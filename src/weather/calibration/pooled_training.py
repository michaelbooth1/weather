"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

from weather.calibration.pooled_band_training import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def train_pooled_models(records, holdout_year=None):
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    artifact = {
        "schema_version": "pooled_feature_hgb_v0.1",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "F",
        "trained_at": datetime.now().isoformat(),
        "support": sorted({int(row["final_bucket"]) for row in records}),
        "blocked_validation": blocked_validation_audit(records),
        "models": {},
    }
    support = artifact["support"]
    validation_rows = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 50:
            continue
        model, imputer, feature_names, train_metrics = train_hour_model(train_rows)
        eval_score = None
        market_scores = []
        if eval_rows:
            predictions = predict_rows(model, imputer, feature_names, eval_rows, support=support)
            eval_score = evaluate_distributions(eval_rows, predictions)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                market_eval = [row for row in eval_rows if row["market_id"] == market_id]
                market_predictions = [
                    pred for row, pred in zip(eval_rows, predictions)
                    if row["market_id"] == market_id
                ]
                score = evaluate_distributions(market_eval, market_predictions)
                if score:
                    market_scores.append({"market_id": market_id, **score})

        final_model, final_imputer, final_feature_names, final_metrics = train_hour_model(hour_rows)
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(hour_rows),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    return artifact, validation_rows


def default_band_postprocess(
    exact_winner_catchup_enabled=False,
    exact_winner_shadow_blend=True,
):
    config = {
        "hard_floor_enabled": True,
        "support_floor_enabled": True,
        "support_floor_one_below_cap": 0.08,
        "support_floor_decay": 0.25,
        "late_lockin_enabled": True,
        "late_lockin_max_strength": 0.85,
        "adjacent_calibration_enabled": True,
        "adjacent_calibration": {},
        "exact_winner_catchup_enabled": bool(exact_winner_catchup_enabled),
        "exact_winner_catchup": {},
        "forecast_centering_enabled": False,
        "forecast_centering_sigma": 1.25,
        "forecast_centering_default_alpha": 0.0,
        "forecast_centering_early_alpha": 0.0,
        "forecast_centering_alpha_by_hour": {},
        "market_bias_calibration_enabled": False,
        "market_bias_calibration": {},
        "partition_normalization_enabled": True,
        "partition_normalization_gamma": 1.25,
        "current_blend_enabled": True,
        "current_blend_default_alpha": 1.0,
        "current_blend_market_alpha": {
            "dallas": 0.0,
            "denver": 0.20,
            "houston": 0.20,
            "los-angeles": 0.20,
            "miami": 0.0,
            "nyc": 0.20,
            "san-francisco": 0.0,
            "seattle": 0.20,
        },
        "current_blend_context_alpha": [
            {
                "policy_id": "item232_current_max_trust_warm_tail_backoff_v0_1",
                "description": "Reduce warm-tail candidate weight when forecast-relative pressure is warm-side.",
                "forecast_bucket_pressure": "warm_side",
                "alpha": 0.35,
            },
            {
                "policy_id": "item232_current_max_trust_warm_tail_backoff_v0_1",
                "description": "Reduce warm-tail candidate weight when the band sits at least two degrees above the printed floor.",
                "band_mid_minus_high_so_far_min": 2.0,
                "alpha": 0.35,
            },
            {
                "policy_id": "item232_current_max_trust_warm_tail_backoff_v0_1",
                "description": "Use half candidate weight when current-max is support-only, quarantined, or pre-reset.",
                "current_max_disposition": ["support_only", "quarantined", "null_before_reset"],
                "alpha": 0.50,
            },
        ],
    }
    if exact_winner_catchup_enabled and exact_winner_shadow_blend:
        # Item 70 is a catch-up shadow lane. Keep incumbent blending disabled
        # except for markets that cleared paired full-replay guardrails.
        config["current_blend_default_alpha"] = 0.0
        config["current_blend_market_alpha"] = {
            "chicago": 0.10,
            "houston": 0.10,
            "nyc": 0.10,
            "seattle": 0.10,
        }
    return config


