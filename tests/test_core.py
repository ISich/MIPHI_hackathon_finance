import csv
import json
from pathlib import Path

import pytest

from decision_diff import ArrayRule, NormalizationConfig, normalize, compare, normalize_pair
from decision_diff.configs import REAL, TEACHING
from decision_diff.core import NormalizationError

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding='utf-8'))


def expected(name):
    with (EXAMPLES / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def legacy_columns(rows):
    return [{k: row[k] for k in ('APP_ID', 'SOURCE','PREFIX','CLASS','SUFFIX','ARRAY_KEY','KEY','VALUE','ADJUSTED_VALUE')} for row in rows]


def test_teaching_matches_reference_csv_exactly():
    before = normalize(load('01_response_BEFORE_MASTER_app1001.json'), '1001', 'BEFORE', TEACHING)
    after = normalize(load('02_response_AFTER_BETA_app1001.json'), '1001', 'AFTER', TEACHING)
    assert sorted(legacy_columns(before),key=str) == sorted(expected('03_normalized_BEFORE_app1001.csv'),key=str)
    assert sorted(legacy_columns(after),key=str) == sorted(expected('04_normalized_AFTER_app1001.csv'),key=str)
    changes = compare(before, after)
    assert len(before) == 12 and len(after) == 14
    assert len(changes) == 14
    assert sum(r['DIFF_FLAG'] for r in changes) == 6  # Verified from the supplied CSVs; README says 5 incorrectly
    assert sum(r['CHANGE_TYPE']=='ATTRIBUTE_NEW' for r in changes) == 2
    assert next(r for r in changes if r['KEY']=='value' and r['ARRAY_KEY']=='TAKEUP_RATE_IP')['CHANGE_TYPE'] == 'VALUE_CHANGED'


def test_real_array_identities_and_null():
    doc = load('I32554354.json')
    rows = normalize(doc, 'I32554354', 'BEFORE', REAL)
    offers = [r for r in rows if r['PATH']=='decisionResult.available_offers.product_name']
    assert len(offers) == 3
    assert len({r['ARRAY_KEY'] for r in offers}) == 3
    assert {r['ARRAY_KEY'] for r in offers} == {'15210:standard', '15210:manual', '5123:standard'}
    assert not any(r['PATH'] in REAL.excluded_paths for r in rows)
    assert any(r['VALUE']=='NULL' for r in rows)
    assert {r['ARRAY_KEY'] for r in rows if r['PATH']=='decisionResult.scoring.value'} == {
        'ML_MICRO_LOAN_V1|0', 'ML_MICRO_LOAN_V1|1', 'ML_MICRO_LOAN_V1|2',
        'ML_MICRO_LOAN_V2|0', 'ML_MICRO_LOAN_V2|1', 'ML_MICRO_LOAN_V2|2',
    }


def test_real_pair_has_true_changes_not_technical():
    _, changed = normalize_pair(load('I32554354_other.json'), load('I32554354.json'), 'I32554354', REAL)
    assert any(r['PATH']=='decisionResult.decision' and r['CHANGE_TYPE']=='VALUE_CHANGED' for r in changed)
    assert any(r['CHANGE_TYPE']=='ATTRIBUTE_NEW' for r in changed)


def test_null_is_not_missing():
    config = NormalizationConfig(arrays={})
    rows = compare(normalize({'a':None},'1','BEFORE',config),normalize({},'1','AFTER',config))
    assert rows[0]['CHANGE_TYPE']=='ATTRIBUTE_LOST'
    assert rows[0]['VALUE_BEFORE']=='NULL'


def test_reorder_keyed_array_does_not_create_differences():
    config = NormalizationConfig(arrays={'a': ArrayRule('fields', ('id',))})
    before = normalize({'a':[{'id':'X','v':1},{'id':'Y','v':2}]},'1','BEFORE',config)
    after = normalize({'a':[{'id':'Y','v':2},{'id':'X','v':1}]},'1','AFTER',config)
    assert all(r['CHANGE_TYPE']=='SAME' for r in compare(before,after))


def test_duplicate_array_key_is_rejected():
    config = NormalizationConfig(arrays={'a': ArrayRule('fields', ('id',))})
    with pytest.raises(NormalizationError):
        normalize({'a':[{'id':1,'v':2},{'id':1,'v':3}]},'1','BEFORE',config)


def test_unconfigured_array_is_rejected():
    with pytest.raises(NormalizationError):
        normalize({'a':[1,2]},'1','BEFORE',NormalizationConfig(arrays={}))
