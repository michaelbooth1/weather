# S0(a): L2 delta bytes from one public market-channel connection (workstation, 2026-10-16)

Receipt for item (a) of step S0 in the [data layer v2 plan](../../operations/DATA_LAYER_V2_PLAN.md). It sizes VR-2, the
journal of the `book`, `price_change` and `tick_size_change` frames that the execution tape discards today.

## Method

- **One connection.** A single public websocket to the International Polymarket CLOB market channel (`CLOB_WS_URL` in
  `market_microstructure_constants.py`). It used the same subscribe frame (`{"assets_ids": [...], "type": "market"}`)
  and the same 10 s text `PING` as `execution_tape_capture.run_connection_once`. There were no credentials, no
  authenticated or order endpoints, and nothing was signed.
- **Universe.** The 12 built-in markets (`all_specs()`), each for event dates 2026-10-15, 10-16 and 10-17: 36 events,
  792 tokens. Event slugs came from `config_for_date(...)` and token ids from 36 public Gamma `events/slug` GETs at
  start. Every subscribed token appeared in at least one frame. Each token-hour is tagged with the event day relative
  to the market's local date at that hour:
  - **T+0** is the execution tape's universe (264 tokens in every hour).
  - **T+0 and T+1** is the VR-2 priority set (528 tokens).
  - **All subscribed** also includes T+2, or T-1 before the local rollover.
- **Counts only.** For every (event_type, token, UTC hour), the meter kept the item count and the raw UTF-8 bytes of the
  text payload. A list frame's bytes were split across its items in proportion to each item's re-serialised size, and a
  `price_change` item's share was split equally across the assets it names. It also kept per-hour frame totals,
  per-second peaks, connects and reconnects. No frame content, price or size was stored. Bytes are raw websocket
  payload: no journal envelope, and gzip not applied.
