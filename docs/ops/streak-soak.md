# Code-soak streak — the #1 operational objective

The **streak** is the number of *contiguous* operationally complete Toronto
capture days. Fourteen in a row is the calendar/capture prerequisite for the
point-in-time lock; it does **not** by itself prove that the fourteen folders
are admissible. The release window additionally needs exact current
`complete` ledger revisions, strictly readable captured inputs and snapshot
tapes, complete captured-input self-hashes, no reconstructed inputs, matching
snapshot/settlement identity, and a passing production prelock/staging
receipt. **Protecting capture cleanliness outranks all other routine work on
this host**, but the release clock must report both properties.

## Check it in one command

```powershell
.\scripts\ops\streak.ps1            # human report
.\scripts\ops\streak.ps1 -Json       # machine-readable
.\scripts\ops\streak.ps1 -Monitor    # exit 3 if TODAY is trending to partial
```

(Equivalently: `venv\Scripts\python.exe scripts\ops\streak_status.py`.) It prints the
streak count, day 1, the projected lock date if every day stays clean, the recent
grade tape, the daily complete-rate, whether **today** is on track, and any promotion
lag. It is pure stdlib and imports nothing from the `weather` package, so it can never
roll a capture loop and runs even mid-refactor.

`streak.ps1` measures only the operational capture clock. A daily release-window
check must collapse the same authoritative ledger, then mark a date admissible
only when its latest revision is exactly `complete` and a bounded streaming
audit of that date's canonical tapes passes the strict predicate above. Report
the contiguous operational streak and contiguous admissible streak separately;
never infer the second from the first. Candidate qualification, route/base-graph
binding, and forward parity remain release-level gates, not properties of one
capture day.

Run the expensive grade once, after the settlement revision is final:

```powershell
venv\Scripts\python.exe -m weather.operations.release_admissibility_clock grade `
  --target-date 2026-07-27 `
  --snapshots-root data\snapshots `
  --ledger-root data\settlements `
  --receipt data\backtest\release_admissibility\receipts\2026-07-27.json `
  --fail-on-block
```

The command parses the bounded CSV/JSONL tapes row-by-row and persists one
self-hashed `release_admissibility_receipt_v1` with `status`, a stable
`reason.code`, the exact ledger revision, inventory counts, and every source
hash. Frequent status checks must never run that command. They may run the
receipt-only collapse:

```powershell
venv\Scripts\python.exe -m weather.operations.release_admissibility_clock collapse `
  --receipt-root data\backtest\release_admissibility\receipts `
  --clock-out data\backtest\release_admissibility\clock.json
