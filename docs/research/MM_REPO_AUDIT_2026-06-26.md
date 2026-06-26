# Market-Making Repo Audit

Date: 2026-06-26

Scope: repo-grounded audit for small-scale market-making preparation and liquidity-reward farming research. No live orders were placed or authorized.

## Executive Summary

The market-making stack is built with the right safety shape for a future small pilot: policy is separate from execution, exchange signing is injected, stale data fails closed, live mode is gated, and paper scoring separates conservative fills from queue-estimated fills.

The current evidence is still not ready for live reward farming. After refreshing same-day metadata and exchange economics for the active daily-roll date, the 2026-06-25 shadow tick reached `preflight_status = PASS` but produced 0 quote-permission rows. After scoped-runtime fixes and supervisor restarts, a later stable post-settlement drill produced 1 non-countable Dallas harvest quote. The remaining blocker is policy/evidence coverage, not basic discovery.

The immediate objective should be quote-starvation diagnosis under fresh active-day data, not live order placement.

## Current Evidence

Commands and results from this pass:

- Focused maker test suite:
  `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py -q`
  - Result: 89 passed, 5 subtests passed.
- Focused maker/exchange/platform-verification suite after v0.2 gate tightening:
  `.\venv\Scripts\python.exe -m pytest tests\market\test_mm_policy.py tests\market\test_mm_risk.py tests\market\test_mm_paper.py tests\market\test_market_making_run.py tests\market\test_mm_exchange.py tests\market\test_mm_exchange_reports.py tests\operations\test_runtime_identity.py -q`
  - Result: 109 passed, 5 subtests passed.
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

The 2026-06-26 shadow tick is useful as a future-date drill, but not as active-day proof. It had event metadata and exchange economics `PASS`, yet all 12 markets blocked on missing active current market rows, missing snapshot/model rows, empty CLOB token files, missing CLOB books/features, and missing reward metadata because no June 26 snapshot folders existed while the active loops were still on June 25.

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
- Policy fail-closed behavior is working: missing future-date artifacts produced 12 no-quote rows and no permissions; active-date policy uncertainty initially produced 132 no-quote rows and no permissions; later post-settlement evidence produced only 1 non-countable quote and no live permission.
- Exchange economics is target-date gated: the snapshot now validates for active date `2026-06-25` and platform `polymarket_us`.
- Event metadata is target-date gated: active-date validation is now `PASS`.
- CLOB strict audit passed at check time across 12 markets.
- Exchange signing remains external/injected through request-plan and adapter boundaries.
- Live-pilot mode remains behind explicit operator flags, live-readiness, data-layer gate, platform/account verification, credential diagnostics, and `--allow-live`.
- The platform-verification gate now requires `mm_platform_verification_v0.2`, including maker-only field proof, private-stream lifecycle/fill/final-state reconciliation, cancel-all zero-open-order confirmation, and US latency-stopgap handling proof.
- Runtime identity is now scoped correctly for snapshot persistence: `snapshot_store.py` now compares the process identity against `current_identity_for(process_identity)`, matching the scoped identity design already used in `snapshot_tracker.py`.

Still blocked:

- Quote permissions are zero under active-day fresh preflight.
- The daily roll status still reported all-market active-day useful-work liveness `BLOCK` in the operator report.
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

3. Future-date validation can pass while data folders are absent.

   The June 26 shadow tick showed event metadata and economics can validate for the future target date, but the market-making preflight still correctly blocks when snapshots, source-status rows, token files, books, features, and reward metadata are not present.

4. The economics snapshot is not a live API readiness proof.

   The accepted snapshot still matches the core Polymarket US fee/reward assumptions rechecked on June 26, 2026, but the official US API docs add operational requirements outside economics: `participateDontInitiate` maker-only order entry, private WebSocket order reconciliation, cancel-all followed by zero-open-order confirmation, rate-limit discipline, and 5-second latency-stopgap reject handling. `mm_exchange.py` now surfaces these as live-readiness notes, normalizes US private-stream order-update fixtures into lifecycle/fill evidence, and classifies documented US latency-stopgap order rejects as no-acceptance stale-price protection rather than ordinary rate-limit backoff. `market_making_preflight.py` now fails live-pilot unless the v0.2 platform-verification artifact records those proofs.

4. A runtime-identity guard bug blocked forced snapshots before this pass.

   `snapshot_store.py` had been comparing scoped process identity to whole-tree current identity, causing `stale_code` even when the loaded-code scope was current. The narrow fix uses `current_identity_for(process_identity)`. Focused runtime/collection tests passed after the fix, and a forced snapshot wrote for the active June 25 event.

5. Reward-farming optimization is under-specified locally.

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
- The restarted daily roll began after the local active evidence window, so it is `post_settlement_evaluation` and does not count toward live-forward gates.

Latest stable one-shot:

- Run folder: `data/mm_runs/2026-06-25/20260626T020148684548Z`.
- Evidence mode: `post_settlement_evaluation`.
- Preflight: `PASS`.
- Quote-permission rows: 1.
- Live-trade-permission rows: 0.
- Reasons: 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 10 `NO_QUOTE_MISSING_BOOK`, 1 `QUOTE_HARVEST_MID`.
- Interpretation: current blocker is mostly quote starvation under policy/evidence gates, not stale inputs. One Dallas harvest quote appears post-settlement but is not countable live-forward evidence.

