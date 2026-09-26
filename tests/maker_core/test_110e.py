"""MAK-1 and MAK-4: uncalibrated symmetry and information-event lifetimes."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from maker_core.contracts import InfoEvent
from maker_core.quoting.policy import QuoteLeg, decide


@pytest.mark.parametrize("expiry", [False, True])
def test_information_event_requires_a_reference_time(inputs, expiry):
    with pytest.raises(ValueError, match="reference time"):
        InfoEvent("print", None, None, None, ("heads",), 1, None, "pull",
                  inputs.now if expiry else None)


@pytest.mark.parametrize("expiry", [False, True])
@pytest.mark.parametrize("age_seconds,active", [(-1, False), (0, True), (600, True), (601, True)])
def test_observed_only_event_lifetime(inputs, expiry, age_seconds, active):
    observed = inputs.now - timedelta(seconds=age_seconds)
    event = InfoEvent("print", None, observed, None, ("heads",), 1, None, "pull",
                      observed + timedelta(minutes=10) if expiry else None)
    if expiry and age_seconds > 600:
        active = False
    decision = decide(replace(inputs, events=(event,)))
    assert decision.action == ("NO_QUOTE" if active else "QUOTE")
    if active:
        assert decision.reasons == ("INFO_PULL",)
    # Caller removal releases an unexpired event; no hidden time limit applies.
    assert decide(replace(inputs, events=())).action == "QUOTE"


def test_observed_only_event_cancels_before_cooldown(inputs):
    resting = decide(inputs).legs
    event = InfoEvent("print", None, inputs.now - timedelta(hours=12), None,
                      ("heads",), 1, None, "pull")
    decision = decide(replace(inputs, events=(event,), existing=resting,
                              last_requote_at=inputs.now))
    assert decision.action == "CANCEL"
    assert decision.reasons == ("INFO_PULL",)


@pytest.mark.parametrize("hint,decided,reason", [("observe", {"heads": .5}, "DECIDED"),
                                               ("pull", None, "INFO_PULL")])
def test_observed_reference_does_not_override_future_detection(inputs, hint, decided, reason):
    event = InfoEvent("print", None, inputs.now - timedelta(seconds=1),
                      inputs.now + timedelta(seconds=1), ("heads",), 1, decided, hint)
    assert decide(replace(inputs, events=(event,))).action == "QUOTE"
    assert decide(replace(inputs, events=(replace(event, detected_at_utc=inputs.now),))).reasons == (reason,)
    assert decide(replace(inputs, events=(replace(event, detected_at_utc=None),))).reasons == (reason,)


def uncalibrated_inputs(inputs, p_yes, mid=D('.5')):
    bids, asks = ((mid-D('.04'), D(75)),), ((mid+D('.04'), D(75)),)
    no_bids, no_asks = ((1-mid-D('.04'), D(75)),), ((1-mid+D('.04'), D(75)),)
    return replace(inputs, fair_value=replace(inputs.fair_value, p_yes=p_yes, stdev=.05,
                                              joint=None, calibration_grade="none"),
                   book=replace(inputs.book, yes_bids=bids, yes_asks=asks, no_bids=no_bids, no_asks=no_asks),
                   terms=replace(inputs.terms, max_spread_cents=D(5)))


@pytest.mark.parametrize("mid", [D('.4'), D('.5'), D('.6')])
@pytest.mark.parametrize("shift", [D('-.03'), D(0), D('.03')])
def test_uncalibrated_quotes_keep_two_symmetric_legs(inputs, mid, shift):
    decision = decide(uncalibrated_inputs(inputs, float(mid+shift), mid))
    assert decision.action == "QUOTE", decision.reasons
    assert decision.centre == mid
    assert decision.legs == (QuoteLeg("YES", mid-D('.03'), D(30)), QuoteLeg("NO", 1-mid-D('.03'), D(30)))


@pytest.mark.parametrize("grade", ["shadow", "scored"])
def test_calibrated_grades_keep_their_asymmetry_rule(inputs, grade):
    frame = uncalibrated_inputs(inputs, .53)
    decision = decide(replace(frame, fair_value=replace(frame.fair_value, calibration_grade=grade)))
    assert decision.action == "QUOTE", decision.reasons
    assert tuple(leg.outcome for leg in decision.legs) == ("YES",)


@pytest.mark.parametrize("legs", [
    (QuoteLeg("YES", D('.47'), D(30)),),
    (QuoteLeg("NO", D('.47'), D(30)),),
    (QuoteLeg("YES", D('.47'), D(30)), QuoteLeg("NO", D('.48'), D(30))),
    (QuoteLeg("YES", D('.47'), D(20)), QuoteLeg("NO", D('.47'), D(30))),
])
def test_uncalibrated_view_cannot_hold_one_sided_or_skewed_quotes(inputs, legs):
    decision = decide(replace(uncalibrated_inputs(inputs, .5), existing=legs,
                              previous_fair_value=.5, last_requote_at=inputs.now))
    assert decision.action == "CANCEL"
    assert decision.reasons == ("UNCALIBRATED_ASYMMETRY",)


def test_uncalibrated_symmetric_quotes_hold_and_keep_safety_gates(inputs):
    frame = uncalibrated_inputs(inputs, .5)
    resting = (QuoteLeg("YES", D('.47'), D(30)), QuoteLeg("NO", D('.47'), D(30)))
    assert decide(replace(frame, existing=resting)).action == "HOLD"
    unsafe = replace(frame, portfolio=replace(frame.portfolio, cash=D(1)))
    assert decide(unsafe).reasons == ("CASH_OR_CAP",)
    assert decide(replace(frame, fair_value=replace(frame.fair_value, p_yes=.7))).reasons == ("FAIR_VALUE_DISAGREEMENT",)
