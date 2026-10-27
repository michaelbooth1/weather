"""Lane L2 MG-3 freeze prep (1a): frozen P3d_H states and blend_l6_H weights (synthetic fits, no outcome join).

Guards: rule_mg3_p3dh_state.md (sha 9e63899d...) and rule_mg3_blend_weights.md (sha 4fb02a2c...) - the frozen
state's serve math reproduces the in-process P3d_H fit's distribution exactly (k columns appended after the
day-of-year columns, NaN k columns kept); the loader checks the sha256 before unpickling and refuses a foreign schema;
the dev re-emit comparison fails on a key mismatch, a missing row or |dp| > 1e-12; the freezes refuse unbound inputs;
(1b) the release binding carries RN-1's constants, its recomputed indices, the land and stations shas and every
executed file, and verification refuses any drift (file, constant, land file, state block or point rule);
(1c) rule_mg3_forward_parity.md (sha 2c6e6045...) - only row_schema 2 R0 rows up to --through are counted, a torn
line is ignored, stamp drift or a missing message fails F0, a cycle newer than the training rule fails F1, slow
retrieval fails F2 except for messages published before the recorder's first start (clarification FP-1),
an archive byte mismatch fails F3c, and without an archive the verdict is PARTIAL, never PASS.
RF-1 (refit_note_rf1.md, sha b13f2e03...): the one SM-L6 weight refit refuses a foreign note, partner, nowcast,
frozen table or rr_score before reading anything.
SM-H wiring (binding_sm_h_state.md, sha 6507946e...): the release binding records the served SM-H 13-15 state
only from a verified load at the bound sha b6bc242a..., with SF excluded; a foreign sha, or a state whose block,
hours, conversion or note sha differ, refuses; verification refuses a binding whose SM-H slot is not re-verified.
0712-1 (clarification_mg3_dc1_0712.md, sha f9e25a90...): the binding records the RF-1 weights 891be564... and the
SM-L6 partner 800072c7... only from verified loads; a wrong weights sha, a wrong partner sha, a foreign RF-1 note,
one without the other, or a file that changes between load and record refuses; verification recomputes both and
refuses a bound sha that differs or a binding made without them.
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


def test_rf1_refit_refuses_a_foreign_note_or_partner_and_records_the_note_sha(tmp_path):
    rule = tmp_path / "x.md"
    rule.write_text("not the note", encoding="utf-8")
    note = RULES / "refit_note_rf1.md"
    assert hashlib.sha256(note.read_bytes()).hexdigest() == prm.MG3_RF1_NOTE_SHA256
    kw = dict(layout=tmp_path, emit_dir=tmp_path, coefficients=rule, nowcasts=rule, season_nowcasts=rule,
              partner_vectors=rule, rr_score=rule, frozen_weights=rule, out_dir=tmp_path / "w", commit="x")
    with pytest.raises(prm.PooledModelError, match="note"):
        prm.mg3_refit_weights_rf1(note_path=rule, **kw)
    with pytest.raises(prm.PooledModelError, match="rr_score"):
        prm.mg3_refit_weights_rf1(note_path=note, **kw)
    assert prm.MG3_RF1_PARTNER_SHA256.startswith("2366d67c")
    assert prm.MG3_RF1_FROZEN_WEIGHTS_SHA256.startswith("c7b8ebc0")
    assert not (tmp_path / "w").exists()


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
    assert {b: s["sha256"] for b, s in binding["states"].items()} == {"07-12": "PENDING", "13-16": "PENDING",
                                                                      prm.SM_H_STATE_BLOCK: "PENDING"}
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


def _smh_state(path, **changes):
    state = {"schema": prm.MG3_STATE_SCHEMA, "arm": prm.MG3_ARM, "block": prm.SM_H_STATE_BLOCK,
             "hours": {h: {} for h in prm.SM_H_HOURS}, "centres": list(prm.SM_H_CENTRES),
             "conversion": {"enabled": False}, "point_rule": {"land_sha256": None},
             "extra_hgb": ["k_max", "k_gap", "k_tcdc"],
             "provenance": {"note_sha256": prm.SM_H_BINDING_SHA256, "rule_sha256": prm.SM_H_RULE_SHA256,
                            "clarification_sha256": prm.SM_H_CLARIFICATION_1_SHA256}}
    state.update(changes)
    path.write_bytes(pickle.dumps(state, protocol=4))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_binding_binds_the_sm_h_state_only_from_a_verified_load(tmp_path, monkeypatch):
    assert prm.SM_H_STATE_SHA256 == "b6bc242a8c2b679069a4090b8912eea3b80af160b6bc228424c846fb3b87a477"
    assert prm.SM_H_EXCLUDED_MARKETS == ("san-francisco",)
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    path, sha = _smh_state(tmp_path / "smh.pkl")
    kwargs = dict(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    # a state whose bytes are not the bound sha refuses before anything is recorded
    with pytest.raises(prm.PooledModelError, match="!= bound"):
        prm.mg3_release_binding(states={prm.SM_H_STATE_BLOCK: path}, **kwargs)
    monkeypatch.setattr(prm, "SM_H_STATE_SHA256", sha)
    binding = prm.mg3_release_binding(states={prm.SM_H_STATE_BLOCK: path}, **kwargs)
    entry = binding["states"][prm.SM_H_STATE_BLOCK]
    assert entry == {"sha256": sha, "point_rule": "nearest", "hours": [13, 14, 15], "replaces": "13-16",
                     "excluded_markets": ["san-francisco"]}
    assert binding["rules"]["sm_h_binding"] == prm.SM_H_BINDING_SHA256
    assert binding["states"]["13-16"]["sha256"] == "PENDING"
    out = tmp_path / "release-binding.json"
    out.write_text(json.dumps(binding), encoding="utf-8")
    assert prm.mg3_verify_release(out, states={prm.SM_H_STATE_BLOCK: path}, **kwargs) == binding
    with pytest.raises(prm.PooledModelError, match="states"):
        prm.mg3_verify_release(out, **kwargs)  # the SM-H slot reads PENDING without the state
    # a state at the bound sha whose contents differ from the binding note refuses
    for field, value in (("block", "13-16"), ("hours", {13: {}, 14: {}}), ("conversion", {"enabled": True}),
                         ("provenance", {"note_sha256": "0" * 64})):
        bad, bad_sha = _smh_state(tmp_path / f"bad_{field}.pkl", **{field: value})
        monkeypatch.setattr(prm, "SM_H_STATE_SHA256", bad_sha)
        with pytest.raises(prm.PooledModelError, match=field if field != "provenance" else "note_sha256"):
            prm.mg3_release_binding(states={prm.SM_H_STATE_BLOCK: bad}, **kwargs)


def test_0712_1_pins_are_the_ruling_and_the_clarification_in_force():
    assert prm.MG3_RF1_WEIGHTS_SHA256 == "891be5640cef9fd3924b98f89f1068108acdf404fbd52a4721cb5d8d9ae8ded5"
    assert prm.MG3_L6_PARTNER_SHA256 == "800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db"
    doc = RULES / "clarification_mg3_dc1_0712.md"
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == prm.MG3_DC1_0712_1_SHA256
    assert prm.MG3_DC1_0712_1_SHA256 == "f9e25a90e56a81326552867fee61ad37b8c159fe56abf6972225be25d459651f"


def _rf1_weights(path, **changes):
    table = {"note_sha256": prm.MG3_RF1_NOTE_SHA256, "rule_sha256": prm.MG3_WEIGHTS_RULE_SHA256,
             "weights": {f"h{h:02d}": 0.25 + 0.05 * i for i, h in enumerate(range(7, 13))}}
    table.update(changes)
    path.write_text(json.dumps(table, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _partner(path, payload=b"synthetic SM-L6 final state"):
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def test_release_binding_binds_rf1_weights_and_l6_partner_from_verified_loads(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    kwargs = dict(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    weights, w_sha = _rf1_weights(tmp_path / "weights.json")
    partner, p_sha = _partner(tmp_path / "sm_l6.pkl")
    monkeypatch.setattr(prm, "MG3_RF1_WEIGHTS_SHA256", w_sha)
    monkeypatch.setattr(prm, "MG3_L6_PARTNER_SHA256", p_sha)
    binding = prm.mg3_release_binding(weights=weights, partner=partner, **kwargs)
    assert binding["weights_sha256"] == w_sha and binding["l6_partner_sha256"] == p_sha
    assert binding["rules"]["mg3_dc1_0712_1"] == prm.MG3_DC1_0712_1_SHA256
    assert binding["schema"] == "mg3_release_binding/2"
    out = tmp_path / "release-binding.json"
    out.write_text(json.dumps(binding), encoding="utf-8")
    assert prm.mg3_verify_release(out, weights=weights, partner=partner, **kwargs) == binding
    # verification recomputes both: without them the slots read PENDING and refuse
    with pytest.raises(prm.PooledModelError, match="weights_sha256"):
        prm.mg3_verify_release(out, **kwargs)
    # a bound partner sha that differs from the recomputed one refuses
    edited = dict(binding, l6_partner_sha256="0" * 64)
    out.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="l6_partner_sha256"):
        prm.mg3_verify_release(out, weights=weights, partner=partner, **kwargs)
    # a bound file whose bytes changed after binding refuses at verification
    out.write_text(json.dumps(binding), encoding="utf-8")
    _partner(partner, b"another state")
    with pytest.raises(prm.PooledModelError, match="!= bound"):
        prm.mg3_verify_release(out, weights=weights, partner=partner, **kwargs)


def test_release_binding_refuses_a_wrong_weights_sha(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    kwargs = dict(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    weights, _ = _rf1_weights(tmp_path / "weights.json")
    partner, p_sha = _partner(tmp_path / "sm_l6.pkl")
    monkeypatch.setattr(prm, "MG3_L6_PARTNER_SHA256", p_sha)
    with pytest.raises(prm.PooledModelError, match="MG-3 weights .* != bound 891be564"):
        prm.mg3_release_binding(weights=weights, partner=partner, **kwargs)
    # at the bound sha, a table whose RF-1 note or hours differ still refuses
    for field, value in (("note_sha256", "0" * 64), ("weights", {"h07": 0.5})):
        bad, bad_sha = _rf1_weights(tmp_path / f"bad_{field}.json", **{field: value})
        monkeypatch.setattr(prm, "MG3_RF1_WEIGHTS_SHA256", bad_sha)
        with pytest.raises(prm.PooledModelError, match=field if field != "weights" else "hours"):
            prm.mg3_release_binding(weights=bad, partner=partner, **kwargs)


def test_release_binding_refuses_a_wrong_partner_sha_or_a_missing_half(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    kwargs = dict(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS)
    weights, w_sha = _rf1_weights(tmp_path / "weights.json")
    partner, _ = _partner(tmp_path / "sm_l6.pkl")
    monkeypatch.setattr(prm, "MG3_RF1_WEIGHTS_SHA256", w_sha)
    with pytest.raises(prm.PooledModelError, match="L6 partner .* != bound 800072c7"):
        prm.mg3_release_binding(weights=weights, partner=partner, **kwargs)
    with pytest.raises(prm.PooledModelError, match="L6 partner sha is missing"):
        prm.mg3_release_binding(weights=weights, **kwargs)
    with pytest.raises(prm.PooledModelError, match="weights sha is missing"):
        prm.mg3_release_binding(partner=partner, **kwargs)
    binding = prm.mg3_release_binding(**kwargs)
    assert binding["weights_sha256"] == binding["l6_partner_sha256"] == "PENDING"


def test_release_binding_refuses_a_file_that_changes_between_load_and_record(tmp_path, monkeypatch):
    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    weights, w_sha = _rf1_weights(tmp_path / "weights.json")
    partner, p_sha = _partner(tmp_path / "sm_l6.pkl")
    monkeypatch.setattr(prm, "MG3_RF1_WEIGHTS_SHA256", w_sha)
    monkeypatch.setattr(prm, "MG3_L6_PARTNER_SHA256", p_sha)
    real = prm._rr_sha
    monkeypatch.setattr(prm, "_rr_sha", lambda p: "f" * 64 if Path(p) == partner else real(p))
    with pytest.raises(prm.PooledModelError, match="L6 partner .* changed while binding"):
        prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS, weights=weights,
                                partner=partner)


# ----------------------------------------------------------------------------- (1c) forward HRRR parity scorer

FWD_TZ = {"KSFO": ("America/Los_Angeles", -7), "KATL": ("America/New_York", -4)}
FWD_DAY = "2026-10-26"


def _iso(dt_):
    return dt_.isoformat()


def _recorder(tmp_path, monkeypatch, name="rec", hours=(7, 13), rows_edit=None, msg_edit=None,
              first_started="2026-10-25T00:00:00Z"):
    """A synthetic recorder dir (and its land file) in the recorder's own shapes: one row per station x hour."""
    from datetime import datetime, timedelta, timezone

    utc = timezone.utc
    rec = tmp_path / name
    rec.mkdir()
    stations = {icao: dict(s, tz=FWD_TZ[icao][0]) for icao, s in RN1_STATIONS.items()}
    stations["CYYZ"] = {"market": "toronto", "i": 1377, "j": 768, "fi": 1377.2, "fj": 767.8, "tz": "America/Toronto"}
    (rec / "stations.json").write_text(json.dumps(stations), encoding="utf-8")
    land = {"stations_json_sha256": hashlib.sha256((rec / "stations.json").read_bytes()).hexdigest(),
            "msg_sha256": prm.RR_LAND_MSG_SHA256, "key": prm.RR_LAND_KEY, "stations": {}}
    for icao, s in RN1_STATIONS.items():
        dist = [math.hypot(s["i"] + k % 3 - 1 - s["fi"], s["j"] + k // 3 - 1 - s["fj"]) for k in range(9)]
        land["stations"][icao] = {**{k: s[k] for k in ("i", "j", "fi", "fj")}, "land_block3x3": RN1_MASKS[icao],
                                  "dist_grid_units": dist, "rn1_chosen_index": {"KSFO": 3, "KATL": 4}[icao]}
    land_path = tmp_path / f"{name}_land.json"
    land_path.write_text(json.dumps(land), encoding="utf-8")
    monkeypatch.setattr(prm, "RR_LAND_SHA256", hashlib.sha256(land_path.read_bytes()).hexdigest())
    (rec / "meta.json").write_text(json.dumps({} if first_started is None else {"first_started_utc": first_started}),
                                   encoding="utf-8")
    messages, rows = {}, []
    for icao in ("KATL", "KSFO"):
        offset = FWD_TZ[icao][1]
        for hour in hours:
            base = datetime(2026, 10, 26, 0, 0, tzinfo=utc)
            snap, end = base + timedelta(hours=hour - offset), base + timedelta(hours=17 - offset)
            cycle = snap - timedelta(hours=2)
            fhs = list(range(2, 2 + int((end - snap).total_seconds() // 3600) + 1))
            shas = {"TMP": [], "TCDC": []}
            tmp, tcdc, near = [], [], []
            for fh in fhs:
                for var, base in (("TMP", 285.0), ("TCDC", 20.0)):
                    key = prm.rk_message_key(cycle, fh)
                    m = messages.get((key, var))
                    if m is None:
                        points = {}
                        for st, idx in (("KATL", 4), ("KSFO", 3), ("CYYZ", 4)):
                            block = [base + 0.37 * k + 0.11 * fh + (st == "KSFO") for k in range(9)]
                            points[st] = {"block3x3": block, "nearest": block[4], "rn1": block[idx], "rn1_index": idx}
                        m = {"cycle_utc": _iso(cycle), "fh": fh, "key": key,
                             "idx_record": f"{prm.RK_VARIABLES[var]}:{fh} hour fcst:",
                             "grib_last_modified": _iso(cycle + timedelta(minutes=50)).replace("+00:00", ".000Z"),
                             "idx_last_modified": _iso(cycle + timedelta(minutes=51)).replace("+00:00", ".000Z"),
                             "captured_at_utc": _iso(cycle + timedelta(minutes=55)),
                             "msg_sha256": hashlib.sha256(f"{key}{var}".encode()).hexdigest(), "points": points}
                        messages[(key, var)] = m
                    shas[var].append(m["msg_sha256"])
                    (tmp if var == "TMP" else tcdc).append(m["points"][icao]["rn1"])
                    if var == "TMP":
                        near.append(m["points"][icao]["nearest"])
            to_f = lambda k: (k - 273.15) * 9.0 / 5.0 + 32.0  # noqa: E731 - the recorder's own conversion
            rows.append({"station": icao, "market": RN1_STATIONS[icao]["market"], "local_date": FWD_DAY,
                         "hour_local": hour, "snapshot_utc": _iso(snap), "window_end_utc": _iso(end),
                         "cycle_utc": _iso(cycle), "fhs": fhs, "training_rule_cycle_utc": _iso(cycle),
                         "hrrr_msg_sha256": shas, "k_max_f": max(to_f(x) for x in tmp),
                         "k_tcdc": sum(tcdc) / len(tcdc), "k_max_f_nearest_cell": max(to_f(x) for x in near),
                         "k_miss": 0, "row_schema": 2, "paused_at_snapshot": False})
    rows.append(dict(rows[0], row_schema=None, k_max_f=0.0))  # schema-1 row: not counted
    rows.append(dict(rows[0], local_date="2026-10-27", k_max_f=0.0))  # after --through: not counted
    for edit in rows_edit or ():
        edit(rows)
    msgs = list(messages.values())
    for edit in msg_edit or ():
        edit(msgs)
    (rec / "snapshots.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + '{"torn', encoding="utf-8")
    (rec / "messages.jsonl").write_text("".join(json.dumps(m) + "\n" for m in msgs), encoding="utf-8")
    return rec, land_path


def _archive_from(rec, tmp_path, name="arch", sha_edit=None):
    """An archive-path corpus with the recorder's messages and the training-rule selections."""
    arch = tmp_path / name
    arch.mkdir()
    (arch / "stations.json").write_bytes((rec / "stations.json").read_bytes())
    msgs = [json.loads(line) for line in (rec / "messages.jsonl").read_text(encoding="utf-8").splitlines()]
    for m in msgs:
        if sha_edit and sha_edit(m):
            m["msg_sha256"] = "f" * 64
    (arch / "manifest.jsonl").write_text("".join(json.dumps(m) + "\n" for m in msgs), encoding="utf-8")
    from datetime import datetime, timedelta

    sel = []
    for line in (rec / "snapshots.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.endswith("}"):
            continue
        r = json.loads(line)
        if r.get("row_schema") == 2 and r["local_date"] == FWD_DAY:
            sel.append({"station": r["station"], "local_date": r["local_date"], "hour_local": r["hour_local"],
                        "snapshot_utc": r["snapshot_utc"], "cycle_utc": r["training_rule_cycle_utc"],
                        "fhs": r["fhs"], "latest_available_utc": (datetime.fromisoformat(r["training_rule_cycle_utc"])
                                                         + timedelta(minutes=51)).isoformat()})
    (arch / "selections.jsonl").write_text("".join(json.dumps(s) + "\n" for s in sel), encoding="utf-8")
    return arch


def _parity(tmp_path, rec, land, out="out", archive=None):
    return prm.mg3_forward_parity(recorder_dir=rec, land=land, out_dir=tmp_path / out, through=FWD_DAY,
                                  commit="test", archive_dir=archive, markets=RN1_MARKETS)


def test_forward_parity_clean_recorder_is_partial_without_archive_and_pass_with_it(tmp_path, monkeypatch):
    rec, land = _recorder(tmp_path, monkeypatch)
    result = _parity(tmp_path, rec, land)
    assert result["verdict"] == "PARTIAL (archive pending)"
    for block in ("07-12", "13-16"):
        b = result["blocks"][block]
        assert b["rows"] == 2  # schema-1, CYYZ, torn and after-through rows are not counted
        assert b["F0"]["pass"] and b["F0"]["max_dk_max"] <= 1e-9 and b["F1"]["pass"] and b["F2"]["pass"]
        assert b["F4"]["pass"] and "F3" not in b
    assert (tmp_path / "out" / "forward_parity.json").is_file()
    archived = _parity(tmp_path, rec, land, out="out2", archive=_archive_from(rec, tmp_path))
    assert archived["verdict"] == "PASS"
    assert all(archived["blocks"][b]["F3"]["values_compared"] == 2 for b in ("07-12", "13-16"))
    with pytest.raises(prm.PooledModelError, match="overwrite"):
        _parity(tmp_path, rec, land)


def test_forward_parity_stamp_drift_or_missing_message_fails_f0(tmp_path, monkeypatch):
    def drift(rows):
        rows[0]["k_max_f"] += 1e-6  # KATL h07: the RN-1 stamp

    rec, land = _recorder(tmp_path, monkeypatch, rows_edit=[drift])
    result = _parity(tmp_path, rec, land)
    assert result["verdict"] == "FAIL"
    assert not result["blocks"]["07-12"]["F0"]["pass"] and result["blocks"]["13-16"]["F0"]["pass"]
    assert result["blocks"]["07-12"]["F0"]["first_bad"] == {"station": "KATL", "local_date": FWD_DAY,
                                                             "hour_local": 7}

    def drop_one(msgs):
        msgs.pop()

    rec2, land2 = _recorder(tmp_path, monkeypatch, name="rec2", msg_edit=[drop_one])
    assert _parity(tmp_path, rec2, land2, out="out2")["verdict"] == "FAIL"


def test_forward_parity_newer_cycle_than_training_rule_fails_f1(tmp_path, monkeypatch):
    def newer(rows):
        rows[1]["training_rule_cycle_utc"] = rows[1]["cycle_utc"][:11] + "00:00:00+00:00"  # training rule older

    rec, land = _recorder(tmp_path, monkeypatch, rows_edit=[newer])
    result = _parity(tmp_path, rec, land)
    f1 = result["blocks"]["13-16"]["F1"]
    assert result["blocks"]["07-12"]["F1"]["pass"]
    assert f1["newer"] == 1 and not f1["pass"] and result["verdict"] == "FAIL"


def test_forward_parity_slow_retrieval_fails_f2(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    def slow(msgs):
        for m in msgs:
            m["captured_at_utc"] = (datetime.fromisoformat(m["captured_at_utc"]) + timedelta(minutes=30)).isoformat()

    rec, land = _recorder(tmp_path, monkeypatch, msg_edit=[slow])
    result = _parity(tmp_path, rec, land)
    assert not result["blocks"]["07-12"]["F2"]["pass"] and result["blocks"]["07-12"]["F2"]["max_s"] > 600


def test_forward_parity_fp1_excludes_only_messages_published_before_the_first_start(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    def slow(cut):
        def edit(msgs):
            for m in msgs:
                if datetime.fromisoformat(m["cycle_utc"]) < cut:
                    m["captured_at_utc"] = (datetime.fromisoformat(m["captured_at_utc"])
                                            + timedelta(minutes=30)).isoformat()
        return edit

    start = "2026-10-26T16:00:00Z"  # 13-16 block: KATL's 15Z cycle is published before it, KSFO's 18Z after
    before = datetime.fromisoformat("2026-10-26T16:00:00+00:00")
    rec, land = _recorder(tmp_path, monkeypatch, msg_edit=[slow(before)], first_started=start)
    f2 = _parity(tmp_path, rec, land)["blocks"]["13-16"]["F2"]
    assert f2["pass"] and f2["excluded_prestart"] > 0 and f2["max_s"] <= 600
    # a slow message published AFTER the first start (a later recorder death) still counts against F2
    after = datetime.fromisoformat("2026-10-26T23:59:00+00:00")
    rec2, land2 = _recorder(tmp_path, monkeypatch, name="rec2", msg_edit=[slow(after)], first_started=start)
    f2b = _parity(tmp_path, rec2, land2, out="out2")["blocks"]["13-16"]["F2"]
    assert not f2b["pass"] and f2b["max_s"] > 600
    rec3, land3 = _recorder(tmp_path, monkeypatch, name="rec3", first_started=None)
    with pytest.raises(prm.PooledModelError, match="first_started_utc"):
        _parity(tmp_path, rec3, land3, out="out3")


def test_forward_parity_archive_byte_mismatch_fails_f3c(tmp_path, monkeypatch):
    rec, land = _recorder(tmp_path, monkeypatch)
    arch = _archive_from(rec, tmp_path, sha_edit=lambda m: m["fh"] == 2)
    result = _parity(tmp_path, rec, land, archive=arch)
    assert result["verdict"] == "FAIL"
    assert not result["blocks"]["07-12"]["F3"]["F3c_pass"] and result["blocks"]["07-12"]["F3"]["F3b_pass"]
