import json

from weather.market.market_microstructure_capture import MarketMicrostructureStore
from weather.market.mm_execution_capture import record_fleet_session


class FakeWebSocket:
    def __init__(self, payload):
        self.payload = payload
        self.sent = []
        self.delivered = False

    def settimeout(self, _value):
        return None

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        if not self.delivered:
            self.delivered = True
            return json.dumps(self.payload)
        raise TimeoutError

    def close(self):
        return None


def test_fleet_session_routes_payloads_and_retains_complete_receipts(tmp_path):
    stores = {
        slug: MarketMicrostructureStore(root=tmp_path / slug, event_slug=slug)
        for slug in ("event-a", "event-b")
    }
    bindings = [
        {"event_slug": "event-a", "market_id": "a", "target_date": "2026-08-04", "asset_ids": {"a1"}, "store": stores["event-a"]},
        {"event_slug": "event-b", "market_id": "b", "target_date": "2026-08-04", "asset_ids": {"b1"}, "store": stores["event-b"]},
    ]
    ws = FakeWebSocket([
        {"event_type": "last_trade_price", "asset_id": "a1", "price": "0.51", "size": "2"},
        {"event_type": "last_trade_price", "asset_id": "b1", "price": "0.62", "size": "3"},
    ])
    progress = []
    receipt = record_fleet_session(
        bindings,
        seconds=0.01,
        heartbeat_seconds=10,
        websocket_factory=lambda *_args, **_kwargs: ws,
        progress_callback=progress.append,
    )
    assert receipt["status"] == "COMPLETE"
    assert receipt["continuous_coverage"] is True
    assert progress[0]["status"] == "RUNNING"
    for slug, asset in (("event-a", "a1"), ("event-b", "b1")):
        raw = json.loads((tmp_path / slug / "market_ws.jsonl").read_text(encoding="utf-8").strip())
        assert raw["payload"][0]["asset_id"] == asset
        session = json.loads((tmp_path / slug / "market_ws_sessions.jsonl").read_text(encoding="utf-8").strip())
        assert session["status"] == "COMPLETE"
        assert session["session_id"] == receipt["session_id"]


def test_disconnect_is_retained_as_incomplete_coverage(tmp_path):
    store = MarketMicrostructureStore(root=tmp_path / "event-a", event_slug="event-a")
    binding = {"event_slug": "event-a", "market_id": "a", "target_date": "2026-08-04", "asset_ids": {"a1"}, "store": store}

    class BrokenWebSocket(FakeWebSocket):
        def recv(self):
            raise ConnectionError("socket dropped")

    receipt = record_fleet_session(
        [binding],
        seconds=1,
        websocket_factory=lambda *_args, **_kwargs: BrokenWebSocket({}),
    )
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["continuous_coverage"] is False
    assert "socket dropped" in receipt["reason"]


def test_clean_socket_close_is_not_complete_coverage(tmp_path):
    store = MarketMicrostructureStore(root=tmp_path / "event-a", event_slug="event-a")
    binding = {
        "event_slug": "event-a",
        "market_id": "a",
        "target_date": "2026-08-04",
        "asset_ids": {"a1"},
        "store": store,
    }

    class ClosedWebSocket(FakeWebSocket):
        def recv(self):
            return ""

    receipt = record_fleet_session(
        [binding],
        seconds=1,
        websocket_factory=lambda *_args, **_kwargs: ClosedWebSocket({}),
    )
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["continuous_coverage"] is False
    assert "closed without a close exception" in receipt["reason"]
