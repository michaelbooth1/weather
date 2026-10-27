# R-I result (lane L2), 2026-10-25: KILL at gate 2

The rule is `rule_ri.md`, sha `b8a3d79ca13111db2bd667dc16e7a8418ddfe27bfaecbfaea23b099037341730`. It was
committed at 686b07234, before any R-I row existed. This is development evidence only and makes no edge claim.
Nothing dated after 2026-09-29 was read.

## Reading

- **Gate 1 (LOYO 2021-25): PASS, barely.**
- **Gate 2 (dev 07-12 against the uncalibrated arm): FAIL.**
- **The pre-registered kill applies.** The width lever is closed again for the NBM family: no retries with new
  families. No other temperature grid, hour grouping, scale variant, per-market map, conditional trigger or
  isotonic form is run on P3d_N_fix, L6 or any NBM-anchored arm under any rung name. EF §1c's closure stands,
  extended to these arms.
- Gate 3 (against L6) was not run.

## Gate 1: nested LOYO 2021-25 on P3d_N_fix (19,657 rows, 300 dates)

| Group | Calibrated − uncalibrated Brier | 95% (date-clustered) |
| --- | --- | --- |
| 07-12 | −0.00045 | [−0.00094, −0.0000084] |
| h09 | −0.00066 | [−0.00126, −0.00011] |
| h10 / h11 / h12 | −0.00041 / −0.00021 / −0.00016 | each interval includes 0 |

- **Effect size:** the gain is about 0.05% of the uncalibrated Brier (0.8516).
- **Fitted τ_h(Y):** 1.04 to 1.29, every one of them above 1 (sharpening), falling from h07 (about 1.22) to h12
  (about 1.06).
- **Controls:**
  - R-A's LOYO Brier was reproduced on all 19,657 rows (maximum absolute difference 2.0e-15).
  - No fitted τ worsened its own training score.

## Gate 2: dev 07-12, P3d_N_fix_cal against P3d_N_fix

The population is 43 scored dates (08-15..09-29), 473 market-days and 21,664 common covered snapshots. The MG-1
positive control gave 0.01196.

| Group | dR (date-clustered) | 95% |
| --- | --- | --- |
| **07-12** | **−0.0022** | **[−0.0156, +0.0104]** |
| h07 | −0.0048 | [−0.0254, +0.0154] |
| h08 | −0.0027 | [−0.0223, +0.0161] |
| h09 | −0.0033 | [−0.0196, +0.0119] |
| h10 | −0.0001 | [−0.0132, +0.0123] |
| h11 | +0.0002 | [−0.0101, +0.0102] |
| h12 | −0.0021 | [−0.0131, +0.0084] |

- **Why it fails:** the upper bound is at or above 0, so the gate fails.
- **Fitted τ on dev:** the walk-forward τ was mean 1.40 to 1.88 by hour, much sharper than the LOYO τ. It did
  not transfer across dates.
- **Per market:** only Miami excludes 0 (−0.0591 [−0.1009, −0.0234]). Denver (+0.029), Austin (+0.032) and San
  Francisco (+0.022) move the wrong way, with intervals that include 0.

## Reported only (never gates)

- **L6_cal − L6 at 07-12:** +0.0024 [−0.0046, +0.0094]. Tempering L6 is null, and its point estimate is worse.
- **R-F incumbent control, P3d_N_fix − L6:** +0.0390 [+0.0097, +0.0690]. L6 is better and in-sample.
- **Bucket position, P3d_N_fix_cal − P3d_N_fix at 07-12:**
  - Tempering raised the winner's mass from 0.291 to 0.327 (−0.0034).
  - It also raised mass one bucket either side (+1: 0.233 → 0.246, +0.0017; −1: +0.0011) and cut mass two or
    more buckets away.
  - The net is about zero: sharpening concentrates mass around our own centre, and that centre is often a
    bucket off.

## Alternative reading: SELECTION EVIDENCE

This reading consumes the market benchmark. It is never a gate, never an arm, and never booked as improvement.

| Excess vs market, 07-12 | P3d_N_fix | L6 |
| --- | --- | --- |
| Uncalibrated | +0.0102 [+0.0078, +0.0127] | +0.0081 [+0.0059, +0.0106] |
| Calibrated | +0.0101 [+0.0076, +0.0127] | +0.0083 [+0.0059, +0.0107] |
| Re-centred on the market median, uncalibrated | +0.0077 [+0.0059, +0.0095] | +0.0069 [+0.0049, +0.0088] |
| Re-centred on the market median, calibrated | +0.0065 [+0.0052, +0.0079] | +0.0064 [+0.0046, +0.0082] |

- **Survival share is not meaningful.** The rule's surviving-share statistic has no meaning here, because R-I's
  own gain on this scope is about 0: +0.0001 [−0.0006, +0.0008] for P3d and −0.0001 for L6. The ratio's
  intervals are reported in the JSON but are not readable.
- **Re-centring shows centre is the larger component.**
  - Moving our median band onto the market's removes about 25% of P3d's 07-12 excess (+0.0102 → +0.0077) and
    about 15% of L6's.
  - Only after re-centring does tempering help: +0.0012 [+0.0004, +0.0019] for P3d and +0.0004 for L6.
- **Width matters only once the centre is right.** That agrees with EF §1c and the digest: centre, not width,
  is the lever.

## Files

| File | sha256 |
| --- | --- |
| `C:\t\l2\rungi\loyo\ri_loyo.json` | `8152e8afd70f706af8b5c8259bfa71517162611488bd9f91de503f237e3470ed` |
| `C:\t\l2\rungi\loyo\ri_loyo_rows.jsonl` | `8b351095e5030c9a010b03c891b24f988e6cfc35d256952033a630ce8895bb7a` |
| `C:\t\l2\rungi\score\ri_score.json` | `59bd3da92eb8ca0aca9047463f6f847a1d73dde39019aaed82f9a9652c281e0e` |
