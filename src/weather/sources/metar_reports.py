"""Per-report METAR/SPECI capture ledger (owner decision 2026-10-02, item 4).

The venue resolves on the weather.gov "Hourly Data" rows, which are METAR
based. Two details of those reports are therefore worth keeping verbatim:

* the remark T-group (``T0xxx1xxx``), which carries temperature and dewpoint in
  tenths of a degree Celsius, and
* SPECI reports, which arrive between the routine hourly METARs.

This module is pure parsing plus an append-only, de-duplicated per-day ledger.
It never feeds an existing feature, the observed-high floor, or any settlement
value: the whole-degree and provider-decoded fields used by the model stay
exactly as they were. The observation-trigger loop reuses the METAR payload it
already fetched, so the ledger adds no provider requests.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("metar_report_ledger")

# Observation-trigger capture cadence for the ledger. The owner asked for 2-5
# minutes. 120 s is the floor of that range: the watcher already polls
# AviationWeather every ~60 s for all 12 stations (12 requests/minute against
# the documented 100 requests/minute limit), so the ledger adds no requests and
# the shortest in-range interval gives the finest first-seen resolution.
METAR_REPORT_CAPTURE_INTERVAL_SECONDS = 120.0
METAR_REPORT_TYPES = ("METAR", "SPECI")
LEDGER_DIRNAME = "metar_reports"

# RMK temperature/dewpoint group: T + sign digit + three digits, optionally the
# dewpoint half. Sign digit 0 = positive, 1 = negative; value is tenths of C.
TGROUP_RE = re.compile(r"(?<![A-Z0-9])T([01])(\d{3})(?:([01])(\d{3}))?(?![A-Z0-9])")


def _tenths(sign, digits):
    value = int(digits) / 10.0
    return -value if sign == "1" else value


def parse_tgroup(raw_text):
    """Return ``(temp_celsius, dewpoint_celsius)`` from the RMK T-group.

    Only the remark section is searched so a body group can never be mistaken
    for it. Missing parts are ``None``.
    """

    text = str(raw_text or "").upper()
    marker = text.find(" RMK ")
    if marker < 0:
        return None, None
    match = TGROUP_RE.search(text[marker + 5:])
    if not match:
        return None, None
    temp = _tenths(match.group(1), match.group(2))
    dewpoint = None
    if match.group(3) is not None:
        dewpoint = _tenths(match.group(3), match.group(4))
    return temp, dewpoint


def metar_report_type(row):
    """Return ``METAR`` or ``SPECI`` for an AviationWeather row, else ``None``."""

    row = row or {}
    declared = str(row.get("metarType") or "").strip().upper()
    if declared in METAR_REPORT_TYPES:
        return declared
    raw = str(row.get("rawOb") or row.get("raw") or "").strip().upper()
    for report_type in METAR_REPORT_TYPES:
        if raw.startswith(report_type + " "):
            return report_type
    return None


def obs_time_utc(row):
    value = (row or {}).get("obsTime")
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def metar_row_annotations(row):
    """Additive per-row fields for normalized METAR rows.

    Keys are deliberately disjoint from every native-temperature accessor in
    ``weather.model.feature_store`` so they cannot reach a trained feature.
    """

    temp, dewpoint = parse_tgroup((row or {}).get("rawOb"))
    return {
        "report_type": metar_report_type(row),
        "obs_time_utc": obs_time_utc(row),
        "tgroup_temp_celsius": temp,
        "tgroup_dewpoint_celsius": dewpoint,
    }


def report_key(station_id, row):
    identity = json.dumps(
        [
            str(station_id or ""),
            (row or {}).get("obsTime"),
            (row or {}).get("reportTime"),
            metar_report_type(row),
            str((row or {}).get("rawOb") or ""),
        ],
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def ledger_record(market_id, station_id, row, first_seen_at_utc):
    annotations = metar_row_annotations(row)
    station = str(row.get("icaoId") or station_id or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "metar_report",
        "market_id": market_id,
        "station_id": station,
        "report_key": report_key(station, row),
        "report_type": annotations["report_type"],
        "obs_time_utc": annotations["obs_time_utc"],
        "report_time": row.get("reportTime"),
        "receipt_time": row.get("receiptTime"),
        "first_seen_at_utc": first_seen_at_utc,
        "provider_temp_celsius": row.get("temp"),
        "provider_dewpoint_celsius": row.get("dewp"),
        "tgroup_temp_celsius": annotations["tgroup_temp_celsius"],
        "tgroup_dewpoint_celsius": annotations["tgroup_dewpoint_celsius"],
        "raw": row.get("rawOb"),
    }


def _ledger_date(row, fallback):
    for value in (obs_time_utc(row), row.get("reportTime")):
        if value:
            return str(value)[:10]
    return fallback


def ledger_path(root, market_id, utc_date):
    return Path(root) / str(market_id) / f"metar_reports-{utc_date}.jsonl"


def _existing_keys(path):
    keys = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                key = json.loads(line).get("report_key")
            except (ValueError, AttributeError):
                continue
            if key:
                keys.add(key)
    return keys


def append_new_reports(root, market_id, station_id, payload, captured_at):
    """Append reports not yet in the per-UTC-day ledger; return the count."""

    captured_utc = captured_at.astimezone(timezone.utc)
    fallback_date = captured_utc.date().isoformat()
    first_seen = captured_utc.isoformat()
    by_path = {}
    for row in payload or []:
        if not isinstance(row, dict) or not row.get("rawOb"):
            continue
        path = ledger_path(root, market_id, _ledger_date(row, fallback_date))
        by_path.setdefault(path, []).append(row)
    appended = 0
    for path, rows in sorted(by_path.items()):
        seen = _existing_keys(path)
        lines = []
        for row in rows:
            record = ledger_record(market_id, station_id, row, first_seen)
            if record["report_key"] in seen:
                continue
            seen.add(record["report_key"])
            lines.append(json.dumps(record, sort_keys=True))
        if not lines:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        appended += len(lines)
    return appended


def capture_due(last_capture_at, now, interval_seconds=METAR_REPORT_CAPTURE_INTERVAL_SECONDS):
    if last_capture_at is None:
        return True
    return (now - last_capture_at).total_seconds() >= float(interval_seconds)


_LAST_CAPTURE_AT = {}


def capture_from_sources(
    root,
    market_id,
    station_id,
    sources,
    now,
    *,
    interval_seconds=METAR_REPORT_CAPTURE_INTERVAL_SECONDS,
    last_capture_at=None,
):
    """Gate and capture the METAR payload already fetched by the watcher.

    A stale or failed (last-good) METAR item is never captured: its reports
    would carry a false first-seen time. Errors are returned, never raised, so
    the ledger cannot interrupt the observation trigger.
    """

    state = _LAST_CAPTURE_AT if last_capture_at is None else last_capture_at
    gate_key = (str(root), str(market_id))
    result = {"interval_seconds": float(interval_seconds), "appended": 0}
    item = (sources or {}).get("metar")
    if not isinstance(item, dict):
        return {**result, "status": "not_configured"}
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    if not item.get("ok") or item.get("stale") or "raw_payload" not in data:
        return {**result, "status": "skipped_not_fresh"}
    if not capture_due(state.get(gate_key), now, interval_seconds):
        return {**result, "status": "not_due"}
    try:
        appended = append_new_reports(
            root,
            market_id,
            station_id,
            data.get("raw_payload"),
            now,
        )
    except (OSError, TypeError, ValueError) as exc:
        return {**result, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    state[gate_key] = now
    return {**result, "status": "captured", "appended": appended}
