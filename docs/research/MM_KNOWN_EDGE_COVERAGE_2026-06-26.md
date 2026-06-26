# Market-Making Known-Edge Coverage

Date: 2026-06-26

Scope: fixed post-settlement drill `data/mm_runs/2026-06-25/20260626T020148684548Z`. No live orders were placed.

## Current State

The stable one-shot drill passed preflight across all 12 markets and emitted one paper quote:

- Rows: 132.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Reason counts: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 10 `NO_QUOTE_MISSING_BOOK`, 1 `QUOTE_HARVEST_MID`.
- Event gate: clear on all rows.
- Evidence mode: `post_settlement_evaluation`, so this is not countable live-forward evidence.

The one quoted row:

- Market: Dallas.
- Band: `92-93 F`.
- Side: `TWO_SIDED`.
- Permission: `harvest_only`.
- Policy reason: `QUOTE_HARVEST_MID`.
- Promotion state: `SHADOW`.
- Known-edge reason: `awaiting_paper_markouts`.
- Bid: 0.9895 for 5 contracts.
- Ask: 0.999 for 5 contracts.
- Quote risk: 4.9525 USDC.
- Expected reward score: 1.0.
- Expected rebate value: 0.0.

Interpretation: this is useful as a paper target for the next active window, but it does not justify live capital.

## Blocker Map

| Market | Rows | Status | Action |
|---|---:|---|---|
| atlanta | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| austin | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| chicago | 11 | Promotion block | Inspect promotion/paper evidence |
| dallas | 1 quote, 10 missing-book | Collect active-window markouts; fix book gaps |
| denver | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| houston | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |
| los-angeles | 11 | Promotion block | Inspect promotion/paper evidence |
| miami | 11 | Promotion block | Inspect promotion/paper evidence |
| nyc | 11 | Promotion block | Inspect promotion/paper evidence |
| san-francisco | 11 | Promotion block | Inspect promotion/paper evidence |
| seattle | 11 | Promotion block | Inspect promotion/paper evidence |
| toronto | 11 | Missing known-edge records | Build shadow evidence or keep no-quote |

Missing known-edge records cover the full active band set for Atlanta, Austin, Denver, Houston, and Toronto. Promotion blocks cover all bands for Chicago, Los Angeles, Miami, NYC, San Francisco, and Seattle.

## Dallas Missing-Book Rows

Dallas has harvest-only permission across all 11 bands, but only one band produced a quote. The other ten rows had token ids and condition ids but no usable book spread, so policy emitted `NO_QUOTE_MISSING_BOOK`.

| Band | Mid | Depth 1pct | Fair probability | Edge |
|---|---:|---:|---:|---:|
| 85 F or below | 0.0005 | 1195.09 | 0.0 | -0.0005 |
| 86-87 F | 0.0005 | 1386.22 | 0.0 | -0.0005 |
| 88-89 F | 0.0005 | 108.71 | 0.0 | -0.0005 |
| 90-91 F | 0.0005 | 2005.09 | 0.0 | -0.0005 |
| 94-95 F | 0.0005 | 2461.30 | 0.0001637907 | -0.0003362093 |
| 96-97 F | 0.0005 | 1741.69 | 0.0000031652 | -0.0004968348 |
| 98-99 F | 0.0005 | 2010.29 | 0.0000000065 | -0.0004999935 |
| 100-101 F | 0.0005 | 2068.83 | 0.0 | -0.0005 |
| 102-103 F | 0.0005 | 2072.73 | 0.0 | -0.0005 |
| 104 F or higher | 0.0005 | 2072.73 | 0.0 | -0.0005 |

These missing-book rows should not be forced into quotes. They should be diagnosed as book/midpoint quality gaps and then re-scored in paper.

## One-Run Paper Score

