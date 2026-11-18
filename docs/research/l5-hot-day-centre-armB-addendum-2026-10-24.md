# L5 hot-day centre lever: arm B addendum (2026-10-24)

**Status:** frozen addendum to [the arm A pre-registration](l5-hot-day-centre-preregistration-2026-10-24.md)
(sha256 `53fd0bc581bcbe911144eb3d7401fdee579b57a744195838d24010c0e6ef0b5b`, unchanged). Its own sha256 is in the
commit that adds it and in the lane report; committed before any arm B candidate was scored and before any
arm A result was read. Development evidence only.

## Corpus (master direction 2; id sent by the coordinator)

Lane L1's full-year PIT union `621bcd8ea82ceed397bcfbdfae1c80664d1cb73adba3e71b240fae34db529cdc`: Jan-Jul
`3a7034d2…`, `672a1f57…`, `ece9d1c2…`; Aug-Sep `b455bd53…`; Oct-Dec `cd0ba2bb…`, `23ac87fa…`, `74807fbe…`.
Read by date as `weather.calibration.r0_full_year.SeasonCorpusUnion` does (each date planned by exactly one
corpus, fail closed on overlap; each `forecast_daily.jsonl` sha256 checked against its manifest) by
`tools/research/morning_loss/corpus_pairs.py`, which **reproduces the union id exactly**. Rows: cutoff 07,
`daily_high`, `gfs_seamless`, lead 1 day; 2021-03-25..2025-12-30, 1,715-1,718 dates per US market. Labels: the
station's WU daily summary `max_temp_bucket_native`, dates <= 2025-12-31.

## What arm B can and cannot test

The corpus holds one forecast field (the Open-Meteo Previous Runs `gfs_seamless` day-1 high); NBM v2, the NWS
grid, HRRR and `forecast_high` have no 2021-25 point-in-time history. So arm A's two forms cannot be refitted
on it as written. Arm B instead tests the coverage question with the one regressor that exists in both the
corpus and point in time at serve: on the dev window, the identical product (same model, same
`temperature_2m_previous_day1`, max over 24 local hours, issued before the day starts) from lane G's
`day1_highs.parquet` (sha256 `62d68e3c…`).

## Candidates (each: MG-1 sigma, floor and availability; MG-1 outside 07-12 or when the regressor is missing)

- **B1 `l5d_corpus_linear_fullyear`:** per market y = a_m + c_m · gfs_d1, OLS on all 2021-25 corpus pairs
  (full year). No dev-window parameter, so every fold is out of sample.
- **B2 `l5e_corpus_half_fullyear`:** mu = (v2_mean + B1) / 2, fixed 50/50.
- **Sensitivity, reported only, not decided: `l5f_corpus_linear_augsep`:** B1 fitted on Aug-Sep 2021-25 pairs
  only. B1 minus this contrasts full-year with in-season coverage for the same form.

Code: `src/weather/reporting/scorecards/free_source_candidates/l5_corpus.py` and the three `l5d/l5e/l5f`
candidate files.

## Decision

The arm A rule unchanged: control MG-1; headline 07-12 pooled `ALL`; KEEP iff crossed candidate − served and
candidate − MG-1 both exclude zero below; LEAD iff not KEEP and the date-clustered candidate − MG-1 interval
excludes zero below; otherwise KILL. Two decided rules in arm B (B1, B2), judged alone; subsets as in arm A.
