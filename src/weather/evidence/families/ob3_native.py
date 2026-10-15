"""OB-3 native foreign/Toronto observations (latest-only upstreams, so first-seen is the record).

Channels (each optional, each change-only):

- ``hko_maxmin``: HKO ``latest_since_midnight_maxmin.csv``; one row per configured station name.
- ``hko_rhrread``: HKO current-weather ``rhrread`` temperature list; one row per configured place.
- ``jma_amedas``: JMA bosai AMeDAS 10-minute point file for the configured station (RJTT = 44166).
- ``eccc_swob``: ECCC SWOB-ML directory listing per station; only file names not yet journalled are
  fetched (per-file cache = the journal's change keys), raw XML goes to the CAS, temperature
  elements are extracted into the row.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone

from weather.evidence.envelope import utc_text
from weather.evidence.families.common import item, json_body

PARSER_VERSION = "ob3-native-1"
HKO_MAXMIN_URL = ("https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/"
                  "latest_since_midnight_maxmin.csv")
HKO_RHRREAD_URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en"
JMA_BASE = "https://www.jma.go.jp/bosai/amedas/data"
SWOB_BASE = "https://dd.weather.gc.ca/today/observations/swob-ml"
JST = timezone(timedelta(hours=9))
HKT = timezone(timedelta(hours=8))
SWOB_HREF = re.compile(r'href="([^"/]+-swob\.xml)"')
SWOB_ELEMENT = re.compile(r'<element\s+name="([^"]+)"[^>]*?\svalue="([^"]*)"')


def hko_maxmin_items(text, stations) -> list[dict]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    rows = list(reader)
    out = []
    for row in rows[1:]:
        if len(row) < 4 or row[1].strip() not in stations:
            continue
        stamp = row[0].strip()
        provider = None
        if re.fullmatch(r"\d{12}", stamp):
            provider = utc_text(datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=HKT))
        body = {"station": row[1].strip(), "local_stamp": stamp, "max_since_midnight_c": row[2].strip(),
                "min_since_midnight_c": row[3].strip()}
        out.append(item(f"{body['station']}|{stamp}", body, parser_version=PARSER_VERSION, provider_time=provider))
    return out


def hko_rhrread_items(payload, places) -> list[dict]:
    temperature = (payload or {}).get("temperature") or {}
    record_time = temperature.get("recordTime")
    out = []
    for row in temperature.get("data") or []:
        if row.get("place") not in places:
            continue
        body = {"place": row.get("place"), "value": row.get("value"), "unit": row.get("unit"),
                "record_time": record_time, "update_time": (payload or {}).get("updateTime")}
        out.append(item(f"{row.get('place')}|{record_time}", body, parser_version=PARSER_VERSION,
                        provider_time=record_time))
    return out


def jma_block_name(latest: datetime) -> str:
    local = latest.astimezone(JST)
    return f"{local:%Y%m%d}_{local.hour // 3 * 3:02d}"


def jma_items(payload, station) -> list[dict]:
    out = []
    for stamp, values in sorted((payload or {}).items()):
        if not re.fullmatch(r"\d{14}", stamp) or not isinstance(values, dict):
            continue
        provider = utc_text(datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=JST))
        body = {"station": station, "local_stamp": stamp, "temp": values.get("temp"),
                "humidity": values.get("humidity"), "values": values}
        out.append(item(f"{station}|{stamp}", body, parser_version=PARSER_VERSION, provider_time=provider))
    return out


def swob_listing(html) -> list[str]:
    return sorted(set(SWOB_HREF.findall(html)))


def swob_body(name, xml_text, station) -> dict:
    elements = {k: v for k, v in SWOB_ELEMENT.findall(xml_text)}
    keep = {k: v for k, v in elements.items() if "air_temp" in k or k in ("date_tm", "stn_nam", "tc_id")}
    return {"station": station, "file": name, "auto": "-AUTO-" in name, "elements": keep}


def build(cfg, locations):
    from weather.evidence.child import Channel
    channels = cfg["channels"]

    def poll_hko_maxmin(ctx):
        spec = channels["hko_maxmin"]
        response = ctx.fetch(spec.get("url", HKO_MAXMIN_URL))
        if response.status != 200:
            ctx.gap("http_status", status=response.status)
            return
        items = hko_maxmin_items(response.body.decode("utf-8", "replace"), set(spec["stations"]))
        if not items:
            ctx.warn("configured_station_absent", stations=list(spec["stations"]))
        ctx.record(items)

    def poll_hko_rhrread(ctx):
        spec = channels["hko_rhrread"]
        response = ctx.fetch(spec.get("url", HKO_RHRREAD_URL))
        if response.status != 200:
            ctx.gap("http_status", status=response.status)
            return
        items = hko_rhrread_items(json_body(response), set(spec["places"]))
        if not items:
            ctx.warn("configured_place_absent", places=list(spec["places"]))
        ctx.record(items)

    def poll_jma(ctx):
        spec = channels["jma_amedas"]
        base = spec.get("base_url", JMA_BASE)
        latest = ctx.fetch(f"{base}/latest_time.txt")
        if latest.status != 200:
            ctx.gap("http_status", status=latest.status, step="latest_time")
            return
        stamp = datetime.fromisoformat(latest.body.decode("utf-8").strip())
        station = str(spec["station"])
        response = ctx.fetch(f"{base}/point/{station}/{jma_block_name(stamp)}.json")
        if response.status != 200:
            ctx.gap("http_status", status=response.status, step="point")
            return
        ctx.record(jma_items(json_body(response), station), meta={"latest_time": stamp.isoformat()})

    def poll_swob(ctx):
        spec = channels["eccc_swob"]
        base = spec.get("base_url", SWOB_BASE)
        day = ctx.now().astimezone(timezone.utc).strftime("%Y%m%d")
        budget = int(spec.get("max_new_files_per_poll", 12))
        for station in spec["stations"]:
            listing = ctx.fetch(f"{base}/{day}/{station}/")
            if listing.status == 404:
                marker = f"{station}|{day}"
                if marker not in ctx.state.setdefault("absent_warned", set()):
                    ctx.state["absent_warned"].add(marker)
                    ctx.warn("swob_station_directory_absent", station=station, day=day)
                continue
            if listing.status != 200:
                ctx.gap("http_status", status=listing.status, station=station, step="listing")
                continue
            names = [n for n in swob_listing(listing.body.decode("utf-8", "replace"))
                     if not ctx.journal.seen("eccc_swob", f"{station}|{n}")]
            items = []
            for name in names[-budget:] if budget else []:
                response = ctx.fetch(f"{base}/{day}/{station}/{name}")
                if response.status != 200:
                    ctx.gap("http_status", status=response.status, station=station, file=name)
                    continue
                raw_ref = ctx.journal.put_raw(response.body, channel="eccc_swob")
                body = swob_body(name, response.body.decode("utf-8", "replace"), station)
                items.append(item(f"{station}|{name}", body, parser_version=PARSER_VERSION,
                                  provider_time=body["elements"].get("date_tm"), raw_ref=raw_ref))
            ctx.record(items, meta={"station": station, "listed": len(names), "fetched": len(items)})

    out = []
    for name, poll in (("hko_maxmin", poll_hko_maxmin), ("hko_rhrread", poll_hko_rhrread),
                       ("jma_amedas", poll_jma), ("eccc_swob", poll_swob)):
        spec = channels.get(name)
        if spec and spec.get("enabled", True):
            out.append(Channel(name, float(spec["interval_seconds"]), poll, optional=bool(spec.get("optional", True))))
    return out
