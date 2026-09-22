"""Deterministic measurement checks; no external calls or runtime state reads."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("truth86a", Path(__file__).with_name("settlement_truth_source_20260922.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize("band,value,expected", [
    ("90-91 F", 89, False), ("90-91 F", 91, True),
    ("-5--4 C", -4, True), ("25 C or below", 25, True),
    ("25 C or higher", 26, True), ("25°C", 26, False),
    ("", 23, None), ("25 C", None, None),
])
def test_band(band, value, expected):
    assert m.band_contains(band, value) is expected


def test_local_day_and_dst():
    spec = m.spec_for_id("nyc")
    start, end = m.boundaries(spec, date(2026, 3, 8), date(2026, 3, 8))
    assert (end-start).total_seconds() == 23*3600
    assert start.hour == 5 and end.hour == 4


def test_hourly_filter_toronto_is_not_us():
    toronto = m.spec_for_id("toronto")
    assert m.is_hourly(toronto, 0) and m.is_hourly(toronto, 56)
    assert not m.is_hourly(toronto, 51)


class FixtureCache:
    def __init__(self, bodies):
        self.bodies = iter(bodies)

    def get(self, url, params=None):
        return next(self.bodies), {"status": 200, "url": url, "sha256": "fixture"}


def test_one_minute_header_local_cutoff_and_half_up():
    raw = ("station,valid(Etc/UTC),tmpf\n"
           "LGA,2026-07-01 03:59,120\n"
           "LGA,2026-07-01 04:00,80\n"
           "LGA,2026-07-02 03:59,81.5\n"
           "LGA,2026-07-02 04:00,130\n").encode()
    got = m.series("asos", m.spec_for_id("nyc"), date(2026,7,1), date(2026,7,1), FixtureCache([raw]))
    assert got["days"]["2026-07-01"]["degree"] == 82
    assert got["days"]["2026-07-01"]["samples"] == 2


def test_six_hour_window_excludes_previous_local_date():
    raw = ("station,valid,tmpc,metar\n"
           "LGA,2026-07-01 05:51,20,METAR KLGA RMK AO2 10400\n"
           "LGA,2026-07-01 17:51,20,METAR KLGA RMK AO2 10250\n").encode()
    got = m.series("metar", m.spec_for_id("nyc"), date(2026,7,1), date(2026,7,1), FixtureCache([raw]))
    day = got["days"]["2026-07-01"]
    assert day["degree"] == 68
    assert day["with_6h_degree"] == 77
    assert day["contained_6h_count"] == 1
    assert day["cross_midnight_6h_excluded"] == 1


def test_batch_station_rows_cannot_cross_markets():
    raw = ("station,valid(Etc/UTC),tmpf\nLGA,2026-07-01 04:00,80\n"
           "MIA,2026-07-01 04:00,110\n").encode()
    got = m.series("asos", m.spec_for_id("nyc"), date(2026,7,1), date(2026,7,1), FixtureCache([raw]),
                   [m.spec_for_id("nyc"), m.spec_for_id("miami")])
    assert got["days"]["2026-07-01"]["degree"] == 80


def test_crossed_delta_keeps_paired_sign():
    rows = [{"market": market, "date": day, "venue_band": "80-81 F", "wu": 80, "metar": 82}
            for market in ("nyc", "miami") for day in ("2026-07-01", "2026-07-02")]
    got = m.crossed_delta(rows, "metar")
    assert got["delta"] == -1
    assert got["exploratory_95_ci"] == [-1, -1]


def observation(stamp, value):
    return {"properties": {"timestamp": stamp, "temperature": {"value": value, "unitCode": "wmoUnit:degC", "qualityControl": "V"}}}


def test_nws_pagination_and_hourly_filter():
    first = {"features": [observation("2026-09-21T20:51:00Z", 25), observation("2026-09-21T20:40:00Z", 30)],
             "pagination": {"next": "https://api.weather.gov/stations/KLGA/observations?cursor=x"}}
    second = {"features": [observation("2026-09-21T03:51:00Z", 40)]}
    cache = FixtureCache([m.json.dumps(first).encode(), m.json.dumps(second).encode()])
    got = m.series("nws", m.spec_for_id("nyc"), date(2026,9,21), date(2026,9,21), cache)
    day = got["days"]["2026-09-21"]
    assert day["degree"] == 86 and day["hourly_degree"] == 77
    assert day["samples"] == 2


def test_cache_fails_closed_offline_and_for_unknown_host(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="uncached"):
        m.Cache().get("https://api.weather.gov/stations/KLGA/observations")
    with pytest.raises(ValueError, match="allowlisted"):
        m.Cache(True).get("https://example.com")


def test_cache_stop_prevents_network(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    (tmp_path / "STOP").write_text("owner starting live")
    with pytest.raises(SystemExit, match="STOP"):
        m.Cache(True).get("https://api.weather.gov/stations/KLGA/observations")


def test_cache_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    url = "https://api.weather.gov/stations/KLGA/observations"
    key = m.sha(url.encode())
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / (key+".body")).write_bytes(b"changed")
    m.dump(tmp_path / "cache" / (key+".json"), {"sha256": m.sha(b"original")})
    with pytest.raises(ValueError, match="hash mismatch"):
        m.Cache().get(url)
