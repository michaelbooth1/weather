"""Loss atlas: positive control first (refuses on failure), decomposition, deltas, data rule, import guard.

Guards: lane L7 brief (2026-10-24) - the atlas always reproduces the served control (R 1.774 all /
1.526 00-16) before reading a candidate and refuses otherwise; dates <= 2026-09-29 only, no 88a or panel
inputs; it refuses to import on the dedicated capture host. The vectorised centre shift is pinned to
lane L5's per-snapshot loop (claude/morning-loss-diagnosis-20261024 @ dee30cabe).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

from tests.host_guard import import_or_skip_on_capture_host

la = import_or_skip_on_capture_host("weather.reporting.scorecards.loss_atlas")

BANDS = (("lte", 77, 77), ("eq", 78, 79), ("eq", 80, 81), ("eq", 82, 83), ("gte", 84, 84))
HOURS = (0, 3, 6, 7, 8, 9, 10, 11, 12, 14, 16)


def _band_of(y):
    for i, (kind, lo, hi) in enumerate(BANDS):
        if (kind == "lte" and y <= hi) or (kind == "gte" and y >= lo) or (kind == "eq" and lo <= y <= hi):
            return i
    raise AssertionError(y)


def _pmf(mu, sd):
    out = []
    for kind, lo, hi in BANDS:
        up = np.inf if kind == "gte" else hi + .5
        low = -np.inf if kind == "lte" else lo - .5
        out.append(norm.cdf((up - mu) / sd) - norm.cdf((low - mu) / sd))
    p = np.maximum(np.asarray(out), 1e-6)
    return p / p.sum()


def _parquet(frame, path):
    frame.to_parquet(path, index=False)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_layout(root, n_dates=28, markets=("m1", "m2", "m3"), seed=11, served_bias=-2.0):
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market = [], [], [], []
    first = date(2026, 8, 1)
    for k in range(n_dates):
        day = (first + timedelta(days=k)).isoformat()
        for mk in markets:
            y = int(rng.integers(76, 86))
            winner = _band_of(y)
            hot = 1.0 if y >= 82 else 0.0
            for hour in HOURS:
                rk = f"{mk}|{day}T{hour:02d}"
                cap = datetime.fromisoformat(f"{day}T{hour:02d}:{int(rng.integers(0, 50)):02d}:00")
                mu_m = y + rng.normal(0, 0.6)
                mu_s = y + served_bias * (0.5 + hot) * (1 - hour / 24) + rng.normal(0, 1.0)
                v2 = y + rng.normal(0.3, 1.0)
                snaps.append({"row_key": rk, "snapshot_id": rk, "market": mk, "date": day, "local_hour": hour,
                              "n_bands": len(BANDS), "captured_at_local": cap.isoformat(),
                              "captured_at_utc": (cap + timedelta(hours=4)).isoformat() + "+00:00",
                              "v2_available_at": (cap + timedelta(hours=1)).isoformat() + "+00:00",
                              "v2_mean": v2, "v2_stddev": 1.4, "v2_p50": v2,
                              "hrrr_high": y + rng.normal(0, 1.5), "nws_grid_high_raw": y + rng.normal(0, 1),
                              "high_so_far": 60.0, "guidance_physical_floor": np.nan,
                              "trusted_current_max": np.nan, "floor": 60.0})
                ps, pm = _pmf(mu_s, 2.4), _pmf(mu_m, 1.5)
                for i, (kind, lo, hi) in enumerate(BANDS):
                    bands.append({"row_key": rk, "band_index": i, "kind": kind, "low": lo, "high": hi,
                                  "p_served": float(ps[i]), "date": day, "market": mk, "local_hour": hour})
                    market.append({"row_key": rk, "band_index": i, "date": day, "market": mk,
                                   "p_market_yes": float(pm[i])})
                labels.append({"row_key": rk, "date": day, "market": mk, "winner": winner,
                               "settlement_high": float(y), "settlement_bucket": winner,
                               "promotion_countable": False})
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frames = {data.SNAPSHOTS_FILE: pd.DataFrame(snaps), data.BANDS_FILE: pd.DataFrame(bands),
              data.LABELS_FILE: pd.DataFrame(labels), data.MARKET_FILE: pd.DataFrame(market)}
    files = {name: {"sha256": _parquet(frame, root / name), "rows": len(frame),
                    "dates": sorted(frame.date.unique())} for name, frame in frames.items()}
    (root / data.MANIFEST).write_text(json.dumps({"schema": data.LAYOUT_SCHEMA, "files": files}),
                                      encoding="utf-8")
    return root


def _table(root):
    start, end = data.check_range(*la.RANGE)
    layout = data.load_layout(root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, *la.FOLDS)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    return layout, sc.Table(layout, scored)


def _fixture_expected(root):
    _, t = _table(root)
    rows = {r["block"]: r for r in sc.score_rows(t, t.p_served, True) if r["market"] == sc.ALL_MARKETS}
    return {b: round(rows[b]["gap_ratio"]["estimate"], 3) for b in ("all", "00-16")}


@pytest.fixture(scope="module")
def layout_root(tmp_path_factory):
    return write_layout(tmp_path_factory.mktemp("atlas") / "lay")


@pytest.fixture(scope="module")
def mg1_atlas(layout_root):
    return la.run_atlas(layout_root, data.CandidateSpec("mg1"), control_expected=_fixture_expected(layout_root))


# ----------------------------------------------------------------------------- positive control

def test_failed_positive_control_refuses_before_any_candidate_or_output(layout_root, tmp_path, monkeypatch):
    touched = []
    monkeypatch.setattr(la, "candidate_vector", lambda *a, **k: touched.append(1))
    with pytest.raises(la.ControlFailed, match="positive control failed"):
        la.run_atlas(layout_root, data.CandidateSpec("mg1"))      # canonical 1.774 / 1.526 cannot match
    assert touched == []
    out = tmp_path / "out"
    code = la.main(["atlas", "--layout", str(layout_root), "--candidate", "mg1", "--out", str(out)])
    assert code == 7 and not out.exists()


def test_positive_control_passes_on_reproduced_values_and_is_recorded(mg1_atlas, layout_root):
    pc = mg1_atlas["positive_control"]
    assert pc["verdict"] == "PASS"
    assert pc["expected"] == _fixture_expected(layout_root)
    assert la.CONTROL_EXPECTED == {"all": 1.774, "00-16": 1.526}


# ----------------------------------------------------------------------------- atlas content

def test_atlas_has_every_section_for_candidate_served_and_mg1(mg1_atlas):
    assert set(mg1_atlas["models"]) == {"candidate", "served", "mg1"}
    for sec in mg1_atlas["models"].values():
        assert {"decomposition", "per_market", "per_hour", "concentration", "regimes", "timing"} <= set(sec)
        d = sec["decomposition"]
        for key in ("excess_over_market", "centre_share_shapley", "width_share_shapley", "centre_bias",
                    "centre_bias_market", "centre_mae", "centre_mae_market"):
            assert set(d[key]) >= {"estimate", "ci95", "ci95_date"}
        sh, wd = d["centre_share_shapley"]["estimate"], d["width_share_shapley"]["estimate"]
        assert sh + wd == pytest.approx(1.0)
    assert set(mg1_atlas["deltas"]) == {"vs_served"}             # an MG-1 candidate has no MG-1 delta


def test_cold_served_fixture_reads_centre_dominated_and_cold(mg1_atlas):
    d = mg1_atlas["models"]["served"]["decomposition"]
    assert d["centre_bias"]["estimate"] < -0.5
    assert abs(d["centre_bias_market"]["estimate"]) < 0.5
    assert d["centre_share_shapley"]["estimate"] > 0.5
    heat = mg1_atlas["models"]["served"]["regimes"]["heat_tercile"]
    assert heat["3"]["market_minus_model_centre"]["estimate"] > heat["1"]["market_minus_model_centre"]["estimate"]


def test_top_decile_is_ceil_ten_percent_and_listed(mg1_atlas):
    c = mg1_atlas["models"]["served"]["concentration"]
    assert c["k_top"] == int(np.ceil(0.1 * c["n_cells"])) == len(c["top_decile"])
    ex = [r["excess"] for r in c["top_decile"]]
    assert ex == sorted(ex, reverse=True)
    assert 0 < c["share_of_total_excess"]["estimate"] <= 1


def test_delta_closure_splits_into_centre_and_width(mg1_atlas):
    d = mg1_atlas["deltas"]["vs_served"]
    total = d["share_of_base_excess_closed"]["estimate"]
    assert d["closed_in_centre_share"]["estimate"] + d["closed_in_width_share"]["estimate"] == pytest.approx(total)
    assert d["closed_excess"]["estimate"] == pytest.approx(-d["candidate_minus_base_brier"]["estimate"])
    assert set(d["per_hour"]) and set(d["per_market"]) == {"m1", "m2", "m3"}


def test_served_candidate_equals_served_and_market_candidate_has_zero_excess(layout_root):
    exp = _fixture_expected(layout_root)
    served = la.run_atlas(layout_root, data.CandidateSpec("served"), control_expected=exp)
    assert "vs_served" not in served["deltas"] and "vs_mg1" in served["deltas"]
    a, b = served["models"]["candidate"]["decomposition"], served["models"]["served"]["decomposition"]
    assert a["excess_over_market"] == b["excess_over_market"]
    market = la.run_atlas(layout_root, data.CandidateSpec("market"), control_expected=exp)
    d = market["models"]["candidate"]["decomposition"]
    assert d["excess_over_market"]["estimate"] == pytest.approx(0.0, abs=1e-12)
    assert d["R"]["estimate"] == pytest.approx(1.0)


def test_cli_writes_content_addressed_json_and_markdown(layout_root, tmp_path, monkeypatch):
    monkeypatch.setattr(la, "CONTROL_EXPECTED", _fixture_expected(layout_root))
    out = tmp_path / "out"
    assert la.main(["atlas", "--layout", str(layout_root), "--candidate", "mg1", "--out", str(out)]) == 0
    (js,) = out.glob("*.json")
    assert hashlib.sha256(js.read_bytes()).hexdigest() == js.stem
    md = (out / f"{js.stem}.md").read_text(encoding="utf-8")
    assert "Positive control **PASS**" in md and "Delta: candidate vs served" in md


# ----------------------------------------------------------------------------- L5 parity

def _l5_shift(geo, p, delta, snaps):
    """Lane L5's per-snapshot shift loop (analyse.py @ dee30cabe), kept verbatim as the reference."""
    t = geo.t
    out = p.copy()
    for s, d in zip(snaps, delta[snaps]):
        a, n = t.offsets[s], t.n[s]
        sl = slice(a, a + n)
        kind, low, high, w = geo.kind[sl], geo.low[sl], geo.high[sl], int(geo.w[a])
        q = p[sl] / max(p[sl].sum(), 1e-300)
        lo_int = np.where(kind == "lte", high - w + 1, low).astype(int)
        hi_int = np.where(kind == "gte", low + w - 1, high).astype(int)
        g0, g1 = int(lo_int.min()) - 40, int(hi_int.max()) + 40
        grid = np.zeros(g1 - g0 + 1)
        for m, lo_, hi_ in zip(q, lo_int, hi_int):
            grid[lo_ - g0:hi_ - g0 + 1] += m / (hi_ - lo_ + 1)
        knots = np.concatenate([[g0 - 0.5], np.arange(g0, g1 + 1) + 0.5])
        cdf = np.concatenate([[0.0], np.cumsum(grid)])

        def F(x):
            return np.interp(np.asarray(x, float) - d, knots, cdf, left=0.0, right=1.0)

        lo_e, hi_e = geo.lo_edge[sl], geo.hi_edge[sl]
        new = np.where(np.isinf(hi_e), 1.0, F(np.where(np.isinf(hi_e), 0, hi_e))) - \
            np.where(np.isinf(lo_e), 0.0, F(np.where(np.isinf(lo_e), 0, lo_e)))
        new = np.maximum(new, 0)
        new[t.impossible[sl]] = 0.0
        tot = new.sum()
        out[sl] = new / tot if tot > 0 else p[sl]
    return out


