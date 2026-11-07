"""Registry of datasets (allowlisted roots), scripts and run configurations."""
from __future__ import annotations

import hashlib
import inspect
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .db import Database, dumps, loads, new_id, now
from .errors import ApiError, not_found
from .settings import Settings

# ---------------------------------------------------------------------------
# Script kinds: team-proposed contract (PRD §8.1 "A"), not organizer signatures.
# ---------------------------------------------------------------------------

NORMALIZED_COLUMNS = ["APP_ID", "SOURCE", "PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH", "VALUE", "ADJUSTED_VALUE"]
COMPARISON_COLUMNS = ["APP_ID", "PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH", "VALUE_BEFORE", "VALUE_AFTER",
                      "ADJUSTED_BEFORE", "ADJUSTED_AFTER", "DIFF_FLAG", "CHANGE_TYPE"]
SEGMENT_COLUMNS = ["APP_ID", "DECISION_BEFORE", "DECISION_AFTER", "DECISION_CHANGED", "PRODUCTS", "TOP_OFFER_BEFORE",
                   "TOP_OFFER_AFTER", "PARTNER_TYPE", "ROUTING_METHOD", "PD_MODEL_BEFORE", "PD_MODEL_AFTER",
                   "CUTOFF_BEFORE", "CUTOFF_AFTER", "REJECT_REASON_BEFORE", "REJECT_REASON_AFTER",
                   "SCORE_OKB_BEFORE", "SCORE_OKB_AFTER"]
