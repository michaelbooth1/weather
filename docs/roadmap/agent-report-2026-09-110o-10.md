# 110o part 10 — dormant roadmap items (owner decision 10, D5-5) [DONE]

**Verdict: DONE, roll-free. Roadmap items gain a `DORMANT YYYY-MM-DD - reason` status (dated disposition required, lint
error otherwise), `roadmap_backlog` lists dormant items apart from the active backlog, and it flags an active item with no
disposition within 45 days. 27 items are marked dormant 2026-09-29: the 25 listed in D5-5 plus 321 and 328.** Active
items fall from 38 to 11; the new flag lists 3 of them (224, 323, 333).

Branch `codex/110o-dormant-items-20260929`; handoff
[workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 10; audit row
D5-5 and proposed ratchet 3 ([D5](audits/repo-health-audit-2026-09-26/dimensions/D5.md)).

## Decisions made while implementing

- **Which items.** The handoff says "the 25 listed items including 321, 322 and 328". D5-5's list of 25 contains 322 but
  not 321 or 328, which the audit README names separately. All 27 are marked; 321 and 328 are the only additions.
- **The 45-day flag uses the newest disposition date in the roadmap, not the clock.** `active-backlog.md` is checked in
  CI with `roadmap_backlog --check`; a wall-clock age would make the committed file go stale every day with no source
  change. With the newest date as reference the report is reproducible and still moves forward as items are updated. It
  reports, never fails (ratchet 3).
- **Revivable, not closed.** Each heading keeps the prior status: `DORMANT 2026-09-29 - <reason>; WAS <old status>`.
  Reasons: 322 taker retired; 328 paper maker retired; 321 Release 1 deferred until a retrained candidate; 157, 161, 307
  soak/cadence proofs (the streak is a diagnostic); the other 21 `NO ACTIVITY SINCE <date>, NO OPERATIONS INBOUND`.
  The June model items may revive (owner 09-21 "model work unpaused"): restore `OPEN`/`PARTIAL` with a fresh date.

## What changed

| File | Roll | Change |
| --- | --- | --- |
| `src/weather/reporting/roadmap/roadmap_backlog.py` | roll-free (reporting CLI; confirm) | `DORMANT` in `STATUS_RE`; `dormant_item_missing_dated_disposition` lint; `stale_active_items()`; payload `dormant_items`, `stale_active_items`, summary counts; Markdown sections. Payload change is additive; `schema_version("roadmap_backlog")` and the schema registry are untouched. |
| `tests/reporting/test_roadmap_backlog.py` | roll-free | Dormant parked outside active; missing date/reason is a lint error; flag at 46 vs 45 days, undated active, COMPLETE/DORMANT never flagged, reference date from sources. |
| `src/weather/reporting/scorecards/settled_day_root_cause.py` | roll-sensitive until `roll_verdict.ps1` says otherwise (Stage-A reporting) | Found by PR CI: it maps issue codes to *active* roadmap owners. An issue owned only by DORMANT items would have fallen through to `complete_owner_unverified_date` and suggested a new roadmap item. New `dormant_owner` classification (checked after `active_owner`) and a `dormant_owner_items` field; additive. |
| `tests/reporting/test_settled_day_root_cause.py` | roll-free | Items 157, 160, 161 now appear as dormant owners with `dormant_owner` classification; `new_roadmap_item_candidate_count` stays 0. |
| 27 `docs/roadmap/items/item-*.md` headings, `docs/roadmap/ROADMAP.md` rows | roll-free | Dormant status text (BOM and line endings preserved). |
| `docs/roadmap/active-backlog.md` | roll-free | Regenerated. |
| `docs/roadmap/AGENTS.md` | roll-free | Item format documents `DORMANT` and the flag. |

## Verification

`roadmap_backlog --fail-on-lint --check` OK (0 lint errors); `tests/reporting/test_roadmap_backlog.py` and
`tests/app/test_app_roadmap.py` 17 passed; repo-wide audits run with them (see PR). Production confirms roll with
`scripts\ops\roll_verdict.ps1 -Branch codex/110o-dormant-items-20260929`.

## What was NOT done

No item was closed or deleted; no item body was edited beyond its heading. No registration, production write, restart or merge.

## Production steps

1. CI green; roll verdict; land on the roll-free light path when the exam-period merge policy allows.
2. Owner review of the three flagged active items (224, 323, 333): refresh each disposition or mark it `DORMANT`.
