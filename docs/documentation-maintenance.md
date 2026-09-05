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
| Durable domain invariants | `docs/operations/AGENT_CONTEXT.md` |
| Architecture/data flow | `docs/architecture.md` |
| Package edges and facade ownership | operations boundary/ownership docs |
| Git branches, worktrees, staging, commits, and pull requests | `docs/git-workflow.md` |
| Config classifications/freshness | `docs/operations/config-inventory.md` plus config/code |
| Operational topology and procedures | `docs/operations/README.md` and linked runbooks |
| Current work | generated roadmap active backlog |
| Item status/scope/evidence | numbered roadmap item file |
| Exact versions, counts, hashes, and active state | code, config, manifests, generated reports |

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

## Integration documentation transaction

A staged branch may carry the documentation for its proposed behavior, but
those bytes are not production truth until the exact branch is integrated.
After a successful guarded integration, finish one documentation transaction
before starting unrelated work:

1. Review `docs/operations/STATE_OF_PLAY.md` against the integrated Git ancestry,
   durable suite/merge receipts, live worker evidence, and current blockers.
   Rewrite changed facts and remove superseded claims; never describe the next
   hoped-for state. If every fact remains accurate, record that review below.
2. Update every numbered roadmap item whose acceptance or next evidence
   changed, then regenerate `docs/roadmap/active-backlog.md`.
3. Update `ESTABLISHED_FINDINGS.md` only for reproduced measurements and move
   invalidated claims to `RETRACTED_AND_FALSE_LEADS.md`. Strategy ordering must
   match the operator's current decision, not an older research programme.
4. Reconcile changed task names, wrappers, receipt schemas, CLI surfaces, and
   evidence boundaries with their owning runbooks and operations design.
5. Run the roadmap lint, focused documentation tests, `git diff --check`, and
   `weather.operations.agent_docs_audit`; commit and publish any required
   documentation changes through the approved push path. Do not create a
   ceremonial diff or empty commit for documents that remain accurate.

The guarded merge records each exact merge commit in
`data/alerts/documentation_transaction_pending.json` before publication.
Multiple commits in one reviewed overnight stack accumulate under one pending
hash. `status.ps1` warns until the local 09:00 deadline and flags after it; a
Task Scheduler result cannot clear the debt.

After any required documentation commit is published and local `master` equals
`origin/master`, prepare an ignored completion manifest with schema
`documentation_transaction_completion_manifest_v0.1`. It must bind the current
pending SHA-256, list the pending integration tips in order, identify the exact
documentation tip, list all canonical documents reviewed, cite at least one
durable evidence path, and summarize the reconciliation. For either
`STATE_OF_PLAY.md` or `active-backlog.md` with no diff after the final pending
integration, include a `documents_unchanged` object keyed by its repository path.
Each entry must contain exactly `blob_oid` (the full committed Git blob SHA at
the documentation tip) and `reason` (why the document remains accurate for these
integrations). Obtain the blob with `git rev-parse <documentation-tip>:<path>`.
The same form may record other reviewed unchanged documents. A changed document
must not be claimed unchanged. The documentation tip may equal the final
integration tip when no follow-up changes are needed. Complete it with:

```powershell
.\venv\Scripts\python.exe -m weather.operations.documentation_transaction `
    --repo-root . complete --manifest data\alerts\documentation-completion.json
```

The command independently verifies Git ancestry and HEAD/local-master/cached-
origin equality, requires an update or a bound unchanged review for each of
`STATE_OF_PLAY.md` and `active-backlog.md`, and rejects missing committed files,
stale blob reviews, and unpublished worktree or index edits to required reviewed
documents. It
runs generated-backlog parity, agent-docs audit, focused docs tests, and
`git diff --check`, then writes an immutable hash-bound receipt containing the
unchanged reviews. These reviews attest prose truth; byte checks cannot establish
that a factual claim is accurate. Required factual updates and the existing
evidence and verification gates remain mandatory.
The pending file is retained; only a matching PASS receipt makes it complete.

If integration fails, do not pre-write the successful state. Preserve the
failed receipts, leave future behavior on its branch, and report the current
blocker through dynamic status and the bounded recovery handoff. A later
morning closeout owns the transaction once the integration is real.

Treat each actual merge independently. A later member of a planned stack
failing does not erase an earlier successful merge and must not leave that
earlier merge undocumented. Close the pending transaction against the commits
that really entered production, describe the later refusal as the current
blocker, and never claim the refused code landed.

## Freshness policy

- Canonical documents use `Update when` triggers instead of ceremonial
  `Last updated` dates.
- Generated documents include generator metadata and should be reproduced, not
  hand-edited.
- Dynamic host inventories belong under ignored `data/`; a tracked generated
  document must depend only on repository-owned inputs.
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
