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
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import data_path

import requests

from weather.sources.daily_summary import native_bucket, native_high, round_half_up
from weather.sources.historical_schema import (
    c_to_native,
    hourly_record,
    quality_counts,
    summarize_daily,
    to_float,
    write_daily_csv,
    write_jsonl_partitions,
    write_manifest,
)
from weather.market.market_registry import all_specs, spec_for_id
from weather.sources.wu_history import get_code_version


SOURCE = "metar_asos"
DEFAULT_ROOT = data_path() / "metar"
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


def chunk_date_ranges(start_date, end_date, chunk_days=None):
    start_date = parse_date(start_date)
    end_date = parse_date(end_date)
    if not chunk_days or chunk_days <= 0:
        return [(start_date, end_date)]
    ranges = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return ranges


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
    RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, timeout=60, max_attempts=3, retry_sleep=10):
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.retry_sleep = retry_sleep

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
        for attempt in range(1, self.max_attempts + 1):
            response = requests.get(IEM_ASOS_URL, params=params, timeout=self.timeout)
            try:
                response.raise_for_status()
                return response.text
            except requests.HTTPError:
                if response.status_code not in self.RETRY_STATUS_CODES or attempt == self.max_attempts:
                    raise
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_seconds = float(retry_after) if retry_after else None
                except ValueError:
                    sleep_seconds = None
                if sleep_seconds is None:
                    sleep_seconds = self.retry_sleep * attempt
                time.sleep(max(0.0, sleep_seconds))
        return ""


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

    def backfill(
        self,
        start_date,
        end_date,
        skip_existing=False,
        client=None,
        chunk_days=None,
        sleep_seconds=0.0,
    ):
        start_date = parse_date(start_date)
        end_date = parse_date(end_date)
        client = client or MetarClient()
        self.raw_root.mkdir(parents=True, exist_ok=True)
        for chunk_start, chunk_end in chunk_date_ranges(start_date, end_date, chunk_days):
            path = self.raw_path(chunk_start, chunk_end)
            if skip_existing and path.exists():
                continue
            text = client.fetch(self.spec.icao, chunk_start, chunk_end)
            path.write_text(text, encoding="utf-8")
            if sleep_seconds:
                time.sleep(sleep_seconds)
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
    client = MetarClient(
        timeout=args.timeout,
        max_attempts=args.retry_attempts,
        retry_sleep=args.retry_sleep,
    )
    result = store.backfill(
        args.start,
        args.end,
        skip_existing=args.skip_existing,
        client=client,
        chunk_days=args.chunk_days,
        sleep_seconds=args.sleep,
    )
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


# Item 5: which intraday cutoff hours can trust METAR-so-far as a settlement
# floor. Afternoon hours are where the live METAR sanity-check role matters.
CUTOFF_MISS_HOURS = tuple(range(9, 20))


