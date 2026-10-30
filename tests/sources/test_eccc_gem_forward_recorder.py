"""Lane L13 ECCC GEM forward recorder: GRIB2 5.40 decoding, rotated-pole points, point-in-time receipts, gaps.

Deterministic: synthetic GRIB2 files (JPEG2000 written by Pillow) are served by a clock-driven fake Datamart; no
network. Guards: station pins against the market registry, fail-closed template checks, forward-only runs, and
timezone-aware local-day fields across the 2026-11-01 DST change.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import struct
from email.utils import format_datetime

import numpy as np
import pytest
from PIL import Image

from tools.research import eccc_gem_forward_recorder as gem

UTC = dt.timezone.utc
RUN = dt.datetime(2026, 11, 1, 0, tzinfo=UTC)
R0, D = 25000.0, 2  # value = (R0 + x) / 100 kelvin
ROT = {"template": 1, "ni": 10, "nj": 10, "la1": -10.0, "lo1": 20.0, "di": 1.0, "dj": 1.0, "scan": 0x40,
       "splat": -36.08852, "splon": 245.305142}
REG = {"template": 0, "ni": 36, "nj": 19, "la1": -90.0, "lo1": 0.0, "di": 10.0, "dj": 10.0, "scan": 0x40}


def _sm32(v):
    return struct.pack(">I", (abs(int(round(v))) | 0x80000000) if v < 0 else int(round(v)))


def _field(g):
    j, i = np.mgrid[0:g["nj"], 0:g["ni"]]
    return (100 * j + i).astype(np.uint16)


def _msg(run, step, product="t2m", grid=REG, member=None, n_members=None, x=None, number=None, window=None,
         ref=None, end=None):
    disc, cat, num, tpls, stat, win = gem.PRODUCTS[product]
    num = num if number is None else number
    win = win if window is None else window
    x = _field(grid) if x is None else x
    ref = ref or run
    s1 = struct.pack(">IBHHBBBHBBBBBBB", 21, 1, 54, 0, 4, 0, 1, ref.year, ref.month, ref.day, ref.hour, 0, 0, 0, 1)
    body3 = bytearray(84 if grid["template"] == 1 else 72)
    body3[0:4] = struct.pack(">I", len(body3))
    body3[4] = 3
    body3[6:10] = struct.pack(">I", grid["ni"] * grid["nj"])
    body3[12:14] = struct.pack(">H", grid["template"])
    body3[30:34] = struct.pack(">I", grid["ni"])
    body3[34:38] = struct.pack(">I", grid["nj"])
    body3[42:46] = b"\xff\xff\xff\xff"
    body3[46:50] = _sm32(grid["la1"] * 1e6)
    body3[50:54] = _sm32((grid["lo1"] % 360) * 1e6)
    body3[55:59] = _sm32((grid["la1"] + grid["dj"] * (grid["nj"] - 1)) * 1e6)
    body3[59:63] = _sm32(((grid["lo1"] + grid["di"] * (grid["ni"] - 1)) % 360) * 1e6)
    body3[63:67] = struct.pack(">I", int(round(grid["di"] * 1e6)))
    body3[67:71] = struct.pack(">I", int(round(grid["dj"] * 1e6)))
    body3[71] = grid["scan"]
    if grid["template"] == 1:
        body3[72:76] = _sm32(grid["splat"] * 1e6)
        body3[76:80] = _sm32(grid["splon"] * 1e6)
    ens = member is not None
    tpl = tpls[1 if ens else 0]
    fc = step - win
    s4 = bytearray(struct.pack(">IBHHBBBBBHBBI", 0, 4, 0, tpl, cat, num, 2, 0, 0, 0, 0, 1, fc))
    s4 += bytes([103, 0]) + struct.pack(">I", 2) + bytes([255, 0]) + struct.pack(">I", 0)
    if ens:
        s4 += bytes([4 if member else 1, member, n_members])
    if tpl in (8, 11):
        e = end or run + dt.timedelta(hours=step)
        s4 += struct.pack(">HBBBBB", e.year, e.month, e.day, e.hour, 0, 0) + bytes([1]) + struct.pack(">I", 0)
        s4 += bytes([stat if stat is not None else 2, 2, 1]) + struct.pack(">I", win) + bytes([255]) + struct.pack(">I", 0)
    s4[0:4] = struct.pack(">I", len(s4))
    b = io.BytesIO()
    Image.fromarray(x.astype(np.uint16)).save(b, format="JPEG2000", no_jp2=True)
    cs = b.getvalue()
    s5 = struct.pack(">IBIHfHHBBBB", 23, 5, x.size, 40, R0, 0, D, 16, 0, 0, 255)
    s6 = struct.pack(">IBB", 6, 6, 255)
    s7 = struct.pack(">IB", 5 + len(cs), 7) + cs
    payload = s1 + bytes(body3) + bytes(s4) + s5 + s6 + s7
    total = 16 + len(payload) + 4
    return b"GRIB" + b"\0\0" + bytes([disc, 2]) + struct.pack(">Q", total) + payload + b"7777"


def _expected(g, lat, lon):
    glat, glon = gem.rotate(lat, lon, g["splat"], g["splon"]) if g["template"] == 1 else (lat, lon)
    fj, fi = (glat - g["la1"]) / g["dj"], ((glon - g["lo1"]) % 360) / g["di"]
    return (R0 + 100 * fj + fi) / 10 ** D


TEST_MODELS = {
    "rdps": {"cycles": (0,), "first_try_h": 2.5, "members": None, "products": {"t2m": (1, 2, 3)}},
    "geps": {"cycles": (0,), "first_try_h": 4.5, "members": 3, "products": {"t2m": (3,), "tmax": (6,)}},
}


class FakeDatamart:
    """Serves synthetic files once ``run + lag`` has passed; ``never`` lists URLs that stay 404."""

    def __init__(self, clock, lag_h=None, never=(), bad=None):
        self.clock, self.lag = clock, lag_h or {"rdps": 3.0, "geps": 5.0}
        self.never, self.bad = set(never), bad or {}
        self.used = self.requests = 0
        self.log = []
        self.urls = {}
        for model, spec in TEST_MODELS.items():
            for product, steps in spec["products"].items():
                for step in steps:
                    self.urls[gem.file_url(model, product, RUN, step)] = (model, product, step)

    def get(self, url):
        self.requests += 1
        self.log.append(url)
        if url not in self.urls or url in self.never:
            return gem.Resp(404, b"", {})
        model, product, step = self.urls[url]
        avail = RUN + dt.timedelta(hours=self.lag[model])
        if self.clock() < avail:
            return gem.Resp(404, b"", {})
        if url in self.bad:
            body = self.bad[url]
        elif model == "geps":
            n = TEST_MODELS["geps"]["members"]
            body = b"".join(_msg(RUN, step, product, REG, member=m, n_members=n) for m in range(n))
        else:
            body = _msg(RUN, step, product, ROT)
        self.used += len(body)
        lm = format_datetime(avail + dt.timedelta(minutes=step), usegmt=True)
        return gem.Resp(200, body, {"Last-Modified": lm, "ETag": f'"{step}"'})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _rec(tmp_path, clock, http, **kw):
    kw.setdefault("first_run", RUN)
    return gem.Recorder(tmp_path / "out", http, clock=clock, sleep=lambda s: None, models=dict(TEST_MODELS),
                        min_free_gb=0, **kw)


def test_station_pins_match_market_registry():
    from weather.market.market_registry import spec_for_id

    for market, icao, lat, lon, tz in gem.STATIONS:
        spec = spec_for_id(market)
        assert spec.icao == icao and spec.timezone == tz
        assert abs(float(spec.lat) - lat) < 1e-3 and abs(float(spec.lon) - lon) < 1e-3


def test_urls_use_the_dated_archive_and_reuse_eccc_gridded():
    run = dt.datetime(2026, 11, 2, 18, tzinfo=UTC)
    u = gem.file_url("hrdps", "t2m", run, 7)
    assert u == ("https://dd.weather.gc.ca/20261102/WXO-DD/model_hrdps/continental/2.5km/18/007/"
                 "20261102T18Z_MSC_HRDPS_TMP_AGL-2m_RLatLon0.0225_PT007H.grib2")
    assert gem.file_url("geps", "tmax", run, 48).endswith("/ensemble/geps/grib2/raw/18/048/"
                                                          "CMC_geps-raw_TMAX_TGL_2m_latlon0p5x0p5_2026110218_P048_allmbrs.grib2")
    assert "/model_gdps/15km/18/012/20261102T18Z_MSC_GDPS_AirTemp-Max_AGL-2m_LatLon0.15_PT012H" in gem.file_url(
        "gdps", "tmax", run, 12)
    assert all("/today/" not in gem.file_url(m, "t2m", run, 3) for m in gem.MODELS)


def test_rotated_pole_transform_known_points():
    splat, splon = -36.08852, 245.305142
    lat, lon = gem.rotate(90 + splat, splon, splat, splon)  # the rotated origin
    assert abs(lat) < 1e-9 and abs(lon) < 1e-9
    assert gem.rotate(splat, splon, splat, splon)[0] == pytest.approx(-90.0)
    assert gem.rotate(-splat, splon - 180.0, splat, splon)[0] == pytest.approx(90.0)


@pytest.mark.parametrize("grid", [REG, ROT])
def test_decode_and_bilinear_point(grid):
    meta, vals = gem.decode_message(_msg(RUN, 2, "t2m", grid))
    gem.check_meta(meta, "t2m", RUN, 2, False)
    _, icao, lat, lon, _ = gem.STATIONS[0]
    pv = gem.point_values(vals, gem.corners(meta["grid"], lat, lon))
    assert pv["bilinear_k"] == pytest.approx(_expected(grid, lat, lon), abs=1e-3)
    assert sorted(pv["corners_k"])[0] <= pv["nearest_k"] <= sorted(pv["corners_k"])[-1]


def test_unshift_rules():
    a = (np.arange(12, dtype=np.int64) * 7) << 4
    assert list(gem.unshift(a, "I;16", 12, 12)) == list(np.arange(12) * 7)
    assert list(gem.unshift(np.arange(5, dtype=np.int64), "I;16", 16, 5)) == [0, 1, 2, 3, 4]
    assert list(gem.unshift(np.arange(5, dtype=np.int64), "L", 8, 5)) == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError):
        gem.unshift(a + 1, "I;16", 12, 12)  # not left-aligned
    with pytest.raises(ValueError):
        gem.unshift(a, "I;16", 12, 13)
    with pytest.raises(ValueError):
        gem.unshift(a, "L", 6, 12)


def test_check_meta_fails_closed():
    good = gem.decode_message(_msg(RUN, 6, "tmax", REG))[0]
    gem.check_meta(good, "tmax", RUN, 6, False)
    for kw, args in [({"number": 0}, ("tmax", RUN, 6, False)), ({"window": 3}, ("tmax", RUN, 6, False)),
                     ({}, ("tmax", RUN, 12, False)), ({}, ("tmax", RUN + dt.timedelta(hours=12), 6, False)),
                     ({"end": RUN + dt.timedelta(hours=7)}, ("tmax", RUN, 6, False)), ({}, ("tmax", RUN, 6, True))]:
        meta = gem.decode_message(_msg(RUN, 6, "tmax", REG, **kw))[0]
        with pytest.raises(ValueError):
            gem.check_meta(meta, *args)
    with pytest.raises(ValueError):
        gem.check_meta(gem.decode_message(_msg(RUN, 2, "t2m", REG, ref=RUN - dt.timedelta(hours=6)))[0],
                       "t2m", RUN, 2, False)


def test_point_in_time_receipts_local_day_and_manifest(tmp_path):
    clock = Clock(RUN + dt.timedelta(hours=2.6))
    http = FakeDatamart(clock)
    rec = _rec(tmp_path, clock, http)
    assert rec.step()["fetched_files"] == 0  # rdps open but not yet published; geps not yet open
    assert not (tmp_path / "out" / "rdps" / "2026110100" / "index.jsonl").exists()
    clock.t = RUN + dt.timedelta(hours=6)
    assert rec.step()["fetched_files"] == 5
    for model, n_points in (("rdps", 3), ("geps", 6)):
        d = tmp_path / "out" / model / "2026110100"
        man = json.loads((d / "manifest.json").read_text())
        assert man["slots_missing"] == [] and man["files"] == len(man["file_sha256"])
        pts = [json.loads(x) for x in (d / "points.jsonl").read_text().splitlines()]
        assert len(pts) == n_points
        for p in pts:
            assert p["fetched_utc"] and p["last_modified_utc"] and p["file_sha256"] and p["tz"] == "America/Toronto"
        idx = [json.loads(x) for x in (d / "index.jsonl").read_text().splitlines()]
        assert {r["status"] for r in idx if r["kind"] == "file"} == {"ok"}
    geps = [json.loads(x) for x in (tmp_path / "out" / "geps" / "2026110100" / "points.jsonl").read_text().splitlines()]
    tmax = [p for p in geps if p["product"] == "tmax"]
    assert sorted(p["member"] for p in tmax) == [0, 1, 2]
    # tmax window 00Z-06Z on 11-01 crosses Toronto local midnight (04Z EDT): no local date
    assert all(p["local_date"] is None and p["straddles_local_midnight"] for p in tmax)
    t2m = [p for p in geps if p["product"] == "t2m"][0]  # 03Z = 23:00 EDT on 10-31
    assert t2m["local_date"] == "2026-10-31" and t2m["window_end_local"].endswith("-04:00")
    # idempotent restart: a new recorder sees the manifests and fetches nothing
    n = http.requests
    r2 = _rec(tmp_path, clock, http)
    assert r2.step()["fetched_files"] == 0 and http.requests == n


def test_late_404_counts_then_missing_and_later_steps_still_fetched(tmp_path):
    clock = Clock(RUN + dt.timedelta(hours=3.5))
    missing_url = gem.file_url("rdps", "t2m", RUN, 2)
    http = FakeDatamart(clock, never=[missing_url])
    rec = _rec(tmp_path, clock, http)
    rec.step()
    d = tmp_path / "out" / "rdps" / "2026110100"
    idx = [json.loads(x) for x in (d / "index.jsonl").read_text().splitlines()]
    assert [(r["step"], r["status"]) for r in idx] == [(1, "ok")]  # step 2 not yet: 3 waits
    clock.t = RUN + dt.timedelta(hours=12)  # past first_try + LATE
    for _ in range(gem.MAX_TRIES + 1):
        rec.step()
    man = json.loads((d / "manifest.json").read_text())
    assert man["slots_missing"] == [["t2m", 2]] and ["t2m", 3] in man["slots_ok"]
    gaps = [json.loads(x) for x in (tmp_path / "out" / "gaps.jsonl").read_text().splitlines()]
    assert [(g["model"], g["step"]) for g in gaps if g["gap"] == "missing"] == [("rdps", 2)]


def test_ensemble_member_mismatch_is_invalid(tmp_path):
    clock = Clock(RUN + dt.timedelta(hours=6))
    url = gem.file_url("geps", "t2m", RUN, 3)
    body = b"".join(_msg(RUN, 3, "t2m", REG, member=m, n_members=3) for m in (0, 1, 1))
    http = FakeDatamart(clock, bad={url: body})
    rec = _rec(tmp_path, clock, http)
    rec.step()
    idx = [json.loads(x) for x in (tmp_path / "out" / "geps" / "2026110100" / "index.jsonl").read_text().splitlines()]
    bad = [r for r in idx if r.get("product") == "t2m"]
    assert bad[0]["status"] == "invalid" and "members" in bad[0]["error"]
    pts = (tmp_path / "out" / "geps" / "2026110100" / "points.jsonl").read_text().splitlines()
    assert all(json.loads(x)["product"] == "tmax" for x in pts)


def test_forward_only(tmp_path):
    clock = Clock(dt.datetime(2026, 10, 31, 12, tzinfo=UTC))
    rec = gem.Recorder(tmp_path / "o", FakeDatamart(clock), clock=clock, models=dict(TEST_MODELS),
                       first_run=dt.datetime(2026, 10, 1, tzinfo=UTC), min_free_gb=0)
    assert all(run >= gem.FORWARD_FIRST for _, run in rec.open_runs(clock()))
    assert rec.first_run == gem.FORWARD_FIRST


def test_stop_and_pause(tmp_path):
    clock = Clock(RUN + dt.timedelta(hours=6))
    http = FakeDatamart(clock)
    rec = _rec(tmp_path, clock, http)
    (tmp_path / "out" / "RECORDER_PAUSE").write_text("")
    assert rec.step()["paused"] and http.requests == 0
    (tmp_path / "out" / "RECORDER_PAUSE").unlink()
    (tmp_path / "out" / "STOP").write_text("")
    rec.run(poll_s=0, max_steps=3)
    assert json.loads((tmp_path / "out" / "status.json").read_text())["state"] == "stopped_by_file"
    gaps = [json.loads(x)["gap"] for x in (tmp_path / "out" / "gaps.jsonl").read_text().splitlines()]
    assert gaps == ["pause_start"]


def test_output_must_be_outside_repo():
    from pathlib import Path

    with pytest.raises(SystemExit):
        gem.main(["--out", str(Path(gem.__file__).resolve().parents[2] / "data" / "x"), "--once"])
