# Audit dimension: PowerShell ops scripts and scheduled-task hygiene (`ps-ops`)

Date: 2026-09-18. Auditor: one read-only subagent in the full-project audit.
Scope: `scripts/ops/*.ps1` (73 scripts, ~1.5 MB of PowerShell) and `scripts/ops/AGENTS.md`.
Nothing was run. No project file was modified. This report is the only file written.

## 1. Method and honesty notes

- Tools used: Read, Grep, Glob on `scripts/`, `tests/`, `docs/`, `src/` only; a handful of
  whitelisted `git log` / `git show` calls and one non-recursive `ls` of `scripts/ops`.
- I did NOT read anything under `data/`, `scratch/`, `logs/`. Every statement about live state
  (21 GB free, 10/14 unsettled dates, 150+ spent tasks, a1..a11 failed) comes from the lead
  auditor's brief, not from my own observation. Those are labelled `live_state (relayed)`.
- I did NOT execute any script. Where a finding depends on PowerShell runtime semantics
  (finding 1 and the `-f` precedence note) I cite the language rule and say so. The owner can
  confirm finding 1 in under a minute from an existing log; the check is given below.
- Coverage is partial. Fully read: 24 scripts. Sampled: `status.ps1` (~15 % of 254 KB),
  `quiet_window_merge.ps1` (~3 % of 215 KB), `bounded_worktree_test_suite.ps1`,
  `integration_attempt_suite.ps1`, `staleness_sweep.ps1`. Not opened: see section 6.
- The "operator-as-parameter" class is recorded by the project as fixed and ratcheted
  (63/63 over 13 files). I did not re-derive it.

## 2. Headline summary

The newer wrappers are genuinely well engineered: suspended-create + kill-on-close Job
containment, an OS-handle heavy-workload lease, create-only receipts, exact post-registration
readbacks, S4U everywhere, no `Invoke-Expression` anywhere, outcome verification instead of
exit-code trust in the settlement backfill. That work is real and should be credited.

Against that, four things matter:

1. The capture host's enforcement backstop (`memory_commit_guard.ps1`) has an assignment to the
   read-only automatic variable `$PID` inside its only tree-termination function. By PowerShell's
   rules that assignment fails, and the function then compares every target against the guard's
   own process and refuses. Tree termination (out-of-window agent work, >8 GB trees, the 92 %
   commit kill) appears to have been inert since 2026-08-23. The test file for this script is
   substring assertions over the source text and cannot see it.
2. The integration suite has a hard-coded 50 GiB free-disk floor. At the relayed 21 GB free,
   every integration attempt must fail at admission, so no code fix can reach production through
   the mandated path while the disk problem persists.
3. The watchdog's settlement-hole age escalation is dead code: it regex-matches a flag format
   that `status.ps1` stopped emitting on 2026-08-10. Settlement holes can never reach CRITICAL.
4. One-shot tasks are never unregistered and no tool exists to retire them; `status.ps1` emits a
   permanent line per spent task and fully re-validates every retained attempt on every
   15-minute pass, under a watchdog with a 5-minute kill limit.

The common root: these scripts are verified by text-presence tests and parse checks, not by
execution, and cross-script string contracts (flag text <-> classifier regex) have no test at all.

## 3. Findings

Severity scale per the audit brief. `known_status`: new / known_open / known_accepted.

### ps-ops-1 (HIGH, new) - memory guard tree termination is inert: `$pid` is a constant

Evidence
- `scripts/ops/memory_commit_guard.ps1:205` - `$pid = [uint32]$row.ProcessId` inside
  `Stop-VerifiedProcessTree`. Same assignment at `:200` inside the `Sort-Object` expression.
- PowerShell variable names are case-insensitive; `$PID` is an automatic variable created with
  options `Constant, AllScope`. Assigning to it in any scope raises
  `Cannot overwrite variable PID because it is read-only or constant` (VariableNotWritable).
  PSScriptAnalyzer ships a rule for exactly this (`PSAvoidAssignmentToAutomaticVariable`).
- The script never sets `$ErrorActionPreference` (whole file read; registrar invokes it with
  `-File`, `register_memory_commit_guard.ps1:32`), so the error is statement-terminating only and
  execution continues with `$pid` still equal to the guard's own process id.
