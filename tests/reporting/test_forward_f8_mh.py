"""F8-MH forward screen (ledger row 104): synthetic tests only; no snapshot, METAR, label or price file is read.

Guards: B's manifest check at import (and a tampered copy refuses); the routine-only regime flag (SPECI, previous-day,
after-capture rows excluded; whole-degree H and C through ``wu_whole_f``; t_H <= 01:59; H - C >= 3; scope US10 and
hours 01-06); the look gate (refuses before PT-1's look, without master's approval or a claiming-look receipt, and any
gated read before the gate); the window (D0 11-02, 11-01 excluded, 01-25 last); the cell pre-filter; the projected
power; the labels; and the frozen statistic on a synthetic regime table (planted signal positive, null not, zero-tilt
identity exact, disclosures non-deciding).
"""
import importlib
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

f8 = importlib.import_module("tools.research.forward_f8.f8_mh")
sw = importlib.import_module("weather.calibration.mr_sweep")
sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")

NY = ZoneInfo("America/New_York")
D = date(2026, 11, 10)


def _row(local_hh, local_mm, temp_f, prefix="", day=D):
    inst = datetime(day.year, day.month, day.day, local_hh, local_mm, tzinfo=NY).astimezone(timezone.utc)
    raw = f"{prefix}KATL {inst:%d%H%M}Z 00000KT 10SM CLR 10/05 A3000 RMK AO2"
    return {"raw": raw.strip(), "report_time": inst.isoformat(), "temp_native": temp_f}


def _cap(hh, mm=40, day=D):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=NY).astimezone(timezone.utc)


def _flag(rows, hour=5, captured=None, payload=None, market="atlanta", day=D):
    rec = {"sources": {"metar": {"data": {"rows": rows, "raw_payload": payload or []}}}}
    return f8.snapshot_regime(rec, market=market, target_date=day, local_hour=hour,
                              captured=captured or _cap(hour, day=day), tz=NY)


# ----------------------------------------------------------------------------- B manifest

def test_import_checked_b_manifest_and_files():
    assert f8.B_IMPORT_CHECK["manifest_sha256"] == f8.B_MANIFEST_SHA256
    assert set(f8.B_IMPORT_CHECK["files"]) == set(f8.B_IMPORTED)
    loaded = f8.check_b_imports()
    assert "src/weather/model/mg_serve_core.py" in loaded and "src/weather/model/observed_running_max.py" in loaded


def test_tampered_b_file_refuses(tmp_path):
    for rel in (f8.B_MANIFEST_PATH, *f8.B_IMPORTED):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f8.TREE / rel, dst)
    assert f8.check_b_manifest(tmp_path)["files"] == f8.B_IMPORT_CHECK["files"]
    target = tmp_path / "src/weather/model/observed_running_max.py"
    target.write_bytes(target.read_bytes() + b"\n# edit\n")
    with pytest.raises(f8.Refused, match="differs from B's manifest"):
        f8.check_b_manifest(tmp_path)
    man = tmp_path / f8.B_MANIFEST_PATH
    man.write_bytes(man.read_bytes() + b" ")
    with pytest.raises(f8.Refused, match="manifest sha256"):
        f8.check_b_manifest(tmp_path)


def test_pinned_blobs_match():
    assert f8.check_blobs() == f8.BLOBS


# ----------------------------------------------------------------------------- the regime flag

def test_midnight_high_then_drop_is_regime():
    rows = [_row(0, 53, 50.0), _row(1, 53, 49.0), _row(3, 53, 47.5), _row(4, 53, 46.94)]
    f = _flag(rows)
    assert f["regime"] and f["H"] == 50.0 and f["C"] == 47.0 and f["t_H"].startswith("2026-11-10T00:53")


def test_drop_below_three_whole_degrees_is_not_regime():
    f = _flag([_row(0, 53, 50.0), _row(4, 53, 47.12 + 0.5)])   # 47.62 -> 48 whole: drop 2
    assert not f["regime"] and f["H"] - f["C"] == 2


def test_whole_scale_threshold_uses_wu_whole_f():
    f = _flag([_row(0, 53, 49.6), _row(4, 53, 47.4)])          # 49.6 -> 50 (T-group snap), 47.4 -> 47
    assert f["regime"] and (f["H"], f["C"]) == (50.0, 47.0)


def test_high_after_0159_is_not_regime():
    f = _flag([_row(0, 53, 48.0), _row(2, 53, 50.0), _row(5, 13, 45.0)], hour=5, captured=_cap(5, 20))
    assert not f["regime"] and f["t_H"].startswith("2026-11-10T02:53")


