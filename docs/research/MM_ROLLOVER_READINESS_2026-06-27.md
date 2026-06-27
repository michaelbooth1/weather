# Market-Making Rollover Readiness

Date: 2026-06-27 local

Scope: current-date midnight rollover probe for the June 27, 2026 weather markets. This is keyless shadow/paper evidence only. It does not authorize live orders, `live-pilot`, credentials, wallet funding, or exchange-state mutation.

## Verdict

June 27 is not ready for countable paper-live-forward evidence or live capital.

Event metadata and exchange economics now validate for June 27. Explicit target-date CLOB capture and explicit target-date snapshot capture now reach all 12 June 27 event folders, but the current one-shot evidence is still noncountable shadow evidence with no quote permissions. After the latest public CLOB refresh, the remaining June 27 rollover-specific CLOB blocker is four Western target-date tapes with counted historical gaps from the pre-repair period. Those gaps cannot be repaired into countable same-day live-forward evidence; the correct action is to keep collecting and remain fail-closed.

## Artifacts

- Event metadata validation: `data/backtest/event_metadata_validation_20260627_midnight.json`
- Keyless shadow run: `data/mm_runs/2026-06-27/20260627T040113401310Z`
- Shadow run report: `data/mm_runs/2026-06-27/20260627T040113401310Z/run_report.md`
- Bounded paper diagnostic: `data/backtest/mm_paper_shadow_20260627T040113_midnight_probe.json`
- Bounded paper report: `data/backtest/mm_paper_shadow_20260627T040113_midnight_probe.md`
- Diagnostic known-edge output: `data/backtest/mm_known_edge_shadow_20260627T040113_midnight_probe.json`
- Refreshed exchange-economics publish: `data/backtest/exchange_economics_publish_20260627_midnight.json`
- Refreshed exchange-economics drift: `data/backtest/exchange_economics_drift_20260627_midnight.json`
- Previous keyless shadow run after economics/remediation fix: `data/mm_runs/2026-06-27/20260627T041123785887Z`
- Previous bounded paper diagnostic: `data/backtest/mm_paper_shadow_20260627T041123_after_economics_remediation_fix.json`
- Previous known-edge diagnostic: `data/backtest/mm_known_edge_shadow_20260627T041123_after_economics_remediation_fix.json`
- Previous target-date-aligned readiness: `data/backtest/mm_live_readiness_20260627T041123_shadow_target_aligned.json`
- Previous keyless shadow run after explicit local-date CLOB capture: `data/mm_runs/2026-06-27/20260627T042401695036Z`
- Previous bounded paper diagnostic after local-date capture: `data/backtest/mm_paper_shadow_20260627T042401_after_capture_recheck.json`
- Previous known-edge diagnostic after local-date capture: `data/backtest/mm_known_edge_shadow_20260627T042401_after_capture_recheck.json`
- Previous target-date-aligned readiness after local-date capture: `data/backtest/mm_live_readiness_20260627T042401_after_capture_recheck.json`
- Previous keyless shadow run after explicit target-date CLOB capture: `data/mm_runs/2026-06-27/20260627T044050256018Z`
- Previous bounded paper diagnostic after target-date capture: `data/backtest/mm_paper_shadow_20260627T044050_after_target_date_capture.json`
- Previous known-edge diagnostic after target-date capture: `data/backtest/mm_known_edge_shadow_20260627T044050_after_target_date_capture.json`
- Previous target-date-aligned readiness after target-date capture: `data/backtest/mm_live_readiness_20260627T044050_after_target_date_capture.json`
- Previous keyless shadow run after explicit target-date snapshot repair: `data/mm_runs/2026-06-27/20260627T050232213844Z`
- Previous bounded paper diagnostic after target-date snapshot repair: `data/backtest/mm_paper_shadow_20260627T050232_after_target_snapshot_repair.json`
- Previous known-edge diagnostic after target-date snapshot repair: `data/backtest/mm_known_edge_shadow_20260627T050232_after_target_snapshot_repair.json`
- Previous target-date-aligned readiness after target-date snapshot repair: `data/backtest/mm_live_readiness_20260627T050232_after_target_snapshot_repair.json`
- Latest keyless shadow run after default metadata, snapshot, and CLOB refresh: `data/mm_runs/2026-06-27/20260627T055820610723Z`
- Latest bounded paper diagnostic after metadata/snapshot/CLOB refresh: `data/backtest/mm_paper_shadow_20260627T055820_after_metadata_snapshot_refresh.json`
- Latest known-edge diagnostic after metadata/snapshot/CLOB refresh: `data/backtest/mm_known_edge_shadow_20260627T055820_after_metadata_snapshot_refresh.json`
- Latest target-date-aligned readiness after metadata/snapshot/CLOB refresh: `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.json`

