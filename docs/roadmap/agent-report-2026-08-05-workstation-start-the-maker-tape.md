# Workstation report 2026-08-05 — start the maker tape

## Decision

**Recommend candidate 3: a narrowed form of `-09-11a`'s dedicated
`mm_execution_capture`, and no other websocket producer.** It must keep the
single fleet connection and mandatory per-event coverage receipts, retain only
individual `last_trade_price` execution objects, and write through a dedicated
execution-tape lock. Do not schedule the stock CLOB enrichment loop and do not
run both producers.

The held `-09-11a` implementation is **NO-GO as-is**. A 30-second live public
feed probe projects its all-payload writer at 27.33 GB/day and it acquires the
same per-event raw-tape lock as the latency-critical book writer. The narrowed
design is a conditional **GO for a fourth loop** after the three fail-closed
contracts in `scripts/ops/register_maker_tape.ps1` exist in the refreshed
producer: execution-only retention, a separate lock scope, and a pause during
the nightly training window. Nothing was registered or started on a production
host by this mission.

Basis: refreshed `origin/master` at
`8cb6101e5e7ecd4adb7e664ad94341690a0eedd3`; held `-09-11a` at
`14dd1e849234896f37ab6e38670f2639779f1367`.

## P1 — producer and writer safety

### Why not the stock enrichment loop

`run_enrichment_loop` delegates to `capture_fleet_enrichment`, which visits the
12 event stores sequentially. Each `capture_event_enrichment` opens a bounded,
market-local websocket sample through `record_market_websocket`; the supplied
registration defaults to 20 seconds per market on a 15-minute supervisor
interval. This is suitable for periodic research enrichment, but it cannot
prove continuous coverage of a paper decision or quote lifetime. It also has
no execution-session receipt. Its absence from the scheduler is therefore no
longer merely an overlooked cheap way to satisfy the maker gate: its sampling
contract is the wrong evidence contract.

The enrichment path can also take `raw_tape_guard("derived_feature_read")`.
Scheduling it creates work in the same event folders as the protected CLOB
loop without supplying the continuous receipt the gate needs. It stays off.

### Shared-writer hazard

Every `MarketMicrostructureStore` uses
`root / "clob_raw_tape"` as `raw_tape_lock_anchor_path`.
`raw_tape_guard` tries the lock three times with 25 ms sleeps and fails with
`RawTapeWriterBusy`; the raw book path holds it while appending token and book
tape. The held execution producer takes this same guard for every routed
websocket payload and for every session receipt. `append_csv` and
`append_jsonl` separately open and append, so the lock prevents interleaved
logical records only when every participant takes it. A second writer can
therefore delay a book append, make one of the writers fail after the bounded
retries, and amplify filesystem contention even when byte-level append remains
intact. At the observed 186.5 messages/second, this is not acceptable for the
Toronto streak.

The repair is not a longer retry. The refreshed maker producer must use a
different anchor, for example `root / "mm_execution_tape"`, and must keep its
raw and canonical execution append plus receipt-binding update inside that
dedicated guard. It must not take `clob_raw_tape` for execution writes or
reads. Because the files are maker-specific, the raw book loop then cannot be
stalled by this writer.

### Exact narrowing contract

Refresh `weather.market.mm_execution_capture` as follows:

1. `_filter_payload_for_assets` / `record_fleet_session` must extract only
   payload members whose `event_type` is `last_trade_price`. It must not retain
   a whole mixed websocket message just because one member is an execution.
2. The producer needs a dedicated execution row writer rather than the shared
   `ws_summary_rows` contract. That writer must copy source `timestamp` into
   normalized exchange time and retain `transaction_hash`, `session_id`, and a
   local monotonically increasing connection-message sequence in the canonical
   row. The raw record already retained timestamp and transaction hash in the
   live probe.
3. `_append_session_receipts` must bind the subscribed-asset set, connection
   sequence interval, execution count including exact zero, and raw/canonical
   tape prefix sizes and hashes. `build_execution_tape_inventory` may accept no
   execution file only when a complete bound receipt proves exactly zero; a
   positive receipt count must require matching raw and canonical tapes.

The public message did not expose an exchange book-alignment sequence. The
exact missing field is therefore `book_alignment_sequence`; it cannot be
fabricated. `record_fleet_session` can add a local connection sequence for
ordering and audit binding, but must label it as local. The strict-through rule
does not require an exchange book sequence: it compares a time-bounded paper
quote with an execution's exchange timestamp, aggressor side, price, and
recorded size. Full-depth book tape remains independently required for reward-Q
and book-freshness evidence.

## P2 — live bytes and end-to-end proof

### Live capture

One authorized, read-only public websocket connection ran for 30.125 seconds
on the workstation. It used the held producer code, subscribed all 264 active
assets (12 markets × 22 tokens), placed no order, used no credential, and wrote
only below the worktree's ignored `scratch/runs/start-maker-tape-09-17a` root.

