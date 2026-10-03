# 2026-10-03 — 88a public stream coverage: the same inline-write stall, the same fix

**VERDICT: FIX READY; CAUSE SHOWN IN A CONTROL RUN, NOT YET MEASURED ON PRODUCTION. The 88a stream
thread (`maker_evidence_stream.py`) did what the execution-tape reader did before #173: it wrote every
frame to the journal inline, under the shared store `RLock`, with an fsync per row. While the disk or
the lock is slow it stops draining the socket and sending `PING`, and its silence deadline fires on
our own stall. Control run: master's loop drops a live localhost session on a 1.5 s store-lock stall
(deadlines scaled to 0.2 s ping and 0.6 s silence) and loses the trade sent during the gap. The new
loop keeps the session and journals all three trades. Roll-sensitive: merging restarts 88a
(`WeatherMakerEvidenceCapture`). Draft PR only; DO NOT MERGE BEFORE 2026-10-14.**

Mission: owner prompt 2026-10-03 (no handoff file). Branch `codex/88a-trade-stream-coverage-20261003`
from `origin/master` `2db00b53`, with `origin/codex/trade-stream-coverage-20261003` (#173, `96e22678`)
merged first. Reserved confirmation window: NONE RESERVED (checked at run time). No production data
was read; every statement comes from code, fixtures or fixture-driven runs.

## Defects found (pre-fix code)

| Defect | Effect |
| --- | --- |
| Frames, trades, lifecycle and gap rows written inline on the socket thread, each under `store.lock` with `fsync` | A slow disk, the main worker's book writes or compression's lock use stalls reading and `PING` |
| 30 s silence check at the top of the loop, before reading | A local stall longer than 30 s is recorded as `TimeoutError: public stream inbound silence` |
| `recv()` turned a close frame and an empty text frame alike into `ConnectionError: public socket closed` | Venue close codes were lost; empty data frames ended the session |
| Fixed 2 s reconnect wait on every socket | No backoff against a refusing venue, and all sockets (one per 100 tokens per channel) reconnect in lockstep |
| `captured_at_utc` stamped by the store at write time | Under a stall it carried the write time, not receipt |

## The fix

1. **Reader/writer split** (`maker_evidence_stream.py`). The socket thread only receives, sends
   `PING`, stamps receipt time, parses trade frames (a pure function; a malformed frame still ends the
   session) and updates the receive counters. A per-session writer thread runs every journal write in
   arrival order from a queue bounded at 4,096 frames **and 64 MiB** (4,096 frames of up to 2 MiB
   would otherwise be 8 GiB on a 16 GB host). The reader blocks only that far behind and never drops a
   frame. A writer error ends the session and is raised by the reader, so it reaches the gap row as
   before.
2. **Drop ordering.** On any exit the reader stamps the moment reading stopped, drains the writer, then
   writes the `disconnected` lifecycle row and (on error) the `stream_gap` row, both stamped at that
   moment.
3. **Silence** is judged only after a receive has just timed out; the 30 s deadline and 10 s `PING` are
   unchanged.
4. **Opcodes** (`maker_evidence_socket.py`). `BoundedWebSocket.recv` reads `recv_data`: a close frame
   raises `VenueCloseError` (a `ConnectionError`) whose text is `venue closed the websocket: code=<n>
   reason=<text>`; an empty data frame is returned as liveness. `connect()` takes an optional URL
   (default unchanged) so tests reach a local server.
5. **Backoff.** Failures double the wait from 2 s to 30 s; a session that stayed connected 60 s resets
   it to 2 s; every wait is jittered into [d/2, d]. A clean session end keeps the base delay.
6. **Receipt stamps** (`maker_evidence_store.py`). `record`/`event` take an optional `captured_at`;
   stream, trade and lifecycle rows pass the reader's receipt time. Without it nothing changes.

**Recorded semantics.** Response bytes, hashes, venue `timestamp` fields, row kinds, row fields,
lifecycle/gap shapes and the daily cap are unchanged; the schema version is unchanged (no field added).
Two precise differences, both toward receipt truth: (a) `captured_at_utc` on stream rows is the receipt
time rather than the time after any lock wait, so a stream row can carry a slightly earlier time than a
book row with a lower `sequence`, and a frame received just before an hour boundary can land in the next
hour's segment (the segment still rolls on the write clock); (b) a close-frame drop now reads
`VenueCloseError: venue closed the websocket: code=…` instead of `ConnectionError: public socket
closed`, and an empty data frame no longer ends a session.

## New read-only report

`python -m weather.market.maker_evidence_disconnects --date <local date> [--root data/maker_evidence]`
(`maker_evidence_disconnects.py`, sibling of #173's `execution_tape_disconnects`, sharing its network
cause patterns). It replays only `stream_lifecycle` and `stream_gap` journals (plain or gzip) per socket
(channel + subscription hash) and reports socket drops by cause, by channel and cause and by local hour,
a daytime/overnight split, venue close codes, connect failures, orderly stops, dark seconds (first drop
to next connect) and session lifetimes, with each input's SHA-256. 88a causes: `silence_timeout`,
`venue_close`, `empty_frame` (pre-fix close or empty frame), `message_bound`, `bad_payload`,
`journal_writer_error`, plus the shared network causes. Production can run it on any closed UTC days;
it reads two small journal kinds and writes nothing unless `--output` is given.

**Pre-registered prediction:** if this defect drives 88a drops, pre-fix days show `silence_timeout`
and `empty_frame`/`connection_*` concentrated in daytime hours, on both channels at once (one shared
store lock), with short session lifetimes. Dominance by `handshake_rejected` or `connect_failed` would
mean the venue side, and this fix then addresses only the secondary defects.

## Evidence

- **Control run** (scratch script, not committed): master's `maker_evidence_stream.py` with ping 0.2 s,
  silence 0.6 s and recv timeout 0.2 s substituted, the production `EvidenceStore` and
  `BoundedWebSocket`, a real localhost websocket server, store lock held 1.5 s. Result: 1 error,
  `TimeoutError: public stream inbound silence`, trades journaled `0.50, 0.51` (the third was lost).
  The new loop under the same scenario: no gap, one connection, all three trades.
- **New tests** `tests/market/test_maker_evidence_stream_coverage.py` (11), production store throughout,
  live tests over a real localhost RFC 6455 server: store-lock stall at 2.5x the silence deadline keeps
  the session, `PING`s continue during the stall, receipt stamps fall inside the stall; close code 1011
  and a code-less close reach the gap row after the frames received before them, with the gap stamped
  before the stalled writes completed; empty data frames are liveness; real silence still disconnects;
  a journal fault ends the session with a gap; backoff escalation, reset after 120 s, no reset after
  10 s, jitter; byte-bounded backlog keeps order. The five live tests passed 10 of 10 repeats.
  `tests/market/test_maker_evidence_disconnects.py` (11) builds journals through `PublicStream` and the
  store, including a gzip-compressed sealed hour.
- **Focused:** maker-evidence capture, stream coverage, disconnects and #173's execution-tape disconnect
  tests: 77 passed, and #173's execution-tape disconnect tests pass alongside. **Repo-wide audits** (agent docs, import architecture, knowledge structure,
  module size, path policy, Python runtime, schema registry, release import boundary): 73 passed;
  `agent_docs_audit` PASS.
