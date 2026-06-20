# Core Model Audit — 2026-06-20

Deep dive on the projection model's core logic and code (`src/weather/model/*`
plus the `weather.calibration` training path that produces its artifacts). Scope
is the probability engine that turns weather sources into a settlement-bucket
distribution — not collection, ops, or market-making. Findings are ordered by
expected impact on calibration/skill, each with concrete code references.

This complements the prior logic audit (`[[model-audit-2026-06-09]]`, findings
5–8 still partly open) and the in-flight items 168/169/170, which independently
measured the symptoms several of these findings predict (predawn over-diffusion,
late-day under-confidence).

---

## 1. How the model is built today (for context)

`TorontoHighTempModel` ([toronto_model.py](../../src/weather/model/toronto_model.py))
composes concern mixins. The heart is
`_estimate_distribution_result` ([model_distribution.py:116](../../src/weather/model/model_distribution.py#L116)),
a ~300-line sequential pipeline:

1. **Climatology prior** — empirical bucket frequencies for the ±window around
   the target calendar day, else a uniform fallback.
2. **Model path** — either the per-hour **HGB feature model** (primary) blended
   with the prior, or a calibrated-empirical component blend (fallback).
3. **~13 post-processors** in fixed order: bucket-transition prior, live-signal
   Gaussian kernels, hard floor, intraday tail target, plausible cap, forecast
   floor + forecast pull, validated-max floor, settlement-lag/current/WU-residual
   floors, late-day continuation, late-day lock-in.
4. **Final calibration** — `apply_exact_distribution_calibration` (per-hour
   temperature + uniform prior weight, tapered by lock-in strength).

The HGB is trained per cutoff hour with LOO in
[feature_model.py](../../src/weather/calibration/feature_model.py); per-hour
`temperature` and `blend_weight` are grid-tuned and shipped in the bundle.

Strengths worth preserving: the `DistributionPipelineState.snapshot()` system
records every intermediate distribution (a ready-made attribution substrate);
floors are hedged by *learned* catch-up rates rather than hard-coded; constants
mostly carry the A/B that justified them; native-unit threading is consistent.

---

## 2. High-impact findings

### H1. Serving applies an unvalidated 50% ordinal smoothing the tuning never saw

On the feature-model path the HGB output is smoothed before it is blended:

```python
# model_distribution.py:472
feature_probs = self.ordinal_smooth_distribution(feature_probs, sigma=0.75, blend_weight=0.50)
...
scores = self.blend_distribution(scores, feature_probs, self.feature_blend_weight(cutoff_hour))
```

But the per-hour `temperature` and `blend_weight` are tuned in
[feature_model.py:1237](../../src/weather/calibration/feature_model.py#L1237) on the
**raw** HGB output — `fit_temperature_blend_grid` receives `(climatology,
raw_hgb, actual)` tuples with no ordinal smoothing
([feature_probability_calibration.py:64](../../src/weather/calibration/feature_probability_calibration.py#L64)).
`ordinal_smooth_distribution` appears only in serving and a unit test, never in
training.

Consequence: serving de-sharpens the distribution **twice** (a fixed 50% Gaussian
ordinal blend, then the tuned temperature/prior-weight), and the tuning that
chose the temperature/blend was blind to the first step. This is a genuine
train/serve skew, and it pushes serving systematically *flatter* than what was
validated — exactly the symptom items 168/169 measured (predawn winner band
24.2% model vs 34.6% market; "model spreads probability over more bands").
`sigma`/`blend_weight` are also global constants applied identically across every
hour and regime, including the predawn slots that are already too diffuse.

**Fix:** fold the ordinal smoothing into the LOO objective so its weight is tuned
(and can go to 0 per hour), or remove it and let the tuned temperature own all
sharpening. Either way, validate the exact transform that serves.

### H2. LOO validation is leakier for the ML model than for the baseline it's compared to

In the LOO loop the baseline priors exclude the **whole validation year**
(`d["date"].year != val_date.year`,
[feature_model.py:1091](../../src/weather/calibration/feature_model.py#L1091)),
but the HGB/LR train mask only removes the **single validation row**
([feature_model.py:1083](../../src/weather/calibration/feature_model.py#L1083)).
Since each row is one day at one cutoff hour, the ML model still trains on the
days immediately adjacent to the held-out day in the same season — highly
autocorrelated weather with, often, the same `final_bucket`.

Two problems: (a) the reported ML-vs-baseline lift is biased toward the ML model
(it gets near-neighbor leakage the baseline is denied), and (b) the
temperature/blend grid is *selected* under that leakage, so it trusts the model
more (smaller climatology weight) than truly-out-of-sample data would justify.
Combined with H1's extra serving smoothing, the model is mis-tuned in two
opposing directions at once, which makes the net calibration hard to reason about.

**Fix:** make both arms leave-one-year (or blocked by day with an embargo
window), as the existing `blocked_validation` module already supports. Re-tune
temperature/blend under the honest split.

---

## 3. Medium-impact findings

### M1. Hard-coded Celsius fallbacks pre-empt the per-market imputer (multi-market skew)

`extract_live_features` substitutes literal constants when a field is missing —
`current_temp = 17.0`, `high_so_far = 17.0`, `temp_7am = 17.0`, `dewpoint = 10.0`,
`humidity = 60.0`, `wind_speed = 15.0`
([model_features.py:378-443](../../src/weather/model/model_features.py#L378)).
These are Celsius-flavoured and unit-blind: on a Fahrenheit market `17.0` is read
as 17 °F (~ −8 °C), a wild value. Worse, by filling a number the code *bypasses*
the per-market `SimpleImputer(strategy="median")` that the model was trained
with — so a missing field serves a different value than training imputed. Open
since 2026-06-09 audit finding #6.

**Fix:** return `None` for missing numeric features and let the trained imputer
(HGB native-NaN / LR median) handle them; reserve literal defaults for the strict
analog path only.

### M2. Forecast signal is consumed twice on the ML path; `capture_hour` is dead

The HGB already ingests forecast features (`forecast_high`, `forecast_gap`,
multi-model guidance). The pipeline then *also* runs `apply_forecast_floor` +
`apply_forecast_pull` on the ML output
([model_distribution.py:698-732](../../src/weather/model/model_distribution.py#L698)),
re-injecting the same forecast consensus post-hoc. The team already found that
tuning the pull window in isolation backfires (constants note, 2026-06-12), which
is consistent with double-counting: the right control variable is "how much
forecast signal is already in the HGB," not the pull window alone.

Relatedly, `forecast_error_distribution(..., capture_hour=...)` accepts the hour
but never uses it ([calibration_runtime.py:411](../../src/weather/model/calibration_runtime.py#L411)),
so the forecast-error component is not hour-conditioned at serve even though the
caller threads the hour through. Open since finding #7.

**Fix:** measure forecast-feature attribution in the HGB (the ablation harness
already exists), then decide whether the serving pull/floor should apply only on
the empirical fallback path. Either use `capture_hour` or delete the parameter.

### M3. The 13-stage heuristic stack is locally tuned, never jointly calibrated or attributed

Each post-processor was added to fix a specific failure and carries its own
magic constants (hedges, per-degree decays, time-weights, blend caps). They run
in a fixed order and mutate the same `scores` dict, so their *interactions* are
unmodeled — and items 169/170 are essentially the bill coming due (the stack is
over-diffuse predawn and under-confident late-day at the same time). There is no
routine measurement of each stage's marginal contribution to held-out Brier.

**Opportunity (high leverage, low risk):** the `pipeline.snapshot(...)` payloads
already capture every intermediate distribution. Add a replay-corpus harness that
scores each named snapshot against settlement and reports per-stage marginal
Brier/log-loss by hour and regime. That turns the existing instrumentation into a
stage-attribution audit and lets stages that no longer pay their way be retired
with evidence (the floors/caps were already measured net-negative for Toronto
once).

### M4. Correlated forecast votes are counted as independent evidence (empirical fallback)

On the empirical/non-feature path, `distribution_live_signals` emits a separate
multiplicative Gaussian bump for `weather_forecast_max`, `open_meteo_max`,
`nws_forecast_max`, `global_ensemble_max`, and `eccc_forecast_high`
([model_distribution.py:939-971](../../src/weather/model/model_distribution.py#L939)),
and `apply_live_signals` multiplies them all into the distribution independently
([model_distribution.py:1023](../../src/weather/model/model_distribution.py#L1023)).
These sources largely share an NWP backbone, so stacking them independently
over-concentrates the consensus bucket — classic correlated-evidence
overconfidence. The primary ML path solves this with the explicit "peak cluster"
([model_distribution.py:906-928](../../src/weather/model/model_distribution.py#L906));
the fallback path did not get the same treatment.

**Fix:** collapse the forecast sources into one cluster vote on the empirical path
too (reuse the peak-cluster logic).

### M5. Uniform prior is a fixed 8–33 °C window for every city

When local climatology is thin the prior is
`range(round(c_to_native(8)), round(c_to_native(33)))` uniform
([model_distribution.py:162](../../src/weather/model/model_distribution.py#L162)).
That is a Toronto-summer band imposed on Miami (rarely < 20 °C) and Seattle
(rarely > 30 °C). It only bites when history is sparse, but for newer markets
that is exactly when the prior matters most. Open since finding #6.

**Fix:** derive the fallback window from the market's own daily-summary
percentiles, or a wider season-aware Gaussian around the climatological normal.

---

## 4. Lower-impact / latent

- **Falsy-zero `or` chains on temperatures.** e.g.
  [model_distribution.py:211-214](../../src/weather/model/model_distribution.py#L211)
  (`hard_floor_bucket or observed_bucket or max_signal or ...`). A legitimate
  bucket of `0` (0 °C / 0 °F) is falsy and silently skipped. In-season summer
  markets rarely hit 0, so this is latent, but it is a real correctness trap;
  prefer explicit `is None` selection.
- **Unbounded class-level climatology cache.**
  `_historical_target_cache` is a class dict keyed by `market:date` and never
  evicts ([model_climatology.py:34](../../src/weather/model/model_climatology.py#L34),
  [toronto_model.py:67](../../src/weather/model/toronto_model.py#L67)). In the
  long-running fleet loop it grows one full per-day observation set per
  (market, date) forever. Add an LRU bound.
- **Continuous-density path is half-adopted.** `continuous_density.py` has a
  complete fine-grid-F → native-band integrator (the principled fix for the x.5
  rounding instability and C/F unification), but the core model still classifies
  **integer** native buckets (`y = df["final_bucket"].astype(int)`,
  [feature_model.py:496](../../src/weather/calibration/feature_model.py#L496)).
  The forecast-soft-density stage is a partial workaround. Completing item-35's
  continuous target end-to-end would retire several boundary heuristics.
- **Single fixed-seed HGB.** `random_state=42`, one model per hour
  ([feature_model.py:1321](../../src/weather/calibration/feature_model.py#L1321)).
  With only a few hundred training days, seed-bagging a small ensemble would cut
  variance for near-free and improve probability calibration.

---

## 5. Suggested additions / enhancements

1. **Stage-attribution harness** over the existing pipeline snapshots (M3) — the
   single highest-leverage, lowest-risk build; it makes every other change
   measurable and would directly serve items 168/169/170.
2. **Validate-what-you-serve calibration** — one learned calibration head
   (temperature + ordinal-smoothing weight, conditioned on hour/regime) fit on
   the *served* distribution under an honest split, replacing H1's untuned 50%
   smoother and unifying the final-calibration constants.
3. **Continuous-density target end-to-end** (finish item 35) — removes the x.5
   instability, unifies C/F, and lets quantile/conformal calibration replace
   per-bucket decay constants.
4. **Per-market priors** (M5) and **hour-conditioned forecast-error** (M2).
5. **Honest CV** (H2) as the foundation under all of the above.

---

## 6. Priority order

| # | Finding | Effort | Why first |
| --- | --- | --- | --- |
| 1 | M3 stage-attribution harness | M | unblocks measuring everything else |
| 2 | H2 honest LOO split | S | every tuned constant rides on it |
| 3 | H1 fold/remove serving ordinal smoothing | S | direct fix for measured predawn over-diffusion (items 168/169) |
| 4 | M1 stop pre-empting the imputer | S | multi-market correctness |
| 5 | M2 forecast double-count + dead `capture_hour` | M | |
| 6 | M4 / M5 fallback-path cluster + per-market prior | S | |
| 7 | continuous-density target (item 35) | L | strategic |

H1, H2, M1, M2, M5 align with still-open items in `[[model-audit-2026-06-09]]`;
H1's symptom is what items **168/169** quantified, and the late-day half of M3 is
item **170**. Closing H1+H2+M3 would give those three items a measurement
foundation they currently lack.
