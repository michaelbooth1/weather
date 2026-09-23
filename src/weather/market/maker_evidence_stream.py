"""Bounded public update stream plus independent uncapped public trade channel."""
from __future__ import annotations

import json
import threading
import time

from websocket import WebSocketException

from weather.market.maker_evidence_socket import connect
from weather.market.maker_evidence_store import RawFootprintLimit, encoded

MAX_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_TOKENS = 100


class PublicStream:
    def __init__(self, store, *, trades_only=False):
        self.store, self.trades_only = store, trades_only
        self.stop_event = threading.Event()
        self.threads, self.tokens = [], ()
        self.messages, self.bytes, self.trades, self.errors = 0, 0, 0, 0
        self.connected = 0
        self.last_event_utc = None
        self.counter_lock = threading.Lock()
        self.window_end = None

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
        while not self.stop_event.is_set() and self._window_open():
            if not self.trades_only and self.store.stream_capped:
                return
            try:
                with connect() as socket:
                    with self.counter_lock:
                        self.connected += 1
                    self.store.event("stream_lifecycle", {"state": "connected", "channel": name,
                                                         "subscription": self.store.subscription(tokens, name)})
                    try:
                        socket.send(encoded({"assets_ids": tokens, "type": "market"}).decode())
                        next_ping, last_inbound = time.monotonic(), time.monotonic()
                        while not self.stop_event.is_set() and self._window_open():
                            if not self.trades_only and self.store.stream_capped:
                                break
                            now = time.monotonic()
                            if now >= next_ping:
                                socket.send("PING")
                                next_ping = now + 10
                            if now - last_inbound > 30:
                                raise TimeoutError("public stream inbound silence")
                            try:
                                message = socket.recv(timeout=1)
                            except TimeoutError:
                                continue
                            last_inbound = time.monotonic()
                            if not self._window_open():
                                break
                            if message in ("PONG", b"PONG"):
                                continue
                            raw = message.encode() if isinstance(message, str) else message
                            with self.counter_lock:
                                self.messages += 1
                                self.bytes += len(raw)
                                self.last_event_utc = self.store.clock().isoformat()
                            if self.trades_only:
                                payload = json.loads(raw)
                                rows = payload if isinstance(payload, list) else [payload]
                                if any(not isinstance(row, dict) for row in rows):
                                    raise ValueError("public trade channel received a non-object event")
                                trades = [row for row in rows if row.get("event_type") == "last_trade_price"
                                          and str(row.get("asset_id")) in tokens]
                                if trades:
                                    # Keep original response bytes, not a reconstructed execution.
                                    self.store.record("trades", raw)
                                    with self.counter_lock:
                                        self.trades += len(trades)
                            elif not self.store.record("stream", raw):
                                break  # Cap closes this socket; independent trade capture survives.
                    finally:
                        with self.counter_lock:
                            self.connected -= 1
                        self.store.event("stream_lifecycle", {"state": "disconnected", "channel": name,
                                                             "subscription": self.store.subscription(tokens, name)})
            except RawFootprintLimit:
                return  # Store latched the limit; the main worker writes terminal status.
            except (OSError, ValueError, WebSocketException, TimeoutError) as exc:
                with self.counter_lock:
                    self.errors += 1
                self.store.event("stream_gap", {"channel": name, "error_type": type(exc).__name__,
                                               "error": str(exc)[:300],
                                               "subscription": self.store.subscription(tokens, name),
                                               "backfill_claimed": False})
            if self.stop_event.wait(2):
                break

    def metrics(self):
        with self.counter_lock:
            return {"messages": self.messages, "received_bytes": self.bytes, "trades": self.trades,
                    "errors": self.errors, "connections": self.connected,
                    "last_event_utc": self.last_event_utc, "tokens": len(self.tokens)}
