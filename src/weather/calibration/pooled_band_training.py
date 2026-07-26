"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

from weather.calibration.pooled_density_training import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def train_band_hour_model(
    train_rows,
    feature_names=None,
    include_dynamic_source_state=False,
    feature_subset=FEATURE_SUBSET_ALL,
    prefit_imputer=None,
):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = band_feature_frame(
            train_rows,
            feature_names=feature_names,
            include_dynamic_source_state=include_dynamic_source_state,
        )
        if feature_names is None:
            train_frame = train_frame.reindex(
                columns=feature_names_for_subset(train_frame.columns, feature_subset),
            )
    build_seconds = time.perf_counter() - build_started
    feature_names = list(train_frame.columns)
    # Preserve the declared feature contract even when a training fold has an
    # entirely missing column; otherwise sklearn drops it and serving-time
    # transforms can silently change shape across folds/runs.
    imputer = prefit_imputer
    if imputer is None:
        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        x_train = imputer.fit_transform(train_frame)
        imputer_fit_scope = "model_training_rows"
    else:
        # Production point-in-time fitting records imputation as its own
        # training-only stage, then hands that exact fitted object to the HGB
        # trainer.  Research callers retain the historical fit-in-model path.
        x_train = imputer.transform(train_frame)
        imputer_fit_scope = "prefit_training_only_stage"
    y_train = np.array([int(row["outcome"]) for row in train_rows])
    weights = np.array([float(row.get("_sample_weight", 1.0)) for row in train_rows])
    model = HistGradientBoostingClassifier(
        max_iter=90,
        max_leaf_nodes=31,
        learning_rate=0.05,
        random_state=42,
    )
    fit_started = time.perf_counter()
    model.fit(x_train, y_train, sample_weight=weights)
    fit_seconds = time.perf_counter() - fit_started
    metrics = {
        "matrix_rows": int(train_frame.shape[0]),
        "matrix_columns": int(train_frame.shape[1]),
        "matrix_build_seconds": round(build_seconds, 6),
        "model_fit_seconds": round(fit_seconds, 6),
        "performance_warning_count": performance_warning_count(caught),
        "feature_subset": feature_subset or FEATURE_SUBSET_ALL,
        "imputer_fit_scope": imputer_fit_scope,
    }
    return model, imputer, feature_names, metrics


def _band_width_label(row):
    try:
        lo = float(row.get("band_value"))
        hi = float(row.get("band_value_hi"))
    except (TypeError, ValueError):
        return "single"
    return "range" if hi > lo else "single"


def fit_adjacent_calibration(
    rows,
    probabilities,
    min_rows=80,
    prior_rows=120.0,
    factor_min=0.15,
    factor_max=2.50,
):
    """Fit multiplicative calibration factors for above-floor eq/range bands."""
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows, probabilities):
        contexts = adjacent_calibration_contexts(row)
        if not contexts:
            continue
        try:
            probability = clip_probability(probability)
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in contexts:
            stats[context]["n"] += 1
            stats[context]["outcome_sum"] += outcome
            stats[context]["prob_sum"] += probability

    contexts = {}
    for context, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        prob_sum = float(stat["prob_sum"])
        if prob_sum <= 0:
            continue
        mean_probability = prob_sum / n
        # Smooth toward factor 1.0 by adding prior rows with the model's own
        # mean probability. This keeps sparse city/hour cells from becoming a
        # second model trained on noise.
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        smoothed_predicted = (
            prob_sum + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if smoothed_predicted <= 0:
            continue
        factor = smoothed_observed / smoothed_predicted
        factor = max(float(factor_min), min(float(factor_max), factor))
        contexts[context] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }

    return {
        "version": "adjacent_market_hour_floor_gap_v1",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "context_count": len(contexts),
        "contexts": contexts,
    }


def _brier_for_probabilities(rows, probabilities):
    pairs = [
        (row, probability)
        for row, probability in zip(rows or [], probabilities or [])
        if probability is not None and row.get("outcome") is not None
    ]
    if not pairs:
        return None
    return sum(
        brier(clip_probability(probability), int(row["outcome"]))
        for row, probability in pairs
    ) / len(pairs)


