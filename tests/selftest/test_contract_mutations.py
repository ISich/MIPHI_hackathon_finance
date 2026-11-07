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
