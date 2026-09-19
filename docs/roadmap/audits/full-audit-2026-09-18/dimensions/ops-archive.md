# Audit dimension: Operations B - archive, tiering, storage recovery, integration attempts, doc transactions

Key: `ops-archive`. Auditor run: 2026-09-18 (production host, protected near-close window).
Read-only. No project file was modified; the only write is this report.

## 1. Scope actually covered

Files I opened and read (fully unless noted):

Python, `src/weather/operations/`:
- `production_cold_archive_stage_cli.py`, `production_cold_archive_stage.py`,
  `production_cold_archive_reclaim_cli.py`, `production_cold_archive_transfer_core.py`
  (lines 20-573), `production_cold_archive_transfer.py` (reserve lines only)
- `cold_archive_reclaim.py`, `cold_archive_native_removal.py`
- `cold_snapshot_compression.py`, `replay_cache_compression_admission.py`
- `storage_recovery_night.py`, `storage_recovery_night_contract.py`
- `clob_raw_tape_tiering.py` (1-400), `closed_day_projection_registry.py` (eligibility lines)
- `cleanup_preflight.py` (153-285), `capture_resource_gate.py` (constants, loop specs)
- `documentation_transaction.py`, `agent_docs_audit.py` (108-182, 340-449)
- `workstation_cold_archive_stage.py` (secret handling: 120-150, 455-536)
- `ntfs_file_compression.py`, `experiment_executor.py` (constants only)

Other source: `src/weather/cold_archive_locations.py`, `src/weather/execution_host.py`,
`src/weather/collection/snapshot_tracker.py` (heartbeat/sleep lines only),
`src/weather/reporting/scorecards/captured_input_parity_evidence.py` (one consumer spot-check).

PowerShell: `scripts/ops/production_cold_archive_run.ps1` (full),
`scripts/ops/workload_admission.ps1` (lines 1-1448 of 2050),
`scripts/ops/bounded_worktree_test_suite.ps1` (270-330).

Docs: `docs/operations/production-cold-archive-staging.md`, `cold-archive-locations.md`,
`INTEGRATION_ATTEMPT_RUNBOOK.md`, `STATE_OF_PLAY.md`, `HOST_LOAD_POLICY.md` (selected),
`docs/roadmap/items/item-325-...md` (lines 1-991 of 1392), `active-backlog.md` (grep).

Git (whitelisted commands only): history of the archive CLIs; `master..codex/recovery-end-to-end-20260917`
commit list; `git diff --stat master...<branch>`; `git show <branch>:<path>` for the branch versions of
`production_cold_archive_stage_cli.py`, `cold_archive_plain.py`, item 325; `git branch --contains`.

Live state (non-recursive `ls` of single directories plus five small JSON receipts, all under
`scratch/`, none under `data/`):
`scratch/archive_plain_campaigns/plain-20260913-now1/run/result.json`,
`.../plain-20260916-cap150b/run/{result,wrapper-result,child-0002}.json`,
`.../plain-20260917-cap150/run/{result,wrapper-result}.json`, and directory listings of
`scratch/production_cold_archive*`.

I did NOT read `data/alerts/MORNING_BRIEFING.md` or anything else under `data/`; my brief did not
grant it. The "21 GB free, ~5.9 GB/day, tasks FAILED 09-14..09-17" figures are the lead auditor's.

## 2. Method

1. Enumerated the package, then grepped reserve/headroom constants across `operations/*.py`.
2. For each lane, read the admission function and traced one call path end to end from the
   PowerShell wrapper to the Python guard to the mutation.
3. Compared master with the branch that the on-disk receipts name as `source_git_sha`.
4. Read the actual failed-campaign receipts for 09-13, 09-16, 09-17 rather than inferring causes.
5. Sized the machinery with `git diff --stat <empty-tree> HEAD -- <paths>`.

## 3. The hypothesis: is there a capacity deadlock?

**Answer: partly yes, and it is sharper today than on the nights that failed.**

### 3.1 Reserve constants per lane (master unless noted)

