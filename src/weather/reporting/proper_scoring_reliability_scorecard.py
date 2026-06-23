"""Proper-scoring and reliability scorecard for model-review artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("proper_scoring_reliability_scorecard")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_ACTIVE_SHADOW_LONG = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_long.csv"
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_HOURLY = DEFAULT_BACKTEST_ROOT / "hourly_model_performance.json"
DEFAULT_TEN_MINUTE = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_SERVED_DISTRIBUTION = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "proper_scoring_reliability_scorecard.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "proper_scoring_reliability_scorecard.md"
DEFAULT_ECE_WARN = 0.12
DEFAULT_PARITY_WARN_MAE = 0.02

LITERATURE_APPENDIX = [
    {
        "concept": "Strictly proper scoring rules",
        "use": "Brier score, logarithmic score, and CRPS/ranked probability score reward calibrated full probabilistic forecasts.",
        "reference": "Gneiting and Raftery (2007), Strictly Proper Scoring Rules, Prediction, and Estimation",
        "url": "https://doi.org/10.1198/016214506000001437",
    },
    {
        "concept": "Reliability and sharpness",
        "use": "Reliability separates calibration error from the sharpness or concentration of the predictive distribution.",
        "reference": "Gneiting, Balabdaoui, and Raftery (2007), Probabilistic forecasts, calibration and sharpness",
        "url": "https://doi.org/10.1111/j.1467-9868.2007.00587.x",
    },
    {
        "concept": "Probability integral transform / rank histograms",
        "use": "PIT and rank diagnostics expose overdispersed, underdispersed, or biased distributions.",
        "reference": "Dawid (1984), Statistical Theory: The Prequential Approach",
        "url": "https://doi.org/10.1111/j.2517-6161.1984.tb01363.x",
    },
]


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return number


def _clamp_probability(value):
    number = _float(value)
    if number is None:
        return None
    return max(1e-9, min(1.0 - 1e-9, number))


def _first(row, names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _lane_for_row(row):
    lane = str(row.get("lane") or row.get("skill_lane") or "").strip().lower()
    if lane:
        return lane
    if str(row.get("uses_market_features") or "").strip().lower() in {"true", "1", "yes"}:
        return "market_informed_overlay"
    return "weather_only"


def _row_probability(row):
    return _clamp_probability(_first(row, (
        "probability",
        "candidate_probability",
        "current_probability",
        "recorded_probability",
        "model_probability",
    )))


def _outcome(row):
    value = _first(row, ("outcome", "settlement_outcome", "winner", "label"))
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "win"}:
        return 1.0
    if text in {"false", "no", "loss"}:
        return 0.0
    return _float(value)


def _log_loss(probability, outcome):
    p = _clamp_probability(probability)
    if p is None or outcome is None:
        return None
    return -(outcome * math.log(p) + (1.0 - outcome) * math.log(1.0 - p))


def _score_rows(rows):
    scored = []
    for row in rows:
        probability = _row_probability(row)
        outcome = _outcome(row)
        if probability is None or outcome is None:
            continue
        lane = _lane_for_row(row)
        scored.append({
            **row,
            "lane": lane,
            "_probability": probability,
            "_outcome": outcome,
            "_brier": (probability - outcome) ** 2,
            "_log_loss": _log_loss(probability, outcome),
        })
        market_probability = _clamp_probability(row.get("market_yes"))
        if market_probability is not None:
            scored.append({
                **row,
                "lane": "market_only",
                "_probability": market_probability,
                "_outcome": outcome,
                "_brier": (market_probability - outcome) ** 2,
                "_log_loss": _log_loss(market_probability, outcome),
            })
    return scored


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _stddev(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _ece(rows, bins=10):
    buckets = [[] for _ in range(bins)]
    for row in rows:
        index = min(bins - 1, int(row["_probability"] * bins))
        buckets[index].append(row)
    error = 0.0
    reliability_rows = []
    n = len(rows)
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        confidence = _mean(row["_probability"] for row in bucket)
        frequency = _mean(row["_outcome"] for row in bucket)
        weight = len(bucket) / n
        gap = abs(confidence - frequency)
        error += weight * gap
        reliability_rows.append({
            "bin": index,
            "count": len(bucket),
            "mean_probability": round(confidence, 6),
            "observed_frequency": round(frequency, 6),
            "absolute_gap": round(gap, 6),
        })
    return round(error, 6), reliability_rows


def _group_key(row):
    return (
        row.get("lane"),
        row.get("market_id") or "",
        row.get("target_date") or "",
        row.get("snapshot_id") or row.get("run_id") or "",
        row.get("event_slug") or "",
    )


def _ordered_value(row):
    return _float(_first(row, ("bin_value", "bin_value_c", "settlement_distance")), default=0.0)


def _distribution_diagnostics(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[_group_key(row)].append(row)
    winner_ranks = []
    top1_hits = []
    winner_probs = []
    adjacent_mass = []
    pit_values = []
    rps_values = []
    for group_rows in groups.values():
        winners = [row for row in group_rows if row["_outcome"] >= 0.5]
        if len(group_rows) < 2 or len(winners) != 1:
            continue
        total = sum(row["_probability"] for row in group_rows)
        if total <= 0:
            continue
        normalized = [{**row, "_norm_probability": row["_probability"] / total} for row in group_rows]
        winner = winners[0]
        ranked = sorted(normalized, key=lambda row: row["_norm_probability"], reverse=True)
        rank = next((index + 1 for index, row in enumerate(ranked) if row is winner or row.get("band_key") == winner.get("band_key")), None)
        if rank is not None:
            winner_ranks.append(rank)
            top1_hits.append(1.0 if rank == 1 else 0.0)
        winner_prob = next(
            (row["_norm_probability"] for row in normalized if row is winner or row.get("band_key") == winner.get("band_key")),
            None,
        )
        if winner_prob is not None:
            winner_probs.append(winner_prob)
        adjacent = [
            row["_norm_probability"]
            for row in normalized
            if abs(_float(row.get("settlement_distance"), default=99.0)) <= 1.0
        ]
        if adjacent:
            adjacent_mass.append(sum(adjacent))
        ordered = sorted(normalized, key=_ordered_value)
        cumulative_forecast = 0.0
        cumulative_observed = 0.0
        sq_sum = 0.0
        for row in ordered:
            cumulative_forecast += row["_norm_probability"]
            cumulative_observed += 1.0 if row["_outcome"] >= 0.5 else 0.0
            sq_sum += (cumulative_forecast - cumulative_observed) ** 2
        if len(ordered) > 1:
            rps_values.append(sq_sum / (len(ordered) - 1))
        before = 0.0
        for row in ordered:
            if row is winner or row.get("band_key") == winner.get("band_key"):
                pit_values.append(before + 0.5 * row["_norm_probability"])
                break
            before += row["_norm_probability"]
    return {
        "distribution_group_count": len(groups),
        "ranked_distribution_group_count": len(rps_values),
        "winner_rank_mean": _mean(winner_ranks),
        "top1_winner_hit_rate": _mean(top1_hits),
        "winner_probability_mean": _mean(winner_probs),
        "adjacent_winner_mass_mean": _mean(adjacent_mass),
        "pit_mean": _mean(pit_values),
        "pit_variance": _stddev(pit_values),
        "ranked_probability_score": _mean(rps_values),
        "crps_status": "PASS" if rps_values else "SKIP_BUCKET_DISTRIBUTION_UNAVAILABLE",
    }


def _slice_value(row, name):
    if name == "cutoff_regime":
        hour = _float(_first(row, ("local_cutoff_hour", "cutoff_hour", "capture_hour_local")), default=None)
        if hour is None:
            return "unknown"
        if hour < 10:
            return "early"
        if hour < 15:
            return "midday"
        return "late"
    return str(_first(row, (name,)) or "unknown")


def _slice_metrics(rows, field):
    groups = defaultdict(list)
    for row in rows:
        groups[_slice_value(row, field)].append(row)
    return [
        {
            "slice": field,
            "group": group,
            "n": len(group_rows),
            "brier": round(_mean(row["_brier"] for row in group_rows), 6),
            "log_loss": round(_mean(row["_log_loss"] for row in group_rows), 6),
        }
        for group, group_rows in sorted(groups.items())
    ]


def _lane_summary(lane, rows):
    ece, reliability_rows = _ece(rows)
    distribution = _distribution_diagnostics(rows)
    brier = _mean(row["_brier"] for row in rows)
    log_loss = _mean(row["_log_loss"] for row in rows)
    probabilities = [row["_probability"] for row in rows]
    outcome_rate = _mean(row["_outcome"] for row in rows)
    sharpness = _stddev(probabilities)
    effective_spread = _mean(abs(prob - outcome_rate) for prob in probabilities) if outcome_rate is not None else None
    status = "PASS"
    blockers = []
    if ece is not None and ece > DEFAULT_ECE_WARN:
        status = "WARN"
        blockers.append(f"ece>{DEFAULT_ECE_WARN}")
    return {
        "lane": lane,
        "row_count": len(rows),
        "status": status,
        "blockers": blockers,
        "brier": round(brier, 6) if brier is not None else None,
        "log_loss": round(log_loss, 6) if log_loss is not None else None,
        "ece": ece,
        "sharpness_stddev": round(sharpness, 6) if sharpness is not None else None,
        "effective_spread": round(effective_spread, 6) if effective_spread is not None else None,
        "base_rate": round(outcome_rate, 6) if outcome_rate is not None else None,
        "exact_band_probability_mean": round(distribution["winner_probability_mean"], 6)
        if distribution["winner_probability_mean"] is not None else None,
        "adjacent_winner_mass_mean": round(distribution["adjacent_winner_mass_mean"], 6)
        if distribution["adjacent_winner_mass_mean"] is not None else None,
        "winner_rank_mean": round(distribution["winner_rank_mean"], 6)
        if distribution["winner_rank_mean"] is not None else None,
        "top1_winner_hit_rate": round(distribution["top1_winner_hit_rate"], 6)
        if distribution["top1_winner_hit_rate"] is not None else None,
        "pit_mean": round(distribution["pit_mean"], 6) if distribution["pit_mean"] is not None else None,
        "pit_stddev": round(distribution["pit_variance"], 6) if distribution["pit_variance"] is not None else None,
        "ranked_probability_score": round(distribution["ranked_probability_score"], 6)
        if distribution["ranked_probability_score"] is not None else None,
        "crps_status": distribution["crps_status"],
        "distribution_group_count": distribution["distribution_group_count"],
        "ranked_distribution_group_count": distribution["ranked_distribution_group_count"],
        "reliability_bins": reliability_rows,
        "slices": {
            "market_id": _slice_metrics(rows, "market_id"),
            "cutoff_regime": _slice_metrics(rows, "cutoff_regime"),
            "source_health_state": _slice_metrics(rows, "source_freshness_state"),
            "runtime_identity": _slice_metrics(rows, "runtime_identity"),
            "weak_slot_state": _slice_metrics(rows, "weak_slot_state"),
            "settlement_distance": _slice_metrics(rows, "settlement_distance"),
            "distribution_family": _slice_metrics(rows, "distribution_family"),
        },
    }


def _served_parity(rows):
    pairs = []
    for row in rows:
        served = _clamp_probability(row.get("served_probability"))
        validated = _clamp_probability(row.get("validated_probability"))
        if served is None or validated is None:
            continue
        pairs.append(abs(served - validated))
    if pairs:
        mae = _mean(pairs)
        return {
            "status": "PASS" if mae <= DEFAULT_PARITY_WARN_MAE else "WARN",
            "pair_count": len(pairs),
            "mean_absolute_probability_delta": round(mae, 6),
            "threshold": DEFAULT_PARITY_WARN_MAE,
            "skip_reason": "",
        }
    return {
        "status": "SKIP",
        "pair_count": 0,
        "mean_absolute_probability_delta": None,
        "threshold": DEFAULT_PARITY_WARN_MAE,
        "skip_reason": "served_and_validated_probability_columns_missing",
    }


def _artifact_status(path, status_path=()):
    payload = _read_json(path)
    current = payload or {}
    for key in status_path:
        current = (current or {}).get(key) or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "status": (current or {}).get("status") or (payload or {}).get("status"),
        "summary": (payload or {}).get("summary") or {},
    }


def build_scorecard(
    *,
    active_shadow_long=DEFAULT_ACTIVE_SHADOW_LONG,
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    hourly=DEFAULT_HOURLY,
    ten_minute=DEFAULT_TEN_MINUTE,
    served_distribution=DEFAULT_SERVED_DISTRIBUTION,
    generated_at_utc=None,
):
    source_rows = _read_csv(active_shadow_long)
    scored_rows = _score_rows(source_rows)
    by_lane = defaultdict(list)
    for row in scored_rows:
        by_lane[row["lane"]].append(row)
    lanes = [_lane_summary(lane, rows) for lane, rows in sorted(by_lane.items())]
    lane_statuses = {row["lane"]: row["status"] for row in lanes}
    lane_sections = {
        "weather_only": [row for row in lanes if row["lane"] in {"weather_only", "current", "candidate", "no_market"}],
        "market_only": [row for row in lanes if row["lane"] == "market_only"],
        "market_informed_overlay": [
            row for row in lanes
            if row["lane"] not in {"weather_only", "current", "candidate", "no_market", "market_only"}
        ],
    }
    parity = _served_parity(scored_rows)
    blocker_count = sum(len(row.get("blockers") or []) for row in lanes)
    if parity["status"] == "WARN":
        blocker_count += 1
    status = "MISSING" if not scored_rows else ("WARN" if blocker_count else "PASS")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": status,
        "summary": {
            "source_row_count": len(source_rows),
            "scored_probability_row_count": len(scored_rows),
            "lane_count": len(lanes),
            "blocker_count": blocker_count,
            "lane_statuses": lane_statuses,
            "served_validated_parity_status": parity["status"],
        },
        "inputs": {
            "active_shadow_long": str(active_shadow_long),
            "promotion_refresh": _artifact_status(promotion_refresh),
            "hourly": _artifact_status(hourly, ("hourly_performance_gate",)),
            "ten_minute": _artifact_status(ten_minute, ("ten_minute_performance_gate",)),
            "served_distribution": _artifact_status(served_distribution),
        },
        "lane_sections": lane_sections,
        "lanes": lanes,
        "served_vs_validated_distribution_parity": parity,
        "density_crps": {
            "status": "SKIP",
            "skip_reason": "continuous_density_payload_not_found; bucket ranked_probability_score reported when distribution groups exist",
        },
        "diagnostic_thresholds": {
            "ece_warn": DEFAULT_ECE_WARN,
            "served_validated_probability_mae_warn": DEFAULT_PARITY_WARN_MAE,
            "mode": "diagnostic_only_not_promotion_gate_replacement",
        },
        "literature_appendix": LITERATURE_APPENDIX,
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Proper-Scoring And Reliability Scorecard",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Source rows", summary.get("source_row_count")],
            ["Scored probability rows", summary.get("scored_probability_row_count")],
            ["Lanes", summary.get("lane_count")],
            ["Blockers", summary.get("blocker_count")],
            ["Served-vs-validated parity", summary.get("served_validated_parity_status")],
        ],
    )
    lines += ["", "## Lane Metrics", ""]
    lines += markdown_table(
        ["Lane", "Rows", "Status", "Brier", "Log Loss", "ECE", "Sharpness", "RPS/CRPS", "Winner Rank"],
        [
            [
                row.get("lane"),
                row.get("row_count"),
                row.get("status"),
                fmt_num(row.get("brier"), 6),
                fmt_num(row.get("log_loss"), 6),
                fmt_num(row.get("ece"), 6),
                fmt_num(row.get("sharpness_stddev"), 6),
                fmt_num(row.get("ranked_probability_score"), 6),
                fmt_num(row.get("winner_rank_mean"), 4),
            ]
            for row in payload.get("lanes") or []
        ],
    )
    parity = payload.get("served_vs_validated_distribution_parity") or {}
    lines += [
        "",
        "## Served Versus Validated Distribution Parity",
        "",
        f"Status: `{parity.get('status')}`",
        f"Pairs: `{parity.get('pair_count')}`",
        f"Mean absolute probability delta: `{fmt_num(parity.get('mean_absolute_probability_delta'), 6)}`",
        f"Skip reason: `{parity.get('skip_reason') or '-'}`",
        "",
        "## Literature Appendix",
        "",
    ]
    lines += markdown_table(
        ["Concept", "Use", "Reference"],
        [
            [row["concept"], row["use"], f"[{row['reference']}]({row['url']})"]
            for row in payload.get("literature_appendix") or []
        ],
    )
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(description="Build proper-scoring and reliability scorecard.")
    parser.add_argument("--active-shadow-long", default=str(DEFAULT_ACTIVE_SHADOW_LONG))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--hourly", default=str(DEFAULT_HOURLY))
    parser.add_argument("--ten-minute", default=str(DEFAULT_TEN_MINUTE))
    parser.add_argument("--served-distribution", default=str(DEFAULT_SERVED_DISTRIBUTION))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_scorecard(
        active_shadow_long=args.active_shadow_long,
        promotion_refresh=args.promotion_refresh,
        hourly=args.hourly,
        ten_minute=args.ten_minute,
        served_distribution=args.served_distribution,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Proper-scoring reliability scorecard: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
