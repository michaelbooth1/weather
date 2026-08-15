# Documentation Maintenance

Status: canonical maintenance policy.

The goal is broad discoverability with one source of truth per fact. Entry
points should summarize and link; they should not copy changing inventories,
metrics, versions, or operational state.

## Ownership map

| Knowledge | Canonical owner |
| --- | --- |
| Product purpose, setup, dashboard, operator commands | `README.md` |
| Repository-wide agent rules | root `AGENTS.md` |
| Subtree-specific constraints | nearest scoped `AGENTS.md` |
| Documentation routing/classification | `docs/README.md` |
| Global current critical path and closed decisions | `docs/operations/STATE_OF_PLAY.md` |
| Production-host role, authority, and safety | `docs/operations/OPERATIONS_AGENT_ROLE.md` |
| Durable domain invariants | `docs/operations/AGENT_CONTEXT.md` |
| Architecture/data flow | `docs/architecture.md` |
| Package edges and facade ownership | operations boundary/ownership docs |
| Git branches, worktrees, staging, commits, and pull requests | `docs/git-workflow.md` |
| Config classifications/freshness | `docs/operations/config-inventory.md` plus config/code |
| Operational topology and procedures | `docs/operations/README.md` and linked runbooks |
| Current work | generated roadmap active backlog |
| Item status/scope/evidence | numbered roadmap item file |
| Exact versions, counts, hashes, and active state | code, config, manifests, generated reports |

## LLM and compaction design

- Put the answer or governing rule in the first screenful; background and
  rationale follow. An agent should not need the bottom half of a long file to
  discover that its premise is obsolete.
- One document owns one question. Routers summarize and link; they do not copy
  branches, commit IDs, schedules, metrics, or current dispositions.
- Conversation summaries, auto-memory, and dated correspondence are indexes,
  not authority. After compaction, agents re-read `STATE_OF_PLAY.md` and the
  action's canonical owner, then verify dynamic state at its source.
- `STATE_OF_PLAY.md` is integration-linear. The production operations master
  rewrites it after an accepted decision, mission, merge, or runtime adoption.
  Ordinary topic branches do not carry speculative future-state edits. If a
  branch proposes text, it is not current until the integration owner rewrites
  it against the actual result.
- Keep durable roles and contracts free of historical snapshots and open-work
  lists. Move dated evidence to a dated record and link it only when it explains
  a current rule.
- Use explicit precedence language when two sources can disagree. Avoid phrases
  such as "newest is current" unless a machine-verifiable lifecycle makes that
  statement true.

## Change triggers

- Market or location contract: update the registry/config owner and linked
  product/config guidance; regenerate validated inventories.
- CLI, flag, output path, or entry point: update the owning runbook/README and
  canonical-command checks.
- Package edge or facade split: update package boundaries, module ownership, and
  architecture ratchets.
- Config file or freshness rule: update config inventory and the knowledge
  audit expectation.
- Schema or tape change: update schema registry, producer/consumer tests, replay
  compatibility, and any storage contract.
- Scheduled task or loop topology: update operations design/index and script
  guidance. Script parameter blocks remain authoritative for required inputs.
- Artifact or release lifecycle: update artifact/release runbooks and gates.
- New work or changed status: update the numbered item and regenerate the
  active backlog; do not put project status in `AGENTS.md`.
- Operator decision, accepted handback, merge, or runtime adoption that changes
  the critical path: have the production operations master rewrite
  `STATE_OF_PLAY.md` on the integration line and remove superseded state.

## Automated checks

Run:

```powershell
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --json-out data\backtest\roadmap_backlog_check.json --report-out data\backtest\roadmap_backlog_check.md
```

The knowledge audit validates required entry points, local links, scoped agent
update triggers, the README market table, checked-in config coverage, dependency
parity, and canonical command hygiene. The roadmap command validates numbered
item/index ownership. The explicit local output paths above make it a
non-tracked check. After an intentional roadmap change, omit `--report-out` to
regenerate the canonical tracked `docs/roadmap/active-backlog.md`, then review
its diff.

Automation cannot prove prose truth. During broad changes and periodically,
review canonical documents against code/config, look for copied dates and
metrics, confirm that runbooks match CLI help/script parameters, and sample
scoped `AGENTS.md` files for redundant or contradictory rules.

## Freshness policy

- Canonical documents use `Update when` triggers instead of ceremonial
  `Last updated` dates.
- Generated documents include generator metadata and should be reproduced, not
  hand-edited.
- Dated documents retain historical facts and commands. Add a visible historical
  banner when their placement could make them look current.
- Dynamic reports stay under ignored `data/` unless explicitly promoted as a
  reviewed historical record.
- Local machine settings and agent permission files are never project truth.

## Adding an agent file

Add a scoped `AGENTS.md` only when the subtree has constraints that differ from
its parent. Keep it short, link to the canonical contract, include focused
checks, and end with `## Update this file when`. Remove or merge it if it becomes
a copy of parent guidance.

## Update this file when

Update when knowledge ownership, change triggers, automated checks,
classification, or scoped-agent policy changes.
