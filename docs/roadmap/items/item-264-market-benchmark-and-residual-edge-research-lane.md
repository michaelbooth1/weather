# 264. Market Benchmark And Residual Edge Research Lane [OPEN 2026-06-23 - MARKET SIGNAL MUST NOT CONFUSE WEATHER SKILL]

Goal: evaluate market prices as a probabilistic benchmark and residual-edge
input without allowing market-informed skill to clear weather-only promotion
gates.

Source: the 2026-06-23 research audit found that weather-only lane separation is
working, but the broad weather-only candidate still trails the market benchmark.
The same audit found trading-specific risks that must be evaluated separately
from model skill: CLOB freshness, executable depth, bid/ask versus midpoint,
fees, slippage, MTM versus settlement, bad-tail fills, and no-trade baselines.

Why this matters: market prices can be a strong real-time probabilistic
benchmark, but they are not automatically tradable edge. A market-informed
overlay may improve settlement accuracy while still being impossible to execute
profitably, and a profitable-looking taker report may be driven by stale or
non-executable prices.

## Design

1. Build a frozen market benchmark dataset with snapshot timestamp, market
   timestamp, book age, token mapping, bid, ask, midpoint, spread, executable
   size, depth tier, and freshness state.
2. Compare weather-only, market-only, weather-plus-market overlay, and residual
   weather-minus-market models under time-blocked and day-blocked settlement
   scoring.
3. Prevent leakage by using only market data available before the forecast
   cutoff, excluding post-resolution prices, and recording stale or missing book
   states as first-class blockers.
4. Score settlement accuracy separately from trading results. Settlement
   accuracy may use midpoint or calibrated market probabilities; trading
   results must use executable bid/ask, depth, fees, slippage, partial fills,
   and no-trade baselines.
5. Include MTM-versus-settlement reconciliation so unrealized gains cannot be
   mistaken for realized edge.
6. Report residual edge by market, cutoff hour, liquidity state, source-health
   state, and tail-risk bucket.

- [ ] Add a market benchmark/residual-edge research report.
- [ ] Add frozen CLOB freshness and executable-depth fields to the research
  input contract.
- [ ] Add weather-only, market-only, overlay, and residual model comparisons.
- [ ] Add no-trade and fees/slippage baselines to every trading-facing result.
- [ ] Add MTM-versus-settlement reconciliation by strategy and tail bucket.
- [ ] Add a guard that this lane cannot satisfy weather-only proof-packet
  blockers.

Acceptance: the repo can answer two different questions with separate evidence:
whether market prices improve settlement probability forecasts, and whether
any residual signal is executable after depth, fees, slippage, and tail losses.
Weather-only promotion remains blocked unless weather-only proof gates pass.

Related: items 47, 48, 72, 115, 156, 221, 242, 253, 256, 257, 261.
