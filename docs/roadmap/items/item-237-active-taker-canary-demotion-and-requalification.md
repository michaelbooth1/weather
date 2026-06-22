# 237. Active Taker Canary Demotion And Requalification [COMPLETE 2026-06-22 - CANARY PAPER-ONLY UNTIL REQUALIFIED]

Goal: demote or requalify `low_price_tail_capped` before it can remain the
active default or be considered for live use.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
The active candidate has no settlement-scored June 22 sample yet, June 22 has a
high low-price-tail fill fraction, June 21 low-price-tail fills lost, and the
June 20 bakeoff evidence was partial-quality rather than robust promotion
evidence.

Why this matters: the canary lifecycle should roll back when current evidence
violates its own promotion gates. Leaving the candidate active while it lacks
settled proof lets an unqualified tail-heavy strategy accumulate more bad
paper or live fills.

## Design

1. Mark `low_price_tail_capped` paper-only and non-promotable until it has
   enough settled fills, settled markets, and full after-fee scoring.
2. Require `3-5` settled days with no unresolved-order blocker, acceptable
   low-tail fill fraction, and nonnegative per-market stability before active
   default promotion.
3. Add automatic rollback or demotion when a candidate violates settlement,
   unresolved-order, or tail-exposure gates after cutover.
4. Keep the candidate in champion/challenger bakeoff so future evidence can
   requalify it without manual bias.

- [x] Set the active taker lifecycle report to flag `low_price_tail_capped` as
  paper-only until requalified.
- [x] Add a demotion trigger for unresolved orders, excessive tail fraction, or
  missing settlement-scored evidence after canary cutover.
- [x] Require multi-day settlement-scored evidence and after-fee PnL before the
  strategy can become active default again.
- [x] Add tests showing the June 22 no-settlement/high-tail shape blocks
  active promotion.

Acceptance: `low_price_tail_capped` cannot remain or become an active default
based on partial bakeoff or MTM-only evidence, and failed follow-up evidence
automatically blocks or rolls back the canary.

Related: items 209, 214, 234, 235, 238, 240.

## Closeout 2026-06-22

Implemented in `weather.market.taker_bot_strategy_registry`,
`weather.market.taker_bot_finalization`, `weather.market.taker_bot_cli`, and
`weather.market.taker_bot_tape_io`.

- Candidate canaries now carry explicit paper-only and requalification-required
  fields in lifecycle payloads, next-run policy gates, finalized summaries, and
  settlement reports.
- Default canary promotion now requires multi-day complete-label evidence and
  explicit after-fee PnL evidence before `promoted_default`.
- Post-cutover canaries block/roll back when bakeoff evidence shows unresolved
  or unscored orders, excessive low-tail fraction, or no settlement-scored
  evidence.
- Temporary snapshot roots no longer inherit the workspace live observation
  status by accident, and empty normalization fields no longer erase
  snapshot-provided current-high trust fields.

Verification:

- `python -m pytest tests\market\test_taker_bot.py tests\reporting\test_taker_tail_casebook.py tests\operations\test_taker_bot_daily_roll.py tests\operations\test_schema_registry.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_learning.py tests\reporting\test_daily_progress_ledger.py -q`
  - 81 passed, 5 subtests passed.
