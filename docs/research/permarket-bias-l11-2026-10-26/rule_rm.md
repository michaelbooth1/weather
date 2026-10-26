# Lane L11 rung R-M pre-registration: per-market centre bias at 07-12 on L6 and P3d_N_fix (one family)

Written 2026-10-25 (lane L11, branch `claude/permarket-bias-20261026`), before any R-M row exists. The owner
directed full throttle on model improvement, and the coordinator relayed R-M as lever 1 of 2. This is
development evidence only and makes no edge claim.

- Nothing dated after 2026-09-29 is read.
- No 88a, panel or settlement data for 2026-09-30..10-15 is read.
- No oracle.
- Nothing touches MG-2 or L8's branch.
- Code base: L2's `claude/rung0712-20261025` @ 63c500021 (`weather.calibration.pooled_residual_model`); R-M
  code is appended to that module on this branch.

## Selection evidence and boundary

- **Selection (R-H atlas, `rungh/rh_summary.md` sha b62c5af6…, finding 4).**
  - At 07-12, P3d_N_fix's excess over the capture-time market is clearly positive in Dallas (+0.0173), Austin
    (+0.0159) and Seattle (+0.0152 [+0.0088, +0.0210]), against a pooled +0.0101.
  - It is null in Miami, San Francisco, Denver and Chicago.
  - L6 ranks the markets the same way, with a smaller spread (Dallas +0.0119, Austin +0.0113).
  - R-H hypothesis 4 names per-market bias as a lever. The lever inventory (row 5) records that it has never
    been run on L6 or P3d_N_fix.
  - This is selection evidence, so every R-M market is fitted, not only these three.
- **Boundary (R-I kill, `rungi/rule_ri.md` sha b8a3d79c…, result `ri_summary.md` sha 09261d45…).**
  - R-I closed width recalibration for every NBM-anchored arm: temperature grids, hour groupings, scale variants,
    per-market maps, conditional triggers and isotonic forms.
  - R-M therefore has **no width, temperature, scale or spread parameter**. Its one free quantity is an
    additive centre shift in °F.
  - R-I gate 2 failed because a walk-forward fit on dev did not transfer across dates. R-M faces the same risk
    and the same gate.
- **Prior (stated now).**
  - P3d_N_fix already carries a (market, season) additive bias fitted on 2021-25 (`MeanModel`,
    `bias_by="season"`), so on the LOYO population a further per-market shift is expected to be near 0.
  - On MG-1, per-market debias (A1) was null: -0.0001 [-0.0042, +0.0045] (morning-loss addendum 10-25).
  - The inventory bounds the plausible gain at about -0.0005 to -0.0015 pooled.

## The family (exactly one)

- **Shift.** One additive shift s_m in °F per market m, for the single hour block 07-12, so one s per market.
  Hours h07..h12 share it.
- **Grid.** s is the minimiser of the population's own mean Brier over the grid {-4.0, -3.9, …, +4.0}, which
  contains 0.0. On a tie, the s closest to 0 is chosen.
- **Exclusions.** No other family, grid, objective, hour grouping, market grouping or shrinkage is tried.
- **How the shift is applied, per arm.**
  - **P3d_N_fix (integer-°F pmf).** Each integer key k carries its mass uniformly on [k - 0.5, k + 0.5].
    1. The density is translated by s and rebinned to integers: q_k = G(k + 0.5) - G(k - 0.5), where
       G(x) = F(x - s) and F is the arm's piecewise-linear CDF at the half-integer edges.
    2. The rule-4 floor mask then sets mass on impossible outcomes to 0 and renormalises:
       - on dev, this is the scorecard's own `candidate_vector` mask over the market bands, unchanged;
       - in LOYO, it zeroes integer keys below round_half_up(F) and renormalises, applied identically to the
         shifted and the s = 0 distributions.
    3. If the mask zeroes everything, the unshifted distribution is kept.
    4. At s = 0 the dev distribution is byte-for-byte the registered arm.
  - **L6.**
    - L6 is v2_mean + a_h + b_h (nowcast - v2_mean), passed to MG-1's Gaussian band probabilities.
    - The shift is applied to that centre (mu + s) before `mg1.predict`'s band probabilities. Width and floor
      handling are unchanged.
    - At s = 0 this is the registered L6 exactly.
  - **Known difference, stated now.** On P3d_N_fix the translation moves the whole pmf, including its 2%
    climatology component. On L6 only the Gaussian centre moves.

## Gates (in order; each stops the rung if it fails)

### Gate 1: LOYO 2021-25, shift beats no-shift (P3d_N_fix)

