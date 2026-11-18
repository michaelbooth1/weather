"""Inactive expansion registry and pure event/bin helpers; never a MarketSpec override."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from weather.paths import config_path
from weather.units import parse_temperature_band

Family = Literal["highest", "lowest"]
SettlementKind = Literal["metar_routine", "hko_daily_extract", "wu_daily_history"]
US_CITIES = frozenset({"nyc", "atlanta", "austin", "chicago", "dallas", "denver",
                       "houston", "los-angeles", "miami", "san-francisco", "seattle"})
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december")


@dataclass(frozen=True)
class WeatherCitySpec:
    slug: str
    display_name: str
    settlement_kind: SettlementKind
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    elevation_m: float
    timezone: str
    market_unit: Literal["C", "F"]
    families: tuple[Family, ...]
    slug_templates: dict[str, str]
    resolution_source_url_template: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", self.slug):
            raise ValueError("invalid city slug")
        if self.settlement_kind not in {"metar_routine", "hko_daily_extract", "wu_daily_history"}:
            raise ValueError("invalid settlement kind")
        expected = "F" if self.slug in US_CITIES else "C"
        if self.market_unit != expected:
            raise ValueError(f"{self.slug}: rule requires {expected}")
        if self.settlement_kind == "hko_daily_extract":
            if self.slug != "hong-kong" or self.station_id != "HKO":
                raise ValueError("invalid HKO station")
        elif not re.fullmatch(r"[A-Z]{4}", self.station_id):
            raise ValueError("invalid station ICAO")
        ZoneInfo(self.timezone)
        if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise ValueError("invalid coordinates")
        if not self.display_name or not self.station_name or not (-500 <= self.elevation_m <= 9000):
            raise ValueError("invalid station metadata")
        if not self.families or len(set(self.families)) != len(self.families):
            raise ValueError("missing or duplicate families")
        if set(self.slug_templates) != set(self.families):
            raise ValueError("slug templates differ from families")
        for family in self.families:
            if family not in {"highest", "lowest"} or self.slug_templates[family] != (
                f"{family}-temperature-in-{self.slug}-on-{{month}}-{{day}}-{{year}}"
            ):
                raise ValueError("invalid family/slug template")
        if not self.resolution_source_url_template.startswith("https://"):
            raise ValueError("resolution source must be public HTTPS")

    def event_slug(self, family: Family, local_date: date) -> str:
        if family not in self.families:
            raise ValueError(f"{self.slug}: unsupported family {family}")
        return self.slug_templates[family].format(
            month=MONTHS[local_date.month - 1], day=local_date.day, year=local_date.year)

    def resolution_source_url(self, local_date: date) -> str:
        """Inferred from the samples: next local midnight + 3 h, in UTC, hours=30."""
        next_midnight = datetime.combine(local_date + timedelta(days=1), time(), ZoneInfo(self.timezone))
        end = (next_midnight + timedelta(hours=3)).astimezone(timezone.utc)
        return self.resolution_source_url_template.format(
            station_id=self.station_id, end_utc=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            local_date=local_date.isoformat(), year=local_date.year, month=local_date.month, day=local_date.day)


def load_weather_universe(path: str | Path | None = None) -> dict[str, WeatherCitySpec]:
    payload = json.loads(Path(path or config_path("weather_universe.json")).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "weather-universe-v1":
        raise ValueError("unknown weather universe schema")
    cities = {}
    for row in payload["cities"]:
        spec = WeatherCitySpec(**{**row, "families": tuple(row["families"])})
        if spec.slug in cities:
            raise ValueError(f"duplicate city slug: {spec.slug}")
        cities[spec.slug] = spec
    if not cities:
        raise ValueError("empty weather universe")
    return cities


@dataclass(frozen=True)
class BinInterval:
    """Interval of resolved market values, not of the unrounded Celsius input.

    None is an infinite endpoint. Whole-degree labels are closed intervals;
    HKO can request half-open degree intervals at its tenth-degree precision.
    """

    label: str
    unit: str
    lower: Decimal | None
    upper: Decimal | None
    lower_closed: bool = True
    upper_closed: bool = True

    def contains(self, value: Decimal | int) -> bool:
        return ((self.lower is None or value > self.lower or (self.lower_closed and value == self.lower))
                and (self.upper is None or value < self.upper or (self.upper_closed and value == self.upper)))


def parse_bin_label(label: str, unit: str | None = None, *, continuous: bool = False) -> BinInterval:
    """Parse every supplied temperature-bin form through the canonical label parser.

    With continuous=True, HKO's whole-degree bins mean [n,n+1), <=n means
    (-infinity,n+1), and >=n means [n,infinity), preserving its 0.1 C reading.
    """
    parsed = parse_temperature_band(label, expected_unit=unit)
    if parsed is None or parsed.unit not in {"C", "F"}:
        raise ValueError(f"invalid temperature bin: {label!r}")
    lower = None if parsed.kind == "lte" else Decimal(parsed.value)
    upper = None if parsed.kind == "gte" else Decimal(parsed.value_hi) + int(continuous)
    return BinInterval(label, parsed.unit, lower, upper, True, not continuous)
