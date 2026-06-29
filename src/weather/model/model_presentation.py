import json
import re
from datetime import datetime
from weather.model.model_constants import (
    DEFAULT_MARKET_CONFIG,
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
from weather.model.calibration_runtime import (
    apply_continuous_density_calibration,
    calibrate_market_probability,
)
from weather.model.continuous_density import (
    band_probability_from_distribution,
    is_continuous_density_payload,
)
from weather.sources.marine_context import active_marine_context_state


# --- Quantitative driver breakdown (item 12) --------------------------------
# estimate_distribution builds the final distribution as an ordered pipeline and
# records a snapshot of the RUNNING distribution after each stage into
# distribution_components. The quantitative contribution of a stage to a bucket
# is therefore the change it made to that bucket's probability. Because every
# stage below is a running snapshot of the full distribution, the per-bucket
# deltas telescope: baseline + sum(deltas) == the final probability exactly.
DRIVER_WATERFALL_STAGES = (
    ("climatology_prior", "Base climatology"),
    # feature_blend (ML path) and empirical_weighted (calibrated-empirical path)
    # are mutually exclusive and occupy the same pipeline slot.
    ("feature_blend", "ML feature blend"),
    ("empirical_weighted", "Empirical component blend"),
    ("post_live_signals", "Live-signal sharpening"),
    ("forecast_pull", "Forecast floor / pull"),
    ("settlement_lag_adjusted", "Settlement-lag (SWOB) floor"),
    ("current_observed_floor", "Current-observed floor"),
    ("high_has_stood_lockin", "High-has-stood lock-in"),
    ("standing_high_partial_lockin", "Standing-high partial dampener"),
    ("late_day_lockin", "Late-day lock-in"),
    ("overconfidence_calibration", "Overconfidence calibration"),
    ("current_max_boundary_guard", "Current-max boundary guard"),
    ("final_model", "Final model"),
)

# Standalone INPUT distributions (not running snapshots): each is one driver's
# independent opinion of the final bucket, shown for context next to the
# telescoping waterfall. The feature-model raw key is resolved dynamically
# because it is named for the active model kind (hgb_/lr_feature_model).
DRIVER_INPUT_COMPONENTS = (
    ("intraday_high", "Intraday high-so-far analogs"),
    ("current_bucket", "Current-temperature bucket"),
    ("wind_regime", "Wind-regime analogs"),
    ("cloud_regime", "Cloud-regime analogs"),
    ("forecast_error", "Forecast-error distribution"),
    ("forecast_cap", "Forecast cap"),
)


def _component_prob(distribution, bucket):
    """Read a bucket probability from a component distribution, tolerating both
    int keys (live in-memory build) and str keys (JSON-loaded snapshot tape)."""
    if not distribution:
        return 0.0
    if bucket in distribution:
        return float(distribution[bucket])
    key = str(bucket)
    if key in distribution:
        return float(distribution[key])
    return 0.0


def _diagnostic_only_input_families(component_payload):
    preflight = (component_payload or {}).get("weak_input_family_preflight") or {}
    families = set(preflight.get("diagnostic_only_families") or [])
    disposition = (component_payload or {}).get("weak_input_family_disposition") or {}
    for row in disposition.get("families") or []:
        if row.get("disposition") in {"diagnostic_only", "regime_backfill", "remove"}:
            family = row.get("family")
            if family:
                families.add(family)
    return sorted(families)


def _family_is_diagnostic_only(component_payload, *family_names):
    families = set(_diagnostic_only_input_families(component_payload))
    return any(name in families for name in family_names)


def driver_waterfall(components, buckets):
    """Telescoping per-bucket probability waterfall over the running pipeline
    stages present in ``components`` (a distribution_components ``components``
    mapping). Returns a list of ``(key, label, {bucket: contribution})``: the
    first present stage carries the absolute baseline probability and every later
    stage carries its signed delta from the previous stage, so for each bucket
    ``baseline + sum(deltas) == final-stage probability``."""
    rows = []
    prev = None
    for key, label in DRIVER_WATERFALL_STAGES:
        distribution = components.get(key)
        if not distribution:
            continue
        contributions = {}
        for bucket in buckets:
            current = _component_prob(distribution, bucket)
            contributions[bucket] = current if prev is None else current - _component_prob(prev, bucket)
        rows.append((key, label, contributions))
        prev = distribution
    return rows


class PresentationMixin:
    """Dashboard/snapshot view rows, market-bin parsing, and value formatting."""

    def model_market_rows(self, event, distribution, distribution_result=None):
        bins = self.market_bins(event)
        calibration_context = (
            distribution_result.calibration_context
            if distribution_result is not None
            else None
        )
        rows = []
        for bin_data in bins:
            model_prob = self.bin_probability(
                distribution,
                bin_data,
                calibration_context=calibration_context,
            )
            market_yes = bin_data.get("market_yes")
            edge = model_prob - market_yes if market_yes is not None else None
            rows.append({
                "Range": bin_data["label"],
                "Model": self.format_pct(model_prob),
                "Market yes": self.format_pct(market_yes),
                "Edge": self.format_signed_pct(edge),
                "Market status": bin_data.get("status"),
            })
        return rows

    def market_bins(self, event):
        bins = []
        for market in event.get("markets", []) or []:
            label = self.clean_label(
                market.get("groupItemTitle") or market.get("question", "")
            )
            outcomes = self.parse_json_list(market.get("outcomes"))
            prices = self.parse_json_list(market.get("outcomePrices"))
            token_ids = self.parse_json_list(
                market.get("clobTokenIds") or market.get("clob_token_ids")
            )
            market_yes = self.price_for_outcome("Yes", outcomes, prices)
            market_no = self.price_for_outcome("No", outcomes, prices)
            clob_yes_token_id = self.token_for_outcome("Yes", outcomes, token_ids)
            clob_no_token_id = self.token_for_outcome("No", outcomes, token_ids)
            digits = [int(value) for value in re.findall(r"\d+", label)]
            if not digits:
                continue
            value = digits[0]
            value_hi = digits[-1]  # range bands ("76-77F") carry a second number
            lower_label = label.lower()
            if "below" in lower_label:
                bin_data = {"kind": "lte", "value": value, "value_hi": value}
            elif "higher" in lower_label or "above" in lower_label:
                bin_data = {"kind": "gte", "value": value, "value_hi": value}
            else:
                bin_data = {"kind": "eq", "value": value, "value_hi": value_hi}
            bin_data.update({
                "unit": self.spec.display_unit,
                "label": label,
                "question": market.get("question"),
                "market_id": market.get("id") or market.get("conditionId"),
                "polymarket_market_id": market.get("id"),
                "condition_id": market.get("conditionId") or market.get("condition_id"),
                "clob_token_ids": json.dumps(token_ids),
                "clob_yes_token_id": clob_yes_token_id,
                "clob_no_token_id": clob_no_token_id,
                "enable_order_book": market.get("enableOrderBook"),
                "market_yes": market_yes,
                "market_no": market_no,
                "best_bid": self.to_number(market.get("bestBid")),
                "best_ask": self.to_number(market.get("bestAsk")),
                "last_trade_price": self.to_number(market.get("lastTradePrice")),
                "volume": self.to_number(market.get("volumeNum") or market.get("volume")),
                "liquidity": self.to_number(
                    market.get("liquidityNum") or market.get("liquidity")
                ),
                "status": self.market_status(market),
            })
            bins.append(bin_data)
        return sorted(bins, key=self.bin_sort_key)

    def source_rows(self, sources):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        metar = self.source_data(sources, "metar")
        marine_context = self.source_data(sources, "marine_context")

        rows = []
        rows.append({
            "Source": "Wunderground history proxy",
            "Signal": "Printed history high",
            "Value": self.format_temp(self.row_max_native(history)),
            "Detail": ", ".join(history.get("max_times") or []) or "-",
            "Model role": "Primary settlement proxy",
        })
        latest = history.get("latest") or {}
        rows.append({
            "Source": "Wunderground history proxy",
            "Signal": "Latest printed row",
            "Value": self.format_temp(self.row_temp_native(latest)),
            "Detail": latest.get("time", "-"),
            "Model role": "Confirms table trend",
        })
        rows.append({
            "Source": f"Weather.com current {self.spec.icao}",
            "Signal": "Current / max since 7 AM",
            "Value": (
                f"{self.format_temp(self.row_temp_native(current))} / "
                f"{self.format_temp(self.row_max_since_7am_native(current))}"
            ),
            "Detail": current.get("time", "-"),
            "Model role": "Same data family, discounted until in history",
        })
        local_analysis = local_history.get("analysis") or {}
        rows.append({
            "Source": "Local WU history",
            "Signal": "+/-7 day prior + intraday analogs",
            "Value": (
                f"{self.spec.key_bucket} {self.spec.display_unit} {self.format_pct(local_history.get('prob_key'))}"
                if local_history.get("prob_key") is not None else "-"
            ),
            "Detail": (
                f"{local_analysis.get('target_window_count', 0)} days; "
                f">={self.spec.key_bucket} {self.spec.display_unit} {self.format_pct(local_history.get('prob_key_plus'))}"
                if local_history.get("available") else local_history.get("reason", "-")
            ),
            "Model role": "Empirical prior, catch-up, and late-day tail",
        })
        eccc_latest = eccc.get("latest") or {}
        rows.append({
            "Source": f"ECCC SWOB {self.spec.icao}",
            "Signal": "Air / same-day max",
            "Value": (
                f"{self.format_temp(self.row_air_temp_native(eccc_latest))} / "
                f"{self.format_temp(self.row_same_day_max_native(eccc))}"
            ),
            "Detail": eccc_latest.get("time", "-"),
            "Model role": "Official station support, non-resolution",
        })
        rows.append({
            "Source": "Environment Canada forecast",
            "Signal": "Public forecast high",
            "Value": self.format_temp(self.row_forecast_high_native(eccc_city)),
            "Detail": eccc_city.get("forecast_cloud", "-"),
            "Model role": "Official forecast, non-resolution",
        })
        rows.append({
            "Source": f"METAR {self.spec.icao}",
            "Signal": "Hourly airport report",
            "Value": self.format_temp(self.row_temp_native(metar)),
            "Detail": metar.get("report_time", "-"),
            "Model role": "Hourly sanity check",
        })
        marine_state = active_marine_context_state(
            marine_context,
            current_temp_native=self.row_temp_native(current),
        )
        if marine_state:
            rows.append({
                "Source": "Marine/lake-breeze context",
                "Signal": marine_state.get("regime", "-").replace("_", " "),
                "Value": (
                    f"water {self.format_temp(marine_state.get('water_temp_native'))}; "
                    f"air {self.format_temp(marine_state.get('air_temp_native'))}"
                ),
                "Detail": (
                    f"{', '.join(marine_state.get('station_ids') or []) or '-'}; "
                    f"age {marine_state.get('latest_age_minutes')} min"
                ),
                "Model role": "Gated coastal/lake-breeze context, non-resolution",
            })
        return rows

    def deep_dive_rows(self, sources, distribution, analogs_data=None, now=None, focus_bucket=None):
        # Bucket-agnostic (item 12): the deep dive explains whichever bucket the
        # caller asks about, defaulting to the model's current top bucket rather
        # than the fixed seasonal key bucket. Falls back to key_bucket only when
        # there is no distribution yet.
        if focus_bucket is None:
            focus_bucket = (
                int(max(distribution, key=distribution.get))
                if distribution else self.spec.key_bucket
            )
        kb = focus_bucket
        u = self.spec.display_unit
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")

        rows = []

        # All source values below are already in the market's native unit;
        # comparisons against key_bucket are direct. scale_delta keeps the
        # "extremely close" margin one PHYSICAL degree C in either unit.
        impact_key = f"Impact on {kb} {u}"

        # 1. Wunderground History
        hist_max = self.row_max_native(history)
        if hist_max is None:
            impact = f"No historical printed observations yet. {kb} {u} is wide open."
        elif hist_max >= kb:
            impact = f"Guaranteed floor. Printed high is already {self.format_temp(hist_max)} (>= {kb} {u})."
        elif hist_max >= kb - self.spec.scale_delta(1.0):
            impact = f"Extremely close. Needs only +{self.spec.scale_delta(1.0):.1f} {u} to reach {kb} {u}."
        else:
            impact = f"Printed high is {self.format_temp(hist_max)}. Needs {kb - hist_max:.1f} {u} rise."
        rows.append({
            "Question": "What has Wunderground history printed?",
            "Answer": self.format_temp(hist_max),
            impact_key: impact,
        })

        # 2. Weather.com Current
        curr_temp = self.row_temp_native(current)
        max_7am = self.row_max_since_7am_native(current)
        if max_7am is not None and max_7am >= kb:
            impact = f"Strong indicator. Max since 7 AM is {self.format_temp(max_7am)}, which matches or exceeds {kb} {u}."
        elif curr_temp is not None and curr_temp >= kb:
            impact = f"Very bullish. Live temperature is already {self.format_temp(curr_temp)}."
        else:
            impact = f"Current temp is {self.format_temp(curr_temp)}; max since 7 AM is {self.format_temp(max_7am)}."
        rows.append({
            "Question": "What does Weather.com current say?",
            "Answer": f"current {self.format_temp(curr_temp)}, max since 7 AM {self.format_temp(max_7am)}",
            impact_key: impact,
        })

        # 3. ECCC SWOB
        swob_max = self.row_same_day_max_native(eccc)
        if swob_max is not None and swob_max >= kb:
            impact = (
                f"Station support. SWOB same-day max is {self.format_temp(swob_max)}, "
                f"supporting >= {kb} {u}; it remains non-resolution until WU history prints it."
            )
        elif swob_max is not None:
            impact = f"Station SWOB max is {self.format_temp(swob_max)}, trailing {kb} {u} by {kb - swob_max:.1f} {u}."
        else:
            impact = "No live SWOB observations yet."
        rows.append({
            "Question": "What does the official station (SWOB) support?",
            "Answer": self.format_temp(swob_max),
            impact_key: impact,
        })

        # 4. Weather.com hourly forecast
        fc_max = self.max_row_temp(weather_forecast.get("rows"))
        if fc_max is not None and fc_max >= kb:
            impact = f"Bullish. Hourly forecast projects high will reach {self.format_temp(fc_max)}."
        elif fc_max is not None:
            impact = f"Bearish forecast. Peak forecast is {self.format_temp(fc_max)}, suggesting {kb} {u} will not be reached."
        else:
            impact = "No forecast data available."
        rows.append({
            "Question": "What does Weather.com forecast for remaining hours?",
            "Answer": self.format_temp(fc_max),
            impact_key: impact,
        })

        # 5. Open-Meteo & ECCC Citypage
        om_max = self.max_row_temp(open_meteo.get("rows"))
        ec_high = self.row_forecast_high_native(eccc_city)
        alt_max = max([val for val in [om_max, ec_high] if val is not None], default=None)
        if alt_max is not None and alt_max >= kb:
            impact = f"Bullish alternative forecast. Alt models project a high of {self.format_temp(alt_max)}."
        elif alt_max is not None:
            impact = f"Bearish. Alternative models peak at {self.format_temp(alt_max)}."
        else:
            impact = "No alternative forecast data."
        rows.append({
            "Question": f"What says {kb} {u} or higher is live?",
            "Answer": f"Open-Meteo max {self.format_temp(om_max)}, ECCC forecast high {self.format_temp(ec_high)}",
            impact_key: impact,
        })

        # 6. Local WU History -- seasonal base rate for the focus bucket (not the
        # fixed key bucket), read from the per-bucket seasonal distribution.
        bucket_probs = (local_history.get("analysis") or {}).get("bucket_probabilities") or {}
        base_rate = bucket_probs.get(kb, bucket_probs.get(str(kb)))
        if base_rate is not None:
            impact = f"Historical seasonal base rate for {kb} {u} is {float(base_rate)*100:.1f}%."
        elif local_history.get("available"):
            impact = f"Seasonal history available but no day in-window settled at exactly {kb} {u}."
        else:
            impact = "No local history available."
        rows.append({
            "Question": "What does local WU history say?",
            "Answer": self.local_history_answer(local_history),
            impact_key: impact,
        })

        # 7. Intraday Analogs
        if analogs_data is None:
            now = now or datetime.now(self.spec.tz)
            history_rows = self.source_data(sources, "wu_history").get("rows") or []
            analogs_data = self.find_analog_days(
                sources,
                self.effective_intraday_cutoff_hour(now, history_rows),
                now,
            )
        analog_n = 0
        analog_prob = 0.0
        if isinstance(analogs_data, dict):
            analogs = analogs_data.get("analogs", [])
            analog_n = len(analogs)
            if analog_n > 0:
                count_focus = sum(1 for d in analogs if d["final_bucket"] == kb)
                analog_prob = count_focus / analog_n
        if analog_n > 0:
            impact = f"Of the closest {analog_n} historical analogs, {analog_prob*100:.0f}% resolved to exactly {kb} {u}."
        else:
            impact = "Insufficient analog days to evaluate."
        rows.append({
            "Question": "What do historical analogs say?",
            "Answer": f"{analog_n} analogs found",
            impact_key: impact,
        })

        # 8. Model probability
        prob_exact = distribution.get(kb, 0.0)
        rows.append({
            "Question": f"Model probability for exact {kb} {u}",
            "Answer": self.format_pct(prob_exact),
            impact_key: f"Final model assigns {prob_exact*100:.1f}% probability to the exact {kb} {u} bucket.",
        })

        return rows

    def get_model_explanation(self, sources, distribution, distribution_result=None):
        # 1. Active regimes and signals
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        eccc_city = self.source_data(sources, "eccc_citypage")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")
        marine_context = self.source_data(sources, "marine_context")
        
        history_max = self.row_max_native(history)
        current_temp = self.row_temp_native(current)
        observed_bucket = self.round_half_up(history_max)
        
        weather_forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        open_meteo_max = self.max_row_temp(open_meteo.get("rows"))
        eccc_forecast_high = self.row_forecast_high_native(eccc_city)
        
        plausible_cap = self.round_half_up(self.max_value(
            observed_bucket,
            weather_forecast_max,
            open_meteo_max,
            eccc_forecast_high,
        ))
        
        wind_group = self.live_wind_group(current, weather_forecast)
        cloud_group = self.live_cloud_group(current, eccc_city, weather_forecast)
        marine_state = active_marine_context_state(
            marine_context,
            current_temp_native=current_temp,
        )
        
        # 2. Top buckets in final distribution
        top_buckets = sorted(distribution.items(), key=lambda x: x[1], reverse=True)[:3]
        focus_buckets = [int(temp) for temp, _ in top_buckets]

        # 3. Model type
        model_type = self.get_model_version_string()
        component_payload = (
            distribution_result.component_payload
            if distribution_result is not None
            else getattr(self, "_last_distribution_components", {}) or {}
        )

        explanation = {
            "model_type": model_type,
            "feature_cutoff_hour": component_payload.get("cutoff_hour"),
            "latest_wu_history_time": component_payload.get("latest_wu_history_time"),
            "latest_wu_history_temp": component_payload.get("latest_wu_history_temp"),
            "high_has_stood_lockin": component_payload.get("high_has_stood_lockin"),
            "current_max_boundary": component_payload.get("current_max_boundary"),
            "observed_floor": observed_bucket,
            "forecast_cap": plausible_cap,
            "wind_regime": wind_group,
            "cloud_regime": cloud_group,
            "top_buckets": [
                {
                    "bucket": f"{temp} {self.spec.display_unit}",
                    "probability": self.format_pct(prob),
                    "status": "Floor constraint" if observed_bucket is not None and temp < observed_bucket else (
                        "Cap constraint" if plausible_cap is not None and temp > plausible_cap + 1 else "Primary projection"
                    )
                }
                for temp, prob in top_buckets
            ],
            # Quantitative, bucket-agnostic contribution of every pipeline driver
            # to the top buckets' final probabilities (item 12).
            "driver_breakdown": self.driver_breakdown(
                focus_buckets,
                component_payload=component_payload,
            ),
        }
        diagnostic_families = _diagnostic_only_input_families(component_payload)
        if diagnostic_families:
            explanation["diagnostic_only_input_families"] = diagnostic_families
        if marine_state and not _family_is_diagnostic_only(
            component_payload,
            "marine_microclimate",
            "marine_context",
        ):
            explanation["marine_context"] = marine_state
        forecast_profile = (
            component_payload.get("forecast_profile_calibration")
            or component_payload.get("forecast_profile_lane")
        )
        if forecast_profile:
            explanation["forecast_profile_calibration"] = forecast_profile
        source_state_reliability = (
            component_payload.get("source_state_reliability")
            or component_payload.get("forecast_source_state_reliability")
        )
        if source_state_reliability:
            explanation["source_state_reliability"] = source_state_reliability
        return explanation

    def driver_breakdown(self, buckets, component_payload=None):
        """Quantitative driver breakdown for the given final-distribution buckets,
        from the last estimate_distribution pipeline. Returns a dict with a
        telescoping ``waterfall`` table (each driver's signed contribution to each
        bucket's probability, ending in the absolute final probability) and an
        ``inputs`` table (each standalone driver's independent opinion of each
        bucket). Bucket-agnostic and unit-aware; empty when no build has run."""
        buckets = [int(bucket) for bucket in buckets]
        payload = component_payload or getattr(self, "_last_distribution_components", {}) or {}
        components = payload.get("components", {}) or {}
        u = self.spec.display_unit
        bucket_cols = {bucket: f"{bucket} {u}" for bucket in buckets}

        waterfall = driver_waterfall(components, buckets)
        waterfall_rows = []
        totals = {bucket: 0.0 for bucket in buckets}
        for index, (_key, label, contributions) in enumerate(waterfall):
            row = {"Driver": label}
            for bucket in buckets:
                value = contributions.get(bucket, 0.0)
                totals[bucket] += value
                # The first present stage is the absolute baseline; later stages
                # are signed deltas (percentage points added / removed).
                row[bucket_cols[bucket]] = (
                    self.format_pct(value) if index == 0 else self.format_signed_pct(value)
                )
            waterfall_rows.append(row)
        if waterfall_rows:
            final_row = {"Driver": "= Final model probability"}
            for bucket in buckets:
                final_row[bucket_cols[bucket]] = self.format_pct(totals[bucket])
            waterfall_rows.append(final_row)

        # Standalone input distributions: each driver's independent opinion.
        feature_key = next(
            (key for key in components if key.endswith("_feature_model")), None
        )
        input_items = list(DRIVER_INPUT_COMPONENTS)
        if feature_key:
            kind = feature_key.split("_feature_model")[0].upper()
            input_items.insert(0, (feature_key, f"{kind} feature model"))
        input_rows = []
        for key, label in input_items:
            distribution = components.get(key)
            if not distribution:
                continue
            row = {"Input": label}
            for bucket in buckets:
                row[bucket_cols[bucket]] = self.format_pct(_component_prob(distribution, bucket))
            input_rows.append(row)

        return {
            "buckets": list(buckets),
            "waterfall": waterfall_rows,
            "inputs": input_rows,
        }

    def forecast_rows(self, sources):
        rows = []
        weather = self.source_data(sources, "weather_forecast")
        for row in weather.get("rows", [])[:8]:
            rows.append({
                "Source": "Weather.com forecast",
                "Time": row.get("time"),
                "Temp": self.format_temp(self.row_temp_native(row)),
                "Cloud": self.format_pct_number(row.get("cloud_cover")),
                "Condition": row.get("condition"),
                "Wind": f"{row.get('wind', '-')}, {row.get('wind_kmh', '-')} km/h",
            })

        open_meteo = self.source_data(sources, "open_meteo")
        for row in open_meteo.get("rows", [])[:8]:
            rows.append({
                "Source": "Open-Meteo forecast",
                "Time": row.get("time"),
                "Temp": self.format_temp(self.row_temp_native(row)),
                "Cloud": self.format_pct_number(row.get("cloud_cover")),
                "Condition": f"solar {row.get('solar', '-')} W/m2",
                "Wind": f"{row.get('wind_kmh', '-')} km/h",
            })
        return rows

    def model_notes(self, sources, distribution_result=None):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        weather_forecast = self.source_data(sources, "weather_forecast")

        notes = [
            (
                f"Resolution is modeled as the highest whole-degree {self.spec.display_unit} value "
                f"that Wunderground history prints for {self.spec.icao} on {self.config.display_date}."
            ),
            (
                "Wunderground/Weather.com history rows are the strongest input; "
                "current max fields are discounted until they appear in history."
            ),
        ]
        kind = (
            distribution_result.active_model_kind
            if distribution_result is not None
            else getattr(self, "active_model_kind", "empirical")
        )
        if kind == "hgb":
            notes.append("Prior probabilities generated by the HistGradientBoosting ML model (v0.4).")
        elif kind == "lr":
            notes.append("Prior probabilities generated by the Logistic Regression ML model coefficients (v0.4).")
        else:
            notes.append("Prior probabilities generated by the empirical lookups baseline (v0.3).")
        history_max = self.row_max_native(history)
        if history_max is not None:
            notes.append(
                f"Current printed WU-history high is {self.format_temp(history_max)}."
            )
        current_max_native = self.row_max_since_7am_native(current)
        if current_max_native is not None:
            notes.append(
                "Weather.com current says max since 7 AM is "
                f"{self.format_temp(current_max_native)}."
            )
        eccc_max_native = self.row_same_day_max_native(eccc)
        if eccc_max_native is not None:
            notes.append(
                "ECCC SWOB same-day max is "
                f"{self.format_temp(eccc_max_native)}; "
                "this can catch intra-hour highs that WU history may miss."
            )
        forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        if forecast_max is not None:
            notes.append(
                f"Weather.com remaining-hour forecast max is {self.format_temp(forecast_max)}."
            )
        eccc_forecast_native = self.row_forecast_high_native(eccc_city)
        if eccc_forecast_native is not None:
            notes.append(
                "Environment Canada public forecast high is "
                f"{self.format_temp(eccc_forecast_native)}; "
                "it is included as a lower-weight non-resolution forecast."
            )
        if local_history.get("available"):
            count = (local_history.get("analysis") or {}).get("target_window_count", 0)
            notes.append(
                f"Local WU history has {count} days in the {self.target_date:%B %d} +/-7-day window; "
                "the live curve now blends the base prior with matching intraday analogs."
            )
            notes.append(
                "Historical target-season data found non-hourly-only settlement highs "
                "rare, so hourly catch-up matters more than hidden intra-hour spikes."
            )
        return notes

    def bin_probability(self, distribution, bin_data, calibration_context=None):
        """Probability a market band contains the realized high. Each market runs
        in its native unit, so the distribution buckets and the band values are
        already in the same unit -- this is a plain native sum (range bands sum
        ``[value, value_hi]``), no cross-unit conversion. Continuous-density
        payloads are canonical Fahrenheit and get projected to the native band
        at serve time."""
        if not distribution:
            return 0.0
        calibration_artifact = getattr(self, "probability_calibration", None)
        calibration_context = (
            calibration_context
            if calibration_context is not None
            else getattr(self, "_last_probability_calibration_context", None) or {}
        )
        if is_continuous_density_payload(distribution) and calibration_context:
            distribution = apply_continuous_density_calibration(
                distribution,
                calibration_artifact,
                floor_bucket=calibration_context.get("observed_floor_bucket"),
                unit=self.spec.display_unit,
                resolution_weight=calibration_context.get("lockin_strength", 0.0),
                cutoff_hour=calibration_context.get("cutoff_hour"),
            )
        raw_probability = band_probability_from_distribution(
            distribution,
            self.spec,
            bin_data,
        )
        if raw_probability is None:
            value = bin_data["value"]
            value_hi = bin_data.get("value_hi", value)
            if bin_data["kind"] == "lte":
                raw_probability = sum(prob for temp, prob in distribution.items() if temp <= value)
            elif bin_data["kind"] == "gte":
                raw_probability = sum(prob for temp, prob in distribution.items() if temp >= value)
            else:  # exact bucket (value_hi == value) or a range band [value, value_hi]
                raw_probability = sum(prob for temp, prob in distribution.items() if value <= temp <= value_hi)
        return calibrate_market_probability(
            raw_probability,
            bin_data,
            calibration_artifact,
            context=calibration_context,
            market_yes=bin_data.get("market_yes"),
        )

    def bin_sort_key(self, bin_data):
        if bin_data["kind"] == "lte":
            return -1
        if bin_data["kind"] == "gte":
            return 10_000
        return bin_data["value"]

    def market_status(self, market):
        if market.get("closed"):
            return market.get("umaResolutionStatus") or "closed"
        if market.get("active"):
            return "active"
        return "inactive"

    def parse_json_list(self, value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def price_for_outcome(self, outcome_name, outcomes, prices):
        for index, outcome in enumerate(outcomes):
            if str(outcome).lower() == outcome_name.lower() and index < len(prices):
                return self.to_number(prices[index])
        return None

    def token_for_outcome(self, outcome_name, outcomes, token_ids):
        for index, outcome in enumerate(outcomes):
            if str(outcome).lower() == outcome_name.lower() and index < len(token_ids):
                return str(token_ids[index])
        return None

    def local_history_answer(self, local_history):
        if not local_history.get("available"):
            return local_history.get("reason", "-")
        analysis = local_history.get("analysis") or {}
        count = analysis.get("target_window_count", 0)
        
        kb = self.spec.key_bucket
        u = self.spec.display_unit
        kb_plus_4 = self.spec.key_bucket + 4
        
        return (
            f"{count} days; {kb} {u} base rate {self.format_pct(local_history.get('prob_key'))}, "
            f">={kb} {u} {self.format_pct(local_history.get('prob_key_plus'))}, "
            f">={kb_plus_4} {u} {self.format_pct(local_history.get('prob_key_plus_4'))}"
        )

    def clean_label(self, label):
        return (
            str(label)
            .replace("Â°C", " C")
            .replace("�C", " C")
            .replace("°C", " C")
        )

    def format_temp(self, value):
        """Format a temperature that is ALREADY in the market's native unit.
        Every source/value in this layer is fetched natively (C markets in C,
        F markets in F), so no conversion here -- converting again turned
        75 F into 167 F on the F-market dashboards."""
        if value is None:
            return "-"
        val_native = float(value)
        if val_native.is_integer():
            return f"{int(val_native)} {self.spec.display_unit}"
        return f"{val_native:.1f} {self.spec.display_unit}"

    def format_pct(self, value):
        if value is None:
            return "-"
        return f"{value * 100:.1f}%"

    def format_signed_pct(self, value):
        if value is None:
            return "-"
        return f"{value * 100:+.1f}%"

    def format_pct_number(self, value):
        if value is None:
            return "-"
        return f"{float(value):.0f}%"
