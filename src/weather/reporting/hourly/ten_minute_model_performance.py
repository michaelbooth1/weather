"""Settlement-scored 10-minute model performance gate and watchlist."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from weather.backtesting.tape_scoring import timestamp_key
from weather.paths import data_path, relative_to_repo
from weather.reporting.hourly.candidate_hourly_performance import candidate_rows_corpus_hash, read_variant_rows
from weather.reporting.formatting import markdown_table
from weather.reporting.hourly.hourly_model_performance import (
    DEFAULT_BACKTEST_ROOT,
    DEFAULT_LABELS_CSV,
    DEFAULT_QUALITY_GRADES,
    DEFAULT_SNAPSHOTS_ROOT,
    FORECAST_CENTERING_BLEND_GRID,
    HOUR_REGIME_LABELS,
    MARKET_BLEND_GRID,
    PARTITION_POWER_GRID,
    DRIVER_NUMERIC_FIELDS,
    discover_labeled_folders,
    forecast_centering_rows,
    hour_regime,
    market_blend_rows,
    mean,
    partition_power_rows,
    score_folder,
    snapshot_partition_stats,
    summarize_rows,
)
from weather.reporting.serving_gates.model_scoring_liveness import attach_scoring_liveness, build_rerun_command
from weather.schema_registry import schema_version
from weather.scoring.metrics import (
    binary_log_loss,
    expected_calibration_error,
    safe_float,
    score_rows,
)


SCHEMA_VERSION = schema_version("ten_minute_model_performance")
TEN_MINUTE_GATE_SCHEMA_VERSION = schema_version("ten_minute_performance_gate")
CANDIDATE_TEN_MINUTE_GATE_SCHEMA_VERSION = schema_version("candidate_ten_minute_performance_gate")
DEFAULT_JSON_OUT = data_path() / "backtest" / "ten_minute_model_performance.json"
DEFAULT_REPORT_OUT = data_path() / "backtest" / "ten_minute_model_performance_report.md"
DEFAULT_SLOT_CSV_OUT = data_path() / "backtest" / "ten_minute_model_performance_by_slot.csv"
DEFAULT_CANDIDATE_CSV_OUT = data_path() / "backtest" / "ten_minute_item147_candidate_by_slot.csv"
DEFAULT_ITEM147_ROWS = data_path() / "backtest" / "item147_time_split_alpha_variant_rows.csv"
DEFAULT_MIN_ROWS = 30
DEFAULT_TOP_SLOTS = 20
DEFAULT_MIN_WEAK_MARKET_DAYS = 10
DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE = 0.003
DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE = 0.010
DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN = 0.0
DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE = 0.003
DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE = 0.010


REPLAY_PROBE_SPECS = {
    "market_blend": {
        "uses_market_prices": True,
        "description": "Blend model probability toward market yes price: (1-alpha)*model + alpha*market.",
        "grid": MARKET_BLEND_GRID,
        "transform_fn": market_blend_rows,
    },
    "partition_power": {
        "uses_market_prices": False,
        "description": "Normalize each snapshot partition after p**gamma; gamma < 1 softens, gamma > 1 sharpens.",
        "grid": PARTITION_POWER_GRID,
        "transform_fn": partition_power_rows,
    },
    "forecast_centering": {
        "uses_market_prices": False,
        "description": "Blend model probability toward a forecast-high anchored Gaussian band projection.",
        "grid": FORECAST_CENTERING_BLEND_GRID,
        "transform_fn": forecast_centering_rows,
    },
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def fmt_num(value: Any, digits: int = 4) -> str:
    number = safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def fmt_signed(value: Any, digits: int = 4) -> str:
    number = safe_float(value)
    if number is None:
        return "-"
    return f"{number:+.{digits}f}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    number = safe_float(value)
    if number is None:
        return "-"
    return f"{number * 100:.{digits}f}%"


def slot_minute(row: dict[str, Any]) -> int | None:
    minute = safe_int(row.get("capture_minute"))
    if minute is None or minute < 0:
        return None
    return (minute // 10) * 10


def slot_label(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value // 60:02d}:{value % 60:02d}"


def slot_regime(value: int | None) -> str | None:
    if value is None:
        return None
    return hour_regime(value // 60)


def ten_minute_checkpoint_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First row per market-day-band-10-minute slot."""

    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        slot = slot_minute(row)
        if slot is None:
            continue
        key = (
            row.get("market_id"),
            row.get("target_date"),
            row.get("band"),
            slot,
        )
        if key not in selected or timestamp_key(row) < timestamp_key(selected[key]):
            selected[key] = row

    output = []
    for key in sorted(selected, key=lambda item: (str(item[0]), str(item[1]), str(item[2]), int(item[3]))):
        row = dict(selected[key])
        row["time_slot_minute"] = int(key[3])
        row["time_slot_label"] = slot_label(int(key[3]))
        row["time_slot_regime"] = slot_regime(int(key[3]))
        output.append(row)
    return output


def group_rows(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], Any]) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[key_fn(row)].append(row)
    return grouped


def summarize_by_slot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for slot, slot_rows in sorted(group_rows(rows, lambda row: row.get("time_slot_minute")).items()):
        if slot is None:
            continue
        summary = summarize_rows(slot_rows)
        if not summary:
            continue
        slot_int = int(slot)
        summary.update(
            {
                "time_slot_minute": slot_int,
                "time_slot_label": slot_label(slot_int),
                "hour": slot_int // 60,
                "minute": slot_int % 60,
                "regime": slot_regime(slot_int),
                "regime_label": HOUR_REGIME_LABELS.get(slot_regime(slot_int), "-"),
            }
        )
        output.append(summary)
    return output


