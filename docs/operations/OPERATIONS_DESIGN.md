# Operations Design

## Target Shape

The operating setup has three layers:

1. Windows Task Scheduler runs short-lived supervisors that keep three
   streak-critical capture loops healthy and, when explicitly armed, one
   auxiliary public execution-tape producer healthy.
2. A lightweight desktop launcher starts the Streamlit dashboard and opens the
   Operations view.
3. The Operations view and status CLIs provide health, code-version, log, and
   recovery controls.

The dashboard launcher does not own capture. Closing Streamlit must not stop
evidence collection, and opening Streamlit must not create a second copy of a
loop.

## Capture Topology

| Loop | Supervisor task | Ensure command | Primary responsibility |
| :--- | :--- | :--- | :--- |
| Weather/model snapshots | `WeatherSnapshotLoopSupervisor` | `python -m weather.collection.snapshot_tracker --ensure` | Multi-market weather, model, source-state, and market snapshot tapes at the slower scheduled cadence. |
| CLOB books | `WeatherClobBookLoopSupervisor` | `python -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15` | Independent fast Polymarket order-book and market-event capture. |
| Observation triggers | `WeatherObservationTriggerSupervisor` | `python -m weather.operations.observation_trigger ensure --market all --interval-seconds 60 --stale-after-seconds 180` | Low-cost observation polling and durable enqueueing when settlement-relevant source state changes. The snapshot loop performs recomputes under its existing resource bounds. |

Those three loops own streak grading and the capture-recovery contract. The
read-only International public execution tape is an auxiliary fourth producer:

| Producer | Supervisor task | Ensure command | Primary responsibility |
| :--- | :--- | :--- | :--- |
| Public executions | `WeatherExecutionTapeSupervisor` | `python -m weather.operations.execution_tape_supervisor ensure --market all --stale-after-seconds 180` | Retain received-time `last_trade_price` observations, connection gaps, and exact subscription seeds for counterfactual price paths. It is not an own-account fill or P&L source. |

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
- `scripts/ops/register_execution_tape_supervisor.ps1` (explicit auxiliary adoption)

All four registration scripts bind a current-user `S4U` / `Limited` principal.
This is part of the capture contract: re-registering a supervisor must not turn
an unattended task back into an interactive-logon dependency.

Read each script before registering it. Re-running a registration script
replaces its task with the supplied parameters.

## Startup After Reboot

1. Logon triggers all three core capture-supervisor tasks and the execution-tape
   supervisor when that auxiliary task has been registered and enabled.
2. Each supervisor issues its `ensure` command and restores at most one healthy
   worker.