def test_earliest_row_attaining_h_sets_t_h():
    f = _flag([_row(0, 53, 50.0), _row(2, 53, 50.0), _row(5, 13, 45.0)], captured=_cap(5, 20))
    assert f["regime"] and f["t_H"].startswith("2026-11-10T00:53")


def test_speci_excluded_by_prefix_and_by_payload_type():
    rows = [_row(0, 53, 48.0), _row(3, 10, 53.0, prefix="SPECI "), _row(4, 53, 44.0)]
    f = _flag(rows)
    assert f["regime"] and f["H"] == 48.0 and f["row_stats"]["speci"] == 1
    plain = _row(3, 20, 53.0)
    payload = [{"rawOb": plain["raw"], "metarType": "SPECI"}]
    g = _flag([_row(0, 53, 48.0), plain, _row(4, 53, 44.0)], payload=payload)
    assert g["regime"] and g["H"] == 48.0 and g["row_stats"]["speci"] == 1


def test_previous_day_and_after_capture_rows_excluded():
    prev = _row(23, 53, 60.0, day=D - timedelta(days=1))
    late = _row(5, 53, 30.0)
    f = _flag([prev, _row(0, 53, 50.0), _row(4, 53, 46.0), late], hour=5, captured=_cap(5, 40))
    assert f["regime"] and f["H"] == 50.0 and f["C"] == 46.0
    assert f["row_stats"]["other_date"] == 1 and f["row_stats"]["after_capture"] == 1


def test_cold_values_are_not_filtered():
    f = _flag([_row(0, 53, 20.0), _row(4, 53, 12.0)])
    assert f["regime"] and (f["H"], f["C"]) == (20.0, 12.0)


def test_missing_and_scope():
    assert _flag([])["missing"] and not _flag([])["regime"]
    rows = [_row(0, 53, 50.0), _row(4, 53, 40.0)]
    assert not _flag(rows, market="denver")["regime"]
    assert not _flag(rows, hour=7, captured=_cap(7))["regime"]
    assert not _flag(rows, hour=0, captured=_cap(0, 59))["regime"]
    nov1 = [_row(0, 53, 50.0, day=date(2026, 11, 1)), _row(4, 53, 40.0, day=date(2026, 11, 1))]
    assert not _flag(nov1, day=date(2026, 11, 1), captured=_cap(5, day=date(2026, 11, 1)))["regime"]


# ----------------------------------------------------------------------------- window and look gate

def test_window_constants():
    assert f8.D0 == date(2026, 11, 2) and f8.WINDOW_LAST == date(2027, 1, 25)
    assert not f8.in_window("2026-11-01") and not f8.in_window("2026-10-31") and not f8.in_window("2027-01-26")
    assert f8.in_window("2026-11-02") and f8.in_window("2027-01-25")
    with pytest.raises(f8.Refused):
        f8.check_dates({"2026-11-02", "2026-11-01"})


LOOKS = ";".join(f"{k}={'a' * 64}" for k in f8.CLAIMING_LOOKS)


def test_look_gate_refuses_early_or_unapproved(tmp_path):
    f8.close_look_gate()
    with pytest.raises(f8.Refused, match="not before"):
        f8.open_look_gate(date(2027, 1, 26), "master F8-MH look", LOOKS)
    with pytest.raises(f8.Refused, match="not before"):
        f8.open_look_gate(date(2026, 12, 15), "master F8-MH look", LOOKS)
    with pytest.raises(f8.Refused, match="approval"):
        f8.open_look_gate(date(2027, 1, 27), "", LOOKS)
    with pytest.raises(f8.Refused, match="PT1"):
        f8.open_look_gate(date(2027, 1, 27), "master F8-MH look", LOOKS.replace("PT1=", "PTX="))
    with pytest.raises(f8.Refused, match="look gate"):
        f8.read_export(tmp_path, "0" * 64, {})
    with pytest.raises(f8.Refused, match="look gate"):
        with f8.forward_layout_override(object()):
            pass
    gate = f8.open_look_gate(date(2027, 1, 27), "master F8-MH look", LOOKS)
    assert gate["claiming_looks"]["PT1"] == "a" * 64
    f8.close_look_gate()


def test_look_cli_refuses_before_gate_without_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(f8, "guards", lambda tree=f8.TREE: {})
    args = f8.build_parser().parse_args(["look", "--out", str(tmp_path / "x"), "--layout", str(tmp_path / "nope"),
                                         "--layout-manifest-sha", "0" * 64, "--export", str(tmp_path / "nope"),
                                         "--export-sums-sha", "0" * 64, "--approval", "master F8-MH look",
                                         "--claiming-looks-done", LOOKS])
    with pytest.raises(f8.Refused, match="not before"):
        f8.look(args, today=date(2026, 12, 13))
    assert not (tmp_path / "x").exists()


# ----------------------------------------------------------------------------- population, power, labels

