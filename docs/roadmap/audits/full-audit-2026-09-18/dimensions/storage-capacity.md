# Audit dimension: Storage and capacity plan (storage-capacity)

Auditor: Claude (subagent), 2026-09-18, run on the live production capture host inside the
protected near-close window. Read-only. No project file was modified; this report is the only write.

## 1. Bottom line

1. **The disk does not have "~4 days". It has roughly 1.5-2.5 days.** The monitor divides the
   *current* free space by a 24-hour slope. The 15-minute trail shows a 13-16 GiB daily sawtooth
   whose low point is at ~04:50, just before the 05:00 tiering job. The binding moment is that
   trough, not the evening reading. Yesterday's trough was 14.2 GiB; tonight's is projected at
   ~6-8 GiB; the following night's is ~0-2 GiB.
2. **The only automatic reclaim deadlocks before the disk reaches zero.** The 05:00 projection
   tiering refuses any file unless `free >= source_bytes + 1 GiB` (about 2.2-2.6 GiB for a normal
   `order_books_long.csv`). The 06:00 raw-tape tiering needs `source + 8 GiB` and additionally refuses
   a folder while `order_books_long.csv` is still present. Neither task has catch-up or retry. Below
   ~2.5 GiB free the host cannot heal itself.
3. **Capture is not fail-closed on disk-full; it is fail-crash with tape corruption.** No disk-free
   check exists anywhere under `src/weather/collection` or in the CLOB store. Appends are plain
   buffered `open("a")` writes with no fsync and no ENOSPC handling. A truncated JSONL line makes the
   canonical order-book reader raise for the whole market-day. Both loops' error paths write status to
   the same full disk, so they exit; the snapshot supervisor opens its breaker after 6 restarts/24 h
   and then needs a manual restart.
4. **Every manual recovery lane is currently inadmissible by its own disk floor** (archive 50 GiB,
   plan-bound 20 GiB, dated 25/8 GiB exceptions expired; replay-cache compression 20 GiB; ordinary
   heavy work 50 GiB). The lane designed to fix low disk needs more free disk than exists. Nothing
   except the two tiering tasks is armed, and they are already inside the measured net burn.
5. **Plainly: the current plan cannot win the race against ~6-8 GiB/day.** The best night ever
   (2026-09-10/11, 79.1 GB reclaimed) bought about seven days. It was a dated, attended one-shot.
   Four subsequent nights failed. There is no recurring retention service, and the one software
   change that would cut the slope (~6 -> ~1.3 GB/day warm tier) has been blocked on the event-day
   manifest pipeline since 2026-08-02.
6. The cheapest real fixes are not the archive machinery: (a) a config-only flag already built and
   merged (`write_order_books_long_csv=false`) is worth ~13 GiB of trough headroom per day;
   (b) a check of Windows shadow-copy storage may return 10+ GiB in minutes; (c) a second disk
   (~CAD 100-250) ends the race for a year or more.

Health grade: **D**. Data-integrity discipline is genuinely strong; capacity planning is losing, the
monitor overstates headroom, and the failure mode at zero is destructive to the project's most
valuable, non-backfillable data.

## 2. Scope and method

Read in full: `docs/roadmap/items/item-325-*.md` (1,392 lines), `docs/operations/HOST_LOAD_POLICY.md`,
`storage-recovery-inventory.md`, `cold-snapshot-compression.md`, `config/storage_pressure.json`,
`data/alerts/disk_free_trail.jsonl` (400 rows, explicitly allowed), `scripts/ops/clob_tiering_run.ps1`,
`src/weather/market/storage_pressure_policy.py`. Read in part / by targeted grep:
`replay-cache-compression.md`, `production-cold-archive-staging.md`, `cold-archive-locations.md`,
`data-retention-policy.md`, `STATE_OF_PLAY.md`, `ESTABLISHED_FINDINGS.md` (sections 8d, 8e, 8p),
`RETRACTED_AND_FALSE_LEADS.md`, `clob_order_book_tiering.py`, `clob_raw_tape_tiering.py`,
`capture_resource_gate.py`, `daily_refresh.py`, `daily_refresh_locks.py`, `bot_run_liveness.py`,
`supervisor.py`, `snapshot_tracker.py`, `snapshot_store.py`, `market_microstructure.py`,
`market_microstructure_capture.py`, `order_book_tape.py`, `production_cold_archive_stage_cli.py`,
`replay_cache_compression_admission.py`, `status.ps1`, `workload_admission.ps1`,
`register_clob_tiering.ps1`, `clob_raw_tape_tiering_run.ps1`.

