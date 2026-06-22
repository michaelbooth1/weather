# 178. Serving-Time Ordinal Smoothing Train/Serve Skew [PARTIAL 2026-06-22 - SERVING-ONLY SMOOTHING REMOVED, RETRAIN STILL PENDING]

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

- [x] Decide fold-vs-remove: remove the serving-only smoother for current
  artifacts and require any future smoother to be tuned/exported by the
  validation objective before serving can apply it.
- [x] Make the serving smoothing parameters artifact-driven, not literals.
- [x] Add the train/serve parity test for the feature-model distribution.
- [ ] Retrain, re-export, and validate predawn winner probability movement
  without regressing ramp/late-day tolerances (items 169/170).

Acceptance: the served feature-model distribution is byte-equivalent to the
distribution scored during tuning (parity test passes), and a retrain raises
predawn winner probability toward market with no ramp/late-day regression.

Related: items 169, 170, 182; `[[model-audit-2026-06-09]]`.

## 2026-06-21 implementation update

Removed the unvalidated serving-only ordinal smoothing from the active feature
path. Serving now reads `ordinal_smoothing` from the active feature artifact and
defaults to disabled when the field is absent, which is the correct behavior for
all existing artifacts because their LOO temperature/blend tuning scored the raw
temperature-scaled HGB/LR distribution.

New artifact exports explicitly include:

```json
"ordinal_smoothing": {
  "enabled": false,
  "source": "disabled_until_tuned_in_validation_objective"
}
```

Future artifacts can re-enable ordinal smoothing only by exporting tuned
`sigma` and `blend_weight` values under `ordinal_smoothing`; serving no longer
has hard-coded `sigma=0.75` / `blend_weight=0.50` literals.

Tests now cover:

- HGB serving output equals `temperature_scale_distribution(raw, artifact_temp)`
  when smoothing is absent.
- Existing artifacts default to smoothing disabled.
- Explicit artifact smoothing config is honored.
- Distribution-stage snapshots record the unsmoothed feature distribution by
  default and apply smoothing only when the artifact config enables it.

The full retrain/replay step remains open: the current code removes the skew,
but item completion still requires regenerated artifacts and weak-slot,
per-market, ramp, and late-day validation.

Verification:

- `python -m pytest tests\model\test_feature_model_calibration.py tests\model\test_estimate_distribution.py tests\calibration\test_feature_probability_calibration.py tests\calibration\test_intraday_calibration.py -q`

## 2026-06-22 Retrain Attempt

The active pooled F-band retrain command from `nightly_retrain --dry-run` was:

```powershell
python -m weather.calibration.pooled_feature_model --family-unit F --objective band --holdout-year 2025 --artifact artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl --out data/backtest/f_family_pooled_band_model_v0_3_report.md
```

It did not complete within a 15-minute interactive command budget and was
stopped. `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl` and
`data/backtest/f_family_pooled_band_model_v0_3_report.md` kept their prior
timestamps, so this attempt produced no valid re-export evidence. Completion
still requires running the full retrain under the long-job guard or another
controlled longer window, then rerunning promotion/weak-slot validation against
the regenerated artifact.
