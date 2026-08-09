# Agent report 2026-08-10 — execution reconstruction feasibility

**Verdict: `NO_GO_EXECUTIONS_NOT_IDENTIFIABLE_FROM_BOOK_DELTAS`. A `price_change` or a
change between sampled books cannot distinguish a cancellation from an execution, and the retained
tape has neither continuous session coverage nor a label that supplies that distinction. Aggressor
side, adverse markout `A`, informed-flow fraction `f`, and a measured zero-edge break-even share are
therefore not identified. P0 stops before estimation, as required. The venue already exposes the
needed evidence: continuously retain the public market stream's explicit `last_trade_price` event,
then reconcile it against the public Data API `/trades` history.**

This is a feasibility NO-GO, not a finding that `f` is high or low. Market-centred spread harvesting
remains an open route, but the present tape cannot decide whether it is a business or a donation.

## 1. Scope and binding stop rule

The refreshed handoff replaced the original instruction to measure `f` from 265
`market_ws_events.csv` files. The production host had opened the files and found only 71 explicit
executions in a 60-file, 1,107,984-row sample. This mission therefore asked the prior question:
whether missing executions can be reconstructed from `price_change` and `book` changes at all.

The answer is no. Because P0 step 1 fails, the handoff requires stopping before:

- assigning an aggressor side;
- estimating markouts at any horizon;
- classifying flow as informed or uninformed;
- substituting a fitted `f` or `A` into the `-09-46a` grid.

Nothing is currently reserved under
[`reserved-confirmation-window.md`](../operations/reserved-confirmation-window.md), so no date was
consumed or exposed in performing this read-only historical audit.

## 2. P0 — why the execution signal is not recoverable

### 2.1 `price_change` is state, not an execution record

The retained normalized row carries `asset_id`, price, **post-change level size**, resting-book
`side`, receive time, and `raw_sha1`. It does not carry an execution type, execution size, trade ID,
transaction hash, or normalized exchange timestamp. A decrease from 100 shares to 60 shares is
observationally compatible with at least these two histories:

1. 40 resting shares were cancelled;
2. 40 resting shares were executed.

Both histories produce the same retained level state. No classifier over that record can separate
them, because the discriminating variable was never captured. A zero level is equally ambiguous: it
means that the level disappeared, not why it disappeared.