Shell, whitelist only: `git log`, `git show --stat`, `git show <rev>:<path>`, `git branch --contains`,
`git ls-tree`, `git shortlog`, `git worktree list`, and non-recursive `ls` of `data/alerts`, `C:/`,
`C:/tmp`, `C:/XboxGames`, one sibling worktree, `src/weather/collection`. No python, no scans, no
`data/` walk, no network.

Traces performed end to end (not grep-only):
- tiering headroom precondition: wrapper args -> `apply_tiering` loop -> `skipped_insufficient_headroom`;
- CLOB write path: `write_books` -> `append_csv`/`append_jsonl` -> reader `iter_*` raising on a bad row;
- snapshot loop and CLOB loop error paths -> unguarded status writes -> process exit -> supervisor guard;
- policy flag: `config/storage_pressure.json` -> `load_storage_pressure_policy` -> store constructor ->
  per-capture construction site;
- monitor headroom formula in `status.ps1`.

Units: `status.ps1:1298` divides by PowerShell `1GB` (2^30), so every `free_gb` in the trail is GiB.

## 3. Live state from the trail (`data/alerts/disk_free_trail.jsonl`)

| Marker | 09-15 | 09-16 | 09-17 | 09-18 |
| --- | ---: | ---: | ---: | ---: |
| 04:50 pre-tiering | 29.9 | 33.3 | 25.9 | **14.2** |
| 05:05 after projection tiering | 43.0 | 47.1 | 37.6 | 27.7 |
| 06:05 after raw-tape tiering (daily peak) | 59.7 | 49.2 | 41.9 | 29.4 |
| 22:05 | 29.8 | 36.2 | 24.9 | **18.5** (last sample) |
| Daily minimum | 29.9 | 18.4 (03:05) | 17.6 (18:35) | 14.2 |

(09-14 22:05 was 42.7.)

