import math
from collections import Counter


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
        return item.get("data", {}) if item.get("ok") else {}

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
