# Gap audit: per-date cause and recoverability of the unsettled dates, and what holds the raised memory baseline

Dimension key: `gap-chain-deferral-evidence-and-memory-root-cause`
Auditor session: 2026-09-19 ~03:00 America/Toronto, on the live 16 GB production host. Read-only.
Health grade for this dimension: **D**

---

## 0. Bottom line (read this first)

1. **The "raised commit baseline" is mostly a shrunken denominator, not grown consumers.** The live guard
   status at 2026-09-19 03:03 shows a commit LIMIT of **22,013 MB** with **11,762 MB** used = 53.4 %.
   The policy that set the 70 % gate was written against a **63.7 GB** limit (48 GB pagefile). The same
   11.76 GB is 18 % at 63.7 GB and 33 % at the 34.5 GB limit recorded on 2026-08-13. A ~30-point rise
   appears with zero growth in any process. The 70 % gate now trips at **15.4 GB** of commit on a 16 GB
   machine, leaving ~3.6 GB of headroom over an idle 03:00 baseline - less than the project's own two
   snapshot-capture children are allowed to commit (2 x 1,792 MiB).
2. **Only 2 of 10 dates have a provable blocker.** 09-17 is proved (deferred at `ingest_quality_gate`,
   sole blocker `host_commit_above_limit` 72.511 %, with 6.4 GiB RAM free and all three loops healthy).
   09-16 is proved to have completed the WU restore 12/12 and then stopped before finalize. For the other
   8 dates the blocker code is **unrecoverable from retained state**: the status file is overwritten daily,
   the progress ledger drops deferral blockers, and nothing archives a deferral receipt.
3. **What IS provable for all 8:** no isolated child was ever admitted on those run days (no per-run child
   folder exists) and no per-date WU restore receipt exists. Stage A ended at or before the FIRST isolated
   step's admission - an audit step (`ingest_quality_gate`) that sits in front of the settlement-truth steps.
4. **All 10 dates are still recoverable; no hard deadline was found.** On 2026-09-04 the same backfill path
   settled 70-day-old dates 12/12 in ~22 minutes each. 09-16 needs no WU fetch at all. Total serial cost
   is ~3.5 h, inside one 00:30-09:00 window. The real deadlines are soft: the alarm's 14-day lookback
   (09-04 has ALREADY silently fallen out of the briefing without being settled) and disk exhaustion
   (10.3 GB free, ~1.5-2 days).
5. **No recovery has been attempted for any of the 10 dates.** Newest receipt in `data/ops/chain_recovery/`
   is 2026-09-04 08:47. The briefing has printed the exact command every night for 14 nights.
6. **Smallest fix that gives settlement a retry:** bounded wait-and-recheck inside the existing admission
   (one function), plus widening the WU restore from `[target, target]` to a lookback window. Because
   finalize already re-processes every historical folder on every run, the lookback alone makes every
   successful chain day heal all earlier holes.

---

## 1. Scope, method, constraints

Read (code): `src/weather/operations/daily_refresh.py` (514-530, 560-890, 960-1815),
`daily_refresh_resources.py` (whole), `daily_refresh_status.py` (20-90), `daily_refresh_steps.py` (whole),
`daily_refresh_source_steps.py` (160-310, 643-678), `daily_refresh_settled_day.py` (148-156),
`settlement_hole_check.py` (whole), `long_job_guard.py` (grep only: no admission logic inside
`run_isolated_subprocess`), `reporting/daily/daily_progress_ledger.py` (275-365),
`backtesting/settled_days.py` (68-96), `market/market_day_labels.py` (24-47), `market/market_registry.py`
(395-424), `market/execution_tape_capture.py` (100-178), `collection/snapshot_tracker.py` (300-326,
660-705, 1530-1700, 1995-2064), `collection/collection_health.py` (1255-1335),
`scripts/ops/daily_refresh.ps1`, `register_daily_refresh.ps1` (1-170), `settlement_backfill_one.ps1`,
`chain_recovery_run.ps1`, `memory_commit_guard.ps1` (whole), `docs/operations/HOST_LOAD_POLICY.md`,
`ESTABLISHED_FINDINGS.md` (200-255, 2085-2124), `tests/operations/test_memory_commit_guard_script.py` (grep).

