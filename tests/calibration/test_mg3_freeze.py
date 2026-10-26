"""Lane L2 MG-3 freeze prep (1a): frozen P3d_H states and blend_l6_H weights (synthetic fits, no outcome join).

Guards: rule_mg3_p3dh_state.md (sha 9e63899d...) and rule_mg3_blend_weights.md (sha 4fb02a2c...) - the frozen
state's serve math reproduces the in-process P3d_H fit's distribution exactly (k columns appended after the
day-of-year columns, NaN k columns kept); the loader checks the sha256 before unpickling and refuses a foreign schema;
the dev re-emit comparison fails on a key mismatch, a missing row or |dp| > 1e-12; the freezes refuse unbound inputs;
(1b) the release binding carries RN-1's constants, its recomputed indices, the land and stations shas and every
executed file, and verification refuses any drift (file, constant, land file, state block or point rule).
"""
import hashlib
import importlib
import json
import math
import pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

RULES = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/mg3"
CENTRE = "2026-08-23"


def _frame(n_days=10, years=(2021, 2022, 2023), markets=("atlanta", "nyc"), hour=13, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for market in markets:
        for year in years:
            for d in range(n_days):
                fh = 80.0 + rng.normal(0, 4)
                y = round(fh + 1.0 + rng.normal(0, 1.5))
                F = y - abs(round(rng.normal(0, 2)))
                target = f"{year}-08-{17 + d:02d}"
                doy = date.fromisoformat(target).timetuple().tm_yday
                k_max = float("nan") if d % 4 == 0 else fh + rng.normal(0, 2)
                rows.append({
                    "market": market, "centre": CENTRE, "season": "aug_sep", "hour": hour, "target_date": target,
                    "year": year, "y": float(y), "F": float(F), "fh": fh, "lat": 33.6, "lon": -84.4, "elev": 300.0,
                    "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                    "x_high_so_far": float(F), "x_current_temp": float(F) - 1.0,
                    "market_code": float(prm.R0_MARKETS.index(market)),
                    "k_max": k_max, "k_gap": k_max - fh, "k_tcdc": float(rng.uniform(0, 100)),
                })
    return pd.DataFrame(rows)


def _state(frame, hour=13):
    entry = prm._rung_entry(frame, *prm._arm_spec(prm.RK_ARMS[prm.MG3_ARM]))
    markets = sorted(frame["market"].unique())
    buckets = {m: list(range(70, 100)) for m in markets}
    state = {
        "schema": prm.MG3_STATE_SCHEMA, "arm": prm.MG3_ARM, "block": "13-16", "markets": markets,
        "centres": [CENTRE], "season_of": {f"{m:02d}": prm.season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
        "coords": {m: [33.6, -84.4, 300.0] for m in markets}, "buckets": buckets,
        "constants": {"min_scale": prm.MIN_SCALE, "clim_alpha": 0.10, "levels": ["high_so_far", "current_temp"]},
        "conversion": {"enabled": False, "rule_id": None, "rule": None},
        "extra_hgb": ["k_max", "k_gap", "k_tcdc"], "hours": {hour: prm.mg3_hour_entry(entry)},
    }
    return state, entry, buckets


def test_rule_files_match_the_bound_shas():
    for name, sha in (("rule_mg3_p3dh_state.md", prm.MG3_STATE_RULE_SHA256),
                      ("rule_mg3_blend_weights.md", prm.MG3_WEIGHTS_RULE_SHA256)):
        assert hashlib.sha256((RULES / name).read_bytes()).hexdigest() == sha
    assert prm.MG3_BLOCKS["07-12"]["hours"] == prm.RR_HOURS and prm.MG3_BLOCKS["13-16"]["hours"] == prm.RK_HOURS
    assert prm.RK_ARMS[prm.MG3_ARM]["extra_hgb"] == ("k_max", "k_gap", "k_tcdc")


def test_frozen_state_reproduces_the_in_process_distribution():
    frame = _frame()
    state, entry, buckets = _state(frame)
    state = pickle.loads(pickle.dumps(state, protocol=4))  # what the control actually serves from
    assert state["hours"][13]["mean"]["extra_hgb"] == ["k_max", "k_gap", "k_tcdc"]
    for i in (0, 1, 5, len(frame) - 1):  # rows 0 and 20 have NaN k columns
        one = frame.iloc[[i]].reset_index(drop=True)
        r = one.iloc[0]
        ref = prm._dist_from_fit(entry, one, buckets, r["market"])[0]
        got = prm.mg3_state_distribution(
            state, 13, market=r["market"], target_date=date.fromisoformat(r["target_date"]),
            high_so_far=float(r["F"]), current_temp=float(r["x_current_temp"]), nbm_mean=float(r["fh"]),
            extra={c: r[c] for c in state["extra_hgb"]})
        assert set(got) == set(ref)
        assert max(abs(got[k] - ref[k]) for k in ref) <= prm.MG3_CONTROL_TOL
        X, _, _, _ = prm.mg3_state_X(
            state, 13, market=r["market"], target_date=date.fromisoformat(r["target_date"]),
            high_so_far=float(r["F"]), current_temp=float(r["x_current_temp"]), nbm_mean=float(r["fh"]),
            extra={c: r[c] for c in state["extra_hgb"]})
        _, X_ref = entry["fit"]["mean"].predict(one)
        assert X.shape == X_ref.shape
        assert np.array_equal(np.isnan(X), np.isnan(X_ref))
        assert np.nanmax(np.abs(X - X_ref)) <= 1e-12


def test_state_refuses_extra_ols_columns():
    frame = _frame()
    state, _, _ = _state(frame)
    state["hours"][13]["mean"]["extra_ols"] = ["k_max"]
    r = frame.iloc[1]
    with pytest.raises(prm.PooledModelError, match="extra OLS"):
        prm.mg3_state_distribution(state, 13, market=r["market"], target_date=date.fromisoformat(r["target_date"]),
                                   high_so_far=float(r["F"]), current_temp=float(r["x_current_temp"]),
                                   nbm_mean=float(r["fh"]), extra={c: r[c] for c in state["extra_hgb"]})


def test_loader_checks_sha_before_unpickling_and_the_schema(tmp_path):
    path = tmp_path / "s.pkl"
    blob = pickle.dumps({"schema": prm.MG3_STATE_SCHEMA, "arm": prm.MG3_ARM}, protocol=4)
    path.write_bytes(blob)
    good = hashlib.sha256(blob).hexdigest()
    assert prm.mg3_load_state(path, good)["arm"] == prm.MG3_ARM
    with pytest.raises(prm.PooledModelError, match="sha256"):
        prm.mg3_load_state(path, "0" * 64)
    other = tmp_path / "o.pkl"
    blob = pickle.dumps({"schema": prm.STATE_SCHEMA, "arm": prm.N_ARM}, protocol=4)
    other.write_bytes(blob)
    with pytest.raises(prm.PooledModelError, match="schema"):
        prm.mg3_load_state(other, hashlib.sha256(blob).hexdigest())


def _rows(path, rows):
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    return path


def test_reemit_comparison_tolerance_keys_and_rows(tmp_path):
    base = [{"market": "nyc", "snapshot_id": f"s{i}", "target_date": "2026-08-03",
             "distribution": {"80": 0.25, "81": 0.75}} for i in range(3)]
    ref = _rows(tmp_path / "ref.jsonl", base)
    same = prm._mg3_compare_jsonl(_rows(tmp_path / "a.jsonl", base), ref)
    assert same["pass"] and same["byte_identical"] and same["max_abs_dp"] == 0.0
    tiny = [dict(r, distribution={"80": 0.25 + 1e-14, "81": 0.75 - 1e-14}) for r in base]
    close = prm._mg3_compare_jsonl(_rows(tmp_path / "b.jsonl", tiny), ref)
    assert close["pass"] and not close["byte_identical"]
    off = [dict(r) for r in base]
    off[1] = dict(off[1], distribution={"80": 0.25 + 1e-9, "81": 0.75 - 1e-9})
    bad = prm._mg3_compare_jsonl(_rows(tmp_path / "c.jsonl", off), ref)
    assert not bad["pass"] and bad["first_bad_line"] == 1
    extra_band = [dict(r) for r in base]
    extra_band[2] = dict(extra_band[2], distribution={"80": 0.25, "81": 0.75, "82": 1e-6})
    assert not prm._mg3_compare_jsonl(_rows(tmp_path / "d.jsonl", extra_band), ref)["pass"]
    swapped = [base[1], base[0], base[2]]
    assert prm._mg3_compare_jsonl(_rows(tmp_path / "e.jsonl", swapped), ref)["key_mismatch"] == 2
    assert not prm._mg3_compare_jsonl(_rows(tmp_path / "f.jsonl", base[:2]), ref)["pass"]


def test_freezes_refuse_unbound_inputs(tmp_path):
    rule = tmp_path / "rule.md"
    rule.write_text("not the rule\n", encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="rule"):
        prm.mg3_freeze_state(block="13-16", records_root=tmp_path, layout=tmp_path, replay_root=tmp_path,
                             nbm_train_corpus=rule, hrrr_corpus=tmp_path, reference=rule, out_dir=tmp_path / "o",
                             commit="x", rule_path=rule)
    good_rule = RULES / "rule_mg3_p3dh_state.md"
    with pytest.raises(prm.PooledModelError, match="reference"):
        prm.mg3_freeze_state(block="13-16", records_root=tmp_path, layout=tmp_path, replay_root=tmp_path,
                             nbm_train_corpus=rule, hrrr_corpus=tmp_path, reference=rule, out_dir=tmp_path / "o",
                             commit="x", rule_path=good_rule)
    with pytest.raises(prm.PooledModelError, match="rule"):
        prm.mg3_freeze_weights(layout=tmp_path, emit_dir=tmp_path, coefficients=rule, nowcasts=rule,
                               rr_score=rule, out_dir=tmp_path / "w", commit="x", rule_path=rule)
    with pytest.raises(prm.PooledModelError, match="rr_score"):
        prm.mg3_freeze_weights(layout=tmp_path, emit_dir=tmp_path, coefficients=rule, nowcasts=rule,
                               rr_score=rule, out_dir=tmp_path / "w", commit="x",
                               rule_path=RULES / "rule_mg3_blend_weights.md")
    assert not (tmp_path / "o").exists() and not (tmp_path / "w").exists()


# ----------------------------------------------------------------------------- (1b) RN-1 bound into the release

RN1_MARKETS = ("san-francisco", "atlanta")
RN1_STATIONS = {"KSFO": {"market": "san-francisco", "i": 178, "j": 594, "fi": 177.89484086990853,
                         "fj": 594.4963606137516},
                "KATL": {"market": "atlanta", "i": 1302, "j": 377, "fi": 1302.2445562292987,
                         "fj": 377.00477929978695}}
RN1_MASKS = {"KSFO": [1, 1, 0, 1, 0, 0, 1, 0, 0], "KATL": [1] * 9}  # KSFO's centre cell is water


def _rn1_inputs(tmp_path, monkeypatch, chosen=None):
    corpus = tmp_path / "corpus"
    corpus.mkdir(exist_ok=True)
    (corpus / "stations.json").write_text(json.dumps(RN1_STATIONS), encoding="utf-8")
    land = {"stations_json_sha256": hashlib.sha256((corpus / "stations.json").read_bytes()).hexdigest(),
            "msg_sha256": prm.RR_LAND_MSG_SHA256, "key": prm.RR_LAND_KEY, "stations": {}}
    for icao, s in RN1_STATIONS.items():
        dist = [math.hypot(s["i"] + k % 3 - 1 - s["fi"], s["j"] + k // 3 - 1 - s["fj"]) for k in range(9)]
        land["stations"][icao] = {**{k: s[k] for k in ("i", "j", "fi", "fj")}, "land_block3x3": RN1_MASKS[icao],
                                  "dist_grid_units": dist,
                                  "rn1_chosen_index": (chosen or {"KSFO": 3, "KATL": 4})[icao]}
    path = tmp_path / "land_3x3.json"
    path.write_text(json.dumps(land), encoding="utf-8")
    monkeypatch.setattr(prm, "RR_LAND_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    root = tmp_path / "repo"
    for rel in prm.MG3_RELEASE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"# {rel}\n", encoding="utf-8")
    return path, corpus, root


def test_rn1_constants_are_the_fitted_point_rule():
    assert prm.MG3_RN1["land_sha256"] == "22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6"
    assert prm.MG3_RN1["rule_sha256"] == "e4869491a8480f302c0bb4c33b0d55d4110ef98551f0db26e59d3441e204004b"
    assert prm.MG3_RN1["index"] == {"KSFO": 3} and prm.MG3_RN1["default_index"] == 4
    assert prm.MG3_RN1["stations_json_sha256"] == prm.RR_CORPUS_SHA256["stations.json"]
    assert prm.MG3_POINT_RULES == {"07-12": "rn1", "13-16": "nearest"}
    assert "src/weather/calibration/pooled_residual_model.py" in prm.MG3_RELEASE_FILES


def test_release_binding_carries_rn1_land_sha_and_files_and_verifies(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    binding = prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    assert binding["schema"] == prm.MG3_BINDING_SCHEMA
    assert binding["rn1"]["recomputed"] == {"KATL": 4, "KSFO": 3}
    assert binding["data_files"]["land_3x3.json"] == hashlib.sha256(land.read_bytes()).hexdigest()
    assert set(binding["files"]) == set(prm.MG3_RELEASE_FILES)
    assert binding["rules"]["rn1"] == prm.MG3_RN1["rule_sha256"]
    assert {b: s["sha256"] for b, s in binding["states"].items()} == {"07-12": "PENDING", "13-16": "PENDING"}
    assert binding["weights_sha256"] == "PENDING"
    path = tmp_path / "release-binding.json"
    path.write_text(json.dumps(binding, indent=1, sort_keys=True), encoding="utf-8")
    assert prm.mg3_verify_release(path, land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS) == binding
    # a changed executed file refuses
    (root / prm.MG3_RELEASE_FILES[0]).write_text("# changed\n", encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="pooled_residual_model"):
        prm.mg3_verify_release(path, land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    (root / prm.MG3_RELEASE_FILES[0]).write_text(f"# {prm.MG3_RELEASE_FILES[0]}\n", encoding="utf-8")
    # a bound RN-1 constant that differs from the running one refuses
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["rn1"]["index"] = {"KSFO": 4}
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="rn1"):
        prm.mg3_verify_release(path, land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)


def test_release_binding_refuses_a_land_file_that_moved_or_disagrees(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(prm, "RR_LAND_SHA256", "0" * 64)
    with pytest.raises(prm.PooledModelError, match="land file sha"):
        prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch, chosen={"KSFO": 4, "KATL": 4})
    with pytest.raises(prm.PooledModelError, match="RN-1 index"):
        prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)


def test_release_binding_checks_each_state_block_and_point_rule(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)

    def state(block, land_sha):
        path = tmp_path / f"state_{block}.pkl"
        path.write_bytes(pickle.dumps({"schema": prm.MG3_STATE_SCHEMA, "arm": prm.MG3_ARM, "block": block,
                                       "point_rule": {"land_sha256": land_sha}}, protocol=4))
        return path

    s0712, s1316 = state("07-12", prm.MG3_RN1["land_sha256"]), state("13-16", None)
    binding = prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS,
                                      states={"07-12": s0712, "13-16": s1316})
    assert binding["states"]["07-12"]["sha256"] == hashlib.sha256(s0712.read_bytes()).hexdigest()
    assert binding["states"]["13-16"]["point_rule"] == "nearest"
    with pytest.raises(prm.PooledModelError, match="block"):
        prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS,
                                states={"07-12": s1316})
    with pytest.raises(prm.PooledModelError, match="point rule"):
        prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS,
                                states={"13-16": state("13-16", prm.MG3_RN1["land_sha256"])})
