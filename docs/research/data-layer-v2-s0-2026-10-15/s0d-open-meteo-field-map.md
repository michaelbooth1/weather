# S0(d) receipt: Open-Meteo served-payload field map

- Date: 2026-10-15. Code: commit `9fc1ff062` (master plus the 10-15 docs batch). Read only. No network calls made.
- Data inspected (workstation copy, all target dates before 2026-09-30): `data/snapshots/highest-temperature-in-{toronto-on-july-27,san-francisco-on-august-10,nyc-on-july-9,*-on-july-12}-2026/` (`forecast_payloads_long.csv` and the `forecast_payloads/sha256/**.json` blobs). Nothing dated 2026-09-30..10-15 was opened.

## 1. Who requests what

Served markets are the 12 built-ins in `src/weather/market/market_registry.py` (Toronto :100-115, 11 US :117-300). `config/markets.json` (the external registry, :25) holds 0 rows. The 51 `config/locations.json` rows list `open_meteo` only in `live_source_plan` (for example :51-57). Nothing in the fetch path reads that field; it is used only by the inventory report (`reporting/source_gates/source_family_inventory.py:1517`).

Source wiring is in `model/model_sources.py:197-231`. If a market declares `open_meteo`, it also gets `open_meteo_air_quality` and `open_meteo_global_models` (:219-222). All six Open-Meteo-family keys (:70-77) share one serial worker (:258-270), a fresh-cache reuse equal to the TTL (:434-483, :512-514), and a shared 429 cooldown. TTLs are in `model/model_constants.py:45-54`: open_meteo 90 min, the others 120 min.

Common to every request: `timezone=<market tz>`, `forecast_days=2`, `temperature_unit=` market native (`market_registry.py:74-75`). None of them sets `past_days`, `daily`, `minutely_15`, `elevation`, `cell_selection` or `models=best_match`. All are hourly only.

| # | Source key (markets) | Endpoint | models | hourly fields | Members | Stored where | Bytes/payload (pre-09-30, measured) | Distinct blobs per market-day (measured) |
|---|---|---|---|---|---|---|---|---|
| 1 | `open_meteo` (all 12) `model_sources.py:1525-1545` | `api.open-meteo.com/v1/forecast` | none (= best_match blend) | 21: temperature_2m, cloud_cover, cloud_cover_low/mid/high, wind_speed_10m, shortwave_radiation, cape, temperature_925hPa, temperature_850hPa, geopotential_height_500hPa, direct_radiation, diffuse_radiation, wind_gusts_10m, visibility, precipitation_probability, precipitation, soil_temperature_0cm, soil_moisture_0_to_1cm, vapour_pressure_deficit, et0_fao_evapotranspiration; `wind_speed_unit=kmh` | none (single blended series) | market-local CAS `data/snapshots/<event>/forecast_payloads/sha256/xx/<h>.json` + manifest rows in `forecast_payloads_long.csv` / `forecast_payloads.jsonl` (`collection/snapshot_store.py:632-634, 1621-1911`) | 6,660-6,870 (Tor 07-27, SF 08-10); 8,057 (NYC 07-09, °F) | 16 |
| 2 | `open_meteo_air_quality` (all 12) `:1609-1647` | `air-quality-api.open-meteo.com/v1/air-quality` | CAMS auto | pm2_5, pm10, aerosol_optical_depth, dust, us_aqi, european_aqi (`:78-85`) | none | same | 2,510-2,950 | 12 |
| 3 | `open_meteo_global_models` (all 12) `:1649-1723` | `/v1/forecast` | ecmwf_ifs025, ecmwf_aifs025, ncep_aigfs025, gfs_graphcast025 (`:86-91`) | temperature_2m only, one column per model | 4 deterministic per-model columns | same | 2,390-2,680 | 12 |
| 4 | `open_meteo_multimodel` (11 US; code no-ops for non-US) `:2101-2205` | `api.open-meteo.com/v1/gfs` | gfs_seamless, ncep_hrrr_conus, ncep_nbm_conus, ncep_nam_conus | 18 of the 21 (all except cloud_cover_low/mid/high), × 4 models = 72 columns | 4 deterministic per-model columns | same | 23,460 (SF 08-10); 27,770 (NYC 07-09) | 11-12 |
| 5 | `global_ensemble` (all 12) `:2207-2285` | `ensemble-api.open-meteo.com/v1/ensemble` | gfs_seamless (GEFS) | temperature_2m only | **31 columns**: `temperature_2m` + `temperature_2m_member01..30`, all kept raw | same | 10,430 (Tor, SF); 12,200 (NYC) | 11-12 |
| 6 | `eccc_gem` (Toronto only) `sources/eccc_gridded.py:101-111, 132` | `api.open-meteo.com/v1/gem` | gem_seamless, gem_global, gem_regional (`:17`) | 11 fields: temperature_2m, wind_speed_10m, wind_direction_10m, wind_gusts_10m, cloud_cover, precipitation, relative_humidity_2m, surface_pressure, temperature_925hPa, temperature_850hPa, geopotential_height_500hPa (`:22-34`) × 3 models = 33 columns | 3 deterministic | same | 10,820-10,840 | 12 |

