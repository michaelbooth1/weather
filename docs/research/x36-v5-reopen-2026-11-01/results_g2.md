# K row 112 (X36 trailing correction): G2 dev result (lane L47, 2026-11-02)

The frozen rule is in `g2_freeze.md`, Clarifications 1-4. The verdict was applied as frozen (C1.6 three-way). No
interpretation beyond the frozen rule's words is recorded here.

## Verdict: CONSISTENT

Under C1.6, CONSISTENT means "point < -0.0005 AND G2-P point < 0, with UB not < 0. It goes to the history-tier
test, with no serving claim." Master ruled on 2026-11-02 that CONSISTENT is accepted and routes to the history-tier
test, and that C2.2 is met.

The statistic is dR = R(P3d_T) - R(P3d_N_fix), where R = Brier_model / Brier_market. It covers pool ALL, scope
covered, hours 07-12, target dates 2026-08-15..09-29: 43 dates, 473 market-days, 21664 covered snapshots.

| Run | Point | Date-cluster 95% CI | Moving-block 95% CI (L=7) | MDE80 | Power at -0.0075 |
| --- | --- | --- | --- | --- | --- |
| G2 (d26 = dseries26L) | -0.00273987162879355 | [-0.010191808599212017, +0.004813162931762016] | [-0.008204767704043119, +0.00260570672064243] | 0.010747 | 0.498 |
| G2-P (d26 = dseries26p) | -0.002766872743854489 | [-0.010591662310777569, +0.005528783578266599] | [-0.008402941873792345, +0.003148769651277253] | 0.011332 | 0.4505 |

Both bootstraps used 2000 draws with seed 20261024.

- The `dev_score` cross-check uses its own seed and agrees on the point (`point_matches` = true) for both runs.
- R against the market at 07-12:
  - G2: P3d_T 1.18850, P3d_N_fix 1.19124.
  - G2-P: P3d_T 1.18847.
- Shift difference, G2-P minus G2, on identical row keys: mean +0.0097 F, mean |.| 0.047 F, max |.| 0.71 F.

## Per-month breakdown (C2.2, required before a CONSISTENT promotion)

| Month | Dates / market-days | G2 point | G2 cluster CI | G2 MBB CI | G2-P point | G2-P cluster CI | G2-P MBB CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Aug | 16 / 176 | +0.00188 | [-0.00530, +0.00891] | [-0.00251, +0.00685] | +0.00097 | [-0.00704, +0.00852] | [-0.00407, +0.00660] |
| Sep | 27 / 297 | -0.00517 | [-0.01603, +0.00591] | [-0.01139, +0.00158] | -0.00474 | [-0.01633, +0.00713] | [-0.01137, +0.00260] |

## Controls and counts

- **Positive control: PASS in both runs.** The re-emitted BASE reproduces R-A's `dev_P3d_N_fix.jsonl`
  (`cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542`) on 21665 of 21665 rows with the same keys.
  The max |diff| is 0.0 at a tolerance of 1e-9. 7090 reference lines dated before 08-15 were skipped on their date
  text.
- **mbbdev** reproduces each run's date-cluster interval to 1e-12 (`cluster_reproduces_g2` = true for both).
- **Rows with fewer than W prior dates (shift 0):**
  - G2: 24 of 21665, 8 each at h08, h10 and h12.
  - G2-P: 0 of 21665.
- **Applied shift:** mean |shift| was 0.2637 F for G2 and 0.2735 F for G2-P.

## Disclosures

- **Old label.** `g2_result.json` (from `x36_trailing_g2.py` `gate()`, module `022565cc`) carries the superseded
  two-way label `"verdict": "KILL"`. Its rule reads "PASS only if the dev dR 95% upper bound < 0".
  - That rule was superseded by C1.6 before dev opened.
  - The deciding rule is `three_way_verdict`. `compare.json` already used it, but it also embedded the old label.
  - `three_way_verdict.json` re-applies the C1.6 function to compare's exact inputs and gets CONSISTENT
    (`matches_compare` = true).
  - Commit `86106f05b34e4a2c52ff00b75be410305ec85780` is a post-result reporting fix. It makes no gate, threshold or
    data change: future compare reports move the two-way fields under `superseded_two_way`.
- **WU mirror and option B (C4).**
  - The WS WU daily mirror was paused on 2026-08-12 by the owner's two-host decision, so it stops at 2026-08-10.
  - Master ruled option B: G2's 2026 d series comes from the dev layout's `labels.parquet` `settlement_high`
    (`1ea636e9...`), via `dseries26L`.
  - Gate (iii) matched the WU store exactly on the 98 common market-dates (max |diff| 0.0, 0 mismatches).
  - Missing label dates: 07-31, 08-16, 09-01 and 09-02, plus austin 08-07. The W-dates window spans these gaps.
  - b_train stays WU-era, as frozen.

## Output sha256 (run outputs under `C:\t\L47b\g2\`, preserved under `C:\archive\ruled-out\x36-trailing-correction-dev-20261102\`)

| File | sha256 |
| --- | --- |
| `dev_g2\g2_result.json` | `0951998f1ddec0ff995654ef68f6990c4ed9d4606b32a74e043b0d83f1e50f74` |
| `dev_g2p\g2_result.json` | `30f6fb5839cf98d4f0b610b01ac6bf154088ec49cc8885d31655217d3395aea6` |
| `mbb\mbb_g2.json` | `b166c76b8b3efa78bba4122ee5f24e8b02a942598e43c2f035d9a71cb466dc6f` |
| `mbb\mbb_g2p.json` | `81e6211d3d6359c409d0e48cecd512b0e4bfd10fd192a1e693401eb9426ae027` |
| `compare\compare.json` | `59e40703389be9433e2f271a30da9d414204186022bfcecf24459bd77d0330ae` |
| `compare\three_way_verdict.json` | `ce6dce450a9d52bf7df26715c2c0d70ca7b0e9e2f1096167973f0d673e9c2f61` |
| `d26\dseries26L.json` | `48bec4aee1b322be1c8700c7d45409e6b6a9abbde1dc8422138237b30a7fb819` |
| `d26\dseries26p.json` | `c780a905c26fe9c0acd7d317e56634ed117e32c8380ce36bc107a7b790653582` |
| `d26\overlap_iii.json` | `6eecbd910c60413d61087bb41fa03ade81e0f4cbcfac0012f50bc5854e30a487` |

Code and inputs:

| Item | sha256 or commit |
| --- | --- |
| G2 module | `022565ccceba52eed4b617ca031425a81f40dd9d373b08a64ee751dae9e55679` |
| freeze table | `eb73fc04ab20d7b0410633e3d159b069aa14ab4a8f36c5b76db0750fac79fc37` |
| g2p module that ran dev, mbbdev and compare | `09676bb4c1d07bd8f462b3c2ca8ff9c366116ad4fa9f87ac9884ae5198d0cd38` |
| run tip | `8293616b1d6ae57fb3a6fa9eb937ea08e03e9c95` |

Launch PIDs: G2 35584, G2-P 35892, mbbdev 37820 and 39584. All exited 0.

## Update when

Update this file only for an additive correction to a recorded figure. The history-tier test gets its own
pre-registration.
