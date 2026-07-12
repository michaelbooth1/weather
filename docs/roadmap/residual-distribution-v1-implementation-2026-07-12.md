# ResidualDistributionV1 implementation

- Date: 2026-07-12
- Status: implemented as an inert shadow candidate; not qualified, promoted, or release-routable

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

This is deliberate. Live capture should be enabled only after a real
candidate-only artifact passes nested PIT evaluation. Release routing should
remain unsupported until all of these are available and hash-bound:

- a frozen candidate artifact and feature/source-health contract;
- at least 14 untouched outer fleet dates with a three-day embargo;
- paired candidate-versus-control Brier/log-loss results with no material
  per-market regression;
- exact live/replay parity on fresh captured input;
- a release-bound 14-day forward shadow with complete partitions and named
  abstention coverage;
- a verified immutable release manifest and active pointer.

No worker, schedule, serving pointer, release artifact, or trading permission
was changed as part of this implementation.

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
  --artifact artifacts/candidates/residual_distribution_v1/model.pkl `
  --report data/backtest/residual_distribution_v1_requalification.json `
  --locked-dates-file data/backtest/residual_distribution_v1_locked_dates.json
```

These commands do not enable live capture or construct a release. A bounded
smoke run is research evidence only; use the full frozen corpus and a
predeclared locked window for any qualification claim.
