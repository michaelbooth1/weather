# Audit dimension: Operations A - daily chain, settlement, backfill, supervisors, admission

Key: `ops-chain`. Auditor run: 2026-09-18, on the live production host, read-only
(Read/Grep/Glob plus whitelisted `git log` / `git show` / one non-recursive `ls scripts/ops`).
No python, no scripts, no `data/` access (my brief did not grant it). Health grade: **D**.

## 1. Scope and method

Files opened (fully or in the cited ranges):

- `src/weather/operations/daily_refresh.py` (whole orchestrator, 1-1867)
- `src/weather/operations/daily_refresh_resources.py` (whole)
- `src/weather/operations/daily_refresh_status.py` (whole)
- `src/weather/operations/daily_refresh_settled_day.py` (whole)
- `src/weather/operations/daily_refresh_bounded.py` (whole)
- `src/weather/operations/daily_refresh_source_steps.py` (150-680)
- `src/weather/operations/daily_refresh_lanes.py` (15-75, 160-240, 876-945)
- `src/weather/operations/daily_refresh_registry.py` (step registry via grep)
- `src/weather/operations/daily_refresh_cli.py` (exit codes, relevant flags)
- `src/weather/operations/capture_resource_gate.py` (1-560)
- `src/weather/operations/settlement_hole_check.py` (whole)
- `src/weather/operations/settled_day_freshness.py` (target-date function)
- `src/weather/operations/supervisor.py` (SupervisorSpec, recovery guard, heartbeat_state)
- `src/weather/operations/long_job_guard.py` (structure only)
- `src/weather/operations/closed_day_projection_tiering.py` (header, to rule out a labels hazard)
- `src/weather/backtesting/settlement_ledger.py` (664-1491: reconciliation, ledger, finalize)
- `src/weather/backtesting/settled_days.py` (folder discovery)
- `src/weather/market/market_day_labels.py` (CLI)
- `src/weather/sources/wu_history.py` (failure classes, unavailable-date poison)
- `src/weather/collection/snapshot_tracker.py` (1405-1445, how `consecutive_errors` latches)
- `scripts/ops/daily_refresh.ps1`, `daily_refresh_contract.ps1` (60-150), `register_daily_refresh.ps1`,
  `chain_recovery_run.ps1`, `settlement_backfill_one.ps1`, `workload_admission.ps1` (1-1780),
  `health_watchdog.ps1` (55-104), `status.ps1` (1478-1690, 3395-3470), `streak_status.py` (56-115)
- `tests/backtesting/test_settlement_ledger.py`, `tests/operations/test_daily_refresh_resources.py` (335-410)
- Docs: `docs/operations/STATE_OF_PLAY.md`, `HOST_LOAD_POLICY.md` (200-350),
  `FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md` (55-94),
  `docs/roadmap/workstation-handoff-2026-07-28c-settlement-revision-churn.md`

Method: for each structural claim I traced one instance end to end in the code and cite
`path:line`. Live-state facts (21 GB free, 10 of 14 dates unsettled, streak 2/14) are the lead
auditor's, from `data/alerts/MORNING_BRIEFING.md`; I did not open `data/`.

## 2. The hypothesis: does 21 GB free disk make the settlement chain defer?

**Refuted in code.** No disk threshold is consulted anywhere on the path from the 09:30 Scheduler
trigger to `market_day_labels_finalize`.

What actually gates Stage A (settlement stage):

1. Wrapper time window and lease. `scripts/ops/daily_refresh.ps1:97-103` refuses (exit 75) outside
   00:30-11:55; `:104-110` refuses (exit 76) if another job holds the single host-global heavy
   lease (`workload_admission.ps1:1505-1516`, mutex `Global\WeatherProjectHeavyWorkloadV1`).
   Neither path reads free disk (grep for disk/free/GB in `workload_admission.ps1`,
   `daily_refresh.ps1`, `chain_recovery_run.ps1`, `settlement_backfill_one.ps1`: no threshold).
