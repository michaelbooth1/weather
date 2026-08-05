# Scheduled Operations Instructions

These instructions apply to `scripts/ops/`.

- These PowerShell files are the source of truth for Windows scheduled-task
  names, default cadences, actions, required arguments, working directories,
  and recovery settings. Read the complete script and its `param(...)` block
  before changing or invoking it.
- Do not publish a bare registration command when the script has mandatory
  evidence, artifact, route, or production-readiness parameters. The default
  `Full` parameter sets for `register_daily_refresh.ps1` and
  `register_nightly_retrain.ps1` require such inputs. Daily refresh has one
  explicit transitional exception: `-ProvenanceOnly` registers both wrapper
  tasks with scheduler provenance and release arguments while deliberately
  omitting the production-evidence contract. Never describe that mode as FULL
  evidence or production readiness.
- Canonical scripts live here. Files directly under `scripts/` are compatibility
  shims unless another owning document says otherwise.
- Registration scripts assume the repository root, its `venv`, and Windows
  Task Scheduler. Re-registration replaces the named task; it is an external
  system change, not a harmless validation step.
- Editing a script does not authorize registering, disabling, starting, or
  deleting a task. Make those changes only when the user explicitly places the
  host scheduler in scope.

The three capture supervisors are snapshot, CLOB, and observation-trigger.
Keep their task names and `ensure` arguments aligned with
`docs/operations/OPERATIONS_DESIGN.md`. An intentional stop must account for
both the detached worker and the supervisor that can revive it.

`WeatherMakerExecutionCapture` is a separate long-lived WebSocket evidence
producer, not a fourth `ensure` supervisor. Its registration source is
`register_mm_execution_capture.ps1`. Editing that script never authorizes
registration or provider access, and a missing/incomplete per-event session
receipt must remain non-countable for the maker-day checklist.

Choose one retraining topology per host:

- `register_nightly_retrain.ps1` directly schedules retraining and does not stop
  capture.
- `register_training_window.ps1` schedules a bounded single-host window plus a
  dead-man restore; `training_window.ps1` stops and restores all three capture
  loops.

Do not leave both topologies enabled for the same workload. Preserve the
training window's `finally` restoration and independent restore task when
modifying it.

Producer provenance follows the chosen topology. The direct nightly action
passes `scheduler-invocation-topology=direct`. The daily-refresh tasks and
training window are scheduled PowerShell wrappers whose Python processes are
`delegated_child`. Daily registration and its wrapper must build the same
task-specific tokens through `daily_refresh_contract.ps1`; the training-window
pair uses `training_window_contract.ps1`. Both reuse the shared scheduled-task
argument string and base64 token-contract converters. Missing or mismatched
action tokens, task
identity, child executable, working directory, running state, or run-time
correlation must remain non-countable. Direct and delegated provenance both
observe the current PID, OS image, complete command line, current working
directory, creation time, optional exact venv redirector, and current scheduler
engine PID/instance. Delegated lineage continues to the registered wrapper
within the two-ancestor bound. Child-supplied flags alone are not evidence.

Validate PowerShell syntax without executing scripts, run the focused Python
tests for the affected operation, and update the operations design or owning
runbook whenever a task name, cadence, parameter, status path, or supervision
contract changes.

## Update this file when

Update when task registration safety, canonical script locations, capture or
training topology, or PowerShell verification changes.
