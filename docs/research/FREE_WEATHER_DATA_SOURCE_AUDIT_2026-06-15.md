# Free Weather Data Source Audit - 2026-06-15

## Scope

Goal: find free online weather and adjacent data sources that could improve the
weather-market model, compare them against what the repo already uses, smoke-test
the promising ones, and record candidates worth integrating.

This audit is intentionally source-first. It does not promote any source into
settlement truth. WU history remains the settlement proxy unless a
market's resolution source changes. Candidate sources should be treated as
features, redundancy checks, source-trust signals, or backfill aids.

## Current Source Inventory

Implemented live or historical sources already present in the repo:

| Source | Current use | Main files |
| :--- | :--- | :--- |
| Weather Underground history | Settlement-proxy intraday and daily highs | `weather.model.model_sources`, `weather.sources.wu_history` |
| disabled paid-provider current and hourly forecast | Live current max/current temp and one forecast source | `weather.model.model_sources` |
| ECCC citypage | Toronto current/forecast high | `weather.model.model_sources` |
| ECCC SWOB | Toronto official leading observation stream | `weather.model.model_sources`, `weather.sources.eccc_swob_history` |
| AviationWeather METAR | Live airport observation | `weather.model.model_sources` |
| IEM ASOS/METAR archive | Historical redundant METAR/ASOS | `weather.sources.metar_history` |
| NOAA GHCNh | Historical hourly station redundancy | `weather.sources.noaa_ghcnh_history` |
| Open-Meteo forecast | Live forecast, clouds, shortwave, wind | `weather.model.model_sources` |
| Open-Meteo historical forecast / previous runs | Forecast history for train/serve parity | `weather.sources.forecast_history` |
| Open-Meteo ERA5-style reanalysis | Historical gridded redundant history | `weather.sources.reanalysis_history` |
| NWS hourly forecast | US hourly forecast source | `weather.model.model_sources` |
| Open-Meteo GFS ensemble API | Live ensemble mean/spread/high percentiles | `weather.model.model_sources` |
| Polymarket Gamma/CLOB | Market prices, books, microstructure | `weather.market.*` |

Already known local feature gaps from
`docs/research/WEATHER_FORECASTING_INPUT_TASKS_2026-06-14.md`:

- Vertical thermal structure: 925/850 hPa temperature, thickness, 500 hPa height.
- Land-surface and energy-budget state: soil moisture/temp, snow, PBL, fluxes.
- Forecast uncertainty beyond the current GFS ensemble spread.
- Realized solar/radiation or defensible proxy.
- Precipitation/convection interruption: radar/QPE, CAPE/CIN, precipitable water.
- Spatial/upstream context: nearby gradients, marine/lake-breeze proxies.

## Highest-Potential Tested Sources

### 1. Open-Meteo Expanded Forecast Fields

