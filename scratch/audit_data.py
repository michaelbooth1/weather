import sys
sys.path.append("src")
from market_registry import all_specs
from pathlib import Path
import os

print("--- Data Audit ---")
for spec in all_specs():
    base = spec.data_root / "daily"
    count = 0
    if base.exists():
        count = len(list(base.glob("*.csv")))
    print(f"{spec.id} ({spec.icao}): {count} days of data")
