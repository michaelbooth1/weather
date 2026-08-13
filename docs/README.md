# Documentation Map

This index is the canonical router for repository knowledge. Read only the
documents relevant to the task; the repository contains a large historical
record that is valuable evidence but not current instruction.

## Start by task

| Need | Canonical source | Class |
| --- | --- | --- |
| Product purpose, setup, dashboard, command catalog | [Root README](../README.md) | Canonical guide |
| Agent rules and task routing | [Root AGENTS.md](../AGENTS.md) | Canonical guide |
| Durable domain constraints | [Agent context](operations/AGENT_CONTEXT.md) | Canonical guide |
| **What we have measured about the model** | [Established findings](operations/ESTABLISHED_FINDINGS.md) | Canonical distillation |
| **Claims that were wrong, and traps that look true** | [Retracted claims and false leads](operations/RETRACTED_AND_FALSE_LEADS.md) | Canonical distillation |
| **Running or receiving a cross-host mission** | [Delegation contract](operations/DELEGATION_CONTRACT.md) | Canonical contract |
| System boundaries and data flow | [Architecture](architecture.md) | Canonical guide |
| Development and verification | [Development](development.md) | Canonical guide |
| Git branches, worktrees, commits, and pull requests | [Git workflow SOP](git-workflow.md) | Canonical runbook |
| Documentation ownership and drift prevention | [Documentation maintenance](documentation-maintenance.md) | Canonical guide |
| End-to-end project operation | [Project operating SOP](operations/PROJECT_OPERATING_SOP.md) | Canonical runbook |
| Bounded International market-making live test | [International MM live pilot](operations/INTERNATIONAL_MM_LIVE_PILOT.md) | Canonical runbook |
| **Capture streak, quiet-window merges, host safety** | [Code-soak streak runbook](ops/streak-soak.md) | Canonical runbook |
| Building the first immutable release | [Release #1 build runbook](operations/RELEASE_ONE_BUILD_RUNBOOK.md) | Canonical runbook |
| Current active work | [Active backlog](roadmap/active-backlog.md) | Generated current view |
| Agent decision log and cross-host correspondence | `roadmap/workstation-handoff-*.md`, `roadmap/agent-report-*.md` | Dated evidence; newest is current |
| Roadmap item scope/status/evidence | `roadmap/items/item-*.md` | Canonical per item |
| Operations and runbooks | [Operations index](operations/README.md) | Canonical index |
| Research findings | `research/` and dated roadmap audits | Historical evidence unless labeled otherwise |

## Durable technical contracts

- [Package dependency boundaries](operations/package-boundaries.md)
- [Large-module ownership map](operations/module-ownership-map.md)
- [Repository path policy](operations/path-policy.md)
- [Configuration inventory](operations/config-inventory.md)
- [Data storage classes](operations/data-storage-class-contract.md)
- [Data retention policy](operations/data-retention-policy.md)
- [Artifact storage policy](operations/artifact-storage-policy.md)
- [Closed market-day archive contract](operations/closed-market-day-parquet-archive-contract.md)

Exact market definitions, schema versions, release contents, event counts, and
artifact hashes belong to code, config, and manifests. Canonical prose explains
how to interpret and update those sources; it should not copy volatile values.

## Two directories, similar names

`docs/operations/` holds the canonical operational contracts and runbooks.
`docs/ops/` holds the host/streak runbook only. They are different directories;
check which one a link points at.

## Roadmap and historical material

`roadmap/active-backlog.md` is generated from numbered item files and is the
fastest current-work view. `roadmap/ROADMAP.md` is the full taxonomy/index.
Dated audits, research reports, incident notes, completed item transcripts, and
older narratives are immutable evidence, not operator instructions.

**The correspondence is too large to read.** It is ~600 files and grows daily.
[Established findings](operations/ESTABLISHED_FINDINGS.md) and
[retracted claims and false leads](operations/RETRACTED_AND_FALSE_LEADS.md) are the distilled state of
what it established — read those first, and go to the dated files only for the detail behind a
specific finding.

**Two records coexist, and they answer different questions.** Numbered items
under `roadmap/items/` own engineering scope, status, acceptance criteria, and
evidence. The dated `workstation-handoff-*` / `agent-report-*` pair is the
append-only decision log of the production-host and workstation agent loop: what
was instructed, what was measured, what was accepted or rejected, and why. Recent
research direction lives almost entirely in that correspondence, so an agent
asking "why are we doing this?" should read the newest handoff, not only the
backlog. See [the roadmap agent guide](roadmap/AGENTS.md) for the convention.

## Update this file when

Update when a canonical guide or index is added, renamed, retired, or changes
classification. Validate changes with:

```powershell
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```
