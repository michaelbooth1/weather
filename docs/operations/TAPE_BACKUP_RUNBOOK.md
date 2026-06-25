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

## Deduplicated Durable Repository

The supported deduplicated backend for this project is **Restic**. Restic was
chosen over Kopia for this repository because it is a single CLI binary,
encrypts repositories by default, supports local external disks, NAS paths, and
object-storage repository URLs, and can be wrapped without adding a daemon or
new Python dependency.

Use the same local mirror/root above as a short-term restore cache only. The
durable repository of record must live outside this checkout: external disk,
NAS, or object storage with enough headroom for raw tapes, closed-day Parquet
archives, manifests, model artifacts, and growth.

Configure credentials outside git:

```powershell
$env:WEATHER_TAPE_DEDUP_REPOSITORY = "E:\weather-restic-repo"
$env:RESTIC_PASSWORD_FILE = "C:\Users\<operator>\.weather-restic-password"
```

Object-storage targets should use Restic's normal repository URL and provider
environment variables. Do not commit repository passwords, access keys, or
provider tokens. The generated status artifacts record whether credential
material was present, but never the secret values.

Initialize the repository once from the repo root:

```powershell
restic -r $env:WEATHER_TAPE_DEDUP_REPOSITORY init
python -m weather.operations.tape_backup dedup-status --no-require-restore-drill
```

Run the full durable backup, restore drill, and status refresh:

```powershell
python -m weather.operations.tape_backup dedup-run
```

The all-in-one command writes:

- `data/backtest/tape_dedup_repository_backup.json`
- `data/backtest/tape_dedup_repository_backup_report.md`
- `data/backtest/tape_dedup_restore_drill.json`
- `data/backtest/tape_dedup_restore_drill_report.md`
- `data/backtest/tape_dedup_repository_status.json`
- `data/backtest/tape_dedup_repository_status_report.md`

`dedup-backup` builds the same retention manifest as the local mirror path,
writes `data/backtest/tape_dedup_repository_manifest.json`, and backs up the
manifest plus every retained file using Restic tags `weather-tape` and
`tape_retention_policy_v0.1`.

`dedup-restore-drill` restores the manifest first, then drills representative
evidence classes from the latest tagged snapshot:

- one raw order-book JSONL tape or critical raw JSONL fallback;
- one closed market-day Parquet partition;
- one archive/source manifest;
- one replay-critical model artifact or replay input.

The drill verifies SHA-256 checksums, registered JSON schema versions, and
Parquet row counts when a closed-day archive manifest records the expected
count. `dedup-status` fails closed when the Restic binary, repository,
credential material, tagged snapshot, or current restore-drill evidence is
missing.

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
- `closed_market_day_parquet_archives`: retain with the corresponding raw
  source evidence. These Parquet partitions are rebuildable analysis
  projections, but durable restore drills must recover at least one partition
  and validate its row count.
- Closed market-day Parquet archive partitions and
  `closed_market_day_archive_manifest_v0.1` manifests: retain with their raw
  source evidence after Item 244 begins writing them. The archive contract is
  documented in
  [Closed Market-Day Parquet Archive Contract](closed-market-day-parquet-archive-contract.md).

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
- `price_history`: `price_history.csv`, `price_history.jsonl`,
  `price_history_raw_manifest.jsonl`, and `price_history_raw/*.json`; CLOB
  price-history point history plus content-addressed raw responses used for
  microstructure features and replay.
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

## Cleanup Preflight

Run cleanup preflight before deleting or demoting local data:

```powershell
python -m weather.operations.cleanup_preflight --manifest data\backtest\cleanup_manifest.json
```

Every cleanup manifest must name exact relative paths, storage class, retention
class, deletion reason, rebuild source or `not rebuildable`, byte count,
SHA-256, latest backup manifest hash, restore-drill manifest hash, and an
approving operator note.

Canonical evidence deletion is allowed only when the candidate is listed in the
reviewed cleanup manifest, the latest backup status is `OK`, restore-drill SLA
is `OK`, no backup checksum failures are present, and the latest backup
manifest covers the candidate hash. If tape status is
`MISSING_CRITICAL_FILES`, canonical evidence deletion is a hard block; the
preflight report carries the missing-file samples from tape status.

