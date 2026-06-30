# 52. Miami Current-Serving Replay Regression Triage [COMPLETE 2026-06-15 - MIAMI SERVING BLOCK CLEARED]

Goal: resolve the one remaining current-serving gauntlet `BLOCK` market without
turning a live disabled paid-provider support signal into an unverified settlement floor.

Source: `data/backtest/promotion_gauntlet_latest_report.md` is now
`PASS_WITH_SHADOWS`: corpus pin, fidelity, and regression gates pass, and no
serving market is blocked. Miami is `SHADOW`, not `BLOCK`, with replayed Brier
`0.0327` versus recorded `0.0331` (code effect `-0.0004`) and market Brier
`0.0238`. The remaining Miami gap is not a serving regression; it is the
ordinary market-skill shadow evidence tracked by item 48.

- [x] Build a WU `max_since_7am` validation slice by market/day/cutoff:
  compare live captured `wu_max_since_7am_c` to final WU history high and
  settlement labels before using it as a hard market-band support bound.
- [x] Add a Miami failure decomposition for the positive code-effect rows by
  cutoff hour, settlement distance, band type, and source-freshness state.
- [x] Test any candidate fix on the exact Miami replay rows and the full pinned
  promotion corpus; no fix can regress the aggregate gauntlet or turn other
  serving markets back to `BLOCK`.
- [x] Keep current serving conservative after the block clears: Miami remains
  `SHADOW` until it is market-better on pinned rows, and item 48 owns that
  readiness proof.

Acceptance: the current-serving gauntlet has no unexplained market-level
`BLOCK`, or the Miami block is backed by a generated source-validation report
and a scoped model-gap task rather than ambiguous F-family readiness text.

Implementation update (2026-06-15 UTC): added
`src.weather.reporting.wu_max_since_7_validation` and the
`src.wu_max_since_7_validation` CLI wrapper. The generated
`data/backtest/wu_max_since_7_validation_report.md` validates 6,989 pinned
snapshots against corpus settlement labels. Miami has 557 pinned snapshots, 555
comparable WU max rows, **100.0% safe-as-support-bound**, and **0 above-final
WU max rows**; source-freshness state is derived from pinned replay input
metadata (`all_fresh` 533 snapshots, `failed:wu_history` 24 snapshots). The
current-serving replay path now carries `source_freshness_state`, and the
promotion gauntlet renders source-freshness slices for overall and blocking
market drilldowns. Unit coverage: `tests/reporting/test_wu_max_since_7_validation.py`
and the gauntlet decomposition test in `tests/reporting/test_promotion_corpus.py`.
`src.weather.model.model_distribution` now applies `wu_current.max_since_7am_c`
as a hard support floor only for markets in
`VALIDATED_WU_MAX_HARD_FLOOR_MARKETS`, currently Miami, and only when the
current max exceeds the WU history floor; `ML_MODEL_VERSION` is bumped to
`v0.5.9` for that serving behavior. The full F-family validation was not
promoted because non-Miami/all-family WU max rows still include over-final
cases.

Acceptance update (2026-06-15 UTC): the refreshed
`data/backtest/promotion_gauntlet_latest_report.md` and
`data/backtest/f_family_promotion_refresh_report.md` show current serving at
`PASS_WITH_SHADOWS` with no blocked markets. Miami serving replay is `SHADOW`
with replayed Brier `0.0327`, recorded Brier `0.0331`, market Brier `0.0238`,
and code effect `-0.0004`; all other serving markets are either `PASS` or
`SHADOW`. Item 48 remains open for aggregate candidate market skill and shadow
markets, not for the cleared Miami serving block.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - MIAMI SERVING BLOCK CLEARED`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