def test_vectorised_shift_matches_l5_loop(layout_root, monkeypatch):
    _, t = _table(layout_root)
    geo = la.Geometry(t)
    rng = np.random.default_rng(3)
    delta = rng.normal(0, 3, len(t.snaps))
    snaps = np.arange(len(t.snaps))
    monkeypatch.setattr(la, "SHIFT_CHUNK", 37)                     # exercise chunk boundaries
    np.testing.assert_allclose(geo.shift(t.p_served, delta, snaps), _l5_shift(geo, t.p_served, delta, snaps),
                               atol=1e-12)
    c_s, _ = geo.centre_sd(t.p_served)
    c_m, _ = geo.centre_sd(t.p_market)
    shifted, _ = geo.centre_sd(geo.shift(t.p_served, c_m - c_s, snaps))
    assert np.mean(np.abs(shifted - c_m)) < np.mean(np.abs(c_s - c_m))


def test_mg1_follows_lane_g_rule(layout_root):
    _, t = _table(layout_root)
    frame = la.mg1_frame(t)
    s = t.snaps.iloc[0]
    got = frame[frame.row_key == s.row_key].sort_values("band_index").p.to_numpy()
    np.testing.assert_allclose(got, _pmf_raw(s.v2_mean, max(s.v2_stddev, 1.0)), atol=1e-12)


