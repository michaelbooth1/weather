import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from weather.paths import data_path

from zoneinfo import ZoneInfo

import requests

from weather.market.market_registry import spec_for_id
from weather.sources.daily_summary import WU_DAILY_SCHEMA_VERSION, native_bucket, native_to_c
from weather.units import round_half_up


def get_code_version():
    try:
        import os
        import subprocess
        # CREATE_NO_WINDOW: a console child spawned from a console-less parent
        # (pythonw / detached background jobs) pops a visible cmd window.
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
            creationflags=creationflags,
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


def replace_with_retry(src, dst, attempts=8, delay=0.5):
    src = Path(src)
    dst = Path(dst)
    for attempt in range(attempts):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def unlink_with_retry(path, attempts=8, delay=0.5):
    path = Path(path)
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)



TORONTO_TZ = ZoneInfo("America/Toronto")
WEATHER_COM_KEY = "e1f10a1e78da46f5b10a1e78da96f525"
CYYZ_HISTORY_ID = "CYYZ:9:CA"
STATION_ICAO = "CYYZ"
STATION_NAME = "Toronto Pearson Intl Airport"
DEFAULT_DATA_ROOT = data_path() / "wunderground" / "cyyz"
TEMPERATURE_BOUNDS = {
    "C": (-60.0, 60.0),
    "F": (-80.0, 140.0),
}
PERMANENT_NO_DATA = "permanent_no_data"
AUTH_FAILURE = "auth_failure"
RATE_LIMITED = "rate_limited"
TRANSIENT_FAILURE = "transient"
PERMANENT_NO_DATA_STATUS_CODES = {400, 404}
AUTH_FAILURE_STATUS_CODES = {401, 403}
TRANSIENT_STATUS_CODES = {408, 500, 502, 503, 504}


def redact_api_key(value):
    if value is None:
        return None
    return re.sub(r"(apiKey=)[^&\s)]+", r"\1<redacted>", str(value))


def failure_class_for_exception(exc):
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in PERMANENT_NO_DATA_STATUS_CODES:
        return PERMANENT_NO_DATA
    if status_code in AUTH_FAILURE_STATUS_CODES:
        return AUTH_FAILURE
    if status_code == 429:
        return RATE_LIMITED
    if status_code in TRANSIENT_STATUS_CODES:
        return TRANSIENT_FAILURE
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return TRANSIENT_FAILURE
    if status_code is None:
        return TRANSIENT_FAILURE
    if 500 <= int(status_code) <= 599:
        return TRANSIENT_FAILURE
    return TRANSIENT_FAILURE


def failure_class_for_error_row(row):
    failure_class = row.get("failure_class")
    if failure_class:
        return failure_class
    try:
        status_code = int(row.get("status_code"))
    except (TypeError, ValueError):
        status_code = None
    if status_code in PERMANENT_NO_DATA_STATUS_CODES:
        return PERMANENT_NO_DATA
    if status_code in AUTH_FAILURE_STATUS_CODES:
        return AUTH_FAILURE
    if status_code == 429:
        return RATE_LIMITED
    return TRANSIENT_FAILURE


def error_row_treats_as_source_unavailable(row):
    failure_class = failure_class_for_error_row(row)
    if row.get("failure_class"):
        return failure_class == PERMANENT_NO_DATA and bool(row.get("treated_as_source_unavailable"))
    return failure_class == PERMANENT_NO_DATA


