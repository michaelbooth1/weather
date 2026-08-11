# Pre-overnight audit — 2026-08-10 21:00

Production host `MICHAEL`. Every number below was measured on production tonight, not carried
forward from a prior report. Verdict: **ATTENTION**, one item newly resolved in our favour and one
newly quantified against us.

---

## 1. The execution tape works. The MM blocker is removable.

`WeatherExecTapePilot` fired 18:15–18:45 and **produced real execution evidence** — the first this
project has ever held. It subscribed to 66 token ids across toronto, nyc and atlanta on the
documented market websocket and ran 1,800 s.

| Readout | Value |
| --- | ---: |
| Trades captured | **40** |
| Rate | **79.98 / hour** |
| Distinct markets touched | **11** |
| `identity_survives` | **true** |
| Identity fields missing | **0** on every one of `asset_id`, `market`, `price`, `side`, `size`, `timestamp`, `transaction_hash` |
| Execution-only bytes / 30 min | **16,007** |
| Raw bytes / 30 min | 8,830,640 |

A record is fully identified and settlement-grade:

```json
{"asset_id": "9769277549...698", "event_type": "last_trade_price",
 "fee_rate_bps": "0", "market": "0x555ef29e...8c21", "price": "0.999",
 "side": "BUY", "size": "341.89", "timestamp": "1786400108425",
 "transaction_hash": "0x1f32e955...1ba0"}
```

BUY 23 / SELL 17 across the sample. **`transaction_hash` is present on every row**, so each trade
is checkable against chain state rather than being our own unverifiable assertion.

**Why this matters more than it looks.** The MM track's blocker is recorded as *absent execution
evidence* — not gates, not permissions. `fills.jsonl` has never been written anywhere on this host
(verified again tonight: zero matches fleet-wide). Tonight's pilot shows the evidence is obtainable
from a **documented, read-only** channel, with full identity, at **~400 bytes per trade**.

**Sizing the real thing.** 80 trades/h × 24 h ≈ 1,920 trades/day for 3 markets ≈ **0.8 MB/day**;
extrapolated to 12 markets ≈ **~3 MB/day**. Against a capture budget of ~9.6 GB/day this is
**0.03%**. Cost is not the reason this does not exist.

> **Execution history is the only data here that cannot be backfilled.** Weather history re-fetches.
> Order books we already retain. Trades that happen tonight and are not captured are gone
> permanently. Every day without this capture is a day of MM evidence that can never be recovered.

Evidence preserved into the repo, out of volatile `C:\tmp`:

| File | Bytes | sha256 (16) | Rows |
| --- | ---: | --- | ---: |
| `docs/roadmap/execution-tape-pilot-2026-08-10-report.json` | 877 | `7cfdebd0c0ae0bd5` | — |
| `docs/roadmap/execution-tape-pilot-2026-08-10-trades.jsonl` | 15,967 | `2710e5cf4d9438ac` | **40** |

Both scanned for credentials before commit: **zero matches**. The pilot task has self-disarmed and
is `Disabled`; it is a spent one-shot and captures nothing further.

> **Hashes are of the LF-normalised files, and `.gitattributes` pins these paths `-text`** so the
> on-disk bytes and the committed blob stay identical on any checkout. As captured they were CRLF
> (909 / 16,007 bytes) — the `execution_only_bytes: 16007` above is that as-captured figure. Line
> counts are unchanged; only line endings differ. A hash nobody else can reproduce is not evidence.

---

## 2. Disk is now the binding constraint on the lock, and it is not a leak

| | |
| --- | ---: |
| Free (21:05) | **151.4 GB** |
| Net trend | **−10.7 GB/day** |
| Headroom | **~14 days → exhausts ~2026-08-24** |
| Streak | 1/14, day 1 `2026-08-09`, **lock ~2026-08-22** |

**These are the same week.** If the disk fills, capture dies and the streak resets to zero — so
disk, not capture health, is what the lock now depends on.

**It is not a leak.** One market-day directory is ~800 MB; × 12 markets = **~9.6 GB/day**, which
matches the observed trend. This is the steady-state cost of capturing 12 markets. Intraday it is
worse than the average suggests: free space fell **152.6 → 151.4 GB in 25 minutes** (~2.9 GB/h)
because the day's raw CSVs accumulate until `WeatherClobTiering` reclaims them at 05:00. That job
ran today at 05:00, exit 0, and **reclaimed 18.04 GB** (167.1 → 185.2 GB free). Tiering is healthy.

**The available lever, measured rather than assumed.** `clob_tiering_run.ps1` states its scope
plainly: *"The raw `order_books.jsonl` stays as canonical evidence — only the CSV projection is
compressed."*

| Artifact | Files | Total |
| --- | ---: | ---: |
| `order_books_long.csv` (tiered to `.gz`) | 32 | 17.56 GB |
| **`order_books.jsonl` (kept raw by design)** | **708** | **133.47 GB** |

Measured gzip on a real settled tape — nyc `2026-08-09`:

```
raw 308,109,123  ->  gz 28,078,865      = 10.97x
```

At that ratio the retained tape compresses to **~12 GB, reclaiming ~121 GB** — turning ~14 days of
headroom into **~25+ days** and clearing the lock window with room. Compression is reversible, so
canonical evidence stays canonical; this is a storage-format change, not a retention change.

