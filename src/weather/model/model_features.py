import json
import logging
import math
import statistics
from collections import Counter, defaultdict
from copy import deepcopy

from weather.artifacts import resolve_artifact_path
from weather.model.feature_store import (
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    NATIVE_NAN_FEATURE_COLUMNS,
    build_historical_feature_record,
    build_live_feature_record,
    closest_wind_direction,
    current_max_trust_features,
    empty_eccc_gridded_features,
    empty_marine_context_features,
    empty_mrms_precip_features,
    empty_reanalysis_synoptic_features,
    empty_us_guidance_features,
    forecast_profile_features,
    merge_forecast_air_quality_rows,
    row_value,
    startup_observation_guard_features,
    row_wind_direction,
    wind_direction_delta_degrees,
)
from weather.sources.forecast_history import load_forecast_daily, daily_path_for
from weather.sources.eccc_gridded import derive_eccc_gridded_features
from weather.sources.marine_context import derive_marine_context_features
from weather.sources.mrms_precip import derive_mrms_precip_features
from weather.sources.nbm_probabilistic_tmax import exceedance_probability_from_percentiles
from weather.model.calibration_runtime import temperature_scale_distribution
from weather.model.model_constants import _UNLOADED
from weather.release_serving import ReleaseServingBindingError

logger = logging.getLogger(__name__)


