# Workstation report - market-making viability - 2026-07-27

## Decision

**`NOT_VIABLE_CURRENT_TRACK` - close the market-making track.**

This is a decision about this repository's current policy, risk envelope, and
evidence path. It is not a claim that two-sided market making is impossible in
principle or that no Polymarket maker can be profitable.

The negative is decision-grade for three independent reasons:

1. The smallest observed reward-qualifying two-sided size cannot fit the
   current per-band risk cap, even at the limiting edge of positive reward
   score.
2. Neither retained reward allocations nor passive-fill-conditional adverse
   selection identify positive after-risk economics at 20, 50, or 100
   contracts. Missing evidence fails closed.
3. The enabled enrichment path can receive real executions, but the current
   loader also treats order-book changes as trades, double-counts raw and
   normalized messages, loses exchange time, and has discontinuous coverage.
   Its tape is not safely scoreable as written.

Mission 2 alone is terminal. The other missions do not talk this result out of
being a negative.

The audit was read-only at exact base
`840771463fbcbdb809c12d5dc3509ecc637040ad`. No collector, trading, sizing,
quoting, model, serving, scheduler, promotion, release, pointer, PR, merge, or
master action was performed.

## Frozen evidence and method

The single output root is
`scratch/workstation-research-output/mm-viability-20260727b`. The project
virtual environment points at a missing Python 3.11 executable, so the bundled
workspace Python 3.12.13 ran the standard-library-only audit. It passed its
self-test and the full read-only run.

| Evidence | SHA-256 |
| :--- | :--- |
| Predeclaration | `e825d18e1f93d28b3a8a41881628162e93b669b522b4a8ac73e22461656b1db3` |
| Host admission | `b7b72c07cf04186b15321d2b7a00a49fc0082c284a223cd68c2399252fe20cad` |
| Audit program | `b0890f0d535a883cf19784b1ebf5b0b970b82ab109bd4228670e8862dd1fe4bb` |
| Input manifest | `94bc31a940dcb20fb37b81197ad8f9d54e4231e6bfebc00c1553b551dbb812ac` |
| Audit JSON | `321a38a143d317ba4cddfd29e3ca397523f4509ad1f2c03f65ce3b4e16563de5` |
| Audit Markdown | `ea5b9974acb4b44f26e931db89ed7db70b8a83f9f618f372f86a4404d9e056f7` |
| Receipt | `f464e5e31167b44818c2ad0357f84ced727f86353193de9b046729cd152d8473` |
| Independent adversarial review | `5a241755a1fd5b97c4a7f96496c086f00089d6c31fe631f18269d4ecaf8ad5a6` |
| Verification receipt | `220c23dbc6da97f9682043e9a58a63e170872d9b52669457010ecf32d822cd47` |
| Retained `mm_paper_report.json` | `c30e33470304831739cd5f2c1f8a99f1ae20c429d1c68ed2b6b1f6550e66ddd6` |
| Retained `mm_known_edge_map.json` | `6187f1107fc6e9bb6cebc436de7efeafce4a0f33d07b9d9cb03f08519b61cc2b` |
| Accepted prior economics audit | `6e230fbab16992a8e1e7976fb4a38daa188db1264cbaaa5cdac93156d74b8f28` |
| Accepted prior Mission 1 result | `715e5d815345b316bb8baef4a1fd0458c22fe38f50d9f22ccc54efac1de93bd2` |

Host admission at `2026-07-27T10:09:55-04:00` found 45.91% committed
memory, 67.28 GiB free on `C:`, no `robocopy`, and the existing explicit
deny-write/delete ACL on `data/` for both the user and sandbox identities.

Verification:

- audit formula self-test: `PASS`;
- full read-only audit and frozen-hash checks: `PASS`;
- `weather.operations.agent_docs_audit`: `PASS` (18 agent files, 482
  Markdown files);
- focused `mm_policy`, `mm_risk`, and `market_microstructure` tests: 109
  passed plus 8 subtests;
- `test_mm_paper.py`: not collected under the fallback Python 3.12 runtime
  because the project environment's NumPy/Pandas wheels are CPython 3.11.
  The project interpreter itself is broken, so no all-tests-green claim is
  made.

