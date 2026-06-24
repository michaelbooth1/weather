# 254. Extract Serving-Safe Variant-Prediction Runtime From Calibration [COMPLETE 2026-06-23 - SERVING RUNTIME EDGE REMOVED AND ARCHITECTURE RATIFIED]

Goal: remove the transitional `collection -> calibration` package edge by moving
serving-safe prediction helpers into a runtime owner module, so live capture no
longer imports training/replay modules.

Source: `docs/roadmap/project-structure-action-plan-2026-06-22.md` Step 1.2
(fallback path) and the architecture ratchet
(`tests/operations/test_import_architecture.py`). The ratchet is currently green
because the edge is **documented as transitional**, not because it is clean.

Previous state: `weather.collection.live_variant_predictions` imported
serving-time prediction helpers from calibration modules:

- from `weather.calibration.pooled_feature_model`: `band_prediction_record`,
  `apply_band_postprocessing`, `predict_band_rows_for_bundle`
- from `weather.calibration.pooled_candidate_replay`:
  `apply_continuous_density_calibration`,
  `density_band_probability_from_distribution`, `microstructure_feature_frame`

Why this matters: `weather.collection` owns live capture/runtime; `weather.calibration`
owns training, replay, promotion-candidate scoring, and artifact writing. A live
capture path importing calibration couples the runtime to heavy training modules
(`pooled_feature_model` is ~5,000 lines) and blurs the ownership boundary. The
fallback documents the edge with a named removal route rather than blessing it as
permanent.

## Implementation

1. Added `weather.model.variant_prediction_runtime` as the runtime owner for
   pooled live variant prediction helpers.
2. Repointed `weather.collection.live_variant_predictions` to the runtime owner.
3. Re-exported the same helpers from calibration facades so existing callers keep
   stable imports while sharing the model-owned runtime implementation.
4. Removed `("collection", "calibration")` from `TRANSITIONAL_PACKAGE_EDGES` and
   from `docs/operations/package-boundaries.md`.
5. Kept CLI, replay orchestration, training, artifact writing, and report
   generation in `weather.calibration`.

- [x] Add the serving-safe runtime module and move the six helpers.
- [x] Repoint collection and calibration imports to the runtime module.
- [x] Remove the transitional edge from the test and the boundaries doc.
- [x] Run `tests/collection/test_live_variant_predictions.py`,
  `tests/calibration/test_pooled_candidate_replay.py`, and
  `tests/operations/test_import_architecture.py`.

Acceptance: `collection -> calibration` no longer appears in observed package
edges, the architecture ratchet stays green without the transitional entry, and
serving prediction helpers are owned by a runtime module rather than calibration.

## 2026-06-23 Completion Note

The named verification command was run:

`python -m pytest tests\collection\test_live_variant_predictions.py tests\calibration\test_pooled_candidate_replay.py tests\operations\test_import_architecture.py -q`

Result: `73 passed`. The architecture ratchet is green with the
serving-safe runtime helpers owned by `weather.model.variant_prediction_runtime`
and the transitional `collection -> calibration` package edge removed.

Related: items 96, 51; `docs/roadmap/project-structure-action-plan-2026-06-22.md`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - SERVING RUNTIME EDGE REMOVED AND ARCHITECTURE RATIFIED`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

