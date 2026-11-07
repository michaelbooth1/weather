"""Inert built-in identity, bounded JSON validation and conservative clock anchors."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import time

from weather.paths import PACKAGE_ROOT

MIB = 1024 * 1024
F0_COMMIT = "f531395522d0b0a37495185b2750164008fe586a"


def retry_delay(value, failures, now=None):
    seconds = 0.0
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) -
                           (now or datetime.now(timezone.utc))).total_seconds()
            except (ValueError, TypeError, OverflowError):
                pass
    return max(min(300, 2 ** min(failures, 9)), seconds)


def strict_json(raw, *, max_bytes=4 * MIB, max_nodes=60000, max_depth=32):
    """Reject expansion/depth before constructing objects, then reject ambiguity."""
    if len(raw) > max_bytes:
        raise ValueError("JSON byte limit")
    depth = nodes = 0
    quoted = escaped = False
    for value in raw:
        c = chr(value) if isinstance(value, int) else value
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
            nodes += 1
        elif c in "[{":
            depth += 1
            nodes += 1
        elif c in "]}":
            depth -= 1
        elif c in ",:":
            nodes += 1
        if depth > max_depth or nodes > max_nodes:
            raise ValueError("JSON structure limit")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON number")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite JSON number")
        return result

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


@dataclass(frozen=True)
class PublicSpec:
    id: str
    slug_prefix: str
    timezone: str
    display_unit: str


def builtin_specs():
    """Read only literal built-ins from canonical source, never execute its loader.

    In particular this does not import market_registry or inspect the inherited
    WEATHER_MARKET_REGISTRY value. Source changes are included in the run pin.
    """
    raw = (PACKAGE_ROOT / "market" / "market_registry.py").read_bytes()
    if len(raw) > 256 * 1024:
        raise ValueError("built-in source size")
    tree = ast.parse(raw)
    values, names = {}, None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "MarketSpec":
            fields = {kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords
                      if kw.arg in {"id", "slug_prefix", "timezone", "display_unit"}}
            values[name] = PublicSpec(**fields)
        elif name == "BUILTIN_SPECS":
            names = [item.id for item in node.value.elts]
    if not names:
        raise ValueError("built-in source contract changed")
    return tuple(values[name] for name in names)


BUILTIN_SPECS = builtin_specs()


class ClockPlan:
    """Freeze UTC-to-monotonic mapping; a material wall step fails closed.

    A step never silently shortens or prolongs capture. It stops optional
    evidence with a clock_discontinuity gap; no system clock is changed.
    """
    def __init__(self, *, start=None, end=None, mono=time.monotonic,
                 wall=lambda: datetime.now(timezone.utc).timestamp(), tolerance=2):
        self.mono, self.wall, self.tolerance = mono, wall, tolerance
        self.anchor_mono, self.anchor_wall = mono(), wall()
        self.start_at = self.anchor_mono + start.timestamp() - self.anchor_wall if start else self.anchor_mono
        self.end_at = self.anchor_mono + max(0, end.timestamp() - self.anchor_wall) if end else None

    def check_clock(self):
        delta = self.wall() - (self.anchor_wall + self.mono() - self.anchor_mono)
        return delta if abs(delta) > self.tolerance else None

    def anchors(self):
        return {"utc_epoch": self.anchor_wall, "monotonic": self.anchor_mono,
                "start_monotonic": self.start_at, "end_monotonic": self.end_at,
                "step_tolerance_seconds": self.tolerance, "step_policy": "stop_with_gap",
                "monotonic_resolution_seconds": time.get_clock_info("monotonic").resolution}
