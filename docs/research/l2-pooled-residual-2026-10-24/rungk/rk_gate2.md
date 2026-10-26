# R-K gates 1a and 2 (LOYO 2021-25): PASS

Run 2026-10-25 under `rule_rk.md` (sha `21b5dfe1…7221`) and Clarification RK-1 (sha `c825b277…32c7`).

**This is LOYO evidence only.** Gate 3 (dev) has not run. It waits for L13's 2026 corpus (`C:\t\l13\hrrr_2026dev\`).
The pre-registered kill still applies if gate 3 fails. R-G had a gate-2 pass at 07-12 (B_G − B_N −0.0060) and
then failed its dev gate.

## Inputs

| Input | sha256 |
| --- | --- |
| HRRR `manifest.jsonl` (L13, 765/765 days, 44,302 lines) | `409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935` |
| HRRR `selections.jsonl` (36,720 rows) | `055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75` |
| HRRR `stations.json` | `52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3` |
| R-J `loyo_rows.jsonl` (control) | `0d5afcb3c26a0c83a719f764b9d4fd69a570d79a86bae95e3df0c1bb5ece6fab` |

- **Code and outputs:** run tree `C:\wt\l2run` with the branch at `63c500021`. Outputs are in `C:\t\l2\rungk\loyo\`.
- **Date scope:** only Aug-Sep 2021-25 training rows are joined. The Oct-Dec selections are never read into the
  frame.

## Gate 1a (training half, inputs only): PASS

- **Coverage:** 13,108 of 13,108 h13-16 rows covered (1.000).
- **Violations:** zero identity, point-in-time, window, snapshot or TMP-range violations.
- **Corpus-wide counts:**
  - 33,643 of the 33,660 R-A-market 13-16 selections are covered.
  - 17 have no cycle. They are treated as absent, not imputed, and none of them falls on a training row.

## Control: R-J reproduction: PASS

- **Keys:** identical (hour, year, market, date) keys, 13,108 rows.
- **Scores:** max |Δ| is 0.0 on the B_N and P3d_N_fix Brier and log scores.

## Gate 2: B_H − B_N, Brier, mean per row, date-clustered bootstrap (2,000 draws, seed 20261024)

| Pool | B_H − B_N | P3d_H − P3d_N_fix (reported) |
| --- | --- | --- |
| **13-16 (gate)** | **−0.0139 [−0.0166, −0.0112]** | −0.0126 [−0.0155, −0.0098] |
| 13-14 | −0.0154 [−0.0188, −0.0120] | −0.0194 [−0.0229, −0.0157] |
| 15-16 | −0.0125 [−0.0154, −0.0095] | −0.0059 [−0.0096, −0.0023] |
| h13 | −0.0119 [−0.0152, −0.0084] | −0.0207 [−0.0249, −0.0165] |
| h14 | −0.0189 [−0.0232, −0.0145] | −0.0182 [−0.0227, −0.0134] |
| h15 | −0.0200 [−0.0251, −0.0146] | −0.0145 [−0.0195, −0.0094] |
| h16 | −0.0049 [−0.0068, −0.0029] | +0.0027 [−0.0020, +0.0075] |

- **Result:** the gate's upper bound is −0.0112, below 0, so gate 2 PASSES.
- **P3d_N_fix − B_N** at 13-16 is −0.0598 [−0.0657, −0.0539]. R-J reproduced it exactly.
- **h16 caveat (reported, not a gate):** P3d_H does not improve on P3d_N_fix at h16. The HRRR window there is
  16:00-17:00 only.

## Files

| File | sha256 |
| --- | --- |
| `C:\t\l2\rungk\loyo\rk_loyo_audit.json` | `8e956b7fdfff6bd3037e349bf4e27d62a7442a695685ffed818b644c33f3cf32` |
| `C:\t\l2\rungk\loyo\loyo_rows.jsonl` | `bb0bf4943b7105b3f0ded1ec327c80bbdc54d9cbcc657cd10bf50d49eb761ee3` |

## Next

- **Gate 1b and gate 3:** run when L13 delivers `C:\t\l13\hrrr_2026dev\` with its manifest sha. That needs the R-K
  dev emit (not yet written, inputs as in the rule).
- **Gate 4:** follows only if gate 3 passes.
