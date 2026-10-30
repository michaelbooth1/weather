# Recorder keepalive (Lane L13, 2026-10-30)

Research / shadow only. Owner decision 6 approved it in principle; registration needs the owner's yes through the
coordinator.

## Why

At 21:45Z on 2026-10-30 all ten workstation forward recorders were killed by accident. They stayed down until they were
restarted by hand. Only HRRR had a keepalive.

## What it does

`tools\research\recorder_keepalive.ps1` runs every 15 minutes. It makes no fetches of its own. For each recorder:

- **STOP file.** If the recorder's output directory holds a `STOP` file, the recorder is logged `stopped` and never restarted.
- **Alive check.** Otherwise liveness is checked exactly as that recorder's own launcher checks it: the PID in `<OutDir>\recorder.pid` must be alive, and its CommandLine must contain the recorder module name.
- **When it is down,** the keepalive runs that recorder's **existing launcher** from the live worktree, unchanged.
  - Those launchers keep their own blob pin, STOP-file check and alive refusal, and start the recorder WMI-detached with `--wait-lock-seconds 120`.
  - Before running a launcher, the keepalive checks the launcher's sha256 against its own pin and refuses on a mismatch or a missing file.
  - A launcher still running after 90 s is killed. The recorder it started is detached and survives.
- **HRRR is check-only.** Its own task, "L13 HRRR forward recorder keepalive (launcher)", already restarts it every 15 minutes. This keepalive logs HRRR's state but never starts it, so the two cannot double-start it. To fold HRRR in later, set its `restart` to `$true` and retire that task, in one reviewed change.

The pinned registry:

| Recorder | Worktree | Output directory |
| --- | --- | --- |
| ECMWF ENS | `C:\wt\l13ens` | `C:\t\ecmwf_ens\forward` |
| ECCC GEM | `C:\wt\l13gem` | `C:\t\eccc_gem\forward` |
| GEFS 00-12-18Z | `C:\wt\l13gc` | `C:\t\gefs_cycles\forward` |
| GEFS 06Z | `C:\wt\l13g` | `C:\t\l6g\forward\gefs` |
| HRRR (check-only) | `C:\wt\l13` | `C:\t\l13\hrrr_forward` |
| MOSMIX | `C:\wt\l13mx` | `C:\t\mosmix\forward` |
| NBM text | `C:\wt\l13nbm` | `C:\t\nbm_text\forward` |
| L3 T+1 price | `C:\wt\l3t1rec` | `C:\t\t1_prices\forward` |
| L8 Open-Meteo previous runs | `C:\wt\omprevrec` | `C:\t\om_prev_runs\forward` |
| IEM MOS | `C:\wt\l13iem` | `C:\t\iem_mos\forward` |

- The launcher sha256 pins are in the script.
- `tests/sources/test_recorder_keepalive.py` checks the pins against the live launchers whenever those files exist.
- **Re-pinning.** When a recorder's launcher changes (for example, a re-pin after a recorder upgrade), the keepalive logs `refused` for that recorder until its pin is updated here. This is deliberate: it never runs a launcher nobody reviewed.

## Log: the per-recorder gap list

- One JSON line per recorder per run goes to `C:\t\recorder_keepalive\keepalive_<yyyyMM>.jsonl`.
- Each line holds:
  - `at_utc` and `recorder`;
  - `state`: `alive`, `dead` or `stopped`;
  - `pid`;
  - `action`: `none`, `launched`, `would_launch`, `not_restarted`, `refused`, `launcher_timeout` or `error`;
  - `detail`;
  - after a launch, `state_after`.
- A recorder's gaps are its runs of `dead` lines. Each gap is bounded by the 15-minute checks on either side.
- **Volume.** About 1,000 lines, roughly 120 KB, per day.

## Controls

- `C:\t\recorder_keepalive\STOP` stops the keepalive: one line is logged and nothing is checked.
- `-CheckOnly` logs every state and what would be done, and starts nothing.
- A local mutex prevents overlapping manual runs; the task itself uses IgnoreNew.
- `-RegistryPath` swaps in a fixture registry, for tests only. Under `WEATHER_TASK_TEST=1` the keepalive refuses to run without one.

## Task

`tools\research\register_recorder_keepalive_task.ps1` registers task `L13 recorder keepalive (15 min)`:

- a time trigger repeating every 15 minutes with no end;
- IgnoreNew, StartWhenAvailable off, ExecutionTimeLimit PT14M, Interactive/Limited;
- the action runs the keepalive from the pinned worktree `C:\wt\l13rk`.

The registrar:

- requires `-ExpectedLauncherSha256`, the keepalive script's sha256;
- refuses reserved characters in the task name, an existing task, and an interval below 5 minutes;
- refuses the real ScheduledTasks module under `WEATHER_TASK_TEST=1`.

Its tests run only behind the hardened stub harness.

## Receipts (2026-10-30 23:33Z)

- **`-CheckOnly` against the real registry:** all ten recorders were `alive` and nothing was started. The run took about one second.
- **Stubbed `-WhatIf` with the real name:** no mutations and no error.
- Both receipts are in `C:\t\recorder_keepalive_receipt`.
