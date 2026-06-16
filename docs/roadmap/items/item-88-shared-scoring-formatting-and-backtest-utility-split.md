# 88. Shared Scoring, Formatting, And Backtest Utility Split [COMPLETE 2026-06-16 - SHARED HELPER MODULES LIVE]

Goal: stop using the settlement backtest CLI module as a general utility
dependency for calibration, reporting, monitoring, and promotion code.

Source: 2026-06-16 architecture review. Many non-backtesting modules import
generic helpers such as Brier/log-loss metrics, number formatting, markdown
tables, settlement label loading, and PnL helpers from
`weather.backtesting.backtest`.

Why this is missing: `backtest.py` started as the natural home for scoring
logic, then accumulated reusable helpers. Those helpers are now useful across
the system, but importing the full backtest module from reporting/calibration
creates an inverted dependency and makes future backtest refactors risky.

- [x] Create small shared modules for generic utilities, for example
  `weather.scoring.metrics`, `weather.reporting.formatting`, and
  `weather.backtesting.settlement_io`.
- [x] Move pure helpers such as Brier, binary log loss, percentage/number
  formatting, markdown table rendering, and generic trade PnL into the shared
  modules without behavioral changes.
- [x] Update calibration and reporting imports to use the shared modules instead
  of `weather.backtesting.backtest`.
- [x] Leave `weather.backtesting.backtest` focused on settlement-scored
  backtest orchestration, report assembly, and CLI behavior.
- [x] Add import architecture coverage that prevents non-backtesting packages
  from importing the backtest CLI module for shared helpers.

Acceptance: non-backtesting code no longer imports `weather.backtesting.backtest`
for generic utilities, the full test suite remains behaviorally equivalent, and
the backtest CLI can be changed without cascading import risk through reporting
and calibration.

## Design

Split by ownership rather than by call site:

- `weather.scoring.metrics` owns pure scoring and grouping helpers: Brier,
  binary log loss, row scoring, reliability/ECE, winner-band catchup,
  daily-first aggregation, missing-value handling, numeric coercion, and stable
  group sorting.
- `weather.scoring.trading` owns generic edge/PnL helpers: per-trade PnL,
  threshold trade aggregation, and PnL merging.
- `weather.reporting.formatting` owns presentation helpers: percentage,
  numeric, signed, group, PnL, and markdown table formatting.
- `weather.backtesting.settlement_io` owns settlement/tape-label IO and native
  band outcome helpers: default snapshot/daily-summary paths, daily summary
  loading, settlement resolution, market-day label loading, band endpoints, and
  outcome resolution.
- `weather.backtesting.tape_scoring` owns settlement-scored tape transforms:
  snapshot timestamp helpers, feature vector attachment, cutoff/last-row
  selection, grouped scoring, and `backtest_tape`.

Compatibility policy:

- `weather.backtesting.backtest` may import and re-export helper names during
  this migration so existing backtesting tests and local users do not break.
- Non-backtesting packages (`calibration`, `collection`, `reporting`,
  `market`, `model`, `operations`, and `sources`) must not import
  `weather.backtesting.backtest`; they should import the owning shared module
  directly.
- Backtesting modules can depend on `settlement_io` and `tape_scoring`, but the
  CLI module should only own argument parsing, report assembly, and the
  top-level `run_backtest` workflow.

Verification strategy:

- Add focused tests for the extracted shared helpers by reusing existing
  backtest assertions.
- Extend the import architecture ratchet to fail if non-backtesting source
  imports `weather.backtesting.backtest`.
- Run the focused backtesting/calibration/reporting tests that exercise the
  moved helpers, then run the full suite before marking the item complete.

## Completion

Completed 2026-06-16.

- Added `weather.scoring.metrics`, `weather.scoring.trading`,
  `weather.reporting.formatting`, `weather.backtesting.settlement_io`, and
  `weather.backtesting.tape_scoring`.
- Moved non-CLI helper ownership out of `weather.backtesting.backtest` while
  keeping compatibility re-exports for existing backtesting callers.
- Updated calibration, collection, reporting, and replay modules to import the
  owning helper modules directly.
- Extended `tests/operations/test_import_architecture.py` so source modules
  other than `weather.backtesting.backtest` cannot import the backtest CLI
  module for shared helpers.

Verification:

- `.\venv\Scripts\python.exe -m compileall -q src\weather`
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q`
- Focused backtesting/calibration/reporting helper-consumer slice: 158 passed.
- `.\venv\Scripts\python.exe -m pytest -q` (790 passed)
