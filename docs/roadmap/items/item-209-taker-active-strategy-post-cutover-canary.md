# 209. Taker Active Strategy Post-Cutover Canary [COMPLETE 2026-06-21 - CANARY LIFECYCLE GATES COMPLETE-LABEL PROMOTION]

Goal: keep the `low_price_tail_capped` taker arm as an explicit canary until
complete-label settlement evidence promotes it, blocks it, or rolls the active
default to a safer arm.

Source: item 192 correctly stopped the active-paper taker bot from using the
unsafe raw-edge default after the June 20 warm-tail loss. The new active
default is `low_price_tail_capped`, but the June 20 bakeoff was still globally
blocked by `partial_target_date_labels`, and item 166 says no strategy can be
promoted from that partial-label bakeoff alone. The current next-run policy
gate can pass an explicit non-raw active arm without proving complete-label
promotion.

Why this matters: cutting away from raw edge was a necessary risk reduction,
but a candidate arm should not silently become a permanent default without a
settlement-scored canary window, complete labels, and rollback criteria. The
operator needs to see whether the active arm is `canary`, `promoted`, or
`blocked`.

## Design

1. Add an active-strategy lifecycle field for taker runs: `candidate_canary`,
   `promoted_default`, `blocked`, or `manual_override`.
2. Require complete-label bakeoff evidence over a minimum rolling sample before
   a canary arm can become `promoted_default`.
3. Keep partial-label or unresolved bakeoffs useful for risk reduction, but do
   not let them mark the active default as promoted.
4. Add rollback/block rules when complete-label settlement shows negative ROI,
   excessive drawdown, stale-mark sign flips, or concentration failures.
5. Surface canary age, sample size, and next action in daily progress and taker
   finalization reports.

- [x] Add taker active-strategy lifecycle/status fields to run config and
  reports.
- [x] Gate `low_price_tail_capped` promotion on complete-label settlement
  evidence and rolling sample size.
- [x] Add next-run rollback/block logic for failed canary evidence.
- [x] Record canary sample counts in daily progress.
- [x] Add tests covering partial-label canary evidence versus complete-label
  promotion.

Acceptance: `low_price_tail_capped` can continue as a risk-reduction canary,
but reports cannot call it promoted until complete-label settlement evidence
passes the configured sample, ROI, drawdown, mark-sanity, and concentration
gates.

Completion notes (2026-06-21):

- Added active-strategy lifecycle fields to taker run config, run summaries,
  taker finalization, trading evidence, and daily progress ledger outputs.
- `candidate_canary` promotion now requires complete-label settlement evidence,
  configured settled-order sample, passing settlement ROI/drawdown/mark sanity
  gates, and concentration gates; failed complete-label evidence blocks or
  rolls back to the best passed safer arm.
- Partial-label bakeoffs remain useful for risk reduction but keep
  `low_price_tail_capped` in `candidate_canary` with next action
  `continue_canary_until_complete_labels`.
- Verified with:
  `python -m pytest tests\market\test_taker_bot.py tests\reporting\test_daily_progress_ledger.py -q`
  and
  `python -m pytest tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py tests\reporting\test_daily_progress_ledger.py tests\reporting\test_daily_learning.py tests\operations\test_schema_registry.py -q`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - CANARY LIFECYCLE GATES COMPLETE-LABEL PROMOTION`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

