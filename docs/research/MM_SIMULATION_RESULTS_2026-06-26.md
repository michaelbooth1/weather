# Market-Making Simulation And Evidence Results

Date: 2026-06-26

Scope: safe local tests, paper evidence, CLOB health checks, and one keyless shadow tick. No live orders were placed.

## 2026-06-27 Continuation Recheck

Safe runtime and scenario work continued at `2026-06-27T14:13Z` to `14:38Z`:

- `market_microstructure status` first showed the CLOB loop had drifted back to `date_selection = market_local_date` with two duplicate local-date loop processes. A safe fixed-date restart was run:
  `.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --date 2026-06-27 --no-price-history --no-websocket-events --clob-features`.
- Post-restart CLOB status initially returned `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, discovery sanity `PASS`, 12 nonzero-book markets, fresh books/features, 0 consecutive errors, and strict audit `ok = true` at `2026-06-27T14:17:44Z`.
- A later pre-fix runtime-identity `ensure` restart launched another undated replacement; `data/snapshots/clob_diagnostics.jsonl` now makes that visible. A final explicit restart at `14:37Z` stopped two undated processes and restored `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, `include_price_history = false`, `include_ws_events = false`, discovery sanity `PASS`, useful raw-book iterations, and 0 target-date mismatch markets. Process inspection confirmed `--date 2026-06-27 --no-price-history --no-websocket-events`; strict target-date audit again returned `ok = true` for all 12 markets.
- Correct snapshot status command is `weather.collection.snapshot_tracker --status`; the older `weather.capture.snapshot_tracker` module path fails in this checkout. Latest snapshot status returned `RUNNING`, `runtime_code_state = current`, `runtime_identity_matches_current = true`, fleet capture liveness `OK`, snapshot cadence `PASS`, early-hour coverage `BLOCK`, and source-status proof `BLOCK` on `settlement_source_auth_failure` with optional provider status fields absent/redacted.
- Added a bounded high-spread/wide-book policy simulation in `tests/market/test_mm_policy.py`: `test_high_spread_wide_book_requires_depth_and_spread_bounds`. It holds clean preflight inputs, varies spread/depth, confirms a deep `0.079` spread book can quote harvest-only, confirms `0.081` spread blocks with `NO_QUOTE_WIDE_SPREAD`, and confirms shallow depth blocks with `NO_QUOTE_THIN_DEPTH`.
- Verification: `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py -q` passed with `29 passed, 5 subtests passed in 0.21s`.

## Commands Run

Source-status degradation preflight regression:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_market_making_run.py -q
.\venv\Scripts\python.exe -m pytest tests\market\test_market_making_readiness.py -q
```

Result:

```text
39 passed in 3.24s
16 passed in 0.29s
```

Post-backfill all-market source-status degradation gate probe:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T103532784124Z --json-out data\backtest\mm_paper_shadow_20260627T103532_after_source_backfill.json --report-out data\backtest\mm_paper_shadow_20260627T103532_after_source_backfill.md --fills-out data\backtest\mm_paper_shadow_20260627T103532_after_source_backfill_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T103532784124Z\run_summary.json --paper-score data\backtest\mm_paper_shadow_20260627T103532_after_source_backfill.json --json-out data\backtest\mm_live_readiness_20260627T103532_after_source_backfill.json --report-out data\backtest\mm_live_readiness_20260627T103532_after_source_backfill.md
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T110334081112Z --json-out data\backtest\mm_paper_shadow_20260627T110334_current_source_status_block.json --report-out data\backtest\mm_paper_shadow_20260627T110334_current_source_status_block.md --fills-out data\backtest\mm_paper_shadow_20260627T110334_current_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T110334081112Z\run_summary.json --paper-score data\backtest\mm_paper_shadow_20260627T110334_current_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T110334_current_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T110334_current_source_status_block.md
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode paper-live-forward --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T111731961696Z --json-out data\backtest\mm_paper_paperlive_20260627T111731_active_source_status_block.json --report-out data\backtest\mm_paper_paperlive_20260627T111731_active_source_status_block.md --fills-out data\backtest\mm_paper_paperlive_20260627T111731_active_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T111731961696Z\run_summary.json --paper-score data\backtest\mm_paper_paperlive_20260627T111731_active_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T111731_paperlive_active_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T111731_paperlive_active_source_status_block.md
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode paper-live-forward --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T112944199984Z --json-out data\backtest\mm_paper_paperlive_20260627T112944_active_source_status_block.json --report-out data\backtest\mm_paper_paperlive_20260627T112944_active_source_status_block.md --fills-out data\backtest\mm_paper_paperlive_20260627T112944_active_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T112944199984Z\run_summary.json --paper-score data\backtest\mm_paper_paperlive_20260627T112944_active_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T112944_paperlive_active_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T112944_paperlive_active_source_status_block.md
```

Result:

- Before this probe, the documented source-status repair was run for the 12 current June 27 snapshot folders. It rewrote 3,756 local source-status rows from replay inputs and did not touch exchange state. Auth-only optional-provider failures are handled through free-source replacement coverage rather than provider setup.
- The post-backfill `snapshot_tracker --status` proof still returned `source_status.status = BLOCK`, `root_cause_class = settlement_source_auth_failure`, `source_status_blocked_market_count = 12`, `settlement_auth_failure_source_count = 12`, `blocking_family_market_counts = {weather_forecast: 12, wu_current: 12, wu_history: 12}`, and `settlement_auth_failure_family_source_counts = {wu_history: 12}`. Latest source-status rows had 12 `settlement_source_auth_failure` rows, 22 `stale_cache` fallback rows, and 2 `failed` rows, so the blocker is not merely a stale source-status artifact.
- Run folder `data/mm_runs/2026-06-27/20260627T103532784124Z`.
- Preflight `BLOCK`; first failing gate `source_status_degradation`.
- `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12, stale_model_row: 8}`.
- Readiness now surfaces the model/source split directly: `snapshot_model_source_failing_gate_counts = {model_freshness: 8, source_status_degradation: 12}`, `model_freshness_failed_market_count = 8`, and `source_status_degradation_failed_market_count = 12`.
- Readiness also surfaces source-status remediation directly: `source_status_blocker_root_cause_class = settlement_source_auth_failure`, `source_status_blocked_market_count = 12`, `source_status_blocking_families = 3`, aggregate `source_status_settlement_auth_failures = 12`, `source_status_settlement_auth_failures_per_market = 1`, and `source_status_repair_command = python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status`.
- 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-trade-permission rows.
- Console output now separates `quote-intent rows`, `quote-permission rows`, `no-quote rows`, and `live-permission rows`; the latest keyless run printed `132 quote-intent rows, 0 quote-permission rows, 132 no-quote rows, 0 live-permission rows`.
- Quote-blocker diagnostics attribute this to preflight, not the event gate: `paper_quote_blocker_event_gate_suppressed_rows = 0`; `contextual_event_gate_suppressed_rows = 0` confirms this latest check had no overlapping information-event suppression.
- Paper score: 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and no payout evidence.
- Readiness: `BLOCK` with 11 blockers, `live_capital_permission = false`, latest tick first failing gate `source_status_degradation`; `snapshot_model_source_fresh` also blocks on the 12 failing `source_status_degradation` market gates.
- Fresh follow-up run folder `data/mm_runs/2026-06-27/20260627T110334081112Z` kept the same no-go conclusion: preflight `BLOCK`, first failing gate `model_freshness`, 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-trade-permission rows.
- That blocker mix narrowed but did not clear: `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12, stale_model_row: 3}`; matching readiness `data/backtest/mm_live_readiness_20260627T110334_current_source_status_block.json` is `BLOCK` with 11 blockers and renders `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}`, `model_freshness_failed_market_count = 3`, `model_freshness_failed_markets = [atlanta, nyc, toronto]`, `source_status_degradation_failed_market_count = 12`, `source_status_degradation_failed_markets = all 12 selected markets`, aggregate `source_status_settlement_auth_failures = 12`, and `source_status_settlement_auth_failures_per_market = 1`.
- That score `data/backtest/mm_paper_shadow_20260627T110334_current_source_status_block.json` remained zero-exposure: 132 quote rows, 132 no-quote rows, 0 quote permissions, 0 live permissions, 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK`, reward score 0, exchange economics `PASS`, event-gate suppressed rows 0, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`.
- Active-window paper-live-forward one-shot `data/mm_runs/2026-06-27/20260627T111731961696Z` is now historical evidence for an observation-trigger runtime incident: `evidence_mode = active_day_live_forward`, preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, and `preflight_remediation.root_cause_counts = {observation_trigger_blocked_markets: 1, observation_trigger_stale_code_markets: 1, source_status_degradation_blocked: 12}`.
- Earlier active-window paper-live-forward one-shot `data/mm_runs/2026-06-27/20260627T112944199984Z` was stricter evidence after observation-trigger freshness recheck and remained no-go: `evidence_mode = active_day_live_forward`, preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, 0 live-trade-permission rows, live-forward gate `BLOCK`, and `current_counts_toward_live_forward_gate = false`.
- Its `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12}`. Matching readiness `data/backtest/mm_live_readiness_20260627T112944_paperlive_active_source_status_block.json` is `BLOCK` with 11 blockers and renders `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`, `model_freshness_failed_markets = []`, `source_status_degradation_failed_markets = all 12 selected markets`, `preflight_remediation_root_cause_counts = {source_status_degradation_blocked: 12}`, `observation_trigger_runtime_root_cause_counts = {}`, aggregate `source_status_settlement_auth_failures = 12`, and `source_status_settlement_auth_failures_per_market = 1`.
- The current score `data/backtest/mm_paper_paperlive_20260627T112944_active_source_status_block.json` remains zero-exposure but paper-fresh: `paper_score_freshness_status = PASS`, 132 quote rows, 132 no-quote rows, 0 quote permissions, 0 live permissions, 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`.

Broad maker/exchange/operations tests:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py tests\operations\test_market_making_daily_roll.py -q
```

Result:

```text
127 passed, 5 subtests passed in 56.43s
```

Continuation recheck of the prompt-required focused maker subset:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q
```

Result:

```text
118 passed, 5 subtests passed in 56.56s
```

Exchange-economics official-docs and fixture-default recheck:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_recheck.json
.\venv\Scripts\python.exe -m pytest tests\market\test_exchange_economics.py tests\market\test_mm_paper.py tests\operations\test_daily_refresh.py -q
```

Result:

```text
Exchange economics drift: PASS -> data\backtest\exchange_economics_drift_20260627_recheck.json
97 passed in 69.84s
```

The current and accepted snapshots both remain `xecon-036874d19e56c76f`; `material_change_count = 0` and `rescore_required = false`. The recheck also aligned `exchange_economics.build_snapshot_payload()` defaults with the accepted Polymarket US economics snapshot so fixture-generated simulations no longer default to legacy tick/min-size/maker-fee/reward assumptions.

Fresh current-source keyless shadow no-go probe:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date 2026-06-27
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_latest.json
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T122613569835Z --json-out data\backtest\mm_paper_shadow_20260627T122613_current_source_status_block.json --report-out data\backtest\mm_paper_shadow_20260627T122613_current_source_status_block.md --fills-out data\backtest\mm_paper_shadow_20260627T122613_current_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T122613569835Z\run_summary.json --paper-score data\backtest\mm_paper_shadow_20260627T122613_current_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T122613_current_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T122613_current_source_status_block.md
```

Result:

- CLOB loop was `RUNNING`, discovery sanity `PASS`, 0 consecutive errors, and fresh books/features; explicit strict target-date CLOB audit at `2026-06-27T12:25:29Z` returned `ok = true` for all 12 markets with startup gaps ignored before the current loop cutoff.
- Daily roll remained noncountable prior-target/post-settlement evidence: target date `2026-06-26`, expected target date `2026-06-27`, supervisor `SCHEDULED_WAIT`, start-time gate before `19:30` local, artifact liveness `STALE_HEARTBEAT_METADATA`, action `blocked_restart_required`, and `current_counts_toward_live_forward_gate = false`.
- Exchange-economics drift `data/backtest/exchange_economics_drift_20260627_latest.json` returned `PASS`, `material_change_count = 0`, `rescore_required = false`, and current/accepted snapshot `xecon-036874d19e56c76f`.
- Source-status proof summary remained `BLOCK`: `root_cause_class = settlement_source_auth_failure`, `source_status_blocked_market_count = 12`, and `settlement_auth_failure_source_count = 12`.
- Run folder `data/mm_runs/2026-06-27/20260627T122613569835Z`.
- Preflight `BLOCK`; first failing gate `source_status_degradation`.
- `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12, stale_model_row: 6}`. The six model-freshness failures were `denver`, `houston`, `los-angeles`, `miami`, `san-francisco`, and `seattle`.
- 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-trade-permission rows.
- Paper score `data/backtest/mm_paper_shadow_20260627T122613_current_source_status_block.json`: 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`.
- Readiness `data/backtest/mm_live_readiness_20260627T122613_current_source_status_block.json`: `BLOCK` with 11 blockers, `live_capital_permission = false`, `current_counts_toward_live_forward_gate = false`, and `snapshot_model_source_failing_gate_counts = {model_freshness: 6, source_status_degradation: 12}`.

Post-refresh and continuation current-source keyless shadow no-go probe:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force --market all --date 2026-06-27
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date 2026-06-27
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_continuation.json
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T124837800878Z --json-out data\backtest\mm_paper_shadow_20260627T124837_current_source_status_block.json --report-out data\backtest\mm_paper_shadow_20260627T124837_current_source_status_block.md --fills-out data\backtest\mm_paper_shadow_20260627T124837_current_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T124837800878Z\run_summary.json --paper-score data\backtest\mm_paper_shadow_20260627T124837_current_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T124837_current_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T124837_current_source_status_block.md
```

Result:

- Forced snapshot/model refresh completed for all 12 current June 27 markets with no blocked or error markets.
- Follow-up `snapshot_tracker --status` reported loop `RUNNING`, runtime identity current, `variant_missing_or_stale_market_count = 0`, `variant_markets_with_tape = 12`, source-status `BLOCK`, `root_cause_class = settlement_source_auth_failure`, `source_status_blocked_market_count = 12`, `settlement_auth_failure_source_count = 12`, redaction proof true, and early-hour coverage `BLOCK` for all 12 markets.
- Continuation strict target-date CLOB audit returned `ok = true` for all 12 markets, with 0 counted gap markets and startup gaps ignored before the current loop cutoff.
- Continuation daily roll remained noncountable prior-target/post-settlement evidence: status `idle_process`, action `blocked_restart_required`, target date `2026-06-26`, expected target date `2026-06-27`, evidence mode `post_settlement_evaluation`, supervisor `SCHEDULED_WAIT`, start-time gate `before_daily_start_time`, artifact liveness `STALE_HEARTBEAT_METADATA`, activity liveness `STALE_ACTIVITY`, live-forward gate `BLOCK`, and latest quote-permission rows 0.
- Exchange-economics drift `data/backtest/exchange_economics_drift_20260627_continuation.json` returned `PASS`.
- Run folder `data/mm_runs/2026-06-27/20260627T124837800878Z`.
- Preflight `BLOCK`; first failing gate `source_status_degradation`.
- `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12}`; the prior stale-model-row blocker cleared in the maker preflight after the forced refresh.
- 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-trade-permission rows.
- Paper score `data/backtest/mm_paper_shadow_20260627T124837_current_source_status_block.json`: 132 quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK`, reward score 0, exchange economics `PASS`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`.
- Readiness `data/backtest/mm_live_readiness_20260627T124837_current_source_status_block.json`: `BLOCK` with 11 blockers, `live_capital_permission = false`, `current_counts_toward_live_forward_gate = false`, `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`, `model_freshness_failed_market_count = 0`, `source_status_degradation_failed_market_count = 12`, and optional provider status fields false/redacted.

Observation-trigger recovery and latest current-source keyless shadow no-go probe:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_supervisor.py tests\operations\test_observation_trigger.py -q
.\venv\Scripts\python.exe -m weather.operations.observation_trigger ensure
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T130826087166Z --json-out data\backtest\mm_paper_shadow_20260627T130826_current_source_status_block.json --report-out data\backtest\mm_paper_shadow_20260627T130826_current_source_status_block.md --fills-out data\backtest\mm_paper_shadow_20260627T130826_current_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T130826087166Z\run_summary.json --paper-score data\backtest\mm_paper_shadow_20260627T130826_current_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T130826_current_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T130826_current_source_status_block.md
```

Result:

