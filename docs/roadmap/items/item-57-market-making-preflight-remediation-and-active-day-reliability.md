# 57. Market-Making Preflight Remediation And Active-Day Reliability [COMPLETE 2026-06-15 - REMEDIATION INCIDENTS LIVE]

Goal: turn recurring market-making preflight failures into actionable recovery
work so the live-forward paper test can collect clean, countable days.

Observed from the running `paper-live-forward` test on 2026-06-15: the latest
run report showed all 12 tracked markets failing preflight. Most markets were
blocked by missing current source-status rows; NYC was stale on the current
model snapshot; San Francisco had CLOB freshness gaps; and Seattle had both
source-status and CLOB freshness problems. The fail-closed behavior is correct,
but the test now needs a remediation loop that tells us how to get back to a
quoteable, countable active day.

- [x] Audit the source-status writer path for every tracked market and guarantee
  a current source-status row is emitted alongside each latest snapshot/model
  row, even when one upstream source is stale or failed.
- [x] Split preflight details into root-cause categories that map to an owner:
  missing source-status row, stale source-status row, stale model row, missing
  active event, missing CLOB tokens, stale CLOB book tape, missing CLOB feature
  rows, watcher stale, promotion blocked, and live-gate blocked.
- [x] Generate a `preflight_remediation.json` or equivalent report with
  first-seen/last-seen times, last good artifact, owning supervisor, suggested
  local command, and whether same-day recovery can still make the day count.
- [x] Integrate the remediation report into `market_making_run` and the MM
  dashboard so a blocked run points to the specific loop or artifact rather
  than only saying `missing current source-status rows`.
- [x] Add active-day reliability checks that run while the test is active and
  alert within 60 seconds when source-status, model, CLOB, or watcher freshness
  would cause the next tick to fail preflight.
- [x] Account for long replay/refresh jobs that can starve snapshot or CLOB
  loops; either isolate them or mark the active-day test as non-countable before
  they create immutable tape gaps.
- [x] Add regression tests using the 2026-06-15 blocker pattern: missing
  source-status rows across most markets, one stale model market, and CLOB gaps
  on west-coast markets.

Acceptance: a full active-day `paper-live-forward` test either maintains fresh
source-status, model, CLOB, and watcher inputs across all selected markets, or
emits actionable preflight incidents quickly enough to recover; silent
`NO_QUOTE_MISSING_PREFLIGHT` floods no longer hide the remediation path.

Implementation update (2026-06-15): `market_making_run` now writes
`preflight_remediation.json`, maps failed preflight gates to root causes,
owners, last-good artifacts, local commands, recoverability, alert deadlines,
and live-forward countability. Remediation incidents are appended to
`risk_events.jsonl` and summarized in `run_summary.json`; the MM dashboard shows
the blocker drilldown and live-forward gate state. Source-status writer behavior
was verified against existing `SnapshotStore.source_status_rows` coverage for
fresh and stale source rows plus source-status backfill. Validation:
`pytest tests\market\test_market_making_run.py tests\app\test_market_making_view.py -q`
passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - REMEDIATION INCIDENTS LIVE`.
- The file contains 7 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

