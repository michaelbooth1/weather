# 53. Candidate Source-Freshness Gap Attribution [COMPLETE 2026-06-15 - REPORT ATTRIBUTION LIVE]

Goal: make stale/failed/fresh weather-source state a first-class replay slice
for candidate promotion reports.

Source: `data/backtest/f_family_promotion_refresh_report.md` now generates
candidate gap drivers for market, cutoff hour, band type, settlement distance,
source freshness, and CLOB taxonomy. The old "source-freshness gap drivers are
not available" note is gone.

- [x] Persist or derive per-row freshness state from `source_status_long.csv`,
  replay input source metadata, source-cache age, or source TTL diagnostics into
  candidate replay rows.
- [x] Add `by_source_freshness` to
  `data/backtest/pooled_candidate_replay_latest.json` and include those rows in
  the promotion refresh `Candidate Gap Drivers` table.
- [x] Add tests proving fresh/stale/failed source states are grouped, ranked by
  excess Brier rows, and emitted in both JSON and Markdown reports.

Acceptance: the F-family promotion refresh report includes source-freshness gap
rows when they contribute positive candidate-vs-market error, and no longer
emits the "not available in the candidate replay rows yet" note.

Implementation update (2026-06-15 UTC): `src.pooled_candidate_replay` now
groups replay-input source states into `source_freshness_state`, scores
`by_source_freshness`, and renders a `By Source Freshness` candidate report
slice; `src.promotion_refresh` preserves the slice and can rank it in
`Candidate Gap Drivers` plus a dedicated `Source Freshness Slice` table.
The refreshed live-corpus candidate replay has seven source-freshness groups
over 6,130 pinned F-family snapshots and zero missing source records; the
largest positive stale/failed groups are `failed:wu_history` (+0.0107 versus
market on 2,695 rows), `failed:wu_history;stale:metar` (+0.0119 on 253 rows),
and `stale:metar` (+0.0040 on 616 rows). Validation:
`pytest tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py -q`
passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - REPORT ATTRIBUTION LIVE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

