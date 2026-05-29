import os
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import config_for_date

DEFAULT_DATA_ROOT = Path("data") / "wunderground" / "cyyz"
DEFAULT_MARKET_CONFIG = config_for_date()
TARGET_MONTH = DEFAULT_MARKET_CONFIG.target_date.month
TARGET_DAY = DEFAULT_MARKET_CONFIG.target_date.day
WINDOW_DAYS = 7
MIN_HOURLY_OBS = 18

def audit_historical_data(data_root=DEFAULT_DATA_ROOT, target_month=None, target_day=None):
    summary_path = data_root / "daily" / "daily_summary.csv"
    if not summary_path.exists():
        print(f"Error: Daily summary file not found at {summary_path}")
        return False

    target_month = target_month or TARGET_MONTH
    target_day = target_day or TARGET_DAY
    print(f"Auditing historical weather data at: {data_root.resolve()}")
    print(f"Target window: {target_month:02d}-{target_day:02d} +/- {WINDOW_DAYS} days")
    
    # 1. Collect target dates in seasonal window across years
    # Let's check from year 2000 to 2025
    years = list(range(2000, 2026))
    target_dates = set()
    for year in years:
        target_ref = date(year, target_month, target_day)
        for offset in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
            target_dates.add(target_ref + timedelta(days=offset))

    # 2. Read daily summary file
    summary_dates = {}
    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date_str = row.get("local_date")
            if local_date_str:
                local_date = date.fromisoformat(local_date_str)
                summary_dates[local_date] = {
                    "row_count": int(row.get("row_count") or 0),
                    "max_temp_c": float(row.get("max_temp_c") or 0.0) if row.get("max_temp_c") else None,
                    "max_temp_bucket_c": int(row.get("max_temp_bucket_c") or 0) if row.get("max_temp_bucket_c") else None
                }

    # 3. Check for missing days
    missing_days = []
    sparse_days = []
    impossible_values = []
    duplicate_timestamps = []

    for d in sorted(target_dates):
        if d not in summary_dates:
            missing_days.append(d)
        else:
            stats = summary_dates[d]
            if stats["row_count"] < MIN_HOURLY_OBS:
                sparse_days.append((d, stats["row_count"]))

            # Verify daily summary values
            if stats["max_temp_c"] is not None:
                if stats["max_temp_c"] > 45.0 or stats["max_temp_c"] < -40.0:
                    impossible_values.append(f"Daily summary temperature for {d}: {stats['max_temp_c']} C is impossible")

    print("\n--- Summary Audit ---")
    print(f"Target window dates: {len(target_dates)}")
    print(f"Historical days recorded: {len(summary_dates)}")
    print(f"Missing days: {len(missing_days)}")
    if missing_days:
        for d in missing_days[:10]:
            print(f"  Missing: {d}")
        if len(missing_days) > 10:
            print("  ...")

    print(f"Sparse days (< {MIN_HOURLY_OBS} rows): {len(sparse_days)}")
    if sparse_days:
        for d, cnt in sparse_days[:10]:
            print(f"  Sparse: {d} (only {cnt} rows)")
        if len(sparse_days) > 10:
            print("  ...")

    # 4. Audit hourly observations
    hourly_checked_days = 0
    for year in years:
        # Load hourly partitions if they exist
        monthly_files = {}
        # Target dates fall in May or June (months 5 and 6)
        for month in [5, 6]:
            path = data_root / "hourly" / f"year={year}" / f"month={month:02d}" / "observations.jsonl"
            if path.exists():
                monthly_files[month] = path

        if not monthly_files:
            continue

        for month, path in monthly_files.items():
            daily_rows = {}
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    local_date_str = row.get("local_date")
                    if not local_date_str:
                        continue
                    local_date = date.fromisoformat(local_date_str)
                    if local_date in target_dates:
                        daily_rows.setdefault(local_date, []).append(row)

            for d, rows in daily_rows.items():
                hourly_checked_days += 1
                timestamps = set()
                for row in rows:
                    local_time = row.get("local_time")
                    if local_time:
                        if local_time in timestamps:
                            duplicate_timestamps.append((d, local_time))
                        timestamps.add(local_time)

                    # Impossible values check
                    temp = row.get("temp_c")
                    if temp is not None:
                        temp = float(temp)
                        if temp > 45.0 or temp < -40.0:
                            impossible_values.append(f"CYYZ {d} {local_time}: Temp {temp} C is impossible")

                    humidity = row.get("humidity")
                    if humidity is not None:
                        humidity = float(humidity)
                        if humidity < 0.0 or humidity > 100.0:
                            impossible_values.append(f"CYYZ {d} {local_time}: Humidity {humidity}% is impossible")

                    pressure = row.get("pressure")
                    if pressure is not None:
                        pressure = float(pressure)
                        if pressure < 900.0 or pressure > 1080.0:
                            impossible_values.append(f"CYYZ {d} {local_time}: Pressure {pressure} hPa is impossible")

                    wind = row.get("wind_speed_kmh")
                    if wind is not None:
                        wind = float(wind)
                        if wind < 0.0 or wind > 250.0:
                            impossible_values.append(f"CYYZ {d} {local_time}: Wind {wind} km/h is impossible")

    print("\n--- Hourly Details Audit ---")
    print(f"Hourly days audited: {hourly_checked_days}")
    print(f"Duplicate timestamps: {len(duplicate_timestamps)}")
    if duplicate_timestamps:
        for d, t in duplicate_timestamps[:10]:
            print(f"  Duplicate: {d} at {t}")
        if len(duplicate_timestamps) > 10:
            print("  ...")

    print(f"Impossible/Anomaly values: {len(impossible_values)}")
    if impossible_values:
        for val in impossible_values[:10]:
            print(f"  Anomaly: {val}")
        if len(impossible_values) > 10:
            print("  ...")

    print("\nAudit Complete.")
    return len(missing_days) == 0 and len(impossible_values) == 0

if __name__ == "__main__":
    audit_historical_data()
