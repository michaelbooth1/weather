"""Forecast source-error model for Toronto high-temperature buckets.

This module turns forecast highs into probability distributions. The first
artifact is intentionally lightweight: it learns source-specific observed-minus-
forecast error, MAE/RMSE, and tail rates from the historical Open-Meteo daily
archive plus any settled snapshot forecast tapes.
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (  # noqa: E402
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    parse_snapshot_time,
    safe_float,
    settlement_for_tape,
)
from market_config import date_from_event_slug  # noqa: E402


DEFAULT_FORECAST_DAILY = Path("data") / "forecast_history" / "cyyz" / "forecast_daily.csv"
DEFAULT_ARTIFACT_PATH = Path("src") / "forecast_error_model.json"
DEFAULT_REPORT_PATH = Path("data") / "backtest" / "forecast_error_report.md"
DEFAULT_SETTLED_SLUGS = (
    "highest-temperature-in-toronto-on-may-27-2026",
    "highest-temperature-in-toronto-on-may-28-2026",
    "highest-temperature-in-toronto-on-may-30-2026",
)
EPSILON = 1e-9


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


def load_forecast_error_model(path=DEFAULT_ARTIFACT_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error loading forecast error model artifact: {exc}")
        return None


def load_daily_summary(path=DEFAULT_DAILY_SUMMARY):
    path = Path(path)
    rows = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            high = safe_float(row.get("max_temp_c"))
            bucket = round_half_up(row.get("max_temp_bucket_c") or high)
            if high is None or bucket is None:
                continue
            rows[row["local_date"]] = {
                "high_c": high,
                "bucket": bucket,
                "row_count": int(float(row.get("row_count") or 0)),
            }
    return rows


def forecast_rows_from_daily_archive(path, daily_summary):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            target_date = row.get("local_date")
            final = daily_summary.get(target_date)
            forecast_high = safe_float(row.get("forecast_high_c"))
            if not final or forecast_high is None:
                continue
            rows.append({
                "target_date": target_date,
                "year": int(target_date[:4]),
                "source": "open_meteo",
                "source_kind": "daily_archive",
                "capture_hour": None,
                "horizon_bucket": "daily",
                "forecast_high_c": forecast_high,
                "observed_high_c": final["high_c"],
                "observed_bucket": final["bucket"],
            })
    return rows


def read_backtest_daily_index(daily_summary):
    return {
        day: (row["bucket"], row["row_count"])
        for day, row in daily_summary.items()
    }


def forecast_rows_from_snapshot_folders(folders, daily_summary):
    daily_index = read_backtest_daily_index(daily_summary)
    rows = []
    for folder in folders:
        folder = Path(folder)
        forecast_path = folder / "forecasts_long.csv"
        snapshot_path = folder / "snapshots_long.csv"
        if not forecast_path.exists() or not snapshot_path.exists():
            continue
        try:
            import pandas as pd
            snapshot_frame = pd.read_csv(snapshot_path)
        except Exception:
            continue
        target_date = date_from_event_slug(folder.name)
        if not target_date:
            continue
        settlement_bucket, _, _ = settlement_for_tape(
            snapshot_frame,
            target_date,
            daily_index,
            {},
        )
        if settlement_bucket is None:
            continue

        grouped = defaultdict(list)
        with forecast_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("target_date") != target_date.isoformat():
                    continue
                grouped[(row.get("snapshot_id"), row.get("source"))].append(row)

        for (snapshot_id, source), group in grouped.items():
            if not snapshot_id or not source:
                continue
            forecast_highs = [safe_float(row.get("forecast_high_c")) for row in group]
            hourly_temps = [safe_float(row.get("target_temp_c")) for row in group]
            values = [value for value in forecast_highs + hourly_temps if value is not None]
            if not values:
                continue
            forecast_high = max(values)
            captured_at = group[0].get("captured_at_local")
            captured_dt = parse_snapshot_time(captured_at)
            rows.append({
                "target_date": target_date.isoformat(),
                "year": target_date.year,
                "source": source,
                "source_kind": "snapshot",
                "capture_hour": captured_dt.hour if captured_dt else None,
                "horizon_bucket": "same_day_snapshot",
                "forecast_high_c": forecast_high,
                "observed_high_c": float(settlement_bucket),
                "observed_bucket": int(settlement_bucket),
            })
    return rows


def summarize_error_rows(rows):
    errors = [row["observed_high_c"] - row["forecast_high_c"] for row in rows]
    if not errors:
        return None
    n = len(errors)
    bias = sum(errors) / n
    mae = sum(abs(error) for error in errors) / n
    rmse = math.sqrt(sum(error * error for error in errors) / n)
    within_0 = sum(1 for error in errors if abs(round_half_up(error)) == 0) / n
    within_1 = sum(1 for error in errors if abs(error) <= 1.0) / n
    tail_2_plus = sum(1 for error in errors if abs(error) >= 2.0) / n
    underforecast_1_plus = sum(1 for error in errors if error >= 1.0) / n
    overforecast_1_plus = sum(1 for error in errors if error <= -1.0) / n
    return {
        "n": n,
        "bias_observed_minus_forecast": bias,
        "mae": mae,
        "rmse": rmse,
        "within_rounded_bucket_rate": within_0,
        "within_1c_rate": within_1,
        "tail_abs_error_ge_2c_rate": tail_2_plus,
        "underforecast_ge_1c_rate": underforecast_1_plus,
        "overforecast_ge_1c_rate": overforecast_1_plus,
    }


def build_source_stats(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source"]].append(row)
    stats = {}
    for source, group in grouped.items():
        summary = summarize_error_rows(group)
        if summary:
            stats[source] = summary
    return dict(sorted(stats.items()))


def build_hour_stats(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row.get("capture_hour") is None:
            continue
        grouped[f"{row['source']}|hour={row['capture_hour']}"].append(row)
    stats = {}
    for key, group in grouped.items():
        summary = summarize_error_rows(group)
        if summary:
            stats[key] = summary
    return dict(sorted(stats.items()))


def normal_bucket_distribution(support, mean, sigma, floor_bucket=None):
    sigma = max(0.10, float(sigma))
    scores = {}
    for bucket in support:
        bucket = int(bucket)
        if floor_bucket is not None and bucket < floor_bucket:
            scores[bucket] = 0.0
        else:
            scores[bucket] = math.exp(-0.5 * ((bucket - mean) / sigma) ** 2)
    return normalize(scores)


def cap_prior_distribution(support, cap_bucket, floor_bucket=None, above_decay=0.28):
    if cap_bucket is None:
        return {}
    scores = {}
    for bucket in support:
        bucket = int(bucket)
        if floor_bucket is not None and bucket < floor_bucket:
            scores[bucket] = 0.02 ** max(1, floor_bucket - bucket)
        elif bucket <= cap_bucket:
            scores[bucket] = 1.0 / (1.0 + abs(bucket - cap_bucket))
        else:
            scores[bucket] = above_decay ** (bucket - cap_bucket)
    return normalize(scores)


def forecast_error_distribution(
    support,
    forecast_values,
    artifact,
    floor_bucket=None,
    capture_hour=None,
):
    if not artifact or not forecast_values:
        return None
    cfg = artifact.get("component") or {}
    if not cfg.get("enabled", True):
        return None
    source_stats = artifact.get("source_stats") or {}
    global_stats = artifact.get("global_stats") or {}
    min_sigma = float(cfg.get("min_sigma", 0.75))
    max_sigma = float(cfg.get("max_sigma", 3.0))
    shrink_k = float(cfg.get("source_weight_shrink_k", 20.0))

    cleaned = []
    for item in forecast_values:
        value = safe_float(item.get("forecast_high_c", item.get("value")))
        source = item.get("source")
        if value is None or not source:
            continue
        stats = source_stats.get(source) or global_stats
        if not stats:
            continue
        cleaned.append((source, value, stats))
    if not cleaned:
        return None

    centers = [
        value + float(stats.get("bias_observed_minus_forecast", 0.0))
        for _, value, stats in cleaned
    ]
    spread = max(centers) - min(centers) if len(centers) > 1 else 0.0
    disagreement_widen = float(cfg.get("disagreement_sigma_per_c", 0.20)) * spread

    combined = {int(bucket): 0.0 for bucket in support}
    total_weight = 0.0
    for (_, value, stats), center in zip(cleaned, centers):
        sigma = max(min_sigma, float(stats.get("rmse") or stats.get("mae") or min_sigma))
        sigma = min(max_sigma, sigma + disagreement_widen)
        n = int(stats.get("n", 0))
        reliability = 1.0 / max(sigma * sigma, 0.01)
        weight = reliability * (n / (n + shrink_k) if n > 0 else 0.25)
        distribution = normal_bucket_distribution(support, center, sigma, floor_bucket)
        for bucket, probability in distribution.items():
            combined[bucket] = combined.get(bucket, 0.0) + weight * probability
        total_weight += weight
    if total_weight <= 0:
        return None
    return normalize(combined)


def multiclass_brier(distribution, observed_bucket):
    support = set(distribution) | {observed_bucket}
    return sum(
        (distribution.get(bucket, 0.0) - (1.0 if bucket == observed_bucket else 0.0)) ** 2
        for bucket in support
    )


def multiclass_logloss(distribution, observed_bucket):
    return -math.log(max(EPSILON, distribution.get(observed_bucket, 0.0)))


def support_for_row(row):
    center = round_half_up(row["forecast_high_c"]) or row["observed_bucket"]
    low = min(center, row["observed_bucket"]) - 8
    high = max(center, row["observed_bucket"]) + 8
    return range(low, high + 1)


def score_component_rows(rows, artifact):
    if not rows:
        return None
    learned_brier = learned_logloss = cap_brier = cap_logloss = 0.0
    scored = 0
    for row in rows:
        support = list(support_for_row(row))
        forecast_item = {
            "source": row["source"],
            "forecast_high_c": row["forecast_high_c"],
        }
        learned = forecast_error_distribution(support, [forecast_item], artifact)
        cap = cap_prior_distribution(support, round_half_up(row["forecast_high_c"]))
        if not learned or not cap:
            continue
        observed = int(row["observed_bucket"])
        learned_brier += multiclass_brier(learned, observed)
        learned_logloss += multiclass_logloss(learned, observed)
        cap_brier += multiclass_brier(cap, observed)
        cap_logloss += multiclass_logloss(cap, observed)
        scored += 1
    if scored <= 0:
        return None
    return {
        "n": scored,
        "learned_brier": learned_brier / scored,
        "learned_logloss": learned_logloss / scored,
        "cap_brier": cap_brier / scored,
        "cap_logloss": cap_logloss / scored,
        "brier_delta_vs_cap": cap_brier / scored - learned_brier / scored,
        "logloss_delta_vs_cap": cap_logloss / scored - learned_logloss / scored,
    }


def leave_one_year_scores(rows):
    years = sorted({
        row["year"] for row in rows
        if row.get("source_kind") == "daily_archive"
    })
    predictions = []
    validation_rows = []
    for year in years:
        train = [row for row in rows if row.get("year") != year]
        validation = [
            row for row in rows
            if row.get("year") == year and row.get("source_kind") == "daily_archive"
        ]
        if not train or not validation:
            continue
        artifact = build_artifact_core(train, [])
        score = score_component_rows(validation, artifact)
        if score:
            predictions.append(score)
            validation_rows.extend(validation)
    if not predictions:
        return None
    total_n = sum(score["n"] for score in predictions)
    return {
        "n": total_n,
        "learned_brier": sum(score["learned_brier"] * score["n"] for score in predictions) / total_n,
        "learned_logloss": sum(score["learned_logloss"] * score["n"] for score in predictions) / total_n,
        "cap_brier": sum(score["cap_brier"] * score["n"] for score in predictions) / total_n,
        "cap_logloss": sum(score["cap_logloss"] * score["n"] for score in predictions) / total_n,
    }


def build_artifact_core(rows, folders):
    source_stats = build_source_stats(rows)
    global_stats = summarize_error_rows(rows) or {}
    target_dates = sorted({row["target_date"] for row in rows})
    artifact = {
        "version": "v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "training": {
            "rows": len(rows),
            "target_date_count": len(target_dates),
            "target_date_min": target_dates[0] if target_dates else None,
            "target_date_max": target_dates[-1] if target_dates else None,
            "snapshot_folders": [str(Path(folder)) for folder in folders],
            "daily_archive_rows": sum(1 for row in rows if row.get("source_kind") == "daily_archive"),
            "snapshot_rows": sum(1 for row in rows if row.get("source_kind") == "snapshot"),
        },
        "component": {
            "enabled": True,
            "min_sigma": 0.75,
            "max_sigma": 3.0,
            "source_weight_shrink_k": 20.0,
            "disagreement_sigma_per_c": 0.20,
        },
        "global_stats": global_stats,
        "source_stats": source_stats,
        "hour_stats": build_hour_stats(rows),
    }
    return artifact


def build_artifact(rows, folders):
    artifact = build_artifact_core(rows, folders)
    replay = score_component_rows(rows, artifact)
    loo = leave_one_year_scores(rows)
    artifact["evaluation"] = {
        "artifact_replay": replay,
        "leave_one_year_daily_archive": loo,
    }
    return artifact


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    root = Path(root)
    return [
        root / slug for slug in DEFAULT_SETTLED_SLUGS
        if (root / slug / "forecasts_long.csv").exists()
    ]


def read_training_rows(
    forecast_daily=DEFAULT_FORECAST_DAILY,
    daily_summary_path=DEFAULT_DAILY_SUMMARY,
    folders=None,
):
    daily_summary = load_daily_summary(daily_summary_path)
    rows = forecast_rows_from_daily_archive(forecast_daily, daily_summary)
    rows.extend(forecast_rows_from_snapshot_folders(folders or [], daily_summary))
    return rows


def fmt_num(value, decimals=4):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def write_report(path, artifact):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    training = artifact["training"]
    replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
    loo = (artifact.get("evaluation") or {}).get("leave_one_year_daily_archive") or {}
    lines = [
        "# Forecast Error Report",
        "",
        f"Generated: {artifact['generated_at_utc']}",
        "",
        "## Scope",
        "",
        f"- Training rows: {training['rows']}",
        f"- Daily archive rows: {training['daily_archive_rows']}",
        f"- Settled snapshot forecast rows: {training['snapshot_rows']}",
        f"- Target dates: {training['target_date_count']} "
        f"({training['target_date_min']} to {training['target_date_max']})",
        "",
        "## Component Score",
        "",
        "Scores compare the learned forecast-error distribution to the previous "
        "point-cap proxy on exact settled buckets.",
        "",
        f"- Artifact replay learned Brier: {fmt_num(replay.get('learned_brier'))}",
        f"- Artifact replay cap-proxy Brier: {fmt_num(replay.get('cap_brier'))}",
        f"- Artifact replay Brier delta vs cap: {fmt_num(replay.get('brier_delta_vs_cap'))}",
        f"- Artifact replay learned log loss: {fmt_num(replay.get('learned_logloss'))}",
        f"- Artifact replay cap-proxy log loss: {fmt_num(replay.get('cap_logloss'))}",
        f"- Artifact replay log-loss delta vs cap: {fmt_num(replay.get('logloss_delta_vs_cap'))}",
        "",
        "## Leave-One-Year Daily Archive",
        "",
        f"- Rows: {loo.get('n', '-')}",
        f"- Learned Brier: {fmt_num(loo.get('learned_brier'))}",
        f"- Cap-proxy Brier: {fmt_num(loo.get('cap_brier'))}",
        f"- Learned log loss: {fmt_num(loo.get('learned_logloss'))}",
        f"- Cap-proxy log loss: {fmt_num(loo.get('cap_logloss'))}",
        "",
        "## Source Error Stats",
        "",
        "| Source | N | Bias obs-fc | MAE | RMSE | Within 1 C | |error| >= 2 C |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for source, stats in artifact["source_stats"].items():
        lines.append(
            f"| {source} | {stats['n']} | "
            f"{fmt_num(stats['bias_observed_minus_forecast'], 3)} | "
            f"{fmt_num(stats['mae'], 3)} | {fmt_num(stats['rmse'], 3)} | "
            f"{fmt_pct(stats['within_1c_rate'])} | "
            f"{fmt_pct(stats['tail_abs_error_ge_2c_rate'])} |"
        )
    lines.extend([
        "",
        "## Live Use",
        "",
        "Live inference consumes `src/forecast_error_model.json` through the "
        "`forecast_cap` component slot, so calibrated empirical weights remain "
        "compatible while the component itself becomes a learned distribution "
        "rather than a one-bucket cap proxy.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_train(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    rows = read_training_rows(args.forecast_daily, args.daily_summary, folders)
    if not rows:
        raise SystemExit("No forecast error training rows found.")
    artifact = build_artifact(rows, folders)
    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    write_report(args.report, artifact)
    replay = artifact["evaluation"]["artifact_replay"]
    print(f"Wrote forecast error artifact to {artifact_path}")
    print(f"Wrote forecast error report to {args.report}")
    print(
        "Learned forecast component Brier "
        f"{replay['cap_brier']:.4f} -> {replay['learned_brier']:.4f}; "
        f"logloss {replay['cap_logloss']:.4f} -> {replay['learned_logloss']:.4f}"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Train forecast source-error artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("folders", nargs="*", help="Settled snapshot folders to add to the forecast-error training set.")
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    train.add_argument("--forecast-daily", default=str(DEFAULT_FORECAST_DAILY))
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
