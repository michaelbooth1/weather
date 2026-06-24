# 97. Shared IO, Time, And Structured Logging Utilities [COMPLETE 2026-06-16 - SHARED RUNTIME UTILITIES LIVE]

Goal: reduce drift in small infrastructure helpers and make runtime logging
consistent without changing CLI user output.

Source: 2026-06-16 architecture review. Many modules locally define
`write_json`, `read_json`, `append_jsonl`, `write_csv`, `utc_now`, `utc_iso`,
`maybe_float`, `to_float`, `fmt_num`, and `markdown_table`. Runtime/model paths
also use ad hoc `print()` for recoverable failures.

Why this is missing: helper extraction focused first on scoring, formatting,
settlement IO, and path policy. Small IO/time/logging helpers remained local
because each module only needed a few lines at first.

- [x] Add shared utility modules for stable infrastructure helpers, for example
  `weather.io`, `weather.time`, and expanded `weather.reporting.formatting`.
- [x] Move atomic JSON writes, tolerant JSON reads, JSONL append/read,
  simple CSV writes/appends, UTC timestamp helpers, and common numeric coercion
  into shared modules.
- [x] Keep CLI-facing `print()` for final command output, but replace library
  and runtime fallback prints with standard `logging`.
- [x] Add logger names by package and preserve structured JSONL diagnostics for
  supervisor/operator event streams.
- [x] Update high-churn modules first: market-making support, exchange/paper
  scoring, observation trigger, daily refresh, source redundancy, data-layer
  audit, model sources, and model feature artifact loading.
- [x] Add tests for atomic write behavior, tolerant reads, JSONL append/read,
  and log emission for representative fallback paths.

Acceptance: repeated small infrastructure helpers are centralized, recoverable
runtime errors are logged through `logging`, CLI command output remains readable,
and structured diagnostics continue to be written for operator workflows.

## Design

Separate three output channels:

- CLI output: concise `print()` summaries for humans running a command.
- Runtime logs: standard `logging` for recoverable library/runtime issues.
- Operator diagnostics: structured JSONL/status artifacts consumed by the
  dashboard and health checks.

Shared helpers should be boring and conservative. Preserve explicit relative
path semantics for caller-supplied paths, and keep repo-default paths in
`weather.paths`.

Verification strategy:

- Focused utility tests.
- Existing operations, market-making, reporting, and source tests.
- Architecture scan for common local helper redefinitions after migration.

## Completion

Completed 2026-06-16.

- Added `weather.io` with atomic JSON writes, tolerant JSON reads, JSONL
  append/read helpers, and simple CSV write/append helpers.
- Added `weather.time` with UTC timestamp, ISO timestamp, datetime parsing, and
  age helpers.
- Routed `weather.operations.supervisor` through the shared IO/time helpers so
  snapshot, CLOB, and observation supervisor paths share the same primitives.
- Migrated high-churn wrappers in market-making support, exchange adapter,
  observation trigger, daily refresh, source redundancy, and data-layer audit to
  delegate to the shared helpers while preserving their local function names and
  return shapes.
- Replaced recoverable model-runtime fallback prints with package loggers in
  calibration runtime, model sources, feature artifact loading/prediction, and
  Toronto model calibrated-weight loading. CLI-facing final output remains
  printed.
- Added focused runtime utility tests for atomic JSON writes, tolerant reads,
  JSONL append/read, CSV write/append, time helpers, and warning log emission.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\operations\test_runtime_utilities.py tests\operations\test_supervisor.py tests\operations\test_daily_refresh.py tests\operations\test_observation_trigger.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\reporting\test_data_layer_audit.py tests\reporting\test_source_redundancy.py tests\operations\test_import_architecture.py -q`
  (91 passed)
- `.\venv\Scripts\python.exe -m pytest -q` (820 passed, 491 subtests passed)

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - SHARED RUNTIME UTILITIES LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

