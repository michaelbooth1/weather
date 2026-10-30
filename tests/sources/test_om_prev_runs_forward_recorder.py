"""Lane L8 Open-Meteo Previous Runs forward recorder (tools/research/om_prev_runs_forward_recorder.py).

Guards: ledger row 81 (Previous Runs drift UNTESTABLE for lack of a receipt), covering:
- the URL allowlist: only GET of the fixed query on previous-runs-api.open-meteo.com, at registry coordinates,
  with no key, credentials, extra parameter or other host;
- the per-market settlement unit;
- the parser's usable/unusable verdicts;
- verbatim body plus response_sha256 and a fetched_at_utc receipt read after the body;
- one fsynced cycle append with rows_sha256, and complete/incomplete cycles with reasons;
- the HH:20-HH:50 window and once-per-slot rule, missed slots recorded as gaps, and the day manifest;
- the pause and STOP files.

No network: an in-memory fake serves replies.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys

import pytest

from weather.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("om_prev_runs_forward_recorder",
                                               REPO_ROOT / "tools/research/om_prev_runs_forward_recorder.py")
rc = importlib.util.module_from_spec(_spec)
sys.modules["om_prev_runs_forward_recorder"] = rc
_spec.loader.exec_module(rc)

UTC = dt.timezone.utc
MARKETS = {"toronto": {"icao": "CYYZ", "lat": 43.6767, "lon": -79.6306, "unit": "C", "tz": "America/Toronto"},
           "nyc": {"icao": "KLGA", "lat": 40.7769, "lon": -73.874, "unit": "F", "tz": "America/New_York"}}
ALLOWED = {(rc.coord(m["lat"]), rc.coord(m["lon"])) for m in MARKETS.values()}
HOURS = 24 * (rc.PAST_DAYS + rc.FORECAST_DAYS)


def reply(unit="°F", drop=(), short=(), all_null=False, offset=0, error=None):
    if error:
        return json.dumps({"error": True, "reason": error}).encode()
    t0 = dt.datetime(2026, 10, 29, tzinfo=UTC)
    times = [(t0 + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(HOURS)]
    hourly = {"time": times}
    for name in rc.series_names():
        if name in drop:
            continue
        n = HOURS - 1 if name in short else HOURS
        hourly[name] = [None] * n if all_null else [50.0 + (i % 7) * 0.5 for i in range(n)]
    return json.dumps({"latitude": 40.77, "longitude": -73.87, "elevation": 3.0, "generationtime_ms": 2.5,
                       "utc_offset_seconds": offset, "timezone": "GMT",
                       "hourly_units": {"time": "iso8601", **{n: unit for n in hourly if n != "time"}},
                       "hourly": hourly}).encode("utf-8")


class Fake:
    def __init__(self, bodies=None, status=200, fail=()):
        self.bodies, self.status, self.fail = bodies or {}, status, set(fail)
        self.calls, self.used, self.requests = [], 0, 0

    def request(self, method, url):
        rc.check_url(method, url, ALLOWED)
        self.calls.append(url)
        self.requests += 1
        lat = dict(rc.parse_qsl(rc.urlsplit(url).query))["latitude"]
        if lat in self.fail:
            raise OSError("boom")
        body = self.bodies.get(lat, reply())
        self.used += len(body)
        return rc.Resp(self.status, body, {"Date": "Fri, 30 Oct 2026 20:20:05 GMT"})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp_path, fake=None, t=dt.datetime(2026, 10, 30, 20, 25, tzinfo=UTC), **kw):
    clock = Clock(t)
    rec = rc.Recorder(tmp_path / "out", fake or Fake(), markets=MARKETS, clock=clock, sleep=lambda s: None,
                      min_free_gb=0.0, **kw)
    return rec, clock


def lines(rec, day="20261030"):
    return rc.read_jsonl(rec.out / day / "prev_runs.jsonl")


# --------------------------------------------------------------------------- URL allowlist
def test_url_for_is_allowlisted_and_carries_the_fixed_query():
    url = rc.url_for(40.7769, -73.874, "F")
    rc.check_url("GET", url, ALLOWED)
    q = dict(rc.parse_qsl(rc.urlsplit(url).query))
    assert q["hourly"].split(",") == ["temperature_2m"] + [f"temperature_2m_previous_day{n}" for n in range(1, 8)]
    assert q["models"].split(",") == ["best_match", "gfs_seamless", "gfs_global", "ncep_hrrr_conus",
                                      "ncep_nbm_conus", "ecmwf_ifs025", "gem_seamless"]
    assert (q["temperature_unit"], q["timezone"], q["past_days"], q["forecast_days"]) == ("fahrenheit", "GMT", "2", "3")
    assert dict(rc.parse_qsl(rc.urlsplit(rc.url_for(43.6767, -79.6306, "C")).query))["temperature_unit"] == "celsius"


def _swap(url, key, value):
    pairs = [(k, value if k == key else v) for k, v in rc.parse_qsl(rc.urlsplit(url).query)]
    return f"https://{rc.HOST}{rc.PATH}?{rc.urlencode(pairs, safe=',')}"


@pytest.mark.parametrize("mutate", [
    lambda u: u.replace("https://", "http://"),
    lambda u: u.replace(rc.HOST, "api.open-meteo.com"),
    lambda u: u.replace(rc.HOST, rc.HOST + ":8443"),
    lambda u: u.replace("https://", "https://user:pw@"),
    lambda u: u.replace(rc.PATH, "/v1/archive"),
    lambda u: u + "&apikey=abc",
    lambda u: u + "#frag",
    lambda u: u.split("?")[0],
    lambda u: _swap(u, "models", "best_match"),
    lambda u: _swap(u, "hourly", "temperature_2m,precipitation"),
    lambda u: _swap(u, "past_days", "92"),
    lambda u: _swap(u, "temperature_unit", "kelvin"),
    lambda u: _swap(u, "timezone", "auto"),
    lambda u: _swap(u, "latitude", "40.7769"),
    lambda u: _swap(u, "latitude", "40.00000"),
])
def test_check_url_refuses_anything_else(mutate):
    url = rc.url_for(40.7769, -73.874, "F")
    with pytest.raises(rc.Refused):
        rc.check_url("GET", mutate(url), ALLOWED)


def test_check_url_refuses_post_and_reordered_keys():
    url = rc.url_for(40.7769, -73.874, "F")
    with pytest.raises(rc.Refused):
        rc.check_url("POST", url, ALLOWED)
    pairs = rc.parse_qsl(rc.urlsplit(url).query)
    swapped = f"https://{rc.HOST}{rc.PATH}?{rc.urlencode(pairs[1:2] + pairs[:1] + pairs[2:], safe=',')}"
    with pytest.raises(rc.Refused):
        rc.check_url("GET", swapped, ALLOWED)


def test_check_url_without_registry_accepts_any_valid_coordinate_only():
    rc.check_url("GET", rc.url_for(10.5, 20.25, "C"))
    with pytest.raises(rc.Refused):
        rc.check_url("GET", rc.url_for(10.5, 20.25, "C"), ALLOWED)


def test_query_for_refuses_unknown_unit():
    with pytest.raises(ValueError):
        rc.query_for(1, 2, "K")


# --------------------------------------------------------------------------- parser
def test_parse_complete_reply():
    p = rc.parse_response(reply())
    assert p["ok"] and p["reason"] is None and p["n_times"] == HOURS
    assert p["series_present"] == len(rc.series_names()) == 7 * 8
    assert p["series_missing"] == [] and p["units"] == ["°F"]
    assert set(p["non_null"].values()) == {HOURS}


def test_parse_counts_nulls_but_one_all_null_series_is_still_usable():
    body = json.loads(reply())
    body["hourly"]["temperature_2m_previous_day7_ncep_hrrr_conus"] = [None] * HOURS
    p = rc.parse_response(json.dumps(body).encode())
    assert p["ok"] and p["non_null"]["temperature_2m_previous_day7_ncep_hrrr_conus"] == 0


@pytest.mark.parametrize("body,reason", [
    (b"not json", "bad_json"),
    (b"[1, 2]", "not_an_object"),
    (b'{"hourly": {}}', "no_hourly_time"),
    (reply(error="Cannot initialize"), "api_error"),
    (reply(drop=("temperature_2m_gem_seamless",)), "series_missing"),
    (reply(short=("temperature_2m_best_match",)), "series_bad_length"),
    (reply(offset=3600), "not_gmt"),
    (reply(all_null=True), "all_null"),
], ids=lambda v: v if isinstance(v, str) else "body")
def test_parse_unusable_replies(body, reason):
    p = rc.parse_response(body)
    assert not p["ok"] and reason in p["reason"]


def test_parse_reports_extra_series_without_failing():
    body = json.loads(reply())
    body["hourly"]["temperature_2m_icon_seamless"] = [1.0] * HOURS
    p = rc.parse_response(json.dumps(body).encode())
    assert p["ok"] and p["series_extra"] == ["temperature_2m_icon_seamless"]


def test_parse_wrong_hour_count():
    body = json.loads(reply())
    body["hourly"] = {k: v[:-24] for k, v in body["hourly"].items()}
    p = rc.parse_response(json.dumps(body).encode())
    assert not p["ok"] and f"n_times_{HOURS - 24}_not_{HOURS}" in p["reason"]


# --------------------------------------------------------------------------- recorder
def test_run_slot_keeps_body_sha_and_receipt(tmp_path):
    rec, _ = make(tmp_path)
    cycle = rec.run_slot(dt.datetime(2026, 10, 30, 20, tzinfo=UTC))
    rows = lines(rec)
    assert [r["kind"] for r in rows] == ["fetch", "fetch", "cycle"]
    f = rows[0]
    assert f["market"] == "toronto" and f["unit"] == "C" and f["status"] == "ok"
    assert f["fetched_at_utc"] == "2026-10-30T20:25:00Z" and f["server_date"].startswith("Fri, 30 Oct")
    assert f["response_sha256"] == hashlib.sha256(f["body"].encode("utf-8")).hexdigest()
    assert f["response_bytes"] == len(f["body"].encode("utf-8"))
    assert "temperature_unit=celsius" in f["url"] and "temperature_unit=fahrenheit" in rows[1]["url"]
    assert cycle["complete"] and cycle["rows_ok"] == 2 and cycle["reasons"] == []
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows[:2]).encode()
    assert cycle["rows_sha256"] == hashlib.sha256(body).hexdigest()


def test_incomplete_cycle_lists_reasons(tmp_path):
    lat_t, lat_n = rc.coord(43.6767), rc.coord(40.7769)
    rec, _ = make(tmp_path, Fake(bodies={lat_n: reply(drop=("temperature_2m_gfs_global",))}, fail={lat_t}))
    cycle = rec.run_slot(dt.datetime(2026, 10, 30, 20, tzinfo=UTC))
    assert not cycle["complete"] and cycle["rows_ok"] == 0
    assert cycle["reasons"] == ["toronto:error:OSError", "nyc:unusable:series_missing"]
    rows = lines(rec)
    assert rows[0]["body"] is None and rows[0]["response_sha256"] is None and rows[0]["fetched_at_utc"]


def test_http_error_status_is_kept_with_its_body(tmp_path):
    rec, _ = make(tmp_path, Fake(status=429))
    cycle = rec.run_slot(dt.datetime(2026, 10, 30, 20, tzinfo=UTC))
    assert cycle["reasons"] == ["toronto:http_429", "nyc:http_429"]
    assert lines(rec)[0]["http_status"] == 429 and lines(rec)[0]["response_sha256"]


def test_step_window_once_per_slot_and_gaps(tmp_path):
    rec, clock = make(tmp_path, t=dt.datetime(2026, 10, 30, 20, 19, 59, tzinfo=UTC))
    assert rec.step()["ran"] is False  # before HH:20
    clock.t = dt.datetime(2026, 10, 30, 20, 20, tzinfo=UTC)
    assert rec.step()["ran"] is True
    clock.t = dt.datetime(2026, 10, 30, 20, 30, tzinfo=UTC)
    assert rec.step()["ran"] is False  # already done
    clock.t = dt.datetime(2026, 10, 30, 21, 50, tzinfo=UTC)
    assert rec.step()["ran"] is False  # HH:50 is outside the window
    clock.t = dt.datetime(2026, 10, 30, 23, 21, tzinfo=UTC)
    assert rec.step()["ran"] is True
    gaps = rc.read_jsonl(rec.out / "gaps.jsonl")
    assert [g["slot_utc"] for g in gaps] == ["2026-10-30T21:00:00Z", "2026-10-30T22:00:00Z"]
    assert len(rec.http.calls) == 4


def test_day_manifest_written_after_utc_midnight(tmp_path):
    rec, clock = make(tmp_path, t=dt.datetime(2026, 10, 30, 23, 25, tzinfo=UTC))
    rec.step()
    clock.t = dt.datetime(2026, 10, 31, 0, 25, tzinfo=UTC)
    rec.step()
    man = json.loads((rec.out / "20261030" / "manifest.json").read_text(encoding="utf-8"))
    assert man["cycles"] == 1 and man["cycles_complete"] == 1 and man["slots_missing"] == 23
    assert man["file_sha256"] == hashlib.sha256((rec.out / "20261030" / "prev_runs.jsonl").read_bytes()).hexdigest()
    assert not (rec.out / "20261031" / "manifest.json").exists()


def test_restart_does_not_refetch_a_done_slot_and_closes_old_days(tmp_path):
    rec, _ = make(tmp_path)
    rec.step()
    rec2, _ = make(tmp_path)
    assert rec2.step()["ran"] is False
    rec3, _ = make(tmp_path, t=dt.datetime(2026, 10, 31, 5, 25, tzinfo=UTC))
    rec3.step()
    assert (rec.out / "20261030" / "manifest.json").exists()


def test_pause_and_stop_files(tmp_path):
    rec, clock = make(tmp_path)
    rec.pause_file.write_text("x")
    assert rec.step() == {"slot": "2026-10-30T20:00:00Z", "ran": False, "paused": True}
    rec.pause_file.unlink()
    assert rec.step()["ran"] is True
    assert [g["gap"] for g in rc.read_jsonl(rec.out / "gaps.jsonl")] == ["pause_start", "pause_end"]
    rec.stop_file.write_text("x")
    clock.t = dt.datetime(2026, 10, 30, 21, 25, tzinfo=UTC)
    cycle = rec.run_slot(slot=dt.datetime(2026, 10, 30, 21, tzinfo=UTC))
    assert cycle["reasons"] == ["stop_file"] and cycle["rows"] == 0
    rec.run(poll_s=0, max_steps=3)
    assert json.loads((rec.out / "status.json").read_text(encoding="utf-8"))["state"] == "stopped_by_file"


def test_hourly_ceiling_marks_rows_guard(tmp_path):
    rec, _ = make(tmp_path, hourly_requests=1)
    cycle = rec.run_slot(dt.datetime(2026, 10, 30, 20, tzinfo=UTC))
    assert cycle["reasons"] == ["nyc:guard"] and len(rec.http.calls) == 1


def test_markets_from_registry_reads_builtin_coordinates(monkeypatch):
    monkeypatch.delenv("WEATHER_MARKET_REGISTRY", raising=False)
    m = rc.markets_from_registry()
    assert tuple(m) == rc.MARKETS
    assert m["toronto"]["unit"] == "C" and m["nyc"]["unit"] == "F" and m["nyc"]["icao"] == "KLGA"
    monkeypatch.setenv("WEATHER_MARKET_REGISTRY", "x.json")
    with pytest.raises(SystemExit):
        rc.markets_from_registry()


def test_main_refuses_output_inside_the_repository():
    with pytest.raises(SystemExit, match="outside the repository"):
        rc.main(["--out", str(REPO_ROOT / "data" / "om_prev_runs_test"), "--once"])
