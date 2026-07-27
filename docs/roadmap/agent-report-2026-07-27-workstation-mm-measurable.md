# Workstation report - make market making measurable - 2026-07-27

## Decision

`INCONCLUSIVE_NOT_DECISION_GRADE`

The track is now measurable, but this pilot does not close it and does not
justify a cap or production change. At the primary 2c/60-second setting,
30-minute adverse selection exceeded spread plus the rebate estimate at the
$25 and $50 caps. The result was heterogeneous, however: all event-day
uncertainty intervals crossed zero, settlement P&L was positive in every
measured cap cell, two wider $50 cells were positive at 30 minutes, and the US
subset was positive while Toronto supplied the primary loss. Historical
liquidity-reward dollars also remain unknown.

This queue ran at exact base
`ce1178bce6b3f5f9ca825bd1fab22c40fef20ab8` on
`codex/workstation-mm-measurable-2026-07-27c`. It did not change any
collector, trading, sizing, quoting, model, serving, scheduler, release,
promotion, or pointer surface. `data/` remained read-only.

## Frozen scope and host controls

The single writable evidence root was:

`C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-measurable-20260727c`

The predeclaration was frozen before the first Data API response was requested:

| Evidence | SHA-256 |
| :--- | :--- |
| Predeclaration | `2b78fad628be08d6b8bffb4ca72a523abb9b3fe2a3f97df51ff6da4a8350e8b8` |
| Initial host admission | `ba22ebaca6054e182d9386d4fe2a30f4083b2e498d7358be57b279d150932057` |
| Data API fetch program | `3051d038addaa6ed8e41c60ac8dd794d9750cf97c24c1fcddd2fc487ba8ca78c` |
| Data API backfill manifest | `603872a739cb598dcbbbbfd579a89dc1a9d362673286809cd599bc8b4a4bbd9f` |
| Data API post-fetch correction | `60fc7985a504412dcc558639aa2afae41c1635002153a11e7c23c1bd6ead9d82` |
| Python environment receipt | `ee37837e2383bd13c55b2694799f84716b7feddd7eb86824c09c1ba5deb272ed` |
| Candidate scorer | `827f4fa7d9e8d6c5b76cfcfea2bd2917e479ec68096e474cd0673556bb76e8b0` |
| Measurement admission | `e9d67e6e901a072a5f1b18072b29d8d07e5e5ad7bfc61162926fb629c4b48601` |
| Measurement program | `0b3f062ce1e388c654fd5c2752cda5449948c984322364d2ace3cef756eb3fd9` |
| Independent harness review | `78c5451b930c76be87f6ba3d27712c63de059ac7c24993745f2db2f06e061687` |
| Measurement input manifest | `a2b19731bdbeff0680d35288df2813cada512798229e620730a76cb1b0452180` |
| Measurement receipt | `0e976845b7a1e4fc948b537e6aa55317696ff2357a7e511c72b2d897df81ae2c` |

Initial admission at `2026-07-27T11:06:39-04:00` found 44.98% committed
memory, 66.41 GiB free on `C:`, completed training restore, no active
`robocopy`, no weather-owned Python process, and explicit deny-write/delete
ACL entries on `data/` for both the user and sandbox identities. Because that
check occurred during the host policy's Stage A scheduled-heavy interval, only
light setup and the bounded API backfill ran then. The material local-corpus
read waited for a fresh post-12:30 admission.

The final admission at `2026-07-27T12:33:19-04:00` found 51.40% committed
memory, 63.42 GiB free, completed training restore, and zero active
mirror/Stage-A/training processes. The 30 exact corpus inputs (462,357,108
bytes) had identical size/mtime fingerprints over two passes. The deny ACL
remained intact. The harness subsequently bound 53 inputs and verified every
bound input remained unchanged through the run.

## Python prerequisite

The shared project `venv` was not repaired in place. Its CPython 3.11 target
exists, but the sandbox identity cannot execute it (`Access is denied`) and
the launcher exits 101. Its NumPy/Pandas extensions are CPython 3.11 builds
that cannot safely be loaded by the available CPython 3.12 runtime.

A task-local environment was created below the single output root using the
bundled CPython 3.12.13. The repository's exact `.[test]` dependencies were
installed, including NumPy 2.4.6, pandas 3.0.3, requests 2.34.2,
scikit-learn 1.8.0, and pytest 9.0.3. It imported `weather` from this topic
worktree. A task-local `.pth` file prepends this worktree's exact `src` path
for direct script execution; its SHA-256 is
`016e47d1ea3a918b87bcfc74cff3bed458ae99f9ab4052de4e4b80b0c33adf29`.
Exact version imports and `pip check` passed. Both of these also passed before
measurement:

- `python -m weather.market.mm_paper --help`;
- the existing conservative-fill focused test (1 passed, 30 deselected).

The shared broken environment and user state were left unchanged.

## Mission 1 - historical executions are available now

### Vendor contract

Polymarket's unauthenticated Data API `/trades` endpoint returns the fields
needed for this bounded retrospective reconstruction: transaction hash,
epoch-second exchange timestamp, condition, asset/token, taker side, price,
and executed size. It accepts a comma-separated condition-ID market filter,
`limit` up to 10,000, `offset` up to 10,000, `takerOnly`, and documented
`start`/`end` epoch-second filters.

The published Data API limit is 1,000 requests per 10 seconds generally and
200 requests per 10 seconds for `/trades`. Polymarket documents market/event
query history as retaining approximately the most recent three years. The
six-case fetch establishes only an empirical lower bound for this corpus; it
does not promote an approximate vendor retention statement into a completeness
guarantee.

Official sources:

- [Data API trades endpoint](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
- [API rate limits](https://docs.polymarket.com/api-reference/rate-limits)
- [Market WebSocket events](https://docs.polymarket.com/api-reference/wss/market)

### Frozen backfill

The outcome-blind pilot was six adjacent settled event-days:

- Atlanta, Dallas, and Toronto on 2026-07-10;
- Atlanta, Dallas, and Toronto on 2026-07-11.

It covers Fahrenheit and Celsius contracts. Each event contributed the 11 YES
band tokens from its first canonical snapshot: 66 conditions and 132 mapped
YES/NO tokens in total.

Exactly six successful HTTP requests were made, one per event, with no retry.
Every first page contained fewer than 10,000 rows, so no second page was
requested. The retained raw and canonical results contain 10,251 rows, with
zero exact duplicates, zero identity conflicts, and zero malformed-row
rejections. Of those, 7,240 executions fall in the six frozen local-day
windows:

| Event-day | Local-day executions | BUY | SELL |
| :--- | ---: | ---: | ---: |
| Atlanta 2026-07-10 | 1,083 | 821 | 262 |
| Dallas 2026-07-10 | 1,202 | 1,006 | 196 |
| Toronto 2026-07-10 | 1,003 | 836 | 167 |
| Atlanta 2026-07-11 | 1,233 | 1,043 | 190 |
| Dallas 2026-07-11 | 1,215 | 1,007 | 208 |
| Toronto 2026-07-11 | 1,504 | 1,239 | 265 |

All 10,251 canonical rows have transaction hash, exchange timestamp,
condition, token, side, price, and positive size. Raw responses, canonical
CSVs, request URLs/times, response hashes, and field-coverage receipts are
retained below the output root.

### Post-fetch correction

The frozen predeclaration incorrectly said the endpoint had no time-window
parameters. The complete official reference page documents `start` and `end`.
The frozen file was not rewritten; a post-fetch correction records the error.
It does not invalidate this fetch: the contract deliberately retained all
returned history, every event fit on its first page, and the local-day filter
was deterministic. No second fetch was made.

`transactionHash` is native provenance but is not documented as a one-to-one
execution ID. The predeclared `(transactionHash, asset, condition)` key had no
collision in this sample, but the repaired scorer therefore uses a fuller
source-independent execution fingerprint and retains the vendor identifiers
as aliases/provenance.

**Mission 1 answer:** historical settled-market executions are retrievable
without a collector change or a forward waiting period. The answer is proven
for this bounded corpus, not for every market or all vendor history.

## Mission 2 - scorer candidate

The candidate scorer now admits WebSocket evidence only when the native event
is exactly `last_trade_price`; `price_change`, nested price-level changes, and
book messages cannot become executions or marks. Data API and WebSocket rows
retain exchange time and its precision, receive/fetch time, taker side,
condition and token, native ID, supplied canonical ID, transaction hash, raw
row hash, and source representations.

Deduplication is alias-aware rather than source-aware. The scorer constructs a
source-independent fingerprint from native identity plus condition, token,
exchange time/precision, price, size, and side; it then reconciles canonical
ID, native ID, transaction hash, and raw-link aliases. Conflicting aliases or
representations fail closed instead of allocating executable size twice. A
matching raw hash is not allowed to conceal contradictory provenance.

Fill matching is side-aware and uses exchange time: a taker `SELL` can fill
only the maker YES bid, a taker `BUY` only the maker YES ask, and both remain
strict trade-through. The additive `mm_execution_evidence_v0.1` columns carry
the execution proof into emitted fills. Any rejected or conflicting execution
evidence blocks fill-evidence completeness.

Focused tests cover exact WebSocket event admission, categorical
`price_change` rejection, raw/CSV and API representation collapse, reverse
alias conflicts, raw-link conflicts, native-only identity, receive-time
validation, side-aware fills, and provenance through materialized fill rows.
The candidate passed 13 focused scorer tests, the existing 32-test
`mm_paper` file, and two targeted integration checks. A direct load of one
retained event returned 1,527 rows with 1,527 unique internal IDs and 1,527
preserved supplied IDs, with no rejection, conflict, or missing-size defect.

No collector or trading surface changed.

| Candidate/test file | SHA-256 |
| :--- | :--- |
| `src/weather/market/mm_paper_scoring.py` | `827f4fa7d9e8d6c5b76cfcfea2bd2917e479ec68096e474cd0673556bb76e8b0` |
| `src/weather/market/mm_paper_constants.py` | `5207b44d657c9b3172b208f9ed6496d589053923a207e7f475ffb2844e4343ef` |
| `src/weather/market/mm_paper.py` | `1af1d575b902f4e5da959bd2102e25f504ed08850b4fd884c948c3f940acdbb6` |
| `tests/market/test_mm_paper.py` | `61516e90ea6eb3d9c584ad90e5d3d28a2ed4a6d5ea4829e04fa1cbd79cd657d9` |
| `tests/market/test_mm_paper_scoring.py` | `2bc138202060be6f034b2069a638f18c83fea661fe5c6d36c27397b420f1d5cb` |

## Mission 3 - frozen counterfactual

The estimator was frozen before fetching trades:

- quote decisions are existing canonical snapshot times;
- the book is the latest capture at or before the decision and no more than
  30 seconds old;
- symmetric tick-rounded, non-crossing YES quotes use 1c, 2c, 3c, and 4c
  half-widths, with 2c primary;
- quote TTL is 60 seconds primary and 120 seconds sensitivity, with
  same-token windows truncated to avoid overlap;
- only unique Data API executions wholly inside the quote interval under their
  one-second timestamp precision are eligible;
- SELL taker executions may fill the maker YES bid, BUY taker executions may
  fill the maker YES ask, and price must be strictly through the quote;
- recorded execution size is consumed once per scenario;
- quote sizes are 20, 50, and 100 contracts; full two-sided reserve is tested
  against $10, $25, and $50 per-band caps without silent resizing;
- 30-minute markout is primary, with 30-second, 1-minute, 5-minute, and
  settlement sensitivities;
- model disagreement is pre-stratified into `<=1c`, `(1c,5c]`, and `>5c`,
  plus the frozen `<=5c` veto;
- every fill decomposes spread capture, maker-rebate economic estimate, and
  adverse selection.

Fill eligibility uses only quote-time-or-earlier snapshots and books.
Executions decide fills only after activation; settlement and future marks are
used only to score an already-fixed fill. With epoch-second Data API time, a
trade is included only when its entire `[second, second+1)` uncertainty
interval is after activation and no later than expiry. A 30-minute mark starts
at that interval's exclusive upper bound plus 30 minutes, then uses the first
available market mark at or after the target. This is deliberately stricter
than assigning the trade to an arbitrary point within its second.

### Measurement result

The admitted run completed in 7.16 seconds and wrote one terminal receipt. It
evaluated six event-days, 1,348 eligible decisions, 48 frozen
width/TTL/size/filter scenarios, 617 scenario-fill rows, and 768 predeclared
strata rows. The 617 rows are scenario-specific sensitivities, not 617
independent exchange executions.

The scorer accepted 2,884 YES-token executions inside the frozen local-day
windows. There were 6,180 decision exclusions for a book older than 30
seconds and 1,096 for no prior book. All 1,348 admitted decisions had their
needed full-book capture. The bound marks contained 150,431 rows. Across all
48 scenarios there were zero missing 30-minute marks, zero missing settlement
rows, zero missing competition rows, and a maximum 30-minute mark lag of 58
seconds.

Primary 2c half-width, 60-second TTL, no disagreement veto:

| Per-band cap | Chosen tier | Pairs | Fills / contracts | Spread | Rebate estimate | 30m adverse selection | Net 30m before rewards | Net settlement before rewards | Event-day mean net, 95% t-interval |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| $10 | none | - | - | - | - | - | - | - | - |
| $25 | 20 | 712 | 13 / 119.043244 | $2.785761 | $0.312616 | $13.264772 | **-$10.166395** | **+$11.222329** | -$1.694399 `[-$6.775181, +$3.386382]` |
| $50 | 50 | 712 | 16 / 209.126576 | $4.792127 | $0.572450 | $26.812122 | **-$21.447545** | **+$20.603662** | -$3.574591 `[-$14.025207, +$6.876026]` |

At $25 the 30-minute adverse-selection cost was 4.28 times spread plus
rebate, or $0.111428 per filled contract; net was -$0.085401 per contract. At
$50 the corresponding values were 5.00 times, $0.128210, and -$0.102558.
Those are adverse point estimates, but neither event-day interval excludes
zero and both settlement totals reverse positive.

The complete cap matrix contains 16 structural $10 cells, 32 complete
measured $25/$50 cells, and zero unknown/no-fill authority cells. The minimum
20-contract tier requires $19.60, $19.20, $18.80, or $18.40 of pair reserve
at 1c, 2c, 3c, or 4c respectively, so no $10 cell fits without silently
resizing.

| Width / TTL | $25 all | $25 <=5c veto | $50 all | $50 <=5c veto |
| :--- | ---: | ---: | ---: | ---: |
| 1c / 60s | -$10.577145 | -$6.248245 | -$23.011949 | -$6.459895 |
| 1c / 120s | -$33.355288 | -$5.690645 | -$67.755369 | -$5.065895 |
| 2c / 60s | -$10.166395 | -$5.979786 | -$21.447545 | -$5.890574 |
| 2c / 120s | -$31.068482 | -$5.221511 | -$63.856788 | -$3.994886 |
| 3c / 60s | -$0.997608 | -$5.576141 | **+$1.153472** | -$5.576141 |
| 3c / 120s | -$8.396186 | -$5.576141 | -$8.630949 | -$5.576141 |
| 4c / 60s | -$1.832184 | -$6.745934 | **+$0.619049** | -$6.745934 |
| 4c / 120s | -$7.388196 | -$6.745934 | -$5.531491 | -$6.745934 |

Thus 30 of 32 measured cells were negative at 30 minutes, but zero had a
negative event-day interval upper bound and zero were negative through
settlement. The two non-negative 30-minute cells were the unfiltered
$50/60-second cases at 3c and 4c.

The frozen calibration strata do not show that the reported 1.12% reliability
ratio protects passive quotes:

| Gap stratum | Tier | Pairs | Fills / contracts | 30m adverse selection | Net 30m | Net / contract | Net settlement |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| <=1c | 20 | 35 | 0 / 0 | $0 | $0 | unknown | $0 |
| (1c,5c] | 20 | 198 | 8 / 47.839407 | $7.161093 | -$5.979786 | -$0.124997 | +$11.220752 |
| >5c | 20 | 479 | 5 / 71.203837 | $6.103679 | -$4.186609 | -$0.058798 | +$0.001576 |
| <=1c | 50 | 35 | 0 / 0 | $0 | $0 | unknown | $0 |
| (1c,5c] | 50 | 198 | 10 / 77.839407 | $7.911093 | -$5.890574 | -$0.075676 | +$23.009965 |
| >5c | 50 | 479 | 6 / 131.287169 | $18.901029 | -$15.556971 | -$0.118496 | -$2.406303 |

The `<=5c` veto is the first two strata. Its 35 `<=1c` pairs produced no
strict-through fills, so the veto's measured P&L comes entirely from
`(1c,5c]` and remains negative at 30 minutes. That is not proof of systematic
pickoff: the veto intervals still cross zero, and settlement is positive.

Geography is also material. In the primary scenario, the US subset was
+$0.632600 at tier 20 and +$0.721813 at tier 50, while Toronto was
-$10.798995 and -$22.169357. The aggregate short-horizon loss is therefore
not geographically stable across the US and Toronto.

| Output | SHA-256 |
| :--- | :--- |
| Coverage | `ff3824836ee41efe83d40bc137bbc64e3bdfe3c4af726e7be11b1c4fc311c8db` |
| Scenarios | `4d7472960ae90ae7c47f709b4b626774244177f444c6472b12b5defd29bd9a2b` |
| Fills | `177f0c3cd14a7a0280d598db6072dbbc69fd410bbfae7883f3f9a052b66d21d5` |
| Cap viability | `4a34b9ca87124df14239dca923f63c0ddf2c901d1d0883d4d9d1df40bb9d8706` |
| Strata | `14ea7b5750fa9f35ffa605740bd7807cd3064d7c60abebc8d4c5934a2a6a7bf8` |

### Capital, inventory, and reward interpretation

The named cap is per pair/band, not total event or fleet capital:

| Metric | $25 cap / tier 20 | $50 cap / tier 50 |
| :--- | ---: | ---: |
| Maximum pair reserve | $19.20 | $48.00 |
| Maximum event quote reserve | $114.76 | $286.90 |
| Maximum fleet quote reserve | $190.78 | $476.95 |
| Maximum event realized gross inventory | 34.719407 | 70.189407 |
| Maximum single-band inventory | 20.00 | 48.88 |
| Maximum event realized worst settlement loss | $11.460800 | $29.760800 |
| Fleet realized worst settlement loss | $33.250880 | $73.462120 |

At tier 20, quote-time competition produced 0.122768 normalized-share
market-days over 0.480300 quote-rest market-days, a 25.56% time-weighted share
proxy. At tier 50 those values were 0.164391 and 34.23%. Offsetting the
primary 30-minute losses would require a uniform historical daily market
allocation of $82.809573 or $130.466946 respectively. Those are break-even
amounts, not observed rewards.

The maker-rebate column is the published weather economic equivalent
`0.0125 * size * price * (1-price)`, not a receipt for a paid rebate.
Polymarket liquidity rewards are competition-normalized and multiplied by a
market-specific allocation. The retained full books can estimate own Q,
observed competing Q, and a normalized share from pre-quote state, but they do
not expose maker identities, per-order minimum eligibility, or the historical
market-dollar allocation. The analysis therefore reports a conservative share
proxy and a break-even uniform daily allocation; it does not invent reward
dollars.

Official economics:

- [Maker rebates](https://docs.polymarket.com/programs/maker-rebates)
- [Liquidity rewards](https://docs.polymarket.com/programs/liquidity-rewards)
- [Positions and settlement](https://docs.polymarket.com/trading/positions/how-positions-work)

## Re-decision

`INCONCLUSIVE_NOT_DECISION_GRADE`

The measurement establishes a real short-horizon adverse-selection problem
at the primary point: spread and the rebate estimate did not carry the $25 or
$50 scenario at 30 minutes. It does **not** establish that market making is
terminally non-viable. The negative fails the frozen closure rule because it
does not survive every width, event-day uncertainty, and settlement horizon.
The US/Toronto split and unknown historical liquidity-reward dollars are
additional non-transferability limits.

The operational decision is therefore:

- retain the scorer candidate and retrospective measurement path;
- do not change the collector, cap, quote size, policy, or trading surface;
- do not promote a market-making strategy;
- leave the track unresolved rather than calling either viability or
  non-viability from six event-days.

A larger outcome-blind settled corpus and historical market reward allocations
would be the decision-grade next evidence. No forward collector change is
required to begin the larger retrospective sample.

## Verification

- Exact base:
  `ce1178bce6b3f5f9ca825bd1fab22c40fef20ab8`.
- Task interpreter: CPython 3.12.13; exact dependency imports and
  `python -m pip check`: pass.
- `python -m weather.market.mm_paper --help`: pass.
- Measurement harness independent pre-run review at exact program hash:
  pass.
- Independent post-run audit recomputed all six output hashes, all 53 input
  hashes, row counts, fill timing/side/capacity, mark timing, P&L
  decomposition, aggregates, and Student-t intervals: pass.
- Measurement harness self-test: pass.
- `tests/market/test_mm_paper.py` plus
  `tests/market/test_mm_paper_scoring.py`: **45 passed in 38.91s**.
- `python -m compileall -q app src tests`: pass.
- `python -m weather.operations.agent_docs_audit`: pass
  (18 agent files, 484 Markdown files).
- `git diff --check`: pass.
- Final receipt/output hash recomputation: pass.

The first direct harness invocation stopped at its scorer-path gate because
the task environment resolved an unregistered `site-packages` source copy.
It stopped before reading the corpus and wrote no measurement output or
receipt. The task-local `.pth` repair made the exact topic-worktree scorer
authoritative; import path, hash, self-test, and host admission were then
rechecked before the single completed measurement.

## NOT-DONE / NOT-REHEARSED

### NOT-DONE

- No claim that six event-days are a decision-grade fleet sample.
- No historical liquidity-reward dollar allocation or actual rebate payout was
  inferred.
- No collector, live/forward capture, policy, quote size, risk cap, trading,
  model, replay, serving, scheduler, release, promotion, or pointer change.
- No PR, merge, or master push.

### NOT-REHEARSED

- Continuous WebSocket coverage, reconnect/gap accounting, or live quote
  lifecycle.
- Queue position or an at-price passive-fill model; the counterfactual requires
  strict trade-through and is intentionally conservative.
- Real exchange order submission, inventory skew/flattening, balance checks,
  cancel-on-silence, kill switches, reward receipt, or withdrawal.
- Profitability outside the frozen six-event pilot.
