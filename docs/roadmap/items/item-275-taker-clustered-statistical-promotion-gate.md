# 275. Taker Clustered Statistical Promotion Gate [COMPLETE 2026-06-23]

Goal: make taker promotion decisions use clustered statistical evidence by
target day, market, strategy, and model version instead of treating raw order or
candidate rows as independent samples.

Source: the June 21-23 taker audit found `58` settled fills but only two
labelable target days. A naive order-level bootstrap was strongly negative, but
the effective sample size is far smaller because fills are clustered by market,
hour, and weather regime.

Why this matters: large candidate tapes can create false confidence. Promotion
needs to answer "does this edge repeat across independent market-days?" rather
than "did many correlated rows agree on one day?"

## Design

1. Add grouped promotion statistics by target day, market, local-hour bucket,
   strategy, model version, tail class, and current-high trust state.
2. Use cluster bootstrap or hierarchical shrinkage for PnL/fill, ROI, win rate,
   and drawdown intervals.
3. Require minimum independent target days and minimum market diversity before
   any strategy or model-version promotion.
4. Report multiple-testing-adjusted confidence when comparing many strategies
   or model variants.
5. Make the gate fail closed when complete-label days, independent markets, or
   after-fee/after-slippage fields are missing.

- [x] Implement clustered taker promotion statistics.
- [x] Add target-day and market diversity thresholds to taker quality reports.
- [x] Add multiple-comparison handling for strategy and model-version bakeoffs.
- [x] Add tests where many same-day rows cannot pass promotion without
  independent market-day evidence.

Acceptance: taker promotion can only pass when settlement-scored performance is
positive under clustered uncertainty, across enough independent days and
markets, after fees and slippage.

Completion evidence (2026-06-23):

- Added `clustered_taker_promotion_statistics`, which groups settled would-buy
  rows by independent `target_date,market_id` clusters for each
  `(model_variant_id, strategy_id)` pair.
- The gate reports cluster count, independent target-day count, independent
  market count, after-fee/after-slippage status, unresolved rows, ROI, cluster
  net-P&L intervals, and failed gates.
- Counterfactual settlement finalization now includes
  `clustered_promotion_gate` in `settled_counterfactual_pnl.json` and in the
  counterfactual settlement report.
- Policy config now carries `promotion_min_independent_target_days`,
  `promotion_min_independent_markets`, and `promotion_cluster_alpha`; the gate
  uses a Bonferroni adjustment over pre-registered strategy/model pairs.
- Tests prove 40 profitable rows from one market-day still block on
  independent-day and market-diversity gates, while identical positive evidence
  across three target days and two markets can pass the clustered gate.

Validation:

- `python -m pytest tests\market\test_taker_bot.py -q`
- `python -m pytest tests\market\test_taker_bot_two_sided.py -q`
- `python -m py_compile src\weather\market\taker_bot_strategy_registry.py src\weather\market\taker_bot_strategy_evaluation.py src\weather\market\taker_bot_bakeoff.py src\weather\market\taker_bot_finalization.py src\weather\market\taker_bot_cli.py`

Related: items 214, 234, 238, 240, 256, 273, 274.
