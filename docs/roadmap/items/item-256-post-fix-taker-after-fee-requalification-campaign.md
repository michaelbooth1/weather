# 256. Post-Fix Taker After-Fee Requalification Campaign [PARTIAL 2026-06-23 - CAMPAIGN STARTED, COMPLETE-LABEL DAYS BLOCKED]

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
- [ ] Require explicit operator review before any live-size change.

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

The daily-roll status still has PID `29952` alive. Its latest operator report
recommended microstructure freshness remediation for stale-model input; the
managed microstructure capture process is already running, so the remaining
action is to let the collector accumulate a fresh market tape rather than
starting duplicate taker workers.

Added the fresh run to the bakeoff and ledger evidence:

- `data/backtest/taker_strategy_bakeoff_2026-06-23_item256_postfix_full.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_item256_postfix_full.md`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_10261355.json`
- `data/backtest/taker_strategy_bakeoff_2026-06-23_taker_10261355.md`
- `data/backtest/item256_taker_champion_challenger_ledger.json`
- `data/backtest/item256_taker_champion_challenger_ledger_report.md`

Refreshed ledger result:

- bakeoff artifacts: `7`.
- loaded bakeoffs: `7`.
- complete-label days: `0`.
- promotion pass count: `0`.
- decision: `KEEP_CHAMPION`.
- recommended strategy: `low_price_tail_capped`.
- June 23 blockers: `missing_target_date_labels` and
  `profitability_artifact_verification_failed`; no settlement labels exist yet
  for the current target date.

Item 256 remains `PARTIAL`: the fresh campaign is now running and represented
in the ledger, but no strategy can be live-qualified until future post-fix days
settle with complete labels, enough fills, and positive after-fee/after-slippage
results.
