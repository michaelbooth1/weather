# 51. Model Architecture Health Refactor [NEW - OPEN]

Goal: turn the 2026-06-14 model-logic audit into replay-gated structural
cleanup, without hiding behavioral changes inside refactors.

- [ ] Consolidate analog/today feature extraction with feature-store and live
  extraction by returning a strict/no-default view from the same primitive,
  rather than maintaining a second hand-rolled analog path.
- [ ] Break `estimate_distribution()` into explicit named pipeline stages
  backed by a shared distribution-state object so each live-signal transform is
  individually testable and explainable.
- [ ] Finish the native-unit naming cleanup by moving serving and source code to
  `*_native` accessors, preserving legacy `temp_c` / `*_c` aliases only at I/O
  compatibility boundaries.
- [ ] Replace top-level compatibility imports and scattered `sys.path` mutation
  with package imports and canonical CLI entry points, keeping old wrappers only
  as thin user-facing shims during migration.
- [ ] Keep every step gated by replay identity/fidelity checks and full pytest,
  with any intentional probability deltas baselined before promotion.

Acceptance: no hidden behavior change ships under the health-refactor label;
exact replay deltas are zero or intentionally baselined, the full suite passes,
and item 24 no longer overclaims analog-search consolidation.
