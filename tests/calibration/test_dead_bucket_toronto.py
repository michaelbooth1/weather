import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from weather.calibration import dead_bucket as db
from weather.calibration import dead_bucket_toronto as tor

TZ = ZoneInfo("America/Toronto")
D = date(2026, 8, 20)
SLUG = "highest-temperature-in-toronto-on-august-20-2026"


def test_celsius_labels_parse_natively_with_open_ends():
    assert tor.bucket_from_label("25 C", "eq", "25", "25", "C") == (("eq", 25, 25), 25)
    assert tor.bucket_from_label("25°C", "eq", "25", "", "°C") == (("eq", 25, 25), 25)
    assert tor.bucket_from_label("17 C or below", "lte", "17", "17", "C") == (("lte", 17), 17)  # open bottom
    assert tor.bucket_from_label("30 C or higher", "gte", "30", "30", "C") == (("gte", 30), None)  # open top
    assert tor.bucket_from_label("-2 C", "eq", "-2", "-2", "C") == (("eq", -2, -2), -2)
    assert tor.bucket_from_label("−3 C or below", "lte", "-3", "-3", "C") == (("lte", -3), -3)


def test_label_mismatch_or_fahrenheit_is_refused():
    assert tor.bucket_from_label("77 F", "eq", "77", "77", "F") is None  # never converted
    assert tor.bucket_from_label("25 C", "eq", "25", "25", "F") is None
    assert tor.bucket_from_label("25 C", "eq", "24", "24", "C") is None
    assert tor.bucket_from_label("25 C", "lte", "25", "25", "C") is None
    assert tor.bucket_from_label("25.5 C", "eq", "25.5", "25.5", "C") is None


def test_settlement_in_whole_celsius():
    assert tor.settled_yes(("lte", 17), 17.0) and not tor.settled_yes(("lte", 17), 18.0)
    assert tor.settled_yes(("eq", 25, 25), 25.0) and not tor.settled_yes(("eq", 25, 25), 26.0)
    assert tor.settled_yes(("gte", 30), 31.0)


def test_tgroup_tenths_and_floor_comparison_in_native_celsius():
    assert tor.tgroup_c("CYYZ 201800Z 24.6 RMK T02460150") == pytest.approx(24.6)
    assert tor.tgroup_c("CYYZ 201800Z RMK T12460150") == pytest.approx(-24.6)
    assert tor.tgroup_c("CYYZ 201800Z 25/15 A3012") is None
    day = _day([18] * 12 + [24] * 2, tgroup={13: 24.6})  # 13:53 T-group 24.6 C -> H = 25
    steps = tor.steps_c(day, D, TZ)
    assert steps[-1][1] == 25
    fd = db.first_dead(steps, 24.0)  # bucket 24 C: dead once H = 25 > 24
    assert fd == datetime(2026, 8, 20, 13, 53, tzinfo=TZ) + timedelta(minutes=10)
    assert db.first_dead(steps, 25.0) is None  # bucket 25 C is not below H = 25


def _day(temps, tgroup=None, minute=0):
    rows = []
    for h, t in enumerate(temps):
        ts = pd.Timestamp(datetime(D.year, D.month, D.day, h, minute, tzinfo=TZ)).tz_convert("UTC")
        tg = (tgroup or {}).get(h)
        rows.append({"valid_utc": ts + pd.Timedelta(minutes=53), "tmpc": float(t),
                     "tgroup_c": tg if tg is not None else float("nan"), "routine": True})
    return pd.DataFrame(rows)


HEADER = ("capture_id,captured_at_utc,event_slug,range_label,bin_kind,bin_value,bin_value_hi,unit,outcome,"
          "clob_token_id,best_bid,best_ask,bid_depth_1pct,ask_depth_1pct,bid_depth_5pct,ask_depth_5pct")