Read (live state, each `ls -l` first, all under 2 MB, none a live-appended log/jsonl):
`data/backtest/daily_refresh_status.json` (131 KB, mtime 09-18 09:34),
`data/logs/memory_commit_guard_status.json` (592 B, 09-19 03:03),
`data/alerts/MORNING_BRIEFING.md` (09-19 02:50), `data/alerts/OPERATING_SCHEDULE.md`,
immutable receipts: `data/alerts/settlement_backfill_2026-06-26.json`, `data/ops/chain_recovery/last_run.json`,
`data/ops/chain_recovery/refresh-20260904-082552-096-19396.json` (targeted ranges),
`data/backtest/public_wu_settlement_restore_2026-09-16.json` (first 40 lines).
Directory listings (non-recursive, single directory): `data/alerts/`, `data/ops/chain_recovery/`,
`data/backtest/daily_refresh_step_children/`, plus `ls -l` of 15 exactly-named
`public_wu_settlement_restore_<date>.json` files and the two guard log files (size/mtime only, NOT opened).

Not opened by rule: `data/logs/memory_commit_guard.log`, `memory_commit_guard_history.jsonl`,
`data/backtest/daily_progress_ledger.{csv,jsonl}`, any settlement ledger, any tape. No python, no ps1, no
process or scheduler queries were run.

Note on the brief: the data/ allowance was labelled "requested (lead to confirm)". I treated the four
listed snapshot files plus immutable per-run receipts as allowed, as the brief's own text states, and
stayed inside that list.

---

## 2. Per-date table (Question 1)

Stage A step order (`daily_refresh_steps.py:102-108`): 1 `reanalysis_recent_refresh` (in-process),
2 `ingest_quality_gate` (**isolated - first admission**), 3 `event_metadata_validation` (in-process),
4 `public_wu_settlement_restore` (isolated), 5 `market_day_labels_finalize` (in-process).

Two retained per-run artefacts make a partial reconstruction possible:
- `data/backtest/daily_refresh_step_children/<run_id>/` is created only AFTER an isolated child is
  admitted (`daily_refresh.py:685-689` -> `daily_refresh_resources.py:449-459`). No folder for a run day
  means no isolated child was admitted that day.
- `data/backtest/public_wu_settlement_restore_<target>.json` is written only when the WU step finishes
  (`daily_refresh_source_steps.py:297-301`).

| Target date | Run day | Child folder for run | WU receipt for target | Where Stage A ended | Blocker | Grade |
| --- | --- | --- | --- | --- | --- | --- |
| 09-03 (control) | 09-04 | yes (mtime 10:42) | yes (09:44) | ran on | - | settled |
| **09-04** | 09-05 | **none** | **none** | at/before step-2 admission | unknown code | step: proved. blocker: **unknown** |
| **09-05** | 09-06 | none | none | same | unknown | same |
| **09-06** | 09-07 | none | none | same | unknown | same |
| **09-07** | 09-08 | none | none | same | unknown | same |
| **09-08** | 09-09 | none | none | same | unknown | same |
| **09-09** | 09-10 | none | none | same | unknown | same |
| **09-10** | 09-11 | none | none | same | unknown | same |
| 09-11 (control) | 09-12 | yes (10:09) | yes (09:45) | ran on | - | settled |
| 09-12 (control) | 09-13 | yes (10:10) | yes (09:46) | ran on | - | settled |
| **09-13** | 09-14 | none | none | at/before step-2 admission | unknown | step: proved. blocker: **unknown** |
| 09-14 (control) | 09-15 | yes (10:12) | yes (09:46) | ran on | - | settled |
| 09-15 (control) | 09-16 | yes (09:46) | yes (09:46) | finalize ran; no later child admitted | - | settled |
| **09-16** | 09-17 | yes (09:58) | **yes, PASS 12/12, 0 errors (09:58:14)** | after step 4, before step 5 completed | post-step admission recheck (inferred) | step: **proved**. blocker: **inferred** |
| **09-17** | 09-18 | none | none | step-2 admission, `ingest_quality_gate` | `host_commit_above_limit` 72.511 % vs 70 % | **proved** |

Evidence for 09-17 (proved): `data/backtest/daily_refresh_status.json:561-570` (single blocker
`host_commit_above_limit`, 72.511), `:936-943` (available 6,876,209,152 B vs required 3,221,225,472 B - RAM
was NOT the blocker), `:572-925` (snapshot, clob, observation_trigger all `ACTIVE_HEALTHY`, 0 consecutive
errors - loops were NOT the blocker), `:236-244` (run lasted 191 s, `interruption.reason =
resource_admission_blocked`, status RESUMABLE).

