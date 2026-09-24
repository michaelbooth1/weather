# Production storage plan — 2026-09-23

- **Owns:** the owner's 2026-09-23 storage decision and the operating plan that follows from it: thresholds, the order of
  levers, and what runs when.
- **Read when:** production free space is below the green band, a heavy job refuses on disk, or you are about to
  compress, archive or reclaim anything under `data/`.
- **Do not use for:** the mechanics of each lever (linked below) or today's free space (`Get-Volume -DriveLetter C`).

**Owner decision, 2026-09-23:** no second disk. We make do with the existing volume, and off-PC storage (the private
Google Drive cold archive already used in July/August) is used **as needed**. Every existing gate still binds:
never delete evidence without an uploaded, independently restore-verified archive and the exact-file reclaim contract;
compress-and-retain changes no bytes a reader sees.

## Why now

On 2026-09-23 the host bounded suite stopped at its 50 GiB floor after 10 of 22 chunks (it passes no `--basetemp`, so
pytest retained ~2.6 GB under `%TEMP%\pytest-of-micha`); free space was 49.7 GiB at 08:30 and falls ~10-13 GiB/day.
The fixed 16 GB pagefile has not grown (checked 09-23). The NBM re-download is a network/CPU cost, not retained disk
(audit D5-01: the payload store skips bytes it already holds). No document attributes the current slope to a data class.

**Owner, 2026-09-23: the production PC is the production agent's alone; the owner never uses it, and any leftover personal
or non-project file on it may be deleted as needed.** That covers everything outside the project's evidence. Project evidence
(`data/` tapes, ledgers, labels, the RE-1 campaign root, `.git/lfs`) still leaves only by the archive-verify-reclaim path
below, because losing it harms the project, and credential files are never opened or removed.

## Bands (judge at the daily low, ~04:50, never an evening reading)

| Band | Free at daily low | Action |
| --- | --- | --- |
| Green | ≥ 75 GiB | normal; nightly compress-and-retain of newly closed days only |
| Amber | 60-75 GiB | plus: archive closed days older than 30 days to Drive, verify restore, reclaim |
| Red | 50-60 GiB | plus: archive down to 14 days; no heavy job that writes > 2 GiB |
| Critical | < 50 GiB | the suite and roll-sensitive landings refuse; archive aggressively; owner told |

Target: hold the daily low at **≥ 70 GiB** so the suite (50 GiB floor plus its own writes) always fits.

## Order of levers

1. **Measure (first night, 00:30-09:00, under the lease):** the read-only storage inventory
   (`weather.operations.storage_recovery_inventory`) attributes bytes and one day's growth by data family. No drain is
   chosen before this exists.
2. **Stop self-inflicted writes (DONE 2026-09-23, `e1d766417`):** `scripts/ops/bounded_worktree_test_suite.ps1` gets a per-chunk `--basetemp` under a
   short path, deleted after each chunk (roll-free `.ps1`), and removes stale `%TEMP%\pytest-of-*` it created.
3. **Compress and retain** closed days with the existing attended NTFS lane
   ([cold-snapshot-compression.md](cold-snapshot-compression.md)); no bytes change for readers.
4. **Off-PC archive** of old closed event days to the private Drive with the existing staging/transfer lane
   ([production-cold-archive-staging.md](production-cold-archive-staging.md),
   [cold-archive-locations.md](cold-archive-locations.md)), then independent restore verification, then exact-file
   reclaim. Oldest days first; never the current or previous 14 days; never the RE-1 campaign root.
5. **Stop growth at the source** once step 1 names the largest writer (for example compress-on-close for the largest
   per-day family), and add a capture-side low-disk brake that stops rebuildable projections before canonical tape
   (audit D5-01 (c)).

## Record

Each night's actions, bytes before/after and receipts go to the item-325 storage record and `STATE_OF_PLAY.md`.

## Step 1 inventory — 2026-09-24 00:39-00:43 (read-only, under the lease)

Stat-only walk of `data/` (no file contents opened, BelowNormal, 3 minutes): **4,441,260 files, 685 GiB logical**; 18.95 GiB
modified in the last 24 hours. Volume free 54.3 GiB at 00:33.

