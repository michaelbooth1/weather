# Market-Making Reward Farming Readiness

Date: 2026-06-26

Status: research and shadow/paper preparation only. This report does not authorize live orders.

## Executive Verdict

The repo is not ready for live reward farming today. It is ready for continued research, quote-starvation diagnosis, targeted data-quality repair, shadow ticks, and paper-live-forward evidence collection after active-day gates are passing.

The important positive finding is that the bot is failing closed. The first 2026-06-26 shadow drill blocked on missing current target-date data. After refreshing active-date metadata and exchange economics for the prior active daily-roll date (`2026-06-25`), the active-date shadow tick reached `preflight_status = PASS` but wrote 0 live-trade-permission rows. After runtime/liveness fixes and supervisor restarts, a stable post-settlement drill emitted only 1 non-countable paper quote and still wrote 0 live-trade-permission rows. An early June 26 shadow tick had current CLOB, event metadata, and exchange economics, but still wrote 0 quote-permission rows because 11 markets failed model freshness and Toronto lacked known-edge permission. After the snapshot/model loop caught up, the next June 26 shadow tick passed preflight and emitted 9 Dallas harvest-only quote permissions, still with 0 live-trade-permission rows. The active daily roll has now been restarted in `paper-live-forward` mode for June 26 and is countable active-day evidence, but the current bounded score has 396 quote rows, 0 quote legs, 0 live-trade-permission rows, and 396 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows during METAR pull windows. That is useful readiness progress, but it is still not live-ready.

Current live-pilot blockers:

- Stable post-settlement quote permission is minimal: run `data/mm_runs/2026-06-25/20260626T020148684548Z` had 132 intent rows, 1 quote-permission row, and 0 live-trade-permission rows.
- Latest current-date June 26 shadow run `data/mm_runs/2026-06-26/20260626T134201734227Z` had 132 intent rows, 9 quote-permission rows, 123 no-quote rows, and 0 live-trade-permission rows.
- June 26 blocker split after model freshness recovered: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, 2 `NO_QUOTE_DISAGREEMENT_SHADOW` rows, and 9 Dallas `QUOTE_HARVEST_MID` rows.
- Bounded scoring for that latest June 26 shadow run found 18 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 12.26505, counterfactual reward 109.2508 USDC, fill evidence `BLOCK`, 784 missing-size trade rows, and 18 unresolved resting quotes because settlement was not available for the active day.
- Current countable daily-roll run `data/mm_runs/2026-06-26/20260626T135556165467Z` is active-day `paper-live-forward`, has useful-work liveness `PASS`, and counts toward paper live-forward evidence, but the bounded score has 396 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 0, 396 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 396 event-gate suppressed rows.
- Reason counts on the latest stable post-settlement drill were `NO_QUOTE_KNOWN_EDGE_PERMISSION = 121`, `NO_QUOTE_MISSING_BOOK = 10`, and `QUOTE_HARVEST_MID = 1`.
- Missing known-edge records, promotion blocks, Dallas missing-book rows, and awaiting active-window paper markouts explain why this is not live-ready.
- The regenerated full-corpus standard paper report has `fill_evidence_completeness.status = BLOCK`.
- Full-corpus standard model-variant scoring now completes on current artifacts, but the result is still not promotion-grade.
- Model variant promotion remains `BLOCK`; the latest full-corpus standard paper run measured it directly instead of skipping it.
- No live account/platform verification, user-stream, cancel-all, paid reward/rebate, isolated-wallet, or settlement-P&L evidence exists for a live pilot.
- The platform-verification live gate now requires `mm_platform_verification_v0.2`; older v0.1 or boolean-only artifacts fail closed until refreshed with maker-only, private-stream, cancel-all zero-open-order, and US latency-stopgap proofs.

Current active-date repairs already completed:

