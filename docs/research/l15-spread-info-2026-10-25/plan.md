# L15 plan: R-S, spread information at 07-12 (13-16 secondary)

Lane L15, workstation DESKTOP-RFCD2GH (not the capture host), 2026-10-25. Master ruling R9: R-I's kill covers
FITTED temperature/scale maps only; day-specific predictors of forecast uncertainty are a new family that needs its
own pre-registration and the full ladder. Hard limits: no global sharpening, the floor is never weakened, EF §1,
§1c, §1g and §2 stand. Nothing dated after 2026-09-29 is read. This file reads NO outcome: every number below is
an input (predictor) count or a byte size.

## What the arm lacks today (the mechanism)

- P3d_N_fix's per-row scale is an HGB on |inner-LOYO error| with inputs: levels minus the anchor, the floor gap g,
  normal, bias, lat/lon/elev, day of year (`pooled_residual_model.fit_pooled`). **No forecast-uncertainty input.**
- L6 and MG-1 use sigma = max(v2_stddev, 1), i.e. NBM's own TXNSD, uncalibrated
  (`free_source_candidates/l6_stack.py`, `mg1.py`). So the one arm that beats P3d_N_fix at 07-12 already consumes
  a day-specific spread input that P3d_N_fix ignores. R-S asks whether that input, added to P3d_N_fix's spread
  as a monotone, mean-zero modulation, carries information the HGB scale lacks.

## Predictor inventory (point-in-time, free, 2021-25 training AND 2026 dev 07-31..09-29)

| # | Predictor | Training 2021-25 (Aug-Sep) | Dev 2026 | PIT rule | Cost | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | **NBP 07Z TXNSD** (NBM standard deviation of the daily max, whole °F) | L9 corpus `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl` (corpus id 1ae4bf52…; 7,425 available rows Aug-Dec, 3,300 Aug-Sep, 07Z only, `sd` present on every available row; values 1-8). Versions 4.0 (2021-22, median 3), 4.1/4.2/4.3 (2023-25, median 2). | Captured `v2_stddev` in `C:\swarm\v3layout\inputs_snapshots.parquet` (110,807 snapshots, values 1-6, median 2, 25% at 1). 97.2% equal to the 2026 07Z NBP corpus `C:\t\l3\analogue\nbm2026\corpus\nbm_pit_corpus_rows.jsonl` (sha 85746b7a…, 682 rows, 07-30..09-29, all v5.0). | Training: the same row `nbm_at_cutoff` selects for the mean (S3 LastModified <= cutoff instant). Dev: the captured value, under the same `usable_v2_mean` filter (v2_available_at <= captured_at_utc). Prior-day values (for a trailing baseline) are strictly earlier bulletins. | **Zero** (on disk; same rows and filters as the anchor) | **Run first (R-S).** Parity is exact by construction (the anchor's own bulletin). Risk: NBM version drift (4.0 -> 5.0 changes the sd level), handled by a trailing same-market anomaly (rule). |
| P2 | NBP 07Z percentile width (p90 - p10) | Same L9 corpus (`p10`, `p90` fields) | Not captured in the v3 layout (v2 has mean/stddev only); in the 2026 NBP corpus | As P1 | Zero for training; dev from the corpus (not the captured serve value) | Same NBM family as P1 and nearly collinear with it; not a separate rung. |
| P3 | NBS XND (TXN sd at the freshest hourly cycle) and NBS/NBH TSD | L12 `C:\t\l12\nbs_nbh\` running: 2021-22 complete, 2023 through ~09-06 at 20:10 local (10,950 / 24,480 objects, ETA ~6 h). | `C:\swarm\data\nbs\nbs_tidy.parquet` 2026-07-25..09-29, all 24 cycles, field `XND`/`TSD` present, v5.0, `available_utc` per cycle. `C:\t\l12\nbs_nbh_2026dev\` does not exist yet. | S3 LastModified <= cutoff (L12 manifest; swarm `available_utc`). | Wait for L12 (~6 h) | Same NBM family (the blend's own uncertainty at a fresher cycle). Covered by P1's kill if P1 fails (rule). |
| P4 | **GEFS member spread** (31 members: gec00 + gep01-30, TMAX 2 m 6-h max, 00Z cycle f18/f24/f30) | Not on disk. `noaa-gefs-pds` (anonymous HTTPS, no key) holds GEFS v12 per-member `pgrb2ap5` (0.5°) and `pgrb2sp25` (0.25°) with `.idx`; listed 2023-08-15 00Z: 81 grib files per member, ~17 MB each; TMAX 2 m message ~140 KB at 0.5°, ~430 KB at 0.25°. | Same bucket, 2026-08-15 objects present (HTTP 200). | 00Z objects LastModified ~03:47-05:00Z, before every 07:00-local cutoff (earliest 11:00Z). Use max(grib, idx) LastModified as in L13. | ~93 messages/day x ~140 KB = ~13 MB/day; Aug-Sep 2021-25 + 2026-07-30..09-29 = ~366 days = **~4.8 GB, ~68k requests (idx + range), ~3-4 h serial**. Decoder: L13's pure-numpy GRIB2 decoder needs template 3.0 (lat-lon) added; complex packing 5.3 is already there. | **Next predictor** (independent of NBM's own sd; F6 says only the control run was ever scored). |
| P5 | Multi-source dispersion (NBM vs HRRR vs NWS vs IFS) | No NWS gridpoint history; PIT corpora hold `gfs_seamless` lead 1 only (b455bd53…: 46,970 rows, one model, one lead) so no model spread; L13 HRRR is valid hours 13-16 only (TMP, TCDC), 2021-25, 36.6 GB, 620/765 days. | 2026 only: `C:\swarm\data\singleruns` (Open-Meteo HRRR/NBM/IFS runs 07-25..09-29), `C:\swarm\data\ecmwf` (IFS 00/12Z). | Per-source availability rules exist in those manifests. | High: no training history for most pairs; a 07-12 HRRR day-max needs another fetch. Dev-fit only. | Not rankable on LOYO; defer. |
| P6 | Observed overnight behaviour (overnight low, dewpoint depression, obs-minus-forecast at cutoff) | Training records carry high_so_far / current_temp; overnight low and dewpoint in L9's corpus. | Captured METAR in replay. | Observed at or before cutoff. | Low | Obs-minus-anchor already feeds the HGB scale (LEVEL_COLUMNS - mu0, g, floor gap), so most of it is absorbed by construction; overnight low / dewpoint failed as centre columns on Aug-Sep (R-G, R-J, EF §10ac). Lowest prior. |
| P7 | Run-to-run (lagged) dispersion | Not available: PIT corpora lead 1 only; L9 NBP 07Z only (01Z would need the inventory row-2 fetch). | Captured v2 (one cycle). | — | Fetch | EF §1e blind null; needs a 01Z NBP pull first. |

## Order

1. **R-S on P1** (this rung; rule `C:\t\l15\rule_rs.md`, sha recorded before any row is joined to an outcome).
2. If R-S passes LOYO and dev: P3 as a freshness variant only after L12 lands (same family, no new rung needed for
   the kill). If R-S fails: the NBM-published-spread family (P1-P3) is closed.
3. Either way, the next independent predictor is **P4 GEFS member spread** (fetch plan + its own rule).
