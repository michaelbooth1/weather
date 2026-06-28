# Market-Making Simulation Scenario Coverage

Date: 2026-06-27

Scope: repo-grounded coverage for safe market-making preparation. This file maps the requested market-making scenarios to current artifacts, tests, and remaining blockers. It is not live-trading approval.

Current decision: NO-GO for live capital.

## Current Evidence Point

Latest active-window paper-live-forward one-shot:

- Run: `data/mm_runs/2026-06-27/20260627T135932865534Z`
- Paper score: `data/backtest/mm_paper_paperlive_20260627T135932_after_clob_recovery_source_status_block.json`
- Readiness: `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json`
- Latest post-snapshot-recovery shadow comparator: `data/mm_runs/2026-06-27/20260627T150554104648Z`
- Shadow score/readiness: `data/backtest/mm_paper_shadow_20260627T150554_post_snapshot_recovery_source_status_block.json`, `data/backtest/mm_live_readiness_20260627T150554_post_snapshot_recovery_source_status_block.json`
- Aggregate latest-five active-window paper score: `data/backtest/mm_paper_paperlive_20260627_latest5_active_after_clob_recovery_source_status_block.json`
- Aggregate readiness: `data/backtest/mm_live_readiness_20260627_latest5_active_after_clob_recovery_source_status_block.json`

Latest single-run summary:

| Field | Value |
| --- | --- |
| Evidence mode | `active_day_live_forward` |
| Readiness status | `BLOCK` |
| Live capital permission | `False` |
| Blocker count | `11` |
| Preflight status | `BLOCK` |
| First failing gate | `source_status_degradation` |
| Root cause count | `source_status_degradation_blocked = 12`; `stale_model_row = 3`; `stale_or_missing_snapshot_model_rows = 1` |
| Failing markets | all 12 selected markets |
| Model freshness failures | `3` |
| Observation-trigger root causes | `{}` |
| Source-status root cause | `settlement_source_auth_failure` |
| Weather.com credential present | `False` for `WEATHER_COM_API_KEY` and `WEATHER_COM_KEY` |
| Credential values redacted | `True` |
| Quote-intent rows | `132` |
| No-quote rows | `132` |
| Quote-permission rows | `0` |
| Live-permission rows | `0` |
| Quoted legs | `0` |
| Conservative fills | `0` |
| Queue-estimated fill legs | `0` |
| Fill evidence | `BLOCK`, reason `no_quote_legs` |
| Reward score | `0` |
| Exchange economics | `PASS`, snapshot `xecon-036874d19e56c76f` |
| Counts toward live-forward gate | `False` in readiness because preflight blocks |
| Information-event context | `INFO_EVENT_WU_CURRENT_PRINT`, action `widen` on 132 rows |

Aggregate latest-five active-window summary:

| Field | Value |
| --- | --- |
| Selected eligible run folders | `111731`, `112944`, `131743`, `135932` |
| Available before selection | `84` |
| Quote-intent rows | `528` |
| Quote-permission rows | `0` |
| Live-permission rows | `0` |
| Quoted legs | `0` |
| Conservative fills | `0` |
| Queue-estimated fill legs | `0` |
| Fill evidence | `BLOCK`, reason `no_quote_legs` |
| Reward score | `0` |
| Readiness | `BLOCK`, 11 blockers |

Interpretation: the latest evidence proves the bot is failing closed before quote permission when source-status proof is blocked. It does not prove reward-farming profitability, queue fill quality, markout quality, or live-forward quote uptime.

Superseding fixed-date CLOB and shadow recheck on 2026-06-27:

- CLOB restart: `.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --date 2026-06-27 --no-price-history --no-websocket-events`.
- Result: stopped two undated local-date loop processes and started a fixed-date public CLOB loop. Latest status is `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, `include_price_history = false`, `include_ws_events = false`, discovery sanity `PASS`, `raw_book_useful_iterations = 2`, and 0 target-date mismatch markets.
- Process proof: active CLOB loop command lines include `--date 2026-06-27 --no-price-history --no-websocket-events`.
- Strict audit: `.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date 2026-06-27` returned `ok = true` for all 12 markets, with startup gaps ignored only before the new fixed-date loop cutoff.
- Diagnostic root cause: `data/snapshots/clob_diagnostics.jsonl` showed a pre-fix `ensure` restart on runtime-identity drift that stopped fixed-date processes and launched an undated replacement. `market_microstructure` now preserves fixed `target_date` through `ensure` restarts, the operations dashboard preserves status-derived CLOB flags, and start diagnostics now record `target_date`, `date_selection`, enrichment flags, batch size, interval settings, and WebSocket settings.
- New keyless shadow drill: `data/mm_runs/2026-06-27/20260627T143831651008Z`, scored by `data/backtest/mm_paper_shadow_20260627T143831_after_fixed_clob_source_status_block.json`, with readiness `data/backtest/mm_live_readiness_20260627T143831_after_fixed_clob_source_status_block.json`.
- Shadow result: 132 quote-intent rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, 0 live-permission rows, exchange economics `PASS`, readiness `BLOCK` with 11 blockers, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, and `live_capital_permission = false`.
- Superseding interpretation: CLOB fixed-date public book evidence is repaired for the current loop, but the all-market maker remains a no-go because snapshot/model freshness and source-status proof still block all 12 markets before policy quote permission can be interpreted.

Fresh non-mutating runtime/recovery rechecks on 2026-06-27:

| Check | Current result | Readiness implication |
| --- | --- | --- |
| Official Polymarket US economics drift | `PASS`, `material_change_count = 0`, current/accepted snapshot `xecon-036874d19e56c76f` | No economics rescore needed from rule drift alone |
| Event metadata validation | `PASS` after `location_config_refresh`; 12 markets passed in `event_metadata_validation_20260627_goal_recheck.json` | Target-date metadata is current after refresh |
| CLOB status | After explicit restart, latest status is `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, `include_price_history = false`, `include_ws_events = false`, discovery sanity `PASS`, fresh heartbeat/books, and 0 target-date mismatch markets. | Current CLOB loop is back on fixed target-date evidence. Continue monitoring for future supervisor drift before treating later paper evidence as countable. |
| Explicit CLOB audit for 2026-06-27 | `ok = true` after the fixed-date restart across all 12 markets, with startup gaps ignored before the new loop cutoff | CLOB is no longer the leading immediate blocker for the latest shadow drill; source/model evidence still blocks promotion. |
| Snapshot tracker | Latest status returned `RUNNING`, `runtime_code_state = current`, `runtime_identity_matches_current = true`, capture liveness `OK`, snapshot cadence `PASS`, early-hour coverage `BLOCK`, and source-status `BLOCK` | Snapshot runtime/cadence recovered, but source-status and next active-day early-hour coverage remain operational blockers |
| Source-status proof | `BLOCK`, `settlement_source_auth_failure`, 12 blocked markets, Weather.com credential env vars absent/redacted | Main preflight blocker remains external source-status repair |
| Observation trigger | `RUNNING`, watcher fresh, PID alive | Current observer liveness is not the blocker |
| Daily roll | prior target `2026-06-26`, expected `2026-06-27`, `SCHEDULED_WAIT`, stale heartbeat/activity, noncountable | Current daily-roll evidence cannot count toward live-forward days |
| Post-snapshot-recovery shadow drill | `20260627T150554104648Z`: 132 quote rows, 132 no-quotes, 0 quote permissions, 0 live permissions, readiness `BLOCK` with 11 blockers and `{source_status_degradation: 12}` | With snapshot runtime/cadence and CLOB recovered, all-market shadow still blocks on source-status/provider-auth plus noncountable/fill/P&L/payout/platform gates |
| Fixed-date shadow drill | `20260627T143831651008Z`: 132 quote intents, 132 no-quotes, 0 quote permissions, 0 live permissions, readiness `BLOCK` with 11 blockers | Fixed CLOB did not unlock quote permission because model freshness/source-status/countability gates still block |
| Post-recovery shadow drill | `20260627T135111048558Z`: 132 quote intents, 132 no-quotes, 0 quote permissions, 0 live permissions, readiness `BLOCK` with 11 blockers | CLOB recovery did not unlock quote permission because source-status/model/countability gates still block |
| Post-recovery active-window paper-forward drill | `20260627T135932865534Z`: 132 quote intents, 132 no-quotes, 0 quote permissions, 0 live permissions, readiness `BLOCK` with 11 blockers | Active paper-forward evidence is current, but still blocked before quote permission |

## Coverage Legend

