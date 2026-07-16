"""Bounded market-day aggregation for hourly model performance."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from weather.reporting.hourly.hourly_model_scoring import (
    DRIVER_NUMERIC_FIELDS,
    FORECAST_CENTERING_BLEND_GRID,
    FORECAST_CENTERING_SIGMA,
    HOUR_REGIME_LABELS,
    MARKET_BLEND_GRID,
    PARTITION_POWER_GRID,
    hour_regime,
    hourly_checkpoint_rows,
    snapshot_partition_stats,
)
from weather.reporting.hourly.hourly_model_slots import (
    forecast_centering_rows,
    market_blend_rows,
    partition_power_rows,
)
from weather.scoring.metrics import binary_log_loss, safe_float


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


REMEDIATION_PROBE_SPECS = {
    "market_blend": {
        "description": "Blend model probability toward market yes price: (1-alpha)*model + alpha*market.",
        "uses_market_prices": True,
        "grid": MARKET_BLEND_GRID,
        "transform_fn": market_blend_rows,
    },
    "partition_power": {
        "description": (
            "Normalize each snapshot partition after p**gamma; gamma < 1 softens, "
            "gamma > 1 sharpens."
        ),
        "uses_market_prices": False,
        "grid": PARTITION_POWER_GRID,
        "transform_fn": partition_power_rows,
    },
    "forecast_centering": {
        "description": (
            "Blend model probability toward a forecast-high anchored Gaussian "
            "band projection; no market prices are used."
        ),
        "uses_market_prices": False,
        "grid": FORECAST_CENTERING_BLEND_GRID,
        "transform_fn": forecast_centering_rows,
        "sigma": FORECAST_CENTERING_SIGMA,
    },
}


class _WindowedSummary:
    """Mergeable sufficient statistics for ``summarize_rows`` without rows."""

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
    def _number(value: Any) -> float | None:
        number = safe_float(value)
        if number is None or math.isnan(number):
            return None
        return float(number)

    def _add_numeric(self, key: str, value: Any) -> None:
        number = self._number(value)
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
            edge = self._number(row.get("model_edge"))
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
                number = self._number(partition.get(source_field))
                if number is None:
                    continue
                self.partition_sums[source_field] += number
                self.partition_counts[source_field] += 1

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
                    if winner_model_probability is not None
                    and winner_market_probability is not None
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
    """Exact distinct counts for fixed report scopes without RAM growth."""

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
                "scope TEXT NOT NULL, value TEXT NOT NULL, "
                "PRIMARY KEY (scope, value)) WITHOUT ROWID"
            )

    @staticmethod
    def _identity(value: Any) -> str:
        return json.dumps(value, default=str, separators=(",", ":"))

    def add(self, scope: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        market_days = [
            (scope, self._identity([row.get("market_id"), row.get("target_date")]))
            for row in rows
        ]
        markets = [
            (scope, self._identity(row.get("market_id")))
            for row in rows
            if row.get("market_id") not in (None, "")
        ]
        snapshots = [
            (scope, self._identity(row.get("snapshot_id")))
            for row in rows
            if row.get("snapshot_id") not in (None, "")
        ]
        self.connection.executemany(
            "INSERT OR IGNORE INTO market_days (scope, value) VALUES (?, ?)",
            market_days,
        )
        self.connection.executemany(
            "INSERT OR IGNORE INTO markets (scope, value) VALUES (?, ?)",
            markets,
        )
        self.connection.executemany(
            "INSERT OR IGNORE INTO snapshots (scope, value) VALUES (?, ?)",
            snapshots,
        )

    def commit(self) -> None:
        self.connection.commit()

    def counts(self, scope: str) -> dict[str, int]:
        return {
            table: int(
                self.connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE scope = ?",
                    (scope,),
                ).fetchone()[0]
            )
            for table in self.TABLES
        }

    def close(self) -> None:
        self.connection.close()


class HourlyMarketDayAggregation:
    """Fold one complete scored market-day at a time into fixed report state."""

    CHECKPOINT_OVERALL = "checkpoint:overall"
    ALL_SNAPSHOT_OVERALL = "all_snapshot:overall"

    def __init__(self, scratch_root: str | Path) -> None:
        scratch_root = Path(scratch_root)
        scratch_root.mkdir(parents=True, exist_ok=True)
        self._distinct = _DiskDistinctIndex(scratch_root / "hourly_distincts.sqlite3")
        self._checkpoint_overall = _WindowedSummary()
        self._checkpoint_by_hour: dict[int, _WindowedSummary] = {}
        self._checkpoint_by_regime: dict[str, _WindowedSummary] = {}
        self._early_by_market: dict[Any, _WindowedSummary] = {}
        self._all_snapshot_overall = _WindowedSummary()
        self._all_snapshot_by_hour: dict[int, _WindowedSummary] = {}
        self._probe_scores: dict[str, dict[int, dict[float, _WindowedModelScore]]] = {
            name: {} for name in REMEDIATION_PROBE_SPECS
        }
        self.all_snapshot_row_count = 0
        self.checkpoint_row_count = 0
        self._closed = False

    def __enter__(self) -> "HourlyMarketDayAggregation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._distinct.close()
            self._closed = True

    @staticmethod
    def _hour_scope(prefix: str, hour: int) -> str:
        return f"{prefix}:hour:{int(hour)}"

    @staticmethod
    def _regime_scope(regime: str) -> str:
        return f"checkpoint:regime:{regime}"

    @staticmethod
    def _market_scope(market_id: Any) -> str:
        identity = json.dumps(market_id, default=str, separators=(",", ":"))
        return f"checkpoint:early_market:{identity}"

    @staticmethod
    def _rows_by_hour(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            hour = row.get("cutoff_hour")
            if hour is not None:
                grouped[int(hour)].append(row)
        return grouped

    def add_market_day_rows(self, rows: list[dict[str, Any]]) -> int:
        """Aggregate a market-day and retain no source row after this call."""

        self.all_snapshot_row_count += len(rows)
        self._all_snapshot_overall.update(rows)
        self._distinct.add(self.ALL_SNAPSHOT_OVERALL, rows)
        all_by_hour = self._rows_by_hour(rows)
        for hour, hour_rows in all_by_hour.items():
            self._all_snapshot_by_hour.setdefault(hour, _WindowedSummary()).update(hour_rows)
            self._distinct.add(self._hour_scope("all_snapshot", hour), hour_rows)

        checkpoints = hourly_checkpoint_rows(rows)
        self.checkpoint_row_count += len(checkpoints)
        self._checkpoint_overall.update(checkpoints)
        self._distinct.add(self.CHECKPOINT_OVERALL, checkpoints)
        checkpoint_by_hour = self._rows_by_hour(checkpoints)
        for hour, hour_rows in checkpoint_by_hour.items():
            self._checkpoint_by_hour.setdefault(hour, _WindowedSummary()).update(hour_rows)
            self._distinct.add(self._hour_scope("checkpoint", hour), hour_rows)
            for name, spec in REMEDIATION_PROBE_SPECS.items():
                parameter_scores = self._probe_scores[name].setdefault(
                    hour,
                    {float(value): _WindowedModelScore() for value in spec["grid"]},
                )
                for parameter in spec["grid"]:
                    transformed = spec["transform_fn"](hour_rows, parameter)
                    parameter_scores[float(parameter)].update(transformed)

        checkpoint_by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
        early_by_market: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for row in checkpoints:
            regime = hour_regime(row.get("cutoff_hour"))
            if regime:
                checkpoint_by_regime[regime].append(row)
            market_id = row.get("market_id")
            if regime == "early_morning" and market_id:
                early_by_market[market_id].append(row)
        for regime, regime_rows in checkpoint_by_regime.items():
            self._checkpoint_by_regime.setdefault(regime, _WindowedSummary()).update(regime_rows)
            self._distinct.add(self._regime_scope(regime), regime_rows)
        for market_id, market_rows in early_by_market.items():
            self._early_by_market.setdefault(market_id, _WindowedSummary()).update(market_rows)
            self._distinct.add(self._market_scope(market_id), market_rows)
        self._distinct.commit()
        return len(checkpoints)

    def _finalize(self, summary: _WindowedSummary, scope: str) -> dict[str, Any] | None:
        return summary.finalize(self._distinct.counts(scope))

    def overall_checkpoint(self) -> dict[str, Any] | None:
        return self._finalize(self._checkpoint_overall, self.CHECKPOINT_OVERALL)

    def overall_all_snapshots(self) -> dict[str, Any] | None:
        return self._finalize(self._all_snapshot_overall, self.ALL_SNAPSHOT_OVERALL)

    def by_hour(self) -> list[dict[str, Any]]:
        output = []
        for hour in sorted(self._checkpoint_by_hour):
            summary = self._finalize(
                self._checkpoint_by_hour[hour],
                self._hour_scope("checkpoint", hour),
            )
            if summary:
                summary.update({"hour": hour, "hour_label": f"{hour:02d}:00"})
                output.append(summary)
        return output

    def by_hour_regime(self) -> list[dict[str, Any]]:
        output = []
        for regime, label in HOUR_REGIME_LABELS.items():
            accumulator = self._checkpoint_by_regime.get(regime)
            if not accumulator:
                continue
            summary = self._finalize(accumulator, self._regime_scope(regime))
            if summary:
                summary.update({"regime": regime, "regime_label": label})
                output.append(summary)
        return output

    def all_snapshot_by_hour(self) -> list[dict[str, Any]]:
        output = []
        for hour in sorted(self._all_snapshot_by_hour):
            summary = self._finalize(
                self._all_snapshot_by_hour[hour],
                self._hour_scope("all_snapshot", hour),
            )
            if summary:
                summary.update({"hour": hour, "hour_label": f"{hour:02d}:00"})
                output.append(summary)
        return output

    def remediation_candidates(self) -> dict[str, Any]:
        output = {}
        early_hours = set(range(9))
        by_hour_summary = {
            int(row["hour"]): row
            for row in self.by_hour()
            if row.get("hour") is not None
        }
        for name, spec in REMEDIATION_PROBE_SPECS.items():
            probe_rows = []
            for hour, parameter_scores in sorted(self._probe_scores[name].items()):
                base = by_hour_summary.get(hour)
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
                            "logloss_delta_vs_base": (
                                score["model_logloss"] - base["model_logloss"]
                            ),
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
                        "hour": hour,
                        "hour_label": f"{hour:02d}:00",
                        "base_model_brier": base["model_brier"],
                        "base_model_logloss": base["model_logloss"],
                        "best": best,
                        "variants": variants,
                    }
                )
            probe = {
                "description": spec["description"],
                "uses_market_prices": spec["uses_market_prices"],
                "grid": list(spec["grid"]),
                "by_hour": probe_rows,
                "early_hours": [row for row in probe_rows if row["hour"] in early_hours],
            }
            if "sigma" in spec:
                probe["sigma"] = spec["sigma"]
            output[name] = probe
        return output

    def early_hour_market_deltas(
        self,
        *,
        early_brier_regression_tolerance: float,
        early_logloss_regression_tolerance: float,
    ) -> list[dict[str, Any]]:
        output = []
        for market_id, accumulator in sorted(
            self._early_by_market.items(),
            key=lambda item: str(item[0]),
        ):
            summary = self._finalize(accumulator, self._market_scope(market_id))
            if not summary:
                continue
            brier_delta = safe_float(summary.get("brier_delta"))
            logloss_delta = safe_float(summary.get("logloss_delta"))
            blocking_gates = []
            if (
                brier_delta is not None
                and brier_delta < -float(early_brier_regression_tolerance)
            ):
                blocking_gates.append("early_hour_brier_regression")
            if (
                logloss_delta is not None
                and logloss_delta < -float(early_logloss_regression_tolerance)
            ):
                blocking_gates.append("early_hour_logloss_regression")
            output.append(
                {
                    "market_id": market_id,
                    "status": "BLOCK" if blocking_gates else "PASS",
                    "blocking_gates": blocking_gates,
                    "n": summary.get("n"),
                    "market_days": summary.get("market_days"),
                    "snapshots": summary.get("snapshots"),
                    "model_brier": summary.get("model_brier"),
                    "market_brier": summary.get("market_brier"),
                    "brier_delta": brier_delta,
                    "model_logloss": summary.get("model_logloss"),
                    "market_logloss": summary.get("market_logloss"),
                    "logloss_delta": logloss_delta,
                    "model_ece": summary.get("model_ece"),
                    "winner_model_probability": summary.get("winner_model_probability"),
                    "winner_market_probability": summary.get("winner_market_probability"),
                }
            )
        return sorted(
            output,
            key=lambda row: (
                row.get("status") != "BLOCK",
                safe_float(row.get("brier_delta"))
                if row.get("brier_delta") is not None
                else math.inf,
                str(row.get("market_id") or ""),
            ),
        )


__all__ = ["HourlyMarketDayAggregation"]
