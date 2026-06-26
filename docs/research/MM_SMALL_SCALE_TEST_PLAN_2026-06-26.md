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

## Phase 0: Repair Current Blocks

Do these before any new paper-live-forward evidence is interpreted.

Use the active daily-roll target date, not UTC tomorrow or a manually guessed date. Earlier in this pass the active target date was `2026-06-25`; a later June 26 shadow tick had current CLOB, event metadata, and exchange economics, but still blocked on stale model snapshots and known-edge permission. Do not treat any `shadow` operator drill as countable live-forward evidence.

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
- `weather.market.market_microstructure audit --strict` passes.
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
- The restarted daily roll is post-settlement evidence and does not count toward live-forward gates.
- Earlier current-date June 26 shadow drill `data/mm_runs/2026-06-26/20260626T132648384687Z` had 132 no-quote rows, 0 quote-permission rows, 0 live-trade-permission rows, 121 `NO_QUOTE_STALE_INPUT` rows, and 11 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows.
- Latest current-date June 26 shadow drill `data/mm_runs/2026-06-26/20260626T134201734227Z` had preflight `PASS`, 9 Dallas harvest-only quote-permission rows, 123 no-quote rows, 0 live-trade-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows, and 2 `NO_QUOTE_DISAGREEMENT_SHADOW` rows.
- Daily-roll status later showed stale/pid-missing. Repair that before collecting countable paper-live-forward evidence.
- Therefore Phase 2 should not be treated as satisfied until daily roll is healthy, quote permissions are observed during an active paper-live-forward window, fill evidence is complete enough for promotion, and the run can be scored with markouts and settlement/resting-quote resolution.

## Phase 2: Countable Paper-Live-Forward

Objective: collect evidence that counts toward live-forward gates.

Command shape:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_making_run --date <ACTIVE_TARGET_DATE> --budget-usdc 500 --mode paper-live-forward --markets all
```

Acceptance:

- Run occurs during the active local trading window.
- Evidence classification is countable.
- Useful-work liveness is `PASS`.
- The run has current snapshots, source-status rows, CLOB books, CLOB features, token metadata, and reward metadata.
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
- The latest bounded active-day promotion-grade score selected `data/mm_runs/2026-06-25/20260626T015448206993Z`, completed in 2.2 seconds after quote-blocker diagnostics were added, and found 132 quote rows, 0 quote legs, 0 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 11 `NO_QUOTE_INFORMATION_EVENT`, and reward score 0. Quote-blocker diagnostics show overlapping blockers: all 132 rows were event-gate suppressed, 121 rows were known-edge permission-blocked, and 11 harvest-only rows were suppressed by the event gate. This is the current active-day blocker; fill evidence `PASS` on this run only means there were no quoted legs to evaluate.
- The latest bounded June 26 shadow score selected `data/mm_runs/2026-06-26/20260626T134201734227Z`, completed in 5.0 seconds, and found 132 quote rows, 18 quote legs, 9 quote-permission rows, 121 `NO_QUOTE_KNOWN_EDGE_PERMISSION`, 2 `NO_QUOTE_DISAGREEMENT_SHADOW`, reward score 12.26505, counterfactual reward 109.2508 USDC, and exchange economics target-date match for `2026-06-26`. This is diagnostic only because it is `shadow`, freshness is `NO_ACTIVE_DAY`, fill evidence is `BLOCK`, and active-day resting quotes are unresolved until settlement evidence exists.
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
- Confirm tick size, min order size, reward target size, reward discount factor/spread threshold, fee rate, maker rebate, and order API semantics for that exact market.
- For Polymarket US, confirm order entry uses `participateDontInitiate`, not a marketable order path.
- Confirm user WebSocket or private stream works and produces order snapshots plus order execution updates.
- Confirm cancel-all request plan can be built without exposing secrets, then prove cancel-all with zero open orders after the request.
- Confirm US latency-stopgap handling before any order placement: new-order and cancel-replace rejects must be treated as transient stale-price protection that requires book refresh/recompute, while pure cancels must remain available. Adapter-level classification exists, but live proof is still required.

Required local artifacts:

- Fresh `mm_platform_verification_v0.2` artifact with maker-only order field proof, private-stream order snapshot/update/fill/final-state reconciliation proof, cancel-all zero-open-order proof, and US latency-stopgap proof where `platform = polymarket_us`.
- Fresh live-readiness JSON with all booleans true.
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
