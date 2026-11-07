"""Review #3 (MAJOR): the whole child process group is cleaned up, also after the leader exits."""
import os
import time
from pathlib import Path

import pytest

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run

SPAWNER = """
import os, subprocess
from decision_diff.core import normalize as core_normalize
from decision_diff.configs import REAL

def normalize(document, app_id, source, params):
    if source == 'BEFORE':
        out = None if params['inherit'] else subprocess.DEVNULL
        p = subprocess.Popen(['sleep', '300'], stdout=out, stderr=out)
        with open(os.path.join(os.environ['HOME'], 'grandchild-%s.pid' % params['tag']), 'w') as f:
            f.write(str(p.pid))
    return core_normalize(document, app_id, source, REAL)
"""


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(")")[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


@pytest.mark.parametrize("inherit", [True, False])
def test_grandchildren_are_killed_and_do_not_hold_the_run(env, monkeypatch, inherit):
    monkeypatch.setenv("DD_EXECUTION_MODE", "trusted-local")
    monkeypatch.setenv("DD_RUN_TIMEOUT_SECONDS", "60")
    with make_client() as c:
        ds = demo_dataset(c)
        s = c.post("/api/scripts", json={"kind": "normalize", "name": "spawner", "code": SPAWNER}).json()
        cfg = config(c, ds["dataset_id"], checks=[], slots={"normalize": {"script_id": s["script_id"],
                                                                         "params": {"inherit": inherit, "tag": str(inherit)}}})
        t = time.monotonic()
        done = wait_run(c, start_run(c, cfg["config_id"]).json()["run_id"], timeout=90)
        assert done["status"] == "COMPLETED", done
        assert time.monotonic() - t < 30  # not held until the 60 s timeout by the grandchild's pipe
        pid = int((env["home"] / "runs" / done["run_id"] / "work" / f"grandchild-{inherit}.pid").read_text())
        deadline = time.time() + 5
        while _alive(pid) and time.time() < deadline:
            time.sleep(0.1)
        alive = _alive(pid)
        if alive:
            os.kill(pid, 9)
        assert not alive, "grandchild survived the run"
