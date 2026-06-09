import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.optimize import minimize


sys.path.insert(0, os.path.abspath("src"))
from toronto_model import INTRADAY_CUTOFF_HOURS, TorontoHighTempModel


WEIGHT_COMPONENTS = (
    "climatology",
    "intraday_high",
    "current_bucket",
    "wind_regime",
    "cloud_regime",
    "forecast_cap",
)

MIN_INTRADAY_MATCHES = 8
MIN_REGIME_MATCHES = 20
MARKET_BIN_MIN = 19
MARKET_BIN_MAX = 29


def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))


def smoothed_dist(buckets, support, alpha=0.10):
    support = sorted(set(int(bucket) for bucket in support))
    counts = Counter(int(bucket) for bucket in buckets if bucket is not None)
    denominator = len(buckets) + alpha * len(support)
    if denominator <= 0:
        return uniform_dist(support)
    return {bucket: (counts.get(bucket, 0) + alpha) / denominator for bucket in support}


def uniform_dist(support):
    support = sorted(set(int(bucket) for bucket in support))
    if not support:
        return {}
    return {bucket: 1.0 / len(support) for bucket in support}


def normalize_dist(dist, support=None):
    keys = sorted(set(int(key) for key in (support or dist.keys())))
    cleaned = {key: max(0.0, float(dist.get(key, dist.get(str(key), 0.0)))) for key in keys}
    total = sum(cleaned.values())
    if total <= 0:
        return uniform_dist(keys)
    return {key: value / total for key, value in cleaned.items()}


def weighted_component_dist(components, weights, support):
    available = {
        name: normalize_dist(dist, support)
        for name, dist in components.items()
        if dist
    }
    if not available:
        return uniform_dist(support)

    raw_weights = {
        name: max(0.0, float(weights.get(name, 0.0)))
        for name in available
    }
    total_weight = sum(raw_weights.values())
    if total_weight <= 0:
        raw_weights = {name: 1.0 for name in available}
        total_weight = float(len(raw_weights))

    combined = {bucket: 0.0 for bucket in support}
    for name, dist in available.items():
        component_weight = raw_weights[name] / total_weight
        for bucket in support:
            combined[bucket] += component_weight * dist.get(bucket, 0.0)
    return normalize_dist(combined, support)


def cap_prior_distribution(support, cap_bucket, floor_bucket=None, above_decay=0.28):
    if cap_bucket is None:
        return None
    cap_bucket = int(cap_bucket)
    floor_bucket = int(floor_bucket) if floor_bucket is not None else None
    scores = {}
    for bucket in support:
        bucket = int(bucket)
        if floor_bucket is not None and bucket < floor_bucket:
            scores[bucket] = 0.02 ** max(1, floor_bucket - bucket)
        elif bucket <= cap_bucket:
            distance = abs(bucket - cap_bucket)
            scores[bucket] = 1.0 / (1.0 + distance)
        else:
            scores[bucket] = above_decay ** (bucket - cap_bucket)
    return normalize_dist(scores, support)


def market_group(bucket):
    bucket = int(bucket)
    if bucket <= MARKET_BIN_MIN:
        return f"lte_{MARKET_BIN_MIN}"
    if bucket >= MARKET_BIN_MAX:
        return f"gte_{MARKET_BIN_MAX}"
    return f"eq_{bucket}"


def market_group_distribution(prob_dist):
    grouped = defaultdict(float)
    for bucket, probability in prob_dist.items():
        grouped[market_group(bucket)] += float(probability)
    return dict(grouped)


def log_loss(prob_dict, actual_bucket):
    p = prob_dict.get(int(actual_bucket), 0.0)
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -math.log(p)


def brier_score(prob_dict, actual_bucket):
    return sum(
        (probability - (1.0 if int(bucket) == int(actual_bucket) else 0.0)) ** 2
        for bucket, probability in prob_dict.items()
    )


def group_log_loss(prob_dict, actual_bucket):
    grouped = market_group_distribution(prob_dict)
    p = grouped.get(market_group(actual_bucket), 0.0)
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -math.log(p)


