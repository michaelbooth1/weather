"""Lane L13: ECMWF ENS open-data forward recorder (tools/research/ecmwf_ens_forward_recorder.py).

Offline. A reference CCSDS/AEC encoder (written here from CCSDS 121.0-B: unit-delay preprocessor, zero-block runs
including the remainder-of-segment code, second extension, split-sample and uncompressed options) round-trips
through the recorder's decoder, full and partial. Synthetic GRIB2 messages (grid 3.0, product 4.11 / 4.1, data 5.42)
are served by a clock-driven fake ``data.ecmwf.int``.

Guards: pinned stations against the market registry, fail-closed
templates and stream length, the point-in-time receipt (run, Last-Modified, our fetch time, sha256), 404 before
publication is not a failure, slots close as missing, per-run manifests pin index and points, restarts are
idempotent, forward runs only, no GRIB on disk, STOP and pause.
"""
import datetime as dt
import json
import struct
from email.utils import format_datetime

import numpy as np
import pytest

from tools.research import ecmwf_ens_forward_recorder as ens

UTC = dt.timezone.utc
NPTS = ens.GRID["ni"] * ens.GRID["nj"]


# --------------------------------------------------------------------------- reference AEC encoder
def _map(x, prev, xmax):
    th = min(prev, xmax - prev)
    d = x - prev
    if 0 <= d <= th:
        return 2 * d
    if -th <= d < 0:
        return -2 * d - 1
    return th + abs(d)


