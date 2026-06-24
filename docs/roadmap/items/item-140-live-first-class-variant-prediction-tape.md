# 140. Live First-Class Variant Prediction Tape [COMPLETE 2026-06-22 - LIVE VARIANT RUNTIME RUNNERS WIRED]

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

Completion update 2026-06-22:

- Added bounded live runtime dispatch for `pooled_candidate_replay`,
  `conservative_bridge_policy`, and CLOB-overlay `microstructure_shadow_report`
  registry contracts.
- Pooled candidate artifacts now score the live snapshot feature vector against
  the captured market bands, including artifact hashing, postprocess metadata,
  partition normalization, and current-serving blend metadata where configured.
- Conservative bridge variants emit explicit serving-probability passthrough
  rows until their base candidate payload is available, preserving live tape
  coverage without changing the serving model.
- CLOB overlay variants now distinguish taxonomy-gated rows from raw
  microstructure overlays instead of falling through to generic unsupported
  runtime skips.
- Covered the runner contract with live-variant tests for bridge passthrough,
  pooled artifact scoring, missing feature vectors, taxonomy-gated CLOB rows,
  persistence, and collection-health freshness.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - LIVE VARIANT RUNTIME RUNNERS WIRED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