- Focused supervisor/observation tests passed: `40 passed in 3.79s`.
- `supervisor.acquire_file_lock` now replaces fresh dead-owner PID locks and keeps fresh live-owner locks; this is covered by tests in `tests/operations/test_supervisor.py`.
- Before recovery, `observation_trigger status` reported `state = DEAD`, PID 1536 not alive, heartbeat age about 782 seconds, and top-level watcher state `DEAD`.
- `observation_trigger ensure` removed the dead writer lock for PID 1536 and started a fresh watcher. Follow-up concise status reported `health_state = RUNNING`, `pid_alive = true`, heartbeat age about 21 seconds, `watcher_state = RUNNING`, and `watcher_fresh = true`.
- Run folder `data/mm_runs/2026-06-27/20260627T130826087166Z`.
- Preflight `BLOCK`; first failing gate `source_status_degradation`.
- `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12}`. The prior 125739 watcher-stale incident cleared; matching readiness has `observation_trigger_runtime_root_cause_counts = {}`.
- 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-trade-permission rows.
- Paper score `data/backtest/mm_paper_shadow_20260627T130826_current_source_status_block.json`: 132 quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`.
- Readiness `data/backtest/mm_live_readiness_20260627T130826_current_source_status_block.json`: `BLOCK` with 11 blockers, `live_capital_permission = false`, `current_counts_toward_live_forward_gate = false`, `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`, `model_freshness_failed_market_count = 0`, `source_status_degradation_failed_market_count = 12`, `source_status_blocker_root_cause_class = settlement_source_auth_failure`, optional provider status fields false/redacted, and 0 quote/live permissions.

Fresh active-window paper-live-forward no-go probe:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date 2026-06-27
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode paper-live-forward --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T131743658156Z --json-out data\backtest\mm_paper_paperlive_20260627T131743_active_source_status_block.json --report-out data\backtest\mm_paper_paperlive_20260627T131743_active_source_status_block.md --fills-out data\backtest\mm_paper_paperlive_20260627T131743_active_source_status_block_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\20260627T131743658156Z\run_summary.json --paper-score data\backtest\mm_paper_paperlive_20260627T131743_active_source_status_block.json --json-out data\backtest\mm_live_readiness_20260627T131743_paperlive_active_source_status_block.json --report-out data\backtest\mm_live_readiness_20260627T131743_paperlive_active_source_status_block.md
```

Result:

- Pre-run CLOB status was `RUNNING`, discovery sanity `PASS`, 0 consecutive errors, and explicit target-date strict CLOB audit returned `ok = true` for 12 markets at `2026-06-27T13:17:20Z`.
- Daily roll remained noncountable prior-target/post-settlement evidence: status `idle_process`, action `blocked_restart_required`, target date `2026-06-26`, expected target date `2026-06-27`, supervisor `SCHEDULED_WAIT`, start gate before `19:30` local, artifact liveness `STALE_HEARTBEAT_METADATA`, activity liveness `STALE_ACTIVITY`, and `current_counts_toward_live_forward_gate = false`.
- Observation trigger was fresh: state `RUNNING`, PID alive, watcher state `RUNNING`, watcher fresh true, and heartbeat age about 29.7 seconds.
- Snapshot tracker/source-status proof remained `BLOCK`: schema `source_status_proof_v0.2`, root cause `settlement_source_auth_failure`, reason `source status blocked: trading=12 live=12 promotion=12 unknown=0`, 12 blocked markets, 12 settlement-auth failure sources, optional provider status false, `optional provider source = false`, `optional provider source = false`, and provider status redacted true.
- Run folder `data/mm_runs/2026-06-27/20260627T131743658156Z`.
- `evidence_mode = active_day_live_forward`, but `counts_toward_live_forward_gate = false` because preflight blocked.
- Preflight `BLOCK`; first failing gate `source_status_degradation`.
- `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12}`; `observation_trigger_runtime_root_cause_counts = {}` and `model_freshness_failed_market_count = 0`.
- 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-trade-permission rows.
- Paper score `data/backtest/mm_paper_paperlive_20260627T131743_active_source_status_block.json`: paper freshness `PASS`, 132 quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, total reward score 0, actual payout evidence false, exchange economics `PASS`, paper-day collection gate `OPEN`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`.
- Readiness `data/backtest/mm_live_readiness_20260627T131743_paperlive_active_source_status_block.json`: `BLOCK` with 11 blockers, `live_capital_permission = false`, `current_counts_toward_live_forward_gate = false`, `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`, `source_status_degradation_failed_market_count = 12`, `source_status_blocker_root_cause_class = settlement_source_auth_failure`, optional provider status fields false/redacted, and 0 quote/live permissions.
- Verification after this probe: prompt-required core maker bundle passed (`118 passed, 5 subtests passed in 54.85s`); readiness/supervisor/observation tests passed (`56 passed in 3.57s`); exchange-economics drift recheck wrote `data/backtest/exchange_economics_drift_20260627_131743_recheck.json` with `PASS`.

Collection/source-status robustness recheck after upstreaming provider source diagnostics:

```powershell
.\venv\Scripts\python.exe -m pytest tests\collection\test_collection_robustness.py -q
```

Result:

```text
33 passed in 0.77s
```

Fleet/readiness source-status diagnostic recheck:

```powershell
.\venv\Scripts\python.exe -m pytest tests\reporting\test_fleet_observability.py tests\market\test_market_making_readiness.py -q
.\venv\Scripts\python.exe -m pytest tests\app\test_market_making_view.py tests\market\test_market_making_readiness.py -q
```

Result:

```text
61 passed in 1.11s
22 passed in 1.03s
```

source-status-aware source-status recovery recheck:

```powershell
.\venv\Scripts\python.exe -m pytest tests\reporting\test_fleet_observability.py tests\collection\test_collection_robustness.py tests\market\test_market_making_readiness.py tests\app\test_market_making_view.py tests\operations\test_schema_registry.py -q
```

Result:

```text
106 passed in 1.86s
```

Schema registry and fleet report recheck:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_schema_registry.py -q
.\venv\Scripts\python.exe -m weather.reporting.fleet.fleet_observability report --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md
```

Result:

```text
5 passed in 0.23s
Fleet observability: CRITICAL
source_status_proof.schema_version = source_status_proof_v0.2
source_status_proof.status = BLOCK
source_status_proof.root_cause_class = settlement_source_auth_failure
source_status_proof.summary.settlement_auth_failure_source_count = 12
source_status_proof.summary.source_status_blocked_market_count = 12
```

CLOB status:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
```

Result at check time:

- State `RUNNING`.
- Discovery sanity `PASS`.
- No error markets.
- Fresh CLOB loop output around the command time.

Strict CLOB audit:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict
```

Result:

- `ok: true`.
- 12 markets ok.
- 0 gaps over threshold.

Daily maker roll status:

```powershell
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
```

Result:

- Process alive.
- Artifacts current.
- Latest run folder at check time: `data/mm_runs/2026-06-26/20260626T231738340378Z`.
- Mode/evidence: `paper-live-forward` / `active_day_live_forward`.
- PID: 28644.
- Latest quote rows: 132.
- Latest quote-permission rows: 0.
- Activity liveness: `PASS`; artifact liveness: `PASS` at that active-window check. After later summary/diagnostic source edits, a temporary `STALE_CODE` backoff fired; after the `2026-06-27T02:18:37Z` retry window cleared, safe `ensure --force` reported current runtime identity and useful-write liveness passing.
- Latest status after the guarded recovery is PID 29180, supervisor state `RUNNING`, action `noop`, runtime identity matching current source, latest folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, useful-work `SKIPPED`, live-forward gate `BLOCK`, and `current_counts_toward_live_forward_gate = false`. Current countability remains blocked by post-settlement/noncountable evidence.

Standard paper report attempt:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper
```

Result:

- Timed out after 180 seconds in the first pass and after 304 seconds in the continuation pass.
- The timed-out `weather.market.mm_paper` processes were stopped.
- Existing `data/backtest/mm_paper_report.json` and `.md` were left unchanged.

Bounded active-day quote diagnostic from the running daily-roll tape:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-target-date 2026-06-26 --evidence-mode active_day_live_forward --latest-n 1 --skip-fill-simulation --skip-model-variants --json-out data\backtest\mm_paper_active_latest_20260626_quote_diag.json --report-out data\backtest\mm_paper_active_latest_20260626_quote_diag.md --fills-out data\backtest\mm_paper_active_latest_20260626_quote_diag_fills.csv --known-edge-out data\backtest\mm_known_edge_active_latest_20260626_quote_diag.json --known-edge-report-out data\backtest\mm_known_edge_active_latest_20260626_quote_diag.md --known-edge-coverage-map data\backtest\mm_known_edge_map.json
```

Result:

- Selected run folder: `data/mm_runs/2026-06-26/20260626T160337445814Z`.
- Quote-intent rows: 4,224.
- Quote-permission rows: 0.
- Quote uptime: 0.
- Quote legs: 0.
- Known-edge permission-blocked rows: 3,916.
- Stale-input rows: 308.
- Event-gate-suppressed rows: 44.
- Top known-edge states: 2,112 `promotion_block/no_quote/BLOCK`, 1,408 `missing_known_edge_record/no_quote/SHADOW`, and 704 `missing_known_edge_record/no_quote/BLOCK`.
- This was produced before `mm_quote_intent_v0.3`; exact `known_edge_match_*` columns were not yet available in the running loop tape. Missing-known-edge rows still clustered at `hour_utc = 15`, missing band-distance/taxonomy/book buckets, `regime = none`, and `source_freshness_state = all_fresh`.
- Diagnostic-only inferred dimensions now show likely active buckets such as `edge_lt_1c`, `edge_3c_8c`, `edge_ge_8c`, `bid_heavy`, `ask_heavy`, and `balanced`; the dry-run comparison against `data/backtest/mm_known_edge_map.json` found 0 inferred record matches and 2,112 inferred missing-record rows still missing. The nearest-record gap table points to mismatched stale paper-slice dimensions, and the blocker-overlap table is dominated by known-edge permission under `INFO_EVENT_CLEAR`, with smaller stale-input and WU-current widen intervals.
- Paper freshness: `PASS`; live-forward paper days in selected bounded scope: 1.
- This run skipped fill simulation and model-variant scoring, so it is quote-blocker evidence only.

v0.3 known-edge match-dimension probe:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once --runs-root "$env:TEMP\weather-mm-v03-probe" --run-id codex-v03-probe
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder "$env:TEMP\weather-mm-v03-probe\2026-06-26\codex-v03-probe" --json-out data\backtest\mm_paper_v03_probe_20260626_quote_diag.json --report-out data\backtest\mm_paper_v03_probe_20260626_quote_diag.md --fills-out data\backtest\mm_paper_v03_probe_20260626_quote_diag_fills.csv --known-edge-out data\backtest\mm_known_edge_v03_probe_20260626.json --known-edge-report-out data\backtest\mm_known_edge_v03_probe_20260626.md --skip-model-variants --skip-fill-simulation
```

Result:

- Shadow probe wrote `mm_quote_intent_v0.3` quote rows under `%TEMP%\weather-mm-v03-probe\2026-06-26\codex-v03-probe`.
- Preflight on the final rerun was `WARN` because moving model-freshness inputs aged while this pass was in progress.
- Row counts: 132 blocked rows, 0 quote-permission rows, 0 live-trade-permission rows.
- Blockers: 88 known-edge permission-blocked rows, 44 stale-input rows, and 0 event-gate-suppressed rows.
- Split: 55 `promotion_block/no_quote/NO_QUOTE_KNOWN_EDGE_PERMISSION`, 33 `missing_known_edge_record/no_quote/NO_QUOTE_KNOWN_EDGE_PERMISSION`, 33 `missing_known_edge_record/no_quote/NO_QUOTE_STALE_INPUT`, and 11 `promotion_block/no_quote/NO_QUOTE_STALE_INPUT`.
- Exact matcher fields are now present in the quote tape. The first inspected row had `known_edge_match_hour_utc = 16`, `known_edge_match_band_type = lte`, `known_edge_match_source_fresh = true`, `known_edge_match_source_freshness_state = all_fresh`, and blank band-distance, taxonomy, regime, and book-imbalance buckets.
- The diagnostic still found 0 inferred known-edge record matches and 66 inferred missing-record rows, so adding the diagnostic columns did not create quote permission.

Current-source v0.3 event-window shadow probe:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T165003338813Z --json-out data\backtest\mm_paper_shadow_20260626T165003338813Z_v03_current.json --report-out data\backtest\mm_paper_shadow_20260626T165003338813Z_v03_current.md --fills-out data\backtest\mm_paper_shadow_20260626T165003338813Z_v03_current_fills.csv --known-edge-out data\backtest\mm_known_edge_shadow_20260626T165003338813Z_v03_current.json --known-edge-report-out data\backtest\mm_known_edge_shadow_20260626T165003338813Z_v03_current.md --known-edge-coverage-map data\backtest\mm_known_edge_map.json --skip-model-variants
```

Result:

- Run folder: `data/mm_runs/2026-06-26/20260626T165003338813Z`.
- Preflight: `PASS`.
- Quote-intent rows: 132.
- Quote-permission rows: 0.
- Quote legs: 0.
- Exchange economics: `PASS`.
- Paper-score freshness: `NO_ACTIVE_DAY`; live-forward paper days in this single shadow selection: 0.
- Fill evidence completeness: `PASS`, only because no quote legs existed.
- Known-edge permission-blocked rows: 132.
- Stale-input rows: 0.
- Event-gate-suppressed rows: 132.
- Reason counts: 132 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Top blocker overlaps: 66 `promotion_block/no_quote/BLOCK`, 44 `missing_known_edge_record/no_quote/SHADOW`, and 22 `missing_known_edge_record/no_quote/BLOCK`, all under `INFO_EVENT_METAR_PRINT`.
- Inferred known-edge record matches: 0.
- Inferred known-edge record misses: 66.
- Exact missing dimensions remain missing in the quote tape: top rows had `hour_utc = 16`, `band_distance_bucket = (missing)`, `casebook_taxonomy = (missing)`, blank `known_edge_match_regime`, `source_freshness_state = all_fresh`, and `book_imbalance_bucket = (missing)`. The rendered no-quote output regime is `none`; that is not evidence that the matcher had a concrete input regime.

Interpretation: this is the cleanest current-source confirmation that the v0.3 schema and blocker report work on live active inputs. It landed inside a METAR pull window, so the event gate correctly suppressed every row. It is event-window/policy evidence, not permission to quote.

Current-source v0.3 WU/SWOB shadow probe:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T170013329405Z --json-out data\backtest\mm_paper_shadow_20260626T170013329405Z_v03_current.json --report-out data\backtest\mm_paper_shadow_20260626T170013329405Z_v03_current.md --fills-out data\backtest\mm_paper_shadow_20260626T170013329405Z_v03_current_fills.csv --known-edge-out data\backtest\mm_known_edge_shadow_20260626T170013329405Z_v03_current.json --known-edge-report-out data\backtest\mm_known_edge_shadow_20260626T170013329405Z_v03_current.md --known-edge-coverage-map data\backtest\mm_known_edge_map.json --skip-model-variants --skip-fill-simulation
```

Result:

- Run folder: `data/mm_runs/2026-06-26/20260626T170013329405Z`.
- Preflight: `WARN`; first failing gate was `model_freshness`.
- Quote-intent rows / quote-permission rows / quoted legs: 132 / 0 / 0.
- Known-edge permission-blocked rows: 121.
- Stale-input blocked rows: 11.
- Event-gate-suppressed rows: 11.
- Event-gate split: WU-current widen rows plus SWOB suppress rows.
- Inferred known-edge record matches / misses: 0 / 66.
- The Seattle model snapshot was stale at score time; the latest capture was `2026-06-26T16:44:44.875756+00:00` and model age was about 928.5 seconds.

Interpretation: this is current-source blocker evidence under a moving model-freshness failure. It does not weaken gates and does not support live readiness.

Historical current-source v0.3 active daily-roll diagnostic after supervisor recovery, superseded by the v0.8 active score below:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T170337841166Z --json-out data\backtest\mm_paper_active_20260626T170337841166Z_v03_current.json --report-out data\backtest\mm_paper_active_20260626T170337841166Z_v03_current.md --fills-out data\backtest\mm_paper_active_20260626T170337841166Z_v03_current_fills.csv --known-edge-out data\backtest\mm_known_edge_active_20260626T170337841166Z_v03_current.json --known-edge-report-out data\backtest\mm_known_edge_active_20260626T170337841166Z_v03_current.md --known-edge-coverage-map data\backtest\mm_known_edge_map.json --skip-model-variants --skip-fill-simulation
```

Initial result before the v0.8 diagnostic/action-item update:

- Run folder: `data/mm_runs/2026-06-26/20260626T170337841166Z`.
- Mode/evidence: `paper-live-forward` / `active_day_live_forward`.
- Daily-roll status at that check time: PID 14452, supervisor `RUNNING`, runtime identity matched current source, activity/artifact/useful-work liveness `PASS`, counts toward live-forward gate true.
- Quote-intent rows / quote-permission rows / quoted legs: 396 / 0 / 0.
- Known-edge permission-blocked rows: 385.
- Stale-input blocked rows: 11.
- Event-gate-suppressed rows: 0.
- Reason counts: 385 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_STALE_INPUT`.
- Inferred known-edge record matches / misses: 0 / 198.
- Exchange economics: `PASS`; paper freshness: `PASS`; live-forward paper days in selected bounded scope: 1.
- Fill evidence and model-variant scoring: `SKIPPED`, because this command was run as a quote-blocker diagnostic.

Interpretation: the stale-code recovery problem is resolved for the running paper loop, but the recovery landed after the active window and quote starvation remains unresolved for countable evidence. Later current-source noncountable diagnostics emitted narrow harvest-only permissions, but fill evidence remains blocked and no promotion-grade P&L evidence exists.

Current-source v0.8 action-item, hour-normalization, and current-countable-status diagnostic:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T231738340378Z --json-out data\backtest\mm_paper_active_20260626T231738340378Z_v08_current.json --report-out data\backtest\mm_paper_active_20260626T231738340378Z_v08_current.md --fills-out data\backtest\mm_paper_active_20260626T231738340378Z_v08_current_fills.csv --known-edge-out data\backtest\mm_known_edge_active_20260626T231738340378Z_v08_current.json --known-edge-report-out data\backtest\mm_known_edge_active_20260626T231738340378Z_v08_current.md --known-edge-coverage-map data\backtest\mm_known_edge_map.json --skip-model-variants --skip-fill-simulation
```

