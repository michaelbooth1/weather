"""Offline checks for the L13 forward HRRR shadow recorder (no network; a clock-driven fake S3).

Guards: tools/research/hrrr_forward_recorder.py forward point-in-time contract (a snapshot row uses
only messages retrieved at or before the snapshot whose LastModified + 10 min is also at or before
it; a late cycle leaves the row on an older cycle or absent; rows are written once and never
backfilled, including across a restart and a RECORDER_PAUSE gap), the RN-1 land-aware point rule
(pinned land/stations shas, recomputed chosen index, KSFO index 3), the in-process bandwidth throttle
and hourly byte ceiling, and that nothing is fetched for a snapshot that has already passed.
"""
import datetime as dt
import hashlib
import json
import re
import struct

import pytest

from tools.research import hrrr_forward_recorder as rec
from tools.research import hrrr_point_fetch as fetch
from tests.sources.test_hrrr_point_fetch import SEC6, _Bits, _sec3, _sm16

UTC = dt.timezone.utc
STATIONS = {
    "KATL": {"lat": 33.62972, "lon": -84.44223, "tz": "America/New_York", "market": "atlanta"},
    "KSFO": {"lat": 37.61961, "lon": -122.36561, "tz": "America/Los_Angeles", "market": "san-francisco"},
}
LAND_KSFO = [1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def _msg(cycle, fh, tcdc=False):
    """HRRR-shaped TMP 2 m (or TCDC entire atmosphere) message with field value[k] = 200 + k / 16384."""
    npts = 1799 * 1059
    sec1 = struct.pack(">IBHHBBBHBBBBBBB", 21, 1, 7, 0, 2, 1, 1, cycle.year, cycle.month,
                       cycle.day, cycle.hour, 0, 0, 0, 1)
    cat, num, surf, sval = (6, 1, 10, 0) if tcdc else (0, 0, 103, 2)
    sec4 = struct.pack(">IBHHBBBBBHBBIBBIBBI", 34, 4, 0, 0, cat, num, 2, 0, 0x53, 0, 0, 1,
                       fh, surf, 0, sval, 255, 0, 0)
    b = _Bits()
    for v in (0, 1, 0):
        b.put_sm(v, 16)
    for _ in range(3):
        b.align()
        b.put(0, 1)
    body = b.tobytes()
    sec7 = struct.pack(">IB", 5 + len(body), 7) + body
    sec5 = struct.pack(">IBIHfHHBBBB", 49, 5, npts, 3, 200.0, _sm16(-14), 0, 1, 0, 1, 0)
    sec5 += struct.pack(">IIIBBIBIBBB", 0, 0, 1, 0, 1, 0, 1, npts, 1, 2, 2)
    payload = sec1 + _sec3() + sec4 + sec5 + SEC6 + sec7 + b"7777"
    return b"GRIB" + b"\0\0" + bytes([0, 2]) + struct.pack(">Q", 16 + len(payload)) + payload


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content
        self.text = content.decode("latin-1")


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += dt.timedelta(seconds=s)


class _TimedS3:
    """Publishes cycle c's fh at c + 50 min + 2 min * fh (+ a delay keyed by (cycle, fh) or by cycle);
    lists only what exists now."""

    def __init__(self, clock, delays=None):
        self.clock, self.delays, self.urls = clock, delays or {}, []

    def lm(self, c, fh):
        return c + dt.timedelta(minutes=50 + 2 * fh) + self.delays.get((c, fh), self.delays.get(c, dt.timedelta(0)))

    def blob(self, c, fh):
        tmp, tcdc = _msg(c, fh), _msg(c, fh, tcdc=True)
        idx = (f"1:0:d=x:REFC:entire atmosphere:{fh} hour fcst:\n"
               f"2:100:d=x:TMP:2 m above ground:{fh} hour fcst:\n"
               f"3:{100 + len(tmp)}:d=x:TCDC:entire atmosphere:{fh} hour fcst:\n")
        return b"\0" * 100 + tmp + tcdc, idx.encode()

    def get(self, url, headers=None, params=None, timeout=None):
        self.urls.append(url)
        if params:
            m = re.match(r"hrrr\.(\d{8})/conus/hrrr\.t(\d\d)z", params["prefix"])
            c = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H").replace(tzinfo=UTC)
            items = []
            for fh in range(19):
                if self.lm(c, fh) > self.clock():
                    continue
                lm = self.lm(c, fh).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                key = fetch.grib_key(c, fh)
                for k, sz in ((key, len(self.blob(c, fh)[0])), (key + ".idx", 120)):
                    items.append(f"<Contents><Key>{k}</Key><LastModified>{lm}</LastModified>"
                                 f'<ETag>"e{fh}"</ETag><Size>{sz}</Size></Contents>')
            body = "<ListBucketResult><IsTruncated>false</IsTruncated>" + "".join(items) + "</ListBucketResult>"
            return _Resp(200, body.encode())
        m = re.search(r"hrrr\.(\d{8})/conus/hrrr\.t(\d\d)z\.wrfsfcf(\d\d)\.grib2(\.idx)?$", url)
        c = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H").replace(tzinfo=UTC)
        blob, idx = self.blob(c, int(m.group(3)))
        if m.group(4):
            return _Resp(200, idx)
        start, end = map(int, headers["Range"].split("=")[1].split("-"))
        return _Resp(206, blob[start:end + 1])


def _land_file(tmp_path, cells, ksfo_index=3):
    st_bytes = rec.stations_json_bytes(STATIONS, cells)
    land = {"stations_json_sha256": hashlib.sha256(st_bytes).hexdigest(), "stations": {}}
    for st, c in cells.items():
        block = LAND_KSFO if st == "KSFO" else [1.0] * 9
        land["stations"][st] = {"i": c["i"], "j": c["j"], "flat": c["flat"], "land_block3x3": block,
                                "rn1_chosen_index": ksfo_index if st == "KSFO" else 4}
    p = tmp_path / "land_3x3.json"
    p.write_text(json.dumps(land), encoding="utf-8")
    return p, hashlib.sha256(p.read_bytes()).hexdigest(), land["stations_json_sha256"]


def _recorder(tmp_path, clock, s3, **kw):
    cells = {st: fetch.station_cell(m["lat"], m["lon"]) for st, m in STATIONS.items()}
    land, land_sha, st_sha = _land_file(tmp_path, cells)
    f = fetch.Fetcher(cap_bytes=10**12, pause=0.0, session=s3)
    return rec.Recorder(tmp_path / "out", STATIONS, land, f, clock=clock, sleep=clock.sleep,
                        disk_root=str(tmp_path), min_free_gb=0.0, expect_land_sha=land_sha,
                        expect_stations_sha=st_sha, **kw)


def _rows(out):
    return [json.loads(x) for x in (out / "snapshots.jsonl").read_text().splitlines()]


def _msgs(out):
    return [json.loads(x) for x in (out / "messages.jsonl").read_text().splitlines()]


def _run_until(r, clock, end, poll_s=120):
    while clock() < end:
        r.step()
        clock.sleep(r.next_wake(clock(), poll_s))


def test_rn1_index_uses_land_cells_and_ties_to_lower_index():
    ksfo = fetch.station_cell(37.61961, -122.36561)
    assert rec.rn1_index(ksfo, LAND_KSFO) == 3
    assert rec.rn1_index(ksfo, [1.0] * 9) == 4
    assert rec.rn1_index(ksfo, [0.0] * 9) is None
    tie = {"i": 10, "j": 10, "fi": 9.5, "fj": 10.0}
    assert rec.rn1_index(tie, [0, 0, 0, 1, 1, 0, 0, 0, 0]) == 3


def test_point_rule_refuses_wrong_land_sha_or_index(tmp_path):
    cells = {st: fetch.station_cell(m["lat"], m["lon"]) for st, m in STATIONS.items()}
    land, land_sha, st_sha = _land_file(tmp_path, cells)
    assert rec.load_point_rule(land, STATIONS, cells, land_sha, st_sha) == {"KATL": 4, "KSFO": 3}
    with pytest.raises(SystemExit, match="land file sha"):
        rec.load_point_rule(land, STATIONS, cells, "0" * 64, st_sha)
    with pytest.raises(SystemExit, match="stations.json sha"):
        rec.load_point_rule(land, STATIONS, cells, land_sha, "0" * 64)
    land, land_sha, st_sha = _land_file(tmp_path, cells, ksfo_index=6)
    with pytest.raises(SystemExit, match="recomputed RN-1 index"):
        rec.load_point_rule(land, STATIONS, cells, land_sha, st_sha)


def test_forward_rows_match_training_rule_rn1_values_and_never_fetch_for_past_snapshots(tmp_path):
    clock = _Clock(dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    s3 = _TimedS3(clock)
    r = _recorder(tmp_path, clock, s3)
    _run_until(r, clock, dt.datetime(2026, 10, 27, 1, 0, tzinfo=UTC))
    rows = _rows(r.out)
    assert sorted((x["station"], x["hour_local"]) for x in rows) == sorted(
        (st, hr) for st in STATIONS for hr in range(7, 17))
    for x in rows:
        assert x["k_miss"] == 0 and x["cycle_utc"] == x["training_rule_cycle_utc"]
        assert x["captured_at_utc_max"] <= x["snapshot_utc"]
        flat = r.cells[x["station"]]["flat"] - (1 if x["station"] == "KSFO" else 0)
        assert x["k_max_f"] == pytest.approx(((200 + flat / 16384) - 273.15) * 1.8 + 32, abs=1e-9)
        assert x["rn1_index"] == (3 if x["station"] == "KSFO" else 4) and x["point_rule"] == "RN-1"
        assert x["land_sha256"] == rec.LAND_SHA256 and len(x["hrrr_msg_sha256"]["TMP"]) == len(x["fhs"])
    ksfo = [x for x in rows if x["station"] == "KSFO"][0]
    assert ksfo["k_max_f"] != ksfo["k_max_f_nearest_cell"]
    snaps = sorted(x["snapshot_utc"] for x in rows)
    for m in _msgs(r.out):
        assert m["status"] == "ok" and m["captured_at_utc"] == m["retrieved_at_utc"] and m["fxx"] == m["fh"]
        assert m["retrieved_at_utc"] <= snaps[-1]
        assert m["points"]["KSFO"]["rn1"] == m["points"]["KSFO"]["block3x3"][3]
    # A message is only read when it can still serve a snapshot after the moment it was read.
    used = {(x["cycle_utc"], fh) for x in rows for fh in x["fhs"]}
    fetched = {(m["cycle_utc"], m["fh"]) for m in _msgs(r.out)}
    assert used <= fetched and len(fetched) <= 2 * len(used)


def test_a_late_cycle_is_not_backfilled_and_rows_are_written_once_across_restart(tmp_path):
    clock = _Clock(dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    late = dt.datetime(2026, 10, 26, 13, tzinfo=UTC)
    s3 = _TimedS3(clock, delays={late: dt.timedelta(hours=3)})
    r = _recorder(tmp_path, clock, s3)
    _run_until(r, clock, dt.datetime(2026, 10, 26, 17, 30, tzinfo=UTC))
    n = len(_rows(r.out))
    r2 = _recorder(tmp_path, clock, s3)  # restart on the same directory
    _run_until(r2, clock, dt.datetime(2026, 10, 27, 1, 0, tzinfo=UTC))
    rows = _rows(r.out)
    keys = [(x["station"], x["local_date"], x["hour_local"]) for x in rows]
    assert len(keys) == len(set(keys)) == 20 and n < 20
    assert all(x["cycle_utc"] != late.isoformat() for x in rows if x["snapshot_utc"] < "2026-10-26T16:10")
    assert any(x["depth"] >= 3 for x in rows)
    for x in rows:  # forward never picks a cycle newer than the training rule
        assert x["cycle_utc"] is None or x["cycle_utc"] <= (x["training_rule_cycle_utc"] or "")


def test_pause_gap_is_logged_and_not_backfilled(tmp_path):
    clock = _Clock(dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    pause = tmp_path / "RECORDER_PAUSE"
    r = _recorder(tmp_path, clock, _TimedS3(clock), pause_file=pause)
    _run_until(r, clock, dt.datetime(2026, 10, 26, 9, 0, tzinfo=UTC))
    pause.write_text("x")
    _run_until(r, clock, dt.datetime(2026, 10, 26, 13, 30, tzinfo=UTC))
    pause.unlink()
    _run_until(r, clock, dt.datetime(2026, 10, 27, 1, 0, tzinfo=UTC))
    gaps = [json.loads(x) for x in (r.out / "gaps.jsonl").read_text().splitlines()]
    assert [g["gap"] for g in gaps] == ["pause_start", "pause_end"]
    rows = {(x["station"], x["hour_local"]): x for x in _rows(r.out)}
    atl7 = rows[("KATL", 7)]  # 11Z snapshot fell inside the pause: nothing was read for it
    assert atl7["paused_at_snapshot"] and atl7["k_miss"] == 1 and atl7["cycle_utc"] is None
    assert all(m["retrieved_at_utc"] >= gaps[1]["at_utc"] or m["retrieved_at_utc"] <= gaps[0]["at_utc"]
               for m in _msgs(r.out))
    assert rows[("KATL", 16)]["k_miss"] == 0


def test_hourly_ceiling_and_bandwidth_throttle(tmp_path):
    clock = _Clock(dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    r = _recorder(tmp_path, clock, _TimedS3(clock), hourly_mb=0.000001)
    _run_until(r, clock, dt.datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
    assert not (r.out / "messages.jsonl").exists()
    events = [json.loads(x)["event"] for x in (r.out / "events.jsonl").read_text().splitlines()]
    assert "hourly_byte_ceiling" in events
    row = [x for x in _rows(r.out) if x["station"] == "KATL" and x["hour_local"] == 7][0]
    assert row["row_schema"] == 2 and row["k_miss"] == 1 and row["polls_in_prior_60m"] >= 25
    assert {"hourly_byte_ceiling"} <= {e["event"] for e in row["gap_events_prior_60m"]}
    assert row["last_poll_before_snapshot_utc"] <= row["snapshot_utc"]
    slept = []
    t = rec.Throttle(1_000_000, 10**9, sleep=slept.append)
    t.spent(2_000_000, 0.5)
    t.spent(100, 1.0)
    assert slept == [1.5]


def test_stations_json_bytes_reproduce_the_crlf_file_the_land_pin_was_taken_from():
    cells = {st: fetch.station_cell(m["lat"], m["lon"]) for st, m in STATIONS.items()}
    raw = rec.stations_json_bytes(STATIONS, cells)
    assert raw.startswith(b'{\r\n "KATL": {\r\n') and b"\n" not in raw.replace(b"\r\n", b"")


def test_gap_signals_use_only_state_at_or_before_the_snapshot_and_survive_restart(tmp_path):
    s = dt.datetime(2026, 10, 26, 15, tzinfo=UTC)
    m = dt.timedelta(minutes=1)
    polls = [s - 70 * m, s - 30 * m, s - 2 * m, s + 1 * m]
    events = [{"event": "low_disk", "at_utc": (s - 61 * m).isoformat()},
              {"event": "hourly_byte_ceiling", "at_utc": (s - 5 * m).isoformat()},
              {"event": "poll", "at_utc": (s - 2 * m).isoformat()},
              {"event": "step_error", "at_utc": (s + 1 * m).isoformat()}]
    sig = rec.gap_signals(s, polls, events, [(s - 50 * m, s - 40 * m)])
    assert sig["last_poll_before_snapshot_utc"] == (s - 2 * m).isoformat() and sig["polls_in_prior_60m"] == 2
    assert [e["event"] for e in sig["gap_events_prior_60m"]] == ["hourly_byte_ceiling"]
    assert not sig["paused_at_snapshot"] and sig["pause_overlaps_prior_60m"]
    assert rec.gap_signals(s, polls, events, [(s - 5 * m, None)])["paused_at_snapshot"]
    clock = _Clock(dt.datetime(2026, 10, 26, 10, 0, tzinfo=UTC))
    s3 = _TimedS3(clock)
    r = _recorder(tmp_path, clock, s3)
    _run_until(r, clock, dt.datetime(2026, 10, 26, 10, 50, tzinfo=UTC))
    r2 = _recorder(tmp_path, clock, s3)
    assert r2.poll_times == r.poll_times and len(r2.poll_times) >= 20
    _run_until(r2, clock, dt.datetime(2026, 10, 26, 11, 1, tzinfo=UTC))
    row = [x for x in _rows(r2.out) if x["station"] == "KATL" and x["hour_local"] == 7][0]
    assert row["polls_in_prior_60m"] >= 25 and row["k_miss"] == 0


def test_git_blob_id_matches_git_hash_object():
    assert rec.git_blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_lite_session_builds_query_reuses_one_tls_context_and_reconnects_once(monkeypatch):
    import http.client

    made, sent = [], []

    class _R:
        status = 206

        def read(self):
            return b"abc"

        def getheader(self, name):
            return None

    class _Conn:
        def __init__(self, host, context=None, timeout=None):
            made.append((host, context))
            self.fail = len(made) == 1

        def request(self, method, path, headers=None):
            sent.append((path, headers.get("Range")))
            if self.fail:
                raise http.client.RemoteDisconnected("idle close")

        def getresponse(self):
            return _R()

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", _Conn)
    s = rec.LiteSession()
    r = s.get("https://noaa-hrrr-bdp-pds.s3.amazonaws.com/", params={"list-type": "2", "prefix": "hrrr.x"})
    assert r.status_code == 206 and r.content == b"abc" and r.text == "abc"
    assert sent[-1][0] == "/?list-type=2&prefix=hrrr.x" and len(made) == 2
    assert made[0][1] is made[1][1] is s.ctx
    s.get("https://noaa-hrrr-bdp-pds.s3.amazonaws.com/k.grib2", headers={"Range": "bytes=1-2"})
    assert sent[-1] == ("/k.grib2", "bytes=1-2") and len(made) == 2


def test_messages_are_read_within_one_poll_of_listing_even_when_a_later_fh_is_late(tmp_path):
    start = dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    clock = _Clock(start)
    c13 = dt.datetime(2026, 10, 26, 13, tzinfo=UTC)
    s3 = _TimedS3(clock, delays={(c13, 5): dt.timedelta(minutes=20)})
    r = _recorder(tmp_path, clock, s3)
    _run_until(r, clock, dt.datetime(2026, 10, 27, 1, 0, tzinfo=UTC))
    rows = _rows(r.out)
    assert rows and all(x["k_miss"] == 0 and x["cycle_utc"] == x["training_rule_cycle_utc"] for x in rows)
    late = []
    for m in _msgs(r.out):
        c = dt.datetime.fromisoformat(m["cycle_utc"])
        lm = s3.lm(c, m["fh"])
        if lm < start + dt.timedelta(minutes=10):
            continue  # published before the recorder started: startup catch-up, excluded from F2
        lat = (dt.datetime.fromisoformat(m["retrieved_at_utc"]) - lm).total_seconds()
        if lat > 600:
            late.append((m["cycle_utc"], m["fh"], lat))
    assert late == []
    got = {m["fh"]: dt.datetime.fromisoformat(m["retrieved_at_utc"]) for m in _msgs(r.out)
           if dt.datetime.fromisoformat(m["cycle_utc"]) == c13 and m["var"].startswith("TMP")}
    for fh in (2, 3, 4):  # read before the out-of-order f05 is even published
        assert fh in got and got[fh] < s3.lm(c13, 5)


def test_lock_refuses_a_second_instance_and_a_waiting_replacement_takes_over(tmp_path):
    path = tmp_path / "recorder.lock"
    held = rec.acquire_lock(path)
    with pytest.raises(SystemExit, match="another recorder holds"):
        rec.acquire_lock(path)
    waits = []

    def release_after_two(s):
        waits.append(s)
        if len(waits) == 2:
            held.close()

    fh = rec.acquire_lock(path, wait_s=30.0, sleep=release_after_two)
    assert waits == [1.0, 1.0]
    fh.close()