| Measure | Result |
| --- | ---: |
| Complete fleet session | 1 |
| Websocket messages | 5,619 |
| Normalized event rows | 11,478 |
| Books / price changes / executions | 272 / 11,202 / 4 |
| Message rate | 186.523/s |
| Event-row rate | 381.012/s |
| Raw + canonical + receipt bytes | 9,529,372 |

The capture evidence file is
`scratch/runs/start-maker-tape-09-17a/live-capture-evidence.json`, SHA-256
`C0D809817F65AE1F9046B526F70EFC6B76CFB174944C2BA866218BEB96A4699E`.

All four live executions had token identity, price, size, and aggressor side.
The raw record also had a millisecond source `timestamp` and
`transaction_hash`. The shared canonical CSV left `timestamp_utc` and
`trade_time_utc` blank and has no transaction-hash column; this is why the
narrow writer must normalize those fields itself rather than rely on
`ws_summary_rows`.

### Strict-through acceptance replay

The proof is deliberately described precisely: it is a **hybrid replay, not a
real maker day**. Exact live Houston `market_ws.jsonl`,
`market_ws_events.csv`, and session-receipt bytes were replayed. The paper
quote/lifetime, full-depth book, markouts, settlement, reservation PASS object,
and fill-evidence PASS object were synthetic so that the execution format could
be exercised through the held `mm_paper_scoring` and `mm_day_countability`
implementation.

The selected real print was a SELL of 0.17 at 0.001, exchange time
`2026-08-05T18:43:32.402Z`, raw SHA-1
`b33a0de53d0f913041a720a7ab6f080734217096`, against a synthetic YES bid of
10 at 0.01. It is strictly below the bid, and the simulated fill was capped at
the recorded 0.17 size. Results:

- one fill with
  `conservative_fill_rule=strict_trade_through_price_and_recorded_size`;
- raw and canonical execution representations linked by `raw_sha1`;
- `acceptance_pnl_status=COUNTABLE_SETTLEMENT`;
- reward-Q PASS with own Q 10, competitor Q 6.9, denominator Q 16.9; and
- day status `COUNTABLE`, zero blockers, all checklist fields true.

The replay evidence is
`scratch/runs/start-maker-tape-09-17a/live-tape-countability-evidence.json`,
SHA-256
`52EE284E17688DB45AC50875F263C04A637040C75DA250C8903F5FBF1EC6D7EF`.
A real countable date must still prove all-market maker decisions, actual quote
lifetimes when quoting, continuous bound receipts, full-depth books, required
markouts, reservation state, and settlement. This replay proves the live
execution bytes are sufficient for the strict-through portion; it does not
claim those synthetic inputs occurred.

A countable day does **not** require the maker to quote. A valid fail-closed or
no-edge decision can be a countable zero-action cell. It does require the maker
to run and retain its decision row. The session receipt is load-bearing even
when no quote is emitted: it proves the decision time was continuously covered
and distinguishes zero executions from an absent producer. Tape alone is not a
countable day.

## P3 — workstation price and loop verdict

The live all-payload probe started at 32,546,816 bytes RSS and peaked/ended at
41,459,712 bytes (31.0 to 39.5 MiB). It consumed 9.906 CPU seconds in 30.125
wall seconds, or 32.9% of one logical core. Narrow retention still parses and
routes the same 186.5 incoming messages/second, so 40 MiB RSS and 33% of one
core are the conservative measured steady-state bounds; reduced serialization
should improve CPU, but no improvement is credited before a soak.

The held all-payload writer produced 9.53 MB in 30.125 seconds, projecting to
27.33 GB/day. Added to the handed-off 27.6 GB/day host growth, that would nearly
double burn to 54.9 GB/day and consume 133 GB free in roughly 2.4 days. It is
unconditionally **NO-GO**.

Filtering complete messages is also insufficient: 16 mixed raw records that
contained the text `last_trade_price` still occupied 631,178 bytes and project
near 1.8 GB/day. Extracting the four execution objects themselves used 2,423
raw bytes and 1,267 canonical bytes. Including one canonical header and all 12
session receipts, the observed narrow form was 10,691 bytes in 30.125 seconds,
projecting to 30.66 MB/day (29.24 MiB/day) at 0.133 executions/second. Against
the existing approximately 0.9 GB MM market-day, this is a 3.4% increment to
about 0.931 GB/day; against whole-host growth it is about 0.11%. Because the
sample is short, initial operations should budget 100 MiB/day and fail the soak
if that envelope or a 64 MiB RSS envelope is exceeded.

The task must run at Task Scheduler priority 6 (`BelowNormal`). The existing
priority guard recognizes only snapshot, CLOB, and observation-trigger modules
and will continue to hold those three at `AboveNormal`. The new producer must:

- yield CPU and filesystem service to those three capture loops;
- use no shared raw-book lock and perform no bulk work during the protected
  18:00–00:30 window (its small append-only execution evidence is the required
  exception);
