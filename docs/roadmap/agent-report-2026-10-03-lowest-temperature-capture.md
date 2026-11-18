# Agent report 2026-10-03 — lowest-temperature capture family

Workstation (Claude Code), implementation with fixture measurement only. Origin: the
[lowest-temperature desk study](agent-report-2026-10-02-lowest-temperature-desk-study.md) (branch
`claude/lowest-temp-desk-study-20261002`), which gave GO for passive capture after 10-14 in 11 cities (Chicago excluded) and
found that 88a `--extra-conditions` cannot hold the family. Branch `codex/lowest-temp-capture-20261003`.

## Verdict

**Built: a config-driven capture family, recorded by a separate 88a process in its own root.** This is smaller and safer than
extending the core universe. `maker_evidence_capture --family lowest_temperature` captures every active condition of the T+0..T+2
lowest-temperature events for 11 cities, with minute books on both tokens and reward terms, into
`data/maker_evidence_families/lowest_temperature`. **Fixture estimate: 35 requests/min steady (0.59 req/s), 51/min peak; 0.13
GiB/day gzipped (0.40 worst case); no websocket.** Roll-sensitive (it changes the 88a module): **do not merge before 2026-10-14**,
and register the task only after integration.

## Why a separate root (the route choice)

- A lowest slug inside core 88a discovery makes the pinned exam exporter refuse with `unregistered_event`
  (`maker_plugin/inputs.py:event_identity` in tree `6ac18be7e`). The 10-15..10-30 retention-hold data would carry it, and so
  would any later export.
- The family's reads would share the core recorder's 55-second cycle and its failure accounting.
- A separate process keeps the core root, the core universe events and every reader of them unchanged. The cost is one more
  long-running worker (no websocket) and one more Scheduler task.

The "minimal shared recorder" (Stage-2 `capture_core`) would be a larger lift and a larger roll; the family mode reuses the 88a
store, reader, discovery and archive unchanged.

## What was built

| File | Change | Behaviour for the core 88a recorder |
| --- | --- | --- |
| `config/capture_families.json` | New. `lowest_temperature`: 11 city slug prefixes, Chicago excluded with its reason, day-aheads 0-2, bounds | none |
| `src/weather/market/maker_evidence_family.py` | New. Validated config load, event slugs in each city's time zone, full universe, reward-read cadence | none |
| `src/weather/market/maker_evidence_capture.py` | `discover_events` extracted verbatim from `build_universe`; `--family` mode; the family root may not overlap the core root | identical |
| `src/weather/market/maker_evidence_public.py` | Optional `partition` on `PublicReader.read` / `reward_record` | identical (default `None`) |
| `src/weather/operations/storage_classes.py` | `passive_capture_family_evidence` (canonical, protected) and `passive_capture_family_status` | additive |
| `src/weather/operations/config_inventory.py`, `docs/operations/config-inventory.md` | Registers the new config file | additive |
| `scripts/ops/register_maker_evidence_family_capture.ps1`, `config/scheduled_tasks.json`, `OPERATING_REFERENCE.md` | Registrar for `WeatherMakerEvidenceLowestTemperature` (S4U, IgnoreNew, one-minute retry); inventory row; generated table | not registered |
| `docs/operations/passive-maker-evidence-capture.md`, `OPERATIONS_DESIGN.md` | New "Capture families" section | — |
| `tests/market/test_maker_evidence_family.py` | 20 tests: config refusals, local-date slugs, full universe, partitions, change-only universe, reward cadence, no websocket, floor stop, root isolation, storage class | — |

No `schema_registry*` file changed. The schema stays `maker_evidence_v2`; family rows add fields only inside JSON bodies.

**Per minute, the family:**
- reads 33 events in 3 batched Gamma reads;
- keeps every active condition (about 363; bound 600);
- POSTs both tokens' books (8 batched reads);
- stores Gamma reward terms change-only through the discovery projection;
- reads the CLOB `/rewards/markets/<cid>` record when a condition's Gamma terms change, when it is first seen, or after 15
  minutes, at most 40 per cycle (changed first, then oldest). F2's rewarded condition-minute can therefore be read from
  minute-resolution Gamma terms, each confirmed by a CLOB record at most 15 minutes old.

