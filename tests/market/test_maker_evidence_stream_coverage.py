"""88a public stream coverage: the socket reader survives journal stalls and venue closes.

Every test journals through the production ``EvidenceStore`` in a temporary
root.  The live tests run a real websocket server on localhost and connect the
production ``BoundedWebSocket`` to it, so opcodes, PING/PONG and close frames
cross a real socket.
"""
import base64
import contextlib
import hashlib
import json
import socket as socketlib
import struct
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from websocket import WebSocketException

from weather.market import maker_evidence_socket as socket_module
from weather.market import maker_evidence_stream as module
from weather.market.maker_evidence_store import EvidenceStore, decode_body, encoded

CID = "0x" + "a" * 64
TOKEN = "123"
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def trade(price):
    return encoded({"event_type": "last_trade_price", "asset_id": TOKEN, "market": CID, "price": price,
                    "size": "5", "side": "BUY", "timestamp": "1790175733000"}).decode()


def journal(store):
    rows = []
    for path in store.root.glob("*/*/*.jsonl"):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    rows = sorted((row for row in rows if "kind" in row), key=lambda row: (row["captured_at_utc"], row["sequence"]))
    for row in rows:
        row["body"] = json.loads(decode_body(row)) if "body_utf8" in row or "body_base64" in row else None
    return rows


def sequence_order(store):
    return [row for row in sorted(journal(store), key=lambda row: row["sequence"])]


class LocalVenue:
    """A minimal RFC 6455 server: answers PING with PONG and runs a per-connection script."""

    def __init__(self, script, *, answer_ping=True):
        self.script, self.answer_ping = script, answer_ping
        self.received, self.connections = [], 0
        self.listener = socketlib.create_server(("127.0.0.1", 0))
        self.url = "ws://127.0.0.1:%d/ws/market" % self.listener.getsockname()[1]
        self.closed = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.closed.is_set():
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(conn, self.connections), daemon=True).start()

    def _serve(self, conn, number):
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(4096)
        key = [line.split(b":", 1)[1].strip() for line in request.split(b"\r\n")
               if line.lower().startswith(b"sec-websocket-key")][0]
        accept = base64.b64encode(hashlib.sha1(key + GUID).digest())
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        lock = threading.Lock()

        def send(opcode, payload=b""):
            payload = payload.encode() if isinstance(payload, str) else payload
            header = bytes([0x80 | opcode])
            header += bytes([len(payload)]) if len(payload) < 126 else b"\x7e" + struct.pack("!H", len(payload))
            with lock, contextlib.suppress(OSError):
                conn.sendall(header + payload)

        def read_frames():
            with contextlib.suppress(OSError, IndexError):
                while True:
                    head = self._exact(conn, 2)
                    length = head[1] & 0x7F
                    if length == 126:
                        length = struct.unpack("!H", self._exact(conn, 2))[0]
                    mask = self._exact(conn, 4)
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._exact(conn, length)))
                    if head[0] & 0x0F == 0x8:
                        return
                    self.received.append((time.monotonic(), number, data.decode()))
                    if data == b"PING" and self.answer_ping:
                        send(0x1, "PONG")

        threading.Thread(target=read_frames, daemon=True).start()
        self.script(send, number)

    @staticmethod
    def _exact(conn, size):
        data = b""
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                raise OSError("client closed")
            data += chunk
        return data

    def pings(self):
        return [at for at, _, text in self.received if text == "PING"]

    def close(self):
        self.closed.set()
        self.listener.close()


def close_payload(code, reason=""):
    return (struct.pack("!H", code) + reason.encode()) if code is not None else b""


@pytest.fixture
def live(monkeypatch, tmp_path):
    venues = []

    def start(script, **kwargs):
        venue = LocalVenue(script, **kwargs)
        venues.append(venue)
        monkeypatch.setattr(module, "connect", lambda: socket_module.connect(venue.url))
        return venue

    yield start
    for venue in venues:
        venue.close()


def fast_stream(store, **overrides):
    stream = module.PublicStream(store, trades_only=True)
    stream.ping_seconds, stream.silence_seconds = 0.2, 0.6
    stream.reconnect_base_seconds, stream.random = 0.05, lambda: 1.0
    for name, value in overrides.items():
        setattr(stream, name, value)
    return stream


