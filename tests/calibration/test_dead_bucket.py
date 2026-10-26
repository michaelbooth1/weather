"""Dead-bucket NO-taker scans and reports (weather.calibration.dead_bucket; lane L11).

Guards: pre-registered dead-bucket rules r2/r3/r4 (docs/research/market-blend-l11-2026-10-25), evidence cutoff 2026-09-29, capture-time dating.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

db = import_or_skip_on_capture_host("weather.calibration.dead_bucket")

TZ = ZoneInfo("America/New_York")
D = date(2026, 8, 20)


def _day(temps, minute=53, tgroup=None):
    """Hourly obs at HH:minute local for hours 0..len-1 (tgroup optional per hour)."""
    rows = []
    for h, t in enumerate(temps):
        ts = pd.Timestamp(datetime(D.year, D.month, D.day, h, minute, tzinfo=TZ)).tz_convert("UTC")
        rows.append({"valid_utc": ts, "tmpf": float(t), "tgroup_f": tgroup[h] if tgroup else float("nan"),
                     "routine": True})
    return pd.DataFrame(rows)


def test_fee_value_and_rounding():
    assert db.fee(0.9) == pytest.approx(0.05 * 0.9 * 0.1)
    assert db.value(0.9) == pytest.approx(0.1 - 0.0045)
    assert db.H(80.5) == 81 and db.H(80.49) == 80 and db.H(None) is None


def test_steps_first_dead_and_cutoff():
    day = _day([70] * 10 + [80, 82, 84, 85, 86, 87, 88, 99])  # 17:53 obs (99) is after 16:59
    steps = db.h_steps(day, D, TZ)
    assert steps[-1][1] == 88 and all(a[1] <= b[1] for a, b in zip(steps, steps[1:]))
    fd = db.first_dead(steps, 83.0)  # H first > 83 at 12:53 (84)
    assert fd == datetime(2026, 8, 20, 12, 53, tzinfo=TZ) + timedelta(minutes=10)
    assert db.first_dead(steps, 88.0) is None


def test_tgroup_variant_and_classifier():
    temps = [70] * 14 + [84] + [83] * 3
    tg = [float("nan")] * 14 + [84.6] + [float("nan")] * 3
    day = _day(temps, tgroup=tg)
    end = db.local_instant(D, 16, 59, TZ)
    assert db.variant_h(day, D, TZ, "base", end) == 85
    assert db.variant_h(day, D, TZ, "tmpf", end) == 84
    assert db.classify({"tmpf": True, "routine": False, "both": True}, 600) == "tgroup_rounding"
    assert db.classify({"tmpf": False, "routine": True, "both": True}, 600) == "non_routine_max"
    assert db.classify({"tmpf": False, "routine": False, "both": True}, 600) == "rounding_and_non_routine"
    assert db.classify({"tmpf": False, "routine": False, "both": False}, 30) == "report_timing"
    assert db.classify({"tmpf": False, "routine": False, "both": False}, 900, "14:00") == "report_timing"
    assert db.classify({"tmpf": False, "routine": False, "both": False}, 900, "23:00") == "unexplained"


def test_summarise_mean_counts_missing_dates_as_zero():
    out = db.summarise({"2026-08-01": 10.0}, ["2026-08-01", "2026-08-02"])
    assert out["estimate"] == pytest.approx(5.0) and out["n_dates"] == 2 and out["n_dates_nonzero"] == 1
    assert out["ci95"][0] <= 5.0 <= out["ci95"][1]


def _layout(prices, winner):
    """One market-day, snapshots every 10 min 12:00..17:00 local; bands lte 80, eq 81-82, gte 83."""
    times = [datetime(2026, 8, 20, 12, 0, tzinfo=TZ) + timedelta(minutes=10 * i) for i in range(31)]
    snaps = pd.DataFrame({"row_key": [f"k{i}" for i in range(len(times))], "market": "atlanta",
                          "date": "2026-08-20", "captured_at_utc": [t.astimezone(timezone.utc).isoformat()
                                                                    for t in times]})
    geo = [(0, "lte", None, 80.0), (1, "eq", 81.0, 82.0), (2, "gte", 83.0, None)]
    bands = pd.DataFrame([{"row_key": k, "band_index": b, "kind": kd, "low": lo, "high": hi}
                          for k in snaps.row_key for b, kd, lo, hi in geo])
    market = pd.DataFrame([{"row_key": k, "band_index": b, "p_market_yes": prices(i, b)}
                           for i, k in enumerate(snaps.row_key) for b, *_ in geo])
    labels = pd.DataFrame({"row_key": snaps.row_key, "winner": winner, "settlement_high": 84.0})
    return SimpleNamespace(snaps=snaps, bands=bands, market=market, labels=labels)


def test_stage_c_entry_pnl_and_duration(tmp_path, monkeypatch):
    day = _day([70] * 13 + [84] * 5)  # H 84 from 13:53 -> lte 80 and eq 81-82 dead at 14:03
    obs = {"atlanta": {"tz": TZ, "days": {D: day}}}
    monkeypatch.setattr(db, "load_wu", lambda root, mk: (pd.DataFrame({"last_time": []}), None))
    monkeypatch.setattr(db, "MARKETS", ("atlanta",))
    # band 1 (eq) priced 0.10 YES until 14:30, then 0.0 ; band 0 priced 0.0 (no value: q = 1.01)
    prices = lambda i, b: {0: 0.0, 1: 0.10 if i <= 15 else 0.0, 2: 0.9}[b]  # noqa: E731
    trades, yes, dead = db.stage_c_trades(_layout(prices, 2), obs, None, ["atlanta"])
    by = {t["band_index"]: t for t in trades}
    assert dead[("atlanta", "2026-08-20")] == 2 and not yes
    assert by[0]["status"] == "no_value"
    t = by[1]
    assert t["status"] == "traded" and t["entry_hour"] == 14
    assert t["entry_instant"].startswith("2026-08-20T14:04:00")  # 13:53 + 10 min + 60 s
    assert t["snapshot_local"].startswith("2026-08-20T14:10")
    q = 0.91
    shares = 25 / q
    assert t["pnl_25"] == pytest.approx(shares * (1 - q) - shares * db.fee(q))
    assert t["duration_min"] == pytest.approx(36.0)  # 14:04 -> 14:40 (first snapshot priced 0)


def test_stage_c_settled_yes_loses_stake(monkeypatch):
    day = _day([70] * 13 + [84] * 5)
    obs = {"atlanta": {"tz": TZ, "days": {D: day}}}
    monkeypatch.setattr(db, "load_wu", lambda root, mk: (pd.DataFrame({"last_time": []}), None))
    monkeypatch.setattr(db, "MARKETS", ("atlanta",))
    prices = lambda i, b: {0: 0.0, 1: 0.10, 2: 0.9}[b]  # noqa: E731
    trades, yes, _ = db.stage_c_trades(_layout(prices, 1), obs, None, ["atlanta"])
    t = next(x for x in trades if x["band_index"] == 1)
    q = 0.91
    assert t["settled_yes"] and t["pnl_25"] == pytest.approx(-25 - (25 / q) * db.fee(q))
    assert len(yes) == 1 and yes[0]["cause"] == "unexplained"
    res = db.pnl_tables(trades, ["2026-08-20"], ["atlanta"], {"atlanta": 0.01})
    assert res["estimate"] == pytest.approx(t["pnl_25"])
    el = db.pnl_tables(trades, ["2026-08-20"], ["atlanta"], {"atlanta": 0.01}, expected_loss=True)
    assert el["estimate"] == pytest.approx(0.99 * (25 / q) * (1 - q) - 0.25 - (25 / q) * db.fee(q))


def test_reading_c():
    mk = lambda e, lo, hi: {"estimate": e, "ci95": [lo, hi]}  # noqa: E731
    assert db.reading_c({"primary_25": mk(1, -1, 0), "ladder": {"100": mk(4, 0, 1)}}).startswith("NOT WORTH")
    assert db.reading_c({"primary_25": mk(1, -1, 2), "ladder": {"100": mk(0.5, 0, 1)}}).startswith("NOT WORTH")
    assert db.reading_c({"primary_25": mk(1, -1, 2), "ladder": {"100": mk(4, 0, 9)}}).startswith("NOT EXCLUDED")


# ----------------------------------------------------------------------------- stage A (tiny fixture)

SLUG = "highest-temperature-in-atlanta-on-august-20-2026"
SUMMARY_HEADER = ("capture_id,captured_at_utc,event_slug,bin_kind,bin_value,bin_value_hi,outcome,clob_token_id,"
                  "best_bid,best_ask,bid_depth_1pct,ask_depth_1pct,bid_depth_5pct,ask_depth_5pct")


def _tapes(tmp_path, no_asks, prints, truncated_last=True):
    """Event folder: the eq 81-82 NO token asks ``no_asks`` [(local HH:MM, ask, depth1)], trades ``prints``."""
    root = tmp_path / "tapes"
    ev = root / SLUG
    (ev / "execution_tape").mkdir(parents=True)
    lines = [SUMMARY_HEADER]
    for i, (hm, ask, d1) in enumerate(no_asks):
        hh, mm = map(int, hm.split(":"))
        t = datetime(2026, 8, 20, hh, mm, tzinfo=TZ).astimezone(timezone.utc).isoformat()
        lines.append(f"c{i},{t},{SLUG},eq,81,82,No,tokNO,{1 - ask - 0.01:.3f},{ask},5,{d1},9,{d1 * 2}")
        lines.append(f"y{i},{t},{SLUG},eq,81,82,Yes,tokYES,{1 - ask:.3f},{1 - ask + 0.01:.3f},7,7,9,9")
    lines.append(f"x,2026-08-20T19:00:00+00:00,{SLUG},gte,83,83,No,tokG,0.1,0.2,1,1,1,1")
    body = "\n".join(lines) + "\n"
    body += 'big,2026-08-20T18:06:00+00:00,' + SLUG + ',eq,81,82,No,tokNO,0.1,"' + "x" * 200000 + '",1,1,1,1\n'
    if truncated_last:
        body += "partial,2026-08-20T19"  # a torn final row is skipped
    (ev / "order_books_summary.csv").write_text(body, encoding="utf-8")
    import json as _json
    with open(ev / "execution_tape" / "trades-00000.jsonl", "w", encoding="utf-8") as fh:
        for hm, token, price, size in prints:
            hh, mm = map(int, hm.split(":"))
            ms = int(datetime(2026, 8, 20, hh, mm, 30, tzinfo=TZ).timestamp() * 1000)
            fh.write(_json.dumps({"asset_id": token, "price": str(price), "size": str(size), "timestamp": str(ms),
                                  "side": "BUY", "transaction_hash": f"h{hm}{token}"}) + "\n")
    (root / "SHA256SUMS").write_text("", encoding="utf-8")
    return root


def _stage_a(tmp_path, monkeypatch, no_asks, prints, winner=2):
    day = _day([70] * 13 + [84] * 5)  # eq 81-82 dead: 13:53 + 10 min + 60 s = entry 14:04
    obs = {"atlanta": {"tz": TZ, "days": {D: day}}}
    monkeypatch.setattr(db, "MARKETS", ("atlanta",))
    prices = lambda i, b: 0.1  # noqa: E731
    root = _tapes(tmp_path, no_asks, prints)
    return db.stage_a_scan(_layout(prices, winner), obs, root, ["atlanta"], ["atlanta"])


def test_stage_a_fill_is_capped_by_prints_and_depth(tmp_path, monkeypatch):
    asks = [("14:00", 0.80, 100.0), ("14:06", 0.90, 20.0), ("14:20", 0.90, 20.0), ("14:30", 0.997, 20.0)]
    prints = [("14:05", "tokNO", 0.90, 8.0), ("14:06", "tokYES", 0.12, 3.0), ("14:07", "tokNO", 0.95, 50.0),
              ("14:30", "tokNO", 0.90, 99.0)]  # 0.95 is above q*; 14:30 is outside the 5-minute window
    buckets, days = _stage_a(tmp_path, monkeypatch, asks, prints)
    b = next(x for x in buckets if x["band_index"] == 1)
    assert b["status"] == "traded" and b["quote_source"] == "no_ask"
    assert b["q"] == pytest.approx(0.90) and b["capture_utc"].startswith("2026-08-20T18:06")  # first >= 14:04
    assert b["printed_shares"] == pytest.approx(11.0)  # 8 NO <= 0.90 plus 3 YES >= 0.10
    assert b["filled_print_d1_25"] == pytest.approx(11.0)
    assert b["filled_book_d1_25"] == pytest.approx(20.0)
    assert b["filled_print_d1_5"] == pytest.approx(5 / 0.9)
    assert b["pnl_print_d1_25"] == pytest.approx(11 * 0.1 - 11 * db.fee(0.9))
    assert b["duration_min"] == pytest.approx(26.0)  # 14:04 -> 14:30 (value < 0.005)
    lte = next(x for x in buckets if x["band_index"] == 0)
    assert lte["status"] == "no_capture"  # no lte 80 token in the summary
    assert days[0]["status"] == "scanned" and days[0]["trade_parts"] == 1
    assert days[0]["summary_bad_rows"] == 2  # the oversized and the torn row


def test_stage_a_settled_yes_loses_the_filled_cost(tmp_path, monkeypatch):
    asks = [("14:06", 0.90, 20.0)]
    buckets, _ = _stage_a(tmp_path, monkeypatch, asks, [("14:05", "tokNO", 0.90, 8.0)], winner=1)
    b = next(x for x in buckets if x["band_index"] == 1)
    assert b["settled_yes"] and b["pnl_print_d1_25"] == pytest.approx(-8 * 0.9 - 8 * db.fee(0.9))


def test_stage_a_no_value_and_report_windows(tmp_path, monkeypatch):
    buckets, days = _stage_a(tmp_path, monkeypatch, [("14:06", 0.999, 20.0)], [])
    b = next(x for x in buckets if x["band_index"] == 1)
    assert b["status"] == "no_value"
    traded = {"market": "atlanta", "date": "2026-08-20", "status": "traded", "entry_hour": 14, "q": 0.9,
              "printed_shares": 1.0, "trade_parts": 1, "settled_yes": False, "quote_source": "no_ask",
              "duration_min": 3.0, "excluded_market": False}
    for s in db.STAKES:
        for v in db.A_VARIANTS:
            traded[f"filled_{v}_{int(s)}"] = 1.0
            traded[f"pnl_{v}_{int(s)}"] = 0.05
    early = dict(traded, date="2026-08-05")
    res, summ = db.stage_a_report([traded, early], days, ["2026-08-05", "2026-08-20"], ["atlanta"], {"atlanta": 0.0})
    assert res["A_08-10..09-29"]["primary_25"]["estimate"] == pytest.approx(0.05)
    assert res["A_08-10..09-29"]["primary_25"]["n_dates"] == 1  # 08-05 never pooled into A
    assert res["book_only_08-01..08-09_separate"]["primary_25"]["estimate"] == pytest.approx(0.05)
    assert res["A_08-10..09-29"]["reading"].startswith("WORTH")
    assert summ["traded_08_10_on"] == 1


def test_discover_skips_folders_after_the_dev_window(tmp_path):
    for slug in (SLUG, "highest-temperature-in-atlanta-on-september-30-2026", "unrelated"):
        (tmp_path / slug).mkdir()
    assert list(db.discover_tape_events(tmp_path)) == [("atlanta", "2026-08-20")]


# ----------------------------------------------------------------------------- r3 windows (late, early)

def _stage_a_window(tmp_path, monkeypatch, temps, no_asks, prints, window):
    obs = {"atlanta": {"tz": TZ, "days": {D: _day(temps)}}}
    monkeypatch.setattr(db, "MARKETS", ("atlanta",))
    root = _tapes(tmp_path, no_asks, prints)
    return db.stage_a_scan(_layout(lambda i, b: 0.1, 2), obs, root, ["atlanta"], ["atlanta"], window)


def test_late_window_uses_evening_floor_and_entry(tmp_path, monkeypatch):
    temps = [70] * 18 + [84] * 4  # H 84 from 18:53 (after 16:59): eq 81-82 dead only in the late window
    asks = [("19:00", 0.80, 100.0), ("19:06", 0.90, 20.0)]
    prints = [("19:07", "tokNO", 0.90, 6.0)]
    buckets, days = _stage_a_window(tmp_path, monkeypatch, temps, asks, prints, "late")
    b = next(x for x in buckets if x["band_index"] == 1)
    assert b["entry_instant"].startswith("2026-08-20T19:04:00")  # 18:53 + 10 min + 60 s
    assert b["status"] == "traded" and b["entry_hour"] == 19 and b["q"] == pytest.approx(0.90)
    assert b["filled_print_d1_25"] == pytest.approx(6.0)
    assert b["duration_min"] == pytest.approx(115.0)  # 19:04 -> 20:59 (window end)
    b13, _ = _stage_a_window(tmp_path / "x", monkeypatch, temps, asks, prints, "13-16")
    assert not b13  # not dead by 16:59


def test_late_window_entry_is_never_before_17(tmp_path, monkeypatch):
    temps = [70] * 13 + [84] * 9  # dead from 14:03, so the late entry is 17:00
    buckets, _ = _stage_a_window(tmp_path, monkeypatch, temps, [("16:50", 0.5, 50.0), ("17:01", 0.9, 20.0)],
                                 [("17:02", "tokNO", 0.9, 2.0)], "late")
    b = next(x for x in buckets if x["band_index"] == 1)
    assert b["entry_instant"].startswith("2026-08-20T17:00:00") and b["q"] == pytest.approx(0.9)
    assert b["filled_print_d1_25"] == pytest.approx(2.0)


def test_early_window_floor_killed_only(tmp_path, monkeypatch):
    temps = [70] * 9 + [84] * 9  # H 84 from 09:53 -> entry 10:04
    buckets, _ = _stage_a_window(tmp_path, monkeypatch, temps, [("10:06", 0.90, 20.0)],
                                 [("10:08", "tokNO", 0.90, 4.0)], "early")
    b = next(x for x in buckets if x["band_index"] == 1)
    assert b["entry_instant"].startswith("2026-08-20T10:04:00") and b["entry_hour"] == 10
    assert b["filled_print_d1_25"] == pytest.approx(4.0)
    assert b["duration_min"] == pytest.approx(175.0)  # 10:04 -> 12:59
    late_kill = [70] * 13 + [84] * 5  # killed at 13:53: not dead by 12:59
    b2, _ = _stage_a_window(tmp_path / "y", monkeypatch, late_kill, [("14:06", 0.9, 20.0)], [], "early")
    assert not b2


def test_window_report_hours():
    traded = {"market": "atlanta", "date": "2026-08-20", "status": "traded", "entry_hour": 18, "q": 0.9,
              "printed_shares": 1.0, "trade_parts": 1, "settled_yes": False, "quote_source": "no_ask",
              "duration_min": 3.0, "excluded_market": False}
    for s in db.STAKES:
        for v in db.A_VARIANTS:
            traded[f"filled_{v}_{int(s)}"] = 1.0
            traded[f"pnl_{v}_{int(s)}"] = 0.05
    res, _ = db.stage_a_report([traded], [], ["2026-08-20"], ["atlanta"], {"atlanta": 0.0}, "late")
    assert set(res["A_08-10..09-29"]["per_hour_25"]) == {"17", "18", "19", "20"}
    assert res["A_08-10..09-29"]["per_hour_25"]["18"]["estimate"] == pytest.approx(0.05)


def test_r3_history_adds_cutoffs_without_changing_r2(monkeypatch):
    temps = [70] * 13 + [84] * 9  # 12 METAR rows by 16:59 hold (17 rows)
    day = _day(temps)
    obs = {"atlanta": {"tz": TZ, "days": {date(2021, 8, 20): day.assign(
        valid_utc=day.valid_utc - pd.Timedelta(days=365 * 5 + 1))}, "station": "KATL",
        "modal_minute_by_year": {}}}
    wu = pd.DataFrame({"row_count": [24], "first_time": ["00:00"], "last_time": ["23:59"],
                       "max_temp_native": [80.0]}, index=[date(2021, 8, 20)])
    monkeypatch.setattr(db, "MARKETS", ("atlanta",))
    monkeypatch.setattr(db, "load_wu", lambda root, mk: (wu, "p"))
    monkeypatch.setattr(db, "sha256_file", lambda p: "s")
    r2 = db.history(obs, None)
    r3 = db.history(obs, None, extra=db.R3_EXTRA_CUTOFFS)
    rates2, rates3 = r2["per_market"]["atlanta"]["rates"], r3["per_market"]["atlanta"]["rates"]
    assert {c: rates3[c] for c in rates2} == rates2
    assert rates3["12:59"] == 0.0 and rates3["16:59"] == 1.0 and rates3["20:59"] == 1.0
