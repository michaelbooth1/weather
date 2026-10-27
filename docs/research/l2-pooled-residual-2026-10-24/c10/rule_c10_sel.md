# C10-sel: season-matched P3d_N (SM-N) for MG-2's 13-16 arm against the served P3d_N (history only, one look)

Lane L2, 2026-10-27. Master opened C10 through the coordinator and accepted L2's comparator fix on the same
day. This file is written, hashed and pushed before any SM_N h16 number or any P3d_N_fwd number exists. Dev-window
ledger row 50 (`claude/l2-dev-ledger-rows-20261026`) is written PENDING before the run.

## 0. Question and decision

MG-2 serves P3d_N at 13-16 from L2's forward state `C:\t\l2\forward\state\p3d_n_state.pkl`, sha256
`c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780`. That state has these properties:
- schema `mg2_p3d_n_state/1`, fit_kind forward;
- trained on Aug-Dec 2021-25, 103,609 rows, 9 centres;
- conversion `wu_whole_f_tgroup:half_up`, late_report `last_in_hour`;
- bound by `C:\t\mg2\control_rule_v3.md` lines 35-45.

SM-N is the same P3d_N specification trained on the Oct-Dec rows only.

**Adopt SM-N for MG-2's 13-16 arm if and only if both conditions hold:**
- `SM_N − P3d_N_fwd | 13-16 | brier` has a 95% upper bound below 0; and
- the h16 point estimate of `SM_N − P3d_N_fwd` is ≤ 0.

Otherwise MG-2 keeps P3d_N (`c6cc39f7`), and that is recorded. Nothing else changes the decision.

## 1. Disclosure (what was seen before this rule)

**Seen in the SM-H run** (rule `fca2bb11…`, output `C:/t/l2/smh/loyo`). These figures compare against the
Aug-Sep dev state `dff5d797…`, not the served arm:
- `SM_N − P3d_N(dff5d797)` at 13-15: −0.0519 [−0.0590, −0.0454].
- By hour: h13 −0.0200, h14 −0.0505, h15 −0.0853.

**Seen in CS-1** (L3):
- part1a, the h16 Brier of the frozen dev state `dff5d797` on Oct-Dec: 0.2047.
- part1b, the h16 Brier of the MG-3 P3d_H state.

**Not yet computed:**
- no SM_N h16 number;
- no P3d_N_fwd number at any hour;
- no figure that compares against the served state `c6cc39f7`.

**Expected h16 rows, from the inputs only.** The SM-H frame has 2,475 rows per year at 13-15 (2025: 2,472), i.e.
825 rows per hour (2025: 824). The h16 count is therefore expected to be 825 per year (2025: 824), 4,124 in all.
This matches CS-1's h16 row count.

## 2. Rows (history only)

**Scored rows.** The Oct-Dec rows of the SM-H frame (`sm_h_frame`) at hours 13, 14, 15 and 16:
- records `C:\t\l2\records`, centres 10-10, 10-25, 11-09, 11-24 and 12-09;
- 11 US markets;
- target dates 2021-25, months 10-12 only;
- L9 NBM anchor `1ae4bf52…` via `attach_training_nbm`.

A row without a finite high_so_far or current_temp is excluded from every arm, and the count is reported.
Nothing dated 2026, and nothing after 2025-12-31, is read.

## 3. Arms

| Arm | What | Fit |
| --- | --- | --- |
| `SM_N` (candidate) | P3d_N spec `_rung_entry(simple=False)`, as in the SM-H run; LOYO buckets = per-market union of the five Oct-Dec record files' bucket spaces | blocked LOYO per hour on the Oct-Dec rows of the other four years |
| `P3d_N_fwd` (comparator) | the forward-fit spec: the same `fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")` call as `forward_fit`, on the Aug-Dec rows of `forward_training_frame` (all 9 centres) with the L9 NBM anchor | blocked LOYO per hour: each fold drops the held-out year's Aug-Dec rows |
| `P3d_N_dev` (reported only) | the frozen dev state `dff5d797…` | none |