## What Passed

- `weather.operations.event_metadata_validation --target-date 2026-06-27 --markets all` returned `PASS`.
- Event metadata validation summary: 12 markets, 12 pass, 0 mismatches, 0 stale, 0 block, 0 manual-review markets.
- Official Polymarket US docs were rechecked before refreshing the exchange-economics snapshot:
  - `https://docs.polymarket.us/fees`
  - `https://docs.polymarket.us/api-reference/orders/overview`
  - `https://docs.polymarket.us/api-reference/market/overview`
  - `https://docs.polymarket.us/incentives/liquidity`
  - `https://docs.polymarket.us/institutional/fix-api/fix-order-entry-overview`
  - `https://docs.polymarket.us/changelog`
- No material fee/reward/order-semantics drift was found versus `docs/research/exchange_economics_snapshot_template.json`.
- `weather.market.exchange_economics publish --target-date 2026-06-27 --platform polymarket_us --accept` returned `PASS`.
- `weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us` returned `PASS`, with material change count `0` and rescore required `false`.
- The economics snapshot now verifies `target_date=2026-06-27`, snapshot `xecon-036874d19e56c76f`, source hash `f4dad4615bc83281b5c144bc788ff77c`.
- The keyless shadow run emitted 0 live-trade-permission rows.
- The shadow run reserved 0 USDC, had 0 open lifecycle orders, and released 0 USDC.
- CLOB loop was running. A later strict audit returned `ok=true`, but eight markets still pointed at June 26 event slugs, so this is not target-date market-making readiness.
- The stale preflight remediation command was fixed in source: `active_event` and `clob_tokens` now suggest the exposed CLI command `python -m weather.market.market_microstructure capture --market all`, not the non-existent `refresh-tokens`.

## What Failed Closed

Keyless shadow command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once --event-metadata-validation data\backtest\event_metadata_validation_20260627_midnight.json
```

Result:

- Run folder: `data/mm_runs/2026-06-27/20260627T040113401310Z`
- Mode: `shadow`
- Evidence mode: `operator_drill`
- Preflight: `BLOCK`
- Row count: 12
- Quote-permission rows: 0
- Live-trade-permission rows: 0
- No-quote rows: 12
- Reason counts: 12 `NO_QUOTE_MISSING_PREFLIGHT`
- First failing gate: `active_event`
- First failing detail: `no active current market rows`
- Root cause class: `blocked_by_market_discovery`
- Live-forward gate: `BLOCK`

Top preflight blockers:

- 12/12 markets: exchange-economics snapshot missing current proof: `target_date_matches`.
- 12/12 markets: missing band-level CLOB feature rows.
- 12/12 markets: missing current snapshot/model rows.
- 12/12 markets: missing current source-status rows.
- 12/12 markets: no active current market rows.
- 8/12 markets: `clob_tokens.csv` has no rows.
- 8/12 markets: missing CLOB token ids or condition ids.
- 8/12 markets: missing current CLOB book rows.
- 8/12 markets: missing min-order-size or tick-size metadata.

Information-event gates were also active:

- 8 rows: WU current print window widened.
- 3 rows: market-open window widened.
- 1 row: Toronto SWOB print window pulled/suppressed.

## After Exchange-Economics Refresh

Refreshed economics command:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-27 --platform polymarket_us --accept --json-out data\backtest\exchange_economics_publish_20260627_midnight.json
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-27 --platform polymarket_us --json-out data\backtest\exchange_economics_drift_20260627_midnight.json
```

