import math
from collections import Counter
from datetime import datetime
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
from forecast_error_model import forecast_error_distribution
from probability_calibration import apply_exact_distribution_calibration
from settlement_lag_model import settlement_catchup_probability

# --- Forecast floor ---------------------------------------------------------
# The cap bounds the distribution from above (the high won't exceed the
# forecast); the forecast floor is its mirror — when independent forecasts
# agree, the high will very likely *reach* near them, so mass far below the
# forecast is suppressed. Kept soft (residual mass always remains) and decayed
# to zero by late afternoon, when a low high-so-far falsifies the forecast.
FORECAST_FLOOR_MARGIN = 2            # "almost certainly reaches forecast minus this"
                                     # (2 for same-day forecasts, which rarely miss low by >2)
FORECAST_AGREEMENT_SPREAD = 3.0      # forecasts must agree within this many degrees
FORECAST_FLOOR_MIN_SOURCES = 2       # and come from at least this many sources
FORECAST_FLOOR_BASE = 0.5            # per-degree decay below the threshold (softer than the cap)

# --- Forecast pull (upper-tail mirror of the forecast floor) ----------------
# The floor lifts the BOTTOM; the pull lifts the TOP. The HGB feature model
# saturates ~1 C below agreeing hot morning forecasts (it under-calls the high),
# yet the forecast-vs-realized tracker (src/forecast_tracker.py) measured the
# morning consensus actually being reached ~70% of the time while the model gave
# it only ~45%. So early in the day, when independent forecasts agree on a high
# the model has not yet reached, raise P(high >= forecast) toward that measured
# reach-rate. One-directional (never lowers an already-confident model),
# time-decayed (the observed high takes over by mid-afternoon), and capped at the
# reach-rate so it trusts the forecast's track record, not blindly the top bucket.
FORECAST_PULL_TARGET_REACH = 0.70   # measured 09:00 reach-rate (forecast_tracker)
FORECAST_PULL_START_HOUR = 11       # full strength at/under this hour
FORECAST_PULL_END_HOUR = 16         # faded to zero by this hour

# --- Live-observed floor ----------------------------------------------------
# Wunderground *history* (the settlement source) prints with a lag and can stall
# for hours. SWOB station observations lead it by ~1 hour and match the WU final
# high within ~0.3 C. So when SWOB has already observed a higher bucket than WU
# history has printed, the high has physically reached there: suppress mass below
# it. Soft one bucket down (SWOB's +0.3 bias can round it up — the v0.4.8 case),
# strong further down. This is observed data, not a forecast, so no time decay.
LIVE_FLOOR_HEDGE = 0.40   # retained fraction one bucket below the SWOB bucket
LIVE_FLOOR_BASE = 0.12    # per-degree decay for buckets further below
CURRENT_OBSERVED_FLOOR_HEDGE = 0.001
CURRENT_OBSERVED_FLOOR_BASE = 0.05

# --- Late-day lock-in (upper-tail mirror of the floors) ---------------------
# The biggest model-vs-market gap is end-of-day under-confidence: once the day
# is past its peak and the temperature is falling, the high is essentially
# locked at the observed maximum, but the forecast cap stays wide and SWOB
# overshoot keeps mass on a higher bucket the high will never reach. As the day
# closes (time) AND the temperature drops below the day's high (past peak),
# concentrate mass onto the observed high by suppressing buckets above it. Soft
# one bucket up (WU history can still revise up a degree), strong further up.
LATE_LOCKIN_START_HOUR = 15    # no lock-in before this (peak is usually 15-16h)
LATE_LOCKIN_FULL_HOUR = 20     # full strength by this hour
LATE_LOCKIN_PEAK_DROP = 2.0    # degrees the temp must fall below the high for full past-peak
LATE_LOCKIN_HEDGE = 0.20       # retained fraction one bucket above the high at full strength
LATE_LOCKIN_BASE = 0.15        # per-degree decay for buckets further above
COMPONENT_SCHEMA_VERSION = "toronto_distribution_components_v0.1"


