"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

from weather.calibration.pooled_feature_assembly import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def band_training_support(records, family_unit="F"):
    """Return native support for synthetic market-band training rows."""
    if str(family_unit or "").lower() != "all":
        return sorted({int(row["final_bucket"]) for row in records})
    by_unit = defaultdict(set)
    for row in records:
        bucket = round_half_up(row.get("final_bucket"))
        if bucket is None:
            continue
        by_unit[record_unit(row)].add(int(bucket))
    return {
        unit: sorted(values)
        for unit, values in sorted(by_unit.items())
        if values
    }


def train_hour_model(train_rows, feature_names=None):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = feature_frame(train_rows, feature_names=feature_names)
    build_seconds = time.perf_counter() - build_started
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([int(row["final_bucket"]) for row in train_rows])
    model = HistGradientBoostingClassifier(
        max_iter=80,
        max_leaf_nodes=21,
        learning_rate=0.05,
        random_state=42,
    )
    fit_started = time.perf_counter()
    model.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - fit_started
    metrics = {
        "matrix_rows": int(train_frame.shape[0]),
        "matrix_columns": int(train_frame.shape[1]),
        "matrix_build_seconds": round(build_seconds, 6),
        "model_fit_seconds": round(fit_seconds, 6),
        "performance_warning_count": performance_warning_count(caught),
    }
    return model, imputer, feature_names, metrics


def predict_rows(model, imputer, feature_names, rows, support=None, epsilon=1e-4):
    frame = feature_frame(rows, feature_names=feature_names)
    x_eval = imputer.transform(frame)
    probabilities = model.predict_proba(x_eval)
    classes = [int(value) for value in model.classes_]
    support = sorted(set(support or classes) | set(classes))
    output = []
    for row in probabilities:
        dist = {bucket: float(epsilon) for bucket in support}
        for bucket, probability in zip(classes, row):
            dist[int(bucket)] = dist.get(int(bucket), 0.0) + float(probability)
        total = sum(dist.values())
        output.append({bucket: probability / total for bucket, probability in dist.items()})
    return output


def distribution_probability(distribution, bucket):
    return float(distribution.get(int(bucket), 0.0))


def evaluate_distributions(rows, distributions):
    if not rows:
        return None
    losses = []
    briers = []
    classes = sorted({int(row["final_bucket"]) for row in rows} | {
        bucket for dist in distributions for bucket in dist
    })
    for row, dist in zip(rows, distributions):
        y_bucket = int(row["final_bucket"])
        probs = [float(dist.get(bucket, 0.0)) for bucket in classes]
        total = sum(probs)
        if total <= 0:
            probs = [1.0 / len(classes)] * len(classes)
        else:
            probs = [p / total for p in probs]
        p_true = max(1e-15, probs[classes.index(y_bucket)])
        losses.append(-math.log(p_true))
        briers.append(brier(distribution_probability(dist, y_bucket), 1.0))
    return {
        "n": len(rows),
        "logloss": sum(losses) / len(losses),
        "winning_bucket_brier": sum(briers) / len(briers),
    }


def train_density_hour_model(train_rows, feature_names=None):
    build_started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        train_frame = feature_frame(train_rows, feature_names=feature_names)
    build_seconds = time.perf_counter() - build_started
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([float(row["final_bucket_f"]) for row in train_rows])
    model = HistGradientBoostingRegressor(
        max_iter=120,
        max_leaf_nodes=31,
        learning_rate=0.05,
        random_state=42,
    )
    fit_started = time.perf_counter()
    model.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - fit_started
    fitted = model.predict(x_train)
    residuals = [float(actual - predicted) for actual, predicted in zip(y_train, fitted)]
    metrics = {
        "matrix_rows": int(train_frame.shape[0]),
        "matrix_columns": int(train_frame.shape[1]),
        "matrix_build_seconds": round(build_seconds, 6),
        "model_fit_seconds": round(fit_seconds, 6),
        "performance_warning_count": performance_warning_count(caught),
    }
    return model, imputer, feature_names, residuals, metrics


def residual_sigma_f(residuals, floor=0.75, cap=10.0):
    clean = [float(value) for value in residuals or [] if value is not None and math.isfinite(float(value))]
    if not clean:
        return 3.0
    rmse = math.sqrt(sum(value * value for value in clean) / len(clean))
    return max(float(floor), min(float(cap), rmse))


