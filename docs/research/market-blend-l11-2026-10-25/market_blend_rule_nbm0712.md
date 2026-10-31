# Rule L11-market-blend NBM-0712 (lane L11, 2026-10-25): an NBM blend at 07-12 vs the market

Written 2026-10-25 (about 04:55 EDT), before any row of this check is read. Research only, development window only
(nothing dated after 2026-09-29 is read; no 88a, panel or settlement data for 2026-09-30..10-15). Approved by
master through the coordinator ("item 5").

Base: the L11 market-blend rule `C:\t\l11\rule.md` (sha256
`e29c9a84395d7f4f5e9a0091da99ff970597c40faa7d4cc81aa034a373f8bb8c`) and clarification 1 (sha256
`46e1fac20a4fed42ec1290c1d675dbf204dfba475ee756ee442b6f121d5a9de0`), run 2 (rows
`1ba4620a60f45277f9199c7f2489f61b7e89ec81a5326f501f1b2bf63a41170b`). **The run-2 log-pool machinery is used
unchanged**: `weather.calibration.market_blend` (`pool`, `grid_cell_values`, `walk_forward_w`,
`score_candidate`, `reading`), the same layout `C:\swarm\v3layout`, folds, burn-in 2026-08-01..08-14, scored
dates, W grid, gap, eps floor, mass renormalisation, placebo, bootstrap (2,000 draws, seed 20260921). The only
change is the candidate fed to it at 07-12.

## Candidate

- **P3d_N**: `C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl`, sha256
  `721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec` (loaded as in run 2 by
  `gap_to_market_atlas.load_candidate`, trained through 2025-12-31, walk-forward declared), used at every hour of
  the pre-13 fit blocks (07-12 primary; 06-09 and 10-12 as in run 2) **in place of MG-1 + L6**. Snapshots the file
  does not cover fall back exactly as run 2's loader does; coverage at 07-12 is reported.
- L9's N1 is **dropped**: no per-snapshot 07-12 probability vectors for N1 exist on this workstation (L9's
  `runs\rung*\ladder_rows.jsonl` hold per-row scores, not distributions). While checking, the first 400 bytes of
  `C:\t\l9\runs\rung1\ladder_rows.jsonl` were displayed (one row of L9's historical ladder scores: atlanta,
  hour 7, centre 08-08); nothing from it is used here.
- **Unseen read confirmed:** P3d_N has never been scored at 07-12 by this lane. Run 2 used P3d_N only at local
  hour >= 13 (`np.where(local_hour < 13, pre-13 slot, P3d_N)`); the descriptive note (`7928629…`) and its rows
  (`4b9c8f57…`) cover 13-16 only. No 07-12 R of P3d_N alone or blended has been computed or seen.

## Metric and reading (run 2's, unchanged)

- Primary: the walk-forward w fitted on 07-12 (pooled cell-mean Brier), the blend scored vs the market only on
  the 07-12 ALL row: R = blend Brier / market Brier, crossed (date x market) 95% CI decides, date-clustered CI
  reported. PRIMARY5 and per-hour h07..h12 rows reported; the log score as secondary.
- **Reading (run 2's `reading`):** placebo failed ⇒ NOT INTERPRETABLE; crossed lower CI > 1 ⇒ HARM; mean w <
  **0.05** ⇒ NOTHING; crossed upper CI < 1 and R below the floor-only control ⇒ INFORMATION; otherwise
  INCONCLUSIVE.
- DESCRIPTIVE only (not for a decision): P3d_N alone vs the market at 07-12 and h07..h12, ALL and PRIMARY5.
- No candidate-minus-candidate deltas.

## (a) Positive control

Before any candidate row: the served control (1.774 all hours / 1.526 00-16), the MG-1 07-12 Brier excess over
the market 0.0120 (4 dp), the w = 0 identity for the new candidate, and MG-1's run-2 07-12 primary R 1.0016629
(rows `1ba4620a…`) must reproduce; the placebo (mean w <= 0.05 and R >= 0.999) must pass for the reading.

## (b) Comparator fairness

The comparator is the market itself. The blend gets the same eps floor and rule-4 impossible-band floor as
run 2, with the market's own mass; no calibration of the market or of the candidate beyond the pre-registered
walk-forward w.

## (c) Targeted loss slice

Loss atlas `535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4`: the 07-12 MG-1 excess over the
market, expected size 0.0120 in Brier (the slice the pre-13 model loses to the market).

## (d) MDE and clusters

43 scored date clusters and 11 market clusters (run 2); run 2's composite 07-12 MDE80 was 0.0056 in R; the new
MDE80 is reported.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: 33 rows counted by this lane's rules so far (r2 32, r3 +1). This check adds 1 K row
(NBM blend at 07-12): K candidate 24 on 2026-07-31..09-29.