- **Snapshot event folders' immediate files: ~453 GiB on disk and almost entirely uncompressed** (on-disk ≈ logical).
  Largest by name: `replay_inputs.jsonl` 78 GiB, `clob_tokens.jsonl` 60, `order_books_summary.csv` 45, `clob_tokens.csv` 41,
  `order_books_long.csv.gz` 35 (already gzip), `variant_predictions.jsonl` 34, `snapshot_explanations_long.csv` 24,
  `variant_predictions_long.csv` 23, `order_books.jsonl.gz` 22, `snapshots.jsonl` 21, `components.jsonl` 19.
- **Compressibility** (gzip level 1, one closed 2026-07-10 folder, read-only): `replay_inputs.jsonl` 9.5x,
  `order_books_summary.csv` 4.9x, `clob_tokens.csv` 19.7x, `snapshot_explanations_long.csv` 20x. NTFS LZNT1 is weaker than
  gzip but transparent to readers; even 2-3x on closed days would return well over 100 GiB.
- `mm_runs/` (paper maker roll) 42 GiB uncompressed, ~0.8 GiB per day, no pruning; `taker_runs/` 9 GiB (taker paused);
  `backtest/replay_cache` 32 GiB; `forecast_payload_cas` 13 GiB.
- **The daily slope is not a leak in one family:** capture writes ~0.8 GiB/hour; step reclaims come from the Stage-A chain
  (09:30-11:55) and a +12.8 GiB step at 21:50-22:05 on 09-23 with no project task running. Windows System Restore holds a
  shadow copy (5.8 GB used, 18.6 GB maximum; copy #6 created 09-23 12:12); its purges are the likely source of unexplained
  steps. Deleting or capping restore points is an owner decision (irreversible system change), not a junk sweep.
- The 05:00 CLOB tiering reclaimed nothing on 09-23 because every closed day's long CSV is already gzip (699/699).
- The scheduled `data_retention_inventory` report last ran 2026-08-13; its daily refresh step has stopped.
- Junk outside the project is small: user temp 23 MB, Windows temp 1 MB, update cache 12 MB, Downloads 131 MB, Recycle Bin
  41 MB. **Worktrees:** 222 registered (33 bound to scheduled tasks); each is ~50 MB, so the 70 clean, merged, >=7-day, untasked
  candidates without local `data/` are ~3.5 GiB.

**Lever order revised by this measurement:** (a) closed-day NTFS compress-and-retain at scale (the existing lane's 64 MiB/file,
1 GiB/batch bounds make ~150 GiB take hundreds of attended batches, so mission 91a automates it); (b) compress-on-close at the
source for the large text families (reader-aware gzip, like the long CSV); (c) prune or gzip `mm_runs`; (d) worktree cleanup.

**Daily low 2026-09-24:** 51.2 GiB at 04:50 (trail), 51.1 GiB at 04:57 — **Red**, 1 GiB above the suite floor. Night slope
~0.5 GiB/hour (54.3 at 00:33). No reclaim was run: compression waits on mission 91a; restore-point capping is an owner call.

**Correction 2026-09-24 12:35 (second-opinion audit, verified):** the 51.1 GiB "daily low" above was the 04:57 reading, not the
24 h minimum. The trail's true low was **43.2 GiB at 21:50 on 09-23**; free space was 45.7 GiB at 12:35 on 09-24 (Critical). The
trough is no longer at ~04:50: the large reclaim steps are System Restore purges (shadow storage 15.4 GB used of 18.6 GB, three
restore points), and the 05:00 CLOB tiering reclaims nothing because every closed day is already gzip. Judge the band from the
trail's 24 h minimum, not a fixed clock time.

**Owner actions 2026-09-24 ~12:45:** shadow storage capped at 2 GB (45.7 -> 56.4 GiB free), Windows Search disabled and its
1.7 GB index removed (-> 58.0 GiB), Defender exclusion on `data\`, paper maker roll paused (~0.8 GiB/day stops).
