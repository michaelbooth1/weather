# 138. Weak Input-Family Pruning And Regime Backfill [PARTIAL 2026-06-22 - GATE REFRESHED, ACTIVE ARTIFACT PRUNING BLOCKED]

Goal: reduce overfit risk by pruning or quarantining broad input families that
do not currently show durable value, while defining targeted backfills for
regimes where they could still matter.

Source: `data/backtest/input_variable_significance_2026_06_18_report.md`.
Broad families outside forecast profile, observed temperature path, source
state, and time context were weak or inconclusive in the current corpus:

- surface weather family all-day HGB delta MAE `0.0044`, q `0.1298`;
- marine microclimate family all-day delta MAE `-0.0009`, q `0.7718`;
- `lake_breeze_proxy` had only 22.7 percent row coverage and was not
  analyzable as a robust broad signal;
- MRMS and ECCC fields were mostly sparse or constant in the analyzed rows.

Why this matters: low-value families can make the model harder to calibrate,
increase feature-matrix fragility, and let sparse availability act like a
hidden market/date proxy. Some of these sources may still be valuable in narrow
regimes such as precipitation interruptions, coastal marine-layer days, lake
breeze reversals, or extreme heat, but they need regime-specific evidence.

## Design

1. Add a feature-family disposition table: `served`, `shadow`, `diagnostic`,
   `regime_backfill`, or `remove`.
2. Default weak broad families to diagnostic or shadow-only unless a
   predeclared regime slice shows lift.
3. Define targeted regime slices for surface weather, marine/coastal,
   lake-breeze, MRMS precipitation, and ECCC gridded features.
4. Add missingness and within-market variation checks before a family can
   enter training.
5. Remove or quarantine columns that create feature-matrix churn without
   settlement-scored value.

- [x] Generate a weak-family disposition report from the significance and
  source-family inventory artifacts.
- [x] Mark weak broad families as diagnostic-only unless they pass a
  regime-specific replay gate.
- [x] Add targeted regime backfill plans for lake-breeze, marine-layer, MRMS
  precipitation interruption, and ECCC Toronto gridded days.
- [x] Add a training preflight warning for families with low coverage,
  near-constant values, or no positive family-level permutation result.
- [x] Update model explanation output so diagnostic-only families are not shown
  as active model evidence.

Acceptance: every weak or sparse input family has an explicit disposition.
Served model artifacts only include families with broad or regime-specific
settlement evidence; otherwise the fields remain diagnostic, shadow-only, or
queued for targeted backfill.

## 2026-06-18 implementation update

Added `weather.reporting.weak_input_family_disposition`, schema
`weak_input_family_disposition_v0.1`. The report reads the June 18
input-significance family permutation and coverage artifacts plus
`data/backtest/source_family_inventory.json`, then emits per-family
dispositions, diagnostic blockers, targeted regime-backfill plans, and a
training preflight warning surface.

Generated:

- `data/backtest/item138_weak_input_family_disposition.json`
- `data/backtest/item138_weak_input_family_disposition_report.md`

The generated status is `WARN`. Current dispositions are:

- `served`: `observed_temp_path`, `open_meteo_forecast_profile`,
  `forecast_source_state`, and `time_context`.
- `diagnostic_only`: `surface_weather` and `reanalysis_synoptic`.
- `regime_backfill`: `marine_microclimate`, `official_multimodel_guidance`,
  and `radar_precip`.

The policy explicitly names the weak/sparse blockers:

- `surface_weather` has broad all-day HGB delta MAE `+0.0044` but q `0.1298`,
  so it does not clear the broad family permutation gate; `wind_gust_kmh` and
  `wind_shift_3h_degrees` remain sparse.
- `marine_microclimate` is negative/inconclusive at the broad-family level and
  has 17 sparse features, including `lake_breeze_proxy` and marine-layer
  fields queued for regime backfill.
- `official_multimodel_guidance` and `radar_precip` remain sparse/near-constant
  and inherit the item 137 official-guidance coverage blockers for NWS,
  multi-model, ECCC, and MRMS families.
- `reanalysis_synoptic` is diagnostic-only in this June 18 significance corpus
  because its fields are sparse/unanalyzable here; item 32 still owns the
  separate all-market sidecar and promotion gates.

`train_pooled_band_models` now records `weak_input_family_preflight` in the
artifact/report. The current generated preflight is `WARN`: active model
features include `surface_weather` columns, so the next retrain/promotion
decision must either prune those columns or clear a predeclared regime replay
gate. Model explanation output now carries `diagnostic_only_input_families`
and suppresses diagnostic-only family panels such as marine context from active
model evidence when that metadata is present.

Remaining acceptance blocker: the existing served artifact has not been
retrained/pruned under the new policy, so item 138 is not complete until a
candidate artifact proves that weak families are excluded or explicitly gated
by positive regime-specific settlement evidence.

## 2026-06-22 active-artifact pruning gate

Regenerated the weak-family disposition report:

```powershell
python -m weather.reporting.weak_input_family_disposition --out data\backtest\item138_weak_input_family_disposition.json --report data\backtest\item138_weak_input_family_disposition_report.md
```

Added `weather.reporting.item138_weak_input_family_gate`, schema
`item138_weak_input_family_gate_v0.1`, and generated:

```powershell
python -m weather.reporting.item138_weak_input_family_gate --out data\backtest\item138_weak_input_family_gate.json --report data\backtest\item138_weak_input_family_gate_report.md
```

Result: **BLOCK**, disposition **KEEP_POLICY_SHADOW_PRUNE_ON_RETRAIN**.

Passing evidence:

- All nine input families have explicit dispositions.
- Every `regime_backfill` family has a targeted plan.
- The diagnostic-only family surface is present for model explanations.

Blockers:

- Active artifact preflight still warns on `marine_microclimate`,
  `open_meteo_forecast_profile`, and `surface_weather`.
- Upstream Item 136 source-state reliability remains shadow-only because
  degraded/high-disagreement raw-forecast thresholds and Chicago/NYC market
  thresholds still block.

Next action: keep weak families diagnostic or regime-backfill only. Do not
treat the active artifact as pruned until training preflight is `PASS` and
upstream source-state reliability gates clear.

## 2026-06-22 active-artifact pruning gate refresh

Regenerated the weak input-family disposition and active-artifact pruning gate
after refreshing upstream Item 136:

- `data/backtest/item138_weak_input_family_disposition.json`
- `data/backtest/item138_weak_input_family_disposition_report.md`
- `data/backtest/item138_weak_input_family_gate.json`
- `data/backtest/item138_weak_input_family_gate_report.md`

The refreshed gate remains `BLOCK` with disposition
`KEEP_POLICY_SHADOW_PRUNE_ON_RETRAIN`. Passing evidence remains:

- all `9` input families have explicit dispositions.
- every `regime_backfill` family has a targeted backfill plan.
- diagnostic-only family surface is present for model explanations.

Current blockers:

- `active_artifact_pruning_preflight`: active artifact still warns on weak
  families `marine_microclimate`, `open_meteo_forecast_profile`, and
  `surface_weather`. The weak-family disposition itself is still `WARN`.
- `upstream_source_state_disposition`: Item 136 remains shadow-only because
  degraded/high-disagreement raw-forecast thresholds and Chicago/NYC market
  thresholds still block.

Keep weak families diagnostic or regime-backfill only. Do not treat the active
artifact as pruned until training preflight is `PASS` and upstream source-state
reliability gates clear.
