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
import hashlib
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from model_sources import request_with_retries
from market_registry import TORONTO, spec_for_id
from daily_summary import native_to_c

HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
RICH_SCHEMA_VERSION = "forecast_history_long_v2"
DAILY_ISSUE_SCHEMA_VERSION = "forecast_history_daily_issue_v1"
DEFAULT_PREVIOUS_RUN_LEADS = (1, 2, 3, 4, 5, 6, 7)
DEFAULT_PREVIOUS_RUN_START_YEAR = 2021
RICH_FORECAST_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_model",
    "temperature_unit",
    "target_date",
    "issue_time",
    "issue_time_basis",
    "lead_hours",
    "lead_days",
    "valid_time",
    "forecast_kind",
    "target_temp_native",
    "target_temp_c",
    "cloud_cover",
    "low_cloud",
    "mid_cloud",
    "high_cloud",
    "shortwave_radiation",
    "wind_speed_kmh",
    "source_url",
    "payload_hash",
]
DAILY_ISSUE_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_model",
    "temperature_unit",
    "target_date",
    "issue_time",
    "issue_time_basis",
    "lead_hours",
    "lead_days",
    "forecast_high_native",
    "forecast_high_c",
    "hourly_rows",
]


def data_root_for(spec):
    return Path("data") / "forecast_history" / spec.icao.lower()


def daily_path_for(spec):
    return data_root_for(spec) / "forecast_daily.csv"


def long_path_for(spec):
    return data_root_for(spec) / "forecast_long.csv"


def daily_issue_path_for(spec):
    return data_root_for(spec) / "forecast_daily_by_issue.csv"


# Toronto defaults so load_forecast_daily() and existing callers keep working.
DATA_ROOT = data_root_for(TORONTO)
DAILY_PATH = daily_path_for(TORONTO)
MANIFEST_PATH = DATA_ROOT / "manifest.json"
# Generous target-season window so one day's +/-7 climatology window is covered
# for any late-May / early-June target date. One API call per year covers it.
SEASON_START = (5, 10)
SEASON_END = (6, 15)


def season_start_end(year):
    start = f"{year}-{SEASON_START[0]:02d}-{SEASON_START[1]:02d}"
    end = f"{year}-{SEASON_END[0]:02d}-{SEASON_END[1]:02d}"
    return start, end


def forecast_payload_hash(row):
    payload = {key: row.get(key) for key in row if key != "payload_hash"}
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def to_float(value):
    if value in (None, "", "MSNG"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def local_valid_datetime(raw_time, spec):
    dt = datetime.fromisoformat(str(raw_time))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=spec.tz)
    return dt.astimezone(spec.tz)


def rich_row(
    spec,
    source,
    source_model,
    target_date,
    valid_time,
    target_temp_native,
    issue_time="",
    issue_time_basis="",
    lead_days="",
    cloud_cover=None,
    low_cloud=None,
    mid_cloud=None,
    high_cloud=None,
    shortwave_radiation=None,
    wind_speed_kmh=None,
    source_url=HIST_FORECAST_URL,
):
    lead_hours = ""
    if lead_days not in ("", None):
        lead_hours = int(lead_days) * 24
    row = {
        "schema_version": RICH_SCHEMA_VERSION,
        "market": spec.id,
        "station": spec.icao,
        "source": source,
        "source_model": source_model,
        "temperature_unit": spec.display_unit,
        "target_date": target_date,
        "issue_time": issue_time,
        "issue_time_basis": issue_time_basis,
        "lead_hours": lead_hours,
        "lead_days": lead_days,
        "valid_time": valid_time,
        "forecast_kind": "hourly",
        "target_temp_native": target_temp_native,
        "target_temp_c": native_to_c(target_temp_native, spec.display_unit),
        "cloud_cover": cloud_cover,
        "low_cloud": low_cloud,
        "mid_cloud": mid_cloud,
        "high_cloud": high_cloud,
        "shortwave_radiation": shortwave_radiation,
        "wind_speed_kmh": wind_speed_kmh,
        "source_url": source_url,
    }
    row["payload_hash"] = forecast_payload_hash(row)
    return row


