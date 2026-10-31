"""Synthetic tests for the S31 venue fetch guards (no network; every transport is a fake)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from weather.sources.free_screens import s31_venue_fetch as s31

TZ = "America/New_York"
SERIES = "KXHIGHNY"
MARKET = "KXHIGHNY-26SEP15-B72.5"
EVENT = "KXHIGHNY-26SEP15"


class FakeTransport:
    def __init__(self, status=200, body=b"{}"):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        return self.status, {}, self.body


def make(tmp_path, transport):
    limiter = s31.RateLimiter(clock=lambda: 0.0, sleep=lambda s: None)
    return s31.Fetcher(tmp_path / "out", tmp_path / "archive", transport=transport, limiter=limiter, run_id="t")


def receipts(tmp_path):
    return [json.loads(x) for x in (tmp_path / "out" / "receipts.jsonl").read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------------------------------ window refusal

@pytest.mark.parametrize("day", [date(2026, 9, 30), date(2026, 7, 31), date(2026, 10, 15)])
def test_target_outside_dev_window_refused(day):
    with pytest.raises(s31.WindowRefused):
        s31.candle_window(day, TZ)


def test_window_bounded_by_local_end_of_dev_last():
    win = s31.candle_window(date(2026, 9, 29), TZ)
    assert win.end_utc == datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)
    assert win.start_utc == datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)
    with pytest.raises(s31.WindowRefused):
        s31.candle_window(date(2026, 9, 29), "Europe/London")


def test_late_ticker_refused_before_any_request(tmp_path):
    fake = FakeTransport()
    fetcher = make(tmp_path, fake)
    with pytest.raises(s31.WindowRefused):
        fetcher.kalshi_candles(SERIES, "KXHIGHNY-26SEP30-B72.5", TZ, "live")
    with pytest.raises(s31.WindowRefused):
        fetcher.kalshi_markets("KXHIGHNY-26OCT01")
    with pytest.raises(s31.WindowRefused):
        fetcher.fex_pairs(date(2026, 9, 30))
    with pytest.raises(s31.WindowRefused):
        fetcher.fex_pairs(date(2026, 7, 29))
    assert fake.calls == []


def test_candle_request_window_in_query(tmp_path):
    fake = FakeTransport(body=b'{"candlesticks": []}')
    make(tmp_path, fake).kalshi_candles(SERIES, MARKET, TZ, "live")
    url = fake.calls[0][0]
    end = int(datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc).timestamp())
    assert f"end_ts={end - 1}" in url and "period_interval=1" in url


# -------------------------------------------------------------------------------- late-timestamp refusal

def test_late_candle_dropped_unparsed_and_recorded(tmp_path):
    end = int(datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc).timestamp())
    body = json.dumps({"candlesticks": [
        {"end_period_ts": end - 60, "yes_bid": {"close_dollars": "0.40"}, "yes_ask": {"close_dollars": "0.44"}},
        {"end_period_ts": end, "yes_bid": "GARBAGE-NOT-A-PRICE", "yes_ask": None},
        {"end_period_ts": end + 600, "yes_bid": {"close_dollars": "not-a-number"}},
    ]}).encode()
    rows = make(tmp_path, FakeTransport(body=body)).kalshi_candles(SERIES, MARKET, TZ, "live")
    assert rows == [{"ticker": MARKET, "end_period_ts": end - 60, "yes_bid_close": 0.40, "yes_ask_close": 0.44}]
    rec = receipts(tmp_path)[0]
    assert rec["n_dropped_late"] == 2
    assert [d["end_period_ts"] for d in rec["dropped_late"]] == [end, end + 600]
    assert "_quarantine_late" in rec["archive"]


def test_historical_candle_close_field():
    end = 2_000_000_000
    body = json.dumps({"candlesticks": [{"end_period_ts": 100, "yes_bid": {"close": 0.3}, "yes_ask": {"close": 0.35}}]})
    rows, dropped = s31.parse_candles(body.encode(), MARKET, end)
    assert rows[0]["yes_bid_close"] == 0.3 and dropped == []


PAIRS_HEADER = "pair_id,event_contract,expiration_date,quantity,yes_price,no_price,pair_time\n"


def test_late_pairs_rows_dropped_unparsed(tmp_path):
    body = (PAIRS_HEADER
            + "1,NYC_0915_80,2026-09-15,10,0.42,0.58,2026-09-14T15:00:00Z\n"
            + "2,NYC_1001_80,2026-10-01,10,GARBAGE,0.5,2026-09-14T15:00:00Z\n"
            + "3,NYC_0929_80,2026-09-29,10,GARBAGE,0.5,2026-09-30T04:00:00Z\n").encode()
    rows = make(tmp_path, FakeTransport(body=body)).fex_pairs(date(2026, 9, 14))
    assert rows == [{"event_contract": "NYC_0915_80", "expiration_date": "2026-09-15", "yes_price": 0.42,
                     "pair_time_utc": "2026-09-14T15:00:00+00:00"}]
    rec = receipts(tmp_path)[0]
    assert rec["n_dropped_late"] == 2 and [d["line"] for d in rec["dropped_late"]] == [3, 4]


def test_naive_or_bad_pair_time_refuses_file():
    naive = (PAIRS_HEADER + "1,X,2026-09-15,1,0.5,0.5,2026-09-14 15:00:00\n").encode()
    with pytest.raises(s31.FormatRefused):
        s31.parse_pairs(naive, s31.global_bound_utc())
    rows, _ = s31.parse_pairs(naive, s31.global_bound_utc(), pair_time_tz="America/Chicago")
    assert rows[0]["pair_time_utc"] == "2026-09-14T20:00:00+00:00"
    with pytest.raises(s31.FormatRefused):
        s31.parse_pairs((PAIRS_HEADER + "1,X,2026-09-15,1,0.5,0.5,yesterday\n").encode(), s31.global_bound_utc())
    with pytest.raises(s31.FormatRefused):
        s31.parse_pairs(b"a,b\n1,2\n", s31.global_bound_utc())


# --------------------------------------------------------------------------------------- allowlist drop

def test_markets_allowlist_a_drops_prices_and_results(tmp_path):
    market = {k: f"v_{k}" for k in s31.ALLOW_A}
    market.update(event_ticker=EVENT, last_price=55, result="yes", volume=1234, yes_bid=40, settlement_value=1)
    rows = make(tmp_path, FakeTransport(body=json.dumps({"markets": [market]}).encode())).kalshi_markets(EVENT)
    assert set(rows[0]) == set(s31.ALLOW_A)
    extract = (tmp_path / "out" / "v0_markets.jsonl").read_text(encoding="utf-8")
    for banned in ("last_price", "result", "volume", "settlement_value", "yes_bid"):
        assert banned not in extract


def test_candle_and_pairs_extracts_keep_only_allowlists():
    body = json.dumps({"candlesticks": [{"end_period_ts": 1, "yes_bid": {"close_dollars": "0.1", "open_dollars": "0.2"},
                                          "yes_ask": {"close_dollars": "0.2"}, "price": {"close_dollars": "0.15"},
                                          "volume_fp": "9", "open_interest_fp": "3"}]})
    rows, _ = s31.parse_candles(body.encode(), MARKET, 10)
    assert set(rows[0]) == {"ticker", *s31.ALLOW_B}
    pairs, _ = s31.parse_pairs((PAIRS_HEADER + "1,X,2026-09-15,7,0.5,0.5,2026-09-14T15:00:00Z\n").encode(),
                               s31.global_bound_utc())
    assert set(pairs[0]) == {"event_contract", "expiration_date", "yes_price", "pair_time_utc"}


# ------------------------------------------------------------------------------------------------ no auth

@pytest.mark.parametrize("status", [401, 403])
def test_auth_status_stops(tmp_path, status):
    fetcher = make(tmp_path, FakeTransport(status=status, body=b'{"error": "unauthorized"}'))
    with pytest.raises(s31.AuthRequired):
        fetcher.kalshi_markets(EVENT)
    assert receipts(tmp_path)[0]["stop"] == "auth_required"


def test_only_ua_and_accept_headers_sent(tmp_path):
    fake = FakeTransport(body=b'{"markets": []}')
    make(tmp_path, fake).kalshi_markets(EVENT)
    headers = fake.calls[0][1]
    assert set(headers) == {"User-Agent", "Accept"}
    assert not any(h.lower() in ("authorization", "cookie") or h.lower().startswith("kalshi-access") for h in headers)


@pytest.mark.parametrize("url", [
    "https://kalshi.com/markets/kxhighny",
    "https://api.elections.kalshi.com/trade-api/v2/portfolio/balance",
    "http://api.elections.kalshi.com/trade-api/v2/markets",
    "https://forecastex.com/",
    "https://forecastex-public-data.s3.amazonaws.com/other/x.csv",
    "https://user:pw@api.elections.kalshi.com/trade-api/v2/markets",
])
def test_non_allowlisted_url_refused_before_transport(tmp_path, url):
    fake = FakeTransport()
    with pytest.raises(s31.EndpointRefused):
        make(tmp_path, fake).get(url, "x")
    assert fake.calls == []


def test_default_transport_refuses_network(tmp_path):
    fetcher = s31.Fetcher(tmp_path / "out", tmp_path / "archive",
                          limiter=s31.RateLimiter(clock=lambda: 0.0, sleep=lambda s: None))
    with pytest.raises(RuntimeError, match="network disabled"):
        fetcher.kalshi_markets(EVENT)


# --------------------------------------------------------------------------------- writes, archive, rate

def test_out_and_archive_must_not_nest(tmp_path):
    with pytest.raises(ValueError):
        s31.Fetcher(tmp_path / "a" / "out", tmp_path / "a", transport=FakeTransport())
    with pytest.raises(ValueError):
        s31.Fetcher(tmp_path / "o", tmp_path / "o" / "arch", transport=FakeTransport())


def test_writes_only_under_out_and_archive_exclusive(tmp_path):
    fetcher = make(tmp_path, FakeTransport(body=b'{"markets": []}'))
    with pytest.raises(ValueError):
        fetcher._out_path("../escape.jsonl")
    fetcher.kalshi_markets(EVENT)
    archived = receipts(tmp_path)[0]["archive"]
    assert archived.startswith(str(tmp_path / "archive" / "raw" / "t"))
    fetcher._seq -= 1  # force a name collision: the archive must refuse to overwrite
    with pytest.raises(FileExistsError):
        fetcher._archive(f"markets_{EVENT}.json", b"other", quarantine=False)
    created = {p.relative_to(tmp_path).parts[0] for p in tmp_path.rglob("*") if p.is_file()}
    assert created == {"out", "archive"}


def test_rate_limiter_spaces_one_second():
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s

    limiter = s31.RateLimiter(clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    now[0] += 0.25
    limiter.wait()
    assert slept == [pytest.approx(0.75)]
    with pytest.raises(ValueError):
        s31.RateLimiter(min_interval=0.5)