- **Rows:** the R-A / R-I LOYO population, which is the Aug-Sep 2021-25 training rows at h07-h12 from
  `dev_training_frame` (records `C:\t\l2\records`) plus `attach_training_nbm` (corpus
  `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl`, sha 1ae4bf52…).
- **Arm:** L6 has no 2021-25 counterpart (its nowcast is captured), so gate 1 is the out-of-sample gate for
  both arms.
- **Fitting, strictly nested,** for each held-out year Y and each market m:
  1. For each year X ≠ Y and each hour h07..h12, fit P3d_N_fix on the years outside {X, Y} and predict X.
  2. Fit s_m(Y) on all those inner predictions of market m, pooled over hours.
  3. Apply s_m(Y) to the plain LOYO prediction for Y (fitted on every year except Y).
- **Positive control:** the unshifted, unmasked Y predictions must reproduce R-A's `loyo_rows.jsonl`
  P3d_N_fix_brier (sha 21cacdaa…) to 1e-9 on every row. R-M is refused otherwise.
- **Training-score check:** no fitted s may worsen its own inner Brier. The grid contains 0, so this can only
  fail through a bug. It is reported anyway.
- **Statistic:**
  - The mean per row of Brier(shift) - Brier(no shift), both under the LOYO mask.
  - It is pooled over all markets and h07-h12, with a date-clustered bootstrap (2,000 draws, seed 20261024).
  - Brier is the multi-category integer-key form `fm.brier_score`.
- **PASS** if the upper 95% bound is below 0.
- **Reported:** per market, per hour, and s_m(Y).

### Gate 2: dev 07-12, shifted arm against the same arm unshifted (per arm)

- **Population:** as R-F and R-I.
  - Scorecard folds 2026-08-01..09-29, scored 08-15..09-29.
  - Layout `C:\swarm\v3layout`.
  - P3d_N_fix vectors `C:\t\l2\rung0712\emit\dev_P3d_N_fix.jsonl`, sha cd0034b9….
  - L6 frozen part 07a67425… from `C:\t\mg2\freeze_cap\mg2_coefficients.json`, and nowcast
    `C:\t\mg2\l6cap_ctl\nowcasts.parquet`, sha 3806687c…; anything else is refused.
  - Scope: the common covered snapshots, where both P3d_N_fix and L6 are covered.
- **Fitting:** s_m(d) is the grid minimiser of the summed scorecard Brier on common covered snapshots of market m
  at 07-12, dated in [2026-08-01, d). It is applied on date d. With no prior date, s = 0.
- **Statistic:** dR = mean_cell(Brier_shift - Brier_unshift) / mean_cell(Brier_market), for ALL markets at
  07-12, with date-clustered 95% intervals (2,000 draws, seed 20260921).
- **PASS** if the upper bound is below 0 and no hour h07..h12 has a lower bound above 0.
- **Controls:**
  - The MG-1 positive control must give 0.012.
  - L6 (s = 0) − P3d_N_fix must be reported (R-F incumbent control), with both shas checked.
  - Mass must be preserved, to 1e-9.

### Gate 3: against L6, read as in R-F (for each arm that passed gate 2)

- **Comparisons:**
  - P3d_N_fix_shift against L6 (unshifted).
  - L6_shift against L6, which is gate 2 for L6, read as gate 3.
- **Reading:**
  - **WIN** if the upper bound is below 0 and no hour h07..h12 has a lower bound above 0.
  - **HARM** if the lower bound is above 0.
  - **NULL** otherwise.
- **Caveat stated now:** L6's frozen coefficients are in-sample on this window, which favours L6. That includes
  its per-hour pooled intercept a_h, which can absorb part of any pooled bias.
- **If WIN:** a dated MG-2 pre-13 Clarification text is drafted, not applied, as in R-F. Nothing else.

## PRE-REGISTERED KILL

- **Gate 1 fails:** per-market centre bias is closed for every NBM-anchored arm (P3d_N_fix, L6, MG-1 family and
  P3d_N family).
- **Gate 2 fails for both arms:** the same closure applies.
- **Gate 2 fails for one arm only:** the lever is closed for that arm.
- **"Closed"** means no other grid, hour block, shrinkage, objective, market grouping or rolling window is run
  under any rung name.

## Reported only (never a gate)

- s_m on dev per market: mean, first and last over the scored dates; and s_m(Y) from LOYO.
- Per-market dR at 07-12, for each arm.
- The R-H three (Dallas, Austin, Seattle) are called out. This is descriptive only and never re-selected.

## Outputs

- `C:\t\l11pb\rm_loyo.json` and `rm_loyo_rows.jsonl` for gate 1.
- `C:\t\l11pb\rm_score.json` for gates 2 and 3.
- This branch carries the rule copy and the summary.
