# Roadmap Agent Guide

These instructions apply to `docs/roadmap/`.

## Sources Of Truth

- `active-backlog.md` is the generated view of current `OPEN` and `PARTIAL`
  work. Use it to decide what is active now.
- Each file under `items/` is authoritative for that item's title, status,
  scope, acceptance criteria, and evidence.
- `ROADMAP.md` is the complete taxonomy and item index. It is not the default
  current-work view.
- Dated audits, `overview.md`, `actionable-work-order.md`, and `sequencing.md`
  are historical context. Do not treat their commands, metrics, or priority
  lists as current instructions without verifying them against active sources.

## Editing Rules

- Update the owning numbered item instead of copying item state into a new
  narrative file.
- Keep item headings in the form `# N. Title [STATUS]`, where status is
  `OPEN`, `PARTIAL`, or `COMPLETE` with an optional dated disposition.
- Preserve historical command transcripts. Current commands must use the
  canonical `python -m weather...` package surface.
- When adding or moving an item, update its primary row in `ROADMAP.md` in the
  same change.
- Do not hand-edit generated counts or rows in `active-backlog.md`.

## Verification

After changing roadmap items or the index, regenerate and lint the backlog:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
```

Run the focused tests:

```powershell
.\venv\Scripts\python.exe -m pytest tests/reporting/test_roadmap_backlog.py -q
```

## Update this file when

Update when roadmap sources of truth, item metadata, generation, indexing, or
focused verification rules change.