Docs: [Open-Meteo Forecast API](https://open-meteo.com/en/docs),
[Open-Meteo GFS and HRRR API](https://open-meteo.com/en/docs/gfs-api),
[Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api).

Why it matters:

- Lowest integration cost: JSON, no API key, same provider already used.
- Directly closes several existing feature gaps: CAPE, pressure levels,
  direct/diffuse radiation, gusts, visibility, soil temp/moisture, VPD, ET0,
  precip/probability, freezing level.
- Supports model-specific columns through `/v1/gfs` with model IDs:
  `gfs_seamless`, `ncep_hrrr_conus`, `ncep_nbm_conus`, `ncep_nam_conus`.

Smoke tests:

- `https://api.open-meteo.com/v1/forecast` for Atlanta returned 24 requested
  fields: `temperature_2m`, `dew_point_2m`, `relative_humidity_2m`,
  `surface_pressure`, `cloud_cover`, `shortwave_radiation`, `direct_radiation`,
  `diffuse_radiation`, `precipitation_probability`, `precipitation`, `rain`,
  `showers`, `cape`, `freezing_level_height`, `visibility`, `weather_code`,
  `wind_gusts_10m`, `vapour_pressure_deficit`,
  `et0_fao_evapotranspiration`, `soil_temperature_0cm`,
  `soil_moisture_0_to_1cm`, `temperature_925hPa`, `temperature_850hPa`,
  `geopotential_height_500hPa`.
- Sample at Atlanta 2026-06-15 12:00 local: `temperature_2m=77.7 F`,
  `dew_point_2m=64.1 F`, `relative_humidity_2m=63`,
  `shortwave_radiation=882 W/m2`, `direct_radiation=742 W/m2`,
  `diffuse_radiation=140 W/m2`.
- `/v1/gfs` with
  `models=best_match,gfs_seamless,ncep_hrrr_conus,ncep_nbm_conus,ncep_nam_conus`
  returned 20 model-specific columns for `temperature_2m`, `dew_point_2m`,
  `shortwave_radiation`, `cape`, and `temperature_850hPa`.

Verdict: integrate first. This is the fastest path to feature experiments and
backfillable train/serve parity.

Recommended features:

- Remaining-day CAPE max/mean, next-3h CAPE, CAPE trend.
- 925/850 hPa temp and surface-to-850 lapse proxies.
- 500 hPa height and day-over-day height tendency if archived.
- Direct/diffuse/shortwave radiation after cutoff.
- Soil temp/moisture, VPD, ET0 as heating-efficiency and boundary-layer proxies.
- Multi-model high spread and HRRR/NBM/NAM minus best-match deltas.

### 2. NWS Raw Gridpoint Data

Docs: [NWS API](https://www.weather.gov/documentation/services-web-api),
[NWS gridpoint FAQ](https://weather-gov.github.io/api/gridpoints).

Why it matters:

- Already using NWS hourly periods, but not the raw `forecastGridData`.
- The raw grid gives structured `temperature`, `maxTemperature`, `dewpoint`,
  `relativeHumidity`, `skyCover`, `probabilityOfPrecipitation`,
  `quantitativePrecipitation`, `weather`, `windSpeed`, and `windDirection`.
- It is free/open with a no-key JSON API and a generous but unpublished rate
  limit.

Smoke test:

- Atlanta `points` lookup returned `forecastGridData` =
  `https://api.weather.gov/gridpoints/FFC/49,81`.
- Grid payload returned 257,927 bytes with structured value counts:
  `temperature=126`, `relativeHumidity=151`, `skyCover=85`,
  `windSpeed=61`, `dewpoint=56`, `probabilityOfPrecipitation=55`,
  `quantitativePrecipitation=32`, `weather=31`, `maxTemperature=8`.
- First sample included 2 m temperature, dewpoint, RH, sky, wind, POP, QPF,
  weather, and max-temperature periods.

Verdict: high priority for US markets. It is a cheap official structured
forecast complement to the current NWS hourly period feed.

Recommended features:

- NWS maxTemperature vs WU/Open-Meteo consensus.
- Raw-grid sky/POP/QPF after cutoff.
- Dewpoint/RH and wind changes by valid period.
- Weather hazard/precip interruption flags.

### 3. NOAA NBM

Docs: [NOAA NBM AWS registry](https://registry.opendata.aws/noaa-nbm/),
[NOMADS NBM filter](https://nomads.ncep.noaa.gov/gribfilter.php?ds=blend),
[NBM weather elements](https://vlab.noaa.gov/web/mdl/nbm-weather-elements).

Why it matters:

- Official calibrated blend guidance for US markets.
- Provides deterministic fields and ensemble standard deviation fields.
- Directly addresses the "forecast uncertainty beyond GFS ensemble spread" gap.

Smoke tests:

- S3 listing succeeded for `noaa-nbm-grib2-pds`, current prefix
  `blend.20260615/20/core/`.
- `.idx` file for `blend.t20z.core.f001.co.grib2` exposed:
  `TMP:2 m above ground`, `TMP ... ens std dev`, `DPT ... ens std dev`,
  `RH`, `GUST ... ens std dev`, `TCDC ... ens std dev`, `APCP`, and visibility
  probability rows.
- NOMADS subset test succeeded for Atlanta box:
  `filter_blend.pl?file=blend.t20z.core.f001.co.grib2&dir=/blend.20260615/20/core&...&var_TMP=on&lev_2_m_above_ground=on`
  returned a GRIB2 subset of 2,908 bytes.
- Open-Meteo `/v1/gfs` also exposes `ncep_nbm_conus` as a JSON model source.

Verdict: high priority. Start through Open-Meteo for quick feature tests; use
raw NOMADS/S3 if we need exact NBM fields, probability products, or archive
control.

Recommended features:

- NBM 2 m temperature high and spread.
- NBM minus HRRR/GFS/NAM forecast deltas.
- Cloud, gust, precip, and visibility probability features.
- NBM uncertainty as a model-confidence scaler.

### 4. NOAA HRRR

Docs: [NOAA HRRR product inventory](https://www.nco.ncep.noaa.gov/pmb/products/hrrr/),
[NOMADS HRRR filter](https://nomads.ncep.noaa.gov/gribfilter.php?ds=hrrr_2d),
[HRRR overview](https://rapidrefresh.noaa.gov/hrrr/).

Why it matters:

- Convection-allowing 3 km US model, hourly refresh.
- Strong candidate for same-day local maximum temperature, cloud, radiation,
  wind shift, precip/convection interruption, and boundary-layer features.

Smoke test:

- NOMADS subset for Atlanta box succeeded:
  `filter_hrrr_2d.pl?file=hrrr.t21z.wrfsfcf00.grib2&dir=/hrrr.20260615/conus&...&var_TMP=on&lev_2_m_above_ground=on`
  returned a GRIB2 subset of 1,480 bytes.
- Open-Meteo `/v1/gfs` exposes `ncep_hrrr_conus` as JSON for quick comparison.

Verdict: high priority for US live features. Prefer Open-Meteo JSON first;
graduate to raw HRRR for fields not exposed or for precise run-age handling.

Recommended features:

- HRRR next-6h/high-of-day 2 m temperature.
- HRRR residual vs observed WU/METAR high-so-far.
- HRRR CAPE/radiation/cloud after cutoff.
- HRRR run age and last-update delta.

### 5. NOAA RTMA/URMA

Docs: [NOAA RTMA/URMA AWS registry](https://registry.opendata.aws/noaa-rtma/),
[NOMADS RTMA filter](https://nomads.ncep.noaa.gov/gribfilter.php?ds=rtma2p5),
[NCO RTMA products](https://www.nco.ncep.noaa.gov/pmb/products/rtma/).

Why it matters:

- Hourly 2.5 km analysis fields for US nowcasting and verification.
- Useful as gridded realized context when station observations are sparse or
  delayed, not as settlement truth.

Smoke test:

- Initial same-day URL failed because NOMADS exposed RTMA only through
  2026-06-14 and files used `_wexp`.
- Corrected URL succeeded:
  `filter_rtma2p5.pl?file=rtma2p5.t20z.2dvaranl_ndfd.grb2_wexp&dir=/rtma2p5.20260614&...&var_TMP=on&lev_2_m_above_ground=on`
  returned a GRIB2 subset of 2,258 bytes.

Verdict: medium-high. Use for lagged verification, station-bias context, and
weather-regime features. It is less useful for a same-minute live model because
of analysis publication lag.

### 6. IEM / NCEI One-Minute ASOS

Docs: [IEM ASOS one-minute page](https://mesonet.agron.iastate.edu/request/asos/1min.phtml),
[IEM one-minute CGI docs](https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?help=),
[NCEI ASOS/AWOS products](https://www.ncei.noaa.gov/products/land-based-station/automated-surface-weather-observing-systems).

Why it matters:

- Current METAR history is hourly plus specials. One-minute data can reveal
  exact high timing and short spikes that hourly METAR misses.
- Best for training "high has stood", late-day continuation, and station high
  path features.

Smoke tests:

- Correct station IDs omit the leading `K`: `LGA`, `ATL`, `ORD`.
- `LGA`, 2025-06-14 12:00-14:00 UTC returned 121 lines with one-minute
  `tmpf`, `dwpf`, wind, direction, and pressure fields.
- Same request for `ATL` and `ORD` returned headers only in the tested window.
- `LGA` 2026-06-14 returned headers only, consistent with IEM's documented
  availability delay and station/date variability.

Verdict: high value but not universal. Build a station/date availability matrix
before using it for all markets.

Recommended features:

- One-minute max-so-far and exact first-reached time.
- Intra-hour max since last WU print.
- Spike persistence and high-duration features.
- Hourly METAR miss/exceed calibration by station.

### 7. NOAA CO-OPS and NDBC Marine / Coastal Data

Docs: [NOAA CO-OPS Data API](https://api.tidesandcurrents.noaa.gov/api/prod/),
[NOAA CO-OPS products](https://tidesandcurrents.noaa.gov/products.html),
[NDBC realtime data access](https://www.ndbc.noaa.gov/faq/rt_data_access.shtml).

Why it matters:

- Coastal and lake-adjacent markets have sea/lake-breeze and marine-layer
  failure modes: NYC, Miami, Houston, Los Angeles, San Francisco, Seattle,
  Chicago, and Toronto.
- Water temperature, coastal wind, pressure, and marine air temp can explain
  suppressed afternoon highs or sudden onshore cooling.

Smoke tests:

- CO-OPS San Francisco `9414290` returned hourly air temperature and wind on
  2026-06-15, but no water temperature at that station.
- CO-OPS water temperature returned hourly rows for:
  Miami/Virginia Key `8723214` (`30.7 C` at 00:00),
  another Miami-area station `8721604`,
  Galveston/Houston-area `8771450` (`31.4 C`),
  NYC Battery `8518750` (`18.6 C`).
- NDBC station `46026` returned realtime flat-file rows with wind, pressure,
  wave, and water temperature fields. Sample latest water temperatures were
  around `13.4-13.8 C`.

Verdict: high value for coastal-market feature engineering. Requires a
per-market station map and missing-sensor fallback rules.

Recommended features:

- Water-minus-air temperature gradient.
- Coastal wind direction/speed and onshore-flow flag.
- Marine-layer risk flag for west-coast markets.
- Lake/sea breeze reversal after cutoff.

### 8. NOAA MRMS Radar / QPE

Docs: [NOAA MRMS AWS registry](https://registry.opendata.aws/noaa-mrms-pds/),
[MRMS operational tables](https://www.nssl.noaa.gov/projects/mrms/operational/tables.php),
[NSSL MRMS overview](https://www.nssl.noaa.gov/projects/mrms/).

Why it matters:

- Precipitation and convection interrupt heating. The model currently has
  forecast precip/CAPE candidates but no realized radar/QPE source.
- MRMS has 2-minute precip-rate products and 15m/1h QPE products.

Smoke tests:

- S3 listing succeeded for current dated prefixes:
  `CONUS/PrecipRate_00.00/20260615/` returned
  `MRMS_PrecipRate_00.00_20260615-000000.grib2.gz`,
  `...000200.grib2.gz`, `...000400.grib2.gz`.
- Top-level product listing also exposed historical keys back to 2020-10-14.

Verdict: medium-high. The signal is strong, but integration needs GRIB
subsetting or nearest-grid extraction. Use binary rain/convection flags first.

Recommended features:

- Any precip within last 15/30/60 minutes near the station.
- QPE since 7 AM and since cutoff.
- Convective interruption flag when precip/radar happens during peak heating.

### 9. ECCC GeoMet / HRDPS / Canadian Open Data

Docs: [MSC GeoMet](https://eccc-msc.github.io/open-data/msc-geomet/readme_en/),
[MSC Datamart](https://eccc-msc.github.io/open-data/msc-datamart/readme_en/),
[HRDPS Datamart](https://eccc-msc.github.io/open-data/msc-data/nwp_hrdps/readme_hrdps-datamart_en/),
[GeoMet OpenAPI](https://api.weather.gc.ca/openapi).

Why it matters:

- Toronto already uses ECCC citypage and SWOB, but not ECCC gridded forecast
  models.
- HRDPS is 2.5 km over Canada with detailed surface and vertical fields,
  specifically valuable near shores and local terrain.

Smoke tests:

- `https://api.weather.gc.ca/collections?f=json&limit=100` returned 103
  GeoMet collections, including climate hourly/daily, SWOB real-time/stations,
  and marine weather collections.
- HRDPS Datamart listing succeeded for 2026-06-15 00/06/12/18 UTC runs.
  Each listed `GUST_AGL-10m` and `TMP_AGL-2m` files.
- HEAD on
  `https://dd.weather.gc.ca/today/model_hrdps/continental/2.5km/18/001/20260615T18Z_MSC_HRDPS_TMP_AGL-2m_RLatLon0.0225_PT001H.grib2`
  returned 200 with content length 3,645,582 bytes.

Verdict: high priority for Toronto and future Canadian markets. Start with
Open-Meteo GEM/HRDPS if fields are sufficient; use raw Datamart GRIB when exact
HRDPS fields or run provenance matter.

### 10. Meteostat Bulk Data

Docs: [Meteostat data access](https://dev.meteostat.net/data),
[Meteostat hourly bulk](https://dev.meteostat.net/data/timeseries/hourly).

Why it matters:

- Free, no signup, global historical station data with CSV/GZIP bulk files.
- Useful for global market expansion and fallback station discovery.
- Provides `_source` columns, which matter because some fields are model-filled.

Smoke test:

- `https://data.meteostat.net/hourly/2025/72503.csv.gz` returned a 98 KB
  gzip CSV for KLGA/NYC.
- Rows include `temp`, `rhum`, `prcp`, `wdir`, `wspd`, `pres`, `cldc`, `coco`
  and corresponding source columns such as `isd_lite` and `dwd_mosmix`.

Verdict: high value for station discovery and global expansion. Do not use
model-filled values as settlement or observation truth without preserving source
columns.

### 11. NASA POWER

Docs: [NASA POWER Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/).

Why it matters:

- Global historical and near-real-time meteorology and solar data.
- Good for solar/energy-budget backfills when station or model radiation fields
  are unavailable.

Smoke tests:

- Atlanta 2025-06-14 to 2025-06-15 returned valid hourly values for `T2M`,
  `T2MDEW`, `RH2M`, `PS`, `WS10M`, `ALLSKY_SFC_SW_DWN`,
  `CLRSKY_SFC_SW_DWN`, and `PRECTOTCORR`.
- Atlanta 2026-06-01 returned met values but no valid solar values.
- Atlanta 2026-06-14 returned fill values for all tested parameters.

Verdict: useful for historical/backfill experiments, not a live same-day source.
Treat recent NRT completeness as a source-lag feature.

## Promising But Deferred

| Source | Why it could help | Why not first |
| :--- | :--- | :--- |
| ECMWF Open Data IFS/AIFS | Global high-skill deterministic/AI forecasts, useful for non-US markets | Raw GRIB/object-store complexity; Open-Meteo exposes ECMWF fields faster for experiments |
| DWD ICON Open Data | Strong global/Europe model, useful for European markets | Raw GRIB complexity; Open-Meteo DWD API is easier first |
| ECCC GDPS/RDPS raw model data | Canadian/global forecast depth | HRDPS/Open-Meteo GEM is the narrower Toronto-first path |
| GOES/GLM public satellite/lightning | Cloud, insolation, lightning, smoke/convection nowcasting | Heavy geospatial pipeline; start with MRMS/Open-Meteo radiation/CAPE |
| Open-Meteo Air Quality / CAMS / UV | Smoke, aerosol, UV, pollen can affect heating/radiation | Lower first-order value than radiation, precip, marine, and vertical thermal fields |
| Open-Meteo Marine API | Wave/water/wind context | CO-OPS/NDBC are better official station proxies for US coastal markets |
| Synoptic Data HF-ASOS | Possible low-latency high-frequency ASOS feed | Requires token/account and HF-ASOS is experimental; IEM/NCEI archive is enough for backfill first |
| Visual Crossing, WeatherAPI, Tomorrow.io, OpenWeather free tiers | Easy JSON, sometimes historical forecast fields | API keys, free-tier limits, license/ToS review, and overlapping signal with official/open sources |

## Integration Priority

### P0: Cheap JSON Features

1. Extend Open-Meteo live and historical forecast requests with:
   `cape`, `temperature_925hPa`, `temperature_850hPa`,
   `geopotential_height_500hPa`, `direct_radiation`, `diffuse_radiation`,
   `wind_gusts_10m`, `visibility`, `precipitation_probability`,
   `precipitation`, `soil_temperature_0cm`, `soil_moisture_0_to_1cm`,
   `vapour_pressure_deficit`, and `et0_fao_evapotranspiration`.
2. Add a US-only Open-Meteo multi-model source using `/v1/gfs` and
   `gfs_seamless,ncep_hrrr_conus,ncep_nbm_conus,ncep_nam_conus`.
3. Add NWS `forecastGridData` extraction for US markets.

Expected model value:

- Better same-day heating potential.
- Explicit convection/precip interruption risk.
- Better forecast-source disagreement and model-run uncertainty.
- Much lower implementation risk than GRIB-first work.

### P1: High-Frequency And Coastal Context

1. Build IEM one-minute ASOS availability audit by market/station/year.
2. Add per-market CO-OPS/NDBC station map for coastal and lake-influenced
   markets.
3. Add marine/coastal features only when station freshness and sensor support
   pass simple gates.

Expected model value:

- Late-day lock-in and spike persistence.
- Onshore/lake-breeze suppression flags.
- Better microclimate handling for coastal markets.

### P2: GRIB Feature Extractors

1. Add a tiny GRIB subsetting/extraction proof for NOMADS HRRR/NBM/RTMA using
   nearest station gridpoint.
2. Add MRMS precip/QPE binary and rolling-window features.
3. Add ECCC HRDPS extraction for Toronto if Open-Meteo GEM/HRDPS is not enough.

Expected model value:

- Official high-resolution model fields with exact run provenance.
- Realized radar/precip interruption.
- RTMA/URMA grid analysis for verification and missing-observation context.

## Guardrails

- Preserve `source`, `model`, `run_time`, `issue_time`, `valid_time`,
  `fetched_at`, `payload_hash`, and source freshness for every added source.
- Keep train/serve parity: any live feature needs a historical backfill path or
  must be explicitly marked live-only and excluded from historical training.
- Do not use gridded analysis, Meteostat model-filled rows, NASA POWER, or
  marine observations as settlement labels.
- Normalize units at source boundaries and keep native values where the market
  settles in Fahrenheit.
- Treat missingness as information. Many candidate sources are station-,
  sensor-, model-, or lag-dependent.

## Bottom Line

The best immediate additions are not new settlement labels. They are additional
forecast and environmental context features:

1. Open-Meteo expanded fields and multi-model source columns.
2. NWS raw gridpoint data.
3. NBM/HRRR model-specific features, first through Open-Meteo and later through
   NOMADS/S3 where needed.
4. IEM one-minute ASOS for selected US station history.
5. CO-OPS/NDBC marine context for coastal and lake-influenced markets.
6. MRMS precip/radar flags for realized convection.
7. ECCC HRDPS/GEM for Toronto.

These sources show enough live accessibility and feature relevance to justify
implementation experiments before adding lower-priority commercial free-tier or
heavy satellite pipelines.
