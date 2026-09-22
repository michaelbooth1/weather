"""Synthetic contracts; no production evidence or network access."""
import numpy as np
import pandas as pd
import pytest

from tools.research.morning_guidance.candidate import candidates
from tools.research.morning_guidance.statistics import future_errors, summarize, planning
from tools.research.missing_information.methods import Band


def fixture():
    bands = [Band("lte", 70, 70), Band("eq", 71, 71), Band("eq", 72, 72), Band("gte", 73, 73)]
    f = {f"nbm_prob_tmax_p{p}": q for p, q in zip((10,25,50,75,90), (69,70,71,72,74))}
    f.update(nbm_prob_tmax_mean=71, nbm_prob_tmax_stddev=2, nbm_prob_tmax_physical_valid_flag=1,
             nbm_prob_tmax_impossible_flag=0, guidance_physical_floor=70.6, high_so_far=70.6)
    return bands, [0., .3, .4, .3], f


def test_mass_floor_and_exact_fixed_pool():
    bands, p, f = fixture()
    c1, c2, status = candidates(bands, p, f)
    assert status == "eligible"
    assert c1[0] == c2[0] == 0
    assert c1.sum() == pytest.approx(1)
    assert c2.sum() == pytest.approx(1)
    np.testing.assert_allclose(c2, .5*np.array(p)+.5*c1)


@pytest.mark.parametrize("key,value", [("nbm_prob_tmax_p10", None), ("nbm_prob_tmax_stddev", 0),
    ("nbm_prob_tmax_p25", 90), ("nbm_prob_tmax_physical_valid_flag", 0),
    ("nbm_prob_tmax_impossible_flag", 1), ("nbm_prob_tmax_mean", float("nan"))])
def test_bad_guidance_keeps_every_served_value(key, value):
    bands, p, f = fixture()
    f[key] = value
    c1, c2, status = candidates(bands, p, f)
    assert status != "eligible"
    assert c1.tolist() == c2.tolist() == p


def test_missing_floor_falls_back_and_trusted_floor_wins():
    bands, p, f = fixture()
    f.pop("guidance_physical_floor")
    f.pop("high_so_far")
    assert candidates(bands, p, f)[2] == "missing_captured_floor"
    f["trusted_current_max"] = 73
    c1, c2, _ = candidates(bands, p, f)
    assert c1.tolist() == c2.tolist() == [0, 0, 0, 1]


def test_native_celsius_translation_is_equivariant():
    bands, p, f = fixture()
    a = candidates(bands, p, f)
    shifted = [Band(b.kind, b.low-50, b.high-50) for b in bands]
    for key in list(f):
        if key in {"guidance_physical_floor", "high_so_far", "nbm_prob_tmax_mean"} or key in {
            f"nbm_prob_tmax_p{p}" for p in (10,25,50,75,90)}:
            f[key] -= 50
    b = candidates(shifted, p, f)
    np.testing.assert_allclose(a[0], b[0])
    np.testing.assert_allclose(a[1], b[1])


def test_invalid_served_support_refuses_instead_of_normalizing():
    bands, _, f = fixture()
    with pytest.raises(ValueError):
        candidates(bands, [0, .2, .2, .2], f)


def test_cdf_duplicate_quantiles_keep_mass():
    bands, p, f = fixture()
    f["nbm_prob_tmax_p25"] = f["nbm_prob_tmax_p50"]
    c1, c2, _ = candidates(bands, p, f)
    assert (c1 >= 0).all() and (c2 >= 0).all()
    assert c1.sum() == pytest.approx(1)


def test_fixed_market_uncertainty_does_not_shrink_with_dates():
    cells = pd.DataFrame([{"date": d, "market": m, "delta": v}
                          for d in range(8) for m, v in [("a", -.1), ("b", .08), ("c", -.02)]])
    infinite = future_errors(cells, "delta", None)
    np.testing.assert_allclose(future_errors(cells, "delta", 1000), infinite, atol=1e-14)
    assert np.std(infinite) > .02
    assert planning(cells, "delta", "2026-09-21")["new_dates"] is None


def test_zero_delta_negative_control_and_nonbeneficial_planning():
    cells = pd.DataFrame([{"date": d, "market": m, "delta": 0.}
                          for d in range(3) for m in ("a", "b")])
    result = summarize(cells, "delta")
    assert result["estimate"] == 0 and result["ci95"] == [0., 0.]
    assert result["power"] is None and result["mde80"] is None
    assert planning(cells, "delta", "2026-09-21")["status"] == "NONBENEFICIAL_DEVELOPMENT_EFFECT"


def test_recorded_valid_without_floor_is_not_eligible():
    bands, p, f = fixture()
    # Mirrors the after-10:00 trap without using real data: source is marked
    # physically valid solely because no observed floor was available.
    f.pop("guidance_physical_floor")
    f.pop("high_so_far")
    c1, c2, reason = candidates(bands, p, f)
    assert reason == "missing_captured_floor"
    assert c1.tolist() == c2.tolist() == p


def test_day_means_and_ratio_are_not_snapshot_weighted():
    rows = pd.DataFrame([{"date": "d1", "market": "a", "loss": 0., "benchmark": .5}]*9 +
                        [{"date": "d2", "market": "b", "loss": 1., "benchmark": 1.}])
    cells = rows.groupby(["date", "market"])[["loss", "benchmark"]].mean().reset_index()
    assert summarize(cells, "loss")["estimate"] == .5
    assert summarize(cells, "loss", "benchmark")["estimate"] == pytest.approx(2/3)