How the payloads are stored:
- What is kept is the **whole `response.json()` dict**: all 48 hourly steps (today and tomorrow, local time), `hourly_units`, and the grid-snapped lat/lon, elevation, generationtime_ms and utc_offset. It is re-serialized as canonical JSON (`sort_keys`, compact; `snapshot_store.py:1294-1306, 1344-1400`), so these are **not the wire bytes**. HTTP headers are dropped (`get_json`, `model_sources.py:2449-2454`).
- The shared `data/forecast_payload_cas` holds **no Open-Meteo payloads**. Only explicitly attested market-invariant sources go there, which today means `nbm_probabilistic_tmax` (`collection/forecast_payload_cas.py:386-416`, `forecast_payload_contracts.py:12`). Every Open-Meteo row has `payload_storage_scope=market_local` (SF 08-10 manifest).
- Run identity is empty on every Open-Meteo manifest row: `forecast_run_time`, `ensemble_member` and `provider_issue_time` are all blank (SF 08-10). The code hard-codes `model_run_age_status="not_exposed_by_open_meteo_*"` (`:1708, :2189`; `eccc_gridded.py:20`).
- Retention defaults on (`snapshot_store.py:2177-2181`, env override). The manifest still has a row per snapshot (141-184 per market-day); blobs dedup by hash.
- The parsed outputs (`rows[:12]`, target-day `day_rows`, `day_max`, member p10/p90) go to forecasts/features/replay_inputs. `raw_payload` is stripped from those (`snapshot_store.py:2190-2198`).
- There is a second copy of the latest `data` dict, including `raw_payload`, in the per-market `last_good_sources.json` (`model_sources.py:517-615`). It is a cache, not history.
- Size estimate (est.): about 0.57 MB per US market-day of unique Open-Meteo blobs and about 0.42 MB for Toronto. That is roughly 7 MB/day across the 12 markets per open target date, and about 13 MB/day if two target dates are open (est., not summed on the host).
- The 21-field set already appears in the workstation blobs from 2026-07-12 (SF, Seattle, Toronto). The plan's "since 08-08" refers to production retention, which I did not check.

## 2. Available from Open-Meteo but NOT requested (relevant to daily Tmax/Tmin)

Source: Open-Meteo API docs as I know them. I did not fetch the docs page; S0(f)/FC-3 should confirm the names against the current docs.

