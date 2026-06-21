# 189. ECMWF & ML-NWP Ensemble Forecast Members [PARTIAL 2026-06-21 - OPEN-METEO GLOBAL MODEL CLUSTER LIVE, GATE PENDING]

Goal: widen the forecast ensemble the model already consumes with ECMWF and the
new machine-learning NWP models, which now lead surface-temperature skill.

Status: the live Open-Meteo global-model path is wired. The new
`open_meteo_global_models` source fetches model-specific `temperature_2m`
columns for ECMWF IFS 0.25, ECMWF AIFS 0.25, NCEP AIGFS, and GFS GraphCast,
auto-runs with the Open-Meteo source family, and uses the same short live-source
TTL as the other Open-Meteo forecast feeds.

The feature path treats these correlated members as one global-model cluster in
`forecast_ensemble_metrics`, contributing a median high vote rather than four
separate over-weighted votes. Per-member diagnostics are still exposed through
US-guidance-style features:

- `open_meteo_global_models_high_spread`
- `open_meteo_ecmwf_ifs_high_delta`
- `open_meteo_ecmwf_aifs_high_delta`
- `open_meteo_ncep_aigfs_high_delta`
- `open_meteo_gfs_graphcast_high_delta`
- `open_meteo_ecmwf_ifs_aifs_disagreement`
- `open_meteo_global_models_next_3h_spread`
- `open_meteo_global_models_run_to_run_high_change`

Remaining work: historical archive/backfill, retraining, and settlement-scored
predawn/morning gates still need enough live and settled data. ECMWF ensemble,
Google WeatherNext / GenCast, and Pangu-style members remain optional follow-ons
unless a stable no-key or already-authorized provider path is added.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
section 4. The model's forecast ensemble (Open-Meteo multimodel, NWS grid, ECCC
GEM, Weather.com, global-ensemble spread) lacked ECMWF and ML-model guidance.

Why this matters: the new members are cheap and additive. They feed the existing
`forecast_high`, `forecast_disagreement`, and per-model-delta surfaces without
new model machinery, and they are most likely to help in predawn and morning
regimes where the observed path is still weak.

## Design

1. Add ECMWF IFS/AIFS and available ML-NWP members as a live Open-Meteo global
   model source.
2. Extend `forecast_ensemble_metrics` with one clustered global-model vote, plus
   disagreement, per-model delta, and next-window spread diagnostics.
3. Keep correlated members clustered so added models widen disagreement honestly
   rather than over-voting a shared provider/model backbone.
4. Settlement-score the new features per market once historical archive and
   settled outcomes are available; verify predawn/morning lift specifically.

- [x] Add ECMWF + ML-NWP members to forecast collection + ensemble metrics
      (scoped to Open-Meteo IFS/AIFS/AIGFS/GraphCast).
- [x] Extend disagreement / per-model-delta / run-to-run features.
- [ ] Historical archive/retrain and settlement-scored predawn/morning gate.
- [ ] Optional additional ML members when a stable no-key provider path exists.

Acceptance: the forecast ensemble includes a clustered ECMWF/ML-NWP live source,
the derived disagreement/delta features reflect its members, and settlement-
scored replay eventually shows non-regressing skill with measured early-hour
improvement.

Related: items 185, 75, 169, 27; `[[highs-projection-data-gap-2026-06-20]]`.
