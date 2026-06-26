# Codex Goal Prompt For Market-Making Reward Research

Date: 2026-06-26

Use this prompt when starting a Codex goal for the next preparation pass. It is intentionally repo-specific and evidence-heavy. It should keep the agent researching, auditing, simulating, and writing artifacts instead of jumping to live orders.

```text
Goal: prepare this repo for a small-scale market-making test whose long-term objective is farming Polymarket liquidity rewards and maker rebates without taking undocumented live risk.

Operating constraints:
- Do not place live orders.
- Do not load, request, print, or modify private keys, API keys, wallet seed material, or account credentials.
- Do not start a live pilot.
- Default all work to research, repo audit, shadow runs, paper-live-forward runs, simulations, reports, and narrowly scoped safety fixes.
- If a command could mutate exchange state, stop and document the blocker instead.
- Use current official Polymarket docs before relying on older repo assumptions. Polymarket International and Polymarket US are distinct surfaces.
- Treat all exchange, fee, reward, API, legal, and eligibility assumptions as time-sensitive. Browse and cite official sources at the start of the pass.
- Prefer evidence from this repo over generic market-making advice once local artifacts exist.

Main objective:
Get us as prepared as possible for a future small-scale market-making pilot. The core business goal is to farm liquidity rewards well, but the near-term objective is to prove that the bot can identify reward-eligible markets, quote only when the evidence supports it, avoid toxic flow, survive stale data and account failures, and produce auditable paper evidence.

Success definition for this pass:
- Produce a repo-grounded go/no-go decision for live market making, defaulting to NO-GO unless every required gate passes.
- Identify the smallest market/band/time-window candidate that could later become a min-size pilot, or explain why no candidate exists.
- Separate policy no-edge, stale/missing data, reward-score insufficiency, queue/fill uncertainty, model uncertainty, and operational live-readiness blockers.
- Leave the repo better prepared by improving only research, audit, simulation, reporting, observability, or safety code. Do not optimize for live throughput yet.
- Produce written artifacts that a future Codex goal can pick up without rediscovering the current state.

Repo context:
- Work in `C:\Users\micha\Desktop\github\weather`.
- Existing market-making docs live under `docs/research`.
- Core maker modules:
  - `src/weather/market/market_making_run.py`
  - `src/weather/market/mm_policy.py`
  - `src/weather/market/mm_risk.py`
  - `src/weather/market/mm_paper.py`
  - `src/weather/market/mm_paper_scoring.py`
  - `src/weather/market/mm_exchange.py`
  - `src/weather/market/exchange_economics.py`
  - `src/weather/market/clob_recon.py`
  - `src/weather/market/market_microstructure.py`
  - `src/weather/market/info_event_calendar.py`
- Existing docs to read first:
  - `docs/research/MARKET_MAKING_PLAN.md`
  - `docs/research/MARKET_MAKING_RESEARCH_AUDIT_2026-06-13.md`
  - `docs/research/MM_INITIAL_TEST_RUN_DESIGN.md`
  - `docs/research/MM_MODEL_READINESS_GAP_PLAN.md`
  - `docs/research/MARKET_MAKING_LIVE_RUNBOOK_2026-06-15.md`
  - `docs/research/MARKET_MAKING_PLATFORM_VERIFICATION_2026-06-16.md`
  - `docs/research/MM_REWARD_FARMING_READINESS_2026-06-26.md`
  - `docs/research/MM_REPO_AUDIT_2026-06-26.md`
  - `docs/research/MM_QUOTE_STARVATION_DIAGNOSIS_2026-06-26.md`
  - `docs/research/MM_KNOWN_EDGE_COVERAGE_2026-06-26.md`
  - `docs/research/MM_SIMULATION_RESULTS_2026-06-26.md`
  - `docs/research/MM_SMALL_SCALE_TEST_PLAN_2026-06-26.md`
- Current evidence artifacts to inspect:
  - `data/backtest/mm_paper_report.json`
  - `data/backtest/mm_paper_report.md`
  - `data/backtest/mm_known_edge_map.json`
  - `data/backtest/exchange_economics_snapshot.json`
  - `data/backtest/exchange_economics_accepted_snapshot.json`
  - `data/backtest/exchange_economics_drift_report.json`
  - `data/backtest/event_metadata_validation.json`
  - latest run folder under `data/mm_runs/<target-date>/`
  - latest CLOB loop status files under `data/snapshots`

Local operating hypothesis to verify:
- The repo currently points market-making economics at Polymarket US via `data/backtest/exchange_economics_snapshot.json`.
- Older docs and some code paths still discuss Polymarket International. Do not merge US and International rules casually.
- Treat the current weather-maker objective as liquidity-reward/rebate harvesting with strict adverse-selection controls, not directional betting.
- Treat the model as a quote veto, band selector, and research signal until positive, countable paper markouts prove stronger use.

Required research:
1. Read current official Polymarket International docs for liquidity rewards, fees, maker rebates, order lifecycle, order creation, cancel-all, market/user WebSockets, tick size, CLOB market info, and authentication.
2. Read current official Polymarket US docs for incentives/liquidity, fees, order API, authentication, WebSockets, rate limits, and market integrity.
3. Compare International versus US reward scoring and API semantics. Explicitly state which platform the local snapshot claims.
4. Pull in market-making literature only where it changes what we should audit or simulate:
   - inventory-skew/reservation-price models,
   - queue-position value,
   - adverse-selection markouts,
   - liquidity-mining incentives and rebate farming risks.
5. Capture citations in any report you write. Use links, source dates where visible, and note when a rule may have changed.

Required repo audit:
1. Run `git status --short` first. Do not revert unrelated user changes.
2. Inspect the maker modules and tests before proposing changes.
3. Verify that `mm_policy.py` remains pure and has no private-key dependency.
4. Verify that `market_making_run.py` is fail-closed on preflight and cannot emit live-trade permission outside `live-pilot`.
5. Verify that `mm_risk.py` enforces per-band, per-event, correlated-regime, daily drawdown, balance, manual pause, heartbeat, and cancel-all concepts.
6. Verify that `mm_exchange.py` builds post-only/non-taking plans and keeps signing external/injected.
7. Verify that `mm_paper.py` and `mm_paper_scoring.py` score conservative fills separately from queue-estimated fills, and that promotion does not rely only on optimistic queue simulation.
8. Verify that `exchange_economics.py` blocks stale/mismatched economics snapshots and requires rescore when material economics drift.
9. Verify that `clob_recon.py` measures reward competition, executable depth, and markouts rather than assuming rewards are free.

Required artifact interrogation:
1. Identify the current target date from `weather.operations.market_making_daily_roll status`, not from wall-clock intuition alone.
2. Inspect the latest run folder under `data/mm_runs/<target-date>/` and read at least:
   - `run_summary.json`
   - `preflight.json`
   - `quote_intents_long.csv`
   - any lifecycle, budget, useful-work, reward, or report artifacts present in that folder.
3. Break quote results down by market, band, side, action, emitted reason, known-edge permission, known-edge reason, promotion state, event gate, book freshness, CLOB token id, expected reward score, quote risk, and live-trade permission.
4. For no-quote rows, classify them into:
   - expected policy abstention,
   - missing known-edge coverage,
   - promotion block,
   - missing or stale CLOB book,
   - snapshot/source/cadence problem,
   - information-event quote-pull gate,
   - reward metadata or economics problem,
   - risk/budget suppression.
5. For quote rows, inspect bid, ask, size, risk, reward score, rebate value, book spread, book depth, event gate, known-edge state, and whether the row counts toward live-forward evidence.
6. Read `data/backtest/mm_known_edge_map.json` and compare its cells against the latest quote tape. Missing cells should not be silently treated as edge.
7. Read `data/backtest/mm_paper_report.json` and decide whether it covers the current active-day evidence. If it does not, say so explicitly.
8. If full `weather.market.mm_paper` is too slow, run a bounded one-run score with `--run-folder` and document that the result is diagnostic, not a replacement for full-corpus scoring.
9. Inspect exchange-economics drift and event-metadata validation before interpreting reward or fee numbers.
10. Check for stale runtime identities in supervisor statuses before trusting loop liveness.

Required commands:
1. Run focused market-making tests:
   `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q`
2. Run CLOB status:
   `.\venv\Scripts\python.exe -m weather.market.market_microstructure status`
3. Run strict CLOB audit:
   `.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict`
4. Run maker daily-roll status:
   `.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status`
5. Run one keyless shadow tick for the current target date:
   `.\venv\Scripts\python.exe -m weather.market.market_making_run --date YYYY-MM-DD --budget-usdc 500 --mode shadow --markets all --once`
6. Do not run `live-pilot` or any command that can place/cancel real orders unless the user explicitly authorizes it in a later turn and all live gates pass.

Optional safe commands when useful:
- Refresh same-day location/event metadata only through the existing safe path:
  `.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json`
- Validate event metadata for the target date:
  `.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date YYYY-MM-DD --markets all`
- Publish and accept exchange economics only when official docs have been rechecked and the target date/platform are explicit:
  `.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date YYYY-MM-DD --platform polymarket_us --accept`
- Run a one-run diagnostic paper score when full scoring is too slow:
  `.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\YYYY-MM-DD\RUN_FOLDER --json-out data\backtest\mm_paper_<label>.json --report-out data\backtest\mm_paper_<label>.md --fills-out data\backtest\mm_paper_<label>_fills.csv --known-edge-out data\backtest\mm_known_edge_<label>.json --known-edge-report-out data\backtest\mm_known_edge_<label>.md`
- Run a bounded diagnostic paper score without overwriting the standard report:
  `.\venv\Scripts\python.exe -m weather.market.mm_paper --target-date YYYY-MM-DD --evidence-mode post_settlement_evaluation --latest-n 1 --json-out data\backtest\mm_paper_bounded_<label>.json --report-out data\backtest\mm_paper_bounded_<label>.md --fills-out data\backtest\mm_paper_bounded_<label>_fills.csv --known-edge-out data\backtest\mm_known_edge_bounded_<label>.json --known-edge-report-out data\backtest\mm_known_edge_bounded_<label>.md`
- For faster operational reward/readiness diagnostics, add `--skip-model-variants` to the bounded paper-score command. Treat the resulting report as diagnostic only; it cannot support model-variant promotion.
- For full-corpus quote/no-quote and reward-score diagnostics when fill simulation is too slow, use `--skip-fill-simulation --skip-model-variants` with separate output filenames. Treat the resulting report and known-edge map as summary-only diagnostics; they cannot support fill evidence, P&L, known-edge promotion, or model-variant promotion.
- Re-run the focused test set after any code change:
  `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\operations\test_runtime_identity.py -q`

Required simulations and analyses:
1. Reward-score simulation:
   - Compute score by side under the active platform formula.
   - Include target-size qualification, discount factor, ticks from best price, order size, expected competition, and zero-score cases.
   - Report reward score separately from expected reward dollars when the reward pool or pro-rata share is uncertain.
2. Rebate and fee simulation:
   - Compare maker rebate value against expected flattening/taker fees and adverse-selection markouts.
   - Treat rebates as paid only on executed maker flow, not on resting quotes.
3. Queue and fill simulation:
   - Keep conservative fills separate from queue-estimated fills.
   - Do not promote based on queue estimates while trade-size or book evidence is incomplete.
4. Adverse-selection simulation:
   - Measure markouts around observation windows, METAR/source-update windows, and high-information event gates.
   - Identify whether a reward-positive quote is still negative after 5m/30m/settlement markouts.
5. Inventory/risk simulation:
   - Stress one-sided fills, correlated weather-city exposure, near-binary markets, stale books, and forced flattening.
   - Check per-band, per-event, day-level, and correlated-regime caps.
6. Model-use simulation:
   - Compare current model fair probabilities, market mids, known-edge map state, and promotion state.
   - Decide whether the model should quote, harvest only, veto, or only collect shadow evidence for each cell.
7. Operational-failure simulation:
   - Verify fail-closed behavior for stale snapshots, stale WU/source rows, stale CLOB books, stale event metadata, stale economics, runtime drift, heartbeat loss, user-stream failure, and cancel-all failure.

Known current state from the 2026-06-26 preparation pass:
- Focused maker tests passed after the latest paper-scoring changes: 100 tests plus 5 subtests.
- CLOB strict audit passed for 12 markets at the time checked.
- Runtime/snapshot guard tests passed after fixing `snapshot_store.py` to compare scoped process identity using `current_identity_for(process_identity)`.
- Maker useful-work runtime identity now also compares loop statuses against their recorded scoped identity, and `current_identity_for(recorded)` honors `recorded["repo_root"]`. Regression tests passed.
- Active daily-roll target at the time checked was `2026-06-25`.
- Active-date event metadata validation passed for `2026-06-25`.
- Active-date Polymarket US exchange economics passed and accepted snapshot `xecon-036874d19e56c76f`; `data/backtest/exchange_economics_drift.json` passed with no rescore required.
- Official Polymarket US docs were rechecked again on 2026-06-26. The accepted economics snapshot still matches the core US fee/reward assumptions, but economics proof is not live API proof: US order entry uses `participateDontInitiate`, cancel-all requires zero-open-order confirmation, private WebSocket order reconciliation is mandatory for final state, and 5-second latency-stopgap rejects need explicit handling before live-pilot scale. The adapter now classifies documented US latency-stopgap order rejects as no-acceptance stale-price protection requiring book refresh/recompute, and treats the same response on pure cancels as a live-readiness blocker.
- Polymarket US private WebSocket order-update fixtures now normalize into lifecycle/fill rows for offline reconciliation tests. This covers partial/full fills, cancels, rejects, expirations, and replacements, but does not prove real private-stream connectivity.
- MM-2 cancel-all probe status now requires structured evidence of a cancel-all request plus zero open orders afterward. A generic canceled user-stream event does not prove cancel-all readiness.
- The live-pilot platform-verification gate now requires `mm_platform_verification_v0.2`; v0.1 or boolean-only artifacts should fail closed until they include maker-only order field proof, private-stream lifecycle/fill/final-state reconciliation, cancel-all zero-open-order proof, and US latency-stopgap proof.
- Current standard paper report has 626,069 quote rows, 71,756 quote legs, 35 conservative fills, 13,045 queue-estimated fill legs, 6 live-forward days, and net paper P&L after fees/incentives of about 2.19 USDC.
- Paper scoring freshness is PASS, but fill evidence completeness is BLOCK because trade-size and queue/book evidence is incomplete.
- Known edge map has 238 cells: 159 harvest_only, 68 no_quote, 11 edge_research.
- Model variant bakeoff is PASS as an experiment but promotion remains BLOCK.
- Latest active-date safe shadow tick for 2026-06-25 emitted 132 no-quote rows, 0 quote permissions, and 0 live-trade permissions with preflight PASS. First failing gate was `policy`; root cause class was `policy_no_edge`; reason counts were `NO_QUOTE_KNOWN_EDGE_PERMISSION = 121`, `NO_QUOTE_MISSING_BOOK = 10`, and `NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED = 1`.
- Latest stable post-settlement one-shot after supervisor restart was `data/mm_runs/2026-06-25/20260626T020148684548Z`: preflight PASS, 1 quote-permission row, 0 live permissions, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 10 `NO_QUOTE_MISSING_BOOK`, and 1 `QUOTE_HARVEST_MID` Dallas `92-93 F` harvest quote with expected reward score 1.0. Useful-work liveness was SKIPPED because it was post-settlement evidence.
- Known-edge coverage diagnosis is in `docs/research/MM_KNOWN_EDGE_COVERAGE_2026-06-26.md`: missing known-edge records cover Atlanta, Austin, Denver, Houston, and Toronto; promotion blocks cover Chicago, Los Angeles, Miami, NYC, San Francisco, and Seattle; Dallas has one quoted band and ten missing-book bands.
- A one-run `mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z` diagnostic completed in 4.4 seconds, but full-corpus promotion-grade `weather.market.mm_paper` timed out after 300 seconds. Full fill/queue/markout scoring needs bounded, cached, or incremental mode before it can be relied on operationally.
- Bounded `mm_paper` selection now supports `--target-date` / `--run-target-date`, `--evidence-mode`, and `--latest-n`. Bounded reports record `diagnostic_selection_not_full_corpus` so they are not mistaken for full-corpus promotion evidence.
- Bounded smoke run `data/backtest/mm_paper_bounded_latest_postsettlement_20260626.json` selected `data/mm_runs/2026-06-25/20260626T015632370043Z`: 4,488 quote rows, 52 quote legs, 5 conservative fills, 0 queue-estimated fill legs, paper score freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, net P&L after fees/incentives -0.00974 USDC, reward estimate 0.
- Reward-score diagnostics now separate Polymarket US score/share from reward-dollar P&L. The same bounded smoke report had 26 quote-permission rows, 52 positive-score legs, total reward score 141.7, score/target-size 0.01417, counterfactual reward 586.263964 USDC under campaign-pool 1000 and competitor-score 100 assumptions, and no actual payout evidence.
- A skip-model-variants bounded smoke report wrote `data/backtest/mm_paper_bounded_latest_postsettlement_skip_variants_20260626.json` in 3.9 seconds at smoke-check time. It selected the same growing post-settlement run, reported 5,148 quote rows, 62 quote legs, 7 conservative fills, model-variant scoring `SKIPPED (skip_model_variants)`, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, net P&L after fees/incentives -0.013636 USDC, reward score 168.95, and no actual reward payout evidence.
- A full-corpus summary-only report wrote `data/backtest/mm_paper_full_summary_only_20260626.json` in about 176 seconds with 36 included run folders, 628,481 quote rows, 71,828 quote legs, 35,914 quote-permission rows, reward score 165,800.676275, counterfactual reward 999.39723 USDC, paper freshness `PASS`, fill evidence `SKIPPED`, and model-variant scoring `SKIPPED`.
- `mm_paper_scoring.py` caches per-token timestamp indexes for trade, book, and mark rows, but full-corpus promotion-grade scoring with `--skip-model-variants` still timed out after 300 seconds and wrote no outputs.
- Bounded latest active-day promotion-grade scoring wrote `data/backtest/mm_paper_bounded_latest_active_skip_variants_20260626.json` in 2.2 seconds after quote-blocker diagnostics were added. It selected `data/mm_runs/2026-06-25/20260626T015448206993Z`, found 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, reward score 0, freshness `PASS`, and fill evidence `PASS` only because no quotes existed.
- Quote-blocker diagnostics now show the active-day blockers overlap: 132 event-gate suppressed rows, 121 known-edge permission-blocked rows, 132 known-edge state rows, 132 known-edge allowed=false rows, 11 harvest-only rows suppressed by the event gate, top event-gate state `PULL/suppress/INFO_EVENT_METAR_PRINT`, and top known-edge states 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, 11 `awaiting_paper_markouts/harvest_only/SHADOW`.
- Current daily roll was restarted after stale-code detection and is now post-settlement, so it should not be treated as countable live-forward evidence.
- Latest 2026-06-26 future-date shadow drill emitted 12 no-quote rows, 0 quote permissions, and 0 live-trade permissions. Event metadata/economics passed during the drill, but preflight blocked because June 26 snapshot/model rows, source-status rows, CLOB token rows, CLOB books/features, and reward metadata were missing while active loops were still on June 25.
- Current blockers: mostly quote starvation under clean active-day preflight, zero quote permissions in the latest countable active-day run, known-edge missing records, promotion blocks, Dallas missing-book rows in post-settlement diagnostics, lack of countable active-window evidence for the one Dallas harvest quote, fill evidence completeness BLOCK in standard promotion-grade scoring, reward estimate still 0, model/policy promotion BLOCK, absent live-account/platform evidence, absent real private WebSocket reconciliation proof, absent real cancel-all zero-open-order confirmation, and absent live US latency-stopgap handling evidence.

Research questions to answer:
1. Which reward formula applies to our likely operating surface today: Polymarket International or Polymarket US?
2. For the current target date, which weather/climate events have active rewards, min size, target size, tick size, spread threshold, and fee/rebate eligibility?
3. What quote shape maximizes reward score without increasing adverse selection beyond observed paper markouts?
4. Which bands should be harvest-only, no-quote, or edge-research according to `mm_known_edge_map.json`, promotion state, CLOB recon, and source freshness?
5. What minimum paper evidence is required before any one-market, one-band, min-size live pilot?
6. Where does the current model help the bot, and where should it only veto quoting?
7. What operational failures would create real loss: stale books, stale WU/source rows, stale event metadata, wrong platform rules, runtime drift, user stream failure, heartbeat failure, cancel-all failure, or fill reconciliation mismatch?
8. What simulations are missing before pilot: queue fill realism, target-size reward share, adverse-selection markouts around observation windows, platform fee/rebate reconciliation, and full-day budget pressure?

Decision gates:
- PASS only when the artifact or command proves the gate with current target-date evidence.
- WARN when evidence is useful but stale, partial, post-settlement, queue-estimated, or diagnostic-only.
- BLOCK when evidence is missing, stale, internally inconsistent, not countable live-forward evidence, or requires credentials/live exchange mutation.
- Any one of these remains a live NO-GO: missing active-date preflight, missing strict CLOB audit, stale economics, stale event metadata, no quote-permission rows, only post-settlement quote evidence, fill evidence completeness BLOCK, reward estimate not measured, promotion BLOCK, missing user-stream/cancel-all verification, or absent platform/account eligibility proof.

Deliverables:
1. Update or create a dated readiness report under `docs/research`.
2. Update or create a dated repo audit under `docs/research`.
3. Update or create a dated simulation report under `docs/research`.
4. Update or create a small-scale test plan under `docs/research`.
5. If code changes are needed, keep them focused on safety, observability, or simulation correctness. Add or update tests for any code change.
6. End with a concise list of current PASS/WARN/BLOCK gates and the next three safest actions.
```

