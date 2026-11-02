# FINAL RULE: trailing excess-bias centre correction on P3d_N_fix (K row 112, count 211), frozen before G0

- Lane L47. Supersedes the draft `rule_x36_v5_correction_DRAFT.md` (sha256 `def19188c5c923a734d9f7ceba6b68d8ebe22d87d31229dbcfef453012d5cdfd`),
  which stays unchanged.
- This file is frozen once its sha256 is reported. Any change is a new file with a new sha.
- Gates run fail-fast, in order. Each result goes to the coordinator before the next gate.

> **X30 caveat, front and centre.** A pooled LOYO intercept win can be a bias correction that reverses on 2026. A
> gate-1 pass is therefore not evidence of information. Only the dev refutation (G2) can support the candidate, and
> even a G2 pass is a dev-selection result, not an edge.

## Status of the family (master rulings, 2026-11-01)

1. **X36's literal reopen does NOT stand.** X36's quantity is a fitted residual shift, and the raw ±1 °F line also
   fires inside the training era (C row 111, `results_x36_v5.md`).
2. **The trailing-window correction is a DISTINCT sub-family, reopened by master ruling**, for these reasons:
   - X36's "rolling window" bar was a closure by extension from a static-shift kill. No rolling window was ever
     measured.
   - The 2026 raw NBM bias is strongly seasonal and moves by year. That is the condition under which a static
     shift fails and a trailing one might work.
   - It is the standard MOS-style decaying-average correction, using strictly earlier days only (point-in-time).

## Data rule

- Nothing dated >= 2026-05-27 is touched, except dev 2026-08-15..09-29 at G2, on the coordinator's go.
- Panel dates (05-27..07-30) are never read.
- G2's trailing windows need labels from 2026-08-01 onward only.

## Candidate

For market m and target date t:
- d(m, u) = NBP 07Z mean − WU high on date u.
- b_recent(m, t; W) = mean of d over the market's W most recent target dates strictly before t that have both an
  NBP 07Z row and a settled WU label.
- b_train(m, s) = the 2021-25 raw mean of d for market m and season s (L9 corpus `1ae4bf52…`; context table of
  `fit.json` `6fe1f123…`).
- Model candidate: mu' = mu − λ · clip(b_recent − b_train, ±3 °F), where mu is P3d_N_fix's centre. Width is
  unchanged. The rule-4 floor is applied after the shift.
- Grid: W ∈ {7, 14}; λ ∈ {0, 0.25, 0.5, 0.75, 1}. Ties go to the smaller λ, then the smaller W.

## G0: descriptive, already-fetched data only, no model

- **Data:** the 2026-01-01..05-26 corpus (`corpus_2026.jsonl` `d59718a7…`) and WU labels, read through the C row
  111 module's window-refusing loaders. No new fetch.
- **Evaluation set:** dates 2026-01-15..05-26, so that W = 14 has a full window. Both W use the same set.
- **Arms, on the raw NBP mean.** There is no model here, so the raw mean is corrected by the full recent bias,
  λ = 1:
  - RAW: NBP mean.
  - T7 / T14: NBP mean − clip(b_recent(W), ±3).
  - SEAS: NBP mean − b_train(m, all seasons). Training covers only Aug-Dec, so Jan-May has no matching season,
    and the all-season Aug-Dec mean per market is the baseline.
- **Metrics:** MAE and mean error (ME) against the WU high, per market × month and pooled. Pooled paired
  differences ΔMAE(T_W − RAW) and ΔMAE(T_W − SEAS), each with a 95% date bootstrap (2000 draws, seed 20261024).
- **STOP and PARK** if no W has a pooled ΔMAE(T_W − RAW) point < 0 with a 95% upper bound < 0.
- Otherwise G0 passes. ΔMAE versus SEAS and the per-market and per-month cells are reported, never decisive.

## G1: LOYO 2021-25 Aug 15..Sep 29, 07-12, nested (via `workstation_heavy.ps1 -Queue`)

- W and λ are picked in the inner loop.
- Trailing windows use L9 corpus dates from Aug 1, so W ≤ 14 is always available.
- **KILL if Δ Brier (candidate − P3d_N_fix) point is not < -0.0005.**
- Positive control first: P3d_N_fix BASE reproduces R-K's 07-12 rows to 1e-9. The rows file and sha are named in
  the G1 module before the run. If the control fails, STOP.
- The module needs master's named allowlist approval. L47 does not edit `scripts/ops/workload_admission.ps1`.
- Disclosure: in Aug-Sep 2021-25 the training-era excess is about 0 by construction, so G1 is a weak test.

## G2: dev refutation 2026-08-15..09-29, 07-12 (on the coordinator's go after G1)

- W and λ are frozen from G1.
- **PASS only if the dev ΔR 95% upper bound < 0.** The dev MDE is disclosed.
- L6 / MG-2 comparisons come only after a pass.

## Constraints

- B-bound modules are imported read-only. No training on dev or panel dates.
- At serve, b_recent needs a settled WU label for each of the previous W days. That holds after the WU print, so
  the serve path must bind each label at its settlement instant.
- Ruled-out outcomes are archived under `C:\archive\ruled-out\` with SHA256SUMS, a README and an INDEX line.
