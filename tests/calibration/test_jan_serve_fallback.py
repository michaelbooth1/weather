"""Item 341 January note (docs/research/item341-january-serving-2026-10-30.md): a January target date never raises
out of the MG-2 P3d_N emission; it is counted as outside the training coverage and the afternoon slot takes MG-1.

Also pins that no source module outside the two known files calls ``state_features`` / ``state_distribution``, so a
``ServeCoreError`` raised for a January date by ``mg_serve_core`` has no serve caller to crash today.
"""
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tests.calibration.test_mg2_p3d_n import _event_folder, _replay, _snap_frame, golden_state, p3  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
JAN_DAYS = (date(2026, 12, 31), date(2027, 1, 5), date(2027, 1, 31))


def _jan_snaps(tmp_path, days):
    tz = ZoneInfo("America/New_York")
    rows = []
    for day in days:
        at = datetime(day.year, day.month, day.day, 15, 30, tzinfo=tz)
        _replay(_event_folder(tmp_path, "atlanta", day), day, tz,
                [(at, [(datetime(day.year, day.month, day.day, 14, 52, tzinfo=tz), 41.0)])])
        rows.append((f"atlanta|r{day.isoformat()}", day, at, 15))
    return _snap_frame(rows, tz)


def test_january_rows_fall_back_to_mg1_without_raising(golden_state, tmp_path, monkeypatch):  # noqa: F811
    from weather.calibration import mg2_composite as mg2

    def never(*_a, **_k):
        raise AssertionError("nearest_centre must not be reached for a date outside the training coverage")

    monkeypatch.setattr(p3, "nearest_centre", never)
    snaps = _jan_snaps(tmp_path, JAN_DAYS)
    out, stats = p3.emit_rows(golden_state, snaps, tmp_path, JAN_DAYS[0], JAN_DAYS[-1], markets=["atlanta"])
    assert out == []
    assert stats["atlanta"]["outside_training_coverage"] == len(JAN_DAYS)
    assert stats["atlanta"]["coverage_fallback"] == list(snaps.row_key)
    snaps = snaps.assign(guidance_physical_floor=35.0, high_so_far=float("nan"), trusted_current_max=float("nan"))
    bands = pd.DataFrame([(rk, i, k, lo, hi) for rk in snaps.row_key
                          for i, (k, lo, hi) in enumerate([("lte", np.nan, 40.0), ("between", 41.0, 42.0),
                                                           ("gte", 43.0, np.nan)])],
                         columns=["row_key", "band_index", "kind", "low", "high"])
    base = pd.DataFrame([(rk, i, 1 / 3) for rk in snaps.row_key for i in range(3)], columns=["row_key", "band_index", "p"])
    _, source = mg2.compose(snaps, bands, base, mg2.distribution_band_frame({}, bands), base)
    assert set(source.values()) == {"mg1"}


def test_no_serve_caller_of_the_core_state_functions():
    pattern = re.compile(r"\bstate_(features|distribution)\(")
    callers = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "src").rglob("*.py")
                     if pattern.search(p.read_text(encoding="utf-8")))
    # mg_serve_core defines and uses them; pooled_residual_model is the research source. A new caller (MG-3 wiring)
    # must catch ServeCoreError and fall back to MG-1 before it is added here (item 341 January note, section 1).
    assert callers == ["src/weather/calibration/pooled_residual_model.py", "src/weather/model/mg_serve_core.py"]
