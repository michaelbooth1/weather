"""Light checks for L3's successor batch C1 module (no data read)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from weather.calibration import successor_odc_low as m


def test_sunrise_new_york_equinox_is_about_1057z():
    sr = m.sunrise_utc("2024-03-20", 40.78, -73.97)
    assert pd.Timestamp("2024-03-20 10:50", tz="UTC") <= sr <= pd.Timestamp("2024-03-20 11:05", tz="UTC")


def test_sunrise_polar_night_is_nat():
    assert pd.isna(m.sunrise_utc("2024-12-21", 80.0, 0.0))


def test_daily_stats_white_noise():
    rng = np.random.default_rng(0)
    dates = np.repeat([f"d{i:04d}" for i in range(600)], 3)
    s = m.daily_stats(dates, rng.normal(0, 1, len(dates)))
    assert s["n_dates"] == 600
    assert abs(s["lag1"]) < 0.15
    assert 0.7 < s["block3_ratio"] < 1.3


def test_rule_pin_is_hex():
    assert len(m.RULE_SHA256) == 64 and int(m.RULE_SHA256, 16) >= 0