def _market_brier_map(rows, probabilities):
    grouped = defaultdict(list)
    for row, probability in zip(rows or [], probabilities or []):
        if probability is None or row.get("outcome") is None:
            continue
        grouped[row.get("market_id") or "unknown"].append((row, probability))
    return {
        market_id: sum(
            brier(clip_probability(probability), int(row["outcome"]))
            for row, probability in pairs
        ) / len(pairs)
        for market_id, pairs in grouped.items()
        if pairs
    }


def fit_market_bias_calibration(
    rows,
    probabilities,
    min_rows=120,
    prior_rows=400.0,
    factor_min=0.40,
    factor_max=2.25,
    min_improvement=0.0002,
    max_market_regression=0.0010,
):
    """Fit a conservative multiplicative market/hour/kind calibration.

    The contexts deliberately use only fields available before settlement. The
    calibration is enabled only if it improves holdout Brier and does not create
    a material market-level regression on the same holdout partition.
    """
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    clean_rows = []
    clean_probabilities = []
    for row, probability in zip(rows or [], probabilities or []):
        if row.get("outcome") is None or probability is None:
            continue
        probability = clip_probability(probability)
        clean_rows.append(row)
        clean_probabilities.append(probability)
        outcome = float(row.get("outcome") or 0.0)
        for context in market_bias_calibration_contexts(row):
            stats[context]["n"] += 1
            stats[context]["outcome_sum"] += outcome
            stats[context]["prob_sum"] += probability

    contexts = {}
    for context, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        prob_sum = float(stat["prob_sum"])
        if prob_sum <= 0:
            continue
        mean_probability = prob_sum / n
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        smoothed_predicted = (
            prob_sum + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if smoothed_predicted <= 0:
            continue
        factor = smoothed_observed / smoothed_predicted
        factor = max(float(factor_min), min(float(factor_max), factor))
        contexts[context] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }

    calibration = {
        "version": "market_hour_kind_bias_v1",
        "enabled": False,
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "min_improvement": float(min_improvement),
        "max_market_regression": float(max_market_regression),
        "context_count": len(contexts),
        "contexts": contexts,
    }
    baseline_brier = _brier_for_probabilities(clean_rows, clean_probabilities)
    trial_calibration = {**calibration, "enabled": True}
    candidate_probabilities = [
        apply_market_bias_calibration(
            probability,
            row,
            config={"market_bias_calibration": trial_calibration},
        )
        for row, probability in zip(clean_rows, clean_probabilities)
    ]
    candidate_brier = _brier_for_probabilities(clean_rows, candidate_probabilities)
    baseline_by_market = _market_brier_map(clean_rows, clean_probabilities)
    candidate_by_market = _market_brier_map(clean_rows, candidate_probabilities)
    market_regressions = {
        market_id: candidate_by_market[market_id] - baseline_brier
        for market_id, baseline_brier in baseline_by_market.items()
        if market_id in candidate_by_market
        and candidate_by_market[market_id] - baseline_brier > float(max_market_regression)
    }
    enabled = (
        baseline_brier is not None
        and candidate_brier is not None
        and candidate_brier <= baseline_brier - float(min_improvement)
        and not market_regressions
        and bool(contexts)
    )
    calibration.update({
        "enabled": bool(enabled),
        "selection": {
            "baseline_brier": baseline_brier,
            "candidate_brier": candidate_brier,
            "delta_brier": (
                candidate_brier - baseline_brier
                if baseline_brier is not None and candidate_brier is not None
                else None
            ),
            "market_regressions": market_regressions,
        },
    })
    if not enabled:
        calibration["disabled_reason"] = (
            "holdout_brier_or_market_regression_gate_failed"
            if contexts else
            "no_contexts"
        )
    return calibration