- **Full suite** through `scripts/ops/workstation_heavy.ps1` and GitHub CI: see the handback reply.

## Per-file roll verdict

`roll_verdict.ps1 -Branch` returns UNDECIDABLE on the workstation (no live closure files). Static reading:

| File | Verdict |
| --- | --- |
| `src/weather/market/maker_evidence_stream.py`, `maker_evidence_socket.py`, `maker_evidence_store.py` | **Roll-sensitive for 88a only.** Imported by `maker_evidence_capture`; no core capture loop imports them. 88a is a directly registered task, not a supervisor: the production operator re-adopts (restarts) it explicitly after merge. |
| `src/weather/market/maker_evidence_disconnects.py` | New; no loop imports it. Roll-free. |
| #173's files (merged in) | As stated in #173's report: `execution_tape_capture.py` rolls the execution-tape producer. |
| `tests/...`, `docs/...` | Roll-free. |

The `schema_registry*` family is not touched. Merge only through `quiet_window_merge.ps1` in a 01:00-04:00
window after 2026-10-13; if #173 lands first, this branch's diff reduces to the 88a files.

## Not done / residual

- No production data read, no extract, registration, restart, Scheduler change, merge or venue call.
- 88a drop causes on production are not measured; the prediction above awaits the report command.
- `PublicStream.stop()` keeps its 8 s join bound, which now includes draining the backlog. A large
  backlog on a slow disk can exceed it and raise the existing `public stream did not terminate within
  its bound`, as an inline write stalled over 8 s did before. Not changed, to keep the main loop's cycle
  timing.
