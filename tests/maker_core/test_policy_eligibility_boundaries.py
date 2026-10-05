"""Killing assertions for the resting-leg eligibility checks in ``decide`` (test-suite review K, role 18).

Each test pins one boundary of ``eligible`` in ``maker_core.quoting.policy`` that the existing veto table
does not reach: the requote window's max-spread edge, the informed depth floor, the venue minimum order
size and the touch buffer on a resting leg.
"""
from dataclasses import replace
from decimal import Decimal as D

from maker_core.quoting.policy import QuoteLeg, decide


def test_resting_leg_exactly_at_max_spread_is_outside_requote_window(inputs):
    # max_spread is 3c and the mid is .50: a resting YES buy at .47 sits exactly 3c away and must not be kept.
    legs = (QuoteLeg("YES", D(".47"), D(30)), QuoteLeg("NO", D(".48"), D(30)))
    assert decide(replace(inputs, existing=legs)).reasons == ("OUTSIDE_REQUOTE_WINDOW",)


def test_displayed_depth_below_seventy_five_share_floor_is_insufficient(inputs):
    # 60 displayed shares is below the 75-share informed depth floor for every quote size.
    thin = replace(inputs.book, yes_bids=((D(".49"), D(60)),))
    assert decide(replace(inputs, book=thin)).reasons == ("INSUFFICIENT_DEPTH",)


def test_resting_leg_below_venue_min_order_size_is_refused(inputs):
    first = decide(inputs)
    assert first.action == "QUOTE"
    raised = replace(inputs, existing=first.legs,
                     market=replace(inputs.market, min_order_size=first.legs[0].size + 1))
    assert decide(raised).reasons == ("SIZE_BELOW_MINIMUM",)


def test_resting_leg_touching_raw_ask_breaks_touch_buffer(inputs):
    # A 5-share YES ask at .48 touches the resting .48 YES buy; the size-qualified mid stays .50.
    legs = (QuoteLeg("YES", D(".48"), D(30)), QuoteLeg("NO", D(".48"), D(30)))
    book = replace(inputs.book, yes_bids=((D(".47"), D(100)),),
                   yes_asks=((D(".48"), D(5)), (D(".53"), D(100))))
    assert decide(replace(inputs, existing=legs, book=book)).reasons == ("TOUCH_BUFFER",)
