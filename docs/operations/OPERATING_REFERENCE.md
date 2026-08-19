# Operating reference

**Generated — do not hand-edit.** Regenerate with:

```powershell
.\venv\Scripts\python.exe -m weather.operations.operating_reference `
    --out docs/operations/OPERATING_REFERENCE.md `
    --schedule-out data/alerts/OPERATING_SCHEDULE.md
```

**Deterministic on purpose — no timestamp is embedded.** For freshness use
`git log -1 -- docs/operations/OPERATING_REFERENCE.md`. A generated file that carried
its own render time would dirty the tree on every refresh, which blocks the release
build's clean-tree gate. Because this output is stable, the daily refresh doubles as a
**drift detector: if regenerating produces a diff, something real changed.**

This exists because durable operational facts live in Python constants and
PowerShell guards. Constants below are **imported at render time**, never copied,
so they cannot drift. A renamed or deleted constant fails this generator loudly.

## Protected windows

| Window | Name | Why | Owner |
| --- | --- | --- | --- |
| **12:00-18:00 local** | Graded capture window | The streak verdict is computed here (see AFTERNOON_START/END_HOUR). Never merge a roll-sensitive branch, run the chain, backfill, or reboot inside it. | `weather.collection.collection_health` |
| **01:00-04:00 local** | Quiet merge window | The only window a ROLL-SENSITIVE branch may be merged, because landing one makes the capture supervisors readopt code. Roll-free branches do not need it. | `scripts/ops/quiet_window_merge.ps1` |
| **18:00-00:05 local** | Near-close capture | Near-close fast CLOB capture, MM quoting, and settlement watch. Policy says nothing heavy, ever. Weigh any exception against what is actually live at the time. | `docs/operations/HOST_LOAD_POLICY.md` |

## Derived rules — the relationships that bite

Each value below looks reasonable on its own. What goes wrong is the *relationship*,
and no single constant expresses it, so it cannot be found by grepping.

| Rule | Value | Why | Owner |
| --- | --- | --- | --- |
| **A capture gap becomes fatal at `interval x 1.5`** | 10 min cadence -> **15 min** doom threshold | `detect_gaps(times, interval_minutes, tolerance=1.5)` — the 15 minutes is derived, not a literal, so grepping for '15' finds nothing. Two consecutive missed capture cycles exceed it and the Toronto day becomes PARTIAL. | `weather.collection.collection_health.detect_gaps` |
| **Loop recovery must beat that threshold** | supervisor `--ensure` every **2 min** | The supervisor exists to survive silent deaths AND hangs (a stale heartbeat with a live PID). Its ensure cadence is fast, but hang detection is not the same as ensure cadence: on 2026-08-08 a hung snapshot loop took ~19 minutes to be declared DEAD and restarted, which exceeded the 15-minute threshold and cost the day. **A supervisor that recovers slower than interval x 1.5 cannot save a day from a hang.** | `scripts/ops/register_snapshot_supervisor.ps1` |

## Governing constants

| Constant | Value | Meaning | Why it matters |
| --- | ---: | --- | --- |
| **`AFTERNOON_START_HOUR`**<br/>`weather.collection.collection_health` line 31 | `12` | Local hour the graded capture window opens. | A Toronto day's CLEAN/PARTIAL verdict is computed only over this window, so capture gaps outside it cannot cost a streak day — and anything heavy inside it can. |
| **`AFTERNOON_END_HOUR`**<br/>`weather.collection.collection_health` line 32 | `18` | Local hour the graded capture window closes. | Once it closes the day's streak verdict is banked and cannot be changed by a later gap. |
| **`EARLY_HOUR_START_HOUR`**<br/>`weather.collection.collection_health` line 33 | `0` | Local hour the early-hour evaluation window opens. | Early-hour model performance is scored over this window; it does not gate the streak. |
| **`EARLY_HOUR_END_HOUR`**<br/>`weather.collection.collection_health` line 34 | `8` | Local hour the early-hour evaluation window closes. | Bounds the early-hour Brier comparison that blocks promotion. |
| **`FREE_REPLACEMENT_MIN_HEALTHY_FAMILIES`**<br/>`weather.collection.collection_health` line 55 | `3` | Minimum healthy free source families required. | Paid weather providers are unsupported, so free-source health is the only path. |
| **`COMPLETE_DAY_MIN_ROWS`**<br/>`weather.backtesting.settlement_ledger` line 34 | `18` | Minimum hourly rows for a settlement day to count as complete. | This is NOT a knob: it decides both whether settlement trusts the daily summary and whether a day counts toward the streak. Lowering it to unblock a retrain silently changes settlement truth. |
| **`POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS`**<br/>`weather.calibration.pooled_training` line 54 | `7` | Maximum age, in days, of the selection universe's latest target date when a production point-in-time lock is taken. | THE CAPTURE STREAK HAS A SHELF LIFE AND THIS IS IT. A banked run of contiguous complete days stops being usable for a production PIT lock once its LATEST day is older than this. So a stalled settlement chain does not merely delay the retrain — it ages out evidence already earned. Found 2026-08-09; it was written nowhere and the relationship to the settlement backlog is invisible from either number alone. |
| **`MATERIAL_COVERAGE_WINDOW`**<br/>`weather.backtesting.settlement_ledger` line 45 | `12:00-18:00 local` | Human-readable coverage window for material capture. | Should agree with the afternoon window above; disagreement is a defect. |

## Live timetable

The scheduler is dynamic host state and is deliberately not committed here. Read
`data/alerts/OPERATING_SCHEDULE.md` on the production host or query Task Scheduler
directly. The countability refresh regenerates that ignored report.

## Update this file when

Never by hand. Add a row to `GOVERNING_CONSTANTS` in
`src/weather/operations/operating_reference.py` when a constant starts governing an
operator decision, then regenerate. The bar for inclusion is: *would someone have to
read source to answer a 3am question?*
