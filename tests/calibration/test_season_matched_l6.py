"""SM-L6 (lane L3): season-matched L6 HGB, history-only research module.

Guards: the SM-L6 rule (``C:/t/l3/sml6/rule_sml6.md``, sha pinned in the module): master's pre-declared decision
rule, the final fit's refusal unless LOYO selected the arm, the unchanged HGB/features, and the allowlist entry.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.calibration import season_matched_l6 as sm
from weather.calibration import upstream_obs_screen as l6
from weather.model import mg_serve_core as core

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.season_matched_l6"


def test_decision_rule_is_upper_bound_below_zero():
    assert sm.decide({"ci95": [-0.02, -0.001]}) == sm.ARM_SEASON
    assert sm.decide({"ci95": [-0.02, 0.0]}) == sm.ARM_MG1
    assert sm.decide({"ci95": [-0.02, 0.003]}) == sm.ARM_MG1
    assert sm.decide(None) == sm.ARM_MG1


def test_rule_pin_refuses_other_text(tmp_path):
    p = tmp_path / "rule.md"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(sm.SeasonL6Error):
        sm.check_rule(p)


def test_final_refuses_without_a_winning_loyo(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "check_rule", lambda rule: None)
    res = tmp_path / "loyo.json"
    res.write_text(json.dumps({"rule_sha256": sm.RULE_SHA256, "decision": sm.ARM_MG1,
                               "season_matched_loyo": {"oct_dec": {"pooled": {"ci95": [-0.1, 0.01]}}}}))
    with pytest.raises(sm.SeasonL6Error):
        sm.final(research_root=tmp_path, loyo_result=res, rule="r", out_dir=tmp_path / "o", commit="c")
    res.write_text(json.dumps({"rule_sha256": sm.RULE_SHA256, "decision": sm.ARM_SEASON,
                               "season_matched_loyo": {"oct_dec": {"pooled": {"ci95": [-0.1, 0.01]}}}}))
    with pytest.raises(sm.SeasonL6Error):
        sm.final(research_root=tmp_path, loyo_result=res, rule="r", out_dir=tmp_path / "o", commit="c")
    assert not (tmp_path / "o").exists()


def test_fit_state_uses_the_frozen_model_spec_and_serves_through_core():
    rng = np.random.default_rng(0)
    n = 400
    frame = pd.DataFrame({c: rng.normal(size=n) for c in l6.OWN})
    frame["station_code"] = rng.integers(0, 3, n).astype(float)
    frame["y"] = frame.t * 0.5 + rng.normal(size=n)
    state = sm.fit_state(frame, {})
    assert state["schema"] == core.L6_STATE_SCHEMA and tuple(state["columns"]) == core.L6_OWN_COLUMNS
    params = state["model"].get_params()
    assert {k: params[k] for k in l6.HGB_PARAMS} == dict(l6.HGB_PARAMS)
    got = core.l6_own_nowcast(state, frame)
    assert np.allclose(got, frame.r + state["model"].predict(frame[list(l6.OWN)].to_numpy(float)))
    assert sm.TRAIN_MONTHS == (10, 11, 12)


def test_hook_and_ps1_admit_the_module_exactly():
    spec = importlib.util.spec_from_file_location("sm_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    assert MODULE + "_x" not in hook._OFFLINE_WEATHER_MODULES
    text = (ROOT / "scripts" / "ops" / "workload_admission.ps1").read_text(encoding="utf-8")
    assert f'"{MODULE}",' in text


def test_bucket_probs_reproduce_bucket_brier():
    from weather.calibration import rz_hrrr_spread as rz

    mu, sig, R = np.array([70.2, 55.0, 90.0]), np.array([1.0, 2.5, 3.0]), np.array([68.4, 56.0, 60.0])
    y = np.array([70.0, 56.0, 91.0])
    p, k = sm.bucket_probs(mu, sig, R)
    assert np.allclose(p.sum(1), 1.0)
    assert k[0, 0] == 68 and k[1, 0] == 56
    onehot = (k == y[:, None]).astype(float)
    assert np.allclose(((p - onehot) ** 2).sum(1), rz.bucket_brier(mu, sig, R, y), atol=1e-12)


def test_dev_emit_refuses_a_sidecar_that_does_not_bind_the_state(tmp_path):
    out = tmp_path / "out"
    (tmp_path / sm.SIDECAR).write_text(json.dumps({"state_sha256": "a" * 64}))
    with pytest.raises(sm.SeasonL6Error):
        sm.dev_emit(state_dir=tmp_path, state_sha="b" * 64, captured_dir=tmp_path, frozen_l6_state=tmp_path / "x",
                    mg2_coefficients=tmp_path / "c", layout=tmp_path, out_dir=out)
    assert sm.DEV_TO == "2026-09-29"
