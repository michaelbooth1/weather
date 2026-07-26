"""Read-only market-uncertainty and settled profit-edge analysis.

This module consumes the same already-settled categorical replay rows used by
the skill-gap decomposition.  It never fits or tunes a model.  Brier
comparisons retain the raw market YES prices used by the accepted scorer;
market probabilities are normalized only to classify categorical uncertainty.

The trading translation is deliberately simple and preregisterable: at the
earliest target-day capture for each market/day/local-hour, take at most one
contract whose model-implied edge remains strictly positive after the published
taker-fee formula.  Results are retrospective diagnostics, not a trading rule
or evidence of executable fills.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import stdev
from typing import Any, Iterable

from weather.market.market_registry import REGISTRY
from weather.reporting.formatting import markdown_table
from weather.reporting.research.skill_gap_decomposition import (
    MASS_TOLERANCE,
    _float,
    _is_verified_same_second_collision,
    _outcome,
    _parse_datetime,
    _partition_key,
    _read_json,
    _sha256,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("profit_edge_analysis")
TAKER_FEE_RATE = 0.05
MAKER_REBATE_POOL_RATE = 0.25
NORMAL_CI_Z = 1.96
EXPLOITABILITY_MIN_TRADES = 100
EXPLOITABILITY_MIN_MARKET_DAYS = 30
BOOTSTRAP_REPETITIONS = 10_000
SENSITIVITY_THRESHOLDS = (0.0, 0.03, 0.05, 0.08, 0.10)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def uncertainty_metrics(market_probabilities: Iterable[float]) -> dict[str, Any]:
    """Return normalized categorical uncertainty and the frozen named bucket."""

    raw = [float(value) for value in market_probabilities]
    if not raw or any(not math.isfinite(value) or value < 0.0 for value in raw):
        raise ValueError("market probabilities must be finite and non-negative")
    mass = sum(raw)
    if mass <= 0.0:
        raise ValueError("market probability mass must be positive")
    normalized = [value / mass for value in raw]
    top = max(normalized)
    if len(normalized) <= 1:
        entropy = 0.0
    else:
        entropy = -sum(value * math.log(value) for value in normalized if value > 0.0)
        entropy /= math.log(len(normalized))
    if top >= 0.95:
        bucket = "near_resolved_top_ge_0.95"
    elif top >= 0.80:
        bucket = "low_top_0.80_to_0.95"
    elif top >= 0.60:
        bucket = "moderate_top_0.60_to_0.80"
    else:
        bucket = "high_top_lt_0.60"
    return {
        "bucket": bucket,
        "raw_mass": mass,
        "top_probability": top,
        "distance_from_resolution": 1.0 - top,
        "normalized_entropy": entropy,
    }


def taker_fee_per_share(contract_price: float) -> float:
    """Return the published weather-contract taker fee for one share."""

    price = float(contract_price)
    if not 0.0 <= price <= 1.0:
        raise ValueError("contract price must be within [0, 1]")
    return TAKER_FEE_RATE * price * (1.0 - price)


def choose_naive_taker_trade(
    rows: list[dict[str, Any]],
    *,
    minimum_predicted_net_edge: float = 0.0,
    allowed_sides: frozenset[str] = frozenset({"YES", "NO"}),
) -> dict[str, Any] | None:
    """Choose the largest model-implied after-fee disagreement in a partition."""

    candidates = []
    for row in rows:
        model_yes = float(row["model_probability"])
        market_yes = float(row["market_probability"])
        if not 0.0 < market_yes < 1.0 or model_yes == market_yes:
            continue
        side = "YES" if model_yes > market_yes else "NO"
        if side not in allowed_sides:
            continue
        contract_price = market_yes if side == "YES" else 1.0 - market_yes
        model_side = model_yes if side == "YES" else 1.0 - model_yes
        fee = taker_fee_per_share(contract_price)
        predicted_gross_edge = model_side - contract_price
        predicted_net_edge = predicted_gross_edge - fee
        if predicted_net_edge <= 0.0 or predicted_net_edge < minimum_predicted_net_edge:
            continue
        candidates.append(
            {
                "band_key": str(row.get("band_key") or ""),
                "side": side,
                "contract_price": contract_price,
                "model_side_probability": model_side,
                "predicted_gross_edge_per_share": predicted_gross_edge,
                "taker_fee_per_share": fee,
                "predicted_net_edge_per_share": predicted_net_edge,
                "outcome": int(row["outcome"]),
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (-row["predicted_net_edge_per_share"], row["band_key"], row["side"]),
    )[0]


def _score_accumulator() -> dict[str, Any]:
    return {
        "partitions": 0,
        "rows": 0,
        "model_squared_error": 0.0,
        "market_squared_error": 0.0,
        "market_days": set(),
        "entropy_sum": 0.0,
        "distance_sum": 0.0,
        "raw_masses": [],
        "locked_partition_count": 0,
    }


def _add_partition_score(
    accumulator: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    market_id: str,
    target_date: str,
    uncertainty: dict[str, Any],
) -> None:
    accumulator["partitions"] += 1
    accumulator["market_days"].add((market_id, target_date))
    accumulator["entropy_sum"] += float(uncertainty["normalized_entropy"])
    accumulator["distance_sum"] += float(uncertainty["distance_from_resolution"])
    accumulator["raw_masses"].append(float(uncertainty["raw_mass"]))
    accumulator["locked_partition_count"] += int(
        float(uncertainty["top_probability"]) >= 0.99
    )
    for row in rows:
        model = float(row["model_probability"])
        market = float(row["market_probability"])
        outcome = int(row["outcome"])
        accumulator["rows"] += 1
        accumulator["model_squared_error"] += (model - outcome) ** 2
        accumulator["market_squared_error"] += (market - outcome) ** 2


def _summarize_score(
    label: str,
    accumulator: dict[str, Any],
    *,
    total_partitions: int,
    total_rows: int,
) -> dict[str, Any]:
    partitions = int(accumulator["partitions"])
    rows = int(accumulator["rows"])
    model_brier = accumulator["model_squared_error"] / rows if rows else None
    market_brier = accumulator["market_squared_error"] / rows if rows else None
    gap = (
        model_brier - market_brier
        if model_brier is not None and market_brier is not None
        else None
    )
    raw_masses = [float(value) for value in accumulator["raw_masses"]]
    return {
        "label": label,
        "partitions": partitions,
        "partition_population_weight": partitions / total_partitions if total_partitions else None,
        "rows": rows,
        "row_population_weight": rows / total_rows if total_rows else None,
        "market_days": len(accumulator["market_days"]),
        "mean_normalized_entropy": accumulator["entropy_sum"] / partitions if partitions else None,
        "mean_distance_from_resolution": (
            accumulator["distance_sum"] / partitions if partitions else None
        ),
        "mean_raw_market_mass": sum(raw_masses) / len(raw_masses) if raw_masses else None,
        "min_raw_market_mass": min(raw_masses) if raw_masses else None,
        "median_raw_market_mass": _quantile(raw_masses, 0.5),
        "p95_raw_market_mass": _quantile(raw_masses, 0.95),
        "max_raw_market_mass": max(raw_masses) if raw_masses else None,
        "raw_market_mass_within_0.05_count": sum(
            abs(value - 1.0) <= 0.05 for value in raw_masses
        ),
        "raw_market_mass_within_0.05_rate": (
            sum(abs(value - 1.0) <= 0.05 for value in raw_masses) / len(raw_masses)
            if raw_masses
            else None
        ),
        "locked_top_ge_0.99_partition_count": accumulator["locked_partition_count"],
        "model_brier": model_brier,
        "market_brier": market_brier,
        "brier_gap": gap,
        "model_squared_error_total": accumulator["model_squared_error"],
        "market_squared_error_total": accumulator["market_squared_error"],
        "signed_excess_loss_total": (
            accumulator["model_squared_error"] - accumulator["market_squared_error"]
        ),
    }


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be within [0, 1]")
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _complete_trade(
    chosen: dict[str, Any],
    *,
    market_id: str,
    target_date: str,
    snapshot_id: str,
    capture_hour: int,
    uncertainty: dict[str, Any],
) -> dict[str, Any]:
    side_outcome = chosen["outcome"] if chosen["side"] == "YES" else 1 - chosen["outcome"]
    price = float(chosen["contract_price"])
    gross = side_outcome - price
    fee = float(chosen["taker_fee_per_share"])
    taker_net = gross - fee
    maker_sensitivity = gross + MAKER_REBATE_POOL_RATE * fee
    return {
        "market_id": market_id,
        "target_date": target_date,
        "market_day": f"{market_id}|{target_date}",
        "snapshot_id": snapshot_id,
        "capture_hour": capture_hour,
        "uncertainty_bucket": uncertainty["bucket"],
        "normalized_entropy": uncertainty["normalized_entropy"],
        "market_top_probability": uncertainty["top_probability"],
        **chosen,
        "gross_pnl_per_share": gross,
        "taker_net_pnl_per_share": taker_net,
        "maker_rebate_sensitivity_per_share": maker_sensitivity,
        "gross_pnl_per_dollar_notional": gross / price,
        "taker_net_pnl_per_dollar_notional": taker_net / price,
        "maker_rebate_sensitivity_per_dollar_notional": maker_sensitivity / price,
    }


def _bootstrap_target_date_blocks_ci(
    date_blocks: dict[str, list[float]],
    *,
    label: str,
    repetitions: int = BOOTSTRAP_REPETITIONS,
) -> tuple[float | None, float | None]:
    if len(date_blocks) < 2 or repetitions <= 0:
        return None, None
    seed_material = hashlib.sha256(
        f"profit-edge-v0.1|{label}|20260726".encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(seed_material[:8], "big"))
    target_dates = sorted(date_blocks)
    count = len(target_dates)
    samples = []
    for _ in range(repetitions):
        sampled_market_days = []
        for _ in range(count):
            sampled_market_days.extend(date_blocks[target_dates[rng.randrange(count)]])
        samples.append(sum(sampled_market_days) / len(sampled_market_days))
    return _quantile(samples, 0.025), _quantile(samples, 0.975)


def summarize_trades(
    label: str,
    trades: list[dict[str, Any]],
    *,
    eligible_partitions: int | None = None,
) -> dict[str, Any]:
    """Summarize trades with equal-weighted market-day inference."""

    if not trades:
        return {
            "label": label,
            "trades": 0,
            "eligible_partitions": eligible_partitions,
            "trade_rate": (
                0.0 if eligible_partitions is not None and eligible_partitions > 0 else None
            ),
            "market_days": 0,
            "mean_taker_net_pnl_per_share": None,
            "market_day_mean_taker_net_pnl_per_share": None,
            "market_day_mean_taker_net_pnl_per_share_ci95_low": None,
            "market_day_mean_taker_net_pnl_per_share_ci95_high": None,
            "positive_market_day_rate": None,
            "meets_exploitability_rule": False,
        }
    by_day: dict[str, list[float]] = defaultdict(list)
    market_day_target_dates: dict[str, str] = {}
    for trade in trades:
        by_day[trade["market_day"]].append(float(trade["taker_net_pnl_per_share"]))
        existing_target_date = market_day_target_dates.setdefault(
            str(trade["market_day"]),
            str(trade["target_date"]),
        )
        if existing_target_date != str(trade["target_date"]):
            raise ValueError("market-day trade group spans multiple target dates")
    day_mean_by_key = {
        market_day: sum(values) / len(values)
        for market_day, values in sorted(by_day.items())
    }
    day_means = list(day_mean_by_key.values())
    date_blocks: dict[str, list[float]] = defaultdict(list)
    for market_day, market_day_mean in day_mean_by_key.items():
        date_blocks[market_day_target_dates[market_day]].append(market_day_mean)
    day_mean = sum(day_means) / len(day_means)
    standard_error = (
        stdev(day_means) / math.sqrt(len(day_means)) if len(day_means) >= 2 else None
    )
    ci_low = day_mean - NORMAL_CI_Z * standard_error if standard_error is not None else None
    ci_high = day_mean + NORMAL_CI_Z * standard_error if standard_error is not None else None
    bootstrap_low, bootstrap_high = _bootstrap_target_date_blocks_ci(
        date_blocks,
        label=label,
    )
    leave_one_date_out_means = []
    date_means = {
        target_date: sum(values) / len(values)
        for target_date, values in date_blocks.items()
    }
    if len(date_means) >= 2:
        for omitted_date in sorted(date_means):
            retained = [
                value
                for target_date, values in date_blocks.items()
                if target_date != omitted_date
                for value in values
            ]
            leave_one_date_out_means.append(sum(retained) / len(retained))
    positive_day_rate = sum(value > 0.0 for value in day_means) / len(day_means)
    mean_taker = sum(float(row["taker_net_pnl_per_share"]) for row in trades) / len(trades)
    meets = (
        len(trades) >= EXPLOITABILITY_MIN_TRADES
        and len(day_means) >= EXPLOITABILITY_MIN_MARKET_DAYS
        and mean_taker > 0.0
        and ci_low is not None
        and ci_low > 0.0
        and positive_day_rate > 0.5
    )

    def mean(field: str) -> float:
        return sum(float(row[field]) for row in trades) / len(trades)

    return {
        "label": label,
        "trades": len(trades),
        "eligible_partitions": eligible_partitions,
        "trade_rate": (
            len(trades) / eligible_partitions
            if eligible_partitions is not None and eligible_partitions > 0
            else None
        ),
        "market_days": len(day_means),
        "markets": len({str(row["market_id"]) for row in trades if "market_id" in row}),
        "target_dates": len(date_blocks),
        "mean_contract_price": mean("contract_price"),
        "mean_predicted_gross_edge_per_share": mean("predicted_gross_edge_per_share"),
        "mean_predicted_net_edge_per_share": mean("predicted_net_edge_per_share"),
        "mean_taker_fee_per_share": mean("taker_fee_per_share"),
        "total_taker_fees_per_share_positions": sum(
            float(row["taker_fee_per_share"]) for row in trades
        ),
        "mean_gross_pnl_per_share": mean("gross_pnl_per_share"),
        "mean_taker_net_pnl_per_share": mean_taker,
        "total_taker_net_pnl_per_share_positions": sum(
            float(row["taker_net_pnl_per_share"]) for row in trades
        ),
        "population_taker_net_contribution_per_eligible_partition": (
            sum(float(row["taker_net_pnl_per_share"]) for row in trades)
            / eligible_partitions
            if eligible_partitions is not None and eligible_partitions > 0
            else None
        ),
        "mean_maker_rebate_sensitivity_per_share": mean(
            "maker_rebate_sensitivity_per_share"
        ),
        "mean_gross_pnl_per_dollar_notional": mean("gross_pnl_per_dollar_notional"),
        "mean_taker_net_pnl_per_dollar_notional": mean(
            "taker_net_pnl_per_dollar_notional"
        ),
        "mean_maker_rebate_sensitivity_per_dollar_notional": mean(
            "maker_rebate_sensitivity_per_dollar_notional"
        ),
        "market_day_mean_taker_net_pnl_per_share": day_mean,
        "market_day_mean_taker_net_pnl_per_share_ci95_low": ci_low,
        "market_day_mean_taker_net_pnl_per_share_ci95_high": ci_high,
        "date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_low": bootstrap_low,
        "date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_high": bootstrap_high,
        "leave_one_date_out_min_mean_taker_net_pnl_per_share": (
            min(leave_one_date_out_means) if leave_one_date_out_means else None
        ),
        "positive_market_day_rate": positive_day_rate,
        "positive_target_date_rate": (
            sum(value > 0.0 for value in date_means.values()) / len(date_means)
        ),
        "negative_trade_count": sum(
            float(row["taker_net_pnl_per_share"]) < 0.0 for row in trades
        ),
        "negative_trade_rate": sum(
            float(row["taker_net_pnl_per_share"]) < 0.0 for row in trades
        )
        / len(trades),
        "worst_trade_taker_net_pnl_per_share": min(
            float(row["taker_net_pnl_per_share"]) for row in trades
        ),
        "yes_trade_count": sum(str(row.get("side")) == "YES" for row in trades),
        "no_trade_count": sum(str(row.get("side")) == "NO" for row in trades),
        "meets_exploitability_rule": meets,
    }


def _trade_slices(
    trades: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    opportunity_groups: dict[str, int] = defaultdict(int)
    groups["all_target_day_hours"].extend(trades)
    opportunity_groups["all_target_day_hours"] = len(opportunities)
    for opportunity in opportunities:
        hour = int(opportunity["capture_hour"])
        bucket = str(opportunity["uncertainty_bucket"])
        opportunity_groups[f"hour_{hour:02d}"] += 1
        opportunity_groups[f"uncertainty__{bucket}"] += 1
        opportunity_groups[f"hour_{hour:02d}__{bucket}"] += 1
        if 18 <= hour <= 23:
            opportunity_groups["evening_18_23"] += 1
            opportunity_groups[f"evening_18_23__{bucket}"] += 1
    for trade in trades:
        hour = int(trade["capture_hour"])
        bucket = str(trade["uncertainty_bucket"])
        groups[f"hour_{hour:02d}"].append(trade)
        groups[f"uncertainty__{bucket}"].append(trade)
        groups[f"hour_{hour:02d}__{bucket}"].append(trade)
        if 18 <= hour <= 23:
            groups["evening_18_23"].append(trade)
            groups[f"evening_18_23__{bucket}"].append(trade)
    labels = sorted(set(groups) | set(opportunity_groups))
    return [
        summarize_trades(
            label,
            groups[label],
            eligible_partitions=opportunity_groups[label],
        )
        for label in labels
    ]


def _first_trade_per_market_day(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first: dict[str, dict[str, Any]] = {}
    for trade in sorted(
        trades,
        key=lambda row: (
            row["market_id"],
            row["target_date"],
            int(row["capture_hour"]),
            row["snapshot_id"],
        ),
    ):
        first.setdefault(str(trade["market_day"]), trade)
    return list(first.values())


def build_profit_edge_analysis(
    *,
    variant_rows: str | Path,
    corpus_manifest: str | Path,
    variant_id: str | None = None,
    model_probability_column: str = "probability",
    market_probability_column: str = "market_yes",
    expected_variant_sha256: str | None = None,
    expected_manifest_sha256: str | None = None,
    generated_at_utc: str | None = None,
    code_identity: str | None = None,
) -> dict[str, Any]:
    """Build the frozen, settled, read-only profit-relevance diagnostic."""

    variant_path = Path(variant_rows)
    manifest_path = Path(corpus_manifest)
    before = {
        "variant_rows_bytes": variant_path.stat().st_size,
        "variant_rows_sha256": _sha256(variant_path),
        "corpus_manifest_bytes": manifest_path.stat().st_size,
        "corpus_manifest_sha256": _sha256(manifest_path),
    }
    if expected_variant_sha256 and before["variant_rows_sha256"] != expected_variant_sha256:
        raise ValueError(
            "variant rows SHA-256 does not match frozen identity: "
            f"{before['variant_rows_sha256']} != {expected_variant_sha256}"
        )
    if expected_manifest_sha256 and before["corpus_manifest_sha256"] != expected_manifest_sha256:
        raise ValueError(
            "corpus manifest SHA-256 does not match frozen identity: "
            f"{before['corpus_manifest_sha256']} != {expected_manifest_sha256}"
        )
    manifest = _read_json(manifest_path)
    expected_band_counts = {
        (str(entry.get("market_id") or ""), str(entry.get("target_date") or "")): int(
            entry["band_count"]
        )
        for entry in (manifest.get("entries") or [])
        if entry.get("market_id")
        and entry.get("target_date")
        and entry.get("band_count") not in (None, "")
    }

    all_scores = _score_accumulator()
    uncertainty_scores: dict[str, dict[str, Any]] = defaultdict(_score_accumulator)
    evening_scores: dict[str, dict[str, Any]] = defaultdict(_score_accumulator)
    hour_scores: dict[int, dict[str, Any]] = defaultdict(_score_accumulator)
    raw_mass_near_unit_score = _score_accumulator()
    locked_score = _score_accumulator()
    opportunities: list[dict[str, Any]] = []
    trade_sets: dict[str, list[dict[str, Any]]] = {
        f"symmetric_tau_{threshold:.2f}": [] for threshold in SENSITIVITY_THRESHOLDS
    }
    trade_sets["yes_only_tau_0.00"] = []
    observed_variant_ids: set[str] = set()
    seen_partition_keys: set[tuple[str, str, str]] = set()
    seen_hour_keys: set[tuple[str, str, str, int]] = set()
    last_capture_by_market_day: dict[tuple[str, str], datetime] = {}
    counters = defaultdict(int)
    max_model_mass_residual = 0.0
    current_key: tuple[str, str, str] | None = None
    partition_rows: list[dict[str, Any]] = []

    def consume(rows: list[dict[str, Any]]) -> None:
        nonlocal max_model_mass_residual
        if not rows:
            return
        counters["partition_count"] += 1
        model_values = [row.get("model_probability") for row in rows]
        market_values = [row.get("market_probability") for row in rows]
        if any(value is None for value in model_values + market_values):
            raise ValueError("complete model and market probability partitions are required")
        if any(not 0.0 <= float(value) <= 1.0 for value in model_values + market_values):
            raise ValueError("model and market probabilities must be within [0, 1]")
        model_mass = sum(float(value) for value in model_values)
        residual = abs(model_mass - 1.0)
        max_model_mass_residual = max(max_model_mass_residual, residual)
        if residual > MASS_TOLERANCE:
            raise ValueError(
                f"candidate probability mass violated (residual {residual:.12g})"
            )
        if any(row.get("outcome") not in (0, 1) for row in rows):
            raise ValueError("binary settled outcomes are required")

        market_id = rows[0]["market_id"]
        target_date = rows[0]["target_date"]
        snapshot_id = rows[0]["snapshot_id"]
        expected_count = expected_band_counts.get((market_id, target_date))
        winner_count = sum(int(row["outcome"]) for row in rows)
        collision = winner_count != 1
        signatures = {
            (
                str(row.get("band_key") or ""),
                str(row.get("bin_type") or ""),
                str(row.get("bin_value") or ""),
            )
            for row in rows
        }
        if collision:
            if not _is_verified_same_second_collision(rows):
                raise ValueError("non-one-hot partition is not a verified same-second collision")
            if expected_count is not None and len(rows) != 2 * expected_count:
                raise ValueError("collision band count does not match the frozen manifest")
            counters["collision_partition_count"] += 1
        else:
            if len(signatures) != len(rows):
                raise ValueError("ordinary partition contains duplicate band keys")
            if expected_count is not None and len(rows) != expected_count:
                raise ValueError("partition band count does not match the frozen manifest")

        uncertainty_rows = rows
        if collision:
            first_capture = min(
                row["captured_at_local"] for row in rows if row["captured_at_local"] is not None
            )
            uncertainty_rows = [
                row for row in rows if row["captured_at_local"] == first_capture
            ]
        uncertainty = uncertainty_metrics(
            float(row["market_probability"]) for row in uncertainty_rows
        )
        _add_partition_score(
            all_scores,
            rows,
            market_id=market_id,
            target_date=target_date,
            uncertainty=uncertainty,
        )
        _add_partition_score(
            uncertainty_scores[uncertainty["bucket"]],
            rows,
            market_id=market_id,
            target_date=target_date,
            uncertainty=uncertainty,
        )
        if abs(float(uncertainty["raw_mass"]) - 1.0) <= 0.05:
            _add_partition_score(
                raw_mass_near_unit_score,
                rows,
                market_id=market_id,
                target_date=target_date,
                uncertainty=uncertainty,
            )
        if float(uncertainty["top_probability"]) >= 0.99:
            _add_partition_score(
                locked_score,
                rows,
                market_id=market_id,
                target_date=target_date,
                uncertainty=uncertainty,
            )

        captured = rows[0].get("captured_at_local")
        if captured is None or captured.tzinfo is None:
            raise ValueError("timezone-aware captured_at_local is required")
        spec = REGISTRY.get(market_id)
        local = captured.astimezone(spec.tz) if spec is not None else captured
        day_key = (market_id, target_date)
        previous = last_capture_by_market_day.get(day_key)
        if previous is not None and local < previous:
            raise ValueError(
                "variant rows are not capture-time ordered within market-day"
            )
        last_capture_by_market_day[day_key] = local
        try:
            is_target_day = local.date() == date.fromisoformat(target_date)
        except ValueError as exc:
            raise ValueError(f"invalid target_date {target_date!r}") from exc
        if is_target_day:
            counters["target_day_partition_count"] += 1
        else:
            counters["non_target_day_partition_count"] += 1
        representative_key = (market_id, target_date, local.date().isoformat(), local.hour)
        representative = representative_key not in seen_hour_keys
        if representative:
            seen_hour_keys.add(representative_key)
            counters["hourly_representative_partition_count"] += 1
        if not representative or not is_target_day:
            return

        counters["target_day_hourly_representative_partition_count"] += 1
        _add_partition_score(
            hour_scores[local.hour],
            rows,
            market_id=market_id,
            target_date=target_date,
            uncertainty=uncertainty,
        )
        if 18 <= local.hour <= 23:
            _add_partition_score(
                evening_scores[uncertainty["bucket"]],
                rows,
                market_id=market_id,
                target_date=target_date,
                uncertainty=uncertainty,
            )
        if collision:
            counters["collision_trade_partition_skips"] += 1
            return
        if not any(0.0 < float(row["market_probability"]) < 1.0 for row in rows):
            counters["no_non_extreme_contract_partition_count"] += 1
            return
        opportunity = {
            "market_id": market_id,
            "target_date": target_date,
            "market_day": f"{market_id}|{target_date}",
            "snapshot_id": snapshot_id,
            "capture_hour": local.hour,
            "uncertainty_bucket": uncertainty["bucket"],
        }
        opportunities.append(opportunity)
        primary_chosen = False
        for threshold in SENSITIVITY_THRESHOLDS:
            key = f"symmetric_tau_{threshold:.2f}"
            chosen = choose_naive_taker_trade(
                rows,
                minimum_predicted_net_edge=threshold,
            )
            if chosen is not None:
                if threshold == 0.0:
                    primary_chosen = True
                trade_sets[key].append(
                    _complete_trade(
                        chosen,
                        market_id=market_id,
                        target_date=target_date,
                        snapshot_id=snapshot_id,
                        capture_hour=local.hour,
                        uncertainty=uncertainty,
                    )
                )
        yes_only = choose_naive_taker_trade(
            rows,
            allowed_sides=frozenset({"YES"}),
        )
        if yes_only is not None:
            trade_sets["yes_only_tau_0.00"].append(
                _complete_trade(
                    yes_only,
                    market_id=market_id,
                    target_date=target_date,
                    snapshot_id=snapshot_id,
                    capture_hour=local.hour,
                    uncertainty=uncertainty,
                )
            )
        if not primary_chosen:
            counters["no_positive_predicted_edge_partition_count"] += 1

    with variant_path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            counters["source_row_count"] += 1
            row_variant = str(raw.get("variant_id") or "")
            observed_variant_ids.add(row_variant)
            if variant_id is not None and row_variant != variant_id:
                continue
            if variant_id is None and len(observed_variant_ids) > 1:
                raise ValueError(
                    "variant rows contain multiple variant_id values; pass --variant-id"
                )
            key = _partition_key(raw)
            if not all(key):
                raise ValueError("variant row is missing market/date/snapshot partition key")
            if current_key is not None and key != current_key:
                consume(partition_rows)
                seen_partition_keys.add(current_key)
                partition_rows = []
                if key in seen_partition_keys:
                    raise ValueError("variant rows are not partition-contiguous")
            current_key = key
            partition_rows.append(
                {
                    "market_id": key[0],
                    "target_date": key[1],
                    "snapshot_id": key[2],
                    "band_key": raw.get("band_key"),
                    "bin_type": raw.get("bin_type"),
                    "bin_value": raw.get("bin_value"),
                    "model_probability": _float(raw.get(model_probability_column)),
                    "market_probability": _float(raw.get(market_probability_column)),
                    "outcome": _outcome(raw.get("outcome")),
                    "captured_at_local": _parse_datetime(raw.get("captured_at_local")),
                }
            )
            counters["selected_row_count"] += 1
    consume(partition_rows)

    if not all_scores["partitions"]:
        raise ValueError("no complete selected partitions were found")
    after = {
        "variant_rows_bytes": variant_path.stat().st_size,
        "variant_rows_sha256": _sha256(variant_path),
        "corpus_manifest_bytes": manifest_path.stat().st_size,
        "corpus_manifest_sha256": _sha256(manifest_path),
    }
    if before != after:
        raise RuntimeError("frozen input identity changed while being analyzed")

    total_partitions = int(all_scores["partitions"])
    total_rows = int(all_scores["rows"])
    uncertainty_rows = [
        _summarize_score(
            label,
            uncertainty_scores[label],
            total_partitions=total_partitions,
            total_rows=total_rows,
        )
        for label in (
            "near_resolved_top_ge_0.95",
            "low_top_0.80_to_0.95",
            "moderate_top_0.60_to_0.80",
            "high_top_lt_0.60",
        )
        if label in uncertainty_scores
    ]
    target_hour_partitions = sum(row["partitions"] for row in hour_scores.values())
    target_hour_rows = sum(row["rows"] for row in hour_scores.values())
    hour_rows = [
        _summarize_score(
            f"{hour:02d}:00",
            hour_scores[hour],
            total_partitions=target_hour_partitions,
            total_rows=target_hour_rows,
        )
        for hour in sorted(hour_scores)
    ]
    evening_partitions = sum(row["partitions"] for row in evening_scores.values())
    evening_row_count = sum(row["rows"] for row in evening_scores.values())
    evening_rows = [
        _summarize_score(
            label,
            evening_scores[label],
            total_partitions=evening_partitions,
            total_rows=evening_row_count,
        )
        for label in (
            "near_resolved_top_ge_0.95",
            "low_top_0.80_to_0.95",
            "moderate_top_0.60_to_0.80",
            "high_top_lt_0.60",
        )
        if label in evening_scores
    ]
    signed_evening_gap = sum(float(row["signed_excess_loss_total"]) for row in evening_rows)
    for row in evening_rows:
        row["share_of_signed_evening_excess_loss"] = (
            row["signed_excess_loss_total"] / signed_evening_gap
            if signed_evening_gap
            else None
        )

    trades = trade_sets["symmetric_tau_0.00"]
    trade_slices = _trade_slices(trades, opportunities)
    pnl_ranking = sorted(
        trade_slices,
        key=lambda row: (
            -(
                float(row["total_taker_net_pnl_per_share_positions"])
                if row.get("total_taker_net_pnl_per_share_positions") is not None
                else -math.inf
            ),
            -int(row.get("eligible_partitions") or 0),
            str(row["label"]),
        ),
    )
    exploitable = [row for row in trade_slices if row["meets_exploitability_rule"]]
    evening_opportunities = [
        row for row in opportunities if 18 <= int(row["capture_hour"]) <= 23
    ]
    evening_trades = [row for row in trades if 18 <= int(row["capture_hour"]) <= 23]
    evening_trade = next(
        (row for row in trade_slices if row["label"] == "evening_18_23"),
        summarize_trades(
            "evening_18_23",
            [],
            eligible_partitions=len(evening_opportunities),
        ),
    )
    event_day_evening_trades = _first_trade_per_market_day(evening_trades)
    evening_event_day_liability = summarize_trades(
        "evening_18_23_first_trade_per_market_day",
        event_day_evening_trades,
        eligible_partitions=len(
            {str(row["market_day"]) for row in evening_opportunities}
        ),
    )
    sensitivity_rows = []
    for label, sensitivity_trades in sorted(trade_sets.items()):
        sensitivity_evening = [
            row
            for row in sensitivity_trades
            if 18 <= int(row["capture_hour"]) <= 23
        ]
        sensitivity_rows.append(
            {
                "label": label,
                "all_target_day_hours": summarize_trades(
                    f"{label}__all_target_day_hours",
                    sensitivity_trades,
                    eligible_partitions=len(opportunities),
                ),
                "evening_18_23_opportunities": summarize_trades(
                    f"{label}__evening_18_23_opportunities",
                    sensitivity_evening,
                    eligible_partitions=len(evening_opportunities),
                ),
                "evening_18_23_first_trade_per_market_day": summarize_trades(
                    f"{label}__evening_18_23_first_trade_per_market_day",
                    _first_trade_per_market_day(sensitivity_evening),
                    eligible_partitions=len(
                        {str(row["market_day"]) for row in evening_opportunities}
                    ),
                ),
            }
        )
    overall_score = _summarize_score(
        "all_settled_partitions",
        all_scores,
        total_partitions=total_partitions,
        total_rows=total_rows,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": "PASS",
        "evidence_classification": (
            "settled_read_only_diagnostic_not_fit_not_tuning_not_execution_evidence"
        ),
        "inputs": {
            "variant_rows": str(variant_path),
            "variant_rows_bytes": before["variant_rows_bytes"],
            "variant_rows_sha256": before["variant_rows_sha256"],
            "corpus_manifest": str(manifest_path),
            "corpus_manifest_bytes": before["corpus_manifest_bytes"],
            "corpus_manifest_sha256": before["corpus_manifest_sha256"],
            "requested_variant_id": variant_id,
            "observed_variant_ids": sorted(observed_variant_ids),
            "model_probability_column": model_probability_column,
            "market_probability_column": market_probability_column,
            "code_identity": code_identity,
        },
        "methodology": {
            "uncertainty": (
                "Raw categorical market YES prices are normalized within each partition only "
                "for top-probability, distance-from-resolution, and normalized Shannon entropy. "
                "Brier scoring retains raw market prices."
            ),
            "uncertainty_buckets": {
                "near_resolved_top_ge_0.95": "normalized market top probability >= 0.95",
                "low_top_0.80_to_0.95": "0.80 <= normalized market top probability < 0.95",
                "moderate_top_0.60_to_0.80": "0.60 <= normalized market top probability < 0.80",
                "high_top_lt_0.60": "normalized market top probability < 0.60",
            },
            "hourly_sampling": (
                "Earliest target-day partition for each market/date/market-local hour; "
                "polling bursts receive no additional weight."
            ),
            "naive_taker_rule": (
                "For every ordinary hourly representative, evaluate each non-extreme YES or "
                "complementary NO contract; subtract 0.05*p*(1-p) per share; select at most one "
                "strictly positive predicted-net edge, largest first with band-key tie break."
            ),
            "price_proxy": (
                "market_yes is the captured Gamma outcomePrices presentation value, not a CLOB "
                "best ask. Complementary 1-market_yes is a synthetic NO price. YES-only and "
                "fixed entry-threshold sensitivities are reported; none establishes fills, "
                "depth, spread, latency, or executability."
            ),
            "fixed_predicted_net_edge_thresholds_per_share": list(
                SENSITIVITY_THRESHOLDS
            ),
            "fees": {
                "taker_fee_per_share": "0.05 * contract_price * (1 - contract_price)",
                "maker_rebate_sensitivity": (
                    "gross realized P&L + 0.25 * taker fee; favorable sensitivity only. "
                    "No maker fill, pool share, or rebate eligibility is claimed."
                ),
            },
            "inference": (
                "Primary normal 95% interval over equal-weighted market-day mean taker P&L "
                "per share; fixed-seed 10,000-repetition target-date block bootstrap and "
                "leave-one-date-out minimum are reported as robustness sensitivities."
            ),
            "exploitable_subset_rule": {
                "minimum_trades": EXPLOITABILITY_MIN_TRADES,
                "minimum_market_days": EXPLOITABILITY_MIN_MARKET_DAYS,
                "mean_taker_pnl_per_share_strictly_positive": True,
                "market_day_ci95_low_strictly_positive": True,
                "positive_market_day_rate_strictly_greater_than": 0.5,
            },
            "no_training_or_tuning": True,
        },
        "population": {
            **dict(counters),
            "complete_partition_count": total_partitions,
            "scored_row_count": total_rows,
            "market_count": len({key[0] for key in all_scores["market_days"]}),
            "market_day_count": len(all_scores["market_days"]),
            "candidate_max_abs_mass_residual": max_model_mass_residual,
            "trade_count": len(trades),
            "profit_eligible_target_day_hour_partition_count": len(opportunities),
        },
        "overall_brier": overall_score,
        "uncertainty_brier": uncertainty_rows,
        "locked_top_ge_0.99_brier": _summarize_score(
            "locked_top_ge_0.99",
            locked_score,
            total_partitions=total_partitions,
            total_rows=total_rows,
        ),
        "raw_market_mass_within_0.05_brier_sensitivity": _summarize_score(
            "raw_market_mass_within_0.05",
            raw_mass_near_unit_score,
            total_partitions=total_partitions,
            total_rows=total_rows,
        ),
        "target_day_hour_brier": hour_rows,
        "evening_18_23_uncertainty_brier": evening_rows,
        "trade_slices": trade_slices,
        "profit_ranking": pnl_ranking,
        "fixed_rule_sensitivities": sensitivity_rows,
        "evening_18_23_naive_taker_liability": evening_trade,
        "evening_18_23_first_trade_per_market_day_liability": evening_event_day_liability,
        "exploitable_subsets": exploitable,
        "exploitable_subset_verdict": (
            f"{len(exploitable)} preregistered slice(s) pass the historical screen."
            if exploitable
            else "No preregistered slice passes the historical exploitability screen."
        ),
        "interpretation_guardrail": (
            "The outcomes were already settled. This retrospective translation does not establish "
            "future edge, executable prices, fill probability, maker eligibility, capacity, or "
            "profit. It authorizes no promotion, release, serving, scheduler, collector, sizing, "
            "or trading change."
        ),
    }


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Profit-relevant model-versus-market edge diagnostic",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        "",
        str(payload.get("exploitable_subset_verdict") or ""),
        "",
        "## Overall settled comparison",
        "",
    ]
    overall = payload.get("overall_brier") or {}
    lines += markdown_table(
        ["Partitions", "Rows", "Model Brier", "Market Brier", "Gap"],
        [[
            overall.get("partitions"),
            overall.get("rows"),
            _fmt(overall.get("model_brier")),
            _fmt(overall.get("market_brier")),
            _fmt(overall.get("brier_gap")),
        ]],
    )
    lines += ["", "## Brier by market uncertainty", ""]
    lines += markdown_table(
        [
            "Bucket",
            "Partitions",
            "Weight",
            "Entropy",
            "1 - top",
            "Raw mass",
            "Model BS",
            "Market BS",
            "Gap",
        ],
        [
            [
                row.get("label"),
                row.get("partitions"),
                _fmt(row.get("partition_population_weight"), 4),
                _fmt(row.get("mean_normalized_entropy"), 4),
                _fmt(row.get("mean_distance_from_resolution"), 4),
                _fmt(row.get("mean_raw_market_mass"), 4),
                _fmt(row.get("model_brier")),
                _fmt(row.get("market_brier")),
                _fmt(row.get("brier_gap")),
            ]
            for row in payload.get("uncertainty_brier") or []
        ],
    )
    lines += [
        "",
        "## Evening 18:00-23:00 loss concentration",
        "",
        "These are earliest target-day hourly captures; the market uncertainty bucket uses only",
        "prices available in that scored partition.",
        "",
    ]
    lines += markdown_table(
        ["Bucket", "Partitions", "Model BS", "Market BS", "Gap", "Signed gap share"],
        [
            [
                row.get("label"),
                row.get("partitions"),
                _fmt(row.get("model_brier")),
                _fmt(row.get("market_brier")),
                _fmt(row.get("brier_gap")),
                _fmt(row.get("share_of_signed_evening_excess_loss"), 4),
            ]
            for row in payload.get("evening_18_23_uncertainty_brier") or []
        ],
    )
    liability = payload.get("evening_18_23_naive_taker_liability") or {}
    event_day_liability = (
        payload.get("evening_18_23_first_trade_per_market_day_liability") or {}
    )
    lines += ["", "## Naive taker liability, 18:00-23:00", ""]
    lines += markdown_table(
        [
            "Counting",
            "Trades",
            "Days",
            "Total unit-share net",
            "Mean net/share",
            "CI95 low",
            "Date-bootstrap low",
            "Positive days",
        ],
        [
            [
                "hourly opportunities",
                liability.get("trades"),
                liability.get("market_days"),
                _fmt(liability.get("total_taker_net_pnl_per_share_positions")),
                _fmt(liability.get("mean_taker_net_pnl_per_share")),
                _fmt(
                    liability.get(
                        "market_day_mean_taker_net_pnl_per_share_ci95_low"
                    )
                ),
                _fmt(
                    liability.get(
                        "date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_low"
                    )
                ),
                _fmt(liability.get("positive_market_day_rate"), 4),
            ],
            [
                "first trade per market-day",
                event_day_liability.get("trades"),
                event_day_liability.get("market_days"),
                _fmt(
                    event_day_liability.get(
                        "total_taker_net_pnl_per_share_positions"
                    )
                ),
                _fmt(event_day_liability.get("mean_taker_net_pnl_per_share")),
                _fmt(
                    event_day_liability.get(
                        "market_day_mean_taker_net_pnl_per_share_ci95_low"
                    )
                ),
                _fmt(
                    event_day_liability.get(
                        "date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_low"
                    )
                ),
                _fmt(event_day_liability.get("positive_market_day_rate"), 4),
            ],
        ],
    )
    lines += [
        "",
        "## Historical slices",
        "",
        "The maker column is a favorable rebate sensitivity, not a claimed strategy return.",
        "",
    ]
    lines += markdown_table(
        [
            "Slice",
            "Eligible",
            "Trades",
            "Days",
            "Total unit-share net",
            "Taker/share",
            "CI95 low",
            "Date-bootstrap low",
            "Positive days",
            "Pass",
        ],
        [
            [
                row.get("label"),
                row.get("eligible_partitions"),
                row.get("trades"),
                row.get("market_days"),
                _fmt(
                    row.get("total_taker_net_pnl_per_share_positions")
                ),
                _fmt(row.get("mean_taker_net_pnl_per_share")),
                _fmt(row.get("market_day_mean_taker_net_pnl_per_share_ci95_low")),
                _fmt(
                    row.get(
                        "date_block_bootstrap_mean_taker_net_pnl_per_share_ci95_low"
                    )
                ),
                _fmt(row.get("positive_market_day_rate"), 4),
                row.get("meets_exploitability_rule"),
            ]
            for row in payload.get("profit_ranking") or []
        ],
    )
    lines += ["", "## Fixed-rule sensitivities", ""]
    lines += markdown_table(
        [
            "Rule",
            "All trades",
            "All net/share",
            "Evening trades",
            "Evening net/share",
            "First/day trades",
            "First/day net/share",
        ],
        [
            [
                row.get("label"),
                (row.get("all_target_day_hours") or {}).get("trades"),
                _fmt(
                    (row.get("all_target_day_hours") or {}).get(
                        "mean_taker_net_pnl_per_share"
                    )
                ),
                (row.get("evening_18_23_opportunities") or {}).get("trades"),
                _fmt(
                    (row.get("evening_18_23_opportunities") or {}).get(
                        "mean_taker_net_pnl_per_share"
                    )
                ),
                (row.get("evening_18_23_first_trade_per_market_day") or {}).get(
                    "trades"
                ),
                _fmt(
                    (row.get("evening_18_23_first_trade_per_market_day") or {}).get(
                        "mean_taker_net_pnl_per_share"
                    )
                ),
            ]
            for row in payload.get("fixed_rule_sensitivities") or []
        ],
    )
    lines += [
        "",
        "## Guardrail",
        "",
        str(payload.get("interpretation_guardrail") or ""),
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    payload: dict[str, Any],
    *,
    json_out: str | Path,
    report_out: str | Path,
    trade_slices_out: str | Path,
) -> tuple[Path, Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    slices_path = Path(trade_slices_out)
    for path in (json_path, report_path, slices_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(payload), encoding="utf-8")
    rows = payload.get("trade_slices") or []
    if rows:
        with slices_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    else:
        slices_path.write_text("", encoding="utf-8")
    return json_path, report_path, slices_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate a frozen settled skill-gap corpus into uncertainty and P&L cuts."
    )
    parser.add_argument("--variant-rows", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--variant-id")
    parser.add_argument("--model-probability-column", default="probability")
    parser.add_argument("--market-probability-column", default="market_yes")
    parser.add_argument("--expected-variant-sha256")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--code-identity")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--trade-slices-out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_profit_edge_analysis(
        variant_rows=args.variant_rows,
        corpus_manifest=args.corpus_manifest,
        variant_id=args.variant_id,
        model_probability_column=args.model_probability_column,
        market_probability_column=args.market_probability_column,
        expected_variant_sha256=args.expected_variant_sha256,
        expected_manifest_sha256=args.expected_manifest_sha256,
        code_identity=args.code_identity,
    )
    json_path, report_path, slices_path = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        trade_slices_out=args.trade_slices_out,
    )
    print(f"Profit-edge analysis: {payload['status']}")
    print(payload["exploitable_subset_verdict"])
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    print(f"Trade slices written to {slices_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
