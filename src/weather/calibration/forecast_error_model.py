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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.backtesting.settlement_io import (
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    settlement_for_tape,
)
from weather.backtesting.tape_scoring import parse_snapshot_time
from weather.scoring.metrics import safe_float
from weather.backtesting.settled_days import discover_settled_folders, validate_folders_market
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY, all_specs, spec_for_id
from weather.model.feature_store import row_forecast_high_native, row_temp_native
from weather.model.calibration_runtime import (
    FORECAST_SOURCE_ALIASES,
    canonical_forecast_source,
    forecast_error_stats_for_source as runtime_forecast_error_stats_for_source,
    forecast_source_reliability,
    forecast_source_weight,
)
from weather.sources.daily_summary import native_bucket, native_high
from weather.sources.forecast_history import daily_path_for
from weather.artifacts import resolve_artifact_path, writable_artifact_path
from weather.units import round_half_up


DEFAULT_FORECAST_DAILY = data_path() / "forecast_history" / "cyyz" / "forecast_daily.csv"
DEFAULT_ARTIFACT_PATH = resolve_artifact_path("forecast_error_model.json")
DEFAULT_REPORT_PATH = data_path() / "backtest" / "forecast_error_report.md"
EPSILON = 1e-9
SCHEMA_VERSION = "forecast_error_model_v0.2"
COMPONENT_FORECAST_SOURCES = frozenset({
    "weather_forecast",
    "open_meteo",
    "eccc_citypage",
    "nws_hourly",
    "global_ensemble",
})
SOURCE_PRIOR_SHRINK_K = 60.0
SOURCE_WEIGHT_SHRINK_MAX_FACTOR = 6.0


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
            high = native_high(row)
            bucket = native_bucket(row)
            if high is None or bucket is None:
                continue
            rows[row["local_date"]] = {
                "high_c": high,
                "bucket": bucket,
                "row_count": int(float(row.get("row_count") or 0)),
            }
    return rows


def forecast_rows_from_daily_archive(path, daily_summary, market_id=None, regime_id=None):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            target_date = row.get("local_date")
            final = daily_summary.get(target_date)
            forecast_high = row_forecast_high_native(row)
            if not final or forecast_high is None:
                continue
            rows.append({
                "target_date": target_date,
                "year": int(target_date[:4]),
                "source": canonical_forecast_source("open_meteo"),
                "source_kind": "daily_archive",
                "capture_hour": None,
                "horizon_bucket": "daily",
                "forecast_high_c": forecast_high,
                "observed_high_c": final["high_c"],
                "observed_bucket": final["bucket"],
                "market_id": market_id,
                "regime_id": regime_id,
            })
    return rows


def read_backtest_daily_index(daily_summary):
    return {
        day: (row["bucket"], row["row_count"])
        for day, row in daily_summary.items()
    }


def forecast_rows_from_snapshot_folders(folders, daily_summary, market_id=None, regime_id=None):
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
            source = canonical_forecast_source(source)
            forecast_highs = [row_forecast_high_native(row) for row in group]
            hourly_temps = [row_temp_native(row) for row in group]
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
                "market_id": market_id,
                "regime_id": regime_id,
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


def _weighted_mean(raw, prior, key, prior_weight):
    raw_n = int(raw.get("n", 0))
    prior_n = int(prior.get("n", 0)) if prior else 0
    weight = min(float(prior_weight), float(prior_n)) if prior_n > 0 else 0.0
    total = raw_n + weight
    if total <= 0 or key not in raw:
        return raw.get(key)
    prior_value = prior.get(key, raw.get(key)) if prior else raw.get(key)
    return (float(raw.get(key, 0.0)) * raw_n + float(prior_value) * weight) / total


