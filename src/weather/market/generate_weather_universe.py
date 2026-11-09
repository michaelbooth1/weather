"""Deterministically generate the inactive registry from the supplied public survey."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from weather.market.weather_universe import MONTHS, WeatherCitySpec
from weather.market.universe_rule_contract import assert_rule_contract, load_rule_pins
from weather.paths import config_path, repo_path

# Geographic IANA assignments, not inferred from the current machine's UTC offset.
# Winter/summer expectations for every assignment are tested on fixed UTC dates.
ZONE_CITIES = {
    "America/New_York": "nyc atlanta miami",
    "America/Chicago": "austin chicago dallas houston",
    "America/Denver": "denver", "America/Los_Angeles": "los-angeles san-francisco seattle",
    "America/Toronto": "toronto", "America/Mexico_City": "mexico-city",
    "America/Panama": "panama-city", "America/Sao_Paulo": "sao-paulo",
    "America/Argentina/Buenos_Aires": "buenos-aires", "Europe/London": "london",
    "Europe/Paris": "paris", "Europe/Amsterdam": "amsterdam", "Europe/Madrid": "madrid",
    "Europe/Berlin": "munich", "Europe/Rome": "milan", "Europe/Warsaw": "warsaw",
    "Europe/Helsinki": "helsinki", "Europe/Moscow": "moscow",
    "Asia/Riyadh": "jeddah", "Asia/Jerusalem": "tel-aviv", "Europe/Istanbul": "ankara istanbul",
    "Asia/Karachi": "karachi", "Asia/Kolkata": "lucknow", "Asia/Singapore": "singapore",
    "Asia/Kuala_Lumpur": "kuala-lumpur", "Asia/Manila": "manila", "Asia/Tokyo": "tokyo",
    "Asia/Seoul": "seoul busan", "Asia/Taipei": "taipei", "Asia/Hong_Kong": "hong-kong",
    "Asia/Shanghai": "beijing qingdao shanghai wuhan chengdu chongqing guangzhou shenzhen jinan zhengzhou",
    "Africa/Johannesburg": "cape-town", "Pacific/Auckland": "wellington",
}


def generate(inputs: Path) -> dict:
    names = ("city_icao.json", "stations.json", "rules_by_city_family.json")
    source = {name: json.loads((inputs / name).read_text(encoding="utf-8-sig")) for name in names}
    stations = {row["id"]: row for row in source["stations.json"]}
    zones = {city: zone for zone, cities in ZONE_CITIES.items() for city in cities.split()}
    rules = {}
    pins = load_rule_pins()
    for row in source["rules_by_city_family.json"]:
        if row["family"] in {"highest", "lowest"} and row["city"]:
            if row["family"] in rules.get(row["city"], {}):
                raise ValueError("duplicate city/family rule")
            rules.setdefault(row["city"], {})[row["family"]] = row
    if {city: sorted(families) for city, families in rules.items()} != {
        city: sorted(families) for city, families in pins["cities"].items()
    }:
        raise ValueError("reviewed city/family coverage drift")
    rows = []
    for city, families in sorted(rules.items()):
        contracts = {family: assert_rule_contract(
            rule, source["city_icao.json"].get(city, "HKO" if city == "hong-kong" else None), pins
        ) for family, rule in families.items()}
        kind, unit, _ = next(iter(contracts.values()))
        if any((c[0], c[1]) != (kind, unit) for c in contracts.values()):
            raise ValueError("city families disagree on settlement kind/unit")
        rule = next(iter(families.values()))
        title = re.fullmatch(r"(?:Highest|Lowest) temperature in (.+) on .+", rule["title"])
        if title is None:
            raise ValueError(f"unexpected title: {rule['title']}")
        if kind == "hko_daily_extract":
            kind, station = "hko_daily_extract", {
                "id": "HKO", "site": "Hong Kong Observatory", "lat": 22.3022,
                "lon": 114.1742, "elev": 32,
            }
            url = "https://www.weather.gov.hk/en/cis/climat.htm"
        else:
            station = stations[source["city_icao.json"][city]]
            url = (rule["resolutionSource"] if kind == "wu_daily_history" else
                   "https://aviationweather.gov/api/data/metar?ids={station_id}&format=raw&date={end_utc}&hours=30")
        row = dict(slug=city, display_name=title[1], settlement_kind=kind,
                   station_id=station["id"], station_name=station["site"],
                   latitude=station["lat"], longitude=station["lon"], elevation_m=station["elev"],
                   timezone=zones[city], market_unit=unit,
                   families=sorted(families), slug_templates={
                       family: f"{family}-temperature-in-{city}-on-{{month}}-{{day}}-{{year}}"
                       for family in sorted(families)}, resolution_source_url_template=url)
        spec = WeatherCitySpec(**row)
        for family, sample in families.items():
            match = re.fullmatch(rf"{family}-temperature-in-{city}-on-([a-z]+)-(\d+)-(\d{{4}})", sample["sample_slug"])
            if match is None or match[1] not in MONTHS:
                raise ValueError(f"{city}/{family}: event-slug drift")
            sample_day = date(int(match[3]), MONTHS.index(match[1]) + 1, int(match[2]))
            if kind != "hko_daily_extract" and spec.resolution_source_url(sample_day) != sample["resolutionSource"]:
                raise ValueError(f"{city}/{family}: resolutionSource query-window drift")
        rows.append(row)
    if set(rules) != set(source["city_icao.json"]) | {"hong-kong"}:
        raise ValueError("city/rules coverage mismatch")
    return {"schema_version": "weather-universe-v1", "source_sha256": {
        name: hashlib.sha256((inputs / name).read_bytes()).hexdigest() for name in names
    }, "rule_pins_sha256": hashlib.sha256(config_path("weather_universe_rule_pins.json").read_bytes()).hexdigest(),
        "cities": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=repo_path("tests", "fixtures", "weather_expansion", "inputs"))
    parser.add_argument("--out", type=Path, default=config_path("weather_universe.json"))
    args = parser.parse_args(argv)
    args.out.write_text(json.dumps(generate(args.inputs), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
