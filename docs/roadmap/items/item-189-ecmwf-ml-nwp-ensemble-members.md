# 189. ECMWF & ML-NWP Ensemble Forecast Members [PARTIAL 2026-06-24 - GLOBAL-MODEL ARCHIVE SUPPORT LIVE, REPLAY BLOCKED]

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

Remaining work: fleet backfill execution, retraining, and settlement-scored
predawn/morning gates still need enough archived and settled data. ECMWF
ensemble, Google WeatherNext / GenCast, and Pangu-style members remain optional
follow-ons unless a stable no-key or already-authorized provider path is added.

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
- [x] Machine-readable global-model guidance gate artifact.
- [x] Historical Open-Meteo global-model archive/backfill support.
- [ ] Retrain and settlement-scored predawn/morning gate.
- [ ] Optional additional ML members when a stable no-key provider path exists.

## 2026-06-24 Global-Model Archive Support

Implemented replay-safe archive/backfill support for Open-Meteo global-model
runs without expanding providers or retraining active artifacts.
`weather.sources.open_meteo_archives` now has:

- idempotent global-model hourly and daily archive writes with
  content-addressed raw payloads.
- `global-models backfill` and `global-models coverage` CLI commands.
- historical backfill planner support via source
  `open_meteo_global_models`.

`weather.reporting.source_gates.source_family_inventory` now reports global-model archive
coverage for the `multi_model_guidance` family as
`historical_global_model_archive_available`,
`partial_historical_global_model_archive`, or
`historical_global_model_archive_missing`. A complete archive changes the
family out of `live_only_until_model_run_archive_backfill` and into normal
parity-required promotion policy; lineage, feature selection, permutation, and
settlement-scored replay blockers still apply independently.

This intentionally does not retrain or promote an active artifact. The
global-model guidance gate remains blocked until the archive is populated,
a global-model-scoped candidate is trained/replayed, ECMWF/AIFS/AIGFS/GraphCast
features are selected by the candidate artifact, permutation evidence exists,
and predawn/morning slices are settlement-scored.

Verification:

- `python -m pytest tests\sources\test_open_meteo_archives.py tests\sources\test_historical_sources.py tests\collection\test_historical_backfill_runner.py tests\reporting\test_source_family_inventory.py tests\reporting\test_global_model_guidance_gate.py tests\operations\test_schema_registry.py -q` -> 70 passed.

## 2026-06-22 Gate Rerun

The refreshed weak-input disposition keeps the relevant
`official_multimodel_guidance` family in `regime_backfill`: `33`
low-coverage/sparse features, `19` near-constant or unanalyzable features, no
positive broad family permutation gate, and incomplete source lineage/parity.
The next unblock is a replay-safe archive/backfill for the global-model members,
then a predawn/morning settlement gate.

## 2026-06-22 Global-Model Gate Artifact

Added `weather.reporting.source_gates.global_model_guidance_gate`, schema
`global_model_guidance_gate_v0.1`, with generated evidence at:

- `data/backtest/item189_global_model_guidance_gate.json`
- `data/backtest/item189_global_model_guidance_gate_report.md`

Current gate status: `BLOCK`.

Current evidence:

- `multi_model_guidance` source inventory sees `open_meteo_global_models` in
  both source status and forecast payloads.
- all eight ECMWF/AIFS/AIGFS/GraphCast diagnostic columns are cataloged.
- the borrowed full forecast-profile replay has an early/predawn proxy slice
  with `-0.0015` Brier delta versus current, but it is not scoped to global
  model guidance.
- the current HGB permutation artifact has five legacy global-ensemble rows,
  but zero ECMWF/AIFS/AIGFS/GraphCast rows.

Blockers:

- the available replay is `feature_subset=forecast_profile`, not an isolated
  global-model replay.
- `92` snapshot folders lack global-model payload rows.
- historical archive status is `live_only_until_model_run_archive_backfill`.
- zero global-model columns are selected by the active artifact.
- source-family train/serve parity is `LINEAGE_BLOCKED`.
- no ECMWF/AIFS/AIGFS/GraphCast permutation rows exist in the current HGB
  artifact.
- the borrowed full forecast-profile replay still fails daily-first market
  tolerance.

Next unblock: backfill or replay-save Open-Meteo global-model runs, train a
global-model-scoped candidate with the eight global-model columns selected,
regenerate HGB permutation evidence, and add a predawn/morning settlement slice.

## 2026-06-22 Gate Refresh

I regenerated `data/backtest/item189_global_model_guidance_gate.json` and
`data/backtest/item189_global_model_guidance_gate_report.md`. The live gate
remains `BLOCK`.

Current blockers:

- `isolated_global_model_replay_missing`: the candidate replay is still scoped
  to `forecast_profile`, not Open-Meteo global-model guidance.
- `global_model_payload_lineage_partial`: `92` snapshot folders lack
  global-model payload rows.
- `historical_global_model_backfill_missing`: historical archive status is
  `live_only_until_model_run_archive_backfill`.
- `global_model_features_not_selected_by_active_artifact`: zero global-model
  columns are selected by the active artifact.
- `train_serve_parity_not_pass`: source-family parity is `LINEAGE_BLOCKED`.
- `global_model_permutation_evidence_missing`: no ECMWF/AIFS/AIGFS/GraphCast
  rows are present in the HGB permutation artifact.
- `blocked_validation_failed`: daily-first candidate validation is not within
  market tolerance.

The full-profile early slice still has a supportive `-0.0015` delta versus
current, but it is not scoped evidence for this subfamily and cannot promote the
global-model features.

Verification:

- `python -m pytest tests\reporting\test_global_model_guidance_gate.py tests\model\test_forecast_feature.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 48 passed, 12 pre-existing sklearn all-missing fixture warnings.

Acceptance: the forecast ensemble includes a clustered ECMWF/ML-NWP live source,
the derived disagreement/delta features reflect its members, and settlement-
scored replay eventually shows non-regressing skill with measured early-hour
improvement.

Related: items 185, 75, 169, 27; `[[highs-projection-data-gap-2026-06-20]]`.
