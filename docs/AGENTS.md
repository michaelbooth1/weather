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

## Writing rules

- Put each fact in one canonical file and link to it from other entry points.
- Prefer code/config/manifests for exact lists, versions, and counts.
- State `Update when` triggers on canonical documents.
- Use repository-relative links and canonical `python -m weather...` commands.
- Keep local runtime paths illustrative; never imply ignored `data/` exists in a
  clean checkout.
- Add a dated roadmap item for work status. Do not store active status in a
  free-form narrative or agent file.

Run `python -m weather.operations.agent_docs_audit` after changing canonical
documentation or agent instructions.

## Update this file when

Update when documentation categories, canonical indexes, link conventions, or
the documentation audit command changes.
