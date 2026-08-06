import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from weather.io import acquire_writer_lock, release_writer_lock
from weather.market.market_microstructure_capture import MarketMicrostructureStore
from weather.market.mm_execution_capture import (
    EMPTY_SHA256,
    EXECUTION_TAPE_COLUMNS,
    HOST_POLICY_MODE,
    LOCK_SCOPE,
    RETENTION_MODE,
    _asset_set_sha256,
    _receipt_binding_sha256,
    _seconds_until_daily_binding_roll,
    _training_window_pause,
    build_parser,
    record_fleet_session,
    run_loop,
)
from weather.market.mm_paper_constants import (
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)


UTC = timezone.utc
NOON_UTC = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)


class FakeWebSocket:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.sent = []
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        if self.payloads:
            return json.dumps(self.payloads.pop(0))
        raise TimeoutError

    def close(self):
        return None


def _contracts():
    return {
        "retention_mode": RETENTION_MODE,
        "lock_scope": LOCK_SCOPE,
        "host_policy_mode": HOST_POLICY_MODE,
    }


def _binding(tmp_path, slug, market, assets):
    return {
        "event_slug": slug,
        "market_id": market,
        "target_date": "2026-08-05",
        "asset_ids": set(assets),
        "store": MarketMicrostructureStore(root=tmp_path / slug, event_slug=slug),
    }


def _execution(asset_id, timestamp, *, price="0.51", size="2", side="BUY", tx="0x1"):
    return {
        "event_type": "last_trade_price",
        "asset_id": asset_id,
        "market": f"condition-{asset_id}",
        "price": price,
        "size": size,
        "side": side,
        "timestamp": str(timestamp),
        "transaction_hash": tx,
    }


def _csv_rows(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_fleet_session_retains_only_execution_members_and_binds_receipts(tmp_path):
    bindings = [
        _binding(tmp_path, "event-a", "a", {"a1"}),
        _binding(tmp_path, "event-b", "b", {"b1"}),
        _binding(tmp_path, "event-zero", "zero", {"z1"}),
    ]
    ws = FakeWebSocket([
        [
            {"event_type": "book", "asset_id": "a1", "bids": []},
            {"event_type": "price_change", "price_changes": [{"asset_id": "a1"}]},
            {"event_type": "book", "asset_id": "z1", "bids": []},
            _execution("a1", 1785945600123, tx="0xa"),
            _execution("b1", 1785945600456, price="0.62", tx="0xb"),
            _execution("not-subscribed", 1785945600789),
        ],
        [_execution("a1", 1785945601123, price="0.52", tx="0xa2")],
    ])
    progress = []
    receipt = record_fleet_session(
        bindings,
        seconds=1,
        heartbeat_seconds=10,
        websocket_factory=lambda *_args, **_kwargs: ws,
        progress_callback=progress.append,
        now_fn=lambda: NOON_UTC,
        monotonic_fn=lambda: 0.0 if ws.payloads else 2.0,
        **_contracts(),
    )

    assert receipt["status"] == "COMPLETE"
    assert receipt["continuous_coverage"] is True
    assert receipt["message_count"] == 2
    assert receipt["event_row_count"] == 3
    assert receipt["local_connection_message_sequence_start"] == 1
    assert receipt["local_connection_message_sequence_end"] == 2
    assert progress[0]["status"] == "RUNNING"

    a_rows = _csv_rows(tmp_path / "event-a" / EXECUTION_CANONICAL_TAPE_FILENAME)
    b_rows = _csv_rows(tmp_path / "event-b" / EXECUTION_CANONICAL_TAPE_FILENAME)
    assert [row["event_type"] for row in a_rows + b_rows] == [
        "last_trade_price",
        "last_trade_price",
        "last_trade_price",
    ]
    assert [row["local_connection_message_sequence"] for row in a_rows] == ["1", "2"]
    assert b_rows[0]["local_connection_message_sequence"] == "1"
    assert a_rows[0]["exchange_time_utc"].endswith(".123+00:00")
    assert a_rows[0]["timestamp_precision_seconds"] == "0.001"
    assert a_rows[0]["transaction_hash"] == "0xa"
    assert a_rows[0]["book_alignment_sequence_status"] == "not_exposed_by_public_feed"
    assert list(a_rows[0]) == EXECUTION_TAPE_COLUMNS

    for binding, expected_count in zip(bindings, (2, 1, 0)):
        folder = tmp_path / binding["event_slug"]
        session = json.loads(
            (folder / EXECUTION_SESSION_FILENAME).read_text(encoding="utf-8").strip()
        )
        assert session["execution_count"] == expected_count
        assert session["subscribed_asset_ids"] == sorted(binding["asset_ids"])
        assert session["observed_subscribed_asset_ids"] == sorted(binding["asset_ids"])
        assert session["observed_subscribed_asset_set_sha256"] == _asset_set_sha256(
            binding["asset_ids"]
        )
        assert session["receipt_binding_sha256"] == _receipt_binding_sha256(session)
        raw_path = folder / EXECUTION_RAW_TAPE_FILENAME
        canonical_path = folder / EXECUTION_CANONICAL_TAPE_FILENAME
        if expected_count:
            assert session["raw_tape_prefix_size_bytes"] == raw_path.stat().st_size
            assert session["canonical_tape_prefix_size_bytes"] == canonical_path.stat().st_size
            assert session["raw_tape_prefix_sha256"] == hashlib.sha256(raw_path.read_bytes()).hexdigest()
            assert session["canonical_tape_prefix_sha256"] == hashlib.sha256(
                canonical_path.read_bytes()
            ).hexdigest()
        else:
            assert not raw_path.exists()
            assert not canonical_path.exists()
            assert session["raw_tape_prefix_size_bytes"] == 0
            assert session["canonical_tape_prefix_size_bytes"] == 0
            assert session["raw_tape_prefix_sha256"] == EMPTY_SHA256
            assert session["canonical_tape_prefix_sha256"] == EMPTY_SHA256


def test_clob_raw_tape_lock_cannot_block_execution_writer(tmp_path, monkeypatch):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})
    maker_anchors = []

    def capture_maker_anchor(anchor, **kwargs):
        maker_anchors.append(anchor)
        return acquire_writer_lock(anchor, **kwargs)

    monkeypatch.setattr(
        "weather.market.mm_execution_capture.acquire_writer_lock",
        capture_maker_anchor,
    )

    def forbidden_raw_guard(*_args, **_kwargs):
        raise AssertionError("maker producer touched clob_raw_tape")

    binding["store"].raw_tape_guard = forbidden_raw_guard
    raw_lock = acquire_writer_lock(binding["store"].raw_tape_lock_anchor_path)
    assert raw_lock is not None
    ws = FakeWebSocket([[_execution("a1", 1785945600123)]])
    try:
        receipt = record_fleet_session(
            [binding],
            seconds=1,
            websocket_factory=lambda *_args, **_kwargs: ws,
            now_fn=lambda: NOON_UTC,
            monotonic_fn=lambda: 0.0 if ws.payloads else 2.0,
            **_contracts(),
        )
    finally:
        release_writer_lock(raw_lock)
    assert receipt["status"] == "COMPLETE"
    assert (tmp_path / "event-a" / EXECUTION_RAW_TAPE_FILENAME).exists()
    assert maker_anchors
    assert {anchor.name for anchor in maker_anchors} == {"mm_execution_tape"}


