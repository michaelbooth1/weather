import os
import csv
import json
import math
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter

# Constants
METAR_ROOT = Path("data") / "metar" / "cyyz"
RAW_ROOT = METAR_ROOT / "raw"
HOURLY_ROOT = METAR_ROOT / "hourly"
ANALYSIS_ROOT = METAR_ROOT / "analysis"
TORONTO_TZ = ZoneInfo("America/Toronto")

def fetch_metar_data():
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_ROOT / "all_years_raw.csv"
    if raw_path.exists():
        print("Using cached METAR raw data...")
        return raw_path.read_text(encoding="utf-8")
        
    url = (
        "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"
        "station=CYYZ&data=tmpc&data=dwpc&year1=1982&month1=5&day1=20"
        "&year2=2025&month2=6&day2=3&tz=Etc/UTC&format=onlycomma"
    )
    print("Downloading historical METAR data for CYYZ from IEM ASOS (1982-2025)...")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    
    # Save raw file
    raw_path.write_text(response.text, encoding="utf-8")
    return response.text

def normalize_and_partition(csv_text):
    HOURLY_ROOT.mkdir(parents=True, exist_ok=True)
    
    # Clear existing partition files if any
    for old_file in HOURLY_ROOT.glob("year=*/observations.jsonl"):
        old_file.unlink()
        
    lines = csv_text.splitlines()
    if len(lines) < 2:
        return
        
    reader = csv.DictReader(lines)
    
    # Group observations by local year
    observations_by_year = defaultdict(list)
    
    print("Normalizing METAR observations and converting to Toronto local time...")
    for row in reader:
        valid_str = row.get("valid")
        if not valid_str or row.get("tmpc") in (None, "", "M") or row.get("tmpc") == "null":
            continue
            
        try:
            # Parse UTC time
            utc_dt = datetime.strptime(valid_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            # Convert to Toronto time
            local_dt = utc_dt.astimezone(TORONTO_TZ)
            
            # Filter for target seasonal window (May 20 to June 3)
            is_seasonal = False
            if local_dt.month == 5 and local_dt.day >= 20:
                is_seasonal = True
            elif local_dt.month == 6 and local_dt.day <= 3:
                is_seasonal = True
                
            if not is_seasonal:
                continue
                
            temp_c = float(row["tmpc"])
            dew_c = float(row["dwpc"]) if row.get("dwpc") not in (None, "", "M", "null") else None
            
            obs = {
                "local_date": local_dt.date().isoformat(),
                "local_time": local_dt.strftime("%H:%M"),
                "minute_of_day": local_dt.hour * 60 + local_dt.minute,
                "temp_c": temp_c,
                "dewpoint_c": dew_c,
            }
            observations_by_year[local_dt.year].append(obs)
        except Exception as e:
            continue

    # Write partitions
    for year, obs_list in observations_by_year.items():
        partition_dir = HOURLY_ROOT / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = partition_dir / "observations.jsonl"
        
        # Sort by local time
        obs_list.sort(key=lambda o: o["minute_of_day"])
        
        with jsonl_path.open("w", encoding="utf-8") as f:
            for obs in obs_list:
                f.write(json.dumps(obs) + "\n")
                
    print(f"Wrote normalized METAR partitions for {len(observations_by_year)} years.")

def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))

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

    # Load METAR hourly files and compare daily maxes
    print("\nComparing METAR same-day maximums versus Wunderground final highs...")
    comparison_data = []
    
    for year in range(1982, 2026):
        jsonl_path = HOURLY_ROOT / f"year={year}" / "observations.jsonl"
        if not jsonl_path.exists():
            continue
            
        daily_obs = defaultdict(list)
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                daily_obs[row["local_date"]].append(row)
                
        for dt_str, obs_list in daily_obs.items():
            temps = [obs["temp_c"] for obs in obs_list if obs["temp_c"] is not None]
            if not temps:
                continue
                
            metar_max = max(temps)
            metar_bucket = round_half_up(metar_max)
            
            # Find times when METAR max occurred
            metar_times = [obs["local_time"] for obs in obs_list if obs["temp_c"] == metar_max]
            
            if dt_str in wu_data:
                wu = wu_data[dt_str]
                if wu["max_temp_c"] is not None:
                    comparison_data.append({
                        "date": dt_str,
                        "metar_max": metar_max,
                        "metar_bucket": metar_bucket,
                        "metar_times": metar_times,
                        "wu_max": wu["max_temp_c"],
                        "wu_bucket": wu["max_temp_bucket_c"],
                        "wu_times": wu["max_temp_times"].split("|") if wu["max_temp_times"] else []
                    })

    # Perform statistics
    df = pd.DataFrame(comparison_data)
    if len(df) == 0:
        print("No comparison data available.")
        return
        
    df["temp_diff"] = df["metar_max"] - df["wu_max"]
    df["bucket_diff"] = df["metar_bucket"] - df["wu_bucket"]
    df["abs_temp_diff"] = df["temp_diff"].abs()
    
    mean_bias = df["temp_diff"].mean()
    mae = df["abs_temp_diff"].mean()
    exact_bucket_match = (df["metar_bucket"] == df["wu_bucket"]).mean()
    metar_exceeds_wu = (df["metar_max"] > df["wu_max"]).mean()
    metar_misses_wu = (df["metar_max"] < df["wu_max"]).mean()
    
    print("\nComparison Results Summary:")
    print(f"Total days compared: {len(df)}")
    print(f"Mean Temperature Bias (METAR - WU): {mean_bias:.4f} °C")
    print(f"Mean Absolute Error: {mae:.4f} °C")
    print(f"Exact Bucket Match Rate: {exact_bucket_match*100:.2f}%")
    print(f"METAR Exceeds WU Rate: {metar_exceeds_wu*100:.2f}%")
    print(f"METAR Misses WU Rate: {metar_misses_wu*100:.2f}%")

    # Generate Markdown Report
    ANALYSIS_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = ANALYSIS_ROOT / "comparison_report.md"
    
    df_sorted = df.sort_values(by="abs_temp_diff", ascending=False)
    
    with report_path.open("w", encoding="utf-8") as f:
        f.write("# METAR vs. Wunderground Historical Climate Comparison\n\n")
        f.write(f"**Station:** `TORONTO PEARSON INT'L A (CYYZ)`  \n")
        f.write(f"**Report Generated:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n")
        f.write(f"**Target Window:** May 20 - June 3 (Years 1982–2025)  \n")
        f.write(f"**Total Days Compared:** {len(df)}\n\n")
        
        f.write("## Overall Discrepancy Statistics\n\n")
        f.write("| Metric | Value |\n")
        f.write("| :--- | :--- |\n")
        f.write(f"| Mean Temperature Bias (METAR - WU) | {mean_bias:+.4f} °C |\n")
        f.write(f"| Mean Absolute Temperature Error | {mae:.4f} °C |\n")
        f.write(f"| Exact Bucket Match Rate | {exact_bucket_match*100:.2f}% |\n")
        f.write(f"| Rate METAR Max > WU High | {metar_exceeds_wu*100:.2f}% |\n")
        f.write(f"| Rate METAR Max < WU High | {metar_misses_wu*100:.2f}% |\n")
        f.write("\n")
        
        f.write("## Summary of Bucket Differences\n\n")
        bucket_diff_counts = Counter(df["bucket_diff"])
        f.write("| Bucket Difference (METAR - WU) | Count | Percentage |\n")
        f.write("| :--- | :--- | :--- |\n")
        for diff in sorted(bucket_diff_counts.keys()):
            count = bucket_diff_counts[diff]
            pct = count / len(df) * 100
            diff_str = f"{diff:+.0f}" if diff != 0 else "0"
            f.write(f"| {diff_str} °C | {count} | {pct:.2f}% |\n")
        f.write("\n")
        
        f.write("## Key Findings & Research Questions\n\n")
        f.write("### 1. Does METAR systematically lead, exceed, or miss Wunderground?\n")
        if mean_bias > 0.05:
            f.write(f"- **Exceeds:** METAR same-day maximum temperatures are on average **{mean_bias:+.3f} °C higher** than the Wunderground printed daily high. METAR exceeded Wunderground on **{metar_exceeds_wu*100:.1f}%** of days.\n")
        elif mean_bias < -0.05:
            f.write(f"- **Misses:** METAR same-day maximum temperatures are on average **{abs(mean_bias):.3f} °C lower** than the Wunderground printed daily high. Wunderground exceeded METAR on **{metar_misses_wu*100:.1f}%** of days.\n")
        else:
            f.write(f"- **Close Agreement:** The mean temperature bias is very small (**{mean_bias:+.3f} °C**), showing strong agreement between METAR reports and Wunderground printed history. Basis risk is extremely low.\n")
            
        f.write("\n### 2. Analysis of the exact bucket match rate\n")
        f.write(f"- The two sources matched the exact whole-degree bucket on **{exact_bucket_match*100:.1f}%** of seasonal days.\n")
        f.write(f"- On **{(1-exact_bucket_match)*100:.1f}%** of days, they differed by at least one whole degree. This represents the 'basis risk' between METAR historical data and Wunderground history (the resolution source).\n\n")
        
        f.write("## Top 15 Largest Discrepancies\n\n")
        f.write("| Date | METAR Max | WU Max | Temp Diff | METAR Bucket | WU Bucket | METAR Times | WU Times |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for _, row in df_sorted.head(15).iterrows():
            f.write(f"| {row['date']} | {row['metar_max']:.1f} °C | {row['wu_max']:.1f} °C | {row['temp_diff']:+.1f} °C | {row['metar_bucket']} | {row['wu_bucket']} | {', '.join(row['metar_times'])} | {', '.join(row['wu_times'])} |\n")
            
    print(f"Saved comparison report to {report_path}")

def main():
    csv_text = fetch_metar_data()
    normalize_and_partition(csv_text)
    run_comparison()

if __name__ == "__main__":
    main()
