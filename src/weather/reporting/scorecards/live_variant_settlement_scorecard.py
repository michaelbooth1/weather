"""Canonical settlement scoring and replay parity for live variant tapes.

The scorecard treats one complete probability partition as the integrity and
scoring unit, then collapses correlated snapshots before equal-market-day and
equal-fleet-date evidence summaries. Variant and release identity are part of
every key so rows from different candidates can never be combined into a
synthetic simplex. Invalid partitions remain in coverage and blocker
accounting, but are never included in proper-score aggregates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from weather.backtesting.settlement_io import load_market_day_label, resolve_outcome
from weather.io import write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_pct, markdown_table
from weather.scoring.metrics import binary_log_loss, brier, safe_float
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("live_variant_settlement_scorecard")

DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSON_OUT = data_path("backtest", "live_variant_settlement_scorecard.json")
DEFAULT_REPORT_OUT = data_path("backtest", "live_variant_settlement_scorecard.md")
DEFAULT_PARITY_JSON_OUT = data_path("backtest", "live_variant_replay_parity.json")
DEFAULT_PARITY_REPORT_OUT = data_path("backtest", "live_variant_replay_parity.md")
DEFAULT_SIMPLEX_TOLERANCE = 1e-6
DEFAULT_PARITY_ATOL = 1e-12
DEFAULT_PARITY_RTOL = 1e-9
DEFAULT_PARITY_MAX_INPUT_AGE_HOURS = 48.0
DEFAULT_ECE_BINS = 10
DEFAULT_CLUSTERED_BOOTSTRAP_ITERATIONS = 1_000
DEFAULT_CLUSTERED_BOOTSTRAP_SEED = 27_182

LANE_WEATHER = "weather_only"
LANE_MARKET = "market_benchmark"
LANE_MARKET_INFORMED = "market_informed"
LANE_TRADING = "trading"
LANE_UNCLASSIFIED = "unclassified"
EVIDENCE_LANES = {
    LANE_WEATHER,
    LANE_MARKET,
    LANE_MARKET_INFORMED,
    LANE_TRADING,
}
SCORE_METRIC_FIELDS = (
    "brier",
    "log_loss",
    "categorical_log_loss",
    "top1_hit",
    "winner_rank",
    "winner_probability",
    "rps",
    "ece",
)

PARTITION_KEY_FIELDS = (
    "target_date",
    "market_id",
    "evaluation_point_id",
    "variant_id",
    "release_id",
    "evidence_lane",
)
BASE_PARTITION_KEY_FIELDS = (
    "target_date",
    "market_id",
    "evaluation_point_id",
    "release_id",
)
PARITY_IDENTITY_FIELDS = (
    "live_runtime",
    "route_id",
    "model_version",
    "artifact_hash",
    "postprocess_config_hash",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _first(row: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = row.get(field)
        if _present(value):
            return value
    return None


def _parse_bool(value: Any, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _finite_probability(value: Any) -> float | None:
    parsed = safe_float(value)
    if parsed is None or not math.isfinite(parsed):
        return None
    return parsed


def _normalized_status(row: Mapping[str, Any]) -> str:
    status = str(_first(row, "prediction_status", "status") or "").strip().lower()
    if status in {"predicted", "ok", "success", "pass"}:
        return "predicted"
    if status in {"failed", "failure", "error", "block"}:
        return "failed"
    if status in {"skipped", "skip"}:
        return "skipped"
    if _first(row, "variant_probability", "probability", "served_probability", "replay_probability") is not None:
        return "predicted"
    return "missing"


def _canonical_lane(row: Mapping[str, Any]) -> str:
    explicit = str(_first(row, "evidence_lane", "claim_lane") or "").strip().lower()
    mapping = {
        "weather_only": LANE_WEATHER,
        "weather-only": LANE_WEATHER,
        "weather_only_core_model": LANE_WEATHER,
        "no_market": LANE_WEATHER,
        "market": LANE_MARKET,
        "market_only": LANE_MARKET,
        "market_benchmark": LANE_MARKET,
        "market_informed": LANE_MARKET_INFORMED,
        "market-informed": LANE_MARKET_INFORMED,
        "market_informed_overlay": LANE_MARKET_INFORMED,
        "market_informed_quote_risk": LANE_MARKET_INFORMED,
        "residual_edge": LANE_MARKET_INFORMED,
        "trading": LANE_TRADING,
        "execution": LANE_TRADING,
        "paper_trading": LANE_TRADING,
    }
    if explicit:
        return mapping.get(explicit, LANE_UNCLASSIFIED)

    track = str(_first(row, "registry_track", "track") or "").strip().lower()
    if track == "no_market":
        return LANE_WEATHER
    if track == "market_informed":
        return LANE_MARKET_INFORMED
    if track in {"trading", "execution"}:
        return LANE_TRADING

    roles = str(row.get("registry_roles") or "").lower().replace(",", "|").split("|")
    if any(role.strip() in {"trading", "execution", "paper-trading"} for role in roles):
        return LANE_TRADING
    uses_market = _parse_bool(row.get("uses_market_features"))
    if uses_market is True:
        return LANE_MARKET_INFORMED
    if uses_market is False:
        return LANE_WEATHER
    return LANE_UNCLASSIFIED


def _evaluation_point(row: Mapping[str, Any]) -> tuple[str, str]:
    snapshot_id = _first(row, "snapshot_id", "served_snapshot_id")
    if snapshot_id is not None:
        return "snapshot", f"snapshot:{snapshot_id}"
    cutoff = _first(row, "cutoff_or_snapshot", "cutoff_id", "cutoff_hour", "cutoff")
    if cutoff is not None:
        return "cutoff", f"cutoff:{cutoff}"
    captured = _first(row, "captured_at_utc", "captured_at_local")
    if captured is not None:
        return "captured_at", f"captured_at:{captured}"
    return "missing", "__missing_evaluation_point__"


def _release_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    explicit = _first(row, "release_id", "release_manifest_id", "release_identity")
    if explicit is not None:
        return str(explicit), "explicit"
    commit = _first(row, "runtime_git_commit", "git_commit")
    dirty = _first(row, "runtime_dirty_fingerprint", "dirty_fingerprint", "runtime_git_dirty")
    source = _first(row, "runtime_source_fingerprint", "source_fingerprint")
    serving = _first(row, "serving_model_version")
    if any(value is not None for value in (commit, dirty, source, serving)):
        return (
            "legacy-runtime:"
            f"{commit or 'unknown'}|dirty:{dirty or 'unknown'}|"
            f"src:{source or 'unknown'}|serving:{serving or 'unknown'}",
            "derived_runtime",
        )
    return "__missing_release__", "missing"


def _band_identity(row: Mapping[str, Any]) -> tuple[str, str, float | None, float | None]:
    kind = str(_first(row, "bin_kind", "bin_type") or "").strip().lower()
    value = safe_float(_first(row, "bin_value_c", "bin_value", "value"))
    value_hi = safe_float(_first(row, "bin_value_hi_c", "bin_value_hi", "value_hi"))
    if value_hi is None:
        value_hi = value
    band_key = str(_first(row, "band_key", "range_label", "condition_id") or "").strip()
    if kind and value is not None:
        canonical = f"{kind}:{value:g}:{value_hi:g}"
    elif band_key:
        canonical = f"key:{band_key}"
    else:
        canonical = "__missing_band__"
    return canonical, kind, value, value_hi


def _row_outcome(row: Mapping[str, Any], label: Mapping[str, Any] | None) -> tuple[int | None, str]:
    explicit = safe_float(row.get("outcome"))
    label = label or {}
    settlement_value = _first(row, "settlement_bucket")
    if settlement_value is None:
        settlement_value = label.get("settlement_bucket")
    settlement_bucket = safe_float(settlement_value)
    _, kind, value, value_hi = _band_identity(row)
    resolved = resolve_outcome(kind, value, settlement_bucket, value_hi=value_hi)
    if explicit is not None:
        rounded = int(round(explicit))
        if rounded not in {0, 1} or abs(explicit - rounded) > 1e-9:
            return None, "invalid_explicit_outcome"
        if resolved is not None and rounded != resolved:
            return None, "explicit_outcome_conflicts_with_settlement"
        return rounded, "explicit"
    if resolved is not None:
        return int(resolved), "settlement_bucket"

    winning_kind = str(label.get("winning_band_kind") or "").strip().lower()
    winning_value = safe_float(label.get("winning_band_value"))
    winning_hi = safe_float(label.get("winning_band_value_hi"))
    if winning_hi is None:
        winning_hi = winning_value
    if winning_kind and winning_value is not None and kind and value is not None:
        return (
            int((kind, value, value_hi) == (winning_kind, winning_value, winning_hi)),
            "winning_band_identity",
        )
    winning_label = str(label.get("winning_band") or "").strip().lower()
    row_label = str(_first(row, "range_label", "band_key") or "").strip().lower()
    if winning_label and row_label:
        return int(winning_label == row_label), "winning_band_label"
    return None, "missing_settlement"


def _label_countable(row: Mapping[str, Any], label: Mapping[str, Any] | None, outcome: int | None) -> bool:
    explicit = _parse_bool(_first(row, "promotion_countable", "countable"))
    if explicit is not None:
        return explicit and outcome is not None
    label_value = _parse_bool((label or {}).get("promotion_countable"))
    if label_value is not None:
        return label_value and outcome is not None
    return outcome is not None


def normalize_score_row(
    raw: Mapping[str, Any],
    *,
    label: Mapping[str, Any] | None = None,
    row_number: int | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    """Normalize one tape row without silently repairing invalid values."""
    evaluation_point_type, evaluation_point_id = _evaluation_point(raw)
    release_id, release_id_source = _release_identity(raw)
    canonical_band, kind, value, value_hi = _band_identity(raw)
    outcome, outcome_source = _row_outcome(raw, label)
    status = _normalized_status(raw)
    probability_raw = _first(raw, "variant_probability", "probability", "served_probability")
    probability = _finite_probability(probability_raw)
    serving_probability = _finite_probability(
        _first(raw, "serving_model_probability", "current_probability", "recorded_probability")
    )
    market_probability = _finite_probability(_first(raw, "market_yes", "market_probability"))
    return {
        "target_date": str(_first(raw, "target_date", "market_date") or "").strip(),
        "market_id": str(_first(raw, "market_id", "location_id") or "").strip(),
        "evaluation_point_type": evaluation_point_type,
        "evaluation_point_id": evaluation_point_id,
        "variant_id": str(raw.get("variant_id") or "").strip(),
        "variant_family": str(raw.get("variant_family") or raw.get("variant_id") or "").strip(),
        "release_id": release_id,
        "release_id_source": release_id_source,
        "evidence_lane": _canonical_lane(raw),
        "band_identity": canonical_band,
        "band_key": str(_first(raw, "band_key", "range_label") or "").strip(),
        "range_label": str(raw.get("range_label") or "").strip(),
        "bin_kind": kind,
        "bin_value": value,
        "bin_value_hi": value_hi,
        "prediction_status": status,
        "failure_reason": str(raw.get("failure_reason") or "").strip(),
        "failure_detail": str(raw.get("failure_detail") or "").strip(),
        "probability": probability,
        "probability_was_present": probability_raw is not None,
        "probability_is_finite": probability is not None,
        "serving_probability": serving_probability,
        "market_probability": market_probability,
        "outcome": outcome,
        "outcome_source": outcome_source,
        "settlement_countable": _label_countable(raw, label, outcome),
        "live_runtime": str(raw.get("live_runtime") or "").strip(),
        "route_id": str(_first(raw, "route_id", "route", "route_name") or "").strip(),
        "model_version": str(raw.get("model_version") or "").strip(),
        "artifact_hash": str(raw.get("artifact_hash") or "").strip(),
        "postprocess_config_hash": str(raw.get("postprocess_config_hash") or "").strip(),
        "captured_input_hash": str(
            _first(raw, "captured_input_hash", "replay_input_hash", "input_hash") or ""
        ).strip(),
        "source_path": source_path or str(raw.get("_source_path") or ""),
        "row_number": row_number if row_number is not None else raw.get("_row_number"),
    }


def _key(row: Mapping[str, Any], fields: Sequence[str]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in fields)


def _issue(code: str, detail: str, **values: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **values}


def _ordered_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]] | None:
    if any(row.get("bin_kind") not in {"lte", "eq", "gte"} or row.get("bin_value") is None for row in rows):
        return None
    order = {"lte": 0, "eq": 1, "gte": 2}
    return sorted(rows, key=lambda row: (float(row["bin_value"]), order[row["bin_kind"]], str(row["band_identity"])))


def _partition_metrics(rows: Sequence[Mapping[str, Any]], probability_field: str = "probability") -> dict[str, Any] | None:
    if not rows:
        return None
    probabilities = [row.get(probability_field) for row in rows]
    outcomes = [row.get("outcome") for row in rows]
    if any(value is None for value in probabilities) or any(value not in {0, 1} for value in outcomes):
        return None
    probs = [float(value) for value in probabilities]
    ys = [int(value) for value in outcomes]
    winner_index = ys.index(1) if sum(ys) == 1 else None
    if winner_index is None:
        return None
    winner_probability = probs[winner_index]
    top_probability = max(probs)
    winner_rank = 1 + sum(1 for probability in probs if probability > winner_probability + 1e-15)
    ordered = _ordered_rows(rows)
    rps = None
    if ordered is not None and len(ordered) >= 2:
        cumulative_p = 0.0
        cumulative_y = 0.0
        contributions = []
        for row in ordered[:-1]:
            cumulative_p += float(row[probability_field])
            cumulative_y += int(row["outcome"])
            contributions.append((cumulative_p - cumulative_y) ** 2)
        rps = sum(contributions) / len(contributions)
    bins: list[list[tuple[float, int]]] = [[] for _ in range(DEFAULT_ECE_BINS)]
    for probability, outcome in zip(probs, ys):
        bin_index = min(
            DEFAULT_ECE_BINS - 1,
            int(max(0.0, min(1.0, probability)) * DEFAULT_ECE_BINS),
        )
        bins[bin_index].append((probability, outcome))
    ece = 0.0
    for values in bins:
        if not values:
            continue
        mean_probability = sum(item[0] for item in values) / len(values)
        mean_outcome = sum(item[1] for item in values) / len(values)
        ece += (len(values) / len(rows)) * abs(mean_probability - mean_outcome)
    return {
        "band_count": len(rows),
        "brier": sum(brier(probability, outcome) for probability, outcome in zip(probs, ys)) / len(rows),
        "log_loss": sum(binary_log_loss(probability, outcome) for probability, outcome in zip(probs, ys)) / len(rows),
        "categorical_log_loss": -math.log(max(1e-15, min(1.0, winner_probability))),
        "top1_hit": int(abs(winner_probability - top_probability) <= 1e-15),
        "winner_rank": winner_rank,
        "winner_probability": winner_probability,
        "rps": rps,
        "ece": ece,
        "ece_bin_count": DEFAULT_ECE_BINS,
    }


def _metric_average(
    metrics: Sequence[Mapping[str, Any]],
    *,
    unit_name: str = "partition",
) -> dict[str, Any] | None:
    if not metrics:
        return None
    output: dict[str, Any] = {f"{unit_name}_count": len(metrics)}
    for field in SCORE_METRIC_FIELDS:
        values = [safe_float(metric.get(field)) for metric in metrics]
        present = [value for value in values if value is not None and math.isfinite(value)]
        output[field] = sum(present) / len(present) if present else None
        output[f"{field}_{unit_name}_count"] = len(present)
    return output


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires values")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _date_clustered_intervals(
    market_day_rows: Sequence[Mapping[str, Any]],
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    if not market_day_rows:
        return {
            "method": "whole_fleet_date_clustered_percentile_bootstrap",
            "iterations": iterations,
            "seed": seed,
            "fleet_date_count": 0,
            "market_day_count": 0,
            "metrics": {},
        }
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in market_day_rows:
        by_date[str(row["target_date"])].append(row)
    dates = sorted(by_date)
    intervals: dict[str, Any] = {}
    for field in SCORE_METRIC_FIELDS:
        available_by_date = {
            target_date: [
                value
                for item in rows
                if (value := safe_float((item.get("metrics") or {}).get(field))) is not None
                and math.isfinite(value)
            ]
            for target_date, rows in by_date.items()
        }
        available_by_date = {
            target_date: values
            for target_date, values in available_by_date.items()
            if values
        }
        field_dates = sorted(available_by_date)
        if not field_dates:
            continue
        point_values = [value for item in field_dates for value in available_by_date[item]]
        stable_basis = json.dumps(
            {"field": field, "dates": field_dates, "values": point_values},
            sort_keys=True,
            separators=(",", ":"),
        )
        stable_seed = seed ^ int(
            hashlib.sha256(stable_basis.encode("utf-8")).hexdigest()[:16], 16
        )
        rng = random.Random(stable_seed)
        samples = []
        for _ in range(iterations):
            sampled_dates = [
                field_dates[rng.randrange(len(field_dates))]
                for _ in field_dates
            ]
            sampled_values = [
                value
                for target_date in sampled_dates
                for value in available_by_date[target_date]
            ]
            samples.append(sum(sampled_values) / len(sampled_values))
        intervals[field] = {
            "point_estimate": sum(point_values) / len(point_values),
            "lower": _quantile(samples, 0.025),
            "upper": _quantile(samples, 0.975),
            "confidence": 0.95,
            "fleet_date_count": len(field_dates),
            "market_day_count": len(point_values),
        }
    return {
        "method": "whole_fleet_date_clustered_percentile_bootstrap",
        "weighting": "equal_market_day_with_whole_fleet_date_resampling",
        "iterations": iterations,
        "seed": seed,
        "fleet_date_count": len(dates),
        "market_day_count": len(market_day_rows),
        "metrics": intervals,
    }


def _metric_views(
    partitions: Sequence[Mapping[str, Any]],
    metric_field: str,
    *,
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    metric_partitions = [
        item for item in partitions if isinstance(item.get(metric_field), Mapping)
    ]
    equal_partition = _metric_average(
        [item[metric_field] for item in metric_partitions]
    )
    by_market_day: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in metric_partitions:
        by_market_day[(str(item["target_date"]), str(item["market_id"]))].append(
            item[metric_field]
        )
    market_day_rows = [
        {
            "target_date": key[0],
            "market_id": key[1],
            "metrics": _metric_average(values),
        }
        for key, values in sorted(by_market_day.items())
    ]
    equal_market_day = _metric_average(
        [row["metrics"] for row in market_day_rows if row.get("metrics")],
        unit_name="market_day",
    )
    by_fleet_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in market_day_rows:
        if row.get("metrics"):
            by_fleet_date[row["target_date"]].append(row["metrics"])
    fleet_date_rows = [
        {
            "target_date": target_date,
            "metrics": _metric_average(values, unit_name="market_day"),
        }
        for target_date, values in sorted(by_fleet_date.items())
    ]
    equal_fleet_date = _metric_average(
        [row["metrics"] for row in fleet_date_rows if row.get("metrics")],
        unit_name="fleet_date",
    )
    return {
        "headline_weighting": "equal_market_day",
        "equal_market_day": equal_market_day,
        "equal_fleet_date": equal_fleet_date,
        "equal_partition_diagnostic": equal_partition,
        "date_clustered_intervals": _date_clustered_intervals(
            market_day_rows,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        ),
    }


def _partition_identity(key: Sequence[Any]) -> dict[str, Any]:
    return dict(zip(PARTITION_KEY_FIELDS, key))


def _base_identity(key: Sequence[Any]) -> dict[str, Any]:
    return dict(zip(BASE_PARTITION_KEY_FIELDS, key))


def _build_partition(
    key: tuple[Any, ...],
    rows: Sequence[dict[str, Any]],
    *,
    expected_bands: set[str],
    simplex_tolerance: float,
    require_explicit_release_id: bool,
) -> dict[str, Any]:
    identity = _partition_identity(key)
    issues: list[dict[str, Any]] = []
    band_counts = Counter(row["band_identity"] for row in rows)
    duplicates = sorted(band for band, count in band_counts.items() if count > 1)
    present_bands = set(band_counts)
    missing_bands = sorted(expected_bands - present_bands)
    unexpected_bands = sorted(present_bands - expected_bands)
    if duplicates:
        issues.append(_issue("duplicate_band_rows", f"duplicate rows for {len(duplicates)} band(s)", bands=duplicates))
    if "__missing_band__" in present_bands:
        issues.append(_issue("missing_band_identity", "one or more rows have no canonical band identity"))
    if missing_bands:
        issues.append(_issue("missing_bands", f"partition is missing {len(missing_bands)} band(s)", bands=missing_bands))
    if unexpected_bands:
        issues.append(
            _issue(
                "unexpected_bands",
                f"partition contains {len(unexpected_bands)} band(s) outside the sibling snapshot contract",
                bands=unexpected_bands,
            )
        )

    statuses = Counter(row["prediction_status"] for row in rows)
    skip_reasons = Counter(
        row["failure_reason"] or "unspecified"
        for row in rows
        if row["prediction_status"] in {"skipped", "failed", "missing"}
    )
    if any(status != "predicted" for status in statuses):
        issues.append(_issue("missing_predictions", "partition contains non-predicted rows", statuses=dict(statuses)))

    unique_rows = []
    for band, count in band_counts.items():
        if count == 1:
            unique_rows.append(next(row for row in rows if row["band_identity"] == band))
    probabilities = [row["probability"] for row in unique_rows]
    nonfinite = [row["band_identity"] for row in rows if row["prediction_status"] == "predicted" and not row["probability_is_finite"]]
    out_of_range = [
        row["band_identity"]
        for row in unique_rows
        if row["probability"] is not None and not 0.0 <= row["probability"] <= 1.0
    ]
    if nonfinite:
        issues.append(_issue("nonfinite_probabilities", "predicted rows contain missing/NaN/infinite probabilities", bands=sorted(set(nonfinite))))
    if out_of_range:
        issues.append(_issue("out_of_range_probabilities", "probabilities must be within [0,1]", bands=out_of_range))
    probability_sum = sum(value for value in probabilities if value is not None and math.isfinite(value))
    simplex_error = abs(probability_sum - 1.0)
    if len(probabilities) != len(expected_bands) or any(value is None for value in probabilities):
        issues.append(_issue("incomplete_probability_partition", "cannot prove a complete probability simplex"))
    elif simplex_error > simplex_tolerance:
        issues.append(
            _issue(
                "simplex_sum_mismatch",
                f"probability sum {probability_sum:.12g} differs from 1 by {simplex_error:.3g}",
                probability_sum=probability_sum,
                error=simplex_error,
                tolerance=simplex_tolerance,
            )
        )

    outcomes = [row["outcome"] for row in unique_rows]
    winner_count = sum(1 for outcome in outcomes if outcome == 1)
    missing_outcomes = sum(1 for outcome in outcomes if outcome not in {0, 1})
    if missing_outcomes:
        issues.append(_issue("missing_or_invalid_outcomes", f"{missing_outcomes} band outcome(s) are unresolved or invalid"))
    if winner_count != 1:
        issues.append(_issue("winner_count_mismatch", f"expected exactly one winning band, found {winner_count}", winner_count=winner_count))

    release_sources = sorted({row["release_id_source"] for row in rows})
    if len(release_sources) > 1:
        issues.append(_issue("mixed_release_identity_sources", "partition mixes release identity provenance", sources=release_sources))
    if require_explicit_release_id and release_sources != ["explicit"]:
        issues.append(_issue("explicit_release_id_required", "promotion evidence requires an explicit immutable release_id", sources=release_sources))
    if identity["evidence_lane"] not in EVIDENCE_LANES - {LANE_MARKET}:
        issues.append(_issue("unclassified_evidence_lane", "variant evidence must declare weather-only, market-informed, or trading lane"))
    if identity["evaluation_point_id"] == "__missing_evaluation_point__":
        issues.append(_issue("missing_evaluation_point", "partition has neither snapshot nor cutoff identity"))
    for field in ("target_date", "market_id", "variant_id"):
        if not identity[field]:
            issues.append(_issue(f"missing_{field}", f"partition is missing {field}"))

    eligible = bool(rows) and all(row["settlement_countable"] for row in rows)
    blocking_codes = [issue["code"] for issue in issues]
    valid = eligible and not blocking_codes
    metrics = _partition_metrics(unique_rows) if valid else None
    current_metrics = None
    if valid and all(row.get("serving_probability") is not None and 0 <= row["serving_probability"] <= 1 for row in unique_rows):
        current_sum = sum(float(row["serving_probability"]) for row in unique_rows)
        if abs(current_sum - 1.0) <= simplex_tolerance:
            current_metrics = _partition_metrics(unique_rows, "serving_probability")
    market_metrics = None
    if valid and all(row.get("market_probability") is not None and 0 <= row["market_probability"] <= 1 for row in unique_rows):
        market_sum = sum(float(row["market_probability"]) for row in unique_rows)
        market_metrics = _partition_metrics(unique_rows, "market_probability")
        if market_metrics is not None:
            market_metrics["probability_sum"] = market_sum
            market_metrics["simplex_valid"] = abs(market_sum - 1.0) <= simplex_tolerance
            # Binary market prices remain legitimate per-band Brier/log-loss
            # benchmarks even when overround means they are not a categorical
            # simplex.  Distribution-only scores must not pretend otherwise.
            if not market_metrics["simplex_valid"]:
                market_metrics["categorical_log_loss"] = None
                market_metrics["rps"] = None

    unresolved_settlement = missing_outcomes > 0
    return {
        **identity,
        "status": (
            "PASS"
            if valid
            else ("BLOCK" if eligible else ("UNRESOLVED" if unresolved_settlement else "INELIGIBLE"))
        ),
        "eligible": eligible,
        "valid": valid,
        "unresolved_settlement": unresolved_settlement,
        "row_count": len(rows),
        "expected_band_count": len(expected_bands),
        "present_band_count": len(present_bands),
        "predicted_band_count": sum(count for status, count in statuses.items() if status == "predicted"),
        "missing_prediction_band_count": sum(count for status, count in statuses.items() if status != "predicted"),
        "prediction_status_counts": dict(sorted(statuses.items())),
        "skip_failure_reasons": dict(sorted(skip_reasons.items())),
        "duplicate_bands": duplicates,
        "missing_bands": missing_bands,
        "unexpected_bands": unexpected_bands,
        "winner_count": winner_count,
        "probability_sum": probability_sum,
        "simplex_error": simplex_error,
        "release_identity_sources": release_sources,
        "blocker_codes": blocking_codes,
        "issues": issues,
        "metrics": metrics,
        "current_served_metrics": current_metrics,
        "market_benchmark_metrics": market_metrics,
    }


def _aggregate_partitions(
    partitions: Sequence[Mapping[str, Any]],
    *,
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for partition in partitions:
        grouped[(partition["evidence_lane"], partition["variant_id"], partition["release_id"])].append(partition)
    summaries = []
    for (lane, variant_id, release_id), items in sorted(grouped.items()):
        valid = [item for item in items if item.get("valid") and item.get("metrics")]
        market_days = {(item["target_date"], item["market_id"]) for item in valid}
        fleet_dates = {item["target_date"] for item in valid}
        metric_views = _metric_views(
            valid,
            "metrics",
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        )
        current_views = _metric_views(
            valid,
            "current_served_metrics",
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        )
        market_views = _metric_views(
            valid,
            "market_benchmark_metrics",
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        )
        summary = {
            "evidence_lane": lane,
            "variant_id": variant_id,
            "release_id": release_id,
            "partition_count": len(items),
            "eligible_partition_count": sum(1 for item in items if item["eligible"]),
            "valid_partition_count": len(valid),
            "blocked_partition_count": sum(1 for item in items if item["status"] == "BLOCK"),
            "market_day_count": len(market_days),
            "fleet_date_count": len(fleet_dates),
            # Headline metrics are market-day weighted. Snapshot density is
            # retained only in the explicitly named diagnostic view.
            "metrics": metric_views["equal_market_day"],
            "current_served_metrics": current_views["equal_market_day"],
            "market_benchmark_metrics": market_views["equal_market_day"],
            "metric_views": metric_views,
            "current_served_metric_views": current_views,
            "market_benchmark_metric_views": market_views,
        }
        if summary["metrics"] and summary["current_served_metrics"]:
            summary["delta_vs_current"] = {
                metric: summary["metrics"][metric] - summary["current_served_metrics"][metric]
                for metric in ("brier", "log_loss")
            }
        if summary["metrics"] and summary["market_benchmark_metrics"]:
            summary["delta_vs_market"] = {
                metric: summary["metrics"][metric] - summary["market_benchmark_metrics"][metric]
                for metric in ("brier", "log_loss")
            }
        summaries.append(summary)
    return summaries


def _normalize_expected_variants(values: Sequence[str | Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    expected = []
    for value in values or []:
        if isinstance(value, str):
            variant_id = value.strip()
            if variant_id:
                expected.append({"variant_id": variant_id, "evidence_lane": LANE_WEATHER, "release_id": None})
            continue
        variant_id = str(value.get("variant_id") or value.get("id") or "").strip()
        if not variant_id:
            continue
        lane = _canonical_lane(value)
        if lane == LANE_UNCLASSIFIED:
            lane = LANE_WEATHER
        expected.append(
            {
                "variant_id": variant_id,
                "evidence_lane": lane,
                "release_id": str(value.get("release_id") or "").strip() or None,
            }
        )
    unique = {
        (row["variant_id"], row["evidence_lane"], row["release_id"]): row
        for row in expected
    }
    return [unique[key] for key in sorted(unique, key=lambda item: tuple(str(value) for value in item))]


def _normalize_expected_partitions(
    values: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized = []
    for value in values or []:
        target_date = str(value.get("target_date") or "").strip()
        market_id = str(value.get("market_id") or "").strip()
        evaluation_point_id = str(value.get("evaluation_point_id") or "").strip()
        bands = [
            dict(row)
            for row in value.get("bands") or []
            if isinstance(row, Mapping) and str(row.get("band_identity") or "").strip()
        ]
        if target_date and market_id and evaluation_point_id and bands:
            normalized.append(
                {
                    "target_date": target_date,
                    "market_id": market_id,
                    "evaluation_point_type": str(
                        value.get("evaluation_point_type") or "snapshot"
                    ),
                    "evaluation_point_id": evaluation_point_id,
                    "bands": bands,
                    "source_path": str(value.get("source_path") or ""),
                }
            )
    unique = {
        (row["target_date"], row["market_id"], row["evaluation_point_id"]): row
        for row in normalized
    }
    return [unique[key] for key in sorted(unique)]


def _synthetic_missing_partition_row(
    *,
    partition: Mapping[str, Any],
    band: Mapping[str, Any],
    expected_variant: Mapping[str, Any],
    release_id: str,
) -> dict[str, Any]:
    return {
        "target_date": partition["target_date"],
        "market_id": partition["market_id"],
        "evaluation_point_type": partition.get("evaluation_point_type") or "snapshot",
        "evaluation_point_id": partition["evaluation_point_id"],
        "variant_id": expected_variant["variant_id"],
        "variant_family": expected_variant["variant_id"],
        "release_id": release_id,
        "release_id_source": "explicit" if release_id else "missing",
        "evidence_lane": expected_variant["evidence_lane"],
        "band_identity": band["band_identity"],
        "band_key": band.get("band_key") or "",
        "range_label": band.get("range_label") or "",
        "bin_kind": band.get("bin_kind"),
        "bin_value": band.get("bin_value"),
        "bin_value_hi": band.get("bin_value_hi"),
        "prediction_status": "missing",
        "failure_reason": "missing_variant_partition",
        "failure_detail": (
            "variant pinned by the expected-variant/snapshot contract has no captured tape rows"
        ),
        "probability": None,
        "probability_was_present": False,
        "probability_is_finite": False,
        "serving_probability": band.get("serving_probability"),
        "market_probability": band.get("market_probability"),
        "outcome": band.get("outcome"),
        "outcome_source": band.get("outcome_source") or "missing_settlement",
        "settlement_countable": bool(band.get("settlement_countable")),
        "live_runtime": "",
        "route_id": "",
        "model_version": "",
        "artifact_hash": "",
        "postprocess_config_hash": "",
        "captured_input_hash": "",
        "source_path": partition.get("source_path") or "",
        "row_number": None,
        "synthetic_expected_variant": True,
        "synthetic_expected_snapshot_partition": True,
    }


def _add_missing_expected_variant_rows(
    normalized: list[dict[str, Any]],
    expected_variants: Sequence[dict[str, Any]],
    expected_partitions: Sequence[dict[str, Any]] = (),
) -> int:
    """Materialize explicit missing partitions for variants pinned by a release.

    Live capture normally emits one skip row per band.  This second line of
    defense catches a variant that disappears from the tape entirely.
    """
    by_base: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        by_base[_key(row, BASE_PARTITION_KEY_FIELDS)].append(row)
    synthetic_count = 0
    additions = []
    partitions_by_key = {
        (row["target_date"], row["market_id"], row["evaluation_point_id"]): row
        for row in expected_partitions
    }

    # A sibling snapshot contract lets us materialize an expected base even
    # when the entire variant snapshot disappeared from the tape. Release IDs
    # come from the frozen expected-variant manifest; an unpinned research
    # registry cannot manufacture immutable release identity.
    for partition_key, partition in partitions_by_key.items():
        matching_base_keys = {
            key
            for key in by_base
            if key[:3] == partition_key
        }
        releases = {
            str(expected.get("release_id") or "")
            for expected in expected_variants
            if expected.get("release_id")
        }
        releases.update(str(key[3] or "") for key in matching_base_keys)
        # If this entire snapshot is absent, reuse only explicit immutable
        # releases observed for another snapshot of the same market-day.  Do
        # not infer release identity from a model name or mutable registry.
        releases.update(
            str(key[3] or "")
            for key in by_base
            if key[0] == partition_key[0]
            and key[1] == partition_key[1]
            and key[3]
            and key[3] != "__missing_release__"
        )
        for release_id in sorted(releases):
            base_key = (*partition_key, release_id)
            by_base.setdefault(base_key, [])

    for base_key, base_rows in by_base.items():
        base = _base_identity(base_key)
        observed = {(row["variant_id"], row["evidence_lane"]) for row in base_rows}
        reference_by_band: dict[str, dict[str, Any]] = {}
        for row in base_rows:
            reference_by_band.setdefault(row["band_identity"], row)
        partition = partitions_by_key.get(base_key[:3])
        if partition:
            for band in partition["bands"]:
                reference_by_band.setdefault(
                    band["band_identity"],
                    _synthetic_missing_partition_row(
                        partition=partition,
                        band=band,
                        expected_variant={
                            "variant_id": "__snapshot_contract__",
                            "evidence_lane": LANE_WEATHER,
                        },
                        release_id=str(base["release_id"] or ""),
                    ),
                )
        for expected in expected_variants:
            if expected.get("release_id") and expected["release_id"] != base["release_id"]:
                continue
            identity = (expected["variant_id"], expected["evidence_lane"])
            if identity in observed:
                continue
            for reference in reference_by_band.values():
                synthetic = dict(reference)
                synthetic.update(
                    {
                        "variant_id": expected["variant_id"],
                        "variant_family": expected["variant_id"],
                        "evidence_lane": expected["evidence_lane"],
                        "prediction_status": "missing",
                        "failure_reason": "missing_variant_partition",
                        "failure_detail": "variant pinned by expected-variant contract has no captured tape rows",
                        "probability": None,
                        "probability_was_present": False,
                        "probability_is_finite": False,
                        "serving_probability": None,
                        "market_probability": reference.get("market_probability"),
                        "source_path": "",
                        "row_number": None,
                        "synthetic_expected_variant": True,
                    }
                )
                additions.append(synthetic)
            synthetic_count += 1
    normalized.extend(additions)
    return synthetic_count


def load_expected_variants(path: str | Path | None) -> list[dict[str, Any]]:
    """Load expected variants from a release manifest or variant registry."""
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    manifest_release_id = None
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        manifest_release_id = str(payload.get("release_id") or "").strip() or None
        values = next(
            (
                payload.get(field)
                for field in (
                    "expected_variants",
                    "expected_variant_ids",
                    "live_variants",
                    "live_variant_ids",
                    "variants",
                )
                if isinstance(payload.get(field), list)
            ),
            [],
        )
    else:
        values = []
    active = []
    for value in values:
        if not isinstance(value, dict):
            active.append(
                {"variant_id": value, "release_id": manifest_release_id}
                if manifest_release_id
                else value
            )
            continue
        lifecycle = str(value.get("lifecycle") or value.get("registry_lifecycle") or "active").lower()
        roles = {str(role).strip().lower() for role in value.get("roles") or []}
        headline = _parse_bool(value.get("active_for_headline"), True)
        if lifecycle != "active" or headline is False or "control" in roles:
            continue
        value = dict(value)
        if manifest_release_id and not value.get("release_id"):
            value["release_id"] = manifest_release_id
        active.append(value)
    return _normalize_expected_variants(active)


def build_scorecard(
    rows: Iterable[Mapping[str, Any]],
    *,
    labels: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    source_labels: Mapping[str, Mapping[str, Any]] | None = None,
    simplex_tolerance: float = DEFAULT_SIMPLEX_TOLERANCE,
    require_explicit_release_id: bool = True,
    generated_at_utc: str | None = None,
    source_paths: Sequence[str] | None = None,
    expected_variants: Sequence[str | Mapping[str, Any]] | None = None,
    expected_partitions: Sequence[Mapping[str, Any]] | None = None,
    expected_partition_blockers: Sequence[Mapping[str, Any]] | None = None,
    expected_partition_contract: str | None = None,
    bootstrap_iterations: int = DEFAULT_CLUSTERED_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = DEFAULT_CLUSTERED_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Build a fail-closed settlement scorecard from live tape rows."""
    if bootstrap_iterations <= 0:
        raise ValueError("bootstrap_iterations must be positive")
    labels = labels or {}
    source_labels = source_labels or {}
    normalized = []
    for index, raw in enumerate(rows, start=1):
        source_path = str(raw.get("_source_path") or "")
        label = source_labels.get(source_path)
        if label is None:
            key = (
                str(_first(raw, "target_date", "market_date") or ""),
                str(_first(raw, "market_id", "location_id") or ""),
            )
            label = labels.get(key)
        normalized.append(
            normalize_score_row(
                raw,
                label=label,
                row_number=int(raw.get("_row_number") or index),
                source_path=source_path,
            )
        )

    captured_row_count = len(normalized)
    expected_variant_rows = _normalize_expected_variants(expected_variants)
    expected_partition_rows = _normalize_expected_partitions(expected_partitions)
    partition_contract = expected_partition_contract or (
        "sibling_snapshot_tape"
        if expected_partitions is not None
        else "observed_tape_rows"
    )
    captured_snapshot_keys = {
        (row["target_date"], row["market_id"], row["evaluation_point_id"])
        for row in normalized
    }
    expected_snapshot_keys = {
        (row["target_date"], row["market_id"], row["evaluation_point_id"])
        for row in expected_partition_rows
    }
    expected_partition_by_key = {
        (row["target_date"], row["market_id"], row["evaluation_point_id"]): row
        for row in expected_partition_rows
    }
    missing_expected_snapshot_keys = sorted(expected_snapshot_keys - captured_snapshot_keys)
    unexpected_snapshot_keys = sorted(captured_snapshot_keys - expected_snapshot_keys)
    if partition_contract != "sibling_snapshot_tape":
        unexpected_snapshot_keys = []
    captured_bands_by_snapshot: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in normalized:
        snapshot_key = (
            row["target_date"],
            row["market_id"],
            row["evaluation_point_id"],
        )
        captured_bands_by_snapshot[snapshot_key].add(row["band_identity"])
    missing_expected_snapshot_bands = []
    for partition in expected_partition_rows:
        snapshot_key = (
            partition["target_date"],
            partition["market_id"],
            partition["evaluation_point_id"],
        )
        missing_bands = sorted(
            {band["band_identity"] for band in partition["bands"]}
            - captured_bands_by_snapshot[snapshot_key]
        )
        if missing_bands:
            missing_expected_snapshot_bands.append(
                {
                    "target_date": snapshot_key[0],
                    "market_id": snapshot_key[1],
                    "evaluation_point_id": snapshot_key[2],
                    "bands": missing_bands,
                }
            )
    missing_expected_variant_partitions = _add_missing_expected_variant_rows(
        normalized,
        expected_variant_rows,
        expected_partition_rows,
    )

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    expected_by_base: dict[tuple[Any, ...], set[str]] = defaultdict(set)
    for row in normalized:
        grouped[_key(row, PARTITION_KEY_FIELDS)].append(row)
        base_key = _key(row, BASE_PARTITION_KEY_FIELDS)
        snapshot_key = base_key[:3]
        contract_partition = expected_partition_by_key.get(snapshot_key)
        if contract_partition:
            expected_by_base[base_key].update(
                band["band_identity"] for band in contract_partition["bands"]
            )
        else:
            expected_by_base[base_key].add(row["band_identity"])

    partitions = []
    for key, group_rows in sorted(grouped.items(), key=lambda item: tuple(str(value) for value in item[0])):
        base_key = tuple(key[PARTITION_KEY_FIELDS.index(field)] for field in BASE_PARTITION_KEY_FIELDS)
        partitions.append(
            _build_partition(
                key,
                group_rows,
                expected_bands=expected_by_base[base_key],
                simplex_tolerance=simplex_tolerance,
                require_explicit_release_id=require_explicit_release_id,
            )
        )

    lane_collisions: list[dict[str, Any]] = []
    variant_lanes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for partition in partitions:
        variant_lanes[(partition["variant_id"], partition["release_id"])].add(partition["evidence_lane"])
    for (variant_id, release_id), lanes in sorted(variant_lanes.items()):
        if len(lanes) > 1:
            lane_collisions.append(
                _issue(
                    "variant_lane_collision",
                    "one variant/release identity appears in multiple evidence lanes",
                    variant_id=variant_id,
                    release_id=release_id,
                    lanes=sorted(lanes),
                )
            )

    comparator_conflicts: list[dict[str, Any]] = []
    comparator_values: dict[tuple[Any, ...], dict[str, set[float]]] = defaultdict(
        lambda: {"market_probability": set(), "serving_probability": set()}
    )
    for row in normalized:
        key = _key(row, BASE_PARTITION_KEY_FIELDS) + (row["band_identity"],)
        for field in ("market_probability", "serving_probability"):
            value = row.get(field)
            if value is not None and math.isfinite(value):
                comparator_values[key][field].add(round(float(value), 15))
    for key, fields in sorted(comparator_values.items(), key=lambda item: str(item[0])):
        for field, values in fields.items():
            if len(values) > 1:
                comparator_conflicts.append(
                    _issue(
                        "comparator_probability_conflict",
                        f"candidate rows disagree on the paired {field}",
                        key=list(key),
                        field=field,
                        values=sorted(values),
                    )
                )

    eligible = [partition for partition in partitions if partition["eligible"]]
    valid = [partition for partition in eligible if partition["valid"]]
    unresolved_settlement = [
        partition for partition in partitions if partition.get("unresolved_settlement")
    ]
    reason_counts = Counter()
    unsupported_skip_band_count = 0
    for row in normalized:
        if row["prediction_status"] != "predicted":
            reason = row["failure_reason"] or "unspecified"
            reason_counts[reason] += 1
            if reason in {"unsupported_runtime", "unsupported_live_runtime", "runtime_unavailable"}:
                unsupported_skip_band_count += 1
    coverage = len(valid) / len(eligible) if eligible else 0.0
    band_eligible = sum(partition["expected_band_count"] for partition in eligible)
    band_predicted = sum(
        partition["predicted_band_count"]
        for partition in eligible
        if not partition["duplicate_bands"]
    )
    overall_blockers = []
    overall_blockers.extend(dict(row) for row in expected_partition_blockers or [])
    if partition_contract == "sibling_snapshot_tape" and not expected_partition_rows:
        overall_blockers.append(
            _issue(
                "expected_snapshot_partitions_empty",
                "sibling snapshot contract contains no expected snapshot partitions",
            )
        )
    if missing_expected_snapshot_keys:
        overall_blockers.append(
            _issue(
                "missing_expected_snapshot_partitions",
                f"{len(missing_expected_snapshot_keys)} sibling snapshot partition(s) are absent from the variant tape",
                partition_count=len(missing_expected_snapshot_keys),
                partitions=[list(key) for key in missing_expected_snapshot_keys[:25]],
            )
        )
    if unexpected_snapshot_keys:
        overall_blockers.append(
            _issue(
                "unexpected_variant_snapshot_partitions",
                f"{len(unexpected_snapshot_keys)} variant snapshot partition(s) are absent from the sibling snapshot tape",
                partition_count=len(unexpected_snapshot_keys),
                partitions=[list(key) for key in unexpected_snapshot_keys[:25]],
            )
        )
    if missing_expected_snapshot_bands:
        overall_blockers.append(
            _issue(
                "missing_expected_snapshot_bands",
                "one or more sibling snapshot bands are absent across every captured variant",
                missing_band_count=sum(
                    len(row["bands"]) for row in missing_expected_snapshot_bands
                ),
                partitions=missing_expected_snapshot_bands[:25],
            )
        )
    if not eligible:
        overall_blockers.append(_issue("no_eligible_settled_partitions", "no promotion-countable settled partitions were available"))
    if len(valid) != len(eligible):
        overall_blockers.append(
            _issue(
                "invalid_eligible_partitions",
                f"{len(eligible) - len(valid)} of {len(eligible)} eligible partitions failed validation",
            )
        )
    if unresolved_settlement:
        overall_blockers.append(
            _issue(
                "unresolved_settlement_partitions",
                (
                    f"{len(unresolved_settlement)} captured partition(s) have missing or "
                    "invalid settlement outcomes"
                ),
                partition_count=len(unresolved_settlement),
                partitions=[
                    _partition_identity(_key(partition, PARTITION_KEY_FIELDS))
                    for partition in unresolved_settlement[:25]
                ],
            )
        )
    if unsupported_skip_band_count:
        overall_blockers.append(
            _issue(
                "unsupported_runtime_skips",
                f"{unsupported_skip_band_count} eligible/captured band rows have unsupported or unavailable runtime skips",
                band_row_count=unsupported_skip_band_count,
            )
        )
    overall_blockers.extend(lane_collisions)
    overall_blockers.extend(comparator_conflicts)
    variant_summaries = _aggregate_partitions(
        partitions,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    lane_summaries = _merged_lane_summaries(
        partitions,
        variant_summaries,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": "PASS" if not overall_blockers else "BLOCK",
        "configuration": {
            "partition_key_fields": list(PARTITION_KEY_FIELDS),
            "simplex_tolerance": simplex_tolerance,
            "require_explicit_release_id": require_explicit_release_id,
            "evidence_unit": "complete_variant_release_probability_partition",
            "independent_evidence_unit": "market_day_and_fleet_date",
            "aggregate_weighting": "equal_market_day",
            "equal_partition_metrics_are_diagnostic_only": True,
            "clustered_bootstrap_iterations": bootstrap_iterations,
            "clustered_bootstrap_seed": bootstrap_seed,
            "expected_partition_contract": partition_contract,
            "expected_variant_contract": (
                "explicit_manifest" if expected_variant_rows else "observed_tape_rows"
            ),
            "expected_variants": expected_variant_rows,
            "metric_definitions": {
                "brier": "mean binary band Brier within partition; partitions collapse within market-day before equal-market-day headline weighting",
                "log_loss": "mean binary band log loss within partition; partitions collapse within market-day before equal-market-day headline weighting",
                "categorical_log_loss": "negative log probability of the unique winning band for simplex-valid distributions",
                "top1_hit": "winner is tied for highest probability",
                "winner_rank": "dense rank of the unique winner by probability",
                "rps": "mean squared cumulative error over K-1 ordered band boundaries",
                "ece": (
                    f"{DEFAULT_ECE_BINS}-bin fixed-width binary-band ECE within each partition; "
                    "partitions collapse within market-day before headline weighting"
                ),
                "equal_partition_diagnostic": (
                    "legacy snapshot-partition mean; diagnostic only and never an independent-sample claim"
                ),
                "confidence_interval": (
                    "deterministic percentile bootstrap resampling whole fleet dates"
                ),
            },
        },
        "inputs": {
            "source_paths": list(source_paths or []),
            "source_path_count": len(source_paths or []),
            "row_count": captured_row_count,
            "synthetic_missing_variant_band_row_count": len(normalized) - captured_row_count,
            "synthetic_missing_snapshot_band_row_count": sum(
                1
                for row in normalized
                if row.get("synthetic_expected_snapshot_partition")
            ),
            "expected_snapshot_source_paths": sorted(
                {
                    str(row.get("source_path") or "")
                    for row in expected_partition_rows
                    if row.get("source_path")
                }
            ),
        },
        "coverage": {
            "partition_count": len(partitions),
            "eligible_partition_count": len(eligible),
            "valid_prediction_partition_count": len(valid),
            "missing_or_invalid_partition_count": len(eligible) - len(valid),
            "unresolved_settlement_partition_count": len(unresolved_settlement),
            "eligible_prediction_coverage": coverage,
            "eligible_band_count": band_eligible,
            "predicted_band_row_count": band_predicted,
            "missing_prediction_band_count": max(0, band_eligible - band_predicted),
            "unsupported_runtime_skip_band_count": unsupported_skip_band_count,
            "missing_expected_variant_partition_count": missing_expected_variant_partitions,
            "expected_snapshot_partition_count": len(expected_snapshot_keys),
            "observed_expected_snapshot_partition_count": len(
                expected_snapshot_keys & captured_snapshot_keys
            ),
            "missing_expected_snapshot_partition_count": len(
                missing_expected_snapshot_keys
            ),
            "unexpected_variant_snapshot_partition_count": len(
                unexpected_snapshot_keys
            ),
            "missing_expected_snapshot_band_count": sum(
                len(row["bands"]) for row in missing_expected_snapshot_bands
            ),
            "expected_snapshot_partition_coverage": (
                len(expected_snapshot_keys & captured_snapshot_keys)
                / len(expected_snapshot_keys)
                if expected_snapshot_keys
                else 0.0
            ),
            "skip_failure_reasons": dict(sorted(reason_counts.items())),
            "market_day_count": len({(item["target_date"], item["market_id"]) for item in eligible}),
            "fleet_date_count": len({item["target_date"] for item in eligible}),
        },
        "blocker_count": len(overall_blockers),
        "first_blocker": overall_blockers[0] if overall_blockers else None,
        "blockers": overall_blockers,
        "lane_summaries": lane_summaries,
        "variant_release_summaries": variant_summaries,
        "partitions": partitions,
    }


def _merged_lane_summaries(
    partitions: Sequence[Mapping[str, Any]],
    variant_summaries: Sequence[Mapping[str, Any]],
    *,
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> list[dict[str, Any]]:
    valid = [partition for partition in partitions if partition.get("valid")]
    summaries = []
    for lane in sorted(EVIDENCE_LANES - {LANE_MARKET}):
        lane_variants = [summary for summary in variant_summaries if summary["evidence_lane"] == lane]
        lane_partitions = [
            partition for partition in valid if partition["evidence_lane"] == lane
        ]
        metric_views = _metric_views(
            lane_partitions,
            "metrics",
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        )
        summaries.append(
            {
                "evidence_lane": lane,
                "variant_release_count": len(lane_variants),
                "eligible_partition_count": sum(item["eligible_partition_count"] for item in lane_variants),
                "valid_partition_count": sum(item["valid_partition_count"] for item in lane_variants),
                "metrics": metric_views["equal_market_day"],
                "metric_views": metric_views,
            }
        )
    unique_market_partitions: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for partition in valid:
        base = tuple(partition[field] for field in BASE_PARTITION_KEY_FIELDS)
        if partition.get("market_benchmark_metrics") and base not in unique_market_partitions:
            unique_market_partitions[base] = partition
    market_views = _metric_views(
        list(unique_market_partitions.values()),
        "market_benchmark_metrics",
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    summaries.append(
        {
            "evidence_lane": LANE_MARKET,
            "variant_release_count": 0,
            "eligible_partition_count": len(unique_market_partitions),
            "valid_partition_count": len(unique_market_partitions),
            "metrics": market_views["equal_market_day"],
            "metric_views": market_views,
        }
    )
    return summaries


def merge_scorecards(
    payloads: Sequence[Mapping[str, Any]],
    *,
    generated_at_utc: str | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    """Merge independently-scored tape files without retaining their raw rows.

    This is the bounded daily-refresh path: each market tape can be loaded,
    normalized, and released before the next tape is read.  Only compact
    partition summaries are combined here.
    """
    if not payloads:
        raise ValueError("at least one scorecard payload is required")
    partitions = [
        dict(partition)
        for payload in payloads
        for partition in payload.get("partitions") or []
    ]
    blockers = []
    source_paths = []
    expected_snapshot_source_paths = []
    skip_reasons = Counter()
    first_configuration = dict(payloads[0].get("configuration") or {})
    configuration_fields = (
        "partition_key_fields",
        "simplex_tolerance",
        "require_explicit_release_id",
        "expected_partition_contract",
        "expected_variant_contract",
        "expected_variants",
        "clustered_bootstrap_iterations",
        "clustered_bootstrap_seed",
    )
    for payload in payloads:
        payload_sources = list((payload.get("inputs") or {}).get("source_paths") or [])
        source_paths.extend(payload_sources)
        expected_snapshot_source_paths.extend(
            (payload.get("inputs") or {}).get("expected_snapshot_source_paths") or []
        )
        child_blockers = list(payload.get("blockers") or [])
        for blocker in child_blockers:
            blockers.append({**dict(blocker), "source_paths": payload_sources})
        if payload.get("status") != "PASS" and not child_blockers:
            blockers.append(
                _issue(
                    "child_scorecard_not_pass",
                    "bounded child scorecard is not PASS but did not provide a blocker",
                    child_status=payload.get("status"),
                    source_paths=payload_sources,
                )
            )
        child_configuration = payload.get("configuration") or {}
        for field in configuration_fields:
            if child_configuration.get(field) != first_configuration.get(field):
                blockers.append(
                    _issue(
                        "inconsistent_child_configuration",
                        f"bounded child scorecards disagree on configuration.{field}",
                        field=field,
                        expected=first_configuration.get(field),
                        actual=child_configuration.get(field),
                        source_paths=payload_sources,
                    )
                )
        skip_reasons.update((payload.get("coverage") or {}).get("skip_failure_reasons") or {})

    partition_counts = Counter(_key(partition, PARTITION_KEY_FIELDS) for partition in partitions)
    for key, count in sorted(partition_counts.items(), key=lambda item: str(item[0])):
        if count > 1:
            blockers.append(
                _issue(
                    "duplicate_partition_across_tapes",
                    f"the same variant/release partition appears in {count} tape payloads",
                    key=list(key),
                    count=count,
                )
            )
            for partition in partitions:
                if _key(partition, PARTITION_KEY_FIELDS) != key:
                    continue
                partition["valid"] = False
                partition["status"] = "BLOCK"
                blocker_codes = list(partition.get("blocker_codes") or [])
                if "duplicate_partition_across_tapes" not in blocker_codes:
                    blocker_codes.append("duplicate_partition_across_tapes")
                partition["blocker_codes"] = blocker_codes
                issues = list(partition.get("issues") or [])
                issues.append(
                    _issue(
                        "duplicate_partition_across_tapes",
                        "duplicate compact partitions cannot contribute to merged metrics",
                    )
                )
                partition["issues"] = issues
    variant_lanes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for partition in partitions:
        variant_lanes[(partition["variant_id"], partition["release_id"])].add(partition["evidence_lane"])
    for (variant_id, release_id), lanes in sorted(variant_lanes.items()):
        if len(lanes) > 1 and not any(
            blocker.get("code") == "variant_lane_collision"
            and blocker.get("variant_id") == variant_id
            and blocker.get("release_id") == release_id
            for blocker in blockers
        ):
            blockers.append(
                _issue(
                    "variant_lane_collision",
                    "one variant/release identity appears in multiple evidence lanes across tapes",
                    variant_id=variant_id,
                    release_id=release_id,
                    lanes=sorted(lanes),
                )
            )

    eligible = [partition for partition in partitions if partition.get("eligible")]
    valid = [partition for partition in eligible if partition.get("valid")]
    unresolved_settlement = [
        partition for partition in partitions if partition.get("unresolved_settlement")
    ]
    bootstrap_iterations = int(
        first_configuration.get("clustered_bootstrap_iterations")
        or DEFAULT_CLUSTERED_BOOTSTRAP_ITERATIONS
    )
    bootstrap_seed = int(
        first_configuration.get("clustered_bootstrap_seed")
        or DEFAULT_CLUSTERED_BOOTSTRAP_SEED
    )
    variant_summaries = _aggregate_partitions(
        partitions,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    first_configuration.update(
        {
            "bounded_merge": True,
            "merged_tape_payload_count": len(payloads),
            "target_date": target_date,
        }
    )
    expected_snapshot_partition_count = sum(
        int((payload.get("coverage") or {}).get("expected_snapshot_partition_count") or 0)
        for payload in payloads
    )
    observed_expected_snapshot_partition_count = sum(
        int(
            (payload.get("coverage") or {}).get(
                "observed_expected_snapshot_partition_count"
            )
            or 0
        )
        for payload in payloads
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "configuration": first_configuration,
        "inputs": {
            "source_paths": sorted(set(source_paths)),
            "source_path_count": len(set(source_paths)),
            "row_count": sum(int((payload.get("inputs") or {}).get("row_count") or 0) for payload in payloads),
            "synthetic_missing_variant_band_row_count": sum(
                int((payload.get("inputs") or {}).get("synthetic_missing_variant_band_row_count") or 0)
                for payload in payloads
            ),
            "synthetic_missing_snapshot_band_row_count": sum(
                int((payload.get("inputs") or {}).get("synthetic_missing_snapshot_band_row_count") or 0)
                for payload in payloads
            ),
            "expected_snapshot_source_paths": sorted(
                set(str(path) for path in expected_snapshot_source_paths)
            ),
        },
        "coverage": {
            "partition_count": len(partitions),
            "eligible_partition_count": len(eligible),
            "valid_prediction_partition_count": len(valid),
            "missing_or_invalid_partition_count": len(eligible) - len(valid),
            "unresolved_settlement_partition_count": len(unresolved_settlement),
            "eligible_prediction_coverage": len(valid) / len(eligible) if eligible else 0.0,
            "eligible_band_count": sum(
                int((payload.get("coverage") or {}).get("eligible_band_count") or 0)
                for payload in payloads
            ),
            "predicted_band_row_count": sum(
                int((payload.get("coverage") or {}).get("predicted_band_row_count") or 0)
                for payload in payloads
            ),
            "missing_prediction_band_count": sum(
                int((payload.get("coverage") or {}).get("missing_prediction_band_count") or 0)
                for payload in payloads
            ),
            "unsupported_runtime_skip_band_count": sum(
                int((payload.get("coverage") or {}).get("unsupported_runtime_skip_band_count") or 0)
                for payload in payloads
            ),
            "missing_expected_variant_partition_count": sum(
                int((payload.get("coverage") or {}).get("missing_expected_variant_partition_count") or 0)
                for payload in payloads
            ),
            "expected_snapshot_partition_count": expected_snapshot_partition_count,
            "observed_expected_snapshot_partition_count": observed_expected_snapshot_partition_count,
            "missing_expected_snapshot_partition_count": sum(
                int((payload.get("coverage") or {}).get("missing_expected_snapshot_partition_count") or 0)
                for payload in payloads
            ),
            "unexpected_variant_snapshot_partition_count": sum(
                int((payload.get("coverage") or {}).get("unexpected_variant_snapshot_partition_count") or 0)
                for payload in payloads
            ),
            "missing_expected_snapshot_band_count": sum(
                int((payload.get("coverage") or {}).get("missing_expected_snapshot_band_count") or 0)
                for payload in payloads
            ),
            "expected_snapshot_partition_coverage": (
                observed_expected_snapshot_partition_count
                / expected_snapshot_partition_count
                if expected_snapshot_partition_count
                else 0.0
            ),
            "skip_failure_reasons": dict(sorted(skip_reasons.items())),
            "market_day_count": len({(item["target_date"], item["market_id"]) for item in eligible}),
            "fleet_date_count": len({item["target_date"] for item in eligible}),
        },
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "lane_summaries": _merged_lane_summaries(
            partitions,
            variant_summaries,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed,
        ),
        "variant_release_summaries": variant_summaries,
        "partitions": partitions,
    }


def operational_status_payload(
    status: str,
    reason: str,
    *,
    target_date: str | None = None,
    source_paths: Sequence[str] | None = None,
    blockers: Sequence[Mapping[str, Any]] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Create a canonical no-score artifact for SKIPPED or preflight BLOCK."""
    if status not in {"SKIPPED", "BLOCK"}:
        raise ValueError("operational scorecard status must be SKIPPED or BLOCK")
    blocker_rows = [dict(row) for row in blockers or []]
    if status == "BLOCK" and not blocker_rows:
        blocker_rows = [_issue("operational_preflight_block", reason)]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "reason": reason,
        "configuration": {
            "target_date": target_date,
            "evidence_unit": "complete_variant_release_probability_partition",
            "independent_evidence_unit": "market_day_and_fleet_date",
            "aggregate_weighting": "equal_market_day",
            "expected_partition_contract": "unavailable",
            "bounded_merge": True,
        },
        "inputs": {
            "source_paths": list(source_paths or []),
            "source_path_count": len(source_paths or []),
            "row_count": 0,
            "synthetic_missing_variant_band_row_count": 0,
            "synthetic_missing_snapshot_band_row_count": 0,
            "expected_snapshot_source_paths": [],
        },
        "coverage": {
            "partition_count": 0,
            "eligible_partition_count": 0,
            "valid_prediction_partition_count": 0,
            "missing_or_invalid_partition_count": 0,
            "unresolved_settlement_partition_count": 0,
            "eligible_prediction_coverage": 0.0,
            "eligible_band_count": 0,
            "predicted_band_row_count": 0,
            "missing_prediction_band_count": 0,
            "unsupported_runtime_skip_band_count": 0,
            "missing_expected_variant_partition_count": 0,
            "expected_snapshot_partition_count": 0,
            "observed_expected_snapshot_partition_count": 0,
            "missing_expected_snapshot_partition_count": 0,
            "unexpected_variant_snapshot_partition_count": 0,
            "missing_expected_snapshot_band_count": 0,
            "expected_snapshot_partition_coverage": 0.0,
            "skip_failure_reasons": {},
            "market_day_count": 0,
            "fleet_date_count": 0,
        },
        "blocker_count": len(blocker_rows),
        "first_blocker": blocker_rows[0] if blocker_rows else None,
        "blockers": blocker_rows,
        "lane_summaries": [],
        "variant_release_summaries": [],
        "partitions": [],
    }


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for field in ("rows", "predictions", "partitions", "records"):
        values = payload.get(field)
        if isinstance(values, list):
            return [dict(row) for row in values if isinstance(row, dict)]
    return [dict(payload)]


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    """Read CSV, JSONL, or JSON prediction rows with source provenance."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
    elif suffix in {".jsonl", ".ndjson"}:
        rows = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        rows.append(dict(payload))
    elif suffix == ".json":
        rows = _read_json_rows(path)
    else:
        raise ValueError(f"unsupported prediction row format: {path}")
    for number, row in enumerate(rows, start=2 if suffix == ".csv" else 1):
        row["_source_path"] = str(path)
        row["_row_number"] = number
    return rows


def discover_tapes(snapshots_root: str | Path) -> list[Path]:
    return sorted(Path(snapshots_root).glob("*/variant_predictions_long.csv"))


def read_label_csv(path: str | Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    if not path:
        return {}
    if not Path(path).is_file():
        return {}
    labels = {}
    for row in read_rows(path):
        key = (
            str(_first(row, "target_date", "market_date") or ""),
            str(_first(row, "market_id", "location_id") or ""),
        )
        if all(key):
            labels[key] = row
    return labels


def load_tape_inputs(
    paths: Sequence[str | Path],
) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    source_labels: dict[str, Mapping[str, Any]] = {}
    used_paths = []
    for value in paths:
        path = Path(value)
        used_paths.append(str(path))
        rows.extend(read_rows(path))
        label = load_market_day_label(path.parent)
        if isinstance(label, dict):
            source_labels[str(path)] = label
    return rows, source_labels, used_paths


def load_snapshot_partition_contracts(
    paths: Sequence[str | Path],
    *,
    source_labels: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load the independent sibling snapshot band universe for each tape.

    Variant rows alone cannot prove that a band or an entire snapshot partition
    did not disappear. The canonical ``snapshots_long.csv`` tape supplies that
    expected universe without borrowing candidate probabilities.
    """

    source_labels = source_labels or {}
    contracts: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for value in paths:
        tape_path = Path(value)
        snapshot_path = tape_path.parent / "snapshots_long.csv"
        if not snapshot_path.is_file():
            blockers.append(
                _issue(
                    "expected_snapshot_tape_missing",
                    "sibling snapshots_long.csv is required to prove complete live partitions",
                    variant_tape=str(tape_path),
                    snapshot_tape=str(snapshot_path),
                )
            )
            continue
        label = source_labels.get(str(tape_path))
        if not isinstance(label, Mapping):
            label = load_market_day_label(tape_path.parent)
        target_date = str((label or {}).get("target_date") or "").strip()
        market_id = str((label or {}).get("market_id") or "").strip()
        if not target_date or not market_id:
            blockers.append(
                _issue(
                    "expected_snapshot_identity_missing",
                    "settled market-day identity is required for the sibling snapshot contract",
                    variant_tape=str(tape_path),
                    snapshot_tape=str(snapshot_path),
                )
            )
            continue
        by_snapshot: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for raw in read_rows(snapshot_path):
            evaluation_type, evaluation_id = _evaluation_point(raw)
            band_identity, kind, band_value, band_value_hi = _band_identity(raw)
            if evaluation_id == "__missing_evaluation_point__" or band_identity == "__missing_band__":
                blockers.append(
                    _issue(
                        "expected_snapshot_row_invalid",
                        "sibling snapshot row lacks a canonical snapshot or band identity",
                        snapshot_tape=str(snapshot_path),
                        row_number=raw.get("_row_number"),
                    )
                )
                continue
            outcome, outcome_source = _row_outcome(raw, label)
            existing = by_snapshot[evaluation_id].get(band_identity)
            band = {
                "band_identity": band_identity,
                "band_key": str(_first(raw, "band_key", "range_label") or "").strip(),
                "range_label": str(raw.get("range_label") or "").strip(),
                "bin_kind": kind,
                "bin_value": band_value,
                "bin_value_hi": band_value_hi,
                "serving_probability": _finite_probability(
                    _first(raw, "model_probability", "serving_model_probability")
                ),
                "market_probability": _finite_probability(
                    _first(raw, "market_yes", "market_probability")
                ),
                "outcome": outcome,
                "outcome_source": outcome_source,
                "settlement_countable": _label_countable(raw, label, outcome),
                "evaluation_point_type": evaluation_type,
            }
            if existing is not None:
                blockers.append(
                    _issue(
                        "expected_snapshot_duplicate_band",
                        "sibling snapshot tape duplicates a band within one snapshot",
                        snapshot_tape=str(snapshot_path),
                        evaluation_point_id=evaluation_id,
                        band_identity=band_identity,
                    )
                )
                continue
            by_snapshot[evaluation_id][band_identity] = band
        for evaluation_id, bands in sorted(by_snapshot.items()):
            evaluation_types = {
                str(row.get("evaluation_point_type") or "snapshot")
                for row in bands.values()
            }
            contracts.append(
                {
                    "target_date": target_date,
                    "market_id": market_id,
                    "evaluation_point_type": (
                        next(iter(evaluation_types)) if len(evaluation_types) == 1 else "snapshot"
                    ),
                    "evaluation_point_id": evaluation_id,
                    "bands": [bands[key] for key in sorted(bands)],
                    "source_path": str(snapshot_path),
                }
            )
        if not by_snapshot:
            blockers.append(
                _issue(
                    "expected_snapshot_tape_empty",
                    "sibling snapshot tape contains no canonical partitions",
                    snapshot_tape=str(snapshot_path),
                )
            )
    return _normalize_expected_partitions(contracts), blockers


def _parity_probability(row: Mapping[str, Any], side: str) -> float | None:
    if side == "served":
        value = _first(row, "served_probability", "variant_probability", "probability")
    else:
        value = _first(row, "replay_probability", "variant_probability", "probability")
    return _finite_probability(value)


def _normalize_parity_row(raw: Mapping[str, Any], side: str) -> dict[str, Any]:
    normalized = normalize_score_row(raw, source_path=str(raw.get("_source_path") or ""))
    normalized["probability"] = _parity_probability(raw, side)
    normalized["captured_input_hash"] = str(
        _first(raw, "captured_input_hash", "replay_input_hash", "input_hash") or ""
    ).strip()
    normalized["release_manifest_sha256"] = str(
        _first(
            raw,
            "release_manifest_sha256",
            "manifest_sha256",
            "active_manifest_sha256",
        )
        or ""
    ).strip()
    return normalized


def _parity_row_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return _key(row, PARTITION_KEY_FIELDS) + (row.get("band_identity"),)


def compare_replay_to_served(
    served_rows: Iterable[Mapping[str, Any]],
    replay_rows: Iterable[Mapping[str, Any]],
    *,
    probability_atol: float = DEFAULT_PARITY_ATOL,
    probability_rtol: float = DEFAULT_PARITY_RTOL,
    generated_at_utc: str | None = None,
    served_source: str = "",
    replay_source: str = "",
) -> dict[str, Any]:
    """Compare exact captured-input replay output with served tape output."""
    served = [_normalize_parity_row(row, "served") for row in served_rows]
    replay = [_normalize_parity_row(row, "replay") for row in replay_rows]
    served_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    replay_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in served:
        served_by_key[_parity_row_key(row)].append(row)
    for row in replay:
        replay_by_key[_parity_row_key(row)].append(row)

    mismatches: list[dict[str, Any]] = []
    identity_rows = [*served, *replay]
    release_ids = {
        str(row.get("release_id") or "")
        for row in identity_rows
        if row.get("release_id_source") == "explicit"
    }
    manifest_hashes = {
        str(row.get("release_manifest_sha256") or "")
        for row in identity_rows
        if row.get("release_manifest_sha256")
    }
    if not identity_rows or any(
        row.get("release_id_source") != "explicit" for row in identity_rows
    ):
        mismatches.append(
            _issue(
                "parity_release_id_missing",
                "every served and replay row must explicitly name one immutable release_id",
            )
        )
    if len(release_ids) > 1:
        mismatches.append(
            _issue(
                "parity_release_id_mixed",
                "served and replay rows contain multiple release identities",
                release_ids=sorted(release_ids),
            )
        )
    if not identity_rows or any(
        not row.get("release_manifest_sha256") for row in identity_rows
    ):
        mismatches.append(
            _issue(
                "parity_release_manifest_hash_missing",
                "every served and replay row must name the immutable release manifest SHA-256",
            )
        )
    if len(manifest_hashes) > 1:
        mismatches.append(
            _issue(
                "parity_release_manifest_hash_mixed",
                "served and replay rows contain multiple release manifest hashes",
                manifest_sha256_values=sorted(manifest_hashes),
            )
        )
    for side, index in (("served", served_by_key), ("replay", replay_by_key)):
        for key, items in index.items():
            if len(items) > 1:
                mismatches.append(
                    _issue("duplicate_parity_key", f"{side} input has {len(items)} rows for one parity key", side=side, key=list(key))
                )
    served_keys = set(served_by_key)
    replay_keys = set(replay_by_key)
    for key in sorted(served_keys - replay_keys, key=str):
        mismatches.append(_issue("missing_replay_row", "served row has no captured-input replay row", key=list(key)))
    for key in sorted(replay_keys - served_keys, key=str):
        mismatches.append(_issue("unexpected_replay_row", "replay row has no served counterpart", key=list(key)))

    compared_rows = 0
    compared_probabilities = 0
    maximum_probability_error = 0.0
    for key in sorted(served_keys & replay_keys, key=str):
        if len(served_by_key[key]) != 1 or len(replay_by_key[key]) != 1:
            continue
        served_row = served_by_key[key][0]
        replay_row = replay_by_key[key][0]
        compared_rows += 1
        if served_row["release_id_source"] != "explicit" or replay_row["release_id_source"] != "explicit":
            mismatches.append(_issue("explicit_release_id_required", "served and replay rows must pin the same immutable release_id", key=list(key)))
        for side, row in (("served", served_row), ("replay", replay_row)):
            if not row.get("live_runtime") and not row.get("route_id"):
                mismatches.append(
                    _issue(
                        "serving_route_identity_missing",
                        f"{side} row has neither live_runtime nor route_id",
                        side=side,
                        key=list(key),
                    )
                )
            for field in ("model_version", "artifact_hash", "postprocess_config_hash"):
                if not row.get(field):
                    mismatches.append(
                        _issue(
                            "serving_identity_missing",
                            f"{side} row is missing required {field}",
                            side=side,
                            key=list(key),
                            field=field,
                        )
                    )
        served_hash = served_row["captured_input_hash"]
        replay_hash = replay_row["captured_input_hash"]
        if not served_hash or not replay_hash:
            mismatches.append(_issue("captured_input_hash_missing", "exact replay requires captured input hashes on both rows", key=list(key)))
        elif served_hash != replay_hash:
            mismatches.append(
                _issue(
                    "captured_input_hash_mismatch",
                    "served and replay rows do not use the same captured input",
                    key=list(key),
                    served=served_hash,
                    replay=replay_hash,
                )
            )
        if served_row["prediction_status"] != replay_row["prediction_status"]:
            mismatches.append(
                _issue(
                    "skip_decision_mismatch",
                    "served and replay prediction status differ",
                    key=list(key),
                    served=served_row["prediction_status"],
                    replay=replay_row["prediction_status"],
                )
            )
        if served_row["failure_reason"] != replay_row["failure_reason"]:
            mismatches.append(
                _issue(
                    "skip_reason_mismatch",
                    "served and replay failure/skip reasons differ",
                    key=list(key),
                    served=served_row["failure_reason"],
                    replay=replay_row["failure_reason"],
                )
            )
        for field in PARITY_IDENTITY_FIELDS:
            if served_row.get(field) != replay_row.get(field):
                mismatches.append(
                    _issue(
                        "serving_identity_mismatch",
                        f"served and replay {field} differ",
                        key=list(key),
                        field=field,
                        served=served_row.get(field),
                        replay=replay_row.get(field),
                    )
                )
        if served_row["prediction_status"] == "predicted" and replay_row["prediction_status"] == "predicted":
            served_probability = served_row["probability"]
            replay_probability = replay_row["probability"]
            if served_probability is None or replay_probability is None:
                mismatches.append(_issue("parity_probability_missing", "predicted parity rows require finite probabilities", key=list(key)))
            else:
                compared_probabilities += 1
                error = abs(served_probability - replay_probability)
                maximum_probability_error = max(maximum_probability_error, error)
                if not math.isclose(
                    served_probability,
                    replay_probability,
                    abs_tol=probability_atol,
                    rel_tol=probability_rtol,
                ):
                    mismatches.append(
                        _issue(
                            "probability_mismatch",
                            "replayed probability exceeds deterministic tolerance",
                            key=list(key),
                            served=served_probability,
                            replay=replay_probability,
                            absolute_error=error,
                        )
                    )
    if compared_rows == 0:
        mismatches.insert(0, _issue("no_comparable_rows", "served and replay inputs contain no one-to-one comparable rows"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "mode": "captured_input_replay_vs_served_parity",
        "status": "PASS" if not mismatches else "BLOCK",
        "release_id": next(iter(release_ids)) if len(release_ids) == 1 else "",
        "manifest_sha256": (
            next(iter(manifest_hashes)) if len(manifest_hashes) == 1 else ""
        ),
        "inputs": {
            "served_source": served_source,
            "replay_source": replay_source,
            "served_row_count": len(served),
            "replay_row_count": len(replay),
        },
        "tolerances": {
            "probability_absolute": probability_atol,
            "probability_relative": probability_rtol,
            "identity_and_skip_decisions": "exact",
            "captured_input_hash": "exact_required",
        },
        "summary": {
            "compared_row_count": compared_rows,
            "compared_probability_count": compared_probabilities,
            "maximum_probability_absolute_error": maximum_probability_error,
            "mismatch_count": len(mismatches),
        },
        "first_mismatch": mismatches[0] if mismatches else None,
        "mismatches": mismatches,
    }


def _prediction_path_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parity_paths(values: str | Path | Sequence[str | Path] | None) -> list[Path]:
    if values is None or values == "":
        return []
    if isinstance(values, (str, Path)):
        return [Path(values)]
    return [Path(value) for value in values if str(value or "").strip()]


def _append_parity_issues(
    payload: dict[str, Any],
    issues: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    mismatches = list(payload.get("mismatches") or [])
    mismatches.extend(dict(issue) for issue in issues)
    payload["mismatches"] = mismatches
    payload["first_mismatch"] = mismatches[0] if mismatches else None
    payload.setdefault("summary", {})["mismatch_count"] = len(mismatches)
    payload["status"] = "PASS" if not mismatches else "BLOCK"
    return payload


def build_captured_input_replay_parity(
    served_paths: str | Path | Sequence[str | Path] | None,
    replay_paths: str | Path | Sequence[str | Path] | None,
    *,
    expected_release_id: str = "",
    expected_manifest_sha256: str = "",
    max_input_age_hours: float = DEFAULT_PARITY_MAX_INPUT_AGE_HOURS,
    probability_atol: float = DEFAULT_PARITY_ATOL,
    probability_rtol: float = DEFAULT_PARITY_RTOL,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load explicit served/replay rows and apply the canonical comparator.

    This function never invents replay output. Missing production replay rows
    produce an actionable BLOCK directing the operator to generate rows from
    the exact captured inputs under the verified release.
    """

    if max_input_age_hours <= 0:
        raise ValueError("max_input_age_hours must be positive")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    source_rows: dict[str, list[dict[str, Any]]] = {"served": [], "replay": []}
    source_records: dict[str, list[dict[str, Any]]] = {"served": [], "replay": []}
    issues: list[dict[str, Any]] = []
    for side, configured in (
        ("served", _parity_paths(served_paths)),
        ("replay", _parity_paths(replay_paths)),
    ):
        if not configured:
            issues.append(
                _issue(
                    f"{side}_parity_input_not_configured",
                    f"no explicit {side} parity row input was configured",
                    next_action=(
                        "generate replay rows from replay_inputs.jsonl under the exact "
                        "verified release; do not infer or fabricate replay parity"
                        if side == "replay"
                        else "provide the exact served variant prediction rows captured live"
                    ),
                )
            )
        for path in configured:
            record = {
                "path": str(path),
                "exists": path.exists(),
                "sha256": None,
                "modified_at_utc": None,
                "age_hours": None,
                "max_age_hours": float(max_input_age_hours),
                "row_count": 0,
                "status": "BLOCK",
            }
            source_records[side].append(record)
            if not path.exists() or not path.is_file() or path.is_symlink():
                issues.append(
                    _issue(
                        f"{side}_parity_input_missing",
                        f"{side} parity input must be a regular non-symlink file: {path}",
                        path=str(path),
                        next_action=(
                            "generate captured-input replay rows with the exact active release; "
                            "do not infer or fabricate replay parity"
                            if side == "replay"
                            else "preserve and provide the live served prediction rows"
                        ),
                    )
                )
                continue
            try:
                stat = path.stat()
                modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                age_hours = (current - modified).total_seconds() / 3600.0
                record.update(
                    {
                        "sha256": _prediction_path_sha256(path),
                        "modified_at_utc": modified.isoformat(),
                        "age_hours": age_hours,
                    }
                )
                if age_hours < -(5.0 / 60.0):
                    issues.append(
                        _issue(
                            f"{side}_parity_input_from_future",
                            f"{side} parity input timestamp is in the future",
                            path=str(path),
                            age_hours=age_hours,
                        )
                    )
                elif age_hours > max_input_age_hours:
                    issues.append(
                        _issue(
                            f"{side}_parity_input_stale",
                            f"{side} parity input exceeds the freshness window",
                            path=str(path),
                            age_hours=age_hours,
                            max_age_hours=float(max_input_age_hours),
                            next_action="regenerate parity rows from current captured inputs",
                        )
                    )
                rows = read_rows(path)
                source_rows[side].extend(rows)
                record["row_count"] = len(rows)
                record["status"] = "PASS"
            except (OSError, UnicodeDecodeError, ValueError, csv.Error, json.JSONDecodeError) as exc:
                issues.append(
                    _issue(
                        f"{side}_parity_input_unreadable",
                        f"cannot read {side} parity input: {type(exc).__name__}: {exc}",
                        path=str(path),
                    )
                )
    payload = compare_replay_to_served(
        source_rows["served"],
        source_rows["replay"],
        probability_atol=probability_atol,
        probability_rtol=probability_rtol,
        generated_at_utc=current.isoformat(),
        served_source=",".join(str(path) for path in _parity_paths(served_paths)),
        replay_source=",".join(str(path) for path in _parity_paths(replay_paths)),
    )
    payload["inputs"].update(
        {
            "source_contract": "explicit_captured_input_rows",
            "max_input_age_hours": float(max_input_age_hours),
            "served_sources": source_records["served"],
            "replay_sources": source_records["replay"],
        }
    )
    expected_release = str(expected_release_id or "").strip()
    expected_manifest = str(expected_manifest_sha256 or "").strip()
    if not expected_release or not expected_manifest:
        issues.append(
            _issue(
                "expected_release_identity_unavailable",
                "verified active release_id and manifest SHA-256 are required before parity",
                expected_release_id=expected_release or None,
                expected_manifest_sha256=expected_manifest or None,
                next_action="repair verified active-release serving bindings, then regenerate replay rows",
            )
        )
    else:
        if payload.get("release_id") != expected_release:
            issues.append(
                _issue(
                    "parity_release_identity_mismatch",
                    "parity rows do not match the verified active release_id",
                    expected_release_id=expected_release,
                    actual_release_id=payload.get("release_id") or None,
                )
            )
        if payload.get("manifest_sha256") != expected_manifest:
            issues.append(
                _issue(
                    "parity_manifest_identity_mismatch",
                    "parity rows do not match the verified active release manifest",
                    expected_manifest_sha256=expected_manifest,
                    actual_manifest_sha256=payload.get("manifest_sha256") or None,
                )
            )
    payload["expected_release_identity"] = {
        "release_id": expected_release or None,
        "manifest_sha256": expected_manifest or None,
    }
    return _append_parity_issues(payload, issues)


def persist_captured_input_replay_parity(
    served_paths: str | Path | Sequence[str | Path] | None,
    replay_paths: str | Path | Sequence[str | Path] | None,
    *,
    json_out: str | Path = DEFAULT_PARITY_JSON_OUT,
    report_out: str | Path = DEFAULT_PARITY_REPORT_OUT,
    protected_paths: str | Path | Sequence[str | Path] | None = None,
    protected_roots: str | Path | Sequence[str | Path] | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path | None, Path | None]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    protected_issue = _protected_parity_output_issue(
        json_path,
        report_path,
        protected_paths=protected_paths,
        protected_roots=protected_roots,
    )
    if protected_issue is not None:
        return _in_memory_parity_output_block(
            protected_issue,
            served_paths=served_paths,
            replay_paths=replay_paths,
            json_path=json_path,
            report_path=report_path,
            expected_release_id=str(kwargs.get("expected_release_id") or ""),
            expected_manifest_sha256=str(
                kwargs.get("expected_manifest_sha256") or ""
            ),
        )
    payload = build_captured_input_replay_parity(
        served_paths,
        replay_paths,
        **kwargs,
    )
    payload["outputs"] = {
        "json_path": str(json_path),
        "report_path": str(report_path),
        "persistence_status": "PENDING",
    }
    input_paths = {
        path.expanduser().resolve(strict=False)
        for path in [*_parity_paths(served_paths), *_parity_paths(replay_paths)]
    }
    resolved_json = json_path.expanduser().resolve(strict=False)
    resolved_report = report_path.expanduser().resolve(strict=False)
    collision = None
    if resolved_json == resolved_report:
        collision = "parity JSON and report outputs must be distinct"
    elif resolved_json in input_paths or resolved_report in input_paths:
        collision = "parity outputs must not overwrite served or replay input rows"
    if collision:
        _append_parity_issues(
            payload,
            [
                _issue(
                    "parity_output_collision",
                    collision,
                    json_out=str(json_path),
                    report_out=str(report_path),
                    next_action="choose dedicated parity evidence outputs outside every input path",
                )
            ],
        )
        payload["outputs"]["persistence_status"] = "BLOCK"
        if resolved_json not in input_paths:
            persisted = _persist_current_parity_block(payload, json_path, None)
            if not persisted:
                payload["outputs"]["json_path"] = None
            payload["outputs"]["report_path"] = None
            return payload, json_path if persisted else None, None
        payload["outputs"]["json_path"] = None
        payload["outputs"]["report_path"] = None
        return payload, None, None
    try:
        payload["outputs"]["persistence_status"] = "PASS"
        json_path, report_path = write_outputs(
            payload,
            json_path,
            report_path,
            parity=True,
        )
    except Exception as exc:  # noqa: BLE001 - missing proof must block promotion
        _append_parity_issues(
            payload,
            [
                _issue(
                    "parity_output_persistence_failed",
                    f"cannot persist parity output: {type(exc).__name__}: {exc}",
                    json_out=str(json_out),
                    report_out=str(report_out),
                    next_action="repair the evidence output path before any heavy work starts",
                )
            ],
        )
        payload["outputs"]["persistence_status"] = "BLOCK"
        json_persisted = _persist_current_parity_block(
            payload,
            json_path,
            report_path,
        )
        if not json_persisted:
            payload["outputs"]["json_path"] = None
        if not report_path.exists():
            payload["outputs"]["report_path"] = None
        return (
            payload,
            json_path if json_persisted else None,
            report_path if report_path.exists() else None,
        )
    return payload, json_path, report_path


def _protected_parity_output_issue(
    json_path: Path,
    report_path: Path,
    *,
    protected_paths: str | Path | Sequence[str | Path] | None,
    protected_roots: str | Path | Sequence[str | Path] | None,
) -> dict[str, Any] | None:
    """Return a blocker before any protected output path can be opened."""

    outputs = {
        "json_out": json_path.expanduser().resolve(strict=False),
        "report_out": report_path.expanduser().resolve(strict=False),
    }
    exact = {
        path.expanduser().resolve(strict=False)
        for path in _parity_paths(protected_paths)
    }
    roots = {
        path.expanduser().resolve(strict=False)
        for path in _parity_paths(protected_roots)
    }
    collisions: list[dict[str, str]] = []
    for output_name, output_path in outputs.items():
        if output_path in exact:
            collisions.append(
                {
                    "output": output_name,
                    "path": str(output_path),
                    "protected_by": "exact_path",
                }
            )
        for root in roots:
            if output_path == root or root in output_path.parents:
                collisions.append(
                    {
                        "output": output_name,
                        "path": str(output_path),
                        "protected_by": f"root:{root}",
                    }
                )
    if not collisions:
        return None
    return _issue(
        "parity_output_protected_path",
        "parity evidence outputs must not alias the active pointer or release tree",
        collisions=collisions,
        next_action="choose dedicated parity evidence outputs outside the immutable release tree",
    )


def _in_memory_parity_output_block(
    issue: Mapping[str, Any],
    *,
    served_paths: str | Path | Sequence[str | Path] | None,
    replay_paths: str | Path | Sequence[str | Path] | None,
    json_path: Path,
    report_path: Path,
    expected_release_id: str,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], None, None]:
    """Build a terminal blocker without touching either configured output."""

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "captured_input_replay_vs_served_parity",
        "status": "BLOCK",
        "release_id": "",
        "manifest_sha256": "",
        "expected_release_identity": {
            "release_id": expected_release_id or None,
            "manifest_sha256": expected_manifest_sha256 or None,
        },
        "inputs": {
            "source_contract": "explicit_captured_input_rows",
            "served_sources": [str(path) for path in _parity_paths(served_paths)],
            "replay_sources": [str(path) for path in _parity_paths(replay_paths)],
        },
        "summary": {
            "compared_row_count": 0,
            "compared_probability_count": 0,
            "maximum_probability_absolute_error": 0.0,
            "mismatch_count": 1,
        },
        "first_mismatch": dict(issue),
        "mismatches": [dict(issue)],
        "outputs": {
            "json_path": None,
            "report_path": None,
            "configured_json_path": str(json_path),
            "configured_report_path": str(report_path),
            "persistence_status": "BLOCK",
        },
    }
    return payload, None, None


def _persist_current_parity_block(
    payload: Mapping[str, Any],
    json_path: Path,
    report_path: Path | None,
) -> bool:
    """Replace an older PASS with the current BLOCK, or remove it fail-closed."""

    persisted = False
    try:
        write_json_atomic(json_path, payload, trailing_newline=True)
        persisted = True
    except Exception:  # noqa: BLE001 - stale PASS must not survive
        try:
            json_path.unlink()
        except (FileNotFoundError, OSError):
            pass
    if report_path is not None:
        try:
            _atomic_write_text(report_path, render_parity(payload))
        except Exception:  # noqa: BLE001 - JSON is the canonical gate input
            try:
                report_path.unlink()
            except (FileNotFoundError, OSError):
                pass
    return persisted


def persist_captured_input_replay_parity_failure(
    error: Exception | str,
    *,
    json_out: str | Path = DEFAULT_PARITY_JSON_OUT,
    report_out: str | Path = DEFAULT_PARITY_REPORT_OUT,
    expected_release_id: str = "",
    expected_manifest_sha256: str = "",
    protected_paths: str | Path | Sequence[str | Path] | None = None,
    protected_roots: str | Path | Sequence[str | Path] | None = None,
) -> tuple[dict[str, Any], Path | None, Path | None]:
    """Persist a current-run BLOCK when parity preflight itself raises."""

    json_path = Path(json_out)
    report_path = Path(report_out)
    protected_issue = _protected_parity_output_issue(
        json_path,
        report_path,
        protected_paths=protected_paths,
        protected_roots=protected_roots,
    )
    if protected_issue is not None:
        return _in_memory_parity_output_block(
            protected_issue,
            served_paths=None,
            replay_paths=None,
            json_path=json_path,
            report_path=report_path,
            expected_release_id=str(expected_release_id or ""),
            expected_manifest_sha256=str(expected_manifest_sha256 or ""),
        )

    issue = _issue(
        "parity_preflight_exception",
        f"captured-input parity preflight failed: {type(error).__name__}: {error}",
        next_action="repair parity inputs/configuration and rerun before any candidate work",
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "captured_input_replay_vs_served_parity",
        "status": "BLOCK",
        "release_id": "",
        "manifest_sha256": "",
        "expected_release_identity": {
            "release_id": str(expected_release_id or "") or None,
            "manifest_sha256": str(expected_manifest_sha256 or "") or None,
        },
        "inputs": {
            "source_contract": "explicit_captured_input_rows",
            "served_source": "",
            "replay_source": "",
            "served_row_count": 0,
            "replay_row_count": 0,
            "served_sources": [],
            "replay_sources": [],
        },
        "tolerances": {
            "probability_absolute": DEFAULT_PARITY_ATOL,
            "probability_relative": DEFAULT_PARITY_RTOL,
            "identity_and_skip_decisions": "exact",
            "captured_input_hash": "exact_required",
        },
        "summary": {
            "compared_row_count": 0,
            "compared_probability_count": 0,
            "maximum_probability_absolute_error": 0.0,
            "mismatch_count": 1,
        },
        "first_mismatch": issue,
        "mismatches": [issue],
        "outputs": {
            "json_path": str(json_out),
            "report_path": str(report_out),
            "persistence_status": "BLOCK",
        },
    }
    persisted = _persist_current_parity_block(payload, json_path, report_path)
    if not persisted:
        payload["outputs"]["json_path"] = None
    if not report_path.exists():
        payload["outputs"]["report_path"] = None
    return (
        payload,
        json_path if persisted else None,
        report_path if report_path.exists() else None,
    )


def render_scorecard(payload: Mapping[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    lines = [
        "# Live Variant Settlement Scorecard",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Schema: `{payload.get('schema_version')}`",
        f"Status: **{payload.get('status')}**",
        f"Reason: `{payload.get('reason') or '-'}`",
        "",
        "## Coverage And Integrity",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Tape rows", (payload.get("inputs") or {}).get("row_count")],
            ["Eligible partitions", coverage.get("eligible_partition_count")],
            ["Valid prediction partitions", coverage.get("valid_prediction_partition_count")],
            ["Eligible prediction coverage", fmt_pct(coverage.get("eligible_prediction_coverage"))],
            ["Missing/invalid partitions", coverage.get("missing_or_invalid_partition_count")],
            ["Expected sibling snapshots", coverage.get("expected_snapshot_partition_count")],
            ["Missing sibling snapshots", coverage.get("missing_expected_snapshot_partition_count")],
            ["Bands absent across all variants", coverage.get("missing_expected_snapshot_band_count")],
            ["Unsupported-runtime skip bands", coverage.get("unsupported_runtime_skip_band_count")],
            ["Market-days", coverage.get("market_day_count")],
            ["Fleet dates", coverage.get("fleet_date_count")],
            ["Blockers", payload.get("blocker_count")],
        ],
    )
    lines += [
        "",
        "## Variant And Release Metrics",
        "",
        "Headline metrics weight market-days equally. Fleet-date means and equal-partition diagnostics are shown separately; the latter do not increase independent evidence.",
        "",
    ]
    rows = []
    for summary in payload.get("variant_release_summaries") or []:
        metrics = summary.get("metrics") or {}
        views = summary.get("metric_views") or {}
        fleet_metrics = views.get("equal_fleet_date") or {}
        partition_metrics = views.get("equal_partition_diagnostic") or {}
        brier_interval = (
            (views.get("date_clustered_intervals") or {}).get("metrics") or {}
        ).get("brier") or {}
        brier_ci = (
            f"[{fmt_num(brier_interval.get('lower'), 6)}, "
            f"{fmt_num(brier_interval.get('upper'), 6)}]"
            if brier_interval
            else "-"
        )
        rows.append(
            [
                summary.get("evidence_lane"),
                summary.get("variant_id"),
                summary.get("release_id"),
                summary.get("valid_partition_count"),
                summary.get("market_day_count"),
                summary.get("fleet_date_count"),
                fmt_num(metrics.get("brier"), 6),
                fmt_num(fleet_metrics.get("brier"), 6),
                fmt_num(partition_metrics.get("brier"), 6),
                brier_ci,
                fmt_num(metrics.get("log_loss"), 6),
                fmt_num(metrics.get("top1_hit"), 4),
                fmt_num(metrics.get("winner_rank"), 3),
                fmt_num(metrics.get("rps"), 6),
                fmt_num(metrics.get("ece"), 6),
            ]
        )
    lines += markdown_table(
        ["Lane", "Variant", "Release", "Partitions", "Market-days", "Fleet dates", "Brier (market-day)", "Brier (fleet-date)", "Brier (partition diagnostic)", "Brier 95% date-cluster CI", "Log loss", "Top-1", "Winner rank", "RPS", "ECE"],
        rows or [["-", "-", "-", 0, 0, 0, "-", "-", "-", "-", "-", "-", "-", "-", "-"]],
    )
    lines += ["", "## Skip And Failure Reasons", ""]
    lines += markdown_table(
        ["Reason", "Band rows"],
        [[reason, count] for reason, count in (coverage.get("skip_failure_reasons") or {}).items()]
        or [["none", 0]],
    )
    lines += ["", "## Gate Blockers", ""]
    lines += markdown_table(
        ["Code", "Detail"],
        [[item.get("code"), item.get("detail")] for item in payload.get("blockers") or []]
        or [["none", "all eligible partitions passed"]],
    )
    return "\n".join(lines) + "\n"


def render_parity(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Captured-Input Replay / Served Parity",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Schema: `{payload.get('schema_version')}`",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Served rows", (payload.get("inputs") or {}).get("served_row_count")],
            ["Replay rows", (payload.get("inputs") or {}).get("replay_row_count")],
            ["Compared rows", summary.get("compared_row_count")],
            ["Compared probabilities", summary.get("compared_probability_count")],
            ["Maximum absolute error", summary.get("maximum_probability_absolute_error")],
            ["Mismatches", summary.get("mismatch_count")],
        ],
    )
    lines += ["", "## Mismatches", ""]
    lines += markdown_table(
        ["Code", "Detail", "Field"],
        [
            [item.get("code"), item.get("detail"), item.get("field") or "-"]
            for item in payload.get("mismatches") or []
        ]
        or [["none", "exact parity within tolerance", "-"]],
    )
    return "\n".join(lines) + "\n"


def _atomic_write_text(path: str | Path, text: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return output


def write_outputs(
    payload: Mapping[str, Any],
    json_out: str | Path,
    report_out: str | Path,
    *,
    parity: bool = False,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    write_json_atomic(json_path, payload, trailing_newline=True)
    _atomic_write_text(
        report_path,
        render_parity(payload) if parity else render_scorecard(payload),
    )
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score settled live variants or verify captured-input replay parity.")
    commands = parser.add_subparsers(dest="command", required=True)

    score = commands.add_parser("score", help="Build the canonical live-variant settlement scorecard.")
    score.add_argument("--tape", action="append", default=[], help="Prediction tape path; repeat for multiple tapes.")
    score.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    score.add_argument("--labels-csv", default="")
    score.add_argument(
        "--expected-variants-manifest",
        default="",
        help="Release manifest or registry pinning variants expected at every evaluation point.",
    )
    score.add_argument("--simplex-tolerance", type=float, default=DEFAULT_SIMPLEX_TOLERANCE)
    score.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=DEFAULT_CLUSTERED_BOOTSTRAP_ITERATIONS,
    )
    score.add_argument(
        "--bootstrap-seed",
        type=int,
        default=DEFAULT_CLUSTERED_BOOTSTRAP_SEED,
    )
    score.add_argument("--allow-derived-release-id", action="store_true", help="Diagnostic legacy scoring only; explicit release IDs remain required by production gates.")
    score.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    score.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    score.add_argument("--fail-on-block", action="store_true")

    parity = commands.add_parser("parity", help="Compare replay output with served output from identical captured inputs.")
    parity.add_argument("--served", required=True)
    parity.add_argument("--replay", required=True)
    parity.add_argument("--probability-atol", type=float, default=DEFAULT_PARITY_ATOL)
    parity.add_argument("--probability-rtol", type=float, default=DEFAULT_PARITY_RTOL)
    parity.add_argument("--json-out", default=str(DEFAULT_PARITY_JSON_OUT))
    parity.add_argument("--report-out", default=str(DEFAULT_PARITY_REPORT_OUT))
    parity.add_argument("--fail-on-block", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "score":
        paths = [Path(path) for path in args.tape] or discover_tapes(args.snapshots_root)
        labels = read_label_csv(args.labels_csv)
        expected_variants = load_expected_variants(args.expected_variants_manifest)
        child_payloads = []
        for path in paths:
            rows, source_labels, used_paths = load_tape_inputs([path])
            expected_partitions, partition_blockers = load_snapshot_partition_contracts(
                [path],
                source_labels=source_labels,
            )
            child_payloads.append(
                build_scorecard(
                    rows,
                    labels=labels,
                    source_labels=source_labels,
                    simplex_tolerance=args.simplex_tolerance,
                    require_explicit_release_id=not args.allow_derived_release_id,
                    source_paths=used_paths,
                    expected_variants=expected_variants,
                    expected_partitions=expected_partitions,
                    expected_partition_blockers=partition_blockers,
                    expected_partition_contract="sibling_snapshot_tape",
                    bootstrap_iterations=args.bootstrap_iterations,
                    bootstrap_seed=args.bootstrap_seed,
                )
            )
            del rows
            del expected_partitions
        if child_payloads:
            payload = merge_scorecards(child_payloads)
        else:
            payload = build_scorecard(
                [],
                labels=labels,
                expected_variants=expected_variants,
                expected_partitions=[],
                expected_partition_blockers=[
                    _issue(
                        "no_live_variant_tapes",
                        "no live variant tapes were selected for bounded scoring",
                    )
                ],
                expected_partition_contract="sibling_snapshot_tape",
                bootstrap_iterations=args.bootstrap_iterations,
                bootstrap_seed=args.bootstrap_seed,
            )
        json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
        print(
            f"Live variant settlement scorecard: {payload['status']} "
            f"({payload['coverage']['valid_prediction_partition_count']}/"
            f"{payload['coverage']['eligible_partition_count']} eligible partitions)"
        )
    else:
        served = read_rows(args.served)
        replay = read_rows(args.replay)
        payload = compare_replay_to_served(
            served,
            replay,
            probability_atol=args.probability_atol,
            probability_rtol=args.probability_rtol,
            served_source=args.served,
            replay_source=args.replay,
        )
        json_path, report_path = write_outputs(payload, args.json_out, args.report_out, parity=True)
        print(
            f"Live variant replay parity: {payload['status']} "
            f"({payload['summary']['mismatch_count']} mismatches)"
        )
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 1 if args.fail_on_block and payload["status"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
