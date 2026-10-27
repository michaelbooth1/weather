"""MG-3's hour table (weather.model.mg3_arms) as rule MG3-DC-1 s2.1 states it after the SM-H binding.

Guards: MG3-DC-1 s2.1 (rule_mg3_paired_dc.md) and binding_sm_h_state.md - 13-15 serve the SM-H state except a
market in the binding's excluded_markets (SF), which keeps MG-2's arm; 07-12 serve MG-3's blend; 00-06, 16 and
17-23 serve MG-2's arm; a binding without the SM-H block, without excluded_markets, with a malformed list or with
hours other than 13-15 refuses at every hour; the module is pure (imports nothing from weather) so the serving
path may import it; its block name, hours and SF exclusion equal the research binding's.
"""
import ast
import importlib
from pathlib import Path

import pytest

from weather.model import mg3_arms
from weather.model.mg3_arms import ARM_BLEND_0712, ARM_MG2, ARM_SM_H, Mg3ArmError, mg3_hour_arm

MODULE = Path(mg3_arms.__file__)


def _binding(**block):
    smh = {"sha256": "b6bc242a" + "0" * 56, "point_rule": "nearest", "hours": [13, 14, 15], "replaces": "13-16",
           "excluded_markets": ["san-francisco"]}
    smh.update(block)
    return {"states": {"13-16": {"sha256": "PENDING"}, "SM-H 13-15": smh}}


def test_hour_table_matches_the_rule():
    b = _binding()
    expected = {**{h: ARM_MG2 for h in range(24)}, **{h: ARM_BLEND_0712 for h in range(7, 13)},
                **{h: ARM_SM_H for h in (13, 14, 15)}}
    assert {h: mg3_hour_arm(b, "atlanta", h) for h in range(24)} == expected


def test_excluded_market_keeps_mg2_at_13_15_only():
    b = _binding()
    assert [mg3_hour_arm(b, "san-francisco", h) for h in (13, 14, 15, 16)] == [ARM_MG2] * 4
    assert mg3_hour_arm(b, "san-francisco", 9) == ARM_BLEND_0712
    assert mg3_hour_arm(_binding(excluded_markets=[]), "san-francisco", 14) == ARM_SM_H


@pytest.mark.parametrize("binding, match", [
    ({}, "no 'SM-H 13-15' state block"),
    ({"states": {"13-16": {}}}, "no 'SM-H 13-15' state block"),
    (_binding(excluded_markets="san-francisco"), "list of market ids"),
    (_binding(excluded_markets=[None]), "list of market ids"),
    (_binding(hours=[13, 14, 15, 16]), "binds hours"),
])
def test_unreadable_binding_refuses_at_every_hour(binding, match):
    for hour in (0, 9, 14, 20):
        with pytest.raises(Mg3ArmError, match=match):
            mg3_hour_arm(binding, "atlanta", hour)


def test_missing_excluded_markets_refuses():
    b = _binding()
    del b["states"]["SM-H 13-15"]["excluded_markets"]
    for hour in (3, 14):
        with pytest.raises(Mg3ArmError, match="no excluded_markets"):
            mg3_hour_arm(b, "san-francisco", hour)


@pytest.mark.parametrize("hour", [-1, 24, 13.0, "13", True])
def test_bad_hour_or_market_refuses(hour):
    with pytest.raises(Mg3ArmError, match="hour"):
        mg3_hour_arm(_binding(), "atlanta", hour)
    with pytest.raises(Mg3ArmError, match="market"):
        mg3_hour_arm(_binding(), "", 13)


def test_module_is_pure():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "collections.abc"}


def test_constants_equal_the_research_binding():
    try:
        prm = importlib.import_module("weather.calibration.pooled_residual_model")
    except ImportError as exc:  # pragma: no cover - only on the capture host
        if "pooled_residual_model refuses" in str(exc):
            pytest.skip("research module refuses this host by design")
        raise
    assert mg3_arms.SM_H_STATE_BLOCK == prm.SM_H_STATE_BLOCK
    assert mg3_arms.SM_H_HOURS == tuple(prm.SM_H_HOURS)
    assert prm.SM_H_EXCLUDED_MARKETS == ("san-francisco",)
