# Workstation report: make MM days countable

Date: 2026-08-05

Handoff: `docs/roadmap/workstation-handoff-2026-09-11a-make-mm-days-countable.md`

Branch: `codex/workstation-make-mm-days-countable-2026-09-11a`

Base: `origin/master` at `d259cc2c9a83835066d39b7465679d5f0c0291fb`

## Outcome

The countability path is now mechanical and fail closed in code, but the host
is **not operationally ready to count its first MM day**. The missing producer
is a real host gap: read-only Task Scheduler inspection found both
`WeatherClobEnrichmentLoop` and the new `WeatherMakerExecutionCapture` absent.
No task was registered or started in this mission, and no provider endpoint was
called.

The branch supplies the missing continuous fleet WebSocket producer and binds
maker-day countability to its retained raw/canonical tape and session receipts.
It also:

- selects the active-day MM attempt instead of a later post-settlement attempt
  when neither is countable;
- prevents optional shadow-variant skips from blocking a served-model maker day;
- fixes the acceptance horizon at settlement, retaining 30-minute P&L only as
  a provisional diagnostic when settlement is absent;
- computes sampled own Q, competitor Q, denominator, and share from retained
  full-depth `order_books.jsonl`, without the flat competitor scalar;
- excludes heuristic reward and rebate dollars from acceptance P&L unless
  actual payout evidence is explicitly present; and
- emits an exact `COUNTABLE` / `NOT_COUNTABLE` checklist in the paper payload
  and propagates it into trading evidence.

No promotion rule, trusted-model floor, release pointer, live sizing setting,
key, wallet, order path, or live-trading path changed. The design target remains
the existing `$25/tier-20` plan and 22 countable dates; this change does not
claim that either has been achieved.

## Reservation state

I re-read `docs/operations/reserved-confirmation-window.md`. It is armed but
undated: no dates are currently reserved. If that source declares a window
before activation, it outranks this report. MM scoring must stop on every
declared confirmation date and receives no exemption.

## Root cause of every observed blocker

The amended handoff's target-day payload reported six blockers. They did not
have one common cause.

| Blocker | Root cause | What clears it |
| --- | --- | --- |
| `evidence_mode=post_settlement_evaluation` | Trading evidence chose the latest non-countable run after failing to find a countable run. On 2026-08-03 that hid active run `20260803T224637558414Z` behind later post-settlement run `20260804T014838228943Z`. | The selector now prefers the latest `active_day_live_forward` attempt when no countable run exists. Post-change read-only replay selects the active run with `ACTIVE_DAY_NON_COUNTABLE`. |
| `live_forward_gate=BLOCK` | The retained active-day run did not have a complete current fleet: nine markets had stale model/CLOB inputs, and the observation-trigger runtime was stale for Los Angeles. | Recover and prove all selected model, CLOB, and observation-trigger producers before the active window. This mission did not call providers or mutate those workers. |
| `preflight=WARN` | The same stale producer inputs made preflight warn before quoting. | A fresh all-market preflight with current model rows, books/features, and observation-trigger state. |
| `model_variant_bakeoff_skipped_variants=66` | Two optional shadow variants lacked their probability columns for 33 inputs each. The trading-evidence gate incorrectly treated all skipped research variants as served-path countability failures. | Variant specs now declare whether they count toward maker-day countability. Only `served_current` is required. All skips remain visible diagnostics; a missing served variant still blocks. |
| `quote_starvation=quote_starved_infra` | The 2026-08-04 active run retained 99 `NO_QUOTE_STALE_INPUT` rows and 33 `NO_QUOTE_KNOWN_EDGE_PERMISSION` rows. The stale-input majority is infrastructure starvation, not a clean no-edge abstention. | Restore the stale producer inputs. The promotion/known-edge rule remains unchanged and separate. |
| `fill_evidence_completeness=BLOCK` | There were no decision-grade execution tapes for the scored events. The scorer therefore had no way to distinguish no fills from no observation. | Run the continuous producer, retain raw and canonical WS tapes plus complete session receipts, and pass the new mechanical tape/coverage checklist. Missing tape can never count. |

After the change, read-only replay of retained 2026-08-04 evidence returns:

```text
run_id=20260804T110502193025Z
selection=ACTIVE_DAY_NON_COUNTABLE
evidence_mode=active_day_live_forward
preflight=WARN
required_model_variant_skipped_input_row_count=0
countability_blockers=
  live_forward_gate=BLOCK
  preflight=WARN
  useful_work_liveness=BLOCK
  quote_starvation=quote_starved_infra
  paper_score_freshness=STALE
  fill_evidence_completeness=BLOCK
```