- `data/backtest/event_metadata_validation.json` is `PASS` for target date `2026-06-26`.
- `data/backtest/exchange_economics_snapshot.json` is verified for `2026-06-26`, platform `polymarket_us`, snapshot id `xecon-036874d19e56c76f`, source hash `85aa79fefa832f611d43ca6aa47b7197`.
- `data/backtest/exchange_economics_drift.json` is `PASS` with `rescore_required = false`.
- Focused runtime/snapshot tests passed after a scoped runtime-identity guard fix in `snapshot_store.py`.
- Maker useful-work runtime identity now uses scoped supervisor identities; focused regression tests passed.
- Snapshot, CLOB, and observation-trigger supervisors were restarted or ensured after stale-code detection. The daily roll later reported `pid_missing` / `blocked_restart_required`, then was explicitly restarted for `2026-06-26` in `paper-live-forward` mode during the active evidence window. Its status is now `started`, `pid_alive = true`, useful-work liveness `PASS`, and `counts_toward_live_forward_gate = true`.

## Current Official Mechanics

Polymarket International and Polymarket US currently have different incentive and API surfaces. The local `exchange_economics_snapshot.json` claims `platform = polymarket_us` and `platform_surface = retail_api_and_exchange_clob`, so US rules must be treated as primary until the operating account/platform is reverified.

International rules checked on 2026-06-26:

- Liquidity rewards are based on resting limit orders, participation, two-sided depth, and tightness versus a size-cutoff-adjusted midpoint. The International formula uses `c = 3.0`, permits reduced single-sided credit when midpoint is between 0.10 and 0.90, and requires double-sided liquidity outside that range. Source: <https://docs.polymarket.com/market-makers/liquidity-rewards>.
- International weather fees use `fee = C * feeRate * p * (1 - p)`, weather taker fee rate `0.05`, maker fee `0`, and maker rebate `25%`. Source: <https://docs.polymarket.com/trading/fees>.
- Maker rebates on International are fee-curve weighted and paid against executed maker flow, not mere resting presence. Source: <https://docs.polymarket.com/market-makers/maker-rebates>.
- Global CLOB order creation supports `postOnly`, only for GTC/GTD orders, and returns states such as `live`, `matched`, or `delayed`. Source: <https://docs.polymarket.com/api-reference/trade/post-a-new-order>.
- Global cancel-all exists and works in cancel-only mode. Source: <https://docs.polymarket.com/api-reference/trade/cancel-all-orders>.
- The user WebSocket carries order and trade events and should be required for fill lifecycle reconciliation. Source: <https://docs.polymarket.com/api-reference/wss/user>.

US rules checked on 2026-06-26:

- US liquidity incentives for Climate, Macro, Politics, and Culture are listed as $1,000/day per event, pro-rated across markets, with default eligibility and a scoring formula of `Discount Factor ^ ticks_from_best_price * Order Size`. Climate shows discount factor `0.30` and target size `10,000`. Source: <https://docs.polymarket.us/incentives/liquidity>.
- US fees are effective exchange-wide from 3pm ET on 2026-04-03. The fee formula is `Theta * C * p * (1 - p)`, taker theta is `0.05`, and maker rebate theta is `-0.0125`, i.e. 25% of taker fees. Source: <https://docs.polymarket.us/fees>.
- US authenticated endpoints require API keys, app/KYC setup, and raw requests use `X-PM-Access-Key`, `X-PM-Timestamp`, and `X-PM-Signature` with timestamps within 30 seconds of server time. Source: <https://docs.polymarket.us/api-reference/authentication>.
- US Orders API base URL is `https://api.polymarket.us`; all order endpoints require auth; batched operations support up to 20 orders; global rate limit is 20 requests/second per API key; best practice is preview before submit and WebSocket/order polling after submit. Source: <https://docs.polymarket.us/api-reference/orders/overview>.
- US create-order examples include `participateDontInitiate: true`, matching the repo's US maker-only request plan. Source: <https://docs.polymarket.us/api-reference/orders/create-order>.
- US cancel-all uses `POST /v1/orders/open/cancel`, optionally filtered by market slug. The endpoint can return canceled order IDs, but the Orders API overview warns that batched responses do not certify per-entry success; private WebSocket order updates are still required for final state. Sources: <https://docs.polymarket.us/api-reference/orders/cancel-all-open-orders> and <https://docs.polymarket.us/api-reference/orders/overview>.
- US WebSocket docs expose `/v1/ws/private` for order, position, and balance updates and `/v1/ws/markets` for market data. The private stream has order snapshots and order execution updates, so it should be treated as mandatory live-reconciliation evidence. Sources: <https://docs.polymarket.us/api-reference/websocket/overview> and <https://docs.polymarket.us/api-reference/websocket/private>.
- US rate-limit docs list 20 requests/second per API key, recommend WebSockets instead of polling, and describe a 5-second latency stopgap that can reject new orders or cancel-replaces while pure cancels remain unaffected. Source: <https://docs.polymarket.us/api-reference/rate-limits>.
- Polymarket US market-integrity rules permit a weather forecast model built from public data, but prohibit manipulation including spoofing, wash trading, fictitious transactions, self-dealing, front-running, information misuse, attempted manipulation, and disruptive practices. Source: <https://integrity.polymarket.us/>.

