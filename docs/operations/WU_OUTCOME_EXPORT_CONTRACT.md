# WU outcome gap and production export contract

`weather.operations.wu_outcome_export_contract` owns the outcome-blind coverage
inventory, production-export CLI, and artifact validator.
`weather.operations.wu_outcome_production_exporter` owns the dependency-light
filesystem transaction behind that stable entry point. The frozen machine
contract is the dated
[`wu-outcome-gap-production-export-spec-2026-09-100a.json`](../roadmap/wu-outcome-gap-production-export-spec-2026-09-100a.json).

The gap builder derives its market/date cohort from the frozen design and
external amendment. It verifies the immutable 2026 NWP transfer and each frozen
WU daily-summary file before reading only `schema_version`, `local_date`,
`temperature_unit`, and `row_count`. It selects the latest physical CSV revision
for a duplicate date unless an explicit revision number is present. The output
contains every cohort key and classifies it as `present_admissible`,
`present_below_threshold`, or `missing`; it contains no settlement temperature.
The pre- and post-2026-07-31 sides remain separate.

The production entry point reads exactly the 12 configured settlement ledgers
and 12 configured WU daily summaries. It strictly verifies ledger history,
selects the deterministic latest revision for each of the exact 96 requested
`(market_id, target_date)` keys, reconciles the native-unit ledger bucket with
the WU daily row, and fails if any requested row is absent, inconsistent, or has
fewer than 18 observations. Sources are opened without writer locks and are
bound by portable repository-relative path, bytes, SHA-256, and stable file
identity before and after selection and immediately before publication.

The command requires an absolute repository root, the exact tracked frozen
spec, and a new absolute destination whose parent already exists:

```text
python -m weather.operations.wu_outcome_export_contract export-production --repo-root <absolute-repository-root> --spec <absolute-path-to-tracked-spec> --destination <absolute-new-export-directory>
```

This is a placeholder-only template. Encode the argument vector and execute it
through `scripts/ops/workstation_heavy.ps1` on the assigned workstation. Never
substitute live paths into documentation or a handback report.

The exporter refuses an existing or case-colliding destination, the repository
root, any destination below repository `data/`, reparse or escaping source and
destination paths, and a publication it cannot prove is same-volume and
create-only. It builds the exact two files in a unique sibling staging
directory, validates them, rechecks every source, and atomically renames the
directory. A failed prepublication attempt leaves the final destination absent.

The validator accepts only a new, non-reparse directory containing
`manifest.json` and `wu-outcomes.jsonl`. It enforces exact request coverage,
native units, configured WU history identities, stations and timezones,
boundary sides, per-file identities, canonical encodings, manifest self-hash,
unchanged source hashes, byte/file bounds, all-false downstream authority, and
the actual destination owner/SDDL proof. It returns counts and hashes without
returning settlement values.

Run all builder, validator, and test invocations on the assigned workstation
through `scripts/ops/workstation_heavy.ps1`; the CLI owner is in that wrapper's
offline allowlist. The builder, exporter, and validator do not contact a
provider, inspect market prices, alter ledgers or corpora, fit models, create
probabilities, or authorize model refit, scoring, promotion, serving, or live
use. The artifact is research input only.
