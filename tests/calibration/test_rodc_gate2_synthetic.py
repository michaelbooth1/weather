"""R-ODC gate 2 (rule Clarification 3): unit tests and a synthetic end to end (no real 2021-25 rows).

The e2e first runs gate 1 (``rodc_octdec.gate1``) on a synthetic frame to produce its ``gate1_rows.csv.gz``, then
runs ``rodc_gate2.gate2`` on the same frame: the gate 1 reproduction control, nested LOYO with real
``_rung_entry`` fits, the determinism check, scoring and the write-once JSON. Only file readers and binders are
replaced. A planted low_so_far effect must select G2 in every outer fold and PASS; a null column must not PASS.
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
from weather.calibration import ols_floor_ladder as lad
from weather.calibration import rodc_gate2 as g
from weather.calibration import rodc_octdec as r
from weather.model import mg_serve_core as core

MARKETS = ("atlanta", "nyc")
YEARS = r.RODC_YEARS


def _centre(target):
    d = date.fromisoformat(target)
    return min(cs.OCT_DEC_CENTRES, key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10]))
                                                      - date(2001, d.month, d.day)).days))


def _frame(planted, n_days=20, seed=11):
    """Rows with low_so_far and dewpoint_c. ``planted``: y moves with the overnight-low anomaly u (information F
    does not fully carry); otherwise low_so_far is noise unrelated to y."""
    rng = np.random.default_rng(seed)
    rows = []
    for market in MARKETS:
        for year in YEARS:
            for d in range(n_days):
                target = f"{year}-11-{1 + d:02d}"
                fh = 55.0 + rng.normal(0, 5)
                u = rng.normal(0, 3)
                y = int(round(fh + 1.0 + (1.2 * u if planted else 0.0) + rng.normal(0, 0.7)))
                noise_low = rng.normal(0, 3)
                doy = date.fromisoformat(target).timetuple().tm_yday
                for hour in r.RODC_HOURS:
                    F = float(y - abs(round(rng.normal(0, 3))) - (12 - hour))
                    low = fh - 14.0 + (u if planted else noise_low)
                    low = min(float(round(low, 1)), F)
                    dew = float("nan") if d % 5 == 0 else float(round(fh / 4 + rng.normal(0, 2), 1))
                    k_max = float("nan") if d % 7 == 0 else fh + rng.normal(0, 2)
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
                        "_low": low, "_dew": dew,
                    })
    return pd.DataFrame(rows)


def _maps(frame):
    low = {(m, c, d, int(h)): (lo, F) for m, c, d, h, lo, F in
           zip(frame.market, frame.centre, frame.target_date, frame.hour, frame._low, frame.F)}
    dew = {(m, c, d, int(h)): (F, de) for m, c, d, h, de, F in
           zip(frame.market, frame.centre, frame.target_date, frame.hour, frame._dew, frame.F)}
    return low, dew


def _skeleton():
    return {"markets": list(MARKETS),
            "season_of": {f"{m:02d}": prm.season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
            "coords": {m: [33.6, -84.4, 300.0] for m in MARKETS},
            "constants": {"min_scale": prm.MIN_SCALE, "clim_alpha": 0.10,
                          "levels": ["high_so_far", "current_temp"]},
            "conversion": {"enabled": False, "rule_id": None, "rule": None}}


def _frozen(frame):
    narrow = {m: list(range(50, 66)) for m in MARKETS}
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
    base = frame.drop(columns=["_low", "_dew"])
    monkeypatch.setattr(core, "R0_MARKETS", MARKETS)
    monkeypatch.setattr(cs, "_pin", lambda path, pinned, what: pinned)
    monkeypatch.setattr(cs, "bind_sha256sums", lambda root, sums: {"stations.json": "same"})
    monkeypatch.setattr(cs, "bind_l2_state", lambda d: (frozen, cs.P3DH_0712_STATE_SHA256, "ctl"))
    monkeypatch.setattr(cs, "bind_blend_weights", lambda p: {h: 0.5 for h in r.RODC_HOURS})
    monkeypatch.setattr(cs, "l6_part", lambda p: {h: (0.0, 0.5) for h in r.RODC_HOURS})
    monkeypatch.setattr(cs, "rn1_point_map", lambda land, root, markets: (None, {"stations": {}}))
    years_of = {"H2123": ("2021", "2022", "2023"), "H2425": ("2024", "2025")}
    monkeypatch.setattr(cs, "hrrr_k_columns",
                        lambda root, markets, hours, point, months: (_hrrr(base, years_of[root]), {"n": 1}))
    monkeypatch.setattr(cs, "record_rows", lambda rr, nbm, hours: (base.copy(), {"records": "x"}, []))
    nmap = {(m, d, int(h)): fh - 0.5 for m, d, h, fh in zip(base.market, base.local_date, base.hour, base.fh)}
    smap = {(m, d, int(h)): fh - 1.5 for m, d, h, fh in zip(base.market, base.local_date, base.hour, base.fh)}
    monkeypatch.setattr(cs, "l6_nowcast_map", lambda rr, nbm, l6: (nmap, {"l6": "x"}))
    monkeypatch.setattr(g, "sm_nowcast_map", lambda rr, nbm, sm: (smap, {"sm": "x"}))
    monkeypatch.setattr(r, "g1_training_frame", lambda rr, nbm, hrrr, markets: (base.copy(), {"rows": len(base)}))
    low, dew = _maps(frame)
    monkeypatch.setattr(g, "ladder_cache_manifest", lambda d, markets: ("c" * 64, 10))
    monkeypatch.setattr(g, "load_low_map", lambda d, markets: low)
    monkeypatch.setattr(g, "load_dew_map", lambda d, markets: dew)
    if spy is not None:
        real_fit, real_score = g.fit_state, g.score_arms

        def fit(frozen_, frame_, buckets, train_years, extra):
            spy.setdefault("fit", []).append((tuple(train_years), tuple(extra)))
            return real_fit(frozen_, frame_, buckets, train_years, extra)

        def score(frame_, arms, hrrr, nmaps, coef, weights):
            spy.setdefault("score", []).append((sorted(set(frame_["year"])), sorted(arms)))
            return real_score(frame_, arms, hrrr, nmaps, coef, weights)

        monkeypatch.setattr(g, "fit_state", fit)
        monkeypatch.setattr(g, "score_arms", score)


def _gate1(tmp_path):
    return r.gate1(nbm_corpus="n", records_root="rr", research_root="rs", state_0712="s", hrrr_2123="H2123",
                   sums_2123="x", hrrr_2425="H2425", land="l", l6_state="l6", mg2_coefficients="c",
                   blend_weights="w", rule="rule", rule_sha256="r" * 64, out_path=tmp_path / "gate1.json",
                   commit="synthetic")


def _gate2(tmp_path, rows=None):
    return g.gate2(nbm_corpus="n", records_root="rr", research_root="rs", state_0712="s", hrrr_2123="H2123",
                   sums_2123="x", hrrr_2425="H2425", land="l", l6_state="l6", sm_state="sm", mg2_coefficients="c",
                   blend_weights="w", ladder_cache="lc", ladder_cache_sha256="c" * 64, gate1_json="g1",
                   gate1_rows=rows or tmp_path / "gate1_rows.csv.gz", rule="rule", rule_sha256="r" * 64,
                   out_path=tmp_path / "gate2.json", commit="synthetic")


@pytest.fixture(scope="module")
def planted():
    frame = _frame(True)
    return frame, _frozen(frame.drop(columns=["_low", "_dew"]))


@pytest.fixture(scope="module")
def null():
    frame = _frame(False)
    return frame, _frozen(frame.drop(columns=["_low", "_dew"]))


# ---------------------------------------------------------------- unit tests

def test_g2_columns_are_exactly_the_declared_five():
    assert g.G2_EXTRA == ("k_max", "k_gap", "k_tcdc", "low_so_far", "dewpoint_c")
    assert r.P3DH_EXTRA == ("k_max", "k_gap", "k_tcdc")


def test_ladder_file_matches_the_rule_pin():
    assert cs._sha(lad.__file__) == g.LADDER_SHA256


def test_attach_g2_columns_values_nan_and_refusals():
    frame = pd.DataFrame({"market": ["nyc", "nyc"], "centre": ["2026-11-09"] * 2,
                          "target_date": ["2023-11-08", "2023-11-09"], "hour": [9, 9], "F": [50.0, 51.0]})
    low = {("nyc", "2026-11-09", "2023-11-08", 9): (41.0, 50.0), ("nyc", "2026-11-09", "2023-11-09", 9): (42.5, 51.0)}
    dew = {("nyc", "2026-11-09", "2023-11-08", 9): (50.0, 3.2),
           ("nyc", "2026-11-09", "2023-11-09", 9): (51.0, float("nan"))}
    out, st = g.attach_g2_columns(frame, low, dew, date_col="target_date")
    assert out.low_so_far.tolist() == [41.0, 42.5]
    assert out.dewpoint_c.iloc[0] == 3.2 and math.isnan(out.dewpoint_c.iloc[1])  # NaN stays NaN
    assert st["dewpoint_nan"] == 1 and "low_so_far" not in frame  # input not mutated
    with pytest.raises(g.RodcGate2Error, match="no ladder-cache or record entry"):
        g.attach_g2_columns(frame, {k: v for k, v in list(low.items())[:1]}, dew, date_col="target_date")
    bad_cache = dict(low)
    bad_cache[("nyc", "2026-11-09", "2023-11-09", 9)] = (42.5, 51.5)  # cache's high_so_far != the record's
    with pytest.raises(g.RodcGate2Error, match="high_so_far assertion"):
        g.attach_g2_columns(frame, bad_cache, dew, date_col="target_date")
    with pytest.raises(g.RodcGate2Error, match="high_so_far assertion"):  # the frame's own F differs
        g.attach_g2_columns(frame.assign(F=[50.0, 52.0]), low, dew, date_col="target_date")
    above = dict(low)
    above[("nyc", "2026-11-09", "2023-11-08", 9)] = (55.0, 50.0)
    with pytest.raises(g.RodcGate2Error, match="above its high_so_far"):
        g.attach_g2_columns(frame, above, dew, date_col="target_date")


def test_load_low_map_keeps_only_octdec_2021_25_and_no_label(tmp_path):
    rows = [{"date": "2023-11-08", "year": 2023, "actual": 61, "low_so_far": 40.0, "high_so_far": 50.0},
            {"date": "2026-11-08", "year": 2026, "actual": 99, "low_so_far": 1.0, "high_so_far": 2.0},
            {"date": "2020-11-08", "year": 2020, "actual": 98, "low_so_far": 1.0, "high_so_far": 2.0}]
    payload = {"market_id": "nyc", "centre": "11-09", "hours": {"9": rows, "14": rows}}
    (tmp_path / "cache_nyc_11-09.json").write_text(json.dumps(payload), encoding="utf-8")
    out = g.load_low_map(tmp_path, ["nyc"], centres=("2026-11-09",))
    assert out == {("nyc", "2026-11-09", "2023-11-08", 9): (40.0, 50.0)}
    payload["market_id"] = "chicago"
    (tmp_path / "cache_nyc_11-09.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(g.RodcGate2Error, match="names chicago"):
        g.load_low_map(tmp_path, ["nyc"], centres=("2026-11-09",))


def test_ladder_cache_manifest_pins_bytes(tmp_path):
    for c in ("10-10", "10-25"):
        (tmp_path / f"cache_nyc_{c}.json").write_text("{}", encoding="utf-8")
    a = g.ladder_cache_manifest(tmp_path, ["nyc"], centres=("2026-10-10", "2026-10-25"))
    assert a == g.ladder_cache_manifest(tmp_path, ["nyc"], centres=("2026-10-10", "2026-10-25")) and a[1] == 2
    (tmp_path / "cache_nyc_10-25.json").write_text("{ }", encoding="utf-8")
    assert g.ladder_cache_manifest(tmp_path, ["nyc"], centres=("2026-10-10", "2026-10-25"))[0] != a[0]
    with pytest.raises(g.RodcGate2Error, match="ladder cache missing"):
        g.ladder_cache_manifest(tmp_path, ["nyc"], centres=("2026-11-09",))


def test_select_arm_strictly_negative_picks_g2():
    assert g.select_arm(-1e-12) == "g2"
    assert g.select_arm(0.0) == "g1"
    assert g.select_arm(1e-9) == "g1"
    with pytest.raises(g.RodcGate2Error):
        g.select_arm(float("nan"))


def test_support_for_uses_training_years_only(planted):
    frame, _ = planted
    hot = frame.copy()
    hot.loc[(hot.year == 2022) & (hot.market == "nyc"), "y"] = 140.0
    sup = g.support_for(hot, [2021, 2023, 2024], MARKETS)
    assert sup["nyc"][-1] < 140
    assert g.support_for(hot, [2022, 2023, 2024], MARKETS)["nyc"][-1] == 140
    with pytest.raises(g.RodcGate2Error, match="training years"):
        g.support_for(hot[hot.year != 2021], [2021, 2023], MARKETS)


def test_fit_state_matches_gate1_fold_state_and_is_deterministic(planted):
    frame, frozen = planted
    low, dew = _maps(frame)
    base, _ = g.attach_g2_columns(frame.drop(columns=["_low", "_dew"]), low, dew, date_col="target_date")
    sup = r.fold_support(base, 2024, MARKETS)
    gate1_state, _ = r.fold_state(frozen, base, sup, 2024)
    train4 = [2021, 2022, 2023, 2025]
    g1_state, _, g1_fits = g.fit_state(frozen, base, sup, train4, r.P3DH_EXTRA)
    held = base[base.year == 2024].reset_index(drop=True)
    for row in held.head(30).itertuples(index=False):
        kw = dict(market=row.market, target_date=date.fromisoformat(row.local_date), high_so_far=row.F,
                  current_temp=row.current_temp, nbm_mean=row.nbm_mean)
        extra = [row.k_max, row.k_gap, row.k_tcdc]
        assert cs.p3dh_distribution(g1_state, row.hour, extra, **kw) == \
            cs.p3dh_distribution(gate1_state, row.hour, extra, **kw)
    _, _, a = g.fit_state(frozen, base, sup, train4, g.G2_EXTRA)
    _, _, b = g.fit_state(frozen, base, sup, train4, g.G2_EXTRA)
    assert g.determinism(a, b, base[base.year.isin(train4)]) == 0.0
    assert g.determinism(a, g1_fits, base[base.year.isin(train4)]) > 0.0  # the columns change the fit
    with pytest.raises(g.RodcGate2Error, match="neither G1's nor G2's"):
        g.fit_state(frozen, base, sup, train4, ("k_max",))
    with pytest.raises(g.RodcGate2Error, match="training years"):
        g.fit_state(frozen, base[base.year != 2021], sup, train4, r.P3DH_EXTRA)


def test_gate1_control_detects_any_difference():
    ref = pd.DataFrame({"market": ["a", "b"], "local_date": ["2023-11-01"] * 2, "hour": [7, 7],
                        **{c: [0.5, float("nan")] for c in g.CONTROL_COLUMNS}})
    assert g.gate1_control(ref.iloc[::-1].copy(), _write(ref))["max_abs_diff"] == 0.0
    off = ref.copy()
    off.loc[0, "g1"] += 1e-9
    with pytest.raises(g.RodcGate2Error, match="VOID: gate 1 control max"):
        g.gate1_control(off, _write(ref))
    nan = ref.copy()
    nan.loc[1, "comp"] = 0.4
    with pytest.raises(g.RodcGate2Error, match="NaN pattern"):
        g.gate1_control(nan, _write(ref))
    with pytest.raises(g.RodcGate2Error, match="keys differ"):
        g.gate1_control(ref.head(1), _write(ref))


def _write(frame):
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "rows.csv.gz"
    frame.to_csv(p, index=False, compression="gzip")
    return p


# ---------------------------------------------------------------- synthetic end to end

def test_gate2_planted_effect_selects_g2_everywhere_and_passes(tmp_path, monkeypatch, planted):
    frame, frozen = planted
    spy = {}
    _wire(monkeypatch, frame, frozen, spy)
    g1 = _gate1(tmp_path)
    out = _gate2(tmp_path)

    assert out["control"]["pass"] and out["control"]["max_abs_diff"] <= g.CONTROL_TOL
    assert out["control"]["determinism_max_abs"] == 0.0
    assert out["selection"]["g2_selected_folds"] == 5
    assert all(v["inner_pooled_mean"] < 0 for v in out["selection"]["nested"].values())
    assert out["verdict"] == "PASS" and out["headline"]["ci95"][1] < 0
    assert out["reported"]["g1_vs_comp"]["estimate"] == pytest.approx(g1["headline"]["estimate"], abs=1e-15)

    # written once, JSON-safe on disk, and the rows carry every arm
    on_disk = json.loads((tmp_path / "gate2.json").read_text(encoding="utf-8"))
    assert on_disk["verdict"] == "PASS" and on_disk["pass_rule"].startswith("upper 95% bound of dR(NEST vs G1)")
    assert "item 341" in on_disk["reported"]["nest_vs_comp"]["label"]
    assert "IN-SAMPLE" in on_disk["reported"]["nest_vs_comp_800072c7"]["label"]
    scored = pd.read_csv(tmp_path / "gate2_rows.csv.gz")
    assert set(scored.nest_arm) == {"g2"}
    assert np.array_equal(scored.nest.to_numpy(float), scored.g2.to_numpy(float), equal_nan=True)
    assert not np.allclose(scored.comp.to_numpy(float), scored.comp_sm.to_numpy(float))  # the variant differs

    # leakage: no fit for outer year y ever trains on y, and inner scoring never touches y
    fits = spy["fit"]
    assert len(fits) == 5 * (4 * 2 + 1) + 1  # inner G1+G2, outer G2, one determinism repeat
    k = 0
    for y in YEARS:
        for _ in range(8):
            assert y not in fits[k][0] and len(fits[k][0]) == 3
            k += 1
        assert fits[k][0] == tuple(x for x in YEARS if x != y) and fits[k][1] == g.G2_EXTRA
        k += 1 + (y == YEARS[0])
    inner_scores = spy["score"][:-1]
    assert len(inner_scores) == 20 and all(len(years) == 1 for years, _ in inner_scores)
    for i, (years, arms) in enumerate(inner_scores):
        outer = YEARS[i // 4]
        assert years[0] != outer and arms == ["g1", "g2"]
    for y, rec in out["selection"]["nested"].items():
        assert int(y) not in rec["train_years"]
        assert all(int(y) not in v["train_years"] and int(z) not in v["train_years"]
                   for z, v in rec["inner"].items())


def test_gate2_null_column_does_not_pass(tmp_path, monkeypatch, null):
    frame, frozen = null
    _wire(monkeypatch, frame, frozen)
    _gate1(tmp_path)
    out = _gate2(tmp_path)
    assert out["control"]["pass"]
    assert out["verdict"] == "FAIL"


def test_gate2_void_when_control_rows_differ(tmp_path, monkeypatch, planted):
    frame, frozen = planted
    _wire(monkeypatch, frame, frozen)
    _gate1(tmp_path)
    rows = pd.read_csv(tmp_path / "gate1_rows.csv.gz")
    rows.loc[0, "g1"] += 1e-6
    bad = tmp_path / "bad_rows.csv.gz"
    rows.to_csv(bad, index=False, compression="gzip")
    with pytest.raises(g.RodcGate2Error, match="VOID: gate 1 control"):
        _gate2(tmp_path, rows=bad)
    assert not (tmp_path / "gate2.json").exists()


def test_gate2_refuses_an_existing_output(tmp_path, monkeypatch, planted):
    frame, frozen = planted
    _wire(monkeypatch, frame, frozen)
    (tmp_path / "gate2.json").write_text("{}", encoding="utf-8")
    with pytest.raises(g.RodcGate2Error, match="refusing to overwrite"):
        _gate2(tmp_path)
    assert (tmp_path / "gate2.json").read_text(encoding="utf-8") == "{}"
