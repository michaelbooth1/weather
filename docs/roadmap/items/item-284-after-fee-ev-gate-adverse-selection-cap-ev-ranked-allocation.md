# 284. After-Fee EV Entry Gate, Adverse-Selection Edge Cap, And EV-Ranked Taker Allocation [COMPLETE 2026-06-23 - AFTER-COST EV GATE AND RANKING LIVE]

Goal: stop the taker from entering on pre-fee raw edge and from spending the
budget on its largest model-vs-market disagreements first. Gate entry on
after-fee, after-slippage expected value, treat implausibly large edge as an
adverse-selection warning, and allocate the budget by calibrated after-cost EV.

Source: 2026-06-23 ML audit of the taker bot. `candidate_skip_reason`
(`weather.market.taker_bot_strategy_evaluation`) blocks on raw
`edge < min_edge`, even though `expected_profit_after_friction_per_share =
edge - taker_fee_per_share` is already computed in `apply_taker_budget`
(`weather.market.taker_bot_sizing`) and never used to gate. The same function
sorts candidates by `-edge` and funds them in that order, so the budget flows to
the biggest disagreements first. On settled run
`data/taker_runs/2026-06-21/taker-20260621-bbe63642` the 0.05-0.15, 0.15-0.30,
and >=0.30 raw-edge buckets that received most of the budget went 0/17, 0/22,
and 1/3, and the low/mid-edge buckets settled `-13.73`, `-22.42`, and `-24.99`
USDC. The largest edges were the largest losers.

Why this matters: maximizing `fair - ask` is a max over noisy per-band estimates
across roughly twelve markets, which systematically selects the band where the
model most overstates probability versus a better-calibrated market. Sorting by
raw edge turns the winner's curse into an allocation rule, and a pre-fee gate
admits trades that are negative after the 5% taker fee and slippage. The entry
and ranking logic must price costs and treat oversized disagreement as risk, not
opportunity.

Why it is not already covered: item 167 added risk-adjusted sizing fields but
left the entry gate on raw edge and the candidate sort on `-edge`. Items 234/235/236
add settlement-only quality, bad-tail no-go, and current-high/warm-tail guards,
but those are downstream blockers on specific bad slices; none change the core
entry threshold to after-fee EV, add an adverse-selection cap on oversized edge,
or reorder allocation by after-cost EV. Item 240 builds the fee/slippage/depth
model but does not move the entry gate onto it. Item 283 produces the calibrated
edge this item gates and ranks on.

## Design

1. Replace the raw-edge entry threshold in `candidate_skip_reason` with an
   after-fee, after-slippage EV gate built on the item-240 fee/depth model and
   the item-282 calibrated edge: require
   `expected_profit_after_friction_per_share` (using calibrated fair) at or above
   a configured minimum, and keep raw `edge` only as a diagnostic field.
2. Add an adverse-selection edge cap: when `edge` versus a fresh, liquid market
   exceeds a configured magnitude (a model that is far above the market is more
   likely wrong than right), down-weight or deny rather than prioritize. Treat
   far low-price tails as suspect by default unless the slice carries proven
   skill from item 283/285.
3. Replace the `-edge` candidate sort in `apply_taker_budget` with a sort by
   calibrated, after-cost expected value (and, when available, by the item-284
   per-slice skill weight), so the budget funds the best-evidence opportunities
   instead of the biggest disagreements.
4. Make no-trade first-class: when the item-241 market benchmark recommends
   no-trade for a slice, that recommendation is a hard precondition and the row
   stays `NO_TRADE` regardless of raw edge.
5. Keep the change fail-closed and shadow-first: prove on the item 273
   counterfactual tape and item 238/275 bakeoff that EV gating, the
   adverse-selection cap, and EV ranking improve settlement-scored after-fee PnL
   versus the raw-edge control before changing the active default.

- [x] Move the entry gate onto after-fee/after-slippage calibrated EV and keep
  raw edge as a diagnostic only.
- [x] Add a configurable adverse-selection edge cap with explicit deny/down-weight
  reason codes, including far-tail suspicion.
- [x] Replace the `-edge` candidate sort with calibrated after-cost EV (and skill
  weight where present).
- [x] Make the item-241 market no-trade recommendation a hard entry precondition.
- [x] Prove EV gating + cap + EV ranking on the item 273 counterfactual tape and
  item 238/275 bakeoff with settlement-scored after-fee evidence.

## Completion

Entry now requires calibrated after-cost EV to clear the configured threshold,
including the existing taker fee model and the actual executable fill price
before an order is finalized. Raw `edge` remains in the tape as a diagnostic.
Oversized raw disagreement is surfaced through `adverse_selection_status` and
blocked unless the slice has enough proven skill, and the item-241 market
no-trade recommendation is a hard precondition. Budget allocation now sorts by
calibrated after-cost EV, then skill, instead of descending raw disagreement.

Verification: focused taker tests cover negative after-fee EV skips, market
no-trade blocking, and EV-ranked allocation. The full focused suite passes.

```powershell
pytest tests\market\test_taker_bot.py tests\market\test_taker_bot_two_sided.py -q
```

Acceptance: taker entry is decided on after-fee, after-slippage expected value;
no filled order has negative after-fee EV at entry; oversized edges against fresh
liquid books are denied or down-weighted with an explicit reason code; the budget
is allocated by calibrated after-cost EV rather than descending raw edge; and a
settled replay shows the new gate and ranking improve settlement-scored after-fee
PnL versus the raw-edge control.

Related: items 164, 167, 214, 234, 235, 236, 240, 241, 273, 283.
