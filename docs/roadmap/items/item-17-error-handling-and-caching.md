# 17. Error Handling And Caching [COMPLETE]

- [x] Add per-source retries with backoff for live HTTP GETs.
- [x] Preserve last-good live payloads when a source fails.
- [x] Enforce an age cap on last-good live payloads.
- [x] Separate short TTLs for fast sources from slower/stabler sources.
- [x] Log snapshot-loop capture failures into a local diagnostics file.
- [x] Add structured source-level diagnostics for partial live-source failures.

Codex update (2026-05-31): `request_with_retries()` and last-good caching now
handle the biggest transient-source risk. The next accuracy risk is staleness:
different feeds age differently, and the model should not treat a stale forecast
and a stale settlement-source row the same way.

Implementation status (2026-06-13): complete. `SOURCE_CACHE_TTL_MINUTES`
(`src/model_constants.py`) replaces the single 90-minute cap with per-source
TTLs: observation/settlement feeds expire fast (`wu_history` / `wu_current` /
`eccc_swob` 30 min, `metar` 75 min) because a stale "current" reading is the
dangerous case, while slow-moving forecasts keep a longer window
(`weather_forecast` / `open_meteo` / `nws_hourly` 90 min, `eccc_citypage` /
`global_ensemble` 120 min); unlisted sources fall back to the 90-minute global
cap, so nothing loosened by accident. `blend_with_last_good` now uses
`source_cache_ttl_minutes(name)` for the freshness gate and stamps each blended
source with a `status` (`fresh` / `stale_cache` / `failed`) plus `ttl_minutes`.
`source_diagnostics(blended)` returns a structured, queryable per-source list
(source, status, fetched_at, age_minutes, ttl_minutes, error) for partial
live-source failures; `build()` surfaces it as `source_diagnostics`, and the
dashboard freshness panel shows the per-source TTL column. This tightens the
previous behavior only (a 45-min-stale `wu_current` is now dropped instead of
trusted, while the same 45-min-old forecast is still served).

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_source_cache_ttl.py -q`: 6 passed,
  including the tightened-observation vs retained-forecast contrast and the
  structured-diagnostics shape.
- `.\venv\Scripts\python.exe -m pytest -q --deselect tests/test_feature_skew.py::TestRampWallOffsets::test_ramp_hours_sample_extended_offsets`:
  373 passed, 34 subtests (the one deselected test is unrelated in-flight item-40
  work). `compileall` passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

