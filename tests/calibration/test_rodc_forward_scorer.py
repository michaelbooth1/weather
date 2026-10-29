"""R-ODC forward scorer: look/embargo refusals, P1 and P2 on synthetic rows only (no forward data is read)."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from weather.calibration import rodc_forward_scorer as fs
from weather.sources.wu_history import WundergroundHistoryStore

TZ = ZoneInfo("America/New_York")
D = date(2026, 11, 10)
CTX = fs.LookContext(freeze_date=date(2026, 10, 30), d0=date(2026, 10, 30), look_date=date(2026, 12, 14),
                     b_receipt_date=date(2026, 12, 14), today=date(2026, 12, 14))


@pytest.mark.parametrize("change, match", [
    ({"freeze_date": date(2026, 10, 29), "d0": date(2026, 10, 29)}, "freeze"),
    ({"d0": date(2026, 10, 29)}, "D0"),
    ({"look_date": date(2026, 12, 13), "b_receipt_date": date(2026, 12, 13), "today": date(2026, 12, 13)},
     "before 2026-12-14"),
    ({"b_receipt_date": None}, "no B look receipt"),
    ({"b_receipt_date": date(2026, 12, 15), "today": date(2026, 12, 20)}, "before the B look receipt"),
    ({"today": date(2026, 12, 13)}, "embargo"),
])
def test_look_context_refusals(change, match):
    with pytest.raises(fs.RodcForwardRefused, match=match):
        fs.check_look(replace(CTX, **change), dates=[D], markets=["atlanta"])


def test_date_and_market_scope_refusals():
    assert fs.check_look(CTX, dates=["2026-11-10", D], markets=["atlanta"]) == [D]
    for bad in (date(2026, 10, 29), date(2026, 9, 29), date(2026, 12, 14)):
        with pytest.raises(fs.RodcForwardRefused, match="outside"):
            fs.check_look(CTX, dates=[bad], markets=["atlanta"])
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        fs.check_look(CTX, dates=[D], markets=["denver"])


class _NoTouchStore:
    @property
    def hourly_root(self):
        raise AssertionError("store opened before the look")


def test_wu_read_is_embargoed_and_never_opens_the_store_early():
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.read_wu_rows("atlanta", [D], replace(CTX, today=date(2026, 11, 30)), store=_NoTouchStore())
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        fs.read_wu_rows("denver", [D], CTX, store=_NoTouchStore())


def test_wu_store_is_the_daily_refresh_store_at_the_registry_root():
    from weather.market.market_registry import spec_for_id

    store = fs.wu_store("atlanta")
    assert store.root == spec_for_id("atlanta").data_root and store.station_icao == "KATL"


def _write_wu(tmp_path, rows):
    store = WundergroundHistoryStore(tmp_path, station_icao="KATL", tz=TZ, unit="F", wu_units="e")
    p = store.hourly_root / "year=2026" / "month=11" / "observations.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return store


WU = [  # local times; 07:00 is inside h07, 07:52 is not
    {"local_date": "2026-11-09", "local_time": "06:52", "temp_native": 20.0, "dewpoint_native": 10.0},
    {"local_date": "2026-11-10", "local_time": "06:52", "temp_native": 41.0, "dewpoint_native": 30.0},
    {"local_date": "2026-11-10", "local_time": "00:52", "temp_native": 45.0, "dewpoint_native": 31.0},
    {"local_date": "2026-11-10", "local_time": "04:52", "temp_native": 39.0, "dewpoint_native": 33.0},
    {"local_date": "2026-11-10", "local_time": "07:00", "temp_native": 40.0, "dewpoint_native": None},
    {"local_date": "2026-11-10", "local_time": "07:52", "temp_native": 38.0, "dewpoint_native": 29.0},
]


def test_research_side_reads_the_store_in_minute_order(tmp_path):
    rows = fs.read_wu_rows("atlanta", [D], CTX, store=_write_wu(tmp_path, WU))[D]
    assert [r["minute_of_day"] for r in rows] == [52, 292, 412, 420, 472]
    assert fs.research_features(rows, 7) == {"low_so_far": 39.0, "dewpoint_c": None}
    assert fs.research_features(rows, 8) == {"low_so_far": 38.0, "dewpoint_c": 29.0}
    assert fs.research_features(rows, 0) is None


def _metar(local_hhmm, temp, dew):
    # EST = UTC-5 on 2026-11-10
    utc = datetime(2026, 11, 10, *map(int, local_hhmm.split(":")), tzinfo=TZ).astimezone(ZoneInfo("UTC"))
    row = {"raw": f"KATL {utc:%d%H%M}Z 00000KT 10SM CLR", "report_time": f"{utc:%Y-%m-%dT%H}:00:00Z",
           "temp_native": temp}
    if dew is not None:
        row["dewpoint_native"] = dew
    return row


def _snapshots(high=50.0):
    metar = {"rows": [_metar(m["local_time"], m["temp_native"], m["dewpoint_native"])
                      for m in WU if m["local_date"] == "2026-11-10"]}
    out = []
    for h in fs.HOURS:
        if h == 9:
            continue  # no capture in the 09 hour -> excluded
        out.append({"captured_at": datetime(2026, 11, 10, h, 40, tzinfo=TZ), "metar": metar,
                    "high_so_far": high, "current_temp": 45.0})
    return out


def test_p1_day_matches_research_and_counts_exclusions(tmp_path):
    wu = fs.read_wu_rows("atlanta", [D], CTX, store=_write_wu(tmp_path, WU))[D]
    recs = fs.p1_day("atlanta", D, _snapshots(), wu, CTX, tz=TZ, unit="F")
    by = {r["hour"]: r for r in recs}
    assert by[9]["excluded"] == "no_snapshot"
    assert (by[7]["serve_low"], by[7]["research_low"], by[7]["serve_dew"], by[7]["research_dew"]) == (39, 39.0,
                                                                                                    None, None)
    assert (by[8]["serve_low"], by[8]["serve_dew"]) == (38, 29)
    assert not any(r["refused"] for r in recs)
    p1 = fs.p1_verdict(recs, fs.wu_gap([("atlanta", D)], [("atlanta", D)]))
    assert p1["columns"]["low_so_far"]["exact_rate"] == 1.0 and p1["excluded"] == 1
    assert p1["verdict"] == "VOID"  # 1 of 6 rows excluded > 10%


def test_p1_day_bound_refusal_marks_the_hour(tmp_path):
    wu = fs.read_wu_rows("atlanta", [D], CTX, store=_write_wu(tmp_path, WU))[D]
    recs = fs.p1_day("atlanta", D, _snapshots(high=38.5), wu, CTX, tz=TZ, unit="F")
    assert [r["hour"] for r in recs if r["refused"]] == [7]  # low 39 > high_so_far 38.5


def test_p1_day_refuses_before_the_look():
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.p1_day("atlanta", D, [], [], replace(CTX, today=date(2026, 12, 1)), tz=TZ, unit="F")


def _rec(i, low=(40, 40.0), dew=(30, 30.0), excluded=None, refused=False, market="atlanta"):
    return {"market": market, "date": "2026-11-10", "hour": 7 + i % 6, "excluded": excluded, "refused": refused,
            "serve_low": low[0], "research_low": low[1], "serve_dew": dew[0], "research_dew": dew[1]}


def test_p1_limits_and_void_rules():
    gap = fs.wu_gap([("a", i) for i in range(100)], [("a", i) for i in range(100)])
    ok = [_rec(i) for i in range(200)]
    assert fs.p1_verdict(ok, gap)["verdict"] == "PASS"
    assert fs.p1_verdict(ok[:-1] + [_rec(0, low=(43, 40.0))], gap)["verdict"] == "FAIL"   # max |diff| 3 > 2
    assert fs.p1_verdict(ok[:-3] + [_rec(0, low=(42, 40.0))] * 3, gap)["verdict"] == "FAIL"  # 1.5% >= 2
    assert fs.p1_verdict(ok[:-11] + [_rec(0, low=(41, 40.0))] * 11, gap)["verdict"] == "FAIL"  # 94.5% exact
    assert fs.p1_verdict(ok[:-1] + [_rec(0, dew=(None, 30.0))], gap)["verdict"] == "PASS"   # 0.5% one-sided None
    assert fs.p1_verdict(ok[:-3] + [_rec(0, refused=True)] * 3, gap)["verdict"] == "FAIL"   # refusals 1.5%
    assert fs.p1_verdict(ok[:-21] + [_rec(0, excluded="no_wu_row")] * 21, gap)["verdict"] == "VOID"
    big_gap = fs.wu_gap([("a", i) for i in range(100)], [("a", i) for i in range(94)])
    assert big_gap["void"] and fs.p1_verdict(ok, big_gap)["verdict"] == "VOID"
    assert not fs.wu_gap([("a", i) for i in range(100)], [("a", i) for i in range(95)])["void"]
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        fs.p1_verdict(ok + [_rec(0, market="denver")], gap)


def _frame(n_dates=45, effect=0.0, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_dates):
        day = (date(2026, 10, 30) + timedelta(days=k)).isoformat()  # 10-30 .. 12-13
        for m in ("atlanta", "nyc", "miami"):
            for h in fs.HOURS:
                g1 = rng.uniform(0.05, 0.3)
                rows.append({"local_date": day, "market": m, "hour": h, "g1": g1,
                             "nest": g1 * (1 + effect) + rng.normal(0, 0.002)})
    return pd.DataFrame(rows)


def test_p2_matches_the_gate_cell_ratio_and_decides():
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc

    f = _frame(effect=-0.01)
    out = fs.p2_verdict(f, CTX)
    cells = f.assign(num=f.nest - f.g1).groupby(["local_date", "market"])[["num", "g1"]].mean().sort_index()
    ref = sc.ratio_interval(l3._date_weights([k[0] for k in cells.index], 2000, 20261027),
                            cells.num.to_numpy(), cells.g1.to_numpy())
    assert out["estimate"] == pytest.approx(ref["estimate"]) and out["ci95"] == pytest.approx(ref["ci95"])
    assert out["verdict"] == "PASS" and out["superiority"] and out["n_dates"] == 45
    worse = fs.p2_verdict(_frame(effect=0.01), CTX)
    assert worse["verdict"] == "FAIL" and worse["ci95"][1] >= fs.MARGIN


def test_p2_refuses_out_of_scope_rows():
    f = _frame()
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.p2_verdict(f, replace(CTX, today=date(2026, 12, 1)))
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        fs.p2_verdict(pd.concat([f, f.head(1).assign(market="denver")]), CTX)
    with pytest.raises(fs.RodcForwardRefused, match="outside"):
        fs.p2_verdict(pd.concat([f, f.head(1).assign(local_date="2026-09-29")]), CTX)


def test_outcome_table():
    p = {"verdict": "PASS"}
    assert fs.verdict(p, p) == "ADOPTION_CANDIDATE"
    assert fs.verdict(p, {"verdict": "FAIL"}) == "CLOSE_NO_FORWARD_GAIN"
    assert fs.verdict({"verdict": "FAIL"}, p) == "CLOSE_SERVE_INFEASIBLE"
    assert fs.verdict({"verdict": "VOID"}, p) == "VOID"