This is the intended diagnosis. The 66 optional shadow skips remain reported
but no longer obscure the actual active-day failures.

## Missing execution tapes: plain statement

The tapes were not pruned or silently lost. They were never continuously
written.

The deployed latency-critical CLOB loop is intentionally raw-book-only. Its
contract disables WebSocket events. The separate enrichment loop is the only
previous producer of `market_ws.jsonl` and `market_ws_events.csv`, but it is not
registered now. Its retained status shows one Toronto research iteration on
2026-07-27, not a running all-fleet production process. Its existing 20-second
per-market sequential sampling would also leave large blind intervals and
could not prove that a resting quote saw every strict-through execution.

The repair is `weather.market.mm_execution_capture`, with registration source
`scripts/ops/register_mm_execution_capture.ps1`. It:

1. fetches current built-in event metadata at runtime;
2. subscribes all active fleet token IDs on one long-lived public CLOB
   WebSocket connection;
3. routes each payload to its owning event folder;
4. writes both `market_ws.jsonl` and `market_ws_events.csv` under the existing
   raw-tape writer guard;
5. writes `market_ws_sessions.jsonl` receipts with session identity, coverage
   start/end, status, asset count, message count, and continuity verdict;
6. writes a heartbeat status while the session is running; and
7. records disconnects and message-limit exits as `INCOMPLETE`, never as
   complete coverage.

The new scheduled task is deliberately separate from the three existing
`ensure` supervisors. It is long lived, uses `MultipleInstances=IgnoreNew`, and
the five-minute repetition is only a crash supervisor. Editing the script did
not authorize registration.

## Constructive retained-artifact proof

`tests/market/test_mm_day_countability.py` builds a complete synthetic market
day on disk, not an in-memory assertion:

- a quote at 0.50 for 10 shares with a 60-second lifetime;
- a full-depth book captured 10 seconds before the quote;
- a retained `SELL` execution at 0.49 for 2 shares, 20 seconds after the quote;
- canonical trade time, side, size, condition, and execution identity;
- a complete WebSocket session covering both the decision time and quote
  lifetime;
- a 30-minute mark; and
- a WU-proxy settlement artifact resolving the quoted band.

The production scorer reads those files and emits exactly one conservative
fill with:

```text
conservative_fill_rule=strict_trade_through_price_and_recorded_size
acceptance_horizon=settlement
acceptance_pnl_status=COUNTABLE_SETTLEMENT
```

The same test replays the retained full-depth bid side. With discount 0.3,
the hypothetical 0.50 / 10-share quote has own Q 10.0. Competitor levels at
0.49 / 20 and 0.48 / 10 produce competitor Q 6.9, denominator 16.9, and sampled
share `10 / 16.9`. The output binds the source path, capture ID, capture time,
book SHA-256, and a streaming hash over all sample bindings. The resulting
maker-day checklist is `COUNTABLE`.

Negative proofs cover the two dangerous inversions:

- a valid policy abstention with no execution tape remains `NOT_COUNTABLE`; and
- a fill with a 30-minute value but no settlement remains `NOT_COUNTABLE`, with
  no acceptance net P&L.

## P2: one acceptance horizon

Settlement is the sole acceptance horizon. `compute_fill_financials` now emits:

- `acceptance_horizon=settlement`;
- `COUNTABLE_SETTLEMENT` and a net P&L only when settlement exists; or
- `NOT_COUNTABLE_SETTLEMENT_MISSING`, `net=None`, and a separately labelled
  `provisional_net_30m_usdc` when it does not.

Summary net P&L is `None` if any fill lacks settlement. The 30-minute aggregate
remains visible but cannot silently stand in for settlement.

Heuristic reward and fixed fee-equivalent rebate dollars are likewise
diagnostic only. They remain in `liquidity_reward_estimate_usdc` and
`maker_rebate_estimate_usdc`, while the corresponding accepted values are zero
unless a fill carries explicit actual payout evidence.
`liquidity_reward_accepted_usdc` and `maker_rebate_accepted_usdc` therefore do
not manufacture incentive income from a scalar proxy. This makes the existing
`does_not_change_pnl=True` reward claim true and applies the same fail-closed
treatment to the rebate shortcut.

## P3: exact sampled reward Q-share

`weather.market.mm_reward_q_share` streams each event's full-depth
`order_books.jsonl` once. It keeps only the latest needed book per token and
merges it against time-sorted quote legs, preserving the scorer's flat-memory
contract. Each quote leg is scored against the latest book at or before the
decision time, subject to a 120-second maximum age.

For each sample the scorer computes:

- effective best price including the hypothetical quote;
- own Q;
- competitor Q from every eligible retained level and size on the same side;
- denominator and own share;
- depth level count, tick, and minimum size; and
- path, capture ID/time, book hash, and aggregate sample-binding hash.

Unsupported formula, missing/stale book, empty side, invalid tick/discount, or
partial sample coverage returns `BLOCK`. The old scalar competitor score
remains only in the legacy counterfactual diagnostic and cannot satisfy the
maker-day checklist or enter acceptance P&L.

## P4: mechanical day checklist

`weather.market.mm_day_countability` emits one exact status and blocker list.
The scheduled paper scorer may retain up to 14 active runs for its longitudinal
diagnostics, but the countability proof is now explicitly bound to the settled
analysis target date. Older selected runs cannot create a multi-date mismatch
or contaminate that day's tape, settlement, or Q-share verdict.

For a day to return `COUNTABLE`, all of these must be true:

- exactly one target date is present;
- every expected event has non-empty raw and canonical execution tapes;
- every expected event has a non-empty full-depth book tape, including valid
  policy-abstention events;
- a complete retained session covers every policy decision time, including
  no-quote decisions;
- a complete retained session covers every resting quote's full lifetime;
- every credited fill uses the strict price-and-recorded-size trade-through
  rule;
- every credited fill retains complete execution identity/time/side/condition/
  price/size provenance and all four required markout horizons;
- every fill has settlement-horizon acceptance P&L;
- fill parsing, identity, size, queue, and resting-quote evidence has no blocker;
- every quoted leg has an exact fresh full-depth Q-share sample; and
- the canonical confirmation reservation is readable and the target date is
  not declared reserved; and
- the selected trading-evidence run independently passes active-day mode,
  live-forward, preflight, useful-work, freshness, exchange-economics, and
  starvation checks.

`no_quote_legs` alone is not an economic fill blocker: a clean policy abstention
can count. But its decision timestamps and execution tapes must still be
complete. Missing execution tape, even with zero trades and zero fills, always
returns `NOT_COUNTABLE`.

The reservation check happens before run discovery, not merely when the report
is rendered. If the canonical source declares a range, an unspecified scoring
target fails closed and a target inside that range is refused before its maker
artifacts are read. The current armed-undated declaration passes and is bound by
SHA-256 in the day proof.

## First post-PASS operational payload

The first day may count toward the 22-date target only after the operator has
verified this payload. None of these items is implied by merging the branch.

```yaml
reservation:
  source: docs/operations/reserved-confirmation-window.md
  target_date_declared_reserved: false

deployment:
  branch_merged_in_quiet_window_01_00_to_04_00: true
  all_three_existing_capture_loops_rolled_after_schema_registry_change: true
  WeatherMakerExecutionCapture_registered: true
  WeatherMakerExecutionCapture_running: true
  market_execution_capture_status: RUNNING_or_COMPLETE_and_fresh

active_day_run:
  evidence_mode: active_day_live_forward
  selection: COUNTABLE_TARGET_DATE_or_COUNTABLE_LATEST
  preflight_status: PASS
  live_forward_gate: PASS
  useful_work_liveness: PASS
  selected_markets_current: true
  quote_starvation: not_quote_starved_infra
  served_current_variant_present: true
  optional_shadow_skips: diagnostic_only

paper_score:
  target_dates: [exact_target_date]
  paper_score_freshness: PASS
  exchange_economics_gate: PASS
  day_countability: COUNTABLE
  execution_tape_inventory: PASS
  all_decision_times_covered: true
  all_quote_lifetimes_covered: true
  non_strict_through_fill_count: 0
  settlement_missing_fill_count: 0
  reward_q_share_status: PASS_or_NOT_APPLICABLE_when_no_quotes
  reward_q_share_exact_sampled: true
  heuristic_reward_or_rebate_dollars_in_acceptance_pnl: false

target_accounting:
  count_increment: 1
  required_countable_dates: 22
  daily_design_target_usd: 25
  live_sizing_config_changed_by_this_branch: false
```

Before that day, the operator must merge during the quiet window, roll the
three existing capture loops because of the schema-registry change, explicitly
register the new task, and verify its fresh running heartbeat. After the market
day, the completed session receipts and tapes must survive scoring. A running
task alone is not countability evidence.

## Roll safety by file

Method: exact membership in each retained loop status
`runtime_identity.source_scope_files`, not `SOURCE_PATTERNS`. The compared
closures were `loop_status.json` (snapshot, 77 files), `clob_loop_status.json`
(23 files), and `observation_trigger_status.json` (85 files).

