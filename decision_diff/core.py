"""Pure normalization/comparison implementation. No API, storage, or UI dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Mapping

ArrayMode = Literal['fields', 'index', 'value']
Source = Literal['BEFORE', 'AFTER']


@dataclass(frozen=True)
class ArrayRule:
    mode: ArrayMode
    keys: tuple[str, ...] = ()
    # scalar arrays have no attribute name; SUFFIX can describe their semantic role
    scalar_suffix: str = ''


@dataclass(frozen=True)
class NormalizationConfig:
    arrays: Mapping[str, ArrayRule]
    excluded_paths: frozenset[str] = field(default_factory=frozenset)
    # path -> thresholds; buckets follow (previous, bound] convention
    buckets: Mapping[str, tuple[tuple[float, str], ...]] = field(default_factory=dict)
    # Optional presentation-only context labels for simplified teaching schemes.
    display_suffixes: Mapping[str, str] = field(default_factory=dict)


class NormalizationError(ValueError):
    """Bad or ambiguous input that must not silently corrupt the mart."""


def _string(value: Any) -> str:
    if value is None:
        return 'NULL'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    raise NormalizationError(f'Unsupported leaf type: {type(value).__name__}')


def _adjust(value: Any, path: str, config: NormalizationConfig) -> str:
    raw = _string(value)
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, Decimal)):
        return raw
    for upper, label in config.buckets.get(path, ()):
        if value <= upper:
            return label
    return raw


def _read_key(obj: Mapping[str, Any], key: str) -> str:
    """Supports dotted key paths, e.g. body.action."""
    value: Any = obj
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            raise NormalizationError(f'Missing array identity key {key!r}')
        value = value[part]
    if isinstance(value, (dict, list)):
        raise NormalizationError(f'Array identity key {key!r} is not scalar')
    return _string(value)


def _parts(path: tuple[str, ...], array_key: tuple[str, ...], scalar_suffix: str = '') -> dict[str, str]:
    # Prefix/class/remaining are display dimensions. PATH is the stable join key.
    if not path:
        raise NormalizationError('Empty attribute path')
    if scalar_suffix:
        prefix = path[0]
        cls = path[1] if len(path) >= 2 else ''
        suffix = '.'.join((*path[2:], scalar_suffix))
        key = ''
    else:
        prefix = path[0]
        cls = path[1] if len(path) >= 2 else ''
        suffix = '.'.join(path[2:-1])
        key = path[-1]
    return {'PREFIX': prefix, 'CLASS': cls, 'SUFFIX': suffix,
            'ARRAY_KEY': '|'.join(array_key), 'KEY': key,
            'PATH': '.'.join(path)}


def normalize(document: Mapping[str, Any], app_id: str, source: Source,
              config: NormalizationConfig) -> list[dict[str, str]]:
    """Flatten a JSON tree into one row per leaf (with configured array identity).

    Throws on unknown arrays instead of guessing index/value/identity semantics.
    Identical (PATH, ARRAY_KEY) is forbidden within a single application/slice.
    """
    if source not in ('BEFORE', 'AFTER'):
        raise ValueError(f'Invalid source: {source}')
    results: list[dict[str, str]] = []
    used: set[tuple[str, str]] = set()

    def emit(path: tuple[str, ...], keys: tuple[str, ...], value: Any,
             scalar_suffix: str = '') -> None:
        dotted = '.'.join(path)
        if dotted in config.excluded_paths:
            return
        parts = _parts(path, keys, scalar_suffix)
        if not scalar_suffix:
            label = config.display_suffixes.get('.'.join(path[:-1]))
            if label:
                parts['SUFFIX'] = '.'.join(filter(None, (parts['SUFFIX'], label)))
        identity = (parts['PATH'], parts['ARRAY_KEY'])
        if identity in used:
            raise NormalizationError(f'Duplicate attribute identity: {app_id} {identity}')
        used.add(identity)
        results.append({'APP_ID': app_id, 'SOURCE': source, **parts,
                        'VALUE': _string(value),
                        'ADJUSTED_VALUE': _adjust(value, dotted, config)})

    def walk(node: Any, path: tuple[str, ...], keys: tuple[str, ...]) -> None:
        dotted = '.'.join(path)
        if dotted in config.excluded_paths:
            return
        if isinstance(node, dict):
            for k, value in node.items():
                walk(value, (*path, k), keys)
            return
        if isinstance(node, list):
            rule = config.arrays.get(dotted)
            if rule is None:
                if node:
                    raise NormalizationError(f'Array rule not configured: {dotted}')
                return
            for index, item in enumerate(node):
                if rule.mode == 'fields':
                    if not isinstance(item, dict) or not rule.keys:
                        raise NormalizationError(f'Expected objects and configured keys: {dotted}')
                    identifier = ':'.join(_read_key(item, k) for k in rule.keys)
                    walk(item, path, (*keys, identifier))
                elif rule.mode == 'index':
                    walk(item, path, (*keys, str(index)))
                elif rule.mode == 'value':
                    if isinstance(item, (list, dict)):
                        raise NormalizationError(f'Expected scalars in value-array: {dotted}')
                    identifier = _string(item)
                    # Same value is both identity and meaningful scalar value.
                    emit(path, (*keys, identifier), item, rule.scalar_suffix)
                else:
                    raise NormalizationError(f'Unknown array mode: {rule.mode}')
            return
        emit(path, keys, node)

    walk(document, (), ())
    return results


def compare(before: list[dict[str, str]], after: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Full outer join by (APP_ID, PATH, ARRAY_KEY), retaining null vs missing."""
    def indexed(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, str]]:
        result: dict[tuple[str, str, str], dict[str, str]] = {}
        for row in rows:
            identity = (row['APP_ID'], row['PATH'], row['ARRAY_KEY'])
            if identity in result:
                raise NormalizationError(f'Duplicate comparison identity: {identity}')
            result[identity] = row
        return result

    lhs, rhs = indexed(before), indexed(after)
    answer: list[dict[str, Any]] = []
    for identity in sorted(lhs.keys() | rhs.keys()):
        b, a = lhs.get(identity), rhs.get(identity)
        exemplar = b if b is not None else a
        assert exemplar is not None
        if b is None:
            change = 'ATTRIBUTE_NEW'
        elif a is None:
            change = 'ATTRIBUTE_LOST'
        elif b['VALUE'] != a['VALUE']:
            change = 'VALUE_CHANGED'
        else:
            change = 'SAME'
        answer.append({k: exemplar[k] for k in ('APP_ID','PREFIX','CLASS','SUFFIX','ARRAY_KEY','KEY','PATH')} | {
            'VALUE_BEFORE': b['VALUE'] if b is not None else '',
            'VALUE_AFTER': a['VALUE'] if a is not None else '',
            'ADJUSTED_BEFORE': b['ADJUSTED_VALUE'] if b is not None else '',
            'ADJUSTED_AFTER': a['ADJUSTED_VALUE'] if a is not None else '',
            'DIFF_FLAG': int(change != 'SAME'), 'CHANGE_TYPE': change,
        })
    return answer


def normalize_pair(before_doc: Mapping[str, Any], after_doc: Mapping[str, Any],
                   app_id: str, config: NormalizationConfig
                   ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    before = normalize(before_doc, app_id, 'BEFORE', config)
    after = normalize(after_doc, app_id, 'AFTER', config)
    return [*before, *after], compare(before, after)
