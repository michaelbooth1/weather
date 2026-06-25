# 204. Roadmap Index Ownership Lint And Duplicate Membership [COMPLETE 2026-06-21 - INDEX LINT GATE LIVE]

Goal: make `docs/roadmap/ROADMAP.md` auditable against the numbered item files
so item status, title, and track membership cannot drift from the canonical
item headings.

Source: the closed-item audit found that item 175 added an item-file parser and
active backlog generator, but the giant manual roadmap index is still outside
that lint surface. The current `ROADMAP.md` table lists items 185-191 twice,
once under Track A and again under Track B, while the generated active backlog
does not detect or explain that duplicate membership.

Why this matters: the active backlog is now the default operator scan path, but
the roadmap index is still the human entry point. If an item appears in two
sections or its table status drifts from the item heading, agents can update the
wrong section, miss the primary owner, or double-count active work.

## Design

1. Extend `weather.reporting.roadmap.roadmap_backlog` or add a companion linter that
   parses `ROADMAP.md` table rows and joins them to item files.
2. Require each numbered item to have exactly one primary index row, unless a
   deliberate cross-track reference is represented in a separate non-primary
   cross-link section.
3. Check table title and status text against the canonical item heading.
4. Report missing index rows, duplicate index rows, stale title/status rows,
   and orphan table links.
5. Add tests using duplicate rows like the current item 185-191 pattern.

- [x] Add roadmap-index parsing and duplicate-membership detection.
- [x] Decide whether cross-track references are allowed and encode them
  separately from primary ownership rows.
- [x] Fail lint when table status/title text drifts from the item file heading.
- [x] Normalize the current item 185-191 duplicate rows.
- [x] Add tests and document the index lint command.

Acceptance: `ROADMAP.md` and `docs/roadmap/items/*.md` agree on item number,
title, status, and exactly one primary section per item; duplicate primary rows
fail lint before they reach the active backlog.

Completion note 2026-06-21: `weather.reporting.roadmap.roadmap_backlog` now parses
`ROADMAP.md` table rows and joins them to canonical numbered item files. The
lint fails orphan links, row-number/link mismatches, title drift, status drift,
missing primary rows, duplicate primary rows, duplicate item numbers, and
malformed row labels. Cross-track references are allowed only in headings named
as cross-link/reference sections, where rows are validated but do not count as
primary ownership. The duplicate primary rows for items 185-191 were normalized
to Track A ownership, and stale visible index text for items 164 and 186-189 was
made canonical.

Verification:
`python -m pytest tests\reporting\test_roadmap_backlog.py -q` passed with
`7 passed`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - INDEX LINT GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