PIVOT_COLUMNS = ["PREFIX", "CLASS", "SUFFIX", "ARRAY_KEY", "KEY", "PATH", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE", "CNT"]

PROCEDURE_SLOTS = ("normalize", "compare", "segments", "aggregate")

SCRIPT_KINDS: dict[str, dict[str, Any]] = {
    "normalize": {
        "entrypoint": "normalize(document: dict, app_id: str, source: 'BEFORE'|'AFTER', params: dict) -> list[dict]",
        "output_columns": NORMALIZED_COLUMNS,
        "template": (
            "def normalize(document, app_id, source, params):\n"
            "    \"\"\"Return one row per leaf with the normalized columns.\"\"\"\n"
            "    rows = []\n"
            "    return rows\n"
        ),
        "example": (
            "from decision_diff.core import normalize as core_normalize\n"
            "from decision_diff.configs import REAL\n\n"
            "def normalize(document, app_id, source, params):\n"
            "    return core_normalize(document, app_id, source, REAL)\n"
        ),
    },
    "compare": {
        "entrypoint": "compare(before_rows: list[dict], after_rows: list[dict], params: dict) -> list[dict]",
        "output_columns": COMPARISON_COLUMNS,
        "template": "def compare(before_rows, after_rows, params):\n    return []\n",
        "example": (
            "from decision_diff.core import compare as core_compare\n\n"
            "def compare(before_rows, after_rows, params):\n"
            "    return core_compare(before_rows, after_rows)\n"
        ),
    },
    "segments": {
        "entrypoint": "build_segment(before_doc: dict, after_doc: dict, app_id: str, params: dict) -> dict",
        "output_columns": SEGMENT_COLUMNS,
        "template": "def build_segment(before_doc, after_doc, app_id, params):\n    return {'APP_ID': app_id}\n",
        "example": (
            "from decision_diff.segments import build_segment as core_segment\n\n"
            "def build_segment(before_doc, after_doc, app_id, params):\n"
            "    return core_segment(before_doc, after_doc, app_id)\n"
        ),
    },
    "aggregate": {
        "entrypoint": "aggregate(comparison_rows: list[dict], segments: list[dict], params: dict) -> {'pivot_facts': list[dict], 'summary': dict}",
        "output_columns": PIVOT_COLUMNS,
        "template": "def aggregate(comparison_rows, segments, params):\n    return {'pivot_facts': [], 'summary': {}}\n",
        "example": (
            "from decision_diff.reporting import pivot_facts, summarize\n\n"
            "def aggregate(comparison_rows, segments, params):\n"
            "    return {'pivot_facts': pivot_facts(comparison_rows), 'summary': summarize(comparison_rows, segments)}\n"
        ),
    },
    "check": {
        "entrypoint": "CHECK = {'id', 'label', 'params', 'entrypoint': run}; run(mart, params) -> list[dict]",
        "output_columns": ["LABEL", "SOURCE", "ARGUMENT", "CNT", "TOTAL", "METRIC", "APP_IDS", "RESULT", "CONFIDENCE"],
        "template": (
            "DEFAULTS = {}\n\n"
            "def run(mart, params=None):\n"
            "    p = {**DEFAULTS, **(params or {})}\n"
            "    return []\n\n"
            "CHECK = {'id': 'my_check', 'label': 'My check', 'params': DEFAULTS, 'entrypoint': run}\n"
        ),
        "example": (
            "def run(mart, params=None):\n"
            "    total = mart.total_apps()\n"
            "    changed = mart.app_ids(diff_flag=1)\n"
            "    share = len(changed) / total if total else 0.0\n"
            "    return [{'LABEL': CHECK['label'], 'SOURCE': 'AFTER', 'ARGUMENT': 'all', 'CNT': len(changed),\n"
            "             'TOTAL': total, 'METRIC': round(share, 4), 'APP_IDS': changed[:20],\n"
            "             'RESULT': 'FAIL' if share > params['max_share'] else 'PASS',\n"
            "             'CONFIDENCE': 'HIGH' if total >= 30 else 'LOW'}]\n\n"
            "CHECK = {'id': 'changed_share', 'label': 'Share of changed apps', 'params': {'max_share': 0.5}, 'entrypoint': run}\n"
        ),
    },
}

# Built-in procedures map to functions of the pinned decision_diff package.
BUILTIN_PROCEDURES: dict[str, dict[str, Any]] = {
    "builtin:normalize": {"kind": "normalize", "name": "decision_diff.core.normalize", "module": "decision_diff.core",
                          "params": {"config": "real"}},
    "builtin:compare": {"kind": "compare", "name": "decision_diff.core.compare", "module": "decision_diff.core",
                        "params": {}},
    "builtin:segments": {"kind": "segments", "name": "decision_diff.segments.build_segment",
                         "module": "decision_diff.segments", "params": {}},
    "builtin:aggregate": {"kind": "aggregate", "name": "decision_diff.reporting.pivot_facts+summarize",
                          "module": "decision_diff.reporting", "params": {}},
}
BUILTIN_CONFIG_NAMES = ("real", "teaching")

_NAME_RE = re.compile(r"^[\w .\-()\[\]]{1,120}$", re.UNICODE)
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}\.py$")


NORMALIZE_PARAM_KEYS = {"config", "excluded_paths", "arrays"}
ARRAY_MODES = ("fields", "index", "value")


def preset_to_json(cfg) -> dict:
    return {
        "excluded_paths": sorted(cfg.excluded_paths),
        "arrays": {path: {"mode": r.mode, "keys": list(r.keys), "scalar_suffix": r.scalar_suffix}
                   for path, r in sorted(cfg.arrays.items())},
        "buckets": {path: [list(b) for b in bounds] for path, bounds in sorted(cfg.buckets.items())},
        "display_suffixes": dict(sorted(cfg.display_suffixes.items())),
    }


def normalize_presets() -> dict:
    from decision_diff import configs
    return {"real": preset_to_json(configs.REAL), "teaching": preset_to_json(configs.TEACHING)}