```

`release_admissibility_clock_v1` is intentionally small. The status digest only
needs `evaluation_end_date`, `contiguous_pass_days`, `streak_start_date`,
`latest_status`, `latest_reason_code`, and `clock_sha256`. An unsettled tail
with `reason.code=ledger_label_missing` does not reset the most recent settled
streak; any settled `BLOCK` does.

## Full host status in one command

For a broader check — streak **plus** capture-loop priority, RAM/disk, the daily
chain, git/push state, scheduled-task health, and recent alerts — run:

```powershell
.\scripts\ops\status.ps1            # compact, interpreted digest
.\scripts\ops\status.ps1 -Json       # machine-readable; exit 2 if any FLAG
```

It encodes what is **expected vs anomalous** so only genuine problems surface. Known
conditions — the daily chain exiting `0x2` (model-skill gates BLOCK pre-release), the
tape backup broken since Jun 30 — go to `notes`, not `FLAGS`. A `FLAG` (capture loop
down, low RAM/disk, an unexpected task result, TODAY at risk) flips the verdict to
`ATTENTION`. It measures only the **persistent** capture loop's priority, ignoring the
transient per-cycle "hot capture" subprocesses (which run at Normal by design). Like the
streak checker it is host tooling and rolls nothing.

A temporarily disabled `WeatherTrainingWindow` is classified as intentional only when an
enabled root task named `WeatherTrainingWindowReenable*` has exactly one non-repeating time
trigger and its sole PowerShell action exactly enables the recurring window, then disables
itself. Its next run must be in the next 30 hours. A missing, malformed, disabled, expired, or
far-future re-enable therefore restores the ordinary `unexpectedly DISABLED` flag.

It also answers the questions that previously required a manual dig:

- **authoritative bounded-wake results** — for hash-bound
  `live-overnight-audits-*` and `live-night-salvage-*` Codex one-shots, the durable receipt outranks Task
  Scheduler's terminal code. Status verifies the action-bound runner hash,
  task/wake identity, run-time correlation, safety fields, and the exact PASS
  classification. A missing, malformed, mismatched, or explicit `FAIL` receipt
  is a FLAG even when a self-disarming task displays `0x0`;

  Preserved receipts are never rewritten when a runner later proves to have
  misclassified a completed Codex process. An optional adjacent
  `<wake>.correction.json` may supersede only that classification. Status
  accepts it only when it binds the original receipt hash and completed-agent
  handoff hash, the agent exited zero without timing out, the safety fields are
  clean, and the correction uses the narrow reviewed classification contract.
  The original receipt remains the immutable historical artifact;

  A non-self-disarming one-time task can remain `Ready` and enabled after it
  runs while `NextRunTime` is blank. That is a spent task, not an armed retry;
  use its result plus the durable log or receipt to classify the run.

- **capture iteration health** — status reads `consecutive_errors`,
  `last_error`, and the snapshot loop's clean-iteration fields through optional
  property lookup. One or two consecutive errors are a warning; three or more
  match the workers' own `ERRORING` threshold and become a FLAG. These fields
  supplement process/lock/heartbeat liveness and do not assume that every
  supervisor artifact shares one schema;

- **which** chain step failed and why (`failing step -> maker_paper_score ->
  maker_paper_input_budget_exceeded`), instead of a bare `error`, and whether a run is
  in flight right now (the stored `terminal` flag goes stale the moment a resume starts);
- **unattended resilience** — capture-critical tasks are S4U and the boot
  recovery task is S4U, so a pending reboot alone is a warning about a brief
  capture gap rather than a fleet-down claim. Status counts only enabled,
  non-spent Interactive tasks with scheduled work as reboot exposure; the
  deliberately Interactive on-demand push and mirror one-shots are excluded
  because the credential vault is unavailable under S4U. A pending reboot plus
  any remaining counted task and no auto-logon is a FLAG;
- **off-host mirror** freshness/success (nothing else watches it, and it is the only
  copy of `data\` that is not on this disk);
- a **capture alert raised on the current local capture day** is promoted to a FLAG — alerts are appended
  to `data/alerts/streak_capture_alerts.jsonl`, which nothing otherwise reads.

Four more were added on 2026-07-25, each because a status review needed something the
digest could not answer:

- **`WATCHDOG`** — the health watchdog's own heartbeat, flagged past 45 min (it runs every
  15). It is what alerts overnight while nobody is awake, so if *it* dies every window-aware
  alert stops silently and the first symptom is a morning with no briefing. Nothing else
  watched the watcher. The same line reports the last guarded merge attempt, and a
  `rolled_back` stage is a FLAG — that means capture did not survive a code roll.
- **`ARMED`** — tasks that have never run and are due within 16h, i.e. one-shot work
  scheduled for tonight. Such a task can be deleted, disabled or mis-scheduled and nothing
  would notice until the morning it failed to have run; one that is armed *and* disabled is
  a FLAG, because silence is its failure mode.
- **failure age** on the failing chain step. `daily_refresh_status.json` holds the last run
  until the next one, so a step that broke in the morning and was fixed that afternoon still
  reads as live breakage — on 2026-07-25 the reported `MemoryError` predated its own budget
  fix by 4.5h.
- **disk trend** — free space is point-in-time and says nothing about how long we have.
  A sample trail in `data/alerts/disk_free_trail.jsonl` gives a 24h burn rate and an
  estimated days-left. It samples `Get-PSDrive` only: a monitor must **never** recursively
  walk `data\`, which has starved capture before. Because the 05:00/06:00 tiering jobs
  reclaim one large daily batch, the 24-hour rate can temporarily describe intraday raw
  buildup rather than net retention. Status keeps that conservative number but demotes it
  to a warning when an available 48-hour window still shows at least 21 days of headroom;
  a short horizon on both windows remains a FLAG, and both tiering tasks must stay armed.

Alert lines also carry their age, since a two-day-old `AT_RISK` was rendering as a current
alarm.

## Overnight alerting (WeatherHostHealthWatchdog)

`status.ps1` answers "what is wrong right now" for a human who is looking.
`scripts/ops/health_watchdog.ps1` asks what nobody is awake to ask: **does this need
someone, and can it even be acted on at this hour?** It runs every 15 minutes (S4U, so it
survives a reboot with nobody logged on) and grades the same conditions differently
depending on the clock:

| Window (host local) | Meaning |
| --- | --- |
| 12:00–18:00 | graded capture window — the streak day is being decided; capture/memory faults are `CRITICAL` |
| 09:30–11:00 | daily chain — settlement and grading of yesterday |
| 00:30–09:00 | agent/ad-hoc heavy-work window — every heavy wrapper also needs the shared OS-held lease |
| 09:30–11:55 | repository-owned Stage-A chain only — absolute Job-owned child-tree teardown at 11:55 |
| 01:00–04:00 | quiet window — required for roll-sensitive merges; roll-free merges do not wait |
| 23:30–00:45 | day rollover — stale location config here blacks out capture |

Outputs, all under `data/alerts/`:

- `host_health_latest.json` — current state, always rewritten;
- `host_health_alerts.jsonl` — append-only, written on **state change**, on any `CRITICAL`,
  or every 6h as a heartbeat, so a standing condition does not spam the log and silence is
  distinguishable from a dead watchdog;
- `MORNING_BRIEFING.md` — regenerated every run: what is open now, each item's severity *and the
  window in which it can be acted on*, standing notes, and a 24h timeline. **Read this first
  after being away.**

Register or remove it with `scripts/ops/register_health_watchdog.ps1` (`-Unregister`).

## This host loses power (WeatherBootRecovery)

Event-log forensics on 2026-07-25 found **five unexpected shutdowns in 90 days**. Four had
`bugcheck=0`, `powerButton=0` and no BSOD — the signature of abrupt power loss rather than a
crash. That is roughly one every three weeks against a **14-day contiguous** streak
requirement, and none of them were ever visible: the digest reported a healthy host either
side of a 29-minute outage on 2026-07-21, which was day 1 of the current streak. It came back
37 minutes before the graded window opened.

An outage inside 12:00–18:00 ends the streak. **Power loss is the top uncontrolled risk to
the soak, and a UPS is the thing that removes it** — no amount of software makes an
unplanned outage free.

What software can do, and now does:

- `scripts/ops/boot_recovery.ps1` runs at every boot (`WeatherBootRecovery`, AtStartup, S4U,
  no delay). It rolls back any unverified guarded-merge tree as early as Task Scheduler
  permits, then waits on exact recovery evidence. Windows does not guarantee ordering
  among startup and logon tasks, so the zero-delay trigger minimizes but does not prove
  that a supervisor cannot briefly observe the tree before rollback. It records *why* we rebooted — distinguishing power loss from a bugcheck
  from a held power button — and verifies the capture loops came back **unattended** with the
  canonical exact three-worker recovery checker. A raw process count is recorded only as a
  diagnostic and cannot make `capture_recovered` true. This is the one failure mode that
  silences every other check. Appends to
  `data/alerts/boot_events.jsonl`. A first-landing task may pass
  `-ExpectedSelfSha256 <sha256>` so the pre-production recovery script fails before acting if
  its frozen worktree bytes move.
- It **heals an interrupted merge**. `quiet_window_merge.ps1` stages with `--no-commit`,
  deliberately keeping `MERGE_HEAD` until every required recovery proof passes, and
  journals a `preparing` marker before even staging the generated configs, then atomically
  refreshes it with the synchronized baseline, temporary pre-merge commit, and any active
  auxiliary producer's rollback identity before target code can enter the tree. A power cut
  in that interval therefore has an exact rollback target. Boot recovery first removes the
  target tree even if `origin/master` moved independently; it refuses only the later baseline
  reset in that divergent case. On the expected baseline it restores `master == origin/master`
  and preserves the two generated config contents as allowlisted working-tree drift. It retires
  the unchanged marker only after the canonical three-worker recovery checker and any required
  execution-tape status/lock/source identity pass, retrying that proof for up to five minutes
  while boot evidence catches up. A legacy unmarked `MERGE_HEAD` uses the same exact post-abort
  proof and conservatively gates any active execution-tape writer; raw process counts are only
  diagnostic. Boot evidence also lists the small exact set of Git workflow lock files and whether
  each predates the boot; it never deletes them automatically because safe cleanup requires a
  repository-wide Git mutation mutex and proof that no current writer owns the lock. A marker
  that does not bind the exact production repository, `master`, baseline,
  and reviewed tip is retained without moving the unrelated checkout. A recovery-proved explicit commit is not reset or
  pushed at boot; it is preserved and blocks another merge until its publication/receipt is
  explicitly reconciled. The merge tool refuses to start while `MERGE_HEAD` or its durable
  marker exists.
- `status.ps1` carries a `STABILITY` line: uptime and unexpected shutdowns in 90 days. One in
  the last 24h is a **FLAG**, because it means today's capture *grade* needs checking, not
  just today's process list.

Recovery itself is sound and was verified: every supervisor is S4U with a repeating 1–2
minute time trigger and `StartWhenAvailable`, so the loops restart with nobody logged on.
Windows Update active hours are 08:00–01:00, so its automatic restarts cannot land inside the
graded window.

## Is the off-host copy actually restorable? (WeatherMirrorRestoreVerify)

`WeatherDataMirror` reports robocopy's exit code, which says a copy **ran** — not that what
landed is readable, complete or correct. With the tape backup's restore drill disabled since
2026-06-30, that exit code was the *only* durability signal for 25 days, on a host that loses
power every few weeks.

`scripts/ops/verify_mirror_restore.ps1` (daily 05:20, after the 04:30 mirror) pulls files
**back** from `\\DESKTOP-RFCD2GH\weather-mirror` into a scratch directory and compares SHA256
against local. First run: 11 of 14 identical, zero problems. `status.ps1` reports it
separately from mirror freshness, because *copied recently* and *restorable* are different
claims and only one of them was ever checked.

Two things that decide whether the check is worth anything:

- It samples files that **predate** the last mirror run. Sampling the newest files is nearly
  worthless — capture rewrites the hot ones constantly, so every comparison returns "newer
  locally"; the first cut verified exactly one file out of nineteen. A file last written
  before the mirror ran must be byte-identical off-host, so each such comparison is a real
  test. For the same reason a file created *after* the run is `not_yet_mirrored`, not missing.
- It **skips entirely if the mirror is still running** (checked via the mirror's own lock
  file), because its `net use /delete` would otherwise tear the share out from under an
  in-progress robocopy. A skip leaves the previous result standing rather than writing a
  failure.

## Merging code at a scheduled time (quiet_window_merge.ps1)

Merging a branch whose modules a capture loop has imported makes the supervisors readopt
the new code (a `STALE_CODE` restart). If the code is bad, capture dies — and inside
12:00–18:00 that costs the streak day. `scripts/ops/quiet_window_merge.ps1` makes that a
guarded operation:

```powershell
.\scripts\ops\quiet_window_merge.ps1 -Branch origin/codex/... `
  -ExpectedTip <full-tested-commit-sha> `
  [-ExpectedSelfSha256 <frozen-wrapper-sha256>] [-DryRun] [-Force]
