# Documentation Instructions

These instructions apply under `docs/`.

## Classification

- Canonical guides describe current contracts and avoid transient metrics.
- Runbooks describe an executable operational procedure and its safety boundary.
- Generated documents identify their generator; edit the source or generator.
- Dated research, audits, incidents, and completed roadmap notes are historical
  evidence. Preserve the facts and commands that were true at the time.

Use [README.md](README.md) to decide which class a file belongs to. Do not turn
a dated audit into current guidance by silently modernizing its transcript.

## Current-state boundary

- `operations/STATE_OF_PLAY.md` is the only global current-state narrative.
  The production operations master owns its integration-line rewrite. Do not
  edit it from an ordinary feature, research, or handoff branch merely because
  that branch changes future state.
- Dated handoffs and reports are scoped mission records. Filename recency does
  not make one global instruction. Verify an apparently open mission against
  `STATE_OF_PLAY.md`, its exact branch/report pair, and any later acceptance or
  rejection before acting.
- After compaction, use summaries and memory as indexes into canonical files.
  Re-read the owner document and dynamic source before resuming a mutation.

## Writing rules

- Put each fact in one canonical file and link to it from other entry points.
- Prefer code/config/manifests for exact lists, versions, and counts.
- State `Update when` triggers on canonical documents.
- Use repository-relative links and canonical `python -m weather...` commands.
- Keep local runtime paths illustrative; never imply ignored `data/` exists in a
  clean checkout.
- Add a dated roadmap item for work status. Do not store active status in a
  free-form narrative or agent file.
- The one sanctioned narrative channel is the dated agent decision log under
  `docs/roadmap/` (`workstation-handoff-*` and `agent-report-*`). It records
  instructions, findings, and accept/reject decisions between hosts — never item
  status, counts, or scope, which stay in the owning numbered item. It is
  append-only: correct a published entry in the next one, not by editing it. See
  [the roadmap agent guide](roadmap/AGENTS.md).

Run `python -m weather.operations.agent_docs_audit` after changing canonical
documentation or agent instructions.

## Update this file when

Update when documentation categories, canonical indexes, link conventions, or
the documentation audit command changes.
