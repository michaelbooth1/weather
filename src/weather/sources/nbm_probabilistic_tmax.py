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


NBM_PROB_TMAX_SCHEMA_VERSION = "nbm_probabilistic_tmax_v0.1"
NBM_STATION_ARCHIVE_SCHEMA_VERSION = "nbm_probabilistic_tmax_station_archive_v0.1"
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
    "nbm_prob_tmax_physical_valid_flag",
    "nbm_prob_tmax_impossible_flag",
    "nbm_prob_tmax_floor_gap",
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


def nbp_raw_payload(text: str, station_id: str, target_date: date | str, source_url: str | None = None, fetched_at: str | None = None) -> dict:
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    return {
        "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
        "source": "nbm_probabilistic_tmax",
        "source_kind": "nbp_station_text",
        "station_id": str(station_id or "").upper().strip(),
        "target_date": target_date.isoformat(),
        "source_url": source_url,
        "fetched_at": fetched_at,
        "payload_hash": _payload_hash(text),
        "text": str(text or ""),
    }


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
        "live_only_fields": list(NBM_PROB_TMAX_FEATURE_COLUMNS),
        "raw_station_block": "\n".join(block),
        "raw_payload": nbp_raw_payload(text, station_id, target_date, source_url=source_url, fetched_at=fetched_at),
    }


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

    def existing_keys(self) -> set[tuple[str | None, str | None, str | None, str | None]]:
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
                ))
        return keys

    def write_payload(self, payload: dict) -> dict:
        payload = dict(payload or {})
        raw_payload = payload.get("raw_payload")
        raw_path = None
        if raw_payload is not None:
            payload_hash_value = payload.get("payload_hash") or (raw_payload or {}).get("payload_hash") or _payload_hash(raw_payload)
            station = str(payload.get("station_id") or "unknown").lower()
            target_date = str(payload.get("target_date") or "unknown")
            filename = f"{target_date}_{station}_{payload_hash_value[:12]}.json"
            raw_path_obj = self.payload_dir / filename
            raw_path_obj.parent.mkdir(parents=True, exist_ok=True)
            raw_path_obj.write_text(json.dumps(raw_payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            raw_path = str(raw_path_obj)
        row = nbp_station_archive_row(payload, raw_payload_path=raw_path)
        key = (row.get("station_id"), row.get("target_date"), row.get("issued_at"), row.get("payload_hash"))
        if key in self.existing_keys():
            return {
                "schema_version": NBM_STATION_ARCHIVE_SCHEMA_VERSION,
                "written_row_count": 0,
                "skipped_existing_row_count": 1,
                "rows_path": str(self.rows_path),
                "raw_payload_path": raw_path,
                "row": row,
            }
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
                )
            except (TypeError, ValueError):
                issues.append("raw_payload_replay_failed")
                replayed = None
        if replayed:
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
