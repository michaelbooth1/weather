import json
import csv
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict, Counter

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

    # Load hourly observations
    hourly_files = list(DATA_ROOT.glob("hourly/year=*/month=*/observations.jsonl"))
    by_date = defaultdict(list)
    for path in hourly_files:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                local_date = date.fromisoformat(row["local_date"])
                if 5 <= local_date.month <= 6: # target season May-June
                    time_str = row.get("local_time")
                    if time_str:
                        h, m = time_str.split(":")[:2]
                        row["minute_of_day"] = int(h) * 60 + int(m)
                        by_date[local_date].append(row)

    # Sort each day by valid time
    for d in by_date:
        by_date[d].sort(key=lambda r: r["valid_time_local"])

    # Analyze after 3 PM (900 mins), 4 PM (960 mins), 5 PM (1020 mins)
    hours = [15, 16, 17]
    
    print("Late-Day Continuation Analysis:")
    
    for hour in hours:
        cutoff = hour * 60
        total_days = 0
        extended_days = 0
        
        # We group by: was the high first reached recently (< 60 minutes ago) or long ago (>= 60 minutes ago)?
        recent_total = 0
        recent_extended = 0
        stable_total = 0
        stable_extended = 0
        
        for local_date, rows in by_date.items():
            if local_date not in daily or daily[local_date]["final_high"] is None:
                continue
            final_high = daily[local_date]["final_high"]
            
            # Observations before or at cutoff
            obs_before = [r for r in rows if r["minute_of_day"] <= cutoff]
            if not obs_before:
                continue
                
            temps_before = [r["temp_c"] for r in obs_before if r["temp_c"] is not None]
            if not temps_before:
                continue
                
            high_so_far = max(temps_before)
            
            # Find when this high was FIRST reached
            first_reached_min = None
            for r in obs_before:
                if r.get("temp_c") == high_so_far:
                    first_reached_min = r["minute_of_day"]
                    break
                    
            if first_reached_min is None:
                continue
                
            time_since_reached = cutoff - first_reached_min
            is_extended = final_high > (high_so_far + 0.1) # strictly greater (accounting for float precision)
            
            total_days += 1
            if is_extended:
                extended_days += 1
                
            if time_since_reached < 60:
                recent_total += 1
                if is_extended:
                    recent_extended += 1
            else:
                stable_total += 1
                if is_extended:
                    stable_extended += 1
                    
        print(f"\nCutoff Hour {hour:02d}:00:")
        print(f"  Total days: {total_days}")
        print(f"  Overall continuation rate (final > high-so-far): {extended_days/total_days*100:.1f}%")
        if recent_total > 0:
            print(f"  High reached recently (< 1h ago): {recent_extended/recent_total*100:.1f}% continuation rate (N={recent_total})")
        if stable_total > 0:
            print(f"  High reached long ago (>= 1h ago): {stable_extended/stable_total*100:.1f}% continuation rate (N={stable_total})")

if __name__ == "__main__":
    main()
