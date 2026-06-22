# 246. Deduplicated Durable Tape Backup Repository [OPEN 2026-06-22 - MIRROR BACKUP REMAINS LONG-TERM ARCHIVE]

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
4. Integrate repository status into the existing tape backup status/fleet
   observability path without requiring `data/tape_backups/latest` to be the
   source of truth.
5. Add restore drills that recover at least one raw order-book JSONL tape, one
   Parquet partition, one manifest, and one replay-critical artifact into a
   temporary restore root and verify checksums/row counts.
6. Define retention policy for point-in-time snapshots: short-term frequent
   snapshots for live days, longer retention for settled/closed days, and
   permanent retention for irreplaceable raw evidence classes unless explicitly
   reclassified.

- [ ] Decide Restic versus Kopia and document the selection criteria.
- [ ] Configure a durable repository outside `data/tape_backups`.
- [ ] Add backup and status commands or wrappers for the selected repository.
- [ ] Add restore-drill evidence for raw JSONL, Parquet, manifests, and replay
  artifacts.
- [ ] Integrate deduplicated repository status into fleet observability and
  daily operational gates.
- [ ] Document credentials, repository path, retention policy, and restore
  procedure without committing secrets.

Acceptance: the project has a durable deduplicated backup repository outside
the workspace; restore drills prove raw and Parquet evidence can be recovered;
operational status reports fail when the repository is stale or unrestorable;
and `data/tape_backups/latest` is no longer treated as the long-term archive of
record.

Related: items 65, 111, 124, 146, 154, 239, 243, 247.
