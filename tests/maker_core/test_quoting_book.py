"""The one canonical decision-book composition and the OD23 own-size mid diagnostic (pure, fictional books).

Guards: engine ruling W1(a) (registration C11) as the single composition shared by replay v2 and the shadow
runner; OD23 (``decide()`` keeps own size in the qualified mid; the shadow gate counts where it moves the mid).
"""
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from maker_core.quoting.book import UnmergedBookLevels, compose_book, own_size_moves_mid
from maker_core.quoting.policy import Book, QuoteLeg

T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
LEGS = (QuoteLeg("YES", D(".48"), D(20)), QuoteLeg("NO", D(".48"), D(20)))


def lv(*rows):
    return tuple((D(p), D(s)) for p, s in rows)


def test_compose_creates_levels_on_all_four_arrays():
    book = Book(T0, lv((".49", 75)), lv((".51", 75)), lv((".49", 75)), lv((".51", 75), (".55", 10)))
    composed = compose_book(book, LEGS)
    assert composed.yes_bids == lv((".49", 75), (".48", 20))
    assert composed.no_asks == lv((".51", 75), (".52", 20), (".55", 10))
    assert composed.no_bids == lv((".49", 75), (".48", 20))
    assert composed.yes_asks == lv((".51", 75), (".52", 20))
    assert composed.as_of_utc == T0 and composed.post_only_available == book.post_only_available


def test_compose_sums_at_existing_levels_and_is_identity_without_legs():
    book = Book(T0, lv((".48", 75)), lv((".52", 5)), lv((".47", 1)), lv((".53", 1)))
    composed = compose_book(book, LEGS)
    assert composed.yes_bids == lv((".48", 95))
    assert composed.yes_asks == lv((".52", 25))
    assert composed.no_bids == lv((".48", 20), (".47", 1))
    assert composed.no_asks == lv((".52", 20), (".53", 1))
    assert compose_book(book, ()) == book


def test_compose_sums_two_legs_at_one_price_instead_of_last_wins():
    book = Book(T0, lv((".48", 5)), lv((".52", 75)), lv((".47", 75)), lv((".53", 75)))
    legs = (QuoteLeg("YES", D(".48"), D(20)), QuoteLeg("YES", D(".48"), D(30)))
    assert compose_book(book, legs).yes_bids == lv((".48", 55))


def test_compose_refuses_an_unmerged_public_side():
    book = Book(T0, lv((".48", 75), (".48", 1)), lv((".52", 5)), lv((".47", 1)), lv((".53", 1)))
    with pytest.raises(UnmergedBookLevels, match="unmerged_book_levels"):
        compose_book(book, LEGS)


# -- OD23 probe book (OD23-WORDING §2.3): public mid 0.475 at min_size 20 -------------------------------------
PROBE = Book(T0, lv((".45", 5), (".40", 100)), lv((".55", 100)), lv((".45", 100)), lv((".55", 100)))


@pytest.mark.parametrize("leg, moves", [
    (QuoteLeg("YES", D(".45"), D(30)), True),   # lifts a sub-minimum public level: mid 0.50
    (QuoteLeg("YES", D(".47"), D(30)), True),   # creates a qualified bid: mid 0.51
    (QuoteLeg("NO", D(".47"), D(30)), True),    # mirrors to a qualified YES ask at .53: mid 0.465
    (QuoteLeg("YES", D(".38"), D(30)), False),  # below the best qualified bid (.40): mid unchanged
    (QuoteLeg("YES", D(".47"), D(10)), False),  # below min_size: never qualifies
], ids=["lift-existing", "create-bid", "mirror-ask", "behind-best", "sub-minimum"])
def test_own_size_moves_mid_on_the_od23_probe(leg, moves):
    assert own_size_moves_mid(PROBE, compose_book(PROBE, (leg,)), D(20)) is moves


def test_a_refusal_on_one_book_only_is_a_difference():
    one_sided = Book(T0, lv((".45", 5)), lv((".55", 100)), lv((".45", 100)), lv((".55", 100)))
    assert own_size_moves_mid(one_sided, compose_book(one_sided, (QuoteLeg("YES", D(".45"), D(30)),)), D(20))
    assert not own_size_moves_mid(one_sided, one_sided, D(20))
