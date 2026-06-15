# 54. Source-Freshness Known-Edge Map Consumption [COMPLETE 2026-06-15 - PERMISSION CELLS LIVE]

Goal: feed the generated source-freshness model-gap cells into the quote
permission layer rather than leaving them as report-only diagnostics.

Source: item 53 now emits source-freshness rows in
`pooled_candidate_replay_latest.json` and
`f_family_promotion_refresh_report.md`; item 47's known-edge map already has a
source-freshness dimension, but it does not yet consume the new promotion
gap cells as explicit model-gap evidence.

- [x] Load promotion-refresh `by_source_freshness` rows into
  `mm_known_edge_map.json` generation as active model-gap cells.
- [x] Show the source-freshness gap rows in `mm_known_edge_map.md`, including
  stale/failed cohorts and their candidate-vs-market deltas.
- [x] Add tests proving a quote permission record can trace back to a
  source-freshness gap cell when source freshness is the limiting evidence.

Acceptance: every source-freshness permission-map cell can cite the generated
promotion source-freshness row that justifies `edge_research`,
`harvest_only`, or `no_quote`.

Implementation update (2026-06-15 UTC): `weather.market.mm_paper` now writes
`mm_known_edge_map_v0.2` records for positive `by_source_freshness` promotion
gap rows, including the generated source-freshness evidence on each permission
cell. `weather.market.mm_policy` and `weather.market.market_making_run` now
carry `source_freshness_state` through quote-intent rows and prefer the matching
source-freshness known-edge record over broad market records when that state is
present. The refreshed `data/backtest/mm_known_edge_map.md` lists five active
source-freshness cells: `all_fresh`, `failed:metar`, `failed:wu_history`,
`failed:wu_history;stale:metar`, and `stale:metar`; all are `harvest_only`
pending paper markout evidence. Validation:
`pytest tests\market\test_mm_paper.py tests\market\test_mm_policy.py tests\market\test_market_making_run.py -q`
passed.
