# 65. Irreplaceable Tape Retention, Backup, And Restore [NEW - OPEN]

Goal: make one-machine loss non-fatal for the append-only evidence that cannot
be reconstructed after the fact.

Why this is missing: completed data-layer work made snapshot, CLOB, trigger,
ledger, promotion, and market-making tapes more complete and auditable, and
item 39 moved large regenerable data out of git. That leaves a separate risk:
the most valuable raw/live-forward tapes now live outside git and some of them
cannot be rebuilt from public sources once the day passes.

- [ ] Classify artifacts by recoverability: irreplaceable raw/live tapes,
  rebuildable derived reports, model artifacts, manifests, and scratch output.
- [ ] Define retention rules for snapshots, replay inputs, CLOB raw books,
  CLOB summaries, trade streams, observation-trigger events, settlement ledgers,
  promotion corpora, market-making run folders, order lifecycles, and risk
  events.
- [ ] Add an incremental backup/export job with checksums and manifest hashes
  to a configurable external or cold-storage root, excluding clearly
  rebuildable intermediates.
- [ ] Add a restore drill that rebuilds a clean temp workspace from backup,
  verifies hashes/schema versions/tape counts, and regenerates the latest
  fleet, promotion, and market-making reports from restored inputs.
- [ ] Surface backup age, last successful restore drill, missing critical tape
  classes, and checksum failures in the daily refresh or fleet observability
  report.
- [ ] Document the operator recovery steps for a failed workstation or corrupt
  data directory before any live-order mode is enabled.

Acceptance: a local data loss event does not destroy settlement, CLOB, trigger,
or market-making evidence needed for promotion gates, live-forward paper gates,
or post-trade audit, and a restore drill proves the current reports can be
recreated from the backup root.
