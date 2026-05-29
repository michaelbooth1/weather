import csv
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict

# Define constants
DATA_ROOT = Path("data") / "wunderground" / "cyyz"
TARGET_DATE = date(2026, 5, 27)
SEASONAL_WINDOW = 7

# Today's observations from the user's screenshot
TODAY_OBS = [
    {"time": "00:00", "temp": 20.0, "condition": "Mostly Cloudy", "wind": "WSW", "wind_speed": 17, "gust": 0, "pressure": 992.25},
    {"time": "01:00", "temp": 20.0, "condition": "Mostly Cloudy", "wind": "WSW", "wind_speed": 22, "gust": 0, "pressure": 991.59},
    {"time": "02:00", "temp": 21.0, "condition": "Mostly Cloudy", "wind": "WNW", "wind_speed": 19, "gust": 30, "pressure": 991.92},
    {"time": "03:00", "temp": 20.0, "condition": "Partly Cloudy", "wind": "WNW", "wind_speed": 20, "gust": 0, "pressure": 991.92},
    {"time": "05:00", "temp": 18.0, "condition": "Mostly Cloudy", "wind": "NW", "wind_speed": 15, "gust": 0, "pressure": 991.92},
    {"time": "06:00", "temp": 17.0, "condition": "Mostly Cloudy", "wind": "NW", "wind_speed": 15, "gust": 0, "pressure": 991.92},
    {"time": "07:00", "temp": 17.0, "condition": "Mostly Cloudy", "wind": "NNW", "wind_speed": 26, "gust": 0, "pressure": 992.25},
    {"time": "08:00", "temp": 17.0, "condition": "Partly Cloudy", "wind": "NNW", "wind_speed": 22, "gust": 0, "pressure": 992.59},
    {"time": "09:00", "temp": 19.0, "condition": "Fair", "wind": "N", "wind_speed": 20, "gust": 31, "pressure": 992.92},
    {"time": "10:00", "temp": 19.0, "condition": "Fair", "wind": "N", "wind_speed": 11, "gust": 0, "pressure": 993.25},
    {"time": "11:00", "temp": 21.0, "condition": "Fair", "wind": "N", "wind_speed": 9, "gust": 0, "pressure": 993.25},
    {"time": "12:00", "temp": 22.0, "condition": "Fair", "wind": "WNW", "wind_speed": 9, "gust": 0, "pressure": 993.25},
    {"time": "14:00", "temp": 23.0, "condition": "Partly Cloudy", "wind": "W", "wind_speed": 11, "gust": 0, "pressure": 992.92},
    {"time": "14:23", "temp": 24.0, "condition": "Fair", "wind": "NNW", "wind_speed": 15, "gust": 28, "pressure": 992.59},
]

# Max temp observed so far is 24.0 C at 14:23 (2:23 PM)
observed_high = 24.0
cutoff_minute = 14 * 60 + 23  # 2:23 PM is 863 minutes

def get_minute_of_day(time_str):
    try:
        h, m = time_str.split(":")
        return int(h) * 60 + int(m)
    except:
        return None

def load_historical_data():
    summary_path = DATA_ROOT / "daily" / "daily_summary.csv"
    reference_year = 2000
    target_reference = date(reference_year, TARGET_DATE.month, TARGET_DATE.day)
    
    seasonal_dates = set()
    daily_summaries = {}
    with summary_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            local_date_str = row["local_date"]
            local_date = date.fromisoformat(local_date_str)
            if local_date.year >= TARGET_DATE.year:
                continue
            ref_date = local_date.replace(year=reference_year)
            if abs((ref_date - target_reference).days) <= SEASONAL_WINDOW:
                seasonal_dates.add(local_date_str)
                daily_summaries[local_date_str] = {
                    "date": local_date_str,
                    "final_max_temp": float(row["max_temp_c"]) if row["max_temp_c"] else None,
                    "final_bucket": int(row["max_temp_bucket_c"]) if row["max_temp_bucket_c"] else None,
                }
                
    hourly_data = defaultdict(list)
    for dt_str in seasonal_dates:
        dt = date.fromisoformat(dt_str)
        path = DATA_ROOT / "hourly" / f"year={dt.year}" / f"month={dt.month:02d}" / "observations.jsonl"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("local_date") == dt_str:
                    time_str = row.get("local_time")
                    minute = get_minute_of_day(time_str)
                    if minute is not None:
                        hourly_data[dt_str].append({
                            "time": time_str,
                            "minute": minute,
                            "temp": row.get("temp_c"),
                        })
                        
    for dt_str in hourly_data:
        hourly_data[dt_str].sort(key=lambda x: x["minute"])
        
    return daily_summaries, hourly_data

def main():
    daily_summaries, hourly_data = load_historical_data()
    
    # Let's count when the high occurred across ALL seasonal days, not just those matching 24 C at 2:23 PM
    # To understand general climatological behavior.
    high_time_minutes = []
    peaked_after_2_23 = 0
    total_days = 0
    
    for dt_str, summary in daily_summaries.items():
        rows = hourly_data.get(dt_str, [])
        if not rows:
            continue
            
        final_max = summary["final_max_temp"]
        if final_max is None:
            continue
            
        # Find first and last times the final max was reached
        high_minutes = [r["minute"] for r in rows if r["temp"] == final_max]
        if not high_minutes:
            continue
            
        total_days += 1
        last_high_minute = max(high_minutes)
        high_time_minutes.append(last_high_minute)
        
        if last_high_minute > cutoff_minute:
            peaked_after_2_23 += 1
            
    print(f"Climatological Analysis of Peak Temperature Timing:")
    print(f"Total days analyzed: {total_days}")
    print(f"Days where peak temperature occurred AFTER 2:23 PM: {peaked_after_2_23} ({peaked_after_2_23 / total_days * 100:.1f}%)")
    print(f"Days where peak temperature occurred BEFORE or AT 2:23 PM: {total_days - peaked_after_2_23} ({(total_days - peaked_after_2_23) / total_days * 100:.1f}%)")
    
    # Bin peak times
    hourly_counts = Counter()
    for m in high_time_minutes:
        hour = m // 60
        hourly_counts[hour] += 1
        
    print("\nPeak temperature occurrence by hour of day (last occurrence):")
    for h in sorted(hourly_counts.keys()):
        count = hourly_counts[h]
        pct = count / total_days * 100
        period = "AM" if h < 12 else "PM"
        display_hour = h if h <= 12 else h - 12
        if display_hour == 0:
            display_hour = 12
        print(f"  {display_hour:2d} {period}: {count:3d} times ({pct:5.1f}%)")

if __name__ == "__main__":
    main()