def group_brier_score(prob_dict, actual_bucket):
    grouped = market_group_distribution(prob_dict)
    actual_group = market_group(actual_bucket)
    all_groups = {market_group(bucket) for bucket in prob_dict}
    return sum(
        (grouped.get(group, 0.0) - (1.0 if group == actual_group else 0.0)) ** 2
        for group in all_groups
    )


def top_bucket_accuracy(prob_dict, actual_bucket):
    if not prob_dict:
        return 0.0
    predicted = max(prob_dict, key=prob_dict.get)
    return 1.0 if int(predicted) == int(actual_bucket) else 0.0


def bucket_group_accuracy(prob_dict, actual_bucket):
    if not prob_dict:
        return 0.0
    grouped = market_group_distribution(prob_dict)
    predicted_group = max(grouped, key=grouped.get)
    return 1.0 if predicted_group == market_group(actual_bucket) else 0.0


def baseline_intraday_base(hour):
    if hour >= 17:
        return 0.82
    if hour >= 15:
        return 0.70
    if hour >= 13:
        return 0.58
    if hour >= 12:
        return 0.48
    return 0.36


def baseline_component_weights(hour):
    return {
        "climatology": 1.0,
        "intraday_high": baseline_intraday_base(hour),
        "current_bucket": 0.0,
        "wind_regime": 0.14,
        "cloud_regime": 0.12,
        "forecast_cap": 0.0,
    }


def extract_hourly_records(model):
    cache = model.historical_target_cache()
    daily = cache["daily"]
    by_date = cache["by_date"]

    records_by_hour = defaultdict(list)
    for local_date in sorted(daily):
        rows = by_date.get(local_date, [])
        if not rows:
            continue
        final_bucket = int(daily[local_date]["bucket"])
        for hour in INTRADAY_CUTOFF_HOURS:
            cutoff = hour * 60
            obs_before = [
                row for row in rows
                if row.get("minute_of_day") is not None
                and row["minute_of_day"] <= cutoff
            ]
            if not obs_before:
                continue
            temp_rows = [row for row in obs_before if row.get("temp_c") is not None]
            if not temp_rows:
                continue
            high_so_far = max(row["temp_c"] for row in temp_rows)
            current_obs = obs_before[-1]
            current_temp = current_obs.get("temp_c")
            records_by_hour[hour].append(
                {
                    "date": local_date,
                    "final_bucket": final_bucket,
                    "high_so_far": high_so_far,
                    "observed_bucket": round_half_up(high_so_far),
                    "current_temp": current_temp,
                    "current_bucket": round_half_up(current_temp),
                    "wind_group": model.wind_group(current_obs.get("wind")),
                    "cloud_group": model.cloud_group(
                        current_obs.get("condition"),
                        current_obs.get("clouds"),
                    ),
                }
            )
    return records_by_hour, cache["bucket_space"]


def matching_dist(records, support, predicate, min_matches, alpha=0.10):
    matches = [record["final_bucket"] for record in records if predicate(record)]
    if len(matches) < min_matches:
        return None, len(matches)
    return smoothed_dist(matches, support, alpha=alpha), len(matches)


def inferred_cap_bucket(train_records, target):
    observed = target.get("observed_bucket")
    if observed is None:
        return None
    same_high = [
        record for record in train_records
        if record.get("observed_bucket") == observed
    ]
    candidates = same_high if len(same_high) >= MIN_INTRADAY_MATCHES else train_records
    if not candidates:
        return observed
    remaining_rises = [
        max(0, int(record["final_bucket"]) - int(record.get("observed_bucket") or record["final_bucket"]))
        for record in candidates
    ]
    if not remaining_rises:
        return observed
    q90_remaining = int(math.ceil(float(np.quantile(remaining_rises, 0.90))))
    return max(int(observed), int(observed) + q90_remaining)


