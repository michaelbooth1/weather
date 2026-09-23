**Session 1 supports the reward-share model's scale, but does not validate either competition scenario or establish paid rewards or profit. The journal's 0.117375 provisional accrual sits between reproduced predictions P_many = 0.105385859 and P_single = 0.125204867; single is closer. Both-book checking changes P_many by only -0.0000268375. Added qualifying depth, rather than midpoint movement, explains almost all of the falling minute estimate. Session 2 must retain per-minute venue percentages with measurement times, synchronized both-token books, own-order-adjusted depth, exact reward configurations, matched T+1/T+2 controls, and independent public capture for 30 minutes before and after quoting, including after a fill or user-stream failure.**

# RE-1 session 1 desk analysis — 2026-09-86c

Historical, offline desk analysis, written 2026-09-23. All times below are UTC
unless explicitly labeled ET. Monetary-looking reward figures retain the journal's
reward units; hundredths are called cents for comparison with the handoff. No
conversion into a paid collateral asset is proved.

## Scope, provenance and method

- Requested handoff: `origin/codex/reward-test-attended-handoff-20260921` at
  `902a1973` (the named 86c handoff). The only network action was the explicitly
  requested initial Git fetch. No subsequent network access or push.
- Branch: `codex/re1-session1-analysis-20260923`, from cached `origin/master`
  `3b4232ae8e337c876f5771294914122b28ea5890`. Master was not refreshed because the
  owner explicitly required offline execution after fetching the handoff.
- Worktree: `scratch/w/re1-session1-analysis-20260923` beneath the workstation
  checkout. LFS smudging was disabled for worktree creation.
- Reserved confirmation window at this base: **NONE RESERVED**.
- Inputs were copied, never moved, from the four named session-1 files into
  this worktree's ignored `data/re1_session1/`. Source-before, source-after and
  destination SHA-256 were identical for each file. Analysis subsequently used
  only copies; copied hashes were checked again after computation.
- Support: **one session, one NYC condition (66–67 F, event date September 24),
  one observation date, 42 minute samples**. No significance test, clustered
  interval, model scoring, fitting, candidate, alpha spend or extrapolated
  profitability claim. Rounding sensitivity below is arithmetic, not a CI.
- There are 3,793 journal rows, 42 `market_snapshot` rows and 42 matching
  `minute` rows. These pairs hold identical snapshots and are counted once.
  Selection happened at 01:47:33; quote placement was at approximately
  01:48:16/18, not 01:47. Minute observations span 01:48:18.937481–02:29:18.961189.
- The stdlib script independently reproduces all 42 recorded shares and both
  prediction sums (tolerance 1e-12), verifies the prediction's journal digest,
  and verifies SHA-256 for all 172 retained selection source-response bodies.
  It imports no project modules or startup hooks. Cached source formulas were
  inspected at reward-test-attended tip
  `7e6e1709c243cf88aa7799bf4486a9af821abbf5`; this is a formula reference, not
  a claim that the journal proves the executing source tip.
- Printed and committed evidence uses explicit selected fields. No raw
  `owner`, API-key-like or credential-named field value is included; raw
  payloads, signed order bodies and account identifiers are not committed.

| Copied file | Bytes | SHA-256 (same before copy, after copy, and destination) |
| --- | ---: | --- |
| journal.jsonl | 2717115 | `70e4add712140a9d3b0e4571c880f4a48366c9460966ed1464275eafbeff72c7` |
| prediction.json | 1233 | `be81609ad5ba27dfaa4aac595f36f066895651057a1b5fc1a29a560ef8613704` |
| selection.json | 1156127 | `2d10ce25d4201788056efc3dc9579a8022fcf4e38310e08d077304978eba4ae9` |
| user-stream.jsonl | 2667 | `6358bdb1d21c9ae0dfb1e642435526cb17e33bf98c5a610681782eeba7ecb552` |

## 1. Book mirror — D4-08

Both tokens and both sides are present in **42/42** minute snapshots. Comparing
price-to-size maps after `NO price -> 1 - price`, **37/42** snapshots mirror
exactly at every level. Five differ; four differ only outside the reward radius.
The reads are sequential, not a simultaneous two-book observation.

