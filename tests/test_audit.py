"""Stage 7: audit schema, errors and reproducible D1 edge cases."""
import json
from pathlib import Path

import pytest

from decision_diff.audit import AuditFailure, audit_checks_report, generate_audit
from decision_diff.configs import REAL
from decision_diff.core import ArrayRule, NormalizationConfig, NormalizationError, compare, normalize
from decision_diff.procedure_api import ProcedureContractError, process_pair, validate_normalized


def test_valid_report_rows_allow_fail_verdicts_and_truncated_ids():
    row = {'LABEL': 'Test', 'SOURCE': 'AFTER', 'ARGUMENT': 'X', 'CNT': 55,
           'TOTAL': 100, 'METRIC': 0.55, 'APP_IDS': ['A'], 'RESULT': 'FAIL',
           'CONFIDENCE': 'LOW'}
    checks = audit_checks_report({'checks': [row], 'diagnostics': []})
    assert all(item['ok'] for item in checks)


def test_report_validation_catches_runner_errors_and_bad_rows():
    checks = audit_checks_report({'checks': [{'RESULT': 'OK'}],
                                 'diagnostics': ['runtime failed']})
    assert all(not item['ok'] for item in checks)


def test_report_requires_contract_fields():
    with pytest.raises(AuditFailure):
        audit_checks_report({'checks': []})


def test_default_adapter_real_pair_has_consistent_change_counts():
    examples = Path(__file__).resolve().parents[1] / 'examples'
    before = json.loads((examples / 'I32554354_other.json').read_text(encoding='utf-8'))
    after = json.loads((examples / 'I32554354.json').read_text(encoding='utf-8'))
    result = process_pair(before, after, app_id='I32554354')
    assert len(result['normalized']) == 264
    assert len(result['comparison']) == 141
    assert result['segment']['DECISION_CHANGED'] == 1
    assert not any(r['PATH'] in REAL.excluded_paths for r in result['comparison'])


def test_indexed_vector_reordering_is_a_real_change():
    config = NormalizationConfig(arrays={'vector': ArrayRule('index')})
    b = normalize({'vector': [0.1, 0.9]}, 'A', 'BEFORE', config)
    a = normalize({'vector': [0.9, 0.1]}, 'A', 'AFTER', config)
    assert sum(r['CHANGE_TYPE'] == 'VALUE_CHANGED' for r in compare(b, a)) == 2


def test_keyed_array_reorder_and_new_attribute():
    config = NormalizationConfig(arrays={'products': ArrayRule('fields', ('id',))})
    b = normalize({'products': [{'id': 'A', 'limit': 10}, {'id': 'B', 'limit': 20}]},
                  'A', 'BEFORE', config)
    a = normalize({'products': [{'id': 'B', 'limit': 20}, {'id': 'A', 'limit': 10, 'new': True}]},
                  'A', 'AFTER', config)
    results = compare(b, a)
    assert [r['CHANGE_TYPE'] for r in results].count('ATTRIBUTE_NEW') == 1
    assert [r['CHANGE_TYPE'] for r in results].count('VALUE_CHANGED') == 0


def test_bad_custom_output_is_detected():
    with pytest.raises(ProcedureContractError):
        validate_normalized([{'APP_ID': 'A', 'VALUE': '1'}], app_id='A')


def test_unknown_array_is_not_silently_indexed():
    with pytest.raises(NormalizationError):
        normalize({'unknown': [1, 2]}, 'A', 'BEFORE', NormalizationConfig(arrays={}))


def test_audit_database_real_duckdb_fixture():
    duckdb = pytest.importorskip('duckdb')
    from decision_diff.base_facts import BASE_DIMS, materialize_base_facts

    db = duckdb.connect(':memory:')
    db.execute('CREATE TABLE normalized_union (APP_ID VARCHAR, SOURCE VARCHAR, PREFIX VARCHAR, CLASS VARCHAR, SUFFIX VARCHAR, ARRAY_KEY VARCHAR, KEY VARCHAR, PATH VARCHAR, VALUE VARCHAR, ADJUSTED_VALUE VARCHAR)')
    db.execute('CREATE TABLE comparison (APP_ID VARCHAR, PATH VARCHAR, ARRAY_KEY VARCHAR, DIFF_FLAG INTEGER, CHANGE_TYPE VARCHAR)')
    extra = [f for f in BASE_DIMS if f not in {'PREFIX', 'CLASS', 'SUFFIX', 'PATH', 'ARRAY_KEY', 'KEY', 'VALUE_ADJUSTED', 'SOURCE', 'DIFF_FLAG', 'CHANGE_TYPE'}]
    db.execute('CREATE TABLE segments (APP_ID VARCHAR, ' + ', '.join(f'"{f}" VARCHAR' if f != 'DECISION_CHANGED' else '"DECISION_CHANGED" INTEGER' for f in extra) + ')')
    db.execute("INSERT INTO normalized_union VALUES ('A','BEFORE','decisionResult','decision','','','decision','decisionResult.decision','REJECT','REJECT'),('A','AFTER','decisionResult','decision','','','decision','decisionResult.decision','APPROVE','APPROVE'),('B','BEFORE','decisionResult','decision','','','decision','decisionResult.decision','REJECT','REJECT'),('B','AFTER','decisionResult','decision','','','decision','decisionResult.decision','APPROVE','APPROVE')")
    db.execute("INSERT INTO comparison VALUES ('A','decisionResult.decision','',1,'VALUE_CHANGED'),('B','decisionResult.decision','',1,'VALUE_CHANGED')")
    def seg(app):
        return (app, *[1 if f == 'DECISION_CHANGED' else 'REJECT' if f == 'DECISION_BEFORE' else 'APPROVE' if f == 'DECISION_AFTER' else '' for f in extra])
    db.executemany('INSERT INTO segments VALUES (' + ','.join('?' for _ in range(len(extra)+1)) + ')', [seg('A'),seg('B')])
    materialize_base_facts(db)
    report = generate_audit(db, checks_report={'checks': [], 'diagnostics': []}, sample_limit=10)
    assert report['ok'], [x for x in report['checks'] if not x['ok']]
    db.execute("UPDATE comparison SET DIFF_FLAG = 0 WHERE APP_ID = 'A'")
    failed = generate_audit(db, sample_limit=10)
    assert not failed['ok']
    assert any(x['name'] == 'comparison_valid_statuses' and not x['ok'] for x in failed['checks'])
    db.close()
