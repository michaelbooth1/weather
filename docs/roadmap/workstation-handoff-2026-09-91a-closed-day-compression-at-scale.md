# Workstation handoff 2026-09-91a — closed-day compression at scale

Written 2026-09-24 by the production agent after the storage-plan step 1 inventory
([storage plan](../operations/storage-plan-2026-09-23.md), "Step 1 inventory"). Production has ~54 GiB free and falls
~10 GiB/day between reclaims; ~453 GiB of snapshot-folder text is stored uncompressed and compresses 5-20x under gzip.
Build and test on the workstation; production runs it after review and landing.

## 1. Goal

Return most of that space **without changing any byte a reader sees** first, then stop the growth at the source.

1. **Scheduled closed-day NTFS compress-and-retain.** Extend the existing lane (`cold_snapshot_compression`,
   `storage_recovery_inventory`, their runbooks) so a nightly scheduled run, inside 00:30-04:45 under the shared lease,
   selects closed event days older than **14 days** (owner storage plan; RE-1 campaign root and hot days never), plans
   bounded batches itself, and compresses them with the same per-file preimage/postimage hashing, writer exclusion,
   identity and allocation receipts. Raise the per-file limit so the large files (60-90 MiB and up) qualify, with a
   streaming hash and the same resource checks; keep a nightly byte budget and a stop on any failure. Report verified
   savings per night.
2. **Compress-on-close at the source** (design plus implementation if small): for the largest text families
   (`replay_inputs.jsonl`, `clob_tokens.jsonl`, `order_books_summary.csv`, `clob_tokens.csv`, `variant_predictions*.`,
   `snapshot_explanations_long.csv`, `components*`, `snapshots.jsonl`), either NTFS-compress at day close or gzip with
   reader support, following the existing long-CSV tiering pattern. List every reader and prove it handles the result.
3. **`mm_runs/`** (paper maker roll, ~0.8 GiB/day, 42 GiB, no pruning): propose retention or compression under the
   data-storage-class contract.

## 2. Constraints

Loop-imported capture modules are roll-sensitive: separate roll-free pieces (`scripts/ops/*.ps1`, new non-loop modules)
from anything the supervisors import, and say which is which. Never delete evidence; compression must be lossless and
verified. No `.env`, credentials, venue calls, RE-1 worktree or campaign root; nothing heavy while an RE-1 session runs.

## 3. Deliverables

Branch `codex/closed-day-compression-20260924` (push authorized); tests with synthetic folders (large files, locked
writer, hash mismatch, budget stop, hot-day refusal); the updated runbooks and storage-plan lever; report
`docs/roadmap/agent-report-2026-09-91a-closed-day-compression-at-scale.md` with verdict first, projected nightly savings,
roll classification per file, and the scheduled-task registration the production agent will run.