def test_cell_prefilter_drops_single_date_cells():
    rows = [{"row_key": f"k{i}", "market": m, "local_hour": h, "date": d}
            for i, (m, h, d) in enumerate([("nyc", 3, "2026-11-05"), ("nyc", 3, "2026-11-09"),
                                           ("nyc", 3, "2026-11-09"), ("miami", 4, "2026-11-05")])]
    kept, info = f8.cell_prefilter(rows)
    assert [r["row_key"] for r in kept] == ["k0", "k1", "k2"] and info["dropped_cells"] == ["miami|4"]
    assert info["market_day_hours_kept"] == 2 and f8.control_cells(kept)["pass"]
    assert not f8.control_cells(rows)["pass"]


def test_projected_power_reference_and_deff():
    assert f8.projected_power(f8.REF_MARKET_DAY_HOURS, deff=1.0) == pytest.approx(
        f8.power_at(f8.DELTA_EDGE, f8.SE_REF))
    assert f8.projected_power(100) < f8.projected_power(400) < f8.projected_power(400, deff=1.0)
    assert f8.projected_power(0) is None
    assert f8.block_counts(7, b=5).sum(axis=1).tolist() == [7.0] * 5


def test_labels():
    e = f8.DELTA_EDGE
    assert f8.label_for(False, 0.9, -0.1, 0.1) == f8.UNTESTABLE
    assert f8.label_for(True, 0.4, -0.1, 0.1) == f8.UNTESTABLE
    assert f8.label_for(True, 0.9, -0.1, e - 1e-6) == f8.KILL
    assert f8.label_for(True, 0.9, 0.01, e + 0.1) == f8.SCREEN
    assert f8.label_for(True, 0.9, -0.01, e + 0.1) == f8.NOT_KILLED


# ----------------------------------------------------------------------------- the statistic, synthetic table

KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]
Z = np.array([58.0, 60.5, 62.5, 64.5, 67.0])


class FakeTable:
    def __init__(self, f):
        f = f.reset_index(drop=True)
        self.snaps = f[["row_key", "date", "captured_at_utc", "market", "local_hour"]].copy()
        k = len(f)
        self.n = np.full(k, 5)
        self.offsets = np.arange(k) * 5
        self.band_snap = np.repeat(np.arange(k), 5)
        self.snap_pos = pd.Series(np.arange(k), index=f.row_key.to_numpy())
        self.bands = pd.DataFrame({"band_index": np.tile(np.arange(5), k), "kind": KINDS * k,
                                   "low": LOWS * k, "high": HIGHS * k})
        self.p_market = np.concatenate(f.pm.to_list())
        self.y = np.concatenate([np.eye(5)[w] for w in f.winner])
        self.local_hour = f.local_hour.to_numpy(int)
        self.markets = f.market.to_numpy()
        self.impossible = np.zeros(len(self.y), bool)
        keys = sorted(set(zip(f.date, f.market)))
        index = {key: i for i, key in enumerate(keys)}
        self.keys = keys
        self.cell = np.array([index[key] for key in zip(f.date, f.market)], int)
        self.w = sc.crossed_weights([key[0] for key in keys], [key[1] for key in keys])
        self.w_date = sc.crossed_weights([key[0] for key in keys], ["all"] * len(keys))


def _frame(seed=11, n_dates=26, markets=("atlanta", "nyc", "miami", "chicago", "dallas", "houston", "seattle"),
           hours=range(1, 7)):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        day = (date(2026, 11, 2) + timedelta(days=d)).isoformat()
        for market in markets:
            for hour in hours:
                pm = rng.dirichlet(np.ones(5) * 2)
                q = rng.dirichlet(pm * 4 + 1e-3)
                winner = int(rng.choice(5, p=q / q.sum()))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm * 0.98,
                             "winner": winner, "h_info": Z[winner] + rng.normal(0, 1.0),
                             "h_null": 62 + rng.normal(0, 3)})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def table():
    f = _frame()
    return f, FakeTable(f)


def test_statistic_planted_signal_is_positive(table, monkeypatch):
    f, t = table
    out = f8.run_statistic(t, f.h_info.to_numpy(float))
    assert out["result"]["testable"] and out["result"]["coverage"]["population_snapshots"] == len(f)
    assert out["d3"]["delta"] > 0 and out["d3"]["ci95_wider"][0] > 0
    assert out["control_zero_tilt"]["pass"] and out["control_zero_tilt"]["max_abs_c_minus_m"] < 1e-12
    disc = out["disclosure_non_deciding"]
    assert {"market_mean_above_H", "market_mean_at_or_below_H", "hour_01", "market_nyc"} <= set(disc)
    assert disc["market_mean_above_H"]["snapshots"] + disc["market_mean_at_or_below_H"]["snapshots"] == len(f)


