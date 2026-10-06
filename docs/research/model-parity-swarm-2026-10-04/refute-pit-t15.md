# R-PIT-T15: PIT/leakage refutation of T15 (development)

**Verdict: NOT DISQUALIFIED on PIT/leakage grounds (disqualified = false).** The candidate is t15-r2 in
17-23 (LEAD, -0.0221). I found no leakage in the code for rules 1-5 or 8. The 17-23 result weakens when
the METAR availability lag is pushed to +1 h or +2 h, but it does not collapse:

| r2, 17-23, from stratum, all rows | cand - served [95%] | before stratum | markets negative | class |
|---|---|---|---|---|
| as registered (valid + 10 min) | -0.0221 [-0.0343, -0.0125] | -0.0271 | 11/11 | LEAD |
| +1 h (valid + 70 min), sigma refit | -0.0192 [-0.0317, -0.0097] | -0.0235 | 9/11 | LEAD |
| +2 h (valid + 130 min), sigma refit | -0.0131 [-0.0262, -0.0037] | -0.0160 | 9/11 | LEAD (passes on the 5%-of-gap bar; the point estimate is above -0.0133) |
| +2 h, original sigmas held fixed | -0.0143 [-0.0277, -0.0043] | -0.0171 | 9/11 | LEAD |
| integer T-group F (round(tgroup_f)) | -0.0222 [-0.0344, -0.0127] | -0.0270 | 11/11 | LEAD |
| body integer C converted to F (coarsest) | -0.0122 [-0.0249, -0.0015] | -0.0185 | 9/11 | LEAD |

r1 and r3 in 17-23 stay LEAD under every variant. r1: -0.0154, then -0.0141 at +1 h and -0.0114 at +2 h.
r3: -0.0128, then -0.0117 and -0.0098.

Candidate minus market (r2, 17-23, from stratum): +0.0077 as registered, +0.0106 at +1 h, +0.0167 at
+2 h. The leakage tripwire (`leakage_suspect_groups`) is empty for every variant. Every number here is
development. HARNESS_SHA256 is `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`. I
registered no new rules. All variants are sensitivity diagnostics of the registered t15-r1, t15-r2 and
t15-r3 procedures, imported unchanged.

## Defects found (none disqualifying)

1. **Sigma 0.27 F is not what gets scored.** `t15_diurnal_projection.py` line 166 has
   `sg = max(Sk[j], 0.5)`, so the 17-23 Normal uses sigma 0.5 F, not 0.27 F. The registered text says
   "Normal(P, sigma_block)" and does not mention the clamp. The hunter's "sigma 0.27 F" describes the
   fitted number, not the scored distribution. This is why +1 h with sigma refit (0.453) and +1 h with
   sigma held at 0.269 give identical results: both clamp to 0.5. The clamp only makes the candidate less
   confident, so it is not leakage. It is still a gap between the code and the registry text, and the
   synthesis should state it.
2. **The before-stratum sign check is partly in-sample.** The five block sigmas are fitted on the before
   stratum (allowed by rules 3 and 7). The LEAD condition "both strata same sign" therefore uses a stratum
   on which sigma is in-sample. The from stratum is out-of-sample for sigma but was read before (rule 7).
   That is for the statistics refuter. It is not a PIT defect.
3. **13-16 and maker diagnostic.** Under +1 h and +2 h, r2 in 13-16 becomes HARM: +0.0095 [+0.0027,
   +0.0155] and +0.0127 [+0.0062, +0.0188], with 2/11 and 1/11 markets negative. Nobody claimed 13-16,
   but with a realistic lag the projection hurts near the peak. The 00-16 maker aggregate also degrades,
   from WEAK -0.0049 to -0.0032 (+1 h) and -0.0021 (+2 h). The 00-05 and 06-09 classifier LEADs persist
   under the lag, but the hunter already assigns them to the r4 control mechanism (closed
   recalibration/sharpening thread).

## Point-in-time re-derivation of every input

