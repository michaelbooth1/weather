"""Attribute distribution-stage score deltas from persisted component snapshots."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic, write_text_atomic
from weather.model.model_presentation import DRIVER_WATERFALL_STAGES
from weather.runtime_identity import (
    format_runtime_identity,
    get_runtime_identity,
    identities_match,
)
from weather.paths import data_path
from weather.reporting.candidate_lifecycle.cutoff_regime_weighting import cutoff_regime
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("distribution_stage_attribution")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "distribution_stage_attribution.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "distribution_stage_attribution_report.md"
COMPONENT_FILENAME = "components_long.csv"
SETTLEMENT_FILENAME = "settlement.json"
EPSILON = 1e-9

STAGE_ORDER = tuple(key for key, _label in DRIVER_WATERFALL_STAGES)
STAGE_LABELS = dict(DRIVER_WATERFALL_STAGES)
FORECAST_SHAPE_STAGES = {"forecast_pull"}
EMPIRICAL_REGIMES = {"empirical", "calibrated_empirical"}
BOTTOM_LOCATION_MARKETS = ("miami", "nyc", "seattle")
BOTTOM_LOCATION_GUARD_STAGES = (
    "post_live_signals",
    "forecast_pull",
    "settlement_lag_adjusted",
    "current_observed_floor",
    "high_has_stood_lockin",
    "late_day_lockin",
    "final_model",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def maybe_int(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(number)


def label_numbers(value):
    if not value:
        return []
    return [int(match.group(0)) for match in re.finditer(r"(?<!\d)-?\d+", str(value))]


def band_key(row):
    kind = (row.get("bin_kind") or row.get("kind") or "").lower()
    value = maybe_int(row.get("bin_value_c") or row.get("bin_value") or row.get("value"))
    value_hi = maybe_int(row.get("bin_value_hi") or row.get("value_hi"))
    nums = label_numbers(row.get("range_label"))
    if value is None and nums:
        value = nums[0]
    if value_hi is None:
        value_hi = nums[-1] if kind == "eq" and len(nums) >= 2 else value
    return kind, value, value_hi


def band_outcome(row, settlement_bucket):
    if settlement_bucket is None:
        return None
    kind, value, value_hi = band_key(row)
    if value is None:
        return None
    if kind == "lte":
        return int(settlement_bucket <= value)
    if kind == "gte":
        return int(settlement_bucket >= value)
    if value_hi is None:
        value_hi = value
    return int(value <= settlement_bucket <= value_hi)


def binary_logloss(probability, outcome):
    p = max(EPSILON, min(1.0 - EPSILON, float(probability)))
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1.0 - p))


def binary_brier(probability, outcome):
    return (float(probability) - int(outcome)) ** 2


def effective_band_spread(probability):
    p = max(0.0, min(1.0, float(probability)))
    return 4.0 * p * (1.0 - p)


def is_adjacent_winner_band(row):
    settlement_bucket = maybe_int(row.get("settlement_bucket"))
    if settlement_bucket is None or row.get("outcome") == 1:
        return False
    kind = row.get("band_kind")
    value = maybe_int(row.get("band_value"))
    value_hi = maybe_int(row.get("band_value_hi"))
    if value is None:
        return False
    if kind == "lte":
        return value == settlement_bucket - 1
    if kind == "gte":
        return value == settlement_bucket + 1
    if value_hi is None:
        value_hi = value
    settlement_hi = settlement_bucket + max(0, value_hi - value)
    return value_hi == settlement_bucket - 1 or value == settlement_hi + 1


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def component_folders(snapshots_root):
    root = Path(snapshots_root)
    if not root.exists():
        return []
    return sorted(folder for folder in root.iterdir() if (folder / COMPONENT_FILENAME).exists())


def _score_component_row(row, folder, settlement):
    probability = maybe_float(row.get("component_probability"))
    settlement_bucket = maybe_int(settlement.get("settlement_bucket"))
    outcome = band_outcome(row, settlement_bucket)
    component_name = row.get("component_name")
    snapshot_id = row.get("snapshot_id")
    if probability is None or outcome is None or not component_name or not snapshot_id:
        return None
    probability = max(0.0, min(1.0, probability))
    kind, value, value_hi = band_key(row)
    return {
        "event_slug": row.get("event_slug") or settlement.get("event_slug") or folder.name,
        "market_id": settlement.get("market_id") or "",
        "target_date": settlement.get("target_date") or "",
        "snapshot_id": snapshot_id,
        "captured_at_utc": row.get("captured_at_utc") or "",
        "captured_at_local": row.get("captured_at_local") or "",
        "cutoff_hour": row.get("cutoff_hour") or "",
        "cutoff_regime": cutoff_regime(row.get("cutoff_hour")),
        "active_model_kind": row.get("active_model_kind") or "",
        "stage_regime": row.get("active_model_kind") or "unknown",
        "runtime_identity_schema_version": row.get("runtime_identity_schema_version") or "",
        "runtime_git_branch": row.get("runtime_git_branch") or "",
        "runtime_git_commit": row.get("runtime_git_commit") or "",
        "runtime_git_dirty": row.get("runtime_git_dirty") or "",
        "runtime_dirty_fingerprint": row.get("runtime_dirty_fingerprint") or "",
        "runtime_source_fingerprint": row.get("runtime_source_fingerprint") or "",
        "runtime_code_state": row.get("runtime_code_state") or "",
        "component_name": component_name,
        "component_label": STAGE_LABELS.get(component_name, component_name),
        "band_kind": kind,
        "band_value": value,
        "band_value_hi": value_hi,
        "settlement_bucket": settlement_bucket,
        "outcome": outcome,
        "probability": probability,
        "brier": binary_brier(probability, outcome),
        "logloss": binary_logloss(probability, outcome),
        "effective_band_spread": effective_band_spread(probability),
    }


def iter_attribution_rows_for_folder(folder):
    folder = Path(folder)
    settlement = read_json(folder / SETTLEMENT_FILENAME, default={}) or {}
    if maybe_int(settlement.get("settlement_bucket")) is None:
        return
    by_snapshot_band = defaultdict(dict)
    component_path = folder / COMPONENT_FILENAME
    with component_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            scored = _score_component_row(row, folder, settlement)
            if not scored:
                continue
            key = (
                scored["snapshot_id"],
                scored["band_kind"],
                scored["band_value"],
                scored["band_value_hi"],
            )
            by_snapshot_band[key][scored["component_name"]] = scored

    for components in by_snapshot_band.values():
        previous = None
        for component_name in STAGE_ORDER:
            current = components.get(component_name)
            if current is None:
                continue
            row = dict(current)
            if previous is None:
                row.update({
                    "previous_component_name": None,
                    "delta_brier": None,
                    "delta_logloss": None,
                    "winner_probability_delta": None,
                    "adjacent_winner_mass_delta": None,
                    "effective_band_spread_delta": None,
                })
            else:
                row.update({
                    "previous_component_name": previous["component_name"],
                    "delta_brier": row["brier"] - previous["brier"],
                    "delta_logloss": row["logloss"] - previous["logloss"],
                    "winner_probability_delta": (
                        row["probability"] - previous["probability"]
                        if row["outcome"] == 1
                        else None
                    ),
                    "adjacent_winner_mass_delta": (
                        row["probability"] - previous["probability"]
                        if is_adjacent_winner_band(row)
                        else None
                    ),
                    "effective_band_spread_delta": (
                        row["effective_band_spread"] - previous["effective_band_spread"]
                    ),
                })
            yield row
            previous = current


def attribution_rows_for_folder(folder):
    return list(iter_attribution_rows_for_folder(folder))


def _component_scope_row(row, folder):
    component_name = row.get("component_name")
    snapshot_id = row.get("snapshot_id")
    if not component_name or not snapshot_id:
        return None
    return {
        "event_slug": row.get("event_slug") or folder.name,
        "market_id": "",
        "target_date": "",
        "snapshot_id": snapshot_id,
        "captured_at_utc": row.get("captured_at_utc") or "",
        "captured_at_local": row.get("captured_at_local") or "",
        "cutoff_hour": row.get("cutoff_hour") or "",
        "active_model_kind": row.get("active_model_kind") or "",
        "stage_regime": row.get("active_model_kind") or "unknown",
        "runtime_identity_schema_version": row.get("runtime_identity_schema_version") or "",
        "runtime_git_branch": row.get("runtime_git_branch") or "",
        "runtime_git_commit": row.get("runtime_git_commit") or "",
        "runtime_git_dirty": row.get("runtime_git_dirty") or "",
        "runtime_dirty_fingerprint": row.get("runtime_dirty_fingerprint") or "",
        "runtime_source_fingerprint": row.get("runtime_source_fingerprint") or "",
        "runtime_code_state": row.get("runtime_code_state") or "",
        "component_name": component_name,
    }


def iter_component_scope_rows_for_folder(folder):
    folder = Path(folder)
    component_path = folder / COMPONENT_FILENAME
    with component_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            scope_row = _component_scope_row(row, folder)
            if scope_row:
                yield scope_row


def component_scope_rows_for_folder(folder):
    return list(iter_component_scope_rows_for_folder(folder))


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


class _RunningMean:
    __slots__ = ("count", "total")

    def __init__(self):
        self.count = 0
        self.total = 0

    def add(self, value):
        if value is None:
            return
        self.total += value
        self.count += 1

    def value(self):
        return self.total / self.count if self.count else None


class _MetricAggregate:
    __slots__ = (
        "n",
        "delta_n",
        "brier",
        "logloss",
        "delta_brier",
        "delta_logloss",
        "winner_probability_delta",
        "adjacent_winner_mass_delta",
        "effective_band_spread_delta",
        "brier_worse_rows",
        "brier_better_rows",
    )

    def __init__(self):
        self.n = 0
        self.delta_n = 0
        self.brier = _RunningMean()
        self.logloss = _RunningMean()
        self.delta_brier = _RunningMean()
        self.delta_logloss = _RunningMean()
        self.winner_probability_delta = _RunningMean()
        self.adjacent_winner_mass_delta = _RunningMean()
        self.effective_band_spread_delta = _RunningMean()
        self.brier_worse_rows = 0
        self.brier_better_rows = 0

    def add(self, row):
        self.n += 1
        self.brier.add(row.get("brier"))
        self.logloss.add(row.get("logloss"))
        delta_brier = row.get("delta_brier")
        if delta_brier is None:
            return
        self.delta_n += 1
        self.delta_brier.add(delta_brier)
        self.delta_logloss.add(row.get("delta_logloss"))
        self.winner_probability_delta.add(row.get("winner_probability_delta"))
        self.adjacent_winner_mass_delta.add(row.get("adjacent_winner_mass_delta"))
        self.effective_band_spread_delta.add(row.get("effective_band_spread_delta"))
        if delta_brier > 0:
            self.brier_worse_rows += 1
        elif delta_brier < 0:
            self.brier_better_rows += 1

    def as_row(self, key, group_keys):
        output = {
            "group": " | ".join(key),
            "n": self.n,
            "delta_n": self.delta_n,
            "mean_brier": self.brier.value(),
            "mean_logloss": self.logloss.value(),
            "mean_delta_brier": self.delta_brier.value(),
            "mean_delta_logloss": self.delta_logloss.value(),
            "mean_winner_probability_delta": self.winner_probability_delta.value(),
            "mean_adjacent_winner_mass_delta": self.adjacent_winner_mass_delta.value(),
            "mean_effective_band_spread_delta": self.effective_band_spread_delta.value(),
            "brier_worse_rows": self.brier_worse_rows,
            "brier_better_rows": self.brier_better_rows,
        }
        for index, group_key in enumerate(group_keys):
            output[group_key] = key[index]
        return output


class _GroupedMetricAccumulator:
    __slots__ = ("group_keys", "groups")

    def __init__(self, group_keys=None):
        self.group_keys = tuple(group_keys or ())
        self.groups = {}

    def _key(self, row):
        if not self.group_keys:
            return ("all",)
        return tuple(
            str(row.get(item) if row.get(item) not in (None, "") else "-")
            for item in self.group_keys
        )

    def add(self, row):
        key = self._key(row)
        aggregate = self.groups.get(key)
        if aggregate is None:
            aggregate = self.groups[key] = _MetricAggregate()
        aggregate.add(row)

    def extend(self, rows):
        for row in rows:
            self.add(row)

    def as_rows(self):
        return [
            self.groups[key].as_row(key, self.group_keys)
            for key in sorted(self.groups)
        ]


def aggregate_rows_by_keys(rows, group_keys=None):
    accumulator = _GroupedMetricAccumulator(group_keys)
    accumulator.extend(rows)
    return accumulator.as_rows()


def aggregate_rows(rows, group_key=None):
    return aggregate_rows_by_keys(rows, () if group_key is None else (group_key,))


def bottom_location_guardrail_rows(
    rows,
    *,
    bottom_markets=BOTTOM_LOCATION_MARKETS,
    guard_stages=BOTTOM_LOCATION_GUARD_STAGES,
):
    market_day_stage = aggregate_rows_by_keys(
        rows,
        ("market_id", "target_date", "component_name", "cutoff_regime"),
    )
    return _bottom_location_guardrail_rows_from_aggregates(
        market_day_stage,
        bottom_markets=bottom_markets,
        guard_stages=guard_stages,
    )


def _bottom_location_guardrail_rows_from_aggregates(
    market_day_stage,
    *,
    bottom_markets=BOTTOM_LOCATION_MARKETS,
    guard_stages=BOTTOM_LOCATION_GUARD_STAGES,
):
    bottom = {str(market) for market in bottom_markets}
    stage_set = {str(stage) for stage in guard_stages}
    guardrails = []
    for row in market_day_stage:
        market_id = row.get("market_id")
        stage = row.get("component_name")
        winner_delta = row.get("mean_winner_probability_delta")
        brier_delta = row.get("mean_delta_brier")
        logloss_delta = row.get("mean_delta_logloss")
        if market_id not in bottom or stage not in stage_set or winner_delta is None:
            continue
        winner_mass_reduced = winner_delta < 0
        improved_scores = (
            brier_delta is not None
            and logloss_delta is not None
            and brier_delta < 0
            and logloss_delta < 0
        )
        status = "PASS" if not winner_mass_reduced or improved_scores else "BLOCK"
        reason = (
            "winner probability reduced without same-day Brier and log-loss improvement"
            if status == "BLOCK"
            else "winner probability preserved or score improvements justify the reduction"
        )
        guardrails.append({
            "market_id": market_id,
            "target_date": row.get("target_date"),
            "component_name": stage,
            "component_label": STAGE_LABELS.get(stage, stage),
            "cutoff_regime": row.get("cutoff_regime"),
            "status": status,
            "reason": reason,
            "n": row.get("n"),
            "delta_n": row.get("delta_n"),
            "mean_delta_brier": brier_delta,
            "mean_delta_logloss": logloss_delta,
            "mean_winner_probability_delta": winner_delta,
            "mean_adjacent_winner_mass_delta": row.get("mean_adjacent_winner_mass_delta"),
            "brier_better_rows": row.get("brier_better_rows", 0),
            "brier_worse_rows": row.get("brier_worse_rows", 0),
        })
    return sorted(
        guardrails,
        key=lambda row: (
            row.get("status") != "BLOCK",
            row.get("mean_winner_probability_delta") or 0.0,
            -(row.get("mean_delta_logloss") or 0.0),
            row.get("market_id") or "",
            row.get("target_date") or "",
        ),
    )


def _is_feature_model_regime(regime):
    regime = str(regime or "").strip().lower()
    return bool(regime and regime not in EMPIRICAL_REGIMES)


def _ordered_text(values, *, reverse=False):
    values = sorted((str(value) for value in values if value), reverse=reverse)
    return values[0] if values else None


def _row_runtime_identity(row):
    if not row:
        return {}
    return {
        "schema_version": row.get("runtime_identity_schema_version") or None,
        "git_branch": row.get("runtime_git_branch") or None,
        "git_commit": row.get("runtime_git_commit") or None,
        "git_dirty": row.get("runtime_git_dirty") or None,
        "dirty_fingerprint": row.get("runtime_dirty_fingerprint") or None,
        "source_fingerprint": row.get("runtime_source_fingerprint") or None,
    }


def _matches_current_runtime(row, current_identity):
    if not current_identity:
        return False
    return identities_match(_row_runtime_identity(row), current_identity)


def _unique_count(rows, key):
    return len({row.get(key) for row in rows if row.get(key)})


def forecast_shape_scope_summary(rows, *, current_identity=None, raw_rows=None):
    current_identity = current_identity or None
    scope_rows = list(raw_rows if raw_rows is not None else rows)
    shape_rows = [
        row for row in scope_rows
        if row.get("component_name") in FORECAST_SHAPE_STAGES
    ]
    scored_shape_rows = [
        row for row in rows
        if row.get("component_name") in FORECAST_SHAPE_STAGES
    ]
    feature_rows = [
        row for row in shape_rows
        if _is_feature_model_regime(row.get("stage_regime"))
    ]
    empirical_rows = [
        row for row in shape_rows
        if not _is_feature_model_regime(row.get("stage_regime"))
    ]
    scored_feature_rows = [
        row for row in scored_shape_rows
        if _is_feature_model_regime(row.get("stage_regime"))
    ]
    scored_empirical_rows = [
        row for row in scored_shape_rows
        if not _is_feature_model_regime(row.get("stage_regime"))
    ]
    current_rows = [
        row for row in scope_rows
        if _matches_current_runtime(row, current_identity)
    ]
    current_feature_model_rows = [
        row for row in current_rows
        if _is_feature_model_regime(row.get("stage_regime"))
    ]
    current_feature_rows = [
        row for row in feature_rows
        if _matches_current_runtime(row, current_identity)
    ]
    stale_feature_rows = [
        row for row in feature_rows
        if current_identity and not _matches_current_runtime(row, current_identity)
    ]
    feature_regimes = sorted({row.get("stage_regime") or "unknown" for row in feature_rows})
    empirical_regimes = sorted({row.get("stage_regime") or "unknown" for row in empirical_rows})
    feature_example = feature_rows[0] if feature_rows else {}
    current_feature_example = current_feature_rows[0] if current_feature_rows else {}
    has_current_feature_model_evidence = bool(current_feature_model_rows)
    if current_feature_rows:
        status = "BLOCK"
        reason = (
            "current-code forecast floor/pull rows were recorded under feature-model regimes: "
            + ", ".join(sorted({row.get("stage_regime") or "unknown" for row in current_feature_rows}))
        )
        next_unblock_action = (
            "remove current-code feature-model forecast-shape application or replay after the fix"
        )
    elif feature_rows and current_identity and not has_current_feature_model_evidence:
        status = "BLOCK"
        reason = (
            "feature-model forecast-shape rows are stale relative to current source, "
            "but no current-code feature-model component tape is available yet"
        )
        next_unblock_action = (
            "regenerate/replay a complete nonzero current-code feature-model component "
            "population and require current_code_feature_model_component_rows>0 with "
            "current_code_feature_model_forecast_shape_rows=0"
        )
    elif feature_rows and current_identity:
        status = "PASS"
        reason = (
            "forecast floor/pull rows under feature-model regimes are stale relative "
            "to current source; current-code feature-model rows have none"
        )
        next_unblock_action = None
    else:
        status = "PASS" if not feature_rows else "BLOCK"
        reason = (
            "forecast floor/pull is scoped to empirical fallback rows"
            if not feature_rows
            else "forecast floor/pull rows were recorded under feature-model regimes: "
            + ", ".join(feature_regimes)
        )
        next_unblock_action = None if not feature_rows else (
            "regenerate/replay after removing feature-model forecast-shape application"
        )
    return {
        "status": status,
        "current_identity": current_identity or {},
        "current_identity_text": format_runtime_identity(current_identity) if current_identity else None,
        "forecast_shape_stage_rows": len(shape_rows),
        "feature_model_forecast_shape_rows": len(feature_rows),
        "empirical_forecast_shape_rows": len(empirical_rows),
        "scored_forecast_shape_stage_rows": len(scored_shape_rows),
        "scored_feature_model_forecast_shape_rows": len(scored_feature_rows),
        "scored_empirical_forecast_shape_rows": len(scored_empirical_rows),
        "current_code_component_rows": len(current_rows),
        "current_code_snapshot_count": _unique_count(current_rows, "snapshot_id"),
        "current_code_feature_model_component_rows": len(current_feature_model_rows),
        "current_code_feature_model_snapshot_count": _unique_count(
            current_feature_model_rows,
            "snapshot_id",
        ),
        "current_code_feature_model_forecast_shape_rows": len(current_feature_rows),
        "stale_feature_model_forecast_shape_rows": len(stale_feature_rows),
        "feature_model_regimes": feature_regimes,
        "empirical_regimes": empirical_regimes,
        "feature_model_delta_brier": mean(row.get("delta_brier") for row in scored_feature_rows),
        "current_code_feature_model_delta_brier": mean(
            row.get("delta_brier") for row in current_feature_rows
        ),
        "feature_model_delta_logloss": mean(row.get("delta_logloss") for row in scored_feature_rows),
        "current_code_feature_model_delta_logloss": mean(
            row.get("delta_logloss") for row in current_feature_rows
        ),
        "empirical_delta_brier": mean(row.get("delta_brier") for row in scored_empirical_rows),
        "empirical_delta_logloss": mean(row.get("delta_logloss") for row in scored_empirical_rows),
        "empirical_winner_probability_delta": mean(
            row.get("winner_probability_delta") for row in scored_empirical_rows
        ),
        "earliest_feature_model_forecast_shape_at_utc": _ordered_text(
            row.get("captured_at_utc") for row in feature_rows
        ),
        "latest_feature_model_forecast_shape_at_utc": _ordered_text(
            (row.get("captured_at_utc") for row in feature_rows),
            reverse=True,
        ),
        "latest_stale_feature_model_forecast_shape_at_utc": _ordered_text(
            (row.get("captured_at_utc") for row in stale_feature_rows),
            reverse=True,
        ),
        "latest_current_code_feature_model_forecast_shape_at_utc": _ordered_text(
            (row.get("captured_at_utc") for row in current_feature_rows),
            reverse=True,
        ),
        "example_feature_model_forecast_shape": {
            "market_id": feature_example.get("market_id"),
            "target_date": feature_example.get("target_date"),
            "snapshot_id": feature_example.get("snapshot_id"),
            "captured_at_utc": feature_example.get("captured_at_utc"),
            "captured_at_local": feature_example.get("captured_at_local"),
            "active_model_kind": feature_example.get("active_model_kind"),
            "runtime_git_commit": feature_example.get("runtime_git_commit"),
            "runtime_source_fingerprint": feature_example.get("runtime_source_fingerprint"),
        } if feature_example else {},
        "example_current_code_feature_model_forecast_shape": {
            "market_id": current_feature_example.get("market_id"),
            "target_date": current_feature_example.get("target_date"),
            "snapshot_id": current_feature_example.get("snapshot_id"),
            "captured_at_utc": current_feature_example.get("captured_at_utc"),
            "captured_at_local": current_feature_example.get("captured_at_local"),
            "active_model_kind": current_feature_example.get("active_model_kind"),
            "runtime_git_commit": current_feature_example.get("runtime_git_commit"),
            "runtime_source_fingerprint": current_feature_example.get("runtime_source_fingerprint"),
        } if current_feature_example else {},
        "reason": reason,
        "next_unblock_action": next_unblock_action,
    }


def _forecast_shape_example(row):
    return {
        "market_id": row.get("market_id"),
        "target_date": row.get("target_date"),
        "snapshot_id": row.get("snapshot_id"),
        "captured_at_utc": row.get("captured_at_utc"),
        "captured_at_local": row.get("captured_at_local"),
        "active_model_kind": row.get("active_model_kind"),
        "runtime_git_commit": row.get("runtime_git_commit"),
        "runtime_source_fingerprint": row.get("runtime_source_fingerprint"),
    }


class _ForecastShapeScopeAccumulator:
    __slots__ = (
        "current_identity",
        "counts",
        "means",
        "current_snapshot_ids",
        "current_feature_snapshot_ids",
        "feature_regimes",
        "current_feature_regimes",
        "empirical_regimes",
        "examples",
        "times",
    )

    def __init__(self, current_identity=None):
        self.current_identity = current_identity or None
        self.counts = defaultdict(int)
        self.means = {
            "feature_model_delta_brier": _RunningMean(),
            "current_code_feature_model_delta_brier": _RunningMean(),
            "feature_model_delta_logloss": _RunningMean(),
            "current_code_feature_model_delta_logloss": _RunningMean(),
            "empirical_delta_brier": _RunningMean(),
            "empirical_delta_logloss": _RunningMean(),
            "empirical_winner_probability_delta": _RunningMean(),
        }
        self.current_snapshot_ids = set()
        self.current_feature_snapshot_ids = set()
        self.feature_regimes = set()
        self.current_feature_regimes = set()
        self.empirical_regimes = set()
        self.examples = {}
        self.times = {}

    def _record_time(self, earliest_key, latest_key, value):
        if not value:
            return
        value = str(value)
        earliest = self.times.get(earliest_key)
        latest = self.times.get(latest_key)
        if earliest is None or value < earliest:
            self.times[earliest_key] = value
        if latest is None or value > latest:
            self.times[latest_key] = value

    def add_scope(self, row):
        regime = row.get("stage_regime")
        feature_model = _is_feature_model_regime(regime)
        current = _matches_current_runtime(row, self.current_identity)
        snapshot_id = row.get("snapshot_id")
        if current:
            self.counts["current_code_component_rows"] += 1
            if snapshot_id:
                self.current_snapshot_ids.add(snapshot_id)
            if feature_model:
                self.counts["current_code_feature_model_component_rows"] += 1
                if snapshot_id:
                    self.current_feature_snapshot_ids.add(snapshot_id)

        if row.get("component_name") not in FORECAST_SHAPE_STAGES:
            return
        self.counts["forecast_shape_stage_rows"] += 1
        if feature_model:
            self.counts["feature_model_forecast_shape_rows"] += 1
            self.feature_regimes.add(regime or "unknown")
            if "feature" not in self.examples:
                self.examples["feature"] = _forecast_shape_example(row)
            self._record_time(
                "earliest_feature",
                "latest_feature",
                row.get("captured_at_utc"),
            )
            if current:
                self.counts["current_code_feature_model_forecast_shape_rows"] += 1
                self.current_feature_regimes.add(regime or "unknown")
                if "current_feature" not in self.examples:
                    self.examples["current_feature"] = _forecast_shape_example(row)
                self.means["current_code_feature_model_delta_brier"].add(
                    row.get("delta_brier")
                )
                self.means["current_code_feature_model_delta_logloss"].add(
                    row.get("delta_logloss")
                )
                self._record_time(
                    "earliest_current_feature",
                    "latest_current_feature",
                    row.get("captured_at_utc"),
                )
            elif self.current_identity:
                self.counts["stale_feature_model_forecast_shape_rows"] += 1
                self._record_time(
                    "earliest_stale_feature",
                    "latest_stale_feature",
                    row.get("captured_at_utc"),
                )
        else:
            self.counts["empirical_forecast_shape_rows"] += 1
            self.empirical_regimes.add(regime or "unknown")

    def add_scored(self, row):
        if row.get("component_name") not in FORECAST_SHAPE_STAGES:
            return
        self.counts["scored_forecast_shape_stage_rows"] += 1
        if _is_feature_model_regime(row.get("stage_regime")):
            self.counts["scored_feature_model_forecast_shape_rows"] += 1
            self.means["feature_model_delta_brier"].add(row.get("delta_brier"))
            self.means["feature_model_delta_logloss"].add(row.get("delta_logloss"))
        else:
            self.counts["scored_empirical_forecast_shape_rows"] += 1
            self.means["empirical_delta_brier"].add(row.get("delta_brier"))
            self.means["empirical_delta_logloss"].add(row.get("delta_logloss"))
            self.means["empirical_winner_probability_delta"].add(
                row.get("winner_probability_delta")
            )

    def summary(self):
        feature_rows = self.counts["feature_model_forecast_shape_rows"]
        current_feature_rows = self.counts["current_code_feature_model_forecast_shape_rows"]
        has_current_feature_model_evidence = bool(
            self.counts["current_code_feature_model_component_rows"]
        )
        feature_regimes = sorted(self.feature_regimes)
        if current_feature_rows:
            status = "BLOCK"
            reason = (
                "current-code forecast floor/pull rows were recorded under feature-model regimes: "
                + ", ".join(sorted(self.current_feature_regimes))
            )
            next_unblock_action = (
                "remove current-code feature-model forecast-shape application or "
                "replay after the fix"
            )
        elif feature_rows and self.current_identity and not has_current_feature_model_evidence:
            status = "BLOCK"
            reason = (
                "feature-model forecast-shape rows are stale relative to current source, "
                "but no current-code feature-model component tape is available yet"
            )
            next_unblock_action = (
                "regenerate/replay a complete nonzero current-code feature-model component "
                "population and require current_code_feature_model_component_rows>0 with "
                "current_code_feature_model_forecast_shape_rows=0"
            )
        elif feature_rows and self.current_identity:
            status = "PASS"
            reason = (
                "forecast floor/pull rows under feature-model regimes are stale relative "
                "to current source; current-code feature-model rows have none"
            )
            next_unblock_action = None
        else:
            status = "PASS" if not feature_rows else "BLOCK"
            reason = (
                "forecast floor/pull is scoped to empirical fallback rows"
                if not feature_rows
                else "forecast floor/pull rows were recorded under feature-model regimes: "
                + ", ".join(feature_regimes)
            )
            next_unblock_action = None if not feature_rows else (
                "regenerate/replay after removing feature-model forecast-shape application"
            )
        return {
            "status": status,
            "current_identity": self.current_identity or {},
            "current_identity_text": (
                format_runtime_identity(self.current_identity)
                if self.current_identity
                else None
            ),
            "forecast_shape_stage_rows": self.counts["forecast_shape_stage_rows"],
            "feature_model_forecast_shape_rows": feature_rows,
            "empirical_forecast_shape_rows": self.counts["empirical_forecast_shape_rows"],
            "scored_forecast_shape_stage_rows": self.counts[
                "scored_forecast_shape_stage_rows"
            ],
            "scored_feature_model_forecast_shape_rows": self.counts[
                "scored_feature_model_forecast_shape_rows"
            ],
            "scored_empirical_forecast_shape_rows": self.counts[
                "scored_empirical_forecast_shape_rows"
            ],
            "current_code_component_rows": self.counts["current_code_component_rows"],
            "current_code_snapshot_count": len(self.current_snapshot_ids),
            "current_code_feature_model_component_rows": self.counts[
                "current_code_feature_model_component_rows"
            ],
            "current_code_feature_model_snapshot_count": len(
                self.current_feature_snapshot_ids
            ),
            "current_code_feature_model_forecast_shape_rows": current_feature_rows,
            "stale_feature_model_forecast_shape_rows": self.counts[
                "stale_feature_model_forecast_shape_rows"
            ],
            "feature_model_regimes": feature_regimes,
            "empirical_regimes": sorted(self.empirical_regimes),
            **{name: accumulator.value() for name, accumulator in self.means.items()},
            "earliest_feature_model_forecast_shape_at_utc": self.times.get(
                "earliest_feature"
            ),
            "latest_feature_model_forecast_shape_at_utc": self.times.get("latest_feature"),
            "latest_stale_feature_model_forecast_shape_at_utc": self.times.get(
                "latest_stale_feature"
            ),
            "latest_current_code_feature_model_forecast_shape_at_utc": self.times.get(
                "latest_current_feature"
            ),
            "example_feature_model_forecast_shape": self.examples.get("feature", {}),
            "example_current_code_feature_model_forecast_shape": self.examples.get(
                "current_feature",
                {},
            ),
            "reason": reason,
            "next_unblock_action": next_unblock_action,
        }


def net_negative_stages(by_component, min_rows):
    rows = [
        row for row in by_component
        if row.get("delta_n", 0) >= min_rows
        and (
            (row.get("mean_delta_brier") is not None and row["mean_delta_brier"] > 0)
            or (row.get("mean_delta_logloss") is not None and row["mean_delta_logloss"] > 0)
        )
    ]
    return sorted(
        rows,
        key=lambda row: (
            max(0.0, row.get("mean_delta_logloss") or 0.0),
            max(0.0, row.get("mean_delta_brier") or 0.0),
        ),
        reverse=True,
    )


def build_payload(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    *,
    min_stage_rows=20,
    now=None,
    current_identity=None,
):
    current_identity = current_identity or get_runtime_identity()
    folders = component_folders(snapshots_root)
    settled_folders = 0
    attribution_row_count = 0
    overall_accumulator = _GroupedMetricAccumulator()
    component_accumulator = _GroupedMetricAccumulator(("component_name",))
    cutoff_hour_accumulator = _GroupedMetricAccumulator(("cutoff_hour",))
    regime_accumulator = _GroupedMetricAccumulator(("stage_regime",))
    market_accumulator = _GroupedMetricAccumulator(("market_id",))
    market_stage_accumulator = _GroupedMetricAccumulator(("market_id", "component_name"))
    market_stage_regime_accumulator = _GroupedMetricAccumulator(
        ("market_id", "component_name", "cutoff_regime")
    )
    guardrail_accumulator = _GroupedMetricAccumulator(
        ("market_id", "target_date", "component_name", "cutoff_regime")
    )
    forecast_shape_accumulator = _ForecastShapeScopeAccumulator(current_identity)
    metric_accumulators = (
        overall_accumulator,
        component_accumulator,
        cutoff_hour_accumulator,
        regime_accumulator,
        market_accumulator,
        market_stage_accumulator,
        market_stage_regime_accumulator,
        guardrail_accumulator,
    )
    for folder in folders:
        for scope_row in iter_component_scope_rows_for_folder(folder):
            forecast_shape_accumulator.add_scope(scope_row)
        folder_has_rows = False
        for row in iter_attribution_rows_for_folder(folder):
            folder_has_rows = True
            attribution_row_count += 1
            forecast_shape_accumulator.add_scored(row)
            for accumulator in metric_accumulators:
                accumulator.add(row)
        if folder_has_rows:
            settled_folders += 1

    by_component = component_accumulator.as_rows()
    negatives = net_negative_stages(by_component, min_rows=min_stage_rows)
    by_market_stage = market_stage_accumulator.as_rows()
    by_market_stage_cutoff_regime = market_stage_regime_accumulator.as_rows()
    bottom_guardrails = _bottom_location_guardrail_rows_from_aggregates(
        guardrail_accumulator.as_rows()
    )
    bottom_guardrail_blockers = [row for row in bottom_guardrails if row.get("status") == "BLOCK"]
    status = "NO_DATA" if not attribution_row_count else (
        "ACTIONABLE" if negatives or bottom_guardrail_blockers else "OK"
    )
    forecast_shape_scope = forecast_shape_accumulator.summary()
    overall_rows = overall_accumulator.as_rows()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now or utc_now(),
        "snapshots_root": str(Path(snapshots_root)),
        "current_identity": current_identity,
        "current_identity_text": format_runtime_identity(current_identity),
        "status": status,
        "folder_count": len(folders),
        "settled_folder_count": settled_folders,
        "attribution_row_count": attribution_row_count,
        "min_stage_rows": min_stage_rows,
        "summary": {
            "status": status,
            "net_negative_stage_count": len(negatives),
            "top_net_negative_stage": negatives[0] if negatives else None,
            "bottom_location_winner_mass_blocker_count": len(bottom_guardrail_blockers),
            "top_bottom_location_winner_mass_blocker": (
                bottom_guardrail_blockers[0] if bottom_guardrail_blockers else None
            ),
        },
        "overall": overall_rows[0] if overall_rows else {},
        "by_component": by_component,
        "by_cutoff_hour": cutoff_hour_accumulator.as_rows(),
        "by_regime": regime_accumulator.as_rows(),
        "by_market": market_accumulator.as_rows(),
        "by_market_stage": by_market_stage,
        "by_market_stage_cutoff_regime": by_market_stage_cutoff_regime,
        "bottom_location_winner_mass_guardrails": bottom_guardrails,
        "forecast_shape_scope": forecast_shape_scope,
        "net_negative_stages": negatives,
    }


def _metric_row(row):
    return [
        row.get("group"),
        row.get("n"),
        row.get("delta_n"),
        fmt_num(row.get("mean_brier")),
        fmt_num(row.get("mean_logloss")),
        fmt_signed(row.get("mean_delta_brier")),
        fmt_signed(row.get("mean_delta_logloss")),
        fmt_signed(row.get("mean_winner_probability_delta")),
        fmt_signed(row.get("mean_adjacent_winner_mass_delta")),
        fmt_signed(row.get("mean_effective_band_spread_delta")),
    ]


def _guardrail_row(row):
    return [
        row.get("market_id"),
        row.get("target_date"),
        row.get("component_name"),
        row.get("cutoff_regime"),
        row.get("status"),
        row.get("n"),
        fmt_signed(row.get("mean_winner_probability_delta")),
        fmt_signed(row.get("mean_adjacent_winner_mass_delta")),
        fmt_signed(row.get("mean_delta_brier")),
        fmt_signed(row.get("mean_delta_logloss")),
        row.get("reason") or "-",
    ]


def render_report(payload, *, top_n=12):
    lines = [
        "# Distribution Stage Attribution",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Snapshot folders: `{payload.get('folder_count', 0)}`",
        f"Settled folders with component rows: `{payload.get('settled_folder_count', 0)}`",
        f"Attribution rows: `{payload.get('attribution_row_count', 0)}`",
        "",
        (
            "Positive deltas mean the stage worsened score versus the previous "
            "available running stage for the same snapshot and market band."
        ),
        "",
    ]
    headers = [
        "Group",
        "Rows",
        "Delta Rows",
        "Brier",
        "Log Loss",
        "Delta Brier",
        "Delta Log Loss",
        "Winner P Delta",
        "Adjacent P Delta",
        "Spread Delta",
    ]
    overall = payload.get("overall") or {}
    if overall:
        lines += ["## Overall", ""]
        lines += markdown_table(headers, [_metric_row(overall)])
        lines.append("")
    negatives = payload.get("net_negative_stages") or []
    lines += ["## Net-Negative Stage Flags", ""]
    if negatives:
        lines += markdown_table(headers, [_metric_row(row) for row in negatives[:top_n]])
    else:
        lines.append("No net-negative stage met the minimum row threshold.")
    lines.append("")
    guardrails = payload.get("bottom_location_winner_mass_guardrails") or []
    guardrail_blockers = [row for row in guardrails if row.get("status") == "BLOCK"]
    lines += ["## Bottom-Location Winner-Mass Guardrails", ""]
    if guardrails:
        lines += markdown_table(
            [
                "Market",
                "Date",
                "Stage",
                "Cutoff Regime",
                "Status",
                "Rows",
                "Winner P Delta",
                "Adjacent P Delta",
                "Delta Brier",
                "Delta Log Loss",
                "Reason",
            ],
            [_guardrail_row(row) for row in (guardrail_blockers or guardrails)[:top_n]],
        )
    else:
        lines.append("No bottom-location final/postprocess winner-mass guardrail rows.")
    lines.append("")
    scope = payload.get("forecast_shape_scope") or {}
    lines += [
        "## Forecast Shape Scope",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", scope.get("status") or "-"],
            ["Current code", scope.get("current_identity_text") or "-"],
            ["Forecast-shape rows", scope.get("forecast_shape_stage_rows")],
            ["Feature-model forecast-shape rows", scope.get("feature_model_forecast_shape_rows")],
            ["Scored forecast-shape rows", scope.get("scored_forecast_shape_stage_rows")],
            [
                "Scored feature-model forecast-shape rows",
                scope.get("scored_feature_model_forecast_shape_rows"),
            ],
            [
                "Current-code feature-model component rows",
                scope.get("current_code_feature_model_component_rows"),
            ],
            [
                "Current-code feature-model forecast-shape rows",
                scope.get("current_code_feature_model_forecast_shape_rows"),
            ],
            [
                "Stale feature-model forecast-shape rows",
                scope.get("stale_feature_model_forecast_shape_rows"),
            ],
            ["Empirical forecast-shape rows", scope.get("empirical_forecast_shape_rows")],
            ["Feature-model regimes", ", ".join(scope.get("feature_model_regimes") or []) or "-"],
            ["Empirical regimes", ", ".join(scope.get("empirical_regimes") or []) or "-"],
            ["Feature-model delta Brier", fmt_signed(scope.get("feature_model_delta_brier"))],
            [
                "Current-code feature-model delta Brier",
                fmt_signed(scope.get("current_code_feature_model_delta_brier")),
            ],
            ["Empirical delta Brier", fmt_signed(scope.get("empirical_delta_brier"))],
            ["Empirical winner P delta", fmt_signed(scope.get("empirical_winner_probability_delta"))],
            ["Latest feature-model forecast-shape UTC", scope.get("latest_feature_model_forecast_shape_at_utc") or "-"],
            [
                "Latest stale feature-model forecast-shape UTC",
                scope.get("latest_stale_feature_model_forecast_shape_at_utc") or "-",
            ],
            [
                "Latest current-code feature-model forecast-shape UTC",
                scope.get("latest_current_code_feature_model_forecast_shape_at_utc") or "-",
            ],
            ["Reason", scope.get("reason") or "-"],
            ["Next unblock action", scope.get("next_unblock_action") or "-"],
        ],
    )
    lines.append("")
    for title, key in (
        ("By Component", "by_component"),
        ("By Cutoff Hour", "by_cutoff_hour"),
        ("By Regime", "by_regime"),
        ("By Market", "by_market"),
        ("By Market Stage", "by_market_stage"),
        ("By Market Stage Cutoff Regime", "by_market_stage_cutoff_regime"),
    ):
        rows = payload.get(key) or []
        lines += [f"## {title}", ""]
        if key in {"by_market_stage", "by_market_stage_cutoff_regime"}:
            rows = sorted(
                rows,
                key=lambda row: (
                    row.get("mean_winner_probability_delta") is None,
                    row.get("mean_winner_probability_delta")
                    if row.get("mean_winner_probability_delta") is not None
                    else math.inf,
                    -(row.get("delta_n", 0)),
                ),
            )
        else:
            rows = sorted(
                rows,
                key=lambda row: (
                    row.get("mean_delta_brier") if row.get("mean_delta_brier") is not None else -math.inf,
                    row.get("delta_n", 0),
                ),
                reverse=True,
            )
        lines += markdown_table(headers, [_metric_row(row) for row in rows[:top_n]])
        lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    write_json_atomic(json_out, payload)
    write_text_atomic(report_out, render_report(payload))
    return json_out, report_out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--min-stage-rows", type=int, default=20)
    args = parser.parse_args(argv)
    payload = build_payload(args.snapshots_root, min_stage_rows=args.min_stage_rows)
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Distribution stage attribution: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
