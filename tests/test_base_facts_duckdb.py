"""Integration tests run on developer machine with pip-installed DuckDB."""
import pytest

from decision_diff.base_facts import BASE_DIMS, materialize_base_facts
from decision_diff.pivot_rollup import PivotRollup


def test_materialization_and_memberships_with_duckdb():
    duckdb = pytest.importorskip('duckdb')
    db = duckdb.connect(':memory:')
    db.execute('CREATE TABLE normalized_union (APP_ID VARCHAR, SOURCE VARCHAR, PREFIX VARCHAR, CLASS VARCHAR, SUFFIX VARCHAR, ARRAY_KEY VARCHAR, KEY VARCHAR, PATH VARCHAR, VALUE VARCHAR, ADJUSTED_VALUE VARCHAR)')
    db.execute('CREATE TABLE comparison (APP_ID VARCHAR, PATH VARCHAR, ARRAY_KEY VARCHAR, DIFF_FLAG INTEGER, CHANGE_TYPE VARCHAR)')
    fields = ', '.join(f'"{f}" VARCHAR' for f in BASE_DIMS if f not in {'PREFIX', 'CLASS', 'SUFFIX', 'PATH', 'ARRAY_KEY', 'KEY', 'VALUE_ADJUSTED', 'SOURCE', 'DIFF_FLAG', 'CHANGE_TYPE'})
    db.execute('CREATE TABLE segments (APP_ID VARCHAR, ' + fields + ')')
    db.execute("INSERT INTO normalized_union VALUES ('A','BEFORE','decisionResult','decision','','','decision','decisionResult.decision','REJECT','REJECT'),('A','AFTER','decisionResult','decision','','','decision','decisionResult.decision','APPROVE','APPROVE'),('B','BEFORE','decisionResult','decision','','','decision','decisionResult.decision','REJECT','REJECT'),('B','AFTER','decisionResult','decision','','','decision','decisionResult.decision','APPROVE','APPROVE')")
    db.execute("INSERT INTO comparison VALUES ('A','decisionResult.decision','',1,'VALUE_CHANGED'),('B','decisionResult.decision','',1,'VALUE_CHANGED')")
    extra_count = len([f for f in BASE_DIMS if f not in {'PREFIX', 'CLASS', 'SUFFIX', 'PATH', 'ARRAY_KEY', 'KEY', 'VALUE_ADJUSTED', 'SOURCE', 'DIFF_FLAG', 'CHANGE_TYPE'}])
    placeholders = ','.join('?' for _ in range(extra_count + 1))
    db.executemany('INSERT INTO segments VALUES ('+placeholders+')', [('A', *(['']*extra_count)),('B', *(['']*extra_count))])
    counts = materialize_base_facts(db)
    assert counts == {'base_facts': 2, 'base_membership': 4}
    with pytest.raises(ValueError):
        materialize_base_facts(db)
    pivot = PivotRollup(db, run_id='R1', data_revision='v1', signing_secret=b'secret')
    result = pivot.cells(dimensions=['SOURCE'])
    assert [x['cnt'] for x in result['items']] == [2,2]
    assert pivot.members(result['items'][1]['group_locator'])['items'] == ['A','B']
    db.close()
