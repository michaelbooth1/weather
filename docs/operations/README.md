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
- **[Operating Reference](OPERATING_REFERENCE.md) answers "what governs this host?"** —
  protected windows and governing constants with their source locations. **Generated,
  never hand-edited:** tracked output depends only on repository-owned inputs. The live
  timetable is generated separately at `data/alerts/OPERATING_SCHEDULE.md`; check the
  scheduler and task receipts before assuming an entry will run or succeeded.
- [Host Load Policy](HOST_LOAD_POLICY.md) defines the protected capture window,
  resource limits, and the single-host training window. It owns the *policy*;
  the Operating Reference owns the *current numbers*.
- [Portable Live Execution Host](PORTABLE_LIVE_EXECUTION_HOST.md) owns the
  second-PC provisioning, public SDK transfer, exact host binding, and
  relocation procedure for the attended International Stage 0/1 lane.
- [Module Ownership Map](module-ownership-map.md) and
  [Package Boundaries](package-boundaries.md) route code changes to their
  owning subsystems.

[Agent Context](AGENT_CONTEXT.md) owns durable domain invariants. It deliberately
excludes current metrics, versions, local runtime state, and backlog priorities;
use generated reports and the active backlog for those facts.

## Accumulated Knowledge

These documents hold what the ~600-file dated correspondence under `docs/roadmap/`
established. That record is too large for any agent to read; these are its
distillation and should be read before model, measurement, or research work.

**Each owns exactly one question, and no other file should answer it.**

| Document | Owns the question |
| --- | --- |
| [STATE_OF_PLAY.md](STATE_OF_PLAY.md) | *What is happening right now?* — **read first** |
| [Established Findings](ESTABLISHED_FINDINGS.md) | *What do we know?* — every measured result and interval |
| [Retracted Claims And False Leads](RETRACTED_AND_FALSE_LEADS.md) | *What is false?* — withdrawn claims, and alarms that look real and are not |
| [How We Get Things Wrong](HOW_WE_GET_THINGS_WRONG.md) | *What SHAPE do our mistakes take?* — five recurring patterns; read before designing a gate or trusting a green signal |
| [Open Backlog](OPEN_BACKLOG.md) | *What is known-broken and unassigned?* — ranked, hand-kept |
| [Delegation Contract](DELEGATION_CONTRACT.md) | *How do we work?* — boundaries, roll verdicts, handoff structure |
| [Operating Reference](OPERATING_REFERENCE.md) | *What are the governing constants and protected windows?* — **generated; fix the constant, not the doc** |

`OPEN_BACKLOG` is **not** [`../roadmap/active-backlog.md`](../roadmap/active-backlog.md): that one is
generated from the numbered roadmap items and tracks feature work, this one tracks operational
defects nobody owns.

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
- [Immutable Integration Attempts](INTEGRATION_ATTEMPT_RUNBOOK.md) owns
  exact-tip preflight, full-suite, quiet-merge, failure closure, bounded repair,
  and downstream receipt authority for overnight branch integration.
- [Nightly Retrain Runbook](NIGHTLY_RETRAIN_RUNBOOK.md) owns research and
  production candidate-only retraining plus immutable inactive-release
  construction.
- [Exchange Economics Snapshot Runbook](EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md)
  owns publication, review, acceptance, and drift checks for exchange rules.
- [Weather Underground Current-Day Degradation](2026-06-21-wu-history-current-day-degradation.md)
  is the incident-specific recovery note for that failure mode.

Required registration parameters are defined by the scripts under `scripts/ops/`. Read a
script's `param(...)` block before registration; some production tasks require explicit
evidence paths and cannot be registered safely with an argument-free example.

**For what is actually scheduled and when, read
`data/alerts/OPERATING_SCHEDULE.md` on the production host and verify the live
scheduler.** No Git document can authoritatively answer whether a dated
one-shot remains armed, is running, or produced its required receipt.

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

## Start here, and the records reachable only from here

- **[STATE_OF_PLAY.md](STATE_OF_PLAY.md) — read first.** What is happening now, what is
  decided, and what is already answered. Rewritten not appended; capped at ~90 lines.
- **[wu-settlement-source-down-2026-08-07.md](wu-settlement-source-down-2026-08-07.md) — LIVE
  INCIDENT.** The settlement proxy returns 404 for *every* date, including ones already stored.
  `-Refetch` works and still fails. Read before touching settlement, the chain, or the streak.
- **[reserved-confirmation-window.md](reserved-confirmation-window.md) — wins over every other
  document, including this index.** Check it at run time before acting on any trading window.
- [OPERATIONS_AGENT_ROLE.md](OPERATIONS_AGENT_ROLE.md) — what the production-host agent owns.
- [RELEASE_ONE_BUILD_RUNBOOK.md](RELEASE_ONE_BUILD_RUNBOOK.md) — the release #1 build procedure
  (currently **deferred**; read the deferral decision below first).
- [forecast-source-and-training-population.md](forecast-source-and-training-population.md) —
  free-tier Open-Meteo only, training population 2021–2025. **Closed; do not stop a mission on it.**
- [release-one-deferred-until-a-retrained-candidate.md](release-one-deferred-until-a-retrained-candidate.md)
  — 2026-08-06 decision: release #1 waits for a retrained candidate.
- [the-season-window-blocks-the-retrain.md](the-season-window-blocks-the-retrain.md) — why the
  first retrain blocks at 0/12,600 cells.
- [workstation-disk-and-mirror-scope.md](workstation-disk-and-mirror-scope.md) — the workstation
  is full because production mirrors 532 GB to it nightly; **deleting there without excluding at
  source is undone by `/MIR`**.
- [release-one-is-not-the-mm-critical-path.md](release-one-is-not-the-mm-critical-path.md) —
  carries a **retracted** headline; read the correction, not the title.
- [mission-dispatch-reconciliation.md](mission-dispatch-reconciliation.md) — telling a
  never-dispatched mission from a completed one.
- [git-lfs-policy.md](git-lfs-policy.md) — **never re-add `lfs: true`; never delete `.git/lfs`.**
- [deleted-branch-recovery-manifest-2026-08-05.md](deleted-branch-recovery-manifest-2026-08-05.md)
  — every ref deleted in the 08-05 cleanup, with its disposition.
- [release-one-lock-evidence-2026-08-04.md](release-one-lock-evidence-2026-08-04.md),
  [release-one-chain-block-triage-2026-08-04.md](release-one-chain-block-triage-2026-08-04.md),
  [release-one-floor-flip-deferred-2026-08-04.md](release-one-floor-flip-deferred-2026-08-04.md)
  — the lock-day record.
- [ops_fix_todo_2026_07_03.md](ops_fix_todo_2026_07_03.md) — historical work log.

**Anything added under `docs/operations/` must be linked from this index.** The CI docs audit
checks that links are not *broken*; it does not check that a file is *reachable*, so an unlinked
document is invisible to a cold agent and will be re-derived or contradicted. The daily
`scripts\ops\staleness_sweep.ps1` reports unreachable files under `docs/unreachable`.

**That sweep check is weaker than the rule stated here**, and knowingly so: it counts a document as
reachable if *any* markdown links it, including dated `docs/roadmap/` correspondence that `AGENTS.md`
says cannot be read. So a file can pass the sweep and still be missing from this index. On
2026-08-06 four were — `reserved-confirmation-window.md` among them, the document that wins over
every other. If you add a file here, link it here; do not rely on the sweep to notice.

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
