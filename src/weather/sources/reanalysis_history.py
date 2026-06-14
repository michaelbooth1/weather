"""Open-Meteo archive / ERA5-style reanalysis historical weather adapter."""
import argparse
import csv
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from historical_schema import (  # noqa: E402
    hourly_record,
    quality_counts,
    summarize_daily,
    to_float,
    write_daily_csv,
    write_jsonl_partitions,
    write_manifest,
)
from market_registry import spec_for_id  # noqa: E402
from wu_history import get_code_version, parse_date  # noqa: E402


SOURCE = "open_meteo_era5_reanalysis"
DEFAULT_ROOT = Path("data") / "reanalysis"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "pressure_msl",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cloud_cover",
)


def iter_dates(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def chunk_date_range(start_date, end_date, chunk_days=31):
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def parse_local_datetime(value, tzinfo):
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tzinfo)
    return dt.astimezone(tzinfo)


def normalize_payload(payload, spec):
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    records = []
    for index, value in enumerate(times):
        local_dt = parse_local_datetime(value, spec.tz)
        if not local_dt:
            continue
        temp = value_at(hourly, "temperature_2m", index)
        if temp is None:
            continue
        records.append(hourly_record(
            source=SOURCE,
            spec=spec,
            station=f"era5:{spec.lat:.4f},{spec.lon:.4f}",
            station_name=f"{spec.city_label} ERA5 grid",
            valid_time_local=local_dt,
            temp_native=temp,
            dewpoint_native=value_at(hourly, "dew_point_2m", index),
            humidity=value_at(hourly, "relative_humidity_2m", index),
            pressure_hpa=value_at(hourly, "pressure_msl", index),
            sea_level_pressure_hpa=value_at(hourly, "pressure_msl", index),
            wind_dir_deg=value_at(hourly, "wind_direction_10m", index),
            wind_speed_kmh=value_at(hourly, "wind_speed_10m", index),
            wind_gust_kmh=value_at(hourly, "wind_gusts_10m", index),
            clouds=value_at(hourly, "cloud_cover", index),
            source_report_type=payload.get("generationtime_ms"),
            source_quality="reanalysis_grid",
        ))
    return records


def value_at(mapping, key, index):
    values = mapping.get(key) or []
    if index >= len(values):
        return None
    return to_float(values[index])