def _pmf_raw(mu, sd):
    out = []
    for kind, lo, hi in BANDS:
        up = np.inf if kind == "gte" else hi + .5
        low = -np.inf if kind == "lte" else lo - .5
        out.append(norm.cdf((up - mu) / sd) - norm.cdf((low - mu) / sd))
    return np.asarray(out)


# ----------------------------------------------------------------------------- data rule and guards

@pytest.mark.parametrize("name", ["data88a_rows.jsonl", "panel_candidate.jsonl", "PANEL/x.jsonl"])
def test_inputs_naming_88a_or_panel_are_refused(layout_root, tmp_path, name):
    path = tmp_path / name
    with pytest.raises(data.Refused, match="88a or panel"):
        la.run_atlas(layout_root, data.CandidateSpec("distributions", str(path), no_training=True),
                     control_expected=_fixture_expected(layout_root))


def test_regimes_file_with_a_later_date_is_refused(layout_root, tmp_path):
    path = tmp_path / "regimes.parquet"
    pd.DataFrame({"date": ["2026-09-30"], "market": ["m1"], "R1_frontal": [True]}).to_parquet(path)
    with pytest.raises(data.Refused, match="after 2026-09-29"):
        la.run_atlas(layout_root, data.CandidateSpec("mg1"), regimes_path=path,
                     control_expected=_fixture_expected(layout_root))


