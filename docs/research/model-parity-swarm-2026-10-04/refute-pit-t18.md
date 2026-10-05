# refute-pit-t18: PIT/leakage refuter for T18 (development)

**Verdict: NOT DISQUALIFIED in 00-16.** All numbers are development numbers, scored with HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.

- **00-16:** t18-r1 is still LEAD after every serve-time input is delayed by +1 h, under all four shift variants. At +2 h it is LEAD in 3 of 4 variants and WEAK in the harshest one.
- **What drives it:** the 00-16 increment over the t3-r3 rung comes from NBM v2_mean. It does not shrink under delay: about -0.010, 10-11 of 11 markets, at +0, +1 h and +2 h.
- **17-23:** the LEAD versus served stands, but it is not T18's own result. Against the rung, T18 adds nothing in 17-23, and two refit variants turn harmful against the rung under delay. Credit the block to the rung / D-DEFECT family.
- **Leakage:** none found. No leakage-suspect group appeared in any of the 17 re-scores, and the rules 1-5 and 8 checks pass in code.

## 1. Reproduction
I re-ran the candidate at delay 0 with T18's frozen parameters (t18_run.json). It reproduces T18 exactly:

| Block | r1 − served (from stratum) | Class | Markets | r1 − t3-r3 rung |
| --- | --- | --- | --- | --- |
| 00-16 | -0.01395 [-0.0195, -0.0089] | LEAD | 11/11 | -0.0096 [-0.0129, -0.0061], 10/11 markets |
| 17-23 | -0.0218 | — | — | +0.0002 [-0.0014, +0.0021] |

The cached rise_table.parquet is identical (DataFrame.equals) to a fresh t3.remaining_rise_table rebuild, which uses history <= 2026-07-31.

## 2. Availability from primary sources

### v2_mean (the load-bearing source)
The extractor (guidance_extract.py, sha 23452a27, matching the manifest) sets v2_available_at to the earliest production-host response_received_at. Production fetches the bulletin from NOMADS, a public source (nbm_probabilistic_tmax.py:31). select_v2 uses a bulletin only if both available_at and issued_at are <= captured_at.

- **Basis:** every row uses response_received_at.
- **Cycles used:** 119 in total (07Z 97,260 rows; 01Z 13,522; 19Z 25).
- **S3 listing:** I listed noaa-nbm-grib2-pds anonymously for all 119 cycles (nbp_s3_lastmod.json).
  - S3 LastModified of blend_nbptx falls 61-77 min after issue (median 75).
  - Production receipt minus S3 LastModified: median +4.3 min, IQR +0.3 to +116 min. The 01Z cycle is polled at about 04:00Z.
- **Rows that used a bulletin before its S3 copy existed:** 864 of 110,807 (0.78%).
  - 828 come from 2026-09-24 01Z/07Z. S3 shows a late re-upload at 14:24Z and 15:40Z; production received the bulletins from NOMADS at 04:00Z and 08:13Z.
  - 16 come from 09-28 07Z (NOMADS receipt 10 min before S3).
  - The rest are 1-3 rows each, about 1 min early.
  - All of these are backed by a real public receipt, so this is not leakage. The +60 shift covers all of them except 09-24.

### hrrr_high
hrrr_fetched_at is production's own fetch time from Open-Meteo, which is a public receipt. Open-Meteo does not expose the run time (manifest note). Together with forecast_high, hrrr_high adds only -0.0005 [-0.0013, +0.0004] over v2_mean (NULL).

### forecast_high
forecast_high is the served forecast-ensemble high from production features_long at the snapshot (model_distribution.py:356).
- It is a weather feature, not a market input.
- It has no stamp of its own; its availability is the capture itself.
- Its coefficient is -0.27, and it adds no measurable increment.

### METAR rung
The rung takes METAR at IEM valid + 10 min. R-PIT-T3 measured the feed lag: about 93% of new maxima appear in production within 10 min. The shift runs cover the rest.

## 3. Shift re-runs (r-pit-t18_shift.py)
All numbers in this section are from-stratum, all-row, candidate − served.

Every serve-time input is delayed by D: the METAR rung (valid + 10 + D) and all three sources. The sources are delayed in one of two ways:
- **stale:** source values come from the latest snapshot of the same market-day captured <= t − D, with stamps asserted <= t − D.
- **impute:** a source is used only if its stamp + D <= t; otherwise it is set to mu_rr. forecast_high is never used in this form, which is T18's r1s form.

Each way is run twice: with parameters frozen, and refit on the before stratum under the same delay.

