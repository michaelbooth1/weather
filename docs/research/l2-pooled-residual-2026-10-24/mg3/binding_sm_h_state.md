# MG-3 SM-H binding note: the served SM-H state for 13-15 (rule, written before the fit)

Lane L2, 2026-10-27. Rule SM-H `fca2bb1179b601ac4fe142fa17855fea095e10850e1501eb1a478f4a9b655e4d` (`rule_sm_h.md`)
§7, as amended by clarification SMH-1 `b30078031375b3ab77db791124ec24e6568035c25f1696c3c7d54d98cc67e891`. Master
accepted both results on 10-27 (via the coordinator).

This note is hashed and pushed **before the freeze fit**. Dev-window ledger row 52
(`claude/l2-dev-ledger-rows-20261026`) is written PENDING before the run.

- **Evidence class:** a freeze plus an identity control. Nothing is scored for a decision, and nothing is
  re-decided.
- **Data:** 2021-25 Oct-Dec training labels only. No 2026 row is read, and no outcome, label, price or market row
  is read.
- **MG3-DC-1:** this note does not edit it.

## 0. What was decided (the basis; not re-opened)

SMH-1 (ledger row 51, audit `fba6d019870d882c9e58a77b80f92c7696b0a6e1d7051fddd6af20b05a51cfa7`) selected SM-H for
MG-3's 13-15. The decision pair was `SM_H − P3d_N_fwd | 13-15 | brier`: −0.01273 [−0.01625, −0.00936] on 12,372
rows. That pair compares against the served MG-2 arm (`c6cc39f7`'s forward spec, blocked LOYO).

By hour (SM_H − P3d_N_fwd, Brier):

| Hour | Estimate | 95% interval |
| --- | --- | --- |
| h13 | −0.0264 | [−0.0316, −0.0213] |
| h14 | −0.0147 | [−0.0194, −0.0096] |
| h15 | +0.0029 | [−0.0019, +0.0080] |

**Disclosure: h15 is unresolved.** Its point estimate is slightly positive and its interval spans 0, so this
history does not show SM-H better than the served P3d_N at h15 alone.
- The rule decides on the pooled 13-15 group only. h15 is therefore not a decision input, and this note does not
  carve it out.
- MG-3 serves SM-H at h13, h14 and h15 alike.
- Any h15-only change needs its own rule.

The earlier SM-H figure −0.0669 [−0.0744, −0.0598] is against the dev state `dff5d797` and stays recorded as such
(ledger row 48, SUPERSEDED by row 51).

## 1. What is fitted (exactly the SM_H arm that was scored)

**Arm.** `SM_H` = `RK_ARMS["P3d_H"]`, i.e.
`_rung_entry(train, simple=False, extra_hgb=("k_max", "k_gap", "k_tcdc"))`. It is fitted per local hour 13, 14
and 15, pooled over the 11 R0 markets. This is the same specification, code path and hyperparameters as the SM-H
run (`sm_h_rows`).

**Training rows.** These are the SM-H run's frame, built exactly as `sm_h_loyo` built it, with every year
included (no year is held out):
- `sm_h_frame(C:\t\l2\records)`: centres 10-10, 10-25, 11-09, 11-24 and 12-09; target dates 2021-25, months
  10-12 only; hours 13-15;
- `attach_training_nbm` with the L9 NBM corpus
  `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd`;
- `rk_training_columns` from L13's HRRR `C:\t\l13\hrrr`, nearest cell, with `sm_h_day_filter`. The input shas are:
  - manifest `409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935`;
  - selections `055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75`;
  - stations `52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3`.

A training row dated 2026 or later, or outside months 10-12, refuses the fit. A fit whose control fails (§3) is
not repaired by retuning; it stops.

## 2. What is frozen

The state uses schema `mg3_p3d_h_state/1`, the same layout and serve math as `rule_mg3_p3dh_state.md` §2
(`9e63899d…`), so the existing loader and serve math read it unchanged. The fields that differ:

| Field | Value |
| --- | --- |
| `arm` | "P3d_H" (the SM_H arm is the P3d_H specification) |
| `block` | "SM-H 13-15" |
| `centres` | the five Oct-Dec centres above |
| `hours` | 13, 14, 15 only |
| `buckets` | the per-market union of the five Oct-Dec record files' bucket spaces, as scored |
| `conversion` | disabled: SM-H read raw high_so_far and current_temp, as fitted |
| `point_rule` | nearest cell (R-K as fitted) |
| `provenance` | commit, module sha256, this note's sha256, SM-H rule and SMH-1 shas, training row count and years, input shas, HRRR coverage stats, package versions |

**What it replaces, at MG-3 13-15 only.** It replaces the Aug-Sep P3d_H 13-16 state `e891d884…` (MG3-DC-1 §3
table) at hours 13-15, for every market except San Francisco. Unchanged:
- San Francisco 13-16 stays on MG-2's bound arm;
- h16 stays on MG-2's bound arm;
- 07-12, the blend weights and every other hour are unchanged.

**Serve inputs.** These are unchanged from the 13-16 block: the 2026 HRRR k columns by the nearest cell, and the
NBM mean.

**Wiring.** Wiring the new sha into MG-3's release binding (`mg3_release_binding` states) is a separate change.
It is made only after the control passes.

## 3. Identity control (must hold before the state is reported as frozen)

1. **Inputs.** All of these must match:
   - every input sha in §1;
   - the frame's per-year row counts equal the SM-H audit's `counts_by_year` (12,372 rows at 13-15; 2,475 per
     year, 2025 2,472);
   - the HRRR training coverage equals the SM-H audit's `covered_by_year`.
2. **Export parity (every training row).** Reload the state from its file only after its sha256 is checked. Then,
   on **every** training row with a finite high_so_far and current_temp:
   - the distribution from the frozen state's serve math (`mg3_state_distribution`) must equal the in-process
     fit's distribution (`_dist_from_fit`);
   - tolerance: max |Δp| ≤ 1e-9 over the union of buckets.
3. **Fold reproduction (the served builder is the scored specification).** For each hour and held-out year:
   - build a fold state with the same state builder on the other four years' rows;
   - serve the held-out rows from that fold state through `mg3_state_distribution`;
   - compute CS-1 Brier.
   - **PASS** if the keys (hour, year, market, date) equal the SM-H rows `loyo_rows.jsonl`
     `f6f96cbceb3d3435431847470008300725161b5c39215e11a65ef696fb392fd5` with no row missing or extra, and every
     row's Brier equals its `SM_H_brier` to 1e-9.
4. **FAIL** of any check stops the freeze. The state is not bound, and the failure is reported with the first
   differing row. No tolerance, input or code is changed to make it pass without a new ruling.

## 4. Outputs (outside the repository, write-once)

`C:\t\l2\mg3\state_smh\`:
- `p3d_h_state.pkl` and `p3d_h_state.json` (sha256 and provenance);
- `export_parity.json`;
- `fold_control.json`;
- `control.json` (per-check pass and the state sha256).

An existing file refuses the run.

## 5. After the control

- **Power.** The power is recomputed under rule_sm_h §7. The 13-15 transfer is SMH-1's `SM_H − P3d_N_fwd`, which
  replaces CS-1's H − N. CS-1 (1c)'s 07-12 delta and row 49 (b) are folded in when they land.
- **Ledger.** Row 52 is filled with the state sha256 and the control result.

## 6. Mechanics and limits

- **Code.** `weather.calibration.pooled_residual_model.sm_h_freeze_state`, CLI `sm-h-freeze`. The constant
  `SM_H_BINDING_SHA256` holds this file's sha256.
- **Run.** One run through `scripts/ops/workstation_heavy.ps1 -Queue`.
- **Limits.** Data ≤ 2025-12-31 for the fit. No paid data, no new dependency, and no change to MG-2, B, L3's or
  L8's branches.
