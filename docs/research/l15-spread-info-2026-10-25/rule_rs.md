# L15 rung R-S pre-registration: NBM TXNSD spread information on P3d_N_fix (one family)

Written 2026-10-25 before any R-S row is joined to an outcome. Master ruling R9 (relayed by the coordinator):
R-I's kill covers fitted temperature/scale maps only; day-specific predictors of forecast uncertainty are a new
family needing their own pre-registration and the full ladder. This is development evidence only and makes no
edge claim. Nothing dated after 2026-09-29 is read; nothing touches MG-2, L6's frozen coefficients or L8.
Plan and predictor inventory: `C:\t\l15\plan.md` (sha256 523d334e65e6a7af335ec2f98734a26e6368d33654816a4f198f9014fac00483).

## Prior findings this rung must answer

- **R-I** (`rungi/rule_ri.md` b8a3d79c…, KILL at gate 2): a per-hour temperature q ∝ p^τ, fitted walk-forward,
  did not transfer (dev −0.0022 [−0.0156, +0.0104]); its kill bars any further fitted temperature grid, hour
  grouping, scale-parameter variant, per-market map, conditional trigger or isotonic form on NBM-anchored arms.
- **EF §1c**: recalibration is closed (bound 16.494%); global sharpening retired (fitted β was smoothing).
- **EF §1g**: conditional reshaping lost to global smoothing on its own training score; "do not spend another
  decision here without a genuinely new mechanism".
- **EF §1 / §2**: centre, not width, is the lever; never sharpen globally; never weaken the observed-high floor.

## Why R-S is not a re-run of R-I, §1c or §1g

1. **New information, not a re-map.** R-I, §1c and §1g transform the arm's own probabilities with a function of
   those probabilities (p^τ, isotonic, a peak-probability trigger). R-S feeds an input the arm has never seen:
   NBM's published standard deviation of the daily maximum (NBP TXNSD) for that market and day. P3d_N_fix's scale
   model has no forecast-uncertainty input (`fit_pooled`: levels − anchor, floor gap, normal, bias, location,
   day of year). L6 and MG-1, which beat or match P3d_N_fix at 07-12, already use σ = max(v2_stddev, 1). This is
   the "genuinely new mechanism" §1g asks for: a day-specific information input to spread.
2. **No global sharpening by construction.** The modulation is centred to mean exactly 0 in log scale over each
   fit's own training rows, and its predictor is a trailing same-market anomaly, so a level shift in NBM's sd
   (versions 4.0 → 5.0) cannot become a net sharpening or smoothing.
3. **Fit on 2021-25, scored on dev with no dev fitting.** R-I's walk-forward τ fitted on dev did not transfer.
   R-S's coefficient for dev is fitted on 2021-25 only and frozen before dev rows are joined.
4. **Mean, floor, z set and climatology mix unchanged.** Only the per-row scale s of the kernel-smoothed residual
   distribution moves.

## The family (exactly one)

Arm: **P3d_N_fix** (rung 07-12 R-A form: `_rung_entry(train, simple=False)`, `_dist_from_fit`), unchanged except:

- **Predictor.** For a row (market m, target date d, cutoff hour h):
  - sd_d = the NBP 07Z TXNSD (°F) on the same bulletin the anchor uses. Training: the L9 corpus row that
    `nbm_at_cutoff` selects (LastModified ≤ cutoff), corpus 1ae4bf52…. Dev: the snapshot's captured `v2_stddev`
    under the `usable_v2_mean` filter (the same rows that carry the anchor).
  - b_d = mean of log(sd) over the 07Z NBP bulletins of market m for target dates d−14 .. d−1 (training: L9 corpus;
    dev: the 2026 NBP corpus 85746b7a…), available rows only, requiring at least 5 values.
  - x = log(sd_d) − b_d. x = 0 when the anchor is imputed (no NBM at cutoff), sd_d is missing or < 1, or b_d has
    fewer than 5 values.
- **Centring.** x̄ = mean of x over the fit's own training rows at hour h (zeros included). x_c = x − x̄.
- **Modulation.** m = clip(β_h · x_c, −ln 2, +ln 2); s' = max(MIN_SCALE, s · e^m), where s is the arm's own scale.
  The distribution is `predictive_distribution(yhat, s', F, z, buckets, p_clim)` with yhat, F, z, p_clim
  unchanged. β_h is monotone non-negative: grid {0.00, 0.05, …, 1.50} (31 values, contains 0), one β per local
  hour, pooled over markets, minimiser of the summed multi-category Brier (`fm.brier_score`) over the fit rows;
  ties go to the smallest β. No per-market fit, no other predictor, transform, grid or objective is tried.
- **Floor and mass.** The floor censoring, the 2% climatology mix and mass normalisation are those of
  `predictive_distribution`; R-S asserts mass 1 ± 1e-9 per snapshot and that no band below the floor gains mass.

