import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from wu_history import DEFAULT_DATA_ROOT, analyze_daily_summary
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


def _is_retryable(exc):
    """Transient network errors worth retrying. 4xx (e.g. a missing SWOB
    directory for a date) is not retryable; connection/timeout/5xx is."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        return response is not None and response.status_code >= 500
    return False


def request_with_retries(fn, attempts=3, base_delay=0.5, sleep=time.sleep):
    """Call ``fn`` (an idempotent GET), retrying transient failures with
    exponential backoff. Re-raises the last error if all attempts fail, and
    raises non-transient errors immediately. ``sleep`` is injectable for tests."""
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            if not _is_retryable(exc):
                raise
            last = exc
            if attempt < attempts - 1:
                sleep(base_delay * (2 ** attempt))
    raise last


class SourceFetchMixin:
    """Live and local source fetching plus the response parsers they rely on."""

    def fetch_sources(self):
        sources = {}
        sources.update(self.fetch_historical_sources())
        sources.update(self.fetch_live_sources())
        return sources

    def fetch_historical_sources(self):
        return self.fetch_source_group({
            "local_history": self.fetch_local_history,
        })

    def fetch_live_sources(self):
        all_fetchers = {
            "wu_history": self.fetch_wu_history,
            "wu_current": self.fetch_wu_current,
            "eccc_citypage": self.fetch_eccc_citypage,
            "eccc_swob": self.fetch_eccc_swob,
            "metar": self.fetch_metar,
            "weather_forecast": self.fetch_weather_com_forecast,
            "open_meteo": self.fetch_open_meteo,
            "nws_hourly": self.fetch_nws_hourly_forecast,
            "global_ensemble": self.fetch_global_ensemble,
        }
        # Only fetch the sources this market declares (e.g. NYC has no ECCC/SWOB).
        fetchers = {name: all_fetchers[name] for name in self.spec.sources if name in all_fetchers}

        # wu_history rows must stay exactly what WU printed: the effective
        # cutoff, features, analogs, late-day model, and the replay corpus all
        # read them as settlement-source evidence. Live wu_current readings
        # reach the model through the live-signal weights and observed floors
        # instead of being spliced into history (v0.5.1 briefly injected a
        # backdated mock row here; reverted in v0.5.2).
        return self.blend_with_last_good(self.fetch_source_group(fetchers))

    def fetch_source_group(self, fetchers):
        fetchers = {
            name: fetcher
            for name, fetcher in fetchers.items()
        }
        results = {}
        with ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
            futures = {
                executor.submit(fetcher): name
                for name, fetcher in fetchers.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                fetched_time = datetime.now(self.spec.tz).isoformat()
                try:
                    results[name] = {
                        "ok": True,
                        "data": future.result(),
                        "fetched_at": fetched_time
                    }
                except Exception as exc:
                    results[name] = {
                        "ok": False,
                        "error": str(exc),
                        "fetched_at": fetched_time
                    }
        return results

    def blend_with_last_good(self, fetched):
        cache_path = self.spec.data_root / "last_good_sources.json"
        
        # Load cache
        cache = {}
        if cache_path.exists():
            try:
                with cache_path.open("r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception as e:
                print(f"Error loading last good sources cache: {e}")

        blended = {}
        for name, item in fetched.items():
            if item.get("ok"):
                # Succeeded! Update cache
                cache[name] = {
                    "data": item["data"],
                    "fetched_at": item["fetched_at"],
                    "target_date": self.target_date.isoformat(),
                }
                blended[name] = {
                    "ok": True,
                    "stale": False,
                    "fetched_at": item["fetched_at"],
                    "data": item["data"]
                }
            else:
                # Failed! Try to load from cache
                cached_item = cache.get(name)
                cache_age_minutes = self.cache_age_minutes(cached_item.get("fetched_at")) if cached_item else None
                cache_is_recent = (
                    cache_age_minutes is not None
                    and cache_age_minutes <= LIVE_CACHE_MAX_AGE_MINUTES
                )
                if (
                    cached_item
                    and cached_item.get("target_date") == self.target_date.isoformat()
                    and cache_is_recent
                ):
                    blended[name] = {
                        "ok": True,
                        "stale": True,
                        "fetched_at": cached_item["fetched_at"],
                        "data": cached_item["data"],
                        "error": item.get("error", "Unknown error"),
                        "cache_age_minutes": cache_age_minutes,
                    }
                else:
                    stale_detail = ""
                    if cached_item and cached_item.get("target_date") == self.target_date.isoformat():
                        stale_detail = f" Last good cache is {cache_age_minutes:.0f} minutes old." if cache_age_minutes is not None else " Last good cache age is unknown."
                    blended[name] = {
                        "ok": False,
                        "stale": False,
                        "fetched_at": item.get("fetched_at"),
                        "error": f"{item.get('error', 'Unknown error')}.{stale_detail}".strip(),
                        "data": {}
                    }
                    
        # Save cache
        try:
            self.spec.data_root.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except Exception as e:
            print(f"Error saving last good sources cache: {e}")
            
        return blended

    def cache_age_minutes(self, fetched_at):
        if not fetched_at:
            return None
        try:
            parsed = datetime.fromisoformat(str(fetched_at))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.spec.tz)
        return max(0.0, (datetime.now(self.spec.tz) - parsed.astimezone(self.spec.tz)).total_seconds() / 60.0)

    def fetch_wu_history(self):
        url = (
            "https://api.weather.com/v1/location/"
            f"{self.spec.wu_history_id}/observations/historical.json"
        )
        payload = self.get_json(url, {
            "apiKey": WEATHER_COM_KEY,
            "units": self.spec.wu_units,
            "startDate": self.target_date_str,
            "endDate": self.target_date_str,
        })

        rows = []
        for obs in payload.get("observations", []) or []:
            local_dt = datetime.fromtimestamp(
                obs.get("valid_time_gmt", 0), timezone.utc
            ).astimezone(self.spec.tz)
            if local_dt.date() != self.target_date:
                continue
            rows.append({
                "time": local_dt.strftime("%H:%M"),
                "datetime": local_dt.isoformat(),
                "temp_c": self.to_number(obs.get("temp")),
                "dewpoint_c": self.to_number(obs.get("dewPt")),
                "humidity": self.to_number(obs.get("rh")),
                "pressure": self.to_number(obs.get("pressure")),
                "clouds": obs.get("clds"),
                "condition": obs.get("wx_phrase"),
                "wind": obs.get("wdir_cardinal"),
                "wind_kmh": self.to_number(obs.get("wspd")),
                "gust_kmh": self.to_number(obs.get("gust")),
            })

        temps = [
            row["temp_c"] for row in rows
            if row.get("temp_c") is not None
        ]
        history_max = max(temps) if temps else None
        max_times = [
            row["time"] for row in rows
            if row.get("temp_c") == history_max
        ] if history_max is not None else []

        return {
            "url": url,
            "rows": rows,
            "latest": rows[-1] if rows else None,
            "max_c": history_max,
            "max_times": max_times,
        }

    def fetch_wu_current(self):
        url = "https://api.weather.com/v3/wx/observations/current"
        data = self.get_json(url, {
            "apiKey": WEATHER_COM_KEY,
            "language": "en-US",
            "units": self.spec.wu_units,
            "format": "json",
            "icaoCode": self.spec.icao,
        })
        valid_time = self.parse_weather_com_time(data.get("validTimeLocal"))
        is_target_day = valid_time is not None and valid_time.date() == self.target_date
        return {
            "url": url,
            "time": data.get("validTimeLocal"),
            "target_date_match": is_target_day,
            "temp_c": self.to_number(data.get("temperature")) if is_target_day else None,
            "max_24h_c": self.to_number(data.get("temperatureMax24Hour")) if is_target_day else None,
            "max_since_7am_c": self.to_number(data.get("temperatureMaxSince7Am")) if is_target_day else None,
            "dewpoint_c": self.to_number(data.get("temperatureDewPoint")) if is_target_day else None,
            "humidity": self.to_number(data.get("relativeHumidity")) if is_target_day else None,
            "cloud_cover": self.to_number(data.get("cloudCover")) if is_target_day else None,
            "cloud_phrase": data.get("cloudCoverPhrase"),
            "condition": data.get("wxPhraseLong"),
            "wind": data.get("windDirectionCardinal"),
            "wind_kmh": self.to_number(data.get("windSpeed")) if is_target_day else None,
            "gust_kmh": self.to_number(data.get("windGust")) if is_target_day else None,
        }

    def fetch_local_history(self):
        summary_path = self.spec.data_root / "daily" / "daily_summary.csv"
        if not summary_path.exists():
            return {
                "available": False,
                "reason": "No local Wunderground daily summary found.",
            }
        target_year_window = {
            self.target_date + timedelta(days=offset)
            for offset in range(-HISTORY_WINDOW_DAYS, HISTORY_WINDOW_DAYS + 1)
        }
        analysis = analyze_daily_summary(
            summary_path,
            self.target_date.month,
            self.target_date.day,
            exclude_dates=target_year_window,
            min_row_count=HISTORY_MIN_ROW_COUNT,
        )
        probabilities = {
            int(bucket): float(probability)
            for bucket, probability in (analysis.get("bucket_probabilities", {}) or {}).items()
        }
        top_bucket = None
        if probabilities:
            top_bucket = max(probabilities, key=probabilities.get)
        return {
            "available": True,
            "summary_path": str(summary_path),
            "analysis": analysis,
            "top_bucket": int(top_bucket) if top_bucket is not None else None,
            "top_probability": probabilities.get(top_bucket) if top_bucket is not None else None,
            "prob_key": probabilities.get(self.spec.key_bucket),
            "prob_key_plus": sum(
                probability for bucket, probability in probabilities.items()
                if bucket >= self.spec.key_bucket
            ),
            "prob_key_plus_4": sum(
                probability for bucket, probability in probabilities.items()
                if bucket >= self.spec.key_bucket + 4
            ),
        }

    def fetch_eccc_swob(self):
        base_urls = [
            f"https://dd.weather.gc.ca/today/observations/swob-ml/{self.target_date_str}/CYYZ/",
            (
                f"https://dd.weather.gc.ca/{self.target_date_str}/WXO-DD/"
                f"observations/swob-ml/{self.target_date_str}/CYYZ/"
            ),
        ]
        index_html = None
        base_url = None
        last_error = None

        for url in base_urls:
            try:
                response = requests.get(url, timeout=self.timeout)
                response.raise_for_status()
                index_html = response.text
                base_url = url
                break
            except requests.RequestException as exc:
                last_error = exc

        if index_html is None:
            raise RuntimeError(f"Could not fetch SWOB directory: {last_error}")

        files = sorted(set(re.findall(r'href="([^"]*CYYZ-MAN-swob\.xml)"', index_html)))
        rows = []
        if files:
            # Fetch the per-observation XML files concurrently — there can be ~50
            # of them and sequential GETs dominated this source's latency. map()
            # preserves file order, so `latest = rows[-1]` stays correct.
            def _fetch_one(filename):
                def _once():
                    resp = requests.get(f"{base_url}{filename}", timeout=self.timeout)
                    resp.raise_for_status()
                    return resp.text
                return self.parse_swob_xml(request_with_retries(_once))

            with ThreadPoolExecutor(max_workers=min(8, len(files))) as executor:
                parsed = executor.map(_fetch_one, files)
                for row in parsed:
                    if row.get("local_date") == self.target_date.isoformat():
                        rows.append(row)

        latest = rows[-1] if rows else None
        same_day_max = self.max_value(*[
            row.get("air_temp_c")
            for row in rows
        ])
        return {
            "url": base_url,
            "latest": latest,
            "rows": rows,
            "same_day_max_c": same_day_max,
        }

    def fetch_eccc_citypage(self):
        url = "https://api.weather.gc.ca/collections/citypageweather-realtime/items/on-143"
        data = self.get_json(url, {"f": "json"})
        props = data.get("properties", {}) or {}
        current = props.get("currentConditions", {}) or {}
        forecasts = props.get("forecastGroup", {}).get("forecasts", []) or []
        today = forecasts[0] if forecasts else {}
        temp_summary = (
            today.get("temperatures", {})
            .get("textSummary", {})
            .get("en")
        )
        high_c = None
        if temp_summary:
            match = re.search(r"High\s+(-?\d+)", temp_summary)
            if match:
                high_c = float(match.group(1))

        return {
            "url": url,
            "last_updated": props.get("lastUpdated"),
            "current_time": current.get("timestamp", {}).get("en"),
            "current_temp_c": self.nested_number(
                current, "temperature", "value", "en"
            ),
            "condition": current.get("condition", {}).get("en"),
            "wind": current.get("wind", {})
            .get("direction", {})
            .get("value", {})
            .get("en"),
            "wind_kmh": self.nested_number(
                current, "wind", "speed", "value", "en"
            ),
            "gust_kmh": self.nested_number(
                current, "wind", "gust", "value", "en"
            ),
            "humidity": self.nested_number(
                current, "relativeHumidity", "value", "en"
            ),
            "forecast_high_c": high_c,
            "forecast_summary": temp_summary,
            "forecast_cloud": today.get("cloudPrecip", {}).get("en"),
            "forecast_wind": today.get("winds", {})
            .get("textSummary", {})
            .get("en"),
        }

    def fetch_metar(self):
        url = "https://aviationweather.gov/api/data/metar"
        payload = self.get_json(url, {
            "ids": self.spec.icao,
            "format": "json",
        })
        row = payload[0] if payload else {}
        report_time = self.parse_utc_time(row.get("reportTime"))
        is_target_day = report_time is not None and report_time.date() == self.target_date
        return {
            "url": url,
            "report_time": row.get("reportTime"),
            "target_date_match": is_target_day,
            # METAR temps are always Celsius from the API; convert to the
            # market's native unit so all features share one unit.
            "temp_c": self.spec.c_to_native(self.to_number(row.get("temp"))) if is_target_day else None,
            "dewpoint_c": self.spec.c_to_native(self.to_number(row.get("dewp"))) if is_target_day else None,
            "wind_dir": row.get("wdir"),
            "wind_speed": self.to_number(row.get("wspd")) if is_target_day else None,
            "wind_gust": self.to_number(row.get("wgst")) if is_target_day else None,
            "cover": row.get("cover"),
            "raw": row.get("rawOb"),
        }

    def fetch_weather_com_forecast(self):
        url = "https://api.weather.com/v3/wx/forecast/hourly/15day"
        payload = self.get_json(url, {
            "apiKey": WEATHER_COM_KEY,
            "geocode": f"{self.spec.lat},{self.spec.lon}",
            "units": self.spec.wu_units,
            "language": "en-US",
            "format": "json",
        })
        rows = []
        now = datetime.now(self.spec.tz)
        for index, raw_time in enumerate(payload.get("validTimeLocal", []) or []):
            dt = self.parse_weather_com_time(raw_time)
            if not dt or dt.date() != self.target_date or dt < now:
                continue
            rows.append({
                "time": dt.strftime("%H:%M"),
                "valid_time": dt.isoformat(),
                "temp_c": self.array_get(payload, "temperature", index),
                "cloud_cover": self.array_get(payload, "cloudCover", index),
                "condition": self.array_get(payload, "wxPhraseLong", index),
                "wind": self.array_get(payload, "windDirectionCardinal", index),
                "wind_kmh": self.array_get(payload, "windSpeed", index),
            })
        return {"url": url, "rows": rows[:12]}

    def fetch_open_meteo(self):
        url = "https://api.open-meteo.com/v1/forecast"
        payload = self.get_json(url, {
            "latitude": self.spec.lat,
            "longitude": self.spec.lon,
            "hourly": (
                "temperature_2m,cloud_cover,cloud_cover_low,cloud_cover_mid,"
                "cloud_cover_high,wind_speed_10m,shortwave_radiation"
            ),
            "temperature_unit": self.spec.om_temperature_unit,
            "wind_speed_unit": "kmh",
            "timezone": self.spec.timezone,
            "forecast_days": 2,
        })
        hourly = payload.get("hourly", {}) or {}
        rows = []
        day_temps = []  # all of today's forecast hours, for the daily-max feature
        now = datetime.now(self.spec.tz).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date:
                continue
            temp = self.to_number(self.array_get(hourly, "temperature_2m", index))
            if temp is not None:
                day_temps.append(temp)
            if dt < now:
                continue
            local_dt = dt.replace(tzinfo=self.spec.tz)
            rows.append({
                "time": dt.strftime("%H:%M"),
                "valid_time": local_dt.isoformat(),
                "temp_c": self.array_get(hourly, "temperature_2m", index),
                "cloud_cover": self.array_get(hourly, "cloud_cover", index),
                "low_cloud": self.array_get(hourly, "cloud_cover_low", index),
                "mid_cloud": self.array_get(hourly, "cloud_cover_mid", index),
                "high_cloud": self.array_get(hourly, "cloud_cover_high", index),
                "wind_kmh": self.array_get(hourly, "wind_speed_10m", index),
                "solar": self.array_get(hourly, "shortwave_radiation", index),
            })
        # Forecasted daily max over ALL of today's hours (the canonical forecast
        # feature, matching the Open-Meteo historical-forecast training value).
        day_max_c = max(day_temps) if day_temps else None
        return {"url": url, "rows": rows[:12], "day_max_c": day_max_c}

    def fetch_nws_hourly_forecast(self):
        """US National Weather Service hourly grid forecast.

        The /points lookup maps lat/lon to the NWS grid; the forecastHourly URL
        then returns hourly periods. US markets trade in Fahrenheit, but this
        converter still honors the market display unit for safety.
        """
        if ":US" not in str(self.spec.wu_history_id):
            return {"available": False, "reason": "NWS hourly forecast is US-only.", "rows": [], "day_max_c": None}
        points_url = f"https://api.weather.gov/points/{self.spec.lat:.4f},{self.spec.lon:.4f}"
        headers = {
            "User-Agent": "weather-market-research/1.0 (local)",
            "Accept": "application/geo+json, application/json",
        }
        points = self.cached_nws_points(points_url, headers)
        forecast_url = ((points.get("properties") or {}).get("forecastHourly"))
        if not forecast_url:
            raise RuntimeError("NWS points response did not include forecastHourly")
        payload = self.get_json(forecast_url, {}, headers=headers)
        rows = []
        day_temps = []
        now = datetime.now(self.spec.tz)
        for period in ((payload.get("properties") or {}).get("periods") or []):
            dt = self.parse_weather_com_time(period.get("startTime"))
            if not dt or dt.date() != self.target_date:
                continue
            temp = self.forecast_temp_to_native(period.get("temperature"), period.get("temperatureUnit"))
            if temp is not None:
                day_temps.append(temp)
            if dt < now:
                continue
            rows.append({
                "time": dt.strftime("%H:%M"),
                "valid_time": dt.isoformat(),
                "temp_c": temp,
                "condition": period.get("shortForecast"),
                "wind": period.get("windDirection"),
                "wind_kmh": self.wind_speed_text_to_kmh(period.get("windSpeed")),
            })
        return {"url": forecast_url, "rows": rows[:12], "day_max_c": max(day_temps) if day_temps else None}

    def cached_nws_points(self, points_url, headers):
        cache_path = self.spec.data_root / "nws_points.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("points_url") == points_url and cached.get("payload"):
                    return cached["payload"]
            except (OSError, json.JSONDecodeError):
                pass
        payload = self.get_json(points_url, {}, headers=headers)
        try:
            self.spec.data_root.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"points_url": points_url, "payload": payload}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            pass
        return payload

    def fetch_global_ensemble(self):
        """Open-Meteo GFS ensemble mean/member forecast.

        ``temperature_2m`` is the ensemble mean in the response; member columns
        are used to expose an hourly spread for diagnostics while day_max_c
        stays comparable to the other daily-max forecast sources.
        """
        url = "https://ensemble-api.open-meteo.com/v1/ensemble"
        payload = self.get_json(url, {
            "latitude": self.spec.lat,
            "longitude": self.spec.lon,
            "hourly": "temperature_2m",
            "temperature_unit": self.spec.om_temperature_unit,
            "timezone": self.spec.timezone,
            "forecast_days": 2,
            "models": "gfs_seamless",
        })
        hourly = payload.get("hourly", {}) or {}
        member_keys = [
            key for key in hourly
            if key.startswith("temperature_2m_member")
        ]
        rows = []
        day_temps = []
        day_spreads = []
        now = datetime.now(self.spec.tz).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date:
                continue
            temp = self.to_number(self.array_get(hourly, "temperature_2m", index))
            members = [
                self.to_number(self.array_get(hourly, key, index))
                for key in member_keys
            ]
            members = [value for value in members if value is not None]
            spread = max(members) - min(members) if len(members) >= 2 else None
            if temp is not None:
                day_temps.append(temp)
            if spread is not None:
                day_spreads.append(spread)
            if dt < now:
                continue
            local_dt = dt.replace(tzinfo=self.spec.tz)
            rows.append({
                "time": dt.strftime("%H:%M"),
                "valid_time": local_dt.isoformat(),
                "temp_c": temp,
                "ensemble_member_spread": spread,
                "condition": "GFS ensemble mean",
            })
        return {
            "url": url,
            "rows": rows[:12],
            "day_max_c": max(day_temps) if day_temps else None,
            "day_mean_member_spread": sum(day_spreads) / len(day_spreads) if day_spreads else None,
        }

    def forecast_temp_to_native(self, value, unit):
        temp = self.to_number(value)
        if temp is None:
            return None
        unit = str(unit or self.spec.display_unit).upper()
        if unit == self.spec.display_unit:
            return temp
        if unit == "F" and self.spec.display_unit == "C":
            return (temp - 32.0) * 5.0 / 9.0
        if unit == "C" and self.spec.display_unit == "F":
            return temp * 9.0 / 5.0 + 32.0
        return temp

    def wind_speed_text_to_kmh(self, value):
        if not value:
            return None
        numbers = [self.to_number(part) for part in re.findall(r"\d+(?:\.\d+)?", str(value))]
        numbers = [number for number in numbers if number is not None]
        if not numbers:
            return None
        mph = max(numbers)
        return round(mph * 1.609344, 2)

    def parse_swob_xml(self, xml_text):
        root = ET.fromstring(xml_text)

        def element_value(name):
            for element in root.iter():
                if element.attrib.get("name") == name:
                    return element.attrib.get("value")
            return None

        utc_time = element_value("date_tm")
        local_dt = self.parse_utc_time(utc_time)
        return {
            "time": utc_time,
            "local_time": local_dt.isoformat() if local_dt else None,
            "local_date": local_dt.date().isoformat() if local_dt else None,
            "air_temp_c": self.to_number(element_value("air_temp")),
            "dewpoint_c": self.to_number(element_value("dwpt_temp")),
            "humidity": self.to_number(element_value("rel_hum")),
            "max_1h_c": self.to_number(element_value("max_air_temp_pst1hr")),
            "max_6h_c": self.to_number(element_value("max_air_temp_pst6hrs")),
            "max_24h_c": self.to_number(element_value("max_air_temp_pst24hrs")),
        }

    def get_json(self, url, params, headers=None):
        def _once():
            response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        return request_with_retries(_once)

    def parse_weather_com_time(self, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(self.spec.tz)
        except ValueError:
            pass
        # Fallback for other ISO-8601 offsets (colon in offset, missing seconds,
        # or a trailing Z) that strptime's fixed format would reject.
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(self.spec.tz)
        except ValueError:
            return None

    def parse_utc_time(self, value):
        if not value:
            return None
        try:
            value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(value).astimezone(self.spec.tz)
        except ValueError:
            return None

    def array_get(self, mapping, key, index):
        values = mapping.get(key) or []
        if index >= len(values):
            return None
        return values[index]

    def nested_number(self, mapping, *path):
        value = mapping
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return self.to_number(value)
