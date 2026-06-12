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

    # --- Native-unit operation --------------------------------------------
    # Every market runs end-to-end in its own unit (display_unit): C markets in
    # Celsius, F markets in Fahrenheit. These helpers translate the pipeline's
    # Celsius-authored constants into the market's unit, so a single code path
    # serves both. For C markets they are the identity (Toronto byte-identical).

    @property
    def unit(self):
        return self.display_unit

    @property
    def is_fahrenheit(self):
        return self.display_unit == "F"

    @property
    def wu_units(self):
        """Weather.com units param: 'e' (English/F) or 'm' (metric/C)."""
        return "e" if self.is_fahrenheit else "m"

    @property
    def om_temperature_unit(self):
        return "fahrenheit" if self.is_fahrenheit else "celsius"

    @property
    def artifact_suffix(self):
        """Model-artifact filename suffix per market ('' for toronto for backward compat)."""
        return "" if self.id == "toronto" else f"_{self.id}"

    @property
    def key_bucket(self):
        """The critical threshold bucket for deep-dive analysis (e.g. 25C for Toronto, 80F for F-markets)."""
        return 25 if self.unit == "C" else 80


    def c_to_native(self, celsius):
        """Convert an absolute Celsius temperature/bucket to the market's unit."""
        if celsius is None:
            return None
        return celsius * 9.0 / 5.0 + 32.0 if self.is_fahrenheit else celsius

    def scale_delta(self, celsius_delta):
        """Convert a Celsius *difference* (margin/spread/drop) to the market's unit."""
        if celsius_delta is None:
            return None
        return celsius_delta * 9.0 / 5.0 if self.is_fahrenheit else celsius_delta


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
             "metar", "weather_forecast", "open_meteo", "global_ensemble"),
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
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=True,
)

REGISTRY = {spec.id: spec for spec in (TORONTO, NYC)}

ATLANTA = MarketSpec(
    id="atlanta",
    city_label="Atlanta",
    slug_prefix="highest-temperature-in-atlanta-on",
    timezone="America/New_York",
    display_unit="F",
    wu_history_id="KATL:9:US",
    icao="KATL",
    lat=33.62972,
    lon=-84.44223,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=False,
)

AUSTIN = MarketSpec(
    id="austin",
    city_label="Austin",
    slug_prefix="highest-temperature-in-austin-on",
    timezone="America/Chicago",
    display_unit="F",
    wu_history_id="KAUS:9:US",
    icao="KAUS",
    lat=30.1831,
    lon=-97.68063,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=False,
)

CHICAGO = MarketSpec(
    id="chicago",
    city_label="Chicago",
    slug_prefix="highest-temperature-in-chicago-on",
    timezone="America/Chicago",
    display_unit="F",
    wu_history_id="KORD:9:US",
    icao="KORD",
    lat=41.96017,
    lon=-87.93161,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=False,
)

DALLAS = MarketSpec(
    id="dallas",
    city_label="Dallas",
    slug_prefix="highest-temperature-in-dallas-on",
    timezone="America/Chicago",
    display_unit="F",
    wu_history_id="KDAL:9:US",
    icao="KDAL",
    lat=32.83836,
    lon=-96.83584,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=False,
)

DENVER = MarketSpec(
    id="denver",
    city_label="Denver",
    slug_prefix="highest-temperature-in-denver-on",
    timezone="America/Denver",
    display_unit="F",
    wu_history_id="KBKF:9:US",
    icao="KBKF",
    lat=39.713,
    lon=-104.758,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=False,
)

HOUSTON = MarketSpec(
    id="houston",
    city_label="Houston",
    slug_prefix="highest-temperature-in-houston-on",
    timezone="America/Chicago",
    display_unit="F",
    wu_history_id="KHOU:9:US",
    icao="KHOU",
    lat=29.64582,
    lon=-95.28214,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=True,
)

LOS_ANGELES = MarketSpec(
    id="los-angeles",
    city_label="Los Angeles",
    slug_prefix="highest-temperature-in-los-angeles-on",
    timezone="America/Los_Angeles",
    display_unit="F",
    wu_history_id="KLAX:9:US",
    icao="KLAX",
    lat=33.93817,
    lon=-118.3866,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=True,
)

MIAMI = MarketSpec(
    id="miami",
    city_label="Miami",
    slug_prefix="highest-temperature-in-miami-on",
    timezone="America/New_York",
    display_unit="F",
    wu_history_id="KMIA:9:US",
    icao="KMIA",
    lat=25.78806,
    lon=-80.31692,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=True,
)

SAN_FRANCISCO = MarketSpec(
    id="san-francisco",
    city_label="San Francisco",
    slug_prefix="highest-temperature-in-san-francisco-on",
    timezone="America/Los_Angeles",
    display_unit="F",
    wu_history_id="KSFO:9:US",
    icao="KSFO",
    lat=37.61961,
    lon=-122.36561,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=True,
)

SEATTLE = MarketSpec(
    id="seattle",
    city_label="Seattle",
    slug_prefix="highest-temperature-in-seattle-on",
    timezone="America/Los_Angeles",
    display_unit="F",
    wu_history_id="KSEA:9:US",
    icao="KSEA",
    lat=47.44467,
    lon=-122.31442,
    sources=("wu_history", "wu_current", "metar", "weather_forecast", "open_meteo",
             "nws_hourly", "global_ensemble"),
    leading_obs="metar",
    coastal=True,
)

REGISTRY = {spec.id: spec for spec in (TORONTO, NYC, ATLANTA, AUSTIN, CHICAGO, DALLAS, DENVER, HOUSTON, LOS_ANGELES, MIAMI, SAN_FRANCISCO, SEATTLE)}
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