**Not done tonight, deliberately.** This touches `CANONICAL_EVIDENCE` and every reader that opens
those paths. It needs a tool with the same verify-then-delete discipline the CSV tier already has
(sha256 + line-count verification, 2 h writer quiescence, cleanup preflight). Filing a risk is not
mitigating it — but neither is a hand-run `gzip` over 708 files at 21:00 on the live tree.

Also idle and reclaimable with far less ceremony: **4.69 GB** of rotated `.jsonl`/`.log` archives in
`data\snapshots\` (38 files), of which the sweep already flags 2,372 MB as cold-storage-eligible.

---

## 3. Settlement holes are real, correctly diagnosed, and correctly armed

`2026-08-06` and `2026-08-08` are genuinely unsettled fleet-wide. `settlement.json` **exists** for
every one of the 24 market-days, which is misleading — the ledger is the authority and it reads:

| Date | `settlement_source` | `settlement_high` |
| --- | --- | ---: |
| `2026-08-06` | `'none'` | `None` |
| `2026-08-08` | `'none'` | `None` |
| `2026-08-09` | `'daily_summary'` | **`91.0`** |

Root cause is upstream of settlement: **the WU daily summary has no row for those two dates**, and
the gap is identical across all 12 stations —

```
station    08-05  08-06  08-07  08-08  08-09
klga/kord/ksfo/...   OK   ****   OK   ****   OK      (all 12 identical)
```

**I was wrong about the mechanism and checked before writing it down.** My first reading was the
documented poisoning trap — `treated_as_source_unavailable` causing `missing_dates()` to silently
subtract the date. The error log does still carry `permanent_no_data` 404 rows for `2026-08-05` and
`2026-08-06`. But querying the production functions directly:

```
unavailable_dates()                      -> []          (empty, all stations)
missing_dates(2026-08-04, 2026-08-09)    -> ['2026-08-06', '2026-08-08']
```

**The dates are not poisoned.** `-09-37a`'s re-derivation from status code is doing its job: the
stale rows no longer poison, and `missing_dates()` names both holes correctly. A refetch will
attempt them.

**And the repair is proven, not hoped for.** `WeatherSettlementBackfill20260805` ran today at 05:30,
exit 0, and `2026-08-05` is now present at `max_temp 84.0`. The two outstanding tasks are armed with
the identical command shape:

- `WeatherSettlementBackfill20260806` → **2026-08-11 05:30** (`-TargetDate 2026-08-06 -Refetch`)
- `WeatherSettlementBackfill20260808` → **2026-08-13 05:30** (`-TargetDate 2026-08-08 -Refetch`)

**The open concern is rate, not mechanism.** Three holes appeared in five days (08-05, 08-06, 08-08)
and repair runs one date per scheduled task, two to three days apart. That is barely break-even, and
**countable date volume is the critical path**. If a hole forms for `2026-08-10`, the queue extends
again.

---

## 4. Checks that passed, and what each one last counted

- **Capture: live.** All 12 markets wrote within 5 seconds of the check (`clob_capture_status.jsonl`
  / `order_books.jsonl`, 20:41:19–20:41:20). Not "green" — twelve fresh writes.
- **Crash hazard: clear.** The 2026-08-09 outage was a 625 MB `.jsonl` sidecar failing to reopen.
  Live sidecars tonight: `diagnostics.jsonl` **30.4 MB**, `clob_diagnostics.jsonl` 34.6 MB,
  `observation_triggers.jsonl` 20.0 MB, `observation_trigger_diagnostics.jsonl` 13.2 MB. Rotation is
  working — the 625 MB and 752 MB files are rotated archives, not live. `live_append_oversized` does
  not fire.
- **`observation_trigger_console.log` is 1,055 MB** and flags WARN only. Per the 08-09 lesson this
  is the right severity: a console redirect holds its handle open and has no reopen to fail, so an
  oversized console is **disk pressure, not a crash risk**. Size alone is the wrong priority signal.
- **Console timestamps are not a stall.** `loop_console.log` and `observation_trigger_console.log`
  last show 10:44, which reads alarming and is meaningless — Windows does not flush directory
  metadata for a held handle. Capture freshness above is the real check.
- **Merge driver:** finished 2026-08-10 06:16 after merging `-09-57a` and `-09-58a`, both pushed.
  Seven branches (`-09-62a`…`-09-68a`) are queued for 05:15 tomorrow.
- **The 12:33 "merge attempt: abort" is by design** — the driver refuses inside the 12:00–18:00
  graded capture window. Not a failure.
- **Git:** `cbeb9a99`, clean tree, `HEAD == origin/master`.
- **Off-host mirror:** ok, 15.6 h ago, restore-verified 16/19.

## 5. Standing items unchanged

- Archive season window still `05-10..06-30` — CRITICAL in the sweep, and the re-fetch **still has
  not been run**. Today `08-10` is outside it.
- A dead supervisor tombstone (`restart_budget_exceeded 6>=6`) persists from the 08-09 incident
  while capture runs healthy. Stale evidence, not live state — but it means the tombstone is not
  self-clearing.
- 3 unexpected shutdowns in 90 days; power loss remains the top uncontrolled risk. Recorded, not
  re-raised.

---

## What I changed tonight

Nothing operational. Two evidence files copied into the repo and this document. No data deleted, no
task altered, no branch merged, no serving path touched.
