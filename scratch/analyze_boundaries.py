import json
import csv
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np

DATA_ROOT = Path("data") / "wunderground" / "cyyz"
summary_path = DATA_ROOT / "daily" / "daily_summary.csv"

def round_half_up(value):
    if value is None:
        return None
    import math
    return int(math.floor(float(value) + 0.5))

def main():
    if not summary_path.exists():
        print("daily_summary.csv not found!")
        return

    # Load daily summary
    daily = {}
    with summary_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            local_date = date.fromisoformat(row["local_date"])
            daily[local_date] = {
                "final_high": float(row["max_temp_c"]) if row["max_temp_c"] else None,
                "final_bucket": int(row["max_temp_bucket_c"]) if row["max_temp_bucket_c"] else None,
            }

    # Find hourly observations for target-season dates (May 20 - June 3)
    target_months = {5, 6}
    hourly_files = list(DATA_ROOT.glob("hourly/year=*/month=*/observations.jsonl"))
    
    by_date = defaultdict(list)
    for path in hourly_files:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                local_date = date.fromisoformat(row["local_date"])
                
                # Filter target season
                if local_date.month == 5 and local_date.day < 20:
                    continue
                if local_date.month == 6 and local_date.day > 3:
                    continue
                if local_date.month not in target_months:
                    continue
                    
                by_date[local_date].append(row)

    # Sort each day by valid time
    for d in by_date:
        by_date[d].sort(key=lambda r: r["valid_time_local"])

    print(f"Analyzing {len(by_date)} target-season days...")

    # 1. Analyze skips/jumps (consecutive temperature jumps that cross an integer bucket boundary)
    jumps_cross_boundary = 0
    total_transitions = 0
    crossings = []
    
    for local_date, rows in by_date.items():
        temps = [r["temp_c"] for r in rows if r.get("temp_c") is not None]
        for i in range(len(temps) - 1):
            t1, t2 = temps[i], temps[i+1]
            total_transitions += 1
            b1 = round_half_up(t1)
            b2 = round_half_up(t2)
            if abs(b2 - b1) >= 1:
                # Temperature crossed a whole-degree boundary
                jumps_cross_boundary += 1
                crossings.append((t1, t2))

    print(f"\n1. Skips / Jumps:")
    print(f"  Total temperature transitions: {total_transitions}")
    print(f"  Transitions crossing a bucket boundary: {jumps_cross_boundary} ({jumps_cross_boundary / total_transitions * 100:.2f}%)")
    if crossings:
        print("  Example crossings:")
        for t1, t2 in crossings[:5]:
            print(f"    {t1} C -> {t2} C (bucket {round_half_up(t1)} -> {round_half_up(t2)})")

    # 2. Timing of daily high temperature
    print("\n2. Peak Temperature Hour Frequencies:")
    peak_hours = []
    for local_date, rows in by_date.items():
        if local_date not in daily or daily[local_date]["final_high"] is None:
            continue
        final_high = daily[local_date]["final_high"]
        # Find hours where final_high was reached
        for r in rows:
            if r.get("temp_c") == final_high:
                t_str = r.get("local_time")
                if t_str:
                    hour = int(t_str.split(":")[0])
                    peak_hours.append(hour)
                    break # count first time reached

    hour_counts = Counter(peak_hours)
    total_peaks = sum(hour_counts.values())
    for hour in sorted(hour_counts.keys()):
        pct = hour_counts[hour] / total_peaks * 100
        print(f"  Hour {hour:02d}:00: {pct:.1f}%")

    # 3. Transitions / Conditional Probabilities for critical range around 24, 25, 26 C
    # We choose cutoff hours: 12:00, 15:00, 17:00
    cutoff_hours = [12, 15, 17]
    print("\n3. Conditional Transition Probabilities for Critical Ranges:")
    
    for ch in cutoff_hours:
        print(f"\n  Cutoff Hour {ch:02d}:00:")
        transitions = defaultdict(list)
        for local_date, rows in by_date.items():
            if local_date not in daily or daily[local_date]["final_bucket"] is None:
                continue
            final_bucket = daily[local_date]["final_bucket"]
            
            # Find max temp up to cutoff hour
            cutoff_minutes = ch * 60
            temps_before = [r["temp_c"] for r in rows if r.get("temp_c") is not None and int(r.get("local_time", "00:00").split(":")[0])*60 + int(r.get("local_time", "00:00").split(":")[1]) <= cutoff_minutes]
            if not temps_before:
                continue
            max_so_far = max(temps_before)
            bucket_so_far = round_half_up(max_so_far)
            
            # Record transition
            transitions[bucket_so_far].append(final_bucket)

        for bucket in sorted(transitions.keys()):
            if 22 <= bucket <= 27:
                outcomes = transitions[bucket]
                counts = Counter(outcomes)
                total = len(outcomes)
                prob_str = ", ".join(f"{k}C: {v/total*100:.1f}%" for k, v in sorted(counts.items()))
                print(f"    If current max is {bucket} C (N={total}): final high distribution -> {prob_str}")

if __name__ == "__main__":
    main()
