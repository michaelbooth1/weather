"""Read-only model-versus-market skill-gap decomposition.

The report consumes an already-settled, already-replayed categorical row
export.  It does not fit, tune, or mutate a model.  Reliability and resolution
use the exact CORP/isotonic form of the Murphy decomposition:

    Brier = reliability - resolution + uncertainty

This avoids arbitrary probability bins while retaining the familiar Murphy
interpretation.  Categorical distributions are scored as their existing
one-versus-rest band rows so the result is directly comparable with the
repository's candidate and market Brier scores.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from weather.paths import data_path
from weather.market.market_registry import REGISTRY
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("skill_gap_decomposition")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_VARIANT_ROWS = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_long.csv"
DEFAULT_CORPUS_MANIFEST = DEFAULT_BACKTEST_ROOT / "promotion_corpus.json"
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "skill_gap_decomposition.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "skill_gap_decomposition.md"
DEFAULT_WORST_CASES_OUT = DEFAULT_BACKTEST_ROOT / "skill_gap_decomposition_worst_cases.csv"
MASS_TOLERANCE = 1e-9
RECENT_OBSERVATION_WINDOW_HOURS = 2.0
CAPTURE_ALIGNMENT_TOLERANCE_SECONDS = 30.0 * 60.0


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _outcome(value: Any) -> int | None:
    text = str(value).strip().lower()
    if text in {"1", "1.0", "true", "yes", "win"}:
        return 1
    if text in {"0", "0.0", "false", "no", "loss"}:
        return 0
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _mean(values: Iterable[float | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def _population_stddev(values: Iterable[float | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    average = sum(cleaned) / len(cleaned)
    return math.sqrt(sum((value - average) ** 2 for value in cleaned) / len(cleaned))


def _sha256(path: Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _score_accumulator() -> dict[str, Any]:
    return {
        "n": 0,
        "model_squared_error": 0.0,
        "market_squared_error": 0.0,
        "outcome_sum": 0.0,
        "market_days": set(),
        "markets": set(),
        "snapshots": set(),
    }


def _add_score(
    accumulator: dict[str, Any],
    *,
    model_probability: float,
    market_probability: float,
    outcome: int,
    market_id: str,
    target_date: str,
    snapshot_id: str,
) -> None:
    accumulator["n"] += 1
    accumulator["model_squared_error"] += (model_probability - outcome) ** 2
    accumulator["market_squared_error"] += (market_probability - outcome) ** 2
    accumulator["outcome_sum"] += outcome
    accumulator["market_days"].add((market_id, target_date))
    accumulator["markets"].add(market_id)
    accumulator["snapshots"].add((market_id, target_date, snapshot_id))


def _summarize_score(accumulator: dict[str, Any], *, label: str) -> dict[str, Any]:
    n = int(accumulator["n"])
    if n <= 0:
        return {
            "label": label,
            "n": 0,
            "market_days": 0,
            "markets": 0,
            "snapshots": 0,
            "model_brier": None,
            "market_brier": None,
            "brier_gap": None,
            "uncertainty": None,
            "gap_over_uncertainty": None,
            "gap_over_market_brier": None,
        }
    model_brier = accumulator["model_squared_error"] / n
    market_brier = accumulator["market_squared_error"] / n
    gap = model_brier - market_brier
    base_rate = accumulator["outcome_sum"] / n
    uncertainty = base_rate * (1.0 - base_rate)
    return {
        "label": label,
        "n": n,
        "market_days": len(accumulator["market_days"]),
        "markets": len(accumulator["markets"]),
        "snapshots": len(accumulator["snapshots"]),
        "base_rate": base_rate,
        "model_brier": model_brier,
        "market_brier": market_brier,
        "brier_gap": gap,
        "uncertainty": uncertainty,
        "gap_over_uncertainty": gap / uncertainty if uncertainty > 0 else None,
        "gap_over_market_brier": gap / market_brier if market_brier > 0 else None,
    }


def isotonic_murphy_decomposition(pairs: Iterable[tuple[float, int]]) -> dict[str, Any]:
    """Return an exact, bin-free CORP/Murphy Brier decomposition.

    Equal forecast values are combined before pool-adjacent-violators fitting,
    so the result is invariant to row order.  The fitted isotonic sequence is
    diagnostic only; it is not returned as or used to create a calibrator.
    """

    cleaned = []
    for probability, outcome in pairs:
        if probability is None or outcome not in (0, 1):
            continue
        probability = float(probability)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError("Murphy decomposition probability must be finite and within [0, 1]")
        cleaned.append((probability, int(outcome)))
    if not cleaned:
        return {
            "n": 0,
            "brier": None,
            "reliability": None,
            "resolution": None,
            "uncertainty": None,
            "identity_residual": None,
            "isotonic_block_count": 0,
        }

    cleaned.sort(key=lambda item: item[0])
    forecast_groups: list[dict[str, float]] = []
    for probability, outcome in cleaned:
        if forecast_groups and probability == forecast_groups[-1]["probability"]:
            forecast_groups[-1]["weight"] += 1.0
            forecast_groups[-1]["outcome_sum"] += outcome
        else:
            forecast_groups.append(
                {
                    "probability": probability,
                    "weight": 1.0,
                    "outcome_sum": float(outcome),
                }
            )

    blocks: list[dict[str, float]] = []
    for group in forecast_groups:
        blocks.append(
            {
                "weight": group["weight"],
                "outcome_sum": group["outcome_sum"],
            }
        )
        while (
            len(blocks) >= 2
            and blocks[-2]["outcome_sum"] / blocks[-2]["weight"]
            > blocks[-1]["outcome_sum"] / blocks[-1]["weight"]
        ):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                {
                    "weight": left["weight"] + right["weight"],
                    "outcome_sum": left["outcome_sum"] + right["outcome_sum"],
                }
            )

    n = len(cleaned)
    brier = sum((probability - outcome) ** 2 for probability, outcome in cleaned) / n
    outcome_sum = sum(outcome for _, outcome in cleaned)
    base_rate = outcome_sum / n
    uncertainty = base_rate * (1.0 - base_rate)
    calibrated_brier = 0.0
    for block in blocks:
        weight = block["weight"]
        positives = block["outcome_sum"]
        rate = positives / weight
        calibrated_brier += positives * (1.0 - rate) ** 2
        calibrated_brier += (weight - positives) * rate**2
    calibrated_brier /= n

    reliability = max(0.0, brier - calibrated_brier)
    resolution = max(0.0, uncertainty - calibrated_brier)
    reconstructed = reliability - resolution + uncertainty
    return {
        "n": n,
        "base_rate": base_rate,
        "brier": brier,
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
        "calibrated_brier": calibrated_brier,
        "identity_residual": brier - reconstructed,
        "forecast_value_count": len(forecast_groups),
        "isotonic_block_count": len(blocks),
        "method": "exact_CORP_isotonic_Murphy_identity",
    }


def _partition_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(row.get("market_id") or ""),
        str(row.get("target_date") or ""),
        str(row.get("snapshot_id") or ""),
    )


def _mode(values: Iterable[Any], default: str = "unknown") -> str:
    cleaned = [str(value) for value in values if value not in (None, "")]
    if not cleaned:
        return default
    counts = Counter(cleaned)
    return sorted(counts, key=lambda value: (-counts[value], value))[0]


def _hour_regime(hour: int | None) -> str:
    if hour is None:
        return "unknown"
    if 3 <= hour <= 5:
        return "predawn_03_05"
    if 9 <= hour <= 14:
        return "primary_09_14"
    if 20 <= hour <= 23:
        return "lock_in_20_23"
    if 0 <= hour <= 8:
        return "other_early_00_08"
    if 15 <= hour <= 19:
        return "late_day_15_19"
    return "unknown"


def _lead_hours(captured_at_local: datetime | None, target_date: str) -> float | None:
    if captured_at_local is None:
        return None
    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        return None
    end = datetime.combine(target + timedelta(days=1), time.min, captured_at_local.tzinfo)
    return (end - captured_at_local).total_seconds() / 3600.0


def _lead_bucket(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours < 0:
        return "after_target_day"
    if hours <= 3:
        return "00-03h"
    if hours <= 6:
        return "03-06h"
    if hours <= 9:
        return "06-09h"
    if hours <= 12:
        return "09-12h"
    if hours <= 18:
        return "12-18h"
    if hours <= 24:
        return "18-24h"
    return "24h+"


def _band_interval(row: dict[str, Any]) -> tuple[float | None, float | None]:
    key = str(row.get("band_key") or "")
    if ":" not in key:
        value = _float(row.get("bin_value"))
        return value, value
    kind, payload = key.split(":", 1)
    match = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*(?:-\s*([+-]?\d+(?:\.\d+)?))?\s*",
        payload,
    )
    numbers = [
        number
        for number in (
            _float(match.group(1)) if match else None,
            _float(match.group(2)) if match and match.group(2) else None,
        )
        if number is not None
    ]
    if kind == "lte" and numbers:
        return None, numbers[-1]
    if kind == "gte" and numbers:
        return numbers[0], None
    if numbers:
        return min(numbers), max(numbers)
    return None, None


def _partition_boundaries(rows: list[dict[str, Any]]) -> tuple[list[float], float | None]:
    intervals = [_band_interval(row) for row in rows]
    finite_widths = [
        high - low + 1.0
        for low, high in intervals
        if low is not None and high is not None and high >= low
    ]
    ordered = sorted(
        intervals,
        key=lambda item: (
            -math.inf if item[0] is None else item[0],
            math.inf if item[1] is None else item[1],
        ),
    )
    boundaries = []
    for left, right in zip(ordered, ordered[1:]):
        left_high = left[1]
        right_low = right[0]
        if left_high is not None and right_low is not None:
            boundaries.append((left_high + right_low) / 2.0)
    return boundaries, median(finite_widths) if finite_widths else None


def _boundary_bucket(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio <= 0.125:
        return "near_boundary_<=0.125_band"
    if ratio <= 0.375:
        return "middle_0.125_to_0.375_band"
    return "band_center_>0.375_band"


def _volatility_bucket(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio <= 0.25:
        return "low_<=0.25_band"
    if ratio <= 0.75:
        return "moderate_0.25_to_0.75_band"
    return "high_>0.75_band"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_feature_context(
    *,
    corpus_manifest: str | Path | None,
    snapshots_root: str | Path,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    """Load compact point-in-time feature context and rolling volatility."""

    if not corpus_manifest:
        return {}, {"status": "SKIP", "reason": "corpus_manifest_not_supplied"}
    manifest_path = Path(corpus_manifest)
    payload = _read_json(manifest_path)
    entries = payload.get("entries") or []
    root = Path(snapshots_root)
    feature_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    missing_files = []
    feature_inputs = []
    duplicate_feature_key_count = 0
    for entry in entries:
        market_id = str(entry.get("market_id") or "")
        target_date = str(entry.get("target_date") or "")
        relative = entry.get("folder_relative_to_snapshots_root") or entry.get("folder_name")
        if not relative:
            continue
        path = root / str(relative) / "features_long.csv"
        if not path.exists():
            missing_files.append(str(path))
            continue
        before_hash = _sha256(path)
        before_bytes = path.stat().st_size
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                snapshot_id = str(row.get("snapshot_id") or "")
                row_target_date = str(row.get("target_date") or target_date)
                key = (market_id, row_target_date, snapshot_id)
                if not all(key):
                    continue
                feature_row = {
                    "captured_at_local": _parse_datetime(row.get("captured_at_local")),
                    "forecast_disagreement": _float(row.get("forecast_disagreement")),
                    "forecast_high": _float(row.get("forecast_high")),
                    "forecast_source_count": _float(row.get("forecast_source_count")),
                    "current_temp": _float(row.get("current_temp")),
                    "warming_rate_2h": _float(row.get("warming_rate_2h")),
                    "high_so_far": _float(row.get("high_so_far")),
                }
                existing = feature_rows.get(key)
                if existing is not None:
                    duplicate_feature_key_count += 1
                    context_fields = set(feature_row) - {"captured_at_local"}
                    if any(existing.get(field) != feature_row.get(field) for field in context_fields):
                        raise ValueError(
                            "duplicate feature snapshot_id has conflicting prediction-time "
                            f"context: {key}"
                        )
                    existing_capture = existing.get("captured_at_local")
                    duplicate_capture = feature_row.get("captured_at_local")
                    if (
                        duplicate_capture is not None
                        and (
                            existing_capture is None
                            or duplicate_capture < existing_capture
                        )
                    ):
                        existing["captured_at_local"] = duplicate_capture
                    continue
                feature_rows[key] = feature_row
        feature_inputs.append(
            {
                "path": str(path),
                "bytes": before_bytes,
                "sha256": before_hash,
            }
        )

    for item in feature_inputs:
        path = Path(item["path"])
        after_hash = _sha256(path)
        after_bytes = path.stat().st_size if path.exists() else None
        if after_hash != item["sha256"] or after_bytes != item["bytes"]:
            raise RuntimeError(f"feature input changed while being read: {path}")
    input_set_bytes = json.dumps(
        feature_inputs,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    feature_input_set_sha256 = hashlib.sha256(input_set_bytes).hexdigest()

    by_market_day: dict[tuple[str, str], list[tuple[tuple[str, str, str], dict[str, Any]]]] = defaultdict(list)
    for key, row in feature_rows.items():
        if row.get("captured_at_local") is not None:
            by_market_day[(key[0], key[1])].append((key, row))

    for day_rows in by_market_day.values():
        day_rows.sort(key=lambda item: item[1]["captured_at_local"])
        recent: deque[tuple[datetime, float]] = deque()
        for _, row in day_rows:
            captured = row["captured_at_local"]
            threshold = captured - timedelta(hours=RECENT_OBSERVATION_WINDOW_HOURS)
            while recent and recent[0][0] < threshold:
                recent.popleft()
            current = row.get("current_temp")
            if current is not None:
                recent.append((captured, current))
            temperatures = [value for _, value in recent]
            row["recent_observation_count_2h"] = len(temperatures)
            row["recent_observation_range_2h"] = (
                max(temperatures) - min(temperatures)
                if len(temperatures) >= 2
                else None
            )
            row["recent_observation_stddev_2h"] = (
                _population_stddev(temperatures)
                if len(temperatures) >= 2
                else None
            )
            row["recent_observation_change_2h"] = (
                temperatures[-1] - temperatures[0] if len(temperatures) >= 2 else None
            )

    return feature_rows, {
        "status": "PASS" if feature_rows else "MISSING",
        "manifest_entry_count": len(entries),
        "feature_file_count": len(feature_inputs),
        "feature_input_set_sha256": feature_input_set_sha256,
        "feature_inputs": feature_inputs,
        "feature_snapshot_count": len(feature_rows),
        "equivalent_duplicate_feature_key_count": duplicate_feature_key_count,
        "missing_feature_file_count": len(missing_files),
        "first_missing_feature_files": missing_files[:10],
    }


def _is_verified_same_second_collision(rows: list[dict[str, Any]]) -> bool:
    """Recognize the frozen scorer's same-second duplicate-capture shape."""

    if len(rows) < 2 or len(rows) % 2 or sum(row["outcome"] for row in rows) != 2:
        return False
    by_capture: dict[datetime | None, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_capture[row.get("captured_at_local")].append(row)
    if None in by_capture or len(by_capture) != 2:
        return False
    captures = sorted(by_capture)
    if captures[0].replace(microsecond=0) != captures[1].replace(microsecond=0):
        return False

    def indexed(capture_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
        return {
            (
                str(row.get("band_key") or ""),
                str(row.get("bin_type") or ""),
                str(row.get("bin_value") or ""),
            ): row
            for row in capture_rows
        }

    left = indexed(by_capture[captures[0]])
    right = indexed(by_capture[captures[1]])
    if len(left) * 2 != len(rows) or left.keys() != right.keys():
        return False
    comparison_fields = ("model_probability", "market_probability", "outcome")
    if any(
        left[key].get(field) != right[key].get(field)
        for key in left
        for field in comparison_fields
    ):
        return False
    return sum(row["outcome"] for row in left.values()) == 1


def _market_weighted_decomposition(
    rows: list[dict[str, Any]],
    forecast_key: str,
) -> dict[str, Any]:
    """Pool exact per-market components without cross-market base-rate mixing."""

    components = [row[forecast_key] for row in rows]
    n = sum(int(component["n"]) for component in components)
    weighted_fields = (
        "base_rate",
        "brier",
        "reliability",
        "resolution",
        "uncertainty",
        "calibrated_brier",
    )
    result = {
        field: (
            sum(float(component[field]) * int(component["n"]) for component in components)
            / n
        )
        for field in weighted_fields
    }
    reconstructed = result["reliability"] - result["resolution"] + result["uncertainty"]
    return {
        "n": n,
        **result,
        "identity_residual": result["brier"] - reconstructed,
        "market_count": len(components),
        "method": "market_stratified_weighted_exact_CORP_isotonic_Murphy_identity",
    }


def _sharpness_metrics(
    rows: list[dict[str, Any]],
    probability_key: str,
) -> dict[str, float | None]:
    probabilities = [max(0.0, float(row[probability_key])) for row in rows]
    total = sum(probabilities)
    if total <= 0:
        return {}
    normalized = [probability / total for probability in probabilities]
    entropy = -sum(probability * math.log(probability) for probability in normalized if probability > 0)
    winner_probabilities = [
        normalized[index]
        for index, row in enumerate(rows)
        if row.get("outcome") == 1
    ]
    return {
        "mass": total,
        "effective_bands": math.exp(entropy),
        "top_probability": max(normalized),
        "winner_probability": winner_probabilities[0] if len(winner_probabilities) == 1 else None,
    }


def _sharpness_accumulator() -> dict[str, Any]:
    return {"count": 0, "sums": defaultdict(float), "counts": Counter()}


def _add_sharpness(accumulator: dict[str, Any], model: dict[str, Any], market: dict[str, Any]) -> None:
    accumulator["count"] += 1
    for prefix, metrics in (("model", model), ("market", market)):
        for field, value in metrics.items():
            if value is not None:
                key = f"{prefix}_{field}"
                accumulator["sums"][key] += float(value)
                accumulator["counts"][key] += 1


def _summarize_sharpness(accumulator: dict[str, Any]) -> dict[str, Any]:
    output = {"partition_count": accumulator["count"]}
    for key, total in sorted(accumulator["sums"].items()):
        count = accumulator["counts"][key]
        output[key] = total / count if count else None
    if output.get("model_effective_bands") is not None and output.get("market_effective_bands") is not None:
        output["effective_band_gap_model_minus_market"] = (
            output["model_effective_bands"] - output["market_effective_bands"]
        )
    if output.get("model_top_probability") is not None and output.get("market_top_probability") is not None:
        output["top_probability_gap_model_minus_market"] = (
            output["model_top_probability"] - output["market_top_probability"]
        )
    return output


def _day_hour_accumulator() -> dict[str, Any]:
    return {
        "score": _score_accumulator(),
        "captured_hours": [],
        "lead_hours": [],
        "forecast_disagreement": [],
        "forecast_disagreement_buckets": [],
        "forecast_source_count_buckets": [],
        "source_freshness_states": [],
        "winner_pressure": [],
        "boundary_distance_native": [],
        "boundary_distance_band_ratio": [],
        "observation_range_2h_native": [],
        "observation_range_band_ratio": [],
        "observation_stddev_2h_native": [],
        "warming_rate_2h": [],
        "feature_context_count": 0,
        "partition_count": 0,
    }


def _summarize_day_hour(
    key: tuple[str, str, int],
    accumulator: dict[str, Any],
) -> dict[str, Any]:
    score = _summarize_score(accumulator["score"], label=f"{key[0]}:{key[1]}:{key[2]:02d}")
    boundary_ratio = _mean(accumulator["boundary_distance_band_ratio"])
    volatility_ratio = _mean(accumulator["observation_range_band_ratio"])
    score.update(
        {
            "market_id": key[0],
            "target_date": key[1],
            "hour": key[2],
            "hour_label": f"{key[2]:02d}:00",
            "regime": _hour_regime(key[2]),
            "partition_count": accumulator["partition_count"],
            "mean_lead_hours_to_target_day_end": _mean(accumulator["lead_hours"]),
            "forecast_disagreement_mean": _mean(accumulator["forecast_disagreement"]),
            "forecast_disagreement_bucket": _mode(accumulator["forecast_disagreement_buckets"]),
            "forecast_source_count_bucket": _mode(accumulator["forecast_source_count_buckets"]),
            "source_freshness_state": _mode(accumulator["source_freshness_states"]),
            "winner_forecast_pressure": _mode(accumulator["winner_pressure"]),
            "boundary_distance_native_mean": _mean(accumulator["boundary_distance_native"]),
            "boundary_distance_band_ratio_mean": boundary_ratio,
            "boundary_proximity_bucket": _boundary_bucket(boundary_ratio),
            "recent_observation_range_2h_native_mean": _mean(accumulator["observation_range_2h_native"]),
            "recent_observation_range_band_ratio_mean": volatility_ratio,
            "recent_observation_stddev_2h_native_mean": _mean(
                accumulator["observation_stddev_2h_native"]
            ),
            "warming_rate_2h_mean": _mean(accumulator["warming_rate_2h"]),
            "observation_volatility_bucket": _volatility_bucket(volatility_ratio),
            "feature_context_partition_count": accumulator["feature_context_count"],
        }
    )
    score["positive_excess_loss"] = max(
        0.0,
        accumulator["score"]["model_squared_error"] - accumulator["score"]["market_squared_error"],
    )
    return score


def _taxonomy_tables(day_hours: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    dimensions = (
        "regime",
        "forecast_disagreement_bucket",
        "boundary_proximity_bucket",
        "observation_volatility_bucket",
        "source_freshness_state",
        "winner_forecast_pressure",
    )
    total_positive = sum(row.get("positive_excess_loss") or 0.0 for row in day_hours)
    output: dict[str, list[dict[str, Any]]] = {}
    for dimension in dimensions:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "day_hours": 0,
                "positive_excess_loss": 0.0,
                "gap_sum": 0.0,
                "positive_gap_day_hours": 0,
            }
        )
        for row in day_hours:
            bucket = str(row.get(dimension) or "unknown")
            current = grouped[bucket]
            current["day_hours"] += 1
            current["positive_excess_loss"] += row.get("positive_excess_loss") or 0.0
            gap = row.get("brier_gap")
            if gap is not None:
                current["gap_sum"] += gap
                if gap > 0:
                    current["positive_gap_day_hours"] += 1
        table = []
        for bucket, values in grouped.items():
            table.append(
                {
                    "dimension": dimension,
                    "bucket": bucket,
                    "day_hours": values["day_hours"],
                    "positive_gap_day_hours": values["positive_gap_day_hours"],
                    "mean_brier_gap": values["gap_sum"] / values["day_hours"],
                    "positive_excess_loss": values["positive_excess_loss"],
                    "share_of_positive_excess_loss": (
                        values["positive_excess_loss"] / total_positive
                        if total_positive > 0
                        else None
                    ),
                }
            )
        output[dimension] = sorted(
            table,
            key=lambda row: (-(row["positive_excess_loss"] or 0.0), row["bucket"]),
        )
    return output


def _decomposition_comparison(
    model: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any]:
    brier_gap = (model.get("brier") or 0.0) - (market.get("brier") or 0.0)
    calibration_contribution = (model.get("reliability") or 0.0) - (
        market.get("reliability") or 0.0
    )
    resolution_contribution = (market.get("resolution") or 0.0) - (
        model.get("resolution") or 0.0
    )
    uncertainty_contribution = (model.get("uncertainty") or 0.0) - (
        market.get("uncertainty") or 0.0
    )
    reconstructed_gap = (
        calibration_contribution + resolution_contribution + uncertainty_contribution
    )
    if resolution_contribution > max(0.0, calibration_contribution) * 1.5:
        problem_type = "resolution_information_dominated"
    elif calibration_contribution > max(0.0, resolution_contribution) * 1.5:
        problem_type = "reliability_calibration_dominated"
    else:
        problem_type = "mixed_reliability_and_resolution"
    return {
        "brier_gap": brier_gap,
        "calibration_gap_contribution": calibration_contribution,
        "resolution_gap_contribution": resolution_contribution,
        "uncertainty_gap_contribution": uncertainty_contribution,
        "reconstructed_gap": reconstructed_gap,
        "gap_identity_residual": brier_gap - reconstructed_gap,
        "calibration_share_of_gap": (
            calibration_contribution / brier_gap if brier_gap != 0 else None
        ),
        "resolution_share_of_gap": (
            resolution_contribution / brier_gap if brier_gap != 0 else None
        ),
        "problem_type": problem_type,
    }


def _information_requirements(
    comparison: dict[str, Any],
    taxonomy: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    requirements = []
    problem_type = comparison.get("problem_type")
    if problem_type == "resolution_information_dominated":
        requirements.append(
            {
                "condition": "The market's resolution advantage must shrink.",
                "implication": (
                    "The model needs prediction-time information that separates the winning band "
                    "from nearby bands; global recalibration alone cannot supply that resolution."
                ),
            }
        )
    elif problem_type == "reliability_calibration_dominated":
        requirements.append(
            {
                "condition": "The model's excess reliability penalty must shrink.",
                "implication": (
                    "A leakage-safe recalibration fitted strictly inside training folds could address "
                    "the dominant deficit, subject to untouched-window confirmation."
                ),
            }
        )
    else:
        requirements.append(
            {
                "condition": "Both reliability and resolution deficits must shrink.",
                "implication": (
                    "A calibration-only or information-only intervention is unlikely to close the "
                    "full gap by itself."
                ),
            }
        )

    mapping = {
        "regime": {
            "predawn_03_05": "better overnight forecast anchoring and run-to-run guidance",
            "primary_09_14": "better heating-trajectory and same-day forecast updates",
            "lock_in_20_23": "faster resolution-source/observation incorporation, though this is near lock-in",
            "late_day_15_19": "better current-high and late heating/cooling trajectory evidence",
        },
        "forecast_disagreement_bucket": {
            "high_disagreement": "higher-quality multimodel spread and source-state reliability",
            "moderate_disagreement": "more precise forecast centering and source weighting",
        },
        "boundary_proximity_bucket": {
            "near_boundary_<=0.125_band": "sub-band centering and boundary-aware uncertainty",
        },
        "observation_volatility_bucket": {
            "high_>0.75_band": "higher-cadence observation trajectory and volatility features",
        },
    }
    for dimension, bucket_actions in mapping.items():
        rows = taxonomy.get(dimension) or []
        if not rows:
            continue
        dominant = rows[0]
        action = bucket_actions.get(dominant.get("bucket"))
        if action:
            requirements.append(
                {
                    "condition": (
                        f"{dimension} bucket `{dominant.get('bucket')}` remains the dominant "
                        f"positive-loss bucket ({dominant.get('share_of_positive_excess_loss'):.1%})."
                    ),
                    "implication": f"The most direct missing-information hypothesis is {action}.",
                }
            )
    return requirements


def build_decomposition(
    *,
    variant_rows: str | Path,
    corpus_manifest: str | Path | None = None,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    variant_id: str | None = None,
    model_probability_column: str = "probability",
    market_probability_column: str = "market_yes",
    worst_case_limit: int = 50,
    generated_at_utc: str | None = None,
    code_identity: str | None = None,
) -> dict[str, Any]:
    variant_path = Path(variant_rows)
    variant_input_bytes = variant_path.stat().st_size
    variant_input_sha256 = _sha256(variant_path)
    manifest_path = Path(corpus_manifest) if corpus_manifest else None
    manifest_input_bytes = (
        manifest_path.stat().st_size
        if manifest_path is not None and manifest_path.exists()
        else None
    )
    manifest_input_sha256 = _sha256(manifest_path) if manifest_path else None
    manifest_payload = _read_json(manifest_path) if manifest_path else {}
    expected_band_counts = {
        (str(entry.get("market_id") or ""), str(entry.get("target_date") or "")): int(
            entry["band_count"]
        )
        for entry in (manifest_payload.get("entries") or [])
        if entry.get("market_id")
        and entry.get("target_date")
        and entry.get("band_count") not in (None, "")
    }
    feature_context, feature_receipt = load_feature_context(
        corpus_manifest=corpus_manifest,
        snapshots_root=snapshots_root,
    )
    if corpus_manifest and (
        feature_receipt.get("status") != "PASS"
        or feature_receipt.get("missing_feature_file_count") != 0
    ):
        raise ValueError(
            "corpus feature context is required for loss taxonomy: "
            f"status={feature_receipt.get('status')} "
            f"missing_files={feature_receipt.get('missing_feature_file_count')}"
        )

    pairs_by_market: dict[str, dict[str, list[tuple[float, int]]]] = defaultdict(
        lambda: {"model": [], "market": []}
    )
    score_slices: dict[str, dict[str, dict[str, Any]]] = {
        "hour": defaultdict(_score_accumulator),
        "lead_time": defaultdict(_score_accumulator),
        "named_cut": defaultdict(_score_accumulator),
    }
    named_cut_predicates = {
        "predawn_03_05": lambda hour: 3 <= hour <= 5,
        "primary_09_14": lambda hour: 9 <= hour <= 14,
        "lock_in_20_23": lambda hour: 20 <= hour <= 23,
        "all_hours": lambda hour: 0 <= hour <= 23,
    }
    sharpness_by_market: dict[str, dict[str, Any]] = defaultdict(_sharpness_accumulator)
    day_hour_groups: dict[tuple[str, str, int], dict[str, Any]] = defaultdict(
        _day_hour_accumulator
    )

    row_count = 0
    selected_row_count = 0
    complete_partition_count = 0
    incomplete_market_partition_count = 0
    invalid_partition_count = 0
    keyless_row_count = 0
    non_single_winner_partition_count = 0
    mass_violation_count = 0
    max_mass_residual = 0.0
    matched_feature_partition_count = 0
    hourly_normalized_partition_count = 0
    target_day_hourly_normalized_partition_count = 0
    capture_alignment_max_abs_seconds = 0.0
    capture_feature_lag_min_seconds: float | None = None
    capture_feature_lag_max_seconds: float | None = None
    observed_variant_ids: set[str] = set()
    seen_partition_keys: set[tuple[str, str, str]] = set()
    seen_hour_keys: set[tuple[str, str, str, int]] = set()
    last_capture_by_market_day: dict[tuple[str, str], datetime] = {}

    current_key: tuple[str, str, str] | None = None
    partition_rows: list[dict[str, Any]] = []

    def consume_partition(rows: list[dict[str, Any]]) -> None:
        nonlocal complete_partition_count
        nonlocal incomplete_market_partition_count
        nonlocal invalid_partition_count
        nonlocal non_single_winner_partition_count
        nonlocal mass_violation_count
        nonlocal max_mass_residual
        nonlocal matched_feature_partition_count
        nonlocal hourly_normalized_partition_count
        nonlocal target_day_hourly_normalized_partition_count
        nonlocal capture_alignment_max_abs_seconds
        nonlocal capture_feature_lag_min_seconds
        nonlocal capture_feature_lag_max_seconds
        if not rows:
            return
        model_values = [row.get("model_probability") for row in rows]
        if any(value is None for value in model_values):
            invalid_partition_count += 1
            return
        if any(not 0.0 <= float(value) <= 1.0 for value in model_values):
            raise ValueError("candidate probability outside [0, 1]")
        model_mass = sum(float(value) for value in model_values)
        residual = abs(model_mass - 1.0)
        max_mass_residual = max(max_mass_residual, residual)
        if residual > MASS_TOLERANCE:
            mass_violation_count += 1

        if any(row.get("market_probability") is None for row in rows):
            incomplete_market_partition_count += 1
            return
        if any(
            not 0.0 <= float(row["market_probability"]) <= 1.0
            for row in rows
        ):
            raise ValueError("market probability outside [0, 1]")
        if any(row.get("outcome") not in (0, 1) for row in rows):
            invalid_partition_count += 1
            return
        winner_count = sum(1 for row in rows if row.get("outcome") == 1)
        band_signatures = [
            (
                str(row.get("band_key") or ""),
                str(row.get("bin_type") or ""),
                str(row.get("bin_value") or ""),
            )
            for row in rows
        ]
        expected_band_count = expected_band_counts.get(
            (rows[0]["market_id"], rows[0]["target_date"])
        )
        if winner_count == 1 and len(set(band_signatures)) != len(rows):
            raise ValueError("ordinary categorical partition contains duplicate band keys")
        if (
            winner_count == 1
            and expected_band_count is not None
            and len(rows) != expected_band_count
        ):
            raise ValueError(
                "categorical partition band count does not match frozen manifest: "
                f"{len(rows)} != {expected_band_count}"
            )
        if winner_count != 1:
            # Snapshot ids are second-resolution identifiers. The frozen corpus
            # contains two same-second capture collisions that the accepted
            # scorer treats as one probability partition with duplicated band
            # outcomes. Keep every binary row in the Brier population, but do
            # not pretend such a multihit partition is a one-hot sharpness row.
            if not _is_verified_same_second_collision(rows):
                raise ValueError(
                    "partition does not have exactly one winner and is not a verified "
                    "same-second duplicate-capture collision"
                )
            if (
                expected_band_count is not None
                and len(rows) != 2 * expected_band_count
            ):
                raise ValueError(
                    "collision partition band count does not match twice the frozen "
                    f"manifest count: {len(rows)} != {2 * expected_band_count}"
                )
            non_single_winner_partition_count += 1

        market_id = rows[0]["market_id"]
        target_date = rows[0]["target_date"]
        snapshot_id = rows[0]["snapshot_id"]
        export_captured = rows[0].get("captured_at_local")
        feature = feature_context.get((market_id, target_date, snapshot_id)) or {}
        feature_captured = feature.get("captured_at_local")
        if corpus_manifest and feature_captured is None:
            raise ValueError(
                "matched feature context lacks a timezone-aware captured_at_local: "
                f"{(market_id, target_date, snapshot_id)}"
            )
        if corpus_manifest and export_captured is None:
            raise ValueError(
                "variant row lacks captured_at_local required for capture-time cuts: "
                f"{(market_id, target_date, snapshot_id)}"
            )
        spec = REGISTRY.get(market_id)
        market_timezone = (
            spec.tz
            if spec is not None
            else (feature_captured.tzinfo if feature_captured is not None else None)
        )
        captured = (
            export_captured.astimezone(market_timezone)
            if export_captured is not None and market_timezone is not None
            else feature_captured or export_captured
        )
        if export_captured is not None and feature.get("captured_at_local") is not None:
            if (
                export_captured.tzinfo is None
                or feature["captured_at_local"].tzinfo is None
            ):
                raise ValueError(
                    "capture timestamps must include UTC offsets for market-local alignment"
                )
            feature_lag_seconds = (
                export_captured.astimezone(timezone.utc)
                - feature["captured_at_local"].astimezone(timezone.utc)
            ).total_seconds()
            alignment_seconds = abs(feature_lag_seconds)
            capture_feature_lag_min_seconds = (
                feature_lag_seconds
                if capture_feature_lag_min_seconds is None
                else min(capture_feature_lag_min_seconds, feature_lag_seconds)
            )
            capture_feature_lag_max_seconds = (
                feature_lag_seconds
                if capture_feature_lag_max_seconds is None
                else max(capture_feature_lag_max_seconds, feature_lag_seconds)
            )
            capture_alignment_max_abs_seconds = max(
                capture_alignment_max_abs_seconds,
                alignment_seconds,
            )
            if feature_lag_seconds < 0:
                raise ValueError(
                    "matched feature context is later than the scored export instant: "
                    f"{(market_id, target_date, snapshot_id)} "
                    f"feature_lag_seconds={feature_lag_seconds:.6f}"
                )
            if feature_lag_seconds > CAPTURE_ALIGNMENT_TOLERANCE_SECONDS:
                raise ValueError(
                    "export and market-local feature capture timestamps do not identify "
                    f"the same instant: {(market_id, target_date, snapshot_id)} "
                    f"delta_seconds={alignment_seconds:.6f}"
                )
        hour = captured.hour if captured is not None else rows[0].get("capture_hour")
        if hour is None:
            invalid_partition_count += 1
            return
        hour = int(hour)
        lead_hours = _lead_hours(captured, target_date)
        lead_bucket = _lead_bucket(lead_hours)
        try:
            is_target_day_capture = (
                captured is not None
                and captured.date() == date.fromisoformat(target_date)
            )
        except ValueError:
            is_target_day_capture = False
        if feature:
            matched_feature_partition_count += 1

        market_day_key = (market_id, target_date)
        previous_capture = last_capture_by_market_day.get(market_day_key)
        if captured is not None and previous_capture is not None and captured < previous_capture:
            raise ValueError(
                "variant row export is not capture-time ordered within market-day; "
                "hour-normalized cuts require the earliest capture first"
            )
        if captured is not None:
            last_capture_by_market_day[market_day_key] = captured
        capture_date = captured.date().isoformat() if captured is not None else "unknown"
        normalization_key = (market_id, target_date, capture_date, hour)
        is_hourly_representative = normalization_key not in seen_hour_keys
        if is_hourly_representative:
            seen_hour_keys.add(normalization_key)
            hourly_normalized_partition_count += 1
            if is_target_day_capture:
                target_day_hourly_normalized_partition_count += 1

        boundaries, band_width = _partition_boundaries(rows)
        forecast_high = feature.get("forecast_high")
        boundary_distance = (
            min(abs(forecast_high - boundary) for boundary in boundaries)
            if forecast_high is not None and boundaries
            else None
        )
        boundary_ratio = (
            boundary_distance / band_width
            if boundary_distance is not None and band_width not in (None, 0)
            else None
        )
        observation_range = feature.get("recent_observation_range_2h")
        observation_range_ratio = (
            observation_range / band_width
            if observation_range is not None and band_width not in (None, 0)
            else None
        )

        complete_partition_count += 1
        if winner_count == 1:
            model_sharpness = _sharpness_metrics(rows, "model_probability")
            market_sharpness = _sharpness_metrics(rows, "market_probability")
            _add_sharpness(
                sharpness_by_market[market_id],
                model_sharpness,
                market_sharpness,
            )

        day_hour = None
        hour_key = (market_id, target_date, hour)
        if is_hourly_representative and is_target_day_capture:
            day_hour = day_hour_groups[hour_key]
            day_hour["partition_count"] += 1
            day_hour["lead_hours"].append(lead_hours)
            day_hour["forecast_disagreement"].append(feature.get("forecast_disagreement"))
            day_hour["forecast_disagreement_buckets"].append(
                _mode(row.get("forecast_disagreement_bucket") for row in rows)
            )
            day_hour["forecast_source_count_buckets"].append(
                _mode(row.get("forecast_source_count_bucket") for row in rows)
            )
            day_hour["source_freshness_states"].append(
                _mode(row.get("source_freshness_state") for row in rows)
            )
            winner_rows = [row for row in rows if row.get("outcome") == 1]
            day_hour["winner_pressure"].append(
                winner_rows[0].get("forecast_bucket_pressure") if winner_rows else None
            )
            day_hour["boundary_distance_native"].append(boundary_distance)
            day_hour["boundary_distance_band_ratio"].append(boundary_ratio)
            day_hour["observation_range_2h_native"].append(observation_range)
            day_hour["observation_range_band_ratio"].append(observation_range_ratio)
            day_hour["observation_stddev_2h_native"].append(
                feature.get("recent_observation_stddev_2h")
            )
            day_hour["warming_rate_2h"].append(feature.get("warming_rate_2h"))
            if feature:
                day_hour["feature_context_count"] += 1

        for row in rows:
            model_probability = float(row["model_probability"])
            market_probability = float(row["market_probability"])
            outcome = int(row["outcome"])
            pairs_by_market[market_id]["model"].append((model_probability, outcome))
            pairs_by_market[market_id]["market"].append((market_probability, outcome))
            score_targets = [score_slices["named_cut"]["all_hours"]]
            if is_hourly_representative:
                score_targets.append(score_slices["lead_time"][lead_bucket])
                if is_target_day_capture:
                    score_targets.extend(
                        [
                            score_slices["hour"][f"{hour:02d}"],
                            day_hour["score"],
                        ]
                    )
                    for name, predicate in named_cut_predicates.items():
                        if name != "all_hours" and predicate(hour):
                            score_targets.append(score_slices["named_cut"][name])
            for accumulator in score_targets:
                _add_score(
                    accumulator,
                    model_probability=model_probability,
                    market_probability=market_probability,
                    outcome=outcome,
                    market_id=market_id,
                    target_date=target_date,
                    snapshot_id=snapshot_id,
                )

    with variant_path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row_count += 1
            row_variant_id = str(raw.get("variant_id") or "")
            observed_variant_ids.add(row_variant_id)
            if variant_id is not None and row_variant_id != variant_id:
                continue
            if variant_id is None and len(observed_variant_ids) > 1:
                raise ValueError(
                    "variant rows contain multiple variant_id values; pass --variant-id explicitly"
                )
            key = _partition_key(raw)
            if not all(key):
                keyless_row_count += 1
                continue
            if current_key is not None and key != current_key:
                consume_partition(partition_rows)
                seen_partition_keys.add(current_key)
                partition_rows = []
                if key in seen_partition_keys:
                    raise ValueError(
                        "variant row export is not partition-contiguous; sort by market/date/snapshot"
                    )
            current_key = key
            model_probability = _float(raw.get(model_probability_column))
            market_probability = _float(raw.get(market_probability_column))
            outcome = _outcome(raw.get("outcome"))
            captured = _parse_datetime(raw.get("captured_at_local"))
            capture_hour = captured.hour if captured is not None else None
            partition_rows.append(
                {
                    "market_id": key[0],
                    "target_date": key[1],
                    "snapshot_id": key[2],
                    "band_key": raw.get("band_key"),
                    "bin_type": raw.get("bin_type"),
                    "bin_value": raw.get("bin_value"),
                    "model_probability": model_probability,
                    "market_probability": market_probability,
                    "outcome": outcome,
                    "captured_at_local": captured,
                    "capture_hour": capture_hour,
                    "forecast_disagreement_bucket": raw.get("forecast_disagreement_bucket"),
                    "forecast_source_count_bucket": raw.get("forecast_source_count_bucket"),
                    "forecast_bucket_pressure": raw.get("forecast_bucket_pressure"),
                    "source_freshness_state": raw.get("source_freshness_state"),
                }
            )
            selected_row_count += 1
    consume_partition(partition_rows)

    if mass_violation_count:
        raise ValueError(
            f"candidate probability mass violated in {mass_violation_count} partitions "
            f"(max residual {max_mass_residual:.12g})"
        )
    if complete_partition_count == 0:
        raise ValueError("no complete model/market categorical partitions were found")
    if (
        keyless_row_count
        or incomplete_market_partition_count
        or invalid_partition_count
    ):
        raise ValueError(
            "input population contains unscored rows or partitions: "
            f"keyless_rows={keyless_row_count} "
            f"incomplete_market_partitions={incomplete_market_partition_count} "
            f"invalid_partitions={invalid_partition_count}"
        )
    if corpus_manifest and matched_feature_partition_count != complete_partition_count:
        raise ValueError(
            "feature context did not match every scored partition: "
            f"{matched_feature_partition_count}/{complete_partition_count}"
        )

    decomposition_rows = []
    pooled_pairs = {"model": [], "market": []}
    pooled_sharpness = _sharpness_accumulator()
    for market_id in sorted(pairs_by_market):
        pairs = pairs_by_market[market_id]
        model_decomposition = isotonic_murphy_decomposition(pairs["model"])
        market_decomposition = isotonic_murphy_decomposition(pairs["market"])
        comparison = _decomposition_comparison(model_decomposition, market_decomposition)
        sharpness = _summarize_sharpness(sharpness_by_market[market_id])
        decomposition_rows.append(
            {
                "scope": market_id,
                "model": model_decomposition,
                "market": market_decomposition,
                "comparison": comparison,
                "sharpness": sharpness,
            }
        )
        pooled_pairs["model"].extend(pairs["model"])
        pooled_pairs["market"].extend(pairs["market"])
        market_accumulator = sharpness_by_market[market_id]
        pooled_sharpness["count"] += market_accumulator["count"]
        for key, value in market_accumulator["sums"].items():
            pooled_sharpness["sums"][key] += value
            pooled_sharpness["counts"][key] += market_accumulator["counts"][key]

    market_rows = list(decomposition_rows)
    pooled_model = _market_weighted_decomposition(market_rows, "model")
    pooled_market = _market_weighted_decomposition(market_rows, "market")
    pooled_comparison = _decomposition_comparison(pooled_model, pooled_market)
    global_model = isotonic_murphy_decomposition(pooled_pairs["model"])
    global_market = isotonic_murphy_decomposition(pooled_pairs["market"])
    global_pool_sensitivity = {
        "scope": "global_pool_sensitivity",
        "model": global_model,
        "market": global_market,
        "comparison": _decomposition_comparison(global_model, global_market),
    }
    pooled_row = {
        "scope": "pooled",
        "model": pooled_model,
        "market": pooled_market,
        "comparison": pooled_comparison,
        "sharpness": _summarize_sharpness(pooled_sharpness),
    }
    decomposition_rows.insert(0, pooled_row)

    hour_rows = [
        _summarize_score(score_slices["hour"][key], label=f"{key}:00")
        for key in sorted(score_slices["hour"], key=int)
    ]
    lead_order = {
        "24h+": 0,
        "18-24h": 1,
        "12-18h": 2,
        "09-12h": 3,
        "06-09h": 4,
        "03-06h": 5,
        "00-03h": 6,
        "after_target_day": 7,
        "unknown": 8,
    }
    lead_rows = [
        _summarize_score(score_slices["lead_time"][key], label=key)
        for key in sorted(
            score_slices["lead_time"],
            key=lambda key: (lead_order.get(key, 99), key),
        )
    ]
    named_rows = [
        _summarize_score(score_slices["named_cut"][key], label=key)
        for key in ("all_hours", "predawn_03_05", "primary_09_14", "lock_in_20_23")
        if key in score_slices["named_cut"]
    ]
    day_hours = [
        _summarize_day_hour(key, accumulator)
        for key, accumulator in sorted(day_hour_groups.items())
    ]
    worst_cases = sorted(
        day_hours,
        key=lambda row: (
            -(
                row["brier_gap"]
                if row.get("brier_gap") is not None
                else -math.inf
            ),
            row["market_id"],
            row["target_date"],
            row["hour"],
        ),
    )[: max(1, int(worst_case_limit))]
    worst_relative_cases = sorted(
        day_hours,
        key=lambda row: (
            -(
                row["gap_over_uncertainty"]
                if row.get("gap_over_uncertainty") is not None
                else -math.inf
            ),
            row["market_id"],
            row["target_date"],
            row["hour"],
        ),
    )[: max(1, int(worst_case_limit))]
    taxonomy = _taxonomy_tables(day_hours)
    information_requirements = _information_requirements(pooled_comparison, taxonomy)

    absolute_hour = max(
        (row for row in hour_rows if row.get("brier_gap") is not None),
        key=lambda row: row["brier_gap"],
    )
    relative_hour = max(
        (row for row in hour_rows if row.get("gap_over_uncertainty") is not None),
        key=lambda row: row["gap_over_uncertainty"],
    )

    if (
        variant_path.stat().st_size != variant_input_bytes
        or _sha256(variant_path) != variant_input_sha256
    ):
        raise RuntimeError(f"variant input changed while being scored: {variant_path}")
    if manifest_path is not None and (
        not manifest_path.exists()
        or manifest_path.stat().st_size != manifest_input_bytes
        or _sha256(manifest_path) != manifest_input_sha256
    ):
        raise RuntimeError(f"corpus manifest changed while being read: {manifest_path}")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": "PASS",
        "evidence_classification": "diagnostic_read_only_not_model_change_not_promotion_evidence",
        "methodology": {
            "brier_decomposition": (
                "Exact CORP/isotonic Murphy identity on the repository's binary band rows: "
                "Brier = reliability - resolution + uncertainty."
            ),
            "pooled_decomposition": (
                "Headline pooled components are row-count-weighted exact per-market components, "
                "which prevents cross-market base-rate mixing. A direct global-pool sensitivity "
                "is reported separately."
            ),
            "categorical_scoring": (
                "Complete model/market partitions with binary outcomes are scored on identical "
                f"rows. {non_single_winner_partition_count} verified same-second collision "
                "partitions with duplicated winners remain in the accepted Brier population but "
                "are excluded from one-hot sharpness. "
                "Market prices remain raw for Brier comparability; categorical entropy normalizes "
                "each unambiguous partition."
            ),
            "hour_definition": (
                "market-local capture hour from the variant export instant converted with the "
                "canonical market-registry timezone. The matched features_long timestamp is a "
                "bounded same-snapshot alignment check, not the analysis clock, because feature "
                "materialization can lag the exported capture. Target-day hour, named-hour, and "
                "taxonomy cuts use the earliest capture per market-day/hour and exclude captures "
                "after target-day midnight. Lead cuts retain a separate earliest capture per "
                "capture-date/hour. all_hours retains the canonical all-snapshot comparator "
                "population."
            ),
            "lead_time_definition": (
                "hours from local capture timestamp to midnight ending target_date; this is a "
                "day-end lead proxy because daily-high settlement has no single occurrence time"
            ),
            "relative_gap_definition": (
                "model-minus-market Brier divided by the slice Murphy uncertainty; "
                "gap_over_market_brier is also reported"
            ),
            "recent_observation_volatility": (
                "rolling two-hour range/stddev of captured current_temp, normalized by categorical "
                "band width for taxonomy"
            ),
            "boundary_proximity": (
                "forecast_high distance to the nearest midpoint separating adjacent settlement "
                "bands, normalized by band width"
            ),
            "no_training_or_tuning": True,
        },
        "inputs": {
            "variant_rows": str(variant_path),
            "variant_rows_bytes": variant_input_bytes,
            "variant_rows_sha256": variant_input_sha256,
            "corpus_manifest": str(manifest_path) if manifest_path else None,
            "corpus_manifest_bytes": manifest_input_bytes,
            "corpus_manifest_sha256": manifest_input_sha256,
            "snapshots_root": str(snapshots_root),
            "requested_variant_id": variant_id,
            "observed_variant_ids": sorted(observed_variant_ids),
            "model_probability_column": model_probability_column,
            "market_probability_column": market_probability_column,
            "code_identity": code_identity,
        },
        "population": {
            "source_row_count": row_count,
            "selected_row_count": selected_row_count,
            "complete_partition_count": complete_partition_count,
            "hourly_normalized_partition_count": hourly_normalized_partition_count,
            "target_day_hourly_normalized_partition_count": (
                target_day_hourly_normalized_partition_count
            ),
            "scored_row_count": pooled_model["n"],
            "market_count": len(pairs_by_market),
            "incomplete_market_partition_count": incomplete_market_partition_count,
            "invalid_partition_count": invalid_partition_count,
            "keyless_row_count": keyless_row_count,
            "non_single_winner_partition_count": non_single_winner_partition_count,
            "candidate_mass_violation_count": mass_violation_count,
            "candidate_max_abs_mass_residual": max_mass_residual,
            "matched_feature_partition_count": matched_feature_partition_count,
            "matched_feature_partition_ratio": (
                matched_feature_partition_count / complete_partition_count
            ),
            "capture_alignment_max_abs_seconds": capture_alignment_max_abs_seconds,
            "capture_feature_lag_min_seconds": capture_feature_lag_min_seconds,
            "capture_feature_lag_max_seconds": capture_feature_lag_max_seconds,
            "capture_alignment_tolerance_seconds": (
                CAPTURE_ALIGNMENT_TOLERANCE_SECONDS
            ),
            "feature_context": feature_receipt,
        },
        "pooled_verdict": {
            **pooled_comparison,
            "model_effective_bands": pooled_row["sharpness"].get("model_effective_bands"),
            "market_effective_bands": pooled_row["sharpness"].get("market_effective_bands"),
            "effective_band_gap_model_minus_market": pooled_row["sharpness"].get(
                "effective_band_gap_model_minus_market"
            ),
            "model_top_probability": pooled_row["sharpness"].get("model_top_probability"),
            "market_top_probability": pooled_row["sharpness"].get("market_top_probability"),
            "model_mean_probability_mass": pooled_row["sharpness"].get("model_mass"),
            "market_mean_raw_probability_mass": pooled_row["sharpness"].get(
                "market_mass"
            ),
        },
        "decomposition": decomposition_rows,
        "global_pool_sensitivity": global_pool_sensitivity,
        "hour_slices": hour_rows,
        "lead_time_slices": lead_rows,
        "named_hour_slices": named_rows,
        "widest_gap": {
            "absolute_hour": absolute_hour,
            "relative_to_uncertainty_hour": relative_hour,
        },
        "worst_market_day_hours": worst_cases,
        "worst_relative_market_day_hours": worst_relative_cases,
        "taxonomy": taxonomy,
        "information_requirements": information_requirements,
        "interpretation_guardrail": (
            "This report diagnoses an already-settled corpus. It does not fit or tune a model and "
            "does not authorize promotion, release, pointer, serving, scheduler, collector, sizing, "
            "or trading changes. Any future improvement claim requires leakage-first review and an "
            "untouched preregistered confirmation window."
        ),
    }


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(payload: dict[str, Any]) -> str:
    population = payload.get("population") or {}
    verdict = payload.get("pooled_verdict") or {}
    lines = [
        "# Model-versus-market skill-gap decomposition",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        "",
        "This is a read-only diagnostic of an already-settled replay. It changes and tunes nothing.",
        "",
        "## What kind of problem is this?",
        "",
        f"**{str(verdict.get('problem_type') or 'unknown').replace('_', ' ').upper()}**",
        "",
    ]
    lines += markdown_table(
        ["Quantity", "Value"],
        [
            ["Model Brier minus market", _fmt(verdict.get("brier_gap"))],
            ["Reliability/calibration contribution", _fmt(verdict.get("calibration_gap_contribution"))],
            ["Resolution/information contribution", _fmt(verdict.get("resolution_gap_contribution"))],
            ["Uncertainty contribution", _fmt(verdict.get("uncertainty_gap_contribution"))],
            ["Gap identity residual", _fmt(verdict.get("gap_identity_residual"), 12)],
            ["Model effective bands", _fmt(verdict.get("model_effective_bands"), 4)],
            ["Market effective bands", _fmt(verdict.get("market_effective_bands"), 4)],
            ["Effective-band gap", _fmt(verdict.get("effective_band_gap_model_minus_market"), 4)],
            ["Model top probability", _fmt(verdict.get("model_top_probability"), 4)],
            ["Market top probability", _fmt(verdict.get("market_top_probability"), 4)],
            [
                "Model mean categorical mass",
                _fmt(verdict.get("model_mean_probability_mass"), 6),
            ],
            [
                "Market mean raw categorical mass",
                _fmt(verdict.get("market_mean_raw_probability_mass"), 6),
            ],
        ],
    )
    lines += [
        "",
        "The exact CORP/isotonic Murphy identity is `Brier = reliability - resolution + uncertainty`.",
        "Resolution here measures outcome separation/information after monotone calibration; the",
        "effective-band and top-probability rows provide the direct categorical sharpness check.",
        "",
        "## Population and integrity",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Scored rows", population.get("scored_row_count")],
            ["Complete partitions", population.get("complete_partition_count")],
            [
                "Hourly-normalized partitions",
                population.get("hourly_normalized_partition_count"),
            ],
            [
                "Target-day hourly-normalized partitions",
                population.get("target_day_hourly_normalized_partition_count"),
            ],
            ["Markets", population.get("market_count")],
            ["Incomplete market partitions", population.get("incomplete_market_partition_count")],
            ["Invalid partitions", population.get("invalid_partition_count")],
            [
                "Scored non-single-winner collision partitions",
                population.get("non_single_winner_partition_count"),
            ],
            ["Candidate mass violations", population.get("candidate_mass_violation_count")],
            ["Maximum candidate mass residual", _fmt(population.get("candidate_max_abs_mass_residual"), 12)],
            [
                "Matched feature-context partitions",
                population.get("matched_feature_partition_count"),
            ],
            [
                "Feature-context match ratio",
                _fmt(population.get("matched_feature_partition_ratio"), 4),
            ],
            [
                "Max export/feature snapshot delta (seconds)",
                _fmt(population.get("capture_alignment_max_abs_seconds"), 6),
            ],
            [
                "Hashed feature inputs",
                (population.get("feature_context") or {}).get("feature_file_count"),
            ],
            [
                "Feature input-set SHA-256",
                (population.get("feature_context") or {}).get(
                    "feature_input_set_sha256"
                ),
            ],
        ],
    )
    lines += [
        "",
        "## Murphy decomposition: pooled and per market",
        "",
        "The pooled headline is the row-weighted mean of exact per-market components, avoiding",
        "cross-market base-rate mixing while preserving the exact pooled Brier score.",
        "",
    ]
    lines += markdown_table(
        [
            "Scope",
            "N",
            "Model BS",
            "Model REL",
            "Model RES",
            "UNC",
            "Market BS",
            "Market REL",
            "Market RES",
            "Gap",
            "Problem",
        ],
        [
            [
                row.get("scope"),
                (row.get("model") or {}).get("n"),
                _fmt((row.get("model") or {}).get("brier")),
                _fmt((row.get("model") or {}).get("reliability")),
                _fmt((row.get("model") or {}).get("resolution")),
                _fmt((row.get("model") or {}).get("uncertainty")),
                _fmt((row.get("market") or {}).get("brier")),
                _fmt((row.get("market") or {}).get("reliability")),
                _fmt((row.get("market") or {}).get("resolution")),
                _fmt((row.get("comparison") or {}).get("brier_gap")),
                (row.get("comparison") or {}).get("problem_type"),
            ]
            for row in payload.get("decomposition") or []
        ],
    )
    sensitivity = payload.get("global_pool_sensitivity") or {}
    lines += [
        "",
        "### Direct global-pool sensitivity",
        "",
        "This sensitivity runs CORP once across all markets. It is not the headline because",
        "location mixing can appear as forecast resolution.",
        "",
    ]
    lines += markdown_table(
        [
            "Model REL",
            "Model RES",
            "Market REL",
            "Market RES",
            "Calibration share",
            "Resolution share",
        ],
        [
            [
                _fmt((sensitivity.get("model") or {}).get("reliability")),
                _fmt((sensitivity.get("model") or {}).get("resolution")),
                _fmt((sensitivity.get("market") or {}).get("reliability")),
                _fmt((sensitivity.get("market") or {}).get("resolution")),
                _fmt(
                    (sensitivity.get("comparison") or {}).get(
                        "calibration_share_of_gap"
                    ),
                    4,
                ),
                _fmt(
                    (sensitivity.get("comparison") or {}).get(
                        "resolution_share_of_gap"
                    ),
                    4,
                ),
            ]
        ],
    )
    lines += [
        "",
        "## Named reporting cuts",
        "",
        "`all_hours` preserves every accepted comparator snapshot. The named hour cuts below",
        "use the earliest market-local target-day capture in each market-day/hour, so polling",
        "bursts receive no extra weight and post-midnight evidence cannot enter a target-day cut.",
        "",
    ]
    lines += markdown_table(
        ["Cut", "N", "Days", "Model BS", "Market BS", "Gap", "Gap/UNC", "Gap/market"],
        [
            [
                row.get("label"),
                row.get("n"),
                row.get("market_days"),
                _fmt(row.get("model_brier")),
                _fmt(row.get("market_brier")),
                _fmt(row.get("brier_gap")),
                _fmt(row.get("gap_over_uncertainty"), 4),
                _fmt(row.get("gap_over_market_brier"), 4),
            ]
            for row in payload.get("named_hour_slices") or []
        ],
    )
    lines += ["", "## By local capture hour", ""]
    lines += markdown_table(
        ["Hour", "N", "Days", "Model BS", "Market BS", "Gap", "Gap/UNC", "Gap/market"],
        [
            [
                row.get("label"),
                row.get("n"),
                row.get("market_days"),
                _fmt(row.get("model_brier")),
                _fmt(row.get("market_brier")),
                _fmt(row.get("brier_gap")),
                _fmt(row.get("gap_over_uncertainty"), 4),
                _fmt(row.get("gap_over_market_brier"), 4),
            ]
            for row in payload.get("hour_slices") or []
        ],
    )
    lines += [
        "",
        "## By lead to target-day end",
        "",
        "Lead is the hours remaining until local midnight ending the target date; it is a",
        "transparent day-end proxy, not a claim that the realized high occurs at midnight.",
        "",
    ]
    lines += markdown_table(
        ["Lead", "N", "Days", "Model BS", "Market BS", "Gap", "Gap/UNC", "Gap/market"],
        [
            [
                row.get("label"),
                row.get("n"),
                row.get("market_days"),
                _fmt(row.get("model_brier")),
                _fmt(row.get("market_brier")),
                _fmt(row.get("brier_gap")),
                _fmt(row.get("gap_over_uncertainty"), 4),
                _fmt(row.get("gap_over_market_brier"), 4),
            ]
            for row in payload.get("lead_time_slices") or []
        ],
    )
    lines += ["", "## Worst market-day/hour losses", ""]
    lines += [
        "Observation volatility requires at least two captured temperatures in the trailing",
        "two-hour window. `unknown` is retained as an explicit coverage limitation and must not",
        "be interpreted as low volatility.",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Date",
            "Hour",
            "Gap",
            "Gap/UNC",
            "Regime",
            "Forecast spread",
            "Boundary",
            "Obs volatility",
            "Source state",
        ],
        [
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("hour_label"),
                _fmt(row.get("brier_gap")),
                _fmt(row.get("gap_over_uncertainty"), 4),
                row.get("regime"),
                row.get("forecast_disagreement_bucket"),
                row.get("boundary_proximity_bucket"),
                row.get("observation_volatility_bucket"),
                row.get("source_freshness_state"),
            ]
            for row in (payload.get("worst_market_day_hours") or [])[:20]
        ],
    )
    lines += ["", "## Loss taxonomy", ""]
    for dimension, rows in (payload.get("taxonomy") or {}).items():
        lines += [f"### {dimension}", ""]
        lines += markdown_table(
            ["Bucket", "Day-hours", "Positive day-hours", "Mean gap", "Positive excess", "Share"],
            [
                [
                    row.get("bucket"),
                    row.get("day_hours"),
                    row.get("positive_gap_day_hours"),
                    _fmt(row.get("mean_brier_gap")),
                    _fmt(row.get("positive_excess_loss")),
                    _fmt(row.get("share_of_positive_excess_loss"), 4),
                ]
                for row in rows
            ],
        )
        lines.append("")
    lines += ["## What would have to be true for the gap to close?", ""]
    for row in payload.get("information_requirements") or []:
        lines.append(f"- **{row.get('condition')}** {row.get('implication')}")
    lines += [
        "",
        "## Guardrail",
        "",
        payload.get("interpretation_guardrail") or "",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    payload: dict[str, Any],
    *,
    json_out: str | Path,
    report_out: str | Path,
    worst_cases_out: str | Path,
) -> tuple[Path, Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    cases_path = Path(worst_cases_out)
    for path in (json_path, report_path, cases_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(payload), encoding="utf-8")
    case_rows = payload.get("worst_market_day_hours") or []
    if case_rows:
        fieldnames = list(case_rows[0])
        with cases_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(case_rows)
    else:
        cases_path.write_text("", encoding="utf-8")
    return json_path, report_path, cases_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a read-only Murphy/Brier model-versus-market gap decomposition."
    )
    parser.add_argument("--variant-rows", default=str(DEFAULT_VARIANT_ROWS))
    parser.add_argument("--corpus-manifest", default=str(DEFAULT_CORPUS_MANIFEST))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--variant-id")
    parser.add_argument("--model-probability-column", default="probability")
    parser.add_argument("--market-probability-column", default="market_yes")
    parser.add_argument("--worst-case-limit", type=int, default=50)
    parser.add_argument("--code-identity")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--worst-cases-out", default=str(DEFAULT_WORST_CASES_OUT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_decomposition(
        variant_rows=args.variant_rows,
        corpus_manifest=args.corpus_manifest,
        snapshots_root=args.snapshots_root,
        variant_id=args.variant_id,
        model_probability_column=args.model_probability_column,
        market_probability_column=args.market_probability_column,
        worst_case_limit=args.worst_case_limit,
        code_identity=args.code_identity,
    )
    json_path, report_path, cases_path = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        worst_cases_out=args.worst_cases_out,
    )
    print(f"Skill-gap decomposition: {payload.get('status')}")
    print(f"Problem type: {(payload.get('pooled_verdict') or {}).get('problem_type')}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    print(f"Worst cases written to {cases_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