class FeatureModelMixin:
    """Feature extraction, HGB/LR feature model, late-day, analogs, transitions."""

    def _bound_base_component(self, component_name):
        components = getattr(self, "_bound_base_model_components", None)
        if components is not None:
            return True, components[component_name]
        bundle = getattr(self, "serving_bundle", None)
        if bundle is not None and getattr(bundle, "pointer_present", False):
            raise ReleaseServingBindingError(
                f"active release forbids global base-model fallback: {component_name}"
            )
        return False, None

    def load_feature_model_hgb(self):
        if self._feature_model_hgb is _UNLOADED:
            self._feature_model_hgb = self._read_feature_model_hgb()
        return self._feature_model_hgb

    def _read_feature_model_hgb(self):
        bound, payload = self._bound_base_component("feature_hgb")
        if bound:
            return payload
        path = resolve_artifact_path(f"feature_model_hgb{self.spec.artifact_suffix}.pkl")
        if path.exists():
            try:
                import pickle
                with path.open("rb") as f:
                    return pickle.load(f)
            except Exception as e:
                logger.warning("Error loading HGBC pickle: %s", e)
        return None

    def load_feature_model_coefs(self):
        if self._feature_model_coefs is _UNLOADED:
            self._feature_model_coefs = self._read_feature_model_coefs()
        return self._feature_model_coefs

    def _read_feature_model_coefs(self):
        bound, payload = self._bound_base_component("feature_lr_coefficients")
        if bound:
            return payload
        path = resolve_artifact_path(f"feature_model_coefs{self.spec.artifact_suffix}.json")
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Error loading LR JSON coefs: %s", e)
        return None

    def feature_blend_weight(self, cutoff_hour, default=0.80):
        """Per-hour climatology<->feature-model blend weight (fraction on the
        model). Tuned by LOO log loss and stored in the active model bundle;
        falls back to the historical default if absent."""
        key = str(cutoff_hour)
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            cfg = (self.load_feature_model_hgb() or {}).get(key) or {}
        elif kind == "lr":
            cfg = (self.load_feature_model_coefs() or {}).get(key) or {}
        else:
            return default
        try:
            return float(cfg.get("blend_weight", default))
        except (TypeError, ValueError):
            return default

    def feature_ordinal_smoothing_config(self, cutoff_hour):
        """Artifact-driven ordinal smoothing config for feature-model serving.

        Older artifacts were tuned on the raw temperature-scaled HGB/LR
        distribution, so absence of this config must mean "disabled" rather than
        the old serving-only 50% smoothing layer.
        """
        key = str(cutoff_hour)
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            cfg = (self.load_feature_model_hgb() or {}).get(key) or {}
        elif kind == "lr":
            cfg = (self.load_feature_model_coefs() or {}).get(key) or {}
        else:
            cfg = {}
        smoothing = cfg.get("ordinal_smoothing") if isinstance(cfg, dict) else {}
        smoothing = smoothing if isinstance(smoothing, dict) else {}
        enabled = bool(smoothing.get("enabled", False))
        try:
            sigma = float(smoothing.get("sigma", 0.0))
            blend_weight = float(smoothing.get("blend_weight", 0.0))
        except (TypeError, ValueError):
            sigma = 0.0
            blend_weight = 0.0
        enabled = enabled and sigma > 0.0 and blend_weight > 0.0
        return {
            "enabled": enabled,
            "sigma": sigma if enabled else 0.0,
            "blend_weight": blend_weight if enabled else 0.0,
            "source": "artifact" if smoothing else "artifact_absent",
        }

    def resolve_forecast_high(self, open_meteo, weather_forecast, eccc_city):
        """Forecasted daily max for the feature model: the MEDIAN of the
        available forecast sources' daily-max values.

        The feature's definition is "median of available sources". The
        historical training archive contains exactly one source (Open-Meteo),
        and the median of one value is that value -- so the training-side
        construction is unchanged and the checked-in artifacts already match
        this definition. Live, the median spans Open-Meteo, the disabled
        paid-provider forecast family, and
        ECCC, so no single busted source can own the feature: the 2026-06-09
        ablation replays measured Open-Meteo-first at ~zero net value (hurt 22
        of 51 days) because its stale-forecast tail (NYC 6/8, Seattle and
        Toronto 6/9) cancelled its good days, while the median is robust to
        exactly that failure.
        """
        values = []
        day_max = self.forecast_day_max(open_meteo)
        if day_max is not None:
            values.append(("open_meteo", day_max))
        weather_com = self.max_row_temp(weather_forecast.get("rows"))
        if weather_com is not None:
            values.append(("weather_forecast", weather_com))
        eccc_high = self.row_forecast_high_native(eccc_city)
        if eccc_high is not None:
            values.append(("eccc_citypage", eccc_high))
        if not values:
            return None, "none"
        if len(values) == 1:
            return values[0][1], values[0][0]
        return (
            statistics.median(value for _, value in values),
            f"median_of_{len(values)}",
        )

    def guidance_physical_margin(self):
        return max(0.1, self.spec.scale_delta(0.5))

    def guidance_physical_floor(
        self,
        *,
        high_so_far=None,
        current_temp=None,
        live_reading=None,
        current_max=None,
        sources=None,
    ):
        candidates = [
            self.to_number(high_so_far),
            self.to_number(current_temp),
            self.to_number(live_reading),
            self.to_number(current_max),
        ]
        if sources:
            for source in ("wu_history", "wu_current", "metar", "eccc_swob"):
                data = self.source_data(sources, source)
                if not data:
                    continue
                candidates.extend([
                    self.row_temp_native(data),
                    self.row_max_native(data),
                    self.row_same_day_max_native(data),
                    self.row_air_temp_native(data.get("latest") or {}),
                ])
                rows = data.get("rows") or []
                if rows:
                    candidates.append(self.max_row_temp(rows))
        candidates = [value for value in candidates if value is not None]
        return max(candidates) if candidates else None

    def guidance_physical_state(
        self,
        source,
        representative_high,
        observed_floor_native,
        feature_values=None,
    ):
        observed_floor_native = self.to_number(observed_floor_native)
        cleaned = {
            name: self.to_number(value)
            for name, value in (feature_values or {}).items()
            if name and self.to_number(value) is not None
        }
        representative_high = self.to_number(representative_high)
        if representative_high is None and cleaned:
            representative_high = max(cleaned.values())
        floor_gap = (
            representative_high - observed_floor_native
            if representative_high is not None and observed_floor_native is not None
            else None
        )
        margin = self.guidance_physical_margin()
        impossible_features = []
        if observed_floor_native is not None:
            impossible_features = sorted(
                name
                for name, value in cleaned.items()
                if value < observed_floor_native - margin
            )
        representative_impossible = (
            floor_gap is not None
            and floor_gap < -margin
        )
        if representative_high is None:
            status = "missing_guidance_value"
        elif representative_impossible or (
            impossible_features and len(impossible_features) == len(cleaned)
        ):
            status = "fresh_but_impossible"
        elif impossible_features:
            status = "fresh_but_partially_impossible"
        else:
            status = "valid"
        return {
            "physical_validity_status": status,
            "representative_high": representative_high,
            "observed_floor": observed_floor_native,
            "floor_gap": floor_gap,
            "impossible_feature_count": len(impossible_features),
            "impossible_features": impossible_features,
            "reason": (
                f"{source}_guidance_below_observed_floor"
                if status.startswith("fresh_but")
                else ""
            ),
        }

    def guidance_physical_states(self, sources, observed_floor_native=None):
        sources = sources or {}
        if observed_floor_native is None:
            observed_floor_native = self.guidance_physical_floor(sources=sources)
        states = {}
        for source, feature_name in (
            ("open_meteo", "forecast_high"),
            ("weather_forecast", "forecast_high"),
            ("eccc_citypage", "forecast_high"),
            ("nws_hourly", "forecast_high"),
            ("global_ensemble", "forecast_high"),
            ("open_meteo_global_models", "forecast_high"),
            ("nws_grid", "nws_grid_high"),
        ):
            data = self.source_data(sources, source)
            if not data:
                continue
            value = self.forecast_day_max(data)
            if source == "weather_forecast":
                value = self.max_row_temp(data.get("rows"))
            elif source == "eccc_citypage":
                value = self.row_forecast_high_native(data)
            states[source] = self.guidance_physical_state(
                source,
                value,
                observed_floor_native,
                {feature_name: value},
            )
        nbm = self.source_data(sources, "nbm_probabilistic_tmax")
        if nbm:
            percentiles = nbm.get("percentiles") or {}
            feature_values = {
                f"nbm_prob_tmax_p{percentile}": row_value(percentiles, str(percentile), percentile)
                for percentile in (10, 25, 50, 75, 90)
            }
            feature_values["nbm_prob_tmax_mean"] = row_value(
                nbm,
                "mean_native",
                "day_max_native",
                "day_max_c",
            )
            representative = (
                feature_values.get("nbm_prob_tmax_p90")
                or feature_values.get("nbm_prob_tmax_mean")
                or feature_values.get("nbm_prob_tmax_p50")
            )
            states["nbm_probabilistic_tmax"] = self.guidance_physical_state(
                "nbm_probabilistic_tmax",
                representative,
                observed_floor_native,
                feature_values,
            )
        return states

    def forecast_ensemble_metrics(
        self,
        open_meteo,
        weather_forecast,
        eccc_city,
        nws_hourly=None,
        global_ensemble=None,
        open_meteo_global_models=None,
        observed_floor_native=None,
    ):
        values = []
        raw_source_values = {}
        impossible_sources = []
        impossible_features = []

        def add_value(source, value):
            value = self.to_number(value)
            if value is None:
                return
            raw_source_values[source] = value
            state = self.guidance_physical_state(
                source,
                value,
                observed_floor_native,
                {"forecast_high": value},
            )
            if state.get("physical_validity_status") == "fresh_but_impossible":
                impossible_sources.append(source)
                impossible_features.extend(state.get("impossible_features") or [])
                return
            values.append((source, value))

        day_max = self.forecast_day_max(open_meteo)
        if day_max is not None:
            add_value("open_meteo", day_max)
        weather_com = self.max_row_temp(weather_forecast.get("rows"))
        if weather_com is not None:
            add_value("weather_forecast", weather_com)
        eccc_high = self.row_forecast_high_native(eccc_city)
        if eccc_high is not None:
            add_value("eccc_citypage", eccc_high)
        nws_high = self.forecast_day_max(nws_hourly or {})
        if nws_high is not None:
            add_value("nws_hourly", nws_high)
        global_high = self.forecast_day_max(global_ensemble or {})
        if global_high is not None:
            add_value("global_ensemble", global_high)
        global_model_high = self.forecast_day_max(open_meteo_global_models or {})
        if global_model_high is not None:
            add_value("open_meteo_global_models", global_model_high)
        if not values:
            return {
                "forecast_high": None,
                "forecast_source": "none",
                "forecast_source_count": 0,
                "forecast_disagreement": None,
                "forecast_robust_high": None,
                "forecast_trimmed_high": None,
                "forecast_warm_outlier_flag": 0.0,
                "forecast_warm_outlier_gap": None,
                "forecast_source_family_count": 0,
                "forecast_source_values": {},
                "forecast_raw_source_values": raw_source_values,
                "forecast_raw_max": max(raw_source_values.values()) if raw_source_values else None,
                "forecast_impossible_sources": impossible_sources,
                "forecast_impossible_features": sorted(set(impossible_features)),
                "guidance_physical_floor": observed_floor_native,
            }
        highs = [value for _, value in values]
        sorted_highs = sorted(highs)
        median_high = statistics.median(sorted_highs)
        if len(sorted_highs) >= 3:
            trimmed_values = sorted_highs[1:-1] or sorted_highs
            trimmed_high = statistics.mean(trimmed_values)
        else:
            trimmed_high = median_high
        max_high = max(sorted_highs)
        second_high = sorted_highs[-2] if len(sorted_highs) >= 2 else max_high
        warm_outlier_gap = max_high - median_high if sorted_highs else None
        warm_outlier_gap_threshold = self.spec.scale_delta(3.0)
        isolated_high_threshold = self.spec.scale_delta(1.5)
        warm_outlier_flag = bool(
            len(sorted_highs) >= 3
            and warm_outlier_gap is not None
            and warm_outlier_gap >= warm_outlier_gap_threshold
            and max_high - second_high >= isolated_high_threshold
        )
        source = values[0][0] if len(values) == 1 else f"median_of_{len(values)}"
        return {
            "forecast_high": median_high,
            "forecast_source": source,
            "forecast_source_count": len(values),
            # With one source there is no observed cross-source disagreement;
            # zero would falsely assert agreement rather than missing support.
            "forecast_disagreement": max(highs) - min(highs) if len(highs) >= 2 else None,
            "forecast_robust_high": trimmed_high if warm_outlier_flag else median_high,
            "forecast_trimmed_high": trimmed_high,
            "forecast_warm_outlier_flag": 1.0 if warm_outlier_flag else 0.0,
            "forecast_warm_outlier_gap": warm_outlier_gap,
            "forecast_source_family_count": len(values),
            "forecast_source_values": {name: value for name, value in values},
            "forecast_raw_source_values": raw_source_values,
            "forecast_raw_max": max(raw_source_values.values()) if raw_source_values else None,
            "forecast_impossible_sources": impossible_sources,
            "forecast_impossible_features": sorted(set(impossible_features)),
            "guidance_physical_floor": observed_floor_native,
        }

    def us_guidance_features(
        self,
        nws_grid=None,
        nbm_probabilistic_tmax=None,
        open_meteo_multimodel=None,
        open_meteo_global_models=None,
        forecast_high=None,
        cutoff_hour=None,
        wall_minute=None,
        observed_floor_native=None,
    ):
        features = empty_us_guidance_features()
        impossible_sources = []
        impossible_features = []
        cutoff_minute = int(cutoff_hour) * 60 if cutoff_hour is not None else 0
        remaining_start = max(int(wall_minute), cutoff_minute) if wall_minute is not None else cutoff_minute

        nws_grid = nws_grid or {}
        nws_high = self.forecast_day_max(nws_grid)
        nws_state = self.guidance_physical_state(
            "nws_grid",
            nws_high,
            observed_floor_native,
            {"nws_grid_high": nws_high},
        )
        if nws_state.get("physical_validity_status") == "fresh_but_impossible":
            impossible_sources.append("nws_grid")
            impossible_features.extend(nws_state.get("impossible_features") or [])
        else:
            features["nws_grid_high"] = nws_high
        if features.get("nws_grid_high") is not None and forecast_high is not None:
            features["nws_grid_vs_forecast_high"] = nws_high - forecast_high
        remaining_rows = [
            row for row in (nws_grid.get("day_rows") or nws_grid.get("rows") or [])
            for minute in [self.minute_of_day(row.get("time") or row.get("valid_time"))]
            if minute is not None and minute >= remaining_start
        ]
        pop_values = [
            row_value(row, "precipitation_probability")
            for row in remaining_rows
            if row_value(row, "precipitation_probability") is not None
        ]
        if pop_values:
            features["nws_grid_pop_after_cutoff_max"] = max(pop_values)
        qpf_values = [
            row_value(row, "quantitative_precipitation")
            for row in remaining_rows
            if row_value(row, "quantitative_precipitation") is not None
        ]
        if qpf_values:
            features["nws_grid_qpf_after_cutoff_sum"] = sum(qpf_values)
        sky_values = [
            row_value(row, "sky_cover", "cloud_cover")
            for row in remaining_rows
            if row_value(row, "sky_cover", "cloud_cover") is not None
        ]
        if sky_values:
            features["nws_grid_sky_cover_after_cutoff_mean"] = sum(sky_values) / len(sky_values)
        hazard_counts = [
            row_value(row, "hazards_count")
            for row in remaining_rows
            if row_value(row, "hazards_count") is not None
        ]
        if hazard_counts:
            features["nws_grid_hazard_count"] = sum(hazard_counts)
        run_age = row_value(nws_grid, "run_age_hours", "model_run_age_hours")
        if run_age is not None:
            features["nws_grid_run_age_hours"] = run_age

        nbm_prob = nbm_probabilistic_tmax or {}
        percentiles = nbm_prob.get("percentiles") or {}
        nbm_feature_values = {
            f"nbm_prob_tmax_p{percentile}": row_value(percentiles, str(percentile), percentile)
            for percentile in (10, 25, 50, 75, 90)
        }
        nbm_feature_values["nbm_prob_tmax_mean"] = row_value(
            nbm_prob,
            "mean_native",
            "day_max_native",
            "day_max_c",
        )
        nbm_representative = (
            nbm_feature_values.get("nbm_prob_tmax_p90")
            or nbm_feature_values.get("nbm_prob_tmax_mean")
            or nbm_feature_values.get("nbm_prob_tmax_p50")
        )
        nbm_state = self.guidance_physical_state(
            "nbm_probabilistic_tmax",
            nbm_representative,
            observed_floor_native,
            nbm_feature_values,
        )
        nbm_present = bool(nbm_prob)
        if nbm_present:
            valid = nbm_state.get("physical_validity_status") == "valid"
            features["nbm_prob_tmax_physical_valid_flag"] = 1.0 if valid else 0.0
            features["nbm_prob_tmax_impossible_flag"] = 0.0 if valid else 1.0
            features["nbm_prob_tmax_floor_gap"] = nbm_state.get("floor_gap")
            if not valid:
                impossible_sources.append("nbm_probabilistic_tmax")
                impossible_features.extend(nbm_state.get("impossible_features") or [])
        nbm_impossible_features = set(nbm_state.get("impossible_features") or [])
        for percentile in (10, 25, 50, 75, 90):
            key = f"nbm_prob_tmax_p{percentile}"
            value = nbm_feature_values.get(key)
            if value is not None and key not in nbm_impossible_features:
                features[key] = value
        mean_native = nbm_feature_values.get("nbm_prob_tmax_mean")
        stddev_native = row_value(nbm_prob, "stddev_native")
        if mean_native is not None and "nbm_prob_tmax_mean" not in nbm_impossible_features:
            features["nbm_prob_tmax_mean"] = mean_native
        if stddev_native is not None:
            features["nbm_prob_tmax_stddev"] = stddev_native
        p10 = features.get("nbm_prob_tmax_p10")
        p25 = features.get("nbm_prob_tmax_p25")
        p50 = features.get("nbm_prob_tmax_p50")
        p75 = features.get("nbm_prob_tmax_p75")
        p90 = features.get("nbm_prob_tmax_p90")
        iqr = row_value(nbm_prob, "iqr")
        spread = row_value(nbm_prob, "p10_p90_spread")
        if iqr is None and p25 is not None and p75 is not None:
            iqr = p75 - p25
        if spread is None and p10 is not None and p90 is not None:
            spread = p90 - p10
        if iqr is not None:
            features["nbm_prob_tmax_iqr"] = iqr
        if spread is not None:
            features["nbm_prob_tmax_p10_p90_spread"] = spread
        if forecast_high is not None:
            if p50 is not None:
                features["nbm_prob_tmax_p50_vs_forecast_high"] = p50 - forecast_high
            if p90 is not None:
                features["nbm_prob_tmax_p90_vs_forecast_high"] = p90 - forecast_high
            usable_percentiles = {
                key: value
                for key, value in (percentiles or {}).items()
                if f"nbm_prob_tmax_p{key}" not in nbm_impossible_features
            }
            exceedance = exceedance_probability_from_percentiles(usable_percentiles, forecast_high)
            if exceedance is not None:
                features["nbm_prob_tmax_exceed_forecast_high"] = exceedance

        multimodel = open_meteo_multimodel or {}
        highs = multimodel.get("day_model_highs") or {}
        high_values = [value for value in highs.values() if value is not None]
        if len(high_values) >= 2:
            features["open_meteo_multimodel_high_spread"] = max(high_values) - min(high_values)
        model_aliases = {
            "gfs": "gfs_seamless",
            "hrrr": "ncep_hrrr_conus",
            "nbm": "ncep_nbm_conus",
            "nam": "ncep_nam_conus",
        }
        reference_high = forecast_high if forecast_high is not None else (
            statistics.median(high_values) if high_values else None
        )
        for alias, model_name in model_aliases.items():
            high = highs.get(model_name)
            if high is not None and reference_high is not None:
                features[f"open_meteo_{alias}_high_delta"] = high - reference_high
        nbm_high = highs.get("ncep_nbm_conus")
        hrrr_high = highs.get("ncep_hrrr_conus")
        if nbm_high is not None and hrrr_high is not None:
            features["open_meteo_nbm_hrrr_disagreement"] = abs(nbm_high - hrrr_high)
        run_age = row_value(multimodel, "model_run_age_hours", "run_age_hours")
        if run_age is not None:
            features["open_meteo_multimodel_run_age_hours"] = run_age
        run_change = row_value(multimodel, "run_to_run_high_change")
        previous_highs = multimodel.get("previous_day_model_highs") or {}
        previous_values = [value for value in previous_highs.values() if value is not None]
        if run_change is None and high_values and previous_values:
            run_change = statistics.median(high_values) - statistics.median(previous_values)
        if run_change is not None:
            features["open_meteo_multimodel_run_to_run_high_change"] = run_change

        next_spreads = []
        nbm_hrrr_diffs_after_cutoff = []
        for row in multimodel.get("day_rows") or multimodel.get("rows") or []:
            minute = self.minute_of_day(row.get("time") or row.get("valid_time"))
            if minute is None or minute < remaining_start:
                continue
            models = row.get("models") or {}
            nbm = row_value(models.get("ncep_nbm_conus"), "temp_native", "temp_c")
            hrrr = row_value(models.get("ncep_hrrr_conus"), "temp_native", "temp_c")
            if nbm is not None and hrrr is not None:
                nbm_hrrr_diffs_after_cutoff.append(abs(nbm - hrrr))
            if minute >= remaining_start + 180:
                continue
            model_values = [
                (payload or {}).get("temp_native")
                for payload in models.values()
            ]
            model_values = [value for value in model_values if value is not None]
            if len(model_values) >= 2:
                next_spreads.append(max(model_values) - min(model_values))
        if next_spreads:
            features["open_meteo_multimodel_next_3h_spread"] = sum(next_spreads) / len(next_spreads)
        if nbm_hrrr_diffs_after_cutoff:
            features["open_meteo_nbm_hrrr_disagreement_after_cutoff"] = max(nbm_hrrr_diffs_after_cutoff)

        global_models = open_meteo_global_models or {}
        global_highs = global_models.get("day_model_highs") or {}
        global_high_values = [value for value in global_highs.values() if value is not None]
        if len(global_high_values) >= 2:
            features["open_meteo_global_models_high_spread"] = max(global_high_values) - min(global_high_values)
        global_reference_high = forecast_high if forecast_high is not None else (
            statistics.median(global_high_values) if global_high_values else None
        )
        global_aliases = {
            "ecmwf_ifs": "ecmwf_ifs025",
            "ecmwf_aifs": "ecmwf_aifs025",
            "ncep_aigfs": "ncep_aigfs025",
            "gfs_graphcast": "gfs_graphcast025",
        }
        for alias, model_name in global_aliases.items():
            high = global_highs.get(model_name)
            if high is not None and global_reference_high is not None:
                features[f"open_meteo_{alias}_high_delta"] = high - global_reference_high
        ifs_high = global_highs.get("ecmwf_ifs025")
        aifs_high = global_highs.get("ecmwf_aifs025")
        if ifs_high is not None and aifs_high is not None:
            features["open_meteo_ecmwf_ifs_aifs_disagreement"] = abs(ifs_high - aifs_high)
        global_previous_highs = global_models.get("previous_day_model_highs") or {}
        global_previous_values = [value for value in global_previous_highs.values() if value is not None]
        global_run_change = row_value(global_models, "run_to_run_high_change")
        if global_run_change is None and global_high_values and global_previous_values:
            global_run_change = statistics.median(global_high_values) - statistics.median(global_previous_values)
        if global_run_change is not None:
            features["open_meteo_global_models_run_to_run_high_change"] = global_run_change

        global_next_spreads = []
        for row in global_models.get("day_rows") or global_models.get("rows") or []:
            minute = self.minute_of_day(row.get("time") or row.get("valid_time"))
            if minute is None or minute < remaining_start or minute >= remaining_start + 180:
                continue
            model_values = [
                (payload or {}).get("temp_native")
                for payload in (row.get("models") or {}).values()
            ]
            model_values = [value for value in model_values if value is not None]
            if len(model_values) >= 2:
                global_next_spreads.append(max(model_values) - min(model_values))
        if global_next_spreads:
            features["open_meteo_global_models_next_3h_spread"] = sum(global_next_spreads) / len(global_next_spreads)
        features["_guidance_impossible_sources"] = sorted(set(impossible_sources))
        features["_guidance_impossible_features"] = sorted(set(impossible_features))
        return features

    def marine_context_features(
        self,
        marine_context=None,
        current_temp_native=None,
        forecast_high_native=None,
        cutoff_hour=None,
        wall_minute=None,
    ):
        if not marine_context:
            return empty_marine_context_features()
        return derive_marine_context_features(
            marine_context,
            current_temp_native=current_temp_native,
            forecast_high_native=forecast_high_native,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
        )

    def mrms_precip_features(
        self,
        mrms_precip=None,
        cutoff_hour=None,
        wall_minute=None,
        forecast_profile=None,
        warming_rate_2h=None,
    ):
        if not mrms_precip:
            return empty_mrms_precip_features()
        forecast_profile = forecast_profile or {}
        return derive_mrms_precip_features(
            mrms_precip,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
            forecast_next_3h_cape_max=forecast_profile.get("forecast_next_3h_cape_max"),
            forecast_next_3h_precip_probability_max=forecast_profile.get(
                "forecast_next_3h_precipitation_probability_max"
            ),
            warming_rate_2h=warming_rate_2h,
        )

    def eccc_gridded_features(
        self,
        eccc_gem=None,
        forecast_high=None,
        open_meteo_high=None,
        weather_high=None,
        eccc_city_high=None,
        cutoff_hour=None,
        wall_minute=None,
    ):
        if not eccc_gem:
            return empty_eccc_gridded_features()
        return derive_eccc_gridded_features(
            eccc_gem,
            forecast_high=forecast_high,
            open_meteo_high=open_meteo_high,
            weather_high=weather_high,
            eccc_city_high=eccc_city_high,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
        )

    def extract_live_features(self, sources, cutoff_hour, now=None, strict=False):
        """Build the cutoff-aligned feature vector shared by the feature model
        (HGB/LR) and the late-day continuation model.

        Both models were trained on the same fields, so they must extract them
        identically at inference time to avoid train/serve skew. This is the
        single source of truth for that extraction; callers add any model-
        specific features (e.g. late-day ``time_since_reached``) on top.

        ``now`` powers the v0.3 intra-hour freshness features (item 40):
        minutes elapsed past the printed cutoff plus the live wu_current
        reading, modeled explicitly instead of fabricated into history rows.
        Without ``now`` they degrade to the at-print state (0 elapsed).

        ``strict`` is used by analog search: it returns ``None`` when required
        cutoff-aligned fields are unavailable. Non-strict serving keeps missing
        numeric values as ``None`` so trained imputers/native-NaN handling see
        the same missingness they saw during training.
        """
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        station_method = getattr(self, "station_observation_data", None)
        station = (
            station_method(sources)
            if callable(station_method)
            else self.source_data(sources, "station_observations")
        )
        weather_forecast = self.source_data(sources, "weather_forecast")
        eccc_city = self.source_data(sources, "eccc_citypage")

        rows = history.get("rows") or []
        latest_wu_history_row, latest_wu_history_minute = self.latest_source_row(rows)
        feature_rows = self.source_rows_until_cutoff(rows, cutoff_hour)
        feature_latest = feature_rows[-1] if feature_rows else None
        wu_current_temp = self.row_temp_native(current)
        station_current_temp = self.row_temp_native(station)
        live_observation_temp = wu_current_temp if wu_current_temp is not None else station_current_temp
        current_max = self.row_max_since_7am_native(current)
        if current_max is None:
            current_max = self.row_max_since_7am_native(station)

        # high_so_far
        history_high_for_trust = self.cutoff_aligned_wu_history_max_native(
            history,
            cutoff_hour,
        )
        current_temp = self.row_temp_native(feature_latest) if feature_latest else live_observation_temp
        high_so_far = history_high_for_trust

        # current_temp
        if current_temp is None:
            current_temp = live_observation_temp
        if current_temp is None and strict:
            return None
        if current_temp is None:
            current_temp = self.row_temp_native(rows[-1]) if rows else None
        high_so_far = self.max_value(high_so_far, current_temp)
        # Station max_since_7am covers 7:00 through NOW, so folding it into
        # high_so_far when printed rows exist would leak post-cutoff readings
        # the training path excludes (train/serve skew). It may only rescue
        # high_so_far when the printed path is empty; with printed history the
        # signal belongs to current_max_trust_features instead.
        if history_high_for_trust is None and cutoff_hour >= 7 and current_max is not None:
            high_so_far = self.max_value(high_so_far, current_max)
        startup_guard = startup_observation_guard_features(
            high_so_far=high_so_far,
            current_temp=current_temp,
            live_reading_temp=live_observation_temp,
            unit=self.spec.display_unit,
        )
        if startup_guard.get("startup_feature_quarantined_flag"):
            high_so_far = None
            current_temp = None
            if strict:
                return None
        if high_so_far is None and strict:
            return None

        # rise_from_7am
        obs_7am_candidates = [r for r in rows if r.get("time") and 360 <= self.minute_of_day(r["time"]) <= 480 and self.row_temp_native(r) is not None]
        temp_7am = None
        if obs_7am_candidates:
            closest_7am = min(obs_7am_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - 420))
            temp_7am = self.row_temp_native(closest_7am)
        if temp_7am is None and strict:
            return None
        rise_from_7am = (
            current_temp - temp_7am
            if current_temp is not None and temp_7am is not None
            else None
        )

        # warming_rate_2h
        cutoff_minutes = cutoff_hour * 60
        obs_2h_candidates = [r for r in rows if r.get("time") and (cutoff_minutes - 180) <= self.minute_of_day(r["time"]) <= (cutoff_minutes - 60) and self.row_temp_native(r) is not None]
        temp_2h_ago = None
        if obs_2h_candidates:
            closest_2h = min(obs_2h_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - (cutoff_minutes - 120)))
            temp_2h_ago = self.row_temp_native(closest_2h)
        warming_rate_2h = (
            current_temp - temp_2h_ago
            if current_temp is not None and temp_2h_ago is not None
            else None
        )

        # hours_at_peak
        first_reached_min = None
        for r in feature_rows:
            if self.row_temp_native(r) == high_so_far and r.get("time"):
                first_reached_min = self.minute_of_day(r["time"])
                break
        hours_at_peak = (
            ((cutoff_minutes - first_reached_min) / 60.0)
            if first_reached_min is not None
            else None
        )

        # dewpoint_c, humidity, pressure
        dewpoint = self.row_dewpoint_native(feature_latest) if feature_latest else self.row_dewpoint_native(current)
        if dewpoint is None and strict:
            return None
        if dewpoint is None:
            dewpoint = self.row_dewpoint_native(rows[-1]) if rows else None
        humidity = feature_latest.get("humidity") if feature_latest else current.get("humidity")
        if humidity is None:
            humidity = rows[-1].get("humidity") if rows else None
        pressure = feature_latest.get("pressure") if feature_latest else current.get("pressure")
        if pressure is None:
            pressures = [r["pressure"] for r in rows if r.get("pressure") is not None]
            pressure = pressures[-1] if pressures else None

        # pressure_trend_3h
        obs_3h_candidates = [r for r in rows if r.get("time") and (cutoff_minutes - 240) <= self.minute_of_day(r["time"]) <= (cutoff_minutes - 120) and r.get("pressure") is not None]
        pressure_trend_3h = None
        if pressure is not None and obs_3h_candidates:
            closest_3h = min(obs_3h_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - (cutoff_minutes - 180)))
            press_3h_ago = closest_3h["pressure"]
            pressure_trend_3h = pressure - press_3h_ago

        # wind_speed_kmh
        wind_speed = feature_latest.get("wind_kmh") if feature_latest else current.get("wind_kmh")
        if wind_speed is None:
            wind_speed = rows[-1].get("wind_kmh") if rows else None
        wind_gust = (
            feature_latest.get("gust_kmh")
            if feature_latest else row_value(current, "gust_kmh", "wind_gust_kmh", "wind_gust")
        )
        if wind_gust is None and rows:
            wind_gust = row_value(rows[-1], "gust_kmh", "wind_gust_kmh", "wind_gust")
        wind_shift_3h = wind_direction_delta_degrees(
            row_wind_direction(feature_latest or current),
            closest_wind_direction(rows, cutoff_minutes - 180, 60),
        )

        # wind_group and cloud_group
        wind_group = (
            self.wind_group(feature_latest.get("wind")) if feature_latest else None
        ) or self.live_wind_group(current, weather_forecast)
        cloud_group = (
            self.cloud_group(feature_latest.get("condition"), feature_latest.get("clouds"))
            if feature_latest else None
        ) or self.live_cloud_group(current, eccc_city, weather_forecast)
        if strict and (wind_group is None or cloud_group is None):
            return None
        microclimate = self.microclimate_features(wind_group, wind_speed)

        # Forecast features: forecasted daily max (matching the archived-forecast
        # training value) and the gap above the high so far. Open-Meteo is the
        # canonical source, but when it is unavailable we fall back to the other
        # live forecasts instead of going forecast-blind (which leaves the model
        # anchored to a modest morning high-so-far). See resolve_forecast_high.
        open_meteo = self.source_data(sources, "open_meteo")
        open_meteo_air_quality = self.source_data(sources, "open_meteo_air_quality")
        open_meteo_global_models = self.source_data(sources, "open_meteo_global_models")
        nws_hourly = self.source_data(sources, "nws_hourly")
        nws_grid = self.source_data(sources, "nws_grid")
        nbm_probabilistic_tmax = self.source_data(sources, "nbm_probabilistic_tmax")
        open_meteo_multimodel = self.source_data(sources, "open_meteo_multimodel")
        global_ensemble = self.source_data(sources, "global_ensemble")
        marine_context_source = self.source_data(sources, "marine_context")
        mrms_precip_source = self.source_data(sources, "mrms_precip")
        eccc_gem = self.source_data(sources, "eccc_gem")
        live_reading = live_observation_temp
        if startup_guard.get("startup_feature_quarantined_flag"):
            live_reading = None
        guidance_floor = self.guidance_physical_floor(
            high_so_far=high_so_far,
            current_temp=current_temp,
            live_reading=live_reading,
            sources=sources,
        )
        forecast_ensemble = self.forecast_ensemble_metrics(
            open_meteo,
            weather_forecast,
            eccc_city,
            nws_hourly=nws_hourly,
            global_ensemble=global_ensemble,
            open_meteo_global_models=open_meteo_global_models,
            observed_floor_native=guidance_floor,
        )
        forecast_high = forecast_ensemble["forecast_high"]
        forecast_gap = (
            forecast_high - high_so_far
            if forecast_high is not None and high_so_far is not None
            else None
        )
        open_meteo_high = self.forecast_day_max(open_meteo)
        weather_high = self.max_row_temp(weather_forecast.get("rows"))
        eccc_city_high = self.row_forecast_high_native(eccc_city)

        # Intra-hour freshness (schema v0.3): the live wu_current reading and
        # the minutes elapsed since the printed cutoff, as explicit features.
        # The printed path above stays <= the cutoff; a missing reading stays
        # None (native NaN for the HGB).
        minutes_since_cutoff = 0.0
        if now is not None:
            try:
                minutes_since_cutoff = float(
                    max(0, now.hour * 60 + now.minute - cutoff_hour * 60)
                )
            except (AttributeError, TypeError):
                minutes_since_cutoff = 0.0
        wall_minute = int(cutoff_hour * 60 + minutes_since_cutoff)
        current_max_features = current_max_trust_features(
            current_max,
            history_max=history_high_for_trust,
            current_temp=current_temp,
            cutoff_hour=cutoff_hour,
            unit=self.spec.display_unit,
        )
        live_reading_minus_high = (
            live_reading - high_so_far
            if live_reading is not None and high_so_far is not None
            else None
        )
        open_meteo_profile_rows = merge_forecast_air_quality_rows(
            open_meteo.get("day_rows") or open_meteo.get("rows"),
            open_meteo_air_quality.get("day_rows") or open_meteo_air_quality.get("rows"),
        )
        forecast_profile = forecast_profile_features(
            open_meteo_profile_rows,
            cutoff_hour,
            high_so_far=high_so_far,
            wall_minute=wall_minute,
            ensemble_rows=global_ensemble.get("day_rows") or global_ensemble.get("rows"),
            ensemble_day_mean_spread=global_ensemble.get("day_mean_member_spread"),
            ensemble_day_high_p10=global_ensemble.get("day_member_high_p10"),
            ensemble_day_high_p90=global_ensemble.get("day_member_high_p90"),
        )
        us_guidance = self.us_guidance_features(
            nws_grid=nws_grid,
            nbm_probabilistic_tmax=nbm_probabilistic_tmax,
            open_meteo_multimodel=open_meteo_multimodel,
            open_meteo_global_models=open_meteo_global_models,
            forecast_high=forecast_high,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
            observed_floor_native=guidance_floor,
        )
        us_guidance_impossible_sources = us_guidance.pop("_guidance_impossible_sources", [])
        us_guidance_impossible_features = us_guidance.pop("_guidance_impossible_features", [])
        guidance_states = self.guidance_physical_states(
            sources,
            observed_floor_native=guidance_floor,
        )
        guidance_impossible_sources = sorted(set(
            list(forecast_ensemble.get("forecast_impossible_sources") or [])
            + list(us_guidance_impossible_sources or [])
            + [
                source
                for source, state in guidance_states.items()
                if str(state.get("physical_validity_status") or "").startswith("fresh_but")
            ]
        ))
        guidance_impossible_features = sorted(set(
            list(forecast_ensemble.get("forecast_impossible_features") or [])
            + list(us_guidance_impossible_features or [])
            + [
                feature
                for state in guidance_states.values()
                for feature in (state.get("impossible_features") or [])
            ]
        ))
        marine_context = self.marine_context_features(
            marine_context=marine_context_source,
            current_temp_native=current_temp,
            forecast_high_native=forecast_high,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
        )
        mrms_precip = self.mrms_precip_features(
            mrms_precip=mrms_precip_source,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
            forecast_profile=forecast_profile,
            warming_rate_2h=warming_rate_2h,
        )
        eccc_gridded = self.eccc_gridded_features(
            eccc_gem=eccc_gem,
            forecast_high=forecast_high,
            open_meteo_high=open_meteo_high,
            weather_high=weather_high,
            eccc_city_high=eccc_city_high,
            cutoff_hour=cutoff_hour,
            wall_minute=wall_minute,
        )

        return {
            "feature_rows": feature_rows,
            "feature_latest": feature_latest,
            "latest_wu_history_time": (
                latest_wu_history_row.get("time") if latest_wu_history_row else None
            ),
            "latest_wu_history_minute": latest_wu_history_minute,
            "latest_wu_history_temp": (
                self.row_temp_native(latest_wu_history_row) if latest_wu_history_row else None
            ),
            "high_so_far": high_so_far,
            "current_temp": current_temp,
            "rise_from_7am": rise_from_7am,
            "warming_rate_2h": warming_rate_2h,
            "hours_at_peak": hours_at_peak,
            "dewpoint_c": dewpoint,
            "humidity": humidity,
            "pressure": pressure,
            "pressure_trend_3h": pressure_trend_3h,
            "wind_speed_kmh": wind_speed,
            "wind_gust_kmh": wind_gust,
            "wind_shift_3h_degrees": wind_shift_3h,
            **microclimate,
            "wind_group": wind_group,
            "cloud_group": cloud_group,
            "forecast_high": forecast_high,
            "forecast_gap": forecast_gap,
            "forecast_source_count": forecast_ensemble["forecast_source_count"],
            "forecast_disagreement": forecast_ensemble["forecast_disagreement"],
            "forecast_robust_high": forecast_ensemble["forecast_robust_high"],
            "forecast_trimmed_high": forecast_ensemble["forecast_trimmed_high"],
            "forecast_warm_outlier_flag": forecast_ensemble["forecast_warm_outlier_flag"],
            "forecast_warm_outlier_gap": forecast_ensemble["forecast_warm_outlier_gap"],
            "forecast_source_family_count": forecast_ensemble["forecast_source_family_count"],
            "forecast_source_values": forecast_ensemble["forecast_source_values"],
            "guidance_physical_floor": guidance_floor,
            "guidance_impossible_source_count": len(guidance_impossible_sources),
            "guidance_impossible_sources": ",".join(guidance_impossible_sources),
            "guidance_impossible_features": ",".join(guidance_impossible_features),
            **forecast_profile,
            **us_guidance,
            **marine_context,
            **mrms_precip,
            **eccc_gridded,
            **empty_reanalysis_synoptic_features(),
            "minutes_since_cutoff": minutes_since_cutoff,
            "live_reading_temp": live_reading,
            "live_reading_minus_high": live_reading_minus_high,
            **current_max_features,
            **startup_guard,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        }

    def live_feature_record(self, sources, cutoff_hour, captured_at=None, model_version=None):
        return build_live_feature_record(
            getattr(self, "target_date", None),
            cutoff_hour,
            captured_at,
            model_version,
            self.extract_live_features(sources, cutoff_hour, now=captured_at),
        )

    def _evaluate_feature_model_for_cutoff(self, sources, cutoff_hour, hgb_bundle, lr_coefs, now=None):
        feats = self.extract_live_features(sources, cutoff_hour, now=now)
        wind_group = feats["wind_group"]
        cloud_group = feats["cloud_group"]

        # Check if HGBC is available (preferred)
        if hgb_bundle and str(cutoff_hour) in hgb_bundle:
            try:
                self._last_weak_input_family_preflight = deepcopy(
                    (hgb_bundle or {}).get("weak_input_family_preflight") or {}
                )
                bundle = hgb_bundle[str(cutoff_hour)]
                if not self._last_weak_input_family_preflight:
                    self._last_weak_input_family_preflight = deepcopy(
                        (bundle or {}).get("weak_input_family_preflight") or {}
                    )
                model_obj = bundle["model"]
                imputer_obj = bundle["imputer"]
                all_wind = bundle["all_wind_groups"]
                all_cloud = bundle["all_cloud_groups"]
                
                # Build feature dictionary. Keys absent from the bundle's
                # feature_names (e.g. v0.3 freshness features against a v0.2
                # artifact) are simply not selected, so old artifacts keep
                # serving unchanged.
                feat_dict = {
                    column: feats.get(column)
                    for column in FEATURE_COLUMNS
                    if column not in {"wind_group", "cloud_group"}
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

                # Restore native NaN for the forecast and live-reading columns
                # (the model was trained with them un-imputed): a present value
                # is used, a missing one stays NaN for the tree to handle.
                fnames = list(bundle["feature_names"])
                for col in NATIVE_NAN_FEATURE_COLUMNS:
                    if col in fnames:
                        X_imputed[0, fnames.index(col)] = float(feat_dict[col]) if feat_dict[col] is not None else float("nan")

                # Predict probability distribution
                probs = model_obj.predict_proba(X_imputed)[0]
                classes = model_obj.classes_
                
                prob_dict = {int(c): float(p) for c, p in zip(classes, probs)}
                prob_dict = temperature_scale_distribution(
                    prob_dict,
                    bundle.get("probability_temperature", 1.0),
                )
                return prob_dict, "hgb"
            except Exception as e:
                logger.warning("Error predicting with HGBC model: %s. Falling back to LR coefficients...", e)
                
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
                
                # Build raw numeric feature vector (count comes from the scaler so
                # it tracks the trained feature set: a v0.2 artifact's 12-wide
                # scaler ignores the appended v0.3 freshness entries).
                n_num = len(scaler_mean)
                raw_vec = [feats.get(name) for name in feature_names[:n_num]]
                # Impute then scale the numeric elements.
                for i in range(n_num):
                    if raw_vec[i] is None:
                        raw_vec[i] = imputer_median[i]
                scaled_vec = [(raw_vec[i] - scaler_mean[i]) / scaler_scale[i] for i in range(n_num)]

                # Add one-hot encoded groups (after the numeric block)
                for name in feature_names[n_num:]:
                    if name.startswith("wind_"):
                        g = name[5:]
                        scaled_vec.append(1.0 if wind_group == g else 0.0)
                    elif name.startswith("cloud_"):
                        g = name[6:]
                        scaled_vec.append(1.0 if cloud_group == g else 0.0)
                    else:
                        scaled_vec.append(0.0)
                        
                # Compute logits: z_c = sum_j coef_{c, j} * x_j + intercept_c
                import math
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
                logger.warning("Error predicting with LR coefficients: %s. Falling back to empirical prior...", e)
                
        return None, "empirical"

    def predict_feature_distribution(self, sources, cutoff_hour, now, include_gate=False):
        """Evaluate the feature model at the printed cutoff. Intra-hour
        freshness is handled by the v0.3 trained features (minutes since the
        cutoff + the live reading) threaded through ``now`` -- NOT by
        evaluating the next hour's model on unprinted state (the removed
        interpolation path) or by fabricating history rows (the reverted
        v0.5.1 injection)."""
        gate = self.family_secondary_feature_model_gate()
        self._last_family_secondary_gate = deepcopy(gate)
        if gate.get("mode") != "ml":
            result = (None, "empirical")
            return (*result, gate) if include_gate else result
        hgb_bundle = self.load_feature_model_hgb()
        lr_coefs = self.load_feature_model_coefs()

        if not hgb_bundle and not lr_coefs:
            result = (None, "empirical")
            return (*result, gate) if include_gate else result

        result = self._evaluate_feature_model_for_cutoff(
            sources, cutoff_hour, hgb_bundle, lr_coefs, now=now
        )
        return (*result, gate) if include_gate else result

    def family_secondary_feature_model_gate(self):
        manifest = getattr(self, "family_secondary_artifacts", None)
        if not manifest:
            return {
                "mode": "ml",
                "reason": "no family secondary manifest",
            }
        if getattr(self.spec, "display_unit", None) != manifest.get("family_unit"):
            return {
                "mode": "ml",
                "reason": "market unit not governed by family secondary manifest",
            }
        market = (manifest.get("markets") or {}).get(self.market_id)
        if not market:
            return {
                "mode": (manifest.get("gate") or {}).get("default_mode", "empirical"),
                "reason": "market missing from family secondary manifest",
            }
        return market.get("serving_gate") or {
            "mode": "empirical",
            "reason": "missing serving gate",
        }

    def family_secondary_feature_model_allowed(self):
        gate = self.family_secondary_feature_model_gate()
        self._last_family_secondary_gate = deepcopy(gate)
        return gate.get("mode") == "ml"


    def bucket_transition_model(self, sources, now, min_sample_size=5):
        history = self.source_data(sources, "wu_history")
        cutoff_hour = self.effective_intraday_cutoff_hour(
            now,
            history.get("rows") or [],
        )
        observed_bucket = self.round_half_up(
            self.cutoff_aligned_wu_history_max_native(history, cutoff_hour)
        )

        if observed_bucket is None:
            return {
                "current_max_bucket": None,
                "observed_bucket": None,
                "cutoff_hour": cutoff_hour,
                "sample_size": 0,
                "probabilities": {},
                "skip_rate": 0.0,
                "update_rate": 0.0,
                "median_first_update_minute": None,
            }

        cache = self.historical_target_cache()
        daily = cache["daily"]
        by_date = cache["by_date"]

        cutoff = cutoff_hour * 60
        matching_final_buckets = []
        first_update_minutes = []

        for local_date, daily_info in daily.items():
            rows = by_date.get(local_date, [])
            high_so_far = self.historical_max_until(rows, cutoff)
            if high_so_far is None:
                continue
            bucket_so_far = self.round_half_up(high_so_far)
            if bucket_so_far == observed_bucket:
                final_bucket = daily_info["bucket"]
                matching_final_buckets.append(final_bucket)
                if final_bucket > observed_bucket:
                    for row in sorted(rows, key=lambda item: item.get("minute_of_day") or 0):
                        minute = row.get("minute_of_day")
                        if minute is None or minute <= cutoff:
                            continue
                        bucket = self.round_half_up(self.row_temp_native(row))
                        if bucket is not None and bucket > observed_bucket:
                            first_update_minutes.append(int(minute))
                            break

        sample_size = len(matching_final_buckets)
        probabilities = {}
        counts = Counter(matching_final_buckets)
        if sample_size >= min_sample_size:
            high = max(max(counts), observed_bucket + 3)
            support = range(observed_bucket, high + 1)
            probabilities = self.smoothed_distribution(
                matching_final_buckets,
                support,
                alpha=0.10,
            )

        # Historical rate of intermediate bucket skips during afternoon warming
        # (10 AM to 6 PM).
        total_warming_days = 0
        skipping_days = 0

        for local_date, rows in by_date.items():
            warm_rows = [r for r in rows if 600 <= r["minute_of_day"] <= 1080]
            if not warm_rows:
                continue
            total_warming_days += 1

            temps = [self.row_temp_native(r) for r in warm_rows if self.row_temp_native(r) is not None]
            if len(temps) < 2:
                continue

            has_skip = False
            for i in range(len(temps) - 1):
                t1, t2 = temps[i], temps[i+1]
                b1 = self.round_half_up(t1)
                b2 = self.round_half_up(t2)
                # Check for an upward jump that skips an integer bucket.
                if b2 >= b1 + 2:
                    has_skip = True
                    break
            if has_skip:
                skipping_days += 1

        skip_rate = (skipping_days / total_warming_days) if total_warming_days > 0 else 0.0
        update_rate = (
            len(first_update_minutes) / sample_size
            if sample_size > 0 else 0.0
        )
        median_first_update_minute = None
        if first_update_minutes:
            ordered = sorted(first_update_minutes)
            median_first_update_minute = ordered[len(ordered) // 2]

        return {
            "current_max_bucket": observed_bucket,
            "observed_bucket": observed_bucket,
            "cutoff_hour": cutoff_hour,
            "sample_size": sample_size,
            "counts": {int(bucket): int(count) for bucket, count in counts.items()},
            "probabilities": probabilities,
            "skip_rate": skip_rate,
            "update_rate": update_rate,
            "median_first_update_minute": median_first_update_minute,
        }

    def get_bucket_transitions(self, sources, now):
        transition_model = self.bucket_transition_model(sources, now)
        observed_bucket = transition_model["observed_bucket"]

        if observed_bucket is None:
            return {
                **transition_model,
                "transitions": [],
            }

        probabilities = transition_model.get("probabilities") or {}
        counts = transition_model.get("counts") or {}
        sample_size = transition_model["sample_size"]
        unit = self.spec.display_unit
        transitions = []
        if sample_size >= 5:
            for target_b in range(observed_bucket, observed_bucket + 3):
                prob = probabilities.get(target_b, 0.0)
                transitions.append({
                    "Target Bucket": f"{target_b} {unit}",
                    "Probability": f"{prob * 100:.1f}%",
                    "Historical Days": counts.get(target_b, 0),
                })
            prob_plus_3 = sum(
                probability
                for target_b, probability in probabilities.items()
                if target_b >= observed_bucket + 3
            )
            cnt_plus_3 = sum(
                count
                for target_b, count in counts.items()
                if target_b >= observed_bucket + 3
            )
            transitions.append({
                "Target Bucket": f">= {observed_bucket + 3} {unit}",
                "Probability": f"{prob_plus_3 * 100:.1f}%",
                "Historical Days": cnt_plus_3,
            })

        return {
            **transition_model,
            "transitions": transitions,
        }

    def load_late_day_model_coefs(self):
        if self._late_day_model_coefs is _UNLOADED:
            self._late_day_model_coefs = self._read_late_day_model_coefs()
        return self._late_day_model_coefs

    def _read_late_day_model_coefs(self):
        bound, payload = self._bound_base_component("late_day_lr_coefficients")
        if bound:
            return payload
        path = resolve_artifact_path(f"late_day_model_coefs{self.spec.artifact_suffix}.json")
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Error loading late-day model coefficients: %s", e)
        return None

    def predict_late_day_continuation(self, sources, cutoff_hour, now):
        coefs = self.load_late_day_model_coefs()
        if not coefs or str(cutoff_hour) not in coefs:
            return None

        # 1. Extract the shared cutoff-aligned features (same as the feature model).
        feats = self.extract_live_features(sources, cutoff_hour, now=now)
        high_so_far = feats["high_so_far"]
        current_temp = feats["current_temp"]
        rise_from_7am = feats["rise_from_7am"]
        dewpoint = feats["dewpoint_c"]
        humidity = feats["humidity"]
        pressure = feats["pressure"]
        pressure_trend_3h = feats["pressure_trend_3h"]
        wind_speed = feats["wind_speed_kmh"]
        wind_gust = feats.get("wind_gust_kmh")
        wind_shift = feats.get("wind_shift_3h_degrees")
        wind_group = feats["wind_group"]
        cloud_group = feats["cloud_group"]
        feature_rows = feats["feature_rows"]
        forecast_high = feats.get("forecast_high")
        forecast_gap = feats.get("forecast_gap")

        # 2. Late-day-specific feature: how long ago today's high was first reached.
        first_reached_min = None
        first_reached_time = None
        for r in feature_rows:
            if self.row_temp_native(r) == high_so_far:
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
            numeric_feature_names = model_data.get("numeric_feature_names")
            if not numeric_feature_names:
                numeric_feature_names = [
                    name for name in feature_names
                    if not name.startswith("wind_") and not name.startswith("cloud_")
                ]
            raw_by_name = {
                "time_since_reached": float(time_since_reached),
                "high_so_far": high_so_far,
                "current_temp": current_temp,
                "rise_from_7am": rise_from_7am,
                "dewpoint_c": dewpoint,
                "humidity": humidity,
                "pressure": pressure,
                "pressure_trend_3h": pressure_trend_3h,
                "wind_speed_kmh": wind_speed,
                "wind_gust_kmh": wind_gust,
                "wind_shift_3h_degrees": wind_shift,
                "forecast_high": forecast_high,
                "forecast_gap": forecast_gap,
            }
            scaled_numeric = {}
            for i, name in enumerate(numeric_feature_names):
                value = raw_by_name.get(name)
                if value is None:
                    value = imputer_median[i] if i < len(imputer_median) else 0.0
                mean = scaler_mean[i] if i < len(scaler_mean) else 0.0
                scale = scaler_scale[i] if i < len(scaler_scale) else 1.0
                if not scale:
                    scale = 1.0
                scaled_numeric[name] = (float(value) - mean) / scale

            scaled_vec = []
            for name in feature_names:
                if name in scaled_numeric:
                    scaled_vec.append(scaled_numeric[name])
                    continue
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
            forecast_tail_probability = None
            observed_bucket = self.round_half_up(high_so_far)
            if observed_bucket is not None:
                weather_forecast = self.source_data(sources, "weather_forecast")
                open_meteo = self.source_data(sources, "open_meteo")
                eccc_city = self.source_data(sources, "eccc_citypage")
                forecast_component = self.forecast_error_component_distribution(
                    range(observed_bucket, observed_bucket + 8),
                    observed_bucket,
                    self.max_row_temp(weather_forecast.get("rows")),
                    self.forecast_day_max(open_meteo),
                    self.row_forecast_high_native(eccc_city),
                    cutoff_hour,
                )
                if forecast_component:
                    forecast_tail_probability = sum(
                        probability
                        for bucket, probability in forecast_component.items()
                        if bucket > observed_bucket
                    )
                    prob = 0.75 * prob + 0.25 * forecast_tail_probability
            
            return {
                "active": True,
                "continuation_probability": prob,
                "time_since_reached": time_since_reached,
                "first_reached_time": first_reached_time,
                "empirical_prior": model_data.get("empirical_prior", 0.10),
                "forecast_high": forecast_high,
                "forecast_gap": forecast_gap,
                "forecast_tail_probability": forecast_tail_probability,
            }
        except Exception as e:
            logger.warning("Error predicting late-day continuation: %s", e)
            return None

    def analog_feature_view(self, features):
        if not features:
            return None
        required = (
            "high_so_far",
            "rise_from_7am",
            "dewpoint_c",
            "wind_group",
            "cloud_group",
        )
        if any(features.get(name) is None for name in required):
            return None
        return {
            "high_so_far": features["high_so_far"],
            "rise_from_7am": features["rise_from_7am"],
            "dewpoint_c": features["dewpoint_c"],
            "wind_group": features["wind_group"],
            "cloud_group": features["cloud_group"],
            "forecast_high": features.get("forecast_high"),
            "forecast_gap": features.get("forecast_gap"),
        }

    def analog_temperature_path(self, rows):
        temp_path = {}
        for hour in range(7, 21):
            target_minute = hour * 60
            candidates = [row for row in rows if self.row_temp_native(row) is not None]
            if candidates:
                closest = min(
                    candidates,
                    key=lambda row: abs(self.minute_of_day(row.get("time")) - target_minute)
                    if row.get("time") else abs(int(row["minute_of_day"]) - target_minute),
                )
                closest_minute = (
                    self.minute_of_day(closest.get("time"))
                    if closest.get("time") else int(closest["minute_of_day"])
                )
                temp_path[f"{hour:02d}:00"] = (
                    self.row_temp_native(closest) if abs(closest_minute - target_minute) <= 60 else None
                )
            else:
                temp_path[f"{hour:02d}:00"] = None
        return temp_path

    def find_analog_days(self, sources, cutoff_hour, now, limit=5):
        # Always return this shape so callers never have to type-check the result.
        empty_result = {"cutoff_hour": cutoff_hour, "today_features": {}, "analogs": []}
        # 1. Get cache
        cache = self.historical_target_cache()
        if not cache or not cache.get("daily"):
            return empty_result

        # 2. Extract today's cutoff-aligned features from the shared live path,
        # rejecting rows that would need analog-specific defaults.
        history = self.source_data(sources, "wu_history")
        rows = history.get("rows") or []
        today_full = self.extract_live_features(
            sources,
            cutoff_hour,
            now=now,
            strict=True,
        )
        today_features = self.analog_feature_view(today_full)
        if not today_features:
            return empty_result

        # 3. Extract historical features at same cutoff hour
        hist_days_features = []
        forecast_index = load_forecast_daily(daily_path_for(self.spec))
        
        for local_date, daily in cache["daily"].items():
            day_obs = cache["by_date"].get(local_date, [])
            if not day_obs:
                continue
            historical_full = build_historical_feature_record(
                local_date,
                day_obs,
                daily,
                cutoff_hour,
                forecast_high=forecast_index.get(local_date.isoformat()),
                wind_group_fn=self.wind_group,
                cloud_group_fn=self.cloud_group,
                microclimate_feature_fn=self.microclimate_features,
                strict=True,
            )
            h_features = self.analog_feature_view(historical_full)
            if not h_features:
                continue

            hist_days_features.append({
                "date": local_date,
                **h_features,
                "final_high": self.row_max_native(daily),
                "final_bucket": daily["bucket"],
                "observations": day_obs
            })

        if not hist_days_features:
            return empty_result

        # 4. Compute standard deviations of numeric features for scaling
        highs = [d["high_so_far"] for d in hist_days_features]
        rises = [d["rise_from_7am"] for d in hist_days_features]
        dews = [d["dewpoint_c"] for d in hist_days_features]
        forecast_gaps = [
            d["forecast_gap"] for d in hist_days_features
            if d.get("forecast_gap") is not None
        ]

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
        std_forecast_gap = std_dev(forecast_gaps, 2.0)

        # 5. Compute distances and similarity scores
        w_high = 2.0
        w_rise = 1.5
        w_dew = 1.0
        w_wind = 1.0
        w_cloud = 1.0
        w_forecast_gap = 1.0

        analogs = []
        for d in hist_days_features:
            d_high = ((d["high_so_far"] - today_features["high_so_far"]) / std_high) ** 2
            d_rise = ((d["rise_from_7am"] - today_features["rise_from_7am"]) / std_rise) ** 2
            d_dew = ((d["dewpoint_c"] - today_features["dewpoint_c"]) / std_dew) ** 2

            d_wind = 1.0 if d["wind_group"] != today_features["wind_group"] else 0.0
            d_cloud = 1.0 if d["cloud_group"] != today_features["cloud_group"] else 0.0
            if today_features.get("forecast_gap") is not None and d.get("forecast_gap") is not None:
                d_forecast_gap = ((d["forecast_gap"] - today_features["forecast_gap"]) / std_forecast_gap) ** 2
            else:
                d_forecast_gap = 0.0

            dist = math.sqrt(
                w_high * d_high +
                w_rise * d_rise +
                w_dew * d_dew +
                w_wind * d_wind +
                w_cloud * d_cloud +
                w_forecast_gap * d_forecast_gap
            )

            similarity = 100.0 * math.exp(-dist / 3.0)

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
                "forecast_high": d["forecast_high"],
                "forecast_gap": d["forecast_gap"],
                "temp_path": self.analog_temperature_path(d["observations"]),
            })

        analogs.sort(key=lambda x: x["distance"])

        # Also get today's temperature path
        return {
            "cutoff_hour": cutoff_hour,
            "today_features": {
                **today_features,
                "temp_path": self.analog_temperature_path(rows),
            },
            "analogs": analogs[:limit]
        }


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _feature_row_market(row):
    return str((row or {}).get("market_id") or (row or {}).get("market") or "unknown").lower()


