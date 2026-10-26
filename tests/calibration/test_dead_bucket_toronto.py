"""Toronto dead-bucket history checks (lane L11).

Guards: pre-registered rule r2-toronto (docs/research/market-blend-l11-2026-10-25), native-unit settlement, evidence cutoff 2026-09-29.
"""
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

db = import_or_skip_on_capture_host("weather.calibration.dead_bucket")
tor = import_or_skip_on_capture_host("weather.calibration.dead_bucket_toronto")

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