class DistributionMixin:
    """The probability engine: priors, blending, live signals, caps, weighting."""

    def apply_live_observed_floor(self, scores, swob_max, history_max, hour=None):
        """Suppress buckets below what SWOB has already observed, when SWOB leads
        the printed WU-history high. Keeps a hedge one bucket down for SWOB's
        small warm bias; strongly suppresses further down. Never zero."""
        swob_bucket = self.round_half_up(swob_max)
        if swob_bucket is None:
            return self.normalize_scores(scores)
        wu_bucket = self.round_half_up(history_max)
        if wu_bucket is not None and swob_bucket <= wu_bucket:
            return self.normalize_scores(scores)  # WU floor already covers it
        catchup_probability = settlement_catchup_probability(
            getattr(self, "settlement_lag_model", None),
            "eccc_swob",
            swob_bucket,
            wu_bucket,
            cutoff_hour=hour,
        )
        one_bucket_hedge = LIVE_FLOOR_HEDGE
        if catchup_probability is not None:
            # SWOB is not the settlement source. Even when historical catch-up
            # rates are high, keep a meaningful one-bucket hedge to avoid
            # recreating a hard non-resolution floor.
            one_bucket_hedge = max(0.30, min(0.80, 1.0 - catchup_probability))
        adjusted = {}
        for temp, score in scores.items():
            if temp >= swob_bucket:
                adjusted[temp] = score
            else:
                below = swob_bucket - temp
                adjusted[temp] = score * one_bucket_hedge * (LIVE_FLOOR_BASE ** (below - 1))
        return self.normalize_scores(adjusted)

    def apply_current_observed_floor(self, scores, current_observed_max, history_max):
        """Strongly suppress buckets below current observed temperature readings.

        This uses live current-temperature readings, not max-since-7am, because
        max-since can overstate the eventual WU settlement bucket by rounding.
        """
        support_bucket = self.round_half_up(current_observed_max)
        if support_bucket is None:
            return self.normalize_scores(scores)
        history_bucket = self.round_half_up(history_max)
        if history_bucket is not None and support_bucket <= history_bucket:
            return self.normalize_scores(scores)
        adjusted = {}
        for temp, score in scores.items():
            if temp >= support_bucket:
                adjusted[temp] = score
            else:
                below = support_bucket - temp
                adjusted[temp] = (
                    score
                    * CURRENT_OBSERVED_FLOOR_HEDGE
                    * (CURRENT_OBSERVED_FLOOR_BASE ** (below - 1))
                )
        return self.normalize_scores(adjusted)

    def late_day_lockin_strength(self, hour, current_reading, history_max):
        """How locked-in the day's high is: 0 until both late enough (time) and
        past peak (temperature has fallen below the observed high), ramping to 1
        once it is clearly evening and the temperature has dropped well below."""
        if history_max is None or current_reading is None:
            return 0.0
        if hour <= LATE_LOCKIN_START_HOUR:
            time_factor = 0.0
        elif hour >= LATE_LOCKIN_FULL_HOUR:
            time_factor = 1.0
        else:
            time_factor = (hour - LATE_LOCKIN_START_HOUR) / (
                LATE_LOCKIN_FULL_HOUR - LATE_LOCKIN_START_HOUR
            )
        drop = history_max - current_reading
        if drop <= 0:
            peak_factor = 0.0  # temperature still at/above the high: it could rise
        elif drop >= LATE_LOCKIN_PEAK_DROP:
            peak_factor = 1.0
        else:
            peak_factor = drop / LATE_LOCKIN_PEAK_DROP
        return time_factor * peak_factor

    def apply_late_day_lockin(self, scores, history_max, current_reading, hour):
        """Suppress buckets above the observed high as the day locks in. Soft one
        bucket up (WU history can still revise up a degree), strong further up.
        Never zero, and a no-op until the day is both late and past peak."""
        strength = self.late_day_lockin_strength(hour, current_reading, history_max)
        if strength <= 0:
            return self.normalize_scores(scores)
        observed_bucket = self.round_half_up(history_max)
        if observed_bucket is None:
            return self.normalize_scores(scores)
        adjusted = {}
        for temp, score in scores.items():
            if temp <= observed_bucket:
                adjusted[temp] = score
            else:
                above = temp - observed_bucket
                full_retained = LATE_LOCKIN_HEDGE * (LATE_LOCKIN_BASE ** (above - 1))
                factor = (1.0 - strength) + strength * full_retained
                adjusted[temp] = score * factor
        return self.normalize_scores(adjusted)

    def forecast_floor_time_weight(self, hour):
        """Strong in the morning (plenty of time to warm up), zero by late
        afternoon (a low high-so-far by then means the forecast is busting)."""
        if hour <= 12:
            return 1.0
        if hour >= 17:
            return 0.0
        return (17 - hour) / 5.0

    def forecast_floor_plan(self, forecasts, hour, observed_bucket):
        """Return (threshold, strength) for the forecast-anchored lower bound,
        or None when forecasts disagree, are too few, or it is too late."""
        vals = [float(v) for v in forecasts if v is not None]
        if len(vals) < FORECAST_FLOOR_MIN_SOURCES:
            return None
        spread = max(vals) - min(vals)
        if spread > FORECAST_AGREEMENT_SPREAD:
            return None
        time_weight = self.forecast_floor_time_weight(hour)
        if time_weight <= 0:
            return None
        anchor = sum(vals) / len(vals)
        threshold = self.round_half_up(anchor) - FORECAST_FLOOR_MARGIN
        # Mild penalty for a wider (but still agreeing) spread; never below 0.5.
        spread_weight = max(0.5, 1.0 - spread / (2 * FORECAST_AGREEMENT_SPREAD))
        return threshold, time_weight * spread_weight

    def apply_forecast_floor(self, scores, forecasts, hour, observed_bucket):
        """Suppress buckets well below an agreed forecast, scaled by confidence
        and time of day. Soft: the multiplier is a convex blend so probability
        is never driven to zero (a busted forecast must stay survivable)."""
        plan = self.forecast_floor_plan(forecasts, hour, observed_bucket)
        if not plan:
            return self.normalize_scores(scores)
        threshold, strength = plan
        adjusted = {}
        for temp, score in scores.items():
            if temp < threshold:
                factor = (1 - strength) + strength * (FORECAST_FLOOR_BASE ** (threshold - temp))
                adjusted[temp] = score * factor
            else:
                adjusted[temp] = score
        return self.normalize_scores(adjusted)

    def forecast_pull_time_weight(self, hour):
        """Strong in the morning (when the model under-calls before the high
        develops), zero by mid-afternoon once the observed high has taken over."""
        if hour <= FORECAST_PULL_START_HOUR:
            return 1.0
        if hour >= FORECAST_PULL_END_HOUR:
            return 0.0
        return (FORECAST_PULL_END_HOUR - hour) / (FORECAST_PULL_END_HOUR - FORECAST_PULL_START_HOUR)

    def forecast_anchor_bucket(self, forecasts):
        """The agreed forecast-high bucket and an agreement weight, or None when
        forecasts are too few or disagree (same gate as the forecast floor)."""
        values = [float(v) for v in forecasts if v is not None]
        if len(values) < FORECAST_FLOOR_MIN_SOURCES:
            return None
        spread = max(values) - min(values)
        if spread > FORECAST_AGREEMENT_SPREAD:
            return None
        anchor = sum(values) / len(values)
        spread_weight = max(0.5, 1.0 - spread / (2 * FORECAST_AGREEMENT_SPREAD))
        return self.round_half_up(anchor), spread_weight

    def apply_forecast_pull(self, scores, forecasts, hour, observed_bucket, current_observed_bucket):
        """Raise P(high >= agreed forecast) toward the measured reach-rate early
        in the day, when the model has under-called a high the forecasts agree on.

        One-directional: only ever increases that tail. No-op when forecasts
        disagree, it is past mid-afternoon, the observed high has already reached
        the forecast, or the model is already at/above the reach-rate.
        """
        anchor = self.forecast_anchor_bucket(forecasts)
        if anchor is None:
            return self.normalize_scores(scores)
        anchor_bucket, spread_weight = anchor
        reached = self.max_value(observed_bucket, current_observed_bucket)
        if reached is not None and anchor_bucket <= reached:
            return self.normalize_scores(scores)   # already there: nothing to pull
        weight = self.forecast_pull_time_weight(hour) * spread_weight
        if weight <= 0:
            return self.normalize_scores(scores)
        scores = self.normalize_scores(scores)
        threshold = anchor_bucket - 1               # tail = P(temp >= anchor_bucket)
        current_tail = sum(score for temp, score in scores.items() if temp > threshold)
        if current_tail >= FORECAST_PULL_TARGET_REACH:
            return scores                            # already confident enough
        return self.apply_tail_target(scores, threshold, FORECAST_PULL_TARGET_REACH, weight)

    def forecast_error_component_distribution(
        self,
        support,
        observed_bucket,
        weather_forecast_max,
        open_meteo_max,
        eccc_forecast_high,
        hour,
    ):
        values = []
        if weather_forecast_max is not None:
            values.append({"source": "weather_forecast", "forecast_high_c": weather_forecast_max})
        if open_meteo_max is not None:
            values.append({"source": "open_meteo", "forecast_high_c": open_meteo_max})
        if eccc_forecast_high is not None:
            values.append({"source": "eccc_citypage", "forecast_high_c": eccc_forecast_high})
        return forecast_error_distribution(
            support,
            values,
            getattr(self, "forecast_error_model", None),
            floor_bucket=observed_bucket,
            capture_hour=hour,
        )

    def estimate_distribution(self, sources, now=None):
        self._last_distribution_components = {}
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
        current_observed_bucket = self.round_half_up(self.max_value(
            history_max,
            current_temp,
            metar_temp,
        ))
        observed_support_bucket = self.round_half_up(self.max_value(
            history_max,
            current_temp,
            eccc_max,
            metar_temp,
        ))
        max_signal = self.round_half_up(self.max_value(*live_values))
        if max_signal is None and not scores:
            self._last_distribution_components = {
                "schema_version": COMPONENT_SCHEMA_VERSION,
                "components": {},
            }
            return {}

        low = min(min(scores), 8, (observed_bucket or max_signal or 16) - 5)
        high = max(max(scores), 34, (max_signal or observed_bucket or 30) + 4)
        for temp in range(low, high + 1):
            scores.setdefault(temp, 0.0005)
        scores = self.normalize_scores(scores)
        distribution_components = {
            "climatology_prior": dict(scores),
        }

        cutoff_hour = self.effective_intraday_cutoff_hour(
            now,
            history.get("rows") or [],
        )
        self._last_probability_calibration_context = {
            "cutoff_hour": cutoff_hour,
            "observed_floor_bucket": observed_bucket,
            "current_observed_bucket": current_observed_bucket,
            "observed_support_bucket": observed_support_bucket,
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
        
        intraday = None
        forecast_component = None
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
            distribution_components[f"{active_kind}_feature_model"] = dict(
                self.normalize_scores(feature_probs)
            )
            # Blend the ML prediction with the climatology prior, using the
            # per-hour weight tuned by LOO log loss (was a flat 0.80).
            scores = self.blend_distribution(
                scores, feature_probs, self.feature_blend_weight(cutoff_hour)
            )
            distribution_components["feature_blend"] = dict(scores)
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
            forecast_component = self.forecast_error_component_distribution(
                scores.keys(),
                observed_bucket,
                weather_forecast_max,
                open_meteo_max,
                eccc_forecast_high,
                now.hour,
            )
            cap_distribution = forecast_component or self.cap_prior_distribution(
                scores.keys(),
                calibrated_cap,
                floor_bucket=observed_bucket,
            )
            empirical_components = {
                "intraday_high": intraday["probabilities"] if intraday else None,
                "current_bucket": current_distribution["probabilities"] if current_distribution else None,
                "wind_regime": wind_distribution["probabilities"] if wind_distribution else None,
                "cloud_regime": cloud_distribution["probabilities"] if cloud_distribution else None,
                "forecast_error" if forecast_component else "forecast_cap": cap_distribution,
            }
            for name, distribution in empirical_components.items():
                if distribution:
                    distribution_components[name] = dict(self.normalize_scores(distribution))

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
                distribution_components["empirical_weighted"] = dict(scores)
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
        distribution_components["post_live_signals"] = dict(self.normalize_scores(scores))

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

        # Symmetric to the cap: when forecasts agree, the high will very likely
        # reach near them, so suppress mass far below the forecast (soft, and
        # only while there's still daytime to warm up).
        if not using_calibrated_empirical:
            scores = self.apply_forecast_floor(
                scores,
                [weather_forecast_max, open_meteo_max, eccc_forecast_high],
                now.hour,
                observed_bucket,
            )
            # Mirror of the floor: lift the upper tail toward an agreed morning
            # forecast the model has under-called (the measured reach-rate gap).
            scores = self.apply_forecast_pull(
                scores,
                [weather_forecast_max, open_meteo_max, eccc_forecast_high],
                now.hour,
                observed_bucket,
                current_observed_bucket,
            )
            distribution_components["forecast_pull"] = dict(self.normalize_scores(scores))

        # Live-observed floor: react to SWOB leading the lagging WU history,
        # instead of waiting hours for WU to print what already happened.
        scores = self.apply_live_observed_floor(scores, eccc_max, history_max, hour=now.hour)
        distribution_components["settlement_lag_adjusted"] = dict(self.normalize_scores(scores))
        scores = self.apply_current_observed_floor(
            scores,
            self.max_value(history_max, current_temp, metar_temp),
            history_max,
        )
        distribution_components["current_observed_floor"] = dict(self.normalize_scores(scores))

        # Late-day lock-in: once the day is past peak and the temperature is
        # falling, concentrate onto the observed high (suppress the upper tail
        # the high will no longer reach). Current reading prefers live temps.
        current_reading = current_temp if current_temp is not None else metar_temp
        scores = self.apply_late_day_lockin(scores, history_max, current_reading, now.hour)
        distribution_components["late_day_lockin"] = dict(self.normalize_scores(scores))

        scores = self.normalize_scores(scores)
        distribution_components["pre_calibration_model"] = dict(scores)
        calibrated_scores = apply_exact_distribution_calibration(
            scores,
            getattr(self, "probability_calibration", None),
            floor_bucket=observed_bucket,
        )
        distribution_components["final_model"] = dict(calibrated_scores)
        self._last_distribution_components = {
            "schema_version": COMPONENT_SCHEMA_VERSION,
            "cutoff_hour": cutoff_hour,
            "active_model_kind": getattr(self, "active_model_kind", "empirical"),
            "observed_floor_bucket": observed_bucket,
            "current_observed_bucket": current_observed_bucket,
            "observed_support_bucket": observed_support_bucket,
            "components": distribution_components,
        }
        return calibrated_scores

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
