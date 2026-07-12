# Point-In-Time Evaluation Runbook

`weather.reporting.validation.point_in_time_evaluation` owns the derived
point-in-time row contract, fleet-date rolling validation plans, and bounded
14-calendar-day evaluator. It does not train or promote a model.

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

Only these evidence lanes are valid, and evaluation never pools them:

- `weather_only`
- `market_benchmark`
- `market_informed`
- `trading`

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
from canonical evidence.

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
