"""R-ODC forward scorer (P1 only): look/embargo refusals and P1 on synthetic rows (no forward data is read)."""
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.calibration import odc_metar_features as odc
from weather.calibration import rodc_forward_scorer as fs
from weather.model.mg_serve_core import wu_whole_f
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
    assert [r["hour"] for r in recs if r["refused_frozen"]] == [7]  # whole scale: 39 > 38 refuses under both


def test_p1_day_clarified_check_drops_a_rounded_vs_raw_refusal(tmp_path, monkeypatch):
    # high_so_far 38.66 F (T-group 3.7 C) is on the whole scale 39 = the low: frozen refuses (39 > 38.66), clarified not
    monkeypatch.setattr(fs, "_levels", lambda metar, day, hour, tz, unit, now: (38.66 if hour == 7 else 50.0, 45.0))
    recs = _day_records(tmp_path)
    assert [r["hour"] for r in recs if r["refused_frozen"]] == [7]
    assert not any(r["refused"] for r in recs)


def test_p1_day_refuses_before_the_look():
    with pytest.raises(fs.RodcForwardRefused, match="embargo"):
        fs.p1_day("atlanta", D, [], [], replace(CTX, today=date(2026, 12, 1)), tz=TZ, unit="F")


def _rec(day, hour, low=(40, 40.0), dew=(30, 30.0), excluded=None, refused=False, market="atlanta",
         refused_frozen=None):
    return {"market": market, "date": day.isoformat(), "hour": hour, "excluded": excluded, "refused": refused,
            "refused_frozen": refused if refused_frozen is None else refused_frozen,
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


# ------------------------------------------------------------------ Clarification 1 (master, 2026-10-31)

def _refuses(check, window):
    try:
        check(window)
    except odc.OdcMetarRefused:
        return True
    return False


def test_clarification_1_is_pinned():
    path = Path(__file__).resolve().parents[2] / fs.CLARIFICATION_1_PATH
    assert hashlib.sha256(path.read_bytes()).hexdigest() == fs.CLARIFICATION_1_SHA256
    text = path.read_text(encoding="utf-8")
    assert ("raw low ≤ raw high implies rounded low ≤ rounded high, so this removes false refusals and "
            "hides no real violation.") in text


@pytest.mark.parametrize("raw", [33.5, 33.62])
def test_a_min_equal_to_current_never_refuses_under_the_clarified_check(raw):
    low = wu_whole_f(raw, "half_up")  # the served low of a min of ``raw`` (odc_features, unchanged)
    window = {7: {"low_so_far": low, "high_so_far": raw, "current_temp": raw}}
    assert not _refuses(fs.clarified_check_bounds, window)
    # frozen mixed scales: 33.62 -> low 34 > 33.62 refuses; 33.5 snaps to T-group 33.44 -> low 33, no refusal
    assert _refuses(odc.check_bounds, window) is (low > raw)
    assert _refuses(odc.check_bounds, {7: {"low_so_far": 34.0, "high_so_far": 33.5, "current_temp": 33.5}})


@pytest.mark.parametrize("window", [
    {7: {"low_so_far": 40.0, "high_so_far": 38.0, "current_temp": 45.0}},          # low above high
    {7: {"low_so_far": 40.0, "high_so_far": 45.0, "current_temp": 38.6}},          # low above current (39)
    {7: {"low_so_far": 38.0}, 8: {"low_so_far": 39.0, "high_so_far": 45.0, "current_temp": 45.0}},  # running min
])
def test_a_real_violation_still_refuses(window):
    assert _refuses(fs.clarified_check_bounds, window)
    assert _refuses(odc.check_bounds, window)


def test_clarified_check_leaves_none_and_the_input_unchanged():
    window = {7: {"low_so_far": None, "high_so_far": 30.0, "current_temp": None}, 8: {"low_so_far": 33.0}}
    before = json.dumps(window, sort_keys=True)
    assert fs.clarified_check_bounds(window) == 2
    assert json.dumps(window, sort_keys=True) == before


def test_p1_report_discloses_frozen_and_clarified_refusals():
    changes = _h7(2, refused=True)                                         # 2 clarified (and frozen) refusals
    changes.update({(k, 8): {"refused_frozen": True} for k in range(5)})   # 5 frozen-only refusals
    changes.update({(k, 9): {"low": (42, 40.0)} for k in range(1)})        # 1 real mismatch
    out = fs.p1_verdict(_season(changes=changes), _wu_all(), CTX)
    assert out["verdict"] == "FAIL"                                        # 3/270 = 1.1% at >= 2 (clarified)
    d = out["disclosure"]
    assert d["non_deciding"] is True and d["clarification_sha256"] == fs.CLARIFICATION_1_SHA256
    assert (d["refusals_frozen_check"], d["refusals_clarified_check"]) == (7, 2)
    low = d["columns"]["low_so_far"]
    assert (low["refused"], low["real_mismatch"]) == (2, 1)
    assert low["refused_share"] == pytest.approx(2 / 270) and low["real_mismatch_share"] == pytest.approx(1 / 270)
    assert (d["columns"]["dewpoint_c"]["refused"], d["columns"]["dewpoint_c"]["real_mismatch"]) == (2, 0)
    assert out["columns"]["low_so_far"]["ge2"] == 3


def test_frozen_only_refusals_do_not_decide():
    changes = {(k, 7): {"refused_frozen": True} for k in range(10)}         # 3.7% under the frozen check
    out = fs.p1_verdict(_season(changes=changes), _wu_all(), CTX)
    assert out["verdict"] == "PASS" and out["disclosure"]["refusals_frozen_check"] == 10
