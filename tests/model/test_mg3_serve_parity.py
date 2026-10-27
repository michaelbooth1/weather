"""Train/serve parity: weather.model.mg3_serve against the research code the MG-3 states were fitted with.

Guards: train/serve feature parity (AGENTS.md model contract) for MG-3's P3d_H serve (rule_mg3_p3dh_state.md s2)
and its HRRR extras (R-K raw path, R-R RN-1 point rule, the 10-minute availability margin before the snapshot,
the 17:00 valid-window end). The serve copies must equal the research sources exactly on synthetic inputs, and on
L2's frozen states when they are present on this workstation (read-only). WS-only: the research module refuses the
capture host, so this module skips there; the synthetic tests in test_mg3_serve.py carry the coverage in CI.
Build -> serve (A item 3): a binding written by L2's one builder (``prm.mg3_release_binding``, schema /2) from
synthetic files is served by this one reader (``ms.load_serve``) unchanged - RF-1-shape weights fitted against the
season nowcasts (master: the binding pins 714fa14e, the season file, so builder and serve read the same nowcasts).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.host_guard import import_or_skip_on_capture_host
from tests.model.test_mg3_serve import _l6_state, _messages, _sha, _state, _write
from weather.model import mg3_arms
from weather.model import mg3_serve as ms

prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")

REAL = {"07-12": (Path("C:/t/l2/mg3/state_0712/p3d_h_state.pkl"),
                  "e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0", tuple(range(7, 13))),
        ms.SM_H_BLOCK: (Path("C:/t/l2/mg3/state_smh/p3d_h_state.pkl"), ms.SM_H_STATE_SHA256, (13, 14, 15))}
INPUTS = [dict(market="atlanta", target_date=date(2026, 8, 10), high_so_far=74.0, current_temp=73.0, nbm_mean=80.0),
          dict(market="atlanta", target_date=date(2025, 11, 20), high_so_far=55.0, current_temp=55.0, nbm_mean=None),
          dict(market="san-francisco", target_date=date(2026, 9, 1), high_so_far=63.2, current_temp=61.0,
               nbm_mean=66.5)]
EXTRAS = [{"k_max": 81.0, "k_gap": 1.0, "k_tcdc": 30.0}, {"k_max": math.nan, "k_gap": math.nan, "k_tcdc": math.nan}]


def _same(a, b):
    assert set(a) == set(b)
    assert all(abs(a[k] - b[k]) == 0.0 for k in a), max(abs(a[k] - b[k]) for k in a)


@pytest.mark.parametrize("block,hours", [("07-12", range(7, 13)), (ms.SM_H_BLOCK, (13, 14, 15))])
def test_p3dh_serve_equals_the_research_state_distribution_on_a_synthetic_state(block, hours):
    st = _state(block, tuple(hours), seed=11)
    for h in hours:
        for kw in INPUTS:
            for extra in EXTRAS:
                X, *_ = ms.p3dh_X(st, h, extra=extra, **kw)
                Xr, *_ = prm.mg3_state_X(st, h, extra=extra, **kw)
                np.testing.assert_array_equal(X, Xr)
                _same(ms.p3dh_distribution(st, h, extra=extra, **kw),
                      prm.mg3_state_distribution(st, h, extra=extra, **kw))


@pytest.mark.parametrize("block", sorted(REAL))
def test_p3dh_serve_equals_the_research_math_on_the_frozen_state(block):
    path, sha, hours = REAL[block]
    if not path.exists():
        pytest.skip(f"L2's frozen {block} state is WS-local")
    st = ms.load_p3dh_state(path, sha, block=block, hours=hours)
    for h in hours:
        for kw in INPUTS:
            for extra in EXTRAS:
                _same(ms.p3dh_distribution(st, h, extra=extra, **kw),
                      prm.mg3_state_distribution(st, h, extra=extra, **kw))


# ----------------------------------------------------------------------------- HRRR extras vs the training columns

def _corpus(tmp_path):
    """A small L13-shaped corpus: two stations, hour 10 on four days, each day a different case."""
    stations = {"KATL": {"market": "atlanta", "tz": "America/New_York"},
                "KSFO": {"market": "san-francisco", "tz": "America/Los_Angeles"}}
    (tmp_path / "stations.json").write_text(json.dumps(stations), encoding="utf-8")
    manifest, selections = [], []
    cases = {"2026-08-10": "covered", "2026-08-11": "pit", "2026-08-12": "window", "2026-08-13": "absent",
             "2026-08-14": "no_cycle"}
    for day, case in cases.items():
        for icao, tz, offset in (("KATL", "America/New_York", 4), ("KSFO", "America/Los_Angeles", 7)):
            snap_h = 10 + offset
            cycle = f"{day}T{snap_h - 2:02d}:00:00+00:00"
            fhs = (2, 3) if case != "window" else (1, 2)
            latest = f"{day}T{snap_h - 1:02d}:{51 if case == 'pit' else 40}:00+00:00"
            selections.append({"station": icao, "local_date": day, "hour_local": 10,
                               "snapshot_utc": f"{day}T{snap_h:02d}:00:00+00:00",
                               "cycle_utc": None if case == "no_cycle" else cycle, "fhs": [] if case == "no_cycle"
                               else list(fhs), "latest_available_utc": latest})
            if case == "no_cycle":
                continue
            msgs = _messages(cycle=cycle, fhs=fhs, tmp_k=(295.0 + offset, 296.5 + offset),
                             tcdc=(10.0 * offset, 5.0))
            for m in msgs:
                m["points"] = {icao: m["points"]["KATL"]}
                if case == "absent" and m["fh"] == fhs[-1] and m["idx_record"].startswith("TCDC"):
                    continue
                manifest.append(m)
    with open(tmp_path / "manifest.jsonl", "w", encoding="utf-8") as f:
        merged = {}
        for m in manifest:  # one manifest record per message, with both stations' points
            k = (m["cycle_utc"], m["fh"], m["idx_record"])
            merged.setdefault(k, {**m, "points": {}})["points"].update(m["points"])
        f.writelines(json.dumps(m) + "\n" for m in merged.values())
    with open(tmp_path / "selections.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(s) + "\n" for s in selections)
    return stations, list(merged.values()), selections


@pytest.mark.parametrize("point", [None, {"KATL": 4, "KSFO": 3}, {"KATL": 2}])
def test_hrrr_extras_equal_the_training_columns(tmp_path, point):
    stations, manifest, selections = _corpus(tmp_path)
    train, _ = prm.rk_hrrr_columns(tmp_path, ("atlanta", "san-francisco"), hours=(10,), point=point)
    reasons = set()
    for s in selections:
        market = stations[s["station"]]["market"]
        msgs = [m for m in manifest if m["cycle_utc"] == s["cycle_utc"]]
        got = ms.hrrr_raw_path(s, msgs, icao=s["station"], tz=stations[s["station"]]["tz"],
                               local_date=s["local_date"], hour=10, point=point)
        want = train[(market, s["local_date"], 10)]
        reasons.add(got["reason"])
        assert got["reason"] == want["reason"] and got["k_miss"] == want["k_miss"]
        for c in ("k_max", "k_tcdc"):
            assert (math.isnan(got[c]) and math.isnan(want[c])) or got[c] == want[c]
        for nbm in (80.0, math.nan, None):
            serve = ms.hrrr_extra_columns(got, nbm)
            fit = prm.rk_columns(want, nbm)
            for c in ms.P3DH_EXTRA:
                assert (math.isnan(serve[c]) and math.isnan(fit[c])) or serve[c] == fit[c]
    assert {"pit_violation", "window_violation", "message_absent", "no_cycle"} <= reasons
    assert None in reasons and (("no_land_cell" in reasons) == (point is not None and "KSFO" not in point))


def test_hrrr_constants_equal_the_fitted_rule():
    assert ms.HRRR_VARIABLES == prm.RK_VARIABLES and ms.HRRR_MARGIN_S == prm.RK_MARGIN_S
    assert ms.HRRR_VALID_END_LOCAL == prm.RK_VALID_END_LOCAL and ms.HRRR_TMP_RANGE_F == prm.RK_TMP_RANGE_F
    assert ms.P3DH_EXTRA == tuple(prm.RK_ARMS["P3d_H"]["extra_hgb"]) and ms.MG3_STATE_SCHEMA == prm.MG3_STATE_SCHEMA
    c = datetime.fromisoformat("2026-08-10T12:00:00+00:00")
    assert ms.hrrr_message_key(c, 3) == prm.rk_message_key(c, 3)


# ----------------------------------------------------------------------------- build -> serve, one builder, one reader

def test_a_binding_built_by_the_release_builder_serves_through_mg3_serve(tmp_path, monkeypatch):
    from tests.calibration.test_mg3_freeze import RN1_MARKETS, _rn1_inputs

    land, corpus, root = _rn1_inputs(tmp_path, monkeypatch)
    s0712 = tmp_path / "state_0712.pkl"
    _write(s0712, _state("07-12", range(7, 13), seed=50,
                         point_rule={"rule": "rn1", "land_sha256": prm.MG3_RN1["land_sha256"]}))
    smh_dir = tmp_path / "state_smh"
    smh_dir.mkdir()
    smh = smh_dir / "p3d_h_state.pkl"
    smh_sha = _write(smh, _state(ms.SM_H_BLOCK, (13, 14, 15), centres=list(prm.SM_H_CENTRES),
                                 provenance={"note_sha256": prm.SM_H_BINDING_SHA256,
                                             "rule_sha256": prm.SM_H_RULE_SHA256,
                                             "clarification_sha256": prm.SM_H_CLARIFICATION_1_SHA256}))
    control = {"block": ms.SM_H_BLOCK, "pass": True, "state_sha256": smh_sha, "note_sha256": ms.SM_H_NOTE_SHA256,
               "checks": {"1_inputs": {"pass": True}}}
    (smh_dir / "control.json").write_text(json.dumps(control), encoding="utf-8")
    (smh_dir / "p3d_h_state.json").write_text(json.dumps({"block": ms.SM_H_BLOCK, "state_sha256": smh_sha,
                                                          "note_sha256": ms.SM_H_NOTE_SHA256}), encoding="utf-8")
    l6_state, l6_sha = _l6_state(tmp_path)
    part = {"coef": {str(h): [0.1, 0.6] for h in range(7, 13)}, "column": "l6_mean"}
    coefficients = tmp_path / "mg2_coefficients.json"
    coefficients.write_text(json.dumps({"l6_stack": part, "other": 1}), encoding="utf-8")
    season = tmp_path / "nowcasts_season_dev.parquet"
    season.write_bytes(b"synthetic season nowcasts")
    part_sha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    table = {"note_sha256": prm.MG3_RF1_NOTE_SHA256, "rule_sha256": prm.MG3_WEIGHTS_RULE_SHA256,
             "weights": {f"h{h:02d}": 0.4 + 0.05 * (h - 7) for h in range(7, 13)},
             "checks": {"1_control": {"pass": True}, "2_identity": {"pass": True}, "3_coverage": {"pass": True}},
             "inputs": {"l6_part": part_sha, "nowcasts": "3806687c" + "0" * 56, "season_nowcasts": _sha(season)}}
    weights = tmp_path / "blend_l6_H_weights_rf1.json"
    weights.write_text(json.dumps(table, sort_keys=True), encoding="utf-8")
    Path(str(weights) + ".sha256").write_text(f"{_sha(weights)}  {weights.name}\n", encoding="utf-8")
    # the real pins first: every constant both modules carry agrees before any is monkeypatched below.
    # (weights and partner shas are not carried by mg3_serve - it reads them only from the binding.)
    assert ms.SM_H_STATE_SHA256 == prm.SM_H_STATE_SHA256
    assert ms.SM_H_NOTE_SHA256 == prm.SM_H_BINDING_SHA256
    assert ms.BINDING_SCHEMA == prm.MG3_BINDING_SCHEMA and ms.MG3_STATE_SCHEMA == prm.MG3_STATE_SCHEMA
    assert ms.P3DH_ARM == prm.MG3_ARM and ms.SM_H_BLOCK == prm.SM_H_STATE_BLOCK
    assert mg3_arms.SM_H_HOURS == prm.SM_H_HOURS and mg3_arms.BLEND_HOURS == prm.RR_HOURS
    assert ms.P3DH_EXTRA == tuple(prm.RK_ARMS["P3d_H"]["extra_hgb"])
    assert prm.MG3_POINT_RULES[ms.BLOCK_0712] == "rn1" and prm.MG3_POINT_RULES["13-16"] == "nearest"
    for module, name, value in ((prm, "MG3_RF1_WEIGHTS_SHA256", _sha(weights)),
                                (prm, "MG3_L6_PARTNER_SHA256", l6_sha), (prm, "SM_H_STATE_SHA256", smh_sha),
                                (ms, "SM_H_STATE_SHA256", smh_sha),
                                (ms, "SM_H_CONTROL_SHA256", _sha(smh_dir / "control.json"))):
        monkeypatch.setattr(module, name, value)

    built = prm.mg3_release_binding(land=land, corpus_dir=corpus, root=root, markets=RN1_MARKETS,
                                    states={"07-12": s0712, prm.SM_H_STATE_BLOCK: smh}, weights=weights,
                                    partner={"state": l6_state, "coefficients": coefficients, "nowcasts": season})
    out = tmp_path / "release-binding.json"
    out.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    binding = json.loads(out.read_text(encoding="utf-8"))  # served exactly as written, nothing added
    assert binding["schema"] == ms.BINDING_SCHEMA == prm.MG3_BINDING_SCHEMA
    assert binding["l6_partner"] == {"state_sha256": l6_sha, "part_sha256": part_sha,
                                     "nowcasts_sha256": _sha(season)}  # the season nowcasts, as serve reads them

    serve = ms.load_serve(binding, state_0712_path=s0712, sm_h_dir=smh_dir, weights_path=weights,
                          l6_state_path=l6_state, l6_part=json.loads(coefficients.read_text("utf-8"))["l6_stack"])
    assert serve.weights == {h: table["weights"][f"h{h:02d}"] for h in range(7, 13)}
    assert [ms.serve_arm(binding, "atlanta", h) for h in (9, 14, 17)] == [
        mg3_arms.ARM_BLEND_0712, mg3_arms.ARM_SM_H, mg3_arms.ARM_MG2]
    assert ms.serve_arm(binding, "san-francisco", 14) == mg3_arms.ARM_MG2
    kw = dict(market="atlanta", target_date=date(2026, 8, 10), high_so_far=74.0, current_temp=73.0, nbm_mean=80.0,
              extra={"k_max": 81.0, "k_gap": 1.0, "k_tcdc": 30.0})
    got = ms.arm_distribution(serve, mg3_arms.ARM_BLEND_0712, hour=9, mg1=(80.0, 2.0, 74.0), l6_nowcast=82.0, **kw)
    assert got == ms.mix(ms.p3dh_distribution(serve.state_0712, 9, **kw),
                         ms.l6_distribution(serve.l6_coef, 9, v=80.0, s=2.0, floor=74.0, nowcast=82.0), table["weights"]["h09"])
    assert ms.arm_distribution(serve, mg3_arms.ARM_SM_H, hour=14, **kw) == ms.p3dh_distribution(
        serve.sm_h_state, 14, **kw)
