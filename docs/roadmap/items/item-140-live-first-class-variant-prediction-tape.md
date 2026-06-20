# 140. Live First-Class Variant Prediction Tape [PARTIAL 2026-06-18 - LIVE VARIANT TAPE CONTRACT LIVE, RUNTIME EXECUTION BLOCKED]

Goal: record first-class live predictions for active model variants at snapshot
time, not only after settlement through replay.

Source: 2026-06-18 model-variant data audit. The snapshot loop instantiates one
`TorontoHighTempModel`, calls `build()` once, and writes one
`model_probability` per market band. The existing replay input tape is valuable
because it preserves sources and recorded distributions, but active variant
probabilities are not emitted as live snapshot artifacts.

Why this matters: replay is necessary but delayed. A live variant tape lets us
measure online coverage, latency, missingness, source-state behavior, and
market-facing differences while the market is still active. It also prevents
serving-only probabilities from becoming the only first-class live signal.

## Design

1. Add a variant prediction interface that can run active registry variants
   against the same event, source bundle, timestamp, and band definitions used
   by the serving model.
2. Extend snapshot persistence with a separate append-only
   `variant_predictions_long.csv` and JSONL sidecar rather than widening
   `snapshots_long.csv`.
3. Include `variant_id`, `variant_family`, lifecycle/track metadata,
   artifact hash, postprocess hash, `model_version`, runtime identity,
   snapshot cadence, trigger context, band key, probability, and failure
   reason.
4. Record skipped variants explicitly when an artifact is unavailable or a
   variant cannot run on the current source bundle.
5. Keep the serving model unchanged until variant predictions clear replay and
   live-forward gates.

- [x] Define the live variant prediction contract and registry loader.
- [x] Add snapshot-store persistence for `variant_predictions_long.csv` and
  JSONL records.
- [x] Add failure rows for missing artifacts, unsupported tracks, and runtime
  exceptions.
- [x] Wire the snapshot loop to run selected active shadow variants per market
  tick without blocking the serving probability write.
- [x] Add collection-health and fleet-observability checks for live variant
  row freshness.

Acceptance: every captured snapshot has either a probability or an explicit
skip/failure row for each active shadow variant, with enough metadata to join
back to the serving snapshot, source status, market prices, and later
settlement labels.

Implementation update 2026-06-18:

- Added `weather.collection.live_variant_predictions` with schema
  `live_variant_predictions_v0.1`, active-registry filtering, band-key
  normalization, model-supplied variant probability support, and explicit
  `skipped`/`failed` rows for missing artifacts, unsupported tracks, and
  runtime exceptions.
- `SnapshotStore.write()` now appends `variant_predictions_long.csv` and
  `variant_predictions.jsonl` beside the existing snapshot tapes without
  widening `snapshots_long.csv`; variant tape failures are captured in the
  snapshot result and do not block the serving probability write.
- Collection health now checks that the latest serving snapshot has live
  variant rows for active registry variants, and fleet observability exposes a
  dedicated `variant_prediction_freshness` recovery gate.

Current blocker after item 142: the active registry now defines artifact,
export, and `live_runtime` contracts for every active headline variant, but the
snapshot loop still needs an explicit runtime runner that can execute those
contracts at capture time. Until `pooled_candidate_replay`,
`conservative_bridge_policy`, and CLOB-overlay `live_runtime` values are mapped
to bounded snapshot-time prediction functions, live rows are expected to be
explicit skip/failure rows rather than probability rows.
