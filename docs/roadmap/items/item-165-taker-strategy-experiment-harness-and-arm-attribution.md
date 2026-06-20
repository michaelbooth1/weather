# 165. Taker Strategy Experiment Harness And Arm Attribution [OPEN]

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

- [ ] Define the taker strategy registry schema and default
  `raw_edge_control` arm.
- [ ] Extend taker tapes and finalization artifacts with strategy attribution.
- [ ] Add a multi-arm paper mode that shares inputs but isolates budgets,
  positions, and scoring by arm.
- [ ] Add a daily strategy comparison report and tests covering control versus
  candidate attribution.
- [ ] Wire the best current arm into daily progress as a strategy-quality
  candidate only when its sample is settlement-scored and countable.

Acceptance: the taker bot can run at least two named strategy arms on the same
active-day inputs, every row can be traced back to its arm and experiment, and
daily/settled reports compare the arms without relying on policy-hash
guesswork.

