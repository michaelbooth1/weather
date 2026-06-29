# Market-Making Repo Audit

Date: 2026-06-26

Scope: repo-grounded audit for small-scale market-making preparation and liquidity-reward farming research. No live orders were placed or authorized.

## Executive Summary

The market-making stack is built with the right safety shape for a future small pilot: policy is separate from execution, exchange signing is injected, stale data fails closed, live mode is gated, and paper scoring separates conservative fills from queue-estimated fills.

The current evidence is still not ready for live reward farming. Latest all-market active-window paper-live-forward evidence is `data/mm_runs/2026-06-27/20260627T135932865534Z`, scored by `data/backtest/mm_paper_paperlive_20260627T135932_after_clob_recovery_source_status_block.json` with readiness `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json`. It is a no-go: `evidence_mode = active_day_live_forward`, paper freshness `PASS`, preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote rows, 0 quote-permission rows, 0 live-permission rows, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, and readiness `BLOCK` with 11 blockers. The latest all-market shadow/operator-drill comparator after CLOB recovery is `data/mm_runs/2026-06-27/20260627T135111048558Z`, scored by `data/backtest/mm_paper_shadow_20260627T135111_after_clob_recovery_source_status_block.json` with readiness `data/backtest/mm_live_readiness_20260627T135111_after_clob_recovery_source_status_block.json`; it preserves the same no-go. CLOB audit, exchange economics, and current observation-trigger runtime are no longer the immediate blockers, but all 12 markets are still blocked by source-status proof with `settlement_auth_failure_family_source_counts = {wu_history: 12}` and `source_status_settlement_auth_failures = 12`; the latest paper-forward preflight also shows 3 stale model rows and 1 stale/missing snapshot-model row.

The aggregate active-window paper-forward view does not improve the decision. `data/backtest/mm_paper_paperlive_20260627_latest5_active_source_status_block.json` selected the three eligible active-day live-forward folders from the bounded latest-five query and found 396 quote rows, 0 quote-permission rows, 0 live permissions, 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, total reward score 0, exchange economics `PASS`, and no payout evidence. Matching readiness `data/backtest/mm_live_readiness_20260627_latest5_paperlive_active_source_status_block.json` is still `BLOCK` with 11 blockers.

Historical context remains useful for diagnosing the next layer after source-status clears. After refreshing same-day metadata and exchange economics for the prior active daily-roll date, the 2026-06-25 shadow tick reached `preflight_status = PASS` but produced 0 quote-permission rows. After scoped-runtime fixes and supervisor restarts, a later stable post-settlement drill produced 1 non-countable Dallas harvest quote. An early 2026-06-26 shadow tick had current event metadata, CLOB, and exchange economics, but still produced 0 quote-permission rows because model snapshots were stale across 11 markets and Toronto lacked known-edge permission. After the snapshot/model loop caught up, a June 26 shadow tick passed preflight and produced 9 Dallas harvest-only quote permissions with 0 live-trade permissions. Later current-source active diagnostics were back to 0 countable quote-permission rows; the post-settlement moving loop can emit noncountable quote permissions but does not count toward live-forward evidence. The latest current-source active diagnostic `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` has 4,807 quote-intent rows, 0 quote legs, 0 quote-permission rows, 4,345 known-edge permission-blocked rows, 462 stale-input rows, and 1,243 event-gate-suppressed rows. After the `2026-06-27T03:18:39Z` retry window cleared, a safe forced ensure quarantined the stale folder and restarted the continuous paper loop onto current source at `2026-06-27T03:19:37Z`; later status became `idle_process` / `blocked_restart_required`, target date `2026-06-26`, expected target `2026-06-27`, and `STALE_HEARTBEAT_METADATA`, so it remains prior-target/noncountable evidence. The current-source event-window shadow tick `data/mm_runs/2026-06-26/20260627T004704070519Z` passed preflight across all 12 markets and produced 0 quote-permission rows because of known-edge and information-event gates; the later post-event current-source shadow tick `data/mm_runs/2026-06-26/20260627T010734537264Z` produced 6 noncountable harvest-only quote permissions and 0 live-trade permissions; and the latest regenerated recovered paper-live-forward post-settlement score `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json` captured 17 noncountable quote permissions, 34 quoted legs, and 0 live-trade permissions. That latest recovered score still has 0 conservative fills, 2 queue-estimated fill legs, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 4,148 missing-size trade rows, 1 missing-book queue leg, and 34 unresolved resting quotes. Its counterfactual reward calculation now uses auto-built CLOB recon competitor evidence: competitor score 112.133982 from 19,019 book rows and 946 slices, producing reward score 89.72025 and counterfactual reward 444.480401 USDC. After source-status proof clears, the next blockers remain active-row known-edge/promotion coverage outside the currently allowed cells, nonzero countable live-forward paper quotes, fill-evidence completeness, active-day settlement/resting-quote resolution, post-settlement noncountability, and promotion-grade P&L evidence.

The next-date June 27 probe remains fail-closed, but the blocker has moved forward. Event metadata passes for all 12 markets, after rechecking official Polymarket US docs the June 27 exchange-economics snapshot is accepted with no material drift, and the latest explicit fixed-date CLOB audit passed after recovery. The latest all-market active-window paper-forward run `data/mm_runs/2026-06-27/20260627T135932865534Z` has preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-permission rows. Its diagnostic score `data/backtest/mm_paper_paperlive_20260627T135932_after_clob_recovery_source_status_block.json` has exchange economics `PASS`, 132 quote rows, 0 quote legs, fill evidence `BLOCK`, reward score 0, and actual payout evidence false. Target-date-aligned readiness `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json` remains `BLOCK` with 11 blockers and `live_capital_permission = false`; it records `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}` and optional provider status fields false/redacted. Earlier 041123/055820/073107/124837/125739/130826/135111 runs are historical or shadow diagnostics for discovery, CLOB, known-edge, quote-emission, watcher recovery, and CLOB recovery behavior, not live readiness.

