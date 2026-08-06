# Workstation report 2026-08-06 — close the maker evidence gap

## Verdict

**NO-GO at P0: the public API cannot reconstruct the known 2.165004-second gap
EXACTLY. The available retrospective results are INDICATIVE only; they cannot
recover every trade and every order-book change. Do not register or start
`WeatherMakerExecutionCapture`.**

The gap is `2026-08-06T00:08:24.636461-04:00` through
`2026-08-06T00:08:26.801465-04:00`, equivalently
`2026-08-06T04:08:24.636461Z` through `04:08:26.801465Z`, epoch seconds
`1785989304.636461` through `1785989306.801465`, and exact epoch microseconds
`1785989304636461` through `1785989306801465`. An all-fleet public Data API
trade query over the enclosing epoch seconds returned HTTP 200 with `[]`. A
separate public `GET /orderbook-history` route returned 101 millisecond-stamped
snapshots inside truncated millisecond bounds, but Polymarket documents no
completeness, loss-detection, sequencing, response, or retention contract for
that route. Neither result proves continuity: no public historical endpoint
replays the `price_change` events that encode every order placement and
cancellation.

The premise is therefore falsified exactly where the handoff required. P1 was
not implemented, P2 was not soaked, and the settlement-continuity gate remains
unchanged. Prompt reconciliation cannot fix this API limitation: the
retrospective **exact-replay** retention horizon exposed by the public API is
**none (effectively zero seconds)**. The snapshot-history route has an
empirical retention lower bound, reported below, but remains indicative.

## P0 — public API capability audit

### Scope and method

The reservation source was checked before the measurement and says that no
dates are currently reserved. The audit covered the complete retained maker
fleet for target date 2026-08-06: 12 events, 132 binary conditions, and 264
tokens. The event/token registry is byte-identical at `75882434` and
`origin/master @ 4aecdb71` (Git blob
`f732dd5d311ddae23a5c32da3e45922c7c6f42d6`).

| Market | Event ID |
| --- | ---: |
| Toronto | `798945` |
| NYC | `798947` |
| Atlanta | `798963` |
| Austin | `798966` |
| Chicago | `798965` |
| Dallas | `798958` |
| Denver | `798967` |
| Houston | `798968` |
| Los Angeles | `798969` |
| Miami | `798964` |
| San Francisco | `798970` |
| Seattle | `798946` |

Every network request was an unauthenticated read-only GET to a public market
data endpoint. No order, cancellation, user channel, authenticated trade
endpoint, API key, wallet, or credential was used.

### Endpoint and response-shape result

