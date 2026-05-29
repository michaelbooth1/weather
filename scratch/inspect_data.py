import json
import csv
from pathlib import Path

DATA_ROOT = Path("data") / "wunderground" / "cyyz"
summary_path = DATA_ROOT / "daily" / "daily_summary.csv"

# Read first few lines of daily summary
print("Daily Summary Columns:")
if summary_path.exists():
    with summary_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        print(header)
        first_row = next(reader)
        print("First row:", first_row)
else:
    print("daily_summary.csv not found!")

# Let's inspect one observations file to check raw hourly schema
hourly_files = list(DATA_ROOT.glob("hourly/year=*/month=*/observations.jsonl"))
print(f"\nFound {len(hourly_files)} hourly jsonl files.")
if hourly_files:
    test_file = hourly_files[0]
    print(f"Inspecting first row of: {test_file}")
    with test_file.open("r", encoding="utf-8") as f:
        first_line = json.loads(f.readline())
        print(json.dumps(first_line, indent=2))