def shrink_summary_to_prior(raw, prior, prior_weight=SOURCE_PRIOR_SHRINK_K):
    if not raw or not prior:
        return dict(raw or {})
    raw_n = int(raw.get("n", 0))
    prior_n = int(prior.get("n", 0))
    weight = min(float(prior_weight), float(prior_n)) if prior_n > 0 else 0.0
    if raw_n <= 0 or weight <= 0:
        return dict(raw)
    shrunk = dict(raw)
    for key in (
        "bias_observed_minus_forecast",
        "mae",
        "within_rounded_bucket_rate",
        "within_1c_rate",
        "tail_abs_error_ge_2c_rate",
        "underforecast_ge_1c_rate",
        "overforecast_ge_1c_rate",
    ):
        if key in raw:
            shrunk[key] = _weighted_mean(raw, prior, key, weight)
    raw_rmse = float(raw.get("rmse") or raw.get("mae") or 0.0)
    prior_rmse = float(prior.get("rmse") or prior.get("mae") or raw_rmse)
    total = raw_n + weight
    shrunk["rmse"] = math.sqrt(((raw_rmse * raw_rmse) * raw_n + (prior_rmse * prior_rmse) * weight) / total)
    shrunk["raw_n"] = raw_n
    shrunk["prior_n"] = prior_n
    shrunk["prior_weight"] = weight
    return shrunk


def _median(values):
    values = sorted(float(value) for value in values if value is not None)
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2.0


def attach_reliability_fields(stats_by_key, base_shrink_k=20.0):
    reliabilities = {
        key: forecast_source_reliability(stats)
        for key, stats in stats_by_key.items()
        if stats
    }
    reference = _median(reliabilities.values()) or 1.0
    enriched = {}
    for key, stats in stats_by_key.items():
        stats = dict(stats)
        source = str(key).split("|", 1)[0]
        reliability = max(0.0, reliabilities.get(key, 0.0))
        if reliability > 0:
            factor = max(1.0, min(SOURCE_WEIGHT_SHRINK_MAX_FACTOR, reference / reliability))
        else:
            factor = SOURCE_WEIGHT_SHRINK_MAX_FACTOR
        stats["source"] = source
        stats["learned_reliability"] = reliability
        stats["source_weight_shrink_k"] = float(base_shrink_k) * factor
        stats["effective_weight"] = forecast_source_weight(stats, {"source_weight_shrink_k": base_shrink_k})
        stats["reliability_basis"] = "inverse_error_variance"
        enriched[key] = stats
    return enriched


def build_source_stats(rows, prior_stats=None, prior_weight=SOURCE_PRIOR_SHRINK_K):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source"]].append(row)
    stats = {}
    for source, group in grouped.items():
        summary = summarize_error_rows(group)
        if summary:
            prior = (prior_stats or {}).get(source)
            stats[source] = shrink_summary_to_prior(summary, prior, prior_weight=prior_weight)
    return attach_reliability_fields(dict(sorted(stats.items())))


def build_hour_stats(rows, prior_stats=None, prior_weight=SOURCE_PRIOR_SHRINK_K):
    grouped = defaultdict(list)
    for row in rows:
        if row.get("capture_hour") is None:
            continue
        grouped[f"{row['source']}|hour={row['capture_hour']}"].append(row)
    stats = {}
    for key, group in grouped.items():
        summary = summarize_error_rows(group)
        if summary:
            prior = (prior_stats or {}).get(key) or (prior_stats or {}).get(key.split("|", 1)[0])
            stats[key] = shrink_summary_to_prior(summary, prior, prior_weight=prior_weight)
    return attach_reliability_fields(dict(sorted(stats.items())))


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


def forecast_error_stats_for_source(artifact, source, capture_hour):
    return runtime_forecast_error_stats_for_source(artifact, source, capture_hour)


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
    min_sigma = float(cfg.get("min_sigma", 0.75))
    max_sigma = float(cfg.get("max_sigma", 3.0))

    cleaned = []
    for item in forecast_values:
        value = safe_float(item.get("forecast_high_c", item.get("value")))
        source = canonical_forecast_source(item.get("source"), artifact)
        if value is None or not source:
            continue
        stats = forecast_error_stats_for_source(artifact, source, capture_hour)
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
        weight = forecast_source_weight(stats, cfg)
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
        learned = forecast_error_distribution(
            support,
            [forecast_item],
            artifact,
            capture_hour=row.get("capture_hour"),
        )
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