- `:206` then queries `Win32_Process` for the guard itself; `:208` compares the guard's
  `CreationDate` with the target row's, which always differs; `:209-211` logs
  `pid <guard pid> creation identity changed before termination`, sets `$ok = $false`, `continue`.
  `Stop-Process` at `:214` is never reached for any member. The function returns `$false`.
- Every tree kill routes through this function: out-of-window / over-concurrency / >8 GB agent
  trees (`:329`) and the 92 % commit offender (`:454`). Only the two direct `Stop-Process` paths
  still work: orphaned evidence-refresh child (`:372`) and the orphan sweep (`:497`).
- Introduced by `88b93e5ae` (2026-08-23); `git show 88b93e5ae:scripts/ops/memory_commit_guard.ps1`
  shows the same two assignments at its lines 157/162. Before that commit the 92 % kill did not go
  through this function, so that commit also regressed the original 2026-07-12 incident control.
- `tests/operations/test_memory_commit_guard_script.py` (whole file read, 126 lines): every test
  is `assert "<substring>" in text`. Nothing executes the script. It asserts that
  `"CreationDate -ne" in block` - i.e. it asserts the presence of the very check that now misfires.
- `scripts/ops/AGENTS.md:194-195` calls this guard "the enforcement backstop".

Falsification check for the owner (read-only, one file): search
`data\logs\memory_commit_guard.log` for `creation identity changed before termination` and
`data\logs\memory_commit_guard_history.jsonl` for `kill_failed_agent_tree_pid_`. If the guard has
ever successfully logged `terminating verified process tree` followed by a process actually
disappearing since 2026-08-23, this finding is wrong. I expect every attempt to show the same
(guard's own) pid in the error line.

Impact: the automatic defence against the project's best-documented capture killer (runaway
agent/ad-hoc memory, recursive scans) does not act. Status JSON still reports the attempt, so it
looks like enforcement is happening.

Recommendation: rename the variable (`$targetPid`), add one executed Pester-style or subprocess
test that feeds a synthetic process row through `Stop-VerifiedProcessTree`, and add
PSScriptAnalyzer's automatic-variable rule to the existing parse ratchet.

### ps-ops-2 (HIGH, known_open as a policy / new as a consequence) - 50 GiB floor closes the merge path

Evidence
- `scripts/ops/bounded_worktree_test_suite.ps1:288-312` - `Assert-SuiteDiskHeadroom`, constant
  `$minimumFreeBytes = [int64]53687091200`, throws if any of RepoRoot / WorktreeRoot / LogPath /
  TEMP volumes is below it. Not a parameter.
- `:365` - called unconditionally at top level, before the time-window check, for both the
  preflight and full-suite phases.
- `scripts/ops/integration_attempt_suite.ps1:168, 201-217` - the attempt suite runs only through
  that script. `scripts/ops/AGENTS.md:26-35` makes integration attempts the mandated path for new
  scheduled integrations.
- `docs/operations/STATE_OF_PLAY.md:24` - "Ordinary qualification retains its 50 GiB disk floor"
  (deliberate, 2026-09-13). `:44-46` makes host qualification item 1 of the critical path.
- live_state (relayed): 21 GB free, filling ~5.9 GB/day.

Impact: item 1 of the owner's critical path cannot pass at current free disk, so PR 61
(reliability) and everything queued behind it, plus any fix for findings in this audit, cannot be
adopted through the sanctioned route until >= 50 GiB is free. Each failed attempt also spends an
immutable namespace and leaves two more permanent tasks (finding 4). I did not establish why
a1..a11 failed; this may or may not be the cause for those dates.

Recommendation: decide explicitly whether the floor or the backlog wins. Either restore headroom
first and stop arming attempts until `status.ps1` shows >= 50 GiB, or make the floor a reviewed
parameter with a lower bound justified by measured suite temp usage.

### ps-ops-3 (MEDIUM, new) - settlement-hole escalation in the watchdog is dead code

Evidence
- `scripts/ops/health_watchdog.ps1:104-108` - severity for class `settlement`:
  `if ($f -match "\((\d+) day") { $holeDays = ... }; if ($holeDays -ge 2) { "CRITICAL" } else { "HIGH" }`.
