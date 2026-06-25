# 175. Roadmap Backlog Normalization And Historical Noise Reduction [COMPLETE 2026-06-21 - ACTIVE BACKLOG PARSER AND LINT LIVE]

Goal: make the roadmap easy to query for active work without losing historical
audit context.

Source: the 2026-06-20 full repository cleanup audit. The roadmap now has more
than 170 item files, many completed historical entries, mixed status wording,
and legacy command references that are useful as history but noisy for active
documentation searches.

Why this matters: the roadmap is now a source of operational truth. If active
OPEN and PARTIAL work is hard to distinguish from completed history, agents and
operators will keep rediscovering old context instead of executing the current
backlog.

## Design

1. Normalize numbered item headings so tooling can parse item number, title,
   status, completion date, and disposition consistently.
2. Generate a compact active backlog index from item files rather than editing
   a giant manual table for every status question.
3. Separate active instructions from historical transcripts and legacy command
   examples.
4. Keep completed historical items available but remove them from the default
   operator scan path.
5. Add a check that new roadmap items include goal, source, why, checklist, and
   acceptance sections.

- [x] Build or update a roadmap parser that extracts OPEN, PARTIAL, COMPLETE,
  date, and disposition from item headings.
- [x] Generate an active backlog summary containing only OPEN and PARTIAL
  items.
- [x] Normalize item headings that currently require manual interpretation.
- [x] Move historical command examples out of active instructions or mark them
  as historical-only.
- [x] Add a docs lint check for required roadmap item sections.
- [x] Document how agents should add new items without creating numbering or
  status drift.

Acceptance: active roadmap work can be listed automatically, historical audit
content remains searchable but clearly separated, and new item files follow one
consistent actionable format.

## 2026-06-21 implementation update

Added `weather.reporting.roadmap.roadmap_backlog`, schema `roadmap_backlog_v0.1`.
The parser reads numbered item headings, extracts item number, title, status,
optional date, and disposition, and writes:

- `data/backtest/roadmap_backlog.json`
- `docs/roadmap/active-backlog.md`

`active-backlog.md` is now the default operator scan path for `OPEN` and
`PARTIAL` work; completed historical items remain in `docs/roadmap/items/` but
are omitted from that compact active report. The linter fails active items that
do not expose `Goal:`, `Source:`, `Why this matters`, at least one checklist
row, and `Acceptance:`. Active legacy partials 32, 35, 48, and 67 were
normalized with missing Source/Why sections so the real roadmap now passes the
lint.

The roadmap index now links the generated active backlog and documents the
regeneration command:
`python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`.
It also states that historical implementation updates and command transcripts
inside completed or dated sections are historical-only evidence, not current
operator instructions.

Verification:

- `python -m weather.reporting.roadmap.roadmap_backlog --json-out data\backtest\roadmap_backlog.json --report-out docs\roadmap\active-backlog.md --fail-on-lint`
- `python -m pytest tests\reporting\test_roadmap_backlog.py tests\operations\test_schema_registry.py -q`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - ACTIVE BACKLOG PARSER AND LINT LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

