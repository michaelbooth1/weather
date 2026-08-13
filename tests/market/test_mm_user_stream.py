import json

import pytest

from weather.market.mm_user_stream import OfficialUserStreamReader


MAKER = "0x" + "a" * 40
CONDITION = "0x" + "b" * 64
TOKEN = "12345"


class FakeWebsocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    def settimeout(self, _value):
        return None

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        if not self.frames:
            raise TimeoutError()
        return self.frames.pop(0)

    def close(self):
        self.closed = True


def order_event(**overrides):
    payload = {
        "event_type": "order",
        "id": "order-1",
        "market": CONDITION,
        "asset_id": TOKEN,
        "type": "PLACEMENT",
        "status": "LIVE",
        "maker_address": MAKER,
    }
    payload.update(overrides)
    return payload


def reader(tmp_path, websocket):
    return OfficialUserStreamReader(
        api_key="api-key",
        secret="api-secret",
        passphrase="passphrase",
        maker_address=MAKER,
        condition_id=CONDITION,
        token_id=TOKEN,
        journal_path=tmp_path / "user-stream.jsonl",
        websocket_factory=lambda *_args, **_kwargs: websocket,
    )


def test_account_wide_reader_journals_normalized_event_without_auth(tmp_path):
    websocket = FakeWebsocket(["PONG", json.dumps(order_event(
        unexpected_server_field={
            "apiKey": "echoed-api-key",
            "secret": "echoed-api-secret",
            "passphrase": "echoed-passphrase",
        },
    ))])
    stream = reader(tmp_path, websocket)

    stream.run(max_events=1)

    subscription = json.loads(websocket.sent[0])
    assert subscription == {
        "auth": {
            "apiKey": "api-key",
            "secret": "api-secret",
            "passphrase": "passphrase",
        },
        "type": "user",
    }
    assert websocket.closed
    assert stream.events()[0]["lifecycle_key"] == "order-1"
    assert stream.events()[0]["maker_address"] == MAKER
    assert len(stream.events()[0]["raw_event_sha256"]) == 64
    assert "unexpected_server_field" not in stream.events()[0]
    assert stream.health()["state"] == "STOPPED"
    evidence = stream.bootstrap_evidence()
    assert evidence["account_wide_subscription_sent"] is True
    assert evidence["server_pong_observed"] is True
    assert evidence["transport_active"] is False
    assert len(evidence["subscription_shape_sha256"]) == 64
    assert len(evidence["journal_sha256"]) == 64
    journal = (tmp_path / "user-stream.jsonl").read_text(encoding="utf-8")
    assert "api-secret" not in journal
    assert "passphrase" not in journal
    assert "api-key" not in journal
    assert "echoed-api-secret" not in journal
    assert "echoed-passphrase" not in journal
    assert "echoed-api-key" not in journal
    assert "subscription_sent" in journal
    assert "user_event" in journal


def test_out_of_scope_event_fails_closed_without_raw_exception_text(tmp_path):
    websocket = FakeWebsocket([
        json.dumps(order_event(market="0x" + "c" * 64)),
    ])
    stream = reader(tmp_path, websocket)

    with pytest.raises(RuntimeError, match="outside the pilot"):
        stream.run()

    health = stream.health()
    assert health["state"] == "FAILED"
    assert health["failure_type"] == "RuntimeError"
    journal = (tmp_path / "user-stream.jsonl").read_text(encoding="utf-8")
    assert "outside the pilot" not in journal
    assert '"exception_type":"RuntimeError"' in journal
    assert websocket.closed


def test_wrong_maker_event_fails_closed(tmp_path):
    websocket = FakeWebsocket([
        json.dumps(order_event(maker_address="0x" + "c" * 40)),
    ])
    stream = reader(tmp_path, websocket)

    with pytest.raises(RuntimeError, match="maker scope"):
        stream.run()

    assert stream.health()["state"] == "FAILED"
    assert stream.events() == []


def test_missing_server_heartbeat_fails_closed(tmp_path):
    websocket = FakeWebsocket([])

    class StepClock:
        def __init__(self):
            self.value = -1.0

        def __call__(self):
            self.value += 1.0
            return self.value

    stream = OfficialUserStreamReader(
        api_key="api-key",
        secret="api-secret",
        passphrase="passphrase",
        maker_address=MAKER,
        condition_id=CONDITION,
        token_id=TOKEN,
        journal_path=tmp_path / "user-stream.jsonl",
        websocket_factory=lambda *_args, **_kwargs: websocket,
        heartbeat_seconds=1.0,
        inbound_silence_seconds=2.0,
        monotonic_clock=StepClock(),
    )

    with pytest.raises(ConnectionError, match="no server PONG"):
        stream.run()

    assert stream.health()["state"] == "FAILED"


def test_market_events_cannot_mask_missing_server_pong(tmp_path):
    websocket = FakeWebsocket([json.dumps(order_event()) for _ in range(5)])

    class StepClock:
        def __init__(self):
            self.value = -1.0

        def __call__(self):
            self.value += 1.0
            return self.value

    stream = OfficialUserStreamReader(
        api_key="api-key",
        secret="api-secret",
        passphrase="passphrase",
        maker_address=MAKER,
        condition_id=CONDITION,
        token_id=TOKEN,
        journal_path=tmp_path / "user-stream.jsonl",
        websocket_factory=lambda *_args, **_kwargs: websocket,
        heartbeat_seconds=1.0,
        inbound_silence_seconds=2.0,
        monotonic_clock=StepClock(),
    )

    with pytest.raises(ConnectionError, match="no server PONG"):
        stream.run()

    assert stream.health()["state"] == "FAILED"


def test_inbound_silence_deadline_must_exceed_heartbeat(tmp_path):
    with pytest.raises(ValueError, match="must exceed"):
        OfficialUserStreamReader(
            api_key="api-key",
            secret="api-secret",
            passphrase="passphrase",
            maker_address=MAKER,
            condition_id=CONDITION,
            token_id=TOKEN,
            journal_path=tmp_path / "user-stream.jsonl",
            heartbeat_seconds=10.0,
            inbound_silence_seconds=10.0,
        )


def test_existing_journal_blocks_before_connect(tmp_path):
    websocket = FakeWebsocket([])
    stream = reader(tmp_path, websocket)
    (tmp_path / "user-stream.jsonl").write_text("existing\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="must not already exist"):
        stream.run()

    assert websocket.sent == []


def test_background_reader_suppresses_raw_transport_exception_text(
    tmp_path,
    monkeypatch,
    capsys,
):
    escaped = []
    monkeypatch.setattr(
        "threading.excepthook",
        lambda args: escaped.append(args.exc_value),
    )

    def fail_to_connect(*_args, **_kwargs):
        raise RuntimeError("RAW-SECRET-TRANSPORT-MESSAGE")

    stream = OfficialUserStreamReader(
        api_key="api-key",
        secret="api-secret",
        passphrase="passphrase",
        maker_address=MAKER,
        condition_id=CONDITION,
        token_id=TOKEN,
        journal_path=tmp_path / "user-stream.jsonl",
        websocket_factory=fail_to_connect,
    )

    stream.start()
    stream._thread.join(2.0)

    assert stream.health()["state"] == "FAILED"
    assert stream.health()["failure_type"] == "RuntimeError"
    assert escaped == []
    assert "RAW-SECRET-TRANSPORT-MESSAGE" not in capsys.readouterr().err
    assert "RAW-SECRET-TRANSPORT-MESSAGE" not in (
        tmp_path / "user-stream.jsonl"
    ).read_text(encoding="utf-8")
