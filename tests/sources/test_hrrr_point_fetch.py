"""Offline decoder, geometry and point-in-time selection checks for the L13 HRRR point fetcher.

Guards: tools/research/hrrr_point_fetch.py point-in-time contract (a cycle is used for a snapshot
only when every needed forecast-hour .grib2 and .idx was published at least the poll margin before
it, else the previous stride cycle; never imputed), its GRIB2 template 5.3/5.0 decode arithmetic
(NCEP g2clib recurrence) and HRRR grid identity check, the nearest-point indices pinned to an
independent eccodes 2.49 lat/lon haversine search, and its 2026-09-29 date refusal.
"""
import datetime as dt
import json
import re
import struct

import numpy as np
import pytest

from tools.research import hrrr_point_fetch as fetch

UTC = dt.timezone.utc


# --------------------------------------------------------------------------- tiny GRIB2 encoder
class _Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, width):
        assert 0 <= value < (1 << width) or width == 0
        self.bits.extend((value >> (width - 1 - k)) & 1 for k in range(width))

    def put_sm(self, value, width):
        self.put((1 << (width - 1)) | -value if value < 0 else value, width)

    def align(self):
        while len(self.bits) % 8:
            self.bits.append(0)

    def tobytes(self):
        self.align()
        return bytes(int("".join(map(str, self.bits[i:i + 8])), 2) for i in range(0, len(self.bits), 8))


def _sm16(v):
    return (0x8000 | -v) if v < 0 else v


def _encode_53(ints, group_lengths, order, ref=0.0, e=0, d=0, nd=2):
    """Complex packing + spatial differencing of integer field ``ints`` into (sec5, sec7)."""
    ints = list(ints)
    n = len(ints)
    if order == 2:
        x = [0, 0] + [ints[i] - 2 * ints[i - 1] + ints[i - 2] for i in range(2, n)]
    else:
        x = [0] + [ints[i] - ints[i - 1] for i in range(1, n)]
    minsd = min(x[order:])
    x = [0] * order + [v - minsd for v in x[order:]]
    groups, pos = [], 0
    for gl in group_lengths:
        vals = x[pos:pos + gl]
        gref = min(vals)
        width = max(v - gref for v in vals).bit_length()
        groups.append((gref, width, gl, [v - gref for v in vals]))
        pos += gl
    assert pos == n
    nbits = max(g[0] for g in groups).bit_length() or 1
    wbits = max(g[1] for g in groups).bit_length() or 1
    lbits = max(g[2] for g in groups).bit_length()
    b = _Bits()
    for k in range(order):
        b.put_sm(ints[k], nd * 8)
    b.put_sm(minsd, nd * 8)
    b.align()
    for g in groups:
        b.put(g[0], nbits)
    b.align()
    for g in groups:
        b.put(g[1], wbits)
    b.align()
    for g in groups:
        b.put(g[2], lbits)
    b.align()
    for g in groups:
        for v in g[3]:
            b.put(v, g[1])
    body = b.tobytes()
    sec7 = struct.pack(">IB", 5 + len(body), 7) + body
    sec5 = struct.pack(">IBIHfHHBBBB", 49, 5, n, 3, ref, _sm16(e), _sm16(d), nbits, 0, 1, 0)
    sec5 += struct.pack(">IIIBBIBIBBBB", 0, 0, len(groups), 0, wbits, 0, 1, group_lengths[-1], lbits, order, nd, 0)[:-1]
    assert len(sec5) == 49
    return sec5, sec7


def _encode_50(ints, nbits, ref=0.0, e=0, d=0):
    b = _Bits()
    for v in ints:
        b.put(v, nbits)
    body = b.tobytes()
    sec5 = struct.pack(">IBIHfHHBB", 21, 5, len(ints), 0, ref, _sm16(e), _sm16(d), nbits, 0)
    return sec5, struct.pack(">IB", 5 + len(body), 7) + body


SEC6 = struct.pack(">IBB", 6, 6, 255)


def _reference_decode(ints_x, firsts, minsd, order):
    """Literal g2clib loop, independent of the vectorised cumsum path."""
    f = list(ints_x)
    f[0] = firsts[0]
    if order == 2:
        f[1] = firsts[1]
        for k in range(2, len(f)):
            f[k] = f[k] + minsd + 2 * f[k - 1] - f[k - 2]
    else:
        for k in range(1, len(f)):
            f[k] = f[k] + minsd + f[k - 1]
    return f