- Scheduled reclaim is visible and regular: +11.7 to +13.8 GiB at 05:00, +2.5 to +2.7 GiB at 06:00.
- Peak-to-peak: 59.7 -> 49.2 -> 41.9 -> 29.4 = **-10.1 GiB/day**.
- Same-phase 22:05: 42.7 -> 18.5 over four days = **-6.05 GiB/day** (matches the monitor's 5.9).
- Docs-to-trail, same phase ~09:00: 81.6 GiB (09-11 08:57, item-325 line 82) -> 25.9 GiB (09-18 08:50)
  = **-8.0 GiB/day**, and that *includes* a +11.9 GiB compression credit on 09-13.
- Overnight burn 22:05 -> 04:50 is steady at 10.3-12.8 GiB on all four nights.
- Unexplained step-ups that are **not** the scheduled jobs: +15.8 (09-16 03:20), +6.5 (09-16 11:35),
  +13.8 (09-17 18:50, inside the protected window where tiering refuses to run), +3.2 (09-18 10:20),
  +7.7 (09-18 12:20), +2.6 (09-15 10:20). Matching step-downs of 1.7-9.3 GiB occur at 09:35-10:05 when
  Stage A starts. Candidates: system-managed pagefile growth/shrink (see finding 5; section 8d of
  ESTABLISHED_FINDINGS proves this mechanism on this host) and Windows shadow-copy expiry (item-325
  lines 34-37 records shadow storage absorbing reclaim on 09-13). I could not attribute them. The
  net slope depends on them continuing.

Projection (inferred, falsifiable): trough 09-19 04:50 = 18.5 minus 10.3-12.8 = **5.7-8.2 GiB**.
After tiering ~22-24 GiB. At -6/day net the 09-19 evening level is ~12.5 and the 09-20 trough is
**~0-2 GiB**, which is below the tiering precondition. At the 7-day rate (-8) or peak-to-peak rate
(-10) the floor is crossed during 09-19 evening or that night.

## 4. Findings

### storage-capacity-1 (critical, live_state, new) - Headroom is ~1.5-2.5 days, not ~4; the monitor ignores the sawtooth
- `scripts/ops/status.ps1:1343-1348`: `diskDaysLeft = round(freeDiskGB / |24h slope|)` from a single
  current sample. 21 / 5.9 = 3.6 -> "4".
- `status.ps1:1365-1372`: if the 48 h slope looks fine the flag is downgraded to a warning with the
  text "treat the short window as a burst".
- Trail rows 331, 235, 139, 41 (04:50 samples) and rows 400, 304, 208, 112 (22:05 samples).
- The estimate is measured from an arbitrary phase of a 13-16 GiB cycle. At 21:20 it reads ~12 GiB
  higher than the level the host will actually reach before the next reclaim.
- `ESTABLISHED_FINDINGS.md:2384-2398` (section 8p, 08-14) still teaches "burst, not steady rate".
  That was true at 157.7 GB free. From 08-14 to 09-07 (27.0 GiB, item-325 line 559) the host lost
  ~130 GB in 24 days. The steady rate is established; 8p is obsolete and biases readers the wrong way.
- Check: the 09-19 04:50 sample should land between 5.5 and 8.5 GiB absent an unexplained step-up.

### storage-capacity-2 (critical, verified_in_code, new) - The only automatic reclaim cannot run at low disk, has no retry, and cascades
- `src/weather/operations/clob_order_book_tiering.py:26` `DEFAULT_MIN_FREE_BYTES = 1 GiB`;
  `:308-328` per candidate `required_free = source_bytes + min_free_bytes`, else
  `skipped_insufficient_headroom`; `:363-366` any such row makes the run `BLOCKED`.
- The gzip it actually needs to write is ~1/23 of the source (~60 MB). The precondition demands
  ~2.2-2.6 GiB. The check is ~40x more conservative than the operation, at exactly the moment the
  operation is the only thing that can save capture.
- `src/weather/operations/clob_raw_tape_tiering.py:81` 8 GiB; `:270-292` same precondition;
  `:286-287` `skipped_projection_tier_pending` when `order_books_long.csv` still exists, so a blocked
  05:00 run also blocks the 06:00 run for the same folders.
- `scripts/ops/clob_tiering_run.ps1:97-103`: the wrapper passes no `--min-free-bytes`, so defaults apply.
  `:83-87` refuses outside 00:30-09:00; `:105-110` exits 0 on a busy lease with no retry.
- `scripts/ops/register_clob_tiering.ps1:61-69, 118`: daily trigger, 31-minute limit, registration is
  rejected if `StartWhenAvailable` is true. One miss = 24 h without ~13.5 GiB.
- With a projected trough of 6-8 GiB tomorrow, a single skipped 05:00 run (busy lease, the pending
  reboot, a hung predecessor) exhausts the disk by mid-morning the same day.
- Partly known: "Tiering 0x0 does not prove reclaim" is recorded (`RETRACTED_AND_FALSE_LEADS.md:288`)
  and surfaced (`status.ps1:1381-1407`). The headroom deadlock and the cascade are not recorded anywhere
  I could find.

### storage-capacity-3 (high, verified_in_code, new) - Capture has no disk-full handling; ENOSPC corrupts canonical tape and crashes both loops
- No match for `disk_usage|ENOSPC|No space|free_bytes|min_free` anywhere under `src/weather/collection`.
  ENOSPC awareness exists only for bot daily rolls (`bot_run_liveness.py:58-81`).
- CLOB writer `src/weather/market/market_microstructure_capture.py:806-828`: `open("a")`, no flush, no
  fsync, no OSError handling. `write_books` (`:835-840`) updates three files non-atomically (summary
  CSV, long CSV, JSONL).
- Snapshot writer `src/weather/collection/snapshot_store.py:2547-2558`: JSON streamed in chunks to an
  append handle, `durable=False` by default. A failure mid-record leaves a partial line with no newline.
- Reader consequences differ and both are bad:
  - `snapshot_store.py:2598-2614` silently skips undecodable lines, so the truncated record *and the
    next record appended onto it* vanish with no signal.
  - `src/weather/market/order_book_tape.py:85-91` raises `ValueError("invalid canonical order-book row ...")`
    on the first bad row, so one truncated line makes that market-day's canonical tape unreadable to
    every consumer until hand-repaired. The tiering job hashes bytes, not JSON, so it would faithfully
    gzip the damaged tape and delete the source.
- Loop behaviour: snapshot loop `snapshot_tracker.py:2034-2047, 2060` writes status, diagnostics and a
  flushed console line with no guard inside `try: while True ... finally:` (no `except`).
  CLOB loop `market_microstructure.py:1768-1785`: the `except Exception` handler itself calls
  `write_clob_loop_status`, `append_clob_diagnostic` and `print(flush=True)`, all on the full volume,
  so the handler re-raises and the process exits. This is the same shape as the 2026-07-12 crash
  described in `HOST_LOAD_POLICY.md:403-408`.
- Supervisor: `supervisor.py:728-763` exponential backoff 120 s doubling to 3600 s, then
  `circuit_open` requiring "an explicit restart". Snapshot budget is 6 per 24 h
  (`snapshot_tracker.py:266-267`), CLOB 12 (`market_microstructure.py:163-164`). Six snapshot
  restarts elapse in ~62 minutes. The 08-09 incident (6/6 budget, 5 h 54 m outage,
  `ESTABLISHED_FINDINGS.md:2132-2136`) shows what that looks like.
- Unknown: whether recovery events can even be recorded on a full disk (the breaker reads the
  diagnostics file). Either way capture is down while the disk is full.

### storage-capacity-4 (high, verified_in_code + doc_claimed, known_open) - Every manual recovery lane is inadmissible at today's free space; nothing else is armed; the plan cannot win
- Archive staging `production_cold_archive_stage_cli.py:35-44, 115-126, 138-152`: 50 GiB reserve;
  20 GiB only for one exact pinned July plan hash; 8 GiB only on 2026-09-10 04:00-13:00 UTC.
  18.5 GiB free fails all three.
- Replay-cache compression `replay_cache_compression_admission.py:32`: 20 GiB + 129 MiB.
- Ordinary heavy work 50 GB (`HOST_LOAD_POLICY.md:330-333`); training 60 GB (`:255-256`).
- Cold-snapshot compression is the only lane still under its floor (8 GiB + 136 MiB,
  `cold-snapshot-compression.md:70-72`), and it will not be after tomorrow's trough. It is "held"
  (item-325 lines 50-52), needs a <=72 h owner-approved request, 00:30-09:00 minus 04:45-06:45,
  and commit < 70%, which has refused repeatedly (item-325 lines 272-274, 409-410, 482-499, 624-627).
- On the unmerged branch `codex/recovery-end-to-end-20260917`,
  `docs/operations/capacity-recovery-exception.md` records a 25 GiB dated exception that expired
  09-16 09:00, a 09-17 successor, "the September 16 failure", and "zero archive payload
  attempts/removals". `git ls-tree` shows `prepare_capacity_recovery_20260916.ps1` and `..._20260917.ps1`
  only; no 09-18 or 09-19 successor exists in git. The lead auditor's live state reports these
  tasks FAILED 09-14 through 09-17 (not independently verified by me; Task Scheduler is off limits).
- `STATE_OF_PLAY.md:36` (09-13): armed recurring work is the two tiering tasks; "Training and further
  archive upload remain disabled". Item-325 line 87: "No continuation is scheduled."
- Arithmetic. Best-ever night: 79.1 GB from 1,679 files in 85 batches (item-325 lines 58-62). Free
  space went 81.6 GiB (09-11) -> 25.9 GiB (09-18) at the same hour, so that result lasted seven
  days. NTFS compress-and-retain yields ~2.0 GB per cold calendar day (14.9 GB for July 1-8,
  12.8 GB for August 6-12), so in steady state it returns ~2 GB/day against 6-8 GB/day of growth.
  Both are one-off; neither changes the slope.
- Effort: 135 of 312 commits across all refs since 09-05 mention archive/storage/capacity/reclaim/
  compress (`git shortlog --grep`), and 32 modules under `src/weather/operations` match
  archive/storage_recovery/compression/tiering/reclaim. Item 325's own acceptance test ("free space
  trends flat or upward across a full week ... with no manual intervention", lines 1082-1083) has
  never been met.

### storage-capacity-5 (high, live_state + doc_claimed, inferred coupling, new) - The pagefile is dynamic and lives on the same volume
- `ls C:/` at audit time: `pagefile.sys` 6,174,015,488 bytes (5.75 GiB), mtime 09-07 19:34. No
  `hiberfil.sys` (hibernation already off, so no free win there).
- `HOST_LOAD_POLICY.md:79` still says "48 GB allocated, commit limit ~63.7 GB" (flagged as a dated
  sample, but it is the only figure in the policy).
- `ESTABLISHED_FINDINGS.md:2101-2103` (08-13): "Disk free fell from 180.6 GB to 146.8 GB while commit
  expanded; 26.2 GB returned immediately after process teardown". `:2120-2123` shows the commit limit
  itself moving (37.05 GB -> 34.51 GB). That is a system-managed pagefile on C:.
- Consequences (inferred):
  1. A single runaway process like 08-13 would now convert 18 GiB of free disk into pagefile within
     minutes and take capture down through ENOSPC. The memory guard's 92% kill threshold is relative
     to a limit that grows with the pagefile, so it does not prevent the disk being eaten.
  2. At zero free the pagefile cannot grow; the commit limit freezes near RAM + 5.75 GiB = ~21.5 GiB on
     a host that routinely sits at 60-78% commit. Allocation failures follow.
  3. Every storage-recovery lane is gated on commit < 70%. With a small pagefile that percentage is
     structurally high, which is consistent with the run of 70-78% refusals since 09-07. Low disk
     and high commit% reinforce each other.
  4. Some of the unexplained trail steps are probably pagefile movement, which means the "net burn"
     is partly memory behaviour, not data.
- I could not read the pagefile configuration or the live commit limit (no shell, and
  `data/logs/memory_commit_guard_status.json` was outside my brief).

### storage-capacity-6 (medium, verified_in_code, new framing) - A built, merged, fail-safe flag worth ~13 GiB of trough headroom was dismissed on the wrong metric
- `config/storage_pressure.json:4` `write_order_books_long_csv: true`.
- `storage_pressure_policy.py:30-38, 54-88`: malformed or missing policy preserves current capture.
- `market_microstructure_capture.py:761-766, 835-840`: the flag only gates the long CSV.
  `:1079` (and 1316, 1456, 1854): the store, and therefore the policy, is constructed per capture
  call, so a config change takes effect on the next iteration without a process restart. (Whether a
  config commit trips the runtime-identity roll detector was not traced.)
- `order_book_tape.py:1-7, 30-36, 54-69`: `order_books.jsonl` is canonical; the long CSV is an
  "analysis projection" that can be rebuilt deterministically from raw records.
- Item-325 lines 843-845 (07-29) rejected the flag because tiering already compresses the projection
  25x, "worth ~0.7 GB/day retained, not ~17 GB/day". Correct for the slope. But the binding constraint
  today is the trough, and the long CSV is ~13.5 GiB of the intra-day decline (it is exactly what the
  05:00 job gives back each morning). Not writing it lifts every trough by ~13 GiB, removes the 05:00
  single point of failure, and removes ~17-18.7 GB/day of writes from the protected window.
- Caveats: flip at a day boundary, otherwise that day holds a partial CSV that the tiering job will
  gzip as if complete (the split-projection hazard, item-325 lines 968-970); confirm no current-day
  consumer requires the CSV (`market_making_preflight.py:26-34` lists it only as one accepted
  artifact key beside the raw tape).

### storage-capacity-7 (medium, doc_claimed + verified grep, known_open) - The only slope-reducing software fix has been blocked for seven weeks while effort went to one-shot offload
- Item-325 lines 817-833: retained snapshots ~8.9 GB/day; gzip of files >5 MB on a closed market-day
  measured 14.3x; warm tier would take retained growth to ~1.3 GB/day; "not gated on the sync split".
- Item-325 lines 917-987 (08-02): 0 of 706 folders eligible; binding blocker is
  `event_day_manifest_missing_or_invalid_json`; "No manifest has been generated since 2026-07-11."
- Grep: no `daily_refresh*.py` module references `event_day_manifest`; no script in `scripts/ops`
  invokes `closed_day_projection_tiering` or manifest generation. Nothing scheduled produces manifests.
- The daily chain does run `closed_market_day_archive` (`daily_refresh_trading_steps.py:891-908`), which
  *adds* Parquet analysis copies; it removes nothing.
- The un-tiered families that make up the residual ~6 GB/day (per-market-day, item-325 lines 821-826):
  `clob_tokens.jsonl` 81 MB (74x), `replay_inputs.jsonl` 54 MB, `variant_predictions.jsonl` 51 MB,
  `order_books_summary.csv` 46 MB, plus explanations, websocket and price-history tapes.
- All scope checkboxes in item 325 (lines 770-791) remain unchecked, including the 07-21 item
  "investigate the 2.5x per-day growth step change".

### storage-capacity-8 (medium, doc_claimed, known_open) - Hardware is the cheapest durable option and the project's own policy already says so
- `HOST_LOAD_POLICY.md:427-430`: "a second physical disk for data\ (separating tape writes from
  OS/pagefile) is the second [best hardware improvement]".
