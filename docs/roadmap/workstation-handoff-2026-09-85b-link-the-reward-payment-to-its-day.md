# Workstation handoff 2026-09-85b — link the reward payment to its day under a reviewed rule

Written 2026-09-21 (night) by the production agent after accepting 85a (`codex/re1-payout-evidence-20260921` @
`045a100ed`, PR 82; qualified source `ba219032f`). 85a is accepted as specified: the collector is honest, the
distribution source is rightly `UNSUPPORTED` because the venue exposes no earned-day reference, and the actual
output is `INCONCLUSIVE`. That leaves the RE-1 test unable to conclude — ever — so this mission adds the missing
link under an explicit, reviewed, labelled rule. All 84a–85a boundaries bind unchanged; the execution worktree
`scratch\w\reward-test-attended-20260921` stays at `7e6e1709c` and is not touched.

## 1. The decision (production agent, 2026-09-21; the owner can veto)

The venue pays the day's liquidity rewards as one account-wide credit and publishes no record binding that credit
to the day. The activity-to-credit contract (`docs/operations/paid-credit-activity-evidence.md`) refuses equal-amount
and previous-day inference for its *pure bridge*, and that stays true for the bridge. For the RE-1 verdict a
separate, reviewed **producer** rule is adopted, `linkage_basis = "exact_amount_single_condition_unique_credit_v0.1"`,
because it is falsifiable from the file itself and any ambiguity degrades to `INCONCLUSIVE`, never to a wrong `PAID`
or a wrong `NOT_PAID`. It is a decision about RE-1 payout evidence only; it does not touch the pilot's financial
gates, the bridge, or any live authority.

## 2. The rule — implemented in `re1_payout_evidence.py`, not in the reconciler

For reward day `D` (accrual window `[D 00:00Z, D+1 00:00Z)`, cash window `[D 00:00Z, D+3 00:00Z)`), the collector
produces distribution rows only when **all** of the following hold, and records which one failed otherwise:

1. **Accruals are final and single-condition.** The accrual source is `OBSERVED` and `complete` (day closed, both
   asset totals present). Every pUSD accrual row for `D` is `ACCRUED` or `COMPLETED_ZERO`, and every *nonzero*
   accrual row for `D` — any asset — has `condition_id == scope.condition_id`. The account earned nothing in any other
   market that day, so the venue's aggregate payment cannot contain another condition's money.
2. **A > 0.** `A` = the sum of day-`D` pUSD accrual amounts quantized to micro-units (see §3).
3. **Candidates are joined activity+credit pairs.** From `/activity` (`REWARD` rows only, maker-scoped, pagination
   complete over `[D+1 00:00Z, min(cash_end, now))`) take each row's `transactionHash`; a candidate exists only when
   exactly one `CONFIRMED` pUSD wallet credit in the cash window carries that transaction hash (already collected
   by `collect_wallet`). An activity row with no matching credit, or with two, is retained as `unjoined` and the
   rule fails with `activity_credit_join_failed`.
4. **Exactly one candidate matches the amount.** `|C − A| ≤ 1` micro-unit, where `C` is the credit amount. Zero matches
   with candidates present → `no_amount_match`; two or more → `ambiguous_amount_match`. A mismatch is *reported* with
   both numbers (§4), never coerced.
5. **Nothing else in the window is unexplained.** Every other pUSD credit in the window must be a `REWARD`-joined
   candidate for another day or an explicit external credit the owner lists; unexplained credits leave the matcher's
   `wallet_credit_unattributed` unresolved and the verdict `INCONCLUSIVE` — that is correct, do not suppress it.

On success: one distribution row per pUSD accrual row of `D` (there is exactly one when rule 1 holds),
`status PAID`, `credit_id = 137:<tx>:<log_index>`, `amount = C`, `distribution_id = "reward-" + digest(D, tx,
log_index)[:48]`, `accrual_id` = the accrual's id, plus the extra keys `linkage_basis`, `activity_sha256`,
`activity_timestamp_utc`, `matched_amount_delta_units`. The distributions source becomes `status OBSERVED`,
`complete = pagination_complete = True`, `coverage_through_utc = min(cash_end, activity observation)`,
`payout_cycle_complete = True`.

`NOT_PAID` is reachable only one way: cash window closed at collection time, `A > 0`, **zero** `REWARD` activity rows
and **zero** credits of either asset in the window (USDC.e included). Then the distributions source is `OBSERVED`,
`complete`, `distributions=[]`; the matcher reports `UNPAID` and `paid = 0` legitimately. Any `REWARD` row, any
USDC.e credit, or any unmatched pUSD credit in the window forbids `NOT_PAID`: leave the source incomplete with the
reason and let the verdict stay `INCONCLUSIVE`.

