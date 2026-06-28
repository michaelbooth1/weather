# Small-Scale Market-Making Test Plan

Date: 2026-06-26

Status: staged plan. This document does not authorize live orders.

## Goal

Prepare a small-scale market-making test where the first measurable objective is not profit, but operational proof:

- current reward/fee rules are verified for the actual operating platform,
- current target-date markets are discovered correctly,
- quote permission only appears when all preflight gates pass,
- paper fills and markouts are reconciled,
- reward/rebate estimates are grounded in current exchange mechanics,
- cancel-all and user-stream lifecycle are proven before live exposure.

Use `docs/research/MM_GOAL_COMPLETION_AUDIT_2026-06-26.md` as the current requirement-by-requirement audit before interpreting this plan. The current audit verdict is `NO LIVE CAPITAL`.

## Phase 0: Repair Current Blocks

Do these before any new paper-live-forward evidence is interpreted.

Use the active daily-roll target date, not UTC tomorrow or a manually guessed date. Earlier in this pass the active target date was `2026-06-25`; a later June 26 shadow tick had current CLOB, event metadata, and exchange economics, but still blocked on stale model snapshots and known-edge permission. Do not treat any `shadow` operator drill as countable live-forward evidence.

Current continuation state on 2026-06-27:

- Official Polymarket US economics still match the accepted local snapshot; `data/backtest/exchange_economics_drift_20260627_post_snapshot_recovery.json` is `PASS`, `material_change_count = 0`, `rescore_required = false`, and snapshot `xecon-036874d19e56c76f`.
- Public CLOB capture is currently repaired for target-date work: status is `RUNNING`, `date_selection = fixed_target_date`, `target_date = 2026-06-27`, `include_price_history = false`, `include_ws_events = false`, discovery sanity `PASS`, useful raw-book iterations, and strict target-date audit `ok = true` for all 12 markets.
- Snapshot/source readiness is still blocked even though the loop itself recovered: `weather.collection.snapshot_tracker --status` reports `RUNNING`, `runtime_code_state = current`, `runtime_identity_matches_current = true`, capture liveness `OK`, snapshot cadence `PASS`, early-hour coverage `BLOCK`, and source-status proof `BLOCK` with `settlement_source_auth_failure`; Weather.com credential booleans are false for both `WEATHER_COM_API_KEY` and `WEATHER_COM_KEY`.
- Daily roll is not countable current evidence: status `idle_process`, action `blocked_restart_required`, target date `2026-06-26`, expected target `2026-06-27`, supervisor `SCHEDULED_WAIT` until `19:30`, artifact liveness `STALE_HEARTBEAT_METADATA`, and live-forward gate `BLOCK`.
- Latest post-snapshot-recovery all-market shadow drill `data/mm_runs/2026-06-27/20260627T150554104648Z` remains no-go: preflight `BLOCK`, first failing gate `source_status_degradation`, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote permissions, 0 live permissions, score `data/backtest/mm_paper_shadow_20260627T150554_post_snapshot_recovery_source_status_block.json`, readiness `data/backtest/mm_live_readiness_20260627T150554_post_snapshot_recovery_source_status_block.json`, and 11 blockers. The readiness aggregate now isolates the model/source gate count to `{source_status_degradation: 12}`; model freshness is no longer a current all-market shadow blocker in this probe.
- Latest regenerated daily-status mismatch readiness `data/backtest/mm_live_readiness_20260627T112003_daily_status_flattened.json` is also no-go. It intentionally combines the current stale June 26 daily-roll status with the June 27 150554 shadow score and blocks on `readiness_inputs_target_date_aligned`, `daily_roll_target_date_current`, stale runtime liveness, 0 quote permissions, missing fill evidence, missing positive P&L, missing payout proof, and missing operator/platform verification. Treat this as a guardrail artifact, not candidate paper evidence.

1. Refresh target-date event metadata:

```powershell
.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --locations config/locations.json --event-metadata config/location_market_events.json
.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date <ACTIVE_TARGET_DATE> --markets all
```

Acceptance:

- `data/backtest/event_metadata_validation.json` is `PASS`.
- The target-date event slug exists for every selected market.
- Token maps, condition IDs, and outcome labels match live discovery.
- The accepted exchange-economics snapshot is verified for the same target date selected for the run. Bounded paper reports must show this target date explicitly.
- Weather.com provider credentials, if needed for source-status proof, are supplied externally through `WEATHER_COM_API_KEY` or `WEATHER_COM_KEY`; missing provider credentials should fail closed as source-status degradation, not be patched back into source code. If `weather_com_credential_present = false`, the first repair is external credential configuration, then `python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status`, then keyless shadow/readiness reruns.

2. Refresh exchange economics:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date <ACTIVE_TARGET_DATE> --platform polymarket_us --accept
```

Acceptance:

- `data/backtest/exchange_economics_snapshot.json` has `verified_for_target_date = <ACTIVE_TARGET_DATE>`.
- Accepted snapshot has the same verified target date.
- Drift report is `PASS`.
- Any material fee/reward/tick/min-size change triggers paper rescore before pilot consideration.

3. Restart or refresh stale runtime loops if needed.

Acceptance:

- `weather.market.market_microstructure status` is running.
- `weather.market.market_microstructure status` shows `date_selection = fixed_target_date` and `target_date = <ACTIVE_TARGET_DATE>` before target-date evidence is interpreted.
- `weather.market.market_microstructure audit --strict --date <ACTIVE_TARGET_DATE>` passes.
- Daily roll useful-work liveness is not blocked for all-market active-day evidence.

## Phase 1: Same-Day Shadow Readiness

Command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date <ACTIVE_TARGET_DATE> --budget-usdc 500 --mode shadow --markets all --once
```

