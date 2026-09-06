# Operations Design

## Target Shape

The operating setup has three layers:

1. Windows Task Scheduler runs short-lived supervisors that keep three
   streak-critical capture loops healthy and, when explicitly armed, one
   auxiliary public execution-tape producer healthy.
2. A lightweight desktop launcher starts the two-page Streamlit dashboard and
   opens the read-only Control Room.
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
breaking, refuses an unproven stop, and readopts changed code. Its status reader
retries a briefly unavailable or non-object snapshot up to three times with
50 ms between reads. It evaluates the recovered heartbeat against a clock
sample taken after the read; persistent failure remains unknown and all
process, source-identity and writer-lock checks still apply. While the
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
even when Task Scheduler reports zero.

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