- `scripts/ops/status.ps1:1652` - the only emitter of `SETTLEMENT HOLE` (grep over `scripts/`,
  `src/`, `tests/`): `"SETTLEMENT HOLE: {0} date(s) unsettled in the last {1} days [{2}] - worst {3},
  up to {4} of {5} market(s) - ..."`. There is no `(<digits> day` sequence in that text, so the
  regex never matches, `$holeDays` stays 0, severity is always HIGH.
- `git show 807c6cbe3:scripts/ops/status.ps1` line 249 (2026-08-06, the commit that added the
  escalation): the text then was `... unsettled since {2} ({3} day(s) behind) ...`, which did
  match. The 2026-08-10 rewrite of the status check (comment at `status.ps1:1621-1628`) changed
  the wording and silently disconnected the watchdog.
- `tests/operations/test_health_watchdog_script.py` contains no match for `settlement`, `hole`
  or `CRITICAL`.

Impact: with 10 of 14 dates unsettled (relayed), the condition the watchdog's own comment calls
"the only thing in the briefing that was actively costing us evidence" is ranked the same as LOW
DISK, never produces exit 2, and never gets `critical_repeat` logging - it is recorded only on
change or the 6-hour heartbeat. It is still visible as HIGH; the defect is the lost escalation.

Recommendation: have `status.ps1 -Json` emit structured fields (`class`, `hole_count`,
`oldest_hole_age_days`) and have the watchdog read those instead of regex-matching prose; add one
fixture test pairing the two scripts.

### ps-ops-4 (MEDIUM, known_open) - one-shot tasks accumulate forever; monitor cost and noise grow with them

Evidence
- Grep for `Unregister-ScheduledTask` across `scripts/ops/*.ps1`: three hits, all replacing a
  recurring task's own definition (`register_clob_enrichment.ps1:45`, `register_boot_recovery.ps1:23`,
  `register_health_watchdog.ps1:19`). No script removes a one-shot.
- One-shots are registered with date/attempt-stamped names and no `EndBoundary` /
  `DeleteExpiredTaskAfter`: `register_integration_attempt.ps1:93-142, 185-208` (two per attempt),
  `register_storage_recovery_night.ps1:58-96` (up to three per plan id).
  `integration_attempt_contract.ps1:792` actually requires `EndBoundary` to be empty.
- `scripts/ops/AGENTS.md:40-41` - closing "never deletes or replaces them" (deliberate).
  `docs/operations/OPERATIONS_AGENT_ROLE.md:198-199` - "a spent one-shot flags forever until
  unregistered" (acknowledged, no tool).
- `scripts/ops/status.ps1:3522-3524` - every pass enumerates every `Weather*` task and calls
  `Get-ScheduledTaskInfo` on each. `:3927`, `:3960`, `:4006-4009` - each spent one-shot produces a
  standing WARN line on every pass, indefinitely (FLAG for the first 24 h).
- `status.ps1:28-42` - `Get-WeatherIntegrationValidatedEvidence` dot-sources the 90 KB
  `integration_attempt_contract.ps1` on every call; `:3607-3683` calls it up to ~10 times per
  retained attempt per pass, plus git subprocesses (`:73-77`); `:4019-4023` additionally walks
  `data\integration_attempts` recursively each pass.
- `scripts/ops/register_health_watchdog.ps1:28-34` - the watchdog runs that pass every 15 minutes
  under `ExecutionTimeLimit` 5 minutes; `health_watchdog.ps1:38` launches `status.ps1` as a plain
  child, not in a Job.

Impact: the briefing's "Standing notes" grows by one line per spent task (150+ relayed), which is
the alert-fatigue mechanism the script's own comments warn about. Status runtime grows linearly
with retained attempts on the host where monitor load matters. If it ever crosses 5 minutes the
watchdog is killed and the briefing silently stops regenerating - inferred, not measured.

Recommendation: add a reviewed `retire_spent_tasks.ps1` that exports each spent task's XML + hash
into the attempt's evidence folder and then unregisters it (evidence is preserved, scheduler is
cleaned). Collapse spent-task WARNs into one counted line. Cache the dot-sourced contract once per
status pass.

