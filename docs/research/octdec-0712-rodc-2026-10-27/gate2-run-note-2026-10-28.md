# R-ODC gate 2 run note (2026-10-28)

Pinned run of R-ODC G2 under nested LOYO (rule sha256
`41dad9d7293e6c7cbab0820a05b548854dd8684fd513d498d5555cb8999a025f`, Clarification 3).
Ledger row 69.

- Code: branch `claude/rodc-gate2-20261028`, tip
  `188d5c382ac041a6ae276eebcac2b957463f885a` (clean worktree), subcommand
  `python -m weather.calibration.cool_season_audit rodc-gate2`.
- Launched once through `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -Queue
  -MinAvailableMemoryGB 3`; argv base64 sha256
  `4af0025a2b6ce5f76ac652da472946ad8b4a42ad8784c720e6aebfbbc3bd53ff`. Exit 0.
- Outputs (local, not tracked): `gate2.json` sha256
  `255bee570fc1e5f96536277f0a9be5e01c27e4b99ea350c292fdf1335f3c8ed8`,
  `gate2_rows.csv.gz` sha256
  `969aa4ae462468bc5b4c58f2569a2117a9b479ff47f7d63a460729c0bca953b1`.
- low_so_far source: L9 ladder caches (Oct-Dec centres), manifest sha256
  `f33bffb157761b3b85f34a9b43dcbafdb2f76660558f1a6753f54f00293512c9`.

## Verdict

**PASS.** NEST vs G1 pooled dR = -0.000876, date-clustered 95% CI
[-0.001452, -0.000286] (4,124 cells, 375 dates, 24,734 rows; 2,000 draws,
seed 20261027). G2 was selected in all 5 outer folds, so NEST equals plain G2.

| Outer year | Inner pooled mean Brier(G2)-Brier(G1) | Selected | dR (NEST vs G1) | 95% CI |
| --- | --- | --- | --- | --- |
| 2021 | -0.000234 | G2 | -0.001405 | [-0.002627, -0.000251] |
| 2022 | -0.000416 | G2 | -0.000348 | [-0.001778, +0.001143] |
| 2023 | -0.000467 | G2 | -0.001162 | [-0.002500, +0.000088] |
| 2024 | -0.000762 | G2 | -0.001111 | [-0.002487, +0.000239] |
| 2025 | -0.000773 | G2 | -0.000349 | [-0.001503, +0.000806] |

All five per-year point estimates are negative; only 2021 excludes zero alone.
By month: Oct -0.000782, Nov -0.001379 (CI excludes 0), Dec -0.000103.

## Refusal checks (Clarification 3 approval)

- (1) Running min: PASS.
- (2) Bounds (low_so_far <= current temp, low_so_far <= high_so_far): PASS.
- (3) Window: **UNVERIFIED assumption, disclosed.** The ladder caches carry no
  observation timestamps, so the at-or-before-h:00-on-date-D window cannot be
  asserted from the cache. It rests on overnight_lows' `minute_of_day <= cutoff`
  filter over date-D rows.
- (4) Join coverage, reported before the fit: train 24,744/24,744, score
  24,744/24,744. PASS.
- Gate 1 reproduction control: max abs diff 0.0 over 24,744 rows (comp, g1, mg1,
  p3d_comp, p3d_g1); determinism max abs 0.0.

## Reported only, never gating

| Comparison | dR | 95% CI |
| --- | --- | --- |
| NEST vs COMP 0e89b32d (vs the Aug-Sep-centred frozen blend, item 341) | -0.02564 | [-0.02842, -0.02282] |
| NEST vs COMP-800072c7 (IN-SAMPLE season-matched L6 nowcasts) | -0.02055 | [-0.02346, -0.01761] |
| NEST vs MG-1 | -0.04990 | [-0.05395, -0.04542] |
| G1 vs COMP 0e89b32d | -0.02479 | [-0.02762, -0.02196] |

Plain G2 vs G1 equals the headline because every fold selected G2.

This is a dev-window research result. It is not a promotion, a serving change,
or evidence of edge over market prices.
