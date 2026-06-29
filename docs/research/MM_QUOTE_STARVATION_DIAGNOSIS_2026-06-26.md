# Market-Making Quote Starvation Diagnosis

Date: 2026-06-26

Scope: active repo evidence for why the maker is producing zero executable quote permissions while preparing for liquidity-reward farming. No live orders were placed.

## Summary

The current blocker is no longer missing active-date metadata or exchange economics. Stable keyless post-settlement drills passed preflight across all 12 markets.

After the METAR pull window cleared on the prior active-date drill, a stable post-settlement run emitted 1 quote-permission row and 0 live-trade-permission rows. That quoted row is useful evidence, but it is not countable live-forward evidence because it was collected after the active window in `post_settlement_evaluation` mode.

Current first blocker update: latest all-market active-window paper-live-forward evidence `data/mm_runs/2026-06-27/20260627T135932865534Z` does not reach the known-edge/policy starvation layer. It fails closed at preflight on `source_status_degradation` for all 12 markets, with 132 quote-intent rows, 132 no-quote `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, 0 live permissions, paper freshness `PASS`, fill evidence `BLOCK` with `no_quote_legs`, and readiness `data/backtest/mm_live_readiness_20260627T135932_after_clob_recovery_source_status_block.json` still `BLOCK`. Preflight remediation also reports 3 stale model rows and 1 stale/missing snapshot-model row. The latest all-market shadow/operator-drill evidence `data/mm_runs/2026-06-27/20260627T135111048558Z` reaches the same source-status no-go after CLOB and observation-trigger recovery. The immediate repair is free-source replacement/source-health plus source-status backfill; the known-edge findings below remain the next diagnostic layer after source-status proof clears.

Aggregate active-window update: bounded latest-five paper-live-forward scoring selected `111731`, `112944`, and `131743` and still found 396 quote rows, 0 quote-permission rows, 0 live permissions, and fill evidence `BLOCK`. The newer single-run paper-forward drill `135932` confirms the same no-go after CLOB recovery. Current quote starvation is preflight/source-status starvation across active paper-forward evidence, not merely a one-tick policy/no-edge artifact.

The current daily roll was later repaired during the June 26 active window and produced active-day `paper-live-forward` artifacts. After the latest diagnostic/reporting edits, the continuous paper loop briefly entered `STALE_CODE` backoff. After the `2026-06-27T03:18:39Z` retry window cleared, safe `ensure --force` quarantined the stale folder and restarted the loop onto current source, so latest status is PID 29180, supervisor state `RUNNING`, action `noop`, runtime identity matching current source, latest runtime folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, evidence mode `post_settlement_evaluation`, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, and `current_counts_toward_live_forward_gate = false`. Daily-roll status now correctly ignores newer one-shot shadow folders when selecting operator-report artifacts and exposes `current_counts_toward_live_forward_gate` from the latest folder's live-forward gate. The latest current-source v0.8 backoff-recheck active score `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` scored 4,807 quote-intent rows, 0 quote-permission rows, 0 quote uptime, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, 0 quote legs, and 0 live-trade-permission rows. A current-source keyless shadow tick during `INFO_EVENT_METAR_PRINT`, `data/mm_runs/2026-06-26/20260627T004704070519Z`, passed preflight across all 12 markets and emitted 0 quote permissions: 88 known-edge blockers plus 44 information-event suppressions. A later post-event keyless shadow tick, `data/mm_runs/2026-06-26/20260627T010734537264Z`, passed preflight and emitted 6 harvest-only shadow quote permissions in Austin, Dallas, and Houston, still with 0 live-trade permissions. Its paper score has 12 quoted legs, 0 fills, paper freshness `NO_ACTIVE_DAY`, and fill evidence `BLOCK`, so it is useful noncountable diagnostics rather than promotion-grade evidence. The latest regenerated recovered fixed paper-live-forward post-settlement score `data/backtest/mm_paper_postsettlement_recovered_20260627T0233_competitor_source.json` captured 17 quote permissions, 0 live permissions, 34 quoted legs, reward score 89.72025, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, and CLOB-calibrated competitor-score diagnostics.

The current quote-starvation state is therefore:

- 1 non-countable Dallas harvest quote in the prior post-settlement drill.
- 9 non-countable Dallas harvest quotes in the later June 26 shadow drill.
- 0 quote permissions in the current active-day daily roll.
- 6 non-countable harvest-only quote permissions in the latest historical current-source shadow drill, with fill evidence still `BLOCK`.
- Current active-window June 27 evidence is blocked earlier by source-status degradation across all 12 markets. Historical active-day scored rows, after source-status/model/CLOB preflight passes, were blocked primarily by known-edge/promotion permission with a clear information-event overlap. The current-source active folder also showed a smaller stale-input contribution. The continuous running process remains post-settlement/noncountable; the latest historical clean current-source one-shot has no stale inputs and six noncountable harvest-only quote permissions, while the regenerated recovered fixed paper-live-forward score captured 17 noncountable quote permissions across recent ticks. Countable active daily-roll evidence still has zero quote permissions and remains blocked before promotion.
- June 27 target-date snapshot/model/source repair succeeded, and the default event-metadata artifact was refreshed back to June 27, but this did not create countable quote evidence. The latest all-market shadow/operator drill is `data/mm_runs/2026-06-27/20260627T135111048558Z`, after CLOB and observation-trigger recovery. It fails closed at preflight on `source_status_degradation`, with 132 quote-intent rows, 132 no-quote `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote permissions, 0 live permissions, and readiness `data/backtest/mm_live_readiness_20260627T135111_after_clob_recovery_source_status_block.json` still `BLOCK`. The latest active paper-forward run `data/mm_runs/2026-06-27/20260627T135932865534Z` confirms the same first blocker with active-day evidence mode; its readiness adds `snapshot_model_source_failing_gate_counts = {model_freshness: 3, source_status_degradation: 12}`.
- Earlier June 27 all-market drills remain historical context for the next diagnostic layer after source-status clears. The 055820 run had 55 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 44 `NO_QUOTE_STALE_INPUT` rows, and 33 `NO_QUOTE_INFORMATION_EVENT` rows, and the 073107 run later emitted 23 noncountable harvest-only quote permissions in Austin, Dallas, Denver, and Houston. Those runs are useful for known-edge/promotion and missing-book analysis, but current source-status proof now blocks every market before policy quote permission can be interpreted.
- A short snapshot/model liveness regression was repaired with `weather.collection.snapshot_tracker --ensure`; snapshot cadence is now `PASS`, but quote permissions remain zero.
- 0 live-trade-permission rows.

