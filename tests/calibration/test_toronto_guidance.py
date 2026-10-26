"""Fixture tests for the L14 Toronto guidance research module (native Celsius, rule L14 a3899507...).

Guards: weather.calibration.toronto_guidance contracts pre-registered in the lane rule.md - NBP F is
converted once to C (MG-1's 1 F spread floor carried as 5/9 C); MG-1 on bins matches loss_atlas.mg1_frame
(bins below the floor get 0, the floor bin takes the CDF from -inf); the point-in-time NBP pick is the
latest issue whose S3 LastModified is at or before the instant; Celsius bins parse or are refused, never
coerced; the displayed market price is the midpoint only when the spread is <= 0.10; B_N's OLS recovers a
known design; nothing dated after 2026-09-29 is accepted.
"""
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from weather.calibration import toronto_guidance as tg


def test_mg1_bins_floor_and_mass():
    bins = [("lte", -10 ** 6, 20), ("eq", 21, 21), ("eq", 22, 22), ("eq", 23, 23), ("gte", 24, 10 ** 6)]
    p = tg.mg1_bins(22.0, 0.1, 22, bins)  # sd below the floor -> 5/9 C
    assert p[0] == 0.0 and p[1] == 0.0
    s = tg.MG1_SD_FLOOR_C
    assert p[2] == pytest.approx(float(tg._ndtr(0.5 / s)))  # CDF from -inf on the floor bin
    q = tg.floor_mask(p, bins, 22)
    assert sum(q) == pytest.approx(1.0)
    assert tg.MG1_SD_FLOOR_C == pytest.approx(5 / 9)


def test_mg1_buckets_moves_mass_below_the_floor_onto_it():
    d = tg.mg1_buckets(20.0, 2.0, 21.4)
    assert min(d) == 21 and sum(d.values()) == pytest.approx(1.0)
    assert d[21] > 0.5


def test_nbp_at_picks_latest_issue_available_by_the_instant():
    t0 = datetime(2026, 8, 12, tzinfo=timezone.utc)
    table = {"2026-08-12": [
        (t0 - timedelta(hours=3), t0 - timedelta(hours=5), 25.0, 1.0, "19"),
        (t0 + timedelta(hours=2), t0 + timedelta(hours=1), 26.0, 1.0, "01"),
    ]}
    assert tg.nbp_at(table, "2026-08-12", t0)[2] == 25.0
    assert tg.nbp_at(table, "2026-08-12", t0 + timedelta(hours=2))[2] == 26.0
    assert tg.nbp_at(table, "2026-08-13", t0) is None


def test_celsius_bins_parse_and_others_are_refused():
    assert tg.bin_from_label("24 C or below", "lte", "24", "24", "C") == ("lte", -10 ** 6, 24)
    assert tg.bin_from_label("34 C or higher", "gte", "34", "34", "C") == ("gte", 34, 10 ** 6)
    assert tg.bin_from_label("27 C", "eq", "27", "27", "C") == ("eq", 27, 27)
    assert tg.bin_from_label("80-81 F", "eq", "80", "81", "F") is None
    assert tg.bin_from_label("27 C", "eq", "28", "28", "C") is None


def test_displayed_price_convention():
    assert tg._price("0.40", "0.44", "0.9") == (pytest.approx(0.42), pytest.approx(0.42))
    disp, mid = tg._price("0.01", "0.99", "0.03")
    assert disp == 0.03 and mid == pytest.approx(0.5)
    assert tg._price("", "", "") == (None, None)


def test_bn_ols_recovers_a_known_design():
    import numpy as np

    rng = np.random.default_rng(1)
    m = rng.normal(25, 3, 400)
    F = m + rng.normal(-3, 2, 400)
    mu0 = m + 1.0
    g = F - mu0
    y = mu0 + 0.2 + 0.1 * g + 0.6 * np.maximum(g, 0)
    fit = tg.BN().fit(m, F, y)
    assert fit.b == pytest.approx(float(np.mean(y - m)))
    pred = fit.predict(m, F)
    assert np.allclose(pred, y, atol=1e-6) or np.corrcoef(pred, y)[0, 1] > 0.999


def test_predictive_distribution_floor_and_mix():
    import numpy as np

    z = np.linspace(-2, 2, 41)
    clim = {k: 1 / 11 for k in range(15, 26)}
    d = tg.predictive_distribution(22.0, 1.0, 23.2, z, clim)
    assert sum(d.values()) == pytest.approx(1.0)
    assert all(v <= 0.02 / 11 + 1e-12 for k, v in d.items() if k < 23)


def test_dates_after_the_cutoff_are_refused():
    tg.guard_date(date(2026, 9, 29))
    with pytest.raises(tg.Refused):
        tg.guard_date(date(2026, 9, 30))


def test_summarise_interval_brackets_the_point():
    import numpy as np

    W = tg.date_weights(30, 7, draws=200)
    d = np.linspace(-0.02, 0.0, 30)
    s = tg.summarise(d, np.full(30, 0.1), W, (0.95, 0.975))
    assert s["ci950"][0] <= s["delta"] <= s["ci950"][1]
    assert s["ci975"][0] <= s["ci950"][0]
    assert s["dR"] == pytest.approx(s["delta"] / 0.1)
    assert math.isfinite(s["mde80"])
