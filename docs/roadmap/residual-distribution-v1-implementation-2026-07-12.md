# ResidualDistributionV1 implementation

- Date: 2026-07-12
- Status: P0 implementation complete; still blocked on new release-bound capture and forward evidence

## Outcome

The new candidate implements this single graph:

```text
captured PIT weather inputs
  -> explicit availability, missingness, and source health
  -> one pooled forecast-residual Ridge model
  -> one canonical-F Gaussian residual density
  -> settlement-valid printed-high truncation
  -> complete native market-band partition
  -> identity or one global simplex temperature
  -> prediction or named abstention
```

It does not call the incumbent binary-band model, density postprocessors,
forecast centering, adjacent/winner corrections, market or incumbent blends,
late lock-in heuristics, routers, or HGB/LR/empirical fallbacks.

## Code boundaries

- `src/weather/model/residual_distribution_v1.py` is the pure graph used by
  live and replay. It owns artifact validation, canonical unit conversion,
  explicit missing indicators, source-health aggregation, residual inference,
  Gaussian density construction, legal truncation, market-band projection,
  coherent calibration, and named failure/abstention results.
- `src/weather/calibration/residual_distribution_corpus.py` creates one
  hash-linked checkpoint per market/date/cutoff directly from captured
  `replay_inputs.jsonl`. Settlement is joined only after feature construction.
  Missing checkpoints are excluded rather than borrowed from another hour.
- `src/weather/calibration/simplex_calibration.py` fits the only V1 calibrator:
  a global `p ** (1 / T)` transform over a complete ordered partition. Hard
  zeros survive and identity is retained unless both categorical Brier and log
  loss improve on OOF rows.
- `src/weather/calibration/residual_distribution_v1.py` owns fold-local pooled
  residual training, inner-OOF scale/calibration, whole-fleet-date nested
  evaluation, ablations, final fitting, lineage, and candidate-only writes.
- `src/weather/collection/live_variant_predictions.py` contains a bounded
  shadow adapter. It forwards the captured feature vector and source
  diagnostics to the pure graph and persists its named status without invoking
  legacy correction stages.
- `src/weather/calibration/pooled_candidate_replay.py` has an equivalent replay
  adapter over the same pure function. Captured source state is mandatory; it
  is never fabricated as all-fresh.

## Target and feature contract

The supervised target is:

```text
settled daily high F - PIT forecast anchor F
```

The base feature contract is intentionally small: forecast anchor, observed
high/current temperature relative context, recent rise/warming, hours at peak,
forecast gap/source count/disagreement, cutoff timing, live-reading context,
physical-guidance invalid count, startup quarantine flag, market ID, and
explicit aggregate/per-required-source health. Every nullable base feature has
both an availability and missing indicator. Native C values and deltas are
converted to canonical F exactly once.

The runtime rejects an unknown market, native-unit mismatch, feature-schema
mismatch, missing forecast anchor, a required feature absence, or source state
outside the artifact's trained policy. Input incompatibility is a named
non-countable skip. Artifact corruption, malformed band partitions, and model
exceptions are named failures. Neither condition invokes another model.

## Point-in-time and validation contract

- Corpus selection is the earliest captured prediction at or after each
  predeclared cutoff, bounded by a declared maximum lateness. No other hour or
  later row is substituted.
- Preprocessing, imputation, categorical encoding, scaling, model fitting,
  residual-width estimation, and calibration are fold-local.
- Folds are expanding whole-fleet-date rolling origins with a three-calendar-day
  embargo. Inner validation produces the only rows used to select/tune an
  outer-fold model, residual width, or calibrator.
- Checkpoint weights are equal by fleet date, then market-day, then cutoff. Band
  count cannot change a checkpoint's weight.
- Evaluation uses complete-partition categorical Brier and winning-band log
  loss. Ablation arms share identical folds and weights; simpler arms win within
  the declared non-inferiority margin.
- Old, research-unbound replay tapes remain usable for development but are
  tagged `research_only`. They are not promotion evidence.

## Settlement and calibration order

The order is fixed and tested:

1. Build the canonical-F residual density.
2. Remove mass in settlement buckets made impossible by the authoritative
   printed observed high.
