"""Read the named HKO Daily Extract endpoint, preserving initial-print uncertainty."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from zoneinfo import ZoneInfo

from weather.market.metar_reports import aware_utc
from weather.market.metar_settlement import DailySettlement


@dataclass(frozen=True)
class DailyExtractSnapshot:
    year: int
    month: int
    # Values are the named Absolute Daily Max / Min columns, not monthly climate data.
    days: dict[int, tuple[Decimal | None, Decimal | None]]

    @property
    def covered_through(self):
        return max(self.days, default=None)


def parse_daily_extract(raw: str, year: int, month: int) -> DailyExtractSnapshot:
    """The official dailyExtract_YYYYMM.xml endpoint serves JSON, despite its suffix.

    dayData columns are day, pressure, absolute max, mean, absolute min,
    dew point, relative humidity, cloud amount and rain. Monthly summaries
    are not observations. Year/month come from the exact allowlisted URL.
    """
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("stn"), dict):
        raise ValueError("unknown HKO Daily Extract schema")
    groups = payload["stn"].get("data", [])
    if not isinstance(groups, list) or len(groups) > 1:
        raise ValueError("unknown HKO Daily Extract schema")
    days = {}
    for group in groups:
        if group.get("month") != month or not isinstance(group.get("dayData"), list):
            raise ValueError("wrong HKO Daily Extract month/schema")
        for row in group["dayData"]:
            if not isinstance(row, list) or len(row) != 9:
                raise ValueError("malformed HKO Daily Extract row")
            if row[0] in {"Mean/Total", "Normal"}:
                continue
            try:
                day = date(year, month, int(row[0])).day
            except (TypeError, ValueError) as exc:
                raise ValueError("malformed HKO Daily Extract date") from exc
            if day in days:
                raise ValueError("duplicate HKO Daily Extract date")
            values = []
            for index in (2, 4):
                token = str(row[index]).strip()
                if token in {"", "-", "--", "***", "N/A"}:
                    values.append(None)
                    continue
                try:
                    value = Decimal(token)
                except InvalidOperation as exc:
                    raise ValueError("malformed HKO Daily Extract temperature") from exc
                if not value.is_finite() or value != value.quantize(Decimal("0.1")):
                    raise ValueError("invalid HKO Daily Extract precision")
                values.append(value)
            days[day] = tuple(values)
    return DailyExtractSnapshot(year, month, days)


class HKODailyExtractAdapter:
    def __init__(self, reader=None):
        self.reader = reader

    def evaluate(self, spec, local_date, reports=(), *, as_of, hko_payloads=None,
                 initial_publication_verified=False, **kwargs):
        cutoff = datetime.combine(local_date + timedelta(days=7), time(23, 59),
                                  ZoneInfo("America/New_York")).astimezone(timezone.utc)
        if hko_payloads is None and self.reader is not None:
            hko_payloads = self.reader(local_date)
        common = dict(cutoff=cutoff, source="hko_daily_extract")
        if not isinstance(hko_payloads, DailyExtractSnapshot) or (
            hko_payloads.year, hko_payloads.month
        ) != (local_date.year, local_date.month) or (
            hko_payloads.covered_through is None or local_date.day > hko_payloads.covered_through
        ):
            return DailySettlement(spec.slug, local_date, "source_unavailable", **common,
                                   notes=("Daily Extract does not yet cover the requested date",))
        high, low = hko_payloads.days.get(local_date.day, (None, None))
        if high is None or low is None:
            return DailySettlement(spec.slug, local_date,
                                   "lowest_bracket_fallback" if aware_utc(as_of) >= cutoff else "source_unavailable",
                                   **common)
        if low > high:
            raise ValueError("inverted HKO extrema")
        return DailySettlement(spec.slug, local_date,
                               "final" if initial_publication_verified else "initial_publication_unverified",
                               high, low, high, low, **common,
                               notes=() if initial_publication_verified else (
                                   "initial Daily Extract publication receipt required; revisions remain possible",))