- Item-325 line 711 asserts "the host cannot be grown" with no supporting reason.
  `HOST_LOAD_POLICY.md:102-104` records the 09-10 owner authorization as "using only existing PC
  storage plus private Google Drive", which is a choice of that night, not a recorded standing decision.
- At 6 GB/day a 2 TB volume is ~11 months of raw growth; with the warm tier, ~4 years. It also
  separates the pagefile from the tape, which addresses finding 5 and the 07-12 incident's I/O collapse.
- The cold-archive catalog and restore-cache resolver (`weather.cold_archive_locations`,
  `cold-archive-locations.md`) already give readers a way to find relocated inputs, so a local second
  volume can reuse that work without the 8 MiB/s network path, 300-second jobs, or Drive credentials.

Ranking of realistic options (cost / risk / effect):

| # | Option | Cost | Risk | Effect |
| --- | --- | --- | --- | --- |
| 1 | Owner runs `vssadmin list shadowstorage`; cap or clear shadow copies if large | minutes | none to project evidence | unknown, plausibly 10+ GiB at once |
| 2 | `write_order_books_long_csv=false` at the day boundary | one config line | low; projection is rebuildable | +~13 GiB trough headroom every day; removes 05:00 SPOF |
| 3 | Protect the 05:00/06:00 runs: nothing holds the lease 04:45-06:45, do not reboot across them | none | none | avoids a same-day outage |
| 4 | Second disk, move >30-day market-days with verified copy, resolve through the existing catalog | ~CAD 100-250 + a few days | low-moderate; cold data only | ends the race for a year or more |
| 5 | Warm tier: fix manifest generation, gzip all closed-day families | moderate, roll-sensitive | moderate | slope ~6 -> ~1.3 GB/day plus large one-time reclaim |
| 6 | Finish NTFS compress-and-retain backlog | existing lane | low; commit gate keeps refusing | one-time ~100-200 GB; ~2 GB/day steady |
| 7 | Drive archive campaign | highest complexity; cannot start below 25-50 GiB free | failed four nights; restore-on-demand burden | one-off per dated approval |
| 8 | Prune worktrees | hours | can break deployed execution sources | ~10 GB once |
| 9 | Reduce capture cadence/depth | - | destroys irreplaceable data | last resort only |