This means the next preparation work should not be live-order work. It should be known-edge map coverage, promotion evidence, reward metadata/scoring, missing-book repair, and countable paper markout collection during the next active window.

## June 27 Target-Date Repair Addendum

After adding target-date-aware snapshot and CLOB capture paths, the safe repair sequence reached all 12 configured markets for `2026-06-27`:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force --market all --date 2026-06-27
.\venv\Scripts\python.exe -m weather.market.market_microstructure capture --market all --date 2026-06-27 --no-price-history --no-websocket-events
.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-27 --markets all
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
```

Current artifacts:

- Run folder: `data/mm_runs/2026-06-27/20260627T055820610723Z`.
- Paper diagnostic: `data/backtest/mm_paper_shadow_20260627T055820_after_metadata_snapshot_refresh.json`.
- Known-edge diagnostic: `data/backtest/mm_known_edge_shadow_20260627T055820_after_metadata_snapshot_refresh.json`.
- Readiness report: `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.md`.

Latest quote-starvation split:

| Market | Rows | Policy reason | Known-edge state | Event gate |
|---|---:|---|---|---|
| atlanta | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| austin | 11 | `NO_QUOTE_INFORMATION_EVENT` | `event_gate_suppress/harvest_only/SHADOW` | `SUPPRESS` |
| chicago | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| dallas | 11 | `NO_QUOTE_INFORMATION_EVENT` | `event_gate_suppress/harvest_only/SHADOW` | `SUPPRESS` |
| denver | 11 | `NO_QUOTE_STALE_INPUT` | `source_freshness_model_gap/harvest_only/SHADOW` | `SUPPRESS` |
| houston | 11 | `NO_QUOTE_INFORMATION_EVENT` | `event_gate_suppress/harvest_only/SHADOW` | `SUPPRESS` |
| los-angeles | 11 | `NO_QUOTE_STALE_INPUT` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| miami | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| nyc | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| san-francisco | 11 | `NO_QUOTE_STALE_INPUT` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| seattle | 11 | `NO_QUOTE_STALE_INPUT` | `promotion_block/no_quote/BLOCK` | `SUPPRESS` |
| toronto | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record/no_quote/BLOCK` | `SUPPRESS` |

