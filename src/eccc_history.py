import os
import csv
import json
import time
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict, Counter

# Constants
ECCC_ROOT = Path("data") / "eccc" / "cyyz"
RAW_ROOT = ECCC_ROOT / "raw"
HOURLY_ROOT = ECCC_ROOT / "hourly"
ANALYSIS_ROOT = ECCC_ROOT / "analysis"

# Target date window May 20 to June 3
TARGET_MONTHS = (5, 6)

def get_station_id(year):
    # Station ID 5096 is Lester B. Pearson prior to 2003
    # Station ID 5097 is Lester B. Pearson from 2003 onwards
    if year <= 2002:
        return 5096
    return 5097

def fetch_eccc_data(year, month):
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_ROOT / f"year={year}" / f"month={month:02d}.csv"
    if raw_path.exists():
        return raw_path.read_text(encoding="utf-8")
        
    station_id = get_station_id(year)
    url = f"https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID={station_id}&Year={year}&Month={month}&Day=1&timeframe=1"
    
    print(f"Downloading ECCC weather data for Year {year}, Month {month} (Station {station_id})...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    # Save raw file
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(response.text, encoding="utf-8")
    
    time.sleep(0.5)  # rate limit courtesy
    return response.text

def normalize_csv_and_write_jsonl(year, month, csv_text):
    HOURLY_ROOT.mkdir(parents=True, exist_ok=True)
    jsonl_path = HOURLY_ROOT / f"year={year}" / "observations.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines = csv_text.splitlines()
    if len(lines) < 2:
        return []
        
    reader = csv.reader(lines)
    headers = next(reader)
    
    # Find column indices robustly
    try:
        date_time_idx = [i for i, h in enumerate(headers) if "date/time" in h.lower()][0]
        year_idx = [i for i, h in enumerate(headers) if h.lower() == "year"][0]
        month_idx = [i for i, h in enumerate(headers) if h.lower() == "month"][0]
        day_idx = [i for i, h in enumerate(headers) if h.lower() == "day"][0]
        time_idx = [i for i, h in enumerate(headers) if "time" in h.lower() and "date" not in h.lower()][0]
        
        temp_idx = [i for i, h in enumerate(headers) if "temp" in h.lower() and "dew" not in h.lower()][0]
        dew_idx = [i for i, h in enumerate(headers) if "dew" in h.lower()][0]
        rh_idx = [i for i, h in enumerate(headers) if "rel hum" in h.lower() or "humidity" in h.lower()][0]
        wind_spd_idx = [i for i, h in enumerate(headers) if "wind spd" in h.lower() or "wind speed" in h.lower()][0]
        wind_dir_idx = [i for i, h in enumerate(headers) if "wind dir" in h.lower()][0]
        press_idx = [i for i, h in enumerate(headers) if "press" in h.lower()][0]
        weather_idx = [i for i, h in enumerate(headers) if "weather" in h.lower() or "condition" in h.lower()][0]
    except IndexError as e:
        print(f"Error finding columns in CSV for year {year}, month {month}: {e}")
        return []

    rows = []
    # Open mode "a" to append May and June into the same yearobservations.jsonl file
    with jsonl_path.open("a" if month == 6 else "w", encoding="utf-8") as f:
        for r in reader:
            if len(r) <= max(temp_idx, press_idx, weather_idx):
                continue
            
            try:
                # Parse numeric values helper
                def to_num(val):
                    if val in (None, "", "MSNG", "M"):
                        return None
                    return float(val)
                
                temp_c = to_num(r[temp_idx])
                dew_c = to_num(r[dew_idx])
                rh = to_num(r[rh_idx])
                wind_spd = to_num(r[wind_spd_idx])
                wind_dir_10s = to_num(r[wind_dir_idx])
                press_kpa = to_num(r[press_idx])
                
                # Normalize pressure to hPa (kPa * 10)
                press_hpa = press_kpa * 10.0 if press_kpa is not None else None
                # Normalize wind dir to degrees
                wind_dir_deg = wind_dir_10s * 10.0 if wind_dir_10s is not None else None
                
                # Date values
                row_year = int(r[year_idx])
                row_month = int(r[month_idx])
                row_day = int(r[day_idx])
                local_date = f"{row_year:04d}-{row_month:02d}-{row_day:02d}"
                local_time = r[time_idx]
                
                obs = {
                    "local_date": local_date,
                    "local_time": local_time,
                    "minute_of_day": int(local_time.split(":")[0]) * 60 + int(local_time.split(":")[1]),
                    "temp_c": temp_c,
                    "dewpoint_c": dew_c,
                    "humidity": rh,
                    "wind_speed_kmh": wind_spd,
                    "wind_dir_deg": wind_dir_deg,
                    "pressure_hpa": press_hpa,
                    "condition": r[weather_idx]
                }
                f.write(json.dumps(obs) + "\n")
                rows.append(obs)
            except Exception as e:
                # Skip invalid row
                continue
                
    return rows

def round_half_up(value):
    if value is None:
        return None
    return int(np.floor(float(value) + 0.5))

def run_comparison():
    # Load Wunderground daily summaries
    wu_summary_path = Path("data") / "wunderground" / "cyyz" / "daily" / "daily_summary.csv"
    if not wu_summary_path.exists():
        print(f"Error: daily_summary.csv not found at {wu_summary_path}")
        return
        
    wu_data = {}
    with wu_summary_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            local_date = row["local_date"]
            wu_data[local_date] = {
                "max_temp_c": float(row["max_temp_c"]) if row["max_temp_c"] else None,
                "max_temp_bucket_c": int(row["max_temp_bucket_c"]) if row["max_temp_bucket_c"] else None,
                "max_temp_times": row["max_temp_times"]
            }

    # Load ECCC hourly files and summarize daily
    print("\nComparing ECCC same-day maximums versus Wunderground final highs...")
    comparison_data = []
    
    for year in range(1982, 2026):
        jsonl_path = HOURLY_ROOT / f"year={year}" / "observations.jsonl"
        if not jsonl_path.exists():
            continue
            
        # Group by local_date
        daily_obs = defaultdict(list)
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                dt = date.fromisoformat(row["local_date"])
                # check if date is in seasonal window (May 20 to June 3)
                is_seasonal = False
                if dt.month == 5 and dt.day >= 20:
                    is_seasonal = True
                elif dt.month == 6 and dt.day <= 3:
                    is_seasonal = True
                    
                if is_seasonal:
                    daily_obs[row["local_date"]].append(row)
                    
        for dt_str, obs_list in daily_obs.items():
            temps = [obs["temp_c"] for obs in obs_list if obs["temp_c"] is not None]
            if not temps:
                continue
                
            eccc_max = max(temps)
            eccc_bucket = round_half_up(eccc_max)
            
            # Find times when ECCC max occurred
            eccc_times = [obs["local_time"] for obs in obs_list if obs["temp_c"] == eccc_max]
            
            # Match with WU data
            if dt_str in wu_data:
                wu = wu_data[dt_str]
                if wu["max_temp_c"] is not None:
                    comparison_data.append({
                        "date": dt_str,
                        "eccc_max": eccc_max,
                        "eccc_bucket": eccc_bucket,
                        "eccc_times": eccc_times,
                        "wu_max": wu["max_temp_c"],
                        "wu_bucket": wu["max_temp_bucket_c"],
                        "wu_times": wu["max_temp_times"].split("|") if wu["max_temp_times"] else []
                    })

    # Perform statistical analysis
    df = pd.DataFrame(comparison_data)
    if len(df) == 0:
        print("No comparison data available.")
        return
        
    df["temp_diff"] = df["eccc_max"] - df["wu_max"]
    df["bucket_diff"] = df["eccc_bucket"] - df["wu_bucket"]
    df["abs_temp_diff"] = df["temp_diff"].abs()
    
    mean_bias = df["temp_diff"].mean()
    mae = df["abs_temp_diff"].mean()
    exact_bucket_match = (df["eccc_bucket"] == df["wu_bucket"]).mean()
    eccc_exceeds_wu = (df["eccc_max"] > df["wu_max"]).mean()
    eccc_misses_wu = (df["eccc_max"] < df["wu_max"]).mean()
    
    print("\nComparison Results Summary:")
    print(f"Total days compared: {len(df)}")
    print(f"Mean Temperature Bias (ECCC - WU): {mean_bias:.4f} °C")
    print(f"Mean Absolute Error: {mae:.4f} °C")
    print(f"Exact Bucket Match Rate: {exact_bucket_match*100:.2f}%")
    print(f"ECCC Exceeds WU Rate: {eccc_exceeds_wu*100:.2f}%")
    print(f"ECCC Misses WU Rate: {eccc_misses_wu*100:.2f}%")

    # Generate Markdown Report
    ANALYSIS_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = ANALYSIS_ROOT / "comparison_report.md"
    
    # Save top 10 discrepancies
    df_sorted = df.sort_values(by="abs_temp_diff", ascending=False)
    
    with report_path.open("w", encoding="utf-8") as f:
        f.write("# ECCC vs. Wunderground Historical Climate Comparison\n\n")
        f.write(f"**Station:** `TORONTO PEARSON INT'L A (CYYZ)`  \n")
        f.write(f"**Report Generated:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n")
        f.write(f"**Target Window:** May 20 - June 3 (Years 1982–2025)  \n")
        f.write(f"**Total Days Compared:** {len(df)}\n\n")
        
        f.write("## Overall Discrepancy Statistics\n\n")
        f.write("| Metric | Value |\n")
        f.write("| :--- | :--- |\n")
        f.write(f"| Mean Temperature Bias (ECCC - WU) | {mean_bias:+.4f} °C |\n")
        f.write(f"| Mean Absolute Temperature Error | {mae:.4f} °C |\n")
        f.write(f"| Exact Bucket Match Rate | {exact_bucket_match*100:.2f}% |\n")
        f.write(f"| Rate ECCC Max > WU High | {eccc_exceeds_wu*100:.2f}% |\n")
        f.write(f"| Rate ECCC Max < WU High | {eccc_misses_wu*100:.2f}% |\n")
        f.write("\n")
        
        f.write("## Summary of Bucket Differences\n\n")
        bucket_diff_counts = Counter(df["bucket_diff"])
        f.write("| Bucket Difference (ECCC - WU) | Count | Percentage |\n")
        f.write("| :--- | :--- | :--- |\n")
        for diff in sorted(bucket_diff_counts.keys()):
            count = bucket_diff_counts[diff]
            pct = count / len(df) * 100
            diff_str = f"{diff:+.0f}" if diff != 0 else "0"
            f.write(f"| {diff_str} °C | {count} | {pct:.2f}% |\n")
        f.write("\n")
        
        f.write("## Key Findings & Research Questions\n\n")
        f.write("### 1. Does ECCC systematically lead, exceed, or miss Wunderground?\n")
        if mean_bias > 0.05:
            f.write(f"- **Exceeds:** ECCC same-day maximum temperatures are on average **{mean_bias:+.3f} °C higher** than the Wunderground printed daily high. ECCC exceeded Wunderground on **{eccc_exceeds_wu*100:.1f}%** of days.\n")
        elif mean_bias < -0.05:
            f.write(f"- **Misses:** ECCC same-day maximum temperatures are on average **{abs(mean_bias):.3f} °C lower** than the Wunderground printed daily high. Wunderground exceeded ECCC on **{eccc_misses_wu*100:.1f}%** of days.\n")
        else:
            f.write(f"- **Close Agreement:** The mean temperature bias is very small (**{mean_bias:+.3f} °C**), showing strong agreement between ECCC actuals and Wunderground printed history. However, there are individual discrepancies due to timing and source updates.\n")
            
        f.write("\n### 2. Analysis of the exact bucket match rate\n")
        f.write(f"- The two sources matched the exact whole-degree bucket on **{exact_bucket_match*100:.1f}%** of seasonal days.\n")
        f.write(f"- On **{(1-exact_bucket_match)*100:.1f}%** of days, they differed by at least one whole degree. This represents the 'basis risk' between ECCC historical data and Wunderground history (the resolution source).\n\n")
        
        f.write("## Top 15 Largest Discrepancies\n\n")
        f.write("| Date | ECCC Max | WU Max | Temp Diff | ECCC Bucket | WU Bucket | ECCC Times | WU Times |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for _, row in df_sorted.head(15).iterrows():
            f.write(f"| {row['date']} | {row['eccc_max']:.1f} °C | {row['wu_max']:.1f} °C | {row['temp_diff']:+.1f} °C | {row['eccc_bucket']} | {row['wu_bucket']} | {', '.join(row['eccc_times'])} | {', '.join(row['wu_times'])} |\n")
            
    print(f"Saved comparison report to {report_path}")

def main():
    # Make sure we don't spam requests, only fetch if not locally cached
    for year in range(1982, 2026):
        # Fetch raw and normalize for target seasonal window (May and June)
        for month in TARGET_MONTHS:
            try:
                csv_text = fetch_eccc_data(year, month)
                normalize_csv_and_write_jsonl(year, month, csv_text)
            except Exception as e:
                print(f"Failed for year {year}, month {month}: {e}")
                continue
                
    run_comparison()

if __name__ == "__main__":
    main()