Acceptance:

- Preflight is `PASS` or a narrowly understood `WARN`.
- Current market rows exist.
- CLOB token and book rows exist for selected markets.
- Quote-permission rows are explained by policy, not by missing preflight.
- Live-trade-permission rows remain 0 because mode is `shadow`.
- `run_report.md`, `preflight.json`, `quote_intents_long.csv`, `budget_ledger.jsonl`, and `risk_events.jsonl` are internally consistent.

If preflight remains `BLOCK`, stop and write the blocker. Do not work around missing target-date data by weakening gates.

Current pass result:

- Active-date and post-settlement preflight for `2026-06-25` passed after metadata/economics refresh and supervisor restarts.
- Latest stable drill `data/mm_runs/2026-06-25/20260626T020148684548Z` had 1 quote-permission row, 0 live-trade-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 10 `NO_QUOTE_MISSING_BOOK` rows.
- The one quote was Dallas `92-93 F`, post-settlement only, with expected reward score 1.0.
- An earlier restarted daily roll was post-settlement evidence and did not count toward live-forward gates.
- Earlier current-date June 26 shadow drill `data/mm_runs/2026-06-26/20260626T132648384687Z` had 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 121 `NO_QUOTE_STALE_INPUT` rows, and 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows.
- Latest current-date June 26 shadow drill `data/mm_runs/2026-06-26/20260626T134201734227Z` had preflight `PASS`, 9 Dallas harvest-only quote-permission rows, 123 no-quote rows, 0 live-trade-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 2 `NO_QUOTE_DISAGREEMENT_SHADOW` rows.
- The stale/pid-missing daily-roll state was repaired earlier, and later source edits triggered safe stale-code backoff. After the guarded retry window cleared, safe `ensure --force` quarantined the stale folder and restarted the loop onto current source. Current status is not countable: status `idle_process`, action `blocked_restart_required`, target date `2026-06-26`, expected target date `2026-06-27`, mode `paper-live-forward`, evidence mode `post_settlement_evaluation`, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, `current_counts_toward_live_forward_gate = false`, latest run folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, latest tick rows 132, supervisor state `SCHEDULED_WAIT`, supervisor action `scheduled_wait`, and artifact liveness `STALE_HEARTBEAT_METADATA`. Current operational blocker: stale prior-target post-settlement noncountability; current scored-row blockers: policy/known-edge, missing/stale books, and fill-evidence blockage.
- Point-in-time daily-roll diagnostic folder `data/mm_runs/2026-06-26/20260626T135556165467Z` is still not useful for live-readiness promotion: the previous fixed bounded diagnostic score has 4,092 quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, 4,070 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 22 `NO_QUOTE_STALE_INPUT` rows, and reward score 0.
- Previous bounded quote diagnostic from the active daily-roll tape before `mm_quote_intent_v0.3`: `data/backtest/mm_paper_active_latest_20260626_quote_diag.json`, from `data/mm_runs/2026-06-26/20260626T160337445814Z`, scored 4,224 accumulated quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, 3,916 known-edge permission-blocked rows, 308 stale-input rows, 44 event-gate-suppressed rows, and `mm_quote_blocker_diagnostics_v0.7`. It loaded the then-current 238-record known-edge map and found 0 inferred known-edge record matches. It skipped fill simulation and model-variant scoring, so it is blocker evidence, not promotion-grade P&L evidence.
- v0.3 quote-schema probe: `%TEMP%\weather-mm-v03-probe\2026-06-26\codex-v03-probe` wrote exact `known_edge_match_*` fields, and the final `data/backtest/mm_paper_v03_probe_20260626_quote_diag.json` still found 132 blocked rows, 0 quote-permission rows, 88 known-edge permission-blocked rows, 44 stale-input rows, and 0 event-gate-suppressed rows. This proves the new diagnostics work, not that any live-pilot gate has improved.
- Current-source v0.3 event-window shadow probe `data/mm_runs/2026-06-26/20260626T165003338813Z` passed preflight and scored 132 blocked rows, 0 quote-permission rows, 132 known-edge permission-blocked rows, 0 stale-input rows, and 132 event-gate-suppressed rows in `data/backtest/mm_paper_shadow_20260626T165003338813Z_v03_current.json`. Because it landed in `INFO_EVENT_METAR_PRINT`, it is useful event-window evidence and reinforces the no-go stance.
- Current-source v0.3 WU/SWOB shadow probe `data/mm_runs/2026-06-26/20260626T170013329405Z` scored 132 blocked rows, 0 quote-permission rows, 121 known-edge permission-blocked rows, 11 stale-input rows, and 11 event-gate-suppressed rows in `data/backtest/mm_paper_shadow_20260626T170013329405Z_v03_current.json`; preflight was `WARN` on `model_freshness`.
- Current-source active daily-roll diagnostic `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` selected `data/mm_runs/2026-06-26/20260626T231738340378Z` and scored 4,807 quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, and 0 inferred known-edge record matches. It reports `mm_quote_blocker_diagnostics_v0.8` coverage action items and required-action buckets and is the latest current-source active no-go evidence.
- Recovered post-settlement diagnostic `data/backtest/mm_paper_postsettlement_recovered_20260627T001837640455Z_v08.json` selected `data/mm_runs/2026-06-26/20260627T001837640455Z` and scored 264 quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, 264 known-edge permission-blocked rows, 0 stale-input rows, and 11 event-gate-suppressed rows. It repairs stale runtime identity, but because it is post-settlement it is not countable live-forward evidence.
- June 27 next-date probe `data/mm_runs/2026-06-27/20260627T055820610723Z` is also a no-go: event metadata, exchange economics, target-date snapshot/model/source rows, and target-date CLOB feature rows exist, but at that time strict target-date CLOB audit had four counted historical gaps. The keyless shadow run has preflight `WARN`, 132 no-quote rows, 0 quote-permission rows, and 0 live-trade-permission rows. The split is 55 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 44 `NO_QUOTE_STALE_INPUT` rows, and 33 `NO_QUOTE_INFORMATION_EVENT` rows; CLOB remediation root cause was four historical `clob_book_tape_gap_over_threshold` rows. A later continuation recheck at `2026-06-27T07:52:34Z` cleared the explicit all-market CLOB audit (`ok: true` with startup gaps ignored), and the 124837 forced-refresh shadow cleared model freshness. The current no-go rationale is no longer this historical CLOB gap or stale model rows; it is persistent source-status/provider-auth failure plus lack of countable paper-live-forward evidence, fill/P&L/payout proof, policy lock, and platform/operator proof. The diagnostic `data/backtest/mm_paper_shadow_20260627T055820_after_metadata_snapshot_refresh.json` has exchange-economics gate `PASS`, model-variant scoring `PASS`, and actual payout evidence false. That zero-quote score predates the `no_quote_legs` fill-evidence fix, so any fill `PASS` wording is vacuous. Target-date-aligned readiness `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.json` is `BLOCK` with 11 blockers.
- Selected-market June 27 subset probe `data/mm_runs/2026-06-27/20260627T061148175884Z` was a useful small-scale paper target candidate, but it is still a no-go for live capital. Command shape was `--mode shadow --markets austin,dallas,houston --once`; it passed preflight and emitted 16 quote-permission rows, 17 no-quote rows, and 0 live-trade-permission rows. Per-market quote permissions were Austin 4, Dallas 4, and Houston 8. The paper score `data/backtest/mm_paper_shadow_20260627T061148_subset_austin_dallas_houston.json` has 32 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` due to missing trade-size rows and 32 unresolved resting quotes, and counterfactual reward 144.890411 USDC. Readiness `data/backtest/mm_live_readiness_20260627T061148_subset_austin_dallas_houston.json` remains `BLOCK` with 11 blockers and `live_capital_permission = false`.
- Fresh selected-market June 27 subset probe after targeted snapshot refresh plus targeted public CLOB capture, `data/mm_runs/2026-06-27/20260627T071559212462Z`, is the current point-in-time subset evidence and is stricter: preflight `PASS`, 33 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 25 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 8 `NO_QUOTE_MISSING_BOOK`. Its paper score `data/backtest/mm_paper_shadow_20260627T071559_subset_austin_dallas_houston.json` has 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, and net P&L 0; because it is a pre-fix zero-quote artifact, any fill `PASS` wording is vacuous. Matching readiness `data/backtest/mm_live_readiness_20260627T071559_subset_austin_dallas_houston.json` is `BLOCK` with 8 blockers and `live_capital_permission = false`; it confirms this subset is not currently quoteable even though preflight, selected-market target-date CLOB cadence, current model age, and current book age pass.
- Fresh all-market June 27 shadow probe `data/mm_runs/2026-06-27/20260627T073107208602Z` is now the latest nonzero-quote all-market evidence, but it is still not Phase 2. It passed preflight and emitted 23 quote-permission rows, 109 no-quote rows, and 0 live-trade-permission rows. Its score `data/backtest/mm_paper_shadow_20260627T073107_current_all.json` has 46 quoted legs, 0 conservative fills, 1 queue-estimated fill leg, fill evidence `BLOCK`, 400 missing-size trade rows, 46 unresolved resting quotes, reward score 20.559525, counterfactual reward 176.767745 USDC, and actual payout evidence false. Matching readiness `data/backtest/mm_live_readiness_20260627T073107_current_all.json` is `BLOCK` with 11 blockers and `live_capital_permission = false`; it proves quote emission can recover in shadow, not that a live or promotion run is ready.
- Later all-market shadow evidence shows the allowed window is unstable and currently blocked again. `data/mm_runs/2026-06-27/20260627T075907746405Z` passed preflight but emitted 0 quote-permission rows and 0 live permissions, split into 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 35 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 9 `NO_QUOTE_MISSING_BOOK`. The patched run `data/mm_runs/2026-06-27/20260627T080312460577Z` then degraded to preflight `STALE` on model freshness with 132 `NO_QUOTE_STALE_INPUT` rows. Its regenerated paper score marks 0 quote legs as non-promotion fill evidence (`no_quote_legs`), and readiness `data/backtest/mm_live_readiness_20260627T080312_current_all.json` is `BLOCK` with 11 blockers while recording accepted known-edge map provenance: `mm_known_edge_map_v0.2`, 17 records, `diagnostic_only = false`.
- Active-window paper-live-forward one-shot `data/mm_runs/2026-06-27/20260627T135932865534Z` is the freshest current paper-forward no-go: preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, 0 live-permission rows, evidence mode `active_day_live_forward`, and live-forward gate `BLOCK`. Before the prior 103532 run, the source-status backfill command was applied to all 12 current June 27 folders and rewrote 3,756 rows from replay inputs; fresh `snapshot_tracker --status` still returns `source_status.status = BLOCK`, `root_cause_class = settlement_source_auth_failure`, and 12 `wu_history` settlement auth failures. `preflight_remediation.json` reports `source_status_degradation_blocked = 12`, plus 3 `stale_model_row` and 1 `stale_or_missing_snapshot_model_rows` root causes, and suggests `python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status` after external source-health repair. The matching paper score `data/backtest/mm_paper_paperlive_20260627T135932_after_clob_recovery_source_status_block.json` has 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, paper freshness `PASS`, paper-day collection gate `OPEN`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`. Matching readiness `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json` is `BLOCK` with 11 blockers and exposes `evidence_mode = active_day_live_forward`, `current_counts_toward_live_forward_gate = false`, `latest_tick_no_quote_rows = 132`, `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}`, `source_status_degradation_failed_markets = all 12 selected markets`, aggregate `source_status_settlement_auth_failures = 12`, `source_status_settlement_auth_failures_per_market = 1`, and top next actions that point to external weather-provider/source-health repair plus source-status backfill. The current small-scale blocker is upstream source-status evidence quality: explicit CLOB audit, exchange-economics drift, and observation-trigger runtime pass, but source-status proof blocks trading evidence before policy quote permission can be interpreted.
- Aggregate active-window paper-forward score `data/backtest/mm_paper_paperlive_20260627_latest5_active_source_status_block.json` selected three eligible folders from the latest-five bounded query and confirms this is not a one-tick issue: 396 quote rows, 0 quote-permission rows, 0 live permissions, 0 quoted legs, fill evidence `BLOCK`, total reward score 0, and readiness `BLOCK` with 11 blockers.
- Earlier all-market shadow after CLOB, forced snapshot/model, and observation-trigger recovery, `data/mm_runs/2026-06-27/20260627T135111048558Z`, remains no-go: preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote-intent rows, 132 no-quote rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-permission rows. Its score `data/backtest/mm_paper_shadow_20260627T135111_after_clob_recovery_source_status_block.json` has 0 quoted legs, fill evidence `BLOCK`, reward score 0, exchange economics `PASS`, paper-day collection gate `OPEN`, and `live_capital_gate_status = NOT_EVALUATED_BY_MM_PAPER`. Matching readiness `data/backtest/mm_live_readiness_20260627T135111_after_clob_recovery_source_status_block.json` is `BLOCK` with 11 blockers and exposes `source_status_weather_com_credential_present = false` and redacted credential values. The prior 125739 shadow is historical evidence for a watcher-stale incident that was cleared by `weather.operations.observation_trigger ensure`. This shadow confirms the durable current blocker is source-status/provider-auth evidence, not CLOB audit, exchange economics, or current observation-trigger liveness.
- Fixed-date all-market shadow after explicit CLOB restart, `data/mm_runs/2026-06-27/20260627T143831651008Z`, remained no-go: preflight `BLOCK`, latest tick first failing gate `model_freshness`, source-status root cause `settlement_source_auth_failure`, 132 quote-intent rows, 132 `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, and 0 live-permission rows. Its score `data/backtest/mm_paper_shadow_20260627T143831_after_fixed_clob_source_status_block.json` has 0 quoted legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, and no actual payout evidence. Matching readiness `data/backtest/mm_live_readiness_20260627T143831_after_fixed_clob_source_status_block.json` is `BLOCK` with 11 blockers. This run proved the fixed-date CLOB loop alone was not enough.
- Latest post-snapshot-recovery all-market shadow, `data/mm_runs/2026-06-27/20260627T150554104648Z`, is the freshest operator-drill comparator and remains no-go with a cleaner root-cause split: preflight `BLOCK`, first failing gate `source_status_degradation`, 132 quote rows, 132 no-quotes, 0 quote-permission rows, and 0 live-permission rows. Its score `data/backtest/mm_paper_shadow_20260627T150554_post_snapshot_recovery_source_status_block.json` has 0 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, fill evidence `BLOCK` with `no_quote_legs`, reward score 0, exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, and no actual payout evidence. Matching readiness `data/backtest/mm_live_readiness_20260627T150554_post_snapshot_recovery_source_status_block.json` is `BLOCK` with 11 blockers and `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`. This isolates the immediate all-market shadow blocker to external source-status/provider-auth evidence plus countability/fill/P&L/payout/platform gates.
- Candidate markets for the next paper-only probe should be chosen from the new exact scorer diagnostics, not from broad intuition: `quote_permission_market_counts = {austin: 4, dallas: 7, denver: 5, houston: 7}`. All top quoted cells are `harvest_only` / `SHADOW` / `QUOTE_HARVEST_MID`; this supports future paper-live-forward targeting of these markets, while still requiring countable evidence, fill completeness, and no unresolved resting quotes before any live pilot.
- Current-source shadow check after canonicalizing known-edge record hours: `data/mm_runs/2026-06-26/20260626T172330853600Z` had preflight `WARN` on `model_freshness`, 132 blocked rows, 0 quote-permission rows, 99 known-edge permission-blocked rows, 33 stale-input rows, and 0 live-trade-permission rows. The hour-format fix did not restore quote permission.
- Current-source keyless shadow check `data/mm_runs/2026-06-26/20260627T004704070519Z` is also a no-go: preflight `PASS` across all 12 markets, 132 quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 44 `NO_QUOTE_INFORMATION_EVENT`, and all 132 rows event-gate-suppressed during `INFO_EVENT_METAR_PRINT`. Its diagnostic score `data/backtest/mm_paper_shadow_20260627T004704070519Z_current_source.json` has exchange economics `PASS`, paper freshness `NO_ACTIVE_DAY`, fill evidence `SKIPPED`, and reward score 0.
- Latest current-source keyless shadow check `data/mm_runs/2026-06-26/20260627T010734537264Z` remains a no-go even though it emits 6 harvest-only quote permissions: preflight `PASS`, 132 quote rows, 0 live-trade-permission rows, 12 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 26.8405, counterfactual reward 211.60828 USDC under default pool/competition assumptions, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 4 missing-book queue legs, 4,980 missing-size trade rows, and 12 unresolved resting quotes. This is noncountable shadow/operator-drill evidence, not Phase 2 live-forward paper evidence.
- Pre-recovery fixed paper-live-forward score `data/backtest/mm_paper_postsettlement_latest_20260627T020932_current_source.json` also remains a no-go: generated at `2026-06-27T02:10:06Z`, 5,016 quote rows, 118 quote-permission rows, 0 live-trade-permission rows, 236 quoted legs, 0 conservative fills, 6 queue-estimated fill legs, reward score 625.5215, counterfactual reward 862.168109 USDC under default pool/competition assumptions, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 50 missing-book queue legs, 7,084 missing-size trade rows, and 236 unresolved resting quotes. This is post-settlement/noncountable evidence from a stale-runtime folder scored with current code, not Phase 2 live-forward paper evidence.
- Latest regenerated recovered paper-live-forward score `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json` remains a no-go: 1,320 quote rows, 17 quote-permission rows, 0 live-trade-permission rows, 34 quoted legs, 0 conservative fills, 2 queue-estimated fill legs, reward score 89.72025, counterfactual reward 444.480401 USDC using CLOB recon competitor score 112.133982, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 1 missing-book queue leg, 4,148 missing-size trade rows, and 34 unresolved resting quotes. This confirms current scoring code can replay the recovered folder and find nonzero paper permissions, but it is still post-settlement/noncountable evidence, not Phase 2 live-forward paper evidence.
- The current accepted known-edge map has 17 records and includes a broad Dallas `harvest_only` row. Latest Dallas rows are mostly blocked by missing books, event gates, stale input, and cadence degradation; other markets still need promotion/missing-record evidence before map changes.
- Therefore Phase 2 should not be treated as satisfied until source-status proof is `PASS`, countable active-window paper-live-forward evidence has nonzero quote permissions, fill evidence is complete enough for promotion, and the run can be scored with markouts and settlement/resting-quote resolution. The regenerated 135932 readiness artifact now makes the first repair explicit: `source_status_weather_com_credential_present = false`, both `WEATHER_COM_API_KEY` and `WEATHER_COM_KEY` are absent in this shell, credential values are redacted, and the top action is external provider credential configuration before rerunning source-status backfill and paper-live-forward/readiness. `snapshot_tracker --status` now also exposes the same boolean-only provider credential evidence in `source_status_proof_v0.2`, fleet observability renders it while staying `CRITICAL`, and the live-forward SLO recovery checklist now reports `settlement_source_auth_failure_missing_weather_com_credentials` with owner `external Weather.com provider credentials` when those env vars are absent. The Market Making cockpit displays the same latest live-readiness/no-go artifact.

## Phase 2: Countable Paper-Live-Forward

Objective: collect evidence that counts toward live-forward gates.

Command shape:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date <ACTIVE_TARGET_DATE> --budget-usdc 500 --mode paper-live-forward --markets all
```

