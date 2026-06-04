"""Probability calibration for Toronto high-temperature market buckets.

The live model produces an exact-bucket distribution. Polymarket trades a set
of binary market bins (exact buckets plus low/high tails). This module keeps
those two calibration layers separate:

* exact distribution calibration: temperature-scale the exact distribution while
  preserving any WU-history hard floor;
* market-bin calibration: calibrate each binary market probability with a
  learned prior-shrink layer, using context summaries for diagnostics and
  fallbacks.

The training CLI compares deployable no-market methods against market-informed
baselines, then writes a lightweight JSON artifact consumed by live inference.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (  # noqa: E402
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    binary_log_loss,
    brier,
    parse_snapshot_time,
    safe_float,
    settlement_for_tape,
    backtest_tape,
)
from market_config import date_from_event_slug  # noqa: E402
from settled_days import discover_settled_folders  # noqa: E402


DEFAULT_ARTIFACT_PATH = Path("src") / "probability_calibration.json"
DEFAULT_REPORT_PATH = Path("data") / "backtest" / "probability_calibration_report.md"
EPSILON = 1e-6
MAX_EXACT_DEPLOYMENT_TEMPERATURE = 1.5


def clip_probability(value, epsilon=EPSILON):
    if value is None:
        return None
    return max(epsilon, min(1.0 - epsilon, float(value)))


def logit(value):
    value = clip_probability(value)
    return math.log(value / (1.0 - value))


def sigmoid(value):
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def round_half_up(value):
    if value is None:
        return None
    try:
        return int(math.floor(float(value) + 0.5))
    except (TypeError, ValueError):
        return None


def normalize(scores):
    cleaned = {
        int(bucket): max(0.0, float(probability))
        for bucket, probability in scores.items()
        if probability is not None
    }
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {bucket: value / total for bucket, value in sorted(cleaned.items())}


def floor_distance_bucket(bin_value, floor_bucket):
    if bin_value is None or floor_bucket is None:
        return "unknown"
    diff = int(bin_value) - int(floor_bucket)
    if diff <= -1:
        return "below_floor"
    if diff == 0:
        return "at_floor"
    if diff == 1:
        return "one_above"
    if diff == 2:
        return "two_above"
    return "three_plus_above"


def hard_bin_probability(bin_kind, bin_value, floor_bucket):
    """Return a hard probability when WU history has already settled that bin.

    A WU printed floor makes `gte` at/below the floor guaranteed YES and makes
    exact/lte bins below the floor guaranteed NO. Exact at the floor is not hard:
    the final high can still rise later.
    """
    if floor_bucket is None or bin_value is None:
        return None
    bin_value = int(bin_value)
    floor_bucket = int(floor_bucket)
    if bin_kind == "gte" and floor_bucket >= bin_value:
        return 1.0
    if bin_kind == "lte" and floor_bucket > bin_value:
        return 0.0
    if bin_kind not in {"gte", "lte"} and bin_value < floor_bucket:
        return 0.0
    return None


def observed_support_blocks_floor_lift(bin_kind, bin_value, floor_bucket, context):
    """True when live observed support has already moved above an exact bin."""
    if bin_kind != "eq":
        return False
    value_bucket = round_half_up(bin_value)
    support_bucket = round_half_up((context or {}).get("observed_support_bucket"))
    if value_bucket is None or support_bucket is None:
        return False
    floor_bucket = round_half_up(floor_bucket)
    if floor_bucket is not None and value_bucket < floor_bucket:
        return True
    return value_bucket < support_bucket


def context_keys(bin_kind, cutoff_hour, distance_bucket):
    kind = bin_kind or "eq"
    hour = str(cutoff_hour) if cutoff_hour is not None else "unknown"
    distance = distance_bucket or "unknown"
    return [
        f"kind={kind}|hour={hour}|distance={distance}",
        f"kind={kind}|distance={distance}",
        f"kind={kind}|hour={hour}",
        f"kind={kind}",
        "global",
    ]


def select_context_base_rate(artifact, bin_kind, cutoff_hour, distance_bucket):
    market_cfg = (artifact or {}).get("market_bin", {})
    contexts = market_cfg.get("contexts") or {}
    min_n = int(market_cfg.get("min_context_n", 40))
    for key in context_keys(bin_kind, cutoff_hour, distance_bucket):
        row = contexts.get(key)
        if row and int(row.get("n", 0)) >= min_n:
            return float(row["base_rate"]), key, int(row.get("n", 0))
    global_row = contexts.get("global") or {}
    return (
        float(global_row.get("base_rate", market_cfg.get("base_rate", 0.10))),
        "global",
        int(global_row.get("n", 0)),
    )


def apply_exact_distribution_calibration(distribution, artifact, floor_bucket=None):
    if not distribution:
        return {}
    cfg = (artifact or {}).get("exact_distribution") or {}
    if not cfg.get("enabled", True):
        return normalize(distribution)

    floor_bucket = int(floor_bucket) if floor_bucket is not None else None
    kept = {}
    for bucket, probability in distribution.items():
        bucket = int(bucket)
        if floor_bucket is not None and bucket < floor_bucket:
            kept[bucket] = 0.0
        else:
            kept[bucket] = max(0.0, float(probability))
    kept = normalize(kept)
    if not kept:
        return {}

    temperature = max(0.05, float(cfg.get("temperature", 1.0)))
    if abs(temperature - 1.0) > 1e-9:
        transformed = {
            bucket: (probability ** (1.0 / temperature)) if probability > 0 else 0.0
            for bucket, probability in kept.items()
        }
        kept = normalize(transformed)

    prior_weight = max(0.0, min(1.0, float(cfg.get("prior_weight", 0.0))))
    if prior_weight > 0:
        eligible = [
            bucket for bucket in kept
            if floor_bucket is None or bucket >= floor_bucket
        ]
        if eligible:
            uniform = 1.0 / len(eligible)
            kept = normalize({
                bucket: (
                    0.0 if floor_bucket is not None and bucket < floor_bucket
                    else (1.0 - prior_weight) * kept.get(bucket, 0.0) + prior_weight * uniform
                )
                for bucket in kept
            })

    if floor_bucket is not None:
        for bucket in list(kept):
            if bucket < floor_bucket:
                kept[bucket] = 0.0
    return normalize(kept)


def calibrate_market_probability(
    probability,
    bin_data,
    artifact,
    context=None,
    market_yes=None,
):
    if probability is None:
        return None
    artifact = artifact or {}
    cfg = artifact.get("market_bin") or {}
    if not cfg:
        return probability
    if not cfg.get("enabled", True):
        return probability

    context = context or {}
    bin_kind = bin_data.get("kind") or bin_data.get("bin_kind") or "eq"
    bin_value = bin_data.get("value", bin_data.get("bin_value_c"))
    floor_bucket = context.get("observed_floor_bucket")
    cutoff_hour = context.get("cutoff_hour")
    hard = hard_bin_probability(bin_kind, bin_value, floor_bucket)
    if hard is not None:
        return hard

    raw_probability = max(0.0, min(1.0, float(probability)))
    if cfg.get("preserve_distribution_coherence", True):
        return raw_probability

    raw = clip_probability(probability)
    distance = floor_distance_bucket(bin_value, floor_bucket)
    method = cfg.get("method", "prior_shrink")
    if method == "temperature":
        temperature = max(0.05, float(cfg.get("temperature", 1.0)))
        calibrated = sigmoid(logit(raw) / temperature)
    elif method == "platt":
        slope = float(cfg.get("slope", 1.0))
        intercept = float(cfg.get("intercept", 0.0))
        calibrated = sigmoid(slope * logit(raw) + intercept)
    elif method == "market_shrink" and market_yes is not None:
        weight = max(0.0, min(1.0, float(cfg.get("market_weight", 0.0))))
        calibrated = (1.0 - weight) * raw + weight * clip_probability(market_yes)
    else:
        base_rate, _, context_n = select_context_base_rate(
            artifact,
            bin_kind,
            cutoff_hour,
            distance,
        )
        weight = max(0.0, min(1.0, float(cfg.get("weight", 0.0))))
        shrink_k = max(1.0, float(cfg.get("context_shrink_k", 50.0)))
        effective_weight = weight * (context_n / (context_n + shrink_k)) if context_n else weight
        calibrated = (1.0 - effective_weight) * raw + effective_weight * base_rate

    if observed_support_blocks_floor_lift(bin_kind, bin_value, floor_bucket, context):
        calibrated = min(calibrated, raw)
    if bin_kind == "eq" and not cfg.get("allow_exact_lift", False):
        calibrated = min(calibrated, raw)

    min_probability = max(0.0, float(cfg.get("min_probability", EPSILON)))
    max_probability = min(1.0, float(cfg.get("max_probability", 1.0 - EPSILON)))
    return max(min_probability, min(max_probability, calibrated))


def load_probability_calibration(path=DEFAULT_ARTIFACT_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error loading probability calibration artifact: {exc}")
        return None


def row_floor_bucket(row):
    return round_half_up(row.get("wu_history_high_c"))


def row_observed_support_bucket(row):
    values = [
        row.get("wu_history_high_c"),
        row.get("wu_current_c"),
        row.get("eccc_swob_max_c"),
    ]
    numeric = []
    for value in values:
        parsed = safe_float(value)
        if parsed is not None:
            numeric.append(parsed)
    if not numeric:
        return None
    return round_half_up(max(numeric))


def prepare_training_row(row):
    floor_bucket = row_floor_bucket(row)
    return {
        "target_date": row.get("target_date"),
        "captured_at_local": row.get("captured_at_local"),
        "cutoff_hour": row.get("cutoff_hour"),
        "bin_kind": row.get("bin_kind") or "eq",
        "bin_value_c": row.get("bin_value_c"),
        "observed_floor_bucket": floor_bucket,
        "observed_support_bucket": row_observed_support_bucket(row),
        "distance_bucket": floor_distance_bucket(row.get("bin_value_c"), floor_bucket),
        "model_probability": row.get("model_probability"),
        "market_yes": row.get("market_yes"),
        "outcome": row.get("outcome"),
    }


def read_scored_rows(folders, daily_summary_path=DEFAULT_DAILY_SUMMARY, overrides=None):
    daily_index = {}
    if daily_summary_path and Path(daily_summary_path).exists():
        from backtest import load_daily_summary
        daily_index = load_daily_summary(daily_summary_path)
    rows = []
    overrides = overrides or {}
    for folder in folders:
        folder = Path(folder)
        tape = folder / "snapshots_long.csv"
        if not tape.exists():
            continue
        frame = pd.read_csv(tape)
        target_date = date_from_event_slug(folder.name)
        bucket, _, _ = settlement_for_tape(frame, target_date, daily_index, overrides)
        scored, _, _, _ = backtest_tape(frame, bucket, [0.10], target_date=target_date)
        # `backtest_tape` does not preserve source columns not needed for item 20;
        # add WU floor from the source frame by row order for calibration context.
        by_order = {
            i: row for i, row in frame.reset_index(drop=True).iterrows()
        }
        for scored_row in scored:
            source_row = by_order.get(scored_row.get("row_order"), {})
            scored_row["wu_history_high_c"] = safe_float(source_row.get("wu_history_high_c"))
            rows.append(prepare_training_row(scored_row))
    return rows


def score_predictions(rows, probabilities):
    n = len(rows)
    if n <= 0:
        return None
    return {
        "n": n,
        "brier": sum(brier(p, row["outcome"]) for p, row in zip(probabilities, rows)) / n,
        "logloss": sum(binary_log_loss(p, row["outcome"]) for p, row in zip(probabilities, rows)) / n,
    }


def smoothed_base_rate(rows, alpha=2.0):
    positives = sum(row["outcome"] for row in rows)
    return (positives + alpha) / (len(rows) + 2.0 * alpha) if rows else 0.10


def candidate_predictions(train_rows, eval_rows, method, param=None):
    if method == "identity":
        return [clip_probability(row["model_probability"]) for row in eval_rows]
    if method == "temperature":
        temperature = float(param)
        return [sigmoid(logit(row["model_probability"]) / temperature) for row in eval_rows]
    if method == "prior_shrink":
        base_rate = smoothed_base_rate(train_rows)
        weight = float(param)
        return [
            (1.0 - weight) * clip_probability(row["model_probability"]) + weight * base_rate
            for row in eval_rows
        ]
    if method == "market_shrink":
        weight = float(param)
        return [
            (1.0 - weight) * clip_probability(row["model_probability"])
            + weight * clip_probability(row["market_yes"])
            for row in eval_rows
        ]
    if method == "platt":
        from sklearn.linear_model import LogisticRegression
        train_x = [[logit(row["model_probability"])] for row in train_rows]
        train_y = [row["outcome"] for row in train_rows]
        model = LogisticRegression(C=1.0, solver="lbfgs")
        model.fit(train_x, train_y)
        return [
            float(model.predict_proba([[logit(row["model_probability"])]])[0][1])
            for row in eval_rows
        ]
    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression
        model = IsotonicRegression(out_of_bounds="clip", y_min=EPSILON, y_max=1.0 - EPSILON)
        model.fit(
            [clip_probability(row["model_probability"]) for row in train_rows],
            [row["outcome"] for row in train_rows],
        )
        return [
            float(model.predict([clip_probability(row["model_probability"])])[0])
            for row in eval_rows
        ]
    raise ValueError(f"Unknown calibration method: {method}")


def candidate_grid():
    candidates = [("identity", None)]
    candidates.extend(("temperature", value) for value in (1.2, 1.5, 2.0, 3.0, 4.0, 5.0))
    candidates.extend(("prior_shrink", value) for value in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9))
    candidates.extend([("platt", None), ("isotonic", None)])
    candidates.extend(("market_shrink", value) for value in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
    return candidates


def loo_candidate_scores(rows):
    days = sorted({row["target_date"] for row in rows})
    output = []
    for method, param in candidate_grid():
        predictions = []
        validation_rows = []
        for day in days:
            train = [row for row in rows if row["target_date"] != day]
            validation = [row for row in rows if row["target_date"] == day]
            try:
                fold_predictions = candidate_predictions(train, validation, method, param)
            except Exception:
                predictions = None
                break
            predictions.extend(fold_predictions)
            validation_rows.extend(validation)
        if predictions is None:
            continue
        score = score_predictions(validation_rows, predictions)
        output.append({
            "method": method,
            "param": param,
            **score,
        })
    return sorted(output, key=lambda row: (row["brier"], row["logloss"]))


def fit_final_market_bin_config(rows, candidate_scores):
    deployable = [
        row for row in candidate_scores
        if row["method"] in {"identity", "temperature", "prior_shrink", "platt", "isotonic"}
    ]
    selected = min(deployable, key=lambda row: (row["brier"], row["logloss"]))
    global_base = smoothed_base_rate(rows)
    cfg = {
        "enabled": True,
        "method": selected["method"],
        "base_rate": global_base,
        "min_context_n": 40,
        "context_shrink_k": 50.0,
        "min_probability": EPSILON,
        "max_probability": 1.0 - EPSILON,
        "allow_exact_lift": False,
        "preserve_distribution_coherence": True,
        "selected_loo_brier": selected["brier"],
        "selected_loo_logloss": selected["logloss"],
    }
    if selected["method"] == "prior_shrink":
        cfg["weight"] = selected["param"]
    elif selected["method"] == "temperature":
        cfg["temperature"] = selected["param"]
    elif selected["method"] == "platt":
        from sklearn.linear_model import LogisticRegression
        model = LogisticRegression(C=1.0, solver="lbfgs")
        model.fit(
            [[logit(row["model_probability"])] for row in rows],
            [row["outcome"] for row in rows],
        )
        cfg["slope"] = float(model.coef_[0][0])
        cfg["intercept"] = float(model.intercept_[0])

    cfg["contexts"] = build_context_summaries(rows)
    market_baselines = [row for row in candidate_scores if row["method"] == "market_shrink"]
    if market_baselines:
        best_market = min(market_baselines, key=lambda row: (row["brier"], row["logloss"]))
        cfg["best_market_informed_baseline"] = best_market
    return cfg, selected


def build_context_summaries(rows):
    grouped = defaultdict(list)
    for row in rows:
        keys = context_keys(row["bin_kind"], row["cutoff_hour"], row["distance_bucket"])
        for key in keys:
            grouped[key].append(row)
    contexts = {}
    for key, group_rows in grouped.items():
        contexts[key] = {
            "n": len(group_rows),
            "base_rate": smoothed_base_rate(group_rows),
        }
    return dict(sorted(contexts.items()))


def fit_exact_distribution_config(rows):
    exact_rows = [row for row in rows if row["bin_kind"] not in {"lte", "gte"}]
    if not exact_rows:
        return {"enabled": True, "method": "temperature", "temperature": 1.0, "prior_weight": 0.0}
    candidates = []
    for temperature in (1.0, 1.2, 1.5, 2.0, 3.0, 4.0):
        probabilities = [
            sigmoid(logit(row["model_probability"]) / temperature)
            for row in exact_rows
        ]
        score = score_predictions(exact_rows, probabilities)
        candidates.append({"temperature": temperature, **score})
    unconstrained_best = min(candidates, key=lambda row: (row["brier"], row["logloss"]))
    deployable = [
        row for row in candidates
        if row["temperature"] <= MAX_EXACT_DEPLOYMENT_TEMPERATURE
    ]
    best = min(deployable, key=lambda row: (row["brier"], row["logloss"]))
    return {
        "enabled": True,
        "method": "temperature",
        "temperature": best["temperature"],
        "max_deployment_temperature": MAX_EXACT_DEPLOYMENT_TEMPERATURE,
        "unconstrained_best_temperature": unconstrained_best["temperature"],
        "prior_weight": 0.0,
        "exact_row_count": len(exact_rows),
        "candidate_metrics": candidates,
    }


def artifact_market_predictions(rows, artifact):
    predictions = []
    for row in rows:
        predictions.append(calibrate_market_probability(
            row["model_probability"],
            {"kind": row["bin_kind"], "value": row["bin_value_c"]},
            artifact,
            context={
                "cutoff_hour": row["cutoff_hour"],
                "observed_floor_bucket": row.get("observed_floor_bucket"),
                "observed_support_bucket": row.get("observed_support_bucket"),
            },
            market_yes=row.get("market_yes"),
        ))
    return predictions


def build_artifact(rows, folders):
    candidate_scores = loo_candidate_scores(rows)
    market_bin, selected = fit_final_market_bin_config(rows, candidate_scores)
    exact_distribution = fit_exact_distribution_config(rows)
    baseline = next(row for row in candidate_scores if row["method"] == "identity")
    market_score = score_predictions(
        rows,
        [clip_probability(row["market_yes"]) for row in rows],
    )
    artifact = {
        "version": "v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "training": {
            "snapshot_folders": [str(Path(folder)) for folder in folders],
            "rows": len(rows),
            "target_dates": sorted({row["target_date"] for row in rows}),
            "baseline_brier": baseline["brier"],
            "baseline_logloss": baseline["logloss"],
            "market_brier": market_score["brier"],
            "market_logloss": market_score["logloss"],
            "baseline_brier_skill_vs_market": (
                1.0 - baseline["brier"] / market_score["brier"]
                if market_score["brier"] > 0 else None
            ),
            "selected_brier_skill_vs_market": (
                1.0 - selected["brier"] / market_score["brier"]
                if market_score["brier"] > 0 else None
            ),
        },
        "exact_distribution": exact_distribution,
        "market_bin": market_bin,
        "candidate_scores": candidate_scores,
        "selected_deployable_candidate": selected,
    }
    artifact_score = score_predictions(rows, artifact_market_predictions(rows, artifact))
    artifact["training"]["artifact_replay_brier"] = artifact_score["brier"]
    artifact["training"]["artifact_replay_logloss"] = artifact_score["logloss"]
    artifact["training"]["artifact_replay_brier_skill_vs_market"] = (
        1.0 - artifact_score["brier"] / market_score["brier"]
        if market_score["brier"] > 0 else None
    )
    return artifact


def write_report(path, artifact):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    training = artifact["training"]
    selected = artifact["selected_deployable_candidate"]
    market_baseline = artifact["market_bin"].get("best_market_informed_baseline")
    lines = [
        "# Probability Calibration Report",
        "",
        f"Generated: {artifact['generated_at_utc']}",
        "",
        "## Scope",
        "",
        f"- Training rows: {training['rows']}",
        f"- Target dates: {', '.join(training['target_dates'])}",
        f"- Baseline Brier: {training['baseline_brier']:.4f}",
        f"- Baseline log loss: {training['baseline_logloss']:.4f}",
        f"- Market Brier: {training['market_brier']:.4f}",
        f"- Market log loss: {training['market_logloss']:.4f}",
        f"- Baseline Brier skill vs market: {training['baseline_brier_skill_vs_market']:.3f}",
        f"- Selected Brier skill vs market: {training['selected_brier_skill_vs_market']:.3f}",
        f"- Artifact replay Brier: {training['artifact_replay_brier']:.4f}",
        f"- Artifact replay log loss: {training['artifact_replay_logloss']:.4f}",
        f"- Artifact replay Brier skill vs market: {training['artifact_replay_brier_skill_vs_market']:.3f}",
        "",
        "## Selected Deployable Calibrator",
        "",
        f"- Method: `{selected['method']}`",
        f"- Parameter: `{selected['param']}`",
        f"- LOO Brier: {selected['brier']:.4f}",
        f"- LOO log loss: {selected['logloss']:.4f}",
        "",
    ]
    if market_baseline:
        lines += [
            "## Market-Informed Baseline",
            "",
            f"- Method: `{market_baseline['method']}`",
            f"- Parameter: `{market_baseline['param']}`",
            f"- LOO Brier: {market_baseline['brier']:.4f}",
            f"- LOO log loss: {market_baseline['logloss']:.4f}",
            "",
        ]

    lines += [
        "## Candidate Comparison",
        "",
        "| Method | Param | LOO Brier | LOO Log Loss |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for row in artifact["candidate_scores"]:
        lines.append(
            f"| {row['method']} | {row['param'] if row['param'] is not None else '-'} "
            f"| {row['brier']:.4f} | {row['logloss']:.4f} |"
        )
    lines += [
        "",
        "## Exact Distribution Calibration",
        "",
        f"- Method: `{artifact['exact_distribution']['method']}`",
        f"- Temperature: `{artifact['exact_distribution']['temperature']}`",
        f"- Max deployment temperature: `{artifact['exact_distribution']['max_deployment_temperature']}`",
        f"- Unconstrained best temperature: `{artifact['exact_distribution']['unconstrained_best_temperature']}`",
        f"- Exact-row count: {artifact['exact_distribution']['exact_row_count']}",
        "",
        "## Context Summaries",
        "",
        "The live calibrator falls back through context keys in this order: "
        "`kind+hour+distance`, `kind+distance`, `kind+hour`, `kind`, `global`.",
        "",
        "| Context | N | Smoothed Base Rate |",
        "| :--- | :--- | :--- |",
    ]
    for key, row in artifact["market_bin"]["contexts"].items():
        if key == "global" or row["n"] >= artifact["market_bin"]["min_context_n"]:
            lines.append(f"| {key} | {row['n']} | {row['base_rate'] * 100:.1f}% |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    return discover_settled_folders(root, required_file="snapshots_long.csv")


def cmd_train(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    rows = read_scored_rows(folders, daily_summary_path=args.daily_summary)
    if not rows:
        raise SystemExit("No scored rows found for calibration training.")
    artifact = build_artifact(rows, folders)
    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    write_report(args.report, artifact)
    print(f"Wrote calibration artifact to {artifact_path}")
    print(f"Wrote calibration report to {args.report}")
    selected = artifact["selected_deployable_candidate"]
    baseline = artifact["training"]
    print(
        f"Selected {selected['method']} ({selected['param']}); "
        f"Brier {baseline['baseline_brier']:.4f} -> {selected['brier']:.4f}, "
        f"logloss {baseline['baseline_logloss']:.4f} -> {selected['logloss']:.4f}"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Train probability calibration artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("folders", nargs="*", help="Snapshot folders. Defaults to settled Toronto tapes.")
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    train.add_argument("--artifact", default=str(DEFAULT_ARTIFACT_PATH))
    train.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    train.set_defaults(func=cmd_train)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
