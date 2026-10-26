# Lane L15 rung R-Q pre-registration: GEFS member spread as spread INFORMATION (07-12 on P3d_N_fix; 00-06 warm-tail variant on MG-1)

Written 2026-10-25 (lane L15, branch `claude/spread-info-20261026`).

At writing:
- No GEFS member value has been fetched, decoded or read by L15.
- L3's 00-06 atlas rows (`atlas_0006.json`, `tags_0006.parquet`) have not been opened by L15. Only the summary
  figures the coordinator relayed are known.
- R-S (`rule_rs.md`, 70908316…) is closed. The NBM-published-spread family was killed at gate 2.

Scope and limits:
- Development evidence only, with no edge claim.
- Nothing dated after 2026-09-29 is read. No 88a, panel or settlement data for 2026-09-30..10-15 is read.
- No paid data and no keys. No oracle.
- Nothing touches MG-2's frozen files, L8's branch, or R-O's pinned rule inputs (`rule_rn.md`, a9ca45f0…).
- The R-N, R-O and R-P names are not reused.

## 1. Why this differs from R-I, EF §1c and R-S

- **R-I** recalibrated width globally (a temperature on z). It closed global width recalibration.
- **EF §1c** records that a sharper-everywhere distribution is not edge.
- **R-S** used NBM's own published spread (TXNSD). L6 already carries that information as its width, and on
  v5.0 dev it is compressed.
- **R-Q** uses an independent ensemble's day-specific dispersion: the GEFS v12 30-member spread, from the
  same model version for all of 2021-2026, so there is no version drift.
  - The modulation is centred to mean zero (log scale) over the fitting years.
  - It cannot sharpen globally; it only redistributes width across days.
  - The location parameter and the floor are unchanged.

## 2. Inputs (point in time)

All GEFS data comes from AWS `noaa-gefs-pds` (anonymous HTTPS), message `TMP:2 m above ground`, members `gep01..gep30`.
`gec00` is excluded from every statistic. Only per-member station values, interpolated bilinearly at the market's
registry lat/lon, are used, in °F.

- **Variant A (07-12):** L11's R-O corpus `C:\t\l11pb\gefs\corpus\gefs_member_rows.jsonl`, used unchanged.
  - Product `pgrb2sp25`, the 06Z cycle of the target date D, f006..f024 every 3 h.
  - h_m is member m's max over the steps whose valid local date is D.
  - A member enters a row only if every step it needs has `available_utc` at or before the row's cutoff (h:00
    local, zoneinfo).
- **Variant B (00-06):** an added cycle in the same fetch (scope agreed with L11, recorded in its NAMING.md).
  - Product `pgrb2ap5` (0.5°), the **18Z cycle of D-1**, f018..f036 every 3 h, so valid 12Z D .. 06Z D+1.
  - h_m and the availability test are as in variant A, at cutoffs 00:00..06:00 local.
  - The 06Z D and 00Z D cycles are never used for 00-06: 00Z posts about 04Z, which is not before 00:00 EDT.
- **Row requirement:** at least 25 of 30 members present. Otherwise x = 0 for that row (no modulation), and coverage
  is disclosed.
- **Predictor A:** u = ln(max(SD_m(h_m), 0.25)), using the sample SD.
- **Predictor B:** u = ln(max(Q90_m(h_m) - Q50_m(h_m), 0.25)), the warm half-spread. Quantiles follow
  `model_sources.percentile` interpolation.
- **Centring:** x = u - ubar_mkt.
  - ubar_mkt is the mean of u over the market's rows in the fitting population: the training fold for A, and the
    prior dev dates for B (section 4).
  - In dev for A, ubar_mkt is the mean over all 2021-25 rows.

## 3. Variant A: 07-12 on P3d_N_fix (primary)

### Modulation

The modulation has R-S's form exactly, with only the predictor replaced:
- m = clip(beta_h · x, -ln 2, +ln 2);
- s' = max(0.5, s · e^m);
- beta_h in {0, 0.05, …, 1.5}, one beta per hour h07..h12, pooled over markets;
- ties go to the smallest beta.

The selection is R-S's tabulated-kernel search, with exact re-scoring of the top 3 candidates and beta = 0. The
anchor, the floor censoring, the kernel z, the 2% climatology mix and the probability mass are unchanged. At beta = 0
the arm is byte-identical to P3d_N_fix.

### Gates

Gate 1 and gate 2 follow R-S's gates exactly, including their seeds, controls and populations:
- **Gate 1:** nested LOYO 2021-25 vs unmodulated, with the R-A control to 1e-9. PASS if the pooled upper bound is
  below 0.
