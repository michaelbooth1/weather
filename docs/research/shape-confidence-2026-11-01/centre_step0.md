# L47 centre-bias step 0: kill check, result STOP (family closed) (2026-11-01)

The master ruling made the centre-bias step 0 a GO, conditional on a prior kill check. The check greps
EXHAUSTION_REGISTER, STATE_OF_PLAY, ESTABLISHED_FINDINGS (EF), RETRACTED_AND_FALSE_LEADS (RF) and the digest,
both by name and by family. Repo docs were read at base `3f3fe50a1f61ac37f225839b2bdc8f9fd0a1dcbf`.
**Result: the centre-correction family is closed for every arm in question.** Per the ruling, no question was
computed, no data was read and no script was run. Ledger row: none.

## Hits

| Family named in the ruling | Where | What it closes or answers |
| --- | --- | --- |
| Per-market / pooled additive centre shift on NBM-anchored arms | Register X36 (R-M, L11), S28 | KILL at gate 1, +0.00013 [-0.00027, +0.00055] on P3d_N_fix at 07-12. Fitted per-market shifts are all within ±0.4 °F in 2021-25. Closed for P3d_N_fix, L6, the MG-1 family and the P3d_N family. "No other grid, hour block, shrinkage, objective, market grouping or rolling window runs under any rung name." Reopen only if a new training corpus shows a fitted per-market shift beyond ±1 °F. |
| Per-market debias, MG-1 | Register X8, EF §10ah | L5 A1 -0.0001 [-0.0042, +0.0045]: KILL. |
| "Cool bias not correctable" / base-HGB cool root cause | EF §2, digest | Seasonal-coverage root cause. "Do not implement a serving-side offset" because the bias is heterogeneous by market. This is about the base HGB, not the NBM-anchored arms. |
| Centre-displacement mechanism | EF §2, RF ("Blindness as the cause" REJECTED) | Floor truncation yanks a too-cool centre warm. EF says to trace it rather than infer it. This was measured on the old served HGB surface (displacement -0.30 bands cooler). |
| MG-1 +0.84 °F warm bias | `docs/research/morning-loss-diagnosis-2026-10-24.md`, Analysis 5 (branch `claude/morning-loss-diagnosis-20261024`; cited in EF §10ah) | At 07-12 on dev (43 dates): the MG-1 centre is +0.84 °F against the outcome, NBM v2 mean +0.74, NBM v2 p50 +0.83, NWS grid high +0.63, market +0.02. |
| X centre rows | Register X27 (R-H, not ruled out), X30 (R-P: "a pooled LOYO intercept win is a bias correction, not information"), X35 / digest (2021-25 vs 2026 corpus difference, not the dev anchor) | X27 is the source of the offset that step 0 found. X30 and X35 bar re-entering the family through an intercept. |

## What this already answers of questions 1-4, without new reads

1. **Warm against the outcome, not only the market.** The morning-loss Analysis 5 table above already measured
   this at 07-12 dev: MG-1 +0.84 °F, against the market's +0.02. It is inherited from the NBM read (NBM v2
   mean +0.74). It was not measured per tercile or for P3d/L6.
2. **Floor truncation.** Not traced for P3d/L6. At 07-12 the floor is usually far below the centre, and the
   R-H atlas excess is "full size before any daytime observation" (EF §10ag). That argues against truncation
   at 07-12. This is inference, not a trace.
3. **Component.** The morning-loss table points to the NBM read. It does not separate the HGB residual or the
   L6 state.
4. **Hard tercile, both arms.** Step 0 measured +0.21 bands for P3d in T2 and a +0.06-band pooled offset for
   L6. The L6 tercile breakdown is in `step0.json`.

## Why STOP rather than run descriptively

The ruling says: "If the family is closed, STOP and report." Any lever from questions 1-4 would be a centre
shift on an NBM-anchored arm, by market, pooled or by tercile, which X36 closes under any rung name. X36's
history shift (±0.4 °F) is much smaller than the dev warm bias (about +0.8 °F). That is the 2021-25 vs 2026
corpus difference also noted under X35. A centre correction fitted on dev alone would be in-sample dev
selection, and X30's caveat applies to it.

What master could still choose to run, purely descriptively and without opening a lever:
- question 2 as the trace that EF §2 asks for, on P3d/L6 at 13-16, where the floor binds;
- a 2026 vs 2021-25 NBM-bias comparison, input-only, for X36's reopen test.

Neither has been run.