| D | Variant | 00-16 | Class | Before | 00-16 r1 − rung | 17-23 r1 − rung |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | as-is | -0.0140 [-0.0195, -0.0089] | LEAD | -0.0143 | -0.0096 [-0.0129, -0.0061] | +0.0002 [-0.0014, +0.0021] |
| +60 | stale, frozen | -0.0105 [-0.0158, -0.0060] | LEAD | -0.0099 | -0.0098 [-0.0132, -0.0063] | +0.0002 |
| +60 | stale, refit | -0.0113 [-0.0165, -0.0066] | LEAD | -0.0112 | -0.0106 [-0.0137, -0.0070] | +0.0019 [-0.0002, +0.0045] |
| +60 | impute, frozen | -0.0099 [-0.0151, -0.0053] | LEAD | -0.0096 | -0.0091 [-0.0121, -0.0059] | +0.0007 |
| +60 | impute, refit | -0.0103 [-0.0156, -0.0056] | LEAD | -0.0104 | -0.0096 [-0.0123, -0.0066] | +0.0016 [+0.0001, +0.0035] |
| +120 | stale, frozen | -0.0067 [-0.0120, -0.0019] | LEAD | -0.0052 | -0.0104 [-0.0134, -0.0070] | +0.0002 |
| +120 | stale, refit | -0.0080 [-0.0132, -0.0032] | LEAD | -0.0080 | -0.0116 [-0.0150, -0.0076] | +0.0037 [+0.0009, +0.0076] |
| +120 | impute, frozen | -0.0045 [-0.0099, +0.0004] | WEAK | -0.0035 | -0.0081 [-0.0108, -0.0051] | +0.0005 |
| +120 | impute, refit | -0.0062 [-0.0115, -0.0015] | LEAD | -0.0064 | -0.0098 [-0.0127, -0.0064] | +0.0032 [+0.0012, +0.0059] |

At +60 the 00-16 result held on 11/11 markets in the stale, frozen variant (10-11 of 11 for the paired rung increments).

### The rung on its own
t3-r3 − served in 00-16:

| D | Estimate | Class |
| --- | --- | --- |
| 0 | -0.0043 | WEAK |
| +60 | -0.0007 | WEAK |
| +120 | +0.0036 | NULL |

In 10-12 at +120, the rung is HARM (+0.0181).

### r1 by block under delay

| Block | +60 | +120 |
| --- | --- | --- |
| 00-05 | LEAD in every variant | LEAD (stale) / WEAK (impute) |
| 06-09 | LEAD in every variant | LEAD in every variant |
| 10-12 | LEAD in every variant | NULL or WEAK, inherited from the rung's METAR timing |
| 13-16 | LEAD in every variant | WEAK (frozen) / LEAD (refit) |
| 17-23 | LEAD in every variant | LEAD vs served |

## 4. Code checks (t18_emos.py, t18_controls.py)

| Rule | Result |
| --- | --- |
| 1 | Every source passes stamp <= captured_at plus h.assert_point_in_time (in pit()). The METAR rung uses an as-of join with an assert. NBH was in the pool but not chosen; it uses t5's S3 LastModified. |
| 2 | Inputs are only R, the prior and the sources, all from the allow-listed h.candidate_inputs(). is_winner is used only in paired() scoring. |
| 3 | The label Y (METAR daily hourly-row max) is used only on training rows. Asserts: dates <= 2026-08-22 and Y >= R. Serve-time coverage does not depend on Y. The prior uses history <= 2026-07-31. |
| 4 | h.score applies the floor; paired() calls _candidate_vector with unfloored=False. |
| 5 | Date assert present; rows_with_target_after_2026_09_29 = 0 in every score. |
| 8 | One coefficient set, no where=, no hour gate. |

## 5. Defects (none disqualifying)
1. **Availability basis:** 0.78% of rows (mostly 2026-09-24) use a v2 bulletin before its S3 LastModified. Each one is backed by a production NOMADS receipt, so an S3-only basis would understate availability. Any serving design or pre-registration should name NOMADS receipt as the availability basis.
2. **Size bar at +1 h:** the 00-16 LEAD meets the size condition only through the 5%-of-gap bar (-0.0105 against a -0.0012 bar). It misses the -0.0133 line.
3. **Harshest +2 h variant:** with impute and frozen parameters (no HRRR and no forecast_high), 00-16 is WEAK; its interval reaches +0.0004.
4. **Fragile component:** the rung's METAR timing is what weakens 10-16 under delay; the v2 increment is not. Under refit with delay, 17-23 r1 − rung turns HARM (+0.0016 at +60 impute, +0.0037 at +120 stale), so 17-23 must not be credited to T18.
5. **forecast_high stamp:** forecast_high has no stamp of its own. This is immaterial because it carries no increment.
6. **Context, not PIT:**
   - This is the known 79a/81a/111h v2-guidance family, read on previously inspected dates.
   - Serving depends on the 83a/83b parser repair plus a retrain.
   - The forking-path count belongs to the statistics refuter.

## Files
- **Code:** C:\pt\swarm\tools\research\model_parity\r-pit-t18_shift.py
- **Outputs (C:\swarm\out\refute-pit-t18\):** shift_summary.json, rpit18_*.score.json (17 files), nbp_s3_lastmod.json, v2_cycles_vs_s3.csv, s3_lastmod.py, shift_run.log
- **Not written:** report.md and the docs copy. A tool guard blocks subagents from writing report files, so this text is the report.