Result:

- Generated from active folder `data/mm_runs/2026-06-26/20260626T231738340378Z`.
- Quote-intent rows / quote-permission rows / quoted legs: 132 / 0 / 0.
- Known-edge permission-blocked rows: 132.
- Stale-input blocked rows: 0.
- Event-gate-suppressed rows: 0.
- Inferred known-edge record matches / misses: 0 / 66.
- Schema: `mm_quote_blocker_diagnostics_v0.8`.
- Top action items include `keep_blocked_until_promotion_gate_passes` for promotion-blocked no-quote records and `collect_countable_markouts_before_map_change` for missing active cells.
- The hour canonicalization removed false same-hour mismatches such as `17!=17:00Z`, but did not restore quote permission.

Backoff recheck from the same active folder after more ticks accumulated:

- Generated `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` and `.md`.
- Quote-intent rows / quote-permission rows / quoted legs: 4,807 / 0 / 0.
- Known-edge permission-blocked rows: 4,345.
- Stale-input blocked rows: 462.
- Event-gate-suppressed rows: 1,243.
- Inferred known-edge record matches / misses: 0 / 2,376.
- Top required-action buckets: 2,178 `keep_blocked_until_promotion_gate_passes`, 1,441 SHADOW `collect_countable_markouts_before_map_change`, and 726 BLOCK `collect_countable_markouts_before_map_change`.
- Fill simulation and model-variant scoring: `SKIPPED`.
- Live-forward paper days in this diagnostic: 1 from the selected active folder's paper evidence, but the running loop later recovered into post-settlement mode and does not add countable active-day evidence.

Current-source shadow verification after the hour-normalization fix:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T172330853600Z --json-out data\backtest\mm_paper_shadow_20260626T172330853600Z_hourfix.json --report-out data\backtest\mm_paper_shadow_20260626T172330853600Z_hourfix.md --fills-out data\backtest\mm_paper_shadow_20260626T172330853600Z_hourfix_fills.csv --known-edge-out data\backtest\mm_known_edge_shadow_20260626T172330853600Z_hourfix.json --known-edge-report-out data\backtest\mm_known_edge_shadow_20260626T172330853600Z_hourfix.md --known-edge-coverage-map data\backtest\mm_known_edge_map.json --skip-model-variants --skip-fill-simulation
```

Result:

- Run folder: `data/mm_runs/2026-06-26/20260626T172330853600Z`.
- Preflight: `WARN`, first failing gate `model_freshness`.
- Quote-intent rows / quote-permission rows / live-trade-permission rows: 132 / 0 / 0.
- Known-edge permission-blocked rows: 99.
- Stale-input blocked rows: 33.
- Event-gate-suppressed rows: 0.
- Inferred known-edge record matches / misses: 0 / 66.

Daily-roll status selector fix:

- A keyless shadow probe initially caused `market_making_daily_roll status` to report the shadow folder as the latest folder. `market_making_daily_roll.py` now filters artifact/activity liveness by expected `mode` and `evidence_mode`.
- After the fix, status reports latest active paper-live-forward folders for daily-roll liveness even when newer `shadow` folders exist.
- The daily-roll process recovered onto current source after transient `STALE_CODE` backoffs. After the guarded retry window cleared, safe `ensure --force` quarantined the stale folder and restarted the loop; latest status has PID 29180, fresh artifact writes, supervisor `SCHEDULED_WAIT` / `scheduled_wait`, and live-forward gate `BLOCK` with `current_counts_toward_live_forward_gate = false` because the evidence is post-settlement and noncountable.

Active-date metadata and exchange-economics refresh:

```powershell
.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json
.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-25 --markets all
.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-25 --platform polymarket_us --accept
```

Result:

- Location refresh: 51 locations, 119 events.
- Event metadata validation: `PASS` for target date `2026-06-25`.
- Exchange economics: `PASS`, accepted snapshot `xecon-036874d19e56c76f`.
- Exchange economics drift: `PASS`, `rescore_required = false`.

Runtime-identity snapshot guard check:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force
.\venv\Scripts\python.exe -m pytest tests\operations\test_runtime_identity.py tests\collection\test_loop_supervisor.py tests\collection\test_collection_robustness.py -q
```

Result:

- Initial forced snapshot returned `stale_code`.
- Root cause: `snapshot_store.py` compared scoped process identity against whole-tree current identity.
- Fix: `runtime_identity_guard` now uses `current_identity_for(process_identity)`.
- Tests after fix: 44 passed.
- Forced active-date snapshot then wrote successfully.

Maker useful-work runtime-identity check:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_market_making_run.py tests\operations\test_runtime_identity.py -q
```

Result:

- `market_making_run.runtime_identity_snapshot` now compares each supervisor against `current_identity_for(process)`.
- `current_identity_for(recorded)` now honors `recorded["repo_root"]` when no explicit root is passed.
- Regression coverage proves unrelated source changes do not stale a scoped loop identity, while recorded scoped-file changes still do.
- Test result: 36 passed.

Supervisor restart and daily-roll ensure:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --restart
.\venv\Scripts\python.exe -m weather.market.market_microstructure restart
.\venv\Scripts\python.exe -m weather.operations.observation_trigger restart
.\venv\Scripts\python.exe -m weather.operations.observation_trigger ensure
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll ensure
```

Result:

- Snapshot and CLOB loops restarted on current code.
- Observation trigger required `ensure` after the old writer lock cleared.
- Daily roll detected stale code, restarted, and quarantined the previous active run folder.
- The restarted daily roll is post-settlement evidence because local time was after the active evidence window.

Keyless active-date shadow tick:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-25 --budget-usdc 500 --mode shadow --markets all --once
```

Result:

```text
MM run: 0 quote rows, 132 no-quote rows, preflight PASS -> data/mm_runs/2026-06-25/20260626T014113607834Z
```

Future-date shadow drill:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once
```

Initial result before June 26 snapshot/CLOB folders were current:

```text
MM run: 0 quote rows, 12 no-quote rows, preflight BLOCK -> data/mm_runs/2026-06-26/20260626T013844852296Z
```

Later current-date shadow drill after CLOB/event/economics evidence existed:

```powershell
.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-26 --markets all
.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-26 --platform polymarket_us --accept
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once
```

Result:

```text
Event metadata validation: PASS
Exchange economics snapshot: PASS
Accepted baseline: PASS
MM run: 0 quote rows, 132 no-quote rows, preflight WARN -> data/mm_runs/2026-06-26/20260626T132648384687Z
```

Stable post-settlement quote-starvation drill:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-25 --budget-usdc 500 --mode paper-live-forward --markets all --once --evidence-mode post_settlement_evaluation
```

Result:

```text
MM run: 0 quote rows, 132 no-quote rows, preflight PASS -> data/mm_runs/2026-06-25/20260626T015818139432Z
MM run: 1 quote rows, 131 no-quote rows, preflight PASS -> data/mm_runs/2026-06-25/20260626T020148684548Z
```

## Current Paper Report

Source: `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`.

Summary:

- Quote-intent rows: 636,005.
- Quote legs: 71,836.
- Conservative fills: 44.
- Queue-estimated fill legs: 13,045.
- Paper score freshness: `PASS`.
- Live-forward paper days: 2.
- Locked policy params: false.
- Exchange economics status in report: `PASS`.
- Fill evidence completeness: `BLOCK`.
- Net P&L after fees/incentives: 2.641678 USDC.
- Spread capture: 2.2 USDC.
- Adverse selection at 30 minutes: -5.4025 USDC.
- Settlement P&L: 3.035 USDC.
- Maker fee-equivalent: 0.52443 USDC.
- Maker rebate estimate: 0.131101 USDC.
- Flattening fee estimate: 0.52443 USDC.
- Liquidity reward estimate: 0.

Interpretation:

- The bot has enough paper machinery to generate and score a large quote-intent corpus.
- Conservative fill count is still very small relative to quote legs.
- Queue simulation finds many possible fills, but promotion should continue to rely on conservative evidence until book/trade-size completeness improves.
- Reward-farming economics are not yet measured in the standard paper P&L because reward estimate remains zero.
- Negative 30-minute adverse selection means rebate/reward farming cannot be evaluated without markout controls.

## Fill Evidence Completeness

Source: `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`.

Current blockers:

- Missing size trade rows: 8,893.
- Missing book queue legs: 2,182.
- Missing trade-size queue legs: 26.
- Unresolved resting quote count: 0.

Largest missing-size event gaps:

- `highest-temperature-in-dallas-on-june-25-2026`: 7,594 trade rows, 1,976 missing size rows.
- `highest-temperature-in-denver-on-june-23-2026`: 2,506 trade rows, 1,562 missing size rows.
- `highest-temperature-in-denver-on-june-21-2026`: 2,236 trade rows, 1,518 missing size rows.
- `highest-temperature-in-austin-on-june-23-2026`: 2,301 trade rows, 1,391 missing size rows.
- `highest-temperature-in-atlanta-on-june-21-2026`: 1,914 trade rows, 1,322 missing size rows.
- `highest-temperature-in-houston-on-june-21-2026`: 1,668 trade rows, 1,124 missing size rows.

Largest missing-book queue slices:

- Los Angeles `70-71 F`, `02:00Z`, `YES_ASK`: 37 quote legs, 37 missing-book legs.
- Houston `88-89 F`, `02:00Z`, `YES_ASK`: 36 quote legs, 36 missing-book legs.
- Dallas `92-93 F`, `02:00Z`, `YES_ASK`: 36 quote legs, 36 missing-book legs.
- Denver `92-93 F`, `02:00Z`, `YES_ASK`: 35 quote legs, 35 missing-book legs.
- Miami `92-93 F`, `02:00Z`, `YES_ASK`: 34 quote legs, 34 missing-book legs.

Required before scale:

- Restore complete trade-size evidence for scored fills.
- Restore book snapshots needed to estimate queue position.
- Keep conservative fills as the promotion gate.
- Use queue-estimated fills only as a sensitivity check until queue evidence is complete.

## Known-Edge Map

Source: `data/backtest/mm_known_edge_full_standard_model_variants_release_quotes_20260626.json`.

Summary:

- Record count: 238.
- Permission counts:
  - `harvest_only`: 158.
  - `no_quote`: 68.
  - `edge_research`: 12.
- Promotion market count: 11.
- Paper fill count: 44.
- CLOB recon slice count: 21,560.
- CLOB overlay blocked taxonomies:
  - `market_lead`.
  - `book_liquidity_artifact`.
- CLOB overlay allowed taxonomy count: 0.

Interpretation:

- The model is not yet a general edge-quoting engine.
- Most allowed cells are harvest-only.
- Edge-research cells should generate shadow/paper evidence, not larger live size.
- No-quote cells are a feature, not a failure.

## Active-Date 2026-06-25 Shadow Run

Source: `data/mm_runs/2026-06-25/20260626T014113607834Z/run_summary.json`.

Summary:

- Mode: `shadow`.
- Budget: 500 USDC.
- Target date: `2026-06-25`.
- Preflight status: `PASS`.
- Row count: 132.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- Reason counts:
  - `NO_QUOTE_KNOWN_EDGE_PERMISSION = 121`.
  - `NO_QUOTE_MISSING_BOOK = 10`.
  - `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED = 1`.
- First failing gate: `policy`.
- First failing detail: `policy produced rows but no executable permissions`.
- Root cause class: `policy_no_edge`.
- Exchange economics status: `PASS`.
- Evidence mode: `operator_drill`.
- Counts toward live-forward gate: false.
- Useful-work liveness: `SKIPPED` because this was not all-market active-day paper-live-forward evidence.

Interpretation:

- This was a good safety drill: the active-date preflight passed, but the policy still emitted no quote permission.
- It does not advance live-forward evidence.
- The next useful simulation must separate true policy no-edge from missing-book and cadence-degraded rows.

## 2026-06-26 Shadow Drills

Source: `data/mm_runs/2026-06-26/20260626T013844852296Z/run_summary.json` and `preflight.json`.

Summary:

- Mode: `shadow`.
- Budget: 500 USDC.
- Target date: `2026-06-26`.
- Preflight status: `BLOCK`.
- Row count: 12.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- Reason counts: `NO_QUOTE_MISSING_PREFLIGHT = 12`.
- First failing gate: `active_event`.
- First failing detail: `no active current market rows`.
- Root cause class: `blocked_by_market_discovery`.
- Event metadata validation: `PASS`.
- Exchange economics status during the drill: `PASS`.
- All 12 markets blocked because snapshot/model rows, source-status rows, CLOB token rows, CLOB books/features, and reward metadata were missing for June 26.

Interpretation:

- Future-date metadata and economics can validate before the data loops have rolled.
- The preflight correctly blocks because active target-date market data does not exist yet.
- Do not use a future-date validation pass as active-day readiness proof.

Earlier current-date source: `data/mm_runs/2026-06-26/20260626T132648384687Z/run_summary.json`, `preflight.json`, and `data/backtest/mm_paper_shadow_20260626T132648384687Z_20260626.json`.

Summary:

- Event metadata validation: `PASS` for target date `2026-06-26`.
- CLOB status/audit at check time: loop `RUNNING`, strict audit `ok: true` across 12 June 26 markets.
- Exchange economics: `PASS`, accepted snapshot `xecon-036874d19e56c76f`, source hash `85aa79fefa832f611d43ca6aa47b7197`, verified for target date `2026-06-26`.
- Shadow run: 132 quote-intent rows, 0 quote-permission rows, 0 live-trade-permission rows.
- Preflight status: `WARN`.
- First failing gate: `model_freshness`.
- First failing detail: current model snapshot is stale or timestamp is missing.
- Per-market preflight: 11 markets `STALE` on `model_freshness`; Toronto `PASS` at preflight.
- No-quote reasons: 121 `NO_QUOTE_STALE_INPUT`, 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Bounded paper score: 132 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, paper freshness `NO_ACTIVE_DAY`.
- Fill evidence status: `PASS`, only because no quoted legs existed.
- Quote-blocker diagnostics: blocked fraction 1.0; top market reason was Toronto `NO_QUOTE_KNOWN_EDGE_PERMISSION` with 11 rows; every other market had 11 `NO_QUOTE_STALE_INPUT` rows.

Interpretation:

- The active blocker moved from missing June 26 market/CLOB/economics artifacts to stale model snapshots and known-edge permission.
- Bounded paper scoring now enforces the selected run target date for exchange economics. The regenerated bounded report shows economics target date `2026-06-26`, verified-for target date `2026-06-26`, and target-date match `true`.
- This is not countable live-forward evidence because it was a one-tick `shadow` operator drill and no quotes were emitted. The daily-roll liveness issue observed around that time was repaired later in the pass.

Latest current-date shadow drill after snapshot/model freshness recovered:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T134201734227Z --skip-model-variants --json-out data\backtest\mm_paper_shadow_20260626T134201734227Z_20260626.json --report-out data\backtest\mm_paper_shadow_20260626T134201734227Z_20260626.md --fills-out data\backtest\mm_paper_shadow_20260626T134201734227Z_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_shadow_20260626T134201734227Z_20260626.json --known-edge-report-out data\backtest\mm_known_edge_shadow_20260626T134201734227Z_20260626.md
```

Result:

```text
MM run: 9 quote rows, 123 no-quote rows, preflight PASS -> data/mm_runs/2026-06-26/20260626T134201734227Z
MM paper: 0 conservative fills, 0 queue-estimated fill legs, gate OPEN -> data/backtest/mm_paper_shadow_20260626T134201734227Z_20260626.md
```

Summary:

- Event metadata validation: `PASS` for target date `2026-06-26`.
- CLOB status/audit at check time: loop `RUNNING`, strict audit `ok: true` across 12 June 26 markets.
- Exchange economics: `PASS`, accepted snapshot `xecon-036874d19e56c76f`, verified for target date `2026-06-26`.
- Shadow run: 132 quote-intent rows, 9 quote-permission rows, 123 no-quote rows, 0 live-trade-permission rows.
- Preflight status: `PASS`.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`.
- Quoted rows: 9 Dallas harvest-only two-sided rows, 18 paper-posted legs, all capped by the early-hour guardrail to 1.75 shares per side.
- Budget reserved in shadow lifecycle: 15.3055 USDC of a 500 USDC drill budget.
- Bounded paper score: 132 quote rows, 18 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 12.26505, counterfactual reward 109.2508 USDC, paper freshness `NO_ACTIVE_DAY`.
- Fill evidence status: `BLOCK`, with 784 missing-size trade rows and 18 unresolved resting quotes because settlement evidence was unavailable for the active day.
- Queue companion status: 18 `no_touch` legs.

Interpretation:

- The model-freshness blocker cleared without weakening gates.
- The immediate no-quote blocker is now known-edge coverage, not stale model rows.
- The 9 Dallas quotes are useful shadow evidence but not countable live-forward evidence. They also are not promotion-grade because the run is a one-tick `shadow` drill, fill evidence is blocked, active-day settlement is unavailable, and the later repaired daily roll did not reproduce quote permissions in countable evidence.

## Active Daily-Roll Repair And Countable Paper Evidence

The daily roll was repaired during the active local evidence window after confirming CLOB strict audit passed and restarting current-code snapshot/observation loops:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --restart
.\venv\Scripts\python.exe -m weather.operations.observation_trigger restart
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode paper-live-forward --markets all --once
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll start --date 2026-06-26 --budget-usdc 500 --mode paper-live-forward --markets all --force
```

Results:

