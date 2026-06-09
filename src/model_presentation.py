import json
import re
from datetime import datetime
from model_constants import (
    DEFAULT_MARKET_CONFIG,
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
from probability_calibration import calibrate_market_probability


class PresentationMixin:
    """Dashboard/snapshot view rows, market-bin parsing, and value formatting."""

    def model_market_rows(self, event, distribution):
        bins = self.market_bins(event)
        rows = []
        for bin_data in bins:
            model_prob = self.bin_probability(distribution, bin_data)
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
            market_yes = self.price_for_outcome("Yes", outcomes, prices)
            market_no = self.price_for_outcome("No", outcomes, prices)
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

        rows = []
        rows.append({
            "Source": "Wunderground history proxy",
            "Signal": "Printed history high",
            "Value": self.format_temp(history.get("max_c")),
            "Detail": ", ".join(history.get("max_times") or []) or "-",
            "Model role": "Primary settlement proxy",
        })
        latest = history.get("latest") or {}
        rows.append({
            "Source": "Wunderground history proxy",
            "Signal": "Latest printed row",
            "Value": self.format_temp(latest.get("temp_c")),
            "Detail": latest.get("time", "-"),
            "Model role": "Confirms table trend",
        })
        rows.append({
            "Source": f"Weather.com current {self.spec.icao}",
            "Signal": "Current / max since 7 AM",
            "Value": (
                f"{self.format_temp(current.get('temp_c'))} / "
                f"{self.format_temp(current.get('max_since_7am_c'))}"
            ),
            "Detail": current.get("time", "-"),
            "Model role": "Same data family, discounted until in history",
        })
        local_analysis = local_history.get("analysis") or {}
        rows.append({
            "Source": "Local WU history",
            "Signal": "+/-7 day prior + intraday analogs",
            "Value": (
                f"{self.spec.key_bucket} {self.spec.display_unit} {self.format_pct(local_history.get('prob_25'))}"
                if local_history.get("prob_25") is not None else "-"
            ),
            "Detail": (
                f"{local_analysis.get('target_window_count', 0)} days; "
                f">={self.spec.key_bucket} {self.spec.display_unit} {self.format_pct(local_history.get('prob_25_plus'))}"
                if local_history.get("available") else local_history.get("reason", "-")
            ),
            "Model role": "Empirical prior, catch-up, and late-day tail",
        })
        eccc_latest = eccc.get("latest") or {}
        rows.append({
            "Source": f"ECCC SWOB {self.spec.icao}",
            "Signal": "Air / same-day max",
            "Value": (
                f"{self.format_temp(eccc_latest.get('air_temp_c'))} / "
                f"{self.format_temp(eccc.get('same_day_max_c'))}"
            ),
            "Detail": eccc_latest.get("time", "-"),
            "Model role": "Official station support, non-resolution",
        })
        rows.append({
            "Source": "Environment Canada forecast",
            "Signal": "Public forecast high",
            "Value": self.format_temp(eccc_city.get("forecast_high_c")),
            "Detail": eccc_city.get("forecast_cloud", "-"),
            "Model role": "Official forecast, non-resolution",
        })
        rows.append({
            "Source": f"METAR {self.spec.icao}",
            "Signal": "Hourly airport report",
            "Value": self.format_temp(metar.get("temp_c")),
            "Detail": metar.get("report_time", "-"),
            "Model role": "Hourly sanity check",
        })
        return rows

    def deep_dive_rows(self, sources, distribution, analogs_data=None, now=None):
        kb = self.spec.key_bucket
        u = self.spec.display_unit
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")

        rows = []

        # 1. Wunderground History
        hist_max = history.get("max_c")
        if hist_max is None:
            impact = f"No historical printed observations yet. {kb} {u} is wide open."
        elif self.spec.c_to_native(hist_max) >= kb:
            impact = f"Guaranteed floor. Printed high is already {self.format_temp(hist_max)} (>= {kb} {u})."
        elif self.spec.c_to_native(hist_max) >= kb - self.spec.scale_delta(1.0):
            impact = f"Extremely close. Needs only +{self.spec.scale_delta(1.0):.1f} {u} to reach {kb} {u}."
        else:
            impact = f"Printed high is {self.format_temp(hist_max)}. Needs {kb - self.spec.c_to_native(hist_max):.1f} {u} rise."
        rows.append({
            "Question": "What has Wunderground history printed?",
            "Answer": self.format_temp(hist_max),
            "Impact on {kb} {u}": impact,
        })

        # 2. Weather.com Current
        curr_temp = current.get("temp_c")
        max_7am = current.get("max_since_7am_c")
        if max_7am is not None and self.spec.c_to_native(max_7am) >= kb:
            impact = f"Strong indicator. Max since 7 AM is {self.format_temp(max_7am)}, which matches or exceeds {kb} {u}."
        elif curr_temp is not None and self.spec.c_to_native(curr_temp) >= kb:
            impact = f"Very bullish. Live temperature is already {self.format_temp(curr_temp)}."
        else:
            impact = f"Current temp is {self.format_temp(curr_temp)}; max since 7 AM is {self.format_temp(max_7am)}."
        rows.append({
            "Question": "What does Weather.com current say?",
            "Answer": f"current {self.format_temp(curr_temp)}, max since 7 AM {self.format_temp(max_7am)}",
            "Impact on {kb} {u}": impact,
        })

        # 3. ECCC SWOB
        swob_max = eccc.get("same_day_max_c")
        if swob_max is not None and self.spec.c_to_native(swob_max) >= kb:
            impact = f"Floor validator. SWOB same-day max is {self.format_temp(swob_max)}, guaranteeing settlement >= {kb} {u}."
        elif swob_max is not None:
            impact = f"Pearson SWOB max is {self.format_temp(swob_max)}, trailing {kb} {u} by {kb - self.spec.c_to_native(swob_max):.1f} {u}."
        else:
            impact = "No live SWOB observations yet."
        rows.append({
            "Question": "What does the official station (SWOB) support?",
            "Answer": self.format_temp(swob_max),
            "Impact on {kb} {u}": impact,
        })

        # 4. Weather.com hourly forecast
        fc_max = self.max_row_temp(weather_forecast.get("rows"))
        if fc_max is not None and self.spec.c_to_native(fc_max) >= kb:
            impact = f"Bullish. Hourly forecast projects high will reach {self.format_temp(fc_max)}."
        elif fc_max is not None:
            impact = f"Bearish forecast. Peak forecast is {self.format_temp(fc_max)}, suggesting {kb} {u} will not be reached."
        else:
            impact = "No forecast data available."
        rows.append({
            "Question": "What does Weather.com forecast for remaining hours?",
            "Answer": self.format_temp(fc_max),
            "Impact on {kb} {u}": impact,
        })

        # 5. Open-Meteo & ECCC Citypage
        om_max = self.max_row_temp(open_meteo.get("rows"))
        ec_high = eccc_city.get("forecast_high_c")
        alt_max = max([val for val in [om_max, ec_high] if val is not None], default=None)
        if alt_max is not None and self.spec.c_to_native(alt_max) >= kb:
            impact = f"Bullish alternative forecast. Alt models project a high of {self.format_temp(alt_max)}."
        elif alt_max is not None:
            impact = f"Bearish. Alternative models peak at {self.format_temp(alt_max)}."
        else:
            impact = "No alternative forecast data."
        rows.append({
            "Question": "What says {kb} {u} or higher is live?",
            "Answer": f"Open-Meteo max {self.format_temp(om_max)}, ECCC forecast high {self.format_temp(ec_high)}",
            "Impact on {kb} {u}": impact,
        })

        # 6. Local WU History
        prob_25 = local_history.get("prob_25")
        if prob_25 is not None:
            impact = f"Historical seasonal base rate for {kb} {u} is {prob_25*100:.1f}%."
        else:
            impact = "No local history available."
        rows.append({
            "Question": "What does local WU history say?",
            "Answer": self.local_history_answer(local_history),
            "Impact on {kb} {u}": impact,
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
        analog_prob_25 = 0.0
        if isinstance(analogs_data, dict):
            analogs = analogs_data.get("analogs", [])
            analog_n = len(analogs)
            if analog_n > 0:
                count_25 = sum(1 for d in analogs if d["final_bucket"] == kb)
                analog_prob_25 = count_25 / analog_n
        if analog_n > 0:
            impact = f"Of the closest {analog_n} historical analogs, {analog_prob_25*100:.0f}% resolved to exactly {kb} {u}."
        else:
            impact = "Insufficient analog days to evaluate."
        rows.append({
            "Question": "What do historical analogs say?",
            "Answer": f"{analog_n} analogs found",
            "Impact on {kb} {u}": impact,
        })

        # 8. Model probability
        prob_exact = distribution.get(kb, 0.0)
        rows.append({
            "Question": "Model probability for exact {kb} {u}",
            "Answer": self.format_pct(prob_exact),
            "Impact on {kb} {u}": f"Final model assigns {prob_exact*100:.1f}% probability to the exact {kb} {u} bucket.",
        })

        return rows

    def get_model_explanation(self, sources, distribution):
        # 1. Active regimes and signals
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        eccc = self.source_data(sources, "eccc_swob")
        eccc_city = self.source_data(sources, "eccc_citypage")
        weather_forecast = self.source_data(sources, "weather_forecast")
        open_meteo = self.source_data(sources, "open_meteo")
        
        history_max = history.get("max_c")
        current_temp = current.get("temp_c")
        current_max = current.get("max_since_7am_c")
        observed_bucket = self.round_half_up(history_max)
        
        weather_forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        open_meteo_max = self.max_row_temp(open_meteo.get("rows"))
        eccc_forecast_high = eccc_city.get("forecast_high_c")
        
        plausible_cap = self.round_half_up(self.max_value(
            observed_bucket,
            weather_forecast_max,
            open_meteo_max,
            eccc_forecast_high,
        ))
        
        wind_group = self.live_wind_group(current, weather_forecast)
        cloud_group = self.live_cloud_group(current, eccc_city, weather_forecast)
        
        # 2. Top buckets in final distribution
        top_buckets = sorted(distribution.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # 3. Model type
        model_type = self.get_model_version_string()
        
        explanation = {
            "model_type": model_type,
            "observed_floor": observed_bucket,
            "forecast_cap": plausible_cap,
            "wind_regime": wind_group,
            "cloud_regime": cloud_group,
            "top_buckets": [
                {
                    "bucket": f"{temp} C",
                    "probability": self.format_pct(prob),
                    "status": "Floor constraint" if observed_bucket is not None and temp < observed_bucket else (
                        "Cap constraint" if plausible_cap is not None and temp > plausible_cap + 1 else "Primary projection"
                    )
                }
                for temp, prob in top_buckets
            ]
        }
        return explanation

    def forecast_rows(self, sources):
        rows = []
        weather = self.source_data(sources, "weather_forecast")
        for row in weather.get("rows", [])[:8]:
            rows.append({
                "Source": "Weather.com forecast",
                "Time": row.get("time"),
                "Temp": self.format_temp(row.get("temp_c")),
                "Cloud": self.format_pct_number(row.get("cloud_cover")),
                "Condition": row.get("condition"),
                "Wind": f"{row.get('wind', '-')}, {row.get('wind_kmh', '-')} km/h",
            })

        open_meteo = self.source_data(sources, "open_meteo")
        for row in open_meteo.get("rows", [])[:8]:
            rows.append({
                "Source": "Open-Meteo forecast",
                "Time": row.get("time"),
                "Temp": self.format_temp(row.get("temp_c")),
                "Cloud": self.format_pct_number(row.get("cloud_cover")),
                "Condition": f"solar {row.get('solar', '-')} W/m2",
                "Wind": f"{row.get('wind_kmh', '-')} km/h",
            })
        return rows

    def model_notes(self, sources):
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        local_history = self.source_data(sources, "local_history")
        eccc_city = self.source_data(sources, "eccc_citypage")
        eccc = self.source_data(sources, "eccc_swob")
        weather_forecast = self.source_data(sources, "weather_forecast")

        notes = [
            (
                "Resolution is modeled as the highest whole-degree C value "
                f"that Wunderground history prints for {self.spec.icao} on {self.config.display_date}."
            ),
            (
                "Wunderground/Weather.com history rows are the strongest input; "
                "current max fields are discounted until they appear in history."
            ),
        ]
        kind = getattr(self, "active_model_kind", "empirical")
        if kind == "hgb":
            notes.append("Prior probabilities generated by the HistGradientBoosting ML model (v0.4).")
        elif kind == "lr":
            notes.append("Prior probabilities generated by the Logistic Regression ML model coefficients (v0.4).")
        else:
            notes.append("Prior probabilities generated by the empirical lookups baseline (v0.3).")
        if history.get("max_c") is not None:
            notes.append(
                f"Current printed WU-history high is {self.format_temp(history.get('max_c'))}."
            )
        if current.get("max_since_7am_c") is not None:
            notes.append(
                "Weather.com current says max since 7 AM is "
                f"{self.format_temp(current.get('max_since_7am_c'))}."
            )
        eccc_latest = eccc.get("latest") or {}
        if eccc.get("same_day_max_c") is not None:
            notes.append(
                "ECCC SWOB same-day max is "
                f"{self.format_temp(eccc.get('same_day_max_c'))}; "
                "this can catch intra-hour highs that WU history may miss."
            )
        forecast_max = self.max_row_temp(weather_forecast.get("rows"))
        if forecast_max is not None:
            notes.append(
                f"Weather.com remaining-hour forecast max is {self.format_temp(forecast_max)}."
            )
        if eccc_city.get("forecast_high_c") is not None:
            notes.append(
                "Environment Canada public forecast high is "
                f"{self.format_temp(eccc_city.get('forecast_high_c'))}; "
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

    def bin_probability(self, distribution, bin_data):
        """Probability a market band contains the realized high. Each market runs
        in its native unit, so the distribution buckets and the band values are
        already in the same unit -- this is a plain native sum (range bands sum
        ``[value, value_hi]``), no cross-unit conversion."""
        if not distribution:
            return 0.0
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
            getattr(self, "probability_calibration", None),
            context=getattr(self, "_last_probability_calibration_context", None),
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

    def local_history_answer(self, local_history):
        if not local_history.get("available"):
            return local_history.get("reason", "-")
        analysis = local_history.get("analysis") or {}
        count = analysis.get("target_window_count", 0)
        
        kb = self.spec.key_bucket
        u = self.spec.display_unit
        kb_plus_4 = self.spec.key_bucket + 4
        
        return (
            f"{count} days; {kb} {u} base rate {self.format_pct(local_history.get('prob_25'))}, "
            f">={kb} {u} {self.format_pct(local_history.get('prob_25_plus'))}, "
            f">={kb_plus_4} {u} {self.format_pct(local_history.get('prob_29_plus'))}"
        )

    def clean_label(self, label):
        return (
            str(label)
            .replace("Â°C", " C")
            .replace("�C", " C")
            .replace("°C", " C")
        )

    def format_temp(self, value):
        if value is None:
            return "-"
        val_native = self.spec.c_to_native(float(value))
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
