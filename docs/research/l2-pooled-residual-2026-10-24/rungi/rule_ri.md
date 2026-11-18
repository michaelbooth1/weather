# L2 rung R-I pre-registration: per-hour temperature on the 07-12 arms (width lever, one family)

Written 2026-10-25 before any R-I row exists. Master approved R-I with conditions, relayed by the coordinator.
This is development evidence only and makes no edge claim. Nothing dated after 2026-09-29 is read, and nothing
touches MG-2 or L8's branch.

R-I follows from the R-H atlas (selection evidence; atlas sha ff7ee231…). At 07-12, the loss to the capture-time
market is the winning bucket's mass: 0.415 for the market against 0.325 for L6 and 0.292 for P3d_N_fix. Our arms
put 0.25 to 0.28 of their mass two or more buckets from the winner, against the market's 0.16.

## Prior findings this rung must answer (ESTABLISHED_FINDINGS)

- **§1:** the gap is resolution, not calibration (84.772% / 15.228% on the `-09-44a` surface).
  "Never globally sharpen."
- **§1c:** recalibration is closed as a workstream.
  - The recoverable calibration share was 8.829% [−2.467%, +16.494%] on out-of-season C, and it is bounded at
    16.494%.
  - The families tested were scalar, per-market and daily-expanding isotonic, plus the power map q ∝ p^β.
  - The fitted β was 0.55, below 1, which is smoothing, not sharpening.
- **§1g:** conditional reshaping lost to global smoothing. Distribution reshaping is capped by a number that is
  indistinguishable from zero. Its standing instruction: "do not spend another decision here without a genuinely
  new mechanism".
- **§2:** the cool bias is a centre property (seasonal coverage). The centre, not the width, is the lever, and
  the trusted observed-high floor must never be weakened. The digest summarises this as "centre, not width, is
  the lever; never sharpen globally".

## Why R-I is not a re-run of §1c or §1g

1. **Different arms.**
   - §1c and §1g measured the old served model on the `-09-44a` export, where the fitted map smoothed (β < 1).
   - R-I's arms are L6 (the frozen MG-2 pre-13 arm) and P3d_N_fix (the pooled NBM-anchored residual model).
     Neither existed when those sections were written.
   - R-H shows these arms are too wide relative to the market. That is the opposite sign from §1c's served model.
2. **Different reference.**
   - The reference is the captured capture-time market (`p_market_yes`), never `last_in_hour`.
   - §1c used the older export's market column.
3. **Different fit.**
   - The temperature is fitted per hour and walk-forward: dates strictly before each scored date, on the dev
     window.
   - In the LOYO gate it is fitted strictly nested: the held-out year is never in the temperature fit or in the
     models that produce the fit's inputs.
   - §1c fitted one global map on in-season B and scored out-of-season C.
4. **Bounded ambition.** R-I does not claim the width is the gap. §1c's bound (at most 16.494%) is the prior
   expectation. R-I tests whether that bound has moved on these arms, under a pre-registered kill.

## The family (exactly one)

- The family is a per-hour temperature τ_h, applied as q_b ∝ p_b^τ_h over the bands or buckets of one snapshot
  and renormalised to sum to 1.
  - Bands with p_b = 0 stay exactly 0, so the hard floor and impossible bands are untouched.
  - If every band is 0, the distribution is left unchanged.
- There is one τ per local hour, h07 to h12, pooled over all markets. There are no per-market fits.
- τ_h is the minimiser of mean multi-category Brier over the grid {0.50, 0.51, …, 3.00}, which contains 1.00.
  On a tie, the τ closest to 1.00 is chosen.
- No other family, grid, objective, hour grouping or market split is tried.

## Gates (in order; each stops the rung if it fails)

### Gate 1: LOYO 2021-25, calibrated beats uncalibrated

- **Rows:** the R-A LOYO population, which is the Aug-Sep 2021-25 training rows at h07-h12 from
  `dev_training_frame` plus `attach_training_nbm` (identical inputs to R-A).
- **Arm:** P3d_N_fix (the NBM family; L6 has no 2021-25 counterpart because its nowcast is captured).
- **Fitting, strictly nested:** for each hour h and held-out year Y:
  1. For each year X ≠ Y, fit P3d_N_fix on the years outside {X, Y} and predict X.
  2. Fit τ_h(Y) on all those inner predictions.
  3. Apply τ_h(Y) to the plain LOYO prediction for Y (the model fitted on every year except Y).
- **Positive control:** the uncalibrated Y predictions must reproduce R-A's `loyo_rows.jsonl` P3d_N_fix_brier to
  1e-9 on every row (C:\t\l2\rung0712\emit\loyo_rows.jsonl). R-I is refused otherwise.
