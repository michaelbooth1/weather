# 50. Scholarly Weather-Input Gap Closure [NEW - OPEN]

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

Open validation/data tasks:

- [ ] Re-run per-market Open-Meteo forecast-history backfills so existing
  `forecast_long.csv` files carry the v2 radiation/cloud-layer columns.
- [ ] Retrain per-market and pooled feature models, then run settlement-scored
  replay/gauntlet reports to prove the new feature family improves Brier/log
  loss before promotion.

Roadmapped infrastructure tasks:

- [ ] Vertical thermal structure/advection: 850/925 hPa temperature, 1000-850
  and 850-700 thickness, 500 hPa height, and warm/cold advection proxies.
- [ ] Land-surface and energy budget: soil moisture/temp, snow cover/depth,
  vegetation/LAI, surface roughness, latent/sensible heat flux, and PBL height.
- [ ] Forecast uncertainty beyond GFS spread: NBM percentiles/probabilities,
  forecast run age, and run-to-run high changes.
- [ ] Realized-vs-forecast insolation: add a realized radiation source or
  defensible proxy before training this feature.
- [ ] Precipitation/convection interruption: radar/precip rate, QPF/PoP,
  lightning/thunder proxies, CAPE/CIN, precipitable water, and post-rain
  cooling flags.
- [ ] Spatial/upstream context: nearby-station gradients, upstream temperature /
  wind / dewpoint changes, sea/lake-breeze proxies, water temperature,
  distance-to-water, and vetted station elevation.

Acceptance: every new weather-input family is either trained and
settlement-scored, or explicitly blocked behind a named source/archive/backfill
task. No feature should be promoted from live-only availability without matching
historical/reforecast coverage.