def fit_exact_winner_catchup(
    rows,
    probabilities,
    min_rows=80,
    prior_rows=160.0,
    factor_min=0.50,
    factor_max=1.80,
    guardrail_rows=None,
    guardrail_probabilities=None,
    strength_grid=None,
    one_above_tolerance=0.0002,
    normalization_gamma=1.25,
):
    """Fit smoothed factors for exact/range winner catch-up contexts."""
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows, probabilities):
        contexts = exact_winner_catchup_contexts(row)
        if not contexts:
            continue
        probability = clip_probability(probability)
        try:
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in contexts:
            stats[context]["n"] += 1
            stats[context]["outcome_sum"] += outcome
            stats[context]["prob_sum"] += probability

    contexts = {}
    for context, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        prob_sum = float(stat["prob_sum"])
        if prob_sum <= 0:
            continue
        mean_probability = prob_sum / n
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        smoothed_predicted = (
            prob_sum + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if smoothed_predicted <= 0:
            continue
        factor = smoothed_observed / smoothed_predicted
        factor = max(float(factor_min), min(float(factor_max), factor))
        contexts[context] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }

    calibration = {
        "version": "pooled_feature_band_hgb_v0.4",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "strength": 1.0,
        "context_count": len(contexts),
        "contexts": contexts,
    }
    if guardrail_rows is not None and guardrail_probabilities is not None:
        diagnostics = select_exact_winner_catchup_strength(
            guardrail_rows,
            guardrail_probabilities,
            calibration,
            strength_grid=strength_grid,
            one_above_tolerance=one_above_tolerance,
            normalization_gamma=normalization_gamma,
        )
        calibration["strength"] = diagnostics["selected_strength"]
        calibration["strength_diagnostics"] = diagnostics
    return calibration


def _exact_strength_grid(values=None):
    if values is None:
        values = (1.0, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.0)
    cleaned = []
    for value in values:
        try:
            strength = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
        if strength not in cleaned:
            cleaned.append(strength)
    return cleaned or [0.0]


def _with_exact_strength(calibration, strength):
    copy = dict(calibration or {})
    copy["strength"] = max(0.0, min(1.0, float(strength)))
    return copy


def _settlement_distance_value(row):
    value = row.get("settlement_distance")
    if value in (None, ""):
        value = row.get("settlement_distance_bucket")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _band_validation_partition_key(row):
    return (
        row.get("market_id") or "unknown",
        row.get("target_date") or "unknown",
        row.get("cutoff_hour") or row.get("candidate_cutoff_hour") or "unknown",
    )


def normalize_band_probabilities_for_rows(rows, probabilities, gamma=1.25):
    """Mirror replay partition normalization for held-out training rows."""
    grouped = _band_validation_groups(rows)
    return _normalize_band_probabilities_for_groups(probabilities, grouped, gamma=gamma)


def _band_validation_groups(rows):
    grouped = defaultdict(list)
    for idx, row in enumerate(rows):
        grouped[_band_validation_partition_key(row)].append(idx)
    return grouped


def _normalize_band_probabilities_for_groups(probabilities, grouped, gamma=1.25):
    gamma = max(0.1, float(gamma or 1.0))
    output = [clip_probability(probability) for probability in probabilities]
    for indexes in grouped.values():
        weights = [max(1e-12, output[idx]) ** gamma for idx in indexes]
        total = sum(weights)
        if total <= 0:
            continue
        for idx, weight in zip(indexes, weights):
            output[idx] = weight / total
    return output


def _slice_brier(rows, probabilities, predicate):
    pairs = [
        (row, float(probability))
        for row, probability in zip(rows, probabilities)
        if predicate(row) and row.get("outcome") is not None
    ]
    if not pairs:
        return {"n": 0, "brier": None, "base_rate": None, "mean_probability": None}
    return {
        "n": len(pairs),
        "brier": sum(brier(probability, int(row["outcome"])) for row, probability in pairs) / len(pairs),
        "base_rate": sum(int(row["outcome"]) for row, _ in pairs) / len(pairs),
        "mean_probability": sum(probability for _, probability in pairs) / len(pairs),
    }


