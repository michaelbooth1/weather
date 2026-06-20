# 177. Core Model Validation And Serving Skew Repair [OPEN]

Goal: close the model-quality issues surfaced by the core model audit that are
not already covered by the 10-minute weak-slot and late-day lock-in items.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` and the 2026-06-20 full
repository cleanup audit. The audit identifies train/serve skew around ordinal
smoothing, validation leakage risk in leave-one-out comparisons, hard-coded
serving fallbacks, forecast double-use, correlated fallback assumptions, broad
per-city priors, and unbounded cache state.

Why this matters: cleanup should not only make the repository smaller. The
model runtime also needs clearer validation and serving contracts so refactors
do not preserve hidden calibration defects.

## Design

1. Convert each model audit finding into a measurable experiment or serving
   parity check.
2. Prioritize issues that can create train/serve skew or overstate validation
   evidence.
3. Keep market-aware overlays separate from price-free weather-model
   calibration evidence.
4. Add before/after reports for Brier, log loss, winner probability, weak-slot
   performance, and per-market regressions.
5. Update promotion gates only after the repaired validation path proves a
   candidate improves current serving behavior.

- [ ] Add a stage-attribution report for the heuristic stack so each smoothing
  or postprocessing layer has measured impact.
- [ ] Replace row-level leave-one-out validation with honest year-blocked or
  embargoed validation where leakage risk exists.
- [ ] Either train the ordinal smoothing behavior into the objective or remove
  the serving-only smoothing layer.
- [ ] Replace hard-coded Celsius fallback constants with explicit missingness
  that the trained imputer/model path handles.
- [ ] Decide whether forecast pull applies only to fallback behavior or to the
  main model path, and remove dead capture-hour semantics.
- [ ] Collapse correlated forecast-source fallbacks into source-family clusters
  before treating evidence as independent.
- [ ] Replace broad uniform temperature priors with per-market climatological
  priors.
- [ ] Bound or invalidate class-level climatology caches.
- [ ] Finish or retire the half-adopted continuous-density path.

Acceptance: validation evidence uses an honest blocked split, serving behavior
matches trained behavior or has explicit measured postprocessing, and promotion
reports show no hidden regression in the weak-slot, per-market, or late-day
lock-in slices.