def build_components(train_records, target, support):
    p_clim = smoothed_dist([record["final_bucket"] for record in train_records], support, alpha=0.10)

    p_intraday, n_intraday = matching_dist(
        train_records,
        support,
        lambda record: record.get("observed_bucket") == target.get("observed_bucket"),
        MIN_INTRADAY_MATCHES,
        alpha=0.05,
    )
    p_current, n_current = matching_dist(
        train_records,
        support,
        lambda record: record.get("current_bucket") == target.get("current_bucket"),
        MIN_INTRADAY_MATCHES,
        alpha=0.05,
    )
    p_wind, n_wind = matching_dist(
        train_records,
        support,
        lambda record: record.get("wind_group") and record.get("wind_group") == target.get("wind_group"),
        MIN_REGIME_MATCHES,
        alpha=0.10,
    )
    p_cloud, n_cloud = matching_dist(
        train_records,
        support,
        lambda record: record.get("cloud_group") and record.get("cloud_group") == target.get("cloud_group"),
        MIN_REGIME_MATCHES,
        alpha=0.10,
    )
    cap_bucket = inferred_cap_bucket(train_records, target)
    p_cap = cap_prior_distribution(
        support,
        cap_bucket,
        floor_bucket=target.get("observed_bucket"),
    )

    return {
        "components": {
            "climatology": p_clim,
            "intraday_high": p_intraday,
            "current_bucket": p_current,
            "wind_regime": p_wind,
            "cloud_regime": p_cloud,
            "forecast_cap": p_cap,
        },
        "actual": int(target["final_bucket"]),
        "counts": {
            "intraday_high": n_intraday,
            "current_bucket": n_current,
            "wind_regime": n_wind,
            "cloud_regime": n_cloud,
            "forecast_cap_bucket": cap_bucket,
        },
    }


def build_leave_one_year_evaluations(records_by_hour, support):
    evaluations = {}
    for hour, records in records_by_hour.items():
        hour_evals = []
        for target in records:
            train_records = [
                record for record in records
                if record["date"].year != target["date"].year
            ]
            if not train_records:
                continue
            hour_evals.append(build_components(train_records, target, support))
        evaluations[hour] = hour_evals
    return evaluations


def params_to_weights(params):
    return {
        component: float(value)
        for component, value in zip(WEIGHT_COMPONENTS, params)
    }


def predict_eval(item, support, weights):
    return weighted_component_dist(item["components"], weights, support)


def average_metrics(evals, support, weights):
    exact_log_losses = []
    exact_briers = []
    exact_accuracies = []
    group_log_losses = []
    group_briers = []
    group_accuracies = []

    for item in evals:
        actual = item["actual"]
        probs = predict_eval(item, support, weights)
        exact_log_losses.append(log_loss(probs, actual))
        exact_briers.append(brier_score(probs, actual))
        exact_accuracies.append(top_bucket_accuracy(probs, actual))
        group_log_losses.append(group_log_loss(probs, actual))
        group_briers.append(group_brier_score(probs, actual))
        group_accuracies.append(bucket_group_accuracy(probs, actual))

    return {
        "exact_log_loss": float(np.mean(exact_log_losses)),
        "exact_brier": float(np.mean(exact_briers)),
        "top_bucket_accuracy": float(np.mean(exact_accuracies)),
        "market_group_log_loss": float(np.mean(group_log_losses)),
        "market_group_brier": float(np.mean(group_briers)),
        "bucket_group_accuracy": float(np.mean(group_accuracies)),
    }


def optimize_weights(evals, support, initial_weights):
    initial = np.array([initial_weights[component] for component in WEIGHT_COMPONENTS], dtype=float)
    bounds = [(0.0, 2.0) for _ in WEIGHT_COMPONENTS]

    def loss_func(params):
        weights = params_to_weights(params)
        return average_metrics(evals, support, weights)["exact_log_loss"]

    result = minimize(loss_func, initial, method="L-BFGS-B", bounds=bounds)
    return params_to_weights(result.x), result


def component_availability(evals):
    availability = {component: 0 for component in WEIGHT_COMPONENTS}
    for item in evals:
        for component in WEIGHT_COMPONENTS:
            if item["components"].get(component):
                availability[component] += 1
    total = len(evals) or 1
    return {
        component: {
            "count": int(count),
            "rate": float(count / total),
        }
        for component, count in availability.items()
    }


