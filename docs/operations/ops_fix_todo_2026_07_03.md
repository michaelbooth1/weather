# Ops Fix Todo - 2026-07-03 Audit

Source audit: `data/backtest/ops_audit_2026_07_03.md`

Status legend:

- `[ ]` not started
- `[~]` partially fixed
- `[x]` fixed in code or verified by targeted tests
- `[!]` requires operator/runtime action or historical-data repair

## P0 - Restore Countable Live/Promotion Evidence

- [~] Fix fleet source-status blocking for all 12 markets.
  - [x] Fix gate semantics so intentionally disabled paid-provider sources classify as expected-unavailable when free replacements are approved/healthy.
  - [x] Add regression coverage for `paid_provider_disabled` source rows.
  - [!] Repair/rerun the public/free WU settlement collection path if fresh source-status captures still miss required free replacements.
  - [!] Rerun source-status capture/recovery and fleet status; do not solve this with paid-provider credentials.
  - [!] Acceptance: all 12 markets have no source-status blocker after live recapture.
- [~] Resolve snapshot cadence failures.
  - [x] Add microsecond snapshot IDs so scheduled and observation-trigger snapshots in the same second do not collide.
  - [x] Add artifact-integrity validation for duplicate snapshot IDs and invalid probability sums.
  - [x] Add regression coverage for same-second scheduled/trigger snapshot IDs.
  - [!] Investigate/repair the live scheduler gaps for 12/12 markets through the supervisor/runbook.
  - [!] Fix early-hour coverage gaps for the 9 blocked markets by rerunning healthy early-hour collection windows.
  - [!] Check supervisor restart/backoff behavior, writer locks, and loop delays on the host.
  - [!] Acceptance: `snapshot_cadence_proof=PASS` and `early_hour_coverage_proof=PASS`.
- [~] Fix daily-refresh long-job staleness.
  - [x] Add long-job guard heartbeat/progress updates while guarded daily-refresh steps are running.
  - [x] Persist last completed step, completed step count, total step count, and refreshed duration.
  - [x] Add long-job guard and daily-refresh regression coverage.
  - [!] Investigate the live PID 28516 state and stale `long_job_guard_status.json` through the supervisor/runbook; do not manually edit locks.
  - [!] Acceptance: daily refresh completes without stale guard metadata and status is not `critical`.
- [!] Unblock nightly retrain and promotion.
  - [!] Resolve `promotion_corpus_vs_settled_labels`.
  - [!] Fix settlement-source/data-layer blockers after the source-status and daily-refresh reruns.
  - [!] Rerun daily learning, nightly retrain, and promotion refresh.
  - [!] Acceptance: `daily_learning=PASS`, `nightly_retrain=PASS`, promotion verdict no longer `not_run`.
- [~] Fix CLOB liveness/countability.
  - [x] Fix false DEAD classification for serial all-market CLOB loops by accounting for measured recent loop duration plus sleep time.
  - [x] Surface `dead_after_seconds` and measured recent iteration duration in CLOB health.
  - [x] Add regression coverage that slow-but-in-cycle CLOB health stays RUNNING while truly stale heartbeats remain DEAD.
  - [!] Restart/re-adopt the live CLOB loop through the supervisor/runbook and verify fresh heartbeat/status artifacts.
  - [!] Reduce book gaps and stale-book conditions after the loop is healthy.
  - [!] Acceptance: CLOB status healthy and taker no longer classifies evidence as `infra_starved_clob`.
- [~] Fix taker bot evidence starvation.
  - [x] Verified existing test coverage for clean `policy_no_edge` days being classified without restart.
  - [!] Resolve live `stale_heartbeat_metadata`.
  - [!] Fix restart/backoff/circuit-open churn after CLOB and snapshot cadence are healthy.
  - [!] Acceptance: taker evidence becomes `COUNTABLE` or explicitly clean `policy_no_edge`, not `infra_starved_clob`.
