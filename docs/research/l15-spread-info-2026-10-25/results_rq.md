# L15 rung R-Q results: GEFS member spread (run by L13, 2026-10-29)

Rule `rule_rq.md` sha256 `5703f06542b6f369bd32eaa2b84214bf4064b98490be3791b223c439d5e010c4` (committed `197729f4a`).
Code `19d822389`, run from `claude/rq-run-env-20261029` @ `c471b32b9`. That tree is the R-S run base `32d0a09d4`
with `19d822389` merged in, because the code commit alone does not import (`ols_floor_ladder` is missing). The
module file is byte-identical to `19d822389`. Dev-window ledger row 71 was opened as pending before any
computation. Every job ran once through `workstation_heavy.ps1 -Queue -MinAvailableMemoryGB 3`. Outputs are under
`C:\t\l15\rq\`.

## Verdict

- **Variant A: KILL at gate 2.** GEFS member SD is closed as a P3d_N_fix / L6-family scale modulator at 07-16, with
  the rule's full breadth.
- **Variant B: BLOCKED.** Precondition P_B failed, so gate B1 was not run. Per the rule this is not a kill.

## Gate 1: nested LOYO 2021-25, 07-12 (Q minus unmodulated, Brier)

The R-A control reproduced the R-A rows exactly: 19,657 rows, max abs diff 0.0.

| hour | dBrier | 95% CI | frozen dev beta |
| --- | --- | --- | --- |
| h07 | -0.00075 | [-0.00169, -0.00000] | 0.30 |
| h08 | -0.00057 | [-0.00115, +0.00003] | 0.25 |
| h09 | -0.00045 | [-0.00101, +0.00011] | 0.20 |
| h10 | -0.00059 | [-0.00115, +0.00002] | 0.20 |
| h11 | -0.00086 | [-0.00153, -0.00021] | 0.25 |
| h12 | -0.00079 | [-0.00147, -0.00011] | 0.25 |
| pooled | **-0.00067** | **[-0.00122, -0.00015]** PASS | |

- Pooled dLog is -0.00453 [-0.00890, -0.00049].
- u is defined on 19,644 of 19,657 rows.
- Result file `rq_loyo_0712.json` sha256 `441ccce45aefaf1a8107c9b467112d3fd3c31f08f2b552aeac26a5b1776e1cfa`.

## Gate 2: dev 2026-08-15..09-29, 07-12, vs unmodulated (dR, date-clustered, seed 20260921)

**Precondition P.** Gate 2 was run on L11's R-O precondition P as clarified by rule_rn Clarification 1.
- That result is `C:\t\l2\ro\parity_c1\rn_parity_c1.json`, sha256 `2553e0ef…`, PASS, on the same GEFS rows sha
  `8f512ad9…`.
- R-O's original P failed (p90 -1.027 °F), and C1 was written after that result.
- If master holds that R-Q's P means the original P, then variant A is BLOCKED rather than KILLED.

**Controls.**
- `dev_P3d_N_fix.jsonl` is byte-identical to `cd0034b9…`.
- MG-1 excess at 07-12 is 0.01196.
- Mass is preserved. The largest below-floor change is 1.0e-17.

**Population and modulation.** There are 21,664 common snapshots, 473 market-days and 43 dates. Mean m is +0.0054
and mean |m| is 0.067.

| group | dR | 95% CI |
| --- | --- | --- |
| h07 | -0.00275 | [-0.00763, +0.00188] |
| h08 | -0.00190 | [-0.00594, +0.00179] |
| h09 | -0.00296 | [-0.00619, +0.00027] |
| h10 | -0.00233 | [-0.00597, +0.00116] |
| h11 | -0.00273 | [-0.00728, +0.00179] |
| h12 | -0.00228 | [-0.00783, +0.00291] |
| 07-12 | **-0.00260** | **[-0.00650, +0.00094]** FAIL (the upper bound is not below 0) |

- No hour's lower bound is above 0.
- Gate 3 (vs L6) was not reached.
- Selection evidence only: the excess vs market is P3d_N_fix 0.01022, Q 0.01008 and L6 0.00814.
- Score file `rq_score_0712.json` sha256 `a2e0dcdb04086130d755680e35eb43a8682fef850a0283cc385386a80b50b694`.
- Emitted Q vectors: `98a31cb7…`.

## Secondary 13-16 LOYO (fails, so no dev run)

Pooled -0.00024 [-0.00062, +0.00014]. By hour:

| hour | dBrier |
| --- | --- |
| h13 | -0.00021 |
| h14 | -0.00003 |
| h15 | +0.00004 |
| h16 | -0.00078 |

Result file `rq_loyo_1316.json` sha256 `3953a5ca829ef0565d53ff55a5ef8dbfe9185015ce99a7a2a680c48407d92033`.

## Variant B: precondition P_B (fails, so B is BLOCKED)

The comparison is corpus 18Z D-1 ap5 node-max member p10/p90 vs the captured `day_member_high_p10/p90`, on 33,615
snapshots at 00-06.

| statistic | mean diff (°F) | median abs diff (°F) | r (cell means) | pass |
| --- | --- | --- | --- | --- |
| p10 | -1.41 | 1.27 | 0.986 | no |
| p90 | -1.21 | 1.16 | 0.988 | no |

- Result file `rq_parity_b.json` sha256 `fdf288241f2d77c3f8f7d6ff87888d7ff7c618db290455f8ab09b60f7b025de9`.
- The colder-history bias looks like the same definition gap that failed R-O's original P: a 3-hourly node max
  against an hourly full-day max. That is a reading only. Any clarification is master's decision.
- Gate B1 was not run, so no 18Z recorder arm is costed.
