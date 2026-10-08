# Operations Design

- **Owns:** the scheduled-task and loop topology of the production capture host: which task runs which command,
  what each loop writes, how the daily chain is staged and contained, and the two retraining topologies.
- **Read when:** changing or diagnosing a supervisor, a scheduled task, a loop status file, the daily refresh
  stages, or deciding which loops a code change must restart.
- **Do not use for:** what is armed, disabled or broken today ([STATE_OF_PLAY](STATE_OF_PLAY.md)); heavy-work
  windows and thresholds ([HOST_LOAD_POLICY](HOST_LOAD_POLICY.md), [OPERATING_REFERENCE](OPERATING_REFERENCE.md));
  the integration procedure ([INTEGRATION_ATTEMPT_RUNBOOK](INTEGRATION_ATTEMPT_RUNBOOK.md)); retention and disk
  ([data retention policy](data-retention-policy.md)).
- **Verify with:** `Get-ScheduledTask -TaskName 'Weather*'` (state and action path, see "What actually executes"),
  the `param()` block of the matching `scripts/ops/register_*.ps1`, and `scripts\ops\status.ps1` output in
  `data/alerts/MORNING_BRIEFING.md`. This file describes design; it never proves a task is enabled.

Status of machinery described here (owner decisions; [STATE_OF_PLAY](STATE_OF_PLAY.md) is
the current authority): nightly training is disabled, Stage B evidence refresh is registered disabled by default,
the taker and paper maker are retired (runtime deleted 2026-09-29), the workstation data mirror is paused
([mirror-paused-2026-08-12](mirror-paused-2026-08-12.md)), and streak contiguity is not an objective
([ESTABLISHED_FINDINGS](ESTABLISHED_FINDINGS.md) section 0d). "Streak-critical" below names the three loops whose
gaps are graded; it does not rank the streak above settlement evidence.

## Target Shape

The legacy paper maker (`mm_policy`, `market_making_run*`, `mm_paper*`) and the
paper taker (`taker_bot*`) are retired, and their scoring, daily-refresh steps,
daily rolls and registrars were deleted on 2026-09-29 (110o part 3, owner decision 3
of the 2026-09-26 repo-health audit). By owner decision the paper-run tool
(`market_making_run` and the modules it imports) is retained only to produce the
International live-pilot Stage 0/1 paper run until the informed maker's own live
procedure replaces it; it has no scheduled task. Their run folders under `data/` are retained
evidence; `trading_evidence` reads them through the read-only
`weather.reporting.market.retired_trading_evidence` module, and git history holds
the deleted code. The Stage 2 hold build at `88aa7e43a` is frozen as fixtures only,
not a runtime migration source. The replacement foundation is
[maker core](maker-core-contracts.md). Production operations owns unregistering
the disabled paper tasks with backups in a separate operation; this retirement
changes no scheduled task or capture worker.

`config/scheduled_tasks.json` owns reviewed task lifecycle intent and registrar
provenance. Its generated table is in [OPERATING_REFERENCE](OPERATING_REFERENCE.md);
it is not a Scheduler snapshot. Missing host-local XML stays explicitly unverified.
Nightly health reports the maker and taker bots as fixed `RETIRED` rows without
reading old run folders or suggesting a restart, and fleet observability supervises
only the three capture loops. The four retired bot tasks stay in the registry as
`retired`/expected-Disabled with no registrar (their registrars were deleted), so
`status.ps1` keeps classifying them. The retired enrichment and disagreement
registrars refuse the register path without `-AcknowledgeRetired`; the enrichment
unregister path remains available. Acknowledgement alone does not grant
live-trading authority.

Stage A no longer has taker or maker-paper-score steps, and the
`--paper-maker-paused` and `--skip-taker-*` flags were removed with them; the
contract script and the Python CLI must be adopted together. Missing or failed
settlement evidence remains blocking at the settled-day barrier.

The operating setup has three layers:

1. Windows Task Scheduler runs short-lived supervisors that keep three
   streak-critical capture loops healthy and, when explicitly armed, one
   auxiliary public execution-tape producer healthy.
2. A lightweight desktop launcher starts the three-page Streamlit dashboard and
   opens the read-only Owner Cockpit.
3. The Control Room and status CLIs expose health and code-version evidence;
   supported CLIs and runbooks remain the only recovery/control surfaces.

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

The separately registered `WeatherMakerEvidenceCapture` runs
`python -m weather.market.maker_evidence_capture` directly, with a kernel writer
lock and Scheduler IgnoreNew, rather than an `ensure` supervisor. Its
[owning contract](passive-maker-evidence-capture.md) defines minute T+0/T+1/T+2
books and reward records, capped extra-condition window updates, continuous public trades, disk
brakes and `data/maker_evidence/status.json`. It does not enter streak grading
or the existing capture recovery contract. The registrar is
`scripts/ops/register_maker_evidence_capture.ps1`; registration and readoption
remain explicit production actions.

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

## What actually executes

A scheduled task runs the files at the path frozen into its action when it was registered. Every
`register_*.ps1` defaults `-RepoRoot` to the checkout that contains the registrar
(`Split-Path -Parent (Split-Path -Parent $PSScriptRoot)`), so a task registered from a linked worktree keeps
executing that worktree. **Merging a `.ps1` to `master` does not change what such a task runs until the task is
re-registered (redeployed) from the intended checkout.** The script path and the data root are separate: a
deployed action can run a worktree's script with `-RepoRoot` and working directory set to the production
checkout, so it executes old script text against live production `data/` and the production venv.

Do not assume the production checkout. On the production host many enabled `Weather*` tasks execute from linked
worktrees. Known cases (2026-09-18 audit; the first three actions were re-read with the command below on 2026-09-19.
Re-verify rather than trusting this list):

