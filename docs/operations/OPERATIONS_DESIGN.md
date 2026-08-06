# Operations Design

## Target Shape

The operating setup has three layers:

1. Windows Task Scheduler runs short-lived supervisors that keep three
   independent capture loops healthy.
2. A lightweight desktop launcher starts the Streamlit dashboard and opens the
   Operations view.
3. The Operations view and status CLIs provide health, code-version, log, and
   recovery controls.

The dashboard launcher does not own capture. Closing Streamlit must not stop
evidence collection, and opening Streamlit must not create a second copy of a
loop.

## Three-Loop Capture Topology

| Loop | Supervisor task | Ensure command | Primary responsibility |
| :--- | :--- | :--- | :--- |
| Weather/model snapshots | `WeatherSnapshotLoopSupervisor` | `python -m weather.collection.snapshot_tracker --ensure` | Multi-market weather, model, source-state, and market snapshot tapes at the slower scheduled cadence. |
| CLOB books | `WeatherClobBookLoopSupervisor` | `python -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15` | Independent fast Polymarket order-book and market-event capture. |
| Observation triggers | `WeatherObservationTriggerSupervisor` | `python -m weather.operations.observation_trigger ensure --market all --interval-seconds 60 --stale-after-seconds 180` | Low-cost observation polling and forced recomputes when settlement-relevant source state changes. |

Each supervisor invokes an idempotent `ensure` command at logon and on its
repeating schedule. The command repairs or starts one detached worker; it is
not itself the long-running capture process. A healthy/no-op or successful
launch exits `0`. Lock contention, restart backoff, an open restart circuit, or
a failed launch exits nonzero so Task Scheduler does not report success while
capture is down. Each ensure writes its latest decision and recovery-guard
state to a separate atomic `*_supervisor_status.json` sidecar; the long-running
worker remains the only writer of its loop status. Registration source, task
names, cadences, and parameters live in:

- `scripts/ops/register_snapshot_supervisor.ps1`
- `scripts/ops/register_clob_supervisor.ps1`
- `scripts/ops/register_observation_trigger_supervisor.ps1`

Read each script before registering it. Re-running a registration script
replaces its task with the supplied parameters.

## Startup After Reboot

1. Logon triggers all three capture-supervisor tasks.
2. Each supervisor issues its `ensure` command and restores at most one healthy
   worker.
3. Check the loop status commands from the repository root:

   ```powershell
   .\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
   .\venv\Scripts\python.exe -m weather.market.market_microstructure status
   .\venv\Scripts\python.exe -m weather.operations.observation_trigger status
   ```

4. Open the dashboard with `scripts/launch/start_weather_dashboard.cmd` or
   `scripts/launch/start_weather_dashboard.ps1`.
5. Confirm the Operations view at `http://localhost:8501/?market=ops` reports
   current runtime identity and fresh capture.

## Loop Outputs

### Weather Snapshot Loop

- `data/snapshots/loop_status.json`
- `data/snapshots/loop_supervisor_status.json`
- `data/snapshots/diagnostics.jsonl`
- `data/snapshots/loop_console.log`
- per-event snapshot, replay-input, source, feature, and component tapes

`consecutive_errors` and `last_error` describe the most recently completed
fleet iteration, not lifetime history. Progress heartbeats retain the prior
completed iteration's state until every registered market has a result; the
next fully completed error-free iteration clears both fields and records the
`last_completed_iteration` / `last_clean_iteration` markers. Cadence liveness
such as 12/12 recently captured markets does not override a current iteration
error for Stage-A admission.

### CLOB Book Loop

- `data/snapshots/clob_loop_status.json`
- `data/snapshots/clob_loop_supervisor_status.json`
- `data/snapshots/clob_diagnostics.jsonl`
- `data/snapshots/clob_loop_console.log`
- per-event token, order-book, price-history, and WebSocket tapes

The active CLOB diagnostics and console sidecars rotate at 64 MiB to UTC-
timestamped siblings in the same directory, and rotated files are never
deleted by the writer. Diagnostics rotation occurs before append. Because
Windows holds the detached child's console handle for the process lifetime,
console rotation occurs at the next managed loop startup before opening the
new handle.

### Maker Execution-Evidence Producer