def _tapes(tmp_path, asks, prints):
    root = tmp_path / "tapes"
    ev = root / SLUG
    (ev / "execution_tape").mkdir(parents=True)
    lines = [HEADER]
    for i, (hm, ask, d1) in enumerate(asks):
        hh, mm = map(int, hm.split(":"))
        t = datetime(2026, 8, 20, hh, mm, tzinfo=TZ).astimezone(timezone.utc).isoformat()
        lines.append(f"n{i},{t},{SLUG},24 C,eq,24,24,C,No,tok24N,{1 - ask - 0.01:.3f},{ask},5,{d1},9,{d1 * 2}")
        lines.append(f"y{i},{t},{SLUG},24 C,eq,24,24,C,Yes,tok24Y,{1 - ask:.3f},{1 - ask + 0.01:.3f},7,7,9,9")
        lines.append(f"b{i},{t},{SLUG},18 C or below,lte,18,18,C,No,tok18N,0.998,,5,0,9,0")
        lines.append(f"m{i},{t},{SLUG},23 C,eq,24,24,C,No,tokBAD,0.1,0.5,1,1,1,1")  # label disagrees
        lines.append(f"g{i},{t},{SLUG},30 C or higher,gte,30,30,C,No,tok30N,0.1,0.2,1,1,1,1")
    (ev / "order_books_summary.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(ev / "execution_tape" / "trades-00000.jsonl", "w", encoding="utf-8") as fh:
        for hm, token, price, size in prints:
            hh, mm = map(int, hm.split(":"))
            ms = int(datetime(2026, 8, 20, hh, mm, 30, tzinfo=TZ).timestamp() * 1000)
            fh.write(json.dumps({"asset_id": token, "price": str(price), "size": str(size), "timestamp": str(ms),
                                 "side": "BUY", "transaction_hash": f"h{hm}{token}"}) + "\n")
    return root


def test_toronto_stage_a_fixture(tmp_path):
    day = _day([18] * 12 + [24] * 6, tgroup={13: 24.6})  # H 25 from 13:53 -> 24 C and 18 C-or-below dead
    obs = {"tz": TZ, "days": {D: day}}
    wu = pd.DataFrame({"max_temp_native": [25.0]}, index=[D])
    root = _tapes(tmp_path, [("14:00", 0.80, 100.0), ("14:06", 0.90, 20.0)], [("14:06", "tok24N", 0.90, 7.0)])
    buckets, days = tor.stage_a_scan(obs, wu, root, ["toronto"])
    by = {tuple(b["bucket"]): b for b in buckets}
    b = by[("eq", 24, 24)]
    assert b["status"] == "traded" and b["q"] == pytest.approx(0.90) and not b["settled_yes"]
    assert b["entry_instant"].startswith("2026-08-20T14:04:00")  # 13:53 + 10 min + 60 s
    assert b["filled_print_d1_25"] == pytest.approx(7.0)
    assert by[("lte", 18)]["status"] == "no_capture"  # NO bid 0.998 and no NO ask: nothing to buy
    assert days[0]["summary"]["label_mismatch"] == 2 and days[0]["summary"]["gte"] == 2
    res, summ = tor.stage_a_report(buckets, days, ["2026-08-20"], ["toronto"], 0.0)
    assert res["A_08-10..09-29"]["primary_25"]["estimate"] == pytest.approx(7 * 0.1 - 7 * db.fee(0.9))
    excluded, _ = tor.stage_a_report(buckets, days, ["2026-08-20"], [], 0.0)
    assert excluded["A_08-10..09-29"]["primary_25"]["estimate"] == 0.0


def _replay(tmp_path, snaps):
    """Replay root: snapshots [(local HH:MM captured, [(obs local HH:MM, temp C)])] for SLUG."""
    root = tmp_path / "replay"
    ev = root / "snapshots" / SLUG
    ev.mkdir(parents=True)
    with open(ev / "replay_inputs.jsonl", "w", encoding="utf-8") as fh:
        for cap, rows in snaps:
            hh, mm = map(int, cap.split(":"))
            t = datetime(2026, 8, 20, hh, mm, 5, tzinfo=TZ)
            out = []
            for ohm, temp in rows:
                oh, om = map(int, ohm.split(":"))
                o = datetime(2026, 8, 20, oh, om, tzinfo=TZ).astimezone(timezone.utc)
                out.append({"raw": f"METAR CYYZ {o:%d%H%M}Z 00000KT 15SM FEW040 A3000",
                            "report_time": (o + timedelta(minutes=7)).isoformat().replace("+00:00", "Z"),
                            "temp_native": float(temp)})
            fh.write(json.dumps({"captured_at_local": t.isoformat(),
                                 "captured_at_utc": t.astimezone(timezone.utc).isoformat(),
                                 "sources": {"metar": {"data": {"rows": out}}}}) + "\n")
    return root


def test_r4_toronto_capture_dating_in_native_celsius_and_parse_check(tmp_path):
    early = [(f"{h:02d}:53", 18) for h in range(13)]
    snaps = [("14:00", early), ("14:10", early + [("13:53", 25)])]  # 25 C kills 24 C at the 14:10 receipt
    day = _day([18] * 13 + [25] * 5)
    obs = {"tz": TZ, "days": {D: day}}
    wu = pd.DataFrame({"max_temp_native": [25.0]}, index=[D])
    root = _tapes(tmp_path, [("14:00", 0.80, 100.0), ("14:12", 0.90, 20.0)], [("14:12", "tok24N", 0.90, 7.0)])
    buckets, days = tor.stage_a_scan(obs, wu, root, ["toronto"], "capture", _replay(tmp_path, snaps))
    b = {tuple(x["bucket"]): x for x in buckets}[("eq", 24, 24)]
    assert b["first_dead"].startswith("2026-08-20T14:10:05")  # receipt, no +10 min
    assert b["first_dead_obs10"].startswith("2026-08-20T14:03:00")
    assert b["entry_instant"].startswith("2026-08-20T14:11:05")
    assert b["status"] == "traded" and b["filled_print_d1_25"] == pytest.approx(7.0)
    assert days[0]["H_s_last_c"] == 25 and days[0]["H_1659_c"] == 25  # whole C, never a F value
    assert days[0]["partition_ok"] is False  # 18-or-below, 24, 30-or-higher leaves gaps
    _, summ = tor.stage_a_report(buckets, days, ["2026-08-20"], ["toronto"], 0.0)
    assert summ["r4"]["verdict"] == "PASS" and summ["r4"]["celsius_sanity"]["share"] == 1.0
    pc = summ["parse_check"]
    assert pc["distinct_failures"] == 1 and pc["failures"][0]["label"] == "23 C"  # listed, not coerced
    assert pc["parsed"]["18 C or below"] == ["lte", 18] and pc["parsed"]["30 C or higher"] == ["gte", 30]
    assert pc["days_not_a_partition"] == ["2026-08-20"]
    lf = summ["label_free_no_ask"]  # clarification 1: NO ask 0.90 from 14:12, depth 20, value >= 0.005
    assert lf["dead_buckets"] == 2 and lf["with_qualifying_no_ask"] == 1
    assert lf["sum_first_ask_depth_1pct"] == pytest.approx(20.0) and lf["per_first_hour"] == {"14": 1}
    nolabel = pd.DataFrame({"max_temp_native": [float("nan")]}, index=[D])
    b2, d2 = tor.stage_a_scan(obs, nolabel, root, ["toronto"], "capture", tmp_path / "replay")
    assert not b2 and d2[0]["status"] == "no_wu_label"  # never in the primary, still measured label-free
    assert sum(x["qualifying_snapshots"] > 0 for x in d2[0]["label_free"]) == 1


def test_partition_check_and_fahrenheit_floor_fails_celsius_sanity():
    assert tor.partition_ok([("lte", 17), ("eq", 18, 18), ("eq", 19, 19), ("gte", 20)])
    assert not tor.partition_ok([("lte", 17), ("eq", 19, 19), ("gte", 20)])
    days = [{"date": "2026-08-20", "H_s_last_c": 77, "H_1659_c": 25}]  # a F-valued floor misses by ~50
    assert tor.r4_controls([], days)["verdict"] == "FAIL"


HDR = "schema_version,local_date,temperature_unit,row_count,last_time,max_temp_native\n"


def _wu(tmp_path, pinned, extra):
    root = tmp_path / "wu"
    (root / "cyyz" / "daily").mkdir(parents=True)
    (root / "cyyz" / "daily" / "daily_summary.csv").write_text(HDR + pinned, encoding="utf-8")
    ex = tmp_path / "extra.csv"
    ex.write_text(HDR + extra, encoding="utf-8")
    return root, ex


def test_appended_wu_input_fails_closed(tmp_path, monkeypatch):
    ok = "v2,2026-08-11,C,24,23:00,27\nv2,2026-09-29,C,24,23:00,19\n"
    root, ex = _wu(tmp_path, "v2,2026-08-10,C,24,23:00,26\nv2,2026-10-02,C,24,23:00,99\n", ok)
    monkeypatch.setattr(tor, "WU_EXTRA_SHA256", db.sha256_file(ex))
    w, _ = tor.load_wu(root, ex, db.sha256_file(ex))
    assert [str(d) for d in w.index] == ["2026-08-10", "2026-08-11", "2026-09-29"]  # pinned 10-02 dropped
    with pytest.raises(db.data.Refused):
        tor.load_wu(root, ex, "0" * 64)  # sha mismatch
    bads = ("v2,2026-08-10,C,24,23:00,26\n",  # duplicates a pinned date
            "v2,2026-09-30,C,24,23:00,20\n",  # after the dev window
            "v2,2026-08-12,C,24,23:00,27\nv2,2026-08-12,C,24,23:00,27\n",  # duplicate within the input
            "v2,2026-08-13,F,24,23:00,80\n")  # not native Celsius
    for i, bad in enumerate(bads):
        root, ex = _wu(tmp_path / f"bad{i}", "v2,2026-08-10,C,24,23:00,26\n", bad)
        monkeypatch.setattr(tor, "WU_EXTRA_SHA256", db.sha256_file(ex))
        with pytest.raises(db.data.Refused):
            tor.load_wu(root, ex, db.sha256_file(ex))