## Gates, primary block 07-12 (in order; each stops the rung if it fails)

### Gate 1: nested LOYO 2021-25, modulated beats unmodulated

- **Rows:** the R-A LOYO population (Aug-Sep 2021-25 rows at h07-h12 from `dev_training_frame` +
  `attach_training_nbm`, identical inputs to R-A and R-I).
- **Fitting, strictly nested,** per hour h and held-out year Y: for each X ≠ Y, fit P3d_N_fix on the years outside
  {X, Y} and predict X (x̄ from that fit's rows); pick β_h(Y) on all those inner predictions; apply β_h(Y) to the
  plain LOYO prediction of Y (fit on all years ≠ Y; x̄ from that fit's rows).
- **Positive control:** β = 0 must reproduce R-A's `C:\t\l2\rung0712\emit\loyo_rows.jsonl` P3d_N_fix_brier to 1e-9
  on every row, else R-S is refused. Training-score check: every fitted β must not worsen its own inner Brier.
- **Statistic:** mean per row of Brier(mod) − Brier(unmod), pooled h07-h12, date-clustered bootstrap (2000 draws,
  seed 20261024). **PASS** if the upper 95% bound < 0. Per hour, log loss, β_h(Y) and mean |m| are reported.

### Gate 2: dev 07-12, modulated against the unmodulated arm

- **Frozen coefficient:** β_h(dev) = the grid minimiser over the plain LOYO predictions of all five years (each with
  its own fit's x̄), fitted before any dev row is joined to an outcome. The dev fit is R-A's all-years fit; x̄ is
  its training mean.
- **Emission:** the unmodulated dev vector must be byte-identical to R-A's `dev_P3d_N_fix.jsonl`
  (sha cd0034b9…), else R-S is refused.
- **Population and statistic (as R-I gate 2):** scorecard folds 2026-08-01..09-29, scored 08-15..09-29;
  dR = mean_cell(Brier_mod − Brier_unmod) / mean_cell(Brier_market) on ALL markets at 07-12, date-clustered 95%
  (2000 draws, seed 20260921), common covered snapshots (P3d_N_fix and L6 both covered). MG-1 positive control
  0.012; L6 part and nowcast shas checked.
- **PASS** if the upper bound < 0 and no hour h07..h12 has a lower bound > 0.

### Gate 3: against L6, read as in R-F

- P3d_N_fix_S against L6, same scope and statistic. **WIN** if upper < 0 and no hour lower > 0; **HARM** if lower > 0;
  **NULL** otherwise. Caveat: L6's frozen coefficients are in-sample on this window, which favours L6. If WIN, L15
  drafts, but does not apply, a dated MG-2 pre-13 clarification text and an L8 control re-run plan. Nothing else.

## Secondary block 13-16 (reported; never reopens or rescues the primary)

- Same family, LOYO at h13-h16 on the same training rows (no R-A control rows exist there; the internal β = 0
  rows are the reference), then dev 13-16 against the R-H 13-16 P3d_N_fix vectors (`C:\t\l2\rungh\emit1316\
  dev_P3d_N_fix.jsonl`, byte-identical control abc43507…), scope = P3d_N_fix-covered snapshots at 13-16.
- Secondary PASS = LOYO upper < 0 and dev upper < 0 with no hour lower > 0. Dev 13-16 runs only after LOYO 13-16
  passes. A secondary pass while the primary fails is recorded as a lead for a ruling, not as an open family.

## PRE-REGISTERED KILL

If gate 1 or gate 2 (primary, 07-12) fails, **the NBM-published-spread predictor family is closed** for
P3d_N_fix, L6 and every NBM-anchored arm: NBP TXNSD, NBP percentile width (p90 − p10), and NBS XND/TSD at fresher
cycles, under any transform, anomaly window, grid, hour grouping or rung name. Other spread families (GEFS member
spread, multi-model dispersion, observed-state predictors) are not covered by this kill and need their own rule.

## Reported only (never gates)

- Mean modulation m and the share of rows with x = 0 on training and dev (a |mean m| above 0.05 on dev is flagged).
- β_h per hour (LOYO per held year; dev frozen).
- Per-market dR at 07-12; excess vs market for P3d_N_fix, P3d_N_fix_S and L6 (SELECTION EVIDENCE: consumes the
  market benchmark, never booked as improvement).

## Outputs

`C:\t\l15\loyo\rs_loyo.json`, `rs_loyo_rows.jsonl`; `C:\t\l15\emit0712\`, `C:\t\l15\emit1316\`;
`C:\t\l15\score\rs_score_0712.json`, `rs_score_1316.json`; code on `claude/spread-info-20261026`
(`weather.calibration.spread_information_rung`).