| Task | Executes | Consequence |
| :--- | :--- | :--- |
| `WeatherBootRecovery` | `boot_recovery.ps1` in the linked worktree `weather-integration-attempt-recovery`, optionally pinned by `-ExpectedSelfSha256` (`register_boot_recovery.ps1 -ExpectedScriptSha256`) | A merged boot-recovery fix is inert until the task is re-registered. |
| `WeatherHostHealthWatchdog` | `health_watchdog.ps1` from a detached worktree named `weather-watchdog-deployed-<commit>`, with `-ExpectedSelfSha256`, `-StatusScriptPath` (that worktree's `status.ps1`) and `-ExpectedStatusScriptSha256` pinned in the action, and `-RepoRoot` set to the production checkout | A merged `status.ps1` or watchdog change does not reach the alarm path until a new pinned deployment is registered. An interactive `status.ps1` run from the production checkout can therefore disagree with the watchdog. The registrar requires reviewed watchdog and status SHA256 pins and checks the registered action. Source incorporates deployed tag `deployed/health-watchdog-aa99048` plus the newer bounded log rotation; any upgrade still requires owner-ops review and explicit re-registration. The watchdog also holds a reviewed, reasoned expected-disabled list (`$expectedDisabledTasks`): only the disabled-state flag of an exactly named task there becomes a standing note; every other flag still alerts. |
| `WeatherMemoryCommitGuard` | `scripts\ops\memory_commit_guard.ps1` in the production checkout, no hash pin (`register_memory_commit_guard.ps1`) | A merge to `master` changes guard behavior at the next one-minute tick, with no redeploy and no review gate. |
| Integration-attempt suite and merge tasks | the orchestration scripts of the checkout that ran `register_integration_attempt.ps1`, with every dependency hash frozen in the manifest | Drift fails closed; see [INTEGRATION_ATTEMPT_RUNBOOK](INTEGRATION_ATTEMPT_RUNBOOK.md). |

Check before reasoning about any task's behavior (read-only, light):

```powershell
Get-ScheduledTask -TaskName 'Weather*' | Where-Object State -ne 'Disabled' |
  ForEach-Object { [pscustomobject]@{ Task = $_.TaskName; State = $_.State
    Execute = $_.Actions[0].Execute; Arguments = $_.Actions[0].Arguments
    WorkingDirectory = $_.Actions[0].WorkingDirectory } } | Format-List
git worktree list
```

Read the path inside `Arguments` (`-File <path>` or an encoded wrapper contract) and `WorkingDirectory`, then match
it against `git worktree list`. If it is not the production checkout, the code to read is
`git -C <that worktree> show HEAD:<script>`, not `master`. When a fix must reach such a task, the work item is
"merge **and** redeploy", and the redeploy is a Scheduler mutation that needs its own authorization.

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

4. Run `python -m weather.operations.capture_recovery_check --json`. A worker
   passes only when status and writer-lock managed-process identities agree
   with the live OS creation token and exact code-owned command. PID liveness,
   a fresh stale heartbeat, or an uninspectable process fails closed.
5. Open the dashboard with `scripts/launch/start_weather_dashboard.cmd` or
   `scripts/launch/start_weather_dashboard.ps1`.
6. Confirm the Control Room at `http://localhost:8501/?market=control` reports
   current runtime identity and fresh capture. This view is read-only.

## Loop Outputs

### Weather Snapshot Loop

Snapshot and CLOB registrar actions use `weather.operations.thin_ensure
--ensure --loop snapshot|clob`. Its proven-healthy path imports only
supervisor/status/runtime-identity helpers, checks the live PID, writer lock,
heartbeat and loaded-source fingerprint, and writes the normal supervisor
status. CLOB also checks its process inventory and healthy discovery results.
Any uncertainty, pause, errors, stale code, missing lock, orphan or target-mode
mismatch delegates to the unchanged canonical ensure routine after releasing
the same supervisor lock. Recovery budgets and stop authority stay there.

After separately authorized host adoption, re-register from the production
checkout (these commands replace tasks and are not validation commands):
`./scripts/ops/register_snapshot_supervisor.ps1 -RepoRoot (Get-Location).Path
-TaskName WeatherSnapshotLoopSupervisor -EnsureEveryMinutes 2` and
`./scripts/ops/register_clob_supervisor.ps1 -RepoRoot (Get-Location).Path
-TaskName WeatherClobBookLoopSupervisor -EnsureEveryMinutes 1 -Market all
-IntervalSeconds 60 -FastIntervalSeconds 15`. Preserve any deliberately
reviewed host overrides instead of silently replacing them with defaults.
Verify both tasks' Actions, Principal, Triggers and Settings with
`Get-ScheduledTask`; the principal stays current-user S4U/Limited.

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
the child rather than the transient launcher. When the supervisor computes
recovery history, a pre-launch start refusal with no
launched PID is not a recovery and does not reset backoff. A failed launched
child and a failed restart remain countable because either can have mutated or
thrashed a process; outcome-less legacy recovery records remain countable.
While the producer is armed or still active, `roll_verdict.ps1` and
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
and issue `ensure` to restore it. Use the loop's supported CLI and owning
runbook rather than killing an arbitrary Python process; the dashboard has no
recovery controls.

## Dashboard Role

The Control Room is the read-only human cockpit for current checkout identity,
loop health, readiness, evidence freshness, and the capped International maker
pilot decision. The Roadmap is the active-work view. Neither page places or
cancels orders, changes risk, manages credentials, promotes releases, or
controls host processes. Status CLIs, their JSON files, and owning runbooks
remain the fail-closed diagnostic and control surfaces when Streamlit is
unavailable.

Reporting jobs have their own launchers, status artifacts, and evidence gates.
They consume capture output but are not a fourth capture loop. The former bot
daily-roll workers and supervisors were deleted with the retired taker and paper
maker on 2026-09-29.

## Daily Refresh Delegated-Child Tasks

Per-step profiling is opt-in: add `--profile-steps --profile-out <run-directory>`
to an otherwise approved, admitted daily-refresh invocation. It does not
grant a new execution window or change child containment. The optional
`requirements-profiling.txt` supplies pyinstrument; without it the JSON
records pyinstrument as unavailable while tracemalloc/memory capture remains.
No profiler is started and no profile files are written by default.

Each executed step writes a small JSON report with wall time, top twenty
tracemalloc allocation sites and traced peak bytes, plus sampled Windows
PrivateUsage (100 ms, process only). Private memory is null when unavailable,
including on unsupported platforms; it is never mislabeled RSS. A separate
bounded text sidecar holds pyinstrument output when installed. Isolated
children write `isolated_step` reports, and the parent writes separate
`orchestrator` reports including its wait. Do not sum those wall times or
treat parent memory as the child's peak. Hard-killed children may have no
terminal profile; containment receipts remain authoritative. Diagnostic
failures do not change step results, exceptions, resource caps or deadlines.
See [pyinstrument's API](https://pyinstrument.readthedocs.io/en/latest/reference.html)
for reading its sample-based output.

`scripts/ops/register_daily_refresh.ps1` registers both daily stages as
scheduled PowerShell wrapper actions:

- `WeatherDailySettlementPromotionRefresh` starts Stage A settlement at 09:30
  local with a four-hour task limit. Its scheduled child suppresses the former
  immediate Stage-B trigger, so Stage A releases the shared heavy-work lease
  before any evidence work is eligible to start.
- `WeatherEveningEvidenceRefresh` has one trigger at 00:35 local with an
  eight-hour child SLA through 08:35, an 8h25m wrapper span through its 09:00
  teardown, and an 8h40m scheduler limit through 09:15 for bounded cleanup
  before Stage A. The strict composition is `28800 < 30300 < 31200` seconds.
  Across midnight it
  requires an exact completed Stage-A
  manifest for the independently derived overnight operating date minus two
  days; an old manifest cannot select its own stale date. It skips only when
  that exact Stage-B binding is already complete. Missing, target-mismatched,
  or incomplete Stage-A evidence terminalizes Stage B as `critical` and
  returns nonzero.

Correct timing, target binding, and containment do not by themselves authorize
enabling Stage B. Its established monolithic-memory hold remains in force until
the evidence workload is chunked and its representative resource receipts pass
the host-load contract. The registrar therefore leaves Stage B disabled unless
the operator explicitly supplies `-EnableEvidenceTask`, then reads the task
state, exact 00:35 trigger, and `PT8H40M` limit back and fails if they disagree.
No alternative `EvidenceAt` is supported. Stage B also omits `StartWhenAvailable`:
a missed 00:35 trigger must not become a guaranteed refusal after its 09:00
window.

A stage manifest is a required publication, not optional reporting. Its
single atomic write includes the Stage-A trigger disposition; any publication
exception changes the pipeline to terminal `error`, rewrites both durable
status and Markdown report, suppresses the post-lock trigger, and returns a
nonzero CLI result. Scheduled `--disable-stage-trigger` writes final `SKIPPED`
in that first publication, so the post-lock path returns it without another
write. For non-disabled/manual topology, failure to replace `PENDING` with the
actual trigger result likewise rewrites status/report to `error`, and Stage B
rejects any manifest whose trigger disposition remains `PENDING`.

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

Scheduled Stage A runs current fleet observability without the separate full
historical audit or full-corpus trust replay. The latter would otherwise call
`score_all_markets` across every settled `snapshots_long.csv`. The scheduled
artifact records trust readiness as honestly `SKIPPED`/omitted rather than
manufacturing an empty pass. It also omits runtime-identity evidence because
that reader scans every snapshot tape before its target filter; the artifact
marks that evidence separately `SKIPPED`/omitted. Finally, it omits the
duplicate all-run MM starvation and MM/taker trading summaries because Stage A
already produced current trading evidence; that omission is also explicit. The
live fleet/tape/provenance summary is an isolated child
with a 20-minute timeout, 3,072 MiB private-memory ceiling, and 2,048 MiB
working-set ceiling. The orchestrator writes a resumable terminal fallback
before child code starts and validates the child terminal before advancing.
This leaves at least ten minutes between an 11:20 fleet start, its containment
timeout, and the outer 11:55 teardown. Full historical audits remain available
through the explicit fleet-observability CLI and are not silently represented
as part of the scheduled Stage-A receipt. Any bounded omission adds a fleet
warning, so the current-run fleet receipt cannot authorize promotion. Fleet
JSON and nightly retrain status
publish by atomic replacement, so containment teardown cannot expose a
partially written status document.

### Settlement in the chain: what it does and does not do

The step order is `STEP_REGISTRY` in `src/weather/operations/daily_refresh_registry.py`; Stage A is every step
through `fleet_observability`, Stage B starts at `promotion_refresh`. Facts that decide settlement evidence:

- **Single shot.** Stage A has one daily 09:30 trigger with `StartWhenAvailable` and no restart or retry setting
  (`register_daily_refresh.ps1`). A run that is refused, deferred or killed is not retried inside its window. The
  next run is tomorrow's, and it does not look back.
- **Each run settles only yesterday.** A missed or failed day leaves a permanent hole until that date is
  backfilled explicitly.
- **Settlement is not first.** `public_wu_settlement_restore` and `market_day_labels_finalize` are steps four and
  five, behind three learning-lane steps (`reanalysis_recent_refresh`, `ingest_quality_gate`,
  `event_metadata_validation`) that have nothing to do with settlement. A global hard stop in one of those
  (physical-resource deferral, isolated-child failure) ends the run before settlement is attempted.
- **The commit gate is relative to the live commit limit.** Stage A refuses above
  `DEFAULT_STAGE_A_MAX_COMMIT_PERCENT` (70, `daily_refresh_resources.py`; the CLI may only lower it) of the
  host's *current* commit limit, which moves with pagefile size. Never reason from a remembered limit. Read the
  live values from `data\logs\memory_commit_guard_status.json` (`commit_total_mb`, `commit_used_mb`,
  `commit_percent`), refreshed each minute by `WeatherMemoryCommitGuard`.
- **Backfill one date with the wrapper, never the runner.** Use
  `scripts\ops\settlement_backfill_one.ps1 -TargetDate <yyyy-MM-dd> -Refetch`. It drives
  `chain_recovery_run.ps1` for the bounded restore-to-finalize range ("One-date settlement recovery" below) and then verifies
  real settlement values in every market ledger, reporting `SILENT_NOOP` when the chain exited zero but nothing
  settled. Calling `chain_recovery_run.ps1` directly skips that check and reports OK on a run that settled nothing.
  Do not declare a date unrecoverable from a count of failed tries; the source has recovered on a later attempt.
- **The alarm has a horizon.** The `SETTLEMENT HOLE` flag in `status.ps1` scans `$windowDays = 14`
  (`weather.operations.settlement_hole_check --window-days`). An older hole drops out of the briefing while still
  unsettled. For an older range run the checker with larger `--window-days` and `--tail-lines` inside the heavy-work window, or
  read the per-market ledgers under `data/settlements/`.

## Bounded Suite And Integration Attempts

This section explains design intent only. [INTEGRATION_ATTEMPT_RUNBOOK](INTEGRATION_ATTEMPT_RUNBOOK.md) owns the
procedure and [development](../development.md#production-capture-host-16-gb) lists the runner limits; skip to
"Daily-Chain Recovery, Locks And Lanes" unless you are changing the attempt machinery.

The same containment primitive backs `scripts/ops/bounded_worktree_test_suite.ps1`.
That runner admits tests only from 00:30-09:00, against a registered clean
worktree whose branch and `HEAD` equal an explicit commit, while all three
capture workers are healthy and Windows commit is below the configured start
ceiling. It rechecks capture and commit between size-bounded pytest chunks,
writes a JUnit artifact per chunk, and owns each child in a kill-on-close Job.
Immediately before a full PASS it re-resolves the worktree and branch tip,
requires a clean tree, and compares the tracked pytest inventory to the plan.
The International SDK contract deliberately remains absent from the shared
production venv. `RequireLiveSdkContract` now makes its one contract test
validate and process-locally activate the repository-manifested external 0.6.0
overlay, including pre/post-import tree and offline-wheelhouse hashes. It does
not use `AdditionalPythonPath`; capture imports and the rest of the suite remain
on the ordinary worktree-plus-production-venv path. The older
`AdditionalPythonPath` diagnostic surface remains available to the bounded
runner, but immutable integration attempts continue to reject it.
It never merges, pushes, checks out, registers a task, or writes production
data; a full PASS is evidence for a separate reviewed merge, not the merge.

New overnight integrations compose that primitive through the immutable
attempt workflow in `INTEGRATION_ATTEMPT_RUNBOOK.md`. Each attempt runs a
repository-owned deterministic ratchet set before the full suite, writes
hash-bound logs and a suite receipt, and gives a separate one-shot merge task
authority only when the exact full-suite receipt is PASS. The manifest also
binds the installed orchestration hashes, task actions, branch tip, isolated
worktree, and canonical evidence paths. It rejects `AdditionalPythonPath` even
though the underlying diagnostic runner retains that option: an ambient import
tree is not immutable attempt evidence. Registration first writes an immutable
intent containing both tasks' complete principal, action, trigger, wake,
battery, overlap, execution-limit, idle, and network contract. Runtime and
merge consumption require a PASS registration receipt that hashes the intent,
then require the observed tasks to match it. Recovery uses that same full
identity when the receipt is valid and falls back to the manifest-derived
intent if the registrar died before publishing a receipt or left it torn;
action-only reconstruction is not sufficient.
The frozen orchestration identity includes `boot_recovery.ps1` and
`register_boot_recovery.ps1`, preventing a startup-trigger delay or registration
drift from escaping the immutable attempt boundary. The boot registrar accepts
an optional expected script SHA256, passes it into the startup action, then
re-reads the registered singleton and verifies its exact action, S4U/Limited
principal, zero-delay startup trigger, and fail-closed settings. A mismatch
disables the just-written task and raises an error.
Registrar, closer, and reconciler serialize terminal classification with an
OS-held attempt mutex; registration checks for closure/reconciliation inside it
before intent or Scheduler writes. Suite and merge wrappers independently reject
either terminal receipt at entry. The reconciler also holds the same
`heavy_workload.lock` as guarded merge across every evidence classification,
receipt write, and marker cleanup; publication resume additionally enforces the
heavy-work time window before using that already-held mutation mutex.

Attempt immutability is narrower than night immutability. A failure keeps its
manifest, logs, task names, and receipts forever; a reviewed repair creates a
new attempt namespace. One unchanged-tip retry is allowed for a classified
transient failure, while mechanical schema, ownership, and wrapper repairs are
limited by Git path/status allowlists. A second consecutive unchanged retry is
refused. If registration or a wrapper dies before emitting its receipt, the
closer validates and disables only exact non-running, intent-bound attempt tasks
and first proves checked-out production `master`, local `master`, and
`origin/master` are still the exact frozen baseline with the source tip absent,
before writing an immutable closure receipt. That proof is mandatory even when
no child report or active marker survived. Because disabling does not terminate
an already-started Scheduler instance, the closer then proves each task remains
absent or terminal+Disabled and immediately repeats the marker, `MERGE_HEAD`,
baseline, and ancestry classification; the receipt records that post-disable
proof. Any valid pushed or `merged_unpushed` report is non-closable durable
commit evidence even if current refs or the marker were later lost. Closure also
holds the guarded-merge `heavy_workload.lock` through classification, shutdown,
reproof, and receipt, eliminating the final ad-hoc merge TOCTOU. Downstream work
consumes the per-attempt merge receipt and
rechecks current capture plus checked-out branch `master` and
`HEAD == master == origin/master`; a mutable latest report or generic task exit
code is insufficient. The quiet-merge child writes its canonical attempt report
directly and maintains a durable in-progress marker across local mutation. Boot
recovery rolls unverified state back to the original synchronized baseline
while preserving only hash-checked generated config contents. A hash-bound
`pushed` report, or the narrower documented/published marker combined with
exact current local/remote Git, can classify a killed parent as published but
never authorizes downstream work. A hash-bound FAIL parent receipt may also be
reconciled when its v0.2 `merged_unpushed` report proves capture, conditional
execution-tape, and documentation recovery and a later reviewed push is
independently proved by
`HEAD == master == origin/master == report.merge_commit` plus source ancestry.
The marker is not mandatory when that immutable receipt/report pair exists.
Conversely, if a child dies post-commit before any report, the parent suppresses
its generic FAIL receipt only after the exact marker and two-parent/current-Git
shape pass, preserving marker-only recovery as the stronger terminal path.
If master advances after a valid pushed report but before the parent samples
refs, the parent refuses to mis-bind `MERGED_UNVERIFIED` to the later tip and
leaves the merge-receipt path absent for exact report-only reconciliation.
The former retry-time poison shape is recoverable only when the marker is exact
post-commit evidence and the subordinate abort report/FAIL receipt are exact
same-attempt pre-existing-marker refusal evidence with no contradictory commit
or publication fields.

Status correlates the immutable attempt with both scheduled tasks and the
preflight log, so a running suite is never described as a missed trigger. A
non-running suite that started but produced no receipt and a non-running merge
task whose trigger passed without a receipt are distinct actionable failures.
A disabled never-run suite fails the merge wait immediately, while a terminal
PASS observed during Task Scheduler's short running-to-ready transition gets a
two-minute exit grace at the 03:40 reserve. A non-running task whose Scheduler
result still carries a transient running/not-run code may proceed only from an
immutable PASS into the complete receipt/task-time validation, with the
disagreement recorded. Other non-terminal states wait only until the reserve,
then the exact task is stopped and must reach `Ready` or `Disabled`. Status
rechecks receipt existence after its task-state sample so a receipt published
mid-scan cannot create a false interrupted-suite alert. Suite evidence
timestamps are invariant-culture. If
publication is proven but final proof is incomplete, `MERGED_UNVERIFIED`
remains non-retryable and cannot authorize downstream work. A reviewed
reconciliation may recheck current Git and capture health and disable the exact
tasks, but its separate immutable `MERGED_RECONCILED` receipt explicitly does
not upgrade the historical proof. It can bind a MERGED_UNVERIFIED receipt, an
attempt-local pushed report when the parent receipt is absent, a recovered-
unpushed FAIL receipt after independently proved publication, or an exact raw
active-marker payload and SHA256 for the post-publication micro-window. A
reviewed `ResumePublication` path additionally consumes the
`merge_committed_unpublished` marker: under the shared workload lease it
rederives the exact baseline/preparation and two-parent commit, rechecks core
capture and conditional execution-tape status/lock/process/source integrity,
idempotently begins documentation, proves the content-addressed documentation
snapshot, validates the exact singleton current-user Interactive/Limited
`WeatherOneShotPush` task by its stable exported XML hash, and invokes it. The
immutable report, current marker, and content-addressed snapshot are re-hashed
immediately at that boundary. It still emits only non-authorizing
reconciliation evidence. Status validates complete schemas, attempt identities,
referenced hashes, and safety fields before exposing any receipt status; a bare
`{status: "PASS"}` is unreadable evidence, not success. It also scans canonical
registered manifests from their immutable registration intents so drift in the
merge task action cannot make an active attempt disappear from health reporting.
A fresh `merged_unpushed` commit is a FLAG requiring reviewed publication or
recovery, not a passive warning.

### One-time production baseline reconciliation (incident mode)

Built for a single incident (see the two `production-baseline` agent reports dated 2026-09-08 and 2026-09-09 under
`docs/roadmap/`). The code and its tests remain, so the contract below still binds any change to
`quiet_window_merge.ps1`, `reconcile_integration_attempt.ps1`, `production_baseline_scheduler_rpc.ps1` or the
`status.ps1` incident classifier. It is not a procedure to run again.

The one-time `production_baseline_reconciliation_v0.1` topology is deliberately
outside that generic attempt state machine. It starts from the exact accepted
local baseline while the published target is already ahead, creates a
config-only child `C`, and stages the frozen reviewed safety tip `S`, a strict
descendant of published target `T`, so the only acceptable commit is `M` with
ordered parents `[C,S]`. `M` must equal `S` plus only the two captured generated
config contents. Until `M`, raw-config, and affected-
producer recovery are all proved, the marker retains `T` as an adopted-boot
refusal sentinel rather than a reset target. The single atomic postcommit
cutover replaces it with `C` and a complete existing boot-recognized phase.
Generic attempt merge/reconcile/close consumers reject this operation mode.
Its push-attempt bit is durable before the sole pre-provisioned task invocation,
so task failure or missing acknowledgement is a terminal reviewed handoff, not
permission to retry. Because Windows bypasses a registered task's
`ExecutionTimeLimit` for on-demand starts, the incident mode owns a separate
15-minute deadline inside 04:00 and stable `Ready`/runtime readback. Every
reconciliation ScheduledTasks read, export, Start, and Stop is isolated in a
strict-request child owned by the parent's kill-on-close Job. Immediately before
every RPC launch, the parent re-hashes the helper against its exact `S`-pinned
dependency SHA-256. The request deadline is eight seconds before the applicable
PT15M/04:00 boundary: five seconds, clamped to the remaining time, are reserved
for `TerminateAndWait` proof and a further three seconds remain for bounded
  result parsing. Each child snapshot brackets the structured task read with
  the same name/path `Export-ScheduledTask` and UTF-8 hash path used by the
  parent freeze, treating a null `Triggers` property as zero while still
  rejecting any real trigger. The child re-resolves and fully attests the exact
  task twice, uses only the final `InputObject` for mutation, and emits bounded
  structured evidence which the parent independently validates. The exact Start
  request is
journaled before launch. Immediately before Scheduler mutation the helper
atomically creates a fixed durable one-use claim for Start, or for the exact Stop
ordinal, and never deletes it. Creation and durable flush are followed by one
immediate nonblocking deadline recheck before the direct `InputObject` mutation;
if the claim consumes the remaining budget, authority is spent/unknown and no
Scheduler dispatch occurs. A claim collision, or any cmdlet throw once a
durable claim exists, is authority-claimed with dispatch unknown and spent,
never a false no-dispatch. Thus a replay or lost result cannot reacquire the same
authority. Any failed, lost, or timed-out Start response spends the sole
authority and cannot PASS or write a published marker even if exact publication
is later observed.
Before the first Stop claim, every post-Start Scheduler read identity is bounded
to `pushContainmentStopAt`, preserving the complete 30-second mutation reserve;
a slow or hung read is killed before that edge. If a Stop identity or its budget
cannot be created, Stop authority is exhausted locally without recording a
false attempt or dispatch. No post-boundary marker is written, and the lease
plus read-only drain remains until exact terminal proof or the absolute report
boundary. Successful Stops remain capped at two;
any lost, timed-out, or uncertain Stop is terminal non-PASS and cannot be
retried. Stop exhaustion and any window breach are recorded and can never
publish PASS. This depends on an explicit exclusive-operator invariant: no other
caller may race the zero-trigger task between the final Ready proof and the sole
  start. The prepublication capture/documentation Python commands and canonical
  live-Git queries use the same kill-on-close ownership with absolute child
  deadlines. The writer rechecks 01:00-04:00 at every risky mutating stage,
  refuses a settle interval that cannot finish in-window, caps rollback recovery
  at 04:00, and re-proves live origin plus local refs after the final Start
  journal. No post-boundary marker replacement is attempted; the earlier
  attempted marker remains the conservative durable authority.
The special unpublished report stage remains
`reconciliation_merged_unpublished`, never generic `merged_unpushed`. Because
`M` adopts `S`, the production status/watchdog immediately understands the
incident marker. Exact complete evidence produces one of three states:
guarded-before-dispatch (manual invocation forbidden), attempted-unacknowledged
(publication pending/uncertain and retry forbidden), or exact acknowledged
(warning suppressed). Any incomplete, stale, malformed, unreadable/lookup-failed,
unrelated, or mismatched marker is `incident_evidence_invalid`: preserve the marker and bound
evidence, obtain reviewed recovery authority, and never manually invoke or
retry `WeatherOneShotPush`. Invalid evidence uses cached `origin/master`, not an
unfetched live SHA, for the unpushed count; an unreadable comparison produces a
neutral warning rather than a false zero. The classifier independently reproves topology, raw
snapshots, roll evidence, documentation, dependency hashes, task-RPC chronology,
clean worktree, immutable canonical-origin configuration, cached master, and a
  bounded live canonical master query. Before decoding, it rejects duplicate or
  case-colliding JSON keys at every nesting depth in the marker and every bound
  artifact. Relabeling populated reconciliation evidence as ordinary is invalid
  and cannot restore generic push guidance.

## Daily-Chain Recovery, Locks And Lanes

One-date settlement recovery uses the same containment and lock contracts but
adds an inclusive execution boundary:
`daily_refresh run --resume-from-step public_wu_settlement_restore
--stop-after-step market_day_labels_finalize`. A bounded run must report both
boundary steps and every selected intermediate step as `ok`; it exits normally
so Python `finally` blocks release daily-refresh and long-job locks. It does not
run readiness, publish stage manifests, trigger Stage B, update the daily
progress ledger, or continue into scoring/tiering work. The wrapper verifies
real finite settlement values in every market ledger after the child exits.

Daily-refresh and long-job lock payloads bind PID plus OS process creation
identity and image. Exact creation-token mismatch proves PID reuse; unreadable
identity fails closed. Legacy PID-only locks are considered stale only when
the current process was created after the lock or its image cannot be a Python
owner. Release also rechecks identity so an old process cannot unlink a
replacement instance's lock.

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
`data_retention_inventory`, `daily_learning` and
`market_beating_objective_scoreboard` admit work only with a current, target-bound
settlement verdict. The barrier's `learning_status` depends on WU restoration,
label finalization, settlement-source audit, the existing observed-floor policy,
replay-status repair and settled-day freshness/countability. Economics, trading
evidence and model-report readiness remain in its aggregate `status` for promotion;
their blocks do not suppress these three settlement-valid learning producers.
Missing, stale, generic-error and legacy blocked barrier receipts remain closed
until the barrier reruns. Each producer still applies its own input-quality
checks; admission does not claim successful learning or available maker evidence.

Learning admission does not change live-readiness or exchange gates.
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

The independent CLOB projection and raw-tape tiering wrappers also own their
Python child trees through `KILL_ON_JOB_CLOSE`, enforce bounded runtimes, write
their latest status atomically, and append every outcome to JSONL history.
`SKIPPED_WORKLOAD_LEASE_BUSY` remains a safe non-run, not successful reclaim;
`status.ps1` reads the durable status and surfaces the skip beside disk slope
even when Task Scheduler reports zero. Registered times are fixed by `ValidateSet`: `WeatherClobTiering` at 05:00
(`register_clob_tiering.ps1`) and `WeatherClobRawTapeTiering` at 06:00 (`register_clob_raw_tape_tiering.ps1`).

Free space on the production volume is therefore a daily sawtooth, not a level: capture writes uncompressed
long order-book CSV for open event days all day, and the 05:00 job returns that space. The daily low is just
before it runs and sits well under an evening reading. Judge every disk floor (the 50 GiB suite floor, training
preflight, capture safety) against the daily low. The
[data retention policy](data-retention-policy.md) owns the numbers, the `capture.write_order_books_long_csv`
switch in `config/storage_pressure.json`, and how to read the live value.

Before the settled-day analysis barrier, the read-only
`observed_floor_safety_monitor` joins captured `observed_floor_bucket` values
from `snapshot_explanations.jsonl` to finalized settlement labels. Missing
snapshot explanation coverage or unattributed floor provenance is `BLOCK`; any
floor above settlement is `ALERT`. The monitor records the exact market, target
date, snapshot, floor, settlement, rescue source, and overshoot in buckets. It
never reconstructs or replays a model.

**Default posture (introduced as temporary on 2026-07-31 and still the code default; the release lock it waited
for is off the critical path):** `ALERT` and `BLOCK` are alert-only unless the flag below is passed. They remain
prominent in status, rollup, and the daily report, but do not block the
settled-day barrier; the original reason was that losing a paper-analysis day outweighed the block. This does
not make the monitor optional or weaken detection. Pass `--fail-on-observed-floor-safety` to `daily_refresh`
(`daily_refresh_cli.py`) to restore fail-closed barrier enforcement; the standalone monitor uses `--fail-closed`.
Whether to flip the default is an open owner decision, not something a registration change should do silently.

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

**Status: disabled by owner decision.** No retraining task should be enabled on the production host; confirm with
`Get-ScheduledTask -TaskName 'WeatherTrainingWindow*','WeatherNightlyRetrainValidatePromote'` and
[STATE_OF_PLAY](STATE_OF_PLAY.md). This section describes the design for when the owner re-arms it. The procedure
is owned by the [Nightly Retrain Runbook](NIGHTLY_RETRAIN_RUNBOOK.md).

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
tree through a kill-on-close Job. Settlement has the sole scheduled exception
through 11:55; evidence runs only in the ordinary heavy window and closes its
Job at 09:00. Thus overnight Stage B cannot overlap the 09:30 settlement task,
and a delayed or long settlement run cannot enter the 12:00–18:00 graded
capture window. These deadlines are independent of per-step memory admission
and Task Scheduler's broader execution limit.

`scripts/ops/training_window_contract.ps1` is the single action-token owner for
both training-window registration and delegated-child attestation. Changing
the task name, executable, repository path, or wrapper action requires a
deliberate re-registration; stale definitions fail closed rather than being
treated as scheduled evidence.

## Daily triggers and DST

`New-ScheduledTaskTrigger -Daily -At` stores a zoned StartBoundary (`...Z` in memory, a fixed `-04:00` once Task
Scheduler saves it). A zoned boundary is a fixed UTC instant, so after daylight saving time ends every such task
fires one hour early on the local clock (DST audit 2026-10-07, finding DST-C1). Every daily registrar therefore
dot-sources `scripts/ops/scheduled_task_local_trigger.ps1`, builds its trigger with `New-WeatherLocalDailyTrigger`
(an unzoned `yyyy-MM-ddTHH:mm:ss` local boundary that follows DST) and reads it back with
`Test-WeatherLocalDailyStartBoundary`, which refuses any zone suffix. A `[datetime]` cast is not a read-back: it
converts `00:30:00-04:00` to local time and hides the offset. Repeating `-Once -RepetitionInterval` triggers and
run-specific one-shot triggers are interval- or instant-based and stay as they are.
`tests/operations/test_scheduled_task_local_daily_triggers.py` fails on any daily trigger built outside the helper,
anywhere in the repository. It checks:
- `New-ScheduledTaskTrigger -Daily/-Weekly/-Monthly`, including commands split with backticks; it uses the
  PowerShell AST on Windows and joined lines elsewhere;
- `-Once` triggers whose repetition is a day or longer;
- COM `Triggers.Create(2..5)`;
- `schtasks /sc daily|weekly|monthly`;
- zoned `<StartBoundary>` task XML;
- any registrar that emits a zoned daily boundary;
- any PowerShell script that does not parse.

For an existing task with no registrar, `scripts/ops/reset_daily_trigger_local.ps1` removes the zone from its
calendar triggers in place (see the runbook below).

### DST re-registration (OD28)

Fixing the registrars changes nothing on the host until each daily task is re-registered from a checkout that
contains the fix. A task with no registrar has its trigger re-set instead. The master-agent (production operator)
does this; no other agent registers anything.

**Scope.** Master's read-only host sweep (2026-10-07 09:46) found 21 enabled `Weather*` tasks, all with `-04:00`
StartBoundaries. Only the calendar (daily) triggers below move on 2026-11-01. The "If left unfixed" column gives
the local time each would fire from then on.

| Pri | Task | Local time | If left unfixed | How |
| --- | --- | --- | --- | --- |
| **1** | `WeatherTrainingWindowRestore` | 04:15 | **03:15** | `register_training_window.ps1` |
| 2 | `WeatherColdSnapshotNightly` | 06:50 (the host still has 00:30) | 05:50 (23:30) | `register_cold_snapshot_nightly.ps1` |
| 3 | `WeatherDailySettlementPromotionRefresh` + `WeatherEveningEvidenceRefresh` | 09:30 / 00:35 | 08:30 / 23:35 | `register_daily_refresh.ps1` |
| 4 | `WeatherClobTiering` | 05:00 | 04:00 | `register_clob_tiering.ps1` |
| 5 | `WeatherClobRawTapeTiering` | 06:00 | 05:00 | `register_clob_raw_tape_tiering.ps1` |
| 6 | `WeatherExchangeEconomicsSnapshotRefresh` | 06:50 | 05:50 | `register_exchange_economics_refresh.ps1` |
| 7 | `WeatherLocationConfigRefresh` | 00:00, 06:00, 12:00, 18:00 | 23:00, 05:00, 11:00, 17:00 | `register_location_config_refresh.ps1` |
| 8 | `WeatherStalenessSweep` | 08:10 | 07:10 | no registrar: `reset_daily_trigger_local.ps1 -ExpectedAt 08:10` |
| 9 | `WeatherStreakCaptureMonitor` | 12:00, then every 30 minutes | 11:00, so the 12:00-18:00 watch starts an hour early | no registrar: `reset_daily_trigger_local.ps1 -ExpectedAt 12:00` |

**`WeatherTrainingWindowRestore` is the highest priority.** At 03:15 its `RestoreOnly` run can start capture
workers inside the 01:00-04:00 quiet merge window. A roll-sensitive merge in that window expects the workers to be
stopped, or is proving their recovery. Do this task first. If the pass cannot finish, do this one alone.

**Not affected; no action.**
- Repeating `-Once` TimeTriggers fire after each elapsed interval through both DST transitions:
  - the supervisors (PT1M/PT2M);
  - the guards and watchdogs (PT1M/PT5M/PT15M);
  - `WeatherMakerEvidenceCapture` (PT5M);
  - `WeatherManualOrderJournal` (PT5M).
- None of the repository's repeating triggers has a duration window anchored to its StartBoundary:
  - the supervisors use a 3650-day duration;
  - `WeatherMemoryCommitGuard` blanks its one-day duration to infinite after registration;
  - the rest have no duration.
- The streak monitor's 30-minute repetition hangs off its daily trigger and moves with it, which is why it is row 9.
- `WeatherDataMirror` and `WeatherMirrorRestoreVerify` are not enabled on the host, so they do not apply.

**When.** On 2026-10-29 or 2026-10-30, after the fix has landed and production is running it.
- Work outside the 12:00-00:30 protected windows, and not while a Stage-A chain or bounded suite is running.
- Just before each row, confirm that the task's `State` is not `Running`.
- Finish before 01:00 on 2026-11-01. Row 1 at least must be done by then.

**Steps.** For a registrar row, re-run the registrar with exactly the parameters the live task was registered
with; read them from the live action first. None of these changes the task's command except row 6. Row 6 converts
the live task from RunLevel Highest and `-Command` to Limited and `-File`, with a status file (Swarm P audit F1;
see the [economics runbook](EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md)).

- Row 1: run with its current parameters. The training window stays disabled.
- Row 2: pass the current approved policy path, its hash, `-ExpectedSourceTip` and `-Apply`
  ([cold-snapshot-compression](cold-snapshot-compression.md)). This also moves the host's legacy 00:30 trigger to
  the 06:50 slot approved on 2026-10-05.
- Row 3: one run with the same Full or `-ProvenanceOnly` parameters as now. Stage B stays disabled; do not add
  `-EnableEvidenceTask`.
- Rows 8 and 9: neither has a repository registrar or task XML in the repository, so do not recreate them. Use
  `scripts/ops/reset_daily_trigger_local.ps1`, which re-sets only the calendar trigger.
  - It removes the zone suffix and keeps the registered wall time.
  - It leaves the action, principal, settings, other triggers and the trigger's repetition unchanged.
  - It refuses a `Z` boundary, a trigger count or time that differs from `-ExpectedAt`, and monthly triggers.
  - Run it once without `-Apply`: it prints the plan and changes nothing. Then run it with `-Apply`, which calls
    `Set-ScheduledTask -Trigger` and reads the result back.
  - If `Set-ScheduledTask` is refused for the S4U principal, stop. Export the task XML for owner review rather
    than recreating the task.

> **DO NOT RUN `register_maker_evidence_capture.ps1` — not in this pass, and not at any time until the owner
> answers the PT5M question.** Its registrar still writes **PT1M**, but the intended and live interval is **PT5M**.
> Re-running it silently reverts the interval and brings back about 1,440 refused starts a day. The task needs no
> DST action anyway ([passive maker evidence capture](passive-maker-evidence-capture.md)).

**Verify afterwards (read-only).**
1. For every task in the table, `(Get-ScheduledTask -TaskName <name>).Triggers.StartBoundary` must show no `Z` or
   `+/-hh:mm` suffix on a daily trigger.
2. List each task's next run times across the change with the `GetRunTimes` probe below. It uses Add-Type and COM
   only, and registers and changes nothing.

```powershell
Add-Type -TypeDefinition @"
using System;using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential)] public struct ST{public ushort Y,Mo,Dow,D,H,Mi,S,Ms;public override string ToString(){return string.Format("{0:D4}-{1:D2}-{2:D2} {3:D2}:{4:D2}",Y,Mo,D,H,Mi);}}
[ComImport,Guid("9c86f320-dee3-4dd1-b972-a303f26b061e"),InterfaceType(ComInterfaceType.InterfaceIsDual)] public interface IRT{
[PreserveSig]int a(out IntPtr p);[PreserveSig]int b(out IntPtr p);[PreserveSig]int c(out int p);[PreserveSig]int d(out short p);[PreserveSig]int e(short p);
[PreserveSig]int f(IntPtr a,out IntPtr b);[PreserveSig]int g(IntPtr a,int b,int c,IntPtr d,out IntPtr e);[PreserveSig]int h(int a,out IntPtr b);
[PreserveSig]int i(out double p);[PreserveSig]int j(out int p);[PreserveSig]int k(out int p);[PreserveSig]int l(out double p);[PreserveSig]int m(out IntPtr p);
[PreserveSig]int n(out IntPtr p);[PreserveSig]int o(int a,out IntPtr b);[PreserveSig]int q(IntPtr a,int b);[PreserveSig]int r(int a);
[PreserveSig]int GetRunTimes(ref ST s,ref ST e,ref uint n,out IntPtr t);}
public static class RTx{static ST S(DateTime d){var s=new ST();s.Y=(ushort)d.Year;s.Mo=(ushort)d.Month;s.D=(ushort)d.Day;return s;}
public static string[] Get(object t,DateTime f,DateTime to){var a=S(f);var b=S(to);uint n=200;IntPtr p;int hr=((IRT)t).GetRunTimes(ref a,ref b,ref n,out p);if(hr<0)throw new Exception(hr.ToString("X"));
var r=new string[n];int z=Marshal.SizeOf(typeof(ST));for(int i=0;i<n;i++)r[i]=Marshal.PtrToStructure(new IntPtr(p.ToInt64()+i*z),typeof(ST)).ToString();Marshal.FreeCoTaskMem(p);return r;}}
"@
$svc = New-Object -ComObject Schedule.Service; $svc.Connect()
foreach ($n in 'WeatherTrainingWindowRestore','WeatherColdSnapshotNightly','WeatherDailySettlementPromotionRefresh',
    'WeatherEveningEvidenceRefresh','WeatherClobTiering','WeatherClobRawTapeTiering',
    'WeatherExchangeEconomicsSnapshotRefresh','WeatherLocationConfigRefresh','WeatherStalenessSweep',
    'WeatherStreakCaptureMonitor') {
  "$n : " + ([RTx]::Get($svc.GetFolder('\').GetTask($n), [datetime]'2026-10-30', [datetime]'2026-11-04') -join ' | ') }
```

**Pass:** every task keeps the same local times each day, including from 2026-11-02 onward. For example:
`2026-10-31 04:15 | 2026-11-01 04:15 | 2026-11-02 04:15`. The streak monitor's first run each day stays at 12:00.

**Fail:** a run one hour earlier from 2026-11-01 or 2026-11-02, for example `... | 2026-11-02 03:15 | ...`. That
means the task still has a zoned boundary.

- A disabled task (Stage B, unless enabled) may return no run times; check its StartBoundary instead.
- If a task lives in a subfolder, change `GetFolder('\')`.

**Around the change itself (owner decisions 2026-10-07).**

- OD30: no merges and no bounded suites between 01:45 and 02:15 local on 2026-11-01; the 01:00-02:00 hour occurs
  twice that night.
- 05-F3: do not run the integration sequencer on the night of 2026-10-31 to 2026-11-01.

## Why Capture Is Not Packaged Into The Dashboard

A shortcut or executable is useful for opening the dashboard, but it is not a
durable supervisor. It can be closed, crash, or never start after reboot. If a
packaged desktop launcher is added later, it should continue to launch only the
human-facing dashboard. Task Scheduler and the loop `ensure` contracts remain
the owners of evidence capture.

## Update this file when

Update when capture-loop ownership, supervisor tasks/commands, status or log
contracts, dashboard controls, deployment/restart behavior, which checkout a task executes from, daily-chain step
order or settlement recovery, daily-trigger construction or the DST re-registration list, or retraining
topology changes.
