import csv
import json
import math
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path

from weather.model.feature_store import row_dewpoint_native, row_temp_native
from weather.sources.daily_summary import native_bucket, native_high
from weather.sources.wu_history import DEFAULT_DATA_ROOT
from weather.model.model_constants import (
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


HISTORICAL_TARGET_CACHE_MAX_ENTRIES = 128
CLIMATOLOGY_FALLBACK_MIN_ROWS = 30
CLIMATOLOGY_FALLBACK_WINDOWS = (HISTORY_WINDOW_DAYS, 21, 45, 90, 183)
CLIMATOLOGY_FALLBACK_ALPHA = 0.05
CLIMATOLOGY_FALLBACK_LOWER_QUANTILE = 0.02
CLIMATOLOGY_FALLBACK_UPPER_QUANTILE = 0.98
CLIMATOLOGY_FALLBACK_SUPPORT_MARGIN = 2


class ClimatologyMixin:
    """Historical target-season climatology cache and conditional lookups."""

    def _historical_cache(self):
        cache = getattr(type(self), "_historical_target_cache", None)
        if isinstance(cache, OrderedDict):
            return cache
        cache = OrderedDict(cache or {})
        type(self)._historical_target_cache = cache
        return cache

    def _historical_cache_get(self, cache_key):
        cache = self._historical_cache()
        if cache_key not in cache:
            return None
        cache.move_to_end(cache_key)
        return cache[cache_key]

    def _historical_cache_put(self, cache_key, payload):
        cache = self._historical_cache()
        cache[cache_key] = payload
        cache.move_to_end(cache_key)
        max_entries = int(
            getattr(type(self), "_historical_target_cache_max_entries", HISTORICAL_TARGET_CACHE_MAX_ENTRIES)
            or HISTORICAL_TARGET_CACHE_MAX_ENTRIES
        )
        max_entries = max(1, max_entries)
        while len(cache) > max_entries:
            cache.popitem(last=False)
        return payload

    def historical_target_cache(self):
        # Keyed by market so Toronto and NYC caches never collide, and read from
        # the market's own data root (NYC analogs/transitions use NYC history).
        cache_key = f"{self.spec.id}:{self.target_date.isoformat()}"
        cached = self._historical_cache_get(cache_key)
        if cached is not None:
            return cached

        summary_path = self.spec.data_root / "daily" / "daily_summary.csv"
        if not summary_path.exists():
            lo, hi = round(self.spec.c_to_native(8)), round(self.spec.c_to_native(35))
            return self._historical_cache_put(cache_key, {
                "daily": {},
                "by_date": {},
                "bucket_space": list(range(lo, hi)),
                "conditional": {},
                "regime": {},
            })

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
                    temp_native = row_temp_native(row)
                    dewpoint_native = row_dewpoint_native(row)
                    by_date[date.fromisoformat(row["local_date"])].append({
                        "minute_of_day": minute_of_day,
                        "minute": int(row.get("minute") or 0),
                        # The serving/model stack is native-unit internally.
                        # Keep ``*_c`` aliases only for historical feature
                        # compatibility while exposing native names first.
                        "temp_native": temp_native,
                        "temp_c": temp_native,
                        "dewpoint_native": dewpoint_native,
                        "dewpoint_c": dewpoint_native,
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
        return self._historical_cache_put(cache_key, {
            "daily": daily,
            "by_date": dict(by_date),
            "bucket_space": bucket_space or list(range(8, 35)),
            "conditional": {},
            "regime": {},
        })

    def wide_uniform_climatology_prior(self):
        prior_lo = round(self.spec.c_to_native(8))
        prior_hi = round(self.spec.c_to_native(33))
        return {
            temp: 1.0 / (prior_hi - prior_lo)
            for temp in range(prior_lo, prior_hi)
        }

    def climatology_fallback_prior(self):
        """Return the thin-history prior in the market's native bucket unit."""
        if getattr(self.spec, "id", None) == "toronto":
            return self.wide_uniform_climatology_prior()

        summary_path = self.spec.data_root / "daily" / "daily_summary.csv"
        if not summary_path.exists():
            return self.wide_uniform_climatology_prior()

        buckets = self._fallback_prior_buckets(summary_path)
        if not buckets:
            return self.wide_uniform_climatology_prior()

        support = self._fallback_prior_support(buckets)
        return self.smoothed_distribution(
            buckets,
            support,
            alpha=CLIMATOLOGY_FALLBACK_ALPHA,
        )

    def _fallback_prior_buckets(self, summary_path):
        rows = []
        with Path(summary_path).open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    local_date = date.fromisoformat(row["local_date"])
                except (KeyError, ValueError):
                    continue
                if local_date.year >= self.target_date.year:
                    continue
                if int(row.get("row_count") or 0) < HISTORY_MIN_ROW_COUNT:
                    continue
                bucket = native_bucket(row)
                if bucket is None:
                    continue
                reference_date = self._fallback_reference_date(local_date)
                rows.append((reference_date, int(bucket)))

        if not rows:
            return []

        target_reference = self._fallback_reference_date(self.target_date)
        selected = []
        for window_days in CLIMATOLOGY_FALLBACK_WINDOWS:
            selected = [
                bucket
                for reference_date, bucket in rows
                if abs((reference_date - target_reference).days) <= window_days
            ]
            if len(selected) >= CLIMATOLOGY_FALLBACK_MIN_ROWS:
                return selected
        return selected

    def _fallback_reference_date(self, value):
        try:
            return value.replace(year=2000)
        except ValueError:
            return date(2000, 2, 28)

    def _fallback_prior_support(self, buckets):
        ordered = sorted(int(bucket) for bucket in buckets)
        lower = self._percentile(ordered, CLIMATOLOGY_FALLBACK_LOWER_QUANTILE)
        upper = self._percentile(ordered, CLIMATOLOGY_FALLBACK_UPPER_QUANTILE)
        lo = math.floor(lower) - CLIMATOLOGY_FALLBACK_SUPPORT_MARGIN
        hi = math.ceil(upper) + CLIMATOLOGY_FALLBACK_SUPPORT_MARGIN
        if hi < lo:
            lo = min(ordered)
            hi = max(ordered)
        return list(range(int(lo), int(hi) + 1))

    def _percentile(self, ordered_values, quantile):
        if not ordered_values:
            return None
        if len(ordered_values) == 1:
            return float(ordered_values[0])
        position = (len(ordered_values) - 1) * quantile
        lower_index = int(math.floor(position))
        upper_index = int(math.ceil(position))
        if lower_index == upper_index:
            return float(ordered_values[lower_index])
        weight = position - lower_index
        return (
            ordered_values[lower_index] * (1.0 - weight)
            + ordered_values[upper_index] * weight
        )

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
            latest_bucket = self.round_half_up(row_temp_native(latest))
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
            row_temp_native(row) for row in rows
            if row_temp_native(row) is not None
            and row.get("minute_of_day") is not None
            and row["minute_of_day"] <= cutoff
        ]
        return max(values) if values else None
