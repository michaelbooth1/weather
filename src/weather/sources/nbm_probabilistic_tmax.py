"""NBM probabilistic maximum-temperature text guidance.

The NBP station text bulletin carries QMD daily max/min temperature
percentiles without requiring per-market GRIB extraction. GRIB/QMD native
exceedance grids are tracked separately by roadmap item 190.
"""
from __future__ import annotations

import hashlib
import csv
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from weather.forecast_payload_contracts import (
    NBM_NBP_ENCODING,
    NBM_NBP_EXTRACTION_SCHEMA,
    NBM_NBP_MEDIA_TYPE,
    NBM_NBP_SOURCE,
    nbm_nbp_cycle_key_from_url,
    nbm_nbp_request_key,
    validate_forecast_extraction_identity,
)
from weather.sources.grib_probe import extract_nearest_with_wgrib2, parse_idx_lines


NBM_PROB_TMAX_SCHEMA_VERSION = "nbm_probabilistic_tmax_v0.1"
NBM_STATION_ARCHIVE_SCHEMA_VERSION = "nbm_probabilistic_tmax_station_archive_v0.1"
NBM_NBP_BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"
NBM_QMD_DEFAULT_DOMAIN = "co"
NBM_NBP_PERCENTILE_ROWS = {
    "TXNP1": 10,
    "TXNP2": 25,
    "TXNP5": 50,
    "TXNP7": 75,
    "TXNP9": 90,
}
NBM_NBP_PARSER_V1 = "nbm-probabilistic-tmax-parser-v1"
NBM_NBP_PARSER_V2 = "nbm-probabilistic-tmax-parser-v2"
NBM_NBP_TXN_CYCLES = (0, 1, 7, 12, 13, 19)
# Explicitly qualified mainland stations. Unknown geography fails closed in v2.
NBM_NBP_STATION_TIMEZONES = {
    "KLGA": "America/New_York", "KATL": "America/New_York",
    "KMIA": "America/New_York", "KAUS": "America/Chicago",
    "KORD": "America/Chicago", "KDAL": "America/Chicago",
    "KHOU": "America/Chicago", "KBKF": "America/Denver",
    "KLAX": "America/Los_Angeles", "KSFO": "America/Los_Angeles",
    "KSEA": "America/Los_Angeles",
}
NBM_PROB_TMAX_PROVENANCE_COLUMNS = [
    "nbm_prob_tmax_parser_version", "nbm_prob_tmax_valid_hour_utc",
    "nbm_prob_tmax_cycle_age_hours", "nbm_prob_tmax_maximum_period_flag",
]
NBM_PROB_TMAX_FEATURE_COLUMNS = [
    "nbm_prob_tmax_p10",
    "nbm_prob_tmax_p25",
    "nbm_prob_tmax_p50",
    "nbm_prob_tmax_p75",
    "nbm_prob_tmax_p90",
    "nbm_prob_tmax_mean",
    "nbm_prob_tmax_stddev",
    "nbm_prob_tmax_iqr",
    "nbm_prob_tmax_p10_p90_spread",
    "nbm_prob_tmax_p50_vs_forecast_high",
    "nbm_prob_tmax_p90_vs_forecast_high",
    "nbm_prob_tmax_exceed_forecast_high",
    "nbm_prob_tmax_physical_valid_flag",
    "nbm_prob_tmax_impossible_flag",
    "nbm_prob_tmax_floor_gap",
    *NBM_PROB_TMAX_PROVENANCE_COLUMNS,
]
NBM_STATION_ARCHIVE_COLUMNS = [
    "schema_version",
    "source",
    "source_kind",
    "station_id",
    "target_date",
    "available",
    "reason",
    "issued_at",
    "forecast_hour",
    "valid_time_utc",
    "product_version",
    "p10",
    "p25",
    "p50",
    "p75",
    "p90",
    "mean_native",
    "stddev_native",
    "day_max_native",
    "p10_p90_spread",
    "iqr",
    "source_url",
    "payload_hash",
    "fetched_at",
    "raw_payload_path",
    "parser_version", "period_kind", "group_index", "token_index",
    "cycle_age_hours",
]


def nbp_text_url(run_time: datetime, base_url: str = NBM_NBP_BASE_URL) -> str:
    run_time = run_time.astimezone(timezone.utc)
    day = run_time.strftime("%Y%m%d")
    hour = run_time.strftime("%H")
    return f"{base_url}/blend.{day}/{hour}/text/blend_nbptx.t{hour}z"


def nbp_request_key(source_url: str) -> str:
    """Return the market-invariant request identity for one national bulletin."""

    return nbm_nbp_request_key(source_url)


def nbp_cycle_key(run_time: datetime) -> str:
    run_time = run_time.astimezone(timezone.utc)
    return f"nbm-nbp:{run_time.strftime('%Y%m%dT%HZ')}"


def nbp_cycle_key_from_url(source_url: str) -> str:
    return nbm_nbp_cycle_key_from_url(source_url)


def nbp_cycle_candidates(now_utc: datetime | None = None, hours_back: int = 24) -> list[datetime]:
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cursor = now_utc.replace(minute=0, second=0, microsecond=0)
    return [cursor - timedelta(hours=offset) for offset in range(max(0, int(hours_back)) + 1)]


