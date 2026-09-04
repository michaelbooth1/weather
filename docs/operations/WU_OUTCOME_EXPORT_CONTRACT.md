# WU outcome gap and production export contract

`weather.operations.wu_outcome_export_contract` owns the outcome-blind coverage
inventory and the validator for a future bounded production export. Its current
machine contract is the dated
[`wu-outcome-gap-production-export-spec-2026-09-100a.json`](../roadmap/wu-outcome-gap-production-export-spec-2026-09-100a.json).

The gap builder derives its market/date cohort from the frozen design and
external amendment. It verifies the immutable 2026 NWP transfer and each frozen
WU daily-summary file before reading only `schema_version`, `local_date`,
`temperature_unit`, and `row_count`. It selects the latest physical CSV revision
for a duplicate date unless an explicit revision number is present. The output
contains every cohort key and classifies it as `present_admissible`,
`present_below_threshold`, or `missing`; it contains no settlement temperature.
The pre- and post-2026-07-31 sides remain separate.

The repository has no reviewed production exporter for this contract. The
machine spec records that absence and gives no production command. The smallest
missing implementation is a read-only entry point that verifies settlement
ledger history, selects the authoritative revision for each requested
`(market_id, target_date)`, and creates the exact two-file artifact in the spec.
It must use configured WU history only, bind pre/post source identities, and fail
if any requested authoritative row is absent or has fewer than 18 WU daily rows.

The validator accepts only a new, non-reparse directory containing
`manifest.json` and `wu-outcomes.jsonl`. It enforces exact request coverage,
native units and stations, boundary sides, per-file identities, manifest
self-hash, unchanged source hashes, byte/file bounds, and the recorded ACL
proof. It returns counts and hashes without returning settlement values.

Run all builder, validator, and test invocations on the assigned workstation
through `scripts/ops/workstation_heavy.ps1`; the module is in that wrapper's
offline allowlist. The builder and validator do not contact a provider, inspect
market data, alter ledgers or corpora, fit models, create probabilities, or
authorize downstream evaluation or live use.
