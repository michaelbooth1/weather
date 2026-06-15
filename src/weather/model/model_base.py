import math
from collections import Counter
from datetime import datetime


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
            self.to_number(row.get("temp_c"))
            for row in rows
            if self.to_number(row.get("temp_c")) is not None
        ]
        history_max = max(temps) if temps else None
        filtered = dict(data)
        filtered["rows"] = rows
        filtered["latest"] = rows[-1] if rows else None
        filtered["max_c"] = history_max
        filtered["max_times"] = [
            row.get("time") for row in rows
            if self.to_number(row.get("temp_c")) == history_max and row.get("time")
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
        filtered["same_day_max_c"] = self.max_value(*[
            self.to_number(row.get("air_temp_c"))
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
            self.to_number(row.get("temp_c"))
            for row in rows
            if self.to_number(row.get("temp_c")) is not None
        ]
        return max(temps) if temps else None

    def forecast_day_max(self, data):
        data = data or {}
        day_max = self.to_number(data.get("day_max_c"))
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
