# 300. Current Exchange Economics And Rule-Drift Gate [OPEN 2026-06-24 - PAPER AND PROMOTION EVIDENCE CAN USE STALE PLATFORM ASSUMPTIONS]

Goal: keep Polymarket fee, rebate, reward, tick-size, minimum-order, and order
semantics assumptions current for taker and maker paper evidence, promotion
gates, and live-readiness checks.

Source: 2026-06-24 system-level roadmap audit. Item 45 requires a current
platform-verification artifact before live market-making orders. Item 240 adds
fee/slippage/depth accounting, item 259 verifies current-run profitability
fields, and item 284 moves taker entry onto after-cost EV. Those items still
consume configured exchange-economics assumptions once the run exists; no active
item owns a daily freshness and drift gate for the assumptions used by paper
evidence, bakeoffs, promotion reports, and maker/taker run summaries.

Owner/package: `weather.market.market_making_preflight`,
`weather.market.mm_paper`, `weather.market.taker_bot_bakeoff`,
`weather.market.taker_edge_permission`, and `weather.operations.daily_refresh`.

Why this matters: a strategy can look profitable only because the paper scorer
used a stale taker fee, obsolete reward formula, wrong tick size, or outdated
minimum-order rule. The live platform gate protects real order submission, but
model and trading promotion decisions can still be distorted before live mode if
the paper evidence is scored against stale platform assumptions.

Why it is not already covered: item 45 is scoped to live platform/account
verification and only blocks live-pilot submission. Item 240 defines the
friction model but does not prove the fee schedule or exchange rules are
current. Item 259 verifies that run artifacts contain profitability fields, not
that the underlying assumptions are fresh. Item 260 checks maker paper-score
freshness, not exchange-economics freshness. Item 284 consumes after-cost EV but
does not validate the currentness of the fee, rebate, reward, or order-rule
snapshot it depends on.

## Design

1. Define a versioned `exchange_economics_snapshot` artifact with platform
   surface, fee model/rates, maker rebate and reward formulas, tick size,
   minimum order size, API/order semantics, effective date, verified timestamp,
   source URLs, and source-hash metadata.
2. Make daily refresh, taker bakeoff, maker paper scoring, profitability
   verification, and live preflights fail closed or downgrade evidence to
   `paper_stale_exchange_economics` when the snapshot is stale, missing, or
   target-date/platform mismatched.
3. Thread the snapshot id/hash into taker and maker run summaries, order tapes,
   paper score reports, bakeoff reports, and promotion artifacts.
4. Add a drift report that compares the latest snapshot to the prior accepted
   snapshot and flags material changes that require recent paper evidence to be
   rescored.
5. Keep live order submission gated by item 45, but require this item before
   paper or shadow trading evidence can justify promotion or live-readiness.

- [ ] Register the exchange-economics snapshot schema and source metadata.
- [ ] Add freshness and target-date/platform validation in daily refresh,
  taker bakeoff, maker paper scoring, and trading preflights.
- [ ] Persist the snapshot id/hash through taker and maker evidence artifacts.
- [ ] Add a material-drift report and rescore-required blocker.
- [ ] Add tests for stale fees, changed reward formulas, tick/min-size drift,
  and paper-evidence downgrade behavior.

Acceptance: no taker or maker promotion, profitability claim, or live-readiness
decision can rely on stale exchange-economics assumptions; every trading run and
paper report cites the rule snapshot it used; material fee/reward/order-rule
drift produces a rescore-required blocker; and live order submission remains
behind the existing item-45 platform/account gate.

Related: items 43, 44, 45, 55, 67, 214, 238, 240, 259, 260, 273, 278, 283, 284, 285.