```

It stages the merge **locally without committing**, waits `-SettleSeconds` (default 300) for readoption, and proves all three
workers have matching status/lock PIDs, live processes, fresh heartbeats, and loaded-source
fingerprints matching the tree. A worker whose PID or loaded-source identity changed must also
advance its heartbeat during the settle. An unchanged worker need not advance merely because an
unrelated closure rolled; this matters for the snapshot worker's normal ten-minute cycle, which is
longer than the five-minute settle. If the active public execution-tape closure rolls, the same
gate directly requires its connected managed process, exact status/lock/process identity, clean
evidence integrity, current loaded-source fingerprint, and advancing post-readoption heartbeat.
An intentionally disabled and inactive optional producer remains disabled and is not made a merge
dependency. `MERGE_HEAD` remains present through these proofs; **only then** is the exact two-parent
merge committed. The wrapper next records the documentation transaction, starts
`WeatherOneShotPush`, and requires
`origin/master` to acknowledge the exact merge commit. If capture
does not recover it aborts the uncommitted merge — nothing published, no merge history to
rewrite — restores synchronized baseline while preserving generated config bytes, and holds the
workload lease for up to `-RollbackRecoverySeconds` (default 1200) until all affected active
producers prove they have re-adopted the previous code. Failure to prove
rollback adoption is recorded separately as `rollback_recovery_failed`; it is never reported
as a completed rollback. It refuses to run outside 01:00–04:00
without `-Force`, never inside 12:00–18:00, and never during the protected 18:00–00:30
near-close window. `-ExpectedTip` is optional for interactive use but required operationally
for a scheduled or already-reviewed merge: the script aborts before any automatic commit if
the named branch no longer resolves to that exact full SHA, and merges the immutable commit
object rather than the movable branch ref. The outcome lands in
`data/alerts/quiet_window_merge_last.json` and is surfaced by `status.ps1`.
An immutable attempt or hash-frozen bootstrap also passes
`-ExpectedSelfSha256`; the child verifies its own exact bytes before entering
the operational path. Roll classification and all later mutations remain
under the same shared workload lease, so a second guarded merge cannot change
the baseline between verdict and mutation.

Before fetch, generated-config commit, or merge, the wrapper also fail-closes unless
`WeatherOneShotPush` is the one enabled root task in `Ready` state with the canonical current-user
Interactive/Limited principal, `cmd.exe` push action, production working directory, and bounded
log redirection. This catches publication dependency drift while rollback is still trivial rather
than predictably stranding a recovery-proved commit after the roll. It repeats that exact task
check immediately before starting the push. At the same boundary it re-proves checked-out
`master`, exact local/remote Git identity, the unchanged documentation marker and immutable
snapshot, all three capture workers, and any required execution-tape writer. A failed boundary
proof leaves the commit and marker unpublished for reviewed recovery.

After capture recovery and before publication, the wrapper also records the
exact local merge commit through `weather.operations.documentation_transaction
begin`. It binds the resulting pending-state SHA256 and content-addressed snapshot
into both the active marker and terminal report. Once `begin` has been invoked,
an error or marker-write failure preserves the recovery-proved local merge for
reviewed, idempotent resume: resetting it could orphan a shared pending transaction
that the child already updated. Successful stacked merges accumulate in one
hash-bound pending transaction whose completion is due by 09:00; see
`docs/documentation-maintenance.md`.

For new scheduled integrations, do not schedule this wrapper directly and do
not freeze one branch tip as the only permissible state for the whole night.
Use the [immutable integration-attempt runbook](../operations/INTEGRATION_ATTEMPT_RUNBOOK.md).
Its merge task still delegates the actual roll, rollback, documentation
transaction, and push to `quiet_window_merge.ps1`, but first requires the
hash-bound preflight and full-suite receipts. A failed attempt remains frozen;
a reviewed repair receives a new attempt id and cannot rewrite the old proof.
The attempt wrapper passes `-AttemptReportPath` as an absolute, unused path whose
parent already exists. The quiet-merge child creates that terminal report through
an exclusive same-directory atomic rename before updating the mutable latest/history
slots, so killing the parent immediately after the child returns cannot lose or
misattribute the attempt-local quiet-merge proof. Mutable compatibility reports never
substitute for that path: the child verifies the immutable report hash again before it
may retire an active recovery marker.

The legacy `suite_gated_quiet_merge.ps1` path remains only for an already
scheduled, hash-frozen bootstrap. Its optional `-SuiteRunningWaitMinutes`
allows one bounded wait when the exact suite task is still `Running`; the
default remains an immediate refusal. After waiting, the gate re-resolves the
singleton task and re-hashes its complete exported XML before it can consume
the suite verdict. A missing, replaced, non-terminal-at-deadline, or failed
task still refuses without invoking the quiet merge.

While the child is non-terminal it maintains
`data/alerts/quiet_window_merge_in_progress.json`. Pre-commit phases are
unverified and boot recovery rolls them back automatically. Once core capture,
any required execution tape, and the documentation transaction are proved, the
marker reaches `documented_unpublished` before push starts. A hard kill after
the remote accepts that commit can therefore be distinguished from an
unverified roll: boot recovery preserves the exact commit and marker, exits
nonzero, and blocks another merge. Do not delete or hand-edit the marker. For an
integration attempt, hash it and run the reviewed reconciler with the frozen
manifest, its expected SHA256, `-ExpectedActiveMarkerSha256`, and a durable
`-ReviewReference`. The reconciler rechecks exact local/remote Git identity and
capture, records `MERGED_RECONCILED` without downstream authority, and only then
retires the active marker. If local master remains ahead of `origin/master`, the
merge is verified but unpushed and still requires reviewed recovery; boot never
publishes it.

Two behaviours that are easy to get wrong, both found by testing it before its first real run:

- **The tracked tree is dirty most nights.** `WeatherLocationConfigRefresh` rewrites
  `config/locations.json` and `config/location_market_events.json` every 6h, including at
  ~00:00. A naive "refuse if dirty" guard therefore aborts normal merges. Exactly those two
  fleet-generated paths are
  committed automatically before the merge. The report distinguishes the original synchronized
  `baseline_commit` from this temporary `pre_merge_commit`. On failure the merge is first restored
  to the latter, then a mixed reset returns `master` to the baseline while retaining the exact
  generated bytes as the same two allowlisted modifications. That makes the failed attempt
  successor-resumable instead of leaving an unpublished local commit ahead of `origin/master`.
  Anything modified outside that exact set still aborts. The live scheduler inventory belongs under ignored
  `data/alerts/OPERATING_SCHEDULE.md` and cannot dirty a tracked document.
- **Never redirect git's stderr inside the wrapper** (`*>$null`, `2>&1`). Under `$ErrorActionPreference='Stop'`,
  PowerShell 5.1 wraps each redirected stderr line in a `NativeCommandError` and terminates —
  and git writes routine notices there, so a `CRLF will be replaced by LF` warning is enough
  to kill the script *between* `git merge` and `git merge --abort`, leaving a half-merged
  tree that rolls the fleet with no rollback in flight. Scheduled callers redirect the wrapper's
  complete stream, so every mutating/fetch Git call temporarily scopes native stderr to Continue
  and still checks the actual process exit code.

`stage: merged_unpushed` means the credential-bearing `WeatherOneShotPush` task did not acknowledge
the merge within its bounded wait. The merge and recovery proof succeeded, but publication did
not; the quiet wrapper never attempts an interactive or S4U `git push` itself. This terminal
retains the `documented_unpublished` active marker. First compare the marker's exact merge
commit with local `master` and `origin/master`. If the remote already equals that commit, use
the hash-bound active-marker reconciliation path above. If local master alone equals it and
the branch/attempt is still reviewed for publication, an active operator may retry only the
credential-bearing `WeatherOneShotPush` task, require `origin/master` to acknowledge that exact
commit, and then use the same reconciler. If the remote moved anywhere else, do not push or
reset; preserve the marker and resolve the divergence explicitly. `rollback_recovery_failed`
also retains its marker until boot or a reviewed recovery proves the exact rollback target and
affected producers healthy.

After the final guarded merge is pushed, the next bounded morning closeout must
complete the documentation transaction in `docs/documentation-maintenance.md`:
rewrite `STATE_OF_PLAY.md`, update the owning roadmap items and evidence canon,
regenerate/lint the active backlog, and run the agent-docs audit. Branch-staged
documentation is proposed state before integration and current truth only
after the exact commit is in production history.

### Bounded execution-tape proof

After a reviewed execution-tape producer lands, use
`scripts/ops/bounded_execution_tape_probe.ps1` for the first production proof instead of
starting an unbounded process and killing it later. The probe is restricted to 01:00–04:00,
requires the reviewed full SHA to be an ancestor of synchronized production master, and runs
the read-only producer in a kill-on-close Windows Job for a bounded interval. It fails unless
the new session observes the complete active seed set connected, writes at least one cleanly
routed execution observation, adds no parse or routing errors, stops cleanly, stays inside
working-set and host-commit ceilings, and leaves all three capture workers healthy with an
advancing snapshot heartbeat. A connected socket plus one routed observation does not prove
that every subscribed asset traded or that the public stream can identify our own fills.
It writes the latest result and append-only history under `data/alerts/`. The probe neither
registers nor authorizes continuous capture.

## Why every task is S4U

Scheduled tasks with `LogonType=Interactive` run **only while a user session exists**. On
2026-07-24 all but one `Weather*` task was Interactive with no auto-logon, so a reboot with
nobody logged in would have left the host dark and silent — capture, chain, streak monitor
and the alerting itself — until someone logged in. Everything unattended-critical is now
`S4U` (runs whether or not anyone is logged on, no stored password), verified by
post-conversion runs.

`WeatherOneShotPush` is the deliberate exception: pushing needs the Windows credential
vault, which an S4U task in session 0 cannot reach. It is not unattended-critical — commits
simply queue until someone is logged on — so it stays Interactive and is excluded from the
reboot-exposure check.

## Where the truth lives (read this before trusting any number)

- **Authoritative grade source:** `data/settlements/toronto/ledger.jsonl` — an
  append-only ledger; collapse it to the *latest written* row per `target_date`.
- **NOT authoritative:** `data/backtest/market_day_labels.csv` — a downstream promotion
  artifact that **lags**. It can show an older date (or `partial`) while the ledger
  already carries the newer `complete` grade. If the two disagree, the ledger wins and
  the CSV just hasn't been promoted yet (run the daily chain). The checker flags this
  as `PROMOTION LAG`.
- **Operational streak eligibility:** `quality_grade in {complete,
  manual_override}`. This is **stricter** than `promotion_countable` — a
  `partial` day can be countable for model *scoring* but does not advance the
  operational streak. Never use `manual_override` to paper over a real gap.
- **Release-lock eligibility:** the latest staging-receipt revision must be
  exactly `complete`; `manual_override` does not satisfy
  `latest_toronto_lock_revisions`. The operational counter can therefore reach
  14 while the release-admissible counter remains below 14.

## What makes a day `complete` vs `partial`

From `src/weather/collection/collection_health.py`:

- **Afternoon material window = 12:00–18:00 local** (`AFTERNOON_START/END_HOUR`).
- A **gap** = two consecutive snapshot captures spaced **> interval × 1.5** apart. The
  snapshot loop interval is 10 min, so the threshold is **15 minutes**.
- A day is **clean** only if captures span 12:00→18:00 **and** have no in-window gap.
- Gaps *outside* 12:00–18:00 do not count. (This is why 2026-07-21 graded `complete`
  despite an 18-min gap at 11:32 — it was before the window.)
- Snapshot cadence is the dominant gate; source-status / observation coverage also feed
  the grade, but an in-window snapshot gap is the usual cause of a `partial`.

The grade is **permanent** once the day's capture is done — it cannot be backfilled.
Backfilling settlement recovers *scoring* evidence and calendar continuity, not streak
days (see `memory/missed-chain-day-leaves-settlement-hole.md`).

## Host protection (why this PC is tuned the way it is)

The recurring streak-killer is an in-window snapshot gap caused by **resource
contention** on this 16 GB host. Defenses in place:

1. **Capture loops run at `AboveNormal` priority, enforced by a guard.** Windows tasks
   default to priority 7 (**BelowNormal**), which let every Normal-priority app preempt
   the capture loops under load. The catch: multiple restart paths reset priority and
   *none* of the obvious fixes survive all of them — a supervisor `ensure` respawn comes
   back at **Normal**, and the **01:00 training-window restart re-launches the snapshot
   loop as `python.exe` at `BelowNormal`**. So `WeatherCapturePriorityGuard`
   (`scripts/ops/capture_priority_guard.ps1`) runs every 5 min, 24/7, and re-asserts
   `AboveNormal` on the three capture workers (matching both `python.exe` and
   `pythonw.exe`). The supervisor task priorities are also set to 3 as a belt-and-braces
   default. Verify with
   `Get-Process python,pythonw | Select Id,PriorityClass` — the snapshot/microstructure/
   observation workers should read `AboveNormal` (they will self-heal within 5 min if not).
2. **Trading bots (`taker_bot`, `market_making_run`) stay `BelowNormal`** — they are
   not streak-critical and must yield to capture.
3. **Heavy daily-chain steps are memory-admission-gated** so they don't start unless
   enough RAM is free (`daily_refresh_resources.py`).
4. **Commit discipline:** commits touching loop-loaded modules *roll* the capture loops
   (a brief worker restart). Do them **only in the 01:00–04:00 quiet window**, or batch
   to a single conscious roll. `.ps1`/docs/config commits are roll-free. See
   `memory/commit-triggered-fleet-rolls.md`.

### If today shows `AT_RISK`

1. Check free RAM: `Get-CimInstance Win32_OperatingSystem | % { $_.FreePhysicalMemory/1MB }`.
   If low, close/kill non-essential resident apps (VS Code, ChatGPT tray) to relieve
   memory pressure — that is the usual cause.
2. Confirm the snapshot loop is alive and fresh; the supervisor respawns a dead worker
   within a minute, but a *stalled* (not dead) loop needs a manual restart.
3. Avoid any daytime commit that would roll the loops until the window closes at 18:00.

## The structural fix

At the current ~50%-per-day complete rate we have never held more than 3 clean days in
a row, so 14 contiguous is not reachable by luck. The lever that actually moves the odds
is the **two-host split**: move VS Code, the interactive agent, and all research load
onto the 32 GB workstation so this box runs lean (capture loops + scheduled chain only).
See `memory/two-host-split-2026-07-21.md` and `memory/streak-clock-2026-07-16.md`.
