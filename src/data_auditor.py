import argparse
import os
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import config_for_date
from market_registry import all_specs, spec_for_id
from daily_summary import (
    celsius_high,
    native_high,
    row_count as daily_row_count,
    row_unit,
    to_float,
)

DEFAULT_DATA_ROOT = Path("data") / "wunderground" / "cyyz"
DEFAULT_MARKET_CONFIG = config_for_date()
TARGET_MONTH = DEFAULT_MARKET_CONFIG.target_date.month
TARGET_DAY = DEFAULT_MARKET_CONFIG.target_date.day
WINDOW_DAYS = 7
MIN_HOURLY_OBS = 18


def temperature_bounds(unit):
    unit = str(unit or "C").upper()
    if unit == "F":
        return -80.0, 140.0, "F"
    return -60.0, 60.0, "C"


def _coerce_years(years):
    if years is None:
        return list(range(2000, 2026))
    return [int(year) for year in years]


def _row_temperature(row, spec):
    if row.get("temp_native") not in (None, ""):
        return to_float(row.get("temp_native")), row.get("temperature_unit") or spec.display_unit
    if row.get("temp_c") not in (None, ""):
        # Legacy Fahrenheit-market WU rows used ``temp_c`` as the native column.
        return to_float(row.get("temp_c")), row.get("temperature_unit") or spec.display_unit
    return None, spec.display_unit


def _pressure(row):
    return to_float(row.get("pressure_hpa") if "pressure_hpa" in row else row.get("pressure"))


def _wind(row):
    return to_float(row.get("wind_speed_kmh"))


def _date_text(value):
    return value.isoformat() if isinstance(value, date) else str(value)


