# L2 rung 07-12 pre-registration (R-A: B_N then P3d_N_fix)

Written 2026-10-25 before any rung row exists. Proposals: C:\t\l2\rung0712\proposals.md
(sha256 5aefe0294714a35aee108526ce44ce4b58b1741d16eb25e4ddf1703fd53ad85e). Development evidence only; no edge claim.

## Arms (both pooled per cutoff hour 07..12, fitted on all Aug-Sep 2021-25 trainer records, union 744289be...)

- **B_N (simple baseline, SIMPLE-BASELINE-FIRST):** mu0 = nbm_mean + bias(market, aug_sep); mean = mu0 + OLS on
  [1, g, max(g, 0)] with g = high_so_far - mu0; one constant scale per hour = max(0.5, mean |inner-LOYO error| *
  sqrt(pi/2)); z = inner-LOYO errors / that scale; same kernel (0.25), observed floor, 2% climatology mix (alpha 0.10)
  over the 09-07 payload's bucket_space. No HGB.
- **P3d_N_fix:** amendment 5's P3d_N unchanged in model (OLS + HGB residual + HGB scale), with two input fixes only.
- **Inputs for both, training:** NBM 1ae4bf52... via L9 `nbm_at_cutoff` (forecast_high imputed when None); WU whole-F
  high_so_far / current_temp at or before h:00.
- **Inputs for both, dev (no look-ahead):** every C:\swarm\v3layout snapshot with effective cutoff 07..12 and
  local_hour >= cutoff; nbm_mean = `usable_v2_mean` (not finite -> not emitted, served fallback). high_so_far
  (METAR-only running max, `metar_only=True`) and current_temp (latest METAR row observed <= h:00) are read from **the
  latest replay snapshot captured at or before that layout row's own captured_at_utc** (L11 audit of 064aabe6a), then
  converted to WU whole F by `wu_whole_f_tgroup:half_up` (rule.md clarification 3 (c)).

## Validation

1. **Blocked leave-one-year-out (training, 2021-25):** per hour 07..12 and year Y, both arms fitted on the other four
   years and scored on Y's rows (identical rows); P3d_N_fix - B_N in Brier and log loss, date-clustered bootstrap
   (2,000 draws, seed 20261024). Reported.
2. **Dev scorecard (2026-08-01..09-29 folds, layout v3):** L3 `dev-score` unchanged (dev_scorecard machinery; crossed
   date x market and date-clustered intervals, 2,000 draws, seed 20260921; MG-1 = builtin `loss_atlas.mg1_frame` with
   its 07-12 excess control). Candidates B_N, P3d_N_fix, and the original P3d_N vectors (721ae2cd...) as an
   orientation candidate. References: served, MG-1, P3d_N (721ae2cd...), B_N. Groups 07-12 and h07..h12, pools ALL,
   PRIMARY5 and per market; scopes blended (all snapshots, served fallback) and covered (identical covered rows).

## Reading (PRIMARY: pool ALL, scope covered, group 07-12, date-clustered 95% interval of dR)

- **B_N vs MG-1:** WIN if upper < 0; HARM if lower > 0 -> the NBM-anchored family is killed at 07-12 (P3d_N_fix is
  then reported but cannot be admitted); otherwise NULL.
- **P3d_N_fix (only if B_N is not HARM):** admitted over the baseline only if P3d_N_fix - B_N upper < 0; then WIN vs
  MG-1 only if P3d_N_fix - MG-1 upper < 0 and no hour h07..h12 has lower > 0. Otherwise the HGB layer is killed at
  07-12 (if not better than B_N) or NULL vs MG-1.
- The blended scope, crossed intervals, PRIMARY5, per market and per hour are reported beside it and change nothing.
- The look-ahead effect (P3d_N_fix vs the original P3d_N) is descriptive.
- R-D (hour-wise MG-1 blend) runs only if the best admitted arm is within 0.02 of MG-1 in R at some hour 07..12;
  it gets its own rule.