2. Per isolated step admission, `build_stage_a_step_admission`
   (`daily_refresh_resources.py:339-415`): available physical RAM >= 1536 MiB reserve + the step's
   admission working set (`:21-23`, `:168-171`), host commit < 70% (`:373-378`), and all three
   capture loops active, heartbeat-fresh and not degraded (`:263-296`). No disk term.

Every disk constant I found, and who consults it:

| Constant | Value | Consulted by |
| --- | --- | --- |
| `capture_resource_gate.DEFAULT_MIN_FREE_DISK_BYTES` (`capture_resource_gate.py:34`) | 30 GiB | `_capture_resource_preflight` (`daily_refresh.py:264-320`), invoked only for `DAILY_HEAVY_STEPS = {promotion_refresh, active_variant_shadow}` (`daily_refresh.py:124`, `:1304-1317`); both are Stage B, whose task is registered disabled (`register_daily_refresh.ps1:191-196`). Also nightly retrain. |
| `DEFAULT_MIN_DISK_HEADROOM_DAYS` (`capture_resource_gate.py:35`) | 30 days | Dormant: evaluated only if `daily_disk_growth_bytes` is supplied (`capture_resource_gate.py:475-493`); the CLI default is `None` (`daily_refresh_cli.py:200-203`). |
| `experiment_executor.MIN_FREE_DISK_BYTES` (`experiment_executor.py:60`) | 50 GiB | Experiment/qualification executor only. This is the "50 GiB floor" in STATE_OF_PLAY line 24. |
| `clob_order_book_tiering.DEFAULT_MIN_FREE_BYTES` (`:26`) | 1 GiB + source size | Stage-A step 14, after settlement. |
| `clob_raw_tape_tiering.DEFAULT_MIN_FREE_BYTES` (`:81`) | 8 GiB + source size | 06:00 tiering task. |
| `cold_snapshot_compression.MIN_FREE_DISK_BYTES` (`:37`) | 8 GiB + 2 files | Compression lane. |
| `bot_run_liveness.DEFAULT_MIN_FREE_BYTES` (`:11`) | 1 GiB | Bot rolls. |
| promotion artifact preflight (`daily_refresh_locks.py:100-124`) | export estimate + floor | `promotion_refresh` only. |
| HOST_LOAD_POLICY rule 2 (`HOST_LOAD_POLICY.md:330-333`) | ">= 50 GB disk free" | A documented convention for ad-hoc heavy work. `chain_recovery_run.ps1` enforces the window (`:135-141`) and the lease (`:218-248`) but not the disk number. |

Two consequences worth stating plainly:

- In `live` mode the capture-resource gate blocks whenever any capture loop is active
  (`capture_resource_gate.py:397-406`), so on this host `promotion_refresh` and
  `active_variant_shadow` can never be admitted while capture runs, regardless of disk. That is by
  design (HOST_LOAD_POLICY 247-249) but means the 30 GiB number is never the binding term here.
- The inverse risk is the real one: the chain has **no** disk floor, so it will keep writing as the
  volume fills (lead: ~4 days of headroom). See finding 5.

So the SETTLEMENT HOLE is not caused by low disk. The mechanisms the code does allow are in
findings 1-4. I could not determine which one fired on each date without reading
`data/backtest/daily_refresh_status.json`; section 6 lists the exact fields to check.

## 3. Findings

### ops-chain-1 (HIGH, known_open) - the settlement chain is single-shot: one failed admission check loses the day, and nothing retries

- The Stage-A task has one daily trigger at 09:30 and no restart/repetition settings
  (`register_daily_refresh.ps1:142-151`). The wrapper exits 75/76 on refusal with no wait loop
  (`daily_refresh.ps1:100-110`).
- Inside the chain, each isolated step evaluates admission exactly once; a DEFER raises
  immediately (`daily_refresh.py:630-683`), `run_step` records `deferred`
  (`daily_refresh_status.py:47-51`), and the orchestrator breaks out of the step loop
  (`daily_refresh.py:1460-1462`). The exception docstring says "retry is safe and bounded"
  (`daily_refresh_resources.py:113-114`) but no code retries. A resume command is persisted
  (`daily_refresh.py:624`, `:661-667`) and no scheduled consumer ever runs it (grep of
  `scripts/ops` for `resume-from-step|resume_command|chain_recovery_run` finds only the manual
  tools and guidance text, e.g. `health_watchdog.ps1:80`).