def nbp_target_cycle_candidates(now_utc: datetime, target_date: date, hours_back: int = 24,
                                *, cycles: Iterable[datetime] | None = None) -> list[datetime]:
    """Newest complete-TXN cycle whose published horizon can include the day.

    The 00/01/07Z first maximum labels the issue date's daytime window;
    12/13/19Z start with a minimum and first carry the following day's maximum.
    Actual station completeness and period identity are still checked by v2.
    """
    result = []
    for cycle in nbp_cycle_candidates(now_utc, hours_back) if cycles is None else cycles:
        if cycle.hour not in NBM_NBP_TXN_CYCLES:
            continue
        first_day = cycle.date() + timedelta(days=int(cycle.hour >= 12))
        if first_day <= target_date <= first_day + timedelta(days=8):
            result.append(cycle)
    return result


def qmd_grib_url(
    run_time: datetime,
    forecast_hour: int,
    *,
    domain: str = NBM_QMD_DEFAULT_DOMAIN,
    base_url: str = NBM_NBP_BASE_URL,
) -> str:
    run_time = run_time.astimezone(timezone.utc)
    day = run_time.strftime("%Y%m%d")
    hour = run_time.strftime("%H")
    fff = f"{int(forecast_hour):03d}"
    domain = str(domain or NBM_QMD_DEFAULT_DOMAIN).lower().strip()
    return f"{base_url}/blend.{day}/{hour}/qmd/blend.t{hour}z.qmd.f{fff}.{domain}.grib2"


def qmd_grib_idx_url(grib_url: str) -> str:
    return f"{str(grib_url).rstrip()}.idx"


def _idx_body_match(record: dict) -> str:
    raw_line = str((record or {}).get("raw_line") or "")
    parts = raw_line.split(":")
    if len(parts) <= 3:
        return raw_line
    return ":".join(parts[3:])


def _qmd_record_match(record: dict) -> str:
    body = _idx_body_match(record)
    return f":{body}" if body and not body.startswith(":") else body


def _qmd_record_text(record: dict) -> str:
    return " ".join([
        str((record or {}).get("variable") or ""),
        str((record or {}).get("level") or ""),
        str((record or {}).get("forecast_step") or ""),
        str((record or {}).get("raw_line") or ""),
    ]).lower()


def _is_qmd_tmax_record(record: dict) -> bool:
    text = _qmd_record_text(record)
    variable = str((record or {}).get("variable") or "").upper()
    return variable == "TMAX" or "maximum temperature" in text or "max temperature" in text


def _parse_qmd_percentile(record: dict) -> int | None:
    text = _qmd_record_text(record)
    for pattern in (
        r"\b(?P<value>\d+(?:\.\d+)?)\s*%\s*level\b",
        r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:st|nd|rd|th)?\s*percentile\b",
        r"\bpercentile\s*(?P<value>\d+(?:\.\d+)?)\b",
    ):
        match = re.search(pattern, text)
        if match:
            return int(round(float(match.group("value"))))
    return None


def _parse_qmd_exceedance_threshold(record: dict) -> float | None:
    text = _qmd_record_text(record)
    for pattern in (
        r"\bprob(?:ability)?\s*(?:of)?\s*(?:>|>=|gt|ge)\s*(?P<value>-?\d+(?:\.\d+)?)",
        r"\b(?:>|>=)\s*(?P<value>-?\d+(?:\.\d+)?)\b",
        r"\bexceed(?:ance|ing)?\s*(?P<value>-?\d+(?:\.\d+)?)\b",
    ):
        match = re.search(pattern, text)
        if match:
            return float(match.group("value"))
    return None


def select_qmd_tmax_idx_records(
    idx_text: str,
    *,
    percentiles: Iterable[int] | None = (10, 25, 50, 75, 90),
    exceedance_thresholds: Iterable[float] | None = None,
) -> list[dict]:
    wanted_percentiles = {
        int(value) for value in (percentiles or [])
    } if percentiles is not None else None
    wanted_thresholds = {
        float(value) for value in (exceedance_thresholds or [])
    } if exceedance_thresholds is not None else None
    selected = []
    for record in parse_idx_lines(idx_text):
        if not _is_qmd_tmax_record(record):
            continue
        percentile = _parse_qmd_percentile(record)
        threshold = _parse_qmd_exceedance_threshold(record)
        kind = None
        if percentile is not None and (wanted_percentiles is None or percentile in wanted_percentiles):
            kind = "percentile"
        elif threshold is not None and (wanted_thresholds is None or threshold in wanted_thresholds):
            kind = "exceedance_probability"
        if kind is None:
            continue
        row = dict(record)
        row.update({
            "source_kind": "qmd_grib_idx",
            "kind": kind,
            "percentile": percentile,
            "threshold": threshold,
            "match": _qmd_record_match(record),
        })
        selected.append(row)
    selected.sort(key=lambda row: (
        row.get("kind") or "",
        row.get("percentile") if row.get("percentile") is not None else 9999,
        row.get("threshold") if row.get("threshold") is not None else 9999,
        row.get("message_number") or 0,
    ))
    return selected


