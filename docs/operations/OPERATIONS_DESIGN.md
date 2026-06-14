# Operations Design

## Target Shape

The long-term setup has three layers:

1. Windows Task Scheduler keeps the background loops alive after login, reboot,
   silent death, or stale-heartbeat hangs.
2. A lightweight desktop launcher starts the Streamlit dashboard and opens the
   Operations page.
3. The Streamlit Operations page is the human cockpit for health, loop control,
   code-version checks, logs, and supervisor status.

The launcher should not own the loops. If the launcher exits, Streamlit closes,
or Windows restarts, the capture loops should still be restored by the
registered supervisor tasks.

## Startup Flow After Reboot

1. Windows logon triggers:
   - `WeatherSnapshotLoopSupervisor`
   - `WeatherClobBookLoopSupervisor`
2. Those tasks run short-lived `ensure` commands:
   - `python -m src.snapshot_tracker --ensure`
   - `python -m src.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15`
3. Each `ensure` command starts or repairs exactly one detached loop.
4. Open the dashboard with:
   - `scripts/start_weather_dashboard.cmd`
   - or `scripts/start_weather_dashboard.ps1`
5. The launcher opens:
   - `http://localhost:8501/?market=ops`

## Loop Responsibilities

### Weather Snapshot Loop

Owns model/weather/market snapshot tapes at the slower cadence. It writes:

- `data/snapshots/loop_status.json`
- `data/snapshots/diagnostics.jsonl`
- `data/snapshots/loop_console.log`

### CLOB Book Loop

Owns fast Polymarket order-book capture. It writes:

- `data/snapshots/clob_loop_status.json`
- `data/snapshots/clob_diagnostics.jsonl`
- `data/snapshots/clob_loop_console.log`

## Runtime Version Signal

Each loop status file includes `runtime_identity`, captured when that loop
process starts. It records:

- git branch
- git commit
- dirty/clean flag
- dirty fingerprint
- source-tree fingerprint
- Python version

The Operations page compares that running identity with the current checkout.
If the page shows `Code State = different`, restart that loop to move it onto
the current code.

## Operator Page

The `Operations` sidebar page shows:

- current checkout identity
- weather snapshot loop state
- CLOB book loop state
- stale/different code count
- registered/missing supervisor task count
- loop PID, heartbeat age, last capture age, errors, pause state, mode, and
  last error
- Task Scheduler status for the two supervisor tasks
- status/diagnostic/log file locations

It can:

- start or repair all loops
- ensure, restart, stop, pause, or resume each loop individually
- stop all loops
- refresh status

## Deployment Routine

After changing code:

1. Run the focused tests for the changed area.
2. Open `Operations`.
3. Restart the affected loop, or use `Restart Weather` and `Restart CLOB` when
   shared code changed.
4. Confirm `Code State = current`.
5. Confirm heartbeats and captures resume.

## Why Not Put Everything In One .exe?

A clickable `.exe` or shortcut is useful for opening the dashboard, but it is
the wrong owner for long-running evidence capture. A launcher can be closed,
crash, or be skipped after reboot. Task Scheduler is the durable supervisor;
Streamlit is the control room.

If a true `.exe` is desired later, package only the dashboard launcher, not the
loops. The capture loops should remain supervised by the scheduled `ensure`
tasks.