def summarize_by_regime(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    grouped = group_rows(rows, lambda row: row.get("time_slot_regime"))
    for regime, label in HOUR_REGIME_LABELS.items():
        summary = summarize_rows(grouped.get(regime, []))
        if summary:
            summary.update({"regime": regime, "regime_label": label})
            output.append(summary)
    return output


def eligible_slots(by_slot: list[dict[str, Any]], min_rows: int) -> list[dict[str, Any]]:
    return [row for row in by_slot if int(row.get("n") or 0) >= int(min_rows)]


def rank_slots(by_slot: list[dict[str, Any]], min_rows: int, top_slots: int) -> dict[str, list[dict[str, Any]]]:
    eligible = eligible_slots(by_slot, min_rows)
    worst_absolute = sorted(
        eligible,
        key=lambda row: (
            safe_float(row.get("model_brier")) or -math.inf,
            safe_float(row.get("model_logloss")) or -math.inf,
        ),
        reverse=True,
    )[:top_slots]
    worst_vs_market = sorted(
        eligible,
        key=lambda row: (
            safe_float(row.get("brier_delta")) if safe_float(row.get("brier_delta")) is not None else math.inf,
            safe_float(row.get("logloss_delta")) if safe_float(row.get("logloss_delta")) is not None else math.inf,
        ),
    )[:top_slots]
    best_absolute = sorted(
        eligible,
        key=lambda row: (
            safe_float(row.get("model_brier")) if safe_float(row.get("model_brier")) is not None else math.inf,
            safe_float(row.get("model_logloss")) if safe_float(row.get("model_logloss")) is not None else math.inf,
        ),
    )[:top_slots]
    return {
        "worst_absolute": worst_absolute,
        "worst_vs_market": worst_vs_market,
        "best_absolute": best_absolute,
    }


def percentile(values: list[float], q: float) -> float | None:
    cleaned = sorted(v for v in values if math.isfinite(v))
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    rank = (len(cleaned) - 1) * q
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return cleaned[lo]
    return cleaned[lo] + (cleaned[hi] - cleaned[lo]) * (rank - lo)


def weak_slot_set(by_slot: list[dict[str, Any]], min_rows: int) -> set[int]:
    eligible = eligible_slots(by_slot, min_rows)
    p90_brier = percentile([float(row["model_brier"]) for row in eligible if row.get("model_brier") is not None], 0.90)
    if p90_brier is None:
        return set()
    return {
        int(row["time_slot_minute"])
        for row in eligible
        if safe_float(row.get("model_brier")) is not None
        and float(row["model_brier"]) >= p90_brier
    }


def summarize_slot_subset(
    checkpoint_rows: list[dict[str, Any]],
    slots: set[int],
) -> dict[str, Any]:
    subset = [row for row in checkpoint_rows if row.get("time_slot_minute") in slots]
    summary = summarize_rows(subset) or {}
    summary["slot_count"] = len(slots)
    summary["slot_labels"] = [slot_label(slot) for slot in sorted(slots)]
    return summary


def ten_minute_performance_gate(
    weak_slots: dict[str, Any],
    corpus: dict[str, Any],
    *,
    min_weak_market_days: int = DEFAULT_MIN_WEAK_MARKET_DAYS,
    weak_brier_regression_tolerance: float = DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
    weak_logloss_regression_tolerance: float = DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    summary = (weak_slots or {}).get("summary") or {}
    blockers = []
    market_days = safe_int(summary.get("market_days")) or 0
    if not (weak_slots or {}).get("slot_minutes"):
        blockers.append({
            "gate": "weak_slots_missing",
            "detail": "no eligible 10-minute weak slots are available",
            "remediation_command": "python -m weather.reporting.hourly.ten_minute_model_performance",
        })
    elif market_days < int(min_weak_market_days):
        blockers.append({
            "gate": "weak_slot_min_market_days",
            "detail": (
                f"10-minute weak-slot evidence has {market_days} market-days; "
                f"requires at least {int(min_weak_market_days)}"
            ),
            "remediation_command": "collect more settled weak-slot market-day evidence",
        })

    brier_delta = safe_float(summary.get("brier_delta"))
    if brier_delta is not None and brier_delta < -float(weak_brier_regression_tolerance):
        blockers.append({
            "gate": "weak_slot_brier_regression",
            "detail": (
                "10-minute weak-slot model Brier trails market by "
                f"{abs(brier_delta):.4f} > {float(weak_brier_regression_tolerance):.4f}"
            ),
            "remediation_command": "keep promotion blocked; run predawn weak-slot remediation candidate",
        })
    logloss_delta = safe_float(summary.get("logloss_delta"))
    if logloss_delta is not None and logloss_delta < -float(weak_logloss_regression_tolerance):
        blockers.append({
            "gate": "weak_slot_logloss_regression",
            "detail": (
                "10-minute weak-slot model log-loss trails market by "
                f"{abs(logloss_delta):.4f} > {float(weak_logloss_regression_tolerance):.4f}"
            ),
            "remediation_command": "inspect weak-slot probability tails and winner centering",
        })

    return {
        "schema_version": TEN_MINUTE_GATE_SCHEMA_VERSION,
        "status": "BLOCK" if blockers else "PASS",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "thresholds": {
            "min_weak_market_days": int(min_weak_market_days),
            "weak_brier_regression_tolerance": float(weak_brier_regression_tolerance),
            "weak_logloss_regression_tolerance": float(weak_logloss_regression_tolerance),
        },
        "weak_slots": {
            "slot_minutes": (weak_slots or {}).get("slot_minutes") or [],
            "slot_labels": (weak_slots or {}).get("slot_labels") or [],
        },
        "weak_slot_summary": summary,
        "corpus_market_days": (corpus or {}).get("scored_market_days", 0),
    }


def ten_minute_daily_summary(rankings: dict[str, Any], gate: dict[str, Any], weak_slots: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": gate.get("status"),
        "best_slots": [row.get("time_slot_label") for row in (rankings.get("best_absolute") or [])],
        "worst_slots": [row.get("time_slot_label") for row in (rankings.get("worst_absolute") or [])],
        "worst_market_relative_slots": [
            row.get("time_slot_label") for row in (rankings.get("worst_vs_market") or [])
        ],
        "weak_slots": (weak_slots or {}).get("slot_labels") or [],
        "first_blocker": gate.get("first_blocker") or {},
    }


def score_probe_by_slot(
    rows: list[dict[str, Any]],
    transform_fn: Callable[[list[dict[str, Any]], float], list[dict[str, Any]]],
    parameter_values: tuple[float, ...],
) -> list[dict[str, Any]]:
    output = []
    for slot, slot_rows in sorted(group_rows(rows, lambda row: row.get("time_slot_minute")).items()):
        if slot is None:
            continue
        base = score_rows(slot_rows)
        if not base:
            continue
        variants = []
        for parameter in parameter_values:
            transformed = transform_fn(slot_rows, parameter)
            score = score_rows(transformed)
            if not score:
                continue
            variants.append(
                {
                    "parameter": parameter,
                    "model_brier": score["model_brier"],
                    "model_logloss": score["model_logloss"],
                    "brier_delta_vs_base": score["model_brier"] - base["model_brier"],
                    "logloss_delta_vs_base": score["model_logloss"] - base["model_logloss"],
                }
            )
        if not variants:
            continue
        best = min(variants, key=lambda row: (row["model_brier"], row["model_logloss"]))
        slot_int = int(slot)
        output.append(
            {
                "time_slot_minute": slot_int,
                "time_slot_label": slot_label(slot_int),
                "hour": slot_int // 60,
                "regime": slot_regime(slot_int),
                "base_model_brier": base["model_brier"],
                "base_model_logloss": base["model_logloss"],
                "best": best,
                "variants": variants,
            }
        )
    return output


def weighted_probe_summary(
    probe_rows: list[dict[str, Any]],
    by_slot: list[dict[str, Any]],
    slots: set[int],
) -> dict[str, Any]:
    by_slot_summary = {int(row["time_slot_minute"]): row for row in by_slot if row.get("time_slot_minute") is not None}
    probe_by_slot = {int(row["time_slot_minute"]): row for row in probe_rows if row.get("time_slot_minute") is not None}
    total_weight = 0.0
    brier_delta = 0.0
    logloss_delta = 0.0
    parameters: list[Any] = []
    rows_count = 0
    for slot in sorted(slots):
        summary = by_slot_summary.get(slot)
        probe = probe_by_slot.get(slot)
        if not summary or not probe:
            continue
        weight = float(summary.get("n") or 0)
        best = probe.get("best") or {}
        delta = safe_float(best.get("brier_delta_vs_base"))
        log_delta = safe_float(best.get("logloss_delta_vs_base"))
        if weight <= 0 or delta is None or log_delta is None:
            continue
        total_weight += weight
        brier_delta += delta * weight
        logloss_delta += log_delta * weight
        parameters.append(best.get("parameter"))
        rows_count += int(weight)
    return {
        "slot_count": len(slots),
        "scored_slot_count": len(parameters),
        "row_count": rows_count,
        "weighted_brier_delta_vs_base": brier_delta / total_weight if total_weight else None,
        "weighted_logloss_delta_vs_base": logloss_delta / total_weight if total_weight else None,
        "best_parameters": parameters,
    }


def build_replay_probes(
    checkpoint_rows: list[dict[str, Any]],
    by_slot: list[dict[str, Any]],
    weak_slots: set[int],
) -> dict[str, Any]:
    probes = {}
    for name, spec in REPLAY_PROBE_SPECS.items():
        probes[name] = {
            "uses_market_prices": spec["uses_market_prices"],
            "description": spec["description"],
            "grid": list(spec["grid"]),
            "rows": score_probe_by_slot(
                checkpoint_rows,
                spec["transform_fn"],
                spec["grid"],
            ),
        }
    for probe in probes.values():
        probe["weak_slot_summary"] = weighted_probe_summary(probe["rows"], by_slot, weak_slots)
    return probes


PARTITION_SUMMARY_FIELDS = {
    "partition_mean_band_count": "band_count",
    "partition_model_effective_bands": "model_effective_bands",
    "partition_market_effective_bands": "market_effective_bands",
    "partition_effective_band_gap": "effective_band_gap",
    "partition_model_norm_entropy": "model_norm_entropy",
    "partition_market_norm_entropy": "market_norm_entropy",
    "partition_norm_entropy_gap": "norm_entropy_gap",
    "partition_model_top_probability": "model_top_probability",
    "partition_market_top_probability": "market_top_probability",
    "partition_top_probability_gap": "top_probability_gap",
    "partition_model_winner_probability": "model_winner_probability",
    "partition_market_winner_probability": "market_winner_probability",
    "partition_winner_probability_gap": "winner_probability_gap",
    "partition_model_winner_rank": "model_winner_rank",
    "partition_market_winner_rank": "market_winner_rank",
    "partition_winner_rank_gap": "winner_rank_gap",
    "partition_model_top_is_winner_rate": "model_top_is_winner",
    "partition_market_top_is_winner_rate": "market_top_is_winner",
    "partition_model_adjacent_winner_mass": "model_adjacent_winner_mass",
    "partition_market_adjacent_winner_mass": "market_adjacent_winner_mass",
    "partition_adjacent_winner_mass_gap": "adjacent_winner_mass_gap",
}


class _WindowedSummary:
    """Mergeable sufficient statistics for ``summarize_rows``.

    The accumulator intentionally owns no source rows.  Callers update it with
    one complete market-day/slot window so snapshot-partition metrics remain
    equivalent to the list-based implementation.
    """

    def __init__(self) -> None:
        self.n = 0
        self.score_sums = {
            "model_brier": 0.0,
            "market_brier": 0.0,
            "model_logloss": 0.0,
            "market_logloss": 0.0,
            "outcome": 0.0,
        }
        self.numeric_sums: dict[str, float] = defaultdict(float)
        self.numeric_counts: dict[str, int] = defaultdict(int)
        self.ece_bins = {
            "model_probability": [[0, 0.0, 0.0] for _ in range(5)],
            "market_yes": [[0, 0.0, 0.0] for _ in range(5)],
        }
        self.winner_count = 0
        self.winner_model_sum = 0.0
        self.winner_market_sum = 0.0
        self.winner_caught_up = 0
        self.winner_model_over_50 = 0
        self.winner_market_over_50 = 0
        self.loser_count = 0
        self.loser_model_sum = 0.0
        self.loser_market_sum = 0.0
        self.partition_snapshots = 0
        self.partition_sums: dict[str, float] = defaultdict(float)
        self.partition_counts: dict[str, int] = defaultdict(int)

    @staticmethod
    def _mean_number(value: Any) -> float | None:
        number = safe_float(value)
        if number is None or math.isnan(number):
            return None
        return float(number)

    def _add_numeric(self, key: str, value: Any) -> None:
        number = self._mean_number(value)
        if number is None:
            return
        self.numeric_sums[key] += number
        self.numeric_counts[key] += 1

    def _numeric_mean(self, key: str) -> float | None:
        count = self.numeric_counts.get(key, 0)
        return self.numeric_sums.get(key, 0.0) / count if count else None

    def _add_ece(self, key: str, probability: float, outcome: float) -> None:
        index = min(4, int(max(0.0, min(0.999999, probability)) * 5))
        bucket = self.ece_bins[key][index]
        bucket[0] += 1
        bucket[1] += probability
        bucket[2] += outcome

    def _ece(self, key: str) -> float | None:
        bins = self.ece_bins[key]
        total = sum(int(bucket[0]) for bucket in bins)
        if total <= 0:
            return None
        return sum(
            (int(bucket[0]) / total)
            * abs(float(bucket[1]) / int(bucket[0]) - float(bucket[2]) / int(bucket[0]))
            for bucket in bins
            if int(bucket[0]) > 0
        )

    def update(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        for row in rows:
            model_probability = float(row["model_probability"])
            market_probability = float(row["market_yes"])
            outcome = float(row["outcome"])
            self.n += 1
            self.score_sums["model_brier"] += (model_probability - outcome) ** 2
            self.score_sums["market_brier"] += (market_probability - outcome) ** 2
            self.score_sums["model_logloss"] += binary_log_loss(model_probability, outcome)
            self.score_sums["market_logloss"] += binary_log_loss(market_probability, outcome)
            self.score_sums["outcome"] += outcome
            self._add_numeric("model_probability", row.get("model_probability"))
            self._add_numeric("market_yes", row.get("market_yes"))
            edge = self._mean_number(row.get("model_edge"))
            if edge is not None:
                self._add_numeric("model_edge", edge)
                self._add_numeric("abs_model_edge", abs(edge))
            self._add_ece("model_probability", model_probability, outcome)
            self._add_ece("market_yes", market_probability, outcome)
            if row.get("outcome") == 1:
                self.winner_count += 1
                self.winner_model_sum += model_probability
                self.winner_market_sum += market_probability
                self.winner_caught_up += int(model_probability >= market_probability)
                self.winner_model_over_50 += int(model_probability > 0.5)
                self.winner_market_over_50 += int(market_probability > 0.5)
            elif row.get("outcome") == 0:
                self.loser_count += 1
                self.loser_model_sum += model_probability
                self.loser_market_sum += market_probability
            for field in DRIVER_NUMERIC_FIELDS:
                self._add_numeric(f"driver:{field}", row.get(field))

        for partition in snapshot_partition_stats(rows):
            self.partition_snapshots += 1
            for source_field in PARTITION_SUMMARY_FIELDS.values():
                number = self._mean_number(partition.get(source_field))
                if number is None:
                    continue
                self.partition_sums[source_field] += number
                self.partition_counts[source_field] += 1

    def merge(self, other: "_WindowedSummary") -> None:
        self.n += other.n
        for key, value in other.score_sums.items():
            self.score_sums[key] += value
        for key, value in other.numeric_sums.items():
            self.numeric_sums[key] += value
        for key, value in other.numeric_counts.items():
            self.numeric_counts[key] += value
        for key, bins in other.ece_bins.items():
            for index, source in enumerate(bins):
                target = self.ece_bins[key][index]
                target[0] += source[0]
                target[1] += source[1]
                target[2] += source[2]
        self.winner_count += other.winner_count
        self.winner_model_sum += other.winner_model_sum
        self.winner_market_sum += other.winner_market_sum
        self.winner_caught_up += other.winner_caught_up
        self.winner_model_over_50 += other.winner_model_over_50
        self.winner_market_over_50 += other.winner_market_over_50
        self.loser_count += other.loser_count
        self.loser_model_sum += other.loser_model_sum
        self.loser_market_sum += other.loser_market_sum
        self.partition_snapshots += other.partition_snapshots
        for key, value in other.partition_sums.items():
            self.partition_sums[key] += value
        for key, value in other.partition_counts.items():
            self.partition_counts[key] += value

    def finalize(self, distinct_counts: dict[str, int]) -> dict[str, Any] | None:
        if self.n <= 0:
            return None
        model_brier = self.score_sums["model_brier"] / self.n
        market_brier = self.score_sums["market_brier"] / self.n
        model_logloss = self.score_sums["model_logloss"] / self.n
        market_logloss = self.score_sums["market_logloss"] / self.n
        winner_model_probability = (
            self.winner_model_sum / self.winner_count if self.winner_count else None
        )
        winner_market_probability = (
            self.winner_market_sum / self.winner_count if self.winner_count else None
        )
        summary: dict[str, Any] = {
            "n": self.n,
            "model_brier": model_brier,
            "market_brier": market_brier,
            "model_logloss": model_logloss,
            "market_logloss": market_logloss,
            "base_rate": self.score_sums["outcome"] / self.n,
            "brier_delta": market_brier - model_brier,
            "logloss_delta": market_logloss - model_logloss,
            "brier_skill_score": 1.0 - model_brier / market_brier if market_brier > 0 else 0.0,
            "market_days": int(distinct_counts.get("market_days") or 0),
            "markets": int(distinct_counts.get("markets") or 0),
            "snapshots": int(distinct_counts.get("snapshots") or 0),
            "model_ece": self._ece("model_probability"),
            "market_ece": self._ece("market_yes"),
            "mean_model_probability": self._numeric_mean("model_probability"),
            "mean_market_probability": self._numeric_mean("market_yes"),
            "mean_edge": self._numeric_mean("model_edge"),
            "mean_abs_edge": self._numeric_mean("abs_model_edge"),
            "winner_model_probability": winner_model_probability,
            "winner_market_probability": winner_market_probability,
            "loser_model_probability": (
                self.loser_model_sum / self.loser_count if self.loser_count else None
            ),
            "loser_market_probability": (
                self.loser_market_sum / self.loser_count if self.loser_count else None
            ),
        }
        if self.partition_snapshots:
            summary["partition_snapshots"] = self.partition_snapshots
            for summary_field, source_field in PARTITION_SUMMARY_FIELDS.items():
                count = self.partition_counts.get(source_field, 0)
                summary[summary_field] = (
                    self.partition_sums.get(source_field, 0.0) / count if count else None
                )
        summary.update(
            {
                "winner_rows": self.winner_count,
                "winner_model_probability": winner_model_probability,
                "winner_market_probability": winner_market_probability,
                "winner_catchup_gap": (
                    winner_model_probability - winner_market_probability
                    if winner_model_probability is not None and winner_market_probability is not None
                    else None
                ),
                "winner_catchup_rate": (
                    self.winner_caught_up / self.winner_count if self.winner_count else None
                ),
                "winner_model_over_50_rate": (
                    self.winner_model_over_50 / self.winner_count if self.winner_count else None
                ),
                "winner_market_over_50_rate": (
                    self.winner_market_over_50 / self.winner_count if self.winner_count else None
                ),
            }
        )
        for field in DRIVER_NUMERIC_FIELDS:
            value = self._numeric_mean(f"driver:{field}")
            if value is not None:
                summary[f"mean_{field}"] = value
        return summary


class _WindowedModelScore:
    def __init__(self) -> None:
        self.n = 0
        self.brier_sum = 0.0
        self.logloss_sum = 0.0

    def update(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            probability = float(row["model_probability"])
            outcome = float(row["outcome"])
            self.n += 1
            self.brier_sum += (probability - outcome) ** 2
            self.logloss_sum += binary_log_loss(probability, outcome)

    def finalize(self) -> dict[str, float] | None:
        if self.n <= 0:
            return None
        return {
            "model_brier": self.brier_sum / self.n,
            "model_logloss": self.logloss_sum / self.n,
        }


class _DiskDistinctIndex:
    """Exact distinct counts without retaining checkpoint identities in RAM."""

    TABLES = ("market_days", "markets", "snapshots")

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("PRAGMA cache_size=-1024")
        for table in self.TABLES:
            self.connection.execute(
                f"CREATE TABLE {table} ("
                "slot INTEGER NOT NULL, value TEXT NOT NULL, "
                "PRIMARY KEY (slot, value)) WITHOUT ROWID"
            )

    @staticmethod
    def _identity(value: Any) -> str:
        return json.dumps(value, default=str, separators=(",", ":"))

    def add_market_day(self, grouped_rows: dict[int, list[dict[str, Any]]]) -> None:
        market_days = []
        markets = []
        snapshots = []
        for slot, rows in grouped_rows.items():
            market_days.extend(
                (slot, self._identity([row.get("market_id"), row.get("target_date")]))
                for row in rows
            )
            markets.extend(
                (slot, self._identity(row.get("market_id")))
                for row in rows
                if row.get("market_id") not in (None, "")
            )
            snapshots.extend(
                (slot, self._identity(row.get("snapshot_id")))
                for row in rows
                if row.get("snapshot_id") not in (None, "")
            )
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO market_days (slot, value) VALUES (?, ?)",
                market_days,
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO markets (slot, value) VALUES (?, ?)",
                markets,
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO snapshots (slot, value) VALUES (?, ?)",
                snapshots,
            )

    def counts(self, slots: set[int]) -> dict[str, int]:
        selected = tuple(sorted(int(slot) for slot in slots))
        if not selected:
            return {table: 0 for table in self.TABLES}
        placeholders = ",".join("?" for _ in selected)
        return {
            table: int(
                self.connection.execute(
                    f"SELECT COUNT(DISTINCT value) FROM {table} "
                    f"WHERE slot IN ({placeholders})",
                    selected,
                ).fetchone()[0]
            )
            for table in self.TABLES
        }

    def close(self) -> None:
        self.connection.close()


class TenMinuteMarketDayAggregation:
    """Bounded ten-minute aggregation over one scored market-day at a time."""

    def __init__(self, scratch_root: str | Path, *, include_replay_probes: bool = True) -> None:
        scratch_root = Path(scratch_root)
        scratch_root.mkdir(parents=True, exist_ok=True)
        self._distinct = _DiskDistinctIndex(scratch_root / "checkpoint_distincts.sqlite3")
        self._summaries: dict[int, _WindowedSummary] = {}
        self._probe_scores: dict[str, dict[int, dict[float, _WindowedModelScore]]] = {
            name: {} for name in REPLAY_PROBE_SPECS
        }
        self.include_replay_probes = bool(include_replay_probes)
        self.checkpoint_row_count = 0
        self._closed = False

    def __enter__(self) -> "TenMinuteMarketDayAggregation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._distinct.close()
            self._closed = True

    def add_market_day_rows(self, rows: list[dict[str, Any]]) -> int:
        """Select and aggregate checkpoints, retaining no row from this call."""

        checkpoints = ten_minute_checkpoint_rows(rows)
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in checkpoints:
            slot = row.get("time_slot_minute")
            if slot is not None:
                grouped[int(slot)].append(row)
        self._distinct.add_market_day(grouped)
        for slot, slot_rows in grouped.items():
            self._summaries.setdefault(slot, _WindowedSummary()).update(slot_rows)
            if not self.include_replay_probes:
                continue
            for name, spec in REPLAY_PROBE_SPECS.items():
                parameter_scores = self._probe_scores[name].setdefault(
                    slot,
                    {float(value): _WindowedModelScore() for value in spec["grid"]},
                )
                for parameter in spec["grid"]:
                    transformed = spec["transform_fn"](slot_rows, parameter)
                    parameter_scores[float(parameter)].update(transformed)
        self.checkpoint_row_count += len(checkpoints)
        return len(checkpoints)

    def summary_for_slots(self, slots: set[int]) -> dict[str, Any] | None:
        selected = {int(slot) for slot in slots if int(slot) in self._summaries}
        combined = _WindowedSummary()
        for slot in sorted(selected):
            combined.merge(self._summaries[slot])
        return combined.finalize(self._distinct.counts(selected))

    def by_slot(self) -> list[dict[str, Any]]:
        output = []
        for slot in sorted(self._summaries):
            summary = self.summary_for_slots({slot})
            if not summary:
                continue
            summary.update(
                {
                    "time_slot_minute": slot,
                    "time_slot_label": slot_label(slot),
                    "hour": slot // 60,
                    "minute": slot % 60,
                    "regime": slot_regime(slot),
                    "regime_label": HOUR_REGIME_LABELS.get(slot_regime(slot), "-"),
                }
            )
            output.append(summary)
        return output

    def by_regime(self) -> list[dict[str, Any]]:
        output = []
        for regime, label in HOUR_REGIME_LABELS.items():
            slots = {slot for slot in self._summaries if slot_regime(slot) == regime}
            summary = self.summary_for_slots(slots)
            if summary:
                summary.update({"regime": regime, "regime_label": label})
                output.append(summary)
        return output

    def replay_probes(
        self,
        by_slot: list[dict[str, Any]],
        weak_slots: set[int],
    ) -> dict[str, Any]:
        by_slot_summary = {
            int(row["time_slot_minute"]): row
            for row in by_slot
            if row.get("time_slot_minute") is not None
        }
        probes = {}
        for name, spec in REPLAY_PROBE_SPECS.items():
            probe_rows = []
            for slot, parameter_scores in sorted(self._probe_scores[name].items()):
                base = by_slot_summary.get(slot)
                if not base:
                    continue
                variants = []
                for parameter in spec["grid"]:
                    score = parameter_scores[float(parameter)].finalize()
                    if not score:
                        continue
                    variants.append(
                        {
                            "parameter": parameter,
                            "model_brier": score["model_brier"],
                            "model_logloss": score["model_logloss"],
                            "brier_delta_vs_base": score["model_brier"] - base["model_brier"],
                            "logloss_delta_vs_base": score["model_logloss"] - base["model_logloss"],
                        }
                    )
                if not variants:
                    continue
                best = min(
                    variants,
                    key=lambda row: (row["model_brier"], row["model_logloss"]),
                )
                probe_rows.append(
                    {
                        "time_slot_minute": slot,
                        "time_slot_label": slot_label(slot),
                        "hour": slot // 60,
                        "regime": slot_regime(slot),
                        "base_model_brier": base["model_brier"],
                        "base_model_logloss": base["model_logloss"],
                        "best": best,
                        "variants": variants,
                    }
                )
            probes[name] = {
                "uses_market_prices": spec["uses_market_prices"],
                "description": spec["description"],
                "grid": list(spec["grid"]),
                "rows": probe_rows,
                "weak_slot_summary": weighted_probe_summary(
                    probe_rows,
                    by_slot,
                    weak_slots,
                ),
            }
        return probes


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def candidate_capture_minute(row: dict[str, Any]) -> int | None:
    parsed = parse_time(row.get("captured_at_local"))
    if not parsed:
        return None
    return parsed.hour * 60 + parsed.minute


def read_candidate_checkpoint_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for source in reader:
            captured = parse_time(source.get("captured_at_local"))
            minute = candidate_capture_minute(source)
            if captured is None or minute is None:
                continue
            slot = (minute // 10) * 10
            outcome = safe_int(source.get("outcome"))
            variant_probability = safe_float(source.get("probability"))
            current_probability = safe_float(source.get("current_probability"))
            market_yes = safe_float(source.get("market_yes"))
            if (
                outcome is None
                or variant_probability is None
                or current_probability is None
                or market_yes is None
                or not source.get("market_id")
                or not source.get("target_date")
                or not source.get("snapshot_id")
                or not source.get("band_key")
            ):
                continue
            row = {
                "variant_id": source.get("variant_id"),
                "market_id": source.get("market_id"),
                "target_date": source.get("target_date"),
                "snapshot_id": source.get("snapshot_id"),
                "band_key": source.get("band_key"),
                "captured_at_local": source.get("captured_at_local"),
                "_timestamp": captured.timestamp(),
                "time_slot_minute": slot,
                "time_slot_label": slot_label(slot),
                "time_slot_regime": slot_regime(slot),
                "variant_probability": variant_probability,
                "current_probability": current_probability,
                "market_yes": market_yes,
                "outcome": outcome,
                "bin_type": source.get("bin_type"),
                "bin_value": source.get("bin_value"),
                "settlement_distance_bucket": source.get("settlement_distance_bucket"),
                "forecast_bucket_pressure": source.get("forecast_bucket_pressure"),
                "forecast_disagreement_bucket": source.get("forecast_disagreement_bucket"),
                "forecast_source_count_bucket": source.get("forecast_source_count_bucket"),
                "source_freshness_state": source.get("source_freshness_state"),
            }
            key = (row["market_id"], row["target_date"], row["band_key"], slot)
            if key not in selected or row["_timestamp"] < selected[key]["_timestamp"]:
                selected[key] = row
    return [selected[key] for key in sorted(selected, key=lambda item: (str(item[0]), str(item[1]), str(item[2]), int(item[3])))]


def score_candidate_probability(rows: list[dict[str, Any]], probability_key: str) -> dict[str, Any]:
    pairs = [
        (safe_float(row.get(probability_key)), safe_int(row.get("outcome")))
        for row in rows
    ]
    pairs = [(p, y) for p, y in pairs if p is not None and y is not None]
    if not pairs:
        return {"brier": None, "logloss": None, "ece": None}
    return {
        "brier": sum((p - y) ** 2 for p, y in pairs) / len(pairs),
        "logloss": sum(binary_log_loss(p, y) for p, y in pairs) / len(pairs),
        "ece": expected_calibration_error(rows, probability_key),
    }


def summarize_candidate_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    variant = score_candidate_probability(rows, "variant_probability")
    current = score_candidate_probability(rows, "current_probability")
    market = score_candidate_probability(rows, "market_yes")
    winners = [row for row in rows if row.get("outcome") == 1]
    losers = [row for row in rows if row.get("outcome") == 0]
    variant_brier = variant["brier"]
    current_brier = current["brier"]
    market_brier = market["brier"]
    variant_logloss = variant["logloss"]
    current_logloss = current["logloss"]
    market_logloss = market["logloss"]
    return {
        "n": len(rows),
        "markets": len({row.get("market_id") for row in rows if row.get("market_id")}),
        "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
        "snapshots": len({row.get("snapshot_id") for row in rows if row.get("snapshot_id")}),
        "variant_brier": variant_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": variant_brier - current_brier if variant_brier is not None and current_brier is not None else None,
        "delta_vs_market": variant_brier - market_brier if variant_brier is not None and market_brier is not None else None,
        "variant_logloss": variant_logloss,
        "current_logloss": current_logloss,
        "market_logloss": market_logloss,
        "logloss_delta_vs_current": (
            variant_logloss - current_logloss
            if variant_logloss is not None and current_logloss is not None
            else None
        ),
        "logloss_delta_vs_market": (
            variant_logloss - market_logloss
            if variant_logloss is not None and market_logloss is not None
            else None
        ),
        "variant_ece": variant["ece"],
        "current_ece": current["ece"],
        "market_ece": market["ece"],
        "winner_variant_probability": mean(row["variant_probability"] for row in winners),
        "winner_current_probability": mean(row["current_probability"] for row in winners),
        "winner_market_probability": mean(row["market_yes"] for row in winners),
        "loser_variant_probability": mean(row["variant_probability"] for row in losers),
        "loser_current_probability": mean(row["current_probability"] for row in losers),
        "loser_market_probability": mean(row["market_yes"] for row in losers),
    }


def summarize_candidate_by_slot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    grouped = group_rows(rows, lambda row: row.get("time_slot_minute"))
    for slot, slot_rows in sorted(grouped.items()):
        summary = summarize_candidate_rows(slot_rows)
        if not summary:
            continue
        slot_int = int(slot)
        summary.update(
            {
                "time_slot_minute": slot_int,
                "time_slot_label": slot_label(slot_int),
                "hour": slot_int // 60,
                "minute": slot_int % 60,
                "regime": slot_regime(slot_int),
                "regime_label": HOUR_REGIME_LABELS.get(slot_regime(slot_int), "-"),
            }
        )
        output.append(summary)
    return output


def summarize_candidate_by_regime(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    grouped = group_rows(rows, lambda row: row.get("time_slot_regime"))
    for regime, label in HOUR_REGIME_LABELS.items():
        summary = summarize_candidate_rows(grouped.get(regime, []))
        if summary:
            summary.update({"regime": regime, "regime_label": label})
            output.append(summary)
    return output


def summarize_candidate_slot_subset(rows: list[dict[str, Any]], slots: set[int]) -> dict[str, Any]:
    subset = [row for row in rows if row.get("time_slot_minute") in slots]
    summary = summarize_candidate_rows(subset) or {}
    overlap_slots = sorted({int(row["time_slot_minute"]) for row in subset if row.get("time_slot_minute") is not None})
    summary["weak_slot_count"] = len(slots)
    summary["candidate_slot_overlap"] = len(overlap_slots)
    summary["slot_minutes"] = overlap_slots
    summary["slot_labels"] = [slot_label(slot) for slot in overlap_slots]
    summary["row_count"] = summary.get("n", 0)
    return summary


def candidate_ten_minute_gate(
    candidate: dict[str, Any],
    *,
    min_weak_market_days: int = DEFAULT_MIN_WEAK_MARKET_DAYS,
    weak_brier_improvement_min: float = DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
    weak_market_regression_tolerance: float = DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
    weak_logloss_regression_tolerance: float = DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    blockers = []
    overlap = (candidate or {}).get("weak_slot_overlap") or {}
    if not candidate or not candidate.get("available"):
        blockers.append({
            "gate": "candidate_ten_minute_performance_missing",
            "detail": "candidate 10-minute performance artifact is missing or empty",
            "remediation_command": "python -m weather.reporting.hourly.ten_minute_model_performance --item147-rows <candidate_rows.csv>",
        })
        status = "MISSING"
    else:
        status = "BLOCK"
        market_days = safe_int(overlap.get("market_days")) or 0
        if not overlap.get("candidate_slot_overlap"):
            blockers.append({
                "gate": "candidate_weak_slot_overlap_missing",
                "detail": "candidate rows do not overlap the current 10-minute weak-slot watchlist",
                "remediation_command": "rerun the candidate export across the current weak-slot watchlist",
            })
        elif market_days < int(min_weak_market_days):
            blockers.append({
                "gate": "candidate_weak_slot_min_market_days",
                "detail": (
                    f"candidate weak-slot evidence has {market_days} market-days; "
                    f"requires at least {int(min_weak_market_days)}"
                ),
                "remediation_command": "collect more settled candidate weak-slot market-day evidence",
            })

        delta_current = safe_float(overlap.get("delta_vs_current"))
        if delta_current is not None and delta_current > -float(weak_brier_improvement_min):
            blockers.append({
                "gate": "candidate_weak_slot_brier_not_improved",
                "detail": (
                    "candidate weak-slot Brier delta versus current is "
                    f"{delta_current:+.4f}; requires <= {-float(weak_brier_improvement_min):+.4f}"
                ),
                "remediation_command": "keep candidate shadowed; improve 10-minute weak-slot Brier versus current",
            })
        delta_market = safe_float(overlap.get("delta_vs_market"))
        if delta_market is not None and delta_market > float(weak_market_regression_tolerance):
            blockers.append({
                "gate": "candidate_weak_slot_market_brier_regression",
                "detail": (
                    "candidate weak-slot Brier trails market by "
                    f"{delta_market:.4f} > {float(weak_market_regression_tolerance):.4f}"
                ),
                "remediation_command": "keep candidate shadowed; repair market-relative weak-slot Brier",
            })
        logloss_market = safe_float(overlap.get("logloss_delta_vs_market"))
        if logloss_market is not None and logloss_market > float(weak_logloss_regression_tolerance):
            blockers.append({
                "gate": "candidate_weak_slot_market_logloss_regression",
                "detail": (
                    "candidate weak-slot log-loss trails market by "
                    f"{logloss_market:.4f} > {float(weak_logloss_regression_tolerance):.4f}"
                ),
                "remediation_command": "inspect candidate weak-slot probability tails before promotion",
            })
        if not blockers:
            status = "PASS"

    return {
        "schema_version": CANDIDATE_TEN_MINUTE_GATE_SCHEMA_VERSION,
        "status": status,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "thresholds": {
            "min_weak_market_days": int(min_weak_market_days),
            "weak_brier_improvement_min": float(weak_brier_improvement_min),
            "weak_market_regression_tolerance": float(weak_market_regression_tolerance),
            "weak_logloss_regression_tolerance": float(weak_logloss_regression_tolerance),
        },
        "variant_ids": (candidate or {}).get("variant_ids") or [],
        "weak_slot_overlap": overlap,
    }


def build_candidate_item147(path: Path, weak_slots: set[int] | None = None) -> dict[str, Any]:
    source_rows = read_variant_rows(path) if path.exists() else []
    rows = read_candidate_checkpoint_rows(path)
    by_slot = summarize_candidate_by_slot(rows)
    by_regime = summarize_candidate_by_regime(rows)
    row_export_corpus_hash = candidate_rows_corpus_hash(source_rows)
    checkpoint_corpus_hash = candidate_rows_corpus_hash(rows)
    payload = {
        "path": str(path),
        "available": bool(rows),
        "source_rows": len(source_rows),
        "checkpoint_rows": len(rows),
        "variant_ids": sorted({str(row.get("variant_id")) for row in rows if row.get("variant_id")}),
        "corpus": {
            "markets": len({row.get("market_id") for row in rows if row.get("market_id")}),
            "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
            "snapshots": len({row.get("snapshot_id") for row in rows if row.get("snapshot_id")}),
            "corpus_hash": row_export_corpus_hash or checkpoint_corpus_hash,
            "row_export_corpus_hash": row_export_corpus_hash,
            "checkpoint_corpus_hash": checkpoint_corpus_hash,
        },
        "overall": summarize_candidate_rows(rows) or {},
        "by_slot": by_slot,
        "by_regime": by_regime,
    }
    if weak_slots is not None:
        payload["weak_slot_overlap"] = summarize_candidate_slot_subset(rows, weak_slots)
    return payload


def candidate_weak_slot_overlap(candidate: dict[str, Any], weak_slots: set[int]) -> dict[str, Any]:
    by_slot = {int(row["time_slot_minute"]): row for row in candidate.get("by_slot") or []}
    rows = [by_slot[slot] for slot in sorted(weak_slots) if slot in by_slot]
    total_weight = 0.0
    weighted_delta_current = 0.0
    weighted_delta_market = 0.0
    for row in rows:
        weight = float(row.get("n") or 0)
        delta_current = safe_float(row.get("delta_vs_current"))
        delta_market = safe_float(row.get("delta_vs_market"))
        if weight <= 0 or delta_current is None or delta_market is None:
            continue
        total_weight += weight
        weighted_delta_current += delta_current * weight
        weighted_delta_market += delta_market * weight
    return {
        "weak_slot_count": len(weak_slots),
        "candidate_slot_overlap": len(rows),
        "row_count": int(total_weight),
        "weighted_delta_vs_current": weighted_delta_current / total_weight if total_weight else None,
        "weighted_delta_vs_market": weighted_delta_market / total_weight if total_weight else None,
    }


def build_ten_minute_performance(
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
    include_promotion_countable_labels=True,
    markets="",
    start_date=None,
    end_date=None,
    min_rows=DEFAULT_MIN_ROWS,
    top_slots=DEFAULT_TOP_SLOTS,
    item147_rows=DEFAULT_ITEM147_ROWS,
    min_weak_market_days=DEFAULT_MIN_WEAK_MARKET_DAYS,
    weak_brier_regression_tolerance=DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
    weak_logloss_regression_tolerance=DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
    candidate_min_weak_market_days=DEFAULT_MIN_WEAK_MARKET_DAYS,
    candidate_weak_brier_improvement_min=DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
    candidate_weak_market_regression_tolerance=DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
    candidate_weak_logloss_regression_tolerance=DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    return build_payload(argparse.Namespace(
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        markets=markets,
        start_date=start_date,
        end_date=end_date,
        min_rows=min_rows,
        top_slots=top_slots,
        item147_rows=item147_rows,
        min_weak_market_days=min_weak_market_days,
        weak_brier_regression_tolerance=weak_brier_regression_tolerance,
        weak_logloss_regression_tolerance=weak_logloss_regression_tolerance,
        candidate_min_weak_market_days=candidate_min_weak_market_days,
        candidate_weak_brier_improvement_min=candidate_weak_brier_improvement_min,
        candidate_weak_market_regression_tolerance=candidate_weak_market_regression_tolerance,
        candidate_weak_logloss_regression_tolerance=candidate_weak_logloss_regression_tolerance,
    ))


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    quality_grades = args.quality_grades
    if isinstance(quality_grades, str):
        quality_grades = tuple(item.strip() for item in quality_grades.split(",") if item.strip())
    else:
        quality_grades = tuple(quality_grades or DEFAULT_QUALITY_GRADES)
    include_promotion_countable_labels = bool(
        getattr(
            args,
            "include_promotion_countable_labels",
            not getattr(args, "strict_quality_grades_only", False),
        )
    )
    markets = args.markets
    if isinstance(markets, str):
        markets = [item.strip() for item in markets.split(",") if item.strip()]
    labels, skipped = discover_labeled_folders(
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        markets=markets,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    all_snapshot_rows = 0
    scored_market_days = 0
    scored_markets: set[str] = set()
    scored_date_min = None
    scored_date_max = None
    score_errors = []
    with tempfile.TemporaryDirectory(prefix="weather-ten-minute-score-") as scratch_root:
        with TenMinuteMarketDayAggregation(scratch_root) as aggregation:
            for item in labels:
                try:
                    rows, day = score_folder(item["folder"], item["label"])
                except Exception as exc:  # noqa: BLE001 - report should include bad folder context
                    score_errors.append({"folder": str(item["folder"]), "error": str(exc)})
                    continue
                all_snapshot_rows += len(rows)
                aggregation.add_market_day_rows(rows)
                scored_market_days += 1
                market_id = day.get("market_id")
                if market_id:
                    scored_markets.add(str(market_id))
                target_date = day.get("target_date")
                if target_date:
                    target_date = str(target_date)
                    scored_date_min = (
                        target_date
                        if scored_date_min is None or target_date < scored_date_min
                        else scored_date_min
                    )
                    scored_date_max = (
                        target_date
                        if scored_date_max is None or target_date > scored_date_max
                        else scored_date_max
                    )
                del rows

            by_slot = aggregation.by_slot()
            by_regime = aggregation.by_regime()
            all_slots = {
                int(row["time_slot_minute"])
                for row in by_slot
                if row.get("time_slot_minute") is not None
            }
            overall = aggregation.summary_for_slots(all_slots) or {}
            rankings = rank_slots(by_slot, args.min_rows, args.top_slots)
            weak_slots = weak_slot_set(by_slot, args.min_rows)
            weak_summary = aggregation.summary_for_slots(weak_slots) or {}
            weak_summary["slot_count"] = len(weak_slots)
            weak_summary["slot_labels"] = [slot_label(slot) for slot in sorted(weak_slots)]
            probes = aggregation.replay_probes(by_slot, weak_slots)
            checkpoint_row_count = aggregation.checkpoint_row_count
    weak_slot_payload = {
        "definition": "Eligible slots in the top decile of model Brier, using first checkpoint per market-day-band-10-minute slot.",
        "slot_minutes": sorted(weak_slots),
        "slot_labels": [slot_label(slot) for slot in sorted(weak_slots)],
        "summary": weak_summary,
    }
    gate = ten_minute_performance_gate(
        weak_slot_payload,
        {
            "scored_market_days": scored_market_days,
        },
        min_weak_market_days=getattr(args, "min_weak_market_days", DEFAULT_MIN_WEAK_MARKET_DAYS),
        weak_brier_regression_tolerance=getattr(
            args,
            "weak_brier_regression_tolerance",
            DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
        ),
        weak_logloss_regression_tolerance=getattr(
            args,
            "weak_logloss_regression_tolerance",
            DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
        ),
    )
    candidate = build_candidate_item147(Path(args.item147_rows), weak_slots=weak_slots) if args.item147_rows else {}
    candidate_gate = candidate_ten_minute_gate(
        candidate,
        min_weak_market_days=getattr(args, "candidate_min_weak_market_days", DEFAULT_MIN_WEAK_MARKET_DAYS),
        weak_brier_improvement_min=getattr(
            args,
            "candidate_weak_brier_improvement_min",
            DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
        ),
        weak_market_regression_tolerance=getattr(
            args,
            "candidate_weak_market_regression_tolerance",
            DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
        ),
        weak_logloss_regression_tolerance=getattr(
            args,
            "candidate_weak_logloss_regression_tolerance",
            DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
        ),
    )
    daily_summary = ten_minute_daily_summary(rankings, gate, weak_slot_payload)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "inputs": {
            "labels_csv": str(args.labels_csv),
            "snapshots_root": str(args.snapshots_root),
            "quality_grades": args.quality_grades,
            "include_promotion_countable_labels": include_promotion_countable_labels,
            "markets": args.markets,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "min_rows": args.min_rows,
            "top_slots": args.top_slots,
            "min_weak_market_days": getattr(args, "min_weak_market_days", DEFAULT_MIN_WEAK_MARKET_DAYS),
            "weak_brier_regression_tolerance": getattr(
                args,
                "weak_brier_regression_tolerance",
                DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
            ),
            "weak_logloss_regression_tolerance": getattr(
                args,
                "weak_logloss_regression_tolerance",
                DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
            ),
            "item147_rows": str(args.item147_rows),
        },
        "corpus": {
            "selected_label_count": len(labels),
            "scored_market_days": scored_market_days,
            "markets": sorted(scored_markets),
            "date_min": scored_date_min,
            "date_max": scored_date_max,
            "all_snapshot_rows": all_snapshot_rows,
            "ten_minute_checkpoint_rows": checkpoint_row_count,
            "skipped_labels": skipped,
            "score_errors": score_errors,
        },
        "overall": overall,
        "by_slot": by_slot,
        "by_regime": by_regime,
        "rankings": rankings,
        "weak_slots": weak_slot_payload,
        "daily_summary": daily_summary,
        "ten_minute_performance_gate": gate,
        "candidate_ten_minute_gate": candidate_gate,
        "variant_ids": candidate.get("variant_ids") or [],
        "candidate_ten_minute_performance": candidate,
        "replay_probes": probes,
        "candidate_item147": candidate,
    }
    rerun_command = build_rerun_command(
        "weather.reporting.hourly.ten_minute_model_performance",
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        markets=markets,
        start_date=args.start_date,
        end_date=args.end_date,
        extra_args=[
            "--min-rows",
            args.min_rows,
            "--top-slots",
            args.top_slots,
            "--min-weak-market-days",
            getattr(args, "min_weak_market_days", DEFAULT_MIN_WEAK_MARKET_DAYS),
            "--weak-brier-regression-tolerance",
            getattr(args, "weak_brier_regression_tolerance", DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE),
            "--weak-logloss-regression-tolerance",
            getattr(args, "weak_logloss_regression_tolerance", DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE),
            "--item147-rows",
            args.item147_rows,
        ],
    )
    return attach_scoring_liveness(
        payload,
        artifact_name="ten_minute_model_performance",
        labels_csv=args.labels_csv,
        quality_grades=quality_grades,
        include_promotion_countable_labels=include_promotion_countable_labels,
        last_scored_target_date=(payload.get("corpus") or {}).get("date_max"),
        rerun_command=rerun_command,
        gate_keys=("ten_minute_performance_gate", "candidate_ten_minute_gate"),
    )


def slot_table(rows: list[dict[str, Any]], limit: int | None = None) -> list[list[Any]]:
    selected = rows[:limit] if limit else rows
    return [
        [
            row.get("time_slot_label"),
            row.get("n"),
            row.get("market_days"),
            row.get("markets"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_num(row.get("model_logloss")),
            fmt_signed(row.get("logloss_delta")),
            fmt_pct(row.get("winner_model_probability")),
            fmt_pct(row.get("winner_market_probability")),
            fmt_num(row.get("partition_effective_band_gap"), 2),
            fmt_num(row.get("mean_feature_forecast_gap"), 2),
        ]
        for row in selected
    ]


def regime_table(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("regime_label"),
            row.get("n"),
            row.get("market_days"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_pct(row.get("winner_model_probability")),
            fmt_pct(row.get("winner_market_probability")),
            fmt_num(row.get("partition_effective_band_gap"), 2),
            fmt_num(row.get("mean_feature_forecast_gap"), 2),
        ]
        for row in rows
    ]


def probe_table(probes: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for name, probe in probes.items():
        summary = probe.get("weak_slot_summary") or {}
        rows.append(
            [
                name,
                "yes" if probe.get("uses_market_prices") else "no",
                summary.get("row_count"),
                fmt_signed(summary.get("weighted_brier_delta_vs_base")),
                fmt_signed(summary.get("weighted_logloss_delta_vs_base")),
                ", ".join(str(item) for item in (summary.get("best_parameters") or [])[:8]),
            ]
        )
    return rows


def candidate_regime_table(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("regime_label"),
            row.get("n"),
            row.get("market_days"),
            fmt_num(row.get("variant_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current")),
            fmt_signed(row.get("delta_vs_market")),
            fmt_pct(row.get("winner_variant_probability")),
            fmt_pct(row.get("winner_current_probability")),
            fmt_pct(row.get("winner_market_probability")),
        ]
        for row in rows
    ]


def render_report(payload: dict[str, Any]) -> str:
    corpus = payload.get("corpus") or {}
    overall = payload.get("overall") or {}
    rankings = payload.get("rankings") or {}
    weak = payload.get("weak_slots") or {}
    weak_summary = weak.get("summary") or {}
    gate = payload.get("ten_minute_performance_gate") or {}
    candidate_gate = payload.get("candidate_ten_minute_gate") or {}
    candidate = payload.get("candidate_item147") or {}
    overlap = candidate.get("weak_slot_overlap") or {}
    probes = payload.get("replay_probes") or {}
    liveness = payload.get("scoring_liveness") or {}
    worst_abs = rankings.get("worst_absolute") or []
    worst_vs_market = rankings.get("worst_vs_market") or []
    best_abs = rankings.get("best_absolute") or []

    lines = [
        "# 10-Minute Model Performance Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Executive Summary",
        "",
        (
            "The weakest absolute 10-minute slots are concentrated in the predawn/early-morning period, "
            "especially the 03:00-05:50 local window. The failure mode is not just calibration noise: "
            "the model assigns materially less probability to the eventual winning band than the market "
            "and spreads probability across more effective bands."
        ),
        "",
        (
            "Replay-only probes show that market-price blending can reduce weak-slot error, but that is "
            "quote-risk mitigation rather than a weather-model improvement. The no-market time-split alpha "
            "candidate (`item147_time_split_alpha`) is the strongest tested weather-model remedy in this "
            "audit: on its own 10-minute checkpoint corpus, it improves early-morning Brier versus current "
            "and is approximately market-parity."
        ),
        "",
        "## Scope And Method",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Selected settlement labels", corpus.get("selected_label_count")],
            ["Scored market-days", corpus.get("scored_market_days")],
            ["Markets", ", ".join(corpus.get("markets") or [])],
            ["Date range", f"{corpus.get('date_min')} to {corpus.get('date_max')}"],
            ["Scoring liveness", liveness.get("status") or "-"],
            ["Last scored target date", liveness.get("last_scored_target_date") or "-"],
            ["Latest settled label date", liveness.get("latest_settled_label_date") or "-"],
            ["All scored snapshot rows", corpus.get("all_snapshot_rows")],
            ["10-minute checkpoint rows", corpus.get("ten_minute_checkpoint_rows")],
            ["Skipped labels", json.dumps(corpus.get("skipped_labels") or {}, sort_keys=True)],
            ["Score errors", len(corpus.get("score_errors") or [])],
        ],
    )
    lines += [
        "",
        (
            "Method: score each `snapshots_long.csv` row against the settlement bucket, then keep the first "
            "available row per market-day-band-10-minute local slot. This prevents dense capture periods "
            "from overweighting the slot ranking."
        ),
        "",
        "## Overall 10-Minute Checkpoint Score",
        "",
    ]
    lines += markdown_table(
        [
            "Rows",
            "Market-days",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Model LogLoss",
            "LogLoss Delta",
            "Winner Model P",
            "Winner Market P",
        ],
        [
            [
                overall.get("n"),
                overall.get("market_days"),
                fmt_num(overall.get("model_brier")),
                fmt_num(overall.get("market_brier")),
                fmt_signed(overall.get("brier_delta")),
                fmt_num(overall.get("model_logloss")),
                fmt_signed(overall.get("logloss_delta")),
                fmt_pct(overall.get("winner_model_probability")),
                fmt_pct(overall.get("winner_market_probability")),
            ]
        ],
    )
    lines += [
        "",
        "## Worst Slots By Absolute Model Brier",
        "",
    ]
    lines += markdown_table(
        [
            "Slot",
            "Rows",
            "Days",
            "Markets",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Model LogLoss",
            "LogLoss Delta",
            "Winner Model P",
            "Winner Market P",
            "Eff Band Gap",
            "Forecast Gap",
        ],
        slot_table(worst_abs, limit=20),
    )
    lines += [
        "",
        "## Worst Slots Versus Market",
        "",
    ]
    lines += markdown_table(
        [
            "Slot",
            "Rows",
            "Days",
            "Markets",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Model LogLoss",
            "LogLoss Delta",
            "Winner Model P",
            "Winner Market P",
            "Eff Band Gap",
            "Forecast Gap",
        ],
        slot_table(worst_vs_market, limit=20),
    )
    lines += [
        "",
        "## Best Slots",
        "",
    ]
    lines += markdown_table(
        [
            "Slot",
            "Rows",
            "Days",
            "Markets",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Model LogLoss",
            "LogLoss Delta",
            "Winner Model P",
            "Winner Market P",
            "Eff Band Gap",
            "Forecast Gap",
        ],
        slot_table(best_abs, limit=10),
    )
    lines += [
        "",
        "## Regime View",
        "",
    ]
    lines += markdown_table(
        [
            "Regime",
            "Rows",
            "Days",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Winner Model P",
            "Winner Market P",
            "Eff Band Gap",
            "Forecast Gap",
        ],
        regime_table(payload.get("by_regime") or []),
    )
    lines += [
        "",
        "## Weak-Slot Definition",
        "",
        (
            "Weak slots are eligible 10-minute slots in the top decile of model Brier. "
            f"Slots: {', '.join(weak.get('slot_labels') or []) or '-'}."
        ),
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Weak slot count", weak_summary.get("slot_count")],
            ["Rows", weak_summary.get("n")],
            ["Market-days", weak_summary.get("market_days")],
            ["Model Brier", fmt_num(weak_summary.get("model_brier"))],
            ["Market Brier", fmt_num(weak_summary.get("market_brier"))],
            ["Brier Delta", fmt_signed(weak_summary.get("brier_delta"))],
            ["Winner Model P", fmt_pct(weak_summary.get("winner_model_probability"))],
            ["Winner Market P", fmt_pct(weak_summary.get("winner_market_probability"))],
            ["Effective band gap", fmt_num(weak_summary.get("partition_effective_band_gap"), 2)],
            ["Forecast gap", fmt_num(weak_summary.get("mean_feature_forecast_gap"), 2)],
        ],
    )
    lines += [
        "",
        "## 10-Minute Performance Gate",
        "",
    ]
    gate_first = gate.get("first_blocker") or {}
    candidate_first = candidate_gate.get("first_blocker") or {}
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Current gate status", gate.get("status") or "-"],
            ["Current blockers", gate.get("blocker_count", 0)],
            ["First current blocker", gate_first.get("detail") or "-"],
            ["Candidate gate status", candidate_gate.get("status") or "-"],
            ["Candidate blockers", candidate_gate.get("blocker_count", 0)],
            ["First candidate blocker", candidate_first.get("detail") or "-"],
        ],
    )
    lines += [
        "",
        "## Theories Tested",
        "",
        "### 1. The weak slots are a predawn unresolved-high problem",
        "",
        (
            "Supported. The highest model-Brier slots cluster before local sunrise/early heating, "
            "when the current high is still far below the forecast high. The weak-slot forecast gap "
            f"is {fmt_num(weak_summary.get('mean_feature_forecast_gap'), 2)}, and winner probability "
            f"is {fmt_pct(weak_summary.get('winner_model_probability'))} for the model versus "
            f"{fmt_pct(weak_summary.get('winner_market_probability'))} for the market."
        ),
        "",
        "### 2. The model is too diffuse or off-center around the eventual winner",
        "",
        (
            "Supported. In weak slots, the model's effective-band count exceeds the market's by "
            f"{fmt_num(weak_summary.get('partition_effective_band_gap'), 2)} bands on average, "
            "and the winner-probability gap remains negative. That points to both distribution "
            "spread and center placement, not merely a Brier scoring artifact."
        ),
        "",
        "### 3. It is probably not a settlement-quality artifact",
        "",
        (
            "Supported but not fully proven. The headline scope excludes partial labels by default "
            "and uses only complete/manual-override settlement labels. The remaining weak slots span "
            f"{weak_summary.get('market_days')} market-days, so the pattern is broader than one bad tape."
        ),
        "",
        "### 4. Simple probability-shape fixes are not enough",
        "",
        (
            "Mostly supported. The partition-power probe is weather-only and tests whether sharpening "
            "or softening the model partition fixes the weak slots. Its weighted weak-slot Brier delta "
            f"is {fmt_signed((probes.get('partition_power') or {}).get('weak_slot_summary', {}).get('weighted_brier_delta_vs_base'))}, "
            "so output-shape tuning alone is not the whole repair."
        ),
        "",
        "### 5. A time-split/early-hour weather candidate is promising",
        "",
    ]
    if candidate.get("available"):
        early = next((row for row in candidate.get("by_regime") or [] if row.get("regime") == "early_morning"), {})
        lines.append(
            "Supported on the candidate corpus. `item147_time_split_alpha` early-morning Brier is "
            f"{fmt_num(early.get('variant_brier'))} versus current {fmt_num(early.get('current_brier'))} "
            f"and market {fmt_num(early.get('market_brier'))}. On overlapping weak slots, its "
            f"Brier delta versus current is {fmt_signed(overlap.get('delta_vs_current'))}."
        )
    else:
        lines.append("Not tested: the item147 candidate row export was not available.")
    lines += [
        "",
        "## Improvement Tests",
        "",
        "Replay probes on the current 10-minute weak slots:",
        "",
    ]
    lines += markdown_table(
        ["Probe", "Uses Market", "Rows", "Brier Delta Vs Base", "LogLoss Delta Vs Base", "Best Parameters Sample"],
        probe_table(probes),
    )
    if candidate.get("available"):
        lines += [
            "",
            "Candidate item147 10-minute checkpoint corpus:",
            "",
        ]
        lines += markdown_table(
            [
                "Regime",
                "Rows",
                "Days",
                "Variant Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Winner Variant P",
                "Winner Current P",
                "Winner Market P",
            ],
            candidate_regime_table(candidate.get("by_regime") or []),
        )
        lines += [
            "",
            "Candidate weak-slot overlap:",
            "",
        ]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Weak slots", overlap.get("weak_slot_count")],
                ["Candidate slot overlap", overlap.get("candidate_slot_overlap")],
                ["Rows", overlap.get("row_count")],
                ["Market-days", overlap.get("market_days")],
                ["Delta vs current", fmt_signed(overlap.get("delta_vs_current"))],
                ["Delta vs market", fmt_signed(overlap.get("delta_vs_market"))],
                ["Log-loss delta vs current", fmt_signed(overlap.get("logloss_delta_vs_current"))],
                ["Log-loss delta vs market", fmt_signed(overlap.get("logloss_delta_vs_market"))],
            ],
        )
    lines += [
        "",
        "## Recommendations",
        "",
        "- Promote `item147_time_split_alpha` into the next no-market candidate bakeoff lane for early-hour serving checks, not directly into serving.",
        "- Add a 10-minute candidate gate mirroring this audit so early-hour improvements cannot hide inside hourly averages.",
        "- Keep market-blend or CLOB-aware overlays in the quote-risk lane only; they help execution risk but should not count as weather-model skill.",
        "- Focus the next weather-model iteration on winner centering before 06:00 local: forecast-relative anchor strength, time-to-heating features, and market-specific overnight climatology.",
        "- Preserve the full all-slot CSV as the operational watchlist; the Markdown report intentionally shows only the highest-signal rows.",
        "",
        "## Caveats",
        "",
        "- Rows from the same market day are correlated; slot-level sample sizes overstate independent evidence.",
        "- The item147 candidate corpus covers fewer market-days than the full current corpus, so its improvement is directional until replayed on the broader settled set.",
        "- Market prices are a strong benchmark late in the day because resolution uncertainty is low; this makes late-day model-vs-market deltas look poor even when absolute model Brier is low.",
        "",
    ]
    return "\n".join(lines)


SLOT_CSV_COLUMNS = [
    "time_slot_minute",
    "time_slot_label",
    "hour",
    "minute",
    "regime",
    "n",
    "market_days",
    "markets",
    "snapshots",
    "model_brier",
    "market_brier",
    "brier_delta",
    "brier_skill_score",
    "model_logloss",
    "market_logloss",
    "logloss_delta",
    "model_ece",
    "market_ece",
    "winner_model_probability",
    "winner_market_probability",
    "winner_catchup_gap",
    "partition_model_effective_bands",
    "partition_market_effective_bands",
    "partition_effective_band_gap",
    "partition_model_top_is_winner_rate",
    "partition_market_top_is_winner_rate",
    "partition_winner_rank_gap",
    "mean_feature_forecast_gap",
    "mean_feature_high_so_far",
    "mean_feature_current_temp",
    "mean_feature_minutes_since_cutoff",
]


CANDIDATE_CSV_COLUMNS = [
    "time_slot_minute",
    "time_slot_label",
    "hour",
    "minute",
    "regime",
    "n",
    "market_days",
    "markets",
    "snapshots",
    "variant_brier",
    "current_brier",
    "market_brier",
    "delta_vs_current",
    "delta_vs_market",
    "variant_logloss",
    "current_logloss",
    "market_logloss",
    "logloss_delta_vs_current",
    "logloss_delta_vs_market",
    "variant_ece",
    "current_ece",
    "market_ece",
    "winner_variant_probability",
    "winner_current_probability",
    "winner_market_probability",
]


def write_csv(rows: list[dict[str, Any]], path: Path, columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_outputs(
    payload: dict[str, Any],
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    slot_csv_out=DEFAULT_SLOT_CSV_OUT,
    candidate_csv_out=DEFAULT_CANDIDATE_CSV_OUT,
) -> tuple[Path, Path, Path, Path | None]:
    json_out = Path(json_out)
    report_out = Path(report_out)
    slot_csv_out = Path(slot_csv_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    write_csv(payload.get("by_slot") or [], slot_csv_out, SLOT_CSV_COLUMNS)
    candidate_csv = None
    candidate = payload.get("candidate_item147") or {}
    if candidate.get("available"):
        candidate_csv = write_csv(candidate.get("by_slot") or [], Path(candidate_csv_out), CANDIDATE_CSV_COLUMNS)
    return json_out, report_out, slot_csv_out, candidate_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit model performance by 10-minute local slots.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES))
    parser.add_argument(
        "--strict-quality-grades-only",
        action="store_true",
        help="Do not include labels that are promotion-countable but outside --quality-grades.",
    )
    parser.add_argument("--markets", default="")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--top-slots", type=int, default=DEFAULT_TOP_SLOTS)
    parser.add_argument("--min-weak-market-days", type=int, default=DEFAULT_MIN_WEAK_MARKET_DAYS)
    parser.add_argument("--weak-brier-regression-tolerance", type=float, default=DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE)
    parser.add_argument("--weak-logloss-regression-tolerance", type=float, default=DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE)
    parser.add_argument("--candidate-min-weak-market-days", type=int, default=DEFAULT_MIN_WEAK_MARKET_DAYS)
    parser.add_argument(
        "--candidate-weak-brier-improvement-min",
        type=float,
        default=DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
    )
    parser.add_argument(
        "--candidate-weak-market-regression-tolerance",
        type=float,
        default=DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--candidate-weak-logloss-regression-tolerance",
        type=float,
        default=DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--item147-rows", default=str(DEFAULT_ITEM147_ROWS))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--slot-csv-out", default=str(DEFAULT_SLOT_CSV_OUT))
    parser.add_argument("--candidate-csv-out", default=str(DEFAULT_CANDIDATE_CSV_OUT))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = build_payload(args)
    json_out, report_out, slot_csv_out, candidate_csv = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        slot_csv_out=args.slot_csv_out,
        candidate_csv_out=args.candidate_csv_out,
    )
    corpus = payload.get("corpus") or {}
    overall = payload.get("overall") or {}
    weak = payload.get("weak_slots") or {}
    print(f"Wrote {relative_to_repo(json_out)}")
    print(f"Wrote {relative_to_repo(report_out)}")
    print(f"Wrote {relative_to_repo(slot_csv_out)}")
    if candidate_csv:
        print(f"Wrote {relative_to_repo(candidate_csv)}")
    print(
        "10-minute checkpoint model Brier "
        f"{overall.get('model_brier'):.4f} vs market {overall.get('market_brier'):.4f} "
        f"across {corpus.get('scored_market_days')} market-days"
    )
    print("Weak slots: " + ", ".join(weak.get("slot_labels") or []))
    gate = payload.get("ten_minute_performance_gate") or {}
    print(f"10-minute performance gate: {gate.get('status')} ({gate.get('blocker_count', 0)} blocker(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