For the current small-scale candidate subset, prefer the managed daily-roll path during the active local window, after stopping any stale or prior-target paper loop:

```powershell
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll stop --date <OLD_TARGET_DATE>
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll start --date <ACTIVE_TARGET_DATE> --budget-usdc 500 --mode paper-live-forward --markets austin,dallas,houston --force
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
```

For CLOB capture around cross-timezone midnight, do not rely on the default managed CLOB loop's per-market local date. Start or restart the CLOB loop with the same fixed target date used by the maker evidence:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure restart --market all --date <ACTIVE_TARGET_DATE> --no-price-history --no-websocket-events
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict --date <ACTIVE_TARGET_DATE>
```

Run that only at or after the active evidence window starts (`07:00` America/Toronto) and before the evidence cutoff (`20:00`). The default scheduled maker roll/supervisor is still a last-window scheduler (`start_after_local_time = 19:30`); it is useful as a backstop, not as full-window reward-farming paper evidence.

Acceptance:

- Run occurs during the active local trading window.
- Evidence classification is countable.
- Useful-work liveness is `PASS`.
- The run has current snapshots, source-status rows, CLOB books, CLOB features, token metadata, and reward metadata.
- Daily-roll status shows the current target date, not a prior post-settlement loop, and `daily_roll_supervisor.start_time_gate` is either allowed or no longer blocking.
- Paper order lifecycle has no impossible reserve state.
- Quote rows contain stable no-quote reasons and policy hashes.

Do not start this if Phase 0 and Phase 1 are blocked.

## Phase 3: Score And Analyze

Commands:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict
```

