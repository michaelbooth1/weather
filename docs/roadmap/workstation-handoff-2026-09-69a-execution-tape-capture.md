# Workstation handoff 2026-09-69a — build the production execution-tape capture

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no fitting, no trading, no live endpoint calls.**

## 1. Why this, and why now

The market-making track's blocker is recorded as **absent execution evidence** — not gates, not
permissions. `fills.jsonl` has never been written anywhere on the production host. The operator
authorized MM decisions on 2026-08-09 with **execution capture first, harvest after, and the order
is load-bearing.**

**Tonight that blocker was measured away.** `WeatherExecTapePilot` ran 18:15–18:45 on production
against the documented, read-only market websocket and captured real trades:

| Readout | Value |
| --- | ---: |
| Trades | **40** in 1,800 s across **11 markets** |
| Rate | **79.98 / hour** (3 markets, 66 token ids) |
| `identity_survives` | **true** — zero missing on all seven identity fields |
| Bytes | **16,007 execution-only / 30 min** ≈ **400 B/trade** |

Every row carries `transaction_hash`, so a trade is checkable against chain state rather than being
our own unverifiable assertion. Extrapolated to 12 markets this is **~3 MB/day — 0.03% of the
~9.6 GB/day capture budget.** Cost is not why this does not exist.

> **Execution history is the only data in this project that cannot be backfilled.** Weather history
> re-fetches. Order books we already retain. Trades that happen tonight and are not captured are
> gone permanently.

The pilot was a one-shot and has self-disarmed. **Nothing is capturing execution data right now.**

## 2. Your inputs — you may not call the endpoint

**The workstation must not call exchange endpoints.** Build and test entirely against the committed
fixture:

| File | Bytes | sha256 (16) | Rows |
| --- | ---: | --- | ---: |
| `docs/roadmap/execution-tape-pilot-2026-08-10-trades.jsonl` | 15,967 | `2710e5cf4d9438ac` | **40** |
| `docs/roadmap/execution-tape-pilot-2026-08-10-report.json` | 877 | `7cfdebd0c0ae0bd5` | — |

Both are LF-normalised and pinned `-text` in `.gitattributes`, so those hashes reproduce on your
checkout. Verify them before you start. A record looks like:

```json
{"asset_id":"…","event_type":"last_trade_price","fee_rate_bps":"0","market":"0x…",
 "price":"0.999","side":"BUY","size":"341.89","timestamp":"1786400108425",
 "transaction_hash":"0x…"}
```

The live pilot runner is on production at `C:\tmp\weather-exec-pilot\runner.ps1` — **you do not have
it and do not need it.** Treat the fixture as the wire format.

## 3. What to build

A capture module that turns that stream into durable, auditable evidence. Model it on the existing
capture loops and on `weather.operations.clob_order_book_tiering` for the verify-then-delete
discipline — **do not invent a new pattern where one is already proven.**

### (a) The writer
- Append-only JSONL per market-day, alongside the existing snapshot artifacts.
- **`append_jsonl` reopens the file on every append.** That is the exact crash mode that took
  capture down for 5 h 54 m on 2026-08-09 when a sidecar reached 625 MB. At ~3 MB/day this is not
  imminent, **but build rotation in from the start** rather than filing it as a risk.
- **Deduplicate on `transaction_hash`.** Reconnects will re-deliver. State plainly what your dedupe
  key is and what happens when the same hash arrives with different fields.

### (b) The counter that cannot lie
Every check on this host must be able to say **what it last counted**, never "it is green". A
stopped counter looks satisfied. So the capture must record, per market-day:
- trades written, duplicates suppressed, last trade timestamp seen;
- **websocket connection state and every gap**: disconnect at, reconnect at, seconds dark;
- **explicitly distinguish "no trades because the market was quiet" from "no trades because we were
  disconnected."** These are the same empty file and completely different facts. Getting this wrong
  is the single most likely way this capture silently becomes worthless.

### (c) Sizing and retention
From the fixture and the report, derive and state: bytes/trade, projected bytes/market-day, and
projected GB/year at 12 markets. **Disk is currently the binding constraint on the lock** — 151.4 GB
free, −10.7 GB/day, exhausting ~2026-08-24 against a lock of ~2026-08-22 — so a capture that is
careless with disk will not be armed. Show the number.

### (d) Tests
Real coverage against the fixture: parse, dedupe, rotation, reconnect-gap accounting, and the
quiet-vs-disconnected distinction. **Run the full suite**, not focused tests — a branch push does
not trigger CI, and the last two handbacks could not collect the suite at all.

## 4. Constraints

- **Read-only market data. No order placement, no credentials, no wallet, no signing.** If any part
  of your design needs a key, you have taken a wrong turn — stop and say so.
- **No live endpoint calls from the workstation**, exchange or weather provider. Fixture only.
- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  **Decision 10 stays RETIRED and must not be reassigned.**
- **Do not arm, register, or schedule anything.** You are delivering code and a report. Whether
  capture starts, and when, is the operator's call — I will roll-verify and it merges in the
  01:00–04:00 quiet window.
- **Assume ROLL-SENSITIVE.** A new capture module lands in a live closure. Give a per-file verdict
  from `scripts\ops\roll_verdict.ps1 -Branch <branch>` and **never hand-derive it.**
- **Do not touch** the serving floor, the frozen protocol, settlement, or `high_so_far`. Open
  production questions live there and the data is on my host.
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). `DELEGATION_CONTRACT.md` §2 in full.

## 5. What I want said plainly

- **The rate is one 30-minute evening window.** 79.98/hour is not a day. Overnight and
  pre-settlement rates are unmeasured, and your sizing must say so rather than annualising a single
  sample as if it were stable.
- If you conclude the documented channel is **insufficient** for MM evidence — wrong granularity,
  missing our own fills, not attributable to a maker quote — **say that and change nothing.** That
  answer is worth as much as a working module and it would redirect the whole track.

## 6. Environment, branch and report

Repo venv points at a removed Python 3.11; use the bundled Codex 3.12 runtime. Install nothing.

- Branch: `codex/workstation-execution-tape-capture-2026-09-69a`
- Report: `docs/roadmap/agent-report-2026-08-24-workstation-execution-tape-capture.md`
- Commit the harness and seed.

Base on `origin/master` (`82fba8ac` or later). Per `DELEGATION_CONTRACT.md` §5, with production-host
reproduction paths and the roll verdict. **Commit and push whenever you finish, at whatever hour.**
