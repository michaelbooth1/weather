# 298. Automatic Experiment Queue And Drift-Triggered Retrain Loop [COMPLETE 2026-06-24 - STRUCTURED QUEUE, NIGHTLY EXECUTION, AND RETRAIN RECOMMENDATION LIVE]

Goal: close the improvement loop. Turn the daily analysis's per-slice experiment
hints into a machine-readable queue that nightly retrain actually executes, and
trigger retraining from drift/novelty signals instead of running it
unconditionally.

Source: 2026-06-24 audit of the daily analysis script. `daily_learning` already
emits per-slice experiment hints via `gap_owner_table.next_experiment` and
`experiment_artifact` (`src/weather/reporting/daily/daily_learning.py:423-440`),
but these are advisory text only: `nightly_retrain` consumes just an integer
`retrain_input_count` from the summary
(`src/weather/operations/nightly_retrain.py:407`) and otherwise retrains on a
fixed daily schedule. There is no structured experiment queue and no signal that
makes retraining conditional on there being something new to learn.

Why this matters: the system observes weaknesses (weak slices, chronic blockers,
calibration drift) every day but does not automatically act on them, and it
spends retrain compute every night regardless of whether the corpus grew or the
model drifted. A structured, consumed experiment queue plus drift-triggered
retraining is the difference between a daily report and a self-improving loop.

Why it is not already covered: item 37 owns the always-on nightly retrain
infrastructure, item 108 owns overnight self-improvement run evidence, and items
115/125/138 own specific gap-remediation and input-pruning programs, but none
provide a generic machine-readable experiment queue that nightly retrain executes
or a drift/novelty trigger that gates whether retraining runs.

## Design

1. Emit a structured, deduplicated experiment queue from the daily analysis with
   fields `{slice, hypothesis, artifact_path, clearance_rule, status, priority}`,
   sourced from the gap-owner table, weak slices, chronic blockers (item 295),
   and calibration drift (item 297).
2. Have `nightly_retrain` read the queue, execute the top-N eligible experiments,
   and write their results back, then have the next daily analysis mark each
   queued experiment `resolved`, `regressed`, or `still_open`.
3. Add a `retrain_recommended` signal with an explicit reason (corpus grew by at
   least N market-days, calibration drift over threshold, a chronic slice
   persists, or a new clean settled day) so unconditional nightly retraining can
   be replaced or supplemented by drift-triggered retraining.
4. Keep it fail-closed: an empty or stale queue and missing drift inputs default
   to the existing scheduled behavior rather than skipping retraining silently,
   and queued experiments never auto-promote without the existing promotion and
   clustered-confidence gates.

- [x] Emit a machine-readable, deduplicated experiment queue from the daily
  analysis.
- [x] Make `nightly_retrain` consume the queue, run top-N experiments, and write
  results back.
- [x] Mark queued experiments resolved/regressed/still-open on the next daily
  run.
- [x] Add a `retrain_recommended` drift/novelty trigger with explicit reasons.
- [x] Add tests proving the queue round-trips and that drift triggers (and the
  absence of drift suppresses) a retrain recommendation without disabling
  scheduled retraining.

Acceptance: the daily analysis emits a structured experiment queue that nightly
retrain executes and writes back, the next daily run reconciles each experiment's
outcome, and a `retrain_recommended` signal fires from explicit drift/novelty
reasons while never auto-promoting outside the existing gates, proven by
round-trip and drift-trigger tests.

Closed notes:

- `daily_learning` now emits `experiment_queue` with schema
  `automatic_experiment_queue_v0.1`, stable `queue_id`s, required queue fields,
  item 301 repair-manifest ingestion, and result reconciliation from
  `experiment_queue_results.json`.
- `nightly_retrain` now runs an internal `experiment_queue` step after daily
  learning, executes top-N eligible command-bearing items, and writes
  `experiment_queue_results_v0.1` with `resolved`, `regressed`, or
  `still_open` reconciliation status for the next daily run.
- `retrain_plan.retrain_recommendation` now records explicit drift/novelty
  reasons and preserves scheduled fail-closed behavior; expensive retrain
  skipping is opt-in via `--skip-when-no-retrain-recommendation`.
- Verification:
  `python -m pytest tests\reporting\test_daily_learning.py::TestDailyLearning::test_build_learning_payload_emits_experiment_queue_and_reconciles_results tests\reporting\test_daily_learning.py::TestDailyLearning::test_build_learning_payload_suppresses_retrain_recommendation_without_clean_triggers tests\operations\test_nightly_retrain.py`.

Related: items 36, 37, 108, 115, 125, 138, 295, 297.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - STRUCTURED QUEUE, NIGHTLY EXECUTION, AND RETRAIN RECOMMENDATION LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