- Snapshot tracker restarted on current code.
- Observation trigger restarted; follow-up inspection found 0 blocked snapshot triggers.
- One-shot active paper run `data/mm_runs/2026-06-26/20260626T135512615163Z` emitted 132 no-quote rows, 0 quote-permission rows, and 0 live-trade-permission rows. It was not countable because Seattle model freshness was stale and the tick landed in a METAR pull window.
- Earlier continuous daily roll started for `2026-06-26`, PID 38032, `paper-live-forward`, evidence mode `active_day_live_forward`.
- `market_making_daily_roll status` then showed `pid_alive = true`, useful-work liveness `PASS`, disk status `PASS`, and `counts_toward_live_forward_gate = true`.

Point-in-time countable diagnostic run folder: `data/mm_runs/2026-06-26/20260626T135556165467Z`.

Run summary after three ticks:

- Mode: `paper-live-forward`.
- Evidence mode: `active_day_live_forward`.
- Counts toward live-forward gate: true.
- Preflight status: `PASS`.
- Quote-intent rows: 396.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- Cumulative live-trade-permission rows: 0.
- No-quote reasons: 396 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Event-gate actions: 396 `suppress`.
- Live-forward gate status: `PASS`.

Initial bounded score command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T135556165467Z --skip-model-variants --json-out data\backtest\mm_paper_daily_roll_20260626T135556165467Z_20260626.json --report-out data\backtest\mm_paper_daily_roll_20260626T135556165467Z_20260626.md --fills-out data\backtest\mm_paper_daily_roll_20260626T135556165467Z_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_daily_roll_20260626T135556165467Z_20260626.json --known-edge-report-out data\backtest\mm_known_edge_daily_roll_20260626T135556165467Z_20260626.md
```

Initial bounded score result:

- Quote-intent rows / quoted legs: 396 / 0.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Paper-score freshness: `PASS`.
- Exchange economics: `PASS`, target date `2026-06-26`.
- Fill evidence completeness: `PASS`, only because there were no quoted legs.
- Live-forward paper days in bounded selection: 1.
- Locked policy params: true.
- Reward score: 0.
- Suppressed opportunity cost: 96.6872 USDC.
- Quote blocker diagnostics: the previous pre-v0.3 bounded diagnostic had 3,916 known-edge permission-blocked rows, 308 stale-input rows, 44 event-gate suppressed rows, and 0 quote-permission rows. The latest current-source active backoff-recheck diagnostic has 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, and 0 quote-permission rows.

Latest follow-up bounded score command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T135556165467Z --skip-model-variants --json-out data\backtest\mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json --report-out data\backtest\mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.md --fills-out data\backtest\mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json --known-edge-report-out data\backtest\mm_known_edge_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.md
```

Latest follow-up result:

- Fixed bounded score artifact: `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`.
- Quote-intent rows / quoted legs: 4,092 / 0.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Paper-score freshness: `PASS`.
- Exchange economics: `PASS`, target date `2026-06-26`.
- Fill evidence completeness: `PASS`, only because there were no quoted legs.
- Live-forward paper days in bounded selection: 1.
- Locked policy params: true.
- Reward score: 0.
- Model-variant scoring: `SKIPPED (skip_model_variants)`.
- No-quote reasons: 4,070 `NO_QUOTE_KNOWN_EDGE_PERMISSION` and 22 `NO_QUOTE_STALE_INPUT`.
- Top known-edge states: 2,046 `promotion_block/no_quote/BLOCK`, 1,364 `missing_known_edge_record/no_quote/SHADOW`, and 682 `missing_known_edge_record/no_quote/BLOCK`.
- Top missing known-edge dimensions: active rows at `hour_utc = 14` or `13`, `band_distance_bucket = (missing)`, `casebook_taxonomy = (missing)`, `regime = none`, `source_freshness_state = all_fresh`, and `book_imbalance_bucket = (missing)`.

Historical June 26 moving-folder validation check after snapshot-loop recovery:

- At that historical check, snapshot tracker status was `RUNNING`, runtime code was current, heartbeat and latest snapshot age were fresh, and source-status proof had 0 blocked markets. That June 26 status still had `action_required = 12` because same-day snapshot cadence and early-hour coverage proofs were `BLOCK` across the fleet due historical gaps. This is superseded for June 27 by the current source-status proof `BLOCK` / `settlement_source_auth_failure` state.
- Latest daily-roll status after guarded recovery is `started`, PID 29180, target date `2026-06-26`, mode `paper-live-forward`, evidence mode `post_settlement_evaluation`, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, `current_counts_toward_live_forward_gate = false`, supervisor state `RUNNING`, supervisor action `noop`, runtime identity matching current source, latest run folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, and latest tick rows 132. Current operational blocker: post-settlement noncountability; current scored-row blockers: policy/known-edge, missing/stale books, and fill-evidence blockage.
- The current accepted `data/backtest/mm_known_edge_map.json` has 17 records and does contain a broad Dallas `harvest_only` key. Latest Dallas rows therefore mostly fail closed on missing books, information-event windows, stale input, and cadence degradation rather than known-edge permission. The generated candidate map is diagnostic only and should not be promoted without countable markouts.

Interpretation:

- The daily-roll process and snapshot loop can be healthy while active-row quote permission remains zero.
- Active-day paper artifacts exist, but current operational countability is blocked because the running process is stale-code and the recovered run is post-settlement. The latest regenerated current-code offline score contains 34 quote legs, 0 conservative fills, 2 queue-estimated fill legs, reward score 89.72025, CLOB-calibrated competitor-score diagnostics, and no promotion evidence because fill evidence remains `BLOCK`.
- The current blocker is active-row known-edge map coverage and promotion state, with a smaller stale-input contribution during the snapshot-loop interruption. This remains a live NO-GO.

## Stable Post-Settlement Quote-Starvation Drill

Source: `data/mm_runs/2026-06-25/20260626T020148684548Z`.

Summary:

- Mode: `paper-live-forward`.
- Evidence mode: `post_settlement_evaluation`.
- Target date: `2026-06-25`.
- Preflight status: `PASS`.
- Event metadata status: `PASS`.
- Exchange economics status: `PASS`.
- Markets: 12.
- Blocked markets: 0.
- Stale markets: 0.
- Row count: 132.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Root cause class: `trading_permissions_emitted`.
- Useful-work liveness: `SKIPPED`, because this was not active-day live-forward evidence.

Reason counts:

- `NO_QUOTE_KNOWN_EDGE_PERMISSION`: 121.
- `NO_QUOTE_MISSING_BOOK`: 10.
- `QUOTE_HARVEST_MID`: 1.

Market-level interpretation:

- Missing known-edge records: Atlanta, Austin, Denver, Houston, Toronto.
- Promotion blocks: Chicago, Los Angeles, Miami, NYC, San Francisco, Seattle.
- Dallas: one `92-93 F` two-sided harvest quote, 10 missing-book no-quote rows, known-edge state `awaiting_paper_markouts`, promotion state `SHADOW`.
- The quoted Dallas row had expected reward score 1.0, expected rebate value 0.0, quote risk 4.9525 USDC, bid 0.9895 for 5 contracts, and ask 0.999 for 5 contracts.
- Live-trade permission stayed false.

Interpretation:

- This is the cleanest current evidence: infrastructure preflight passes and one non-countable harvest quote can appear after information-event suppression clears.
- The next simulation should explain known-edge coverage, promotion blockers, Dallas missing-book rows, and whether the one harvest quote survives active-window paper markout scoring.

## One-Run Paper Score And Known-Edge Coverage

Source: `data/backtest/mm_paper_quote_starvation_20260626T020148684548Z.json`, `data/backtest/mm_known_edge_quote_starvation_20260626T020148684548Z.json`, and `docs/research/MM_KNOWN_EDGE_COVERAGE_2026-06-26.md`.

Command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z --json-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.json --report-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.md --fills-out data\backtest\mm_paper_quote_starvation_fills_20260626T020148684548Z.csv --known-edge-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.json --known-edge-report-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.md
```

Result:

- Completed for the fixed post-settlement run.
- Candidate run folders: 1.
- Quote-intent rows: 132.
- Quote legs: 2.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Gate status: `OPEN`.
- Paper score freshness: `NO_ACTIVE_DAY`.
- Fill evidence status: `BLOCK`.
- Missing size trade rows: 1,944.
- Missing book queue legs: 1.
- P&L, reward, and rebate estimates: 0.
- One-run known-edge map: 217 records, with 177 `harvest_only`, 37 `no_quote`, and 3 `edge_research`.

Interpretation:

- The bounded scorer works and is useful for quote-starvation diagnosis.
- The result is diagnostic only because it uses one post-settlement run and does not cover countable active-day live-forward evidence.
- The full `weather.market.mm_paper` path still needs a bounded or incremental mode before it is reliable for daily operational preparation.
- Known-edge coverage is now the main research target: five markets lack records, six markets are promotion-blocked, and Dallas has one quoted band plus ten missing-book bands.

## Bounded Paper Scoring Mode

Code update:

- `src/weather/market/mm_paper.py` now supports bounded run-folder selection with `--target-date` / `--run-target-date`, `--evidence-mode`, and `--latest-n`.
- `src/weather/market/mm_paper_reports.py` now renders run-folder selection mode and warning in the paper report summary.
- `src/weather/market/mm_paper.py` now adds `reward_score_diagnostics` that scores quoted legs under the accepted Polymarket US discount-factor/ticks formula.
- `src/weather/market/mm_paper.py` now computes counterfactual score share, payout, and market/band/hour/side score attribution under explicit assumptions.
- `src/weather/market/mm_paper_reports.py` now renders reward-score and counterfactual payout diagnostics separately from reward-dollar P&L.
- `src/weather/market/mm_paper.py` now supports `--skip-model-variants` for faster operational diagnostics. Skipped reports mark model-variant bakeoff as `SKIPPED (skip_model_variants)` and are not model-promotion evidence.
- `src/weather/market/mm_paper.py` now supports `--skip-fill-simulation` for full-corpus quote/no-quote/reward diagnostics when promotion-grade fill simulation is too slow. Skipped reports mark fill evidence as `SKIPPED (skip_fill_simulation)`.
- `src/weather/market/mm_paper_scoring.py` now caches per-token timestamp indexes for trade, book, and mark rows so repeated queue/fill lookups do not rebuild the same time arrays.
- `src/weather/market/mm_paper.py` and `src/weather/market/mm_paper_reports.py` now emit quote-blocker diagnostics by market/reason, known-edge state, event-gate state, and blocked cell.
- `tests/market/test_mm_paper.py` covers latest-N selection, target-date/evidence-mode filtering, Polymarket US reward-score diagnostics, counterfactual payout/share math, skip-model-variant report disclosure, skip-fill-simulation report disclosure, quote-blocker report disclosure, and missing-known-edge dimension rendering.

Validation:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py tests\operations\test_market_making_daily_roll.py -q
```

Result:

```text
127 passed, 5 subtests passed in 56.43s
```

Bounded smoke command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --target-date 2026-06-25 --evidence-mode post_settlement_evaluation --latest-n 1 --json-out data\backtest\mm_paper_bounded_latest_postsettlement_20260626.json --report-out data\backtest\mm_paper_bounded_latest_postsettlement_20260626.md --fills-out data\backtest\mm_paper_bounded_latest_postsettlement_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_bounded_latest_postsettlement_20260626.json --known-edge-report-out data\backtest\mm_known_edge_bounded_latest_postsettlement_20260626.md
```

Bounded smoke result:

- Selection mode: `bounded`.
- Selection warning: `diagnostic_selection_not_full_corpus`.
- Available run folders before selection: 37.
- Selected folder: `data/mm_runs/2026-06-25/20260626T015632370043Z`.
- Quote-intent rows: 4,488.
- Quote legs: 52.
- Conservative fills: 5.
- Queue-estimated fill legs: 0.
- Paper score freshness: `NO_ACTIVE_DAY`.
- Fill evidence status: `BLOCK`.
- Net P&L after fees/incentives: -0.00974 USDC.
- Liquidity reward estimate: 0.
- Bounded known-edge map: 217 records, 177 `harvest_only`, 37 `no_quote`, 3 `edge_research`.

Reward-score diagnostics from the bounded smoke report:

- Status: `PASS`.
- Score basis: `polymarket_us_discount_factor_ticks_from_best`.
- Discount factor: 0.30.
- Tick size: 0.005.
- Minimum order size: 0.01.
- Target size: 10,000 contracts.
- Campaign pool: 1,000 USDC.
- Assumed competitor score: 100.
- Quote-permission rows: 26.
- Quoted legs: 52.
- Positive-score legs: 52.
- Unscored legs: 0.
- Total reward score: 141.7.
- Score / target-size: 0.01417.
- Target size met: false.
- Counterfactual score share: 0.58626396.
- Counterfactual reward: 586.263964 USDC.
- Actual payout evidence: false.
- Attribution: Dallas `92-93 F` ask side contributed 130.0 score and 537.856847 counterfactual USDC; Dallas `92-93 F` bid side contributed 11.7 score and 48.407116 counterfactual USDC.
- No-quote reasons: 3,850 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 308 `NO_QUOTE_STALE_INPUT`, 270 `NO_QUOTE_MISSING_BOOK`, 33 `NO_QUOTE_INFORMATION_EVENT`, and 1 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`.

Skip-model-variants bounded smoke command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --target-date 2026-06-25 --evidence-mode post_settlement_evaluation --latest-n 1 --skip-model-variants --json-out data\backtest\mm_paper_bounded_latest_postsettlement_skip_variants_20260626.json --report-out data\backtest\mm_paper_bounded_latest_postsettlement_skip_variants_20260626.md --fills-out data\backtest\mm_paper_bounded_latest_postsettlement_skip_variants_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_bounded_latest_postsettlement_skip_variants_20260626.json --known-edge-report-out data\backtest\mm_known_edge_bounded_latest_postsettlement_skip_variants_20260626.md
```

Skip-model-variants result at smoke-check time:

- Runtime: 3.9 seconds.
- Selected folder: `data/mm_runs/2026-06-25/20260626T015632370043Z`.
- Selection mode/warning: `bounded` / `diagnostic_selection_not_full_corpus`.
- Quote-intent rows / quoted legs: 5,148 / 62.
- Model-variant quote-intent rows / quoted legs: 0 / 0.
- Model-variant scoring: `SKIPPED (skip_model_variants)`.
- Conservative fills: 7.
- Queue-estimated fill legs: 0.
- Paper score freshness: `NO_ACTIVE_DAY`.
- Fill evidence status: `BLOCK`.
- Net P&L after fees/incentives: -0.013636 USDC.
- Liquidity reward estimate: 0.
- Reward score: 168.95.
- Counterfactual reward: 628.183677 USDC.

Full-corpus summary-only command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --skip-fill-simulation --skip-model-variants --json-out data\backtest\mm_paper_full_summary_only_20260626.json --report-out data\backtest\mm_paper_full_summary_only_20260626.md --fills-out data\backtest\mm_paper_full_summary_only_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_full_summary_only_20260626.json --known-edge-report-out data\backtest\mm_known_edge_full_summary_only_20260626.md
```

Full-corpus summary-only result:

- Runtime: about 176 seconds.
- Run folders: 36 included, 1 excluded, 37 available before selection.
- Quote-intent rows / quoted legs: 628,481 / 71,828.
- Fill simulation: `SKIPPED (skip_fill_simulation)`.
- Fill evidence completeness: `SKIPPED`; blocker `fill_simulation_skipped`.
- Model-variant scoring: `SKIPPED (skip_model_variants)`.
- Paper score freshness: `PASS`, latest completed active day `2026-06-25`, latest covered active day `2026-06-25`.
- Exchange economics: `PASS`, snapshot `xecon-036874d19e56c76f`.
- Quote-permission rows: 35,914.
- No-quote rows: 592,567.
- Positive reward-score legs: 71,828.
- Total reward score: 165,800.676275.
- Counterfactual reward share: 0.99939723.
- Counterfactual reward: 999.39723 USDC under campaign-pool 1,000 and competitor-score 100 assumptions.
- The summary-only known-edge map had 17 records: 7 `harvest_only`, 7 `no_quote`, and 3 `edge_research`. This map is diagnostic only and must not replace the standard known-edge map.

Promotion-grade full-corpus retry after time-index optimization:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --skip-model-variants --json-out data\backtest\mm_paper_full_promotion_grade_skip_variants_20260626.json --report-out data\backtest\mm_paper_full_promotion_grade_skip_variants_20260626.md --fills-out data\backtest\mm_paper_full_promotion_grade_skip_variants_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_full_promotion_grade_skip_variants_20260626.json --known-edge-report-out data\backtest\mm_known_edge_full_promotion_grade_skip_variants_20260626.md
```

Result:

- Timed out after 300 seconds.
- No output files were written for the `full_promotion_grade_skip_variants` label.
- Interpretation at that point: cached per-token timestamp indexes were useful and covered by tests, but the full-corpus fill/queue/markout path still needed memory/runtime work.

Promotion-grade full-corpus retry after streamed casebook loading and compact quote legs:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --skip-model-variants --json-out data\backtest\mm_paper_full_promotion_skip_variants_compact_legs_20260626.json --report-out data\backtest\mm_paper_full_promotion_skip_variants_compact_legs_20260626.md --fills-out data\backtest\mm_paper_full_promotion_skip_variants_compact_legs_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_full_promotion_skip_variants_compact_legs_20260626.json --known-edge-report-out data\backtest\mm_known_edge_full_promotion_skip_variants_compact_legs_20260626.md
```

Result:

- Output files were written for the `compact_legs` label.
- Quote-intent rows / quoted legs: 636,005 / 71,836.
- Conservative fills: 44.
- Queue-estimated fill legs: 13,045.
- Paper-score freshness: `PASS`.
- Fill evidence completeness: `BLOCK`.
- Fill blockers: `missing_size_trade_rows`, `missing_book_queue_legs`, `missing_trade_size_queue_legs`, and `unresolved_resting_quotes`.
- Model-variant scoring: `SKIPPED (skip_model_variants)`.
- Reward score: 165,822.476275.
- Counterfactual reward: 999.397309 USDC under campaign-pool 1,000 and competitor-score 100 assumptions.
- Net P&L after fees/incentives: 2.609178 USDC.
- Interpretation: full-corpus fill/queue/markout scoring can now produce a model-variant-skipped diagnostic report on current artifacts, but it still blocks promotion because fill evidence is incomplete and model-variant evidence is intentionally omitted.

Standard full-corpus retry after releasing quote rows before fill simulation:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --json-out data\backtest\mm_paper_full_standard_model_variants_release_quotes_20260626.json --report-out data\backtest\mm_paper_full_standard_model_variants_release_quotes_20260626.md --fills-out data\backtest\mm_paper_full_standard_model_variants_release_quotes_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_full_standard_model_variants_release_quotes_20260626.json --known-edge-report-out data\backtest\mm_known_edge_full_standard_model_variants_release_quotes_20260626.md
```

Result:

- Runtime: about 4.4 minutes.
- Output files were written for the `release_quotes` label.
- Quote-intent rows / quoted legs: 636,005 / 71,836.
- Conservative fills: 44.
- Queue-estimated fill legs: 13,045.
- Paper-score freshness: `PASS`.
- Fill evidence completeness: `BLOCK`.
- Fill blockers: `missing_size_trade_rows`, `missing_book_queue_legs`, and `missing_trade_size_queue_legs`.
- Fill blocker detail: 8,893 missing-size trade rows, 2,182 missing-book queue legs, 26 missing-trade-size queue legs, and 0 unresolved resting quotes.
- The regenerated markdown report includes `Top Event Data Gaps` and `Top Incomplete Market Data Slices` so the next data-quality pass can target exact event slugs and market/hour/range/side cells.
- Model-variant scoring: `PASS`.
- Model-variant quote-intent rows / quoted legs: 39,534 / 264.
- Model-variant conservative fills: 32.
- Model-variant promotion gate: `BLOCK`, method `clustered_market_day_bootstrap`.
- Model-variant promotion blockers: broad 12-market pairs have only 1 independent target day and fail positive lower-bound net-P&L delta; one-market pairs also miss independent cluster/market requirements.
- Reward score: 165,822.476275.
- Counterfactual reward: 999.397309 USDC under campaign-pool 1,000 and competitor-score 100 assumptions.
- Net P&L after fees/incentives: 2.641678 USDC.
- Interpretation: the scorer now produces standard full-corpus model-variant evidence, but the result is still a live NO-GO because fill evidence and model promotion are blocked.

Bounded latest active-day promotion-grade command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --target-date 2026-06-25 --evidence-mode active_day_live_forward --latest-n 1 --skip-model-variants --json-out data\backtest\mm_paper_bounded_latest_active_skip_variants_20260626.json --report-out data\backtest\mm_paper_bounded_latest_active_skip_variants_20260626.md --fills-out data\backtest\mm_paper_bounded_latest_active_skip_variants_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_bounded_latest_active_skip_variants_20260626.json --known-edge-report-out data\backtest\mm_known_edge_bounded_latest_active_skip_variants_20260626.md
```

Result:

- Runtime: 2.2 seconds after quote-blocker diagnostics were added.
- Selected folder: `data/mm_runs/2026-06-25/20260626T015448206993Z`.
- Selection mode/warning: `bounded` / `diagnostic_selection_not_full_corpus`.
- Quote-intent rows / quoted legs: 132 / 0.
- Quote-permission rows: 0.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`.
- Quote-blocker diagnostics:
  - Blocked rows: 132, blocked fraction 1.0.
  - Known-edge permission-blocked rows: 121.
  - Known-edge state rows: 132.
  - Known-edge allowed=false rows: 132.
  - Harvest-only rows suppressed by the event gate: 11.
  - Event-gate suppressed rows: 132.
  - Top known-edge states: 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, 11 `awaiting_paper_markouts/harvest_only/SHADOW`.
  - Top event-gate state: 132 `PULL/suppress/INFO_EVENT_METAR_PRINT`.
  - Interpretation: blockers overlap. The METAR event gate suppressed every row, while the emitted reason codes still show known-edge/promotion blockers for 121 rows and information-event blocking for 11 rows.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Fill evidence completeness: `PASS`, because there were no quoted legs to evaluate.
- Paper score freshness: `PASS`; latest completed and covered active day `2026-06-25`.
- Exchange economics: `PASS`, snapshot `xecon-036874d19e56c76f`.
- Reward score: 0.
- Model-variant scoring: `SKIPPED (skip_model_variants)`.
- Interpretation: this is the clean active-day blocker. The active run was countable for freshness, but it produced no quote permissions, so it provides no harvest/reward/fill evidence.

Interpretation:

- Bounded scoring is now available for quick diagnostics and active-window follow-up.
- It is not a substitute for full-corpus paper scoring unless the selected folders are exactly the intended promotion evidence set.
- Bounded active-day scoring can be promotion-grade for its selected run, but the latest active-day run has zero quote permissions and therefore cannot advance reward farming readiness.
- The latest bounded post-settlement run had positive reward score and counterfactual reward share under explicit assumptions, but still negative net after fees/incentives, zero actual reward-dollar estimate, no active-day freshness, and fill evidence `BLOCK`.
- The reward-score diagnostic separates score/share opportunity from actual reward P&L; it does not prove payout, target-size eligibility, active-window eligibility, or live eligibility.
- `--skip-model-variants` makes reward/readiness smoke checks faster, but it deliberately omits model-variant promotion evidence.
- `--skip-fill-simulation` makes full-corpus quote and reward-score diagnostics possible within a few minutes, but it deliberately omits conservative fills, queue companion fills, markouts, P&L, and fill-evidence promotion gates.

## Event Metadata Validation

Source: `data/backtest/event_metadata_validation.json`.

Summary:

- Status: `PASS`.
- Target date: `2026-06-25`.
- Generated at: `2026-06-26T01:41:08.010146+00:00`.
- Market count: 12.
- Same-day remediation command recorded by artifact:
  `python -m weather.operations.location_config_refresh --locations config/locations.json --event-metadata config/location_market_events.json`

Interpretation:

- Active-date metadata is no longer the current blocker for June 25.
- Future-date validation should use target-specific outputs or be rerun only when the daily roll has switched, so default active-date artifacts do not get overwritten unnecessarily.

## Exchange Economics Snapshot

Source: `data/backtest/exchange_economics_snapshot.json`.

Current snapshot:

- Platform: `polymarket_us`.
- Platform surface: `retail_api_and_exchange_clob`.
- Snapshot id: `xecon-036874d19e56c76f`.
- Verified for target date: `2026-06-26`.
- Source hash: `85aa79fefa832f611d43ca6aa47b7197`.
- Effective date: `2026-04-03`.
- Taker fee rate: 0.05.
- Maker fee rate: 0.0.
- Flattening fee rate: 0.05.
- Maker rebate share: 0.25.
- Reward formula: US score formula based on discount factor, ticks from best price, and order size.
- Tick size: 0.005.
- Minimum order size: 0.01.
- Drift report: `data/backtest/exchange_economics_drift.json` is `PASS`, `rescore_required = false`.

Interpretation:

- Economics assumptions are internally plausible for Polymarket US.
- The default snapshot is current for target date `2026-06-26` after the continuation publish/accept.
- Official US docs were rechecked again on 2026-06-26. No material core fee/reward formula drift was found versus the accepted snapshot, but the temporary high-volume taker rebate on the US fee page remains excluded from small-scale economics until account eligibility and payout proof exist. Live API readiness also remains outside the economics proof.
- `weather.market.mm_paper` now falls back to the selected run's single target date when a bounded report has no completed active-day freshness date; this keeps exchange-economics target-date matching active for shadow/operator-drill reports.
- A bounded active-day daily-roll paper report has now been generated, but the run folder is still moving. Regenerate the bounded report before interpreting any later quote permissions, and use the timestamped report artifact as the fixed evidence point.

## Continuation Status And Platform API Recheck

- The regenerated 071559 selected-subset readiness artifact now carries paper-side quote-blocker diagnostics into its Summary: `paper_quote_blocked_rows = 33`, `paper_quote_blocked_fraction = 1.0`, `paper_quote_blocker_reason_counts = {NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED: 25, NO_QUOTE_MISSING_BOOK: 8}`, `paper_quote_blocker_event_gate_suppressed_rows = 0`, and `paper_quote_blocker_stale_input_rows = 0`. This confirms the no-quote state is policy/data starvation, not event-gate suppression or stale model/book input in the final tick.

Safe commands rerun during the continuation:

```powershell
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_exchange.py -q
```

Results:

- Earlier daily-roll checks did show `2026-06-25` post-settlement artifacts and later `pid_missing` / `blocked_restart_required`; that state was repaired during the active June 26 window.
- A later snapshot-loop liveness regression briefly made the moving daily-roll folder fail freshness/preflight. At that point the snapshot tracker was `RUNNING` with current runtime code and fresh heartbeat/snapshot age, but same-day snapshot cadence and early-hour coverage proofs were `BLOCK` because of historical gaps. The latest snapshot check now has runtime identity current, capture liveness `OK`, and snapshot cadence `PASS`, while early-hour coverage and source-status still block.
- Current daily-roll status after guarded recovery is `started`, PID 29180, target date `2026-06-26`, mode `paper-live-forward`, evidence mode `post_settlement_evaluation`, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, `current_counts_toward_live_forward_gate = false`, supervisor state `RUNNING`, supervisor action `noop`, runtime identity matching current source, latest run folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, and latest tick rows 132. Current operational blocker: post-settlement noncountability; current scored-row blockers: policy/known-edge, missing/stale books, and fill-evidence blockage.
- Diagnostic daily-roll folder `data/mm_runs/2026-06-26/20260626T135556165467Z` was still being appended when scored, so use the fixed bounded diagnostic artifact for point-in-time counts.
- The previous fixed bounded score for that folder is `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`: 4,092 quote rows, 0 quote legs, reward score 0, no fills, 4,070 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 22 `NO_QUOTE_STALE_INPUT` rows. Treat that artifact as a point-in-time score, not the current full contents of the moving run folder.
- The current accepted known-edge map has 17 records and includes a broad Dallas `harvest_only` row. Latest Dallas rows are therefore mostly blocked by missing books, event gates, stale input, and cadence degradation rather than known-edge permission. The generated 217-record candidate map is diagnostic only and should not replace the accepted map without countable markouts.
- Previous bounded quote diagnostic from the pre-v0.3 active daily-roll tape: `data/backtest/mm_paper_active_latest_20260626_quote_diag.json`, from `data/mm_runs/2026-06-26/20260626T160337445814Z`, scored 4,224 accumulated quote rows, 0 quote legs, 0 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, 3,916 known-edge permission-blocked rows, 308 stale-input rows, 44 event-gate-suppressed rows, and `mm_quote_blocker_diagnostics_v0.7`. Later status checks on the moving active folder alternated with snapshot/model freshness; the latest recovered check is live-forward countable again. The v0.3 probe confirms exact match fields are now written for future quote tapes, but the diagnostic still found 0 inferred known-edge record matches, so adding diagnostic buckets alone does not restore quote permission. This diagnostic skipped fill simulation and model-variant scoring, so it is quote-blocker evidence only.
- Latest current-source active daily-roll diagnostic: `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json`, from `data/mm_runs/2026-06-26/20260626T231738340378Z`, scored 4,807 quote rows, 0 quote legs, 0 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, and 0 inferred known-edge record matches. This diagnostic skipped fill simulation and model-variant scoring, so it is quote-blocker evidence only.
- Recovered post-settlement current-source diagnostic: `data/backtest/mm_paper_postsettlement_recovered_20260627T001837640455Z_v08.json`, from `data/mm_runs/2026-06-26/20260627T001837640455Z`, scored 264 quote rows, 0 quote legs, 0 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, paper freshness `NO_ACTIVE_DAY`, 264 known-edge permission-blocked rows, 0 stale-input rows, 11 event-gate-suppressed rows, and 0 inferred known-edge record matches. This proves runtime recovery, but it is not countable live-forward evidence.
- June 27 next-date probe:
  - `.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-27 --markets all --json-out data\backtest\event_metadata_validation_20260627_probe.json --report-out data\backtest\event_metadata_validation_20260627_probe.md` passed.
  - Standard event metadata was then restored to target date `2026-06-26` with `weather.operations.event_metadata_validation --target-date 2026-06-26 --markets all`.
  - `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once` wrote refreshed artifact `data/mm_runs/2026-06-27/20260627T003709708211Z`: 12 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, preflight `BLOCK`, first failing gate `active_event`, first detail `no active current market rows`, root cause `blocked_by_market_discovery`.
  - The pre-refresh run summary includes aggregate `preflight_diagnostics`: all 12 markets were blocked by empty `clob_tokens.csv`, default event-metadata target-date mismatch, exchange-economics target-date mismatch, missing current snapshot/model rows, missing source-status rows, missing CLOB books/features, missing token/condition ids, missing reward metadata, and no active current market rows.
  - `data/backtest/mm_paper_shadow_20260627T003709708211Z_nextdate_probe.json` scored 12 quote rows, 0 quote legs, 0 quote-permission rows, paper freshness `NO_ACTIVE_DAY`, fill evidence `SKIPPED`, and exchange-economics gate `BLOCK` because target-date proof is still for June 26.
- CLOB loop state was `RUNNING`.
- Strict CLOB audit was `ok: true` across 12 markets, with post-restart startup gaps ignored by policy.
- Exchange adapter/report tests passed after latency-stopgap classification, US private WebSocket fixture normalization, and stricter cancel-all proof: 15 tests.
- Latest focused maker/operations suite: `.\venv\Scripts\python.exe -m pytest tests\operations\test_market_making_daily_roll.py tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q` passed with 123 tests and 5 subtests.
- Latest syntax check: `.\venv\Scripts\python.exe -m py_compile src\weather\operations\market_making_daily_roll.py src\weather\market\market_making_run.py src\weather\market\mm_policy.py src\weather\market\mm_paper.py src\weather\market\mm_paper_reports.py` passed.
- Latest CLOB status check at `2026-06-27T02:10Z`: state `RUNNING`, discovery sanity `PASS`, heartbeat age about 20.9s, last books age about 20.9s, no error markets, 12 markets with current token/book captures.
- Latest strict CLOB audit at `2026-06-27T02:10:06Z`: `ok: true` across all 12 markets, with post-restart startup gaps ignored by policy and 0 counted gaps over threshold.
- Latest bounded post-settlement score for the moving paper-live-forward folder: `data/backtest/mm_paper_postsettlement_latest_20260627T004446Z_skipfill.json` selected `data/mm_runs/2026-06-26/20260627T001837640455Z` and scored 2,772 quote rows, 110 quote legs, 55 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS`, gate `OPEN`, paper freshness `NO_ACTIVE_DAY`, fill evidence `SKIPPED`, reward score 255.80375, and counterfactual reward 718.946189 USDC. This is diagnostic-only because it is explicit one-folder, post-settlement, and skipped fill/model-variant scoring.
- Current-source keyless shadow check during `INFO_EVENT_METAR_PRINT`: `data/mm_runs/2026-06-26/20260627T004704070519Z` passed preflight across all 12 markets and wrote 132 quote rows, 0 quote-permission rows, 0 live-trade-permission rows, reason split `NO_QUOTE_KNOWN_EDGE_PERMISSION = 88` and `NO_QUOTE_INFORMATION_EVENT = 44`, and live-forward gate `BLOCK`. Its score `data/backtest/mm_paper_shadow_20260627T004704070519Z_current_source.json` has 88 known-edge blockers, 132 event-gate-suppressed rows during `INFO_EVENT_METAR_PRINT`, 0 stale-input blockers, 0 inferred known-edge record matches, 11 inferred misses, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, fill evidence `SKIPPED`, and reward score 0.
- Latest current-source keyless shadow check after the event gate cleared: `data/mm_runs/2026-06-26/20260627T010734537264Z` passed preflight across all 12 markets and wrote 132 quote rows, 6 harvest-only quote-permission rows, 0 live-trade-permission rows, reason split `NO_QUOTE_KNOWN_EDGE_PERMISSION = 88`, `NO_QUOTE_MISSING_BOOK = 34`, `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED = 4`, and `QUOTE_HARVEST_MID = 6`. The six allowed cells were Austin `94-95 F`, Austin `96-97 F`, Dallas `94-95 F`, Dallas `96-97 F`, Houston `92-93 F`, and Houston `94-95 F`. Its score `data/backtest/mm_paper_shadow_20260627T010734537264Z_current_source.json` has 12 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 26.8405, counterfactual reward 211.60828 USDC under the default pool/competition assumption, exchange economics `PASS`, gate `OPEN`, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 4 missing-book queue legs, 4,980 missing-size trade rows, and 12 unresolved resting quotes. This is diagnostic-only because it is a one-shot shadow/operator drill and not countable active live-forward paper evidence.
- Pre-recovery fixed paper-live-forward post-settlement score: `data/backtest/mm_paper_postsettlement_latest_20260627T020932_current_source.json` was generated at `2026-06-27T02:10:06Z` from the moving folder `data/mm_runs/2026-06-26/20260627T011838375104Z`: 5,016 quote rows, 118 quote-permission rows, 0 live-trade-permission rows, 236 quoted legs, 0 conservative fills, 6 queue-estimated fill legs, reward score 625.5215, counterfactual reward 862.168109 USDC under the default pool/competition assumption, exchange economics `PASS`, gate `OPEN`, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 50 missing-book queue legs, 7,084 missing-size trade rows, and 236 unresolved resting quotes. The report summary includes `Quote permissions / live permissions | 118 / 0 |`, and the JSON summary exposes flat reward-score and fill-evidence fields for readiness scripts. This is diagnostic-only because it is post-settlement/noncountable and from the pre-recovery stale-runtime folder.
- Latest regenerated recovered fixed paper-live-forward post-settlement score: `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json` was generated from the recovered folder `data/mm_runs/2026-06-26/20260627T021842583677Z`: 1,320 quote rows, 17 quote-permission rows, 0 live-trade-permission rows, 34 quoted legs, 0 conservative fills, 2 queue-estimated fill legs, reward score 89.72025, counterfactual reward 444.480401 USDC, exchange economics `PASS`, gate `OPEN`, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 1 missing-book queue leg, 4,148 missing-size trade rows, and 34 unresolved resting quotes. The counterfactual reward share uses CLOB recon competitor score 112.133982 from 19,019 book rows and 946 slices, with source `clob_recon_policy_parameter_suggestions.reward_competitor_q`. The report summary includes `Quote permissions / live permissions | 17 / 0 |`, `Competitor score source`, and CLOB recon row counts; the JSON summary exposes flat reward-score and fill-evidence fields for readiness scripts. This confirms current scoring code can replay the recovered folder and improves reward-share evidence, but remains diagnostic-only because it is post-settlement/noncountable.
- Target-date machine-readable live-readiness summary `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.json` was regenerated by `weather.market.market_making_readiness` against the all-market June 27 one-shot shadow score and returned `BLOCK` with 11 blockers. Stable blockers include preflight/CLOB tape gaps, no countable active-day paper-live-forward evidence, live-forward gate block, no countable quote permissions, unlocked policy, fewer than 14 consecutive countable paper days, nonpositive conservative P&L, no actual reward payout evidence, missing `live_readiness.json`, and fail-safe `mm_platform_verification.json` schema `mm_platform_verification_v0.2` with all operator/API proofs plus all five `secret_redaction_*` proofs missing. That artifact predates the zero-quote fill-evidence fix, so any fill `PASS` wording is vacuous and not promotion proof. Its sorted `next_actions` prioritize preflight/CLOB repair, then active-window paper evidence, live-forward gate, quote policy, and P&L/payout work. It always emits `live_capital_permission = false`; technical readiness does not override the requirement for explicit operator approval. Later selected-subset readiness `data/backtest/mm_live_readiness_20260627T071559_subset_austin_dallas_houston.json` is also `BLOCK`, with 8 blockers.
- Target-date-aligned June 27 readiness `data/backtest/mm_live_readiness_20260627T042401_after_capture_recheck.json` was generated from the 04:24Z one-shot shadow run and returned `BLOCK` with 13 blockers. It records 0 quote permissions, 0 live permissions, preflight `WARN`, fill evidence `SKIPPED`, no countable active-day paper-live-forward evidence, and `live_capital_permission = false`.
- Daily-roll operator-report enrichment now copies supervisor fields into `operator_report` and falls back to `recovery_guard.remediation` for operator guidance. Focused test `tests\operations\test_market_making_daily_roll.py::TestMarketMakingDailyRoll::test_operator_report_exposes_supervisor_backoff` passed after switching the fixture to the nested recovery-guard shape. A later reporting fix persists `daily_roll_supervisor.start_time_gate`, target date, expected target date, and status target date; focused tests `test_ensure_persists_start_time_gate_during_scheduled_wait` and `test_stop_status_file_stops_matching_paper_roll` passed, and the full `tests\operations\test_market_making_daily_roll.py` suite passed with 16 tests. Live `ensure` at `2026-06-27T06:24:17Z` returned `SCHEDULED_WAIT` with `start_after_local_time = 19:30`, `allowed = false`, `target_date = 2026-06-26`, and `expected_target_date = 2026-06-27`; it did not launch a new paper loop. The new `market_making_daily_roll stop` command provides a guarded paper-loop stop path before starting the current target date during the active window. The console log also contains older operational failures, including `OSError: [Errno 28] No space left on device` during prior writes and a `MemoryError` reading promotion state; current disk free space was about 223 GB, so the no-space event is historical rather than the current blocker.
- Readiness target-date alignment/current-target/runtime-liveness fix: `market_making_readiness` now extracts paper target dates from top-level fields, `summary`, `run_folder_selection`, and `run_configs`, blocks with `readiness_inputs_target_date_aligned` if status/latest-run/paper dates disagree, selects a same-target paper score by default when the status/latest run has a target date, and blocks with `daily_roll_target_date_current` when the status target differs from the supervisor expected target. It also treats daily-roll `blocked_restart_required`, failing `artifact_liveness`, and `operator_report.restart_recommended` as fail-closed runtime-liveness evidence even if source identity evidence is otherwise ambiguous, and renders those fields in the readiness Summary. Current readiness tests pass with 16 tests, and the combined fleet/readiness suite passes with 61 tests. Current daily-status readiness `data/backtest/mm_live_readiness_20260627T0642_daily_status_stale_heartbeat.json` is `BLOCK` with 17 blockers: target-date alignment passes on June 26, but `daily_roll_target_date_current` blocks because expected target is June 27, and `daily_roll_runtime_identity_current` now explicitly lists `daily_roll_action=blocked_restart_required`, `artifact_liveness_status=STALE_HEARTBEAT_METADATA`, `operator_restart_reason=stale_heartbeat_metadata`, `operator_restart_recommended=True`, and `run_summary.json is stale`. Latest explicit mismatch readiness `data/backtest/mm_live_readiness_20260627T112003_daily_status_flattened.json` remains `BLOCK` on target-date alignment when a June 27 paper score is passed against the June 26 daily status; `data/backtest/mm_live_readiness_20260627T0625_daily_status_target_mismatch.json` is the older regression artifact.
- June 27 midnight rollover probe is documented in `docs/research/MM_ROLLOVER_READINESS_2026-06-27.md`. The pre-refresh keyless shadow run `data/mm_runs/2026-06-27/20260627T040113401310Z` failed closed: preflight `BLOCK`, 12 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, 0 live-trade-permission rows, first failing gate `active_event`, and root cause `blocked_by_market_discovery`. Top blockers at that time were no active current market rows, missing current snapshot/model and source-status rows, missing band-level CLOB feature rows, June 27 exchange-economics target-date mismatch, and missing CLOB token/book/reward metadata for 8 markets. Bounded diagnostic score `data/backtest/mm_paper_shadow_20260627T040113_midnight_probe.json` also returned gate `BLOCK`, exchange economics `BLOCK`, 12 quote rows, 0 quote legs, 0 quote permissions, 0 reward score, and model-variant scoring `SKIPPED`.
- After rechecking current official Polymarket US docs, `weather.market.exchange_economics publish --target-date 2026-06-27 --platform polymarket_us --accept` passed and `weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us` passed with material change count `0`, rescore required `false`, snapshot `xecon-036874d19e56c76f`, and source hash `f4dad4615bc83281b5c144bc788ff77c`. The 04:24Z keyless shadow run after explicit local-date CLOB capture, `data/mm_runs/2026-06-27/20260627T042401695036Z`, has exchange economics `PASS`, preflight `WARN`, 52 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 22 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 22 `NO_QUOTE_STALE_INPUT` rows, 8 `NO_QUOTE_MISSING_PREFLIGHT` rows, and live-forward gate `BLOCK`. Bounded diagnostic `data/backtest/mm_paper_shadow_20260627T042401_after_capture_recheck.json` remains zero-exposure: 52 quote rows, 0 quote legs, 0 quote permissions, fill evidence `SKIPPED`, reward score 0, and actual payout evidence false. Target-date-aligned readiness `data/backtest/mm_live_readiness_20260627T042401_after_capture_recheck.json` is `BLOCK` with 13 blockers and `live_capital_permission = false`.
- Target-date CLOB capture/audit fix: `market_microstructure capture`, `raw-refresh`, and `audit` now accept `--date YYYY-MM-DD`, and preflight remediation commands include the run target date. Focused regression tests for explicit-date capture, raw-refresh propagation, explicit-date audit, and remediation command rendering passed. Safe command `weather.market.market_microstructure capture --market all --date 2026-06-27 --no-price-history --no-websocket-events` wrote June 27 token/book folders for all 12 markets. A later explicit strict audit after another public CLOB refresh still returns `ok=false` because Denver, Los Angeles, San Francisco, and Seattle have one counted historical gap each.
- Previous keyless shadow run after the target-date CLOB fix, `data/mm_runs/2026-06-27/20260627T044050256018Z`, has exchange economics `PASS`, preflight `WARN`, 52 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 44 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 8 `NO_QUOTE_MISSING_PREFLIGHT` rows, and live-forward gate `BLOCK`. Remaining preflight root causes were 8 missing active-event rows, 8 missing snapshot/model rows, 8 stale model rows, 8 missing source-status rows, 8 stale source-status rows, and 8 missing band-level CLOB feature rows. Bounded diagnostic `data/backtest/mm_paper_shadow_20260627T044050_after_target_date_capture.json` remains zero-exposure: 52 quote rows, 0 quote legs, 0 quote permissions, fill evidence `SKIPPED`, reward score 0, and actual payout evidence false. Target-date-aligned readiness `data/backtest/mm_live_readiness_20260627T044050_after_target_date_capture.json` is `BLOCK` with 13 blockers and `live_capital_permission = false`.
- Target-date snapshot repair fix: `weather.collection.snapshot_tracker` now accepts `--date/--target-date` plus `--market`, and `snapshot_tracker --force --market all --date 2026-06-27` wrote all 12 June 27 snapshot/model/source folders with no blocked or error markets. `current_fleet_collection_health(target_date="2026-06-27")` then reported all 12 markets `COLLECTING`, snapshot cadence `PASS`, and root cause counts `within_cadence: 12`.
- Previous keyless shadow run after target-date snapshot repair, `data/mm_runs/2026-06-27/20260627T050232213844Z`, has exchange economics `PASS`, preflight `WARN`, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 44 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 88 `NO_QUOTE_STALE_INPUT` rows, and live-forward gate `BLOCK`. Remaining remediation root cause was 8 `clob_book_tape_gap_over_threshold`, marked not recoverable same day. Bounded diagnostic `data/backtest/mm_paper_shadow_20260627T050232_after_target_snapshot_repair.json` remains zero-exposure historical evidence: 0 quote permissions, fill evidence `SKIPPED`, reward score 0, and actual payout evidence false. Target-date-aligned readiness `data/backtest/mm_live_readiness_20260627T050232_after_target_snapshot_repair.json` was `BLOCK` with 12 blockers and `live_capital_permission = false`.
- All-market keyless shadow run after refreshing default June 27 event metadata, target-date snapshots, and public CLOB books/features, `data/mm_runs/2026-06-27/20260627T055820610723Z`, has exchange economics `PASS`, preflight `WARN`, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 55 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 44 `NO_QUOTE_STALE_INPUT` rows, 33 `NO_QUOTE_INFORMATION_EVENT` rows, and live-forward gate `BLOCK`. Remaining preflight issue is four counted historical `clob_freshness` gaps. Bounded diagnostic `data/backtest/mm_paper_shadow_20260627T055820_after_metadata_snapshot_refresh.json` remains zero-exposure: 0 quote permissions, model-variant scoring `PASS`, exchange-economics gate `PASS`, and actual payout evidence false. The zero-quote fill status in that artifact predates the `no_quote_legs` fix. Target-date-aligned readiness `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.json` is historical all-market no-go evidence with 11 blockers and `live_capital_permission = false`.
- Selected-market Austin/Dallas/Houston subset shadow after the event gate cleared, `data/mm_runs/2026-06-27/20260627T061148175884Z`, was run with `--mode shadow --markets austin,dallas,houston --once`. It passed preflight and wrote 33 quote-intent rows: 16 `QUOTE_HARVEST_MID`, 10 `NO_QUOTE_DISAGREEMENT_SHADOW`, 7 `NO_QUOTE_MISSING_BOOK`, 16 quote-permission rows, and 0 live-trade-permission rows. Event gate action was `none` on all rows. Bounded diagnostic `data/backtest/mm_paper_shadow_20260627T061148_subset_austin_dallas_houston.json` has 32 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` due to missing-size trade rows and 32 unresolved resting quotes, counterfactual reward 144.890411 USDC, exchange-economics gate `PASS`, model-variant scoring `PASS`, and actual payout evidence false. Matching readiness `data/backtest/mm_live_readiness_20260627T061148_subset_austin_dallas_houston.json` remains `BLOCK` with 11 blockers and `live_capital_permission = false`; this is historical small-scale paper-subset evidence, not live readiness.
- Subset input-gate verification after that run: `weather.operations.event_metadata_validation --target-date 2026-06-27 --markets austin,dallas,houston` wrote `data/backtest/event_metadata_validation_20260627_subset_austin_dallas_houston.json` with `PASS`; strict target-date CLOB audits for Austin, Dallas, and Houston each returned `ok: true`; the subset run summary records preflight `PASS`, fresh source-status rows, 11 snapshot rows, and 11 CLOB feature rows for each of the three markets.
- Managed CLOB fixed-date safety fix: `market_microstructure loop`, `start-detached`, `restart`, and `ensure` now accept `--date YYYY-MM-DD`, pass that fixed target date into capture, record `target_date` / `date_selection` in `clob_loop_status.json`, include per-market `event_slug` / `target_date` in status summaries, and mark fixed-date health `DEGRADED` if any market's captured target date disagrees. This closes the cross-timezone-midnight ambiguity where `market_microstructure status` could look fresh while west-coast markets were still being captured into prior-local-date folders. Focused `tests/market/test_market_microstructure.py` now has 42 passing tests covering this behavior.
- Selected-market Austin/Dallas/Houston shadow after that fix, `data/mm_runs/2026-06-27/20260627T065901450465Z`, passed preflight but emitted 0 quote-permission rows, 0 live-trade-permission rows, and 33 no-quote rows: 25 `NO_QUOTE_STALE_BOOK` and 8 `NO_QUOTE_MISSING_BOOK`. Its paper score `data/backtest/mm_paper_shadow_20260627T065901_subset_austin_dallas_houston.json` has 33 quote rows, 0 quoted legs, 0 conservative fills, 0 queue-estimated fills, exchange economics `PASS`, net P&L 0, reward score 0, and actual payout evidence false; any zero-quote fill `PASS` wording is pre-fix/vacuous. Matching readiness `data/backtest/mm_live_readiness_20260627T065901_subset_austin_dallas_houston.json` is `BLOCK` with 8 real blockers and `live_capital_permission = false`; the one-shot run-summary root cause `policy_no_edge` is now shown as non-applicable to the daily-roll runtime gate instead of being misreported as daily-roll runtime staleness.
- Fresh selected-market Austin/Dallas/Houston shadow after targeted snapshot refresh plus targeted public CLOB capture, `data/mm_runs/2026-06-27/20260627T071559212462Z`, passed preflight with fresh model and book ages but still emitted 0 quote-permission rows, 0 live-trade-permission rows, and 33 no-quote rows: 25 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED` and 8 `NO_QUOTE_MISSING_BOOK`. All rows were during a WU current print window with event action `widen`, not `suppress`; the policy blocker was degraded snapshot cadence from earlier gaps plus missing spread on thin-tail books. Its paper score `data/backtest/mm_paper_shadow_20260627T071559_subset_austin_dallas_houston.json` has 33 quote rows, 0 quoted legs, 0 conservative fills, 0 queue-estimated fills, exchange economics `PASS`, net P&L 0, reward score 0, and actual payout evidence false; any zero-quote fill `PASS` wording is pre-fix/vacuous. Matching readiness `data/backtest/mm_live_readiness_20260627T071559_subset_austin_dallas_houston.json` is `BLOCK` with 8 real blockers and `live_capital_permission = false`; its Summary now exposes `latest_tick_reason_counts`.
- Fresh all-market June 27 shadow after current runtime/data checks, `data/mm_runs/2026-06-27/20260627T073107208602Z`, passed preflight and emitted 23 quote-permission rows, 109 no-quote rows, and 0 live-trade-permission rows. Quote permissions were harvest-mid rows in Austin (4), Dallas (7), Denver (5), and Houston (7); the no-quote split was 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_DISAGREEMENT_SHADOW`, and 10 `NO_QUOTE_MISSING_BOOK`. Its bounded score `data/backtest/mm_paper_shadow_20260627T073107_current_all.json` has 46 quoted legs, 0 conservative fills, 1 queue-estimated fill leg, fill evidence `BLOCK` because of 400 missing-size trade rows and 46 unresolved resting quotes, total reward score 20.559525, counterfactual reward 176.767745 USDC, and actual payout evidence false. Matching readiness `data/backtest/mm_live_readiness_20260627T073107_current_all.json` remains `BLOCK` with 11 blockers and `live_capital_permission = false`; the run is useful shadow quote-emission evidence, not countable paper-live-forward evidence.
- Paper scoring now exposes exact candidate-market diagnostics under `summary.quote_uptime`: `quote_permission_market_counts = {austin: 4, dallas: 7, denver: 5, houston: 7}` and `top_quote_permission_cells`. The first cells are Austin `91 F or below`, `100-101 F`, `102-103 F`, `104-105 F`; Dallas `90-91 F`, `92-93 F`, `94-95 F`, `96-97 F`, `100-101 F`, `102-103 F`, `104-105 F`; and Denver `86-87 F`, all with `known_edge_permission = harvest_only`, `promotion_state = SHADOW`, and `reason_code = QUOTE_HARVEST_MID`.
- Readiness for the 073107 shadow now carries the paper evidence blockers and candidate-market fields in its own Summary: `paper_quote_permission_market_counts = {austin: 4, dallas: 7, denver: 5, houston: 7}`, `paper_score_freshness_status = NO_ACTIVE_DAY`, `live_forward_day_count = 0`, `locked_policy_params = false`, `fill_evidence_blockers = [missing_size_trade_rows, unresolved_resting_quotes]`, `missing_size_trade_rows = 400`, `missing_book_queue_legs = 0`, `unresolved_resting_quote_count = 46`, `total_reward_score = 20.559525`, `counterfactual_reward_usdc = 176.767745`, and `score_at_or_above_target_size = false`.
- Follow-up all-market shadow at `data/mm_runs/2026-06-27/20260627T075907746405Z` passed preflight but emitted 0 quote-permission rows and 0 live-trade-permission rows. Reason split: 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 35 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 9 `NO_QUOTE_MISSING_BOOK`. Its pre-fix paper score `data/backtest/mm_paper_shadow_20260627T075907_current_all.json` has 132 quote rows, 0 quoted legs, reward score 0, and actual payout evidence false; readiness `data/backtest/mm_live_readiness_20260627T075907_current_all.json` is `BLOCK` with 8 blockers. Treat any zero-quote fill `PASS` wording there as vacuous.
- Known-edge provenance patch: `market_making_run.py` now copies `known_edge_map` diagnostics into `run_summary.json`, `mm_policy.load_known_edge_map` preserves `diagnostic_only`, and `market_making_readiness.py` renders `known_edge_map_path`, schema, record count, and diagnostic-only status in its Summary. The patched shadow run `data/mm_runs/2026-06-27/20260627T080312460577Z` records accepted map `data/backtest/mm_known_edge_map.json`, schema `mm_known_edge_map_v0.2`, `record_count = 17`, and `diagnostic_only = false`. That run is still a no-go: preflight `STALE` on `model_freshness`, 132 `NO_QUOTE_STALE_INPUT` rows, 0 quote permissions, 0 live permissions, and readiness `BLOCK`.
- Zero-quote fill-evidence safety fix: `mm_paper.fill_evidence_completeness_summary` now treats a scored run with 0 quoted legs as non-promotion evidence (`status = BLOCK`, `blockers = [no_quote_legs]`, `vacuous = true`) instead of a clean fill-evidence pass. `market_making_readiness` also downgrades legacy zero-quote paper artifacts that report `PASS` with 0 quoted legs by adding `fill_evidence_effective_promotion_grade = false`, `fill_evidence_vacuous = true`, and `fill_evidence_quote_legs = 0` to the Summary. The regenerated 080312 score `data/backtest/mm_paper_shadow_20260627T080312_current_all.json` now records 132 quote-intent rows, 0 quote permissions, 0 quoted legs, fill evidence `BLOCK`, `fill_evidence_reason = no_quote_legs`, reward score 0, and exchange economics `PASS`. Matching readiness `data/backtest/mm_live_readiness_20260627T080312_current_all.json` is now `BLOCK` with 11 blockers, including the explicit `fill_evidence_complete` blocker. Older zero-quote artifacts that still say fill evidence `PASS` should be read as pre-fix diagnostics, not promotion-grade fill proof.
- Continuation safe rechecks at `2026-06-27T08:14Z`: explicit target-date strict CLOB audit `weather.market.market_microstructure audit --strict --date 2026-06-27` returned `ok = true` for all 12 markets with startup gaps ignored before the current loop cutoff, and `weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_latest.json` returned `PASS`.
- Continuation safe rechecks at `2026-06-27T08:24Z`: CLOB loop status was `RUNNING`, discovery sanity `PASS`, heartbeat fresh, no error markets, and explicit target-date strict CLOB audit returned `ok = true` for all 12 markets. Exchange-economics drift for `2026-06-27` / `polymarket_us` again returned `PASS`. The daily roll remained noncountable prior-target/post-settlement evidence: `action = blocked_restart_required`, target date `2026-06-26`, expected target date `2026-06-27`, supervisor `SCHEDULED_WAIT`, start gate before `19:30` local, and `artifact_liveness.status = STALE_HEARTBEAT_METADATA`.
- Snapshot/model/source status at the same time was still not quote-ready. `snapshot_tracker --status` reported the loop `RUNNING` and runtime identity current, but all 12 markets were `AT_RISK`; latest snapshots were about 17-19 minutes old, snapshot cadence proof was `BLOCK`, early-hour coverage proof was `BLOCK`, and source-status proof blocked all 12 markets because WU source families were degraded or unauthorized (`weather_forecast`, `wu_current`, `wu_history`; `wu_history` settlement auth failure on all 12). This remains useful point-in-time evidence for model/source freshness fail-closed behavior, while the latest snapshot check has since recovered runtime/cadence and still blocks on source-status plus early-hour coverage.
- Fresh all-market keyless shadow at `data/mm_runs/2026-06-27/20260627T082513537232Z` captured that fail-closed state: preflight `STALE`, first failing gate `model_freshness`, 132 `NO_QUOTE_STALE_INPUT` rows, 0 quote-permission rows, 0 live-trade-permission rows, live-forward gate `BLOCK`, and accepted known-edge map provenance `mm_known_edge_map_v0.2` with 17 records and `diagnostic_only = false`. Its score `data/backtest/mm_paper_shadow_20260627T082513_current_all.json` has 132 quote-intent rows, 0 quote permissions, 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and actual payout evidence false. Matching readiness `data/backtest/mm_live_readiness_20260627T082513_current_all.json` is `BLOCK` with 11 blockers: preflight/model freshness, no countable active-day paper evidence, live-forward gate, no quote permissions, no fill evidence, 14-day evidence, positive P&L, payout, operator readiness, and platform verification. A fixed-string scan of the fresh run/paper/readiness artifacts found only field names such as `private_key_storage_recorded` / `loads_private_keys = false`, not secret material.
- Pre-gate all-market keyless shadow at `data/mm_runs/2026-06-27/20260627T083841810915Z` showed preflight `PASS`, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, live-forward gate `BLOCK`, and accepted known-edge map provenance `mm_known_edge_map_v0.2` with 17 records and `diagnostic_only = false`. Reason counts were 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 31 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 13 `NO_QUOTE_MISSING_BOOK`; the cadence-denied rows were concentrated in Austin, Dallas, Houston, and Denver with per-row `snapshot_cadence_quality_state = gappy` and roughly 19.6 minute selected-snapshot gaps. Its score `data/backtest/mm_paper_shadow_20260627T083841_current_all.json` has 132 quote-intent rows, 0 quote permissions, 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and actual payout evidence false. This artifact is now historical context because preflight did not yet block on the fleet source-status proof.
- Post-backfill all-market keyless shadow at `data/mm_runs/2026-06-27/20260627T103532784124Z` showed the stricter fail-closed state with explicit count aliases in `run_summary.json`: `quote_intent_rows = 132`, `quote_rows = 132`, `no_quote_rows = 132`, `quote_permission_rows = 0`, and `live_trade_permission_rows = 0`. Before that run, source-status backfill rewrote 3,756 rows across the 12 current June 27 folders from replay inputs, but `snapshot_tracker --status` still reported `source_status.status = BLOCK`, `root_cause_class = settlement_source_auth_failure`, and 12 `wu_history` settlement auth failures. Preflight was `BLOCK`, first failing gate was `source_status_degradation`, reason counts were 132 `NO_QUOTE_MISSING_PREFLIGHT`, and `preflight_remediation.root_cause_counts = {source_status_degradation_blocked: 12, stale_model_row: 8}`. Its score `data/backtest/mm_paper_shadow_20260627T103532_after_source_backfill.json` has 132 quote-intent rows, 0 quote permissions, 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, paper-day collection gate `OPEN`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`. The regenerated blocker diagnostics separate primary cause from context: `event_gate_suppressed_rows = 0` and `contextual_event_gate_suppressed_rows = 0`, so that check was not confounded by an overlapping information-event window. Matching readiness `data/backtest/mm_live_readiness_20260627T103532_after_source_backfill.json` is `BLOCK` with 11 blockers and `live_capital_permission = false`; its Summary renders `snapshot_model_source_failing_gate_counts = {model_freshness: 8, source_status_degradation: 12}`, `model_freshness_failed_market_count = 8`, `source_status_degradation_failed_market_count = 12`, aggregate `source_status_settlement_auth_failures = 12`, `source_status_settlement_auth_failures_per_market = 1`, and `latest_tick_quote_permission_rows = 0`.
- Fresh follow-up all-market keyless shadow at `data/mm_runs/2026-06-27/20260627T110334081112Z` remains no-go and is now historical context before the active-window paper-live-forward one-shot: preflight `BLOCK`, first failing gate `model_freshness`, 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT`, 0 quote permissions, and 0 live permissions. Its score `data/backtest/mm_paper_shadow_20260627T110334_current_source_status_block.json` has 0 quoted legs, fill evidence `BLOCK`, reward score 0, exchange economics `PASS`, event-gate suppressed rows 0, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`. Matching readiness `data/backtest/mm_live_readiness_20260627T110334_current_source_status_block.json` is `BLOCK` with 11 blockers and renders `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}`, `model_freshness_failed_markets = [atlanta, nyc, toronto]`, `source_status_degradation_failed_markets = all 12 selected markets`, `source_status_settlement_auth_failures = 12`, and `source_status_settlement_auth_failures_per_market = 1`.
- Current active-window paper-live-forward one-shot at `data/mm_runs/2026-06-27/20260627T135932865534Z` is the freshest active-window paper-live-forward evidence: `evidence_mode = active_day_live_forward`, preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT`, 0 quote permissions, 0 live permissions, live-forward gate `BLOCK`, and `current_counts_toward_live_forward_gate = false`. Its score `data/backtest/mm_paper_paperlive_20260627T135932_after_clob_recovery_source_status_block.json` has `paper_score_freshness_status = PASS`, 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, actual payout evidence false, exchange economics `PASS`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`. Matching readiness `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json` is `BLOCK` with 11 blockers and renders `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}`, `source_status_degradation_failed_markets = all 12 selected markets`, aggregate `source_status_settlement_auth_failures = 12`, and `source_status_settlement_auth_failures_per_market = 1`. The latest all-market shadow/operator-drill comparator is `data/mm_runs/2026-06-27/20260627T135111048558Z`, scored by `data/backtest/mm_paper_shadow_20260627T135111_after_clob_recovery_source_status_block.json`, with readiness `data/backtest/mm_live_readiness_20260627T135111_after_clob_recovery_source_status_block.json`.
- Operator-facing run output, generated `run_report.md`, regenerated paper Markdown, and readiness Markdown now use explicit counter/gate names: `quote-intent rows`, `quote-permission rows`, `quoted legs`, `no-quote rows`, `live-permission rows`, and paper-day collection gate. The latest run report renders `Latest-tick quote-intent rows = 132`, `Latest-tick quote-permission rows = 0`, `Latest-tick no-quote rows = 132`, `Cumulative quote-intent rows = 132`, `Cumulative quote-permission rows = 0`, and `Cumulative no-quote rows = 132`; the latest paper report renders `Quote-intent rows / quoted legs = 132 / 0`, `Quote permissions / live permissions = 0 / 0`, `Paper-day collection gate = OPEN`, `Live-capital gate = NOT_EVALUATED_BY_MM_PAPER`, and `Early-hour quote-permission rows = 0`. Regression coverage includes the 39-test focused run for `market_making_run`, the 27-test focused run for `mm_paper`, the current 16-test readiness suite, the 61-test combined fleet/readiness suite, the 118-test prompt-required core maker bundle, and the 33-test collection robustness suite.
- Status-output redaction was rechecked after broadening `redaction.py` to treat empty sensitive query values as unredacted until redacted. Capturing `snapshot_tracker --status` to an in-memory string and scanning it found 0 `apiKey=&` matches, 0 raw secret-query parameters, and 48 redacted secret-query parameters. Auth-only optional-provider failures are now treated as source-health evidence covered by free-source replacement, not as an operator setup path.
- Official Polymarket US docs were rechecked again during this continuation. Liquidity incentives still score resting orders every second by `Discount Factor ^ ticks_from_best_price * Order Size`; US fee/rebate assumptions still use `Fee = Theta * C * p * (1 - p)`, taker theta `0.05`, maker rebate theta `-0.0125`; US create-order docs still expose `participateDontInitiate` as maker-only/no-immediate-match behavior; Orders API overview still lists a global 20 requests/second per API-key rate limit. These checks do not change the no-go result because local data/readiness evidence is blocked.
- Small safety/usability fixes from this probe: `market_making_preflight` remediation now points `active_event`, `clob_tokens`, and related CLOB repairs to exposed date-aware commands such as `python -m weather.market.market_microstructure capture --market all --date <YYYY-MM-DD>` instead of stale or target-date-ambiguous strings; `market_making_readiness` can use a one-shot run summary as its status input by following `run_folder`.
- Latest CLOB checks: after the `13:43Z` to `13:59Z` fixed-date recovery sequence, later diagnostics showed a pre-fix runtime-identity `ensure` restart had launched an undated local-date replacement. The latest explicit restart at `14:37Z` stopped two undated processes and restored loop `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, `include_price_history = false`, `include_ws_events = false`, heartbeat/books/features fresh, discovery sanity `PASS`, useful raw-book iterations, and 0 target-date mismatch markets. Process inspection confirmed `--date 2026-06-27 --no-price-history --no-websocket-events`, and explicit `weather.market.market_microstructure audit --strict --date 2026-06-27` returned `ok = true` for all 12 markets. Continue checking status/process/audit before counting future evidence because earlier supervisor drift did occur.
- Continuation non-mutating recheck at `2026-06-27T10:14Z`: `weather.market.market_microstructure status` still reported the CLOB loop `RUNNING`, discovery sanity `PASS`, heartbeat/books fresh, 0 consecutive errors, and no error markets; explicit `weather.market.market_microstructure audit --strict --date 2026-06-27` again returned `ok = true` for all 12 markets with only startup gaps ignored. `weather.operations.market_making_daily_roll status` remained noncountable and restart-blocked: target date `2026-06-26`, expected target date `2026-06-27`, evidence mode `post_settlement_evaluation`, `live_forward_gate_status = BLOCK`, `current_counts_toward_live_forward_gate = false`, artifact liveness `STALE_HEARTBEAT_METADATA`, root cause `stale_heartbeat_metadata`, supervisor state `SCHEDULED_WAIT`, and the 19:30 local start-time gate had not opened.
- Current snapshot tracker check: `weather.collection.snapshot_tracker --status` is the correct module path and currently reports `RUNNING`, `runtime_code_state = current`, `runtime_identity_matches_current = true`, fleet capture liveness `OK`, snapshot cadence `PASS`, early-hour coverage `BLOCK`, and `source_status_proof.status = BLOCK` with `root_cause_class = settlement_source_auth_failure` blocking all 12 markets. Process inspection showed the apparent two snapshot PIDs are a venv launcher wrapper plus its Python child, with the writer lock owned by the current child PID. The older `weather.capture.snapshot_tracker` path fails in this checkout. Source-status proof still blocks quote permission before policy output can be interpreted.
- Source-status proof schema was tightened to `source_status_proof_v0.2` so the status payload exposes `status`, `root_cause_class`, `reason`, source-status blocker counts, and free-source replacement coverage at `fleet_collection.source_status_proof` and in the summary copy. Current verified values are `status = BLOCK`, `root_cause_class = settlement_source_auth_failure`, `reason = source status blocked: trading=12 live=12 promotion=12 unknown=0`, with 0 raw secret-query parameters in status output. Fleet observability Markdown now renders settlement-auth failure sources and free-source replacement coverage; the regenerated fleet report is `CRITICAL`.
- Latest readiness was regenerated from the 135932 active-window paper-live-forward run/score after adding non-secret provider source diagnostics and recovering CLOB/observation-trigger liveness. The JSON/Markdown report `paper_score_freshness_status = PASS`, `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}`, and 0 quote/live permissions; upstream `snapshot_tracker --status` reports the same source-status proof. The first two next actions now verify free-source replacement coverage before rerunning source-status backfill and paper-live-forward/readiness.
- Fleet SLO recovery now carries the same per-market source-status layer. When a settlement-auth failure is covered by free-source replacement, the recovery row uses root cause `settlement_source_auth_failure_optional_provider`, owner `optional provider source status`, and a repair sequence of free-source replacement verification first, then `python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status`.
- Regenerated fleet observability at `2026-06-27T12:14:27Z` remains `CRITICAL`, but the machine-readable and Markdown recovery path is now specific and readable: `live_forward_slo.first_blocker.root_cause = settlement_source_auth_failure_optional_provider`, `owner = optional provider source status`, and the first repair command starts with `verify free-source replacement coverage`. `source_status_proof` remains `BLOCK` with 12 blocked markets, 12 settlement-auth failures, and redaction enabled. The Broad Recovery Gates Markdown row now summarizes the duplicated source-status detail as `(x12)` instead of repeating the same long text for every market.
- Same continuation status checks: `weather.market.market_microstructure status` reported the CLOB loop `RUNNING` with discovery sanity `PASS`, fresh books/features, 0 consecutive errors, and no error markets; `weather.market.market_microstructure audit --strict --date 2026-06-27` returned `ok = true` for all 12 markets with startup gaps ignored after the current loop cutoff. `weather.operations.market_making_daily_roll status` remained noncountable: `target_date = 2026-06-26`, expected target date `2026-06-27`, supervisor state `SCHEDULED_WAIT`, start-time gate `before_daily_start_time` until `19:30` local, artifact liveness `STALE_HEARTBEAT_METADATA`, action `blocked_restart_required`, and `current_counts_toward_live_forward_gate = false`.
- Schema registry strict audit now passes after registering the current source-status proof and market-making schemas: `source_status_proof_v0.2`, `mm_live_readiness_v0.2`, `mm_quote_blocker_diagnostics_v0.8`, `mm_quote_intent_v0.3`, and `mm_reward_score_diagnostics_v0.2`.
- The Streamlit Market Making cockpit now reads the latest target-date `mm_live_readiness*.json` artifact and renders a `Live Readiness` section with status, live-capital permission, blocker count, source-status root cause, optional provider status, summary rows, and sorted next actions. The focused app/readiness test verifies the cockpit surfaces `settlement_source_auth_failure`, `optional provider status = false`, and the `optional provider source` / `optional provider source` external-configuration action.
- Official Polymarket US docs were rechecked again during this continuation. The current repo assumptions still match the accepted US template at the level used here: fee theta 0.05, maker rebate pool share 25 percent of taker fees, liquidity score by discount factor raised to ticks from best price times order size with default Climate/category economics, market-specific tick/min-order fields, post-only `participateDontInitiate`, and private/order/cancel semantics. The June 27 exchange-economics snapshot and accepted baseline were refreshed after that check.

Official Polymarket US API details rechecked:

- `POST /v1/orders` accepts `participateDontInitiate: true` in the create-order body.
- `POST /v1/orders/open/cancel` can cancel all open orders, optionally filtered by market slug.
- Orders API documentation warns that batch/cancel results alone do not prove every final order outcome; the private WebSocket order stream is required for final state.
- `/v1/ws/private` provides order snapshots and order execution updates.
- US rate limits are 20 requests/second per API key. A 5-second latency stopgap can reject new orders and cancel-replaces, while pure cancels are not affected.

Local code change:

- `src/weather/market/mm_exchange.py` now exposes platform-specific live-readiness notes in adapter diagnostics.
- `src/weather/market/mm_exchange_reports.py` renders those notes in the reconciliation report.
- For Polymarket US, the diagnostics explicitly list private stream reconciliation, cancel-all zero-open-order confirmation, latency-stopgap handling, and API-key/platform eligibility as live-readiness requirements.
- The US adapter now classifies documented latency-stopgap order rejects as `reject_class = latency_stopgap`, `order_acceptance = not_accepted`, no rate-limit backoff required, and book refresh/recompute required before retry. If the same message appears on cancel/cancel-all, it is classified as an unexpected cancel reject and live-readiness blocker. Both returned error payloads and raised HTTP exceptions are covered by tests.
- The reconciliation path now normalizes Polymarket US private WebSocket order-update fixtures into existing lifecycle/fill rows. Tested mappings include `EXECUTION_TYPE_PARTIAL_FILL`, `EXECUTION_TYPE_FILL`, `EXECUTION_TYPE_CANCELED`, `EXECUTION_TYPE_REJECTED`, `EXECUTION_TYPE_EXPIRED`, `EXECUTION_TYPE_DONE_FOR_DAY`, and `EXECUTION_TYPE_REPLACE`.
- `mm_exchange_reports.mm2_probe_status` now requires structured cancel-all evidence with zero open orders after the request. Tests cover pending status when cancel-all evidence lacks zero-open-order confirmation and observed status when `open_orders_after_cancel_all` is empty.
- `market_making_preflight.load_platform_verification_gate` now requires `mm_platform_verification_v0.2`; legacy v0.1 or boolean-only artifacts fail live-pilot preflight unless the structured maker-only, private-stream, cancel-all zero-open-order, and US latency-stopgap fields are present and true.
- `src/weather/market/mm_paper.py` now exposes `quote_permission_rows`, `no_quote_rows`, `quote_permission_rate`, `live_trade_permission_rows`, `live_trade_permission_rate`, flat reward-score fields, and flat fill-evidence fields directly in `payload["summary"]`; `src/weather/market/mm_paper_reports.py` renders `Quote permissions / live permissions` and quote-permission rate in the report summary. This prevents future readiness checks from having to infer live-safety counters or go/no-go evidence from nested diagnostics.
- `src/weather/market/mm_paper.py` now uses CLOB recon `reward_competitor_q` when recon coverage exists and records whether counterfactual reward share came from recon evidence or the paper config default; `src/weather/market/mm_paper_reports.py` renders the competitor-score source and recon row counts.
- `src/weather/market/market_making_readiness.py` now builds a conservative live-readiness JSON/Markdown summary from daily-roll status, latest paper score, live-readiness JSON, and platform-verification proof. It treats missing evidence as `BLOCK`, separates technical readiness from live-capital permission, emits sorted `next_actions` from failed gates, and keeps `live_capital_permission = false` until an operator explicitly authorizes a future pilot outside this report.
- `src/weather/market/market_making_readiness.py` now distinguishes one-shot run-summary status from daily-roll status so a one-shot `root_cause_class` such as `policy_no_edge` is not misreported as stale daily-roll runtime identity. Daily-roll stale heartbeat/action evidence still fails closed.
- Current official Polymarket US docs were rechecked again. The Cancel Multiple Orders page now documents `POST /v1/orders/batched/cancel` with a 20-order cap and says `canceledOrderIds` is only an echo/submission record, so `mm_exchange.adapter_capability_matrix("polymarket_us")` now exposes `max_cancel_order_batch_size = 20` and the US live-readiness notes require chunking plus private-order-stream final-state reconciliation for any future batch-cancel path.
- Latest continuation drift check at `2026-06-27T12:20:30Z`: `weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_recheck.json` returned `PASS`, `material_change_count = 0`, `rescore_required = false`, and current/accepted snapshot `xecon-036874d19e56c76f`. Focused regression tests for exchange economics, paper scoring, and daily refresh then passed (`97 passed in 69.84s`).

Interpretation:

- The US fee/reward snapshot is still useful for paper and shadow economics.
- The snapshot is not a sufficient live-readiness artifact. Any future pilot still needs real private stream reconciliation, real cancel-all verification with zero open orders afterward, live latency-stopgap proof, account eligibility, and secret-redaction proof.

## Next Simulation Work

Latest 2026-06-27 fixed-date recovery continuation:

- `.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --date 2026-06-27 --no-price-history --no-websocket-events` stopped two undated local-date CLOB loop processes and started a fixed-date public-data loop.
- Follow-up status showed `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, `include_price_history = false`, `include_ws_events = false`, discovery sanity `PASS`, fresh heartbeat/books, useful raw-book iterations, and 0 target-date mismatch markets. Process inspection confirmed the command line includes `--date 2026-06-27 --no-price-history --no-websocket-events`.
- `.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date 2026-06-27` returned `ok = true` for all 12 markets, with startup gaps ignored only before the new fixed-date loop cutoff.
- `data/snapshots/clob_diagnostics.jsonl` now records start diagnostics with `target_date`, `date_selection`, capture enrichment flags, interval/batch settings, and WebSocket settings. The preceding drift root cause was a pre-fix `ensure` restart on runtime-identity mismatch that launched an undated replacement after stopping fixed-date processes.
- Correct snapshot status command is `.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status`; the older `weather.capture.snapshot_tracker` module path is stale in this checkout. Latest status still blocks readiness through source/coverage, not runtime: `RUNNING`, current runtime identity, fleet capture liveness `OK`, snapshot cadence `PASS`, early-hour coverage `BLOCK` for all 12 markets, and source-status proof `BLOCK` from `settlement_source_auth_failure` with `optional provider source = false` and `optional provider source = false`.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once` wrote `data/mm_runs/2026-06-27/20260627T143831651008Z`: 132 quote-intent rows, 132 no-quote rows, 0 quote-permission rows, 0 live-permission rows, and preflight `BLOCK`.
- Scored artifact `data/backtest/mm_paper_shadow_20260627T143831_after_fixed_clob_source_status_block.json` has 0 quoted legs, 0 conservative fills, 0 queue-estimated fills, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and no actual payout evidence.
- Readiness artifact `data/backtest/mm_live_readiness_20260627T143831_after_fixed_clob_source_status_block.json` is `BLOCK` with 11 blockers, `live_capital_permission = false`, 0 live-forward days, 0 quote permissions, source-status `settlement_source_auth_failure` across all 12 markets, and model freshness failures across all 12 markets in this one-shot.
- `.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status` remains noncountable: status `idle_process`, action `blocked_restart_required`, target date `2026-06-26`, expected target `2026-06-27`, supervisor `SCHEDULED_WAIT` until 19:30 local, artifact liveness `STALE_HEARTBEAT_METADATA`, activity `STALE_ACTIVITY`, live-forward gate `BLOCK`, and `current_counts_toward_live_forward_gate = false`.

Latest 2026-06-27 post-snapshot-recovery shadow continuation:

- Non-mutating gate rechecks at about `15:05Z` found fixed-date CLOB still `RUNNING` with `target_date = 2026-06-27`, strict CLOB audit `ok = true`, snapshot tracker `RUNNING` with current runtime identity, capture liveness `OK`, snapshot cadence `PASS`, source-status `BLOCK`, early-hour coverage `BLOCK`, observation trigger `RUNNING` with 0 snapshot-blocked markets, and daily roll still prior-target/noncountable with `SCHEDULED_WAIT` before the 19:30 local start gate.
- Daily-roll status surfacing was tightened after this check: `src/weather/operations/market_making_daily_roll.py` now flattens `expected_target_date`, `supervisor_state`, `supervisor_action`, `start_reason`, `start_after_local_time`, and related supervisor/start-gate fields onto the top-level status payload while preserving `daily_roll_supervisor` and `operator_report`. Focused verification `tests\operations\test_market_making_daily_roll.py` passed with 16 tests, and live `market_making_daily_roll status` now reports `expected_target_date = 2026-06-27`, `supervisor_state = SCHEDULED_WAIT`, `supervisor_action = scheduled_wait`, `start_reason = before_daily_start_time`, and `start_after_local_time = 19:30`.
- `.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_post_snapshot_recovery.json` returned `PASS`, `material_change_count = 0`, `rescore_required = false`, and snapshot `xecon-036874d19e56c76f`.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once` wrote `data/mm_runs/2026-06-27/20260627T150554104648Z`: 132 quote rows, 132 no-quote rows, 0 quote-permission rows, 0 live-permission rows, preflight `BLOCK`, and first failing gate `source_status_degradation`.
- Scored artifact `data/backtest/mm_paper_shadow_20260627T150554_post_snapshot_recovery_source_status_block.json` has 132 quote rows, 132 no-quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, and actual payout evidence false.
- Readiness artifact `data/backtest/mm_live_readiness_20260627T150554_post_snapshot_recovery_source_status_block.json` is `BLOCK` with 11 blockers, `live_capital_permission = false`, 0 live-forward days, 0 quote permissions, 0 live permissions, `source_status_degradation_failed_market_count = 12`, `source_status_settlement_auth_failures = 12`, and `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`. This latest probe confirms source-status evidence is the immediate all-market blocker after runtime/cadence recovery.
- Fresh daily-status mismatch readiness after flattening uses `data/mm_runs/daily_roll_status.json` plus the 150554 shadow score and writes `data/backtest/mm_live_readiness_20260627T112003_daily_status_flattened.json` / `.md`. It is `BLOCK` with 16 blockers. The key result is structural target-date safety: daily-roll status target `2026-06-26`, supervisor expected target `2026-06-27`, and paper-score target `2026-06-27` produce `readiness_inputs_target_date_aligned = BLOCK` and `daily_roll_target_date_current = BLOCK`. The same report confirms top-level flattened fields are available to readiness/reporting (`daily_roll_action = blocked_restart_required`, `supervisor_state = SCHEDULED_WAIT`, `supervisor_action = scheduled_wait`, `start_reason = before_daily_start_time`, `start_after_local_time = 19:30`).