- [!] Fix market-making countability.
  - [!] Resolve `live_forward_gate=BLOCK` after source/cadence/CLOB recovery.
  - [!] Fix quote-permission starvation: 132 quote rows but 0 permission rows.
  - [!] Review quarantined MM runs and stale heartbeat metadata.
  - [!] Acceptance: MM daily roll counts toward live-forward evidence or cleanly explains no quoting.

## P1 - Data Integrity And Runtime Hygiene

- [~] Fix Austin duplicate snapshot IDs.
  - [x] Add microseconds to new `snapshot_id` values.
  - [x] Add regression test for scheduled and observation-trigger snapshots in the same second.
  - [x] Add daily validation for duplicate snapshot IDs and probability sums.
  - [!] Historical Austin duplicate rows still need quarantine/backfill if they remain in promotion evidence inputs.
- [~] Standardize process runtime.
  - [x] Verified current task registration scripts use the repo venv.
  - [!] Re-register scheduled tasks or restart old processes that were launched with system Python.
  - [!] Resolve any remaining mixed runtime identity blocks in live evidence after rerun.
- [x] Fix status command side effects.
  - [x] `nightly_retrain status` is read-only by default and prints JSON.
  - [x] Add `nightly_retrain status --write` for the previous SLA artifact write behavior.
  - [x] Add regression coverage that default status does not write artifacts.
- [~] Improve long-job guard semantics.
  - [x] Track alive-and-progressing state with `progress`, `updated_at_utc`, `last_progress_at_utc`, and refreshed `duration_seconds`.
  - [!] Add a richer alive-but-stale versus hung status taxonomy if the next live run still reports ambiguous stale metadata.
  - [!] Include last useful output/log timestamp in the guard/status report.
- [~] Fix bot supervisor logic.
  - [x] Verified existing taker daily-roll coverage for healthy no-edge/no-trade days avoiding restart classification.
  - [!] Recheck live supervisor behavior after CLOB/snapshot recovery.
  - [!] Keep infra-starved, stale heartbeat, missing artifact, and policy no-edge root causes separate in the live daily roll evidence.

## P2 - Monitoring, UI, And Model Quality

- [~] Fix Streamlit dashboard exception.
  - [x] Current single-market route smoke test passes; the logged `pd` `UnboundLocalError` appears stale.
  - [!] Add dashboard health logging for active-day views if the exception recurs.
- [~] Add artifact health checks.
  - [x] Duplicate snapshot IDs.
  - [x] Invalid probability sums.
  - [x] Missing source-status rows are already surfaced by source-family degradation.
  - [!] Add explicit stale CLOB row checks to the daily artifact-health rollup.
  - [!] Add explicit missing bot heartbeat metadata checks to the daily artifact-health rollup.
  - [!] Add quarantine count growth alerting.
- [!] Investigate model performance blockers.
  - [!] Ten-minute model performance block.
  - [!] Hourly model performance block.
  - [!] Early-hour weak slots.
  - [!] Winner-rank parity gap.
  - [!] Shadow A/B alerts.
- [!] Investigate imputer/all-missing feature warnings.
  - [!] Daily refresh tests still show sklearn warnings for all-missing feature columns.
  - [!] Populate, drop, or explicitly mark those features unavailable.
- [!] Clean up historical log instability.
  - [!] Review old `No space left on device`, `UnicodeDecodeError`, `MemoryError`, and malformed log quarantines.
  - [!] Add recurrence alerts even when disk is currently healthy.

## Best Remaining Order

1. Re-register/restart any live loops still using system Python, using the repo scheduler scripts.
2. Rerun source-status capture/recovery and fleet status for all markets.
3. Restart or re-adopt snapshot and CLOB supervisors through the runbook, then wait for a fresh cadence window.
4. Run daily refresh through the guarded path and verify guard progress is fresh.
5. Run nightly retrain and promotion refresh.
6. Rerun taker/MM daily rolls and confirm the evidence is countable or cleanly classified as policy no-edge/no-quote.
