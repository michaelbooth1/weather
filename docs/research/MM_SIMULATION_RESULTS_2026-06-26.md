# Market-Making Simulation And Evidence Results

Date: 2026-06-26

Scope: safe local tests, paper evidence, CLOB health checks, and one keyless shadow tick. No live orders were placed.

## Commands Run

Focused tests:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q
```

Result:

```text
89 passed, 5 subtests passed in 9.23s
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
- Latest run folder at check time: `data/mm_runs/2026-06-25/20260625T233003232942Z`.
- Latest quote rows: 132.
- Latest quote-permission rows: 0.
- Useful-work liveness blocked because all-market active-day useful-write evidence did not satisfy the SLA.

Standard paper report attempt:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper
```

Result:

- Timed out after 180 seconds in the first pass and after 300 seconds in the continuation pass.
- The timed-out `weather.market.mm_paper` processes were stopped.
- Existing `data/backtest/mm_paper_report.json` and `.md` were left unchanged.

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

Result:

```text
MM run: 0 quote rows, 12 no-quote rows, preflight BLOCK -> data/mm_runs/2026-06-26/20260626T013844852296Z
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

Source: `data/backtest/mm_paper_report.json`.

Summary:

- Candidate run folders: 30.
- Anti-overfit run count: 29.
- Quote rows: 626,069.
- Quote legs: 71,756.
- Conservative fills: 35.
- Conservative filled shares: 175.
- Queue-estimated fill legs: 13,045.
- Paper score freshness: `PASS`.
- Live-forward day count: 6.
- Exchange economics status in report: `PASS`.
- Fill evidence completeness: `BLOCK`.
- Net P&L after fees/incentives: 2.18671 USDC.
- Spread capture: 1.75 USDC.
- Adverse selection at 30 minutes: -5.3925 USDC.
- Settlement P&L: 2.5625 USDC.
- Maker fee-equivalent: 0.501057 USDC.
- Maker rebate estimate: 0.125260 USDC.
- Flattening fee estimate: 0.501057 USDC.
- Liquidity reward estimate: 0.

Interpretation:

- The bot has enough paper machinery to generate and score a large quote-intent corpus.
- Conservative fill count is still very small relative to quote legs.
- Queue simulation finds many possible fills, but promotion should continue to rely on conservative evidence until book/trade-size completeness improves.
- Reward-farming economics are not yet measured in the standard paper P&L because reward estimate remains zero.
- Negative 30-minute adverse selection means rebate/reward farming cannot be evaluated without markout controls.

## Fill Evidence Completeness

Source: `data/backtest/mm_paper_report.json`.

Current blockers:

- Missing size trade rows: 6,917.
- Missing book queue legs: 2,142.
- Missing trade-size queue legs: 26.
- Unresolved resting quote count: 0.

Required before scale:

- Restore complete trade-size evidence for scored fills.
- Restore book snapshots needed to estimate queue position.
- Keep conservative fills as the promotion gate.
- Use queue-estimated fills only as a sensitivity check until queue evidence is complete.

## Known-Edge Map

Source: `data/backtest/mm_known_edge_map.json`.

Summary:

- Record count: 238.
- Permission counts:
  - `harvest_only`: 159.
  - `no_quote`: 68.
  - `edge_research`: 11.
- Promotion market count: 11.
- Paper fill count: 35.
- CLOB recon slice count: 21,032.
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

## Future-Date 2026-06-26 Shadow Drill

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
- One-run known-edge map: 217 records, with 176 `harvest_only`, 38 `no_quote`, and 3 `edge_research`.

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
- `tests/market/test_mm_paper.py` covers latest-N selection, target-date/evidence-mode filtering, Polymarket US reward-score diagnostics, counterfactual payout/share math, skip-model-variant report disclosure, skip-fill-simulation report disclosure, and quote-blocker report disclosure.

Validation:

```powershell
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py -q
```

Result:

```text
109 passed, 5 subtests passed in 9.64s
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
- Quote rows: 4,488.
- Quote legs: 52.
- Conservative fills: 5.
- Queue-estimated fill legs: 0.
- Paper score freshness: `NO_ACTIVE_DAY`.
- Fill evidence status: `BLOCK`.
- Net P&L after fees/incentives: -0.00974 USDC.
- Liquidity reward estimate: 0.
- Bounded known-edge map: 217 records, 176 `harvest_only`, 38 `no_quote`, 3 `edge_research`.

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
- Quote rows / legs: 5,148 / 62.
- Model-variant quote rows / legs: 0 / 0.
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
- Quote rows / legs: 628,481 / 71,828.
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
- Interpretation: cached per-token timestamp indexes are still useful and covered by tests, but full-corpus promotion-grade fill/queue/markout scoring remains a runtime blocker.

Bounded latest active-day promotion-grade command:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --target-date 2026-06-25 --evidence-mode active_day_live_forward --latest-n 1 --skip-model-variants --json-out data\backtest\mm_paper_bounded_latest_active_skip_variants_20260626.json --report-out data\backtest\mm_paper_bounded_latest_active_skip_variants_20260626.md --fills-out data\backtest\mm_paper_bounded_latest_active_skip_variants_fills_20260626.csv --known-edge-out data\backtest\mm_known_edge_bounded_latest_active_skip_variants_20260626.json --known-edge-report-out data\backtest\mm_known_edge_bounded_latest_active_skip_variants_20260626.md
```

Result:

- Runtime: 2.2 seconds after quote-blocker diagnostics were added.
- Selected folder: `data/mm_runs/2026-06-25/20260626T015448206993Z`.
- Selection mode/warning: `bounded` / `diagnostic_selection_not_full_corpus`.
- Quote rows / legs: 132 / 0.
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
- Verified for target date: `2026-06-25`.
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
- The default snapshot is current for the active daily-roll date at this pass.
- A 2026-06-26 future-date drill can validate economics separately, but the default accepted snapshot was restored to the active date after the drill.
- Official US docs were rechecked again on 2026-06-26. No material fee/reward formula drift was found versus the accepted snapshot, but live API readiness remains outside the economics proof.
- The next paper report should be regenerated after current active-day paper-live-forward evidence is collected.

## Continuation Status And Platform API Recheck

Safe commands rerun during the continuation:

```powershell
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.market.market_microstructure status
.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict
.\venv\Scripts\python.exe -m pytest tests\market\test_mm_exchange.py -q
```

Results:

- Daily roll target date remained `2026-06-25`.
- Daily roll was alive with fresh post-settlement artifacts under `data/mm_runs/2026-06-25/20260626T015632370043Z`.
- Useful-work liveness remained `SKIPPED`, reason `not all-market active-day paper-live-forward evidence`.
- Latest daily-roll operator report still had 132 quote rows and 0 quote-permission rows.
- CLOB loop state was `RUNNING`.
- Strict CLOB audit was `ok: true` across 12 markets, with post-restart startup gaps ignored by policy.
- Exchange adapter/report tests passed after latency-stopgap classification, US private WebSocket fixture normalization, and stricter cancel-all proof: 15 tests.

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

Interpretation:

- The US fee/reward snapshot is still useful for paper and shadow economics.
- The snapshot is not a sufficient live-readiness artifact. Any future pilot still needs real private stream reconciliation, real cancel-all verification with zero open orders afterward, live latency-stopgap proof, account eligibility, and secret-redaction proof.

## Next Simulation Work

1. Diagnose active-date quote starvation by market, band, side, known-edge state, model variant, promotion state, and CLOB recon taxonomy.
2. Repair or explain the 10 `NO_QUOTE_MISSING_BOOK` rows and 1 `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED` row from the active-date run.
3. Run paper-live-forward only when active-date metadata, exchange economics, CLOB audit, snapshot freshness, and useful-work liveness are all passing.
4. Regenerate `mm_paper_report.json` after current active-day evidence is collected.
5. Extend reward-score diagnostics into stronger payout evidence:
   - US: calibrate competitor score/share from CLOB reward competition, not just the default `reward_competitor_q` assumption.
   - International: add Q-one/Q-two/Q-min scoring with `c = 3.0` and midpoint edge cases if the operating surface changes.
   - Reconcile predicted reward payout against actual payout artifacts before live scaling.
6. Compare reward score against adverse-selection markouts, not against resting time alone.
