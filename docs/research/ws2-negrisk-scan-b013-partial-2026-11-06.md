# WS-2 negRisk structural-arbitrage scan — development findings

Generated from verified task outputs by `C:\t\codex\T003\out\build_final_report.py`; dated development evidence.

**G2: not met; execution unverified.** Partial census under a prescribed stop. No T3 preregistration was drafted or frozen.

Headline at **q10, ANY route**: snapshot-coincident screen positives form **10 episodes** with the 120-second join and **10 episodes** over consecutive captures, from 16 positive captures. These are alternate joins of the same headline series; do not add them.

Coverage: 393/900 event-days valued; 507 remain unvalued, including the failed event. Stopped on `field larger than field limit (131072)` in `highest-temperature-in-san-francisco-on-september-2-2026`. The controller exited; no automatic retry or source normalization. A separately pinned single-event structural diagnostic awaits master GO. The approved scanner bytes remain unchanged.

Pending structural diagnostic: `C:\t\codex\T003\out\diagnose_csv_boundary.py`, SHA-256 `9a5dcc9122282b3ab75b61d50627c57a8d287a14deb6f4bc3ed6175112a07da7`. Synthetic controls passed; no real diagnostic payload was read. Its only prospective data input is the failed San Francisco 2026-09-02 book summary, bounded to 120 seconds, 100,000 records and 1,048,576 characters per logical CSV record. It reports lengths/hashes without field values and performs no valuation, row skipping or normalization.

## Scope, completeness and counts

Read 393 event-days, 32,267,972 book rows and 1,466,726 captures, target dates 2026-08-01 through 2026-09-02, within the authorized 2026-08-01..2026-10-14 range. Only the three task-authorized book-summary roots were read; no outcomes, labels, execution tapes, maker shadow or >=2026-10-15 target dates.

Complete partition geometry: 393/393 event-days; complete capture sets: 1,466,726; captures with missing legs: 0. Unresolved walks/configuration remain explicit. The counters and details are bound to exact input/script hashes.

Observed tick-size values: 0.001, 0.01. Observed minimum-order sizes (shares): 5.0. Per-value book-row counts are in the analysis receipt; every selected leg is checked against its captured constraints.

| Quantity | Captures | Eligible unwindowed ANY | Positive lower, no timing window | Positive upper, no timing window | Positive 1 s screen |
| --- | --- | --- | --- | --- | --- |
| 1 | 1466726 | 0 | 0 | 0 | 0 |
| 5 | 1466726 | 964013 | 385 | 385 | 16 |
| 10 | 1466726 | 962048 | 256 | 257 | 16 |
| 100 | 1466726 | 940692 | 23 | 23 | 8 |

Only q10 ANY episode counts are the headline. Raw tables are snapshot × route × size. Do not sum across routes/sizes. `positive_lower`/`positive_upper` have no timing window. Five-share walks beyond top depth are unavailable, and sub-minimum orders cannot count.

Two sizing examples from the initial 30 events, at their archived one-second screen captures. Values are conservative fee-net dollars after walking depth. The 100-set ANY column reoptimizes within the one-second window.

| Event | Capture UTC | 1 set | 10 sets, mixed route | 100 sets, same mixed route | 100 sets, ANY |
| --- | --- | --- | --- | --- | --- |
| highest-temperature-in-los-angeles-on-august-1-2026 | 2026-08-01T19:35:02.651704+00:00 | Ineligible: minimum 5 shares | 0.106609 | -37.546634415 | -0.21995 |
| highest-temperature-in-san-francisco-on-august-1-2026 | 2026-08-01T22:19:27.958278+00:00 | Ineligible: minimum 5 shares | 0.050215619 | -69.032231134 | -0.982870084 |

## Largest q10 episode peaks

One peak per consecutive-capture episode; the alternate 120-second join is reported separately.

