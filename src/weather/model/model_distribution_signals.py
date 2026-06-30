"""Live observed and forecast signal helpers for distribution modeling."""

from __future__ import annotations

import math

from weather.model.calibration_runtime import (
    forecast_error_distribution,
    revision_up_probability,
    settlement_catchup_probability,
)
from weather.model.model_distribution_constants import (
    BUCKET_TRANSITION_BLEND_MAX,
    BUCKET_TRANSITION_MIN_SAMPLE,
    EXPANDED_LOCKIN_END_HOUR,
    EXPANDED_LOCKIN_FORECAST_MARGIN,
    EXPANDED_LOCKIN_MAX_STRENGTH,
    EXPANDED_LOCKIN_ROLLOVER_MARGIN,
    EXPANDED_LOCKIN_STAND_MINUTES,
    EXPANDED_LOCKIN_START_HOUR,
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
    CURRENT_MAX_BOUNDARY_CONFLICT_EXACT_CAP,
    LIVE_FLOOR_BASE,
    LIVE_FLOOR_HEDGE,
    LIVE_FLOOR_HEDGE_MAX,
    LIVE_FLOOR_HEDGE_MIN,
    METAR_LIVE_SIGNAL_MAX_WEIGHT,
    METAR_LIVE_SIGNAL_REACHED_BASELINE,
    METAR_LIVE_SIGNAL_SIGMA,
    STANDING_HIGH_PARTIAL_BASE,
    STANDING_HIGH_PARTIAL_END_HOUR,
    STANDING_HIGH_PARTIAL_FORECAST_AGREEMENT_SPREAD,
    STANDING_HIGH_PARTIAL_FORECAST_UPSIDE_MAX,
    STANDING_HIGH_PARTIAL_MAX_STRENGTH,
    STANDING_HIGH_PARTIAL_MIN_MINUTES,
    STANDING_HIGH_PARTIAL_ONE_UP_RETAINED,
    STANDING_HIGH_PARTIAL_ROLLOVER_MARGIN,
    STANDING_HIGH_PARTIAL_START_HOUR,
    STANDING_HIGH_PARTIAL_TWO_UP_RETAINED,
    VALIDATED_WU_MAX_HARD_FLOOR_MARKETS,
    WU_FLOOR_LIVE_SUPPORT_MIN_RESIDUAL,
)

