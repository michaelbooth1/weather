# 153. Live Observation Monotonicity And Settlement-Bin Normalization [COMPLETE 2026-06-18 - SETTLEMENT-NORMALIZED LIVE HIGH LEDGER]

Goal: make live model assessment and trade permission compare forecasts against
the same monotonic, settlement-normalized high that the market will resolve
against.

Source: the June 18 log audit compared latest live snapshots with observation
trigger state. Most markets were aligned by evening, but two edge cases showed
that raw live observations can distort model assessment. Atlanta's WU
`max_since_7am` trigger moved down from 87 F to 86 F while WU history still
reported 87 F, which is a source revision rather than a real decrease in the
day's high. Denver's `max_live_observation` was 87.08 F from raw METAR while WU
history showed 88 F and the model top bin was 88-89 F; a raw decimal comparison
assigned zero probability to the current-high bin even though the likely
settlement-style rounded high was covered.

Why this matters: the model can be penalized or permissioned against the wrong
target if live highs are allowed to decrease, if source revisions are treated
like weather events, or if raw METAR decimals are compared to market bins
without the same rounding rule used at settlement.

## Design

1. Maintain a per-market monotonic intraday high ledger with source provenance,
   raw value, rounded settlement value, and revision events.
2. Classify downward changes in `max_since_7am` as source revisions unless an
   explicit correction policy accepts the lower value.
3. Compare model probabilities and trade permission to settlement-normalized
   bins, not raw decimal observation values.
4. Expose `raw_current_high`, `settlement_current_high`, `high_source`,
   `revision_state`, and `bin_key` in snapshot, observation-trigger, taker, and
   market-making reports.
5. Add a late-day disagreement audit for markets where the model top bin,
   observed raw high, and settlement-normalized high disagree.
6. Use this audit to separate true model misses, such as a real one-bin miss,
   from source/rounding artifacts.

- [x] Add a monotonic high ledger consumed by observation trigger and bot
  preflight.
- [x] Add settlement-bin normalization helpers to live current-high comparisons.
- [x] Record revision events when a source high decreases within the active
  day.
- [x] Add model-vs-live reports that show both raw and normalized current-high
  probabilities.
- [x] Add regression tests for Atlanta-style downward WU max revisions.
- [x] Add regression tests for Denver-style raw METAR decimals near a bin
  boundary.

Acceptance: live model review, taker decisions, and market-making permission
use the same settlement-normalized current high, and downward source revisions
are visible without being mistaken for a real decrease in the day's high.

## Implementation Notes

Completed 2026-06-18. `weather.market.live_observation_normalization` now owns
the monotonic live-high ledger, settlement-bucket normalization, raw-vs-rounded
probability lookup, and per-row normalized high fields. The observation trigger
records `settlement_normalization` on each market state, persists
`monotonic_high_ledger`, and classifies downward `wu_current_max_since_7am`
changes as source revisions instead of lower daily highs.

Market-making and taker preflight/input paths now consume the same per-market
ledger from `observation_trigger_status.json`, write normalized high fields to
quote/order rows, and include a current-high assessment section in their
Markdown reports. The assessment shows raw high, settlement high, raw-high
probability, settlement-high probability, source, and revision state.

Validation: `python -m pytest tests/operations/test_market_making_daily_roll.py tests/operations/test_taker_bot_daily_roll.py tests/operations/test_observation_trigger.py tests/market/test_market_microstructure.py tests/market/test_market_making_run.py::TestMarketMakingRun::test_blank_clob_tokens_are_market_discovery_blocker tests/market/test_market_making_run.py::TestMarketMakingRun::test_quote_rows_include_settlement_normalized_current_high tests/market/test_taker_bot.py tests/reporting/test_fleet_observability.py tests/market/test_mm_policy.py` passed with 110 tests.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - SETTLEMENT-NORMALIZED LIVE HIGH LEDGER`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