def audit_historical_data(
    data_root=None,
    target_month=None,
    target_day=None,
    market_id=None,
    years=None,
    quiet=False,
):
    spec = spec_for_id(market_id)
    if data_root is None:
        data_root = spec.data_root if market_id else DEFAULT_DATA_ROOT
    data_root = Path(data_root)
    summary_path = data_root / "daily" / "daily_summary.csv"
    if not summary_path.exists():
        if not quiet:
            print(f"Error: Daily summary file not found at {summary_path}")
        return None

    target_config = config_for_date(market_id=spec.id)
    target_month = target_month or (target_config.target_date.month if market_id else TARGET_MONTH)
    target_day = target_day or (target_config.target_date.day if market_id else TARGET_DAY)
    years = _coerce_years(years)
    if not quiet:
        print(f"Auditing historical weather data at: {data_root.resolve()}")
        print(f"Market: {spec.id} ({spec.display_unit})")
        print(f"Target window: {target_month:02d}-{target_day:02d} +/- {WINDOW_DAYS} days")
    
    # 1. Collect target dates in seasonal window across years
    target_dates = set()
    for year in years:
        target_ref = date(year, target_month, target_day)
        for offset in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
            target_dates.add(target_ref + timedelta(days=offset))

    # 2. Read daily summary file
    summary_dates = {}
    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date_str = row.get("local_date")
            if local_date_str:
                local_date = date.fromisoformat(local_date_str)
                unit = row_unit(row) or spec.display_unit
                summary_dates[local_date] = {
                    "row_count": daily_row_count(row),
                    "max_temp_native": native_high(row),
                    "max_temp_c": celsius_high(row),
                    "unit": unit,
                }

    # 3. Check for missing days
    missing_days = []
    sparse_days = []
    impossible_values = []
    duplicate_timestamps = []

    for d in sorted(target_dates):
        if d not in summary_dates:
            missing_days.append(d)
        else:
            stats = summary_dates[d]
            if stats["row_count"] < MIN_HOURLY_OBS:
                sparse_days.append((d, stats["row_count"]))

            # Verify daily summary values
            unit = stats.get("unit") or spec.display_unit
            lo, hi, label = temperature_bounds(unit)
            if stats["max_temp_native"] is not None:
                if stats["max_temp_native"] > hi or stats["max_temp_native"] < lo:
                    impossible_values.append(
                        f"{spec.icao} daily {d}: max {stats['max_temp_native']} {label} is impossible"
                    )
            c_hi = stats.get("max_temp_c")
            if c_hi is not None:
                c_lo, c_hi_limit, _ = temperature_bounds("C")
                if c_hi > c_hi_limit or c_hi < c_lo:
                    impossible_values.append(
                        f"{spec.icao} daily {d}: max {c_hi} C is impossible"
                    )

    if not quiet:
        print("\n--- Summary Audit ---")
        print(f"Target window dates: {len(target_dates)}")
        print(f"Historical days recorded: {len(summary_dates)}")
        print(f"Missing days: {len(missing_days)}")
        if missing_days:
            for d in missing_days[:10]:
                print(f"  Missing: {d}")
            if len(missing_days) > 10:
                print("  ...")

        print(f"Sparse days (< {MIN_HOURLY_OBS} rows): {len(sparse_days)}")
        if sparse_days:
            for d, cnt in sparse_days[:10]:
                print(f"  Sparse: {d} (only {cnt} rows)")
            if len(sparse_days) > 10:
                print("  ...")

    # 4. Audit hourly observations
    hourly_checked_days = 0
    for year in years:
        # Load hourly partitions if they exist
        monthly_files = {}
        # Target dates fall in May or June (months 5 and 6)
        for month in [5, 6]:
            path = data_root / "hourly" / f"year={year}" / f"month={month:02d}" / "observations.jsonl"
            if path.exists():
                monthly_files[month] = path

        if not monthly_files:
            continue

        for month, path in monthly_files.items():
            daily_rows = {}
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    local_date_str = row.get("local_date")
                    if not local_date_str:
                        continue
                    local_date = date.fromisoformat(local_date_str)
                    if local_date in target_dates:
                        daily_rows.setdefault(local_date, []).append(row)

            for d, rows in daily_rows.items():
                hourly_checked_days += 1
                timestamps = set()
                for row in rows:
                    local_time = row.get("local_time")
                    if local_time:
                        if local_time in timestamps:
                            duplicate_timestamps.append((d, local_time))
                        timestamps.add(local_time)

                    # Impossible values check
                    temp, temp_unit = _row_temperature(row, spec)
                    if temp is not None:
                        lo, hi, label = temperature_bounds(temp_unit)
                        if temp > hi or temp < lo:
                            impossible_values.append(
                                f"{spec.icao} {d} {local_time}: Temp {temp} {label} is impossible"
                            )

                    humidity = row.get("humidity")
                    if humidity is not None:
                        humidity = float(humidity)
                        if humidity < 0.0 or humidity > 100.0:
                            impossible_values.append(f"{spec.icao} {d} {local_time}: Humidity {humidity}% is impossible")

                    pressure = _pressure(row)
                    if pressure is not None:
                        if pressure < 40.0:
                            if pressure < 15.0 or pressure > 33.0:
                                impossible_values.append(
                                    f"{spec.icao} {d} {local_time}: Pressure {pressure} inHg is impossible"
                                )
                        elif pressure < 900.0 or pressure > 1080.0:
                            impossible_values.append(f"{spec.icao} {d} {local_time}: Pressure {pressure} hPa is impossible")

                    wind = _wind(row)
                    if wind is not None:
                        if wind < 0.0 or wind > 250.0:
                            impossible_values.append(f"{spec.icao} {d} {local_time}: Wind {wind} km/h is impossible")

    if not quiet:
        print("\n--- Hourly Details Audit ---")
        print(f"Hourly days audited: {hourly_checked_days}")
        print(f"Duplicate timestamps: {len(duplicate_timestamps)}")
        if duplicate_timestamps:
            for d, t in duplicate_timestamps[:10]:
                print(f"  Duplicate: {d} at {t}")
            if len(duplicate_timestamps) > 10:
                print("  ...")

        print(f"Impossible/Anomaly values: {len(impossible_values)}")
        if impossible_values:
            for val in impossible_values[:10]:
                print(f"  Anomaly: {val}")
            if len(impossible_values) > 10:
                print("  ...")

        print("\nAudit Complete.")
    return {
        "market_id": spec.id,
        "station": spec.icao,
        "unit": spec.display_unit,
        "target_dates": len(target_dates),
        "recorded_days": len(summary_dates),
        "missing_days": missing_days,
        "sparse_days": sparse_days,
        "duplicate_timestamps": duplicate_timestamps,
        "impossible_values": impossible_values,
        "hourly_days_audited": hourly_checked_days,
    }