def run_until(stream, done, timeout=10):
    thread = threading.Thread(target=stream._run, args=((TOKEN,),), daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        time.sleep(0.02)
    stream.stop_event.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_store_lock_stall_longer_than_silence_deadline_keeps_the_session(tmp_path, live):
    store = EvidenceStore(tmp_path)
    stall = {}

    def script(send, number):
        send(0x1, trade("0.50"))
        time.sleep(0.4)
        send(0x1, trade("0.51"))  # Arrives while the journal is stalled.
        time.sleep(0.6)
        send(0x1, trade("0.52"))

    venue = live(script)
    stream = fast_stream(store)

    def hold_store_lock():
        time.sleep(0.2)
        with store.lock:
            stall["start"] = time.monotonic()
            stall["start_utc"] = datetime.now(timezone.utc)
            time.sleep(1.5)  # 2.5x the silence deadline.
            stall["end"] = time.monotonic()
            stall["end_utc"] = datetime.now(timezone.utc)
        time.sleep(0.5)
        stall["done"] = True

    holder = threading.Thread(target=hold_store_lock)
    holder.start()
    run_until(stream, lambda: stall.get("done"))
    holder.join()

    rows = journal(store)
    assert not [row for row in rows if row["kind"] == "stream_gap"]
    assert [row["body"]["state"] for row in rows if row["kind"] == "stream_lifecycle"] == ["connected", "disconnected"]
    assert venue.connections == 1
    assert len([at for at in venue.pings() if stall["start"] < at < stall["end"]]) >= 3
    trades = [row for row in rows if row["kind"] == "trades"]
    assert [row["body"]["price"] for row in trades] == ["0.50", "0.51", "0.52"]
    # Receipt stamps are taken by the reader, not after the stalled write.
    second = datetime.fromisoformat(trades[1]["captured_at_utc"])
    assert stall["start_utc"] < second < stall["end_utc"] - timedelta(seconds=0.5)
    assert stream.trades == 3 and stream.errors == 0


@pytest.mark.parametrize("code, reason, expected", [
    (1011, "overloaded", "code=1011 reason='overloaded'"),
    (None, "", "code=None reason=''"),
])
def test_venue_close_code_reaches_the_gap_row_after_received_frames(tmp_path, live, code, reason, expected):
    store = EvidenceStore(tmp_path)
    stalled = threading.Event()

    def script(send, number):
        if number > 1:
            return
        send(0x1, trade("0.50"))
        send(0x1, trade("0.51"))
        stalled.wait(5)
        send(0x8, close_payload(code, reason))

    live(script)
    stream = fast_stream(store, reconnect_base_seconds=5.0)
    release = {}

    def stall_then_close():
        with store.lock:
            stalled.set()
            time.sleep(0.8)  # The close arrives while both trades are still queued.
            release["at"] = datetime.now(timezone.utc)

    holder = threading.Thread(target=stall_then_close)
    holder.start()
    run_until(stream, lambda: stream.errors)
    holder.join()

    ordered = sequence_order(store)
    kinds = [(row["kind"], (row["body"] or {}).get("state")) for row in ordered if row["kind"] != "subscription"]
    assert kinds == [("stream_lifecycle", "connected"), ("trades", None), ("trades", None),
                     ("stream_lifecycle", "disconnected"), ("stream_gap", None)]
    gap = ordered[-1]
    assert gap["body"]["error_type"] == "VenueCloseError" and expected in gap["body"]["error"]
    # The gap is stamped when reading stopped, before the queued trades could be written.
    stopped = datetime.fromisoformat(gap["captured_at_utc"])
    assert stopped < release["at"]
    assert ordered[-2]["captured_at_utc"] == gap["captured_at_utc"]


def test_empty_data_frames_are_liveness_not_a_close(tmp_path, live):
    store = EvidenceStore(tmp_path)

    def script(send, number):
        for _ in range(15):
            send(0x1, b"")
            time.sleep(0.1)

    venue = live(script, answer_ping=False)
    stream = fast_stream(store, ping_seconds=5.0, silence_seconds=0.5)
    started = time.monotonic()
    run_until(stream, lambda: time.monotonic() - started > 1.2)
    assert stream.errors == 0 and venue.connections == 1
    assert not [row for row in journal(store) if row["kind"] == "stream_gap"]


def test_real_silence_still_disconnects(tmp_path, live):
    store = EvidenceStore(tmp_path)
    live(lambda send, number: time.sleep(3), answer_ping=False)
    stream = fast_stream(store, silence_seconds=0.3)
    run_until(stream, lambda: stream.errors)
    gaps = [row for row in journal(store) if row["kind"] == "stream_gap"]
    assert gaps[0]["body"]["error_type"] == "TimeoutError"
    assert gaps[0]["body"]["error"] == "public stream inbound silence"


def test_journal_fault_ends_the_session_with_a_gap(tmp_path, live, monkeypatch):
    store = EvidenceStore(tmp_path)
    live(lambda send, number: (send(0x1, trade("0.50")), time.sleep(3)))
    original = store.record

    def failing(kind, raw, **kwargs):
        if kind == "trades":
            raise OSError("journal disk fault")
        return original(kind, raw, **kwargs)

    monkeypatch.setattr(store, "record", failing)
    stream = fast_stream(store, reconnect_base_seconds=5.0)
    run_until(stream, lambda: stream.errors)
    gaps = [row for row in journal(store) if row["kind"] == "stream_gap"]
    assert gaps[0]["body"]["error_type"] == "OSError" and stream.trades == 0


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Waits:
    def __init__(self, limit):
        self.seconds, self.limit = [], limit

    def is_set(self):
        return len(self.seconds) >= self.limit

    def set(self):
        pass

    def wait(self, seconds):
        self.seconds.append(round(seconds, 6))
        return self.is_set()


def policy_stream(store, sessions, *, random_value=1.0):
    """Each entry is a session length in fake seconds, or None for a refused connect."""
    clock = FakeClock()
    stream = module.PublicStream(store, trades_only=True)
    stream.monotonic, stream.random = clock, lambda: random_value
    plan = list(sessions)

    class Socket:
        def __init__(self, length):
            self.length = length

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, value):
            pass

        def recv(self, timeout):
            clock.now += self.length
            raise ConnectionError("public socket closed")

    def connect():
        length = plan.pop(0) if plan else None
        if length is None:
            raise WebSocketException("handshake refused")
        return Socket(length)

    return stream, connect