| Lane | Reserve | Citation | Admissible at 21 GB (19.56 GiB)? |
| --- | --- | --- | --- |
| CLOB projection gzip tiering | 1 GiB + source bytes | `clob_order_book_tiering.py:26` | yes |
| CLOB raw-tape gzip tiering | 8 GiB + source bytes | `clob_raw_tape_tiering.py:81, 269-292` | yes |
| Cold snapshot NTFS compression | 8 GiB + 2x64 MiB + 8 MiB | `cold_snapshot_compression.py:37, 42-49` | yes (disk only) |
| Storage recovery inventory | 8 GiB + output + 2 MiB | `storage_recovery_inventory_cli.py:33` | yes |
| Replay-cache NTFS compression | 20 GiB + 2x64 MiB + 1 MiB | `replay_cache_compression_admission.py:32, 35-41` | **no** |
| Cold archive stage | 50 GiB + 16 MiB + worst-case output | `production_cold_archive_stage_cli.py:35, 44, 115-126` | **no** |
| Cold archive transfer/upload/download | same selected reserve | `production_cold_archive_transfer.py:160, 176-177, 199` | **no** |
| **Cold archive RECLAIM (the delete that frees space)** | same selected reserve, `output_reservation=0` | `production_cold_archive_reclaim_cli.py:125-131` | **no** |
| July 16-31 plan exception | 20 GiB + 16 MiB, one exact plan SHA | `production_cold_archive_stage_cli.py:36-39, 143-145` | **no** (19.56 < 20.02) |
| Sept 10 overnight exception | 8 GiB, only 2026-09-10 04:00-13:00 UTC | `production_cold_archive_stage_cli.py:40-43, 147-151` | expired |
| Branch `cap150` exception | 25 GiB + 2 GiB + 300 MiB = 27.29 GiB; nights hard-coded to 09-16 and 09-17 | branch `production_cold_archive_stage_cli.py` `capacity_recovery_reserve` | **no**, and expired |
| Bounded full test suite (integration attempts) | 50 GiB on every involved volume | `bounded_worktree_test_suite.ps1:288-312` | **no** |
| Experiment executor | 50 GiB | `experiment_executor.py:60` | **no** |
| Capture resource gate (heavy work) | 30 GiB and 30 days of growth headroom | `capture_resource_gate.py:34-35, 464-491` | **no** |
| Training window | > 60 GB | `HOST_LOAD_POLICY.md:255-256` | no (also disabled) |

### 3.2 What that means

- The lane that *deletes originals and therefore frees the most space* refuses when free space is low.
  `production_cold_archive_reclaim_cli.py:125` takes the reserve from `load_plan_with_reserve`, and
  `:131` calls `staging.check_resources(output_reservation=0, source_reserve_bytes=reserve, ...)`.
  `production_cold_archive_stage_cli.py:120-125` then blocks with `archive_disk_reservation_unmet`
  when `free_disk < reserve + 16 MiB`. A delete needs no output space, yet it carries the same
  50 GiB floor as a stage.
- Item 325 already records one instance of exactly this: "The early reclaim attempts refused before
  deletion because the six-GiB disk reserve was unavailable" (`item-325...md:182-183`).
- The integration path is coupled to the same number. `Assert-SuiteDiskHeadroom`
  (`bounded_worktree_test_suite.ps1:288-312`) throws below 53,687,091,200 bytes, so at today's free
  space no immutable integration attempt can pass its full suite, so nothing (including the
  reliability candidate and any settlement-hole repair) can reach master by the sanctioned route.
- It is **not** a total deadlock. The two scheduled gzip tiering jobs and the NTFS compress-and-retain
  lane remain disk-admissible. They are lossless and in place, and they are the only things still
  standing between the host and a full disk.
- Unit caveat: if the briefing's "21 GB" is really GiB, the 20 GiB July exception and the replay-cache
  lane clear by under 1 GiB. That plan is from 09-09 and the campaign moved on to other plan SHAs,
  so it does not change the conclusion.

### 3.3 But the nights of 09-16 and 09-17 did NOT fail on disk

I read the receipts. Both failed on brittle guards with ample disk:

- `plain-20260916-cap150b/run/result.json`: `FAILED_RETAIN_AND_INSPECT`, reason
  `Child failed: conditional-retained-compression`, `completed_batches: []`,
  `actual_free_disk_bytes: 26972418048`. Wrapper: started 04:30:00Z, completed 04:33:42Z, deadline 08:42Z.
  **3 min 42 s of a 4 h 12 min window used.**
- `plain-20260917-cap150/run/result.json`: reason `Independent download proof is stale or
  future-dated`, phase `copy-receipt`, `completed_batches: []`, `actual_free_disk_bytes: 34891943936`,
  target 150,000,000,000. Wrapper: 04:30:01Z to 04:37:16Z. **7 minutes used, zero bytes reclaimed.**
  The repair committed at 12:17 that day (`56fe1ead3`) documents the cause as a proof timestamp a few
  seconds ahead of the controller clock, i.e. clock skew between the two PCs.
- The approved nights are literals in source on the branch:
  `approved_nights = {"2026-09-16T13:00:00Z": 16, "2026-09-17T13:00:00Z": 17}`. There is no code path
  that admits a recovery night on 09-18 or later without another commit.

So the accurate statement is: the proximate cause of the zero-yield nights was fail-closed
brittleness; the disk reserve is what now prevents a retry. Each lost night cost roughly 6-7 GB.

## 4. Findings

### ops-archive-1 (critical, known_open): every delete-capable and merge-capable lane is now inadmissible, and the dated approvals have expired

See section 3. Evidence: the table in 3.1; live receipts in 3.3.
Impact: with ~4 days of headroom, the tools built to recover space cannot be started, and no code
fix can be merged through the sanctioned path, because both share a 50 GiB floor. A full disk stops
capture, which is the project's only irreplaceable asset (`item-325...md:711-716`).
What is new versus what the project already records: disk pressure is known and tracked. What I could
not find recorded on master is (a) that reclaim carries a stage-sized reserve, (b) that the suite floor
now blocks all integration, and (c) that the recovery authority is a pair of date literals that lapsed.
Recommendation: owner decision, tonight, on a standing low-disk rule rather than another dated
exception: reclaim (pure delete, `output_reservation=0`) should be admissible at a small fixed floor;
and the scheduled gzip tiering plus NTFS compression should be confirmed armed and unblocked.

### ops-archive-2 (high, new): the code that deleted ~80.8 GB of canonical originals is not on master, and master's state documents are contradicted by receipts on this disk

- `scratch/archive_plain_campaigns/plain-20260913-now1/run/result.json` records
  `source_git_sha 7b9681883e41...`, two completed batches (38 + 32 files deleted), and canonical
  progress `deleted_files: 1749`, `reclaimed_allocated_bytes: 80816955392`, `sequence: 87`,
  updated 2026-09-13T23:11:38Z (19:11 Toronto).
- `git branch --contains 7b9681883` lists only `codex/archive-immediate-20260913`,
  `archive-next50-20260914`, `capacity-150gb-20260915`, `recovery-end-to-end-20260917`. Not master.
  `8c6826d7c` (the 09-17 run) is only on `codex/recovery-end-to-end-20260917`.
- `git diff --stat master...codex/recovery-end-to-end-20260917`: 95 files, +9,898/-335, including
  `cold_archive_plain.py`, seven `cold_archive_campaign*.py` modules, `production_cold_archive_copy.py`,
  `workstation_cold_archive_{backup,cleanup,transfer}.py`.
- `STATE_OF_PLAY.md:21, 31` still says uploads are paused and reports 79,105,806,336 bytes /
  1,679 files / 85 batches. `active-backlog.md:59` says "QUALIFICATION RESERVE RECOVERED; UPLOADS PAUSED".
- The branch adds an **unencrypted** lane: `cold_archive_plain.py` requires
  `uploaded.get("payload_encryption") == "none"` and its docstring says "No encryption or key custody
  applies". Master has no such code and `docs/operations/` has no mention of it (grep for
  `payload_encryption|cold_archive_plain|plain_upload` in `src/weather` returns nothing). Item 325's own
  design argued encryption was structural, because payloads can embed provider API keys
  (`item-325...md:884-890`).
