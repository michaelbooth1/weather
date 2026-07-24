# Code-soak streak — the #1 operational objective

The **streak** is the number of *contiguous* `complete`-grade Toronto capture days.
Fourteen in a row unlocks the point-in-time window that bootstraps the first inactive
model release (release #1), which is the gate to the entire learning loop. **Protecting
capture cleanliness outranks all other routine work on this host.**

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

## Where the truth lives (read this before trusting any number)

- **Authoritative grade source:** `data/settlements/toronto/ledger.jsonl` — an
  append-only ledger; collapse it to the *latest written* row per `target_date`.
- **NOT authoritative:** `data/backtest/market_day_labels.csv` — a downstream promotion
  artifact that **lags**. It can show an older date (or `partial`) while the ledger
  already carries the newer `complete` grade. If the two disagree, the ledger wins and
  the CSV just hasn't been promoted yet (run the daily chain). The checker flags this
  as `PROMOTION LAG`.
- **Streak eligibility:** `quality_grade in {complete, manual_override}`
  (`point_in_time_evaluation.py: COUNTABLE_LABEL_QUALITIES`). This is **stricter** than
  `promotion_countable` — a `partial` day is countable for model *scoring* but does
  **not** advance the streak. Never use `manual_override` to paper over a real gap.

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
