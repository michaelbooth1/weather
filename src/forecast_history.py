"""Historical forecast layer: archived Open-Meteo forecasts for past target-season
days, used as a non-leaky training feature for the model.

Open-Meteo's Historical Forecast API returns the forecast that was *issued for* a
past date (initialized from that morning's run, so it predicts the day without
seeing its outcome). We store the forecasted daily-max temperature per date; the
model joins it as `forecast_high` and derives `forecast_gap = forecast_high -
high_so_far`. Open-Meteo is the canonical forecast source for both training (this
layer) and serving (live Open-Meteo), so the feature means the same thing on both
sides.

CLI:
  python -m src.forecast_history backfill [--start-year 2015] [--end-year 2026]
  python -m src.forecast_history coverage
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from model_constants import PEARSON_LAT, PEARSON_LON
from model_sources import request_with_retries

HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
DATA_ROOT = Path("data") / "forecast_history" / "cyyz"
DAILY_PATH = DATA_ROOT / "forecast_daily.csv"
MANIFEST_PATH = DATA_ROOT / "manifest.json"
# Generous target-season window so one day's +/-7 climatology window is covered
# for any late-May / early-June target date. One API call per year covers it.
SEASON_START = (5, 10)
SEASON_END = (6, 15)


def fetch_year_forecast(year, timeout=30):
    """Return {local_date_iso: forecast_daily_max_c} for the season window of a year."""
    start = f"{year}-{SEASON_START[0]:02d}-{SEASON_START[1]:02d}"
    end = f"{year}-{SEASON_END[0]:02d}-{SEASON_END[1]:02d}"

    def _once():
        resp = requests.get(HIST_FORECAST_URL, params={
            "latitude": PEARSON_LAT,
            "longitude": PEARSON_LON,
            "start_date": start,
            "end_date": end,
            "hourly": "temperature_2m",
            "timezone": "America/Toronto",
        }, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    payload = request_with_retries(_once)
    hourly = payload.get("hourly", {}) or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    daily = {}
    for t, temp in zip(times, temps):
        if temp is None or not t:
            continue
        day = str(t)[:10]
        daily[day] = max(daily.get(day, float("-inf")), float(temp))
    return {d: v for d, v in daily.items() if v != float("-inf")}


def load_forecast_daily(path=DAILY_PATH):
    """date_iso -> forecast_high_c from the stored layer (empty dict if absent)."""
    index = {}
    if not Path(path).exists():
        return index
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            d = row.get("local_date")
            v = row.get("forecast_high_c")
            if d and v not in (None, ""):
                try:
                    index[d] = float(v)
                except ValueError:
                    continue
    return index


def backfill(start_year, end_year, pause=0.4):
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    rows = {}
    per_year = {}
    for year in range(start_year, end_year + 1):
        try:
            year_daily = fetch_year_forecast(year)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  {year}: ERROR {type(exc).__name__}: {exc}")
            per_year[year] = 0
            continue
        per_year[year] = len(year_daily)
        rows.update(year_daily)
        print(f"  {year}: {len(year_daily)} forecast-days "
              f"({min(year_daily.values()):.1f}..{max(year_daily.values()):.1f} C)"
              if year_daily else f"  {year}: no data")
        time.sleep(pause)

    ordered = sorted(rows.items())
    with DAILY_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_date", "forecast_high_c"])
        for d, v in ordered:
            writer.writerow([d, f"{v:.1f}"])

    covered_years = sorted(y for y, n in per_year.items() if n > 0)
    manifest = {
        "endpoint": HIST_FORECAST_URL,
        "params": {"latitude": PEARSON_LAT, "longitude": PEARSON_LON,
                   "hourly": "temperature_2m", "timezone": "America/Toronto"},
        "season_window": {"start": list(SEASON_START), "end": list(SEASON_END)},
        "generated_at": datetime.now().isoformat(),
        "total_days": len(ordered),
        "covered_years": covered_years,
        "per_year_days": per_year,
    }
    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)

    print(f"\n=== Coverage ===")
    print(f"  years with data : {covered_years[0] if covered_years else '-'}"
          f"..{covered_years[-1] if covered_years else '-'} ({len(covered_years)} years)")
    print(f"  total forecast-days: {len(ordered)}")
    print(f"  written to {DAILY_PATH}")
    return manifest


def coverage():
    index = load_forecast_daily()
    if not index:
        print("No forecast history stored yet. Run: python -m src.forecast_history backfill")
        return
    years = sorted({d[:4] for d in index})
    print(f"Stored forecast-days: {len(index)}  years {years[0]}..{years[-1]} ({len(years)} years)")
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open(encoding="utf-8") as handle:
            man = json.load(handle)
        print("Per-year days:", man.get("per_year_days"))


def main():
    parser = argparse.ArgumentParser(description="Backfill archived Open-Meteo forecasts.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--start-year", type=int, default=2015)
    b.add_argument("--end-year", type=int, default=datetime.now().year)
    sub.add_parser("coverage")
    args = parser.parse_args()

    if args.command == "backfill":
        backfill(args.start_year, args.end_year)
    elif args.command == "coverage":
        coverage()


if __name__ == "__main__":
    main()