Scenario coverage matrix:

- `docs/research/MM_SIMULATION_SCENARIO_COVERAGE_2026-06-27.md` maps each requested simulation scenario to current repo artifacts, regression tests, coverage status, and remaining blockers. Current conclusion remains NO-GO: the latest active-window paper-live-forward run, latest-five aggregate, and fixed-date shadow drill all have 0 quote permissions and block before quote/fill/reward evidence can be interpreted.
- Latest CLOB recovery evidence: stale generated event metadata initially blocked a public CLOB capture; `location_config_refresh` plus `event_metadata_validation --target-date 2026-06-27` produced `data/backtest/event_metadata_validation_20260627_goal_recheck.json` with 12/12 markets `PASS`. A fixed-date CLOB capture then wrote 22 books/tokens per market. After diagnosing an undated restart, explicit fixed-date restart at `14:37Z` restored loop status to `RUNNING`/fixed-date mode, process command lines include `--date 2026-06-27 --no-price-history --no-websocket-events`, and strict target-date audit returned `ok = true` for all 12 markets.
- Latest post-recovery shadow/operator drill: `data/mm_runs/2026-06-27/20260627T135111048558Z`, scored by `data/backtest/mm_paper_shadow_20260627T135111_after_clob_recovery_source_status_block.json`, with readiness `data/backtest/mm_live_readiness_20260627T135111_after_clob_recovery_source_status_block.json`. It emitted 132 quote-intent rows, 132 no-quote rows, 0 quote-permission rows, 0 live-permission rows, fill evidence `BLOCK` with `no_quote_legs`, and readiness `BLOCK` with 11 blockers. Source-status and countability remain the leading blockers.
- Latest post-recovery active-window paper-live-forward drill: `data/mm_runs/2026-06-27/20260627T135932865534Z`, scored by `data/backtest/mm_paper_paperlive_20260627T135932_after_clob_recovery_source_status_block.json`, with readiness `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json`. It emitted 132 quote-intent rows, 132 no-quote rows, 0 quote-permission rows, 0 live-permission rows, evidence mode `active_day_live_forward`, live-forward gate `BLOCK`, and readiness `BLOCK` with 11 blockers. First failing gate is still `source_status_degradation`; preflight remediation also reports 3 stale model rows and 1 stale/missing snapshot-model row. Paper score has 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, exchange economics `PASS`, paper freshness `PASS`, reward score 0, and no actual payout evidence. The run overlapped `INFO_EVENT_WU_CURRENT_PRINT` with event action `widen`, but the quote outcome stayed `NO_QUOTE_MISSING_PREFLIGHT`.
- Latest aggregate active-window paper-live-forward diagnostic: `data/backtest/mm_paper_paperlive_20260627_latest5_active_after_clob_recovery_source_status_block.json`, with readiness `data/backtest/mm_live_readiness_20260627_latest5_active_after_clob_recovery_source_status_block.json`. It selected four eligible active folders (`111731`, `112944`, `131743`, `135932`) from 84 discovered folders, found 528 quote rows, 0 quote-permission rows, 0 live permissions, 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, paper freshness `PASS`, no actual payout evidence, and readiness `BLOCK` with 11 blockers.
- Fixed-date CLOB supervisor safeguards: a focused safeguard now preserves fixed `target_date` through `market_microstructure ensure` restarts and preserves status-derived target date/enrichment flags through the operations-dashboard CLOB restart path. Start diagnostics now include target date/date-selection/enrichment settings. Current CLOB status is fixed-date, but future evidence should still recheck status, process command line, and strict target-date audit before interpreting quote permissions.

