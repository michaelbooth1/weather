# Initial Market-Making Test Run Design

Date: 2026-06-14

This design turns the existing market-making research into the first operator
workflow: choose a target day and a total budget, then run one supervised
market-making process across the tracked weather markets for that day. The
first implementation should be shadow/paper by default. Live order placement
uses the same interface later, but only after the policy, paper trading, risk,
heartbeat, and account gates in roadmap items 43-45 pass.

## Operator Interface

The operator should start from one command:

```powershell
python -m src.market_making_run --date 2026-06-15 --budget-usdc 500 --mode shadow
```

Later live testing should require explicit extra flags:

```powershell
python -m src.market_making_run --date 2026-06-15 --budget-usdc 500 --mode live --pilot --confirm-live-orders
```

`src.market_making_run` should be a thin orchestration wrapper around the pure
policy module (`src.mm_policy` / `weather.market.mm_policy`), adding date
selection, run folders, budget ledgers, preflight gates, and the eventual
execution adapter.

The command owns one run folder:

```text
data/mm_runs/2026-06-15/<run_id>/
  run_config.json
  preflight.json
  quote_intents_long.csv
  budget_ledger.jsonl
  risk_events.jsonl
  fills_long.csv
  run_report.md
```

Tracked markets come from `market_registry.all_specs()`: Toronto, NYC, Atlanta,
Austin, Chicago, Dallas, Denver, Houston, Los Angeles, Miami, San Francisco,
and Seattle. For a target date, each market maps through `config_for_date()` to
the Polymarket event slug and local snapshot folder.

## Run Modes

`shadow` is the first test run mode. It computes quotes every tick, writes the
intent tape, updates simulated inventory and budget ledgers, and scores the run
afterward against CLOB book/trade tapes. It never loads wallet keys and never
posts orders.

`paper-live-forward` is a shadow run that stays active all day and is scored
nightly with the conservative fill simulator and queue-aware companion
simulator from roadmap item 44.

`live-pilot` is the later MM-2 mode. It can only post min-size, post-only orders
after all live gates pass. It still writes the same quote-intent and budget
tapes, with order IDs and user WebSocket fill lifecycle appended.

## Preflight

The run should refuse live mode, and warn in shadow mode, unless all required
inputs are current:

1. The target date has active Polymarket events for every selected market.
2. Snapshot folders exist for the target day and include model probabilities,
   source-status rows, CLOB token IDs, condition IDs, and CLOB book summaries.
3. `src.market_microstructure audit --strict` passes for selected markets.
4. Observation-trigger/watchdog health is fresh.
5. Promotion state is available from `f_family_promotion_refresh.json` and
   related Toronto gates.
6. Current reward/min-size/tick metadata is fetched from Gamma/CLOB/rewards
   endpoints and written to `preflight.json`.
7. For live mode only: account platform, jurisdiction, wallet type, allowances,
   pUSD/USDC balance, heartbeat behavior, cancel-all, post-only rejection, and
   user WebSocket lifecycle have been verified for the operating account.

The current local check on 2026-06-14 did not pass strict CLOB audit for all 12
markets because several later markets had stale trailing book captures. That is
acceptable for design work and shadow development, but it is a hard live-order
blocker.

## Policy Scope For The First Run

The initial policy should be harvest-only across the fleet. Even where a market
has a promotion-pass signal, edge quoting stays disabled in the first operator
workflow. The goal is to validate quote generation, budget accounting, stale
input pulls, and paper markouts before taking model-skewed risk.

Per band:

- Quote only active, open-order-enabled bands with current CLOB books.
- Prefer central bands with active rewards and useful volume.
- Skip tails unless a later recon report proves the reward and toxicity tradeoff
  is favorable.
- Represent two-sided no-inventory quoting as a YES bid plus a NO bid. Do not
  rely on naked SELL orders.
- Center harvest quotes on the market midpoint, not the model fair value.
- Use the model only as a veto: stand down when model-mid disagreement exceeds
  uncertainty and configured buffers.
- Use post-only prices rounded away from crossing after tick-size rounding.
- Stand down around stale sources, stale books, stale observation-trigger state,
  decisive observation windows, and fast CLOB moves that are not supported by
  our source state.

Every tick emits either a quote intent or a no-quote reason. Missing a quote is
not a silent failure; it is an auditable policy decision.

## Budget Semantics

The user budget is the bot's run risk budget, not a blind proxy for Polymarket's
order-validity checks.