def _kelvin_to_fahrenheit(value: float | None) -> float | None:
    if value is None:
        return None
    return (float(value) - 273.15) * 9.0 / 5.0 + 32.0


def _probability_unit_value(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if value > 1.0:
        return value / 100.0
    return value


def extract_qmd_grib_tmax_point(
    grib_path,
    idx_text: str,
    *,
    lon: float,
    lat: float,
    run_time: datetime | str | None = None,
    forecast_hour: int | None = None,
    target_date: date | str | None = None,
    source_url: str | None = None,
    domain: str = NBM_QMD_DEFAULT_DOMAIN,
    percentiles: Iterable[int] | None = (10, 25, 50, 75, 90),
    exceedance_thresholds: Iterable[float] | None = None,
    wgrib2_path: str | None = None,
    extractor=None,
) -> dict:
    """Extract native QMD Tmax percentile/exceedance records for one point.

    The extractor defaults to ``wgrib2 -lon`` through ``grib_probe`` but is
    injectable so tests and offline callers can verify record selection without
    a local GRIB decoder.
    """
    records = select_qmd_tmax_idx_records(
        idx_text,
        percentiles=percentiles,
        exceedance_thresholds=exceedance_thresholds,
    )
    extract = extractor or extract_nearest_with_wgrib2
    percentile_values_k = {}
    percentile_values_f = {}
    exceedance_probabilities = {}
    extraction_rows = []
    failures = []
    for record in records:
        try:
            extracted = extract(
                grib_path,
                lon=lon,
                lat=lat,
                match=record["match"],
                wgrib2_path=wgrib2_path,
            )
        except TypeError:
            extracted = extract(grib_path, lon, lat, record["match"])
        except Exception as exc:  # noqa: BLE001 - source payload should preserve extraction failure detail
            failures.append({
                "record": record,
                "reason": str(exc),
            })
            continue
        value = extracted.get("value") if isinstance(extracted, dict) else None
        if record.get("kind") == "percentile":
            percentile = str(int(record["percentile"]))
            percentile_values_k[percentile] = value
            percentile_values_f[percentile] = _kelvin_to_fahrenheit(value)
        elif record.get("kind") == "exceedance_probability":
            threshold = str(record.get("threshold"))
            exceedance_probabilities[threshold] = _probability_unit_value(value)
        extraction_rows.append({
            "kind": record.get("kind"),
            "percentile": record.get("percentile"),
            "threshold": record.get("threshold"),
            "match": record.get("match"),
            "idx_line": record.get("raw_line"),
            "value": value,
            "extraction": extracted,
        })
    p10 = percentile_values_f.get("10")
    p25 = percentile_values_f.get("25")
    p50 = percentile_values_f.get("50")
    p75 = percentile_values_f.get("75")
    p90 = percentile_values_f.get("90")
    if isinstance(run_time, datetime):
        run_time_value = run_time.astimezone(timezone.utc).isoformat()
    else:
        run_time_value = run_time
    target_date_value = target_date.isoformat() if isinstance(target_date, date) else target_date
    available = bool(percentile_values_f or exceedance_probabilities) and not failures
    return {
        "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
        "available": available,
        "source": "nbm_probabilistic_tmax",
        "source_kind": "qmd_grib_point",
        "domain": domain,
        "run_time": run_time_value,
        "forecast_hour": forecast_hour,
        "target_date": target_date_value,
        "lon": lon,
        "lat": lat,
        "source_url": source_url,
        "grib_path": str(grib_path),
        "idx_record_count": len(parse_idx_lines(idx_text)),
        "selected_record_count": len(records),
        "extracted_record_count": len(extraction_rows),
        "percentiles_kelvin": percentile_values_k,
        "percentiles": percentile_values_f,
        "exceedance_probabilities": exceedance_probabilities,
        "mean_native": p50,
        "day_max_native": p50,
        "day_max_c": p50,
        "p10_p90_spread": p90 - p10 if p10 is not None and p90 is not None else None,
        "iqr": p75 - p25 if p25 is not None and p75 is not None else None,
        "exceedance_grid_available": bool(exceedance_probabilities),
        "exceedance_status": "native_qmd_grib_extracted" if exceedance_probabilities else "native_qmd_grib_percentiles_extracted",
        "records": records,
        "extractions": extraction_rows,
        "failures": failures,
    }


def _payload_hash(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="replace")).hexdigest()


def nbp_raw_payload(text: str, station_id: str, target_date: date | str, source_url: str | None = None, fetched_at: str | None = None) -> dict:
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    payload = {
        "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
        "source": NBM_NBP_SOURCE,
        "source_kind": "nbp_station_text",
        "station_id": str(station_id or "").upper().strip(),
        "target_date": target_date.isoformat(),
        "source_url": source_url,
        "fetched_at": fetched_at,
        "payload_hash": _payload_hash(text),
        "text": str(text or ""),
    }
    if source_url:
        # The national text response is invariant across markets for this exact
        # URL/cycle.  Station and target-date fields remain outside the attested
        # body and are retained as the per-market extraction identity.
        payload["forecast_payload_attestation"] = {
            "market_invariant": True,
            "source": NBM_NBP_SOURCE,
            "request_key": nbp_request_key(source_url),
            "cycle_key": nbp_cycle_key_from_url(source_url),
            "body_field": "text",
            "encoding": NBM_NBP_ENCODING,
            "media_type": NBM_NBP_MEDIA_TYPE,
            "extraction_schema": NBM_NBP_EXTRACTION_SCHEMA,
            "extraction_identity": {
                "station_id": str(station_id or "").upper().strip(),
                "target_date": target_date.isoformat(),
            },
        }
    return payload


