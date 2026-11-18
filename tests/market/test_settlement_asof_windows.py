from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from weather.market.metar_reports import parse_metar
from weather.market.metar_settlement import MetarSettlementAdapter, possible_bins
from weather.market.weather_universe import parse_bin_label


DAY = date(2025, 1, 8)
SPEC = SimpleNamespace(station_id="KZZZ", slug="fixture", timezone="America/New_York", market_unit="C")
ASOF = datetime(2025, 1, 8, 17, tzinfo=timezone.utc)
DAY_END = datetime(2025, 1, 9, 5, tzinfo=timezone.utc)
DEADLINE = datetime(2025, 1, 10, 4, 59, tzinfo=timezone.utc)


def evaluate(reports=(), *, as_of=ASOF, day=DAY, **kwargs):
    return MetarSettlementAdapter().evaluate(SPEC, day, reports, as_of=as_of, **kwargs)


def report(body, start, end, receipt=None):
    return parse_metar("METAR KZZZ " + body, start, end, receipt_time=receipt, station_ids=(SPEC.station_id,))


def test_unreadable_receiptless_report_cannot_change_an_earlier_status():
    past = report("081600Z 15/04", ASOF - timedelta(hours=4), ASOF + timedelta(hours=3))
    future = report("BADTIME 27/04", ASOF + timedelta(seconds=1), ASOF + timedelta(hours=2))
    assert evaluate([future]).status == "missing"
    result = evaluate([past, future])
    assert (result.status, result.maximum) == ("running", 15)
    assert "publication_cutoff_unverified_without_receipt_times" in result.notes
    starts_at_cut = report("BADTIME 27/04", ASOF, DAY_END + timedelta(hours=2))
    current = evaluate([starts_at_cut])
    assert current.status == "source_unavailable"
    assert "publication_cutoff_unverified_without_receipt_times" in current.notes
    assert evaluate([starts_at_cut], day=DAY + timedelta(days=1)).status == "missing"


def test_known_revision_receipt_governs_over_overlapping_query_window():
    late = report("081600Z 15/04", ASOF - timedelta(hours=4), ASOF + timedelta(hours=3), ASOF + timedelta(minutes=1))
    assert evaluate([late]).status == "missing"
    accepted = evaluate([late], as_of=ASOF + timedelta(minutes=1))
    assert accepted.maximum == 15
    assert "publication_cutoff_unverified_without_receipt_times" not in accepted.notes


@pytest.mark.parametrize(("read_at", "status", "unverified"), [
    (DAY_END - timedelta(seconds=1), "awaiting_wu_fallback", False),
    (DAY_END, "wu_fallback", True),
    (DEADLINE - timedelta(seconds=1), "wu_fallback", True),
    (DEADLINE, "wu_fallback", False),
    (DEADLINE + timedelta(seconds=1), "awaiting_wu_fallback", False),
    (None, "wu_fallback", True),
])
def test_positive_fallback_preserves_completed_day_and_reports_publication_limits(read_at, status, unverified):
    bounds = {"wu_values": (Decimal(12), Decimal(3)), "wu_read_at": read_at}
    result = evaluate(as_of=DEADLINE, **bounds)
    assert (result.status, result.source_read_at) == (status, read_at)
    assert ("wu_post_deadline_read_unverified" in result.notes) == unverified
    for family, winner in (("highest", 12), ("lowest", 3)):
        bins = [parse_bin_label(f"{n}°C", "C") for n in (3, 12, 15)]
        possible = [b.interval.label for b in possible_bins(result, family, bins) if b.possible]
        assert possible == ([f"{winner}°C"] if status == "wu_fallback" else [b.label for b in bins])
    assert evaluate(as_of=DEADLINE - timedelta(seconds=1), **bounds).status != "wu_fallback"


def test_wu_empty_still_requires_post_deadline_evidence():
    assert evaluate(as_of=DEADLINE, wu_empty=True, wu_read_at=DAY_END).status == "awaiting_wu_fallback"
    assert evaluate(as_of=DEADLINE, wu_empty=True, wu_read_at=DEADLINE).status == "lowest_bracket_fallback"
