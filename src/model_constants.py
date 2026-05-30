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
