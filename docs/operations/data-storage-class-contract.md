# Data Storage Class Contract

Every durable data or log artifact should be classified as exactly one storage
class before a writer adds a new file family under `data/`.

## Storage Classes

| Storage class | Purpose | Examples | Retention and deletion gate |
| :--- | :--- | :--- | :--- |
| `canonical_evidence` | Append-only or source-of-truth evidence that cannot be safely rebuilt later. | Snapshot JSONL, replay inputs, shared raw forecast payloads, settlement ledgers, market-making lifecycle and risk ledgers, taker run ledgers, raw CLOB books, websocket messages, price-history source evidence, CLOB token maps. | Permanent archive unless a family-specific reviewed bounded-retention policy applies. Local deletion requires exact paths, reason, operator authorization, and checksums. |
| `analysis_projection` | Tables, partitions, or indexes derived from canonical evidence for faster reads and reports. | Snapshot CSV long tables, CLOB summary/long CSVs, price-history CSVs, closed-day Parquet partitions, taker incremental SQLite checkpoints, large backtest row exports, model artifacts with rebuild manifests. | Rebuildable, but not disposable by size alone. Deletion requires a reviewed cleanup manifest and named rebuild source. `order_books_long` is rebuilt exactly from `order_books.jsonl`; gzip is its retained serving projection. |
| `operator_cache` | Reports, dashboards, status files, provider/runtime caches, console logs, and local workflow outputs. | `data/backtest/*_report.md`, `fleet_observability.json`, replay-cache entries, `data/logs/*.log`, provider cache folders, bounded observation-trigger source caches. | TTL or cleanup-manifest driven. Replay-cache cleanup is stricter: exact full-key reachability only, with ambiguity retained; never age or LRU. Incident-linked logs or reports must be named in an incident or cleanup manifest before deletion. |

## Code Registry

The code-backed registry lives in
`weather.operations.storage_classes`. It records:

- artifact family name and owning subsystem
- storage class
- path patterns
- retention class
- rebuild source
- delete gate
- whether the artifact family is protected by class

`weather.reporting.data_quality.data_retention_inventory` uses the registry to summarize
bytes and recent growth by storage class.

## Operator Rule

Cleanup is allowed only from a reviewed cleanup manifest. Do not delete from
raw directory size, age, or duplicated-looking filenames alone.

For `canonical_evidence`, the cleanup manifest must name exact files, reason,
operator review, and checksums. For `analysis_projection`, the manifest must
name the canonical rebuild source. For `operator_cache`, TTL cleanup is
acceptable only when no incident, replay, promotion, or cleanup manifest
references the file.

Taker counterfactual replay detail is the sole current bounded-retention
canonical family. `counterfactual_orders_long.csv` and its settled detail copy
default to 14 days. Daily roll requires both the run target date and file mtime
to cross the cutoff, writes a self-hashed exact-path/SHA-256/byte plan before
apply, rechecks identity immediately before deletion, and writes an apply
receipt. The rule does not depend on `settled_counterfactual_pnl.json`; real
orders and compact run, P&L, strategy, and settlement summaries are excluded.

Shared forecast blobs under `data/forecast_payload_cas/` are reachable from
many event folders. Reachability must be computed across every per-market
forecast manifest; one event-day manifest cannot classify a shared blob as an
orphan. Garbage collection is disabled in every current cleanup and inventory
workflow; generic operator review cannot override that block. A future,
separately reviewed deletion contract would have to prove global reachability,
restore hashes, and market-specific replay before enabling any mutation.