def density_residuals_from_means(rows, means):
    residuals = []
    for row, mean_f in zip(rows or [], means or []):
        target_f = row.get("final_bucket_f")
        if target_f is None or mean_f is None:
            continue
        try:
            residual = float(target_f) - float(mean_f)
        except (TypeError, ValueError):
            continue
        if math.isfinite(residual):
            residuals.append(residual)
    return residuals


def density_support_f(rows, margin_f=15.0):
    targets = [
        float(row["final_bucket_f"])
        for row in rows or []
        if row.get("final_bucket_f") is not None
    ]
    if not targets:
        return 30.0, 125.0
    low = math.floor(min(targets) - float(margin_f))
    high = math.ceil(max(targets) + float(margin_f))
    return max(-40.0, float(low)), min(130.0, float(high))


def density_shape_config(shape_config=None):
    cfg = dict(DENSITY_DEFAULT_SHAPE)
    if isinstance(shape_config, dict):
        cfg.update({
            key: value
            for key, value in shape_config.items()
            if value is not None
        })
    shape = str(cfg.get("shape") or "gaussian")
    if shape not in {"gaussian", "tail_mixture", "anchor_mixture"}:
        shape = "gaussian"
    cfg["shape"] = shape
    cfg["id"] = str(cfg.get("id") or shape)
    return cfg


def density_shape_id(shape_config=None):
    return density_shape_config(shape_config).get("id") or "gaussian"


def density_shape_components(rows, means_array, sigma_f, shape_config=None):
    cfg = density_shape_config(shape_config)
    sigma = max(0.1, float(sigma_f or 1.0))
    base_weight = 1.0
    components = []

    def add_component(weight, centers, sigma_scale):
        weight = max(0.0, min(0.95, float(weight or 0.0)))
        sigma_scale = max(0.05, float(sigma_scale or 1.0))
        if weight <= 0:
            return
        components.append((weight, np.asarray(centers, dtype=float), sigma * sigma_scale))

    if cfg["shape"] == "tail_mixture":
        tail_weight = max(0.0, min(0.80, float(cfg.get("tail_weight") or 0.0)))
        base_weight -= tail_weight
        add_component(tail_weight, means_array, cfg.get("tail_scale") or 2.0)
    elif cfg["shape"] == "anchor_mixture":
        anchor_weight = max(0.0, min(0.80, float(cfg.get("anchor_weight") or 0.0)))
        anchor = cfg.get("anchor")
        anchor_values = []
        for row, mean_f in zip(rows or [], means_array):
            anchor_value = finite_float((row or {}).get(anchor))
            anchor_values.append(float(mean_f) if anchor_value is None else anchor_value)
        base_weight -= anchor_weight
        add_component(anchor_weight, anchor_values, cfg.get("anchor_sigma_scale") or 1.0)

    components.insert(0, (max(0.0, base_weight), np.asarray(means_array, dtype=float), sigma))
    total_weight = sum(component[0] for component in components)
    if total_weight <= 0:
        return [(1.0, np.asarray(means_array, dtype=float), sigma)]
    return [
        (weight / total_weight, centers, component_sigma)
        for weight, centers, component_sigma in components
        if weight > 0
    ]


def density_weight_matrix(rows, means_array, grid, sigma_f, shape_config=None):
    matrix = None
    for weight, centers, component_sigma in density_shape_components(
        rows,
        means_array,
        sigma_f,
        shape_config=shape_config,
    ):
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            component = np.exp(-0.5 * ((grid[None, :] - centers[:, None]) / component_sigma) ** 2)
        matrix = component * weight if matrix is None else matrix + component * weight
    return matrix if matrix is not None else np.zeros((len(means_array), len(grid)), dtype=float)


def gaussian_density_f(mean_f, sigma_f, grid_f, shape_config=None, row=None):
    sigma_f = max(0.1, float(sigma_f or 1.0))
    grid = np.asarray([float(value) for value in grid_f], dtype=float)
    weights = density_weight_matrix(
        [row or {}],
        np.asarray([float(mean_f)], dtype=float),
        grid,
        sigma_f,
        shape_config=shape_config,
    )[0]
    density = {float(value): float(weight) for value, weight in zip(grid, weights)}
    shape_cfg = density_shape_config(shape_config)
    payload = continuous_density_payload(density, mean_f=float(mean_f), sigma_f=sigma_f)
    payload["density_shape_id"] = shape_cfg["id"]
    payload["density_shape"] = shape_cfg
    return payload