class ReanalysisClient:
    def __init__(self, timeout=30, sleep_seconds=0.2):
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds

    def fetch_range(self, spec, start_date, end_date):
        params = {
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "hourly": ",".join(HOURLY_VARIABLES),
            "temperature_unit": "fahrenheit" if spec.display_unit == "F" else "celsius",
            "wind_speed_unit": "kmh",
            "timezone": spec.timezone,
            "models": "era5",
        }
        response = requests.get(ARCHIVE_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


class ReanalysisStore:
    def __init__(self, spec, root=None):
        self.spec = spec
        self.root = Path(root) if root else DEFAULT_ROOT / spec.icao.lower()
        self.raw_root = self.root / "raw"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"

    def raw_path(self, start_date, end_date):
        return self.raw_root / f"year={start_date:%Y}" / f"{start_date}_{end_date}.json"

    def write_payload(self, start_date, end_date, payload):
        path = self.raw_path(start_date, end_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def raw_covered_dates(self):
        dates = set()
        for path in self.raw_root.glob("year=*/*.json"):
            try:
                start_text, end_text = path.stem.split("_", 1)
                start = date.fromisoformat(start_text)
                end = date.fromisoformat(end_text)
            except ValueError:
                continue
            dates.update(iter_dates(start, end))
        return dates

    def normalized_daily_dates(self):
        path = self.daily_root / "daily_summary.csv"
        dates = set()
        if not path.exists():
            return dates
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    dates.add(date.fromisoformat(row.get("local_date", "")))
                except ValueError:
                    continue
        return dates

    def covered_dates_for_queue(self):
        normalized = self.normalized_daily_dates()
        return normalized if normalized else self.raw_covered_dates()

    def missing_ranges(self, start_date, end_date, chunk_days=31):
        covered = self.covered_dates_for_queue()
        missing = [day for day in iter_dates(start_date, end_date) if day not in covered]
        if not missing:
            return []
        ranges = []
        run_start = prev = missing[0]
        for current in missing[1:]:
            if current == prev + timedelta(days=1):
                prev = current
                continue
            ranges.extend(chunk_date_range(run_start, prev, chunk_days))
            run_start = prev = current
        ranges.extend(chunk_date_range(run_start, prev, chunk_days))
        return ranges

    def iter_raw_payloads(self):
        for path in sorted(self.raw_root.glob("year=*/*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))

    def rebuild(self):
        records = []
        for payload in self.iter_raw_payloads():
            records.extend(normalize_payload(payload, self.spec))
        records.sort(key=lambda row: row["valid_time_utc"])
        write_jsonl_partitions(self.hourly_root, records)
        daily = summarize_daily(records)
        write_daily_csv(self.daily_root / "daily_summary.csv", daily)
        write_manifest(
            self.root / "manifest.json",
            SOURCE,
            self.spec,
            self.raw_root,
            self.hourly_root,
            daily,
            metadata={
                "code_version": get_code_version(),
                "archive_url": ARCHIVE_URL,
                "hourly_variables": HOURLY_VARIABLES,
                "model": "era5",
                "quality_counts": quality_counts(records),
            },
        )
        return records, daily

    def coverage(self, start_date=None, end_date=None):
        raw_covered = self.raw_covered_dates()
        normalized_covered = self.normalized_daily_dates()
        covered = normalized_covered
        if start_date and end_date:
            expected = set(iter_dates(start_date, end_date))
        else:
            expected = covered or raw_covered
        missing = sorted(expected - covered)
        raw_missing = sorted(expected - raw_covered)
        return {
            "source": SOURCE,
            "market_id": self.spec.id,
            "station": f"era5:{self.spec.lat:.4f},{self.spec.lon:.4f}",
            "data_root": str(self.root),
            "covered_days": len(covered),
            "raw_covered_days": len(raw_covered),
            "normalized_daily_days": len(normalized_covered),
            "expected_days": len(expected),
            "missing_days": len(missing),
            "raw_missing_days": len(raw_missing),
            "first_raw_date": min(raw_covered).isoformat() if raw_covered else None,
            "last_raw_date": max(raw_covered).isoformat() if raw_covered else None,
            "first_normalized_date": min(normalized_covered).isoformat() if normalized_covered else None,
            "last_normalized_date": max(normalized_covered).isoformat() if normalized_covered else None,
            "daily_summary_exists": (self.daily_root / "daily_summary.csv").exists(),
            "manifest_exists": (self.root / "manifest.json").exists(),
        }


def cmd_backfill(args):
    spec = spec_for_id(args.market)
    store = ReanalysisStore(spec, args.data_root)
    client = ReanalysisClient(timeout=args.timeout, sleep_seconds=args.sleep)
    start = parse_date(args.start)
    end = parse_date(args.end)
    ranges = (
        store.missing_ranges(start, end, args.chunk_days)
        if args.skip_existing
        else list(chunk_date_range(start, end, args.chunk_days))
    )
    print(f"{spec.id}: {len(ranges)} reanalysis range(s) to fetch")
    for start_date, end_date in ranges:
        payload = client.fetch_range(spec, start_date, end_date)
        path = store.write_payload(start_date, end_date, payload)
        print(f"Fetched {start_date} to {end_date}: {path}")
        if args.sleep:
            time.sleep(args.sleep)
    records, daily = store.rebuild()
    print(f"Rebuilt {len(records)} hourly rows and {len(daily)} daily rows")


def cmd_rebuild(args):
    spec = spec_for_id(args.market)
    records, daily = ReanalysisStore(spec, args.data_root).rebuild()
    print(f"Rebuilt {len(records)} hourly rows and {len(daily)} daily rows")


def cmd_coverage(args):
    spec = spec_for_id(args.market)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    print(json.dumps(ReanalysisStore(spec, args.data_root).coverage(start, end), indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Backfill Open-Meteo ERA5-style reanalysis history.")
    parser.add_argument("--market", default="toronto")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--timeout", type=float, default=30)
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill")
    backfill.add_argument("--start", required=True)
    backfill.add_argument("--end", required=True)
    backfill.add_argument("--chunk-days", type=int, default=31)
    backfill.add_argument("--sleep", type=float, default=0.2)
    backfill.add_argument("--skip-existing", action="store_true")
    backfill.set_defaults(func=cmd_backfill)

    rebuild = sub.add_parser("rebuild")
    rebuild.set_defaults(func=cmd_rebuild)

    coverage = sub.add_parser("coverage")
    coverage.add_argument("--start", default="")
    coverage.add_argument("--end", default="")
    coverage.set_defaults(func=cmd_coverage)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
