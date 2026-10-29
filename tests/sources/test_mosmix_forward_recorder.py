"""Lane L13: DWD MOSMIX forward-capture recorder (tools/research/mosmix_forward_recorder.py).

Offline: a clock-driven fake opendata.dwd.de serving synthetic KMZ files. Guards: the pinned station map (ids,
coordinates, the 12 markets), the issue schedule, byte-exact S subsets, the point-in-time receipt (IssueTime,
Last-Modified, our fetch time, sha256) and ``issue_available``, forward issues only, a 404 before publication is not
a failure, slots close as missing at the retention horizon, day manifests pin every kept file by sha256, raw S
pruning keeps the index record, and STOP / pause work.
"""
import datetime as dt
import hashlib
import io
import json
import zipfile
from email.utils import format_datetime

import pytest

from tools.research import mosmix_forward_recorder as mx

UTC = dt.timezone.utc


def _placemark(sid):
    pin = next((s for s in mx.STATIONS if s[1] == sid), (None, sid, None, 70.93, -8.67, 10.0))  # unpinned: Jan Mayen
    return (f"<kml:Placemark><kml:name>{sid}</kml:name><kml:description>X</kml:description><kml:ExtendedData>"
            f'<dwd:Forecast dwd:elementName="TTT"><dwd:value>290.15 291.15 -</dwd:value></dwd:Forecast>'
            f'<dwd:Forecast dwd:elementName="TX"><dwd:value>- - 295.0</dwd:value></dwd:Forecast>'
            f"</kml:ExtendedData><kml:Point><kml:coordinates>{pin[4]:.2f},{pin[3]:.2f},{pin[5]:.1f}"
            f"</kml:coordinates></kml:Point></kml:Placemark>").encode()


def _kml(issue, sids):
    head = ('<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>'
            f'<kml:kml xmlns:dwd="{mx.NS_DWD}" xmlns:kml="http://www.opengis.net/kml/2.2"><kml:Document>'
            "<kml:ExtendedData><dwd:ProductDefinition>"
            f"<dwd:IssueTime>{issue.strftime('%Y-%m-%dT%H:00:00.000Z')}</dwd:IssueTime>"
            '<dwd:ReferencedModel><dwd:Model dwd:name="ICON" dwd:referenceTime="2026-10-30T00:00:00Z"/>'
            "</dwd:ReferencedModel><dwd:ForecastTimeSteps><dwd:TimeStep>a</dwd:TimeStep><dwd:TimeStep>b</dwd:TimeStep>"
            "<dwd:TimeStep>c</dwd:TimeStep></dwd:ForecastTimeSteps></dwd:ProductDefinition></kml:ExtendedData>").encode()
    return head + b"".join(_placemark(s) for s in sids) + b"</kml:Document></kml:kml>"


def _kmz(name, kml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name.replace(".kmz", ".kml"), kml)
    return buf.getvalue()


class FakeDWD:
    """Serves an issue once ``clock() >= issue + lag``; Last-Modified = issue + lag."""

    def __init__(self, clock, lag=dt.timedelta(minutes=73), extra_s=("10637", "01001")):
        self.clock, self.lag, self.extra_s = clock, lag, extra_s
        self.used, self.requests, self.urls = 0, 0, []
        self.fail = set()

    def get(self, url, timeout=120):
        self.requests += 1
        self.urls.append(url)
        name = url.rsplit("/", 1)[1]
        parts = name[:-4].split("_")
        issue = dt.datetime.strptime(parts[2], "%Y%m%d%H").replace(tzinfo=UTC)
        if self.clock() < issue + self.lag:
            return mx.Resp(404, b"", {})
        if name in self.fail:
            return mx.Resp(503, b"", {})
        if parts[1] == "L":
            body = _kmz(name, _kml(issue, [parts[3]]))
        else:
            body = _kmz(name, _kml(issue, list(self.extra_s[:1]) + list(mx.STATION_IDS) + list(self.extra_s[1:])))
        self.used += len(body)
        lm = format_datetime(issue + self.lag, usegmt=True)
        return mx.Resp(200, body, {"Last-Modified": lm, "ETag": '"e"', "Content-Length": str(len(body))})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _rec(tmp_path, t, **kw):
    clock = Clock(t)
    http = FakeDWD(clock)
    r = mx.Recorder(tmp_path / "out", http, clock=clock, sleep=lambda s: None, min_free_gb=0, **kw)
    return r, http, clock


def test_station_map_pins_twelve_markets_and_flags():
    tab = mx.station_table()
    markets = {r["market"] for r in tab}
    assert len(markets) == 12 and "toronto" in markets
    prim = {r["market"]: r for r in tab if r["role"] == "primary"}
    assert len(prim) == 12
    assert prim["san-francisco"]["mosmix_id"] == "72494" and prim["san-francisco"]["distance_km"] < 2
    assert prim["houston"]["distance_km"] > 30  # KHOU has no MOSMIX point; IAH is the nearest
    assert {r["mosmix_id"] for r in tab if r["role"] == "secondary"} == {"72565", "72242"}
    assert len(set(mx.STATION_IDS)) == len(mx.STATION_IDS) == 14


