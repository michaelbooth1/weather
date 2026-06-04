"""Toronto high-temperature market model.

The implementation is split across concern-specific mixins (model_*.py);
``TorontoHighTempModel`` composes them. Constants live in model_constants and
are re-exported here so existing ``from toronto_model import ...`` callers keep
working unchanged.
"""
import json
from datetime import datetime
from pathlib import Path

from market_config import config_for_date, config_from_event
from market_registry import DEFAULT_MARKET_ID
# Re-exported for backward compatibility: callers historically imported these
# from toronto_model when it owned the wu_history import.
from wu_history import DEFAULT_DATA_ROOT, analyze_daily_summary  # noqa: F401
from model_constants import (
    DEFAULT_MARKET_CONFIG,
    TORONTO_TZ,
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
from model_base import ModelUtilsMixin
from model_sources import SourceFetchMixin
from model_climatology import ClimatologyMixin
from model_distribution import DistributionMixin
from model_features import FeatureModelMixin
from model_presentation import PresentationMixin
from forecast_error_model import load_forecast_error_model
from probability_calibration import load_probability_calibration
from settlement_lag_model import load_settlement_lag_model


class TorontoHighTempModel(
    SourceFetchMixin,
    ClimatologyMixin,
    DistributionMixin,
    FeatureModelMixin,
    PresentationMixin,
    ModelUtilsMixin,
):
    _historical_target_cache = {}

    def __init__(self, timeout=8, target_date=None, market_id=DEFAULT_MARKET_ID):
        self.timeout = timeout
        self.market_id = market_id
        self.set_target_date(target_date or TARGET_DATE)
        self.calibrated_weights = self.load_calibrated_weights()
        self.forecast_error_model = self.load_forecast_error_model()
        self.settlement_lag_model = self.load_settlement_lag_model()
        self.probability_calibration = self.load_probability_calibration()
        self._last_probability_calibration_context = {}
        self.active_model_kind = "empirical"
        self._feature_model_hgb = _UNLOADED
        self._feature_model_coefs = _UNLOADED
        self._late_day_model_coefs = _UNLOADED

    def set_target_date(self, target_date):
        self.config = config_for_date(target_date, getattr(self, "market_id", DEFAULT_MARKET_ID))
        self.spec = self.config.spec
        self.target_date = self.config.target_date
        self.target_date_str = self.config.target_date_str
        return self

    def sync_target_date_from_event(self, event):
        config = config_from_event(event, fallback_date=self.target_date)
        if config.market_id != self.market_id or config.target_date != self.target_date:
            self.market_id = config.market_id
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

    def load_probability_calibration(self):
        path = Path(__file__).parent / "probability_calibration.json"
        return load_probability_calibration(path)

    def load_forecast_error_model(self):
        path = Path(__file__).parent / "forecast_error_model.json"
        return load_forecast_error_model(path)

    def load_settlement_lag_model(self):
        path = Path(__file__).parent / "settlement_lag_model.json"
        return load_settlement_lag_model(path)

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
        model_version = self.get_model_version_string()
        feature_vector = self.live_feature_record(
            sources,
            cutoff_hour,
            captured_at=now_tz,
            model_version=model_version,
        )
        # Compute analogs once at the effective cutoff and reuse them in the deep
        # dive, so both panels agree and the heaviest lookup runs a single time.
        analog_search = self.find_analog_days(sources, cutoff_hour, now_tz, limit=5)
        return {
            "sources": sources,
            # The exact timestamp this build used. Persisted with the captured
            # sources so the replay corpus can re-run estimate_distribution with
            # the identical `now` the model saw (the hour drives the cutoff, the
            # late-day lock-in, and every time-weighted signal).
            "built_at": now_tz.isoformat(),
            "distribution": distribution,
            "distribution_components": getattr(self, "_last_distribution_components", {}),
            "model_rows": model_rows,
            "source_rows": self.source_rows(sources),
            "forecast_rows": self.forecast_rows(sources),
            "deep_dive_rows": self.deep_dive_rows(sources, distribution, analog_search, now=now_tz),
            "notes": self.model_notes(sources),
            "top_temp": top_temp,
            "model_version": model_version,
            "feature_vector": feature_vector,
            "boundary_transitions": self.get_bucket_transitions(sources, now_tz),
            "late_day_risk": self.predict_late_day_continuation(sources, cutoff_hour, now_tz),
            "analog_search": analog_search,
            "model_explanation": self.get_model_explanation(sources, distribution),
        }

    def get_model_version_string(self):
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            return MODEL_VERSION_HGB
        if kind == "lr":
            return MODEL_VERSION_LR
        return MODEL_VERSION_EMPIRICAL
