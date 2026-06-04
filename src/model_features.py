import json
import math
import statistics
from collections import Counter
from pathlib import Path

from feature_store import (
    FEATURE_SCHEMA_VERSION,
    build_live_feature_record,
)
from forecast_history import load_forecast_daily
from model_constants import _UNLOADED


class FeatureModelMixin:
    """Feature extraction, HGB/LR feature model, late-day, analogs, transitions."""

    def load_feature_model_hgb(self):
        if self._feature_model_hgb is _UNLOADED:
            self._feature_model_hgb = self._read_feature_model_hgb()
        return self._feature_model_hgb

    def _read_feature_model_hgb(self):
        path = Path(__file__).parent / "feature_model_hgb.pkl"
        if path.exists():
            try:
                import pickle
                with path.open("rb") as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"Error loading HGBC pickle: {e}")
        return None

    def load_feature_model_coefs(self):
        if self._feature_model_coefs is _UNLOADED:
            self._feature_model_coefs = self._read_feature_model_coefs()
        return self._feature_model_coefs

    def _read_feature_model_coefs(self):
        path = Path(__file__).parent / "feature_model_coefs.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading LR JSON coefs: {e}")
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

    def resolve_forecast_high(self, open_meteo, weather_forecast, eccc_city):
        """Forecasted daily max for the feature model, robust to a missing
        Open-Meteo.

        Open-Meteo is the canonical source -- the model is trained on its
        historical archive, and across the captured corpus it tracks the other
        forecasts (median gap 0 C) -- so it is used whenever present, leaving the
        served feature identical to today in the common case. Only when it is
        absent (a fetch outage, or a day before the feature existed) do we
        substitute the consensus (median) of the other live forecasts, rather
        than leaving the model forecast-blind and anchored to the morning's
        high-so-far. Returns (value, source_label) for auditability.
        """
        day_max = self.to_number(open_meteo.get("day_max_c"))
        if day_max is not None:
            return day_max, "open_meteo"
        others = []
        weather_com = self.max_row_temp(weather_forecast.get("rows"))
        if weather_com is not None:
            others.append(weather_com)
        eccc_high = self.to_number(eccc_city.get("forecast_high_c"))
        if eccc_high is not None:
            others.append(eccc_high)
        if not others:
            return None, "none"
        return statistics.median(others), "fallback_consensus"

    def extract_live_features(self, sources, cutoff_hour):
        """Build the cutoff-aligned feature vector shared by the feature model
        (HGB/LR) and the late-day continuation model.

        Both models were trained on the same fields, so they must extract them
        identically at inference time to avoid train/serve skew. This is the
        single source of truth for that extraction; callers add any model-
        specific features (e.g. late-day ``time_since_reached``) on top.

        Note: ``find_analog_days`` deliberately keeps its own extraction because
        it bails out on missing data instead of substituting seasonal defaults.
        """
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        weather_forecast = self.source_data(sources, "weather_forecast")
        eccc_city = self.source_data(sources, "eccc_citypage")

        rows = history.get("rows") or []
        feature_rows = self.source_rows_until_cutoff(rows, cutoff_hour)
        feature_latest = feature_rows[-1] if feature_rows else None

        # high_so_far
        temps = [r["temp_c"] for r in feature_rows if r.get("temp_c") is not None]
        current_temp = feature_latest.get("temp_c") if feature_latest else current.get("temp_c")
        if temps:
            high_so_far = max(temps)
        else:
            high_so_far = None

        # current_temp
        if current_temp is None:
            current_temp = current.get("temp_c")
        if current_temp is None:
            current_temp = rows[-1]["temp_c"] if rows else 17.0
        high_so_far = self.max_value(high_so_far, current_temp)
        if high_so_far is None:
            high_so_far = 17.0 # fallback

        # rise_from_7am
        obs_7am_candidates = [r for r in rows if r.get("time") and 360 <= self.minute_of_day(r["time"]) <= 480 and r.get("temp_c") is not None]
        temp_7am = None
        if obs_7am_candidates:
            closest_7am = min(obs_7am_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - 420))
            temp_7am = closest_7am["temp_c"]
        if temp_7am is None:
            temp_7am = 17.0 # default seasonal fallback
        rise_from_7am = current_temp - temp_7am

        # dewpoint_c, humidity, pressure
        dewpoint = feature_latest.get("dewpoint_c") if feature_latest else current.get("dewpoint_c")
        if dewpoint is None:
            dewpoint = rows[-1]["dewpoint_c"] if rows else 10.0 # fallback
        humidity = feature_latest.get("humidity") if feature_latest else current.get("humidity")
        if humidity is None:
            humidity = rows[-1]["humidity"] if rows else 60.0
        pressure = feature_latest.get("pressure") if feature_latest else current.get("pressure")
        if pressure is None:
            pressures = [r["pressure"] for r in rows if r.get("pressure") is not None]
            pressure = pressures[-1] if pressures else None

        # pressure_trend_3h
        cutoff_minutes = cutoff_hour * 60
        obs_3h_candidates = [r for r in rows if r.get("time") and (cutoff_minutes - 240) <= self.minute_of_day(r["time"]) <= (cutoff_minutes - 120) and r.get("pressure") is not None]
        pressure_trend_3h = 0.0
        if pressure is not None and obs_3h_candidates:
            closest_3h = min(obs_3h_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - (cutoff_minutes - 180)))
            press_3h_ago = closest_3h["pressure"]
            pressure_trend_3h = pressure - press_3h_ago

        # wind_speed_kmh
        wind_speed = feature_latest.get("wind_kmh") if feature_latest else current.get("wind_kmh")
        if wind_speed is None:
            wind_speed = rows[-1].get("wind_kmh") if rows else 15.0

        # wind_group and cloud_group
        wind_group = (
            self.wind_group(feature_latest.get("wind")) if feature_latest else None
        ) or self.live_wind_group(current, weather_forecast)
        cloud_group = (
            self.cloud_group(feature_latest.get("condition"), feature_latest.get("clouds"))
            if feature_latest else None
        ) or self.live_cloud_group(current, eccc_city, weather_forecast)

        # Forecast features: forecasted daily max (matching the archived-forecast
        # training value) and the gap above the high so far. Open-Meteo is the
        # canonical source, but when it is unavailable we fall back to the other
        # live forecasts instead of going forecast-blind (which leaves the model
        # anchored to a modest morning high-so-far). See resolve_forecast_high.
        open_meteo = self.source_data(sources, "open_meteo")
        forecast_high, _forecast_source = self.resolve_forecast_high(
            open_meteo, weather_forecast, eccc_city
        )
        forecast_gap = (forecast_high - high_so_far) if forecast_high is not None else None

        return {
            "feature_rows": feature_rows,
            "feature_latest": feature_latest,
            "high_so_far": high_so_far,
            "current_temp": current_temp,
            "rise_from_7am": rise_from_7am,
            "dewpoint_c": dewpoint,
            "humidity": humidity,
            "pressure": pressure,
            "pressure_trend_3h": pressure_trend_3h,
            "wind_speed_kmh": wind_speed,
            "wind_group": wind_group,
            "cloud_group": cloud_group,
            "forecast_high": forecast_high,
            "forecast_gap": forecast_gap,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        }

    def live_feature_record(self, sources, cutoff_hour, captured_at=None, model_version=None):
        return build_live_feature_record(
            getattr(self, "target_date", None),
            cutoff_hour,
            captured_at,
            model_version,
            self.extract_live_features(sources, cutoff_hour),
        )

    def predict_feature_distribution(self, sources, cutoff_hour, now):
        hgb_bundle = self.load_feature_model_hgb()
        lr_coefs = self.load_feature_model_coefs()

        if not hgb_bundle and not lr_coefs:
            return None, "empirical"

        feats = self.extract_live_features(sources, cutoff_hour)
        high_so_far = feats["high_so_far"]
        current_temp = feats["current_temp"]
        rise_from_7am = feats["rise_from_7am"]
        dewpoint = feats["dewpoint_c"]
        humidity = feats["humidity"]
        pressure = feats["pressure"]
        pressure_trend_3h = feats["pressure_trend_3h"]
        wind_speed = feats["wind_speed_kmh"]
        wind_group = feats["wind_group"]
        cloud_group = feats["cloud_group"]
        forecast_high = feats["forecast_high"]
        forecast_gap = feats["forecast_gap"]

        # Check if HGBC is available (preferred)
        if hgb_bundle and str(cutoff_hour) in hgb_bundle:
            try:
                bundle = hgb_bundle[str(cutoff_hour)]
                model_obj = bundle["model"]
                imputer_obj = bundle["imputer"]
                all_wind = bundle["all_wind_groups"]
                all_cloud = bundle["all_cloud_groups"]
                
                # Build feature dictionary
                feat_dict = {
                    "high_so_far": high_so_far,
                    "current_temp": current_temp,
                    "rise_from_7am": rise_from_7am,
                    "dewpoint_c": dewpoint,
                    "humidity": humidity,
                    "pressure": pressure,
                    "pressure_trend_3h": pressure_trend_3h,
                    "wind_speed_kmh": wind_speed,
                    "forecast_high": forecast_high,
                    "forecast_gap": forecast_gap
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

                # Restore native NaN for the forecast columns (the model was
                # trained with them un-imputed): a present forecast is used, a
                # missing one stays NaN for the tree to handle.
                fnames = list(bundle["feature_names"])
                if "forecast_high" in fnames:
                    for col in ("forecast_high", "forecast_gap"):
                        X_imputed[0, fnames.index(col)] = float(feat_dict[col]) if feat_dict[col] is not None else float("nan")

                # Predict probability distribution
                probs = model_obj.predict_proba(X_imputed)[0]
                classes = model_obj.classes_
                
                prob_dict = {int(c): float(p) for c, p in zip(classes, probs)}
                return prob_dict, "hgb"
            except Exception as e:
                print(f"Error predicting with HGBC model: {e}. Falling back to LR coefficients...")
                
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
                # it tracks the trained feature set, e.g. with forecast features).
                raw_vec = [
                    high_so_far, current_temp, rise_from_7am, dewpoint,
                    humidity, pressure, pressure_trend_3h, wind_speed,
                    forecast_high, forecast_gap
                ]
                n_num = len(scaler_mean)
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
                print(f"Error predicting with LR coefficients: {e}. Falling back to empirical prior...")
                
        return None, "empirical"

    def get_bucket_transitions(self, sources, now):
        history = self.source_data(sources, "wu_history")
        observed_bucket = self.round_half_up(history.get("max_c"))
        
        cutoff_hour = self.effective_intraday_cutoff_hour(
            now,
            history.get("rows") or [],
        )
        
        if observed_bucket is None:
            return {
                "current_max_bucket": None,
                "observed_bucket": None,
                "cutoff_hour": cutoff_hour,
                "sample_size": 0,
                "transitions": [],
                "skip_rate": 0.0
            }
            
        cache = self.historical_target_cache()
        daily = cache["daily"]
        by_date = cache["by_date"]
        
        cutoff = cutoff_hour * 60
        matching_final_buckets = []
        
        # 1. Compute transitions
        for local_date, daily_info in daily.items():
            rows = by_date.get(local_date, [])
            high_so_far = self.historical_max_until(rows, cutoff)
            if high_so_far is None:
                continue
            bucket_so_far = self.round_half_up(high_so_far)
            if bucket_so_far == observed_bucket:
                matching_final_buckets.append(daily_info["bucket"])
                
        # Calculate transition distribution
        transitions = []
        sample_size = len(matching_final_buckets)
        if sample_size >= 5:
            counts = Counter(matching_final_buckets)
            # Group into stays at X, rises to X+1, rises to X+2, rises to >= X+3
            for target_b in range(observed_bucket, observed_bucket + 3):
                cnt = counts.get(target_b, 0)
                prob = cnt / sample_size
                transitions.append({
                    "Target Bucket": f"{target_b} C",
                    "Probability": f"{prob * 100:.1f}%",
                    "Historical Days": cnt
                })
            cnt_plus_3 = sum(cnt for target_b, cnt in counts.items() if target_b >= observed_bucket + 3)
            prob_plus_3 = cnt_plus_3 / sample_size
            transitions.append({
                "Target Bucket": f">= {observed_bucket + 3} C",
                "Probability": f"{prob_plus_3 * 100:.1f}%",
                "Historical Days": cnt_plus_3
            })
            
        # 2. Compute historical rate of intermediate bucket skips during afternoon warming (10 AM to 6 PM)
        total_warming_days = 0
        skipping_days = 0
        
        for local_date, rows in by_date.items():
            warm_rows = [r for r in rows if 600 <= r["minute_of_day"] <= 1080]
            if not warm_rows:
                continue
            total_warming_days += 1
            
            temps = [r["temp_c"] for r in warm_rows if r.get("temp_c") is not None]
            if len(temps) < 2:
                continue
                
            has_skip = False
            for i in range(len(temps) - 1):
                t1, t2 = temps[i], temps[i+1]
                b1 = self.round_half_up(t1)
                b2 = self.round_half_up(t2)
                # Check for an upward jump that skips an integer bucket (e.g. 23 C -> 25 C)
                if b2 >= b1 + 2:
                    has_skip = True
                    break
            if has_skip:
                skipping_days += 1
                
        skip_rate = (skipping_days / total_warming_days) if total_warming_days > 0 else 0.0
        
        return {
            "current_max_bucket": observed_bucket,
            "observed_bucket": observed_bucket,
            "cutoff_hour": cutoff_hour,
            "sample_size": sample_size,
            "transitions": transitions,
            "skip_rate": skip_rate
        }

    def load_late_day_model_coefs(self):
        if self._late_day_model_coefs is _UNLOADED:
            self._late_day_model_coefs = self._read_late_day_model_coefs()
        return self._late_day_model_coefs

    def _read_late_day_model_coefs(self):
        path = Path(__file__).parent / "late_day_model_coefs.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading late-day model coefficients: {e}")
        return None

    def predict_late_day_continuation(self, sources, cutoff_hour, now):
        coefs = self.load_late_day_model_coefs()
        if not coefs or str(cutoff_hour) not in coefs:
            return None

        # 1. Extract the shared cutoff-aligned features (same as the feature model).
        feats = self.extract_live_features(sources, cutoff_hour)
        high_so_far = feats["high_so_far"]
        current_temp = feats["current_temp"]
        rise_from_7am = feats["rise_from_7am"]
        dewpoint = feats["dewpoint_c"]
        humidity = feats["humidity"]
        pressure = feats["pressure"]
        pressure_trend_3h = feats["pressure_trend_3h"]
        wind_speed = feats["wind_speed_kmh"]
        wind_group = feats["wind_group"]
        cloud_group = feats["cloud_group"]
        feature_rows = feats["feature_rows"]
        forecast_high = feats.get("forecast_high")
        forecast_gap = feats.get("forecast_gap")

        # 2. Late-day-specific feature: how long ago today's high was first reached.
        first_reached_min = None
        first_reached_time = None
        for r in feature_rows:
            if r.get("temp_c") == high_so_far:
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
            
            raw_vec = [
                float(time_since_reached), high_so_far, current_temp, rise_from_7am,
                dewpoint, humidity, pressure, pressure_trend_3h, wind_speed
            ]
            for i in range(9):
                if raw_vec[i] is None:
                    raw_vec[i] = imputer_median[i]
            scaled_vec = [(raw_vec[i] - scaler_mean[i]) / scaler_scale[i] for i in range(9)]
            
            for name in feature_names[9:]:
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
                    open_meteo.get("day_max_c") or self.max_row_temp(open_meteo.get("rows")),
                    eccc_city.get("forecast_high_c"),
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
            print(f"Error predicting late-day continuation: {e}")
            return None

    def find_analog_days(self, sources, cutoff_hour, now, limit=5):
        # Always return this shape so callers never have to type-check the result.
        empty_result = {"cutoff_hour": cutoff_hour, "today_features": {}, "analogs": []}
        # 1. Get cache
        cache = self.historical_target_cache()
        if not cache or not cache.get("daily"):
            return empty_result

        # 2. Extract today's live features
        history = self.source_data(sources, "wu_history")
        current = self.source_data(sources, "wu_current")
        weather_forecast = self.source_data(sources, "weather_forecast")
        eccc_city = self.source_data(sources, "eccc_citypage")
        open_meteo = self.source_data(sources, "open_meteo")

        rows = history.get("rows") or []
        feature_rows = self.source_rows_until_cutoff(rows, cutoff_hour)
        feature_latest = feature_rows[-1] if feature_rows else None
        
        # Today's high_so_far
        temps = [r["temp_c"] for r in feature_rows if r.get("temp_c") is not None]
        today_current_temp = feature_latest.get("temp_c") if feature_latest else current.get("temp_c")
        if temps:
            today_high = max(temps)
        else:
            today_high = None

        # Today's current_temp
        if today_current_temp is None:
            today_current_temp = current.get("temp_c")
        if today_current_temp is None:
            today_current_temp = feature_latest.get("temp_c") if feature_latest else today_high
        if today_current_temp is None:
            today_current_temp = today_high
        today_high = self.max_value(today_high, today_current_temp)
        if today_high is None:
            today_high = current.get("max_since_7am_c")
        if today_high is None:
            return empty_result

        # Today's rise_from_7am
        obs_7am_candidates = [r for r in rows if r.get("time") and 360 <= self.minute_of_day(r["time"]) <= 480 and r.get("temp_c") is not None]
        temp_7am = None
        if obs_7am_candidates:
            closest_7am = min(obs_7am_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - 420))
            temp_7am = closest_7am["temp_c"]
        if temp_7am is None:
            temp_7am = today_current_temp
        today_rise = today_current_temp - temp_7am

        # Today's dewpoint
        today_dewpoint = feature_latest.get("dewpoint_c") if feature_latest else current.get("dewpoint_c")
        if today_dewpoint is None:
            today_dewpoint = current.get("dewpoint_c")
        if today_dewpoint is None:
            today_dewpoint = feature_latest.get("dewpoint_c") if feature_latest else 10.0
        if today_dewpoint is None:
            today_dewpoint = 10.0

        # Today's wind_group and cloud_group
        today_wind = (
            self.wind_group(feature_latest.get("wind")) if feature_latest else None
        ) or self.live_wind_group(current, weather_forecast)
        today_cloud = (
            self.cloud_group(feature_latest.get("condition"), feature_latest.get("clouds"))
            if feature_latest else None
        ) or self.live_cloud_group(current, eccc_city, weather_forecast)
        today_forecast_high = open_meteo.get("day_max_c") or self.max_row_temp(open_meteo.get("rows"))
        today_forecast_gap = (
            today_forecast_high - today_high
            if today_forecast_high is not None and today_high is not None
            else None
        )

        # 3. Extract historical features at same cutoff hour
        cutoff_minutes = cutoff_hour * 60
        hist_days_features = []
        forecast_index = load_forecast_daily()
        
        for local_date, daily in cache["daily"].items():
            day_obs = cache["by_date"].get(local_date, [])
            if not day_obs:
                continue

            obs_before = [r for r in day_obs if r["minute_of_day"] <= cutoff_minutes]
            if not obs_before:
                continue
            
            # high_so_far
            h_temps = [r["temp_c"] for r in obs_before if r.get("temp_c") is not None]
            if not h_temps:
                continue
            h_high = max(h_temps)

            # current_temp
            h_curr_obs = obs_before[-1]
            h_curr_temp = h_curr_obs.get("temp_c")
            if h_curr_temp is None:
                h_curr_temp = h_high

            # temp at 7 AM
            h_obs_7am_candidates = [r for r in day_obs if 360 <= r["minute_of_day"] <= 480 and r.get("temp_c") is not None]
            h_temp_7am = None
            if h_obs_7am_candidates:
                closest_h_7am = min(h_obs_7am_candidates, key=lambda r: abs(r["minute_of_day"] - 420))
                h_temp_7am = closest_h_7am["temp_c"]
            if h_temp_7am is None:
                h_temp_7am = h_curr_temp

            h_rise = h_curr_temp - h_temp_7am

            # dewpoint
            h_dewpoint = h_curr_obs.get("dewpoint_c")
            if h_dewpoint is None:
                h_dews = [r["dewpoint_c"] for r in obs_before if r.get("dewpoint_c") is not None]
                h_dewpoint = h_dews[-1] if h_dews else 10.0

            # wind and cloud groups
            h_wind = self.wind_group(h_curr_obs.get("wind"))
            h_cloud = self.cloud_group(h_curr_obs.get("condition"), h_curr_obs.get("clouds"))
            h_forecast_high = forecast_index.get(local_date.isoformat())
            h_forecast_gap = (
                h_forecast_high - h_high
                if h_forecast_high is not None and h_high is not None
                else None
            )

            hist_days_features.append({
                "date": local_date,
                "high_so_far": h_high,
                "rise_from_7am": h_rise,
                "dewpoint_c": h_dewpoint,
                "wind_group": h_wind,
                "cloud_group": h_cloud,
                "forecast_high": h_forecast_high,
                "forecast_gap": h_forecast_gap,
                "final_high": daily["max_temp_c"],
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
            d_high = ((d["high_so_far"] - today_high) / std_high) ** 2
            d_rise = ((d["rise_from_7am"] - today_rise) / std_rise) ** 2
            d_dew = ((d["dewpoint_c"] - today_dewpoint) / std_dew) ** 2

            d_wind = 1.0 if d["wind_group"] != today_wind else 0.0
            d_cloud = 1.0 if d["cloud_group"] != today_cloud else 0.0
            if today_forecast_gap is not None and d.get("forecast_gap") is not None:
                d_forecast_gap = ((d["forecast_gap"] - today_forecast_gap) / std_forecast_gap) ** 2
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

            # Extract temperature path (hourly from 7 AM to 8 PM)
            temp_path = {}
            for h in range(7, 21):
                target_min = h * 60
                obs_candidates = [r for r in d["observations"] if r.get("temp_c") is not None]
                if obs_candidates:
                    closest_obs = min(obs_candidates, key=lambda r: abs(r["minute_of_day"] - target_min))
                    if abs(closest_obs["minute_of_day"] - target_min) <= 60:
                        temp_path[f"{h:02d}:00"] = closest_obs["temp_c"]
                    else:
                        temp_path[f"{h:02d}:00"] = None
                else:
                    temp_path[f"{h:02d}:00"] = None

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
                "temp_path": temp_path
            })

        analogs.sort(key=lambda x: x["distance"])

        # Also get today's temperature path
        today_temp_path = {}
        for h in range(7, 21):
            target_min = h * 60
            obs_candidates = [r for r in rows if r.get("temp_c") is not None]
            if obs_candidates:
                closest_obs = min(obs_candidates, key=lambda r: abs(self.minute_of_day(r["time"]) - target_min))
                if abs(self.minute_of_day(closest_obs["time"]) - target_min) <= 60:
                    today_temp_path[f"{h:02d}:00"] = closest_obs["temp_c"]
                else:
                    today_temp_path[f"{h:02d}:00"] = None
            else:
                today_temp_path[f"{h:02d}:00"] = None
        
        return {
            "cutoff_hour": cutoff_hour,
            "today_features": {
                "high_so_far": today_high,
                "rise_from_7am": today_rise,
                "dewpoint_c": today_dewpoint,
                "wind_group": today_wind,
                "cloud_group": today_cloud,
                "forecast_high": today_forecast_high,
                "forecast_gap": today_forecast_gap,
                "temp_path": today_temp_path
            },
            "analogs": analogs[:limit]
        }
