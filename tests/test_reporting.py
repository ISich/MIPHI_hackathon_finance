import json
from pathlib import Path

from decision_diff.configs import REAL, TEACHING
from decision_diff.core import normalize_pair
from decision_diff.segments import build_segment
from decision_diff.reporting import summarize, pivot_facts

ROOT = Path(__file__).resolve().parents[1] / 'examples'


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def test_real_segments_include_all_contract_fields():
    b, a = load('I32554354_other.json'), load('I32554354.json')
    segment = build_segment(b, a, 'I32554354')
    assert segment['DECISION_BEFORE'] == 'REJECT'
    assert segment['DECISION_AFTER'] == 'APPROVE'
    assert segment['DECISION_CHANGED'] == 1
    assert segment['PRODUCTS'] == 'DO_ZARPL;KUPI_KUPI'
    assert segment['TOP_OFFER_BEFORE'] == ''
    assert segment['TOP_OFFER_AFTER'] == 'KUPI_KUPI'
    assert segment['PD_MODEL_BEFORE'] == 'ML_MICRO_LOAN_V1'
    assert segment['SCORE_OKB_AFTER'] == '710'
    assert len(segment) == 17


def test_summary_distinguishes_attributes_and_applications():
    b, a = load('I32554354_other.json'), load('I32554354.json')
    _, comparison = normalize_pair(b, a, 'I32554354', REAL)
    result = summarize(comparison, [build_segment(b, a, 'I32554354')])
    assert result['total_apps'] == 1
    assert result['changed_apps'] == 1
    assert result['decision_changed_apps'] == 1
    assert result['changed_attributes'] > 1


def test_pivot_facts_keep_sources_and_skip_missing_side():
    before = load('01_response_BEFORE_MASTER_app1001.json')
    after = load('02_response_AFTER_BETA_app1001.json')
    _, comparison = normalize_pair(before, after, '1001', TEACHING)
    facts = pivot_facts(comparison)
    risk = [r for r in facts if r['PATH'] == 'company.decisionResult.riskSegment']
    assert len(risk) == 1
    assert risk[0]['SOURCE'] == 'AFTER'
    assert risk[0]['CNT'] == 1
    assert set(r['SOURCE'] for r in facts) == {'BEFORE', 'AFTER'}
