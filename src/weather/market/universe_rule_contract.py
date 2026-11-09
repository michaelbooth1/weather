"""Reviewed rule variants and station/source assertions for registry generation."""

import hashlib
import json
import re
from urllib.parse import parse_qs, urlparse

from weather.paths import config_path


def normalized_rule_text(text):
    """Normalize survey encoding/whitespace and event-specific airport/date/URLs only."""
    try:
        text = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        pass
    airport = re.search(r"temperature reported at (.+? \([A-Z]{4}\)) on ", text)
    if airport:
        text = text.replace(airport[1], "<STATION>")
    def normalize_url(match):
        url = match[0]
        if urlparse(url).hostname == "aviationweather.gov":
            url = re.sub(r"(ids=)[A-Z]{4}", r"\1<ICAO>", url)
            url = re.sub(r"(date=)[^&\s]+", r"\1<END_UTC>", url)
        return url
    text = re.sub(r"https?://\S+", normalize_url, text)
    text = re.sub(r"\bon \d{1,2} [A-Za-z]+ '\d{2}\b", "on <DATE>", text)
    return " ".join(text.split())


def assert_rule_contract(row, icao, pins):
    city, family = row["city"], row["family"]
    if icao != pins["stations"].get(city):
        raise ValueError(f"{city}/{family}: reviewed station ICAO drift")
    source = urlparse(row["resolutionSource"])
    normalized = normalized_rule_text(row["rules"])
    if source.hostname == "aviationweather.gov" and source.path == "/api/data/metar":
        if source.scheme != "https" or source.username or source.password or parse_qs(source.query).get("ids") != [icao]:
            raise ValueError(f"{city}/{family}: resolutionSource ICAO drift")
        query = parse_qs(source.query)
        if set(query) != {"ids", "format", "date", "hours"} or query["format"] != ["raw"] or query["hours"] != ["30"]:
            raise ValueError(f"{city}/{family}: resolutionSource format/window drift")
        if set(re.findall(r"\(([A-Z]{4})\)", row["rules"])) != {icao}:
            raise ValueError(f"{city}/{family}: named rule station drift")
        for url in re.findall(r"https?://\S+", row["rules"]):
            if urlparse(url).hostname == "aviationweather.gov" and parse_qs(urlparse(url).query).get("ids") != [icao]:
                raise ValueError(f"{city}/{family}: rule URL ICAO drift")
        if "whole degrees Fahrenheit" in normalized:
            unit = "F"
        elif "whole degrees Celsius" in normalized:
            unit = "C"
        else:
            raise ValueError(f"{city}/{family}: unrecognized METAR market unit")
        kind, variant = "metar_routine", f"metar_{family}_{unit}"
    elif source.hostname == "www.wunderground.com":
        if (source.scheme != "https" or source.username or source.password or
            source.path != f"/history/daily/cn/{city}/{icao}" or
            "whole degrees Celsius" not in normalized):
            raise ValueError(f"{city}/{family}: WU source/unit drift")
        kind, unit, variant = "wu_daily_history", "C", f"wu_{city}"
    elif not row["resolutionSource"] and "Hong Kong Observatory" in normalized and "Daily Extract" in normalized:
        kind, unit, variant = "hko_daily_extract", "C", f"hko_{family}"
    else:
        raise ValueError(f"{city}/{family}: resolution source drift")
    expected = pins["cities"].get(city, {}).get(family)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if expected != variant or pins["variants"].get(variant) != digest:
        raise ValueError(f"{city}/{family}: rule-text variant drift")
    return kind, unit, variant


def load_rule_pins(path=None):
    pins = json.loads((path or config_path("weather_universe_rule_pins.json")).read_text(encoding="utf-8"))
    if pins.get("schema_version") != "weather-universe-rule-pins-v1" or set(pins.get("variants", {})) != {
        "metar_highest_C", "metar_highest_F", "metar_lowest_C", "metar_lowest_F",
        "hko_highest", "hko_lowest", "wu_jinan", "wu_zhengzhou",
    }:
        raise ValueError("unreviewed rule pin schema/variant set")
    if set(pins.get("stations", {})) != set(pins["cities"]):
        raise ValueError("reviewed station coverage drift")
    return pins
