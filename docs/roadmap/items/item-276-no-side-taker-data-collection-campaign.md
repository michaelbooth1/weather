# 276. NO-Side Taker Data Collection Campaign [COMPLETE 2026-06-23 - REAL NO-SIDE COUNTERFACTUAL CAMPAIGN LIVE]

Goal: collect actual settlement-scored NO-side taker evidence now that real
NO-token book fields and promotion gates exist.

Source: item 257 completed real NO-book depth capture and live-scale gates, but
the June 21-23 taker audit found no `NO_BUY` fills in the settled sample and no
NO-side rows in the current active run. The two-sided/fade arm remains a
promising research path, but it has not yet produced actual post-gate evidence.

Why this matters: the YES-side low-tail strategy has repeatedly lost. NO-side
fades may harvest the opposite error mode, but only if the bot captures real
NO-book liquidity and scores actual or counterfactual NO decisions against
settlement.

## Design

1. Include the two-sided/fade strategy in the daily paper and counterfactual
   taker campaign with real NO-book depth required for countable evidence.
2. Report real-NO-book eligible rows, synthetic-only rows, stale NO-book rows,
   NO-side would-buy rows, and actual NO-side fills.
3. Settlement-score NO-side decisions separately from YES-side decisions and
   compare against no-trade and market-top baselines.
4. Keep synthetic complement rows as diagnostics only; they cannot count toward
   live qualification.
5. Add per-market and per-hour slice summaries so NO-side evidence does not get
   diluted by markets where real NO liquidity is absent.

- [x] Add the two-sided/fade arm to the post-fix daily campaign by default in
  paper/counterfactual mode.
- [x] Add NO-side coverage and stale-depth metrics to taker reports.
- [x] Settlement-score NO-side actual and counterfactual rows separately.
- [x] Add promotion tests proving synthetic-only NO evidence remains
  non-countable.

Acceptance: the taker evidence ledger shows whether NO-side fades have real
settlement edge using real NO-book depth, with synthetic-only rows excluded
from live promotion.

## Implementation

- Added `fade_overpriced` to the default taker bakeoff/counterfactual campaign
  so the shadow tape collects NO-side decisions without changing key handling or
  live order posting.
- Added `no_side_campaign_summary` with real NO-book, synthetic book, stale
  book, depth-eligible, would-buy, settled, P&L, by-market, and by-hour metrics.
- Added NO-side campaign sections to the live paper report, settlement report,
  and counterfactual settlement report.
- Surfaced counterfactual NO-side status and countable would-buy counts in run
  and finalized summaries.
- Added regression coverage proving real NO-token books produce countable,
  settlement-scored NO-side counterfactual evidence, while synthetic-only NO
  evidence stays non-countable and blocks promotion.

Validation:

- `python -m py_compile src\weather\market\taker_bot_strategy_registry.py src\weather\market\taker_bot_bakeoff.py src\weather\market\taker_bot_cli.py src\weather\market\taker_bot_reporting.py src\weather\market\taker_bot_finalization.py tests\market\test_taker_bot.py`
- `python -m pytest tests\market\test_taker_bot.py -q` -> 51 passed, 5 subtests passed.
- `python -m pytest tests\market\test_taker_bot_two_sided.py -q` -> 14 passed.

Related: items 253, 257, 273, 274, 275.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - REAL NO-SIDE COUNTERFACTUAL CAMPAIGN LIVE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