def _feature_row_regime(row):
    return str((row or {}).get("weather_regime") or (row or {}).get("regime") or "all")


def _feature_row_settlement(row):
    return row_value(row, "settlement_high", "settlement", "observed_high", "actual_high")


def _guidance_highs(row):
    forecast_high = row_value(row, "forecast_high")
    highs = {}
    nws_high = row_value(row, "nws_grid_high")
    if nws_high is not None:
        highs["nws_grid"] = nws_high
    nbm_p50 = row_value(row, "nbm_prob_tmax_p50")
    if nbm_p50 is not None:
        highs["nbm_prob_tmax_p50"] = nbm_p50
    if forecast_high is None:
        return highs
    for source, delta_key in (
        ("open_meteo_gfs", "open_meteo_gfs_high_delta"),
        ("open_meteo_hrrr", "open_meteo_hrrr_high_delta"),
        ("open_meteo_nbm", "open_meteo_nbm_high_delta"),
        ("open_meteo_nam", "open_meteo_nam_high_delta"),
    ):
        delta = row_value(row, delta_key)
        if delta is not None:
            highs[source] = forecast_high + delta
    return highs


def build_us_guidance_replay_diagnostics(rows):
    """Summarize US official-grid/multi-model guidance against settlement rows."""
    groups = defaultdict(list)
    input_rows = list(rows or [])
    for row in input_rows:
        key = (
            _feature_row_market(row),
            str((row or {}).get("cutoff_hour") or "unknown"),
            _feature_row_regime(row),
        )
        groups[key].append(row)
    diagnostics = []
    for (market_id, cutoff_hour, regime), group_rows in sorted(groups.items()):
        source_scores = defaultdict(lambda: {
            "rows": 0,
            "mean_abs_error": [],
            "mean_abs_error_improvement_vs_forecast": [],
        })
        forecast_errors = []
        for row in group_rows:
            settlement = _feature_row_settlement(row)
            forecast_high = row_value(row, "forecast_high")
            if settlement is None or forecast_high is None:
                continue
            forecast_error = abs(forecast_high - settlement)
            forecast_errors.append(forecast_error)
            for source, high in _guidance_highs(row).items():
                error = abs(high - settlement)
                source_scores[source]["rows"] += 1
                source_scores[source]["mean_abs_error"].append(error)
                source_scores[source]["mean_abs_error_improvement_vs_forecast"].append(
                    forecast_error - error
                )
        diagnostics.append({
            "market_id": market_id,
            "cutoff_hour": cutoff_hour,
            "weather_regime": regime,
            "rows": len(group_rows),
            "scored_rows": len(forecast_errors),
            "forecast_mean_abs_error": _mean(forecast_errors),
            "sources": {
                source: {
                    "rows": values["rows"],
                    "mean_abs_error": _mean(values["mean_abs_error"]),
                    "mean_abs_error_improvement_vs_forecast": _mean(
                        values["mean_abs_error_improvement_vs_forecast"]
                    ),
                }
                for source, values in sorted(source_scores.items())
            },
        })
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "report_type": "us_guidance_replay_diagnostics",
        "summary": {
            "input_rows": len(input_rows),
            "groups": len(diagnostics),
            "scored_rows": sum(row["scored_rows"] for row in diagnostics),
        },
        "groups": diagnostics,
    }


def render_us_guidance_replay_diagnostics_markdown(payload):
    lines = [
        "# US Guidance Replay Diagnostics",
        "",
        "| Market | Cutoff | Regime | Source | Rows | Mean Error | Improvement vs Forecast |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for group in (payload or {}).get("groups") or []:
        for source, values in (group.get("sources") or {}).items():
            lines.append(
                "| {market_id} | {cutoff_hour} | {weather_regime} | {source} | "
                "{rows} | {mean_abs_error} | {improvement} |".format(
                    market_id=group.get("market_id"),
                    cutoff_hour=group.get("cutoff_hour"),
                    weather_regime=group.get("weather_regime"),
                    source=source,
                    rows=values.get("rows"),
                    mean_abs_error=values.get("mean_abs_error"),
                    improvement=values.get("mean_abs_error_improvement_vs_forecast"),
                )
            )
    return "\n".join(lines) + "\n"
