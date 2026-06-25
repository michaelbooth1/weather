# 155. Inactive-Market Price-Free Learning And Current-Max Carryover Guard [COMPLETE 2026-06-19 - 2026-06-18 AUDIT GAP]

Goal: make all-inactive market days still produce reliable settled model
learning, and prevent early-hour `wu_max_since_7am` carryover from looking like
same-day evidence.

Source: the 2026-06-18 post-settlement log audit. All 12 normal location
folders have local winning bands, but the market-making and taker bots could
not act because every market was inactive from the market/CLOB registry view.
The standard hourly scorer selected the 12 `partial` settlement labels but
scored zero rows because `market_yes` was blank for inactive markets. A manual
price-free diagnostic from `snapshots_long.csv` showed the serving model did
eventually lock onto every winner: final winner probability averaged `0.990`,
all 12 final top bands matched the local winning band, and the model reached
100% top-hit rate by 20:00 local. That signal should feed daily learning even
when market prices are absent.

The same audit found an early-hour source-state risk. Before noon, seven
markets had `wu_max_since_7am` at least 10 native degrees above WU history high
while the same-day high had not caught up yet: Austin, Dallas, Denver, Houston,
Miami, San Francisco, and Seattle. That field can carry Weather.com current
page state across the pre-7 AM boundary or otherwise disagree sharply with
same-day WU history. It should remain a weak/support signal until validated as
same-day evidence, not an implicit early-day floor.

Why this matters: inactive markets are still valuable weather-model evidence,
but only if scoring can run without Polymarket prices. Early apparent accuracy
can also be overstated if current-page max values leak prior-day or stale
state into model confidence.

## Design

1. Add a price-free settled-day scorer for inactive/no-market folders that
   scores `model_probability` against `settlement.json` without requiring
   `market_yes`.
2. Feed price-free hourly summaries into daily learning as diagnostic model
   evidence, clearly separated from promotion evidence versus Polymarket.
3. Record why price-free scoring was used: inactive market, missing token map,
   missing CLOB book, or absent market prices.
4. Add an early-hour current-max carryover audit that compares
   `wu_max_since_7am`, WU history high, current temperature, local hour, and
   final settlement high.
5. Downweight or null `wu_max_since_7am` as a model feature before the local
   same-day 7 AM reset unless same-day WU history validates it.
6. Add a taker/MM post-run consistency check for CSV row counts versus summary
   counters so zero-trade evidence cannot silently lose rows.

- [x] Build the price-free scorer and write JSON/CSV/Markdown artifacts.
- [x] Teach `hourly_model_performance` or daily learning to fall back to the
  price-free scorer when market prices are absent.
- [x] Add pre-7/current-max carryover feature-state classification and tests.
- [x] Add a focused report slice for early high current-max minus WU-history
  gaps by market/hour.
- [x] Add bot run summary-vs-CSV row-count validation for taker and
  market-making tapes.

Acceptance: a future all-inactive or no-market day with valid settlement labels
produces nonzero settled model diagnostics; early-hour current max carryover is
visible and cannot be mistaken for same-day lock-in evidence; bot run summaries
and append-only tapes agree on row counts or emit an explicit integrity
warning.

## Completion Evidence

- Added `weather.reporting.candidate_lifecycle.price_free_model_learning`, which writes
  `data/backtest/price_free_model_learning.json`,
  `data/backtest/price_free_model_learning_report.md`,
  `data/backtest/price_free_model_learning_by_hour.csv`, and
  `data/backtest/price_free_model_learning_current_max_carryover.csv`.
- Wired daily refresh to run `price_free_model_learning` after
  `hourly_model_performance`; wired daily learning to add distinct
  `price_free_model_learning` and `current_max_carryover` retrain-context
  learnings while keeping Polymarket benchmark promotion evidence separate.
- Ran the scorer on 2026-06-18 with
  `--quality-grades partial,complete,manual_override --start-date 2026-06-18 --end-date 2026-06-18`.
  Result: `OK`, 12 scored market-days, 3,168 hourly checkpoint rows,
  22,638 all-snapshot rows, and reasons
  `absent_market_prices=12`, `inactive_market=12`, `missing_token_map=12`.
- Current-max carryover audit for 2026-06-18 recorded 2,052 snapshot rows,
  542 pre-reset null rows, 642 support-only rows, 857 validated rows,
  and 34 early large WU-history-gap rows; daily learning now carries compact
  summary, focused market-hour rows, and examples.
- Serving live-signal generation now nulls `wu_max_since_7am` before the local
  7 AM reset for both the feature-model peak-cluster path and empirical live
  signal path; post-reset behavior is unchanged.
- Observation-trigger normalization now resets previous-day monotonic highs
  when `target_date`/`event_slug` changes, excludes unvalidated
  `wu_current_max_since_7am` from trusted raw/settlement high rows, and carries
  `current_max_state`, `current_max_disposition`, and
  `current_high_trusted` into bot current-high assessments.
- Taker policy now has a dedicated 00:00-08:00 local guardrail: guarded
  current-high state, weak source state, or insufficient early edge blocks
  taker buys, while passing early-hour rows use reduced order, per-token, and
  filled-position caps. The same budget loop dedupes same-tick `intent_key`
  values before any candidate can spend budget.
- Added taker and market-making tape integrity summaries. The bots compare the
  physical append-only CSV data-row count with the saved run-summary row count
  and emit `PASS` or `WARN` in JSON and Markdown.
- Verification:
  `python -m pytest tests/model/test_estimate_distribution.py tests/reporting/test_price_free_model_learning.py tests/reporting/test_daily_learning.py tests/operations/test_daily_refresh.py tests/operations/test_schema_registry.py tests/market/test_taker_bot.py tests/market/test_market_making_run.py tests/operations/test_import_architecture.py::test_migrated_modules_use_package_imports_for_internal_modules`
  passed, 106 tests.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-19 - 2026-06-18 AUDIT GAP`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