## Mission 1 - the known-edge gate

### The premise needs a correction

`known_edge_allowed=false` is not itself a universal no-quote gate.

The current path is:

1. `market_making_run.py:1333-1340` loads policy, promotion state, the
   known-edge map, and watcher state.
2. `market_making_run_support.py:232-283` assembles model, book, source, and
   promotion context, resolves a known-edge record, and applies its permission.
3. `mm_policy.py:809-914` matches the record dimensions and maps permissions.
   A loaded map with no match becomes `no_quote`; a missing map becomes
   `harvest_only`; only `edge_allowed` makes `known_edge_allowed=true`.
4. `mm_policy.py:1332-1344` hard-blocks `known_edge_permission=no_quote`, then
   independently blocks `promotion_state=BLOCK`.
5. `mm_policy.py:1417-1482` permits directional, model-centred quoting only
   with `PASS`, `edge_allowed`, and sufficient edge. `harvest_only` and
   `edge_research` may still reach two-sided, market-mid harvest mode.

The retained report contains 174,504 rows with
`known_edge_allowed=false`, but only 63,272 rows, 36.2582%, have the
known-edge permission as their primary blocker. Its state composition is
159,962 `no_quote/promotion_block` rows and 14,542
`harvest_only/source_freshness_model_gap` rows. Every row also has promotion
state `BLOCK`. Deleting the known-edge veto would therefore reveal the
independent promotion veto, not create a viable maker.

The 93-record map contains 40 `edge_research`, 42 `harvest_only`, 11
`no_quote`, and zero `edge_allowed` records. It also records zero paper fills.

### Original rationale and disposition

The gate's original rationale is sound and narrower than the handoff's
description.

`docs/research/MARKET_MAKING_RESEARCH_AUDIT_2026-06-13.md:47-94` starts from
the model trailing the market. It centres harvest quotes on market mid, uses
the model as a veto, reserves model-skewed quotes for proven slices, and calls
for freshness, inventory, settlement, and adverse-selection protection.
Lines 206-223 explicitly warn that rewards are not alpha and can pay a maker
to accept toxic flow. Its permission matrix at lines 244-255 permits fresh
`SHADOW` harvest while keeping model-skewed quoting behind evidence.
`docs/research/MM_MODEL_READINESS_GAP_PLAN.md:21-25,84-123` repeats that
global model superiority is not required for harvest, but positive
fill-conditioned economics is.

Relevant history:

- `47635d595a6af01b7162c3ca396ea2d7ed3817ad` added the research audit.
- `1d64c3f76c667bc719cd8eefac31674b1ed79fd6` introduced the pure policy and
  harvest/edge separation.
- `1334d700b6e526b2017c8e7457bb31f15fc06aed` added market-wide preflight and
  stale-input blocking.
- `d309544f01747e6f726482a02a517db95b38bfdf` wired generated known-edge
  permissions into policy.
- `90434a85c75fee5b163eb5fbf548793b5c0de371` implemented the information-event
  calendar.

**Disposition: retain the known-edge permission for directional quotes.** It
protects against using an inferior or unproven model to lean into informed
flow. A non-directional maker does not require directional alpha, but it does
require a separate, evidence-backed harvest authority; removing this gate is
not that authority.

### What a safe spread-and-rebate authority would require

A future harvest permission would need all of the following:

- market-mid or independently defensible fair-value centring, with the model
  used only as a disagreement veto until its edge is proven;
- half-spread greater than a conservative passive-fill-conditional toxicity
  bound, plus latency, event, inventory, and operating buffers;
- post-only/no-cross enforcement, minimum depth, maximum spread, and
  cancel/replace TTL;
- explicit per-side, band, event, correlated-regime, fleet, backed-balance,
  worst-settlement, and daily-loss limits;
- settlement-vector inventory across mutually exclusive weather bands,
  reservation-price skew, one-sided flattening, and stop-at-cap behaviour;
- unchanged model/book/source/watcher freshness checks, scheduled-event pulls,
  heartbeat cancel-on-silence, and global/manual kill switches;
- locked-policy, genuine-trade conservative fills and post-fill markouts whose
  lower confidence bound shows spread plus incentives exceed toxicity and
  inventory cost.

