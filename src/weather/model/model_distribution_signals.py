"""Live observed and forecast signal helpers for distribution modeling."""

from __future__ import annotations

import math

from forecast_error_model import forecast_error_distribution
try:
    from .model_distribution_constants import (
        BUCKET_TRANSITION_BLEND_MAX,
        BUCKET_TRANSITION_MIN_SAMPLE,
        FALSIFICATION_EARLIEST_HOUR,
        FALSIFICATION_MARGIN,
        FALSIFICATION_STAND_MINUTES,
        FORECAST_AGREEMENT_SPREAD,
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
        VALIDATED_WU_MAX_HARD_FLOOR_MARKETS,
        WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL,
    )
except ImportError:  # pragma: no cover - direct src compatibility
    from model_distribution_constants import (
        BUCKET_TRANSITION_BLEND_MAX,
        BUCKET_TRANSITION_MIN_SAMPLE,
        FALSIFICATION_EARLIEST_HOUR,
        FALSIFICATION_MARGIN,
        FALSIFICATION_STAND_MINUTES,
        FORECAST_AGREEMENT_SPREAD,
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
        VALIDATED_WU_MAX_HARD_FLOOR_MARKETS,
        WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL,
    )
from settlement_lag_model import revision_up_probability, settlement_catchup_probability