| City / target date | Peak capture UTC | Selected route | Fee-net lower..selected upper | Source span s | Top depth | Observations / sampled span s | Confirmed crossed VWAPs | Post nominal close suspect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| houston / 2026-08-27 | 2026-08-28T04:20:38.028613+00:00 | buy_pair | 3.3757505..3.3757505 | 0 | 285.7 | 7 / 90.054698944 | yes | False |
| toronto / 2026-08-03 | 2026-08-03T20:01:01.658860+00:00 | buy_yes | 0.82464084..0.8248152 | 0.581 | 7.02 | 1 / 0 | unconfirmed | False |
| denver / 2026-09-01 | 2026-09-01T21:18:37.987050+00:00 | buy_yes_mixed | 0.139950029..0.1408743 | 0.086 | 2.62 | 1 / 0 | unconfirmed | False |
| los-angeles / 2026-08-01 | 2026-08-01T19:35:02.651704+00:00 | buy_yes_mixed | 0.106609..0.107577 | 0.376 | 8 | 1 / 0 | unconfirmed | False |
| chicago / 2026-08-07 | 2026-08-07T19:54:49.500428+00:00 | buy_yes_mixed | 0.090904906..0.092214 | 0.058 | 7.39 | 1 / 0 | unconfirmed | False |
| seattle / 2026-08-19 | 2026-08-19T10:52:46.592081+00:00 | buy_pair | 0.07450839..0.0762417 | 0 | 5.53 | 1 / 0 | yes | False |
| san-francisco / 2026-08-01 | 2026-08-01T22:19:27.958278+00:00 | buy_yes_mixed | 0.050215619..0.051428452 | 0.418 | 3.44 | 1 / 0 | unconfirmed | False |
| toronto / 2026-08-04 | 2026-08-04T19:42:03.213172+00:00 | buy_yes_mixed | 0.0162345..0.01731 | 0.063 | 7 | 1 / 0 | unconfirmed | False |

Largest episode sizing: One set is below the captured five-share minimum. At 100 sets, reoptimized ANY margin is 33.757505..33.757505 via buy_pair.


Bounds use collateral taker fees `0.05*p*(1-p)` and depth VWAPs; makers pay zero. Global optimistic bounds may select a different route; this table uses the selected route upper bound. Depth ceilings do not establish profit capacity at larger quantities. Economic payoffs may include guaranteed settlement value; immediate atomic cash realization is not established.

## Episodes, quantiles, close time and the one-cent diagnostic

Quote-consistency diagnostic: 8 headline captures have confirmed crossed selected-leg VWAPs at the same token/capture/server-book time, touching 2 episodes under the 120-second join and 2 under the consecutive join. 7 of 7 one-cent-positive captures have this flag. Pinned counts are unchanged. Opposite quotes can be omitted from retained rows, so absence of a flag does not establish an uncrossed or accepting book.

| Selected route | Positive captures | Net lower p50 / p90 / p99 | Source span p50 / p90 s |
| --- | --- | --- | --- |
| buy_pair | 8 | 3.3757505 / 3.3757505 / 3.3757505 | 0 / 0 |
| buy_yes | 1 | 0.82464084 / 0.82464084 / 0.82464084 | 0.581 / 0.581 |
| buy_yes_mixed | 6 | 0.070560263 / 0.123279514 / 0.138282977 | 0.2045 / 0.397 |
| sell_no | 1 | 0.007215 / 0.007215 / 0.007215 | 0.139 / 0.139 |

| Episode join | Peak selected route | Episodes | Peak net p50 / p90 | Sampled span p50 / p90 s | Multi-capture |
| --- | --- | --- | --- | --- | --- |
| 120s | buy_pair | 2 | 1.725129445 / 3.045626289 | 45.027349472 / 81.04922905 | 1 |
| 120s | buy_yes | 1 | 0.82464084 / 0.82464084 | 0 / 0 | 0 |
| 120s | buy_yes_mixed | 6 | 0.070560263 / 0.123279514 | 0 / 0 | 0 |
| 120s | sell_no | 1 | 0.007215 / 0.007215 | 0 / 0 | 0 |
| consecutive_captures | buy_pair | 2 | 1.725129445 / 3.045626289 | 45.027349472 / 81.04922905 | 1 |
| consecutive_captures | buy_yes | 1 | 0.82464084 / 0.82464084 | 0 / 0 | 0 |
| consecutive_captures | buy_yes_mixed | 6 | 0.070560263 / 0.123279514 | 0 / 0 | 0 |
| consecutive_captures | sell_no | 1 | 0.007215 / 0.007215 | 0 / 0 | 0 |

Positive capture close-hour bins [h,h+1), hours relative to the end of the event local day: -22=1, -21=1, -13=1, -12=1, -10=1, -9=3, -8=1, -1=7.

For the selected q10 ANY routes, 7 snapshot screens remain conservatively positive after an additional $0.01 per share on each CLOB leg. 0 headline positive captures are at/after nominal close; 0 have unknown local close position. Nominal close is midnight ending the event city local date, a proxy because actual accepting-orders/closed status is absent.

