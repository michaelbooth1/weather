# Host Load Policy — Dedicated Capture Host

Status: adopted 2026-07-12 after the commit-exhaustion incident (below).
Owner: operations. This host is dedicated to the weather platform; the policy
spreads load across the 24-hour day so capture — the one workload that cannot
be rescheduled — is never starved.

> **For the current numbers, read [OPERATING_REFERENCE.md](OPERATING_REFERENCE.md).** It is
> generated — governing constants are imported at render time and the timetable is read from the
> live scheduler, so it cannot drift. **This file owns the *policy*; that file owns the *facts*.**
> On 2026-08-08 the capacity figures below were three times wrong and the 24-hour map listed a
> window as "steady-state capture only" that by then held nine scheduled jobs. A stale operations
> document is worse than a missing one, because it gets believed.

## Host capacity (measured 2026-07-12 — A DATED SAMPLE, NOT CURRENT STATE)

**Do not plan against these.** `scripts\ops\status.ps1` reports live RAM, disk, and the daily
growth trend; use it. Retained because the *ratios* explain why the policy exists.

| Resource | Value at sample | Note |
| --- | --- | --- |
| Physical RAM | 15.7 GB | smallest resource on the box, and still true |
| Pagefile | 48 GB allocated | commit limit ~63.7 GB |
| Disk free | ~385 GB | **stale — was 124.6 GB on 2026-08-08.** Read it live |
| data/ growth (24h sample) | snapshots 23.4 GB, taker_runs 2.7, reanalysis 2.5, backtest 1.6, wunderground 1.4 | snapshots dominate; the taker is since PAUSED |

## The 24-hour map (America/Toronto)

**Load classes are policy and live here. What actually runs in each window is generated** — see
the daily timetable in [OPERATING_REFERENCE.md](OPERATING_REFERENCE.md), which reads the live
scheduler rather than describing it from memory.

| Window | Load class |
| --- | --- |
| 00:05–00:30 | taker/MM daily roll-over — brief spike |
| 00:30–09:00 | **the least-contended block, but no longer empty.** Heavy work goes here, and the quiet merge window (01:00–04:00) sits inside it |
| 09:30–11:55 | Stage A settlement chain — heavy, scheduled, with an absolute teardown deadline |
| 12:00–18:00 | **PROTECTED graded capture window — no heavy work** |
| 18:00–00:05 | **PROTECTED — nothing heavy, ever.** Near-close fast capture (15s CLOB), MM quoting from 19:30, settlement watch |

Stage-A settlement safeguards: the daily taker edge-permission aggregation is
single-pass and tape-bounded. Scheduled maker-paper scoring selects the latest
14 active-day runs and fails closed before materialization when its selected
quote inputs exceed 512 MiB (`--maker-paper-latest-active-runs` and
`--maker-paper-max-input-bytes`). These independent input limits remain
fail-closed alongside the per-step isolation and physical-memory admission
owned by Roadmap Item 324.

For each run, a complete validated `mm_scoring_projection_v0.2` base/variant
pair is measured and passed to the streaming scorer; any missing, stale,
malformed, or incompatible member makes that run use both canonical tapes.
The receipt records projected versus canonical bytes and exact input bindings.
The scorer revalidates admitted size/mtime bindings (and projection hashes)
before ingestion and checks that inputs stay stable through streaming. Daily
roll projection finalization starts only after the superseded target-matched
writer's exit is confirmed; otherwise canonical fallback remains in force.
Projection compaction does not change the 512 MiB input cap, the 4 GiB
isolated-child private cap, or the 3 GiB working-set cap.