1. Diagnose current active-date quote starvation by market, band, side, known-edge state, model variant, promotion state, CLOB book freshness, and CLOB recon taxonomy. The latest Austin/Dallas/Houston subset blocks on stale/missing books despite passing preflight.
2. Repair or explain active-row known-edge/promotion coverage outside the currently accepted cells. The accepted map has a broad Dallas `harvest_only` row, but generated candidate-map rows remain diagnostic only until countable markouts support promotion.
3. Keep the current daily-roll paper-live-forward loop under observation; latest status was prior-target/post-settlement or scheduled-wait/noncountable, so it does not satisfy live-forward evidence.
4. Re-score the moving daily-roll folder only after a nonzero quote-permission interval and a fresh snapshot/CLOB/economics status check; if known-edge permission blockers dominate, treat active-row known-edge/promotion coverage as the next blocker.
5. Regenerate the full standard paper report after current active-day evidence is collected; do not rely on the legacy `mm_paper_report.json` if a dated standard artifact is newer.
6. Extend reward-score diagnostics into stronger payout evidence:
   - US: CLOB recon competitor-score calibration is now wired into `mm_paper` when recon coverage exists; next calibrate the recon score against actual campaign competitor/payout artifacts, not just local book depth.
   - International: add Q-one/Q-two/Q-min scoring with `c = 3.0` and midpoint edge cases if the operating surface changes.
   - Reconcile predicted reward payout against actual payout artifacts before live scaling.
7. Compare reward score against adverse-selection markouts, not against resting time alone.
