"""Item 342: the bound P3d_N centre lookups on leap years (P2 copy parity, P5 fail-closed pin).

Guards: roadmap item 342 (docs/roadmap/items/item-342-feb29-bound-centre-lookup-crash.md), parity checks P2 and P5,
routed by master on 2026-11-03 through the tests-only lane before the B look. The five bound sites build a
non-leap reference date ``date(2001, month, day)``:

* ``pooled_residual_model.nearest_centre`` and ``pooled_residual_model.state_features``;
* ``mg_serve_core.nearest_centre`` and ``mg_serve_core.state_features`` (copies of prm);
* ``mg2_p3d_n.nearest_centre`` (third copy, called by ``serve_distribution``).

P2 closes the 2026-only gap of ``test_mg_serve_core_parity.test_prm_scalars``: the three copies agree on every 2024
and 2028 date except Feb 29, for every bound centre set. P5 pins today's loud ``ValueError`` on Feb 29 (master's term:
before B, a Feb-29 reach fails closed). P5 is TO BE REPLACED BY P4 IN THE ITEM-342 FIX CHANGE, which lands after the
B look with the shared Feb 29 -> Feb 28 helper, the release rebind and the ``KNOWN_COPIES`` update.

Calendar arithmetic and a hand-built synthetic state only; no data is read.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.model import mg_serve_core as core

prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")
p3 = import_or_skip_on_capture_host("weather.calibration.mg2_p3d_n")

# Every bound centre set (item 342 section 4, C3's table).
CENTRE_SETS = {
    "VALIDATION": (prm.VALIDATION_CENTRE,),
    "AUG_SEP": prm.AUG_SEP_CENTRES,
    "OCT_DEC": prm.OCT_DEC_CENTRES,
    "JAN_JUL": prm.JAN_JUL_CENTRES,
    "P3": prm.ARMS["P3"]["centres"],
    "P3F": prm.EXTRA_ARMS["P3F"]["centres"],
    "FORWARD": prm.FORWARD_CENTRES,
    "GOLDEN": p3.GOLDEN_CENTRES,
}
LEAP_YEARS = (2024, 2028)
MARKET = "atlanta"
HOUR = 13


def _leap_year_dates_except_feb29():
    for year in LEAP_YEARS:
        day = date(year, 1, 1)
        while day.year == year:
            if (day.month, day.day) != (2, 29):
                yield day
            day += timedelta(days=1)


def _state(centres):
    """A minimal frozen-state dict for ``state_features``: one hour, distinct normal per centre, bias per season."""
    seasons = sorted({c[5:7] for c in centres})
    mean = {
        "bias": {(MARKET, f"s{m}"): 0.25 * (i + 1) for i, m in enumerate(seasons)},
        "bias_global": -100.0,
        "normal": {(MARKET, c): 50.0 + i for i, c in enumerate(centres)},
        "normal_by_market": {MARKET: -200.0},
        "normal_global": -300.0,
        "doy": True,
    }
    return {
        "hours": {HOUR: {"mean": mean}},
        "centres": tuple(centres),
        "season_of": {m: f"s{m}" for m in seasons},
        "conversion": {"enabled": False},
        "coords": {MARKET: (33.6, -84.4, 300.0)},
        "constants": {"levels": ["high_so_far", "current_temp"]},
    }


def _features(module, state, day, nbm_mean):
    return module.state_features(state, HOUR, market=MARKET, target_date=day, high_so_far=81.0,
                                 current_temp=79.0, nbm_mean=nbm_mean)


def _same_features(a, b):
    """Exact equality of (X row, mu0, g, F); floats bitwise."""
    import numpy as np

    return np.array_equal(a[0], b[0]) and a[1:] == b[1:]


# ----------------------------------------------------------------------------- P2: copy parity on leap years


def test_bound_centre_sets_are_what_the_item_lists():
    assert core.AUG_SEP_CENTRES == prm.AUG_SEP_CENTRES == p3.GOLDEN_CENTRES
    assert prm.ARMS["P3"]["centres"] == prm.OCT_DEC_CENTRES + prm.AUG_SEP_CENTRES
    assert set(prm.EXTRA_ARMS["P3F"]["centres"]) == set(
        prm.JAN_JUL_CENTRES + prm.AUG_SEP_CENTRES + prm.OCT_DEC_CENTRES)
    # No bound centre is a Feb 29, so the centre side of every lambda is total.
    assert not any(c[5:] == "02-29" for cs in CENTRE_SETS.values() for c in cs)


@pytest.mark.parametrize("name", sorted(CENTRE_SETS))
def test_nearest_centre_copies_agree_on_2024_and_2028_except_feb29(name):
    centres = CENTRE_SETS[name]
    n = 0
    for day in _leap_year_dates_except_feb29():
        want = prm.nearest_centre(day, centres)
        assert want in centres
        assert core.nearest_centre(day, centres) == want, (name, day)
        assert p3.nearest_centre(day, centres) == want, (name, day)
        iso = day.isoformat()
        assert prm.nearest_centre(iso, centres) == core.nearest_centre(iso, centres) == p3.nearest_centre(
            iso, centres) == want, (name, iso)
        n += 1
    assert n == 2 * 365


def test_nearest_centre_default_centres_agree_on_2024_and_2028_except_feb29():
    for day in _leap_year_dates_except_feb29():
        want = prm.nearest_centre(day)
        assert core.nearest_centre(day) == want == p3.nearest_centre(day, p3.GOLDEN_CENTRES), day


@pytest.mark.parametrize("name", sorted(CENTRE_SETS))
def test_state_features_copies_agree_on_2024_and_2028_except_feb29(name):
    centres = CENTRE_SETS[name]
    state = _state(centres)
    mean = state["hours"][HOUR]["mean"]
    for day in _leap_year_dates_except_feb29():
        centre = p3.nearest_centre(day, centres)  # the third copy names the centre the state lookup must pick
        # NaN anchor: mu0 is the (market, centre) normal, so it identifies the chosen centre.
        old, new = _features(prm, state, day, float("nan")), _features(core, state, day, float("nan"))
        assert _same_features(old, new), (name, day)
        assert old[1] == mean["normal"][(MARKET, centre)], (name, day, centre)
        # Finite anchor: mu0 = nbm + the bias of the chosen centre's season.
        old, new = _features(prm, state, day, 80.0), _features(core, state, day, 80.0)
        assert _same_features(old, new), (name, day)
        assert old[1] == 80.0 + mean["bias"][(MARKET, state["season_of"][centre[5:7]])], (name, day, centre)
        assert all(math.isfinite(v) for v in old[0].ravel())


# ----------------------------------------------------------------------------- P5: fail-closed pin (pre-fix)
# TO BE REPLACED BY P4 IN THE ITEM-342 FIX CHANGE: after the fix every site returns the Feb-28 centre on Feb 29.

FEB29 = (date(2024, 2, 29), date(2028, 2, 29))
NEIGHBOURS = (date(2028, 2, 28), date(2028, 3, 1))
OUT_OF_RANGE = "day is out of range for month"


@pytest.mark.parametrize("day", FEB29)
def test_p5_nearest_centre_raises_on_feb29_at_all_three_copies(day):
    """P5 (to be replaced by P4 in the item-342 fix change): prm :940, core :447, mg2_p3d_n :204."""
    for centres in CENTRE_SETS.values():
        for target in (day, day.isoformat()):
            with pytest.raises(ValueError, match=OUT_OF_RANGE):
                prm.nearest_centre(target, centres)
            with pytest.raises(ValueError, match=OUT_OF_RANGE):
                core.nearest_centre(target, centres)
            with pytest.raises(ValueError, match=OUT_OF_RANGE):
                p3.nearest_centre(target, centres)
    with pytest.raises(ValueError, match=OUT_OF_RANGE):
        prm.nearest_centre(day)
    with pytest.raises(ValueError, match=OUT_OF_RANGE):
        core.nearest_centre(day)


@pytest.mark.parametrize("day", FEB29)
def test_p5_state_features_raises_on_feb29_at_both_copies(day):
    """P5 (to be replaced by P4 in the item-342 fix change): prm :1496-1497, core :536-537."""
    for centres in CENTRE_SETS.values():
        state = _state(centres)
        for nbm in (80.0, float("nan")):
            with pytest.raises(ValueError, match=OUT_OF_RANGE):
                _features(prm, state, day, nbm)
            with pytest.raises(ValueError, match=OUT_OF_RANGE):
                _features(core, state, day, nbm)


@pytest.mark.parametrize("day", FEB29)
def test_p5_mg2_serve_distribution_reaches_the_crash_on_feb29(day):
    """P5 (to be replaced by P4 in the item-342 fix change): ``serve_distribution`` calls :204 and does not swallow it."""
    state = {"hours": {HOUR: {}}, "conversion": {"enabled": False}, "centres": p3.GOLDEN_CENTRES}
    with pytest.raises(ValueError, match=OUT_OF_RANGE):
        p3.serve_distribution(state, market=MARKET, target_date=day.isoformat(), hour=HOUR, nbm_mean=80.0,
                              high_so_far=81.0, current_temp=79.0)


def test_p5_feb29_neighbours_do_not_raise():
    """The other side of the P5 boundary: Feb 28 and Mar 1 of 2028 resolve at every site."""
    for centres in CENTRE_SETS.values():
        state = _state(centres)
        for day in NEIGHBOURS:
            want = prm.nearest_centre(day, centres)
            assert core.nearest_centre(day, centres) == p3.nearest_centre(day, centres) == want
            assert _same_features(_features(prm, state, day, 80.0), _features(core, state, day, 80.0))
