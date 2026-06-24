# 287. Per-Market-Day Event Manifest For Evidence, Projections, And Rebuild Sources [COMPLETE 2026-06-23 - EVENT-DAY MANIFEST WRITER AND VALIDATOR LIVE]

Goal: add an `event_day_manifest.json` to each market-day snapshot folder so
the folder is self-describing: file role, schema version, row count, byte count,
hash, storage class, retention class, rebuild source, and backup/restore state.

Source: the 2026-06-23 data-layer audit found that a single market-day folder
contains many useful files with different roles: raw JSONL tapes, CSV analysis
sidecars, replay inputs, forecast-payload indexes, derived CLOB features, raw
CLOB books, price history, websocket messages, and status rows. The current
archive manifest describes closed-day Parquet partitions, but the live
`data/snapshots/<event_slug>/` folder itself has no one manifest that declares
which files are canonical evidence versus rebuildable projections. Existing
readers infer meaning from filenames and path layout.

Why this matters: folder-level self-description is the missing layer between
"keep everything" and "avoid duplicate bloat." A manifest lets operators and
tools safely answer: what is irreplaceable, what can be rebuilt, whether a CSV
matches its raw JSONL, which schema version wrote it, whether a file is covered
by backup, and whether a cleanup or Parquet conversion can proceed. It also
removes future dependence on fragile filename-only ownership and makes
long-term archive migrations verifiable.

## Design

1. Define `event_day_manifest_v0.1` with folder identity fields
   (`event_slug`, `market_id`, `local_date`, target date, generated time,
   writer version) and one `artifact_families` entry per emitted family.
2. For every file entry, record relative path, role
   (`canonical_evidence`, `analysis_projection`, `operator_cache`), schema
   version when known, row count when applicable, bytes, SHA-256, storage class,
   retention class, rebuild source, and whether it is expected to be backed up.
3. Generate or refresh the manifest at the end of snapshot/CLOB capture cycles
   and with an offline repair command for historical folders. The manifest
   must not block live capture if one optional family fails, but it must record
   the missing/error state explicitly.
4. Integrate the manifest with closed-day Parquet conversion so the archive
   manifest can reference the event-day manifest and avoid rescanning every raw
   file to rediscover source metadata.
5. Add validation that compares manifest counts/hashes to current files and
   reports stale, missing, extra, or role-conflicting artifacts before any
   cleanup manifest can delete local data.

- [x] Register `event_day_manifest_v0.1` in the schema registry.
- [x] Add a manifest writer/validator for existing snapshot, CLOB, replay,
  settlement, and market-making artifact families.
- [x] Backfill manifests for historical market-day folders without rewriting
  the underlying tapes.
- [x] Teach data-retention and closed-day archive planning to consume the
  manifest when present.
- [x] Add tests for hash/row-count validation, missing family handling,
  projection-to-evidence rebuild references, and stale-manifest detection.

Acceptance: each active or historical market-day folder can produce a valid
`event_day_manifest.json` that lists all durable file families with role,
schema, count, hash, retention class, and rebuild source; cleanup/archive
planning consumes the manifest when present; and validation fails closed when a
manifest is stale or when a deletion candidate lacks canonical evidence and
backup proof.

Implementation (2026-06-23): `weather.operations.event_day_manifest` now owns
`event_day_manifest_v0.1`, a writer, validator, manifest hash helper,
historical plan/apply backfill command, manifest summary helper, and a
fail-closed deletion-candidate gate. File entries include folder-relative path,
data-relative path, role/storage class, schema version when present, row count,
bytes, SHA-256, retention class, rebuild source, backup expectation, and
backup/restore state.

The manifest covers snapshot, feature, component, forecast, forecast-payload,
source-status, replay, CLOB token/book/price/websocket/feature, variant,
settlement, market-making, and taker artifact families. Missing optional
families are recorded explicitly. `weather.reporting.data_retention_inventory`
summarizes existing event-day manifests, and
`weather.operations.closed_market_day_archive` validates a present
`event_day_manifest.json`, blocks stale manifests, and stores the event-day
manifest hash in the closed-day archive manifest.

Verification (2026-06-23):

- `python -m pytest tests/operations/test_event_day_manifest.py -q` -> 6
  passed.
- `python -m pytest tests/operations/test_storage_classes.py -q` -> 3 passed,
  16 subtests passed.
- `python -m pytest tests/operations/test_schema_registry.py -q` -> 3 passed.
- Earlier focused integration run:
  `python -m pytest tests/operations/test_closed_market_day_archive.py -q` ->
  14 passed; `python -m pytest tests/reporting/test_data_retention_inventory.py
  -q` -> 3 passed.

Related: items 60, 65, 124, 171, 243, 244, 245, 286.
