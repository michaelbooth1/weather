import json
import csv

from weather.paths import data_path

DATA_ROOT = data_path() / "wunderground" / "cyyz"
summary_path = DATA_ROOT / "daily" / "daily_summary.csv"

def main() -> int:
    print("Daily Summary Columns:")
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            print(header or [])
            first_row = next(reader, None)
            print("First row:", first_row or [])
    else:
        print("daily_summary.csv not found!")

    hourly_files = list(DATA_ROOT.glob("hourly/year=*/month=*/observations.jsonl"))
    print(f"\nFound {len(hourly_files)} hourly jsonl files.")
    if hourly_files:
        test_file = hourly_files[0]
        print(f"Inspecting first row of: {test_file}")
        with test_file.open("r", encoding="utf-8") as f:
            first_raw = f.readline()
            if first_raw:
                first_line = json.loads(first_raw)
                print(json.dumps(first_line, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