## 3. Precision — a bounded consumer change is authorized

The venue reports earnings beyond six decimals; `INCENTIVE_AMOUNT_RE` refuses them and the whole file would be
`INVALID`. Fix it in two places and nowhere else:

- Producer: each accrual row's `amount` is the venue value quantized to micro-units with `ROUND_HALF_EVEN`; the
  unrounded string is kept beside it as `venue_amount`. Totals are compared at venue precision before quantizing.
- Consumer (`reconcile_incentive_payments`, the **only** authorized edit there): tolerate one micro-unit per
  accrual in `incentive_distribution_exceeds_accrual` and in the `PAID` / `PARTIALLY_PAID` decision, and record
  `rounding_tolerance_units: 1` in the result. Nothing else in the reconciler changes; its tests gain the two
  boundary cases (`A+1` accepted, `A+2` refused).

## 4. The human-readable answer, printed regardless of the verdict

`collect-payout` prints (and `collect-evidence` retains in the file) a `payout_diagnostics` block so the owner can
read the answer even when the matcher refuses: `reward_day`, `accrual_total_venue` (unrounded), `accrual_total_units`,
`other_condition_accruals` (count and total), `reward_activity_rows` (each: `timestamp_utc`, `transaction_hash`,
`amount`), `pusd_credits_in_window` and `usdc_e_credits_in_window` (each: `credited_at_utc`, `transaction_hash`,
`log_index`, `amount`), `linkage_rule_outcome` (the first failed rule from §2 or `matched`), and `cash_window_closed`.
Every value passes the secret guard. No inference in this block: it is a table of what was observed.

## 5. Tests (extend `tests/market/test_re1_payout_evidence.py`; the round trip is the test)

Build the sources from SDK 0.6.0 models and real-shaped `eth_getLogs` replies as 85a did, then, **without any
synthetic distribution fixture**, run the real collector → `reconcile_incentive_payments` → `payout_verdict`:

1. One `REWARD` row whose tx hash is one pUSD credit of `A` → `paid` is a number, `k` computed, `PAID_AS_MODELLED`,
   `linkage_basis` recorded. Same with `C = A − 1` micro-unit → still complete (`PARTIALLY_PAID`, `paid = C`).
2. Credit `A + 1` → accepted under §3; `A + 2` → `no_amount_match`, `INCONCLUSIVE`, the diagnostics show both numbers.
3. Two `REWARD` credits both equal to `A` → `ambiguous_amount_match`, `INCONCLUSIVE`.
4. A nonzero accrual in a second condition → rule 1 fails, `INCONCLUSIVE`; no split is attempted.
5. Window closed, no activity, no credits in either asset → `NOT_PAID`, `paid = 0`.
6. Window closed, no pUSD credit but one USDC.e credit → `INCONCLUSIVE`, `usdc_e_credits_in_window` non-empty.
7. A `REWARD` row whose tx hash has no credit (or two) → `activity_credit_join_failed`, `INCONCLUSIVE`.
8. One block chunk missing → `INCONCLUSIVE`, `paid None` (85a's case, kept).
9. The fake client still raises on every non-read method; no venue write path is reachable.

Keep 85a's existing tests; replace the "explicit synthetic distribution" control with case 1 (it is now real).

## 6. What not to do

- Do not modify `re1_attended.py`, `re1_resilience.py`, `re1_owner_checks.py`, `re1_transport.py`, the bridge
  `mm_paid_credit_activity.py`, or `paid-credit-activity-evidence.md` beyond one sentence pointing to this rule.
- Do not run `collect-evidence` with the owner's credentials; do not read the root `.env` (variable names only).
- Do not check this branch out into the execution worktree.
- Do not start a workstation full suite between 09:00 and 19:00 Eastern on 2026-09-22 (the live session). Focused
  tests and implementation are fine at any hour. The full suite runs after 19:00 or the next night.

## 7. Boundaries and report

Branch `codex/re1-payout-link-20260922` stacked on `045a100ed`, draft PR onto PR 82. Append a dated 85b section to
the same report: verdict first in bold; the rule as implemented with the exact field names; the nine cases and their
observed outputs; the consumer diff (it must be tiny — print it in the report); the updated owner run card
(`collect-evidence` on or after `D+3 00:00Z`, then `collect-payout … --payment-evidence <file>`); what was NOT done.
Update `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`'s 85a paragraph so it no longer says the collector
cannot prove paid rewards, and states the rule and its two `INCONCLUSIVE` escape hatches instead.

First session is 2026-09-22 (reward day `2026-09-22`); its cash window closes 2026-09-25 00:00Z, so this must be
merged into the evidence worktree and qualified before the owner runs `collect-evidence` on the morning of
2026-09-25 Eastern.