def replay_nbp_shared_payload(
    payload_bytes: bytes,
    extraction_identity: dict,
    *,
    source_url: str | None = None,
    fetched_at: str | None = None,
    parser_version: str | int | None = None,
) -> dict:
    """Replay one market extraction from verified shared national bytes."""

    extraction_identity = validate_forecast_extraction_identity(
        NBM_NBP_SOURCE,
        NBM_NBP_EXTRACTION_SCHEMA,
        extraction_identity,
    )
    station_id = extraction_identity["station_id"]
    target_date = extraction_identity["target_date"]
    text = bytes(payload_bytes).decode("utf-8", errors="strict")
    return parse_nbp_station_tmax(
        text,
        station_id,
        target_date,
        source_url=source_url,
        fetched_at=fetched_at,
        parser_version=parser_version or NBM_NBP_PARSER_V1,
    )


def _parse_issue_time(line: str) -> datetime | None:
    match = re.search(r"NBM\s+V(?P<version>\S+)\s+NBP\s+GUIDANCE\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+(?P<hour>\d{4})\s+UTC", line)
    if not match:
        return None
    return datetime.strptime(
        f"{match.group('date')} {match.group('hour')}",
        "%m/%d/%Y %H%M",
    ).replace(tzinfo=timezone.utc)


def _parse_product_version(line: str) -> str | None:
    match = re.search(r"NBM\s+V(?P<version>\S+)\s+NBP\s+GUIDANCE", line)
    return match.group("version") if match else None


def _row_code(line: str) -> str:
    return str(line[:6] or "").strip().upper()


def _parse_pair_row(line: str) -> list[tuple[float | None, float | None]]:
    groups = str(line[6:] or "").split("|")
    pairs = []
    for group in groups:
        tokens = re.findall(r"-?\d+(?:\.\d+)?", group)
        first = float(tokens[0]) if tokens else None
        second = float(tokens[1]) if len(tokens) > 1 else None
        pairs.append((first, second))
    return pairs


def _station_header_re(station_id: str) -> re.Pattern:
    return re.compile(
        rf"^\s*{re.escape(station_id.upper())}\s+NBM\s+V\S+\s+NBP\s+GUIDANCE\b",
        re.IGNORECASE,
    )


def station_nbp_block(text: str, station_id: str) -> list[str]:
    station_id = str(station_id or "").upper().strip()
    if not station_id:
        return []
    lines = str(text or "").splitlines()
    header_re = _station_header_re(station_id)
    start = None
    for index, line in enumerate(lines):
        if header_re.search(line):
            start = index
            break
    if start is None:
        return []
    next_header_re = re.compile(r"^\s*[A-Z0-9]{3,5}\s+NBM\s+V\S+\s+NBP\s+GUIDANCE\b", re.IGNORECASE)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if next_header_re.search(lines[index]):
            end = index
            break
    return lines[start:end]


def _slot_index_for_target_v1(fhr_pairs: Iterable[tuple[float | None, float | None]], issue_time: datetime, target_date: date) -> int | None:
    for index, pair in enumerate(fhr_pairs):
        max_fhr = pair[0]
        if max_fhr is None:
            continue
        valid_time = issue_time + timedelta(hours=float(max_fhr))
        max_target_date = (valid_time - timedelta(days=1)).date()
        if max_target_date == target_date:
            return index
    return None