def regime_for_spec(spec):
    if spec.display_unit == "C":
        return "canadian"
    return "marine" if spec.coastal else "continental"


def forecast_component_sources_for_spec(spec):
    return sorted(
        canonical_forecast_source(source)
        for source in spec.sources
        if canonical_forecast_source(source) in COMPONENT_FORECAST_SOURCES
    )


def source_coverage(source_stats, expected_sources):
    observed = set(source_stats or {})
    expected = set(expected_sources or [])
    return {
        "expected_sources": sorted(expected),
        "observed_sources": sorted(observed),
        "missing_sources": sorted(expected - observed),
        "extra_sources": sorted(observed - expected) if expected else sorted(observed),
        "status": "PASS" if not expected or expected <= observed else "WARN",
    }


def build_artifact_core(
    rows,
    folders,
    *,
    market_id=None,
    regime_id=None,
    family_unit=None,
    expected_sources=None,
    prior_rows=None,
):
    raw_source_stats = build_source_stats(rows, prior_stats=None)
    raw_hour_stats = build_hour_stats(rows, prior_stats=None)
    prior_source_stats = build_source_stats(prior_rows or [], prior_stats=None) if prior_rows else {}
    prior_hour_stats = build_hour_stats(prior_rows or [], prior_stats=None) if prior_rows else {}
    source_stats = build_source_stats(rows, prior_stats=prior_source_stats)
    hour_stats = build_hour_stats(rows, prior_stats={**prior_source_stats, **prior_hour_stats})
    global_stats = summarize_error_rows(rows) or {}
    global_stats = attach_reliability_fields({"global": global_stats}).get("global", global_stats) if global_stats else {}
    target_dates = sorted({row["target_date"] for row in rows})
    coverage = source_coverage(source_stats, expected_sources)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "version": "v0.2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market_id": market_id,
        "regime_id": regime_id,
        "family_unit": family_unit,
        "source_aliases": dict(sorted(FORECAST_SOURCE_ALIASES.items())),
        "training": {
            "rows": len(rows),
            "target_date_count": len(target_dates),
            "target_date_min": target_dates[0] if target_dates else None,
            "target_date_max": target_dates[-1] if target_dates else None,
            "snapshot_folders": [str(Path(folder)) for folder in folders],
            "daily_archive_rows": sum(1 for row in rows if row.get("source_kind") == "daily_archive"),
            "snapshot_rows": sum(1 for row in rows if row.get("source_kind") == "snapshot"),
            "market_id": market_id,
            "regime_id": regime_id,
            "family_unit": family_unit,
            "prior_rows": len(prior_rows or []),
        },
        "component": {
            "enabled": True,
            "min_sigma": 0.75,
            "max_sigma": 3.0,
            "source_weight_shrink_k": 20.0,
            "source_prior_shrink_k": SOURCE_PRIOR_SHRINK_K,
            "source_weight_shrink_max_factor": SOURCE_WEIGHT_SHRINK_MAX_FACTOR,
            "disagreement_sigma_per_c": 0.20,
            "weighting": "learned_reliability_x_sample_shrink",
        },
        "source_coverage": coverage,
        "global_stats": global_stats,
        "source_stats": source_stats,
        "raw_source_stats": raw_source_stats,
        "hour_stats": hour_stats,
        "raw_hour_stats": raw_hour_stats,
    }
    return artifact


def build_artifact(rows, folders, **metadata):
    artifact = build_artifact_core(rows, folders, **metadata)
    replay = score_component_rows(rows, artifact)
    loo = leave_one_year_scores(rows)
    artifact["evaluation"] = {
        "artifact_replay": replay,
        "leave_one_year_daily_archive": loo,
    }
    return artifact


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT, market_id=None):
    return discover_settled_folders(
        root, required_file="forecasts_long.csv", market_id=market_id
    )


