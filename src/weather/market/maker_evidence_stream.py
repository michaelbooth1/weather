"""Bounded public update stream plus independent uncapped public trade channel.

Each socket thread only reads, sends ``PING`` and stamps receive time.  A
per-session writer thread journals its rows in arrival order, so an fsync or a
held store lock can no longer stop the socket being drained and pinged.

A trade-channel token-set swap is make-before-break: the new sockets connect and
subscribe while the old ones stay open, and the old ones close once every new
socket has received its first data frame, or after ``SWAP_OVERLAP_SECONDS``.
A trade seen on both sockets during that overlap is journaled once, keyed by the
execution tape's trade identity fields (the venue's ``last_trade_price`` carries
no trade id of its own).  Every token-set change journals a ``stream_tokens`` row
naming the wanted subscriptions, so dark time can be judged per token.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import time
from collections import OrderedDict

from websocket import WebSocketException

from weather.market.maker_evidence_socket import EMPTY_DATA_FRAME, connect
from weather.market.maker_evidence_store import RawFootprintLimit, digest, encoded

MAX_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_TOKENS = 100
PING_SECONDS = 10.0
SILENCE_SECONDS = 30.0
RECONNECT_BASE_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 30.0
# A failed session that had stayed connected this long resets the backoff.
STABLE_SESSION_SECONDS = 60.0
# Received frames waiting for the journal writer; the reader blocks only this far behind.
MAX_PENDING_FRAMES = 4096
# Byte bound on the same backlog: 4,096 frames of up to 2 MiB would otherwise be 8 GiB.
MAX_PENDING_BYTES = 64 * 1024 * 1024
# Make-before-break: the longest the old trade sockets are held open waiting for the new ones.
SWAP_OVERLAP_SECONDS = 5.0
# Cross-socket trade dedupe memory: an identity is forgotten after the horizon, and
# at most this many are held (about 4 MB at the count bound).
DEDUPE_HORIZON_SECONDS = 120.0
MAX_DEDUPE_IDENTITIES = 16_384
# Equal to ``execution_tape_store.TRADE_IDENTITY_FIELDS`` (a test pins the equality).
TRADE_IDENTITY_FIELDS = ("asset_id", "event_type", "fee_rate_bps", "market", "price", "side", "size",
                         "timestamp", "transaction_hash")


def reconnect_delay(delay, random_fn=random.random):
    """Jitter one backoff step into [delay/2, delay] so sockets do not reconnect in lockstep."""
    return delay * (0.5 + 0.5 * random_fn())


class TradeDedupe:
    """Admit each trade identity once across sockets, keeping genuine repeats on one socket.

    A socket's n-th sighting of an identity is new only when no other socket has
    already seen it n times: two overlapping sockets cannot double a trade, and two
    identical-looking trades on the same socket are both kept.
    """

    def __init__(self, horizon_seconds=DEDUPE_HORIZON_SECONDS, max_identities=MAX_DEDUPE_IDENTITIES):
        self.horizon, self.max_identities = horizon_seconds, max_identities
        self.seen = OrderedDict()  # identity -> [last seen (monotonic), {socket id: sightings}]

    def admit(self, socket_id, row, now):
        identity = digest(encoded({field: row.get(field) for field in TRADE_IDENTITY_FIELDS}))
        entry = self.seen.pop(identity, None) or [now, {}]
        while self.seen and (len(self.seen) >= self.max_identities
                             or next(iter(self.seen.values()))[0] < now - self.horizon):
            self.seen.popitem(last=False)
        entry[0] = now
        self.seen[identity] = entry
        counts = entry[1]
        counts[socket_id] = counts.get(socket_id, 0) + 1
        return counts[socket_id] > max((n for key, n in counts.items() if key != socket_id), default=0)


class _JournalWriter:
    """Run one session's journal writes in arrival order, off the socket thread."""

    _STOP = object()

    def __init__(self, max_pending, max_bytes):
        self.error = None
        self._queue = queue.Queue(maxsize=max(1, int(max_pending)))
        self._room, self._pending_bytes, self._max_bytes = threading.Condition(), 0, max_bytes
        self._thread = threading.Thread(target=self._run, name="maker-evidence-writer", daemon=True)
        self._thread.start()

    def raise_error(self):
        if self.error is not None:
            raise self.error

    def put(self, write, *args, size=0):
        with self._room:
            # One oversized frame may always queue alone; otherwise wait for the writer.
            while self._pending_bytes and self._pending_bytes + size > self._max_bytes:
                self.raise_error()
                self._room.wait(0.5)
            self._pending_bytes += size
        while True:
            self.raise_error()
            try:
                self._queue.put((write, args, size), timeout=0.5)
                return
            except queue.Full:
                continue

    def _run(self):
        while (item := self._queue.get()) is not self._STOP:
            if self.error is None:
                try:
                    item[0](*item[1])
                except BaseException as exc:  # The reader re-raises it and ends the session.
                    self.error = exc
            with self._room:
                self._pending_bytes -= item[2]
                self._room.notify_all()

    def close(self):
        """Write every queued row, then stop; a received frame is never dropped."""
        if self._thread.is_alive():
            self._queue.put(self._STOP)
            self._thread.join()