def validate_normalize_params(params: dict) -> None:
    unknown = set(params) - NORMALIZE_PARAM_KEYS
    if unknown:
        raise ApiError(422, "PARAMS_INVALID", "Unknown builtin normalize params", {"unknown": sorted(unknown),
                       "allowed": sorted(NORMALIZE_PARAM_KEYS)})
    if params.get("config") not in BUILTIN_CONFIG_NAMES:
        raise ApiError(422, "PARAMS_INVALID", "builtin normalize params.config must be one of " + ", ".join(BUILTIN_CONFIG_NAMES))
    ex = params.get("excluded_paths")
    if ex is not None and not (isinstance(ex, list) and all(isinstance(x, str) and x for x in ex) and len(ex) <= 1000):
        raise ApiError(422, "PARAMS_INVALID", "excluded_paths must be a list of non-empty strings")
    arrays = params.get("arrays")
    if arrays is not None:
        if not isinstance(arrays, dict) or len(arrays) > 1000:
            raise ApiError(422, "PARAMS_INVALID", "arrays must be an object {path: rule}")
        for path, rule in arrays.items():
            ok = (isinstance(rule, dict) and set(rule) <= {"mode", "keys", "scalar_suffix"} and rule.get("mode") in ARRAY_MODES
                  and isinstance(rule.get("keys", []), list) and all(isinstance(k, str) for k in rule.get("keys", []))
                  and isinstance(rule.get("scalar_suffix", ""), str))
            if not ok or (rule["mode"] == "fields" and not rule.get("keys")):
                raise ApiError(422, "PARAMS_INVALID", "Invalid array rule", {"path": path, "modes": list(ARRAY_MODES)})


def declared_check_params(code: bytes):
    """Static (AST, no execution) extraction of CHECK['params'] when it is a literal or a literal-bound name."""
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    names: dict[str, ast.AST] = {}
    check = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            names[node.targets[0].id] = node.value
            if node.targets[0].id == "CHECK" and isinstance(node.value, ast.Dict):
                check = node.value
    if check is None:
        return None
    for k, v in zip(check.keys, check.values):
        if isinstance(k, ast.Constant) and k.value == "params":
            if isinstance(v, ast.Name):
                v = names.get(v.id)
            try:
                value = ast.literal_eval(v)
            except (ValueError, TypeError, SyntaxError, RecursionError):
                return None
            return value if isinstance(value, dict) else None
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def builtin_source(module_name: str) -> str:
    import importlib
    return inspect.getsource(importlib.import_module(module_name))


