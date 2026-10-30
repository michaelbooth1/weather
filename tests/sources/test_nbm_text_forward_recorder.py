"""Lane L13 NBM text forward recorder (tools/research/nbm_text_forward_recorder.py).

Guards: fixed-width column parsing of NBH/NBS/NBE blocks (adjacent 3-digit cells, day rollover, FHR/UTC agreement,
NBE climatology columns kept apart), issuance-time and product checks, the listing LastModified as availability time,
the backfill flag, NBP closed as not issued only after the settle time, failed products closed missing after the
retry limit, live-then-catch-up cycle order, restart idempotence, the hourly byte ceiling, and pause and STOP files.
No network: an in-memory fake serves the S3 listing and the bulletins.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys

import pytest

from weather.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("nbm_text_forward_recorder",
                                               REPO_ROOT / "tools/research/nbm_text_forward_recorder.py")
rc = importlib.util.module_from_spec(_spec)
sys.modules["nbm_text_forward_recorder"] = rc
_spec.loader.exec_module(rc)

UTC = dt.timezone.utc
CYCLE = dt.datetime(2026, 10, 30, 22, tzinfo=UTC)
STATIONS = {"CYYZ": "toronto", "KLGA": "nyc"}


def nbh_block(station, cycle=CYCLE, product="NBH"):
    hours = [(cycle.hour + k) % 24 for k in range(1, 5)]
    return "\n".join([
        f" {station}   NBM V5.0 {product} GUIDANCE    {cycle:%m/%d/%Y}  {cycle:%H}00 UTC",
        " UTC  " + " ".join(f"{h:02d}" for h in hours),
        " TMP  50 49 48 47",
        " SKY  98 99100100",
        " CIG -88-88-88  5",
    ])


def nbs_block(station, cycle=CYCLE):
    return "\n".join([
        f" {station}    NBM V5.0 NBS GUIDANCE    {cycle:%m/%d/%Y}  {cycle:%H}00 UTC",
        " DT /OCT  31/NOV   1",
        " UTC  " + " ".join(f"{(cycle.hour + k) % 24:02d}" for k in (6, 9, 12)),
        " FHR  06 09 12",
        " TXN        57",
        " TMP  56 55 49",
    ])


def nbe_block(station, cycle=CYCLE):
    return "\n".join([
        f" {station}    NBM V5.0 NBE GUIDANCE    {cycle:%m/%d/%Y}  {cycle:%H}00 UTC",
        "   SAT 31 |SUN 01 |MON 02  CLIMO ",
        " UTC    " + f"{(cycle.hour + 14) % 24:02d}| {(cycle.hour + 2) % 24:02d}  {(cycle.hour + 14) % 24:02d}|",
        " FHR    14| 26  38|",
        " TXN    36| 59  40| -99-99",
        " P12     0|  1   1|  37 26",
    ])


def bulletin(product, cycle=CYCLE, stations=("CYYZ", "KLGA", "KXXX"), bad_issue=False):
    make = {"nbh": nbh_block, "nbs": nbs_block, "nbe": nbe_block, "nbp": nbs_block}[product]
    issued = cycle - dt.timedelta(hours=1) if bad_issue else cycle
    text = "\n".join(make(s, issued) for s in stations) + "\n"
    if product == "nbp":
        text = text.replace("NBS GUIDANCE", "NBP GUIDANCE")
    return text.encode("ascii")


class FakeHttp:
    def __init__(self):
        self.objects = {}  # key -> (bytes, last_modified)
        self.used = self.requests = 0
        self.gets = []

    def put(self, cycle, product, data=None, lm=None):
        self.objects[rc.object_key(cycle, product)] = (data if data is not None else bulletin(product, cycle),
                                                        lm or cycle + dt.timedelta(minutes=70))

    def get(self, url):
        self.requests += 1
        self.gets.append(url)
        if "?list-type=2" in url:
            prefix = url.split("prefix=")[1].split("&")[0]
            items = "".join(
                f"<Contents><Key>{k}</Key><LastModified>{lm:%Y-%m-%dT%H:%M:%S}.000Z</LastModified>"
                f"<ETag>&quot;e{len(b)}&quot;</ETag><Size>{len(b)}</Size></Contents>"
                for k, (b, lm) in sorted(self.objects.items()) if k.startswith(prefix))
            body = (f'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"<IsTruncated>false</IsTruncated>{items}</ListBucketResult>").encode()
            self.used += len(body)
            return rc.Resp(200, body, {})
        key = url.split(".com/", 1)[1]
        if key not in self.objects:
            return rc.Resp(404, b"", {})
        b, lm = self.objects[key]
        self.used += len(b)
        return rc.Resp(200, b, {"ETag": f'"e{len(b)}"', "Last-Modified": lm.strftime("%a, %d %b %Y %H:%M:%S GMT")})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _recorder(tmp_path, http, clock, **kw):
    kw.setdefault("bytes_per_s", 0)
    kw.setdefault("min_free_gb", 0)
    kw.setdefault("first_cycle", CYCLE)
    return rc.Recorder(tmp_path / "out", http, stations=STATIONS, clock=clock, sleep=lambda s: None, **kw)


def _rows(tmp_path, cycle=CYCLE):
    p = tmp_path / "out" / f"{cycle:%Y%m%d}" / f"{cycle:%H}" / "nbm_text.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()]


def test_nbh_columns_roll_over_midnight_and_split_adjacent_cells():
    lines = nbh_block("CYYZ").splitlines()
    cols, vals, unal = rc.parse_columns(lines, CYCLE)
    assert [c["fhr"] for c in cols] == [1, 2, 3, 4]
    assert cols[1]["valid_utc"] == "2026-10-31T00:00:00Z"
    assert vals["SKY"] == [98, 99, 100, 100] and vals["CIG"] == [-88, -88, -88, 5] and unal == {}


def test_nbs_uses_fhr_and_places_sparse_rows():
    cols, vals, _ = rc.parse_columns(nbs_block("CYYZ").splitlines(), CYCLE)
    assert [c["fhr"] for c in cols] == [6, 9, 12] and cols[0]["valid_utc"] == "2026-10-31T04:00:00Z"
    assert vals["TXN"] == [None, None, 57] and "DT" not in vals


def test_fhr_utc_disagreement_raises():
    lines = nbs_block("CYYZ").splitlines()
    lines[3] = " FHR  07 09 12"
    with pytest.raises(ValueError):
        rc.parse_columns(lines, CYCLE)


def test_nbe_climatology_columns_are_kept_apart():
    cols, vals, unal = rc.parse_columns(nbe_block("CYYZ").splitlines(), CYCLE)
    assert [c["fhr"] for c in cols] == [14, 26, 38]
    assert vals["TXN"] == [36, 59, 40] and unal == {"TXN": [-99, -99], "P12": [37, 26]}


def test_cycle_records_products_then_closes_nbp_as_not_issued_after_settle(tmp_path):
    http, clock = FakeHttp(), Clock(CYCLE + dt.timedelta(minutes=90))
    for p in ("nbh", "nbs", "nbe"):
        http.put(CYCLE, p)
    r = _recorder(tmp_path, http, clock)
    assert r.step() == {"fetched_products": 3, "cycles": ["2026-10-30T22:00:00Z"], "paused": False}
    rows = _rows(tmp_path)
    prods = {x["product"]: x for x in rows if x["kind"] == "product"}
    assert set(prods) == {"nbh", "nbs", "nbe"}
    nbh = prods["nbh"]
    assert nbh["status"] == "ok" and nbh["available_utc"] == "2026-10-30T23:10:00Z" and nbh["backfill"] is False
    assert nbh["fetch_lag_s"] == 1200.0 and nbh["stations_found"] == ["CYYZ", "KLGA"]
    blocks = [x for x in rows if x["kind"] == "block"]
    assert len(blocks) == 6 and {b["icao"] for b in blocks} == {"CYYZ", "KLGA"}  # KXXX dropped
    assert all(b["issued_utc"] == "2026-10-30T22:00:00Z" and b["parse_ok"] for b in blocks)
    assert rows.index(nbh) > max(i for i, x in enumerate(rows) if x["kind"] == "block" and x["product"] == "nbh")
    assert not (tmp_path / "out/20261030/22/manifest.json").exists()  # NBP may still come
    clock.t = CYCLE + rc.SETTLE
    r.step()
    man = json.loads((tmp_path / "out/20261030/22/manifest.json").read_text())
    assert man["products_ok"] == ["nbe", "nbh", "nbs"] and man["products_closed"] == {"nbp": "not_issued"}
    assert not (tmp_path / "out/gaps.jsonl").exists()  # NBP skipped hours are not gaps
    # restart: nothing fetched again, the closed cycle is not reopened
    n = len(http.gets)
    r2 = _recorder(tmp_path, http, clock)
    assert "2026-10-30T22:00:00Z" not in r2.step()["cycles"]
    assert not [u for u in http.gets[n:] if "20261030/22/" in u]


def test_catch_up_fetch_is_flagged_backfill_with_true_availability(tmp_path):
    http, clock = FakeHttp(), Clock(CYCLE + dt.timedelta(hours=5))
    for p in rc.PRODUCTS:
        http.put(CYCLE, p)
    r = _recorder(tmp_path, http, clock)
    r.step()
    prods = [x for x in _rows(tmp_path) if x["kind"] == "product"]
    assert len(prods) == 4 and all(x["backfill"] and x["available_utc"] == "2026-10-30T23:10:00Z" for x in prods)
    assert json.loads((tmp_path / "out/20261030/22/manifest.json").read_text())["backfill"]["nbp"] is True


def test_wrong_issuance_is_invalid_then_closed_missing(tmp_path):
    http, clock = FakeHttp(), Clock(CYCLE + dt.timedelta(minutes=90))
    http.put(CYCLE, "nbh", bulletin("nbh", bad_issue=True))
    r = _recorder(tmp_path, http, clock, products=("nbh",))
    for _ in range(rc.MAX_TRIES):
        r.step()
    rows = [x for x in _rows(tmp_path) if x["kind"] == "product"]
    assert len(rows) == rc.MAX_TRIES and all(x["status"] == "invalid" and "issued" in x["error"] for x in rows)
    assert not [x for x in _rows(tmp_path) if x["kind"] == "block"]
    r.step()
    assert _rows(tmp_path)[-2]["status"] == "missing"
    gaps = [json.loads(l) for l in (tmp_path / "out/gaps.jsonl").read_text().splitlines()]
    assert gaps[-1]["gap"] == "missing" and gaps[-1]["product"] == "nbh"


def test_torn_write_without_product_row_is_refetched(tmp_path):
    http, clock = FakeHttp(), Clock(CYCLE + dt.timedelta(minutes=90))
    http.put(CYCLE, "nbh")
    d = tmp_path / "out/20261030/22"
    d.mkdir(parents=True)
    (d / "nbm_text.jsonl").write_text('{"kind": "block", "product": "nbh", "icao": "CYYZ"}\n{"kind": "pro')
    r = _recorder(tmp_path, http, clock, products=("nbh",))
    assert r.step()["fetched_products"] == 1


def test_live_cycles_newest_first_then_catch_up_oldest_first(tmp_path):
    clock = Clock(CYCLE + dt.timedelta(hours=1, minutes=55))
    r = _recorder(tmp_path, FakeHttp(), clock, first_cycle=CYCLE - dt.timedelta(hours=4))
    got = [c.hour for c in r.open_cycles(clock())]
    assert got == [23, 22, 21, 20, 18, 19]  # 23Z..20Z live (<= 4 h) newest first, then 18Z, 19Z catch-up
    r.started = clock()
    clock.t += dt.timedelta(hours=3)
    assert [c.hour for c in r.open_cycles(clock())][:3] == [2, 1, 0]


def test_hourly_ceiling_stops_before_fetching(tmp_path):
    http, clock = FakeHttp(), Clock(CYCLE + dt.timedelta(minutes=90))
    http.put(CYCLE, "nbh")
    r = _recorder(tmp_path, http, clock, hourly_mb=1.0)  # below one bulletin's size hint
    assert r.step()["fetched_products"] == 0
    assert "hourly_byte_ceiling" in (tmp_path / "out/events.jsonl").read_text()


def test_pause_and_stop_files(tmp_path):
    http, clock = FakeHttp(), Clock(CYCLE + dt.timedelta(minutes=90))
    http.put(CYCLE, "nbh")
    r = _recorder(tmp_path, http, clock, products=("nbh",))
    (tmp_path / "out/RECORDER_PAUSE").write_text("")
    assert r.step() == {"fetched_products": 0, "cycles": [], "paused": True}
    (tmp_path / "out/RECORDER_PAUSE").unlink()
    (tmp_path / "out/STOP").write_text("")
    r.run(poll_s=0, max_steps=3)
    assert json.loads((tmp_path / "out/status.json").read_text())["state"] == "stopped_by_file"
    assert http.gets == []


def test_registry_gives_the_twelve_market_stations():
    st = rc.stations_from_registry()
    assert len(st) == 12 and st["CYYZ"] == "toronto" and set(st.values()) == set(rc.MARKETS)
