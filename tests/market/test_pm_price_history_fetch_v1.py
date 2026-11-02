"""tools.research.pm_price_history.fetch_v1: guards, suffixed slugs, immutable store (no network)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import date

import pytest

from tools.research.pm_price_history import fetch_v1 as f, guards, inventory as inv


# ----------------------------------------------------------------- suffixed slugs

@pytest.mark.parametrize("slug,end,expected,how", [
    ("highest-temperature-in-nyc-on-may-22-799", "2025-05-22T12:00:00Z", date(2025, 5, 22), "suffixed_slug_eq_endDate"),
    ("highest-temperature-in-nyc-on-february-1-777", "2026-02-01T00:00:00Z", date(2026, 2, 1), "suffixed_slug_eq_endDate"),
    ("highest-temperature-in-toronto-on-december-8-174", "2025-12-08T12:00:00Z", date(2025, 12, 8), "suffixed_slug_eq_endDate"),
    ("highest-temperature-in-nyc-on-may-22-799", "2025-05-23T12:00:00Z", None, "suffixed_slug_endDate_mismatch"),
    ("highest-temperature-in-nyc-on-jan-23-25", "2025-01-23T12:00:00Z", date(2025, 1, 23), "slug_eq_endDate"),
    ("highest-temperature-in-london-on-jan-26-2024", "2025-01-26T12:00:00Z", None, "slug_endDate_mismatch"),
    ("highest-temperature-in-nyc-on-may-22-7999", "2025-05-22T12:00:00Z", None, "slug_endDate_mismatch"),
])
def test_event_target_date_v1(slug, end, expected, how):
    assert f.event_target_date_v1({"slug": slug, "endDate": end}) == (expected, how)


def test_suffixed_slug_still_guarded():
    target, _ = f.event_target_date_v1({"slug": "highest-temperature-in-nyc-on-june-3-123",
                                        "endDate": "2026-06-03T12:00:00Z"})
    assert target == date(2026, 6, 3)
    assert guards.refusal_reason(target) == "sealed_panel_2026_05_27_to_07_30"


# ----------------------------------------------------------------- fakes

class FakeClock:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s


class FakeRaw:
    def __init__(self, body):
        self.body = body

    def read(self, decode_content=True):
        return self.body


class FakeResp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw = FakeRaw(payload if isinstance(payload, bytes) else json.dumps(payload).encode())


class RoutedSession:
    """Answers /series, /events and /prices-history; records every URL."""

    def __init__(self, events_by_window, history=None, status=200):
        self.headers = {}
        self.events_by_window = events_by_window
        self.history = history if history is not None else {"history": [{"t": 1, "p": 0.5}, {"t": 61, "p": 0.5}]}
        self.status = status
        self.urls = []

    def get(self, url, timeout=None, stream=None):
        self.urls.append(url)
        if "/series" in url:
            return FakeResp(200, [{"id": 7}])
        if "/events" in url:
            key = "post" if "end_date_min" in url else "pre"
            return FakeResp(200, self.events_by_window.get(key, []))
        return FakeResp(self.status, self.history)


def _client(session):
    c = FakeClock()
    return f.RawClient(session=session, limiter=inv.RateLimiter(clock=c.clock, sleep=c.sleep), sleep=c.sleep)


def _event(slug, end):
    return {"slug": slug, "endDate": end, "startDate": end[:10] + "T00:00:00Z",
            "markets": [{"clobTokenIds": json.dumps(["111", "222"]), "outcomes": json.dumps(["Yes", "No"]),
                         "groupItemTitle": "60-61F", "conditionId": "0xabc", "question": "q",
                         "outcomePrices": json.dumps(["1", "0"]), "lastTradePrice": 0.99,
                         "umaResolutionStatus": "resolved"}]}


MARKET = inv.Market("nyc", "builtin", "highest-temperature-in-nyc-on", "nyc-daily-weather")


class StaticResources(f.ResourceGuard):
    pass


def _resources(tmp_path, free=100 * 1024 ** 3, rss=100 * 1024 ** 2):
    r = f.ResourceGuard(tmp_path)
    r.free_bytes = lambda p: free
    r.rss = lambda: rss
    return r


# ----------------------------------------------------------------- run

def test_run_saves_raw_immutably_and_seals(tmp_path):
    events = {"pre": [_event("highest-temperature-in-nyc-on-may-22-799", "2025-05-22T12:00:00Z"),
                      _event("highest-temperature-in-nyc-on-may-27-2026", "2026-05-27T12:00:00Z")],
              "post": [_event("highest-temperature-in-nyc-on-september-30-2026", "2026-09-30T12:00:00Z")]}
    session = RoutedSession(events)
    client = _client(session)
    store = f.ImmutableStore(tmp_path / "run-x")
    counts = f.run([MARKET], client, store, _resources(tmp_path), 1, log=lambda m: None)
    assert counts["tokens_saved"] == 1 and counts["stopped"] is None
    assert counts["markets"]["nyc"]["refused_events_by_reason"] == {
        "sealed_panel_2026_05_27_to_07_30": 1, "after_last_admitted_2026_09_29": 1}
    price_urls = [u for u in session.urls if "prices-history" in u]
    assert len(price_urls) == 1 and "market=111" in price_urls[0] and "fidelity=1" in price_urls[0]
    tokens = [json.loads(line) for line in (store.run_dir / "tokens.jsonl").read_text().splitlines()]
    raw = gzip.decompress((store.run_dir / tokens[0]["path"]).read_bytes())
    assert raw == json.dumps(session.history).encode()  # byte-exact
    assert tokens[0]["decoded_sha256"] == hashlib.sha256(raw).hexdigest()
    assert tokens[0]["band_label"] == "60-61F" and tokens[0]["url_params"]["startTs"] < tokens[0]["url_params"]["endTs"]
    events_rows = [json.loads(line) for line in (store.run_dir / "events.jsonl").read_text().splitlines()]
    assert events_rows[0]["date_inference"] == "suffixed_slug_eq_endDate"
    assert "outcomePrices" not in json.dumps(events_rows) and "222" not in json.dumps(events_rows)
    sums = store.seal()
    listed = dict(reversed(line.split("  ", 1)) for line in sums.read_text().splitlines())
    for rel, digest in listed.items():
        assert hashlib.sha256((store.run_dir / rel).read_bytes()).hexdigest() == digest
    assert "events.jsonl" in listed and tokens[0]["path"] in listed
    assert not os.access(store.run_dir / tokens[0]["path"], os.W_OK)


def test_store_refuses_overwrite_and_reuse(tmp_path):
    store = f.ImmutableStore(tmp_path / "run-a")
    store.write("raw/a.json.gz", b"x")
    with pytest.raises(FileExistsError):
        store.write("raw/a.json.gz", b"y")
    with pytest.raises(FileExistsError):
        f.ImmutableStore(tmp_path / "run-a")
    with pytest.raises(guards.GuardRefusal):
        store.write("../escape.txt", b"z")


def test_fetch_token_refuses_guarded_event_before_request(tmp_path):
    session = RoutedSession({})
    client = _client(session)
    store = f.ImmutableStore(tmp_path / "run-g")
    event = {"event_date": "2026-10-20", "slug": "s", "end_date_utc": "2026-10-20T12:00:00Z", "start_utc": None}
    with pytest.raises(guards.GuardRefusal):
        f.fetch_token(client, store, "nyc", event, {"yes_token": "111"}, 1)
    assert session.urls == []


def test_low_disk_stops_before_any_request(tmp_path):
    session = RoutedSession({"pre": [_event("highest-temperature-in-nyc-on-jan-22", "2025-01-22T12:00:00Z")]})
    store = f.ImmutableStore(tmp_path / "run-d")
    counts = f.run([MARKET], _client(session), store, _resources(tmp_path, free=7 * 1024 ** 3), 1,
                   log=lambda m: None)
    assert counts["stopped"] and "free space" in counts["stopped"]
    assert session.urls == []


def test_rss_ceiling_stops(tmp_path):
    with pytest.raises(f.ResourceStop):
        _resources(tmp_path, rss=1100 * 1024 ** 2).check()


def test_repeated_429_stops_run(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "MAX_429", 2)
    pre = [_event(f"highest-temperature-in-nyc-on-jan-{d}", f"2025-01-{d:02d}T12:00:00Z") for d in range(22, 28)]
    session = RoutedSession({"pre": pre}, status=429)
    client = _client(session)
    client.max_attempts = 2
    store = f.ImmutableStore(tmp_path / "run-r")
    counts = f.run([MARKET], client, store, _resources(tmp_path), 1, log=lambda m: None)
    assert counts["stopped"] and "429" in counts["stopped"]
    assert counts["tokens_saved"] == 0


def test_raw_rel_path_rejects_odd_tokens():
    assert f.raw_rel_path("nyc", "2025-01-22", "Slug/x", "123", 1) == "raw/nyc/2025-01-22/slug_x/123.f1.json.gz"
    with pytest.raises(guards.GuardRefusal):
        f.raw_rel_path("nyc", "2025-01-22", "s", "../1", 1)


def test_main_refuses_weaker_limits(tmp_path):
    with pytest.raises(guards.GuardRefusal):
        f.main(["--root", str(tmp_path), "--min-free-gib", "4"])
    with pytest.raises(guards.GuardRefusal):
        f.main(["--root", str(tmp_path), "--max-rss-mib", "4096"])
    with pytest.raises(guards.GuardRefusal):
        f.main(["--root", str(tmp_path), "--min-interval", "0.05"])
