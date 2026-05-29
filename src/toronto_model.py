import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import requests

from market_config import config_for_date, config_from_event
from wu_history import DEFAULT_DATA_ROOT, analyze_daily_summary


DEFAULT_MARKET_CONFIG = config_for_date()
TORONTO_TZ = ZoneInfo("America/Toronto")
TARGET_DATE = DEFAULT_MARKET_CONFIG.target_date
TARGET_DATE_STR = DEFAULT_MARKET_CONFIG.target_date_str
# Weather.com's public web API key. Overridable via env; the default is the
# widely-published browser key, kept so the app runs without configuration.
WEATHER_COM_KEY = os.environ.get(
    "WEATHER_COM_API_KEY", "e1f10a1e78da46f5b10a1e78da96f525"
)
CYYZ_HISTORY_ID = "CYYZ:9:CA"
CYYZ_ICAO = "CYYZ"
PEARSON_LAT = 43.6767
PEARSON_LON = -79.6306
HISTORY_MIN_ROW_COUNT = 20
HISTORY_WINDOW_DAYS = 7
INTRADAY_CUTOFF_HOURS = (9, 10, 12, 13, 15, 16, 17, 18, 20)
LIVE_CACHE_MAX_AGE_MINUTES = 90

# Model-version labels — the single source of truth shared with snapshot_tracker.
ML_MODEL_VERSION = "v0.4.9"
MODEL_VERSION_HGB = f"{ML_MODEL_VERSION} HGBC feature-based ML model"
MODEL_VERSION_LR = f"{ML_MODEL_VERSION} LogisticRegression feature-based ML model"
MODEL_VERSION_EMPIRICAL = "v0.3.1 empirical lookup baseline"

# Sentinel so memoized loaders can cache a None result (missing/failed file)
# without re-reading from disk on every build.
_UNLOADED = object()


