"""R-ODC gate 1, synthetic end to end (no real 2021-25 rows, no backfill data).

The full ``rodc_octdec.gate1`` path runs on a tiny synthetic frame: fold_support -> fold_state (real
``_rung_entry`` fits per hour) / comp_state -> score_rows (edge_brier) -> compare -> write-once JSON + rows.
Only the file readers and binders are replaced; every model, support, scoring and output step is the real code at
the pinned env tip. Asserts: completion, the same support in both arms per fold, the support built from training
years only, the edge counts, and the refusal paths (training years, differing supports, existing gate1.json).
"""
import importlib
import json
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

from weather.calibration import cool_season_audit as cs
from weather.calibration import rodc_octdec as r
from weather.model import mg_serve_core as core

MARKETS = ("atlanta", "nyc")
YEARS = r.RODC_YEARS
OUTLIER = ("atlanta", 2023, 3, 140)  # (market, held-out year, day index, y) far above every training label


def _centre(target):
    d = date.fromisoformat(target)
    return min(cs.OCT_DEC_CENTRES, key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10]))
                                                      - date(2001, d.month, d.day)).days))


def _frame(n_days=6, seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    for market in MARKETS:
        for year in YEARS:
            for d in range(n_days):
                target = f"{year}-11-{3 + 4 * d:02d}"
                fh = 55.0 + rng.normal(0, 5)
                y = int(round(fh + 1.0 + rng.normal(0, 1.5)))
                if (market, year, d) == OUTLIER[:3]:
                    y = OUTLIER[3]
                doy = date.fromisoformat(target).timetuple().tm_yday
                for hour in r.RODC_HOURS:
                    F = float(y - abs(round(rng.normal(0, 3))) - (12 - hour))
                    k_max = float("nan") if d % 3 == 0 else fh + rng.normal(0, 2)
                    rows.append({
                        "market": market, "centre": _centre(target), "season": "oct_dec", "hour": hour,
                        "target_date": target, "local_date": target, "year": year, "month": 11, "y": float(y),
                        "F": F, "fh": fh, "lat": 33.6, "lon": -84.4, "elev": 300.0,
                        "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                        "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                        "x_high_so_far": F, "x_current_temp": F - 1.0, "current_temp": F - 1.0,
                        "nbm_mean": fh, "v": fh + 0.5, "s": 2.0,
                        "market_code": float(prm.R0_MARKETS.index(market)),
                        "k_max": k_max, "k_gap": k_max - fh, "k_tcdc": float(rng.uniform(0, 100)),
                    })
    return pd.DataFrame(rows)


def _skeleton():
    return {"markets": list(MARKETS),
            "season_of": {f"{m:02d}": prm.season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
            "coords": {m: [33.6, -84.4, 300.0] for m in MARKETS},
            "constants": {"min_scale": prm.MIN_SCALE, "clim_alpha": 0.10,
                          "levels": ["high_so_far", "current_temp"]},
            "conversion": {"enabled": False, "rule_id": None, "rule": None}}


def _frozen(frame):
    """A fake 'frozen' P3d_H state: the real fit on years 2021-24, Aug-Sep-like narrow support (65..75)."""
    narrow = {m: list(range(65, 76)) for m in MARKETS}
    state, _ = r.fold_state(_skeleton(), frame, narrow, 2025)
    state["point_rule"] = {"report": {"stations": {}}}
    return state


def _hrrr(frame, years):
    out = {}
    for row in frame[frame.year.astype(str).isin(years)].itertuples(index=False):
        miss = not math.isfinite(row.k_max)
        out[(row.market, row.local_date, int(row.hour))] = {
            "k_max": row.k_max, "k_tcdc": row.k_tcdc, "k_miss": miss, "cycle_present": not miss}
    return out


def _wire(monkeypatch, frame, frozen, spy=None):
    monkeypatch.setattr(core, "R0_MARKETS", MARKETS)
    monkeypatch.setattr(cs, "_pin", lambda path, pinned, what: pinned)
    monkeypatch.setattr(cs, "bind_sha256sums", lambda root, sums: {"stations.json": "same"})
    monkeypatch.setattr(cs, "bind_l2_state", lambda d: (frozen, cs.P3DH_0712_STATE_SHA256, "ctl"))
    monkeypatch.setattr(cs, "bind_blend_weights", lambda p: {h: 0.5 for h in r.RODC_HOURS})
    monkeypatch.setattr(cs, "l6_part", lambda p: {h: (0.0, 0.5) for h in r.RODC_HOURS})
    monkeypatch.setattr(cs, "rn1_point_map", lambda land, root, markets: (None, {"stations": {}}))
    years_of = {"H2123": ("2021", "2022", "2023"), "H2425": ("2024", "2025")}
    monkeypatch.setattr(cs, "hrrr_k_columns",
                        lambda root, markets, hours, point, months: (_hrrr(frame, years_of[root]), {"n": 1}))
    monkeypatch.setattr(cs, "record_rows", lambda rr, nbm, hours: (frame.copy(), {"records": "x"}, []))
    nmap = {(m, d, int(h)): fh - 0.5 for m, d, h, fh in zip(frame.market, frame.local_date, frame.hour, frame.fh)}
    monkeypatch.setattr(cs, "l6_nowcast_map", lambda rr, nbm, l6: (nmap, {"l6": "x"}))
    monkeypatch.setattr(r, "g1_training_frame", lambda rr, nbm, hrrr, markets: (frame.copy(), {"rows": len(frame)}))
    if spy is not None:
        real_comp, real_fold = r.comp_state, r.fold_state

        def comp(frozen_, buckets):
            st = real_comp(frozen_, buckets)
            spy.setdefault("comp", []).append(st)
            return st

        def fold(frozen_, frame_, buckets, year):
            st, rows = real_fold(frozen_, frame_, buckets, year)
            spy.setdefault("fold", []).append((year, st))
            return st, rows

        monkeypatch.setattr(r, "comp_state", comp)
        monkeypatch.setattr(r, "fold_state", fold)


def _run(tmp_path, out_name="gate1.json"):
    return r.gate1(nbm_corpus="n", records_root="rr", research_root="rs", state_0712="s", hrrr_2123="H2123",
                   sums_2123="x", hrrr_2425="H2425", land="l", l6_state="l6", mg2_coefficients="c",
                   blend_weights="w", rule="rule", rule_sha256="r" * 64, out_path=tmp_path / out_name,
                   commit="synthetic")


@pytest.fixture(scope="module")
def synth():
    frame = _frame()
    return frame, _frozen(frame)


def test_gate1_synthetic_end_to_end(tmp_path, monkeypatch, synth):
    frame, frozen = synth
    before = {m: list(v) for m, v in frozen["buckets"].items()}
    train_y_before = {h: {m: list(v) for m, v in e["train_y"].items()} for h, e in frozen["hours"].items()}
    spy = {}
    _wire(monkeypatch, frame, frozen, spy)
    out = _run(tmp_path)

    # completes, writes both files once, and the JSON on disk is the payload
    assert out["verdict"] in ("PASS", "FAIL")
    on_disk = json.loads((tmp_path / "gate1.json").read_text(encoding="utf-8"))
    assert on_disk["headline"]["n_rows"] == out["headline"]["n_rows"] > 0
    assert (tmp_path / "gate1_rows.csv.gz").exists() and len(out["rows_sha256"]) == 64
    scored = pd.read_csv(tmp_path / "gate1_rows.csv.gz")
    assert np.isfinite(scored[["comp", "g1", "mg1", "p3d_comp", "p3d_g1"]].to_numpy(float)).all()

    # the frozen state is never mutated
    assert frozen["buckets"] == before
    assert {h: e["train_y"] for h, e in frozen["hours"].items()} == train_y_before

    # both arms use the same support in every fold, built from the training years only
    assert len(spy["comp"]) == len(spy["fold"]) == len(YEARS)
    for (year, g1), comp in zip(spy["fold"], spy["comp"]):
        assert g1["buckets"] == comp["buckets"]
        train = frame[frame.year != year]
        for m in MARKETS:
            ys = train.loc[train.market == m, "y"].astype(int)
            assert g1["buckets"][m] == list(range(ys.min(), ys.max() + 1))
            for h in r.RODC_HOURS:  # open edges: clipped train_y inside the support in both arms
                for st in (g1, comp):
                    assert all(g1["buckets"][m][0] <= v <= g1["buckets"][m][-1] for v in st["hours"][h]["train_y"][m])
        sup = out["fold_support"][str(year)]
        assert sup == {m: [g1["buckets"][m][0], g1["buckets"][m][-1], len(g1["buckets"][m])] for m in MARKETS}
    # the outlier's held-out fold excludes it; the other folds include it (it is a training label there)
    assert out["fold_support"]["2023"]["atlanta"][1] < OUTLIER[3]
    assert all(out["fold_support"][str(y)]["atlanta"][1] == OUTLIER[3] for y in YEARS if y != 2023)

    # edge counts: recomputed independently from labels and the recorded supports
    below = above = inside = 0
    for row in frame.itertuples(index=False):
        lo, hi, _ = out["fold_support"][str(row.year)][row.market]
        below += int(row.y) < lo
        above += int(row.y) > hi
        inside += lo <= int(row.y) <= hi
    st = out["counts"]["row_stats"]
    assert st.get("y_below_support", 0) == below and st.get("y_above_support", 0) == above
    assert st["y_in_support"] == inside and st["scored"] == len(frame)
    assert above >= len(r.RODC_HOURS)  # the outlier date: one row per hour above max in fold 2023

    # an out-of-support label scores on the edge bucket, identically for both arms' partition
    row = scored[(scored.market == "atlanta") & (scored.year == 2023)]
    assert len(row) and np.isfinite(row.comp).all() and np.isfinite(row.g1).all()


def test_edge_brier_open_edges():
    sup = list(range(10, 21))
    d = {5: 0.1, 10: 0.2, 15: 0.3, 25: 0.4}
    # below-min and above-max mass folds onto the edges, and an out-of-support label is clipped
    assert r.edge_brier(d, 30, sup) == pytest.approx(cs.brier_from_dist({10: 0.3, 15: 0.3, 20: 0.4}, 20))
    assert r.edge_brier(d, 0, sup) == pytest.approx(cs.brier_from_dist({10: 0.3, 15: 0.3, 20: 0.4}, 10))


def test_fold_state_refuses_when_training_years_are_not_the_other_four(synth):
    frame, frozen = synth
    short = frame[frame.year != 2022]
    with pytest.raises(r.RodcError, match="training years are not the other four"):
        r.fold_state(_skeleton(), short, r.fold_support(short, 2021, MARKETS), 2021)


def test_fold_support_never_sees_the_held_out_year(synth):
    frame, _ = synth
    sup = r.fold_support(frame, 2023, MARKETS)
    assert sup["atlanta"][-1] < OUTLIER[3]
    with pytest.raises(r.RodcError, match="no training labels"):
        r.fold_support(frame[frame.market == "nyc"], 2023, MARKETS)


def test_gate1_refuses_differing_supports(tmp_path, monkeypatch, synth):
    frame, frozen = synth
    _wire(monkeypatch, frame, frozen)
    real = r.comp_state

    def skewed(frozen_, buckets):
        return real(frozen_, {m: v[1:] for m, v in buckets.items()})

    monkeypatch.setattr(r, "comp_state", skewed)
    with pytest.raises(r.RodcError, match="COMP and G1 supports differ"):
        _run(tmp_path)
    assert not (tmp_path / "gate1.json").exists()


def test_score_rows_refuses_differing_supports(synth):
    frame, frozen = synth
    sup = r.fold_support(frame, 2021, MARKETS)
    comps = {y: r.comp_state(frozen, sup) for y in YEARS}
    folds = {y: r.comp_state(frozen, {m: v[1:] for m, v in sup.items()}) for y in YEARS}
    with pytest.raises(r.RodcError, match="COMP and G1 supports differ"):
        r.score_rows(frame.head(3), comps, folds, {}, {}, {h: (0.0, 0.5) for h in r.RODC_HOURS},
                     {h: 0.5 for h in r.RODC_HOURS})


def test_gate1_refuses_an_existing_output(tmp_path, monkeypatch, synth):
    frame, frozen = synth
    _wire(monkeypatch, frame, frozen)
    (tmp_path / "gate1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(cs.CoolSeasonError, match="refusing to overwrite"):
        _run(tmp_path)
    assert (tmp_path / "gate1.json").read_text(encoding="utf-8") == "{}"
    assert not (tmp_path / "gate1_rows.csv.gz").exists()
