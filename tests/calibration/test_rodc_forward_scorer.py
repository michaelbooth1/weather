"""R-ODC forward scorer (P1 only): look/embargo refusals and P1 on synthetic rows (no forward data is read)."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from weather.calibration import rodc_forward_scorer as fs
from weather.market.market_config import event_slug_for_date
from weather.sources.wu_history import WundergroundHistoryStore

TZ = ZoneInfo("America/New_York")
FREEZE = date(2026, 10, 30)
D0 = date(2026, 10, 31)
D = date(2026, 11, 10)
CTX = fs.LookContext(freeze_date=FREEZE, d0=D0, look_date=date(2026, 12, 15),
                     b_receipt_date=date(2026, 12, 15), today=date(2026, 12, 15))


@pytest.mark.parametrize("change, match", [
    ({"freeze_date": date(2026, 10, 29), "d0": date(2026, 10, 30)}, "freeze"),
    ({"d0": FREEZE}, "not the first full local date after the freeze"),
    ({"d0": date(2026, 11, 1)}, "not the first full local date after the freeze"),
    ({"look_date": date(2026, 12, 14), "b_receipt_date": date(2026, 12, 14), "today": date(2026, 12, 14)},
     "cannot follow 45 countable dates"),
    ({"b_receipt_date": None}, "no B look receipt"),
    ({"b_receipt_date": date(2026, 12, 16), "today": date(2026, 12, 20)}, "before the B look receipt"),
    ({"today": date(2026, 12, 14)}, "embargo"),
])
def test_look_context_refusals(change, match):
    with pytest.raises(fs.RodcForwardRefused, match=match):
        fs.check_look(replace(CTX, **change), dates=[D], markets=["atlanta"])


def test_d0_is_always_the_day_after_the_freeze():
    assert fs.first_countable_date(FREEZE) == D0
    assert fs.first_countable_date("2026-10-30T13:05:00-04:00") == D0
    assert fs.first_countable_date(date(2026, 11, 2)) == date(2026, 11, 3)


def test_a_later_look_is_allowed_after_the_b_receipt():
    late = replace(CTX, look_date=date(2027, 1, 5), b_receipt_date=date(2026, 12, 20), today=date(2027, 1, 5))
    assert fs.check_look(late, dates=[date(2027, 1, 4)], markets=["nyc"]) == [date(2027, 1, 4)]


def test_date_and_market_scope_refusals():
    assert fs.check_look(CTX, dates=["2026-11-10", D], markets=["atlanta"]) == [D]
    for bad in (FREEZE, date(2026, 10, 29), date(2026, 9, 29), date(2026, 12, 15)):
        with pytest.raises(fs.RodcForwardRefused, match="outside"):
            fs.check_look(CTX, dates=[bad], markets=["atlanta"])
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        fs.check_look(CTX, dates=[D], markets=["denver"])


class _NoTouchStore:
    @property
    def hourly_root(self):
        raise AssertionError("store opened before the look")


def test_reads_are_embargoed_and_never_open_a_store_early(tmp_path):
    early = replace(CTX, today=date(2026, 11, 30))
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.read_wu_rows("atlanta", [D], early, store=_NoTouchStore())
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        fs.read_wu_rows("denver", [D], CTX, store=_NoTouchStore())
    _write_snapshots(tmp_path)
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.read_snapshots("atlanta", D, early, tz=TZ, root=tmp_path)


def test_stores_are_built_from_weather_paths():
    from weather.market.market_registry import spec_for_id
    from weather.paths import data_path

    store = fs.wu_store("atlanta")
    assert store.root == spec_for_id("atlanta").data_root and store.station_icao == "KATL"
    assert fs.snapshots_root() == data_path() / "snapshots"


def _write_wu(root, rows):
    store = WundergroundHistoryStore(root, station_icao="KATL", tz=TZ, unit="F", wu_units="e")
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


def _write_snapshots(root):
    metar = {"rows": [_metar(m["local_time"], m["temp_native"], m["dewpoint_native"])
                      for m in WU if m["local_date"] == "2026-11-10"]}
    lines = [{"captured_at_local": datetime(2026, 11, 9, 23, 40, tzinfo=TZ).isoformat(), "sources": {}}]
    for h in fs.HOURS:
        if h != 9:  # no capture in the 09 hour -> excluded
            lines.append({"captured_at_local": datetime(2026, 11, 10, h, 40, tzinfo=TZ).isoformat(),
                          "sources": {"metar": {"data": metar}}})
    folder = root / event_slug_for_date(D, "atlanta")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / fs.REPLAY_INPUTS).write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def _day_records(tmp_path):
    _write_snapshots(tmp_path / "snaps")
    snaps = fs.read_snapshots("atlanta", D, CTX, tz=TZ, root=tmp_path / "snaps")
    assert len(snaps) == 5
    assert fs.read_snapshots("atlanta", D + timedelta(days=1), CTX, tz=TZ, root=tmp_path / "snaps") == []
    wu = fs.read_wu_rows("atlanta", [D], CTX, store=_write_wu(tmp_path / "wu", WU))[D]
    return fs.p1_day("atlanta", D, snaps, wu, CTX, tz=TZ, unit="F")


def test_p1_day_matches_research_and_counts_exclusions(tmp_path):
    recs = _day_records(tmp_path)
    by = {r["hour"]: r for r in recs}
    assert by[9]["excluded"] == "no_snapshot"
    assert (by[7]["serve_low"], by[7]["research_low"], by[7]["serve_dew"], by[7]["research_dew"]) == (
        39, 39.0, None, None)
    assert (by[8]["serve_low"], by[8]["serve_dew"]) == (38, 29)
    assert not any(r["refused"] for r in recs)
    assert fs.countable_dates(recs) == [D]


def test_p1_day_bound_refusal_marks_the_hour(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_levels", lambda metar, day, hour, tz, unit, now: (38.5 if hour == 7 else 50.0, 45.0))
    recs = _day_records(tmp_path)
    assert [r["hour"] for r in recs if r["refused"]] == [7]  # low 39 > high_so_far 38.5 at h07 only


def test_p1_day_refuses_before_the_look():
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.p1_day("atlanta", D, [], [], replace(CTX, today=date(2026, 12, 1)), tz=TZ, unit="F")


def _rec(day, hour, low=(40, 40.0), dew=(30, 30.0), excluded=None, refused=False, market="atlanta"):
    return {"market": market, "date": day.isoformat(), "hour": hour, "excluded": excluded, "refused": refused,
            "serve_low": low[0], "research_low": low[1], "serve_dew": dew[0], "research_dew": dew[1]}


def _season(n_dates=45, changes=None):
    """6 rows per date from D0; ``changes[(k, hour)]`` overrides a row's fields."""
    changes = changes or {}
    return [_rec(D0 + timedelta(days=k), h, **changes.get((k, h), {})) for k in range(n_dates) for h in fs.HOURS]