- The mechanism that permits this: `production_cold_archive_run.ps1:91-94` checks only that the
  worktree HEAD equals `-ExpectedSourceTip` and that the tree is clean. It does not require the tip to
  be on `origin/master`, to have a PASS integration receipt, or to be reviewed by anyone.

Impact: the most destructive code in the project is exempt from the exact-tip suite and guarded-merge
gate that every other change must pass. An agent reading the canonical docs gets a wrong count, a
wrong "paused" status and no knowledge that a plaintext lane exists. If those branches are retired
(46 were retired on 08-11), the verification and restore tooling for the plain archives goes with them.
Mitigation worth stating: plain archives are ordinary `.tar.gz`, so standard tools can restore them.

### ops-archive-3 (high, new): fail-closed with no retry means one small bug burns an entire recovery night

Pattern, with sources:
- 09-08: heartbeat age of -0.007398 s refused a batch (`item-325...md:532-535`).
- 09-08: registrar compared `PT4H14M` to `PT254M` as text (`item-325...md:354-360`).
- 09-08: 15,000-entry directory limit ended an inventory as PARTIAL (`item-325...md:278-283`).
- 09-15: commits `08f7e322d` (UTF-8 BOM in approval metadata) and `c91a2536a` (deadlines compared as strings, not instants).
- 09-16: compression prerequisite child failed at 3 min 42 s (receipt above); commit `368adf4fc` "retry bounded capture status reads".
- 09-17: clock-skew freshness check failed at 7 min (receipt above); commit `56fe1ead3`.

Each failure "spends" the namespace, stops the campaign, and needs a commit, a re-qualification, a new
hard-coded approval and newly registered one-shot tasks. On a host losing 6-7 GB/day that is a day of
runway per defect. The safety intent is right for *deletes*; it is mis-applied to idempotent,
pre-mutation checks (a freshness comparison before any byte has moved) where a bounded retry is safe.

### ops-archive-4 (high, known_open): there is no recurring retention service; the inflow is structurally unaddressed and the disk crisis recurs

- Docs record the same emergency repeatedly: 223 GB free and ~11 days (07-21, `item-325...md:691-709`),
  146 GB and ~9 days (07-29, `:817`), 151 GB and ~14 days (08-10, `clob_raw_tape_tiering.py:9-13`),
  27 GiB (09-07, `:559`), 8.7 GiB low point (09-08, `:680`), 67.6 GiB (09-13, `:36-37`), ~21 GB (09-18).
- The only recurring reclaim is two gzip jobs covering two file families. The registry hard-asserts that
  nothing else may be tiered: `closed_day_projection_registry.py:315-319`,
  "only order_books_long may be eligible".
- The project measured on 07-29 that compressing the remaining families in place would take retained
  growth from ~8.9 to ~1.3 GB/day and "is not a deletion" (`item-325...md:828-833`).
- The lane that does compress those families (`cold_snapshot_compression`) is attended, one-shot,
  capped at 64 MiB per file (`cold_snapshot_compression.py:96`), excludes the tiering filenames
  (`storage_recovery_night_contract.py:26`) and is currently "held" (`item-325...md:50`).
- Item 325 itself says it "remains PARTIAL for a durable recurring retention service" (`:85`).

### ops-archive-5 (medium, new): master's storage lanes refuse most of the time because the snapshot loop does not heartbeat while it sleeps

- `replay_cache_compression_admission.py:27` sets `MAX_HEARTBEAT_AGE_SECONDS = 180` and `:87-94` applies
  it to all three loops, including `snapshot`.
- `snapshot_tracker.py:2060` writes status once, then `:2063-2071` sleeps;
  `sleep_until_due_or_triggered_work` (`:1300-1317`) never touches `last_heartbeat`. Heartbeats are
  written only at `:1539, 1680, 1911, 1939, 1948`, all inside an iteration.
- The default sleep is `interval_minutes*60 - elapsed` (`:2050`), and
  `bounded_worktree_test_suite.ps1:317-319` states the snapshot "normally sleeps for almost its
  10-minute cadence" and uses a 720 s bound for that reason.
