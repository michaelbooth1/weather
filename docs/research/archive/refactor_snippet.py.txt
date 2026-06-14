    def _evaluate_feature_model_for_cutoff(self, sources, cutoff_hour, hgb_bundle, lr_coefs):
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
                print(f"Error predicting with LR coefficients: {e}. Falling back to empirical prior...")
                
        return None, "empirical"

    def predict_feature_distribution(self, sources, cutoff_hour, now):
        hgb_bundle = self.load_feature_model_hgb()
        lr_coefs = self.load_feature_model_coefs()

        if not hgb_bundle and not lr_coefs:
            return None, "empirical"

        # 1. Base evaluation at the primary cutoff
        dist, kind = self._evaluate_feature_model_for_cutoff(sources, cutoff_hour, hgb_bundle, lr_coefs)
        if not dist:
            return dist, kind

        # 2. Check if we can interpolate with the next cutoff
        minute_of_day = self.minute_of_day(now)
        cutoff_min = cutoff_hour * 60
        
        # Only interpolate if we are actually past the cutoff time
        if minute_of_day is not None and minute_of_day > cutoff_min:
            next_cutoff = next((c for c in INTRADAY_CUTOFF_HOURS if c > cutoff_hour), None)
            if next_cutoff is not None:
                dist_next, kind_next = self._evaluate_feature_model_for_cutoff(sources, next_cutoff, hgb_bundle, lr_coefs)
                
                # Only blend if both predictions succeeded and are of the same type
                if dist_next and kind_next == kind:
                    next_min = next_cutoff * 60
                    
                    # Prevent extrapolation past the next cutoff (e.g., if we are somehow past next_min)
                    current_min = min(minute_of_day, next_min)
                    
                    weight_next = (current_min - cutoff_min) / (next_min - cutoff_min)
                    weight_prev = 1.0 - weight_next
                    
                    blended = {}
                    all_keys = set(dist.keys()) | set(dist_next.keys())
                    for k in all_keys:
                        blended[k] = dist.get(k, 0.0) * weight_prev + dist_next.get(k, 0.0) * weight_next
                        
                    return blended, kind

        return dist, kind
