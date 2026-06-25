# 303. Post-Settlement Taker Zero-Fill Evidence And Artifact Canonicalization [COMPLETE 2026-06-24 - ZERO-FILL DAYS AND PRE-LABEL BAKEOFFS NOW PRODUCE CANONICAL POST-SETTLEMENT EVIDENCE]

Goal: make zero-fill taker days post-settlement auditable, current, and
distinguishable between valid no-edge policy behavior and infrastructure
blockers.

Source: settled 2026-06-23 log audit. June 23 taker runs produced zero fills
and zero PnL, with skips dominated by snapshot cadence degradation, stale book,
market-centered warm-tail, bad-tail no-go, price/out-of-range, and current-high
trust gates. That was risk-clean, but the generated bakeoff artifacts were
created before labels finalized and still reported missing target-date labels.
Daily learning also expected canonical taker watchdog/casebook outputs that
were absent or date-specific only.

Why this matters: a zero-fill day can be a good outcome if every skipped trade
was invalid after fees and risk gates. It can also hide broken books, stale
inputs, missing labels, or disabled strategy arms. The daily learning stack
needs to tell those apart and should not keep stale pre-label reports after
labels have settled.

Why it is not already covered: items 234 through 241 and 283 through 285 define
the taker quality, settlement, fee, and permission gates. Items 272 through 276
cover liveness and counterfactual tapes. None guarantees that a zero-fill day
gets regenerated after labels finalize, emits canonical daily artifact names,
and decomposes no-trade evidence into `policy_no_edge` versus infrastructure
blockers.

## Design

1. Regenerate taker bakeoffs and finalization reports after settled labels are
   present, even when fills are zero.
2. Emit canonical daily `taker_finalization_watchdog` and `taker_tail_casebook`
   artifacts with stable filenames, plus date-specific detail artifacts.
3. Split no-trade reasons into policy gates, market/book infrastructure gates,
   data freshness gates, and strategy-disabled gates.
4. Mark a zero-fill day as `risk_clean_no_edge`, `infra_blocked`, or
   `unscored_stale_labels` rather than only reporting zero PnL.
5. Feed the classification into daily learning, trading evidence, and taker
   requalification reports.

- [x] Add a post-settlement taker regeneration step for zero-fill and filled
  days.
- [x] Write canonical watchdog and tail-casebook artifacts every target day.
- [x] Add no-trade reason taxonomy and daily counts by category.
- [x] Add zero-fill quality classification to taker daily PnL/evidence reports.
- [x] Add tests for pre-label bakeoff refresh, zero-fill risk-clean days, and
  zero-fill infrastructure-blocked days.

Acceptance: a settled zero-fill taker day has fresh post-label bakeoff and
finalization artifacts, stable canonical watchdog/casebook outputs, an explicit
reason taxonomy, and a quality classification that daily learning can consume
without treating stale labels or missing artifacts as valid no-edge evidence.

Related: items 234, 235, 236, 238, 239, 240, 241, 256, 272, 273, 274, 275, 276, 283, 284, 285, 294.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - ZERO-FILL DAYS AND PRE-LABEL BAKEOFFS NOW PRODUCE CANONICAL POST-SETTLEMENT EVIDENCE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

