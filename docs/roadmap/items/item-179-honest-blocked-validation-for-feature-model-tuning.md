# 179. Honest Blocked Validation For Feature-Model Tuning [OPEN]

Goal: remove the validation leakage that inflates the HGB-vs-baseline comparison
and biases the per-hour temperature/blend selection.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding H2. In the LOO loop
the ML train mask removes only the single validation row
([feature_model.py:1083](../../../src/weather/calibration/feature_model.py#L1083)),
so adjacent same-season days — highly autocorrelated weather, often the same
`final_bucket` — stay in training. The climatology baseline it is compared to
excludes the **whole validation year**
([feature_model.py:1091](../../../src/weather/calibration/feature_model.py#L1091)).

Why this matters: the asymmetry (a) inflates the reported ML lift, because the
model gets near-neighbour leakage the baseline is denied, and (b) the
temperature/blend grid is *selected* under that leakage, so it trusts the model
more (smaller climatology weight) than honest out-of-sample data would justify.
Combined with item 178's untuned serving smoothing, the model is mis-tuned in two
opposing directions, which makes net calibration hard to reason about. Item 106
already shipped a `blocked_validation` module this can reuse.

## Design

1. Use year-blocked or embargoed splits for **both** the ML model and the
   baseline priors so the comparison is symmetric.
2. Reuse `weather.calibration.blocked_validation` rather than a second split
   implementation.
3. Re-run the temperature/blend grid under the honest split; record the selected
   per-hour `(temperature, blend_weight)` before and after.
4. Report the leakage delta (how much apparent ML lift was leakage) in the
   feature-model report so promotion decisions use honest numbers.

- [ ] Make the ML and baseline arms share one blocked/embargoed split.
- [ ] Re-tune temperature/blend under the honest split and re-export.
- [ ] Add the leakage-delta and honest-LOO section to the feature-model report.
- [ ] Confirm promotion gates consume the honest metrics.

Acceptance: both arms use the same blocked/embargoed split, the report shows
honest LOO metrics and the re-selected per-hour `(temperature, blend_weight)`,
and any promotion claim cites the honest numbers.

Related: items 106, 178; `[[model-audit-2026-06-09]]`.
