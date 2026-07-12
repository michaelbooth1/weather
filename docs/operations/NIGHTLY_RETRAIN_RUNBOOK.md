# Nightly Retrain, Validate, And Build Candidate Release Runbook

This runbook covers the overnight self-improvement job that refreshes daily
learning, retrains candidate artifacts, validates promotion evidence, and
writes one operator-readable status report. It never activates a model: the
scheduled job can only build an immutable, inactive candidate release.

## Register The Task

Run from the repository root:

```powershell
.\scripts\ops\register_nightly_retrain.ps1
```

The scheduled task is `WeatherNightlyRetrainValidatePromote`. It runs daily at
`03:30` local time and calls:

```powershell
python -m weather.operations.nightly_retrain run --fail-on-daily-learning-blocker
```

That flag is also the CLI default. It makes `daily_learning.status == BLOCKED`
stop the run before expensive retraining or promotion refresh steps.

## Smoke Test

After registering the task, run:

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

Training output paths are candidate-only by default. An old serving path fails
before training begins. `--allow-legacy-serving-output` is a temporary migration
flag: it marks the run quarantined, blocks immutable release construction, and
cannot permit writes into `artifacts/releases` or the active pointer.

If daily learning is blocked, the nightly report should show status `blocked`,
only the `daily_learning` step should have run, and the Daily-Learning Blockers
table should list the exact P0 gates and actions.

## Missed-Run SLA

The SLA check expects a fresh `nightly_retrain_status.json` after the latest
`03:30` local scheduled window plus a two-hour grace period. If no fresh status
exists, `weather.operations.nightly_retrain status` returns a critical state
and names the expected task and status file.

The Operations dashboard shows the same state in the Nightly Self-Improvement
table: task registration, next run, status freshness, daily-learning blocker
count, and the first P0 gate.