def parse_nbp_station_tmax_v1(text: str, station_id: str, target_date: date | str, source_url: str | None = None, fetched_at: str | None = None) -> dict:
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    station_id = str(station_id or "").upper().strip()
    block = station_nbp_block(text, station_id)
    if not block:
        return {
            "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
            "available": False,
            "station_id": station_id,
            "target_date": target_date.isoformat(),
            "reason": "station_not_found_in_nbp_text",
            "source_url": source_url,
            "url": source_url,
            "payload_hash": _payload_hash(text),
            "fetched_at": fetched_at,
            "raw_payload": nbp_raw_payload(text, station_id, target_date, source_url=source_url, fetched_at=fetched_at),
        }
    issue_time = _parse_issue_time(block[0])
    if issue_time is None:
        return {
            "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
            "available": False,
            "station_id": station_id,
            "target_date": target_date.isoformat(),
            "reason": "nbp_issue_time_not_found",
            "source_url": source_url,
            "url": source_url,
            "payload_hash": _payload_hash(text),
            "fetched_at": fetched_at,
            "raw_payload": nbp_raw_payload(text, station_id, target_date, source_url=source_url, fetched_at=fetched_at),
        }

    rows = {_row_code(line): _parse_pair_row(line) for line in block if _row_code(line)}
    fhr_pairs = rows.get("FHR") or []
    slot_index = _slot_index_for_target_v1(fhr_pairs, issue_time, target_date)
    if slot_index is None:
        return {
            "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
            "available": False,
            "station_id": station_id,
            "issued_at": issue_time.isoformat(),
            "target_date": target_date.isoformat(),
            "reason": "target_date_not_in_nbp_max_temperature_window",
            "source_url": source_url,
            "url": source_url,
            "payload_hash": _payload_hash(text),
            "fetched_at": fetched_at,
            "raw_payload": nbp_raw_payload(text, station_id, target_date, source_url=source_url, fetched_at=fetched_at),
        }

    percentiles = {}
    for row_code, percentile in NBM_NBP_PERCENTILE_ROWS.items():
        values = rows.get(row_code) or []
        value = values[slot_index][0] if slot_index < len(values) else None
        percentiles[str(percentile)] = value
    mean_values = rows.get("TXNMN") or []
    stddev_values = rows.get("TXNSD") or []
    mean_native = mean_values[slot_index][0] if slot_index < len(mean_values) else None
    stddev_native = stddev_values[slot_index][0] if slot_index < len(stddev_values) else None
    max_fhr = fhr_pairs[slot_index][0]
    valid_time = issue_time + timedelta(hours=float(max_fhr)) if max_fhr is not None else None
    p10 = percentiles.get("10")
    p25 = percentiles.get("25")
    p50 = percentiles.get("50")
    p75 = percentiles.get("75")
    p90 = percentiles.get("90")
    return {
        "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
        "available": True,
        "source_kind": "nbp_station_text",
        "station_id": station_id,
        "issued_at": issue_time.isoformat(),
        "forecast_hour": int(max_fhr) if max_fhr is not None else None,
        "valid_time_utc": valid_time.isoformat() if valid_time is not None else None,
        "target_date": target_date.isoformat(),
        "product_version": _parse_product_version(block[0]),
        "percentiles": percentiles,
        "mean_native": mean_native,
        "stddev_native": stddev_native,
        "day_max_native": p50,
        "day_max_c": p50,
        "p10_p90_spread": p90 - p10 if p10 is not None and p90 is not None else None,
        "iqr": p75 - p25 if p25 is not None and p75 is not None else None,
        "source_url": source_url,
        "url": source_url,
        "payload_hash": _payload_hash(text),
        "fetched_at": fetched_at,
        "historical_archive_available": False,
        "exceedance_grid_available": False,
        "exceedance_status": "native_qmd_grid_or_band_edge_extraction_pending",
        "live_only_fields": list(NBM_PROB_TMAX_FEATURE_COLUMNS[:-len(NBM_PROB_TMAX_PROVENANCE_COLUMNS)]),
        "raw_station_block": "\n".join(block),
        "raw_payload": nbp_raw_payload(text, station_id, target_date, source_url=source_url, fetched_at=fetched_at),
    }


def nbp_parser_version_number(value: str | int | None) -> int:
    if value in (None, "", 1, "1", NBM_NBP_PARSER_V1):
        return 1
    if value in (2, "2", NBM_NBP_PARSER_V2):
        return 2
    raise ValueError(f"unsupported NBP parser version: {value!r}")


def _slot_for_target_v2(rows: dict, issue: datetime, target: date, station_id: str):
    zone_name = NBM_NBP_STATION_TIMEZONES.get(station_id)
    if zone_name is None:
        return None, "station_max_date_ambiguous"
    zone = ZoneInfo(zone_name)
    matches = []
    for group, pair in enumerate(rows.get("FHR") or []):
        for token, lead in enumerate(pair):
            if lead is None or lead < 0 or not lead.is_integer():
                continue
            valid = issue + timedelta(hours=lead)
            if valid.hour != 0 or valid.minute != 0:
                continue
            # NOAA's 12Z..06Z window is named by its daytime date, not by
            # its ending date. Its start and 00Z label must agree locally.
            local_day = (valid - timedelta(hours=12)).astimezone(zone).date()
            if valid.astimezone(zone).date() != local_day:
                return None, "station_max_date_ambiguous"
            if local_day == target:
                matches.append((group, token, lead, valid))
    if len(matches) != 1:
        return None, "target_max_not_in_cycle" if not matches else "target_max_ambiguous"
    return matches[0], None


