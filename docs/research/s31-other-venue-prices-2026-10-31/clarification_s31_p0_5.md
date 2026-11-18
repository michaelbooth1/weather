# S31 P0 Clarification 5 (2026-10-31): every deciding bound uses the widest of three intervals

Status: fifth clarification to `rule_s31_p0.md` (sha256
`d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e`), issued at the coordinator's review of the
P0 code, before the P0 runs. It sits beside these files, none of which is edited:

| file | sha256 |
| --- | --- |
| `clarification_s31_p0_1.md` | `b7bb9f2aafb654bd68389c170416f3efae64b33696723a6c54572ce22e177e5d` |
| `clarification_s31_p0_2.md` | `798dfaa912c7e94da97c0c99340d12726bb9c606b7279324b92ef4b8c670bd26` |
| `clarification_s31_p0_3.md` | `654408acbc40fa981b30947547863ae7140694f530f559f1bb9fefe94db0a340` |
| `clarification_s31_p0_4.md` | `ee35f782f89934095bad84e1c4ad92906c1a1b77ae687ec6d388879c89bc4c2c` |
| `amendment_s31_1.md` (master AMENDMENT 1) | `4c29c0bf4023b2a4121a4adda0fb37e6d1bf1814ee8987923d5a8f14967f5666` |

Lane L14, written outcome-blind: no twin price, label or outcome has been read, and the P0 has not run.

## 1. Why

Clarification 1 names its block-3 interval as a moving-block bootstrap whose block starts are uniform on
0..n − 3. That scheme is not circular, so the first and last dates get less expected weight than the rest.

The D3 rulings and C3 REVISION-2 use the circular scheme instead. Its source is `c3_kill_tier.block_counts` at
`1b65f11ee28f1b44dff9fde6ac9a7fb0d7769add` (dev-window ledger row 84).

Clarification 1 is pinned and approved, so it is not edited. This file adds the circular interval beside it.

## 2. The three intervals

For each testable arm (KAL-MEAN, KAL-WIDTH), Δ gets three 95% percentile intervals. Each one pairs bootstrap
draw b with placebo j_b = b mod 20, as rule §5 states.

| # | interval | dates resampled | draws, seed |
| --- | --- | --- | --- |
| 1 | date-clustered (rule §5) | the scored dates, iid with replacement | 10,000, seed 20261024 |
| 2 | Clarification 1 block-3 (non-circular moving block) | blocks of 3 consecutive dates with starts uniform on 0..n − 3, concatenated and cut to n | 10,000, seed 20261024 |
| 3 | REV-2 circular block-3 | ⌈n/3⌉ blocks of 3 consecutive dates with starts uniform on 0..n − 1, wrapping past the last date, cut to n | 2,000, seed 20261024 |

For both block intervals:

- The dates are the scored dates that have entries for the arm, in date order, so n is the realised N.
- The circular scheme is copied into `weather.calibration.s31_p0`, not imported from the C3 branch. A test checks
  that its counts equal the C3 reference.

## 3. The deciding bounds

| bound | rule |
| --- | --- |
| Lower | the minimum of the three lower bounds |
| Upper | the maximum of the three upper bounds |
| SE | the maximum of the three draw standard deviations |

These bounds decide the outcome as follows:

- **Survivor:** BH rejects at q = 0.10 over K = 3, and the widest lower bound is > 0. This replaces the
  date-clustered lower bound alone (rule §5).
- **D3 label (Clarification 2):** the widest upper bound is compared with Δ_edge = 0.224. This replaces "the
  wider of the date-clustered and block-3" upper bounds.
- **SE:** the widest SE is reported with the realised N, for the power line.

Unchanged:

- The BH p-values: still the rule's date-clustered one-sided p. The block p-values are reported beside them.
- FEX: UNTESTABLE with p = 1.
- The survivors' w gate: still uses `mr_gate`'s date-clustered rows. The block intervals are not added there.

**Effect.** Taking the widest interval can only make a survivor harder to reach and a "KILL at edge size" harder
to reach. It never makes either easier.

## 4. Code binding

The P0 module pins this file's sha256 together with the rule, Clarifications 1-4 and the amendment, and refuses
on a mismatch. It records all three intervals and the deciding bounds for each testable arm in the receipt.
Nothing runs until the coordinator admits the P0, after master has seen this file.
