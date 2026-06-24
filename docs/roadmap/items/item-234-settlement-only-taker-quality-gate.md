# 234. Settlement-Only Taker Quality Gate [COMPLETE 2026-06-22 - MTM-ONLY QUALITY FAILS CLOSED]

Goal: make taker quality gates, daily learning, active strategy promotion, and
profitability claims fail closed unless the relevant PnL evidence is
settlement-scored.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
The audit found repeated MTM/settlement sign flips: June 21 reported
`+4401.81` MTM but settlement scoring gives `-56.31`, and a June 19 run
reported `+1238.75` MTM before finalizing to `-10.00`.

Why this matters: MTM rewards cheap losing tails before settlement and can make
a harmful strategy look promotable. Taker quality needs to learn from MTM as a
diagnostic, but only settlement-scored PnL can approve quality, promotion, or
profitability claims.

## Design

1. Require `pnl_evidence_status == SETTLEMENT_SCORED` before any taker quality
   gate can pass.
2. Exclude MTM-only rows from rolling net PnL used for daily learning,
   promotion, active default selection, and "profitable" labels.
3. Keep MTM visible as provisional telemetry with explicit sign-flip and
   settlement-pending diagnostics.
4. Add regression fixtures for large positive MTM that finalizes negative, and
   for positive MTM with zero settled orders.

- [x] Make taker daily-learning quality gates fail closed unless the run is
  settlement-scored.
- [x] Make active strategy promotion and rollback logic ignore MTM-only rolling
  net PnL.
- [x] Add sign-flip diagnostics comparing MTM PnL to settlement-scored PnL
  once labels arrive.
- [x] Add tests for the June 19 and June 21 shapes where MTM cannot pass a
  quality or promotion gate.

Acceptance: a taker run with positive MTM but missing or negative
settlement-scored PnL cannot pass quality, promotion, default-selection, or
profitability gates, and reports label MTM as diagnostic only.

Related: items 192, 209, 214, 237, 238, 240.

## 2026-06-22 settlement-only quality closeout

The taker quality path now uses settlement-scored rolling evidence only for the
quality gate sample:

- `quality_gate.rolling_run_count`, `rolling_filled_orders`, and
  `rolling_net_pnl_usdc` count only runs with
  `pnl_evidence_status == SETTLEMENT_SCORED`.
- MTM-only runs remain visible through `rolling_total_run_count`,
  `rolling_total_filled_orders`, `rolling_reported_net_pnl_usdc`,
  `rolling_mark_to_market_pnl_usdc`, and
  `rolling_provisional_mtm_run_count`, but cannot make the quality gate
  `PASS`.
- `quality_gate.evidence_basis` is explicitly `settlement_scored`.

Existing strategy scoring and finalization already enforce the other item
requirements: strategy comparison sets `promotion_evidence_basis` to
`settlement_scored`, keeps `mtm_promotion_allowed=false`, and only selects
`quality_candidate_countable` strategies from settlement-promotion gates.
Finalization reconciliation reports material MTM/settlement divergence and
sign-flip warnings, and canary promotion requires complete settlement-scored
labels plus settled-order sample gates before `promotion_eligible=true`.

I added a regression fixture with five positive MTM-only taker days and zero
settled orders. The rolling MTM total is positive, but the settlement-scored
quality sample remains zero and the gate does not pass.

Verification:

- `python -m pytest tests\reporting\test_trading_evidence.py tests\reporting\test_daily_learning.py tests\reporting\test_daily_progress_ledger.py -q`
  -> 33 passed.
- `python -m pytest tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py -q`
  -> 35 passed, 5 subtests passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - MTM-ONLY QUALITY FAILS CLOSED`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

