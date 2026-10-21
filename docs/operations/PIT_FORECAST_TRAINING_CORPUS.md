# Point-In-Time Forecast Training Corpus

- **Owns:** the immutable training-only forecast corpus contract:
  `weather.sources.forecast_training_corpus` (`plan`, `resume-status`,
  `materialize`), its free Previous Runs collector
  `weather.sources.forecast_training_corpus_fetch`, staging/publication rules,
  and how retraining consumes the manifest.
- **Read when:** planning, staging, verifying or consuming a PIT forecast corpus,
  or debugging a base-retrain PIT-manifest preflight refusal.
- **Do not use for:** which forecast source/population was chosen
  ([forecast-source-and-training-population.md](forecast-source-and-training-population.md));
  the retrain procedure ([NIGHTLY_RETRAIN_RUNBOOK.md](NIGHTLY_RETRAIN_RUNBOOK.md)).
- **Verify with:** the subparsers at the end of
  `src/weather/sources/forecast_training_corpus.py` and
  `src/weather/sources/forecast_training_corpus_fetch.py`, and
  `FIRST_RETRAIN_*` / the station-day exclusion registry in
  `src/weather/operations/base_retrain.py`.

> **Status:** dormant. No collection, fit or retrain is authorized or scheduled
> (training disabled, new model-alpha work paused — `STATE_OF_PLAY.md`). The
> corpus module cannot fetch. The separate collector
> `weather.sources.forecast_training_corpus_fetch` exists; running it is an
> external fetch that needs its own owner approval, free source only (no paid
> weather APIs, no key).

This contract owns the training-only forecast input used to repair historical
forecast blindness without changing the active serving archive. The corpus is
immutable, cutoff-safe, content-addressed, and supplied explicitly to pooled
retraining. It is not a serving fallback and is never discovered through
`weather.sources.forecast_history.daily_path_for`.

## Safety boundary

- `weather.sources.forecast_training_corpus` contains no HTTP client. Its
  planner is always `dry_run_no_network` and never authorizes a provider probe
  or collection.
