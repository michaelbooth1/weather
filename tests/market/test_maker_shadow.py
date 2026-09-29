from dataclasses import replace
from datetime import timedelta
import json

import pytest

from maker_core.evidence.journal import digest
from maker_core.replay.bundle import Condition
from maker_core.replay.lifecycle import ReplayConfig
from maker_core.shadow.codec import checked, decode
from maker_core.shadow.session import Manifest, verified
from maker_core.shadow.agreement import evaluate
from weather.market.maker_shadow import WeatherDomain, public_session, assert_launcher
from tests.market.test_maker_plugin import fixture as captured, NOW


def test_weather_composition_and_recording_public_session(tmp_path):
    universe, bands, spec, target, discovery, books = captured()
    inputs = {"discovery": [discovery], "books": [books], "band_rows": bands}
    assert decode(checked(inputs)) == inputs
    domain = WeatherDomain(inputs)
    markets = domain.descriptors(NOW)
    assert markets
    # No provider bulletin: explicit Unavailable, never a manufactured probability.
    until = NOW+timedelta(minutes=1)
    manifest = Manifest("weather-fixture", "1"*40, markets[0].plugin_version,
        "unavailable", digest(inputs), "2"*64,
        tuple(Condition(m.condition_id, spec.id, "weather", NOW, until) for m in markets),
        tuple((m.condition_id, target.isoformat()) for m in markets), NOW, until,
        ReplayConfig(hazard_per_minute=.001, max_book_gap_seconds=10), "synthetic", mode="drill")
    now = [NOW]
    wire = []
    public_books = {b["asset_id"]: b for b in json.loads(books["body_utf8"])}
    class Transport:
        def read(self, kind, identity):
            wire.append(("GET", kind, identity))
            if kind == "book":
                value = {**public_books[identity], "timestamp": str(int(now[0].timestamp()*1000))}
            else:
                value = {"data": [{"condition_id": identity, "rewards_min_size": 20, "rewards_max_spread": 5,
                         "rewards_config": [{"start_date": "2030-01-01", "end_date": "2030-02-01", "rate_per_day": 100}]}]}
            return json.dumps(value).encode()
    class Stream:
        def __init__(self, assets): wire.append(("SUBSCRIBE", tuple(assets)))
        def receive(self):
            now[0] += timedelta(seconds=1)
            if now[0] > NOW+timedelta(seconds=3):
                raise OSError("fixture disconnect")
            return "PONG"
        def ping(self): wire.append(("PING",))
        def close(self): wire.append(("CLOSE",))
    result = public_session(manifest, inputs, tmp_path / "session", tmp_path / "STOP",
                            clock=lambda: now[0], transport_factory=Transport, stream_factory=Stream)
    assert result["status"] == "CLOSED", result
    assert wire[-1] == ("CLOSE",)
    assert all(c[0] in ("GET", "SUBSCRIBE", "PING", "CLOSE") for c in wire)
    report = evaluate(tmp_path / "session", result["receipt_sha256"], tmp_path / "evaluation")
    assert report["status"] == "PASS", report
    _, trace, _, _ = verified(tmp_path / "session", result["receipt_sha256"])
    assert not any(r["decision"]["action"] == "QUOTE" for r in trace if r["event"] == "decision")


def test_bare_public_command_has_no_network_authority(monkeypatch):
    monkeypatch.setattr("weather.market.maker_shadow.os.name", "posix")
    with pytest.raises(ValueError, match="launcher"):
        assert_launcher()
