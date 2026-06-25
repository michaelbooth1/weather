# 243. Closed Market-Day Parquet Archive Contract [COMPLETE 2026-06-22 - VERSIONED ARCHIVE CONTRACT REGISTERED]

Goal: define the canonical Parquet archive contract for closed market-days while
leaving live `data/snapshots` text tapes unchanged for current collectors and
serving code.

Source: the 2026-06-22 local storage audit found the workspace at about 191.8
GB, with `data/snapshots` at about 81.4 GB and the largest historical snapshot
artifacts stored as CSV/JSONL text. Compression samples showed the long CSV
tables are highly redundant and well suited to Parquet/Zstd, but the repo has
no partition, schema, or manifest contract for using Parquet as the historical
analysis surface.

Why this matters: retaining every useful observation is the right default, but
keeping settled historical market-days only as mutable row-oriented text makes
analysis slow, backup growth expensive, and storage pressure look like a data
retention problem instead of a layout problem. A written contract lets later
conversion, readers, and cleanup preserve forensic evidence while making the
normal historical path compact and queryable.

## Design

1. Keep active and unsettled market-days in the existing
   `data/snapshots/<event_slug>/` CSV/JSONL layout until finalization.
2. Define a versioned archive root, partition layout, and manifest schema for
   closed market-days, for example by local date, market id, event slug, and
   artifact family.
3. Treat Parquet as the default historical analysis representation for heavy
   normalized tables: `order_books_long.csv`, `price_history.csv`,
   `clob_tokens.csv`, `snapshots_long.csv`, replay inputs, variant predictions,
   source status, and other high-row-count long tables.
4. Keep raw JSONL/order-book payloads as forensic evidence and source material;
   the Parquet archive must reference their source hashes rather than pretending
   derived Parquet replaces raw capture evidence.
5. Record row counts, column schemas, source file sizes, source SHA-256 hashes,
   conversion timestamp, writer version, compression codec, and source
   finalization state in a per-market-day manifest.
6. Specify the compatibility rule: readers must prefer Parquet only for closed
   market-days whose manifest validates, and must fall back to the current text
   tapes for live, active, missing, or invalid archive partitions.

- [x] Define the Parquet archive root, partition keys, and naming convention.
- [x] Register a schema version for closed-market-day archive manifests.
- [x] Specify artifact-family mappings from current CSV/JSONL files to Parquet
  datasets and raw-evidence references.
- [x] Add validation requirements for row counts, source hashes, schemas, and
  closed-day eligibility.
- [x] Document reader fallback rules so live snapshot compatibility is not
  broken.
- [x] Add roadmap/runbook guidance for which files remain raw forensic evidence
  versus Parquet analysis tables.

Acceptance: a versioned closed-market-day Parquet archive contract exists; it
states exactly when a market-day is eligible, where each artifact family is
written, how source evidence is hashed and referenced, and how readers must
fall back to the current text layout when an archive partition is absent or
invalid.

Related: items 124, 146, 154, 203, 239, 244, 245.

## 2026-06-22 contract implementation

The closed market-day Parquet archive contract is now explicit and
code-backed:

- `docs/operations/closed-market-day-parquet-archive-contract.md` defines the
  v0.1 archive root, Hive-style partition keys, eligibility states, manifest
  requirements, artifact-family mappings, validation rules, reader fallback
  order, and raw forensic evidence boundaries.
- `weather.operations.closed_market_day_archive` owns the contract constants
  for `data/archive/closed_market_days/v0.1`, per-family `data.parquet`
  paths, manifest path construction, artifact-family mapping, manifest shape
  validation, and Parquet-reader eligibility.
- `closed_market_day_archive_manifest_v0.1` is registered in
  `weather.schema_registry` as `closed_market_day_archive_manifest`.
- `docs/operations/data-retention-policy.md` and
  `docs/operations/TAPE_BACKUP_RUNBOOK.md` now point operators at the contract
  and preserve the rule that Parquet is an analysis copy, not a replacement for
  raw JSONL/order-book/settlement evidence.

Verification:

- `python -m pytest tests\operations\test_closed_market_day_archive.py tests\operations\test_schema_registry.py tests\reporting\test_roadmap_backlog.py -q`
  passed with `17 passed`.
- `python -m compileall src\weather\operations\closed_market_day_archive.py`
  passed.
- `python -m pytest tests\operations\test_closed_market_day_archive.py tests\operations\test_schema_registry.py -q`
  passed with `9 passed`.
- `python -m pytest tests\operations\test_closed_market_day_archive.py -q`
  passed with `6 passed`.
- `python -m weather.schema_registry audit --paths src\weather\operations\closed_market_day_archive.py --strict`
  passed with `unregistered_versions=0`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - VERSIONED ARCHIVE CONTRACT REGISTERED`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

