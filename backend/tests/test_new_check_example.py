"""The editor's default example is executable against a real run's mart, not an empty stub."""
import json
import os

from conftest import make_client
from helpers import config, demo_dataset, idem, start_run
from dd_backend.check_child import execute, register
from dd_backend.db import dumps
from dd_backend.pipeline import Emitter, run as run_pipeline


def test_editor_example_saves_snapshots_and_calculates_real_results(env, monkeypatch, tmp_path):
    # This test exercises the real API, snapshot and Python runner; Linux worker containment is separate.
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_EMBEDDED_WORKER", "0")
    with make_client() as client:
        dataset = demo_dataset(client)
        configuration = config(client, dataset["dataset_id"], checks=[])
        accepted = start_run(client, configuration["config_id"]).json()
        run_id = accepted["run_id"]
        run_dir = env["home"] / "runs" / run_id
        emit = Emitter(os.open(os.devnull, os.O_WRONLY))
        try:
            result = run_pipeline(run_dir, emit)
        finally:
            emit.stream.close()
        with client.app.state.db.tx() as con:
            con.execute("UPDATE runs SET status = 'COMPLETED', summary_json = ? WHERE run_id = ?",
                        (dumps(result["summary"]), run_id))

        kind = next(item for item in client.get("/api/script-kinds").json() if item["kind"] == "check")
        assert kind["custom_execution_enabled"] is True
        saved = client.post("/api/scripts", json={"kind": "check", "name": "Доля изменённых заявок", "code": kind["example"]})
        assert saved.status_code == 201, saved.text
        requested = client.post(f"/api/runs/{run_id}/check-runs",
                                json={"checks": [{"script_id": saved.json()["script_id"]}]}, headers=idem())
        assert requested.status_code == 202, requested.text
        check_run = requested.json()
        assert check_run["report_id"] != accepted["initial_report_id"]
        snapshot = client.get(f"/api/check-runs/{check_run['check_run_id']}/code/check-01").json()
        assert snapshot["code"] == kind["example"]
        script = run_dir / "snapshot" / "checks" / check_run["check_run_id"] / "check-01.py"

        registration = tmp_path / "registration.json"
        assert register(script, registration) == 0
        definition = json.loads(registration.read_text())
        assert definition["ok"] is True
        assert definition["label"] == "Доля изменённых заявок"
        overrides = tmp_path / "overrides.json"
        overrides.write_text("{}")
        output = tmp_path / "result.json"
        assert execute(script, run_dir / "artifacts" / "mart.duckdb", overrides, output) == 0
        execution = json.loads(output.read_text())
        assert execution["status"] == "SUCCEEDED", execution
        assert execution["diagnostics"] == []
        row, = execution["rows"]
        assert row["TOTAL"] == result["summary"]["total_apps"]
        assert row["CNT"] == result["summary"]["changed_apps"]
        assert row["METRIC"] == round(row["CNT"] / row["TOTAL"], 4)
        assert row["RESULT"] == "FAIL"  # the real fixture has changes in its only application

        # A changed parameter must affect the actual verdict, rather than returning a canned result.
        overrides.write_text(json.dumps({definition["id"]: {"max_share": 1.0}}))
        execute(script, run_dir / "artifacts" / "mart.duckdb", overrides, output)
        assert json.loads(output.read_text())["rows"][0]["RESULT"] == "PASS"
