"""Developer demo CLI. Production integration should call core functions directly."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter

from .configs import REAL, TEACHING
from .core import normalize_pair


def load(path: Path) -> dict:
    with path.open(encoding='utf-8') as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError(f'JSON root must be object: {path}')
    return result


def write_csv(path: Path, records: list[dict]) -> None:
    if not records:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), delimiter=';')
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(description='Normalize and compare JSON responses')
    parser.add_argument('--before', required=True, type=Path, help='BEFORE .json file or directory')
    parser.add_argument('--after', required=True, type=Path, help='AFTER .json file or directory')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--config', choices=['real', 'teaching'], default='real')
    args = parser.parse_args()
    config = {'real': REAL, 'teaching': TEACHING}[args.config]
    args.out.mkdir(parents=True, exist_ok=True)

    if args.before.is_file() and args.after.is_file():
        # Explicit file pair: names may differ (e.g. locally renamed uploaded files).
        before_files = {'single_pair.json': args.before}
        after_files = {'single_pair.json': args.after}
    else:
        if not args.before.is_dir() or not args.after.is_dir():
            parser.error('Both inputs must be files, or both must be directories')
        before_files = {p.name: p for p in args.before.glob('*.json')}
        after_files = {p.name: p for p in args.after.glob('*.json')}
    missing_before = sorted(set(after_files) - set(before_files))
    missing_after = sorted(set(before_files) - set(after_files))
    pairs = sorted(set(before_files) & set(after_files))
    normalized, changes, errors = [], [], []
    t0 = perf_counter()
    for name in pairs:
        try:
            b, a = load(before_files[name]), load(after_files[name])
            app_id = before_files[name].stem if name != 'single_pair.json' else b.get('appData', {}).get('application_id', before_files[name].stem)
            union, diff = normalize_pair(b, a, app_id, config)
            normalized.extend(union)
            changes.extend(diff)
        except (OSError, ValueError, TypeError) as exc:
            errors.append({'file': name, 'reason': str(exc)})

    write_csv(args.out / 'normalized_union.csv', normalized)
    write_csv(args.out / 'comparison.csv', changes)
    with (args.out / 'issues.json').open('w', encoding='utf-8') as file:
        json.dump({'missing_before': missing_before, 'missing_after': missing_after, 'failed': errors}, file,
                  ensure_ascii=False, indent=2)
    changed_apps = {r['APP_ID'] for r in changes if r['DIFF_FLAG'] == 1}
    # Decision path is chosen by configured schema rather than hardcoded in the comparison engine.
    print(f'Compared pairs: {len(pairs) - len(errors)} / {len(pairs)}')
    print(f'Normalized union rows: {len(normalized)}')
    print(f'Comparison rows: {len(changes)}')
    print(f'Applications with differences: {len(changed_apps)}')
    print(f'Missing before/after: {len(missing_before)}/{len(missing_after)}; invalid pairs: {len(errors)}')
    print(f'Elapsed seconds: {perf_counter() - t0:.3f}')
    print(f'Outputs: {args.out.absolute()}')


if __name__ == '__main__':
    main()
