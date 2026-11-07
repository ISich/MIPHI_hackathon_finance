"""D4 server-side distinct pivot rollups over BaseFacts/BaseMembership.

The UI never sends SQL. Locators are signed and bound to a run/revision; D2
must independently check owner access to run_id on EVERY request. The secret
is an application-level signing key supplied by D2, not a user-provided value.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .base_facts import BASE_DIMS, ensure_schema


class PivotQueryError(ValueError):
    pass


_ALLOWED = frozenset(BASE_DIMS)
_MAX_LIMIT = 500


def _quoted(field: str) -> str:
    if field not in _ALLOWED:
        raise PivotQueryError(f"Unsupported dimension/filter: {field}")
    return f'f."{field}"'


def _value(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _conditions(filters: Mapping[str, Any]) -> tuple[str, list[Any]]:
    if not isinstance(filters, Mapping):
        raise PivotQueryError('filters must be a mapping')
    pieces: list[str] = []
    arguments: list[Any] = []
    for key in sorted(filters):
        col = _quoted(key)
        value = filters[key]
        if isinstance(value, (tuple, list)):
            if not value:
                pieces.append('1=0')
            elif not all(_value(x) for x in value):
                raise PivotQueryError(f'Unsupported filter value for {key}')
            else:
                parts = [f'{col} IN ({", ".join("?" for x in value if x is not None)})'] if any(x is not None for x in value) else []
                if any(x is None for x in value):
                    parts.append(f'{col} IS NULL')
                pieces.append('(' + ' OR '.join(parts) + ')')
                arguments.extend(x for x in value if x is not None)
        elif value is None:
            pieces.append(f'{col} IS NULL')
        elif _value(value):
            pieces.append(f'{col} = ?')
            arguments.append(value)
        else:
            raise PivotQueryError(f'Unsupported filter value for {key}')
    return (' AND '.join(pieces) if pieces else '1=1'), arguments


def _paging(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > _MAX_LIMIT:
        raise PivotQueryError('limit must be an integer from 1 to 500')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PivotQueryError('offset must be a non-negative integer')


def _encode(payload: dict[str, Any], secret: bytes) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body).rstrip(b'=').decode() + '.' + base64.urlsafe_b64encode(mac).rstrip(b'=').decode()


def _decode(token: str, secret: bytes) -> dict[str, Any]:
    try:
        part, signature = token.split('.', 1)
        body = base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))
        received = base64.urlsafe_b64decode(signature + '=' * (-len(signature) % 4))
        expected = hmac.new(secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(received, expected):
            raise PivotQueryError('Invalid group locator signature')
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise PivotQueryError('Invalid group locator')
        return payload
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PivotQueryError('Malformed group locator') from exc


class PivotRollup:
    """Queries a completed run; caller supplies a read-only connection.

    DO NOT share connections across unrelated threads. D2 maps authorized
    run_id to DB path and provides revision+signing secret. This code performs
    no auth, orchestration, or database creation.
    """

    def __init__(self, connection: Any, *, run_id: str, data_revision: str, signing_secret: bytes):
        if not run_id or not data_revision or not signing_secret:
            raise ValueError('run_id, data_revision and signing_secret are required')
        self.db = connection
        self.run_id = run_id
        self.data_revision = data_revision
        self.secret = signing_secret
        ensure_schema(connection)

    def cells(self, *, dimensions: Sequence[str], filters: Mapping[str, Any] | None = None,
              limit: int = 100, offset: int = 0) -> dict[str, Any]:
        _paging(limit, offset)
        if not dimensions or len(set(dimensions)) != len(dimensions):
            raise PivotQueryError('dimensions must be nonempty and unique')
        dims = tuple(dimensions)
        for dimension in dims:
            _quoted(dimension)
        filters = dict(filters or {})
        where, params = _conditions(filters)
        columns = ', '.join(_quoted(c) for c in dims)
        # Membership (not SUM of base_fact CNT) is the only source of totals.
        grouped = (
            f'SELECT {columns}, COUNT(DISTINCT m.APP_ID) AS CNT '
            'FROM base_facts f JOIN base_membership m ON f.fact_id = m.fact_id '
            f'WHERE {where} GROUP BY {columns}'
        )
        total_cells = int(self.db.execute(
            f'SELECT COUNT(*) FROM ({grouped}) result', params
        ).fetchone()[0])
        cur = self.db.execute(
            f'SELECT * FROM ({grouped}) result ORDER BY ' +
            ', '.join('"' + d + '"' for d in dims) + ' LIMIT ? OFFSET ?',
            [*params, limit, offset]
        )
        records = cur.fetchall()
        items = []
        for row in records:
            coordinates = dict(zip(dims, row[:-1]))
            locator = _encode({
                'version': 1, 'run_id': self.run_id, 'data_revision': self.data_revision,
                'dimensions': list(dims), 'filters': filters, 'cell': coordinates,
            }, self.secret)
            items.append({'dimensions': coordinates, 'cnt': int(row[-1]), 'group_locator': locator})
        return {'run_id': self.run_id, 'data_revision': self.data_revision,
                'items': items, 'total': total_cells, 'limit': limit, 'offset': offset}

    def members(self, locator: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        _paging(limit, offset)
        p = _decode(locator, self.secret)
        if p.get('version') != 1 or p.get('run_id') != self.run_id or p.get('data_revision') != self.data_revision:
            raise PivotQueryError('Group locator does not match this run/revision')
        dimensions = p.get('dimensions')
        filters = p.get('filters')
        cell = p.get('cell')
        if not isinstance(dimensions, list) or not isinstance(cell, dict) or set(cell) != set(dimensions):
            raise PivotQueryError('Invalid group locator dimensions')
        if len(set(dimensions)) != len(dimensions):
            raise PivotQueryError('Duplicate group locator dimensions')
        # A group coordinate must be compatible with every original filter.
        for k, selected in cell.items():
            if k in filters:
                allowed = filters[k]
                matches = selected in allowed if isinstance(allowed, list) else selected == allowed
                if not matches:
                    raise PivotQueryError('Group cell conflicts with filter')
        where, params = _conditions({**filters, **cell})
        query = ('FROM base_facts f JOIN base_membership m ON f.fact_id = m.fact_id '
                 f'WHERE {where}')
        count = int(self.db.execute('SELECT COUNT(DISTINCT m.APP_ID) ' + query, params).fetchone()[0])
        ids = [str(row[0]) for row in self.db.execute(
            'SELECT DISTINCT m.APP_ID ' + query + ' ORDER BY m.APP_ID LIMIT ? OFFSET ?',
            [*params, limit, offset]
        ).fetchall()]
        return {'run_id': self.run_id, 'data_revision': self.data_revision,
                'total': count, 'items': ids, 'limit': limit, 'offset': offset}