def parse_nbp_station_tmax(text: str, station_id: str, target_date: date | str,
                           source_url: str | None = None, fetched_at: str | None = None,
                           *, parser_version: str | int = NBM_NBP_PARSER_V2) -> dict:
    """Parse a complete target-day maximum; v1 remains an explicit replay rule."""
    if nbp_parser_version_number(parser_version) == 1:
        return parse_nbp_station_tmax_v1(text, station_id, target_date, source_url, fetched_at)
    target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    station = str(station_id or "").strip().upper()
    block = station_nbp_block(text, station)
    issue = _parse_issue_time(block[0]) if block else None
    raw = nbp_raw_payload(text, station, target, source_url, fetched_at)
    raw["parser_version"] = NBM_NBP_PARSER_V2
    payload = {
        "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
        "parser_version": NBM_NBP_PARSER_V2,
        "available": False, "source_kind": "nbp_station_text",
        "station_id": station, "target_date": target.isoformat(),
        "source_url": source_url, "url": source_url, "fetched_at": fetched_at,
        "payload_hash": _payload_hash(text), "raw_payload": raw,
        "raw_station_block": "\n".join(block),
        "percentiles": {}, "period_kind": None,
    }
    if not block or issue is None:
        payload["reason"] = "station_not_found_in_nbp_text" if not block else "nbp_issue_time_not_found"
        return payload
    payload["issued_at"] = issue.isoformat()
    payload["product_version"] = _parse_product_version(block[0])
    rows = {_row_code(line): _parse_pair_row(line) for line in block if _row_code(line)}
    selected, reason = _slot_for_target_v2(rows, issue, target, station)
    if selected is None:
        payload["reason"] = reason
        return payload
    group, token, lead, valid = selected
    values, rejections = {}, {}
    for code in (*NBM_NBP_PERCENTILE_ROWS, "TXNMN", "TXNSD"):
        pairs = rows.get(code) or []
        value = pairs[group][token] if group < len(pairs) else None
        values[code] = value
        rejections[code] = ("missing_row_or_token" if value is None else
                            "provider_missing_sentinel" if value == -99 else
                            "negative_spread" if code == "TXNSD" and value < 0 else None)
    age = None
    if fetched_at:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            raise ValueError("NBP fetched_at must be timezone aware")
        age = (fetched - issue).total_seconds() / 3600
        if age < 0:
            raise ValueError("NBP issue time is after capture")
    provenance = {
        "issued_at": issue.isoformat(), "valid_time_utc": valid.isoformat(),
        "period_kind": "maximum", "group_index": group, "token_index": token,
        "forecast_hour": int(lead), "cycle_age_hours": age,
        "station_timezone": NBM_NBP_STATION_TIMEZONES[station],
        "raw_values": values, "value_rejection_reasons": rejections,
    }
    payload.update(provenance)
    raw.update(provenance)
    if any(rejections.values()):
        payload["reason"] = "target_max_incomplete_rows"
        return payload
    percentiles = {str(q): values[code] for code, q in NBM_NBP_PERCENTILE_ROWS.items()}
    payload.update({
        "available": True, "percentiles": percentiles,
        "mean_native": values["TXNMN"], "stddev_native": values["TXNSD"],
        "day_max_native": percentiles["50"], "day_max_c": percentiles["50"],
        "p10_p90_spread": percentiles["90"] - percentiles["10"],
        "iqr": percentiles["75"] - percentiles["25"],
        "historical_archive_available": False, "exceedance_grid_available": False,
        "exceedance_status": "native_qmd_grid_or_band_edge_extraction_pending",
        "live_only_fields": list(NBM_PROB_TMAX_FEATURE_COLUMNS),
    })
    return payload


def nbp_station_archive_row(payload: dict, raw_payload_path: str | None = None) -> dict:
    percentiles = (payload or {}).get("percentiles") or {}
    available = bool((payload or {}).get("available"))
    return {
        "schema_version": NBM_STATION_ARCHIVE_SCHEMA_VERSION,
        "source": "nbm_probabilistic_tmax",
        "source_kind": (payload or {}).get("source_kind") or "nbp_station_text",
        "station_id": (payload or {}).get("station_id"),
        "target_date": (payload or {}).get("target_date"),
        "available": available,
        "reason": (payload or {}).get("reason"),
        "issued_at": (payload or {}).get("issued_at"),
        "forecast_hour": (payload or {}).get("forecast_hour"),
        "valid_time_utc": (payload or {}).get("valid_time_utc"),
        "product_version": (payload or {}).get("product_version"),
        "p10": percentiles.get("10"),
        "p25": percentiles.get("25"),
        "p50": percentiles.get("50"),
        "p75": percentiles.get("75"),
        "p90": percentiles.get("90"),
        "mean_native": (payload or {}).get("mean_native"),
        "stddev_native": (payload or {}).get("stddev_native"),
        "day_max_native": (payload or {}).get("day_max_native"),
        "p10_p90_spread": (payload or {}).get("p10_p90_spread"),
        "iqr": (payload or {}).get("iqr"),
        "source_url": (payload or {}).get("source_url") or (payload or {}).get("url"),
        "payload_hash": (payload or {}).get("payload_hash"),
        "fetched_at": (payload or {}).get("fetched_at"),
        "raw_payload_path": raw_payload_path,
        **{key: (payload or {}).get(key) for key in (
            "parser_version", "period_kind", "group_index", "token_index", "cycle_age_hours"
        )},
    }


def _append_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


