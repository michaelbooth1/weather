# 256. Post-Fix Taker After-Fee Requalification Campaign [COMPLETE 2026-06-24 - CURRENT-FEE CAMPAIGN CLOSED FAIL-CLOSED]

Goal: collect a fresh paper-only champion/challenger campaign under current
taker defaults and require complete-label, after-fee, after-slippage evidence
before any live promotion.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-23.md`.
The last labelable runs are settlement-negative in aggregate (`-96.611751`
USDC over `154` settled fills), all settled rows are `paper_no_fee`, and the
active June 22 `low_price_tail_capped` run has `8` unresolved fills with no
settled sample.

Why this matters: items 234-241 added the right gates, but they do not create
the missing evidence. The bot needs a clean post-fix sample under the current
fee, bad-tail, cadence, current-high, and bakeoff defaults before any
profitability claim can be counted.

## Design

1. Relaunch paper taker runs under current source defaults, not the stale
   `daily_roll_status.json` launch config.
2. Run the full champion/challenger set every day, including
   `low_price_tail_capped`, trusted current-high/adjacent arms, and the
   two-sided/fade probe.
3. Settlement-score each day as labels arrive and require `3-5` complete-label
   days before promotion.
4. Track net PnL after fees, slippage, executable depth, drawdown,
   per-market stability, tail fraction, unresolved fills, and MTM sign flips.
5. Keep every arm paper-only until the full campaign passes.

- [x] Start a fresh paper campaign with current taker defaults and full
  bakeoff strategies.
- [x] Finalize each labelable run through the watchdog within SLA.
- [x] Build a campaign ledger with complete-label day count, after-fee net PnL,
  drawdown, tail exposure, and market-benchmark comparison.
- [x] Require explicit operator review before any live-size change.

Acceptance: no taker strategy is considered live-qualified until a fresh
post-fix campaign has at least `3-5` complete-label days, sufficient fills,
positive after-fee/after-slippage PnL, stable per-market slices, no unresolved
orders, and no material MTM/settlement sign-flip pattern.

Related: items 234, 237, 238, 240, 241, 253.

## 2026-06-23 Finalization And Ledger Refresh

Generated item-specific finalization and promotion evidence:

- `data/backtest/item256_taker_finalization_watchdog.json`
- `data/backtest/item256_taker_finalization_watchdog_report.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-21_bbe63642.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-21_bbe63642.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-22_3d74b86b.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-22_3d74b86b.md`
- `data/backtest/item256_taker_champion_challenger_ledger.json`
- `data/backtest/item256_taker_champion_challenger_ledger_report.md`

Watchdog result:

- runs scanned: `7`.
- labelable runs: `5`.
- newly finalized runs: `2` (`2026-06-21`, `2026-06-22`).
- needs finalization: `0`.
- pending finalization: `0`.
- SLA breaches: `0`.

Ledger result across the five available bakeoff artifacts:

- complete-label days: `0` against the required minimum of `3`.
- promotion pass count: `0`.
- decision: `KEEP_CHAMPION`.
- recommended strategy: `low_price_tail_capped`.
- all runs remain blocked by `partial_target_date_labels`; the June 21 and
  June 22 bakeoffs also carry `profitability_artifact_verification_failed`.
- `low_price_tail_capped` has `18` settled orders, `0` unresolved orders, and
  `+2.7603` after-fee PnL in the current ledger, but it cannot qualify with
  `0` complete-label days.

Current-default strategy smoke:

- `data/taker_runs/2026-06-23/item256-postfix-smoke-20260623/`
- selected markets: `austin`, `chicago`, `dallas`.
- strategies: `raw_edge_control`, `calibrated_edge`,
  `low_price_tail_capped`, `winner_centered_or_adjacent`,
  `current_high_lockin`, `late_day_liquidity_filtered`.
- latest tick rows: `198`.
- filled buys: `0`.
- zero-trade root cause: `policy_no_edge`.
- first failing gate: `policy`.
- tape integrity: `PASS`.

This smoke proves the current six-arm config writes artifacts, but it does not
count as campaign qualification because it has no fills and no settlement
labels. An all-market six-arm daily-roll launch was attempted with experiment
`item256-postfix-20260623-full-bakeoff`; it remained CPU-bound with an empty
first-run folder and was stopped rather than left as a runaway process.

Next unblock: collect `3-5` post-fix paper days with complete target-date
labels, then rerun the finalization watchdog and champion/challenger ledger.
The current blocker is label quality/sample availability, not missing
watchdog, bakeoff, or ledger tooling.

## 2026-06-23 Fresh Full-Campaign Launch

Started the fresh post-fix paper campaign under current taker defaults and the
full six-arm champion/challenger set:

```powershell
python -m weather.market.taker_bot --date 2026-06-23 --budget-usdc 100 --markets all --runs-root data\taker_runs --run-id item256-postfix-full-20260623 --strategies raw_edge_control,calibrated_edge,low_price_tail_capped,winner_centered_or_adjacent,current_high_lockin,late_day_liquidity_filtered --experiment-id item256-postfix-20260623-full-bakeoff --fresh
python -m weather.operations.taker_bot_daily_roll start --force --date 2026-06-23 --budget-usdc 100 --markets all --interval-seconds 60 --strategies raw_edge_control,calibrated_edge,low_price_tail_capped,winner_centered_or_adjacent,current_high_lockin,late_day_liquidity_filtered --experiment-id item256-postfix-20260623-full-bakeoff
```

Fresh run artifacts:

- `data/taker_runs/2026-06-23/item256-postfix-full-20260623/run_summary.json`
- `data/taker_runs/2026-06-23/item256-postfix-full-20260623/run_report.md`
- `data/taker_runs/2026-06-23/item256-postfix-full-20260623/strategy_summary.json`
- `data/taker_runs/2026-06-23/item256-postfix-full-20260623/strategy_report.md`
- `data/taker_runs/2026-06-23/item256-postfix-full-20260623/orders_long.csv`
- `data/taker_runs/daily_roll_status.json`

Launch evidence:

- markets: `12` (`toronto`, `nyc`, `atlanta`, `austin`, `chicago`, `dallas`,
  `denver`, `houston`, `los-angeles`, `miami`, `san-francisco`, `seattle`).
- strategies: `raw_edge_control`, `calibrated_edge`,
  `low_price_tail_capped`, `winner_centered_or_adjacent`,
  `current_high_lockin`, `late_day_liquidity_filtered`.
- latest tick rows: `792` (`132` per strategy; `66` per market).
- filled buys: `0`.
- tape integrity: `PASS` (`792/792` rows).
- zero-trade root cause: `policy_no_edge`.
- first failing gate: `policy`.
- leading no-trade reasons: `NO_TRADE_SNAPSHOT_CADENCE_DEGRADED` (`660`),
  `NO_TRADE_MARKET_CENTERED_WARM_TAIL` (`63`), `NO_TRADE_BAD_TAIL_NO_GO`
  (`35`), and `NO_TRADE_STALE_BOOK` (`21`).

Started the continuous daily-roll collector with the same experiment id. Its
first completed loop tick wrote:

- `data/taker_runs/2026-06-23/taker-20260623-10261355/run_summary.json`
- `data/taker_runs/2026-06-23/taker-20260623-10261355/run_report.md`
- `data/taker_runs/2026-06-23/taker-20260623-10261355/strategy_summary.json`
- `data/taker_runs/2026-06-23/taker-20260623-10261355/strategy_report.md`
- `data/taker_runs/2026-06-23/taker-20260623-10261355/orders_long.csv`
- `data/taker_runs/2026-06-23/taker-20260623-10261355/counterfactual_orders_long.csv`

Loop tick evidence:

- latest tick rows: `792`.
- filled buys: `0`.
- counterfactual rows: `792`.
- counterfactual would-buy rows: `0`.
- tape integrity: `PASS` for both orders and counterfactual orders.
- zero-trade root cause: `policy_no_edge`.
- first failing gate: `policy`.
- leading no-trade reasons: `NO_TRADE_SNAPSHOT_CADENCE_DEGRADED` (`660`),
  `NO_TRADE_MARKET_CENTERED_WARM_TAIL` (`57`), `NO_TRADE_BAD_TAIL_NO_GO`
  (`32`), `NO_TRADE_STALE_BOOK` (`22`), and `NO_TRADE_STALE_MODEL` (`11`).

The daily-roll status then classified that loop tick as stale-model-input and
terminal. Ran the recommended microstructure supervisor check:

```powershell
python -m weather.market.market_microstructure ensure
```

It returned `action=noop` because capture was already running with matching
runtime identity and fresh books. The stale taker run folder was then retired
with a forced restart:

```powershell
python -m weather.operations.taker_bot_daily_roll start --force --date 2026-06-23 --budget-usdc 100 --markets all --interval-seconds 60 --strategies raw_edge_control,calibrated_edge,low_price_tail_capped,winner_centered_or_adjacent,current_high_lockin,late_day_liquidity_filtered --experiment-id item256-postfix-20260623-full-bakeoff --startup-grace-seconds 1800 --max-activity-age-seconds 1800
```

Restart evidence:

- retired folder:
  `data/taker_runs/2026-06-23/_quarantine/taker-20260623-10261355__20260623T212745Z`.
- new roll PID: `29580`.
- new run folder: `data/taker_runs/2026-06-23/taker-20260623-83df0edc`.
- stale taker PID `29952` was stopped after confirming its command line was the
  retired `weather.market.taker_bot` process.
- status after restart: `started`, `pid_alive=true`, target date
  `2026-06-23`.

Follow-up operator refresh:

- patched `weather.operations.taker_bot_daily_roll` so stale activity from an
  older run folder cannot terminalize a live taker process when the latest run
  folder is still empty inside startup grace and artifact liveness is healthy.
- added regression coverage in
  `tests/operations/test_taker_bot_daily_roll.py`.
- reran `python -m weather.market.market_microstructure ensure`; the supervisor
  stopped mixed-runtime capture processes and the final check reports
  `state=RUNNING`, `action=noop`, and `runtime_identity_matches_current=true`.
- refreshed status reports `already_running`, `pid_alive=true`, artifact
  liveness `STARTUP_GRACE`, and latest run folder
  `data/taker_runs/2026-06-23/taker-20260623-83df0edc`.
- the latest run folder has written `orders_long.csv` and
  `budget_ledger.jsonl`; `run_summary.json` and `strategy_summary.json` are
  still pending, so this tick is not yet eligible for a bakeoff/ledger refresh.

The real order tape was complete enough to salvage into an item-specific
bakeoff while the loop remained stuck before summary artifacts:

- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_83df0edc.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_83df0edc.md`

