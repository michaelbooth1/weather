"""Free HKO climate-data reader, with an explicit initial-publication limitation."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from weather.market.metar_reports import aware_utc
from weather.market.metar_settlement import DailySettlement


def hko_value(payload, day: date, family: str) -> Decimal | None:
    """Read HKO's CLMMAXT/CLMMINT JSON schema, not an airport METAR or provisional RHR."""
    expected = "Daily Maximum Temperature" if family == "highest" else "Daily Minimum Temperature"
    if family not in {"highest", "lowest"} or not any(
        expected in title and "Hong Kong Observatory" in title for title in payload.get("type", [])
    ):
        raise ValueError("wrong HKO series/station")
    fields = payload.get("fields", [])
    if len(fields) != 5 or not all(word in fields[i] for i, word in enumerate(
        ("Year", "Month", "Day", "Value", "Completeness")
    )):
        raise ValueError("unknown HKO schema")
    values = []
    for row in payload.get("data", []):
        if len(row) != 5:
            raise ValueError("malformed HKO row")
        try:
            row_day = date(*map(int, row[:3]))
        except (TypeError, ValueError) as exc:
            raise ValueError("malformed HKO date") from exc
        if row_day != day:
            continue
        if row[4] != "C":
            return None
        try:
            value = Decimal(row[3])
        except InvalidOperation as exc:
            raise ValueError("malformed HKO value") from exc
        if not value.is_finite() or value != value.quantize(Decimal("0.1")):
            raise ValueError("invalid HKO precision")
        values.append(value)
    if len(values) > 1:
        raise ValueError("duplicate HKO day")
    return values[0] if values else None


class HKODailyExtractAdapter:
    def __init__(self, reader=None):
        self.reader = reader

    def evaluate(self, spec, local_date, reports=(), *, as_of, hko_payloads=None,
                 initial_publication_verified=False, **kwargs):
        cutoff = datetime.combine(local_date + timedelta(days=7), time(23, 59),
                                  ZoneInfo("America/New_York")).astimezone(timezone.utc)
        if hko_payloads is None and self.reader is not None:
            hko_payloads = self.reader(local_date)
        if hko_payloads is None:
            return DailySettlement(spec.slug, local_date, "not_implemented", source="hko_daily_extract",
                                   notes=("inject public HKO reader or captured climate JSON",))
        high = hko_value(hko_payloads[0], local_date, "highest")
        low = hko_value(hko_payloads[1], local_date, "lowest")
        if high is None or low is None:
            return DailySettlement(spec.slug, local_date,
                                   "lowest_bracket_fallback" if aware_utc(as_of) >= cutoff else "missing",
                                   cutoff=cutoff, source="hko_daily_extract")
        if low > high:
            raise ValueError("inverted HKO extrema")
        return DailySettlement(spec.slug, local_date,
                               "final" if initial_publication_verified else "initial_publication_unverified",
                               high, low, high, low, cutoff=cutoff, source="hko_daily_extract",
                               notes=() if initial_publication_verified else (
                                   "public climate series can contain revisions; initial Daily Extract receipt required",))