- The WU fetch targets yesterday only (`daily_refresh_source_steps.py:169`, `:187-191`;
  `settled_day_freshness.py:190-197`), so a date whose chain never reached
  `public_wu_settlement_restore` has no raw WU payload and is never fetched again.
  `status.ps1:1652` says so itself: "each needs an EXPLICIT per-date backfill; the next chain run
  will not retry it". No automatic backfill exists.
- Nuance the project docs do not state: `market_day_labels_finalize` re-labels **every** settled
  folder on every run (`market_day_labels.py:24-25`, `settled_days.py:83-96`,
  `settlement_ledger.py:1465-1482`). A date whose WU raw exists but whose finalize was skipped (for
  example a post-step deferral, `daily_refresh.py:832-876`) does self-heal on the next successful
  run. Only dates with no WU raw need the explicit fetch.

Impact: with before+after checks on two isolated steps ahead of finalize, a day is settled only if
four consecutive point-in-time checks all pass. Recovery is manual, one date per night, in a
00:30-09:00 window that is also used by storage and qualification work under the same single lease.

### ops-chain-2 (HIGH, new) - settlement is sequenced behind a hard-stop diagnostic and an admission rule stricter than the supervisor's own health model

- Step order (`daily_refresh_registry.py:17-21`): `reanalysis_recent_refresh`,
  `ingest_quality_gate`, `event_metadata_validation`, `public_wu_settlement_restore`,
  `market_day_labels_finalize`.
- `ingest_quality_gate` is a learning-lane fleet historical audit
  (`daily_refresh_source_steps.py:548-561`, `data_auditor.audit_fleet_historical_data`) with a
  30-minute/2 GiB budget (`daily_refresh_resources.py:54`). Because it is in
  `STAGE_A_ISOLATED_STEPS`, lane containment is explicitly withheld
  (`daily_refresh.py:1404-1408`, `:1426-1432`) and any error, timeout, budget breach or deferral
  breaks the chain (`:1463-1471`) before settlement runs. `--skip-historical-audits` does not skip
  it; that flag only reaches fleet observability (`daily_refresh_reporting_steps.py:1457`).
- Admission treats a loop as degraded at `consecutive_errors >= 1`
  (`capture_resource_gate.py:127`, `:169-172`), and any degraded loop is a blocker
  (`daily_refresh_resources.py:288-295`). The snapshot loop latches `consecutive_errors += 1` when
  **any one** of the 12 markets errors in the last completed 10-minute iteration
  (`snapshot_tracker.py:1418-1434`). The test suite pins this exact case: one
  `los-angeles: capture_process_error` defers the step
  (`tests/operations/test_daily_refresh_resources.py:369-405`).
- The supervisor itself tolerates `ERRORING` and only calls a loop erroring at 3 consecutive errors
  (`supervisor.py:80`, `:919`, `:930-931`, `:943-950`). The settlement gate is therefore three
  times stricter than the definition of "healthy enough not to restart".

Impact: one market's transient capture error, present at the instant of one of four checks, cancels
settlement for all 12 markets for that date, with no retry (finding 1). Capture trouble and
settlement loss are coupled, which is consistent with the lead's live state (streak 2/14 alongside
10 of 14 dates unsettled) but I have not proved causation for those dates.

### ops-chain-3 (HIGH, known_open since 2026-07-28, unfixed) - finalize re-revises every historical market-day on every run; cost grows super-linearly inside a 145-minute kill window

Traced end to end:

- `finalize_folders` stamps one wall-clock `finalized_at` per run (`settlement_ledger.py:1460`);
  `build_label` writes it into the label twice (`:1234`, `:1321`) plus a whole-file hash of the
  growing `daily_summary.csv` (`:1210-1217`).
- The idempotency hash excludes only revision metadata (`:825-835`, `:849-854`), so
  `record_hash != previous hash` on every run and the early return at `:1044-1049` never fires in
  production. The unit test that claims idempotency uses a fixed timestamp
  (`tests/backtesting/test_settlement_ledger.py:28`, `:69-79`).
