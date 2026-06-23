import hashlib
import json
import logging
import re
import statistics
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

from weather.io import acquire_writer_lock, release_writer_lock, write_json_atomic
from weather.sources.wu_history import DEFAULT_DATA_ROOT, analyze_daily_summary
from weather.sources.eccc_gridded import fetch_open_meteo_gem_for_market
from weather.sources.marine_context import active_marine_context_state, fetch_marine_context_for_market
from weather.sources.mrms_precip import fetch_mrms_precip_for_market
from weather.sources.nbm_probabilistic_tmax import (
    NBM_PROB_TMAX_SCHEMA_VERSION,
    nbp_cycle_candidates,
    nbp_text_url,
    parse_nbp_station_tmax,
)
from weather.model.source_adapters import (
    FETCH_META_KEY,
    SourceExpectedUnavailable,
    SourceProviderRateLimited,
    fetch_source_group as run_source_adapter_group,
    retry_after_seconds as response_retry_after_seconds,
)
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


OPEN_METEO_SOURCE_FAMILY = {
    "open_meteo",
    "open_meteo_air_quality",
    "open_meteo_global_models",
    "open_meteo_multimodel",
    "global_ensemble",
    "eccc_gem",
}
OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS = (
    "pm2_5",
    "pm10",
    "aerosol_optical_depth",
    "dust",
    "us_aqi",
    "european_aqi",
)
OPEN_METEO_GLOBAL_MODEL_MEMBERS = (
    "ecmwf_ifs025",
    "ecmwf_aifs025",
    "ncep_aigfs025",
    "gfs_graphcast025",
)
OPEN_METEO_RATE_LIMIT_COOLDOWN_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 10.0
TORONTO_OFFICIAL_CANADIAN_SOURCES = {
    "eccc_swob": "official_observation",
    "eccc_citypage": "official_forecast",
    "eccc_gem": "official_gridded_forecast",
}
TORONTO_OFFICIAL_SOURCE_LATE_DAY_HOUR = 15


def _is_retryable(exc):
    """Transient network errors worth retrying.

    Most 4xx responses are configuration/data availability problems, but 429 is
    a provider-capacity signal and gets retried with backoff/retry-after.
    """
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        if response is None:
            return False
        return response.status_code == 429 or response.status_code >= 500
    return False


def retry_after_seconds(exc):
    return response_retry_after_seconds(getattr(exc, "response", None))


def retry_delay_seconds(exc, attempt, base_delay=0.5, max_delay=MAX_RETRY_DELAY_SECONDS):
    retry_after = retry_after_seconds(exc)
    if retry_after is not None:
        return min(float(max_delay), retry_after)
    return min(float(max_delay), base_delay * (2 ** attempt))


