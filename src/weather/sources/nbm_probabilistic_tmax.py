"""NBM probabilistic maximum-temperature text guidance.

The NBP station text bulletin carries QMD daily max/min temperature
percentiles without requiring per-market GRIB extraction. GRIB/QMD native
exceedance grids are tracked separately by roadmap item 190.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable


NBM_PROB_TMAX_SCHEMA_VERSION = "nbm_probabilistic_tmax_v0.1"
NBM_NBP_BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"
NBM_NBP_PERCENTILE_ROWS = {
    "TXNP1": 10,
    "TXNP2": 25,
    "TXNP5": 50,
    "TXNP7": 75,
    "TXNP9": 90,
}
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
]


def nbp_text_url(run_time: datetime, base_url: str = NBM_NBP_BASE_URL) -> str:
    run_time = run_time.astimezone(timezone.utc)
    day = run_time.strftime("%Y%m%d")
    hour = run_time.strftime("%H")
    return f"{base_url}/blend.{day}/{hour}/text/blend_nbptx.t{hour}z"


def nbp_cycle_candidates(now_utc: datetime | None = None, hours_back: int = 24) -> list[datetime]:
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cursor = now_utc.replace(minute=0, second=0, microsecond=0)
    return [cursor - timedelta(hours=offset) for offset in range(max(0, int(hours_back)) + 1)]


def _payload_hash(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="replace")).hexdigest()


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


def _slot_index_for_target(fhr_pairs: Iterable[tuple[float | None, float | None]], issue_time: datetime, target_date: date) -> int | None:
    for index, pair in enumerate(fhr_pairs):
        max_fhr = pair[0]
        if max_fhr is None:
            continue
        valid_time = issue_time + timedelta(hours=float(max_fhr))
        max_target_date = (valid_time - timedelta(days=1)).date()
        if max_target_date == target_date:
            return index
    return None


def parse_nbp_station_tmax(text: str, station_id: str, target_date: date | str, source_url: str | None = None, fetched_at: str | None = None) -> dict:
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
            "payload_hash": _payload_hash(text),
            "fetched_at": fetched_at,
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
            "payload_hash": _payload_hash(text),
            "fetched_at": fetched_at,
        }

    rows = {_row_code(line): _parse_pair_row(line) for line in block if _row_code(line)}
    fhr_pairs = rows.get("FHR") or []
    slot_index = _slot_index_for_target(fhr_pairs, issue_time, target_date)
    if slot_index is None:
        return {
            "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
            "available": False,
            "station_id": station_id,
            "issued_at": issue_time.isoformat(),
            "target_date": target_date.isoformat(),
            "reason": "target_date_not_in_nbp_max_temperature_window",
            "source_url": source_url,
            "payload_hash": _payload_hash(text),
            "fetched_at": fetched_at,
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
        "payload_hash": _payload_hash(text),
        "fetched_at": fetched_at,
        "historical_archive_available": False,
        "exceedance_grid_available": False,
        "exceedance_status": "native_qmd_grid_or_band_edge_extraction_pending",
        "live_only_fields": list(NBM_PROB_TMAX_FEATURE_COLUMNS),
        "raw_station_block": "\n".join(block),
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
