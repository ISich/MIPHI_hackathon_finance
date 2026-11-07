"""The single managed worker.

* Claims jobs from SQLite; at most ONE job runs at a time across all workers
  (claim happens inside BEGIN IMMEDIATE and refuses while any job is RUNNING).
* Each data run is ONE child process (``dd_backend.pipeline``), never a process per JSON.
  Each check is executed in its own short child (``dd_backend.check_child``) so that
  timeouts can be enforced and module-level state never leaks between checks.
* Children get a scrubbed environment (no inherited secrets), their own process group,
  rlimits (address space, file size, open files), a wall-clock timeout and capped logs.
  This is NOT a filesystem/network sandbox.
* On start, jobs left RUNNING by a dead worker are deterministically marked FAILED
  with code RUN_INTERRUPTED; QUEUED jobs stay queued and are executed.
"""
from __future__ import annotations

import json
import logging
import os
import resource
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .db import Database, dumps, loads, new_id, now
from .runs import append_event
from .settings import BACKEND_DIR, Settings

log = logging.getLogger("dd_backend.worker")

POLL_SECONDS = 0.2
PR_SET_PDEATHSIG = 1
try:
    import ctypes
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True) if sys.platform.startswith("linux") else None
except OSError:  # pragma: no cover
    _LIBC = None
HEARTBEAT_SECONDS = 2.0