- **Training-score check (§1c method rule):** for every (h, Y), the fitted τ must not worsen its own inner-fit
  Brier. The grid contains 1.00, so this can only fail through a bug. It is reported anyway.
- **Statistic:** the mean per row of Brier(cal) − Brier(uncal), pooled over h07-h12, with a date-clustered
  bootstrap (2000 draws, seed as in `rung_loyo_summary`).
- **PASS** if the upper 95% bound is below 0. Per-hour values and τ_h(Y) are reported.

### Gate 2: dev 07-12, calibrated against the uncalibrated arm

- **Population:** the same as R-F. Scorecard folds 2026-08-01..09-29, scored 08-15..09-29 (43 dates). The
  capture-time inputs are the P3d_N_fix vectors cd0034b9….
- **Fitting:** τ_h(d) is fitted on covered P3d_N_fix snapshots at hour h dated in [2026-08-01, d), and applied on
  date d. With no prior date, τ = 1.
- **Statistic:** dR = mean_cell(Brier_cal − Brier_uncal) / mean_cell(Brier_market), on ALL markets at 07-12, with
  date-clustered 95% intervals (2000 draws, seed 20260921). The scope is covered snapshots, where P3d_N_fix and
  L6 are both covered.
- **PASS** if the upper bound is below 0 and no hour h07..h12 has a lower bound above 0.
- **Controls:** the MG-1 positive control must give 0.012. The R-F incumbent control requires P3d_N_fix − L6 on
  this scope to be reported, with the L6 part and nowcast shas checked.

### Gate 3: against L6, read as in R-F

- **Comparison:** P3d_N_fix_cal against L6 on the same scope and statistic.
- **Reading:**
  - **WIN** if the upper bound is below 0 and no hour h07..h12 has a lower bound above 0.
  - **HARM** if the lower bound is above 0.
  - **NULL** otherwise.
- **Caveat stated now:** L6's frozen coefficients are in-sample on this window, which favours L6.
- **If WIN:** L2 drafts, but does not apply, a dated MG-2 pre-13 Clarification text and an L8 control re-run
  plan, as in R-F. Nothing else.

### Reported only (never a gate, never an arm)

- **L6_cal − L6** on dev uses the same family and the same walk-forward fit applied to L6. L6 has no LOYO
  population, so this comparison cannot pass or fail anything.
- **Fitted τ_h** is reported per hour (mean, first and last over the scored dates) for both P3d_N_fix_cal and
  L6_cal.
- **Bucket-position decomposition (as in R-H):** P3d_N_fix_cal − P3d_N_fix at 07-12, with winner mass per arm.

## PRE-REGISTERED KILL

If gate 1 (LOYO) or gate 2 (dev against the uncalibrated arm) fails, the width lever is closed again for the NBM
family: no retries with new families.

Concretely, no other temperature grid, hour grouping, scale-parameter variant, per-market map, conditional
trigger or isotonic form is run on P3d_N_fix, L6 or any NBM-anchored arm under any rung name. EF §1c's closure
stands extended to these arms.

## Alternative reading (descriptive only; selection evidence; never feeds a gate or an arm)

This reading treats the winner-mass loss as a centre error rather than a width error.

- **Re-centring:**
  - For each covered 07-12 snapshot, k = (the market-implied median band index) − (the arm's median band index).
    The median band is the first band whose cumulative probability reaches 0.5, with the market normalised per
    snapshot.
  - The arm's distribution is shifted by k bands. Mass that would leave the band range is added to the end band.
  - Impossible bands are then set to 0, and the distribution is renormalised. If that zeroes every band, the
    unshifted distribution is kept.
- **Report:**
  - Brier excess against the market for P3d_N_fix, P3d_N_fix_cal, recentred(P3d_N_fix) and
    recentred(P3d_N_fix_cal).
  - The surviving share of R-I's gain = Σ_cells[B(rc_uncal) − B(rc_cal)] / Σ_cells[B(uncal) − B(cal)], with a
    date-clustered interval.
  - The same share for L6 / L6_cal.
- **Labelling:** this reading consumes the market benchmark. Every output carrying it is headed "SELECTION
  EVIDENCE", and it is never booked as model improvement (EF §1c, market-shrinkage paragraph).

## Outputs

- `C:\t\l2\rungi\ri_loyo.json` and `C:\t\l2\rungi\ri_loyo_rows.jsonl` for gate 1.
- `C:\t\l2\rungi\ri_score.json` for gates 2 and 3, the reported comparisons and the alternative reading.
- `docs/research/l2-pooled-residual-2026-10-24/rungi/` for this rule, the summary and the tables.