- `PASS`: covered by current artifact or regression test in a way that supports fail-closed readiness.
- `WARN`: covered only by diagnostic, historical, post-settlement, one-shot, or unit-test evidence; useful but not live-forward promotion evidence.
- `BLOCK`: currently blocked by latest active-window readiness evidence.
- `TODO`: not yet covered by a current repo artifact or focused simulation.

## Scenario Matrix

| Scenario | Coverage | Current evidence | What it proves | Remaining gap |
| --- | ---: | --- | --- | --- |
| Clean active day with fresh snapshots, CLOB, observation trigger, and exchange economics | `BLOCK` | Latest active-window paper-live-forward run `20260627T135932865534Z`; readiness `mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json`; latest shadow comparator `20260627T150554104648Z` | CLOB, event metadata, observation trigger, snapshot runtime/cadence, and exchange economics can pass together, but source-status proof still blocks all markets before quote permission; active paper-forward remains noncountable/zero-permission | Configure external Weather.com credentials, backfill source status, rerun active-window paper-live-forward and readiness |
| Stale snapshot/model rows | `PASS` | Historical runs `20260627T103532`, `110334`, `122613`; tests `test_default_model_freshness_covers_snapshot_loop_sla`, `test_snapshot_cadence_gap_blocks_high_confidence_edge_quote`, `test_snapshot_model_source_summary_counts_gate_failures` | Stale model/snapshot evidence fails closed and is separated from source-status failure | Need current clean source-status run to verify the gate clears without hiding quote starvation |
| Source-status degradation | `PASS` | Latest readiness root cause `settlement_source_auth_failure`; tests `test_preflight_blocks_source_status_degradation_even_when_a_source_is_fresh`, `test_source_status_blocker_aggregates_settlement_auth_failures`, `test_source_status_settlement_auth_failure_redacts_configured_provider_env` | Missing/degraded source-status proof blocks all selected markets and surfaces boolean-only credential diagnostics | External provider credential configuration and source-status backfill are required before quote permission can be interpreted |
| Stale CLOB rows or missing CLOB tape | `PASS` for fail-closed logic, `WARN` for supervisor drift monitoring | The loop degraded to zero books/tokens, recovered after fixed-date capture/restart, drifted to an undated local-date process after a pre-fix `ensure` restart, and was explicitly restored to fixed-date mode at `14:37Z`; tests cover failure and preservation: `test_data_layer_live_gate_requires_target_day_clob_artifacts`, `test_data_layer_live_gate_rejects_derived_clob_without_raw_artifacts`, `test_audit_book_tape_flags_internal_gap_and_stale_tail`, `test_ensure_clob_loop_preserves_fixed_target_date_when_restarting`, `test_ops_monitor_restart_clob_preserves_status_config`, `test_start_clob_loop_detached_writes_provisional_status` | Live/paper readiness requires target-day raw CLOB evidence and fails closed on stale/missing tape; supervisor/UI restarts now preserve fixed-date config and start diagnostics expose date/enrichment flags | Keep monitoring process command lines and diagnostics for repeat drift; if source-status clears, rerun strict audit and shadow/paper-forward before interpreting quote permission |
| Event metadata target-date mismatch | `PASS` | Next-date probe `20260627T003709708211Z`; tests `test_event_metadata_gate_blocks_maker_preflight_as_market_discovery`, `test_readiness_snapshot_blocks_mismatched_status_and_paper_target_dates`, `test_stale_target_event_uses_refresh_remediation` | Target-date mismatch blocks maker preflight and countability | Keep rerunning target-date validation before active evidence; no current blocker in latest readiness |
| Exchange economics target-date mismatch or material drift | `PASS` | Latest drift `exchange_economics_drift_20260627_goal_recheck.json`; tests `test_stale_snapshot_fails_closed`, `test_material_drift_requires_rescore_for_fee_reward_tick_and_min_order_changes`, `test_snapshot_blocks_target_date_mismatch` | Current accepted Polymarket US economics snapshot passes, and mismatches/material drift fail closed | Continue official-doc rechecks before any new promotion or live-capital decision |
| High-information WU/METAR/SWOB print windows | `PASS` | Historical event-gate artifacts around `20260627T004704070519Z`; tests `test_information_event_gate_suppresses_quote`, `test_information_event_exception_requires_evidence_and_caps_size`, `test_event_gate_score_tracks_suppressed_opportunity_cost` | Event windows can suppress or widen quotes and paper reports track suppressed opportunity cost | Need active source-status-clean evidence to measure opportunity cost and avoided toxicity in real quote-permission windows |
| No reward campaign or missing reward metadata | `PASS` | Next-date pre-refresh evidence included missing reward metadata; tests and preflight gates require reward metadata for live data layer | Reward metadata absence is treated as a preflight/live-data blocker | Need current campaign/reward metadata proof after source-status clears before interpreting reward score |
| Thin book / reward competition | `WARN` | Post-settlement recovered score `mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json`; tests `test_reward_score_diagnostics_use_clob_recon_competitor_score_when_available`, `test_clob_recon_summary_feeds_paper_report_and_known_edge_map` | CLOB recon competitor score can feed counterfactual reward-share diagnostics | No current active-window quote-permission/fill evidence; actual reward payout reconciliation is missing |
| High spread / wide book | `PASS` for bounded policy fixture, `WARN` for live-forward evidence | `test_high_spread_wide_book_requires_depth_and_spread_bounds` varies spread and depth while holding preflight inputs clean: spread `0.079` with deep book quotes harvest-only, spread `0.081` blocks with `NO_QUOTE_WIDE_SPREAD`, and shallow depth blocks with `NO_QUOTE_THIN_DEPTH` | Policy will not blindly farm a wide book: it requires both spread inside `max_harvest_spread` and adequate depth | Need active source-status-clean quote/fill/reward evidence before choosing production wide-spread quote parameters |
| Fast book movement | `WARN` | `test_fast_interval_triggers_on_large_midpoint_change`; CLOB loop status/audit artifacts | The capture loop can react to large midpoint changes | Need maker quote/cancel-replace simulation over fast-book intervals with fill and markout scoring |
| Queue depletion vs strict trade-through fills | `WARN` | Paper reports separate conservative fills and queue-estimated fill legs; tests `test_conservative_fills_queue_markouts_incentives_and_known_edge_map` | Queue estimates remain companion evidence and do not replace conservative fill gates | Latest active evidence has zero quoted legs, so queue/fill quality cannot be evaluated |
| Partial fill handling | `PASS` | Tests `test_partial_fill_lifecycle_event_reduces_open_risk`, `test_negative_risk_lifecycle_tracks_partial_fills_reductions_and_settlement` | Partial fills reduce open risk and lifecycle exposure in regression coverage | Need real or replay quote legs with partial fills and markouts |
| Inventory imbalance | `PASS` | Tests `test_event_inventory_metrics_scores_pnl_by_settlement_outcome`, `test_sizing_stack_caps_yes_ask_by_no_side_risk`, `test_balance_reservation_accounts_for_open_orders_and_allowance` | Inventory and balance reservations are covered at primitive level | Need active paper fills before inventory imbalance can be measured operationally |
| Correlated regime exposure | `PASS` | Tests `test_correlated_regime_grouping_uses_day_region_and_side_adjusted_direction`, `test_correlated_exposure_state_blocks_group_joint_loss_breach`, `test_sizing_stack_caps_correlated_regime_joint_loss` | Correlated same-regime exposure can shrink or block quote sizing | Need active evidence with nonzero quote permissions before this becomes a binding live policy measurement |
| Budget exhaustion and stale reservation release | `PASS` | Tests `test_shadow_run_writes_complete_artifacts_and_budget_exhaustion`, `test_append_same_tick_does_not_double_reserve_existing_lifecycle_orders`, `test_append_releases_open_budget_when_preflight_blocks`, `test_expired_quotes_release_before_new_reservations` | Budget ledger and lifecycle release behavior are covered under synthetic runs | Current latest active run has no reservations because preflight blocks |
| Cancel-all / kill-switch path | `PASS` for local safety, `BLOCK` for live proof | Tests `test_cancel_all_flag_releases_and_prevents_reposting`, `test_negative_risk_rejects_unbacked_orders_and_cancel_all_releases_reserves`, `test_polymarket_us_latency_stopgap_on_cancel_is_live_readiness_blocker`; readiness platform gate blocks | Local cancel-all and repost prevention are covered; live proof still requires structured zero-open-order confirmation and private stream reconciliation | Do not run exchange mutation without explicit approval; platform verification remains blocked |
| Model-market disagreement veto | `PASS` | Tests `test_shadow_large_disagreement_stands_down`, `test_late_untrusted_current_high_blocks_aggressive_mm_edge_for_june_21_markets`, `test_model_variant_clustered_gate_blocks_many_rows_from_one_market_day` | Model signal is constrained as veto/research evidence unless edge is proven | No model-skewed live quoting is justified by current active evidence |
| Edge mode blocked but harvest-only allowed | `WARN` | Known-edge map `mm_known_edge_map.json` has 17 records: 7 `harvest_only`, 3 `edge_research`, 7 `no_quote`; historical `073107` had 23 quote-permission rows | Harvest-only cells exist and historical shadow can emit quote permission | Latest source-status blocker prevents current policy interpretation; no countable active quote permissions |
| Shadow and paper modes never emit live trade permission | `PASS` | Latest single-run and aggregate latest-five paper scores show `live_trade_permission_rows = 0`; prompt-required maker suite passed | Safe modes did not grant live permission in current evidence | Continue checking this in every paper/shadow run before interpreting quote permissions |
| Live-pilot requires explicit gates | `PASS` | Tests `test_live_execution_blocks_without_explicit_enablement`, `test_live_execution_blocks_when_item45_gates_are_not_passing`, `test_live_pilot_blocks_without_platform_verification`, `test_live_pilot_blocks_when_latest_data_layer_audit_lacks_clob_proof` | Live execution is gated by explicit enablement, data-layer proof, and platform verification | No live-pilot run is approved; platform/operator proofs remain missing |
| Observation-trigger stale/dead watcher | `PASS` | Historical `125739` incident; post-recovery `135111` shadow and `135932` paper-forward drills clear current observation-trigger root causes; tests `test_stale_watcher_fails_closed_before_quote_logic`, `test_file_lock_replaces_fresh_dead_owner_pid`, `test_fresh_provisional_heartbeat_with_dead_pid_is_dead` | Stale/dead observation state fails closed and dead PID locks can be replaced safely | Keep checking watcher status before every active paper-forward run |
| Daily roll current target/date alignment | `BLOCK` for unattended roll | `market_making_daily_roll status` remains prior-target/post-settlement or scheduled wait; tests `test_after_window_roll_is_post_settlement_and_non_countable`, `test_active_window_roll_counts_as_live_forward_candidate`, `test_daily_roll_health_ignores_newer_shadow_probe_folder` | Readiness separates one-shot evidence from daily-roll countability and blocks stale/prior-target roll status | Operator needs a current target-date paper-forward loop after source-status repair; latest one-shot is diagnostic, not a replacement for 14 days |
| Actual reward/rebate payout reconciliation | `TODO` | Paper reports expose counterfactual reward fields, but `actual_payout_evidence = False` | Counterfactual reward score is not actual P&L | Need payout artifacts and reconciliation before scaling; not a day-one small test gate unless explicitly scoped to paper-only |

