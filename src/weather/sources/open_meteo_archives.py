"""Open-Meteo source archive helpers for replay-safe backfills.

These helpers normalize payloads from Open-Meteo's historical/replay-compatible
APIs without making any promotion or reporting-gate decisions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from weather.paths import data_path
from weather.market.market_registry import spec_for_id
from weather.sources.forecast_history import HIST_FORECAST_URL
from weather.units import to_float


OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION = "open_meteo_global_model_archive_v0.1"
OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION = "open_meteo_air_quality_archive_v0.1"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_GLOBAL_MODEL_MEMBERS = (
    "ecmwf_ifs025",
    "ecmwf_aifs025",
    "ncep_aigfs025",
    "gfs_graphcast025",
)
OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS = (
    "pm2_5",
    "pm10",
    "aerosol_optical_depth",
    "dust",
    "us_aqi",
    "european_aqi",
)

GLOBAL_MODEL_HOURLY_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_url",
    "target_date",
    "valid_time",
    "minute_of_day",
    "temperature_unit",
    "ecmwf_ifs025_temp_native",
    "ecmwf_aifs025_temp_native",
    "ncep_aigfs025_temp_native",
    "gfs_graphcast025_temp_native",
    "model_temp_median",
    "model_temp_spread",
    "payload_hash",
    "fetched_at",
]
GLOBAL_MODEL_DAILY_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_url",
    "target_date",
    "temperature_unit",
    "ecmwf_ifs025_high_native",
    "ecmwf_aifs025_high_native",
    "ncep_aigfs025_high_native",
    "gfs_graphcast025_high_native",
    "day_max_native",
    "day_high_spread",
    "hourly_rows",
    "payload_hash",
    "fetched_at",
]
AIR_QUALITY_HOURLY_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_url",
    "target_date",
    "valid_time",
    "minute_of_day",
    "pm2_5",
    "pm10",
    "aerosol_optical_depth",
    "dust",
    "us_aqi",
    "european_aqi",
    "payload_hash",
    "fetched_at",
]


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iter_dates(start_date, end_date):
    current = parse_date(start_date)
    end = parse_date(end_date)
    while current <= end:
        yield current
        current += timedelta(days=1)


def chunk_date_range(start_date, end_date, chunk_days):
    current = parse_date(start_date)
    end = parse_date(end_date)
    chunk_days = max(1, int(chunk_days))
    ranges = []
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return ranges


def split_ranges(missing_dates, chunk_days):
    missing_dates = sorted(set(missing_dates))
    if not missing_dates:
        return []
    ranges = []
    run_start = prev = missing_dates[0]
    for current in missing_dates[1:]:
        if current == prev + timedelta(days=1):
            prev = current
            continue
        ranges.extend(chunk_date_range(run_start, prev, chunk_days))
        run_start = prev = current
    ranges.extend(chunk_date_range(run_start, prev, chunk_days))
    return ranges


def payload_hash(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _array_get(mapping, key, index):
    values = (mapping or {}).get(key) or []
    if index >= len(values):
        return None
    return values[index]


def _local_datetime(raw_time, spec):
    parsed = datetime.fromisoformat(str(raw_time))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=spec.tz)
    return parsed.astimezone(spec.tz)


def _median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def build_open_meteo_global_model_archive_params(
    spec,
    start_date,
    end_date,
    model_members=OPEN_METEO_GLOBAL_MODEL_MEMBERS,
):
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "start_date": parse_date(start_date).isoformat(),
        "end_date": parse_date(end_date).isoformat(),
        "hourly": "temperature_2m",
        "temperature_unit": spec.om_temperature_unit,
        "timezone": spec.timezone,
        "models": ",".join(model_members),
    }


def build_open_meteo_air_quality_archive_params(
    spec,
    start_date,
    end_date,
    fields=OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS,
):
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "start_date": parse_date(start_date).isoformat(),
        "end_date": parse_date(end_date).isoformat(),
        "hourly": ",".join(fields),
        "timezone": spec.timezone,
    }


def fetch_open_meteo_global_model_archive_payload(spec, start_date, end_date, timeout=30, session=None):
    client = session or requests
    response = client.get(
        HIST_FORECAST_URL,
        params=build_open_meteo_global_model_archive_params(spec, start_date, end_date),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def fetch_open_meteo_air_quality_archive_payload(spec, start_date, end_date, timeout=30, session=None):
    client = session or requests
    response = client.get(
        OPEN_METEO_AIR_QUALITY_URL,
        params=build_open_meteo_air_quality_archive_params(spec, start_date, end_date),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def normalize_open_meteo_global_model_archive(
    payload,
    spec,
    source_url=HIST_FORECAST_URL,
    fetched_at=None,
    model_members=OPEN_METEO_GLOBAL_MODEL_MEMBERS,
):
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    hash_value = payload_hash(payload or {})
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    rows = []
    grouped_highs = defaultdict(lambda: {model: [] for model in model_members})
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        try:
            local_dt = _local_datetime(raw_time, spec)
        except ValueError:
            continue
        model_values = {}
        values = []
        for model in model_members:
            value = to_float(_array_get(hourly, f"temperature_2m_{model}", index))
            if value is None and len(model_members) == 1:
                value = to_float(_array_get(hourly, "temperature_2m", index))
            model_values[model] = value
            if value is not None:
                values.append(value)
                grouped_highs[local_dt.date().isoformat()][model].append(value)
        row = {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_global_models",
            "source_url": source_url,
            "target_date": local_dt.date().isoformat(),
            "valid_time": local_dt.isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "temperature_unit": spec.display_unit,
            "model_temp_median": _median(values),
            "model_temp_spread": max(values) - min(values) if len(values) >= 2 else None,
            "payload_hash": hash_value,
            "fetched_at": fetched_at,
        }
        for model, value in model_values.items():
            row[f"{model}_temp_native"] = value
        rows.append(row)
    daily_rows = []
    for target_date, highs_by_model in sorted(grouped_highs.items()):
        model_highs = {
            model: max(values) if values else None
            for model, values in highs_by_model.items()
        }
        high_values = [value for value in model_highs.values() if value is not None]
        daily = {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_global_models",
            "source_url": source_url,
            "target_date": target_date,
            "temperature_unit": spec.display_unit,
            "day_max_native": _median(high_values),
            "day_high_spread": max(high_values) - min(high_values) if len(high_values) >= 2 else None,
            "hourly_rows": sum(1 for row in rows if row.get("target_date") == target_date),
            "payload_hash": hash_value,
            "fetched_at": fetched_at,
        }
        for model, value in model_highs.items():
            daily[f"{model}_high_native"] = value
        daily_rows.append(daily)
    return {
        "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
        "source": "open_meteo_global_models",
        "market": spec.id,
        "station": spec.icao,
        "source_url": source_url,
        "payload_hash": hash_value,
        "fetched_at": fetched_at,
        "model_members": list(model_members),
        "hourly_rows": rows,
        "daily_rows": daily_rows,
        "raw_payload": payload,
    }


def normalize_open_meteo_air_quality_archive(
    payload,
    spec,
    source_url=OPEN_METEO_AIR_QUALITY_URL,
    fetched_at=None,
    fields=OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS,
):
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    hash_value = payload_hash(payload or {})
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    rows = []
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        try:
            local_dt = _local_datetime(raw_time, spec)
        except ValueError:
            continue
        row = {
            "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_air_quality",
            "source_url": source_url,
            "target_date": local_dt.date().isoformat(),
            "valid_time": local_dt.isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "payload_hash": hash_value,
            "fetched_at": fetched_at,
        }
        for field in fields:
            row[field] = to_float(_array_get(hourly, field, index))
        rows.append(row)
    return {
        "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
        "source": "open_meteo_air_quality",
        "market": spec.id,
        "station": spec.icao,
        "source_url": source_url,
        "payload_hash": hash_value,
        "fetched_at": fetched_at,
        "hourly_fields": list(fields),
        "hourly_rows": rows,
        "raw_payload": payload,
    }


def _write_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _row_sort_key(row):
    return (
        str(row.get("target_date") or ""),
        int(float(row.get("minute_of_day") or 0)),
        str(row.get("valid_time") or ""),
    )


def _merge_rows(existing, incoming, key_fields):
    merged = {}
    for row in list(existing or []) + list(incoming or []):
        key = tuple(str(row.get(field) or "") for field in key_fields)
        if not any(key):
            continue
        merged[key] = row
    return sorted(merged.values(), key=_row_sort_key)


class OpenMeteoArchiveStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_path() / "open_meteo_archives"

    def market_root(self, spec):
        return self.root / spec.icao.lower()

    def air_quality_root(self, spec):
        return self.market_root(spec) / "air_quality"

    def global_model_root(self, spec):
        return self.market_root(spec) / "global_models"

    def air_quality_hourly_path(self, spec):
        return self.air_quality_root(spec) / "hourly.csv"

    def global_model_hourly_path(self, spec):
        return self.global_model_root(spec) / "hourly.csv"

    def global_model_daily_path(self, spec):
        return self.global_model_root(spec) / "daily.csv"

    def read_air_quality_hourly_rows(self, spec):
        return _read_csv(self.air_quality_hourly_path(spec))

    def read_global_model_hourly_rows(self, spec):
        return _read_csv(self.global_model_hourly_path(spec))

    def read_global_model_daily_rows(self, spec):
        return _read_csv(self.global_model_daily_path(spec))

    def air_quality_covered_dates(self, spec):
        dates = set()
        for row in self.read_air_quality_hourly_rows(spec):
            value = row.get("target_date")
            if not value:
                continue
            try:
                dates.add(parse_date(value))
            except ValueError:
                continue
        return dates

    def global_model_covered_dates(self, spec):
        dates = set()
        for row in self.read_global_model_daily_rows(spec):
            value = row.get("target_date")
            if not value:
                continue
            try:
                dates.add(parse_date(value))
            except ValueError:
                continue
        if dates:
            return dates
        for row in self.read_global_model_hourly_rows(spec):
            value = row.get("target_date")
            if not value:
                continue
            try:
                dates.add(parse_date(value))
            except ValueError:
                continue
        return dates

    def air_quality_missing_ranges(self, spec, start_date, end_date, chunk_days=31):
        expected = set(iter_dates(start_date, end_date))
        missing = expected - self.air_quality_covered_dates(spec)
        return split_ranges(missing, chunk_days)

    def global_model_missing_ranges(self, spec, start_date, end_date, chunk_days=31):
        expected = set(iter_dates(start_date, end_date))
        missing = expected - self.global_model_covered_dates(spec)
        return split_ranges(missing, chunk_days)

    def air_quality_coverage(self, spec, start_date=None, end_date=None):
        covered = self.air_quality_covered_dates(spec)
        if start_date and end_date:
            expected = set(iter_dates(start_date, end_date))
        else:
            expected = covered
        missing = sorted(expected - covered)
        covered_in_window = sorted(covered & expected) if expected else sorted(covered)
        return {
            "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
            "source": "open_meteo_air_quality",
            "market_id": spec.id,
            "station": spec.icao,
            "data_root": str(self.air_quality_root(spec)),
            "hourly_path": str(self.air_quality_hourly_path(spec)),
            "expected_days": len(expected),
            "covered_days": len(covered_in_window),
            "missing_days": len(missing),
            "first_covered_date": min(covered).isoformat() if covered else None,
            "last_covered_date": max(covered).isoformat() if covered else None,
            "missing_ranges": [
                {"start": start.isoformat(), "end": end.isoformat()}
                for start, end in split_ranges(missing, chunk_days=10_000)
            ],
            "hourly_rows": len(self.read_air_quality_hourly_rows(spec)),
            "hourly_exists": self.air_quality_hourly_path(spec).exists(),
            "raw_payload_count": len(list((self.air_quality_root(spec) / "raw_payloads").glob("*.json"))),
        }

    def global_model_coverage(self, spec, start_date=None, end_date=None):
        covered = self.global_model_covered_dates(spec)
        if start_date and end_date:
            expected = set(iter_dates(start_date, end_date))
        else:
            expected = covered
        missing = sorted(expected - covered)
        covered_in_window = sorted(covered & expected) if expected else sorted(covered)
        return {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "source": "open_meteo_global_models",
            "market_id": spec.id,
            "station": spec.icao,
            "data_root": str(self.global_model_root(spec)),
            "hourly_path": str(self.global_model_hourly_path(spec)),
            "daily_path": str(self.global_model_daily_path(spec)),
            "expected_days": len(expected),
            "covered_days": len(covered_in_window),
            "missing_days": len(missing),
            "first_covered_date": min(covered).isoformat() if covered else None,
            "last_covered_date": max(covered).isoformat() if covered else None,
            "missing_ranges": [
                {"start": start.isoformat(), "end": end.isoformat()}
                for start, end in split_ranges(missing, chunk_days=10_000)
            ],
            "hourly_rows": len(self.read_global_model_hourly_rows(spec)),
            "daily_rows": len(self.read_global_model_daily_rows(spec)),
            "hourly_exists": self.global_model_hourly_path(spec).exists(),
            "daily_exists": self.global_model_daily_path(spec).exists(),
            "raw_payload_count": len(list((self.global_model_root(spec) / "raw_payloads").glob("*.json"))),
        }

    def write_global_model_archive(self, normalized, spec):
        root = self.global_model_root(spec)
        hourly_path = self.global_model_hourly_path(spec)
        daily_path = self.global_model_daily_path(spec)
        payload_path = root / "raw_payloads" / f"{normalized['payload_hash']}.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(json.dumps(normalized.get("raw_payload") or {}, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        hourly_rows = _merge_rows(
            _read_csv(hourly_path),
            normalized.get("hourly_rows") or [],
            ("market", "station", "source", "valid_time"),
        )
        daily_rows = _merge_rows(
            _read_csv(daily_path),
            normalized.get("daily_rows") or [],
            ("market", "station", "source", "target_date"),
        )
        _write_csv(hourly_path, GLOBAL_MODEL_HOURLY_COLUMNS, hourly_rows)
        _write_csv(daily_path, GLOBAL_MODEL_DAILY_COLUMNS, daily_rows)
        return {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "hourly_rows": len(hourly_rows),
            "daily_rows": len(daily_rows),
            "new_hourly_rows": len(normalized.get("hourly_rows") or []),
            "new_daily_rows": len(normalized.get("daily_rows") or []),
            "hourly_path": str(hourly_path),
            "daily_path": str(daily_path),
            "raw_payload_path": str(payload_path),
        }

    def write_air_quality_archive(self, normalized, spec):
        root = self.air_quality_root(spec)
        hourly_path = self.air_quality_hourly_path(spec)
        payload_path = root / "raw_payloads" / f"{normalized['payload_hash']}.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(json.dumps(normalized.get("raw_payload") or {}, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        rows = _merge_rows(
            _read_csv(hourly_path),
            normalized.get("hourly_rows") or [],
            ("market", "station", "source", "valid_time"),
        )
        _write_csv(hourly_path, AIR_QUALITY_HOURLY_COLUMNS, rows)
        return {
            "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
            "hourly_rows": len(rows),
            "new_hourly_rows": len(normalized.get("hourly_rows") or []),
            "hourly_path": str(hourly_path),
            "raw_payload_path": str(payload_path),
        }


def cmd_air_quality_backfill(args):
    spec = spec_for_id(args.market)
    store = OpenMeteoArchiveStore(args.data_root)
    start = parse_date(args.start)
    end = parse_date(args.end)
    ranges = (
        store.air_quality_missing_ranges(spec, start, end, args.chunk_days)
        if args.skip_existing
        else chunk_date_range(start, end, args.chunk_days)
    )
    print(f"{spec.id}: {len(ranges)} Open-Meteo Air Quality range(s) to fetch")
    for range_start, range_end in ranges:
        payload = fetch_open_meteo_air_quality_archive_payload(
            spec,
            range_start,
            range_end,
            timeout=args.timeout,
        )
        normalized = normalize_open_meteo_air_quality_archive(payload, spec)
        result = store.write_air_quality_archive(normalized, spec)
        print(
            f"Fetched {range_start} to {range_end}: "
            f"{result['new_hourly_rows']} new row(s), {result['hourly_rows']} archived"
        )
        if args.sleep:
            time.sleep(args.sleep)


def cmd_air_quality_coverage(args):
    spec = spec_for_id(args.market)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    if (start is None) != (end is None):
        raise SystemExit("--start and --end must be supplied together for bounded coverage")
    payload = OpenMeteoArchiveStore(args.data_root).air_quality_coverage(spec, start, end)
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_global_models_backfill(args):
    spec = spec_for_id(args.market)
    store = OpenMeteoArchiveStore(args.data_root)
    start = parse_date(args.start)
    end = parse_date(args.end)
    ranges = (
        store.global_model_missing_ranges(spec, start, end, args.chunk_days)
        if args.skip_existing
        else chunk_date_range(start, end, args.chunk_days)
    )
    print(f"{spec.id}: {len(ranges)} Open-Meteo global-model range(s) to fetch")
    for range_start, range_end in ranges:
        payload = fetch_open_meteo_global_model_archive_payload(
            spec,
            range_start,
            range_end,
            timeout=args.timeout,
        )
        normalized = normalize_open_meteo_global_model_archive(payload, spec)
        result = store.write_global_model_archive(normalized, spec)
        print(
            f"Fetched {range_start} to {range_end}: "
            f"{result['new_hourly_rows']} new hourly row(s), "
            f"{result['daily_rows']} archived day(s)"
        )
        if args.sleep:
            time.sleep(args.sleep)


def cmd_global_models_coverage(args):
    spec = spec_for_id(args.market)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    if (start is None) != (end is None):
        raise SystemExit("--start and --end must be supplied together for bounded coverage")
    payload = OpenMeteoArchiveStore(args.data_root).global_model_coverage(spec, start, end)
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Backfill replay-safe Open-Meteo source archives.")
    parser.add_argument("--market", default="toronto")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--timeout", type=float, default=30)
    sub = parser.add_subparsers(dest="archive", required=True)

    air_quality = sub.add_parser("air-quality", help="Open-Meteo Air Quality archive")
    aq_sub = air_quality.add_subparsers(dest="command", required=True)

    aq_backfill = aq_sub.add_parser("backfill")
    aq_backfill.add_argument("--start", required=True)
    aq_backfill.add_argument("--end", required=True)
    aq_backfill.add_argument("--chunk-days", type=int, default=31)
    aq_backfill.add_argument("--sleep", type=float, default=0.2)
    aq_backfill.add_argument("--skip-existing", action="store_true")
    aq_backfill.set_defaults(func=cmd_air_quality_backfill)

    aq_coverage = aq_sub.add_parser("coverage")
    aq_coverage.add_argument("--start", default="")
    aq_coverage.add_argument("--end", default="")
    aq_coverage.set_defaults(func=cmd_air_quality_coverage)

    global_models = sub.add_parser("global-models", help="Open-Meteo ECMWF/ML-NWP global model archive")
    gm_sub = global_models.add_subparsers(dest="command", required=True)

    gm_backfill = gm_sub.add_parser("backfill")
    gm_backfill.add_argument("--start", required=True)
    gm_backfill.add_argument("--end", required=True)
    gm_backfill.add_argument("--chunk-days", type=int, default=31)
    gm_backfill.add_argument("--sleep", type=float, default=0.2)
    gm_backfill.add_argument("--skip-existing", action="store_true")
    gm_backfill.set_defaults(func=cmd_global_models_backfill)

    gm_coverage = gm_sub.add_parser("coverage")
    gm_coverage.add_argument("--start", default="")
    gm_coverage.add_argument("--end", default="")
    gm_coverage.set_defaults(func=cmd_global_models_coverage)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
