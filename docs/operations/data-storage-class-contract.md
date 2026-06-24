# Data Storage Class Contract

Every durable data or log artifact should be classified as exactly one storage
class before a writer adds a new file family under `data/`.

## Storage Classes

| Storage class | Purpose | Examples | Retention and deletion gate |
| :--- | :--- | :--- | :--- |
| `canonical_evidence` | Append-only or source-of-truth evidence that cannot be safely rebuilt later. | Snapshot JSONL, replay inputs, settlement ledgers, market-making lifecycle and risk ledgers, taker run ledgers, raw CLOB books, websocket messages, price-history source evidence, CLOB token maps. | Permanent archive. Local deletion requires a reviewed cleanup manifest, current backup manifest, fresh restore drill, and checksum proof. |
| `analysis_projection` | Tables or partitions derived from canonical evidence for faster reads and reports. | Snapshot CSV long tables, CLOB summary/long CSVs, price-history CSVs, closed-day Parquet partitions, large backtest row exports, model artifacts with rebuild manifests. | Rebuildable, but not disposable by size alone. Deletion requires a reviewed cleanup manifest, named rebuild source, and current restore proof for the source evidence. |
| `operator_cache` | Reports, dashboards, status files, provider/runtime caches, console logs, and local workflow outputs. | `data/backtest/*_report.md`, `fleet_observability.json`, `data/logs/*.log`, provider cache folders, same-disk tape-backup control copies. | TTL or cleanup-manifest driven. Incident-linked logs or reports must be named in an incident or cleanup manifest before deletion. |

## Code Registry

The code-backed registry lives in
`weather.operations.storage_classes`. It records:

- artifact family name and owning subsystem
- storage class
- path patterns
- retention class
- rebuild source
- delete gate
- whether the artifact family requires backup by class

`weather.reporting.data_quality.data_retention_inventory` uses the registry to summarize
bytes and recent growth by storage class. `weather.operations.tape_backup`
uses the same registry to annotate backup manifests and status reports with
storage class, artifact family, rebuild source, and delete gate metadata.

## Operator Rule

Cleanup is allowed only from a reviewed cleanup manifest. Do not delete from
raw directory size, age, or duplicated-looking filenames alone.

For `canonical_evidence`, the cleanup manifest must name exact files and must
be paired with current backup and restore-drill proof. For
`analysis_projection`, the manifest must name the canonical rebuild source and
that source must have current restore proof. For `operator_cache`, TTL cleanup
is acceptable only when no incident, replay, promotion, or cleanup manifest
references the file.
