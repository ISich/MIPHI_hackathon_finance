"""Data-run child process: VALIDATING -> NORMALIZING -> COMPARING(+SEGMENTS) -> AGGREGATING.

Started by the worker as ``python -I -m dd_backend.pipeline <run_dir> <event_fd>``,
with a scrubbed environment, its own process group and resource limits.
Events go to a dedicated pipe (not stdout), one JSON object per line.
CHECKING and FINALIZING are executed by the worker after this process succeeds.
"""
from __future__ import annotations

import csv
import dataclasses
import errno
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import sys
import traceback
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .registry import COMPARISON_COLUMNS, NORMALIZED_COLUMNS, PIVOT_COLUMNS, SEGMENT_COLUMNS


class StageFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Emitter:
    def __init__(self, fd: int) -> None:
        self.stream = os.fdopen(fd, "w", encoding="utf-8", buffering=1)

    def send(self, **payload: Any) -> None:
        self.stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.stream.flush()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise StageFailure("PROCEDURE_IMPORT_ERROR", f"Cannot import {path.name}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise StageFailure("PROCEDURE_IMPORT_ERROR", f"{path.name}: {type(exc).__name__}: {exc}") from exc
    return module


def build_procedures(run_dir: Path, procs: dict[str, dict]) -> dict[str, Callable]:
    """Return callables for each slot: built-ins call the pinned decision_diff package."""
    from decision_diff import configs, core, reporting, segments

    out: dict[str, Callable] = {}
    for slot, spec in procs.items():
        params = spec["params"]
        if spec["source"] == "builtin":
            if slot == "normalize":
                config = {"real": configs.REAL, "teaching": configs.TEACHING}[params.get("config", "real")]
                changes = {}
                if params.get("excluded_paths") is not None:
                    changes["excluded_paths"] = frozenset(params["excluded_paths"])
                if params.get("arrays") is not None:
                    changes["arrays"] = {path: core.ArrayRule(r["mode"], tuple(r.get("keys", ())), r.get("scalar_suffix", ""))
                                         for path, r in params["arrays"].items()}
                if changes:
                    config = dataclasses.replace(config, **changes)
                out[slot] = lambda doc, app_id, source, _c=config: core.normalize(doc, app_id, source, _c)
            elif slot == "compare":
                out[slot] = lambda b, a: core.compare(b, a)
            elif slot == "segments":
                out[slot] = lambda b, a, app_id: segments.build_segment(b, a, app_id)
            elif slot == "aggregate":
                out[slot] = lambda rows, segs: {"pivot_facts": reporting.pivot_facts(rows),
                                                "summary": reporting.summarize(rows, segs)}
            continue
        module = _load_module(run_dir / "snapshot" / f"{slot}.py", f"dd_user_{slot}")
        fn_name = {"normalize": "normalize", "compare": "compare", "segments": "build_segment", "aggregate": "aggregate"}[slot]
        fn = getattr(module, fn_name, None)
        if not callable(fn):
            raise StageFailure("PROCEDURE_CONTRACT_ERROR", f"{slot} script must define callable {fn_name}()")
        if slot == "normalize":
            out[slot] = lambda doc, app_id, source, _f=fn, _p=params: _f(doc, app_id, source, dict(_p))
        elif slot == "compare":
            out[slot] = lambda b, a, _f=fn, _p=params: _f(b, a, dict(_p))
        elif slot == "segments":
            out[slot] = lambda b, a, app_id, _f=fn, _p=params: _f(b, a, app_id, dict(_p))
        else:
            out[slot] = lambda rows, segs, _f=fn, _p=params: _f(rows, segs, dict(_p))
    return out


def verify_builtin_runtime(cfg: dict) -> None:
    """Refuse to run if the installed core is not the code accepted in the snapshot."""
    import inspect

    from .readiness import core_info
    from .registry import BUILTIN_PROCEDURES
    accepted = (cfg.get("core") or {}).get("commit")
    installed = core_info().get("commit")
    if not accepted or accepted != installed:
        raise StageFailure("CORE_VERSION_MISMATCH",
                           f"installed core commit {str(installed)[:12]} differs from the accepted {str(accepted)[:12]}")
    for slot, spec in cfg["procedures"].items():
        if spec["source"] != "builtin":
            continue
        module = BUILTIN_PROCEDURES[spec["builtin_ref"]]["module"]
        actual = hashlib.sha256(inspect.getsource(importlib.import_module(module)).encode()).hexdigest()
        if actual != spec["code_sha256"]:
            raise StageFailure("CORE_VERSION_MISMATCH",
                               f"built-in {slot} code ({module}) differs from the accepted snapshot")


def _require_rows(rows: Any, columns: list[str], what: str) -> list[dict]:
    if not isinstance(rows, list):
        raise StageFailure("OUTPUT_SCHEMA_INVALID", f"{what} must return a list of dicts")
    for row in rows:
        if not isinstance(row, dict):
            raise StageFailure("OUTPUT_SCHEMA_INVALID", f"{what} returned a non-dict row")
        missing = [c for c in columns if c not in row]
        if missing:
            raise StageFailure("OUTPUT_SCHEMA_INVALID", f"{what} row is missing columns {missing}")
    return rows


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> int:
    # Same dialect the core CLI and D4 storage use: ';' delimiter, UTF-8 with BOM, header always written.
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _file_digest(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return path.stat().st_size, h.hexdigest()


def _read_verified(path: Path, root: str, label: str, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    """Open without following a final symlink (non-blocking: FIFOs cannot hang us), check the opened file
    really lives under root and is a regular file within the size limit, read it once."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise StageFailure("INPUT_ESCAPES_ROOT", f"{label}: is a symlink; refused") from None
        raise StageFailure("INPUT_UNREADABLE", f"{label}: cannot open ({type(exc).__name__})") from None
    try:
        real = os.readlink(f"/proc/self/fd/{fd}") if os.path.isdir("/proc/self/fd") else os.path.realpath(path)
        if not real.startswith(root.rstrip("/") + "/"):
            raise StageFailure("INPUT_ESCAPES_ROOT", f"{label}: resolves outside the dataset root; refused")
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise StageFailure("INPUT_NOT_REGULAR", f"{label}: not a regular file")
        if st.st_size > max_bytes:
            raise StageFailure("INPUT_FILE_TOO_LARGE", f"{label}: exceeds {max_bytes} bytes")
        chunks, read = [], 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            read += len(chunk)
            if read > max_bytes:
                raise StageFailure("INPUT_FILE_TOO_LARGE", f"{label}: exceeds {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise StageFailure("INPUT_UNREADABLE", f"{label}: cannot read ({type(exc).__name__})") from None
    finally:
        os.close(fd)


def _load_json(data: bytes, name: str, side: str) -> dict:
    try:
        doc = json.loads(data)
    except ValueError as exc:
        raise StageFailure("INPUT_INVALID_JSON", f"{side}/{name}: invalid JSON ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise StageFailure("INPUT_INVALID_JSON", f"{side}/{name}: JSON root must be an object")
    return doc


def run(run_dir: Path, emit: Emitter) -> dict:
    from decision_diff.procedure_api import (
        ProcedureContractError, validate_comparison, validate_normalized, validate_segment,
    )

    started = perf_counter()
    cfg = json.loads((run_dir / "snapshot" / "config.json").read_text("utf-8"))
    inputs = json.loads((run_dir / "snapshot" / "inputs.json").read_text("utf-8"))
    procs = cfg["procedures"]
    out_dir = run_dir / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    def stage(name: str, substep: str | None = None, slot: str | None = None, message: str | None = None):
        emit.send(type="stage", stage=name, substep=substep,
                  code_ref=(f"{slot}@{procs[slot]['code_sha256'][:12]}" if slot else None),
                  message=message or f"{name}{'/' + substep if substep else ''} started")

    # ---------------------------------------------------------- VALIDATING
    stage("VALIDATING")
    before_files, after_files = inputs["before"], inputs["after"]
    missing_before = sorted(set(after_files) - set(before_files))
    missing_after = sorted(set(before_files) - set(after_files))
    if missing_before or missing_after:
        raise StageFailure("INPUT_MISSING_PAIR", f"Unpaired inputs: {len(missing_before)} without BEFORE, "
                           f"{len(missing_after)} without AFTER (e.g. {(missing_before + missing_after)[:3]})")
    # Each input is read exactly once; the fingerprinted bytes are the bytes parsed later (no re-open).
    digest = hashlib.sha256()
    raw: dict[tuple[str, str], bytes] = {}
    for side, files in (("BEFORE", before_files), ("AFTER", after_files)):
        for name in sorted(files):
            data = _read_verified(Path(files[name]), inputs["root"], f"{side}/{name}",
                                  inputs.get("max_file_bytes", 64 * 1024 * 1024))
            raw[(side, name)] = data
            digest.update(f"{side}/{name}\0".encode())
            digest.update(hashlib.sha256(data).digest())
    if digest.hexdigest() != inputs["fingerprint"]:
        raise StageFailure("DATASET_REVISION_MISMATCH",
                           "Dataset files changed since the registered revision; rescan the dataset to create a new revision")
    pairs = sorted(before_files)
    emit.send(type="event", level="INFO", message=f"{len(pairs)} complete pairs, fingerprint verified",
              processed=len(pairs), total=len(pairs))
    # Sandboxed mode: from here on (user code may run) the process can read only the runtime and this run's
    # snapshot, write only artifacts/work, and has no network, exec, fork or signals to others.
    from . import sandbox
    if sandbox.enter_from_env():
        emit.send(type="event", level="INFO", message="sandbox entered: landlock + seccomp")
    verify_builtin_runtime(cfg)
    fns = build_procedures(run_dir, procs)

    # --------------------------------------------------------- NORMALIZING
    stage("NORMALIZING", slot="normalize")
    docs: dict[str, tuple[dict, dict, str]] = {}
    normalized: dict[str, tuple[list[dict], list[dict]]] = {}
    step = max(1, len(pairs) // 20)
    for i, name in enumerate(pairs, 1):
        b = _load_json(raw.pop(("BEFORE", name)), name, "BEFORE")
        a = _load_json(raw.pop(("AFTER", name)), name, "AFTER")
        if inputs["mode"] == "files":
            app_id = str((b.get("appData") or {}).get("application_id") or Path(before_files[name]).stem)
        else:
            app_id = Path(name).stem
        try:
            nb = _require_rows(fns["normalize"](b, app_id, "BEFORE"), NORMALIZED_COLUMNS, "normalize")
            na = _require_rows(fns["normalize"](a, app_id, "AFTER"), NORMALIZED_COLUMNS, "normalize")
            nb = validate_normalized(nb, app_id=app_id, source="BEFORE")
            na = validate_normalized(na, app_id=app_id, source="AFTER")
        except ProcedureContractError as exc:
            raise StageFailure("OUTPUT_SCHEMA_INVALID", f"{name}: normalize: {exc}") from exc
        except StageFailure:
            raise
        except Exception as exc:
            raise StageFailure("NORMALIZATION_ERROR", f"{name}: {type(exc).__name__}: {exc}") from exc
        docs[name] = (b, a, app_id)
        normalized[name] = (nb, na)
        if i % step == 0 or i == len(pairs):
            emit.send(type="progress", processed=i, total=len(pairs), message=f"normalized {i}/{len(pairs)} pairs")

    # ----------------------------------------------------------- COMPARING
    stage("COMPARING", slot="compare")
    comparison: list[dict] = []
    for i, name in enumerate(pairs, 1):
        nb, na = normalized[name]
        try:
            rows = _require_rows(fns["compare"](nb, na), COMPARISON_COLUMNS, "compare")
            rows = validate_comparison(rows, app_id=docs[name][2])
        except ProcedureContractError as exc:
            raise StageFailure("OUTPUT_SCHEMA_INVALID", f"{name}: compare: {exc}") from exc
        except StageFailure:
            raise
        except Exception as exc:
            raise StageFailure("COMPARISON_ERROR", f"{name}: {type(exc).__name__}: {exc}") from exc
        comparison.extend(rows)
        if i % step == 0 or i == len(pairs):
            emit.send(type="progress", processed=i, total=len(pairs), message=f"compared {i}/{len(pairs)} pairs")

    stage("COMPARING", substep="SEGMENTS", slot="segments")
    segment_rows: list[dict] = []
    for name in pairs:
        b, a, app_id = docs[name]
        try:
            seg = fns["segments"](b, a, app_id)
        except Exception as exc:
            raise StageFailure("SEGMENTS_ERROR", f"{name}: {type(exc).__name__}: {exc}") from exc
        _require_rows([seg], SEGMENT_COLUMNS, "segments")
        try:
            seg = validate_segment(seg, app_id=app_id)
        except ProcedureContractError as exc:
            raise StageFailure("OUTPUT_SCHEMA_INVALID", f"{name}: segments: {exc}") from exc
        segment_rows.append(seg)
    emit.send(type="progress", processed=len(segment_rows), total=len(pairs), message=f"{len(segment_rows)} segment rows")

    # --------------------------------------------------------- AGGREGATING
    stage("AGGREGATING", slot="aggregate")
    try:
        agg = fns["aggregate"](comparison, segment_rows)
    except Exception as exc:
        raise StageFailure("AGGREGATION_ERROR", f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(agg, dict) or not isinstance(agg.get("summary"), dict):
        raise StageFailure("OUTPUT_SCHEMA_INVALID", "aggregate must return {'pivot_facts': [...], 'summary': {...}}")
    missing_summary = [k for k in ("total_apps", "changed_apps", "decision_changed_apps") if k not in agg["summary"]]
    if missing_summary:
        raise StageFailure("OUTPUT_SCHEMA_INVALID", f"aggregate summary is missing {missing_summary}")
    pivot = _require_rows(agg.get("pivot_facts"), PIVOT_COLUMNS, "aggregate.pivot_facts")
    union = [row for name in pairs for row in (*normalized[name][0], *normalized[name][1])]
    counts = {
        "normalized_union": _write_csv(out_dir / "normalized_union.csv", union, NORMALIZED_COLUMNS),
        "comparison": _write_csv(out_dir / "comparison.csv", comparison, COMPARISON_COLUMNS),
        "segments": _write_csv(out_dir / "segments.csv", segment_rows, SEGMENT_COLUMNS),
        "pivot_facts": _write_csv(out_dir / "pivot_facts.csv", pivot, PIVOT_COLUMNS),
    }
    del union, normalized, docs
    emit.send(type="event", level="INFO", message="CSV artifacts written; building per-run DuckDB mart (D4 storage)")
    from decision_diff.storage import build_database
    try:
        table_counts = build_database(out_dir, out_dir / "mart.duckdb")
    except Exception as exc:
        raise StageFailure("STORAGE_ERROR", f"{type(exc).__name__}: {exc}") from exc
    # D4 (core): fixed-grain BaseFacts/BaseMembership, written once by this run's single writer.
    import duckdb
    from decision_diff.base_facts import materialize_base_facts
    from decision_diff.report_service import ReportService
    con = duckdb.connect(str(out_dir / "mart.duckdb"))
    try:
        table_counts.update(materialize_base_facts(con))
    except Exception as exc:
        raise StageFailure("BASE_FACTS_INVALID", f"{type(exc).__name__}: {exc}") from exc
    finally:
        con.close()
    with ReportService(out_dir / "mart.duckdb") as reports:
        validation = reports.validate_memberships(sample_limit=500)
    if not validation["ok"]:
        raise StageFailure("BASE_FACTS_INVALID", f"pivot membership mismatches: {validation['mismatches'][:3]}")
    emit.send(type="event", level="INFO",
              message=f"base facts {table_counts['base_facts']}, memberships {table_counts['base_membership']}; "
                      f"membership check ok on {validation['checked']} groups")
    summary = {
        **agg["summary"],
        "membership_validation": {"ok": validation["ok"], "checked": validation["checked"]},
        "pairs": len(pairs),
        "rows": {"normalized_union": counts["normalized_union"], "comparison": counts["comparison"],
                 "segments": counts["segments"], "pivot_facts": counts["pivot_facts"]},
        "mart_tables": table_counts,
        "pipeline_seconds": round(perf_counter() - started, 3),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = []
    for kind, fname, rows in (("normalized_union", "normalized_union.csv", counts["normalized_union"]),
                              ("comparison", "comparison.csv", counts["comparison"]),
                              ("segments", "segments.csv", counts["segments"]),
                              ("pivot_facts", "pivot_facts.csv", counts["pivot_facts"]),
                              ("summary", "summary.json", None), ("mart", "mart.duckdb", None)):
        size, sha = _file_digest(out_dir / fname)
        artifacts.append({"kind": kind, "file": fname, "rows": rows, "bytes": size, "sha256": sha})
    return {"summary": summary, "artifacts": artifacts}


def _is_file_too_large(exc: BaseException | None) -> bool:
    """RLIMIT_FSIZE hit (Python ignores SIGXFSZ, so writes fail with EFBIG)."""
    for _ in range(10):
        if exc is None:
            return False
        if (isinstance(exc, OSError) and exc.errno == errno.EFBIG) or "File too large" in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def main() -> int:
    run_dir = Path(sys.argv[1])
    emit = Emitter(int(sys.argv[2]))
    try:
        result = run(run_dir, emit)
    except Exception as exc:
        if _is_file_too_large(exc):
            emit.send(type="error", code="OUTPUT_LIMIT", message="Output file size limit exceeded (DD_MAX_OUTPUT_BYTES)",
                      traceback="")
            return 5
        if isinstance(exc, MemoryError):
            emit.send(type="error", code="MEMORY_LIMIT", message="Memory limit exceeded", traceback="")
            return 3
        if isinstance(exc, StageFailure):
            emit.send(type="error", code=exc.code, message=exc.message, traceback=traceback.format_exc(limit=8))
            return 2
        emit.send(type="error", code="PIPELINE_ERROR", message=f"{type(exc).__name__}: {exc}",
                  traceback=traceback.format_exc(limit=8))
        return 4
    emit.send(type="result", **result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
