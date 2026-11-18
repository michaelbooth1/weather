# 2026-10-03 — trade-stream coverage: why the execution-tape socket drops, and the fix

**VERDICT: FIX READY; DOMINANT CAUSE INFERRED FROM CODE, NOT YET MEASURED. Production must run the
classifier on the 09-29 lifecycle rows to confirm it. The socket thread did all tape work inline.
That includes each trade append, the status writes and the shared coordinator lock, which waits
behind the fsync flusher. While the disk is slow the thread stops draining the socket and sending
`PING`. Its silence deadline then fires on our own stall, or the venue drops a reader that has
stopped reading. Load is heavier in the day, which fits the 30-87/h daytime against 2-10/h
overnight. A control run shows the old loop disconnecting on a 1.5 s lock stall with a live server
(silence deadline set to 0.6 s); the new loop stays connected. Roll-sensitive (rolls the
execution-tape producer). Draft PR only; DO NOT MERGE BEFORE 2026-10-14.**

Mission: owner prompt 2026-10-02 (no handoff file). Branch `codex/trade-stream-coverage-20261003`
from `origin/master` `fd274ac5`, with `origin/codex/execution-tape-fsync-20261001` (#152, `a09beb45`)
merged first. `execution_tape_io.py` is unchanged. Reserved confirmation window: NONE RESERVED
(checked at run time). No production data was read. Every statement below comes from code, the
committed fixture, or a fixture-driven run.

## Part 1 — disconnect causes, from code

Every way a session ends writes one `OPEN` gap row (the lifecycle row) per route on that
connection. The row's `reason` is the text below. One socket failure therefore costs as many rows as
the connection has market-days. The 1,968 rows on 09-29 are probably several hundred socket events.
The classifier reports both counts.

| Cause (classifier label) | Where it is raised (pre-fix) | Load-sensitive? |
| --- | --- | --- |
| `silence_timeout` | top of the reader loop: 30 s since the last inbound frame, checked *before* reading | **Yes, falsely.** A stall in tape work (heartbeat, ingest, `TAPE_FSYNC.check()`, coordinator `RLock`) longer than 30 s trips it even when the socket holds buffered frames. A true venue silence would be *more* common overnight, the opposite of what was observed. |
| `empty_frame` | `recv()` returned `""` | Mixed. In `websocket-client` 1.9.0 `recv()` returns `""` for a **venue close frame** and for an empty text frame, so the close code was lost. A venue that drops slow consumers shows up here. |
| `connection_lost` / `connection_reset` | `WebSocketConnectionClosedException`, `ConnectionResetError` (WinError 10054) | **Yes** if the venue resets readers that fall behind (TCP window full while we are stalled). |
| `confirmation_timeout` | every requested asset of every route must be proven within 30 s of subscribing | **Yes.** The initial book frames were processed through the same inline tape path, so a stall right after a reconnect also failed proof. |
| `socket_timeout`, `tls_error`, `connect_failed`, `handshake_rejected` | `create_connection` / TLS / HTTP 429 | No (network or venue side). |
| `tape_writer_error` | a persistent fsync fault re-raised by `TAPE_FSYNC` (#152 makes transients retry) | Yes, but #152 already absorbs transient faults. |
| `orderly_stop`, `seed_error`, `session_replaced`, `process_restart` | fleet rotation when `location_market_events.json` regenerates (4×/day), seed failure, process restart | No. At about 4 events a day, far too few to explain the volume. |

Why the reader stalls (#152 code, read but not edited): `TapeFsyncBatch.sync_due()` holds the
flusher's condition lock while it fsyncs every dirty handle in turn. Every writer operation and
every `StatusCadence.due()` (via `TAPE_FSYNC.check()`) waits on that lock. The capture reader called
`coordinator.heartbeat()` on every inbound frame and every `PONG`, taking the coordinator's single
`RLock` (shared by all connection threads) and then that condition. So all readers stalled together
whenever the flusher was slow. Fsync latency grows with daytime disk load on the capture host.

Two further coverage defects, independent of the cause:

- **The backoff never reset after a failure.** `connection_worker` reset `delay` only when a
  session *returned*, and a session returns only on stop. After the first few drops, every
  later gap waited the full 30 s cap. The cost was coverage per disconnect, not the number of
  disconnects.
- **Reconnects were in lockstep.** Every connection waited the same delay, so one venue-wide
  drop reconnected all of them in the same second.

**Prediction to test with the extract (pre-registered here):** on 09-29 the daytime excess is
dominated by `silence_timeout`, `empty_frame` and `connection_lost`/`connection_reset`, not by
`confirmation_timeout`, `connect_failed`, `handshake_rejected` or `orderly_stop`. Session lifetimes
for those causes should be short and spread out. A narrow cluster (e.g. every N minutes) would
instead mean a venue session limit. If venue-side connect failures or handshake 429s dominate, the
inference is wrong and the fix below addresses only the secondary defects.

### Production extract (transfer manifest)

[`agent-report-2026-10-03-trade-stream-coverage-transfer-manifest.json`](agent-report-2026-10-03-trade-stream-coverage-transfer-manifest.json)
lists the extract: execution-tape `gaps-*.jsonl` and per-route `status.json` for market-days dated
09-26..09-29 only. The 09-28 slugs carry the early hours of local 09-29 for western markets. It gives
two ways to run it, (a) in place from a detached verify worktree or (b) as an archive for the
workstation. The command is read-only and writes only to `scratch/`.

## Part 2 — the fix (`src/weather/market/execution_tape_capture.py`)

1. **Reader/writer split.** The connection thread now only receives, sends `PING`, stamps
   `received_at`, and proves routes, which is a pure function of the frame. A per-session writer
   thread applies `mark_connected`, `heartbeat` and `ingest_frame` in arrival order from a bounded
   queue of 4,096 frames. The reader blocks only when that many frames are behind; it never drops a
   frame. A writer error ends the session and is raised. On any exit the queue is drained first, and
   then the gap row is written, stamped at the moment reading stopped.
2. **Silence is judged only after a receive has just timed out.** A local stall can no longer be
   read as server silence. The 30 s deadline is kept: the venue answers `PING` every 10 s, so 30 s
   means three missed `PONG`s. That is real silence at any hour, and quiet markets do not need a
   longer deadline because `PONG` keeps arriving.
3. **Opcodes are read** (`recv_data`). A close frame raises `VenueCloseError` and its gap reason
   carries `code=<n> reason=<text>`. An empty data frame counts as inbound liveness. Test doubles
   without `recv_data` keep the old `recv()` path.
4. **Backoff reset and jitter.** A session that kept every route proven for 60 s resets the delay
   to the 1 s base. Each wait is jittered into [d/2, d], so connections stagger. Unproven failures
   still double to the 30 s cap.

**Recorded semantics unchanged.** Venue `timestamp` fields are stored as received. `received_at_utc`
is the reader's stamp at receive time, exactly where it was taken before. Gap rows are still
written per route, with the same schema and the same `startup_connecting`/`stop_requested` and
exception-text reasons. The only change is that close-frame drops now name their code instead of
`ConnectionError: websocket returned an empty frame`. Coverage still begins only after routed
frames prove every asset, and `PONG` alone still never proves a route.

New read-only command `python -m weather.market.execution_tape_disconnects --date <local date>`
(`src/weather/market/execution_tape_disconnects.py`). It reports lifecycle rows and socket-level
events by cause, venue close codes, an hourly table, a daytime/overnight split, dark seconds by
opening cause and session lifetimes. It also lists input files with their SHA-256.

### Evidence

- **Control run** (fixture trade, real `ExecutionTapeCoordinator` in a temp root, a server that
  answers `PONG` every 50 ms, coordinator lock held 1.5 s, silence deadline 0.6 s, `PING` every
  0.2 s). Pre-fix `HEAD` code: `TimeoutError: no inbound server heartbeat or market frame before
  silence deadline`. Fixed code: `stop_requested`, no disconnect.
- **New tests, all writing with the production writers.**
  `tests/market/test_execution_tape_stream_coverage.py` covers the lock stall: no drop, `PING`s sent
  during the stall, all 3 trades written with reader receipt stamps. It also covers close code
  1011 and a close with no code reaching the gap row, empty data frames, frames before a drop being
  written before the gap row, a writer fault ending the session, real silence still disconnecting,
  backoff escalation, reset after a 120 s proven session, no reset after a 10 s one, and jitter
  bounds. `tests/market/test_execution_tape_disconnects.py` builds a two-route ledger with the real
  coordinator and checks socket-event grouping, causes, hours, lifetimes and dark seconds. The stall
  test passed 15 of 15 repeats.
- **Focused suites:** `tests/market/test_execution_tape_*.py` and
  `tests/operations/test_execution_tape_supervisor.py`: 60 passed.
- **Full suite** through `scripts/ops/workstation_heavy.ps1` and GitHub CI: see the handback reply
  for the result and head SHA.

## Per-file roll verdict

`roll_verdict.ps1` returns UNDECIDABLE on the workstation (no live closure files). Static reading:

| File | Verdict |
| --- | --- |
| `src/weather/market/execution_tape_capture.py` | **Roll-sensitive.** It is in the execution-tape producer's import closure (`execution_tape_supervisor` imports it), so merging triggers that producer's stale-code readoption. No core capture loop imports it. |
| `src/weather/market/execution_tape_disconnects.py` | New; no loop imports it. Roll-free by closure. |
| `tests/...`, `docs/...` (this report, the manifest, `OPERATIONS_DESIGN.md`, item 326) | Roll-free. |

Merge only through `quiet_window_merge.ps1` in a 01:00-04:00 window **after 2026-10-13** (the exam
panel). Production must take the verdict from `roll_verdict.ps1 -Branch` on the host.

## Not done

- No production data read, no extract run, no registration, restart, Scheduler change, merge or
  venue call. The draft PR is not to be merged before 10-14.
- 09-29 has not been measured. The dominant cause stays an inference until the manifest's command
  runs on production.
- `src/weather/market/maker_evidence_stream.py` (the 88a maker-evidence public trade channel and its
  `stream_lifecycle` rows) has the same inline read-and-write loop and the same silence check before
  the read. It was out of scope. If the maker hazard is fitted from 88a rows rather than the
  execution tape, it needs the same change.
- `execution_tape_io.py` was not edited. Its flusher still fsyncs while holding its lock. The split
  stops that lock from reaching the socket, but the writer thread can still lag.

## Reproduction

On the workstation, from a checkout of this branch (or on production in 00:30-09:00, serially):

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=C:\pt\tsc tests\market\test_execution_tape_stream_coverage.py tests\market\test_execution_tape_disconnects.py tests\market\test_execution_tape_capture.py
```

Production extract and classification: follow `option_a_run_in_place` in the manifest.

Commit and branch: `codex/trade-stream-coverage-20261003`. The head SHA is in the handback reply.
