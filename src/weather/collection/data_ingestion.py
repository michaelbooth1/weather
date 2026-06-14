#!/usr/bin/env python
"""Data ingestion script to backfill historical weather data for all registered markets.

This script iterates over every market defined in `market_registry.REGISTRY` and invokes the
existing backfill CLI (`wu_history.py`) for each market. It uses a start date of 2015-01-01
(which covers the historical range used in training) and backs up to the current date.
The `--skip-existing` flag ensures that already‑fetched raw data is not re‑downloaded, making
the process incremental and rate‑limit friendly.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Ensure the repository's src directory is on PYTHONPATH
SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_registry import all_specs


def backfill_market(spec, start_date: str, end_date: str):
    """Run the backfill command for a single market.

    Returns True on success, False on failure.
    """
    cmd = [
        sys.executable,
        "-m",
        "src.wu_history",
        "backfill",
        "--market",
        spec.id,
        "--start",
        start_date,
        "--end",
        end_date,
        "--skip-existing",
        "--sleep",
        "0.2",
    ]
    print(f"Running backfill for market {spec.id}: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Backfill failed for {spec.id}: exit={result.returncode}")
        print(result.stderr)
        return False
    print(result.stdout)
    return True


def main():
    start_date = "2015-01-01"
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    all_success = True
    for spec in all_specs():
        success = backfill_market(spec, start_date, end_date)
        if not success:
            all_success = False
    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