def _age_seconds(ts: str | None) -> float:
    if not ts:
        return float("inf")
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Worker:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.worker_id = new_id("wrk")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hb_thread: threading.Thread | None = None
        self._current: dict[str, Any] = {}
        self._child: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------- lifecycle
    def _register(self) -> None:
        ts = now()
        with self.db.tx() as con:
            con.execute("INSERT INTO workers VALUES (?,?,?,?,?)", (self.worker_id, os.getpid(), socket.gethostname(), ts, ts))
        self.recover()

    def start_thread(self) -> None:
        self._register()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="dd-heartbeat", daemon=True)
        self._hb_thread.start()
        self._thread = threading.Thread(target=self._loop, name="dd-worker", daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        self._register()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="dd-heartbeat", daemon=True)
        self._hb_thread.start()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self._stop.set())
        self._loop()
        self._shutdown()

    def stop(self) -> None:
        self._stop.set()
        self._kill_child()
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._shutdown()

    def _shutdown(self) -> None:
        with self.db.tx() as con:
            con.execute("DELETE FROM workers WHERE worker_id = ?", (self.worker_id,))
        # A job still marked RUNNING by us was interrupted by shutdown: fail it explicitly.
        self.recover(include_self=True)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            self.heartbeat()

    def heartbeat(self) -> None:
        ts = now()
        try:
            with self.db.tx() as con:
                con.execute("UPDATE workers SET heartbeat_at = ? WHERE worker_id = ?", (ts, self.worker_id))
                cur = self._current
                if cur.get("kind") == "DATA_RUN":
                    con.execute("UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (ts, cur["ref"]))
                elif cur.get("kind") == "CHECK_RUN":
                    con.execute("UPDATE check_runs SET heartbeat_at = ? WHERE check_run_id = ?", (ts, cur["ref"]))
        except Exception:  # never kill the heartbeat thread
            log.exception("heartbeat failed")

    # ------------------------------------------------------------ recovery
    def recover(self, include_self: bool = False) -> list[str]:
        """Fail jobs whose worker is gone. Deterministic: RUNNING -> FAILED/RUN_INTERRUPTED."""
        failed: list[str] = []
        host = socket.gethostname()
        with self.db.tx() as con:
            workers = {r["worker_id"]: dict(r) for r in con.execute("SELECT * FROM workers")}

            def dead(worker_id: str | None, heartbeat: str | None) -> bool:
                if worker_id == self.worker_id:
                    return include_self
                w = workers.get(worker_id or "")
                if w is None:
                    return True
                if w["hostname"] == host and not _pid_alive(w["pid"]):
                    return True
                return _age_seconds(w["heartbeat_at"]) > self.settings.worker_lease_seconds

            for job in con.execute("SELECT * FROM jobs WHERE status = 'RUNNING'").fetchall():
                if job["kind"] == "DATA_RUN":
                    row = con.execute("SELECT worker_id, heartbeat_at FROM runs WHERE run_id = ?", (job["ref_id"],)).fetchone()
                else:
                    row = con.execute("SELECT worker_id, heartbeat_at FROM check_runs WHERE check_run_id = ?",
                                      (job["ref_id"],)).fetchone()
                if row is None or not dead(row["worker_id"], row["heartbeat_at"]):
                    continue
                msg = "Worker stopped while the job was running; job marked FAILED (not resumed automatically)"
                if job["kind"] == "DATA_RUN":
                    self._fail_run_tx(con, job["ref_id"], "RUN_INTERRUPTED", msg)
                else:
                    self._fail_check_run_tx(con, job["ref_id"], "RUN_INTERRUPTED", msg)
                con.execute("UPDATE jobs SET status = 'DONE' WHERE job_seq = ?", (job["job_seq"],))
                failed.append(job["ref_id"])
            con.execute("DELETE FROM workers WHERE worker_id <> ? AND (julianday('now') - julianday(heartbeat_at)) * 86400 > ?",
                        (self.worker_id, self.settings.worker_lease_seconds * 4))
        return failed

    # --------------------------------------------------------------- claim
    def claim(self) -> dict | None:
        with self.db.tx() as con:
            if con.execute("SELECT 1 FROM jobs WHERE status = 'RUNNING' LIMIT 1").fetchone():
                return None  # global concurrency = 1
            job = con.execute("SELECT * FROM jobs WHERE status = 'QUEUED' ORDER BY job_seq LIMIT 1").fetchone()
            if job is None:
                return None
            ts = now()
            con.execute("UPDATE jobs SET status = 'RUNNING' WHERE job_seq = ?", (job["job_seq"],))
            if job["kind"] == "DATA_RUN":
                con.execute("UPDATE runs SET status='RUNNING', started_at=?, worker_id=?, heartbeat_at=? WHERE run_id=?",
                            (ts, self.worker_id, ts, job["ref_id"]))
                append_event(con, job["ref_id"], "INFO", f"Run started by worker {self.worker_id}")
            else:
                con.execute("UPDATE check_runs SET status='RUNNING', started_at=?, worker_id=?, heartbeat_at=? WHERE check_run_id=?",
                            (ts, self.worker_id, ts, job["ref_id"]))
                run_id = con.execute("SELECT run_id FROM check_runs WHERE check_run_id = ?", (job["ref_id"],)).fetchone()[0]
                append_event(con, run_id, "INFO", "Check run started", check_run_id=job["ref_id"], stage="CHECKING")
            return dict(job)

    def _loop(self) -> None:
        last_recover = time.monotonic()
        while not self._stop.is_set():
            try:
                if time.monotonic() - last_recover > self.settings.worker_lease_seconds:
                    self.recover()
                    last_recover = time.monotonic()
                job = self.claim()
                if job is None:
                    self._stop.wait(POLL_SECONDS)
                    continue
                self._current = {"kind": job["kind"], "ref": job["ref_id"]}
                try:
                    if job["kind"] == "DATA_RUN":
                        self.execute_data_run(job["ref_id"])
                    else:
                        self.execute_check_run(job["ref_id"])
                except Exception:
                    # Never leave a job RUNNING forever: fail it explicitly, details only in the server log.
                    log.exception("job %s %s failed inside the worker", job["kind"], job["ref_id"])
                    self._fail_job(job, "WORKER_ERROR", "Internal worker error; see server log for this run id")
                finally:
                    self._current = {}
                    if not self._stop.is_set():
                        with self.db.tx() as con:
                            con.execute("UPDATE jobs SET status = 'DONE' WHERE job_seq = ?", (job["job_seq"],))
            except Exception:
                log.exception("worker loop error")
                self._stop.wait(1.0)

    # ------------------------------------------------------- child process
    def _sanitize(self, text: str) -> str:
        for real, alias in ((str(self.settings.runs_dir), "<runs>"), (str(self.settings.home), "<home>"),
                            (sys.prefix, "<venv>"), (str(BACKEND_DIR), "<backend>"), (str(Path.home()), "<user-home>")):
            text = text.replace(real, alias)
        return text

    def _child_env(self, workdir: Path) -> dict[str, str]:
        tmp = workdir / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        # Built from scratch: nothing from the server environment (tokens, keys, DD_* paths) is inherited.
        return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": str(workdir),
                "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1"}

    def _limits(self) -> Callable[[], None]:
        mem = self.settings.max_memory_mb * 1024 * 1024
        fsize = self.settings.max_output_bytes

        def apply() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            os.umask(0o077)
            if _LIBC is not None:  # Linux: child dies with the worker instead of running orphaned
                _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
        return apply

    def _kill_child(self) -> None:
        with self._lock:
            child = self._child
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)  # own process group only (start_new_session)
            except ProcessLookupError:
                pass

    def spawn(self, argv: list[str], *, workdir: Path, timeout: float, log_path: Path,
              on_event: Callable[[dict], None] | None = None) -> tuple[int | None, bool]:
        """Run a child; returns (returncode, timed_out). Logs are capped at max_log_bytes."""
        workdir.mkdir(parents=True, exist_ok=True)
        ev_r, ev_w = os.pipe()
        cmd = [sys.executable, "-I", "-m", *argv]
        if on_event is not None:
            cmd.append(str(ev_w))
        child = subprocess.Popen(
            cmd, cwd=workdir, env=self._child_env(workdir), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, pass_fds=(ev_w,) if on_event else (),
            start_new_session=True, preexec_fn=self._limits(), close_fds=True,
        )
        os.close(ev_w)
        with self._lock:
            self._child = child
        log_budget = self.settings.max_log_bytes
        truncated = False
        deadline = time.monotonic() + timeout
        timed_out = False
        sel = selectors.DefaultSelector()
        sel.register(child.stdout, selectors.EVENT_READ, "log")
        ev_file = os.fdopen(ev_r, "rb", buffering=0)
        sel.register(ev_file, selectors.EVENT_READ, "ev")
        buf = b""
        open_streams = 2
        with log_path.open("ab") as logf:
            while open_streams:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._kill_child()
                    break
                if self._stop.is_set():
                    self._kill_child()
                    break
                for key, _ in sel.select(timeout=min(remaining, 0.5)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        open_streams -= 1
                        continue
                    if key.data == "log":
                        if log_budget > 0:
                            logf.write(chunk[:log_budget])
                            log_budget -= len(chunk)
                        elif not truncated:
                            truncated = True
                            logf.write(b"\n[log truncated: limit reached]\n")
                    else:
                        buf += chunk
                        if len(buf) > 4 * 1024 * 1024:  # protocol flood -> kill
                            self._kill_child()
                            buf = b""
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            try:
                                payload = json.loads(line)
                            except ValueError:
                                continue
                            if on_event is not None and isinstance(payload, dict):
                                on_event(payload)
        sel.close()
        ev_file.close()
        child.stdout.close()
        try:
            rc = child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._kill_child()
            rc = child.wait()
        with self._lock:
            self._child = None
        return (None if timed_out else rc), timed_out

    # ------------------------------------------------------------ data run
    def _fail_run_tx(self, con, run_id: str, code: str, message: str) -> None:
        ts = now()
        con.execute("UPDATE runs SET status='FAILED', error_code=?, error_message=?, finished_at=? WHERE run_id=?",
                    (code, message[:2000], ts, run_id))
        r = con.execute("SELECT stage, initial_check_run_id, initial_report_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        con.execute("UPDATE check_runs SET status='FAILED', error_code='DATA_RUN_FAILED', error_message=?, finished_at=? "
                    "WHERE check_run_id=? AND status NOT IN ('COMPLETED','FAILED')", (f"data run failed: {code}", ts, r[1]))
        con.execute("UPDATE reports SET status='FAILED' WHERE report_id=? AND status='PENDING'", (r[2],))
        append_event(con, run_id, "ERROR", f"{code}: {message}", stage=r[0])

    def _fail_job(self, job: dict, code: str, message: str) -> None:
        with self.db.tx() as con:
            if job["kind"] == "DATA_RUN":
                row = con.execute("SELECT status FROM runs WHERE run_id=?", (job["ref_id"],)).fetchone()
                if row and row[0] not in ("COMPLETED", "FAILED"):
                    self._fail_run_tx(con, job["ref_id"], code, message)
            else:
                row = con.execute("SELECT status FROM check_runs WHERE check_run_id=?", (job["ref_id"],)).fetchone()
                if row and row[0] not in ("COMPLETED", "FAILED"):
                    self._fail_check_run_tx(con, job["ref_id"], code, message)

    def _fail_check_run_tx(self, con, cr_id: str, code: str, message: str) -> None:
        ts = now()
        c = con.execute("SELECT run_id, report_id FROM check_runs WHERE check_run_id=?", (cr_id,)).fetchone()
        con.execute("UPDATE check_runs SET status='FAILED', error_code=?, error_message=?, finished_at=? WHERE check_run_id=?",
                    (code, message[:2000], ts, cr_id))
        con.execute("UPDATE reports SET status='FAILED' WHERE report_id=? AND status='PENDING'", (c[1],))
        append_event(con, c[0], "ERROR", f"{code}: {message}", check_run_id=cr_id, stage="CHECKING")

    def _set_stage(self, run_id: str, stage: str, substep: str | None, message: str, code_ref: str | None = None,
                   check_run_id: str | None = None) -> None:
        with self.db.tx() as con:
            con.execute("UPDATE runs SET stage=?, substep=?, processed=NULL, total=NULL WHERE run_id=?", (stage, substep, run_id))
            append_event(con, run_id, "INFO", message, stage=stage, substep=substep, code_ref=code_ref, check_run_id=check_run_id)

    def execute_data_run(self, run_id: str) -> None:
        settings = self.settings
        rdir = settings.runs_dir / run_id
        cfg = json.loads((rdir / "snapshot" / "config.json").read_text("utf-8"))
        custom = [s for s in [*cfg["procedures"].values(), *cfg["checks"]] if s["source"] != "builtin"]
        if custom and settings.execution_mode != "trusted-local":
            with self.db.tx() as con:
                self._fail_run_tx(con, run_id, "CUSTOM_EXECUTION_DISABLED",
                                  "Run contains custom code but the worker runs in builtin-only mode; nothing executed")
            return
        state: dict[str, Any] = {"stage": None, "substep": None, "result": None, "error": None}

        def on_event(p: dict) -> None:
            kind = p.get("type")
            if kind == "stage":
                state["stage"], state["substep"] = p.get("stage"), p.get("substep")
                self._set_stage(run_id, p["stage"], p.get("substep"), self._sanitize(str(p.get("message", ""))), p.get("code_ref"))
            elif kind in ("event", "progress"):
                processed, total = p.get("processed"), p.get("total")
                with self.db.tx() as con:
                    if kind == "progress":
                        con.execute("UPDATE runs SET processed=?, total=? WHERE run_id=?", (processed, total, run_id))
                    append_event(con, run_id, p.get("level", "INFO"), self._sanitize(str(p.get("message", ""))),
                                 stage=state["stage"], substep=state["substep"], processed=processed, total=total)
            elif kind == "result":
                state["result"] = p
            elif kind == "error":
                state["error"] = p

        rc, timed_out = self.spawn(["dd_backend.pipeline", str(rdir)], workdir=rdir / "work",
                                   timeout=settings.run_timeout_seconds, log_path=rdir / "pipeline.log", on_event=on_event)
        if self._stop.is_set() and state["result"] is None:
            return  # shutdown: recover(include_self=True) marks it interrupted
        if timed_out:
            with self.db.tx() as con:
                self._fail_run_tx(con, run_id, "TIMEOUT", f"Pipeline exceeded {settings.run_timeout_seconds}s and was killed")
            return
        if state["error"] is not None or rc != 0 or state["result"] is None:
            err = state["error"] or {}
            code = err.get("code") or ("KILLED_BY_LIMIT" if rc is not None and rc < 0 else "PIPELINE_CRASHED")
            message = err.get("message") or f"pipeline exited with code {rc}; see owner log"
            with self.db.tx() as con:
                self._fail_run_tx(con, run_id, code, self._sanitize(message))
                if err.get("traceback"):
                    append_event(con, run_id, "DEBUG", self._sanitize(err["traceback"]), stage=state["stage"])
            return
        result = state["result"]
        total_bytes = sum(a["bytes"] for a in result["artifacts"])
        if total_bytes > settings.max_output_bytes:
            with self.db.tx() as con:
                self._fail_run_tx(con, run_id, "OUTPUT_LIMIT", f"Artifacts total {total_bytes} bytes exceed the limit")
            return
        with self.db.tx() as con:
            for a in result["artifacts"]:
                con.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
                            (new_id("art"), run_id, a["kind"], f"{run_id}/artifacts/{a['file']}", a["rows"], a["bytes"],
                             a["sha256"], now()))
            con.execute("UPDATE runs SET summary_json=? WHERE run_id=?", (dumps(result["summary"]), run_id))
        for p in (rdir / "artifacts").iterdir():
            p.chmod(0o444)
        run = self.db.one("SELECT initial_check_run_id FROM runs WHERE run_id=?", (run_id,))
        ok = self._run_checks(run_id, run["initial_check_run_id"], initial=True)
        if not ok:
            return
        self._set_stage(run_id, "FINALIZING", None, "Publishing run and initial report")
        with self.db.tx() as con:
            con.execute("UPDATE runs SET status='COMPLETED', finished_at=? WHERE run_id=?", (now(), run_id))
            append_event(con, run_id, "INFO", "Run COMPLETED", stage="FINALIZING")

    # ------------------------------------------------------------- checks
    def execute_check_run(self, cr_id: str) -> None:
        c = self.db.one("SELECT run_id FROM check_runs WHERE check_run_id=?", (cr_id,))
        self._run_checks(c["run_id"], cr_id, initial=False)

    def _run_checks(self, run_id: str, cr_id: str, *, initial: bool) -> bool:
        """Registration + per-check execution + immutable report publication. Returns False on hard failure."""
        settings = self.settings
        c = self.db.one("SELECT * FROM check_runs WHERE check_run_id=?", (cr_id,))
        selected = loads(c["selected_json"])
        if initial:
            self._set_stage(run_id, "CHECKING", None, f"Executing {len(selected)} checks (check_run {cr_id})",
                            check_run_id=cr_id)
            with self.db.tx() as con:
                con.execute("UPDATE check_runs SET status='RUNNING', started_at=?, worker_id=?, heartbeat_at=? WHERE check_run_id=?",
                            (now(), self.worker_id, now(), cr_id))
        custom = [s for s in selected if s["source"] != "builtin"]
        if custom and settings.execution_mode != "trusted-local":
            with self.db.tx() as con:
                self._fail_check_run_tx(con, cr_id, "CUSTOM_EXECUTION_DISABLED",
                                        "Custom checks are disabled in builtin-only mode; nothing executed")
                if initial:
                    self._fail_run_tx(con, run_id, "CUSTOM_EXECUTION_DISABLED", "Custom checks disabled")
            return False
        rdir = settings.runs_dir / run_id
        mart = rdir / "artifacts" / "mart.duckdb"
        cdir = rdir / "checks" / cr_id
        cdir.mkdir(parents=True, exist_ok=True)
        executions: list[dict] = []
        seen_ids: dict[str, str] = {}
        for s in selected:
            if self._stop.is_set():
                return False
            ex = {"execution_id": new_id("exe"), "slot": s["slot"], "script_id": s["script_id"], "check_id": None,
                  "label": None, "params": s["params"], "execution_status": None, "diagnostics": [], "rows": [],
                  "duration_seconds": None}
            executions.append(ex)
            path = settings.runs_dir / s["snapshot_rel"]
            reg_out = cdir / f"{s['slot']}.register.json"
            started = time.monotonic()
            rc, timed_out = self.spawn(["dd_backend.check_child", "register", str(path), str(reg_out)],
                                       workdir=cdir / "work", timeout=settings.check_timeout_seconds,
                                       log_path=cdir / f"{s['slot']}.log")
            if timed_out:
                ex.update(execution_status="TIMEOUT", diagnostics=[{"error_type": "Timeout", "message": "check import timed out"}])
                continue
            reg = json.loads(reg_out.read_text("utf-8")) if reg_out.exists() else None
            if reg is None:
                ex.update(execution_status="ERROR", diagnostics=[{"error_type": "ChildCrashed",
                                                                  "message": f"registration exited with {rc}"}])
                continue
            if not reg["ok"]:
                ex.update(execution_status=reg["status"], diagnostics=[{"error_type": reg["error_type"],
                                                                        "message": self._sanitize(reg["message"])}])
                continue
            ex.update(check_id=reg["id"], label=reg["label"])
            if reg["id"] in seen_ids:
                ex.update(execution_status="DUPLICATE_ID", diagnostics=[{
                    "error_type": "DuplicateCheckId",
                    "message": f"CHECK.id {reg['id']!r} already registered by {seen_ids[reg['id']]}; not executed"}])
                continue
            seen_ids[reg["id"]] = s["slot"]
            ex["params"] = {**reg["params"], **s["params"]}
            overrides = cdir / f"{s['slot']}.params.json"
            overrides.write_text(json.dumps({reg["id"]: s["params"]}))
            run_out = cdir / f"{s['slot']}.result.json"
            rc, timed_out = self.spawn(["dd_backend.check_child", "run", str(path), str(mart), str(overrides), str(run_out)],
                                       workdir=cdir / "work", timeout=settings.check_timeout_seconds,
                                       log_path=cdir / f"{s['slot']}.log")
            ex["duration_seconds"] = round(time.monotonic() - started, 3)
            if timed_out:
                ex.update(execution_status="TIMEOUT", diagnostics=[{
                    "error_type": "Timeout", "message": f"check exceeded {settings.check_timeout_seconds}s and was killed"}])
                continue
            res = json.loads(run_out.read_text("utf-8")) if run_out.exists() else None
            if res is None:
                ex.update(execution_status="ERROR", diagnostics=[{"error_type": "ChildCrashed",
                                                                  "message": f"check process exited with {rc}"}])
                continue
            ex.update(execution_status=res["status"], rows=res["rows"],
                      diagnostics=[{**d, "message": self._sanitize(str(d.get("message", ""))),
                                    "file": s["slot"] + ".py"} for d in res["diagnostics"]])
        return self._publish_report(run_id, cr_id, executions, initial=initial)

    def _publish_report(self, run_id: str, cr_id: str, executions: list[dict], *, initial: bool) -> bool:
        c = self.db.one("SELECT report_id FROM check_runs WHERE check_run_id=?", (cr_id,))
        run = self.db.one("SELECT summary_json, dataset_revision_id FROM runs WHERE run_id=?", (run_id,))
        summary = loads(run["summary_json"])
        if not executions:
            completeness = "NO_CHECKS_SELECTED"
        elif all(e["execution_status"] == "SUCCEEDED" for e in executions):
            completeness = "COMPLETE"
        else:
            completeness = "INCOMPLETE"
        report_id = c["report_id"]
        # D4 checks_report.json shape (consumed by decision_diff.html_report) + identity metadata.
        doc = {
            "report_id": report_id, "run_id": run_id, "check_run_id": cr_id,
            "dataset_revision_id": run["dataset_revision_id"], "completeness": completeness,
            "summary": {k: summary[k] for k in ("total_apps", "changed_apps", "decision_changed_apps")},
            "checks": [row for e in executions for row in e["rows"]],
            "diagnostics": [{"check": e["check_id"] or e["slot"], **d} for e in executions for d in e["diagnostics"]],
            "timings_seconds": {e["check_id"] or e["slot"]: e["duration_seconds"] for e in executions},
            "executions": [{k: e[k] for k in ("execution_id", "slot", "script_id", "check_id", "label", "params",
                                              "execution_status", "duration_seconds")} | {"rows_count": len(e["rows"])}
                           for e in executions],
        }
        rel = f"{run_id}/reports/{report_id}.json"
        target = self.settings.runs_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(doc, ensure_ascii=False, indent=1, default=str).encode()
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        target.chmod(0o444)
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        ts = now()
        with self.db.tx() as con:
            for e in executions:
                con.execute("INSERT INTO check_executions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (e["execution_id"], cr_id, e["slot"], e["script_id"], e["check_id"], e["label"],
                             dumps(e["params"]), e["execution_status"], dumps(e["diagnostics"]), len(e["rows"]),
                             e["duration_seconds"]))
            con.execute("UPDATE reports SET status='PUBLISHED', completeness=?, rel_path=?, sha256=?, published_at=? "
                        "WHERE report_id=?", (completeness, rel, sha, ts, report_id))
            con.execute("UPDATE check_runs SET status='COMPLETED', finished_at=? WHERE check_run_id=?", (ts, cr_id))
            failed = sum(1 for e in executions if e["execution_status"] != "SUCCEEDED")
            business_fail = sum(1 for e in executions for r in e["rows"] if r.get("RESULT") == "FAIL")
            append_event(con, run_id, "WARN" if failed else "INFO",
                         f"Report {report_id} published: {len(executions)} checks, {failed} execution problems, "
                         f"{business_fail} business FAIL rows, completeness={completeness}",
                         stage="CHECKING", check_run_id=cr_id)
        return True


def clean_run_dir(settings: Settings, run_id: str) -> None:  # pragma: no cover - manual maintenance helper
    shutil.rmtree(settings.runs_dir / run_id, ignore_errors=True)
