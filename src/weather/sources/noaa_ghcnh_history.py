"""NOAA GHCNh hourly historical weather adapter.

GHCNh is NOAA/NCEI's hourly successor to the older ISD/Global Hourly line. This
module stores raw station-year PSV files and rebuilds them into the shared
native-unit hourly/daily schema.
"""
import argparse
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from historical_schema import (  # noqa: E402
    c_to_native,
    hourly_record,
    quality_counts,
    summarize_daily,
    to_float,
    write_daily_csv,
    write_jsonl_partitions,
    write_manifest,
)
from market_registry import all_specs, spec_for_id  # noqa: E402
from wu_history import get_code_version  # noqa: E402


SOURCE = "noaa_ghcnh"
STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/doc/ghcnh-station-list.csv"
)
YEAR_FILE_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/access/by-year/{year}/psv/GHCNh_{station_id}_{year}.psv"
)
DEFAULT_ROOT = Path("data") / "noaa_ghcnh"


def distance2(row, spec):
    lat = to_float(row.get("LATITUDE"))
    lon = to_float(row.get("LONGITUDE"))
    if lat is None or lon is None:
        return float("inf")
    return (lat - spec.lat) ** 2 + (lon - spec.lon) ** 2


def country_hint(spec):
    text = str(getattr(spec, "wu_history_id", ""))
    if ":CA" in text:
        return "CA"
    if ":US" in text:
        return "US"
    return ""


def parse_station_list(text):
    return list(csv.DictReader(io.StringIO(text)))