def run_policy(monkeypatch, tmp_path, sessions, **kwargs):
    store = EvidenceStore(tmp_path)
    stream, connect = policy_stream(store, sessions, **kwargs)
    monkeypatch.setattr(module, "connect", connect)
    stream.stop_event = Waits(len(sessions))
    stream._run((TOKEN,))
    return stream.stop_event.seconds


def test_backoff_escalates_on_repeated_failures(monkeypatch, tmp_path):
    assert run_policy(monkeypatch, tmp_path, [None] * 7) == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_backoff_resets_after_a_long_connected_session(monkeypatch, tmp_path):
    assert run_policy(monkeypatch, tmp_path, [None, None, None, 120.0, None]) == [2.0, 4.0, 8.0, 2.0, 4.0]


def test_backoff_is_not_reset_by_a_short_session(monkeypatch, tmp_path):
    assert run_policy(monkeypatch, tmp_path, [None, None, None, 10.0, None]) == [2.0, 4.0, 8.0, 16.0, 30.0]


def test_reconnects_are_jittered_into_half_to_full_delay(monkeypatch, tmp_path):
    assert run_policy(monkeypatch, tmp_path, [None] * 3, random_value=0.0) == [1.0, 2.0, 4.0]
    assert module.reconnect_delay(8.0, lambda: 0.5) == 6.0


def test_writer_backlog_is_bounded_by_bytes_and_keeps_order():
    gate, written = threading.Event(), []
    writer = module._JournalWriter(max_pending=100, max_bytes=10)
    writer.put(lambda: (gate.wait(5), written.append("first")), size=8)
    queued = threading.Event()

    def second():
        writer.put(lambda: written.append("second"), size=8)
        queued.set()

    threading.Thread(target=second, daemon=True).start()
    assert not queued.wait(0.3)  # 16 bytes would exceed the 10-byte bound.
    gate.set()
    assert queued.wait(5)
    writer.put(lambda: written.append("large"), size=50)  # Alone, an oversized frame still queues.
    writer.close()
    assert written == ["first", "second", "large"]