class TorontoHighTempModel:
    _historical_target_cache = {}

    def __init__(self, timeout=8, target_date=None):
        self.timeout = timeout
        self.set_target_date(target_date or TARGET_DATE)
        self.calibrated_weights = self.load_calibrated_weights()
        self.active_model_kind = "empirical"
        self._feature_model_hgb = _UNLOADED
        self._feature_model_coefs = _UNLOADED
        self._late_day_model_coefs = _UNLOADED

    def set_target_date(self, target_date):
        self.config = config_for_date(target_date)
        self.target_date = self.config.target_date
        self.target_date_str = self.config.target_date_str
        return self

    def sync_target_date_from_event(self, event):
        config = config_from_event(event, fallback_date=self.target_date)
        if config.target_date != self.target_date:
            self.set_target_date(config.target_date)

    def load_calibrated_weights(self):
        path = Path(__file__).parent / "calibrated_weights.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading calibrated weights: {e}")
        return None

    def calibrated_hour_config(self, cutoff_hour):
        if not self.calibrated_weights:
            return None
        key = str(cutoff_hour)
        if isinstance(self.calibrated_weights, dict) and "hours" in self.calibrated_weights:
            return (self.calibrated_weights.get("hours") or {}).get(key)
        if isinstance(self.calibrated_weights, dict):
            return self.calibrated_weights.get(key)
        return None

    @classmethod
    def clear_historical_cache(cls):
        cls._historical_target_cache = {}

    def build(self, event, historical_sources=None, live_sources=None, now=None):
        self.sync_target_date_from_event(event)
        if historical_sources is None and live_sources is None:
            sources = self.fetch_sources()
        else:
            sources = {}
            sources.update(historical_sources or {})
            sources.update(live_sources or {})
        # One timestamp for the whole build so every panel (distribution, cutoff,
        # analogs, transitions, late-day) agrees, and so callers can backtest by
        # passing a historical `now`.
        now_tz = now or datetime.now(TORONTO_TZ)
        distribution = self.estimate_distribution(sources, now=now_tz)
        model_rows = self.model_market_rows(event, distribution)
        top_temp = max(distribution, key=distribution.get) if distribution else None

        cutoff_hour = self.effective_intraday_cutoff_hour(
            now_tz,
            self.source_data(sources, "wu_history").get("rows") or [],
        )
        # Compute analogs once at the effective cutoff and reuse them in the deep
        # dive, so both panels agree and the heaviest lookup runs a single time.
        analog_search = self.find_analog_days(sources, cutoff_hour, now_tz, limit=5)
        return {
            "sources": sources,
            "distribution": distribution,
            "model_rows": model_rows,
            "source_rows": self.source_rows(sources),
            "forecast_rows": self.forecast_rows(sources),
            "deep_dive_rows": self.deep_dive_rows(sources, distribution, analog_search, now=now_tz),
            "notes": self.model_notes(sources),
            "top_temp": top_temp,
            "model_version": self.get_model_version_string(),
            "boundary_transitions": self.get_bucket_transitions(sources, now_tz),
            "late_day_risk": self.predict_late_day_continuation(sources, cutoff_hour, now_tz),
            "analog_search": analog_search,
            "model_explanation": self.get_model_explanation(sources, distribution),
        }

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
        fetched = self.fetch_source_group({
            "wu_history": self.fetch_wu_history,
            "wu_current": self.fetch_wu_current,
            "eccc_citypage": self.fetch_eccc_citypage,
            "eccc_swob": self.fetch_eccc_swob,
            "metar": self.fetch_metar,
            "weather_forecast": self.fetch_weather_com_forecast,
            "open_meteo": self.fetch_open_meteo,
        })
        return self.blend_with_last_good(fetched)

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
                fetched_time = datetime.now(TORONTO_TZ).isoformat()
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
        cache_path = DEFAULT_DATA_ROOT / "last_good_sources.json"
        
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
            DEFAULT_DATA_ROOT.mkdir(parents=True, exist_ok=True)
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
            parsed = parsed.replace(tzinfo=TORONTO_TZ)
        return max(0.0, (datetime.now(TORONTO_TZ) - parsed.astimezone(TORONTO_TZ)).total_seconds() / 60.0)

    def fetch_wu_history(self):
        url = (
            "https://api.weather.com/v1/location/"
            f"{CYYZ_HISTORY_ID}/observations/historical.json"
        )
        payload = self.get_json(url, {
            "apiKey": WEATHER_COM_KEY,
            "units": "m",
            "startDate": self.target_date_str,
            "endDate": self.target_date_str,
        })

        rows = []
        for obs in payload.get("observations", []) or []:
            local_dt = datetime.fromtimestamp(
                obs.get("valid_time_gmt", 0), timezone.utc
            ).astimezone(TORONTO_TZ)
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
            "units": "m",
            "format": "json",
            "icaoCode": CYYZ_ICAO,
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
        summary_path = DEFAULT_DATA_ROOT / "daily" / "daily_summary.csv"
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
            "prob_25": probabilities.get(25),
            "prob_25_plus": sum(
                probability for bucket, probability in probabilities.items()
                if bucket >= 25
            ),
            "prob_29_plus": sum(
                probability for bucket, probability in probabilities.items()
                if bucket >= 29
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
            with ThreadPoolExecutor(max_workers=min(8, len(files))) as executor:
                parsed = executor.map(
                    lambda filename: self.parse_swob_xml(
                        requests.get(f"{base_url}{filename}", timeout=self.timeout).text
                    ),
                    files,
                )
                for row in parsed:
                    if row.get("local_date") == self.target_date.isoformat():
                        rows.append(row)

        latest = rows[-1] if rows else None
        same_day_max = self.max_value(*[
            self.max_value(row.get("air_temp_c"), row.get("max_1h_c"))
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
            "ids": CYYZ_ICAO,
            "format": "json",
        })
        row = payload[0] if payload else {}
        report_time = self.parse_utc_time(row.get("reportTime"))
        is_target_day = report_time is not None and report_time.date() == self.target_date
        return {
            "url": url,
            "report_time": row.get("reportTime"),
            "target_date_match": is_target_day,
            "temp_c": self.to_number(row.get("temp")) if is_target_day else None,
            "dewpoint_c": self.to_number(row.get("dewp")) if is_target_day else None,
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
            "geocode": f"{PEARSON_LAT},{PEARSON_LON}",
            "units": "m",
            "language": "en-US",
            "format": "json",
        })
        rows = []
        now = datetime.now(TORONTO_TZ)
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
            "latitude": PEARSON_LAT,
            "longitude": PEARSON_LON,
            "hourly": (
                "temperature_2m,cloud_cover,cloud_cover_low,cloud_cover_mid,"
                "cloud_cover_high,wind_speed_10m,shortwave_radiation"
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "America/Toronto",
            "forecast_days": 2,
        })
        hourly = payload.get("hourly", {}) or {}
        rows = []
        now = datetime.now(TORONTO_TZ).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date or dt < now:
                continue
            local_dt = dt.replace(tzinfo=TORONTO_TZ)
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
        return {"url": url, "rows": rows[:12]}

    def estimate_distribution(self, sources, now=None):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        metar = self.source_data(sources, "metar")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")

        now = now or datetime.now(TORONTO_TZ)
        history_max = history.get("max_c")
        current_temp = current.get("temp_c")
        current_max = current.get("max_since_7am_c")
        eccc_max = eccc.get("same_day_max_c")
        metar_temp = metar.get("temp_c")
        weather_forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        open_meteo_max = self.max_row_temp(open_meteo.get("rows"))
        eccc_forecast_high = eccc_city.get("forecast_high_c")

        local_analysis = local_history.get("analysis") or {}
        probabilities = local_analysis.get("bucket_probabilities") or {}
        if local_history.get("available") and local_analysis.get("target_window_count", 0) >= 30:
            scores = {
                int(bucket): float(probability)
                for bucket, probability in probabilities.items()
            }
        else:
            scores = {temp: 1.0 / 25.0 for temp in range(8, 33)}

        live_values = [
            history_max,
            current_temp,
            current_max,
            self.round_half_up(eccc_max) if eccc_max is not None else None,
            metar_temp,
            weather_forecast_max,
            self.round_half_up(open_meteo_max) if open_meteo_max is not None else None,
            eccc_forecast_high,
        ]
        observed_bucket = self.round_half_up(history_max)
        max_signal = self.round_half_up(self.max_value(*live_values))
        if max_signal is None and not scores:
            return {}

        low = min(min(scores), 8, (observed_bucket or max_signal or 16) - 5)
        high = max(max(scores), 34, (max_signal or observed_bucket or 30) + 4)
        for temp in range(low, high + 1):
            scores.setdefault(temp, 0.0005)
        scores = self.normalize_scores(scores)

        cutoff_hour = self.effective_intraday_cutoff_hour(
            now,
            history.get("rows") or [],
        )
        weights_config = self.calibrated_hour_config(cutoff_hour)
        weight_map = (weights_config or {}).get("weights") or (weights_config or {})
        has_component_weights = any(
            name in weight_map
            for name in (
                "climatology",
                "intraday_high",
                "current_bucket",
                "wind_regime",
                "cloud_regime",
                "forecast_cap",
            )
        )
        
        intraday = None
        using_feature_model = False
        feature_probs, active_kind = self.predict_feature_distribution(sources, cutoff_hour, now)
        using_calibrated_empirical = False
        if feature_probs:
            using_feature_model = True
            self.active_model_kind = active_kind
            feature_probs = self.ordinal_smooth_distribution(
                feature_probs,
                sigma=0.75,
                blend_weight=0.50,
            )
            # Blend the ML prediction as prior with climatology (scores), prior weight = 0.80
            scores = self.blend_distribution(scores, feature_probs, 0.80)
        else:
            self.active_model_kind = "empirical"
            intraday = self.historical_intraday_distribution(
                observed_bucket, cutoff_hour
            )
            wind_group = self.live_wind_group(current, weather_forecast)
            wind_distribution = self.historical_regime_distribution("wind", wind_group)
            cloud_group = self.live_cloud_group(current, eccc_city, weather_forecast)
            cloud_distribution = self.historical_regime_distribution("cloud", cloud_group)
            current_distribution = self.historical_current_distribution(
                self.round_half_up(current_temp),
                cutoff_hour,
            )
            calibrated_cap = self.round_half_up(self.max_value(
                observed_bucket,
                weather_forecast_max,
                open_meteo_max,
                eccc_forecast_high,
            ))
            cap_distribution = self.cap_prior_distribution(
                scores.keys(),
                calibrated_cap,
                floor_bucket=observed_bucket,
            )

            if has_component_weights:
                using_calibrated_empirical = True
                components = {
                    "climatology": scores,
                    "intraday_high": intraday["probabilities"] if intraday else None,
                    "current_bucket": current_distribution["probabilities"] if current_distribution else None,
                    "wind_regime": wind_distribution["probabilities"] if wind_distribution else None,
                    "cloud_regime": cloud_distribution["probabilities"] if cloud_distribution else None,
                    "forecast_cap": cap_distribution,
                }
                scores = self.weighted_component_distribution(
                    components,
                    weight_map,
                )
            else:
                if intraday:
                    if weights_config:
                        w_int_base = weights_config.get("w_intraday_base", 0.36)
                        intraday_weight = w_int_base * (intraday["n"] / (intraday["n"] + 25))
                    else:
                        intraday_weight = self.intraday_blend_weight(now.hour, intraday["n"])
                    scores = self.blend_distribution(
                        scores, intraday["probabilities"], intraday_weight
                    )

                if wind_distribution:
                    w_wnd = weights_config.get("w_wind", 0.14) if weights_config else 0.14
                    scores = self.blend_distribution(
                        scores, wind_distribution["probabilities"], w_wnd
                    )

                if cloud_distribution:
                    w_cld = weights_config.get("w_cloud", 0.12) if weights_config else 0.12
                    scores = self.blend_distribution(
                        scores, cloud_distribution["probabilities"], w_cld
                    )

        if using_feature_model:
            current_max_signal = None
            current_max_bucket = self.round_half_up(current_max)
            if current_max_bucket is not None and (
                observed_bucket is None or current_max_bucket > observed_bucket
            ):
                current_max_signal = current_max
            peak_cluster_values = [
                current_max_signal,
                weather_forecast_max,
                self.round_half_up(open_meteo_max)
                if open_meteo_max is not None else None,
            ]
            peak_cluster_signal = self.max_value(*peak_cluster_values)
            peak_cluster_count = sum(
                1 for value in peak_cluster_values if value is not None
            )
            peak_cluster_weight = 1.1 if peak_cluster_count <= 1 else 1.6
            live_signals = [
                # Current max, Weather.com forecast, and Open-Meteo often share
                # the same weather-family signal. Treat them as one peak cluster
                # so a single bucket does not get triple-counted.
                (peak_cluster_signal, peak_cluster_weight, 1.0),
                (eccc_max, 0.6, 0.8),
                (eccc_forecast_high, 0.5, 1.2),
            ]
        elif using_calibrated_empirical:
            live_signals = [
                (history_max, self.history_signal_weight(now.hour), 0.65),
                (
                    self.round_half_up(eccc_max) if eccc_max is not None else None,
                    0.6,
                    0.9,
                ),
                (metar_temp, 0.3, 0.9),
            ]
        else:
            live_signals = [
                (history_max, self.history_signal_weight(now.hour), 0.65),
                (current_temp, 1.8, 0.65),
                # Weather.com's 24h max can include the previous afternoon. For this
                # market we only use the same-day max-since-7am field.
                (current_max, 2.3, 0.75),
                (
                    self.round_half_up(eccc_max) if eccc_max is not None else None,
                    0.6,
                    0.9,
                ),
                (metar_temp, 0.3, 0.9),
                (weather_forecast_max, self.forecast_signal_weight(now.hour), 0.9),
                (
                    self.round_half_up(open_meteo_max)
                    if open_meteo_max is not None else None,
                    0.8,
                    1.1,
                ),
                (eccc_forecast_high, 0.5, 1.2),
            ]
        scores = self.apply_live_signals(scores, live_signals)

        history_bucket = self.round_half_up(history_max)
        if history_bucket is not None:
            self.apply_floor(scores, history_bucket, 0.001)
        if observed_bucket is not None:
            self.apply_floor(scores, observed_bucket, 0.000001)
            scores = self.normalize_scores(scores)

        if intraday and observed_bucket is not None:
            tail_target = sum(
                probability for temp, probability in intraday["probabilities"].items()
                if temp > observed_bucket
            )
            if weather_forecast_max is not None and self.round_half_up(weather_forecast_max) <= observed_bucket:
                tail_target *= 0.70
            if self.max_value(open_meteo_max, eccc_forecast_high) is not None:
                if self.round_half_up(self.max_value(open_meteo_max, eccc_forecast_high)) > observed_bucket:
                    tail_target *= 1.12
            tail_target = max(0.01, min(0.95, tail_target))
            scores = self.apply_tail_target(
                scores,
                observed_bucket,
                tail_target,
                self.tail_target_weight(now.hour),
            )

        plausible_cap = self.round_half_up(self.max_value(
            observed_bucket,
            weather_forecast_max,
            open_meteo_max,
            eccc_forecast_high,
        ))
        if plausible_cap is not None and not using_calibrated_empirical:
            for temp in list(scores):
                if temp > plausible_cap + 1:
                    scores[temp] *= 0.28 ** (temp - plausible_cap - 1)

        return self.normalize_scores(scores)

    def historical_target_cache(self):
        cache_key = self.target_date.isoformat()
        if cache_key in TorontoHighTempModel._historical_target_cache:
            return TorontoHighTempModel._historical_target_cache[cache_key]

        summary_path = DEFAULT_DATA_ROOT / "daily" / "daily_summary.csv"
        if not summary_path.exists():
            TorontoHighTempModel._historical_target_cache[cache_key] = {
                "daily": {},
                "by_date": {},
                "bucket_space": list(range(8, 35)),
            }
            return TorontoHighTempModel._historical_target_cache[cache_key]

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
                if not row.get("max_temp_bucket_c"):
                    continue
                reference_date = local_date.replace(year=reference_year)
                if abs((reference_date - target_reference).days) > HISTORY_WINDOW_DAYS:
                    continue
                daily[local_date] = {
                    "bucket": self.round_half_up(row.get("max_temp_bucket_c")),
                    "max_temp_c": self.to_number(row.get("max_temp_c")),
                    "condition_mode": row.get("condition_mode"),
                    "cloud_mode": row.get("cloud_mode"),
                }

        needed_paths = defaultdict(set)
        for local_date in daily:
            path = (
                DEFAULT_DATA_ROOT
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
                        "temp_c": self.to_number(row.get("temp_c")),
                        "dewpoint_c": self.to_number(row.get("dewpoint_c")),
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
        TorontoHighTempModel._historical_target_cache[cache_key] = {
            "daily": daily,
            "by_date": dict(by_date),
            "bucket_space": bucket_space or list(range(8, 35)),
            "conditional": {},
            "regime": {},
        }
        return TorontoHighTempModel._historical_target_cache[cache_key]

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

    def weighted_component_distribution(self, components, weights):
        support = sorted({
            int(bucket)
            for distribution in components.values()
            if distribution
            for bucket in distribution.keys()
        })
        if not support:
            return {}
        available = {
            name: self.normalize_scores(distribution)
            for name, distribution in components.items()
            if distribution
        }
        if not available:
            return {}
        raw_weights = {
            name: max(0.0, float(weights.get(name, 0.0)))
            for name in available
        }
        total_weight = sum(raw_weights.values())
        if total_weight <= 0:
            raw_weights = {name: 1.0 for name in available}
            total_weight = float(len(raw_weights))

        combined = {bucket: 0.0 for bucket in support}
        for name, distribution in available.items():
            component_weight = raw_weights[name] / total_weight
            for bucket in support:
                combined[bucket] += component_weight * distribution.get(bucket, 0.0)
        return self.normalize_scores(combined)

    def cap_prior_distribution(self, support, cap_bucket, floor_bucket=None, above_decay=0.28):
        if cap_bucket is None:
            return None
        support = sorted(int(bucket) for bucket in support)
        if not support:
            return None
        cap_bucket = int(cap_bucket)
        floor_bucket = int(floor_bucket) if floor_bucket is not None else None
        scores = {}
        for bucket in support:
            if floor_bucket is not None and bucket < floor_bucket:
                scores[bucket] = 0.02 ** max(1, floor_bucket - bucket)
            elif bucket <= cap_bucket:
                scores[bucket] = 1.0 / (1.0 + abs(bucket - cap_bucket))
            else:
                scores[bucket] = above_decay ** (bucket - cap_bucket)
        return self.normalize_scores(scores)

    def apply_live_signals(self, scores, signals):
        for value, weight, sigma in signals:
            if value is None:
                continue
            for temp in scores:
                scores[temp] *= 1 + weight * math.exp(
                    -0.5 * ((temp - value) / sigma) ** 2
                )
        return self.normalize_scores(scores)

    def apply_floor(self, scores, floor_bucket, multiplier):
        for temp in list(scores):
            if temp < floor_bucket:
                scores[temp] *= multiplier

    def apply_tail_target(self, scores, threshold, target_tail, weight):
        if weight <= 0:
            return self.normalize_scores(scores)
        scores = self.normalize_scores(scores)
        current_tail = sum(
            score for temp, score in scores.items()
            if temp > threshold
        )
        desired_tail = (1 - weight) * current_tail + weight * target_tail
        desired_tail = max(0.0, min(1.0, desired_tail))
        if current_tail > 0:
            tail_scale = desired_tail / current_tail
        else:
            tail_scale = 0.0
        current_body = 1 - current_tail
        if current_body > 0:
            body_scale = (1 - desired_tail) / current_body
        else:
            body_scale = 0.0
        return self.normalize_scores({
            temp: score * (tail_scale if temp > threshold else body_scale)
            for temp, score in scores.items()
        })

    def blend_distribution(self, scores, probabilities, weight):
        if not probabilities or weight <= 0:
            return self.normalize_scores(scores)
        current = self.normalize_scores(scores)
        keys = set(current) | {int(bucket) for bucket in probabilities}
        return self.normalize_scores({
            key: ((1 - weight) * current.get(key, 0.0))
            + (weight * float(probabilities.get(key, probabilities.get(str(key), 0.0))))
            for key in keys
        })

    def ordinal_smooth_distribution(self, probabilities, sigma=0.75, blend_weight=0.50):
        base = self.normalize_scores(probabilities)
        if not base or sigma <= 0 or blend_weight <= 0:
            return base
        smoothed = {}
        for bucket in base:
            weighted_sum = 0.0
            weight_total = 0.0
            for other_bucket, probability in base.items():
                distance = bucket - other_bucket
                weight = math.exp(-0.5 * (distance / sigma) ** 2)
                weighted_sum += probability * weight
                weight_total += weight
            smoothed[bucket] = weighted_sum / weight_total if weight_total else 0.0
        return self.blend_distribution(base, smoothed, blend_weight)

    def normalize_scores(self, scores):
        cleaned = {
            int(temp): max(0.0, float(score))
            for temp, score in scores.items()
            if score is not None
        }
        total = sum(cleaned.values())
        if total <= 0:
            return {}
        return {
            temp: score / total
            for temp, score in sorted(cleaned.items())
        }

    def smoothed_distribution(self, buckets, bucket_space, alpha=0.10):
        counts = Counter(int(bucket) for bucket in buckets)
        support = sorted(set(bucket_space) | set(counts))
        denominator = len(buckets) + alpha * len(support)
        return {
            bucket: (counts.get(bucket, 0) + alpha) / denominator
            for bucket in support
        }

    def intraday_cutoff_hour(self, now):
        hour = now.hour
        eligible = [cutoff for cutoff in INTRADAY_CUTOFF_HOURS if cutoff <= hour]
        return eligible[-1] if eligible else INTRADAY_CUTOFF_HOURS[0]

    def effective_intraday_cutoff_hour(self, now, rows):
        wall_cutoff = self.intraday_cutoff_hour(now)
        latest_minute = None
        for row in rows or []:
            minute = self.minute_of_day(row.get("time"))
            if minute is not None:
                latest_minute = minute if latest_minute is None else max(latest_minute, minute)
        if latest_minute is None:
            return wall_cutoff
        eligible = [
            cutoff for cutoff in INTRADAY_CUTOFF_HOURS
            if cutoff <= wall_cutoff and cutoff * 60 <= latest_minute
        ]
        return eligible[-1] if eligible else wall_cutoff

    def intraday_blend_weight(self, hour, sample_size):
        if hour >= 17:
            base = 0.82
        elif hour >= 15:
            base = 0.70
        elif hour >= 13:
            base = 0.58
        elif hour >= 12:
            base = 0.48
        else:
            base = 0.36
        return base * (sample_size / (sample_size + 25))

    def tail_target_weight(self, hour):
        if hour >= 18:
            return 0.90
        if hour >= 16:
            return 0.75
        if hour >= 15:
            return 0.55
        if hour >= 13:
            return 0.35
        return 0.15

    def history_signal_weight(self, hour):
        if hour >= 18:
            return 3.5
        if hour >= 16:
            return 2.7
        if hour >= 15:
            return 2.2
        if hour >= 13:
            return 1.6
        return 1.0

    def forecast_signal_weight(self, hour):
        if hour >= 16:
            return 1.0
        if hour >= 13:
            return 1.4
        return 1.8

    def historical_max_until(self, rows, cutoff):
        values = [
            row.get("temp_c") for row in rows
            if row.get("temp_c") is not None
            and row.get("minute_of_day") is not None
            and row["minute_of_day"] <= cutoff
        ]
        return max(values) if values else None

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
            hour, minute = str(value).split(":")[:2]
            return int(hour) * 60 + int(minute)
        except (TypeError, ValueError):
            return None

    def mode(self, values):
        cleaned = [value for value in values if value not in (None, "")]
        if not cleaned:
            return None
        return Counter(cleaned).most_common(1)[0][0]

    def model_market_rows(self, event, distribution):
        bins = self.market_bins(event)
        rows = []
        for bin_data in bins:
            model_prob = self.bin_probability(distribution, bin_data)
            market_yes = bin_data.get("market_yes")
            edge = model_prob - market_yes if market_yes is not None else None
            rows.append({
                "Range": bin_data["label"],
                "Model": self.format_pct(model_prob),
                "Market yes": self.format_pct(market_yes),
                "Edge": self.format_signed_pct(edge),
                "Market status": bin_data.get("status"),
            })
        return rows

    def market_bins(self, event):
        bins = []
        for market in event.get("markets", []) or []:
            label = self.clean_label(
                market.get("groupItemTitle") or market.get("question", "")
            )
            outcomes = self.parse_json_list(market.get("outcomes"))
            prices = self.parse_json_list(market.get("outcomePrices"))
            market_yes = self.price_for_outcome("Yes", outcomes, prices)
            market_no = self.price_for_outcome("No", outcomes, prices)
            digits = [int(value) for value in re.findall(r"\d+", label)]
            if not digits:
                continue
            value = digits[0]
            lower_label = label.lower()
            if "below" in lower_label:
                bin_data = {"kind": "lte", "value": value}
            elif "higher" in lower_label or "above" in lower_label:
                bin_data = {"kind": "gte", "value": value}
            else:
                bin_data = {"kind": "eq", "value": value}
            bin_data.update({
                "label": label,
                "question": market.get("question"),
                "market_id": market.get("id") or market.get("conditionId"),
                "market_yes": market_yes,
                "market_no": market_no,
                "best_bid": self.to_number(market.get("bestBid")),
                "best_ask": self.to_number(market.get("bestAsk")),
                "last_trade_price": self.to_number(market.get("lastTradePrice")),
                "volume": self.to_number(market.get("volumeNum") or market.get("volume")),
                "liquidity": self.to_number(
                    market.get("liquidityNum") or market.get("liquidity")
                ),
                "status": self.market_status(market),
            })
            bins.append(bin_data)
        return sorted(bins, key=self.bin_sort_key)

    def source_rows(self, sources):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        metar = self.source_data(sources, "metar")

        rows = []
        rows.append({
            "Source": "Wunderground history proxy",
            "Signal": "Printed history high",
            "Value": self.format_temp(history.get("max_c")),
            "Detail": ", ".join(history.get("max_times") or []) or "-",
            "Model role": "Primary settlement proxy",
        })
        latest = history.get("latest") or {}
        rows.append({
            "Source": "Wunderground history proxy",
            "Signal": "Latest printed row",
            "Value": self.format_temp(latest.get("temp_c")),
            "Detail": latest.get("time", "-"),
            "Model role": "Confirms table trend",
        })
        rows.append({
            "Source": "Weather.com current CYYZ",
            "Signal": "Current / max since 7 AM",
            "Value": (
                f"{self.format_temp(current.get('temp_c'))} / "
                f"{self.format_temp(current.get('max_since_7am_c'))}"
            ),
            "Detail": current.get("time", "-"),
            "Model role": "Same data family, discounted until in history",
        })
        local_analysis = local_history.get("analysis") or {}
        rows.append({
            "Source": "Local WU history",
            "Signal": "+/-7 day prior + intraday analogs",
            "Value": (
                f"25 C {self.format_pct(local_history.get('prob_25'))}"
                if local_history.get("prob_25") is not None else "-"
            ),
            "Detail": (
                f"{local_analysis.get('target_window_count', 0)} days; "
                f">=25 C {self.format_pct(local_history.get('prob_25_plus'))}"
                if local_history.get("available") else local_history.get("reason", "-")
            ),
            "Model role": "Empirical prior, catch-up, and late-day tail",
        })
        eccc_latest = eccc.get("latest") or {}
        rows.append({
            "Source": "ECCC SWOB CYYZ",
            "Signal": "Air / same-day max",
            "Value": (
                f"{self.format_temp(eccc_latest.get('air_temp_c'))} / "
                f"{self.format_temp(eccc.get('same_day_max_c'))}"
            ),
            "Detail": eccc_latest.get("time", "-"),
            "Model role": "Official station support, non-resolution",
        })
        rows.append({
            "Source": "Environment Canada forecast",
            "Signal": "Public forecast high",
            "Value": self.format_temp(eccc_city.get("forecast_high_c")),
            "Detail": eccc_city.get("forecast_cloud", "-"),
            "Model role": "Official forecast, non-resolution",
        })
        rows.append({
            "Source": "METAR CYYZ",
            "Signal": "Hourly airport report",
            "Value": self.format_temp(metar.get("temp_c")),
            "Detail": metar.get("report_time", "-"),
            "Model role": "Hourly sanity check",
        })
        return rows

    def deep_dive_rows(self, sources, distribution, analogs_data=None, now=None):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")

        rows = []

        # 1. Wunderground History
        hist_max = history.get("max_c")
        if hist_max is None:
            impact = "No historical printed observations yet. 25 C is wide open."
        elif hist_max >= 25:
            impact = f"Guaranteed floor. Printed high is already {hist_max} C (>= 25 C)."
        elif hist_max == 24:
            impact = "Extremely close. Needs only +1 C to reach 25 C."
        else:
            impact = f"Printed high is {hist_max} C. Needs {25 - hist_max} C rise."
        rows.append({
            "Question": "What has Wunderground history printed?",
            "Answer": self.format_temp(hist_max),
            "Impact on 25 C": impact,
        })

        # 2. Weather.com Current
        curr_temp = current.get("temp_c")
        max_7am = current.get("max_since_7am_c")
        if max_7am is not None and max_7am >= 25:
            impact = f"Strong indicator. Max since 7 AM is {max_7am} C, which matches or exceeds 25 C."
        elif curr_temp is not None and curr_temp >= 25:
            impact = f"Very bullish. Live temperature is already {curr_temp} C."
        else:
            impact = f"Current temp is {curr_temp or '-'} C; max since 7 AM is {max_7am or '-'} C."
        rows.append({
            "Question": "What does Weather.com current say?",
            "Answer": f"current {self.format_temp(curr_temp)}, max since 7 AM {self.format_temp(max_7am)}",
            "Impact on 25 C": impact,
        })

        # 3. ECCC SWOB
        swob_max = eccc.get("same_day_max_c")
        if swob_max is not None and swob_max >= 25.0:
            impact = f"Floor validator. SWOB same-day max is {swob_max} C, guaranteeing settlement >= 25 C."
        elif swob_max is not None:
            impact = f"Pearson SWOB max is {swob_max} C, trailing 25 C by {25.0 - swob_max:.1f} C."
        else:
            impact = "No live SWOB observations yet."
        rows.append({
            "Question": "What does the official station (SWOB) support?",
            "Answer": self.format_temp(swob_max),
            "Impact on 25 C": impact,
        })

        # 4. Weather.com hourly forecast
        fc_max = self.max_row_temp(weather_forecast.get("rows"))
        if fc_max is not None and fc_max >= 25:
            impact = f"Bullish. Hourly forecast projects high will reach {fc_max} C."
        elif fc_max is not None:
            impact = f"Bearish forecast. Peak forecast is {fc_max} C, suggesting 25 C will not be reached."
        else:
            impact = "No forecast data available."
        rows.append({
            "Question": "What does Weather.com forecast for remaining hours?",
            "Answer": self.format_temp(fc_max),
            "Impact on 25 C": impact,
        })

        # 5. Open-Meteo & ECCC Citypage
        om_max = self.max_row_temp(open_meteo.get("rows"))
        ec_high = eccc_city.get("forecast_high_c")
        alt_max = max([val for val in [om_max, ec_high] if val is not None], default=None)
        if alt_max is not None and alt_max >= 25:
            impact = f"Bullish alternative forecast. Alt models project a high of {alt_max} C."
        elif alt_max is not None:
            impact = f"Bearish. Alternative models peak at {alt_max} C."
        else:
            impact = "No alternative forecast data."
        rows.append({
            "Question": "What says 25 C or higher is live?",
            "Answer": f"Open-Meteo max {self.format_temp(om_max)}, ECCC forecast high {self.format_temp(ec_high)}",
            "Impact on 25 C": impact,
        })

        # 6. Local WU History
        prob_25 = local_history.get("prob_25")
        if prob_25 is not None:
            impact = f"Historical seasonal base rate for 25 C is {prob_25*100:.1f}%."
        else:
            impact = "No local history available."
        rows.append({
            "Question": "What does local WU history say?",
            "Answer": self.local_history_answer(local_history),
            "Impact on 25 C": impact,
        })

        # 7. Intraday Analogs
        if analogs_data is None:
            now = now or datetime.now(TORONTO_TZ)
            history_rows = self.source_data(sources, "wu_history").get("rows") or []
            analogs_data = self.find_analog_days(
                sources,
                self.effective_intraday_cutoff_hour(now, history_rows),
                now,
            )
        analog_n = 0
        analog_prob_25 = 0.0
        if isinstance(analogs_data, dict):
            analogs = analogs_data.get("analogs", [])
            analog_n = len(analogs)
            if analog_n > 0:
                count_25 = sum(1 for d in analogs if d["final_bucket"] == 25)
                analog_prob_25 = count_25 / analog_n
        if analog_n > 0:
            impact = f"Of the closest {analog_n} historical analogs, {analog_prob_25*100:.0f}% resolved to exactly 25 C."
        else:
            impact = "Insufficient analog days to evaluate."
        rows.append({
            "Question": "What do historical analogs say?",
            "Answer": f"{analog_n} analogs found",
            "Impact on 25 C": impact,
        })

        # 8. Model probability
        prob_exact = distribution.get(25, 0.0)
        rows.append({
            "Question": "Model probability for exact 25 C",
            "Answer": self.format_pct(prob_exact),
            "Impact on 25 C": f"Final model assigns {prob_exact*100:.1f}% probability to the exact 25 C bucket.",
        })

        return rows

    def get_model_explanation(self, sources, distribution):
        # 1. Active regimes and signals
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        eccc = self.source_data(sources, "eccc_swob")
        eccc_city = self.source_data(sources, "eccc_citypage")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")
        
        history_max = history.get("max_c")
        current_temp = current.get("temp_c")
        current_max = current.get("max_since_7am_c")
        observed_bucket = self.round_half_up(history_max)
        
        weather_forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        open_meteo_max = self.max_row_temp(open_meteo.get("rows"))
        eccc_forecast_high = eccc_city.get("forecast_high_c")
        
        plausible_cap = self.round_half_up(self.max_value(
            observed_bucket,
            weather_forecast_max,
            open_meteo_max,
            eccc_forecast_high,
        ))
        
        wind_group = self.live_wind_group(current, weather_forecast)
        cloud_group = self.live_cloud_group(current, eccc_city, weather_forecast)
        
        # 2. Top buckets in final distribution
        top_buckets = sorted(distribution.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # 3. Model type
        model_type = self.get_model_version_string()
        
        explanation = {
            "model_type": model_type,
            "observed_floor": observed_bucket,
            "forecast_cap": plausible_cap,
            "wind_regime": wind_group,
            "cloud_regime": cloud_group,
            "top_buckets": [
                {
                    "bucket": f"{temp} C",
                    "probability": self.format_pct(prob),
                    "status": "Floor constraint" if observed_bucket is not None and temp < observed_bucket else (
                        "Cap constraint" if plausible_cap is not None and temp > plausible_cap + 1 else "Primary projection"
                    )
                }
                for temp, prob in top_buckets
            ]
        }
        return explanation

    def forecast_rows(self, sources):
        rows = []
        weather = self.source_data(sources, "weather_forecast")
        for row in weather.get("rows", [])[:8]:
            rows.append({
                "Source": "Weather.com forecast",
                "Time": row.get("time"),
                "Temp": self.format_temp(row.get("temp_c")),
                "Cloud": self.format_pct_number(row.get("cloud_cover")),
                "Condition": row.get("condition"),
                "Wind": f"{row.get('wind', '-')}, {row.get('wind_kmh', '-')} km/h",
            })

        open_meteo = self.source_data(sources, "open_meteo")
        for row in open_meteo.get("rows", [])[:8]:
            rows.append({
                "Source": "Open-Meteo forecast",
                "Time": row.get("time"),
                "Temp": self.format_temp(row.get("temp_c")),
                "Cloud": self.format_pct_number(row.get("cloud_cover")),
                "Condition": f"solar {row.get('solar', '-')} W/m2",
                "Wind": f"{row.get('wind_kmh', '-')} km/h",
            })
        return rows

    def model_notes(self, sources):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        weather_forecast = self.source_data(sources, "weather_forecast")

        notes = [
            (
                "Resolution is modeled as the highest whole-degree C value "
                f"that Wunderground history prints for CYYZ on {self.config.display_date}."
            ),
            (
                "Wunderground/Weather.com history rows are the strongest input; "
                "current max fields are discounted until they appear in history."
            ),
        ]
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            notes.append("Prior probabilities generated by the HistGradientBoosting ML model (v0.4).")
        elif kind == "lr":
            notes.append("Prior probabilities generated by the Logistic Regression ML model coefficients (v0.4).")
        else:
            notes.append("Prior probabilities generated by the empirical lookups baseline (v0.3).")
        if history.get("max_c") is not None:
            notes.append(
                f"Current printed WU-history high is {self.format_temp(history.get('max_c'))}."
            )
        if current.get("max_since_7am_c") is not None:
            notes.append(
                "Weather.com current says max since 7 AM is "
                f"{self.format_temp(current.get('max_since_7am_c'))}."
            )
        eccc_latest = eccc.get("latest") or {}
        if eccc.get("same_day_max_c") is not None:
            notes.append(
                "ECCC SWOB same-day max is "
                f"{self.format_temp(eccc.get('same_day_max_c'))}; "
                "this can catch intra-hour highs that WU history may miss."
            )
        forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        if forecast_max is not None:
            notes.append(
                f"Weather.com remaining-hour forecast max is {self.format_temp(forecast_max)}."
            )
        if eccc_city.get("forecast_high_c") is not None:
            notes.append(
                "Environment Canada public forecast high is "
                f"{self.format_temp(eccc_city.get('forecast_high_c'))}; "
                "it is included as a lower-weight non-resolution forecast."
            )
        if local_history.get("available"):
            count = (local_history.get("analysis") or {}).get("target_window_count", 0)
            notes.append(
                f"Local WU history has {count} days in the {self.target_date:%B %d} +/-7-day window; "
                "the live curve now blends the base prior with matching intraday analogs."
            )
            notes.append(
                "Historical target-season data found non-hourly-only settlement highs "
                "rare, so hourly catch-up matters more than hidden intra-hour spikes."
            )
        return notes

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

    def get_json(self, url, params):
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

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

    def bin_probability(self, distribution, bin_data):
        if not distribution:
            return 0.0
        value = bin_data["value"]
        if bin_data["kind"] == "lte":
            return sum(prob for temp, prob in distribution.items() if temp <= value)
        if bin_data["kind"] == "gte":
            return sum(prob for temp, prob in distribution.items() if temp >= value)
        return distribution.get(value, 0.0)

    def bin_sort_key(self, bin_data):
        if bin_data["kind"] == "lte":
            return -1
        if bin_data["kind"] == "gte":
            return 10_000
        return bin_data["value"]

    def market_status(self, market):
        if market.get("closed"):
            return market.get("umaResolutionStatus") or "closed"
        if market.get("active"):
            return "active"
        return "inactive"

    def parse_json_list(self, value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def price_for_outcome(self, outcome_name, outcomes, prices):
        for index, outcome in enumerate(outcomes):
            if str(outcome).lower() == outcome_name.lower() and index < len(prices):
                return self.to_number(prices[index])
        return None

    def parse_weather_com_time(self, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(TORONTO_TZ)
        except ValueError:
            pass
        # Fallback for other ISO-8601 offsets (colon in offset, missing seconds,
        # or a trailing Z) that strptime's fixed format would reject.
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TORONTO_TZ)
        except ValueError:
            return None

    def parse_utc_time(self, value):
        if not value:
            return None
        try:
            value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(value).astimezone(TORONTO_TZ)
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

    def local_history_answer(self, local_history):
        if not local_history.get("available"):
            return local_history.get("reason", "-")
        analysis = local_history.get("analysis") or {}
        count = analysis.get("target_window_count", 0)
        return (
            f"{count} days; 25 C base rate {self.format_pct(local_history.get('prob_25'))}, "
            f">=25 C {self.format_pct(local_history.get('prob_25_plus'))}, "
            f">=29 C {self.format_pct(local_history.get('prob_29_plus'))}"
        )

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

    def clean_label(self, label):
        return (
            str(label)
            .replace("Â°C", " C")
            .replace("�C", " C")
            .replace("°C", " C")
        )

    def format_temp(self, value):
        if value is None:
            return "-"
        if float(value).is_integer():
            return f"{int(value)} C"
        return f"{float(value):.1f} C"

    def format_pct(self, value):
        if value is None:
            return "-"
        return f"{value * 100:.1f}%"

    def format_signed_pct(self, value):
        if value is None:
            return "-"
        return f"{value * 100:+.1f}%"

    def format_pct_number(self, value):
        if value is None:
            return "-"
        return f"{float(value):.0f}%"

    def load_feature_model_hgb(self):
        if self._feature_model_hgb is _UNLOADED:
            self._feature_model_hgb = self._read_feature_model_hgb()
        return self._feature_model_hgb

    def _read_feature_model_hgb(self):
        path = Path(__file__).parent / "feature_model_hgb.pkl"
        if path.exists():
            try:
                import pickle
                with path.open("rb") as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"Error loading HGBC pickle: {e}")
        return None

    def load_feature_model_coefs(self):
        if self._feature_model_coefs is _UNLOADED:
            self._feature_model_coefs = self._read_feature_model_coefs()
        return self._feature_model_coefs

    def _read_feature_model_coefs(self):
        path = Path(__file__).parent / "feature_model_coefs.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading LR JSON coefs: {e}")
        return None

    def get_model_version_string(self):
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            return MODEL_VERSION_HGB
        if kind == "lr":
            return MODEL_VERSION_LR
        return MODEL_VERSION_EMPIRICAL

    def extract_live_features(self, sources, cutoff_hour):
        """Build the cutoff-aligned feature vector shared by the feature model
        (HGB/LR) and the late-day continuation model.

        Both models were trained on the same fields, so they must extract them
        identically at inference time to avoid train/serve skew. This is the
        single source of truth for that extraction; callers add any model-
        specific features (e.g. late-day ``time_since_reached``) on top.

        Note: ``find_analog_days`` deliberately keeps its own extraction because
        it bails out on missing data instead of substituting seasonal defaults.
        """
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        weather_forecast = self.source_data(sources, "weather_forecast")
        eccc_city = self.source_data(sources, "eccc_citypage")

        rows = history.get("rows") or []
        feature_rows = self.source_rows_until_cutoff(rows, cutoff_hour)
        feature_latest = feature_rows[-1] if feature_rows else None

        # high_so_far
        temps = [r["temp_c"] for r in feature_rows if r.get("temp_c") is not None]
        current_temp = feature_latest.get("temp_c") if feature_latest else current.get("temp_c")
        if temps:
            high_so_far = max(temps)
        else:
            high_so_far = None

        # current_temp
        if current_temp is None:
            current_temp = current.get("temp_c")
        if current_temp is None:
            current_temp = rows[-1]["temp_c"] if rows else 17.0
        high_so_far = self.max_value(high_so_far, current_temp)
        if high_so_far is None:
            high_so_far = 17.0 # fallback

        # rise_from_7am
        obs_7am_candidates = [r for r in rows if r.get("time") and 360 <= self.minute_of_day(r["time"]) <= 480 and r.get("temp_c") is not None]
        temp_7am = None
        if obs_7am_candidates:
            closest_7am = min(obs_7am_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - 420))
            temp_7am = closest_7am["temp_c"]
        if temp_7am is None:
            temp_7am = 17.0 # default seasonal fallback
        rise_from_7am = current_temp - temp_7am

        # dewpoint_c, humidity, pressure
        dewpoint = feature_latest.get("dewpoint_c") if feature_latest else current.get("dewpoint_c")
        if dewpoint is None:
            dewpoint = rows[-1]["dewpoint_c"] if rows else 10.0 # fallback
        humidity = feature_latest.get("humidity") if feature_latest else current.get("humidity")
        if humidity is None:
            humidity = rows[-1]["humidity"] if rows else 60.0
        pressure = feature_latest.get("pressure") if feature_latest else current.get("pressure")
        if pressure is None:
            pressures = [r["pressure"] for r in rows if r.get("pressure") is not None]
            pressure = pressures[-1] if pressures else None

        # pressure_trend_3h
        cutoff_minutes = cutoff_hour * 60
        obs_3h_candidates = [r for r in rows if r.get("time") and (cutoff_minutes - 240) <= self.minute_of_day(r["time"]) <= (cutoff_minutes - 120) and r.get("pressure") is not None]
        pressure_trend_3h = 0.0
        if pressure is not None and obs_3h_candidates:
            closest_3h = min(obs_3h_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - (cutoff_minutes - 180)))
            press_3h_ago = closest_3h["pressure"]
            pressure_trend_3h = pressure - press_3h_ago

        # wind_speed_kmh
        wind_speed = feature_latest.get("wind_kmh") if feature_latest else current.get("wind_kmh")
        if wind_speed is None:
            wind_speed = rows[-1].get("wind_kmh") if rows else 15.0

        # wind_group and cloud_group
        wind_group = (
            self.wind_group(feature_latest.get("wind")) if feature_latest else None
        ) or self.live_wind_group(current, weather_forecast)
        cloud_group = (
            self.cloud_group(feature_latest.get("condition"), feature_latest.get("clouds"))
            if feature_latest else None
        ) or self.live_cloud_group(current, eccc_city, weather_forecast)

        return {
            "feature_rows": feature_rows,
            "feature_latest": feature_latest,
            "high_so_far": high_so_far,
            "current_temp": current_temp,
            "rise_from_7am": rise_from_7am,
            "dewpoint_c": dewpoint,
            "humidity": humidity,
            "pressure": pressure,
            "pressure_trend_3h": pressure_trend_3h,
            "wind_speed_kmh": wind_speed,
            "wind_group": wind_group,
            "cloud_group": cloud_group,
        }

    def predict_feature_distribution(self, sources, cutoff_hour, now):
        hgb_bundle = self.load_feature_model_hgb()
        lr_coefs = self.load_feature_model_coefs()

        if not hgb_bundle and not lr_coefs:
            return None, "empirical"

        feats = self.extract_live_features(sources, cutoff_hour)
        high_so_far = feats["high_so_far"]
        current_temp = feats["current_temp"]
        rise_from_7am = feats["rise_from_7am"]
        dewpoint = feats["dewpoint_c"]
        humidity = feats["humidity"]
        pressure = feats["pressure"]
        pressure_trend_3h = feats["pressure_trend_3h"]
        wind_speed = feats["wind_speed_kmh"]
        wind_group = feats["wind_group"]
        cloud_group = feats["cloud_group"]

        # Check if HGBC is available (preferred)
        if hgb_bundle and str(cutoff_hour) in hgb_bundle:
            try:
                bundle = hgb_bundle[str(cutoff_hour)]
                model_obj = bundle["model"]
                imputer_obj = bundle["imputer"]
                all_wind = bundle["all_wind_groups"]
                all_cloud = bundle["all_cloud_groups"]
                
                # Build feature dictionary
                feat_dict = {
                    "high_so_far": high_so_far,
                    "current_temp": current_temp,
                    "rise_from_7am": rise_from_7am,
                    "dewpoint_c": dewpoint,
                    "humidity": humidity,
                    "pressure": pressure,
                    "pressure_trend_3h": pressure_trend_3h,
                    "wind_speed_kmh": wind_speed
                }
                for g in all_wind:
                    feat_dict[f"wind_{g}"] = 1.0 if wind_group == g else 0.0
                for g in all_cloud:
                    feat_dict[f"cloud_{g}"] = 1.0 if cloud_group == g else 0.0
                    
                # Format as pandas DataFrame to avoid feature name warnings
                import pandas as pd
                X_feat = pd.DataFrame([feat_dict], columns=bundle["feature_names"])
                
                # Impute
                X_imputed = imputer_obj.transform(X_feat)
                
                # Predict probability distribution
                probs = model_obj.predict_proba(X_imputed)[0]
                classes = model_obj.classes_
                
                prob_dict = {int(c): float(p) for c, p in zip(classes, probs)}
                return prob_dict, "hgb"
            except Exception as e:
                print(f"Error predicting with HGBC model: {e}. Falling back to LR coefficients...")
                
        # Fallback to pure Python Logistic Regression coefficients
        if lr_coefs and str(cutoff_hour) in lr_coefs:
            try:
                coef_data = lr_coefs[str(cutoff_hour)]
                feature_names = coef_data["feature_names"]
                classes = coef_data["classes"]
                coef = coef_data["coef"] # Shape: (n_classes, n_features)
                intercept = coef_data["intercept"] # Shape: (n_classes,)
                scaler_mean = coef_data["scaler_mean"]
                scaler_scale = coef_data["scaler_scale"]
                imputer_median = coef_data["imputer_median"]
                
                # Build raw feature vector
                raw_vec = [
                    high_so_far, current_temp, rise_from_7am, dewpoint,
                    humidity, pressure, pressure_trend_3h, wind_speed
                ]
                # Impute first 8 elements
                for i in range(8):
                    if raw_vec[i] is None:
                        raw_vec[i] = imputer_median[i]
                # Scale first 8 elements
                scaled_vec = [(raw_vec[i] - scaler_mean[i]) / scaler_scale[i] for i in range(8)]
                
                # Add one-hot encoded groups (index 8 onwards)
                for name in feature_names[8:]:
                    if name.startswith("wind_"):
                        g = name[5:]
                        scaled_vec.append(1.0 if wind_group == g else 0.0)
                    elif name.startswith("cloud_"):
                        g = name[6:]
                        scaled_vec.append(1.0 if cloud_group == g else 0.0)
                    else:
                        scaled_vec.append(0.0)
                        
                # Compute logits: z_c = sum_j coef_{c, j} * x_j + intercept_c
                logits = []
                for c_idx in range(len(classes)):
                    z = sum(coef[c_idx][j] * scaled_vec[j] for j in range(len(scaled_vec))) + intercept[c_idx]
                    logits.append(z)
                    
                # Softmax
                max_logit = max(logits)
                exp_logits = [math.exp(z - max_logit) for z in logits]
                sum_exp = sum(exp_logits)
                probs = [ez / sum_exp for ez in exp_logits]
                
                prob_dict = {int(classes[c_idx]): float(probs[c_idx]) for c_idx in range(len(classes))}
                return prob_dict, "lr"
            except Exception as e:
                print(f"Error predicting with LR coefficients: {e}. Falling back to empirical prior...")
                
        return None, "empirical"

    def get_bucket_transitions(self, sources, now):
        history = self.source_data(sources, "wu_history")
        observed_bucket = self.round_half_up(history.get("max_c"))
        
        cutoff_hour = self.effective_intraday_cutoff_hour(
            now,
            history.get("rows") or [],
        )
        
        if observed_bucket is None:
            return {
                "current_max_bucket": None,
                "observed_bucket": None,
                "cutoff_hour": cutoff_hour,
                "sample_size": 0,
                "transitions": [],
                "skip_rate": 0.0
            }
            
        cache = self.historical_target_cache()
        daily = cache["daily"]
        by_date = cache["by_date"]
        
        cutoff = cutoff_hour * 60
        matching_final_buckets = []
        
        # 1. Compute transitions
        for local_date, daily_info in daily.items():
            rows = by_date.get(local_date, [])
            high_so_far = self.historical_max_until(rows, cutoff)
            if high_so_far is None:
                continue
            bucket_so_far = self.round_half_up(high_so_far)
            if bucket_so_far == observed_bucket:
                matching_final_buckets.append(daily_info["bucket"])
                
        # Calculate transition distribution
        transitions = []
        sample_size = len(matching_final_buckets)
        if sample_size >= 5:
            counts = Counter(matching_final_buckets)
            # Group into stays at X, rises to X+1, rises to X+2, rises to >= X+3
            for target_b in range(observed_bucket, observed_bucket + 3):
                cnt = counts.get(target_b, 0)
                prob = cnt / sample_size
                transitions.append({
                    "Target Bucket": f"{target_b} C",
                    "Probability": f"{prob * 100:.1f}%",
                    "Historical Days": cnt
                })
            cnt_plus_3 = sum(cnt for target_b, cnt in counts.items() if target_b >= observed_bucket + 3)
            prob_plus_3 = cnt_plus_3 / sample_size
            transitions.append({
                "Target Bucket": f">= {observed_bucket + 3} C",
                "Probability": f"{prob_plus_3 * 100:.1f}%",
                "Historical Days": cnt_plus_3
            })
            
        # 2. Compute historical rate of intermediate bucket skips during afternoon warming (10 AM to 6 PM)
        total_warming_days = 0
        skipping_days = 0
        
        for local_date, rows in by_date.items():
            warm_rows = [r for r in rows if 600 <= r["minute_of_day"] <= 1080]
            if not warm_rows:
                continue
            total_warming_days += 1
            
            temps = [r["temp_c"] for r in warm_rows if r.get("temp_c") is not None]
            if len(temps) < 2:
                continue
                
            has_skip = False
            for i in range(len(temps) - 1):
                t1, t2 = temps[i], temps[i+1]
                b1 = self.round_half_up(t1)
                b2 = self.round_half_up(t2)
                # Check for an upward jump that skips an integer bucket (e.g. 23 C -> 25 C)
                if b2 >= b1 + 2:
                    has_skip = True
                    break
            if has_skip:
                skipping_days += 1
                
        skip_rate = (skipping_days / total_warming_days) if total_warming_days > 0 else 0.0
        
        return {
            "current_max_bucket": observed_bucket,
            "observed_bucket": observed_bucket,
            "cutoff_hour": cutoff_hour,
            "sample_size": sample_size,
            "transitions": transitions,
            "skip_rate": skip_rate
        }

    def load_late_day_model_coefs(self):
        if self._late_day_model_coefs is _UNLOADED:
            self._late_day_model_coefs = self._read_late_day_model_coefs()
        return self._late_day_model_coefs

    def _read_late_day_model_coefs(self):
        path = Path(__file__).parent / "late_day_model_coefs.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading late-day model coefficients: {e}")
        return None

    def predict_late_day_continuation(self, sources, cutoff_hour, now):
        coefs = self.load_late_day_model_coefs()
        if not coefs or str(cutoff_hour) not in coefs:
            return None

        # 1. Extract the shared cutoff-aligned features (same as the feature model).
        feats = self.extract_live_features(sources, cutoff_hour)
        high_so_far = feats["high_so_far"]
        current_temp = feats["current_temp"]
        rise_from_7am = feats["rise_from_7am"]
        dewpoint = feats["dewpoint_c"]
        humidity = feats["humidity"]
        pressure = feats["pressure"]
        pressure_trend_3h = feats["pressure_trend_3h"]
        wind_speed = feats["wind_speed_kmh"]
        wind_group = feats["wind_group"]
        cloud_group = feats["cloud_group"]
        feature_rows = feats["feature_rows"]

        # 2. Late-day-specific feature: how long ago today's high was first reached.
        first_reached_min = None
        first_reached_time = None
        for r in feature_rows:
            if r.get("temp_c") == high_so_far:
                time_str = r.get("time")
                if time_str:
                    first_reached_time = time_str
                    first_reached_min = self.minute_of_day(time_str)
                    break
        if first_reached_min is None:
            # fallback to current time minus 30 mins
            first_reached_min = now.hour * 60 + now.minute - 30
            first_reached_time = f"{(now.hour * 60 + now.minute - 30)//60:02d}:{(now.hour * 60 + now.minute - 30)%60:02d}"

        time_since_reached = (now.hour * 60 + now.minute) - first_reached_min
        time_since_reached = max(0, time_since_reached)

        try:
            model_data = coefs[str(cutoff_hour)]
            feature_names = model_data["feature_names"]
            coef = model_data["coef"]
            intercept = model_data["intercept"]
            scaler_mean = model_data["scaler_mean"]
            scaler_scale = model_data["scaler_scale"]
            imputer_median = model_data["imputer_median"]
            
            raw_vec = [
                float(time_since_reached), high_so_far, current_temp, rise_from_7am,
                dewpoint, humidity, pressure, pressure_trend_3h, wind_speed
            ]
            for i in range(9):
                if raw_vec[i] is None:
                    raw_vec[i] = imputer_median[i]
            scaled_vec = [(raw_vec[i] - scaler_mean[i]) / scaler_scale[i] for i in range(9)]
            
            for name in feature_names[9:]:
                if name.startswith("wind_"):
                    g = name[5:]
                    scaled_vec.append(1.0 if wind_group == g else 0.0)
                elif name.startswith("cloud_"):
                    g = name[6:]
                    scaled_vec.append(1.0 if cloud_group == g else 0.0)
                else:
                    scaled_vec.append(0.0)
                    
            z = sum(coef[i] * scaled_vec[i] for i in range(len(scaled_vec))) + intercept
            prob = 1.0 / (1.0 + math.exp(-z))
            
            return {
                "active": True,
                "continuation_probability": prob,
                "time_since_reached": time_since_reached,
                "first_reached_time": first_reached_time,
                "empirical_prior": model_data.get("empirical_prior", 0.10)
            }
        except Exception as e:
            print(f"Error predicting late-day continuation: {e}")
            return None

    def find_analog_days(self, sources, cutoff_hour, now, limit=5):
        # Always return this shape so callers never have to type-check the result.
        empty_result = {"cutoff_hour": cutoff_hour, "today_features": {}, "analogs": []}
        # 1. Get cache
        cache = self.historical_target_cache()
        if not cache or not cache.get("daily"):
            return empty_result

        # 2. Extract today's live features
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        weather_forecast = self.source_data(sources, "weather_forecast")
        eccc_city = self.source_data(sources, "eccc_citypage")

        rows = history.get("rows") or []
        feature_rows = self.source_rows_until_cutoff(rows, cutoff_hour)
        feature_latest = feature_rows[-1] if feature_rows else None
        
        # Today's high_so_far
        temps = [r["temp_c"] for r in feature_rows if r.get("temp_c") is not None]
        today_current_temp = feature_latest.get("temp_c") if feature_latest else current.get("temp_c")
        if temps:
            today_high = max(temps)
        else:
            today_high = None

        # Today's current_temp
        if today_current_temp is None:
            today_current_temp = current.get("temp_c")
        if today_current_temp is None:
            today_current_temp = feature_latest.get("temp_c") if feature_latest else today_high
        if today_current_temp is None:
            today_current_temp = today_high
        today_high = self.max_value(today_high, today_current_temp)
        if today_high is None:
            today_high = current.get("max_since_7am_c")
        if today_high is None:
            return empty_result

        # Today's rise_from_7am
        obs_7am_candidates = [r for r in rows if r.get("time") and 360 <= self.minute_of_day(r["time"]) <= 480 and r.get("temp_c") is not None]
        temp_7am = None
        if obs_7am_candidates:
            closest_7am = min(obs_7am_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - 420))
            temp_7am = closest_7am["temp_c"]
        if temp_7am is None:
            temp_7am = today_current_temp
        today_rise = today_current_temp - temp_7am

        # Today's dewpoint
        today_dewpoint = feature_latest.get("dewpoint_c") if feature_latest else current.get("dewpoint_c")
        if today_dewpoint is None:
            today_dewpoint = current.get("dewpoint_c")
        if today_dewpoint is None:
            today_dewpoint = feature_latest.get("dewpoint_c") if feature_latest else 10.0
        if today_dewpoint is None:
            today_dewpoint = 10.0

        # Today's wind_group and cloud_group
        today_wind = (
            self.wind_group(feature_latest.get("wind")) if feature_latest else None
        ) or self.live_wind_group(current, weather_forecast)
        today_cloud = (
            self.cloud_group(feature_latest.get("condition"), feature_latest.get("clouds"))
            if feature_latest else None
        ) or self.live_cloud_group(current, eccc_city, weather_forecast)

        # 3. Extract historical features at same cutoff hour
        cutoff_minutes = cutoff_hour * 60
        hist_days_features = []
        
        for local_date, daily in cache["daily"].items():
            day_obs = cache["by_date"].get(local_date, [])
            if not day_obs:
                continue

            obs_before = [r for r in day_obs if r["minute_of_day"] <= cutoff_minutes]
            if not obs_before:
                continue
            
            # high_so_far
            h_temps = [r["temp_c"] for r in obs_before if r.get("temp_c") is not None]
            if not h_temps:
                continue
            h_high = max(h_temps)

            # current_temp
            h_curr_obs = obs_before[-1]
            h_curr_temp = h_curr_obs.get("temp_c")
            if h_curr_temp is None:
                h_curr_temp = h_high

            # temp at 7 AM
            h_obs_7am_candidates = [r for r in day_obs if 360 <= r["minute_of_day"] <= 480 and r.get("temp_c") is not None]
            h_temp_7am = None
            if h_obs_7am_candidates:
                closest_h_7am = min(h_obs_7am_candidates, key=lambda r: abs(r["minute_of_day"] - 420))
                h_temp_7am = closest_h_7am["temp_c"]
            if h_temp_7am is None:
                h_temp_7am = h_curr_temp

            h_rise = h_curr_temp - h_temp_7am

            # dewpoint
            h_dewpoint = h_curr_obs.get("dewpoint_c")
            if h_dewpoint is None:
                h_dews = [r["dewpoint_c"] for r in obs_before if r.get("dewpoint_c") is not None]
                h_dewpoint = h_dews[-1] if h_dews else 10.0

            # wind and cloud groups
            h_wind = self.wind_group(h_curr_obs.get("wind"))
            h_cloud = self.cloud_group(h_curr_obs.get("condition"), h_curr_obs.get("clouds"))

            hist_days_features.append({
                "date": local_date,
                "high_so_far": h_high,
                "rise_from_7am": h_rise,
                "dewpoint_c": h_dewpoint,
                "wind_group": h_wind,
                "cloud_group": h_cloud,
                "final_high": daily["max_temp_c"],
                "final_bucket": daily["bucket"],
                "observations": day_obs
            })

        if not hist_days_features:
            return empty_result

        # 4. Compute standard deviations of numeric features for scaling
        highs = [d["high_so_far"] for d in hist_days_features]
        rises = [d["rise_from_7am"] for d in hist_days_features]
        dews = [d["dewpoint_c"] for d in hist_days_features]

        def std_dev(vals, default=2.0):
            if len(vals) < 2:
                return default
            mean = sum(vals) / len(vals)
            variance = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
            std = math.sqrt(variance)
            return std if std > 0.1 else default

        std_high = std_dev(highs, 2.0)
        std_rise = std_dev(rises, 2.0)
        std_dew = std_dev(dews, 3.0)

        # 5. Compute distances and similarity scores
        w_high = 2.0
        w_rise = 1.5
        w_dew = 1.0
        w_wind = 1.0
        w_cloud = 1.0

        analogs = []
        for d in hist_days_features:
            d_high = ((d["high_so_far"] - today_high) / std_high) ** 2
            d_rise = ((d["rise_from_7am"] - today_rise) / std_rise) ** 2
            d_dew = ((d["dewpoint_c"] - today_dewpoint) / std_dew) ** 2

            d_wind = 1.0 if d["wind_group"] != today_wind else 0.0
            d_cloud = 1.0 if d["cloud_group"] != today_cloud else 0.0

            dist = math.sqrt(
                w_high * d_high +
                w_rise * d_rise +
                w_dew * d_dew +
                w_wind * d_wind +
                w_cloud * d_cloud
            )

            similarity = 100.0 * math.exp(-dist / 3.0)

            # Extract temperature path (hourly from 7 AM to 8 PM)
            temp_path = {}
            for h in range(7, 21):
                target_min = h * 60
                obs_candidates = [r for r in d["observations"] if r.get("temp_c") is not None]
                if obs_candidates:
                    closest_obs = min(obs_candidates, key=lambda r: abs(r["minute_of_day"] - target_min))
                    if abs(closest_obs["minute_of_day"] - target_min) <= 60:
                        temp_path[f"{h:02d}:00"] = closest_obs["temp_c"]
                    else:
                        temp_path[f"{h:02d}:00"] = None
                else:
                    temp_path[f"{h:02d}:00"] = None

            analogs.append({
                "date": d["date"].isoformat(),
                "distance": dist,
                "similarity": similarity,
                "final_high": d["final_high"],
                "final_bucket": d["final_bucket"],
                "high_so_far": d["high_so_far"],
                "rise_from_7am": d["rise_from_7am"],
                "dewpoint_c": d["dewpoint_c"],
                "wind_group": d["wind_group"],
                "cloud_group": d["cloud_group"],
                "temp_path": temp_path
            })

        analogs.sort(key=lambda x: x["distance"])

        # Also get today's temperature path
        today_temp_path = {}
        for h in range(7, 21):
            target_min = h * 60
            obs_candidates = [r for r in rows if r.get("temp_c") is not None]
            if obs_candidates:
                closest_obs = min(obs_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - target_min))
                if abs(self.minute_of_day(closest_obs["time"]) - target_min) <= 60:
                    today_temp_path[f"{h:02d}:00"] = closest_obs["temp_c"]
                else:
                    today_temp_path[f"{h:02d}:00"] = None
            else:
                today_temp_path[f"{h:02d}:00"] = None
        
        return {
            "cutoff_hour": cutoff_hour,
            "today_features": {
                "high_so_far": today_high,
                "rise_from_7am": today_rise,
                "dewpoint_c": today_dewpoint,
                "wind_group": today_wind,
                "cloud_group": today_cloud,
                "temp_path": today_temp_path
            },
            "analogs": analogs[:limit]
        }
