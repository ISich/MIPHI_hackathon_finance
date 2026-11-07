from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

_keys = itertools.count(1)


def idem() -> dict:
    return {"Idempotency-Key": f"test-key-{next(_keys)}"}


def demo_dataset(client) -> dict:
    r = client.post("/api/datasets", json={"name": "core demo pair", "root": "examples", "mode": "files",
                                           "before": "I32554354_other.json", "after": "I32554354.json"})
    assert r.status_code == 201, r.json()
    return r.json()


def config(client, dataset_id: str, **extra) -> dict:
    r = client.post("/api/configurations", json={"name": "cfg", "dataset_id": dataset_id, **extra})
    assert r.status_code == 201, r.json()
    return r.json()


def start_run(client, config_id: str, headers: dict | None = None):
    return client.post("/api/runs", json={"configuration_id": config_id}, headers=headers or idem())


def copy_pair_dirs(core: Path, data: Path, name: str = "set1", n: int = 3) -> Path:
    """Directory dataset built from the REAL core fixture pair (renamed copies; not an official dataset)."""
    root = data / name
    (root / "BEFORE").mkdir(parents=True)
    (root / "AFTER").mkdir(parents=True)
    before = json.loads((core / "examples" / "I32554354_other.json").read_text())
    after = json.loads((core / "examples" / "I32554354.json").read_text())
    for i in range(n):
        app = f"T{i:04d}"
        for doc, side in ((before, "BEFORE"), (after, "AFTER")):
            d = json.loads(json.dumps(doc))
            d.setdefault("appData", {})["application_id"] = app
            (root / side / f"{app}.json").write_text(json.dumps(d))
    return root