def test_template_53_order2_matches_literal_recurrence_and_prefix_decode():
    rng = np.random.default_rng(7)
    ints = [int(v) for v in np.cumsum(np.cumsum(rng.integers(-40, 41, size=97))) + 5000]
    ints[0], ints[1] = -3, 12  # negative first value exercises the sign-magnitude descriptor
    sec5, sec7 = _encode_53(ints, [10, 1, 30, 25, 31], order=2, ref=250.0, e=-2, d=1)
    got = fetch.unpack_values(sec5, SEC6, sec7, len(ints) - 1)
    want = (250.0 + np.array(ints, dtype=float) * 0.25) / 10.0
    assert np.array_equal(got, want)
    # Literal recurrence on the stored second differences reproduces the same integers.
    x = [0, 0] + [ints[i] - 2 * ints[i - 1] + ints[i - 2] for i in range(2, len(ints))]
    assert _reference_decode(x, ints[:2], 0, 2) == ints
    # Decoding only a prefix gives exactly the prefix (the fetcher decodes up to the last station).
    part = fetch.unpack_values(sec5, SEC6, sec7, 40)
    assert np.array_equal(part, want[:41])


def test_template_53_order1_and_constant_groups():
    ints = [7, 7, 7, 7, 9, 12, 12, 12, 11, 4, 4, 4]
    sec5, sec7 = _encode_53(ints, [4, 4, 4], order=1)
    assert np.array_equal(fetch.unpack_values(sec5, SEC6, sec7, 11), np.array(ints, dtype=float))


def test_template_50_simple_packing():
    ints = [0, 5, 1023, 512, 3]
    sec5, sec7 = _encode_50(ints, 10, ref=-1.5, e=1, d=0)
    assert np.array_equal(fetch.unpack_values(sec5, SEC6, sec7, 4), -1.5 + np.array(ints) * 2.0)


def test_bitmap_and_missing_value_management_fail_closed():
    sec5, sec7 = _encode_53([1, 2, 3, 4], [4], order=1)
    with pytest.raises(ValueError):
        fetch.unpack_values(sec5, struct.pack(">IBB", 6, 6, 0), sec7, 3)
    bad5 = sec5[:22] + bytes([1]) + sec5[23:]
    with pytest.raises(ValueError):
        fetch.unpack_values(bad5, SEC6, sec7, 3)


# --------------------------------------------------------------------------- full HRRR message
def _sec3(nx=1799):
    g = fetch.HRRR_GRID
    s = struct.pack(">IBBIBBH", 81, 3, 0, g["nx"] * g["ny"], 0, 0, 30)
    s += struct.pack(">BBIBIBI", 6, 0, 0, 0, 0, 0, 0)
    s += struct.pack(">IIIIB", nx, g["ny"], int(g["la1"] * 1e6), int(g["lo1"] * 1e6), 8)
    s += struct.pack(">IIIIBBII", 38500000, int(g["lov"] * 1e6), 3000000, 3000000, 0, 0x40,
                     38500000, 38500000)
    s += struct.pack(">II", 0, 0)
    assert len(s) == 81
    return s


def _message(cycle, fh, nx=1799, category=0, number=0):
    """A real-shaped HRRR TMP 2 m message whose field is the ramp value[k] = 200 + k / 16384."""
    npts = 1799 * 1059
    sec1 = struct.pack(">IBHHBBBHBBBBBBB", 21, 1, 7, 0, 2, 1, 1, cycle.year, cycle.month,
                       cycle.day, cycle.hour, 0, 0, 0, 1)
    sec4 = struct.pack(">IBHHBBBBBHBBIBBIBBI", 34, 4, 0, 0, category, number, 2, 0, 0x53, 0, 0, 1,
                       fh, 103, 0, 2, 255, 0, 0)
    # A linear ramp has zero second differences: one width-0 group covers the whole grid.
    b = _Bits()
    b.put_sm(0, 16)
    b.put_sm(1, 16)
    b.put_sm(0, 16)
    b.align()
    b.put(0, 1)
    b.align()
    b.put(0, 1)
    b.align()
    b.put(0, 1)
    body = b.tobytes()
    sec7 = struct.pack(">IB", 5 + len(body), 7) + body
    sec5 = struct.pack(">IBIHfHHBBBB", 49, 5, npts, 3, 200.0, _sm16(-14), 0, 1, 0, 1, 0)
    sec5 += struct.pack(">IIIBBIBIBBB", 0, 0, 1, 0, 1, 0, 1, npts, 1, 2, 2)
    payload = sec1 + _sec3(nx) + sec4 + sec5 + SEC6 + sec7 + b"7777"
    sec0 = b"GRIB" + b"\0\0" + bytes([0, 2]) + struct.pack(">Q", 16 + len(payload))
    return sec0 + payload


