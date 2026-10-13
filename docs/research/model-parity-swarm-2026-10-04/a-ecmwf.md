# A-ECMWF: acquisition report (model-parity swarm v2, development)

**Status: COMPLETE.** All 134 ECMWF IFS oper runs (00Z and 12Z, run dates 2026-07-25..2026-09-29) were fetched. Every run has every step (0-48 h every 3 h) for `2t` and `mx2t3`. No run failed and none is missing. I did not score anything (acquisition only), so there is no HARNESS_SHA256.

## What is where
- `C:\swarm\data\ecmwf\MANIFEST.json`: source, URL pattern, window, availability basis, Last-Modified lag stats, undersampling statement, file sha256s, and coverage per station x local day.
- `C:\swarm\data\ecmwf\values.parquet` (and `values.jsonl`): 50,116 rows = 134 runs x 34 messages x 11 stations. 48,642 rows are usable.
  - Keys: one row per (date, cycle, step, param, station).
  - Values: nearest grid-point K and F, and a bilinear K beside them.
  - Times: `valid_utc`, `window_start_utc`, plus `available_utc_assumed` (+8 h), `available_utc_measured` (S3 Last-Modified) and `available_utc_conservative` (the later of the two).
  - Provenance: message sha256.
- `runs.jsonl`: one line per run, with the byte offset, length, sha256, stepRange and Last-Modified of each message.
- `acquire.log`: the run log. There were 17 retries, all HTTP 503 SlowDown from the bucket. Every retry succeeded.
- Code:
  - Workstation copies: `C:\swarm\out\a-ecmwf\a_ecmwf_acquire.py` and `a_ecmwf_finalize.py`.
  - Repo copies: `C:\pt\swarm\tools\research\model_parity\a_ecmwf_acquire.py` and `a_ecmwf_finalize.py`.

## Method
- Source: `https://ecmwf-forecasts.s3.amazonaws.com/YYYYMMDD/HHz/ifs/0p25/oper/YYYYMMDDHH0000-<step>h-oper-fc.{index,grib2}`, fetched anonymously over HTTPS.
  - There is no `scda` directory in this window; 00z and 12z live under `oper`.
- Only `.index` byte ranges were used, never whole files. Each Range GET was accepted only if all of these held: HTTP 206, the body starts with `GRIB`, and the body length equals the index length. Failed GETs were retried with backoff of 5, 10, 20 s and so on.
- Transfer: 6,851 requests and 2.96 GB, inside the 4.5 GB budget. The fetch ran from 00:24 to 00:37 local with 2 workers.
- Raw GRIB was never written to disk. Each message was decoded in memory with eccodes and its sha256 recorded.
- Decode checks:
  - shortName, dataDate and dataTime are asserted per message.
  - The grid (721x1440, starting at lat 90 / lon 180, i.e. -180..179.75) is asserted per message.
  - On the first message of every run, the nearest-point index is checked against eccodes `codes_grib_find_nearest`.
- Nearest grid points:

  | Station | Grid point |
  | --- | --- |
  | KATL | 33.75, -84.50 |
  | KAUS | 30.25, -97.75 |
  | KBKF | 39.75, -104.75 |
  | KDAL | 32.75, -96.75 |
  | KHOU | 29.75, -95.25 |
  | KLAX | 34.00, -118.50 |
  | KLGA | 40.75, -74.00 |
  | KMIA | 25.75, -80.25 |
  | KORD | 42.00, -88.00 |
  | KSEA | 47.50, -122.25 |
  | KSFO | 37.50, -122.25 |

  The 0.25-degree grid is coarse. KLAX, KSFO and KMIA are coastal: their grid cells mix land and sea, which can damp the daily maximum.

## Availability (point in time)
- Measured: S3 Last-Modified on both the `.index` and the `.grib2` lands 7.567-7.571 h after the run time, for every message of every run. Both cycles show the same lag.
- Assumed: the design's +8 h. That is later than the measured time in 100% of rows (0 rows have measured later than assumed), so +8 h is conservative.
- Rule for candidates: use `available_utc_conservative <= t`. The 00Z run becomes usable at 08Z (04 EDT / 01 PDT). The 12Z run becomes usable at 20Z (16 EDT / 13 PDT).
  - So the 12Z run is not available for most of a same-day eastern-market afternoon.
  - For a T+0 target day, the freshest usable run before 20Z is the 00Z run of that day.

## Undersampling and quirks
- **3-hourly undersampling.** `2t` is instantaneous every 3 h (00, 03, ..., 21Z). The maximum of those samples under-samples the hourly-row daily max and is biased low, worst when the local peak falls between synoptic hours.
- **`mx2t3` behaviour.** It is the 3-hour window maximum. It closes the gaps but is a model-internal continuous maximum, not an hourly-row maximum, so it may exceed an hourly-row settlement max.
  - Measured: the median of `mx2t3` minus `2t` at the same window end is +0.6 K.
  - It can also be slightly below `2t` at the window end (about 25% of rows are below 0; observed at KATL 2026-07-25 00z step 18 by 0.05 K).
- Neither `2t` nor `mx2t3` matches the hourly-row settlement shape exactly.
- **Placeholder trap.** The step-0 file carries an `mx2t3` message with stepRange "0-3" whose values are all 0 K. These 1,474 rows are flagged `usable=False` and must never be used.

## Coverage
Every station x local target day 2026-08-01..09-29 is covered by several runs, each spanning all 3-hourly valid times of the day; the per-day counts are in the manifest. Hunters must still apply the +8 h availability per snapshot.

## Boundaries
- No credentials and no paid sources.
- No data dated on or after 2026-09-30 was read; the last run read is 2026-09-29 12Z. Its later valid times are allowed under rule 5.
- Git was not run.
- No processes are left running: the acquirer exited with code 0, and the monitors were stopped.
