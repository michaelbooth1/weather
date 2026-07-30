# Point-In-Time Evaluation Runbook

`weather.reporting.validation.point_in_time_evaluation` owns the derived
point-in-time row contract, candidate-independent production preselection,
fleet-date rolling validation plans, bounded 14-calendar-day evaluation, and
production candidate qualification. It does not train or promote a model.

## Evidence contract

The canonical key is:

```text
(target_date, market_id, cutoff_or_snapshot, band, variant_id, release_id)
```

Every row also preserves canonical source-payload JSON and its SHA-256,
archive/text-reader provenance, feature-availability and prediction times,
label quality/countability, claim lane, replay/serve parity, source quality,
transformation version, score fields, and runtime identity. Missing release or
runtime identity is rejected; it is never inferred from an old model name.

That full row contract applies after a candidate exists. The production
preselection source uses the separate, narrow
`production_point_in_time_preselection_source_v1` schema. It contains only
`target_date`, `market_id`, `cutoff_or_snapshot`, `band`, feature-availability
and prediction-boundary timestamps, label quality/countability, claim lane,
source quality, and the settled binary label. Candidate, variant, release,
probability, runtime, and source-payload fields are physically absent so a
model cannot determine the population that is locked before training.

Only these evidence lanes are valid, and evaluation never pools them:

- `weather_only`
- `market_benchmark`
- `market_informed`
- `trading`

## Prelock A Production Population

Production preselection verifies a candidate-independent source before
training, freezes its bounded replay inventory, and locks a contiguous 14-day
evaluation window:

```powershell
python -m weather.reporting.validation.point_in_time_evaluation prelock-production `
  --source-corpus <production-preselection-source-v1.parquet> `
  --source-manifest <production-preselection-source-v1-manifest.json> `
  --source-replay-manifest <promotion-corpus.json> `
  --replay-manifest-out <candidate>/qualification/point_in_time/work/replay_manifest.json `
  --lock-out <candidate>/qualification/point_in_time/work/preselection_lock.json
```

To build that narrow source directly from reviewed market-day folders:

```powershell
python -m weather.reporting.validation.point_in_time_evaluation prelock-production `
  --folder <snapshots-root>/<settled-event-1> `
  --folder <snapshots-root>/<settled-event-2> `
  --source-corpus-out <candidate>/qualification/point_in_time/work/preselection-source.parquet `
  --source-manifest-out <candidate>/qualification/point_in_time/work/preselection-source-manifest.json `
  --replay-manifest-out <candidate>/qualification/point_in_time/work/replay_manifest.json `
  --lock-out <candidate>/qualification/point_in_time/work/preselection_lock.json
