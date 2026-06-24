# 191. Lake/Sea Surface-Temperature Contrast Feature [PARTIAL 2026-06-24 - ADAPTER/BACKFILL COMPLETE, PROMOTION GATE AWAITS REPLAY]

Goal: give the lake/sea-breeze signal the water temperature contrast it depends
on, so the model can anticipate shoreline-cooling days instead of only flagging
onshore wind.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
Gap 5. Item 78 already added live CO-OPS/NDBC marine context with water
temperature, air temperature, wind, onshore/offshore flow, and breeze-risk
diagnostics. This item extends that live source with the missing daily
water-minus-forecast-air contrast that sets lake/sea-breeze strength and inland
penetration. For Toronto, Chicago, and coastal markets, the next richer source
layer remains gridded/satellite SST such as GLSEA for the Great Lakes or OISST
for broader coastal markets.

Why this matters / distinct from item 78: item 78 captures whether a market is
near water, whether live wind is onshore, and whether local marine observations
show cool water/air. Item 191 adds the model-facing magnitude: how far the water
temperature is below the forecast high, and how much of that cooling contrast is
active under onshore flow.

## Design

1. Reuse the existing marine-context registry's station selection and nearest-
   water distance, so the contrast only applies to lake/coast-influenced
   markets.
2. Feature: `marine_water_minus_forecast_high` from live station water
   temperature minus the resolved serving `forecast_high`.
3. Feature: `marine_onshore_water_minus_forecast_high`, an onshore-gated
   contrast that is zero when wind is not onshore and equal to the contrast when
   wind is onshore.
4. Feature: `marine_onshore_cooling_potential`, the positive cooling magnitude
   available only under onshore flow.
5. Use a cache-first GLSEA/OISST point-extraction adapter for markets where a
   single station is sparse, missing, or not representative. Operators place
   provider NetCDF files locally, the adapter extracts nearest market-point SST
   with provenance, and historical feature assembly consumes the resulting
   sidecar without leaking future cutoffs.

## Progress 2026-06-21

- [x] Added water-minus-forecast-high, onshore-gated contrast, and onshore
  cooling-potential fields to `MARINE_CONTEXT_FEATURE_COLUMNS`.
- [x] Passed the resolved live `forecast_high` into marine-context feature
  derivation, so the contrast uses the same forecast consensus as serving.
- [x] Bumped the feature schema to `toronto_feature_store_v1.11`; historical
  rows keep these live-only fields nullable until backfills/replay gates exist.
- [x] Added focused source and live-feature tests for the contrast fields.
- [x] Added machine-readable marine contrast gate artifact.
- [x] Add GLSEA Great Lakes SST and/or OISST gridded SST adapters with
  market-point extraction and provenance.
- [x] Backfill or replay-gate the station/gridded water-contrast features for
  lake/coast-influenced markets.
- [ ] Settlement-score the onshore-wind/breeze-day slice and require no
  aggregate regression before promotion.

## 2026-06-24 Adapter And Backfill Implementation

Added `weather.sources.marine_water_contrast`, a historical sidecar adapter for
lake/sea SST contrast features.

- station-history backfill is cutoff-aware and recomputes the same marine
  feature columns used by serving.
- GLSEA/OISST support is cache-first: local NetCDF files are converted to
  market-point SST rows with provider, product, URL, raw path, grid distance,
  and payload-hash provenance.
- station-history rows and gridded SST rows can be merged so gridded water
  temperature drives the water-air contrast while station wind still gates
  onshore cooling.
- sidecars are loaded by historical feature assembly for per-market cutoff rows.
- source-family inventory now recognizes marine water-contrast sidecars and
  upgrades archive status to `marine_station_archive_available` or
  `glsea_oisst_archive_available` when evidence is present.
- historical backfill planning can queue `marine_water_contrast` station-history
  backfills with missing-range and chunk metadata.

This completes the adapter/provenance/backfill-support portion of the roadmap
item. The promotion gate remains fail-closed until real backfilled sidecars are
generated, a marine-contrast-scoped replay selects the contrast columns, and the
onshore/breeze settlement slice shows positive lift with no aggregate
regression.

## 2026-06-22 Gate Rerun

The refreshed weak-input disposition keeps `marine_microclimate` in
`regime_backfill`: `17` low-coverage/sparse features, `8` near-constant or
unanalyzable features, no positive broad family permutation gate, and incomplete
lineage/parity. The next unblock is still GLSEA/OISST or enough station history,
then an onshore/breeze-day settlement slice.

## 2026-06-22 Marine Contrast Gate Artifact

Added `weather.reporting.marine_contrast_gate`, schema
`marine_contrast_gate_v0.1`, with generated evidence at:

- `data/backtest/item191_marine_contrast_gate.json`
- `data/backtest/item191_marine_contrast_gate_report.md`

Current gate status: `BLOCK`.

Current evidence:

- source inventory sees `marine_context` source-status rows.
- all six water-contrast gate features are cataloged.
- the existing `marine_context` source-family ablation covers `42,273` rows
  across `24` days, but shows `+0.0000` delta and `0` days helped.
- the active artifact selects zero marine contrast features.

Blockers:

- the available replay is `feature_subset=forecast_profile`, not an isolated
  marine-contrast replay.
- `81` snapshot folders lack marine source rows.
- historical archive status is `station_archive_partial`.
- source-family train/serve parity is `PARTIAL_MISSINGNESS`.
- existing marine ablation has no positive lift.
- the current HGB permutation artifact has zero water-contrast rows.
- no onshore/breeze settlement slice exists.
- the borrowed full forecast-profile replay still fails daily-first market
  tolerance.

Next unblock: backfill station history or add GLSEA/OISST gridded SST, train a
marine-contrast-scoped candidate with water-contrast columns selected,
regenerate HGB permutation evidence, and add an onshore/breeze settlement slice.

## 2026-06-22 Gate Refresh

I regenerated `data/backtest/item191_marine_contrast_gate.json` and
`data/backtest/item191_marine_contrast_gate_report.md`. The live gate remains
`BLOCK`.

Current blockers:

- `isolated_marine_replay_missing`: the replay is still a broad
  `forecast_profile` candidate, not a marine water-contrast candidate.
- `marine_source_lineage_partial`: `81` snapshot folders lack marine source
  rows.
- `historical_marine_backfill_missing`: historical archive status is
  `station_archive_partial`.
- `marine_contrast_features_not_selected_by_active_artifact`: the active
  artifact still selects zero contrast columns.
- `train_serve_parity_not_pass`: source-family parity is `PARTIAL_MISSINGNESS`.
- `marine_ablation_no_positive_lift`: marine-context ablation delta is
  `+0.0000`.
- `marine_contrast_permutation_evidence_missing`: no water-contrast rows are in
  the HGB permutation artifact.
- `blocked_validation_failed`: daily-first candidate validation is not within
  market tolerance.
- `onshore_breeze_settlement_slice_missing`: onshore/breeze slice rows are `0`.

This keeps item 191 shadow-only until station or gridded SST history is
backfilled, the contrast columns are selected in a scoped replay, and an
onshore/breeze settlement slice shows positive value without aggregate
regression.

Verification:

- `python -m pytest tests\reporting\test_marine_contrast_gate.py tests\sources\test_marine_context.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 38 passed, 12 pre-existing sklearn all-missing fixture warnings.

Acceptance: a daily lake/sea surface-temperature contrast feature is available
and settlement-scored, with measured improvement on onshore-wind/breeze days for
lake- and coast-influenced markets and no aggregate regression.

Related: items 185, 78, 32, 27; `[[highs-projection-data-gap-2026-06-20]]`.
