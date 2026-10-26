# R-L2 anchor diagnostic: NBS TXN against the L9 NBM anchor (inputs only, no rule)

Coordinator request of 2026-10-26: a diagnostic only, with no rule and no follow-up rung without a fresh ruling.
- **Rulings that stand:** R-L3 is dropped, and the R-L2 kill stands.
- **What was read:** inputs only. No label, outcome, price or market row was read.
- **Output:** `C:\t\l2\rungl2\anchor_diag.json`, sha256 `8e5eba6b32e74e1e0a3599f6cc8060a6d8b396a0047c750290fd3a8b7fef8353`.
- **Code:** `rl_anchor_diag` (CLI `rung-l-anchor-diag`), module sha256 `f270fe6f…` as recorded in the JSON.

## What is compared

- **Statistic:** `n_txn − anchor`, in °F, at cutoff hours 07-12 local.
  - `n_txn` is the TXN that R-L2's `txn_bearing` cycle rule selects.
  - `anchor` is the NBP mean that L9's `nbm_at_cutoff` selects (the training anchor, with the cycle preference 07, 01, 00).
- **Training half:** 2021-25, Aug-Sep. NBS from `C:\t\l12\nbs_nbh`; NBP from the L9 corpus `1ae4bf52…`.
- **Dev half:** 2026-07-30..09-29. NBS from `C:\t\l12\nbs_nbh_2026dev`; NBP from the dev corpus `85746b7a…`. Both are
  read through the same functions.
- **Pairs:**

  | Half | Paired rows | No anchor | Rows |
  | --- | --- | --- | --- |
  | Training | 19,797 | 3 | 19,800 |
  | Dev | 4,052 | 40 | 4,092 |

## Result

| Group | n | median abs | mean abs | mean signed | exact 0 | within 1 °F |
| --- | --- | --- | --- | --- | --- | --- |
| Training, all | 19,797 | 1.00 | 0.956 | +0.241 | 0.336 | 0.791 |
| Dev, all | 4,052 | 0.00 | 0.051 | +0.051 | 0.954 | 0.997 |

**By year and NBM product version (training).** The hour makes almost no difference, since every row's anchor is the
07Z cycle.

| Year | Version | mean abs | mean signed | exact 0 | within 1 °F |
| --- | --- | --- | --- | --- | --- |
| 2021 | 4.0 | 1.085 | −0.068 | 0.303 | 0.726 |
| 2022 | 4.0 | 1.260 | +0.522 | 0.248 | 0.678 |
| 2023 | 4.1 | 0.805 | +0.253 | 0.378 | 0.850 |
| 2024 | 4.2 | 0.840 | +0.299 | 0.365 | 0.842 |
| 2025 | 4.3 | 0.788 | +0.198 | 0.387 | 0.859 |
| 2026 dev | 5.0 | 0.051 | +0.051 | 0.954 | 0.997 |

**By cycle timing:**
- **Anchor cycle:** 07Z in every paired row, in both halves.
- **NBS cycle selected:**
  - Training: 12Z on 15,744 rows, 11Z on 2,517, 10Z on 1,293 and 09Z on 243.
  - Dev: 12Z on 2,932 rows, 11Z on 919, 10Z on 190 and 07Z on 11.
- **Effect of the NBS cycle:** within each half, the gap barely moves with the NBS cycle. Training mean absolute gap is
  0.87-0.97; dev is 0.01-0.09.

**By market:**
- **Training:** mean absolute gap from 0.64 (Atlanta) to 1.49 (San Francisco).
- **Dev:**
  - 0 at Austin, Chicago, Denver, Miami and NYC.
  - Under 0.04 at Atlanta, Dallas, Los Angeles and Seattle.
  - Larger only at Houston (0.21) and San Francisco (0.26).

## Reading (descriptive, no rule)

**The two halves are different.**
- In 2021-25 (NBM v4.x), the selected NBS TXN differs from the 07Z NBP mean by a median of 1 °F, matching exactly on
  only a third of rows.
- In 2026 (v5.0), the two agree exactly on 95% of rows, even though the NBS cycle is usually 12Z and the NBP cycle 07Z.
- **Consequence for R-L2:** the R-L2 features `n_txn` and `n_gap` therefore carried a training-only distribution.
  - The training-era gap is about 1 °F with era structure: 2021-22 on v4.0 is the widest.
  - On dev, `n_gap` is essentially 0.
  - This is consistent with R-L2's train-versus-dev gap difference.
  - It is about the TXN source's relationship to NBP across NBM versions, not the dev anchor choice (rl2_summary.md).

**Open input question (not acted on).** Near-exact agreement between a 12Z NBS TXN and a 07Z NBP mean in 2026 is
unusual. It may reflect a v5.0 product change, or a cycle-labelling difference in the dev NBS corpus. Checking it is
outcome-free, but any follow-up needs a fresh ruling.
