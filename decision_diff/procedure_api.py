"""Stable, runner-friendly D1 procedure adapters (no I/O, no code execution).

The host D2 runner owns execution isolation, artifact paths, persistence and logs.
These functions are the default trusted procedures, not a script sandbox.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .configs import REAL
from .core import ArrayRule, NormalizationConfig, compare, normalize
from .segments import build_segment

NORMALIZED_COLUMNS = frozenset({
    'APP_ID','SOURCE','PREFIX','CLASS','SUFFIX','ARRAY_KEY','KEY',
    'PATH','VALUE','ADJUSTED_VALUE',
})
COMPARISON_COLUMNS = frozenset({
    'APP_ID','PREFIX','CLASS','SUFFIX','ARRAY_KEY','KEY','PATH',
    'VALUE_BEFORE','VALUE_AFTER','ADJUSTED_BEFORE','ADJUSTED_AFTER',
    'DIFF_FLAG','CHANGE_TYPE',
})
SEGMENT_COLUMNS = frozenset({
    'APP_ID','DECISION_BEFORE','DECISION_AFTER','DECISION_CHANGED',
    'PRODUCTS','TOP_OFFER_BEFORE','TOP_OFFER_AFTER','PARTNER_TYPE',
    'ROUTING_METHOD','PD_MODEL_BEFORE','PD_MODEL_AFTER','CUTOFF_BEFORE',
    'CUTOFF_AFTER','REJECT_REASON_BEFORE','REJECT_REASON_AFTER',
    'SCORE_OKB_BEFORE','SCORE_OKB_AFTER',
})
CHANGE_TYPES = frozenset({'SAME','VALUE_CHANGED','ATTRIBUTE_NEW','ATTRIBUTE_LOST'})


class ProcedureContractError(ValueError):
    """An adapter input or output violates the shared processing contract."""


def config_from_dict(raw: Mapping[str, Any] | None) -> NormalizationConfig:
    """Turn JSON-safe configuration into the existing immutable normalizer config.

    None selects the dataset's known default REAL config. Empty dict is an
    explicitly empty config, not an alias for REAL.
    """
    if raw is None:
        return REAL
    if not isinstance(raw, Mapping):
        raise ProcedureContractError('Normalization config must be a JSON object')
    permitted = {'arrays','excluded_paths','buckets','display_suffixes'}
    unknown = set(raw) - permitted
    if unknown:
        raise ProcedureContractError(f'Unknown config properties: {sorted(unknown)}')
    arrays_raw = raw.get('arrays', {})
    if not isinstance(arrays_raw, Mapping):
        raise ProcedureContractError('arrays must be an object')
    arrays: dict[str, ArrayRule] = {}
    for path, spec in arrays_raw.items():
        if not isinstance(path, str) or not path or not isinstance(spec, Mapping):
            raise ProcedureContractError('Each array rule needs a nonempty path and object')
        if set(spec) - {'mode','keys','scalar_suffix'}:
            raise ProcedureContractError(f'Unexpected array rule options at {path}')
        mode = spec.get('mode')
        keys = spec.get('keys', [])
        suffix = spec.get('scalar_suffix', '')
        if mode not in ('fields','index','value'):
            raise ProcedureContractError(f'Unknown array mode at {path}: {mode!r}')
        if not isinstance(keys, list) or not all(isinstance(x, str) and x for x in keys):
            raise ProcedureContractError(f'Invalid keys at {path}')
        if mode == 'fields' and not keys:
            raise ProcedureContractError(f'fields array must provide keys at {path}')
        if mode != 'fields' and keys:
            raise ProcedureContractError(f'Keys not allowed in {mode} array at {path}')
        if not isinstance(suffix, str):
            raise ProcedureContractError(f'Invalid scalar_suffix at {path}')
        arrays[path] = ArrayRule(mode, tuple(keys), suffix)

    excluded = raw.get('excluded_paths', [])
    if not isinstance(excluded, list) or not all(isinstance(x,str) for x in excluded):
        raise ProcedureContractError('excluded_paths must be an array of strings')
    display = raw.get('display_suffixes', {})
    if not isinstance(display, Mapping) or not all(isinstance(k,str) and isinstance(v,str) for k,v in display.items()):
        raise ProcedureContractError('display_suffixes must be a string map')
    buckets_raw = raw.get('buckets', {})
    if not isinstance(buckets_raw, Mapping):
        raise ProcedureContractError('buckets must be an object')
    buckets: dict[str, tuple[tuple[float, str],...]] = {}
    for path, definitions in buckets_raw.items():
        if not isinstance(path,str) or not isinstance(definitions,list):
            raise ProcedureContractError('buckets must map paths to lists')
        parsed: list[tuple[float,str]] = []
        for definition in definitions:
            if not isinstance(definition,list) or len(definition)!=2 or not isinstance(definition[0],(int,float)) or isinstance(definition[0],bool) or not isinstance(definition[1],str):
                raise ProcedureContractError(f'Invalid bucket at {path}')
            parsed.append((float(definition[0]), definition[1]))
        if any(parsed[i][0] >= parsed[i+1][0] for i in range(len(parsed)-1)):
            raise ProcedureContractError(f'Bucket bounds must increase at {path}')
        buckets[path] = tuple(parsed)
    return NormalizationConfig(
        arrays=arrays, excluded_paths=frozenset(excluded),
        buckets=buckets, display_suffixes=dict(display),
    )


def config_to_dict(config: NormalizationConfig) -> dict[str, Any]:
    """Export a configurable policy for JSON/UI editing."""
    return {
        'arrays': {path: {'mode': rule.mode, 'keys': list(rule.keys),
                          'scalar_suffix': rule.scalar_suffix}
                   for path, rule in sorted(config.arrays.items())},
        'excluded_paths': sorted(config.excluded_paths),
        'buckets': {path: [[bound, label] for bound, label in thresholds]
                    for path, thresholds in config.buckets.items()},
        'display_suffixes': dict(config.display_suffixes),
    }


def validate_normalized(rows: Iterable[Mapping[str, Any]], *, app_id: str | None = None,
                        source: str | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    identities: set[tuple[str,str,str,str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ProcedureContractError(f'Normalized row {index} is not an object')
        missing = NORMALIZED_COLUMNS - row.keys()
        if missing:
            raise ProcedureContractError(f'Normalized row {index} missing {sorted(missing)}')
        if row['SOURCE'] not in ('BEFORE','AFTER'):
            raise ProcedureContractError(f'Invalid SOURCE at normalized row {index}')
        if source is not None and row['SOURCE'] != source:
            raise ProcedureContractError(f'Wrong SOURCE at normalized row {index}')
        if app_id is not None and row['APP_ID'] != app_id:
            raise ProcedureContractError(f'Wrong APP_ID at normalized row {index}')
        if not all(isinstance(row[k], str) for k in NORMALIZED_COLUMNS):
            raise ProcedureContractError(f'Non-string normalized field at row {index}')
        if not row['PATH']:
            raise ProcedureContractError(f'Empty PATH at row {index}')
        identity = (row['SOURCE'], row['APP_ID'], row['PATH'], row['ARRAY_KEY'])
        if identity in identities:
            raise ProcedureContractError(f'Duplicate normalized key: {identity}')
        identities.add(identity)
        result.append(dict(row))
    return result


def validate_comparison(rows: Iterable[Mapping[str, Any]], *, app_id: str | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    identities: set[tuple[str,str,str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or COMPARISON_COLUMNS - row.keys():
            raise ProcedureContractError(f'Invalid comparison shape at row {index}')
        if app_id is not None and row['APP_ID'] != app_id:
            raise ProcedureContractError(f'Wrong APP_ID at comparison row {index}')
        if row['CHANGE_TYPE'] not in CHANGE_TYPES or type(row['DIFF_FLAG']) is not int or row['DIFF_FLAG'] not in (0,1):
            raise ProcedureContractError(f'Invalid change status at row {index}')
        if row['DIFF_FLAG'] != int(row['CHANGE_TYPE'] != 'SAME'):
            raise ProcedureContractError(f'Conflicting change status at row {index}')
        if not all(isinstance(row[k],str) for k in COMPARISON_COLUMNS - {'DIFF_FLAG'}):
            raise ProcedureContractError(f'Non-string comparison field at row {index}')
        identity = (row['APP_ID'],row['PATH'],row['ARRAY_KEY'])
        if identity in identities:
            raise ProcedureContractError(f'Duplicate comparison key: {identity}')
        identities.add(identity)
        result.append(dict(row))
    return result


def validate_segment(row: Mapping[str, Any], *, app_id: str | None = None) -> dict[str, Any]:
    if not isinstance(row, Mapping) or SEGMENT_COLUMNS - row.keys():
        raise ProcedureContractError(f'Invalid segment shape: missing {sorted(SEGMENT_COLUMNS - row.keys()) if isinstance(row, Mapping) else "all"}')
    if app_id is not None and row['APP_ID'] != app_id:
        raise ProcedureContractError('Wrong APP_ID in segment')
    if type(row['DECISION_CHANGED']) is not int or row['DECISION_CHANGED'] not in (0,1):
        raise ProcedureContractError('DECISION_CHANGED must be integer 0 or 1')
    if not all(isinstance(row[k],str) for k in SEGMENT_COLUMNS - {'DECISION_CHANGED'}):
        raise ProcedureContractError('Segment fields must be strings except DECISION_CHANGED')
    if row['DECISION_CHANGED'] != int(row['DECISION_BEFORE'] != row['DECISION_AFTER']):
        raise ProcedureContractError('DECISION_CHANGED inconsistent with decisions')
    return dict(row)


def normalize_document(document: Mapping[str, Any], *, app_id: str, source: str,
                       params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Default trusted normalize entrypoint. No filesystem or SQL side effects."""
    if not isinstance(document, Mapping):
        raise ProcedureContractError('Input document must be a JSON object')
    config = config_from_dict(params)
    return validate_normalized(normalize(document, app_id, source, config), app_id=app_id, source=source)


