# SM-H clarification SMH-1: re-decide SM-H against the served P3d_N (one look)

Lane L2, 2026-10-27. Master accepted L2's comparator fix and suspended SM-H's acceptance. This clarification
amends SM-H rule `fca2bb1179b601ac4fe142fa17855fea095e10850e1501eb1a478f4a9b655e4d` (`rule_sm_h.md`). It is
hashed and pushed before any P3d_N_fwd number exists. Dev-window ledger row 51
(`claude/l2-dev-ledger-rows-20261026`) is written PENDING before the run.

## 1. The defect

SM-H's comparator was MG-2's dev state `dff5d797…`, the Aug-Sep fit used only for MG-2's control replay. MG-2
binds L2's forward state `c6cc39f7…` instead. That state is the Aug-Dec 2021-25 fit, and it is bound by
`C:\t\mg2\control_rule_v3.md` lines 35-45, which also say `dff5d797` "is never bound".

MG-3's 13-15 fallback is MG-2's served arm, so the SM-H decision compared against the wrong object.

- **What is kept.** The SM-H result −0.0669 [−0.0744, −0.0598] stays recorded as "SM_H vs the dev state
  `dff5d797`, not the served arm".
- **What is suspended.** The selection is suspended. MG-3 falls back to P3d_N (`c6cc39f7`) unless this
  re-decision selects SM-H.

## 2. Re-decision (replaces rule_sm_h.md section 6; nothing else in the rule changes)

**Rows.** Only the existing SM-H run's rows are used, and nothing is refitted for SM_H:
- `SM_H` per-row Brier from `C:/t/l2/smh/loyo/loyo_rows.jsonl`, sha256
  `f6f96cbceb3d3435431847470008300725161b5c39215e11a65ef696fb392fd5`, h13-15;
- the comparator `P3d_N_fwd`, defined in C10-sel (`docs/research/l2-pooled-residual-2026-10-24/c10/rule_c10_sel.md`,
  section 3), from that run's `fwd_rows.jsonl`. Its sha256 is read from the C10 audit.

**Preconditions.** The C10 run must have passed all its checks (1-5), and the C10 audit records the
`fwd_rows.jsonl` sha256. If the C10 run is VOID, this re-decision is VOID too.

**Join.** The keys (hour, year, market, date) at 13-15 must be identical in both files, with no row missing or
extra. Otherwise the re-decision is VOID.

**Score.** `SM_H − P3d_N_fwd`, CS-1 Brier form. `rg_loyo_summary`: 2,000 draws, seed 20261024, the pooled group
"13-15" plus each hour.

**Decision.**
- **SM-H is selected for MG-3's 13-15** if the 13-15 95% upper bound is below 0.
- **Otherwise MG-3's 13-15 falls back to P3d_N (`c6cc39f7`).** MG-3 then equals MG-2 at 13-15, unless C10-sel
  adopts SM-N for MG-2.

This is one look.

**Interaction with C10.** If C10-sel adopts SM-N for MG-2, SM-H's comparator is still `P3d_N_fwd`, as
registered here. Any MG-3-versus-new-MG-2 question needs its own rule.

## 3. Mechanics

- **Code.** `weather.calibration.pooled_residual_model.sm_h_redecide`, CLI `sm-h-redecide`. The constant
  `SM_H_CLARIFICATION_1_SHA256` holds this file's sha256.
- **Run.** One run through `scripts/ops/workstation_heavy.ps1 -Queue`, after the C10 run.
- **Output.** `C:\t\l2\smh\redecide\smh1_audit.json`, write-once.
- **After.** The follow-ons in rule_sm_h.md section 7 apply unchanged: power, and the served-state binding note
  only if SM-H is selected. Ledger row 51 is filled with the result.