- Each upsert parses the entire market ledger (`:1032`) and each new row stores old and new values
  of every changed field, including the full `evidence` dict (`:965-976`).
- Folders are processed oldest first (`settled_days.py:96`), each with a full pandas read and SHA-256
  of the tape (`:1141`, `:1211`), a reload of the daily summary (`:1148-1149`), a Gamma HTTP GET with
  a 10 s timeout because the scheduled command never passes `--skip-polymarket-reconciliation`
  (`daily_refresh_contract.ps1:87-114`; `settlement_ledger.py:670-673`, `:774-775`), and a rewrite of
  `settlement.json` (`:1100-1102`).
- The labels CSV is written only after the whole loop (`:1483-1489`). The step is `in_process`,
  labelled "one-day settlement finalization", with no timeout or memory ceiling
  (`daily_refresh_resources.py:63`). The wrapper kills the process tree at 11:55
  (`daily_refresh.ps1:97`, `:122-139`).

The project already measured this: 633 of 646 folders rewritten in one run, median revision 17
(07-28 handoff, lines 11-14, fix deferred "after the lock"); Austin ledger 19.5 MB, ~66 folders per
run, "Nobody has asked what that costs" (`FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md:79-85`).
`git log` shows one commit to `settlement_ledger.py` since (3c38a1b0b, 08-11, per-folder
isolation); the churn is unchanged at HEAD.

Inferred magnitude (not measured by me): roughly 1,200+ folders now, so each run makes 1,200+ Gamma
calls and parses each market ledger ~100 times. If Gamma is unreachable, 1,200 x 10 s exceeds the
145-minute window by itself. Because yesterday's folders are processed last, a deadline kill or
crash loses exactly the new day while having re-revised months-old days. Every consumer that reads a
ledger whole (`streak_status.py:73-91`) pays the same growth.

### ops-chain-4 (MEDIUM, new) - monitoring words a Stage-A deferral as benign and whitelists its exit codes

- `status.ps1:1584-1586`: when the first non-ok step is `deferred`, the line reads "heavy steps wait
  for a quieter host" and is **not** added to `$warns`; every other failure is (`:1587-1590`). The
  comment (`:1569-1570`) was written for Stage-B heavy steps. For Stage A it means yesterday's
  settlement is gone.
- `status.ps1:3414` lists `0x2` and `0x4B` as expected results for the chain task. Exit 2 is
  overloaded: `critical` (the standing pre-release readiness BLOCK), `deferred`, and `interrupted`
  all map to it (`daily_refresh_cli.py:815-820`). Exit 75 covers both "refused outside window" and
  "killed at 11:55" (`daily_refresh.ps1:100-103`, `:132-138`).
- The consequence check does fire (`status.ps1:1648-1655`, `settlement_hole_check.py:80-88`), but
  only after noon the following day (`:83-84`) and only as a flag with manual guidance.

This is the project's own named defect shape (an overloaded bit silenced for one meaning hides the
other). Ten open dates show the flag is not producing repair.

### ops-chain-5 (MEDIUM, new) - the chain has no disk floor, the documented 50 GB rule is unenforced on the recovery path, and its canonical writes are not atomic

- No disk check on Stage A or `chain_recovery_run.ps1` (section 2). The 30-day headroom check exists
  but is dormant (`capture_resource_gate.py:475-493`, `daily_refresh_cli.py:200-203`).
- `write_labels_csv` opens the canonical labels CSV with `"w"` and streams rows
  (`settlement_ledger.py:1326-1334`); `write_folder_label` uses `write_text` (`:1100-1102`). ENOSPC,
  the 11:55 Job kill, or power loss during that write leaves a truncated file. The ledger is the
  authority, so this is recoverable by a clean finalize, but readers in between see a short CSV.
- The ledger append is fsynced (`:1073-1076`) but a torn final line is possible on ENOSPC, and
  `read_jsonl` silently drops undecodable lines (`:806-813`); `verify_ledger_history` only sees
  parsed rows, so a lost revision is invisible (it is re-appended next run, so impact is low).