Separate conservative one-cent counts by raw route (not additive): buy_no=0, buy_pair=7, buy_yes=0, buy_yes_mixed=0, convert_subset=0, sell_no=0, sell_pair=7, sell_yes=0. The ANY diagnostic follows the raw-margin winner; it does not reoptimize across families after the extra charge.

`headline_route_quantiles.json` gives exact linearly interpolated margin/source-span quantiles by selected route and episode margin/sampled-span quantiles under both joins. Episode attribution is the selected route at its best margin, with route changes recorded. `headline_by_close_hour.csv` gives [h,h+1) hour bins; all route/size close flags are separate. Sampled span and consecutive reobservation are not continuous lifetime or measured latency survival; continuous-duration lower bounds are zero. Filtered cases are labelled **closest retained (positive-upper) cases**.

## Timing and executable interpretation

Observed capture gaps range 0.702352047..2298.167546034 seconds; per-event median gaps range 15.01..15.04 seconds. Source windows are 1/5/30/60 seconds, with 1 second the headline. Book timestamps are server book time; capture time is assigned before fetching. These windows establish book-time coincidence, not simultaneous fills or receipt/order latency.

Historical negRisk group membership, adapter conversion fee (assumed zero), fee deployment/rounding, raw fill ladders and actual market status remain unverified. The capture summaries supply no measured observation-to-order latency. Consequently no case can satisfy executable G2 from this evidence alone.

Mechanics follow the [official adapter](https://github.com/Polymarket/neg-risk-ctf-adapter/blob/main/src/NegRiskAdapter.sol): selected NO positions convert to complementary YES plus m−1 collateral; reverse conversion is not assumed. The eight routes are buy_yes, sell_yes, buy_no, sell_no, convert_subset, buy_yes_mixed, buy_pair and sell_pair; ANY deduplicates them. [Official fees](https://docs.polymarket.com/trading/fees), [order constraints](https://docs.polymarket.com/trading/place-orders) and [V2 collateral-fee settlement](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol) are archived with source receipts. Current documents do not establish historical market terms.

## B010 re-check, B012 replan and B013 execution receipts

B010 fixed selected-leg eligibility, optimization within each source window, unresolved defaults, streaming/budget bounds, publication integrity/recovery and explicit GO gating. Current V2 source charges collateral fees; legacy V1 was not deployment evidence. Continued re-check added the retained-output crossed-VWAP diagnostic, distinct episode peaks and actual interim date coverage. B012 v3 chunk 1 projected 2,323,754,460 bytes and stopped at the required 1.5 GiB limit. V4 changes only detail retention, capture ordinals, numeric precision and version metadata; all counters and calculations remain complete.

V4 chunk 1 completed 30 events in 425.4356705 seconds, writing 4,154,088 stream-event bytes. Its projected total task output was 208,206,452 bytes, including retained prior artifacts, and its projected finish was 2026-11-07T03:40:01.9487270+00:00. Projections exclude future admission waits.

B013 authorized exact v4 SHA `b42a25f7d1fe4fc708059f1e2116607360a895a63b02f65e563435147cbf26cf` at allowlist commit `43e648c4a8fab1d91745e827ee59b659f0189d18`. Real-data equivalence passed on the original 30 events: JSON counts/windows/timing/best cases/input hashes match, hours/episodes are byte-identical, and all 824 retained rows match after the allowed formatting/ordinal changes. The headline remains two positives/two episodes under both joins. The master fixed the later chunk stop at 8,360 retained rows.

Maximum retained rows in a chunk: 852; failed row guards: 0. Projections follow successful progress chunks. The final fatal chunk stopped before automatic projection. Its three completed events retained zero rows; `B013_fatal_chunk_safety_receipt.json` preserves the manual output/row check and marks the post-fatal runtime forecast unknown. Resource refusal waits ten minutes, HOLD five minutes, and successful chunks yield for sixty seconds. Scanner bytes, six-GiB memory floor and disk/lease checks stayed unchanged.

## Archive and open questions

Artifacts, source archives, scripts and SHA-256 manifests: `C:\t\codex\T003\out\`. Primary receipt: `partial_analysis_receipt.json`; equivalence: `B013_equivalence_receipt.json`; postprocessor report: `C:\t\codex\T003\out\B012-report-20261107T044205124951Z`. City/day/hour tables and per-event manifests retain the detailed counts. A verified Git bundle accompanies the branch; merge nothing.

OPEN QUESTIONS: obtain historical receipt timing and measured order latency, group/adapter fee and fee-rounding/deployment evidence, raw ladders and market status before an executable-G2 claim. The master owns canonical findings/register updates. No forward T3 dates or PASS/kill rule are frozen.