CYCLE = dt.datetime(2023, 8, 15, 12, tzinfo=UTC)
EXPECT = {"param": fetch.VARIABLES["TMP:2 m above ground"], "cycle_utc": CYCLE.isoformat(), "fh": 6}


def test_point_values_reads_nearest_and_3x3_from_a_full_grid_message():
    cells = {"KATL": fetch.station_cell(33.62972, -84.44223), "KSEA": fetch.station_cell(47.44467, -122.31442)}
    meta, pts = fetch.point_values(_message(CYCLE, 6), cells, EXPECT)
    assert meta["ref_time_utc"] == CYCLE.isoformat() and meta["fh"] == 6
    for st, c in cells.items():
        assert pts[st]["nearest"] == 200.0 + c["flat"] / 16384.0
        assert pts[st]["block3x3"][4] == pts[st]["nearest"]
        assert pts[st]["block3x3"][0] == 200.0 + (c["flat"] - 1799 - 1) / 16384.0
        assert pts[st]["block3x3"][8] == 200.0 + (c["flat"] + 1799 + 1) / 16384.0


@pytest.mark.parametrize("kwargs, expect", [
    ({"nx": 1800}, EXPECT),
    ({"number": 6}, EXPECT),
    ({}, {**EXPECT, "fh": 7}),
    ({}, {**EXPECT, "cycle_utc": (CYCLE + dt.timedelta(hours=1)).isoformat()}),
])
def test_point_values_refuses_wrong_grid_variable_or_time(kwargs, expect):
    cells = {"KATL": fetch.station_cell(33.62972, -84.44223)}
    with pytest.raises(ValueError):
        fetch.point_values(_message(CYCLE, 6, **kwargs), cells, expect)


def test_truncated_message_fails_closed():
    blob = _message(CYCLE, 6)
    with pytest.raises(ValueError):
        fetch.parse_sections(blob[:-1])


# --------------------------------------------------------------------------- geometry
# Nearest flat index from an eccodes 2.49 lat/lon haversine search on a real 2023-08-15 12Z message.
ECCODES_NEAREST = {
    "CYYZ": (43.6767, -79.6306, 1383009), "KATL": (33.62972, -84.44223, 679525),
    "KHOU": (29.64582, -95.28214, 362570), "KLGA": (40.7769, -73.874, 1257258),
    "KSEA": (47.44467, -122.31442, 1702131), "KSFO": (37.61961, -122.36561, 1068784),
    "KMIA": (25.78806, -80.31692, 197574), "KBKF": (39.713, -104.758, 1047710),
}


@pytest.mark.parametrize("station", sorted(ECCODES_NEAREST))
def test_station_cell_matches_eccodes_nearest_and_toronto_is_inside(station):
    lat, lon, flat = ECCODES_NEAREST[station]
    cell = fetch.station_cell(lat, lon)
    assert cell["flat"] == flat
    assert cell["inside"] and cell["offset_km"] < 2.2


def test_points_outside_the_domain_are_flagged():
    assert not fetch.station_cell(51.47, -0.45)["inside"]  # London
    assert not fetch.station_cell(21.0, -100.0)["inside"]  # south of the first row


# --------------------------------------------------------------------------- idx and listing
IDX = "1:0:d=2023081512:REFC:entire atmosphere:6 hour fcst:\n2:100:d=2023081512:TMP:2 m above ground:6 hour fcst:\n3:250:d=2023081512:DPT:2 m above ground:6 hour fcst:\n"


def test_find_range_uses_next_offset_or_object_size():
    rows = fetch.parse_idx(IDX)
    assert fetch.find_range(rows, "TMP:2 m above ground", 400)[:2] == (100, 249)
    assert fetch.find_range(rows, "DPT:2 m above ground", 400)[:2] == (250, 399)
    with pytest.raises(LookupError):
        fetch.find_range(rows, "UGRD:10 m above ground", 400)
    with pytest.raises(LookupError):
        fetch.find_range(fetch.parse_idx(IDX + IDX.splitlines()[1].replace("2:100", "4:300") + "\n"),
                         "TMP:2 m above ground", 400)