class WundergroundHistoryClient:
    def __init__(self, api_key=WEATHER_COM_KEY, timeout=20, sleep_seconds=0.2,
                 history_id=CYYZ_HISTORY_ID, units="m"):
        self.api_key = api_key
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.history_id = history_id
        self.units = units  # 'm' (Celsius) or 'e' (Fahrenheit) -- the market's native unit
        self.url = (
            "https://api.weather.com/v1/location/"
            f"{history_id}/observations/historical.json"
        )

    def fetch_range(self, start_date, end_date, units=None):
        params = {
            "apiKey": self.api_key,
            "units": units or self.units,
            "startDate": start_date.strftime("%Y%m%d"),
            "endDate": end_date.strftime("%Y%m%d"),
        }
        response = requests.get(self.url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch_chunks(self, start_date, end_date, chunk_days=14, units=None):
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
                 station_name=STATION_NAME, history_id=CYYZ_HISTORY_ID,
                 tz=TORONTO_TZ, unit="C", wu_units="m"):
        self.root = Path(root)
        self.station_icao = station_icao
        self.station_name = station_name
        self.history_id = history_id
        self.unit = unit
        self.wu_units = wu_units
        # The market's local timezone -- day boundaries and intraday times must be
        # bucketed in the city's own tz, not a global one (Pacific != Eastern).
        self.tz = tz
        self.raw_root = self.root / "raw"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"
        self.error_log_path = self.root / "backfill_errors.jsonl"

    def write_payload(self, start_date, end_date, payload):
        observations = payload.get("observations", []) or []
        by_day = defaultdict(list)
        for obs in observations:
            local_dt = local_datetime(obs, self.tz)
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
                    "temperature_unit": self.unit,
                    "weather_com_units": self.wu_units,
                    "local_date": obs_date.isoformat(),
                    "fetched_range": {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    },
                    "observations": rows,
                }, handle, indent=2, sort_keys=True)

    def rebuild_normalized_files(self):
        records = list(self.iter_raw_records())
        hourly_records = []
        quarantined_records = []
        for obs in records:
            row = normalize_observation(obs, self.tz, unit=self.unit)
            if row is None:
                quarantined_records.append(obs)
                continue
            hourly_records.append(row)

        hourly_records = [
            row for row in hourly_records
            if row.get("local_date") and row.get("valid_time_utc")
        ]
        hourly_records.sort(key=lambda row: row["valid_time_utc"])

        self.write_hourly_partitions(hourly_records)
        daily_rows = summarize_daily(hourly_records)
        self.write_daily_summary(daily_rows)
        self.write_manifest(hourly_records, daily_rows, quarantined_records=quarantined_records)
        return hourly_records, daily_rows

    def iter_raw_records(self):
        for path in sorted(self.raw_root.glob("year=*/month=*/*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            yield from payload.get("observations", []) or []

    def write_hourly_partitions(self, records):
        grouped = defaultdict(list)
        for row in records:
            local_date = date.fromisoformat(row["local_date"])
            grouped[(local_date.year, local_date.month)].append(row)

        written_paths = set()
        for (year, month), rows in grouped.items():
            path = self.hourly_root / f"year={year:04d}" / f"month={month:02d}" / "observations.jsonl"
            written_paths.add(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
            replace_with_retry(tmp_path, path)

        if self.hourly_root.exists():
            for old_file in self.hourly_root.glob("year=*/month=*/observations.jsonl"):
                if old_file not in written_paths:
                    unlink_with_retry(old_file)

    def write_daily_summary(self, daily_rows):
        path = self.daily_root / "daily_summary.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "schema_version",
            "local_date",
            "temperature_unit",
            "row_count",
            "first_time",
            "last_time",
            "max_temp",
            "max_temp_native",
            "max_temp_bucket",
            "max_temp_bucket_native",
            "min_temp",
            "min_temp_native",
            "avg_temp",
            "avg_temp_native",
            "max_dewpoint",
            "max_dewpoint_native",
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

    def write_manifest(self, hourly_records, daily_rows, quarantined_records=None):
        path = self.root / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        quarantined_records = list(quarantined_records or [])
        quarantine_dates = Counter()
        quarantine_samples = []
        for obs in quarantined_records:
            local_dt = local_datetime(obs, self.tz)
            local_date = local_dt.date().isoformat() if local_dt else None
            if local_date:
                quarantine_dates[local_date] += 1
            if len(quarantine_samples) < 20:
                quarantine_samples.append({
                    "local_date": local_date,
                    "valid_time_utc": (
                        datetime.fromtimestamp(int(obs["valid_time_gmt"]), timezone.utc).isoformat()
                        if obs.get("valid_time_gmt") is not None
                        else None
                    ),
                    "obs_id": obs.get("obs_id") or obs.get("key"),
                    "temp": obs.get("temp"),
                    "dewPt": obs.get("dewPt"),
                    "heat_index": obs.get("heat_index"),
                    "wc": obs.get("wc"),
                })
        
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
            "timezone": str(self.tz),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "code_version": get_code_version(),
            "source_details": {
                "endpoint": WundergroundHistoryClient(history_id=self.history_id).url,
                "api_params": {
                    "units": self.wu_units,
                    "apiKey": redacted_key
                }
            },
            "hourly_record_count": len(hourly_records),
            "daily_record_count": len(daily_rows),
            "quarantined_raw_observations": len(quarantined_records),
            "quarantined_raw_observation_dates": dict(sorted(quarantine_dates.items())),
            "quarantined_raw_observation_samples": quarantine_samples,
            "quarantine_policy": "drop impossible WU temperature rows during normalization",
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

    def raw_dates(self):
        dates = set()
        for path in self.raw_root.glob("year=*/month=*/*.json"):
            try:
                dates.add(date.fromisoformat(path.stem))
            except ValueError:
                continue
        return dates

    def write_fetch_error(self, start_date, end_date, exc):
        response = getattr(exc, "response", None)
        failure_class = failure_class_for_exception(exc)
        payload = {
            "source": "weather.com v1 historical observations",
            "station": self.station_icao,
            "history_id": self.history_id,
            "temperature_unit": self.unit,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "status_code": getattr(response, "status_code", None),
            "failure_class": failure_class,
            "url": redact_api_key(getattr(response, "url", None)),
            "error": redact_api_key(str(exc)),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "treated_as_source_unavailable": failure_class == PERMANENT_NO_DATA,
        }
        self.error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.error_log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload

    def iter_error_rows(self):
        if not self.error_log_path.exists():
            return
        with self.error_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield row

    def unavailable_dates(self):
        dates = set()
        for row in self.iter_error_rows() or []:
            if not error_row_treats_as_source_unavailable(row):
                continue
            try:
                start = date.fromisoformat(row.get("start"))
                end = date.fromisoformat(row.get("end"))
            except (TypeError, ValueError):
                continue
            dates.update(iter_dates(start, end))
        return dates

    def recover_unavailable_errors(self, dry_run=False):
        rows = list(self.iter_error_rows() or [])
        recovered_dates = set()
        recovered_rows = 0
        rewritten_rows = []
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            updated = dict(row)
            failure_class = failure_class_for_error_row(updated)
            was_unavailable = bool(updated.get("treated_as_source_unavailable", True))
            updated["failure_class"] = failure_class
            updated["treated_as_source_unavailable"] = failure_class == PERMANENT_NO_DATA
            if failure_class != PERMANENT_NO_DATA and was_unavailable:
                recovered_rows += 1
                updated["recovery_action"] = "cleared_from_unavailable_dates"
                updated["recovered_at_utc"] = now
                try:
                    start = date.fromisoformat(updated.get("start"))
                    end = date.fromisoformat(updated.get("end"))
                except (TypeError, ValueError):
                    start = end = None
                if start and end:
                    recovered_dates.update(iter_dates(start, end))
            rewritten_rows.append(updated)
        recovered_ranges = [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in split_date_runs(recovered_dates, chunk_days=10_000)
        ]
        if rows and not dry_run:
            tmp_path = self.error_log_path.with_suffix(self.error_log_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rewritten_rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
            replace_with_retry(tmp_path, self.error_log_path)
        return {
            "station": self.station_icao,
            "history_id": self.history_id,
            "data_root": str(self.root),
            "error_rows": len(rows),
            "recovered_error_rows": recovered_rows,
            "recovered_days": len(recovered_dates),
            "recovered_ranges": recovered_ranges,
            "dry_run": bool(dry_run),
        }

    def missing_dates(self, start_date, end_date):
        existing = self.raw_dates()
        unavailable = self.unavailable_dates()
        return [
            current
            for current in iter_dates(start_date, end_date)
            if current not in existing and current not in unavailable
        ]

    def missing_ranges(self, start_date, end_date, chunk_days=14):
        return split_date_runs(self.missing_dates(start_date, end_date), chunk_days)


def plausible_temperature(value, unit):
    if value is None:
        return True
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(numeric):
        return False
    low, high = TEMPERATURE_BOUNDS.get(str(unit or "C").upper(), TEMPERATURE_BOUNDS["C"])
    return low <= numeric <= high


def normalize_observation(obs, tz=TORONTO_TZ, unit="C"):
    local_dt = local_datetime(obs, tz)
    utc_dt = datetime.fromtimestamp(
        int(obs["valid_time_gmt"]), timezone.utc
    ) if obs.get("valid_time_gmt") is not None else None
    temp = to_number(obs.get("temp"))
    dewpoint = to_number(obs.get("dewPt"))
    heat_index = to_number(obs.get("heat_index"))
    wind_chill = to_number(obs.get("wc"))
    if not all(plausible_temperature(value, unit) for value in (temp, dewpoint, heat_index, wind_chill)):
        return None

    temp_c = native_to_c(temp, unit)
    dewpoint_c = native_to_c(dewpoint, unit)
    heat_index_c = native_to_c(heat_index, unit)
    wind_chill_c = native_to_c(wind_chill, unit)

    return {
        "schema_version": "wu_hourly_native_v1",
        "station": obs.get("key") or obs.get("obs_id") or STATION_ICAO,
        "obs_id": obs.get("obs_id"),
        "obs_name": obs.get("obs_name"),
        "temperature_unit": unit,
        "valid_time_utc": utc_dt.isoformat() if utc_dt else None,
        "valid_time_local": local_dt.isoformat() if local_dt else None,
        "local_date": local_dt.date().isoformat() if local_dt else None,
        "local_time": local_dt.strftime("%H:%M") if local_dt else None,
        "minute": local_dt.minute if local_dt else None,
        "temp_native": temp,
        "dewpoint_native": dewpoint,
        "heat_index_native": heat_index,
        "wind_chill_native": wind_chill,
        "temp_c": temp_c,
        "dewpoint_c": dewpoint_c,
        "heat_index_c": heat_index_c,
        "wind_chill_c": wind_chill_c,
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
        unit = next((row.get("temperature_unit") for row in rows if row.get("temperature_unit")), "C")
        temps = [row_temp(row) for row in rows if row_temp(row) is not None]
        temps_c = [native_to_c(value, unit) for value in temps if native_to_c(value, unit) is not None]
        dewpoints = [row_dewpoint(row) for row in rows if row_dewpoint(row) is not None]
        dewpoints_c = [
            native_to_c(value, unit)
            for value in dewpoints
            if native_to_c(value, unit) is not None
        ]
        if temps:
            max_temp = max(temps)
            min_temp = min(temps)
            avg_temp = round(sum(temps) / len(temps), 2)
            max_temp_c = max(temps_c) if temps_c else None
            min_temp_c = min(temps_c) if temps_c else None
            avg_temp_c = round(sum(temps_c) / len(temps_c), 2) if temps_c else None
            max_times = [
                row["local_time"] for row in rows
                if row_temp(row) == max_temp
            ]
            max_temp_bucket = round_half_up(max_temp)
            max_temp_bucket_c = round_half_up(max_temp_c)
            max_on_hour_mark = any(
                row_temp(row) == max_temp and row.get("minute") == 0
                for row in rows
            )
        else:
            max_temp = min_temp = avg_temp = max_temp_bucket = None
            max_temp_c = min_temp_c = avg_temp_c = max_temp_bucket_c = None
            max_times = []
            max_on_hour_mark = False
        max_dewpoint = max_value(dewpoints)
        max_dewpoint_c = max_value(dewpoints_c)

        non_hourly_rows = [
            row for row in rows
            if row.get("minute") not in (None, 0)
        ]
        daily_rows.append({
            "schema_version": WU_DAILY_SCHEMA_VERSION,
            "local_date": local_date,
            "temperature_unit": unit,
            "row_count": len(rows),
            "first_time": rows[0].get("local_time"),
            "last_time": rows[-1].get("local_time"),
            "max_temp": max_temp,
            "max_temp_native": max_temp,
            "max_temp_bucket": max_temp_bucket,
            "max_temp_bucket_native": max_temp_bucket,
            "min_temp": min_temp,
            "min_temp_native": min_temp,
            "avg_temp": avg_temp,
            "avg_temp_native": avg_temp,
            "max_dewpoint": max_dewpoint,
            "max_dewpoint_native": max_dewpoint,
            "max_temp_c": max_temp_c,
            "max_temp_times": "|".join(max_times),
            "min_temp_c": min_temp_c,
            "avg_temp_c": avg_temp_c,
            "max_dewpoint_c": max_dewpoint_c,
            "max_wind_kmh": max_value(row.get("wind_speed_kmh") for row in rows),
            "max_gust_kmh": max_value(row.get("wind_gust_kmh") for row in rows),
            "max_temp_bucket_c": max_temp_bucket_c,
            "has_non_hourly_rows": bool(non_hourly_rows),
            "non_hourly_count": len(non_hourly_rows),
            "max_on_hour_mark": max_on_hour_mark,
            "condition_mode": mode(row.get("condition") for row in rows),
            "cloud_mode": mode(row.get("clouds") for row in rows),
        })
    return daily_rows


def row_temp(row):
    for key in ("temp_native", "temperature_native", "target_temp_native", "temp_c", "target_temp_c"):
        value = to_number(row.get(key))
        if value is not None:
            return value
    return None


def row_dewpoint(row):
    for key in ("dewpoint_native", "dewpoint_c"):
        value = to_number(row.get(key))
        if value is not None:
            return value
    return None


def iter_dates(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def chunk_date_range(start_date, end_date, chunk_days=14):
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def split_date_runs(dates, chunk_days=14):
    dates = sorted(set(dates))
    if not dates:
        return []
    runs = []
    run_start = prev = dates[0]
    for current in dates[1:]:
        if current == prev + timedelta(days=1):
            prev = current
            continue
        runs.extend(chunk_date_range(run_start, prev, chunk_days))
        run_start = prev = current
    runs.extend(chunk_date_range(run_start, prev, chunk_days))
    return runs


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
            bucket = native_bucket(row)
            if bucket is not None:
                bucket_counts[int(bucket)] += 1
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


def local_datetime(obs, tz=TORONTO_TZ):
    if obs.get("valid_time_gmt") is None:
        return None
    return datetime.fromtimestamp(
        int(obs["valid_time_gmt"]), timezone.utc
    ).astimezone(tz)


def to_number(value):
    if value in (None, "", "MSNG"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        tz=spec.tz,
        unit=spec.display_unit,
        wu_units=spec.wu_units,
    )


def cmd_backfill(args):
    spec, data_root = _resolve(args)
    start_date = parse_date(args.start)
    end_date = parse_date(args.end)
    client = WundergroundHistoryClient(
        sleep_seconds=args.sleep, history_id=spec.wu_history_id, units=spec.wu_units
    )
    store = _store_for(spec, data_root)
    ranges = (
        store.missing_ranges(start_date, end_date, chunk_days=args.chunk_days)
        if args.skip_existing
        else list(chunk_date_range(start_date, end_date, chunk_days=args.chunk_days))
    )
    if args.skip_existing:
        covered = (end_date - start_date).days + 1 - sum((end - start).days + 1 for start, end in ranges)
        print(f"Skip-existing enabled: {covered} raw day(s) already present; {len(ranges)} range(s) to fetch")
    if not ranges:
        print("No missing raw WU history days to fetch.")
    for chunk_start, chunk_end in ranges:
        try:
            payload = client.fetch_range(chunk_start, chunk_end, units=spec.wu_units)
        except requests.RequestException as exc:
            error = store.write_fetch_error(chunk_start, chunk_end, exc)
            print(
                f"Fetch failed {chunk_start} to {chunk_end}: "
                f"{error.get('failure_class')} HTTP {error.get('status_code')} "
                f"({error.get('error')})"
            )
            if not args.continue_on_error:
                raise
            continue
        count = len(payload.get("observations", []) or [])
        print(f"Fetched {chunk_start} to {chunk_end}: {count} rows")
        store.write_payload(chunk_start, chunk_end, payload)
        if args.sleep:
            time.sleep(args.sleep)
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


def cmd_recover_unavailable(args):
    store = _store_for(*_resolve(args))
    report = store.recover_unavailable_errors(dry_run=args.dry_run)
    print(json.dumps(report, indent=2, sort_keys=True))


def history_coverage(store, start_date=None, end_date=None):
    raw_dates = store.raw_dates()
    unavailable_dates = store.unavailable_dates()
    if start_date and end_date:
        expected = set(iter_dates(start_date, end_date))
    else:
        expected = set(raw_dates) | set(unavailable_dates)
    unavailable = sorted(expected & unavailable_dates)
    missing = sorted(expected - raw_dates - unavailable_dates)
    return {
        "station": store.station_icao,
        "history_id": store.history_id,
        "temperature_unit": store.unit,
        "data_root": str(store.root),
        "first_raw_date": min(raw_dates).isoformat() if raw_dates else None,
        "last_raw_date": max(raw_dates).isoformat() if raw_dates else None,
        "raw_days": len(raw_dates),
        "expected_days": len(expected),
        "source_unavailable_days": len(unavailable),
        "source_unavailable_ranges": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in split_date_runs(unavailable, chunk_days=10_000)
        ],
        "missing_days": len(missing),
        "missing_ranges": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in split_date_runs(missing, chunk_days=10_000)
        ],
        "manifest_exists": (store.root / "manifest.json").exists(),
        "daily_summary_exists": (store.daily_root / "daily_summary.csv").exists(),
    }


def cmd_coverage(args):
    store = _store_for(*_resolve(args))
    start_date = parse_date(args.start) if args.start else None
    end_date = parse_date(args.end) if args.end else None
    if (start_date is None) != (end_date is None):
        raise SystemExit("--start and --end must be supplied together for bounded coverage")
    print(json.dumps(history_coverage(store, start_date, end_date), indent=2, sort_keys=True))


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
    backfill.add_argument(
        "--skip-existing",
        action="store_true",
        help="Only fetch raw dates not already present; rebuild outputs afterward.",
    )
    backfill.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Record source-unavailable ranges and continue instead of aborting.",
    )
    backfill.set_defaults(func=cmd_backfill)

    rebuild = subparsers.add_parser("rebuild")
    rebuild.set_defaults(func=cmd_rebuild)

    audit = subparsers.add_parser("audit")
    audit.set_defaults(func=cmd_audit)

    coverage = subparsers.add_parser("coverage")
    coverage.add_argument("--start", default="")
    coverage.add_argument("--end", default="")
    coverage.set_defaults(func=cmd_coverage)

    recover = subparsers.add_parser("recover-unavailable")
    recover.add_argument(
        "--dry-run",
        action="store_true",
        help="Report recoverable rows without rewriting backfill_errors.jsonl.",
    )
    recover.set_defaults(func=cmd_recover_unavailable)

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