Evidence for 09-16: the 09-18 status file embeds the previous run's long-job state at `:100-130`:
started 13:30:10Z, `completed_step_count 4`, `last_completed_step public_wu_settlement_restore`, ended
13:59:26Z (71 s after the WU step). Finalize takes ~12 min on this corpus (09-04 receipts: WU step ended
08:35:34, run ended 08:47:31), so a 71-second tail means finalize never ran to completion. That matches the
`ok_postcheck_deferred` branch (`daily_refresh.py:832-876`, break at `:1457-1459`). Corroboration: both guard
log files were last written at **09-17 09:56**, i.e. the guard recorded an incident-bearing sample
(`memory_commit_guard.ps1:518`) two minutes before the post-step recheck. A fast finalize error cannot be
excluded without the 09-17 status file, which no longer exists.

For the 8 "unknown" dates the alternatives I cannot exclude: (a) admission DEFER at `ingest_quality_gate`
on commit, RAM, or loop freshness; (b) the scheduled task never reached Python (lease busy exit 76, window
refusal exit 75, lock refusal). Seven consecutive failures 09-05..09-11 followed by success on 09-12 (the day
the owner granted program-control authority) fits (a)-by-commit, but that is correlation.

**Per-date history is unrecoverable from what is retained, by design:**
- `daily_refresh_status.json` is a single file overwritten by every run (`daily_refresh.py:525`, `:1710`).
- The progress ledger row keeps blockers only for `status == "error"` steps
  (`reporting/daily/daily_progress_ledger.py:352-361`); a deferred step has `status == "deferred"`
  (`daily_refresh_status.py:47-51`), so its admission blockers are dropped. The ledger does keep the run's
  overall status string ("deferred"), so deferred-vs-error-vs-never-ran IS recoverable from
  `data/backtest/daily_progress_ledger.csv` (would need; it is a ledger, not opened).
- The Python admission receipt records `commit_percent` only - not used bytes, not the limit
  (`daily_refresh_resources.py:402-410`), so even the retained 09-17 receipt cannot say what the limit was.

What should retain it: copy the terminal status to `data/backtest/daily_refresh_runs/<run_id>.json` on every
terminal write (one `write_json_atomic` beside `:1710`), add `commit_used_bytes`/`commit_limit_bytes` to the
admission receipt (the computation already exists at `operations/runtime_monitor.py:716-725`), and include
deferred steps' blocker codes in the ledger row.

---

## 3. What holds the memory (Questions 2 and 4)

### 3.1 The guard status records no consumers at all

`data/logs/memory_commit_guard_status.json` has 16 scalar fields and no process list. The top-5
private-bytes line is written only to the text log and only at commit >= 85 %
(`memory_commit_guard.ps1:394-400`); the top-5 working-set line only when free RAM < 1.5 GiB (`:385-392`);
the history JSONL is event-only and carries no process names (`:518-530`). **In the 50-75 % band where the
70 % gate actually bites, the project retains zero attribution of who holds commit.** The 09-18 deferral at
72.5 % left no guard record at all (both guard logs last written 09-17 09:56). This is why nobody could
answer the question.

### 3.2 The denominator moved (the main finding)

| When | Commit used | Commit limit | Percent | Source |
| --- | --- | --- | --- | --- |
| 2026-07-12 | 63.3 GB (incident peak) | 63.7 GB | 99.4 % | `HOST_LOAD_POLICY.md:79, 400-401` |
| 2026-08-13 | 28.70 GB -> 16.91 GB | 37.05 GB -> 34.51 GB | 77.5 % -> 49.0 % | `ESTABLISHED_FINDINGS.md:2120-2123` |
| 2026-09-04 08:35 | not recorded | not recorded | 58.289 % | `refresh-20260904-082552-096-19396.json:720-724` |
| 2026-09-18 09:33 | not recorded | not recorded | 72.511 % | `daily_refresh_status.json:930-934` |
| **2026-09-19 03:03** | **11,762 MB** | **22,013 MB** | **53.4 %** | `memory_commit_guard_status.json:9,15,20` |