| File | Verdict | Exact closure result |
| --- | --- | --- |
| `README.md` | Roll-free | In none of the three closures. |
| `docs/operations/OPERATIONS_DESIGN.md` | Roll-free | In none. |
| `docs/roadmap/agent-report-2026-08-05-workstation-make-mm-days-countable.md` | Roll-free | In none. |
| `scripts/ops/AGENTS.md` | Roll-free | In none. |
| `scripts/ops/register_mm_execution_capture.ps1` | Roll-free | In none; registering it is a separate stateful action. |
| `src/weather/market/market_making_model_variants.py` | Roll-free | In none. |
| `src/weather/market/mm_day_countability.py` | Roll-free | In none. |
| `src/weather/market/mm_execution_capture.py` | Roll-free | In none; it is a new, separately launched process. |
| `src/weather/market/mm_paper.py` | Roll-free | In none. |
| `src/weather/market/mm_paper_aggregation.py` | Roll-free | In none. |
| `src/weather/market/mm_paper_constants.py` | Roll-free | In none. |
| `src/weather/market/mm_paper_reports.py` | Roll-free | In none. |
| `src/weather/market/mm_paper_scoring.py` | Roll-free | In none. |
| `src/weather/market/mm_reward_q_share.py` | Roll-free | In none. |
| `src/weather/reporting/market/trading_evidence.py` | Roll-free | In none. |
| `src/weather/schema_registry_data.py` | **Roll-sensitive** | Present in snapshot, CLOB, and observation-trigger closures. |
| `tests/market/test_mm_day_countability.py` | Roll-free | In none. |
| `tests/market/test_mm_execution_capture.py` | Roll-free | In none. |
| `tests/market/test_mm_paper.py` | Roll-free | In none. |
| `tests/market/test_mm_paper_scoring.py` | Roll-free | In none. |
| `tests/reporting/test_trading_evidence.py` | Roll-free | In none. |

Therefore this branch must merge between 01:00 and 04:00 and roll all three
existing capture loops. The new MM execution producer is activated separately.

## Verification

Passed:

- focused MM/reporting/schema slice: **82 passed**;
- architecture and schema-registry slice: **32 passed**;
- constructive countability proof: **5 passed** (including isolation of the
  exact day proof from a multi-date paper corpus and a declared-reservation
  stop-before-read proof);
- `python -m compileall -q app src tests`;
- `python -m weather.operations.agent_docs_audit`: **PASS**, 18 agent files and
  618 Markdown files;
- PowerShell parser validation of `register_mm_execution_capture.ps1`;
- focused flat-memory regression inside `test_mm_paper.py`; and
- `git diff --check` on tracked edits.

The repository-wide suite could not collect under the available interpreter.
The repository venv launcher points to a missing Python 3.11 installation. The
available bundled Python is 3.12, while the venv's scikit-learn, SciPy,
Matplotlib, and PyArrow extensions are CPython 3.11 binaries; full collection
stopped with 61 environment import errors. No dependency installation was
attempted because this handoff permits network only for `git fetch` and
`git push`. The focused affected slice used bundled Python 3.12 libraries plus
compatible pure-Python packages from the project venv.

## What would falsify this

Any one of the following falsifies the result or the claim that a day is
countable:

1. `WeatherMakerExecutionCapture` is absent, stale, disconnected, or produces
   an `INCOMPLETE` session during any decision/quote interval.
2. A day returns `COUNTABLE` with a missing/empty `market_ws.jsonl`,
   `market_ws_events.csv`, or `market_ws_sessions.jsonl`.
3. A no-quote day counts despite an uncovered policy decision timestamp.
4. A credited fill is not reproducible from retained exchange time, side,
   strict-through price, recorded size, and canonical execution identity.
5. A fill without settlement receives a non-null acceptance net, or a
   30-minute mark changes the acceptance verdict.
6. Replaying a bound full-depth book does not reproduce own Q, competitor Q,
   denominator, share, or the recorded book/sample hashes.
7. The scalar `reward_competitor_q` can satisfy the exact Q-share checklist or
   heuristic reward dollars enter acceptance P&L without actual payout evidence.
8. Missing optional shadow probability columns block a day whose served model
   is complete, or a missing served model fails to block.
9. Trading evidence selects a later post-settlement run over a same-date active
   attempt when neither is countable.
10. The schema-registry change merges outside 01:00-04:00 or the required
    three-loop roll creates an unaccounted Toronto capture gap.
11. The reservation source declares the date before collection and MM scoring
    nevertheless counts it.

The fastest real falsification test is the first post-activation day: retain
the complete raw inputs, rerun the paper scorer from those artifacts only, and
compare the payload above. Until it passes exactly, the 22-day counter remains
unchanged.
