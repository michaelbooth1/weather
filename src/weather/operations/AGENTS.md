# Operations Guidance

Scope: scheduled jobs, supervisors, and lifecycle orchestration under
`src/weather/operations/`. Inherits [package-wide guidance](../AGENTS.md).

- Operations modules coordinate domain entrypoints; they should not absorb
  model, market, source, or report business logic. Preserve the step-owner
  splits documented in the module ownership map.
- Status, diagnostics, locks, manifests, and reports are public operational
  contracts. Keep writes atomic, failures explicit, resume ordering stable, and
  stale-lock/process recovery fail-closed.
- Long-running Windows workers use the repo venv, repository working directory,
  `sitecustomize.py`, runtime-identity checks, and silent child-process defaults.
  Preserve those assumptions when changing Task Scheduler registration.
- `daily_refresh_registry.STEP_ORDER` is the canonical morning pipeline order.
  Maintain stage barriers and carried-forward resume state when adding steps.
- Nightly training writes candidate-only outputs and may construct an inactive
  immutable release only after qualification. Promotion/rollback must use the
  verified atomic release pointer; trainers must never write into an active or
  immutable release tree.
- Prefer `status`, `--dry-run`, temporary output paths, and focused unit tests
  during verification. Do not start, stop, register, or mutate live scheduled
  jobs unless the task explicitly requires it.

Run focused tests in `tests/operations/`, including import architecture for new
module edges. Canonical references are
[Operations Design](../../../docs/operations/OPERATIONS_DESIGN.md),
[Nightly Retrain Runbook](../../../docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md),
and [Large Module Ownership Map](../../../docs/operations/module-ownership-map.md).

## Update this file when

Update when orchestration ownership, status/lock contracts, scheduled-worker
assumptions, pipeline ordering, release behavior, or operations verification
changes.