The limit is elastic (it moved 37.05 -> 34.51 GB within minutes on 08-13, and 26.2 GB of disk "returned"),
which is the signature of a system-managed pagefile. 22,013 MB minus ~16 GB RAM leaves ~6 GB of pagefile.
11,762 MB is 18.0 % of 63.7 GB, 33.3 % of 34.5 GB, 53.4 % of 22.0 GB. **No script in `scripts/` and no
module in `src/` monitors the limit** (grep: `TotalVirtualMemorySize` appears only in the guard and
`training_window.ps1`, both reducing it to a percent immediately). Why the limit is small is inferred, not
proved: candidates are pagefile reset after the 09-03 01:20 unexpected shutdown, and a system-managed
pagefile that cannot grow on a disk with 10-21 GB free. If the second is true, low disk and the commit gate
are one coupled failure: low disk -> small commit limit -> high commit % -> storage-recovery and settlement
jobs (all gated on commit < 70 %) defer -> disk is not recovered.

Falsification: read `Win32_PageFileUsage.AllocatedBaseSize` and the pagefile setting once (one CIM query).
If the pagefile is a fixed 48 GB, this finding is wrong.

### 3.3 Ranked consumers, with evidence grade

| Rank | Consumer | Size | Evidence grade |
| --- | --- | --- | --- |
| 1 | Commit-limit shrink (denominator) | ~20-35 points of the percent | limit value **proved** (live status); causal attribution **inferred** (no limit history retained) |
| 2 | Snapshot capture children in flight at the admission instant: up to 2 x 1,792 MiB cap, measured peak 1.49 GiB each (`HOST_LOAD_POLICY.md:169-173`) = 14-16 points on a 22 GB limit | transient 3.0-3.5 GB | **inferred**: snapshot heartbeat age was 3.6 s at the 09-18 admission instant (`daily_refresh_status.json:578-579`, loop interval 600 s), so a batch was starting or running when commit was sampled once |
| 3 | Long-lived capture parents: snapshot parent and observation trigger each import the full model stack (81 and 86 loaded modules, `daily_refresh_status.json:606, 819`); loops had been up 8.3 and 6.4 days at the 09-18 sample (`:699-700, :917-918`); policy admits the parent "can retain its pre-fix allocator high-water mark" (`HOST_LOAD_POLICY.md:179-181`); the project previously scheduled `WeatherSnapshotMemoryRestart08xx` and `WeatherSnapshotStageAHeadroom0819/0820` at 09:05 to buy Stage-A headroom (`OPERATING_SCHEDULE.md:31-32, 178-179`) | unknown | **inferred**; no per-process number retained anywhere |
| 4 | Agent/desktop programs on the production host (Codex, ChatGPT, Claude, editors, browsers) | unknown | **unknown**. Suspected by the operators themselves: a `WeatherAgentMemoryRelease_20260913_a1` task ran 09-13 04:42 (`MORNING_BRIEFING.md:32-33`) and the chain passed on 09-12/09-13 after the 09-12 authority, then failed 09-14. n=1 correlation. No doc under `docs/` describes that task (grep: no match) |
| 5 | Stage-A parent itself (in-process reanalysis + imports before step-2 admission) | unknown, likely < 1 GB | inferred |
| 6 | Defender / OS | unknown | unknown |

Question 4 (interactive agent sessions at 09:30): the owner's 2026-09-12 note says he does not use the
production PC interactively, so "owner at the keyboard at 09:30" is not the mechanism. Agent programs,
however, do live on this host persistently (this audit is one), the guard only ever looks at agent *tool*
subtrees (pytest, inline python, recursive scans - `memory_commit_guard.ps1:107-130`), and their resident
session footprint is never measured. Plausible contributor, not shown dominant. The 09-12 authority is the
right instrument but it has no measurement to aim it: nothing tells the agent which program to close.

### 3.4 Tie-break on "tree-kill is inert"

I could not open the guard log (live-appended; forbidden), so I cannot say whether a successful tree
termination was logged since 2026-08-23. The code trace supports ps-ops:
`Stop-VerifiedProcessTree` assigns `$pid = [uint32]$row.ProcessId` (`memory_commit_guard.ps1:205`, and again
inside the sort block at `:200`). `$PID` is PowerShell's constant, all-scope automatic variable; the
assignment raises "Cannot overwrite variable PID because it is read-only or constant". The script never
sets `$ErrorActionPreference` (grep: no match), so execution continues with `$pid` equal to the GUARD'S OWN
process id. Line 206 then fetches the guard's own process, line 208 compares its creation date with the
target's, logs "creation identity changed", sets `$ok = $false`, and continues. No member of any tree is
ever stopped by this function; both callers (`:329`, `:454`) record `kill_failed_*`. The orphan sweep
(`:497`) and orphaned-evidence kill (`:372`) use other variable names and are unaffected. The only tests
are string-presence assertions (`tests/operations/test_memory_commit_guard_script.py:38, 49, 63`); nothing
executes the function. Introduced 2026-08-23 (`88b93e5ae`, `d8a45ca12`). Basis: verified in code; PowerShell
semantics not executed (running PowerShell was forbidden). Would need: an offline copy of
`data/logs/memory_commit_guard.log` searched for `terminating verified process tree` and
`creation identity changed`.