| Surface | Exact request/contract | Response shape and granularity | P0 result |
| --- | --- | --- | --- |
| Public Data API trades | `GET https://data-api.polymarket.com/trades?eventId=<comma-separated-event-ids>&start=1785989304&end=1785989307&limit=10000&takerOnly=true` | Array rows containing `proxyWallet`, `side`, `asset`, `conditionId`, `size`, `price`, integer epoch-second `timestamp`, event/outcome metadata, and `transactionHash` | **INDICATIVE, not exact.** Whole-second time cannot place an execution against the microsecond gap bounds or reproduce the WebSocket's millisecond timestamp/local sequence. `transactionHash` is provenance but is not documented as a one-to-one execution ID. No book changes are returned. |
| CLOB price history | `GET https://clob.polymarket.com/prices-history?market=<token_id>&startTs=1785989304.636461&endTs=1785989306.801465&fidelity=1` | `{"history":[{"t": <epoch-seconds>, "p": <price>}]}`; `fidelity` is expressed in minutes and defaults to one minute | **SAMPLED/INDICATIVE, not exact.** It has no size, side, transaction identity, book levels, or order/cancel changes. |
| CLOB order-book history | `GET https://clob.polymarket.com/orderbook-history?asset_id=<token_id>&startTs=1785989304636&endTs=1785989306801&limit=1000&offset=0` | Empirical `{"count":N,"data":[<full-book-snapshot>]}`; each snapshot has a string epoch-millisecond `timestamp`, `hash`, bid/ask levels, and current-book metadata | **INDICATIVE, not exact.** The official error reference names only `startTs`, `asset_id` or `market`, and `limit <= 1000`; it does not define the response, units, completeness, ordering, pagination, loss detection, or retention. Millisecond filtering also cannot express the microsecond gap bounds exactly. |
| CLOB book REST | `GET https://clob.polymarket.com/book?token_id=<token_id>`; batch equivalent `POST /books` | Current aggregated snapshot: `market`, `asset_id`, `timestamp`, `hash`, `bids[{price,size}]`, `asks[{price,size}]`, `min_order_size`, `tick_size`, `neg_risk`, `last_trade_price` | **CURRENT STATE ONLY.** There is no historical timestamp/window/cursor parameter and no event history. A before/after snapshot cannot reveal intermediate changes that net to the same state. |
| Public market WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market`; subscription body has `assets_ids` and `type=market` | Live `book`, `price_change`, and `last_trade_price` messages with millisecond timestamps | **EXACT ONLY WHILE CONNECTED AND RETAINED.** The public contract exposes no start time, resume cursor, or historical replay. Reconnect supplies current/live state, not missed messages. |

The official contracts are:

- [Data API trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
- [CLOB prices history](https://docs.polymarket.com/api-reference/markets/get-prices-history)
- [CLOB error reference, including `GET orderbook-history`](https://docs.polymarket.com/resources/error-codes)
- [CLOB current order book](https://docs.polymarket.com/api-reference/market-data/get-order-book)
- [CLOB current batch order books](https://docs.polymarket.com/api-reference/market-data/get-order-books-request-body)
- [Public market WebSocket](https://docs.polymarket.com/api-reference/wss/market)

The WebSocket conclusion is an inference from the complete documented public
surface: the channel is explicitly real-time and its subscription schema has no
replay control. The normal REST order-book endpoints expose current snapshots
only. The error-code page mentions `GET orderbook-history`, but neither the API
reference, official documentation index, public SDK surface, nor rate-limit
table defines that route as a lossless event replay. Its empirical snapshots
cannot be promoted into a completeness guarantee that Polymarket does not make.

### Empirical known-gap result

The all-fleet Data API query deliberately used `[1785989304, 1785989307]` so
the whole microsecond-bounded gap is inside the queried seconds. It returned:

```json
[]
```

The unindexed `/orderbook-history` route was then queried separately for all
264 fleet tokens with the truncated millisecond bounds
`[1785989304636, 1785989306801]`, `limit=1000`, and `offset=0`. All 264 requests
returned HTTP 200. The API reported 101 snapshots across 52 tokens at 60 unique
timestamps, from `1785989304640` through `1785989306707`. Every per-token count
was at most 101, so the API's 1000-row page limit was not reached. Snapshot
support by market was Chicago 19, Dallas 2, Denver 9, Houston 4, Los Angeles 22,
Miami 12, NYC 3, San Francisco 24, Toronto 6, and zero for Atlanta, Austin, and
Seattle.

The empirical response schema was the following (schematic values, not a row
transcript):

```json
{
  "count": 1,
  "data": [
    {
      "market": "<condition-id>",
      "asset_id": "<token-id>",
      "timestamp": "1785989304640",
      "hash": "<book-hash>",
      "bids": [{"price": "0.45", "size": "10"}],
      "asks": [{"price": "0.46", "size": "20"}],
      "min_order_size": "5",
      "tick_size": "0.01",
      "neg_risk": false,
      "last_trade_price": "0.45"
    }
  ]
}
```

That is useful historical state, but it is not a replay proof. Rows contain no
event type, delta/cause, order ID, trade side/size/hash, prior-sequence pointer,
or completeness marker. The `startTs`/`endTs` filters and returned timestamps
are only millisecond-precise: the floored bounds differ from the source
boundaries by 0.461 ms at the start and 0.465 ms at the end. Because the route's
boundary-inclusion semantics are undocumented, those boundary fractions cannot
be classified exactly. Most importantly, the server gives no contract that
every `price_change` produced a snapshot. The 101 rows are therefore a complete
retrieval of what this API reported for the supplied filters, not proof of every
matching-engine change. The route was empirically usable with `asset_id`; a
valid condition-ID `market` probe returned HTTP 400 despite that parameter being
named in the error reference, further underscoring the lack of a stable public
contract.

A positive-control window, `[1785989244, 1785989367]`, was then queried once
per event under the same public contract. It returned 16 Miami rows and zero
rows for the other 11 events. The rows had integer-second timestamps; several
distinct transaction hashes shared `1785989274`. This proves that the endpoint
and event identifiers were live while also demonstrating the lost subsecond
ordering. The support is D=1 target date, M=12 markets, 12 market-days, 132
conditions, and 264 tokens.

For a Miami token with nearby positive-control trades
(`15332633911667325118121586693747338564353024644825829348764813223409126388999`),
the exact-gap `/prices-history` request returned only a `t`/`p` history point;
the tested response was not an execution or book-event tape.

The empty trade array means only “the Data API published no trade row in the
enclosing seconds.” It cannot prove that no order was placed or cancelled, no
book level changed and reverted, or no transient queue state affected
counterfactual fills. Those events are visible as live `price_change` messages
while connected and are absent from every retrospective response above.

### Why the settlement-continuity gate cannot pass

1. The missing interval may contain order placements or cancellations with no
   trade. `/trades` and `/prices-history` do not carry them.
2. A reconnect snapshot binds only the resulting book. Multiple intermediate
   paths, including a change followed by its reversal, produce the same result.
3. Public retrospective trade rows lose the source millisecond timestamp and
   connection-local ordering required by the canonical execution tape.
4. Minute-fidelity `t`/`p` samples cannot support strict counterfactual fill
   attribution.
5. `/orderbook-history` returns millisecond snapshots without a sequence or
   completeness contract, and its filters cannot encode the microsecond bounds.

Marking such a splice “exactly covered” would therefore be false and would
corrupt downstream maker P&L. The unchanged zero-gap continuity rule correctly
continues to reject this session.

### Retention horizon

| Evidence | Public retrospective horizon | Consequence |
| --- | --- | --- |
| Exact trades **and every book change** | **No lossless replay contract is exposed; effectively zero seconds** | P0 fails even for an immediate reconnect. There is no exact backfill design to implement. |
| Data API market/event trade rows | Documented as approximately the most recent **three years** | Useful for bounded retrospective trade analysis, but second-precision trades alone cannot close continuity. |
| `/prices-history` samples | No retention guarantee stated in the official endpoint contract | Whatever samples remain are still only `t`/`p` aggregates and cannot become exact evidence. |
| `/orderbook-history` snapshots | **No documented horizon.** Empirically the known gap remained readable at least **12 h 17 m 09.198535 s** after it ended. | This is a lower bound for indicative snapshot availability, not a completeness or future-retention guarantee. |
| `/book`, `/books`, market WebSocket | Current/live only; no documented retrospective replay | Exact book evidence must be captured continuously at event time. |

The trade endpoint's approximate three-year window and the snapshot route's
empirical lower bound are not the horizon of an exact backfill. The load-bearing
exact-replay horizon is none.

That empirical lower bound uses the HTTP `Date` value from a nonempty Toronto
gap-snapshot response, `2026-08-06T16:25:36Z`, minus the exact gap end,
`2026-08-06T04:08:26.801465Z`. That response returned HTTP 200 with three rows
for token
`54154421552674617436912803891331752657171436628211836980484290480640026577307`.
It is an observation time, not a promised expiry or retention floor.

## P1 and P2 — hard-stopped

P1 was not implemented because P0 did not pass exactly. No schema was bumped,
no receipt was changed, no backfilled row was written, and no source or test
file was edited for a backfill.

P2 was not run. A soak cannot validate an implementation that correctly does
not exist, and a gap-free soak would merely repeat the rejected lottery. The
settlement-continuity gate, `harvest_only` promotion rule, and every other gate
remain byte-for-byte unchanged by this mission.

This is a deterministic API-capability falsifier, not a population-effect
estimate. No confidence interval is claimed. Crossed date × market clustering
is therefore not applicable; the full fleet support is reported so the scope
of the falsifier remains explicit.

## Roll verdict

The retained runtime identities are the same authoritative arrays used by the
carried `-09-25a` report:

| Closure | Retained commit | Loaded source files |
| --- | --- | ---: |
| Snapshot | `64273c2ed4a9` | 77 |
| CLOB | `64273c2ed4a9` | 23 |
| Observation trigger | `64273c2ed4a9` | 85 |
| CLOB enrichment | `5c004c4554d8` | 21 |

The new report is Markdown and enters none of the four closures. The cumulative
branch also carries the requested `75882434` dependency. Its only path in any
retained closure is the purely additive `src/weather/schema_registry_data.py`,
which enters all four and therefore requires a coordinated quiet-window roll if
the branch is ever integrated. No integration is performed here.

| Changed path versus `origin/master` | Snapshot | CLOB | Observation | Enrichment | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `README.md` | no | no | no | no | roll-free |
| `docs/operations/HOST_LOAD_POLICY.md` | no | no | no | no | roll-free |
| `docs/operations/OPERATIONS_DESIGN.md` | no | no | no | no | roll-free |
| `docs/operations/closed-market-day-parquet-archive-contract.md` | no | no | no | no | roll-free |
| `docs/operations/data-storage-class-contract.md` | no | no | no | no | roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-close-the-maker-evidence-gap.md` | no | no | no | no | roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-narrow-the-maker-producer.md` | no | no | no | no | roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-respecify-the-maker-settlement-gate.md` | no | no | no | no | roll-free |
| `scripts/ops/AGENTS.md` | no | no | no | no | roll-free |
| `scripts/ops/register_mm_execution_capture.ps1` | no | no | no | no | roll-free |
| `src/weather/market/market_making_model_variants.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_day_countability.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_execution_capture.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_aggregation.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_constants.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_reports.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_scoring.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_reward_q_share.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_day_projection_registry.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_market_day_archive.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_market_day_archive_manifest_contract.py` | no | no | no | no | roll-free |
| `src/weather/operations/event_day_manifest.py` | no | no | no | no | roll-free |
| `src/weather/operations/storage_classes.py` | no | no | no | no | roll-free |
| `src/weather/reporting/market/trading_evidence.py` | no | no | no | no | roll-free |
| `src/weather/schema_registry_data.py` | **yes** | **yes** | **yes** | **yes** | coordinated quiet-window roll |
| `tests/market/test_mm_day_countability.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_execution_capture.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_paper.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_paper_scoring.py` | no | no | no | no | roll-free |
| `tests/operations/test_closed_day_projection_tiering.py` | no | no | no | no | roll-free |
| `tests/operations/test_closed_market_day_archive.py` | no | no | no | no | roll-free |
| `tests/operations/test_event_day_archive_coverage.py` | no | no | no | no | roll-free |
| `tests/operations/test_event_day_manifest.py` | no | no | no | no | roll-free |
| `tests/operations/test_register_mm_execution_capture_script.py` | no | no | no | no | roll-free |
| `tests/operations/test_schema_registry.py` | no | no | no | no | roll-free |
| `tests/operations/test_storage_classes.py` | no | no | no | no | roll-free |
| `tests/reporting/test_trading_evidence.py` | no | no | no | no | roll-free |