def read_hourly_by_date(store):
    """Group normalized hourly METAR temps by local_date into sorted
    (minute_of_day, temp_native) tuples, read from the JSONL partitions."""
    by_date = defaultdict(list)
    for path in sorted(store.hourly_root.glob("year=*/month=*/observations.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                local_date = row.get("local_date")
                temp = to_float(row.get("temp_native"))
                local_time = row.get("local_time")
                if not local_date or temp is None or not local_time:
                    continue
                try:
                    hh, mm = str(local_time).split(":")
                    minute_of_day = int(hh) * 60 + int(mm)
                except (ValueError, AttributeError):
                    continue
                by_date[local_date].append((minute_of_day, temp))
    for local_date in by_date:
        by_date[local_date].sort()
    return by_date


def cutoff_miss_analysis(spec, store, wu_rows, cutoff_hours=CUTOFF_MISS_HOURS):
    """Quantify how often the METAR max-so-far has NOT yet reached the WU final
    settlement bucket, by intraday cutoff hour (item 5). ``wu_rows`` is the WU
    daily summary {local_date: {high, bucket, ...}} -- the settlement-source
    truth proxy. For each cutoff hour and each day with both sources, classify
    METAR-so-far vs the WU FINAL bucket as miss (below), match (equal), or
    exceed (above), and report the rates plus the mean still-to-go gap. The
    first hour whose match+exceed rate reaches 0.5 is when METAR-so-far becomes
    a usable floor on a typical day."""
    hourly = read_hourly_by_date(store)
    matched_dates = sorted(
        d for d in hourly
        if d in wu_rows and wu_rows[d].get("bucket") is not None
    )
    per_cutoff = {}
    reaches_final_by_hour = None
    for hour in cutoff_hours:
        cutoff_min = hour * 60
        miss = match = exceed = n = 0
        gaps = []
        for local_date in matched_dates:
            obs = [temp for minute, temp in hourly[local_date] if minute <= cutoff_min]
            if not obs:
                continue
            n += 1
            metar_bucket = round_half_up(max(obs))
            final_bucket = int(wu_rows[local_date]["bucket"])
            gaps.append(final_bucket - metar_bucket)
            diff = metar_bucket - final_bucket
            if diff < 0:
                miss += 1
            elif diff == 0:
                match += 1
            else:
                exceed += 1
        reached_rate = (match + exceed) / n if n else None
        per_cutoff[hour] = {
            "n": n,
            "miss_rate": miss / n if n else None,
            "match_rate": match / n if n else None,
            "exceed_rate": exceed / n if n else None,
            "reached_rate": reached_rate,
            "mean_gap_to_final": mean(gaps) if gaps else None,
        }
        if reaches_final_by_hour is None and reached_rate is not None and reached_rate >= 0.5:
            reaches_final_by_hour = hour
    return {
        "market_id": spec.id,
        "station": spec.icao,
        "unit": spec.display_unit,
        "matched_days": len(matched_dates),
        "reaches_final_by_hour": reaches_final_by_hour,
        "per_cutoff": per_cutoff,
    }


def cutoff_miss_report_lines(result):
    lines = [
        f"### {result['market_id']} (`{result['station']}`, {result['unit']})",
        "",
        f"Matched days: `{result['matched_days']}`. "
        f"METAR-so-far reaches the WU final bucket on >=50% of days by hour: "
        f"`{result['reaches_final_by_hour'] if result['reaches_final_by_hour'] is not None else '-'}`.",
        "",
        "| Cutoff | N | Miss (below) | Match | Exceed | Reached | Mean gap to final |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for hour, stats in sorted(result["per_cutoff"].items()):
        lines.append(
            f"| {hour:02d}:00 | {stats['n']} | {fmt_num(stats['miss_rate'])} | "
            f"{fmt_num(stats['match_rate'])} | {fmt_num(stats['exceed_rate'])} | "
            f"{fmt_num(stats['reached_rate'])} | {fmt_num(stats['mean_gap_to_final'], 2)} |"
        )
    lines.append("")
    return lines


def command_cutoff_miss(args):
    specs = all_specs() if getattr(args, "all_markets", False) else [spec_for_id(args.market)]
    results = []
    for spec in specs:
        store = MetarStore(spec, root=args.data_root or None)
        wu_root = Path(args.wu_root) if args.wu_root else data_path() / "wunderground" / spec.icao.lower()
        wu_rows = read_daily_summary(wu_root / "daily" / "daily_summary.csv")
        results.append(cutoff_miss_analysis(spec, store, wu_rows))

    lines = [
        "# METAR/ASOS Settlement-Miss By Intraday Cutoff Hour",
        "",
        "How often the METAR max-so-far has not yet reached the WU final "
        "settlement bucket, by cutoff hour. Low matched-day counts mean the "
        "rates are directional only -- deepen METAR history (item 29/39) for "
        "statistical power.",
        "",
    ]
    for result in results:
        lines.extend(cutoff_miss_report_lines(result))

    if args.out:
        out_path = Path(args.out)
    elif getattr(args, "all_markets", False):
        out_path = data_path() / "backtest" / "metar_cutoff_miss_report.md"
    else:
        out_path = MetarStore(specs[0], root=args.data_root or None).root / "analysis" / "cutoff_miss_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"Wrote cutoff-miss report to {out_path}")


def command_compare(args):
    spec = spec_for_id(args.market)
    store = MetarStore(spec, root=args.data_root or None)
    wu_root = Path(args.wu_root) if args.wu_root else data_path() / "wunderground" / spec.icao.lower()
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
    backfill.add_argument("--chunk-days", type=int, default=0)
    backfill.add_argument("--sleep", type=float, default=0.0)
    backfill.add_argument("--timeout", type=float, default=60)
    backfill.add_argument("--retry-attempts", type=int, default=3)
    backfill.add_argument("--retry-sleep", type=float, default=10.0)
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

    cutoff = sub.add_parser(
        "cutoff-miss",
        help="Quantify how often METAR-so-far misses the WU final bucket by cutoff hour (item 5).",
    )
    cutoff.add_argument("--wu-root", default="")
    cutoff.add_argument("--out", default="")
    cutoff.add_argument("--all-markets", action="store_true",
                        help="Run every registered market into one fleet report.")
    cutoff.set_defaults(func=command_cutoff_miss)

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
