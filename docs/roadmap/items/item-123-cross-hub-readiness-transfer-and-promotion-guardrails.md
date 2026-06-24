# 123. Cross-Hub Readiness Transfer And Promotion Guardrails [COMPLETE 2026-06-18 - READINESS REPORT LIVE]

Goal: turn hub-specific lessons from Toronto, Denver, Atlanta, Dallas, Miami,
Seattle, and the other active weather hubs into a repeatable readiness report
that separates model skill, source redundancy, quoteability, and operational
live-forward eligibility.

Source: the 2026-06-18 cross-hub review found that all 12 active hubs were
blocked by snapshot coverage gaps even though CLOB capture and observation
trigger health were passing. Toronto had the strongest source-readiness pattern
and highest trust maturity, Denver/Atlanta were the cleanest promotion examples,
Dallas showed that fewer collection gaps do not imply calibrated trust, and
Miami/Seattle showed that quote behavior is not the same as forecast edge.

Why this matters: a one-off review can catch these differences, but operators
need the same distinction every day. A hub should not look stronger merely
because it has more quote rows, fewer snapshot gaps, or more mature source
coverage if its model/trust/live gates are weak.

## Design

1. Build a cross-hub readiness report from durable artifacts:
   `fleet_observability.json`, `f_family_promotion_refresh.json`,
   `mm_paper_report.json`, quote-intent tapes, and the latest run summaries.
2. Add a per-market table with collection, source redundancy, trust/ECE,
   candidate-vs-current, candidate-vs-market, quoteability, and live-forward
   evidence.
3. Classify each hub as `promote`, `shadow`, `ops-blocked`, or
   `model-blocked`, preserving the model decision even when operational gates
   force the final readiness label to `ops-blocked`.
4. Apply explicit anti-false-strength guardrails:
   quote rows cannot promote Miami/Seattle, collection cleanliness cannot
   promote Dallas without ECE/trust clearance, and broad live claims remain
   blocked while snapshot, preflight/current-market, serialization, or replay
   artifact gates fail.
5. Attach the relevant hub lesson to each blocked market so the report explains
   what should transfer: Toronto-style source redundancy, Denver/Atlanta
   promotion criteria, Dallas trust calibration, quoteability-vs-edge
   separation, or shared plumbing recovery.

- [x] Generate `data/backtest/cross_hub_readiness.json`.
- [x] Generate `data/backtest/cross_hub_readiness_report.md`.
- [x] Add per-market readiness labels and reason strings.
- [x] Add anti-false-strength tests for Miami/Seattle quoteability and Dallas
  collection/trust separation.
- [x] Keep broad live-forward claims blocked while shared operational gates are
  failing.
- [x] Surface the applicable hub lesson for every blocked market.

Acceptance: the report can be regenerated from current artifacts and shows a
per-market readiness table with collection, source redundancy, trust/ECE,
candidate-vs-current, candidate-vs-market, quoteability, and live-forward
evidence. The final label is `ops-blocked` while shared plumbing is unhealthy,
but model labels still show which hubs are promote/shadow/model-blocked. Miami
and Seattle cannot be promoted merely from quote volume, Dallas cannot be
promoted merely from cleaner collection, and every blocked row names the lesson
to transfer.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - READINESS REPORT LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

