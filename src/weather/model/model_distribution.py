import math
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
import re
from datetime import datetime, timedelta, timezone
from weather.model.model_constants import (
    DEFAULT_MARKET_CONFIG,
    TARGET_DATE,
    TARGET_DATE_STR,
    CYYZ_HISTORY_ID,
    CYYZ_ICAO,
    PEARSON_LAT,
    PEARSON_LON,
    INTRADAY_CUTOFF_HOURS,
    LIVE_CACHE_MAX_AGE_MINUTES,
    ML_MODEL_VERSION,
    MODEL_VERSION_HGB,
    MODEL_VERSION_LR,
    MODEL_VERSION_EMPIRICAL,
    _UNLOADED,
)
from weather.model.calibration_runtime import (
    apply_afternoon_residual_centering,
    apply_exact_distribution_calibration,
)
from weather.model.model_contracts import DistributionResult
from weather.model.feature_store import current_max_trust_features, plausible_native_temperature

from weather.model.model_distribution_constants import (
    BUCKET_TRANSITION_BLEND_MAX,
    BUCKET_TRANSITION_MIN_SAMPLE,
    COMPONENT_SCHEMA_VERSION,
    FALSIFICATION_EARLIEST_HOUR,
    FALSIFICATION_MARGIN,
    FALSIFICATION_STAND_MINUTES,
    FORECAST_AGREEMENT_SPREAD,
    FORECAST_CLUSTER_MAX_WEIGHT,
    FORECAST_CLUSTER_SOURCE_WEIGHT_STEP,
    FORECAST_FLOOR_BASE,
    FORECAST_FLOOR_MARGIN,
    FORECAST_FLOOR_MIN_SOURCES,
    FORECAST_PULL_BLEND_MAX,
    FORECAST_PULL_END_HOUR,
    FORECAST_PULL_START_HOUR,
    FORECAST_SOFT_SIGMA,
    HIGH_HAS_STOOD_END_HOUR,
    HIGH_HAS_STOOD_FORECAST_MARGIN,
    HIGH_HAS_STOOD_MIN_FORECAST_SOURCES,
    HIGH_HAS_STOOD_MIN_MINUTES,
    HIGH_HAS_STOOD_ROLLOVER_MARGIN,
    HIGH_HAS_STOOD_START_HOUR,
    LATE_DAY_CONTINUATION_BLEND_15H,
    LATE_DAY_CONTINUATION_BLEND_17H,
    LATE_DAY_LOCKIN_ANCHOR_VERSION,
    LATE_LOCKIN_BASE,
    LATE_LOCKIN_FULL_HOUR,
    LATE_LOCKIN_HEDGE,
    LATE_LOCKIN_PEAK_DROP,
    LATE_LOCKIN_START_HOUR,
    LEARNED_LOCKIN_STAND_MINUTES,
    LEARNED_LOCKIN_START_HOUR,
    LIVE_FLOOR_BASE,
    LIVE_FLOOR_HEDGE,
    LIVE_FLOOR_HEDGE_MAX,
    LIVE_FLOOR_HEDGE_MIN,
    METAR_LIVE_SIGNAL_MAX_WEIGHT,
    METAR_LIVE_SIGNAL_REACHED_BASELINE,
    METAR_LIVE_SIGNAL_SIGMA,
    RAMP_WARM_TAIL_ANCHOR_MARGIN,
    RAMP_WARM_TAIL_DECAY,
    RAMP_WARM_TAIL_DISAGREEMENT,
    RAMP_WARM_TAIL_END_HOUR,
    RAMP_WARM_TAIL_SOURCE_CAP_MARGIN,
    RAMP_WARM_TAIL_START_HOUR,
    VALIDATED_WU_MAX_HARD_FLOOR_MARKETS,
    WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL,
)


# METAR observation day/time group, e.g. "KAUS 250453Z".
METAR_OBSERVATION_GROUP_RE = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")

EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS = frozenset({
    # Item 181 settled stage attribution: empirical fallback forecast-shape
    # must be non-regressing on both Brier and log-loss before serving applies it.
    "houston",
    "los-angeles",
    "miami",
    "nyc",
    "seattle",
    "toronto",
})


@dataclass
class DistributionPipelineState:
    """Named probability snapshots and metadata for one distribution run."""

    schema_version: str = COMPONENT_SCHEMA_VERSION
    components: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def snapshot(self, name, distribution):
        self.components[name] = dict(distribution or {})
        return self.components[name]

    def snapshot_normalized(self, name, distribution, normalizer):
        return self.snapshot(name, normalizer(distribution or {}))

    def update_metadata(self, **metadata):
        self.metadata.update(metadata)

    def payload(self):
        return {
            "schema_version": self.schema_version,
            **self.metadata,
            "components": self.components,
        }



