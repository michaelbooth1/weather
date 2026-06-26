# Market-Making Reward Farming Readiness

Date: 2026-06-26

Status: research and shadow/paper preparation only. This report does not authorize live orders.

## Executive Verdict

The repo is not ready for live reward farming today. It is ready for continued research, quote-starvation diagnosis, targeted data-quality repair, shadow ticks, and paper-live-forward evidence collection after active-day gates are passing.

The important positive finding is that the bot is failing closed. The first 2026-06-26 shadow drill blocked on missing current target-date data. After refreshing active-date metadata and exchange economics for the active daily-roll date (`2026-06-25`), the active-date shadow tick reached `preflight_status = PASS` but wrote 0 live-trade-permission rows. After runtime/liveness fixes and supervisor restarts, a stable post-settlement drill emitted only 1 non-countable paper quote and still wrote 0 live-trade-permission rows. That is the correct behavior while policy and evidence gates are thin.

Current live-pilot blockers:

- Stable post-settlement quote permission is minimal: run `data/mm_runs/2026-06-25/20260626T020148684548Z` had 132 intent rows, 1 quote-permission row, and 0 live-trade-permission rows.
- Reason counts on the latest stable post-settlement drill were `NO_QUOTE_KNOWN_EDGE_PERMISSION = 121`, `NO_QUOTE_MISSING_BOOK = 10`, and `QUOTE_HARVEST_MID = 1`.
- Missing known-edge records, promotion blocks, Dallas missing-book rows, and awaiting active-window paper markouts explain why this is not live-ready.
- The standard paper report has `fill_evidence_completeness.status = BLOCK`.
- Promotion-grade `weather.market.mm_paper` did not finish within 300 seconds in this pass, so the standard paper report was not regenerated after the latest post-settlement drill.
- Model variant promotion remains `BLOCK`.
- No live account/platform verification, user-stream, cancel-all, paid reward/rebate, isolated-wallet, or settlement-P&L evidence exists for a live pilot.
- The platform-verification live gate now requires `mm_platform_verification_v0.2`; older v0.1 or boolean-only artifacts fail closed until refreshed with maker-only, private-stream, cancel-all zero-open-order, and US latency-stopgap proofs.

Current active-date repairs already completed:

- `data/backtest/event_metadata_validation.json` is `PASS` for target date `2026-06-25`.
- `data/backtest/exchange_economics_snapshot.json` is verified for `2026-06-25`, platform `polymarket_us`, snapshot id `xecon-036874d19e56c76f`.
- `data/backtest/exchange_economics_drift.json` is `PASS` with `rescore_required = false`.
- Focused runtime/snapshot tests passed after a scoped runtime-identity guard fix in `snapshot_store.py`.
- Maker useful-work runtime identity now uses scoped supervisor identities; focused regression tests passed.
- Snapshot, CLOB, observation-trigger, and daily-roll supervisors were restarted or ensured after stale-code detection. The restarted daily roll is post-settlement evidence and is not countable live-forward evidence.

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
- The accepted snapshot's `source_checked_at_utc` remains `2026-06-24T00:00:00+00:00`, so the next target-date economics publish/accept should refresh source dates before any live review.
- The economics snapshot does not and should not by itself prove live API readiness. The new exchange diagnostics in `mm_exchange.py` now separately disclose US private-stream, cancel-all confirmation, latency-stopgap handling, API-key eligibility, and secret-redaction requirements.
- The live-pilot `platform_verification_gate` now enforces those API-readiness requirements through `mm_platform_verification_v0.2`, including `participateDontInitiate` for US, private-stream final-state reconciliation, cancel-all zero-open-order proof, and US latency-stopgap handling proof.

## Local Evidence Snapshot

Commands run in this pass:

- `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q`
  - Result: 89 passed, 5 subtests passed.
- `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py -q`
  - Result: 109 passed, 5 subtests passed.
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

Paper report summary from `data/backtest/mm_paper_report.json`:

- Candidate run folders: 30, with 29 anti-overfit runs.
- Quote rows: 626,069.
- Quote legs: 71,756.
- Conservative fills: 35.
- Conservative filled shares: 175.
- Queue-estimated fill legs: 13,045.
- Paper score freshness: `PASS`.
- Live-forward day count: 6.
- Gate status: `OPEN`.
- Fill evidence completeness: `BLOCK`.
- Fill evidence blockers: 6,917 missing-size trade rows, 2,142 missing-book queue legs, 26 missing-trade-size queue legs.
- Net paper P&L after fees/incentives: about 2.19 USDC.
- 30-minute adverse-selection P&L: about -5.39 USDC.
- Settlement P&L: about 2.56 USDC.
- Liquidity reward estimate: 0.
- Model variant bakeoff status: `PASS`.
- Model variant promotion: `BLOCK`.

Known-edge map summary from `data/backtest/mm_known_edge_map.json`:

- Record count: 238.
- Permission counts: 159 `harvest_only`, 68 `no_quote`, 11 `edge_research`.
- Promotion market count: 11.
- Paper fill count: 35.
- CLOB recon slice count: 21,032.
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
- `mm_paper_scoring.py` now caches per-token timestamp indexes for trade, book, and mark rows. After that optimization, full-corpus promotion-grade scoring with `--skip-model-variants` still timed out after 300 seconds, so the fill/queue/markout path remains a runtime blocker.
- Bounded latest active-day promotion-grade scoring selected `data/mm_runs/2026-06-25/20260626T015448206993Z` and completed in 2.2 seconds after quote-blocker diagnostics were added: 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, freshness `PASS`, fill evidence `PASS` only because no quotes existed, reward score 0.
- Quote-blocker diagnostics show overlapping blockers: 132 blocked rows, 132 event-gate suppressed rows, 121 known-edge permission-blocked rows, 132 known-edge state rows, 132 known-edge allowed=false rows, 11 harvest-only rows suppressed by the event gate, top event-gate state `PULL/suppress/INFO_EVENT_METAR_PRINT`, and top known-edge states 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, 11 `awaiting_paper_markouts/harvest_only/SHADOW`.
- Validation after the latest exchange-diagnostics, latency-stopgap, US private WebSocket fixture-normalization, stricter cancel-all proof, and platform-verification v0.2 changes: 109 focused maker tests passed plus 5 subtests.

Latest future-date 2026-06-26 shadow drill:

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
- Active-date event metadata and exchange economics now pass for `2026-06-25`; future-date drills can still block when the snapshot/CLOB folders have not rolled to the requested date.
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
- Daily roll was alive, but all-market active-day useful-work liveness was blocked.
- Queue-estimated fill volume is much larger than conservative fills and should be treated as diagnostic only.

BLOCK:

- Active-window countable quote permission is still unproven.
- The latest countable active-day run produced zero quote permissions.
- Dallas has 10 missing-book no-quote rows in the latest stable drill.
- Known-edge and promotion blockers still suppress 121 rows.
- Fill evidence completeness.
- Reward-score simulation and reward P&L measurement.
- Model variant promotion.
- Full-corpus promotion-grade scoring runtime, or a bounded active-window evidence set that exactly covers the intended promotion scope.
- Real private WebSocket order-stream reconciliation, cancel-all zero-open-order confirmation, US latency-stopgap live proof, and API-key/platform eligibility proof.
- Any live-pilot step.