- Status and manifests do use atomic writes (`daily_refresh.py:525`, `:1773`), so the gap is
  specific to the settlement artifacts.

### ops-chain-6 (MEDIUM, partly known) - a bounded recovery run reports PASS / exit 0 when nothing settled

- `run_public_wu_settlement_restore_step` returns `status: BLOCK` rather than raising
  (`daily_refresh_source_steps.py:252`, `:278-282`, `:302-317`); `run_market_day_labels_finalize`
  then returns `{"status": "BLOCK", "reason": "public_wu_settlement_restore_not_passed"}`
  (`:651-657`). `run_step` marks both rows `ok` because no exception was raised
  (`daily_refresh_status.py:34-36`).
- Neither step is a promotion gate (`daily_refresh_registry.py:20-21`), so the lane stays unblocked
  (`daily_refresh_lanes.py:185-188`), payload status is `ok`, exit code 0
  (`daily_refresh_cli.py:815-820`).
- The bounded receipt is computed from row status only (`daily_refresh_bounded.py:76-86`) and
  `chain_recovery_run.ps1:403-435` accepts it and prints "OK: bounded chain completed".
- In the full chain the settled-day barrier catches this (`daily_refresh_settled_day.py:189-203`);
  in a `--stop-after-step market_day_labels_finalize` run the barrier never executes.
- `settlement_backfill_one.ps1:198-307` compensates by verifying ledger content per market. But
  `health_watchdog.ps1:80` and STATE_OF_PLAY step 5 point operators at `chain_recovery_run.ps1`
  directly, which has no outcome check.

### ops-chain-7 (MEDIUM, known_open) - the labels-CSV truncation hazard is fixed only on the failure path

`finalize_folders` merges when a folder failed (`settlement_ledger.py:1483-1488`) but on success it
rewrites the whole CSV from whatever folder list it was given (`:1489`). Both entry points still
accept a subset: `python -m weather.market.market_day_labels finalize <folders>`
(`market_day_labels.py:37`, `:74`) and the positional `folders` of `daily_refresh run`
(`daily_refresh_cli.py:111`; `daily_refresh_source_steps.py:658`). A clean subset run replaces
~1,200 rows with the subset. `merge_labels_csv`'s own docstring states the rule
(`:1337-1343`) and nothing enforces it. The supported backfill path does not pass folders, so it is
safe; the hazard is the ad-hoc command an agent will reach for.

### ops-chain-8 (MEDIUM, known_open) - one market's WU failure still blocks labels for all 12

Per-folder isolation (3c38a1b0b) fixed the finalize side. The gate in front of it is still
all-or-nothing: any market with status != PASS makes the restore BLOCK
(`daily_refresh_source_steps.py:252`, `:278-282`) and finalize refuses every market (`:651-657`).
Transient errors get two retries at 5 s and 10 s (`:175-176`, `:210-219`); a permanent-class status
also stamps the date `treated_as_source_unavailable` so later plain runs fetch nothing
(`wu_history.py:655`, `:734-741`), which the `-Refetch` switch exists to undo. The 11 healthy
markets self-heal on the next successful finalize (finding 1 nuance); the failed market does not.

### ops-chain-9 (LOW, new) - receipts and budgets that do not describe what runs

- A kill during an in-process step (finalize is one) leaves `daily_refresh_status.json` at
  `status: running`, because the terminal fallback is persisted only before isolated children
  (`daily_refresh.py:649-670`, reset to running at `:877-879`). The comment at `:668-669` promises
  otherwise.
- Stage-A producer SLA is 14,400 s (`daily_refresh_contract.ps1:115`) but the wrapper kills at
  8,700 s, so the SLA can never be breached. Isolated-step timeouts sum to ~905 minutes against a
  145-minute window (`daily_refresh_resources.py:52-104`), so the wrapper deadline, not the budgets,
  bounds the stage.
- Stale text: `_finalize_folder_with_retry` and the 08-11 incident doc say the ledger is "rewritten
  whole on every upsert" (`settlement_ledger.py:1384`); HEAD appends (`:1073`). The cost is the
  whole-file read.

