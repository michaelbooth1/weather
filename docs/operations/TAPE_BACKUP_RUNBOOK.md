# Irreplaceable Tape Backup And Restore Runbook

This runbook covers evidence that cannot be reconstructed after a workstation
loss: snapshot tapes, replay inputs, CLOB captures, observation-trigger events,
settlement labels, promotion corpora, market-making run folders, order
lifecycle ledgers, and risk events.

## Backup Root

Use an external disk, NAS, or cloud-synced cold-storage folder. Configure it
with `WEATHER_TAPE_BACKUP_ROOT` or pass `--backup-root` explicitly.

Recommended layout:

```powershell
$env:WEATHER_TAPE_BACKUP_ROOT = "E:\weather-tape-backups"
python -m weather.operations.tape_backup run --backup-root $env:WEATHER_TAPE_BACKUP_ROOT --verify-checksums
python -m weather.operations.tape_backup status --backup-root $env:WEATHER_TAPE_BACKUP_ROOT --verify-checksums
```

The backup manifest is written to `latest/tape_backup_manifest.json` and to a
timestamped copy under `manifests/`. Each manifest records tape classes,
recoverability, retention rules, SHA-256 checksums, file counts, total bytes,
and a manifest hash.

On Windows, register the daily scheduled job from the repository root:

```powershell
.\scripts\ops\register_tape_backup.ps1 -BackupRoot $env:WEATHER_TAPE_BACKUP_ROOT
```

The scheduled task runs `weather.operations.tape_backup run`, which performs
the export, restore drill, checksum verification, and status/report writes in
one fail-closed step.

## Retention Rules

- `snapshot_tapes`: retain permanently. Includes snapshot, feature, component,
  source-status, forecast-payload, and replay-input tapes.
- `clob_tapes`: retain permanently. Includes CLOB tokens, book/feature tapes,
  diagnostics, and loop status.
- `observation_trigger_tapes`: retain permanently. Includes trigger events,
  diagnostics, status, and console traces.
- `settlement_ledgers`: retain permanently. Includes settlement ledgers,
  market-day labels, and resolution provenance.
- `promotion_corpora`: retain permanently. Includes pinned promotion corpora,
  location trust, promotion decisions, and gauntlet JSON outputs.
- `market_making_runs`: retain permanently. Includes run folders, quote tapes,
  fills, budgets, and run summaries.
- `order_lifecycle_and_risk`: retain permanently. Includes order lifecycle,
  risk, budget, and remediation-event records.
- `model_artifacts_and_manifests`: retain through the corresponding promotion
  and live-forward window.
- `source_manifests` and `operational_status`: retain with the backed-up data
  to prove provenance and last known operational state.

Markdown reports, lock files, PID files, temp files, and clearly rebuildable
scratch outputs are excluded.

Zero-byte files are also excluded from backup manifests. They cannot prove
recoverable evidence and should be repaired or regenerated at the producer
instead of copied as valid tape. Promotion-refresh lifecycle manifests using
`promotion_refresh_incomplete_v0.1` are retained and schema-checked; the
`status` field distinguishes `STARTED`, `COMPLETE`, and `INCOMPLETE` runs.

### CLOB Artifact Classes

The backup status command audits CLOB artifacts by emitted filename, not only by
`clob*` prefixes. These classes are treated as required backup evidence:

- `tokens`: `clob_tokens.csv` and `clob_tokens.jsonl`; join keys for market
  outcomes, books, features, and replay.
- `order_book_summary`: `order_books_summary.csv`; per-token bid/ask, spread,
  depth, and executable-size summaries.
- `order_book_long`: `order_books_long.csv` or `order_books_long.csv.gz`;
  full depth long-table book evidence and the highest local storage-growth
  risk.
- `order_book_raw`: `order_books.jsonl`; raw order-book payload and response
  metadata.