def resolve_station(spec, station_rows):
    matches = [row for row in station_rows if (row.get("ICAO") or "").upper() == spec.icao.upper()]
    if matches:
        return min(matches, key=lambda row: distance2(row, spec))
    hint = country_hint(spec)
    nearby = [
        row for row in station_rows
        if (not hint or row.get("ISO_CODE") == hint) and distance2(row, spec) <= 0.05
    ]
    if not nearby:
        return None
    return min(nearby, key=lambda row: (
        0 if row.get("WMO_ID") else 1,
        distance2(row, spec),
        row.get("GHCN_ID") or "",
    ))


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def first_present(row, names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def row_quality(row):
    fields = [
        "temperature_Quality_Code",
        "dew_point_temperature_Quality_Code",
        "station_level_pressure_Quality_Code",
        "sea_level_pressure_Quality_Code",
        "wind_speed_Quality_Code",
    ]
    return ",".join(f"{field}={row.get(field)}" for field in fields if row.get(field))


def normalize_psv(text, spec, station):
    records = []
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    station_id = station.get("GHCN_ID") or station.get("ID") or ""
    station_name = station.get("NAME") or station.get("Station_name") or spec.city_label
    for row in reader:
        dt = parse_datetime(row.get("DATE"))
        if not dt:
            continue
        local_dt = dt.replace(tzinfo=timezone.utc).astimezone(spec.tz)
        temp_c = to_float(row.get("temperature"))
        if temp_c is None:
            continue
        dew_c = to_float(row.get("dew_point_temperature"))
        records.append(hourly_record(
            source=SOURCE,
            spec=spec,
            station=station_id,
            station_name=station_name,
            valid_time_local=local_dt,
            temp_native=c_to_native(temp_c, spec.display_unit),
            dewpoint_native=c_to_native(dew_c, spec.display_unit),
            humidity=first_present(row, ("relative_humidity", "humidity")),
            pressure_hpa=row.get("station_level_pressure"),
            sea_level_pressure_hpa=row.get("sea_level_pressure"),
            wind_dir_deg=row.get("wind_direction"),
            wind_speed_kmh=row.get("wind_speed"),
            wind_gust_kmh=row.get("wind_gust"),
            condition=row.get("present_weather"),
            clouds=row.get("cloud_coverage"),
            source_report_type=row.get("temperature_Report_Type"),
            source_quality=row_quality(row),
        ))
    return records


class GHCNHClient:
    def __init__(self, timeout=30, sleep_seconds=0.2):
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds

    def fetch_station_list(self):
        response = requests.get(STATION_LIST_URL, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def fetch_year(self, station_id, year):
        url = YEAR_FILE_URL.format(station_id=station_id, year=year)
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text


class GHCNHStore:
    def __init__(self, spec, root=None):
        self.spec = spec
        self.root = Path(root) if root else DEFAULT_ROOT / spec.icao.lower()
        self.raw_root = self.root / "raw"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"
        self.station_path = self.root / "station.json"

    def raw_path(self, station_id, year):
        return self.raw_root / f"year={year}" / f"GHCNh_{station_id}_{year}.psv"

    def write_station(self, station):
        self.station_path.parent.mkdir(parents=True, exist_ok=True)
        self.station_path.write_text(json.dumps(station, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def read_station(self):
        if not self.station_path.exists():
            return None
        return json.loads(self.station_path.read_text(encoding="utf-8"))

    def write_year(self, station_id, year, text):
        path = self.raw_path(station_id, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def raw_years(self):
        years = set()
        for path in self.raw_root.glob("year=*/*.psv"):
            try:
                years.add(int(path.parent.name.split("=", 1)[1]))
            except (IndexError, ValueError):
                continue
        return years

    def missing_years(self, start_year, end_year):
        existing = self.raw_years()
        return [year for year in range(start_year, end_year + 1) if year not in existing]

    def iter_raw_files(self):
        return sorted(self.raw_root.glob("year=*/*.psv"))

    def rebuild(self):
        station = self.read_station() or {}
        records = []
        for path in self.iter_raw_files():
            records.extend(normalize_psv(path.read_text(encoding="utf-8"), self.spec, station))
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
                "station": station,
                "station_list_url": STATION_LIST_URL,
                "year_file_url_template": YEAR_FILE_URL,
                "quality_counts": quality_counts(records),
            },
        )
        return records, daily

    def coverage(self, start_year=None, end_year=None):
        raw_years = self.raw_years()
        if start_year is not None and end_year is not None:
            expected = set(range(start_year, end_year + 1))
        else:
            expected = raw_years
        missing = sorted(expected - raw_years)
        return {
            "source": SOURCE,
            "market_id": self.spec.id,
            "station": self.spec.icao,
            "data_root": str(self.root),
            "raw_years": sorted(raw_years),
            "expected_years": sorted(expected),
            "missing_years": missing,
            "station_resolved": self.read_station() is not None,
            "daily_summary_exists": (self.daily_root / "daily_summary.csv").exists(),
            "manifest_exists": (self.root / "manifest.json").exists(),
        }


def resolve_and_store_station(spec, store, client):
    station_rows = parse_station_list(client.fetch_station_list())
    station = resolve_station(spec, station_rows)
    if not station:
        raise SystemExit(f"No GHCNh station found for ICAO {spec.icao}")
    store.write_station(station)
    return station


def cmd_station(args):
    spec = spec_for_id(args.market)
    store = GHCNHStore(spec, args.data_root)
    station = resolve_and_store_station(spec, store, GHCNHClient(timeout=args.timeout))
    print(json.dumps(station, indent=2, sort_keys=True))


def cmd_backfill(args):
    spec = spec_for_id(args.market)
    store = GHCNHStore(spec, args.data_root)
    client = GHCNHClient(timeout=args.timeout, sleep_seconds=args.sleep)
    station = store.read_station() or resolve_and_store_station(spec, store, client)
    station_id = station.get("GHCN_ID")
    years = (
        store.missing_years(args.start_year, args.end_year)
        if args.skip_existing
        else list(range(args.start_year, args.end_year + 1))
    )
    print(f"{spec.id}: {len(years)} GHCNh year(s) to fetch for {station_id}")
    for year in years:
        text = client.fetch_year(station_id, year)
        path = store.write_year(station_id, year, text)
        print(f"Fetched {year}: {len(text)} bytes -> {path}")
        if args.sleep:
            time.sleep(args.sleep)
    records, daily = store.rebuild()
    print(f"Rebuilt {len(records)} hourly rows and {len(daily)} daily rows")


def cmd_rebuild(args):
    spec = spec_for_id(args.market)
    records, daily = GHCNHStore(spec, args.data_root).rebuild()
    print(f"Rebuilt {len(records)} hourly rows and {len(daily)} daily rows")


def cmd_coverage(args):
    spec = spec_for_id(args.market)
    start_year = args.start_year if args.start_year else None
    end_year = args.end_year if args.end_year else None
    print(json.dumps(GHCNHStore(spec, args.data_root).coverage(start_year, end_year), indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Backfill NOAA GHCNh hourly history.")
    parser.add_argument("--market", default="toronto")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--timeout", type=float, default=30)
    sub = parser.add_subparsers(dest="command", required=True)

    station = sub.add_parser("station")
    station.set_defaults(func=cmd_station)

    backfill = sub.add_parser("backfill")
    backfill.add_argument("--start-year", type=int, required=True)
    backfill.add_argument("--end-year", type=int, required=True)
    backfill.add_argument("--sleep", type=float, default=0.2)
    backfill.add_argument("--skip-existing", action="store_true")
    backfill.set_defaults(func=cmd_backfill)

    rebuild = sub.add_parser("rebuild")
    rebuild.set_defaults(func=cmd_rebuild)

    coverage = sub.add_parser("coverage")
    coverage.add_argument("--start-year", type=int, default=0)
    coverage.add_argument("--end-year", type=int, default=0)
    coverage.set_defaults(func=cmd_coverage)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