from weather.model.model_distribution_signals import DistributionSignalMixin
class DistributionMixin(DistributionSignalMixin):
    """The probability engine: priors, blending, live signals, caps, weighting."""

    def estimate_distribution_result(self, sources, now=None):
        return self._estimate_distribution_result(sources, now=now)

    def estimate_distribution(self, sources, now=None):
        return self.estimate_distribution_result(sources, now=now).distribution

    def _set_distribution_result_compatibility(self, result, pipeline_state=None):
        """Populate legacy scratch fields from the explicit result object."""
        self._last_distribution_result = result
        self._last_distribution_components = deepcopy(dict(result.component_payload or {}))
        self._last_probability_calibration_context = deepcopy(dict(result.calibration_context or {}))
        self._last_family_secondary_gate = deepcopy(dict(result.family_secondary_gate or {}))
        self.active_model_kind = result.active_model_kind or "empirical"
        if pipeline_state is not None:
            self._last_distribution_pipeline_state = pipeline_state
        return result

    def _estimate_distribution_result(self, sources, now=None):
        self._last_distribution_components = {}
        self._last_distribution_pipeline_state = None
        self._last_probability_calibration_context = {}
        self._last_family_secondary_gate = {}
        self._last_weak_input_family_preflight = {}
        self._last_distribution_result = DistributionResult()
        self.active_model_kind = "empirical"
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        metar = self.source_data(sources, "metar")
        station_method = getattr(self, "station_observation_data", None)
        station = (
            station_method(sources)
            if callable(station_method)
            else self.source_data(sources, "station_observations")
        )
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")
        nws_hourly = self.source_data(sources, "nws_hourly")
        global_ensemble = self.source_data(sources, "global_ensemble")

        now = now or datetime.now(self.spec.tz)
        station_temp = self.row_temp_native(station)
        station_max = self.row_max_since_7am_native(station)
        current_temp = self.row_temp_native(current)
        if current_temp is None:
            current_temp = station_temp
        current_max = self.row_max_since_7am_native(current)
        if current_max is None:
            current_max = station_max
        cutoff_hour = self.effective_intraday_cutoff_hour(
            now,
            history.get("rows") or [],
        )
        observed_high_context = self.effective_observed_high_context(
            history,
            current,
            station,
            cutoff_hour,
        )
        history_max = observed_high_context["history_high"]
        effective_observed_high = observed_high_context["effective_observed_high"]
        effective_observed_floor_high = observed_high_context[
            "effective_observed_floor_high"
        ]
        current_max_features = current_max_trust_features(
            current_max,
            history_max=history_max,
            current_temp=current_temp,
            cutoff_hour=cutoff_hour,
            unit=self.spec.display_unit,
        )
        trusted_current_max = current_max_features.get("trusted_current_max")
        support_only_current_max = current_max_features.get("support_only_current_max")
        eccc_max = self.row_same_day_max_native(eccc)
        metar_temp = self.row_temp_native(metar)
        current_max_boundary = self.current_max_boundary_context(
            current_max=current_max,
            support_only_current_max=support_only_current_max,
            history_max=history_max,
            official_observations={
                "eccc_swob": eccc_max,
                "metar": metar_temp,
                "station_observations": station_max,
            },
            current_max_disposition=current_max_features.get("current_max_disposition"),
            current_max_state=current_max_features.get("current_max_state"),
            hour=now.hour,
        )
        weather_forecast_max = self.forecast_day_max(weather_forecast)
        open_meteo_max = self.forecast_day_max(open_meteo)
        nws_forecast_max = self.forecast_day_max(nws_hourly)
        global_ensemble_max = self.forecast_day_max(global_ensemble)
        eccc_forecast_high = self.row_forecast_high_native(eccc_city)
        guidance_floor = self.guidance_physical_floor(
            high_so_far=history_max,
            current_temp=current_temp,
            live_reading=current_temp,
            current_max=trusted_current_max,
            sources=sources,
        )
        forecast_ensemble = self.forecast_ensemble_metrics(
            open_meteo,
            weather_forecast,
            eccc_city,
            nws_hourly=nws_hourly,
            global_ensemble=global_ensemble,
            observed_floor_native=guidance_floor,
        )
        guidance_states = self.guidance_physical_states(
            sources,
            observed_floor_native=guidance_floor,
        )

        def forecast_signal(source, value):
            state = guidance_states.get(source) or {}
            if str(state.get("physical_validity_status") or "") == "fresh_but_impossible":
                return None
            return self.robust_forecast_signal_value(value, forecast_ensemble)

        weather_forecast_signal = forecast_signal("weather_forecast", weather_forecast_max)
        open_meteo_signal = forecast_signal("open_meteo", open_meteo_max)
        nws_forecast_signal = forecast_signal("nws_hourly", nws_forecast_max)
        global_ensemble_signal = forecast_signal("global_ensemble", global_ensemble_max)
        eccc_forecast_signal = forecast_signal("eccc_citypage", eccc_forecast_high)
        forecast_signal_values = {
            "weather_forecast": weather_forecast_signal,
            "open_meteo": open_meteo_signal,
            "nws_hourly": nws_forecast_signal,
            "global_ensemble": global_ensemble_signal,
            "eccc_citypage": eccc_forecast_signal,
        }
        forecast_values = [
            weather_forecast_signal,
            open_meteo_signal,
            nws_forecast_signal,
            global_ensemble_signal,
            eccc_forecast_signal,
        ]

        local_analysis = local_history.get("analysis") or {}
        probabilities = local_analysis.get("bucket_probabilities") or {}
        if local_history.get("available") and local_analysis.get("target_window_count", 0) >= 30:
            scores = {
                int(bucket): float(probability)
                for bucket, probability in probabilities.items()
            }
        else:
            scores = self.climatology_fallback_prior()

        live_values = [
            history_max,
            current_temp,
            trusted_current_max,
            self.round_half_up(eccc_max) if eccc_max is not None else None,
            metar_temp,
            weather_forecast_signal,
            self.round_half_up(open_meteo_signal) if open_meteo_signal is not None else None,
            self.round_half_up(nws_forecast_signal) if nws_forecast_signal is not None else None,
            self.round_half_up(global_ensemble_signal) if global_ensemble_signal is not None else None,
            eccc_forecast_signal,
        ]
        observed_bucket = self.round_half_up(history_max)
        effective_observed_bucket = self.round_half_up(
            effective_observed_floor_high
        )
        validated_current_max_floor = self.validated_current_max_floor_bucket(
            trusted_current_max,
            history_max=history_max,
        )
        hard_floor_bucket = max(
            [
                bucket
                for bucket in (
                    effective_observed_bucket,
                    validated_current_max_floor,
                )
                if bucket is not None
            ],
            default=None,
        )
        current_observed_bucket = self.round_half_up(self.max_value(
            history_max,
            current_temp,
            metar_temp,
            validated_current_max_floor,
        ))
        observed_support_bucket = self.round_half_up(self.max_value(
            history_max,
            current_temp,
            eccc_max,
            metar_temp,
        ))
        max_signal = self.round_half_up(self.max_value(*live_values))
        if max_signal is None and not scores:
            pipeline = DistributionPipelineState()
            result = DistributionResult(
                distribution={},
                component_payload=pipeline.payload(),
                calibration_context={},
                active_model_kind="empirical",
                family_secondary_gate={},
            )
            return self._set_distribution_result_compatibility(result, pipeline)

        low = min(min(scores), round(self.spec.c_to_native(8)),
                  (hard_floor_bucket or observed_bucket or max_signal or round(self.spec.c_to_native(16))) - round(self.spec.scale_delta(5)))
        high = max(max(scores), round(self.spec.c_to_native(34)),
                   (max_signal or observed_bucket or round(self.spec.c_to_native(30))) + round(self.spec.scale_delta(4)))
        for temp in range(low, high + 1):
            scores.setdefault(temp, 0.0005)
        scores = self.normalize_scores(scores)
        pipeline = DistributionPipelineState()
        self._last_distribution_pipeline_state = pipeline
        pipeline.snapshot("climatology_prior", scores)

        calibration_context = {
            "cutoff_hour": cutoff_hour,
            "observed_floor_bucket": hard_floor_bucket,
            "wu_history_floor_bucket": observed_bucket,
            "effective_observed_high": effective_observed_high,
            "effective_observed_floor_high": effective_observed_floor_high,
            "effective_observed_floor_bucket": effective_observed_bucket,
            "effective_observed_high_source": observed_high_context[
                "effective_observed_high_source"
            ],
            "validated_current_max_floor_bucket": validated_current_max_floor,
            "current_observed_bucket": current_observed_bucket,
            "observed_support_bucket": observed_support_bucket,
            "current_max_state": current_max_features.get("current_max_state"),
            "current_max_disposition": current_max_features.get("current_max_disposition"),
            "quarantined_current_max": current_max_features.get("quarantined_current_max"),
            "current_max_boundary": deepcopy(current_max_boundary),
            "forecast_high": forecast_ensemble.get("forecast_high"),
            "forecast_robust_high": forecast_ensemble.get("forecast_robust_high"),
            "forecast_trimmed_high": forecast_ensemble.get("forecast_trimmed_high"),
            "forecast_disagreement": forecast_ensemble.get("forecast_disagreement"),
            "forecast_warm_outlier_flag": forecast_ensemble.get("forecast_warm_outlier_flag"),
            "forecast_warm_outlier_gap": forecast_ensemble.get("forecast_warm_outlier_gap"),
            "forecast_source_count": forecast_ensemble.get("forecast_source_count"),
            "forecast_source_values": forecast_ensemble.get("forecast_source_values"),
            "forecast_raw_source_values": forecast_ensemble.get("forecast_raw_source_values"),
            "forecast_raw_max": forecast_ensemble.get("forecast_raw_max"),
            "forecast_impossible_sources": forecast_ensemble.get("forecast_impossible_sources"),
            "forecast_impossible_features": forecast_ensemble.get("forecast_impossible_features"),
            "guidance_physical_floor": guidance_floor,
            "forecast_signal_values": forecast_signal_values,
            "target_date": getattr(self, "target_date_str", TARGET_DATE_STR),
        }
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
        (
            scores,
            intraday,
            using_feature_model,
            using_calibrated_empirical,
        ) = self.distribution_model_path_stage(
            scores,
            sources=sources,
            cutoff_hour=cutoff_hour,
            now=now,
            observed_bucket=observed_bucket,
            current=current,
            weather_forecast=weather_forecast,
            eccc_city=eccc_city,
            current_temp=current_temp,
            weather_forecast_max=weather_forecast_signal,
            open_meteo_max=open_meteo_signal,
            nws_forecast_max=nws_forecast_signal,
            global_ensemble_max=global_ensemble_signal,
            eccc_forecast_high=eccc_forecast_signal,
            weights_config=weights_config,
            weight_map=weight_map,
            has_component_weights=has_component_weights,
            pipeline=pipeline,
        )

        scores, bucket_transition = self.distribution_bucket_transition_stage(
            scores,
            sources,
            now,
            pipeline,
        )

        metar_live_signal = self.learned_metar_live_signal(metar_temp, history_max, hour=now.hour)

        live_signals = self.distribution_live_signals(
            using_feature_model=using_feature_model,
            using_calibrated_empirical=using_calibrated_empirical,
            hour=now.hour,
            history_max=history_max,
            current_temp=current_temp,
            current_max=trusted_current_max,
            eccc_max=eccc_max,
            metar_live_signal=metar_live_signal,
            weather_forecast_max=weather_forecast_signal,
            open_meteo_max=open_meteo_signal,
            nws_forecast_max=nws_forecast_signal,
            global_ensemble_max=global_ensemble_signal,
            eccc_forecast_high=eccc_forecast_signal,
            observed_bucket=observed_bucket,
            forecast_context=forecast_ensemble,
        )
        scores = self.distribution_apply_live_signals_stage(
            scores,
            live_signals,
            pipeline,
        )
        scores = self.distribution_hard_floor_stage(scores, hard_floor_bucket)
        scores = self.distribution_intraday_tail_stage(
            scores,
            intraday=intraday,
            observed_bucket=observed_bucket,
            hour=now.hour,
            weather_forecast_max=weather_forecast_signal,
            open_meteo_max=open_meteo_signal,
            nws_forecast_max=nws_forecast_signal,
            global_ensemble_max=global_ensemble_signal,
            eccc_forecast_high=eccc_forecast_signal,
        )
        scores = self.distribution_plausible_cap_stage(
            scores,
            observed_bucket=observed_bucket,
            weather_forecast_max=weather_forecast_signal,
            open_meteo_max=open_meteo_signal,
            nws_forecast_max=nws_forecast_signal,
            global_ensemble_max=global_ensemble_signal,
            eccc_forecast_high=eccc_forecast_signal,
            using_calibrated_empirical=using_calibrated_empirical,
        )
        scores = self.distribution_forecast_shape_stage(
            scores,
            forecast_values=forecast_values,
            history=history,
            now=now,
            observed_bucket=observed_bucket,
            current_observed_bucket=current_observed_bucket,
            using_feature_model=using_feature_model,
            using_calibrated_empirical=using_calibrated_empirical,
            pipeline=pipeline,
        )
        scores, ramp_warm_tail_context = self.distribution_ramp_warm_tail_dampening_stage(
            scores,
            hour=now.hour,
            observed_bucket=observed_bucket,
            current_observed_bucket=current_observed_bucket,
            forecast_context=forecast_ensemble,
            pipeline=pipeline,
        )
        calibration_context["ramp_warm_tail_dampening"] = ramp_warm_tail_context
        scores, afternoon_centering_context = self.distribution_afternoon_residual_centering_stage(
            scores,
            hour=now.hour,
            forecast_context=forecast_ensemble,
            pipeline=pipeline,
        )
        calibration_context["afternoon_residual_centering"] = afternoon_centering_context
        current_max_boundary_reference = self.normalize_scores(scores)
        scores = self.distribution_validated_current_max_floor_stage(
            scores,
            validated_current_max_floor,
            pipeline,
        )
        scores = self.distribution_observed_floor_stage(
            scores,
            eccc_max=eccc_max,
            current_temp=current_temp,
            metar_temp=metar_temp,
            history_max=history_max,
            observed_support_bucket=observed_support_bucket,
            hour=now.hour,
            pipeline=pipeline,
        )

        # One re-anchored history view for every late-day stage (S1-S6); the
        # S7 calibration taper below reads the strength it produces.
        lockin_anchor = self.late_day_lockin_anchor(
            history=history,
            history_max=history_max,
            guidance_floor=guidance_floor,
            station=station,
            metar=metar,
            now=now,
        )
        scores, late_day_continuation = self.distribution_late_day_continuation_stage(
            scores,
            sources=sources,
            cutoff_hour=cutoff_hour,
            now=now,
            using_feature_model=using_feature_model,
            observed_bucket=lockin_anchor["bucket"],
            observed_support_bucket=observed_support_bucket,
            pipeline=pipeline,
        )
        scores, lockin_strength, high_has_stood_context = self.distribution_late_day_lockin_stage(
            scores,
            history=history,
            current_temp=current_temp,
            metar_temp=metar_temp,
            history_max=history_max,
            now=now,
            weather_forecast=weather_forecast,
            open_meteo=open_meteo,
            nws_hourly=nws_hourly,
            global_ensemble=global_ensemble,
            eccc_city=eccc_city,
            official_current_stale=bool((sources.get("metar") or {}).get("stale")),
            pipeline=pipeline,
            lockin_anchor=lockin_anchor,
            continuation_blended="late_day_continuation_blend" in pipeline.components,
        )

        scores = self.normalize_scores(scores)
        pipeline.snapshot("pre_calibration_model", scores)
        # Taper the overconfidence-calibration toward identity as the day locks
        # in: once it is past peak and falling, the concentration is earned, so
        # softening it back toward uniform only re-inflates buckets the high can
        # no longer reach. resolution_weight == the late-day lock-in strength.
        calibrated_scores = apply_exact_distribution_calibration(
            scores,
            getattr(self, "probability_calibration", None),
            floor_bucket=self.max_value(
                hard_floor_bucket,
                lockin_anchor.get("observed_floor_bucket"),
            ),
            resolution_weight=lockin_strength,
            cutoff_hour=cutoff_hour,
        )
        pipeline.snapshot("overconfidence_calibration", calibrated_scores)
        calibrated_scores, current_max_boundary = self.apply_current_max_boundary_overlock_guard(
            calibrated_scores,
            current_max_boundary,
            allocation_reference=current_max_boundary_reference,
        )
        calibration_context["current_max_boundary"] = deepcopy(current_max_boundary)
        if current_max_boundary.get("active") or current_max_boundary.get("state") == "conflicting":
            pipeline.snapshot("current_max_boundary_guard", calibrated_scores)
        pipeline.snapshot("final_model", calibrated_scores)
        latest_wu_history_row, latest_wu_history_minute = self.latest_source_row(
            history.get("rows") or []
        )
        pipeline.update_metadata(
            cutoff_hour=cutoff_hour,
            active_model_kind=getattr(self, "active_model_kind", "empirical"),
            latest_wu_history_time=(
                latest_wu_history_row.get("time") if latest_wu_history_row else None
            ),
            latest_wu_history_minute=latest_wu_history_minute,
            latest_wu_history_temp=(
                self.row_temp_native(latest_wu_history_row) if latest_wu_history_row else None
            ),
            lockin_strength=lockin_strength,
            high_has_stood_lockin=high_has_stood_context,
            family_secondary_gate=pipeline.metadata.get("family_secondary_gate") or {},
            weak_input_family_preflight=deepcopy(getattr(self, "_last_weak_input_family_preflight", {}) or {}),
            bucket_transition=bucket_transition,
            late_day_continuation=late_day_continuation,
            ramp_warm_tail_dampening=ramp_warm_tail_context,
            forecast_ensemble=forecast_ensemble,
            forecast_signal_values=forecast_signal_values,
            observed_floor_bucket=hard_floor_bucket,
            wu_history_floor_bucket=observed_bucket,
            validated_current_max_floor_bucket=validated_current_max_floor,
            current_observed_bucket=current_observed_bucket,
            observed_support_bucket=observed_support_bucket,
            current_max_boundary=deepcopy(current_max_boundary),
        )
        component_payload = pipeline.payload()
        result = DistributionResult(
            distribution=calibrated_scores,
            component_payload=component_payload,
            calibration_context=calibration_context,
            active_model_kind=str(component_payload.get("active_model_kind") or getattr(self, "active_model_kind", "empirical") or "empirical"),
            family_secondary_gate=component_payload.get("family_secondary_gate") or {},
        )
        return self._set_distribution_result_compatibility(result, pipeline)

    def robust_forecast_signal_value(self, value, forecast_context):
        """Cap isolated warm forecast sources toward the robust ensemble high."""
        value = self.to_number(value)
        if value is None:
            return None
        forecast_context = forecast_context or {}
        robust_high = self.to_number(forecast_context.get("forecast_robust_high"))
        if robust_high is None:
            return value
        warm_outlier = bool(forecast_context.get("forecast_warm_outlier_flag"))
        disagreement = self.to_number(forecast_context.get("forecast_disagreement"))
        high_disagreement = (
            disagreement is not None
            and disagreement >= self.spec.scale_delta(RAMP_WARM_TAIL_DISAGREEMENT)
        )
        if not warm_outlier and not high_disagreement:
            return value
        cap = robust_high + self.spec.scale_delta(RAMP_WARM_TAIL_SOURCE_CAP_MARGIN)
        return min(value, cap)

    def apply_ramp_warm_tail_dampening(
        self,
        scores,
        *,
        hour,
        observed_bucket,
        current_observed_bucket,
        robust_forecast_high,
        forecast_disagreement,
        warm_outlier_flag,
    ):
        """Dampen ramp-window mass materially above robust live/forecast anchors."""
        normalized = self.normalize_scores(scores)
        context = {
            "active": False,
            "reason": "inactive",
            "hour": hour,
            "cap_bucket": None,
            "tail_probability_before": None,
            "tail_probability_after": None,
            "forecast_disagreement": forecast_disagreement,
            "forecast_warm_outlier_flag": 1.0 if warm_outlier_flag else 0.0,
        }
        if not normalized:
            context["reason"] = "empty_scores"
            return normalized, context
        if hour is None or hour < RAMP_WARM_TAIL_START_HOUR or hour > RAMP_WARM_TAIL_END_HOUR:
            context["reason"] = "outside_hour_window"
            return normalized, context
        disagreement = self.to_number(forecast_disagreement)
        high_disagreement = (
            disagreement is not None
            and disagreement >= self.spec.scale_delta(RAMP_WARM_TAIL_DISAGREEMENT)
        )
        if not warm_outlier_flag and not high_disagreement:
            context["reason"] = "no_warm_outlier_or_high_disagreement"
            return normalized, context

        anchors = []
        for value in (observed_bucket, current_observed_bucket):
            if value is not None:
                anchors.append(int(value))
        robust_bucket = self.round_half_up(robust_forecast_high)
        if robust_bucket is not None:
            anchors.append(robust_bucket)
        if not anchors:
            context["reason"] = "missing_anchor"
            return normalized, context

        margin = max(1, self.round_half_up(self.spec.scale_delta(RAMP_WARM_TAIL_ANCHOR_MARGIN)))
        cap_bucket = max(anchors) + margin
        tail_before = sum(probability for bucket, probability in normalized.items() if bucket > cap_bucket)
        context["cap_bucket"] = cap_bucket
        context["tail_probability_before"] = tail_before
        if tail_before <= 0:
            context["reason"] = "no_tail_above_cap"
            context["tail_probability_after"] = 0.0
            return normalized, context

        adjusted = {}
        for bucket, probability in normalized.items():
            if bucket <= cap_bucket:
                adjusted[bucket] = probability
            else:
                adjusted[bucket] = probability * (RAMP_WARM_TAIL_DECAY ** (bucket - cap_bucket))
        adjusted = self.normalize_scores(adjusted)
        tail_after = sum(probability for bucket, probability in adjusted.items() if bucket > cap_bucket)
        context["active"] = True
        context["reason"] = "warm_tail_above_robust_anchor_dampened"
        context["tail_probability_after"] = tail_after
        return adjusted, context

    def distribution_ramp_warm_tail_dampening_stage(
        self,
        scores,
        *,
        hour,
        observed_bucket,
        current_observed_bucket,
        forecast_context,
        pipeline,
    ):
        forecast_context = forecast_context or {}
        scores, context = self.apply_ramp_warm_tail_dampening(
            scores,
            hour=hour,
            observed_bucket=observed_bucket,
            current_observed_bucket=current_observed_bucket,
            robust_forecast_high=forecast_context.get("forecast_robust_high"),
            forecast_disagreement=forecast_context.get("forecast_disagreement"),
            warm_outlier_flag=bool(forecast_context.get("forecast_warm_outlier_flag")),
        )
        if context.get("active"):
            pipeline.snapshot_normalized(
                "ramp_warm_tail_dampening",
                scores,
                self.normalize_scores,
            )
        return scores, context

    def afternoon_residual_regime_id(self):
        if self.spec.display_unit == "C":
            return "canadian"
        return "marine" if self.spec.coastal else "continental"

    def distribution_afternoon_residual_centering_stage(
        self,
        scores,
        *,
        hour,
        forecast_context,
        pipeline,
    ):
        scores, context = apply_afternoon_residual_centering(
            scores,
            getattr(self, "afternoon_residual_centering", None),
            market_id=getattr(self, "market_id", None),
            regime_id=self.afternoon_residual_regime_id(),
            hour=hour,
            forecast_disagreement=(forecast_context or {}).get("forecast_disagreement"),
        )
        if context.get("active"):
            pipeline.snapshot_normalized(
                "afternoon_residual_centering",
                scores,
                self.normalize_scores,
            )
        return scores, context

    def distribution_model_path_stage(
        self,
        scores,
        *,
        sources,
        cutoff_hour,
        now,
        observed_bucket,
        current,
        weather_forecast,
        eccc_city,
        current_temp,
        weather_forecast_max,
        open_meteo_max,
        nws_forecast_max,
        global_ensemble_max,
        eccc_forecast_high,
        weights_config,
        weight_map,
        has_component_weights,
        pipeline,
    ):
        """Blend either the feature-model path or the empirical component path."""
        intraday = None
        using_feature_model = False
        using_calibrated_empirical = False
        try:
            feature_result = self.predict_feature_distribution(
                sources,
                cutoff_hour,
                now,
                include_gate=True,
            )
        except TypeError as exc:
            if "include_gate" not in str(exc):
                raise
            feature_result = self.predict_feature_distribution(sources, cutoff_hour, now)
        if len(feature_result) == 3:
            feature_probs, active_kind, family_secondary_gate = feature_result
        else:
            feature_probs, active_kind = feature_result
            family_secondary_gate = deepcopy(getattr(self, "_last_family_secondary_gate", {}) or {})
        pipeline.update_metadata(family_secondary_gate=deepcopy(family_secondary_gate or {}))
        if feature_probs:
            using_feature_model = True
            self.active_model_kind = active_kind
            candidate_prior = self.feature_serving_prior(cutoff_hour)
            if candidate_prior is not None:
                scores = candidate_prior
                pipeline.snapshot_normalized(
                    "candidate_target_date_aligned_prior",
                    scores,
                    self.normalize_scores,
                )
            smoothing_config = self.feature_ordinal_smoothing_config(cutoff_hour)
            pipeline.update_metadata(feature_ordinal_smoothing=deepcopy(smoothing_config))
            if smoothing_config.get("enabled"):
                feature_probs = self.ordinal_smooth_distribution(
                    feature_probs,
                    sigma=smoothing_config.get("sigma", 0.0),
                    blend_weight=smoothing_config.get("blend_weight", 0.0),
                )
            pipeline.snapshot_normalized(
                f"{active_kind}_feature_model",
                feature_probs,
                self.normalize_scores,
            )
            scores = self.blend_distribution(
                scores,
                feature_probs,
                self.feature_blend_weight(cutoff_hour),
            )
            pipeline.snapshot("feature_blend", scores)
            return scores, intraday, using_feature_model, using_calibrated_empirical

        self.active_model_kind = "empirical"
        intraday = self.historical_intraday_distribution(
            observed_bucket,
            cutoff_hour,
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
            nws_forecast_max,
            global_ensemble_max,
            eccc_forecast_high,
        ))
        forecast_component = self.forecast_error_component_distribution(
            scores.keys(),
            observed_bucket,
            weather_forecast_max,
            open_meteo_max,
            eccc_forecast_high,
            now.hour,
            nws_forecast_max=nws_forecast_max,
            global_ensemble_max=global_ensemble_max,
        )
        cap_distribution = forecast_component or self.cap_prior_distribution(
            scores.keys(),
            calibrated_cap,
            floor_bucket=observed_bucket,
        )
        empirical_components = {
            "intraday_high": intraday["probabilities"] if intraday else None,
            "current_bucket": (
                current_distribution["probabilities"]
                if current_distribution else None
            ),
            "wind_regime": (
                wind_distribution["probabilities"]
                if wind_distribution else None
            ),
            "cloud_regime": (
                cloud_distribution["probabilities"]
                if cloud_distribution else None
            ),
            "forecast_error" if forecast_component else "forecast_cap": cap_distribution,
        }
        for name, distribution in empirical_components.items():
            if distribution:
                pipeline.snapshot_normalized(name, distribution, self.normalize_scores)

        if has_component_weights:
            using_calibrated_empirical = True
            components = {
                "climatology": scores,
                "intraday_high": empirical_components["intraday_high"],
                "current_bucket": empirical_components["current_bucket"],
                "wind_regime": empirical_components["wind_regime"],
                "cloud_regime": empirical_components["cloud_regime"],
                "forecast_cap": cap_distribution,
            }
            scores = self.weighted_component_distribution(
                components,
                weight_map,
            )
            pipeline.snapshot("empirical_weighted", scores)
            return scores, intraday, using_feature_model, using_calibrated_empirical

        if intraday:
            if weights_config:
                w_int_base = weights_config.get("w_intraday_base", 0.36)
                intraday_weight = w_int_base * (intraday["n"] / (intraday["n"] + 25))
            else:
                intraday_weight = self.intraday_blend_weight(now.hour, intraday["n"])
            scores = self.blend_distribution(
                scores,
                intraday["probabilities"],
                intraday_weight,
            )

        if wind_distribution:
            w_wnd = weights_config.get("w_wind", 0.14) if weights_config else 0.14
            scores = self.blend_distribution(
                scores,
                wind_distribution["probabilities"],
                w_wnd,
            )

        if cloud_distribution:
            w_cld = weights_config.get("w_cloud", 0.12) if weights_config else 0.12
            scores = self.blend_distribution(
                scores,
                cloud_distribution["probabilities"],
                w_cld,
            )

        return scores, intraday, using_feature_model, using_calibrated_empirical

    def distribution_bucket_transition_stage(self, scores, sources, now, pipeline):
        """Blend the WU bucket-transition prior and record its snapshots."""
        bucket_transition = self.bucket_transition_model(
            sources,
            now,
            min_sample_size=BUCKET_TRANSITION_MIN_SAMPLE,
        )
        bucket_transition_probabilities = bucket_transition.get("probabilities") or {}
        bucket_transition_weight = self.bucket_transition_blend_weight(bucket_transition)
        if bucket_transition_probabilities and bucket_transition_weight > 0:
            pipeline.snapshot_normalized(
                "bucket_transition_model",
                bucket_transition_probabilities,
                self.normalize_scores,
            )
            scores = self.blend_distribution(
                scores,
                bucket_transition_probabilities,
                bucket_transition_weight,
            )
            pipeline.snapshot("bucket_transition_blend", scores)
        return scores, bucket_transition

    def distribution_apply_live_signals_stage(self, scores, live_signals, pipeline):
        """Apply live signal kernels and record the post-live-signal snapshot."""
        scores = self.apply_live_signals(scores, live_signals)
        pipeline.snapshot_normalized("post_live_signals", scores, self.normalize_scores)
        return scores

    def distribution_hard_floor_stage(self, scores, hard_floor_bucket):
        """Apply the hard settlement floor from trusted same-day observations."""
        if hard_floor_bucket is not None:
            self.apply_floor(scores, hard_floor_bucket, 0.000001)
            scores = self.normalize_scores(scores)
        return scores

    def distribution_intraday_tail_stage(
        self,
        scores,
        *,
        intraday,
        observed_bucket,
        hour,
        weather_forecast_max,
        open_meteo_max,
        nws_forecast_max,
        global_ensemble_max,
        eccc_forecast_high,
    ):
        """Shape the upper tail toward the historical intraday continuation rate."""
        if intraday and observed_bucket is not None:
            tail_target = sum(
                probability
                for temp, probability in intraday["probabilities"].items()
                if temp > observed_bucket
            )
            if (
                weather_forecast_max is not None
                and self.round_half_up(weather_forecast_max) <= observed_bucket
            ):
                tail_target *= 0.70
            ahead_forecast = self.max_value(
                open_meteo_max,
                nws_forecast_max,
                global_ensemble_max,
                eccc_forecast_high,
            )
            if ahead_forecast is not None and self.round_half_up(ahead_forecast) > observed_bucket:
                tail_target *= 1.12
            tail_target = max(0.01, min(0.95, tail_target))
            scores = self.apply_tail_target(
                scores,
                observed_bucket,
                tail_target,
                self.tail_target_weight(hour),
            )
        return scores

    def distribution_plausible_cap_stage(
        self,
        scores,
        *,
        observed_bucket,
        weather_forecast_max,
        open_meteo_max,
        nws_forecast_max,
        global_ensemble_max,
        eccc_forecast_high,
        using_calibrated_empirical,
    ):
        """Suppress buckets beyond the highest plausible live/forecast cap."""
        plausible_cap = self.round_half_up(self.max_value(
            observed_bucket,
            weather_forecast_max,
            open_meteo_max,
            nws_forecast_max,
            global_ensemble_max,
            eccc_forecast_high,
        ))
        if plausible_cap is not None and not using_calibrated_empirical:
            for temp in list(scores):
                if temp > plausible_cap + 1:
                    scores[temp] *= 0.28 ** (temp - plausible_cap - 1)
        return scores

    def distribution_forecast_shape_stage(
        self,
        scores,
        *,
        forecast_values,
        history,
        now,
        observed_bucket,
        current_observed_bucket,
        using_feature_model,
        using_calibrated_empirical,
        pipeline,
    ):
        """Apply the forecast floor and upper-tail forecast pull."""
        market_id = str(getattr(self, "market_id", "") or "").strip().lower()
        policy = {
            "enabled": (
                not using_feature_model
                and not using_calibrated_empirical
                and market_id in EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS
            ),
            "market_id": market_id or None,
            "allowed_markets": sorted(EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS),
            "reason": None,
        }
        if using_feature_model or using_calibrated_empirical:
            policy["reason"] = "feature_or_calibrated_empirical_path"
            pipeline.update_metadata(forecast_shape_policy=policy)
            return scores
        if market_id not in EMPIRICAL_FORECAST_SHAPE_ALLOWED_MARKETS:
            policy["reason"] = "empirical_fallback_market_not_validated"
            pipeline.update_metadata(forecast_shape_policy=policy)
            return scores
        policy["reason"] = "empirical_fallback_market_validated"
        pipeline.update_metadata(forecast_shape_policy=policy)
        floor_votes = self.unfalsified_forecasts(
            forecast_values,
            history,
            now,
        )
        scores = self.apply_forecast_floor(
            scores,
            floor_votes,
            now.hour,
            observed_bucket,
        )
        scores = self.apply_forecast_pull(
            scores,
            forecast_values,
            now.hour,
            observed_bucket,
            current_observed_bucket,
        )
        pipeline.snapshot_normalized("forecast_pull", scores, self.normalize_scores)
        return scores

    def distribution_validated_current_max_floor_stage(
        self,
        scores,
        validated_current_max_floor,
        pipeline,
    ):
        """Apply a validated hard max-since-7am floor for markets that allow it."""
        if validated_current_max_floor is not None:
            self.apply_floor(scores, validated_current_max_floor, 0.000001)
            scores = self.normalize_scores(scores)
            pipeline.snapshot("validated_current_max_floor", scores)
        return scores

    def distribution_observed_floor_stage(
        self,
        scores,
        *,
        eccc_max,
        current_temp,
        metar_temp,
        history_max,
        observed_support_bucket,
        hour,
        pipeline,
    ):
        """Apply settlement-lag, current-observation, and WU residual floors."""
        scores = self.apply_live_observed_floor(scores, eccc_max, history_max, hour=hour)
        pipeline.snapshot_normalized("settlement_lag_adjusted", scores, self.normalize_scores)
        scores = self.apply_current_observed_floor(
            scores,
            current_temp,
            metar_temp,
            history_max,
            hour=hour,
        )
        pipeline.snapshot_normalized("current_observed_floor", scores, self.normalize_scores)
        scores = self.preserve_wu_floor_residual(
            scores,
            history_max,
            observed_support_bucket,
        )
        pipeline.snapshot_normalized("wu_floor_residual", scores, self.normalize_scores)
        return scores

    def distribution_late_day_continuation_stage(
        self,
        scores,
        *,
        sources,
        cutoff_hour,
        now,
        using_feature_model,
        observed_bucket,
        observed_support_bucket,
        pipeline,
    ):
        """Blend the learned late-day continuation probability when eligible."""
        late_day_continuation = None
        live_support_ahead_of_wu = (
            observed_support_bucket is not None
            and observed_bucket is not None
            and observed_support_bucket > observed_bucket
        )
        if (
            using_feature_model
            and observed_bucket is not None
            and not live_support_ahead_of_wu
        ):
            late_day_continuation = self.predict_late_day_continuation(
                sources,
                cutoff_hour,
                now,
            )
            continuation_probability = (
                late_day_continuation or {}
            ).get("continuation_probability")
            continuation_weight = self.late_day_continuation_blend_weight(now.hour)
            if continuation_probability is not None and continuation_weight > 0:
                tail_target = max(0.0, min(1.0, float(continuation_probability)))
                scores = self.apply_tail_target(
                    scores,
                    observed_bucket,
                    tail_target,
                    continuation_weight,
                )
                pipeline.snapshot_normalized(
                    "late_day_continuation_blend",
                    scores,
                    self.normalize_scores,
                )
        return scores, late_day_continuation

    def late_day_lockin_anchor(
        self,
        *,
        history,
        history_max,
        guidance_floor,
        station=None,
        metar=None,
        now=None,
    ):
        """Return the one history view every late-day lock-in stage reads.

        Lock-in anchor contract ``LATE_DAY_LOCKIN_ANCHOR_VERSION``.  While the
        WU printed history supplies the high, the view is that history,
        untouched (the pre-restoration anchor).  When it is empty, as it has
        been since paid WU access was disabled, the lock-in re-anchors on the
        OBSERVED high of the target local day: the maximum of the
        point-in-time station rows (METAR rows, plus SWOB rows where SWOB is
        the station source) observed on the target local day at or before
        ``now``.  METAR rows are keyed by observation time (``obsTime`` from
        the retained AWC payload, else the ``DDHHMMZ`` group of the raw
        report), not by AWC ``reportTime``: a D-1 23:5x report carried into
        day D as a "00:00" row (capture defect M0) is excluded, so the anchor
        is never a prior-day reading.  It never exceeds
        ``guidance_physical_floor``.  ``max_times`` is the first such row whose
        value reached ``B = round_half_up(anchor)``.  Every stage acts only
        above ``B``; ``apply_lockin_observed_floor`` handles the mass below it,
        at every hour (v4), not only once a late-day stage acts.
        """
        history = history or {}
        legacy = bool(getattr(self, "late_day_lockin_legacy_wu_anchor", False))
        anchor = {
            "version": LATE_DAY_LOCKIN_ANCHOR_VERSION,
            "source": "wu_history" if history_max is not None else None,
            "high": history_max,
            "bucket": self.round_half_up(history_max),
            "first_reached_time": (history.get("max_times") or [None])[0],
            "guidance_physical_floor": self.to_number(guidance_floor),
            "excluded_prior_day_rows": 0,
            "metar_bucket": None,
            "legacy_wu_anchor": legacy,
            "history": history,
        }
        if history_max is not None or legacy:
            return anchor
        rows, excluded = self.lockin_observed_rows(station=station, metar=metar, now=now)
        anchor["excluded_prior_day_rows"] = excluded
        if not rows:
            return anchor
        high = max(value for _, _, value in rows)
        bucket = self.round_half_up(high)
        # The pre-lock-in floor (v4) reads METAR rows only: the owner accepted a
        # hard zero below a METAR-derived reading, and SWOB keeps its warm-bias
        # hedge (apply_live_observed_floor) until a late-day stage acts.
        metar_rows, _ = self.lockin_observed_rows(metar=metar, now=now)
        if metar_rows:
            anchor["metar_bucket"] = self.round_half_up(max(value for _, _, value in metar_rows))
        first_time = next(
            (time for _, time, value in rows if self.round_half_up(value) >= bucket),
            None,
        )
        view = dict(history)
        view["max_native"] = high
        view["max_c"] = high
        view["max_times"] = [first_time] if first_time else []
        anchor.update({
            "source": "observed_station_rows",
            "high": high,
            "bucket": bucket,
            "first_reached_time": first_time,
            "history": view,
        })
        return anchor

    def lockin_observed_rows(self, *, station=None, metar=None, now=None):
        """Point-in-time observed rows of the target local day, keyed by
        observation time: ``([(minute, "HH:MM", value)], excluded_count)``."""
        target = getattr(self, "target_date", None)
        tz = self.spec.tz
        raw_obs_times = {}
        for item in (metar or {}).get("raw_payload") or []:
            if isinstance(item, dict) and item.get("rawOb") and item.get("obsTime") is not None:
                raw_obs_times[str(item["rawOb"])] = item["obsTime"]
        row_sets = [(metar or {}).get("rows") or []]
        station = station or {}
        station_source = station.get("station_observation_source") or station.get("source")
        if station_source not in (None, "metar") or not row_sets[0]:
            row_sets.append(station.get("rows") or [])
        now_minute = now.hour * 60 + now.minute if now is not None else None
        now_local = now.astimezone(tz) if now is not None and now.tzinfo else None
        rows = []
        excluded = 0
        for source_rows in row_sets:
            for row in source_rows:
                value = self.row_temp_native(row)
                if value is None or not plausible_native_temperature(value, self.spec.display_unit):
                    continue
                observed = self.metar_observation_local_time(row, raw_obs_times)
                if observed is None:
                    observed = self.row_obs_time_local(row)
                if observed is not None:
                    if target is not None and observed.date() != target:
                        excluded += 1
                        continue
                    if now_local is not None and observed > now_local:
                        continue
                    minute = observed.hour * 60 + observed.minute
                else:
                    minute = self.minute_of_day(row.get("local_time") or row.get("time"))
                    if minute is None:
                        continue
                    if now_minute is not None and minute > now_minute:
                        continue
                rows.append((minute, "%02d:%02d" % divmod(minute, 60), value))
        rows.sort(key=lambda item: item[0])
        return rows, excluded

    def row_obs_time_local(self, row):
        """Local time of a row's own ``obs_time`` (ISO UTC), or None."""
        value = row.get("obs_time")
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(self.spec.tz)

    def metar_observation_local_time(self, row, raw_obs_times=None):
        """Local observation time of a METAR row, or None when it is not one.

        AWC ``reportTime`` is the nominal hour, so the observation time comes
        from the payload ``obsTime`` (epoch seconds) when retained, else from
        the ``DDHHMMZ`` group of the raw report anchored on ``reportTime``.
        """
        raw = row.get("raw")
        if not raw:
            return None
        obs_epoch = (raw_obs_times or {}).get(str(raw))
        if obs_epoch is not None:
            try:
                return datetime.fromtimestamp(float(obs_epoch), timezone.utc).astimezone(self.spec.tz)
            except (TypeError, ValueError, OverflowError, OSError):
                pass
        match = METAR_OBSERVATION_GROUP_RE.search(str(raw))
        report = row.get("report_time") or row.get("datetime")
        if not match or not report:
            return None
        try:
            report_dt = datetime.fromisoformat(str(report).replace("Z", "+00:00"))
        except ValueError:
            return None
        if report_dt.tzinfo is None:
            return None
        report_utc = report_dt.astimezone(timezone.utc)
        day, hour, minute = (int(part) for part in match.groups())
        for offset in (0, -1, -2, 1):
            candidate = report_utc + timedelta(days=offset)
            if candidate.day == day:
                observed = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return observed.astimezone(self.spec.tz)
        return None

    def apply_lockin_observed_floor(self, scores, bucket):
        """Move every probability below the observed anchor bucket onto it.

        The anchor is an observed same-day reading, so the settled high cannot
        round below ``bucket``.  Moving that mass onto ``bucket`` (instead of
        renormalizing it across the support) means a late-day stage never
        leaves or adds mass below its anchor; buckets at or above ``bucket``
        keep their mass.
        """
        if bucket is None or not scores:
            return self.normalize_scores(scores)
        below = sum(max(0.0, p) for b, p in scores.items() if b < bucket)
        adjusted = {b: (0.0 if b < bucket else max(0.0, p)) for b, p in scores.items()}
        adjusted[bucket] = adjusted.get(bucket, 0.0) + below
        return self.normalize_scores(adjusted)

    def distribution_late_day_lockin_stage(
        self,
        scores,
        *,
        history,
        current_temp,
        metar_temp,
        history_max,
        now,
        weather_forecast,
        open_meteo,
        nws_hourly,
        global_ensemble,
        eccc_city,
        pipeline,
        official_current_stale=False,
        lockin_anchor=None,
        continuation_blended=False,
    ):
        """Apply late-day lock-in and return the metadata needed downstream.

        ``lockin_anchor`` (from ``late_day_lockin_anchor``) supplies the one
        history view and high that S1-S5 read; without it the stage reads the
        WU history exactly as before.  When the anchor is the observed station
        high and any late-day stage acted (hard or partial lock-in here, or the
        ``continuation_blended`` S6 blend upstream), the mass below the anchor
        bucket moves onto it, so a late-day stage never leaves mass below an
        observed floor.  ``lockin_anchor["observed_floor_bucket"]`` then
        carries that bucket to the calibration floor.
        """
        if lockin_anchor is not None:
            history = lockin_anchor["history"]
            history_max = lockin_anchor["high"]
        current_reading = current_temp if current_temp is not None else metar_temp
        heuristic_lockin_strength = self.late_day_lockin_strength(
            now.hour,
            current_reading,
            history_max,
        )
        learned_lockin_strength = self.learned_lockin_strength(now.hour, history, now)
        high_has_stood_context = self.high_has_stood_lockin_context(
            now.hour,
            history,
            current_reading,
            now,
            weather_forecast,
            open_meteo,
            nws_hourly,
            global_ensemble,
            eccc_city,
            official_current_reading=metar_temp,
            official_source="metar",
            official_current_stale=official_current_stale,
        )
        high_has_stood_strength = high_has_stood_context.get("strength") or 0.0
        expanded_lockin_context = self.expanded_late_day_lockin_context(
            now.hour,
            history,
            current_reading,
            now,
            weather_forecast,
            open_meteo,
            nws_hourly,
            global_ensemble,
            eccc_city,
            official_current_reading=metar_temp,
            official_source="metar",
            official_current_stale=official_current_stale,
        )
        expanded_lockin_strength = expanded_lockin_context.get("strength") or 0.0
        partial_lockin_context = self.standing_high_partial_lockin_context(
            now.hour,
            history,
            current_reading,
            now,
            weather_forecast,
            open_meteo,
            nws_hourly,
            global_ensemble,
            eccc_city,
            official_current_reading=metar_temp,
            official_source="metar",
            official_current_stale=official_current_stale,
        )
        lockin_strength = max(
            heuristic_lockin_strength,
            learned_lockin_strength,
            high_has_stood_strength,
            expanded_lockin_strength,
        )
        scores = self.apply_late_day_lockin(
            scores,
            history_max,
            current_reading,
            now.hour,
            strength=lockin_strength,
        )
        hard_lockin_active = lockin_strength > 0.0
        if high_has_stood_strength > max(heuristic_lockin_strength, learned_lockin_strength):
            pipeline.snapshot_normalized("high_has_stood_lockin", scores, self.normalize_scores)
        if expanded_lockin_strength > max(
            heuristic_lockin_strength,
            learned_lockin_strength,
            high_has_stood_strength,
        ):
            pipeline.snapshot_normalized("expanded_late_day_lockin", scores, self.normalize_scores)
        if hard_lockin_active:
            partial_lockin_context = deepcopy(partial_lockin_context)
            partial_lockin_context.update({
                "active": False,
                "stage": "hard_lockin",
                "reason": "hard_lockin_already_active",
                "hard_lockin_strength": lockin_strength,
            })
        else:
            scores, partial_lockin_context = self.apply_standing_high_partial_lockin(
                scores,
                history_max,
                partial_lockin_context,
            )
            if partial_lockin_context.get("active"):
                pipeline.snapshot_normalized(
                    "standing_high_partial_lockin",
                    scores,
                    self.normalize_scores,
                )
        high_has_stood_context = deepcopy(high_has_stood_context)
        high_has_stood_context["expanded_late_day_lockin"] = expanded_lockin_context
        high_has_stood_context["standing_high_partial_lockin"] = partial_lockin_context
        high_has_stood_context["heuristic_lockin_strength"] = heuristic_lockin_strength
        high_has_stood_context["learned_lockin_strength"] = learned_lockin_strength
        if lockin_anchor is not None:
            high_has_stood_context["lockin_anchor"] = {
                key: value for key, value in lockin_anchor.items() if key != "history"
            }
        partial_strength = (
            partial_lockin_context.get("strength") or 0.0
            if partial_lockin_context.get("active")
            else 0.0
        )
        effective_lockin_strength = max(lockin_strength, partial_strength)
        observed_floor_bucket = None
        observed_floor_stage = None
        late_day_acts = effective_lockin_strength > 0.0 or continuation_blended
        # lockin-anchor-v4: the observed same-day high is a floor at every hour,
        # not only once a late-day stage acts.  Before lock-in nothing else
        # holds the same-day max since midnight (the hard floor reads the
        # current reading and max-since-07:00 only).
        pre_lockin_floor = bool(getattr(self, "pre_lockin_same_day_floor", True))
        observed_anchor = (
            lockin_anchor is not None
            and lockin_anchor.get("source") == "observed_station_rows"
            and lockin_anchor.get("bucket") is not None
        )
        if observed_anchor and late_day_acts:
            observed_floor_bucket = lockin_anchor["bucket"]
            observed_floor_stage = "late_day"
        elif observed_anchor and pre_lockin_floor and lockin_anchor.get("metar_bucket") is not None:
            observed_floor_bucket = lockin_anchor["metar_bucket"]
            observed_floor_stage = "pre_lockin"
        if observed_floor_bucket is not None:
            # The current-max overlock guard never runs alongside this floor:
            # it needs a WU history bucket, and an observed anchor exists only
            # while WU history is empty.
            scores = self.apply_lockin_observed_floor(scores, observed_floor_bucket)
        if lockin_anchor is not None:
            lockin_anchor["observed_floor_bucket"] = observed_floor_bucket
            lockin_anchor["observed_floor_stage"] = observed_floor_stage
            high_has_stood_context["lockin_anchor"]["observed_floor_bucket"] = observed_floor_bucket
            high_has_stood_context["lockin_anchor"]["observed_floor_stage"] = observed_floor_stage
        high_has_stood_context["stage_attribution"] = {
            "hard_lockin_strength": lockin_strength,
            "partial_dampener_strength": partial_strength,
            "final_stage": (
                "hard_lockin"
                if hard_lockin_active
                else "partial_dampening" if partial_strength > 0 else "no_action"
            ),
        }
        pipeline.snapshot_normalized("late_day_lockin", scores, self.normalize_scores)
        return scores, effective_lockin_strength, high_has_stood_context

    def distribution_live_signals(
        self,
        *,
        using_feature_model,
        using_calibrated_empirical,
        hour,
        history_max,
        current_temp,
        current_max,
        eccc_max,
        metar_live_signal,
        weather_forecast_max,
        open_meteo_max,
        nws_forecast_max,
        global_ensemble_max,
        eccc_forecast_high,
        observed_bucket,
        forecast_context=None,
    ):
        """Return the live-signal stage inputs for the current model path."""
        current_max_live_signal = None if hour is not None and int(hour) < 7 else current_max
        if using_feature_model:
            current_max_signal = None
            current_max_bucket = self.round_half_up(current_max_live_signal)
            if current_max_bucket is not None and (
                observed_bucket is None or current_max_bucket > observed_bucket
            ):
                current_max_signal = current_max_live_signal
            forecast_cluster_signal = self.forecast_source_cluster_signal(
                hour,
                weather_forecast_max=weather_forecast_max,
                open_meteo_max=open_meteo_max,
                nws_forecast_max=nws_forecast_max,
                global_ensemble_max=global_ensemble_max,
                eccc_forecast_high=eccc_forecast_high,
                forecast_context=forecast_context,
            )
            peak_cluster_signal = self.max_value(
                current_max_signal,
                forecast_cluster_signal[0],
            )
            if forecast_cluster_signal[0] is None:
                peak_cluster_weight = 1.1
            else:
                peak_cluster_weight = min(1.6, max(1.1, forecast_cluster_signal[1]))
            return [
                # Current max, forecast sources, and Open-Meteo often share
                # the same weather-family signal. Treat them as one robust peak
                # cluster so a lone warm source cannot own the feature path.
                (peak_cluster_signal, peak_cluster_weight, 1.0),
                (eccc_max, 0.6, 0.8),
                (eccc_forecast_high, 0.5, 1.2),
            ]
        if using_calibrated_empirical:
            return [
                (history_max, self.history_signal_weight(hour), 0.65),
                (
                    self.round_half_up(eccc_max) if eccc_max is not None else None,
                    0.6,
                    0.9,
                ),
                metar_live_signal or (None, 0.0, METAR_LIVE_SIGNAL_SIGMA),
            ]
        forecast_cluster_signal = self.forecast_source_cluster_signal(
            hour,
            weather_forecast_max=weather_forecast_max,
            open_meteo_max=open_meteo_max,
            nws_forecast_max=nws_forecast_max,
            global_ensemble_max=global_ensemble_max,
            eccc_forecast_high=eccc_forecast_high,
            forecast_context=forecast_context,
        )
        return [
            (history_max, self.history_signal_weight(hour), 0.65),
            (current_temp, 1.8, 0.65),
            # The disabled paid-provider 24h max can include the previous afternoon. For this
            # market we only use the same-day max-since-7am field.
            (current_max_live_signal, 2.3, 0.75),
            (
                self.round_half_up(eccc_max) if eccc_max is not None else None,
                0.6,
                0.9,
            ),
            metar_live_signal or (None, 0.0, METAR_LIVE_SIGNAL_SIGMA),
            forecast_cluster_signal,
        ]

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
        _latest_row, latest_minute = self.latest_source_row(self.rows_for_target_date(rows or []))
        if latest_minute is None:
            return wall_cutoff
        latest_minute = self.aliased_settlement_print_minute(latest_minute, wall_cutoff)
        eligible = [
            cutoff for cutoff in INTRADAY_CUTOFF_HOURS
            if cutoff <= wall_cutoff and cutoff * 60 <= latest_minute
        ]
        return eligible[-1] if eligible else INTRADAY_CUTOFF_HOURS[0]

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

    def forecast_source_cluster_signal(
        self,
        hour,
        *,
        weather_forecast_max,
        open_meteo_max,
        nws_forecast_max,
        global_ensemble_max,
        eccc_forecast_high,
        forecast_context=None,
    ):
        values = [
            weather_forecast_max,
            self.round_half_up(open_meteo_max) if open_meteo_max is not None else None,
            self.round_half_up(nws_forecast_max) if nws_forecast_max is not None else None,
            self.round_half_up(global_ensemble_max) if global_ensemble_max is not None else None,
            eccc_forecast_high,
        ]
        values = [value for value in values if value is not None]
        if not values:
            return (None, 0.0, 1.1)
        forecast_context = forecast_context or {}
        raw_values = list(values)
        robust_high = self.to_number(forecast_context.get("forecast_robust_high"))
        if robust_high is not None and forecast_context.get("forecast_warm_outlier_flag"):
            cap = robust_high + self.spec.scale_delta(RAMP_WARM_TAIL_SOURCE_CAP_MARGIN)
            values = [min(value, cap) for value in values]
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            cluster_value = ordered[midpoint]
        else:
            cluster_value = (ordered[midpoint - 1] + ordered[midpoint]) / 2.0
        spread = max(raw_values) - min(raw_values)
        agreement = max(0.1, self.spec.scale_delta(FORECAST_AGREEMENT_SPREAD))
        agreement_factor = max(0.5, 1.0 - spread / (2.0 * agreement))
        base_weight = self.forecast_signal_weight(hour)
        count_weight = (
            base_weight
            if len(values) <= 1
            else min(
                FORECAST_CLUSTER_MAX_WEIGHT,
                base_weight + FORECAST_CLUSTER_SOURCE_WEIGHT_STEP * (len(values) - 1),
            )
        )
        weight = count_weight * agreement_factor
        return (cluster_value, weight, 1.1)