class DistributionSignalMixin:
    def current_max_boundary_context(
        self,
        *,
        current_max,
        support_only_current_max=None,
        history_max=None,
        official_observations=None,
        current_max_disposition=None,
        current_max_state=None,
        hour=None,
    ):
        """Classify whether support-only current max is an exact-band risk."""

        official_observations = official_observations or {}
        current_bucket = self.round_half_up(
            support_only_current_max if support_only_current_max is not None else current_max
        )
        history_bucket = self.round_half_up(history_max)
        official_buckets = [
            self.round_half_up(value)
            for value in official_observations.values()
            if self.round_half_up(value) is not None
        ]
        official_bucket = max(official_buckets, default=None)
        disposition = str(current_max_disposition or "").strip().lower()
        state = str(current_max_state or "").strip().lower()
        context = {
            "active": False,
            "state": "stale",
            "reason": "missing_current_max",
            "market_id": getattr(self.spec, "id", None),
            "hour": hour,
            "current_max_bucket": current_bucket,
            "wu_history_floor_bucket": history_bucket,
            "official_observed_bucket": official_bucket,
            "current_max_disposition": disposition or None,
            "current_max_state": state or None,
            "exact_band_bucket": current_bucket,
            "printed_lower_bucket": history_bucket,
            "warmer_adjacent_bucket": current_bucket + 1 if current_bucket is not None else None,
            "cumulative_support_bucket": current_bucket,
            "exact_band_cap": None,
            "probability_before": None,
            "probability_after": None,
            "capped_probability": 0.0,
            "redistribution": {},
        }
        if current_bucket is None:
            return context
        if disposition in {"quarantined", "null_before_reset"}:
            context.update({"state": "stale", "reason": disposition})
            return context
        if history_bucket is not None and current_bucket <= history_bucket:
            context.update({"state": "confirmed", "reason": "covered_by_wu_history"})
            return context
        if official_bucket is not None and current_bucket <= official_bucket:
            context.update({"state": "confirmed", "reason": "confirmed_by_official_observation"})
            return context
        if disposition != "support_only":
            context.update({"state": "stale", "reason": disposition or "not_support_only"})
            return context
        if history_bucket is not None and current_bucket == history_bucket + 1:
            context.update({
                "state": "conflicting",
                "reason": "wu_history_one_bucket_lower_without_official_confirmation",
                "exact_band_cap": CURRENT_MAX_BOUNDARY_CONFLICT_EXACT_CAP,
                "active": str(getattr(self.spec, "id", "") or "").lower() == "toronto",
            })
            return context
        context.update({
            "state": "support_only",
            "reason": "support_only_without_one_bucket_conflict",
        })
        return context

    def apply_current_max_boundary_overlock_guard(self, scores, context, allocation_reference=None):
        """Cap exact current-max lock-in while redistributing through nearby risk.

        The cap is only active for the classified conflict state. Reallocation
        uses a pre-floor reference shape when available so excess probability
        follows the model's ordinary adjacent-bucket risk instead of being
        dumped into a single neighboring bucket.
        """

        normalized = self.normalize_scores(scores)
        context = dict(context or {})
        if not normalized:
            context.setdefault("reason", "empty_scores")
            return normalized, context
        bucket = context.get("exact_band_bucket")
        cap = context.get("exact_band_cap")
        if not context.get("active") or bucket is None or cap is None:
            return normalized, context
        bucket = int(bucket)
        cap = max(0.0, min(1.0, float(cap)))
        before = float(normalized.get(bucket, 0.0))
        context["probability_before"] = before
        if before <= cap:
            context.update({
                "reason": "exact_band_already_under_cap",
                "probability_after": before,
                "capped_probability": 0.0,
            })
            return normalized, context

        reference = self.normalize_scores(allocation_reference or {})
        history_bucket = context.get("printed_lower_bucket")
        warmer_bucket = context.get("warmer_adjacent_bucket")
        preferred = [
            int(value)
            for value in (history_bucket, warmer_bucket)
            if value is not None and int(value) != bucket
        ]
        recipients = [value for value in preferred if value in normalized]
        if not recipients:
            recipients = [value for value in sorted(normalized) if value != bucket]
        weights = {}
        for value in recipients:
            weight = float(reference.get(value, 0.0))
            if weight <= 0:
                weight = float(normalized.get(value, 0.0))
            if weight > 0:
                weights[value] = weight
        if not weights:
            weights = {value: 1.0 for value in recipients}
        total_weight = sum(weights.values())
        if total_weight <= 0:
            context.update({
                "reason": "no_redistribution_weight",
                "probability_after": before,
                "capped_probability": 0.0,
            })
            return normalized, context

        excess = before - cap
        adjusted = dict(normalized)
        adjusted[bucket] = cap
        redistribution = {}
        for value, weight in weights.items():
            moved = excess * (weight / total_weight)
            adjusted[value] = adjusted.get(value, 0.0) + moved
            redistribution[value] = moved
        adjusted = self.normalize_scores(adjusted)
        context.update({
            "reason": "exact_band_capped",
            "probability_after": float(adjusted.get(bucket, 0.0)),
            "capped_probability": excess,
            "redistribution": redistribution,
        })
        return adjusted, context

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
        """Market-scoped hard floor for validated WU current max-since-7am data.

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
        history_max = self.row_max_native(history)
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
                value = self.row_temp_native(row)
                if minute is not None and minute >= wall_minute and value is not None:
                    values.append(value)
            if not values and self.row_forecast_high_native(source) is not None:
                value = self.row_forecast_high_native(source)
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
            "remaining_forecast_values": sorted(source_maxes),
            "remaining_forecast_ceiling": max(source_maxes) if source_maxes else None,
            "remaining_forecast_floor": min(source_maxes) if source_maxes else None,
            "remaining_forecast_spread": (
                max(source_maxes) - min(source_maxes)
                if len(source_maxes) >= 2
                else 0.0 if source_maxes else None
            ),
            "remaining_forecast_robust_high": (
                sorted(source_maxes)[len(source_maxes) // 2]
                if len(source_maxes) % 2 == 1
                else (
                    sorted(source_maxes)[len(source_maxes) // 2 - 1]
                    + sorted(source_maxes)[len(source_maxes) // 2]
                ) / 2.0
                if source_maxes
                else None
            ),
            "remaining_degree_hours_above_high": degree_hours_above_high,
        }

    def high_has_stood_lockin_context(
        self,
        hour,
        history,
        current_reading,
        now,
        *forecast_sources,
        official_current_reading=None,
        official_source=None,
        official_current_stale=False,
    ):
        context = {
            "active": False,
            "strength": 0.0,
            "reason": "inactive",
            "stood_minutes": None,
            "current_minus_high": None,
            "third_party_current_reading": self.to_number(current_reading),
            "third_party_current_minus_high": None,
            "official_current_reading": self.to_number(official_current_reading),
            "official_current_minus_high": None,
            "official_source": official_source,
            "official_current_stale": bool(official_current_stale),
            "official_rollover_signal": False,
            "current_source_for_rollover": None,
            "remaining_forecast_ceiling": None,
            "remaining_degree_hours_above_high": None,
            "forecast_source_count": 0,
            "revision_up_rate": None,
        }
        if hour < HIGH_HAS_STOOD_START_HOUR or hour > HIGH_HAS_STOOD_END_HOUR:
            context["reason"] = "outside_hour_window"
            return context
        history_max = self.row_max_native(history)
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
        official_value = self.to_number(official_current_reading)
        if current_value is None and official_value is None:
            context["reason"] = "missing_current_reading"
            return context
        current_minus_high = current_value - history_max if current_value is not None else None
        official_minus_high = official_value - history_max if official_value is not None else None
        context["third_party_current_minus_high"] = current_minus_high
        context["official_current_minus_high"] = official_minus_high
        rollover_threshold = -self.spec.scale_delta(HIGH_HAS_STOOD_ROLLOVER_MARGIN)
        third_party_rollover = (
            current_minus_high is not None
            and current_minus_high <= rollover_threshold
        )
        official_rollover = (
            not official_current_stale
            and official_minus_high is not None
            and official_minus_high <= rollover_threshold
        )
        stale_official_rollover = (
            bool(official_current_stale)
            and official_minus_high is not None
            and official_minus_high <= rollover_threshold
        )
        used_official_rollover = False
        if third_party_rollover:
            context["current_source_for_rollover"] = "third_party_current"
        elif official_rollover:
            current_minus_high = official_minus_high
            used_official_rollover = True
            context["official_rollover_signal"] = True
            context["current_source_for_rollover"] = official_source or "official"
        else:
            context["current_source_for_rollover"] = "third_party_current" if current_value is not None else (official_source or "official")
        context["current_minus_high"] = current_minus_high
        if not third_party_rollover and not official_rollover:
            context["reason"] = "official_current_stale" if stale_official_rollover else "current_not_below_high"
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
        context["reason"] = (
            "high_stood_official_rollover_forecasts_below"
            if used_official_rollover
            else "high_stood_current_rolled_forecasts_below"
        )
        return context

    def expanded_late_day_lockin_context(
        self,
        hour,
        history,
        current_reading,
        now,
        *forecast_sources,
        official_current_reading=None,
        official_source=None,
        official_current_stale=False,
    ):
        """Broader late-day lock-in coverage for a high that has stood.

        This fills the gap between the strict 13-15h high-has-stood gate and
        the learned evening revision-up curve. It stays soft and traceable:
        current temperature must have rolled below the printed high, and any
        remaining forecast ceiling must not be materially above that high.
        """
        context = {
            "active": False,
            "strength": 0.0,
            "reason": "inactive",
            "stood_minutes": None,
            "current_minus_high": None,
            "third_party_current_reading": self.to_number(current_reading),
            "third_party_current_minus_high": None,
            "official_current_reading": self.to_number(official_current_reading),
            "official_current_minus_high": None,
            "official_source": official_source,
            "official_current_stale": bool(official_current_stale),
            "official_rollover_signal": False,
            "current_source_for_rollover": None,
            "remaining_forecast_ceiling": None,
            "remaining_degree_hours_above_high": None,
            "forecast_source_count": 0,
        }
        if hour < EXPANDED_LOCKIN_START_HOUR or hour > EXPANDED_LOCKIN_END_HOUR:
            context["reason"] = "outside_hour_window"
            return context
        history_max = self.row_max_native(history)
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
        if stood_minutes < EXPANDED_LOCKIN_STAND_MINUTES:
            context["reason"] = "high_not_stood_long_enough"
            return context
        current_value = self.to_number(current_reading)
        official_value = self.to_number(official_current_reading)
        if current_value is None and official_value is None:
            context["reason"] = "missing_current_reading"
            return context
        rollover_margin = self.spec.scale_delta(EXPANDED_LOCKIN_ROLLOVER_MARGIN)
        rollover_threshold = -rollover_margin
        current_minus_high = current_value - history_max if current_value is not None else None
        official_minus_high = official_value - history_max if official_value is not None else None
        context["third_party_current_minus_high"] = current_minus_high
        context["official_current_minus_high"] = official_minus_high
        third_party_rollover = (
            current_minus_high is not None
            and current_minus_high <= rollover_threshold
        )
        official_rollover = (
            not official_current_stale
            and official_minus_high is not None
            and official_minus_high <= rollover_threshold
        )
        stale_official_rollover = (
            bool(official_current_stale)
            and official_minus_high is not None
            and official_minus_high <= rollover_threshold
        )
        used_official_rollover = False
        if third_party_rollover:
            context["current_source_for_rollover"] = "third_party_current"
        elif official_rollover:
            current_minus_high = official_minus_high
            used_official_rollover = True
            context["official_rollover_signal"] = True
            context["current_source_for_rollover"] = official_source or "official"
        else:
            context["current_source_for_rollover"] = "third_party_current" if current_value is not None else (official_source or "official")
        context["current_minus_high"] = current_minus_high
        if not third_party_rollover and not official_rollover:
            context["reason"] = "official_current_stale" if stale_official_rollover else "current_not_below_high"
            return context

        forecast_context = self.remaining_forecast_context(now, history_max, *forecast_sources)
        context.update(forecast_context)
        ceiling = forecast_context["remaining_forecast_ceiling"]
        forecast_margin = self.spec.scale_delta(EXPANDED_LOCKIN_FORECAST_MARGIN)
        if ceiling is not None and ceiling > history_max + forecast_margin:
            context["reason"] = "forecast_ceiling_above_high"
            return context

        hour_span = max(1, EXPANDED_LOCKIN_END_HOUR - EXPANDED_LOCKIN_START_HOUR)
        time_progress = max(
            0.0,
            min(1.0, (hour - EXPANDED_LOCKIN_START_HOUR) / hour_span),
        )
        stood_progress = max(
            0.0,
            min(1.0, stood_minutes / max(1, EXPANDED_LOCKIN_STAND_MINUTES * 2)),
        )
        drop_progress = max(
            0.0,
            min(
                1.0,
                (-current_minus_high)
                / max(self.spec.scale_delta(LATE_LOCKIN_PEAK_DROP), 0.1),
            ),
        )
        strength = 0.25 + 0.35 * time_progress + 0.15 * stood_progress + 0.25 * drop_progress
        context["active"] = True
        context["strength"] = max(0.0, min(EXPANDED_LOCKIN_MAX_STRENGTH, strength))
        context["reason"] = (
            "expanded_late_day_official_rollover"
            if used_official_rollover
            else "expanded_late_day_current_below_high"
        )
        return context

    def standing_high_partial_lockin_context(
        self,
        hour,
        history,
        current_reading,
        now,
        *forecast_sources,
        official_current_reading=None,
        official_source=None,
        official_current_stale=False,
    ):
        """Soft late-day dampener for a stood high with fresh official rollover.

        This stage is deliberately weaker than the hard high-has-stood gates:
        modest warm forecast ceilings reduce the strength instead of blocking
        the stage outright, and the apply helper keeps one/two-up rebound
        buckets alive.
        """

        context = {
            "active": False,
            "stage": "no_action",
            "strength": 0.0,
            "reason": "inactive",
            "stood_minutes": None,
            "current_minus_high": None,
            "third_party_current_reading": self.to_number(current_reading),
            "third_party_current_minus_high": None,
            "official_current_reading": self.to_number(official_current_reading),
            "official_current_minus_high": None,
            "official_source": official_source,
            "official_current_stale": bool(official_current_stale),
            "remaining_forecast_ceiling": None,
            "remaining_forecast_robust_high": None,
            "remaining_forecast_spread": None,
            "remaining_forecast_values": [],
            "forecast_source_count": 0,
            "forecast_upside": None,
            "forecast_agreement_factor": None,
            "forecast_upside_factor": None,
            "time_factor": None,
            "stood_factor": None,
            "official_drop_factor": None,
            "live_source_consistency_factor": None,
            "live_source_consistency": None,
        }
        if hour < STANDING_HIGH_PARTIAL_START_HOUR or hour > STANDING_HIGH_PARTIAL_END_HOUR:
            context["reason"] = "outside_hour_window"
            return context
        history_max = self.row_max_native(history)
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
        if stood_minutes < STANDING_HIGH_PARTIAL_MIN_MINUTES:
            context["reason"] = "high_not_stood_long_enough"
            return context

        official_value = self.to_number(official_current_reading)
        if official_value is None:
            context["reason"] = "missing_official_current"
            return context
        official_minus_high = official_value - history_max
        context["official_current_minus_high"] = official_minus_high
        rollover_threshold = -self.spec.scale_delta(STANDING_HIGH_PARTIAL_ROLLOVER_MARGIN)
        if official_current_stale and official_minus_high <= rollover_threshold:
            context["reason"] = "official_current_stale"
            return context
        if official_current_stale:
            context["reason"] = "official_current_stale"
            return context
        if official_minus_high > rollover_threshold:
            context["reason"] = "official_current_not_below_high"
            return context

        current_value = self.to_number(current_reading)
        current_minus_high = current_value - history_max if current_value is not None else None
        context["third_party_current_minus_high"] = current_minus_high
        context["current_minus_high"] = official_minus_high
        live_margin = self.spec.scale_delta(STANDING_HIGH_PARTIAL_ROLLOVER_MARGIN)
        if current_minus_high is None:
            consistency_factor = 0.85
            consistency = "missing_third_party_current"
        elif current_minus_high > live_margin:
            consistency_factor = 0.35
            consistency = "third_party_current_above_high"
        elif current_minus_high > 0:
            consistency_factor = 0.65
            consistency = "third_party_current_slightly_above_high"
        else:
            consistency_factor = 1.0
            consistency = "third_party_current_consistent_or_flat"
        context["live_source_consistency_factor"] = consistency_factor
        context["live_source_consistency"] = consistency

        forecast_context = self.remaining_forecast_context(now, history_max, *forecast_sources)
        context.update(forecast_context)
        if forecast_context["forecast_source_count"] <= 0:
            context["reason"] = "missing_remaining_forecasts"
            return context
        ceiling = forecast_context["remaining_forecast_ceiling"]
        upside = max(0.0, ceiling - history_max) if ceiling is not None else 0.0
        context["forecast_upside"] = upside
        max_upside = self.spec.scale_delta(STANDING_HIGH_PARTIAL_FORECAST_UPSIDE_MAX)
        if ceiling is not None and ceiling > history_max + max_upside:
            context["reason"] = "forecast_ceiling_too_high_for_partial"
            return context
        spread = forecast_context.get("remaining_forecast_spread")
        agreement_margin = self.spec.scale_delta(STANDING_HIGH_PARTIAL_FORECAST_AGREEMENT_SPREAD)
        if spread is None:
            agreement_factor = 0.80
        elif spread <= agreement_margin:
            agreement_factor = 1.0
        else:
            agreement_factor = max(
                0.45,
                1.0 - 0.40 * min(1.0, (spread - agreement_margin) / max(agreement_margin, 0.1)),
            )
        upside_factor = 1.0 - 0.40 * min(1.0, upside / max(max_upside, 0.1))
        context["forecast_agreement_factor"] = agreement_factor
        context["forecast_upside_factor"] = upside_factor

        hour_span = max(1, STANDING_HIGH_PARTIAL_END_HOUR - STANDING_HIGH_PARTIAL_START_HOUR)
        time_factor = max(0.0, min(1.0, (hour - STANDING_HIGH_PARTIAL_START_HOUR) / hour_span))
        stood_factor = max(
            0.0,
            min(1.0, stood_minutes / max(1, STANDING_HIGH_PARTIAL_MIN_MINUTES * 2)),
        )
        drop_factor = max(
            0.0,
            min(
                1.0,
                (-official_minus_high)
                / max(self.spec.scale_delta(LATE_LOCKIN_PEAK_DROP), 0.1),
            ),
        )
        context["time_factor"] = time_factor
        context["stood_factor"] = stood_factor
        context["official_drop_factor"] = drop_factor
        raw_strength = (
            STANDING_HIGH_PARTIAL_BASE
            + 0.14 * time_factor
            + 0.16 * stood_factor
            + 0.20 * drop_factor
        )
        strength = (
            raw_strength
            * agreement_factor
            * upside_factor
            * consistency_factor
        )
        strength = max(0.0, min(STANDING_HIGH_PARTIAL_MAX_STRENGTH, strength))
        if strength <= 0:
            context["reason"] = "strength_zero"
            return context
        context["active"] = True
        context["stage"] = "partial_dampening"
        context["strength"] = strength
        context["reason"] = (
            "standing_high_partial_official_rollover_warm_forecast"
            if upside > self.spec.scale_delta(STANDING_HIGH_PARTIAL_ROLLOVER_MARGIN)
            else "standing_high_partial_official_rollover"
        )
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

    def apply_standing_high_partial_lockin(self, scores, history_max, context):
        """Apply the stood-high partial dampener and annotate tail movement."""

        context = dict(context or {})
        normalized = self.normalize_scores(scores)
        observed_bucket = self.round_half_up(history_max)
        if not context.get("active") or observed_bucket is None:
            context.setdefault("stage", "no_action")
            return normalized, context
        strength = max(0.0, min(1.0, float(context.get("strength") or 0.0)))
        before_above = sum(
            probability for bucket, probability in normalized.items()
            if bucket > observed_bucket
        )
        before_one_up = float(normalized.get(observed_bucket + 1, 0.0))
        before_two_up = float(normalized.get(observed_bucket + 2, 0.0))
        adjusted = {}
        for temp, score in normalized.items():
            if temp <= observed_bucket:
                adjusted[temp] = score
                continue
            above = temp - observed_bucket
            if above == 1:
                full_retained = STANDING_HIGH_PARTIAL_ONE_UP_RETAINED
            elif above == 2:
                full_retained = STANDING_HIGH_PARTIAL_TWO_UP_RETAINED
            else:
                full_retained = STANDING_HIGH_PARTIAL_TWO_UP_RETAINED * (
                    STANDING_HIGH_PARTIAL_BASE ** (above - 2)
                )
            factor = (1.0 - strength) + strength * full_retained
            adjusted[temp] = score * factor
        out = self.normalize_scores(adjusted)
        after_above = sum(
            probability for bucket, probability in out.items()
            if bucket > observed_bucket
        )
        after_one_up = float(out.get(observed_bucket + 1, 0.0))
        after_two_up = float(out.get(observed_bucket + 2, 0.0))
        context.update({
            "stage": "partial_dampening",
            "observed_bucket": observed_bucket,
            "tail_mass_above_high_before": before_above,
            "tail_mass_above_high_after": after_above,
            "tail_mass_above_high_delta": after_above - before_above,
            "moved_probability": max(0.0, before_above - after_above),
            "one_up_tail_before": before_one_up,
            "one_up_tail_after": after_one_up,
            "two_up_tail_before": before_two_up,
            "two_up_tail_after": after_two_up,
            "one_up_tail_preserved": after_one_up > 0.0,
            "two_up_tail_preserved": after_two_up > 0.0,
        })
        return out, context

    def unfalsified_forecasts(self, forecasts, history, now):
        """Drop forecast values the observed day has falsified, for the
        floor/pull votes only. Falsified = past the peak window, the printed
        WU high has stood unimproved for FALSIFICATION_STAND_MINUTES, and the
        source still claims more than FALSIFICATION_MARGIN above it. If the
        high later rises, max_times resets and benched sources are readmitted.
        """
        if now.hour < FALSIFICATION_EARLIEST_HOUR:
            return forecasts
        history_max = self.row_max_native(history)
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
            values.append({"source": "weather_forecast", "value": weather_forecast_max})
        if open_meteo_max is not None:
            values.append({"source": "open_meteo", "value": open_meteo_max})
        if eccc_forecast_high is not None:
            values.append({"source": "eccc_citypage", "value": eccc_forecast_high})
        if nws_forecast_max is not None:
            values.append({"source": "nws_hourly", "value": nws_forecast_max})
        if global_ensemble_max is not None:
            values.append({"source": "global_ensemble", "value": global_ensemble_max})
        return forecast_error_distribution(
            support,
            values,
            getattr(self, "forecast_error_model", None),
            floor_bucket=observed_bucket,
            capture_hour=hour,
        )