Maker-day scoring has a stricter execution-evidence requirement than the raw
book loop. On this branch, `WeatherMakerExecutionCapture` is registered only
through `scripts/ops/register_mm_execution_capture.ps1`. The accepted `-09-17a`
follow-on adds the operator-facing `scripts/ops/register_maker_tape.ps1`; after
that branch is integrated, it must pass the same deployed-module `--help`
contract before registration. The task runs
`python -m weather.market.mm_execution_capture --market all --retention-mode
executions-only --lock-scope execution-tape --host-policy-mode
pause-training-window` as a separate BelowNormal process. It subscribes the
whole active fleet on one WebSocket but retains only individual
`last_trade_price` members. Each event's `mm_execution_tape.jsonl`,
`mm_execution_tape.csv`, and `mm_execution_tape_sessions.jsonl` are serialized
through `root/mm_execution_tape`, never the CLOB writer's `clob_raw_tape`
anchor. The receipt binds the exact asset set, local connection-message
sequence interval, execution count, and raw/canonical prefix bytes and hashes.
A receipt claims complete coverage only after every asset subscribed for every
event has appeared in public market data; each event row binds its own observed
asset set and market-data message count, so activity in one event cannot prove
an exact-zero interval for another.
`data/snapshots/market_execution_capture_status.json` records the latest
session, planned pause, or connection failure.

This process is separate because the latency-critical CLOB loop intentionally
remains raw-book-only, while the older enrichment loop samples each market for
a short bounded interval and cannot prove continuous quote-lifetime coverage.
The maker-day checklist fails closed when bound execution evidence or a
complete session covering a decision or resting quote is absent. A valid
no-quote day still needs a complete bound receipt. Missing raw/canonical files
prove exact zero only when that receipt declares zero executions and binds both
absent prefixes to zero bytes and SHA-256(empty); a positive receipt requires
matching raw and canonical tapes. The paper scorer also binds the checklist to one settled target
date even though its longitudinal diagnostics can read a bounded multi-run
corpus. Before run discovery, it reads
`docs/operations/reserved-confirmation-window.md`: a declared reserved target,
an unspecified target under a declared reservation, or an unparseable
declaration blocks scoring before target artifacts are read. Editing or testing
the registration script does not register or start the task.

### Observation-Trigger Loop

- `data/snapshots/observation_trigger_status.json`
- `data/snapshots/observation_trigger_supervisor_status.json`
- `data/snapshots/observation_trigger_diagnostics.jsonl`
- `data/snapshots/observation_trigger_console.log`
- `data/snapshots/observation_triggers.jsonl`
- `data/snapshots/observation_source_cache/<market>.json`
- forced snapshot rows tagged with trigger context

The watcher uses one observation-only last-good cache per market. It does not
read or migrate the full model cache under `data/wunderground/`; a missing
dedicated cache remains fail closed until a live observation bootstraps it.
Only `wu_history`, `wu_current`, `metar`, and `eccc_swob` entries are accepted,
and each file has an 8 MiB read/write ceiling. An oversized or out-of-scope
cache is quarantined before JSON materialization. Cache scope, readiness, and
the live-bootstrap transition are recorded with each market's latest
observation state. These files are bounded operator caches, not canonical
evidence.

These files are runtime state under ignored `data/`, but many of the tapes are
canonical evidence. Follow the
[Data Storage Class Contract](data-storage-class-contract.md) and
[Data Retention Policy](data-retention-policy.md); do not delete evidence as a
loop-recovery shortcut.

## Runtime Identity And Deployment

Loop status records include runtime identity such as Git branch and commit,
dirty/source fingerprints, and Python version. A healthy heartbeat on old code
is still a deployment problem.

After changing code:

1. Run focused tests for the changed subsystem and the baseline local checks.
2. Restart every loop that imports the changed code. Shared model, source,
   path, schema, or runtime changes usually require all three loops to restart.
3. Confirm each status command reports a live worker on current code.
4. Confirm heartbeats and useful writes resume; inspect the corresponding
   diagnostics and console log if they do not.

To stop a loop deliberately, stop the worker and disable its scheduled
supervisor so the next `ensure` tick does not revive it. Re-enable supervision
and issue `ensure` to restore it. Use the loop's supported CLI or Operations
control rather than killing an arbitrary Python process.

## Dashboard Role

The Operations view is the human cockpit for current checkout identity, loop
health, heartbeats, useful-write freshness, errors, logs, and supported control
actions. Status CLIs and their JSON files remain the fail-closed diagnostic
surface when Streamlit is unavailable.

Bot daily-roll workers and reporting jobs have their own launchers,
supervisors, status artifacts, and evidence gates. They consume capture output
but are not a fourth capture loop.

## Daily Refresh Delegated-Child Tasks

`scripts/ops/register_daily_refresh.ps1` registers both daily stages as
scheduled PowerShell wrapper actions:

- `WeatherDailySettlementPromotionRefresh` starts Stage A settlement at 09:30
  local with a four-hour task limit and names the Stage B task it may trigger.
- `WeatherEveningEvidenceRefresh` has guarded fallback triggers at 14:00 and
  17:00 local with an eight-hour task limit.