That protection is feasible as a design, but it is not complete here.
`mm_policy.py:1190` records `inventory_notional` without using it in the
decision; the input assembler at `market_making_run_support.py:232-283` does
not populate cumulative inventory, event/band notional, or daily loss; and
`_risk_limited_size` at `mm_policy.py:1031-1078` consumes zero fallbacks.
Open-order budget reservation exists, but is not proof of cumulative
settlement-vector inventory control. No inventory reservation-price skew or
positive fill-conditioned proof exists.

### Stale input: operational failure, correct fail-closed response

`NO_QUOTE_STALE_INPUT` is the primary reason for 81,961 rows, 46.9680%.
All those rows carry
`failed:weather_forecast,wu_current,wu_history`; this is not an economic
strategy choice.

The exact 108 final market preflights across the nine selected runs contain:

| Status | Market-days |
| :--- | ---: |
| `PASS` | 47 |
| `STALE` | 49 |
| `BLOCK` | 12 |

The 49 stale market-days split into:

- 36 on July 17-20 whose first failure is model freshness; age is
  3,578.5-18,925.9 seconds, mean 9,215.9, against a 900-second limit;
- 13 on July 22-25 whose first failure is CLOB freshness, with counted gaps
  of 120.0-123.1 seconds against a 120-second limit.

On July 21, all 12 are `BLOCK` because the exchange-economics proof is stale;
nine also first expose model freshness in their ordered gate trace.

`market_making_run_support.py:514-750` classifies these preflights and builds
the forced no-quote record; `market_making_run.py:1471-1502` bypasses the
ordinary policy decision when preflight is not `PASS`.

This is a producer/cadence/SLA fault, not a reason to loosen the thresholds.
It would need repair only if the track survived the independent economics and
tape gates.

### Contextual event gate: 35% overlap, zero primary blocks

The reported 61,875 rows, 35.4582%, are not a fifth disjoint blocker.
`mm_paper.py:1574-1614` labels every already-blocked row whose calendar action
was `suppress` as contextual. Primary event-gate blocks are exactly zero.

| Calendar state | Rows | Share |
| :--- | ---: | ---: |
| Clear | 94,325 | 54.0532% |
| METAR suppress | 29,788 | 17.0701% |
| WU-current widen | 18,304 | 10.4892% |
| Market-close suppress | 11,484 | 6.5809% |
| NWP-release suppress | 10,791 | 6.1838% |
| Resolution suppress | 8,360 | 4.7907% |
| SWOB suppress | 1,452 | 0.8321% |

The gate protects against scheduled jump risk that ordinary age checks cannot
anticipate. With no quote legs or fills, the retained report cannot estimate
avoided toxicity or opportunity cost. Keep it; narrow only from genuine
fill/markout evidence.

## Mission 2 - qualifying-size risk and reward

### Current risk envelope

All nine selected July 17-25 run configurations agree on:

- quote size: 5 contracts;
- harvest half-spread: $0.01;
- per-band notional cap: $10;
- per-event notional cap: $25;
- daily loss cap: $25;
- aggregate run budget: $500;
- release identity: `research_unbound_non_countable`.

The applicable retained global-market audit covers 1,188 band markets. Every
observed reward minimum is 20, 50, or 100 contracts; none is at or below the
policy's five contracts. Its July 17-25 historical reward allocation is
`UNKNOWN_NOT_ZERO`, not zero.

The current non-directional path is two-sided. For `C` contracts, midpoint
`m`, and half-spread `h=.01`, it reserves:

`R_pair = C[(m-h) + (1-(m+h))] = 0.98C`.

This is the same expression used by `mm_policy.py:1275-1318` and
`market_making_run_support.py:776-786`.

| Contracts | Pair reserve, one band | Central one-side full loss | One band in each of 12 events | $10 band | $25 event | $500 fleet |
| ---: | ---: | ---: | ---: | :---: | :---: | :---: |
| 20 | $19.60 | $9.80 | $235.20 | fail | pass | pass |
| 50 | $49.00 | $24.50 | $588.00 | fail | fail | fail |
| 100 | $98.00 | $49.00 | $1,176.00 | fail | fail | fail |