## Metrics Coverage

| Metric | Current status | Evidence |
| --- | ---: | --- |
| Quote rows and no-quote reasons | `PASS` | Latest run/report count 132 `NO_QUOTE_MISSING_PREFLIGHT`; aggregate latest-five counts 396 |
| Quote uptime by market/band/hour | `BLOCK` | No current quote-permission rows because source-status blocks before policy |
| Conservative fills | `BLOCK` | Latest current and aggregate scores have 0 quoted legs and 0 fills |
| Queue-estimated fills | `BLOCK` | Latest current and aggregate scores have 0 queue-estimated fill legs |
| Missing trade-size rows | `PASS` diagnostic | Latest current score has 0, but there are no quote legs; older post-settlement diagnostics had thousands |
| Missing book rows | `WARN` | Historical diagnostics identify missing-book/stale-input blockers; latest source-status block is earlier |
| Spread capture | `BLOCK` live-forward, `PASS` policy fixture | 0 current quote legs; bounded wide-book policy fixture covers spread/depth gating |
| 30s/1m/5m/30m/settlement markouts | `BLOCK` | 0 current quote legs/fills |
| Net P&L after fees/incentives | `BLOCK` | Latest current score is 0.0 due no quotes; not positive evidence |
| Liquidity reward estimate | `BLOCK` | Latest current reward score 0; no actual payout evidence |
| Maker rebate estimate | `BLOCK` | No fills/trades in current evidence |
| Flattening fee estimate | `BLOCK` | No positions/fills in current evidence |
| Adverse-selection loss | `BLOCK` | No current fills or markouts |
| Inventory/worst-case exposure | `PASS` regression, `BLOCK` current evidence | Risk tests pass; latest run has 0 exposure |
| Countable live-forward days | `BLOCK` | Readiness live-forward day count 0; latest one-shot is not countable because preflight blocks |
| Locked policy hash consistency | `PASS` within scored report | Latest paper score reports locked policy params true |
| Event-gate suppressed opportunity cost | `PASS` historical, `WARN` current | Latest run has 0 event-gate suppressed rows; historical event-window reports exercise it |
| Avoided toxicity evidence | `WARN` | Event-gate and markout machinery exists, but current active day has no quotes/fills |
| Fill evidence completeness | `BLOCK` | Latest readiness reports `no_quote_legs` |
| Known-edge permissions | `WARN` | Accepted map exists, but current source-status block prevents quote-policy interpretation |

