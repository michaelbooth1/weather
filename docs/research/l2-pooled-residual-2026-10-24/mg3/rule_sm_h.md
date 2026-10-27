# SM-H: season-matched P3d_H at 13-15 for MG-3 (history only, one look)

Lane L2, 2026-10-26. Ordered by master through the coordinator. This file is written, hashed and pushed before
any SM-H fit or score. Dev-window ledger row 48 (`claude/l2-dev-ledger-rows-20261026`) is PENDING before the run.

## 0. Question and what it decides

MG-3 serves P3d_H at 13-15. Its state was fitted on Aug-Sep 2021-25. CS-1 (1b) shows that the Aug-Sep P3d_H does
not keep its edge over P3d_N in Oct-Dec at 14-15 (H − N at 13/14/15: −0.0098 / +0.0092 / +0.0114; part1a
`98d80635…`, part1b `34284e45…`).

SM-H is the same P3d_H specification refitted on the Oct-Dec rows. It asks whether SM-H beats the incumbent
fallback in Oct-Dec. The incumbent fallback is MG-2's frozen P3d_N state, the part MG-3 would otherwise serve.

- **SM-H selected:** MG-3's 13-15 uses SM-H.
- **Otherwise:** MG-3's 13-15 falls back to MG-2's P3d_N. MG-3 then equals MG-2 at 13-15 and differs only at
  07-12.

The decision is one look and is final for this lever.

## 1. Kill check (done before this rule)

- **No prior season-matched-H row.** I grepped "season-matched", "season matched", "SM-H" and "SM-L6" in:
  - `EXHAUSTION_REGISTER.md` (X1-X37 and L1-L15);
  - the findings digest and established findings;
  - `CAMPAIGN_LEDGER.md` and `DEV_WINDOW_LEDGER.md` (`claude/l2-dev-ledger-rows-20261026`);
  - the lever inventory `C:\t\inv\lever_inventory.md`;
  - `WORKSTATION_STATE.md`, including the 10-25 and 10-26 kills (R-L, R-L2, R-P).

  No season-matched P3d_H or any season-matched 13-16 refit has been run or killed.
- **Register family.** The family is L7 "Per-market / per-season specialisation" (EXHAUSTION_REGISTER line 262),
  status Open.
- **Row 15 is a different object.** Row 15 (L7 / row 24) is the production season-matched retrain lane, waived
  for the 12-21 decision. SM-H is not that lane.
- **Precedent.** SM-L6, L3 rule `81649748…`, row 46 (`claude/l3-dev-ledger-rows-20261025`; numbered 41 before the 10-26 renumbering).
- **Same-day kills.** The R-P kill (dev 13-16, NBH centre) and the R-L2 kill (07-12) are other inputs, so they
  are not this lever.

## 2. Rows (history only)

**Records.** `C:\t\l2\records`, centres 2026-10-10, 10-25, 11-09, 11-24 and 12-09, the 11 US markets (R0_MARKETS),
local cutoff hours 13, 14 and 15.
- Every target date must fall in 2021-01-01..2025-12-31 and in months 10-12, else the run refuses.
- Rows are built by `pooled_frame` with `DEV_KEEP_X` (the P3d training frame).
- No 2026 row and nothing dated after 2025-12-31 is read.
- Centre 12-24 is not used.

**NBM anchor.** `attach_training_nbm` reads L9's corpus `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl`. The run
binds its sha256 `1ae4bf52…`. The forecast_high fallback count is reported; CS-1 found it to be 0 in Oct-Dec.

**HRRR.** L13's corpus `C:\t\l13\hrrr`, read with `rk_hrrr_columns` as R-K fitted it:
- nearest cell, hours 13-15;
- a `day_filter` that keeps only local dates in 2021-2025, months 10-12;
- k_max, k_gap against the row's NBM anchor, and k_tcdc;
- the corpus files bound at load: manifest `409f6f91…`, selections `055add5a…`, stations `52e8bb5f…`.

A row without a covered selection keeps NaN extras and k_miss = 1, as in R-K.

**Data answer (pre-run).** CS-1 (1b) counts the Oct-Dec 13-16 rows as follows:
- 2021-2024: 3,300 each; 2025: 3,296; 75 dates per year;
- HRRR-covered: 16,482 of 16,496.

