# Operations Documentation

This page is the index of `docs/operations/`. It routes; it does not restate. Link to the owning
document instead of copying its commands or policies into another guide.

**The linking rule, stated once:** every file in `docs/operations/` and `docs/operations/history/`
— dated or not, Markdown or JSON — is linked from this index with a one-line "read when". Undated
contracts go in the topical tables. Files with a date in their name are incident records, traces or
work logs: they go in [Dated records (historical)](#dated-records-historical) with their true
status, and never override current code, registration scripts or undated policy. The daily
`scripts\ops\staleness_sweep.ps1` (`docs/unreachable`) is a weaker backstop: it exempts dated names
and counts a link from *any* Markdown file, so a file can pass the sweep and still be missing here.
If you add a file, link it here in the same change.

## Start here

| Document | Read when |
| --- | --- |
| **[STATE_OF_PLAY.md](STATE_OF_PLAY.md)** | **Always, first.** The only file that says what is happening now, what is decided, and what is already answered. Rewritten, not appended. |
| [OPERATIONS_AGENT_ROLE.md](OPERATIONS_AGENT_ROLE.md) | You are the agent operating the 16 GB production capture host. |
| [HOST_LOAD_POLICY.md](HOST_LOAD_POLICY.md) | Before any heavy command on the capture host. Owns the protected windows, resource limits, the training reservation and the full workstation heavy-wrapper contract. |
| [OPERATING_REFERENCE.md](OPERATING_REFERENCE.md) | You need a governing constant or protected window with its source location. **Generated — fix the constant, never the doc.** The live timetable is generated separately at `data/alerts/OPERATING_SCHEDULE.md`; verify Task Scheduler before assuming an entry will run. |
| [reserved-confirmation-window.md](reserved-confirmation-window.md) | Before reading dated evidence or settled market-days. Read its `Status:` line; the rest applies only when a window is reserved, and then it wins over every other document. |
| [DELEGATION_CONTRACT.md](DELEGATION_CONTRACT.md) | Writing a handoff, executing a delegated mission, verifying a handback, or deciding roll sensitivity. |
| [AGENT_CONTEXT.md](AGENT_CONTEXT.md) | You need durable domain invariants: settlement, units, source roles, floors, evidence rules. Deliberately excludes metrics, versions and priorities. |
| [PROJECT_OPERATING_SOP.md](PROJECT_OPERATING_SOP.md) | You need the end-to-end shift-to-release decision flow and which runbook owns each step. |
| [Git workflow SOP](../git-workflow.md) | Branches, worktrees, commits, pushes, merges, branch retirement. Single owner of git authority. |

## Accumulated knowledge

These hold what the dated correspondence under `docs/roadmap/` established. That record is too
large for any agent to read. **Each file owns exactly one question, and no other file should answer
it.** They record evidence, not invariants: re-verify a number against its named source before
citing it in a new decision.

| Document | Owns the question |
| --- | --- |
| [FINDINGS_DIGEST.md](FINDINGS_DIGEST.md) | *What is the short version?* — read first for model, measurement or research work; it cites the sections below worth opening. |
| [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md) | *What do we know?* — every measured result and interval. Read before model, measurement or research work. |
| [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) | *What is false?* — withdrawn claims, and alarms that look real and are not. |
| [HOW_WE_GET_THINGS_WRONG.md](HOW_WE_GET_THINGS_WRONG.md) | *What shape do our mistakes take?* — read before designing a gate or trusting a green signal. |
| [CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md) | *How much α is spent, and on what?* — the binding decision ledger. Read before proposing any confirmatory look; only the operator allocates. |

Open work is **not** tracked here. Owned work lives in numbered roadmap items, surfaced by the
generated [`../roadmap/active-backlog.md`](../roadmap/active-backlog.md). What is open on the host
right now is the generated `data/alerts/MORNING_BRIEFING.md` and `scripts\ops\status.ps1`.

## Development and validation

| Document | Read when |
| --- | --- |
| [path-policy.md](path-policy.md) | Adding a CLI, a path, or generated output: canonical `python -m weather...` execution and repository-owned paths. |
| [module-ownership-map.md](module-ownership-map.md) | Routing a code change to its owning subsystem. |
| [package-boundaries.md](package-boundaries.md) | Adding an import across packages. |
| [PYTHON_RUNTIME_AUDIT_GATE.md](PYTHON_RUNTIME_AUDIT_GATE.md) | Running or changing the focused runtime lint, daily-refresh smoke, Streamlit-route smoke or log-signature checks. Its tracked baseline is [python-runtime-audit-baseline.json](python-runtime-audit-baseline.json). |
| [RESEARCH_AUDIT_HARNESS.md](RESEARCH_AUDIT_HARNESS.md) | Running a research audit script; distinguishes fixture-only from networked entrypoints. |

The root `README.md`, `pyproject.toml`, `pytest.ini` and `.github/workflows/ci.yml` are the
authoritative setup and baseline-test surfaces; [`../development.md`](../development.md) owns
verification depth.

## Runtime operations

For the independent public maker collector, its task and retention, read
[passive-maker-evidence-capture.md](passive-maker-evidence-capture.md).

| Document | Read when |
| --- | --- |
| [OPERATIONS_DESIGN.md](OPERATIONS_DESIGN.md) | Touching capture supervision, status files, the dashboard, or restart guidance. |
| [INTEGRATION_ATTEMPT_RUNBOOK.md](INTEGRATION_ATTEMPT_RUNBOOK.md) | Landing a reviewed branch on production: exact-tip preflight, full suite, quiet merge, failure closure, bounded repair. |
| [Capture-day grading and guarded-merge runbook](../ops/streak-soak.md) | Checking capture-day health, `status.ps1` / `streak.ps1`, the watchdog, boot recovery, `quiet_window_merge.ps1`. The streak it measures is a diagnostic, not an objective. |
| [NIGHTLY_RETRAIN_RUNBOOK.md](NIGHTLY_RETRAIN_RUNBOOK.md) | Candidate-only retraining or immutable inactive-release construction. |
| [EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md](EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md) | Publishing, reviewing, accepting or drift-checking exchange rules. |
| [mission-dispatch-reconciliation.md](mission-dispatch-reconciliation.md) | A handoff has no visible branch and you are about to call it lost. |

Required registration parameters are defined by the scripts under `scripts/ops/`. Read a script's
`param(...)` block before registration; some production tasks require explicit evidence paths.
**No Git document can say whether a dated one-shot is armed, running, or produced its receipt** —
read `data/alerts/OPERATING_SCHEDULE.md` on the production host and verify the live scheduler.

## Trading and live execution

No live trading is authorized by any document here; `STATE_OF_PLAY.md` records current authority.

| Document | Read when |
| --- | --- |
| [INTERNATIONAL_MM_LIVE_PILOT.md](INTERNATIONAL_MM_LIVE_PILOT.md) | Any work toward the bounded International Polymarket maker pilot. Never authorizes Polymarket US and never makes a blocked gate pass. |
| [PORTABLE_LIVE_EXECUTION_HOST.md](PORTABLE_LIVE_EXECUTION_HOST.md) | Provisioning, binding or relocating the second-PC attended Stage 0/1 executor. |
| [maker-incentive-feasibility.md](maker-incentive-feasibility.md) | Evaluating an explicit maker BUY plan against incentives; a pure calculation contract. |

## Configuration, paths and artifacts

| Document | Read when |
| --- | --- |
| [config-inventory.md](config-inventory.md) | Adding or changing a checked-in config file; owns classification and freshness. |
| [artifact-storage-policy.md](artifact-storage-policy.md) | Git vs Git LFS vs external storage, size thresholds, restore, promotion preflight. |
| [git-lfs-policy.md](git-lfs-policy.md) | Anything touching LFS. **Never re-add `lfs: true` to a workflow; never delete `.git/lfs`.** |
| [schema-registry-storage-log-reconciliation.md](schema-registry-storage-log-reconciliation.md) | Mapping a durable schema to its producer and storage/log contract. |

Scoped agent instructions also live in `config/AGENTS.md`, `artifacts/AGENTS.md` and
`scripts/ops/AGENTS.md`.

## Data evidence, retention and storage recovery

Never infer deletion safety from age, size or apparently duplicate names. Use the storage-class
contract and a reviewed cleanup manifest.

| Document | Read when |
| --- | --- |
| [data-storage-class-contract.md](data-storage-class-contract.md) | Classifying data as `canonical_evidence`, `analysis_projection` or `operator_cache`. |
| [data-retention-policy.md](data-retention-policy.md) | Planning any inventory or cleanup. |
| [storage-plan-2026-09-23.md](storage-plan-2026-09-23.md) | Free space below the green band, a heavy job refusing on disk, or before any compress/archive/reclaim. |
| [HISTORY_DATA_DESIGN.md](HISTORY_DATA_DESIGN.md) | Working on Weather Underground history storage or settlement-proxy handling. |
| [verified-cold-archive.md](verified-cold-archive.md) | Create-only archive objects, verification, restore drill, cleanup-plan contracts. |
| [cold-archive-locations.md](cold-archive-locations.md) | Finding an archived object's original path, cloud object ID, recovery proof or restore cache. |
| [closed-market-day-parquet-archive-contract.md](closed-market-day-parquet-archive-contract.md) | Archive eligibility, manifests and raw-evidence boundaries for a closed market-day. |
| [production-cold-archive-staging.md](production-cold-archive-staging.md) | The owner has re-authorized archive staging/upload, or you are reading a staging receipt. |
| [storage-recovery-inventory.md](storage-recovery-inventory.md) | You need a source-bound, metadata-only file selection for compression or archive. |
| [cold-snapshot-compression.md](cold-snapshot-compression.md) | The owner asks for retained-file capacity, or you reconcile an interrupted compression attempt. |
| [replay-cache-compression.md](replay-cache-compression.md) | The owner asks for replay-cache capacity (lossless compression, never eviction). |
| [storage-recovery-night.md](storage-recovery-night.md) | The owner authorizes an unattended compression night, or you reconcile its result. |
| [workstation-disk-and-mirror-scope.md](workstation-disk-and-mirror-scope.md) | Reclaiming disk on the workstation. The mirror it describes is **paused** ([record](mirror-paused-2026-08-12.md)); on restart, deleting there without excluding at source is undone by `/MIR`. |

## Evaluation and research operations

| Document | Read when |
| --- | --- |
| [settlement-source-audit.md](settlement-source-audit.md) | Touching the settlement-source audit, its bounded storage path, source-lineage classification, or the truth-label gate for settlement-scored trading evidence. Owner: `weather.reporting.source_gates.settlement_source_audit`. |
| [POINT_IN_TIME_EVALUATION.md](POINT_IN_TIME_EVALUATION.md) | Evidence key, materialization, preselection/qualification, folds, locked evaluation. |
| [PIT_FORECAST_TRAINING_CORPUS.md](PIT_FORECAST_TRAINING_CORPUS.md) | Immutable forecast planning, request-keyed staging, cutoff-safe publication, pooled-retraining consumption. |
| [forecast-source-and-training-population.md](forecast-source-and-training-population.md) | Anyone raises provider licensing or the training population. **Closed: free-tier Open-Meteo only; do not stop a mission on it.** |
| [the-season-window-blocks-the-retrain.md](the-season-window-blocks-the-retrain.md) | Touching forecast-archive coverage or the first-retrain corpus. |

## Release #1 (deferred — off the critical path)

| Document | Read when |
| --- | --- |
| [release-one-deferred-until-a-retrained-candidate.md](release-one-deferred-until-a-retrained-candidate.md) | **First**, before any release #1 work: the 2026-08-06 decision that it waits for a retrained candidate. |
| [RELEASE_ONE_BUILD_RUNBOOK.md](RELEASE_ONE_BUILD_RUNBOOK.md) | The deferral has been lifted and you are building release #1. |
| [release-one-is-not-the-mm-critical-path.md](release-one-is-not-the-mm-critical-path.md) | Relating release #1 to the maker track. Carries a **retracted** headline — read the correction, not the title. |
| [release-market-day-boundary.template.json](release-market-day-boundary.template.json), [release-promotion-decision.template.json](release-promotion-decision.template.json) | Preparing the boundary proof or reviewed promotion decision the release runbook requires. Templates only. |

## Dormant logs (HISTORICAL)

| Document | Status |
| --- | --- |
| [OPEN_BACKLOG.md](OPEN_BACKLOG.md) | **DORMANT** since 2026-08-14. Hand-kept list of unowned operational defects; its one item is now owned by `ESTABLISHED_FINDINGS.md` §8l. Use numbered roadmap items instead. |
| [OVERNIGHT_BRIEFINGS.md](OVERNIGHT_BRIEFINGS.md) | **DORMANT** since 2026-08-11. Two hand-written overnight narratives. The live after-away read is the generated `data/alerts/MORNING_BRIEFING.md`. |

## Dated records (historical)

Date-named files explain why a contract exists. **None is current authority, and none describes
today's host state.** Status is the state of the *subject*, as recorded in the file or verified in
git; re-verify before relying on it.

| Record | Status | Read when |
| --- | --- | --- |
| [2026-06-21-wu-history-current-day-degradation.md](2026-06-21-wu-history-current-day-degradation.md) | CLOSED — classified; framing superseded by the 08-07 root cause | WU history returns HTTP 400 for the current day. |
| [ops_fix_todo_2026_07_03.md](ops_fix_todo_2026_07_03.md) | CLOSED — work log | Tracing a July ops fix. |
| [release-one-lock-evidence-2026-08-04.md](release-one-lock-evidence-2026-08-04.md) | CLOSED — record; release #1 since deferred | Auditing the lock-day evidence. |
| [release-one-chain-block-triage-2026-08-04.md](release-one-chain-block-triage-2026-08-04.md) | CLOSED — record | The chain ends `deferred` with every step `ok`. |
| [release-one-floor-flip-deferred-2026-08-04.md](release-one-floor-flip-deferred-2026-08-04.md) | DEFERRED — decision record | Someone proposes flipping the observed-floor monitor to fail-closed. |
| [deleted-branch-recovery-manifest-2026-08-05.md](deleted-branch-recovery-manifest-2026-08-05.md) | CLOSED — recovery manifest | Restoring a ref deleted in the 08-05 cleanup. |
| [wu-settlement-source-down-2026-08-07.md](wu-settlement-source-down-2026-08-07.md) | **FIXED** 2026-08-07 (`e6a89db2e`, on `master`). Not an outage: an advertising key was scraped instead of the API key | A *new* settlement failure is uniform across every date and market — check the part you are not varying. Not a description of any current settlement hole. |
| [taker-paused-and-pruned-2026-08-07.md](taker-paused-and-pruned-2026-08-07.md) | **PAUSED** — operator decision, in force until reversed | Anything touching the taker bot, its tasks or its pruned run tree. |
| [SERVED_BAND_FLOOR_DEFECT_2026-08-10.md](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md) | **FIXED** 2026-06-15 — a serialization defect, not a live serving defect | Served-band zeros on the realized outcome appear in old rows. |
| [REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md) | CLOSED — measured trace | Comparing a replayed floor with what was served. |
| [GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md](GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md) | CLOSED — trace; decision 10 stays retired | Reading a gate result computed on replayed rather than served values. |
| [PRE_OVERNIGHT_AUDIT_2026-08-10.md](PRE_OVERNIGHT_AUDIT_2026-08-10.md) | CLOSED — point-in-time audit | Tracing the 08-10 overnight decisions. |
| [FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md](FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md) | **FIXED** (`bcb49506`) and recovered 12/12 | A settlement day is missing after finalize, or a low streak follows a healthy capture day. |
| [REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md) | CLOSED — thread closed; do not dispatch another historical-reproduction mission | Anyone proposes reconstructing what we served from history. |
| [mirror-paused-2026-08-12.md](mirror-paused-2026-08-12.md) | **PAUSED** — operator decision; the live answer is the `WeatherDataMirror` task state | Anything touching the off-host mirror, workstation `data\`, or mirror flags in `status.ps1`. |
| [codex-host-overload-2026-08-23.md](codex-host-overload-2026-08-23.md) | CLOSED — incident trace; prevention lives in `HOST_LOAD_POLICY.md` rule 6 | Why Codex verification is serial and time-gated. |

### History appendices

Text moved out of always-read files. Verbatim, unmaintained, never authority.

| File | Holds |
| --- | --- |
| [history/host-load-policy-expired-exceptions.md](history/host-load-policy-expired-exceptions.md) | Expired one-date owner exceptions from `HOST_LOAD_POLICY.md`, and where their date-bound literals still live in code. |
| [history/operations-agent-role-snapshot-2026-08-13.md](history/operations-agent-role-snapshot-2026-08-13.md) | The 2026-08-13 handover snapshot that was §7 of `OPERATIONS_AGENT_ROLE.md`. |
| [history/scripts-ops-agents-incident-modes.md](history/scripts-ops-agents-incident-modes.md) | Spent incident mode and pasted contracts moved out of `scripts/ops/AGENTS.md`. |

## Update this file when

A file is added to, renamed in, archived from or removed from `docs/operations/` (dated or not), a
document changes ownership, or a dated record's subject changes status (a pause is lifted, a fix
lands). Update the owning document in the same change when modifying:

- a CLI or dashboard entrypoint;
- a scheduled-task name, cadence, required parameter, or supervision model;
- a checked-in config classification or freshness rule;
- an artifact, release, storage-class, retention, or cleanup contract; or
- a runtime status, diagnostic, or log path used for recovery.

Do not turn this index into another command catalog. Keep details in the document or script that
owns them, and keep counts, dates of "now" and host state out of it.