def historical_forecast_rows(payload, spec=TORONTO, source_model="best_match"):
    hourly = payload.get("hourly", {}) or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    clouds = hourly.get("cloud_cover") or []
    low_clouds = hourly.get("cloud_cover_low") or []
    mid_clouds = hourly.get("cloud_cover_mid") or []
    high_clouds = hourly.get("cloud_cover_high") or []
    solar = hourly.get("shortwave_radiation") or []
    winds = hourly.get("wind_speed_10m") or []
    rows = []
    for index, raw_time in enumerate(times):
        temp = to_float(temps[index] if index < len(temps) else None)
        if temp is None or not raw_time:
            continue
        valid_dt = local_valid_datetime(raw_time, spec)
        rows.append(rich_row(
            spec,
            source="open_meteo_historical_forecast",
            source_model=source_model,
            target_date=valid_dt.date().isoformat(),
            valid_time=valid_dt.isoformat(),
            target_temp_native=temp,
            issue_time="",
            issue_time_basis="stitched_continuous_archive",
            lead_days="",
            cloud_cover=to_float(clouds[index] if index < len(clouds) else None),
            low_cloud=to_float(low_clouds[index] if index < len(low_clouds) else None),
            mid_cloud=to_float(mid_clouds[index] if index < len(mid_clouds) else None),
            high_cloud=to_float(high_clouds[index] if index < len(high_clouds) else None),
            shortwave_radiation=to_float(solar[index] if index < len(solar) else None),
            wind_speed_kmh=to_float(winds[index] if index < len(winds) else None),
            source_url=HIST_FORECAST_URL,
        ))
    return rows


def previous_run_rows(payload, spec=TORONTO, leads=DEFAULT_PREVIOUS_RUN_LEADS, source_model="best_match"):
    hourly = payload.get("hourly", {}) or {}
    times = hourly.get("time") or []
    rows = []
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        valid_dt = local_valid_datetime(raw_time, spec)
        for lead in leads:
            key = f"temperature_2m_previous_day{lead}"
            values = hourly.get(key) or []
            temp = to_float(values[index] if index < len(values) else None)
            if temp is None:
                continue
            issue_date = valid_dt.date() - timedelta(days=int(lead))
            issue_dt = datetime(issue_date.year, issue_date.month, issue_date.day, tzinfo=spec.tz)
            rows.append(rich_row(
                spec,
                source="open_meteo_previous_runs",
                source_model=source_model,
                target_date=valid_dt.date().isoformat(),
                valid_time=valid_dt.isoformat(),
                target_temp_native=temp,
                issue_time=issue_dt.isoformat(),
                issue_time_basis="fixed_lead_day_offset",
                lead_days=int(lead),
                source_url=PREVIOUS_RUNS_URL,
            ))
    return rows


def daily_issue_rows(hourly_rows):
    grouped = defaultdict(list)
    for row in hourly_rows:
        temp = to_float(row.get("target_temp_native"))
        if temp is None:
            continue
        key = (
            row.get("market"),
            row.get("station"),
            row.get("source"),
            row.get("source_model"),
            row.get("temperature_unit"),
            row.get("target_date"),
            row.get("issue_time"),
            row.get("issue_time_basis"),
            row.get("lead_hours"),
            row.get("lead_days"),
        )
        grouped[key].append(temp)
    rows = []
    for key, temps in sorted(grouped.items(), key=lambda item: tuple("" if value is None else str(value) for value in item[0])):
        (
            market,
            station,
            source,
            source_model,
            unit,
            target_date,
            issue_time,
            issue_time_basis,
            lead_hours,
            lead_days,
        ) = key
        high = max(temps)
        rows.append({
            "schema_version": DAILY_ISSUE_SCHEMA_VERSION,
            "market": market,
            "station": station,
            "source": source,
            "source_model": source_model,
            "temperature_unit": unit,
            "target_date": target_date,
            "issue_time": issue_time,
            "issue_time_basis": issue_time_basis,
            "lead_hours": lead_hours,
            "lead_days": lead_days,
            "forecast_high_native": high,
            "forecast_high_c": native_to_c(high, unit),
            "hourly_rows": len(temps),
        })
    return rows


def compatibility_daily_from_rows(hourly_rows):
    daily = {}
    for row in hourly_rows:
        if row.get("source") != "open_meteo_historical_forecast":
            continue
        temp = to_float(row.get("target_temp_native"))
        day = row.get("target_date")
        if temp is None or not day:
            continue
        daily[day] = max(daily.get(day, float("-inf")), temp)
    return {d: v for d, v in daily.items() if v != float("-inf")}


