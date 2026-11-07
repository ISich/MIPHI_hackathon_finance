import json

from conftest import peer
from dd_backend import dataset_tables


def register(client, env, before, after):
    (env["data"] / "before.json").write_text(json.dumps(before), encoding="utf-8")
    (env["data"] / "after.json").write_text(json.dumps(after), encoding="utf-8")
    response = client.post("/api/datasets", json={"name": "table", "root": "data", "mode": "files",
                                               "before": "before.json", "after": "after.json"})
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def test_table_snapshot_flattens_json_and_keeps_types(no_worker_client, env):
    client = no_worker_client
    ds = register(client, env, {"amount": 5}, [{"amount": 10, "active": True, "nested": {"region": "Москва"}, "a/b": 2, "long_id": 12345678901234567890},
                                             {"amount": None, "items": [1, 2]}])
    response = client.get(f"/api/datasets/{ds}/table?side=after")
    assert response.status_code == 200, response.text
    body = response.json()
    records = [dict(zip(body["columns"], row)) for row in body["rows"]]
    assert records[0]["/amount"] == 10 and records[0]["/active"] is True
    assert records[0]["/nested/region"] == "Москва" and records[0]["/a~1b"] == 2
    assert records[0]["/long_id"] == "12345678901234567890"
    assert records[1]["/items"] == "[1, 2]"
    assert client.get(f"/api/datasets/{ds}/table?side=before").json()["rows"][0][1] == 5
    assert client.get(f"/api/datasets/{ds}/table?side=other").status_code == 422
    with peer(client.app) as other:
        assert other.get(f"/api/datasets/{ds}/table").status_code == 404


def test_table_rejects_oversize_invalid_json_and_symlinks(no_worker_client, env, monkeypatch):
    client = no_worker_client
    ds = register(client, env, {}, [{"a": 1}, {"a": 2}])
    monkeypatch.setattr(dataset_tables, "MAX_ROWS", 1)
    assert client.get(f"/api/datasets/{ds}/table").status_code == 413
    monkeypatch.setattr(dataset_tables, "MAX_ROWS", 20000)
    after = env["data"] / "after.json"
    after.write_text('{"invalid": NaN}')
    assert client.get(f"/api/datasets/{ds}/table").json()["code"] == "DATASET_JSON_INVALID"
    after.unlink()
    outside = env["home"] / "secret.json"
    outside.write_text('{"secret": 42}')
    after.symlink_to(outside)
    response = client.get(f"/api/datasets/{ds}/table")
    assert response.status_code == 422 and "secret" not in response.text
