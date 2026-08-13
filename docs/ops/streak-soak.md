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

It also answers the questions that previously required a manual dig:

- **which** chain step failed and why (`failing step -> maker_paper_score ->
  maker_paper_input_budget_exceeded`), instead of a bare `error`, and whether a run is
  in flight right now (the stored `terminal` flag goes stale the moment a resume starts);
- **unattended resilience** — a pending reboot combined with logon-dependent tasks and
  no auto-logon is a FLAG, because almost every `Weather*` task is
  `LogonType=Interactive` and therefore does not run at all after a reboot with nobody
  logged in. That failure mode also silences the monitoring itself, so it has to be
  surfaced continuously rather than alerted on;
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
  walk `data\`, which has starved capture before.

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
| 01:00–04:00 | quiet window — the only safe slot for code merges and heavy steps |
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
  2-minute delay). It records *why* we rebooted — distinguishing power loss from a bugcheck
  from a held power button — and verifies the capture loops came back **unattended**, which
  is the one failure mode that silences every other check. Appends to
  `data/alerts/boot_events.jsonl`.
- It **heals an interrupted merge**. `quiet_window_merge.ps1` merges locally and waits five
  minutes before deciding, so a power cut inside that window leaves `MERGE_HEAD` and a merged
  working tree — and the supervisors would readopt unreviewed half-merged code on the way
  back up, with no rollback in flight. An interrupted merge was never approved, so it is
  undone. The merge tool also refuses to start while `MERGE_HEAD` exists.
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
  -ExpectedTip <full-tested-commit-sha> [-DryRun] [-Force]
```

It merges **locally**, waits `-SettleSeconds` (default 300) for readoption, proves the loop
count did not fall and the snapshot heartbeat advanced, and **only then** pushes. If capture
does not recover it resets to the pre-merge commit — nothing published, no history to
rewrite, and the supervisors readopt the previous code. It refuses to run outside 01:00–04:00
without `-Force`, never inside 12:00–18:00, and never during the protected 18:00–00:30
near-close window. `-ExpectedTip` is optional for interactive use but required operationally
for a scheduled or already-reviewed merge: the script aborts before any automatic commit if
the named branch no longer resolves to that exact full SHA, and merges the immutable commit
object rather than the movable branch ref. The outcome lands in
`data/alerts/quiet_window_merge_last.json` and is surfaced by `status.ps1`.

Two behaviours that are easy to get wrong, both found by testing it before its first real run:

- **The tracked tree is dirty most nights.** `WeatherLocationConfigRefresh` rewrites
  `config/locations.json` and `config/location_market_events.json` every 6h, including at
  ~00:00 — so a naive "refuse if dirty" guard aborts almost every run. That named pair is
  committed automatically before the merge (regenerated config is not *work*; the fleet
  rebuilds it within 6h), and the rollback point is taken **after** that commit so a rollback
  undoes only the merge. Anything modified outside that pair still aborts.
- **Never redirect git's stderr** (`*>$null`, `2>&1`). Under `$ErrorActionPreference='Stop'`,
  PowerShell 5.1 wraps each redirected stderr line in a `NativeCommandError` and terminates —
  and git writes routine notices there, so a `CRLF will be replaced by LF` warning is enough
  to kill the script *between* `git merge` and `git merge --abort`, leaving a half-merged
  tree that rolls the fleet with no rollback in flight.

Expect `stage: merged_unpushed`: the task is S4U, so its `git push` (and `git fetch`) cannot
reach the credential vault. The merge and the capture verification still happen; the commit
simply waits for `WeatherOneShotPush`, and `status.ps1` says so.

### Bounded execution-tape proof

After a reviewed execution-tape producer lands, use
`scripts/ops/bounded_execution_tape_probe.ps1` for the first production proof instead of
starting an unbounded process and killing it later. The probe is restricted to 01:00–04:00,
requires the reviewed full SHA to be an ancestor of synchronized production master, and runs
the read-only producer in a kill-on-close Windows Job for a bounded interval. It fails unless
the new session proves full routed coverage, writes at least one new execution observation,
adds no parse or routing errors, stops cleanly, stays inside working-set and host-commit
ceilings, and leaves all three capture workers healthy with an advancing snapshot heartbeat.
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
