# Roadmap Agent Guide

These instructions apply to `docs/roadmap/`.

## Sources Of Truth

- `work/W-####.yaml` owns mission status, owner, dependencies, landing slots and
  owner requests; [work registry](work/README.md) owns its CLI and checks. Only
  production regenerates `work-board.md` in its docs step. Workstations update
  their records and link handbacks; a handback is not verification.
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
research agent. They preserve direction and results for their specific missions.

| Pattern | Direction | Meaning |
| --- | --- | --- |
| `workstation-handoff-<date><letter>-<slug>.md` | production host → workstation | the mission: what to do, constraints, guardrails, required handback |
| `agent-report-<id>-<slug>.md` | workstation → production host | the result: findings, evidence hashes, verdict; reuse the handoff id |
| `agent-work-order-<date><letter>.md` | operations agent → coding agent | an older single-host work order; historical |

Do not read this log to learn the current state. Its distilled conclusions are in
[the findings digest](../operations/FINDINGS_DIGEST.md); open a dated file only
when the digest, a numbered item, or the user's task names it. Adjacent
`.json`/`.csv`/`.sha256` files are the evidence artifacts a report cites.

[Correspondence index](correspondence-index.md) is generated from filenames,
H1 titles, citations and Git-added dates, one shard per Git-added month under
`correspondence-index/`; the root lists the months only, and regeneration
rewrites only shards whose rows changed. Reports reuse the exact handoff id;
legacy collisions are listed as multiple possible answers, not inferred matches.
Name new audits `<scope>-audit-<date>.md` and add their row to
[the audit index](audits/README.md) in the same commit.

Reading rules:

- **The `<date>` in a filename is a mission label, not a calendar date.** Handoff
  and report names run as a sequence and can be weeks ahead of, or collide with,
  the real date. Never sort, filter, or infer recency from filenames; use
  `git log --diff-filter=A --format=%ad -- <path>` for when a file was written.
- **September 2026 ids exist twice.** The unmerged workstation research lineage (branched at `c932b54f8`,
  run 09-01..09-11) used `79a`..`90a` and `100a`..`100i`; production reused those numbers from 09-21. Write a
  lineage id as `research 2026-09-88a` with branch and commit; a bare id means the production mission. Never
  merge the lineage's `item-330-model-bom-…` file (collides with master's item 330).
- **Bind a handoff to the user's task, assigned host/role, and scope.** Read the
  handoff named by that task and any explicit corrections or successors for the
  same mission. A newer unrelated handoff does not replace or expand the task.
  Current user instructions and canonical safety contracts remain authoritative.
- Check supersession within that mission by commit order, not filename date or
  the `<letter>` suffix. Use
  `git log --diff-filter=A -- <relevant-handoff-paths>` for bounded history;
  recency alone does not grant authority.
- A handoff and its answering report form a pair; read both before concluding
  what was decided. A report is evidence, not self-acceptance; look for the
  operator's decision or an explicit acceptance/rejection for the same mission.
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
  `OPEN`, `PARTIAL`, or `COMPLETE` with an optional dated disposition, or
  `DORMANT YYYY-MM-DD - reason` (date and reason required). A dormant item is
  parked, not closed: revive it by restoring `OPEN`/`PARTIAL` with a fresh dated
  disposition. `active-backlog.md` lists dormant items apart from active ones
  and flags an active item whose disposition is more than 45 days older than the
  newest disposition date in the roadmap; refresh it or mark it dormant.
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
.\venv\Scripts\python.exe -m pytest tests/reporting/test_worktrack.py -q
```

After adding correspondence, commit the source file, then regenerate its index
so the Git-added date is available (include both commits in the handback):

```powershell
.\venv\Scripts\python.exe -m weather.reporting.roadmap.correspondence_index
.\venv\Scripts\python.exe -m weather.reporting.roadmap.correspondence_index --check
```

`agent_docs_audit` includes both generators' read-only parity checks, audit-row
coverage, digest EF references, question ids/answer pointers and owner-decision
dates. Full Git history is required for correspondence parity; a shallow clone
fails explicitly. Workstation tests and the audit CLI test run through the
heavy wrapper described in [development](../development.md).

## Update this file when

Update when roadmap sources of truth, item metadata, generation, indexing, or
focused verification rules change.
