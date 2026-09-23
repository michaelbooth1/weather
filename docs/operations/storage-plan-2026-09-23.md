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