def _wu_all(n_dates=45, skip=()):
    return {("atlanta", D0 + timedelta(days=k)) for k in range(n_dates) if k not in skip}


def _v(recs, wu=None):
    return fs.p1_verdict(recs, _wu_all() if wu is None else wu, CTX)["verdict"]


def _h7(n, **fields):
    return {(k, 7): fields for k in range(n)}


def test_p1_limits_and_void_rules():  # 270 rows
    assert _v(_season()) == "PASS"
    assert _v(_season(changes=_h7(1, low=(43, 40.0)))) == "FAIL"           # max |diff| 3 > 2
    assert _v(_season(changes=_h7(3, low=(42, 40.0)))) == "FAIL"           # 1.1% at >= 2
    assert _v(_season(changes=_h7(2, low=(42, 40.0)))) == "PASS"           # 0.7% at >= 2
    assert _v(_season(changes=_h7(14, low=(41, 40.0)))) == "FAIL"          # 94.8% exact
    assert _v(_season(changes=_h7(1, dew=(None, 30.0)))) == "PASS"         # one-sided None 0.4%
    assert _v(_season(changes=_h7(3, refused=True))) == "FAIL"             # refusals 1.1%
    assert _v(_season(changes=_h7(28, excluded="no_wu_row"))) == "VOID"    # 10.4% excluded
    assert _v(_season(changes=_h7(27, excluded="no_wu_row"))) == "PASS"    # 10.0%
    assert _v(_season(), wu=_wu_all(skip=(1, 2, 3))) == "VOID"             # WU gap 6.7%
    assert _v(_season(), wu=_wu_all(skip=(1, 2))) == "PASS"                # WU gap 4.4%
    with pytest.raises(fs.RodcForwardRefused, match="excluded market"):
        _v(_season() + [_rec(D, 7, market="denver")])


def test_countable_dates_and_the_first_45():
    with pytest.raises(fs.RodcForwardRefused, match="44 countable dates"):
        _v(_season(n_dates=44))
    late = replace(CTX, look_date=date(2026, 12, 20), today=date(2026, 12, 20))
    changes = {(3, h): {"excluded": "no_snapshot"} for h in fs.HOURS}       # date 3 is not countable
    changes.update({(46, h): {"low": (49, 40.0)} for h in fs.HOURS})        # date 46 is the 46th countable
    out = fs.p1_verdict(_season(n_dates=47, changes=changes), _wu_all(47), late)
    assert out["countable_dates"] == 46 and out["last_scored_date"] == (D0 + timedelta(days=45)).isoformat()
    assert out["verdict"] == "PASS" and out["rows"] == 45 * 6 and out["excluded"] == 0  # non-countable: out of scope


def test_outcome_table():
    assert fs.verdict({"verdict": "PASS"}) == "ELIGIBLE_FEATURE"
    assert fs.verdict({"verdict": "FAIL"}) == "CLOSE_SERVE_INFEASIBLE"
    assert fs.verdict({"verdict": "VOID"}) == "VOID"
