# 48. F-Family Promotion Readiness And Serving Parity [PARTIAL 2026-06-18 - EMPIRICAL PROMOTION BLOCKED]

Goal: separate the implemented family-pooled pipeline from the unresolved proof
that it is ready for broader promotion.

Source: `data/backtest/f_family_promotion_refresh_report.md` now emits explicit
promotion-readiness blockers. The current report generated
`2026-06-16T05:44:55Z` keeps readiness `OPEN`: aggregate candidate Brier trails
market Brier by `+0.0042`, seven F markets remain `KEEP_SHADOW`, and no F
market is `BLOCK_CANDIDATE`. Miami's candidate-block remediation was completed
in item 82 by holding Miami on current-serving probabilities. The refreshed
promotion report ranks generated candidate gap drivers by market, cutoff hour,
band type, settlement distance, and source freshness; the latest canonical
refresh intentionally skipped the serving gauntlet and CLOB overlay, while the
Item 82 full replay preserves the CLOB-taxonomy diagnostic evidence.

- [x] Reduce the F-family aggregate candidate-vs-market Brier gap to <= 0 on
  pinned rows, or keep the gap explicitly marked as a readiness blocker.
- [ ] Move shadow markets to `PROMOTE_CANDIDATE` only when each market beats
  current replay, clears trust/sample gates, and is not worse than market prices
  within the promotion tolerance.
- [x] Keep candidate-blocked markets at zero; if a future market blocks, keep
  the generated `BLOCK_CANDIDATE` detail and split market-specific remediation
  into its own roadmap item.
- [x] Add generated decomposition for the largest candidate-vs-market gap
  drivers by market, cutoff hour, band type, settlement distance, and CLOB
  taxonomy in the promotion refresh `Candidate Gap Drivers` table.
- [x] Feed those generated gap-driver cells into item 47's known-edge map and
  paper permission report; tracked by item 54.
- [x] Add source-freshness gap attribution once replay rows carry freshness
  state; completed in item 53.
- [ ] Keep the promotion refresh report as the acceptance artifact: readiness is
  not complete until `readiness.status` is `READY`, serving parity is
  non-blocking, and no F market has an unexplained `KEEP_SHADOW` or
  `BLOCK_CANDIDATE`.

Implementation update (2026-06-15 UTC): `src.promotion_refresh` preserves
candidate replay slices and writes a `Candidate Gap Drivers` table plus a
dedicated `Source Freshness Slice` table to
`data/backtest/f_family_promotion_refresh_report.md`. The current top generated
drivers include at-settlement rows, CLOB taxonomy `wu_lag_catchup_miss`, exact
bands, the aggregate `all_fresh` source-freshness cohort, 07:00 rows, and
market-level gaps for Seattle/NYC/Miami. The source-freshness slice also
surfaces failed/stale groups including `failed:wu_history`,
`failed:wu_history;stale:metar`, and `stale:metar`.

Permission-cell update (2026-06-15 UTC): item 54 completed the consumption path
from generated source-freshness gap rows into `mm_known_edge_map.json`,
`mm_known_edge_map.md`, quote-intent permission records, and market-making run
preflight diagnostics. Item 48 remains open for the underlying promotion
readiness blockers: aggregate candidate-vs-market Brier, per-market shadow
actions, and unexplained `KEEP_SHADOW` / `BLOCK_CANDIDATE` cells.

Miami block update (2026-06-16 UTC): item 82 cleared the Miami
`BLOCK_CANDIDATE` cell with an explicit current-serving fallback. The canonical
promotion refresh generated `2026-06-16T05:44:55Z` now reports 4 promote, 7
shadow, and 0 blocked F markets. Miami remains `KEEP_SHADOW` with candidate
Brier equal to current Brier (`0.025046`, delta `+0.000000`) and still trails
market Brier (`0.023776`). Item 48 remains open for readiness because the
aggregate candidate still trails market by `+0.0042` and seven F markets remain
shadow.

Readiness-detail update (2026-06-16 UTC): `src.promotion_refresh` now carries
generated `shadow_market_details` / `blocked_market_details` in
`readiness`, and the Markdown report renders `Shadow/Block Explanation Detail`
directly under `Promotion Readiness Blockers`. The refreshed artifact generated
`2026-06-16T08:32:56Z` still reports 4 promote, 7 shadow, and 0 blocked F
markets, with aggregate candidate-vs-market Brier still blocked at `+0.0042`.
The seven shadow markets now have explicit generated blockers in the readiness
section:

- Austin, Chicago, NYC, and Seattle: not proven better than market on pinned
  rows.
- Dallas and Miami: not proven better than current replay.
- San Francisco: not proven better than current replay and not proven better
  than market on pinned rows.

Item 48 remains open for empirical readiness: the candidate must either clear
the aggregate market-price gap and move shadow markets through the gates, or
continue to report those blockers without serving promotion.

No-market lane selection update (2026-06-16 UTC): item 86 selected
`item50_pooled_forecast_v3_candidate` as the canonical no-market shadow lane
from `data/backtest/item86_no_market_bakeoff_multi_variant_shadow_report.md`.
The report is clean (`OK`, zero warnings/errors) and compares item 50, item 70,
item 71, item 73 policy bridge, item 82 Miami fallback, and the control over the
same 67,430 unique observations. Item 50 is best among active no-market
variants versus current replay (`-0.0016` daily-first Brier delta), but it still
trails market by `+0.0041`, so this is a shadow-lane decision rather than a
promotion approval. Item 48 remains open until the selected lane clears the
aggregate market-price gap and per-market shadow blockers.

Acceptance: the F-family promotion report has no readiness blockers, every
promoted market has pinned market-or-better evidence, and any remaining shadow
market has a concrete, generated blocker rather than ambiguous roadmap text.

## 2026-06-18 audit disposition

The Python audit found the promotion-readiness machinery, generated blocker
details, source-freshness attribution, shadow-lane selection, and report
acceptance artifact already implemented. The remaining unchecked boxes are not
missing code paths: they require the candidate to clear the generated readiness
gates and move shadow markets to `PROMOTE_CANDIDATE` only after pinned
market-or-better evidence exists. Until the replay artifact reports
`readiness.status` as `READY`, this item correctly remains an empirical
promotion blocker.
