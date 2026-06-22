# 243. Closed Market-Day Parquet Archive Contract [OPEN 2026-06-22 - COLUMNAR ARCHIVE CONTRACT MISSING]

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

- [ ] Define the Parquet archive root, partition keys, and naming convention.
- [ ] Register a schema version for closed-market-day archive manifests.
- [ ] Specify artifact-family mappings from current CSV/JSONL files to Parquet
  datasets and raw-evidence references.
- [ ] Add validation requirements for row counts, source hashes, schemas, and
  closed-day eligibility.
- [ ] Document reader fallback rules so live snapshot compatibility is not
  broken.
- [ ] Add roadmap/runbook guidance for which files remain raw forensic evidence
  versus Parquet analysis tables.

Acceptance: a versioned closed-market-day Parquet archive contract exists; it
states exactly when a market-day is eligible, where each artifact family is
written, how source evidence is hashed and referenced, and how readers must
fall back to the current text layout when an archive partition is absent or
invalid.

Related: items 124, 146, 154, 203, 239, 244, 245.
