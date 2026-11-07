"""Mutation self-tests for offline contract tests (CR #10, #11). The mutations are TEST DOUBLES applied with
monkeypatch to the pinned core, only here, to prove the strengthened tests detect the defect."""
from __future__ import annotations

import inspect

import pytest

from contracts import test_check_runner_contract as runner_tests
from contracts import test_core_contract as core_tests


def test_cr10_duplicate_comparison_rows_are_detected(monkeypatch):
    import decision_diff.core as core

    real = core.normalize_pair

    def duplicating(*args, **kwargs):  # TEST DOUBLE: injects one duplicate logical key
        union, rows = real(*args, **kwargs)
        return union, [*rows, dict(rows[0], VALUE_AFTER="dup")]

    monkeypatch.setattr(core, "normalize_pair", duplicating)
    with pytest.raises(AssertionError, match="duplicate comparison rows"):
        core_tests.test_ac03_four_change_types_and_one_row_per_key()


def test_cr11_unused_timeout_parameter_does_not_satisfy_timeout_test():
    """The old check (`'timeout' in signature`) is satisfied by a do-nothing parameter; the new test is behavioural."""
    import decision_diff.check_runner as cr

    def fake(mart, paths, parameter_overrides=None, timeout=None):  # TEST DOUBLE: ignores timeout
        return cr.run_checks(mart, paths, parameter_overrides)

    assert "timeout" in " ".join(inspect.signature(fake).parameters)  # old test would pass on this
    src = inspect.getsource(runner_tests.test_runner_enforces_timeout_on_hanging_check)
    assert "signature" not in src and "time.sleep(3600)" in src and "communicate(timeout=20)" in src


def test_cr2_1_drilldown_tests_accept_the_target_contract(monkeypatch, tmp_path):
    """CR2 #1: if D4 returns the data.md contract {items, total}, BOTH drill-down tests must pass.
    The pre-fix fact test compared len(response) with CNT and would fail on a correct dict response."""
    from contracts import test_mart_contract as mart_tests
    from decision_diff.mart import DuckDBMart
    from support.fixtures import pair, run_real_pipeline

    real = DuckDBMart.pivot_app_ids

    def paged(self, group, *, limit=200):  # TEST DOUBLE: the target contract on top of the real query
        everything = real(self, group, limit=10000)
        return {"items": everything[:limit], "total": len(everything)}

    run = run_real_pipeline(tmp_path, [pair("M2", mart_tests._changed), pair("M1"), pair("M10", mart_tests._changed),
                                       pair("M3")])
    monkeypatch.setattr(DuckDBMart, "pivot_app_ids", paged)
    with DuckDBMart(run.db) as mart:
        mart_tests.test_pivot_drilldown_matches_fact_cnt(mart)
        mart_tests.test_pivot_drilldown_returns_full_distinct_total(mart)  # no xfail: defect absent
        fact = [f for f in mart.pivot(limit=100000) if f["CNT"] not in (2,)][0]  # len(dict)==2 keys
        group = {k: fact[k] for k in ("PATH", "ARRAY_KEY", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE")}
        assert len(mart.pivot_app_ids(group, limit=10000)) != fact["CNT"]  # the old assertion would fail here


def test_cr2_3_upload_probe_boundary(tmp_path):
    """CR2 #3: a sanitized copy inside DD_HOME is allowed; a copy at an escape target outside the scanned work
    dir is caught. The 08714b9 logic (any evil_qa.py under the work dir) got both wrong."""
    from support.fs_probe import forbidden_copies

    outer = tmp_path / "outer"
    work = outer / "work"
    home = work / "home"
    (home / "scripts").mkdir(parents=True)
    name, marker = "qa_trav_x.py", b"MARK"
    (home / "scripts" / name).write_bytes(b"# MARK")          # permitted: inside DD_HOME
    old_logic = list(work.rglob(name))                        # what 08714b9 flagged
    assert old_logic and forbidden_copies(home, name, marker, scan_root=work) == []
    (outer / name).write_bytes(b"# MARK")                    # escape target OUTSIDE the work dir
    assert outer / name not in list(work.rglob(name))        # 08714b9 never looked there
    assert forbidden_copies(home, name, marker, scan_root=work) == [outer / name]
    (work / "stray.txt").write_bytes(b"MARK")                 # marker content leaked inside work, outside home
    assert work / "stray.txt" in forbidden_copies(home, name, marker, scan_root=work)