class NBPStationArchiveStore:
    def __init__(self, root):
        self.root = Path(root)
        self.payload_dir = self.root / "payloads"
        self.rows_path = self.root / "nbp_station_tmax.csv"

    def existing_keys(self) -> set[tuple]:
        if not self.rows_path.exists():
            return set()
        keys = set()
        with self.rows_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                keys.add((
                    row.get("station_id"),
                    row.get("target_date"),
                    row.get("issued_at"),
                    row.get("payload_hash"),
                    nbp_parser_version_number(row.get("parser_version")),
                ))
        return keys

    def write_payload(self, payload: dict) -> dict:
        payload = dict(payload or {})
        if self.rows_path.exists():
            with self.rows_path.open(encoding="utf-8", newline="") as handle:
                if next(csv.reader(handle), []) != NBM_STATION_ARCHIVE_COLUMNS:
                    raise ValueError("legacy station archive header: use a new archive root; never rewrite evidence")
        identity = nbp_station_archive_row(payload)
        version = nbp_parser_version_number(payload.get("parser_version"))
        key = (identity.get("station_id"), identity.get("target_date"),
               identity.get("issued_at"), identity.get("payload_hash"), version)
        if key in self.existing_keys():
            with self.rows_path.open(encoding="utf-8", newline="") as handle:
                row = next(row for row in csv.DictReader(handle) if (
                    row.get("station_id"), row.get("target_date"), row.get("issued_at"),
                    row.get("payload_hash"), nbp_parser_version_number(row.get("parser_version"))
                ) == key)
            return {"schema_version": NBM_STATION_ARCHIVE_SCHEMA_VERSION,
                    "written_row_count": 0, "skipped_existing_row_count": 1,
                    "rows_path": str(self.rows_path),
                    "raw_payload_path": row.get("raw_payload_path"), "row": row}
        raw_payload = payload.get("raw_payload")
        raw_path = None
        if raw_payload is not None:
            payload_hash_value = payload.get("payload_hash") or (raw_payload or {}).get("payload_hash") or _payload_hash(raw_payload)
            station = str(payload.get("station_id") or "unknown").lower()
            target_date = str(payload.get("target_date") or "unknown")
            suffix = "" if version == 1 else f"_parser-v{version}"
            filename = f"{target_date}_{station}_{payload_hash_value[:12]}{suffix}.json"
            raw_path_obj = self.payload_dir / filename
            raw_path_obj.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(raw_payload, indent=2, sort_keys=True, default=str) + "\n"
            if raw_path_obj.exists():
                if raw_path_obj.read_text(encoding="utf-8") != serialized:
                    raise ValueError("station raw payload already exists with different provenance")
            else:
                with raw_path_obj.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(serialized)
            raw_path = str(raw_path_obj)
        row = nbp_station_archive_row(payload, raw_payload_path=raw_path)
        _append_csv(self.rows_path, NBM_STATION_ARCHIVE_COLUMNS, [row])
        return {
            "schema_version": NBM_STATION_ARCHIVE_SCHEMA_VERSION,
            "written_row_count": 1,
            "skipped_existing_row_count": 0,
            "rows_path": str(self.rows_path),
            "raw_payload_path": raw_path,
            "row": row,
        }


def _read_station_archive_rows(rows_path: Path) -> list[dict[str, str]]:
    if not rows_path.exists():
        return []
    with rows_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _resolve_raw_payload_path(rows_path: Path, raw_payload_path: str | None) -> Path | None:
    if not raw_payload_path:
        return None
    path = Path(raw_payload_path)
    if path.is_absolute():
        return path
    return rows_path.parent / path


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _same_float(left: Any, right: Any, tolerance: float = 1e-6) -> bool:
    left_number = _as_float(left)
    right_number = _as_float(right)
    if left_number is None or right_number is None:
        return left_number is None and right_number is None
    return abs(left_number - right_number) <= tolerance