## Verification

- reserved-confirmation-window runtime check: **PASS — none reserved**;
- exact all-fleet Data API gap query: **HTTP 200, `[]`**;
- exact-gap `/orderbook-history` probe: **264/264 HTTP 200; 101 returned
  snapshots across 52 tokens and 60 millisecond timestamps; INDICATIVE only**;
- 123-second all-fleet positive control: **HTTP 200, 16 rows across 12
  event queries; integer-second timestamps reproduced**;
- exact-gap `/prices-history` shape probe: **HTTP 200, `history[{t,p}]` only**;
- P1 implementation: **not run — blocked by P0**;
- P2 soak: **not run — blocked by P0**;
- focused carried-dependency tests: **31 passed** with bundled CPython 3.12.13,
  its compatible NumPy/Pandas wheels, and the retained pure-Python pytest 9.0.3;
- documentation audit: **one pre-existing failure**, the known missing source
  link in `agent-report-2026-08-02-workstation-spec-contract-repair.md`; this
  report adds no missing link; and
- `git diff --check`: **PASS**.

## What was not done

- no P1 implementation, receipt/schema change, or backfill write;
- no P2 soak, new evidence root, capture loop, producer, or supervisor run;
- no registration, scheduled-task creation/mutation/start, scheduling, or restart;
- no production, mirror, `D:\weather-mirror`, or `data/` write;
- no credential read, API key, wallet, authenticated endpoint, user channel,
  order, cancellation, trade, promotion, or live execution;