3. Renormalize the density.
4. Integrate it over the complete registered market partition using native
   rounding intervals.
5. Apply identity or one global simplex power temperature and normalize once.

There is no soft probability stage after step 5.

## Shadow and release boundary

`config/model_variant_registry.json` records `residual_distribution_v1` as a
blocked shadow with `live_capture_enabled=false`,
`active_for_headline=false`, and
`counts_toward_weather_model_promotion=false`. The declared artifact path is
under `artifacts/candidates/`, not a serving or immutable-release path.

This is deliberate. Qualification and promotion are now two separate,
non-circular phases:

1. Offline nested PIT evaluation may produce `OFFLINE_PASS`. That state permits
   construction of one immutable, inactive release, but it is never promotion
   permission.
2. Exact live/replay parity and the contiguous 14-day streaming window are
   collected after the freeze and must name the exact candidate ID, release
   ID, release-manifest SHA-256, and candidate-artifact SHA-256.
3. A self-hashed forward attestation is written outside the immutable release.
   It does not activate a pointer. Any later activation remains a separate,
   explicit operation.

The offline release cannot be built until all of these are available and
hash-bound:

- a frozen candidate artifact and feature/source-health contract;
- at least 14 untouched outer fleet dates with a three-day embargo;
- paired candidate-versus-control Brier/log-loss results with no material
  per-market regression;
- executable E3/E4 calibration and stage-removal evidence plus its verified
  retirement register;
- PASS E5-E7 leakage, fault, timing, metamorphic, settlement, and rare-regime
  stress evidence;
- a verified semantic corpus manifest and output-bound fit-receipt graph.

The external promotion attestation then requires exhaustive branch/fleet
live/replay parity and a release-bound 14-day forward shadow with complete
partitions, a single runtime identity, zero unsupported skips, and named
abstention coverage. The active pointer is deliberately not part of either
builder.

No worker, schedule, serving pointer, or trading permission was changed as part
of this implementation.

## P0 hardening completed

The audit follow-up changed more than the candidate graph:

- Live and replay now use one pure current-blend resolver with identical
  market/default, freshness, context, multi-match, and missing-field semantics.
- Forecast and observation raw payload retention is default-on and uses
  deduplicated SHA-256 content-addressed blobs with explicit provenance gaps.
- Settlement revisions are append-only, hash-chained, and retain supersession,
  old/new values, raw evidence hashes, timing, and override provenance.
- Observation payloads and CLOB capture status are required event/storage/
  archive/PIT/backup families. Missing or mixed-identity event manifests fail
  closed.
- Historical feature validation now fits preprocessing inside each blocked
  training fold and reports cross-fitted calibration rather than selecting and
  reporting a transform on the same held-out predictions.
- Nullable weather context is preserved as null; degraded required-source
  states are a serving permission boundary and cause named abstention.
- Qualification now requires a verified v2 corpus manifest, all rows bound to
  one release and runtime, complete fleet-date coverage, a pre-selection lock,
  at least 14 outer and 14 locked dates, captured incumbent/Item 50/dynamic/
  climatology comparators, clustered intervals, and recomputable output-bound
  fit receipts. Only an exact offline PASS can be frozen.
- Event-manifest countability is semantic, not filename-based: every required
  family/file/hash/row count, release/config identity, runtime commit/source
  fingerprint, and replay/settlement proof is reverified against the live
  folder. Forged, stale, or incomplete lineages remain research-only.
- Forecast and observation JSONL rows are cross-checked against canonical
  content-addressed raw blobs. Missing, corrupt, mislinked, outside-folder,
  symlinked, or orphan blobs block the event manifest. Recursive forecast blobs
  are included in archive plans and restore evidence.
- Real source attempts now propagate separate request-start and response times
  plus explicit parser and payload-schema versions into snapshot persistence.
- The legacy pooled trainer no longer tunes temperature, adjacent, exact-winner,
  or market-bias transforms on the outer holdout. It serializes identity for
  those stages with a receipt proving zero holdout fit rows.
- The E3/E4 executor owns a bounded complete calibration/remove-one/cumulative/
  order-interaction matrix, scores paired whole dates with clustered intervals,
  and emits the exact self-hashed artifact consumed by the retirement gate.
