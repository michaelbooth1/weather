# Workstation report 2026-08-06 — close the maker evidence gap

## Verdict

**NO-GO at P0: the public API cannot reconstruct the known 2.165004-second gap
EXACTLY. The available retrospective results are INDICATIVE only; they cannot
recover every trade and every order-book change. Do not register or start
`WeatherMakerExecutionCapture`.**

The gap is `2026-08-06T00:08:24.636461-04:00` through
`2026-08-06T00:08:26.801465-04:00`, equivalently
`2026-08-06T04:08:24.636461Z` through `04:08:26.801465Z` and epoch milliseconds
`1785989304636` through `1785989306801`. An all-fleet public Data API trade
query over the enclosing epoch seconds returned HTTP 200 with `[]`. That does
**not** prove continuity: the endpoint timestamps trades only to whole seconds,
and no public historical endpoint replays the `price_change` events that encode
order placement and cancellation. Current book snapshots reveal only net state,
not the missing intermediate changes.

The premise is therefore falsified exactly where the handoff required. P1 was
not implemented, P2 was not soaked, and the settlement-continuity gate remains
unchanged. Prompt reconciliation cannot fix this API limitation: the exact
retrospective book-change retention horizon exposed by the public API is
**none (effectively zero seconds)**.

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
| CLOB book REST | `GET https://clob.polymarket.com/book?token_id=<token_id>`; batch equivalent `POST /books` | Current aggregated snapshot: `market`, `asset_id`, `timestamp`, `hash`, `bids[{price,size}]`, `asks[{price,size}]`, `min_order_size`, `tick_size`, `neg_risk`, `last_trade_price` | **CURRENT STATE ONLY.** There is no historical timestamp/window/cursor parameter and no event history. A before/after snapshot cannot reveal intermediate changes that net to the same state. |
| Public market WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market`; subscription body has `assets_ids` and `type=market` | Live `book`, `price_change`, and `last_trade_price` messages with millisecond timestamps | **EXACT ONLY WHILE CONNECTED AND RETAINED.** The public contract exposes no start time, resume cursor, or historical replay. Reconnect supplies current/live state, not missed messages. |

The official contracts are:

- [Data API trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
- [CLOB prices history](https://docs.polymarket.com/api-reference/markets/get-prices-history)
- [CLOB current order book](https://docs.polymarket.com/api-reference/market-data/get-order-book)
- [CLOB current batch order books](https://docs.polymarket.com/api-reference/market-data/get-order-books-request-body)
- [Public market WebSocket](https://docs.polymarket.com/api-reference/wss/market)

The WebSocket conclusion is an inference from the complete documented public
surface: the channel is explicitly real-time and its subscription schema has no
replay control; the REST order-book endpoints expose current snapshots only.
There is no documented public historical book-event endpoint elsewhere in the
published orderbook/pricing surface.

### Empirical known-gap result

The all-fleet Data API query deliberately used `[1785989304, 1785989307]` so
the whole microsecond-bounded gap is inside the queried seconds. It returned:

```json
[]
```

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
the tested response was not an execution or book-event tape. Both `fidelity=1`
and the undocumented `fidelity=0` probe returned the same sampled shape, so the
zero probe does not create a hidden event-level route.

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

Marking such a splice “exactly covered” would therefore be false and would
corrupt downstream maker P&L. The unchanged zero-gap continuity rule correctly
continues to reject this session.

### Retention horizon

| Evidence | Public retrospective horizon | Consequence |
| --- | --- | --- |
| Exact trades **and every book change** | **Not exposed; effectively zero seconds** | P0 fails even for an immediate reconnect. There is no exact backfill design to implement. |
| Data API market/event trade rows | Documented as approximately the most recent **three years** | Useful for bounded retrospective trade analysis, but second-precision trades alone cannot close continuity. |
| `/prices-history` samples | No retention guarantee stated in the official endpoint contract | Whatever samples remain are still only `t`/`p` aggregates and cannot become exact evidence. |
| `/book`, `/books`, market WebSocket | Current/live only; no documented retrospective replay | Exact book evidence must be captured continuously at event time. |

The trade endpoint's three-year floor is not the horizon of an exact backfill.
The load-bearing horizon is the missing historical book-event route, and that
horizon is none.

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

$events = "798963,798966,798965,798958,798967,798968,798969,798964,798947,798970,798946,798945"
$tradeUri = "https://data-api.polymarket.com/trades?eventId=$events&start=1785989304&end=1785989307&limit=10000&takerOnly=true"
(Invoke-WebRequest -UseBasicParsing -Method Get -Uri $tradeUri).Content

$token = "15332633911667325118121586693747338564353024644825829348764813223409126388999"
$historyUri = "https://clob.polymarket.com/prices-history?market=$token&startTs=1785989304.636461&endTs=1785989306.801465&fidelity=1"
(Invoke-WebRequest -UseBasicParsing -Method Get -Uri $historyUri).Content

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
- P0 report commit: `05176bd8e73107c85c8c3f3d0b57ec7764552685`
