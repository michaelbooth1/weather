# 254. Extract Serving-Safe Variant-Prediction Runtime From Calibration [OPEN]

Goal: remove the transitional `collection -> calibration` package edge by moving
serving-safe prediction helpers into a runtime owner module, so live capture no
longer imports training/replay modules.

Source: `docs/roadmap/project-structure-action-plan-2026-06-22.md` Step 1.2
(fallback path) and the architecture ratchet
(`tests/operations/test_import_architecture.py`). The ratchet is currently green
because the edge is **documented as transitional**, not because it is clean.

`weather.collection.live_variant_predictions` imports serving-time prediction
helpers from calibration modules:

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

## Design

1. Create a runtime owner module, e.g. `weather.model.variant_prediction_runtime`
   (or `weather.model.pooled_candidate_runtime`).
2. Move only the serving-safe, pure prediction helpers listed above into it.
3. Update `weather.collection.live_variant_predictions` to import from the new
   runtime module.
4. Update the calibration modules to import those helpers from the runtime module
   instead of defining runtime behaviour themselves.
5. Keep CLI, replay orchestration, training, artifact writing, and report
   generation in `weather.calibration`.
6. Remove `("collection", "calibration")` from `TRANSITIONAL_PACKAGE_EDGES` in
   the architecture test and from the transitional list in
   `docs/operations/package-boundaries.md`.

- [ ] Add the serving-safe runtime module and move the six helpers.
- [ ] Repoint collection and calibration imports to the runtime module.
- [ ] Remove the transitional edge from the test and the boundaries doc.
- [ ] Run `tests/collection/test_live_variant_predictions.py`,
  `tests/calibration/test_pooled_candidate_replay.py`, and
  `tests/operations/test_import_architecture.py`.

Acceptance: `collection -> calibration` no longer appears in observed package
edges, the architecture ratchet stays green without the transitional entry, and
serving prediction helpers are owned by a runtime module rather than calibration.

Related: items 96, 51; `docs/roadmap/project-structure-action-plan-2026-06-22.md`.