Snapshot comparison after the 2026-06-26 recheck:

- `data/backtest/exchange_economics_accepted_snapshot.json` matches the core US fee/reward assumptions rechecked here: platform `polymarket_us`, fee theta `0.05`, maker rebate theta-equivalent `0.0125`, Climate liquidity discount factor `0.30`, and target size `10,000`.
- The accepted snapshot's `source_checked_at_utc` is now `2026-06-26T13:25:00+00:00` after the continuation recheck and publish/accept for target date `2026-06-26`.
- The economics snapshot does not and should not by itself prove live API readiness. The new exchange diagnostics in `mm_exchange.py` now separately disclose US private-stream, cancel-all confirmation, latency-stopgap handling, API-key eligibility, and secret-redaction requirements.
- The live-pilot `platform_verification_gate` now enforces those API-readiness requirements through `mm_platform_verification_v0.2`, including `participateDontInitiate` for US, private-stream final-state reconciliation, cancel-all zero-open-order proof, and US latency-stopgap handling proof.

## Local Evidence Snapshot

Commands run in this pass:

- `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q`
  - Result: 89 passed, 5 subtests passed.
- `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py -q`
  - Result after the latest shadow-score/doc refresh: 111 passed, 5 subtests passed.
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_runtime_identity.py tests\collection\test_loop_supervisor.py tests\collection\test_collection_robustness.py -q`
  - Result: 44 passed.
- `.\venv\Scripts\python.exe -m weather.market.market_microstructure status`
  - Result at check time: CLOB state `RUNNING`, discovery sanity `PASS`, no error markets, fresh heartbeats.
- `.\venv\Scripts\python.exe -m weather.market.market_microstructure audit --strict`
  - Result: `ok: true`, all 12 markets ok, 0 gaps over threshold.
- `.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status`
  - Result: process alive and artifacts current, but operator report useful-work liveness `BLOCK` on all-market active-day useful-write SLA.
- `.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json`
  - Result: 51 locations, 119 events.
- `.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-25 --markets all`
  - Result: `PASS`.
- `.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-25 --platform polymarket_us --accept`
  - Result: `PASS`; accepted snapshot `xecon-036874d19e56c76f`.
- `.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --force`
  - Initial result: `stale_code` from a scoped runtime identity mismatch.
  - After the `snapshot_store.py` guard fix, the forced active-date snapshot wrote successfully.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-25 --budget-usdc 500 --mode shadow --markets all --once`
  - Result: run `data/mm_runs/2026-06-25/20260626T014113607834Z`, 132 no-quote rows, 0 quote-permission rows, preflight `PASS`.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once`
  - Result after target-date validation/economics: run `data/mm_runs/2026-06-26/20260626T013844852296Z`, 12 no-quote rows, 0 quote-permission rows, preflight `BLOCK` because the June 26 snapshot/CLOB folders were not present while active loops were still on June 25.
- `.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation --target-date 2026-06-26 --markets all`
  - Result: `PASS`.
- `.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-26 --platform polymarket_us --accept`
  - Result: `PASS`; accepted snapshot `xecon-036874d19e56c76f`, source hash `85aa79fefa832f611d43ca6aa47b7197`.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once`
  - Result: run `data/mm_runs/2026-06-26/20260626T132648384687Z`, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, preflight `WARN`, first failing gate `model_freshness`.
