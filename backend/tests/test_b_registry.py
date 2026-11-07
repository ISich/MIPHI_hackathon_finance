"""Slice B: datasets/scripts/configurations registry and path safety."""
import os

from helpers import config, copy_pair_dirs, demo_dataset


def test_register_file_pair_dataset_with_revision(client):
    ds = demo_dataset(client)
    assert ds["mode"] == "files" and ds["revisions"][0]["pairs"] == 1
    assert len(ds["revisions"][0]["fingerprint"]) == 64
    assert "/" not in ds["root"]  # root is a name, never a server path
    listed = client.get("/api/datasets").json()
    assert [d["dataset_id"] for d in listed] == [ds["dataset_id"]]
    assert client.get(f"/api/datasets/{ds['dataset_id']}").json()["name"] == "core demo pair"


def test_register_directory_dataset_and_missing_pair_is_reported(client, env):
    root = copy_pair_dirs(env["core"], env["data"], n=3)
    os.remove(root / "AFTER" / "T0002.json")
    r = client.post("/api/datasets", json={"name": "dirs", "root": "data", "mode": "dirs",
                                           "before": "set1/BEFORE", "after": "set1/AFTER"})
    assert r.status_code == 201, r.json()
    rev = r.json()["revisions"][0]
    assert rev["pairs"] == 2 and rev["missing_after"] == ["T0002.json"]


def test_path_traversal_absolute_and_unknown_root_are_rejected(client, env):
    cases = [
        ({"root": "data", "before": "../home/backend.sqlite3", "after": "x"}, "DATASET_PATH_INVALID"),
        ({"root": "data", "before": "/etc/passwd", "after": "/etc/passwd"}, "DATASET_PATH_INVALID"),
        ({"root": "nope", "before": "a", "after": "b"}, "DATASET_ROOT_NOT_ALLOWED"),
        ({"root": "data", "before": "missing.json", "after": "missing.json"}, "DATASET_PATH_NOT_FOUND"),
    ]
    for body, code in cases:
        r = client.post("/api/datasets", json={"name": "x", "mode": "files", **body})
        assert r.status_code == 422, (body, r.json())
        assert r.json()["code"] == code
        assert str(env["home"]) not in r.text and "/etc" not in r.json()["message"]


