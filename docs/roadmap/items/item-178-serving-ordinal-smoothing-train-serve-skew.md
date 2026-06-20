# 178. Serving-Time Ordinal Smoothing Train/Serve Skew [OPEN]

Goal: eliminate the train/serve skew where serving de-sharpens the feature-model
distribution with an ordinal-smoothing layer that the per-hour temperature/blend
tuning never saw.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding H1. Serving calls
`ordinal_smooth_distribution(sigma=0.75, blend_weight=0.50)` on the HGB output
([model_distribution.py:472](../../../src/weather/model/model_distribution.py#L472))
before the climatology blend, but `fit_temperature_blend_grid`
([feature_model.py:1237](../../../src/weather/calibration/feature_model.py#L1237),
[feature_probability_calibration.py:64](../../../src/weather/calibration/feature_probability_calibration.py#L64))
tunes the per-hour `temperature` and `blend_weight` on the **raw** HGB output.
`ordinal_smooth_distribution` appears only in serving and one unit test, never in
training.

Why this matters: the served distribution is de-sharpened twice (a fixed 50%
ordinal blend, then the tuned temperature/prior weight), and the tuning that
chose those values was blind to the first step. The net effect is a distribution
flatter than anything validated — the exact symptom items 168/169 measured
(predawn winner band `24.2%` model vs `34.6%` market; probability spread over
more bands). The smoothing constants are also global, applied identically across
every hour and regime, including the predawn slots already too diffuse.

## Design

1. Choose a policy: either fold the ordinal smoothing into the LOO objective
   (tune `sigma` and its blend weight per hour, allowing 0) or remove it and let
   the tuned temperature own all sharpening.
2. If folded: apply the exact serving transform inside the tuning grid before
   scoring, and export the chosen smoothing parameters in the per-hour bundle so
   serving reads them instead of the hard-coded `0.75`/`0.50`.
3. Add a serving-parity test: for a fixed feature vector, the distribution scored
   during tuning equals the distribution served.
4. Re-tune and re-export artifacts; gate the change on weak-slot and per-market
   replay so predawn slices improve rather than only the aggregate.

- [ ] Decide fold-vs-remove with a replay-measured comparison.
- [ ] Make the serving smoothing parameters artifact-driven, not literals.
- [ ] Add the train/serve parity test for the feature-model distribution.
- [ ] Retrain, re-export, and validate predawn winner probability movement
  without regressing ramp/late-day tolerances (items 169/170).

Acceptance: the served feature-model distribution is byte-equivalent to the
distribution scored during tuning (parity test passes), and a retrain raises
predawn winner probability toward market with no ramp/late-day regression.

Related: items 169, 170, 182; `[[model-audit-2026-06-09]]`.