Snapshot fleet capture admits at most two isolated children by default, with a
1,792 MiB process-tree working-set and private-commit cap per child. The 3,584
MiB aggregate ceiling is below the prior three-by-1,536 MiB envelope while
leaving allocation headroom above the 1,598,382,080-byte peak measured in a
successful production child on 2026-07-16. Canonical source hashing and
market-local raw-evidence persistence must stream JSON into the digest/file
sink and publish a complete fsynced CAS blob atomically; the higher per-child
cap is not authority to restore a whole-document `json.dumps` copy. The
long-lived snapshot parent must likewise stream fleet-health tape scans and
retain only per-snapshot summaries or the latest snapshot rows. An older
already-running parent can retain its pre-fix allocator high-water mark until
a supported, separately authorized code-adoption restart; that retained value
is not authority to stop or replace the worker ad hoc.

Worker launch is additionally admitted against current available physical
memory. Every admitted slot reserves its complete 1,792 MiB ceiling and must
leave 1,536 MiB available for the parent and other capture loops. The loop
therefore runs one worker when only one full slot is safe, uses two only above
the complete 5,120 MiB requirement, and records an explicit retryable host-
memory admission failure when even one slot cannot be proven safe. Missing
physical-memory measurement fails closed.

The WU settlement restore fetches a target day but rebuilds each market's full
retained normalized history, so it is not a light one-day operation. It runs in
an isolated child with a 60-minute timeout, 4,096 MiB private-memory ceiling,
and 2,560 MiB working-set ceiling; admission requires 4,096 MiB physically
available including the 1,536 MiB capture reserve. Raw payload, daily-summary,
and manifest publication is atomic, and an existing raw payload must parse as
valid JSON before skip-existing logic may reuse it.

The target-day taker finalization watchdog folds one run at a time through a
rebuildable SQLite row store with a 2 MiB page cache. Order and counterfactual
CSV inputs stream row by row; the seven-strategy bakeoff, settlement outputs,
and benchmark arrays publish atomically from disk-backed views before that
run's scratch state is released. Compact source-bound projections let
freshness, next-run policy, profitability, and champion/challenger readers
avoid decoding large canonical JSON artifacts. The watchdog still runs in an
isolated child with a 60-minute timeout, 5,120 MiB private-memory ceiling, and
2,048 MiB working-set ceiling; admission still requires 3,584 MiB physically
available including the capture reserve. Do not raise these ceilings for a
historical corpus.

Stage-A high-risk steps are now isolated one child at a time. The orchestrator
persists an interruption-safe resume receipt before resuming child code and
enforces the repository-declared private-memory, working-set, and timeout
budget. Every child requires commit below 70%, fresh capture-loop evidence, and
available physical RAM equal to its admission working-set expectation plus a
1.5 GiB capture reserve. An unspecified expectation defaults byte-for-byte to
the working-set ceiling and every expectation must remain at or below that
ceiling; the same physical/capture checks run again after exit. The containment
ceilings remain fail closed. Parent receipts include elapsed time, peak private
and working-set memory, lifetime process-tree read/write bytes, and bounded result
cardinality fields. Child result envelopes additionally record the child's own
peak working set and peak commit when the platform query is available. Do not
loosen the ceilings to force a scheduled run through; Item 324 remains partial
until a representative scheduled soak supplies measured per-step peaks, I/O,
and cardinality evidence.

On Windows, the guard associates a dedicated Job completion port before the
suspended root is assigned, retains one exact Job-verified handle per
`(process ID, creation time)` instance, and terminally queries every retained
handle after the Job becomes inactive. The reported process-tree working-set
peak is the conservative sum of those complete-lifetime per-process peaks;
the private/commit peak remains the Job Object's exact `PeakJobMemoryUsed`.
Missing process notifications are not trusted: the retained instance count
must reconcile exactly to the Job lifetime `TotalProcesses`, all terminal
queries and handle closes must succeed, and any mismatch blocks the receipt.

