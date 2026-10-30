"""Generic nested-LOYO history screen (lane L3, 2026-10-30; master YES via coordinator).

Guards: the screen's contract - a column row after 2026-09-29, a duplicate key or a bad rule refuses before any
fit; the clustered summary is seeded and reproduces ``spread_information_rung.loyo_summary`` draw for draw; the
control check refuses a row-set or value mismatch above 1e-9; a known-null column gives a pooled dR interval that
covers 0, a planted-signal column gives an upper bound below 0, and a rerun with the same seed is identical. The
P3d_N_fix / scale tests run the real R-S / R-Q machinery and skip where it is absent (it is not on master).
"""
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    ls = importlib.import_module("weather.calibration.loyo_screen")
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

try:
    rung = importlib.import_module("weather.calibration.spread_information_rung")
except ModuleNotFoundError:
    rung = None
needs_rung = pytest.mark.skipif(rung is None, reason="spread_information_rung is not on this base")


def _write_column(path, rows):
    frame = pd.DataFrame(rows, columns=["market", "date", "hour", "u"])
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        path.write_text("".join(json.dumps(r) + "\n" for r in frame.to_dict("records")), encoding="utf-8")
    return path


@pytest.mark.parametrize("suffix", (".parquet", ".jsonl"))
def test_load_column_keys_values_and_refusals(tmp_path, suffix):
    path = _write_column(tmp_path / f"c{suffix}", [("nyc", "2023-08-10", 9, 0.5), ("nyc", "2023-08-11", 9, None)])
    column, record = ls.load_column(path)
    assert column[("nyc", "2023-08-10", 9)] == 0.5 and np.isnan(column[("nyc", "2023-08-11", 9)])
    assert record["value"] == "u" and record["rows"] == 2 and len(record["sha256"]) == 64
    with pytest.raises(ls.ScreenError, match="after 2026-09-29"):
        ls.load_column(_write_column(tmp_path / f"late{suffix}", [("nyc", "2026-09-30", 9, 1.0)]))
    with pytest.raises(ls.ScreenError, match="duplicate"):
        ls.load_column(_write_column(tmp_path / f"dup{suffix}", [("nyc", "2023-08-10", 9, 1.0)] * 2))


def test_join_column_coverage():
    column = {("a", "2022-08-01", 7): 1.0, ("a", "2022-08-02", 7): float("nan"), ("z", "2022-08-01", 7): 2.0}
    u, cov = ls.join_column(["a", "a", "a"], ["2022-08-01", "2022-08-02", "2022-08-03"], [7, 7, 7], column)
    assert u[0] == 1.0 and np.isnan(u[1]) and np.isnan(u[2])
    assert cov == {"frame_rows": 3, "defined": 1, "coverage": 1 / 3, "column_keys_outside_frame": 1}