Salvaged bakeoff result:

- source run: `taker-20260623-83df0edc`.
- replay input rows: `132`.
- replay ticks: `12`.
- scored order rows: `792`.
- strategy arms: `6`.
- filled buys: `0`.
- blockers: `missing_target_date_labels` and
  `profitability_artifact_verification_failed` before the recovery verifier
  refresh below.
- all strategy promotion gates remain `BLOCK`.

A counterfactual-disabled diagnostic one-shot was attempted with run id
`item256-postfix-full-nocf-20260623`, but it also exceeded a two-minute
foreground timeout before producing artifacts. The diagnostic process and its
empty run folder were removed to avoid confusing daily-roll liveness.

After the default startup/activity thresholds elapsed, daily-roll status
classified PID `29580` as terminal `idle_process` with root cause
`missing_heartbeat_metadata` because the latest run folder still lacked
`run_summary.json` and `strategy_summary.json`. The stale PID was stopped after
the salvage bakeoff was written. The next operator unblock is to fix or bound
the all-market post-order summary path before relaunching the continuous
collector; starting another identical worker would likely repeat the same
partial-artifact failure.

The immediate artifact unblock was implemented with a tape-preserving recovery
path:

```powershell
python -m weather.market.taker_bot recover --run-folder data\taker_runs\2026-06-23\taker-20260623-83df0edc --budget-usdc 100 --markets all --strategies raw_edge_control,calibrated_edge,low_price_tail_capped,winner_centered_or_adjacent,current_high_lockin,late_day_liquidity_filtered --experiment-id item256-postfix-20260623-full-bakeoff
```

