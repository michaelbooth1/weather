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
| System boundaries and data flow | [Architecture](architecture.md) | Canonical guide |
| Development and verification | [Development](development.md) | Canonical guide |
| Git branches, worktrees, commits, and pull requests | [Git workflow SOP](git-workflow.md) | Canonical runbook |
| Documentation ownership and drift prevention | [Documentation maintenance](documentation-maintenance.md) | Canonical guide |
| End-to-end project operation | [Project operating SOP](operations/PROJECT_OPERATING_SOP.md) | Canonical runbook |
| Current active work | [Active backlog](roadmap/active-backlog.md) | Generated current view |
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

## Roadmap and historical material

`roadmap/active-backlog.md` is generated from numbered item files and is the
fastest current-work view. `roadmap/ROADMAP.md` is the full taxonomy/index.
Dated audits, research reports, incident notes, completed item transcripts, and
older narratives are immutable evidence, not operator instructions.

## Update this file when

Update when a canonical guide or index is added, renamed, retired, or changes
classification. Validate changes with:

```powershell
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```