| Snapshot time | Journal minute sequence | Difference in YES-price coordinates | NO minus YES book timestamp |
| --- | ---: | --- | ---: |
| 02:06:18.784820 | 1661 | YES bid .24: 30 vs mirrored NO ask: 0 | 1.326 s |
| 02:07:19.152665 | 1743 | YES bid .24: 30 vs mirrored NO ask: 0 | 0.866 s |
| 02:17:19.258776 | 2624 | YES ask .85: 0 vs 25; .86: 7.14 vs 42.14 | 4.857 s |
| 02:20:19.471700 | 2900 | YES bid .48: 246.2 vs 266.2; YES ask .53: 373 vs 393 | 1.755 s |
| 02:28:19.356974 | 3599 | YES bid .35: 90 vs 0; .36: 0 vs 24; .37: 0 vs 90 | 6.313 s |

Recalculation removes our 20 shares from each relevant display before scoring.
With `S = size * ((4.5 - abs(distance_cents))/4.5)^2`, levels below 20 shares or
at/beyond 4.5 cents score zero. Own Q is 8.888888889 throughout. For each paired
display, average the YES score and its NO mirror, then average the two sides for
competing Q_many. **Do not sum redundant books**, which would double count.
As a sensitivity, using just the two native bid books gives the same result
as this four-side average for every retained minute in this session.

At 02:20, external scores are YES bid **127.743209877**, YES ask
**165.777777778**, NO bid **169.728395062**, NO ask **131.693827160**.
Competing Q_many changes **146.760493827 -> 148.735802469** and share_many
**5.710841080% -> 5.639274413%**, a **-0.071566667 percentage-point** change
(about -1.25% relative). Every other minute's share is unchanged within 1e-12.
The integrated estimate becomes **0.105359021332**, down **0.000026837500**
(about 0.0255%). These are asynchronous-book sensitivities; exact simultaneous
competition and maker-level allocation remain not identifiable. The appendix
reports the complete minute-by-minute comparison.

## 2. Venue percentage versus ours — D4-09

Define `k_share = (venue percentage / 100) / modeled share`. Missing percentage
is missing, not zero. Match each accrual to the nearest retained minute snapshot
and disclose its age; final accrual occurs after cancellation and is not a
contemporaneous live-order comparison.

| Accrual time (sequence) | Accrual | Venue % | Our many % | Our single % | k_many | k_single | Snapshot age |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01:48:20.683346 (88) | no row | absent | 16.411079 | 21.301775 | not identifiable | not identifiable | 1.746 s |
| 02:19:21.273770 (2809) | 0.093223 | 6.229909 | 5.692780 | 6.505711 | 1.094353 | 0.957606 | 1.772 s |
| 02:30:11.454208 (3791) | 0.117375 | 5.475049 | 4.811535 | 6.505711 | 1.137901 | 0.841576 | 52.493 s |

Only **one nonempty during-quoting percentage** is available. Its value lies
between the scenarios and is closer to single. The final percentage cannot
identify post-fill instantaneous share: it may be cached or averaged, and the
captured response supplies no effective measurement interval. Every accrual
response explicitly says `payment_verified=false`.

## 3. Which competition model fits?

| Scenario | Reproduced prediction | Absolute error vs site 0.12 | Absolute error vs journal 0.117375 | Journal accrual / prediction |
| --- | ---: | ---: | ---: | ---: |
| many | 0.105385859 | 0.014614141 | 0.011989141 | 1.113764 |
| single | 0.125204867 | 0.005204867 | 0.007829867 | 0.937464 |

**Single is closer to both reported numbers.** The exact provisional accrual
is a stronger arithmetic comparison than the rounded site display, but not a
completed payout. If the site rounds to the nearest cent, 0.12 represents
`[0.115, 0.125)`; the equal-error crossover is **0.115295363**. Thus rounding
alone does not guarantee the ranking across that entire interval. The
journal's 0.117375 is on the single-closer side. Site rounding policy is not
established by these files.

The scenarios are assumptions about unobserved maker ownership, not confidence
bounds. Aggregated levels can contain subminimum individual orders. Sampling
phase, partial exposure at start/end, response lag and changing competition
are unresolved. Session 2 should compare each scenario to time-aligned venue
percentages and later finalized condition/day accrual, especially during
periods when the two predictions diverge. Do not fit a calibration constant
from this one session or interpret its 42 observations as independent sessions.

## 4. Why the minute estimate fell

