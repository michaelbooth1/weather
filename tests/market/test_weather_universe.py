"""Guards: inactive expansion coverage, reproducibility, native units and event/bin semantics."""

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.market import market_registry
from weather.market.generate_weather_universe import generate
from weather.market.weather_universe import load_weather_universe, parse_bin_label
from weather.paths import config_path, repo_path

FIXTURE = repo_path("tests", "fixtures", "weather_expansion")
UNIVERSE = load_weather_universe()
SAMPLES = json.loads((FIXTURE / "inputs" / "bins_sample.json").read_text(encoding="utf-8"))["by_city_family"]


def test_generator_and_family_coverage():
    result = generate(FIXTURE / "inputs")
    assert json.dumps(result, ensure_ascii=False, indent=2) + "\n" == config_path("weather_universe.json").read_text(encoding="utf-8")
    assert len(UNIVERSE) == 51
    assert sum(s.settlement_kind == "metar_routine" for s in UNIVERSE.values()) == 48
    assert sum("lowest" in s.families for s in UNIVERSE.values()) == 45
    for key in SAMPLES:
        family, city = key.split("|")
        assert family in UNIVERSE[city].families


def test_builtin_registry_stays_byte_identical():
    before = (FIXTURE / "legacy_market_registry.sha256").read_text().strip()
    source = Path(market_registry.__file__).read_text(encoding="utf-8").encode()
    assert hashlib.sha256(source).hexdigest() == before
    assert len(market_registry.BUILTIN_SPECS) == 12
    assert market_registry.spec_for_id("denver").icao == "KBKF"
    assert UNIVERSE["denver"].station_id == "KDEN"


# Independent known UTC offsets, Jan 15 / Jul 15, in minutes. All registry zones covered.
OFFSETS = {
    "America/New_York": (-300, -240), "America/Chicago": (-360, -300),
    "America/Denver": (-420, -360), "America/Los_Angeles": (-480, -420),
    "America/Toronto": (-300, -240), "America/Mexico_City": (-360, -360),
    "America/Panama": (-300, -300), "America/Sao_Paulo": (-180, -180),
    "America/Argentina/Buenos_Aires": (-180, -180), "Europe/London": (0, 60),
    "Europe/Paris": (60, 120), "Europe/Amsterdam": (60, 120), "Europe/Madrid": (60, 120),
    "Europe/Berlin": (60, 120), "Europe/Rome": (60, 120), "Europe/Warsaw": (60, 120),
    "Europe/Helsinki": (120, 180), "Europe/Moscow": (180, 180), "Asia/Riyadh": (180, 180),
    "Asia/Jerusalem": (120, 180), "Europe/Istanbul": (180, 180), "Asia/Karachi": (300, 300),
    "Asia/Kolkata": (330, 330), "Asia/Singapore": (480, 480), "Asia/Kuala_Lumpur": (480, 480),
    "Asia/Manila": (480, 480), "Asia/Tokyo": (540, 540), "Asia/Seoul": (540, 540),
    "Asia/Taipei": (480, 480), "Asia/Hong_Kong": (480, 480), "Asia/Shanghai": (480, 480),
    "Africa/Johannesburg": (120, 120), "Pacific/Auckland": (780, 720),
}


@pytest.mark.parametrize("city", sorted(UNIVERSE))
def test_timezone_fixed_dates_and_slug(city):
    spec = UNIVERSE[city]
    offsets = tuple(int(datetime(2026, month, 15, 12, tzinfo=timezone.utc).astimezone(
        ZoneInfo(spec.timezone)).utcoffset().total_seconds() / 60) for month in (1, 7))
    assert offsets == OFFSETS[spec.timezone]
    for family in spec.families:
        assert spec.event_slug(family, date(2027, 2, 3)) == f"{family}-temperature-in-{city}-on-february-3-2027"


@pytest.mark.parametrize("label", sorted({label for row in SAMPLES.values() for label in row["bins"]}))
def test_every_supplied_bin_label(label):
    interval = parse_bin_label(label)
    assert interval.unit in {"C", "F"}
    if interval.lower is not None:
        assert interval.contains(interval.lower)
    if interval.upper is not None:
        assert interval.contains(interval.upper)


def test_bin_boundaries_and_negative_ranges():
    assert parse_bin_label("60-61°F").contains(61)
    assert not parse_bin_label("60-61°F").contains(62)
    assert parse_bin_label("13°C or below").contains(-100)
    assert parse_bin_label("20°C or higher").contains(100)
    assert parse_bin_label("−5–−4°C").contains(-4)
    hko = parse_bin_label("14°C", continuous=True)
    assert hko.contains(Decimal("14.9"))
    assert not hko.contains(15)
    with pytest.raises(ValueError):
        parse_bin_label("60-61°F", "C")
    with pytest.raises(ValueError):
        parse_bin_label("What is 14°C?")


@pytest.mark.parametrize("changes", [
    {"market_unit": "F"}, {"station_id": "XYZ"}, {"timezone": "Mars/Olympus"},
    {"families": ("rain",)}, {"settlement_kind": "unknown"}, {"latitude": 91},
])
def test_invalid_specs_fail_closed(changes):
    with pytest.raises((ValueError, KeyError)):
        replace(UNIVERSE["toronto"], **changes)


def test_loader_rejects_duplicate_slugs(tmp_path):
    payload = generate(FIXTURE / "inputs")
    payload["cities"].append(payload["cities"][0])
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate city"):
        load_weather_universe(path)
