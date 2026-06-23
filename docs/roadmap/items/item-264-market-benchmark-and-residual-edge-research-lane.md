# 264. Market Benchmark And Residual Edge Research Lane [COMPLETE 2026-06-23 - MARKET RESIDUAL LANE FAIL-CLOSED]

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

- [x] Add a market benchmark/residual-edge research report.
- [x] Add frozen CLOB freshness and executable-depth fields to the research
  input contract.
- [x] Add weather-only, market-only, overlay, and residual model comparisons.
- [x] Add no-trade and fees/slippage baselines to every trading-facing result.
- [x] Add MTM-versus-settlement reconciliation by strategy and tail bucket.
- [x] Add a guard that this lane cannot satisfy weather-only proof-packet
  blockers.

## Completion Notes

Implemented `weather.reporting.market_benchmark_residual_edge` with schema
`market_benchmark_residual_edge_v0.1` and canonical outputs at
`data/backtest/market_benchmark_residual_edge.json` and
`data/backtest/market_benchmark_residual_edge.md`.

The report reads the active shadow long table and trading evidence, then keeps
settlement probability skill separate from executable trading evidence. It
reports weather-only versus market-only Brier, market-informed overlay rows,
residual model-minus-market edge slices, frozen CLOB contract fields, fees,
slippage, no-trade benchmark fields, and MTM-versus-settlement reconciliation
by strategy.

The generated artifact is intentionally `BLOCK`: current rows show the market
benchmark beating weather-only settlement Brier by `+0.0089`, but frozen CLOB
fields are incomplete for timestamp/book-age/token/bid/ask/executable-depth
contract fields, and trading evidence still lacks complete market-benchmark
and no-trade fields. That is the expected fail-closed result for this lane.

The payload includes `proof_guard.counts_toward_weather_model_promotion=false`
and `BLOCKED_FROM_WEATHER_PROOF`, so market-only, market-informed overlay, and
residual-edge evidence cannot satisfy weather-only proof-packet blockers.

Verification:

- `python -m weather.reporting.market_benchmark_residual_edge --json-out data\backtest\market_benchmark_residual_edge.json --report-out data\backtest\market_benchmark_residual_edge.md`
- `python -m pytest tests\reporting\test_market_benchmark_residual_edge.py tests\reporting\test_market_residual_repair_program.py tests\operations\test_schema_registry.py -q`

Acceptance: the repo can answer two different questions with separate evidence:
whether market prices improve settlement probability forecasts, and whether
any residual signal is executable after depth, fees, slippage, and tail losses.
Weather-only promotion remains blocked unless weather-only proof gates pass.

Related: items 47, 48, 72, 115, 156, 221, 242, 253, 256, 257, 261.