Both actions run `scripts/ops/daily_refresh.ps1`. Registration and runtime
independently reconstruct the exact wrapper tokens through
`scripts/ops/daily_refresh_contract.ps1`, using the shared argument serializer
and base64 scheduler contract from `training_window_contract.ps1`. The Python
`weather.operations.daily_refresh` child passes
`scheduler-invocation-topology=delegated_child`, the exact registered wrapper
action contract, its own venv executable and arguments, repository working
directory, and stage-specific SLA. Countability still requires the running
wrapper PID/instance, task state, action, child lineage, and run-time
correlation to match; child-supplied flags alone are not evidence.

Before the settled-day analysis barrier, the read-only
`observed_floor_safety_monitor` joins captured `observed_floor_bucket` values
from `snapshot_explanations.jsonl` to finalized settlement labels. Missing
snapshot explanation coverage or unattributed floor provenance is `BLOCK`; any
floor above settlement is `ALERT`. The monitor records the exact market, target
date, snapshot, floor, settlement, rescue source, and overshoot in buckets. It
never reconstructs or replays a model.

**Temporary posture, 2026-07-31:** until the Toronto release-admissible capture
lock is secured, `ALERT` and `BLOCK` are alert-only by default. They remain
prominent in status, rollup, and the daily report, but do not block the
settled-day barrier: losing a paper-analysis day during the four-day pre-lock
window is the larger operational risk. This does not make the monitor optional
or weaken detection. After the lock, explicitly pass
`--fail-on-observed-floor-safety` to `daily_refresh` to restore fail-closed
barrier enforcement; the standalone monitor uses `--fail-closed`.

The default `Full` registration parameter set keeps captured-input parity,
served-artifact, and served-route inputs mandatory. Before reviewed release #1
parity inputs exist, the explicit transitional command is:

```powershell
& .\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly
```

This replaces both tasks with wrapper, provenance, and release arguments but
omits `--fail-on-production-readiness-block` and all production-evidence
bindings. It proves scheduler lineage only; it does not satisfy or weaken the
FULL production-evidence gate. Re-registration is a stateful adoption action
and is not performed by repository tests or code changes.

## Retraining Topologies: Choose One

Nightly retraining is heavy and candidate-only. It may build an immutable,
inactive release after validation; it must not activate
`artifacts/releases/current_release.json`. Promotion remains a separate
reviewed release-lifecycle action.

There are two alternative scheduling patterns:

### Direct Nightly Task

`scripts/ops/register_nightly_retrain.ps1` registers
`WeatherNightlyRetrainValidatePromote`, which runs `nightly_retrain` directly
at its configured time without stopping capture. Use this pattern only on a
host where the capture-resource gate permits the workload, such as an offline
or separate training host. The registration script requires explicit
production-evidence arguments; its `param(...)` block is the source of truth.
Countable direct runs bind the current OS PID, image, complete argument vector,
working directory, creation time, optional exact venv redirector, and current
Task Scheduler engine PID/instance to the registered action and fresh task run.

### Single-Host Training Window

`scripts/ops/register_training_window.ps1` registers two tasks for a Windows
host that otherwise captures continuously:

- `WeatherTrainingWindow` performs a resource preflight, disables all three
  capture supervisors, stops all three workers, runs bounded nightly retraining,
  and restores capture in a `finally` block. Its nightly process is a delegated
  child, not a direct scheduled action: the child must attest the exact running
  PowerShell task action plus its own Python executable, arguments, working
  directory, and task-run correlation. OS-observed process lineage must reach
  the registered PowerShell engine PID, image, and complete action command line,
  with wrapper/child creation times correlated to the task run. Only the exact
  expected Windows venv redirector may appear between producer and wrapper;
  the observed chain is bounded to two ancestors and fails closed if over-deep.
- `WeatherTrainingWindowRestore` is a later dead-man task that unconditionally
  re-enables supervisors and issues all three `ensure` commands.

The detailed resource thresholds, protected hours, and evidence consequences
are owned by the [Host Load Policy](HOST_LOAD_POLICY.md). A day with the
deliberate capture gap is not a clean continuous-capture day.

Do not enable both the direct nightly task and the single-host training window
for the same workload. The registration scripts do not remove the alternative
task automatically; inspect and reconcile Task Scheduler explicitly when
changing topology.

`scripts/ops/training_window_contract.ps1` is the single action-token owner for
both training-window registration and delegated-child attestation. Changing
the task name, executable, repository path, or wrapper action requires a
deliberate re-registration; stale definitions fail closed rather than being
treated as scheduled evidence.

## Why Capture Is Not Packaged Into The Dashboard

A shortcut or executable is useful for opening the dashboard, but it is not a
durable supervisor. It can be closed, crash, or never start after reboot. If a
packaged desktop launcher is added later, it should continue to launch only the
human-facing dashboard. Task Scheduler and the loop `ensure` contracts remain
the owners of evidence capture.

## Update this file when

Update when capture-loop ownership, supervisor tasks/commands, status or log
contracts, dashboard controls, deployment/restart behavior, or retraining
topology changes.