### ops-chain-10 (INFO) - the recovery tool is only exercised when needed

`settlement_backfill_one.ps1` could not pass its own registry guard until 2026-09-04: the Python
`-c` program was passed as an array element and split at spaces (`git show 654bdc5eb`). The guard
arrived in the 08-19/08-21 hardening commits, so the tool refused every invocation for roughly two
weeks, and the fix landed the day the current hole began. Its test file changed by three lines in
that commit, which suggests text-level coverage. Separately, the recipe runs a full all-history
finalize per backfilled date; since one finalize labels every date whose WU raw exists, N fetches
plus one finalize would do the same work with far less ledger churn.

## 4. Strengths

- Process containment is real: children start suspended inside a kill-on-close Job Object, with
  private-memory, working-set and timeout ceilings and post-exit receipt validation including the
  venv launcher-shim PID case (`daily_refresh.py:685-821`; `daily_refresh.ps1:111-149`).
- Resume receipts are written before a child runs and fail closed if they cannot be persisted
  (`daily_refresh.py:649-670`); status is flushed after every step (`:1444-1449`).
- The settlement ledger is append-only with hash-chained revisions and refuses to extend a corrupt
  history (`settlement_ledger.py:905-962`, `:1034-1039`, `:1073-1076`).
- `settlement_backfill_one.ps1` verifies outcome, not exit code, against the market registry, and
  reads ledgers with `FileShare.ReadWrite` after the 08-11 incident (`:198-307`).
- `settlement_hole_check.py` seeks from EOF, counts a date only if source and high are present, and
  scans for interior holes (`:15-52`, `:80-88`).
- Host resource overrides can only be made stricter (`daily_refresh_resources.py:137-150`).
- Incident knowledge is written into the code at the point of failure, which made this audit
  tractable.

## 5. Not covered

`nightly_health_checks.py`, `ops_monitor.py`, `runtime_monitor.py`, `operator_host_status.py`,
`capture_recovery_check.py`, `bot_daily_roll_supervisor.py`, `execution_tape_supervisor.py`,
`market_making_daily_roll.py`, `taker_bot_daily_roll.py`, `daily_roll_log_hygiene.py` and log
rotation, `loop_jsonl_repair.py`, `observation_trigger.py`, `release_admissibility_clock.py`,
`daily_refresh_stage_manifests.py` (Stage-B gate), `daily_refresh_trading_steps.py`,
`daily_refresh_reporting_steps.py` beyond greps, `daily_refresh_locks.py`, the internals of
`long_job_guard.run_isolated_subprocess`, `workload_admission.ps1` lines 1780-2050, `streak.ps1`,
`boot_recovery.ps1`, `memory_commit_guard.ps1`. No live state was read, so no finding here is
`live_state`.

## 6. Open questions (each answerable from one small file)

1. Which mechanism fired on 09-04..09-10, 09-13, 09-16, 09-17? In
   `data/backtest/daily_refresh_status.json` (and any retained copies) read
   `resource_steps[].admission_before.blockers[].code` and `interruption.reason`; compare with the
   Scheduler last result (0x2 deferred/critical, 0x4B deadline or window refusal, 76 lease busy).
2. What is `duration_seconds` for `market_day_labels_finalize` on recent successful runs, and how
   large are the 12 `ledger.jsonl` files? That converts finding 3 from inferred to measured.
3. Do any storage lanes remove `snapshots_long.csv` from closed folders? Discovery and `build_label`
   accept only the `.csv` (`settled_days.py:93`, `settlement_ledger.py:1138-1140`) while the archive
   registry treats `.csv.gz` as equivalent (`closed_market_day_archive.py:105-107`). If so, the next
   clean finalize silently drops those rows from the labels CSV (finding 7 mechanism). I found no
   such removal in the modules I grepped; this belongs to the storage dimension.
4. Did lease contention with the 09-13..09-17 one-shot qualification/storage tasks ever overlap
   09:30? They are window-bound to 09:00, so probably not, but `data/logs/heavy_workload.lock`
   history would settle it.