def test_symlink_escape_is_rejected(client, env, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.json").write_text("{}")
    (env["data"] / "link").symlink_to(outside, target_is_directory=True)
    r = client.post("/api/datasets", json={"name": "x", "root": "data", "mode": "files",
                                           "before": "link/a.json", "after": "link/a.json"})
    assert r.status_code == 422 and r.json()["code"] == "DATASET_PATH_ESCAPES_ROOT"
    # symlinked file inside a directory dataset is also refused
    root = copy_pair_dirs(env["core"], env["data"], name="set2", n=1)
    (root / "BEFORE" / "evil.json").symlink_to(outside / "a.json")
    (root / "AFTER" / "evil.json").symlink_to(outside / "a.json")
    r = client.post("/api/datasets", json={"name": "y", "root": "data", "mode": "dirs",
                                           "before": "set2/BEFORE", "after": "set2/AFTER"})
    assert r.status_code == 422 and r.json()["code"] == "DATASET_PATH_ESCAPES_ROOT"


def test_script_kinds_have_contract_template_example(client):
    kinds = {k["kind"]: k for k in client.get("/api/script-kinds").json()}
    assert set(kinds) == {"normalize", "compare", "segments", "aggregate", "check"}
    for k in kinds.values():
        assert k["template"] and k["example"] and k["entrypoint"] and k["output_columns"]
        compile(k["template"], "t", "exec"), compile(k["example"], "e", "exec")
        assert k["custom_execution_enabled"] is False


def test_builtin_scripts_include_procedures_and_five_organizer_checks(client):
    scripts = client.get("/api/scripts").json()
    builtin = [s for s in scripts if s["source"] == "builtin"]
    assert {s["kind"] for s in builtin} == {"normalize", "compare", "segments", "aggregate", "check"}
    assert len([s for s in builtin if s["kind"] == "check"]) == 5
    one = client.get(f"/api/scripts/{builtin[0]['script_id']}").json()
    assert one["code"]
    r = client.put(f"/api/scripts/{builtin[0]['script_id']}", json={"code": "x = 1\n"})
    assert r.status_code == 403 and r.json()["code"] == "SCRIPT_READ_ONLY"


def test_workspace_and_file_scripts_are_distinct_sources(client):
    ws = client.post("/api/scripts", json={"kind": "check", "name": "ws", "code": "CHECK = {}\n"})
    assert ws.status_code == 201 and ws.json()["source"] == "workspace" and ws.json()["revision"] == 1
    up = client.post("/api/scripts/upload", data={"kind": "check", "name": "up", "params": '{"a": 1}'},
                     files={"file": ("my_check.py", b"CHECK = {}\n", "text/x-python")})
    assert up.status_code == 201, up.json()
    assert up.json()["source"] == "file" and up.json()["filename"] == "my_check.py" and up.json()["params"] == {"a": 1}
    edited = client.put(f"/api/scripts/{ws.json()['script_id']}", json={"code": "CHECK = {'id': 'x'}\n"}).json()
    assert edited["revision"] == 2 and edited["code"] == "CHECK = {'id': 'x'}\n"
    bad_name = client.post("/api/scripts/upload", data={"kind": "check", "name": "x"},
                           files={"file": ("../../evil.py", b"x=1\n", "text/x-python")})
    assert bad_name.status_code == 422 and bad_name.json()["code"] == "SCRIPT_FILENAME_INVALID"


def test_script_validation_kind_syntax_and_size(client):
    r = client.post("/api/scripts", json={"kind": "shell", "name": "x", "code": "x=1"})
    assert r.status_code == 422
    r = client.post("/api/scripts", json={"kind": "check", "name": "x", "code": "def (:"})
    assert r.status_code == 422 and r.json()["code"] == "CODE_SYNTAX_ERROR"
    big = b"# " + b"x" * (300 * 1024) + b"\n"
    r = client.post("/api/scripts/upload", data={"kind": "check", "name": "big"},
                    files={"file": ("big.py", big, "text/x-python")})
    assert r.status_code == 413 and r.json()["code"] in ("CODE_TOO_LARGE", "PAYLOAD_TOO_LARGE")


def test_configuration_defaults_to_builtin_slots_and_all_organizer_checks(client):
    ds = demo_dataset(client)
    cfg = config(client, ds["dataset_id"])
    assert set(cfg["slots"]) == {"normalize", "compare", "segments", "aggregate"}
    assert len(cfg["checks"]) == 5
    assert client.get(f"/api/configurations/{cfg['config_id']}").json() == cfg
    assert [c["config_id"] for c in client.get("/api/configurations").json()] == [cfg["config_id"]]
    empty = config(client, ds["dataset_id"], checks=[])
    assert empty["checks"] == []


def test_configuration_rejects_wrong_kind_and_bad_builtin_params(client):
    ds = demo_dataset(client)
    check = next(s for s in client.get("/api/scripts?kind=check").json())
    r = client.post("/api/configurations", json={"name": "c", "dataset_id": ds["dataset_id"],
                                                  "slots": {"normalize": {"script_id": check["script_id"]}}})
    assert r.status_code == 422 and r.json()["code"] == "SCRIPT_KIND_MISMATCH"
    r = client.post("/api/configurations", json={"name": "c", "dataset_id": ds["dataset_id"],
                                                  "slots": {"normalize": {"params": {"config": "../../x"}}}})
    assert r.status_code == 422 and r.json()["code"] == "PARAMS_INVALID"
    r = client.post("/api/configurations", json={"name": "c", "dataset_id": ds["dataset_id"], "owner_id": "x"})
    assert r.status_code == 422  # owner never accepted from the body
