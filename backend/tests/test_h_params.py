"""Visible/editable defaults: CHECK.params of built-in checks and builtin normalize config overrides."""
from conftest import wait_run
from helpers import config, demo_dataset, start_run


def test_builtin_checks_expose_declared_default_params_without_executing_them(client):
    checks = {s["name"]: s for s in client.get("/api/scripts?kind=check").json() if s["source"] == "builtin"}
    ar = checks["check_ar_drop_by_product"]
    assert ar["declared_params"] == {"max_drop_rel": 0.10, "low_confidence_cnt": 5, "app_ids_limit": 20}
    assert ar["params"] == ar["declared_params"]  # defaults visible/editable; same effective params


def test_builtin_normalize_preset_is_visible(client):
    norm = next(s for s in client.get("/api/scripts?kind=normalize").json() if s["source"] == "builtin")
    presets = norm["declared_params"]["presets"]
    assert "appData.request_id" in presets["real"]["excluded_paths"]
    assert presets["real"]["arrays"]["decisionResult.available_offers"] == {"mode": "fields", "keys": ["product_id", "type"], "scalar_suffix": ""}


def test_builtin_normalize_exclusions_are_editable_per_configuration(client):
    ds = demo_dataset(client)
    base = wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=[])["config_id"]).json()["run_id"])
    extra = ["appData.request_id", "appData.createDateTime", "characteristics"]
    cfg = config(client, ds["dataset_id"], checks=[], slots={"normalize": {"params": {"config": "real", "excluded_paths": extra}}})
    edited = wait_run(client, start_run(client, cfg["config_id"]).json()["run_id"])
    assert edited["status"] == "COMPLETED", edited
    s0 = client.get(f"/api/runs/{base['run_id']}/summary").json()
    s1 = client.get(f"/api/runs/{edited['run_id']}/summary").json()
    assert s1["rows"]["comparison"] < s0["rows"]["comparison"]
    code = client.get(f"/api/runs/{edited['run_id']}/code/normalize").json()
    assert code["params"]["excluded_paths"] == extra
    bad = client.post("/api/configurations", json={"name": "b", "dataset_id": ds["dataset_id"],
                      "slots": {"normalize": {"params": {"arrays": {"x": {"mode": "weird"}}}}}})
    assert bad.status_code == 422 and bad.json()["code"] == "PARAMS_INVALID"
