"""Trade-stream coverage: the socket reader survives tape stalls and venue closes.

Every test drives the production ``ExecutionTapeCoordinator`` and its real
JSONL writers in a temporary root, so gap (lifecycle) rows and trade rows are
read back exactly as production writes them.
"""

import json
import struct
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import websocket

from weather.market import execution_tape_capture as capture
from weather.market.execution_tape_capture import (
    VenueCloseError,
    connection_worker,
    reconnect_delay_seconds,
    run_connection_once,
)
from weather.market.execution_tape_store import ExecutionTapeCoordinator, MarketDaySeed


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "docs" / "roadmap" / "execution-tape-pilot-2026-08-10-trades.jsonl"
STARTED = datetime(2026, 8, 10, 22, 15, tzinfo=timezone.utc)


def fixture_rows():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def one_seed(row):
    return MarketDaySeed(
        market_id="toronto",
        target_date=date(2026, 8, 10),
        event_slug="highest-temperature-in-toronto-on-august-10-2026",
        asset_ids=(row["asset_id"],),
        condition_ids=(row["market"],),
        source="committed-test-fixture",
    )


def tape_rows(root, seed, prefix):
    folder = Path(root) / seed.event_slug / "execution_tape"
    rows = []
    for path in sorted(folder.glob(f"{prefix}-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    return rows


class OpcodeWebsocket:
    """Speaks websocket-client's ``recv_data`` opcode contract."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    def settimeout(self, _value):
        pass

    def send(self, value):
        self.sent.append(value)

    def recv_data(self):
        if not self.frames:
            raise websocket.WebSocketTimeoutException("timed out")
        item = self.frames.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


def text(value):
    return websocket.ABNF.OPCODE_TEXT, value.encode("utf-8")


def close_frame(code, reason):
    return websocket.ABNF.OPCODE_CLOSE, struct.pack("!H", code) + reason.encode("utf-8")


class StreamCoverageTests(unittest.TestCase):
    def test_tape_lock_stall_longer_than_silence_deadline_keeps_the_session(self):
        rows = fixture_rows()
        row = rows[0]
        seed = one_seed(row)
        trades = [dict(item, asset_id=row["asset_id"], market=row["market"]) for item in rows[:3]]
        stall_seconds = 1.5
        silence_seconds = 0.6
        ping_times = []
        stall = {"start": None, "end": None}

        class LiveSocket(OpcodeWebsocket):
            """Server stays alive: a PONG every 50 ms and a trade now and then."""

            def __init__(self):
                super().__init__([])
                self.started = time.monotonic()
                self.queued = [json.dumps(trades[0])]
                self.later = [(0.4, json.dumps(trades[1])), (1.0, json.dumps(trades[2]))]

            def send(self, value):
                super().send(value)
                if value == "PING":
                    ping_times.append(time.monotonic())

            def recv_data(self):
                elapsed = time.monotonic() - self.started
                while self.later and elapsed >= self.later[0][0]:
                    self.queued.append(self.later.pop(0)[1])
                if self.queued:
                    return text(self.queued.pop(0))
                time.sleep(0.05)
                return text("PONG")

        fake = LiveSocket()
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)
            try:
                def hold_tape_lock():
                    time.sleep(0.2)
                    with coordinator._mutex:
                        stall["start"] = time.monotonic()
                        time.sleep(stall_seconds)
                        stall["end"] = time.monotonic()
                    time.sleep(0.5)
                    stop.set()

                holder = threading.Thread(target=hold_tape_lock)
                holder.start()
                result = run_connection_once(
                    coordinator,
                    (seed,),
                    stop_event=stop,
                    websocket_factory=lambda *_args, **_kwargs: fake,
                    heartbeat_seconds=0.2,
                    inbound_silence_timeout_seconds=silence_seconds,
                    connect_timeout_seconds=5.0,
                )
                holder.join()
                status = coordinator.stores[seed.key].status_payload(now=datetime.now(timezone.utc))
            finally:
                coordinator.close()
            gaps = tape_rows(tmp, seed, "gaps")
            written = tape_rows(tmp, seed, "trades")

        self.assertEqual(result["reason"], "stop_requested")
        self.assertGreater(stall["end"] - stall["start"], silence_seconds)
        # The reader kept the socket alive while the tape was locked.
        self.assertTrue(any(stall["start"] < at < stall["end"] for at in ping_times))
        opened = [gap for gap in gaps if gap["gap_state"] == "OPEN"]
        self.assertEqual([gap["reason"] for gap in opened], ["startup_connecting", "stop_requested"])
        self.assertEqual(status["connection_count"], 1)
        self.assertEqual(status["trades_written"], 3)
        self.assertEqual([item["timestamp"] for item in written], [item["timestamp"] for item in trades])
        # Receipt times are the reader's stamps, not the delayed write time.
        receipts = [datetime.fromisoformat(item["received_at_utc"]) for item in written]
        self.assertEqual(receipts, sorted(receipts))
        # The third trade arrived 0.6 s after the second, inside the stall; a
        # blocked reader would have stamped it only after the lock released.
        self.assertLess((receipts[2] - receipts[1]).total_seconds(), 1.0)

    def test_venue_close_frame_records_code_and_reason_in_the_gap_row(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        fake = OpcodeWebsocket([text(json.dumps(row)), close_frame(1011, "server overloaded")])
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)
            try:
                with self.assertRaises(VenueCloseError) as raised:
                    run_connection_once(
                        coordinator,
                        (seed,),
                        stop_event=threading.Event(),
                        websocket_factory=lambda *_args, **_kwargs: fake,
                        now_fn=lambda: STARTED,
                        monotonic_fn=lambda: 0.0,
                    )
            finally:
                coordinator.close()
            gaps = tape_rows(tmp, seed, "gaps")
            written = tape_rows(tmp, seed, "trades")

        self.assertEqual(raised.exception.code, 1011)
        self.assertEqual(raised.exception.reason, "server overloaded")
        self.assertEqual(
            gaps[-1]["reason"],
            "VenueCloseError: venue closed the websocket: code=1011 reason='server overloaded'",
        )
        self.assertTrue(gaps[-1]["was_ever_connected"])
        self.assertEqual(len(written), 1)
        self.assertTrue(fake.closed)

    def test_close_frame_without_status_code_is_still_a_venue_close(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        fake = OpcodeWebsocket([text(json.dumps(row)), (websocket.ABNF.OPCODE_CLOSE, b"")])
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)
            try:
                with self.assertRaisesRegex(VenueCloseError, "code=None"):
                    run_connection_once(
                        coordinator,
                        (seed,),
                        stop_event=threading.Event(),
                        websocket_factory=lambda *_args, **_kwargs: fake,
                        now_fn=lambda: STARTED,
                        monotonic_fn=lambda: 0.0,
                    )
            finally:
                coordinator.close()

    def test_empty_data_frame_is_liveness_not_a_disconnect(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        second = dict(row, timestamp=str(int(row["timestamp"]) + 1000))
        fake = OpcodeWebsocket([
            text(json.dumps(row)),
            text(""),
            (websocket.ABNF.OPCODE_BINARY, b""),
            text(json.dumps(second)),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)
            try:
                result = run_connection_once(
                    coordinator,
                    (seed,),
                    stop_event=threading.Event(),
                    websocket_factory=lambda *_args, **_kwargs: fake,
                    now_fn=lambda: STARTED,
                    monotonic_fn=lambda: 0.0,
                    max_messages=2,
                )
                status = coordinator.stores[seed.key].status_payload(now=STARTED)
            finally:
                coordinator.close()

        self.assertEqual(result["reason"], "message_limit_reached")
        self.assertEqual(status["trades_written"], 2)
        self.assertEqual(status["messages_seen"], 2)
        self.assertEqual(status["disconnect_count"], 1)  # the orderly end, not the empty frames
        self.assertEqual(status["parse_rejections"], 0)

    def test_frames_received_before_a_drop_are_written_before_the_gap_row(self):
        rows = fixture_rows()
        seed = one_seed(rows[0])
        trades = [dict(item, asset_id=rows[0]["asset_id"], market=rows[0]["market"]) for item in rows[:4]]
        lost = websocket.WebSocketConnectionClosedException("Connection to remote host was lost.")
        fake = OpcodeWebsocket([text(json.dumps(item)) for item in trades] + [lost])
        clock = {"now": STARTED}

        def now_fn():
            clock["now"] += timedelta(milliseconds=10)
            return clock["now"]

        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)
            original_ingest = coordinator.ingest_frame

            def slow_ingest(*args, **kwargs):
                time.sleep(0.05)  # the writer lags the reader
                return original_ingest(*args, **kwargs)

            coordinator.ingest_frame = slow_ingest
            try:
                with self.assertRaises(websocket.WebSocketConnectionClosedException):
                    run_connection_once(
                        coordinator,
                        (seed,),
                        stop_event=threading.Event(),
                        websocket_factory=lambda *_args, **_kwargs: fake,
                        now_fn=now_fn,
                        monotonic_fn=lambda: 0.0,
                    )
            finally:
                coordinator.close()
            gaps = tape_rows(tmp, seed, "gaps")
            written = tape_rows(tmp, seed, "trades")

        self.assertEqual(len(written), 4)
        drop = gaps[-1]
        self.assertEqual(drop["gap_state"], "OPEN")
        self.assertEqual(
            drop["reason"],
            "WebSocketConnectionClosedException: Connection to remote host was lost.",
        )
        last_receipt = datetime.fromisoformat(written[-1]["received_at_utc"])
        self.assertLess(last_receipt, datetime.fromisoformat(drop["disconnected_at_utc"]))

    def test_tape_writer_failure_ends_the_session_and_is_raised(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        fake = OpcodeWebsocket([text(json.dumps(row))] * 50)
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)

            def failing_ingest(*_args, **_kwargs):
                raise OSError("simulated persistent fsync fault")

            coordinator.ingest_frame = failing_ingest
            try:
                with self.assertRaisesRegex(OSError, "persistent fsync fault"):
                    run_connection_once(
                        coordinator,
                        (seed,),
                        stop_event=threading.Event(),
                        websocket_factory=lambda *_args, **_kwargs: fake,
                        now_fn=lambda: STARTED,
                        monotonic_fn=lambda: 0.0,
                    )
            finally:
                coordinator.close()
            gaps = tape_rows(tmp, seed, "gaps")

        self.assertEqual(gaps[-1]["reason"], "OSError: simulated persistent fsync fault")
        self.assertTrue(fake.closed)

    def test_true_server_silence_still_disconnects(self):
        row = fixture_rows()[0]
        seed = one_seed(row)
        fake = OpcodeWebsocket([text(json.dumps(row))])
        monotonic = {"value": 0.0}

        def monotonic_fn():
            monotonic["value"] += 0.5
            return monotonic["value"]

        with tempfile.TemporaryDirectory() as tmp:
            coordinator = ExecutionTapeCoordinator((seed,), snapshots_root=tmp, now=STARTED)
            try:
                with self.assertRaisesRegex(TimeoutError, "silence deadline"):
                    run_connection_once(
                        coordinator,
                        (seed,),
                        stop_event=threading.Event(),
                        websocket_factory=lambda *_args, **_kwargs: fake,
                        heartbeat_seconds=1.0,
                        inbound_silence_timeout_seconds=3.0,
                        connect_timeout_seconds=10.0,
                        now_fn=lambda: STARTED,
                        monotonic_fn=monotonic_fn,
                    )
            finally:
                coordinator.close()
            gaps = tape_rows(tmp, seed, "gaps")

        self.assertIn("silence deadline", gaps[-1]["reason"])


class ReconnectPolicyTests(unittest.TestCase):
    def run_worker(self, outcomes, *, monotonic_now=1000.0, random_value=1.0):
        """Run the worker against scripted session outcomes; return the waits."""

        waits = []
        calls = {"count": 0}

        class RecordingStop(threading.Event):
            def wait(self, timeout=None):
                waits.append(timeout)
                return self.is_set()

        stop = RecordingStop()

        def scripted_session(*_args, session_outcome, **_kwargs):
            index = calls["count"]
            calls["count"] += 1
            if index >= len(outcomes):
                stop.set()
                raise ConnectionError("end of script")
            confirmed_at = outcomes[index]
            if confirmed_at is not None:
                session_outcome["routes_confirmed_monotonic"] = confirmed_at
            raise ConnectionError(f"scripted drop {index}")

        class NullCoordinator:
            def heartbeat(self, *_args, **_kwargs):
                pass

        original = capture.run_connection_once
        capture.run_connection_once = scripted_session
        try:
            connection_worker(
                NullCoordinator(),
                (),
                stop_event=stop,
                reconnect_base_seconds=1.0,
                reconnect_max_seconds=30.0,
                stable_session_seconds=60.0,
                monotonic_fn=lambda: monotonic_now,
                random_fn=lambda: random_value,
            )
        finally:
            capture.run_connection_once = original
        return waits

    def test_unconfirmed_failures_back_off_exponentially_to_the_cap(self):
        waits = self.run_worker([None] * 7)
        # One-second wait steps: 1 + 2 + 4 + 8 + 16 + 30 + 30.
        self.assertEqual(waits, [1.0] * (1 + 2 + 4 + 8 + 16 + 30 + 30))

    def test_a_long_proven_session_resets_the_backoff(self):
        # Four quick failures escalate to 16 s; a session proven 120 s before it
        # dropped then reconnects after the base delay again.
        waits = self.run_worker([None, None, None, None, 880.0])
        self.assertEqual(sum(waits[:15]), 15.0)  # 1 + 2 + 4 + 8
        self.assertEqual(waits[15:], [1.0])

    def test_a_session_that_drops_soon_after_proof_keeps_backing_off(self):
        waits = self.run_worker([None, None, 990.0])
        self.assertEqual(sum(waits), 1.0 + 2.0 + 4.0)

    def test_jitter_staggers_within_half_to_full_delay(self):
        self.assertEqual(reconnect_delay_seconds(8.0, random_fn=lambda: 0.0), 4.0)
        self.assertEqual(reconnect_delay_seconds(8.0, random_fn=lambda: 1.0), 8.0)
        self.assertEqual(reconnect_delay_seconds(8.0, random_fn=lambda: 0.5), 6.0)


if __name__ == "__main__":
    unittest.main()