### storage-capacity-9 (low, live_state, inferred size) - 200 worktrees are a small, risky, one-off reclaim
- `git worktree list`: 200 entries, all on C: (8 in `C:/tmp`, ~165 siblings under
  `C:/Users/micha/Desktop/github/`, 25 under `scratch/w/`, 2 under `.claude/worktrees/`).
- One sampled sibling (`weather-bulk-cold-archive-20260909`) has no `venv`; it does have its own
  `data/`, `scratch/` and a nested `weather/` directory whose sizes I did not measure. `C:/tmp` holds
  one stray `clob_v2_venv`.
- At ~50 MB of tracked files each, checkouts total roughly 10 GB: about a day and a half of growth.
- Two worktrees are `locked` (`weather-watchdog-deployed-aa99048`, `weather-overnight-watchdog-20260906`),
  and item 325 repeatedly binds scheduled tasks to "isolated execution checkouts". Removing a worktree
  that a task action points into breaks production. Check Task Scheduler actions first.
- Unknown and potentially larger: staged archive spools and "pending originals" retained on production
  under `scratch/` (item-325 lines 75-76, 85-87). Item 325 records 10.2 GB of duplicate downloads
  cleaned from the workstation but gives no figure for what remains on this host.

### storage-capacity-10 (low, verified, new) - Capacity documentation is stale or split across unmerged branches
- `active-backlog.md:59` and the item-325 title still read "QUALIFICATION RESERVE RECOVERED" at 18.5 GiB free.
- Master has no commit since 09-13. All storage work from 09-14 to 09-17 (exceptions, failures,
  the "plain" campaign) exists only on unmerged branches whose copy of item 325 is based on a 09-10
  snapshot and lacks master's 09-11 and 09-13 sections. No single document tells the current story.
