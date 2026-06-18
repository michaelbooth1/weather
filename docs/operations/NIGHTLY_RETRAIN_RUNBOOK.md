# Nightly Retrain Validate Promote Runbook

This runbook covers the overnight self-improvement job that refreshes daily
learning, retrains candidate artifacts, validates promotion evidence, and
writes one operator-readable status report.

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