## Source Links To Re-check Each Pass

- Polymarket International liquidity rewards: <https://docs.polymarket.com/market-makers/liquidity-rewards>
- Polymarket International fees: <https://docs.polymarket.com/trading/fees>
- Polymarket International maker rebates: <https://docs.polymarket.com/market-makers/maker-rebates>
- Polymarket International order creation: <https://docs.polymarket.com/api-reference/trade/post-a-new-order>
- Polymarket International cancel-all: <https://docs.polymarket.com/api-reference/trade/cancel-all-orders>
- Polymarket International user WebSocket: <https://docs.polymarket.com/api-reference/wss/user>
- Polymarket US liquidity incentives: <https://docs.polymarket.us/incentives/liquidity>
- Polymarket US fee schedule: <https://docs.polymarket.us/fees>
- Polymarket US order API overview: <https://docs.polymarket.us/api-reference/orders/overview>
- Polymarket US authentication: <https://docs.polymarket.us/api-reference/authentication>
- Polymarket US market integrity: <https://integrity.polymarket.us/>
- Avellaneda and Stoikov, inventory-risk market making: <https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf>
- Gueant, Lehalle, and Fernandez-Tapia, inventory-constrained quoting: <https://arxiv.org/abs/1105.3115>
- Moallemi et al., queue position value: <https://moallemi.com/ciamac/papers/queue-value-2016.pdf>
- Hummingbot liquidity mining whitepaper: <https://hummingbot.org/liquidity-mining.pdf>