## Model-Use Readiness

Current model use should remain conservative:

- Harvest mode: model can be a veto/risk overlay and band-selection aid only.
- Edge mode: model-skewed quotes remain blocked until countable active-window paper days show nonzero quote permissions, complete fill evidence, positive conservative markouts after fees/rewards/flattening, locked policy, and known-edge permission.
- Current known-edge map: 17 records, 7 `harvest_only`, 3 `edge_research`, 7 `no_quote`.
- Current active evidence: source-status gate blocks before policy, so the latest run cannot prove that harvest-only cells are currently tradable.

Do not promote generated candidate known-edge maps or model-skewed quote cells from diagnostic-only or post-settlement evidence.

## Safe Next Simulation Branch

Do these only after external Weather.com provider credentials are configured outside the repo. Do not put credentials in code, docs, git, or generated artifacts.

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --date 2026-06-27 --no-price-history --no-websocket-events
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date 2026-06-27
.\venv\Scripts\python.exe -m weather.operations.observation_trigger status
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_after_source_repair.json
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode paper-live-forward --markets all --once
```

Then score only the newly created run folder:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\<NEW_RUN_FOLDER> --json-out data\backtest\mm_paper_paperlive_20260627_<NEW_RUN_ID>_after_source_repair.json --report-out data\backtest\mm_paper_paperlive_20260627_<NEW_RUN_ID>_after_source_repair.md --fills-out data\backtest\mm_paper_paperlive_20260627_<NEW_RUN_ID>_after_source_repair_fills.csv --exchange-economics-target-date 2026-06-27 --exchange-economics-platform polymarket_us
.\venv\Scripts\python.exe -m weather.market.market_making_readiness --status data\mm_runs\2026-06-27\<NEW_RUN_FOLDER>\run_summary.json --paper-score data\backtest\mm_paper_paperlive_20260627_<NEW_RUN_ID>_after_source_repair.json --json-out data\backtest\mm_live_readiness_20260627_<NEW_RUN_ID>_after_source_repair.json --report-out data\backtest\mm_live_readiness_20260627_<NEW_RUN_ID>_after_source_repair.md
```

