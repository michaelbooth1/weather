# A-SingleRuns: Open-Meteo Single Runs acquisition (development)

**Status: COMPLETE.** All 469 planned run requests are done (67 run dates 2026-07-25..09-29 x 7 run hours). Every HTTP status was 200, there were no 429s, and the budget was respected. Two HRRR runs are empty at the source (null in Open-Meteo's archive). The fetcher has terminated. MANIFEST.json is final.

## What was fetched
- Endpoint: https://single-runs-api.open-meteo.com/v1/forecast (no key), `&run=YYYY-MM-DDTHH:00`, `forecast_hours=48`, `timezone=GMT`, `temperature_unit=fahrenheit`. Each request carried all 11 stations and every model initialised at that run hour.
- HRRR (`ncep_hrrr_conus`): 06/09/12/15/18/21Z. 06/12/18Z reach lead 47 h. 09/15/21Z are 18 h runs (lead 0..18).
- NBM (`ncep_nbm_conus`): 00/06/12/18Z, leads 1..47 (lead 0 null).
- ECMWF IFS (`ecmwf_ifs`): 00/12Z, leads 0..47.
- Variables: temperature_2m (degF), cloud_cover (%), precipitation (mm, preceding hour), wind_speed_10m (km/h). NBM and IFS also return the three extra variables because they share the request.
- Output: `C:\swarm\data\singleruns\` contains raw/<YYYYMMDDHH>.json (468 files), `singleruns_long.parquet` (423,984 rows: station x model x run x valid hour, wide over variables, with availability columns), `requests.jsonl` (one line per HTTP request: run, request_utc, status, sha256, weight, URL), `meta_samples.jsonl` and `MANIFEST.json` (sha256 AD7483F4...B801 at finalisation).

## Coverage
- Runs with data per station, the same for all 11 stations: HRRR 400/402, NBM 268/268, IFS 134/134.
- HRRR gaps, null at the source: **2026-08-10 18Z** (retried once at 01:46 local, still all null; recorded in requests.jsonl with an error_body) and **2026-08-20 15Z** (not retried).
- The MANIFEST has coverage per station x LOCAL target day x model (`coverage_station_localday_model`, 737 station-days per model, local dates 07-25..09-29 in the station tz). Mean runs touching a local day: HRRR 13.7 (min 6), NBM 11.5 (min 5), IFS 5.9 (min 3). Every station-day has all 24 local hours covered by some run, except 3 HRRR station-days on 2026-07-25 (KATL/KLGA/KMIA, 22 h, edge of window). The MANIFEST also keeps coverage per station x run-date x model.
- No identical consecutive runs were found (no duplicated or stale run served under a new run label).
- Runs issued on 09-29 contain valid times up to 10-01, which rule 5 allows. Scorers must still guard target date <= 09-29.

## Point in time (rule 1)
Single Runs exposes no per-run publication timestamp. Availability is therefore the run time plus a stated delay, and the parquet carries two columns:
- `available_utc_design` = run +3 h (HRRR) / +6 h (NBM, IFS). These are the DESIGN section 3 values.
- `available_utc_conservative` = run +3 h (HRRR) / +6 h (NBM) / **+8 h (IFS)**. **Recommended.** Evidence: Open-Meteo meta.json sampled live tonight shows HRRR 91-95 min, NBM 57-60 min and IFS ~367 min (6.1 h) from init to availability. AWS LastModified (PREFLIGHT section 3) shows ECMWF 00z oper landing at ~+7.6 h. So the design's +6 h for IFS is **not conservative**. HRRR +3 h and NBM +6 h are conservative by a wide margin.
- Caveat: the archived Single-Runs values may differ from what the live API served at the time, because Open-Meteo reprocessing cannot be ruled out. Tonight's meta.json samples are not a measurement of August-September ingestion.
- Refuters re-running at +2 h only need to shift these columns. No re-fetch is needed.

## Budget and rate
- requests.jsonl shows 470 HTTP requests, all status 200 (469 planned runs plus 1 retry), for 5,317.4 weighted calls. The weighting is locations x max(1, variables x models / 10), a conservative reading of the free-tier rule. Adding the prior P0/probe allowance of about 70 gives a **total of about 5,387 across both attempts** (budget 9,000).
- Rate: one request every ~10 s, about 66 weighted calls/min (limit 300/min). No 429s.

## Restart handling
The first attempt's fetcher (PID 1544, child 55668, C:\swarm\venv, started 00:26 local) was found healthy at 01:23: it was writing every ~10 s, about 131 runs remained and there were no errors. I adopted it and did not restart it. It skips runs that already have a raw file, so nothing was re-fetched. It exited on its own at 01:45 with "ALL DONE". I confirmed that no fetcher process remains.

## Fix made during the restart
`a-singleruns_tidy.py` dropped single-model files (HRRR 09/15/21Z). Open-Meteo returns unsuffixed keys for those files, so they were never attributed to a model. I fixed this by attributing the model from the request log, with an assert. I also added coverage per station x local day.

## Code
- C:\pt\swarm\tools\research\model_parity\a-singleruns_fetch.py (fetcher, resumable, guards for 429/STOP/deadline/budget)
- C:\pt\swarm\tools\research\model_parity\a-singleruns_tidy.py (parquet + MANIFEST)

Nothing here was scored, so there is no HARNESS_SHA256. All values are development.