- **Gate 2:** dev 08-15..09-29 vs unmodulated, with the control byte-identical to cd0034b9…. PASS if the upper bound
  is below 0 and no hour has a lower bound above 0.

Gate 2 also requires L11's precondition P to have passed. P is GEFS p10/p90/control parity with the capture on
07-12 dev snapshots.
- If P failed, gate 2 is not run and A is BLOCKED (not killed).
- Dev uses the history corpus values, with the disclosure that serving would read the Open-Meteo capture.

Gate 3 and the 13-16 secondary follow R-S's rule:
- **Gate 3:** vs L6, read as WIN, HARM or NULL. Report only.
- **Secondary 13-16:** LOYO, then dev vs the R-H control abc43507…, on 06Z values with the same availability test.
  It never reopens the primary.

## 4. Variant B: 00-06 warm tail on MG-1 (served arm at 00-06)

**Why.** L3's relayed 00-06 summary says MG-1 is too wide, with the warm tail over-weighted:
- +2 bucket: 0.118 vs the market's 0.066;
- +3 and beyond: 0.072 vs 0.027.

Global narrowing is barred (R9). The test is whether the **day-specific** GEFS warm half-spread tells which days
deserve a heavy warm tail.

### Arm

MG-1 as the dev scorecard builds it (`loss_atlas.mg1_frame`): mu, sigma = max(v2_stddev, 1), the running-max floor,
and MG-1's band mapping. The CDF Phi((t - mu)/sigma) is replaced by the two-piece CDF:
- F(t) = Phi((t - mu)/sigma) for t <= mu;
- F(t) = Phi((t - mu)/sigma_up) for t > mu;
- sigma_up = max(1, sigma · e^m), with m = clip(beta_h · x, ±ln 2), x as in predictor B.

Properties:
- The median stays at mu.
- The cold half is unchanged.
- Floor censoring is MG-1's, unchanged, applied to F, so below-floor mass changes only through the warm half.
- Mass is preserved to 1e-9.
- At beta = 0 the vector is byte-identical to MG-1.

### Fitting

There is no 2021-25 MG-1 history at 00-06 here, so beta is fitted walk-forward on dev:
- For each scored date d and hour h, beta_h(d) is the grid minimiser of mean Brier over the covered MG-1 00-06 dev
  snapshots dated in [2026-08-01, d).
- ubar_mkt(d) is the mean of u over the same prior rows.
- Before 10 prior dates, beta = 0.
- The grid and tie-break are as in A.
- No other form, statistic, cycle, product, hour grouping or objective is tried.

### Gate B1: dev 00-06 vs MG-1

- **Population:** the dev scorecard, layout `C:\swarm\v3layout`, folds 08-01..09-29, scored 08-15..09-29, the common
  covered MG-1 snapshots at local hours 00..06.
- **Statistic:** dR = mean_cell(Brier_B - Brier_MG1) / mean_cell(Brier_market), date-clustered (2,000 draws, seed
  20260921).
- **PASS** if the upper bound is below 0 and no hour h00..h06 has a lower bound above 0.
- **Controls:** the MG-1 excess at 00-06 is reproduced and reported; beta = 0 is byte-identical; mass is preserved.
- **Reported only:**
  - the warm-tail mass at +2 and at +3 and beyond, vs the market, before and after;
  - winner-bucket mass;
  - mean m;
  - the share of rows with m < 0.

  These are never gates.
- **Precondition P_B:** this corpus's p10/p90 of h_m vs the captured `day_member_high_p10/p90` on 00-06 dev
  snapshots, with L11's thresholds (|mean diff| <= 1 °F, median |diff| <= 1 °F, r >= 0.95). If it fails, B is
  BLOCKED, not killed.
- **Against L3's R-PD arm:** reported only, if R-PD has scored.

## 5. PRE-REGISTERED KILL

- **A fails gate 1 or gate 2:** GEFS member SD is closed as a P3d_N_fix / L6-family scale modulator at 07-16. No other
  cycle, product, member statistic (IQR, range, MAD), centring, clip, grid or hour grouping is run as a scale
  modulator under any rung name.
- **B fails B1:** GEFS warm half-spread is closed as an MG-1 upper-tail modulator at 00-06, with the same breadth.
- **A BLOCKED or B BLOCKED** (parity fails) is not a kill.

## 6. Outputs

All outputs go outside the repository, under `C:\t\l15\rq\`:
- `rq_loyo_0712.json`, `rq_loyo_1316.json`;
- `rq_emit_*`, `rq_score_0712.json`;
- `rq_b_0006.json`, `rq_parity_b.json`.

A summary goes on the branch. The code extends `weather.calibration.spread_information_rung`, which is already
allowlisted.