def _slice_brier_indexes(outcomes, probabilities, indexes):
    pairs = [
        (int(outcomes[idx]), float(probabilities[idx]))
        for idx in indexes
        if outcomes[idx] is not None
    ]
    if not pairs:
        return {"n": 0, "brier": None, "base_rate": None, "mean_probability": None}
    return {
        "n": len(pairs),
        "brier": sum(brier(probability, outcome) for outcome, probability in pairs) / len(pairs),
        "base_rate": sum(outcome for outcome, _ in pairs) / len(pairs),
        "mean_probability": sum(probability for _, probability in pairs) / len(pairs),
    }


def _exact_winner_factor_delta(row, contexts):
    if not contexts:
        return 0.0
    for context in exact_winner_catchup_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            factor = float(entry.get("factor", 1.0))
        else:
            factor = float(entry)
        return factor - 1.0
    return 0.0


def _strength_candidate_probabilities_precomputed(
    probabilities,
    factor_deltas,
    groups,
    strength,
    normalization_gamma=1.25,
):
    adjusted = [
        clip_probability(probability * (1.0 + float(strength) * delta))
        for probability, delta in zip(probabilities, factor_deltas)
    ]
    return _normalize_band_probabilities_for_groups(
        adjusted,
        groups,
        gamma=normalization_gamma,
    )


def _strength_candidate_probabilities(rows, probabilities, calibration, strength, normalization_gamma=1.25):
    config = {"exact_winner_catchup": _with_exact_strength(calibration, strength)}
    adjusted = [
        apply_exact_winner_catchup(probability, row, config=config)
        for row, probability in zip(rows, probabilities)
    ]
    return normalize_band_probabilities_for_rows(rows, adjusted, gamma=normalization_gamma)


def select_exact_winner_catchup_strength(
    rows,
    probabilities,
    calibration,
    strength_grid=None,
    one_above_tolerance=0.0002,
    normalization_gamma=1.25,
):
    """Select the strongest exact-winner boost that protects adjacent rows."""
    rows = list(rows or [])
    probabilities = [clip_probability(probability) for probability in (probabilities or [])]
    grid = _exact_strength_grid(strength_grid)
    groups = _band_validation_groups(rows)
    baseline = _normalize_band_probabilities_for_groups(
        probabilities,
        groups,
        gamma=normalization_gamma,
    )
    outcomes = []
    distance0_indexes = []
    one_above_indexes = []
    eq_indexes = []
    for idx, row in enumerate(rows):
        try:
            outcome = int(row["outcome"]) if row.get("outcome") is not None else None
        except (TypeError, ValueError):
            outcome = None
        outcomes.append(outcome)
        distance = _settlement_distance_value(row)
        if distance == 0:
            distance0_indexes.append(idx)
        if distance == 1:
            one_above_indexes.append(idx)
        if row.get("band_kind") == "eq":
            eq_indexes.append(idx)
    factor_deltas = [
        _exact_winner_factor_delta(row, calibration.get("contexts") or {})
        for row in rows
    ]
    baseline_distance0 = _slice_brier_indexes(outcomes, baseline, distance0_indexes)
    baseline_one_above = _slice_brier_indexes(outcomes, baseline, one_above_indexes)
    baseline_eq = _slice_brier_indexes(outcomes, baseline, eq_indexes)

    candidates = []
    selected = None
    for strength in grid:
        candidate = _strength_candidate_probabilities_precomputed(
            probabilities,
            factor_deltas,
            groups,
            strength,
            normalization_gamma=normalization_gamma,
        )
        distance0 = _slice_brier_indexes(outcomes, candidate, distance0_indexes)
        one_above = _slice_brier_indexes(outcomes, candidate, one_above_indexes)
        eq = _slice_brier_indexes(outcomes, candidate, eq_indexes)
        distance0_delta = (
            distance0["brier"] - baseline_distance0["brier"]
            if distance0["brier"] is not None and baseline_distance0["brier"] is not None
            else None
        )
        one_above_delta = (
            one_above["brier"] - baseline_one_above["brier"]
            if one_above["brier"] is not None and baseline_one_above["brier"] is not None
            else None
        )
        eq_delta = (
            eq["brier"] - baseline_eq["brier"]
            if eq["brier"] is not None and baseline_eq["brier"] is not None
            else None
        )
        passed = (
            (distance0_delta is None or distance0_delta <= 0.0)
            and (one_above_delta is None or one_above_delta <= float(one_above_tolerance))
        )
        item = {
            "strength": strength,
            "passed": bool(passed),
            "distance0_brier": distance0["brier"],
            "distance0_delta_vs_base": distance0_delta,
            "one_above_brier": one_above["brier"],
            "one_above_delta_vs_base": one_above_delta,
            "eq_brier": eq["brier"],
            "eq_delta_vs_base": eq_delta,
        }
        candidates.append(item)
        if passed and selected is None:
            selected = item
    if selected is None:
        fallback_strength = 0.0 if 0.0 in grid else grid[-1]
        selected = next(
            (item for item in candidates if item["strength"] == fallback_strength),
            candidates[-1] if candidates else {"strength": 0.0},
        )
    return {
        "selected_strength": float(selected["strength"]),
        "one_above_tolerance": float(one_above_tolerance),
        "normalization_gamma": float(normalization_gamma),
        "baseline": {
            "distance0_brier": baseline_distance0["brier"],
            "distance0_n": baseline_distance0["n"],
            "one_above_brier": baseline_one_above["brier"],
            "one_above_n": baseline_one_above["n"],
            "eq_brier": baseline_eq["brier"],
            "eq_n": baseline_eq["n"],
        },
        "selected": selected,
        "candidates": candidates,
    }