Historical keyless shadow command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once --event-metadata-validation data\backtest\event_metadata_validation_20260627_midnight.json
```

Post-refresh result:

- Run folder: `data/mm_runs/2026-06-27/20260627T041123785887Z`
- Mode: `shadow`
- Evidence mode: `operator_drill`
- Preflight: `WARN`
- Row count: 52
- Quote-permission rows: 0
- Live-trade-permission rows: 0
- No-quote rows: 52
- Reason counts: 44 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 8 `NO_QUOTE_MISSING_PREFLIGHT`
- First failing gate: `active_event`
- First failing detail: `no active current market rows`
- Root cause class: `blocked_by_preflight`
- Exchange economics: `PASS`
- Counts toward live-forward gate: false
- Live-forward gate: `BLOCK`

Current preflight-remediation root causes remain:

- 8 markets: missing active event.
- 8 markets: missing CLOB tokens.
- 8 markets: missing CLOB book rows.
- 8 markets: missing band-level CLOB feature rows.
- 8 markets: stale CLOB book tape.
- 8 markets: missing reward metadata.
- 8 markets: missing snapshot/model rows.
- 8 markets: stale model rows.
- 8 markets: missing source-status rows.
- 8 markets: stale source-status rows.
- 8 markets: blank or inactive CLOB discovery.

The bounded paper diagnostic for that run is `data/backtest/mm_paper_shadow_20260627T041123_after_economics_remediation_fix.json`:

- Gate status: `OPEN` only for the zero-exposure diagnostic score.
- Exchange economics: `PASS`.
- Paper-score freshness: `NO_ACTIVE_DAY`.
- Quote rows / legs: 52 / 0.
- Quote permissions / live permissions: 0 / 0.
- Fill simulation: `SKIPPED`.
- Fill evidence completeness: `SKIPPED`.
- Conservative fills: 0.
- Queue-estimated fill legs: 0.
- Total reward score: 0.
- Counterfactual reward status: `MISSING_POOL_OR_SCORE`.
- Actual payout evidence: false.

Known-edge interpretation after the refresh:

- 44 active-row quotes were blocked by known-edge permissions.
- 33 rows require `keep_blocked_until_promotion_gate_passes`.
- 11 rows require `collect_countable_markouts_before_map_change`.
- Do not expand or promote the known-edge map from this probe.

Target-date-aligned live readiness remains `BLOCK` in `data/backtest/mm_live_readiness_20260627T041123_shadow_target_aligned.json`:

- Live capital permission: false.
- Blocker count: 13.
- Event metadata and exchange economics pass.
- Preflight, CLOB/reward metadata, snapshot/model/source freshness, daily-roll runtime identity, active-day live-forward evidence, live-forward gate, quote permission, fill evidence, 14-day paper history, conservative P&L, actual reward payout, operator readiness, and platform verification remain blocking.

## After Explicit CLOB Capture And Rollover Recheck

Safe public-data command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure capture --market all
```

The command completed, and a follow-up CLOB status/audit at about `2026-06-27T04:28Z` showed a running capture loop with fresh heartbeat/books and strict audit `ok=true`. This is not target-date readiness, because strict audit still showed only Toronto, NYC, Atlanta, and Miami writing under June 27 event folders; Austin, Chicago, Dallas, Denver, Houston, Los Angeles, San Francisco, and Seattle still wrote under June 26 event folders.

