# WS-2 negRisk structural-arbitrage scan — development evidence

G2 is **not met: execution remains unverified**. B012 approved v3 and its first
chunk completed 30 event-days / 113,136 snapshots. The controller stopped before
chunk 2 because projected storage exceeded the master's limit. The remaining
870 event-days have not been scanned. This partial screen is not a census rule-out.
No preregistration has been drafted or frozen. V4 requires separate review and GO.

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

## B012 first chunk and projection stop

Chunk 1 used the unchanged approved script, SHA-256
`b59dcce9cd53609860d3fb8338e2e3ba71ce2de827365ee1bb53d1206d8c9fc3`,
under allowlist commit `704b76cf692f505cb5a6ec285cd0cb1aa1c62e30`.
It scanned August 1–2 in all 12 cities and August 3 in Atlanta, Austin, Chicago,
Dallas, Denver and Houston. All 30 event geometries were complete partitions.

Elapsed wrapper time was 507.420 seconds; peak whole-job committed memory was
23,375,872 bytes. Event output was 77,458,482 bytes. Multiplying by 900/30 gives
2,323,754,460 bytes (2.164 GiB), above the 1.5 GiB stop limit. Projected finish,
including 60-second pauses, was November 6 at 21:12:55 America/Toronto, before
the November 7 16:00 runtime limit. Storage is the binding constraint. The canonical
wrapper returned zero and proved teardown; the controller then recorded
`B012_replan_required`. No second chunk or controller remains running.

Receipts: `out\B012-projection-20261106T2138404963444Z.json`,
`out\v3-receipt-20261106T213014366212Z-scan-0000.json`, and
`out\wrapped-v3-20261106T2130130536869Z.log`.

## Partial screen results, one headline quantity

Headline: **2 ANY-route positive_span1 episodes at q10**, called
**snapshot-coincident screen positives**. There are two under the 120-second rule
and two under a join over consecutive captures; these are the same two episodes,
not four. Both contain one observation, have sampled span and continuous-duration
lower bound zero, and have no measured latency-survival estimate.

| City / event date | Capture UTC | q10 fee-net lower..upper | Source span | Hour bin before nominal close |
| --- | --- | --- | --- | --- |
| Los Angeles / August 1 | 19:35:02.651704 | +0.106609..+0.107577 | 0.376 s | [-12,-11) |
| San Francisco / August 1 | 22:19:27.958278 | +0.050215619..+0.051428452 | 0.418 s | [-9,-8) |

Both selected `buy_yes_mixed`, with 11 CLOB legs. Los Angeles has buy cost 0.35,
sell proceeds 80.73, signed transformation cash -80 and fee cost
0.272423..0.273391; minimum top depth is 8 shares. San Francisco has buy cost 3.1,
sell proceeds 93.44344, transformation cash -90 and fee cost
0.292011548..0.293224381; minimum top depth is 3.44 shares. Thus q10 walks depth;
raw fills remain unavailable. Depth ceilings are not profit capacity guarantees.

At q1 both are below the minimum order size and ineligible. At q100 the same
mixed-route fee-net bounds are -37.546634415..-36.885831140 for Los Angeles and
-69.032231134..-67.729238455 for San Francisco. Optimized ANY at q100 instead
selects binary pairs and remains negative (-0.219950 and
-0.982870084..-0.971634180 respectively). These are separately sized diagnostics,
not additions to the headline count.

The next q10 ANY screen is negative after 15.045 s and 14.884 s respectively.
That does not establish continuous lifetime or survivability of measured order
latency. The charter's extra one-cent-per-leg diagnostic is also negative:
-0.993391 and -1.049784381. No positive is after nominal local-day close; actual
accepting-orders/closed status is absent, so midnight is a proxy, not venue proof.

The light streaming report is `out\B012-report-20261106T213856637241Z\summary.json`;
its CSVs contain city/day/hour counts, both episode definitions and close-hour bins.
`out\B012_case_details.json` contains size sensitivity and adjacent captures.
Tables are snapshot × route × size; never sum them across routes or sizes.
`positive_lower` and `positive_upper` are explicitly **without a timing window**.

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
Outputs expose buy cost, sell proceeds, signed transformation cash and per-leg
VWAP/fee bounds, depth and source timestamps for the selected route.

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
They use far below the 500 MB light-work limit. B012 subsequently authorized the
single bounded chunk described above; the pinned v3 bytes stayed unchanged.

Fee-source correction: the current official
[V2 trading implementation](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol)
charges BUY fees in collateral and deducts SELL fees from collateral proceeds.
Its [fee module](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Fees.sol)
also denominates fees in collateral. The earlier V1 helper caveat did not establish
current deployment terms. The task's additive collateral-fee model is retained;
historical deployment, adapter fees and rounding still require verification.

The earlier self-review/pin did not constitute master GO. B012 supplied explicit GO
for v3 with conditions. The controller enforced its storage stop after chunk 1;
the proposed v4 cannot start without a separately reviewed commit and GO. The
canonical wrapper's memory/disk/lease checks are unchanged.

## Proposed output-only v4

`out\scan_stream_v4.py` retains detailed rows only when an eligible unwindowed
optimistic bound or one-second optimistic bound is positive. All event/hour
counters, route calculations, sizes/windows, timing histograms and best-case heaps
remain complete. Missing negative detail is explicitly an omission, not zero margin.
Capture ordinals preserve consecutive-episode breaks across omitted captures;
17-digit float serialization preserves threshold decisions. V3 remains archived.

`out\v4_vs_v3.diff` isolates the changes; `out\RULE_V4_B012.md` specifies the
replan. Light controls pass 576 optimizer comparisons and archived real-schema
counter/window equivalence. No original tape was read by v4. Metadata/hour/episode
files alone project to about 122 MB; positive-row storage remains to be measured
under a new first-chunk gate. That gate includes retained v3 output in task storage.

## Handoff and open questions

Master review and explicit GO for v4 are required before further bounded bulk work. Then inspect
candidate margins, completeness, depth, measured capture timing and any available
latency receipts before deciding G2. A positive screen alone does not freeze T3.
If an executable case survives, draft strategy, unread forward dates, PASS and kill
rules for review, with no automatic freeze or live execution.

The master owns eventual findings/register and ledger updates. Publication follows
the latest COMMON.md deploy-key instruction, with a verified bundle retained. No merge.
