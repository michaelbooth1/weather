"""Shared helpers for evidence families: station lists and item construction."""
from __future__ import annotations

import json

from weather.evidence.envelope import LIVE_RECEIPT, envelope, sha256_hex


def settlement_stations(locations, *, overrides=None, country_code=None) -> list[dict]:
    """``[{location, station, timezone}]`` for every configured market (51 today)."""
    overrides = overrides or {}
    out = []
    for row in locations:
        if country_code and row.get("country_code") != country_code:
            continue
        station = (row.get("settlement") or {}).get("station_id")
        if not station:
            continue
        out.append({"location": row["id"], "station": overrides.get(station, station),
                    "timezone": row.get("timezone")})
    return out


def item(key, body, *, parser_version, provider_time=None, run_init=None, raw_ref=None, event_date=None,
         basis=LIVE_RECEIPT, meta=None, partition=None) -> dict:
    out = {"key": key, "body": body,
           "envelope": envelope(basis=basis, parser_version=parser_version, provider_time=provider_time,
                                run_init=run_init, raw_ref=raw_ref, event_date=event_date)}
    if meta:
        out["meta"] = meta
    if partition:
        out["partition"] = partition
    return out


def json_body(response):
    return json.loads(response.body.decode("utf-8"))


def short_hash(text) -> str:
    return sha256_hex(str(text).encode("utf-8"))[:16]


def chunks(values, size):
    size = max(1, int(size))
    return [values[i:i + size] for i in range(0, len(values), size)]