---

## 4. Code trace of the long-lived loops (Question 3)

- **No loop iterates the 51 locations / 119 events.** `all_specs()` returns the static 12-entry `REGISTRY`
  (`market/market_registry.py:422-423`); the snapshot loop (`snapshot_tracker.py:1595`), the CLOB loop
  (`market_microstructure.py:1574`) and execution-tape seeding (`execution_tape_capture.py:125`, via
  `selected_market_ids`) all iterate it. The 09-04 backfill receipt independently lists exactly 12 ids.
  `config/location_market_events.json` is read whole (1.7 MB) by execution-tape seed loading, then filtered
  to one event per registered market (`execution_tape_capture.py:119-145`).
- **Snapshot parent:** capture runs in isolated children in production (`snapshot_tracker.py:1605-1622,
  1691-1699`), so the data-integrity auditor's "whole-day `forecasts_long.csv` re-read per snapshot" is a
  per-child transient, not parent growth. The parent's per-iteration fleet-health pass streams
  `snapshots_long.csv` twice per market and keeps only the latest snapshot's rows
  (`collection_health.py:1279-1301`): CPU and IO grow with day length, memory does not.
  `read_jsonl_records` (`snapshot_tracker.py:312-326`) materialises a whole JSONL; I did not trace its
  callers.
- **CLOB loop and observation trigger:** the accumulators I found are bounded
  (`market_microstructure.py:1741` slice to `BOOK_AUDIT_RECENT_CYCLE_COUNT`; `observation_trigger.py:692`
  `processed[-2048:]`, `:1341` `recent_elapsed[-12:]`).
- **Not traced (say so plainly):** `forecast_tracker.py`, `triggered_snapshot_queue.py`,
  `market_microstructure_capture.py` book-capture internals, the websocket path of
  `execution_tape_capture.py` (`confirmed: dict[str, set[str]]` at `:243` deserves a look), the MM bot.
  A grep is not a trace; I make no "no leak" claim. The honest position: no unbounded structure was found
  in the parts read, and no retained measurement exists that could show growth either way.

---

## 5. Recoverability (Question 5)

**Deadline:** none found in code or docs.
- WU history: on 2026-09-04 the backfill settled 06-15..06-26 (70-81 days old) 12 of 12 each
  (`data/alerts/settlement_backfill_2026-06-26.json`). A 9-15-day-old date is well inside that.
- "First WU fetch frozen" rule: I searched `src/weather` for `first_wu|first fetch|frozen_settlement|
  original_settlement` and `wu_history.py` for freeze/immutable wording and found nothing. Not a claim of
  absence; I could not locate the rule the brief names.
- 7-day shelf life: `POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS = 7` constrains the newest target of a pooled
  PIT training set (`ESTABLISHED_FINDINGS.md:207-213`); it does not limit settling an old date.