Historical keyless shadow command after the capture:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once --event-metadata-validation data\backtest\event_metadata_validation_20260627_0020.json
```

Historical result:

- Run folder: `data/mm_runs/2026-06-27/20260627T042401695036Z`
- Mode: `shadow`
- Evidence mode: `operator_drill`
- Preflight: `WARN`
- Row count: 52
- Quote-permission rows: 0
- Live-trade-permission rows: 0
- No-quote rows: 52
- Reason counts: 22 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 22 `NO_QUOTE_STALE_INPUT`, 8 `NO_QUOTE_MISSING_PREFLIGHT`
- First failing gate: `model_freshness`
- First failing detail: `current model snapshot is stale or timestamp is missing`
- Exchange economics: `PASS`
- Counts toward live-forward gate: false
- Live-forward gate: `BLOCK`

Preflight split:

- Toronto and Miami passed preflight.
- NYC and Atlanta were stale only on `model_freshness`.
- Austin, Chicago, Dallas, Denver, Houston, Los Angeles, San Francisco, and Seattle remained blocked on active event, CLOB discovery/tokens/books/features/freshness, reward metadata, snapshot/model rows, source-status rows/freshness, and model freshness.

Current remediation root-cause counts:

- 8 markets: blank or inactive CLOB discovery.
- 8 markets: missing active event.
- 8 markets: missing CLOB book rows.
- 8 markets: missing band-level CLOB feature rows.
- 8 markets: missing CLOB tokens.
- 8 markets: missing reward metadata.
- 8 markets: missing snapshot/model rows.
- 8 markets: missing source-status rows.
- 8 markets: stale CLOB book tape.
- 8 markets: stale source-status rows.
- 10 markets: stale model rows.

The bounded paper diagnostic for this 04:24Z run is `data/backtest/mm_paper_shadow_20260627T042401_after_capture_recheck.json`:

- Gate status: `OPEN` only for the zero-exposure diagnostic score.
- Exchange economics: `PASS`.
- Paper-score freshness: `NO_ACTIVE_DAY`.
- Quote rows / legs: 52 / 0.
- Quote permissions / live permissions: 0 / 0.
- Fill simulation: `SKIPPED`.
- Fill evidence completeness: `SKIPPED`.
- Total reward score: 0.
- Counterfactual reward status: `MISSING_POOL_OR_SCORE`.
- Actual payout evidence: false.

Known-edge interpretation after the capture:

- 11 rows require `collect_countable_markouts_before_map_change`.
- 11 rows require `keep_blocked_until_promotion_gate_passes`.
- Do not expand or promote the known-edge map from this probe.

The target-date-aligned live readiness generated for this 04:24Z run is `BLOCK` in `data/backtest/mm_live_readiness_20260627T042401_after_capture_recheck.json`:

- Live capital permission: false.
- Blocker count: 13.
- Event metadata and exchange economics pass.
- Preflight, CLOB/reward metadata, snapshot/model/source freshness, daily-roll runtime identity evidence, active-day live-forward evidence, live-forward gate, quote permission, fill evidence, 14-day paper history, conservative P&L, actual reward payout, operator readiness, and platform verification remain blocking.
- The one-shot readiness gate now correctly reports absent daily-roll runtime evidence for one-shot/non-daily-roll status instead of treating the one-shot as a stale daily-roll runtime.

## After Target-Date Capture Fix

Code change:

- `market_microstructure capture`, `raw-refresh`, and `audit` now accept `--date YYYY-MM-DD`.
- Preflight remediation commands for active event, CLOB discovery/tokens/books/freshness, and reward metadata now include the preflight target date.
- This fixes the cross-timezone rollover mismatch where `capture --market all` used each market's local date, leaving Central/Mountain/Pacific markets on June 26 at `2026-06-27T04:xxZ`.

Safe target-date capture command:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure capture --market all --date 2026-06-27 --no-price-history --no-websocket-events
```

Result:

- Wrote target-date CLOB token/book folders for all 12 June 27 markets.
- `weather.market.market_microstructure audit --strict --date 2026-06-27` returned `ok=true` across all 12 June 27 folders.
- CLOB token/book discovery is no longer the leading June 27 blocker.