The first-to-last estimate falls **0.615415474 -> 0.177091213 cents/minute**,
down **71.2241%**. Share falls **16.4110793% -> 4.8115349%**; competing Q_many
rises **45.275061728 -> 175.852345679**, or **3.8841x**. Adjusted midpoint,
plain midpoint and our own Q remain **0.505**, **0.505** and **8.888888889**.
Rate is 54 in 36 samples, then 53 in six, first observed at
**02:24:19.479240** (sequence 3249).

An exact, explicitly ordered endpoint decomposition (change rate first at
initial share, then depth at final rate) is:

| Component | Change in cents/minute |
| --- | ---: |
| Rate 54 -> 53, holding initial share | -0.011396583 |
| Qualifying depth, holding final rate and fixed midpoint | -0.426927678 |
| Midpoint | 0 |
| Total | -0.438324260 |

Allocation of the rate/depth interaction depends on order; the multiplicative
rate effect is unambiguously **53/54 = 0.98148148**. Rate alone cannot explain
the decline. Endpoint external depth inside the scoring radius changed as
follows, with our 20-share orders already removed:

| YES-coordinate side/price | Initially | Finally | Change in qualifying shares |
| --- | ---: | ---: | ---: |
| Bid .48 | 20 | 246.2 | +226.2 |
| Bid .49 | 65 | 178 | +113 |
| Ask .52 (NO bid .48) | 50 | 313 | +263 |
| Ask .53 (NO bid .47) | 179.66 | 352 | +172.34 |
| Ask .54 (NO bid .46) | 5, below minimum | 310.22 | +310.22 qualifying; +305.22 raw |

Total qualifying external depth is **314.66 -> 1399.42 shares**. No quoted
price moves strictly inside the unchanged .49/.52 YES bid/ask spread; the
growth is at existing levels and within the **reward scoring radius**.

The largest one-minute earnings drop is already between **01:48:18.937481
and 01:49:19.746345**: **-0.196331312 cents/minute**, Q_many **+25.374567901**.
By 01:50 Q_many is **84.476790123**. There are **23 increases, 14 decreases
and four unchanged transitions** among 41 consecutive samples. Later large
Q increases occur at **02:11:18.783184 (+23.703703704)** and
**02:27:18.785496 (+22.864197531)**. This is repeated depth growth and
withdrawal, not one observed permanent step. Whether one competitor or many
placed those orders, and their exact arrival timestamps between snapshots,
are **not identifiable** from aggregated books.

## 5. Self-referential midpoint and rate configurations — D4-16

Both of our prices sit at the best qualifying bid level in **42/42 minutes**:
YES .49 and NO .48 (mirrored YES ask .52). But we are never the only qualifying
depth there. Removing our 20 shares leaves at least **65 YES shares and 50 NO
shares** across the session. Recomputing the size-adjusted midpoint without
our orders changes it in **0/42 minutes**. Adjusted and plain midpoint agree
in **42/42**, and both distances remain **1.5 cents**, each leg scoring
**8.888888889**. Thus the observed self-induced midpoint, distance and own-Q
effects are **zero** for this treatment. This does not establish that another
size or market would be immune.

Exactly **one rewards_config entry is active in each of 42 snapshots**:
configuration ID **2392797**, start **2026-09-23**, end **2500-12-31**. Its
rate sums to the recorded 54 or 53 in every minute. **No configuration rate
double count is present**. The decline in rate is a change to the same entry.

## 6. Fill, price path and missing markouts

Five snapshots fall in the requested five-minute pre-fill window:

| Snapshot | Minute sequence | YES bid / ask | NO bid / ask |
| --- | ---: | --- | --- |
| 02:25:18.808840 | 3335 | .49 / .52 | .48 / .51 |
| 02:26:19.704025 | 3421 | .49 / .52 | .48 / .51 |
| 02:27:18.785496 | 3509 | .49 / .52 | .48 / .51 |
| 02:28:19.356974 | 3599 | .49 / .52 | .48 / .51 |
| 02:29:18.961189 | 3681 | .49 / .52 | .48 / .51 |

There is **no observed NO bid/ask crossing through .48**: the bid rests at
.48 and the ask at .51. The last book is **48.039 seconds before** the
handoff's 02:30:07 anchor, so intraminute movement around the execution is not
identifiable. The trade itself identifies the mechanism: `terminal_trades`
sequence **3777** records a **BUY of 25.57 YES at .52**, matched at
**02:30:06Z**, against two **NO BUY makers at .48**, for **20 + 5.57 shares**.
Our maker-order ID matches the second leg. This is a **complementary YES-buy
match**, not a same-token NO sell. Status at read is **MINED**. The
user-stream failure is recorded at **02:30:07.439464Z**; its raw triggering
trade message is absent, so the stream alone cannot independently reconstruct
that message.