- Gamma retention: finalize reconciles against Polymarket (`daily_refresh_source_steps.py:666`). The 09-04
  backfills of June dates passed the tool's check, but that check tests `settlement_source ==
  daily_summary` only (`settlement_backfill_one.ps1:240-257`), not `reconciliation_status` or
  `promotion_countable`. Whether old dates still reconcile is **unknown**.
- Soft deadlines that ARE real: (i) the hole alarm looks back 14 days, hard-coded
  (`settlement_hole_check.py:59, 64, 81`). 09-04 was in the list on 09-18 and is absent on 09-19
  (`MORNING_BRIEFING.md:10` lists 9 dates starting 09-05) although nothing settled it - the count improved
  by expiry. By 10-02 the briefing will report zero holes with all 10 still unsettled. (ii) Disk: 10.3 GB
  free, 6.6 GB/day (`MORNING_BRIEFING.md:12-14`).

**Exact command path:** `scripts\ops\settlement_backfill_one.ps1 -TargetDate <d> [-Refetch]` ->
`chain_recovery_run.ps1 -ResumeFrom public_wu_settlement_restore -TargetDate <d> -StopAfter
market_day_labels_finalize` -> `python -m weather.operations.daily_refresh run --resume-from-step ...
--stop-after-step ...` in a kill-on-close Job. One date per invocation by design. `-Refetch` is needed only
for dates already stamped `treated_as_source_unavailable`; the 9 dates with no WU receipt were never
attempted, so they should not be poisoned.

**Does it pass its own admission now?** Gates on that path: 00:30-09:00 window
(`chain_recovery_run.ps1:135-141`), shared lease free (`:219-248`), lock ownership (`:255-309`), and the same
Python admission for the WU child: commit < 70 %, available RAM >= 3,584 MiB (2,048 + 1,536), three loops
fresh (`daily_refresh_resources.py:56-62, 339-415`). There is **no disk gate** on this path
(`workload_admission.ps1` contains no disk or commit check; the Python disk floor applies to
`DAILY_HEAVY_STEPS` only). At the 03:03 sample (53.4 %, 7,760 MB free, briefing "ON_TRACK, 0.0 min max gap")
it would be admitted. At the 09:30 sample it would not. The pre-dawn window is the right time.

**Time per date:** 21 m 40 s end to end on 09-04 (`last_run.json:9-10`): WU restore ~9.6 min (full
normalized-history rebuild for 12 stations), finalize ~12 min. Finalize is slow because it re-finalizes
**every** settled folder, not one day: `run_market_day_labels_finalize` passes
`discover_default_folders(args.snapshots_root)` (`daily_refresh_source_steps.py:658`), which returns every
past-dated event folder with a `snapshots_long.csv` (`backtesting/settled_days.py:83-96`). The 09-04 receipt
shows Toronto's ledger growing by 99 rows for a one-date backfill. Ten dates serial ~3.6 h.

**Two consequences of the all-folder finalize that nobody has used:**
1. **09-16 needs no WU fetch.** Its WU data is on disk (PASS 12/12). The next finalize that runs for any
   date settles it.
2. The only per-date operation is the WU fetch. Nine WU-only runs (`-StopAfter
   public_wu_settlement_restore`) followed by one full backfill would settle all ten in roughly 100 minutes
   instead of 3.6 hours. This ordering is my inference from the code, is NOT a rehearsed path, and bypasses
   the per-date outcome check in `settlement_backfill_one.ps1`; use the rehearsed one-date tool unless time
   is the constraint.

Also note the resource policy text is wrong about this step: `daily_refresh_resources.py:63` justifies
running finalize in-process as "one-day settlement finalization". It is an all-history finalization that
grows by 12 folders a day.

---

## 6. Minimal fix (Question 6)

Ranked by size. None was applied; this audit changed nothing.

**A. Bounded wait inside the existing admission (smallest; one function).**
`_run_isolated_stage_a_step` samples commit once and raises `StageAResourceDeferred` immediately
(`daily_refresh.py:630-683`). Its own docstring says "retry is safe and bounded"
(`daily_refresh_resources.py:113-114`), the run writes a complete `resume_command` and
`interruption.status = RESUMABLE` - and **nothing consumes either**: `resource_admission_blocked` has one
producer and zero consumers in `src/`, `resume_command|RESUMABLE` has zero matches under `scripts/`, the
task has one daily trigger with no repetition or restart settings (`register_daily_refresh.ps1:142-151`),
and the wrapper launches the child exactly once (`daily_refresh.ps1:116-143`). Re-evaluating admission every
60 s for up to ~20 minutes before deferring would ride out a snapshot capture batch (section 3.3 rank 2)
without loosening any threshold. The 11:55 teardown still bounds it. Deferred, critical and interrupted all
exit 2 (`daily_refresh_cli.py:815-820`), so a wrapper-level retry would have to read the status file; the
in-function wait avoids that.

**B. Make every successful day heal earlier holes (small; one call site).**
Change the WU restore range from `store.missing_ranges(target, target, chunk_days=1)`
(`daily_refresh_source_steps.py:187-191`) to a lookback such as `target - 14 days .. target`.
`missing_ranges` already skips dates with raw data, so the no-hole cost is nil. Because finalize is
all-folder, this alone would have closed 09-04..09-10 on 09-12 and 09-13 on 09-15. Caveat: dates stamped
`treated_as_source_unavailable` are subtracted by `missing_ranges` and still need `-Refetch`.

**C. Stop an audit step from forfeiting the day's truth.** `ingest_quality_gate` (needs 3.0 GiB available,
commit < 70 %) precedes the WU restore, and a post-step recheck after the WU restore can stop the run
before the in-process, low-memory finalize (the 09-16 case). Either move steps 3-5 ahead of step 2, or do
not let a post-check deferral break before `market_day_labels_finalize`. Larger change (step order, resume
binding, promotion receipts); do A and B first.

**D. Fix the denominator rather than fight the numerator.** Pin the pagefile to a fixed size (the policy
already assumes 48 GB) once disk allows, or express the gate in absolute bytes of commit headroom. Owner
decision; interacts with the disk shortage.

**E. Evidence so the next audit is not blind:** per-run status archive, `commit_used/limit_bytes` in the
receipt, deferred blockers in the ledger row, and a top-N private-bytes-by-name sample in the guard status
every N minutes regardless of threshold.

---

## 7. Findings (summary; full structured list returned separately)

1. HIGH - Commit gate is evaluated against a commit limit that has fallen to 22.0 GB from the 63.7 GB the
   policy documents; nothing records or monitors the limit. (new)
2. HIGH - Settlement deferral is single-instant, never retried, holes never self-heal, and no recovery has
   been attempted for any of the 10 dates since 09-04. (known_open mechanism; new: resumable contract has
   zero consumers, and zero attempts)
3. HIGH - The hole alarm expires unsettled dates after 14 days; 09-04 already vanished unsettled. (new)
4. HIGH - Guard tree termination cannot succeed (`$pid` assignment); tests are string-presence only.
   (corroborates ps-ops by code; log not opened)
5. MEDIUM - Per-date blocker history is destroyed daily; 8 of 10 dates unattributable. (new)
6. MEDIUM - An audit step's admission sits in front of settlement truth; post-step recheck can stop before
   the light finalize (09-16). (new)
7. MEDIUM - No consumer attribution retained below 85 % commit; the 09-12 program-control authority has
   nothing to aim at. (new)
8. LOW - Finalize is all-history and in-process but documented as "one-day". (new)
9. INFO - All 10 dates recoverable; no hard deadline; ~22 min per date; 09-16 needs finalize only.
10. INFO - No long-lived loop iterates the 51-location config; all iterate the static 12-market registry.

## 8. Strengths

- Admission receipts are honest and rich: exact blocker code, numbers, per-loop identity, and a terminal
  RESUMABLE fallback persisted BEFORE the child is launched (`daily_refresh.py:647-670`). The one proved
  date was proved entirely from that receipt.
- `settlement_backfill_one.ps1` verifies the outcome row content in all 12 ledgers rather than the exit
  code, opens ledgers with `FileShare.ReadWrite` after the 08-11 incident, and derives the market list from
  the authoritative registry with a module-path check (`:86-142, 209-257`).
- Kill-on-close Job containment with an absolute deadline in both the scheduled wrapper and the recovery
  wrapper (`daily_refresh.ps1:111-149`, `chain_recovery_run.ps1:165-212`).
- Per-date WU receipts and per-run child folders exist and are immutable; they are what made the
  reconstruction in section 2 possible.
- Long-lived parents read tapes by streaming and keep bounded status lists
  (`collection_health.py:1279-1301`, `observation_trigger.py:692`).

## 9. Not covered / open questions

- Guard log and history contents (forbidden to open). Open question: what fired at 09-17 09:56.
- `daily_progress_ledger.csv` (would show deferred-vs-error-vs-absent for each of the 8 unknown run days).
- Actual pagefile configuration and current allocated size (one CIM query; process queries were forbidden).
- Full leak trace of `forecast_tracker.py`, `triggered_snapshot_queue.py`, CLOB book capture internals,
  execution-tape websocket state, the MM bot.
- Whether Gamma still serves resolution data for 9-15-day-old events (reconciliation outcome of a backfill).
- Whether `finalize_folders` settles a folder purely from the presence of a WU daily-summary row; I read the
  caller and the folder discovery, not `finalize_folders` itself. The 09-16 "finalize-only" claim rests on
  that reading plus the 99-row ledger growth observed on 09-04.
- Task Scheduler history for 09-05..09-11 (would separate "deferred" from "never launched").
