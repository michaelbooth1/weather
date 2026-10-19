"""HARNESS v3 arm protocol (outcome-free).

An arm is one Python file declaring::

    NAME = "my_arm"                  # unique within a prereg
    FAMILY = "nbm_guidance_band"     # the gate family its scores are charged to
    READS_NBM_GUIDANCE = True        # whether the MG-1 reservation applies to it
    INPUTS = ("v2_mean", "v2_stddev")  # snapshot/band columns it reads (blanked for its twin)
    def build(snaps, bands): ...     # -> DataFrame row_key, band_index, p (omit rows to fall back)

``build`` receives only the allow-listed input tables. ``load_arm`` records the file's sha256 so a
prereg can pin it. ``input_removed`` blanks the declared inputs to make the arm's input-removed
twin (control f): the twin must still build, and normally falls back to served where it cannot.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pandas as pd

LABELISH = frozenset({"winner", "settlement_high", "settlement_bucket", "settlement_source", "is_winner",
                      "p_market_yes", "best_bid", "best_ask", "market_mid", "promotion_countable"})
CANDIDATE_COLUMNS = ("row_key", "band_index", "p")
_REQUIRED = ("NAME", "FAMILY", "READS_NBM_GUIDANCE", "INPUTS", "build")


class ArmError(ValueError):
    pass


def load_arm(path, expected_sha256=None):
    path = Path(path)
    with open(path, "rb") as stream:
        code = stream.read()
    sha = hashlib.sha256(code).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ArmError(f"arm {path.name}: code sha256 {sha} != pinned {expected_sha256}")
    spec = importlib.util.spec_from_file_location(f"harness_v3_arm_{sha[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(code, str(path), "exec"), module.__dict__)
    missing = [k for k in _REQUIRED if not hasattr(module, k)]
    if missing:
        raise ArmError(f"arm {path.name} lacks {missing}")
    if not isinstance(module.READS_NBM_GUIDANCE, bool):
        raise ArmError("READS_NBM_GUIDANCE must be a bool")
    module.INPUTS = tuple(module.INPUTS)
    if LABELISH & set(module.INPUTS):
        raise ArmError(f"arm {module.NAME} declares label/market inputs {sorted(LABELISH & set(module.INPUTS))}")
    module.CODE_SHA256 = sha
    module.PATH = str(path)
    return module


def screen_names(snaps, bands):
    leaked = LABELISH & (set(snaps.columns) | set(bands.columns))
    if leaked:
        raise ArmError(f"arm inputs carry label/market columns {sorted(leaked)}")


def build(arm, snaps, bands):
    screen_names(snaps, bands)
    out = arm.build(snaps.copy(), bands.copy())
    if not isinstance(out, pd.DataFrame) or set(out.columns) != set(CANDIDATE_COLUMNS):
        raise ArmError(f"arm {arm.NAME} must return columns {CANDIDATE_COLUMNS}")
    return out[list(CANDIDATE_COLUMNS)]


def input_removed(arm, snaps, bands):
    """Copies of the inputs with every declared input column blanked (missing)."""
    s, b = snaps.copy(), bands.copy()
    for frame in (s, b):
        for col in arm.INPUTS:
            if col in frame.columns:
                frame[col] = pd.Series(pd.NA, index=frame.index, dtype="object") \
                    if frame[col].dtype == object or str(frame[col].dtype) == "string" \
                    else float("nan")
    return s, b