The immediate objective should be quote-starvation diagnosis under fresh active-day data, not live order placement.

## Current Evidence

For the current requirement-by-requirement completion state, see `docs/research/MM_GOAL_COMPLETION_AUDIT_2026-06-26.md`. It keeps the active-goal verdict at `NO LIVE CAPITAL`.

Commands and results from this pass:

- Latest focused maker/operations suite:
  `.\venv\Scripts\python.exe -m pytest tests\operations\test_market_making_daily_roll.py tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q`
  - Result: 123 passed, 5 subtests passed.
- Latest syntax check:
  `.\venv\Scripts\python.exe -m py_compile src\weather\operations\market_making_daily_roll.py src\weather\market\market_making_run.py src\weather\market\mm_policy.py src\weather\market\mm_paper.py src\weather\market\mm_paper_reports.py`
  - Result: passed.
- Focused v0.3 policy/orchestrator regression:
  `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_market_making_run.py -q`
  - Result: 60 passed, 5 subtests passed.
- Broader maker/exchange/platform/operations suite after the v0.3 diagnostic-field update:
  `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py tests\operations\test_market_making_daily_roll.py -q`
  - Result: 127 passed, 5 subtests passed.
- Runtime/snapshot identity tests after the scoped runtime guard fix:
  `.\venv\Scripts\python.exe -m pytest tests\operations\test_runtime_identity.py tests\collection\test_loop_supervisor.py tests\collection\test_collection_robustness.py -q`
  - Result: 44 passed.
- Strict CLOB audit:
  `.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict`
  - Result: `ok: true`, 12 markets ok, 0 counted gaps over threshold.
- Location and event metadata refresh:
  `.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json`
  - Result: 51 locations, 119 events.
- Active-date event metadata validation:
  `.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-25 --markets all`
  - Result: `PASS`.
- Active-date exchange economics:
  `.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-25 --platform polymarket_us --accept`
  - Result: `PASS`, accepted snapshot `xecon-036874d19e56c76f`.
- Active-date keyless shadow tick:
  `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-25 --budget-usdc 500 --mode shadow --markets all --once`
  - Run: `data/mm_runs/2026-06-25/20260626T014113607834Z`.
  - Result: `preflight_status = PASS`, `row_count = 132`, `quote_permission_rows = 0`, `live_trade_permission_rows = 0`.
  - First failing gate: `policy`.
  - Root cause class: `policy_no_edge`.
  - Reason counts: `NO_QUOTE_KNOWN_EDGE_PERMISSION = 121`, `NO_QUOTE_MISSING_BOOK = 10`, `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED = 1`.

The initial 2026-06-26 shadow tick was useful as a future-date drill, but not as active-day proof. It had event metadata and exchange economics `PASS`, yet all 12 markets blocked on missing active current market rows, missing snapshot/model rows, empty CLOB token files, missing CLOB books/features, and missing reward metadata because no June 26 snapshot folders existed while the active loops were still on June 25.

The earlier 2026-06-26 current-date shadow tick `data/mm_runs/2026-06-26/20260626T132648384687Z` showed the next blocker after CLOB and economics recovered:

- CLOB status/audit: `RUNNING`, strict audit `ok: true`.
- Event metadata validation: `PASS`.
- Exchange economics: `PASS`, accepted for `2026-06-26`.
- Preflight status: `WARN`.
- Quote rows / quote permissions / live-trade permissions: 132 / 0 / 0.
- First failing gate: `model_freshness`.
- No-quote reasons: 121 `NO_QUOTE_STALE_INPUT`, 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Bounded paper score: 0 quote legs, 0 conservative fills, 0 queue-estimated fills, reward score 0, freshness `NO_ACTIVE_DAY`.

The latest 2026-06-26 current-date shadow tick `data/mm_runs/2026-06-26/20260626T134201734227Z` shows model freshness can clear without weakening gates:

- CLOB status/audit: `RUNNING`, strict audit `ok: true`.
- Event metadata validation: `PASS`.
- Exchange economics: `PASS`, accepted for `2026-06-26`.
- Preflight status: `PASS`.
- Quote rows / quote permissions / live-trade permissions: 132 / 9 / 0.
- Quoted cells: 9 Dallas harvest-only two-sided rows, 18 paper-posted lifecycle legs, 15.3055 USDC reserved shadow risk.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`.
- Bounded paper score: 18 quote legs, 0 conservative fills, 0 queue-estimated fills, reward score 12.26505, counterfactual reward 109.2508 USDC, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`.
- Fill blockers in the bounded score: 784 missing-size trade rows and 18 unresolved resting quotes because active-day settlement evidence was not available.

The active 2026-06-26 daily-roll folders remain the current diagnostic evidence stream, with countable active-window evidence separated from the recovered post-settlement loop:

- Latest daily-roll status check after the guarded recovery: `started`, PID 29180, target date `2026-06-26`, mode `paper-live-forward`, evidence mode `post_settlement_evaluation`, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, `current_counts_toward_live_forward_gate = false`, latest run folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, latest tick rows 132, supervisor state `RUNNING`, supervisor action `noop`, and runtime identity matching current source. The process is alive and writing, but it is after-window/noncountable evidence.
- Moving-folder tick state is not stable evidence: an earlier recovered `run_summary.json` read saw 2 quote-permission rows, while the final status read saw 0 quote-permission rows, 0 live-trade-permission rows, preflight `PASS`, first failing gate `policy`, and reason split 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 39 `NO_QUOTE_MISSING_BOOK`, and 5 `NO_QUOTE_STALE_BOOK`. Treat fixed paper-score artifacts as evidence, not a single moving tick.
- Current snapshot tracker status was `RUNNING` at the latest source-status check, heartbeat and last snapshot age were fresh, and source-status proof had 0 blocked markets. The same status still had `action_required = 12` because June 26 snapshot cadence and early-hour coverage proofs were `BLOCK` across the fleet due historical same-day gaps. Fresh loop liveness is not the same thing as countable full-day coverage.
- Previous fixed bounded diagnostic score: `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`, with 4,092 quote-intent rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, 4,070 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 22 `NO_QUOTE_STALE_INPUT` rows.
- Default map coverage drift: the current accepted `data/backtest/mm_known_edge_map.json` has only 17 records: 7 `harvest_only`, 3 `edge_research`, and 7 `no_quote`. It includes a broad Dallas `harvest_only` record, so Dallas is now mostly blocked by missing books, information-event windows, stale input, and cadence degradation rather than known-edge permission. The generated candidate map from the latest score has 217 records, but it is diagnostic only and must not be promoted without countable paper markouts.
- Previous bounded quote diagnostic from the active daily-roll tape before `mm_quote_intent_v0.3`: `data/backtest/mm_paper_active_latest_20260626_quote_diag.json`, from `data/mm_runs/2026-06-26/20260626T160337445814Z`, scored 4,224 accumulated quote rows, 0 quote legs, 0 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, 3,916 known-edge permission-blocked rows, 308 stale-input rows, 44 event-gate-suppressed rows, and `mm_quote_blocker_diagnostics_v0.7`. That historical diagnostic loaded the then-current 238-record known-edge map and found 0 inferred known-edge record matches. The current accepted map has 17 records, so use current-map diagnostics for present readiness decisions. This historical diagnostic skipped fill simulation and model-variant scoring, so it is quote-blocker evidence only.
- v0.3 quote-schema probe: `%TEMP%\weather-mm-v03-probe\2026-06-26\codex-v03-probe` wrote `mm_quote_intent_v0.3` quote rows with `known_edge_match_*` fields. The final generated diagnostic `data/backtest/mm_paper_v03_probe_20260626_quote_diag.json` has 132 blocked rows, 0 quote-permission rows, 88 known-edge permission-blocked rows, 44 stale-input rows, and 0 event-gate-suppressed rows after moving model-freshness inputs aged into `WARN`. This confirms the new fields are diagnostic-only and the active coverage/freshness gap remains.
- Current-source v0.3 event-window shadow probe: `data/mm_runs/2026-06-26/20260626T165003338813Z` ran keyless `shadow --once` with preflight `PASS` and scored to `data/backtest/mm_paper_shadow_20260626T165003338813Z_v03_current.json`. It had 132 blocked rows, 0 quote-permission rows, 132 known-edge permission-blocked rows, 0 stale-input rows, 132 event-gate-suppressed rows, 0 inferred known-edge record matches, and 66 inferred misses. Its top blocker overlaps were all `INFO_EVENT_METAR_PRINT`, so this proves the current source writes exact diagnostics and pulls quotes during information events; it does not improve the live-readiness conclusion.
- Current-source v0.3 WU/SWOB shadow probe: `data/mm_runs/2026-06-26/20260626T170013329405Z` scored to `data/backtest/mm_paper_shadow_20260626T170013329405Z_v03_current.json` with 132 blocked rows, 0 quote-permission rows, 121 known-edge permission-blocked rows, 11 stale-input rows, 11 event-gate-suppressed rows, 0 inferred known-edge record matches, and 66 inferred misses. Preflight was `WARN` on `model_freshness`, led by a stale Seattle model snapshot.
- Current-source active daily-roll score after the v0.8 backoff recheck: `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` selected `data/mm_runs/2026-06-26/20260626T231738340378Z` and scored 4,807 quote rows, 0 quote legs, 0 quote-permission rows, 4,345 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 462 `NO_QUOTE_STALE_INPUT` rows, 1,243 event-gate-suppressed rows, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, fill evidence `SKIPPED (skip_fill_simulation)`, and model-variant scoring `SKIPPED (skip_model_variants)`. This is active-folder blocker evidence only; the current running loop is post-settlement and noncountable.
- Pre-recovery fixed paper-live-forward post-settlement score: `data/backtest/mm_paper_postsettlement_latest_20260627T020932_current_source.json` selected `data/mm_runs/2026-06-26/20260627T011838375104Z` and scored 5,016 quote rows, 118 quote-permission rows, 0 live-trade-permission rows, 236 quote legs, 0 conservative fills, 6 queue-estimated fill legs, reward score 625.5215, counterfactual reward 862.168109 USDC, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 7,084 missing-size trade rows, 50 missing-book queue legs, and 236 unresolved resting quotes. The top no-quote reasons were 2,926 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 950 `NO_QUOTE_MISSING_BOOK`, 473 `NO_QUOTE_STALE_INPUT`, 440 `NO_QUOTE_INFORMATION_EVENT`, and 109 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`. This is current-source scoring code over a stale-runtime, post-settlement folder, so it is diagnostic only.
- Latest regenerated recovered paper-live-forward post-settlement score: `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json` selected `data/mm_runs/2026-06-26/20260627T021842583677Z` and scored 1,320 quote rows, 17 quote-permission rows, 0 live-trade-permission rows, 34 quote legs, 0 conservative fills, 2 queue-estimated fill legs, reward score 89.72025, counterfactual reward 444.480401 USDC, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 4,148 missing-size trade rows, 1 missing-book queue leg, and 34 unresolved resting quotes. The counterfactual reward share used `clob_recon_policy_parameter_suggestions.reward_competitor_q` with competitor score 112.133982 from 19,019 CLOB book rows and 946 recon slices. This confirms current scoring code can replay the recovered folder, find nonzero paper quote permissions, and surface CLOB-calibrated reward-share diagnostics, but it is still post-settlement/noncountable and not promotion evidence.
- Current target-date machine-readable live-readiness artifact: `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json` (`weather.market.market_making_readiness`) returned `BLOCK` with 11 blockers against June 27 active-window paper-live-forward evidence. It records `live_capital_permission = false` even in a hypothetical all-green technical state, because live capital still requires explicit operator authorization. Current summary: preflight `BLOCK` on `source_status_degradation`, 0 quote permissions, 0 live permissions, fill evidence `BLOCK` with `no_quote_legs`, no countable active-day quote/fill evidence, missing `data/backtest/live_readiness.json`, and fail-safe `data/backtest/mm_platform_verification.json` schema `mm_platform_verification_v0.2` with all operator/API proofs plus all five `secret_redaction_*` proofs missing.
- June 27 next-date shadow score: `data/backtest/mm_paper_shadow_20260627T003709708211Z_nextdate_probe.json` selected `data/mm_runs/2026-06-27/20260627T003709708211Z` and scored 12 quote rows, 0 quote legs, 0 quote-permission rows, 12 `NO_QUOTE_MISSING_PREFLIGHT` rows, paper freshness `NO_ACTIVE_DAY`, exchange-economics gate `BLOCK`, and fill evidence `SKIPPED (skip_fill_simulation)`.
- Current-source shadow check after canonicalizing known-edge record hours: `data/mm_runs/2026-06-26/20260626T172330853600Z` had preflight `WARN` on `model_freshness`, 132 quote rows, 0 quote-permission rows, 99 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 33 `NO_QUOTE_STALE_INPUT` rows, and 0 live-trade-permission rows. The hour-format fix did not create quote permission.
- Current-source keyless shadow check during `INFO_EVENT_METAR_PRINT`: `data/mm_runs/2026-06-26/20260627T004704070519Z` passed preflight across all 12 markets with fresh source/CLOB rows and wrote 132 quote rows, 0 quote-permission rows, and 0 live-trade-permission rows. Its score `data/backtest/mm_paper_shadow_20260627T004704070519Z_current_source.json` has 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 44 `NO_QUOTE_INFORMATION_EVENT`, 132 event-gate-suppressed rows during `INFO_EVENT_METAR_PRINT`, 0 stale-input blockers, 0 inferred known-edge record matches, 11 inferred misses, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, fill evidence `SKIPPED`, and reward score 0.
- Latest current-source keyless shadow check after the event gate cleared: `data/mm_runs/2026-06-26/20260627T010734537264Z` passed preflight across all 12 markets with fresh source/CLOB rows and wrote 132 quote rows, 6 quote-permission rows, and 0 live-trade-permission rows. Its score `data/backtest/mm_paper_shadow_20260627T010734537264Z_current_source.json` has 12 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 34 `NO_QUOTE_MISSING_BOOK`, 4 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, 6 `QUOTE_HARVEST_MID`, reward score 26.8405, counterfactual reward 211.60828 USDC under default pool/competition assumptions, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, and fill evidence `BLOCK`.
- Operator-report recovery visibility is now fixed: `operator_report` includes supervisor state/action/intended action/retry time/runtime-identity match fields when the persisted status contains `daily_roll_supervisor`. It now also falls back to `daily_roll_supervisor.recovery_guard.remediation` when the guard owns the actionable remediation text. The latest live status read exposes `RUNNING`/`noop`, PID 29180, runtime identity matching current source, useful-write liveness passing, live-forward gate `BLOCK`, and `current_counts_toward_live_forward_gate = false`.

## Architecture Map

- `src/weather/market/mm_policy.py`
  - Pure quote-intent logic. It emits quote/no-quote rows and reason codes such as `NO_QUOTE_KNOWN_EDGE_PERMISSION`, `NO_QUOTE_MISSING_BOOK`, and `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`.
  - It does not own signing, credentials, or exchange mutation.
- `src/weather/market/market_making_run.py`
  - Run-folder orchestrator. It loads target-date artifacts, preflight gates, useful-work liveness, exchange economics, budget ledgers, lifecycle rows, reports, and run summaries.
  - It records `quote_permission_rows` and `live_trade_permission_rows`, and guards against live-trade permission outside `live-pilot`.
- `src/weather/market/market_making_run_support.py`
  - Shared run support. It defines the `live-pilot` gate path, active-event gate, exchange-economics gate integration, budget reservation behavior, and mode-dependent live permission.
- `src/weather/market/mm_risk.py`
  - Risk and sizing decisions. It models quote permission, per-band and event-level risk, reserve acceptance, halts, and risk events.
- `src/weather/market/mm_exchange.py`
  - Exchange adapter boundary. It builds redacted request plans, keeps signers injected, checks credential diagnostics, requires `--allow-live` for live execution, and supports post-only or participate-dont-initiate semantics.
  - Adapter diagnostics now disclose platform-specific live-readiness requirements. For Polymarket US they explicitly call out private WebSocket order reconciliation, cancel-all zero-open-order confirmation, latency-stopgap reject handling, and external API-key/platform eligibility.
  - Polymarket US private WebSocket order-update fixtures are normalized into existing lifecycle/fill rows, covering fill, canceled, rejected, expired, and replaced states without requiring live credentials.
  - MM-2 cancel-all probe status now requires structured zero-open-order proof after a cancel-all request. A generic canceled lifecycle event is not enough.
- `src/weather/market/mm_paper.py` and `src/weather/market/mm_paper_scoring.py`
  - Paper fill and scoring stack. Conservative fills remain separate from queue-estimated companion evidence, which is correct for promotion discipline.
- `src/weather/market/exchange_economics.py`
  - Versioned economics gate for fee, rebate, reward, tick-size, minimum-order, and order-semantics assumptions. It blocks stale/mismatched target-date snapshots and produces drift/rescore blockers.
- `src/weather/market/market_microstructure.py`
  - CLOB capture, status, strict audit, and raw-refresh tooling.
- `src/weather/market/clob_recon.py`
  - Reward competition, executable depth, book-quality, and passive markout analysis.
- `src/weather/market/info_event_calendar.py`
  - Scheduled high-information event windows and quote-pull gates.
- `src/weather/operations/event_metadata_validation.py`
  - Target-date event metadata validation.
- `src/weather/operations/location_config_refresh.py`
  - Safe same-day metadata refresh path.
- `src/weather/collection/snapshot_store.py` and `src/weather/collection/snapshot_tracker.py`
  - Snapshot/model persistence and runtime-identity guards.

## Roadmap Crosswalk

Relevant roadmap items are consistent with the current audit result:

- Item 43: policy and quote-intent tape exist.
- Item 44: paper trading, queue simulation, markouts, and incentive accounting exist, but promotion still depends on complete evidence.
- Item 45: software live gates exist; live order submission remains blocked without platform/account proof.
- Item 46: date-budget-market run orchestration exists.
- Item 55: order lifecycle and budget reconciliation exist.
- Item 56: cockpit and drilldown diagnostics exist.
- Item 57: preflight remediation and active-day reliability exist.
- Item 66: CLOB book recon and reward competition analytics exist.
- Item 67: authenticated adapter boundary exists, but real MM-2 live-account probes and paid-vs-predicted evidence remain open because credentials and eligible account evidence are absent.
- Item 68: information-event quote-pull gates exist.
- Item 277: all-market useful-work liveness exists.
- Item 278: maker model-version shadow bakeoff exists.
- Item 279: clustered statistical promotion gate exists.
- Item 280: fill-evidence completeness gate exists, and the current standard report is still blocked by incomplete fill evidence.
- Item 282: parallel raw CLOB refresh exists.
- Item 300: current exchange-economics and rule-drift gate exists.
- Item 304: current-run selection and quote-starvation gate exists. The active-date shadow run is now exactly the kind of quote-starvation case this item is meant to classify.

## Safety Properties

Verified or strongly evidenced:

- Shadow mode did not emit live-trade permission: the active-date run had `live_trade_permission_rows = 0`.
- Policy fail-closed behavior is working: missing future-date artifacts produced 12 no-quote rows and no permissions; stale current-date model snapshots produced 132 no-quote rows and no permissions; prior active-date policy uncertainty produced 132 no-quote rows and no permissions; later post-settlement evidence produced only 1 non-countable quote and no live permission.
- Exchange economics is target-date gated: the snapshot now validates for target date `2026-06-26` and platform `polymarket_us`.
- Event metadata is target-date gated: active-date validation is now `PASS`.
- CLOB strict audit passed at check time across 12 markets.
- Exchange signing remains external/injected through request-plan and adapter boundaries.
- Live-pilot mode remains behind explicit operator flags, live-readiness, data-layer gate, platform/account verification, credential diagnostics, and `--allow-live`.
- The platform-verification gate now requires `mm_platform_verification_v0.2`, including maker-only field proof, private-stream lifecycle/fill/final-state reconciliation, cancel-all zero-open-order confirmation, and US latency-stopgap handling proof.
- Runtime identity is now scoped correctly for snapshot persistence: `snapshot_store.py` now compares the process identity against `current_identity_for(process_identity)`, matching the scoped identity design already used in `snapshot_tracker.py`.

Still blocked:

- Quote permissions remain sparse and mostly non-countable: an earlier current-date `shadow` run produced 9 Dallas harvest-only quote permissions, later current-source shadow probes ranged from 0 to 6 noncountable permissions, the prior active-day daily-roll folder still has 0 quote-permission rows, and the latest recovered post-settlement fixed score has 17 noncountable quote-permission rows.
- The earlier `pid_missing` / `blocked_restart_required` daily-roll state was repaired, and a later snapshot-loop stale interval was recovered. Daily-roll status now filters artifact/activity liveness by expected mode and evidence mode, reads the latest folder's `live_forward_gate.json`, and exposes `current_counts_toward_live_forward_gate` so a blocked gate cannot be hidden by the start-time evidence classification. After the latest source edits and retry-window recovery, the paper loop is alive on current source; useful-work is `SKIPPED`, live-forward liveness is `BLOCK`, and quote permissions are noncountable post-settlement evidence.
- Active-row known-edge/promotion coverage remains the immediate quote blocker outside the currently allowed cells: the accepted map has a broad Dallas `harvest_only` record, but other markets remain blocked by `promotion_block` or `missing_known_edge_record`, while Dallas itself is now mostly blocked by missing books, event gates, stale input, and cadence degradation.
- The standard paper report has `fill_evidence_completeness.status = BLOCK`.
- Standard reward estimate remains 0, so reward-farming economics are not yet measured in a useful way.
- Model variant promotion remains blocked by evidence gates.
- No 14 consecutive countable paper days with locked policy hash have been proven in this pass.
- No real account/platform eligibility, user-stream, cancel-all, isolated-wallet, paid-rebate, paid-reward, or settlement-P&L evidence exists for a live pilot.
- US private WebSocket order-update parsing, latency-stopgap handling, and structured cancel-all zero-open-order proof now have adapter/report-level fixture coverage, but no live or account-backed probe has shown correct behavior for real order updates, real cancel-all, new-order rejects, cancel-replace rejects, and pure cancel exemption under elevated latency.

## Findings

1. The first-pass blocker moved from stale target-date metadata/economics to quote starvation.

   After refreshing active-date metadata and economics, preflight passed for the active June 25 roll. The active blocker is now policy/no-edge: 121 of 132 rows were suppressed by `NO_QUOTE_KNOWN_EDGE_PERMISSION`.

2. Missing-book and cadence reasons need targeted repair before interpreting quote starvation as purely rational abstention.

   The active run had 10 `NO_QUOTE_MISSING_BOOK` rows and 1 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED` row. Those are infrastructure/data-quality blockers mixed into an otherwise policy-driven no-quote day.

