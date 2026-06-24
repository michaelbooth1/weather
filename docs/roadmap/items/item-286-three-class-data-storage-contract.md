# 286. Three-Class Data Storage Contract And Retention Classification [COMPLETE 2026-06-23 - STORAGE CLASS REGISTRY AND REPORTING LIVE]

Goal: make every persisted data/log artifact fall into one explicit storage
class: canonical evidence, analysis projection, or operator/cache export, with
retention, backup, and cleanup behavior derived from that class instead of from
ad hoc filename patterns.

Source: the 2026-06-23 data-layer and log-storage audit found that the project
already stores useful raw evidence and analysis tables, but the classification
is implicit. `data/snapshots` writes JSONL evidence, CSV sidecars, replay
inputs, forecast payload indexes, CLOB raw tapes, price-history tables, and
console/status logs side by side. The retention tooling classifies many files
by glob in `weather.operations.tape_backup`, while the closed-day Parquet
contract treats Parquet as an analysis copy rather than raw evidence. That is
the right direction, but the storage roles are not yet first-class across all
writers and reports.

Why this matters: "store all possibly useful information" and "avoid bloat or
duplicate data" are not conflicting goals if the project separates canonical
evidence from projections and operator cache. Raw append-only evidence should
be backed up permanently; Parquet and CSV analysis tables should be rebuildable
from evidence; console logs and dashboards should be TTL- or cleanup-manifest
driven. Without a shared contract, future collectors will keep adding useful
fields in whatever file is closest, making cleanup unsafe and analysis slower
as the fleet grows.

## Design

1. Define the three storage classes in code and docs:
   `canonical_evidence`, `analysis_projection`, and `operator_cache`, including
   allowed formats, retention defaults, backup requirements, and deletion
   prerequisites.
2. Map existing artifact families to those classes, including snapshot JSONL,
   replay inputs, settlement ledgers, market-making lifecycle/risk ledgers,
   CLOB tokens/books/ws/price raw evidence, CSV long tables, Parquet archive
   partitions, generated reports, status JSON, and console logs.
3. Add a shared storage-class registry or manifest helper that writers can use
   when emitting new artifact families instead of adding new tape-backup glob
   rules directly.
4. Teach the data-retention inventory and tape-backup status to report storage
   class, rebuild source, and delete gate by class, while keeping legacy glob
   classification as a compatibility fallback.
5. Document the operator rule: cleanup is allowed only from a reviewed cleanup
   manifest, never from raw directory size alone; projections may be deleted
   only when their rebuild source and restore proof are current.

- [x] Add a code-backed storage-class registry covering the current artifact
  families and their retention/delete gates.
- [x] Update the data-retention inventory to summarize bytes and new growth by
  storage class, not only by top-level directory.
- [x] Update tape-backup policy reporting to distinguish canonical evidence,
  rebuildable projections, and operator/cache exports.
- [x] Document the class contract in operations docs with examples from
  snapshots, CLOB tapes, market-making runs, and reports.
- [x] Add tests that fail when a new durable artifact family is emitted without
  a storage-class classification.

Acceptance: every durable file family under `data/` that is written by project
code has a documented and code-visible storage class; retention reports show
bytes and growth by class; cleanup gates derive from the class contract; and
adding a new persisted artifact without class metadata fails a focused
operations/reporting test.

Implementation (2026-06-23): `weather.operations.storage_classes` now defines
the three storage classes, operator contracts, artifact-family registry,
classification helper, and delete-gate helper. The registry covers snapshot
JSONL, replay inputs, settlement ledgers, market-making and taker run evidence,
CLOB raw evidence and token maps, CSV/Parquet projections, generated reports,
status JSON, provider/runtime caches, backup mirrors, console logs, model
artifacts, and historical source rows.

`weather.reporting.data_retention_inventory` now annotates each file with
storage class, artifact family, retention class, rebuild source, delete gate,
and backup requirement, then renders a storage-class summary with bytes and
recent growth. `weather.operations.tape_backup` now embeds the same metadata in
backup manifests, exposes storage-class summaries in backup status, and renders
those summaries in the tape-backup status report while preserving the legacy
backup-class glob rules.

Operator documentation lives in
`docs/operations/data-storage-class-contract.md` and is linked from
`docs/operations/data-retention-policy.md`. Focused coverage:
`tests/operations/test_storage_classes.py`,
`tests/reporting/test_data_retention_inventory.py`, and
`tests/operations/test_tape_backup.py`.

Verification (2026-06-23):

- `python -m pytest tests/operations/test_storage_classes.py -q` -> 3 passed,
  16 subtests passed.
- `python -m pytest tests/reporting/test_data_retention_inventory.py -q` -> 3
  passed.
- `python -m pytest tests/operations/test_tape_backup.py -q` -> 15 passed, 10
  subtests passed.

Related: items 65, 124, 146, 154, 171, 243, 244, 245, 246, 247.
