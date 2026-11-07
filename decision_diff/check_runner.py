"""Load organizer-compatible CHECK objects from .py files and run them.

WARNING: imports execute arbitrary Python. Only trusted files should be loaded
in-process. For an interactive editor isolate execution in a separate worker
container with resource limits (future module), never inside FastAPI itself.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any


REQUIRED_FIELDS = frozenset({
    "LABEL", "SOURCE", "ARGUMENT", "CNT", "TOTAL", "METRIC",
    "APP_IDS", "RESULT", "CONFIDENCE",
})


class CheckContractError(ValueError):
    pass


@dataclass
class CheckRunResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


def discover_checks(directory: str | Path) -> list[Path]:
    folder = Path(directory)
    if not folder.is_dir():
        raise NotADirectoryError(folder)
    return sorted(folder.glob("check_*.py"))


def load_check(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file() or path.suffix != ".py":
        raise FileNotFoundError(f"Python check not found: {path}")
    spec = importlib.util.spec_from_file_location(f"loaded_check_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise CheckContractError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition = getattr(module, "CHECK", None)
    if not isinstance(definition, dict):
        raise CheckContractError(f"No CHECK dict in {path}")
    if not isinstance(definition.get("id"), str) or not definition["id"]:
        raise CheckContractError(f"CHECK.id must be a nonempty string in {path}")
    if not isinstance(definition.get("label"), str):
        raise CheckContractError(f"CHECK.label must be a string in {path}")
    if not isinstance(definition.get("params"), dict):
        raise CheckContractError(f"CHECK.params must be a dictionary in {path}")
    if not callable(definition.get("entrypoint")):
        raise CheckContractError(f"CHECK.entrypoint must be callable in {path}")
    return definition


def _validate_check_row(value: Any, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CheckContractError(f"Check returned non-dict row in {path}")
    missing = REQUIRED_FIELDS - value.keys()
    if missing:
        raise CheckContractError(f"Check returned missing fields {sorted(missing)} in {path}")
    if value["SOURCE"] not in ("BEFORE", "AFTER"):
        raise CheckContractError(f"Invalid SOURCE in {path}: {value['SOURCE']}")
    if value["RESULT"] not in ("PASS", "FAIL"):
        raise CheckContractError(f"Invalid RESULT in {path}: {value['RESULT']}")
    if value["CONFIDENCE"] not in ("HIGH", "LOW"):
        raise CheckContractError(f"Invalid CONFIDENCE in {path}: {value['CONFIDENCE']}")
    if not isinstance(value["APP_IDS"], list):
        raise CheckContractError(f"APP_IDS must be a list in {path}")
    return value


def run_checks(
    mart: Any,
    paths: Sequence[str | Path],
    parameter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> CheckRunResult:
    """Execute every configured check; isolate errors *per check*.

    Failures go to diagnostics, not counterfeit PASS/FAIL rows.
    """
    overrides = parameter_overrides or {}
    outcome = CheckRunResult()
    seen_ids: set[str] = set()
    for location in paths:
        path = Path(location)
        started = perf_counter()
        check_id = path.stem
        try:
            check = load_check(path)
            check_id = check["id"]
            if check_id in seen_ids:
                raise CheckContractError(f"Duplicate check ID: {check_id}")
            seen_ids.add(check_id)
            params = {**check["params"], **dict(overrides.get(check_id, {}))}
            result = check["entrypoint"](mart, params)
            if not isinstance(result, list):
                raise CheckContractError(f"Check must return list[dict]: {path}")
            validated = [_validate_check_row(item, path) for item in result]
            outcome.rows.extend(validated)
        except Exception as exc:
            outcome.diagnostics.append({
                "check": check_id,
                "file": str(path),
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
        finally:
            outcome.timings[check_id] = round(perf_counter() - started, 4)
    return outcome