Projection and operator/cache cleanup can still proceed with reviewed
manifests when they do not delete canonical evidence. Examples include
rebuildable `data/backtest` row exports and verified gzip-tiered
`order_books_long.csv` projections. Same-disk backup mirror cleanup under
`data/tape_backups/latest` has a stricter gate because those files can look
like cache while still being the only local restore copy of a file that is not
covered by the latest manifest.

Treat `data/tape_backups/latest` as a short-term local restore cache, not as
the durable archive of record. Durable retention belongs outside the workspace
on the external or deduplicated repository covered by the backup status and
restore-drill evidence.

If a failed same-disk export leaves files in `latest/` that are not listed in
`latest/tape_backup_manifest.json`, plan cleanup before rerunning backup:

```powershell
python -m weather.operations.tape_backup prune-unmanifested
```

Review both the JSON and Markdown report. Candidate rows must show the latest
manifest hash, the source counterpart, file size, source/mirror SHA-256 match,
durable restore proof when the source counterpart is absent, and the reason the
row is eligible or blocked. If meaningful reclaim bytes are blocked only
because the source counterpart is absent, create a per-row durable proof before
regenerating the dry-run:

```powershell
python -m weather.operations.tape_backup prove-unmanifested `
  --plan data\backtest\tape_backup_unmanifested_cleanup.json `
  --executable <restic.exe> `
  --repository <durable-restic-repo> `
  --password-file <password-file>

python -m weather.operations.tape_backup prune-unmanifested `
  --durable-restore-proof data\backtest\tape_backup_unmanifested_durable_restore_proof.json
```

The proof command writes
`data/backtest/tape_backup_unmanifested_durable_restore_proof.json` and a
Markdown report, backs up the selected unmanifested mirror rows to the durable
Restic repository under tag `weather-tape-unmanifested-mirror-proof`, restores
each selected row, and verifies the restored SHA-256 equals the local mirror
SHA-256. Apply is fail-closed unless all of these are true:

- the reviewed dry-run JSON is passed back with `--reviewed-plan`;
- the latest manifest validates and still matches the dry-run plan hash;
- the latest restore drill is current and matches the latest manifest hash;
- tape backup status is `OK`;
- every unmanifested row is either a byte-identical source-backed duplicate or
  has current byte-identical durable restore proof;
- an operator approval note is supplied.

Apply syntax, used only after durable backup/restore evidence is current:

```powershell
python -m weather.operations.tape_backup prune-unmanifested --apply `
  --reviewed-plan data\backtest\tape_backup_unmanifested_cleanup.json `
  --operator-approve `
  --operator-approved-by "<operator>" `
  --operator-note "reviewed dry-run report; durable backup and restore evidence current"
```

This removes only unmanifested files under the backup `latest/` directory; it
does not delete source tapes or manifest-listed backup files. Do not apply
cleanup when the report has blocked rows, missing/stale restore evidence,
`MISSING_CRITICAL_FILES`, or any source/mirror size or checksum mismatch.

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
`weather.reporting.fleet.fleet_observability`.

## Recovery After Workstation Loss

1. Clone the repository on a clean machine and install dependencies.
2. Attach or sync the configured backup root.
3. Run `python -m weather.operations.tape_backup status --backup-root <root> --verify-checksums`.
4. Run `python -m weather.operations.tape_backup restore-drill --backup-root <root> --restore-root <new-workspace> --keep-restore`.
5. Copy the restored `data/` and `artifacts/` trees into the active workspace,
   preserving relative paths.
6. Regenerate operational reports:

```powershell
python -m weather.reporting.fleet.fleet_observability report --tape-backup-root <root>
python -m weather.operations.daily_refresh run --continue-on-error --tape-backup-root <root>
```

7. Do not enable live-order mode until fleet observability shows backup status,
   restore-drill status, snapshot collection, CLOB capture, and observation
   trigger gates as healthy or explicitly accepted by a documented risk cap.
