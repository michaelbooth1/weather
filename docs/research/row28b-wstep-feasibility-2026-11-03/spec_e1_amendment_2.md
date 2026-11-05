# E1 spec amendment 2: descriptive projected power at N = 45, 80 and 100 (create-only)

Lane L59, WS, 2026-11-04, after master's second GO (master 2026-11-04 about 11:50) and before the score stage.
It amends `spec_e1_0712_descriptive.md` (sha256
`0496eaa962b5911587db5a345879f328e6020fcefd251bf8e3d0ed547d28bdd2`) and `spec_e1_amendment_1.md` (sha256
`00c1081464f13cc3d28df72e0ab655faf498c02f04a41e93ee4d0698b07c6a0e`). Neither file is edited. The label is
unchanged: **POST-HOC-FILLED DESCRIPTIVE**. When this file is committed, no E1 label, outcome, Brier value or loss
has been computed or read.

## B1. Added output: projected power at N = 45, 80 and 100 (DESCRIPTIVE, for sizing 4b only)

- **What.** The projected power of a forward 07-12 B−S arm at N = 45, N = 80 and N = 100 dates.
- **Formula.** The rules 16 + 19 projection of E3 condition 2, with only N varied. Its inputs are those E3
  condition 2 names, all taken from E1's own score result:
  - σ = 1.5 × σ_d;
  - VIF = max(1, κ_AR, κ_block3²), where κ_AR = (1+ρ)/(1−ρ) for the lag-1 ρ;
  - futility inflation ×1.07;
  - delta = d̄ / 2 (rule 6).

  The closed form is the one the E1 source note uses (`extension_0712_feasibility.md` (b): MDE80 =
  1.07 × 2.802 × σ × √VIF / √N):
  - SE_N = 1.07 × σ × √VIF / √N;
  - power_N = Φ(−delta / SE_N − 1.96), with a negative delta meaning B is better.
- **Inputs used.** Only quantities that `row28_run_v13.py` (sha256
  `d23980b5123761ef0cfe46afa60274063aee66c84eb58169a55cb283a847f61d`) already writes in its score result:
  `d_bar`, `sigma_d`, `rho_lag1`, `kappa_ar` and `kappa_block3`.
- **Where.** The computation runs outside v13. A separate, versioned light script reads only the score result JSON
  and writes one JSON; its sha256 is recorded with the result. v13 is not changed.
- **Use.** Descriptive only, for sizing 4b. The N = 80 and N = 100 values decide nothing.

## B2. Unchanged

- **The E3 ADD / DON'T ADD rule is UNCHANGED**, conditions 1 and 2 as written in `spec_e1_0712_descriptive.md`.
  - Condition 2 is evaluated at N = 45 only; the N = 45 value in B1 is that same number.
  - The N = 80 and N = 100 numbers never enter E3.
- No decision rule, threshold, population or E3 condition changes.
- Also unchanged:
  - the arms, folds and rows;
  - the integrity rules (caps and imputation reported as FLAGs, under RULING_E1_CAPS, accepted by master);
  - the S definition and the LOYO N states (amendment 1);
  - every other output.
