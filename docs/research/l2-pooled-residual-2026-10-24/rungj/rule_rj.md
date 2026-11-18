# L2 rung R-J pre-registration: R-G trajectory/floor columns in the afternoon (h13-14 primary, h15-16 secondary)

Written 2026-10-25 before any R-J row exists. Master pre-approved R-J (lever 3), relayed by the coordinator. This
is development evidence only and makes no edge claim. Nothing dated after 2026-09-29 is read, and nothing touches
MG-2 or L8's branch. Code is on `claude/rung0712-20261025` (functions `rung_g_emit` with R-J's hour parameters,
and `rung_j_score`).

## Selection, stated plainly

R-J is selected on the dev window. The R-H market-relative atlas (selection evidence, atlas sha `ff7ee231…`)
motivated it:

- P3d_N_fix's 13-16 loss to the capture-time market is concentrated where the captured observed path runs colder
  than NBM's diurnal path: +0.0183 [+0.0139, +0.0225], 47% of the window's excess, against +0.0045 on warm-path
  rows.
- The loss is concentrated at h13-14 (+0.0107 and +0.0105).
- So the dev dates used by gates 3 and 4 have already been looked at for this purpose.

The LOYO gate (2021-25) is the only gate on unseen data. The dev gates can only refute.

## The feature family (pre-committed, exactly one)

- The family is R-G's columns, unchanged: `RG_FEATURES` = t_trend3, t_trend3_miss, t_amp, t_path_gap (rule_rg.md,
  sha `a8cf6564…`).
  - They come from `trajectory_features`, `rg_columns` and `rg_diurnal_fraction`, with the same IEM 2021-25
    diurnal fractions, the same clip and the same 3 h window.
  - Arms are unchanged: B_G = B_N + `extra_ols` RG_FEATURES; P3d_G = P3d_N_fix + `extra_hgb` (t_trend3, t_amp,
    t_path_gap).
- No new feature, transform, window, interaction or HRRR input is added.
- HRRR's hourly path is a later, separately pre-registered variant and is excluded here.
- Fits are per cutoff hour, h13, h14, h15 and h16, on the Aug-Sep 2021-25 training rows at those hours. This is
  R-A and R-G's construction with `hours=(13, 14, 15, 16)`.

## Gates (in order; each stops the rung if it fails)

### Gate 1: parity

- R-G's parity result (gate 1, `rg_emit_audit.json`) covered the h07-12 rows only. The R-J rows (h13-16 cutoffs)
  are different, so parity is re-checked on them, with R-G's thresholds unchanged:
  - overnight_min exact ≥ 0.95;
  - trend3 within 1 °F/h ≥ 0.90;
  - IEM training coverage (3 reports in 3 h) ≥ 0.95.
- The verdict uses the h13-14 rows. Per-hour fractions for h13-16 are reported.

### Gate 2: LOYO 2021-25, B_G beats B_N at 13-14

- **Rows:** blocked leave-one-year-out (R-A's `rung_loyo`), all four arms on identical rows.
- **Statistic:** the mean per row of Brier(B_G) − Brier(B_N), pooled over h13 and h14, with a date-clustered
  bootstrap (R-A's construction).
- **PASS** if the upper 95% bound is below 0.
- **Reported:** h15-16 pooled, each hour, and P3d_G − P3d_N_fix.

### Gate 3: dev, P3d_G beats P3d_N_fix at 13-14

- **Population:** the same as R-A, R-F and R-G. Scorecard folds 2026-08-01..09-29, scored 08-15..09-29 (43 dates).
  Capture-time inputs; each layout row uses the latest replay snapshot at or before its own `captured_at_utc`.
- **Statistic:** dR = mean_cell(Brier_P3d_G − Brier_P3d_N_fix) / mean_cell(Brier_market), ALL markets, h13-14
  pooled, with date-clustered 95% intervals (2000 draws, seed 20260921).
- **Scope:** snapshots covered by B_N, B_G, P3d_N_fix, P3d_G and the composite's post-13 arm.
- **PASS** if the upper bound is below 0.
- **Reproduction controls (refused otherwise):**
  - The B_N and P3d_N_fix 13-16 files emitted under R-J must be byte-identical to R-H's
    (`C:\t\l2\rungh\emit1316`; P3d_N_fix `abc43507…`, B_N `bab9cac7…`).
  - The MG-1 07-12 positive control must give 0.012.

### Gate 4: against the composite's actual post-13 arm, read as in R-F

- **The comparator:** MG-2's post-13 half, which is P3d_N (MG-2 rule §1 and Clarification C2). On the dev
  window it is L2's dev emission `C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl` (sha
  `721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec`, the file MG-2's control replay reproduces).
  Where P3d_N is not usable (the scorecard's covered mask: no distribution, or no mass on an allowed band), MG-1
  is used, as in `mg2_composite.compose`. The fallback count is reported.
- **Comparison:** P3d_G against that comparator on the gate 3 scope and statistic.
- **Reading:**
  - **WIN** if the h13-14 upper bound is below 0 and neither h13 nor h14 has a lower bound above 0.
  - **HARM** if the lower bound is above 0.
  - **NULL** otherwise.
- **If WIN:** L2 drafts, but does not apply, a dated MG-2 post-13 Clarification text and an L8 control re-run
  plan. Nothing else.

### Reported only (never a gate)

- h15-16 pooled, and h15 and h16 separately, for every gate 3 and gate 4 comparison.
- B_G − B_N on dev.
- P3d_N_fix − composite post-13, to size the incumbent.

## PRE-REGISTERED KILL

If gate 2 or gate 3 fails, the trajectory family is closed for the afternoon too.

Concretely, no other trajectory, path-gap, trend or floor-feature variant is run on B_N, P3d_N_fix or any
NBM-anchored arm at any hour under any rung name. The separately pre-registered HRRR hourly-path variant is a
different source and is not covered by this kill. If gate 1 fails, nothing is fitted or scored, and R-J stops as
"parity failed" (not a kill).

## Outputs

- `C:\t\l2\rungj\emit\` holds the R-G-shaped emit with `rg_emit_audit.json`, `loyo_rows.jsonl` and the
  `dev_*.jsonl` files.
- `C:\t\l2\rungj\score\rj_score.json` holds the gate 3 and gate 4 results.
- `docs/research/l2-pooled-residual-2026-10-24/rungj/` holds this rule and the summary.
