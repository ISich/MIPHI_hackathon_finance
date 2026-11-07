"""Generate standalone HTML from the existing checks_report.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .html_report import write_html_report


def main() -> None:
    parser = argparse.ArgumentParser(description='Export organizer check results to standalone HTML')
    parser.add_argument('--report', type=Path, required=True, help='Path to checks_report.json')
    parser.add_argument('--out', type=Path, required=True, help='Output HTML path')
    parser.add_argument('--report-url', required=True, help='Public HTTP(S) URL of the pivot page for this run')
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        parser.error('Report JSON must contain an object')
    path = write_html_report(data, args.out, report_url=args.report_url)
    print(f'HTML report: {path}')


if __name__ == '__main__':
    main()