- pause/disconnect during the `WeatherTrainingWindow` and resume only after its
  04:15 restore, recording the planned coverage break; and
- never run concurrently with `WeatherClobEnrichmentLoop`.

**GO for the narrowed fourth loop, conditional on those contracts and a focused
soak; NO-GO for the held producer or stock enrichment.** If the narrowed loop
cannot meet the 100 MiB/day, 64 MiB RSS, BelowNormal, and no-book-lock bounds,
do not buy it by risking Toronto. Leave enrichment off and trade away any
remaining taker capture/archive workload first; the taker track is already
deprioritized and its tape has already been deleted. If that is insufficient,
the maker tape waits for a second host.

The delivered registration script is fail-closed: it refuses to register an
older producer whose help does not advertise execution-only retention, the
dedicated lock, and the host-policy pause; it refuses while the enrichment task
is enabled; it registers BelowNormal; and it does not call
`Start-ScheduledTask`. Task Scheduler owns the configured trigger.

## P4 — composed decision calendar

Using the supplied power table unchanged, the cheapest decisive pilot is
**$25 total / tier-20 with 22 countable dates**. Fifteen dates is the 80%-power
base case, but is not decisive under the supplied date-shock envelope. The
22-date version is genuinely decisive under that envelope. The $50 / tier-50
path needs 43 shock-envelope dates and is additional capacity, not the cheapest
first decision.

If 2026-08-06 is countable date 1 and every following calendar day is
countable, the theoretical earliest verdicts are:

| Path | Countable dates | Earliest perfect-capture verdict |
| --- | ---: | --- |
| $25 / tier-20 shock envelope | 22 | 2026-08-27 |
| $50 / tier-50 shock envelope | 43 | 2026-09-17 |

Those are lower bounds, not an operator promise. `clob_freshness` uses the
maximum qualifying gap over the active day, and any failure makes the whole
fleet-date non-countable. The retained host incident had qualifying gaps in
Denver, Miami, and Los Angeles despite all 12 markets being trailing-fresh;
that date therefore has a 0% fleet-date result, not 9/12 credit. The watcher
repair is held and unmerged, and its acceptance asks for two complete active
windows. There is not yet a defensible empirical countable-day fraction above
zero.

Planning sensitivity, explicitly not an estimate:

| Countable fraction | Calendar days for 22 | Verdict date | Calendar days for 43 | Verdict date |
| ---: | ---: | --- | ---: | --- |
| 100% | 22 | 2026-08-27 | 43 | 2026-09-17 |
| 80% | 28 | 2026-09-02 | 54 | 2026-09-28 |
| 60% | 37 | 2026-09-11 | 72 | 2026-10-16 |
| 50% | 44 | 2026-09-18 | 86 | 2026-10-30 |

Until `-09-14a` is integrated and two complete active windows establish a
rate, plan in the 50–80% sensitivity band, not at 100%. Thus 22 countable
dates may realistically occupy 28–44 calendar days; the honest current value
remains “unmeasured,” and a worse realized rate moves the dates later. The
reserved confirmation window is armed but undated and adds no reserved dates
to this calculation.

## P5 — roll safety and merge placement

This branch changes only the following tracked files:

| File | Snapshot closure | CLOB closure | Observation-trigger closure | CLOB-enrichment closure | Verdict |
| --- | --- | --- | --- | --- | --- |
| `scripts/ops/register_maker_tape.ps1` | no | no | no | no | roll-free; operator-only task registration |
| `docs/roadmap/agent-report-2026-08-05-workstation-start-the-maker-tape.md` | no | no | no | no | roll-free documentation |

The verdict comes from retained runtime import closures, not a source glob.
Neither file is imported by a long-lived capture process. This branch itself
requires no snapshot, CLOB, observation-trigger, or enrichment roll.

The producer narrowing belongs in the refreshed `-09-11a` branch, before this
registration contract is integrated. Keep the dedicated writer local to
`mm_execution_capture`; do not casually move its schema into shared
`schema_registry_data.py`, which the handoff establishes is in all four
capture closures and therefore forces a coordinated quiet-window adoption.

Standing integration order with this branch inserted:

```text
refreshed -09-11a (narrow producer)
  -> -09-14a
  -> -09-17a (this roll-free script/report)
  -> refreshed -09-01a alone
  -> -09-04a
  -> refreshed -09-12a + PIT seam
```

No PR or merge is part of this mission. Production registration remains a
separate operator action after the preceding producer and watcher work is
integrated, adopted in a quiet window where required, and verified.

## Verification performed

- PowerShell parser validation of `scripts/ops/register_maker_tape.ps1`.
- One 30-second public, read-only 12-market websocket probe in ignored scratch.
- Hybrid replay through held `mm_paper_scoring` and `mm_day_countability`, with
  one live strict-through execution and explicitly synthetic complementary
  paper evidence.
- No production scheduled-task mutation, no order, no credential access, no
  write under `data/`, no mirror write, no provider/tier/promotion change.
