# 149. Target-Vs-Extra Location Validation Harness [COMPLETE 2026-06-18 - PRICE-FREE TRANSFER HARNESS LIVE]

Goal: promote the scratch no-market transfer audit into a reproducible CLI and
reporting harness that can evaluate whether extra locations help the model
without relying on Polymarket prices.

Source: the deep audit used `scratch/no_market_location_fast_audit.py` after the
full HGB transfer harness exceeded the interactive runtime budget. The fast
harness produced useful paired evidence, but it is not a first-class artifact,
does not run from the daily research harness, and is intentionally simpler than
the production pooled band model.

Why this matters: the right comparison for non-market locations is not model
versus market. It is target-only versus target-plus-extra on the same target
labels, with blocked splits and daily-first aggregation. Without a canonical
harness, future extra-location experiments will be hard to compare and easy to
overfit.

## Design

1. Add `weather.reporting.no_market_location_transfer` or an equivalent
   research CLI that builds paired target-only, target-plus-extra, extra-only,
   and weighted-extra comparisons.
2. Support multiple scoring backends:
   - fast residual/density scoring for cheap daily monitoring,
   - production pooled-band HGB scoring for promotion-grade offline runs,
   - optional continuous-density scoring for all-unit experiments.
3. Use blocked splits by target market, target date, holdout year, and cutoff
   regime. Aggregate row-level bands only after daily-first market-day metrics
   are computed.
4. Report paired bootstrap or clustered confidence intervals for Brier, log
   loss, MAE, winner probability, and winner rank.
5. Persist JSON, CSV, and Markdown outputs under `data/backtest/` so item 85
   can track independent evidence growth.
6. Add a small fixture suite proving the harness refuses leakage, distinguishes
   row counts from independent observations, and handles missing extra-location
   coverage explicitly.

- [x] Move the fast audit logic out of `scratch/` into a canonical reporting or
  calibration module.
- [x] Add CLI flags for target markets, extra-location sets, holdout years,
  cutoff regimes, and scoring backend.
- [x] Add daily-first paired metric output and confidence intervals.
- [x] Add tests for leakage prevention, missing labels, row-multiplier
  accounting, and no-market price-free scoring.
- [x] Wire the harness into research audit documentation and optional daily
  refresh reporting.

Acceptance: a new extra-location training idea can be evaluated by one
canonical command, producing comparable target-only versus target-plus-extra
evidence without market prices and without relying on scratch scripts.

## 2026-06-18 implementation update

Added `weather.reporting.no_market_location_transfer`, schema
`no_market_location_transfer_v0.1`, with a canonical CLI:

```powershell
python -m weather.reporting.no_market_location_transfer observations.csv --target-markets nyc --extra-locations boston,philadelphia --holdout-years 2025 --cutoff-regimes early --scoring-backend fast_residual
```

The harness emits JSON, CSV, and Markdown under `data/backtest/` by default,
computes paired target-only, target-plus-extra, extra-only, and
similarity-weighted comparisons, and reports daily-first bootstrap confidence
intervals for Brier, log loss, MAE, exact-winner probability, and squared
error. Market-price fields are ignored even when present.

The split policy excludes same target dates and same holdout years from every
training condition, records blocked leakage rows, and makes missing
extra-location coverage explicit. The promotion gate
`no_market_extra_location_gate_v0.1` blocks target-plus-extra when daily-first
Brier/log-loss or MAE confidence intervals are clearly positive versus
target-only.

Optional promotion-refresh wiring is available through
`--extra-location-transfer-report`.
