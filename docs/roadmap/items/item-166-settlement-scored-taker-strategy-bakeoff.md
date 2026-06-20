# 166. Settlement-Scored Taker Strategy Bakeoff [COMPLETE 2026-06-20 - BAKEOFF AND LABEL-QUALITY BLOCKERS LIVE]

Goal: evaluate the best taker strategy ideas against historical and live
settled evidence before promoting any active-paper strategy.

Source: the 2026-06-20 taker-bot log audit. The June 19 simple raw-edge run
settled at `+36.687839` USDC after initially reporting `-17.208695` MTM, while
the later Seattle-only run reported `+1238.750000` MTM but settled at
`-10.000000`. This shows that mark-to-market and one-day raw-edge results are
not reliable enough to choose a taker strategy.

Why this matters: strategy selection needs a settlement-first bakeoff with
clear control arms, not anecdotal fills. The current bot can identify model
edge, but it has not shown which risk regime, sizing rule, or timing filter
turns that edge into repeatable P&L.

## Design

1. Build a taker replay harness that replays snapshot/model rows, CLOB book
   rows, source-status rows, current-high state, and settlement labels for each
   candidate arm.
2. Score every arm on settlement P&L, expected-versus-realized P&L, hit rate,
   ROI, drawdown, exposure concentration, stale-book decisions, source-state
   failures, and independent market/band opinion count.
3. Include these initial strategy arms:
   `raw_edge_control`, `calibrated_edge`, `low_price_tail_capped`,
   `winner_centered_or_adjacent`, `current_high_lockin`, and
   `late_day_liquidity_filtered`.
4. Require paired control/candidate comparisons by date, market, hour, and
   strategy family before any candidate can be promoted to active-paper default.
5. Keep intraday mark-to-market as a diagnostic only; promotion decisions use
   settled labels or explicitly unresolved sample accounting.

- [x] Implement a replay CLI that can score named strategy arms over existing
  taker-capable snapshot/book tapes.
- [x] Backfill the June 19 active-day tapes into the bakeoff.
- [x] Backfill the June 20 active-day tape after settlement labels are present
  in `data/backtest/market_day_labels.csv`.
- [x] Add per-arm reports for expected versus realized P&L and concentration.
- [x] Add promotion gates for minimum settled sample, non-negative settled ROI,
  max drawdown, and no unresolved stale-mark sign flips.
- [x] Add tests covering the June 19 positive-settlement and Seattle stale-MTM
  cases as bakeoff fixtures.

Acceptance: each candidate strategy has a settlement-scored comparison against
`raw_edge_control` over the same inputs, and no strategy can become the taker
default based only on raw edge, MTM, or unpaired live-paper anecdotes.

## 2026-06-20 Completion Notes

Implemented `python -m weather.market.taker_bot bakeoff` with chronological
tick replay over existing `orders_long.csv` tapes. The bakeoff runs the named
candidate arms on shared inputs, carries per-strategy budget and positions
forward by tick, scores fills with `market_day_labels.csv`, writes JSON and
Markdown reports, and blocks promotion when settlement samples are missing,
settled ROI is negative, drawdown exceeds the configured limit, unresolved
orders remain, stale MTM sign flips resolve against the strategy, or the
target-date label set is only partial quality.

Initial arms now available for bakeoff:
`raw_edge_control`, `calibrated_edge`, `low_price_tail_capped`,
`winner_centered_or_adjacent`, `current_high_lockin`, and
`late_day_liquidity_filtered`.

Generated June 19 bakeoff artifacts:

- `data/backtest/taker_strategy_bakeoff_2026-06-19_221a357c.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_221a357c.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_3d3450f0.md`

June 19 broad-run result after risk sizing: 2 of 6 arms passed the mechanical
strategy gates, but the artifact carries a global `partial_target_date_labels`
blocker because all 12 June 19 labels are partial quality. The
`winner_centered_or_adjacent` arm led the control by `+3.1666` USDC settled net
P&L on the same replay inputs. The Seattle stale-MTM run blocked all arms, with
raw-edge, late-day, and winner-adjacent failing on negative settled ROI and
resolved stale-mark sign flips. It also carries the partial-label blocker.

Generated June 20 settlement labels from local `snapshot_high` evidence with:

```powershell
python -m weather.operations.settled_day_freshness repair --target-date 2026-06-20 --snapshots-root data\snapshots --labels-csv data\backtest\market_day_labels.csv --ledger-root data\settlements --json-out data\backtest\settled_day_freshness_2026-06-20_post_repair.json --report-out data\backtest\settled_day_freshness_2026-06-20_post_repair.md --skip-polymarket-reconciliation
```

This wrote 12 June 20 labels to `market_day_labels.csv`; all are
`quality_grade=partial` and `settlement_source=snapshot_high` because the WU
daily summary files do not yet contain June 20 target rows. The settled-day
freshness report remains `FAIL` only because replay-status repair and complete
daily-summary labels are still unavailable; the taker bakeoff now has target
labels for every June 20 market.

Generated June 20 bakeoff artifacts:

- `data/backtest/taker_strategy_bakeoff_2026-06-20_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-20_3d3450f0.md`

The June 20 artifact scores all replay fills against the partial labels and is
intentionally non-promotable because it carries a global
`partial_target_date_labels` blocker. The mechanical strategy gates show
`winner_centered_or_adjacent` passing and raw edge blocking on negative settled
ROI and resolved stale-mark sign flips, but no strategy can be promoted from
this partial-label bakeoff alone.

Verification:

```powershell
python -m pytest -q tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_progress_ledger.py tests\operations\test_schema_registry.py
```

Result: `34 passed`.
