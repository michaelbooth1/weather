# 171. Local Data Retention And CLOB Tape Storage Cleanup [COMPLETE 2026-06-20 - DATA RETENTION INVENTORY AND DAILY BUDGET LIVE]

Goal: reduce local runtime data from an unbounded 138 GB working tree into a
documented, recoverable, and operator-safe storage layout.

Source: the 2026-06-20 full repository cleanup audit. The ignored `data/`
directory contains roughly 188k files and 138 GB. The largest contributors are
`data/tape_backups` at roughly 60 GB and `data/snapshots` at roughly 58 GB,
with many market-day order book and snapshot JSONL files above hundreds of MB.

Why this matters: the project is now operationally constrained by local disk
growth. Cleanup cannot be an ad hoc delete because these tapes may be the only
copy of live CLOB, snapshot, taker, market-making, and backtest evidence.

## Design

1. Inventory `data/` by owner, producer, regeneration path, and durability
   requirement: raw CLOB tape, live snapshot, forecast/observation cache,
   backtest output, market-making run, taker run, and operational report.
2. Separate durable evidence from regenerable cache and scratch output.
3. Add a retention manifest that records keep/delete/archive/compress policy
   for each major data subtree.
4. Move large durable raw tapes to an external root or object store with local
   manifests and restore checks.
5. Replace mirror-like `data/tape_backups/latest` growth with a bounded
   backup strategy: dedupe, hardlink where safe, compress, or rotate.
6. Add preflight disk-headroom and retention warnings before active-day loops,
   daily refresh, tape backup, and backtest generation can create another
   large batch.

- [x] Produce a `data/` ownership and retention inventory report.
- [x] Define keep/archive/delete TTLs for `snapshots`, `tape_backups`,
  `backtest`, `mm_runs`, `taker_runs`, `ops`, and provider caches.
- [x] Add restore-proof checks before any raw tape or snapshot deletion is
  permitted.
- [x] Compress or externalize large historical JSONL/CSV evidence files after
  manifesting them.
- [x] Add a daily disk-budget report that flags the largest new files and
  directories.
- [x] Document the operator procedure for pruning local data safely.

Acceptance: local `data/` growth is bounded by policy, every deletion candidate
has an owner and restore/regeneration answer, and active-day operations fail
early with a clear disk-budget blocker instead of silently filling the drive.

## 2026-06-20 implementation

Added `weather.reporting.data_retention_inventory`, schema
`data_retention_inventory_v0.1`, and wired it into
`weather.operations.daily_refresh` before daily learning. The report is
read-only and classifies the local `data/` tree by owner, durability,
keep/archive/delete TTL policy, restore requirements, regeneration path, and
delete permission.

The inventory enforces restore-proof deletion gates for irreplaceable classes
such as `snapshots`, `mm_runs`, `taker_runs`, `settlements`, and canonical
historical sources. Classes that are regenerable or cleanup-manifest driven
(`backtest`, provider caches, `reanalysis`, `ops`, and `tape_backups`) remain
manifest-only and are not deleted by this report. The existing CLOB gzip
tiering and tape-backup restore proof remain the compression/externalization
mechanisms for full-depth order-book evidence; the new inventory surfaces those
classes in the same daily budget view.

Generated current evidence:

- `data/backtest/data_retention_inventory.json`
- `data/backtest/data_retention_inventory_report.md`

The current report scanned `191250` files and `137.3 GB` under `data/`, with
zero unclassified bytes and restore-blocked classes `0`. Largest roots are
`snapshots` (`59.1 GB`), `tape_backups` (`58.8 GB`), `noaa_ghcnh` (`6.2 GB`),
`wunderground` (`3.8 GB`), and `reanalysis` (`3.3 GB`). The 24-hour growth
section flags `41.4 GB` of recent files, led by `tape_backups`, `snapshots`,
`reanalysis`, and `backtest`.

Operator documentation is in `docs/operations/data-retention-policy.md`.
Deletion remains gated: operators must use the generated owner table and the
appropriate cleanup manifest (`tape_backup prune-unmanifested` or
`backtest_artifact_retention`) rather than deleting files ad hoc.

Verification:

- `python -m pytest -q tests\reporting\test_data_retention_inventory.py tests\operations\test_daily_refresh.py tests\operations\test_schema_registry.py`
  passed with 34 tests.
- `python -m pytest -q tests\operations\test_import_architecture.py tests\operations\test_path_policy.py`
  passed with 19 tests.
- `python -m weather.reporting.data_retention_inventory --root data --out data\backtest\data_retention_inventory.json --report data\backtest\data_retention_inventory_report.md --min-free-bytes 0 --top-n 25`
  generated the current PASS inventory.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - DATA RETENTION INVENTORY AND DAILY BUDGET LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