Bounded paper-score follow-up:

- `weather.market.mm_paper --run-folder data\mm_runs\2026-06-25\20260626T020148684548Z` completed and wrote `data/backtest/mm_paper_quote_starvation_20260626T020148684548Z.json`.
- Result: 132 quote rows, 2 quote legs, 0 conservative fills, 0 queue-estimated fill legs, gate `OPEN`, paper score freshness `NO_ACTIVE_DAY`, fill evidence status `BLOCK`, and 0 P&L/reward/rebate estimates.
- The diagnostic known-edge map had 217 records: 176 `harvest_only`, 38 `no_quote`, and 3 `edge_research`.
- First-class bounded selection was added to `weather.market.mm_paper`: `--target-date` / `--run-target-date`, `--evidence-mode`, and `--latest-n`.
- Bounded reports now disclose `diagnostic_selection_not_full_corpus` in their summary so they are not confused with standard full-corpus evidence.
- Smoke run `data/backtest/mm_paper_bounded_latest_postsettlement_20260626.json` selected `data/mm_runs/2026-06-25/20260626T015632370043Z`: 4,488 quote rows, 52 quote legs, 5 conservative fills, 0 queue-estimated fill legs, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, net -0.00974 USDC, reward estimate 0.
- Reward-score diagnostics were added to `weather.market.mm_paper` and the paper report. The bounded smoke report scored 52 quoted legs under the Polymarket US discount-factor/ticks formula, with total reward score 141.7, score/target-size 0.01417, and counterfactual reward 586.263964 USDC under campaign-pool 1000 and competitor-score 100 assumptions.
- `--skip-model-variants` was added for faster operational paper diagnostics. A skip-variant smoke report completed in 3.9 seconds at smoke-check time, selected the same growing post-settlement run, and disclosed model-variant scoring `SKIPPED (skip_model_variants)` with 5,148 quote rows, 62 quote legs, 7 conservative fills, freshness `NO_ACTIVE_DAY`, fill evidence `BLOCK`, and net -0.013636 USDC.
- `--skip-fill-simulation` was added for full-corpus quote/no-quote/reward diagnostics. A full summary-only report completed in about 176 seconds with 36 included run folders, 628,481 quote rows, 71,828 quote legs, 35,914 quote-permission rows, reward score 165,800.676275, counterfactual reward 999.39723 USDC, paper freshness `PASS`, fill evidence `SKIPPED`, and model-variant scoring `SKIPPED`.
- `mm_paper_scoring.py` now caches per-token timestamp indexes for trade, book, and mark rows, but full-corpus promotion-grade scoring with `--skip-model-variants` still timed out after 300 seconds and wrote no outputs.
- Bounded latest active-day promotion-grade scoring selected `data/mm_runs/2026-06-25/20260626T015448206993Z`: 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, freshness `PASS`, fill evidence `PASS` only because no quotes existed, reward score 0.
- Paper reports now include quote-blocker diagnostics. The latest active-day report shows overlapping blockers: 132 event-gate suppressed rows, 121 known-edge permission-blocked rows, 132 known-edge state rows, 132 known-edge allowed=false rows, 11 harvest-only rows suppressed by the event gate, top event-gate state `PULL/suppress/INFO_EVENT_METAR_PRINT`, and top known-edge states 66 `promotion_block/no_quote/BLOCK`, 33 `missing_known_edge_record/no_quote/SHADOW`, 22 `missing_known_edge_record/no_quote/BLOCK`, 11 `awaiting_paper_markouts/harvest_only/SHADOW`.
- The full historical promotion-grade `weather.market.mm_paper` path still timed out after 300 seconds, so fill/queue/markout scoring still needs further runtime work before it can be relied on during live-prep cycles.

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
- Paper P&L is small and 30-minute adverse selection is negative in the existing standard report.
- Queue-estimated fills are much larger than conservative fills and remain diagnostic, not promotion-grade.
- Bounded post-settlement scoring is now fast, but it is diagnostic-only unless it exactly covers the intended countable evidence set.
- Skip-model-variants scoring is faster, but it omits model-promotion evidence by design.
- Skip-fill-simulation scoring makes full-corpus quote/reward inspection possible, but omits conservative fills, queue companion, markouts, P&L, and fill-evidence gates by design.
- Reward-score and counterfactual payout diagnostics are present, but actual payout and competitor-score calibration remain unproven.

BLOCK:

- Zero quote-permission rows on the active-date shadow tick.
- Missing-book and snapshot-cadence no-quote reasons.
- Fill evidence completeness.
- Reward-score simulation and reward P&L measurement.
- Model/policy promotion.
- Live account/platform verification and live lifecycle evidence.

## Next Safe Actions

1. Diagnose quote starvation on the active-date run:
   - use the new quote-blocker diagnostics to separate event-gate suppression from known-edge and promotion blockers;
   - separately fix the 10 missing-book rows seen in the post-settlement drill.
2. Run a countable `paper-live-forward` session only while active-date metadata/economics, CLOB audit, snapshot freshness, and useful-work liveness are all passing.
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
