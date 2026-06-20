# 167. Calibration-Aware Taker Sizing And Tail-Risk Controls [COMPLETE 2026-06-20 - RISK-ADJUSTED SIZING LIVE]

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

- [x] Add calibrated/reliability-adjusted fair probability fields to taker
  candidate rows and reports.
- [x] Implement strategy-arm sizing rules for flat, capped fractional Kelly,
  EV-tiered, and tail-lottery budgets.
- [x] Add concentration metrics for market, bin, adjacent-bin cluster,
  low-price tail, and repeated snapshot exposure.
- [x] Add hard guards for stale/resolved mark outliers and missing CLOB
  continuity before a fill can count toward strategy-quality evidence.
- [x] Backtest and live-shadow the sizing rules through item 166's bakeoff
  before changing the active default.

Acceptance: taker fills include both raw and reliability-adjusted edge, sizing
is traceable to a named rule, tail/repetition exposure is bounded, and strategy
reports can show whether calibrated sizing improves settled P&L and drawdown
versus the raw-edge control.

## 2026-06-20 Completion Notes

Implemented reliability/risk annotations on every taker candidate row:
`reliability_context_key`, `reliability_confidence`,
`reliability_adjusted_fair_probability`, `risk_adjusted_edge`,
`risk_adjusted_expected_profit_per_share`, `low_price_tail`,
`tail_risk_bucket`, `current_high_band_distance`,
`adjacent_bin_cluster_key`, `clob_continuity_status`, and
`mark_sanity_status`.

Implemented named sizing rules:

- `flat_notional`: current control behavior.
- `fractional_kelly`: capped by reliability confidence for `calibrated_edge`.
- `ev_tiered`: edge-tiered sizing for winner/current-high and late-day arms.
- `tail_lottery`: small-budget lane for cheap tails with explicit tail caps.

Implemented hard exposure controls for market notional, adjacent-bin clusters,
low-price tail notional, and repeated same-opinion fills. Strategy reports and
bakeoff reports now include raw expected P&L, risk-adjusted expected P&L, tail
spend, top-market concentration, adjacent-cluster concentration, repeated
opinion counts, CLOB-continuity failures, and mark-sanity outliers.

Backtested through the item 166 bakeoff artifacts:

- `data/backtest/taker_strategy_bakeoff_2026-06-19_221a357c.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_221a357c.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_3d3450f0.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-20_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-20_3d3450f0.md`

June 19 broad-run result after risk sizing: `winner_centered_or_adjacent`
passed and improved over `raw_edge_control` by `+3.1666` USDC settled net P&L.
`low_price_tail_capped` was capped to `2.50` USDC spent and blocked on negative
settled ROI. The Seattle stale-MTM run blocked all arms; raw edge, late-day,
and winner-adjacent all failed on negative settled ROI and resolved stale-mark
sign flips. June 20 remains non-promotable because no `2026-06-20` settlement
labels exist yet.

Verification:

```powershell
python -m pytest -q tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_progress_ledger.py tests\operations\test_schema_registry.py
```

Result: `33 passed`.
