# Nightly Retrain, Validate, And Build Candidate Release Runbook

This runbook covers the overnight self-improvement job that refreshes daily
learning, retrains candidate artifacts, validates promotion evidence, and
writes one operator-readable status report. It never activates a model: the
scheduled job can only build an immutable, inactive candidate release.

## Choose One Scheduling Topology

There are two alternative scheduling patterns:

- Dedicated single-host capture: `register_training_window.ps1` owns a bounded
  maintenance window that stops and always restores all three capture loops.
- Separate-capacity/direct scheduling: `register_nightly_retrain.ps1` owns
  `WeatherNightlyRetrainValidatePromote`, which defaults to `03:30` local time.

Do not enable both patterns for the same workload. The direct registration
requires explicit served/replay captured-input parity files, served artifact
bindings, and the served route. Read its `param(...)` block and provide reviewed
current paths; there is intentionally no argument-free production example.

The direct task calls:

```powershell
python -m weather.operations.nightly_retrain run --fail-on-daily-learning-blocker
```

That flag is also the CLI default. It makes `daily_learning.status == BLOCKED`
stop the run before expensive retraining or promotion refresh steps.

## Smoke Test

Before or after registration, use the non-activating dry-run and read-only
status paths:

```powershell
python -m weather.operations.nightly_retrain run --dry-run
python -m weather.operations.nightly_retrain status
```

When daily learning is currently blocked and you want to verify the
short-circuit path without training, run:

```powershell
python -m weather.operations.nightly_retrain run --step-timeout-seconds 300
python -m weather.operations.nightly_retrain status
```

Expected outputs:

- `data/backtest/nightly_retrain_status.json`
- `data/backtest/nightly_retrain_report.md`
- `data/backtest/nightly_retrain_sla_status.json`
- `data/backtest/nightly_retrain_sla_status_report.md`
- `artifacts/candidates/nightly-<UTC timestamp>/...` for mutable training outputs
- `artifacts/releases/nightly-<UTC timestamp>/release_manifest.json` only when
  every existing validation gate passes and the source tree is clean

The active pointer remains `artifacts/releases/current_release.json`. Nightly
retraining does not create or modify it. Promotion remains a separate reviewed
operation through `python -m weather.operations.release_lifecycle promote`,
which requires both a matching promotion-decision proof and a fresh
market-day-boundary proof.

## Reviewed Rollback

Rollback is also separate from nightly retraining. At a reviewed market-day
boundary, one command returns the pointer to its recorded prior release:

```powershell
python -m weather.operations.release_lifecycle rollback --market-day-boundary <reviewed-boundary-proof.json>
```

The command fully hash-verifies the rollback target and atomically writes a
self-hashed reconciliation intent before the atomic pointer replacement. It
then re-reads both the pointer and immutable release, emits the post-rollback
identity proof, and atomically finalizes the drill record at
`data/backtest/release_rollback_drill.json`. If finalization is interrupted,
the same command recognizes the exact pointer-bound intent and retries only
the proof/record finalization; it never toggles back to the failed release.
`--drill-record` may select an isolated output for a synthetic drill but cannot
point inside the immutable release tree.

Loop control remains an explicit operator step. The initial record truthfully
uses `status=PENDING_MANUAL_RESTART` and names the target runtimes under
`manual_coordinated_restart.required_runtimes`. A real drill becomes complete
only after those workers are coordinated onto the restored release, their
runtime-identity proof is attached, post-restart health passes, and the manual
restart, health, and overall statuses are all recorded as `PASS`.

Training output paths are candidate-only by default. An old serving path fails
before training begins. `--allow-legacy-serving-output` is a temporary migration
flag: it marks the run quarantined, blocks immutable release construction, and
cannot permit writes into `artifacts/releases` or the active pointer.

If daily learning is blocked, the nightly report should show status `blocked`,
only the `daily_learning` step should have run, and the Daily-Learning Blockers
table should list the exact P0 gates and actions.

## Missed-Run SLA

The SLA check expects a fresh `nightly_retrain_status.json` after the configured
scheduled window plus its grace period. If no fresh status exists,
`weather.operations.nightly_retrain status` returns a critical state and names
the expected task and status file. When the dedicated-host training window is
authoritative, interpret freshness together with its skip/preflight result and
restore status.

The Operations dashboard shows the same state in the Nightly Self-Improvement
table: task registration, next run, status freshness, daily-learning blocker
count, and the first P0 gate.

## Update this file when

Update when nightly step ordering, candidate/release output contracts,
registration parameters, scheduling topology, or SLA semantics change.