- no reserved-date consumption or enumeration;
- no relaxation of settlement continuity, `clob_freshness`, `harvest_only`,
  promotion, or any other gate;
- no edit to a concurrent-owner file;
- no PR, no integration merge, no merge to `master`, no force-push, and no
  branch deletion.

## Reproduction and handback verification

These commands use paths that exist on the production host. The API commands
are unauthenticated read-only GETs and write no response to disk. They do not
register or start anything.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather

$branch = "origin/codex/workstation-close-the-maker-evidence-gap-2026-09-27a"
git fetch origin codex/workstation-close-the-maker-evidence-gap-2026-09-27a
git merge-base --is-ancestor 75882434 $branch
git merge-base --is-ancestor 4aecdb71 $branch
git log --oneline --decorate "origin/master..$branch"
git diff --check "origin/master...$branch"
git diff --name-status "origin/master...$branch"
git show "$branch`:docs/roadmap/agent-report-2026-08-06-workstation-close-the-maker-evidence-gap.md"

$eventMap = [ordered]@{
  toronto = "798945"; nyc = "798947"; atlanta = "798963";
  austin = "798966"; chicago = "798965"; dallas = "798958";
  denver = "798967"; houston = "798968"; "los-angeles" = "798969";
  miami = "798964"; "san-francisco" = "798970"; seattle = "798946"
}
$events = @($eventMap.Values) -join ","
$tradeUri = "https://data-api.polymarket.com/trades?eventId=$events&start=1785989304&end=1785989307&limit=10000&takerOnly=true"
(Invoke-WebRequest -UseBasicParsing -Method Get -Uri $tradeUri).Content