def predict_density_means(model, imputer, feature_names, rows):
    if not rows:
        return []
    frame = feature_frame(rows, feature_names=feature_names)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Skipping features without any observed values",
            category=UserWarning,
        )
        x_eval = imputer.transform(frame)
    return [float(value) for value in model.predict(x_eval)]


def predict_density_payloads(model, imputer, feature_names, rows, sigma_f, grid_f, shape_config=None):
    means = predict_density_means(model, imputer, feature_names, rows)
    return [
        gaussian_density_f(mean, sigma_f, grid_f, shape_config=shape_config, row=row)
        for mean, row in zip(means, rows or [])
    ]


def density_winning_probability(row, payload):
    unit = record_unit(row)
    final_bucket = row.get("final_bucket")
    if final_bucket is None:
        return None
    return band_probability_from_density(
        payload.get("density_f") or {},
        unit,
        "eq",
        final_bucket,
    )


def evaluate_density_predictions(rows, payloads):
    if not rows:
        return None
    losses = []
    briers = []
    absolute_errors = []
    for row, payload in zip(rows, payloads):
        probability = density_winning_probability(row, payload)
        if probability is None:
            continue
        probability = max(1e-15, min(1.0, float(probability)))
        losses.append(-math.log(probability))
        briers.append(brier(probability, 1.0))
        target_f = native_value_to_f(row.get("final_bucket"), record_unit(row))
        mean_f = (payload or {}).get("mean_f")
        if target_f is not None and mean_f is not None:
            absolute_errors.append(abs(float(mean_f) - float(target_f)))
    if not losses:
        return None
    return {
        "n": len(losses),
        "density_logloss": sum(losses) / len(losses),
        "winning_bucket_brier": sum(briers) / len(briers),
        "mean_absolute_error_f": (
            sum(absolute_errors) / len(absolute_errors)
            if absolute_errors else None
        ),
    }


def density_winner_bucket_score(rows, means, grid_f, sigma_f, shape_config=None):
    """Score winner-bucket probabilities without materializing payload dicts.

    Full replay still uses ``continuous_density_f`` payloads. During training,
    sigma tuning only needs each holdout row's probability assigned to its
    final rounded bucket, so a vectorized Gaussian-grid calculation avoids
    repeatedly building and normalizing thousands of Python dictionaries.
    """
    if not rows or not means:
        return None
    usable = []
    for row, mean_f in zip(rows or [], means or []):
        final_bucket = row.get("final_bucket")
        if final_bucket is None or mean_f is None:
            continue
        try:
            final_bucket = float(final_bucket)
            mean_f = float(mean_f)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(final_bucket) or not math.isfinite(mean_f):
            continue
        unit = record_unit(row)
        low_f = native_value_to_f(final_bucket - 0.5, unit)
        high_f = native_value_to_f(final_bucket + 0.5, unit)
        target_f = native_value_to_f(final_bucket, unit)
        usable.append((row, mean_f, low_f, high_f, target_f))
    if not usable:
        return None

    sigma = max(0.1, float(sigma_f or 1.0))
    grid = np.asarray([float(value) for value in grid_f], dtype=float)
    source_rows = [row[0] for row in usable]
    means_array = np.asarray([row[1] for row in usable], dtype=float)
    lows = np.asarray([row[2] for row in usable], dtype=float)
    highs = np.asarray([row[3] for row in usable], dtype=float)
    targets = np.asarray([row[4] for row in usable], dtype=float)
    weights = density_weight_matrix(source_rows, means_array, grid, sigma, shape_config=shape_config)
    totals = weights.sum(axis=1)
    mask = (grid[None, :] >= lows[:, None]) & (grid[None, :] < highs[:, None])
    bucket_mass = (weights * mask).sum(axis=1)
    probabilities = np.divide(
        bucket_mass,
        totals,
        out=np.zeros_like(bucket_mass, dtype=float),
        where=totals > 0,
    )
    probabilities = np.clip(probabilities, 1e-15, 1.0)
    losses = -np.log(probabilities)
    briers = (probabilities - 1.0) ** 2
    absolute_errors = np.abs(means_array - targets)
    return {
        "n": int(len(probabilities)),
        "density_logloss": float(losses.mean()),
        "winning_bucket_brier": float(briers.mean()),
        "mean_absolute_error_f": float(absolute_errors.mean()),
    }


