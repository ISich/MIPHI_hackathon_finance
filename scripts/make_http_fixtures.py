"""Write synthetic BEFORE/AFTER datasets for black-box HTTP tests into DIR.

Point the backend data root (e.g. DD_DATA_ROOTS=...,qa=DIR) at DIR and run tests with
QA_FIXTURE_ROOT=qa QA_FIXTURE_DIR=DIR. Datasets (all in mode=dirs):
  neutral/{BEFORE,AFTER}  - identical pairs, every organizer check PASS
  events/{BEFORE,AFTER}   - one event per organizer check (FAIL expected)
  broken/{BEFORE,AFTER}   - one missing AFTER file and one invalid JSON (AC-02)
  badjson/{BEFORE,AFTER}  - all pairs present, one AFTER file is invalid JSON (AC-02)
  escape -> /             - symlink leaving the root (path traversal test)
These are internal fixtures, not the organizers' dataset.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from support.fixtures import pair, write_dataset  # noqa: E402


def _reject(doc):
    doc["decisionResult"]["decision"] = "REJECT"


def _events():
    rules = [("RESTRICTED_REGIONS", False), ("AGELOW@21", True)]

    def drift(doc):
        doc["characteristics"]["score_okb"] = 500
        _reject(doc)

    def new_attr(doc):
        doc["characteristics"]["score_new"] = 1

    def stop(doc):
        doc["decisionResult"]["product_trials"][0]["rules"][1]["hit"] = False

    def model(doc):
        doc["decisionResult"]["product_trials"][0]["scoring"]["pd"]["modelName"] = "ML_V2"
    return [pair("EV01", _reject), pair("EV02", drift), pair("EV03", new_attr),
            pair("EV04", stop, rules=rules), pair("EV05", model), pair("EV06")]


def main(target: str) -> None:
    root = Path(target)
    root.mkdir(parents=True, exist_ok=True)
    write_dataset(root / "neutral", [pair(f"N{i:02d}") for i in range(3)])
    write_dataset(root / "events", _events())
    b, a = write_dataset(root / "broken", [pair("K01"), pair("K02"), pair("K03")])
    (a / "K02.json").unlink()
    (a / "K03.json").write_text("{not json", encoding="utf-8")
    _, a2 = write_dataset(root / "badjson", [pair("J01"), pair("J02")])
    (a2 / "J02.json").write_text("{not json", encoding="utf-8")
    link = root / "escape"
    if not link.exists():
        os.symlink("/", link)
    (root / "MANIFEST.json").write_text(json.dumps({"datasets": ["neutral", "events", "broken", "badjson"]}), encoding="utf-8")
    print(root)


if __name__ == "__main__":
    main(sys.argv[1])
