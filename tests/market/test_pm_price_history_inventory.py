"""Guards and counts-only behaviour of tools.research.pm_price_history (no network)."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from tools.research.pm_price_history import guards, inventory as inv


# ----------------------------------------------------------------- date guards

@pytest.mark.parametrize("d", ["2025-01-22", "2026-05-26", "2026-07-31", "2026-09-29", date(2025, 6, 1)])
def test_admitted_dates(d):
    assert guards.refusal_reason(d) is None
    assert guards.require_admitted(d) == (d if isinstance(d, date) else date.fromisoformat(d))


@pytest.mark.parametrize("d,reason", [
    ("2026-09-30", "after_last_admitted_2026_09_29"),
    ("2026-10-15", "after_last_admitted_2026_09_29"),
    ("2026-11-28", "after_last_admitted_2026_09_29"),
    ("2027-03-01", "after_last_admitted_2026_09_29"),
    ("2026-05-27", "sealed_panel_2026_05_27_to_07_30"),
    ("2026-06-30", "sealed_panel_2026_05_27_to_07_30"),
    ("2026-07-30", "sealed_panel_2026_05_27_to_07_30"),
    (None, "unreadable_event_date"),
    ("", "unreadable_event_date"),
    ("june 1", "unreadable_event_date"),
    (datetime(2025, 6, 1, 12), "unreadable_event_date"),
])
def test_refused_dates(d, reason):
    assert guards.refusal_reason(d) == reason
    with pytest.raises(guards.GuardRefusal):
        guards.require_admitted(d)


def test_mg1_window_refused_even_if_cutoff_moved(monkeypatch):
    # MG-1 is refused independently of the 09-29 cutoff (open-ended from its floor).
    monkeypatch.setattr(guards, "LAST_ADMITTED", date(2030, 1, 1))
    assert guards.refusal_reason("2026-10-15") == "mg1_reserved_window"
    assert guards.refusal_reason("2027-06-01") == "mg1_reserved_window"
    assert guards.refusal_reason("2026-10-14") is None


# ----------------------------------------------------------------- endpoint guards

@pytest.mark.parametrize("url", [
    "https://gamma-api.polymarket.com/events?closed=true",
    "https://gamma-api.polymarket.com/series?slug=nyc-daily-weather",
    "https://clob.polymarket.com/prices-history?market=1",
])
def test_public_endpoints_allowed(url):
    guards.require_public_endpoint(url, {"User-Agent": "x"})


@pytest.mark.parametrize("url", [
    "http://clob.polymarket.com/prices-history",
    "https://clob.polymarket.com/order",
    "https://clob.polymarket.com/book",
    "https://gateway.polymarket.us/v1/markets",
    "https://api.polymarket.us/prices-history",
    "https://data-api.polymarket.com/trades",
])
def test_other_endpoints_refused(url):
    with pytest.raises(guards.GuardRefusal):
        guards.require_public_endpoint(url)


@pytest.mark.parametrize("header", ["Authorization", "Cookie", "POLY_API_KEY", "poly-signature", "X-API-KEY"])
def test_auth_headers_refused(header):
    with pytest.raises(guards.GuardRefusal):
        guards.require_public_endpoint("https://clob.polymarket.com/prices-history", {header: "v"})


# ----------------------------------------------------------------- rate limiter / client

class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def test_rate_limiter_caps_bytes_and_paces():
    c = FakeClock()
    lim = inv.RateLimiter(min_interval=0.25, clock=c.clock, sleep=c.sleep)
    lim.wait()
    lim.record(8 * 1024 * 1024)
    lim.wait()
    assert c.now == pytest.approx(2.0)  # 8 MiB at 4 MiB/s
    lim.wait()
    assert c.now == pytest.approx(2.25)  # min interval


def test_rate_cap_above_4mib_refused():
    with pytest.raises(guards.GuardRefusal):
        inv.RateLimiter(max_bps=4 * 1024 * 1024 + 1)


class FakeRaw:
    def __init__(self, body):
        self.body = body

    def read(self, decode_content=True):
        assert decode_content is False
        return self.body


class FakeResp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw = FakeRaw(json.dumps(payload).encode())


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.urls = []

    def get(self, url, timeout=None, stream=None):
        self.urls.append(url)
        return self.responses.pop(0)


def _client(responses):
    c = FakeClock()
    session = FakeSession(responses)
    client = inv.PublicClient(session=session, limiter=inv.RateLimiter(clock=c.clock, sleep=c.sleep),
                              sleep=c.sleep)
    return client, session, c


def test_client_honours_429_retry_after_and_sends_no_auth():
    client, session, clock = _client([FakeResp(429, {}, {"Retry-After": "7"}), FakeResp(200, [1])])
    assert client.get_json(f"{inv.CLOB}/prices-history", {"market": "1"}) == [1]
    assert 7 in clock.sleeps
    assert client.stats.status_429 == 1 and client.stats.requests == 2
    assert not any(k.lower().startswith(("authorization", "cookie", "poly")) for k in session.headers)


def test_client_refuses_disallowed_endpoint_before_request():
    client, session, _ = _client([])
    with pytest.raises(guards.GuardRefusal):
        client.get_json("https://clob.polymarket.com/order")
    assert session.urls == []


# ----------------------------------------------------------------- date inference

@pytest.mark.parametrize("slug,end,expected", [
    ("highest-temperature-in-nyc-on-jan-22", "2025-01-22T12:00:00Z", date(2025, 1, 22)),
    ("highest-temperature-in-nyc-on-jan-23-25", "2025-01-23T12:00:00Z", date(2025, 1, 23)),
    ("highest-temperature-in-new-york-city-on-jan-26", "2025-01-26T12:00:00Z", date(2025, 1, 26)),
    ("highest-temperature-in-nyc-on-september-29-2026", "2026-09-29T12:00:00Z", date(2026, 9, 29)),
    ("highest-temperature-in-seoul-on-dec-31", "2026-01-01T03:00:00Z", date(2025, 12, 31)),
])
def test_event_target_date(slug, end, expected):
    got, _ = inv.event_target_date({"slug": slug, "endDate": end})
    assert got == expected


def test_event_target_date_mismatch_is_unreadable():
    got, how = inv.event_target_date({"slug": "highest-temperature-in-nyc-on-jan-22", "endDate": "2025-03-01T12:00:00Z"})
    assert got is None and how == "slug_endDate_mismatch"
    assert guards.refusal_reason(got) == "unreadable_event_date"


# ----------------------------------------------------------------- discovery and probe

def _event(slug, end):
    return {
        "slug": slug, "endDate": end, "startDate": end[:10] + "T00:00:00Z",
        "markets": [{"clobTokenIds": json.dumps(["111", "222"]), "outcomes": json.dumps(["Yes", "No"]),
                     "outcomePrices": json.dumps(["1", "0"]), "lastTradePrice": 0.99, "bestAsk": 1,
                     "umaResolutionStatus": "resolved"}],
    }


def test_discover_drops_guarded_events_and_price_fields():
    market = inv.Market("nyc", "builtin", "highest-temperature-in-nyc-on", "nyc-daily-weather")
    window1 = [_event("highest-temperature-in-nyc-on-may-26-2026", "2026-05-26T12:00:00Z"),
               _event("highest-temperature-in-nyc-on-may-27-2026", "2026-05-27T12:00:00Z"),
               _event("lowest-temperature-in-nyc-on-may-20-2026", "2026-05-20T12:00:00Z")]
    window2 = [_event("highest-temperature-in-nyc-on-september-29-2026", "2026-09-29T12:00:00Z"),
               _event("highest-temperature-in-nyc-on-september-30-2026", "2026-09-30T12:00:00Z"),
               _event("highest-temperature-in-nyc-on-july-30-2026", "2026-07-30T12:00:00Z")]
    client, session, _ = _client([FakeResp(200, [{"id": 10005}]), FakeResp(200, window1), FakeResp(200, window2)])
    disc = inv.discover(client, market)
    assert sorted(e["event_date"] for e in disc.admitted) == ["2026-05-26", "2026-09-29"]
    assert disc.refused == {"sealed_panel_2026_05_27_to_07_30": 2, "after_last_admitted_2026_09_29": 1}
    assert disc.non_highest == 1
    text = json.dumps(disc.admitted)
    for banned in ("outcomePrices", "lastTradePrice", "bestAsk", "umaResolution", "222"):
        assert banned not in text
    assert all("end_date_max" in u or "end_date_min" in u for u in session.urls[1:])


def test_probe_refuses_guarded_event_before_any_request():
    client, session, _ = _client([])
    event = {"event_date": "2026-06-10", "end_date_utc": "2026-06-10T12:00:00Z", "start_utc": None}
    with pytest.raises(guards.GuardRefusal):
        inv.probe_token(client, event, "111", 60)
    assert session.urls == []


def test_probe_counts_points_and_never_returns_prices():
    history = {"history": [{"t": 1_700_000_000 + 3600 * i, "p": 0.37} for i in range(25)]}
    client, session, _ = _client([FakeResp(200, history)])
    event = {"event_date": "2025-01-22", "end_date_utc": "2025-01-22T12:00:00Z", "start_utc": "2025-01-21T16:00:00Z"}
    row = inv.probe_token(client, event, "111", 60)
    assert row["points"] == 25 and row["median_gap_s"] == 3600 and row["points_per_day"] == 25.0
    assert row["regular_grid_share"] == 1.0
    assert "0.37" not in json.dumps(row)
    assert "fidelity=60" in session.urls[0] and "prices-history" in session.urls[0]


def test_go_verdict_interpretations():
    def row(m, n, ok=True):
        return {"market": m, "admitted_dates": n, "hourly_or_better": ok}
    rows = [row(f"m{i}", 20) for i in range(8)]
    v = inv.go_verdict(rows)
    assert v["go_pooled"] and not v["go_per_market"]
    v = inv.go_verdict([row(f"m{i}", 200) for i in range(7)] + [row("x", 500, ok=False)])
    assert not v["go_pooled"] and not v["go_per_market"]


def test_market_universe_has_22_markets():
    markets = inv.market_universe()
    assert len(markets) == 22
    assert sum(m.role == "builtin" for m in markets) == 12
    assert {m.id for m in markets if m.role == "R2"} == {"munich", "madrid", "beijing", "wellington", "hong-kong"}
