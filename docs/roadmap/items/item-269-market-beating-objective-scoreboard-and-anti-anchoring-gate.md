# 269. Market-Beating Objective Scoreboard And Anti-Anchoring Gate [OPEN 2026-06-23 - NORTH-STAR SCOREBOARD NEEDED]

Goal: make "beat the market independently and profitably" the explicit daily
objective, so market prices stay a benchmark and residual input rather than
becoming the target the model quietly imitates.

Source: 2026-06-23 roadmap coverage review after the concern that the project
may be anchoring too hard on Polymarket prices. Existing items already cover
weather-only proof separation, market/residual evidence, proper scoring,
winner-rank parity, no-market candidate governance, and taker/maker execution
gates, but no single active item joins those into one objective contract.

Why this matters: a model can look better by moving closer to market prices
without creating independent edge. A trading strategy can also look profitable
from mark-to-market or stale midpoint evidence while failing after settlement,
fees, slippage, executable depth, and no-trade baselines. The roadmap needs one
daily answer to the strategic question: are we independently beating the market,
finding executable residual edge, or merely converging toward the benchmark?

## Design

1. Add a `market_beating_objective_scoreboard` artifact that joins
   `weather_only_model_proof_packet`, `proper_scoring_reliability_scorecard`,
   `market_benchmark_residual_edge`, `winner_rank_parity`,
   `daily_progress_latest`, and `trading_evidence`.
2. Report three separate decisions:
   - `weather_only_market_beating`: weather-only model skill versus market
     under proper scoring, proof-packet gates, winner-rank parity, and pinned
     baseline evidence.
   - `residual_edge`: model-minus-market disagreement skill on time-blocked or
     day-blocked slices, with market-informed rows barred from weather-only
     credit.
   - `executable_profitability`: maker/taker net performance versus no-trade
     and market baselines after settlement, bid/ask, depth, fees, slippage,
     partial fills, tail losses, and MTM reconciliation.
3. Add anti-anchoring checks that flag any objective improvement driven by
   market-price, CLOB, midpoint, or overlay features unless it is reported in
   the market-informed residual/trading lane. Proximity-to-market is
   diagnostic only; it cannot be a success metric by itself.
4. Require the headline status to stay `BLOCK` unless at least one of these is
   true on countable evidence:
   - weather-only model beats market on the proof-packet/proper-score stack;
   - a predeclared residual disagreement slice beats market and clears
     executable trading gates;
   - a maker/taker strategy beats no-trade and market baselines after all
     execution costs and settlement finalization.
5. Feed the scoreboard into the daily progress ledger, active backlog ordering,
   and dashboard/operator reports, so broad progress claims are ordered by
   market-beating evidence rather than incumbent-relative improvement.

- [ ] Define and register the `market_beating_objective_scoreboard_v0.1`
  schema.
- [ ] Generate JSON and Markdown outputs from the existing proof, scoring,
  residual, parity, progress, and trading artifacts.
- [ ] Add lane-contamination and anti-anchoring fields for every headline
  improvement.
- [ ] Wire the scoreboard into daily refresh after trading evidence and before
  the progress ledger rollup.
- [ ] Teach the daily progress ledger and actionable work order to display the
  scoreboard headline status and first blocker.
- [ ] Add tests showing market-informed convergence cannot clear
  weather-only, residual-edge, or profitability success without its own
  countable lane evidence.

Acceptance: each daily refresh produces a single market-beating objective
scoreboard that answers whether the system is independently beating the market,
has a tradable residual edge, or is blocked. The scoreboard must fail closed
when gains come only from market anchoring, market-informed overlays, MTM-only
PnL, stale/non-executable prices, or incumbent-relative improvement that still
trails the market.

Related: items 48, 69, 72, 83, 86, 115, 163, 217, 240, 241, 242, 256, 258,
262, 263, 264, 266.