def test_issue_schedule_and_urls():
    t0 = dt.datetime(2026, 10, 30, 0, tzinfo=UTC)
    assert [i.hour for i in mx.issues_between("L", t0, t0 + dt.timedelta(hours=23))] == [3, 9, 15, 21]
    assert len(mx.issues_between("S", t0, t0 + dt.timedelta(hours=23))) == 24
    i = dt.datetime(2026, 10, 30, 9, tzinfo=UTC)
    assert mx.issue_url("L", i, "72494").endswith("MOSMIX_L/single_stations/72494/kml/MOSMIX_L_2026103009_72494.kmz")
    assert mx.issue_url("S", i).endswith("MOSMIX_S/all_stations/kml/MOSMIX_S_2026103009_240.kmz")


def test_s_subset_is_byte_exact_for_our_stations():
    issue = dt.datetime(2026, 10, 30, 9, tzinfo=UTC)
    kml = _kml(issue, ["10637"] + list(mx.STATION_IDS) + ["01001"])
    member, body, meta = mx.s_subset(_kmz("MOSMIX_S_2026103009_240.kmz", kml), wanted=mx.STATION_IDS)
    for sid in mx.STATION_IDS:
        assert _placemark(sid) in body
    assert b"<kml:name>10637<" not in body and b"<kml:name>01001<" not in body
    assert body.startswith(kml[:kml.find(mx.PM_OPEN)]) and body.endswith(b"</kml:Document></kml:kml>")
    assert meta["issue_time_doc"] == "2026-10-30T09:00:00.000Z" and meta["stations_missing"] == []
    assert meta["referenced_models"] == [["ICON", "2026-10-30T00:00:00Z"]]
    series = mx.read_series(body, "72494")
    assert series["TTT"] == [290.15, 291.15, None] and series["TX"] == [None, None, 295.0]


def test_split_placemarks_across_small_chunks():
    issue = dt.datetime(2026, 10, 30, 9, tzinfo=UTC)
    kml = _kml(issue, ["10637"] + list(mx.STATION_IDS))
    head, found, tail = mx.split_placemarks(io.BytesIO(kml), {"72494", "71624"}, chunk=37)
    assert set(found) == {"72494", "71624"} and found["72494"] == _placemark("72494")
    assert tail == b"</kml:Document></kml:kml>"


def test_placemark_pin_refuses_moved_station():
    bad = _placemark("72494").replace(b"37.62", b"37.70")
    with pytest.raises(ValueError):
        mx.check_placemark(bad, "72494")


