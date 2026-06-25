# 207. Root-Cause Active Owner Recurrence Routing [COMPLETE 2026-06-21 - ACTIVE OWNER RECURRENCE ROUTING LIVE]

Goal: make settled-day root-cause reports distinguish historical closure
evidence from post-closure recurrence, and require actionable issue codes to
route to an active owner or proposed new roadmap item.

Source: item 198 completed the canonical settled-day root-cause report. The
latest June 20 root-cause JSON maps issue codes such as
`MODEL_TOP_WARM_SIDE_MISS`, `WU_CURRENT_MAX_ANOMALY`,
`STARTUP_LIVE_OBSERVATION_IMPLAUSIBLE`, and `TAKER_BOUGHT_WARM_TAIL` only to
completed items 192-198. That is useful as closure evidence for the June 20
audit, but the report has no guard that would catch the same issue recurring
after the item's completion date.

Why this matters: a current issue mapped only to `COMPLETE` items looks owned,
but it is absent from the active backlog. That can hide regressions, especially
when root-cause reporting is supposed to propose a new item candidate for every
actionable flaw without an active owner.

## Design

1. Join root-cause roadmap mappings to parsed roadmap item status and completion
   date.
2. Label issue evidence as historical closure evidence when it predates or
   belongs to the closure audit that created the completed item.
3. Flag post-closure recurrence when the issue date is after every mapped
   item's completion date and no mapped item is `OPEN` or `PARTIAL`.
4. Emit a suggested new roadmap item title for every recurrence with no active
   owner.
5. Correct broad issue routing, including generic model weak-slot evidence, so
   it points to model-performance owners rather than only the taker cutover
   item.

- [x] Add active-owner status and completion-date checks to root-cause mappings.
- [x] Add a recurrence classification for issue evidence after item closure.
- [x] Emit suggested new item candidates when no active owner exists.
- [x] Revisit the `MODEL_WEAK_HOUR_SLOT` owner mapping.
- [x] Add tests proving current issues cannot silently map only to `COMPLETE`
  items.

Acceptance: a root-cause report can intentionally cite completed items as
historical closure evidence, but any post-closure actionable recurrence either
maps to an active item or produces a new roadmap-item candidate.

Completion note 2026-06-21: settled-day root-cause roadmap mappings now join
issue codes to parsed roadmap item status/date metadata. Each mapping is
classified as `active_owner`, `historical_closure_evidence`,
`post_closure_recurrence`, `unmapped_no_owner`, `missing_mapped_item`, or
`complete_owner_unverified_date`. Complete-only issues after every mapped
completion date emit a suggested new roadmap item title; current June 20 closure
evidence remains historical. `MODEL_WEAK_HOUR_SLOT` now routes to active model
owners 160 and 177 plus completed watchlist item 168 instead of the taker
cutover item, and `MM_PREFLIGHT_STALE_BOOKS` routes to active items 210, 161,
and 157 instead of the report module.

Generated June 20 evidence now has roadmap mapping classifications:
`active_owner=2` and `historical_closure_evidence=7`, with no suggested new item
candidate for the closure audit. The issue CSV includes
`roadmap_classification`, `active_owner_items`, and `suggested_new_item_title`
columns.

Verification:
- `python -m pytest tests\reporting\test_settled_day_root_cause.py -q` passed
  with `3 passed`.
- `python -m weather.reporting.settled_day_root_cause --date 2026-06-20 ...`
  regenerated the JSON, Markdown, and issue CSV with active-owner
  classifications.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - ACTIVE OWNER RECURRENCE ROUTING LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