3. Future-date validation can pass while data folders are absent, and later model freshness can recover without weakening gates.

   The first June 26 shadow tick showed event metadata and economics can validate for the target date, while preflight correctly blocked when snapshots, source-status rows, token files, books, features, and reward metadata were not present. The next June 26 shadow tick showed CLOB and economics recovered, but model freshness still blocked 11 markets. The latest June 26 shadow tick then passed preflight and emitted only 9 Dallas harvest-only quote permissions, proving the stale-model gate can clear while known-edge and evidence gates still prevent broader quoting.

4. Active-row known-edge map coverage drift explains why the countable daily roll did not reproduce the broad Dallas shadow quotes.

   The accepted `mm_known_edge_map.json` now has a broad Dallas `harvest_only` record, and the latest moving folder shows 1 Dallas `QUOTE_HARVEST_MID` row. The remaining Dallas rows fail closed on missing books, information-event windows, stale input, and cadence degradation. Do not replace the accepted 17-record map with the 217-record generated candidate map unless countable active-row evidence proves the permission is valid.

5. The economics snapshot is not a live API readiness proof.

   The accepted snapshot still matches the core Polymarket US fee/reward assumptions rechecked on June 26, 2026, but the official US docs add two important constraints outside core maker scoring: temporary high-volume taker rebates must not be counted without account-level eligibility and payout proof, and API readiness requires `participateDontInitiate` maker-only order entry, private WebSocket order reconciliation, cancel-all followed by zero-open-order confirmation, rate-limit discipline, and 5-second latency-stopgap reject handling. `mm_exchange.py` now surfaces these as live-readiness notes, normalizes US private-stream order-update fixtures into lifecycle/fill evidence, and classifies documented US latency-stopgap order rejects as no-acceptance stale-price protection rather than ordinary rate-limit backoff. `market_making_preflight.py` now fails live-pilot unless the v0.2 platform-verification artifact records those proofs.

