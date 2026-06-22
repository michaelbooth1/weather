# 238. Daily Taker Full-Bakeoff Champion/Challenger Loop [COMPLETE 2026-06-22]

Goal: run a full daily taker strategy bakeoff on the same market inputs, then
settlement-score every strategy before choosing the next champion.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
Single-strategy daily runs made it difficult to compare alternatives on June 21
and encouraged an active switch from sparse, partial-quality bakeoff evidence.

Why this matters: one-arm runs can hide whether the chosen strategy is actually
better than no-trade, the market baseline, or a narrower challenger. The bot
needs a repeatable champion/challenger loop with settlement-scored
counterfactuals.

## Design

1. Run all configured bakeoff strategies daily on the same snapshots and order
   book inputs, including the active strategy as champion.
2. Settlement-score each strategy by market, local hour, current-high distance,
   tail flag, source state, and strategy family.
3. Maintain a champion/challenger ledger with settled PnL, after-fee PnL,
   drawdown, fill count, market count, unresolved-order count, tail fraction,
   and MTM/settlement sign flips.
4. Promote only with out-of-sample settlement evidence and enough comparable
   days, not from a single promising partial run.

- [x] Wire daily roll to run the full `DEFAULT_BAKEOFF_STRATEGIES` set in paper
  or shadow mode.
- [x] Add same-input strategy comparison reports before the next-day active
  policy selection.
- [x] Add a champion/challenger ledger with settlement-scored multi-day
  thresholds.
- [x] Add promotion tests where a partial-quality winner cannot dethrone the
  champion.

Acceptance: every active taker day produces a same-input strategy comparison
that is settlement-scored before next-day policy selection, and active
promotion requires multi-day out-of-sample evidence.

Related: items 209, 214, 234, 237, 240, 241.
