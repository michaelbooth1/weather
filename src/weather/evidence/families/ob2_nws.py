"""OB-2 US 5-minute ASOS first-seen log (``api.weather.gov``, User-Agent only, 11 US stations).

One request per station every interval (``/stations/<icao>/observations?limit=N``). Each
observation is keyed ``station|timestamp`` and recorded change-only, so a later QC revision of the
same timestamp appears as a new row with the same key. Rows are ``live_receipt``; the provider
timestamp is the observation time, not an availability stamp.
"""
from __future__ import annotations

from weather.evidence.families.common import item, json_body, settlement_stations

PARSER_VERSION = "ob2-nws-1"
DEFAULT_BASE_URL = "https://api.weather.gov/stations"
FIELDS = ("temperature", "dewpoint", "maxTemperatureLast24Hours", "minTemperatureLast24Hours",
          "relativeHumidity", "windSpeed", "barometricPressure")


def _quantity(value):
    if not isinstance(value, dict):
        return None
    return {"value": value.get("value"), "unit": value.get("unitCode"), "qc": value.get("qualityControl")}


def observation_items(payload, *, station, location, exact) -> list[dict]:
    out = []
    for feature in (payload or {}).get("features") or []:
        props = (feature or {}).get("properties") or {}
        stamp = props.get("timestamp")
        if not stamp:
            continue
        body = {"station": station, "location": location, "timestamp": stamp,
                "raw_message": props.get("rawMessage") or None,
                **{name: _quantity(props.get(name)) for name in FIELDS}}
        out.append(item(f"{station}|{stamp}", body, parser_version=PARSER_VERSION, provider_time=stamp,
                        meta={"first_seen_exact": bool(exact)}))
    return out


def build(cfg, locations):
    from weather.evidence.child import Channel
    stations = settlement_stations(locations, country_code=cfg.get("country_code", "US"))
    base = cfg.get("base_url", DEFAULT_BASE_URL)
    spec = cfg["channels"]["nws_observations"]
    limit = int(spec.get("limit", 3))

    def poll(ctx):
        for row in stations:
            response = ctx.fetch(f"{base}/{row['station']}/observations?limit={limit}",
                                 headers={"Accept": "application/geo+json"})
            if response.status != 200:
                ctx.gap("http_status", status=response.status, station=row["station"])
                continue
            items = observation_items(json_body(response), station=row["station"], location=row["location"],
                                      exact=ctx.continuous)
            ctx.record(items, meta={"station": row["station"]})
            ctx.sleep(float(spec.get("spacing_seconds", 0.5)))

    if not spec.get("enabled", True):
        return []
    return [Channel("nws_observations", float(spec["interval_seconds"]), poll,
                    optional=bool(spec.get("optional", True)))]
