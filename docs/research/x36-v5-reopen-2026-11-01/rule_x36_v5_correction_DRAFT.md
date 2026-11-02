# DRAFT, NOT FROZEN, NOT RUN: trailing excess-bias centre correction on P3d_N_fix (X36 reopen candidate)

Status: drafted by L47 under C row 111 step 4, because the frozen decision line fired (Denver, Los Angeles).
- **Do not run.** It needs master's ruling on whether the reopen stands (see disclosure 1 of
  `results_x36_v5.md`), then a frozen revision with a sha and a go.
- Ledger row: TBD (coordinator assigns).
- No K row exists. No candidate has been scored.

## Why this form

The results favour a 2026 / year effect over a version effect: v4.3 in 2026 is already warm, and within May v5.0
minus v4.3 is +0.00. A v5.0 version term would therefore model the wrong thing. A trailing point-in-time bias
window adapts to a year or season drift whatever its cause.

The model already absorbs the training-era raw bias. So the correction targets only the **excess** of the recent
raw bias over the training-era raw bias for the same market and season. This puts it on X36's residual scale.

## Candidate

For market m and target date t:
- b_recent(m, t) is the mean of (NBP 07Z mean − WU high) over the market's previous W target dates. All of them
  must be strictly before t, have a settled WU label and have an NBP 07Z row.
- b_train(m, s) is the 2021-25 raw mean for market m and season s, from L9's corpus. This is the context table
  in `fit.json`.
- The candidate centre is mu' = mu − λ · clip(b_recent − b_train, ±3 °F). Width is unchanged. The floor
  (rule 4) is applied after the shift, exactly as now.

The grid is W ∈ {7, 14} and λ ∈ {0, 0.25, 0.5, 0.75, 1}. Ties go to the smaller λ, then the smaller W.

## Gates

1. **LOYO 2021-25 Aug 15..Sep 29, 07-12, nested.**
   - W and λ are picked in the inner loop.
   - Trailing windows use L9 corpus dates from Aug 1 onward, so W ≤ 14 is always available from Aug 15.
   - **KILL if Δ Brier (candidate − P3d_N_fix) point is not < -0.0005.** This mirrors X36 gate 1.
2. **Dev refutation, 2026-08-15..09-29, 07-12** (dev is the refutation gate, per the brief).
   - W and λ are frozen from gate 1.
   - Trailing windows need labels from 2026-08-01 onward only, never panel dates (05-27..07-30), because
     W ≤ 14 starts at 08-15.
   - **PASS only if the dev ΔR upper bound < 0**, with the dev MDE disclosed.
   - L6 / MG-2 comparisons come only after a pass.
3. Before any scored read, a positive control: P3d_N_fix BASE reproduces R-K / R-M's rows (sha recorded in the
   frozen revision) to 1e-9.

## Constraints

- No training on dev or panel dates. B-bound modules are imported read-only. Heavy runs go only through
  `workstation_heavy.ps1 -Queue`, after master names the module for the allowlist.
- At serve, b_recent needs a settled WU label for each of the previous W days. That holds after the WU print,
  but the serve path must bind it at the label's settlement instant, not at the target-day cutoff.
- Disclosures carried over:
  - (a) X36's kill text bars "rolling window" variants. This candidate exists only because X36's own reopen
    condition fired, and that firing is on the raw quantity (disclosure 1).
  - (b) Jan-May 2026 is outside every training window. Gate 1 sees only Aug-Sep, where the training-era excess
    is about 0 by construction. So gate 1 is a weak test, and dev carries the decision.
  - (c) A pooled intercept-like win is a bias correction, not information (X30).
