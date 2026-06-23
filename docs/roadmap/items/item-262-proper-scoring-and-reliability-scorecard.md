# 262. Proper-Scoring And Reliability Scorecard [COMPLETE 2026-06-23 - CANONICAL SCORECARD AND DAILY REFRESH STEP LIVE]

Goal: make proper probabilistic verification a first-class model-review
artifact, separate from but comparable with the existing Brier/log-loss
promotion packet.

Source: the 2026-06-23 research audit found that the current weather-only
proof packet is appropriately blocked on Brier/log-loss, early-hour, exact-band,
bottom-location, and served-distribution evidence. The audit also found that
the repo does not yet have one canonical scholarly verification scorecard for
CRPS, PIT/rank reliability, calibration versus sharpness, and served-versus-
validated distribution parity across weather-only, market-only, and
market-informed lanes.

Why this matters: daily high-temperature markets are full-distribution
forecasting problems. A candidate can improve one bucket metric while still
being overdispersed, underdispersed, poorly ranked near the eventual winner, or
miscalibrated in early-hour and exact-band slices. Proper scoring and
reliability diagnostics make those failures visible before they become trading
or promotion claims.

## Design

1. Define a canonical verification scorecard schema for served rows, candidate
   shadow rows, current replay rows, market rows, and no-market baselines.
2. Keep weather-only skill, market-only benchmark skill, and market-informed
   overlay skill in separate sections so market prices cannot clear a
   weather-only proof gate.
3. Report Brier, log-loss, CRPS where a continuous or density payload exists,
   PIT or randomized-rank reliability, ECE/reliability, sharpness/effective
   spread, winner-rank mass, adjacent-winner mass, exact-band probability, and
   settlement-distance slices.
4. Slice every metric by market, local cutoff hour, early/midday/late regime,
   source-health state, runtime identity, weak-slot state, settlement distance,
   and served-versus-validated distribution family.
5. Add diagnostic thresholds first. Do not weaken or replace the current
   promotion gates until the scorecard has enough settled active-day history to
   justify hard thresholds.
6. Include a short literature appendix naming the proper-score and calibration
   concepts used, so future reviewers can distinguish repo-specific heuristics
   from standard forecast-verification methods.

- [x] Add the scorecard schema and Markdown/JSON report.
- [x] Wire the report to existing proof-packet inputs without retraining models.
- [x] Add density/continuous CRPS support for item-35 style payloads when
  present, with graceful skip reasons for bucket-only artifacts.
- [x] Add PIT/rank reliability and sharpness diagnostics for bucket
  distributions.
- [x] Add served-versus-validated distribution parity checks by lane and cutoff
  regime.
- [x] Add a literature appendix with stable links to the verification methods
  used by the report.

## Completion Notes

Implemented `weather.reporting.proper_scoring_reliability_scorecard`, registered
`proper_scoring_reliability_scorecard_v0.1`, and generated canonical outputs at
`data/backtest/proper_scoring_reliability_scorecard.json` and
`data/backtest/proper_scoring_reliability_scorecard.md`.

Daily refresh now runs `proper_scoring_reliability_scorecard` after
`active_variant_shadow` and before frozen-baseline replay trend, with
`--skip-proper-scoring-reliability-scorecard` for explicit bypasses. The
pipeline summary and Markdown report expose scored rows, lane count, blockers,
lane statuses, and served-versus-validated parity status.

The scorecard reports lane-separated Brier, log-loss, ECE/reliability,
sharpness/effective spread, rank/PIT-style bucket diagnostics, winner-rank and
ranked-probability score diagnostics, settlement-distance/source/runtime/weak
slot/distribution-family slices, market-only benchmark rows, and
served-versus-validated parity. Continuous-density CRPS is present as a
diagnostic section with an explicit skip reason when bucket-only artifacts are
the only available payload.

Verification:

- `python -m weather.reporting.proper_scoring_reliability_scorecard --json-out data\backtest\proper_scoring_reliability_scorecard.json --report-out data\backtest\proper_scoring_reliability_scorecard.md`
- `python -m pytest tests\reporting\test_proper_scoring_reliability_scorecard.py tests\operations\test_schema_registry.py -q`
- `python -m pytest tests\operations\test_daily_refresh.py -q`

Acceptance: each promotion review can show whether the active candidate is
better, calibrated, and sharp enough under proper probabilistic verification,
while still preserving the existing weather-only versus market-informed lane
separation. A candidate with strong Brier/log-loss but severe reliability,
sharpness, CRPS, or served-parity failures must remain blocked until those
failures are explained or fixed.

Related: items 35, 48, 69, 88, 145, 160, 230, 233, 242.