| Input | Source and availability basis | Re-derived check | Result |
|---|---|---|---|
| METAR tmpf: T_now, running min, running max M | IEM asos.py routine (report_type 3) + SPECI (4); available = valid + 10 min; COR excluded via regex on the raw text | The IEM archive stores no ingest or receipt time per report, so the +10 min cannot be measured from a primary source per object. Live receipt-time feeds (aviationweather.gov) hold only recent days, which falls in the forbidden window of 2026-09-30 or later, so I did not query them. I bounded the lag by re-running at +1 h and +2 h (above). As independent corroboration, I compared M at t with production-captured `max(high_so_far, trusted_current_max)`, which production holds at captured_at. | 17-23: mean METAR minus captured is -0.02 F. M exceeds the captured value by >= 1 F in 0.61% of rows and by >= 2 F in 0.35%. 13-16: 1.5% / 1.2%. Production had this information at t, so **the 17-23 LEAD's input is genuinely point in time.** |
| Same, morning | as above | 00-05: M exceeds captured by 1.54 F on average, >= 1 F in 53% of rows. 06-09: 2.01 F, 57%. | This is not leakage: it survives +2 h, and searchsorted on available_utc is correct. The METAR since-midnight max is simply not what production captures, so the morning inputs need new capture (the hunter already says so). |
| forecast_high (G for r1, r2, r4) | captured snapshot feature: the served HGBC model's point forecast (`model_version` v0.5.10), present in 96.1% of rows | It was captured at captured_at_utc by construction, and it is not NBM/NBP guidance. | PIT |
| nws_grid_high (G for r3) | captured; nws_grid_updated_at and fetched_at | 110,773 rows with timestamps. Updated or fetched later than captured_at: 0. (hrrr_fetched_at and v2_available_at later than captured_at: also 0, though T15 does not use them.) | PIT |
| r(station, month, half-hour) table | IEM METAR, local dates <= 2026-07-31 | `assert hist.local_date.max() <= HIST_END` is in the code. Months {m-1, m, m+1} draw on 2024-2025 Aug/Sep and July 2026, all before the cutoff. | PIT (history only) |
| sigma per block (r2) | RMS(settlement_high - P) on before-stratum rows | `before_labels()` filters `stratum == "before_20260823"` before taking settlement_high. The labels feed only the sigma (clamped at 0.5) and MAE diagnostics. | Allowed by rule 3 |
| S3 LastModified / Open-Meteo | not used | T15 reads no NBH, NBS, HRRR, ECMWF or Single-Runs input. | n/a |

Raw METAR note: the last raw chunk was requested to 2026-09-30 04Z UTC, which covers the evening of local
2026-09-29 at the western stations. The tidy step drops local dates >= 2026-09-30 (0 rows kept), and T15
reads only the tidied parquet. No market or settlement record dated 2026-09-30 or later was touched.

## Rules checked in code

- **Rule 1 (PIT).** In `obs_features`, METAR rows are sorted by available_utc, `searchsorted(avail,
  captured, 'right') - 1` takes the latest obs available at or before t, running min and max are
  cumulative in availability order within the local date (the lag is constant, so this matches valid-time
  order), and the obs local date must equal the target date. `h.assert_point_in_time` runs on every
  station. COR rows are dropped. IEM 1-minute and 5-minute data are not used. tmpf matches T-group F within
  0.08 F (KORD sample, 25,379 rows), so tmpf is the T-group value rounded to 0.1 F, and an integer-rounding
  variant leaves the result unchanged.
- **Rule 2 (market).** Candidates are built from `h.candidate_inputs()` (allow-listed) and the band
  columns low, high, kind, p_served and floor_impossible. No price, mid, book or trade enters.
  `_candidate_vector` refuses forbidden columns.
- **Rule 3 (settlement).** settlement_high enters only through the before-stratum sigma fit (see above).
  No winner and no from-stratum label enters any candidate.
- **Rule 4 (floor).** The harness applies the 81a floor mask inside `score()` (not unfloored). r1 and r3
  also zero `floor_impossible` bands before shifting.
- **Rule 5 (dates).** The code asserts `(snaps.date > "2026-09-29").sum() == 0`, the harness asserts it
  again, and the count is 0.
- **Rule 8 (hour gates).** There is no NBM/NBP gate. The blocks are the harness's fixed blocks, sigma is
  per block (a dispersion parameter on the before stratum, not a guidance gate), and r(h) comes from
  history. G is the served model's forecast_high, not NBM guidance.

## Family note

After about 17:00, r is about 0 and P equals M, so the 17-23 effect is the T1 decided-band collapse
(running max plus a tight Normal clamped at 0.5 F). T1 and T15 count as one family in the synthesis. The
serving-stage form should take M from captured `trusted_current_max`/`high_so_far`, which agree with the
METAR max in 17-23 (above), and must be stated with its interaction with the 81a floor mask.

## Files

- Code: `C:\pt\swarm\tools\research\model_parity\r-pit-t15_lag_sensitivity.py`. It imports t15
  unchanged. Run it with runpy because the module name contains a hyphen.
- Scores: `C:\swarm\out\refute-pit-t15\rpit_t15_*.score.json`. Summary:
  `C:\swarm\out\refute-pit-t15\rpit_t15_sensitivity.json`.
