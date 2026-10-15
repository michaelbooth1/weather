"""OB-1 METAR/SPECI first-seen log (51 settlement ICAOs, AWC Data API).

Two channels share one change-key space (``metar``), keyed ``station|obs_time|raw hash``:

- ``metar_recent``: one multi-id request a minute with ``hours=2`` (S0(e): ≤ ~160 rows, under the
  400-row cap). A report's first appearance is its ``first_seen_utc``; ``first_seen_exact`` is true
  only when the previous recent poll succeeded within three intervals (a cold start or outage makes
  the stamp an upper bound).
- ``metar_sweep``: hourly, stations in chunks of ``sweep_chunk`` with ``sweep_hours`` of history so
  every station's local midnight is covered and reports missed during an outage are recovered
  (``via=sweep``, never exact). A reply at the row cap writes a ``cap`` row (truncation).

Parsed per report: T group (tenths), 6 h max/min (1snnn/2snnn), 24 h max/min (4snTTTsnTTT), SLP
group, type (METAR/SPECI) and COR. Rows are ``live_receipt``. The finality snapshot and labels are
S5's job (LB-1); this family only records what AWC served and when we first saw it.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode

from weather.evidence.envelope import epoch_utc_text, parse_utc, utc_text
from weather.evidence.families.common import chunks, item, json_body, settlement_stations, short_hash

PARSER_VERSION = "ob1-metar-1"
CHANNEL_KEYS = "metar"
DEFAULT_BASE_URL = "https://aviationweather.gov/api/data/metar"
AWC_ROW_CAP = 400

_TOKEN = r"(?<!\S){}(?!\S)"
T_GROUP = re.compile(_TOKEN.format(r"T([01])(\d{3})(?:([01])(\d{3}))?"))
MAX6 = re.compile(_TOKEN.format(r"1([01])(\d{3})"))
MIN6 = re.compile(_TOKEN.format(r"2([01])(\d{3})"))
MAXMIN24 = re.compile(_TOKEN.format(r"4([01])(\d{3})([01])(\d{3})"))
SLP = re.compile(_TOKEN.format(r"SLP(\d{3}|NO)"))
COR = re.compile(_TOKEN.format("COR"))


def _tenths(sign, digits):
    return (-1 if sign == "1" else 1) * int(digits) / 10.0


def parse_remarks(raw: str) -> dict:
    main, _, remarks = str(raw or "").partition(" RMK ")
    out = {"t_group_c": None, "t_group_dewpoint_c": None, "max6h_c": None, "min6h_c": None,
           "max24h_c": None, "min24h_c": None, "slp_group": False, "slp_hpa": None,
           "cor": bool(COR.search(main))}
    if match := T_GROUP.search(remarks):
        out["t_group_c"] = _tenths(match.group(1), match.group(2))
        if match.group(3):
            out["t_group_dewpoint_c"] = _tenths(match.group(3), match.group(4))
    if match := MAX6.search(remarks):
        out["max6h_c"] = _tenths(*match.groups())
    if match := MIN6.search(remarks):
        out["min6h_c"] = _tenths(*match.groups())
    if match := MAXMIN24.search(remarks):
        out["max24h_c"] = _tenths(match.group(1), match.group(2))
        out["min24h_c"] = _tenths(match.group(3), match.group(4))
    if match := SLP.search(remarks):
        out["slp_group"] = True
        if match.group(1) != "NO":
            value = int(match.group(1)) / 10.0
            out["slp_hpa"] = value + (900.0 if value >= 50 else 1000.0)
    return out


def _text_time(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return epoch_utc_text(value)
    try:
        return utc_text(parse_utc(str(value).replace(" ", "T") if "T" not in str(value) else str(value)))
    except ValueError:
        try:
            return utc_text(parse_utc(str(value).replace(" ", "T") + "Z"))
        except ValueError:
            return str(value)


def report_items(rows, *, location_by_station, via, exact) -> list[dict]:
    out = []
    for row in rows if isinstance(rows, list) else []:
        raw = str(row.get("rawOb") or "").strip()
        station = str(row.get("icaoId") or "").upper()
        if not raw or not station:
            continue
        obs_time = _text_time(row.get("obsTime"))
        kind = str(row.get("metarType") or ("SPECI" if raw.startswith("SPECI") else "METAR")).upper()
        body = {"station": station, "location": location_by_station.get(station), "obs_time_utc": obs_time,
                "report_time": _text_time(row.get("reportTime")), "receipt_time": _text_time(row.get("receiptTime")),
                "raw": raw, "type": kind, "awc_temp_c": row.get("temp"), **parse_remarks(raw)}
        out.append(item(f"{station}|{obs_time}|{short_hash(raw)}", body, parser_version=PARSER_VERSION,
                        provider_time=body["receipt_time"],
                        meta={"via": via, "first_seen_exact": bool(exact and via == "recent")}))
    return out


def _request(ctx, base, stations, hours, via):
    url = base + "?" + urlencode({"ids": ",".join(stations), "format": "json", "hours": hours})
    response = ctx.fetch(url)
    if response.status == 204:
        return []
    if response.status != 200:
        ctx.gap("http_status", status=response.status, via=via, stations=len(stations))
        return None
    rows = json_body(response)
    if isinstance(rows, list) and len(rows) >= AWC_ROW_CAP:
        ctx.journal.event("cap", {"reason": "awc_row_cap", "rows": len(rows), "stations": stations,
                                  "hours": hours, "via": via}, channel=ctx.channel)
    return rows if isinstance(rows, list) else []


def build(cfg, locations):
    from weather.evidence.child import Channel
    stations = settlement_stations(locations, overrides=cfg.get("station_overrides"))
    location_by_station = {s["station"]: s["location"] for s in stations}
    ids = sorted(location_by_station)
    base = cfg.get("base_url", DEFAULT_BASE_URL)
    channels = cfg["channels"]

    def poll_recent(ctx):
        rows = _request(ctx, base, ids, channels["metar_recent"].get("hours", 2), "recent")
        if rows is None:
            return
        items = report_items(rows, location_by_station=location_by_station, via="recent", exact=ctx.continuous)
        ctx.record(items, channel=CHANNEL_KEYS, meta={"via": "recent", "rows_returned": len(rows),
                                                      "stations_returned": len({i["body"]["station"] for i in items}),
                                                      "stations_requested": len(ids)})

    def poll_sweep(ctx):
        spec = channels["metar_sweep"]
        for group in chunks(ids, spec.get("chunk", 6)):
            rows = _request(ctx, base, group, spec.get("hours", 36), "sweep")
            if rows is None:
                continue
            items = report_items(rows, location_by_station=location_by_station, via="sweep", exact=False)
            ctx.record(items, channel=CHANNEL_KEYS, meta={"via": "sweep", "rows_returned": len(rows),
                                                          "stations_requested": len(group)})
            ctx.sleep(float(spec.get("spacing_seconds", 1.0)))

    out = []
    for name, poll in (("metar_recent", poll_recent), ("metar_sweep", poll_sweep)):
        spec = channels.get(name)
        if spec and spec.get("enabled", True):
            out.append(Channel(name, float(spec["interval_seconds"]), poll, optional=bool(spec.get("optional", True)),
                               quiet_local=tuple(tuple(w) for w in spec.get("quiet_local", []))))
    return out
