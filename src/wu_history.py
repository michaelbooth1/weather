import argparse
import csv
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
from market_registry import spec_for_id  # noqa: E402


def get_code_version():
    try:
        import subprocess
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return f"git:{git_sha}"
    except Exception:
        try:
            hasher = hashlib.sha256()
            script_path = Path(__file__).resolve()
            with open(script_path, "rb") as f:
                hasher.update(f.read())
            return f"file_sha256:{hasher.hexdigest()[:16]}"
        except Exception:
            return "unknown"


def calculate_sha256(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()



TORONTO_TZ = ZoneInfo("America/Toronto")
WEATHER_COM_KEY = "e1f10a1e78da46f5b10a1e78da96f525"
CYYZ_HISTORY_ID = "CYYZ:9:CA"
STATION_ICAO = "CYYZ"
STATION_NAME = "Toronto Pearson Intl Airport"
DEFAULT_DATA_ROOT = Path("data") / "wunderground" / "cyyz"


class WundergroundHistoryClient:
    def __init__(self, api_key=WEATHER_COM_KEY, timeout=20, sleep_seconds=0.2,
                 history_id=CYYZ_HISTORY_ID):
        self.api_key = api_key
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.history_id = history_id
        self.url = (
            "https://api.weather.com/v1/location/"
            f"{history_id}/observations/historical.json"
        )

    def fetch_range(self, start_date, end_date, units="m"):
        params = {
            "apiKey": self.api_key,
            "units": units,
            "startDate": start_date.strftime("%Y%m%d"),
            "endDate": end_date.strftime("%Y%m%d"),
        }
        response = requests.get(self.url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch_chunks(self, start_date, end_date, chunk_days=14, units="m"):
        current = start_date
        while current <= end_date:
            chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
            payload = self.fetch_range(current, chunk_end, units=units)
            yield current, chunk_end, payload
            current = chunk_end + timedelta(days=1)
            if current <= end_date and self.sleep_seconds:
                time.sleep(self.sleep_seconds)


class WundergroundHistoryStore:
    def __init__(self, root=DEFAULT_DATA_ROOT, station_icao=STATION_ICAO,
                 station_name=STATION_NAME, history_id=CYYZ_HISTORY_ID):
        self.root = Path(root)
        self.station_icao = station_icao
        self.station_name = station_name
        self.history_id = history_id
        self.raw_root = self.root / "raw"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"

    def write_payload(self, start_date, end_date, payload):
        observations = payload.get("observations", []) or []
        by_day = defaultdict(list)
        for obs in observations:
            local_dt = local_datetime(obs)
            if local_dt:
                by_day[local_dt.date()].append(obs)

        for obs_date, rows in by_day.items():
            raw_path = self.raw_root / f"year={obs_date:%Y}" / f"month={obs_date:%m}" / f"{obs_date}.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with raw_path.open("w", encoding="utf-8") as handle:
                json.dump({
                    "station": self.station_icao,
                    "station_name": self.station_name,
                    "source": "weather.com v1 historical observations",
                    "units": "metric",
                    "local_date": obs_date.isoformat(),
                    "fetched_range": {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    },
                    "observations": rows,
                }, handle, indent=2, sort_keys=True)

    def rebuild_normalized_files(self):
        records = list(self.iter_raw_records())
        hourly_records = [normalize_observation(obs) for obs in records]
        hourly_records = [
            row for row in hourly_records
            if row.get("local_date") and row.get("valid_time_utc")
        ]
        hourly_records.sort(key=lambda row: row["valid_time_utc"])

        self.write_hourly_partitions(hourly_records)
        daily_rows = summarize_daily(hourly_records)
        self.write_daily_summary(daily_rows)
        self.write_manifest(hourly_records, daily_rows)
        return hourly_records, daily_rows

    def iter_raw_records(self):
        for path in sorted(self.raw_root.glob("year=*/month=*/*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            yield from payload.get("observations", []) or []

    def write_hourly_partitions(self, records):
        if self.hourly_root.exists():
            for old_file in self.hourly_root.glob("year=*/month=*/observations.jsonl"):
                old_file.unlink()

        grouped = defaultdict(list)
        for row in records:
            local_date = date.fromisoformat(row["local_date"])
            grouped[(local_date.year, local_date.month)].append(row)

        for (year, month), rows in grouped.items():
            path = self.hourly_root / f"year={year:04d}" / f"month={month:02d}" / "observations.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")

    def write_daily_summary(self, daily_rows):
        path = self.daily_root / "daily_summary.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "local_date",
            "row_count",
            "first_time",
            "last_time",
            "max_temp_c",
            "max_temp_times",
            "min_temp_c",
            "avg_temp_c",
            "max_dewpoint_c",
            "max_wind_kmh",
            "max_gust_kmh",
            "max_temp_bucket_c",
            "has_non_hourly_rows",
            "non_hourly_count",
            "max_on_hour_mark",
            "condition_mode",
            "cloud_mode",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(daily_rows)

    def write_manifest(self, hourly_records, daily_rows):
        path = self.root / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Redact api key for security
        api_key = WEATHER_COM_KEY
        redacted_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 8 else "..."
        
        # Scan partitions and calculate checksums and row counts
        partitions = []
        if self.hourly_root.exists():
            for p_path in sorted(self.hourly_root.glob("year=*/month=*/observations.jsonl")):
                rel_path = p_path.relative_to(self.root).as_posix()
                with p_path.open("r", encoding="utf-8") as f:
                    row_count = sum(1 for _ in f)
                sha256_val = calculate_sha256(p_path)
                partitions.append({
                    "path": rel_path,
                    "row_count": row_count,
                    "sha256": sha256_val
                })
        
        payload = {
            "station": self.station_icao,
            "station_name": self.station_name,
            "history_id": self.history_id,
            "timezone": str(TORONTO_TZ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "code_version": get_code_version(),
            "source_details": {
                "endpoint": WundergroundHistoryClient(history_id=self.history_id).url,
                "api_params": {
                    "units": "m",
                    "apiKey": redacted_key
                }
            },
            "hourly_record_count": len(hourly_records),
            "daily_record_count": len(daily_rows),
            "first_date": daily_rows[0]["local_date"] if daily_rows else None,
            "last_date": daily_rows[-1]["local_date"] if daily_rows else None,
            "layout": {
                "raw": "raw/year=YYYY/month=MM/YYYY-MM-DD.json",
                "hourly": "hourly/year=YYYY/month=MM/observations.jsonl",
                "daily": "daily/daily_summary.csv",
            },
            "partitions": partitions
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    def audit_partitions(self):
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            print(f"Error: Manifest file not found at {manifest_path}")
            return False
            
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
            
        partitions = manifest.get("partitions", [])
        if not partitions:
            print("Warning: No partitions listed in manifest.")
            return True
            
        mismatches = []
        for part in partitions:
            p_path = self.root / part["path"]
            if not p_path.exists():
                mismatches.append(f"File missing: {part['path']}")
                continue
                
            # Count rows
            with p_path.open("r", encoding="utf-8") as f:
                row_count = sum(1 for _ in f)
            if row_count != part["row_count"]:
                mismatches.append(f"Row count mismatch for {part['path']}: manifest={part['row_count']}, actual={row_count}")
                
            # Checksum
            sha256_val = calculate_sha256(p_path)
            if sha256_val != part["sha256"]:
                mismatches.append(f"SHA-256 checksum mismatch for {part['path']}: manifest={part['sha256']}, actual={sha256_val}")
                
        if mismatches:
            print("Audit FAILED with the following errors:")
            for error in mismatches:
                print(f" - {error}")
            return False
            
        print(f"Audit PASSED: Checked {len(partitions)} partitions successfully.")
        return True


def normalize_observation(obs):
    local_dt = local_datetime(obs)
    utc_dt = datetime.fromtimestamp(
        int(obs["valid_time_gmt"]), timezone.utc
    ) if obs.get("valid_time_gmt") is not None else None

    return {
        "station": obs.get("key") or obs.get("obs_id") or STATION_ICAO,
        "obs_id": obs.get("obs_id"),
        "obs_name": obs.get("obs_name"),
        "valid_time_utc": utc_dt.isoformat() if utc_dt else None,
        "valid_time_local": local_dt.isoformat() if local_dt else None,
        "local_date": local_dt.date().isoformat() if local_dt else None,
        "local_time": local_dt.strftime("%H:%M") if local_dt else None,
        "minute": local_dt.minute if local_dt else None,
        "temp_c": to_number(obs.get("temp")),
        "dewpoint_c": to_number(obs.get("dewPt")),
        "heat_index_c": to_number(obs.get("heat_index")),
        "wind_chill_c": to_number(obs.get("wc")),
        "humidity": to_number(obs.get("rh")),
        "pressure": to_number(obs.get("pressure")),
        "visibility": to_number(obs.get("vis")),
        "wind_dir_deg": to_number(obs.get("wdir")),
        "wind_cardinal": obs.get("wdir_cardinal"),
        "wind_speed_kmh": to_number(obs.get("wspd")),
        "wind_gust_kmh": to_number(obs.get("gust")),
        "precip_hourly": to_number(obs.get("precip_hrly")),
        "precip_total": to_number(obs.get("precip_total")),
        "clouds": obs.get("clds"),
        "condition": obs.get("wx_phrase"),
        "icon": obs.get("wx_icon"),
        "qualifier": obs.get("qualifier"),
    }


def summarize_daily(records):
    grouped = defaultdict(list)
    for row in records:
        grouped[row["local_date"]].append(row)

    daily_rows = []
    for local_date, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: row["valid_time_local"])
        temps = [row["temp_c"] for row in rows if row.get("temp_c") is not None]
        if temps:
            max_temp = max(temps)
            min_temp = min(temps)
            avg_temp = round(sum(temps) / len(temps), 2)
            max_times = [
                row["local_time"] for row in rows
                if row.get("temp_c") == max_temp
            ]
            max_temp_bucket = round_half_up(max_temp)
            max_on_hour_mark = any(
                row.get("temp_c") == max_temp and row.get("minute") == 0
                for row in rows
            )
        else:
            max_temp = min_temp = avg_temp = max_temp_bucket = None
            max_times = []
            max_on_hour_mark = False

        non_hourly_rows = [
            row for row in rows
            if row.get("minute") not in (None, 0)
        ]
        daily_rows.append({
            "local_date": local_date,
            "row_count": len(rows),
            "first_time": rows[0].get("local_time"),
            "last_time": rows[-1].get("local_time"),
            "max_temp_c": max_temp,
            "max_temp_times": "|".join(max_times),
            "min_temp_c": min_temp,
            "avg_temp_c": avg_temp,
            "max_dewpoint_c": max_value(row.get("dewpoint_c") for row in rows),
            "max_wind_kmh": max_value(row.get("wind_speed_kmh") for row in rows),
            "max_gust_kmh": max_value(row.get("wind_gust_kmh") for row in rows),
            "max_temp_bucket_c": max_temp_bucket,
            "has_non_hourly_rows": bool(non_hourly_rows),
            "non_hourly_count": len(non_hourly_rows),
            "max_on_hour_mark": max_on_hour_mark,
            "condition_mode": mode(row.get("condition") for row in rows),
            "cloud_mode": mode(row.get("clouds") for row in rows),
        })
    return daily_rows


def analyze_daily_summary(
    summary_path,
    target_month=5,
    target_day=27,
    exclude_dates=None,
    min_row_count=0,
):
    rows = []
    with Path(summary_path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)

    exclude_dates = set(exclude_dates or [])
    reference_year = 2000
    target_reference_date = date(reference_year, target_month, target_day)
    target_window = []
    bucket_counts = Counter()
    non_hourly_high_days = 0
    excluded_target_dates = 0
    quality_filtered_target_days = 0
    for row in rows:
        local_date = date.fromisoformat(row["local_date"])
        if abs((local_date.replace(year=reference_year) - target_reference_date).days) <= 7:
            if local_date in exclude_dates:
                excluded_target_dates += 1
                continue
            if int(row.get("row_count") or 0) < min_row_count:
                quality_filtered_target_days += 1
                continue
            target_window.append(row)
            bucket = row.get("max_temp_bucket_c")
            if bucket:
                bucket_counts[int(float(bucket))] += 1
            if row.get("max_on_hour_mark") == "False":
                non_hourly_high_days += 1

    total = len(target_window)
    bucket_probs = {
        bucket: count / total
        for bucket, count in sorted(bucket_counts.items())
    } if total else {}

    return {
        "record_count": len(rows),
        "target_window_count": total,
        "target_month": target_month,
        "target_day": target_day,
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "bucket_probabilities": bucket_probs,
        "non_hourly_high_days": non_hourly_high_days,
        "non_hourly_high_rate": non_hourly_high_days / total if total else None,
        "excluded_target_dates": excluded_target_dates,
        "quality_filtered_target_days": quality_filtered_target_days,
        "min_row_count": min_row_count,
    }


def local_datetime(obs):
    if obs.get("valid_time_gmt") is None:
        return None
    return datetime.fromtimestamp(
        int(obs["valid_time_gmt"]), timezone.utc
    ).astimezone(TORONTO_TZ)


def to_number(value):
    if value in (None, "", "MSNG"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))


def max_value(values):
    cleaned = [value for value in values if value is not None]
    return max(cleaned) if cleaned else None


def mode(values):
    cleaned = [value for value in values if value not in (None, "")]
    if not cleaned:
        return None
    return Counter(cleaned).most_common(1)[0][0]


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _resolve(args):
    """Resolve the market spec + data root from --market / --data-root."""
    spec = spec_for_id(getattr(args, "market", "toronto"))
    data_root = args.data_root or str(spec.data_root)
    return spec, data_root


def _store_for(spec, data_root):
    return WundergroundHistoryStore(
        data_root,
        station_icao=spec.icao,
        station_name=spec.city_label,
        history_id=spec.wu_history_id,
    )


def cmd_backfill(args):
    spec, data_root = _resolve(args)
    start_date = parse_date(args.start)
    end_date = parse_date(args.end)
    client = WundergroundHistoryClient(sleep_seconds=args.sleep, history_id=spec.wu_history_id)
    store = _store_for(spec, data_root)
    for chunk_start, chunk_end, payload in client.fetch_chunks(
        start_date, end_date, chunk_days=args.chunk_days
    ):
        count = len(payload.get("observations", []) or [])
        print(f"Fetched {chunk_start} to {chunk_end}: {count} rows")
        store.write_payload(chunk_start, chunk_end, payload)
    hourly, daily = store.rebuild_normalized_files()
    print(f"Wrote {len(hourly)} hourly rows and {len(daily)} daily rows")


def cmd_analyze(args):
    _spec, data_root = _resolve(args)
    summary_path = Path(data_root) / "daily" / "daily_summary.csv"
    exclude_dates = [parse_date(value) for value in args.exclude_date]
    analysis = analyze_daily_summary(
        summary_path,
        args.month,
        args.day,
        exclude_dates=exclude_dates,
        min_row_count=args.min_row_count,
    )
    print(json.dumps(analysis, indent=2, sort_keys=True))


def cmd_rebuild(args):
    store = _store_for(*_resolve(args))
    print("Rebuilding normalized hourly, daily summary, and manifest files from raw payloads...")
    hourly, daily = store.rebuild_normalized_files()
    print(f"Rebuild completed successfully. Wrote {len(hourly)} hourly rows and {len(daily)} daily rows.")


def cmd_audit(args):
    store = _store_for(*_resolve(args))
    print("Auditing partition files against manifest checksums and row counts...")
    success = store.audit_partitions()
    if not success:
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Collect and analyze Wunderground/Weather.com CYYZ history."
    )
    parser.add_argument(
        "--market",
        default="toronto",
        help="Registered market id (toronto, nyc, ...); sets the WU station + data root.",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="Override the per-market data root (defaults to the market's station folder).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser("backfill")
    backfill.add_argument("--start", required=True, help="YYYY-MM-DD")
    backfill.add_argument("--end", required=True, help="YYYY-MM-DD")
    backfill.add_argument("--chunk-days", type=int, default=14)
    backfill.add_argument("--sleep", type=float, default=0.2)
    backfill.set_defaults(func=cmd_backfill)

    rebuild = subparsers.add_parser("rebuild")
    rebuild.set_defaults(func=cmd_rebuild)

    audit = subparsers.add_parser("audit")
    audit.set_defaults(func=cmd_audit)

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--month", type=int, default=5)
    analyze.add_argument("--day", type=int, default=27)
    analyze.add_argument(
        "--exclude-date",
        action="append",
        default=[],
        help="YYYY-MM-DD date to exclude from the target seasonal window.",
    )
    analyze.add_argument("--min-row-count", type=int, default=0)
    analyze.set_defaults(func=cmd_analyze)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