Diagnostic conclusions:

- Quote permissions: 0 of 132 rows.
- Live trade permissions: 0 of 132 rows.
- `quote_blocker_diagnostics.blocked_fraction`: 1.0.
- `known_edge_allowed_false_rows`: 132.
- `inferred_known_edge_record_match_rows`: 0.
- `inferred_known_edge_record_miss_rows`: 11.
- Latest known-edge map output still has 17 records: 7 `harvest_only`, 3 `edge_research`, and 7 `no_quote`.

Strict CLOB audit remains noncountable for the eight stale markets because the counted gaps were already in the tape. The suggested remediation is evidence collection, not a same-day quote override: collect a clean continuous CLOB tape for the target date, then re-run strict audit, shadow, and paper scoring. Do not broaden the known-edge map from this noncountable run.

## METAR Pull Drill

Command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-25 --budget-usdc 500 --mode paper-live-forward --markets all --once --evidence-mode post_settlement_evaluation
```

Run folder:

```text
data/mm_runs/2026-06-25/20260626T015818139432Z
```

Result:

- Mode: `paper-live-forward`.
- Evidence mode: `post_settlement_evaluation`.
- Target date: `2026-06-25`.
- Preflight status: `PASS`.
- Markets: 12.
- Blocked markets: 0.
- Stale markets: 0.
- Row count: 132.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- First failing gate: `policy`.
- First failing detail: `policy produced rows but no executable permissions`.
- Root cause class: `policy_no_edge`.
- Exchange economics status: `PASS`.
- Event metadata status: `PASS`.
- Useful-work liveness: `SKIPPED`, correctly, because the drill was not active-day live-forward evidence.

Reason counts:

- `NO_QUOTE_KNOWN_EDGE_PERMISSION`: 121.
- `NO_QUOTE_INFORMATION_EVENT`: 11.

Known-edge and promotion split:

- 66 rows: `known_edge_permission = no_quote`, `known_edge_allowed = False`, `known_edge_reason = promotion_block`, `promotion_state = BLOCK`.
- 33 rows: `known_edge_permission = no_quote`, `known_edge_allowed = False`, `known_edge_reason = missing_known_edge_record`, `promotion_state = SHADOW`.
- 22 rows: `known_edge_permission = no_quote`, `known_edge_allowed = False`, `known_edge_reason = missing_known_edge_record`, `promotion_state = BLOCK`.
- 11 rows: `known_edge_permission = harvest_only`, `known_edge_allowed = False`, `known_edge_reason = awaiting_paper_markouts`, `promotion_state = SHADOW`.

Event gate:

- 132 rows had `event_gate_status = PULL`, `event_gate_action = suppress`, and `event_gate_reason_code = INFO_EVENT_METAR_PRINT`.
- Dallas emitted `NO_QUOTE_INFORMATION_EVENT`; the other markets emitted earlier known-edge/promotion blockers.

## Post-METAR Stable Drill

Command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-25 --budget-usdc 500 --mode paper-live-forward --markets all --once --evidence-mode post_settlement_evaluation
```

Run folder:

```text
data/mm_runs/2026-06-25/20260626T020148684548Z
```

Result:

- Mode: `paper-live-forward`.
- Evidence mode: `post_settlement_evaluation`.
- Target date: `2026-06-25`.
- Preflight status: `PASS`.
- Markets: 12.
- Blocked markets: 0.
- Stale markets: 0.
- Row count: 132.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Root cause class: `trading_permissions_emitted`.
- Exchange economics status: `PASS`.
- Event metadata status: `PASS`.
- Useful-work liveness: `SKIPPED`, correctly, because the drill was not active-day live-forward evidence.

Reason counts:

- `NO_QUOTE_KNOWN_EDGE_PERMISSION`: 121.
- `NO_QUOTE_MISSING_BOOK`: 10.
- `QUOTE_HARVEST_MID`: 1.

Quoted row:

- Market: Dallas.
- Range: `92-93 F`.
- Side: `TWO_SIDED`.
- Reason: `QUOTE_HARVEST_MID`.
- Known-edge permission: `harvest_only`.
- Known-edge reason: `awaiting_paper_markouts`.
- Promotion state: `SHADOW`.
- Event gate: `CLEAR`.
- Market mid: 0.9995.
- Fair probability: 0.9998330377336805.
- Edge: 0.0003330377336804302.
- Bid: 0.9895 for 5 contracts.
- Ask: 0.999 for 5 contracts.
- Quote risk: 4.9525 USDC.
- Expected reward score: 1.0.
- Expected rebate value: 0.0.
- Live-trade permission: false.

## Latest Market Split

| Market | Rows | Emitted reason | Known-edge reason | Promotion state |
|---|---:|---|---|---|
| atlanta | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record` | `BLOCK` |
| austin | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record` | `SHADOW` |
| chicago | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block` | `BLOCK` |
| dallas | 10 no-quote, 1 quote | `NO_QUOTE_MISSING_BOOK`, `QUOTE_HARVEST_MID` | `awaiting_paper_markouts` | `SHADOW` |
| denver | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record` | `SHADOW` |
| houston | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record` | `SHADOW` |
| los-angeles | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block` | `BLOCK` |
| miami | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block` | `BLOCK` |
| nyc | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block` | `BLOCK` |
| san-francisco | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block` | `BLOCK` |
| seattle | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `promotion_block` | `BLOCK` |
| toronto | 11 | `NO_QUOTE_KNOWN_EDGE_PERMISSION` | `missing_known_edge_record` | `BLOCK` |

## One-Run Paper Score

The latest stable run was scored with a bounded paper command before the streamed-casebook, compact-leg, and quote-row release runtime fixes. A later full-corpus standard model-variant run wrote `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`, but it remains blocked because fill evidence is `BLOCK` and model-variant promotion is `BLOCK`. The standard report now identifies the fill-evidence gaps directly: 8,893 missing-size trade rows, 2,182 missing-book queue legs, and 26 missing-trade-size queue legs.

Command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z --json-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.json --report-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.md --fills-out data\backtest\mm_paper_quote_starvation_fills_20260626T020148684548Z.csv --known-edge-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.json --known-edge-report-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.md
```

Result:

- Quote rows: 132.
- Quote legs: 2.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Gate status: `OPEN`.
- Paper score freshness: `NO_ACTIVE_DAY`.
- Fill evidence status: `BLOCK`.
- Missing size trade rows: 1,944.
- Missing book queue legs: 1.
- P&L, reward, and rebate estimates: 0.

The latest diagnostic known-edge map has 217 records: 177 `harvest_only`, 37 `no_quote`, and 3 `edge_research`. This is useful for diagnosis only; it should not replace the standard full-corpus known-edge map until promotion-grade scoring is made reliable and current.

## Earlier Active-Day Score

An earlier bounded active-day promotion-grade score selected `data/mm_runs/2026-06-25/20260626T015448206993Z`:

- Command output: `MM paper: 0 conservative fills, 0 queue-estimated fill legs, gate OPEN`.
- Quote rows / legs: 132 / 0.
- Quote-permission rows: 0.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`.
- Quote-blocker diagnostics from `data/backtest/mm_paper_bounded_latest_active_skip_variants_20260626.md`:
  - Blocked rows: 132.
  - Blocked fraction: 1.0.
  - Quote-permission rows: 0.
  - Known-edge permission-blocked rows: 121.
  - Known-edge state rows: 132.
  - Known-edge allowed=false rows: 132.
  - Harvest-only rows suppressed by the event gate: 11.
  - Event-gate suppressed rows: 132.
  - Top known-edge states: 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, 11 `awaiting_paper_markouts/harvest_only/SHADOW`.
  - Top event-gate state: 132 `PULL/suppress/INFO_EVENT_METAR_PRINT`.
- Paper-score freshness: `PASS`.
- Fill evidence completeness: `PASS`, only because there were no quoted legs to evaluate.
- Reward score: 0.

Interpretation: the active-day run is countable for freshness but provides no reward-farming evidence because policy emitted no quotes. Blockers overlap: the METAR event gate suppressed every row, while known-edge/promotion state still blocked 121 emitted rows and Dallas remained information-event blocked. The post-settlement Dallas quote is useful for diagnosis, but it is not countable active-window evidence.

## Earlier June 26 Shadow Score

After June 26 CLOB, event metadata, and exchange economics were current, the keyless shadow drill `data/mm_runs/2026-06-26/20260626T132648384687Z` still produced no quote permissions:

- Command output: `MM run: 0 quote rows, 132 no-quote rows, preflight WARN`.
- Preflight first failing gate: `model_freshness`.
- Per-market preflight: 11 markets `STALE` on model freshness; Toronto `PASS`.
- No-quote reasons: 121 `NO_QUOTE_STALE_INPUT`, 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Bounded paper score: `data/backtest/mm_paper_shadow_20260626T132648384687Z_20260626.json`.
- Paper score result: 132 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, fill evidence `PASS` only because there were no quoted legs.
- Exchange-economics gate: `PASS`, target date `2026-06-26`, verified-for target date `2026-06-26`.

Interpretation: this June 26 blocker was not missing CLOB or economics anymore. It was stale model snapshots across 11 markets plus missing known-edge permission for Toronto.

## Latest June 26 Shadow Score

After the snapshot/model loop caught up, the keyless shadow drill `data/mm_runs/2026-06-26/20260626T134201734227Z` produced limited Dallas quote permission while still emitting no live-trade permission:

- Command output: `MM run: 9 quote rows, 123 no-quote rows, preflight PASS`.
- Preflight first failing gate: none.
- Quote-permission rows: 9.
- Live-trade-permission rows: 0.
- Quoted rows: Dallas `87 F or below`, `88-89 F`, `90-91 F`, `96-97 F`, `98-99 F`, `100-101 F`, `102-103 F`, `104-105 F`, and `106 F or higher`; all were two-sided `QUOTE_HARVEST_MID` rows capped by the early-hour guardrail to 1.75 shares per side.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`.
- Bounded paper score: `data/backtest/mm_paper_shadow_20260626T134201734227Z_20260626.json`.
- Paper score result: 132 quote rows, 18 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 12.26505, counterfactual reward 109.2508 USDC, fill evidence `BLOCK`.
- Fill blockers: 784 missing-size trade rows and 18 unresolved resting quotes because active-day settlement evidence was not available.
- Exchange-economics gate: `PASS`, target date `2026-06-26`, verified-for target date `2026-06-26`.

Interpretation: stale model snapshots are no longer the immediate current-date blocker. The current shadow blocker is sparse, non-countable quote permission, mostly driven by known-edge coverage. The bounded score is useful only as shadow diagnostics until active-window paper-live-forward evidence has nonzero quote permissions and fill/settlement evidence resolves.

## June 26 Countable Daily-Roll Evidence

The daily roll was repaired and restarted during the June 26 active evidence window:

- Point-in-time diagnostic run folder: `data/mm_runs/2026-06-26/20260626T135556165467Z`.
- Mode: `paper-live-forward`.
- Evidence mode: `active_day_live_forward`.
- Latest status check after guarded recovery: status `started`, PID 29180, latest run folder `data/mm_runs/2026-06-26/20260627T031938117215Z`, evidence mode `post_settlement_evaluation`, latest tick rows 132, useful-work liveness `SKIPPED`, live-forward gate `BLOCK`, `current_counts_toward_live_forward_gate = false`, daily-roll supervisor state `RUNNING`, supervisor action `noop`, and runtime identity matching current source. This matters operationally: stale-source recovery is complete, but after-window evidence remains noncountable.
- Previous fixed bounded diagnostic artifact: `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_known_edge_dims_20260626.json`.
- Previous fixed bounded diagnostic result: 4,092 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, and fill evidence `PASS` only because no quoted legs existed.
- Quote-blocker diagnostics from that fixed score: 4,070 known-edge permission-blocked rows, 22 stale-input rows, 396 event-gate suppressed rows, and top known-edge states of 2,046 `promotion_block/no_quote/BLOCK`, 1,364 `missing_known_edge_record/no_quote/SHADOW`, and 682 `missing_known_edge_record/no_quote/BLOCK`.
- Exact missing-dimension diagnostics show the top missing active-row records have `hour_utc = 14` or `15`, `band_distance_bucket = (missing)`, `casebook_taxonomy = (missing)`, `regime = none`, `source_freshness_state = all_fresh`, and `book_imbalance_bucket = (missing)`.
- Previous bounded quote diagnostic from the active daily-roll tape before the v0.3 quote-schema change: `data/backtest/mm_paper_active_latest_20260626_quote_diag.json`, from `data/mm_runs/2026-06-26/20260626T160337445814Z`, scored 4,224 accumulated quote rows, 0 quote legs, 0 quote-permission rows, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS`, paper freshness `PASS`, live-forward paper days 1, 3,916 known-edge permission-blocked rows, 308 stale-input rows, and 44 event-gate-suppressed rows. It reports `mm_quote_blocker_diagnostics_v0.7`. Exact policy-match dimensions were not yet present in that moving loop tape, so the diagnostic-only inferred table surfaced likely active buckets; the dry-run map comparison found 0 inferred known-edge record matches and 2,112 inferred missing-record rows still missing. Top blocker overlaps are still dominated by known-edge permission under `INFO_EVENT_CLEAR`, with smaller WU-current widen and stale-input intervals.
- v0.3 quote-schema probe: a separate keyless shadow run under `%TEMP%\weather-mm-v03-probe\2026-06-26\codex-v03-probe` wrote `mm_quote_intent_v0.3` rows with `known_edge_match_*` fields populated from the actual matcher dimensions. Its final diagnostic report `data/backtest/mm_paper_v03_probe_20260626_quote_diag.json` has 132 blocked rows, 0 quote-permission rows, 88 known-edge permission-blocked rows, 44 stale-input rows, and 0 event-gate-suppressed rows after moving model-freshness inputs aged into `WARN`. The quote tape split is 55 `promotion_block/no_quote/NO_QUOTE_KNOWN_EDGE_PERMISSION`, 33 `missing_known_edge_record/no_quote/NO_QUOTE_KNOWN_EDGE_PERMISSION`, 33 `missing_known_edge_record/no_quote/NO_QUOTE_STALE_INPUT`, and 11 `promotion_block/no_quote/NO_QUOTE_STALE_INPUT`. Exact matcher fields now show `hour_utc = 16`, source freshness `true/all_fresh`, and real missing band-distance, taxonomy, and book-imbalance buckets where the input rows do not provide them. The blocker is therefore real coverage/promotion/freshness state, not a reporting artifact.
- Current-source v0.3 event-window shadow probe: `data/mm_runs/2026-06-26/20260626T165003338813Z` ran keyless `shadow --once` with preflight `PASS` and scored to `data/backtest/mm_paper_shadow_20260626T165003338813Z_v03_current.json`. It found 132 blocked rows, 0 quote-permission rows, 132 known-edge permission-blocked rows, 0 stale-input rows, 132 event-gate-suppressed rows, 0 inferred record matches, and 66 inferred misses. The top overlap was `NO_QUOTE_KNOWN_EDGE_PERMISSION` under `INFO_EVENT_METAR_PRINT`, so the event gate and known-edge gate both fail closed on current-source active inputs.
- Current-source v0.3 WU/SWOB shadow probe: `data/mm_runs/2026-06-26/20260626T170013329405Z` scored to `data/backtest/mm_paper_shadow_20260626T170013329405Z_v03_current.json`. It found 132 blocked rows, 0 quote-permission rows, 121 known-edge permission-blocked rows, 11 stale-input rows, 11 event-gate-suppressed rows, 0 inferred record matches, and 66 inferred misses. Preflight was `WARN` on `model_freshness`; Seattle's latest model snapshot was about 928.5 seconds old.
- Current-source active daily-roll score after the v0.8 backoff recheck: `data/backtest/mm_paper_active_20260626T231738340378Z_v08_backoff_recheck.json` selected `data/mm_runs/2026-06-26/20260626T231738340378Z`. It found 4,807 blocked rows, 0 quote-permission rows, 4,345 known-edge permission-blocked rows, 462 stale-input rows, 1,243 event-gate-suppressed rows, 0 inferred record matches, and 2,376 inferred misses. Reason counts are 4,345 `NO_QUOTE_KNOWN_EDGE_PERMISSION` and 462 `NO_QUOTE_STALE_INPUT`; the top required-action buckets are 2,178 promotion-blocked rows, 1,441 missing SHADOW cells needing countable markouts, and 726 missing BLOCK cells needing countable markouts.
- Current-source one-shot `data/mm_runs/2026-06-26/20260627T004704070519Z` passed preflight during `INFO_EVENT_METAR_PRINT`, wrote 132 quote rows, 0 quote-permission rows, and 0 live-trade-permission rows. Its diagnostic `data/backtest/mm_paper_shadow_20260627T004704070519Z_current_source.json` has 88 known-edge permission-blocked rows, 44 `NO_QUOTE_INFORMATION_EVENT` rows, 132 event-gate-suppressed rows during `INFO_EVENT_METAR_PRINT`, 0 stale-input blockers, 0 inferred known-edge record matches, and 11 inferred misses.
- Latest current-source one-shot `data/mm_runs/2026-06-26/20260627T010734537264Z` passed preflight after the event gate cleared, wrote 132 quote rows, 6 quote-permission rows, 0 live-trade-permission rows, 88 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 34 `NO_QUOTE_MISSING_BOOK`, 4 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, and 6 `QUOTE_HARVEST_MID` rows. Its diagnostic `data/backtest/mm_paper_shadow_20260627T010734537264Z_current_source.json` has 12 quoted legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 26.8405, counterfactual reward 211.60828 USDC under the default pool/competition assumption, paper freshness `NO_ACTIVE_DAY`, and fill evidence `BLOCK` because trade-size rows, queue-book rows, and resting quote resolution are incomplete.
- Current-source shadow check after the hour-normalization fix: `data/mm_runs/2026-06-26/20260626T172330853600Z` had preflight `WARN` on `model_freshness`, 132 blocked rows, 0 quote-permission rows, 99 known-edge permission-blocked rows, 33 stale-input rows, 0 event-gate-suppressed rows, 0 inferred matches, and 66 inferred misses. This confirms that canonicalizing `HH:00Z` map hours does not by itself restore quote permission under current active inputs.

Interpretation: daily-roll artifact selection is now protected from shadow-probe interference, and the current-source one-shots isolate policy/event/book blockers from the continuous loop. The scored-row blocker is known-edge coverage, with information-event suppression in the earlier tick and missing-book/cadence blockers in the later ticks. The remaining operational blocker is noncountable post-settlement evidence. The latest current-source active score, recovered post-settlement score, and shadow probes are still not promotion evidence because active live-forward quote permissions are 0, the newest permissions are noncountable, and fill evidence remains blocked. The active evidence confirms quote starvation under the default known-edge map and promotion gates, even though the latest one-shot and recovered post-settlement score prove a narrow harvest-only path can emit permissions once event gates clear.

## Active-Row Known-Edge Map Mismatch

The current accepted `data/backtest/mm_known_edge_map.json` has 17 records and now includes a broad Dallas `harvest_only` row. That explains why Dallas has one `QUOTE_HARVEST_MID` row in the latest moving folder and why most current Dallas blocks are `NO_QUOTE_MISSING_BOOK`, `NO_QUOTE_INFORMATION_EVENT`, `NO_QUOTE_STALE_INPUT`, or `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED`, not known-edge permission. Other markets remain blocked by `promotion_block` or `missing_known_edge_record`. This is still safe fail-closed behavior and not a reason to force quotes or promote the generated candidate map.

## Liveness Fixes From This Pass

Two scoped runtime-identity fixes were made because all-market useful-work liveness was reporting stale runtime identity even when individual supervisor status checks were scoped and current:

- `src/weather/collection/snapshot_store.py` now uses `current_identity_for(process_identity)` inside `runtime_identity_guard`.
- `src/weather/market/market_making_run.py` now compares each supervisor loop against `current_identity_for(process)` inside `runtime_identity_snapshot`.
- `src/weather/runtime_identity.py` now lets `current_identity_for(recorded)` use `recorded["repo_root"]` when no explicit repo root is passed.
- `tests/market/test_market_making_run.py` now has a regression proving a scoped loop identity ignores unrelated source changes but still detects changes to recorded scoped files.

Validation:

- `.\venv\Scripts\python.exe -m pytest tests\market\test_market_making_run.py tests\operations\test_runtime_identity.py -q`
  - Result: 36 passed.
- `.\venv\Scripts\python.exe -m py_compile src\weather\runtime_identity.py src\weather\market\market_making_run.py src\weather\collection\snapshot_store.py src\weather\collection\snapshot_tracker.py src\weather\market\market_microstructure.py`
  - Result: passed.

Local supervisor remediation:

- Restarted `weather.collection.snapshot_tracker --restart`.
- Restarted `weather.market.market_microstructure restart`.
- Restarted `weather.operations.observation_trigger` via `restart`, then `ensure` after the stale writer lock cleared.
- Ran `weather.operations.market_making_daily_roll ensure`; it correctly restarted the old daily roll as stale-code and quarantined the prior active run folder.

Important caveat: the first restarted daily roll began after the local active evidence window, so it was classified as `post_settlement_evaluation` and did not count toward live-forward gates. The latest safe recovery also landed in `post_settlement_evaluation`; it repaired runtime identity but did not add countable active-day evidence.

## Interpretation

The bot is behaving conservatively:

- It can pass active-date metadata and exchange-economics gates.
- It can run with current snapshots/books after supervisor restart.
- It emits a small harvest quote only after an information-event pull clears.
- It still refuses most rows because the known-edge map and promotion evidence do not allow them.
- The information-event gate can suppress otherwise closer-to-eligible cells during METAR windows.

This is the correct capital-preservation posture. Reward farming should not proceed until at least one market/band has positive, current, markout-aware harvest permission and nonzero reward score under the active platform formula.

## Next Actions

1. Extend `docs/research/MM_KNOWN_EDGE_COVERAGE_2026-06-26.md` into a remediation plan:
   - decide which missing known-edge keys should remain `no_quote`;
   - decide which keys should collect shadow evidence;
   - keep Dallas missing-book rows separate from true policy no-edge rows.
2. For promotion-blocked markets, inspect the paper report and model-variant bakeoff evidence that drives `promotion_state = BLOCK`.
3. For current-date operation, keep the daily roll and snapshot loop healthy, then collect post-event-gate active-window paper evidence; if quote permissions remain zero, prioritize active-row known-edge coverage and promotion-state remediation before any live work.
4. Extend the new reward-score diagnostics into payout/share simulation: target-size occupancy, competitor score, score share, and reward-dollar attribution by market/band/hour.
5. Use bounded `weather.market.mm_paper --target-date ... --latest-n ...` for targeted active-window diagnostics, use the full-corpus standard model-variant report for current fill/queue/markout and model-variant diagnostics, and use `--skip-fill-simulation --skip-model-variants` only for quote/reward diagnostics. Continue improving fill-evidence blockers and collecting independent target days before treating the standard path as promotion-grade.
6. Do not run live-pilot. The current state remains no-go for live capital.
