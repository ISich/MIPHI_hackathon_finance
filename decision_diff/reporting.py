"""Storage-agnostic summary and pivot fact aggregation.

Each comparison attribute can yield up to two vertical reporting facts, one per
actually present side. CNT counts attribute occurrences in that group (one per
APP_ID per attribute identity), not distinct applications across unrelated paths.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def summarize(rows: Iterable[Mapping[str, Any]], segments: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    changed: set[str] = set()
    attributes_changed = 0
    by_type: dict[str, int] = defaultdict(int)
    for row in rows:
        by_type[str(row['CHANGE_TYPE'])] += 1
        if int(row['DIFF_FLAG']) == 1:
            changed.add(str(row['APP_ID']))
            attributes_changed += 1
    segment_rows = list(segments)
    decision_changed = sum(int(s['DECISION_CHANGED']) for s in segment_rows)
    before_approved = sum(s['DECISION_BEFORE'] == 'APPROVE' for s in segment_rows)
    after_approved = sum(s['DECISION_AFTER'] == 'APPROVE' for s in segment_rows)
    total = len(segment_rows)
    return {
        'total_apps': total,
        'changed_apps': len(changed),
        'decision_changed_apps': decision_changed,
        'changed_attributes': attributes_changed,
        'change_types': dict(sorted(by_type.items())),
        'approval_rate_before': round(before_approved / total, 6) if total else 0,
        'approval_rate_after': round(after_approved / total, 6) if total else 0,
    }


def pivot_facts(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Facts grouped by full attribute identity, value, diff status and slice.

    The resulting fact table is intended for a pivot UI and should NOT be summed
    across unrelated attributes to obtain a global count of applications.
    """
    groups: dict[tuple[str, ...], set[str]] = defaultdict(set)
    dims = ('PREFIX', 'CLASS', 'SUFFIX', 'ARRAY_KEY', 'KEY', 'PATH')
    for row in rows:
        base = tuple(str(row[k]) for k in dims)
        for side, adjusted in [('BEFORE', 'ADJUSTED_BEFORE'), ('AFTER', 'ADJUSTED_AFTER')]:
            if row['CHANGE_TYPE'] == 'ATTRIBUTE_NEW' and side == 'BEFORE':
                continue
            if row['CHANGE_TYPE'] == 'ATTRIBUTE_LOST' and side == 'AFTER':
                continue
            key = (*base, str(row[adjusted]), str(row['DIFF_FLAG']), side)
            groups[key].add(str(row['APP_ID']))
    return [dict(zip((*dims, 'VALUE_ADJUSTED', 'DIFF_FLAG', 'SOURCE'), key), CNT=len(app_ids))
            for key, app_ids in sorted(groups.items())]
