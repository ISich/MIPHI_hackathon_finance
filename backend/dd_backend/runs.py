"""Run / CheckRun / Report lifecycle: creation with immutable snapshots, events, reads.

Status (QUEUED/RUNNING/COMPLETED/FAILED) is separate from stage.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .db import Database, dumps, loads, new_id, now
from .errors import ApiError, not_found, not_ready
from .registry import PROCEDURE_SLOTS, Registry
from .settings import Settings

STAGES = ("VALIDATING", "NORMALIZING", "COMPARING", "AGGREGATING", "CHECKING", "FINALIZING")
TERMINAL = ("COMPLETED", "FAILED")


def request_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def append_event(con, run_id: str, level: str, message: str, *, stage: str | None = None, substep: str | None = None,
                 processed: int | None = None, total: int | None = None, code_ref: str | None = None,
                 check_run_id: str | None = None) -> int:
    """Insert one event with the next per-run sequence number (inside the caller's write tx)."""
    seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?", (run_id,)).fetchone()[0]
    con.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, seq, now(), check_run_id, stage, substep, level, message[:4000], processed, total, code_ref))
    return seq


class RunService:
    def __init__(self, settings: Settings, db: Database, registry: Registry) -> None:
        self.settings = settings
        self.db = db
        self.registry = registry

    # ------------------------------------------------------------ helpers
    def run_dir(self, run_id: str) -> Path:
        return self.settings.runs_dir / run_id

    def _idempotent(self, owner_id: str, scope: str, key: str | None, body_hash: str) -> str | None:
        if not key:
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header (1..128 chars) for this operation")
        if len(key) > 128:
            raise ApiError(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key is too long")
        row = self.db.one("SELECT request_hash, result_id FROM idempotency WHERE owner_id=? AND scope=? AND key=?",
                          (owner_id, scope, key))
        if row is None:
            return None
        if row["request_hash"] != body_hash:
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different request",
                           {"existing_id": row["result_id"]})
        return row["result_id"]

    @staticmethod
    def _decide_in_tx(con, owner_id: str, scope: str, key: str, body_hash: str) -> str | None:
        """Inside BEGIN IMMEDIATE: replay id, raise 409 on a different body, or None to accept."""
        row = con.execute("SELECT request_hash, result_id FROM idempotency WHERE owner_id=? AND scope=? AND key=?",
                          (owner_id, scope, key)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != body_hash:
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different request",
                           {"existing_id": row["result_id"]})
        return row["result_id"]

    def _snapshot_script(self, owner_id: str, script_id: str, params_override: dict | None, dest: Path) -> dict:
        row = self.registry._script_row(owner_id, script_id)
        code = self.registry.script_code(row)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(code)
        dest.chmod(0o444)
        params = {**loads(row["params_json"]), **(params_override or {})}
        return {"script_id": row["script_id"], "kind": row["kind"], "source": row["source"], "name": row["name"],
                "filename": row["filename"], "builtin_ref": row["builtin_ref"], "script_revision": row["revision"],
                "code_sha256": hashlib.sha256(code).hexdigest(), "params": params}

    def _check_mode(self, snapshots: list[dict]) -> None:
        custom = [s for s in snapshots if s["source"] != "builtin"]
        if custom and not self.settings.custom_execution_enabled:
            raise ApiError(403, "CUSTOM_EXECUTION_DISABLED",
                           "Custom (workspace/file) code execution is disabled in the safe builtin-only mode; "
                           "nothing was started. Use built-in procedures/checks, or ask the operator to enable "
                           "DD_EXECUTION_MODE=sandboxed (kernel sandbox) or trusted-local (loopback only).",
                           {"execution_mode": self.settings.execution_mode,
                            "custom_scripts": [s["script_id"] for s in custom]})

    def _snapshot_checks(self, owner_id: str, checks: list[dict], dest_dir: Path) -> list[dict]:
        selected = []
        for i, ref in enumerate(checks):
            slot = f"check-{i + 1:02d}"
            rel = f"{slot}.py"
            snap = self._snapshot_script(owner_id, ref["script_id"], ref.get("params"), dest_dir / rel)
            snap["slot"] = slot
            snap["snapshot_rel"] = str((dest_dir / rel).relative_to(self.settings.runs_dir))
            selected.append(snap)
        return selected

    # --------------------------------------------------------------- runs
    def create_run(self, owner_id: str, config_id: str, idem_key: str | None) -> tuple[dict, bool]:
        body_hash = request_hash({"op": "create_run", "config_id": config_id})
        existing = self._idempotent(owner_id, "runs", idem_key, body_hash)
        if existing:
            return self.get_run(owner_id, existing), True
        cfg = self.registry.get_configuration(owner_id, config_id)
        dataset = self.registry._dataset_row(owner_id, cfg["dataset_id"])
        revision = self.registry.latest_revision(dataset["dataset_id"])
        run_id, cr_id, report_id = new_id("run"), new_id("chk"), new_id("rep")
        rdir = self.run_dir(run_id)
        try:
            snap_dir = rdir / "snapshot"
            procs = {}
            for slot in PROCEDURE_SLOTS:
                ref = cfg["slots"][slot]
                procs[slot] = self._snapshot_script(owner_id, ref["script_id"], ref.get("params"), snap_dir / f"{slot}.py")
                procs[slot]["snapshot_rel"] = f"{run_id}/snapshot/{slot}.py"
            checks = self._snapshot_checks(owner_id, cfg["checks"], snap_dir / "checks" / cr_id)
            self._check_mode([*procs.values(), *checks])
            before, after = self.registry.dataset_files(dataset)
            inputs = {
                "dataset_id": dataset["dataset_id"], "revision_id": revision["revision_id"],
                "fingerprint": revision["fingerprint"], "mode": dataset["mode"],
                "root": str(self.settings.data_roots[dataset["root"]].resolve()),
                "max_file_bytes": self.settings.max_input_file_bytes,
                "before": {k: str(v) for k, v in sorted(before.items())},
                "after": {k: str(v) for k, v in sorted(after.items())},
            }
            (snap_dir / "inputs.json").write_text(json.dumps(inputs, ensure_ascii=False))
            from .readiness import core_info
            (snap_dir / "config.json").write_text(json.dumps(
                {"config": cfg, "procedures": procs, "checks": checks, "core": core_info()}, ensure_ascii=False, indent=1))
        except BaseException:
            shutil.rmtree(rdir, ignore_errors=True)
            raise
        ts = now()
        replay = None
        try:
            with self.db.tx() as con:
                replay = self._decide_in_tx(con, owner_id, "runs", idem_key, body_hash)
                if replay is None:
                    self._insert_run_tx(con, owner_id, config_id, dataset, revision, run_id, cr_id, report_id,
                                        procs, checks, idem_key, body_hash, ts)
        except BaseException:
            shutil.rmtree(rdir, ignore_errors=True)
            raise
        if replay is not None:  # lost the race to an identical request
            shutil.rmtree(rdir, ignore_errors=True)
            return self.get_run(owner_id, replay), True
        return self.get_run(owner_id, run_id), False

    def _insert_run_tx(self, con, owner_id, config_id, dataset, revision, run_id, cr_id, report_id, procs, checks,
                       idem_key, body_hash, ts) -> None:
        if True:
            con.execute("""INSERT INTO runs(run_id, owner_id, config_id, dataset_id, dataset_revision_id, status,
                           initial_check_run_id, initial_report_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (run_id, owner_id, config_id, dataset["dataset_id"], revision["revision_id"], "QUEUED",
                         cr_id, report_id, ts))
            for slot, s in procs.items():
                con.execute("INSERT INTO run_scripts VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (run_id, slot, s["script_id"], s["kind"], s["source"], s["name"], s["script_revision"],
                             s["code_sha256"], dumps(s["params"]), s["snapshot_rel"]))
            con.execute("INSERT INTO check_runs(check_run_id, run_id, owner_id, report_id, initial, status, selected_json, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?)", (cr_id, run_id, owner_id, report_id, 1, "QUEUED", dumps(checks), ts))
            con.execute("INSERT INTO reports(report_id, run_id, check_run_id, owner_id, status, created_at) VALUES (?,?,?,?,?,?)",
                        (report_id, run_id, cr_id, owner_id, "PENDING", ts))
            con.execute("INSERT INTO jobs(kind, ref_id, status, created_at) VALUES ('DATA_RUN', ?, 'QUEUED', ?)", (run_id, ts))
            con.execute("INSERT INTO idempotency VALUES (?,?,?,?,?,?)", (owner_id, "runs", idem_key, body_hash, run_id, ts))
            append_event(con, run_id, "INFO", f"Run accepted: {len(procs)} procedures, {len(checks)} checks snapshotted")

    def _run_row(self, owner_id: str, run_id: str) -> dict:
        row = self.db.one("SELECT * FROM runs WHERE run_id = ? AND owner_id = ?", (run_id, owner_id))
        if row is None:
            raise not_found("run", run_id)
        return row

    def _run_view(self, r: dict) -> dict:
        report = self.db.one("SELECT status, completeness FROM reports WHERE report_id = ?", (r["initial_report_id"],))
        return {
            "run_id": r["run_id"], "status": r["status"], "stage": r["stage"], "substep": r["substep"],
            "processed": r["processed"], "total": r["total"], "config_id": r["config_id"],
            "dataset_id": r["dataset_id"], "dataset_revision_id": r["dataset_revision_id"],
            "initial_check_run_id": r["initial_check_run_id"], "initial_report_id": r["initial_report_id"],
            "report_status": report["status"] if report else None,
            "checks_completeness": report["completeness"] if report else None,
            "error": {"code": r["error_code"], "message": r["error_message"]} if r["error_code"] else None,
            "created_at": r["created_at"], "started_at": r["started_at"], "finished_at": r["finished_at"],
            "links": {"self": f"/api/runs/{r['run_id']}", "events": f"/api/runs/{r['run_id']}/events",
                      "summary": f"/api/runs/{r['run_id']}/summary", "checks": f"/api/runs/{r['run_id']}/checks",
                      "report": f"/api/reports/{r['initial_report_id']}"},
        }

    def get_run(self, owner_id: str, run_id: str) -> dict:
        return self._run_view(self._run_row(owner_id, run_id))

    def list_runs(self, owner_id: str, limit: int, offset: int) -> dict:
        rows = self.db.all("SELECT * FROM runs WHERE owner_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                           (owner_id, limit, offset))
        total = self.db.one("SELECT COUNT(*) AS n FROM runs WHERE owner_id = ?", (owner_id,))["n"]
        return {"items": [self._run_view(r) for r in rows], "total": total, "limit": limit, "offset": offset}

    def events(self, owner_id: str, run_id: str, after: int, limit: int) -> dict:
        self._run_row(owner_id, run_id)
        rows = self.db.all("SELECT * FROM events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?", (run_id, after, limit))
        items = [{k: r[k] for k in ("seq", "ts", "check_run_id", "stage", "substep", "level", "message", "processed",
                                     "total", "code_ref")} for r in rows]
        return {"items": items, "next_after": items[-1]["seq"] if items else after}

    def code(self, owner_id: str, run_id: str, slot: str) -> dict:
        self._run_row(owner_id, run_id)
        if slot.startswith("check-"):
            run = self._run_row(owner_id, run_id)
            return self.check_run_code(owner_id, run["initial_check_run_id"], slot)
        row = self.db.one("SELECT * FROM run_scripts WHERE run_id = ? AND slot = ?", (run_id, slot))
        if row is None:
            raise not_found("code snapshot", slot)
        return {"run_id": run_id, "slot": slot, "script_id": row["script_id"], "kind": row["kind"],
                "source": row["source"], "name": row["name"], "script_revision": row["script_revision"],
                "code_sha256": row["code_sha256"], "params": loads(row["params_json"]),
                "code": (self.settings.runs_dir / row["snapshot_rel"]).read_text("utf-8")}

    def summary(self, owner_id: str, run_id: str) -> dict:
        r = self._run_row(owner_id, run_id)
        if r["status"] != "COMPLETED":
            raise not_ready("Run summary is available only after the run COMPLETED",
                            {"run_id": run_id, "status": r["status"], "stage": r["stage"]})
        return {"run_id": run_id, "dataset_revision_id": r["dataset_revision_id"], **loads(r["summary_json"]),
                "artifacts": self.artifacts(owner_id, run_id)["items"]}

    def artifacts(self, owner_id: str, run_id: str) -> dict:
        r = self._run_row(owner_id, run_id)
        if r["status"] != "COMPLETED":
            raise not_ready("Artifacts are published only after the run COMPLETED", {"status": r["status"]})
        rows = self.db.all("SELECT artifact_id, kind, rows, bytes, sha256, created_at FROM artifacts WHERE run_id = ? ORDER BY kind", (run_id,))
        for a in rows:
            a["download"] = f"/api/runs/{run_id}/artifacts/{a['artifact_id']}"
        return {"run_id": run_id, "items": rows}

    def artifact_file(self, owner_id: str, run_id: str, artifact_id: str) -> tuple[Path, str]:
        self.artifacts(owner_id, run_id)
        row = self.db.one("SELECT * FROM artifacts WHERE run_id = ? AND artifact_id = ?", (run_id, artifact_id))
        if row is None:
            raise not_found("artifact", artifact_id)
        return self.settings.runs_dir / row["rel_path"], Path(row["rel_path"]).name

    def mart_path(self, owner_id: str, run_id: str) -> Path:
        r = self._run_row(owner_id, run_id)
        if r["status"] != "COMPLETED":
            raise not_ready("Analytics are available only after the run COMPLETED", {"status": r["status"]})
        return self.run_dir(run_id) / "artifacts" / "mart.duckdb"

    # --------------------------------------------------------- check runs
    def create_check_run(self, owner_id: str, run_id: str, checks: list[dict], idem_key: str | None) -> tuple[dict, bool]:
        body_hash = request_hash({"op": "check_run", "run_id": run_id, "checks": checks})
        existing = self._idempotent(owner_id, f"check-runs:{run_id}", idem_key, body_hash)
        if existing:
            return self.get_check_run(owner_id, existing), True
        run = self._run_row(owner_id, run_id)
        if run["status"] != "COMPLETED":
            raise not_ready("Check runs need a COMPLETED data run", {"status": run["status"]})
        seen = set()
        for ref in checks:
            row = self.registry._script_row(owner_id, ref.get("script_id") or "")
            if row["kind"] != "check":
                raise ApiError(422, "SCRIPT_KIND_MISMATCH", "Selected script is not a check", {"script_id": row["script_id"]})
            if row["script_id"] in seen:
                raise ApiError(422, "DUPLICATE_CHECK", "The same check script is selected twice")
            seen.add(row["script_id"])
        cr_id, report_id = new_id("chk"), new_id("rep")
        dest = self.run_dir(run_id) / "snapshot" / "checks" / cr_id
        try:
            selected = self._snapshot_checks(owner_id, checks, dest)
            self._check_mode(selected)
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        ts = now()
        replay = None
        try:
            with self.db.tx() as con:
                replay = self._decide_in_tx(con, owner_id, f"check-runs:{run_id}", idem_key, body_hash)
                if replay is None:
                    self._insert_check_run_tx(con, owner_id, run_id, cr_id, report_id, selected, idem_key, body_hash, ts)
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        if replay is not None:
            shutil.rmtree(dest, ignore_errors=True)
            return self.get_check_run(owner_id, replay), True
        return self.get_check_run(owner_id, cr_id), False

    def _insert_check_run_tx(self, con, owner_id, run_id, cr_id, report_id, selected, idem_key, body_hash, ts) -> None:
        if True:
            con.execute("INSERT INTO check_runs(check_run_id, run_id, owner_id, report_id, initial, status, selected_json, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?)", (cr_id, run_id, owner_id, report_id, 0, "QUEUED", dumps(selected), ts))
            con.execute("INSERT INTO reports(report_id, run_id, check_run_id, owner_id, status, created_at) VALUES (?,?,?,?,?,?)",
                        (report_id, run_id, cr_id, owner_id, "PENDING", ts))
            con.execute("INSERT INTO jobs(kind, ref_id, status, created_at) VALUES ('CHECK_RUN', ?, 'QUEUED', ?)", (cr_id, ts))
            con.execute("INSERT INTO idempotency VALUES (?,?,?,?,?,?)",
                        (owner_id, f"check-runs:{run_id}", idem_key, body_hash, cr_id, ts))
            append_event(con, run_id, "INFO", f"Check run accepted with {len(selected)} checks", check_run_id=cr_id)

    def _check_run_row(self, owner_id: str, cr_id: str) -> dict:
        row = self.db.one("SELECT * FROM check_runs WHERE check_run_id = ? AND owner_id = ?", (cr_id, owner_id))
        if row is None:
            raise not_found("check run", cr_id)
        return row

    def _executions(self, cr_id: str) -> list[dict]:
        rows = self.db.all("SELECT * FROM check_executions WHERE check_run_id = ? ORDER BY slot", (cr_id,))
        return [{"execution_id": e["execution_id"], "slot": e["slot"], "script_id": e["script_id"], "check_id": e["check_id"],
                 "label": e["label"], "params": loads(e["params_json"]), "execution_status": e["execution_status"],
                 "rows_count": e["rows_count"], "diagnostics": loads(e["diagnostics_json"]),
                 "duration_seconds": e["duration_seconds"]} for e in rows]

    def get_check_run(self, owner_id: str, cr_id: str) -> dict:
        c = self._check_run_row(owner_id, cr_id)
        run = self.db.one("SELECT dataset_revision_id FROM runs WHERE run_id = ?", (c["run_id"],))
        return {"check_run_id": cr_id, "run_id": c["run_id"], "dataset_revision_id": run["dataset_revision_id"],
                "report_id": c["report_id"], "initial": bool(c["initial"]), "status": c["status"],
                "selected": [{k: s[k] for k in ("slot", "script_id", "name", "source", "code_sha256", "params")}
                             for s in loads(c["selected_json"])],
                "executions": self._executions(cr_id),
                "error": {"code": c["error_code"], "message": c["error_message"]} if c["error_code"] else None,
                "created_at": c["created_at"], "started_at": c["started_at"], "finished_at": c["finished_at"],
                "links": {"self": f"/api/check-runs/{cr_id}", "report": f"/api/reports/{c['report_id']}"}}

    def check_run_code(self, owner_id: str, cr_id: str, slot: str) -> dict:
        c = self._check_run_row(owner_id, cr_id)
        for s in loads(c["selected_json"]):
            if s["slot"] == slot:
                return {"check_run_id": cr_id, "run_id": c["run_id"], **{k: s[k] for k in (
                    "slot", "script_id", "kind", "source", "name", "script_revision", "code_sha256", "params")},
                    "code": (self.settings.runs_dir / s["snapshot_rel"]).read_text("utf-8")}
        raise not_found("code snapshot", slot)

    # ------------------------------------------------------------ reports
    def _report_row(self, owner_id: str, report_id: str) -> dict:
        row = self.db.one("SELECT * FROM reports WHERE report_id = ? AND owner_id = ?", (report_id, owner_id))
        if row is None:
            raise not_found("report", report_id)
        return row

    def _report_meta(self, r: dict) -> dict:
        run = self.db.one("SELECT dataset_revision_id FROM runs WHERE run_id = ?", (r["run_id"],))
        return {"report_id": r["report_id"], "run_id": r["run_id"], "dataset_revision_id": run["dataset_revision_id"],
                "check_run_id": r["check_run_id"], "status": r["status"], "completeness": r["completeness"],
                "sha256": r["sha256"], "created_at": r["created_at"], "published_at": r["published_at"],
                "links": {"checks": f"/api/reports/{r['report_id']}/checks",
                          "html": f"/api/reports/{r['report_id']}/checks.html",
                          "summary": f"/api/runs/{r['run_id']}/summary"}}

    def get_report(self, owner_id: str, report_id: str) -> dict:
        return self._report_meta(self._report_row(owner_id, report_id))

    def list_reports(self, owner_id: str, run_id: str) -> dict:
        run = self._run_row(owner_id, run_id)
        rows = self.db.all("SELECT * FROM reports WHERE run_id = ? ORDER BY created_at, rowid", (run_id,))
        return {"run_id": run_id, "initial_report_id": run["initial_report_id"], "items": [self._report_meta(r) for r in rows]}

    def report_document(self, owner_id: str, report_id: str) -> dict:
        r = self._report_row(owner_id, report_id)
        if r["status"] != "PUBLISHED":
            raise not_ready("Report is not published", {"report_id": report_id, "status": r["status"]})
        doc = json.loads((self.settings.runs_dir / r["rel_path"]).read_text("utf-8"))
        return doc

    def initial_report_id(self, owner_id: str, run_id: str) -> str:
        return self._run_row(owner_id, run_id)["initial_report_id"]