def read_training_rows(
    forecast_daily=DEFAULT_FORECAST_DAILY,
    daily_summary_path=DEFAULT_DAILY_SUMMARY,
    folders=None,
    market_id=None,
    regime_id=None,
):
    daily_summary = load_daily_summary(daily_summary_path)
    rows = forecast_rows_from_daily_archive(
        forecast_daily,
        daily_summary,
        market_id=market_id,
        regime_id=regime_id,
    )
    rows.extend(forecast_rows_from_snapshot_folders(
        folders or [],
        daily_summary,
        market_id=market_id,
        regime_id=regime_id,
    ))
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
    coverage = artifact.get("source_coverage") or {}
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
        f"- Market: {artifact.get('market_id') or '-'}",
        f"- Regime: {artifact.get('regime_id') or artifact.get('family_unit') or '-'}",
        f"- Source coverage: {coverage.get('status') or '-'}",
        f"- Missing forecast-component sources: {', '.join(coverage.get('missing_sources') or []) or '-'}",
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
        "| Source | N | Bias obs-fc | MAE | RMSE | Reliability | Effective weight | Shrink K | Within 1 | |error| >= 2 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for source, stats in artifact["source_stats"].items():
        lines.append(
            f"| {source} | {stats['n']} | "
            f"{fmt_num(stats['bias_observed_minus_forecast'], 3)} | "
            f"{fmt_num(stats['mae'], 3)} | {fmt_num(stats['rmse'], 3)} | "
            f"{fmt_num(stats.get('learned_reliability'), 4)} | "
            f"{fmt_num(stats.get('effective_weight'), 4)} | "
            f"{fmt_num(stats.get('source_weight_shrink_k'), 2)} | "
            f"{fmt_pct(stats['within_1c_rate'])} | "
            f"{fmt_pct(stats['tail_abs_error_ge_2c_rate'])} |"
        )
    lines.extend([
        "",
        "## Live Use",
        "",
        "Live inference consumes `artifacts/calibration/forecast_error_model.json` through the "
        "`forecast_cap` component slot, so calibrated empirical weights remain "
        "compatible while the component itself becomes a learned distribution "
        "rather than a one-bucket cap proxy.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_train(args):
    # One market's tapes, archive, summary, and artifact per train run:
    # data/snapshots holds all 12 markets' folders.
    spec = spec_for_id(args.market)
    if args.folders:
        folders = [Path(folder) for folder in args.folders]
        validate_folders_market(folders, spec.id)
    else:
        folders = discover_default_folders(args.snapshots_root, market_id=spec.id)
    daily_summary = args.daily_summary or spec.data_root / "daily" / "daily_summary.csv"
    forecast_daily = args.forecast_daily or daily_path_for(spec)
    artifact_arg = args.artifact or writable_artifact_path(f"forecast_error_model{spec.artifact_suffix}.json")
    report_arg = args.report or data_path() / "backtest" / f"forecast_error_report{spec.artifact_suffix}.md"
    regime_id = regime_for_spec(spec)
    rows = read_training_rows(
        forecast_daily,
        daily_summary,
        folders,
        market_id=spec.id,
        regime_id=regime_id,
    )
    if not rows:
        raise SystemExit("No forecast error training rows found.")
    artifact = build_artifact(
        rows,
        folders,
        market_id=spec.id,
        regime_id=regime_id,
        expected_sources=forecast_component_sources_for_spec(spec),
    )
    artifact_path = Path(artifact_arg)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    write_report(report_arg, artifact)
    replay = artifact["evaluation"]["artifact_replay"]
    print(f"Wrote forecast error artifact to {artifact_path}")
    print(f"Wrote forecast error report to {report_arg}")
    print(
        "Learned forecast component Brier "
        f"{replay['cap_brier']:.4f} -> {replay['learned_brier']:.4f}; "
        f"logloss {replay['cap_logloss']:.4f} -> {replay['learned_logloss']:.4f}"
    )


def _rows_for_spec(spec, snapshots_root):
    folders = discover_default_folders(snapshots_root, market_id=spec.id)
    regime_id = regime_for_spec(spec)
    rows = read_training_rows(
        daily_path_for(spec),
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
        market_id=spec.id,
        regime_id=regime_id,
    )
    return rows, folders


def _write_artifact_and_report(artifact, artifact_path, report_path):
    artifact_path = Path(artifact_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    write_report(report_path, artifact)
    return artifact_path


def cmd_train_all(args):
    specs = all_specs()
    rows_by_market = {}
    folders_by_market = {}
    regime_rows = defaultdict(list)
    family_rows = defaultdict(list)
    for spec in specs:
        rows, folders = _rows_for_spec(spec, args.snapshots_root)
        rows_by_market[spec.id] = rows
        folders_by_market[spec.id] = folders
        regime_rows[regime_for_spec(spec)].extend(rows)
        family_rows[spec.display_unit].extend(rows)

    results = []
    for spec in specs:
        rows = rows_by_market.get(spec.id) or []
        folders = folders_by_market.get(spec.id) or []
        if not rows:
            results.append((spec.id, "skipped", 0, None, None, "no rows"))
            continue
        regime_id = regime_for_spec(spec)
        prior_rows = [
            row for row in regime_rows.get(regime_id, [])
            if row.get("market_id") != spec.id
        ]
        artifact = build_artifact(
            rows,
            folders,
            market_id=spec.id,
            regime_id=regime_id,
            expected_sources=forecast_component_sources_for_spec(spec),
            prior_rows=prior_rows,
        )
        artifact_path = writable_artifact_path(f"forecast_error_model{spec.artifact_suffix}.json")
        report_path = data_path() / "backtest" / f"forecast_error_report{spec.artifact_suffix}.md"
        _write_artifact_and_report(artifact, artifact_path, report_path)
        replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
        results.append((
            spec.id,
            (artifact.get("source_coverage") or {}).get("status"),
            len(rows),
            artifact["training"].get("target_date_max"),
            replay.get("learned_brier"),
            str(artifact_path),
        ))

    for unit, rows in sorted(family_rows.items()):
        if unit != "F" or not rows:
            continue
        folders = [
            folder
            for spec in specs
            if spec.display_unit == unit
            for folder in folders_by_market.get(spec.id, [])
        ]
        artifact = build_artifact(
            rows,
            folders,
            family_unit=unit,
            expected_sources=sorted({
                source
                for spec in specs
                if spec.display_unit == unit
                for source in forecast_component_sources_for_spec(spec)
            }),
        )
        artifact["training"]["market_rows"] = {
            spec.id: len(rows_by_market.get(spec.id) or [])
            for spec in specs
            if spec.display_unit == unit
        }
        artifact_path = writable_artifact_path(f"forecast_error_model_{unit.lower()}_family.json")
        report_path = data_path() / "backtest" / f"forecast_error_report_{unit.lower()}_family.md"
        _write_artifact_and_report(artifact, artifact_path, report_path)
        replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
        results.append((
            f"{unit.lower()}_family",
            (artifact.get("source_coverage") or {}).get("status"),
            len(rows),
            artifact["training"].get("target_date_max"),
            replay.get("learned_brier"),
            str(artifact_path),
        ))

    print("Forecast error all-market refit:")
    for market_id, status, rows, target_max, learned_brier, artifact_path in results:
        print(
            f"{market_id}: coverage={status} rows={rows} "
            f"target_date_max={target_max} learned_brier={fmt_num(learned_brier)} "
            f"artifact={artifact_path}"
        )


def build_parser():
    parser = argparse.ArgumentParser(description="Train forecast source-error artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("folders", nargs="*", help="Settled snapshot folders to add to the forecast-error training set.")
    train.add_argument("--market", default="toronto", choices=sorted(REGISTRY),
                       help="Market whose tapes and artifact this train run targets.")
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--daily-summary", default=None,
                       help="Daily summary CSV (default: the market's own data root).")
    train.add_argument("--forecast-daily", default=None,
                       help="Historical forecast daily CSV (default: the market's archive).")
    train.add_argument("--artifact", default=None,
                       help="Artifact path (default: artifacts/calibration/forecast_error_model<suffix>.json).")
    train.add_argument("--report", default=None,
                       help="Report path (default: per-market report under data/backtest).")
    train.set_defaults(func=cmd_train)
    train_all = sub.add_parser("train-all")
    train_all.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train_all.set_defaults(func=cmd_train_all)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
