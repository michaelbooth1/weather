# Weather Forecasting Missing-Input Task Ledger

Created from the 2026-06-14 forecasting-input research pass.

## Completed Now

- [x] Add full hourly forecast-profile features to the shared feature schema:
  forecast peak hour, peak timing relative to cutoff, 12:00-16:00 forecast
  temperatures, afternoon slope, and remaining heating degree-hours.
- [x] Add Open-Meteo radiation/cloud-detail features to the shared schema:
  remaining shortwave sum, next-3h shortwave mean, total/low/mid/high cloud
  means, low/total cloud maxima, and 3h cloud trend.
- [x] Add GFS ensemble uncertainty features already available from the live
  fetcher: day mean member spread, next-3h member spread, daily high p10/p90,
  and p90-p10 spread.
- [x] Preserve those live source fields in `forecasts_long.csv` instead of
  hiding them inside free-text condition strings.
- [x] Extend the Open-Meteo historical forecast archive schema so future
  backfills can store low/mid/high cloud and shortwave radiation.
- [x] Wire historical training and live serving through one shared
  forecast-profile feature helper.
- [x] Keep old LR/HGB artifacts serving by selecting features by trained names
  rather than assuming the newest schema order.

## Completed As Schema-Ready, Needs Backfill/Retrain

- [ ] Re-run `forecast_history backfill` for each market so existing
  `forecast_long.csv` files carry v2 radiation and cloud-layer columns.
- [ ] Retrain per-market and pooled feature models after the v2 backfill so the
  new forecast-profile/radiation/cloud fields are learned rather than mostly
  missing.
- [ ] Run settlement-scored replay/gauntlet reports to prove the new feature
  family improves out-of-sample Brier/log loss before promotion.

## Roadmap Tasks

- [ ] Vertical thermal structure: archive 850/925 hPa temperature, 1000-850 and
  850-700 thickness, 500 hPa height, and warm/cold advection proxies from an
  operational model/reanalysis source.
- [ ] Land-surface and energy budget: archive soil moisture, soil temperature,
  snow cover/depth, vegetation/LAI, surface roughness, latent/sensible heat
  flux, and PBL height.
- [ ] Forecast uncertainty beyond GFS ensemble spread: add NBM percentiles or
  probabilities, forecast run age, and run-to-run high changes.
- [ ] Forecast-vs-realized insolation: add a realized solar/radiation source or
  a defensible proxy before training this feature.
- [ ] Precipitation and convection interruption: add radar/precip rate,
  QPF/PoP, thunder/lightning proxies, CAPE/CIN, precipitable water, and
  post-rain cooling flags.
- [ ] Spatial/upstream context: add nearby station gradients, upstream
  temperature/wind/dewpoint changes, sea/lake-breeze proxies, water
  temperature, distance-to-water, and vetted station elevation.

## Not Done Deliberately

- Static elevation was not added from the current local metadata because the
  Toronto GHCNh station file reports missing elevation (`-999.9`) while the US
  stations have valid elevations. This should be normalized as part of the
  spatial/upstream roadmap task rather than introduced inconsistently.
