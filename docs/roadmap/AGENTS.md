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

## Agent Correspondence (the dated decision log)

Most files directly under `docs/roadmap/` are not item files. They are the
append-only decision log between the production-host agent and the workstation
research agent, and they are where recent direction actually lives.

| Pattern | Direction | Meaning |
| --- | --- | --- |
| `workstation-handoff-<date><letter>-<slug>.md` | production host → workstation | the mission: what to do, constraints, guardrails, required handback |
| `agent-report-<date>-workstation-<slug>.md` | workstation → production host | the result: findings, evidence hashes, verdict |

Reading rules:

- **The newest `workstation-handoff-*` is live instruction.** Every older one is
  historical evidence. Everything in `agent-report-*` is historical evidence.
- **Sort by commit order, not by filename date.** A handoff is named for the
  mission's nominal day, which can run ahead of the day it was written. Use
  `git log --diff-filter=A -- docs/roadmap/` to get true order.
- The `<letter>` suffix (`a`, `b`, `c`) orders multiple missions within one day.
- A handoff and its answering report form a pair; read both before concluding
  what was decided. Acceptance or rejection is stated in the *next* handoff, not
  in the report.
- **Never edit a published handoff or report.** They are the record of what was
  actually instructed and measured. Corrections go in the next one, stated
  explicitly as a correction.

This log answers "why are we doing this?"; the numbered items answer "what is
the scope and status of work item N?". Both are canonical for their own
question. Do not copy item status into correspondence, and do not treat a
superseded handoff as current instruction.

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

When no roadmap change is intended, verify that the committed generated view
still matches its sources without rewriting it:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
```

Run the focused tests:

```powershell
.\venv\Scripts\python.exe -m pytest tests/reporting/test_roadmap_backlog.py -q
```

## Update this file when

Update when roadmap sources of truth, item metadata, generation, indexing, or
focused verification rules change.
