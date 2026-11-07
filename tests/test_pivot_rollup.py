"""Behavioral unit tests with stdlib sqlite.

This proves distinct rollup/locator logic but DOES NOT substitute for a real
DuckDB integration test for the materializer on the full run.
"""
import sqlite3
import pytest

from decision_diff.pivot_rollup import PivotRollup, PivotQueryError


@pytest.fixture
def small_db():
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE base_facts (fact_id INTEGER, PATH TEXT, SOURCE TEXT, CHANGE_TYPE TEXT, CNT INTEGER)')
    connection.execute('CREATE TABLE base_membership (fact_id INTEGER, APP_ID TEXT)')
    connection.executemany('INSERT INTO base_facts VALUES (?, ?, ?, ?, ?)', [
        (1, 'decisionResult.decision', 'AFTER', 'VALUE_CHANGED', 2),
        (2, 'decisionResult.product_trials.decision', 'AFTER', 'VALUE_CHANGED', 2),
        (3, 'decisionResult.decision', 'BEFORE', 'VALUE_CHANGED', 1),
    ])
    connection.executemany('INSERT INTO base_membership VALUES (?, ?)', [
        (1, 'A'), (1, 'B'), (2, 'B'), (2, 'C'), (3, 'A'),
    ])
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def rollup(small_db, monkeypatch):
    # SQLite lacks information_schema. The query contract is fully tested;
    # production schema validation is the responsibility of DuckDB tests.
    monkeypatch.setattr('decision_diff.pivot_rollup.ensure_schema', lambda _: None)
    return PivotRollup(small_db, run_id='R1', data_revision='rev1', signing_secret=b'test-secret-not-for-prod')


def test_rollup_distinct_across_overlapping_facts(rollup):
    result = rollup.cells(dimensions=['SOURCE'])
    assert [(r['dimensions']['SOURCE'], r['cnt']) for r in result['items']] == [
        ('AFTER', 3), ('BEFORE', 1)
    ]
    # Plain SUM(CNT) would be 4 for AFTER, which is wrong.
    locator = result['items'][0]['group_locator']
    assert rollup.members(locator, limit=2) == {
        'run_id': 'R1', 'data_revision': 'rev1',
        'total': 3, 'items': ['A', 'B'], 'limit': 2, 'offset': 0,
    }
    assert rollup.members(locator, limit=2, offset=2)['items'] == ['C']
    assert rollup.members(locator, limit=2, offset=20)['total'] == 3
    assert rollup.members(locator, limit=2, offset=20)['items'] == []


def test_filters_and_labeled_cells(rollup):
    result = rollup.cells(dimensions=['SOURCE', 'PATH'], filters={'CHANGE_TYPE':'VALUE_CHANGED'})
    assert result['total'] == 3
    lookup = {(x['dimensions']['SOURCE'], x['dimensions']['PATH']): x for x in result['items']}
    assert lookup[('AFTER', 'decisionResult.decision')]['cnt'] == 2
    assert lookup[('AFTER', 'decisionResult.product_trials.decision')]['cnt'] == 2
    result2 = rollup.cells(dimensions=['SOURCE'], filters={'PATH':['decisionResult.decision']})
    assert result2['items'][0]['cnt'] == 2


def test_locator_rejects_tampering_other_runs_and_unknown_fields(rollup, small_db):
    token = rollup.cells(dimensions=['SOURCE'])['items'][0]['group_locator']
    with pytest.raises(PivotQueryError):
        rollup.members(token + 'tampered')
    other = PivotRollup(small_db, run_id='R2', data_revision='rev1', signing_secret=b'test-secret-not-for-prod')
    with pytest.raises(PivotQueryError):
        other.members(token)
    with pytest.raises(PivotQueryError):
        rollup.cells(dimensions=['BAD'])
    with pytest.raises(PivotQueryError):
        rollup.cells(dimensions=['SOURCE'], filters={'PATH); DROP TABLE base_facts; --':'x'})
    with pytest.raises(PivotQueryError):
        rollup.cells(dimensions=['SOURCE'], limit=0)
