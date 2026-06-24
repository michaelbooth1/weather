# 246. Deduplicated Durable Tape Backup Repository [COMPLETE 2026-06-24 - RESTIC SNAPSHOT AND RESTORE DRILL LIVE]

Goal: replace the same-disk `data/tape_backups/latest` mirror as the long-term
archive with a deduplicated, encrypted, durable backup repository that can
restore raw evidence and Parquet archive partitions.

Source: the 2026-06-22 storage audit found `data/tape_backups` at about 87.2
GB and `data/tape_backups/latest` at about 87.2 GB, while the latest manifest
covered about 65.3 GB. The current backup code checksum-skips unchanged files,
but changed append-heavy CSV/JSONL files are still stored as whole-file mirror
copies. Item 146 already tracks that same-workstation storage is not enough for
durability; this item chooses and integrates the deduplicated archive backend.

Why this matters: raw tapes are irreplaceable, but a full-file mirror is the
wrong long-term storage primitive for append-heavy evidence. A content-defined
deduplicating repository such as Restic or Kopia preserves point-in-time
history and restore capability while avoiding repeated full copies of mostly
similar files.

## Design

1. Choose the supported backend for this project: Restic, Kopia, or an
   equivalent content-defined deduplicating repository, with the decision
   documented in the operator runbook.
2. Place the repository outside the workspace on external, NAS, or object
   storage with enough headroom for raw evidence, Parquet archives, manifests,
   and growth.
3. Back up raw forensic evidence, Parquet archive partitions, manifests, model
   artifacts needed for replay, and settlement/promotion evidence according to
   retention classes.
4. Expose repository status through a fail-closed operational status report
   without requiring `data/tape_backups/latest` to be the source of truth.
   Fleet/daily reporting integration is deferred while reporting moves remain
   active.
5. Add restore drills that recover at least one raw order-book JSONL tape, one
   Parquet partition, one manifest, and one replay-critical artifact into a
   temporary restore root and verify checksums/row counts.
6. Define retention policy for point-in-time snapshots: short-term frequent
   snapshots for live days, longer retention for settled/closed days, and
   permanent retention for irreplaceable raw evidence classes unless explicitly
   reclassified.

- [x] Decide Restic versus Kopia and document the selection criteria.
- [x] Configure a durable repository outside `data/tape_backups`.
- [x] Add backup and status commands or wrappers for the selected repository.
- [x] Add restore-drill flow for raw JSONL, Parquet, manifests, and replay
  artifacts.
- [x] Add live restore-drill evidence for raw JSONL, Parquet, manifests, and
  replay artifacts from the external repository.
- [x] Add fail-closed deduplicated repository status evidence; fleet/daily
  observability integration is deferred while reporting moves remain active.
- [x] Document credentials, repository path, retention policy, and restore
  procedure without committing secrets.

Acceptance: the project has a durable deduplicated backup repository outside
the workspace; restore drills prove raw and Parquet evidence can be recovered;
operational status reports fail when the repository is stale or unrestorable;
and `data/tape_backups/latest` is no longer treated as the long-term archive of
record.

Related: items 65, 111, 124, 146, 154, 239, 243, 247.

## Implementation Notes

2026-06-24:

- Selected Restic as the supported deduplicated backend. The runbook documents
  the Restic-over-Kopia decision, repository/credential environment variables,
  initialization, backup, status, and restore-drill commands.
- Added `weather.operations.tape_backup dedup-backup`, `dedup-status`,
  `dedup-restore-drill`, and `dedup-run` wrappers. They fail closed when the
  Restic binary, repository, credential material, tagged snapshot, or current
  restore-drill evidence is missing.
- Extended the retention manifest to include
  `closed_market_day_parquet_archives`, covering
  `data/archive/closed_market_days/**/*.parquet` and
  `closed_market_day_archive_manifest.json`.
- Added restore-drill selection for one raw order-book JSONL tape, one
  closed-day Parquet partition, one archive/source manifest, and one
  replay-critical artifact. The drill verifies SHA-256 checksums, registered
  JSON schemas, and Parquet row counts when the archive manifest records them.

Restic `0.19.0` is installed in user scope, and an encrypted repository was
initialized at `C:\Users\micha\OneDrive\weather-restic-repo` with password
material stored outside the repo at `C:\Users\micha\.weather-restic-password`.

Live repository evidence is now recorded:

- `python -m weather.operations.tape_backup dedup-run --executable
  C:\Users\micha\AppData\Local\Microsoft\WinGet\Packages\restic.restic_Microsoft.Winget.Source_8wekyb3d8bbwe\restic_0.19.0_windows_amd64.exe
  --repository C:\Users\micha\OneDrive\weather-restic-repo --password-file
  C:\Users\micha\.weather-restic-password --timeout-seconds 21600` -> `PASS`.
- `data/backtest/tape_dedup_repository_backup.json` records snapshot
  `47ebbeebbea804bceb8aa66923b542b90f63f2c104ce7c1c4c55ebd510e2a550`,
  `17,951` manifest files, `83,629,776,580` bytes, and no missing critical
  classes.
- `data/backtest/tape_dedup_restore_drill.json` records restore-drill `PASS`
  for raw order-book JSONL, closed-day Parquet, closed-day archive manifest,
  and replay-critical artifact categories, with `4` verified files, zero
  checksum failures, zero schema failures, and zero Parquet failures.
- `data/backtest/tape_dedup_repository_status.json` records repository status
  `OK`, `1` tagged snapshot, and restore-drill SLA `OK` for the latest
  snapshot.
- `restic check` against `C:\Users\micha\OneDrive\weather-restic-repo` found no
  errors.

The same-disk `data/tape_backups/latest` mirror remains useful as a local cache
and for existing cleanup gates, but the long-term archive of record is now the
encrypted Restic repository. Fleet/daily reporting integration is intentionally
left to the active reporting workstream; `dedup-status` is the fail-closed
operational gate for this item.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - RESTIC SNAPSHOT AND RESTORE DRILL LIVE`.
- The file contains 7 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

