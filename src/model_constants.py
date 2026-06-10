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
# v0.5.3: the canonical forecast feature (resolve_forecast_high) is now the
# MEDIAN of available forecast sources instead of Open-Meteo-first. Ablation
# replays (data/backtest/replay_ablation_report.md) measured OM-first at ~zero
# net value with fat-tailed bust days; the median is robust to one stale
# source. Training is unchanged by definition (the historical archive has one
# source, whose median is itself), so artifacts did not need retraining.
# v0.5.4: the current/METAR observed floor is no longer near-hard (0.001
# hedge). It now uses the same learned catch-up sizing as the SWOB floor
# (settlement_lag_model, hedge clamped to [0.30, 0.80]); WU history is the
# only hard floor. Stage/ablation analysis measured the near-hard floor
# net-negative for Toronto, and Toronto's measured wu_current catch-up is
# only ~41% -- a 0.001 hedge priced it like settlement proof.
# v0.5.6: learned late-day lock-in floor -- the lag artifact's measured WU
# revision-up curve (P(final > printed high | hour): 91.9% at 10:00 -> 0.3%
# at 20:00) floors the lock-in strength as 1 - rate from 17:00 once the high
# has stood 90+ minutes. Covers the evening plateau (current == high) where
# the past-peak heuristic stayed at 0 on 2026-06-09 and the model held 20%+
# above the high against a learned ~2-5% revision rate.
# v0.5.5: forecast falsification bench -- a source that still claims >=1C
# above a WU high that has stood unimproved 90+ minutes (past 13:00) loses
# its forecast FLOOR vote (a falsified forecast must not prop up the bottom).
# The pull keeps every source: it is a two-way uncertainty blend, and benching
# it was measured to backfire (it had been SOFTENING the over-sharp model on
# the 2026-06-09 bust day). Serving-side only; the trained HGB forecast
# feature is untouched. The replay regate also confirmed the v0.5.1
# FORECAST_AGREEMENT_SPREAD widening (5.0) beats reverting to 3.0.
ML_MODEL_VERSION = "v0.5.6"
MODEL_VERSION_HGB = f"{ML_MODEL_VERSION} HGBC feature-based ML model"
MODEL_VERSION_LR = f"{ML_MODEL_VERSION} LogisticRegression feature-based ML model"
MODEL_VERSION_EMPIRICAL = "v0.3.1 empirical lookup baseline"

# Sentinel so memoized loaders can cache a None result (missing/failed file)
# without re-reading from disk on every build.
_UNLOADED = object()