- The unmerged `capacity-recovery-exception.md` records a 09-15 owner approval of **unencrypted**
  upload for a 1,066-file selection, while master's item-325 lines 1011-1013 still say raw capture
  "must never be uploaded unencrypted" because payloads can embed provider keys. This is an owner
  decision, but the reversal and its reasoning are not visible on master.
- `HOST_LOAD_POLICY.md:79, 431-433` pagefile and "6-7 days" figures; `ESTABLISHED_FINDINGS.md` section 8p.
- `data/alerts/host_health_alerts.jsonl` is 32.7 MB and outside the 64 MiB managed-rotation set. Trivial
  in bytes; it is the same unbounded-sidecar shape that caused the 08-09 outage.

## 5. Direct answers to the brief

**Growth drivers by directory (docs and code only).** `data/snapshots` dominates: 345.6 GB and 3.53M
files on 07-21, 74% of bytes (item-325 lines 694-704). Gross daily writes are ~17-18.7 GB of
`order_books_long.csv` plus ~3.2 GB of `order_books.jsonl` plus ~6 GB of other per-market-day families.
After the two tiering jobs the retained rate is ~6 GB/day, which matches the observed net slope.
`data/taker_runs` 47.8 GB (taker paused 08-07, 19.2 GB pruned). `data/backtest` 43.6 GB, of which
`replay_cache` 32.3 GB is not evictable (item-325 lines 846-850) and 10.67 GB is loose root output.
`data/archive/closed_market_days` grows daily with Parquet copies. Execution tape ~3 MB/day.