- `.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T132648384687Z --skip-model-variants ...`
  - Result: `data/backtest/mm_paper_shadow_20260626T132648384687Z_20260626.json`, 132 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS` for target date `2026-06-26`, reward score 0, fill evidence `PASS` only because there were no quoted legs.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode shadow --markets all --once`
  - Result after snapshot/model freshness recovered: run `data/mm_runs/2026-06-26/20260626T134201734227Z`, preflight `PASS`, 9 quote-permission rows, 123 no-quote rows, 0 live-trade-permission rows, 18 paper-posted lifecycle legs, and 15.3055 USDC reserved shadow risk.
- `.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T134201734227Z --skip-model-variants ...`
  - Result: `data/backtest/mm_paper_shadow_20260626T134201734227Z_20260626.json`, 132 quote rows, 18 quote legs, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS` for target date `2026-06-26`, reward score 12.26505, counterfactual reward 109.2508 USDC, paper freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, 784 missing-size trade rows, and 18 unresolved resting quotes.
- `.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --restart`
  - Result: stopped stale snapshot PID 21224 and started a new current-code snapshot loop.
- `.\venv\Scripts\python.exe -m weather.operations.observation_trigger restart`
  - Result: restarted observation trigger; follow-up status showed no blocked snapshot triggers.
- `.\venv\Scripts\python.exe -m weather.market.market_making_run --date 2026-06-26 --budget-usdc 500 --mode paper-live-forward --markets all --once`
  - Result: run `data/mm_runs/2026-06-26/20260626T135512615163Z`, active-day `paper-live-forward`, 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, preflight `WARN` because Seattle model freshness was stale and all rows were in a METAR pull window.
- `.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll start --date 2026-06-26 --budget-usdc 500 --mode paper-live-forward --markets all --force`
  - Result: daily roll started at `2026-06-26T13:55:56Z`, PID 38032, evidence mode `active_day_live_forward`, useful-work liveness `PASS`, and `counts_toward_live_forward_gate = true`.
- `.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-26\20260626T135556165467Z --skip-model-variants ...`
  - Result: `data/backtest/mm_paper_daily_roll_20260626T135556165467Z_20260626.json`, 396 quote rows, 0 quote legs, 0 conservative fills, 0 queue-estimated fill legs, exchange economics `PASS` for target date `2026-06-26`, paper freshness `PASS`, fill evidence `PASS` only because no quoted legs existed, live-forward paper days 1 in the bounded selection, reward score 0, and 396 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows.

Paper report summary from `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`:

- Quote rows: 636,005.
- Quote legs: 71,836.
- Conservative fills: 44.
- Queue-estimated fill legs: 13,045.
- Paper score freshness: `PASS`.
- Live-forward paper days: 2.
- Locked policy params: false.
- Fill evidence completeness: `BLOCK`.
- Fill evidence blockers: 8,893 missing-size trade rows, 2,182 missing-book queue legs, 26 missing-trade-size queue legs, and 0 unresolved resting quotes.
- Top missing-size events: Dallas June 25 (1,976), Denver June 23 (1,562), Denver June 21 (1,518), Austin June 23 (1,391), Atlanta June 21 (1,322), and Houston June 21 (1,124).
- Top missing-book slices are early-hour `YES_ASK` rows, led by Los Angeles `70-71 F` at `02:00Z` (37/37 legs missing book), Houston `88-89 F` at `02:00Z` (36/36), and Dallas `92-93 F` at `02:00Z` (36/36).
- Net paper P&L after fees/incentives: 2.641678 USDC.
- 30-minute adverse-selection P&L: -5.4025 USDC.
- Settlement P&L: 3.035 USDC.
- Liquidity reward estimate: 0.
- Model variant bakeoff status: `PASS`.
- Model variant promotion: `BLOCK`.

Known-edge map summary from `data/backtest/mm_known_edge_full_standard_model_variants_release_quotes_20260626.json`:

- Record count: 238.
- Permission counts: 158 `harvest_only`, 68 `no_quote`, 12 `edge_research`.
- Promotion market count: 11.
- Paper fill count: 44.
- CLOB recon slice count: 21,560.
- CLOB overlay explicitly blocks `market_lead` and `book_liquidity_artifact`; no overlay taxonomies are allowed.

Latest stable no-live drill:

- Mode: `paper-live-forward`.
- Evidence mode: `post_settlement_evaluation`.
- Target date: `2026-06-25`.
- Run folder: `data/mm_runs/2026-06-25/20260626T020148684548Z`.
- Preflight status: `PASS`.
- Row count: 132.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Root cause class: `trading_permissions_emitted`.
- Exchange economics status: `PASS`.
- Counts toward live-forward gate: false, because this was post-settlement evidence.
- Useful-work liveness: `SKIPPED`, because this was post-settlement evidence.
- Reason counts:
  - `NO_QUOTE_KNOWN_EDGE_PERMISSION = 121`.
  - `NO_QUOTE_MISSING_BOOK = 10`.
  - `QUOTE_HARVEST_MID = 1`.
- Quoted row: Dallas `92-93 F`, two-sided harvest quote, 5 contracts per side, 4.9525 USDC quote risk, expected reward score 1.0, live-trade permission false.

One-run diagnostic paper score for the latest stable drill:

- Command: `.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z --json-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.json --report-out data\backtest\mm_paper_quote_starvation_20260626T020148684548Z.md --fills-out data\backtest\mm_paper_quote_starvation_fills_20260626T020148684548Z.csv --known-edge-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.json --known-edge-report-out data\backtest\mm_known_edge_quote_starvation_20260626T020148684548Z.md`.
- Result: 132 quote rows, 2 quote legs, 0 conservative fills, 0 queue-estimated fill legs, gate `OPEN`, paper score freshness `NO_ACTIVE_DAY`, fill evidence status `BLOCK`, and 0 P&L/reward/rebate estimates.
- Diagnostic known-edge map: 217 records, with 176 `harvest_only`, 38 `no_quote`, and 3 `edge_research`.
- Interpretation: useful for quote-starvation diagnosis, but not live-forward evidence and not a replacement for promotion-grade full-corpus paper scoring.

Bounded paper-score mode added in this pass:

- `weather.market.mm_paper` now accepts `--target-date` / `--run-target-date`, `--evidence-mode`, and `--latest-n`.
- Reports include `Run-folder selection` and `Selection warning`, with bounded reports marked `diagnostic_selection_not_full_corpus`.
- Smoke command selected `data/mm_runs/2026-06-25/20260626T015632370043Z` and wrote `data/backtest/mm_paper_bounded_latest_postsettlement_20260626.json`.
- Smoke result: 4,488 quote rows, 52 quote legs, 5 conservative fills, 0 queue-estimated fill legs, paper score freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, net P&L after fees/incentives -0.00974 USDC, reward estimate 0.
- Reward-score diagnostics: Polymarket US basis `discount_factor ** ticks_from_best_price * order_size`, 26 quote-permission rows, 52 positive-score legs, total reward score 141.7, score/target-size 0.01417, counterfactual score share 0.58626396, counterfactual reward 586.263964 USDC under campaign-pool 1000 and competitor-score 100 assumptions, 0 unscored quoted legs, and no actual payout evidence.
- `--skip-model-variants` is now available for faster operational diagnostics. The skip-variant smoke report wrote `data/backtest/mm_paper_bounded_latest_postsettlement_skip_variants_20260626.json`, selected the same growing post-settlement run, and completed in 3.9 seconds with 5,148 quote rows, 62 quote legs, 7 conservative fills, model-variant scoring `SKIPPED (skip_model_variants)`, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, net P&L after fees/incentives -0.013636 USDC, reward score 168.95, and counterfactual reward 628.183677 USDC.
- `--skip-fill-simulation` is now available for full-corpus quote/reward diagnostics when conservative fill simulation is too slow. The full summary-only report wrote `data/backtest/mm_paper_full_summary_only_20260626.json` and completed in about 176 seconds with 36 included run folders, 628,481 quote rows, 71,828 quote legs, 35,914 quote-permission rows, reward score 165,800.676275, counterfactual reward 999.39723 USDC, paper freshness `PASS`, fill evidence `SKIPPED`, and model-variant scoring `SKIPPED`.
- `mm_paper_scoring.py` now caches per-token timestamp indexes, streams the large disagreement casebook instead of loading the full payload, drops full quote-row references from quote legs after reward estimates are attached, and releases the full quote-row corpus before fill simulation. After those changes, the full-corpus standard model-variant run wrote `data/backtest/mm_paper_full_standard_model_variants_release_quotes_20260626.json`: 636,005 quote rows, 71,836 quote legs, 44 conservative fills, 13,045 queue-estimated fill legs, paper freshness `PASS`, fill evidence `BLOCK`, reward score 165,822.476275, counterfactual reward 999.397309 USDC, model-variant scoring `PASS`, and model-variant promotion `BLOCK`.
- The regenerated standard report now includes fill-evidence blocker tables. The actionable gaps are missing trade sizes in six high-volume resolved events and missing book snapshots in early-hour `YES_ASK` slices; these are data-quality blockers, not permission to use queue-estimated fills as promotion evidence.
- Model-variant promotion blockers in that run: only one independent target day for the broad 12-market policy pairs, insufficient clusters/markets for the one-market policy pair, and no positive lower-bound delta in net P&L versus served current.
- Bounded latest active-day promotion-grade scoring selected `data/mm_runs/2026-06-25/20260626T015448206993Z` and completed in 2.2 seconds after quote-blocker diagnostics were added: 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, freshness `PASS`, fill evidence `PASS` only because no quotes existed, reward score 0.
- Quote-blocker diagnostics show overlapping blockers: 132 blocked rows, 132 event-gate suppressed rows, 121 known-edge permission-blocked rows, 132 known-edge state rows, 132 known-edge allowed=false rows, 11 harvest-only rows suppressed by the event gate, top event-gate state `PULL/suppress/INFO_EVENT_METAR_PRINT`, and top known-edge states 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, 11 `awaiting_paper_markouts/harvest_only/SHADOW`.
- Validation after the latest exchange-diagnostics, latency-stopgap, US private WebSocket fixture-normalization, stricter cancel-all proof, platform-verification v0.2, and paper-scoring runtime changes: 110 focused maker tests passed plus 5 subtests.

Earlier future-date 2026-06-26 shadow drill:

- Run folder: `data/mm_runs/2026-06-26/20260626T013844852296Z`.
- Event metadata validation: `PASS`.
- Exchange economics status: `PASS` during that drill.
- Preflight status: `BLOCK`.
- Row count: 12.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- First failing gate: `active_event`.
- First failing detail: `no active current market rows`.
- Root cause class: `blocked_by_market_discovery`.
- Main missing artifacts: current snapshot/model rows, source-status rows, CLOB token rows, CLOB book rows, band-level CLOB feature rows, and reward metadata for June 26.

Earlier current-date 2026-06-26 shadow drill:

- Run folder: `data/mm_runs/2026-06-26/20260626T132648384687Z`.
- Event metadata validation: `PASS`.
- CLOB status/audit: `RUNNING`, strict audit `ok: true` across 12 June 26 markets.
- Exchange economics status: `PASS`, verified for target date `2026-06-26`.
- Preflight status: `WARN`.
- Row count: 132.
- Quote-permission rows: 0.
- Live-trade-permission rows: 0.
- First failing gate: `model_freshness`.
- First failing detail: current model snapshot is stale or timestamp is missing.
- Per-market preflight: 11 markets `STALE` on `model_freshness`; Toronto `PASS` at preflight but then blocked by missing known-edge permission.
- No-quote reasons: 121 `NO_QUOTE_STALE_INPUT`, 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION`.
- Bounded paper score: freshness `NO_ACTIVE_DAY`, exchange economics target-date match `PASS`, reward score 0, fill evidence `PASS` only because no quotes existed.

