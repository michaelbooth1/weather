import hashlib
import json
import re
import statistics
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from weather.sources.wu_history import DEFAULT_DATA_ROOT, analyze_daily_summary
from weather.sources.eccc_gridded import fetch_open_meteo_gem_for_market
from weather.sources.marine_context import active_marine_context_state, fetch_marine_context_for_market
from weather.sources.mrms_precip import fetch_mrms_precip_for_market
from weather.model.source_adapters import fetch_source_group as run_source_adapter_group
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
    SOURCE_CACHE_TTL_MINUTES,
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


def percentile(values, q):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * float(q)
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


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
            "eccc_gem": self.fetch_eccc_gem,
            "metar": self.fetch_metar,
            "weather_forecast": self.fetch_weather_com_forecast,
            "open_meteo": self.fetch_open_meteo,
            "nws_hourly": self.fetch_nws_hourly_forecast,
            "nws_grid": self.fetch_nws_grid_forecast,
            "open_meteo_multimodel": self.fetch_open_meteo_multimodel,
            "global_ensemble": self.fetch_global_ensemble,
            "marine_context": self.fetch_marine_context,
            "mrms_precip": self.fetch_mrms_precip,
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
        return run_source_adapter_group(fetchers, timezone=self.spec.tz)

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
                    "status": "fresh",
                    "fetched_at": item["fetched_at"],
                    "latency_ms": item.get("latency_ms"),
                    "data": item["data"]
                }
            else:
                # Failed! Try to load from cache, governed by this source's TTL:
                # a stale "current" observation expires fast; a stale forecast
                # can be trusted longer.
                ttl_minutes = self.source_cache_ttl_minutes(name)
                cached_item = cache.get(name)
                cache_age_minutes = self.cache_age_minutes(cached_item.get("fetched_at")) if cached_item else None
                cache_is_recent = (
                    cache_age_minutes is not None
                    and cache_age_minutes <= ttl_minutes
                )
                if (
                    cached_item
                    and cached_item.get("target_date") == self.target_date.isoformat()
                    and cache_is_recent
                ):
                    blended[name] = {
                        "ok": True,
                        "stale": True,
                        "status": "stale_cache",
                        "fetched_at": cached_item["fetched_at"],
                        "data": cached_item["data"],
                        "error": item.get("error", "Unknown error"),
                        "latency_ms": item.get("latency_ms"),
                        "cache_age_minutes": cache_age_minutes,
                        "ttl_minutes": ttl_minutes,
                    }
                else:
                    stale_detail = ""
                    if cached_item and cached_item.get("target_date") == self.target_date.isoformat():
                        stale_detail = (
                            f" Last good cache is {cache_age_minutes:.0f} minutes old (TTL {ttl_minutes} min)."
                            if cache_age_minutes is not None else " Last good cache age is unknown."
                        )
                    blended[name] = {
                        "ok": False,
                        "stale": False,
                        "status": "failed",
                        "fetched_at": item.get("fetched_at"),
                        "error": f"{item.get('error', 'Unknown error')}.{stale_detail}".strip(),
                        "latency_ms": item.get("latency_ms"),
                        "ttl_minutes": ttl_minutes,
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

    def source_cache_ttl_minutes(self, name):
        """Per-source last-good cache TTL in minutes (item 17). Observation /
        settlement sources expire fast because a stale 'current' reading is
        misleading; slow-moving forecasts keep a longer window. Sources not in
        the map fall back to the global cap."""
        return SOURCE_CACHE_TTL_MINUTES.get(name, LIVE_CACHE_MAX_AGE_MINUTES)

    def source_diagnostics(self, blended):
        """Structured per-source status for partial live-source failures (item
        17): a queryable list of {source, status, fetched_at, age_minutes,
        ttl_minutes, error} so one failing or stale feed is visible rather than
        silently blended away. ``status`` is fresh / stale_cache / failed."""
        diagnostics = []
        for name in sorted(blended):
            item = blended.get(name) or {}
            status = item.get("status")
            if status is None:
                if item.get("ok") and not item.get("stale"):
                    status = "fresh"
                elif item.get("stale"):
                    status = "stale_cache"
                else:
                    status = "failed"
            age = item.get("cache_age_minutes")
            if age is None:
                age = self.cache_age_minutes(item.get("fetched_at"))
            diagnostic = {
                "source": name,
                "status": status,
                "fetched_at": item.get("fetched_at"),
                "age_minutes": round(age, 1) if age is not None else None,
                "ttl_minutes": self.source_cache_ttl_minutes(name),
                "latency_ms": item.get("latency_ms"),
                "error": item.get("error"),
            }
            if name == "marine_context":
                marine_state = active_marine_context_state(item.get("data") or {})
                if marine_state:
                    diagnostic["marine_context"] = marine_state
            diagnostics.append(diagnostic)
        return diagnostics

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
            temp_native = self.to_number(obs.get("temp"))
            dewpoint_native = self.to_number(obs.get("dewPt"))
            rows.append({
                "time": local_dt.strftime("%H:%M"),
                "datetime": local_dt.isoformat(),
                "temp_native": temp_native,
                "temp_c": temp_native,
                "dewpoint_native": dewpoint_native,
                "dewpoint_c": dewpoint_native,
                "humidity": self.to_number(obs.get("rh")),
                "pressure": self.to_number(obs.get("pressure")),
                "clouds": obs.get("clds"),
                "condition": obs.get("wx_phrase"),
                "wind": obs.get("wdir_cardinal"),
                "wind_kmh": self.to_number(obs.get("wspd")),
                "gust_kmh": self.to_number(obs.get("gust")),
            })

        temps = [row["temp_native"] for row in rows if row.get("temp_native") is not None]
        history_max = max(temps) if temps else None
        max_times = [
            row["time"] for row in rows
            if row.get("temp_native") == history_max
        ] if history_max is not None else []

        return {
            "url": url,
            "rows": rows,
            "latest": rows[-1] if rows else None,
            "max_native": history_max,
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
        temp_native = self.to_number(data.get("temperature")) if is_target_day else None
        max_24h_native = self.to_number(data.get("temperatureMax24Hour")) if is_target_day else None
        max_since_7am_native = self.to_number(data.get("temperatureMaxSince7Am")) if is_target_day else None
        dewpoint_native = self.to_number(data.get("temperatureDewPoint")) if is_target_day else None
        return {
            "url": url,
            "time": data.get("validTimeLocal"),
            "target_date_match": is_target_day,
            "temp_native": temp_native,
            "temp_c": temp_native,
            "max_24h_native": max_24h_native,
            "max_24h_c": max_24h_native,
            "max_since_7am_native": max_since_7am_native,
            "max_since_7am_c": max_since_7am_native,
            "dewpoint_native": dewpoint_native,
            "dewpoint_c": dewpoint_native,
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
            self.row_air_temp_native(row)
            for row in rows
        ])
        return {
            "url": base_url,
            "latest": latest,
            "rows": rows,
            "same_day_max_native": same_day_max,
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
            "provider_update_time": props.get("lastUpdated"),
            "raw_payload": data,
            "current_time": current.get("timestamp", {}).get("en"),
            "current_temp_native": self.nested_number(
                current, "temperature", "value", "en"
            ),
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
            "forecast_high_native": high_c,
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
        temp_native = self.spec.c_to_native(self.to_number(row.get("temp"))) if is_target_day else None
        dewpoint_native = self.spec.c_to_native(self.to_number(row.get("dewp"))) if is_target_day else None
        return {
            "url": url,
            "report_time": row.get("reportTime"),
            "target_date_match": is_target_day,
            # METAR temps are always Celsius from the API; convert to the
            # market's native unit so all features share one unit.
            "temp_native": temp_native,
            "temp_c": temp_native,
            "dewpoint_native": dewpoint_native,
            "dewpoint_c": dewpoint_native,
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
            temp_native = self.array_get(payload, "temperature", index)
            rows.append({
                "time": dt.strftime("%H:%M"),
                "valid_time": dt.isoformat(),
                "temp_native": temp_native,
                "temp_c": temp_native,
                "cloud_cover": self.array_get(payload, "cloudCover", index),
                "condition": self.array_get(payload, "wxPhraseLong", index),
                "wind": self.array_get(payload, "windDirectionCardinal", index),
                "wind_kmh": self.array_get(payload, "windSpeed", index),
            })
        metadata = payload.get("metadata", {}) or {}
        return {
            "url": url,
            "rows": rows[:12],
            "provider_issue_time": metadata.get("created_time") or metadata.get("createdTime"),
            "provider_update_time": metadata.get("updated") or metadata.get("update_time"),
            "raw_payload": payload,
        }

    def fetch_open_meteo(self):
        url = "https://api.open-meteo.com/v1/forecast"
        payload = self.get_json(url, {
            "latitude": self.spec.lat,
            "longitude": self.spec.lon,
            "hourly": (
                "temperature_2m,cloud_cover,cloud_cover_low,cloud_cover_mid,"
                "cloud_cover_high,wind_speed_10m,shortwave_radiation,cape,"
                "temperature_925hPa,temperature_850hPa,geopotential_height_500hPa,"
                "direct_radiation,diffuse_radiation,wind_gusts_10m,visibility,"
                "precipitation_probability,precipitation,soil_temperature_0cm,"
                "soil_moisture_0_to_1cm,vapour_pressure_deficit,"
                "et0_fao_evapotranspiration"
            ),
            "temperature_unit": self.spec.om_temperature_unit,
            "wind_speed_unit": "kmh",
            "timezone": self.spec.timezone,
            "forecast_days": 2,
        })
        hourly = payload.get("hourly", {}) or {}
        rows = []
        day_rows = []
        day_temps = []  # all of today's forecast hours, for the daily-max feature
        now = datetime.now(self.spec.tz).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date:
                continue
            temp = self.to_number(self.array_get(hourly, "temperature_2m", index))
            if temp is not None:
                day_temps.append(temp)
            local_dt = dt.replace(tzinfo=self.spec.tz)
            row = {
                "time": dt.strftime("%H:%M"),
                "valid_time": local_dt.isoformat(),
                "temp_native": temp,
                "temp_c": temp,
                "cloud_cover": self.to_number(self.array_get(hourly, "cloud_cover", index)),
                "low_cloud": self.to_number(self.array_get(hourly, "cloud_cover_low", index)),
                "mid_cloud": self.to_number(self.array_get(hourly, "cloud_cover_mid", index)),
                "high_cloud": self.to_number(self.array_get(hourly, "cloud_cover_high", index)),
                "wind_kmh": self.to_number(self.array_get(hourly, "wind_speed_10m", index)),
                "solar": self.to_number(self.array_get(hourly, "shortwave_radiation", index)),
                "cape": self.to_number(self.array_get(hourly, "cape", index)),
                "temperature_925hpa": self.to_number(self.array_get(hourly, "temperature_925hPa", index)),
                "temperature_850hpa": self.to_number(self.array_get(hourly, "temperature_850hPa", index)),
                "geopotential_height_500hpa": self.to_number(
                    self.array_get(hourly, "geopotential_height_500hPa", index)
                ),
                "direct_radiation": self.to_number(self.array_get(hourly, "direct_radiation", index)),
                "diffuse_radiation": self.to_number(self.array_get(hourly, "diffuse_radiation", index)),
                "wind_gust_kmh": self.to_number(self.array_get(hourly, "wind_gusts_10m", index)),
                "visibility": self.to_number(self.array_get(hourly, "visibility", index)),
                "precipitation_probability": self.to_number(
                    self.array_get(hourly, "precipitation_probability", index)
                ),
                "precipitation": self.to_number(self.array_get(hourly, "precipitation", index)),
                "soil_temperature_0cm": self.to_number(self.array_get(hourly, "soil_temperature_0cm", index)),
                "soil_moisture_0_to_1cm": self.to_number(
                    self.array_get(hourly, "soil_moisture_0_to_1cm", index)
                ),
                "vapour_pressure_deficit": self.to_number(
                    self.array_get(hourly, "vapour_pressure_deficit", index)
                ),
                "et0_fao_evapotranspiration": self.to_number(
                    self.array_get(hourly, "et0_fao_evapotranspiration", index)
                ),
            }
            day_rows.append(row)
            if dt < now:
                continue
            rows.append(row)
        # Forecasted daily max over ALL of today's hours (the canonical forecast
        # feature, matching the Open-Meteo historical-forecast training value).
        day_max_native = max(day_temps) if day_temps else None
        return {
            "url": url,
            "rows": rows[:12],
            "day_rows": day_rows,
            "day_max_native": day_max_native,
            "day_max_c": day_max_native,
            "raw_payload": payload,
        }

    def fetch_nws_hourly_forecast(self):
        """US National Weather Service hourly grid forecast.

        The /points lookup maps lat/lon to the NWS grid; the forecastHourly URL
        then returns hourly periods. US markets trade in Fahrenheit, but this
        converter still honors the market display unit for safety.
        """
        if ":US" not in str(self.spec.wu_history_id):
            return {"available": False, "reason": "NWS hourly forecast is US-only.", "rows": [], "day_max_native": None, "day_max_c": None}
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
        props = payload.get("properties") or {}
        rows = []
        day_temps = []
        now = datetime.now(self.spec.tz)
        for period in (props.get("periods") or []):
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
                "temp_native": temp,
                "temp_c": temp,
                "condition": period.get("shortForecast"),
                "wind": period.get("windDirection"),
                "wind_kmh": self.wind_speed_text_to_kmh(period.get("windSpeed")),
            })
        return {
            "url": forecast_url,
            "rows": rows[:12],
            "day_max_native": max(day_temps) if day_temps else None,
            "day_max_c": max(day_temps) if day_temps else None,
            "provider_issue_time": props.get("generatedAt"),
            "provider_update_time": props.get("updated"),
            "raw_payload": payload,
        }

    def fetch_nws_grid_forecast(self):
        """US National Weather Service raw forecastGridData values."""
        if ":US" not in str(self.spec.wu_history_id):
            return {"available": False, "reason": "NWS grid forecast is US-only.", "rows": [], "day_rows": [], "day_max_native": None, "day_max_c": None}
        points_url = f"https://api.weather.gov/points/{self.spec.lat:.4f},{self.spec.lon:.4f}"
        headers = {
            "User-Agent": "weather-market-research/1.0 (local)",
            "Accept": "application/geo+json, application/json",
        }
        metadata = self.cached_nws_grid_metadata(points_url, headers)
        grid_url = metadata.get("forecastGridData")
        if not grid_url:
            raise RuntimeError("NWS points response did not include forecastGridData")
        fetched_at = datetime.now(timezone.utc).isoformat()
        payload = self.get_json(grid_url, {}, headers=headers)
        props = payload.get("properties") or {}
        rows_by_time = {}

        def row_for(dt):
            key = dt.isoformat()
            row = rows_by_time.setdefault(key, {
                "time": dt.strftime("%H:%M"),
                "valid_time": key,
            })
            return row

        field_map = {
            "temperature": ("temp_native", True),
            "maxTemperature": ("max_temp_native", True),
            "dewpoint": ("dewpoint_native", True),
            "relativeHumidity": ("humidity", False),
            "skyCover": ("sky_cover", False),
            "windDirection": ("wind_direction", False),
            "windSpeed": ("wind_kmh", False),
            "probabilityOfPrecipitation": ("precipitation_probability", False),
            "quantitativePrecipitation": ("quantitative_precipitation", False),
        }
        for source_key, (target_key, is_temp) in field_map.items():
            series = props.get(source_key) or {}
            uom = series.get("uom")
            for item in series.get("values") or []:
                dt = self.parse_nws_grid_valid_time(item.get("validTime"))
                if not dt or dt.date() != self.target_date:
                    continue
                value = self.nws_grid_value(item.get("value"), uom, is_temp=is_temp)
                row = row_for(dt)
                row[target_key] = value
                if target_key == "temp_native":
                    row["temp_c"] = value
                elif target_key == "dewpoint_native":
                    row["dewpoint_c"] = value

        for source_key in ("weather", "hazards"):
            series = props.get(source_key) or {}
            for item in series.get("values") or []:
                dt = self.parse_nws_grid_valid_time(item.get("validTime"))
                if not dt or dt.date() != self.target_date:
                    continue
                value = item.get("value")
                row = row_for(dt)
                row[source_key] = value
                row[f"{source_key}_count"] = self.nws_grid_value_count(value)

        day_rows = sorted(rows_by_time.values(), key=lambda row: row.get("valid_time") or "")
        now = datetime.now(self.spec.tz)
        rows = [
            row for row in day_rows
            if self.parse_weather_com_time(row.get("valid_time")) is not None
            and self.parse_weather_com_time(row.get("valid_time")) >= now
        ]
        max_values = [
            row.get("max_temp_native") for row in day_rows
            if row.get("max_temp_native") is not None
        ]
        if not max_values:
            max_values = [
                row.get("temp_native") for row in day_rows
                if row.get("temp_native") is not None
            ]
        day_max_native = max(max_values) if max_values else None
        provider_update_time = props.get("updateTime") or props.get("updated")
        return {
            "available": True,
            "url": grid_url,
            "rows": rows[:12],
            "day_rows": day_rows,
            "day_max_native": day_max_native,
            "day_max_c": day_max_native,
            "provider_issue_time": props.get("generatedAt"),
            "provider_update_time": provider_update_time,
            "fetched_at": fetched_at,
            "run_age_hours": self.hours_between(fetched_at, provider_update_time),
            "row_count": len(day_rows),
            "payload_hash": self.payload_hash(payload),
            "grid_metadata": metadata,
            "historical_archive_available": False,
            "live_only_fields": [
                "nws_grid_high",
                "nws_grid_vs_forecast_high",
                "nws_grid_pop_after_cutoff_max",
                "nws_grid_qpf_after_cutoff_sum",
                "nws_grid_sky_cover_after_cutoff_mean",
                "nws_grid_hazard_count",
                "nws_grid_run_age_hours",
            ],
            "raw_payload": payload,
        }

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

    def cached_nws_grid_metadata(self, points_url, headers):
        cache_path = self.spec.data_root / "nws_grid_metadata.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("points_url") == points_url and cached.get("forecastGridData"):
                    return cached
            except (OSError, json.JSONDecodeError):
                pass
        points = self.cached_nws_points(points_url, headers)
        props = points.get("properties") or {}
        metadata = {
            "points_url": points_url,
            "forecastGridData": props.get("forecastGridData"),
            "forecastHourly": props.get("forecastHourly"),
            "gridId": props.get("gridId"),
            "gridX": props.get("gridX"),
            "gridY": props.get("gridY"),
            "cwa": props.get("cwa"),
            "timeZone": props.get("timeZone"),
        }
        try:
            self.spec.data_root.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
        return metadata

    def fetch_open_meteo_multimodel(self):
        """US-only Open-Meteo /v1/gfs model-specific guidance columns."""
        if ":US" not in str(self.spec.wu_history_id):
            return {"available": False, "reason": "Open-Meteo multi-model guidance is US-only.", "rows": [], "day_rows": [], "day_model_highs": {}}
        url = "https://api.open-meteo.com/v1/gfs"
        models = ("gfs_seamless", "ncep_hrrr_conus", "ncep_nbm_conus", "ncep_nam_conus")
        field_map = {
            "temperature_2m": "temp_native",
            "cloud_cover": "cloud_cover",
            "shortwave_radiation": "solar",
            "direct_radiation": "direct_radiation",
            "diffuse_radiation": "diffuse_radiation",
            "wind_speed_10m": "wind_kmh",
            "wind_gusts_10m": "wind_gust_kmh",
            "precipitation_probability": "precipitation_probability",
            "precipitation": "precipitation",
            "cape": "cape",
            "visibility": "visibility",
            "soil_temperature_0cm": "soil_temperature_0cm",
            "soil_moisture_0_to_1cm": "soil_moisture_0_to_1cm",
            "vapour_pressure_deficit": "vapour_pressure_deficit",
            "et0_fao_evapotranspiration": "et0_fao_evapotranspiration",
            "temperature_925hPa": "temperature_925hpa",
            "temperature_850hPa": "temperature_850hpa",
            "geopotential_height_500hPa": "geopotential_height_500hpa",
        }
        fetched_at = datetime.now(timezone.utc).isoformat()
        payload = self.get_json(url, {
            "latitude": self.spec.lat,
            "longitude": self.spec.lon,
            "hourly": ",".join(field_map),
            "temperature_unit": self.spec.om_temperature_unit,
            "wind_speed_unit": "kmh",
            "timezone": self.spec.timezone,
            "forecast_days": 2,
            "models": ",".join(models),
        })
        hourly = payload.get("hourly", {}) or {}
        rows = []
        day_rows = []
        model_day_temps = {model: [] for model in models}
        now = datetime.now(self.spec.tz).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date:
                continue
            model_payloads = {}
            model_temps = []
            for model in models:
                values = {}
                for source_key, target_key in field_map.items():
                    value = self.to_number(self.array_get(hourly, f"{source_key}_{model}", index))
                    values[target_key] = value
                temp = values.get("temp_native")
                if temp is not None:
                    values["temp_c"] = temp
                    model_temps.append(temp)
                    model_day_temps[model].append(temp)
                model_payloads[model] = values
            row = {
                "time": dt.strftime("%H:%M"),
                "valid_time": dt.replace(tzinfo=self.spec.tz).isoformat(),
                "models": model_payloads,
                "model_temp_spread": max(model_temps) - min(model_temps) if len(model_temps) >= 2 else None,
            }
            day_rows.append(row)
            if dt < now:
                continue
            rows.append(row)
        day_model_highs = {
            model: max(values) if values else None
            for model, values in model_day_temps.items()
        }
        high_values = [value for value in day_model_highs.values() if value is not None]
        day_max_native = statistics.median(high_values) if high_values else None
        return {
            "available": True,
            "url": url,
            "rows": rows[:12],
            "day_rows": day_rows,
            "day_model_highs": day_model_highs,
            "day_max_native": day_max_native,
            "day_max_c": day_max_native,
            "day_high_spread": max(high_values) - min(high_values) if len(high_values) >= 2 else None,
            "row_count": len(day_rows),
            "payload_hash": self.payload_hash(payload),
            "fetched_at": fetched_at,
            "model_run_age_hours": None,
            "model_run_age_status": "not_exposed_by_open_meteo_gfs",
            "run_to_run_high_change": None,
            "run_to_run_change_status": "requires_previous_run_archive",
            "historical_archive_available": False,
            "live_only_fields": [
                "open_meteo_multimodel_high_spread",
                "open_meteo_gfs_high_delta",
                "open_meteo_hrrr_high_delta",
                "open_meteo_nbm_high_delta",
                "open_meteo_nam_high_delta",
                "open_meteo_nbm_hrrr_disagreement",
                "open_meteo_multimodel_next_3h_spread",
                "open_meteo_multimodel_run_age_hours",
                "open_meteo_multimodel_run_to_run_high_change",
                "open_meteo_nbm_hrrr_disagreement_after_cutoff",
            ],
            "generation_time_ms": payload.get("generationtime_ms"),
            "raw_payload": payload,
        }

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
        day_rows = []
        day_temps = []
        day_spreads = []
        member_day_temps = {key: [] for key in member_keys}
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
            for key in member_keys:
                member_temp = self.to_number(self.array_get(hourly, key, index))
                if member_temp is not None:
                    member_day_temps[key].append(member_temp)
            if temp is not None:
                day_temps.append(temp)
            if spread is not None:
                day_spreads.append(spread)
            local_dt = dt.replace(tzinfo=self.spec.tz)
            row = {
                "time": dt.strftime("%H:%M"),
                "valid_time": local_dt.isoformat(),
                "temp_native": temp,
                "temp_c": temp,
                "ensemble_member_spread": spread,
                "ensemble_member_p10": percentile(members, 0.10),
                "ensemble_member_p90": percentile(members, 0.90),
                "condition": "GFS ensemble mean",
            }
            day_rows.append(row)
            if dt < now:
                continue
            rows.append(row)
        member_highs = [
            max(values) for values in member_day_temps.values()
            if values
        ]
        member_high_p10 = percentile(member_highs, 0.10)
        member_high_p90 = percentile(member_highs, 0.90)
        return {
            "url": url,
            "rows": rows[:12],
            "day_rows": day_rows,
            "day_max_native": max(day_temps) if day_temps else None,
            "day_max_c": max(day_temps) if day_temps else None,
            "day_mean_member_spread": sum(day_spreads) / len(day_spreads) if day_spreads else None,
            "day_member_high_p10": member_high_p10,
            "day_member_high_p90": member_high_p90,
            "day_member_high_spread_80": (
                member_high_p90 - member_high_p10
                if member_high_p10 is not None and member_high_p90 is not None
                else None
            ),
            "raw_payload": payload,
        }

    def fetch_marine_context(self):
        """CO-OPS/NDBC marine and lake-breeze station context."""
        def get_text(url):
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text

        return fetch_marine_context_for_market(
            self.spec,
            self.target_date,
            get_json=self.get_json,
            get_text=get_text,
            now=datetime.now(timezone.utc),
            timeout=self.timeout,
        )

    def fetch_mrms_precip(self):
        """MRMS CONUS realized precipitation metadata and lag state."""
        def get_text(url):
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text

        return fetch_mrms_precip_for_market(
            self.spec,
            self.target_date,
            get_text=get_text,
            now=datetime.now(timezone.utc),
        )

    def fetch_eccc_gem(self):
        """Open-Meteo GEM/HRDPS-style Canadian gridded guidance for Toronto."""
        return fetch_open_meteo_gem_for_market(
            self.spec,
            self.target_date,
            get_json=self.get_json,
            now=datetime.now(self.spec.tz),
        )

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

    def parse_nws_grid_valid_time(self, value):
        if not value:
            return None
        start = str(value).split("/")[0]
        try:
            return datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(self.spec.tz)
        except ValueError:
            return None

    def nws_grid_value(self, value, uom=None, is_temp=False):
        number = self.to_number(value)
        if number is None:
            return None
        uom_text = str(uom or "")
        if is_temp:
            if "degC" in uom_text:
                return self.forecast_temp_to_native(number, "C")
            if "degF" in uom_text:
                return self.forecast_temp_to_native(number, "F")
        if "mi_h-1" in uom_text or "mile" in uom_text.lower():
            return round(number * 1.609344, 2)
        return number

    def nws_grid_value_count(self, value):
        if value in (None, ""):
            return 0
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return 1 if value else 0
        return 1

    def payload_hash(self, payload):
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha1(encoded).hexdigest()

    def hours_between(self, later, earlier):
        later_dt = self.parse_any_utc_time(later)
        earlier_dt = self.parse_any_utc_time(earlier)
        if later_dt is None or earlier_dt is None:
            return None
        return (later_dt - earlier_dt).total_seconds() / 3600.0

    def parse_any_utc_time(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

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
            "air_temp_native": self.to_number(element_value("air_temp")),
            "air_temp_c": self.to_number(element_value("air_temp")),
            "dewpoint_native": self.to_number(element_value("dwpt_temp")),
            "dewpoint_c": self.to_number(element_value("dwpt_temp")),
            "humidity": self.to_number(element_value("rel_hum")),
            "max_1h_native": self.to_number(element_value("max_air_temp_pst1hr")),
            "max_1h_c": self.to_number(element_value("max_air_temp_pst1hr")),
            "max_6h_native": self.to_number(element_value("max_air_temp_pst6hrs")),
            "max_6h_c": self.to_number(element_value("max_air_temp_pst6hrs")),
            "max_24h_native": self.to_number(element_value("max_air_temp_pst24hrs")),
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
