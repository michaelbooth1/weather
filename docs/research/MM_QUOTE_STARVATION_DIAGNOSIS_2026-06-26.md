# Market-Making Quote Starvation Diagnosis

Date: 2026-06-26

Scope: active repo evidence for why the maker is producing zero executable quote permissions while preparing for liquidity-reward farming. No live orders were placed.

## Summary

The current blocker is no longer missing active-date metadata or exchange economics. Stable keyless post-settlement drills passed preflight across all 12 markets.

After the METAR pull window cleared, the latest stable drill emitted 1 quote-permission row and 0 live-trade-permission rows. The quoted row is useful evidence, but it is not countable live-forward evidence because it was collected after the active window in `post_settlement_evaluation` mode.

The current quote-starvation state is therefore:

- 1 non-countable Dallas harvest quote.
- 121 rows blocked on known-edge or promotion permission.
- 10 Dallas rows blocked by missing book data.
- 0 live-trade-permission rows.

This means the next preparation work should not be live-order work. It should be known-edge map coverage, promotion evidence, reward metadata/scoring, missing-book repair, and countable paper markout collection during the next active window.

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

The latest stable run was scored with a bounded paper command because full-corpus promotion-grade `weather.market.mm_paper` timed out after 300 seconds in this pass.

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

The diagnostic known-edge map had 217 records: 176 `harvest_only`, 38 `no_quote`, and 3 `edge_research`. This is useful for diagnosis only; it should not replace the standard full-corpus known-edge map until promotion-grade scoring is made reliable and current.

## Latest Active-Day Score

The latest bounded active-day promotion-grade score selected `data/mm_runs/2026-06-25/20260626T015448206993Z`:

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

Important caveat: the restarted daily roll began after the local active evidence window, so it is classified as `post_settlement_evaluation` and does not count toward live-forward gates.

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
3. For Dallas, collect countable active-window paper evidence for the `92-93 F` harvest quote and inspect the 10 missing-book no-quote rows.
4. Extend the new reward-score diagnostics into payout/share simulation: target-size occupancy, competitor score, score share, and reward-dollar attribution by market/band/hour.
5. Use bounded `weather.market.mm_paper --target-date ... --latest-n ...` for targeted active-window diagnostics and `--skip-fill-simulation --skip-model-variants` for full-corpus quote/reward diagnostics. Continue improving promotion-grade full-corpus fill/queue/markout scoring because the standard path still timed out after 300 seconds in this pass.
6. Do not run live-pilot. The current state remains no-go for live capital.