$token = "15332633911667325118121586693747338564353024644825829348764813223409126388999"
$historyUri = "https://clob.polymarket.com/prices-history?market=$token&startTs=1785989304.636461&endTs=1785989306.801465&fidelity=1"
(Invoke-WebRequest -UseBasicParsing -Method Get -Uri $historyUri).Content

$marketIds = @(
  "toronto", "nyc", "atlanta", "austin", "chicago", "dallas",
  "denver", "houston", "los-angeles", "miami", "san-francisco", "seattle"
)
$config = git show "$branch`:config/location_market_events.json" |
  Out-String | ConvertFrom-Json
$tokenRows = foreach ($marketId in $marketIds) {
  $location = $config.locations | Where-Object { $_.location_id -eq $marketId }
  $event = $location.active_events | Where-Object { $_.event_date -eq "2026-08-06" }
  foreach ($market in $event.markets) {
    foreach ($outcome in $market.outcomes) {
      [pscustomobject]@{
        market_id = $marketId
        token_id = [string]$outcome.token_id
      }
    }
  }
}
$bookRows = @()
$bookResults = foreach ($tokenRow in $tokenRows) {
  $uri = "https://clob.polymarket.com/orderbook-history?asset_id=$($tokenRow.token_id)&startTs=1785989304636&endTs=1785989306801&limit=1000&offset=0"
  $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $uri
  $payload = $response.Content | ConvertFrom-Json
  foreach ($row in @($payload.data)) {
    $bookRows += [pscustomobject]@{
      market_id = $tokenRow.market_id
      timestamp = [string]$row.timestamp
    }
  }
  [pscustomobject]@{
    market_id = $tokenRow.market_id
    token_id = $tokenRow.token_id
    status_code = [int]$response.StatusCode
    response_date = [string]$response.Headers["Date"]
    count = [int]$payload.count
  }
  Start-Sleep -Milliseconds 100
}
[pscustomobject]@{
  token_requests = @($bookResults).Count
  http_200 = @($bookResults | Where-Object { $_.status_code -eq 200 }).Count
  reported_rows = ($bookResults | Measure-Object -Property count -Sum).Sum
  returned_rows = @($bookRows).Count
  nonempty_tokens = @($bookResults | Where-Object { $_.count -gt 0 }).Count
  page_limit_hits = @($bookResults | Where-Object { $_.count -ge 1000 }).Count
  unique_timestamps = @($bookRows.timestamp | Sort-Object -Unique).Count
  minimum_timestamp = ($bookRows.timestamp | Measure-Object -Minimum).Minimum
  maximum_timestamp = ($bookRows.timestamp | Measure-Object -Maximum).Maximum
  earliest_nonempty_response_date = ($bookResults |
    Where-Object { $_.count -gt 0 } |
    Sort-Object { [datetime]$_.response_date } |
    Select-Object -First 1).response_date
}
$marketCounts = foreach ($marketId in $marketIds) {
  [pscustomobject]@{
    market_id = $marketId
    snapshots = @($bookRows | Where-Object { $_.market_id -eq $marketId }).Count
  }
}
$marketCounts | Format-Table -AutoSize

