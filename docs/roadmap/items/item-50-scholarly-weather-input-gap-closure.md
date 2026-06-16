# 50. Scholarly Weather-Input Gap Closure [COMPLETE 2026-06-16 - CORE BACKFILL AND SHADOW EVIDENCE]

Goal: turn the 2026-06-14 forecasting literature/source audit into a replay-safe
feature roadmap.

Task ledger: `docs/research/WEATHER_FORECASTING_INPUT_TASKS_2026-06-14.md`.

Completed first slice (2026-06-14):

- [x] Add already-fetched Open-Meteo forecast-profile features to the shared
  train/serve schema: peak hour, peak timing, 12:00-16:00 hourly temperatures,
  afternoon slope, and remaining heating degree-hours.
- [x] Add already-fetched Open-Meteo radiation/cloud detail: remaining
  shortwave, next-3h shortwave, total/low/mid/high cloud summaries, low/total
  cloud maxima, and cloud trend.
- [x] Add already-fetched GFS ensemble uncertainty: day mean member spread,
  next-3h spread, daily high p10/p90, and p90-p10 spread.
- [x] Persist those live fields in `forecasts_long.csv` and extend the
  historical Open-Meteo forecast archive schema so future backfills store
  low/mid/high cloud and shortwave.
- [x] Keep old LR/HGB artifacts serving by selecting coefficient inputs by
  trained feature names rather than by newest schema position.

Validation/data tasks:

- [x] Re-run per-market Open-Meteo forecast-history backfills so existing
  `forecast_long.csv` files carry the v3 radiation/cloud-layer columns.
- [x] Retrain per-market and pooled feature models, then run settlement-scored
  replay/gauntlet reports to prove the new feature family improves Brier/log
  loss before promotion.

Roadmapped infrastructure tasks:

- [x] Vertical thermal structure/advection: historical Open-Meteo archive rows
  now carry partial 850/925 hPa temperature and 500 hPa height coverage
  (`5328/7992` rows per market), but thickness and advection proxies remain
  blocked behind `item-76` GRIB subset extraction plus a named
  `item50_vertical_thermal_archive_backfill` task.
- [x] Land-surface and energy budget: soil temperature/moisture coverage is
  partial (`3552/7992` rows per market), and snow, vegetation, flux, roughness,
  and PBL fields remain blocked behind a named
  `item50_land_surface_energy_archive_backfill` source-selection task.
- [x] Forecast uncertainty beyond GFS spread: NBM percentiles/probabilities,
  forecast run age, and run-to-run high changes remain blocked behind `item-75`
  US guidance diagnostics plus a named `item50_nbm_reforecast_archive_backfill`
  task.
- [x] Realized-vs-forecast insolation: no realized radiation source is promoted;
  this remains blocked behind `item-81` fallback-source work plus a named
  `item50_realized_insolation_archive_backfill` task.
- [x] Precipitation/convection interruption: historical PoP coverage is partial
  (`1776/7992` rows per market), while radar/lightning/thunder/CIN/PWAT features
  remain blocked behind `item-79` MRMS work plus a named
  `item50_convection_archive_backfill` task.
- [x] Spatial/upstream context: marine/lake-breeze and nearby-station ideas
  remain blocked behind `item-78` coastal context work and a named
  `item50_upstream_spatial_context_backfill` task.

Acceptance: every new weather-input family is either trained and
settlement-scored, or explicitly blocked behind a named source/archive/backfill
task. No feature should be promoted from live-only availability without matching
historical/reforecast coverage.

Completion update 2026-06-16:

- Added repeatable fleet forecast-history coverage reporting in
  `src/weather/sources/forecast_history.py`:
  `python -m src.forecast_history fleet-coverage --json-out ... --out ...`.
  The report uses schema `forecast_history_coverage_v0.1`, verifies the exact
  v3 CSV header/schema, and separates core required cloud/radiation completeness
  from partial experimental archive fields.
- Re-ran all 12 Open-Meteo forecast-history backfills with
  `--start-year 2015 --end-year 2026 --no-previous-runs`. Open-Meteo returned
  no target-season 2015 archive rows, and all markets now hold 333 days /
  7,992 v3 historical rows from 2018..2026.
- Coverage evidence:
  `data/backtest/item50_forecast_history_v3_coverage.json` and
  `data/backtest/item50_forecast_history_v3_coverage_report.md`. The fleet
  report is 12/12 OK for core replay-safe cloud/radiation fields and records
  partial archive coverage for vertical, soil, and PoP fields.
- Per-market feature-value evidence:
  `data/backtest/item50_feature_value_gate_summary.json` and
  `data/backtest/item50_feature_value_gate_summary_report.md`. The forecast
  family promotes in 7 markets and blocks in 5, with weighted held-out deltas
  `+0.003229` log-loss and `+0.000548` Brier. Blocked forecast-family markets
  are Toronto, Atlanta, Dallas, Los Angeles, and Seattle.
- Pooled candidate retrain artifact:
  `data/backtest/item50_feature_model_hgb_f_pooled_v0_3_candidate.pkl`; model
  report: `data/backtest/item50_f_family_pooled_band_model_report.md`. This is
  an Item 50 research artifact and does not replace the canonical serving
  artifact.
- Settlement-scored replay evidence:
  `data/backtest/item50_pooled_candidate_replay.json` and
  `data/backtest/item50_pooled_candidate_replay_report.md`. Verdict is
  `PASS_WITH_SHADOWS` / `PER_MARKET_ONLY`: aggregate candidate Brier `0.041980`
  improves current replay `0.043554` by `-0.001574`, but still trails market
  Brier `0.037869` by `+0.004111`. Per-market action is 5 cutover-ready
  markets, 6 continue-shadow markets, and 0 blocked markets.
- Multi-variant verifier evidence:
  `data/backtest/item50_pooled_multi_variant_shadow.json` and
  `data/backtest/item50_pooled_multi_variant_shadow_report.md` returned `OK`
  with 67,430 scored rows, 44 market-days, 11 F markets, zero warnings, and
  zero errors. Daily-first candidate Brier is `0.041929`, current Brier
  `0.043496`, and market Brier `0.037830`.
- Promotion decision: no live-only input is promoted. The core Open-Meteo
  cloud/radiation slice is replay-safe and scored, but the F-family candidate
  remains Item 48 shadow/per-market-only until aggregate market skill and
  remaining shadow-market proof clear.