The current $10 band cap can admit at most `10/.98 = 10.204082` paired
contracts before existing exposure. That is below every observed reward
minimum.

This is not an artefact of using a one-cent spread. The observed reward
cutoff is 4.5 cents from adjusted midpoint. Polymarket scores proximity as
`S(v,s)=((v-s)/v)^2`, so score is zero at `s=v`; positive score requires
`s<.045`. A positive-scoring pair therefore reserves strictly more than
`C(1-2*.045)=.91C`: more than $18.20, $45.50, or $91.00 for 20, 50, or 100.
All still violate the $10 band cap.

If five separate bands were kept at qualifying size, the gross open-order
reserve would be $98/$245/$490 per weather event and
$1,176/$2,940/$5,880 across 12 events. This is a scenario, not a claim that
exactly five bands must always be active; one band is already enough to fail
the controlling cap.

### One-sided inventory does not rescue an edgeless strategy

For one filled buy of `C` outcome tokens at price `p`:

- capital and full settlement loss if wrong are `Cp`;
- settlement P&L is `C(1-p)` if it pays $1 and `-Cp` if it pays $0;
- conditional expected P&L before incentives is `C(q_fill-p)`, where
  `q_fill=P(pays $1 | passive fill, state, size)`.

| Contracts | Full loss at p=.10 | p=.50 | p=.90 | 12-event exposure at p=.50 |
| ---: | ---: | ---: | ---: | ---: |
| 20 | $2 | $10 | $18 | $120 |
| 50 | $5 | $25 | $45 | $300 |
| 100 | $10 | $50 | $90 | $600 |

One side can fit the $10 band cap only at `p<=.50`, `.20`, or `.10` for
20, 50, or 100 contracts. But `mm_policy.py:1417-1471` makes one-sided
quoting the directional-edge path, not the spread/rebate-only path. The
published liquidity formula also divides a central single-sided score by
three and gives it zero score outside midpoint `[.10,.90]`, where two sides
are required. One-sided qualification therefore reintroduces the unavailable
directional claim and cannot hedge toxic fills with paired spread capture.

### Own calibration cannot identify adverse selection

No `artifacts/releases/current_release.json` exists. The newest direct
checked-in calibration artifacts are unconditional:

| Artifact | Rows | Model Brier | Market Brier | Skill vs market |
| :--- | ---: | ---: | ---: | ---: |
| F-family, `6967be77...f19` | 96,041 | 0.059844 | 0.040325 | -0.484056 |
| Seattle, `8d1a0c67...3c6` | 7,788 | 0.063978 | 0.035499 | -0.802239 |
| C-family, `5d1cdcdb...207` | 4,763 | 0.053604 | 0.040137 | -0.335528 |

None contains a fill, trade, queue, markout, execution, or adverse-selection
field. The retained paper report has zero quote legs, zero fills, vacuous
`BLOCK/no_quote_legs` evidence, and no markout slices.

The newer checked-in skill-gap audit reinforces the direction of caution over
206,745 rows and 18,793 partitions: model Brier 0.0620561 versus market
0.0373686, with 98.8767% of the gap attributed to
resolution/missing-information and only 1.1233% to reliability. It remains an
unconditional evaluation.

These are the repository's own calibration results, and they do not identify
`q_fill`. Unconditional calibration must not be converted into a dollar
passive-fill toxicity estimate. The comparison is unfavorable to the model,
but that is supporting caution rather than a manufactured expected loss.

### What the published programs pay

