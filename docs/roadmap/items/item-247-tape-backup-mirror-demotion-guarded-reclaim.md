# 247. Tape Backup Mirror Demotion And Guarded Reclaim [OPEN 2026-06-22 - UNMANIFESTED MIRROR DUPLICATES BLOCK RECLAIM]

Goal: safely demote `data/tape_backups/latest` from long-term archive to
short-term local restore cache, then reclaim only unmanifested duplicate mirror
files after manifest and restore evidence pass.

Source: the 2026-06-22 storage audit found about 21.9 GB in 29 files under
`data/tape_backups/latest` that are not referenced by the latest manifest.
Most sampled files are old order-book CSV mirror copies whose source
counterparts still exist. The repo already has
`python -m weather.operations.tape_backup prune-unmanifested`, but the current
operator policy does not require a full dry-run, report inspection, restore
drill, and apply gate before reclaiming local mirror bytes.

Why this matters: the safest way to regain local headroom is to remove
verified duplicate backup mirror files, not source data. But reclaim must be
fail-closed: no source tape, raw JSONL, Parquet partition, or manifest should
be deleted because a mirror cleanup looked plausible.

## Design

1. Treat `data/tape_backups/latest` as a local cache for recent restore
   convenience, not as the durable archive of record once Item 246 is live.
2. Require `prune-unmanifested` dry-run output before any local mirror cleanup,
   with candidate rows showing latest manifest hash, source counterpart, file
   size, and reason.
3. Require latest manifest validation and a current restore drill before apply
   mode can delete any unmanifested mirror file.
4. Restrict apply mode to files under `data/tape_backups/latest` that are not
   in the latest manifest and whose source counterpart still exists or whose
   durable deduplicated repository restore is verified.
5. Write an applied cleanup manifest with deleted paths, bytes, manifest hash,
   restore-drill evidence, skipped rows, and post-cleanup backup status.
6. Add a local mirror retention setting for how much recent cache, if any, is
   worth keeping after the deduplicated repository is operational.

- [ ] Run and review `python -m weather.operations.tape_backup
  prune-unmanifested` in dry-run mode against the current mirror.
- [ ] Add or tighten tests that apply mode refuses to delete without manifest
  validation and restore-drill evidence.
- [ ] Add an operator gate that blocks cleanup when candidate files lack a
  source counterpart or verified durable-repository restore.
- [ ] Apply cleanup only to verified unmanifested mirror duplicates.
- [ ] Refresh backup status, fleet observability, and local storage inventory
  after cleanup.
- [ ] Document the new role of `data/tape_backups/latest` as cache, not
  archive.

Acceptance: unmanifested duplicate files in `data/tape_backups/latest` can be
reclaimed through a dry-run, restore-verified, manifest-backed apply workflow;
no source snapshot data is deleted; post-cleanup backup status remains healthy;
and the runbook makes clear that durable retention belongs to the
deduplicated repository, not the local mirror.

Related: items 65, 111, 124, 146, 154, 239, 246.