```

Repeated `--folder` may be used instead of the paired source corpus and
manifest. Folder mode first builds a quality-grade-only, manifest-pinned replay
inventory and then enumerates every pinned snapshot/band directly from
`snapshots_long.csv` plus captured `replay_inputs.jsonl`; it does not load or
score an ambient model. A supplied source replay manifest is hash-verified.
When it is omitted for a staged source, the exact replay manifest bound in the
source manifest is copied byte-for-byte into the candidate work area.

The prelock records the complete candidate-independent selection universe, its
hash, the source/replay hashes, and the 14 locked dates. Its latest target date
must be no more than seven days old when the lock is created; a freshly
generated evaluation over a stale or truncated corpus cannot qualify. The
reader rejects reconstructed or unsettled inputs, promotion-countable
admission, folders outside the configured snapshots root, changed input bytes,
inventory drift, duplicate coordinates, and any snapshot without exactly one
winning band. `source_quality=healthy` means those pinned structural and input-
integrity checks passed; it is not a claim that the forecast has predictive
edge.

The operational Toronto `streak.ps1` count is necessary but not sufficient for
this contract. It checks ledger grade/capture cadence, while the staging
receipt requires fourteen exact current `complete` revisions and the source
reader independently verifies every pinned folder and byte inventory. Strict
release-bound replay/serve parity adds a captured-input self-hash gate. That
hash restores the schema-owned integer type of `recorded_distribution`
temperature-bucket keys before canonical JSON hashing, plus nested numeric-key
maps only when their persisted numeric ordering proves the original type.
JSON persistence represents every object key as a string. This is typed
canonicalization, not insertion-order acceptance; malformed JSON still fails
the whole strict source file.

Production accepts at most 60 market-days and 250,000 rows per market-day,
retains one raw market-day at a time, and writes Arrow batches of at most 65,536
rows. Each tape is capped at 128 MiB with 1 MiB CSV fields; each captured replay
file is capped at 64 MiB with 8 MiB lines and the same per-day record bound;
optional feature CSVs use the tape bounds, settlement JSON is capped at 1 MiB,
the replay manifest at 16 MiB, the source manifest at 4 MiB, and the source
Parquet at 1 GiB. Request bounds are validated before source I/O. Exclusive
output locks reject concurrent writers. Each file is published atomically with
the manifest last, and consumers require both files plus their exact hashes;
the pair is not a single atomic filesystem operation. Failed verification
removes published outputs. A host crash can leave a lock or manifest-less
orphan requiring reviewed cleanup. No candidate artifact exists when this lock
is chosen.

The lock must then flow into every selection owner. Pooled feature and source-
reliability priors, family calibration/trust, final pooled fitting, and routing
selection exclude the 14 dates. Calibration and routing artifacts carry
self-hashed bindings with `used_for_selection: false`; their inventory hashes
must stay inside the exact immutable selection universe minus the locked dates.

## Qualify A Production Candidate

After the actual trainers finish, qualification consumes the manifest-pinned
prelock and replay inventory. It rejects raw-folder substitution, loads the
exact fitted pickle, verifies its nested-fold evidence, freshly scores the
pinned population, and attaches settlement evidence only after prediction:

```powershell
python -m weather.reporting.validation.point_in_time_evaluation qualify-production `
  --candidate-id <candidate-id> `
  --release-id <candidate-id> `
  --model-artifact <candidate>/model/feature_model_hgb_f_pooled_v0_3.pkl `
  --calibration-artifact <candidate>/calibration/f_family_secondary_artifacts.json `
  --routing-artifact <promotion-refresh.json> `
  --preselection-lock <candidate>/qualification/point_in_time/work/preselection_lock.json `
  --replay-manifest <candidate>/qualification/point_in_time/work/replay_manifest.json `
  --corpus-out <candidate>/qualification/point_in_time/corpus.parquet `
  --manifest-out <candidate>/qualification/point_in_time/materialization_manifest.json `
  --validation-plan-out <candidate>/qualification/point_in_time/validation_plan.json `
  --evaluation-out <candidate>/qualification/point_in_time/streaming_evaluation.json
```

The four outputs share one self-hashed candidate-training graph. That graph
binds the preselection and window identities, exact model/calibration/routing
hashes, canonical route decision, source replay, folds, all fit receipts, and
the serialized final-refit receipt. Every outer and inner scope must have six
chained receipts produced by the pooled training path: feature selection,
scaling/imputation, model, calibration, postprocessing, and regime routing.
The last three execute the currently served identity-disabled calibration/
postprocessing policy and predeclared single route; their receipts bind real
fold inputs and outputs without representing those fixed policies as learned
parameters.
Candidate verification re-inspects the Parquet structure and resource bounds;
immutable-release verification rechecks the frozen hash graph without loading
PyArrow into serving processes.

Production qualification defaults to a 4 GiB declared private-memory budget,
128 fold scopes, seven-date fold steps, 65,536-row Parquet batches, and one raw
market-day retained at a time. The replay producer hands off an explicit
market-day batch and cannot score the next day until the writer has flushed and
released the current one. Canonical row hashing is incremental, and Arrow
conversion is chunked to at most 65,536 rows even when the market-day bound is
larger. Raw training inputs are also read one market-day at a time, while the
non-incremental HGB fit honestly retains a separately capped normalized
population (at most 60 × 1,000 source rows). These production bounds are
intentionally stricter than the generic materializer's 500-day pilot maximum
below.