The [Polymarket positions contract](https://docs.polymarket.com/concepts/positions-tokens)
confirms that a winning outcome token redeems for $1 and a losing token for
$0.

Under the [Maker Rebates Program](https://docs.polymarket.com/programs/maker-rebates),
weather has taker fee rate `.05`, maker fee zero, and 25% of taker fees
distributed fee-curve-weighted per market. For a filled maker order:

`fee_equivalent = .05 C p(1-p)`

and the pre-rounding rebate equivalent attributable under the 25% pool is:

`R_rebate = .0125 C p(1-p)`.

| Contracts | Rebate at p=.10 | p=.50 | p=.90 |
| ---: | ---: | ---: | ---: |
| 20 | $0.02250 | $0.06250 | $0.02250 |
| 50 | $0.05625 | $0.15625 | $0.05625 |
| 100 | $0.11250 | $0.31250 | $0.11250 |

At those prices, a full one-sided settlement loss is about 88.9x, 160x, or
800x the same-size rebate. Rebate eligibility requires the resting order to
be filled; a resting quote alone earns none. The minimum accrued payout is
$1.

If both current one-cent sides fill in matched size, gross spread capture is
$0.40/$1.00/$2.00 and the two-fill rebate equivalent near `.50` is
$0.125/$0.3125/$0.625, for $0.525/$1.3125/$2.625 before adverse selection.
That is a paired-fill illustration, not a profit estimate; the unresolved
problem is which side fills first and why.

The [Liquidity Rewards methodology](https://docs.polymarket.com/programs/liquidity-rewards)
does not attach a fixed dollar payment to 20, 50, or 100 contracts. It scores
size and proximity, favours balanced quoting, normalizes each maker against
competitors, and multiplies the final share by a market-specific allocation.
The [raw rewards endpoint](https://docs.polymarket.com/api-reference/rewards/get-raw-rewards-for-a-specific-market)
returns present and future configurations. The accepted prior audit retained
no July 17-25 `rate_per_day`; a settled empty result cannot prove a historical
zero.

### Mission 2 answer

**No qualifying size is evidenced to have reward plus rebate greater than
expected adverse selection inside the current risk envelope.**

The minimum two-sided positive-score size is structurally incompatible with
the per-band cap. Low-price one-sided orders sometimes fit, but are
directional, score less or zero depending on midpoint, and lack
fill-conditional economics. Reward dollars and `q_fill` are both unidentified.
The capital expansion is therefore not proportionate to any proven payout.
Under the predeclared missing-evidence rule, Mission 2 is independently
`NOT_VIABLE`.

## Mission 3 - will the enabled tape score?

### Vendor channel: yes, genuine executions exist

The official [market stream](https://docs.polymarket.com/market-data/realtime-data#market-stream)
distinguishes:

- `book`: an order-book snapshot;
- `price_change`: changed price-level size;
- `last_trade_price`: an execution containing token, price, executed size,
  side, timestamp, and transaction hash.

So the absence of trades in one bounded sample does not mean the channel
cannot emit trades. `last_trade_price` is genuine scoreable source material.
`book` and `price_change` are not execution proof.

### Current repository path: not scoreable as written

`market_microstructure_capture.py:1719-1771` expands every
`price_changes[]` child into a normalized row with `price` and `size`, and
also preserves top-level events. Lines 1774-1845 write both normalized CSV
and a raw JSON wrapper.

`mm_paper_scoring.load_trade_rows` at lines 759-851:

- accepts any row with parseable time, token, and price;
- treats positive `size` on a `price_change` as execution size;
- never checks `event_type`;
- reads `market_ws_events.csv` and `market_ws.jsonl`;
- expands nested `price_changes`, `trades`, and `fills`;
- assigns source/index IDs rather than a vendor execution identity;
- never deduplicates the raw and normalized copies.

The strict crossing rule at lines 854-859 and fill loops at 1451-1468 and
1561-1582 do require a price strictly through the quote and positive size.
That rule is conservative only after its input is known to be a unique
execution. Here, an order-level change can falsely satisfy it, and a real
trade can be consumed more than once.

The normalized schema maps `timestamp_utc` and `trade_time_utc`, not the
vendor's `timestamp`, and has no transaction-hash column. Normalized trade
rows therefore fall back to receive time for quote-window eligibility.

The armed task samples each market for at most 20 seconds on a 900-second
loop (`scripts/ops/register_clob_enrichment.ps1:29-35,50-58`): at most
2.2222% time coverage per market, less if the 400-message cap fires. It cannot
distinguish no trade from not listening. The code's initial subscription form
also differs from the current documented market-topic example; retained
samples show it was accepted, so this is a compatibility risk rather than the
decisive fault.

The accepted July 11 fallback receipt makes the contamination concrete:
25,080 rows had the generic loader's price/size shape across 12 markets, while
only 12 were exact `last_trade_price` events.

**Verdict: `CURRENT_ENABLED_TAPE_NOT_SCOREABLE`.**

### Minimum future trade-evidence contract

No collector change was made. A future specification should require:

1. Accept only exact `last_trade_price` events or validated public
   [Data API `/trades`](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
   records as executions. Categorically reject `book` and `price_change`.
2. Retain source/schema, event slug, condition ID, token/asset ID, price in
   pUSD per share, positive size in contracts, side, vendor exchange timestamp
   with units, receive/fetch timestamp, transaction hash/native ID, and raw
   payload hash.
3. Build one canonical execution fingerprint and deduplicate normalized/raw
   copies and overlapping API pages before allocating trade size.
4. Prove continuous WebSocket coverage from quote activation through expiry
   with subscription acknowledgement, heartbeats, reconnects, and a gap
   ledger; alternatively prove complete bounded Data API start/end pagination.
   A gap means `UNKNOWN/exclude`, never no-fill.
5. Validate token-to-condition-to-event mapping, price range, positive size,
   monotonic clocks, and use exchange time for quote-window eligibility.
6. Retain append-only raw payloads plus pre/post completeness receipts.
7. Add negative fixtures proving `book`/`price_change` can never fill and a
   deduplication fixture proving one trade is consumed once.

The Data API is appropriate for bounded backfill and reconciliation because
it exposes market condition, asset, size, price, timestamp, side, and
transaction hash with time-window pagination. Continuous WebSocket capture is
preferable for millisecond quote-window timing.

## Independent challenge and closure rule

The integrated conclusion was sent for an adversarial read-only challenge
with three explicit escape routes: find a qualifying size inside current
caps, show the tape is safely scoreable as written, or show that the
known-edge interpretation was overstated.

The reviewer found one real counterexample to a too-broad cap claim.
Polymarket gives reduced single-sided score at central midpoints, so nominal
cap-fitting qualifying orders exist: 20 contracts at `.49` reserve $9.80,
50 at `.19` reserve $9.50, and 100 at `.09` reserve $9.00. One such band in
each of 12 events reserves $117.60, $114, or $108.

This narrows the argument exactly as the report now states: the strict
`>.91C` and current `.98C` cap contradictions apply to the implemented
**two-sided harvest** path, not every theoretical order. The counterexample
does not rescue the track because one-sided quoting is the unavailable
directional path, has no guaranteed paired spread capture, earns reduced
score, and still has neither historical reward dollars nor an identified
`q_fill`. Its rebate equivalents at those prices are only about
$0.0625/$0.0962/$0.1024 per fill.

The reviewer found no other factual or arithmetic error. The known-edge
correction is sound, and the tape still categorically admits non-trades and
lacks execution deduplication. Final adversarial disposition:
**`NOT_VIABLE_CURRENT_TRACK` survives.**

## NOT-DONE / NOT-REHEARSED

### NOT-DONE

- No new market, book, trade, reward, weather, or settlement observation.
- No empirical passive-fill adverse-selection estimate; the required tape is
  not trustworthy.
- No historical July reward allocation was invented and no
  `polymarket_us` reward formula was transferred to the global tape.
- No collector, scorer, policy, risk, quote-size, scheduler, or code change.
- No model fit, replay, serving, release, promotion, pointer, live trade, PR,
  merge, or master push.

### NOT-REHEARSED

- Any reward-qualifying quote at 20, 50, or 100 contracts.
- Continuous genuine-trade capture, reconnect/gap accounting, or Data API
  completeness.
- Fill simulation from deduplicated exchange-time executions.
- Inventory skew, cumulative settlement-vector caps, flattening, kill switch,
  cancel-on-silence, account/balance, or live lifecycle controls.
- Reward receipt, rebate payout, or profitability under live competition.

## Final handback

Retain directional known-edge protection. Do not spend engineering effort
repairing freshness or enriching the tape for this track unless the operator
deliberately reopens it with a new risk envelope and a predeclared reason to
believe reward dollars can cover passive-fill toxicity.

At the current caps and evidence standard, market making is not viable. This
negative closes the queue.
