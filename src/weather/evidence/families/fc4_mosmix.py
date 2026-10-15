"""FC-4 DWD MOSMIX_L single-station forecasts (CC BY 4.0) for every settlement airport with an id.

Hourly poll per station; the KMZ bytes go to the CAS (deduplicated by digest, so an unchanged file
costs no bytes) and one change-only row per ``station|IssueTime`` carries the extracted TTT
(hourly 2 m temperature, K), TX and TN series and their time steps. ``run_init`` is the IssueTime.
The decompressed KML is bounded by ``MAX_KML_BYTES``.
"""
from __future__ import annotations

import io
import re
import zipfile

from weather.evidence.families.common import item

PARSER_VERSION = "fc4-mosmix-1"
DEFAULT_URL = ("https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/single_stations/"
               "{id}/kml/MOSMIX_L_LATEST_{id}.kmz")
MAX_KML_BYTES = 32 * 1024**2
ELEMENTS = ("TTT", "TX", "TN")
ISSUE = re.compile(r"<dwd:IssueTime>([^<]+)</dwd:IssueTime>")
STEP = re.compile(r"<dwd:TimeStep>([^<]+)</dwd:TimeStep>")
FORECAST = re.compile(r'<dwd:Forecast\s+dwd:elementName="([A-Za-z0-9_]+)">\s*<dwd:value>([^<]*)</dwd:value>')


def kml_text(kmz: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
        if not names:
            raise ValueError("KMZ has no KML member")
        with archive.open(names[0]) as handle:
            raw = handle.read(MAX_KML_BYTES + 1)
    if len(raw) > MAX_KML_BYTES:
        raise ValueError("KML over MAX_KML_BYTES")
    return raw.decode("utf-8", "replace")


def _values(text):
    out = []
    for token in text.split():
        out.append(None if token == "-" else float(token))
    return out


def parse_kml(text) -> dict:
    issue = ISSUE.search(text)
    series = {name: _values(values) for name, values in FORECAST.findall(text) if name in ELEMENTS}
    return {"issue_time": issue.group(1).strip() if issue else None, "time_steps": STEP.findall(text),
            "series": series}


def mosmix_item(location, mosmix_id, kmz, raw_ref) -> dict:
    parsed = parse_kml(kml_text(kmz))
    body = {"location": location, "mosmix_id": mosmix_id, **parsed}
    return item(f"{mosmix_id}|{parsed['issue_time']}", body, parser_version=PARSER_VERSION,
                provider_time=parsed["issue_time"], run_init=parsed["issue_time"], raw_ref=raw_ref)


def build(cfg, locations):
    from weather.evidence.child import Channel
    spec = cfg["channels"]["mosmix_l"]
    stations = dict(cfg["stations"])
    template = spec.get("url_template", DEFAULT_URL)

    def poll(ctx):
        items = []
        for location, mosmix_id in sorted(stations.items()):
            response = ctx.fetch(template.format(id=mosmix_id), max_bytes=4 * 1024**2)
            if response.status != 200:
                ctx.gap("http_status", status=response.status, station=mosmix_id)
                continue
            raw_ref = ctx.journal.put_raw(response.body, channel=ctx.channel)
            try:
                items.append(mosmix_item(location, mosmix_id, response.body, raw_ref))
            except (ValueError, zipfile.BadZipFile) as exc:
                ctx.gap("parse_error", station=mosmix_id, detail=str(exc)[:200])
            ctx.sleep(float(spec.get("spacing_seconds", 0.5)))
        ctx.record(items, meta={"stations": len(stations)})

    if not spec.get("enabled", True):
        return []
    return [Channel("mosmix_l", float(spec["interval_seconds"]), poll, optional=bool(spec.get("optional", True)))]
