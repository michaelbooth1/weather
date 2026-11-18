# L2 rung 07-12 R-D pre-registration (walk-forward MG-1 / P3d_N_fix blend) + R-E (descriptive)

Written 2026-10-25 before any blend row exists. R-A rule: C:\t\l2\rung0712\rule.md (sha 0b6be0d6...); R-A scores
C:\t\l2\rung0712\scores.json (sha 3c408182...). Precondition met: at h07 P3d_N_fix R 1.180 vs MG-1 1.190 (|diff| <=
0.02). Development evidence only; no edge claim; nothing after 2026-09-29.

## R-D blend

- **Components:** MG-1 = builtin `loss_atlas.mg1_frame` (no fitted parameter); P3d_N_fix = C:\t\l2\rung0712\emit\
  dev_P3d_N_fix.jsonl (sha cd0034b9...). Both through the scorecard's `Table.candidate_vector` (rule-4 floor mask,
  renormalised, served fallback).
- **Blend:** per snapshot p = w * p_P3d_N_fix + (1 - w) * p_MG1 where both are covered (the scorecard's covered mask);
  p = p_MG1 elsewhere. Linear pool on band vectors.
- **Weight:** one w per (local hour h in 07..12, scored date d). w(h, d) = the exact minimiser over [0, 1] of the mean
  band Brier of the pool on every snapshot with local_hour = h, both covered, and date in [2026-08-01, d) -- strictly
  before d, from a scorecard Table built over 2026-08-01..09-29. Closed form w = clip(-sum B / sum A, 0, 1) with
  A = sum_bands (a - b)^2 / n, B = sum_bands (a - b)(b - y) / n per snapshot (a = P3d_N_fix, b = MG-1). Nothing is
  tuned on scored rows; no other parameter.
- **Population and intervals:** identical to R-A: dev_scorecard folds 2026-08-01..09-29 (scored 08-15..09-29, 43
  dates, 473 market-days), crossed date x market and date-clustered 95% intervals, 2,000 draws, seed 20260921
  (`r0_ols_floor_challenger._date_weights`), dR = mean_cell(Brier_blend - Brier_ref) / mean_cell(Brier_market).
- **References:** MG-1, P3d_N_fix, B_N (dev_B_N.jsonl, sha 83cf9bbe...), served. Scopes covered (blend, reference
  and P3d_N_fix all covered) and blended. Groups 07-12, h07..h12; pools ALL, PRIMARY5 (descriptive), per market.
- **Reading (PRIMARY: ALL, covered, 07-12, date-clustered):** WIN vs MG-1 if upper < 0 and no hour h07..h12 has
  lower > 0. **Kill:** if the upper bound vs MG-1 is >= 0, 07-12 parity is closed for the NBM family and the ladder
  stops there. Blend vs P3d_N_fix and vs B_N, crossed intervals, PRIMARY5 and per market are reported only.
- **Reported:** w(h, d) per hour: mean over scored dates, first and last scored date.

## R-E (descriptive only; decides nothing)

P3d_N_fix - MG-1 at 07-12, h11, h12 (ALL, covered rows of both), decomposed exactly into band-position classes:
position = band_index - winning band_index, classes <= -3, -2, -1, 0, +1, +2, >= +3. Contribution of a class =
mean_cell(sum over its bands of ((p_a - y)^2 - (p_b - y)^2) / n) / mean_cell(Brier_market); the classes sum to dR.
Date-clustered 95% interval per class. Also per market (07-12) and the mean probability on the winning band for both.