$controlRows = @()
$controlResults = foreach ($entry in $eventMap.GetEnumerator()) {
  $uri = "https://data-api.polymarket.com/trades?eventId=$($entry.Value)&start=1785989244&end=1785989367&limit=10000&takerOnly=true"
  $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $uri
  $payload = @($response.Content | ConvertFrom-Json)
  foreach ($row in $payload) {
    $controlRows += [pscustomobject]@{
      market_id = [string]$entry.Key
      timestamp = $row.timestamp
      transaction_hash = [string]$row.transactionHash
    }
  }
  [pscustomobject]@{
    market_id = [string]$entry.Key
    status_code = [int]$response.StatusCode
    count = @($payload).Count
  }
}
[pscustomobject]@{
  event_requests = @($controlResults).Count
  http_200 = @($controlResults | Where-Object { $_.status_code -eq 200 }).Count
  rows = @($controlRows).Count
  integer_timestamps = @($controlRows | Where-Object { $_.timestamp -is [int] -or $_.timestamp -is [long] }).Count
  support_by_market = @($controlResults | Where-Object { $_.count -gt 0 } |
    ForEach-Object { "$($_.market_id)=$($_.count)" }) -join ","
  rows_at_1785989274 = @($controlRows |
    Where-Object { $_.timestamp -eq 1785989274 }).Count
  distinct_hashes_at_1785989274 = @($controlRows |
    Where-Object { $_.timestamp -eq 1785989274 } |
    Select-Object -ExpandProperty transaction_hash -Unique).Count
}

.\venv\Scripts\python.exe -m pytest -q `
  tests\market\test_mm_execution_capture.py `
  tests\market\test_mm_day_countability.py
.\venv\Scripts\python.exe -m weather.market.mm_execution_capture --help
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```

The empty trade response is a positive API observation but a negative
continuity proof. The response cannot be upgraded from “no published trade
row” to “no book change.”

## Branch and commits

- Branch: `codex/workstation-close-the-maker-evidence-gap-2026-09-27a`
- Current-master base: `4aecdb71416de083c6177f272f1a7a40a9f32871`
- Carried dependency: `758824342f14aecdc42da4b545c40e048929059a`
- Dependency merge on this topic branch: `958c1b68adb8ae2480801e9c433e42f4fdc9709e`
- Initial P0 report commit: `05176bd8e73107c85c8c3f3d0b57ec7764552685`
- Initial handback-provenance commit: `f9155a665787f3c0b90ac4cc9205fed63d38783a`
- Public-history correction commit: `f5559f03697d6059e1891aa3664902eaeab49fd4`
