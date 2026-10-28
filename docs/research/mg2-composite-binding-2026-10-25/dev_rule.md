# MG-2 composite: dev-window sizing run (LOCKED before the run)

Written 2026-10-25, before any composite vector exists. Code: `weather.calibration.mg2_composite dev`
on `claude/mg2-composite-binding-20261025`. **Every number this run produces is development
selection evidence only.** It sizes the forward look; it cannot pass, fail or promote MG-2.

## What is computed

- **Candidate:** the composite. Before 13:00 local it is MG-1 plus lane L6's own-obs stack, refit per
  walk-forward fold (`l6_stack.fit(train, "n_own")`). From 13:00 it is arm A, L3's `ols_floor`
  `l8_high_so_far` distributions `C:\t\l3\dev_l8\dev_l8_high_so_far_ols_floor.jsonl` (2021-25 fit).
  MG-1 is used where a half has nothing usable. The switch hour is 13, fixed.
- **Comparator:** MG-1, `loss_atlas.mg1_frame`, on the same rows.
- **Scorer:** dev scorecard `Table` (2026-08-01..09-29, default folds, rule-4 mask, served
  fallback). Brier delta = mean_cell(B_mg2 − B_mg1); dR = that over mean_cell(B_market).
  Date-clustered 95% interval, 2,000 draws, seed 20261025; crossed reported beside it.
- **Sizing:** per N in {30, 45, 60}, the date-bootstrap SE of the equal-cell mean at N dates. Then
  MDE80 = (1.95996 + 0.84162) × SE. Also the power at the dev point, for superiority at 13-16 and
  for non-inferiority at 00-16 against margin +0.0010 Brier.

## (a) Positive control

The run is void unless these hold:

- **Pre-13 equals L6:** composite equals L6's own-obs twin on every band before 13:00 (max abs
  ≤ 1e-12). L3 reproduced L6's 07-12 Brier − MG-1 = −0.0036243.
- **Post-13 equals arm A or MG-1:** composite equals arm A where arm A is used, and MG-1 elsewhere
  (max abs ≤ 1e-12).
- **MG-1 control:** MG-1 − served 00-12 dR −0.0153 (lane G / L8) is not re-derived. Reproducing the
  first two checks is the control.

## (b) Comparator fairness

MG-1 and both halves get the same floor: the scorecard's rule-4 floor mask, with
B = floor(F + 0.5) and F = max(guidance_physical_floor, high_so_far, trusted_current_max). They also
get the same calibration: none, because MG-1 has no calibration stage. MG-1 falls back to served.

## (c) Targeted loss slice

The slice is 13-16 local, where arm A is the change.
- Loss atlas `46a66f7b7727` attributes 76.1% of the 00-16 excess (0.0256) to the centre.
- L3's arm A − MG-1 13-16 dR is −0.3661 [−0.5315, −0.2231] (EF 10ab). It is the expected size,
  and it is selection evidence.

## (d) MDE and clusters

- **Expected MDE:** 0.0015 Brier at 13-16 for 45 dates, scaled from arm A's dev interval. This run
  measures it.
- **Clusters:** 43 date clusters × 11 markets (473 cells).

## (e) Dev-window reuse

`DEV_WINDOW_LEDGER.md` row 20; reuse count 20 on this window.

## Stop condition

If either of the following holds, I report to the coordinator before any binding text is written:
- the 13-16 date-clustered upper bound is ≥ 0;
- the 00-16 lower bound is > 0.