Current caveat:

- Full-corpus standard model-variant scoring now writes `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json` after the streamed-casebook, compact-leg, and quote-row release runtime fixes. The result is still not promotion-grade because fill evidence is `BLOCK` and model-variant promotion is `BLOCK`.
- Current fill-evidence blockers are specific enough to target before any live pilot: 8,893 missing-size trade rows, 2,182 missing-book queue legs, and 26 missing-trade-size queue legs. The largest missing-size event gaps are Dallas June 25, Denver June 23, Denver June 21, Austin June 23, Atlanta June 21, and Houston June 21. The largest missing-book queue gaps are early-hour `YES_ASK` slices, led by Los Angeles `70-71 F` at `02:00Z`, Houston `88-89 F` at `02:00Z`, and Dallas `92-93 F` at `02:00Z`.
- A bounded score for `data/mm_runs/2026-06-25/20260626T020148684548Z` completed and wrote `data/backtest/mm_paper_quote_starvation_20260626T020148684548Z.json`, but that result is diagnostic only because it is one post-settlement run.
- `weather.market.mm_paper` now also supports target-date/latest-N bounded scoring:
  `.\venv\Scripts\python.exe -m weather.market.mm_paper --target-date <ACTIVE_TARGET_DATE> --evidence-mode active_day_live_forward --latest-n <N> --json-out data\backtest\mm_paper_bounded_<label>.json --report-out data\backtest\mm_paper_bounded_<label>.md --fills-out data\backtest\mm_paper_bounded_<label>_fills.csv --known-edge-out data\backtest\mm_known_edge_bounded_<label>.json --known-edge-report-out data\backtest\mm_known_edge_bounded_<label>.md`
