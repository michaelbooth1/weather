"""Toronto high-temperature market model.

The implementation is split across concern-specific mixins (model_*.py);
``TorontoHighTempModel`` composes them. Constants live in model_constants and
are re-exported here so existing ``from toronto_model import ...`` callers keep
working unchanged.

Ownership note: keep serving composition and legacy re-exports here. New
serving-time calibration/runtime helpers belong in
``weather.model.calibration_runtime`` or concern-specific model modules.
"""
import json
import logging
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from weather.artifacts import resolve_artifact_path
from weather.market.market_config import config_for_date, config_from_event
from weather.market.market_registry import DEFAULT_MARKET_ID
# Re-exported for backward compatibility: callers historically imported these
# from toronto_model when it owned the wu_history import.
from weather.sources.wu_history import DEFAULT_DATA_ROOT, analyze_daily_summary  # noqa: F401
from weather.model.model_constants import (
    DEFAULT_MARKET_CONFIG,
    TORONTO_TZ,
    TARGET_DATE,
    TARGET_DATE_STR,
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
from weather.model.model_base import ModelUtilsMixin
from weather.model.model_contracts import ModelBuildResult, SourceBundle
from weather.model.model_sources import SourceFetchMixin
from weather.model.model_climatology import ClimatologyMixin
from weather.model.model_distribution import DistributionMixin
from weather.model.model_features import FeatureModelMixin
from weather.model.model_presentation import PresentationMixin
from weather.model.calibration_runtime import (
    load_afternoon_residual_centering,
    load_family_secondary_manifest,
    load_forecast_error_model,
    load_probability_calibration,
    load_settlement_lag_model,
)
from weather.release_contract import BASE_MODEL_MARKET_COMPONENT_KINDS
from weather.release_serving import (
    STATUS_BOUND,
    STATUS_RESEARCH_UNBOUND,
    ReleaseServingBindingError,
    get_process_active_serving_bundle,
    materialize_verified_base_model_market,
)

logger = logging.getLogger(__name__)


class TorontoHighTempModel(
    SourceFetchMixin,
    ClimatologyMixin,
    DistributionMixin,
    FeatureModelMixin,
    PresentationMixin,
    ModelUtilsMixin,
):
    _historical_target_cache = OrderedDict()
    _historical_target_cache_max_entries = 128

    def __init__(
        self,
        timeout=8,
        target_date=None,
        market_id=DEFAULT_MARKET_ID,
        serving_bundle=None,
        source_cache_path=None,
        source_cache_names=None,
        source_cache_max_bytes=None,
    ):
        self.timeout = timeout
        self.market_id = market_id
        self._source_cache_path = (
            Path(source_cache_path) if source_cache_path is not None else None
        )
        self._source_cache_names = (
            frozenset(str(name) for name in source_cache_names)
            if source_cache_names is not None
            else None
        )
        self._source_cache_max_bytes = (
            max(1, int(source_cache_max_bytes))
            if source_cache_max_bytes is not None
            else None
        )
        self.serving_bundle = serving_bundle or get_process_active_serving_bundle()
        if self.serving_bundle.status not in {STATUS_BOUND, STATUS_RESEARCH_UNBOUND}:
            raise ReleaseServingBindingError(
                "base-model construction blocked by active-release binding: "
                f"{self.serving_bundle.status}: {self.serving_bundle.reason}"
            )
        if self.serving_bundle.status == STATUS_BOUND and not self.serving_bundle.base_model_bound:
            raise ReleaseServingBindingError(
                "active release is bound but its complete base-model graph is not"
            )
        self.set_target_date(target_date or TARGET_DATE)
        self._last_family_secondary_gate = {}
        self._last_probability_calibration_context = {}
        self.active_model_kind = "empirical"
        self._bound_base_model_components = None
        self._bound_base_model_shared_components = None
        self._configure_base_model_components()

    def _configure_base_model_components(self):
        if self.serving_bundle.status == STATUS_BOUND:
            self._bind_release_base_model_components()
            return
        self._bound_base_model_components = None
        self._bound_base_model_shared_components = None
        self._feature_model_hgb = _UNLOADED
        self._feature_model_coefs = _UNLOADED
        self._late_day_model_coefs = _UNLOADED
        self.calibrated_weights = self.load_calibrated_weights()
        self.forecast_error_model = self.load_forecast_error_model()
        self.afternoon_residual_centering = self.load_afternoon_residual_centering()
        self.settlement_lag_model = self.load_settlement_lag_model()
        self.probability_calibration = self.load_probability_calibration()
        self.family_secondary_artifacts = self.load_family_secondary_artifacts()

    def _bind_release_base_model_components(self):
        route = self.serving_bundle.route.get("markets", {}).get(self.market_id)
        components = materialize_verified_base_model_market(
            self.serving_bundle,
            self.market_id,
        )
        shared = self.serving_bundle.base_model_shared_artifacts
        locations = self.serving_bundle.json_artifacts.get("locations_config") or {}
        location = next(
            (
                row
                for row in locations.get("locations") or []
                if isinstance(row, Mapping) and row.get("id") == self.market_id
            ),
            None,
        )
        if (
            not isinstance(route, Mapping)
            or route.get("decision") not in {"promote", "shadow"}
            or route.get("base_model_market_id") != self.market_id
            or not isinstance(components, Mapping)
            or set(components) != set(BASE_MODEL_MARKET_COMPONENT_KINDS)
            or not isinstance(shared, Mapping)
            or set(shared) != {
                "afternoon_residual_centering",
                "family_secondary_artifacts",
            }
            or not isinstance(location, Mapping)
            or self.spec.id != self.market_id
        ):
            raise ReleaseServingBindingError(
                f"active release has no complete exact base-model route for {self.market_id!r}"
            )
        settlement = location.get("settlement") or {}
        polymarket = location.get("polymarket") or {}
        if (
            location.get("market_unit") != self.spec.unit
            or settlement.get("unit") != self.spec.unit
            or polymarket.get("event_slug_prefix") != self.spec.slug_prefix
        ):
            raise ReleaseServingBindingError(
                f"active release location semantics disagree with runtime code for {self.market_id!r}"
            )
        self._bound_base_model_components = components
        self._bound_base_model_shared_components = shared
        self._feature_model_hgb = components["feature_hgb"]
        self._feature_model_coefs = components["feature_lr_coefficients"]
        self._late_day_model_coefs = components["late_day_lr_coefficients"]
        self.calibrated_weights = components["calibrated_weights"]
        self.forecast_error_model = components["forecast_error_model"]
        self.settlement_lag_model = components["settlement_lag_model"]
        self.probability_calibration = components["probability_calibration"]
        self.afternoon_residual_centering = shared["afternoon_residual_centering"]
        self.family_secondary_artifacts = shared["family_secondary_artifacts"]

    def _assert_global_base_path_allowed(self, component_name):
        if self.serving_bundle.pointer_present:
            raise ReleaseServingBindingError(
                f"active release forbids global base-model fallback: {component_name}"
            )

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
            self._configure_base_model_components()

    def load_calibrated_weights(self):
        if self._bound_base_model_components is not None:
            return self._bound_base_model_components["calibrated_weights"]
        self._assert_global_base_path_allowed("calibrated_weights")
        path = resolve_artifact_path(f"calibrated_weights{self.spec.artifact_suffix}.json")
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Error loading calibrated weights: %s", e)
        return None

    def load_probability_calibration(self):
        if self._bound_base_model_components is not None:
            return self._bound_base_model_components["probability_calibration"]
        self._assert_global_base_path_allowed("probability_calibration")
        path = resolve_artifact_path(f"probability_calibration{self.spec.artifact_suffix}.json")
        return load_probability_calibration(path)

    def load_forecast_error_model(self):
        if self._bound_base_model_components is not None:
            return self._bound_base_model_components["forecast_error_model"]
        self._assert_global_base_path_allowed("forecast_error_model")
        path = resolve_artifact_path(f"forecast_error_model{self.spec.artifact_suffix}.json")
        return load_forecast_error_model(path)

    def load_afternoon_residual_centering(self):
        if self._bound_base_model_shared_components is not None:
            return self._bound_base_model_shared_components["afternoon_residual_centering"]
        self._assert_global_base_path_allowed("afternoon_residual_centering")
        path = resolve_artifact_path("afternoon_residual_centering.json")
        return load_afternoon_residual_centering(path)

    def load_settlement_lag_model(self):
        if self._bound_base_model_components is not None:
            return self._bound_base_model_components["settlement_lag_model"]
        self._assert_global_base_path_allowed("settlement_lag_model")
        path = resolve_artifact_path(f"settlement_lag_model{self.spec.artifact_suffix}.json")
        return load_settlement_lag_model(path)

    def load_family_secondary_artifacts(self):
        if self._bound_base_model_shared_components is not None:
            return self._bound_base_model_shared_components["family_secondary_artifacts"]
        self._assert_global_base_path_allowed("family_secondary_artifacts")
        path = resolve_artifact_path("f_family_secondary_artifacts.json")
        return load_family_secondary_manifest(path)

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
        cls._historical_target_cache = OrderedDict()

    def build(self, event, historical_sources=None, live_sources=None, now=None):
        self.sync_target_date_from_event(event)
        if historical_sources is None and live_sources is None:
            source_bundle = SourceBundle.from_combined(self.fetch_sources())
        else:
            source_bundle = SourceBundle.from_groups(
                historical_sources=historical_sources,
                live_sources=live_sources,
            )
        sources = source_bundle.sources
        # One timestamp for the whole build so every panel (distribution, cutoff,
        # analogs, transitions, late-day) agrees, and so callers can backtest by
        # passing a historical `now`.
        now_tz = now or datetime.now(self.spec.tz)
        distribution_result = self.estimate_distribution_result(sources, now=now_tz)
        distribution = distribution_result.distribution
        model_rows = self.model_market_rows(event, distribution, distribution_result=distribution_result)
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
        return ModelBuildResult(
            source_bundle=source_bundle,
            built_at=now_tz.isoformat(),
            distribution_result=distribution_result,
            model_rows=model_rows,
            source_rows=self.source_rows(sources),
            # Structured per-source freshness/failure status (item 17), so the
            # dashboard/loop can surface partial live-source failures and stale
            # caches per their own TTL rather than as one undifferentiated blob.
            source_diagnostics=self.source_diagnostics(sources),
            forecast_rows=self.forecast_rows(sources),
            deep_dive_rows=self.deep_dive_rows(sources, distribution, analog_search, now=now_tz),
            notes=self.model_notes(sources, distribution_result=distribution_result),
            top_temp=top_temp,
            model_version=model_version,
            feature_vector=feature_vector,
            boundary_transitions=self.get_bucket_transitions(sources, now_tz),
            late_day_risk=self.predict_late_day_continuation(sources, cutoff_hour, now_tz),
            source_health=self.toronto_official_source_health(sources, now=now_tz),
            analog_search=analog_search,
            model_explanation=self.get_model_explanation(
                sources,
                distribution,
                distribution_result=distribution_result,
            ),
        ).as_dict()

    def get_model_version_string(self):
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            return MODEL_VERSION_HGB
        if kind == "lr":
            return MODEL_VERSION_LR
        return MODEL_VERSION_EMPIRICAL