def request_with_retries(
    fn,
    attempts=3,
    base_delay=0.5,
    sleep=time.sleep,
    max_delay=MAX_RETRY_DELAY_SECONDS,
):
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
                sleep(retry_delay_seconds(exc, attempt, base_delay=base_delay, max_delay=max_delay))
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

    _source_family_rate_limited_until = {}

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
            "open_meteo_air_quality": self.fetch_open_meteo_air_quality,
            "open_meteo_global_models": self.fetch_open_meteo_global_models,
            "nws_hourly": self.fetch_nws_hourly_forecast,
            "nws_grid": self.fetch_nws_grid_forecast,
            "nbm_probabilistic_tmax": self.fetch_nbm_probabilistic_tmax,
            "open_meteo_multimodel": self.fetch_open_meteo_multimodel,
            "global_ensemble": self.fetch_global_ensemble,
            "marine_context": self.fetch_marine_context,
            "mrms_precip": self.fetch_mrms_precip,
        }
        # Only fetch the sources this market declares (e.g. NYC has no ECCC/SWOB).
        # Open-Meteo Air Quality is a same-provider adjunct to the canonical
        # Open-Meteo forecast, so markets with Open-Meteo opt into it without
        # duplicating every market spec.
        source_names = list(self.spec.sources)
        if "open_meteo" in source_names and "open_meteo_air_quality" not in source_names:
            source_names.append("open_meteo_air_quality")
        if "open_meteo" in source_names and "open_meteo_global_models" not in source_names:
            source_names.append("open_meteo_global_models")
        if (
            ":US" in str(self.spec.wu_history_id)
            and ("nws_grid" in source_names or "open_meteo_multimodel" in source_names)
            and "nbm_probabilistic_tmax" not in source_names
        ):
            source_names.append("nbm_probabilistic_tmax")
        fetchers = {name: all_fetchers[name] for name in source_names if name in all_fetchers}
        fetchers = {
            name: self.source_fetcher_with_budget(name, fetcher)
            for name, fetcher in fetchers.items()
        }

        # wu_history rows must stay exactly what WU printed: the effective
        # cutoff, features, analogs, late-day model, and the replay corpus all
        # read them as settlement-source evidence. Live wu_current readings
        # reach the model through the live-signal weights and observed floors
        # instead of being spliced into history (v0.5.1 briefly injected a
        # backdated mock row here; reverted in v0.5.2).
        return self.blend_with_last_good(self.fetch_live_source_groups(fetchers))

    def fetch_source_group(self, fetchers, *, max_workers=None):
        fetchers = {
            name: fetcher
            for name, fetcher in fetchers.items()
        }
        return run_source_adapter_group(fetchers, timezone=self.spec.tz, max_workers=max_workers)

    def fetch_live_source_groups(self, fetchers):
        regular_fetchers = {
            name: fetcher
            for name, fetcher in fetchers.items()
            if self.source_family(name) != "open_meteo"
        }
        open_meteo_fetchers = {
            name: fetcher
            for name, fetcher in fetchers.items()
            if self.source_family(name) == "open_meteo"
        }
        fetched = {}
        if regular_fetchers:
            fetched.update(self.fetch_source_group(regular_fetchers))
        if open_meteo_fetchers:
            fetched.update(self.fetch_source_group(open_meteo_fetchers, max_workers=1))
        return fetched

    def source_family(self, name):
        if name in OPEN_METEO_SOURCE_FAMILY:
            return "open_meteo"
        return name

    def source_fetcher_with_budget(self, name, fetcher):
        if self.source_family(name) != "open_meteo":
            return fetcher

        def _fetch():
            cached = self.cached_source_for_reuse(
                name,
                self.open_meteo_fresh_cache_reuse_minutes(name),
            )
            if cached:
                return self.with_source_fetch_meta(
                    cached["data"],
                    {
                        "status": "fresh_cache",
                        "stale": False,
                        "source_family": "open_meteo",
                        "fetched_at": cached.get("fetched_at"),
                        "cache_age_minutes": cached.get("cache_age_minutes"),
                        "ttl_minutes": self.source_cache_ttl_minutes(name),
                        "degradation_state": "healthy",
                        "cache_status": "fresh_cache",
                    },
                )
            rate_limit = self.source_family_rate_limit_state("open_meteo")
            if rate_limit.get("active"):
                raise SourceProviderRateLimited(
                    (
                        "Open-Meteo provider family is in shared cooldown "
                        f"for {rate_limit['retry_after_seconds']:.0f}s"
                    ),
                    source_family="open_meteo",
                    retry_after_seconds=rate_limit.get("retry_after_seconds"),
                )
            try:
                data = fetcher()
            except Exception as exc:  # noqa: BLE001 - converted by source adapter
                if self.http_status(exc) == 429:
                    self.record_source_family_rate_limit(
                        "open_meteo",
                        retry_after_seconds=retry_after_seconds(exc),
                    )
                raise
            return self.with_source_fetch_meta(
                data,
                {
                    "source_family": "open_meteo",
                    "degradation_state": "healthy",
                    "cache_status": "live",
                },
            )

        return _fetch

    def open_meteo_fresh_cache_reuse_minutes(self, name):
        """Avoid re-querying Open-Meteo while the last-good forecast is TTL-valid."""
        return self.source_cache_ttl_minutes(name)

    def cached_source_for_reuse(self, name, max_age_minutes):
        cached_item = self.load_last_good_sources().get(name)
        if not cached_item or cached_item.get("target_date") != self.target_date.isoformat():
            return None
        cache_age_minutes = self.cache_age_minutes(cached_item.get("fetched_at"))
        if cache_age_minutes is None or cache_age_minutes > max_age_minutes:
            return None
        return {
            "data": cached_item.get("data") or {},
            "fetched_at": cached_item.get("fetched_at"),
            "cache_age_minutes": cache_age_minutes,
        }

    def load_last_good_sources(self):
        cache_path = self.last_good_sources_path()
        if not cache_path.exists():
            return {}
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                return payload
            raise ValueError("last good sources cache root must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            quarantine_path = self.quarantine_last_good_sources_cache(cache_path)
            logger.warning("Error loading last good sources cache: %s", e)
            if quarantine_path:
                logger.warning("Quarantined invalid last good sources cache at %s", quarantine_path)
            return {}
        except Exception as e:
            logger.warning("Error loading last good sources cache: %s", e)
            return {}

    def quarantine_last_good_sources_cache(self, cache_path):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantine_path = cache_path.with_name(
            f"{cache_path.stem}.corrupt.{timestamp}{cache_path.suffix}"
        )
        counter = 1
        while quarantine_path.exists():
            quarantine_path = cache_path.with_name(
                f"{cache_path.stem}.corrupt.{timestamp}.{counter}{cache_path.suffix}"
            )
            counter += 1
        try:
            cache_path.replace(quarantine_path)
            return quarantine_path
        except Exception as e:
            logger.warning("Error quarantining invalid last good sources cache: %s", e)
            return None

    def save_last_good_sources(self, cache):
        cache_path = self.last_good_sources_path()
        lock = None
        try:
            self.spec.data_root.mkdir(parents=True, exist_ok=True)
            lock = acquire_writer_lock(
                cache_path,
                owner={"component": "model_sources_last_good_cache"},
                attempts=20,
                stale_after_seconds=120,
                sleep_seconds=0.05,
            )
            if lock is None:
                logger.warning("Skipping last good sources cache save because writer lock is busy: %s", cache_path)
                return
            merged = self.load_last_good_sources()
            merged.update(cache)
            write_json_atomic(cache_path, merged)
        except Exception as e:
            logger.warning("Error saving last good sources cache: %s", e)
        finally:
            release_writer_lock(lock)

    def last_good_sources_path(self):
        return self.spec.data_root / "last_good_sources.json"

    def with_source_fetch_meta(self, data, metadata):
        if isinstance(data, dict):
            payload = dict(data)
            payload[FETCH_META_KEY] = dict(metadata)
            return payload
        return data

    def http_status(self, exc):
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)

    def source_family_rate_limit_state(self, source_family):
        until = self._source_family_rate_limited_until.get(source_family)
        if not until:
            return {"active": False, "retry_after_seconds": None}
        remaining = (until - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            self._source_family_rate_limited_until.pop(source_family, None)
            return {"active": False, "retry_after_seconds": None}
        return {"active": True, "retry_after_seconds": remaining}

    def record_source_family_rate_limit(self, source_family, retry_after_seconds=None):
        cooldown = retry_after_seconds
        if cooldown is None:
            cooldown = OPEN_METEO_RATE_LIMIT_COOLDOWN_SECONDS
        cooldown = max(float(cooldown), float(OPEN_METEO_RATE_LIMIT_COOLDOWN_SECONDS))
        self._source_family_rate_limited_until[source_family] = (
            datetime.now(timezone.utc) + timedelta(seconds=cooldown)
        )

    def source_metadata_fields(self, item, name):
        fields = {}
        for key in (
            "source_family",
            "http_status",
            "retry_after_seconds",
            "degradation_state",
            "cache_status",
            "fallback_source",
            "cache_age_minutes",
            "ttl_minutes",
        ):
            value = item.get(key)
            if value not in (None, ""):
                fields[key] = value
        fields.setdefault("source_family", self.source_family(name))
        return fields

    def source_failure_status(self, item):
        status = item.get("status")
        if status:
            return status
        if item.get("http_status") == 429:
            return "rate_limited"
        return "failed"

    def source_cache_fallback_status(self, failure_status):
        if failure_status == "rate_limited":
            return "rate_limited_cache"
        return "stale_cache"

    def source_degradation_state(self, status, item):
        if status in {"expected_current_day_unavailable", "expected_unavailable"}:
            return status
        if item.get("degradation_state") in {"expected_current_day_unavailable", "expected_unavailable"}:
            return item.get("degradation_state")
        if status == "rate_limited_cache":
            return "rate_limited_fallback"
        if status == "stale_cache":
            return "stale_fallback"
        if status == "rate_limited":
            return "rate_limited"
        if status == "failed":
            return "failed"
        if item.get("degradation_state"):
            return item.get("degradation_state")
        return "healthy"

    def blend_with_last_good(self, fetched):
        cache = self.load_last_good_sources()
        blended = {}
        for name, item in fetched.items():
            item = item or {}
            if item.get("ok"):
                status = item.get("status") or "fresh"
                stale = bool(item.get("stale", False))
                cache[name] = {
                    "data": item["data"],
                    "fetched_at": item["fetched_at"],
                    "target_date": self.target_date.isoformat(),
                }
                output = {
                    "ok": True,
                    "stale": stale,
                    "status": status,
                    "fetched_at": item["fetched_at"],
                    "latency_ms": item.get("latency_ms"),
                    "data": item["data"],
                }
                output.update(self.source_metadata_fields(item, name))
                output["degradation_state"] = self.source_degradation_state(status, output)
                output.setdefault("cache_status", "fresh_cache" if status == "fresh_cache" else "live")
                blended[name] = output
            else:
                # Failed! Try to load from cache, governed by this source's TTL:
                # a stale "current" observation expires fast; a stale forecast
                # can be trusted longer.
                failure_status = self.source_failure_status(item)
                ttl_minutes = self.source_cache_ttl_minutes(name)
                cached_item = cache.get(name)
                cache_age_minutes = self.cache_age_minutes(cached_item.get("fetched_at")) if cached_item else None
                cache_is_recent = (
                    cache_age_minutes is not None
                    and cache_age_minutes <= ttl_minutes
                )
                if (
                    failure_status in {"expected_current_day_unavailable", "expected_unavailable"}
                ):
                    output = {
                        "ok": False,
                        "stale": False,
                        "status": failure_status,
                        "fetched_at": item.get("fetched_at"),
                        "error": item.get("error", "Expected source unavailability"),
                        "latency_ms": item.get("latency_ms"),
                        "ttl_minutes": ttl_minutes,
                        "data": {},
                    }
                    output.update(self.source_metadata_fields(item, name))
                    output["ttl_minutes"] = ttl_minutes
                    output["degradation_state"] = self.source_degradation_state(failure_status, item)
                    output.setdefault("cache_status", "expected_unavailable")
                    output.setdefault("fallback_source", item.get("fallback_source") or "current_live_sources")
                    blended[name] = output
                    continue
                if (
                    cached_item
                    and cached_item.get("target_date") == self.target_date.isoformat()
                    and cache_is_recent
                ):
                    fallback_status = self.source_cache_fallback_status(failure_status)
                    output = {
                        "ok": True,
                        "stale": True,
                        "status": fallback_status,
                        "fetched_at": cached_item["fetched_at"],
                        "data": cached_item["data"],
                        "error": item.get("error", "Unknown error"),
                        "latency_ms": item.get("latency_ms"),
                        "cache_age_minutes": cache_age_minutes,
                        "ttl_minutes": ttl_minutes,
                    }
                    output.update(self.source_metadata_fields(item, name))
                    output["cache_age_minutes"] = cache_age_minutes
                    output["ttl_minutes"] = ttl_minutes
                    output["degradation_state"] = self.source_degradation_state(fallback_status, item)
                    output["cache_status"] = "fallback"
                    blended[name] = output
                else:
                    stale_detail = ""
                    if cached_item and cached_item.get("target_date") == self.target_date.isoformat():
                        stale_detail = (
                            f" Last good cache is {cache_age_minutes:.0f} minutes old (TTL {ttl_minutes} min)."
                            if cache_age_minutes is not None else " Last good cache age is unknown."
                        )
                    status = failure_status if failure_status == "rate_limited" else "failed"
                    output = {
                        "ok": False,
                        "stale": False,
                        "status": status,
                        "fetched_at": item.get("fetched_at"),
                        "error": f"{item.get('error', 'Unknown error')}.{stale_detail}".strip(),
                        "latency_ms": item.get("latency_ms"),
                        "ttl_minutes": ttl_minutes,
                        "data": {},
                    }
                    output.update(self.source_metadata_fields(item, name))
                    output["ttl_minutes"] = ttl_minutes
                    output["degradation_state"] = self.source_degradation_state(status, item)
                    output.setdefault("cache_status", "miss")
                    blended[name] = output
                    
        self.save_last_good_sources(cache)
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
        physical_states = {}
        physical_state_method = getattr(self, "guidance_physical_states", None)
        if callable(physical_state_method):
            try:
                physical_states = physical_state_method(blended)
            except Exception:
                physical_states = {}
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
                "source_family": item.get("source_family") or self.source_family(name),
                "http_status": item.get("http_status"),
                "retry_after_seconds": item.get("retry_after_seconds"),
                "degradation_state": item.get("degradation_state"),
                "cache_status": item.get("cache_status"),
            }
            if name in TORONTO_OFFICIAL_CANADIAN_SOURCES:
                diagnostic["official_canadian_source"] = True
                diagnostic["official_canadian_role"] = TORONTO_OFFICIAL_CANADIAN_SOURCES[name]
            physical_state = physical_states.get(name) or {}
            if physical_state:
                diagnostic["physical_validity_status"] = physical_state.get("physical_validity_status")
                diagnostic["physical_validity_floor"] = physical_state.get("observed_floor")
                diagnostic["physical_validity_gap"] = physical_state.get("floor_gap")
                diagnostic["impossible_feature_count"] = physical_state.get("impossible_feature_count")
                diagnostic["impossible_features"] = ",".join(physical_state.get("impossible_features") or [])
            if name == "marine_context":
                marine_state = active_marine_context_state(item.get("data") or {})
                if marine_state:
                    diagnostic["marine_context"] = marine_state
            diagnostics.append(diagnostic)
        return diagnostics

    def source_item_status(self, item):
        item = item or {}
        status = item.get("status")
        if status:
            return status
        if item.get("ok") and not item.get("stale"):
            return "fresh"
        if item.get("stale"):
            return "stale_cache"
        return "failed"

    def source_item_available(self, item):
        status = str(self.source_item_status(item) or "").lower()
        return (
            bool((item or {}).get("ok"))
            and not bool((item or {}).get("stale"))
            and status in {"fresh", "fresh_cache", "ok", "available"}
        )

    def toronto_official_source_health(self, sources, now=None):
        now = now or datetime.now(self.spec.tz)
        if getattr(self, "market_id", None) != "toronto":
            return {
                "schema_version": "toronto_official_source_health_v0.1",
                "market_id": getattr(self, "market_id", None),
                "status": "NOT_APPLICABLE",
                "late_day_lockin_window": False,
                "sources": [],
            }
        late_day = now.astimezone(self.spec.tz).hour >= TORONTO_OFFICIAL_SOURCE_LATE_DAY_HOUR
        rows = []
        for source, role in TORONTO_OFFICIAL_CANADIAN_SOURCES.items():
            item = (sources or {}).get(source) or {}
            available = self.source_item_available(item)
            rows.append({
                "source": source,
                "role": role,
                "available": available,
                "ok": bool(item.get("ok")),
                "stale": bool(item.get("stale")),
                "status": self.source_item_status(item),
                "fetched_at": item.get("fetched_at"),
                "error": item.get("error"),
            })
        missing = [row["source"] for row in rows if not row["available"]]
        status = "WARN" if late_day and missing else "PASS"
        return {
            "schema_version": "toronto_official_source_health_v0.1",
            "market_id": "toronto",
            "generated_at": now.isoformat(),
            "late_day_lockin_window": late_day,
            "late_day_warning_hour": TORONTO_OFFICIAL_SOURCE_LATE_DAY_HOUR,
            "status": status,
            "official_sources_available": len(rows) - len(missing),
            "official_sources_missing": len(missing),
            "missing_sources": missing,
            "sources": rows,
            "message": (
                "Official Canadian source degraded during late-day lock-in window."
                if status == "WARN"
                else "Official Canadian source gate clear."
            ),
        }

    def fetch_wu_history(self):
        url = (
            "https://api.weather.com/v1/location/"
            f"{self.spec.wu_history_id}/observations/historical.json"
        )
        params = {
            "apiKey": WEATHER_COM_KEY,
            "units": self.spec.wu_units,
            "startDate": self.target_date_str,
            "endDate": self.target_date_str,
        }
        try:
            payload = self.get_json(url, params)
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            today = datetime.now(self.spec.tz).date()
            if status_code == 400 and self.target_date == today:
                raise SourceExpectedUnavailable(
                    (
                        "WU history is expected to be unavailable for the current target date; "
                        "fall back to wu_current/METAR/official observations."
                    ),
                    status="expected_current_day_unavailable",
                    source_family="wu_history",
                    http_status=400,
                    degradation_state="expected_current_day_unavailable",
                    cache_status="expected_unavailable",
                    fallback_source="wu_current,metar,eccc_swob,current_high_ledger",
                ) from exc
            raise

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
        missing_files = []
        if files:
            # Fetch the per-observation XML files concurrently — there can be ~50
            # of them and sequential GETs dominated this source's latency. map()
            # preserves file order, so `latest = rows[-1]` stays correct.
            def _fetch_one(filename):
                def _once():
                    resp = requests.get(f"{base_url}{filename}", timeout=self.timeout)
                    resp.raise_for_status()
                    return resp.text
                try:
                    return self.parse_swob_xml(request_with_retries(_once)), None
                except requests.HTTPError as exc:
                    if self.http_status(exc) == 404:
                        return None, filename
                    raise

            with ThreadPoolExecutor(max_workers=min(8, len(files))) as executor:
                parsed = executor.map(_fetch_one, files)
                for row, missing_file in parsed:
                    if missing_file:
                        missing_files.append(missing_file)
                        continue
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
            "skipped_missing_file_count": len(missing_files),
            "skipped_missing_files": missing_files[-5:],
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

    def fetch_open_meteo_air_quality(self):
        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        payload = self.get_json(url, {
            "latitude": self.spec.lat,
            "longitude": self.spec.lon,
            "hourly": ",".join(OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS),
            "timezone": self.spec.timezone,
            "forecast_days": 2,
        })
        hourly = payload.get("hourly", {}) or {}
        rows = []
        day_rows = []
        now = datetime.now(self.spec.tz).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date:
                continue
            local_dt = dt.replace(tzinfo=self.spec.tz)
            row = {
                "time": dt.strftime("%H:%M"),
                "valid_time": local_dt.isoformat(),
            }
            for field in OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS:
                row[field] = self.to_number(self.array_get(hourly, field, index))
            day_rows.append(row)
            if dt < now:
                continue
            rows.append(row)
        return {
            "url": url,
            "rows": rows[:12],
            "day_rows": day_rows,
            "hourly_fields": list(OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS),
            "provenance": {
                "provider": "open_meteo_air_quality",
                "upstream": "CAMS auto domain via Open-Meteo Air Quality API",
            },
            "raw_payload": payload,
        }

    def fetch_open_meteo_global_models(self):
        url = "https://api.open-meteo.com/v1/forecast"
        payload = self.get_json(url, {
            "latitude": self.spec.lat,
            "longitude": self.spec.lon,
            "hourly": "temperature_2m",
            "temperature_unit": self.spec.om_temperature_unit,
            "timezone": self.spec.timezone,
            "forecast_days": 2,
            "models": ",".join(OPEN_METEO_GLOBAL_MODEL_MEMBERS),
        })
        hourly = payload.get("hourly", {}) or {}
        rows = []
        day_rows = []
        model_day_temps = {model: [] for model in OPEN_METEO_GLOBAL_MODEL_MEMBERS}
        now = datetime.now(self.spec.tz).replace(tzinfo=None)
        for index, raw_time in enumerate(hourly.get("time", []) or []):
            dt = datetime.fromisoformat(raw_time)
            if dt.date() != self.target_date:
                continue
            model_payloads = {}
            model_temps = []
            for model in OPEN_METEO_GLOBAL_MODEL_MEMBERS:
                value = self.to_number(self.array_get(hourly, f"temperature_2m_{model}", index))
                values = {"temp_native": value, "temp_c": value}
                if value is not None:
                    model_temps.append(value)
                    model_day_temps[model].append(value)
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
            "model_members": list(OPEN_METEO_GLOBAL_MODEL_MEMBERS),
            "model_run_age_hours": None,
            "model_run_age_status": "not_exposed_by_open_meteo_forecast",
            "run_to_run_high_change": None,
            "run_to_run_change_status": "requires_previous_run_archive",
            "historical_archive_available": False,
            "live_only_fields": [
                "open_meteo_global_models_high_spread",
                "open_meteo_ecmwf_ifs_high_delta",
                "open_meteo_ecmwf_aifs_high_delta",
                "open_meteo_ncep_aigfs_high_delta",
                "open_meteo_gfs_graphcast_high_delta",
                "open_meteo_ecmwf_ifs_aifs_disagreement",
                "open_meteo_global_models_next_3h_spread",
                "open_meteo_global_models_run_to_run_high_change",
            ],
            "generation_time_ms": payload.get("generationtime_ms"),
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

    def fetch_nbm_probabilistic_tmax(self):
        """National Blend of Models NBP station Tmax percentile guidance."""
        if ":US" not in str(self.spec.wu_history_id):
            return {
                "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
                "available": False,
                "reason": "NBM probabilistic Tmax guidance is US-only.",
                "station_id": self.spec.icao,
                "target_date": self.target_date.isoformat(),
                "percentiles": {},
            }
        fetched_at = datetime.now(timezone.utc).isoformat()
        tried_urls = []
        last_payload = None
        for run_time in nbp_cycle_candidates(datetime.now(timezone.utc), hours_back=24):
            url = nbp_text_url(run_time)
            tried_urls.append(url)
            try:
                text = self.get_text(url)
            except requests.HTTPError as exc:
                if self.http_status(exc) in {403, 404}:
                    continue
                raise
            payload = parse_nbp_station_tmax(
                text,
                self.spec.icao,
                self.target_date,
                source_url=url,
                fetched_at=fetched_at,
            )
            payload["tried_urls"] = list(tried_urls)
            if payload.get("available"):
                return payload
            last_payload = payload
        if last_payload is not None:
            last_payload["tried_urls"] = list(tried_urls)
            return last_payload
        return {
            "schema_version": NBM_PROB_TMAX_SCHEMA_VERSION,
            "available": False,
            "reason": "nbp_text_unavailable",
            "station_id": self.spec.icao,
            "target_date": self.target_date.isoformat(),
            "percentiles": {},
            "fetched_at": fetched_at,
            "tried_urls": tried_urls,
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

    def get_text(self, url, headers=None):
        def _once():
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.text
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
