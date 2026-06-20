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

Decomposition (2026-06-20): the seven calibration findings now have their own
standalone OPEN items so each carries its own status, acceptance, and owner.
This item is the **parent tracker** for that set plus the two leftover
state-cleanup tasks it still owns directly.

## Delegated findings (tracked as standalone items)

- [ ] Item 178 — Serving-Time Ordinal Smoothing Train/Serve Skew (H1).
- [ ] Item 179 — Honest Blocked Validation For Feature-Model Tuning (H2).
- [ ] Item 180 — Unit-Safe Missing-Feature Handling (M1).
- [ ] Item 181 — Forecast Signal Double-Counting And Dead Capture-Hour (M2).
- [ ] Item 182 — Distribution Stage-Attribution Harness (M3, measurement
  substrate for the rest).
- [ ] Item 183 — Correlated Forecast-Source Clustering On Fallback Path (M4).
- [ ] Item 184 — Per-Market Climatological Fallback Prior (M5).

## Retained scope (owned here)

1. Keep market-aware overlays separate from price-free weather-model calibration
   evidence across the delegated items.
2. Use item 182's stage-attribution harness as the shared before/after report
   (Brier, log loss, winner probability, weak-slot, per-market regressions).
3. Update promotion gates only after the repaired validation path proves a
   candidate improves current serving behavior.

- [ ] Bound or invalidate the class-level climatology cache
  (`_historical_target_cache`, unbounded by `market:date`).
- [ ] Finish or retire the half-adopted continuous-density path (coordinate with
  item 35).

Acceptance: items 178–184 are resolved, validation evidence uses an honest
blocked split, serving behavior matches trained behavior or has explicit measured
postprocessing, the climatology cache is bounded, the continuous-density path is
finished or retired, and promotion reports show no hidden regression in the
weak-slot, per-market, or late-day lock-in slices.