def apply_source_freshness_guardrail(
    artifact,
    policy_id="item35_all_fresh_only_candidate_v0_1",
):
    """Blend non-all-fresh replay rows fully back to incumbent serving."""
    postprocess = artifact.setdefault("postprocess", {})
    postprocess["current_blend_source_freshness_default_alpha"] = 0.0
    postprocess["current_blend_source_freshness_alpha"] = {
        "all_fresh": 1.0,
    }
    postprocess["source_freshness_guardrail_policy"] = policy_id
    for bundle in (artifact.get("models") or {}).values():
        bundle["postprocess"] = dict(postprocess)
    return artifact


def train_pooled_density_models(records, holdout_year=None, grid_step_f=0.1, min_sigma_validation_residuals=20):
    canonical_records = [
        row for row in canonical_density_records(records)
        if row.get("final_bucket_f") is not None
    ]
    by_hour = defaultdict(list)
    for row in canonical_records:
        by_hour[int(row["cutoff_hour"])].append(row)

    low_f, high_f = density_support_f(canonical_records)
    grid_f = canonical_grid_f(low_f, high_f, grid_step_f)
    artifact = {
        "schema_version": "pooled_continuous_density_hgb_v0.7",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "all",
        "prediction_mode": "continuous_density_f",
        "objective": "canonical_f_density_shape_holdout_forecast_relative_band_postprocess",
        "trained_at": datetime.now().isoformat(),
        "grid_low_f": low_f,
        "grid_high_f": high_f,
        "grid_step_f": float(grid_step_f),
        "sigma_policy": {
            "preferred": "holdout_market_band_brier_grid_search",
            "fallback": "in_sample_residual_rmse",
            "min_validation_residuals": int(min_sigma_validation_residuals),
            "candidate_scales": list(DENSITY_SIGMA_TUNING_SCALES),
        },
        "density_shape_policy": {
            "preferred": "holdout_market_band_brier_shape_grid_search",
            "fallback": "gaussian_in_sample_residual_rmse",
            "candidate_shape_ids": [
                density_shape_id(row)
                for row in DENSITY_SHAPE_TUNING_CANDIDATES
            ],
        },
        "blocked_validation": blocked_validation_audit(canonical_records),
        "models": {},
    }
    validation_rows = []
    density_calibration_rows = []
    density_calibration_probabilities = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 20:
            continue
        model, imputer, feature_names, residuals, train_metrics = train_density_hour_model(train_rows)
        sigma_f = residual_sigma_f(residuals)
        eval_score = None
        baseline_eval_score = None
        market_scores = []
        eval_residuals = []
        sigma_tuning = None
        shape_tuning = None
        if eval_rows:
            eval_means = predict_density_means(
                model,
                imputer,
                feature_names,
                eval_rows,
            )
            eval_residuals = density_residuals_from_means(eval_rows, eval_means)
            baseline_eval_score = evaluate_density_sigma(eval_rows, eval_means, grid_f, sigma_f)
            sigma_tuning = tune_density_sigma_f(eval_rows, eval_means, grid_f, sigma_f)
            shape_tuning = tune_density_shape_policy(eval_rows, eval_means, grid_f, sigma_f)
            tuned_sigma_f = (
                (shape_tuning or {}).get("selected_sigma_f")
                if len(eval_residuals) >= int(min_sigma_validation_residuals)
                else None
            )
            tuned_shape = (
                (shape_tuning or {}).get("selected_density_shape")
                if len(eval_residuals) >= int(min_sigma_validation_residuals)
                else None
            )
            eval_sigma_f = tuned_sigma_f if tuned_sigma_f is not None else sigma_f
            eval_shape = density_shape_config(tuned_shape)
            eval_score = evaluate_density_sigma(
                eval_rows,
                eval_means,
                grid_f,
                eval_sigma_f,
                shape_config=eval_shape,
            )
            post_rows, post_probabilities = density_projected_market_band_rows_and_probabilities(
                eval_rows,
                eval_means,
                grid_f,
                eval_sigma_f,
                shape_config=eval_shape,
            )
            density_calibration_rows.extend(post_rows)
            density_calibration_probabilities.extend(post_probabilities)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                subset = [
                    (row, mean)
                    for row, mean in zip(eval_rows, eval_means)
                    if row["market_id"] == market_id
                ]
                score = evaluate_density_sigma(
                    [row for row, _ in subset],
                    [mean for _, mean in subset],
                    grid_f,
                    eval_sigma_f,
                    shape_config=eval_shape,
                )
                if score:
                    market_scores.append({
                        "market_id": market_id,
                        "density_shape_id": eval_shape["id"],
                        **score,
                    })

        final_model, final_imputer, final_feature_names, final_residuals, final_metrics = train_density_hour_model(hour_rows)
        if len(eval_residuals) >= int(min_sigma_validation_residuals) and (shape_tuning or {}).get("selected_sigma_f"):
            final_sigma_source = "holdout_market_band_brier_shape_grid_search"
            final_sigma_residuals = eval_residuals
            final_sigma_f = float(shape_tuning["selected_sigma_f"])
            final_density_shape = density_shape_config(shape_tuning.get("selected_density_shape"))
            final_density_shape_source = "holdout_market_band_brier_shape_grid_search"
        else:
            final_sigma_source = "in_sample_residual_rmse"
            final_sigma_residuals = final_residuals
            final_sigma_f = residual_sigma_f(final_sigma_residuals)
            final_density_shape = density_shape_config(DENSITY_DEFAULT_SHAPE)
            final_density_shape_source = "gaussian_fallback"
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "train_rows": len(hour_rows),
            "sigma_f": final_sigma_f,
            "sigma_source": final_sigma_source,
            "sigma_residual_count": len(final_sigma_residuals),
            "density_shape_id": final_density_shape["id"],
            "density_shape": final_density_shape,
            "density_shape_source": final_density_shape_source,
            "sigma_tuning": sigma_tuning,
            "density_shape_tuning": shape_tuning,
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "sigma_f": sigma_f,
            "final_sigma_f": final_sigma_f,
            "final_sigma_source": final_sigma_source,
            "final_sigma_residual_count": len(final_sigma_residuals),
            "final_density_shape_id": final_density_shape["id"],
            "final_density_shape_source": final_density_shape_source,
            "holdout_sigma_residual_count": len(eval_residuals),
            "eval_score": eval_score,
            "baseline_eval_score": baseline_eval_score,
            "sigma_tuning": sigma_tuning,
            "density_shape_tuning": shape_tuning,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    if density_calibration_rows:
        artifact["density_postprocess"] = fit_density_market_band_postprocess(
            density_calibration_rows,
            density_calibration_probabilities,
        )
    else:
        artifact["density_postprocess"] = {
            "schema_version": "density_market_band_postprocess_v0.2",
            "enabled": False,
            "calibration_rows": 0,
            "reason": "no holdout market-band calibration rows",
        }
    return artifact, validation_rows


