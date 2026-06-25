# 86. No-Market Candidate Bakeoff And Promotion Lane Selection [COMPLETE 2026-06-16 - ITEM50 SHADOW LANE SELECTED]

Goal: choose the canonical no-market promotion lane from a clean paired bakeoff
instead of comparing whichever variant artifact was most recently refreshed.

Source: `docs/research/MODEL_VARIANT_AUDIT_2026-06-16.md`. The audit found
that `item50_pooled_forecast_v3_candidate`, dynamic source-state,
exact-winner catch-up, conservative bridge, and Miami current fallback all have
useful no-market evidence, but they are not yet compared in one clean active
variant report.

Why this is missing: item 70 through item 82 proved several narrow hypotheses,
but active no-market candidates are now spread across several historical
artifacts. Promotion needs one clean lane selection report with stale alpha and
smoke variants excluded from the headline comparison.

- [x] Generate a no-market multi-variant report containing the current serving
  control, item 50, item 70, item 71, item 73 policy bridge, and item 82 Miami
  fallback behavior with duplicate controls removed.
- [x] Gate the bakeoff on daily-first Brier, log loss, ECE, per-market deltas,
  source-state slices, all-fresh slices, and candidate gap versus market.
- [x] Decide whether one no-market variant becomes the canonical promotion
  candidate or whether multiple variants remain in predeclared shadow lanes.
- [x] Archive superseded alpha and smoke artifacts out of active headline
  reports after the lane decision.
- [x] Record the selected lane and rationale in item 48 promotion readiness.

Acceptance: the no-market promotion candidate is selected from a clean,
predeclared active bakeoff with comparable paired evidence and no duplicate
control accounting.

Completion update 2026-06-16:

- Generated `data/backtest/item86_no_market_bakeoff_multi_variant_shadow_report.md`
  and `data/backtest/item86_no_market_bakeoff_multi_variant_shadow_long.csv`
  from item 50, item 70, item 71, item 73 conservative bridge, and item 82
  Miami fallback rows. The summary JSON omits embedded row arrays; the long CSV
  is the row-level artifact.
- Report status is `OK`: 404,580 scored rows, 67,430 unique observations, row
  multiplier `6.0000`, five active no-market headline variants, one control,
  zero warnings, and zero errors.
- The selected no-market lane is `item50_pooled_forecast_v3_candidate` with
  daily-first delta versus current `-0.0016`, ECE `0.0324`, and daily-first
  delta versus market `+0.0041`.
- The selection status is `SHADOW_LANE_SELECTED`, not promotion-ready. Item 50
  is the canonical no-market shadow lane because it is the best active
  no-market candidate versus current replay, but it still fails the market-gap
  gate and the current long-form item-69 rows do not carry source-freshness
  slice columns. Promotion readiness remains governed by item 48.
- Alpha and smoke exact-winner/source-state variants are archived in
  `config/model_variant_registry.json` and excluded from active headline track
  summaries.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - ITEM50 SHADOW LANE SELECTED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

