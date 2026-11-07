from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_diff.configs import REAL, TEACHING
from decision_diff.procedure_api import (
    ProcedureContractError, compare_rows, config_from_dict, config_to_dict,
    normalize_document, process_pair, validate_comparison, validate_normalized,
    validate_segment,
)

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def _load(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding='utf-8'))


def test_config_round_trip_and_default():
    assert config_from_dict(None) == REAL
    assert config_from_dict(config_to_dict(REAL)) == REAL
    assert config_from_dict(config_to_dict(TEACHING)) == TEACHING
    assert config_from_dict({}).arrays == {}


def test_real_pair_does_not_change_core_results():
    b = _load('I32554354_other.json')
    a = _load('I32554354.json')
    result = process_pair(b, a, app_id='I32554354')
    assert len(result['normalized']) == 264
    assert len(result['comparison']) == 141
    assert result['segment']['DECISION_CHANGED'] == 1
    assert {row['SOURCE'] for row in result['normalized']} == {'BEFORE', 'AFTER'}


def test_comparison_adapter_rejects_cross_app_rows():
    rows = normalize_document({'a': 3}, app_id='A', source='BEFORE', params={})
    with pytest.raises(ProcedureContractError, match='Wrong APP_ID'):
        compare_rows(rows, [], app_id='B')


def test_invalid_outputs_are_caught_before_db_writes():
    row = normalize_document({'a': None}, app_id='A', source='BEFORE', params={})[0]
    with pytest.raises(ProcedureContractError, match='Duplicate'):
        validate_normalized([row, row])
    with pytest.raises(ProcedureContractError, match='Invalid SOURCE'):
        validate_normalized([{**row, 'SOURCE': 'MASTER'}])
    result = compare_rows([row], [], app_id='A')[0]
    with pytest.raises(ProcedureContractError, match='Conflicting'):
        validate_comparison([{**result, 'DIFF_FLAG': 0}])


def test_segment_consistency():
    a = _load('I32554354.json')
    b = _load('I32554354_other.json')
    segment = process_pair(b, a, app_id='I32554354')['segment']
    with pytest.raises(ProcedureContractError, match='inconsistent'):
        validate_segment({**segment, 'DECISION_CHANGED': 0})


@pytest.mark.parametrize('bad', [
    {'arrays': {'x': {'mode': 'fields'}}},
    {'arrays': {'x': {'mode': 'index', 'keys': ['id']}}},
    {'buckets': {'x': [[0.8, 'high'], [0.3, 'low']]}},
    {'excluded_paths': 'appData.request_id'},
    {'surprise': 3},
])
def test_reject_invalid_configs(bad):
    with pytest.raises(ProcedureContractError):
        config_from_dict(bad)
