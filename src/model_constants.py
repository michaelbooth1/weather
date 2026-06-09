"""Shared constants for the Toronto high-temperature model.

Split out of toronto_model.py so the concern-specific mixin modules
(model_*.py) can import these without a circular dependency back to the
composed ``TorontoHighTempModel`` class.
"""
import os
from zoneinfo import ZoneInfo

from market_config import config_for_date


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
INTRADAY_CUTOFF_HOURS = (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20)
LIVE_CACHE_MAX_AGE_MINUTES = 90

# Model-version labels — the single source of truth shared with snapshot_tracker.
# v0.5.0: multi-source forecast fallback (resolve_forecast_high) + forecast pull
# (apply_forecast_pull) — the morning forecast-trust upgrade.
# v0.5.1: resolution-aware late-day collapse — stronger/earlier lock-in
# (LATE_LOCKIN_FULL_HOUR 20->17, HEDGE 0.20->0.05) + the overconfidence
# calibration tapers to identity as the high locks in (resolution_weight), so
# the evening distribution concentrates onto the observed high instead of
# hedging the buckets it can no longer reach.
# v0.5.2: reverted v0.5.1's wu_current->wu_history mock-row injection. It
# backdated live readings to the top of the hour, advanced the effective
# cutoff past what WU history had printed (the v0.4.9 invariant), and masked
# live wind fields. wu_history rows are settlement-source evidence again;
# the cutoff-hour grid stays at the full 7-20 range.
ML_MODEL_VERSION = "v0.5.2"
MODEL_VERSION_HGB = f"{ML_MODEL_VERSION} HGBC feature-based ML model"
MODEL_VERSION_LR = f"{ML_MODEL_VERSION} LogisticRegression feature-based ML model"
MODEL_VERSION_EMPIRICAL = "v0.3.1 empirical lookup baseline"

# Sentinel so memoized loaders can cache a None result (missing/failed file)
# without re-reading from disk on every build.
_UNLOADED = object()
