"""Weather feature adapter for the COUNTERFACTUAL toxicity table (item 330 build 2).

Guards: the weather toxicity feature adapter is point-in-time (nothing after the instant; market prices never enter
  information features), signs the scheduled print, and refuses embargoed dates and unidentified inputs.
"""
from datetime import datetime, timedelta, timezone

import pytest

from maker_core.contracts.evidence_embargo import EmbargoRefused
from maker_core.quoting.fill_cost import FillContext, levels
from weather.market.maker_plugin.toxicity_features import (
    FeatureAfterInstant, minutes_from_scheduled_print, weather_fill_context,
)

UTC = timezone.utc
AT = datetime(2026, 9, 12, 17, 54, 30, tzinfo=UTC)


def _prints(price_shift=0.0):
    return [
        {"at_utc": AT - timedelta(seconds=40), "band": "84-85", "size": 12, "price": .40 + price_shift},
        {"at_utc": AT - timedelta(seconds=20), "band": "86-87", "size": 7, "price": .30 + price_shift},
        *({"at_utc": AT - timedelta(milliseconds=100 * (i + 1)), "band": "82-83", "size": 20 + i,
           "price": .55 + price_shift} for i in range(5)),
        {"at_utc": AT - timedelta(minutes=5), "band": "88-89", "size": 300, "price": .10 + price_shift},
    ]


def _book(price_shift=0.0):
    return {"as_of_utc": AT - timedelta(seconds=2),
            "yes_bids": [(.54 + price_shift, 30), (.53 + price_shift, 50)],
            "yes_asks": [(.56 + price_shift, 20)]}


def _context(**overrides):
    values = dict(at_utc=AT, station="KATL", maker_side="YES", horizon_days=0,
                  close_utc=AT + timedelta(hours=8), band="82-83",
                  nbm_available_utc=[AT - timedelta(minutes=50), AT + timedelta(minutes=5)],
                  decided_probability=.3, decided_at_utc=AT - timedelta(minutes=2),
                  book=_book(), prints=_prints())
    values.update(overrides)
    return weather_fill_context(**values)


def test_adapter_builds_a_point_in_time_fill_context():
    payload = _context()
    ctx = FillContext.from_mapping(payload)
    assert payload["minutes_from_scheduled_print"] == pytest.approx(2.5)      # KATL routine minute 52
    assert payload["minutes_since_model_cycle"] == pytest.approx(50.0)         # later cycle ignored
    assert payload["burst_prints"] == 5 and payload["sweep_bands"] == 3       # 88-89 is outside 60 s
    assert payload["last_print_size"] == 20 and payload["depth_shares"] == 100
    assert payload["book_imbalance"] == pytest.approx(.6)
    assert levels(ctx)["flow"] == "sweep" and levels(ctx)["clock"] == "print_window"
    assert all(t <= ctx.at_utc for t in ctx.feature_times.values())


def test_market_prices_never_move_information_or_decided_features():
    base = _context()
    for shift in (-.2, .15, .4):
        assert _context(book=_book(shift), prints=_prints(shift)) == base


def test_scheduled_print_is_signed_and_nearest():
    assert minutes_from_scheduled_print("KLGA", datetime(2026, 9, 1, 12, 49, tzinfo=UTC)) == -2
    assert minutes_from_scheduled_print("CYYZ", datetime(2026, 9, 1, 12, 59, tzinfo=UTC)) == -1
    assert minutes_from_scheduled_print("CYYZ", datetime(2026, 9, 1, 13, 4, tzinfo=UTC)) == 4
    with pytest.raises(ValueError):
        minutes_from_scheduled_print("XXXX", AT)


@pytest.mark.parametrize("overrides", [
    {"decided_at_utc": AT + timedelta(seconds=1)},
    {"book": dict(_book(), as_of_utc=AT + timedelta(seconds=1))},
    {"prints": _prints() + [{"at_utc": AT + timedelta(milliseconds=1), "band": "82-83", "size": 1, "price": .5}]},
    # The triggering print itself, planted exactly at the instant, must not leak into its own context.
    {"prints": _prints() + [{"at_utc": AT, "band": "82-83", "size": 1, "price": .5}]},
])
def test_feature_after_instant_raises(overrides):
    with pytest.raises(FeatureAfterInstant):
        _context(**overrides)


def test_adapter_refuses_embargoed_dates():
    exam = datetime(2026, 10, 5, 17, 54, tzinfo=UTC)
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        weather_fill_context(at_utc=exam, station="KATL", maker_side="YES", horizon_days=0,
                             close_utc=exam + timedelta(hours=1), band="82-83")
    with pytest.raises(EmbargoRefused, match="EMBARGO_EXAM_WINDOW"):
        _context(prints=_prints() + [{"at_utc": datetime(2026, 10, 1, tzinfo=UTC), "band": "x", "size": 1}])
    later = datetime(2026, 10, 20, 17, 54, tzinfo=UTC)
    assert weather_fill_context(at_utc=later, station="KATL", maker_side="NO", horizon_days=1,
                                close_utc=later + timedelta(hours=1), band="82-83")["sweep_bands"] == 0


def test_close_on_the_next_utc_date_is_a_schedule_not_a_read():
    # A 09-29 context whose market closes on 09-30 UTC reads nothing from the exam window.
    evening = datetime(2026, 9, 29, 20, tzinfo=UTC)
    payload = weather_fill_context(at_utc=evening, station="KATL", maker_side="YES", horizon_days=0,
                                   close_utc=evening + timedelta(hours=8), band="82-83")
    assert payload["minutes_to_close"] == pytest.approx(480.0)


def test_adapter_refuses_unidentified_inputs():
    with pytest.raises(ValueError):
        _context(close_utc=AT - timedelta(seconds=1))
    with pytest.raises(ValueError):
        _context(decided_at_utc=None)
    with pytest.raises(ValueError):
        _context(at_utc=datetime(2026, 9, 12, 17, 54))
