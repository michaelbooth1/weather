"""Implementation slice extracted from src/weather/reporting/hourly_model_performance.py."""

import tempfile

from weather.reporting.hourly.hourly_model_aggregation import HourlyMarketDayAggregation
from weather.reporting.hourly.hourly_model_gate import *  # noqa: F403
from weather.reporting.serving_gates.model_scoring_liveness import attach_scoring_liveness, build_rerun_command

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def read_json_file(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_cutoff_regime_context(context_root=DEFAULT_BACKTEST_ROOT):
    path = Path(context_root) / DEFAULT_CUTOFF_REGIME_CONTEXT.name
    payload = read_json_file(path)
    if not payload:
        return {"available": False, "path": str(path)}

    replay_by_regime = {
        row.get("group"): row
        for row in (
            payload.get("daily_first_by_cutoff_regime")
            or payload.get("by_cutoff_regime")
            or []
        )
    }
    threshold_by_regime = {
        row.get("regime"): row
        for row in payload.get("regime_thresholds") or []
    }
    weights = []
    for row in payload.get("regime_family_weights") or []:
        regime = row.get("regime")
        replay = replay_by_regime.get(regime) or {}
        threshold = threshold_by_regime.get(regime) or {}
        weights.append({
            "regime": regime,
            "evidence_status": row.get("evidence_status"),
            "forecast_component_weight": row.get("forecast_component_weight"),
            "observed_component_weight": row.get("observed_component_weight"),
            "forecast_family_weight": (row.get("family_weights") or {}).get("open_meteo_forecast_profile"),
            "observed_path_weight": (row.get("family_weights") or {}).get("observed_temp_path"),
            "source_state_weight": (row.get("family_weights") or {}).get("forecast_source_state"),
            "time_context_weight": (row.get("family_weights") or {}).get("time_context"),
            "surface_weight": (row.get("family_weights") or {}).get("surface_weather"),
            "forecast_family_delta_mae": (row.get("family_delta_mae") or {}).get("open_meteo_forecast_profile"),
            "observed_path_delta_mae": (row.get("family_delta_mae") or {}).get("observed_temp_path"),
            "source_state_delta_mae": (row.get("family_delta_mae") or {}).get("forecast_source_state"),
            "candidate_delta_vs_current": replay.get("delta_vs_current"),
            "candidate_delta_vs_market": replay.get("delta_vs_market"),
            "candidate_brier": replay.get("candidate_brier"),
            "current_brier": replay.get("current_brier"),
            "market_brier": replay.get("market_brier"),
            "n_days": replay.get("n_days"),
            "n": replay.get("n"),
            "status": threshold.get("status"),
            "reasons": threshold.get("reasons") or [],
        })
    return {
        "available": True,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "acceptance": payload.get("acceptance") or {},
        "no_leakage_audit": payload.get("no_leakage_audit") or {},
        "regime_family_weights": weights,
    }


def load_forecast_profile_context(context_root=DEFAULT_BACKTEST_ROOT):
    path = Path(context_root) / DEFAULT_FORECAST_PROFILE_CONTEXT.name
    payload = read_json_file(path)
    if not payload:
        return {"available": False, "path": str(path)}

    acceptance = payload.get("acceptance") or {}
    required_slices = []
    for regime, row in sorted((acceptance.get("required_slices") or {}).items()):
        required_slices.append({
            "regime": regime,
            "candidate_brier": row.get("candidate_brier"),
            "current_brier": row.get("current_brier"),
            "market_brier": row.get("market_brier"),
            "delta_vs_current": row.get("delta_vs_current"),
            "delta_vs_market": row.get("delta_vs_market"),
            "n": row.get("n"),
        })

    subfamilies = sorted(
        payload.get("subfamilies") or [],
        key=lambda row: safe_float(row.get("positive_delta_mae_sum")) or 0.0,
        reverse=True,
    )
    return {
        "available": True,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": acceptance.get("status"),
        "reasons": acceptance.get("reasons") or [],
        "required_slices": required_slices,
        "top_subfamilies": [
            {
                "subfamily": row.get("subfamily"),
                "positive_delta_mae_sum": row.get("positive_delta_mae_sum"),
                "best_feature": row.get("best_feature"),
                "best_feature_delta_mae": row.get("best_feature_delta_mae"),
                "min_hgb_importance_q": row.get("min_hgb_importance_q"),
            }
            for row in subfamilies[:5]
        ],
    }


def load_variable_weight_context(context_root=DEFAULT_BACKTEST_ROOT):
    return {
        "cutoff_regime_weighting": load_cutoff_regime_context(context_root),
        "forecast_profile_calibration": load_forecast_profile_context(context_root),
    }


def delta(value, baseline):
    if value is None or baseline is None:
        return None
    return value - baseline


def direction_text(value, good_when_negative=False, decimals=4):
    if value is None:
        return "unavailable"
    direction = "lower" if value < 0 else "higher"
    if good_when_negative and value < 0:
        direction = "better/lower"
    if good_when_negative and value > 0:
        direction = "worse/higher"
    return f"{abs(value):.{decimals}f} {direction}"


def explain_hour(row, overall, best=True):
    hour = row.get("hour_label")
    brier_delta = delta(row.get("model_brier"), overall.get("model_brier"))
    winner_delta = delta(row.get("winner_model_probability"), overall.get("winner_model_probability"))
    loser_delta = delta(row.get("loser_model_probability"), overall.get("loser_model_probability"))
    forecast_gap_delta = delta(row.get("mean_feature_forecast_gap"), overall.get("mean_feature_forecast_gap"))
    market_delta = delta(row.get("market_brier"), overall.get("market_brier"))
    effective_band_gap = row.get("partition_effective_band_gap")
    winner_rank_gap = row.get("partition_winner_rank_gap")
    bits = [
        f"{hour}: model Brier is {direction_text(brier_delta, good_when_negative=True)} than the headline checkpoint average",
    ]
    if winner_delta is not None:
        bits.append(f"realized winner probability is {direction_text(winner_delta, decimals=3)}")
    if loser_delta is not None:
        bits.append(f"probability left on losing bands is {direction_text(loser_delta, decimals=3)}")
    if forecast_gap_delta is not None:
        bits.append(f"forecast-gap feature is {direction_text(forecast_gap_delta, decimals=2)}")
    if market_delta is not None:
        bits.append(f"market Brier is {direction_text(market_delta, good_when_negative=True)}")
    if effective_band_gap is not None:
        bits.append(f"model effective-band spread is {direction_text(effective_band_gap, decimals=2)} than market")
    if winner_rank_gap is not None:
        bits.append(f"winner rank is {direction_text(winner_rank_gap, decimals=2)} than market")
    text = "; ".join(bits) + "."
    if best and row.get("hour") is not None and int(row["hour"]) >= 18:
        text += " This is also a late-day hour, when observed highs and market resolution state are usually much more constrained."
    if not best and row.get("hour") is not None and 10 <= int(row["hour"]) <= 16:
        text += " This sits in the heating/peak-discovery window, where the final high is often not settled yet."
    return text


def driver_notes(best_hours, worst_hours, overall):
    notes = {"best": [], "worst": []}
    for row in best_hours:
        notes["best"].append(explain_hour(row, overall, best=True))
    for row in worst_hours:
        notes["worst"].append(explain_hour(row, overall, best=False))
    return notes


def build_hourly_performance(
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    context_root=DEFAULT_BACKTEST_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
    include_promotion_countable_labels=True,
    markets=None,
    start_date=None,
    end_date=None,
    min_rows=DEFAULT_MIN_ROWS,
    top_hours=DEFAULT_TOP_HOURS,
    min_regime_market_days=DEFAULT_MIN_REGIME_MARKET_DAYS,
    early_brier_regression_tolerance=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    early_logloss_regression_tolerance=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    early_ece_max=DEFAULT_EARLY_ECE_MAX,
):
    labels, skipped = discover_labeled_folders(
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        markets=markets,
        start_date=start_date,
        end_date=end_date,
    )
    days = []
    score_errors = []
    with tempfile.TemporaryDirectory(prefix="weather-hourly-score-") as scratch_root:
        with HourlyMarketDayAggregation(scratch_root) as aggregation:
            for item in labels:
                try:
                    rows, day = score_folder(item["folder"], item["label"])
                except Exception as exc:  # pragma: no cover - defensive report surface
                    score_errors.append({"folder": str(item["folder"]), "error": str(exc)})
                    continue
                aggregation.add_market_day_rows(rows)
                days.append(day)
                del rows

            by_hour = aggregation.by_hour()
            by_hour_regime = aggregation.by_hour_regime()
            all_snapshot_by_hour = aggregation.all_snapshot_by_hour()
            overall_checkpoint = aggregation.overall_checkpoint() or {}
            overall_all_snapshots = aggregation.overall_all_snapshots() or {}
            remediation = aggregation.remediation_candidates()
            early_hour_market_delta_rows = aggregation.early_hour_market_deltas(
                early_brier_regression_tolerance=early_brier_regression_tolerance,
                early_logloss_regression_tolerance=early_logloss_regression_tolerance,
            )
            all_snapshot_row_count = aggregation.all_snapshot_row_count
            checkpoint_row_count = aggregation.checkpoint_row_count

    best_hours, worst_hours = rank_hours(by_hour, min_rows=min_rows, top_hours=top_hours)
    notes = driver_notes(best_hours, worst_hours, overall_checkpoint) if overall_checkpoint else {"best": [], "worst": []}
    remediation_registry = build_remediation_registry(
        remediation,
        by_hour,
        early_hour_market_delta_rows=early_hour_market_delta_rows,
        early_brier_regression_tolerance=early_brier_regression_tolerance,
        early_logloss_regression_tolerance=early_logloss_regression_tolerance,
    )
    gate = hourly_performance_gate(
        by_hour_regime,
        {
            "scored_market_days": len(days),
        },
        min_regime_market_days=min_regime_market_days,
        early_brier_regression_tolerance=early_brier_regression_tolerance,
        early_logloss_regression_tolerance=early_logloss_regression_tolerance,
        early_ece_max=early_ece_max,
    )
    daily_summary = hourly_daily_summary(best_hours, worst_hours, remediation_registry, gate)
    variable_weight_context = load_variable_weight_context(context_root)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now().isoformat(),
        "inputs": {
            "labels_csv": str(Path(labels_csv)),
            "snapshots_root": str(Path(snapshots_root)),
            "context_root": str(Path(context_root)),
            "quality_grades": list(quality_grades or []),
            "include_promotion_countable_labels": bool(include_promotion_countable_labels),
            "markets": list(markets or []),
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
            "min_rows": int(min_rows),
            "top_hours": int(top_hours),
            "min_regime_market_days": int(min_regime_market_days),
            "early_brier_regression_tolerance": float(early_brier_regression_tolerance),
            "early_logloss_regression_tolerance": float(early_logloss_regression_tolerance),
            "early_ece_max": float(early_ece_max),
        },
        "corpus": {
            "selected_label_count": len(labels),
            "scored_market_days": len(days),
            "markets": sorted({day.get("market_id") for day in days if day.get("market_id")}),
            "date_min": min((day.get("target_date") for day in days if day.get("target_date")), default=None),
            "date_max": max((day.get("target_date") for day in days if day.get("target_date")), default=None),
            "all_snapshot_rows": all_snapshot_row_count,
            "hourly_checkpoint_rows": checkpoint_row_count,
            "skipped_labels": skipped,
            "score_errors": score_errors,
        },
        "days": days,
        "overall": {
            "hourly_checkpoint": overall_checkpoint,
            "all_snapshots": overall_all_snapshots,
        },
        "by_hour": by_hour,
        "by_hour_regime": by_hour_regime,
        "all_snapshot_by_hour": all_snapshot_by_hour,
        "best_hours": best_hours,
        "worst_hours": worst_hours,
        "driver_notes": notes,
        "remediation_candidates": remediation,
        "remediation_registry": remediation_registry,
        "hourly_performance_gate": gate,
        "daily_summary": daily_summary,
        "deep_diagnostics": {
            "hour_regime_labels": HOUR_REGIME_LABELS,
            "variable_weight_context": variable_weight_context,
        },
    }
    rerun_command = build_rerun_command(
        "weather.reporting.hourly.hourly_model_performance",
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        markets=markets,
        start_date=start_date,
        end_date=end_date,
        extra_args=[
            "--context-root",
            context_root,
            "--min-rows",
            min_rows,
            "--top-hours",
            top_hours,
            "--min-regime-market-days",
            min_regime_market_days,
            "--early-brier-regression-tolerance",
            early_brier_regression_tolerance,
            "--early-logloss-regression-tolerance",
            early_logloss_regression_tolerance,
            "--early-ece-max",
            early_ece_max,
        ],
    )
    return attach_scoring_liveness(
        payload,
        artifact_name="hourly_model_performance",
        labels_csv=labels_csv,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        last_scored_target_date=(payload.get("corpus") or {}).get("date_max"),
        rerun_command=rerun_command,
        gate_keys=("hourly_performance_gate",),
    )

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
