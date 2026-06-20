# 171. Local Data Retention And CLOB Tape Storage Cleanup [OPEN]

Goal: reduce local runtime data from an unbounded 138 GB working tree into a
documented, recoverable, and operator-safe storage layout.

Source: the 2026-06-20 full repository cleanup audit. The ignored `data/`
directory contains roughly 188k files and 138 GB. The largest contributors are
`data/tape_backups` at roughly 60 GB and `data/snapshots` at roughly 58 GB,
with many market-day order book and snapshot JSONL files above hundreds of MB.

Why this matters: the project is now operationally constrained by local disk
growth. Cleanup cannot be an ad hoc delete because these tapes may be the only
copy of live CLOB, snapshot, taker, market-making, and backtest evidence.

## Design

1. Inventory `data/` by owner, producer, regeneration path, and durability
   requirement: raw CLOB tape, live snapshot, forecast/observation cache,
   backtest output, market-making run, taker run, and operational report.
2. Separate durable evidence from regenerable cache and scratch output.
3. Add a retention manifest that records keep/delete/archive/compress policy
   for each major data subtree.
4. Move large durable raw tapes to an external root or object store with local
   manifests and restore checks.
5. Replace mirror-like `data/tape_backups/latest` growth with a bounded
   backup strategy: dedupe, hardlink where safe, compress, or rotate.
6. Add preflight disk-headroom and retention warnings before active-day loops,
   daily refresh, tape backup, and backtest generation can create another
   large batch.

- [ ] Produce a `data/` ownership and retention inventory report.
- [ ] Define keep/archive/delete TTLs for `snapshots`, `tape_backups`,
  `backtest`, `mm_runs`, `taker_runs`, `ops`, and provider caches.
- [ ] Add restore-proof checks before any raw tape or snapshot deletion is
  permitted.
- [ ] Compress or externalize large historical JSONL/CSV evidence files after
  manifesting them.
- [ ] Add a daily disk-budget report that flags the largest new files and
  directories.
- [ ] Document the operator procedure for pruning local data safely.

Acceptance: local `data/` growth is bounded by policy, every deletion candidate
has an owner and restore/regeneration answer, and active-day operations fail
early with a clear disk-budget blocker instead of silently filling the drive.