def _rows(shift, n_dates=60, per_date=8, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        for k in range(per_date):
            ctrl = float(rng.uniform(0.6, 1.0))
            rows.append({"hour": 7 + k % 2, "market": f"m{k}", "date": f"2023-08-{d % 28 + 1:02d}#{d}",
                         "P3d_N_fix_brier": ctrl, "C_brier": ctrl + shift + float(rng.normal(0, 0.02)),
                         "P3d_N_fix_log": 2 * ctrl, "C_log": 2 * ctrl + shift})
    return rows


def test_clustered_summary_null_planted_and_seed():
    null = ls.clustered_summary(_rows(0.0), "C", "P3d_N_fix", draws=500, seed=7)["pooled|brier"]
    assert null["ci95"][0] < 0 < null["ci95"][1]
    planted = ls.clustered_summary(_rows(-0.01), "C", "P3d_N_fix", draws=500, seed=7)
    assert planted["pooled|brier"]["ci95"][1] < 0
    assert set(planted) == {"h07|brier", "h07|log", "h08|brier", "h08|log", "pooled|brier", "pooled|log"}
    again = ls.clustered_summary(_rows(-0.01), "C", "P3d_N_fix", draws=500, seed=7)
    assert again == planted
    assert ls.clustered_summary(_rows(-0.01), "C", "P3d_N_fix", draws=500, seed=8) != planted


def test_rule_and_verdict():
    assert ls.parse_rule("upper<0") == ("upper", "<", 0.0)
    assert ls.parse_rule(" lower >= -1e-3 ") == ("lower", ">=", -0.001)
    for bad in ("upper", "mean<0", "upper<<0", ""):
        with pytest.raises(ls.ScreenError):
            ls.parse_rule(bad)
    summary = {"pooled|brier": {"dR": -0.002, "ci95": [-0.003, -0.001], "n": 10, "n_dates": 5}}
    assert ls.verdict(summary, "upper<0")["pass"]
    assert not ls.verdict(summary, "lower>0")["pass"]
    assert ls.verdict(summary, "upper<0")["line"].startswith("PASS: pooled dR -0.00200 [-0.00300, -0.00100]")


def test_control_check_reproduces_or_refuses(tmp_path):
    rows = [{"hour": 7, "market": "a", "date": "2022-08-01", "P3d_N_fix_brier": 0.5},
            {"hour": 8, "market": "a", "date": "2022-08-01", "P3d_N_fix_brier": 0.25}]
    ref = tmp_path / "ref.jsonl"
    ref.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert ls.control_check(rows, "P3d_N_fix", ref)["max_abs_diff"] == 0.0
    with pytest.raises(ls.ScreenError, match="max abs diff"):
        ls.control_check([dict(rows[0], P3d_N_fix_brier=0.5 + 1e-6), rows[1]], "P3d_N_fix", ref)
    with pytest.raises(ls.ScreenError, match="control rows differ"):
        ls.control_check(rows[:1], "P3d_N_fix", ref)


def test_screen_refuses_bad_rule_runner_and_name_before_reading(tmp_path):
    common = dict(column=tmp_path / "absent.parquet", records_root="x", nbm_train_corpus="x", out_dir=tmp_path,
                  hours=(9,))
    with pytest.raises(ls.ScreenError, match="rule"):
        ls.screen(name="C", rule="mean<0", **common)
    with pytest.raises(ls.ScreenError, match="no runner"):
        ls.screen(name="C", rule="upper<0", mechanism="shift", **common)
    with pytest.raises(ls.ScreenError, match="distinct"):
        ls.screen(name="P3d_N_fix", rule="upper<0", **common)


# ----------------------------------------------------------------------------- P3d_N_fix / scale, real machinery

def _frame(signal, years=(2021, 2022, 2023, 2024, 2025), markets=("atlanta", "nyc", "miami"), n_days=16, seed=0):
    """Synthetic training rows (the R-Q test frame): even days are wide (sd 4 F), odd days narrow (sd 1 F)."""
    rng = np.random.default_rng(seed)
    noise = np.random.default_rng(seed + 100)
    rows, column = [], []
    for market in markets:
        for year in years:
            for d in range(n_days):
                wide = d % 2 == 0
                fh = 80.0 + rng.normal(0, 3)
                y = round(fh + rng.normal(0, 4.0 if wide else 1.0))
                day = f"{year}-08-{10 + d:02d}"
                rows.append({"market": market, "centre": "2026-08-23", "season": "aug_sep", "hour": 9,
                             "target_date": day, "year": year, "y": float(y), "F": fh - 8.0, "fh": fh,
                             "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.5, "doy_cos": 0.8,
                             "x_high_so_far": fh - 8.0, "x_current_temp": fh - 9.0,
                             "market_code": float(prm.R0_MARKETS.index(market))})
                u = (0.4 if wide else -0.4) if signal else float(noise.normal(0, 0.4))
                column.append((market, day, 9, u + (1.0 if market == "atlanta" else 0.0)))
    return pd.DataFrame(rows), column


def _screen(tmp_path, monkeypatch, signal, out="out", seed=ls.DEFAULT_SEED):
    frame, column = _frame(signal)
    buckets = {m: list(range(60, 105)) for m in ("atlanta", "nyc", "miami")}
    monkeypatch.setattr(ls, "training_frame", lambda *a, **k: (frame, buckets, {"years": list(range(2021, 2026))}))
    path = _write_column(tmp_path / f"col_{signal}.parquet", column)
    return ls.screen(column=path, records_root="unused", nbm_train_corpus="unused", out_dir=tmp_path / out,
                     name="P3d_N_fix_C", rule="upper<0", hours=(9,), draws=400, seed=seed)


@needs_rung
def test_screen_known_null_column_covers_zero(tmp_path, monkeypatch):
    result = _screen(tmp_path, monkeypatch, signal=False)
    lo, hi = result["summary"]["pooled|brier"]["ci95"]
    assert lo < 0 < hi and not result["verdict"]["pass"]
    assert result["coverage"]["coverage"] == 1.0 and result["rows"] == 3 * 5 * 16


@needs_rung
def test_screen_planted_signal_column_is_negative_and_reruns_identically(tmp_path, monkeypatch):
    first = _screen(tmp_path, monkeypatch, signal=True, out="a")
    assert first["summary"]["pooled|brier"]["ci95"][1] < 0 and first["verdict"]["pass"]
    second = _screen(tmp_path, monkeypatch, signal=True, out="b")
    assert first["summary"] == second["summary"] and first["fit"] == second["fit"]
    assert (tmp_path / "a" / "P3d_N_fix_C_loyo_rows.jsonl").read_bytes() == (
        tmp_path / "b" / "P3d_N_fix_C_loyo_rows.jsonl").read_bytes()
    with pytest.raises(ls.ScreenError, match="overwrite"):
        _screen(tmp_path, monkeypatch, signal=True, out="a")


@needs_rung
def test_clustered_summary_matches_the_rung_summary_draw_for_draw():
    rows = [dict(r, P3d_N_fix_Q_brier=r["C_brier"], P3d_N_fix_Q_log=r["C_log"], m=0.0) for r in _rows(-0.004)]
    ours = ls.clustered_summary(rows, "P3d_N_fix_Q", "P3d_N_fix", draws=300, seed=11)
    theirs = rung.loyo_summary(rows, draws=300, seed=11, arm="P3d_N_fix_Q")
    assert set(ours) == set(theirs)
    for key in ours:
        assert ours[key]["dR"] == theirs[key]["S_minus_unmod"] and ours[key]["ci95"] == theirs[key]["ci95"]