class Registry:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    # ----------------------------------------------------------- datasets
    def resolve_in_root(self, root: str, rel: str) -> Path:
        """Resolve a client-supplied relative path strictly inside an allowlisted root.

        Rejects absolute paths, traversal and symlinks that escape the root.
        """
        if root not in self.settings.data_roots:
            raise ApiError(422, "DATASET_ROOT_NOT_ALLOWED", "Unknown data root", {"root": root,
                           "allowed_roots": sorted(self.settings.data_roots)})
        if not isinstance(rel, str) or not rel or "\x00" in rel or len(rel) > 500:
            raise ApiError(422, "DATASET_PATH_INVALID", "Path must be a non-empty relative path")
        pure = PurePosixPath(rel.replace("\\", "/"))
        if pure.is_absolute() or any(part == ".." for part in pure.parts) or re.match(r"^[A-Za-z]:", rel):
            raise ApiError(422, "DATASET_PATH_INVALID", "Absolute paths and '..' are not allowed", {"path": rel})
        base = self.settings.data_roots[root].resolve()
        try:
            target = (base / pure).resolve(strict=True)
        except (FileNotFoundError, OSError):
            raise ApiError(422, "DATASET_PATH_NOT_FOUND", "Path does not exist in the data root", {"root": root, "path": rel})
        if target != base and base not in target.parents:
            raise ApiError(422, "DATASET_PATH_ESCAPES_ROOT", "Path resolves outside the allowlisted root (symlink?)",
                           {"root": root, "path": rel})
        return target

    def dataset_files(self, ds: dict[str, Any]) -> tuple[dict[str, Path], dict[str, Path]]:
        before = self.resolve_in_root(ds["root"], ds["before_rel"])
        after = self.resolve_in_root(ds["root"], ds["after_rel"])
        base = self.settings.data_roots[ds["root"]].resolve()

        def inside(p: Path) -> Path:
            r = p.resolve()
            if base not in r.parents:
                raise ApiError(422, "DATASET_PATH_ESCAPES_ROOT", "Dataset file resolves outside the root",
                               {"file": p.name})
            return r

        if ds["mode"] == "files":
            if not (before.is_file() and after.is_file()):
                raise ApiError(422, "DATASET_PATH_INVALID", "mode=files requires two JSON files")
            return {"pair.json": before}, {"pair.json": after}
        if not (before.is_dir() and after.is_dir()):
            raise ApiError(422, "DATASET_PATH_INVALID", "mode=dirs requires two directories")
        return ({p.name: inside(p) for p in before.glob("*.json")},
                {p.name: inside(p) for p in after.glob("*.json")})

    def scan_revision(self, ds: dict[str, Any]) -> dict[str, Any]:
        before, after = self.dataset_files(ds)
        digest = hashlib.sha256()
        for side, files in (("BEFORE", before), ("AFTER", after)):
            for name in sorted(files):
                digest.update(f"{side}/{name}\0".encode())
                digest.update(hashlib.sha256(files[name].read_bytes()).digest())
        return {
            "fingerprint": digest.hexdigest(),
            "pairs": len(set(before) & set(after)),
            "missing_before": sorted(set(after) - set(before)),
            "missing_after": sorted(set(before) - set(after)),
        }

    def create_dataset(self, owner_id: str | None, name: str, root: str, mode: str, before: str, after: str) -> dict:
        if not _NAME_RE.match(name or ""):
            raise ApiError(422, "VALIDATION_ERROR", "Invalid dataset name")
        if mode not in ("files", "dirs"):
            raise ApiError(422, "VALIDATION_ERROR", "mode must be 'files' or 'dirs'")
        ds = {"dataset_id": new_id("ds"), "owner_id": owner_id, "name": name, "root": root, "mode": mode,
              "before_rel": before, "after_rel": after, "created_at": now()}
        scan = self.scan_revision(ds)
        if scan["pairs"] == 0:
            raise ApiError(422, "DATASET_EMPTY", "No BEFORE/AFTER JSON pairs found")
        with self.db.tx() as con:
            con.execute("INSERT INTO datasets VALUES (:dataset_id,:owner_id,:name,:root,:mode,:before_rel,:after_rel,:created_at)", ds)
            self._insert_revision(con, ds["dataset_id"], scan)
        return self.get_dataset(owner_id, ds["dataset_id"])

    def _insert_revision(self, con, dataset_id: str, scan: dict) -> str:
        rid = new_id("rev")
        con.execute("INSERT INTO dataset_revisions VALUES (?,?,?,?,?,?,?)",
                    (rid, dataset_id, scan["fingerprint"], scan["pairs"], dumps(scan["missing_before"]),
                     dumps(scan["missing_after"]), now()))
        return rid

    def rescan_dataset(self, owner_id: str, dataset_id: str) -> dict:
        ds = self._dataset_row(owner_id, dataset_id)
        scan = self.scan_revision(ds)
        latest = self.latest_revision(dataset_id)
        if latest is None or latest["fingerprint"] != scan["fingerprint"]:
            with self.db.tx() as con:
                self._insert_revision(con, dataset_id, scan)
        return self.get_dataset(owner_id, dataset_id)

    def _dataset_row(self, owner_id: str | None, dataset_id: str) -> dict:
        row = self.db.one("SELECT * FROM datasets WHERE dataset_id = ? AND (owner_id IS NULL OR owner_id = ?)",
                          (dataset_id, owner_id))
        if row is None:
            raise not_found("dataset", dataset_id)
        return row

    def latest_revision(self, dataset_id: str) -> dict | None:
        return self.db.one("SELECT * FROM dataset_revisions WHERE dataset_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                           (dataset_id,))

    def _dataset_view(self, row: dict) -> dict:
        revs = self.db.all("SELECT * FROM dataset_revisions WHERE dataset_id = ? ORDER BY created_at, rowid", (row["dataset_id"],))
        return {
            "dataset_id": row["dataset_id"], "name": row["name"], "shared": row["owner_id"] is None,
            "root": row["root"], "mode": row["mode"], "before": row["before_rel"], "after": row["after_rel"],
            "created_at": row["created_at"],
            "revisions": [{"revision_id": r["revision_id"], "fingerprint": r["fingerprint"], "pairs": r["pairs"],
                           "missing_before": loads(r["missing_before"]), "missing_after": loads(r["missing_after"]),
                           "created_at": r["created_at"]} for r in revs],
        }

    def get_dataset(self, owner_id: str | None, dataset_id: str) -> dict:
        return self._dataset_view(self._dataset_row(owner_id, dataset_id))

    def list_datasets(self, owner_id: str) -> list[dict]:
        rows = self.db.all("SELECT * FROM datasets WHERE owner_id IS NULL OR owner_id = ? ORDER BY created_at", (owner_id,))
        return [self._dataset_view(r) for r in rows]

    # ------------------------------------------------------------ scripts
    def sync_builtin_scripts(self) -> None:
        """Register built-in procedures and organizer checks (read-only, shared)."""
        entries: list[dict[str, Any]] = []
        for ref, spec in BUILTIN_PROCEDURES.items():
            try:
                code = builtin_source(spec["module"]).encode()
            except Exception:
                continue
            entries.append({"ref": ref, "kind": spec["kind"], "name": spec["name"], "filename": None,
                            "code": code, "params": spec["params"]})
        if self.settings.checks_dir.is_dir():
            for path in sorted(self.settings.checks_dir.glob("check_*.py")):
                code = path.read_bytes()
                # Defaults shown/editable in the UI; effective params stay {**CHECK.params, **these, **config}.
                entries.append({"ref": f"builtin:check:{path.name}", "kind": "check", "name": path.stem,
                                "filename": path.name, "code": code, "params": declared_check_params(code) or {}})
        ts = now()
        with self.db.tx() as con:
            for e in entries:
                sha = sha256_bytes(e["code"])
                rel = f"builtin/{sha}.py"
                target = self.settings.scripts_dir / rel
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(e["code"])
                row = con.execute("SELECT script_id, code_sha256, revision FROM scripts WHERE owner_id IS NULL AND builtin_ref = ?",
                                  (e["ref"],)).fetchone()
                if row is None:
                    con.execute("INSERT INTO scripts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (new_id("scr"), None, e["kind"], "builtin", e["name"], e["filename"], e["ref"], sha, rel,
                                 dumps(e["params"]), 1, ts, ts))
                elif row["code_sha256"] != sha:
                    con.execute("UPDATE scripts SET code_sha256=?, code_rel=?, params_json=?, revision=?, updated_at=? "
                                "WHERE script_id=?", (sha, rel, dumps(e["params"]), row["revision"] + 1, ts, row["script_id"]))

    def builtin_script_id(self, ref: str) -> str | None:
        row = self.db.one("SELECT script_id FROM scripts WHERE owner_id IS NULL AND builtin_ref = ?", (ref,))
        return row["script_id"] if row else None

    def _validate_code(self, kind: str, code: bytes) -> None:
        if kind not in SCRIPT_KINDS:
            raise ApiError(422, "SCRIPT_KIND_INVALID", "Unknown script kind", {"allowed": sorted(SCRIPT_KINDS)})
        if len(code) > self.settings.max_code_bytes:
            raise ApiError(413, "CODE_TOO_LARGE", "Script exceeds the size limit", {"limit_bytes": self.settings.max_code_bytes})
        try:
            text = code.decode("utf-8")
        except UnicodeDecodeError:
            raise ApiError(422, "CODE_INVALID", "Script must be UTF-8 text")
        try:
            compile(text, "<script>", "exec")  # syntax only; nothing is executed in the API process
        except SyntaxError as exc:
            raise ApiError(422, "CODE_SYNTAX_ERROR", "Python syntax error", {"line": exc.lineno, "msg": exc.msg})

    def _store_code(self, owner_id: str, code: bytes) -> tuple[str, str]:
        sha = sha256_bytes(code)
        rel = f"{owner_id}/{sha}.py"
        target = self.settings.scripts_dir / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(code)
            os.replace(tmp, target)
        return sha, rel

    def create_script(self, owner_id: str, kind: str, source: str, name: str, code: bytes,
                      params: dict | None, filename: str | None = None) -> dict:
        if source not in ("workspace", "file"):
            raise ApiError(422, "SCRIPT_SOURCE_INVALID", "source must be 'workspace' or 'file' (built-ins are read-only)")
        if not _NAME_RE.match(name or ""):
            raise ApiError(422, "VALIDATION_ERROR", "Invalid script name")
        if source == "file" and not (filename and _FILENAME_RE.match(filename)):
            raise ApiError(422, "SCRIPT_FILENAME_INVALID", "Uploaded file must be a plain name ending with .py")
        if not isinstance(params or {}, dict):
            raise ApiError(422, "VALIDATION_ERROR", "params must be an object")
        self._validate_code(kind, code)
        sha, rel = self._store_code(owner_id, code)
        sid, ts = new_id("scr"), now()
        with self.db.tx() as con:
            con.execute("INSERT INTO scripts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, owner_id, kind, source, name, filename, None, sha, rel, dumps(params or {}), 1, ts, ts))
        return self.get_script(owner_id, sid)

    def update_script(self, owner_id: str, script_id: str, code: bytes | None, params: dict | None,
                      filename: str | None = None) -> dict:
        row = self._script_row(owner_id, script_id)
        if row["owner_id"] is None:
            raise ApiError(403, "SCRIPT_READ_ONLY", "Built-in scripts are read-only; create a workspace copy")
        sets: dict[str, Any] = {}
        if code is not None:
            self._validate_code(row["kind"], code)
            sets["code_sha256"], sets["code_rel"] = self._store_code(owner_id, code)
            if row["source"] == "file":
                if not (filename and _FILENAME_RE.match(filename)):
                    raise ApiError(422, "SCRIPT_FILENAME_INVALID", "Uploaded file must be a plain name ending with .py")
                sets["filename"] = filename
        if params is not None:
            sets["params_json"] = dumps(params)
        if sets:
            sets["revision"] = row["revision"] + 1
            sets["updated_at"] = now()
            assign = ", ".join(f"{k} = :{k}" for k in sets)
            with self.db.tx() as con:
                con.execute(f"UPDATE scripts SET {assign} WHERE script_id = :sid", {**sets, "sid": script_id})
        return self.get_script(owner_id, script_id)

    def _script_row(self, owner_id: str, script_id: str) -> dict:
        row = self.db.one("SELECT * FROM scripts WHERE script_id = ? AND (owner_id IS NULL OR owner_id = ?)", (script_id, owner_id))
        if row is None:
            raise not_found("script", script_id)
        return row

    def script_code(self, row: dict) -> bytes:
        return (self.settings.scripts_dir / row["code_rel"]).read_bytes()

    def _script_view(self, row: dict, with_code: bool) -> dict:
        view = {"script_id": row["script_id"], "kind": row["kind"], "source": row["source"], "name": row["name"],
                "filename": row["filename"], "builtin_ref": row["builtin_ref"], "shared": row["owner_id"] is None,
                "params": loads(row["params_json"]), "revision": row["revision"], "code_sha256": row["code_sha256"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}
        if row["kind"] == "check":
            view["declared_params"] = declared_check_params(self.script_code(row))
        elif row["kind"] == "normalize" and row["source"] == "builtin":
            view["declared_params"] = {"presets": normalize_presets(),
                                       "overridable": sorted(NORMALIZE_PARAM_KEYS - {"config"})}
        else:
            view["declared_params"] = None
        if with_code:
            view["code"] = self.script_code(row).decode("utf-8")
        return view

    def get_script(self, owner_id: str, script_id: str, with_code: bool = True) -> dict:
        return self._script_view(self._script_row(owner_id, script_id), with_code)

    def list_scripts(self, owner_id: str, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM scripts WHERE (owner_id IS NULL OR owner_id = ?)"
        params: list[Any] = [owner_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        return [self._script_view(r, False) for r in self.db.all(sql + " ORDER BY owner_id IS NOT NULL, created_at", params)]

    # ----------------------------------------------------- configurations
    def create_configuration(self, owner_id: str, name: str, dataset_id: str, slots: dict[str, dict],
                             checks: list[dict] | None) -> dict:
        if not _NAME_RE.match(name or ""):
            raise ApiError(422, "VALIDATION_ERROR", "Invalid configuration name")
        self._dataset_row(owner_id, dataset_id)
        unknown = set(slots) - set(PROCEDURE_SLOTS)
        if unknown:
            raise ApiError(422, "SLOT_INVALID", "Unknown procedure slot", {"slots": sorted(unknown), "allowed": list(PROCEDURE_SLOTS)})
        resolved_slots: dict[str, dict] = {}
        for slot in PROCEDURE_SLOTS:
            ref = slots.get(slot) or {}
            sid = ref.get("script_id") or self.builtin_script_id(f"builtin:{slot}")
            if sid is None:
                raise ApiError(503, "BUILTIN_UNAVAILABLE", f"Built-in {slot} procedure is not available")
            row = self._script_row(owner_id, sid)
            if row["kind"] != slot:
                raise ApiError(422, "SCRIPT_KIND_MISMATCH", f"Slot {slot} needs a script of kind {slot}",
                               {"script_id": sid, "kind": row["kind"]})
            params = ref.get("params")
            if params is not None and not isinstance(params, dict):
                raise ApiError(422, "VALIDATION_ERROR", "params must be an object")
            if slot == "normalize" and row["source"] == "builtin":
                validate_normalize_params({**loads(row["params_json"]), **(params or {})})
            resolved_slots[slot] = {"script_id": sid, "params": params}
        if checks is None:
            checks = [{"script_id": s["script_id"]} for s in self.list_scripts(owner_id, "check") if s["shared"]]
        seen: set[str] = set()
        resolved_checks = []
        for ref in checks:
            sid = ref.get("script_id")
            row = self._script_row(owner_id, sid) if sid else None
            if row is None:
                raise not_found("script", sid)
            if row["kind"] != "check":
                raise ApiError(422, "SCRIPT_KIND_MISMATCH", "Selected check is not a check script", {"script_id": sid})
            if sid in seen:
                raise ApiError(422, "DUPLICATE_CHECK", "The same check script is selected twice", {"script_id": sid})
            seen.add(sid)
            params = ref.get("params")
            if params is not None and not isinstance(params, dict):
                raise ApiError(422, "VALIDATION_ERROR", "params must be an object")
            resolved_checks.append({"script_id": sid, "params": params})
        cid = new_id("cfg")
        with self.db.tx() as con:
            con.execute("INSERT INTO configurations VALUES (?,?,?,?,?,?,?)",
                        (cid, owner_id, name, dataset_id, dumps(resolved_slots), dumps(resolved_checks), now()))
        return self.get_configuration(owner_id, cid)

    def _config_row(self, owner_id: str, config_id: str) -> dict:
        row = self.db.one("SELECT * FROM configurations WHERE config_id = ? AND owner_id = ?", (config_id, owner_id))
        if row is None:
            raise not_found("configuration", config_id)
        return row

    @staticmethod
    def _config_view(row: dict) -> dict:
        return {"config_id": row["config_id"], "name": row["name"], "dataset_id": row["dataset_id"],
                "slots": loads(row["slots_json"]), "checks": loads(row["checks_json"]), "created_at": row["created_at"]}

    def get_configuration(self, owner_id: str, config_id: str) -> dict:
        return self._config_view(self._config_row(owner_id, config_id))

    def list_configurations(self, owner_id: str) -> list[dict]:
        return [self._config_view(r) for r in
                self.db.all("SELECT * FROM configurations WHERE owner_id = ? ORDER BY created_at", (owner_id,))]

    # ------------------------------------------------------------ helpers
    def custom_script_rows(self, owner_id: str, script_ids: list[str]) -> list[dict]:
        return [r for r in (self._script_row(owner_id, s) for s in script_ids) if r["source"] != "builtin"]