def density_synthetic_market_band_rows(row, exact_radius=7, tail_stride=1):
    final = round_half_up((row or {}).get("final_bucket"))
    if final is None:
        return []
    unit = record_unit(row)
    centers = [final]
    for column in ("high_so_far", "forecast_high", "current_temp", "live_reading_temp", "climate_normal"):
        value = (row or {}).get(column)
        if value is None:
            continue
        try:
            native_value = f_to_native(float(value), unit)
        except (TypeError, ValueError):
            continue
        center = round_half_up(native_value)
        if center is not None:
            centers.append(center)
    low = min(centers) - int(exact_radius)
    high = max(centers) + int(exact_radius)
    rows = []

    def add(kind, value, value_hi=None):
        outcome = band_outcome(kind, value, final, value_hi=value_hi)
        if outcome is None:
            return
        distance = 0
        if kind == "lte":
            distance = max(0, final - int(value))
        elif kind == "gte":
            distance = max(0, int(value) - final)
        else:
            hi = int(value_hi) if value_hi is not None else int(value)
            distance = 0 if int(value) <= final <= hi else min(abs(final - int(value)), abs(final - hi))
        weight = 1.0
        if outcome:
            weight *= 4.0 if kind == "eq" else 2.0
        if distance == 0:
            weight *= 1.5
        if int((row or {}).get("cutoff_hour") or 0) >= 16:
            weight *= 2.0
        rows.append({
            "kind": kind,
            "value": int(value),
            "value_hi": int(value_hi) if value_hi is not None else None,
            "outcome": int(outcome),
            "unit": unit,
            "settlement_distance": int(distance),
            "_sample_weight": float(weight),
        })

    for value in range(low, high + 1):
        add("eq", value)
    for value in range(low, high):
        add("eq", value, value_hi=value + 1)
    for value in range(low, high + 1, max(1, int(tail_stride))):
        add("lte", value)
        add("gte", value)
    return rows


def canonical_row_to_native_band_record(row):
    """Return a density row with temperature coordinates restored to native units."""
    out = dict(row or {})
    unit = record_unit(row)
    for column in CANONICAL_F_ABSOLUTE_COLUMNS:
        value = out.get(column)
        if value in (None, ""):
            continue
        try:
            out[column] = f_to_native(float(value), unit)
        except (TypeError, ValueError):
            continue
    for column in CANONICAL_F_DELTA_COLUMNS:
        value = out.get(column)
        if value in (None, ""):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        out[column] = value * 5.0 / 9.0 if str(unit).upper() == "C" else value
    out["unit"] = unit
    out["display_unit"] = unit
    return out


def density_market_band_training_rows(row):
    native_record = canonical_row_to_native_band_record(row)
    rows = []
    for band_row in density_synthetic_market_band_rows(row):
        record = band_prediction_record(
            native_record,
            band_row["kind"],
            band_row["value"],
            value_hi=band_row.get("value_hi"),
        )
        record["outcome"] = int(band_row["outcome"])
        record["unit"] = band_row["unit"]
        record["settlement_distance"] = int(band_row["settlement_distance"])
        record["_sample_weight"] = float(band_row.get("_sample_weight", 1.0))
        rows.append(record)
    return rows


def density_projected_market_band_rows_and_probabilities(rows, means, grid_f, sigma_f, shape_config=None):
    band_rows = []
    probabilities = []
    for row, mean_f in zip(rows or [], means or []):
        if mean_f is None:
            continue
        try:
            mean_f = float(mean_f)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mean_f):
            continue
        payload = gaussian_density_f(
            mean_f,
            sigma_f,
            grid_f,
            shape_config=shape_config,
            row=row,
        )
        for band_row in density_market_band_training_rows(row):
            calibrated_payload = apply_continuous_density_calibration(
                payload,
                {},
                floor_bucket=band_row.get("observed_floor_bucket"),
                unit=band_row.get("unit") or record_unit(row),
                resolution_weight=band_row.get("late_lockin_strength", 0.0),
                cutoff_hour=row.get("cutoff_hour"),
            )
            probability = band_probability_from_density(
                calibrated_payload.get("density_f") or {},
                band_row.get("unit") or record_unit(row),
                band_row.get("band_kind"),
                band_row.get("band_value"),
                value_hi=band_row.get("band_value_hi"),
            )
            band_rows.append(band_row)
            probabilities.append(clip_probability(probability))
    return band_rows, probabilities


