"""Raw bounded frames, shared handshake cooldown and explicit stream uncertainty."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from types import SimpleNamespace

from weather.market.pilot_evidence_contract import strict_json
from weather.market.pilot_evidence_public import open_socket, retry_delay
from weather.market.pilot_evidence_store import CaptureStopped, MIB, source_clocks, stamp
from weather.market.pilot_evidence_transport import BoundedWebSocket, HandshakeError, IdlePoll, TransportLimit, header_cooldown
from weather.market.pilot_evidence_public import SOCKET

EVENT_COUNTERS = frozenset(("book", "price_change", "last_trade_price", "best_bid_ask",
                            "tick_size_change", "new_market", "market_resolved"))


class MarketStream(threading.Thread):
    def __init__(self, store, gate, tokens, *, coverage, connect=None, max_age=30, max_delay=30):
        super().__init__(name="pilot-public-market", daemon=False)
        self.store, self.gate, self.tokens, self.coverage = store, gate, tokens, coverage
        self.connect = connect
        self.max_age, self.max_delay = max_age, max_delay
        self.ending = threading.Event()
        self.pending, self.gap_open = set(), False
        self.ws = None
        self.connection_number = 0  # Local transport identity, never a venue sequence.
        self.decoder = BoundedWebSocket(None, max_size=MIB)

    def disconnected(self, reason):
        self.coverage.interval("stream_transport_gap", "stream", boundary=self.coverage.last_market or self.coverage.begin,
                               reason=reason, public_prints_backfilled=False)
        self.gap_open = True

    def frame(self, opcode, raw, received, *, fin=1, rsv1=0, rsv2=0, rsv3=0):
        if len(raw) > MIB:
            self.store.fail("socket_frame_cap", bytes=len(raw))
            raise CaptureStopped("socket_frame_cap")
        self.store.raw("ws_frame", raw, received=received, parse=False, opcode=opcode, fin=fin,
                       rsv1=rsv1, rsv2=rsv2, rsv3=rsv3, local_connection_number=self.connection_number)
        self.coverage.last_transport = received
        self.store.counts["ws_opcode_" + str(opcode)] += 1
        frame = SimpleNamespace(opcode=opcode, fin=fin, data=raw)
        message = self.decoder.message(frame)
        if message is None or message in (b"PONG", b"PING"):
            return
        try:
            value = strict_json(message, max_bytes=MIB)
        except (ValueError, UnicodeError):
            self.coverage.interval("stream_message_unvalidated", "stream", boundary=self.coverage.last_market or self.coverage.begin)
            return
        clocks = source_clocks(value)
        self.coverage.interval("stream_message_unvalidated", "stream", bad=False)
        self.store.write("ws_message_clocks", {"message_sha256": hashlib.sha256(message).hexdigest(),
                                               "source_timestamps": clocks,
                                               "local_connection_number": self.connection_number}, received=received)
        for row in value if isinstance(value, list) else [value]:
            if not isinstance(row, dict):
                continue
            kind, token = row.get("event_type"), str(row.get("asset_id"))
            if kind == "book" and token in self.coverage.tokens:
                self.coverage.book(row, token, received, source="stream")
                if self.coverage.tokens[token]["last_stream"] == received:
                    self.pending.discard(token)  # Structurally validated recovery; freshness is separate.
            elif kind == "price_change":
                self.coverage.changes(row, received)
            elif kind == "last_trade_price" and token in self.coverage.tokens:
                if row.get("market") == self.coverage.tokens[token]["condition_id"]:
                    self.coverage.stream_clock(row, received, [token])
            if isinstance(kind, str):
                self.store.counts["market_event_" + (kind if kind in EVENT_COUNTERS else "other")] += 1
        if self.gap_open and not self.pending:
            self.coverage.interval("stream_transport_gap", "stream", bad=False)
            self.store.write("stream_transport_recovered", {"basis": "all_full_scoped_book_frames",
                                "source_freshness_certified": False, "public_prints_backfilled": False})
            self.gap_open = False

    def send_control(self, payload, kind):
        self.store.write("stream_control", {"control": kind, "payload": payload})
        def send():
            self.store.attempt_started("ws_control")
            self.store.network_started("ws_control")
            self.ws.send(payload)
            self.store.counts["control_send_" + kind] += 1
        self.gate.start(send)

    def run(self):
        failures = 0
        while not self.ending.is_set() and not self.store.stop.is_set():
            try:
                tokens = self.tokens()
                if not tokens:
                    self.ending.wait(0.2)
                    continue
                self.disconnected("initial_or_reconnect")
                if self.connect is None:
                    self.ws = open_socket(gate=self.gate, store=self.store, max_size=MIB)
                else:
                    self.gate.wait()
                    self.ws = self.connect()
                self.connection_number += 1
                # The receiver must see the same partial-message length before
                # allocating a continuation payload, not just after that read.
                self.decoder = self.ws if isinstance(self.ws, BoundedWebSocket) else BoundedWebSocket(None, max_size=MIB)
                self.pending = set(tokens)
                self.store.write("stream_connected", {"token_count": len(tokens),
                                                       "local_connection_number": self.connection_number})
                self.send_control(json.dumps({"assets_ids": tokens, "type": "market", "custom_feature_enabled": True}), "subscribe")
                subscribed = set(tokens)
                connected_at = last_receive = last_ping = time.monotonic()
                baseline_due = connected_at + self.max_age
                window, frames, byte_count = connected_at, 0, 0
                while not self.ending.is_set():
                    self.store.check()
                    now = time.monotonic()
                    additions = set(self.tokens()) - subscribed
                    if additions:
                        self.send_control(json.dumps({"assets_ids": sorted(additions), "operation": "subscribe"}), "subscribe_additive")
                        subscribed.update(additions)
                        self.pending.update(additions)
                        baseline_due = now + self.max_age
                        self.disconnected("new_tokens_awaiting_full_book")
                    if now - last_ping >= 9:
                        self.send_control("PING", "ping")
                        last_ping = time.monotonic()
                    if now - last_receive > self.max_age or self.pending and now > baseline_due:
                        raise TimeoutError("stream transport/baseline deadline")
                    try:
                        with self.store.operation("ws_frame", 6):
                            frame = self.ws.recv_frame()
                    except IdlePoll:
                        continue
                    received = stamp()
                    raw = frame.data.encode() if isinstance(frame.data, str) else frame.data
                    now = time.monotonic()
                    if now - window >= 1:
                        window, frames, byte_count = now, 0, 0
                    frames, byte_count = frames + 1, byte_count + len(raw)
                    if frames > 500 or byte_count > 8 * MIB:
                        self.store.fail("inbound_rate_cap", frames=frames, bytes=byte_count)
                        raise CaptureStopped("inbound_rate_cap")
                    self.frame(frame.opcode, raw, received, fin=frame.fin,
                               rsv1=frame.rsv1, rsv2=frame.rsv2, rsv3=frame.rsv3)
                    last_receive = now
                    if not self.pending and now - connected_at >= 30 and self.coverage.snapshot()["coverage_ready"]:
                        failures = 0  # Never reset just for a PONG/control frame.
                    if frame.opcode == 9:
                        self.ws.pong(raw)  # Mandatory protocol reply; separately counted, no HTTP request.
                        self.store.counts["protocol_pong_replies"] += 1
                    if frame.opcode == 8:
                        raise ConnectionError("peer close")
            except CaptureStopped:
                break
            except TransportLimit as exc:
                self.store.fail("socket_size_cap", error=str(exc))
                break
            except Exception as exc:
                if self.ending.is_set() or self.store.stop.is_set():
                    break
                self.disconnected(type(exc).__name__)
                failures += 1
                headers, status = {}, None
                if isinstance(exc, HandshakeError):
                    headers, status = exc.headers, exc.status
                    self.store.raw("ws_handshake_error", exc.body, parse=False, status=status,
                                   response_headers=headers, truncated=exc.truncated)
                    try:
                        header_cooldown(status, headers, self.gate, self.store, "websocket", endpoint=SOCKET, body_unread=False)
                    except CaptureStopped:
                        break
                    if exc.truncated:
                        self.store.fail("handshake_body_cap")
                        break
                delay = retry_delay(headers.get("Retry-After"), failures)
                self.gate.defer(delay)  # Shared cooldown also suspends REST.
                self.store.write("stream_reconnect", {"error": type(exc).__name__, "status": status,
                                                       "backoff_seconds": delay,
                                                       "retry_after": headers.get("Retry-After")})
                self.ending.wait(min(delay, 0.2))  # Gate owns the full wait and stop checks.
            finally:
                if self.ws is not None:
                    self.ws.close(timeout=1)
                    self.ws = None

    def shutdown(self):
        self.ending.set()
        current = self.ws
        if current is not None:
            try:
                current.close(timeout=1)
            except OSError as exc:
                self.store.fail("stream_socket_close_failure", error=type(exc).__name__)
        self.join(timeout=2)
        return not self.is_alive()
