# 190. NBM Native Probabilistic Tmax Consumption [PARTIAL 2026-06-24 - REPLAY-SAFE NBP ARCHIVE PROVEN, SCORING BLOCKED]

Goal: consume the National Blend of Models' calibrated probabilistic maximum-
temperature distribution, instead of using only its point high.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
section 4. NOAA documents NBM probabilistic MaxT percentiles in the QMD/NBP
product family, and NBM GRIB2/text products are publicly available through
NOMADS and the NOAA Open Data S3 bucket. The model previously ingested NBM only
as a single point high through Open-Meteo's `ncep_nbm_conus` field, discarding
NBM's calibrated uncertainty.

Why this matters: NBM's probabilistic MaxT is a strong, calibrated baseline that
is cheap to obtain for US markets. It can serve both as features (percentile
spread and exceedance probabilities) and as a calibration anchor the model's own
distribution is scored against.

## Design

1. Add an NBM probabilistic-Tmax adapter with provenance/freshness. The live
   first path reads NOMADS `blend_nbptx` NBP station text, which exposes
   station-aligned `TXNP1/TXNP2/TXNP5/TXNP7/TXNP9` daily MaxT percentile rows
   for 10/25/50/75/90 percentiles without requiring per-market GRIB extraction.
2. Features: expose `nbm_prob_tmax_p10/p25/p50/p75/p90`, mean, standard
   deviation, IQR, 10-90 spread, p50/p90 deltas against `forecast_high`, and an
   interpolated exceedance probability against `forecast_high`.
3. Keep native QMD GRIB exceedance grids as a second gate. The station text
   gives percentile curve features now; bucket-edge native exceedance grids and
   historical backfills still need GRIB extraction, archive parity, and
   settlement-scored validation before promotion.
4. Settlement-scored gate per US market. NBM remains US-only in this live path,
   so Toronto stays on the existing non-NBM path.

## Progress 2026-06-21

- [x] Added `weather.sources.nbm_probabilistic_tmax` with NBP station text URL
  construction, recent-cycle candidates, station block parsing, target-day MaxT
  slot selection, percentile payload hashing, and percentile-curve exceedance
  interpolation.
- [x] Added `nbm_probabilistic_tmax` to US live source fetching when official
  US guidance is active, with a 120-minute last-good cache TTL and fallback
  over recent NBM cycles.
- [x] Added live-only `nbm_prob_tmax_*` feature columns and bumped the feature
  schema to `toronto_feature_store_v1.10`; historical training rows default the
  fields to `None` until archives exist.
- [x] Added NBM payload/source visibility to snapshot reconstruction, source
  family inventory, disagreement casebook, and official US guidance ablations.
- [x] Added machine-readable NBM probabilistic Tmax gate artifact.
- [x] Proved a replay-safe NBP station archive path for US markets.
- [ ] Add native QMD GRIB percentile/exceedance-grid extraction for market
  points and bucket edges if bucket-edge native exceedance grids become needed.
- [ ] Settlement-score NBM-prob as a calibration anchor and gate promotion on
  non-regressing per-market skill.

## 2026-06-22 Gate Rerun

The source-family refresh still treats the live NBM station-percentile path as
unpromoted evidence. The open work remains QMD/bucket-edge extraction or a
replay-safe station archive, historical probabilistic NBM feature backfill, and
per-market settlement scoring before it can act as a calibration anchor.

## 2026-06-22 NBM Probabilistic Gate Artifact

Added `weather.reporting.nbm_probabilistic_tmax_gate`, schema
`nbm_probabilistic_tmax_gate_v0.1`, with generated evidence at:

- `data/backtest/item190_nbm_probabilistic_tmax_gate.json`
- `data/backtest/item190_nbm_probabilistic_tmax_gate_report.md`

Current gate status: `BLOCK`.

Current evidence:

- source inventory sees `nbm_probabilistic_tmax` in source status.
- source inventory does not yet see `nbm_probabilistic_tmax` in forecast
  payload rows.
- all twelve `nbm_prob_tmax_*` feature columns are cataloged.
- zero NBM probabilistic columns are selected by the active artifact.

Blockers:

- the available replay is `feature_subset=forecast_profile`, not an isolated
  NBM-prob replay.
- durable forecast-payload capture is missing for `nbm_probabilistic_tmax`.
- `77` snapshot folders lack NBM payload rows.
- historical archive status is `live_only_until_grid_archive_backfill`.
- source-family train/serve parity is `LINEAGE_BLOCKED`.
- the current HGB permutation artifact has zero NBM probabilistic rows.
- no US-market settlement slice exists for NBM-prob.
- the borrowed full forecast-profile replay still fails daily-first market
  tolerance.

Next unblock: persist NBM probabilistic payloads into forecast payload tapes,
add QMD/bucket-edge extraction or a replay-safe NBP station archive, train a
NBM-prob-scoped candidate with NBM columns selected, regenerate HGB permutation
evidence, and add US-market settlement slices.

## 2026-06-22 Gate Refresh

I regenerated `data/backtest/item190_nbm_probabilistic_tmax_gate.json` and
`data/backtest/item190_nbm_probabilistic_tmax_gate_report.md`. The live gate
remains `BLOCK`.

Current blockers:

- `isolated_nbm_replay_missing`: the candidate replay is still scoped to
  `forecast_profile`, not NBM probabilistic Tmax guidance.
- `nbm_forecast_payload_missing`: `nbm_probabilistic_tmax` is absent from
  forecast-payload inventory.
- `nbm_payload_lineage_partial`: `77` snapshot folders lack NBM payload rows.
- `historical_nbm_backfill_missing`: historical archive status is
  `live_only_until_grid_archive_backfill`.
- `nbm_features_not_selected_by_active_artifact`: zero NBM probabilistic
  columns are selected by the active artifact.
- `train_serve_parity_not_pass`: source-family parity is `LINEAGE_BLOCKED`.
- `nbm_permutation_evidence_missing`: no NBM probabilistic rows are in the HGB
  permutation artifact.
- `blocked_validation_failed`: daily-first candidate validation is not within
  market tolerance.
- `us_market_settlement_slices_missing`: US-market settlement rows are `0`.

The live station-text path remains useful source plumbing, but it cannot serve
as a calibration anchor until payload capture, historical archive parity, and
US-market settlement gates exist.

Verification:

- `python -m pytest tests\reporting\test_nbm_probabilistic_tmax_gate.py tests\sources\test_nbm_probabilistic_tmax.py tests\model\test_forecast_feature.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 53 passed, 12 pre-existing sklearn all-missing fixture warnings.

## 2026-06-24 Replay-Safe NBP Station Archive

Added a replay-safety proof for the NBP station-text archive path:

- `weather.sources.nbm_probabilistic_tmax.replay_nbp_station_archive_row`
  reloads the archived raw NBP text payload, reparses the station/target-date
  Tmax percentiles, and verifies station, target date, issue time, forecast
  hour, valid time, product version, source URL, payload hash, percentile
  values, mean, standard deviation, spread, and IQR against the CSV manifest.
- `nbp_station_archive_summary` reports archive status as `PASS` only when at
  least one available row exists and every manifest row replays cleanly.
- `weather.reporting.source_family_inventory` now upgrades item 190's NWS/NBM
  historical archive status to `nbp_station_archive_available` only when that
  replay-safe archive evidence is present; otherwise the family remains on the
  live-only/grid-backfill status.
- Snapshot forecast-payload manifests now retain NBM bulletin `issued_at` and
  `valid_time_utc` metadata as provider issue/update times when raw NBP payloads
  are persisted.

Verification:

- `python -m pytest tests\sources\test_nbm_probabilistic_tmax.py -q` -> 8 passed.
- `python -m pytest tests\collection\test_forecast_payload_persistence.py -q` -> 1 passed.
- `python -m pytest tests\reporting\test_source_family_inventory.py -q` -> 16 passed.

Acceptance: NBM probabilistic MaxT is ingested for US markets, exposed as
features, and settlement-scored, with non-regressing per-market skill and a
documented comparison against NBM as a calibrated baseline.

Related: items 185, 75, 21, 27; `[[highs-projection-data-gap-2026-06-20]]`.
