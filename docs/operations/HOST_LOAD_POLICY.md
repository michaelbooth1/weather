# Host Load Policy — Dedicated Capture Host

Status: adopted 2026-07-12 after the commit-exhaustion incident (below).
Owner: operations. This host is dedicated to the weather platform; the policy
spreads load across the 24-hour day so capture — the one workload that cannot
be rescheduled — is never starved.

## Host capacity (measured 2026-07-12)

| Resource | Value | Note |
| --- | --- | --- |
| Physical RAM | 15.7 GB | smallest resource on the box |
| Pagefile | 48 GB allocated | commit limit ~63.7 GB |
| Disk free | ~385 GB | data writes ~50-65 GB/day → ~6-7 days headroom |
| data/ growth (24h sample) | snapshots 23.4 GB, taker_runs 2.7, reanalysis 2.5, backtest 1.6, wunderground 1.4 | snapshots dominate |

## The 24-hour map (America/Toronto)

| Window | What runs | Load class |
| --- | --- | --- |
| 00:05–00:30 | taker/MM daily roll-over | brief spike |
| 00:30–09:00 | steady-state capture only (loops + supervisors) | **QUIET — heavy work goes here** |
| 09:30–12:30 | Stage A settlement chain (labels, scorecards, tiering, parquet incremental) | heavy, scheduled |
| 12:30–18:00 | capture + light periodic tasks (config refresh, disagreement analysis) | moderate |
| 18:00–00:05 | near-close fast capture (15s CLOB), MM quoting from 19:30, settlement watch | **PROTECTED — nothing heavy, ever** |

Stage-A settlement safeguards: the daily taker edge-permission aggregation is
single-pass and tape-bounded. Scheduled maker-paper scoring selects the latest
14 active-day runs and fails closed before materialization when its selected
quote inputs exceed 512 MiB (`--maker-paper-latest-active-runs` and
`--maker-paper-max-input-bytes`). These are immediate containment limits, not
a substitute for the per-step isolation and physical-memory admission owned by
Roadmap Item 324.

### The training window (adopted 2026-07-12)

The capture-resource admission gate refuses heavy work while capture loops are
active, and a single host cannot both capture 24/7 and train. Until the model
earns a second machine, the learning loop runs inside a bounded nightly
maintenance window:

- **`WeatherTrainingWindow` (01:00 daily)**: preflight (skip unless commit
  < 70% and disk free > 60 GB) → disable the three capture supervisors and
  stop the loops → run `nightly_retrain` with a 3-hour hard cap → restore
  capture in a `finally` block. The window must confirm all three workers are
  inactive through the canonical capture-resource gate before starting the
  child, and the child runs with `capture_resource_mode=no_live_capture`.
  Window commit preflight owns the memory decision; a blocked/error/missing
  nightly status is surfaced as a nonzero window result after capture restore.
- **`WeatherTrainingWindowRestore` (04:15 daily)**: dead-man backstop that
  unconditionally re-enables supervisors and ensures all loops, in case the
  window process dies mid-flight.
- Script: `scripts\ops\training_window.ps1` (also supports `-RestoreOnly` and
  `-DryRun`). Log: `data\logs\training_window.log`.

Any day using the window has a deliberate capture gap and is **not a clean
day** for item-321 Phase 2 proofs. Clean-day streaks are collected on nights
the window skips, or after a second host removes this trade-off. On
warm-cache nights the retrain should finish well before the 03:00–05:00
predawn frontier; the 3-hour cap bounds the worst case to ~04:05.

## Rules

1. **Protected window 18:00–00:30**: no ad-hoc analysis jobs, corpus builds,
   replays, conversions, backfills, or bulk file operations. Near-close tape
   is the highest-value data this platform collects; the 15-second fast-mode
   contract has no slack for IO contention.
2. **Heavy ad-hoc work runs 01:00–08:30**, and checks first:
   `data\logs\memory_commit_guard_status.json` (commit_percent < 70) and
   ≥ 50 GB disk free.
3. **Memory budget for any single ad-hoc job: 8 GB private bytes.** The
   `WeatherMemoryCommitGuard` task (every 5 min) warns at 85% commit and
   kills the largest ad-hoc python offender above 8 GB at 92% commit. It
   never touches `-m weather.*` module processes. Agents running unbounded
   materializations must chunk or spill to disk instead.
4. **Orphaned ad-hoc python is killed on sight** (30-minute grace). Every
   guard run sweeps for `python -` / `python -c` processes whose parent is
   gone: a stdin or inline job's script and output have no owner once its
   parent dies. The incident's second process sat at only 1.3 GB — under
   every memory threshold — while reading 113 GB from the data disk with
   nobody left to consume the result. Orphaned bare-script python is logged
   but not killed, since detached-by-design launchers are legitimate here.
5. Scheduled `-m weather.*` heavy work stays governed by its own admission
   gate (capture-resource DEFER on this live host) — this policy does not
   loosen it.

## Incident 2026-07-12 (why this policy exists)

At 19:15, during the run-up to near-close and the 19:30 MM roll, an ad-hoc
`python -` analysis job began materializing a corpus unboundedly. By 19:26 it
held **36 GB of private commit** on a 15.7 GB host; system commit hit **99.4%
(63.3/63.7 GB)**, the pagefile thrashed the data disk to 100% utilization,
and both capture loops degraded: the snapshot loop stalled at 18:21 (~75
minutes of fleet gap), and the CLOB book loop crashed at 19:19 with a
pressure-induced `OSError: [Errno 22]` writing its diagnostics, then
crash-looped through its supervisor restart budget into backoff. Killing the
runaway restored commit to 47% instantly; the snapshot loop was revived with
`snapshot_tracker --restart` and the CLOB loop with a forced
`market_microstructure restart` after clearing wedged ensure probes.

Contributing factors worth fixing structurally:

- `clob_diagnostics.jsonl` (489 MB) and `clob_loop_console.log` (474 MB) grow
  without rotation; the crash was an append to the former. In-code size-based
  rotation is the durable fix.
- 15.7 GB RAM is undersized for capture + any concurrent analysis. A RAM
  upgrade (32-64 GB) is the single best hardware improvement; a second
  physical disk for `data\` (separating tape writes from OS/pagefile) is the
  second.
- Disk headroom is ~6-7 days at current burn. The parquet/archive conversion
  backlog (item-321 Phase 3) is the sanctioned drain; deletion of canonical
  tape is prohibited before off-machine copy proof.
