"""Check additive materialization algorithm against a portable SQL engine.
DuckDB-specific table catalog behavior is simulated by a tiny compatibility shim.
The separate test_base_facts_duckdb.py covers real DuckDB when installed.
"""
from __future__ import annotations

import sqlite3

import pytest

from decision_diff.base_facts import BASE_DIMS, SEGMENT_DIMS, materialize_base_facts


class CatalogShim:
    def __init__(self, con):
        self.con = con

    def execute(self, sql, params=None):
        if 'information_schema.tables' in sql:
            # The only DuckDB-specific catalog query in the materializer.
            if params:
                return self.con.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", params
                )
            return self.con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name IN ('base_facts','base_membership')"
            )
        return self.con.execute(sql, params or [])


def setup():
    con = sqlite3.connect(':memory:', isolation_level=None)
    con.execute('CREATE TABLE normalized_union (APP_ID TEXT, SOURCE TEXT, PREFIX TEXT, CLASS TEXT, SUFFIX TEXT, ARRAY_KEY TEXT, KEY TEXT, PATH TEXT, VALUE TEXT, ADJUSTED_VALUE TEXT)')
    con.execute('CREATE TABLE comparison (APP_ID TEXT, PATH TEXT, ARRAY_KEY TEXT, DIFF_FLAG INTEGER, CHANGE_TYPE TEXT)')
    con.execute('CREATE TABLE segments (APP_ID TEXT, ' + ', '.join(f'"{c}" TEXT' for c in SEGMENT_DIMS) + ')')
    con.executemany('INSERT INTO normalized_union VALUES (?,?,?,?,?,?,?,?,?,?)', [
        ('A','BEFORE','decisionResult','decision','','','decision','decisionResult.decision','REJECT','REJECT'),
        ('A','AFTER','decisionResult','decision','','','decision','decisionResult.decision','APPROVE','APPROVE'),
        ('B','BEFORE','decisionResult','decision','','','decision','decisionResult.decision','REJECT','REJECT'),
        ('B','AFTER','decisionResult','decision','','','decision','decisionResult.decision','APPROVE','APPROVE'),
    ])
    con.executemany('INSERT INTO comparison VALUES (?,?,?,?,?)', [
        ('A','decisionResult.decision','',1,'VALUE_CHANGED'),
        ('B','decisionResult.decision','',1,'VALUE_CHANGED'),
    ])
    con.executemany('INSERT INTO segments VALUES (' + ','.join('?' for _ in range(len(SEGMENT_DIMS)+1)) + ')', [
        ('A', *([''] * len(SEGMENT_DIMS))), ('B', *([''] * len(SEGMENT_DIMS))),
    ])
    return CatalogShim(con)


def test_base_facts_materialized_distinct_and_replace():
    con = setup()
    assert materialize_base_facts(con) == {'base_facts': 2, 'base_membership': 4}
    actual = con.execute('SELECT SOURCE, CNT FROM base_facts ORDER BY SOURCE').fetchall()
    assert actual == [('AFTER', 2), ('BEFORE', 2)]
    assert con.execute('SELECT COUNT(*) FROM base_membership').fetchone()[0] == 4
    with pytest.raises(ValueError, match='already exist'):
        materialize_base_facts(con)
    assert materialize_base_facts(con, replace=True) == {'base_facts': 2, 'base_membership': 4}


def test_missing_comparison_rolls_back():
    con = setup()
    con.execute('DELETE FROM comparison WHERE APP_ID=?', ['B'])
    with pytest.raises(ValueError, match='Normalized rows differ'):
        materialize_base_facts(con)
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='base_facts'").fetchone()[0] == 0
