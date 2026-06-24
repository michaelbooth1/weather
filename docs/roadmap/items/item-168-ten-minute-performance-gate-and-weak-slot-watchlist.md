# 168. Ten-Minute Performance Gate And Weak-Slot Watchlist [COMPLETE]

Goal: make 10-minute local-slot model performance a first-class promotion and
daily-learning gate instead of relying only on hourly averages.

Source: `data/backtest/ten_minute_model_performance_audit.md` generated on
2026-06-20 from `ten_minute_model_performance_audit_v0.1`. The current model
scores 10-minute checkpoints at Brier `0.0537` versus market `0.0368` across
54 settled market-days. The weak-slot top decile is concentrated at `03:00`,
`03:10`, `03:20`, and `04:00` through `05:50`, with aggregate model Brier
`0.0721` versus market `0.0592`.

Why this matters: the hourly gate correctly identifies the early-hour problem,
but a candidate can still hide slot-level regressions inside a broad
00:00-08:00 average. The 10-minute audit shows the actionable failure window
is narrower than the whole early regime and should become the remediation
watchlist for candidate promotion.

## Design

1. Promote `tools/research/ten_minute_performance_audit.py` into a canonical
   reporting module with schema registration, tests, and stable CLI outputs.
2. Run the 10-minute audit after settled labels, hourly performance, and
   promotion-corpus refreshes.
3. Persist JSON, Markdown, current all-slot CSV, and candidate all-slot CSV in
   the daily evidence bundle.
4. Define a weak-slot gate over the top-decile model-Brier slots, with minimum
   market-day evidence, Brier/log-loss tolerance versus market, and candidate
   delta versus current.
5. Require candidate-specific 10-minute evidence to match the candidate
   variant ID before it can mitigate a current-serving weak-slot blocker.
6. Feed the weak-slot list, worst absolute slots, worst market-relative slots,
   and accepted remediation owner into daily learning and progress audit.

- [x] Move the 10-minute audit from `tools/research` to
  `weather.reporting.ten_minute_model_performance` with schema registry
  coverage.
- [x] Add tests that verify first-checkpoint-per-market-day-band-slot
  semantics and all 144 local slots in the CSV output.
- [x] Add a candidate 10-minute performance gate for Item-69-style variant
  row exports.
- [x] Wire the current and candidate 10-minute gates into promotion refresh
  and daily learning.
- [x] Add a weak-slot watchlist section to progress audit so broad
  improvement claims cannot ignore slot-level regressions.

Implementation evidence:

- Added canonical `weather.reporting.ten_minute_model_performance` with
  registered current and candidate gate schemas.
- Daily refresh now writes `ten_minute_model_performance.json`,
  `ten_minute_model_performance_report.md`,
  `ten_minute_model_performance_by_slot.csv`, and candidate slot CSV output.
- Promotion readiness blocks on current-serving weak-slot regressions and only
  applies candidate mitigation when `candidate_ten_minute_gate` is `PASS` and
  the candidate variant ID matches.
- Daily learning and progress audit now surface the weak-slot watchlist and
  blocker details.
- Verified with `python -m pytest tests/reporting/test_ten_minute_model_performance.py tests/operations/test_schema_registry.py tests/operations/test_daily_refresh.py tests/calibration/test_promotion_refresh.py tests/reporting/test_daily_learning.py tests/reporting/test_progress_audit.py -q`.

Acceptance: every promotion candidate has current and candidate 10-minute
slot evidence attached, weak-slot regressions are explicit blockers, and a
candidate cannot clear the early-hour blocker solely by improving the broad
hourly average while leaving the `03:00` through `05:50` weak-slot cluster
unfixed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