def test_l_and_s_receipts_and_point_in_time(tmp_path):
    t = dt.datetime(2026, 10, 30, 10, 30, tzinfo=UTC)
    r, http, clock = _rec(tmp_path, t)
    day = t.date()
    r.work_day(day, t)
    rows = r.day_state(day)["rows"]
    l9 = [x for x in rows if x["product"] == "L" and x["issue_utc"].startswith("2026-10-30T09")]
    assert {x["station"] for x in l9} == set(mx.STATION_IDS) and all(x["status"] == "ok" for x in l9)
    x = l9[0]
    assert x["last_modified_utc"] == "2026-10-30T10:13:00+00:00" and x["fetched_utc"] == t.isoformat()
    raw = (r.out / x["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == x["sha256"]
    s = [x for x in rows if x["product"] == "S"]
    assert [x["issue_utc"][11:13] for x in s] == ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"]
    assert all((r.out / x["subset_path"]).exists() for x in s)
    # 10Z S is published at 11:13 (fake lag): not fetched, not indexed (404 before publication is not a failure)
    assert not any(x.get("status") == "not_yet" for x in rows)
    cut = dt.datetime(2026, 10, 30, 10, 0, tzinfo=UTC)  # before the 09Z L Last-Modified
    best = mx.issue_available(rows, "L", cut, sid="72494")
    assert best["issue_utc"].startswith("2026-10-30T03")
    best = mx.issue_available(rows, "L", dt.datetime(2026, 10, 30, 10, 20, tzinfo=UTC), sid="72494")
    assert best["issue_utc"].startswith("2026-10-30T09")
    late = mx.issue_available(rows, "L", dt.datetime(2026, 10, 30, 10, 20, tzinfo=UTC), sid="72494",
                              require_fetched=True)
    assert late is None  # live variant: every file here was first fetched at 10:30, after the cutoff
    late = mx.issue_available(rows, "L", t, sid="72494", require_fetched=True)
    assert late["issue_utc"].startswith("2026-10-30T09")


def test_forward_only(tmp_path):
    t = dt.datetime(2026, 10, 29, 23, 0, tzinfo=UTC)
    r, http, clock = _rec(tmp_path, t, first_issue=dt.datetime(2026, 1, 1, tzinfo=UTC))
    assert r.first_issue == mx.FORWARD_FIRST
    r.work_day(t.date(), t)
    assert all(dt.datetime.fromisoformat(x["issue_utc"]) >= mx.FORWARD_FIRST for x in r.day_state(t.date())["rows"])


def test_missing_close_and_manifest(tmp_path):
    t = dt.datetime(2026, 10, 30, 23, 0, tzinfo=UTC)
    r, http, clock = _rec(tmp_path, t, products=("L",))
    day = t.date()
    http.fail = {"MOSMIX_L_2026103015_72494.kmz"}
    r.work_day(day, t)
    st = r.day_state(day)
    assert st["tries"][("L", "2026-10-30T15:00:00+00:00", "72494")] == 1 and not st["done"]
    later = t + dt.timedelta(hours=20)
    clock.t = later
    r.work_day(day, later)
    assert not st["done"]
    clock.t = later + dt.timedelta(hours=20)
    http.fail = set()
    r.work_day(day, clock.t)  # 15Z + 44 h passed: the failing slot closes as missing (gaps.jsonl)
    assert st["done"]
    man = json.loads((r.out / day.isoformat() / "manifest.json").read_text())
    assert man["ok"] == 4 * 14 - 1 and man["missing"] == 1
    idx = (r.out / day.isoformat() / "index.jsonl").read_bytes()
    assert man["index_sha256"] == hashlib.sha256(idx).hexdigest()
    for path, sha in man["files_sha256"].items():
        assert hashlib.sha256((r.out / path).read_bytes()).hexdigest() == sha
    gaps = [json.loads(line) for line in (r.out / "gaps.jsonl").read_text().splitlines()]
    assert gaps[-1]["station"] == "72494" and gaps[-1]["status"] == "missing"
    # a restart re-reads the day as done and fetches nothing
    r2 = mx.Recorder(r.out, FakeDWD(clock), clock=clock, sleep=lambda s: None, min_free_gb=0, products=("L",))
    assert r2.day_state(day)["done"] and day not in r2.active_days(clock.t)


def test_s_raw_pruning_keeps_record(tmp_path):
    t = dt.datetime(2026, 10, 30, 3, 0, tzinfo=UTC)
    r, http, clock = _rec(tmp_path, t, products=("S",), s_raw_retain_days=1)
    r.work_day(t.date(), t)
    raws = sorted((r.out / "S").rglob("MOSMIX_S_*_240.kmz"))
    assert raws
    n = r.prune_s_raw(t + dt.timedelta(days=2))
    assert n == len(raws) and not list((r.out / "S").rglob("MOSMIX_S_*_240.kmz"))
    assert list((r.out / "S").rglob("*_subset.kmz"))
    pruned = [json.loads(line) for line in (r.out / "pruned.jsonl").read_text().splitlines()]
    assert len(pruned) == n and all(len(p["sha256"]) == 64 for p in pruned)


def test_invalid_issue_time_is_recorded_not_kept(tmp_path):
    t = dt.datetime(2026, 10, 30, 10, 30, tzinfo=UTC)
    r, http, clock = _rec(tmp_path, t, products=("L",))
    orig = http.get

    def wrong(url, timeout=120):
        resp = orig(url, timeout)
        if resp.status_code == 200 and "2026103009_72494" in url:
            name = url.rsplit("/", 1)[1]
            body = _kmz(name, _kml(dt.datetime(2026, 10, 30, 3, tzinfo=UTC), ["72494"]))
            return mx.Resp(200, body, {**resp.headers, "Content-Length": str(len(body))})
        return resp

    http.get = wrong
    r.work_day(t.date(), t)
    bad = [x for x in r.day_state(t.date())["rows"] if x["station"] == "72494" and x["issue_utc"][11:13] == "09"]
    assert bad[0]["status"] == "invalid" and "IssueTime" in bad[0]["error"]


def test_stop_and_pause(tmp_path):
    t = dt.datetime(2026, 10, 30, 10, 30, tzinfo=UTC)
    r, http, clock = _rec(tmp_path, t, products=("L",))
    r.pause_file.write_text("")
    assert r.step()["paused"] and http.requests == 0
    r.pause_file.unlink()
    assert r.step()["fetched"] > 0
    r.stop_file.write_text("")
    r.run(poll_s=1, max_steps=5)
    assert json.loads((r.out / "status.json").read_text())["state"] == "stopped_by_file"


def test_output_must_be_outside_repo(tmp_path):
    from pathlib import Path

    repo = Path(mx.__file__).resolve().parents[2]
    with pytest.raises(SystemExit):
        mx.main(["--out", str(repo / "data" / "mosmix_test_should_not_exist"), "--once"])