- **Guards.** Started 2026-10-16 00:09:51Z, after the 00:00Z floor, with an internal hard deadline of 15:30Z
  (11:30 EDT). The run was set to abort for good on more than 3 reconnects in 10 minutes, on an HTTP 4xx/429 at the
  handshake, or on a 4xxx or 1008 close code. It ran as one below-normal-priority venv interpreter process. The meter
  script and its 10-minute JSON summaries are kept on the workstation in `C:\wt\workstation-chat\l-data\s0a\`.

## Run

- **Ended early on the abort rule** at 12:56:23Z (08:56 EDT). There were 4 reconnects between 12:49:39Z and 12:56:23Z.
- **Earlier reconnects.** 8 isolated reconnects came before the spike: 03:29, 03:40, 03:42, 04:45, 07:29, 08:20, 08:41
  and 11:13Z.
- **How the drops looked.** Every drop was an abrupt close with no close frame. There was no 429 and no policy close
  code. The meter used about 3.7% of one core, so this was not a slow consumer.
- **Production comparison (added 10-16, read by master-agent on the host).** Master-agent read the production
  execution tape's `gaps-00000.jsonl` and `status.json` for the 12 markets, shared-open and read-only.
  - Production had **no disconnect in 12:49-12:57Z** on any connection group. Its last drop before the read was
    12:25Z, on the nyc/sf/seattle/toronto group.
  - Production groups drop together near the top of the hour (04, 05, 06, 07, 09 and 10:00Z). Its other drops cluster
    across groups at 06:19, 06:36/37, 07:24, 07:53, 08:25, 08:33, 08:50, 09:52, 10:25 and 10:56Z.
  - None of the meter's drops falls within a minute of a production drop. Its 4-drop burst is therefore specific to its own
    connection, not a venue-wide event. The likely difference is subscription size: production caps tokens per
    connection (`max_tokens_per_connection`), while the meter held all 792 on one socket. A per-connection size or
    rate limit is the leading hypothesis; it is not proven.
  - For a rerun (the 13Z-23Z hours), split the meter's tokens across connections no larger than production's cap.
- **Coverage.** The full hours are 01Z-11Z (11 hours, 21:00-08:00 EDT), plus two partial hours: 00Z (3,008 s) and 12Z
  (3,371 s). The percentiles use full hours only.
- **Not covered.** UTC hours 13Z-23Z (09:00-20:00 EDT) were not sampled at all. That includes the US daytime trading
  hours and the excluded 12:00-18:00 EDT window.
- **Totals.** 7,015,610 text frames and 4.33 GB in all. `price_change` is over 98% of the L2 bytes.

## Results

Bytes per (token, UTC hour) over the 11 full hours (1 MB = 10^6 bytes, raw payload):

| Universe (token-hours) | Family | zero share | p50 | p90 | **p95** | **p99** | max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T+0, exec-tape universe (2,904) | L2 total | 0.0% | 36 KB | 0.96 MB | **1.80 MB** | **7.66 MB** | 32.9 MB |
| | price_change | 0.0% | 36 KB | 0.92 MB | 1.76 MB | 7.57 MB | 32.8 MB |
| | book | 62.9% | 0 | 19 KB | 39 KB | 121 KB | 297 KB |
| | tick_size_change | 99.4% | 0 | 0 | 0 | 0 | 0.6 KB |
| T+0 and T+1 (5,808) | L2 total | 0.0% | 170 KB | 1.21 MB | **1.92 MB** | **5.67 MB** | 32.9 MB |
| | price_change | 0.0% | 166 KB | 1.19 MB | 1.87 MB | 5.66 MB | 32.8 MB |
| | book | 60.6% | 0 | 16 KB | 30 KB | 88 KB | 297 KB |
| All subscribed (8,712) | L2 total | 14.5% | 113 KB | 1.00 MB | 1.46 MB | 4.25 MB | 32.9 MB |
| For comparison: T+0 `last_trade_price` (kept today) | | 72.5% | 0 | 1.6 KB | 3.5 KB | 11 KB | 34 KB |

Per-(token, hour) budget that binds in under 5% / under 1% of token-hours, and what it would drop:

| Universe | p95 budget | token-hours over p95 | bytes dropped at p95 | p99 budget | bytes dropped at p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| T+0 | 1.80 MB | 5.0% | **45%** | 7.66 MB | 18% |
| T+0 and T+1 | 1.92 MB | 5.0% | **26%** | 5.67 MB | 12% |

Volume and rates:

| Measure | T+0 (264 tokens) | T+0 and T+1 (528) | All (792) |
| --- | ---: | ---: | ---: |
| Mean L2 bytes per full hour | 127 MB | 291 MB | 335 MB |
| Max L2 bytes in one hour | 330 MB (06Z) | 490 MB | 520 MB |
| **Projection, mean hour × 24** | **3.1 GB/day** | **7.0 GB/day** | **8.0 GB/day** |

- **Peaks.** All subscribed tokens peaked at **2,255 frames/s** and **1.76 MB/s** in one second (09Z). The per-hour
  peaks were 737-2,255 frames/s. Hourly means were about 98-235 frames/s.
- **Concentration.** The top 1% of T+0 token-hours carry 34% of T+0 bytes. Dallas alone carried 465 MB of the 1.4 GB T+0
  total, followed by Austin and Chicago at about 190 MB each.
- **T+0 depends on the hour.** From 01Z to 04Z, T+0 is the closing 10-15 day, and its hours are 11-35 MB. After the US
  local rollover (05Z-11Z), T+0 hours are 100-330 MB, a mean of about 184 MB, which is about 4.4 GB/day if held all day.

## What this means for VR-2

- **The budget that binds in under 5% of hours** is about **1.8-1.9 MB of raw payload per (token, hour)** on this sample
  (p95). The under-1% budget is 5.7-7.7 MB.
- **Volume is heavy-tailed.** A p95 budget drops 26-45% of the bytes, all of it in the few hottest token-hours, which
  are exactly where cancel-vs-fill evidence matters. The pre-registered priority order and the `cap`/`gap` rows carry
  that loss. "Binds in <5% of hours" and "keeps most bytes" are not the same target.
- **Raw L2 is several GB/day.** It is 3.1 GB/day for the exec-tape universe and 7.0 GB/day with T+1, before gzip at
  seal. The plan's provisional Phase C envelope (≤0.65 GiB/day, of which about 0.25 GiB is left for VR-2) holds only
  if gzip of `price_change` JSON reaches about 11x for T+0 alone, or about 26x with T+1. **The post-gzip ratio is not
  measured.**
- **Feed side.** Production's exec-tape sockets already receive the T+0 share of this traffic and discard it, so
  journalling adds disk and CPU but no new socket traffic for T+0. T+1 would add subscriptions.

## Limits

- **One night, US hours missing.** This is one night, 11 full hours, all between 21:00 and 08:00 EDT. The US daytime
  hours (13Z-23Z) were not sampled, and they likely carry the heaviest near-close T+0 traffic. One night under-samples
  the tail. Treat p95 and p99 as provisional lower bounds, and re-measure across a full day and more than one weekday
  before fixing the budget.
- **Reconnect dumps.** Each reconnect re-sent the initial `book` snapshots. Those dumps sit inside the hours they fell in,
  as they would for a production journal.
- **Byte attribution.** Splitting bytes across the items of a list frame and across the assets of a `price_change` item
  is an approximation. Per-hour totals are exact frame bytes.
