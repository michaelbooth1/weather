"""The gap-to-market atlas is admitted by exact name and reports candidates only against the market.

Guards: master pre-authorisation 2026-10-24 (a lane may allowlist its own offline research module in
Get-WeatherWorkstationOfflineModule and the Codex hook mirror, with a pinning test); the atlas
discipline (no candidate-minus-candidate deltas; composite switches to arm A at 13:00 local).
"""
import ast
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.gap_to_market_atlas"
SOURCE = ROOT / "src/weather/calibration/gap_to_market_atlas.py"


def _hook():
    spec = importlib.util.spec_from_file_location("gtm_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_admitted_once_in_both_mirrors_and_nothing_wider():
    # Mirror equality with Get-WeatherWorkstationOfflineModule is proved by executing it in
    # tests/operations/test_loss_atlas_admission.py; here the hook mirror pins this module.
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration.gap_to_market"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} --layout x --arm-a y --dev4 z --out-dir w'
    }}, constrained_capture_host=False) is not None


def test_constants_and_no_cross_candidate_delta():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name)}
    assert ast.literal_eval(consts["COMPOSITE_SWITCH_HOUR"]) == 13
    blocks = [b[0] for b in ast.literal_eval(ast.unparse(consts["BLOCKS"]).split(" + ")[0])]
    assert blocks == ["06-09", "10-12", "07-12", "12-16", "13-16", "00-16"]
    text = SOURCE.read_text(encoding="utf-8")
    # The only ratio is candidate Brier over market Brier; no arm-vs-arm delta is ever formed.
    assert "market_b" in text and "p_a - p_" not in text and "b_a - b_" not in text
