"""Full open-dataset acceptance run (AC-01 via API, NFR-001, NFR-003 timings) - numbers come from execution only.

    QA_BACKEND_DIR=<backend checkout> .venv/bin/python scripts/full_dataset_run.py <RESULTS_DIR> <OUT_DIR>

RESULTS_DIR contains BEFORE_MASTER/ and AFTER_BETA/ (read-only; served as allowlisted root `full`; never copied).
Starts its own backend on a free loopback port with a temporary DD_HOME, registers the dataset over HTTP, runs all
built-in checks, then independently runs the pinned core CLI on the same folders and compares. Writes
OUT_DIR/full_run.json. Exit code 0 only if acceptance_problems() is empty: Run COMPLETED, initial report PUBLISHED and
COMPLETE, exactly the organizer checks executed and all SUCCEEDED, API summary == CLI summary.
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

from support.backend_proc import organizer_checks, start_backend  # noqa: E402
from support.http_api import Api  # noqa: E402

KEYS = ("total_apps", "changed_apps", "decision_changed_apps", "changed_attributes", "change_types",
        "approval_rate_before", "approval_rate_after")


def organizer_check_ids(checks_dir: Path) -> set[str]:
    return {p.stem[len("check_"):] for p in checks_dir.glob("check_*.py")}


def acceptance_problems(report: dict, expected_check_ids: set[str]) -> list[str]:
    """CR3 #4: why the full run is NOT accepted (empty = accepted). An empty execution list is a failure."""
    problems = []
    if report.get("cli", {}).get("returncode") != 0:
        problems.append(f"core CLI returncode {report.get('cli', {}).get('returncode')!r}")
    for side in ("api_summary", "cli_summary"):
        values = report.get(side) or {}
        missing = [k for k in KEYS if values.get(k) is None]
        if missing:
            problems.append(f"{side} missing {missing}")
        elif not (isinstance(values["total_apps"], int) and values["total_apps"] > 0):
            problems.append(f"{side} total_apps invalid {values['total_apps']!r}")
    if report.get("http_errors"):
        problems.append(f"HTTP errors {report['http_errors']}")
    if report.get("run", {}).get("status") != "COMPLETED":
        problems.append(f"run status {report.get('run', {}).get('status')!r}")
    if not report.get("api_equals_cli"):
        problems.append("API summary differs from the independent core CLI")
    checks = report.get("checks") or {}
    if checks.get("completeness") != "COMPLETE":
        problems.append(f"report completeness {checks.get('completeness')!r}")
    if report.get("report_status") != "PUBLISHED":
        problems.append(f"initial report status {report.get('report_status')!r}")
    executions = checks.get("executions") or []
    executed = sorted(str(e.get("check_id")) for e in executions)
    if not expected_check_ids or executed != sorted(expected_check_ids):
        problems.append(f"executed checks {executed} != expected {sorted(expected_check_ids)}")
    bad = [e for e in executions if e.get("execution_status") != "SUCCEEDED"]
    if bad:
        problems.append(f"non-succeeded executions {bad}")
    return problems


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
        report["http_errors"] = []

        def get_json(url):
            resp = api.get(url, params={"limit": 2000} if url.endswith("/events") else None)
            if resp.status_code != 200:
                report["http_errors"].append(f"GET {url} -> {resp.status_code}")
                return {}
            return resp.json()

        if run["status"] == "COMPLETED":
            summary = get_json(f"/api/runs/{run['run_id']}/summary")
            report["api_summary"] = {k: summary.get(k) for k in (*KEYS, "pairs", "pipeline_seconds", "rows")}
            checks = get_json(f"/api/runs/{run['run_id']}/checks")
            report["checks"] = {"completeness": checks.get("completeness"),
                                "executions": [{k: e.get(k) for k in ("check_id", "execution_status", "rows_count",
                                                                       "duration_seconds")} for e in checks.get("executions", [])],
                                "rows": [{k: r[k] for k in ("LABEL", "ARGUMENT", "CNT", "TOTAL", "METRIC", "RESULT",
                                                            "CONFIDENCE")} for r in checks.get("checks", [])]}
            report["report_status"] = get_json(f"/api/reports/{run['initial_report_id']}").get("status")
            report["artifacts"] = [{k: a[k] for k in ("kind", "rows", "bytes", "sha256")}
                                   for a in get_json(f"/api/runs/{run['run_id']}/artifacts").get("items", [])]
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
    api_s, cli_s = report.get("api_summary") or {}, report.get("cli_summary") or {}
    report["api_equals_cli"] = all(api_s.get(k) is not None and api_s.get(k) == cli_s.get(k) for k in KEYS)
    report["acceptance_problems"] = acceptance_problems(report, organizer_check_ids(organizer_checks()))
    (out / "full_run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = not report["acceptance_problems"]
    print(json.dumps({k: report.get(k) for k in ("files", "run", "api_summary", "cli_summary", "api_equals_cli",
                                                 "wall_seconds_accept_to_final", "acceptance_problems")},
                     ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
