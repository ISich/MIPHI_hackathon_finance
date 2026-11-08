"""Top paths use real DuckDB comparison data, with distinct-application counts."""
import csv
import json
import os

import duckdb

from conftest import peer
from helpers import config, demo_dataset, start_run
from dd_backend.db import dumps, new_id, now
from dd_backend.pipeline import Emitter, run as run_pipeline
from dd_backend.summary import top_changed_paths


def _comparison(con, rows):
    con.execute("CREATE TABLE comparison (PATH VARCHAR, APP_ID VARCHAR, DIFF_FLAG INTEGER)")
    if rows:
        con.executemany("INSERT INTO comparison VALUES (?, ?, ?)", rows)


def test_counts_changed_applications_once_per_path_and_excludes_unchanged_rows():
    with duckdb.connect() as con:
        _comparison(con, [
            ("offers.amount", "A", 1), ("offers.amount", "A", 1),
            ("offers.amount", "B", 1), ("offers.amount", "C", 0),
            ("decision", "A", 1), ("score", "B", 1), ("unchanged", "A", 0),
        ])
        assert top_changed_paths(con) == [
            {"path": "offers.amount", "changed_apps": 2},
            {"path": "decision", "changed_apps": 1},
            {"path": "score", "changed_apps": 1},
        ]


def test_returns_at_most_twenty_paths_with_deterministic_tie_order():
    with duckdb.connect() as con:
        _comparison(con, [(f"field_{i:02d}", "A", 1) for i in reversed(range(25))])
        assert top_changed_paths(con) == [
            {"path": f"field_{i:02d}", "changed_apps": 1} for i in range(20)
        ]


def test_no_changes_is_an_empty_list():
    with duckdb.connect() as con:
        _comparison(con, [])
        assert top_changed_paths(con) == []
        con.execute("INSERT INTO comparison VALUES ('unchanged', 'A', 0)")
        assert top_changed_paths(con) == []


def test_real_pipeline_and_summary_api_include_paths_for_new_and_legacy_runs(no_worker_client, env):
    """Run the real built-in data pipeline in-process; Linux worker containment is tested separately."""
    client = no_worker_client
    ds = demo_dataset(client)
    accepted = start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()
    run_id = accepted["run_id"]
    run_dir = env["home"] / "runs" / run_id
    emit = Emitter(os.open(os.devnull, os.O_WRONLY))
    try:
        result = run_pipeline(run_dir, emit)
    finally:
        emit.stream.close()

    # Reference counts come from the generated comparison CSV, independently of the DuckDB query.
    with (run_dir / "artifacts" / "comparison.csv").open(encoding="utf-8-sig") as stream:
        changed_by_path = {}
        for row in csv.DictReader(stream, delimiter=";"):
            if row["DIFF_FLAG"] == "1":
                changed_by_path.setdefault(row["PATH"], set()).add(row["APP_ID"])
    expected = [{"path": path, "changed_apps": len(apps)} for path, apps in changed_by_path.items()]
    expected.sort(key=lambda row: (-row["changed_apps"], row["path"]))
    assert expected
    assert result["summary"]["top_paths"] == expected[:20]
    assert json.loads((run_dir / "artifacts" / "summary.json").read_text())["top_paths"] == expected[:20]

    # Publish the real pipeline result as a completed fixture without starting the Linux-only worker.
    db = client.app.state.db
    with db.tx() as con:
        con.execute("UPDATE runs SET status = 'COMPLETED', summary_json = ? WHERE run_id = ?",
                    (dumps(result["summary"]), run_id))
        for artifact in result["artifacts"]:
            con.execute("INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (new_id("art"), run_id, artifact["kind"], f"{run_id}/artifacts/{artifact['file']}",
                         artifact["rows"], artifact["bytes"], artifact["sha256"], now()))
    response = client.get(f"/api/runs/{run_id}/summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["top_paths"] == expected[:20]
    summary_artifact = next(a for a in summary["artifacts"] if a["kind"] == "summary")
    assert client.get(summary_artifact["download"]).json()["top_paths"] == expected[:20]

    # Old summaries are enriched from the existing mart without changing stored data or artifacts.
    stored = dict(result["summary"])
    del stored["top_paths"]
    with db.tx() as con:
        con.execute("UPDATE runs SET summary_json = ? WHERE run_id = ?", (dumps(stored), run_id))
    assert client.get(f"/api/runs/{run_id}/summary").json() == summary
    assert json.loads(db.one("SELECT summary_json FROM runs WHERE run_id = ?", (run_id,))["summary_json"]) == stored
    foreign = peer(client.app)
    assert foreign.get(f"/api/runs/{run_id}/summary").status_code == 404