- `price_history`: `price_history.csv` and `price_history.jsonl`; CLOB price
  history used for microstructure features and replay.
- `market_ws`: `market_ws_events.csv` and `market_ws.jsonl`; websocket event
  summaries and raw messages.

`clob_features_long.csv` and `clob_features.jsonl` are classified separately as
derived CLOB features. They are useful to retain for audit speed, but they are
rebuildable from the raw order-book, price-history, websocket, token, and
snapshot tapes.

`python -m weather.operations.tape_backup status --source-root . --backup-root
<root>` fails with `MISSING_CRITICAL_FILES` when any local required CLOB class
is absent from the latest manifest. The report's CLOB coverage table shows
local bytes, backed-up bytes, missing bytes, excluded bytes, and warning counts
by class.

### CLOB Storage Budget

Treat `order_books_long.csv` as the budget driver. Any single file above 1 GB
is a warning in backup status and should trigger a review before adding more
markets or increasing capture cadence.

Preferred compaction path:

1. Keep raw `order_books.jsonl` with checksums permanently.
2. Keep `order_books_summary.csv` permanently for fast replay and audit.
3. Move older `order_books_long.csv` files to compressed cold storage after the
   manifest proves raw JSONL and summary rows are backed up and restorable.
4. Rebuild derived `clob_features*` from raw tapes during restore drills when
   practical; do not treat derived features as the only recoverable evidence.

Plan gzip tiering before applying it:

```powershell
python -m weather.operations.clob_order_book_tiering plan --settled-before 2026-06-19
```

Apply in small batches only when the preflight has enough scratch space:

```powershell
python -m weather.operations.clob_order_book_tiering apply --settled-before 2026-06-19 --delete-source --limit 1
```

The apply path requires free space for the source file plus a 1 GiB reserve,
writes `order_books_long.csv.gz` through a temp file, verifies decompressed
SHA-256 and line count against the source, and deletes the uncompressed CSV
only after verification and only when `--delete-source` is passed.

If a failed same-disk export leaves files in `latest/` that are not listed in
`latest/tape_backup_manifest.json`, plan cleanup before rerunning backup:

```powershell
python -m weather.operations.tape_backup prune-unmanifested
```

Apply only after the report shows the candidates have source counterparts:

```powershell
python -m weather.operations.tape_backup prune-unmanifested --apply
```

This removes only unmanifested files under the backup `latest/` directory; it
does not delete source tapes or manifest-listed backup files.

## Restore Drill

Run a restore drill after the first backup, after changing backup storage, and
at least once per week while live-forward tests are active.

```powershell
python -m weather.operations.tape_backup restore-drill --backup-root $env:WEATHER_TAPE_BACKUP_ROOT
```

The drill restores files to a temporary workspace, verifies manifest hash,
per-file checksums, registered JSON schema versions, critical tape-class counts,
and writes regenerated restore-input reports for fleet, promotion, and
market-making evidence.

The latest drill status is copied to
`latest/tape_restore_drill.json` under the backup root and is surfaced by
`weather.reporting.fleet_observability`.

## Recovery After Workstation Loss

1. Clone the repository on a clean machine and install dependencies.
2. Attach or sync the configured backup root.
3. Run `python -m weather.operations.tape_backup status --backup-root <root> --verify-checksums`.
4. Run `python -m weather.operations.tape_backup restore-drill --backup-root <root> --restore-root <new-workspace> --keep-restore`.
5. Copy the restored `data/` and `artifacts/` trees into the active workspace,
   preserving relative paths.
6. Regenerate operational reports:

```powershell
python -m weather.reporting.fleet_observability report --tape-backup-root <root>
python -m weather.operations.daily_refresh run --continue-on-error --tape-backup-root <root>
```

7. Do not enable live-order mode until fleet observability shows backup status,
   restore-drill status, snapshot collection, CLOB capture, and observation
   trigger gates as healthy or explicitly accepted by a documented risk cap.
