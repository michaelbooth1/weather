# 48. F-Family Promotion Readiness And Serving Parity [OPEN - GAP DRIVERS + PERMISSION CELLS LIVE]

Goal: separate the implemented family-pooled pipeline from the unresolved proof
that it is ready for broader promotion.

Source: `data/backtest/f_family_promotion_refresh_report.md` now emits explicit
promotion-readiness blockers. The current blockers are aggregate candidate
Brier behind market Brier and eight F markets still in shadow; no
candidate-blocked F markets remain. The current-serving gauntlet is now
non-blocking at `PASS_WITH_SHADOWS` with corpus/fidelity/regression gates
passing; Miami is `SHADOW` with code effect `-0.0004`, so the remaining Miami
gap is market-skill evidence rather than a serving replay regression. The
promotion report now ranks generated candidate gap drivers by market, cutoff
hour, band type, settlement distance, source freshness, and CLOB taxonomy;
feeding those generated cells into the known-edge permission map is split into
item 54.

- [ ] Reduce the F-family aggregate candidate-vs-market Brier gap to <= 0 on
  pinned rows, or keep the gap explicitly marked as a readiness blocker.
- [ ] Move shadow markets to `PROMOTE_CANDIDATE` only when each market beats
  current replay, clears trust/sample gates, and is not worse than market prices
  within the promotion tolerance.
- [ ] Keep candidate-blocked markets at zero; if a future market blocks, keep
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

Acceptance: the F-family promotion report has no readiness blockers, every
promoted market has pinned market-or-better evidence, and any remaining shadow
market has a concrete, generated blocker rather than ambiguous roadmap text.