The exact own fill is **5.57 shares**, not 5.6 except as rounding; cost is
**2.6736**. Final order reconciliation records matched sizes **0 YES / 5.57
NO**. Collateral falls **139.942594 -> 137.268994**, also **2.6736**. Top-level
trade fee rate is **0**, but own maker fee-rate field is null. Terminal
positions returns **zero rows** immediately after the fill; that stale/lagging
read is not proof of zero inventory. `evidence_complete=false` remains a
material limit despite the terminal cleanup flags.

There are **zero post-fill book snapshots** in these inputs. The table uses
the last available book as a visibly stale reference, never a measured markout:

| Requested horizon from 02:30:07 | Target time | Last book age at target | Actual horizon MTM |
| --- | --- | ---: | --- |
| +1 minute | 02:31:07 | 108.039 s | not identifiable |
| +5 minutes | 02:35:07 | 348.039 s | not identifiable |
| +30 minutes | 03:00:07 | 1848.039 s | not identifiable |

Last-known NO midpoint is **.495**: stale value of 5.57 shares is **2.75715**,
or **+0.08355** over cost. Last-known bid .48 gives **2.6736**, or **0** over
cost. Those same stale references apply to all three rows and are **not**
post-fill returns or guaranteed executable proceeds. Using the rounded 5.6
shares would instead give midpoint value **2.772**, cost **2.688** and stale
difference **0.084**; the exact trade quantity governs. Settlement value and
realized inventory P&L come later.

## 7. Requotes and legs

**Zero requotes**, consistent with all **84 leg-minute distances equal to
1.5 cents**. The controller requests a requote outside the inclusive **[1, 3]
cent** interval. Each observation has **0.5 cent clearance to the lower bound
and 1.5 cents to the upper**; a half-tick midpoint move would reach the lower
bound, but none is observed. No sampled bound violation or requote flag occurs.
There are **0/42 minutes with either leg not visible** at aggregate size 20
or greater. Visibility is sampled aggregate depth, not continuous own-order
identity proof. The two orders were placed separately about two seconds
apart; the partial fill/cleanup after the last minute lies outside those
42 two-sided samples.

## 8. T+2 population — D4-06

Selection at **2026-09-23 01:47:33Z = September 22, 21:47:33 ET** chooses an
event dated **September 24**, so this is **T+2 in local-date terms**, despite
the UTC date difference being one day. The copied `selection.json` contains
**seven candidate rows, all dated September 24**, not a T+1 comparison panel.
Its **172 source records** comprise 12 September-24 event queries, 132 reward
market queries, 14 book queries and 14 fee-rate queries. Retained reward
records with configuration fields cover **56 September-24 conditions**, all
with 20-share minimum, rates **1–57** (sum **1201**, an eligibility pool, not
income). Only seven conditions have the two-token books needed for this
comparison. **Zero T+1 candidate rows or books are present.** The requested
T+2 versus T+1 book/competition difference is therefore **not identifiable**
from these files; `universe_complete=true` pertains to the selected target.

| T+2 row (city, midpoint) | Daily rate | Competing Q_many | Share_many % | Share_single % | 360-minute selection estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chicago, .480 | 57 | 596.415988 | 1.024387 | 1.851483 | .145975 |
| Houston, .385 | 42 | 1495.305679 | .590940 | 1.014701 | .062049 |
| Los Angeles, .435 | 47 | 112.596543 | 7.316835 | 7.957841 | .859728 |
| Los Angeles, .385 | 41 | 90.061728 | 8.983157 | 11.952191 | .920774 |
| Miami, .490 | 57 | 141.197037 | 4.188671 | 5.724098 | .596886 |
| NYC, .505 | 54 | 40.155802 | 18.124059 | 26.277372 | 2.446748 |
| Toronto, .555 | 56 | 929.227160 | .947526 | 1.594531 | .132654 |

NYC alone passes the selection's two-unit projection threshold; its initial
Q_many is the lowest of the seven. These are retained **pre-placement
selection projections**, not six-hour earned rewards. Session competition
rose quickly, so the selected 2.446748 projection did not persist. Neither the
selected condition nor the seven filtered candidates represent an unbiased
T+2 population estimate.

