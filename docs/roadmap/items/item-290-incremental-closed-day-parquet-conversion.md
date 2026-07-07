# 290. Incremental Closed-Day Parquet Conversion And Reader Migration Closure [COMPLETE 2026-06-23 - BOUNDED CURSOR CONVERTER AND READER STATUS LIVE]

Goal: make closed-day Parquet conversion incremental, resumable, and routine so
heavy historical analysis reads compact validated Parquet instead of repeatedly
scanning large CSV/JSONL snapshot tapes.

Source: Items 243-245 created the closed market-day Parquet contract, guarded
backfill harness, and reader boundary. The 2026-06-23 audit found the design is
sound but local archive coverage is still tiny relative to raw snapshots:
`data/archive` is only a few hundred KB while `data/snapshots` is about 92 GB.
A full-tree archive planning attempt also timed out during audit, showing that
planning/conversion must be incremental and cheap rather than a single
expensive scan.

Why this matters: Parquet is the right analysis projection for long-term growth
because it is compact, partitioned, and queryable by date/market/family. But it
only reduces bloat and scan cost when conversion coverage grows and high-byte
readers actually use it. A slow full-tree planner will get skipped when disk
pressure is high; a resumable daily converter can keep up as market-days close.

## Design

1. Add an incremental planner that inspects only newly closed or changed
   market-day folders, using event-day manifests when available and falling
   back to source-file signatures.
2. Convert eligible closed folders family-by-family, writing validated Parquet
   partitions with manifest hashes, row counts, source hashes, codec, schema
   fingerprints, finalization state, and raw-evidence references.
3. Store conversion cursor/status artifacts so daily refresh can resume after
   interruption and can report backlog by market, date, artifact family, bytes,
   and blocker reason.
4. Migrate the remaining high-byte historical readers after source-family
   inventory: snapshot evaluation, replay input loading, market/CLOB analysis,
   promotion-corpus scans, and model/taker/maker evidence reports.
5. Add operator reports that compare text/gzip/parquet source modes and quantify
   bytes/scan-time avoided, without allowing Parquet to replace raw forensic

- [x] Add an incremental closed-day Parquet planner with a bounded scan window
  and resumable cursor/status.
- [x] Convert all eligible closed market-days currently present under
  `data/snapshots` into validated Parquet partitions or explicit blockers.
- [x] Migrate remaining high-byte reports/readers to `read_market_day_artifact`
  with provenance summaries.
- [x] Add parity tests comparing text/gzip/parquet reads for representative
  snapshot, CLOB, replay, and price-history families.
- [x] Add daily refresh/fleet observability status for Parquet backlog,
  conversion errors, and reader source-mode mix.

## Completion Notes

- Added `closed_market_day_parquet_incremental_v0.1` with
  `incremental-plan` / `incremental-apply` CLI modes, bounded scan windows,
  event-day-manifest/source-stat signatures, cursor persistence, and retry of
  failed or changed folders.
- Daily refresh now runs `closed_day_parquet_incremental` after replay-status
  backfill and before historical report scans. Outputs are written to
  `closed_market_day_parquet_incremental.{json,md}` plus a cursor under the
  backtest root.
- Fleet observability reads the incremental status artifact and reports
  conversion failures, blockers, bytes, and remaining scan backlog.
- `snapshot_evaluation` now reads snapshot and replay-input history through
  `read_market_day_artifact` and reports historical reader source modes.
  Source-family inventory was already on the shared reader boundary.
- Parity tests cover representative snapshot, order-book/CLOB,
  price-history, clob-token, replay-input, gzip fallback, and validated
  parquet reads.

Verification:

- `python -m pytest tests/operations/test_closed_market_day_archive.py tests/operations/test_schema_registry.py tests/operations/test_daily_refresh.py -q`
- `python -m pytest tests/reporting/test_snapshot_evaluation.py tests/reporting/test_fleet_observability.py -q`

Acceptance: daily or operator conversion can process closed market-days
incrementally without full-tree timeouts; eligible closed folders have validated
Parquet partitions or explicit blocker rows; high-byte historical readers prefer
Parquet with text fallback and source-mode provenance; and parity tests prove
Parquet results match legacy text/gzip readers for covered families.

Related: items 124, 154, 171, 203, 243, 244, 245, 286, 287, 289.
