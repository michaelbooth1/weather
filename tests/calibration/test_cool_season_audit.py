"""CS-1 (lane L3): cool-season transfer audit, history-only research module.

Guards: the CS-1 rule (``C:/t/l3/coolseason/rule_cs.md``, sha pinned in the module): the integer-bucket Brier,
the pre-declared transfer reading, sha-bound state loading and the offline allowlist entry.
"""
import importlib.util
import pickle
import sys
from pathlib import Path

import pytest

from weather.calibration import cool_season_audit as cs

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.cool_season_audit"


def test_brier_from_dist_matches_one_hot_sum():
    dist = {70: 0.2, 71: 0.5, 72: 0.3}
    expected = (0.2 ** 2) + (0.5 - 1) ** 2 + 0.3 ** 2
    assert cs.brier_from_dist(dist, 71) == pytest.approx(expected)
    assert cs.brier_from_dist(dist, 90) == pytest.approx(0.04 + 0.25 + 0.09 + 1.0)


def test_state_load_refuses_other_bytes(tmp_path):
    p = tmp_path / "s.pkl"
    p.write_bytes(pickle.dumps({"a": 1}))
    with pytest.raises(cs.CoolSeasonError):
        cs.load_state(p, "0" * 64)


def test_rule_pin_refuses_other_text(tmp_path):
    p = tmp_path / "rule.md"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(cs.CoolSeasonError):
        cs.check_rule(p)


def test_hook_and_ps1_admit_the_module_exactly():
    spec = importlib.util.spec_from_file_location("cs_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    assert MODULE + "_x" not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} coverage --rule r --out o'
    }}, constrained_capture_host=False) is not None
    text = (ROOT / "scripts" / "ops" / "workload_admission.ps1").read_text(encoding="utf-8")
    assert f'"{MODULE}",' in text