def test_parse_listing_with_namespace_and_continuation():
    xml = (b'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
           b"<IsTruncated>true</IsTruncated><NextContinuationToken>tok</NextContinuationToken>"
           b"<Contents><Key>a.grib2</Key><LastModified>2023-08-15T13:28:00.000Z</LastModified>"
           b'<ETag>"e1"</ETag><Size>10</Size></Contents></ListBucketResult>')
    out, token = fetch.parse_listing(xml)
    assert token == "tok"
    assert out == {"a.grib2": {"last_modified": "2023-08-15T13:28:00.000Z", "size": 10, "etag": '"e1"'}}


# --------------------------------------------------------------------------- point-in-time plan
def _avail(cycle, minutes=88, skip=()):
    return {fh: cycle + dt.timedelta(minutes=minutes) for fh in range(19) if fh not in skip}


T = dt.datetime(2023, 8, 15, 15, tzinfo=UTC)  # 11:00 EDT snapshot
END = dt.datetime(2023, 8, 16, 1, tzinfo=UTC)  # 21:00 EDT
MARGIN = dt.timedelta(minutes=10)


def test_select_cycle_boundary_both_sides():
    c12, c09 = T - dt.timedelta(hours=3), T - dt.timedelta(hours=6)
    exactly = T - MARGIN - c12
    on_time = {c12: _avail(c12, exactly.total_seconds() / 60), c09: _avail(c09)}
    sel = fetch.select_cycle(T, END, on_time, 3, MARGIN)
    assert sel["cycle_utc"] == c12.isoformat() and sel["depth"] == 1  # depth 0 is the 15Z cycle itself
    assert sel["fhs"] == list(range(3, 14))
    late = {c12: _avail(c12, exactly.total_seconds() / 60 + 1 / 60), c09: _avail(c09)}
    sel = fetch.select_cycle(T, END, late, 3, MARGIN)
    assert sel["cycle_utc"] == c09.isoformat() and sel["depth"] == 2
    assert sel["fhs"] == list(range(6, 17))


def test_select_cycle_falls_back_when_a_needed_fh_is_missing_and_ignores_unneeded_gaps():
    c12, c09 = T - dt.timedelta(hours=3), T - dt.timedelta(hours=6)
    unneeded_gap = {c12: _avail(c12, skip=(0, 1, 2, 18)), c09: _avail(c09)}
    assert fetch.select_cycle(T, END, unneeded_gap, 3, MARGIN)["cycle_utc"] == c12.isoformat()
    needed_gap = {c12: _avail(c12, skip=(13,)), c09: _avail(c09)}
    assert fetch.select_cycle(T, END, needed_gap, 3, MARGIN)["cycle_utc"] == c09.isoformat()
    assert fetch.select_cycle(T, END, {}, 3, MARGIN)["cycle_utc"] is None


def test_needed_fhs_flags_truncation_at_f18():
    c = dt.datetime(2023, 8, 15, 9, tzinfo=UTC)
    fhs, truncated = fetch.needed_fhs(c, c + dt.timedelta(hours=2), c + dt.timedelta(hours=19))
    assert fhs == list(range(2, 19)) and truncated
    fhs, truncated = fetch.needed_fhs(c, c + dt.timedelta(hours=2), c + dt.timedelta(hours=18))
    assert fhs == list(range(2, 19)) and not truncated


def test_plan_day_uses_local_dst_snapshot_hours():
    stations = {"KLAX": {"tz": "America/Los_Angeles"}}
    day = dt.date(2023, 12, 1)  # PST: 07:00 local = 15Z, 21:00 local = 05Z next day
    cycles = fetch.cycles_to_list(day, stations, [7], 3)
    sels, msgs = fetch.plan_day(day, stations, [7], 21, 3, MARGIN, {c: _avail(c) for c in cycles})
    assert sels[0]["snapshot_utc"] == "2023-12-01T15:00:00+00:00"
    assert sels[0]["cycle_utc"] == "2023-12-01T12:00:00+00:00"
    assert [fh for _, fh in msgs] == list(range(3, 18))


def test_season_dates_refuses_after_last_allowed_and_is_seeded():
    with pytest.raises(SystemExit):
        fetch.season_dates([2026], [9, 10], 1)
    a, b = fetch.season_dates([2024], [8], 5), fetch.season_dates([2024], [8], 5)
    assert a == b and sorted(a) == [dt.date(2024, 8, d) for d in range(1, 32)]


# --------------------------------------------------------------------------- offline end to end
class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content
        self.text = content.decode("latin-1")


