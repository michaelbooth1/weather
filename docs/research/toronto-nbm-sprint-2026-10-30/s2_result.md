# Toronto NBM sprint: S2 result (lane L8, 2026-10-30)

This applies `rule_toronto_nbm.md` §3 under clarifications 3 (`5dc5f1935`) and 4 (`069b2c681`), both
committed before any arm fit. History only (2021-25); no dev window, dev label or price has been read.

## Gate: Aug-Sep 2021-25, hours 07..16

- **Rows:** 3,049 hour rows on 305 dates. One row was dropped because the 07Z NBP had not been received by
  t.
- **Incumbent:** P3d_N_fix-CYYZ, mean Brier 0.614913. This reproduces clarification 3 exactly.

d = arm − incumbent. Date-clustered intervals, 2,000 draws, seed 20261024:

| Arm | Mean Brier | d Brier [95%] | one-sided p | Holm | d log [95%] (descriptive) |
| --- | --- | --- | --- | --- | --- |
| **B** (A + NBH rest-of-day max) | 0.581515 | −0.0334 [−0.0468, −0.0198] | 0.000 (< 1/2000) | **PASS** (1st, < 0.025) | −0.1175 [−0.1643, −0.0719] |
| **A** (newest NBP + TXNSD) | 0.605196 | −0.0097 [−0.0159, −0.0038] | 0.003 | **PASS** (2nd, < 0.05) | −0.0285 [−0.0457, −0.0126] |
| no-NBM a1 (reference) | 0.672447 | +0.0575 [+0.0398, +0.0743] | 1.000 | not gating | +0.2678 |

**S2 verdict: Arm A PASS, Arm B PASS.** Both go to P0.

**Arm A is a spec test only.** At every scored hour (07..16) the newest NBP received by t was the D 07Z
cycle (3,049 of 3,049 rows). Arm A's N is therefore the incumbent's N. Arm A differs only by TXNSD as an HGB
residual and scale input, so its gain is a TXNSD/spec gain, not a timing gain. Arm B carries the new
information (NBH).

**Per hour, Brier d for B and for A:**

| Hour | 07 | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | −0.067 | −0.051 | −0.056 | −0.040 | −0.028 | −0.039 | −0.032 | −0.011 | −0.014 | +0.004 |
| A | −0.017 | −0.021 | −0.017 | −0.015 | −0.008 | −0.005 | −0.008 | −0.003 | −0.005 | 0.000 |

## Descriptive only: Aug-Dec 2021-25 (never gating)

- **Rows:** 7,649 on 765 dates. The incumbent's mean Brier is 0.574254.
- **Arm B:** −0.0292 [−0.0375, −0.0206]. By season: Aug-Sep −0.0376 [−0.0515, −0.0241]; Oct-Dec −0.0236
  [−0.0339, −0.0137].
- **Arm A:** −0.0080 [−0.0117, −0.0043]. By season: Aug-Sep −0.0123; Oct-Dec −0.0051 [−0.0095, −0.0010].
- **No-NBM reference:** a2, at +0.0948 [+0.0814, +0.1092].
- **Run env note:** this run read the run env worktree at `6f50e0882`. That is cf381f0f3 plus L3's
  `mr_sweep` carry. The four files used (`pooled_residual_model.py`, `feature_model.py`,
  `nbm_probabilistic_tmax.py`, `units.py`) are byte-identical between the two (git diff empty). The gate
  run was at `cf381f0f3`.

## Disclosures

- These are history gains against an NBP-centred incumbent. They are not market evidence. P0 on the dev
  window decides.
- There is a train/serve version shift: V4.0-V4.3 in training, V5.0 on dev (S1).
- This is the second test of this source on the window (row 77).

## Receipts

All runs were light (each under 1 minute and under 1 GB) and ran directly with their sha recorded.

- **Gate:**
  - script `C:\t\l8tor\s2.py` as run, sha256
    `c9a64d0b6679e6c169ffe5f204b95dbf905d49a3f40b0514f09873d5ee952bcd` (kept as `s2_augsep_run.py.bak`);
  - receipt `C:\t\l8tor\s2_out_augsep\receipt.json`, sha256
    `6d1e98dac1cd46370d18912118e148dfe2fb15a80f9b1117c0d7e5746047cbc5`, with `run_env_head` `cf381f0f3…`;
  - per-hour and per-date rows `rows_hour.jsonl` and `rows_date.jsonl` (sha256 values in the receipt).
- **Descriptive:**
  - script sha256 `0d5382afb6660e357fc46e3bddd96fdda6e8467c552f0f11e329c1c5e4fb95d2`, which adds hour
    splitting and a merge;
  - it ran as two hour halves (07-11 and 12-16, 47 s each) and then a merge;
  - receipt `C:\t\l8tor\s2_out_augdec\receipt.json`, sha256
    `acc798d8a72c8c3b63737c7b34ced0b1af9163e90c875588daca5f23d40cb733`.
- **Helper:** `incumbent.py`, sha256 `c26170b6…66e3c`.