- The separately reviewed collector `weather.sources.forecast_training_corpus_fetch`
  submits raw response bytes to `stage_response` only after an immutable plan
  exists. Each unit is keyed by the plan's request hash. See
  [Collector](#collector) below.
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

### Field set (`--fields`)

`plan --fields temperature_2m` plans a subset of the frozen field contract.
Without `--fields` the plan is byte-identical to the pre-option planner (all 21
fields), so existing plans and manifests verify exactly as before. A subset is
written in canonical contract order, must contain `temperature_2m` (it carries
the daily high), and is carried by the plan's `source_fields`, every request's
variable bindings and URL, the coverage rows' `field_status`, and the
manifest's `source_fields`. Staging, `materialize` and manifest verification
check completeness against that planned set, never against the default.

**The free Previous Runs surface is temperature-only** (EF §4f, 441-cell probe:
only `temperature_2m_previous_dayN` returns data; the other fields are all-null
or HTTP 400). A 2021-2023 plan must therefore use `--fields temperature_2m`;
a 21-field plan for those years can never materialize. The consumer
dispositions in a subset plan are unchanged, so a pooled/base-retrain consumer
would see the non-temperature profile columns as missing; that consumer
question is separate from this corpus.

**Correction to the retrain sizing memo** (`docs/research/retrain-sizing-memo-2026-10-19.md`,
branch `claude/retrain-sizing-memo-20261019`, §2.2 and r2.1; not on master).
The memo says the repository's collector covers the 2021-2023 Previous Runs
fetch with `plan`, then `resume` and `materialize`. Before 2026-10-21 none of
those subcommands could fetch, nothing in the repository called
`stage_response`, and a default (21-field) plan for those years could never
materialize. The fetch step is the collector below, and the plan needs
`--fields temperature_2m`.

## Collector

`weather.sources.forecast_training_corpus_fetch` is the only repository-owned
network collector for this corpus. It fetches the free
`previous-runs-api.open-meteo.com` endpoint with no API key, credential or
environment variable, and writes nothing itself: every byte goes through
`stage_response` under the `--staging-root` you pass. A staging root that is,
contains or lies under `data/forecast_history` (or any `forecast_history`
directory) is refused before any request.

```powershell
python -m weather.sources.forecast_training_corpus plan `
  --out <run-root>\plan.json --years 2021,2022,2023 `
  --markets atlanta,austin,chicago,dallas,denver,houston,los-angeles,miami,nyc,san-francisco,seattle `
  --season-start 10-01 --season-end 12-31 --fields temperature_2m --pad-request-days 1
python -m weather.sources.forecast_training_corpus_fetch `
  --plan <run-root>\plan.json --staging-root <run-root>\staging [--max-requests 1]
python -m weather.sources.forecast_training_corpus resume-status `
  --plan <run-root>\plan.json --staging-root <run-root>\staging
python -m weather.sources.forecast_training_corpus materialize `
  --plan <run-root>\plan.json --staging-root <run-root>\staging `
  --publish-root data\training\pit_forecast_corpus
```

- **Politeness.** Strictly serial; at least `--min-interval-seconds` (default
  10) between requests; transport errors and 429/5xx retry with exponential
  backoff (`--backoff-base-seconds` 30, doubling, capped at 600,
  `--max-attempts` 5); a 429 waits at least its `Retry-After`. A unit that
  still fails is staged as a failed receipt (failure ledger) and the run stops.
- **Resume.** A hash-verified complete unit is skipped with no network call, so
  re-running the same command continues where it stopped. `--max-requests N`
  bounds a trial.
- **Issue evidence.** The API exposes no run id (`run_id_exposed: false`). For
  lead `N`, every hourly value on local date `D` comes from a run at least
  `N x 24 h` before that hour, so the collector records an upper bound: the
  latest 6-hourly UTC cycle at or before local 23:00 on `D` minus `N x 24 h`,
  plus `--availability-latency-hours` (default 6). Staging and `materialize`
  then require that bound to precede every feature cutoff. For US markets and
  cutoffs from 07:00 local it does. The lead semantics are the provider's
  documented ones and are not independently proven
  (`HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`, EF §1m).
- **Retry-After cap.** A `Retry-After` longer than `--backoff-cap-seconds` is
  not slept: the run stops (exit 2) and nothing is staged for that unit.
- **No redirects.** A 3xx is never followed; it is staged as a failed unit.
- **Protected roots.** Staging and publish roots under `src/` or `artifacts/`
  (via `weather.paths`) are refused as well as any `forecast_history` path.
- **Manifest.** `issue_evidence_bases` records each distinct
  `issue_time_basis`, `availability_latency_hours` and `run_id_exposed` the
  collector staged.

### DST and provider time labels

**Measured, not assumed (2026-10-21, from responses already on the
workstation, no fetch):** with `timezone=<IANA zone>` the Previous Runs API
labels the whole series with **one** offset, `utc_offset_seconds`, and that
offset is the zone's offset **at retrieval time**, not at the window start. An
Atlanta 2024 Jan 1-Feb 29 response retrieved in September 2026 carries
`-14400` (`GMT-4`) although January is EST; a Nov 1-Dec 31 response carries
`-14400` for all 1,464 hours with no repeated label.

Staging and `materialize` therefore never read a naive label as wall time when
the response carries a scalar `utc_offset_seconds` and no label repeats: the
UTC instant is `label - offset`, and the local date and hour come from the
market zone (`resolve_provider_times`). A response with no offset, or with a
repeated label (a fall-back hour, which a fixed-offset series cannot produce),
is read as true local time with `fold=1` on the repeat; a label that does not
exist in the zone is rejected. Every local date must then hold exactly one
on-the-hour row per real hour (23, 24 or 25; `hours_in_local_date`), with
distinct UTC instants. Cutoffs and issue checks use the same UTC instants.

**Consequence:** an unpadded fixed-offset response whose window crosses a DST
change is always one real hour short at one edge date (the window's last date
if retrieved under daylight time, its first date if under standard time), so
the unit fails closed with `incomplete_hourly_envelope`. Before 2026-10-21 that
case passed and every row on the far side of the change was silently one hour
off.

**Request padding (`plan --pad-request-days N`, opt-in, 1-3).** Each request's
provider window becomes `window_start - N` to `window_end + N`; the planned
target dates, `expected_local_dates` and every coverage count are unchanged.
The plan records `request_padding` (`enabled`, `days`, `purpose`) and each
request `request_pad_days`, so `verify_plan`, `resume-status` and the manifest
refuse a plan or corpus whose padding disagrees, and a padded plan's request
hashes never match units staged for an unpadded one. A pad that would reach
the target year is refused. Staging and `materialize` resolve every label to
its UTC instant first, then keep a row only if that instant's market-local
date is a planned target date; pad rows (and nulls inside them) never count
toward any planned date and never reach the published files. The per-date
check (23/24/25 distinct UTC instants) runs on planned dates only. Without the
flag the plan is byte-identical to before. **Every October-December plan needs
`--pad-request-days 1`.**

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
built-in markets. The versioned, code-owned, reason-bearing station-day
exclusion registry is intersected with that window before the expected matrix is declared. For
the 2026-07-31 target, Denver 2025-07-28 is the only applicable exclusion, so
the plan requires 74 Denver dates, 75 dates for each other market, and 12,586
fleet cells. Denver 2022-07-20 is also registered but lies outside this target
window. Candidate-supplied `covered_years`, selected dates, counts, minimums,
or omissions can prove rows only; they cannot reduce the required matrix or
add another exclusion.

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

## Update this file when

Update when the corpus CLI, plan/staging/publication contract, excluded
forecast fields, the first-retrain selection or exclusion registry, the
research A/B/C variants, or the corpus storage class changes.