- Every guard in `cold_snapshot_compression.py:279-291` re-checks each second and raises on
  `capture_unhealthy:snapshot`. `storage_recovery_night.py:176-184` waits at most 300 s then stops
  `RESOURCE_LIMITED`.

A fix exists only on the unmerged branch (commit `659dbbb65`, "Recognize bounded completed snapshot
sleeps in archive admission"; I read the message, not the diff). So master's version of these lanes is
known-defective relative to what actually runs.

### ops-archive-6 (medium, new): proportionality

- 42 storage/archive/tiering/retention modules on master: **23,761 lines** (`git diff --stat` against the empty tree).
- 47 matching test and script files: **16,589 lines**. Branch adds **9,898** more across 95 files.
- 61 master commits in the last 30 days touch these paths (about 23% of 266), plus ~50 on the branch.
- Outcome: 80.8 GB archived-and-deleted (target 100 GB, not reached), 14.9 GB + 12.8 GB NTFS
  compression. At 6-9 GB/day that bought about two weeks.
- Comparison: the two gzip tiering modules total ~1,100 lines and reclaim 12-17 GB on an ordinary night
  (`item-325...md:637-642`).
- `closed_day_projection_tiering.py` (1,952 lines) "has never been able to emit an action" as of the
  08-02 dry run (`item-325...md:919-927, 972-974`); no ops script invokes it. I did not verify whether
  that changed after 08-02.
- Reclaim counters measure NTFS allocation, not free space, and the docs say Windows shadow storage
  "absorbed much of the capacity benefit" (`item-325...md:34-37`). Free space fell from 72.6 GB
  (09-13 02:16) to 27.0 GB (09-16 00:33), about 14.7 GB/day, which is 2.5x the briefing's burn rate.
  I could not establish why (open question 1).

### ops-archive-7 (medium, known_open): the approval chain proves consistency, not authority

- `approved_by` is any non-empty string up to 128 chars (`production_cold_archive_stage_cli.py:64-65`,
  `production_cold_archive_reclaim_cli.py:49-50`).
- The source review is a JSON of PASS flags that the code cannot check against reality
  (`cold_archive_reclaim.py:115-144`); the docs concede "synthetic PASS flags are not production proof".
- Key custody is a JSON with `confirmed: true` (`cold_archive_reclaim.py:215-220`).
- The "canonical cleanup preflight" gives `canonical_evidence` an unconditional PASS
  (`cleanup_preflight.py:255-256`), and tiering approves itself
  (`clob_raw_tape_tiering.py:306-309`, `approved_by: "weather.operations.clob_raw_tape_tiering"`).

For a one-owner project whose agents write every one of those files, this is mistake-prevention, which
is a legitimate goal. It should not be described, or relied on, as owner authorization.

### ops-archive-8 (low, known_open): documentation transaction is permanently overdue, and the docs audit cannot see staleness

- `begin_transaction` sets `due_at_local` only on creation (`documentation_transaction.py:167-186`);
  appending integrations never extends it, so a multi-night stack reads `overdue: true` indefinitely
  (`:229`). `STATE_OF_PLAY.md:40` confirms ten integrations pending and not cleared.
- `complete_transaction` runs pytest and two Python audits with no lease or admission
  (`:303-332, 448`). Small, but it is heavy-ish work outside the host's own rules.
- `agent_docs_audit.audit_repo` (`agent_docs_audit.py:350-425`) checks presence, links, trigger phrases
  and tables. Nothing checks that `STATE_OF_PLAY.md`'s date is recent, so a five-day-old state file
  during a disk emergency passes.

### ops-archive-9 (low, new): key custody and published locations

`item-325...md:192-203` publishes, in a Git-tracked file pushed to origin, the private Drive folder
ID, the Drive object ID of the recovery-keys JSON and its SHA-256 (values deliberately not repeated
here). These are identifiers, not credentials. The more substantive point is that the recovery keys
live in the same Drive remote as the ciphertext they unlock, so the custody flag `outside_both_pcs`
is satisfied while encryption adds little against that one account. Basis: doc_claimed.

### ops-archive-10 (info, known_accepted): off-host copies

Backups and the mirror are an owner-closed decision; reported once. Relevance here: ~80.8 GB of
originals classed "irreplaceable" now exist only in Drive, plus whatever the frozen 08-12 workstation
mirror still holds for July (inferred, not verified).

## 5. Checks that came back clean (strengths)

1. **Delete-after-verify is genuinely careful.** `cold_archive_native_removal.py:44-62` opens with share
   mode 0 and confirms the final path by handle; `:64-83` hashes through that same handle; `:85-93`
   deletes via `SetFileInformationByHandle` with no path-based fallback. `cold_archive_reclaim.py:329-345`
   checks marker, native identity, allocation and full SHA-256 for every file before the first removal,
   and journals intent before deleting (`:380-383`).
2. **rclone invocation is safe.** `production_cold_archive_transfer_core.py:118-133`: `shell=False`, list
   argv, a four-command allowlist, `--ask-password=false`. Remote name, folder ID and object key are
   regex-validated (`:31-32, 107-108, 215-216`). The config password travels only in the child
   environment, never argv; ambient `RCLONE_*` is stripped and the variable is popped in `finally`
   (`:448-450, 567-571`). Copies use `--immutable`, `--max-transfer` with `--cutoff-mode HARD` (`:236-241`).
3. **Secrets at rest use DPAPI** with buffers zeroed (`workstation_cold_archive_stage.py:457-536`).
   Residual: `secret.text()` returns an immutable `str` that cannot be wiped. Inherent to Python.
4. **Gzip tiering verifies before it deletes**: SHA-256 and line count over the decompressed stream
   (`clob_raw_tape_tiering.py:221-249`), with writer-lock and quiet checks repeated at apply time (`:283-289`).
5. **Archived inputs cannot silently look empty** to archive-aware readers:
   `cold_archive_locations.py:29-40, 236-247` raise a typed `RuntimeError`.
6. **Wrapper honesty under failure**: a killed reclaim reports `deleted_files: null`,
   `reclaim_state: UNKNOWN` rather than zero (`production_cold_archive_run.ps1:125-130, 270-273`), inside a
   kill-on-close Job with a 300 s deadline and 384 MB ceiling (`:148-163`).
7. Successful batches do clean their staged payloads (`p11k00071s1/stage` holds only JSON), so the
   three-copies-per-chunk design is not leaking space on the success path.

## 6. Not covered

- `verified_cold_archive.py`, `bulk_cold_archive_crypt.py`, `cold_archive_catalog.py`,
  `workstation_cold_archive_restore.py`, `cold_archive_spool_cleanup.py`, `cold_archive_cache_cleanup.py`,
  `cold_archive_recovery_publication.py`, `storage_recovery_inventory.py`,
  `storage_recovery_batch_plan.py`, `storage_recovery_night_{evidence,steps}.py`,
  `replay_cache_retention*.py`, `closed_day_projection_tiering.py`, `closed_market_day_archive.py`,
  `event_day_manifest.py`: not opened beyond greps.
- The eight integration-attempt PowerShell scripts: I read the runbook, not the scripts.
- `workload_admission.ps1` lines 1449-2050 (lease acquire/release and poisoning).
- Tests: none opened.
- Whether the 05:00 and 06:00 tiering tasks actually ran on 09-14..09-18 (status lives in `data/logs`).
- The branch's diffs beyond the three files named above.

## 7. Open questions for the owner or lead

1. Why did free space fall ~45 GB between 09-13 02:16 and 09-16 00:33? Candidates: shadow-storage
   regrowth, skipped tiering (the lease was busy during qualification attempts), 200 worktrees and
   `scratch/` growth. Nothing I was permitted to read settles it.
2. What is the true archive counter now? The last value I saw is 80,816,955,392 bytes at
   2026-09-13T23:11Z, but `scratch/production_cold_archive` shows staging activity at 21:56-21:59 that night.
3. How many of the 87+ batches went through the plaintext lane, and which file families?
4. Is `origin` a private repository?
5. Was the 09-13 19:05-21:59 archive activity inside the protected 18:00-00:30 window covered by the
   "owner immediate" exception (commit `9205b3fb3`)? I assume yes and have not raised it as a finding.