def density_postprocess_probabilities(rows, probabilities, config):
    from weather.calibration import pooled_band_training as band_training

    config = config or {}
    adjusted = []
    for row, probability in zip(rows or [], probabilities or []):
        probability = clip_probability(probability)
        if config.get("adjacent_calibration_enabled", False):
            probability = band_training.apply_adjacent_calibration(probability, row, config=config)
        if config.get("exact_winner_catchup_enabled", False):
            probability = band_training.apply_exact_winner_catchup(probability, row, config=config)
        if config.get("forecast_relative_calibration_enabled", False):
            probability = apply_forecast_relative_density_calibration(probability, row, config=config)
        adjusted.append(clip_probability(probability))
    if config.get("partition_normalization_enabled", False):
        adjusted = band_training.normalize_band_probabilities_for_rows(
            rows,
            adjusted,
            gamma=float(config.get("partition_normalization_gamma", 1.25)),
        )
    return adjusted


def weighted_market_band_brier(rows, probabilities):
    total_weight = 0.0
    total_loss = 0.0
    for row, probability in zip(rows or [], probabilities or []):
        if row.get("outcome") is None:
            continue
        try:
            outcome = int(row.get("outcome"))
            weight = float(row.get("_sample_weight", 1.0))
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        total_weight += weight
        total_loss += weight * brier(clip_probability(probability), outcome)
    if total_weight <= 0:
        return None
    return total_loss / total_weight


def density_forecast_source_count_bucket(value):
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if value <= 1:
        return "low_count"
    if value == 2:
        return "two_sources"
    return "three_plus_sources"


def density_forecast_disagreement_bucket(value):
    try:
        value = abs(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if value < 1.0:
        return "low_disagreement"
    if value < 2.5:
        return "moderate_disagreement"
    return "high_disagreement"


def density_forecast_pressure_bucket(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if value <= -1.0:
        return "cool_side"
    if value >= 1.0:
        return "warm_side"
    return "near_forecast"


def density_forecast_relative_contexts(row):
    """Serve-time context fallbacks for density projection calibration."""
    from weather.calibration import pooled_band_training as band_training

    market_id = row.get("market_id") or "unknown"
    kind = row.get("band_kind") or "unknown"
    width = band_training._band_width_label(row)
    hour_bucket = band_training.calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    pressure = density_forecast_pressure_bucket(row.get("band_mid_minus_forecast"))
    disagreement = density_forecast_disagreement_bucket(row.get("forecast_disagreement"))
    source_count = density_forecast_source_count_bucket(row.get("forecast_source_count"))
    floor_gap = band_training.calibration_gap_bucket(row.get("band_mid_minus_high_so_far"))
    return [
        (
            f"market={market_id}|hour={hour_bucket}|kind={kind}|width={width}|"
            f"pressure={pressure}|disagreement={disagreement}|source_count={source_count}|"
            f"floor_gap={floor_gap}"
        ),
        (
            f"market={market_id}|hour={hour_bucket}|kind={kind}|"
            f"pressure={pressure}|disagreement={disagreement}|source_count={source_count}"
        ),
        (
            f"market={market_id}|kind={kind}|pressure={pressure}|"
            f"disagreement={disagreement}|source_count={source_count}"
        ),
        f"hour={hour_bucket}|kind={kind}|pressure={pressure}|disagreement={disagreement}",
        f"kind={kind}|pressure={pressure}|disagreement={disagreement}",
        f"pressure={pressure}|disagreement={disagreement}",
        f"pressure={pressure}",
    ]


def _forecast_relative_strength_grid(values=None):
    if values is None:
        values = (1.0, 0.75, 0.50, 0.25, 0.0)
    cleaned = []
    for value in values:
        try:
            strength = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
        if strength not in cleaned:
            cleaned.append(strength)
    return cleaned or [0.0]


def _with_forecast_relative_strength(calibration, strength):
    copy = dict(calibration or {})
    copy["strength"] = max(0.0, min(1.0, float(strength)))
    return copy


def forecast_relative_density_factor(row, config=None):
    config = config or {}
    calibration = config.get("forecast_relative_calibration") or config
    contexts = calibration.get("contexts") or {}
    if not contexts:
        return 1.0
    for context in density_forecast_relative_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            return float(entry.get("factor", 1.0))
        return float(entry)
    return 1.0


def apply_forecast_relative_density_calibration(probability, row, config=None):
    config = config or {}
    calibration = config.get("forecast_relative_calibration") or config
    factor = forecast_relative_density_factor(row, config={"forecast_relative_calibration": calibration})
    strength = max(0.0, min(1.0, float(calibration.get("strength", 1.0))))
    if factor == 1.0 or strength <= 0.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * (float(factor) ** strength))


def select_forecast_relative_density_strength(rows, probabilities, calibration, strength_grid=None):
    rows = list(rows or [])
    probabilities = [clip_probability(probability) for probability in (probabilities or [])]
    grid = _forecast_relative_strength_grid(strength_grid)
    baseline_brier = weighted_market_band_brier(rows, probabilities)
    candidates = []
    for strength in grid:
        adjusted = [
            apply_forecast_relative_density_calibration(
                probability,
                row,
                config={
                    "forecast_relative_calibration": _with_forecast_relative_strength(
                        calibration,
                        strength,
                    ),
                },
            )
            for row, probability in zip(rows, probabilities)
        ]
        candidates.append({
            "strength": float(strength),
            "market_band_brier": weighted_market_band_brier(rows, adjusted),
        })
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            0 if float(row.get("strength", 0.0)) == 0.0 else 1,
        ),
    )
    selected = candidates[0] if candidates else {"strength": 0.0, "market_band_brier": baseline_brier}
    return {
        "baseline_market_band_brier": baseline_brier,
        "selected_strength": float(selected.get("strength", 0.0)),
        "selected_market_band_brier": selected.get("market_band_brier"),
        "candidates": candidates,
    }


