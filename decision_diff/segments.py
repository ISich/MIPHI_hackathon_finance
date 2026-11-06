"""One-row-per-application reporting dimensions for the comparison mart.

The comparison engine is independent from this domain-specific extraction.
The selection policy for representative product-level attributes is explicit.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _objects(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _value(value: Any) -> str:
    if value is None:
        return ''
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    return str(value)


def _trials(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _objects(_object(document.get('decisionResult')).get('product_trials'))


def _primary_trial(document: Mapping[str, Any]) -> dict[str, Any]:
    """Prefer top-ranked offered product; otherwise sort by product ID.

    One application can have many product trials. A single segment row cannot
    represent all their per-product model/cutoff values. Their full information
    remains available in the attribute comparison mart.
    """
    decision = _object(document.get('decisionResult'))
    trials = _trials(document)
    if not trials:
        return {}
    offers = _objects(decision.get('available_offers'))
    if offers:
        best = min(offers, key=lambda offer: (offer.get('rank') is None, offer.get('rank', 0)))
        for trial in trials:
            if str(trial.get('product_id')) == str(best.get('product_id')):
                return trial
    return min(trials, key=lambda trial: str(trial.get('product_id', '')))


def _trial_value(trial: dict[str, Any], *path: str) -> str:
    node: Any = trial
    for part in path:
        node = _object(node).get(part)
    return _value(node)


def build_segment(before: Mapping[str, Any], after: Mapping[str, Any], app_id: str) -> dict[str, Any]:
    """Build one report segment row, respecting the organizer's field contract."""
    before_decision = _object(before.get('decisionResult'))
    after_decision = _object(after.get('decisionResult'))
    bt, at = _primary_trial(before), _primary_trial(after)
    all_trials = [*_trials(before), *_trials(after)]
    products = sorted({_value(t.get('product_name') or t.get('product_id'))
                       for t in all_trials if t.get('product_name') or t.get('product_id') is not None})

    def top_offer(decision: dict[str, Any]) -> str:
        offers = _objects(decision.get('available_offers'))
        if not offers:
            return ''
        offer = min(offers, key=lambda item: (item.get('rank') is None, item.get('rank', 0)))
        return _value(offer.get('product_name') or offer.get('product_id'))

    d_before = _value(before_decision.get('decision'))
    d_after = _value(after_decision.get('decision'))
    # The dataset's decision is global; we retain per-product detail in the mart.
    return {
        'APP_ID': app_id,
        'DECISION_BEFORE': d_before,
        'DECISION_AFTER': d_after,
        'DECISION_CHANGED': int(d_before != d_after),
        'PRODUCTS': ';'.join(products),
        'TOP_OFFER_BEFORE': top_offer(before_decision),
        'TOP_OFFER_AFTER': top_offer(after_decision),
        'PARTNER_TYPE': _value(at.get('partner_type') or bt.get('partner_type')),
        'ROUTING_METHOD': _value(at.get('routing_method') or bt.get('routing_method')),
        'PD_MODEL_BEFORE': _trial_value(bt, 'scoring', 'pd', 'modelName'),
        'PD_MODEL_AFTER': _trial_value(at, 'scoring', 'pd', 'modelName'),
        'CUTOFF_BEFORE': _trial_value(bt, 'cutOff', 'name'),
        'CUTOFF_AFTER': _trial_value(at, 'cutOff', 'name'),
        'REJECT_REASON_BEFORE': _trial_value(bt, 'rejectReason'),
        'REJECT_REASON_AFTER': _trial_value(at, 'rejectReason'),
        'SCORE_OKB_BEFORE': _value(_object(before.get('characteristics')).get('score_okb')),
        'SCORE_OKB_AFTER': _value(_object(after.get('characteristics')).get('score_okb')),
    }