def test_statistic_null_signal_is_not_positive(table, monkeypatch):
    f, t = table
    out = f8.run_statistic(t, f.h_null.to_numpy(float))
    assert out["result"]["testable"] and out["d3"]["ci95_wider"][0] <= 0
    assert out["label"] != f8.SCREEN


def test_statistic_thin_table_is_untestable(monkeypatch):
    f = _frame(n_dates=8, markets=("nyc",), hours=(3,))
    out = f8.run_statistic(FakeTable(f), f.h_info.to_numpy(float))
    assert not out["result"]["testable"] and out["label"] == f8.UNTESTABLE


def test_statistic_refuses_missing_h(table):
    f, t = table
    h = f.h_info.to_numpy(float).copy()
    h[0] = np.nan
    with pytest.raises(f8.Refused, match="finite H"):
        f8.run_statistic(t, h)


def test_module_doc_states_mechanism_and_dropped_gate():
    doc = f8.__doc__
    assert "keeps mass above H for a daytime recovery that does not come" in doc
    assert "the NBM gate G was dropped before any count" in doc
    json.dumps({"D0": str(f8.D0)})


def test_pinned_freeze_doc_and_s0_spec():
    assert f8.check_pinned_docs() == {f8.FREEZE_DOC_PATH: f8.FREEZE_DOC_SHA256, f8.S0_SPEC_PATH: f8.S0_SPEC_SHA256}


# ----------------------------------------------------------------------------- Clarification 1 (non-deciding)

def test_clarification_1_pinned_and_scope_verbatim():
    assert f8.check_clarifications() == {f8.CLARIFICATION_1_PATH: f8.CLARIFICATION_1_SHA256}
    text = (f8.TREE / f8.CLARIFICATION_1_PATH).read_text(encoding="utf-8")
    assert ("01-06 book mass above H on cooling nights (midnight-set max, ≥ 3°F drop), broader than the frontal "
            "story") in text
    assert "closes the broad version only" in text and "OUTCOME-DEFINED" in text


def _deciding(out):
    return json.dumps({"result": out["result"], "d3": out["d3"], "label": out["label"],
                       "frozen_disclosure": out["disclosure_non_deciding"], "control": out["control_zero_tilt"]},
                      sort_keys=True, default=str)


@pytest.mark.parametrize("signal", ["h_info", "h_null"])
def test_clarification_disclosure_never_changes_the_verdict(table, signal):
    f, t = table
    h = f[signal].to_numpy(float)
    rng = np.random.default_rng(5)
    day_max = np.where(rng.random(len(f)) < 0.5, np.round(h), np.round(h) + 2)
    day_max[:3] = np.nan
    without = f8.run_statistic(t, h, clarification_disclosure=False)
    with_none = f8.run_statistic(t, h)
    with_dm = f8.run_statistic(t, h, day_max=day_max)
    assert "disclosure" not in without
    assert _deciding(without) == _deciding(with_none) == _deciding(with_dm)
    disc = with_dm["disclosure"]
    assert disc["non_deciding"] is True and disc["clarification_sha256"] == f8.CLARIFICATION_1_SHA256
    band = disc["hour_band"]
    assert band["hours_01_03"]["snapshots"] + band["hours_04_06"]["snapshots"] == len(f)
    dm = disc["day_max_vs_H"]
    assert dm["available"] and dm["outcome_defined"] and dm["missing_day_max"] == 3
    assert dm["day_max_eq_H_frontal"]["snapshots"] + dm["day_max_ne_H"]["snapshots"] == len(f) - 3
    assert with_none["disclosure"]["day_max_vs_H"] == {"available": False, "outcome_defined": True}


def test_day_max_split_uses_wu_whole_scale():
    eq, ne, missing = f8.day_max_split_masks([50.0, 50.0, 50.0, 50.0], [49.6, 50.4, 51.0, float("nan")])
    assert eq.tolist() == [True, True, False, False] and ne.tolist() == [False, False, True, False] and missing == 1


def test_disclosure_error_does_not_change_the_verdict(table, monkeypatch):
    f, t = table
    h = f.h_info.to_numpy(float)
    base = f8.run_statistic(t, h, clarification_disclosure=False)

    def boom(*a, **k):
        raise RuntimeError("disclosure failure")

    monkeypatch.setattr(f8, "clarification_1_disclosure", boom)
    out = f8.run_statistic(t, h, day_max=np.round(h))
    assert _deciding(out) == _deciding(base) and "error" in out["disclosure"] and out["disclosure"]["non_deciding"]


def test_labels_day_max_is_gated():
    f8.close_look_gate()
    with pytest.raises(f8.Refused, match="look gate"):
        f8.labels_day_max(object(), [])
