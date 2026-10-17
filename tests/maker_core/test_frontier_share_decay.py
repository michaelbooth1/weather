"""Item 330 build 3 (b): the competitor-response (reward-share decay) model.

The RE-1 projection fixture is identity-free and owner-authorised, with sessions on 2026-09-23..25, so
every date is before the fit cutoff. The synthetic sessions come from a seeded ``random.Random``.

Guards: the reward-share decay model: RE-1 projection, the pinned central fit, ordered bounds, synthetic parameter
  recovery, determinism, and disclosure of edge-of-grid or underpowered fits.
"""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random

import pytest

from maker_core.frontier.share_decay import (
    BOUNDS, K_GRID, TAU_GRID_MINUTES, DecayModel, Sample, Session, fit, fit_session, re1_sessions,
)

FIXTURES = Path(__file__).parent / "fixtures"
T = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def sessions():
    projection = json.loads((FIXTURES / "re1_sessions.json").read_text(encoding="utf-8"))
    selections = json.loads((FIXTURES / "re1_price_parity.json").read_text(encoding="utf-8"))
    return {s.label: s for s in re1_sessions(projection, selections)}


@pytest.fixture(scope="module")
def model(sessions):
    return fit(list(sessions.values()))


def test_re1_sessions_with_minutes_are_projected(sessions):
    # Attempts 2, 3, 7 and 11 never rested a minute, so they have no samples.
    assert sorted(sessions, key=lambda s: int(s.split("-")[1])) == [
        "attempt-1", "attempt-4", "attempt-5", "attempt-6", "attempt-8", "attempt-9", "attempt-10", "attempt-12"]


def test_re1_share_halved_within_two_to_four_minutes_in_the_long_reported_sessions(sessions):
    """The RE-1 finding: NYC (1), Miami (5), Atlanta (6) and session 11 (attempt 12) halve in 2-4 minutes."""
    halving = {label: sessions[label].halving_minutes() for label in sessions}
    for label in ("attempt-1", "attempt-5", "attempt-6", "attempt-12"):
        assert 2.0 <= halving[label] <= 4.25, (label, halving[label])
    assert sessions["attempt-5"].share0() == pytest.approx(.954, abs=.001)   # Miami 95.4% at selection
    assert sessions["attempt-6"].share0() == pytest.approx(.631, abs=.001)   # Atlanta 63.1% at selection


def test_not_every_re1_session_halved_within_four_minutes(sessions):
    """The fixture does not support "every session". Sessions 8 and 9 halve only after about 12 and 14
    minutes, attempt 4 halves at once on two samples, and attempt 8 is censored by a fill before it halves."""
    halving = {label: sessions[label].halving_minutes() for label in sessions}
    assert 11.5 <= halving["attempt-9"] <= 12.5 and 13.5 <= halving["attempt-10"] <= 14.5
    assert halving["attempt-4"] < 0.2 and halving["attempt-8"] is None


def test_central_fit_summary_is_pinned(model):
    assert model.k == pytest.approx(5.011872)
    assert model.tau_minutes == 5.0
    # Full bound: the largest identified plateau k (attempt 1), in extra competing Q per unit of own Q.
    assert model.x_full == pytest.approx(11.659144)
    assert 1 / (1 + model.x_full) == pytest.approx(.079, abs=.001)  # share ceiling with no other competition
    fitted = [f for f in model.fits if f.k is not None]
    assert len(fitted) == 6 and all(f.samples >= 13 for f in fitted)
    assert all(f.rmse < .12 for f in fitted)  # absolute share RMSE
    # The raw largest observed ratio stays disclosed but is not the full bound (attempt 5 drifted off mid).
    assert max(f.x_max for f in model.fits if f.x_max is not None) == pytest.approx(59.6305, abs=1e-3)


def test_fits_with_tau_on_the_grid_edge_are_disclosed_and_excluded(model):
    by_label = {f.label: f for f in model.fits}
    assert by_label["attempt-9"].tau_at_bound and by_label["attempt-9"].tau_minutes == TAU_GRID_MINUTES[-1]
    assert [f.label for f in model.fits if f.tau_at_bound] == ["attempt-9"]
    assert by_label["attempt-10"].k == pytest.approx(1.995262)
    edge = synthetic("edge", 3.0, 600.0, 5.0, seed=4)
    assert fit_session(edge).tau_at_bound
    with pytest.raises(ValueError, match="no_session"):
        fit([edge])


def test_central_model_halves_a_typical_share_within_two_to_four_minutes(model):
    for share0 in (.5, .63, .95):  # a 0.3 opening share needs about 5.5 minutes
        assert 1.0 <= model.halving_minutes("central", share0) <= 4.0, share0
    assert model.halving_minutes("none", .5) is None
    assert model.halving_minutes("full", .5) == 0.0


@pytest.mark.parametrize("age", (0.0, 0.5, 2.0, 10.0, 90.0))
@pytest.mark.parametrize("own,competing", ((1.0, 0.0), (10.0, 5.0), (3.0, 40.0)))
def test_bounds_are_ordered(model, age, own, competing):
    none, central, full = (model.share(b, own, competing, age) for b in BOUNDS)
    assert none >= central >= full > 0
    assert none == own / (own + competing)


def test_unknown_bound_and_zero_own_are_handled(model):
    with pytest.raises(ValueError):
        model.share("median", 1.0, 1.0, 1.0)
    assert model.share("central", 0.0, 1.0, 1.0) == 0.0


def synthetic(label, k, tau, competing0, seed, minutes=30, noise=.01):
    rng = random.Random(seed)
    samples = []
    for step in range(1, minutes * 2 + 1):
        age = step / 2
        own = 10.0
        x = k * (1 - math.exp(-age / tau))
        competing = (competing0 + x * own) * (1 + rng.uniform(-noise, noise))
        samples.append(Sample(T + timedelta(minutes=age), competing, own))
    return Session(label, T, 10.0, competing0, tuple(samples))


@pytest.mark.parametrize("k,tau", ((4.0, 3.0), (1.0, 10.0), (12.0, 1.0)))
def test_synthetic_parameters_are_recovered(k, tau):
    result = fit_session(synthetic("s", k, tau, 5.0, seed=int(k * 10 + tau)))
    assert result.tau_minutes == tau
    assert result.k == pytest.approx(k, rel=.12)
    assert result.rmse < .01


def test_fit_is_deterministic_and_order_invariant():
    group = [synthetic("s%d" % i, k, t, 5.0, seed=i) for i, (k, t) in enumerate(((2, 2), (4, 3), (8, 5)))]
    one, two = fit(group), fit(list(reversed(group)))
    assert (one.k, one.tau_minutes, one.x_full) == (two.k, two.tau_minutes, two.x_full)
    assert one.k == pytest.approx(4.0, rel=.12) and one.tau_minutes == 3.0


def test_sessions_with_too_few_samples_are_reported_not_fitted():
    short = Session("short", T, 1.0, 1.0, (Sample(T + timedelta(minutes=1), 2.0, 1.0),))
    result = fit_session(short)
    assert result.k is None and result.x_max == 1.0
    with pytest.raises(ValueError, match="no_session"):
        fit([short])


def test_grids_are_fixed():
    assert K_GRID[0] == 0.0 and K_GRID[-1] == pytest.approx(100.0)
    assert TAU_GRID_MINUTES == tuple(sorted(TAU_GRID_MINUTES))
    assert DecayModel(1.0, 1.0, 2.0, ()).extra("central", 0.0) == 0.0