6. A runtime-identity guard bug blocked forced snapshots before this pass.

   `snapshot_store.py` had been comparing scoped process identity to whole-tree current identity, causing `stale_code` even when the loaded-code scope was current. The narrow fix uses `current_identity_for(process_identity)`. Focused runtime/collection tests passed after the fix, and a forced snapshot wrote for the active June 25 event.

7. Reward-farming optimization is under-specified locally.

   The repo records Polymarket US reward mechanics, including `score = discount_factor ** ticks_from_best_price * order_size`, and the bounded paper report now exposes score/share diagnostics plus counterfactual payout attribution. The next simulation should calibrate competitor score from reward competition data and reconcile predicted payout against actual payout artifacts.

## Continuation Update

After this audit was first written, two scoped runtime-identity fixes were completed:

- `src/weather/market/market_making_run.py` now compares supervisor loop identities against `current_identity_for(process)` instead of the whole source tree.
- `src/weather/runtime_identity.py` now lets `current_identity_for(recorded)` use `recorded["repo_root"]` when no explicit root is passed.
- `tests/market/test_market_making_run.py` now has a regression covering scoped loop identities.

Validation:

- `.\venv\Scripts\python.exe -m pytest tests\market\test_market_making_run.py tests\operations\test_runtime_identity.py -q` -> 36 passed.
- `.\venv\Scripts\python.exe -m py_compile src\weather\runtime_identity.py src\weather\market\market_making_run.py src\weather\collection\snapshot_store.py src\weather\collection\snapshot_tracker.py src\weather\market\market_microstructure.py` -> passed.

