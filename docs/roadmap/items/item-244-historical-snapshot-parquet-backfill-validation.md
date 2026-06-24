# 244. Historical Snapshot Parquet Backfill And Validation Harness [COMPLETE 2026-06-22 - GUARDED PARQUET BACKFILL LIVE]

Goal: build the guarded conversion pipeline that backfills closed
`data/snapshots` market-days into the Parquet archive without deleting source
tapes or weakening replay/audit evidence.

Source: Item 243 defines the missing archive contract. The 2026-06-22 storage
audit found the main historical growth in heavy text snapshot artifacts:
`order_books.jsonl`, `price_history.csv`, `clob_tokens.jsonl`,
`replay_inputs.jsonl`, `order_books_long.csv`, and related long tables. Several
of these are already closed market-days and can be converted once finalization,
row-count, and checksum checks are explicit.

Why this matters: a Parquet contract is only useful if there is a repeatable
backfill command that proves the archive is complete and correct. The pipeline
must be incremental, idempotent, and conservative: first create validated
analysis copies, then let later items decide what can be compacted, moved, or
reclaimed.

## Design

1. Add a dry-run planner that scans `data/snapshots`, filters to closed or
   settled market-days, and reports convertible artifact families, estimated
   output bytes, source bytes, and blockers.
2. Add a conversion command that writes Parquet to a temp path, verifies row
   counts and schema expectations, writes a manifest, then atomically publishes
   the partition.
3. Convert large CSV tables with pyarrow-backed Parquet compression; keep codec
   selection configurable but default to the repo's best available compact
   codec.
4. Convert JSONL families only when the transformation is schema-safe and
   auditable; otherwise retain the raw JSONL in the forensic backup and record
   it as a raw-only source in the archive manifest.
5. Make the command resumable by skipping partitions whose manifest still
   matches source hashes and by rewriting only stale or invalid partitions.
6. Write a backfill report under `data/backtest` that lists converted,
   skipped, blocked, and failed market-days, with no source deletion in this
   item.

- [x] Add a closed-day Parquet backfill dry-run planner.
- [x] Add an apply mode that writes validated Parquet partitions and manifests.
- [x] Cover `order_books_long.csv`, `price_history.csv`, `clob_tokens.csv`,
  `snapshots_long.csv`, and replay inputs where schemas are stable.
- [x] Add tests for idempotent reruns, stale-manifest rewrite, source-hash
  mismatch handling, and invalid/active-day exclusion.
- [x] Produce a representative backfill report for existing closed
  market-days.
- [x] Confirm the command never deletes or rewrites source snapshot tapes.

Acceptance: closed market-days can be converted into validated Parquet
partitions through a dry-run/apply workflow; every partition has a manifest
with source hashes and row-count checks; reruns are idempotent; active days are
excluded; and original CSV/JSONL source tapes remain untouched.

Related: items 124, 146, 154, 203, 239, 243, 245.

## 2026-06-22 completion

`weather.operations.closed_market_day_archive` now owns the guarded backfill
harness for the item 243 archive contract. The CLI supports `plan` and `apply`
modes, filters out active/future days and writer-locked folders, writes Parquet
through a temporary partition, validates row counts and schema fingerprints,
attaches source SHA-256 hashes, writes a v0.1 manifest, and skips reruns when
the existing manifest still matches the source files.

Evidence:

- Backfill schema: `closed_market_day_parquet_backfill_v0.1`.
- Representative apply:
  `python -m weather.operations.closed_market_day_archive apply --event-slug
  highest-temperature-in-atlanta-on-june-10-2026 --as-of-date 2026-06-23`.
- Report: `data/backtest/closed_market_day_parquet_backfill_report.md`
  (`PASS`, `converted=1`, `converted_family_count=8`,
  `source_deleted_count=0`).
- Manifest validation for the representative partition passed shape checks,
  manifest-hash verification, and `parquet_reader_allowed`.
- Idempotent rerun report:
  `data/backtest/closed_market_day_parquet_backfill_idempotent_report.md`
  (`PASS`, `skipped=1`, `source_deleted_count=0`).
- Tests: `python -m pytest tests/operations/test_closed_market_day_archive.py
  tests/operations/test_schema_registry.py -q`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - GUARDED PARQUET BACKFILL LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

