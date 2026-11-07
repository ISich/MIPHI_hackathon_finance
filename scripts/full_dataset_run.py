"""Full open-dataset acceptance run (AC-01 via API, NFR-001, NFR-003 timings) - numbers come from execution only.

    QA_BACKEND_DIR=<backend checkout> .venv/bin/python scripts/full_dataset_run.py <RESULTS_DIR> <OUT_DIR>

RESULTS_DIR contains BEFORE_MASTER/ and AFTER_BETA/ (read-only; served as allowlisted root `full`; never copied).
Starts its own backend on a free loopback port with a temporary DD_HOME, registers the dataset over HTTP, runs all
built-in checks, then independently runs the pinned core CLI on the same folders and compares. Writes
OUT_DIR/full_run.json. Exit code 0 only if the Run COMPLETED, every check SUCCEEDED and API summary == CLI summary.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from support.backend_proc import start_backend  # noqa: E402
from support.http_api import Api  # noqa: E402

KEYS = ("total_apps", "changed_apps", "decision_changed_apps", "changed_attributes", "change_types",
        "approval_rate_before", "approval_rate_after")


def count_json(folder: Path) -> int:
    return sum(1 for _ in folder.glob("*.json"))


def main(results: str, out_dir: str) -> int:
    results_dir, out = Path(results).resolve(), Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"results_dir": str(results_dir), "host": platform.node(), "python": platform.python_version(),
                    "cpu_count": os.cpu_count(), "files": {"BEFORE_MASTER": count_json(results_dir / "BEFORE_MASTER"),
                                                           "AFTER_BETA": count_json(results_dir / "AFTER_BETA")}}
    work = Path(tempfile.mkdtemp(prefix="qa-full-"))
    backend = start_backend(work / "home", {"full": results_dir}, mode="builtin-only",
                            extra_env={"DD_RUN_TIMEOUT_SECONDS": "1800"})
    try:
        api = Api(backend.url)
        ds = api.dataset("full", "dirs", "BEFORE_MASTER", "AFTER_BETA", name="open dataset RUN-20260827-0001")
        report["dataset_revision"] = ds["revisions"][-1]
        cfg = api.config(ds["dataset_id"])
        t0 = time.monotonic()
        accepted = api.start_run(cfg["config_id"])
        report["accept_seconds"] = round(time.monotonic() - t0, 3)
        assert accepted.status_code == 202, accepted.text
        run = api.wait(f"/api/runs/{accepted.json()['run_id']}", timeout=1800)
        report["wall_seconds_accept_to_final"] = round(time.monotonic() - t0, 3)
        report["run"] = {k: run.get(k) for k in ("run_id", "status", "stage", "error", "created_at", "started_at",
                                                  "finished_at", "checks_completeness")}
        events = api.get(f"/api/runs/{run['run_id']}/events", params={"limit": 2000}).json()["items"]
        report["stage_first_ts"] = {}
        for e in events:
            if e["stage"] and e["stage"] not in report["stage_first_ts"]:
                report["stage_first_ts"][e["stage"]] = e["ts"]
        if run["status"] == "COMPLETED":
            summary = api.get(f"/api/runs/{run['run_id']}/summary").json()
            report["api_summary"] = {k: summary.get(k) for k in (*KEYS, "pairs", "pipeline_seconds", "rows")}
            checks = api.get(f"/api/runs/{run['run_id']}/checks").json()
            report["checks"] = {"completeness": checks["completeness"],
                                "executions": [{k: e.get(k) for k in ("check_id", "execution_status", "rows_count",
                                                                       "duration_seconds")} for e in checks["executions"]],
                                "rows": [{k: r[k] for k in ("LABEL", "ARGUMENT", "CNT", "TOTAL", "METRIC", "RESULT",
                                                            "CONFIDENCE")} for r in checks["checks"]]}
            report["artifacts"] = [{k: a[k] for k in ("kind", "rows", "bytes", "sha256")}
                                   for a in api.get(f"/api/runs/{run['run_id']}/artifacts").json()["items"]]
    finally:
        backend.stop()

    cli_out = work / "cli"
    t0 = time.monotonic()
    proc = subprocess.run([sys.executable, "-m", "decision_diff.cli", "--before", str(results_dir / "BEFORE_MASTER"),
                           "--after", str(results_dir / "AFTER_BETA"), "--out", str(cli_out)],
                          capture_output=True, text=True, check=False)
    report["cli"] = {"returncode": proc.returncode, "wall_seconds": round(time.monotonic() - t0, 3),
                     "stdout": proc.stdout.strip().splitlines()}
    if proc.returncode == 0:
        cli_summary = json.loads((cli_out / "summary.json").read_text(encoding="utf-8"))
        report["cli_summary"] = {k: cli_summary.get(k) for k in KEYS}
        report["cli_issues"] = json.loads((cli_out / "issues.json").read_text(encoding="utf-8"))
    api_s = report.get("api_summary") or {}
    report["api_equals_cli"] = bool(api_s) and all(api_s.get(k) == report.get("cli_summary", {}).get(k) for k in KEYS)
    (out / "full_run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = (report.get("run", {}).get("status") == "COMPLETED" and report["api_equals_cli"]
          and all(e["execution_status"] == "SUCCEEDED" for e in report.get("checks", {}).get("executions", [])))
    print(json.dumps({k: report.get(k) for k in ("files", "run", "api_summary", "cli_summary", "api_equals_cli",
                                                 "wall_seconds_accept_to_final")}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