These ceilings authorize containment, not completion claims. A child that
reaches a ceiling must terminate inside its container and leave an exact safe
resume point; the first isolated WU and watchdog receipts must be reviewed at
the 80% thresholds before any adjustment. The 2026-07-14 scheduled run is
explicitly non-countable: both steps still ran in-process, the watchdog reached
at least 5,792,079,872 private bytes and 4,118,310,912 working-set bytes, and
available physical RAM fell to 617 MiB before an emergency manual task stop.

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
  The nightly process is scheduler topology `delegated_child`: it attests the
  exact running PowerShell wrapper action, its own Python command, and the
  OS-observed bounded parent process lineage. A stale, disabled, unrelated,
  mismatched, or manually invoked topology remains non-countable.
  Before disabling capture it must acquire the same OS-held heavy-workload
  lease used by the daily chain, guarded merges, bounded suites/probes, and
  tiering. A busy lease skips the window without touching capture.
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
2. **Heavy ad-hoc work runs 00:30–09:00**, holds the shared lease from
   `scripts/ops/workload_admission.ps1`, and checks first:
   `data\logs\memory_commit_guard_status.json` (commit_percent < 70) and
   ≥ 50 GB disk free. The lease itself rejects acquisition outside that
   window. Only the settlement Stage-A wrapper can request the explicit
   09:30–11:55 exception. Bounded test suites additionally kill their complete
   Job-owned child tree at 09:00 rather than merely checking the start time.
3. **Memory budget for any single ad-hoc job: 8 GB private bytes.** The
   `WeatherMemoryCommitGuard` task (every 5 min) warns when available physical
   RAM is below 1.5 GiB and records the top working-set processes. It also
   warns at 85% commit and kills the largest ad-hoc python offender above 8 GB
   at 92% commit. Physical-RAM pressure is warning-only: every kill decision
   remains commit-based, and the guard never touches `-m weather.*` module
   processes. Agents running unbounded materializations must chunk or spill to
   disk instead.
4. **Orphaned ad-hoc python is killed on sight** (30-minute grace). Every
   guard run sweeps for `python -` / `python -c` processes whose parent is
   gone: a stdin or inline job's script and output have no owner once its
   parent dies. The incident's second process sat at only 1.3 GB — under
   every memory threshold — while reading 113 GB from the data disk with
   nobody left to consume the result. Orphaned bare-script python is logged
   but not killed, since detached-by-design launchers are legitimate here.
5. Scheduled `-m weather.*` heavy work stays governed by its own admission
   gate (capture-resource DEFER on this live host) **and** the shared workload
   lease—neither mechanism loosens the other. The daily-refresh wrapper tears
   down its complete Job-owned child tree at 11:55 rather than crossing into
   the graded window.

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

- At incident time, `clob_diagnostics.jsonl` (489 MB) and
  `clob_loop_console.log` (474 MB) grew without rotation; the crash was an
  append to the former. The CLOB, snapshot, and observation-trigger managed-loop
  sidecars now share one 64 MiB policy: append-opened JSONL rotates before the
  next append, and console logs rotate at managed-loop startup before Windows
  opens the new child handle. Rotation renames to timestamped siblings and never
  deletes prior archives; transient Windows access denials receive a short,
  bounded exponential retry and persistent denial still fails closed. Supervisor
  restart-budget reads span retained
  diagnostics siblings, so diagnostics rotation cannot clear breaker state. On
  first adoption, archives whose physical last write predates the breaker
  window are excluded before content is read; retained cold history must not
  turn a recovery guard into a multi-gigabyte capture stall.
  The dormant CLOB-enrichment diagnostics writer uses the same append-time bound;
  this does not re-arm or otherwise adopt that dormant loop.
- 15.7 GB RAM is undersized for capture + any concurrent analysis. A RAM
  upgrade (32-64 GB) is the single best hardware improvement; a second
  physical disk for `data\` (separating tape writes from OS/pagefile) is the
  second.
- Disk headroom is ~6-7 days at current burn. The parquet/archive conversion
  backlog (item-321 Phase 3) is the sanctioned drain; deletion of canonical
  tape is prohibited before off-machine copy proof.
