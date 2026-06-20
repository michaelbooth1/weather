# 135. Cutoff-Regime Forecast/Observation Weighting [PARTIAL 2026-06-19 - FINAL LOCK-IN PASS, REGIME GAPS BLOCKED]

Goal: make the model explicitly switch weight between forecast-profile evidence
and observed-temperature-path evidence by cutoff regime.

Source: `data/backtest/input_variable_significance_2026_06_18_report.md` and
the generated family permutation table. The same input families have very
different value by time of day:

- early: Open-Meteo forecast profile delta MAE `0.5035`, observed temp path
  `0.0346`;
- midday: Open-Meteo forecast profile `0.3365`, observed temp path `0.1828`;
- late: observed temp path `0.7122`, Open-Meteo forecast profile `0.0500`.

Why this matters: a single global model can learn the right average behavior
while still underweighting forecasts before the day develops or overtrusting
forecasts after the realized high has effectively declared itself. Late-day
rows can dominate apparent feature importance because `high_so_far` and live
readings are nearly the answer by then.

## Design

1. Define explicit cutoff regimes: early, midday, late, and final lock-in.
2. Train or calibrate separate family weights for forecast profile, observed
   temperature path, source state, time context, and surface weather in each
   regime.
3. Evaluate the regime-weighted candidate against the current pooled artifact
   with grouped market-day validation.
4. Add leakage checks so late-day high-so-far certainty cannot improve early
   validation through duplicated snapshot rows.
5. Expose the active family weights in model explanations and replay reports.

- [x] Add cutoff-regime family-weight reporting to the replay/promotion output.
- [x] Build a regime-weighted candidate that increases forecast-family
  influence early and observed-path influence late.
- [x] Add a no-leakage audit that scores independent market-days, not repeated
  snapshot rows, as the primary evidence unit.
- [x] Add separate early, midday, late, and final-lock-in acceptance thresholds.
- [x] Add a casebook for days where the global model disagrees with the
  regime-weighted candidate.
- [ ] Clear the separate regime thresholds on pinned replay rows, including
  final-lock-in evidence.

Acceptance: the regime-weighted candidate improves early-day and midday
settlement metrics without material late-day degradation, and the report shows
family weights by cutoff regime with market-day-clustered validation evidence.

## 2026-06-18 implementation update

Added `weather.reporting.cutoff_regime_weighting`, schema
`cutoff_regime_weighting_v0.1`. The report reads
`data/backtest/input_variable_significance_2026_06_18_family_permutation.csv`
and derives explicit family weights for `early`, `midday`, `late`, and
`final_lock_in`. The resulting blend is forecast-heavy early
(`0.9357` forecast component), mixed at midday (`0.6480` forecast component),
and observation-heavy late/final (`0.9343` observed component).

Generated the regime-weighted shadow candidate from the item 134
forecast-profile shadow rows:

- `data/backtest/item135_regime_weighted_shadow_variants.csv`
- `data/backtest/item135_cutoff_regime_weighting.json`
- `data/backtest/item135_cutoff_regime_weighting_report.md`

The report scores independent market-days as the primary evidence unit. The
leakage audit passes with 44 market-days, 707 snapshots, 7,777 rows, and zero
duplicate observation keys. It also emits separate regime thresholds and a
disagreement casebook for rows where the regime-weighted candidate diverges
from current serving probabilities.

The initial `08/12/16` acceptance remained `blocked`: early, midday, and late
all improved current replay on daily-first Brier, but still exceeded the
market-tolerance threshold (`+0.0036`, `+0.0146`, and `+0.0115` versus market
respectively). That first run also lacked final-lock-in rows. The all-hour
update below supersedes the final-lock-in coverage blocker while preserving the
early/midday/late market-gap blockers.

## 2026-06-19 all-hour regime update

The final-lock-in evidence gap is now resolved by the all-hour Item 134 row
export. `data/backtest/item134_forecast_profile_all_hours_shadow_variants.csv`
feeds
`data/backtest/item135_cutoff_regime_weighting_all_hours_report.md`,
`data/backtest/item135_cutoff_regime_weighting_all_hours.json`, and
`data/backtest/item135_regime_weighted_all_hours_shadow_variants.csv`.

The all-hour report scores 67,430 rows, 6,130 snapshots, and 44 market-days
with zero duplicate observation keys. Acceptance remains `blocked`: the
regime-weighted candidate improves current on the daily-first metric in every
regime, but early, midday, and late still exceed market tolerance. Early is
candidate `0.0634` versus current `0.0651` and market `0.0600` (`+0.0034`
versus market); midday is `0.0559` versus current `0.0587` and market
`0.0436` (`+0.0123`); late is `0.0192` versus current `0.0193` and market
`0.0118` (`+0.0074`). Final lock-in now passes with candidate `0.0002`,
current `0.0003`, market `0.0000`, and market gap `+0.0002`.

The blocker has therefore changed. Final-lock-in row coverage is no longer the
blocker; Item 135 needs early/midday/late market-gap repair. The all-hour
regime blend is not an Item 48 promotion path by itself.