Operational follow-up:

- Restarted the snapshot, CLOB, and observation-trigger supervisors so they run current code.
- Ran `weather.operations.market_making_daily_roll ensure`; it restarted the stale-code daily roll and quarantined the previous active run.
- That first restarted daily roll began after the local active evidence window, so it was `post_settlement_evaluation` and did not count toward live-forward gates.
- Later, during the June 26 active window, the daily roll was explicitly restarted in `paper-live-forward` mode. A later snapshot-loop stale interval was recovered with `weather.collection.snapshot_tracker --ensure`; follow-up daily-roll status is healthy and countable, with latest useful writes less than a minute old.

Latest stable one-shot:

- Run folder: `data/mm_runs/2026-06-25/20260626T020148684548Z`.
- Evidence mode: `post_settlement_evaluation`.
- Preflight: `PASS`.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 10 `NO_QUOTE_MISSING_BOOK`, 1 `QUOTE_HARVEST_MID`.
- Interpretation: current blocker is mostly quote starvation under policy/evidence gates, not stale inputs. One Dallas harvest quote appears post-settlement but is not countable live-forward evidence; the repaired active-day daily roll is countable but has not emitted quote permission.

Latest active daily-roll score:

- `weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T135556165467Z --skip-model-variants` completed and wrote `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`.
- Result: 4,092 quote-intent rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, 4,070 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 22 `NO_QUOTE_STALE_INPUT` rows.
- New `mm_quote_blocker_diagnostics_v0.8` output reads exact known-edge match fields when quote tapes provide them, and otherwise falls back to legacy row fields plus explicitly labeled inference. The pre-v0.3 active-loop report showed missing-known-edge active rows clustered at `hour_utc = 15`, `band_distance_bucket = (missing)`, `casebook_taxonomy = (missing)`, `regime = none`, `source_freshness_state = all_fresh`, and `book_imbalance_bucket = (missing)`. The v0.8 diagnostic-only inferred table surfaces likely active buckets such as `edge_lt_1c`, `edge_3c_8c`, `edge_ge_8c`, `bid_heavy`, `ask_heavy`, and `balanced` without changing quote permission. It also canonicalizes known-edge record hours such as `17:00Z` to `17` and adds coverage action items that distinguish promotion gates from missing-map evidence work.
- Interpretation: the active daily roll is useful liveness evidence but not quote, fill, reward, or promotion evidence. The default known-edge map needs active-row coverage work before the daily roll can reproduce the earlier Dallas shadow quote permissions.