def fit_forecast_relative_density_calibration(
    rows,
    probabilities,
    min_rows=120,
    prior_rows=240.0,
    factor_min=0.50,
    factor_max=1.60,
):
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows or [], probabilities or []):
        try:
            probability = clip_probability(probability)
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in density_forecast_relative_contexts(row):
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
        "version": "density_forecast_relative_v0.1",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "strength": 1.0,
        "context_count": len(contexts),
        "contexts": contexts,
    }
    diagnostics = select_forecast_relative_density_strength(rows, probabilities, calibration)
    calibration["strength"] = diagnostics["selected_strength"]
    calibration["strength_diagnostics"] = diagnostics
    return calibration


def fit_density_market_band_postprocess(rows, probabilities, min_improvement=0.003):
    from weather.calibration import pooled_band_training as band_training

    rows = list(rows or [])
    probabilities = [clip_probability(probability) for probability in (probabilities or [])]
    adjacent = band_training.fit_adjacent_calibration(rows, probabilities)
    exact = band_training.fit_exact_winner_catchup(
        rows,
        probabilities,
        factor_min=1.0,
        guardrail_rows=rows,
        guardrail_probabilities=probabilities,
    )
    forecast_relative = fit_forecast_relative_density_calibration(rows, probabilities)
    base_config = {
        "schema_version": "density_market_band_postprocess_v0.2",
        "adjacent_calibration": adjacent,
        "exact_winner_catchup": exact,
        "forecast_relative_calibration": forecast_relative,
        "partition_normalization_gamma": 1.25,
        "calibration_rows": len(rows),
    }
    candidates = []
    policy_grid = [
        ("disabled", False, False, False, False),
        ("forecast_relative", False, False, True, False),
        ("adjacent_only", True, False, False, False),
        ("exact_only", False, True, False, False),
        ("adjacent_exact", True, True, False, False),
        ("forecast_adjacent", True, False, True, False),
        ("forecast_exact", False, True, True, False),
        ("forecast_adjacent_exact", True, True, True, False),
        ("forecast_normalized", False, False, True, True),
        ("adjacent_normalized", True, False, False, True),
        ("exact_normalized", False, True, False, True),
        ("adjacent_exact_normalized", True, True, False, True),
        ("forecast_adjacent_exact_normalized", True, True, True, True),
    ]
    for policy_id, adjacent_enabled, exact_enabled, forecast_enabled, normalized in policy_grid:
        config = {
            **base_config,
            "enabled": policy_id != "disabled",
            "policy_id": policy_id,
            "adjacent_calibration_enabled": bool(adjacent_enabled),
            "exact_winner_catchup_enabled": bool(exact_enabled),
            "forecast_relative_calibration_enabled": bool(forecast_enabled),
            "partition_normalization_enabled": bool(normalized),
        }
        candidate_probabilities = density_postprocess_probabilities(rows, probabilities, config)
        candidates.append({
            "policy_id": policy_id,
            "enabled": policy_id != "disabled",
            "adjacent_calibration_enabled": bool(adjacent_enabled),
            "exact_winner_catchup_enabled": bool(exact_enabled),
            "forecast_relative_calibration_enabled": bool(forecast_enabled),
            "partition_normalization_enabled": bool(normalized),
            "market_band_brier": weighted_market_band_brier(rows, candidate_probabilities),
        })
    baseline = next(row for row in candidates if row["policy_id"] == "disabled")
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            0 if row["policy_id"] == "disabled" else 1,
        ),
    )
    best = candidates[0]
    baseline_brier = baseline.get("market_band_brier")
    best_brier = best.get("market_band_brier")
    if (
        baseline_brier is None
        or best_brier is None
        or best["policy_id"] == "disabled"
        or (float(baseline_brier) - float(best_brier)) < float(min_improvement)
    ):
        selected = baseline
    else:
        selected = best
    return {
        **base_config,
        "enabled": bool(selected.get("enabled")),
        "policy_id": selected.get("policy_id"),
        "adjacent_calibration_enabled": bool(selected.get("adjacent_calibration_enabled")),
        "exact_winner_catchup_enabled": bool(selected.get("exact_winner_catchup_enabled")),
        "forecast_relative_calibration_enabled": bool(selected.get("forecast_relative_calibration_enabled")),
        "partition_normalization_enabled": bool(selected.get("partition_normalization_enabled")),
        "selection": {
            "baseline_market_band_brier": baseline_brier,
            "selected_market_band_brier": selected.get("market_band_brier"),
            "selected_policy_id": selected.get("policy_id"),
            "min_improvement": float(min_improvement),
            "candidates": candidates,
        },
    }


