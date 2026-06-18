# 122. UI And Loop Serialization Health Cleanup [COMPLETE 2026-06-18 - ARROW SAFE TABLES AND JSONL QUARANTINE]

Goal: remove recurring dashboard serialization errors and loop JSONL malformed
line warnings so operator health reports reflect real collection problems
rather than avoidable formatting defects.

Source: the 2026-06-18 review found `data/logs/streamlit_stderr.log` with
6,028 Streamlit tracebacks, including 2,823 `ArrowTypeError` failures and 3,204
`ArrowInvalid` failures from mixed-type `Value` columns. The same day's fleet
observability report showed loop artifact integrity `ok=false` with 426
malformed lines: 49 for snapshot capture, 276 for CLOB capture, and 101 for the
observation trigger, with zero duplicate writers.

Why this matters: these are not model-performance misses. They are operator
surface and artifact hygiene issues that create noise in every daily review,
make dashboards brittle, and can hide new runtime failures among thousands of
known tracebacks.

## Design

1. Normalize dashboard status/detail tables to string-safe display records
   before handing them to Streamlit/Arrow.
2. Add a small regression test for mixed scalar/date/string values in the app
   table helpers.
3. Identify which loop JSONL files contain malformed lines and whether they are
   partial writes, console text, encoding artifacts, or legacy mixed logs.
4. Add a quarantine/repair path for malformed historical loop lines while
   preserving raw evidence.
5. Keep fleet observability warnings, but make them point to file paths,
   malformed-line samples, and a concrete repair command.

- [x] Fix Streamlit mixed-type table rendering for status/value panels.
- [x] Add app tests covering mixed string, numeric, boolean, and date values.
- [x] Add loop JSONL malformed-line sampling to fleet observability.
- [x] Add a repair/quarantine command for historical malformed loop lines.
- [x] Require new loop writers to emit one valid JSON object per line, with
  tests for interrupted writes where practical.

Acceptance: the dashboard can render current operational reports without Arrow
tracebacks, and fleet observability either reports zero malformed loop lines or
names the exact files and repair command needed to quarantine legacy damage.

## Completion Notes

Added shared Streamlit table helpers in `app.table_utils` and routed
market-making and operations dashboard tables through Arrow-safe dataframe or
record normalization. Added malformed JSONL line classification to supervisor
integrity checks, included samples and repair commands in fleet observability,
and added `weather.operations.loop_jsonl_repair` to quarantine malformed lines
while preserving raw backups.

Verification:
`python -m pytest tests/app/test_market_making_view.py tests/reporting/test_fleet_observability.py tests/operations/test_loop_jsonl_repair.py -q`