**How P3d_N_fwd is served.** Each fold is served through the same path as the served state:
1. Load `c6cc39f7` (sha-checked).
2. Replace its `hours[h]` entries with the fold fits. Each entry is built exactly as `forward_fit` builds it:
   - `state_mean_dict`, scale, z;
   - `train_y` from the fold's training rows.
3. Leave every other field unchanged: centres, season map, coords, buckets, constants, conversion
   `wu_whole_f_tgroup:half_up`, and late_report.
4. Score each scored row with `state_distribution`.

The conversion acts on the history rows' high_so_far and current_temp, exactly as at serve time.

## 4. Score

**Brier.** Brier = sum_k p_k² − 2 p_y + 1, CS-1's form, for every arm on identical rows. Log loss is reported
only.

**Summary.** `rg_loyo_summary`: date-clustered bootstrap, 2,000 draws, seed 20261024, the pooled group "13-16"
plus each hour.
- The decision pair is `SM_N − P3d_N_fwd`.
- The other pairs are reported only: `SM_N − P3d_N_dev` and `P3d_N_fwd − P3d_N_dev`.

## 5. Checks (any failure makes the run VOID, and no score is read)

1. **Inputs.** All 55 Oct-Dec and 44 Aug-Sep record files are present.
   - The forward frame's years are 2021-25.
   - The forward frame has 103,609 rows, as recorded in `c6cc39f7`'s provenance.
   - The scored-row keys (hour, year, market, date) at 13-15 equal the SM-H run's rows, `loyo_rows.jsonl`
     `f6f96cbceb3d3435431847470008300725161b5c39215e11a65ef696fb392fd5`.
2. **Comparator control, tier 1 (state bytes).** Tier 1 cannot be reached, for two reasons:
   - `c6cc39f7`'s provenance embeds the producing module's sha256 `52c497a9…` and commit `73675b78…`. The
     current module differs.
   - Re-pickling the loaded state does not reproduce its bytes: the round-trip sha256 is `12062716…`, measured
     on the state file alone, with no row read.

   So tier 2 binds.
3. **Comparator control, tier 2 (export parity on every scored row).**
   - Refit the same call on all five years.
   - Build the state shell as in section 3.
   - On EVERY scored Oct-Dec row at 13-16, compare its distribution with `c6cc39f7`'s `state_distribution`.
   - Pass if the max abs difference over the union of buckets is ≤ 1e-9.
4. **Row-identity control.** `P3d_N_dev` per-hour mean Brier and row count must equal CS-1 part1a
   `periods.oct_dec.by.hXX` at h13-16, to 1e-12.
   - Part1a sha `98d80635666fafca107072b8fae2026b8924a6a8500c2968c599807e246166b7`.
   - Reference h16 value 0.20471494020808334, on 4,124 rows.
5. **SM_N reproduction.** `SM_N` at 13-15 must reproduce the SM-H run's `SM_N_brier` on every row, to 1e-12.

## 6. Outputs and what follows

**Outputs.** `C:\t\l2\c10\loyo`, write-once:
- `c10_audit.json`;
- `loyo_rows.jsonl` (all arms, 13-16);
- `fwd_rows.jsonl` (P3d_N_fwd per row, 13-16). SM-H clarification SMH-1 reads this file for its re-decision.

**If SM-N is adopted.** The served SM-N state is built the way `800072c7` was built:
- one final fit on all Oct-Dec 2021-25 rows;
- schema `mg2_p3d_n_state/1`;
- its own control receipt and state sha.

The LOYO fold rows of this run are PRIMARY for any dev or cool-season read, as in row 49.

**Code and run.** `weather.calibration.pooled_residual_model.c10_sel`, CLI `c10-sel`, constant
`C10_RULE_SHA256`. One run through `scripts/ops/workstation_heavy.ps1 -Queue`. Ledger row 50 is filled with the
result.
