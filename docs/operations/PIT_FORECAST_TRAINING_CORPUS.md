# Point-In-Time Forecast Training Corpus

This contract owns the training-only forecast input used to repair historical
forecast blindness without changing the active serving archive. The corpus is
immutable, cutoff-safe, content-addressed, and supplied explicitly to pooled
retraining. It is not a serving fallback and is never discovered through
`weather.sources.forecast_history.daily_path_for`.

## Safety boundary

- `weather.sources.forecast_training_corpus` contains no HTTP client. Its
  planner is always `dry_run_no_network` and never authorizes a provider probe
  or collection.
- A separately reviewed collector may submit raw response bytes to
  `stage_response` only after an immutable plan exists and provider semantics
  have been probed. Each unit is keyed by the plan's request hash.
- Staging records the allowlisted HTTP metadata, retrieval timestamp, response
  SHA-256, byte and row counts, validation result, and issue/run evidence.
  Zero-row or invalid units are failures. Resume skips only a complete unit
  whose receipt, byte count, and raw-response hash still verify.
- Materialization requires every planned market/year request. Every target
  date must have exactly 24 local hourly rows, all contracted fields, valid
  units, accepted issue evidence, and both `issue_time_utc` and
  `available_at_utc` at or before every feature cutoff.
- Target-year rows, empty issue identity, and stitched continuous-archive rows
  fail closed. Partial or zero-row builds never enter a `corpora/` directory.
- Publication verifies the complete temporary corpus, derives its identity
  from the plan and file hashes, and atomically renames it to
  `corpora/<corpus_id>`. An existing identity is never overwritten.

The active analog archive remains pinned. Forecast-relative marine fields,
forecast-error secondary artifacts, late-day continuation, and analog distance
are explicitly excluded from this first corpus. Every pooled forecast-profile
column is either mapped to a source field or named in the exclusions receipt.

## Dry-run planning

Run the planner from the repository root. The command performs no network I/O:

```powershell
python -m weather.sources.forecast_training_corpus plan `
  --out <run-root>\pit-forecast-plan-2021-2025.json `
  --years 2021,2022,2023,2024,2025 `
  --target-year 2026
```

The plan pins markets, seasonal dates, cutoff hours, the source model, fixed
lead, variables and units, endpoint parameters, request hashes, consumer
dispositions, estimated call equivalents, and exact expected coverage. Writing
different content to an existing plan path is refused.

Use the same module's `resume-status` and `materialize` commands after an
authorized collector has populated request-keyed staging. Neither command
fetches data. Failed units are recorded in `failure_ledger.jsonl`.

## Retraining input

Pooled retraining accepts the corpus only through the explicit option:

```powershell
python -m weather.calibration.pooled_feature_cli `
  --pit-forecast-corpus-manifest <corpus-root>\manifest.json `
  <other reviewed training arguments>
```

Before record assembly, the preflight verifies the manifest and every file
hash, reconstructs the exact market/date/cutoff matrix from `plan.json`, checks
daily and hourly row hashes and point-in-time timestamps, verifies all profile
field dispositions, and rejects paths overlapping the active forecast archive.
When this option is present there is no compatibility fallback to ambient
`data/forecast_history` files. Forecast-relative marine columns are nulled so
they cannot retain values derived from the legacy archive.

The all-market base-retrain lane uses the same manifest through its required
`--pit-forecast-corpus-manifest` option (or nightly's
`--base-retrain-pit-forecast-corpus-manifest` binding). Its preflight requests
the exact planned market/date/cutoff selection, then matches the corpus receipt
against PIT provenance flattened into every hash-bound feature record. Corpus
identity, request/raw-response hashes, native forecast value and unit, and
issue/availability/as-of timestamps must all agree. Legacy records assembled
from ambient `forecast_daily.csv` have no such provenance and fail closed.

The first-retrain selection is owned by the hash-bound retrain plan, not by a
source or feature-corpus manifest: training years 2021-2025, the target
month/day plus or minus seven days in each year, cutoff hours 07-20, and all 12
built-in markets. For the 2026-07-31 target that is 75 dates, 1,050 cells per
market, and 12,600 fleet cells. Candidate-supplied `covered_years`, selected
dates, counts, or minimums can prove rows only; they cannot reduce the required
matrix.

This input does not authorize fitting, promotion, serving changes, or release
binding. Those remain separate reviewed actions under the nightly retrain and
release runbooks.

### Honest-versus-rich research inputs

The pooled trainer also has an explicit research-only A/B/C input for measuring
settled-archive contamination. It reads only a caller-supplied forecast-history
root and never discovers the active serving archive:

```powershell
python -m weather.calibration.pooled_feature_cli `
  --forecast-training-variant honest `
  --forecast-history-root <run-root>\forecast_history `
  --pit-lead-days 1 `
  <other reviewed training arguments>
```

The variants are `honest` (fixed-lead Previous Runs daily high, no settled
profiles), `rich` (settled historical-forecast daily high and profiles), and
`hybrid` (fixed-lead Previous Runs daily high plus settled profiles). Honest
and hybrid validate issue time, lead, market, station, unit, duplicates, and a
complete 24-hour daily high before record assembly. Forecast-relative marine
features are nulled whenever the high is point-in-time.

This A/B/C reader is evidence for a controlled research comparison. It is not
the immutable, content-addressed production corpus above, does not satisfy the
base-retrain PIT-manifest preflight, and does not authorize a fit, candidate,
promotion, serving change, or release binding.

## Storage and retention

Raw staging and published corpora are `canonical_evidence` under the
[Data Storage Class Contract](data-storage-class-contract.md). Plans,
preflight receipts, and failure ledgers are evidence for the same run. Keep
task execution under its declared run root until a separate operating decision
assigns a durable repository-owned location. Never publish into or below
`data/forecast_history`.