def cap_proxy_summary(evals):
    values = [
        item["counts"].get("forecast_cap_bucket")
        for item in evals
        if item["counts"].get("forecast_cap_bucket") is not None
    ]
    if not values:
        return {}
    return {
        "median_cap_bucket": float(np.median(values)),
        "min_cap_bucket": int(min(values)),
        "max_cap_bucket": int(max(values)),
    }


def write_report(report_path, calibrated, support):
    lines = [
        "# Intraday Calibration Report",
        "",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Design",
        "",
        (
            "The empirical intraday model is calibrated as a per-cutoff-hour "
            "weighted ensemble of six probability components."
        ),
        "",
        "- `climatology`: base target-season distribution.",
        "- `intraday_high`: final-bucket distribution conditioned on high so far.",
        "- `current_bucket`: final-bucket distribution conditioned on latest/current bucket.",
        "- `wind_regime`: final-bucket distribution conditioned on live wind group.",
        "- `cloud_regime`: final-bucket distribution conditioned on live cloud group.",
        "- `forecast_cap`: non-leaky forecast-cap proxy from training data; live use maps this weight onto the available forecast cap.",
        "",
        (
            "Validation is leave-one-year-out so every target day is scored "
            "against years other than its own."
        ),
        "",
        "## Exact Bucket Metrics",
        "",
        "| Cutoff | Days | Base Log Loss | Opt Log Loss | Base Brier | Opt Brier | Base Top Acc | Opt Top Acc |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for hour in sorted(calibrated["hours"], key=lambda value: int(value)):
        item = calibrated["hours"][hour]
        base = item["metrics"]["baseline"]
        opt = item["metrics"]["optimized"]
        lines.append(
            f"| {int(hour):02d}:00 | {item['n_days']} | "
            f"{base['exact_log_loss']:.4f} | {opt['exact_log_loss']:.4f} | "
            f"{base['exact_brier']:.4f} | {opt['exact_brier']:.4f} | "
            f"{base['top_bucket_accuracy']*100:.1f}% | {opt['top_bucket_accuracy']*100:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Market-Bin Metrics",
            "",
            (
                "Market-bin metrics score the cumulative edge cases separately: "
                f"`{MARKET_BIN_MIN} C or below`, exact buckets between them, "
                f"and `{MARKET_BIN_MAX} C or higher`."
            ),
            "",
            "| Cutoff | Base Group Log Loss | Opt Group Log Loss | Base Group Brier | Opt Group Brier | Base Group Acc | Opt Group Acc |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for hour in sorted(calibrated["hours"], key=lambda value: int(value)):
        item = calibrated["hours"][hour]
        base = item["metrics"]["baseline"]
        opt = item["metrics"]["optimized"]
        lines.append(
            f"| {int(hour):02d}:00 | "
            f"{base['market_group_log_loss']:.4f} | {opt['market_group_log_loss']:.4f} | "
            f"{base['market_group_brier']:.4f} | {opt['market_group_brier']:.4f} | "
            f"{base['bucket_group_accuracy']*100:.1f}% | {opt['bucket_group_accuracy']*100:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Learned Weights",
            "",
            "| Cutoff | Climatology | Intraday High | Current Bucket | Wind | Cloud | Forecast Cap |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for hour in sorted(calibrated["hours"], key=lambda value: int(value)):
        weights = calibrated["hours"][hour]["weights"]
        normalized = normalized_weight_map(weights)
        lines.append(
            f"| {int(hour):02d}:00 | "
            f"{normalized['climatology']:.3f} | {normalized['intraday_high']:.3f} | "
            f"{normalized['current_bucket']:.3f} | {normalized['wind_regime']:.3f} | "
            f"{normalized['cloud_regime']:.3f} | {normalized['forecast_cap']:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Component Availability",
            "",
            "| Cutoff | Intraday High | Current Bucket | Wind | Cloud | Forecast Cap |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for hour in sorted(calibrated["hours"], key=lambda value: int(value)):
        availability = calibrated["hours"][hour]["component_availability"]
        lines.append(
            f"| {int(hour):02d}:00 | "
            f"{availability['intraday_high']['rate']*100:.1f}% | "
            f"{availability['current_bucket']['rate']*100:.1f}% | "
            f"{availability['wind_regime']['rate']*100:.1f}% | "
            f"{availability['cloud_regime']['rate']*100:.1f}% | "
            f"{availability['forecast_cap']['rate']*100:.1f}% |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalized_weight_map(weights):
    total = sum(max(0.0, float(weights.get(component, 0.0))) for component in WEIGHT_COMPONENTS)
    if total <= 0:
        return {component: 1.0 / len(WEIGHT_COMPONENTS) for component in WEIGHT_COMPONENTS}
    return {
        component: max(0.0, float(weights.get(component, 0.0))) / total
        for component in WEIGHT_COMPONENTS
    }


def calibrate(model):
    print(f"Loading historical data cache for market '{model.spec.id}'...")
    records_by_hour, support = extract_hourly_records(model)
    total_records = sum(len(records) for records in records_by_hour.values())
    print(f"Loaded {total_records} hour-day rows.")
    
    if total_records == 0:
        print("Not enough data to calibrate. Returning empty calibration.")
        return None
        
    print(f"Unique target-season days: {len({record['date'] for records in records_by_hour.values() for record in records})}")

    print("Building leave-one-year-out component evaluations...")
    evaluations = build_leave_one_year_evaluations(records_by_hour, support)

    calibrated = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "support": [int(bucket) for bucket in support],
            "components": list(WEIGHT_COMPONENTS),
            "validation": "leave-one-year-out",
            "market_groups": {
                "lower_cumulative": f"lte_{MARKET_BIN_MIN}",
                "upper_cumulative": f"gte_{MARKET_BIN_MAX}",
            },
            "note": (
                "forecast_cap is calibrated with a non-leaky historical cap proxy "
                "until a multi-day forecast archive is available."
            ),
        },
        "hours": {},
    }

    for hour in INTRADAY_CUTOFF_HOURS:
        evals = evaluations.get(hour, [])
        if not evals:
            continue
        baseline_weights = baseline_component_weights(hour)
        optimized_weights, result = optimize_weights(evals, support, baseline_weights)
        baseline_metrics = average_metrics(evals, support, baseline_weights)
        optimized_metrics = average_metrics(evals, support, optimized_weights)

        print(
            f"Hour {hour:02d}:00 | exact log loss "
            f"{baseline_metrics['exact_log_loss']:.4f} -> {optimized_metrics['exact_log_loss']:.4f}; "
            f"group log loss {baseline_metrics['market_group_log_loss']:.4f} -> {optimized_metrics['market_group_log_loss']:.4f}"
        )

        calibrated["hours"][str(hour)] = {
            "n_days": len(evals),
            "weights": optimized_weights,
            "normalized_weights": normalized_weight_map(optimized_weights),
            "baseline_weights": baseline_weights,
            "metrics": {
                "baseline": baseline_metrics,
                "optimized": optimized_metrics,
            },
            "component_availability": component_availability(evals),
            "forecast_cap_proxy": cap_proxy_summary(evals),
            "optimizer": {
                "success": bool(result.success),
                "message": str(result.message),
                "objective": float(result.fun),
            },
        }
    return calibrated


def build_parser():
    parser = argparse.ArgumentParser(
        description="Calibrate empirical intraday model weights by cutoff hour."
    )
    parser.add_argument(
        "--market",
        default="toronto",
        help="The market ID to train the model for.",
    )
    parser.add_argument(
        "--weights-path",
        default=None,
        help="Where to write learned weights JSON (defaults based on market).",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Where to write Markdown calibration report (defaults based on market).",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    model = TorontoHighTempModel(market_id=args.market)
    calibrated = calibrate(model)

    if not calibrated:
        print(f"Skipping calibration output for market {args.market} due to missing data.")
        return 0

    weights_path = Path(args.weights_path) if args.weights_path else Path("src") / f"calibrated_weights{model.spec.artifact_suffix}.json"
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    weights_path.write_text(json.dumps(calibrated, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Saved calibrated weights to {weights_path}")

    report_path = Path(args.report_path) if args.report_path else Path("data") / "wunderground" / model.spec.icao.lower() / "analysis" / "calibration_report.md"
    write_report(report_path, calibrated, calibrated["metadata"]["support"])
    print(f"Saved calibration report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