def replay_nbp_station_archive_row(row: dict, *, rows_path: str | Path | None = None) -> dict:
    """Verify that one archive manifest row can be replayed from its raw NBP text."""
    row = dict(row or {})
    rows_path = Path(rows_path) if rows_path is not None else None
    issues = []
    raw_payload_path = _resolve_raw_payload_path(rows_path or Path("."), row.get("raw_payload_path"))
    raw_payload = None

    if row.get("schema_version") != NBM_STATION_ARCHIVE_SCHEMA_VERSION:
        issues.append("schema_version_mismatch")
    if row.get("source") != "nbm_probabilistic_tmax":
        issues.append("source_mismatch")
    if row.get("source_kind") != "nbp_station_text":
        issues.append("source_kind_mismatch")
    if raw_payload_path is None:
        issues.append("raw_payload_path_missing")
    elif not raw_payload_path.exists():
        issues.append("raw_payload_file_missing")
    else:
        try:
            raw_payload = json.loads(raw_payload_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            issues.append("raw_payload_not_readable_json")

    replayed = None
    if isinstance(raw_payload, dict):
        text = raw_payload.get("text")
        if not text:
            issues.append("raw_payload_text_missing")
        raw_hash = raw_payload.get("payload_hash")
        computed_hash = _payload_hash(text or "")
        if raw_hash and raw_hash != computed_hash:
            issues.append("raw_payload_hash_mismatch")
        if row.get("payload_hash") and row.get("payload_hash") != computed_hash:
            issues.append("row_payload_hash_mismatch")
        if text:
            try:
                replayed = parse_nbp_station_tmax(
                    text,
                    row.get("station_id") or raw_payload.get("station_id"),
                    row.get("target_date") or raw_payload.get("target_date"),
                    source_url=row.get("source_url") or raw_payload.get("source_url"),
                    fetched_at=row.get("fetched_at") or raw_payload.get("fetched_at"),
                    parser_version=row.get("parser_version") or NBM_NBP_PARSER_V1,
                )
            except (TypeError, ValueError):
                issues.append("raw_payload_replay_failed")
                replayed = None
        if replayed:
            try:
                raw_version = nbp_parser_version_number(raw_payload.get("parser_version"))
            except ValueError:
                raw_version = None
            if nbp_parser_version_number(row.get("parser_version")) != raw_version:
                issues.append("parser_version_mismatch")
            if nbp_parser_version_number(row.get("parser_version")) == 2:
                for key in ("period_kind", "group_index", "token_index", "cycle_age_hours"):
                    same = (_same_float(row.get(key), replayed.get(key)) if key != "period_kind"
                            else row.get(key) == replayed.get(key))
                    if not same:
                        issues.append(f"{key}_mismatch")
            if _as_bool(row.get("available")) != bool(replayed.get("available")):
                issues.append("available_mismatch")
            for key in ("station_id", "target_date", "issued_at", "valid_time_utc", "product_version"):
                if (row.get(key) or None) != (replayed.get(key) or None):
                    issues.append(f"{key}_mismatch")
            if _as_int(row.get("forecast_hour")) != _as_int(replayed.get("forecast_hour")):
                issues.append("forecast_hour_mismatch")
            for percentile in ("10", "25", "50", "75", "90"):
                if not _same_float(row.get(f"p{percentile}"), (replayed.get("percentiles") or {}).get(percentile)):
                    issues.append(f"p{percentile}_mismatch")
            for row_key, replay_key in (
                ("mean_native", "mean_native"),
                ("stddev_native", "stddev_native"),
                ("day_max_native", "day_max_native"),
                ("p10_p90_spread", "p10_p90_spread"),
                ("iqr", "iqr"),
            ):
                if not _same_float(row.get(row_key), replayed.get(replay_key)):
                    issues.append(f"{row_key}_mismatch")
            if row.get("source_url") and row.get("source_url") != (replayed.get("source_url") or replayed.get("url")):
                issues.append("source_url_mismatch")

    available = _as_bool(row.get("available"))
    replay_safe = bool(available and replayed and replayed.get("available") and not issues)
    return {
        "schema_version": NBM_STATION_ARCHIVE_SCHEMA_VERSION,
        "station_id": row.get("station_id"),
        "target_date": row.get("target_date"),
        "issued_at": row.get("issued_at"),
        "payload_hash": row.get("payload_hash"),
        "raw_payload_path": str(raw_payload_path) if raw_payload_path is not None else None,
        "available": available,
        "replay_safe": replay_safe,
        "status": "PASS" if replay_safe else "FAIL",
        "issues": sorted(set(issues)),
        "replayed_forecast_hour": replayed.get("forecast_hour") if replayed else None,
        "replayed_percentiles": (replayed or {}).get("percentiles") or {},
    }


def nbp_station_archive_summary(root: str | Path, *, max_samples: int = 5) -> dict:
    """Summarize whether a station archive can safely reconstruct NBM percentile features."""
    store = NBPStationArchiveStore(root)
    rows = _read_station_archive_rows(store.rows_path)
    checks = [
        replay_nbp_station_archive_row(row, rows_path=store.rows_path)
        for row in rows
    ]
    pass_count = sum(1 for item in checks if item.get("replay_safe"))
    fail_count = len(checks) - pass_count
    available_count = sum(1 for row in rows if _as_bool(row.get("available")))
    station_ids = sorted({str(row.get("station_id") or "") for row in rows if row.get("station_id")})
    target_dates = sorted({str(row.get("target_date") or "") for row in rows if row.get("target_date")})
    status = "PASS" if rows and available_count and fail_count == 0 else "MISSING"
    if rows and fail_count:
        status = "FAIL"
    return {
        "schema_version": NBM_STATION_ARCHIVE_SCHEMA_VERSION,
        "root": str(store.root),
        "rows_path": str(store.rows_path),
        "status": status,
        "replay_safe": status == "PASS",
        "row_count": len(rows),
        "available_row_count": available_count,
        "replay_safe_row_count": pass_count,
        "failed_row_count": fail_count,
        "station_ids": station_ids[:max_samples],
        "target_dates": target_dates[:max_samples],
        "samples": checks[:max_samples],
        "failed_samples": [item for item in checks if not item.get("replay_safe")][:max_samples],
    }


def cdf_probability_from_percentiles(percentiles: dict, threshold: float | None) -> float | None:
    if threshold is None:
        return None
    points = []
    for key, value in (percentiles or {}).items():
        if value is None:
            continue
        try:
            q = float(key) / 100.0
            points.append((float(value), q))
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda item: item[0])
    if not points:
        return None
    threshold = float(threshold)
    if threshold <= points[0][0]:
        return points[0][1]
    if threshold >= points[-1][0]:
        return points[-1][1]
    for (lower_value, lower_q), (upper_value, upper_q) in zip(points, points[1:]):
        if lower_value <= threshold <= upper_value:
            if upper_value == lower_value:
                return (lower_q + upper_q) / 2.0
            weight = (threshold - lower_value) / (upper_value - lower_value)
            return lower_q + weight * (upper_q - lower_q)
    return None


def exceedance_probability_from_percentiles(percentiles: dict, threshold: float | None) -> float | None:
    cdf = cdf_probability_from_percentiles(percentiles, threshold)
    if cdf is None:
        return None
    return max(0.0, min(1.0, 1.0 - cdf))
