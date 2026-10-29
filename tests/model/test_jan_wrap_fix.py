"""Item 341 January no-wrap fix: wrap-aware nearest centre plus refusal outside coverage.

Both serve copies (``mg_serve_core`` and ``mg2_p3d_n``) used a linear month-day distance, so a January date
snapped to the far 08-08 centre. They now measure on a 365-day circle and refuse any date outside their
coverage. Aug-Dec served outputs must stay byte-identical to the unchanged source
(``pooled_residual_model``), which still carries the old lookup. Synthetic inputs only.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.model import mg_serve_core as core

p3 = import_or_skip_on_capture_host("weather.calibration.mg2_p3d_n")
prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")

FIXTURE = "2027-01-05"
OCT_DEC_LADDER = tuple(f"2026-{m:02d}-{d:02d}" for m, d in (
    (10, 1), (10, 8), (10, 15), (10, 22), (10, 29), (11, 5), (11, 12), (11, 19), (11, 26), (12, 3), (12, 10),
    (12, 16)))
AUG_DEC_LADDER = core.AUG_SEP_CENTRES + OCT_DEC_LADDER
CENTRE_SETS = (core.AUG_SEP_CENTRES, OCT_DEC_LADDER, AUG_DEC_LADDER, ("2026-10-10", "2026-11-24"))


def _days(first, last):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _old_nearest(target_date, centres):
    """The pre-fix lookup, verbatim (linear month-day distance, no refusal)."""
    d = date.fromisoformat(str(target_date)[:10])
    ref = date(2001, d.month, d.day)
    return min(centres, key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10])) - ref).days))


def test_the_2027_01_05_fixture_is_refused_by_both_copies():
    assert _old_nearest(FIXTURE, core.AUG_SEP_CENTRES) == "2026-08-08"  # the bug: 215 days away
    with pytest.raises(core.ServeCoreError, match="outside the serve coverage"):
        core.nearest_centre(FIXTURE)
    with pytest.raises(p3.P3dNRefused, match="outside the training coverage"):
        p3.nearest_centre(FIXTURE, p3.GOLDEN_CENTRES)


def test_the_2027_01_05_fixture_wraps_to_the_december_centre_when_covered():
    centres = ("2026-08-08", "2026-12-24")
    assert _old_nearest(FIXTURE, centres) == "2026-08-08"
    assert core.nearest_centre(FIXTURE, centres, coverage=("08-01", "01-31")) == "2026-12-24"
    assert core.month_day_gap(date(2026, 12, 24), date(2027, 1, 5)) == 12
    assert core.nearest_centre("2026-12-30", ("2026-01-02", "2026-12-01"), coverage=("12-01", "01-31")) == "2026-01-02"


def test_the_2027_01_05_fixture_refuses_a_whole_serve_call():
    state = {"centres": core.AUG_SEP_CENTRES, "hours": {9: {"mean": {}}}}
    with pytest.raises(core.ServeCoreError, match="outside the serve coverage"):
        core.state_features(state, 9, market="nyc", target_date=date(2027, 1, 5), high_so_far=40.0,
                            current_temp=39.0, nbm_mean=45.0)


@pytest.mark.parametrize("md, covered", [("07-31", False), ("08-01", True), ("12-31", True), ("01-01", False)])
def test_core_coverage_boundaries(md, covered):
    if covered:
        assert core.nearest_centre(f"2026-{md}") in core.AUG_SEP_CENTRES
    else:
        with pytest.raises(core.ServeCoreError):
            core.nearest_centre(f"2026-{md}")


@pytest.mark.parametrize("md, covered", [("07-31", False), ("08-01", True), ("12-16", True), ("12-17", False)])
def test_p3d_n_coverage_boundaries_match_training_coverage(md, covered):
    assert p3.in_training_coverage(f"2026-{md}") is covered
    if covered:
        assert p3.nearest_centre(f"2026-{md}", p3.GOLDEN_CENTRES) in p3.GOLDEN_CENTRES
    else:
        with pytest.raises(p3.P3dNRefused):
            p3.nearest_centre(f"2026-{md}", p3.GOLDEN_CENTRES)


def test_every_aug_dec_centre_is_unchanged():
    for centres in CENTRE_SETS:
        for day in _days(date(2026, 8, 1), date(2026, 12, 31)):
            assert core.nearest_centre(day, centres) == _old_nearest(day, centres) == prm.nearest_centre(day, centres)
        for day in _days(date(2026, 8, 1), date(2026, 12, 16)):
            assert p3.nearest_centre(day, centres) == _old_nearest(day, centres)


def test_every_aug_dec_served_distribution_is_byte_identical():
    """Serve outputs on the synthetic golden state, every covered day, vs the unchanged prm copy (exact ==)."""
    from tests.model.test_mg_serve_core_state_parity import _golden_state

    state = _golden_state()
    hour = sorted(state["hours"])[0]
    n = 0
    for market in state["markets"][:2]:
        normal = state["hours"][hour]["mean"]["normal_by_market"].get(market, state["hours"][hour]["mean"]["normal_global"])
        case = {"market": market, "high_so_far": float(round(normal)) - 1.0, "current_temp": float(round(normal)) - 2.0,
                "nbm_mean": normal + 1.3}
        for day in _days(date(2026, 8, 1), date(2026, 12, 31)):
            old = prm.state_distribution(state, hour, target_date=day, **case)
            assert core.state_distribution(state, hour, target_date=day, **case) == old, day
            if day <= date(2026, 12, 16):
                assert p3.serve_distribution(state, hour=hour, target_date=day, **case) == old, day
            n += 1
    assert n == 2 * 153
