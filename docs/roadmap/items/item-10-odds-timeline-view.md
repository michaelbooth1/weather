# 10. Odds Timeline View [COMPLETE]

- [x] Add charts for each price band:
  market price, model probability, and edge through time.
- [x] Highlight snapshots where edge crosses configured thresholds.
- [x] Add a compact table of current biggest positive and negative edges.

Codex audit (2026-05-28): mostly passes. The Streamlit dashboard includes per
band timeline tabs, threshold highlighting, and current positive/negative edge
tables. Issues found: the current-edge table rebuilds labels from nonexistent
`groupItemTitle` fields instead of using `bin_data["label"]`, so labels can be
blank; several warning/status strings show mojibake from corrupted emoji text.

Codex update (2026-05-31): still mostly complete. The cleanup should be small
but should happen before relying on the dashboard during live trading/research:
use canonical bin labels and remove user-visible mojibake.

Implementation status (2026-06-13): cleanup complete. The current-edge table in
`app.py` no longer reads the nonexistent `groupItemTitle` key (which blanked the
"Range" column) nor re-sums only `value`; it now consumes the canonical
`bin_data["label"]` and `bin_probability`, so it is calibrated and range-aware
(F-market 2-degree bands `[value, value_hi]` were previously undercounted to the
lower bucket only) and matches the main model table exactly. The mojibake
concern is already resolved: `clean_label` scrubs `Â°C` / `�C` / `°C` to
` C` defensively, and a full scan of `app.py` + `src/*.py` found no remaining
corrupted glyphs. Regression guard: `tests/test_edge_table.py` (3 tests) pins
the bin-label contract and the range-aware edge probability;
`tests/test_market_units.py` continues to cover the native eq/lte/gte sums.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