def evaluate_band_predictions(rows, probabilities):
    if not rows:
        return None
    losses = [
        brier(float(probability), int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ]
    log_losses = [
        binary_log_loss(float(probability), int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ]
    positives = [
        (row, probability)
        for row, probability in zip(rows, probabilities)
        if int(row["outcome"]) == 1
    ]
    exact_winners = [
        (row, probability)
        for row, probability in positives
        if row.get("band_kind") == "eq" and int(row.get("settlement_distance") or 0) == 0
    ]
    late_rows = [
        (row, probability)
        for row, probability in zip(rows, probabilities)
        if int(row.get("cutoff_hour") or 0) >= 16
    ]
    return {
        "n": len(rows),
        "base_rate": sum(int(row["outcome"]) for row in rows) / len(rows),
        "brier": sum(losses) / len(losses),
        "logloss": sum(log_losses) / len(log_losses),
        "positive_mean_p": (
            sum(float(probability) for _, probability in positives) / len(positives)
            if positives else None
        ),
        "exact_winner_mean_p": (
            sum(float(probability) for _, probability in exact_winners) / len(exact_winners)
            if exact_winners else None
        ),
        "late_brier": (
            sum(brier(float(probability), int(row["outcome"])) for row, probability in late_rows) / len(late_rows)
            if late_rows else None
        ),
    }


def tune_temperature(rows, raw_probabilities):
    if not rows:
        return 1.0, None
    grid = [0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.30, 1.50, 1.75, 2.0]
    best = (1.0, float("inf"))
    for temperature in grid:
        probs = [temperature_scale_probability(p, temperature=temperature) for p in raw_probabilities]
        score = sum(brier(p, int(row["outcome"])) for row, p in zip(rows, probs)) / len(rows)
        if score < best[1]:
            best = (temperature, score)
    return best[0], best[1]


from weather.model.variant_prediction_runtime import (  # noqa: E402
    adjacent_calibration_contexts,
    adjacent_calibration_factor,
    apply_adjacent_calibration,
    apply_band_postprocessing,
    apply_exact_winner_catchup,
    apply_forecast_centering,
    apply_market_bias_calibration,
    calibration_gap_bucket,
    calibration_hour_bucket,
    exact_winner_catchup_contexts,
    exact_winner_catchup_factor,
    forecast_anchor_probability,
    forecast_centering_alpha,
    market_bias_calibration_contexts,
    market_bias_calibration_factor,
    normal_cdf,
    pooled_band_regime_route,
    predict_band_probabilities,
    predict_band_rows_for_bundle,
    source_trust_bucket,
)

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