**Any automatic expiry or deletion?** Only gzip-then-delete of two file families on closed days
(05:00 and 06:00). Log rotation renames and never deletes (`HOST_LOAD_POLICY.md:412-426`). The taker
counterfactual prune is inert because the taker is paused (`data-retention-policy.md:26-34`). There
is no age-based expiry of anything. Everything else is compress-and-retain or one-shot
archive-then-reclaim under dated owner approval.

**What happens at zero?** See findings 2, 3 and 5: reclaim deadlocks first (~2.5 GiB), then truncated
JSONL/CSV rows, a fail-closed canonical reader for the affected market-days, both capture loops
exiting through their own status writes, supervisor breaker after ~1 hour for snapshots, and a frozen
commit limit. Strength worth noting: forecast payload CAS blobs are published atomically after fsync
(`HOST_LOAD_POLICY.md:173-176`), and bot daily rolls have an explicit 1 GiB preflight and `disk_full`
terminal state.

**Is anything armed that acts before exhaustion?** Only the two tiering tasks, which are already in the
net burn, and the monitor, which only alerts (`status.ps1:1301-1302`: flag < 25 GB, warn < 60 GB).

**Can the current plan win?** No. See finding 4.

## 6. Strengths

- Tiering verifies sha256 and line count of the decompressed payload before deleting, re-checks 2 h
  writer quiescence at apply time, and structurally excludes split days
  (`clob_order_book_tiering.py:265-288, 318-328`).