Historical keyless shadow command after the target-date capture:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once --event-metadata-validation data\backtest\event_metadata_validation_20260627_0020.json
```

Historical result:

- Run folder: `data/mm_runs/2026-06-27/20260627T044050256018Z`
- Mode: `shadow`
- Evidence mode: `operator_drill`
- Preflight: `WARN`
- Row count: 52
- Quote-permission rows: 0
- Live-trade-permission rows: 0
- No-quote rows: 52
- Reason counts: 44 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 8 `NO_QUOTE_MISSING_PREFLIGHT`
- First failing gate: `active_event`
- First failing detail: `no active current market rows`
- Exchange economics: `PASS`
- Counts toward live-forward gate: false
- Live-forward gate: `BLOCK`

Remaining preflight-remediation root causes:

- 8 markets: missing active event.
- 8 markets: missing snapshot/model rows.
- 8 markets: stale model rows.
- 8 markets: missing source-status rows.
- 8 markets: stale source-status rows.
- 8 markets: missing band-level CLOB feature rows.

The bounded paper diagnostic for this 04:40Z run is `data/backtest/mm_paper_shadow_20260627T044050_after_target_date_capture.json`:

- Gate status: `OPEN` only for the zero-exposure diagnostic score.
- Exchange economics: `PASS`.
- Paper-score freshness: `NO_ACTIVE_DAY`.
- Quote rows / legs: 52 / 0.
- Quote permissions / live permissions: 0 / 0.
- Fill simulation: `SKIPPED`.
- Fill evidence completeness: `SKIPPED`.
- Total reward score: 0.
- Counterfactual reward status: `MISSING_POOL_OR_SCORE`.
- Actual payout evidence: false.

Target-date-aligned live readiness remains `BLOCK` in `data/backtest/mm_live_readiness_20260627T044050_after_target_date_capture.json`:

- Live capital permission: false.
- Blocker count: 13.
- Event metadata, exchange economics, and explicit target-date CLOB audit passed at that stage.
- Preflight, snapshot/model/source freshness, active rows, target-date CLOB features, daily-roll runtime identity evidence, active-day live-forward evidence, live-forward gate, quote permission, fill evidence, 14-day paper history, conservative P&L, actual reward payout, operator readiness, and platform verification remain blocking.

## After Target-Date Snapshot Repair

Code change:

- `weather.collection.snapshot_tracker` now accepts `--date/--target-date` and `--market`.
- `snapshot_tracker --force --market all --date 2026-06-27` can write snapshot/model/source rows for all selected markets without waiting for each market's local midnight.
- `snapshot_tracker --status --date 2026-06-27` and `fleet_collection_health(..., target_date=...)` can inspect exact target-date folders instead of each market's latest local-date folder.
- Preflight remediation for snapshot/model/source gates now points at `python -m weather.collection.snapshot_tracker --force --market all --date <YYYY-MM-DD>`.
- CLOB preflight remediation now distinguishes a repairable stale trailing book from an unrecoverable counted tape gap. Counted gaps use root cause `clob_book_tape_gap_over_threshold`, are `recoverable_same_day = false`, and point to target-date audit verification rather than implying raw-refresh can make the day countable.

Safe target-date snapshot command:

```powershell
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force --market all --date 2026-06-27
```

Result:

- Completed with `blocked_markets = []` and `error_markets = []`.
- `current_fleet_collection_health(target_date="2026-06-27")` then reported all 12 markets `COLLECTING`, snapshot cadence `PASS`, and root cause counts `within_cadence: 12`.
- Source/snapshot/model rows are no longer the latest June 27 one-shot blocker.

Safe target-date CLOB refresh after the snapshot repair:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_microstructure capture --market all --date 2026-06-27 --no-price-history --no-websocket-events
```

Result:

- Wrote target-date CLOB token/book/features for all 12 markets.
- Latest strict target-date CLOB audit is now intentionally `ok=false` for countability: Denver, Los Angeles, San Francisco, and Seattle each have one counted historical gap over the 309s threshold, about 3305s max, from the pre-repair interval.
- This is not a missing-data repair blocker anymore; it is a noncountable-evidence blocker for June 27.

