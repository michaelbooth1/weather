# A-HRRR-AWS report (development)

**Verdict: COMPLETE. Single-Runs HRRR matches AWS HRRR at 10 of 11 stations (|diff| <= 0.29 F everywhere, MAE 0.03-0.19 F). At KSFO it does NOT: Open-Meteo serves an adjacent HRRR grid point (37.626, -122.400, about 2.8 km west of the station, over land) instead of the nearest one, giving +4.29 F bias, MAE 5.18 F and up to +25.5 F at a single hour. Against KSFO METAR, the Open-Meteo point verifies better than the nearest point (MAE 2.42 F vs 4.20 F; nearest-point bias -3.9 F). This is a grid-point choice and not a data defect. The Single-Runs HRRR availability rule (run + 3 h) is conservative against AWS LastModified for every object (latest f00-f12 object is +92 min).**

Agent a-hrrr-aws, 2026-10-04, from 01:47 to 01:55 local. I scored no candidates, used no harness and registered no rule. Every number here is development. A tool guard blocked writing report.md, so the full report is carried here in result.json "report_md".

## What was fetched
- Source: noaa-hrrr-bdp-pds over anonymous HTTPS. For each object I listed it with ListObjectsV2 to get its LastModified, read the .idx, and did a Range GET of the "TMP:2 m above ground" message only. Each response was checked for HTTP 206, the GRIB header and the 7777 trailer.
- Window: runs 2026-07-25..09-29, cycles 12Z and 18Z, f00-f12. That is 1,742 messages, and all 1,742 returned OK, so coverage is complete: 134 runs and 26 messages per station-day for every station and day.
- Transfer: 2.193 GB in total (cap 3 GB), at about 1.26 MB per message. The fetch took 84 s with 6 threads. No raw GRIB was staged on disk: values were decoded in memory with eccodes codes_new_from_message. Lat/lon came from one cfgrib decode (indexpath '').
- Each message was checked with asserts on shortName 2t, level 2, dataDate, dataTime, endStep and grid size.
- Grid point: the haversine-nearest HRRR 3 km point to each station in stations.json. All are <= 1.76 km from the station (nearest_points.json).
- Outputs, all in C:\swarm\data\hrrr_aws\:
  - hrrr_aws_tmp2m.parquet: 19,162 rows with station, run_utc, fh, valid_utc, tmp2m_k, tmp2m_f, grid point, available_utc (= the grib object's LastModified) and idx_last_modified.
  - parts\*.jsonl: per-object URL, Range, idx line, message sha256, and grib/idx LastModified.
  - MANIFEST.json.
- Background PID 9468 exited normally. No processes are left running.

## Availability (AWS LastModified minus cycle, minutes)
- 12Z: f00 has a median of 51.6 min (max 61.5) and f12 a median of 67.3 min (max 76.7).
- 18Z: f00 has a median of 52.3 min (max 83.3) and f12 a median of 67.2 min (max 92.4).
- The run is complete (the latest of f00-f12) at a median of 68.2 min, a p95 of 76.8 min and a max of 92.4 min after the cycle.
- f00 was written after f01 in 16 of 134 runs, and after f12 in 2 runs. Use each object's own LastModified, never a formula in fh.
- No object landed later than 3 h after its cycle. Single-Runs available_utc_design (run + 3 h) is never earlier than the AWS LastModified (100% of 19,019 matched rows). The rule is conservative by about 1.5-2 h. Open-Meteo's own ingest lag is not measured here.

## Single-Runs vs AWS (Single-Runs minus AWS, degF; 19,019 matched rows; 143 Single-Runs nulls)
Overall, the bias is +0.398, MAE 0.539, RMSE 2.007 and max |d| 25.5. 91.6% of rows are within 0.5 F. Almost all of the error is KSFO.

| station | bias | MAE | max abs | share <= 0.5 F |
|---|---|---|---|---|
| KATL | -0.084 | 0.084 | 0.175 | 1.00 |
| KAUS | 0.086 | 0.086 | 0.174 | 1.00 |
| KBKF | -0.194 | 0.194 | 0.284 | 1.00 |
| KDAL | -0.025 | 0.038 | 0.114 | 1.00 |
| KHOU | 0.056 | 0.058 | 0.144 | 1.00 |
| KLAX | 0.106 | 0.106 | 0.194 | 1.00 |
| KLGA | 0.035 | 0.043 | 0.124 | 1.00 |
| KMIA | 0.075 | 0.075 | 0.164 | 1.00 |
| KORD | 0.015 | 0.033 | 0.104 | 1.00 |
| KSEA | 0.015 | 0.034 | 0.104 | 1.00 |
| KSFO | +4.288 | 5.182 | 25.52 | 0.08 |

By lead, pooled over all stations (KSFO drives the shape):

| fh | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bias F | .201 | .249 | .304 | .416 | .498 | .539 | .571 | .578 | .520 | .436 | .365 | .284 | .207 |
| MAE F | .515 | .554 | .595 | .523 | .558 | .601 | .632 | .639 | .586 | .525 | .479 | .424 | .382 |

The bias peaks at f05-f08, which is local afternoon at SFO for both cycles. That is the hours when the land point heats and the bay-shore point does not.

Run max over f01-f12 (a hrrr_high-like quantity), pooled: bias +0.76 F, MAE 0.82 F and max 17.5 F (all KSFO). Bias by cycle is 12Z +0.38 and 18Z +0.41. By month: Jul +0.45, Aug +0.47, Sep +0.31.

The residual 0.03-0.19 F at the other stations has a constant sign per station. It is consistent with Open-Meteo's own point or interpolation (its grid points sit about 0.0006 deg from mine) plus K->F rounding. It does not matter at the scale of a band.

## KSFO grid point (verified)
- In AWS HRRR, the nearest point to SFO is (37.633, -122.367): 72.2 F on 09-09 18Z f04. Open-Meteo's point (37.626, -122.400) is the adjacent column to the west: 97.7 F, which matches Single-Runs' 97.7 exactly.
- So Open-Meteo is not reading different HRRR data. It picks a different cell, plausibly through land-sea or elevation-aware selection.
- Against KSFO METAR (truth use only, matched within 10 min, n = 1,728 hours):
  - The AWS nearest point has bias -3.9 F and MAE 4.20 F.
  - The Single-Runs point has bias +0.39 F and MAE 2.42 F.

## Implications for hunters (T8/T9/T20)
- At 10 stations, Single-Runs HRRR can be treated as identical to the operational HRRR. The +3 h availability rule is safe: AWS shows +52..92 min. A refuter re-running at +2 h stays safe, because the max is 92 min, which is below 2 h.
- At KSFO, any result from Single-Runs HRRR depends on Open-Meteo's grid-point choice. A candidate built from raw nearest-point AWS HRRR would be about 4 F colder in the afternoon.
- Production's hrrr_high comes from Open-Meteo, presumably with the same point selection. This is not verified here, and it is a T20 item. If so, it is the better-verifying point for this table.
- Any KSFO-specific HRRR lead should be reported with and without KSFO.

## Boundaries
- I did not run git and used no credentials.
- All dates are <= 2026-09-29. METAR was used only as truth for the grid-point diagnostic.
- I did not open any market or settlement data.
- Disk use is 6.5 MB.
- Code:
  - C:\pt\swarm\tools\research\model_parity\a-hrrr-aws_fetch.py
  - C:\pt\swarm\tools\research\model_parity\a-hrrr-aws_tidy_compare.py
- Full tables: C:\swarm\out\a-hrrr-aws\compare_tables.md and compare_summary.json.
