# 110o part 2 — D1-09 scheduled evidence producers [PARTIAL]

**Verdict: implementation is drafted; local qualification is blocked because the workstation-heavy wrapper rejected both the isolated-worktree and assigned-checkout invocations for host/principal identity.** No direct pytest or compile fallback was run. The branch is not qualified until the wrapper suite and exact-head CI pass.

The D1-09 producer chain now registers seven artifacts in `daily_refresh` and routes each through its isolated child runner. Two promotion inputs are refreshed before `promotion_refresh`; dependent reports run after their required current-run reports. `forecast_tracker` is omitted from scheduling: the traced promotion reader only copied its status into a display summary, so that copied field and its report row were removed. No fixture or production runtime data was opened for this work.

## Producer and consumer trace

| Producer | Current input and output contract | Reader and action | Scheduled position |
| --- | --- | --- | --- |
| `data_quality/per_location_artifact_quarantine.py` | Reads artifact and variant registries; writes `data/backtest/per_location_artifact_quarantine.json` and report. | `promotion/orchestration.py` reads the quarantine artifact when assembling promotion decisions; absent or invalid input remains a blocker. | After `fleet_observability`, before `promotion_refresh`. |
| `source_gates/physical_feature_family_ratchet.py` | Reads `source_family_inventory.json` and `source_family_ablation.json`; writes `data/backtest/physical_feature_family_ratchet.json` and report. | `promotion/orchestration.py` reads the ratchet before family decisions; missing or blocked family evidence remains fail-closed. | After `fleet_observability`, before `promotion_refresh`. |
| `location_analysis/pooled_f_retrain_location_gate.py` | Reads the pooled band artifact, training report, replay, prior refresh, predawn repair, bottom-location and exact-distance reports; writes `pooled_f_retrain_location_gate.json`. | `served_distribution_calibration_contract.py` consumes it. | After current-run `promotion_refresh`. |
| `serving_gates/served_distribution_calibration_contract.py` | Reads the serving ordinal gate, pooled-location gate, replay/candidate reports, exact-distance and bottom-location reports, and predawn refresh; writes `served_distribution_calibration_contract.json`. | Proper-scoring step reads it at `daily_refresh_reporting_steps.py`; early-hour gate and proof packet also consume it. | After the pooled-location gate and before proper scoring. |
| `serving_gates/early_hour_positive_daily_first_gate.py` | Reads `progress_audit.json`, the served-distribution contract and the two candidate time-split reports; writes `early_hour_positive_daily_first_gate.json`. | `weather_only_model_proof_packet.py` includes its verdict as a proof gate. | After `progress_audit`. |
| `scorecards/weather_only_model_proof_packet.py` | Reads promotion, hourly/ten-minute, distance, bottom-location, fleet, progress, daily-progress, served-distribution, early-hour, Austin and winner-parity evidence; writes `weather_only_model_proof_packet.json`. | `market_beating_objective_scoreboard.py` treats the packet as a required input. | After `daily_learning`, before the scoreboard. |
| `market/market_benchmark_residual_edge.py` | Reads active-shadow rows and trading evidence; writes `market_benchmark_residual_edge.json`. | `market_beating_objective_scoreboard.py` treats residual-edge evidence as required input. | Before the scoreboard; active-shadow and trading-evidence producers precede it. |

The eight paths named by the D1-09 audit reconcile to the handoff's seven scheduled producers plus one display-only input. The promotion gauntlet read `forecast_vs_realized.json` only to display an INFO/WARN line; its status did not enter the overall verdict. That file read, CLI option, orchestration argument, copied manifest field and display row are removed. The `forecast_tracker` module and its own tests remain available to explicit callers.

## Changed files and roll classification

| File | Classification | Change |
| --- | --- | --- |
| `src/weather/operations/daily_refresh_registry.py` | **Roll-sensitive** | Registers the seven steps in dependency order and declares learning coverage/dependencies. |
| `src/weather/operations/daily_refresh_steps.py` | **Roll-sensitive** | Adds seven isolated report adapters to `DEFAULT_RUNNERS`. |
| `src/weather/operations/daily_refresh_reporting_steps.py` | **Roll-sensitive** | Adds child-process CLI adapters; output and evidence paths derive from the configured backtest root. |
| `src/weather/operations/daily_refresh.py` | **Roll-sensitive** | Exports the adapters through the existing daily-refresh surface. |
| `src/weather/reporting/promotion/readers.py` | **Roll-sensitive** | Stops copying the display-only forecast-tracker field into promotion output. |
| `src/weather/reporting/promotion/promotion_gauntlet.py`, `cli.py`, `orchestration.py`, `report.py` | **Roll-sensitive** | Removes the display-only tracker read, argument, carry-forward field and report row. |
| `tests/operations/test_daily_refresh.py`, `tests/reporting/test_promotion_corpus.py`, `tests/calibration/test_promotion_refresh.py` | **Roll-free** | Adds dependency-order, runner-binding, fixture-output-root and display-drop assertions; removes obsolete fixture arguments. |
| `docs/roadmap/agent-report-2026-09-110o-2.md` | **Roll-free** | Records the source trace, classification, evidence and production handback. |
| `docs/roadmap/correspondence-index.md` | **Roll-free** | Generated by `weather.reporting.roadmap.correspondence_index` after the report's first commit. |

The source edits are loop-imported; no production roll verdict or production closure state was inspected. Treat integration as **roll-sensitive** until production runs `scripts/ops/roll_verdict.ps1 -Branch codex/110o-unscheduled-producers-20260928` and follows its result. Production closure membership is **unverified**.

## Verification and handback

The focused fixture selection includes `tests/operations/test_daily_refresh.py`, `test_daily_refresh_step_child.py`, all seven producer tests, `test_promotion_corpus.py`, and the four repository-wide audits (`test_schema_registry.py`, `test_import_architecture.py`, `test_agent_docs_audit.py`, and `test_path_policy.py`). The required wrapper rejected both attempts with `this host and Windows principal are not the assigned non-capture workstation`; no pytest or compileall result is claimed. The attempted task-owned basetemps were not created. Re-run the full focused selection through `scripts/ops/workstation_heavy.ps1` on the assigned non-capture workstation, then confirm CI on the exact pushed head.

Production activation steps after qualification:

1. Obtain the roll verdict with `scripts/ops/roll_verdict.ps1 -Branch codex/110o-unscheduled-producers-20260928`; use the existing quiet-window integration path if the verdict requires it. Do not alter Scheduler registration as part of this change.
2. Let the existing daily-refresh Stage A/B invocation execute the new registered steps. Confirm its current-run receipt names and output paths for all seven producers. Missing inputs must remain visibly BLOCK/MISSING; do not seed these reports from historical or hand-created PASS JSON.
3. Confirm the two pre-promotion reports exist before `promotion_refresh`; confirm the five dependent reports run after their declared producers and before the scoreboard consumes them. Retain the daily-refresh manifest and report with the production closeout.
4. Keep the seven producer identifiers in the 110m part-5 unscheduled-producer allow-list until the schedule and current-run receipts are verified in production; then resolve the allow-list entries through that ratchet's owner. Do not claim production closure from this workstation report.