Polymarket can accept open orders whose gross size exceeds wallet balance when
those orders are across different markets. The bot should model that correctly,
but it should not use exchange permissiveness as risk control. The design needs
two separate ledgers:

### 1. Exchange Validity Ledger

This ledger mirrors what Polymarket is likely to accept or reject:

- Group open orders by market/condition/token context, not by a single global
  "cash minus every open order" number.
- BUY orders reserve pUSD spend for that market context.
- SELL orders require conditional-token balance unless they are represented as
  complementary-token BUY orders.
- Across different market contexts, do not falsely subtract all open orders
  from one global exchange-available balance, because Polymarket does not apply
  that check uniformly across markets.

This ledger prevents the bot from predicting false rejections and lets it
operate across the weather fleet.

### 2. Run Risk Ledger

This ledger enforces the user's total budget across the whole selected day:

```text
run_budget = min(user_budget, dedicated_wallet_balance, configured_live_cap)

quote_size = min(
  reward_min_size_or_shadow_target,
  per_band_notional_cap,
  per_event_notional_cap_remaining,
  per_event_worst_case_cap_remaining,
  fleet_worst_case_cap_remaining,
  daily_loss_cap_remaining,
  exchange_validity_remaining
)
```

For the first run, `fleet_worst_case_cap_remaining` should be conservative:
assume all currently resting BUY intents can fill before cancellation and count
their max cash spend plus existing inventory risk. Later versions can add an
explicit open-order multiplier after live-forward paper data shows realistic
fill concurrency. The default live multiplier should be 1.0 until measured.

Event-level inventory should be represented as settlement P&L if each mutually
exclusive band wins:

```text
event_worst_case = max_loss_over_all_possible_settlement_bands(
  current_positions + resting_orders_assumed_filled
)
```

If this calculation is unavailable in v0, fall back to gross buy-order spend as
the live cap. That is capital-inefficient but safe for the first pilot.

## Allocation

Given a date and total budget:

1. Build the eligible quote universe across all tracked markets.
2. Estimate minimum two-sided capital per band as roughly `size` because a YES
   bid at `p` plus a NO bid near `1 - p` costs about one dollar per share if
   both fill.
3. Rank quote candidates by:
   - live data freshness,
   - promotion state and known-edge permissions,
   - reward campaign presence and min size,
   - centrality / tail risk,
   - book stability and spread,
   - recent casebook/toxicity exclusions,
   - market-level cap remaining.
4. Allocate min-size quotes until the run risk ledger binds.
5. Emit `budget_exhausted` no-quote rows for eligible candidates that did not
   fit. If the operator asked for all markets and the budget cannot support all
   of them at min size, the run should continue in shadow but live mode should
   require either a larger budget or an explicit partial-market pilot flag.

This keeps the user-facing workflow simple while making the budget behavior
deterministic and auditable.

## Live Order Adapter, Later

The live adapter should be a thin replacement for the shadow adapter:

- Maintain a CLOB heartbeat session and cancel-all on heartbeat, watcher, book,
  source, or user WebSocket failure.
- Place only post-only orders.
- Prefer short GTD expiries or aggressive cancel/replace cadence so stale
  quotes age out quickly.
- Reconcile intended quotes to actual open orders every tick.
- Cancel orders before replacing them when policy says stand down, budget binds,
  price would cross, or a source/observation event invalidates the quote.
- Record order IDs, lifecycle states, fills, rejects, and reserve deltas in the
  same run folder.

Day-one live protocol remains: heartbeat-lapse drill with a throwaway
far-from-mid order, min-size/tick/post-only rejection probes, then one tiny
two-sided quote on one band before scaling to multiple events.

## Reports And Acceptance

The run report should include:

- selected markets and unquoted markets with reasons,
- quote uptime by market/band,
- budget usage over time from both ledgers,
- stale-input pulls and latency-budget failures,
- conservative simulated fills,
- queue-aware companion fills,
- markouts at +30s, +1m, +5m, +30m, and settlement,
- reward/rebate estimates only after adverse-selection markout,
- final recommendation: keep shadow, narrow policy, or eligible for live-pilot
  review.

The initial test-run implementation is complete when a single date/budget
shadow run can cover all tracked markets, write a complete quote/no-quote tape,
produce a budget ledger that never exceeds the configured run risk budget, and
generate an end-of-day paper report without requiring live keys.