- Disk safety was deliberately decoupled from chain health into its own scheduled job with a durable
  status file, and the monitor refuses to treat Scheduler 0x0 as proof of reclaim
  (`clob_tiering_run.ps1:1-29`, `status.ps1:1381-1407`).
- The free-space trail costs one `Get-PSDrive` call and explicitly avoids walking `data/`
  (`status.ps1:1318-1322`).
- "Never delete unverified" was honoured under pressure: 79.1 GB reclaimed only after independent
  download and full restore, 27.7 GB of lossless NTFS compression with before/after hashes, failed
  attempts retained and never relabelled (item-325 lines 10-32, 56-66, 378-417).
- `storage_pressure_policy.py` is a well-built fail-safe lever; it simply has not been used.

## 7. Not covered

- Task Scheduler state, pagefile configuration, live commit limit, VSS shadow-storage usage (no shell).
- Actual sizes of anything: `data/` subtrees, `scratch/`, `.git`, worktree `data/`/`scratch/`, staged
  archive spools, `System Volume Information`.
- `MORNING_BRIEFING.md`, `OPERATING_SCHEDULE.md`, tiering status JSONs and the memory-guard status
  (in `data/`, not named in my brief). I relied on the lead auditor's summary for failed-task state.
- Disk-full behaviour of the execution-tape producer, maker paper run writers and the settlement chain.
- Whether a config-only commit trips the runtime-identity roll detector.
- Workstation capacity and Google Drive quota.
- Whether any unencrypted upload actually ran on 09-16/09-17.

## 8. Open questions for the owner

1. What does `vssadmin list shadowstorage` report for C: right now?
2. Is the pagefile system-managed? What is the current commit limit?
3. Why "the host cannot be grown"? Is a USB or internal second disk actually impossible?
4. How many GB of staged archive spools and already-uploaded "pending originals" sit on this host?
5. What are the +13.8 GiB (09-17 18:50) and +15.8 GiB (09-16 03:20) step-ups?
6. Is anything armed for tonight's 00:30 window that is not in git?
