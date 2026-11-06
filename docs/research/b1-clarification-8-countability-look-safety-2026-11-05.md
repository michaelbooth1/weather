# B-1 Clarification 8: outcome-blind countability and look-chain safety
Master ruling, dated 2026-11-05 22:30 ET. **Outcome-blind:** no promotion_countable flag, ledger row, label, price or MG-2 output for any date ≥ 10-29 was read in making it. Basis: audit 2026-11-05, findings A2 and A3, traced by master in the code. It changes no estimand, arm, label source, interval, PASS/FAIL/INCONCLUSIVE rule, N, D0 or market set. Under the owner's 11-05 definition, B's verdict is a diagnostic, not edge.

## 1. Countable dates (replaces the reconciliation part of T1)
**Defect.** From 10-23 the venue pays on the highest routine METAR, but the settlement ledger's bucket is WU (settlement_ledger.py:539-563; Stage A stays WU until after B). `promotion_countable` requires `reconciliation_status == "match"` against the venue winner (settlement_ledger.py:55, :334-341, :704-735). So every market-day where WU and the venue rule disagree drops B's whole date (b_transfer T1: all 10 markets). This selects on the outcome exactly where the rule switch matters. At the pre-cutover routine-vs-WU disagreement rate (9/626 station-days), it pushes B's 45th date past 12-16 with probability ≈ 0.8. That changes B's candidate (the 13-16 slot becomes MG-1), and its dates run into the row-28b ≥ 12-17 line.
**Ruling.** For B, a market-day is countable if and only if all three conditions hold, each decided from keys, metadata and timing only:
(1) its material coverage grade is in MATERIAL_COUNTABLE_COVERAGE_GRADES;
(2) its event is closed with exactly one winning market (that a winner exists, not which band won);
(3) a venue-rule label key exists in the look-morning frozen manifest's label_dates.
The reconciliation status against WU is NOT a condition. It is recorded per market-day in the transfer manifest and reported at the look as a count only. Unchanged: a date counts only if all 10 market-days count, and the 45th date is fixed before any label value is read (T2/T3).
**Disclosed sensitivity, at the look, non-deciding:** Δ re-computed on the market-days where our venue-rule label bucket equals the venue's winning market, with the number of excluded cells reported.

## 2. Look-chain safety: one look must yield one verdict or be held, never wasted
**Defect** (traced):
- b_scorer.py:398-407 writes the consumed marker before the late VOID checks;
- b_look_wrapper.py:26-28 lets VOID 5 spend the look;
- b_scorer.py:780-790 builds the decision and the log-pool secondary in one expression, so an exception in a secondary loses the verdict;
- the MG-1 entry pin is unset (b_look_wrapper.py:82).
**Ruling** (built through the S0→S1 entry-edit path; the decision logic is unchanged):
1. **Preflight before the marker.** VOID 5's MG-1 receipt checks (schema, body sha, entry sha against the recorded pin, manifest binding), the existence of the --transfer directory and every input path move into the wrapper preflight. A preflight failure refuses and spends nothing.
2. **Decision first.** decide(rows_b) is computed and written to the receipt (mode "x") before any secondary. Each secondary runs in its own guard. An exception is recorded in the receipt and never discards the verdict.
3. **MG-1 cut-off.** If MG-1 has no look receipt by 2026-12-08 23:59 local, master writes a dated MG-1 abandonment receipt. Its sha is recorded in a further dated clarification before B's look, and B's preflight accepts it in place of the MG-1 receipt.
4. **Look-morning order.** B's transfer runs in the first admitted host window after Stage A has written the 45th date's ledger row. The R24 look freeze is taken once, in that same window, after that row exists. Expected on 12-14 or later; the look date was "12-13 at the earliest".
5. **Dress rehearsal by 12-01.** The full MG-1 → B chain (export, pull, emit, transfer, freeze, wrapper, scorer, receipt) runs on synthetic, dev-shaped inputs, at S1 and the exact pinned shas. It runs in a scratch root that cannot reach real look paths, and covers every refusal, hold and VOID path. A receipt goes to master.

## 3. Prose erratum (no rule change)
B §2's "normalised exactly as the dev scorecard's market arm does it" is wrong. The market arm is scored as captured, un-normalised (dev_scorecard.py:14-17, :143-147; b_price_coverage.py:67-83). The code is correct and unchanged. Disclosed, and deciding nothing: a ladder-normalised market Brier and the floor-only control (already computed, b_scorer.py:680-685), reported next to Δ at the look.
