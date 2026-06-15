# 35. Unified Continuous-Density Model [NEW - ENDGAME]

Goal: one model for all cities; C/F becomes serving-only (audit Option B).

- [ ] Predict a fine canonical-grid / continuous max-temp density pooled across
  all 12 cities plus city features.
- [ ] Discretize the density to each market's native bands at serve time
  (finer-than-bands grid => leakage-free, the principled fix the coarse
  canonical-C approach lacked).
- [ ] Port calibration and floors from integer buckets to the continuous
  representation.
- [ ] Prove it rescues the data-poor C/Canada family (Toronto borrows US-city
  structure).

Acceptance: the unified model matches or beats the family models per-market and
lifts the data-poor side.
