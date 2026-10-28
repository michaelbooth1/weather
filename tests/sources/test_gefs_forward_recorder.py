"""Lane L13: forward GEFS 06Z member recorder (tools/research/gefs_forward_recorder.py) for the L6_G forward test.

Guards the point-in-time rule of R-O (rule_rn.md L36-38): G at (market, D, h) uses only messages whose S3
LastModified (max of .grib2 and .idx) is at or before h:00 local, so a cycle published after h:00 is excluded, and
a late member drops out. It also guards: the dev corpus station geometry is pinned, forward dates only (no backfill
before 2026-10-28), the archive path refuses dates after 2026-09-29, each row carries the availability receipt
(LastModified, our fetch time, sha256), the day manifest is written once with the rows sha256, and STOP/pause work.
Offline: a clock-driven fake S3 and a stubbed decoder. The network parity check against the dev corpus is
``test_parity_against_dev_corpus`` and runs only when GEFS_FORWARD_PARITY_CORPUS names the corpus directory.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest

from tools.research import gefs_forward_recorder as rec
from tools.research import gefs_member_point_fetch as g

UTC = dt.timezone.utc
STATIONS = {m: {"lat": v[0], "lon": v[1], "tz": v[2]} for m, v in rec.DEV_STATIONS.items()}


def _k(f):
    return (f - 32.0) * 5.0 / 9.0 + 273.15


def _row(day, member, fh, avail, value_f, markets=("nyc",)):
    cycle = dt.datetime(day.year, day.month, day.day, 6, tzinfo=UTC)
    return {"kind": "message", "status": "ok", "date": day.isoformat(), "member": member, "fh": fh,
            "valid_utc": (cycle + dt.timedelta(hours=fh)).isoformat(), "available_utc": avail.isoformat(),
            "fetched_utc": avail.isoformat(), "points": {m: {"bilinear_k": _k(value_f)} for m in markets}}


def _day_rows(day, avail_for, value_for):
    return [_row(day, m, fh, avail_for(m, fh), value_for(m, fh)) for m in g.MEMBERS for fh in g.FHS]


# --------------------------------------------------------------------------- point-in-time rule (synthetic)
def test_cycle_published_after_cutoff_is_excluded():
    day = dt.date(2026, 8, 15)  # EDT: nyc h07 = 11:00Z, h08 = 12:00Z
    late = dt.datetime(2026, 8, 15, 11, 30, tzinfo=UTC)
    rows = _day_rows(day, lambda m, fh: late, lambda m, fh: 80.0 + fh / 10)
    table = rec.table_from_rows(rows)
    assert rec.g_value(table, "nyc", day, 7, "America/New_York") is None
    assert rec.g_value(table, "nyc", day, 8, "America/New_York") == pytest.approx(80.0 + 2.1)  # f021 (03Z D+1 = 23:00 EDT) is the last node on D
    exact = dt.datetime(2026, 8, 15, 11, 0, tzinfo=UTC)  # LastModified == h:00 is allowed (<=)
    table = rec.table_from_rows(_day_rows(day, lambda m, fh: exact, lambda m, fh: 70.0))
    assert rec.g_value(table, "nyc", day, 7, "America/New_York") == pytest.approx(70.0)


def test_late_member_and_late_step_drop_out_and_floor_25():
    day = dt.date(2026, 8, 15)
    on_time = dt.datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    late = dt.datetime(2026, 8, 15, 11, 1, tzinfo=UTC)
    value = lambda m, fh: 60.0 + (int(m[3:]) if m != "gec00" else 99)  # noqa: E731
    # gep30's f024 (valid 06Z D+1 = 02:00 EDT D+1, not local date D) is late: irrelevant, gep30 still counts
    rows = _day_rows(day, lambda m, fh: late if (m, fh) == ("gep30", 24) else on_time, value)
    assert rec.g_value(rec.table_from_rows(rows), "nyc", day, 7, "America/New_York") == pytest.approx(60 + 15.5)
    # gep30's f012 (16Z, local date D) is late: gep30 drops out, the mean is over gep01..gep29; gec00 never counts
    rows = _day_rows(day, lambda m, fh: late if (m, fh) == ("gep30", 12) else on_time, value)
    assert rec.g_value(rec.table_from_rows(rows), "nyc", day, 7, "America/New_York") == pytest.approx(60 + 15.0)
    # six perturbed members late: 24 < 25, no value
    rows = _day_rows(day, lambda m, fh: late if m in rec.PERTURBED[:6] else on_time, value)
    assert rec.g_value(rec.table_from_rows(rows), "nyc", day, 7, "America/New_York") is None


def test_fetched_rule_also_requires_our_fetch_by_cutoff():
    day = dt.date(2026, 8, 15)
    rows = _day_rows(day, lambda m, fh: dt.datetime(2026, 8, 15, 10, tzinfo=UTC), lambda m, fh: 75.0)
    for r in rows:
        r["fetched_utc"] = "2026-08-15T11:20:00+00:00"
    assert rec.g_value(rec.table_from_rows(rows), "nyc", day, 7, "America/New_York") == pytest.approx(75.0)
    assert rec.g_value(rec.table_from_rows(rows, require_fetched=True), "nyc", day, 7, "America/New_York") is None


# --------------------------------------------------------------------------- geometry and date guards
def test_geometry_pinned_to_dev_corpus_and_registry_agrees():
    stations, corners = rec.pinned_geometry()  # the live registry must still give the dev corpus geometry
    assert corners["nyc"]["i0"] == 1144 and corners["nyc"]["j0"] == 196
    assert corners["seattle"]["wx"] == pytest.approx(0.7423200000000634, abs=1e-12)
    moved = {**STATIONS, "nyc": {**STATIONS["nyc"], "lat": 40.8}}
    with pytest.raises(SystemExit):
        rec.pinned_geometry(moved)


def test_parity_path_refuses_dates_after_dev_last():
    with pytest.raises(SystemExit):
        rec.parity_day(None, dt.date(2026, 9, 30), {})


# --------------------------------------------------------------------------- recorder loop on a fake S3
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


class _FakeS3:
    """Serves member listings (prefix/start-after/max-keys), .idx files and Range reads of published objects."""

    def __init__(self, clock):
        self.clock, self.objects, self.calls = clock, {}, []

    def publish(self, day, member, fh, lm):
        key = g.grib_key(day, member, fh)
        blob = f"{day.isoformat()}|{member}|{fh}#".encode() * 4
        idx = f"1:0:d={day:%Y%m%d}06:TMP:2 m above ground:{fh} hour fcst:ENS=+1\n".encode()
        stamp = lm.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.objects[key] = (blob, stamp)
        self.objects[key + ".idx"] = (idx, stamp)

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if params:
            keys = sorted(k for k in self.objects if k.startswith(params["prefix"]) and k > params["start-after"])
            keys = keys[:int(params["max-keys"])]
            body = "".join(f"<Contents><Key>{k}</Key><LastModified>{self.objects[k][1]}</LastModified>"
                           f"<Size>{len(self.objects[k][0])}</Size><ETag>\"{hashlib.md5(self.objects[k][0]).hexdigest()}"
                           f"\"</ETag></Contents>" for k in keys)
            return _Resp(200, f"<ListBucketResult><IsTruncated>false</IsTruncated>{body}</ListBucketResult>".encode())
        key = unquote(url.split(".amazonaws.com/", 1)[1])
        if key not in self.objects:
            return _Resp(404, b"")
        blob = self.objects[key][0]
        if headers and "Range" in headers:
            a, b = (int(x) for x in headers["Range"].split("=")[1].split("-"))
            return _Resp(206, blob[a:b + 1])
        return _Resp(200, blob)


@pytest.fixture
def stub_decoder(monkeypatch):
    def decode(blob):
        day, member, fh = blob.decode().split("#")[0].split("|")
        fh = int(fh)
        pert = 0 if member == "gec00" else int(member[3:])
        d = dt.date.fromisoformat(day)
        meta = {"discipline": 0, "category": 0, "number": 0, "surface_type": 103, "surface_value": 2.0,
                "ref_time_utc": dt.datetime(d.year, d.month, d.day, 6, tzinfo=UTC).isoformat(), "fh": fh,
                "ensemble_type": 3 if pert else 1, "perturbation": pert, "ensemble_size": 31}
        return meta, np.full((721, 1440), _k(60.0 + pert))

    monkeypatch.setattr(g, "decode_field", decode)


def _recorder(tmp_path, clock, s3, **kw):
    f = g.Fetcher(10**12, session=s3, pause=0.0)
    return rec.Recorder(tmp_path / "out", f, stations=STATIONS, clock=clock, sleep=clock.sleep, **kw)


def test_forward_loop_receipts_manifest_and_no_backfill(tmp_path, stub_decoder):
    clock = _Clock(dt.datetime(2026, 10, 29, 9, 0, tzinfo=UTC))
    s3 = _FakeS3(clock)
    r = _recorder(tmp_path, clock, s3)
    day, prev = dt.date(2026, 10, 29), dt.date(2026, 10, 28)
    # 09:00Z: today not polled yet; yesterday (10-28, forward) is caught up and, past its deadline, closed
    assert r.step()["active_days"] == [str(prev)] and all("20261028" in str(c[1]) for c in s3.calls)
    assert json.loads((tmp_path / "out" / str(prev) / "manifest.json").read_text())["ok"] == 0
    for m in g.MEMBERS[:-1]:
        for fh in g.FHS:
            s3.publish(day, m, fh, dt.datetime(2026, 10, 29, 9, 40, tzinfo=UTC))
    clock.t = dt.datetime(2026, 10, 29, 9, 45, tzinfo=UTC)
    res = r.step()
    assert res["fetched"] == 30 * 7 and res["active_days"] == [str(day)]
    assert not (tmp_path / "out" / str(day) / "manifest.json").exists()
    for fh in g.FHS:
        s3.publish(day, "gep30", fh, dt.datetime(2026, 10, 29, 11, 30, tzinfo=UTC))  # after nyc h07 (11:00Z EDT)
    clock.t = dt.datetime(2026, 10, 29, 11, 35, tzinfo=UTC)
    assert r.step()["fetched"] == 7
    man = json.loads((tmp_path / "out" / str(day) / "manifest.json").read_text())
    rows_path = tmp_path / "out" / str(day) / "gefs_member_rows.jsonl"
    assert man["rows_sha256"] == hashlib.sha256(rows_path.read_bytes()).hexdigest() and man["ok"] == 217
    assert man["module_sha256"] == rec.DEV_MODULE_SHA256
    # h07: gep30 excluded (published after 11:00Z) -> mean of 60+1..60+29; h08: all 30
    assert man["g_lastmodified_rule"]["nyc"]["h07"] == pytest.approx(75.0)
    assert man["g_lastmodified_rule"]["nyc"]["h08"] == pytest.approx(75.5)
    rows = [json.loads(x) for x in rows_path.read_text().splitlines()]
    ok = [x for x in rows if x.get("status") == "ok"]
    assert all({"grib_last_modified", "idx_last_modified", "available_utc", "fetched_utc", "idx_fetched_utc",
                "idx_sha256", "message_sha256", "listed_utc"} <= set(x) for x in ok)
    assert all(set(rec.DEV_ROW_KEYS) <= set(x) for x in ok)
    assert ok[0]["fetched_utc"] == "2026-10-29T09:45:00+00:00"
    assert rows[-1]["kind"] == "date_done" and rows[-1]["missing"] == 0
    n = len(s3.calls)
    clock.t = dt.datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    assert r.step()["active_days"] == [] and len(s3.calls) == n  # both days closed (10-28 at its deadline)
    assert not any("20261027" in str(c) for c in s3.calls)  # never before FORWARD_FIRST


def test_deadline_closes_missing_slots_and_restart_reloads(tmp_path, stub_decoder):
    clock = _Clock(dt.datetime(2026, 10, 29, 10, 0, tzinfo=UTC))
    s3 = _FakeS3(clock)
    day = dt.date(2026, 10, 29)
    for m in g.MEMBERS[:20]:
        for fh in g.FHS:
            s3.publish(day, m, fh, dt.datetime(2026, 10, 29, 9, 50, tzinfo=UTC))
    r = _recorder(tmp_path, clock, s3, first_day=day)
    assert r.step()["fetched"] == 140
    r2 = _recorder(tmp_path, clock, s3, first_day=day)  # restart: nothing refetched
    n = len(s3.calls)
    assert r2.step()["fetched"] == 0 and all(c[1] for c in s3.calls[n:])  # listings only
    clock.t = dt.datetime(2026, 10, 30, 0, 1, tzinfo=UTC)
    r2.step()
    man = json.loads((tmp_path / "out" / str(day) / "manifest.json").read_text())
    assert man["ok"] == 140 and man["g_lastmodified_rule"]["nyc"]["h12"] is None  # 19 perturbed < 25
    rows = [json.loads(x) for x in (tmp_path / "out" / str(day) / "gefs_member_rows.jsonl").read_text().splitlines()]
    assert sum(x.get("status") == "object_missing" for x in rows) == 77


def test_stop_file_and_pause(tmp_path, stub_decoder):
    clock = _Clock(dt.datetime(2026, 10, 29, 10, 0, tzinfo=UTC))
    s3 = _FakeS3(clock)
    r = _recorder(tmp_path, clock, s3)
    (tmp_path / "out" / "RECORDER_PAUSE").write_text("")
    assert r.step() == {"fetched": 0, "active_days": [], "paused": True} and s3.calls == []
    (tmp_path / "out" / "RECORDER_PAUSE").unlink()
    r.step()
    gaps = (tmp_path / "out" / "gaps.jsonl").read_text().splitlines()
    assert [json.loads(x)["gap"] for x in gaps] == ["pause_start", "pause_end"]
    (tmp_path / "out" / "STOP").write_text("")
    r.run(poll_s=1, max_steps=5)
    assert json.loads((tmp_path / "out" / "status.json").read_text())["state"] == "stopped_by_file"


# --------------------------------------------------------------------------- network parity with the dev corpus
PARITY_DATES = ("2023-08-20", "2026-08-15", "2026-09-29")  # all <= 2026-09-29


@pytest.mark.skipif(not os.environ.get("GEFS_FORWARD_PARITY_CORPUS"), reason="network parity: set the corpus dir")
@pytest.mark.parametrize("day", PARITY_DATES)
def test_parity_against_dev_corpus(day):
    corpus = Path(os.environ["GEFS_FORWARD_PARITY_CORPUS"])
    man = json.loads((corpus / "manifest.json").read_text())
    assert man["module_sha256"] == rec.DEV_MODULE_SHA256 == hashlib.sha256(Path(g.__file__).read_bytes()).hexdigest()
    needle = f'"date": "{day}"'
    dev = [json.loads(x) for x in (corpus / "gefs_member_rows.jsonl").open(encoding="utf-8") if needle in x]
    dev = [x for x in dev if x.get("kind") == "message" and x["date"] == day]
    stations, corners = rec.pinned_geometry()
    assert stations == man["stations"] and corners == man["corners"]
    d = dt.date.fromisoformat(day)
    ours = rec.parity_day(g.Fetcher(int(2e9), session=rec.LiteSession()), d, corners)
    by_slot = {(x["member"], x["fh"]): x for x in ours}
    assert len(dev) == 217 and all(x["status"] == "ok" for x in dev)
    for x in dev:
        y = by_slot[(x["member"], x["fh"])]
        assert y["status"] == "ok"
        assert {k: y[k] for k in rec.DEV_ROW_KEYS} == {k: x[k] for k in rec.DEV_ROW_KEYS}
    g_dev, g_fwd = rec.g_table(dev, stations, d), rec.g_table(ours, stations, d)
    assert g_fwd == g_dev and sum(v is not None for m in g_dev.values() for v in m.values()) >= 60
    out = os.environ.get("GEFS_FORWARD_PARITY_REPORT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"date": day, "rows_compared": len(dev), "g": g_fwd}, sort_keys=True) + "\n")