Historical keyless shadow command after refreshing default June 27 event metadata, target-date snapshots, and public CLOB books/features:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-27 --budget-usdc 500 --mode shadow --markets all --once
```

Historical result from that rollover-repair probe:

- Run folder: `data/mm_runs/2026-06-27/20260627T055820610723Z`
- Mode: `shadow`
- Evidence mode: `operator_drill`
- Preflight: `WARN`
- Row count: 132
- Quote-permission rows: 0
- Live-trade-permission rows: 0
- Reason counts: 55 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 44 `NO_QUOTE_STALE_INPUT`, 33 `NO_QUOTE_INFORMATION_EVENT`
- Remediation root cause: four counted historical `clob_book_tape_gap_over_threshold` gaps
- Live-forward gate: `BLOCK`

The bounded paper diagnostic for that historical rollover-repair probe is `data/backtest/mm_paper_shadow_20260627T055820_after_metadata_snapshot_refresh.json`:

- Gate status: `OPEN` only for the zero-exposure diagnostic score.
- Exchange economics: `PASS`.
- Paper-score freshness: `NO_ACTIVE_DAY`.
- Quote permissions / live permissions: 0 / 0.
- Fill evidence completeness: `PASS` only because no quotes rested.
- Model-variant scoring: `PASS`.
- Actual payout evidence: false.

Target-date-aligned live readiness remains `BLOCK` in `data/backtest/mm_live_readiness_20260627T055820_after_metadata_snapshot_refresh.json`:

- Live capital permission: false.
- Blocker count: 11.
- Snapshot/model/source freshness is no longer listed as a blocker in this one-shot artifact.
- Latest blockers are preflight, CLOB capture/reward freshness due counted CLOB gaps, daily-roll runtime identity evidence, active-day live-forward evidence, live-forward gate, countable quote permission, 14-day paper history, conservative P&L, actual reward payout, operator readiness, and platform verification. Fill evidence is not a blocker in this exact zero-quote diagnostic, but that does not prove promotion-grade fill/P&L evidence.

Current supersession note:

- Later explicit target-date CLOB audit cleared the immediate CLOB-gap blocker, and a forced snapshot/model refresh cleared maker-preflight model freshness.
- The latest all-market keyless shadow is now `data/mm_runs/2026-06-27/20260627T124837800878Z`, scored by `data/backtest/mm_paper_shadow_20260627T124837_current_source_status_block.json`, with readiness `data/backtest/mm_live_readiness_20260627T124837_current_source_status_block.json`.
- It remains `BLOCK` with 132 quote-intent rows, 132 no-quote `NO_QUOTE_MISSING_PREFLIGHT` rows, 0 quote-permission rows, 0 live-trade-permission rows, `snapshot_model_source_failing_gate_counts = {source_status_degradation: 12}`, and `model_freshness_failed_market_count = 0`.
- Therefore this rollover document should be read as historical midnight-repair evidence; the current all-market blocker is persistent source-status/provider-auth evidence plus noncountable paper evidence, not the old CLOB gap.

## Paper Diagnostic

Bounded diagnostic command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-27\20260627T040113401310Z --skip-fill-simulation --skip-model-variants --json-out data\backtest\mm_paper_shadow_20260627T040113_midnight_probe.json --report-out data\backtest\mm_paper_shadow_20260627T040113_midnight_probe.md --fills-out data\backtest\mm_paper_shadow_20260627T040113_midnight_probe_fills.csv --known-edge-out data\backtest\mm_known_edge_shadow_20260627T040113_midnight_probe.json --known-edge-report-out data\backtest\mm_known_edge_shadow_20260627T040113_midnight_probe.md
```

Result:

- Gate status: `BLOCK`
- Exchange economics: `BLOCK`
- Paper-score freshness: `NO_ACTIVE_DAY`
- Quote rows / legs: 12 / 0
- Quote permissions / live permissions: 0 / 0
- Fill simulation: `SKIPPED`
- Fill evidence completeness: `SKIPPED`
- Conservative fills: 0
- Queue-estimated fill legs: 0
- Total reward score: 0
- Counterfactual reward status: `MISSING_POOL_OR_SCORE`
- Actual payout evidence: false
- Model-variant scoring: `SKIPPED`
- Run-level model-variant bakeoff: `EMPTY`, `NO_ROWS`

Known-edge interpretation:

- Accepted map remains 17 records: 7 `harvest_only`, 3 `edge_research`, 7 `no_quote`.
- The June 27 shadow rows did not reach known-edge permission evaluation in a useful way because all rows were blocked by missing preflight.
- Do not expand or promote the known-edge map from this probe.

## Next Safe Actions

1. Treat the June 27 rollover drill as noncountable because eight target-date CLOB tapes have counted gaps.
2. Keep collecting continuous target-date CLOB and snapshot/model/source data; require the next active-day audit to have zero counted CLOB gaps before it can count.
3. Re-run keyless shadow and bounded paper scoring only after strict target-date CLOB audit passes and require nonzero quote permissions before diagnosing fill/reward quality.
4. Investigate known-edge coverage separately: the latest full 132-row shadow split is 44 known-edge permission blocks and 88 stale-input blocks.
5. Do not restart `live-pilot` or place orders. The current evidence is fail-closed and noncountable.
6. Do not treat the June 26 post-settlement paper loop or any June 27 one-shot shadow run as countable live-forward evidence.