Bounded paper-score follow-up:

- `weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z` completed and wrote `data/backtest/mm_paper_quote_starvation_20260626T020148684548Z.json`.
- Result: 132 quote rows, 2 quote legs, 0 conservative fills, 0 queue-estimated fill legs, gate `OPEN`, paper score freshness `NO_ACTIVE_DAY`, fill evidence status `BLOCK`, and 0 P&L/reward/rebate estimates.
- The latest diagnostic known-edge map has 217 records: 177 `harvest_only`, 37 `no_quote`, and 3 `edge_research`.
- First-class bounded selection was added to `weather.market.mm_paper`: `--target-date` / `--run-target-date`, `--evidence-mode`, and `--latest-n`.
- Bounded reports now disclose `diagnostic_selection_not_full_corpus` in their summary so they are not confused with standard full-corpus evidence.
- Smoke run `data/backtest/mm_paper_bounded_latest_postsettlement_20260626.json` selected `data/mm_runs/2026-06-25/20260626T015632370043Z`: 4,488 quote rows, 52 quote legs, 5 conservative fills, 0 queue-estimated fill legs, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, net -0.00974 USDC, reward estimate 0.
- Reward-score diagnostics were added to `weather.market.mm_paper` and the paper report. The bounded smoke report scored 52 quoted legs under the Polymarket US discount-factor/ticks formula, with total reward score 141.7, score/target-size 0.01417, and counterfactual reward 586.263964 USDC under campaign-pool 1000 and competitor-score 100 assumptions.
- `--skip-model-variants` was added for faster operational paper diagnostics. A skip-variant smoke report completed in 3.9 seconds at smoke-check time, selected the same growing post-settlement run, and disclosed model-variant scoring `SKIPPED (skip_model_variants)` with 5,148 quote rows, 62 quote legs, 7 conservative fills, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, and net -0.013636 USDC.
- `--skip-fill-simulation` was added for full-corpus quote/no-quote/reward diagnostics. A full summary-only report completed in about 176 seconds with 36 included run folders, 628,481 quote rows, 71,828 quote legs, 35,914 quote-permission rows, reward score 165,800.676275, counterfactual reward 999.39723 USDC, paper freshness `PASS`, fill evidence `SKIPPED`, and model-variant scoring `SKIPPED`.
- `mm_paper_scoring.py` now caches per-token timestamp indexes, streams the large disagreement casebook, drops full quote-row references from quote legs after reward estimates are attached, and releases the full quote-row corpus before fill simulation. A full-corpus standard report with model variants enabled now wrote `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`: 636,005 quote rows, 71,836 quote legs, 44 conservative fills, 13,045 queue-estimated fill legs, freshness `PASS`, fill evidence `BLOCK`, reward score 165,822.476275, model-variant scoring `PASS`, 39,534 model-variant quote rows, 264 model-variant quote legs, 32 model-variant conservative fills, and model-variant promotion `BLOCK`.
- The standard report now renders focused fill-evidence blockers. Current fill blockers are 8,893 missing-size trade rows, 2,182 missing-book queue legs, and 26 missing-trade-size queue legs. The largest missing-size events are Dallas June 25, Denver June 23, Denver June 21, Austin June 23, Atlanta June 21, and Houston June 21. The largest missing-book queue slices are early-hour `YES_ASK` rows, led by Los Angeles `70-71 F` at `02:00Z`, Houston `88-89 F` at `02:00Z`, and Dallas `92-93 F` at `02:00Z`.
- Bounded latest active-day promotion-grade scoring selected `data/mm_runs/2026-06-25/20260626T015448206993Z`: 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, freshness `PASS`, fill evidence `PASS` only because no quotes existed, reward score 0.
- Paper reports now include quote-blocker diagnostics. The latest pre-v0.3 active-day report showed 4,224 blocked rows, 3,916 known-edge permission-blocked rows, 308 stale-input rows, 44 event-gate suppressed rows, 0 quote-permission rows, 0 quote uptime, and `mm_quote_blocker_diagnostics_v0.7`. The prior accumulated v0.8 active-day report showed 31,284 blocked rows and 0 quote-permission rows before that folder was quarantined. The current-source active daily-roll backoff recheck now shows `mm_quote_blocker_diagnostics_v0.8`, 4,807 blocked rows, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, 0 quote-permission rows, and 0 quote uptime. The v0.8 report adds diagnostic-only coverage action items, diagnostic-only required-action buckets, and canonicalizes known-edge record hours such as `17:00Z` to `17`; the current action items still require promotion-gate progress or countable markouts before any map change.
- Bounded paper scoring now enforces the selected run's target date for exchange-economics gates when no completed active-day freshness date exists. The June 26 shadow report proves economics target-date match for `2026-06-26` instead of silently checking with no target date.
- The full historical fill/queue/markout path can now produce a standard model-variant report on current artifacts, but it is still not promotion-grade live-prep evidence because fill evidence is `BLOCK`, locked policy params are false, live-forward paper days are only 2, and model-variant promotion is `BLOCK`.

