# Evening lock-in fix scoring: Clarification 2 (2026-11-03)

> **Status: master's ruling of 2026-11-03, recorded before any label read.** It adds one descriptive sensitivity
> and a disclosure to the signed pre-registration
> [`evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md`](evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md)
> and to [Clarification 1](evening-lockin-fix-scoring-clarification-1-2026-10-31.md). Neither file is edited, so their
> SHA-256 values are unchanged. It changes no threshold, estimand, market set, window date, gate or decision rule.
> Written after the label-free Stage 1 stages and before any settlement label, outcome, score or market price of the
> window was read. `promotion_countable` had not been read either.

## 1. B2 reproduction: proceed under the frozen overall rule

Clarification 1 section 7.3 gates on the overall share of a single commit: at least 99% of rows with a recorded vector
whose NEW arm reproduces the recorded served vector within L1 1e-9. The replay at `c32629156` gives
**28,001 / 28,108 = 0.99619**, with a recorded vector on every row. B2 therefore passes, and the read proceeds on
`c32629156`. Clarification 1 has no per-date rule. The per-date shortfall below is **disclosed, not a gate**.

Source: `replay_c32629156_all.jsonl`, sha256 `ff4478c3bf5493c82047bd6d0b539b9fbdd4ebb07eb004dba42d2a94c90db3ab`.
Label-free result: `scratch-transport/stage1-label-free/stage1_label_free_c32629156.json`, sha256
`ebf3f5ee88d2ac5fa136510ef961a225f0e02b1a61282d9cf96a9c2af2e9baff`, commit `9c40a39ce340ab73ab087622ad148a652cd41f83`.

| Target date | Rows reproduced / rows | Share | Non-reproduced | Local hours of the misses |
| --- | --- | --- | --- | --- |
| 2026-10-16 .. 10-21 | all | 1.0000 | 0 | — |
| 2026-10-22 | 2118 / 2167 | 0.97739 | 49 | 17-23 |
| 2026-10-23 | 2138 / 2138 | 1.0000 | 0 | — |
| 2026-10-24 | 2171 / 2171 | 1.0000 | 0 | — |
| 2026-10-25 | 2144 / 2170 | 0.98802 | 26 | 17-20 |
| 2026-10-26 | 2191 / 2191 | 1.0000 | 0 | — |
| 2026-10-27 | 2156 / 2161 | 0.99769 | 5 | 16 |
| 2026-10-28 | 2158 / 2185 | 0.98764 | 27 | 11, 13, 14, 21-23 |

**All 107 non-reproduced snapshots are Denver.** Every other market reproduces every snapshot on every date. All 107
were served by v0.5.12 and none is reconstructed. Their cause is not established when this is written.

## 2. Added sensitivity: three Denver cells excluded

Defined now, before any label read:

- **Excluded cells:** the whole Denver market-day cells **2026-10-22, 2026-10-25 and 2026-10-28**.
- **Why these three:** they are the only cells with a non-reproduced snapshot in the primary hours 17-23. The 10-27
  hour-16 misses and the 10-28 hour-11, -13 and -14 misses are outside the primary hours and do not count.
- **Whole cells, not snapshots:** a cell is either fully in or fully out. No snapshot is dropped inside a kept cell,
  so the 90% snapshot-coverage rule (Clarification 1 section 2) is untouched.
- **Statistics:** the same conditions 1-2 statistics as the primary, on the same US11 market set, the same
  outcome-blind window and the same countable cells, less the excluded cells. They are computed with the scorer's
  `primary_block` (fixed-market date-clustered bootstrap, 2,000 draws, seed 20261016). A cell that is not countable
  is already out, so excluding it changes nothing.
- **Weight:** descriptive only. **It decides nothing.** If its sign disagrees with the primary, the disagreement is
  reported, not decided.

It sits beside the frozen Clarification 1 section 6 Denver-excluded sensitivity (all Denver cells out;
`evening_fix_scorer.py:518-523` at `c32629156`), which also decides nothing. The signed primary keeps every countable
Denver cell.

## 3. What this clarification does not do

- It does not change B2, the window, countability, any threshold, the seed, the market set or the outcome table.
- It authorises no read by itself.
- It reads no 88a data and no market price.