## Concrete design inputs for session 2

1. Retain venue percentage and exact condition/day accrual at every minute,
   with request, receive and effective measurement times (or explicit unknown
   effective time), units, null/empty distinction and cache metadata.
2. Retain synchronized YES and NO books with exchange and receive timestamps;
   compute native-bid and mirror-consistency diagnostics without double
   counting. Preserve size/order-level limitations and subtract our remaining
   quantity, rather than assuming 20 shares after a partial fill.
3. Retain midpoint both with and without our depth, each leg's distance,
   own/external Q, remaining quantity, qualifying levels and every active
   reward configuration ID/date/rate. Record every bound crossing and requote.
4. Start independent public observation 30 minutes before quoting and keep it
   running at least 30 minutes after cancel/fill/user-stream failure. Continuing
   observation must not require continued quoting. Preserve sub-minute price
   paths and exact +1/+5/+30-minute marks with staleness and coverage flags.
5. Preserve normalized complementary trade legs and trade-state transitions,
   retaining raw-event hashes while redacting all owner/credential fields.
   Continue read-only inventory reconciliation until fills and positions
   agree, then obtain final reward accrual, actual payout and settlement
   separately. An empty immediate positions read must not imply flat inventory.
6. Capture matched T+1 and T+2 books and rewards at the same local/UTC times,
   including excluded candidates and explicit selection denominators. Repeat
   controls before, during and after our treatment to distinguish background
   depth growth from a reaction to our placement; maker identity remains
   unknown unless separately evidenced.
7. Preserve unrounded accrual and its asset/rate metadata. Compare the frozen
   many/single scenarios prospectively, with actual exposure durations and
   finalized accounting. This descriptive result does not select a production
   calibration or authorize another live session.

## Reproduction, verification and handback

Analysis script: [`tools/re1_session1_analysis.py`](../../tools/re1_session1_analysis.py).
From the branch root, after making the hash-verified copies and the retained
`copy-manifest.json`, run a standard-library Python interpreter:

```powershell
& C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -I -S tools/re1_session1_analysis.py
git diff --check
git rev-parse codex/re1-session1-analysis-20260923
```

The successful workstation invocation used the existing project interpreter
at `C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe` with
the same `-I -S` arguments, from this analysis worktree. No clean checkout is
assumed to contain the ignored inputs. The result is
`data/re1_session1/analysis.json`; its `minutes` array is the full numerical
evidence behind the appendix. The copy receipt stores `name`, `bytes`,
`source_before`, `source_after`, and `copy_sha256` for each file; it contains
no raw payload or credential values.

Verification is limited to executing this bounded stdlib analysis, arithmetic
reproduction assertions, four copy hashes, 172 response-body hashes and Git
diff review. **No pytest, compileall, training, bulk scan or heavy command**
was run, per the explicit task. No `.env` was read. No campaign-root write,
production write, task registration, restart, exchange call, merge, push or
PR was performed. The local branch and copied evidence are retained.

Per-file integration disposition: the report is documentation (roll-free by
contract); the script is a new standalone offline tool. No production closure
evidence was accessed, so a mechanically verified branch roll verdict is
**not available on this workstation**. The integrating production agent must
use `scripts/ops/roll_verdict.ps1 -Branch codex/re1-session1-analysis-20260923`
before integration; this report does not substitute a hand-derived verdict.
The exact committed branch tip is supplied in the handback and resolves with
the command above. Publication remains intentionally undone under the owner's
no-network instruction.

## Appendix: all minute comparisons

Each row identifies its zero-based journal sequence (`line = sequence + 1`).
Q values exclude our orders. Both-books Q averages corresponding mirrored
displays; shares are percentages. Detailed unmatched levels and timestamps are
retained in the generated local analysis. Rounding in this table does not
replace the full-precision reproduction assertions.