**What the family never does:**
- Opens a websocket. At 100 tokens per connection, 726 tokens would add eight sockets against an UNVERIFIED per-IP cap
  (swarm-expansion 2026-10-01). Trades for this family therefore need the planned shared subscriber.
- Ranks bands or runs a model.
- Writes to the core root.

**Disk floors.** The family stops at its own `stop_below_free_gib` = 70 GiB (the swarm's abort guard). That is above the core
Critical brake (40 GiB) and the bounded-suite floor (50 GiB), so the family yields disk before the core recorder does. Below the
floor it opens no journal; each one-minute retry only rewrites `status.json` (`STOPPED_FAMILY_DISK_FLOOR`).

## Measured on fixtures (request rate and disk)

**Method.** The real `family_universe`, `get_books`, `EvidenceStore` and verified `compress_closed_segments` ran on a simulated
clock for 180 minutes, with three hourly segments sealed and gzipped. Inputs were public-shape fixtures: full Gamma market
objects (about 3.5 KB each), CLOB books, and reward records. There were no venue calls. The script is in
[Reproduction](#reproduction).

| Quantity | Baseline (15 levels/side, 30% of books change per minute) | Worst case (25 levels/side, every book changes every minute) |
| --- | ---: | ---: |
| Conditions / tokens | 363 / 726 | 363 / 726 |
| Requests per minute, steady (after warm-up) | **35.2** (3 Gamma + 8 books + 24.2 rewards) | 35.2 |
| Requests per minute, peak (first 10 minutes: 40 reward reads) | 51 | 51 |
| Inbound response bytes | 2.5 GiB/day | 3.2 GiB/day |
| Uncompressed journal writes | 1.9 GiB/day | 2.8 GiB/day |
| **Retained gzip** | **0.125 GiB/day** (0.35 MiB/condition-day) | **0.40 GiB/day** (1.13 MiB/condition-day) |
| Allocated at 4 KiB clusters | 0.16 GiB/day | 0.49 GiB/day |
| Gzipped files | ~17.8k/day (741 per hour segment) | ~35.6k/day (100 MB rotation splits the hour) |

- **Planning number: about 0.3 GiB/day** (88a's MEASURED ~0.8 MB/condition-day × 363), bracketed by the fixture's 0.13-0.40.
  This is about +3-5% of the host's current net burn. At 117 GiB free it would take months alone to reach the 70 GiB family
  floor. The fixture's churn is a guess; the receipt from the first real day replaces these numbers.
- **Request budget:** about +0.6 req/s against 88a's ~1.9 req/s today. Gamma reads are about 1.4 MB/min of the inbound bytes;
  the inbound figure is fixture-shaped (the real Gamma payload size is UNVERIFIED).
- **Write pattern:** about 770 fsynced appends per minute (one per book token per minute plus small records), about 13/s at IDLE
  priority.

## Roll verdict

`scripts\ops\roll_verdict.ps1 -Branch origin/codex/lowest-temp-capture-20261003` on the workstation: **UNDECIDABLE** (exit 1,
no live closure evidence; the mirror has no `data\snapshots` status files). Treat the branch as **roll-sensitive**. The
production agent must re-run the verdict.

Per file:
- `maker_evidence_capture.py`, `maker_evidence_public.py` and the new `maker_evidence_family.py` belong to the 88a worker. That
  worker is not one of the four supervisor closures, but changing it requires an explicit re-adoption of
  `WeatherMakerEvidenceCapture`.
- `storage_classes.py` and `config_inventory.py`: the closure membership is unknown here, so the production verdict decides.
- `config/`, `docs/`, `.ps1` and tests are roll-free.

## Integration steps for production (after 10-14)

1. Re-run the roll verdict; merge in the quiet window.
2. Re-adopt `WeatherMakerEvidenceCapture`, whose module changed with identical behaviour.
3. Run `register_maker_evidence_family_capture.ps1 -WhatIf`, then register it. Verify
   `data\maker_evidence_families\lowest_temperature\status.json` (`state` CAPTURING, `universe_size` about 363,
   `websocket` none).
4. After the first full UTC day, run `maker_evidence_inspect --root data\maker_evidence_families\lowest_temperature` through the
   heavy policy. Record the real requests/min and GB/day as the stage receipt.
5. F2 (pre-registered) runs on the first 14 captured local days.

Not done: `status.ps1` and the cockpit do not read the family status yet. Chicago stays excluded unless the owner overrides it
(one config line).

## What was NOT done

No venue, provider or production call. No 88a or exam data read. No registration, scheduled task, production write, merge,
model fit or candidate. Reserved confirmation window: not read (no dated evidence used).

## Reproduction

The script below (Python, `PYTHONPATH=<worktree>\src`) writes the JSON shown above.
`python measure_family.py <new-root> 180` gives the baseline. Adding `LEVELS=25 P_CHANGE=1.0` gives the worst case.

```python
"""Fixture measurement of the lowest-temperature capture family: requests/min and GB/day.

Real family_universe/get_books/EvidenceStore/compress_closed_segments on a simulated clock;
public-shape fixtures only (no venue call). Usage: python measure_family.py <root> <minutes>
"""
import json, random, sys, time, os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.market import maker_evidence_capture as capture
from weather.market.maker_evidence_family import load_family, family_universe
from weather.market.maker_evidence_public import discovery_projection
from weather.market.maker_evidence_store import EvidenceStore, digest, encoded
from weather.market.maker_evidence_archive import compress_closed_segments

root, minutes = Path(sys.argv[1]), int(sys.argv[2])
LEVELS = int(os.environ.get("LEVELS", "15"))       # price levels per side
P_CHANGE = float(os.environ.get("P_CHANGE", "0.3"))  # chance a book changes in a minute
REWARDED = int(os.environ.get("REWARDED", "4"))      # rewarded bands per event (swarm: 2-5 of 11)
rng = random.Random(20261003)
clock = [datetime(2026, 10, 15, 4, 0, 30, tzinfo=timezone.utc)]
store = EvidenceStore(root, clock=lambda: clock[0])
family = load_family("lowest_temperature")
books, tokens_of = {}, {}


def market(slug, band):
    cid = "0x" + digest(encoded([slug, band]))
    toks = [str(int(cid[2:20], 16)), str(int(cid[20:38], 16))]
    for t in toks:
        tokens_of[t] = cid
    rate = 10.0 if band in range(3, 3 + REWARDED) else 0.
    # Full Gamma market shape (~3.5 KB): projection keeps the selection fields only.
    return {"id": str(int(cid[40:48], 16)), "question": f"Will the lowest temperature in X be {band}?", "conditionId": cid,
            "slug": f"{slug}-{band}", "description": "This market will resolve ... " * 40, "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.12", "0.88"]', "volume": "1234.5", "active": True, "closed": False,
            "enableOrderBook": True, "clobTokenIds": json.dumps(toks), "rewardsMinSize": 20, "rewardsMaxSpread": 4.5,
            "clobRewards": [{"id": "1", "conditionId": cid, "assetAddress": "0x" + "0" * 40, "rewardsAmount": 0,
                             "rewardsDailyRate": rate, "startDate": "2026-10-13", "endDate": "2500-12-31"}] if rate else [],
            "volume24hr": 321.0, "liquidity": "4321.1", "bestBid": 0.11, "bestAsk": 0.13, "lastTradePrice": 0.12,
            "spread": 0.02, "oneDayPriceChange": 0.01, "umaResolutionStatuses": "[]", "image": "https://x/y.png"}


def book(token):
    if token not in books or rng.random() < P_CHANGE:
        mid = rng.uniform(0.02, 0.98)
        bids = [{"price": f"{max(0.001, mid - 0.01 * (i + 1)):.3f}", "size": f"{rng.uniform(5, 900):.2f}"} for i in range(LEVELS)]
        asks = [{"price": f"{min(0.999, mid + 0.01 * (i + 1)):.3f}", "size": f"{rng.uniform(5, 900):.2f}"} for i in range(LEVELS)]
        books[token] = {"bids": bids[::-1], "asks": asks[::-1], "hash": digest(encoded([token, rng.random()]))[:40]}
    b = books[token]
    return {"market": tokens_of[token], "asset_id": token, "timestamp": str(int(clock[0].timestamp() * 1000)),
            "hash": b["hash"], "bids": b["bids"], "asks": b["asks"], "min_order_size": "5", "tick_size": "0.001",
            "neg_risk": False, "last_trade_price": "0.120"}


class Reader:
    def __init__(self):
        self.store, self.deadline = store, float("inf")
        self.calls, self.response_bytes = Counter(), Counter()

    def read(self, url, *, params=None, body=None, kind="discovery", change_key=None, partition=None):
        stored = None
        if url.endswith("/events"):
            slugs = [v for k, v in params if k == "slug"]
            reply = [{"id": s, "slug": s, "title": s, "description": "x" * 2000,
                      "markets": [market(s, band) for band in range(11)]} for s in slugs]
            name = "gamma_events"
        elif url.endswith("/books"):
            reply = [book(row["token_id"]) for row in body]
            name = "clob_books"
        else:
            cid = url.rsplit("/", 1)[1]
            reply = {"data": [{"condition_id": cid, "question": "q", "market_slug": "s", "event_slug": "e",
                               "rewards_max_spread": 4.5, "rewards_min_size": 20, "tokens": [],
                               "rewards_config": []}], "next_cursor": "LTE=", "limit": 100, "count": 1}
            name = "clob_rewards"
        raw = json.dumps(reply).encode()
        if kind == "discovery":
            stored = encoded(discovery_projection(reply))
            change_key = "discovery:" + digest(encoded(params))
        self.calls[name] += 1
        self.response_bytes[name] += len(raw)
        self.store.record(kind, raw, metadata={"url": url, "http_status": 200}, change_key=change_key,
                          stored_body=stored, partition=partition)
        return json.loads(raw)


reader, state = Reader(), {}
per_minute = []
t0 = time.perf_counter()
for minute in range(minutes):
    before = Counter(reader.calls)
    universe, _, _ = family_universe(reader, family, now=clock[0], reward_state=state, discover=capture.discover_events)
    capture.get_books(reader, [t for row in universe for t in row["tokens"]], kind="books")
    per_minute.append(sum((reader.calls - before).values()))
    clock[0] += timedelta(minutes=1)
wall = time.perf_counter() - t0
store.seal()
compress_closed_segments(store)
gz = sum(p.stat().st_size for p in root.rglob("*.gz"))
files = sum(1 for _ in root.rglob("*.gz"))
alloc = sum(-(-p.stat().st_size // 4096) * 4096 for p in root.rglob("*.gz"))
hours = minutes / 60
steady = per_minute[30:] if minutes > 45 else per_minute
print(json.dumps({
    "minutes": minutes, "conditions": len(universe), "tokens": 2 * len(universe), "levels_per_side": LEVELS,
    "p_book_change_per_minute": P_CHANGE, "rewarded_bands_per_event": REWARDED,
    "requests_by_endpoint": dict(reader.calls),
    "requests_per_minute_first5": per_minute[:5], "requests_per_minute_steady_mean": sum(steady) / len(steady),
    "requests_per_minute_steady_max": max(steady),
    "response_mib_per_minute": sum(reader.response_bytes.values()) / minutes / 2**20,
    "response_gib_per_day": sum(reader.response_bytes.values()) / minutes * 1440 / 2**30,
    "journal_bytes_written_per_day_gib": store.bytes_written / minutes * 1440 / 2**30,
    "gzip_bytes": gz, "gzip_files": files,
    "gzip_gib_per_day": gz / hours * 24 / 2**30, "allocated_4k_gib_per_day": alloc / hours * 24 / 2**30,
    "gzip_mib_per_condition_day": gz / hours * 24 / len(universe) / 2**20,
    "files_per_day": files / hours * 24, "sim_wall_seconds": round(wall, 1),
}, indent=1))
```
