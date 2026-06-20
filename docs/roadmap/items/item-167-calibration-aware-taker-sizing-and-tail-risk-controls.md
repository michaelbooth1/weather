# 167. Calibration-Aware Taker Sizing And Tail-Risk Controls [OPEN]

Goal: stop raw model edge from over-allocating to fragile low-price tails and
repeated same-band opinions, while preserving a controlled lane for genuine
tail mispricing.

Source: the 2026-06-20 taker-bot log audit. The current policy ranks candidates
by raw `fair_probability - best_ask` and uses static caps. On settled June 19,
the simple-edge run generated `+152.3226` USDC of raw model expected profit on
59.8051 USDC spent but settled at `+36.6878`. The Seattle run generated
`+58.1713` USDC of raw expected profit on 10 USDC spent and settled at
`-10.0000`. Low ask prices and repeated snapshot fills amplify expected value
far more than the current evidence can justify.

Why this matters: a taker strategy should spend more when the model is both
mispriced and reliable. Static raw-edge sorting does not distinguish a
well-calibrated winner-adjacent edge from a cheap tail with thin support.

## Design

1. Add reliability-adjusted fair probability by market, bin, hour, source
   freshness state, current-high trust state, and model variant.
2. Convert raw edge into risk-adjusted expected value using calibration error,
   uncertainty, price, depth, and settlement-lag/mark-staleness diagnostics.
3. Add exposure caps for low-price tails, repeated same-band fills, adjacent
   correlated bins, market-level spend, and untrusted-current-high states.
4. Add sizing rules to test: flat notional, fractional Kelly capped by
   calibration confidence, EV-per-dollar tiers, and small-budget tail lottery.
5. Require CLOB continuity and price-history sanity before using mark-to-market
   or taking very low-price asks late in the day.

- [ ] Add calibrated/reliability-adjusted fair probability fields to taker
  candidate rows and reports.
- [ ] Implement strategy-arm sizing rules for flat, capped fractional Kelly,
  EV-tiered, and tail-lottery budgets.
- [ ] Add concentration metrics for market, bin, adjacent-bin cluster,
  low-price tail, and repeated snapshot exposure.
- [ ] Add hard guards for stale/resolved mark outliers and missing CLOB
  continuity before a fill can count toward strategy-quality evidence.
- [ ] Backtest and live-shadow the sizing rules through item 166's bakeoff
  before changing the active default.

Acceptance: taker fills include both raw and reliability-adjusted edge, sizing
is traceable to a named rule, tail/repetition exposure is bounded, and strategy
reports can show whether calibrated sizing improves settled P&L and drawdown
versus the raw-edge control.

