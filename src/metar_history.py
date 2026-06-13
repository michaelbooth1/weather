"""Registry-driven METAR/ASOS historical adapter.

The legacy version of this module only downloaded Toronto CYYZ data. Item 30
needs METAR/ASOS as a reusable redundant observation stream for every registered
market, so this module now stores IEM ASOS raw CSVs and rebuilds them into the
shared native-unit hourly/daily schema used by the other historical sources.
"""
import argparse
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta, timezone
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
from daily_summary import native_bucket, native_high  # noqa: E402
from market_registry import all_specs, spec_for_id  # noqa: E402
from wu_history import get_code_version  # noqa: E402


SOURCE = "metar_asos"
DEFAULT_ROOT = Path("data") / "metar"
IEM_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
DATA_FIELDS = (
    "tmpc",
    "dwpc",
    "relh",
    "drct",
    "sknt",
    "gust",
    "alti",
    "mslp",
    "vsby",
    "skyc1",
    "skyc2",
    "skyc3",
    "wxcodes",
)


def parse_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_valid_utc(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_present(row, names):
    for name in names:
        value = row.get(name)
        if value not in (None, "", "M", "null"):
            return value
    return None


def knots_to_kmh(value):
    value = to_float(value)
    return None if value is None else round(value * 1.852, 2)


def inches_hg_to_hpa(value):
    value = to_float(value)
    return None if value is None else round(value * 33.8638866667, 2)


def cloud_text(row):
    layers = [row.get(name) for name in ("skyc1", "skyc2", "skyc3")]
    return "|".join(layer for layer in layers if layer not in (None, "", "M", "null"))


def normalize_csv(text, spec):
    records = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        utc_dt = parse_valid_utc(row.get("valid"))
        temp_c = to_float(row.get("tmpc"))
        if utc_dt is None or temp_c is None:
            continue
        local_dt = utc_dt.astimezone(spec.tz)
        dew_c = to_float(row.get("dwpc"))
        records.append(hourly_record(
            source=SOURCE,
            spec=spec,
            station=spec.icao,
            station_name=row.get("station") or spec.icao,
            valid_time_local=local_dt,
            temp_native=c_to_native(temp_c, spec.display_unit),
            dewpoint_native=c_to_native(dew_c, spec.display_unit),
            humidity=row.get("relh"),
            pressure_hpa=inches_hg_to_hpa(row.get("alti")),
            sea_level_pressure_hpa=row.get("mslp"),
            wind_dir_deg=row.get("drct"),
            wind_speed_kmh=knots_to_kmh(row.get("sknt")),
            wind_gust_kmh=knots_to_kmh(row.get("gust")),
            condition=row.get("wxcodes"),
            clouds=cloud_text(row),
            source_report_type="METAR/ASOS",
            source_quality=row.get("metar") or row.get("raw") or "",
        ))
    records.sort(key=lambda item: item["valid_time_utc"])
    return records


def dedupe_records(records):
    by_key = {}
    for row in records:
        key = (row.get("station"), row.get("valid_time_utc"))
        by_key[key] = row
    return [by_key[key] for key in sorted(by_key, key=lambda item: item[1] or "")]


def read_daily_summary(path):
    path = Path(path)
    if not path.exists():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date = row.get("local_date")
            if not local_date:
                continue
            high = native_high(row)
            bucket = native_bucket(row)
            if high is None and bucket is None:
                continue
            rows[local_date] = {
                "high": high,
                "bucket": bucket,
                "times": row.get("max_temp_times") or "",
            }
    return rows


def fmt_num(value, digits=3):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


class MetarClient:
    def __init__(self, timeout=60):
        self.timeout = timeout

    def fetch(self, station, start_date, end_date):
        start_date = parse_date(start_date)
        end_date = parse_date(end_date)
        # IEM ASOS date params are UTC-day based. Fetching one extra UTC day
        # ensures the requested local end date is present for western timezones.
        request_end = end_date + timedelta(days=1)
        params = [
            ("station", station.upper()),
            ("year1", start_date.year),
            ("month1", start_date.month),
            ("day1", start_date.day),
            ("year2", request_end.year),
            ("month2", request_end.month),
            ("day2", request_end.day),
            ("tz", "Etc/UTC"),
            ("format", "onlycomma"),
            ("latlon", "no"),
            ("missing", "M"),
            ("trace", "T"),
        ]
        params.extend(("data", field) for field in DATA_FIELDS)
        response = requests.get(IEM_ASOS_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.text


class MetarStore:
    def __init__(self, spec, root=None):
        self.spec = spec
        self.root = Path(root) if root else DEFAULT_ROOT / spec.icao.lower()
        self.raw_root = self.root / "raw"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"

    def raw_path(self, start_date, end_date):
        start_date = parse_date(start_date)
        end_date = parse_date(end_date)
        return self.raw_root / f"asos_{start_date.isoformat()}_{end_date.isoformat()}.csv"

    def raw_files(self):
        return sorted(self.raw_root.glob("asos_*.csv"))

    def backfill(self, start_date, end_date, skip_existing=False, client=None):
        start_date = parse_date(start_date)
        end_date = parse_date(end_date)
        client = client or MetarClient()
        path = self.raw_path(start_date, end_date)
        if not (skip_existing and path.exists()):
            self.raw_root.mkdir(parents=True, exist_ok=True)
            text = client.fetch(self.spec.icao, start_date, end_date)
            path.write_text(text, encoding="utf-8")
        return self.rebuild()

    def rebuild(self):
        records = []
        for path in self.raw_files():
            records.extend(normalize_csv(path.read_text(encoding="utf-8"), self.spec))
        records = dedupe_records(records)
        write_jsonl_partitions(self.hourly_root, records)
        daily_rows = summarize_daily(records)
        write_daily_csv(self.daily_root / "daily_summary.csv", daily_rows)
        manifest = write_manifest(
            self.root / "manifest.json",
            SOURCE,
            self.spec,
            self.raw_root,
            self.hourly_root,
            daily_rows,
            metadata={
                "code_version": get_code_version(),
                "raw_file_count": len(self.raw_files()),
                "quality_counts": quality_counts(records),
                "provider": "IEM ASOS",
            },
        )
        return {
            "records": len(records),
            "daily_rows": len(daily_rows),
            "manifest": manifest,
        }

    def daily_dates(self):
        path = self.daily_root / "daily_summary.csv"
        if not path.exists():
            return set()
        with path.open("r", encoding="utf-8", newline="") as handle:
            return {row.get("local_date") for row in csv.DictReader(handle) if row.get("local_date")}

    def coverage(self, start_date, end_date):
        start_date = parse_date(start_date)
        end_date = parse_date(end_date)
        dates = self.daily_dates()
        expected = []
        current = start_date
        while current <= end_date:
            expected.append(current.isoformat())
            current = date.fromordinal(current.toordinal() + 1)
        missing = [day for day in expected if day not in dates]
        return {
            "source": SOURCE,
            "market_id": self.spec.id,
            "station": self.spec.icao,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "expected_days": len(expected),
            "covered_days": len(expected) - len(missing),
            "missing_days": len(missing),
            "missing": missing,
        }


def run_legacy_toronto_backfill():
    spec = spec_for_id("toronto")
    result = MetarStore(spec).backfill(date(1982, 5, 20), date(2025, 6, 3), skip_existing=True)
    print(
        f"{spec.id}: wrote {result['records']} METAR hourly rows and "
        f"{result['daily_rows']} daily rows"
    )


def command_backfill(args):
    spec = spec_for_id(args.market)
    store = MetarStore(spec, root=args.data_root or None)
    result = store.backfill(args.start, args.end, skip_existing=args.skip_existing)
    print(
        f"{spec.id}: wrote {result['records']} METAR hourly rows and "
        f"{result['daily_rows']} daily rows"
    )


def command_rebuild(args):
    spec = spec_for_id(args.market)
    store = MetarStore(spec, root=args.data_root or None)
    result = store.rebuild()
    print(
        f"{spec.id}: rebuilt {result['records']} METAR hourly rows and "
        f"{result['daily_rows']} daily rows"
    )


def command_coverage(args):
    spec = spec_for_id(args.market)
    store = MetarStore(spec, root=args.data_root or None)
    print(json.dumps(store.coverage(args.start, args.end), indent=2, sort_keys=True))


def command_compare(args):
    spec = spec_for_id(args.market)
    store = MetarStore(spec, root=args.data_root or None)
    wu_root = Path(args.wu_root) if args.wu_root else Path("data") / "wunderground" / spec.icao.lower()
    wu_rows = read_daily_summary(wu_root / "daily" / "daily_summary.csv")
    metar_rows = read_daily_summary(store.daily_root / "daily_summary.csv")
    compared = []
    for local_date in sorted(set(wu_rows) & set(metar_rows)):
        wu = wu_rows[local_date]
        metar = metar_rows[local_date]
        if wu["high"] is None or metar["high"] is None:
            continue
        bucket_diff = None
        if wu["bucket"] is not None and metar["bucket"] is not None:
            bucket_diff = int(metar["bucket"]) - int(wu["bucket"])
        compared.append({
            "local_date": local_date,
            "metar_high": metar["high"],
            "metar_bucket": metar["bucket"],
            "metar_times": metar["times"],
            "wu_high": wu["high"],
            "wu_bucket": wu["bucket"],
            "wu_times": wu["times"],
            "temp_diff": metar["high"] - wu["high"],
            "bucket_diff": bucket_diff,
        })
    diffs = [row["temp_diff"] for row in compared]
    bucket_diffs = [row["bucket_diff"] for row in compared if row["bucket_diff"] is not None]
    summary = {
        "market_id": spec.id,
        "station": spec.icao,
        "unit": spec.display_unit,
        "n": len(compared),
        "bias_metar_minus_wu": mean(diffs),
        "mae_vs_wu": mean([abs(diff) for diff in diffs]),
        "exact_bucket_match_rate": (
            sum(1 for diff in bucket_diffs if diff == 0) / len(bucket_diffs)
            if bucket_diffs else None
        ),
        "metar_exceeds_wu_rate": sum(1 for diff in diffs if diff > 0) / len(diffs) if diffs else None,
        "metar_misses_wu_rate": sum(1 for diff in diffs if diff < 0) / len(diffs) if diffs else None,
    }
    out_path = Path(args.out) if args.out else store.root / "analysis" / "comparison_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    largest = sorted(compared, key=lambda row: abs(row["temp_diff"]), reverse=True)[:15]
    lines = [
        "# METAR/ASOS vs WU Daily High Comparison",
        "",
        f"Market: `{spec.id}`",
        f"Station: `{spec.icao}`",
        f"Unit: `{spec.display_unit}`",
        f"Matched days: `{summary['n']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| Bias METAR - WU | {fmt_num(summary['bias_metar_minus_wu'])} |",
        f"| MAE vs WU | {fmt_num(summary['mae_vs_wu'])} |",
        f"| Exact bucket match | {fmt_num(summary['exact_bucket_match_rate'])} |",
        f"| METAR exceeds WU | {fmt_num(summary['metar_exceeds_wu_rate'])} |",
        f"| METAR misses WU | {fmt_num(summary['metar_misses_wu_rate'])} |",
        "",
        "## Largest Differences",
        "",
        "| Date | METAR High | WU High | Diff | METAR Bucket | WU Bucket | METAR Times | WU Times |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in largest:
        lines.append(
            f"| {row['local_date']} | {fmt_num(row['metar_high'], 1)} | "
            f"{fmt_num(row['wu_high'], 1)} | {fmt_num(row['temp_diff'], 1)} | "
            f"{row['metar_bucket']} | {row['wu_bucket']} | "
            f"{row['metar_times']} | {row['wu_times']} |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Wrote comparison report to {out_path}")


def build_parser():
    parser = argparse.ArgumentParser(description="Backfill and rebuild METAR/ASOS history.")
    parser.add_argument("--market", default="toronto", choices=[spec.id for spec in all_specs()])
    parser.add_argument("--data-root", default="")
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill")
    backfill.add_argument("--start", required=True)
    backfill.add_argument("--end", required=True)
    backfill.add_argument("--skip-existing", action="store_true")
    backfill.set_defaults(func=command_backfill)

    rebuild = sub.add_parser("rebuild")
    rebuild.set_defaults(func=command_rebuild)

    coverage = sub.add_parser("coverage")
    coverage.add_argument("--start", required=True)
    coverage.add_argument("--end", required=True)
    coverage.set_defaults(func=command_coverage)

    compare = sub.add_parser("compare")
    compare.add_argument("--wu-root", default="")
    compare.add_argument("--out", default="")
    compare.set_defaults(func=command_compare)

    return parser


def main(argv=None):
    if argv is None and len(sys.argv) == 1:
        run_legacy_toronto_backfill()
        return
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