The official [Polymarket market-stream contract](https://docs.polymarket.com/market-data/realtime-data#market-stream)
presents `price_change` as a price-level event and `last_trade_price` as the distinct trade event.
The latter carries `asset_id`, market, price, executed size, side, exchange timestamp, fee rate, and
transaction hash. Reinterpreting the former as the latter would erase exactly the distinction the
protocol supplies.

This is stronger than low precision. Precision cannot be estimated: the tape contains sparse
positive labels (`last_trade_price`) but no cancellation labels, so there is no false-positive
denominator. Matching a depletion to some of the positive controls could measure limited recall; it
could never prove that unmatched depletions were trades rather than cancellations.

### 2.2 Successive `book` snapshots do not rescue identity

The raw `market_ws.jsonl` wrapper retains full book payloads and the vendor timestamp, but the
collector opens bounded sessions repeatedly. The configured research loop samples each market for
20 seconds on a 900-second interval, at most **2.222% nominal time coverage per market** before
message-limit and connection losses. Every connection begins with book state. The retained envelope
stores the subscription payload, receive time, raw hash, and payload, but no durable session ID,
subscription acknowledgement, sequence number, or gap ledger.

Consequently, a difference between two initial books spans unobserved placements, cancellations,
and executions. Even a net depletion has no causal identity. The CSV projection is weaker still:
its `book` rows contain no price levels and no normalized exchange timestamp, only a pointer to the
raw payload.

The relevant source path is direct:

- `record_market_websocket` creates a connection, sends one subscription, receives for the bounded
  window, closes, and returns;
- `ws_summary_rows` maps `price_change.size` straight into the generic `size` column and does not map
  the vendor `timestamp` or `transaction_hash`;
- the raw wrapper preserves the payload, but not connection/session continuity or the reason a full
  book was emitted.

Cross-connection book differencing therefore cannot turn missing time into execution evidence.

### 2.3 Aggressor side and markout time fail with identity

`price_change.side` identifies the side of the changed resting level. Calling the opposite side the
aggressor first assumes the change was a fill—the proposition P0 cannot establish. The raw vendor
timestamp could be recovered for an individual retained message, but a sparse inferred event cannot
be followed through seconds-to-minutes horizons when the surrounding market stream is absent.

There are thus **zero admissible inferred executions**. `A` and `f` are undefined on this evidence,
not estimates with wide intervals.

## 3. Support, clustering, and power

The production-host fact supplied by the handoff remains the authoritative content measurement:

| Production sample | Support |
| --- | ---: |
| Files | 60 |
| Normalized rows | 1,107,984 |
| `book` | 904,325 |
| `price_change` | 203,584 |
| **`last_trade_price`** | **71** |
| `tick_size_change` | 3 |

A full read-only inventory of the workstation's historical copy corroborated the schema and
sparsity, but is not presented as live production evidence:

| Workstation historical copy | Support |
| --- | ---: |
| Files / distinct market-days | 265 / 265 |
| Date clusters / market clusters | D=23 / M=12 |
| Normalized rows | 4,493,597 |
| `book` | 3,734,993 |
| `price_change` | 758,189 |
| **`last_trade_price`** | **411 (0.0091% of rows)** |
| Explicit-trade support | D=20 / M=12 / 182 market-days |
| `price_change` rows with `timestamp_utc` or `trade_time_utc` | **0 / 758,189** |
| `book` rows retaining levels in the CSV projection | **0 / 3,734,993** |

Rows were deduplicated to their 265 event directories before any market-day claim. The date range is
2026-06-14 through 2026-07-27, entirely before the `2026-07-31` provenance boundary. Nothing was
pooled across that boundary.

Crossed date × market intervals and power are **not applicable**. They quantify sampling uncertainty
after an estimand is identified; they cannot recover a missing execution/cancellation label. There
is no honest effect size or variance estimate on which to base power. “Not powered” would understate
the failure: this design has no valid observation unit for `A` or `f`.

## 4. Business implication — no substitution into `-09-46a`

The zero-edge economics used here are from the report on
`origin/codex/workstation-does-a-quotable-edge-exist-2026-09-46a`, commit `b960d213`.
Its no-reward sensitivity remains:

| Assumed informed fraction `f` | Zero-edge scenarios clearing break-even |
| ---: | ---: |
| 0.10 | 79.43% |
| 0.25 | 56.57% |
| 0.50 | 42.29% |
| 0.75 | 26.86% |
| 1.00 | 24.57% |

No row is selected or interpolated here. The realistic reward input remains **$0**: commit
`8e7b5732` established that the 20-contract reward minimum requires $19.60 against the current $10
`max_band_notional` cap. The grid's unconditional no-reward share of 45.94% is a sensitivity summary,
not a measured business verdict. With both `A` and `f` unidentified, quoting any unique clearing
share would be false precision.

## 5. P1 — the feed that would settle the question

No endpoint was called. The following contracts were documented from official venue documentation
and checked against the retained raw payload shape.

### 5.1 Primary: continuous public market WebSocket execution capture

Endpoint:

```text
wss://ws-subscriptions-clob.polymarket.com/ws/market
```

Current documented subscription:

```json
{
  "assets_ids": ["<token_id_1>", "<token_id_2>"],
  "type": "market"
}
```

Send `PING` every 10 seconds. Retain only the explicit execution message for the execution tape:

```json
{
  "event_type": "last_trade_price",
  "market": "<condition_id>",
  "asset_id": "<token_id>",
  "price": "0.08",
  "size": "219.217767",
  "fee_rate_bps": "0",
  "side": "SELL",
  "timestamp": "<exchange_epoch_ms>",
  "transaction_hash": "<transaction_hash>"
}
```

Execution identity and exchange time therefore survive at the venue boundary. The present raw
wrapper already proves this on its sparse positive rows; the generic CSV normalizer discards
`timestamp` and `transaction_hash` because it looks only for `timestamp_utc` and has no transaction
hash column.

A production capture change should be continuous across the quote/markout window and retain:

- condition ID, asset/token ID, price, executed size, taker side, fee rate;
- vendor exchange timestamp with declared units and local receive timestamp;
- transaction hash/native execution identity and raw payload hash;
- session ID, subscription acknowledgement, heartbeat, reconnect, sequence information if exposed,
  and an explicit gap ledger;
- one canonical fingerprint so raw and normalized representations cannot double count an execution.

The current collector sends the legacy frame `{"operation":"subscribe","assets_ids":[...]}`. It
was accepted by the historical service, but any new producer should use and test the current
documented `{"type":"market"}` form rather than silently inheriting that compatibility assumption.

### 5.2 Reconciliation/backfill: public Data API trade history

Exact public call shape:

```text
GET https://data-api.polymarket.com/trades?market=<condition_id>&start=<epoch_s>&end=<epoch_s>&limit=<n>&offset=<n>&takerOnly=true
```

The [official `/trades` reference](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
documents condition-ID filtering, bounded `start`/`end` windows, pagination, and response fields
including `side`, `asset`, `conditionId`, `size`, `price`, `timestamp`, and `transactionHash`.
Execution identity and exchange time therefore survive this route too.

This endpoint is suitable for bounded backfill and reconciliation, not for replacing the live
millisecond stream in short-horizon markouts. The documented Data API timestamp is integer-valued and
historical project testing found second-level trade timing; it cannot prove sub-second ordering or
repair an exact book-coverage gap. Page inside bounded time windows because offset is capped at
10,000.

The official public client also exposes `getMarketTradesEvents(conditionID)` with side, size, price,
transaction hash, and timestamp. It is a recent-events convenience, not a substitute for a retained,
gap-accounted continuous stream.

### 5.3 Not sufficient: authenticated user stream

The authenticated user WebSocket emits rich `trade` lifecycle records—trade ID, taker order ID,
match time, transaction hash, maker orders, and side—but only for the authenticated account. It can
prove our own future fills; it cannot estimate the market-wide informed-flow denominator and is not
available before any order is placed. It should complement, not replace, the public execution tape.

## 6. Exact reproduction commands

All repository paths below exist on the production host. The inventory is read-only and writes
nothing under `data/`:

```powershell
@'
import csv
import collections
import re
from pathlib import Path

files = list(Path("data/snapshots").rglob("market_ws_events.csv"))
counts = collections.Counter()
markets, slugs, dates = set(), set(), set()
coverage = collections.Counter()
months = {name: i for i, name in enumerate(
    ["", "january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"]) if name}
pattern = re.compile(r"-on-([a-z]+)-(\d{1,2})-(\d{4})$")

for path in files:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            kind = row.get("event_type") or "<blank>"
            counts[kind] += 1
            if row.get("market_id"):
                markets.add(row["market_id"])
            slug = row.get("event_slug")
            if slug:
                slugs.add(slug)
                match = pattern.search(slug)
                if match:
                    dates.add((int(match.group(3)), months[match.group(1)], int(match.group(2))))
            for key in ("timestamp_utc", "trade_time_utc"):
                if row.get(key):
                    coverage[(kind, key)] += 1

print({
    "files": len(files),
    "rows": sum(counts.values()),
    "event_types": dict(counts),
    "market_days": len(slugs),
    "date_clusters": len(dates),
    "market_clusters": len(markets),
    "price_change_timestamp_utc": coverage[("price_change", "timestamp_utc")],
    "price_change_trade_time_utc": coverage[("price_change", "trade_time_utc")],
})
'@ | .\venv\Scripts\python.exe -
```

Inspect the retained schema, collector boundary, and one genuine raw execution without calling the
venue:

```powershell
Get-Content data\snapshots\highest-temperature-in-atlanta-on-june-30-2026\market_ws_events.csv -TotalCount 2
rg -n --max-count 1 'event_type.{0,30}last_trade_price' data\snapshots\highest-temperature-in-atlanta-on-june-30-2026\market_ws.jsonl
rg -n 'def ws_summary_rows|sent =|"subscription": sent|seconds=ws_seconds' src\weather\market\market_microstructure_capture.py
rg -n 'IntervalSeconds|WebsocketSeconds|WebsocketMessageLimit' scripts\ops\register_clob_enrichment.ps1
git show --format=fuller --stat 8e7b5732
```

Re-derive the branch roll verdict; do not infer it from file suffixes:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch codex/workstation-can-executions-be-reconstructed-2026-09-47a
```

## 7. Roll verdict and boundaries

Branch: `codex/workstation-can-executions-be-reconstructed-2026-09-47a`

Base: `origin/master` at `5cf08abac4ea30f153e34e5d24bee626efecf64f`

Result commit: `b90f4b263dd3403294aef2a63532fbc7f9bf7f4d`.

Repository-owned roll verdict: **`ROLL-FREE` (exit 0)**. The script reported one changed file and
zero importable files. Per-file verdict:

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-10-workstation-execution-reconstruction.md` | no | no | no | no | roll-free |

The script also reported that the dormant CLOB-enrichment closure is a strict subset of the live
closures, so its dormancy cannot change this verdict. No source, schema, config, or scheduled script
is changed.

What was **not** done: no exchange or provider endpoint call; no model fit; no candidate or
promotion; no order; no live-trading enablement; no registration; no production `data/` write; no
chain run; no settlement; no loop start or restart; no gate or fixture change; no merge.
