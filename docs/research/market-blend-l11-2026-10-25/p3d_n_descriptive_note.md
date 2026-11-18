# L11 descriptive note: P3d_N alone vs the market, 13-16 (DESCRIPTIVE, not pre-registered for a decision)

Written 2026-10-25, before any P3d_N-alone row is computed. It drives no decision, no reading rule and no ledger
K row. It is a description that sits beside market-blend run 2 (rows `1ba4620a…`).

- **Candidate:** the P3d_N vectors `C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl`, sha256
  `721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec`, unblended.
  - The vector is the dev scorecard's `Table.candidate_vector`: the rule-4 floor mask, renormalised, with the
    served fallback where P3d_N does not cover a snapshot. The covered share per row is reported beside it.
  - It is loaded exactly as in run 2 (`gap_to_market_atlas.load_candidate`, distributions, trained_through
    2025-12-31).
- **Population:** the market-blend scored dates, 2026-08-15..09-29 (43 dates, 473 market-days), on layout
  `C:\swarm\v3layout`.
- **Rows:** R = candidate cell-mean Brier sum / market cell-mean Brier sum, plus the log-score ratio.
  - Windows: local hours h13, h14, h15, h16 and the block 13-16.
  - Pools: ALL 11 markets and PRIMARY5 (atlanta, austin, chicago, dallas, denver).
- **CI method:** `gap_to_market_atlas.cell_stats` (dev scorecard), 95% bootstrap with 2,000 draws and seed
  20260921.
  - The date-clustered interval uses `Table.w_date`; the crossed date x market interval uses `Table.w`.
  - Both are reported for ALL and PRIMARY5.
- **Beside them** (for orientation, same windows): the floor-only control R (market plus hard floor, no
  candidate) from L11's `floor_only_rows`.
