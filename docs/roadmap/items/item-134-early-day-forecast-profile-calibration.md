# 134. Early-Day Forecast Profile Calibration [PARTIAL 2026-06-19 - ALL-HOUR REPLAY COMPLETE, PROMOTION BLOCKED]

Goal: turn the strongest measured early-day signal, the forecast-profile
family, into a deliberately calibrated model lane rather than letting it be one
large correlated feature block inside the pooled model.

Source: `data/backtest/input_variable_significance_2026_06_18_report.md`.
The June 18 input-significance analysis scored 19,320 settled feature rows
across 148 matched market-days and 12 markets. The Open-Meteo forecast-profile
family was the strongest family overall and early day:

- all-day family HGB permutation delta MAE: `0.4426`, q `8.126e-06`;
- early-day family HGB permutation delta MAE: `0.5035`, q `0.0001296`;
- `forecast_high` single-feature HGB delta MAE: `0.4159`, q `3.78e-05`;
- early-day latest-snapshot `forecast_high` correlation with settlement high:
  `r=0.8607` across 136 market-days.

Why this matters: the model has added many forecast-profile fields, but the
evidence says most of the useful early-day information is concentrated in the
forecast family and especially `forecast_high`. Highly correlated profile
fields can make individual p-values unstable, hide calibration errors, and
allow sparse subfields to look important only because they proxy the same
forecast level.

## Design

1. Add a forecast-profile calibration report that separates `forecast_high`,
   hourly profile temperatures, cloud/solar/radiation fields, ensemble spread,
   and forecast-gap fields.
2. Train a forecast-family-only early-day candidate and compare it against the
   current pooled model on frozen market-days.
3. Add monotonic or shrinkage constraints around `forecast_high` so correlated
   auxiliary profile fields can adjust confidence without overriding the core
   forecast level without evidence.
4. Score lift by market, cutoff hour, warm/cool-side bucket pressure, source
   count, and forecast disagreement.
5. Require blocked, daily-first replay before any forecast-profile weighting
   change is promoted.

- [x] Generate a forecast-profile-only replay report with all-day, early,
  midday, and late slices.
- [x] Quantify marginal lift of forecast-profile subfamilies after controlling
  for `forecast_high`.
- [x] Add a candidate artifact that treats forecast-profile value as an
  explicitly calibrated early-day component.
- [x] Add per-market guardrails for cities where forecast profile is strong but
  source disagreement is high.
- [x] Feed the winning forecast-profile calibration into promotion refresh and
  the model explanation panel.
- [ ] Clear daily-first market-tolerance and high-disagreement guardrails
  before any forecast-profile lane can be promoted.

Acceptance: a candidate model or component proves daily-first settlement lift
on early-day snapshots, does not regress midday/late-day slices beyond the
promotion tolerance, and reports whether each forecast-profile subfamily adds
value beyond `forecast_high`.

## 2026-06-18 implementation update

Added a named `forecast_profile` pooled band-model feature subset and schema
`pooled_feature_band_hgb_forecast_profile_v0.1`. The subset contract keeps
`forecast_high`, forecast-profile fields, market/climate context, and
forecast-relative band geometry while excluding observed-temperature-path,
live-reading, CLOB, official-guidance, marine, and dynamic source-state
families from the model matrix. Candidate replay now emits cutoff-regime,
forecast source-count, forecast-disagreement, and forecast-relative
warm/cool-side slices, plus a per-market high-disagreement guardrail. The
default shadow-variant lane is `item134_forecast_profile_v0_1` /
`forecast_profile_calibration`.

Generated smoke artifact:
`data/backtest/item134_forecast_profile_smoke.pkl` and
`data/backtest/item134_forecast_profile_smoke_report.md` using
`--objective band --feature-subset forecast_profile --hours 8,12,16
--max-days-per-market 20`. This proves the candidate artifact path and subset
contract, but it is not acceptance evidence because it is a capped smoke run.

Added `weather.reporting.forecast_profile_calibration`, which writes
`data/backtest/item134_forecast_profile_calibration.json` and
`data/backtest/item134_forecast_profile_calibration_report.md`. The report
uses HGB permutation rows with `forecast_high` retained in the fitted model to
quantify marginal value of forecast-profile subfamilies after the
`forecast_high` anchor.

## 2026-06-18 full replay disposition

Trained the uncapped forecast-profile candidate:
`data/backtest/item134_forecast_profile_candidate.pkl` and
`data/backtest/item134_forecast_profile_candidate_report.md` using
`--objective band --feature-subset forecast_profile --hours 8,12,16
--holdout-year 2025`. The artifact reports schema
`pooled_feature_band_hgb_forecast_profile_v0.1`, feature subset
`forecast_profile`, and 14,541 source rows.

Replayed the candidate against `data/backtest/promotion_corpus.json` and wrote
`data/backtest/item134_forecast_profile_replay_report.md`,
`data/backtest/item134_forecast_profile_replay.json`, and
`data/backtest/item134_forecast_profile_shadow_variants.csv`. The replay scored
7,777 forecast-profile candidate rows across the early, midday, and late
cutoff regimes. Aggregate candidate Brier improved current replay
(`0.0500` vs `0.0523`), and each regime improved current replay:
early `-0.0016`, midday `-0.0035`, and late `-0.0017`.

The lane remains blocked for promotion. The daily-first candidate still trails
market prices beyond tolerance (`+0.0089` Brier delta versus market), and the
high-disagreement guardrail blocks Austin, Chicago, Houston, NYC,
San Francisco, and Seattle. The generated
`data/backtest/item134_forecast_profile_calibration_report.md` therefore keeps
acceptance `blocked`.

Remaining acceptance blocker: either improve the forecast-profile lane until
daily-first market tolerance and high-disagreement guardrails pass, or keep it
as a shadow diagnostic lane with explicit promotion blockers.

## 2026-06-19 all-hour replay disposition

The sparse `08/12/16` evidence gap is now closed. The full all-hour
forecast-profile candidate was trained with
`--objective band --feature-subset forecast_profile --holdout-year 2025` and
wrote `data/backtest/item134_forecast_profile_all_hours_candidate.pkl` plus
`data/backtest/item134_forecast_profile_all_hours_candidate_report.md`. The
artifact has hour models `07` through `20`, schema
`pooled_feature_band_hgb_forecast_profile_v0.1`, and the same
forecast-profile subset contract.

Pinned replay against `data/backtest/promotion_corpus.json` wrote
`data/backtest/item134_forecast_profile_all_hours_replay_report.md`,
`data/backtest/item134_forecast_profile_all_hours_replay.json`, and
`data/backtest/item134_forecast_profile_all_hours_shadow_variants.csv`. It
scored all 67,430 F-family rows with zero missing candidate rows, but the gate
still blocks: validation `BLOCK`, market-only verdict `PARTIAL_PASS`, cutover
`DO_NOT_CUT_OVER`. Aggregate candidate Brier is `0.0421` versus current
`0.0435` and market `0.0379`; daily-first candidate Brier is `0.0421` versus
current `0.0434` and market `0.0378`, leaving a daily-first market gap of
`+0.0043`.

Per-market action is mixed. Atlanta, Denver, and Houston are cutover-ready;
Dallas, Los Angeles, and Miami remain shadow; Austin, Chicago, NYC,
San Francisco, and Seattle remain blocked. The high-disagreement guardrail
still blocks Austin, Denver, NYC, San Francisco, and Seattle. The all-hour
run is therefore useful negative evidence: broader forecast-profile coverage
improves current replay, but it does not clear market tolerance or
high-disagreement safety, so it should not be promoted as an Item 48 unblock.