def load_forecast_profiles(path=None, source="open_meteo_historical_forecast"):
    """target_date -> hourly forecast rows in the market's native unit.

    This powers cutoff-specific forecast-shape features without leaking the
    observed outcome. Old v1 files simply return ``None`` for newly added
    radiation/cloud-layer fields until the archive is backfilled.
    """
    path = Path(path or long_path_for(TORONTO))
    if not path.exists():
        return {}
    profiles = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if source and row.get("source") != source:
                continue
            target_date = row.get("target_date")
            if not target_date:
                continue
            minute = ""
            valid_time = row.get("valid_time")
            if valid_time:
                try:
                    valid_dt = datetime.fromisoformat(str(valid_time).replace("Z", "+00:00"))
                    minute = valid_dt.hour * 60 + valid_dt.minute
                except ValueError:
                    minute = ""
            profiles[target_date].append({
                "minute_of_day": minute,
                "time": valid_time,
                "temp_c": to_float(row.get("target_temp_native") or row.get("target_temp_c")),
                "cloud_cover": to_float(row.get("cloud_cover")),
                "low_cloud": to_float(row.get("low_cloud") or row.get("cloud_cover_low")),
                "mid_cloud": to_float(row.get("mid_cloud") or row.get("cloud_cover_mid")),
                "high_cloud": to_float(row.get("high_cloud") or row.get("cloud_cover_high")),
                "solar": to_float(row.get("shortwave_radiation") or row.get("solar")),
                "wind_kmh": to_float(row.get("wind_speed_kmh")),
            })
    return dict(profiles)


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def fetch_historical_forecast_payload(year, spec=TORONTO, timeout=30):
    start, end = season_start_end(year)

    def _once():
        resp = requests.get(HIST_FORECAST_URL, params={
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": start,
            "end_date": end,
            "hourly": (
                "temperature_2m,cloud_cover,cloud_cover_low,cloud_cover_mid,"
                "cloud_cover_high,shortwave_radiation,wind_speed_10m"
            ),
            "temperature_unit": spec.om_temperature_unit,
            "wind_speed_unit": "kmh",
            "timezone": spec.timezone,
        }, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    return request_with_retries(_once)


def fetch_previous_runs_payload(
    year,
    spec=TORONTO,
    leads=DEFAULT_PREVIOUS_RUN_LEADS,
    source_model="best_match",
    timeout=30,
):
    start, end = season_start_end(year)
    hourly = ",".join(f"temperature_2m_previous_day{lead}" for lead in leads)

    def _once():
        params = {
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": start,
            "end_date": end,
            "hourly": hourly,
            "temperature_unit": spec.om_temperature_unit,
            "timezone": spec.timezone,
        }
        if source_model and source_model != "best_match":
            params["models"] = source_model
        resp = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    return request_with_retries(_once)


def fetch_year_forecast(year, spec=TORONTO, timeout=30):
    """Return {local_date_iso: forecast_daily_max_native} for compatibility."""
    payload = fetch_historical_forecast_payload(year, spec, timeout=timeout)
    return compatibility_daily_from_rows(historical_forecast_rows(payload, spec))


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


def backfill(
    start_year,
    end_year,
    spec=TORONTO,
    pause=0.4,
    include_previous_runs=True,
    previous_runs_start_year=DEFAULT_PREVIOUS_RUN_START_YEAR,
    previous_runs_leads=DEFAULT_PREVIOUS_RUN_LEADS,
    previous_runs_model="best_match",
):
    data_root = data_root_for(spec)
    daily_path = daily_path_for(spec)
    long_path = long_path_for(spec)
    daily_issue_path = daily_issue_path_for(spec)
    manifest_path = data_root / "manifest.json"
    data_root.mkdir(parents=True, exist_ok=True)
    rows = {}
    rich_rows = []
    per_year = {}
    previous_per_year = {}
    for year in range(start_year, end_year + 1):
        try:
            payload = fetch_historical_forecast_payload(year, spec)
            year_rows = historical_forecast_rows(payload, spec)
            year_daily = compatibility_daily_from_rows(year_rows)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  {year}: ERROR {type(exc).__name__}: {exc}")
            per_year[year] = 0
            year_rows = []
            year_daily = {}
        rich_rows.extend(year_rows)
        if include_previous_runs and year >= int(previous_runs_start_year):
            try:
                previous_payload = fetch_previous_runs_payload(
                    year,
                    spec,
                    leads=previous_runs_leads,
                    source_model=previous_runs_model,
                )
                previous_rows = previous_run_rows(
                    previous_payload,
                    spec,
                    leads=previous_runs_leads,
                    source_model=previous_runs_model,
                )
            except Exception as exc:  # noqa: BLE001 - previous-runs availability varies by model/year
                print(f"  {year}: previous-runs ERROR {type(exc).__name__}: {exc}")
                previous_rows = []
            rich_rows.extend(previous_rows)
            previous_per_year[year] = len(previous_rows)
        elif include_previous_runs:
            previous_per_year[year] = 0
        if not year_daily:
            continue
        per_year[year] = len(year_daily)
        rows.update(year_daily)
        print(f"  {year}: {len(year_daily)} forecast-days "
              f"({min(year_daily.values()):.1f}..{max(year_daily.values()):.1f} {spec.display_unit})"
              if year_daily else f"  {year}: no data")
        time.sleep(pause)

    ordered = sorted(rows.items())
    with daily_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_date", "forecast_high_c"])
        for d, v in ordered:
            writer.writerow([d, f"{v:.1f}"])

    rich_rows.sort(key=lambda row: (
        row.get("target_date") or "",
        row.get("source") or "",
        str(row.get("lead_days") or ""),
        row.get("valid_time") or "",
    ))
    write_csv(long_path, RICH_FORECAST_COLUMNS, rich_rows)
    issue_rows = daily_issue_rows(rich_rows)
    write_csv(daily_issue_path, DAILY_ISSUE_COLUMNS, issue_rows)

    covered_years = sorted(y for y, n in per_year.items() if n > 0)
    manifest = {
        "endpoints": {
            "historical_forecast": HIST_FORECAST_URL,
            "previous_runs": PREVIOUS_RUNS_URL,
        },
        "market": spec.id,
        "params": {"latitude": spec.lat, "longitude": spec.lon,
                   "hourly": (
                       "temperature_2m,cloud_cover,cloud_cover_low,"
                       "cloud_cover_mid,cloud_cover_high,shortwave_radiation,"
                       "wind_speed_10m"
                   ), "timezone": spec.timezone},
        "previous_runs": {
            "enabled": bool(include_previous_runs),
            "start_year": int(previous_runs_start_year),
            "leads": list(previous_runs_leads),
            "model": previous_runs_model,
            "per_year_rows": previous_per_year,
        },
        "schema_versions": {
            "long": RICH_SCHEMA_VERSION,
            "daily_by_issue": DAILY_ISSUE_SCHEMA_VERSION,
            "compatibility_daily": "forecast_daily_legacy_v1",
        },
        "season_window": {"start": list(SEASON_START), "end": list(SEASON_END)},
        "generated_at": datetime.now().isoformat(),
        "total_days": len(ordered),
        "long_rows": len(rich_rows),
        "daily_issue_rows": len(issue_rows),
        "covered_years": covered_years,
        "per_year_days": per_year,
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)

    print(f"\n=== Coverage ({spec.id}) ===")
    print(f"  years with data : {covered_years[0] if covered_years else '-'}"
          f"..{covered_years[-1] if covered_years else '-'} ({len(covered_years)} years)")
    print(f"  total forecast-days: {len(ordered)}")
    print(f"  long source/issue rows: {len(rich_rows)}")
    print(f"  daily source/issue rows: {len(issue_rows)}")
    print(f"  written to {daily_path}")
    return manifest


def coverage(spec=TORONTO):
    index = load_forecast_daily(daily_path_for(spec))
    if not index:
        print(f"No forecast history for {spec.id}. Run: python -m src.forecast_history --market {spec.id} backfill")
        return
    years = sorted({d[:4] for d in index})
    print(f"[{spec.id}] Stored forecast-days: {len(index)}  years {years[0]}..{years[-1]} ({len(years)} years)")
    manifest_path = data_root_for(spec) / "manifest.json"
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as handle:
            man = json.load(handle)
        print("Per-year days:", man.get("per_year_days"))
        print("Long rows:", man.get("long_rows"), "Daily issue rows:", man.get("daily_issue_rows"))


def parse_leads(value):
    if not value:
        return DEFAULT_PREVIOUS_RUN_LEADS
    return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())