So the training side holds HRRR 13-16 for Oct-Dec 2021-25 and no backfill is needed. The run records the exact
13-15 counts per year and the coverage.

## 3. Arms

| Arm | What | Fit |
| --- | --- | --- |
| `SM_H` (decides) | P3d_H spec: `fit_pooled(market_id=False, doy=True, raw_columns=False, simple=False, extra_hgb=(k_max, k_gap, k_tcdc))`, the fixed HGB_PARAMS | blocked LOYO per hour on the Oct-Dec rows of the other four years |
| `P3d_N` (comparator) | MG-2's frozen P3d_N state `C:/t/mg2/p3d_n_ctl/state/p3d_n_state.pkl`, sha256 `dff5d797…` bound at load, served by `state_distribution` (its own buckets, centres and season map, unchanged) | none (frozen) |
| `SM_N` (reported only) | P3d_N spec (`simple=False`, no extras) | the same LOYO as SM_H |

- **LOYO buckets.** The LOYO arms use, per market, the sorted union of the bucket spaces of that market's five
  Oct-Dec record files. The climatology mix uses the fold's training labels (`_rung_entry`).
- **Leakage note.** The frozen comparator saw the held-out year's Aug-Sep rows in training. It never saw an
  Oct-Dec row. This can only favour the comparator.

## 4. Score

**Brier.** Brier = sum_k p_k² − 2 p_y + 1 for every arm on identical rows. This is CS-1's form; the label need not
be in the support. Log loss is reported only.

**Excluded rows.** A row where the frozen P3d_N has no observation input (high_so_far or current_temp not finite)
is excluded from every arm. The count is reported.

**Summary.** The summary uses `rg_loyo_summary`: a date-clustered bootstrap, 2,000 draws, seed 20261024, the
pooled group "13-15" plus each hour.
- The decision pair is `SM_H − P3d_N`.
- The other pairs are reported only: `SM_N − P3d_N` and `SM_H − SM_N`.

## 5. Checks (a failure stops the run; it is not a kill)

1. **Inputs.** All 55 record files are present.
   - Every target year is 2021-2025 and every month is 10-12.
   - The HRRR training coverage at 13-15 is ≥ 0.95.
   - The R-K integrity checks of `rk_parity_training` pass: no identity mismatch used, no TMP out of range, no PIT
     or window violation, no snapshot mismatch.
2. **Comparator control.** For each of hours 13, 14 and 15, the frozen P3d_N mean Brier over the rows scored here
   must equal CS-1 part1a `periods.oct_dec.by.hXX.brier_part`, and the row count must equal `n_rows`.
   - The tolerance is 1e-9.
   - The part1a file is bound at sha256
     `98d80635666fafca107072b8fae2026b8924a6a8500c2968c599807e246166b7`.
   - The reference values are h13 0.7085570141394979, h14 0.5862480806362578 and h15 0.4193016212506275, each on
     4,124 rows.

## 6. Decision (pre-declared)

- **SM-H is selected** if `SM_H − P3d_N | 13-15 | brier` has a 95% upper bound below 0.
- **Otherwise MG-3's 13-15 falls back to P3d_N.**

Nothing else changes the decision: not a per-hour result, and not log loss.

## 7. After the decision (stated now, not part of the look)

- **Power.** The power for the chosen arm is recomputed with `C:\t\l2\mg3\size_transfer.py`.
  - If SM-H is selected, the SM_H − P3d_N 13-15 transfer from this run replaces CS-1's H − N.
  - Otherwise the 13-15 contribution is zero.
  - CS-1 (1c)'s 07-12 delta is folded in when it lands.
- **If SM-H is selected,** its served state is fitted once on all Oct-Dec 2021-25 rows by this specification. It
  is frozen under a separate MG-3 binding note with its own control. MG3-DC-1 is not edited by this rule.
- **The ledger.** Row 48 is filled with the result and this rule's sha.

## 8. Mechanics

- **Code.** `weather.calibration.pooled_residual_model.sm_h_loyo`, CLI `sm-h-loyo`. The constant
  `SM_H_RULE_SHA256` holds this file's sha256.
- **Run.** One run through `scripts/ops/workstation_heavy.ps1 -Queue`.
- **Output.** `C:\t\l2\smh\loyo`, write-once: `sm_h_loyo_audit.json` and `loyo_rows.jsonl`.