## Go / No-Go

Current decision: NO-GO for live orders.

PASS:

- Focused maker tests.
- Runtime/snapshot guard tests after the fix.
- Strict CLOB audit at check time.
- Active-date event metadata validation.
- Active-date Polymarket US exchange-economics snapshot and accepted baseline.
- Active-date shadow preflight.
- Shadow/live-permission separation.
- Bounded paper-score CLI for diagnostic target-date/latest-N scoring.
- Skip-model-variants paper diagnostics with explicit `SKIPPED` disclosure.
- Skip-fill-simulation full-corpus diagnostics with explicit `SKIPPED` disclosure.

WARN:

- CLOB and daily-roll processes can look alive while useful-work liveness is blocked.
- Paper P&L is small and 30-minute adverse selection is negative in the current standard report.
- Queue-estimated fills are much larger than conservative fills and remain diagnostic, not promotion-grade.
- Bounded post-settlement scoring is now fast, but it is diagnostic-only unless it exactly covers the intended countable evidence set.
- Standard model-variant scoring now runs, but promotion remains blocked by insufficient independent target-day evidence and no positive lower-bound net-P&L delta versus served current.
- Skip-fill-simulation scoring makes full-corpus quote/reward inspection possible, but omits conservative fills, queue companion, markouts, P&L, and fill-evidence gates by design.
- Reward-score and counterfactual payout diagnostics are present, but actual payout and competitor-score calibration remain unproven.

BLOCK:

- Sparse quote permissions: 9 Dallas harvest-only rows appeared in an earlier `shadow` drill, while the latest recovered fixed paper-live-forward post-settlement score has 17 noncountable quote-permission rows and 0 live-trade-permission rows. The latest active-folder bounded quote diagnostic still has 4,807 rows with 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, and 0 quote uptime.
- Active-row known-edge/promotion coverage: the accepted map now has a broad Dallas `harvest_only` row, but other markets remain blocked by `promotion_block` or `missing_known_edge_record`, and Dallas is mostly blocked by missing books, event gates, stale input, and cadence degradation.
- Latest regenerated recovered post-settlement score still has fill evidence `BLOCK`: 4,148 missing-size trade rows, 1 missing-book queue leg, and 34 unresolved resting quotes.
- Daily-roll liveness is repaired, but countable live-forward evidence still has no quote permissions.
- Missing-book and snapshot-cadence no-quote reasons.
- Fill evidence completeness: missing trade sizes and missing book snapshots are still too large for promotion-grade queue/fill confidence.
- Reward-score simulation and reward P&L measurement.
- Model/policy promotion.
- Live account/platform verification and live lifecycle evidence.

## Next Safe Actions

1. Diagnose active-row known-edge/promotion coverage before any live work: prove or reject harvest permission for the currently blocked promotion/missing-record cells, and keep the accepted-map fail-closed behavior until countable active-row evidence supports a permission change.
2. Keep the countable `paper-live-forward` daily roll running only while active-date metadata/economics, CLOB audit, snapshot freshness, and useful-work liveness remain passing; re-score it after any nonzero quote-permission interval.
3. Calibrate Polymarket US reward-score share from CLOB reward competition and compare predicted payout against markout, maker rebate, taker/flattening fees, queue fill risk, and inventory concentration.
4. Regenerate the standard paper report after current active-day runs, but do not treat queue-estimated fills as promotion evidence until fill-evidence completeness passes.
5. Keep live-pilot work limited to read-only platform/account verification until the evidence gates above pass.

## Source Links

- Polymarket US fee schedule: https://docs.polymarket.us/fees
- Polymarket US liquidity incentives: https://docs.polymarket.us/incentives/liquidity
- Polymarket US order API overview: https://docs.polymarket.us/api-reference/orders/overview
- Polymarket US authentication: https://docs.polymarket.us/api-reference/authentication
- Polymarket US market integrity: https://integrity.polymarket.us/
- Polymarket International liquidity rewards: https://docs.polymarket.com/market-makers/liquidity-rewards
- Polymarket International fees: https://docs.polymarket.com/trading/fees
- Polymarket International maker rebates: https://docs.polymarket.com/market-makers/maker-rebates
