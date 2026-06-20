# 175. Roadmap Backlog Normalization And Historical Noise Reduction [OPEN]

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

- [ ] Build or update a roadmap parser that extracts OPEN, PARTIAL, COMPLETE,
  date, and disposition from item headings.
- [ ] Generate an active backlog summary containing only OPEN and PARTIAL
  items.
- [ ] Normalize item headings that currently require manual interpretation.
- [ ] Move historical command examples out of active instructions or mark them
  as historical-only.
- [ ] Add a docs lint check for required roadmap item sections.
- [ ] Document how agents should add new items without creating numbering or
  status drift.

Acceptance: active roadmap work can be listed automatically, historical audit
content remains searchable but clearly separated, and new item files follow one
consistent actionable format.

