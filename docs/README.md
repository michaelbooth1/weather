# Documentation Map

This index is the canonical router for repository knowledge. It owns two things:
which document answers a question, and what class each document is. **Read only
the rows that match your task.** Most of `docs/` is historical evidence, not
instruction. For operations runbooks, incident records, and decision records not
listed here, use [the operations index](operations/README.md).

Classes: **Current state** (the one file about today) · **Canonical**
guide/contract/runbook (durable, no dates or counts) · **Distillation** (what the
research established) · **Generated** (edit the generator) · **History**
(preserved, never authority).

## Every task

| Read | Why | Class |
| --- | --- | --- |
| [Root AGENTS.md](../AGENTS.md) (Claude Code: via [CLAUDE.md](../CLAUDE.md)) | Non-negotiable rules and task routing | Canonical guide, always loaded |
| [State of play](operations/STATE_OF_PLAY.md) | Current objectives, critical path, closed decisions, answered questions | Current state |
| The nearest nested `AGENTS.md` | Constraints for the subtree you will edit | Canonical guide |

## Route by task

| Read when you are… | Document | Class |
| --- | --- | --- |
| Doing model, measurement, or research work; or about to claim a number | [Findings digest](operations/FINDINGS_DIGEST.md) — short, mandatory; it cites the depth below | Distillation |
| …and need the full derivation behind a digest entry | [Established findings](operations/ESTABLISHED_FINDINGS.md) (read the cited section, not the file) | Distillation, reference depth |
| …and need to know what was claimed and was wrong | [Retracted claims and false leads](operations/RETRACTED_AND_FALSE_LEADS.md); the recurring error *shapes* are in [How we get things wrong](operations/HOW_WE_GET_THINGS_WRONG.md) | Distillation, reference depth |
| Spending a statistical decision on the sealed panel | [Campaign ledger](operations/CAMPAIGN_LEDGER.md) | Canonical control |
| Reading dated evidence or settled days for evaluation | [Reserved confirmation window](operations/reserved-confirmation-window.md) — its status line says whether anything is reserved | Canonical contract |
| Building a leakage-free evaluation or the PIT training corpus | [Point-in-time evaluation](operations/POINT_IN_TIME_EVALUATION.md), [PIT forecast training corpus](operations/PIT_FORECAST_TRAINING_CORPUS.md) | Canonical runbook |
| Unsure about settlement, units, source roles, or floors | [Agent context](operations/AGENT_CONTEXT.md) | Canonical guide |
| Asking whether a forecast source or training population is allowed | [Forecast source and training population](operations/forecast-source-and-training-population.md), [the season window](operations/the-season-window-blocks-the-retrain.md) | Canonical decision record |
| Acting on the production capture host | [Operations agent role](operations/OPERATIONS_AGENT_ROLE.md) | Canonical guide |
| A guard, marker or lock blocks work and you must decide whether to clear it | [Fail-forward recovery table](operations/fail-forward-recovery.md) | Canonical decision record |
| About to run anything heavy, on either host | [Host load policy](operations/HOST_LOAD_POLICY.md); generated numbers in [Operating reference](operations/OPERATING_REFERENCE.md) | Canonical policy; Generated |
| Writing, executing, or verifying a cross-host mission | [Delegation contract](operations/DELEGATION_CONTRACT.md), [roadmap agent guide](roadmap/AGENTS.md), [mission dispatch reconciliation](operations/mission-dispatch-reconciliation.md) | Canonical contract |
| Changing task names, loops, supervisors, or the dashboard role | [Operations design](operations/OPERATIONS_DESIGN.md) | Canonical guide |
| Merging on the production host, or protecting capture during a change | [Capture-day grading and guarded merges](ops/streak-soak.md), [Immutable integration attempts](operations/INTEGRATION_ATTEMPT_RUNBOOK.md) | Canonical runbook |
| Working on branches, worktrees, commits, pushes, or pull requests | [Git workflow SOP](git-workflow.md); LFS limits in [Git LFS policy](operations/git-lfs-policy.md) | Canonical runbook |
| Working on the maker pilot, live trading, or maker economics | [International MM live pilot](operations/INTERNATIONAL_MM_LIVE_PILOT.md), [Item 330 master plan](roadmap/items/item-330-maker-economics-refocus-master-plan.md), [Maker incentive feasibility](operations/maker-incentive-feasibility.md), [Exchange economics snapshot runbook](operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md) | Canonical runbook; numbered item |
| Moving the attended live executor to another PC | [Portable live execution host](operations/PORTABLE_LIVE_EXECUTION_HOST.md) | Canonical runbook |
| Retraining, or building or sequencing a release | [Nightly retrain runbook](operations/NIGHTLY_RETRAIN_RUNBOOK.md), [Release #1 build runbook](operations/RELEASE_ONE_BUILD_RUNBOOK.md), [Release #1 is deferred](operations/release-one-deferred-until-a-retrained-candidate.md), [Release #1 and the MM clock](operations/release-one-is-not-the-mm-critical-path.md) | Canonical runbook; decision record |
| Operating the project end to end | [Project operating SOP](operations/PROJECT_OPERATING_SOP.md) | Canonical runbook |
| Looking for work, or an item's scope, status, and evidence | [Active backlog](roadmap/active-backlog.md) (generated), `roadmap/items/item-*.md` (one owner per item), [ROADMAP.md](roadmap/ROADMAP.md) (full taxonomy), [Open backlog](operations/OPEN_BACKLOG.md) (known-broken, unowned) | Generated; canonical per item |
| Understanding system boundaries and data flow | [Architecture](architecture.md) | Canonical guide |
| Setting up, testing, or checking the definition of done | [Development](development.md), [Python runtime audit gate](operations/PYTHON_RUNTIME_AUDIT_GATE.md), [Research audit harness](operations/RESEARCH_AUDIT_HARNESS.md) | Canonical guide |
| Looking up product purpose, setup, dashboard, or an operator command | [Root README](../README.md) | Canonical guide |
| Changing or adding documentation | [Documentation maintenance](documentation-maintenance.md), [docs/AGENTS.md](AGENTS.md) | Canonical guide |

## Durable technical contracts

Read the one that owns the thing you are changing.

| Changing | Contract |
| --- | --- |
| Imports or package edges | [Package dependency boundaries](operations/package-boundaries.md) |
| A domain-neutral maker plugin, pure decision or evidence journal | [Maker core contracts](operations/maker-core-contracts.md) |
| A large module or facade split | [Large-module ownership map](operations/module-ownership-map.md) |
| Any repository path or default location | [Repository path policy](operations/path-policy.md) |
| A file under `config/` | [Configuration inventory](operations/config-inventory.md) |
| Tracked artifacts, LFS, or artifact size | [Artifact storage policy](operations/artifact-storage-policy.md) |
| What may be deleted, tiered, or compressed under `data/` | [Data storage classes](operations/data-storage-class-contract.md), [Data retention policy](operations/data-retention-policy.md) |
| Closed market-day archives | [Closed market-day archive contract](operations/closed-market-day-parquet-archive-contract.md) |
| Cold archive and restore | [Verified cold archive](operations/verified-cold-archive.md), [Production cold-archive staging](operations/production-cold-archive-staging.md), [Cold archive locations and restore cache](operations/cold-archive-locations.md), [Cold snapshot NTFS compression](operations/cold-snapshot-compression.md) |
| Bounded storage recovery | [Storage plan](operations/storage-plan-2026-09-23.md), [Storage recovery inventory](operations/storage-recovery-inventory.md), [One-night retained-file recovery](operations/storage-recovery-night.md), [Replay-cache compression](operations/replay-cache-compression.md) |
| Workstation disk or the production mirror | [Workstation disk and mirror scope](operations/workstation-disk-and-mirror-scope.md) |
| WU history layer (Toronto foundation, CYYZ recovery) | [History data design](operations/HISTORY_DATA_DESIGN.md) |

Exact market definitions, schema versions, release contents, event counts, and
artifact hashes belong to code, config, and manifests. Canonical prose explains
how to interpret and update those sources; it does not copy volatile values.

## History — preserved, never authority

| Location | What it is | Read when |
| --- | --- | --- |
| [operations/history/](operations/history/) | Text moved out of always-read files: expired dated exceptions, spent incident modes, condensed long-form wording. Each file opens with a HISTORICAL banner. | Tracing why a literal or code path exists |
| `roadmap/workstation-handoff-*`, `roadmap/agent-report-*`, `roadmap/agent-work-order-*` | The append-only decision log between hosts, with its evidence artifacts | Only when the digest, an item, or your task names a specific file. Filename dates are mission labels, not calendar dates; see [the roadmap agent guide](roadmap/AGENTS.md) |
| [Overnight briefings](operations/OVERNIGHT_BRIEFINGS.md) | Hand-written notes from unattended overnight agents | Reconstructing a specific night |
| Dated files in `operations/` (name ends in a date) | Incident and decision records | From [the operations index](operations/README.md), when touching the same subsystem |
| `research/`, `roadmap/audits/`, other dated roadmap narratives | Research and audit evidence | For the detail behind a specific finding; start audits from [the audit index](roadmap/audits/README.md) |
| [Open questions](operations/OPEN_QUESTIONS.md), [decision log](operations/DECISION_LOG.md) | What is still unanswered and who owns it; dated owner decisions | Choosing what to analyse next; tracing when a decision was made |

The correspondence is too large to read end to end, and it is not the current
state. To count it, run `git ls-files docs/roadmap`; do not copy the number into
prose. Numbered items own engineering scope, status, and evidence; the
correspondence records what was instructed, measured, accepted, or rejected, and
why. A newer unrelated mission does not supersede the task you were given.

## Two directories, similar names

`docs/operations/` holds the canonical operational contracts and runbooks.
`docs/ops/` holds the capture-day grading and guarded-merge runbook only. Check which one a link points at.

## Update this file when

Update when a canonical guide or index is added, renamed, retired, or changes
classification, or when a routing condition above stops being true. Validate with:

```powershell
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```
