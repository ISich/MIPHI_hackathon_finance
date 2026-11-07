# D4 patch: HTML export (additive)

## Files
- `decision_diff/html_report.py`: pure HTML renderer of `checks_report.json` with HTML escaping and a configurable link to the web report.
- `decision_diff/html_cli.py`: standalone CLI, no API dependency.
- `tests/test_html_report.py`: four tests.

**Copy these files to the existing repository without replacing core.py, mart.py, storage.py, pyproject.toml or team files.** No new dependencies.

## Run tests

```powershell
python -m pytest tests/test_html_report.py -v
python -m pytest -q
```

## Generate HTML

```powershell
python -m decision_diff.html_cli `
  --report outputs/full_run/checks_report.json `
  --out outputs/full_run/checks_report.html `
  --report-url "http://localhost:5173/runs/demo/report"
```

The `--report-url` is **provisional**: replace it with the final route agreed with D2/D3. It only defines where the downloaded HTML will navigate. It does not create any FastAPI/Vue route.

The HTML report is self-contained for its tabular data; app detail links require the web app to be available. `APP_IDS` is limited by the check settings, not the full membership for every aggregate. The `?app_id=` convention is also provisional, pending D3 routing.

## Integration contract proposal (to approve with D2/D3)

- D2 accepts `run_id`, ensures the selected run is complete, looks up its `checks_report.json`, then invokes `write_html_report(report, output_path, report_url=absolute_report_url)` and streams the HTML as an attachment.
- D3 provides the report page URL and handles optional `app_id` query parameter, or asks D4 to change the link convention.
- D4 owns report-content generation; D2 owns routing, authentication, permissions and URL determination.

## Known limitation

This implementation follows the **original organizer check result schema**, not any unavailable new PR docs/DTO; reconcile before freezing public APIs.