def test_regimes_flags_are_scored_when_given(layout_root, tmp_path):
    _, t = _table(layout_root)
    keys = pd.DataFrame(t.keys, columns=["date", "market"])
    rng = np.random.default_rng(5)
    keys["R1_frontal"] = rng.random(len(keys)) < 0.3
    keys["overnight_low_gap"] = rng.normal(0, 3, len(keys))
    keys["R4_low_gap"] = keys.overnight_low_gap.abs() >= 3
    path = tmp_path / "regimes.parquet"
    keys.to_parquet(path)
    res = la.run_atlas(layout_root, data.CandidateSpec("mg1"), regimes_path=path,
                       control_expected=_fixture_expected(layout_root))
    flags = res["models"]["served"]["regimes"]["flags"]
    assert {"R1_frontal", "R4_low_gap", "R5_revision"} <= set(flags)
    assert all(f["verdict"] in {"NO_SIGNAL", "SIGNAL", "STRONG_SIGNAL"} for f in flags.values())


def test_regime_extractor_never_parses_a_line_after_the_target_date(tmp_path, monkeypatch):
    path = tmp_path / "replay_inputs.jsonl"
    lines = [{"captured_at_local": "2026-09-29T00:05:00", "sources": {}, "k": 1},
             {"captured_at_local": "2026-09-29T23:55:00", "sources": {}, "k": 2},
             {"captured_at_local": "2026-09-30T00:05:00", "sources": {}, "k": 3}]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    parsed = []
    real = json.loads
    monkeypatch.setattr(la.json, "loads", lambda s, *a, **k: parsed.append(real(s)) or parsed[-1])
    first, last = la.first_and_last_on_date(path, date(2026, 9, 29))
    assert first["k"] == 1 and last["k"] == 2
    assert all(rec["k"] != 3 for rec in parsed)


def test_regimes_cli_refuses_a_first_date_after_the_window(tmp_path):
    assert la.main(["regimes", "--replay-root", str(tmp_path), "--layout", str(tmp_path),
                    "--first-date", "2026-09-30", "--out", str(tmp_path / "r.parquet")]) == 2


def test_import_guard_fails_closed_on_the_capture_host_and_when_identity_is_unprovable():
    with pytest.raises(ImportError, match="capture host"):
        la.refuse_production_import("nt", lambda: ("abc", "abc"))
    with pytest.raises(ImportError, match="not provable"):
        la.refuse_production_import("nt", lambda: (_ for _ in ()).throw(OSError("no registry")))
    with pytest.raises(ImportError):
        la.refuse_production_import("nt", lambda: ("", "abc"))
    la.refuse_production_import("nt", lambda: ("abc", "def"))
    la.refuse_production_import("posix", lambda: ("abc", "abc"))


def test_module_has_no_network_imports():
    source = Path(la.__file__).read_text(encoding="utf-8")
    for token in ("import urllib", "from urllib", "import requests", "import http", "import socket"):
        assert token not in source