class PublicStream:
    ping_seconds, silence_seconds = PING_SECONDS, SILENCE_SECONDS
    reconnect_base_seconds, reconnect_max_seconds = RECONNECT_BASE_SECONDS, RECONNECT_MAX_SECONDS
    stable_session_seconds, max_pending_frames = STABLE_SESSION_SECONDS, MAX_PENDING_FRAMES
    max_pending_bytes, swap_overlap_seconds = MAX_PENDING_BYTES, SWAP_OVERLAP_SECONDS

    def __init__(self, store, *, trades_only=False):
        self.store, self.trades_only = store, trades_only
        self.stop_event = threading.Event()
        self.threads, self.tokens = [], ()
        self.messages, self.bytes, self.trades, self.errors = 0, 0, 0, 0
        self.duplicate_trades, self.sessions = 0, 0
        self.dedupe = TradeDedupe()
        self.connected = 0
        self.last_event_utc = None
        self.counter_lock = threading.Lock()
        self.window_end = None
        self.monotonic, self.random = time.monotonic, random.random

    @property
    def channel(self):
        return "trades" if self.trades_only else "updates"

    def replace_window(self, tokens, end):
        self.window_end = end
        if end is None or self.store.clock() >= end:
            self.stop()
        else:
            self.replace(tokens)

    def _window_open(self):
        return self.trades_only or (self.window_end is not None and self.store.clock() < self.window_end)

    def replace(self, tokens):
        wanted = tuple(sorted(set(tokens)))
        if (wanted == self.tokens and len(self.threads) == (len(wanted) + MAX_TOKENS - 1) // MAX_TOKENS
                and all(t.is_alive() for t in self.threads)):
            return
        chunks = [wanted[start:start + MAX_TOKENS] for start in range(0, len(wanted), MAX_TOKENS)]
        old_threads, old_event = self.threads, self.stop_event
        try:
            self._journal_tokens(chunks)
        finally:
            if not self.trades_only:
                # Raw update frames carry no identity to dedupe, so that channel stays break-before-make.
                self._halt(old_threads, old_event)
                old_threads = []
        self.tokens, self.stop_event, self.threads = wanted, threading.Event(), []
        ready = []
        for chunk in chunks:
            ready.append(threading.Event())
            thread = threading.Thread(target=self._run, args=(chunk, self.stop_event, ready[-1]), daemon=True)
            self.threads.append(thread)
            thread.start()
        if old_threads:
            # Make-before-break, bounded: the old sockets close once every new one has
            # answered, and never later than the overlap bound.
            deadline = time.monotonic() + self.swap_overlap_seconds
            for event in ready:
                event.wait(max(0.0, deadline - time.monotonic()))
            self._halt(old_threads, old_event)

    def stop(self):
        try:
            if self.tokens or self.threads:
                self._journal_tokens([])
        finally:
            self._halt(self.threads, self.stop_event)
            self.threads = []
            self.tokens = ()

    @staticmethod
    def _halt(threads, stop_event):
        stop_event.set()
        for thread in threads:
            thread.join(timeout=8)
            if thread.is_alive():
                raise RuntimeError("public stream did not terminate within its bound")

    def _journal_tokens(self, chunks):
        """Journal the wanted subscriptions from now on; an empty list means nothing is wanted."""
        try:
            self.store.event("stream_tokens", {
                "channel": self.channel, "tokens": sum(len(chunk) for chunk in chunks),
                "subscriptions": [self.store.subscription(chunk, self.channel) for chunk in chunks]})
        except RawFootprintLimit:
            pass  # Store latched the limit; the main worker writes terminal status.

    def _run(self, tokens, stop_event=None, ready=None):
        stop_event = self.stop_event if stop_event is None else stop_event
        ready = threading.Event() if ready is None else ready
        try:
            self._sessions(tokens, stop_event, ready)
        finally:
            ready.set()  # A finished thread is never waited for.

    def _sessions(self, tokens, stop_event, ready):
        name = self.channel
        delay = self.reconnect_base_seconds
        while not stop_event.is_set() and self._window_open():
            if not self.trades_only and self.store.stream_capped:
                return
            session, failed = {}, False
            try:
                self._session(tokens, name, session, stop_event, ready)
            except RawFootprintLimit:
                return  # Store latched the limit; the main worker writes terminal status.
            except (OSError, ValueError, WebSocketException, TimeoutError) as exc:
                failed = True
                with self.counter_lock:
                    self.errors += 1
                self.store.event("stream_gap", {"channel": name, "error_type": type(exc).__name__,
                                               "error": str(exc)[:300],
                                               "subscription": self.store.subscription(tokens, name),
                                               "backfill_claimed": False},
                                 captured_at=session.get("stopped_at"))
                connected = session.get("connected_monotonic")
                if connected is not None and self.monotonic() - connected >= self.stable_session_seconds:
                    # A long session is not a failing venue; skip a backoff escalated hours ago.
                    delay = self.reconnect_base_seconds
            if stop_event.wait(reconnect_delay(delay, self.random)):
                break
            delay = min(self.reconnect_max_seconds, delay * 2) if failed else self.reconnect_base_seconds

    def _session(self, tokens, name, session, stop_event, ready):
        with connect() as socket:
            session["connected_monotonic"] = self.monotonic()
            writer = _JournalWriter(self.max_pending_frames, self.max_pending_bytes)
            with self.counter_lock:
                self.connected += 1
                self.sessions += 1
                socket_id = self.sessions
            try:
                writer.put(self._lifecycle, "connected", tokens, name, self.store.clock())
                socket.send(encoded({"assets_ids": tokens, "type": "market"}).decode())
                self._read(socket, tokens, writer, stop_event, ready, socket_id)
                session["stopped_at"] = self.store.clock()
                writer.close()
                writer.raise_error()
            finally:
                # Frames already received are journaled first, then the lifecycle
                # row, stamped when reading stopped.
                session.setdefault("stopped_at", self.store.clock())
                writer.close()
                with self.counter_lock:
                    self.connected -= 1
                self._lifecycle("disconnected", tokens, name, session["stopped_at"])

    def _read(self, socket, tokens, writer, stop_event, ready, socket_id):
        next_ping = last_inbound = self.monotonic()
        while not stop_event.is_set() and self._window_open():
            writer.raise_error()
            if not self.trades_only and self.store.stream_capped:
                return  # Cap closes this socket; independent trade capture survives.
            if self.monotonic() >= next_ping:
                socket.send("PING")
                next_ping = self.monotonic() + self.ping_seconds
            try:
                message = socket.recv(timeout=min(1.0, self.ping_seconds))
            except TimeoutError:
                # Silence is judged on socket wait only, never on a local stall.
                if self.monotonic() - last_inbound > self.silence_seconds:
                    raise TimeoutError("public stream inbound silence") from None
                continue
            received_at = self.store.clock()
            last_inbound = self.monotonic()
            if not self._window_open():
                return
            if message in ("PONG", b"PONG"):
                continue
            # The venue answers a subscribe with data (its book snapshot); once it has,
            # a socket this one replaces may close.
            ready.set()
            if message is EMPTY_DATA_FRAME:
                continue
            raw = message.encode() if isinstance(message, str) else message
            with self.counter_lock:
                self.messages += 1
                self.bytes += len(raw)
                self.last_event_utc = received_at.isoformat()
            if not self.trades_only:
                writer.put(self._update, raw, received_at, size=len(raw))
                continue
            payload = json.loads(raw)
            rows = payload if isinstance(payload, list) else [payload]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("public trade channel received a non-object event")
            trades = [row for row in rows if row.get("event_type") == "last_trade_price"
                      and str(row.get("asset_id")) in tokens]
            if not trades:
                continue
            now = time.monotonic()
            with self.counter_lock:
                new = sum(self.dedupe.admit(socket_id, row, now) for row in trades)
                self.duplicate_trades += len(trades) - new
            if new:
                # A frame with any new trade keeps its exact bytes; its repeats are named in metadata.
                writer.put(self._trades, raw, new, len(trades) - new, received_at, size=len(raw))

    def _lifecycle(self, state, tokens, name, at):
        self.store.event("stream_lifecycle", {"state": state, "channel": name,
                                             "subscription": self.store.subscription(tokens, name)},
                         captured_at=at)

    def _update(self, raw, at):
        # Past the daily cap the store refuses the row and the reader closes this socket.
        self.store.record("stream", raw, captured_at=at)

    def _trades(self, raw, count, duplicates, at):
        # Keep original response bytes, not a reconstructed execution.
        self.store.record("trades", raw, captured_at=at,
                          metadata={"duplicate_trades": duplicates} if duplicates else None)
        with self.counter_lock:
            self.trades += count

    def metrics(self):
        with self.counter_lock:
            return {"messages": self.messages, "received_bytes": self.bytes, "trades": self.trades,
                    "duplicate_trades": self.duplicate_trades, "errors": self.errors,
                    "connections": self.connected, "last_event_utc": self.last_event_utc,
                    "tokens": len(self.tokens)}
