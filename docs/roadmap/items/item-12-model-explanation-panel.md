# 12. Model Explanation Panel [COMPLETE]

- [x] Show the major probability drivers for the current top buckets.
- [x] Include quantitative contributions from:
  base climatology, intraday analog set, current max floor, forecast cap,
  wind/cloud analog adjustment, and late-day tail.
- [x] Make the deep dive bucket-agnostic rather than centered on fixed 25 C text.

Codex audit (2026-05-28): partial. A model explanation panel and data-backed
25 C deep dive exist. Issues found: the explanation is mostly descriptive and
does not expose quantitative driver contributions for base climatology,
intraday analogs, wind/cloud adjustment, or late-day tail; the deep dive is
still hardcoded around the 25 C bucket.

Codex update (2026-05-31): unchanged. This is more than UX polish: a
quantitative explanation panel is how we catch overconfident exact-bucket
probabilities before they become bad trades.

Implementation status (2026-06-13): complete. The key enabler is that
`estimate_distribution` already records the running distribution after each
pipeline stage into `distribution_components` (schema
`toronto_distribution_components_v0.1`, item 26). Because every stage is a
running snapshot of the FULL distribution, the per-bucket deltas telescope:
baseline + sum(stage deltas) == the final probability exactly. `driver_waterfall`
(`src/model_presentation.py`) builds that telescoping per-bucket contribution
table over the present running stages (climatology prior -> ML feature blend /
empirical component blend -> live-signal sharpening -> forecast floor/pull ->
settlement-lag floor -> current-observed floor -> late-day lock-in ->
overconfidence calibration); `driver_breakdown(buckets)` formats it unit-aware
plus a standalone-input table (the raw HGB/LR feature model and each empirical
sub-component's independent opinion of each bucket). `get_model_explanation`
now attaches `driver_breakdown` for the top buckets, and `deep_dive_rows` takes
a `focus_bucket` defaulting to the model's current top bucket (falling back to
`key_bucket` only when there is no distribution yet), with the seasonal
base-rate row reading the focus bucket from the per-bucket seasonal
distribution. `app.py` renders the contribution waterfall + standalone-input
tables and the deep-dive title now follows the focus bucket/unit (the hardcoded
"25 C"/"C" strings are gone, fixing them for the 11 F markets too).

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_model_explanation.py tests\test_market_units.py tests\test_toronto_model_bugs.py tests\test_intraday_calibration.py -q`: 50 passed.
- Telescoping verified on a real captured pipeline (June 9 Toronto
  `snapshots.jsonl`): for the top buckets 24/25/26 C, baseline + sum(deltas)
  matched `final_model` to 1e-9.
- `.\venv\Scripts\python.exe -m compileall -q src app.py tests`: passed.
- `.\venv\Scripts\python.exe -m pytest -q`: 365 passed, 34 subtests passed.

This is a presentation/auditability change only -- it reads existing
`distribution_components` and does not alter the served distribution, so no
promotion-gauntlet replay was required.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