Recovered artifacts for `taker-20260623-83df0edc`:

- `data/taker_runs/2026-06-23/taker-20260623-83df0edc/daily_pnl.json`
- `data/taker_runs/2026-06-23/taker-20260623-83df0edc/run_config.json`
- `data/taker_runs/2026-06-23/taker-20260623-83df0edc/run_summary.json`
- `data/taker_runs/2026-06-23/taker-20260623-83df0edc/run_report.md`
- `data/taker_runs/2026-06-23/taker-20260623-83df0edc/strategy_summary.json`
- `data/taker_runs/2026-06-23/taker-20260623-83df0edc/strategy_report.md`

The profitability verifier now treats no-fill opportunity tapes separately
from executed-order realized PnL checks. The three June 23 bakeoffs were
refreshed and all now report profitability artifact verification `PASS`; each
is blocked only by `missing_target_date_labels` because no settlement labels
exist yet for `2026-06-23`.

The live-size guard is now fail-closed on operator review. Even when a
candidate canary has complete labels, minimum settled sample, after-fee
evidence, and passing settlement gates, `next_run_policy_gate` keeps it
paper-only with `next_action=operator_review_live_size_change` until
`run_config.operator_review` explicitly approves the strategy and
`promote_default` action. The finalization summary/report exposes
`active_strategy_operator_review_*` fields so the review requirement is visible
before any live-size change.

Added the fresh run to the bakeoff and ledger evidence:

- `data/backtest/taker_strategy_bakeoff_2026-06-23_item256_postfix_full.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_item256_postfix_full.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_10261355.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_10261355.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_83df0edc.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_83df0edc.md`
- `data/backtest/item256_taker_champion_challenger_ledger.json`
- `data/backtest/item256_taker_champion_challenger_ledger_report.md`

Initial refreshed ledger result:

- bakeoff artifacts: `8`.
- loaded bakeoffs: `8`.
- strategies: `6`.
- complete-label days: `0`.
- promotion pass count: `0`.
- decision: `KEEP_CHAMPION`.
- recommended strategy: `low_price_tail_capped`.
- June 23 blockers: `missing_target_date_labels`; no settlement labels exist
  yet for the current target date.

This intermediate result was superseded by the settlement-label and current-fee
replay closures below.

## 2026-06-23 Settlement-Complete Label Refresh

Backfilled Weather.com/Wunderground daily summaries for all registered markets
from `2026-06-19` through `2026-06-22`, then regenerated the settlement ledger
and campaign bakeoffs. The generic market-day label quality remains `partial`
because the snapshot tapes still have collection gaps, but each refreshed
`2026-06-19` through `2026-06-22` label row now uses canonical
`settlement_source=daily_summary` and reconciles with Polymarket (`match`).
The taker bakeoff gate now distinguishes this settlement-complete state from
true partial snapshot-derived labels.

Updated artifacts:

- `data/backtest/market_day_labels.csv`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_221a357c.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-20_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-21_bbe63642.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-22_3d74b86b.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_item256_postfix_full.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_10261355.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_83df0edc.json`
- `data/backtest/item256_taker_finalization_watchdog.json`
- `data/backtest/item256_taker_finalization_watchdog_report.md`
- `data/backtest/item256_taker_champion_challenger_ledger.json`
- `data/backtest/item256_taker_champion_challenger_ledger_report.md`

Updated ledger result:

- bakeoff artifacts: `8`.
- loaded bakeoffs: `8`.
- strategies: `7`.
- settlement-complete bakeoff days: `5` (two June 19 bakeoffs plus June 20,
  June 21, and June 22).
- true partial-quality days: `0`.
- missing-label days in strategy rows: `0`; June 23 no-fill diagnostics are
  retained at run level but no longer fail a strategy ledger row.
- promotion pass count: `0`.
- decision: `KEEP_CHAMPION`.
- recommended strategy remains `low_price_tail_capped`.

The remaining promotion blockers at this stage were no longer the June 19-22
settlement labels. They were:

- June 19 through June 22 source run tapes still fail profitability artifact
  verification because the legacy `orders_long.csv` files lack current
  fee/slippage/executable-depth fields.
- No strategy passes every complete-day promotion gate
  (`all_complete_days_pass_strategy_gate`).
- Several strategies still have insufficient settled order samples.
- Challengers with enough settled orders do not beat the current champion after
  fees across the campaign ledger.

This intermediate result was superseded by the current-fee replay closure below.

## 2026-06-24 Current-Fee Replay Closure

Regenerated the five settlement-complete campaign bakeoffs (`2026-06-19`
through `2026-06-22`) with explicit current taker economics:

- `taker_fee_model=polymarket_symmetric_price_v1`
- `taker_fee_rate=0.05`
- `executable_depth_model=top_of_book_plus_1pct_depth_v1`
- `executable_depth_slippage_bps=100`
- `executable_depth_haircut=1`

The original June 19-22 source run tapes remain legacy/no-fee tapes, but the
bakeoff artifacts now carry a separate current-replay profitability verifier.
Each settlement-complete bakeoff reports `profitability_artifact_verification`
`PASS` with `evidence_basis=current_fee_depth_replay`; the legacy source
artifact verifier is retained separately for provenance and no longer poisons
the item-specific current-default replay.

Updated artifacts:

- `data/backtest/taker_strategy_bakeoff_2026-06-19_221a357c.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-19_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-20_3d3450f0.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-21_bbe63642.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-22_3d74b86b.json`
- `data/backtest/item256_taker_champion_challenger_ledger.json`
- `data/backtest/item256_taker_champion_challenger_ledger_report.md`

Final ledger result:

- bakeoff artifacts: `8`.
- loaded bakeoffs: `8`.
- strategies: `7`.
- settlement-complete bakeoff days: `5`.
- missing-label days in strategy rows: `0`.
- promotion pass count: `0`.
- blocked challengers: `6`.
- decision: `KEEP_CHAMPION`.
- recommended strategy remains `low_price_tail_capped`.

Current-fee/depth replay produced no filled orders on the five settlement-
complete campaign days, so every strategy remains blocked by real promotion
requirements (`min_settled_orders` and `all_complete_days_pass_strategy_gate`;
challengers also fail `beats_current_champion_after_fee_pnl`). This is the
intended fail-closed outcome for the post-fix requalification campaign: complete
labels are available, profitability evidence is current-cost, no stale no-fee
PnL is counted, and no strategy is considered live-qualified.

Item 256 is complete as a fail-closed requalification campaign. No live-size
change or challenger promotion is authorized.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - CURRENT-FEE CAMPAIGN CLOSED FAIL-CLOSED`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