def density_market_band_score(rows, means, grid_f, sigma_f, shape_config=None):
    """Score Gaussian density width on replay-shaped native market bands."""
    if not rows or not means:
        return None
    usable = []
    for row, mean_f in zip(rows or [], means or []):
        if mean_f is None:
            continue
        try:
            mean_f = float(mean_f)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mean_f):
            continue
        for band_row in density_synthetic_market_band_rows(row):
            low_native, high_native = bucket_interval_native(
                band_row["kind"],
                band_row["value"],
                band_row.get("value_hi"),
            )
            low_f, high_f = native_interval_to_f(
                low_native,
                high_native,
                band_row["unit"],
            )
            usable.append((
                row,
                mean_f,
                float("-inf") if low_f is None else float(low_f),
                float("inf") if high_f is None else float(high_f),
                float(band_row["outcome"]),
                float(band_row.get("_sample_weight", 1.0)),
            ))
    if not usable:
        return None

    sigma = max(0.1, float(sigma_f or 1.0))
    grid = np.asarray([float(value) for value in grid_f], dtype=float)
    source_rows = [row[0] for row in usable]
    means_array = np.asarray([row[1] for row in usable], dtype=float)
    lows = np.asarray([row[2] for row in usable], dtype=float)
    highs = np.asarray([row[3] for row in usable], dtype=float)
    outcomes = np.asarray([row[4] for row in usable], dtype=float)
    sample_weights = np.asarray([row[5] for row in usable], dtype=float)
    weights = density_weight_matrix(source_rows, means_array, grid, sigma, shape_config=shape_config)
    totals = weights.sum(axis=1)
    mask = (grid[None, :] >= lows[:, None]) & (grid[None, :] < highs[:, None])
    bucket_mass = (weights * mask).sum(axis=1)
    probabilities = np.divide(
        bucket_mass,
        totals,
        out=np.zeros_like(bucket_mass, dtype=float),
        where=totals > 0,
    )
    probabilities = np.clip(probabilities, 1e-15, 1.0 - 1e-15)
    briers = (probabilities - outcomes) ** 2
    losses = -(
        outcomes * np.log(probabilities)
        + (1.0 - outcomes) * np.log(1.0 - probabilities)
    )
    weight_sum = float(sample_weights.sum())
    if weight_sum <= 0:
        sample_weights = np.ones_like(sample_weights)
        weight_sum = float(sample_weights.sum())
    return {
        "market_band_rows": int(len(probabilities)),
        "market_band_brier": float(np.average(briers, weights=sample_weights)),
        "market_band_logloss": float(np.average(losses, weights=sample_weights)),
        "market_band_positive_rate": float(np.average(outcomes, weights=sample_weights)),
    }


def density_sigma_candidates(base_sigma_f, scales=DENSITY_SIGMA_TUNING_SCALES, floor=0.35, cap=10.0):
    base = residual_sigma_f([float(base_sigma_f or 3.0)], floor=floor, cap=cap)
    candidates = {base}
    for scale in scales or ():
        try:
            value = float(base) * float(scale)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            candidates.add(max(float(floor), min(float(cap), value)))
    return sorted(round(value, 6) for value in candidates)