def main():
    parser = argparse.ArgumentParser(description="Backfill archived Open-Meteo forecasts.")
    parser.add_argument("--market", default="toronto",
                        help="Registered market id (toronto, nyc, ...); sets geo + data root.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--start-year", type=int, default=2015)
    b.add_argument("--end-year", type=int, default=datetime.now().year)
    b.add_argument("--pause", type=float, default=0.4)
    b.add_argument("--previous-runs", dest="previous_runs", action="store_true", default=True)
    b.add_argument("--no-previous-runs", dest="previous_runs", action="store_false")
    b.add_argument("--previous-runs-start-year", type=int, default=DEFAULT_PREVIOUS_RUN_START_YEAR)
    b.add_argument("--previous-runs-leads", default=",".join(str(item) for item in DEFAULT_PREVIOUS_RUN_LEADS))
    b.add_argument("--previous-runs-model", default="best_match")
    sub.add_parser("coverage")
    args = parser.parse_args()
    spec = spec_for_id(args.market)

    if args.command == "backfill":
        backfill(
            args.start_year,
            args.end_year,
            spec,
            pause=args.pause,
            include_previous_runs=args.previous_runs,
            previous_runs_start_year=args.previous_runs_start_year,
            previous_runs_leads=parse_leads(args.previous_runs_leads),
            previous_runs_model=args.previous_runs_model,
        )
    elif args.command == "coverage":
        coverage(spec)


if __name__ == "__main__":
    main()