**Request parameters not used**
- `daily=temperature_2m_max,temperature_2m_min` (also apparent_temperature_max/min, sunshine_duration, daylight_duration, shortwave_radiation_sum, wind_speed_10m_max). The code derives Tmax as the max of 24 hourly values instead (`:1593-1595`). **No Tmin is derived anywhere in this path.**
- `minutely_15=temperature_2m`. Native 15-min data exists for HRRR/ICON-D2/AROME-class domains and is interpolated elsewhere. It catches intra-hour peaks the hourly max misses.
- `elevation=<station elevation>` and `cell_selection`. Today the request uses the default land cell and the DEM elevation. The payload shows grid points snapped up to ~0.1° away (Toronto global models at 43.75,-79.75 against the station at 43.68,-79.63).
- `past_days`. Not needed live, since local-tz `forecast_days=2` already starts at today 00:00.

**Hourly fields not requested** (all for the main `open_meteo` call): relative_humidity_2m, dew_point_2m, apparent_temperature, pressure_msl/surface_pressure, wind_direction_10m (GEM only), sunshine_duration, boundary_layer_height, weather_code, temperature_80m/120m, lifted_index, convective_inhibition, freezing_level_height, total_column_integrated_water_vapour, soil_temperature_6cm.

**Deterministic models not requested**: icon_seamless/icon_global/icon_eu/icon_d2, ukmo_seamless/ukmo_global_deterministic_10km/ukmo_uk_deterministic_2km, meteofrance_seamless (arpege/arome), jma_seamless (gsm/msm), cma_grapes_global, kma_seamless (gdps/ldps), bom_access_global, knmi/dmi harmonie, metno_nordic. GEM is requested for Toronto only; NCEP CONUS models for the US only. ECMWF IFS, AIFS, AIGFS and GraphCast are requested for **temperature_2m only**. No other field is requested per model outside the US `/v1/gfs` call and the Toronto `/v1/gem` call.

**Ensembles not requested** (FC-2): ecmwf_ifs025 ENS (51), ecmwf_aifs025 ENS, icon_seamless_eps / icon_global_eps (40), gem_global_ensemble (21), ukmo global/uk ensembles, bom_access_global_ensemble, gfs025 ensemble. GEFS is requested for temperature_2m only, with no members of any other field.

**Metadata not requested** (FC-1): `/data/<model>/static/meta.json` (run init and availability time). No run identity exists anywhere in the stored Open-Meteo evidence.

## 3. Implications for FC-3 / FC-11

**FC-11** can extract, from the market-local blobs and manifests (not `forecast_payload_cas`):
- (1) best_match: 21 fields × 48 h;
- (3) 4 global-model T2m columns;
- (4) US 4-model × 18 fields;
- (5) GEFS control + 30 members, T2m;
- (6) Toronto GEM 3 models × 11 fields;
- (2) AQ, 6 fields.

The join key is the manifest row (`payload_hash`/`payload_ref`, `fetched_at`, `cache_status`). `fresh_cache` rows reuse an earlier fetch. Use `fetched_at`, not `captured_at`, as first-seen, and dedup by hash. `run_init` must be null or `blend_unresolved` for every row because nothing stores it.

**FC-3** should shadow only what is not served:
- per-model **non-T2m** fields for IFS/AIFS/AIGFS/GraphCast;
- ICON, UKMO, MF, JMA, CMA and KMA, which are absent entirely;
- per-model members for anything other than GEFS T2m;
- `daily` Tmax/Tmin and `minutely_15` T2m;
- the station-elevation variant.

Do **not** re-fetch the best_match 21 fields, the 4-model global T2m, the US NCEP 4-model set, GEFS T2m, or Toronto GEM. Those are already kept, so a shadow would duplicate bytes and Open-Meteo quota.

**Flags**
- (a) `fetch_global_ensemble` labels unsuffixed `temperature_2m` as the "ensemble mean" (`:2208-2213, :2260`) and uses it for `day_max`. Per the Open-Meteo ensemble docs, the unsuffixed column is the **control member**, not the mean. This needs confirmation against the docs. If it holds, the extractor must label it `member00`/control.
- (b) Raw blobs are stored per event folder, so the same location fetched for two open target dates is stored twice (est.). That is a CAS-sharing opportunity, not a correctness issue.
