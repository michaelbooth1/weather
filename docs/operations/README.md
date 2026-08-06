# Operations Documentation

This directory contains the durable operating contracts for the repository.
Use this page as the index; link to the owning document instead of copying its
commands or policies into another guide.

## Start Here

- [Project Operating SOP](PROJECT_OPERATING_SOP.md) is the end-to-end
  shift-to-release decision flow and routes each action to its owning runbook.
- [Operations Design](OPERATIONS_DESIGN.md) describes the three capture loops,
  their Windows supervisors, runtime identity, and deployment routine.
- [Repository Path Policy](path-policy.md) defines canonical package execution,
  repository-owned paths, and where generated output belongs.
- [Host Load Policy](HOST_LOAD_POLICY.md) defines the protected capture window,
  resource limits, and the single-host training window.
- [Module Ownership Map](module-ownership-map.md) and
  [Package Boundaries](package-boundaries.md) route code changes to their
  owning subsystems.

[Agent Context](AGENT_CONTEXT.md) owns durable domain invariants. It deliberately
excludes current metrics, versions, local runtime state, and backlog priorities;
use generated reports and the active backlog for those facts.

## Accumulated Knowledge

Three documents hold what the ~600-file dated correspondence under `docs/roadmap/`
established. That record is too large for any agent to read; these are its
distillation and should be read before model, measurement, or research work.

- [Established Findings](ESTABLISHED_FINDINGS.md) owns measured results about the
  model, the market gap, the cool bias, the serving floor, and feature blindness,
  each with its support and interval treatment.
- [Retracted Claims And False Leads](RETRACTED_AND_FALSE_LEADS.md) owns claims that
  were published and withdrawn, plus operational alarms that look real and are not.
  Read it before acting on a surprising result.
- [Delegation Contract](DELEGATION_CONTRACT.md) owns the standing boundaries,
  roll-verdict method, and required structure for cross-host handoffs and reports.

These files record evidence, not invariants. Re-verify a number against its named
source report before citing it in a new decision.

## Development And Validation

- [Python Runtime Audit Gate](PYTHON_RUNTIME_AUDIT_GATE.md) covers the focused
  runtime lint, daily-refresh smoke, Streamlit-route smoke, and log-signature
  checks.
- [Research Audit Harness](RESEARCH_AUDIT_HARNESS.md) distinguishes fixture-only
  and networked research scripts and provides the supported smoke workflow.
- [Repository Path Policy](path-policy.md) owns the editable-install and
  `python -m weather...` command convention.

The root `README.md`, `pyproject.toml`, `pytest.ini`, and
`.github/workflows/ci.yml` are the authoritative setup and baseline-test
surfaces. Run commands from the repository root with the repository virtual
environment.

## Runtime Operations

- [Operations Design](OPERATIONS_DESIGN.md) owns capture supervision, status
  files, dashboard control, and code-restart guidance.
- [Host Load Policy](HOST_LOAD_POLICY.md) owns when heavy work may run on the
  capture host.
- [Nightly Retrain Runbook](NIGHTLY_RETRAIN_RUNBOOK.md) owns research and
  production candidate-only retraining plus immutable inactive-release
  construction.
- [Exchange Economics Snapshot Runbook](EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md)
  owns publication, review, acceptance, and drift checks for exchange rules.
- [Weather Underground Current-Day Degradation](2026-06-21-wu-history-current-day-degradation.md)
  is the incident-specific recovery note for that failure mode.

Task names, default cadences, and required registration parameters are defined
by the scripts under `scripts/ops/`. Read a script's `param(...)` block before
registration; some production tasks require explicit evidence paths and cannot
be registered safely with an argument-free example.

## Configuration, Paths, And Artifacts

- [Config Inventory](config-inventory.md) classifies every checked-in config
  file and owns its freshness policy.
- [Artifact Storage Policy](artifact-storage-policy.md) owns Git, Git LFS,
  externalization, size thresholds, restore, and promotion preflight.
- [Repository Path Policy](path-policy.md) owns `config/`, `artifacts/`,
  `data/`, `docs/`, and `tests/fixtures/` placement.
- [Schema Registry Reconciliation](schema-registry-storage-log-reconciliation.md)
  maps durable schemas to producers and storage/log contracts.

Scoped agent instructions also live in `config/AGENTS.md`,
`artifacts/AGENTS.md`, and `scripts/ops/AGENTS.md`.

## Data Evidence And Retention

- [Data Storage Class Contract](data-storage-class-contract.md) defines
  `canonical_evidence`, `analysis_projection`, and `operator_cache`.
- [Data Retention Policy](data-retention-policy.md) defines inventory and
  reviewed cleanup requirements.
- [Closed Market-Day Parquet Archive Contract](closed-market-day-parquet-archive-contract.md)
  defines archive eligibility, manifests, and raw-evidence boundaries.
- [History Data Design](HISTORY_DATA_DESIGN.md) describes Weather Underground
  history storage and settlement-proxy handling.

Never infer deletion safety from age, size, or apparently duplicate names.
Use the storage-class contract and a reviewed cleanup manifest.

## Evaluation And Research Operations

- [Point-In-Time Evaluation Runbook](POINT_IN_TIME_EVALUATION.md) defines the
  evidence key, materialization, production preselection and qualification,
  folds, and locked evaluation workflow.
- [Point-In-Time Forecast Training Corpus](PIT_FORECAST_TRAINING_CORPUS.md)
  defines immutable forecast planning, request-keyed staging, cutoff-safe
  publication, and explicit pooled-retraining consumption.
- [Research Audit Harness](RESEARCH_AUDIT_HARNESS.md) owns reproducible audit
  entrypoints.

Files with dates in their names and `ops_fix_todo_*.md` are incident records,
audits, or work logs. They may explain why a contract exists, but they do not
override the current code, registration scripts, or undated policy documents.

## Update this file when

Update this index when an undated operations contract is added, renamed,
archived, or changes ownership. Update the owning document in the same change
when modifying:

- a CLI or dashboard entrypoint;
- a scheduled-task name, cadence, required parameter, or supervision model;
- a checked-in config classification or freshness rule;
- an artifact, release, storage-class, retention, or cleanup contract; or
- a runtime status, diagnostic, or log path used for recovery.

Do not turn this index into another command catalog. Keep details in the
document or script that owns them.
