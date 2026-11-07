"""Bounded, read-only tabular snapshots of the existing JSON datasets."""
from __future__ import annotations

import json
import math
import os
import stat
from typing import Any

from .errors import ApiError

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
MAX_COLUMNS = 200


def dataset_table(registry, owner: str, dataset_id: str, side: str) -> dict:
    ds = registry._dataset_row(owner, dataset_id)
    before, after = registry.dataset_files(ds)
    files = before if side == "before" else after
    rows: list[dict] = []
    columns = {"_file": None}
    consumed = 0

    def too_large():
        raise ApiError(413, "TABLE_TOO_LARGE", "Dataset table exceeds 10 MiB, 20000 rows or 200 columns; select a smaller dataset")

    def flatten(value: Any, prefix: str, row: dict):
        if isinstance(value, dict) and value:
            for key, child in value.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                flatten(child, f"{prefix}/{escaped}", row)
        else:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Non-finite JSON number")
            if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
                value = str(value)  # Preserve long identifiers exactly in JavaScript.
            row[prefix or "/value"] = json.dumps(value, ensure_ascii=False, allow_nan=False) if isinstance(value, (dict, list)) else value
            columns.setdefault(prefix or "/value", None)
            if len(columns) > MAX_COLUMNS:
                too_large()

    for name, path in sorted(files.items()):
        # Re-resolve against the allowlist, then open a bounded regular descriptor.
        base = registry.settings.data_roots[ds["root"]].resolve()
        path = registry.resolve_in_root(ds["root"], path.relative_to(base).as_posix())
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            raise ApiError(422, "DATASET_FILE_NOT_REGULAR", "Input is not a readable regular file", {"file": name})
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise ApiError(422, "DATASET_FILE_NOT_REGULAR", "Input is not a regular file", {"file": name})
            if st.st_size > min(registry.settings.max_input_file_bytes, MAX_BYTES - consumed):
                too_large()
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(min(registry.settings.max_input_file_bytes, MAX_BYTES - consumed) + 1)
            consumed += len(raw)
            if consumed > MAX_BYTES or len(raw) > registry.settings.max_input_file_bytes:
                too_large()
            try:
                document = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                records = document if isinstance(document, list) else [document]
                for record in records:
                    if len(rows) >= MAX_ROWS:
                        too_large()
                    row = {"_file": path.name}
                    flatten(record, "", row)
                    rows.append(row)
            except (ValueError, RecursionError, UnicodeError):
                raise ApiError(422, "DATASET_JSON_INVALID", "Input contains invalid or excessively nested JSON", {"file": name})
        finally:
            os.close(fd)
    names = list(columns)
    return {"dataset_id": dataset_id, "side": side, "columns": names,
            "rows": [[row.get(column) for column in names] for row in rows]}
