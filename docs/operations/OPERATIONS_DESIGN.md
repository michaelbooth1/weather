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

### Observation-Trigger Loop

- `data/snapshots/observation_trigger_status.json`
- `data/snapshots/observation_trigger_supervisor_status.json`
- `data/snapshots/observation_trigger_diagnostics.jsonl`
- `data/snapshots/observation_trigger_console.log`
- `data/snapshots/observation_triggers.jsonl`
- forced snapshot rows tagged with trigger context

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