## Materialize bounded derived rows

```powershell
python -m weather.reporting.validation.point_in_time_evaluation materialize `
  --snapshots-root data/snapshots `
  --archive-root data/archive/closed_market_days/v0.1 `
  --as-of 2026-07-12 `
  --max-market-days 500 `
  --max-rows-per-market-day 250000 `
  --out data/analysis/point_in_time/v0.1/point_in_time_rows.parquet `
  --manifest-out data/analysis/point_in_time/v0.1/point_in_time_manifest.json
```

The reader preference is validated Parquet, gzip-tiered text, then the source
text tape. One market-day frame is retained at a time. The source tree is never
modified. The command writes a Zstandard Parquet projection and a manifest
containing its hash, row count, transformation version, input provenance,
reader modes, bounds, and all exclusion reasons. Any missing contract field or
duplicate key makes the manifest `BLOCK` and the command exits nonzero.
All emitted artifacts use timezone-aware `generated_at_utc`; naive timestamps
are rejected.

Use `--folder` repeatedly for a bounded pilot. `--text-only` is a diagnostic
fallback and records that choice in source-mode provenance. Historical rows
without immutable `release_id`, point-in-time timestamps, countable settlement
labels, or runtime identity will correctly block until their lineage is joined
from canonical evidence. This generic materializer is not accepted as a
production preselection source. The narrow production source instead begins
from manifest-pinned captured rows before candidate identity exists; it never
invents release or runtime lineage.

## Create nested rolling-origin folds

Put one fleet target date per line in `fleet_dates.txt`, then run:

```powershell
python -m weather.reporting.validation.point_in_time_evaluation folds `
  --dates-file fleet_dates.txt `
  --outer-min-train-dates 14 `
  --inner-min-train-dates 7 `
  --embargo-days 3 `
  --out data/backtest/point_in_time_validation_plan.json
```

The embargo is a calendar interval and must be predeclared between three and
seven days. A fleet date is indivisible: all markets, snapshots, bands, and
variants for that date remain in the same partition. Inner folds are built
only from the corresponding outer-training dates. Code using
`run_training_only_pipeline` supplies fresh factories for feature selection,
scaling/imputation, model fitting, calibration, postprocessing, and regime
routing; each hook's `fit` method receives training-fold rows only.

## Evaluate a locked 14-day window

```powershell
python -m weather.reporting.validation.point_in_time_evaluation evaluate `
  --input data/analysis/point_in_time/v0.1/point_in_time_rows.parquet `
  --manifest data/analysis/point_in_time/v0.1/point_in_time_manifest.json `
  --window-days 14 `
  --window-end 2026-07-11 `
  --bootstrap-iterations 2000 `
  --out data/backtest/point_in_time_streaming_evaluation.json
```

Before scoring, the evaluator hashes and locks the calendar window. Missing
calendar dates block the result. Raw rows are reduced to cutoff scores and then
equal-cutoff market-day summaries; no raw row survives a market-day flush.
Reports include selected label qualities, every exclusion reason/date,
market-days, fleet dates, source modes, source-quality failure rate, and runtime
identities. Both equal-market-day and equal-fleet-date estimates receive a
deterministic bootstrap interval that resamples entire fleet dates.

Weather-only and market-informed rows require replay/serve parity `pass` to be
countable. Incomplete/quarantined labels and stale/failed sources remain
diagnostic. Any rejected or duplicate band poisons its whole cutoff, so a
partial simplex cannot survive as countable evidence. A stale/failed row rate
of exactly 5% blocks: the declared target is strictly below 5%. This evaluator
supplies evidence; it does not grant promotion or trading permission.

## Update this file when

Update when the row key or lineage fields, production prelock/source contract,
fold or embargo semantics, fit-receipt stages or payload binding, qualification
role graph, locked evaluation rules, or resource bounds change.