def predict_density_rows_for_bundle(bundle, rows):
    if not bundle or not rows:
        return []
    rows = canonical_density_records(rows)
    grid_f = canonical_grid_f(
        bundle.get("grid_low_f", 30.0),
        bundle.get("grid_high_f", 125.0),
        bundle.get("grid_step_f", 0.1),
    )
    output = [None] * len(rows)
    by_hour = defaultdict(list)
    for index, row in enumerate(rows):
        try:
            hour = str(int(row.get("cutoff_hour")))
        except (TypeError, ValueError):
            continue
        by_hour[hour].append((index, row))
    for hour, indexed_rows in by_hour.items():
        model_bundle = (bundle.get("models") or {}).get(hour)
        if not model_bundle:
            continue
        payloads = predict_density_payloads(
            model_bundle["model"],
            model_bundle["imputer"],
            model_bundle["feature_names"],
            [row for _, row in indexed_rows],
            model_bundle.get("sigma_f", 3.0),
            grid_f,
            shape_config=model_bundle.get("density_shape"),
        )
        for (index, _row), payload in zip(indexed_rows, payloads):
            output[index] = payload
    return output


def train_pooled_band_models(
    records,
    holdout_year=None,
    exact_winner_catchup=False,
    dynamic_source_state=False,
    feature_subset=FEATURE_SUBSET_ALL,
    weak_family_disposition=None,
    reanalysis_promotion_lane=None,
    family_unit="F",
    source_freshness_guardrail=False,
    write_merge_payload=False,
):
    if exact_winner_catchup and dynamic_source_state:
        raise ValueError("exact_winner_catchup and dynamic_source_state are separate shadow variants")
    feature_subset = feature_subset or FEATURE_SUBSET_ALL
    if feature_subset not in FEATURE_SUBSET_CHOICES:
        raise ValueError(f"Unknown pooled feature subset: {feature_subset}")
    if feature_subset != FEATURE_SUBSET_ALL and (exact_winner_catchup or dynamic_source_state):
        raise ValueError("feature subsets are separate candidate lanes from exact/dynamic source variants")
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    support = band_training_support(records, family_unit=family_unit)
    all_market_band = str(family_unit or "").lower() == "all"
    schema_version = (
        "pooled_all_market_band_hgb_v0.1"
        if all_market_band else
        "pooled_feature_band_hgb_v0.3"
    )
    objective = (
        "binary_native_market_band_brier_all_market_source_reliability"
        if all_market_band else
        "binary_market_band_brier_source_reliability"
    )
    if exact_winner_catchup:
        schema_version = (
            "pooled_all_market_band_hgb_exact_winner_v0.1"
            if all_market_band else
            "pooled_feature_band_hgb_v0.4"
        )
        objective = (
            "binary_native_market_band_brier_all_market_exact_winner_catchup"
            if all_market_band else
            "binary_market_band_brier_source_reliability_exact_winner_catchup"
        )
    if dynamic_source_state:
        schema_version = "pooled_feature_band_hgb_v0.5"
        objective = "binary_market_band_brier_dynamic_source_state"
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        schema_version = "pooled_feature_band_hgb_forecast_profile_v0.1"
        objective = "binary_market_band_brier_forecast_profile_calibrated"
    if feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        schema_version = "pooled_feature_band_hgb_forecast_radiation_v0.1"
        objective = "binary_market_band_brier_forecast_radiation_calibrated"
    if feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        schema_version = "pooled_feature_band_hgb_marine_contrast_v0.1"
        objective = "binary_market_band_brier_marine_water_contrast"
    artifact = {
        "schema_version": schema_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": family_unit,
        "prediction_mode": "band_binary",
        "objective": objective,
        "feature_subset": feature_subset,
        "feature_subset_contract": feature_subset_contract(feature_subset),
        "dynamic_source_state_enabled": bool(dynamic_source_state),
        "dynamic_source_state_columns": (
            DYNAMIC_SOURCE_NUMERIC_COLUMNS + DYNAMIC_SOURCE_CATEGORICAL_COLUMNS
            if dynamic_source_state else []
        ),
        "trained_at": datetime.now().isoformat(),
        "support": support,
        "blocked_validation": blocked_validation_audit(records),
        "models": {},
        "postprocess": default_band_postprocess(
            exact_winner_catchup_enabled=exact_winner_catchup,
            exact_winner_shadow_blend=not all_market_band,
        ),
    }
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        artifact["forecast_profile_calibration"] = {
            "schema_version": "forecast_profile_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "forecast_high",
            "feature_subset": feature_subset,
            "daily_first_replay_required": True,
            "promotion_blocker": (
                "Forecast-profile weighting cannot promote unless replay "
                "proves early-day lift, midday/late guardrails, and "
                "per-market high-disagreement safety."
            ),
        }
    if feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        artifact["forecast_radiation_calibration"] = {
            "schema_version": "forecast_radiation_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "forecast_high",
            "feature_subset": feature_subset,
            "daily_first_replay_required": True,
            "promotion_blocker": (
                "Forecast-radiation weighting cannot promote unless replay "
                "proves early/midday lift, late guardrails, and market safety."
            ),
        }
    if feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        artifact["marine_contrast_calibration"] = {
            "schema_version": "marine_contrast_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "marine_water_minus_forecast_high",
            "feature_subset": feature_subset,
            "onshore_breeze_replay_required": True,
            "promotion_blocker": (
                "Marine contrast cannot promote unless a scoped settlement "
                "replay proves onshore/breeze-slice lift with no aggregate "
                "regression."
            ),
        }
    if dynamic_source_state:
        artifact["postprocess"]["current_blend_source_freshness_default_alpha"] = 0.0
        artifact["postprocess"]["current_blend_source_freshness_alpha"] = {
            "all_fresh": 1.0,
            "failed:local_history": 1.0,
            "failed:metar,wu_history": 1.0,
            "failed:wu_history;stale:metar": 1.0,
            "stale:metar": 1.0,
            "failed:metar": 0.0,
            "failed:wu_history": 0.0,
        }
        artifact["postprocess"]["current_blend_market_alpha"] = {
            **(artifact["postprocess"].get("current_blend_market_alpha") or {}),
            "miami": 0.0,
        }
    if source_freshness_guardrail:
        apply_source_freshness_guardrail(artifact)
    apply_reanalysis_lane_metadata(artifact, reanalysis_promotion_lane)
    validation_rows = []
    calibration_rows = []
    calibration_probabilities = []
    merge_payload_rows = []
    merge_payload_probabilities = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_source_rows = hour_rows
            eval_source_rows = []
        else:
            train_source_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_source_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        train_band_rows = build_band_rows(train_source_rows, support)
        if len(train_band_rows) < 200 or len({row["outcome"] for row in train_band_rows}) < 2:
            continue

        model, imputer, feature_names, train_metrics = train_band_hour_model(
            train_band_rows,
            include_dynamic_source_state=dynamic_source_state,
            feature_subset=feature_subset,
        )
        eval_score = None
        raw_eval_score = None
        temperature = 1.0
        tuned_brier = None
        market_scores = []
        eval_band_rows = []
        post_probs = []
        if eval_source_rows:
            eval_band_rows = build_band_rows(eval_source_rows, support)
            if eval_band_rows:
                raw_probs = predict_band_probabilities(
                    model,
                    imputer,
                    feature_names,
                    eval_band_rows,
                    temperature=1.0,
                )
                raw_eval_score = evaluate_band_predictions(eval_band_rows, raw_probs)
                temperature, tuned_brier = tune_temperature(eval_band_rows, raw_probs)
                tuned_probs = [
                    temperature_scale_probability(probability, temperature=temperature)
                    for probability in raw_probs
                ]
                post_probs = [
                    apply_band_postprocessing(
                        probability,
                        row,
                        config=artifact["postprocess"],
                    )
                    for row, probability in zip(eval_band_rows, tuned_probs)
                ]
                if write_merge_payload:
                    merge_payload_rows.extend(eval_band_rows)
                    merge_payload_probabilities.extend(post_probs)
                calibration_rows.extend(eval_band_rows)
                calibration_probabilities.extend(post_probs)
                eval_score = evaluate_band_predictions(eval_band_rows, post_probs)
                for market_id in sorted({row["market_id"] for row in eval_band_rows}):
                    subset = [
                        (row, probability)
                        for row, probability in zip(eval_band_rows, post_probs)
                        if row["market_id"] == market_id
                    ]
                    score = evaluate_band_predictions(
                        [row for row, _ in subset],
                        [probability for _, probability in subset],
                    )
                    if score:
                        market_scores.append({"market_id": market_id, **score})

        final_band_rows = build_band_rows(hour_rows, support)
        final_model, final_imputer, final_feature_names, final_metrics = train_band_hour_model(
            final_band_rows,
            include_dynamic_source_state=dynamic_source_state,
            feature_subset=feature_subset,
        )
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(final_band_rows),
            "source_rows": len(hour_rows),
            "temperature": temperature,
            "postprocess": dict(artifact["postprocess"]),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "source_train_rows": len(train_source_rows),
            "band_train_rows": len(train_band_rows),
            "source_eval_rows": len(eval_source_rows),
            "temperature": temperature,
            "tuned_brier": tuned_brier,
            "raw_eval_score": raw_eval_score,
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
            "_eval_band_rows": eval_band_rows if eval_source_rows else [],
            "_post_probs": post_probs if eval_source_rows else [],
        })
    calibration = fit_adjacent_calibration(calibration_rows, calibration_probabilities)
    artifact["postprocess"]["adjacent_calibration"] = calibration
    exact_rows = []
    exact_probabilities = []
    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows", [])
        post_probs = validation.pop("_post_probs", [])
        if not eval_band_rows or not post_probs:
            continue
        adjacent_probs = [
            apply_adjacent_calibration(
                probability,
                row,
                config=artifact["postprocess"],
            )
            for row, probability in zip(eval_band_rows, post_probs)
        ]
        if exact_winner_catchup:
            exact_rows.extend(eval_band_rows)
            exact_probabilities.extend(adjacent_probs)
        validation["_eval_band_rows_for_exact"] = eval_band_rows
        validation["_adjacent_probs_for_exact"] = adjacent_probs

    if exact_winner_catchup:
        exact_calibration = fit_exact_winner_catchup(
            exact_rows,
            exact_probabilities,
            guardrail_rows=exact_rows,
            guardrail_probabilities=exact_probabilities,
            normalization_gamma=artifact["postprocess"].get("partition_normalization_gamma", 1.25),
        )
        artifact["postprocess"]["exact_winner_catchup"] = exact_calibration

    market_bias_rows = []
    market_bias_probabilities = []
    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows_for_exact", [])
        adjacent_probs = validation.pop("_adjacent_probs_for_exact", [])
        if not eval_band_rows or not adjacent_probs:
            continue
        calibrated_probs = adjacent_probs
        if exact_winner_catchup:
            calibrated_probs = [
                apply_exact_winner_catchup(
                    probability,
                    row,
                    config=artifact["postprocess"],
                )
                for row, probability in zip(eval_band_rows, adjacent_probs)
            ]
        validation["_eval_band_rows_for_market_bias"] = eval_band_rows
        validation["_probabilities_for_market_bias"] = calibrated_probs
        market_bias_rows.extend(eval_band_rows)
        market_bias_probabilities.extend(calibrated_probs)

    market_bias_calibration = fit_market_bias_calibration(
        market_bias_rows,
        market_bias_probabilities,
    )
    artifact["postprocess"]["market_bias_calibration"] = market_bias_calibration
    artifact["postprocess"]["market_bias_calibration_enabled"] = bool(
        market_bias_calibration.get("enabled")
    )

    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows_for_market_bias", [])
        calibrated_probs = validation.pop("_probabilities_for_market_bias", [])
        if not eval_band_rows or not calibrated_probs:
            continue
        final_probs = [
            apply_market_bias_calibration(
                probability,
                row,
                config=artifact["postprocess"],
            )
            for row, probability in zip(eval_band_rows, calibrated_probs)
        ]
        validation["eval_score"] = evaluate_band_predictions(eval_band_rows, final_probs)
        market_scores = []
        for market_id in sorted({row["market_id"] for row in eval_band_rows}):
            subset = [
                (row, probability)
                for row, probability in zip(eval_band_rows, final_probs)
                if row["market_id"] == market_id
            ]
            score = evaluate_band_predictions(
                [row for row, _ in subset],
                [probability for _, probability in subset],
            )
            if score:
                market_scores.append({"market_id": market_id, **score})
        validation["market_scores"] = market_scores
    for bundle in artifact["models"].values():
        bundle["postprocess"] = dict(artifact["postprocess"])
    model_feature_names = sorted({
        feature
        for bundle in artifact["models"].values()
        for feature in (bundle.get("feature_names") or [])
    })
    artifact["weak_input_family_preflight"] = weak_input_training_preflight(
        model_feature_names,
        weak_family_disposition,
    )
    if write_merge_payload:
        artifact[BAND_MERGE_PAYLOAD_KEY] = {
            "holdout_year": holdout_year,
            "hours": sorted(int(hour) for hour in artifact["models"]),
            "rows": merge_payload_rows,
            "probabilities": merge_payload_probabilities,
        }
    return artifact, validation_rows


from weather.model.variant_prediction_runtime import predict_density_rows_for_bundle  # noqa: E402

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
