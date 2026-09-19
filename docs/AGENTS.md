# Documentation Instructions

Scope: `docs/`. The readers are coding agents. Write so an agent learns in the
first ten lines what a file owns, when to read it, and what to read instead.
[documentation-maintenance.md](documentation-maintenance.md) owns the ownership
map, change triggers, and checks; this file owns only the writing rules.

## Classification

- Canonical guides describe current contracts and avoid transient metrics.
- Runbooks describe an executable operational procedure and its safety boundary.
- Generated documents identify their generator; edit the source or generator.
- `operations/STATE_OF_PLAY.md` is the only document that describes today. It is
  rewritten, never appended, and is the only place a `Last updated` date belongs.
- `operations/history/` holds text moved out of always-read files: expired dated
  exceptions, spent incident modes, condensed long-form wording. Every file there
  opens with a `HISTORICAL — not current authority` banner.
- Dated research, audits, incidents, completed roadmap notes, and the
  correspondence under `roadmap/` are historical evidence. Preserve the facts and
  commands that were true at the time.

Use [README.md](README.md) to decide which class a file belongs to. Do not turn
a dated audit into current guidance by silently modernizing its transcript.

## Writing rules

- Put each fact in one canonical file and link to it from other entry points.
  Never paste another file's contract; write one sentence and link to the owner.
- Open a canonical document with its status, what it owns, and a `Read when`
  condition. Prefer conditions to unconditional "read this".
- Prefer code/config/manifests for exact lists, versions, and counts. Give the
  command or path that yields the current value instead of copying it.
- Every command, flag, path, task name, and threshold must exist. Check the
  script `param()` block, argparse, or constant before writing it down.
- State `Update when` triggers on canonical documents.
- Use repository-relative links and canonical `python -m weather...` commands.
  Before renaming or removing a heading, search for links to its anchor.
- Keep local runtime paths illustrative; never imply ignored `data/` exists in a
  clean checkout.
- Always-loaded files (`AGENTS.md`, `CLAUDE.md`, `STATE_OF_PLAY.md`, the findings
  digest) have line budgets enforced by the documentation audit. When one is
  full, move detail to its owner or to `operations/history/`; do not raise the
  budget to fit.
- Add a dated roadmap item for work status. Do not store active status in a
  free-form narrative or agent file.
- The one sanctioned narrative channel is the dated agent decision log under
  `docs/roadmap/` (`workstation-handoff-*` and `agent-report-*`). It records
  instructions, findings, and accept/reject decisions between hosts — never item
  status, counts, or scope, which stay in the owning numbered item. It is
  append-only: correct a published entry in the next one, not by editing it. See
  [the roadmap agent guide](roadmap/AGENTS.md).

Run `python -m weather.operations.agent_docs_audit` after changing canonical
documentation or agent instructions. It is offline and deterministic; the host
load policy still decides when Python may run on the capture host.

## Update this file when

Update when documentation categories, canonical indexes, link conventions, or
the documentation audit command changes.