3. Check the loop status commands from the repository root:

   ```powershell
   .\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
   .\venv\Scripts\python.exe -m weather.market.market_microstructure status
   .\venv\Scripts\python.exe -m weather.operations.observation_trigger status
   .\venv\Scripts\python.exe -m weather.operations.execution_tape_supervisor status
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

### Execution-Tape Producer (Supervised Path Prepared; Host Adoption Separate)

`weather.market.execution_tape_capture` remains the explicit, read-only
operator command for the public market websocket. The managed lifecycle lives
separately in `weather.operations.execution_tape_supervisor`; its registrar is
an explicit host-adoption action and repository integration alone does not arm
the task. The producer is auxiliary to the three-loop streak-critical topology.
It builds subscriptions only from the retained
`config/location_market_events.json` seed; it does not discover markets from a
live REST endpoint and has no order, credential, wallet, or signing path.

The managed worker records its PID, exact process provenance, loaded-source
identity, and heartbeat into `execution_tape_status.json` while its writer lock
binds the same process instance. The short-lived ensure command publishes
`execution_tape_supervisor_status.json`, applies restart backoff/circuit
breaking, refuses an unproven stop, and readopts changed code. While the
Windows venv executable launches a distinct base-interpreter child, startup
admits that child only when its direct parent, complete command, creation token,
status owner, and writer-lock owner all agree; lifecycle ownership then follows
the child rather than the transient launcher. While the
producer is armed or still active, `roll_verdict.ps1` and
`staleness_sweep.ps1` require its live import closure; an unarmed or cleanly
stopped optional producer cannot make unrelated merge verdicts undecidable.
`status.ps1` treats process/lock/identity loss and evidence-integrity loss as
actionable, but does not relabel it as one of the three streak workers.

Each active location market-day writes bounded 64 MiB append-only parts under
`data/snapshots/<event>/execution_tape/`: `trades`, repeated-identity annotations,
connection `gaps`, and subscription `seeds`. The current public market-channel
contract does not guarantee a transaction hash on `last_trade_price`, nor does
it document the hash plus execution economics as a unique fill identifier. The
writer therefore retains every observation and suppresses none. A repeated
identity is annotated on the legacy-named `dedupe` tape, and transaction-hash
reuse is counted, but both observations remain on the trade tape because they
may be distinct fills. All public-stream execution rows remain price-path
evidence but set
`identity_integrity=BLOCKED_UNIQUE_EXECUTION_COUNTS`, so trade-count, fill-count,
and intensity claims cannot consume them as unique executions. Only a separate
source with a documented event ID may support those claims. The documented
`size`, `fee_rate_bps`, `timestamp`, and transaction hash fields are optional;
their absence is retained as `null` and counted as partial economics rather than
invented as zero or rejected. A row with a valid market, token, side, and price
can still support a receipt-ordered price path, but not missing size, fee, or
exchange-time claims. Treat rows as received-time state observations: resample
by asset and time or take state transitions. Never row-weight a price
distribution or infer fill probability, volume, or intensity from public row
frequency because redelivery cannot be separated from identical executions.
Atomic per-market-day `status.json` and global
`data/snapshots/execution_tape_status.json` state the physical tapes last
counted, current connection state, reconnect count, and seconds dark. An empty
trade tape is classified as connected-and-quiet only when connection coverage
supports that conclusion. Coverage begins only after inbound routed market
events cumulatively prove every requested asset ID in the market-day; a frame
for one token, socket connection, subscription send, or `PONG` heartbeat alone
is not full market-day coverage. Each asset is hash-bound to its exact condition
in the seed; a token paired with another condition in the same event is rejected
as evidence loss rather than accepted by coarse market-day routing. An empty tape with a gap is
explicitly disconnected evidence, not a quiet market. After route proof, the
connection also has an inbound-silence deadline: a server `PONG` or market frame
must continue arriving, so local heartbeat sends cannot sustain green status.
Any invalid execution message, unrouted execution, or ambiguous token/condition
route changes global status to `DEGRADED_EVIDENCE_LOSS`; a healthy socket cannot
override evidence loss.
The offline
`python -m weather.market.execution_tape_capture status` command prints that
last-counted global status without opening a connection.

Managed files:

- `data/snapshots/execution_tape_status.json`
- `data/snapshots/execution_tape_supervisor_status.json`
- `data/snapshots/execution_tape_supervisor_diagnostics.jsonl`
- `data/snapshots/execution_tape_console.log`

### Observation-Trigger Loop

- `data/snapshots/observation_trigger_status.json`
- `data/snapshots/observation_trigger_supervisor_status.json`
- `data/snapshots/observation_trigger_diagnostics.jsonl`
- `data/snapshots/observation_trigger_console.log`
- `data/snapshots/observation_triggers.jsonl`
- `data/snapshots/observation_source_cache/<market>.json`
- `data/snapshots/triggered_snapshot_queue/{pending,inflight,completed,acknowledged}/`
- forced snapshot rows tagged with trigger context

The watcher writes one immutable work file per material market trigger and does
not execute snapshot/model work in its polling iteration. The weather snapshot
loop checks the spool every five seconds during its normal idle sleep, claims
at most one queued item per market on its next pass, and substitutes it into
the same bounded isolated batch used for scheduled captures. A pass already in
progress retains its existing fleet-deadline bound. Retryable resource,
timeout, or fleet-budget failures return to
`pending`; terminal receipts remain in `completed` until the watcher publishes
the existing observation-trigger event and replaces the receipt with a compact
acknowledgement. A snapshot-loop restart recovers orphaned `inflight` files.

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
but are not a fourth capture loop. The maker supervisor may launch or recover a
worker only inside its configured local evidence window. A healthy worker is
not killed at the end boundary, but a dead, idle, or stale-code worker remains
stopped after that boundary so non-countable recovery cannot consume restart
budget or create another run folder. The taker supervisor has no end boundary.

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

The wrapper owns the entire delegated process tree with a Windows Job Object
configured for `KILL_ON_JOB_CLOSE`. It creates the Python child suspended,
assigns it to that Job, and resumes it only after assignment succeeds. Thus no
child instruction or descendant can run outside containment, and terminating
the scheduled wrapper closes the only Job handle and tears down the tree.
Failure to create, assign, or resume fails before daily-refresh work can begin.

The same containment primitive backs `scripts/ops/bounded_worktree_test_suite.ps1`.
That runner admits tests only from 00:30–09:00, against a registered clean
worktree whose branch and `HEAD` equal an explicit commit, while all three
capture workers are healthy and Windows commit is below the configured start
ceiling. It rechecks capture and commit between size-bounded pytest chunks,
writes a JUnit artifact per chunk, and owns each child in a kill-on-close Job.
It also requires checked-in optional live-SDK contract tests to execute rather
than silently skip; the exact pinned SDK must therefore be installed before a
live-client branch can earn a production-host suite verdict.
It never merges, pushes, checks out, registers a task, or writes production
data; a full PASS is evidence for a separate reviewed merge, not the merge.

Daily-refresh steps declare an execution lane and, separately, whether their
current-run receipt gates promotion beside the canonical step registry. This
keeps shared pre-promotion producers available to learning without allowing
promotion to read an older PASS artifact after their current-run failure. Independent evidence
producers and the settled-day barrier still run after a blocker; only the two
target-day promotion consumers (live settlement scoring and the promotion
action) are suppressed. Missing current-run gate receipts and target-mismatched
barrier receipts fail promotion closed. A blocked settled-day barrier therefore
still yields a completed, critical Stage-A manifest, and Stage B runs in
gap-aware learning mode while carrying the exact promotion blocker forward.
Every learning result declares whether target coverage comes from its own
corpus, named dependencies, or is not applicable, and records the requested
target, observed corpus dates, inclusion, staleness, and gap reason without
inheriting a barrier PASS as proof. `daily_learning.json` persists the same
coverage. Stage-B completion is bound to the exact Stage-A run, so a repaired
Stage A can rerun promotion for the same target date. The canonical promotion
adapter also reads the prior `daily_learning` and `data_layer_audit` artifacts
because those producers run later in the same chain, and `daily_learning`
itself consumes promotion output. This split does not redefine that
pre-existing lag cycle as a same-run receipt; those artifacts remain subject
to their canonical adapter gates.
Heavy-work capture admission and captured-input parity may defer the affected
heavy step, but lightweight learning continues. Physical-resource deferrals
and isolated-child orchestration failures remain global hard stops.

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
  It also holds the shared OS-backed heavy-workload lease before it disables
  capture, so a bounded suite, guarded merge, tiering job, or daily chain can
  never overlap the window.
- `WeatherTrainingWindowRestore` is a later dead-man task that unconditionally
  re-enables supervisors and issues all three `ensure` commands.

The detailed resource thresholds, protected hours, and evidence consequences
are owned by the [Host Load Policy](HOST_LOAD_POLICY.md). A day with the
deliberate capture gap is not a clean continuous-capture day.

Do not enable both the direct nightly task and the single-host training window
for the same workload. The registration scripts do not remove the alternative
task automatically; inspect and reconcile Task Scheduler explicitly when
changing topology.

The delegated daily-refresh wrapper uses the same lease and owns its Python
tree through a kill-on-close Job. It refuses to start outside 00:30–11:55 and
closes the Job at 11:55, so a delayed or long settlement run cannot enter the
12:00–18:00 graded capture window. This deadline is independent of per-step
memory admission and Task Scheduler's broader execution limit.

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
