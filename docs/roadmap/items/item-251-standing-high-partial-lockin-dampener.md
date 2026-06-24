# 251. Standing-High Partial Lock-In Dampener [COMPLETE 2026-06-22 - PARTIAL DAMPENER GATED]

Goal: Add a partial late-day dampener when the observed high has stood for at least 60 minutes and the latest official temperature is below that high, even if one or two forecast sources still imply another 1-2F of upside.
Source: 2026-06-22 Austin weather-model disagreement audit. The observed high had effectively stood, the latest official METAR had rolled down, but lock-in stayed inactive because live current/high state and a warm forecast ceiling kept the model focused on `96-97F`.
Why this matters: Late-day lock-in should not be all-or-nothing. A single remaining warm forecast can justify a tail, but it should not prevent the model from dampening mass above a standing observed high when official temperatures have already fallen.

## Design

1. Define a soft dampener curve using stood-high minutes, official current below-high delta, time of day, solar/ramp regime, and forecast-cluster agreement.
2. Preserve a nonzero one-up or two-up tail when the robust forecast cluster and physical regime support a rebound.
3. Downweight the dampener when official METAR data is stale, missing, or inconsistent with nearby live sources.
4. Add stage-attribution output that separates hard lock-in, partial dampening, and no-action states.
5. Replay late-day warm-tail cases with separate metrics for over-warm concentration and missed late climbs.

- [x] Austin 2026-06-22 activates a partial dampener after the high has stood and official temperature is below the high.
- [x] Dampener reduces concentrated mass above the standing high without zeroing plausible rebound buckets.
- [x] Replay includes positive examples where late highs continue after an apparent stall.
- [x] Stage attribution reports how much probability moved due to partial dampening.
- [x] Promotion gate requires no degradation on late-day revision-up days and improvement on over-warm rollover days.

Acceptance: The partial dampener materially reduces Austin-style `96-97F` overconcentration after official rollover, while replay confirms it does not over-lock days that later make a new high.
Related: items 59, 170, 196, 232, 242, and 249.

## 2026-06-22 completion

The distribution pipeline now has a named `standing_high_partial_lockin` stage.
It activates only when a high has stood for at least 60 minutes, fresh official
METAR/current evidence is below the high, and the remaining forecast ceiling is
only modestly above the standing high. Hard lock-in still wins when eligible;
stale official readings remain diagnostic only; materially higher rebound
ceilings stay undamped.

Evidence:

- `weather.model.model_distribution_signals` defines the partial dampener
  context and soft application curve, including moved-probability attribution
  and one/two-up tail preservation.
- `weather.model.model_distribution` records the
  `standing_high_partial_lockin` component and stage attribution.
- `data/backtest/austin_weather_model_hardening_report.md` now includes item
  `251` gates for Austin activation, warm-tail reduction, stale official
  no-action, late-rebound no-action, and fail-closed promotion metrics.
- Tests: `python -m pytest tests/model/test_late_day_lockin.py
  tests/reporting/test_austin_weather_model_hardening.py -q`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - PARTIAL DAMPENER GATED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