- `weather.residual_distribution_release` first builds and verifies a
  write-once inactive release from exact `OFFLINE_PASS` evidence, including
  E3-E7 reports. Its separate forward-attestation builder accepts only
  exhaustive, self-hashed parity and canonical streaming evidence bound to
  that exact release. Both prove `current_release.json` is byte-for-byte
  unchanged.
- Legacy weather-only variants remain available for comparator capture but are
  explicitly excluded from headline/promotion evidence pending clean
  requalification.

The retained historical tapes predate these contracts. They remain research
inputs and are not silently upgraded: missing raw blobs, manifests, release
IDs, comparator rows, or immutable settlement revisions stay visible as
qualification blockers.

## Current bounded evidence

The post-hardening Atlanta smoke materialization was deliberately capped at 20
market days and two cutoffs. It produced 27 rows across 14 fleet dates, with 7
explicit exclusions. All 27 retained rows are `research_only`; zero are
release-bound. Every one of the 20 source folders fails the new semantic
manifest contract, so the corpus input contract is `BLOCK` rather than being
retrospectively upgraded.

The bounded trainer run produced a valid candidate-only artifact with verified
output-bound fit receipts, but overall and offline qualification are `BLOCK`:
only four outer dates were feasible, the one-date smoke lock is below the
14-date minimum, there is no preselection ledger entry, release/runtime
identity is missing, fleet coverage is incomplete, and the source-health rows
do not match the fresh-only serving permission. The refreshed E5-E7 report is
`INCONCLUSIVE` because no row is serve-eligible under that fresh-only policy.
No immutable candidate release or forward attestation was built from these
smoke artifacts.

## Reproducible research commands

Materialize a bounded smoke corpus from captured replay inputs:

```powershell
python -m weather.calibration.residual_distribution_corpus `
  --market-id atlanta `
  --max-market-days-per-market 2 `
  --cutoff-hours 8,12 `
  --out data/backtest/residual_distribution_v1_training_corpus.jsonl `
  --manifest-out data/backtest/residual_distribution_v1_training_corpus_manifest.json
```

After replacing that smoke corpus with the full frozen fleet corpus, train and
evaluate into the guarded candidate path:

```powershell
python -m weather.calibration.residual_distribution_v1 `
  --corpus data/backtest/residual_distribution_v1_training_corpus.jsonl `
  --corpus-manifest data/backtest/residual_distribution_v1_training_corpus_manifest.json `
  --artifact artifacts/candidates/residual_distribution_v1/model.pkl `
  --report data/backtest/residual_distribution_v1_requalification.json `
  --locked-dates-file data/backtest/residual_distribution_v1_locked_dates.json `
  --preselection-lock-ledger data/backtest/residual_distribution_v1_preselection_locks.jsonl
```

The pre-selection ledger entry must be appended in a separate command before
training; training never creates its own retrospective lock. Pre-release
parity or streaming files are intentionally ignored by the trainer because
they cannot yet bind an immutable candidate release.

After an exact offline PASS, use
`build_residual_distribution_v1_offline_release` with the artifact,
requalification, corpus manifest, preselection lock, E3/E4 ablation, retirement
register, E5-E7 stress report, and registry snapshot. After forward collection,
use `build_residual_distribution_v1_forward_attestation` with the immutable
release plus the external parity and streaming artifacts. The latter artifacts
must carry the exact release-manifest and model-artifact hashes and the parity
coverage contract must contain every predeclared market/branch pair.

Forward collection is opt-in and residual-only. Set
`WEATHER_RESIDUAL_DISTRIBUTION_V1_SHADOW_RELEASE_DIR` to the verified inactive
release directory and pin its exact manifest with
`WEATHER_RESIDUAL_DISTRIBUTION_V1_SHADOW_MANIFEST_SHA256`. The snapshot loop
then loads a distinct `SHADOW_BOUND` bundle for variant tape rows only; it does
not replace the active base-model bundle or read/write the active pointer.

These operations do not enable live capture, activate a pointer, or grant
trading permission. A bounded smoke run is research evidence only; use a
complete immutable corpus and a predeclared contiguous locked window for any
qualification claim.
