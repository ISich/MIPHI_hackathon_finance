"""Mutation self-tests (CR #3, #4, #7, #8): each strengthened HTTP test must FAIL when the real backend is put
behind the mutating proxy (TEST DOUBLE) that injects exactly the defect the test is meant to catch, and must not
fail without the mutation (control). Opt-in: QA_BACKEND_DIR.
"""
from __future__ import annotations

import pytest

from support.backend_proc import backend_dir
from support.mutation_harness import backend_with_fixtures, outcome, run_nodes

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(backend_dir() is None, reason="QA_BACKEND_DIR not set - NOT VERIFIED")]

H = "tests/http/"
CASES = {
    # CR item: (server mode, mutation, test nodes, expected outcome without mutation)
    "cr3_policy_canary": ("trusted-local", "lie_mode_builtin",
                          [H + "test_execution_policy.py::test_custom_check_only_run_is_refused_and_never_executes",
                           H + "test_execution_policy.py::test_custom_procedure_run_is_refused_and_never_executes"],
                          None),
    "cr4_owner_header": ("builtin-only", "trust_owner_header",
                         [H + "test_owner_isolation.py::test_owner_header_is_ignored"], "passed"),
    "cr7_not_ready": ("builtin-only", "summary_200_while_running",
                      [H + "test_runs_async.py::test_not_ready_before_completion_and_status_stays_responsive"],
                      ("passed", "xfailed")),  # xfailed = API-DISC-05 window observed (timing-dependent)
    "cr8_precise_xfail": ("builtin-only", "pivot_500",
                          [H + "test_results_contract.py::test_pivot_rollup_with_user_layout"], "xfailed"),
    "cr2_2_bounded_wait": ("builtin-only", "stuck_running",
                           [H + "test_runs_async.py::test_not_ready_before_completion_and_status_stays_responsive"],
                           None),
    "cr2_6_early_report_validated": ("builtin-only", "checks_garbage_while_running",
                                     [H + "test_runs_async.py::test_not_ready_before_completion_and_status_stays_responsive"],
                                     None),
    "cr2_4_query_isolation": ("builtin-only", "shared_owner_for_query",
                              [H + "test_owner_isolation.py::test_query_endpoints_and_group_locators_are_owner_scoped"],
                              "passed"),
}
EXTRA_ENV = {"cr2_2_bounded_wait": {"QA_RUN_TIMEOUT": "30"}}


@pytest.fixture(scope="module")
def servers(tmp_path_factory):
    out = {}
    managers = []
    for mode in ("builtin-only", "trusted-local"):
        cm = backend_with_fixtures(tmp_path_factory.mktemp(mode), mode)
        out[mode] = cm.__enter__()
        managers.append(cm)
    yield out
    for cm in managers:
        cm.__exit__(None, None, None)


@pytest.mark.parametrize("case", sorted(CASES))
def test_mutation_is_detected(servers, case):
    mode, mutation, nodes, _ = CASES[case]
    backend, fixtures = servers[mode]
    proc = run_nodes(backend.url, fixtures, nodes, {mutation}, timeout=180, extra_env=EXTRA_ENV.get(case))
    assert outcome(proc) == "failed", proc.stdout[-3000:]


@pytest.mark.parametrize("case", sorted(c for c in CASES if CASES[c][3]))
def test_control_without_mutation(servers, case):
    mode, _, nodes, expected = CASES[case]
    backend, fixtures = servers[mode]
    proc = run_nodes(backend.url, fixtures, nodes, set())
    allowed = expected if isinstance(expected, tuple) else (expected,)
    assert outcome(proc) in allowed, proc.stdout[-3000:]


def test_policy_control_on_real_builtin_only(servers):
    """Control for cr3: the same nodes pass against a genuinely builtin-only server."""
    backend, fixtures = servers["builtin-only"]
    proc = run_nodes(backend.url, fixtures, CASES["cr3_policy_canary"][2], set())
    assert outcome(proc) == "passed", proc.stdout[-3000:]
