"""111l: tied end knots read at print resolution (T+1 Amendment 2).

The KAUS trace uses a tracked public NBP bulletin (tests/fixtures/nbm_target_fix);
everything else is synthetic. No production data.
"""
from datetime import date, datetime, timezone
from itertools import product
import math
import random

import pytest

from weather.market.maker_plugin.fair_value import integrate, model_id, percentile_cdf
from weather.market.maker_plugin.nbp import parse
from tests.market.test_maker_plugin_111k import KAUS, frozen_110b_cdf, raw_bulletin

PLAIN, ATOMS, TAILS = ("nbp-v2-piecewise-linear", "nbp-v2-piecewise-linear-atoms",
                       "nbp-v2-piecewise-linear-atoms-resolution-tails")


def test_kaus_01z_upper_tail_is_positive_one_band_out_and_zero_two_out():
    target = date(2026, 9, 17)
    fetched = datetime(2026, 9, 17, 2, tzinfo=timezone.utc)
    _, knots, _ = parse(raw_bulletin(KAUS.read_text(), "KAUS", target, fetched), "KAUS", target)
    assert knots == (97., 98., 99., 100., 100.) and model_id(knots) == TAILS
    bands = {"le96": (-math.inf, 96.5), "97": (96.5, 97.5), "98": (97.5, 98.5), "99": (98.5, 99.5),
             "100": (99.5, 100.5), "101": (100.5, 101.5), "ge102": (101.5, math.inf)}
    joint = integrate(bands, lambda x: percentile_cdf(knots, x))
    # The tail ends 2/3 degree above 100: F(100.5) = .975, F(101.5) = 1.
    assert joint["101"] + joint["ge102"] == pytest.approx(.025, abs=1e-12)
    assert joint["101"] == pytest.approx(.025, abs=1e-12) and joint["ge102"] == 0
    assert joint["100"] == pytest.approx(.35, abs=1e-12)


@pytest.mark.parametrize("ties", list(product((False, True), repeat=4)))
def test_every_tie_pattern(ties):
    knots = [70.]
    for tied in ties:
        knots.append(knots[-1] + (0 if tied else 2))
    knots = tuple(knots)
    if all(ties):
        with pytest.raises(ValueError, match="degenerate_percentile_knots"):
            percentile_cdf(knots, 70.5)
        return
    xs = [60 + i / 8 for i in range(240)]
    values = [percentile_cdf(knots, x) for x in xs]
    assert values == sorted(values) and values[0] == 0 and values[-1] == 1
    for k, q in zip(knots, (.10, .25, .50, .75, .90)):
        assert percentile_cdf(knots, k) >= q - 1e-12  # Right-continuous: the atom is included.
    expected_id = PLAIN if not any(ties) else TAILS if ties[0] or ties[3] else ATOMS
    assert model_id(knots) == expected_id
    if ties[0]:
        # Ten percent below p10 at .15 per degree: ends 2/3 degree out.
        assert percentile_cdf(knots, knots[0] - .5) == pytest.approx(.025)
        assert percentile_cdf(knots, knots[0] - 2 / 3 - 1e-9) == 0
    if ties[3]:
        assert percentile_cdf(knots, knots[4] + .5) == pytest.approx(.975)
        assert percentile_cdf(knots, knots[4] + 2 / 3 + 1e-9) == 1
    if not ties[0] and not ties[3]:
        # Untied ends keep the frozen extension exactly, wherever the ties are.
        for x in (knots[0] - 1.5, knots[0] - .5, knots[4] + .5, knots[4] + 1.5):
            assert percentile_cdf(knots, x) == frozen_110b_cdf(knots, x)


def test_strict_knots_are_byte_identical_to_frozen_110b():
    rng = random.Random(110)
    for _ in range(500):
        knots = tuple(sorted(rng.sample(range(40, 110), 5)))
        knots = tuple(float(k) for k in knots)
        xs = [-math.inf, math.inf] + [knots[0] - 6 + i / 4 for i in range(int((knots[4] - knots[0] + 12) * 4))]
        assert [percentile_cdf(knots, x) for x in xs] == [frozen_110b_cdf(knots, x) for x in xs]
        assert model_id(knots) == PLAIN


def test_untied_exact_zero_tail_is_frozen_behaviour():
    # Amendment 2 leaves the strict-knot extension's bounded support alone.
    knots = (90., 91., 93., 95., 96.)
    assert percentile_cdf(knots, 88.5) == 0 and percentile_cdf(knots, 97.5) == 1


def test_all_tied_knots_refuse_before_any_band_mass():
    bands = {"lo": (-math.inf, 70.5), "hi": (70.5, math.inf)}
    with pytest.raises(ValueError, match="degenerate_percentile_knots"):
        integrate(bands, lambda x: percentile_cdf((70.,) * 5, x))
