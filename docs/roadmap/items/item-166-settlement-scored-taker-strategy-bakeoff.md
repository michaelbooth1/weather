# 166. Settlement-Scored Taker Strategy Bakeoff [OPEN]

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

- [ ] Implement a replay CLI that can score named strategy arms over existing
  taker-capable snapshot/book tapes.
- [ ] Backfill the June 19 and June 20 active-day tapes into the bakeoff once
  June 20 settles.
- [ ] Add per-arm reports for expected versus realized P&L and concentration.
- [ ] Add promotion gates for minimum settled sample, non-negative settled ROI,
  max drawdown, and no unresolved stale-mark sign flips.
- [ ] Add tests covering the June 19 positive-settlement and Seattle stale-MTM
  cases as bakeoff fixtures.

Acceptance: each candidate strategy has a settlement-scored comparison against
`raw_edge_control` over the same inputs, and no strategy can become the taker
default based only on raw edge, MTM, or unpaired live-paper anecdotes.