def test_incompatible_execution_csv_header_fails_closed_before_raw_append(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})
    canonical = tmp_path / "event-a" / EXECUTION_CANONICAL_TAPE_FILENAME
    canonical.parent.mkdir(parents=True)
    canonical.write_text("legacy,header\nvalue,row\n", encoding="utf-8")
    receipt = record_fleet_session(
        [binding],
        seconds=0.01,
        websocket_factory=lambda *_args, **_kwargs: FakeWebSocket([
            [_execution("a1", 1785945600123)]
        ]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )
    assert receipt["status"] == "INCOMPLETE"
    assert "incompatible execution tape header" in receipt["reason"]
    assert not (tmp_path / "event-a" / EXECUTION_RAW_TAPE_FILENAME).exists()


def test_malformed_exchange_timestamp_makes_session_incomplete(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})
    payload = _execution("a1", "not-a-millisecond")
    receipt = record_fleet_session(
        [binding],
        seconds=0.01,
        websocket_factory=lambda *_args, **_kwargs: FakeWebSocket([[payload]]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["continuous_coverage"] is False
    assert "invalid source millisecond timestamp" in receipt["reason"]


def test_missing_strict_through_fields_and_malformed_frames_fail_closed(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})
    missing_transaction = _execution("a1", 1785945600123)
    missing_transaction.pop("transaction_hash")
    receipt = record_fleet_session(
        [binding],
        seconds=0.01,
        websocket_factory=lambda *_args, **_kwargs: FakeWebSocket([
            [missing_transaction]
        ]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )
    assert receipt["status"] == "INCOMPLETE"
    assert "missing valid strict-through evidence" in receipt["reason"]

    class MalformedWebSocket(FakeWebSocket):
        def recv(self):
            return "{not-json"

    malformed = record_fleet_session(
        [binding],
        seconds=0.01,
        websocket_factory=lambda *_args, **_kwargs: MalformedWebSocket([]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )
    assert malformed["status"] == "INCOMPLETE"
    assert "unrecognized non-JSON WebSocket frame" in malformed["reason"]


def test_silent_connection_cannot_prove_exact_zero(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})
    receipt = record_fleet_session(
        [binding],
        seconds=0.01,
        websocket_factory=lambda *_args, **_kwargs: FakeWebSocket([]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )

    assert receipt["status"] == "INCOMPLETE"
    assert receipt["continuous_coverage"] is False
    assert receipt["reason"] == "event_subscriptions_not_fully_observed:event-a"


def test_one_live_event_cannot_prove_exact_zero_for_an_unobserved_event(tmp_path):
    bindings = [
        _binding(tmp_path, "event-a", "a", {"a1"}),
        _binding(tmp_path, "event-b", "b", {"b1"}),
    ]
    ws = FakeWebSocket([[{"event_type": "book", "asset_id": "a1", "bids": []}]])

    receipt = record_fleet_session(
        bindings,
        seconds=1,
        websocket_factory=lambda *_args, **_kwargs: ws,
        now_fn=lambda: NOON_UTC,
        monotonic_fn=lambda: 0.0 if ws.payloads else 2.0,
        **_contracts(),
    )

    assert receipt["status"] == "INCOMPLETE"
    assert receipt["coverage_start_utc"] is None
    assert receipt["reason"] == "event_subscriptions_not_fully_observed:event-b"
    event_a = json.loads(
        (tmp_path / "event-a" / EXECUTION_SESSION_FILENAME).read_text(encoding="utf-8")
    )
    event_b = json.loads(
        (tmp_path / "event-b" / EXECUTION_SESSION_FILENAME).read_text(encoding="utf-8")
    )
    assert event_a["market_data_message_count"] == 1
    assert event_a["observed_subscribed_asset_ids"] == ["a1"]
    assert event_b["market_data_message_count"] == 0
    assert event_b["observed_subscribed_asset_ids"] == []


def test_disconnect_and_clean_close_are_incomplete(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})

    class BrokenWebSocket(FakeWebSocket):
        def recv(self):
            raise ConnectionError("socket dropped")

    broken = record_fleet_session(
        [binding],
        seconds=1,
        websocket_factory=lambda *_args, **_kwargs: BrokenWebSocket([]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )
    assert broken["status"] == "INCOMPLETE"
    assert "socket dropped" in broken["reason"]

    class ClosedWebSocket(FakeWebSocket):
        def recv(self):
            return ""

    closed = record_fleet_session(
        [binding],
        seconds=1,
        websocket_factory=lambda *_args, **_kwargs: ClosedWebSocket([]),
        now_fn=lambda: NOON_UTC,
        **_contracts(),
    )
    assert closed["status"] == "INCOMPLETE"
    assert "closed without a close exception" in closed["reason"]


def test_host_policy_pause_and_daily_binding_roll_boundaries(tmp_path, monkeypatch):
    assert _training_window_pause(datetime(2026, 8, 5, 4, 59, tzinfo=UTC)) is None
    pause = _training_window_pause(datetime(2026, 8, 5, 5, 0, tzinfo=UTC))
    assert pause["start_utc"] == "2026-08-05T05:00:00+00:00"
    assert pause["restore_utc"] == "2026-08-05T08:15:00+00:00"
    assert _training_window_pause(datetime(2026, 8, 5, 8, 14, tzinfo=UTC)) is not None
    assert _training_window_pause(datetime(2026, 8, 5, 8, 15, tzinfo=UTC)) is None
    assert _seconds_until_daily_binding_roll(
        datetime(2026, 8, 5, 8, 15, tzinfo=UTC)
    ) == pytest.approx(20 * 3600 + 40 * 60)

    monkeypatch.setattr(
        "weather.market.mm_execution_capture.fleet_bindings",
        lambda **_kwargs: pytest.fail("paused loop must not fetch or connect"),
    )
    status_path = tmp_path / "status.json"
    result = run_loop(
        status_path=status_path,
        snapshots_root=tmp_path,
        once=True,
        now_fn=lambda: datetime(2026, 8, 5, 6, 0, tzinfo=UTC),
        **_contracts(),
    )
    assert result["status"] == "PAUSED"
    assert result["planned_coverage_break"]["policy"] == "WeatherTrainingWindow"
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "PAUSED"


def test_active_session_disconnects_at_training_window_and_binds_planned_break(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})

    class ClosingWebSocket(FakeWebSocket):
        closed = False

        def close(self):
            self.closed = True

    ws = ClosingWebSocket([[{"event_type": "book", "asset_id": "a1"}]])
    clock = iter([
        datetime(2026, 8, 5, 4, 59, 58, tzinfo=UTC),
        datetime(2026, 8, 5, 4, 59, 58, tzinfo=UTC),
        datetime(2026, 8, 5, 4, 59, 58, tzinfo=UTC),
        datetime(2026, 8, 5, 4, 59, 58, tzinfo=UTC),
        datetime(2026, 8, 5, 4, 59, 59, tzinfo=UTC),
        datetime(2026, 8, 5, 4, 59, 59, tzinfo=UTC),
        datetime(2026, 8, 5, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 5, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 5, 5, 0, 0, tzinfo=UTC),
    ])
    receipt = record_fleet_session(
        [binding],
        seconds=60,
        websocket_factory=lambda *_args, **_kwargs: ws,
        now_fn=lambda: next(clock),
        **_contracts(),
    )

    assert ws.closed is True
    assert receipt["status"] == "COMPLETE"
    assert receipt["continuous_coverage"] is True
    assert receipt["reason"] == "planned_host_policy_pause"
    assert receipt["planned_coverage_break"] == {
        "policy": "WeatherTrainingWindow",
        "reason": "planned_host_policy_pause",
        "timezone": "America/Toronto",
        "start_utc": "2026-08-05T05:00:00+00:00",
        "restore_utc": "2026-08-05T08:15:00+00:00",
        "seconds_until_restore": 11700.0,
    }
    session = json.loads(
        (tmp_path / "event-a" / EXECUTION_SESSION_FILENAME).read_text(encoding="utf-8")
    )
    assert session["planned_coverage_break"] == receipt["planned_coverage_break"]
    assert session["execution_count"] == 0
    assert session["receipt_binding_sha256"] == _receipt_binding_sha256(session)


def test_connect_finishing_at_training_boundary_never_subscribes(tmp_path):
    binding = _binding(tmp_path, "event-a", "a", {"a1"})

    class ClosingWebSocket(FakeWebSocket):
        closed = False

        def close(self):
            self.closed = True

    ws = ClosingWebSocket([])
    clock = iter([
        datetime(2026, 8, 5, 4, 59, 58, tzinfo=UTC),
        datetime(2026, 8, 5, 4, 59, 59, tzinfo=UTC),
        datetime(2026, 8, 5, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 5, 5, 0, 0, tzinfo=UTC),
    ])
    receipt = record_fleet_session(
        [binding],
        seconds=60,
        websocket_factory=lambda *_args, **_kwargs: ws,
        now_fn=lambda: next(clock),
        **_contracts(),
    )

    assert ws.sent == []
    assert ws.closed is True
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["reason"] == "planned_host_policy_pause_before_subscription"
    assert receipt["planned_coverage_break"]["policy"] == "WeatherTrainingWindow"


def test_run_loop_carries_startup_pause_into_first_post_restore_receipt(
    tmp_path,
    monkeypatch,
):
    current = {"now": datetime(2026, 8, 5, 6, 0, tzinfo=UTC)}
    captured = {}

    monkeypatch.setattr(
        "weather.market.mm_execution_capture.fleet_bindings",
        lambda **_kwargs: [object()],
    )

    def fake_record(_bindings, **kwargs):
        captured.update(kwargs)
        return {"status": "COMPLETE", "reason": "duration_complete"}

    monkeypatch.setattr(
        "weather.market.mm_execution_capture.record_fleet_session",
        fake_record,
    )

    sleep_calls = 0

    def sleep(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            current["now"] = datetime(2026, 8, 5, 8, 15, tzinfo=UTC)
            return
        raise StopIteration

    with pytest.raises(StopIteration):
        run_loop(
            status_path=tmp_path / "status.json",
            snapshots_root=tmp_path,
            once=False,
            now_fn=lambda: current["now"],
            sleep_fn=sleep,
            **_contracts(),
        )

    assert captured["preceding_planned_coverage_break"]["policy"] == (
        "WeatherTrainingWindow"
    )
    assert captured["preceding_planned_coverage_break"]["restore_utc"] == (
        "2026-08-05T08:15:00+00:00"
    )


def test_cli_requires_the_only_safe_contract_values():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--market", "all"])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--retention-mode", "all-payloads",
            "--lock-scope", LOCK_SCOPE,
            "--host-policy-mode", HOST_POLICY_MODE,
        ])
    args = parser.parse_args([
        "--retention-mode", RETENTION_MODE,
        "--lock-scope", LOCK_SCOPE,
        "--host-policy-mode", HOST_POLICY_MODE,
    ])
    assert args.retention_mode == RETENTION_MODE
