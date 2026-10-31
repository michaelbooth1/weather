"""Synthetic tests for the S31 venue fetch guards (no network; every transport is a fake)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

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


SPEC_LINE = "Region NYC: New York City, LaGuardia Airport station KLGA\n"


def confirm_nyc(tmp_path, fetcher, line=SPEC_LINE):
    """Write an archived filing-text fixture and run the V0.3 station pre-step for NYC."""
    spec = tmp_path / "forecastex" / "cftc" / "ptc_fixture.txt"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(line, encoding="utf-8")
    return fetcher.fex_stations([str(spec)], [{"city": "NYC", "region": "NYC", "station": "KLGA"}])


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
            + "1,UHNYC_20260915_80,2026-09-15,10,0.42,0.58,2026-09-14T15:00:00Z\n"
            + "2,UHNYC_20261001_80,2026-10-01,10,GARBAGE,0.5,2026-09-14T15:00:00Z\n"
            + "3,UHNYC_20260929_80,2026-09-29,10,GARBAGE,0.5,2026-09-30T04:00:00Z\n").encode()
    fetcher = make(tmp_path, FakeTransport(body=body))
    confirm_nyc(tmp_path, fetcher)
    rows = fetcher.fex_pairs(date(2026, 9, 14))
    assert rows == [{"event_contract": "UHNYC_20260915_80", "expiration_date": "2026-09-15", "yes_price": 0.42,
                     "pair_time_utc": "2026-09-14T15:00:00+00:00"}]
    rec = receipts(tmp_path)[-1]
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


# ------------------------------------------------------------- master F5: global bound and series zones

def test_global_bound_constant_is_earliest_city_end():
    assert s31.GLOBAL_BOUND_UTC == datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)
    assert s31.global_bound_utc() == s31.GLOBAL_BOUND_UTC
    assert set(s31.SERIES_TZ.values()) <= s31.TIMEZONES


@pytest.mark.parametrize("tz", ["America/Chicago", "America/Denver", "America/Los_Angeles"])
def test_wrong_declared_tz_cannot_extend_past_global_bound(tz):
    # A New York market mis-declared as a western zone would otherwise end up to 3 h into local 09-30.
    win = s31.candle_window(date(2026, 9, 29), tz)
    assert win.end_utc == s31.GLOBAL_BOUND_UTC


def test_wrong_declared_tz_for_series_refused_before_request(tmp_path):
    fake = FakeTransport(body=b'{"candlesticks": []}')
    fetcher = make(tmp_path, fake)
    with pytest.raises(s31.SeriesRefused):
        fetcher.kalshi_candles(SERIES, "KXHIGHNY-26SEP29-B72.5", "America/Los_Angeles", "live")
    with pytest.raises(s31.SeriesRefused):
        fetcher.kalshi_candles("KXHIGHLAX", MARKET, "America/Los_Angeles", "historical")
    with pytest.raises(s31.SeriesRefused):
        fetcher.kalshi_candles("KXHIGHOTHER", "KXHIGHOTHER-26SEP15-B70", TZ, "live")
    with pytest.raises(s31.SeriesRefused):
        fetcher.kalshi_markets("KXHIGHTCYYZ-26SEP15")
    assert fake.calls == []
    assert issubclass(s31.SeriesRefused, s31.WindowRefused)


def test_correct_series_tz_late_city_still_ends_at_global_bound(tmp_path):
    fake = FakeTransport(body=b'{"candlesticks": []}')
    make(tmp_path, fake).kalshi_candles("KXHIGHLAX", "KXHIGHLAX-26SEP29-B80.5", "America/Los_Angeles", "live")
    assert f"end_ts={int(s31.GLOBAL_BOUND_UTC.timestamp()) - 1}" in fake.calls[0][0]
    assert receipts(tmp_path)[0]["window_end"] == "2026-09-30T04:00:00+00:00"


# ------------------------------------------------------ master F6: refused bodies archived and receipted

@pytest.mark.parametrize("call,body", [
    ("markets", b"not json at all"),
    ("candles", b'{"candlesticks": [truncated'),
    ("pairs", b"a,b\n1,2\n"),
    ("pairs", b"\xff\xfe\x00bad-utf8"),
])
def test_refused_body_quarantined_and_receipted(tmp_path, call, body):
    fetcher = make(tmp_path, FakeTransport(body=body))
    if call == "pairs":
        confirm_nyc(tmp_path, fetcher)
    with pytest.raises(s31.FormatRefused):
        if call == "markets":
            fetcher.kalshi_markets(EVENT)
        elif call == "candles":
            fetcher.kalshi_candles(SERIES, MARKET, TZ, "live")
        else:
            fetcher.fex_pairs(date(2026, 9, 14))
    rec = receipts(tmp_path)[-1]
    assert rec["stop"] == "format_refused" and rec["refused"]
    assert "_quarantine_refused" in rec["archive"]
    assert rec["archive"].startswith(str(tmp_path / "archive" / "raw" / "t" / "_quarantine_refused"))
    assert Path(rec["archive"]).read_bytes() == body
    assert rec["raw_sha256"] == s31.sha256_bytes(body)


def test_main_returns_refused_on_json_decode_error(tmp_path, monkeypatch, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"kind": "kalshi_markets", "event_ticker": EVENT}]), encoding="utf-8")
    monkeypatch.setattr(s31, "refuse_network", FakeTransport(body=b"<html>not json</html>"))
    code = s31.main(["--plan", str(plan), "--out", str(tmp_path / "out"), "--archive-root", str(tmp_path / "archive")])
    assert code == 2
    assert "REFUSED" in capsys.readouterr().err
    assert receipts(tmp_path)[0]["stop"] == "format_refused"


def test_main_refuses_bad_plan_json(tmp_path, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text("[{not json", encoding="utf-8")
    assert s31.main(["--plan", str(plan), "--out", str(tmp_path / "out"), "--archive-root", str(tmp_path / "a")]) == 2
    assert "REFUSED" in capsys.readouterr().err


# ------------------------------------------------------- master F8: naive pair_time under a wrong zone

def test_naive_pair_time_declared_et_past_bound_on_pacific_reading_dropped():
    # 22:00 naive read as ET is 02:00Z (inside the bound); read as Pacific it is 05:00Z (past it): dropped.
    body = (PAIRS_HEADER + "1,NYC_0929_80,2026-09-29,1,GARBAGE,0.5,2026-09-29T22:00\n").encode()
    rows, dropped = s31.parse_pairs(body, s31.GLOBAL_BOUND_UTC, pair_time_tz="America/New_York")
    assert rows == []
    assert dropped == [{"line": 2, "expiration_date": "2026-09-29",
                        "pair_time_utc": "2026-09-30T02:00:00+00:00",
                        "pair_time_utc_conservative": "2026-09-30T05:00:00+00:00"}]


def test_naive_pair_time_records_both_readings_when_kept():
    body = (PAIRS_HEADER + "1,NYC_0929_80,2026-09-29,1,0.5,0.5,2026-09-29T20:00\n").encode()
    rows, dropped = s31.parse_pairs(body, s31.GLOBAL_BOUND_UTC, pair_time_tz="America/New_York")
    assert dropped == []
    assert rows[0]["pair_time_utc"] == "2026-09-30T00:00:00+00:00"
    assert rows[0]["pair_time_utc_conservative"] == "2026-09-30T03:00:00+00:00"
    aware, conservative = s31.parse_pair_time("2026-09-29T20:00:00Z", "America/New_York")
    assert aware == conservative == datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)


# ---------------------------------------------- master ruling (a): pre-cutoff Kalshi jobs (Clarification 4)

HIST_EVENT = "KXHIGHNY-26AUG10"
META_BODY = json.dumps({"competition": "c", "image_url": "i", "settlement_sources": [{"name": "n", "url": "u"}],
                        "market_details": [{"market_ticker": f"{HIST_EVENT}-B72.5", "color_code": "x",
                                            "image_url": "y"}]}).encode()


@pytest.mark.parametrize("call", ["meta", "hist_markets"])
@pytest.mark.parametrize("ticker", ["KXHIGHNY-26SEP30", "KXHIGHNY-26JUL31", "KXHIGHTCYYZ-26AUG10", "KXHIGHNY"])
def test_new_kalshi_jobs_refuse_bound_before_request(tmp_path, call, ticker):
    fake = FakeTransport(body=META_BODY)
    fetcher = make(tmp_path, fake)
    with pytest.raises(s31.WindowRefused):
        (fetcher.kalshi_event_metadata if call == "meta" else fetcher.kalshi_historical_markets)(ticker)
    assert fake.calls == []


def test_event_metadata_allowlist_m_keeps_tickers_only(tmp_path):
    fake = FakeTransport(body=META_BODY)
    rows = make(tmp_path, fake).kalshi_event_metadata(HIST_EVENT)
    assert fake.calls[0][0] == f"https://{s31.KALSHI_HOST}/trade-api/v2/events/{HIST_EVENT}/metadata"
    assert rows == [{"event_ticker": HIST_EVENT, "market_ticker": f"{HIST_EVENT}-B72.5"}]
    extract = (tmp_path / "out" / "event_markets.jsonl").read_text(encoding="utf-8")
    for banned in ("settlement_sources", "color_code", "image_url", "competition"):
        assert banned not in extract
    with pytest.raises(s31.FormatRefused):
        s31.parse_event_metadata(json.dumps({"market_details": [{"market_ticker": "KXHIGHNY-26AUG11-B70"}]}).encode(),
                                 HIST_EVENT)


def test_historical_markets_exact_path_and_allowlist_a(tmp_path):
    market = {k: f"v_{k}" for k in s31.ALLOW_A}
    market.update(event_ticker=HIST_EVENT, last_price=55, result="yes", volume=9, settlement_value=1,
                  expiration_value="80")
    fake = FakeTransport(body=json.dumps({"markets": [market], "cursor": ""}).encode())
    rows = make(tmp_path, fake).kalshi_historical_markets(HIST_EVENT)
    assert fake.calls[0][0].startswith(f"https://{s31.KALSHI_HOST}/trade-api/v2/historical/markets?")
    assert set(rows[0]) == set(s31.ALLOW_A)
    extract = (tmp_path / "out" / "v0_markets_hist.jsonl").read_text(encoding="utf-8")
    for banned in ("last_price", "result", "volume", "settlement_value", "expiration_value"):
        assert banned not in extract


@pytest.mark.parametrize("url", [
    "https://api.elections.kalshi.com/trade-api/v2/historical/trades",
    "https://api.elections.kalshi.com/trade-api/v2/historical/markets/KXHIGHNY-26AUG10-B72.5",
    "https://api.elections.kalshi.com/trade-api/v2/historical/fills",
    "https://api.elections.kalshi.com/trade-api/v2/historical/markets/x/y",
])
def test_only_exact_historical_paths_allowlisted(tmp_path, url):
    fake = FakeTransport()
    with pytest.raises(s31.EndpointRefused):
        make(tmp_path, fake).get(url, "x")
    assert fake.calls == []


def test_historical_candles_bound_late_drop_and_cutoff(tmp_path):
    market = f"{HIST_EVENT}-B72.5"
    win = s31.candle_window(date(2026, 8, 10), TZ)
    body = json.dumps({"candlesticks": [
        {"end_period_ts": win.end_ts - 60, "yes_bid": {"close": 0.3}, "yes_ask": {"close": 0.4}},
        {"end_period_ts": win.end_ts, "yes_bid": {"close": "GARBAGE"}}]}).encode()
    fake = FakeTransport(body=body)
    fetcher = make(tmp_path, fake)
    rows = fetcher.kalshi_candles(SERIES, market, TZ, "historical")
    assert "/trade-api/v2/historical/markets/" in fake.calls[0][0] and len(rows) == 1
    rec = receipts(tmp_path)[-1]
    assert rec["n_dropped_late"] == 1 and "_quarantine_late" in rec["archive"]
    with pytest.raises(s31.WindowRefused):  # a window starting after the cutoff is never historical-tier
        fetcher.kalshi_candles(SERIES, "KXHIGHNY-26SEP15-B72.5", TZ, "historical")
    with pytest.raises(s31.WindowRefused):
        fetcher.kalshi_candles(SERIES, "KXHIGHNY-26SEP30-B72.5", TZ, "historical")
    assert len(fake.calls) == 1


@pytest.mark.parametrize("call", ["meta", "hist_markets", "hist_candles"])
def test_new_kalshi_jobs_auth_stop(tmp_path, call):
    fetcher = make(tmp_path, FakeTransport(status=403, body=b'{"error": "unauthorized"}'))
    with pytest.raises(s31.AuthRequired):
        if call == "meta":
            fetcher.kalshi_event_metadata(HIST_EVENT)
        elif call == "hist_markets":
            fetcher.kalshi_historical_markets(HIST_EVENT)
        else:
            fetcher.kalshi_candles(SERIES, f"{HIST_EVENT}-B72.5", TZ, "historical")
    rec = receipts(tmp_path)[-1]
    assert rec["stop"] == "auth_required" and rec["complete"] is False


@pytest.mark.parametrize("call", ["meta", "hist_markets"])
def test_new_kalshi_jobs_archive_exclusive_create(tmp_path, call):
    body = META_BODY if call == "meta" else b'{"markets": []}'
    fetcher = make(tmp_path, FakeTransport(body=body))
    (fetcher.kalshi_event_metadata if call == "meta" else fetcher.kalshi_historical_markets)(HIST_EVENT)
    archived = Path(receipts(tmp_path)[-1]["archive"])
    assert archived.read_bytes() == body and archived.is_relative_to(tmp_path / "archive" / "raw" / "t")
    fetcher._seq -= 1
    with pytest.raises(FileExistsError):
        fetcher._archive(archived.name.split("_", 1)[1], b"other", quarantine=False)
    assert archived.read_bytes() == body


def test_http_429_stops_and_leaves_job_incomplete(tmp_path):
    fetcher = make(tmp_path, FakeTransport(status=429, body=b"slow down"))
    with pytest.raises(s31.HttpStop):
        fetcher.kalshi_event_metadata(HIST_EVENT)
    assert receipts(tmp_path)[-1]["complete"] is False


# ------------------------------------------------------------------------------ resume (Clarification 4)

def _resumer(tmp_path, transport, run_id):
    limiter = s31.RateLimiter(clock=lambda: 0.0, sleep=lambda s: None)
    return s31.Fetcher(tmp_path / "out", tmp_path / "archive", transport=transport, limiter=limiter, run_id=run_id)


def test_resume_skips_completed_jobs_new_run_folder(tmp_path):
    jobs = [{"kind": "kalshi_event_metadata", "event_ticker": HIST_EVENT},
            {"kind": "kalshi_markets", "event_ticker": EVENT}]
    first = FakeTransport(body=META_BODY)
    s31.run_plan(_resumer(tmp_path, first, "r1"), jobs[:1])
    second = FakeTransport(body=b'{"markets": []}')
    summary = s31.run_plan(_resumer(tmp_path, second, "r2"), jobs)
    assert len(first.calls) == 1 and len(second.calls) == 1 and "/markets?" in second.calls[0][0]
    assert summary["skipped_done"] == 1 and summary["run"] == 1
    assert (tmp_path / "archive" / "raw" / "r1").is_dir() and (tmp_path / "archive" / "raw" / "r2").is_dir()
    with pytest.raises(ValueError):  # a used run_id is never reused
        _resumer(tmp_path, second, "r1")


def test_resume_refetches_partial_job_whole_and_records_it(tmp_path, monkeypatch):
    fetcher = _resumer(tmp_path, FakeTransport(body=META_BODY), "r1")

    def crash(*args, **kwargs):  # the run dies after the request, before the receipt
        raise KeyboardInterrupt

    monkeypatch.setattr(fetcher, "finish", crash)
    with pytest.raises(KeyboardInterrupt):
        fetcher.kalshi_event_metadata(HIST_EVENT)
    (tmp_path / "out" / "event_markets.jsonl").write_text(
        json.dumps({"event_ticker": HIST_EVENT, "market_ticker": "stale", "job": f"event_meta:{HIST_EVENT}",
                    "run_id": "r1"}) + "\n", encoding="utf-8")  # a partial extract row left by the dead run
    again = FakeTransport(body=META_BODY)
    summary = s31.run_plan(_resumer(tmp_path, again, "r2"),
                           [{"kind": "kalshi_event_metadata", "event_ticker": HIST_EVENT}])
    assert summary["run"] == 1 and len(again.calls) == 1
    rec = receipts(tmp_path)[-1]
    assert rec["refetched_after_partial"] == ["r1"] and rec["complete"] is True
    rows = s31.load_extract(tmp_path / "out", "event_markets.jsonl")
    assert [r["market_ticker"] for r in rows] == [f"{HIST_EVENT}-B72.5"] and rows[0]["run_id"] == "r2"


# ---------------------------------------------------------- master ruling (c): ForecastEx staging

GOOD_PAIRS = (PAIRS_HEADER
              + "1,UHNYC_20260915_80,2026-09-15,10,0.42,0.58,2026-09-14T15:00:00Z\n"
              + "2,UHCHI_20260915_80,GARBAGE,10,GARBAGE,0.5,GARBAGE\n"
              + "3,ULNYC_20260915_60,GARBAGE,10,GARBAGE,0.5,GARBAGE\n"
              + "4,odd-contract,GARBAGE,10,GARBAGE,0.5,GARBAGE\n").encode()


def test_pairs_refused_before_station_receipt_exists(tmp_path):
    fake = FakeTransport(body=GOOD_PAIRS)
    fetcher = make(tmp_path, fake)
    with pytest.raises(s31.OrderRefused):
        fetcher.fex_pairs(date(2026, 9, 14))
    assert fake.calls == [] and not (tmp_path / "out" / "receipts.jsonl").exists()


def test_station_prestep_unconfirmed_city_blocks_pairs(tmp_path):
    fake = FakeTransport(body=GOOD_PAIRS)
    fetcher = make(tmp_path, fake)
    payload = confirm_nyc(tmp_path, fetcher, line="Region NYC: New York City (station not named)\n")
    assert payload["confirmed_regions"] == {} and payload["claims"][0]["found_in"] is None
    assert payload["sources"][0]["sha256"]
    with pytest.raises(s31.OrderRefused):
        fetcher.fex_pairs(date(2026, 9, 14))
    assert fake.calls == []
    with pytest.raises(s31.OrderRefused):  # the station receipt is never rewritten
        confirm_nyc(tmp_path, fetcher)


@pytest.mark.parametrize("name", ["notices_to_members_x.txt", "forecastex_markets.html", "ptc.pdf"])
def test_station_prestep_reads_only_archived_filing_text(tmp_path, name):
    bad = tmp_path / "forecastex" / name
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(SPEC_LINE, encoding="utf-8")
    claim = [{"city": "NYC", "region": "NYC", "station": "KLGA"}]
    with pytest.raises(s31.EndpointRefused):
        make(tmp_path, FakeTransport()).fex_stations([str(bad)], claim)
    outside = tmp_path / "elsewhere" / "ptc_x.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text(SPEC_LINE, encoding="utf-8")
    with pytest.raises(s31.EndpointRefused):
        s31.Fetcher(tmp_path / "out2", tmp_path / "archive", transport=FakeTransport(),
                    run_id="t2").fex_stations([str(outside)], claim)
    assert not (tmp_path / "out" / "fex_stations.json").exists()


def test_station_prestep_different_station_not_confirmed(tmp_path):
    fetcher = make(tmp_path, FakeTransport())
    spec = tmp_path / "forecastex" / "ptc_x.txt"
    spec.parent.mkdir(parents=True)
    spec.write_text("Region NYC station KJFK\n", encoding="utf-8")
    payload = fetcher.fex_stations([str(spec)], [{"city": "NYC", "region": "NYC", "station": "KJFK"}])
    assert payload["claims"][0]["found_in"] and payload["claims"][0]["confirmed"] is False


def test_city_filter_drops_non_twin_rows_unparsed(tmp_path):
    fetcher = make(tmp_path, FakeTransport(body=GOOD_PAIRS))
    confirm_nyc(tmp_path, fetcher)
    rows = fetcher.fex_pairs(date(2026, 9, 14))  # GARBAGE fields in non-twin rows would raise if parsed
    assert [r["event_contract"] for r in rows] == ["UHNYC_20260915_80"]
    rec = receipts(tmp_path)[-1]
    assert rec["n_dropped_non_twin"] == 2 and rec["n_dropped_undecodable"] == 1
    extract = (tmp_path / "out" / "fex_pairs.jsonl").read_text(encoding="utf-8")
    assert "UHCHI" not in extract and "ULNYC" not in extract
    v04 = json.loads((tmp_path / "out" / "fex_v04.json").read_text(encoding="utf-8"))
    assert v04["passed"] is True and v04["pair_time_zone"] == "explicit" and v04["first_region"] == "NYC"


@pytest.mark.parametrize("first_row", [
    "1,UHNYC_20260915_80,2026-09-15,1,0.5,0.5,2026-09-14\n",          # no minute resolution
    "1,UHNYC_20260915_80,2026-09-15,1,0.5,0.5,2026-09-14T15:00:00\n",  # naive, no documented zone
    "1,NYC-SEP15-80,2026-09-15,1,0.5,0.5,2026-09-14T15:00:00Z\n",      # event_contract does not decode
])
def test_v04_refuses_file_and_fex_lineage(tmp_path, first_row):
    body = (PAIRS_HEADER + first_row).encode()
    fake = FakeTransport(body=body)
    fetcher = make(tmp_path, fake)
    confirm_nyc(tmp_path, fetcher)
    with pytest.raises(s31.FormatRefused):
        fetcher.fex_pairs(date(2026, 9, 14))
    rec = receipts(tmp_path)[-1]
    assert rec["stop"] == "format_refused" and "_quarantine_refused" in rec["archive"]
    assert not (tmp_path / "out" / "fex_pairs.jsonl").exists()
    assert json.loads((tmp_path / "out" / "fex_v04.json").read_text(encoding="utf-8"))["passed"] is False
    with pytest.raises(s31.OrderRefused):  # later files are refused before any request
        fetcher.fex_pairs(date(2026, 9, 15))
    assert len(fake.calls) == 1


def test_v04_per_row_bound_check_still_applies(tmp_path):
    body = (PAIRS_HEADER + "1,UHNYC_20260929_80,2026-09-29,1,0.5,0.5,2026-09-29T20:00:00\n"
            + "2,UHNYC_20260929_81,2026-09-29,1,GARBAGE,0.5,2026-09-29T22:00:00\n").encode()
    fetcher = make(tmp_path, FakeTransport(body=body))
    confirm_nyc(tmp_path, fetcher)
    rows = fetcher.fex_pairs(date(2026, 9, 29), pair_time_tz="America/New_York")
    assert [r["event_contract"] for r in rows] == ["UHNYC_20260929_80"]
    assert receipts(tmp_path)[-1]["n_dropped_late"] == 1
