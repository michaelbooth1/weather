# WS-2 negRisk structural-arbitrage scan — development evidence

G2 is **NOT EVALUATED**. The full census has not run. No real-data opportunity
counts, best cases, rule-out result or latency-survival estimate can be reported.
The exact v3 scanner is prepared for master review; execution waits for explicit
GO under `C:\t\codex\COMMON.md`. No preregistration has been drafted or frozen.

## Scope and evidence

The fixed pre-read inventory lists 900 event-days, 12 cities and 75 target dates,
2026-08-01 through 2026-10-14 inclusive, with 44,891,293,020 bytes of book summaries.
Only `order_books_summary.csv` is opened, from these task-authorized roots:

- `C:\t\recopy-20261106\tapes-toronto-0801-0929`
- `C:\t\recopy-20261106\tapes-us-0801-0929`
- `C:\t\recopy-20261106\events-0930-1014`

The input plan, method, scripts, source archives, light controls and receipts are
under `C:\t\codex\T003\out\`. `inventory.json` enumerates every input path.
`REVIEW_REQUEST.md` under `C:\t\codex\T003r1\` binds the commit and script SHA.
No outcomes, labels, execution tapes, maker shadow or guarded-date payloads are read.
The earlier note is archived as `out\findings-note-pre-B010.md` for provenance.

## Mechanics and measurement

The [official adapter](https://github.com/Polymarket/neg-risk-ctf-adapter/blob/main/src/NegRiskAdapter.sol)
converts selected NO positions into complementary YES positions and, for m selected
NO positions, m−1 units of collateral. A conversion fee can apply. Reverse conversion
is not assumed. The scan checks full YES and NO sets in both directions, permitted
NO-subset conversion routes, mixed direct/synthetic YES routes and binary pairs.
Linked routes require complete integer partition geometry; missing/blocked band
indices are recorded per capture.

The [official fee schedule](https://docs.polymarket.com/trading/fees) supports the
requested weather taker curve `0.05*p*(1-p)`; maker fees are zero. The
[order documentation](https://docs.polymarket.com/trading/place-orders) supplies the
constraints. Captured minimum sizes and supported ticks are checked on selected
legs. Quantities are 1, 10 and 100, plus 5 at top depth to catch a minimum-lot
opportunity that disappears at ten.

Summaries retain top prices/depth and 10/100-share VWAPs, not individual fills.
Nonlinear fee costs therefore use conservative/optimistic bounds when walking depth.
A missing walk is unresolved. Capacity at best and an all-depth ceiling are reported;
neither establishes profitability at untested quantities. Adapter fee zero is an
optimistic screen, conditional on later group identity and feeBips verification.

The capture timestamp is assigned before fetching books. Source-book windows of
1/5/30/60 seconds are sensitivity screens, not measured simultaneity. Route optimization
happens within each selected-leg window. Consecutive positive samples are counted,
with sampled spans and continuous-duration lower bound zero. The summaries do not
provide HTTP receipt timing or measured observation-to-order latency. An executable
G2 verdict requires those receipts and historical terms; its count remains null.

## B010 re-check and light validation

The previous scanner could discard a valid route because an unselected book was
missing, off-grid or stale. It could also miss a timely alternative by filtering
only an unconstrained optimizer's winner. V3 checks selected legs and optimizes
both fee bounds within each window. Independent exhaustive enumeration passes 576
small subset/window comparisons; a numeric YES-set control returns +3.76 at q10.

Other fixes: streaming hours/episodes; cooperative runtime/output bounds; explicit
unresolved values; aware UTC/local-time checks; strict CSV schema; two-pass input
hashes; staged publication with completion JSON last; verified artifact hashes;
retained interrupted attempts; and fatal-error versus resource-retry separation.

The real-schema control reads 15,031 bytes from the first Toronto August 1 capture,
retains 22 rows, and confirms a complete partition. It is excluded from census counts.
Final-script controls and peak working memory are in `out\b010_recheck_receipt.json`.
They use far below the 500 MB light-work limit. No heavy invocation has started.

Fee-source correction: the current official
[V2 trading implementation](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol)
charges BUY fees in collateral and deducts SELL fees from collateral proceeds.
Its [fee module](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Fees.sol)
also denominates fees in collateral. The earlier V1 helper caveat did not establish
current deployment terms. The task's additive collateral-fee model is retained;
historical deployment, adapter fees and rounding still require verification.

The earlier self-review/pin did not constitute master GO. The prior supervisor is
absent, and the replacement cannot start automatically without an explicit reviewed
commit argument. The canonical wrapper's memory/disk/lease checks are unchanged.

## Handoff and open questions

Master review and explicit GO are required before bounded bulk work. Then inspect
candidate margins, completeness, depth, measured capture timing and any available
latency receipts before deciding G2. A positive screen alone does not freeze T3.
If an executable case survives, draft strategy, unread forward dates, PASS and kill
rules for review, with no automatic freeze or live execution.

The master owns eventual findings/register and ledger updates. Publication follows
the latest COMMON.md deploy-key instruction, with a verified bundle retained. No merge.
