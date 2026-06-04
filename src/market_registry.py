"""Declarative registry of weather markets.

Adding a standard market is a config entry here -- no engine changes. Each
``MarketSpec`` carries everything city-specific: the Polymarket slug prefix, the
station + geo + timezone the data sources need, the display/settlement unit, the
source adapters to fetch, and climate context.

The model and pipeline run in a canonical internal unit (Celsius) for *every*
market -- WU is fetched in metric for all stations -- so a model trained on one
city's Celsius data applies to another unchanged. ``display_unit`` only affects
how the Polymarket bands are parsed and shown (Toronto trades in C, NYC in F).
"""
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketSpec:
    id: str                       # "toronto", "nyc"
    city_label: str               # "Toronto", "NYC"
    slug_prefix: str              # Polymarket event-slug prefix
    timezone: str                 # IANA tz name
    display_unit: str             # "C" or "F" -- the market's band/settlement unit
    wu_history_id: str            # Weather.com history location id
    icao: str                     # METAR / WU-current station
    lat: float
    lon: float
    sources: tuple                # ordered source-adapter ids fetched live
    leading_obs: str              # source whose obs lead the WU settlement print
    coastal: bool = False

    @property
    def tz(self):
        return ZoneInfo(self.timezone)

    @property
    def data_root(self):
        """Per-market local data root (climatology summary, last-good cache)."""
        return Path("data") / "wunderground" / self.icao.lower()


TORONTO = MarketSpec(
    id="toronto",
    city_label="Toronto",
    slug_prefix="highest-temperature-in-toronto-on",
    timezone="America/Toronto",
    display_unit="C",
    wu_history_id="CYYZ:9:CA",
    icao="CYYZ",
    lat=43.6767,
    lon=-79.6306,
    sources=("wu_history", "wu_current", "eccc_citypage", "eccc_swob",
             "metar", "weather_forecast", "open_meteo"),
    leading_obs="eccc_swob",
    coastal=False,
)

NYC = MarketSpec(
    id="nyc",
    city_label="NYC",
    slug_prefix="highest-temperature-in-nyc-on",
    timezone="America/New_York",
    display_unit="F",
    wu_history_id="KLGA:9:US",
    icao="KLGA",
    lat=40.7769,
    lon=-73.8740,
    # No ECCC/SWOB (Canadian); Open-Meteo + Weather.com cover NYC forecasts and
    # METAR/WU-current KLGA cover the leading-observation role SWOB plays up north.
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo"),
    leading_obs="metar",
    coastal=True,
)

REGISTRY = {spec.id: spec for spec in (TORONTO, NYC)}
DEFAULT_MARKET_ID = "toronto"


def spec_for_id(market_id):
    return REGISTRY.get(market_id or DEFAULT_MARKET_ID, REGISTRY[DEFAULT_MARKET_ID])


def spec_for_slug(slug):
    """The market a Polymarket slug belongs to, or None."""
    if not slug:
        return None
    low = str(slug).lower()
    for spec in REGISTRY.values():
        if spec.slug_prefix in low:
            return spec
    return None


def all_specs():
    return list(REGISTRY.values())