The full promotion-grade `weather.market.mm_paper` command still timed out after 300 seconds on the full historical corpus. The explicit one-run score completed quickly:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z --json-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.json --report-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.md --fills-out data\backtest\mm_paper_quote_starvation_fills_20260626T020148684548Z.csv --known-edge-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.json --known-edge-report-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.md
```

Result:

- Runtime: 4.4 seconds.
- Run folders: 1.
- Quote rows / legs: 132 / 2.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Gate status: `OPEN`.
- Paper-score freshness: `NO_ACTIVE_DAY`.
- Fill evidence completeness: `BLOCK`.
- Missing-size trade rows: 1,944.
- Missing-book queue legs: 1.
- Missing-trade-size queue legs: 0.
- P&L, reward, and rebate estimates: 0.

The one-run known-edge map produced 217 records: 176 `harvest_only`, 38 `no_quote`, and 3 `edge_research`. That map is diagnostic only; it should not replace the standard map until promotion-grade full-corpus scoring is made reliable.

## Full-Corpus Scoring Bottleneck

`discover_run_folders(data/mm_runs)` found 37 candidate folders, 36 eligible and 1 excluded. Several eligible quote tapes are large:

- `data/mm_runs/2026-06-23/20260623T165025535344Z`: about 105 MB of quote tape.
- `data/mm_runs/2026-06-21/20260621T153607128252Z`: about 83 MB of quote tape.
- `data/mm_runs/2026-06-24/20260624T233003009128Z`: about 82 MB of quote tape.
- `data/mm_runs/2026-06-22/20260622T233019900796Z`: about 14 MB of quote tape.
- Ongoing post-settlement roll `20260626T015632370043Z`: growing while the scorer runs.

Bounded and summary-only scoring are now available for diagnostics, but full-corpus promotion-grade runtime remains a blocker for standard reporting:

- explicit `--run-folder` for current diagnostics,
- `--latest-n` for recent runs,
- `--target-date` / `--run-target-date` filtering,
- `--evidence-mode` filtering,
- bounded reports that disclose `diagnostic_selection_not_full_corpus`,
- `--skip-model-variants` for faster operational diagnostics, with model-variant bakeoff disclosed as `SKIPPED (skip_model_variants)`,
- `--skip-fill-simulation --skip-model-variants` for full-corpus quote/no-quote and reward-score diagnostics, with fill evidence disclosed as `SKIPPED (skip_fill_simulation)`,
- cached CLOB/trade joins for queue companion scoring remain useful follow-up work.

The full summary-only run completed in about 176 seconds with 628,481 quote rows, 71,828 quote legs, 35,914 quote-permission rows, reward score 165,800.676275, paper freshness `PASS`, fill evidence `SKIPPED`, and model-variant scoring `SKIPPED`. Its known-edge map had only 17 records and is diagnostic only.

Skip-model-variant reports are not model-promotion evidence, and skip-fill reports are not fill, P&L, or known-edge promotion evidence. Until promotion-grade full-corpus scoring is fast enough, use explicit `--run-folder` or bounded target-date scoring for targeted diagnosis and do not treat bounded or summary-only known-edge maps as the standard map.

The latest bounded active-day promotion-grade score selected `data/mm_runs/2026-06-25/20260626T015448206993Z` and found 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, and reward score 0. Quote-blocker diagnostics show all 132 rows were event-gate suppressed, 121 were known-edge permission-blocked, and 11 harvest-only rows were suppressed by the event gate, with top known-edge states 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, and 11 `awaiting_paper_markouts/harvest_only/SHADOW`. That active-day result is the countable blocker; the Dallas harvest quote remains post-settlement only.

## Go / No-Go Impact

PASS:

- The latest fixed one-shot has current metadata/economics and passes preflight.
- Shadow/paper modes still emit no live permission.
- A single paper harvest quote can be generated after the information-event pull clears.

WARN:

- The quote is post-settlement, not active-window evidence.
- The quoted Dallas cell has no fill or queue-estimated fill evidence yet.
- Reward score appears, but reward P&L remains unproven.

BLOCK:

- No countable active-window paper evidence for the Dallas quote.
- Known-edge coverage missing for five markets.
- Promotion blocks across six markets.
- Dallas missing-book rows.
- Full-corpus `mm_paper` runtime.
- Full-corpus promotion-grade fill/queue/markout scoring runtime.
- Live capital.
