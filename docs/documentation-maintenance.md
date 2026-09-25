# Documentation Maintenance

Status: canonical maintenance policy.

- **Owns:** which file owns which knowledge, what change forces which document
  update, the automated documentation checks, the freshness policy, and the
  rules for agent files and their line budgets.
- **Read when:** you change behavior that a document describes, add or move a
  canonical document, add an agent file, or close an integration.
- **Not here:** how to write a document (see [docs/AGENTS.md](AGENTS.md)) or
  which document answers a question (see [docs/README.md](README.md)).

The readers are coding agents. The goal is broad discoverability with one source
of truth per fact. Entry points should summarize and link; they should not copy
changing inventories, metrics, versions, or operational state.

## Ownership map

| Knowledge | Canonical owner |
| --- | --- |
| What is happening now; decisions in force; answered questions | `docs/operations/STATE_OF_PLAY.md` (rewritten, never appended; the only dated canonical file) |
| Dated history of owner decisions | `docs/operations/DECISION_LOG.md` (append-only; a row in the same commit as the STATE_OF_PLAY change) |
| Unanswered research questions, the data that would answer them, owning mission | `docs/operations/OPEN_QUESTIONS.md` (ids never reused; handoffs name ids, handbacks update rows) |
| The list of audits, their status and dispositions | `docs/roadmap/audits/README.md` (a row for every audit, added in the audit's commit) |
| Product purpose, setup, dashboard, operator commands | `README.md` |
| Repository-wide agent rules and task routing | root `AGENTS.md` |
| Claude Code entry point | root `CLAUDE.md` — an `@AGENTS.md` import plus Claude-only harness notes; never a second rule set |
| Subtree-specific constraints | nearest scoped `AGENTS.md` |
| Documentation routing/classification | `docs/README.md` |
| Documentation writing rules | `docs/AGENTS.md` |
| What the research established, in short mandatory form | `docs/operations/FINDINGS_DIGEST.md` |
| Full derivations; claims that were wrong; recurring error shapes | `docs/operations/ESTABLISHED_FINDINGS.md`; `RETRACTED_AND_FALSE_LEADS.md`; `HOW_WE_GET_THINGS_WRONG.md` (reference depth behind the digest) |
| Host windows, leases, heavy-work wrappers | `docs/operations/HOST_LOAD_POLICY.md`; generated numbers in `OPERATING_REFERENCE.md` |
| Production-host agent role and authority | `docs/operations/OPERATIONS_AGENT_ROLE.md` |
| Cross-host mission rules | `docs/operations/DELEGATION_CONTRACT.md` |
| Text retired from always-read files (expired exceptions, spent incident modes) | `docs/operations/history/`, each file under a `HISTORICAL — not current authority` banner |
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

- Owner decision (a priority, an authorization, an accepted outcome, a closed
  question): rewrite `STATE_OF_PLAY.md` and update the owning numbered item in
  the same change. A decision recorded only in chat, a handoff, or a
  machine-local agent memory did not happen.
- Measured finding or a claim found wrong: add or correct the entry in
  `FINDINGS_DIGEST.md`, put the derivation in `ESTABLISHED_FINDINGS.md`, and
  move the invalidated claim to `RETRACTED_AND_FALSE_LEADS.md`. If the retired
  claim was quoted in a canonical file, fix that file and add the phrase to the
  audit's retired-claim list.
- Scheduled-task change (a task added, removed, renamed, re-timed, or paused):
  update `docs/operations/OPERATIONS_DESIGN.md` and the
  `docs/operations/README.md` index, regenerate `OPERATING_REFERENCE.md` if a
  governing constant moved, and update `scripts/ops/AGENTS.md` only if a safety
  rule changed.
- New, renamed, or retired canonical document: update `docs/README.md` (and the
  operations index for files under `docs/operations/`), search for links to any
  removed heading anchor, and add an ownership row above.
- Always-loaded file over its line budget: move detail to the owner or to
  `docs/operations/history/`; do not raise the budget to fit.
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

The knowledge audit also enforces the controls added after the 2026-09-18 audit
(constants in `src/weather/operations/agent_docs_audit.py`):

| Control | What it stops | How to change it |
| --- | --- | --- |
| `LINE_BUDGETS`, `NESTED_AGENT_FILE_LINE_BUDGET` | Always-loaded files growing by accretion; every agent pays for them on every task | Move detail to its owner file and link. Raise a budget only as a reviewed decision, with a comment saying why |
| `unindexed_operations_docs` | A document nobody can find: every `docs/operations/*.md` must be linked from the operations index or `docs/README.md` | Add the index row, with its true status, in the same change that adds the file |
| `RETIRED_CLAIMS` | A retracted claim surviving in another canonical file, where an agent reads it first and acts on it | **When you retract a claim, add its phrase to `RETIRED_CLAIMS` in the same change** |
| `CLAUDE.md` must import `@AGENTS.md` | Two harnesses starting from two different entry points | Do not fork the entry point; add harness notes only |
| `--max-state-age-days N` (off by default, so CI stays deterministic) | `STATE_OF_PLAY.md` going stale while nothing merges | `status.ps1` raises the same flag every morning at 3 days; rewrite or re-attest the file |

Freshness has three triggers, and only the first used to exist. **Event:** a
change updates its owner document in the same commit (the table above and the
change triggers). **Integration:** the documentation transaction below.
**Age:** `status.ps1` flags `STATE_OF_PLAY.md` by its declared date, because the
other two triggers stall exactly when the project does (2026-09-13..19: six days
frozen through a disk emergency and a settlement hole).

Automation cannot prove prose truth. The periodic review that can is a
**verify-against-code pass**, run by partition so no agent needs the whole tree:
for each runbook, extract every command, flag, path, task name, threshold and
step order, and check each against the script `param()` block, argparse
definition, registrar or constant it names; fix or delete what does not match.
The 2026-09-19 pass found, among others, three documented commands that could
not run because mandatory flags were missing. Do this after any broad change,
and whenever a runbook is about to be relied on for a stateful operation. Sample
scoped `AGENTS.md` files for redundant or contradictory rules at the same time.

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
  `Last updated` dates. The one exception is `STATE_OF_PLAY.md`: its
  `**Last updated: YYYY-MM-DD` line is machine-read by `status.ps1` and the
  knowledge audit, so keep that exact form and make it true.
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
its parent. Open with its scope, link to the canonical contract instead of
pasting it, include focused checks, and end with `## Update this file when`.
Remove or merge it if it becomes a copy of parent guidance. Never put status,
dates, counts, or a one-time incident procedure in an agent file; when an
incident mode is spent, move its text to `docs/operations/history/` and leave a
one-line pointer.

Agent files and mandatory pre-reads are paid for in context on every task, so
they carry line budgets. The documentation audit enforces them; the constants in
`src/weather/operations/agent_docs_audit.py` (`LINE_BUDGETS`,
`NESTED_AGENT_FILE_LINE_BUDGET`) are authoritative if this table drifts.

| Always-loaded file | Budget (physical lines) |
| --- | --- |
| `docs/operations/STATE_OF_PLAY.md` | about 90 |
| root `AGENTS.md` | 170 |
| root `CLAUDE.md` | 25 |
| each nested `AGENTS.md` | 130, unless the audit lists an explicit entry for it |
| `docs/operations/FINDINGS_DIGEST.md` | 250 |

`CLAUDE.md` must keep the `@AGENTS.md` import so Claude Code and Codex sessions
start from the same entry point. Machine-local agent memory and settings are
private aids and never project truth.

## Update this file when

Update when knowledge ownership, change triggers, automated checks,
classification, or scoped-agent policy changes.
