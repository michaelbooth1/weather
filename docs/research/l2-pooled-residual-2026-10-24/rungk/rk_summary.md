# R-K result (lane L2), 2026-10-25: gates 1-3 PASS; gate 4 WIN

**Rule:** `rule_rk.md` (sha `21b5dfe1…7221`) and Clarification RK-1 (sha `c825b277…32c7`). Gate 2 is in
`rk_gate2.md`.

**Evidence class:** development evidence only.
- No promotion, binding or MG-2 change.
- Captured-forward HRRR does not exist. Forward parity (gate 1, rule §8 plan) is unproven and required before any
  use.
- Per the rule, a WIN lets L2 draft, but not apply, an MG-2 post-13 Clarification and the forward-parity plan.

## Headline

| Gate | Result |
| --- | --- |
| 1a training parity | PASS: coverage 13,108/13,108 |
| 1b dev parity | PASS: coverage 18,573/18,573; zero identity, point-in-time, window or range violations |
| 2 LOYO 2021-25, B_H − B_N 13-16 | PASS: −0.0139 [−0.0166, −0.0112] |
| 3 dev, P3d_H − P3d_N_fix 13-16 (dR) | **PASS: −0.0722 [−0.0979, −0.0471]** |
| 4 against the composite post-13 arm on as-of-capture inputs | **WIN: −0.0722 [−0.0979, −0.0471]**; no hour has a lower bound above 0 |

**P3d_H is still worse than the market.** R(P3d_H) at 13-16 is 1.220 [1.100, 1.349], against 1.293 for the
as-of-capture composite.

## Controls

- **R-H reproduction:** `dev_B_N.jsonl` and `dev_P3d_N_fix.jsonl` are byte-identical to R-H (`bab9cac7…`,
  `abc43507…`).
- **MG-1 07-12 control:** 0.01196, which rounds to 0.012.
- **Composite against MG-1 at 13-16:** Brier difference −0.0151 [−0.0192, −0.0113]. This equals the diagnostic's
  as-of-capture composite figure (`p3dn_diag/diag_summary.md`).
- **Population:** 43 scored dates (08-15..09-29), 473 market-days. Common covered snapshots: 13,970 at 13-16.

## Gate 3 per hour (dR, date-clustered; P3d_H − P3d_N_fix)

| Pool | dR | R(P3d_H) |
| --- | --- | --- |
| 13-16 | −0.0722 [−0.0979, −0.0471] | 1.220 [1.100, 1.349] |
| 13-14 | −0.0777 [−0.1097, −0.0471] | 1.199 |
| 15-16 | −0.0601 [−0.1035, −0.0170] | 1.266 |
| h13 | −0.0552 [−0.0876, −0.0231] | 1.191 |
| h14 | −0.1022 [−0.1441, −0.0646] | 1.208 |
| h15 | −0.0705 [−0.1173, −0.0261] | 1.300 |
| h16 | −0.0367 [−0.1012, +0.0237] | 1.209 |

**Reported only, B_H − B_N on dev:** 13-16 −0.0695 [−0.0905, −0.0489].

## Gate 4 (P3d_H with MG-1 fallback, against the composite post-13 arm as of capture)

- **dR at 13-16:** −0.0722 [−0.0979, −0.0471]. The per-hour figures equal gate 3's to 4 dp, because the MG-1
  fallback covers only 2 snapshots.
- **MG-2's G2 form, Brier difference against MG-1 (reported):** P3d_H_mg1 −0.0171 [−0.0213, −0.0134], against
  −0.0151 [−0.0192, −0.0113] for the composite.

| Hour | P3d_H_mg1 − MG-1 | Composite − MG-1 |
| --- | --- | --- |
| h13 | −0.0085 | −0.0061 |
| h14 | −0.0132 | −0.0096 |
| h15 | −0.0192 | −0.0176 |
| h16 | −0.0274 | −0.0270 |

## Per market (gate 3 statistic, 13-16, reported only)

- **Ten of 11 markets are negative.** The upper bound is below 0 in atlanta, chicago, houston and seattle.
- **san-francisco is worse:** +0.0954 [+0.0268, +0.1735].
  - The rule has no per-market gate.
  - This is flagged for the Clarification draft. It is a candidate market-level fallback, which would need its own
    rule.

| Market | dR |
| --- | --- |
| atlanta | −0.1048 [−0.2278, −0.0060] |
| austin | −0.0599 [−0.1428, +0.0148] |
| chicago | −0.1226 [−0.2403, −0.0037] |
| dallas | −0.0423 [−0.1162, +0.0259] |
| denver | −0.0421 [−0.1390, +0.0399] |
| houston | −0.1844 [−0.3498, −0.0437] |
| los-angeles | −0.0219 [−0.2089, +0.1839] |
| miami | −0.0043 [−0.0767, +0.0461] |
| nyc | −0.0684 [−0.1935, +0.0274] |
| san-francisco | **+0.0954 [+0.0268, +0.1735]** |
| seattle | −0.1436 [−0.2618, −0.0571] |

## Inputs and files

| Item | sha256 |
| --- | --- |
| HRRR train `manifest.jsonl` | `409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935` |
| HRRR train `selections.jsonl` | `055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75` |
| HRRR dev `manifest.jsonl` (`C:\t\l13\hrrr_2026dev\`) | `b6e4a37049e6d326d497b69675d2673472ff3042e868fe84fef9f5831caf3619` |
| HRRR dev `selections.jsonl` | `5cb89831067bb013f78a8a899c1c4d5631251dc091d04f6e98bc2441de5e837b` |
| `stations.json` (both corpora) | `52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3` |
| `C:\t\l2\rungk\emit\rk_emit_audit.json` | `30d7c6d9f6c55360d47e0615ca036a9c724edb2cb9559f85b827230a362b147b` |
| `dev_B_H.jsonl` | `da18f40982bad2358f6bc5afb00c02a242f953f15f9e22d2f3eedb47d0a03b59` |
| `dev_P3d_H.jsonl` | `e5195945cd8a24db178cd8b85e0af8914c95321b581a65897e8cac59eb451da1` |
| `C:\t\l2\rungk\score\rk_score.json` | `ad8eb2b03c44f6bc402ae4649431129a386e74849cd4e4ec135b6df428725a27` |

- **Code:** branch `claude/rung0712-20261025` @ `3f03bd12c`. The emit reuses `dev_emit_rung` with arm and column
  hooks; the defaults are unchanged, as the byte-identical R-H files show.
- **Run tree:** `C:\wt\l2run` @ `969507397` (local).
- **Wrapper:** all heavy steps ran through `workstation_heavy.ps1 -Queue`, with PREGATE_HOLD absent at each launch.

## Caveats

- **One season.** The dev window is 43 scored dates. The LOYO gain (−0.0139 Brier, B_H) and the dev gain are in
  the same direction.
- **The source is new to production.** HRRR native-grid point extraction is not captured today. Every forward use
  waits on the plan §8 recorder and parity proof.
- **h16 is not significant** on its own at dev (upper +0.0237), and LOYO showed no P3d_H gain at h16.