class DistributionSignalMixin:
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
        one_bucket_hedge = self.catchup_floor_hedge("eccc_swob", swob_bucket, wu_bucket, hour)
        adjusted = {}
        for temp, score in scores.items():
            if temp >= swob_bucket:
                adjusted[temp] = score
            else:
                below = swob_bucket - temp
                adjusted[temp] = score * one_bucket_hedge * (LIVE_FLOOR_BASE ** (below - 1))
        return self.normalize_scores(adjusted)

    def catchup_floor_hedge(self, source, source_bucket, wu_bucket, hour):
        """One-bucket-below retained fraction for a non-resolution observed
        floor, sized by the source's learned WU catch-up rate and clamped so no
        non-resolution source becomes a hard settlement floor."""
        catchup_probability = settlement_catchup_probability(
            getattr(self, "settlement_lag_model", None),
            source,
            source_bucket,
            wu_bucket,
            cutoff_hour=hour,
        )
        if catchup_probability is None:
            return LIVE_FLOOR_HEDGE
        return max(LIVE_FLOOR_HEDGE_MIN, min(LIVE_FLOOR_HEDGE_MAX, 1.0 - catchup_probability))

    def validated_current_max_floor_bucket(self, current_max, history_max=None):
        """Market-scoped hard floor for Weather.com max-since-7am validation.

        Most markets still use max-since-7am only as soft support because the
        pinned validation found over-final rows. Miami's pinned source check had
        zero over-final comparable rows, so it can use the same-day WU current
        max as a hard lower bound when it leads printed WU history.
        """
        if getattr(self.spec, "id", None) not in VALIDATED_WU_MAX_HARD_FLOOR_MARKETS:
            return None
        current_bucket = self.round_half_up(current_max)
        if current_bucket is None:
            return None
        history_bucket = self.round_half_up(history_max)
        if history_bucket is not None and current_bucket <= history_bucket:
            return None
        return current_bucket

    def apply_current_observed_floor(self, scores, current_temp, metar_temp, history_max, hour=None):
        """Suppress buckets below the highest live current-temperature reading,
        hedged by that source's learned WU catch-up rate (same machinery as the
        SWOB floor -- these are non-resolution readings and must never act as a
        hard floor; the measured Toronto wu_current catch-up is only ~41%).

        Uses live current readings, not max-since-7am, because max-since can
        overstate the eventual WU settlement bucket by rounding.
        """
        candidates = []
        for source, value in (("weather_current", current_temp), ("metar", metar_temp)):
            bucket = self.round_half_up(value)
            if bucket is not None:
                candidates.append((bucket, source))
        if not candidates:
            return self.normalize_scores(scores)
        support_bucket = max(bucket for bucket, _ in candidates)
        leaders = [source for bucket, source in candidates if bucket == support_bucket]
        # On a tie, METAR's measured catch-up (~66%) outranks weather_current's
        # (~41%); sizing by the stronger-evidence source is the sharper hedge.
        source = "metar" if "metar" in leaders else leaders[0]
        history_bucket = self.round_half_up(history_max)
        if history_bucket is not None and support_bucket <= history_bucket:
            return self.normalize_scores(scores)
        one_bucket_hedge = self.catchup_floor_hedge(source, support_bucket, history_bucket, hour)
        adjusted = {}
        for temp, score in scores.items():
            if temp >= support_bucket:
                adjusted[temp] = score
            else:
                below = support_bucket - temp
                adjusted[temp] = score * one_bucket_hedge * (LIVE_FLOOR_BASE ** (below - 1))
        return self.normalize_scores(adjusted)

    def learned_metar_live_signal(self, metar_temp, history_max, hour=None):
        """Cutoff-aware METAR vote learned from historical catch-up behavior.

        METAR only gets this extra Gaussian live vote when it leads the printed
        WU high and the settlement-lag artifact has evidence for that hour/gap.
        Otherwise METAR remains available to the hedged observed-floor path, but
        no longer contributes the old fixed small signal.
        """
        metar_bucket = self.round_half_up(metar_temp)
        history_bucket = self.round_half_up(history_max)
        if metar_bucket is None or history_bucket is None or metar_bucket <= history_bucket:
            return None
        catchup_probability = settlement_catchup_probability(
            getattr(self, "settlement_lag_model", None),
            "metar",
            metar_bucket,
            history_bucket,
            cutoff_hour=hour,
        )
        if catchup_probability is None:
            return None
        lift = (float(catchup_probability) - METAR_LIVE_SIGNAL_REACHED_BASELINE) / (
            1.0 - METAR_LIVE_SIGNAL_REACHED_BASELINE
        )
        weight = METAR_LIVE_SIGNAL_MAX_WEIGHT * max(0.0, min(1.0, lift))
        if weight <= 0:
            return None
        return (metar_temp, weight, METAR_LIVE_SIGNAL_SIGMA)

    def preserve_wu_floor_residual(self, scores, history_max, observed_support_bucket):
        """Keep a small exact-bucket residual on the printed WU high.

        Live current/METAR/SWOB support can lead lagging WU history, but those
        are non-resolution sources. They should suppress the printed WU bucket,
        not erase the branch where WU never catches that higher live reading.
        """
        history_bucket = self.round_half_up(history_max)
        support_bucket = self.round_half_up(observed_support_bucket)
        scores = self.normalize_scores(scores)
        if (
            history_bucket is None
            or support_bucket is None
            or support_bucket <= history_bucket
            or history_bucket not in scores
            or scores.get(history_bucket, 0.0) >= WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL
        ):
            return scores
        other_total = sum(
            probability for bucket, probability in scores.items()
            if bucket != history_bucket
        )
        if other_total <= 0:
            return scores
        scale = (1.0 - WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL) / other_total
        return {
            bucket: (
                WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL
                if bucket == history_bucket
                else probability * scale
            )
            for bucket, probability in scores.items()
        }

    def bucket_transition_blend_weight(self, transition_model):
        sample_size = int((transition_model or {}).get("sample_size") or 0)
        if sample_size < BUCKET_TRANSITION_MIN_SAMPLE:
            return 0.0
        return BUCKET_TRANSITION_BLEND_MAX * min(1.0, sample_size / 100.0)

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
        peak_drop = self.spec.scale_delta(LATE_LOCKIN_PEAK_DROP)
        if drop <= 0:
            peak_factor = 0.0  # temperature still at/above the high: it could rise
        elif drop >= peak_drop:
            peak_factor = 1.0
        else:
            peak_factor = drop / peak_drop
        return time_factor * peak_factor

    def late_day_continuation_blend_weight(self, hour):
        if hour < 15:
            return 0.0
        if hour >= 17:
            return LATE_DAY_CONTINUATION_BLEND_17H
        return LATE_DAY_CONTINUATION_BLEND_15H

    def learned_lockin_strength(self, hour, history, now):
        """Lock-in floor from the learned WU revision-up curve: ``1 - rate``
        once it is late (>= LEARNED_LOCKIN_START_HOUR) and the printed high has
        stood unimproved for LEARNED_LOCKIN_STAND_MINUTES. Covers the evening
        plateau the past-peak heuristic misses (current == high => drop 0)."""
        if hour < LEARNED_LOCKIN_START_HOUR:
            return 0.0
        history_max = self.to_number(history.get("max_c"))
        max_times = history.get("max_times") or []
        if history_max is None or not max_times:
            return 0.0
        first_at_max = self.minute_of_day(max_times[0])
        if first_at_max is None:
            return 0.0
        stood_minutes = (now.hour * 60 + now.minute) - first_at_max
        if stood_minutes < LEARNED_LOCKIN_STAND_MINUTES:
            return 0.0
        rate = revision_up_probability(getattr(self, "settlement_lag_model", None), hour)
        if rate is None:
            return 0.0
        return max(0.0, min(1.0, 1.0 - rate))

    def remaining_forecast_context(self, now, history_max, *forecast_sources):
        wall_minute = now.hour * 60 + now.minute
        source_maxes = []
        degree_hours_above_high = 0.0
        for source in forecast_sources:
            source = source or {}
            rows = source.get("rows") or source.get("day_rows") or []
            values = []
            for row in rows:
                minute = self.minute_of_day(row.get("time") or row.get("valid_time"))
                value = self.to_number(row.get("temp_c"))
                if minute is not None and minute >= wall_minute and value is not None:
                    values.append(value)
            if not values and source.get("forecast_high_c") is not None:
                value = self.to_number(source.get("forecast_high_c"))
                if value is not None:
                    values.append(value)
            if not values:
                continue
            source_max = max(values)
            source_maxes.append(source_max)
            if history_max is not None:
                degree_hours_above_high += sum(max(0.0, value - history_max) for value in values)
        return {
            "forecast_source_count": len(source_maxes),
            "remaining_forecast_ceiling": max(source_maxes) if source_maxes else None,
            "remaining_degree_hours_above_high": degree_hours_above_high,
        }

    def high_has_stood_lockin_context(
        self,
        hour,
        history,
        current_reading,
        now,
        *forecast_sources,
    ):
        context = {
            "active": False,
            "strength": 0.0,
            "reason": "inactive",
            "stood_minutes": None,
            "current_minus_high": None,
            "remaining_forecast_ceiling": None,
            "remaining_degree_hours_above_high": None,
            "forecast_source_count": 0,
            "revision_up_rate": None,
        }
        if hour < HIGH_HAS_STOOD_START_HOUR or hour > HIGH_HAS_STOOD_END_HOUR:
            context["reason"] = "outside_hour_window"
            return context
        history_max = self.to_number(history.get("max_c"))
        max_times = history.get("max_times") or []
        if history_max is None or not max_times:
            context["reason"] = "missing_history_high"
            return context
        first_at_max = self.minute_of_day(max_times[0])
        if first_at_max is None:
            context["reason"] = "missing_first_high_time"
            return context
        stood_minutes = (now.hour * 60 + now.minute) - first_at_max
        context["stood_minutes"] = stood_minutes
        if stood_minutes < HIGH_HAS_STOOD_MIN_MINUTES:
            context["reason"] = "high_not_stood_long_enough"
            return context
        current_value = self.to_number(current_reading)
        if current_value is None:
            context["reason"] = "missing_current_reading"
            return context
        current_minus_high = current_value - history_max
        context["current_minus_high"] = current_minus_high
        if current_minus_high > -self.spec.scale_delta(HIGH_HAS_STOOD_ROLLOVER_MARGIN):
            context["reason"] = "current_not_below_high"
            return context
        forecast_context = self.remaining_forecast_context(now, history_max, *forecast_sources)
        context.update(forecast_context)
        if forecast_context["forecast_source_count"] < HIGH_HAS_STOOD_MIN_FORECAST_SOURCES:
            context["reason"] = "insufficient_remaining_forecasts"
            return context
        ceiling = forecast_context["remaining_forecast_ceiling"]
        if ceiling is None or ceiling > history_max + self.spec.scale_delta(HIGH_HAS_STOOD_FORECAST_MARGIN):
            context["reason"] = "forecast_ceiling_above_high"
            return context
        revision_rate = revision_up_probability(getattr(self, "settlement_lag_model", None), hour)
        context["revision_up_rate"] = revision_rate
        context["active"] = True
        context["strength"] = 1.0
        context["reason"] = "high_stood_current_rolled_forecasts_below"
        return context

    def apply_late_day_lockin(self, scores, history_max, current_reading, hour, strength=None):
        """Suppress buckets above the observed high as the day locks in. Soft one
        bucket up (WU history can still revise up a degree), strong further up.
        Never zero, and a no-op until the day is both late and past peak.
        ``strength`` may be passed in so the calibration taper reuses the exact
        same lock-in strength (single source of truth)."""
        if strength is None:
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

    def unfalsified_forecasts(self, forecasts, history, now):
        """Drop forecast values the observed day has falsified, for the
        floor/pull votes only. Falsified = past the peak window, the printed
        WU high has stood unimproved for FALSIFICATION_STAND_MINUTES, and the
        source still claims more than FALSIFICATION_MARGIN above it. If the
        high later rises, max_times resets and benched sources are readmitted.
        """
        if now.hour < FALSIFICATION_EARLIEST_HOUR:
            return forecasts
        history_max = self.to_number(history.get("max_c"))
        max_times = history.get("max_times") or []
        if history_max is None or not max_times:
            return forecasts
        first_at_max = self.minute_of_day(max_times[0])
        if first_at_max is None:
            return forecasts
        stood_minutes = (now.hour * 60 + now.minute) - first_at_max
        if stood_minutes < FALSIFICATION_STAND_MINUTES:
            return forecasts
        threshold = history_max + self.spec.scale_delta(FALSIFICATION_MARGIN)
        return [
            value for value in forecasts
            if value is None or value <= threshold
        ]

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
        agreement = self.spec.scale_delta(FORECAST_AGREEMENT_SPREAD)
        spread = max(vals) - min(vals)
        if spread > agreement:
            return None
        time_weight = self.forecast_floor_time_weight(hour)
        if time_weight <= 0:
            return None
        anchor = sum(vals) / len(vals)
        threshold = self.round_half_up(anchor) - self.spec.scale_delta(FORECAST_FLOOR_MARGIN)
        # Mild penalty for a wider (but still agreeing) spread; never below 0.5.
        spread_weight = max(0.5, 1.0 - spread / (2 * agreement))
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
        agreement = self.spec.scale_delta(FORECAST_AGREEMENT_SPREAD)
        spread = max(values) - min(values)
        if spread > agreement:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            anchor = ordered[mid]
        else:
            anchor = (ordered[mid - 1] + ordered[mid]) / 2.0
        spread_weight = max(0.5, 1.0 - spread / (2 * agreement))
        return self.round_half_up(anchor), spread_weight

    def forecast_soft_density(self, forecasts, support):
        """A smooth forecast distribution over the bucket ``support``: a Gaussian
        of width ~RMSE (``FORECAST_SOFT_SIGMA``) around each source's CONTINUOUS
        forecast value, averaged over sources.

        Unlike rounding the forecast to one bucket, this (1) stays stable across
        the x.5 rounding boundary (27.8 and 27.3 give near-identical densities),
        (2) spreads the forecast over its real uncertainty, and (3) caps how much
        any single source concentrates one bucket -- a sigma>=1.5 Gaussian puts at
        most ~27% of its mass on the centre bucket, and a multi-source mixture that
        disagrees spreads wider still. Returns ``{bucket: prob}`` or None.
        """
        vals = [float(v) for v in forecasts if v is not None]
        if not vals:
            return None
        sigma = max(0.5, self.spec.scale_delta(FORECAST_SOFT_SIGMA))
        density = {
            bucket: sum(math.exp(-0.5 * ((bucket - v) / sigma) ** 2) for v in vals)
            for bucket in support
        }
        total = sum(density.values())
        if total <= 0:
            return None
        return {bucket: value / total for bucket, value in density.items()}

    def apply_forecast_pull(self, scores, forecasts, hour, observed_bucket, current_observed_bucket):
        """Blend the distribution toward the SMOOTH forecast density early in the
        day, instead of forcing mass above a rounded point-anchor. The pull is
        one-sided at the median consensus bucket, so it raises an under-called
        forecast region without injecting fresh mass into buckets below the
        agreed forecast.

        Time-decayed to zero by mid-afternoon (the observed high then owns the
        call), and the downstream observed floors handle the low side. No-op when
        forecasts disagree (>spread), it is past mid-afternoon, or the observed
        high has already reached the forecast.
        """
        scores = self.normalize_scores(scores)
        anchor = self.forecast_anchor_bucket(forecasts)
        if anchor is None:
            return scores                            # too few sources or they disagree
        anchor_bucket, spread_weight = anchor
        reached = self.max_value(observed_bucket, current_observed_bucket)
        if reached is not None and anchor_bucket <= reached:
            return scores                            # observed high owns it now
        weight = self.forecast_pull_time_weight(hour) * spread_weight
        if weight <= 0:
            return scores
        density = self.forecast_soft_density(forecasts, list(scores.keys()))
        if not density:
            return scores
        blend = min(FORECAST_PULL_BLEND_MAX, weight)
        upper_density = {
            bucket: probability
            for bucket, probability in density.items()
            if bucket >= anchor_bucket
        }
        upper_total = sum(upper_density.values())
        if upper_total <= 0:
            return scores
        upper_density = {
            bucket: probability / upper_total
            for bucket, probability in upper_density.items()
        }
        blended = {
            bucket: (
                (1.0 - blend) * scores.get(bucket, 0.0)
                + blend * upper_density.get(bucket, 0.0)
            )
            for bucket in scores
        }
        return self.normalize_scores(blended)

    def forecast_error_component_distribution(
        self,
        support,
        observed_bucket,
        weather_forecast_max,
        open_meteo_max,
        eccc_forecast_high,
        hour,
        nws_forecast_max=None,
        global_ensemble_max=None,
    ):
        values = []
        if weather_forecast_max is not None:
            values.append({"source": "weather_forecast", "forecast_high_c": weather_forecast_max})
        if open_meteo_max is not None:
            values.append({"source": "open_meteo", "forecast_high_c": open_meteo_max})
        if eccc_forecast_high is not None:
            values.append({"source": "eccc_citypage", "forecast_high_c": eccc_forecast_high})
        if nws_forecast_max is not None:
            values.append({"source": "nws_hourly", "forecast_high_c": nws_forecast_max})
        if global_ensemble_max is not None:
            values.append({"source": "global_ensemble", "forecast_high_c": global_ensemble_max})
        return forecast_error_distribution(
            support,
            values,
            getattr(self, "forecast_error_model", None),
            floor_bucket=observed_bucket,
            capture_hour=hour,
        )
