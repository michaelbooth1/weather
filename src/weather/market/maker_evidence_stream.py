"""Bounded public update stream plus independent uncapped public trade channel.

Each socket thread only reads, sends ``PING`` and stamps receive time.  A
per-session writer thread journals its rows in arrival order, so an fsync or a
held store lock can no longer stop the socket being drained and pinged.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import time

from websocket import WebSocketException

from weather.market.maker_evidence_socket import EMPTY_DATA_FRAME, connect
from weather.market.maker_evidence_store import RawFootprintLimit, encoded

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


def reconnect_delay(delay, random_fn=random.random):
    """Jitter one backoff step into [delay/2, delay] so sockets do not reconnect in lockstep."""
    return delay * (0.5 + 0.5 * random_fn())


class _JournalWriter:
    """Run one session's journal writes in arrival order, off the socket thread."""

    _STOP = object()

    def __init__(self, max_pending):
        self.error = None
        self._queue = queue.Queue(maxsize=max(1, int(max_pending)))
        self._thread = threading.Thread(target=self._run, name="maker-evidence-writer", daemon=True)
        self._thread.start()

    def raise_error(self):
        if self.error is not None:
            raise self.error

    def put(self, write, *args):
        while True:
            self.raise_error()
            try:
                self._queue.put((write, args), timeout=0.5)
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

    def close(self):
        """Write every queued row, then stop; a received frame is never dropped."""
        if self._thread.is_alive():
            self._queue.put(self._STOP)
            self._thread.join()


class PublicStream:
    ping_seconds, silence_seconds = PING_SECONDS, SILENCE_SECONDS
    reconnect_base_seconds, reconnect_max_seconds = RECONNECT_BASE_SECONDS, RECONNECT_MAX_SECONDS
    stable_session_seconds, max_pending_frames = STABLE_SESSION_SECONDS, MAX_PENDING_FRAMES

    def __init__(self, store, *, trades_only=False):
        self.store, self.trades_only = store, trades_only
        self.stop_event = threading.Event()
        self.threads, self.tokens = [], ()
        self.messages, self.bytes, self.trades, self.errors = 0, 0, 0, 0
        self.connected = 0
        self.last_event_utc = None
        self.counter_lock = threading.Lock()
        self.window_end = None
        self.monotonic, self.random = time.monotonic, random.random

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
        self.stop()
        self.tokens = wanted
        self.stop_event = threading.Event()
        for start in range(0, len(wanted), MAX_TOKENS):
            thread = threading.Thread(target=self._run, args=(wanted[start:start + MAX_TOKENS],), daemon=True)
            self.threads.append(thread)
            thread.start()

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=8)
            if thread.is_alive():
                raise RuntimeError("public stream did not terminate within its bound")
        self.threads = []
        self.tokens = ()

    def _run(self, tokens):
        name = "trades" if self.trades_only else "updates"
        delay = self.reconnect_base_seconds
        while not self.stop_event.is_set() and self._window_open():
            if not self.trades_only and self.store.stream_capped:
                return
            session, failed = {}, False
            try:
                self._session(tokens, name, session)
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
            if self.stop_event.wait(reconnect_delay(delay, self.random)):
                break
            delay = min(self.reconnect_max_seconds, delay * 2) if failed else self.reconnect_base_seconds

    def _session(self, tokens, name, session):
        with connect() as socket:
            session["connected_monotonic"] = self.monotonic()
            writer = _JournalWriter(self.max_pending_frames)
            with self.counter_lock:
                self.connected += 1
            try:
                writer.put(self._lifecycle, "connected", tokens, name, self.store.clock())
                socket.send(encoded({"assets_ids": tokens, "type": "market"}).decode())
                self._read(socket, tokens, writer)
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

    def _read(self, socket, tokens, writer):
        next_ping = last_inbound = self.monotonic()
        while not self.stop_event.is_set() and self._window_open():
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
            if message is EMPTY_DATA_FRAME or message in ("PONG", b"PONG"):
                continue
            raw = message.encode() if isinstance(message, str) else message
            with self.counter_lock:
                self.messages += 1
                self.bytes += len(raw)
                self.last_event_utc = received_at.isoformat()
            if not self.trades_only:
                writer.put(self._update, raw, received_at)
                continue
            payload = json.loads(raw)
            rows = payload if isinstance(payload, list) else [payload]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("public trade channel received a non-object event")
            trades = [row for row in rows if row.get("event_type") == "last_trade_price"
                      and str(row.get("asset_id")) in tokens]
            if trades:
                writer.put(self._trades, raw, len(trades), received_at)

    def _lifecycle(self, state, tokens, name, at):
        self.store.event("stream_lifecycle", {"state": state, "channel": name,
                                             "subscription": self.store.subscription(tokens, name)},
                         captured_at=at)

    def _update(self, raw, at):
        # Past the daily cap the store refuses the row and the reader closes this socket.
        self.store.record("stream", raw, captured_at=at)

    def _trades(self, raw, count, at):
        # Keep original response bytes, not a reconstructed execution.
        self.store.record("trades", raw, captured_at=at)
        with self.counter_lock:
            self.trades += count

    def metrics(self):
        with self.counter_lock:
            return {"messages": self.messages, "received_bytes": self.bytes, "trades": self.trades,
                    "errors": self.errors, "connections": self.connected,
                    "last_event_utc": self.last_event_utc, "tokens": len(self.tokens)}