class _FakeS3:
    """Serves listings, idx sidecars and synthetic messages for any HRRR cycle; counts requests."""

    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        if params:
            m = re.match(r"hrrr\.(\d{8})/conus/hrrr\.t(\d\d)z", params["prefix"])
            c = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H").replace(tzinfo=UTC)
            items = []
            for fh in range(19):
                lm = (c + dt.timedelta(minutes=60 + fh)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                key = fetch.grib_key(c, fh)
                size = 100 + len(_message(c, fh))
                for k, sz in ((key, size), (key + ".idx", 50)):
                    items.append(f"<Contents><Key>{k}</Key><LastModified>{lm}</LastModified>"
                                 f'<ETag>"x"</ETag><Size>{sz}</Size></Contents>')
            body = "<ListBucketResult><IsTruncated>false</IsTruncated>" + "".join(items) + "</ListBucketResult>"
            return _Resp(200, body.encode())
        m = re.search(r"hrrr\.(\d{8})/conus/hrrr\.t(\d\d)z\.wrfsfcf(\d\d)\.grib2(\.idx)?$", url)
        c = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H").replace(tzinfo=UTC)
        fh = int(m.group(3))
        msg = _message(c, fh)
        if m.group(4):
            idx = f"1:0:d=x:REFC:entire atmosphere:{fh} hour fcst:\n2:100:d=x:TMP:2 m above ground:{fh} hour fcst:\n"
            return _Resp(200, idx.encode())
        start, end = map(int, headers["Range"].split("=")[1].split("-"))
        blob = b"\0" * 100 + msg
        return _Resp(206, blob[start:end + 1])


def test_run_writes_manifest_and_selections_and_resumes_without_refetching(tmp_path):
    out = tmp_path / "hrrr"
    argv = ["--out", str(out), "--years", "2023", "--months", "8", "--stations", "KATL",
            "--limit-days", "1", "--pause", "0", "--min-free-gb", "0", "--disk-root", str(tmp_path),
            "--stop-file", str(tmp_path / "STOP"), "--variables", "TMP:2 m above ground"]
    s3 = _FakeS3()
    assert fetch.main(argv, session=s3) == 0
    manifest = [json.loads(line) for line in (out / "manifest.jsonl").read_text().splitlines()]
    sels = [json.loads(line) for line in (out / "selections.jsonl").read_text().splitlines()]
    assert len(sels) == 4 and all(s["cycle_utc"] for s in sels)  # 13-16 local
    assert manifest and all(r["status"] == "ok" and len(r["msg_sha256"]) == 64 for r in manifest)
    needed = {(s["cycle_utc"], fh) for s in sels for fh in s["fhs"]}
    assert {(r["cycle_utc"], r["fh"]) for r in manifest} == needed
    flat = fetch.station_cell(33.62972, -84.44223)["flat"]
    stations = json.loads((out / "stations.json").read_text())
    assert manifest[0]["points"]["KATL"]["nearest"] == 200.0 + stations["KATL"]["flat"] / 16384.0
    assert abs(stations["KATL"]["flat"] - flat) <= 1  # registry vs pinned coordinates
    assert json.loads((out / "status.json").read_text())["state"] == "complete"
    before = len(s3.calls)
    assert fetch.main(argv, session=s3) == 0
    assert len(s3.calls) == before  # the finished day is not listed or read again


def test_run_stops_at_the_byte_cap(tmp_path):
    out = tmp_path / "hrrr"
    argv = ["--out", str(out), "--years", "2023", "--months", "8", "--stations", "KATL",
            "--limit-days", "2", "--pause", "0", "--min-free-gb", "0", "--disk-root", str(tmp_path),
            "--stop-file", str(tmp_path / "STOP"), "--cap-gb", "0.000002"]
    assert fetch.main(argv, session=_FakeS3()) == 0
    assert json.loads((out / "status.json").read_text())["state"] == "cap_reached"


def test_a_variable_missing_from_the_idx_is_recorded_not_fatal(tmp_path):
    out = tmp_path / "hrrr"
    argv = ["--out", str(out), "--years", "2023", "--months", "8", "--stations", "KATL",
            "--limit-days", "1", "--pause", "0", "--min-free-gb", "0", "--disk-root", str(tmp_path),
            "--stop-file", str(tmp_path / "STOP")]  # default variables include TCDC, absent here
    assert fetch.main(argv, session=_FakeS3()) == 0
    rows = [json.loads(line) for line in (out / "manifest.jsonl").read_text().splitlines()]
    by_var = {v: {r["status"] for r in rows if r["var"] == v} for v in {r["var"] for r in rows}}
    assert by_var == {"TMP:2 m above ground": {"ok"}, "TCDC:entire atmosphere": {"decode_error"}}
    assert json.loads((out / "status.json").read_text())["state"] == "complete"
