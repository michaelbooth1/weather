# 308. Model-Performance Scoring Liveness And Regenerate-On-Settlement [COMPLETE 2026-06-24 - MODEL-SKILL SCORING WENT 3 DAYS STALE WHILE LABELS ARE CURRENT]

Goal: ensure the model-skill scoring artifacts regenerate when new settlement
labels land, and that a scoring step which fails to produce an artifact at least
as fresh as the latest settled label becomes a visible blocking remediation
rather than silent multi-day staleness.

Source: settled 2026-06-23 log audit. Settlement labels were current to
2026-06-23 (latest finalized 2026-06-24), but `hourly_model_performance`,
`ten_minute_model_performance`, and `price_free_model_learning` were all last
generated `2026-06-21T13:40`, the `settled_day_root_cause` report still covered
2026-06-22, and `daily_learning` reported `run_date=2026-06-22`. The 2026-06-24
`daily_refresh_status` ran with only 4 steps and none of them were the
model-performance scoring steps, so the early-hour and 10-minute promotion gates
blocked on skill numbers computed against 3-day-stale scoring. Item 294's input
freshness gate correctly flagged the staleness, but that is detection only;
nothing re-ran the scoring.

Why this matters: the hourly and 10-minute gates directly drive promotion
readiness and early-hour blocker enforcement. Scoring the served model against
3-day-old labels can both block a genuinely improved model and credit a stale
one, and it means the daily "which location did well or poorly" answer is simply
absent for the day that just settled. Detection without regeneration leaves the
nightly permanently blocked rather than self-healing.

Why it is not already covered: item 294 detects input staleness and consistency
but does not regenerate any artifact; item 305 enforces settled-day finalization
ordering, a barrier, and rerun of the daily-learning packet, but does not own
re-running the model-performance scoring sub-steps and does not list them in its
dependency graph; items 145/160/168 produce and consume these scoring artifacts
but none guarantees regeneration on new settlement or treats a non-regenerated
scoring artifact as a step failure; items 303/304 cover taker and maker evidence
regeneration, not model scoring.

## Design

1. Make settlement finalization (or the settled-day analysis chain) trigger
   re-scoring of `hourly_model_performance`, `ten_minute_model_performance`,
   `price_free_model_learning`, and `settled_day_root_cause` for the newly
   settled target date.
2. Record a per-artifact `last_scored_target_date` and treat any model-skill
   scoring artifact older than the latest settled label as a blocking
   step-level remediation with an explicit rerun command, not a silent warning.
3. Add these scoring steps to the daily refresh / nightly dependency graph so a
   failed or skipped scoring step is a visible refresh-chain error.
4. Fail closed so the hourly, 10-minute, and early-hour promotion gates never
   consume scoring computed against labels older than the latest settled day.
5. Surface scoring liveness (per-artifact scored target date versus latest
   settled label) in daily learning and daily flow.

- [x] Trigger model-performance scoring regeneration when a new day settles.
- [x] Add `last_scored_target_date` and a blocking remediation for scoring older
  than the latest settled label.
- [x] Add the scoring steps to the refresh dependency graph with step-level
  error surfacing.
- [x] Block the hourly/10-minute/early-hour gates from consuming stale-dated
  scoring.
- [x] Add tests proving a newly settled day regenerates scoring or emits a
  blocking step error, and that gates reject stale-dated scoring.

Acceptance: when a new day settles, the model-performance scoring artifacts
regenerate for that target date or emit a blocking step-level remediation with a
rerun command, no model-skill gate consumes scoring older than the latest settled
label, and a regression test proves a stale scoring artifact triggers
regeneration or a blocker rather than silent staleness.

Closed notes:

- Added a shared `model_scoring_liveness` contract that records
  `last_scored_target_date`, compares it with the latest promotion-countable
  settled label, and emits a blocking rerun remediation when stale.
- Stamped liveness into hourly, 10-minute, price-free, and settled-day
  root-cause artifacts; stale hourly/10-minute scoring now injects hard gate
  blockers that promotion readiness cannot candidate-mitigate.
- Daily refresh now surfaces scoring liveness in step results and marks the run
  critical when any scoring artifact is stale; daily learning and daily flow
  surface P0 blocker actions and scored-vs-latest dates.
- Verified with
  `python -m pytest tests\reporting\test_hourly_model_performance.py tests\reporting\test_ten_minute_model_performance.py tests\reporting\test_price_free_model_learning.py tests\reporting\test_settled_day_root_cause.py tests\reporting\test_daily_learning.py tests\operations\test_daily_refresh.py tests\calibration\test_promotion_refresh.py tests\reporting\test_daily_flow_analysis.py`.

Related: items 37, 120, 145, 160, 168, 198, 199, 294, 305.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - MODEL-SKILL SCORING WENT 3 DAYS STALE WHILE LABELS ARE CURRENT`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