| UTC snapshot | Sequence | Exact mirror | YES Q_many | Both Q_many | YES share % | Both share % |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| 01:48:18 | 89 | yes | 45.275062 | 45.275062 | 16.411079 | 16.411079 |
| 01:49:19 | 175 | yes | 70.649630 | 70.649630 | 11.175578 | 11.175578 |
| 01:50:19 | 261 | yes | 84.476790 | 84.476790 | 9.520510 | 9.520510 |
| 01:51:19 | 351 | yes | 87.126914 | 87.126914 | 9.257735 | 9.257735 |
| 01:52:19 | 439 | yes | 97.069383 | 97.069383 | 8.389047 | 8.389047 |
| 01:53:18 | 518 | yes | 97.069383 | 97.069383 | 8.389047 | 8.389047 |
| 01:54:18 | 608 | yes | 96.575556 | 96.575556 | 8.428328 | 8.428328 |
| 01:55:18 | 698 | yes | 116.184444 | 116.184444 | 7.106942 | 7.106942 |
| 01:56:19 | 784 | yes | 131.147407 | 131.147407 | 6.347561 | 6.347561 |
| 01:57:19 | 870 | yes | 135.591852 | 135.591852 | 6.152300 | 6.152300 |
| 01:58:19 | 960 | yes | 131.740000 | 131.740000 | 6.320813 | 6.320813 |
| 01:59:19 | 1050 | yes | 124.513580 | 124.513580 | 6.663212 | 6.663212 |
| 02:00:18 | 1132 | yes | 125.320247 | 125.320247 | 6.623162 | 6.623162 |
| 02:01:18 | 1219 | yes | 121.665926 | 121.665926 | 6.808549 | 6.808549 |
| 02:02:19 | 1312 | yes | 121.665926 | 121.665926 | 6.808549 | 6.808549 |
| 02:03:19 | 1395 | yes | 121.172099 | 121.172099 | 6.834401 | 6.834401 |
| 02:04:19 | 1481 | yes | 102.797778 | 102.797778 | 7.958774 | 7.958774 |
| 02:05:19 | 1571 | yes | 122.143210 | 122.143210 | 6.783749 | 6.783749 |
| 02:06:18 | 1661 | no | 124.184444 | 124.184444 | 6.679692 | 6.679692 |
| 02:07:19 | 1743 | no | 124.184444 | 124.184444 | 6.679692 | 6.679692 |
| 02:08:18 | 1833 | yes | 129.715309 | 129.715309 | 6.413146 | 6.413146 |
| 02:09:18 | 1923 | yes | 130.019753 | 130.019753 | 6.399090 | 6.399090 |
| 02:10:19 | 2009 | yes | 130.530370 | 130.530370 | 6.375654 | 6.375654 |
| 02:11:18 | 2092 | yes | 154.234074 | 154.234074 | 5.449195 | 5.449195 |
| 02:12:19 | 2182 | yes | 134.234074 | 134.234074 | 6.210666 | 6.210666 |
| 02:13:19 | 2272 | yes | 147.589630 | 147.589630 | 5.680581 | 5.680581 |
| 02:14:18 | 2358 | yes | 156.972346 | 156.972346 | 5.359232 | 5.359232 |
| 02:15:19 | 2444 | yes | 140.649877 | 140.649877 | 5.944204 | 5.944204 |
| 02:16:18 | 2534 | yes | 133.242469 | 133.242469 | 6.253996 | 6.253996 |
| 02:17:19 | 2624 | no | 134.723951 | 134.723951 | 6.189481 | 6.189481 |
| 02:18:18 | 2706 | yes | 148.982716 | 148.982716 | 5.630455 | 5.630455 |
| 02:19:19 | 2810 | yes | 147.254321 | 147.254321 | 5.692780 | 5.692780 |
| 02:20:19 | 2900 | no | 146.760494 | 148.735802 | 5.710841 | 5.639274 |
| 02:21:19 | 2983 | yes | 158.118519 | 158.118519 | 5.322452 | 5.322452 |
| 02:22:19 | 3069 | yes | 158.118519 | 158.118519 | 5.322452 | 5.322452 |
| 02:23:19 | 3159 | yes | 148.735802 | 148.735802 | 5.639274 | 5.639274 |
| 02:24:19 | 3249 | yes | 156.637037 | 156.637037 | 5.370089 | 5.370089 |
| 02:25:18 | 3335 | yes | 174.809877 | 174.809877 | 4.838840 | 4.838840 |
| 02:26:19 | 3421 | yes | 181.877037 | 181.877037 | 4.659579 | 4.659579 |
| 02:27:18 | 3509 | yes | 204.741235 | 204.741235 | 4.160878 | 4.160878 |
| 02:28:19 | 3599 | no | 176.840000 | 176.840000 | 4.785948 | 4.785948 |
| 02:29:18 | 3681 | yes | 175.852346 | 175.852346 | 4.811535 | 4.811535 |