class _Enc:
    def __init__(self, bps, block, rsi, pp=True, mode="auto"):
        self.bps, self.block, self.rsi, self.pp, self.mode = bps, block, rsi, pp, mode
        self.id_len = 5 if bps > 16 else 4 if bps > 8 else 3
        self.cache = {}

    def _rsi_bits(self, x):
        bps, block, xmax = self.bps, self.block, (1 << self.bps) - 1
        out = []
        put = lambda v, n: out.append(format(v, f"0{n}b")) if n else None  # noqa: E731
        fs = lambda v: out.append("0" * v + "1")  # noqa: E731
        if self.pp:
            mapped = [x[0]] + [_map(x[i], x[i - 1], xmax) for i in range(1, len(x))]
        else:
            mapped = list(x)
        nblocks = -(-len(mapped) // block)
        mapped += [0] * (nblocks * block - len(mapped))
        b = 0
        while b < nblocks:
            ref = self.pp and b == 0
            blk = mapped[b * block:(b + 1) * block]
            data = blk[1:] if ref else blk
            mode = self.mode if self.mode != "auto" else ("zero" if not any(data) else "split")
            if mode == "cycle":
                mode = ("split", "se", "uncomp")[b % 3] if any(data) else "zero"
            if mode == "se" and any(data[i] + (data[i + 1] if i + 1 < len(data) else 0) > 12
                                    for i in range(len(data))):
                mode = "split"
            if mode == "zero" and any(data):
                mode = "split"
            if mode == "zero":
                run = 1
                while b + run < nblocks and not any(mapped[(b + run) * block:(b + run + 1) * block]):
                    run += 1
                to_end = min(self.rsi - b, 64 - (b % 64))
                run = min(run, to_end)
                put(0, self.id_len)
                put(0, 1)
                if ref:
                    put(blk[0], bps)
                if run == to_end and run >= ens.ROS:
                    fs(ens.ROS - 1)
                elif run >= ens.ROS:
                    fs(run)
                else:
                    fs(run - 1)
                b += run
                continue
            if mode == "se":
                put(0, self.id_len)
                put(1, 1)
                if ref:
                    put(blk[0], bps)
                    pairs = [(0, blk[1])] + [(blk[i], blk[i + 1]) for i in range(2, block, 2)]
                else:
                    pairs = [(blk[i], blk[i + 1]) for i in range(0, block, 2)]
                for a, c in pairs:
                    fs((a + c) * (a + c + 1) // 2 + c)
            elif mode == "uncomp":
                put((1 << self.id_len) - 1, self.id_len)
                for v in blk:
                    put(v, bps)
            else:
                k = 0
                while k < bps - 1 and sum(v >> k for v in data) > 2 * len(data):
                    k += 1
                put(k + 1, self.id_len)
                if ref:
                    put(blk[0], bps)
                for v in data:
                    fs(v >> k)
                for v in data:
                    put(v & ((1 << k) - 1), k)
            b += 1
        return "".join(out)

    def encode(self, samples):
        rsi_n = self.rsi * self.block
        parts = []
        for s in range(0, len(samples), rsi_n):
            chunk = tuple(int(v) for v in samples[s:s + rsi_n])
            key = chunk if len(set(chunk)) > 1 else (chunk[0], len(chunk))
            if key not in self.cache:
                self.cache[key] = self._rsi_bits(list(chunk))
            parts.append(self.cache[key])
        bits = "".join(parts)
        bits += "0" * (-len(bits) % 8)
        return int(bits, 2).to_bytes(len(bits) // 8, "big") if bits else b""


def _flags(pp=True):
    return ens.AEC_DATA_MSB | ens.AEC_DATA_3BYTE | (ens.AEC_DATA_PREPROCESS if pp else 0)


@pytest.mark.parametrize("mode", ["auto", "cycle", "se", "uncomp"])
@pytest.mark.parametrize("pp", [True, False])
def test_aec_round_trip_all_options(mode, pp):
    rng = np.random.default_rng(7)
    n = 32 * 128 * 3 + 32 * 5  # three full RSIs and a partial one
    walk = np.clip(np.cumsum(rng.integers(-2, 3, n)) + 250, 0, 511)
    walk[4096:4096 + 32 * 70] = walk[4096]  # a long constant stretch: zero-block runs incl. remainder-of-segment
    walk[9000:9032] = 511  # a jump to the maximum
    walk[9032:9064] = 0
    enc = _Enc(9, 32, 128, pp=pp, mode=mode)
    data = enc.encode(walk)
    full = ens.aec_decode(data, 9, 32, 128, _flags(pp), n)
    assert np.array_equal(full, walk)
    want = [0, 31, 4095, 4096, 9000, 9063, n - 1]
    part = ens.aec_decode(data, 9, 32, 128, _flags(pp), n, want)
    assert part == {i: int(walk[i]) for i in want}


def test_aec_fails_closed():
    walk = np.full(32 * 128, 300)
    data = _Enc(9, 32, 128).encode(walk)
    with pytest.raises(ens.AecError):
        ens.aec_decode(data + b"\0\0", 9, 32, 128, _flags(), len(walk))  # trailing bytes: length mismatch
    rng = np.random.default_rng(1)
    noisy = rng.integers(0, 512, 32 * 128)
    data = _Enc(9, 32, 128).encode(noisy)
    with pytest.raises(ens.AecError):
        ens.aec_decode(data[: len(data) // 2], 9, 32, 128, _flags(), len(noisy))  # truncated
    for bad in (ens.AEC_DATA_SIGNED, ens.AEC_PAD_RSI, ens.AEC_RESTRICTED):
        with pytest.raises(ens.AecError):
            ens.aec_decode(data, 9, 32, 128, _flags() | bad, len(noisy))


# --------------------------------------------------------------------------- synthetic GRIB2
R0, E0, BPS = 200.0, -2, 9


def _field(base_k, station_k=None):
    x = np.full(NPTS, int(round((base_k - R0) * 4)), dtype=np.int64)
    for icao, k in (station_k or {}).items():
        for i in ens.CORNERS[icao]["idx"]:
            x[i] = int(round((k - R0) * 4))
    return x


ENC = _Enc(BPS, 32, 128)


def _grib(run, step, member, samples, param="mx2t3", grid_template=0, data_template=42):
    s1 = struct.pack(">IBHHBBBHBBBBBBB", 21, 1, 98, 0, 30, 0, 1, run.year, run.month, run.day, run.hour, 0, 0, 0, 1)
    s3 = bytearray(72)
    s3[0:4] = struct.pack(">I", 72)
    s3[4] = 3
    s3[6:10] = struct.pack(">I", NPTS)
    s3[12:14] = struct.pack(">H", grid_template)
    s3[14] = 6
    s3[30:34] = struct.pack(">I", 1440)
    s3[34:38] = struct.pack(">I", 721)
    s3[46:50] = struct.pack(">i", 90_000_000)
    s3[50:54] = struct.pack(">i", 180_000_000)
    s3[55:59] = struct.pack(">i", -90_000_000)
    s3[59:63] = struct.pack(">i", 179_750_000)
    s3[63:67] = struct.pack(">I", 250_000)
    s3[67:71] = struct.pack(">I", 250_000)
    if param == "mx2t3":
        s4 = bytearray(61)
        s4[7:9] = struct.pack(">H", 11)
        s4[18:22] = struct.pack(">I", step - 3)
        end = run + dt.timedelta(hours=step)
        s4[37:39] = struct.pack(">H", end.year)
        s4[39:44] = bytes([end.month, end.day, end.hour, 0, 0])
        s4[44] = 1
        s4[49], s4[50], s4[51] = 2, 2, 1
        s4[52:56] = struct.pack(">I", 3)
        s4[56] = 255
    else:
        s4 = bytearray(37)
        s4[7:9] = struct.pack(">H", 1)
        s4[18:22] = struct.pack(">I", step)
    s4[0:4] = struct.pack(">I", len(s4))
    s4[4] = 4
    s4[9], s4[10], s4[17] = 0, 0, 1
    s4[22], s4[34], s4[35], s4[36] = 103, 3, member, 51
    data = ENC.encode(samples)
    s5 = struct.pack(">IBIH", 25, 5, NPTS, data_template) + struct.pack(">f", R0) + struct.pack(">H", 0x8000 | -E0) \
        + struct.pack(">HBBBBH", 0, BPS, 0, _flags(), 32, 128)
    s6 = struct.pack(">IBB", 6, 6, 255)
    s7 = struct.pack(">IB", 5 + len(data), 7) + data
    body = s1 + bytes(s3) + bytes(s4) + s5 + s6 + s7 + b"7777"
    return b"GRIB\0\0\0\x02" + struct.pack(">Q", 16 + len(body)) + body


def test_grib_decode_points_and_checks():
    run = dt.datetime(2026, 11, 1, 0, tzinfo=UTC)
    msg = _grib(run, 24, 7, _field(280.0, {"CYYZ": 290.25, "KMIA": 301.0}))
    meta, vals = ens.decode_points(msg, ens.WANTED)
    ens.check_param(meta, "mx2t3")
    assert meta["ref_time"] == run and meta["member"] == 7 and meta["forecast_time"] == 21
    assert meta["stat_length"] == 3 and meta["packing"]["bps"] == BPS
    assert ens.point_values(vals, ens.CORNERS["CYYZ"])["bilinear_k"] == pytest.approx(290.25)
    assert ens.point_values(vals, ens.CORNERS["KMIA"])["corners_k"] == [301.0] * 4
    assert ens.point_values(vals, ens.CORNERS["KSEA"])["nearest_k"] == pytest.approx(280.0)
    meta2, _ = ens.decode_points(_grib(run, 24, 7, _field(280.0), param="2t"), ens.WANTED)
    ens.check_param(meta2, "2t")
    with pytest.raises(ValueError):
        ens.check_param(meta2, "mx2t3")
    with pytest.raises(ValueError):
        ens.decode_points(_grib(run, 24, 7, _field(280.0), grid_template=1), ens.WANTED)
    with pytest.raises(ValueError):
        ens.decode_points(_grib(run, 24, 7, _field(280.0), data_template=40), ens.WANTED)
    with pytest.raises(ValueError):
        ens.decode_points(msg[:-1] + b"8", ens.WANTED)


def test_station_pins_match_market_registry():
    from weather.market.market_registry import spec_for_id

    assert len(ens.STATIONS) == 12 and len({s[1] for s in ens.STATIONS}) == 12
    for market, icao, lat, lon in ens.STATIONS:
        spec = spec_for_id(market)
        assert abs(float(spec.lat) - lat) < 1e-3 and abs(float(spec.lon) - lon) < 1e-3, market
        c = ens.station_corners(lat, lon)
        j0, i0 = divmod(c["idx"][0], 1440)
        assert ens.GRID["la1"] - 0.25 * j0 >= lat > ens.GRID["la1"] - 0.25 * (j0 + 1)
        glon = (ens.GRID["lo1"] + 0.25 * i0) % 360
        assert 0 <= ((lon % 360) - glon) % 360 < 0.25


# --------------------------------------------------------------------------- fake server and recorder
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _member_k(member, step):
    return 270.0 + 0.25 * member + step / 3


class FakeECMWF:
    """Serves a run's step files once ``clock() >= run + lag``; Last-Modified = run + lag."""

    def __init__(self, clock, lag=dt.timedelta(hours=7), members=50):
        self.clock, self.lag, self.members = clock, lag, members
        self.used, self.requests, self.urls = 0, 0, []
        self.files = {}
        self.fail_steps = set()

    def _file(self, run, step):
        key = (run, step)
        if key not in self.files:
            idx, body = [], b""
            for member in range(1, self.members + 1):
                for param in ("2t", "mx2t3"):
                    msg = _grib(run, step, member, _field(280.0, {s[1]: _member_k(member, step) for s in ens.STATIONS}),
                                param=param)
                    idx.append({"domain": "g", "date": f"{run:%Y%m%d}", "time": f"{run:%H}00", "type": "pf",
                                "stream": "enfo", "step": str(step), "levtype": "sfc", "number": str(member),
                                "param": param, "_offset": len(body), "_length": len(msg)})
                    body += msg
            self.files[key] = ("".join(json.dumps(r) + "\n" for r in idx).encode(), body)
        return self.files[key]

    def get(self, url, byte_range=None, timeout=120):
        self.requests += 1
        self.urls.append((url, byte_range))
        name = url.rsplit("/", 1)[1]
        stamp, step_s = name.split("-")[0], name.split("-")[1]
        run = dt.datetime.strptime(stamp[:10], "%Y%m%d%H").replace(tzinfo=UTC)
        step = int(step_s[:-1])
        if self.clock() < run + self.lag:
            return ens.Resp(404, b"", {})
        if step in self.fail_steps:
            return ens.Resp(503, b"", {})
        index, body = self._file(run, step)
        lm = format_datetime(run + self.lag, usegmt=True)
        if url.endswith(".index"):
            self.used += len(index)
            return ens.Resp(200, index, {"Last-Modified": lm, "ETag": '"i"'})
        assert byte_range is not None, "the recorder must never GET a whole step file"
        part = body[byte_range[0]:byte_range[1] + 1]
        self.used += len(part)
        return ens.Resp(206, part, {"Last-Modified": lm, "ETag": '"g"', "Content-Length": str(len(part))})


RUN = dt.datetime(2026, 11, 1, 0, tzinfo=UTC)


def _rec(tmp_path, t, **kw):
    clock = Clock(t)
    http = FakeECMWF(clock, **{k: kw.pop(k) for k in ("members",) if k in kw})
    kw.setdefault("steps", (3, 6))
    kw.setdefault("cycles", (0,))
    kw.setdefault("first_run", RUN)
    r = ens.Recorder(tmp_path / "out", http, clock=clock, sleep=lambda s: None, min_free_gb=0, **kw)
    return r, http, clock


def test_point_in_time_receipt_and_manifest(tmp_path):
    r, http, clock = _rec(tmp_path, RUN + dt.timedelta(hours=6, minutes=30))
    assert r.step()["fetched_steps"] == 0  # index 404 before publication: not indexed, not a failure
    assert not (r.out / "2026110100" / "index.jsonl").exists() and not (r.out / "gaps.jsonl").exists()
    clock.t = RUN + dt.timedelta(hours=7, minutes=5)
    assert r.step()["fetched_steps"] == 2
    d = r.out / "2026110100"
    rows = ens.read_jsonl(d / "index.jsonl")
    steps = [x for x in rows if x["kind"] == "step"]
    assert [x["status"] for x in steps] == ["ok", "ok"] and steps[0]["members"] == 50
    assert all(len(x["messages"]) == 50 for x in steps)  # mx2t3 only: 2t is not fetched by default
    assert steps[0]["index_last_modified_utc"] == "2026-11-01T07:00:00+00:00"
    pts = ens.read_jsonl(d / "points.jsonl")
    assert len(pts) == 2 * 50 * 12
    p = next(x for x in pts if x["icao"] == "CYYZ" and x["member"] == 13 and x["step"] == 6)
    assert p["bilinear_k"] == pytest.approx(_member_k(13, 6), abs=0.13)
    assert p["param"] == "mx2t3" and p["window_h"] == 3 and p["valid_utc"] == "2026-11-01T06:00:00+00:00"
    assert p["run_utc"] == RUN.isoformat() and p["last_modified_utc"] == "2026-11-01T07:00:00+00:00"
    assert p["fetched_utc"] == clock.t.isoformat() and len(p["msg_sha256"]) == 64
    man = json.loads((d / "manifest.json").read_text())
    assert man["steps_ok"] == [3, 6] and man["steps_missing"] == [] and man["messages"] == 100
    assert man["index_sha256"] == ens.sha256((d / "index.jsonl").read_bytes())
    assert man["points_sha256"] == ens.sha256((d / "points.jsonl").read_bytes())
    assert all(u.endswith(".index") or rng is not None for u, rng in http.urls)
    kept = {p.suffix for p in r.out.rglob("*") if p.is_file()}
    assert kept <= {".jsonl", ".json"}  # point extractions only, never GRIB
    n = http.requests
    r2 = ens.Recorder(r.out, http, clock=clock, sleep=lambda s: None, min_free_gb=0, steps=(3, 6), cycles=(0,),
                      first_run=RUN)
    assert r2.step()["fetched_steps"] == 0 and http.requests == n  # idempotent restart


def test_params_add_2t(tmp_path):
    r, http, clock = _rec(tmp_path, RUN + dt.timedelta(hours=8), steps=(3,), params=("mx2t3", "2t"))
    r.step()
    pts = ens.read_jsonl(r.out / "2026110100" / "points.jsonl")
    assert {p["param"] for p in pts} == {"mx2t3", "2t"} and len(pts) == 2 * 50 * 12


def test_failures_then_missing_close(tmp_path):
    r, http, clock = _rec(tmp_path, RUN + dt.timedelta(hours=8))
    http.fail_steps = {6}
    r.step()
    d = r.out / "2026110100"
    st = [x for x in ens.read_jsonl(d / "index.jsonl") if x["kind"] == "step"]
    assert [(x["step"], x["status"]) for x in st] == [(3, "ok"), (6, "http_503")]
    assert not (d / "manifest.json").exists()
    clock.t = RUN + ens.CLOSE_AFTER
    r.step()
    gaps = ens.read_jsonl(r.out / "gaps.jsonl")
    assert [(g["gap"], g["step"]) for g in gaps] == [("missing", 6)]
    man = json.loads((d / "manifest.json").read_text())
    assert man["steps_ok"] == [3] and man["steps_missing"] == [6]


def test_too_few_members_is_invalid(tmp_path):
    r, http, clock = _rec(tmp_path, RUN + dt.timedelta(hours=8), members=49, steps=(3,))
    r.step()
    st = [x for x in ens.read_jsonl(r.out / "2026110100" / "index.jsonl") if x["kind"] == "step"]
    assert st[0]["status"] == "invalid" and "49 members" in st[0]["error"]
    assert not (r.out / "2026110100" / "points.jsonl").exists()


def test_forward_only(tmp_path):
    early = ens.FORWARD_FIRST - dt.timedelta(hours=12)
    r, http, clock = _rec(tmp_path, ens.FORWARD_FIRST + dt.timedelta(hours=5), first_run=early, cycles=(0, 12))
    assert r.first_run == ens.FORWARD_FIRST
    r.step()
    assert http.requests == 0  # the forward-first run is not published yet; the earlier 12z is never asked


def test_stop_and_pause(tmp_path):
    r, http, clock = _rec(tmp_path, RUN + dt.timedelta(hours=8))
    (r.out / "RECORDER_PAUSE").write_text("")
    assert r.step()["paused"] and http.requests == 0
    (r.out / "RECORDER_PAUSE").unlink()
    r.step()
    assert [g["gap"] for g in ens.read_jsonl(r.out / "gaps.jsonl")] == ["pause_start", "pause_end"]
    (r.out / "STOP").write_text("")
    r.run(poll_s=0, max_steps=5)
    assert json.loads((r.out / "status.json").read_text())["state"] == "stopped_by_file"


def test_output_must_be_outside_repo(tmp_path):
    from pathlib import Path

    repo = Path(ens.__file__).resolve().parents[2]
    with pytest.raises(SystemExit):
        ens.main(["--out", str(repo / "data" / "x"), "--once"])
