# 165. Taker Strategy Experiment Harness And Arm Attribution [COMPLETE 2026-06-20 - MULTI-ARM ATTRIBUTION LIVE]

Goal: make taker-bot strategy tests explicit, auditable, and comparable instead
of inferring strategy differences from ad hoc policy hashes.

Source: the 2026-06-20 taker-bot log audit. The available logs contain two
policy hashes, `221a357c` and `3d3450f0`, but they are sequential policy
configurations rather than controlled A/B strategy arms. The order tape records
`policy_hash`, but it does not record `strategy_id`, `experiment_id`,
control/candidate arm, assignment rule, or the strategy family that generated a
fill.

Why this matters: a profitable or losing taker day cannot teach us which idea
worked unless every decision is tied to a named strategy arm and scored against
the same active-day and settlement evidence. Without arm attribution, repeated
fills and config drift can be mistaken for strategy learning.

## Design

1. Add a strategy registry for taker arms with stable IDs, descriptions,
   config payloads, owner, and status: control, shadow, active-paper,
   discontinued, or promoted.
2. Add `experiment_id`, `strategy_id`, `strategy_family`, `assignment_rule`,
   `control_strategy_id`, and `strategy_config_hash` to taker order rows,
   budget ledger events, run config, run summary, and settlement finalization.
3. Allow one daily taker process to evaluate multiple strategy arms on the same
   snapshot/book/model inputs while isolating budgets and positions per arm.
4. Keep the current raw-edge policy as `raw_edge_control` so every new strategy
   has a stable baseline.
5. Produce a daily strategy report with fills, spend, expected profit, MTM,
   settled P&L when available, concentration, stale-source/book blocks, and
   sample count by strategy arm.

- [x] Define the taker strategy registry schema and default
  `raw_edge_control` arm.
- [x] Extend taker tapes and finalization artifacts with strategy attribution.
- [x] Add a multi-arm paper mode that shares inputs but isolates budgets,
  positions, and scoring by arm.
- [x] Add a daily strategy comparison report and tests covering control versus
  candidate attribution.
- [x] Wire the best current arm into daily progress as a strategy-quality
  candidate only when its sample is settlement-scored and countable.

Acceptance: the taker bot can run at least two named strategy arms on the same
active-day inputs, every row can be traced back to its arm and experiment, and
daily/settled reports compare the arms without relying on policy-hash
guesswork.

## Completion - 2026-06-20

Implemented a registered taker strategy surface in `weather.market.taker_bot`:
`taker_strategy_registry_v0.1` defines `raw_edge_control`,
`small_order_probe`, and `strict_edge_probe`, with `raw_edge_control` as the
stable control arm.

Order tapes, settled tapes, budget ledger events, run config, run summary,
daily P&L, settled P&L, and daily-progress trading evidence now carry
`experiment_id`, `strategy_id`, `strategy_family`, `assignment_rule`,
`control_strategy_id`, and `strategy_config_hash`. Legacy rows without those
fields normalize to `raw_edge_control` for backward-compatible reporting.

`python -m weather.market.taker_bot` now accepts `--strategies` and
`--experiment-id`. A single run discovers snapshot/book/model inputs once, then
applies each selected arm with isolated budgets, positions, and scoring. The
daily-roll launcher can pass the same strategy arguments.

Each run writes `strategy_summary.json` and `strategy_report.md`, and
settlement finalization writes `settled_strategy_summary.json` and
`settled_strategy_report.md`. The reports compare arm-level fills, spend,
independent opinions, settled/unsettled counts, settlement P&L, MTM P&L, net
P&L, and countability. Daily progress records the best strategy and only marks
a taker strategy-quality candidate when a settlement-scored arm is countable.

Verification:

- `python -m pytest -q tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_progress_ledger.py tests\operations\test_schema_registry.py`
  -> `29 passed`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - MULTI-ARM ATTRIBUTION LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