def evaluate_density_sigma(rows, means, grid_f, sigma_f, shape_config=None):
    winner_score = density_winner_bucket_score(
        rows,
        means,
        grid_f,
        sigma_f,
        shape_config=shape_config,
    ) or {}
    band_score = density_market_band_score(
        rows,
        means,
        grid_f,
        sigma_f,
        shape_config=shape_config,
    ) or {}
    if not winner_score and not band_score:
        return None
    return {**winner_score, **band_score}


def tune_density_sigma_f(rows, means, grid_f, base_sigma_f):
    """Choose density width against holdout market-band Brier.

    The replay gate scores projected market-band probabilities, not raw
    temperature RMSE or winner-bucket probability alone. A Gaussian width that
    is optimal for the true bucket can still overprice nearby losing bands, so
    the v0.4 density artifact selects sigma from a small holdout grid using
    synthetic native market bands that mirror replay's eq/lte/gte scoring.
    """
    if not rows or not means:
        return None
    candidates = []
    for sigma_f in density_sigma_candidates(base_sigma_f):
        score = evaluate_density_sigma(rows, means, grid_f, sigma_f)
        if not score:
            continue
        candidates.append({
            "sigma_f": sigma_f,
            "density_logloss": score.get("density_logloss"),
            "winning_bucket_brier": score.get("winning_bucket_brier"),
            "mean_absolute_error_f": score.get("mean_absolute_error_f"),
            "market_band_rows": score.get("market_band_rows"),
            "market_band_brier": score.get("market_band_brier"),
            "market_band_logloss": score.get("market_band_logloss"),
            "market_band_positive_rate": score.get("market_band_positive_rate"),
            "n": score.get("n"),
        })
    if not candidates:
        return None
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            float(row.get("winning_bucket_brier", float("inf"))),
            float(row.get("density_logloss", float("inf"))),
            abs(float(row.get("sigma_f")) - float(base_sigma_f or row.get("sigma_f"))),
        ),
    )
    return {
        "selected_sigma_f": candidates[0]["sigma_f"],
        "selected_score": candidates[0],
        "base_sigma_f": float(base_sigma_f or candidates[0]["sigma_f"]),
        "candidates": candidates,
    }


def tune_density_shape_policy(rows, means, grid_f, base_sigma_f):
    """Choose sigma and density shape against holdout market-band Brier."""
    if not rows or not means:
        return None
    candidates = []
    for sigma_f in density_sigma_candidates(base_sigma_f):
        for shape_config in DENSITY_SHAPE_TUNING_CANDIDATES:
            shape_cfg = density_shape_config(shape_config)
            score = evaluate_density_sigma(
                rows,
                means,
                grid_f,
                sigma_f,
                shape_config=shape_cfg,
            )
            if not score:
                continue
            candidates.append({
                "sigma_f": sigma_f,
                "density_shape_id": shape_cfg["id"],
                "density_shape": shape_cfg,
                "density_logloss": score.get("density_logloss"),
                "winning_bucket_brier": score.get("winning_bucket_brier"),
                "mean_absolute_error_f": score.get("mean_absolute_error_f"),
                "market_band_rows": score.get("market_band_rows"),
                "market_band_brier": score.get("market_band_brier"),
                "market_band_logloss": score.get("market_band_logloss"),
                "market_band_positive_rate": score.get("market_band_positive_rate"),
                "n": score.get("n"),
            })
    if not candidates:
        return None
    base_shape_id = density_shape_id(DENSITY_DEFAULT_SHAPE)
    candidates = sorted(
        candidates,
        key=lambda row: (
            float(row.get("market_band_brier", float("inf"))),
            float(row.get("winning_bucket_brier", float("inf"))),
            float(row.get("density_logloss", float("inf"))),
            0 if row.get("density_shape_id") == base_shape_id else 1,
            abs(float(row.get("sigma_f")) - float(base_sigma_f or row.get("sigma_f"))),
        ),
    )
    return {
        "selected_sigma_f": candidates[0]["sigma_f"],
        "selected_density_shape_id": candidates[0]["density_shape_id"],
        "selected_density_shape": candidates[0]["density_shape"],
        "selected_score": candidates[0],
        "base_sigma_f": float(base_sigma_f or candidates[0]["sigma_f"]),
        "base_density_shape_id": base_shape_id,
        "candidate_shape_ids": [density_shape_id(row) for row in DENSITY_SHAPE_TUNING_CANDIDATES],
        "candidates": candidates,
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
