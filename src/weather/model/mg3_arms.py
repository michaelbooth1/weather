"""MG-3's arm per local hour and market, read from the MG-3 release binding (rule MG3-DC-1 s2.1).

Pure: no I/O and no research imports, so the serving path (``mg_serve_core``) and the research freeze can share
one hour table. The caller passes the parsed ``release-binding.json`` content.

MG3-DC-1 s2.1, after the served SM-H state replaced the 13-16 state at 13-15 (binding_sm_h_state.md):

| Local hour | Arm |
| --- | --- |
| 00-06, 16, 17-23 | MG-2's bound arm |
| 07-12 | MG-3's 07-12 blend |
| 13-15 | the SM-H state, except a market in the binding's ``excluded_markets`` (SF), which keeps MG-2's arm |
"""
from __future__ import annotations

from collections.abc import Mapping

ARM_MG2 = "MG-2"
ARM_BLEND_0712 = "MG-3 07-12 blend"
ARM_SM_H = "SM-H 13-15"
SM_H_STATE_BLOCK = "SM-H 13-15"
SM_H_HOURS = (13, 14, 15)
BLEND_HOURS = tuple(range(7, 13))


class Mg3ArmError(ValueError):
    """The binding cannot say which arm serves this hour."""


def _sm_h_block(binding: Mapping) -> tuple[tuple[int, ...], frozenset[str]]:
    states = binding.get("states") if isinstance(binding, Mapping) else None
    block = states.get(SM_H_STATE_BLOCK) if isinstance(states, Mapping) else None
    if not isinstance(block, Mapping):
        raise Mg3ArmError(f"the MG-3 binding has no {SM_H_STATE_BLOCK!r} state block")
    if "excluded_markets" not in block:
        raise Mg3ArmError(f"the {SM_H_STATE_BLOCK!r} block has no excluded_markets; refusing to serve 13-15")
    excluded = block["excluded_markets"]
    if isinstance(excluded, str) or not all(isinstance(m, str) and m for m in excluded):
        raise Mg3ArmError(f"excluded_markets must be a list of market ids, got {excluded!r}")
    hours = tuple(int(h) for h in block.get("hours", ()))
    if hours != SM_H_HOURS:
        raise Mg3ArmError(f"the {SM_H_STATE_BLOCK!r} block binds hours {list(hours)}, not {list(SM_H_HOURS)}")
    return hours, frozenset(excluded)


def mg3_hour_arm(binding: Mapping, market: str, hour: int) -> str:
    """The arm MG-3 serves for ``market`` at local ``hour`` (MG3-DC-1 s2.1). Refuses an unreadable SM-H block."""
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise Mg3ArmError(f"local hour must be an int 0-23, got {hour!r}")
    if not isinstance(market, str) or not market:
        raise Mg3ArmError(f"market must be a non-empty market id, got {market!r}")
    hours, excluded = _sm_h_block(binding)
    if hour in hours:
        return ARM_MG2 if market in excluded else ARM_SM_H
    if hour in BLEND_HOURS:
        return ARM_BLEND_0712
    return ARM_MG2