def audit_fleet_historical_data(market_ids=None, target_month=None, target_day=None,
                                years=None, quiet=True):
    ids = set(market_ids or [])
    results = {}
    for spec in all_specs():
        if ids and spec.id not in ids:
            continue
        results[spec.id] = audit_historical_data(
            data_root=spec.data_root,
            target_month=target_month,
            target_day=target_day,
            market_id=spec.id,
            years=years,
            quiet=quiet,
        )
    return results


def has_corruption(result):
    if not result:
        return True
    return bool(result.get("duplicate_timestamps") or result.get("impossible_values"))


def audit_summary(results):
    markets = results or {}
    return {
        "market_count": len(markets),
        "missing_market_audits": sum(1 for result in markets.values() if not result),
        "markets_with_missing_days": sum(1 for result in markets.values() if result and result.get("missing_days")),
        "markets_with_sparse_days": sum(1 for result in markets.values() if result and result.get("sparse_days")),
        "markets_with_duplicates": sum(1 for result in markets.values() if result and result.get("duplicate_timestamps")),
        "markets_with_impossible_values": sum(1 for result in markets.values() if result and result.get("impossible_values")),
        "corruption_markets": [
            market_id for market_id, result in markets.items()
            if has_corruption(result)
        ],
    }


def jsonable_result(result):
    if result is None:
        return None
    out = dict(result)
    out["missing_days"] = [_date_text(item) for item in result.get("missing_days") or []]
    out["sparse_days"] = [
        [_date_text(day), count] for day, count in result.get("sparse_days") or []
    ]
    out["duplicate_timestamps"] = [
        [_date_text(day), timestamp] for day, timestamp in result.get("duplicate_timestamps") or []
    ]
    return out


def _coerce_year_arg(value):
    if not value:
        return None
    return [int(item) for item in str(value).split(",") if item.strip()]


def _print_fleet_summary(results):
    print("Fleet historical data audit")
    for market_id, result in sorted((results or {}).items()):
        if not result:
            print(f"- {market_id}: missing audit result")
            continue
        print(
            f"- {market_id}: missing={len(result.get('missing_days') or [])}, "
            f"sparse={len(result.get('sparse_days') or [])}, "
            f"duplicates={len(result.get('duplicate_timestamps') or [])}, "
            f"impossible={len(result.get('impossible_values') or [])}, "
            f"hourly_days={result.get('hourly_days_audited')}"
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Audit WU historical weather data for missing, sparse, duplicate, and impossible values."
    )
    parser.add_argument("--fleet", action="store_true", help="Audit every registered market.")
    parser.add_argument(
        "--market-id",
        action="append",
        dest="market_ids",
        help="Market id to audit. Repeat with --fleet to audit a subset.",
    )
    parser.add_argument("--data-root", default=None, help="Override data root for a single-market audit.")
    parser.add_argument("--target-month", type=int, default=None)
    parser.add_argument("--target-day", type=int, default=None)
    parser.add_argument("--years", default="", help="Comma-separated years; default 2000-2025.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--quiet", action="store_true", help="Suppress detailed single-market text output.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when duplicate timestamps, impossible values, or missing audit results are found.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    years = _coerce_year_arg(args.years)

    if args.fleet:
        results = audit_fleet_historical_data(
            market_ids=args.market_ids,
            target_month=args.target_month,
            target_day=args.target_day,
            years=years,
            quiet=True,
        )
        payload = {
            "schema_version": "historical_data_audit_fleet_v0.1",
            "summary": audit_summary(results),
            "markets": {
                market_id: jsonable_result(result)
                for market_id, result in results.items()
            },
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_fleet_summary(results)
        if args.strict and payload["summary"]["corruption_markets"]:
            sys.exit(2)
        return

    market_id = args.market_ids[0] if args.market_ids else None
    result = audit_historical_data(
        data_root=args.data_root,
        target_month=args.target_month,
        target_day=args.target_day,
        market_id=market_id,
        years=years,
        quiet=args.quiet or args.json,
    )
    if args.json:
        print(json.dumps(jsonable_result(result), indent=2, sort_keys=True))
    if args.strict and has_corruption(result):
        sys.exit(2)


if __name__ == "__main__":
    main()