Latest current-date 2026-06-26 shadow drill:

- Run folder: `data/mm_runs/2026-06-26/20260626T134201734227Z`.
- Event metadata validation: `PASS`.
- CLOB status/audit at check time: `RUNNING`, strict audit `ok: true` across 12 June 26 markets.
- Exchange economics status: `PASS`, verified for target date `2026-06-26`.
- Preflight status: `PASS`.
- Row count: 132.
- Quote-permission rows: 9.
- Latest-tick no-quote rows: 123.
- Live-trade-permission rows: 0.
- Quoted cells: Dallas `87 F or below`, `88-89 F`, `90-91 F`, `96-97 F`, `98-99 F`, `100-101 F`, `102-103 F`, `104-105 F`, and `106 F or higher`, all two-sided harvest-only quotes capped to 1.75 shares per side by the early-hour guardrail.
- No-quote reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`.
- Order lifecycle: 18 intended legs and 18 paper-posted legs, with no live exchange transitions.
- Bounded paper score: freshness `NO_ACTIVE_DAY`, exchange economics target-date match `PASS`, 18 quote legs, 0 conservative fills, 0 queue-estimated fill legs, reward score 12.26505, counterfactual reward 109.2508 USDC, fill evidence `BLOCK`, 784 missing-size trade rows, and 18 unresolved resting quotes because active-day settlement was not yet available.

## Architecture Audit

The market-making architecture is aligned with the goal of safely farming rewards, but the evidence gates are correctly preventing live use.

Strengths:

- `mm_policy.py` is a pure quote-intent module with no execution adapter or private-key dependency. It turns model state, promotion state, CLOB freshness, watcher freshness, known-edge map, event gates, and risk caps into auditable quote/no-quote rows.
- `market_making_run.py` owns run folders, target-date discovery, preflight, budget ledgers, evidence classification, and fail-closed run summaries.
- `mm_risk.py` has explicit sizing and halt concepts: per-band cap, per-event expected and worst-case cap, correlated-regime caps, daily drawdown, backed balance, manual pause, heartbeat halt, stale-source halt, stale-book halt, stale watcher, and cancel-all.
- `mm_exchange.py` builds request plans instead of directly hiding mutations. For US it uses `participateDontInitiate`; for global it requires a signed EIP-712 order payload and sets `postOnly`.
- `mm_exchange.py` now reports platform-specific live-readiness notes in adapter diagnostics and reconciliation reports. For US these call out private WebSocket order reconciliation, cancel-all zero-open-order confirmation, latency-stopgap reject handling, and external API-key/platform eligibility.
- The US adapter now classifies a documented `Global Rate Limit Exceeded` latency-stopgap response on order placement as `reject_class = latency_stopgap`, `order_acceptance = not_accepted`, `rate_limit_backoff_required = false`, and `must_refresh_book_before_retry = true`. The same message on pure cancel/cancel-all is classified as `unexpected_latency_stopgap_on_cancel` and remains a live-readiness blocker.
- The reconciliation path now normalizes Polymarket US private WebSocket order updates into lifecycle and fill rows for fixture testing. Covered execution types include partial/full fills, canceled, rejected, expired/done-for-day, and replaced/modified orders.
- Cancel-all probe status now requires structured proof of a cancel-all request plus zero open orders after the request. A generic canceled user-stream event or an unstructured `passed` flag no longer satisfies `cancel_all_verification`.
- `market_making_preflight.load_platform_verification_gate` now requires a current `mm_platform_verification_v0.2` artifact with structured private-stream, maker-only, cancel-all, and US latency-stopgap fields before `live-pilot` can pass.
- `mm_paper.py` keeps conservative fills separate from the queue-aware companion. That is important because queue simulation is useful for diagnosis but should not be the promotion gate.
- `mm_paper_scoring.py` scores fee-equivalent, maker rebate, flattening fees, reward estimates, markouts, settlement P&L, and queue evidence.
- `clob_recon.py` measures reward-qualifying depth, executable depth, and passive markouts rather than assuming that a reward window is profitable.
- `exchange_economics.py` blocks stale target-date economics and emits drift/rescore evidence.

Risks and gaps:

- The local snapshot currently points to Polymarket US economics, while older docs and some research artifacts also discuss International rules. The operating platform must be explicit on every run.
- Current-date event metadata, CLOB audit, exchange economics, snapshot/model freshness, and daily-roll useful-work liveness now pass for the active June 26 paper loop. The active blocker has moved to known-edge permission plus information-event suppression, with no quote permissions in the countable daily-roll evidence so far.
- The latest stable post-settlement one-shot passed preflight and produced only one quote permission. That means quote starvation, not basic active-date discovery, is the immediate bottleneck.
- The active-date run still had 10 missing-book rows and 1 snapshot-cadence-degraded row, so some infrastructure/data-quality cleanup remains mixed into the policy no-edge result.
- Fill evidence is not complete enough to scale. The conservative fills are too sparse, and queue evidence has missing book/trade-size links.
- Reward P&L remains zero in the standard paper report. Bounded diagnostics now compute Polymarket US reward score and counterfactual score share separately from reward-dollar P&L, but actual payout eligibility, target-size qualification, active-window evidence, and paid-vs-predicted reconciliation remain unproven.
- Skip-model-variants diagnostics are useful for operational readiness and reward-score smoke checks, but they deliberately omit model-variant promotion evidence.
- Skip-fill-simulation diagnostics are useful for current full-corpus quote/no-quote and reward-score inspection, but they deliberately omit conservative fills, queue companion fills, markouts, P&L, and fill-evidence gates.
- The current model should remain a veto and edge-research source, not a global fair-value quoting engine. The known-edge map is mostly `harvest_only`.
- Live-user stream connectivity, account-level reward/rebate reconciliation, real cancel-all verification, and isolated-wallet proof remain live-readiness work, not current assumptions. The US private-stream message shape and zero-open-order cancel-all probe are fixture-tested only.
- US latency-stopgap handling is partly implemented and tested at the adapter-response level, but there is no live proof that order-submit rejects, cancel-replace rejects, and pure cancel behavior are handled correctly under load.

## Readiness Gate

PASS:

- Focused maker tests.
- CLOB strict audit at check time.
- Active-date event metadata validation.
- Active-date Polymarket US exchange-economics snapshot and accepted baseline.
- Active-date shadow preflight.
- Paper score freshness.
- Fail-closed shadow behavior.
- Pure policy and externalized signing design.

WARN:

- Paper P&L is positive but tiny, with negative 30-minute adverse selection.
- Daily roll is alive for `2026-06-26`, active-day useful-work liveness is `PASS`, and the current bounded daily-roll score has 1 live-forward paper day but 0 quote legs.
- Queue-estimated fill volume is much larger than conservative fills and should be treated as diagnostic only.

BLOCK:

- Active-window countable quote permission is still unproven.
- The latest countable active-day run produced zero quote permissions.
- Dallas has 10 missing-book no-quote rows in the latest stable drill.
- Known-edge and promotion blockers still suppress 121 rows.
- Fill evidence completeness.
- Reward-score simulation and reward P&L measurement.
- Model variant promotion.
- Model-variant promotion evidence with enough independent target days and a positive lower-bound net-P&L delta versus served current.
- Real private WebSocket order-stream reconciliation, cancel-all zero-open-order confirmation, US latency-stopgap live proof, and API-key/platform eligibility proof.
- Any live-pilot step.
