import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from daily_summary import native_bucket, native_high
from wu_history import DEFAULT_DATA_ROOT
from model_constants import (
    DEFAULT_MARKET_CONFIG,
    TARGET_DATE,
    TARGET_DATE_STR,
    WEATHER_COM_KEY,
    CYYZ_HISTORY_ID,
    CYYZ_ICAO,
    PEARSON_LAT,
    PEARSON_LON,
    HISTORY_MIN_ROW_COUNT,
    HISTORY_WINDOW_DAYS,
    INTRADAY_CUTOFF_HOURS,
    LIVE_CACHE_MAX_AGE_MINUTES,
    ML_MODEL_VERSION,
    MODEL_VERSION_HGB,
    MODEL_VERSION_LR,
    MODEL_VERSION_EMPIRICAL,
    _UNLOADED,
)


class ClimatologyMixin:
    """Historical target-season climatology cache and conditional lookups."""

    def historical_target_cache(self):
        # Keyed by market so Toronto and NYC caches never collide, and read from
        # the market's own data root (NYC analogs/transitions use NYC history).
        cache_key = f"{self.spec.id}:{self.target_date.isoformat()}"
        if cache_key in type(self)._historical_target_cache:
            return type(self)._historical_target_cache[cache_key]

        summary_path = self.spec.data_root / "daily" / "daily_summary.csv"
        if not summary_path.exists():
            lo, hi = round(self.spec.c_to_native(8)), round(self.spec.c_to_native(35))
            type(self)._historical_target_cache[cache_key] = {
                "daily": {},
                "by_date": {},
                "bucket_space": list(range(lo, hi)),
                "conditional": {},
                "regime": {},
            }
            return type(self)._historical_target_cache[cache_key]

        reference_year = 2000
        target_reference = date(reference_year, self.target_date.month, self.target_date.day)
        daily = {}
        with summary_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                local_date = date.fromisoformat(row["local_date"])
                if local_date.year >= self.target_date.year:
                    continue
                if int(row.get("row_count") or 0) < HISTORY_MIN_ROW_COUNT:
                    continue
                bucket = native_bucket(row)
                if bucket is None:
                    continue
                reference_date = local_date.replace(year=reference_year)
                if abs((reference_date - target_reference).days) > HISTORY_WINDOW_DAYS:
                    continue
                daily[local_date] = {
                    "bucket": bucket,
                    "max_temp_native": native_high(row),
                    "condition_mode": row.get("condition_mode"),
                    "cloud_mode": row.get("cloud_mode"),
                }

        needed_paths = defaultdict(set)
        for local_date in daily:
            path = (
                self.spec.data_root
                / "hourly"
                / f"year={local_date.year}"
                / f"month={local_date.month:02d}"
                / "observations.jsonl"
            )
            needed_paths[path].add(local_date.isoformat())

        by_date = defaultdict(list)
        for path, needed_dates in needed_paths.items():
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    if row.get("local_date") not in needed_dates:
                        continue
                    minute_of_day = self.minute_of_day(row.get("local_time"))
                    if minute_of_day is None:
                        continue
                    by_date[date.fromisoformat(row["local_date"])].append({
                        "minute_of_day": minute_of_day,
                        "minute": int(row.get("minute") or 0),
                        # The serving/model stack is native-unit internally.
                        # Storage keeps true Celsius in ``*_c``; map native
                        # hourly values into the historical feature shape.
                        "temp_c": self.to_number(row.get("temp_native"))
                                  if row.get("temp_native") not in (None, "")
                                  else self.to_number(row.get("temp_c")),
                        "dewpoint_c": self.to_number(row.get("dewpoint_native"))
                                      if row.get("dewpoint_native") not in (None, "")
                                      else self.to_number(row.get("dewpoint_c")),
                        "humidity": self.to_number(row.get("humidity")),
                        "pressure": self.to_number(row.get("pressure")),
                        "wind": row.get("wind_cardinal"),
                        "wind_kmh": self.to_number(row.get("wind_speed_kmh")),
                        "condition": row.get("condition"),
                        "clouds": row.get("clouds"),
                    })

        for rows in by_date.values():
            rows.sort(key=lambda row: row["minute_of_day"])

        daily = {
            local_date: row
            for local_date, row in daily.items()
            if local_date in by_date
        }
        bucket_space = sorted({row["bucket"] for row in daily.values()})
        type(self)._historical_target_cache[cache_key] = {
            "daily": daily,
            "by_date": dict(by_date),
            "bucket_space": bucket_space or list(range(8, 35)),
            "conditional": {},
            "regime": {},
        }
        return type(self)._historical_target_cache[cache_key]

    def historical_intraday_distribution(self, observed_bucket, cutoff_hour):
        if observed_bucket is None:
            return None
        cache = self.historical_target_cache()
        key = (int(observed_bucket), int(cutoff_hour))
        if key in cache["conditional"]:
            return cache["conditional"][key]

        cutoff = cutoff_hour * 60
        buckets = []
        for local_date, daily in cache["daily"].items():
            high_so_far = self.historical_max_until(
                cache["by_date"].get(local_date, []), cutoff
            )
            if high_so_far is None:
                continue
            if self.round_half_up(high_so_far) == observed_bucket:
                buckets.append(daily["bucket"])

        if len(buckets) < 8:
            cache["conditional"][key] = None
            return None

        result = {
            "n": len(buckets),
            "bucket": observed_bucket,
            "hour": cutoff_hour,
            "probabilities": self.smoothed_distribution(
                buckets, cache["bucket_space"], alpha=0.05
            ),
        }
        cache["conditional"][key] = result
        return result

    def historical_current_distribution(self, current_bucket, cutoff_hour):
        if current_bucket is None:
            return None
        cache = self.historical_target_cache()
        current_cache = cache.setdefault("current", {})
        key = (int(current_bucket), int(cutoff_hour))
        if key in current_cache:
            return current_cache[key]

        cutoff = cutoff_hour * 60
        buckets = []
        for local_date, daily in cache["daily"].items():
            rows = [
                row for row in cache["by_date"].get(local_date, [])
                if row.get("minute_of_day") is not None
                and row["minute_of_day"] <= cutoff
            ]
            if not rows:
                continue
            latest = rows[-1]
            latest_bucket = self.round_half_up(latest.get("temp_c"))
            if latest_bucket == current_bucket:
                buckets.append(daily["bucket"])

        if len(buckets) < 8:
            current_cache[key] = None
            return None

        result = {
            "n": len(buckets),
            "bucket": current_bucket,
            "hour": cutoff_hour,
            "probabilities": self.smoothed_distribution(
                buckets, cache["bucket_space"], alpha=0.05
            ),
        }
        current_cache[key] = result
        return result

    def historical_regime_distribution(self, regime_type, group):
        if not group:
            return None
        cache = self.historical_target_cache()
        key = (regime_type, group)
        if key in cache["regime"]:
            return cache["regime"][key]

        buckets = []
        for local_date, daily in cache["daily"].items():
            rows = [
                row for row in cache["by_date"].get(local_date, [])
                if 10 * 60 <= row["minute_of_day"] <= 16 * 60
            ]
            if regime_type == "wind":
                row_group = self.wind_group(self.mode(row.get("wind") for row in rows))
            else:
                row_group = self.cloud_group(
                    self.mode(row.get("condition") for row in rows) or daily.get("condition_mode"),
                    self.mode(row.get("clouds") for row in rows) or daily.get("cloud_mode"),
                )
            if row_group == group:
                buckets.append(daily["bucket"])

        if len(buckets) < 20:
            cache["regime"][key] = None
            return None

        result = {
            "n": len(buckets),
            "group": group,
            "probabilities": self.smoothed_distribution(
                buckets, cache["bucket_space"], alpha=0.10
            ),
        }
        cache["regime"][key] = result
        return result

    def historical_max_until(self, rows, cutoff):
        values = [
            row.get("temp_c") for row in rows
            if row.get("temp_c") is not None
            and row.get("minute_of_day") is not None
            and row["minute_of_day"] <= cutoff
        ]
        return max(values) if values else None