- Add `--skip-model-variants` only for faster operational diagnostics. A skip report must show model-variant scoring `SKIPPED (skip_model_variants)` and cannot be used as model-promotion evidence.
- Add `--skip-fill-simulation --skip-model-variants` only for full-corpus quote/no-quote and reward-score diagnostics. A skip-fill report must show fill evidence `SKIPPED (skip_fill_simulation)` and cannot be used for P&L, fill evidence, known-edge promotion, or model-variant promotion.
- The earlier bounded active-day promotion-grade score selected `data/mm_runs/2026-06-25/20260626T015448206993Z`, completed in 2.2 seconds after quote-blocker diagnostics were added, and found 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, and reward score 0. Quote-blocker diagnostics showed overlapping blockers: all 132 rows were event-gate suppressed, 121 rows were known-edge permission-blocked, and 11 harvest-only rows were suppressed by the event gate.
- The latest bounded June 26 shadow score selected `data/mm_runs/2026-06-26/20260626T134201734227Z`, completed in 5.0 seconds, and found 132 quote rows, 18 quote legs, 9 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`, reward score 12.26505, counterfactual reward 109.2508 USDC, and exchange economics target-date match for `2026-06-26`. This is diagnostic only because it is `shadow`, freshness is `NO_ACTIVE_DAY`, fill evidence is `BLOCK`, and active-day resting quotes are unresolved until settlement evidence exists.
- The previous bounded active-day daily-roll diagnostic selected `data/mm_runs/2026-06-26/20260626T135556165467Z` and wrote `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`: 4,092 quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, reward score 0, exchange economics `PASS`, paper freshness `PASS`, fill evidence `PASS` only because there were no quoted legs, live-forward paper days 1, and model-variant scoring `SKIPPED (skip_model_variants)`. The new missing-known-edge dimension table shows the current active-day blocker is known-edge permission and active-row map coverage, not CLOB capture or live permissions.
- The previous pre-v0.3 bounded active-day daily-roll quote diagnostic selected `data/mm_runs/2026-06-26/20260626T160337445814Z` and wrote `data/backtest/mm_paper_active_latest_20260626_quote_diag.json`: 4,224 accumulated quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, 3,916 known-edge permission-blocked rows, 308 stale-input rows, 44 event-gate-suppressed rows, quote uptime 0, paper freshness `PASS`, live-forward paper days 1, and `mm_quote_blocker_diagnostics_v0.7`. It remains historical no-go evidence for quote permissions, but not fill/P&L evidence because fill simulation and model-variant scoring were skipped. The separate v0.3 probe confirms exact match fields are now written for future quote tapes; the diagnostic-only inferred-map comparison still found 0 matches against the current default known-edge map and reports nearest-record dimension gaps plus blocker-overlap rows.
- The latest current-source active-day daily-roll quote diagnostic selected `data/mm_runs/2026-06-26/20260626T231738340378Z` and wrote `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json`: 4,807 quote rows, 0 quote legs, 0 quote-permission rows, 0 live-trade-permission rows, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, quote uptime 0, paper freshness `PASS`, live-forward paper days 1, and `mm_quote_blocker_diagnostics_v0.8`. It is the current no-go evidence for quote permissions and freshness risk, but not fill/P&L evidence because fill simulation and model-variant scoring were skipped. The action-item and required-action tables are diagnostic-only and must not be used to grant permission without countable paper evidence.
- Before any live pilot, full standard scoring must pass on current artifacts. Bounded scoring is useful for targeted diagnosis only unless it explicitly covers every countable active-window run selected for promotion and all live-pilot gates still pass.

Acceptance:

- The latest full standard paper report freshness is `PASS`.
- Fill evidence completeness is `PASS`; an explicitly understood `BLOCK` is useful for diagnosis but does not satisfy live-pilot acceptance.
- Conservative fills and queue-estimated fills are reported separately.
- Adverse-selection markout is not hidden by rebate/reward estimates.
- Reward estimate is calculated using the current operating platform formula.
- Reward score diagnostics are reported separately from reward-dollar P&L and show selected scope, score basis, target-size fraction, and no-quote blockers.
- Model-variant bakeoff is present unless the run is explicitly labeled as a skip-variant operational diagnostic.
- Fill simulation is present unless the run is explicitly labeled as a skip-fill operational diagnostic.
- Known-edge map is updated only from countable evidence.

Scale criteria for future pilot consideration:

- Nonzero conservative fills across multiple market-days.
- No unresolved lifecycle/reserve mismatches.
- No stale source or stale book quote permissions.
- No reward estimate that depends on a stale economics snapshot.
- Net paper economics remain acceptable after flattening fee and adverse-selection markout.

## Phase 4: One-Market Live-Readiness Drill

This phase is still no-live-order unless explicitly authorized later.

Pick one market and one central band only after Phases 0-3 pass.

Read-only checks:

- Confirm exact platform: `polymarket_us` or International CLOB.
- Confirm account eligibility, jurisdiction, wallet type, signer/funder, collateral token, balance endpoint, allowance endpoint, and order endpoint.
- Confirm tick size, min order size, reward target size, reward discount factor/spread threshold, fee rate, maker rebate, any taker-rebate eligibility, and order API semantics for that exact market. Do not include temporary high-volume taker rebates in small-scale economics without account-level qualification and payout proof.
- For Polymarket US, confirm order entry uses `participateDontInitiate`, not a marketable order path.
- Confirm user WebSocket or private stream works and produces order snapshots plus order execution updates.
- Confirm cancel-all request plan can be built without exposing secrets, then prove cancel-all with zero open orders after the request.
- Confirm US latency-stopgap handling before any order placement: new-order and cancel-replace rejects must be treated as transient stale-price protection that requires book refresh/recompute, while pure cancels must remain available. Adapter-level classification exists, but live proof is still required.
- Confirm platform-verification v0.2 secret hygiene before any live-pilot attempt: the artifact must contain no exact secret fields, no unredacted secret-like URL query values, and fresh `secret_redaction` proof for status-output, source/docs, generated-artifact, no-finding, and scan-scope checks.

Required local artifacts:

- Fresh `mm_platform_verification_v0.2` artifact with maker-only order field proof, private-stream order snapshot/update/fill/final-state reconciliation proof, cancel-all zero-open-order proof, US latency-stopgap proof where `platform = polymarket_us`, and secret-redaction proof.
- Fresh live-readiness JSON with all booleans true.
- Fresh readiness Summary must include paper-side quote-blocker diagnostics for the candidate run. The current 073107 all-market shadow has `paper_quote_blocked_rows = 109`, `paper_quote_blocked_fraction = 0.825758`, `paper_quote_blocker_reason_counts = {NO_QUOTE_KNOWN_EDGE_PERMISSION: 88, NO_QUOTE_DISAGREEMENT_SHADOW: 11, NO_QUOTE_MISSING_BOOK: 10}`, `paper_quote_blocker_event_gate_suppressed_rows = 11`, and `paper_quote_blocker_stale_input_rows = 0`, which is a no-go diagnostic, not a live permission.
- Fresh readiness Summary must also include paper evidence blockers for promotion review. The current 073107 all-market shadow has `paper_score_freshness_status = NO_ACTIVE_DAY`, `live_forward_day_count = 0`, `locked_policy_params = false`, `fill_evidence_blockers = [missing_size_trade_rows, unresolved_resting_quotes]`, `conservative_fills = 0`, `queue_estimated_fill_legs = 1`, `missing_size_trade_rows = 400`, `unresolved_resting_quote_count = 46`, `counterfactual_reward_usdc = 176.767745`, and `actual_payout_evidence = false`.
- Fresh readiness Summary must include candidate-market diagnostics: `paper_quote_permission_market_counts = {austin: 4, dallas: 7, denver: 5, houston: 7}` plus top quoted cells. These fields guide paper-only market selection and do not weaken any go/no-go gate.
- Fresh `weather.market.market_making_readiness` output with `status = PASS`, zero blockers, and `live_capital_permission = false` is still required before any live discussion, and even then separate explicit operator authorization remains required. Latest selected-subset target-date artifact `data/backtest/mm_live_readiness_20260627T071559_subset_austin_dallas_houston.json` is `BLOCK` with 8 blockers; its platform gate sees schema `mm_platform_verification_v0.2` but blocks on missing operator/API proofs and all five `secret_redaction_*` proof checks. The latest all-market shadow artifact `data/backtest/mm_live_readiness_20260627T150554_post_snapshot_recovery_source_status_block.json` and latest active-window paper-forward artifact `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json` both remain no-go evidence with 11 blockers and 0 quote/live permissions. Inspect each Summary table and sorted `next_actions` because moving-tick counts and runtime/preflight state can change while the paper loop runs.
- Fresh exchange-economics drift before any new paper/live-forward evidence: latest current check `data/backtest/exchange_economics_drift_20260627_post_snapshot_recovery.json` is `PASS`, `material_change_count = 0`, `rescore_required = false`, and snapshot `xecon-036874d19e56c76f`.
- Latest selected-market readiness artifact `data/backtest/mm_live_readiness_20260627T071559_subset_austin_dallas_houston.json` is also `BLOCK` with 8 blockers; it proves Austin/Dallas/Houston can pass selected-market preflight and target-date CLOB cadence, but current quote policy still emits 0 quote permissions because snapshot cadence is degraded and some thin-tail books lack spread. Phase 2/live readiness is not satisfied.
- Latest daily-status readiness artifact `data/backtest/mm_live_readiness_20260627T0642_daily_status_stale_heartbeat.json` is `BLOCK` with 17 blockers after selecting same-target June 26 paper evidence; the top next action is `daily_roll_target_date_current` because the supervisor expects June 27 while the status still targets June 26. It also exposes the current stale runtime state: `daily_roll_action = blocked_restart_required`, `artifact_liveness_status = STALE_HEARTBEAT_METADATA`, and `operator_restart_reason = stale_heartbeat_metadata`. Latest explicit mismatch artifact `data/backtest/mm_live_readiness_20260627T112003_daily_status_flattened.json` is also `BLOCK` and proves a June 27 paper score cannot be mixed into the June 26 daily-roll status; `data/backtest/mm_live_readiness_20260627T0625_daily_status_target_mismatch.json` is the older regression artifact.
- Latest subset input checks: `event_metadata_validation_20260627_subset_austin_dallas_houston.json` is `PASS`; strict target-date CLOB audits for Austin, Dallas, and Houston each return `ok: true`; the latest subset run summary has preflight `PASS`, fresh source-status rows, 11 snapshot rows, and 11 CLOB feature rows for each of the three markets, but quote policy still blocks on stale/missing book rows at quote time.
- Fresh exchange adapter reconciliation report with `private_user_stream_required`, `cancel_all_requires_zero_open_orders_confirmation`, and `latency_stopgap_reject_handling_required` either observed or explicitly still blocked.
- Fixture-backed US private WebSocket normalization passing for fill, cancel, reject, and replace messages is necessary but not sufficient; the same path must be proven with a real private stream before live exposure.
- Fixture-backed cancel-all proof must include a cancel-all request artifact plus zero open orders after the request. A generic canceled order event is not enough.
- Fresh data-layer live gate.
- Fresh strict CLOB audit.
- Fresh one-market shadow tick.

Stop here unless the user explicitly authorizes a live pilot in a separate instruction.

## Phase 5: Future Live Pilot Guardrails

Only after explicit authorization and all gates pass:

- Use one market, one central band, smallest valid size.
- Harvest mode only.
- Post-only / participate-dont-initiate only.
- No market orders except explicit risk-reduction in a documented emergency.
- Do not treat an order/cancel response as final until the private user stream or a follow-up open-order check reconciles final state.
- Treat US latency-stopgap order rejects as no-fill stale-price protection, not as a signal to chase price or widen live scope.
- YES bid plus complementary-side representation only; no naked short assumptions.
- Dedicated isolated wallet with only pilot risk capital.
- One quote TTL, then cancel.
- Cancel immediately on stale book, stale source, stale watcher, user-stream failure, heartbeat failure, runtime drift, or unexpected fill lifecycle.
- Reconcile every fill against exchange state, local lifecycle, markout, fees, rebate estimate, and settlement.
- Do not scale after a lucky fill. Scale only after repeated countable evidence.

## Reward-Farming Policy Direction

Near term:

- Use model as veto, not as primary quote center.
- Quote harvest-only where preflight, known-edge map, source freshness, and CLOB recon are clean.
- Prefer central bands where liquidity rewards and volume exist.
- Avoid tails unless reward math and markout evidence prove the tradeoff.
- Treat rewards as a subsidy for good quoting, not as standalone yield.

Medium term:

- Add a platform-specific reward-score simulator.
- Build a target-size occupancy dashboard by market, band, side, hour, and competitor score.
- Estimate expected reward share under minimum-size, target-size, and queue-priority scenarios.
- Pair every reward estimate with adverse-selection markout.
- Promote model-skewed quoting only from countable live-forward evidence and slice-level confidence intervals.

Long term:

- Use reservation-price/inventory skew from market-making literature, adapted to binary event settlement.
- Compute event-level settlement distribution risk rather than simple token count.
- Use queue-position value as a simulator dimension, but keep conservative fills as the promotion gate.
- Add explicit anti-overfit controls for policy variants and reward-harvesting parameters.
