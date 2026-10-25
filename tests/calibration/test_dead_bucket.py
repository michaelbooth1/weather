from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from weather.calibration import dead_bucket as db

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