If that still has zero quote permissions, diagnose quote starvation by market/band/side/known-edge state using the new run's `quote_intents_long.csv` and `mm_paper` quote-blocker diagnostics. If it has quote permissions, continue with bounded latest-N active-window scoring before any live discussion.

## No-Go Conditions Still Active

- Source-status proof blocks all 12 markets with `settlement_source_auth_failure`.
- External Weather.com credentials are absent in the current shell and must remain outside the repo.
- Current CLOB loop was explicitly restored to fixed-date `2026-06-27` mode after the drift incident, but repeated supervisor drift remains a monitored risk. Future paper evidence still needs a fresh process-command/status/audit check before it counts.
- Snapshot runtime identity and cadence have recovered, but early-hour coverage is still blocked for promotion-quality evidence.
- Latest post-snapshot-recovery shadow readiness isolates the model/source blocker to `source_status_degradation = 12`, so the next local rerun is not meaningful until external source-health repair/backfill occurs.
- Latest active-window readiness has 11 blockers and `live_capital_permission = false`.
- Latest active-window and aggregate latest-five scores have 0 quote permissions and 0 quoted legs.
- Fill evidence is blocked by `no_quote_legs`.
- Live-forward day count is 0, not 14.
- Conservative P&L after costs is not positive in countable active evidence.
- Actual reward/rebate payout evidence is missing.
- Platform/operator live-readiness proofs are missing or fail-safe.
- Daily-roll evidence is prior-target/post-settlement or scheduled-wait/noncountable.