### ps-ops-5 (MEDIUM, new) - training window: a bookkeeping failure can skip the capture restore

Evidence
- `scripts/ops/training_window.ps1:527-541` - inside `finally`, the inner `try` runs
  `Write-WindowStatus "restore" "in_progress"` (`:530`) BEFORE `Restore-Capture` (`:531`).
- `Write-WindowStatus` (`:136-151`) uses `[IO.File]::WriteAllText` and
  `Move-Item ... -ErrorAction Stop`; both raise terminating errors (disk full, sharing violation
  while a monitor has the status JSON open). Either jumps to `catch` (`:535-539`), which logs and
  sets exit 9002 but never calls `Restore-Capture`. The `-RestoreOnly` path has the correct order
  (`:275-276`).
- There is no `catch` on the outer `try` (`:352-527`). Any `throw` inside it (`:387, 394, 399-403,
  409, 266`) propagates after `finally`, so `exit $childExit` (`:542`) is never reached and the
  thrown reason is written nowhere - the task is Hidden S4U with no transcript. The log then reads
  "window closed (nightly not_run ... exit -1); capture recovery 3/3 PASS".
- `:498-504` - the retrain child is started with `Start-Process` and torn down with `taskkill /T`,
  not the kill-on-close Job that 15 other wrappers use. `memory_commit_guard.ps1:338-346` documents
  the exact orphan scenario this permits (wrapper killed, governed `-m weather.*` child survives
  and is exempt from the guard).
- `:377-379` - `git add` / `git commit` exit codes are not checked; the next line logs
  "committed scheduled location-config drift" unconditionally.
- Spring-forward day: start 01:00 + 170 min elapsed = 04:50 wall clock, after the 04:15 dead-man.

Impact: bounded. The window is currently disabled, the 60 GB preflight (`:48, 329`) would skip it
at today's free disk, and the 04:15 dead-man is an independent backstop. If re-enabled, a status
write failure converts a ~5 minute restore into a gap of up to ~2.5 h.

Recommendation: call `Restore-Capture` first and treat status writes as best-effort; add an outer
`catch` that logs the message; move the child onto `New-WeatherKillOnCloseJob`; check the git exits.
`scripts/ops/AGENTS.md:155-157` already says to preserve the `finally` restoration.

### ps-ops-6 (MEDIUM, new) - one-shot runners have throw sites that leave no receipt and no log

Evidence
- `scripts/ops/storage_recovery_night_run.ps1:14-40` - seven `throw` sites (source tip, plan read,
  preflight timing, `night segment missed its exact one-minute start window` at `:32-34`, spent
  namespace, missing interpreter) execute before the `try` at `:61` and before `$outputRoot` is
  created at `:62`. The receipt is only written if `$outputRoot` exists (`:130-132`).
- `register_storage_recovery_night.ps1:78-86` - action is `-File <runner>`, Hidden, S4U, no
  redirection, so stderr goes nowhere.
- The 60-second start window must absorb Task Scheduler launch, two git subprocesses, and two
  `Add-Type` C# compilations (`workload_admission.ps1:67-466`, `windows_kill_on_close_job.ps1:11-409`)
  on a loaded or waking 16 GB host.
- Same shape: `integration_attempt_suite.ps1:140-188` (manifest, orchestration hashes, terminal
  check, task binding, `State -ne "Running"`, stale evidence, window - all before the `try` at
  `:198`); `production_cold_archive_run.ps1:40-108`.

Impact: for exactly the tasks the briefing reports as FAILED several nights running, the most
likely early-exit reasons cannot be recovered afterwards; the only artefact is `0x1`. This makes
each failed night cost another night. I did not confirm that the live failures took these paths.