def compare_rows(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]],
                 *, app_id: str) -> list[dict[str, Any]]:
    """Default trusted compare entrypoint; accepts normalized rows only."""
    lhs = validate_normalized(before, app_id=app_id, source='BEFORE')
    rhs = validate_normalized(after, app_id=app_id, source='AFTER')
    return validate_comparison(compare(lhs, rhs), app_id=app_id)


def segment_documents(before_doc: Mapping[str, Any], after_doc: Mapping[str, Any],
                      *, app_id: str) -> dict[str, Any]:
    """Default trusted segment projection, with explicitly documented product policy."""
    if not isinstance(before_doc, Mapping) or not isinstance(after_doc, Mapping):
        raise ProcedureContractError('Segment documents must be objects')
    return validate_segment(build_segment(before_doc, after_doc, app_id), app_id=app_id)


def process_pair(before_doc: Mapping[str, Any], after_doc: Mapping[str, Any],
                *, app_id: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Local integration helper; D2 may independently call each individual stage.

    Result keys are descriptive only, not authoritative HTTP DTO names.
    """
    before = normalize_document(before_doc, app_id=app_id, source='BEFORE', params=params)
    after = normalize_document(after_doc, app_id=app_id, source='AFTER', params=params)
    return {
        'normalized': [*before, *after],
        'comparison': compare_rows(before, after, app_id=app_id),
        'segment': segment_documents(before_doc, after_doc, app_id=app_id),
    }
