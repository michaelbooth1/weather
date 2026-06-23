# 252. Impossible Guidance Feature Quarantine [COMPLETE 2026-06-22 - FRESH-BUT-IMPOSSIBLE GUIDANCE QUARANTINED]

Goal: Quarantine guidance features whose Tmax distributions or forecast highs are physically inconsistent with the already observed settlement floor or official current high.
Source: 2026-06-22 Austin weather-model disagreement audit. The row included `nbm_prob_tmax_p10..p90` values around 75-79F even though KAUS had already observed about 94F, so the feature could be fresh by timestamp while impossible by physical consistency.
Why this matters: Freshness is not validity. Physically impossible guidance can distort model training, calibration, attribution, and source-health decisions unless it is explicitly marked unusable before feature construction and serving.

## Design

1. Add a physical-consistency gate for guidance values against official observed high, current high, and settlement floor.
2. Emit a source state such as `fresh_but_impossible` separately from stale, missing, and low-coverage states.
3. Route impossible guidance to missingness or quarantine handling before model feature construction.
4. Add training-time exclusion or masking rules so impossible rows do not teach the model false source reliability.
5. Extend source-health reporting to count impossible rows by provider, market, timestamp, and feature family.

- [x] Austin 2026-06-22 NBM probabilistic Tmax features are flagged as impossible before serving features are built.
- [x] Guidance freshness reports distinguish timestamp freshness from physical validity.
- [x] Training and serving paths handle impossible guidance consistently.
- [x] Source-health reports show impossible-row counts and top affected features.
- [x] Replay demonstrates that quarantining impossible guidance does not silently remove useful valid guidance rows.

Acceptance: Any guidance feature materially below an already observed official high is quarantined with an auditable reason before it can affect model probabilities, and the source-health layer exposes the difference between stale, missing, and physically impossible data.
Related: items 75, 136, 137, 190, 208, 221, 232, and 242.

## Completion - 2026-06-22

Implemented physical-consistency quarantine for guidance features against the
observed settlement floor. Feature-store schema `toronto_feature_store_v1.15`
adds guidance physical-floor diagnostics plus NBM physical-validity flags, and
the source diagnostics now keep timestamp freshness separate from physical
validity.

Evidence:

- `data/backtest/austin_weather_model_hardening.json`
- `data/backtest/austin_weather_model_hardening_report.md`

The Austin hardening packet passes item 252 gates:

- `austin_nbm_impossible_before_features`: NBM percentiles `75-79F` are masked
  before feature use when the observed Austin floor is `94F`.
- `freshness_distinct_from_physical_validity`: NBM remains timestamp `fresh`
  while source-health reports `fresh_but_impossible` and the affected feature
  names.
- `valid_guidance_not_silently_removed`: a valid NBM row at or above the
  observed floor keeps `p10..p90` features and has zero impossible sources.

Verification:

```powershell
python -m weather.reporting.austin_weather_model_hardening
python -m pytest tests/reporting/test_austin_weather_model_hardening.py tests/model/test_forecast_feature.py tests/model/test_feature_store.py tests/operations/test_schema_registry.py -q
```