Recommendation: wrap each runner's whole body in one `try` that appends a single line
(timestamp, script, message) to a fixed log under `data\logs\` before rethrowing; widen or
justify the 60 s start window with a measured cold-start time.

### ps-ops-7 (MEDIUM, known_open) - generated config is git-tracked and rewritten in the production tree four times a day

Evidence
- `scripts/ops/register_location_config_refresh.ps1:33-38` - triggers 00:00 / 06:00 / 12:00 / 18:00;
  `refresh_location_config.ps1:15-19, 54` regenerates `config/location_market_events.json`
  (1.7 MB) and `config/locations.json` in the production checkout.
- Session-start `git status`: both files modified. `git log -- config/location_market_events.json`
  shows 25 of the most recent 25 touching commits are automated drift commits
  ("ops: preserve fleet-generated drift", "config: scheduled location refresh drift ...").
- Drift handling is re-implemented per script: `training_window.ps1:356-384` (auto-commit),
  `boot_recovery.ps1:159-162, 376-398`, `quiet_window_merge.ps1` (4 references plus the whole
  one-time `production_baseline_reconciliation` mode described at `AGENTS.md:67-117`),
  `reconcile_integration_attempt.ps1`, `status.ps1`.

Impact: a permanently dirty production tree is the input condition for a large share of the
clean-tree gate, baseline-reconciliation and boot-recovery complexity, and it puts a 1.7 MB blob
into history every few days. Two of the four refreshes land on the boundaries of the two protected
windows.

Recommendation: move the generated files to an untracked runtime path (or track only a small
hand-maintained seed) and delete the drift machinery that then has no job.

### ps-ops-8 (LOW, new) - time-window policy is copied, not called; docs disagree on the boundary

Evidence
- The 00:30-09:00 check is hand-written in at least 12 places instead of calling
  `Get-WeatherHeavyWorkloadPolicyWindow` (`workload_admission.ps1:565-608`):
  `daily_refresh.ps1:99-100`, `integration_attempt_suite.ps1:185-186`,
  `bounded_worktree_test_suite.ps1:368-369`, `clob_tiering_run.ps1:82-83`,
  `clob_raw_tape_tiering_run.ps1:75-76`, `cold_snapshot_compression_run.ps1:35`,
  `storage_recovery_inventory_run.ps1:31`, `replay_cache_compression_run.ps1:20`,
  `production_cold_archive_run.ps1:40`, `memory_commit_guard.ps1:272-273`,
  `register_integration_attempt.ps1:83`, `integration_attempt_contract.ps1:1160`.
  Only `chain_recovery_run.ps1:135` calls the shared function. Values currently agree.
- `docs/operations/HOST_LOAD_POLICY.md:131` says PROTECTED 18:00-00:05; `:326` says 18:00-00:30.
  Scripts implement 00:30 (`quiet_window_merge.ps1:3251-3252`). 00:05-00:30 is the daily-roll slot
  (`:127`), so the table row is the stale one.
- Clock source is mixed: most scripts use host-local `Get-Date`; the storage/archive runners use
  `TimeZoneInfo 'Eastern Standard Time'` (`production_cold_archive_run.ps1:37-38`). Equal only
  while the host zone stays Eastern.
- DST: no script checks `IsInvalidTime` / `IsAmbiguousTime`. `new_integration_attempt.ps1:89-98`
  admits merge triggers 01:00-03:40 by `TimeOfDay`, which includes the non-existent 02:00-03:00 on
  2027-03-14 and the repeated 01:00-02:00 on 2026-11-01. Deadline arithmetic is wall-clock and
  otherwise behaves.
- Expired dated exceptions remain as live branches in the admission path:
  `workload_admission.ps1:573-594, 1456-1468`, `quiet_window_merge.ps1:3229-3241`,
  `cold_snapshot_compression_run.ps1:29`, `storage_recovery_inventory_run.ps1:25`.

Recommendation: one exported function for "which window am I in", called everywhere; delete
expired exception tokens; fix the policy table row.

### ps-ops-9 (LOW, new) - scheduler state is not reproducible from the repo; hard-coded paths; a password on a command line

Evidence
- `AGENTS.md:5-8` says these files are the source of truth for task names, cadences and actions.
  No registrar exists in `scripts/` or `tools/` for tasks that `status.ps1` expects:
  `WeatherStalenessSweep` (`status.ps1:3427`; zero hits in `docs/operations`),
  `WeatherStreakCaptureMonitor` (`streak_capture_monitor.ps1:5`),
  `WeatherCapturePriorityGuard` (`capture_priority_guard.ps1:12`), `WeatherOneShotPush`,
  `WeatherDataMirror`, `WeatherMirrorRestoreVerify`. The mirror script itself lives outside the
  repo (`verify_mirror_restore.ps1:17, 47, 62` reference `C:\Users\micha\ops\`), contrary to
  `AGENTS.md:21-23`.
- Hard-coded production checkout, contrary to `AGENTS.md:127-129`: `boot_recovery.ps1:37`
  (a script that can `git reset --hard`), `health_watchdog.ps1:26`, `streak_capture_monitor.ps1:7`,
  `verify_mirror_restore.ps1:22`, `mm_countability_report.ps1:16`.
- Credential (type and location only): `verify_mirror_restore.ps1:26, 72-73` reads a plaintext
  SMB password file from the user profile and passes it as an argument to `net use`, where it is
  visible to anything that enumerates process command lines - which several of this project's own
  guards do. The mirror is paused by owner decision, so this path is dormant.
- Thirteen of the 22 registrars set no `$ErrorActionPreference` (grep: only 9 do). The four of
  those I read in full (`register_snapshot_supervisor.ps1`, `register_location_config_refresh.ps1`,
  `register_memory_commit_guard.ps1`, `register_health_watchdog.ps1`) do no asserting readback, so
  they print "Registered scheduled task" even if `Register-ScheduledTask` raised a non-terminating
  error. The streak-critical snapshot supervisor therefore has a weaker registrar than the
  tiering and boot-recovery tasks, which verify exactly. I did not open the other nine.

Recommendation: add registrars (or an exported-XML inventory) for the unowned tasks; derive
`$repo` from `$PSScriptRoot`; use a `PSCredential` + `New-SmbMapping` if the mirror returns; give
the supervisor registrars the same readback as `register_clob_tiering.ps1`.

### ps-ops-10 (LOW, new) - `-f` binds tighter than `+`: tiering-skip message never names the job

Evidence: `scripts/ops/status.ps1:1401-1404`. The format operator applies only to the second
string literal, which has no placeholder, so the message is emitted with a literal `{0}`.
A multiline grep for the same shape across `scripts/ops` found only this instance;
`workload_admission.ps1:1473-1476` shows the correct parenthesised form.
Impact: cosmetic, but it is the message that explains why disk reclaim did not happen.
It is a sibling of the project's known "parses clean, binds wrong" class and is not in that ratchet.

## 4. Smaller observations (not ranked)

- `boot_recovery.ps1:659-699` writes its boot record only at the very end, after up to
  20 x 15 s + 21 x 15 s of waiting and ~41 Python cold starts; the task limit is PT15M
  (`register_boot_recovery.ps1:48`). In the compound worst case (capture not recovering and a
  marker rollback pending) the record that "is the only place an unattended outage is written
  down" may never be written. Inferred timing, verified structure.
- `market_making_daily_roll_task.ps1:49-52` starts Python detached and always `exit 0`; the
  scheduler result can never reflect the child. By design, but it means 0x0 carries no information.
- `streak_capture_monitor.ps1:6, 12, 27` combines `ErrorActionPreference = Stop`, `2>&1` on a
  native command, and an unconditional `exit 0`. A checker crash is visible only because PS 5.1
  happens to promote the stderr line to a terminating error; any non-3 exit without stderr is
  silently "no risk".
- `health_watchdog.ps1:25, 146-151, 204` runs under `SilentlyContinue` and writes its latest-state,
  state and briefing files with non-atomic `Set-Content` on the same volume it is warning about.
  At disk-full every alert channel fails together and quietly. There is no off-host or push
  channel in `scripts/ops` (grep for mail/webhook/toast: none).
- `chain_recovery_run.ps1:138-140` uses exit 2 for REFUSED while `:441` documents exit 2 as
  "readiness gates BLOCK, expected". Callers treat any non-zero as failure, so this is only
  ambiguity in the scheduler history.
- `chain_recovery_run.ps1:147-163` accepts an inherited lease by PID ancestry without creation
  time, unlike the rest of the lease code.
- `production_cold_archive_run.ps1:50-51, 156, 183` bounds every archive/reclaim invocation to
  300 s, 384 MB and 256 files, attended, one reviewed request each, and refuses 04:45-06:45.
  Safe, but it is a hard throughput ceiling on the only reclaim lane while disk is the binding
  constraint. Storage strategy belongs to another dimension.
- Monolith size: `status.ps1` 254 KB, `quiet_window_merge.ps1` 215 KB,
  `integration_attempt_contract.ps1` 90 KB, `workload_admission.ps1` 76 KB. `workload_admission.ps1`
  carries a hand-written C# JSON parser and a Python command-line tokenizer. 198 occurrences of
  `catch {}` / `SilentlyContinue` / `2>$null` across 35 files (50 in `status.ps1`, 25 in
  `boot_recovery.ps1`, 25 in `quiet_window_merge.ps1`).

## 5. Strengths (genuine)

- `windows_kill_on_close_job.ps1`: CREATE_SUSPENDED -> AssignProcessToJobObject -> ResumeThread,
  non-inherited handle, `TerminateAndWait` that proves zero active processes. Correct, and used by
  15 wrappers. No Python instruction can run outside containment.
- `workload_admission.ps1`: ownership is the open OS handle plus a Global mutex, not file
  existence; abandoned-mutex handling; PID + creation-time identity; fail-closed poison states.
- `settlement_backfill_one.ps1:198-307`: refuses to trust exit 0, verifies settled content per
  market against the registry-derived denominator, opens ledgers with `FileShare.ReadWrite` after
  the 2026-08-11 incident, one date per invocation.
- `status.ps1:1381-1407` and `:1603-1656`: explicitly treats scheduler 0x0 as non-evidence for
  tiering, and watches the settlement consequence rather than the chain event.
- S4U / Limited on every registrar (22 of 22 that set a principal); `register_clob_tiering.ps1`,
  `register_boot_recovery.ps1:59-98`, `register_training_window.ps1:161-216`,
  `register_storage_recovery_night.ps1:97-110` do exact post-registration readback.
- No `Invoke-Expression` anywhere; argument strings are built through
  `ConvertTo-WeatherWindowsArgumentString` / `ConvertTo-ScheduledTaskArgumentString` with correct
  backslash-quote escaping; paths are quoted; no credentials in scheduled-task actions.
- Comments record the incident each guard exists for, with dates. That institutional memory is
  unusually good.

## 6. Not covered

Not opened at all: `integration_attempt_contract.ps1`, `integration_attempt_merge.ps1`,
`reconcile_integration_attempt.ps1`, `close_integration_attempt.ps1`,
`dispatch_integration_attempt_recovery.ps1`, `assert_integration_attempt_success.ps1`,
`new_integration_attempt.ps1`, `production_baseline_scheduler_rpc.ps1`,
`adopt_execution_tape_after_merge.ps1`, `suite_gated_quiet_merge.ps1`, `roll_verdict.ps1` (exits
only), `workstation_heavy.ps1`, `portable_live_sdk.ps1`, `international_live_execution_host_status.ps1`,
the `international_live_templates/` launchers, `install_codex_host_load_hook.ps1`,
`cold_snapshot_compression_run.ps1`, `replay_cache_compression_run.ps1`,
`storage_recovery_inventory_run.ps1`, `storage_recovery_night_contract.ps1`,
`clob_raw_tape_tiering_run.ps1`, `bounded_execution_tape_probe.ps1`, `package_exact_tip_bundle.ps1`,
`register_nightly_retrain.ps1`, both `*_contract.ps1` token builders, the MM/taker/CLOB/observation
registrars, `mm_countability_report.ps1`, `streak.ps1`, `refresh_exchange_economics_snapshot.ps1`.
About 85 % of `status.ps1` and 97 % of `quiet_window_merge.ps1` were not read.
The live Task Scheduler, every log and receipt under `data/` and `scratch/`, and actual runtimes.

## 7. Open questions for the owner

1. Does `memory_commit_guard.log` show `creation identity changed before termination` on every
   kill attempt since 2026-08-23? (Confirms or refutes ps-ops-1.)
2. How long does one `status.ps1 -Json` pass take today, against the watchdog's 5-minute limit?
3. What did a1..a11 and the 09-14..09-17 storage tasks actually fail on - and for how many of them
   is there no artefact at all (ps-ops-6)?
4. Is the 50 GiB suite floor based on a measured temp/log footprint, or a round number?
5. Is "never delete a spent task" still wanted once its XML and hash are archived with the attempt?
