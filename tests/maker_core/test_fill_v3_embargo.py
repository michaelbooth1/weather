"""The fill model v3 date embargo (item 330 build 1): window edges, purposes and input forms."""
from datetime import date, datetime, timedelta, timezone

import pytest

from maker_core.replay import fill_v3_embargo as E


@pytest.mark.parametrize("day", E.window_days(E.RESERVED_FIRST, E.RESERVED_LAST))
@pytest.mark.parametrize("purpose", E.PURPOSES)
def test_every_reserved_day_is_refused_for_every_purpose(day, purpose):
    with pytest.raises(E.EmbargoRefused) as caught:
        E.check(day, purpose)
    assert caught.value.code == "v3_reserved_window_refused"


def test_window_edges():
    assert E.check(date(2026, 9, 29), "descriptive") == date(2026, 9, 29)
    assert E.check(date(2026, 10, 16), "descriptive") == date(2026, 10, 16)
    assert E.reason(date(2026, 10, 16), "scored") == "v3_scored_embargo_refused"
    assert E.reason(date(2026, 11, 13), "scored") == "v3_scored_embargo_refused"
    assert E.reason(date(2026, 11, 14), "scored") == "v3_scored_requires_signed_registration"
    assert E.reason(date(2026, 9, 29), "scored") == "v3_scored_requires_signed_registration"
    assert E.SIGNED_REGISTRATION_SHA256 is None


def test_instants_are_read_as_utc_days():
    assert E.reason(datetime(2026, 9, 29, 23, 59, tzinfo=timezone.utc), "descriptive") is None
    late = datetime(2026, 9, 29, 20, 0, tzinfo=timezone(timedelta(hours=-5)))  # 2026-09-30 01:00 UTC
    assert E.reason(late, "descriptive") == "v3_reserved_window_refused"
    assert E.reason("2026-09-29T20:00:00-05:00", "descriptive") == "v3_reserved_window_refused"
    assert E.reason("2026-10-16T00:00:00Z", "descriptive") is None


@pytest.mark.parametrize("value,code", [
    (datetime(2026, 9, 1), "v3_embargo_naive_instant"),
    ("2026-09-01T00:00:00", "v3_embargo_naive_instant"),
    ("20260901", "v3_embargo_day_required"),
    (20260901, "v3_embargo_day_required"),
    (None, "v3_embargo_day_required"),
])
def test_malformed_values_refuse(value, code):
    with pytest.raises(E.EmbargoRefused) as caught:
        E.check(value, "descriptive")
    assert caught.value.code == code


def test_unknown_purpose_refuses():
    with pytest.raises(E.EmbargoRefused, match="v3_embargo_unknown_purpose"):
        E.check(date(2020, 1, 1), "exploratory")
    with pytest.raises(E.EmbargoRefused):
        E.check_all([date(2020, 1, 1), date(2026, 10, 1)], "descriptive")
