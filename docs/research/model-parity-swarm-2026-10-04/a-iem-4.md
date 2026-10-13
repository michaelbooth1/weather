# A-IEM-4 - 1-minute ASOS temperature (truth/label only) - COMPLETE (partial coverage by archive)

Status: COMPLETE (fetch finished 01:01 local, well before the 04:30 freeze). All numbers are development.
**NOT POINT IN TIME** - IEM/NCEI 1-minute ASOS (18-36 h+ delay, QC/back-filled). Truth/label use only; never a
candidate input (DESIGN hard rule 1). MANIFEST.json says `point_in_time: false`.

## What was fetched
- Endpoint: `https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py?station={iem_id}&vars=tmpf&sts=..Z&ets=..Z&sample=1min&what=download&tz=UTC&delim=comma&gis=no`
- Window: local days 2026-07-25..2026-09-29 per station tz (UTC request = local midnight 07-25 .. local midnight 09-30,
  split at UTC month starts). 33 requests, sequential, single connection, >= 2 s spacing; no 429/503 seen.
  No data for local dates >= 2026-09-30 was kept (the build filters on local date <= 09-29).
- Output: `C:\swarm\data\iem\onemin\` - `raw\*.csv.gz` (33 chunks, as served), `<ICAO>.parquet` (icao, valid_utc,
  tmpf, local_date), `coverage_station_day.csv` (minutes_valid, coverage_frac, hours_with_data,
  minutes_valid_10_18_local, max_gap_min, tmax_1min_f), `MANIFEST.json` (files, bytes, sha256, URL pattern, window,
  availability basis, coverage), `fetch.log`.
- Code: `C:\pt\swarm\tools\research\model_parity\a-iem-4_onemin_fetch.py`, `a-iem-4_onemin_build.py`.
  Fetch process PID 55280 has exited; nothing is left running.

## Coverage (67 local days per station)
| ICAO | days any | days >= 90% of minutes | days with 10-18 local >= 95% | minute coverage |
|---|---|---|---|---|
| KATL | 60 | 37 | 51 | 78.3% |
| KAUS | 60 | 18 | 25 | 59.8% |
| KBKF | 0 | 0 | 0 | 0% (no 1-minute archive at IEM; military station; 2024 probe also empty) |
| KDAL | 64 | 58 | 61 | 91.3% |
| KHOU | 66 | 53 | 56 | 90.1% |
| KLAX | 58 | 14 | 23 | 58.0% |
| KLGA | 61 | 13 | 41 | 61.3% |
| KMIA | 59 | 16 | 34 | 67.6% |
| KORD | 59 | 29 | 39 | 71.1% |
| KSEA | 63 | 24 | 40 | 71.3% |
| KSFO | 63 | 27 | 37 | 75.3% |
Gaps are missing rows in the IEM archive. Before using `tmax_1min_f` as truth, gate on
`minutes_valid_10_18_local` (afternoon completeness) and `max_gap_min`.

## Sanity check (development)
On days with afternoon (10-18 local) coverage >= 95%, the 1-minute daily max is compared with the non-COR METAR
daily max (routine+SPECI) from `C:\swarm\data\iem\metar`. The 1-minute max is >= the METAR max on 406/407 station-days;
the mean difference is +0.86..+1.74 F per station. That is the expected direction, because the true max includes peaks
between reports. One KORD day has the 1-minute max below the METAR max. For F2: the 1-minute max is a "true max"
truth series, not the venue's settlement value.
