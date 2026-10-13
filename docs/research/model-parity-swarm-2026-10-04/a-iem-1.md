# A-IEM-1 report: METAR/SPECI acquisition (IEM asos.py)

**Status: COMPLETE** (development data acquisition; no scoring done). Finished 00:33 local 2026-10-04, ahead of the 02:15 deadline.

## What was acquired
- 11 stations (KATL KAUS KBKF KDAL KHOU KLAX KLGA KMIA KORD KSEA KSFO), local dates 2024-05-01..2026-09-29.
- Priority window 2026-07-25..09-29 fetched first (00:23-00:24), then history newest-first in quarterly chunks.
- 220 requests (station x report type x chunk), one connection, sequential, >= 2 s spacing (stricter than 1 req/s, per PREFLIGHT §5). No 429/503. One dropped connection at 00:26:07 recovered after a 60 s backoff.
- Raw CSV chunks are kept gzipped under `C:\swarm\data\iem\raw_metar\` (first line holds the request URL and retrieval time). Tidy parquet is at `C:\swarm\data\iem\metar\<ICAO>.parquet`. MANIFEST: `C:\swarm\data\iem\metar\MANIFEST.json` (231 files with bytes and sha256, URL pattern, window, availability basis, per-station-day coverage `[routine_rows, speci_rows, rows_with_tgroup]`). About 28 MB in total.
- Code: `C:\pt\swarm\tools\research\model_parity\a-iem-1_metar_acquire.py` (fetch, resumable) and `a-iem-1_metar_tidy.py` (parse and manifest).

## Columns
station (ICAO), iem_id, valid_utc, **available_utc = valid_utc + 10 min**, local_time, local_date (station tz), report_type (`routine` = IEM report_type 3, `speci` = 4; requested separately because the text has no METAR/SPECI prefix), **is_cor** (COR token after the time group or in the body), tmpf (IEM), **tgroup_c** (T-group tenths in deg C, parsed from RMK), tgroup_f (unrounded), main_temp_c (body integer), dwpf, sknt, drct, gust, skyc1-4, skyl1-4, metar (raw), maintenance_flag (`$`), source_file.

## Availability basis (rule 1)
A row enters a candidate at snapshot t only if `available_utc <= t` (METAR/SPECI valid time + 10 min) **and** `is_cor == False`. tmpf is IEM's stored value, which can be derived or revised. Use the raw text, tgroup_c or main_temp_c as primary values. Where a T-group is present, tmpf == round(tgroup_f) on every row checked (KMIA window).

## Coverage
- Window 2026-07-25..09-29: 67/67 days with >= 20 routine rows for all 11 stations (lowest day: 22 routine rows). T-group present on 92-99.5% of rows (KBKF lowest, 0.921).
- Whole span (882 days): every station has >= 881 days with >= 20 routine rows, except KBKF (852/882; 30 thin days, e.g. 2024-12-18, 2025-02-19).
- COR rows per station: 89 (KSEA) to 1,546 (KMIA). Caveat: IEM appears to keep one row per valid time, so a COR can replace the original report. Excluding COR can therefore leave an hourly gap for that hour rather than falling back to the uncorrected original. Hunters should treat it as a missing observation.

## Date guard
The upper bound is the local midnight that ends 2026-09-29 for each station. For LA stations this runs to 2026-09-30 06:53Z, which is still local date 09-29. Rows with local_date >= 2026-09-30 are dropped, and the code asserts this (0 remain). No market or settlement records were touched.

## Processes
Fetch PID 45864 exited normally after the last request. Nothing is left running.
