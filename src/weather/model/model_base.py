import math
from collections import Counter
from datetime import datetime

from weather.model.feature_store import (
    row_air_temp_native,
    row_dewpoint_native,
    row_forecast_high_native,
    row_max_native,
    row_max_since_7am_native,
    row_same_day_max_native,
    row_temp_native,
)


SETTLEMENT_PRINT_ALIAS_WINDOW_MINUTES = 10


class ModelUtilsMixin:
    """Stateless numeric, regime, and source-access helpers shared model-wide."""

    def source_rows_until_cutoff(self, rows, cutoff_hour):
        cutoff = cutoff_hour * 60
        filtered = []
        for row in rows or []:
            minute = self.minute_of_day(row.get("time"))
            if minute is not None and minute <= cutoff:
                filtered.append(row)
        return filtered

    def row_temp_native(self, row):
        return row_temp_native(row)

    def row_dewpoint_native(self, row):
        return row_dewpoint_native(row)

    def row_air_temp_native(self, row):
        return row_air_temp_native(row)

    def row_forecast_high_native(self, row):
        return row_forecast_high_native(row)

    def row_max_native(self, row):
        return row_max_native(row)

    def row_max_since_7am_native(self, row):
        return row_max_since_7am_native(row)

    def row_same_day_max_native(self, row):
        return row_same_day_max_native(row)

    def latest_source_row(self, rows):
        latest = None
        latest_minute = None
        for row in rows or []:
            minute = self.minute_of_day(row.get("time"))
            if minute is None:
                continue
            if latest_minute is None or minute > latest_minute:
                latest = row
                latest_minute = minute
        return latest, latest_minute

    def aliased_settlement_print_minute(
        self,
        minute,
        wall_cutoff_hour,
        alias_window=SETTLEMENT_PRINT_ALIAS_WINDOW_MINUTES,
    ):
        if minute is None:
            return None
        try:
            minute = int(minute)
            wall_cutoff_minute = int(wall_cutoff_hour) * 60
        except (TypeError, ValueError):
            return None
        next_hour_minute = ((minute // 60) + 1) * 60
        if (
            next_hour_minute <= wall_cutoff_minute
            and 0 < (next_hour_minute - minute) <= int(alias_window)
        ):
            return next_hour_minute
        return minute

    def live_wind_group(self, current, weather_forecast):
        wind = current.get("wind")
        if not wind:
            rows = weather_forecast.get("rows") or []
            wind = self.mode(row.get("wind") for row in rows[:4])
        return self.wind_group(wind)

    def live_cloud_group(self, current, eccc_city, weather_forecast):
        condition = current.get("condition")
        cloud = current.get("cloud_phrase")
        if not condition:
            rows = weather_forecast.get("rows") or []
            condition = self.mode(row.get("condition") for row in rows[:4])
        if not cloud:
            cloud = eccc_city.get("forecast_cloud")
        return self.cloud_group(condition, cloud)

    def wind_group(self, wind):
        wind = str(wind or "").upper()
        if wind in {"E", "ENE", "ESE", "SE"}:
            return "E-SE/onshore-ish"
        if wind in {"S", "SSW", "SW", "WSW"}:
            return "S-SW"
        if wind in {"W", "WNW", "NW"}:
            return "W-NW"
        if wind in {"N", "NNE", "NE"}:
            return "N-NE"
        if wind == "SSE":
            return "SSE"
        return "Other/variable" if wind else None

    def cloud_group(self, condition, cloud):
        text = f"{condition or ''} {cloud or ''}".lower()
        if any(word in text for word in ("rain", "drizzle", "shower", "thunder", "snow")):
            return "Precip"
        if any(word in text for word in ("fog", "haze", "mist")):
            return "Fog/haze"
        if any(word in text for word in ("fair", "clear", "clr")):
            return "Fair/clear"
        if any(word in text for word in ("partly", "sct", "few")):
            return "Partly cloudy"
        if any(word in text for word in ("mostly cloudy", "cloudy", "ovc", "bkn", "overcast")):
            return "Mostly cloudy/overcast"
        return "Other" if text.strip() else None

    def microclimate_features(self, wind_group, wind_speed_kmh=None):
        """Market-aware onshore/lake-breeze indicators for item 27."""
        west_coast = {"los-angeles", "san-francisco", "seattle"}
        east_or_lake = {"toronto", "nyc", "miami", "houston"}
        market_id = getattr(self, "market_id", "")
        if market_id in west_coast:
            onshore_group = "W-NW"
        elif market_id in east_or_lake:
            onshore_group = "E-SE/onshore-ish"
        else:
            onshore_group = None
        try:
            wind_speed = float(wind_speed_kmh) if wind_speed_kmh is not None else 0.0
        except (TypeError, ValueError):
            wind_speed = 0.0
        onshore = 1.0 if onshore_group and wind_group == onshore_group else 0.0
        return {
            "onshore_flow": onshore,
            "onshore_wind_speed_kmh": wind_speed if onshore else 0.0,
            "lake_breeze_proxy": 1.0 if market_id == "toronto" and onshore and wind_speed >= 8.0 else 0.0,
        }

    def minute_of_day(self, value):
        if not value:
            return None
        try:
            v = str(value)
            if "T" in v:
                v = v.split("T")[1]
            hour, minute = v.split(":")[:2]
            return int(hour) * 60 + int(minute)
        except (TypeError, ValueError, IndexError):
            return None

    def mode(self, values):
        cleaned = [value for value in values if value not in (None, "")]
        if not cleaned:
            return None
        return Counter(cleaned).most_common(1)[0][0]

    def source_data(self, sources, name):
        item = sources.get(name, {}) or {}
        if not item.get("ok"):
            return {}
        data = item.get("data", {}) or {}
        if data.get("target_date_match") is False:
            return {}
        return self.target_date_filtered_source_data(name, data)

    def target_date_filtered_source_data(self, name, data):
        if name == "wu_history":
            return self.target_date_filtered_wu_history(data)
        if name == "eccc_swob":
            return self.target_date_filtered_eccc_swob(data)
        return data

    def target_date_iso(self):
        target_date = getattr(self, "target_date", None)
        return target_date.isoformat() if hasattr(target_date, "isoformat") else None

    def row_local_date(self, row):
        for key in ("local_date",):
            value = row.get(key)
            if value:
                return str(value)[:10]
        for key in ("datetime", "valid_time", "valid_time_local", "local_time"):
            value = row.get(key)
            if not value or "T" not in str(value):
                continue
            text = str(value).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text).date().isoformat()
            except ValueError:
                continue
        return None

    def rows_for_target_date(self, rows):
        rows = list(rows or [])
        target_iso = self.target_date_iso()
        if not target_iso:
            return rows
        dated_rows = [row for row in rows if self.row_local_date(row) is not None]
        if not dated_rows:
            # Reconstructed replay rows often contain only HH:MM times; keep
            # them because there is no contradictory date evidence.
            return rows
        return [
            row for row in rows
            if self.row_local_date(row) == target_iso
        ]

    def target_date_filtered_wu_history(self, data):
        rows = self.rows_for_target_date(data.get("rows") or [])
        if rows == (data.get("rows") or []):
            return data
        temps = [
            self.row_temp_native(row)
            for row in rows
            if self.row_temp_native(row) is not None
        ]
        history_max = max(temps) if temps else None
        filtered = dict(data)
        filtered["rows"] = rows
        filtered["latest"] = rows[-1] if rows else None
        filtered["max_native"] = history_max
        filtered["max_c"] = history_max
        filtered["max_times"] = [
            row.get("time") for row in rows
            if self.row_temp_native(row) == history_max and row.get("time")
        ] if history_max is not None else []
        filtered["target_date_match"] = bool(rows)
        return filtered

    def target_date_filtered_eccc_swob(self, data):
        rows = self.rows_for_target_date(data.get("rows") or [])
        if rows == (data.get("rows") or []):
            return data
        filtered = dict(data)
        filtered["rows"] = rows
        filtered["latest"] = rows[-1] if rows else None
        filtered["same_day_max_native"] = self.max_value(*[
            self.row_air_temp_native(row)
            for row in rows
        ])
        filtered["same_day_max_c"] = self.max_value(*[
            self.row_air_temp_native(row)
            for row in rows
        ])
        filtered["target_date_match"] = bool(rows)
        return filtered

    def max_value(self, *values):
        cleaned = [value for value in values if value is not None]
        return max(cleaned) if cleaned else None

    def max_row_temp(self, rows):
        if not rows:
            return None
        temps = [
            self.row_temp_native(row)
            for row in rows
            if self.row_temp_native(row) is not None
        ]
        return max(temps) if temps else None

    def forecast_day_max(self, data):
        data = data or {}
        day_max = self.row_forecast_high_native(data)
        if day_max is not None:
            return day_max
        return self.max_row_temp(data.get("rows"))

    def round_half_up(self, value):
        if value is None:
            return None
        return int(math.floor(float(value) + 0.5))

    def to_number(self, value):
        if value in (None, "", "MSNG"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
