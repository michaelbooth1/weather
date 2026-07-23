"""Post-hoc robustness checks for a completed H1 ordinal-smoothing holdout.

This command never replays a model and never selects a weight.  It accepts only
the tune-selected holdout caches recorded by an already-complete H1 result,
streams their scoring rows with bounded buffering, and derives fixed source and
panel sensitivities from the pinned promotion-corpus manifest.  The original
all-pinned holdout remains the sole preregistered result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.research.current_replay_time_frontier import (
    MAX_CACHE_BYTES,
    ReaderStats,
    iter_cache_array,
    read_cache_metadata,
    sha256_stable_file,
)
from weather.reporting.research.ordinal_smoothing_sweep import paired_summary
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_robustness")
H1_SCHEMA_VERSION = schema_version("ordinal_smoothing_sweep")
MAX_H1_RESULT_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_SCORING_KEYS = 500_000
LOG_LOSS_EPSILON = 1e-15
SUMMARY_TOLERANCE = 1e-12
UNITS = ("C", "F")
SENSITIVITY_NAMES = (
    "daily_summary_only",
    "complete_12_market_dates",
    "daily_summary_complete_12_market_dates",
)


class RobustnessConfigurationError(ValueError):
    """Raised when immutable provenance or a fail-closed contract is violated."""


@dataclass(frozen=True)
class ManifestEntry:
    market_id: str
    target_date: str
    unit: str
    settlement_source: str


@dataclass(frozen=True)
class ScoreValue:
    market_id: str
    target_date: str
    unit: str
    replayed_p: float
    outcome: int
    market_yes: float

    @property
    def scoring_projection(self) -> tuple[Any, ...]:
        return (self.replayed_p, self.outcome, self.market_yes, self.unit)

    @property
    def alignment_projection(self) -> tuple[Any, ...]:
        return (self.outcome, self.market_yes, self.unit)


@dataclass
class MarketDateScores:
    market_id: str
    target_date: str
    unit: str
    settlement_source: str
    rows: int = 0
    baseline_brier_sum: float = 0.0
    candidate_brier_sum: float = 0.0
    baseline_logloss_sum: float = 0.0
    candidate_logloss_sum: float = 0.0
    market_brier_sum: float = 0.0
    market_logloss_sum: float = 0.0

    def add(self, baseline: ScoreValue, candidate: ScoreValue) -> None:
        self.rows += 1
        self.baseline_brier_sum += _brier(baseline.replayed_p, baseline.outcome)
        self.candidate_brier_sum += _brier(candidate.replayed_p, candidate.outcome)
        self.baseline_logloss_sum += _log_loss(
            baseline.replayed_p, baseline.outcome
        )
        self.candidate_logloss_sum += _log_loss(
            candidate.replayed_p, candidate.outcome
        )
        self.market_brier_sum += _brier(baseline.market_yes, baseline.outcome)
        self.market_logloss_sum += _log_loss(
            baseline.market_yes, baseline.outcome
        )


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _same_path(left: Path, right: Path) -> bool:
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            # Fall through to the normalized resolved-path comparison. Any
            # later open/stat failure still blocks before an output write.
            pass
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _read_json_bounded(path: Path, *, max_bytes: int) -> dict[str, Any]:
    before = path.stat()
    if before.st_size <= 0 or before.st_size > max_bytes:
        raise RobustnessConfigurationError(
            f"JSON size is outside the fail-closed bound: {path} ({before.st_size})"
        )
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise RobustnessConfigurationError(f"input changed while read: {path}")
    if not isinstance(payload, dict):
        raise RobustnessConfigurationError(f"JSON root must be an object: {path}")
    return payload


def _sha256_small_stable(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise RobustnessConfigurationError(f"input changed while hashed: {path}")
    return digest.hexdigest()


def validate_paths(
    *,
    h1_result: str | Path,
    corpus_manifest: str | Path,
    baseline_cache: str | Path,
    candidate_caches: Iterable[str | Path],
    json_out: str | Path,
    report_out: str | Path,
) -> dict[str, Any]:
    """Resolve read/write paths and keep all outputs outside repository data/."""

    candidates = tuple(_resolved(path) for path in candidate_caches)
    paths: dict[str, Any] = {
        "h1_result": _resolved(h1_result),
        "corpus_manifest": _resolved(corpus_manifest),
        "baseline_cache": _resolved(baseline_cache),
        "candidate_caches": candidates,
        "json_out": _resolved(json_out),
        "report_out": _resolved(report_out),
    }
    for key in ("h1_result", "corpus_manifest", "baseline_cache"):
        if not paths[key].is_file():
            raise RobustnessConfigurationError(f"input is not a file: {paths[key]}")
    if not candidates:
        raise RobustnessConfigurationError("at least one selected candidate cache is required")
    for path in candidates:
        if not path.is_file():
            raise RobustnessConfigurationError(f"candidate cache is not a file: {path}")
        if path.stat().st_size > MAX_CACHE_BYTES:
            raise RobustnessConfigurationError(f"cache exceeds safety bound: {path}")
    for index, path in enumerate(candidates):
        if any(_same_path(path, prior) for prior in candidates[:index]):
            raise RobustnessConfigurationError("candidate cache paths must be unique")

    json_path = paths["json_out"]
    report_path = paths["report_out"]
    if _same_path(json_path, report_path):
        raise RobustnessConfigurationError("JSON and report outputs must be distinct")
    input_files = (
        paths["h1_result"],
        paths["corpus_manifest"],
        paths["baseline_cache"],
        *candidates,
    )
    for output in (json_path, report_path):
        if any(_same_path(output, input_path) for input_path in input_files):
            raise RobustnessConfigurationError(f"output aliases an immutable input: {output}")
        if output.exists() and output.is_dir():
            raise RobustnessConfigurationError(f"output must be a file path: {output}")

    # The pinned corpus lives at data/backtest/promotion_corpus.json.  Inferring
    # data/ from that fixed topology prevents this post-hoc command from writing
    # into operational evidence without requiring a mutable environment setting.
    if paths["corpus_manifest"].parent.name.lower() != "backtest":
        raise RobustnessConfigurationError(
            "corpus manifest must have the pinned data/backtest topology"
        )
    data_root = paths["corpus_manifest"].parent.parent
    for output in (json_path, report_path):
        if _is_within(output, data_root):
            raise RobustnessConfigurationError(
                f"post-hoc output must be outside input data root {data_root}: {output}"
            )
    paths["data_root"] = data_root
    return paths


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    fields = (
        "market_id",
        "target_date",
        "snapshot_id",
        "captured_at_local",
        "band",
        "bin_type",
        "bin_value_c",
        "bin_value_hi",
    )
    # Canonical JSON makes independently decoded NaN/None values stable and
    # keeps the key contract identical across separately streamed cache files.
    return tuple(_canonical_json(row.get(field)) for field in fields)


def _probability(row: Mapping[str, Any], field: str) -> float:
    try:
        value = float(row.get(field))
    except (TypeError, ValueError) as exc:
        raise RobustnessConfigurationError(f"invalid {field} in scoring row") from exc
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise RobustnessConfigurationError(f"invalid {field} probability: {value!r}")
    return value


def _score_value(row: Mapping[str, Any]) -> ScoreValue:
    market_id = str(row.get("market_id") or "")
    target_date = str(row.get("target_date") or "")
    unit = str(row.get("unit") or "").upper()
    if not market_id or not target_date:
        raise RobustnessConfigurationError("scoring row lacks market_id or target_date")
    if unit not in UNITS:
        raise RobustnessConfigurationError(f"scoring row has unsupported unit: {unit!r}")
    try:
        outcome_number = float(row.get("outcome"))
    except (TypeError, ValueError) as exc:
        raise RobustnessConfigurationError("invalid scoring outcome") from exc
    if outcome_number not in (0.0, 1.0):
        raise RobustnessConfigurationError(f"scoring outcome is not binary: {outcome_number!r}")
    return ScoreValue(
        market_id=market_id,
        target_date=target_date,
        unit=unit,
        replayed_p=_probability(row, "replayed_p"),
        outcome=int(outcome_number),
        market_yes=_probability(row, "market_yes"),
    )


def _brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def _log_loss(probability: float, outcome: int) -> float:
    probability = max(
        LOG_LOSS_EPSILON, min(1.0 - LOG_LOSS_EPSILON, float(probability))
    )
    return -(
        int(outcome) * math.log(probability)
        + (1 - int(outcome)) * math.log(1.0 - probability)
    )


def expected_market_units() -> dict[str, str]:
    """Return the canonical built-in 12-market fleet and native units."""

    from weather.market.market_registry import BUILTIN_SPECS

    market_units = {str(spec.id): str(spec.display_unit).upper() for spec in BUILTIN_SPECS}
    if len(market_units) != 12:
        raise RobustnessConfigurationError(
            f"the requested robustness contract requires 12 built-in markets; got {len(market_units)}"
        )
    if set(market_units.values()) - set(UNITS):
        raise RobustnessConfigurationError("built-in fleet has an unsupported settlement unit")
    return market_units


def build_manifest_index(
    manifest: Mapping[str, Any],
    holdout_dates: Iterable[str],
    market_units: Mapping[str, str],
) -> tuple[dict[tuple[str, str], ManifestEntry], dict[str, Any]]:
    """Join source labels by market/date and predeclare exact panel sets."""

    dates = tuple(str(value) for value in holdout_dates)
    date_set = set(dates)
    if not dates or len(dates) != len(date_set):
        raise RobustnessConfigurationError("holdout dates must be nonempty and unique")
    index: dict[tuple[str, str], ManifestEntry] = {}
    by_date: dict[str, set[str]] = {target_date: set() for target_date in dates}
    source_counts: Counter[str] = Counter()
    for raw in manifest.get("entries") or []:
        target_date = str(raw.get("target_date") or "")
        if target_date not in date_set:
            continue
        market_id = str(raw.get("market_id") or "")
        if market_id not in market_units:
            raise RobustnessConfigurationError(
                f"holdout manifest contains a noncanonical market: {market_id!r}"
            )
        key = (market_id, target_date)
        if key in index:
            raise RobustnessConfigurationError(
                f"holdout manifest repeats market/date entry: {key!r}"
            )
        unit = str(raw.get("settlement_unit") or "").upper()
        if unit != market_units[market_id]:
            raise RobustnessConfigurationError(
                f"manifest unit disagrees with canonical market unit for {key!r}: {unit!r}"
            )
        source = str(raw.get("settlement_source") or "")
        if not source:
            raise RobustnessConfigurationError(
                f"manifest lacks settlement_source for {key!r}"
            )
        index[key] = ManifestEntry(market_id, target_date, unit, source)
        by_date[target_date].add(market_id)
        source_counts[source] += 1

    if not index:
        raise RobustnessConfigurationError("manifest has no entries on holdout dates")
    expected = set(market_units)
    manifest_complete_dates = sorted(
        target_date for target_date, markets in by_date.items() if markets == expected
    )
    manifest_daily_complete_dates = sorted(
        target_date
        for target_date in manifest_complete_dates
        if all(
            index[(market_id, target_date)].settlement_source == "daily_summary"
            for market_id in expected
        )
    )
    return index, {
        "holdout_dates": list(dates),
        "expected_market_count": len(expected),
        "expected_markets": sorted(expected),
        "manifest_market_dates": len(index),
        "manifest_markets_by_date": {
            target_date: sorted(markets) for target_date, markets in sorted(by_date.items())
        },
        "manifest_settlement_sources": dict(sorted(source_counts.items())),
        "manifest_complete_12_market_dates": manifest_complete_dates,
        "manifest_daily_summary_complete_12_market_dates": manifest_daily_complete_dates,
    }


def stream_baseline_rows(
    cache_path: Path,
    manifest_index: Mapping[tuple[str, str], ManifestEntry],
) -> tuple[dict[tuple[str, ...], ScoreValue], dict[str, Any], ReaderStats, list[str]]:
    """Read the immutable weight-zero scoring array once into a bounded key index."""

    stats = ReaderStats("rows", 256 * 1024, 4 * 1024 * 1024)
    rows: dict[tuple[str, ...], ScoreValue] = {}
    duplicates = 0
    conflicts = 0
    conflict_examples: list[str] = []
    blockers: list[str] = []
    market_dates: set[tuple[str, str]] = set()
    for raw in iter_cache_array(cache_path, "rows", stats=stats):
        value = _score_value(raw)
        pair = (value.market_id, value.target_date)
        entry = manifest_index.get(pair)
        if entry is None:
            raise RobustnessConfigurationError(
                f"baseline scoring row is absent from pinned holdout manifest: {pair!r}"
            )
        if entry.unit != value.unit:
            raise RobustnessConfigurationError(
                f"baseline scoring row unit disagrees with manifest: {pair!r}"
            )
        key = _row_key(raw)
        prior = rows.get(key)
        if prior is not None:
            duplicates += 1
            if prior.scoring_projection != value.scoring_projection:
                conflicts += 1
                if len(conflict_examples) < 10:
                    conflict_examples.append(repr(key))
            continue
        if len(rows) >= MAX_SCORING_KEYS:
            raise RobustnessConfigurationError(
                f"baseline scoring-key cap exceeded: {MAX_SCORING_KEYS}"
            )
        rows[key] = value
        market_dates.add(pair)
    if conflicts:
        blockers.append(
            f"baseline has {conflicts} conflicting duplicate H1 scoring keys"
        )
    if not rows:
        blockers.append("baseline cache has no scoring rows")
    evidence = {
        "raw_rows": stats.items_yielded,
        "unique_scoring_rows": len(rows),
        "duplicate_extras": duplicates,
        "conflicting_duplicates": conflicts,
        "conflict_examples": conflict_examples,
        "market_dates": len(market_dates),
        "target_dates": sorted({value.target_date for value in rows.values()}),
    }
    return rows, evidence, stats, blockers


def stream_candidate_rows(
    cache_path: Path,
    *,
    baseline_rows: Mapping[tuple[str, ...], ScoreValue],
    manifest_index: Mapping[tuple[str, str], ManifestEntry],
    selected_units: set[str],
    accumulators: dict[tuple[str, str], MarketDateScores],
) -> tuple[dict[str, Any], ReaderStats, list[str]]:
    """Align one selected-weight cache and aggregate only units selecting it."""

    stats = ReaderStats("rows", 256 * 1024, 4 * 1024 * 1024)
    seen: dict[tuple[str, ...], ScoreValue] = {}
    duplicates = 0
    conflicts = 0
    label_mismatches = 0
    extra = 0
    extra_examples: list[str] = []
    conflict_examples: list[str] = []
    label_examples: list[str] = []
    matched = 0
    for raw in iter_cache_array(cache_path, "rows", stats=stats):
        value = _score_value(raw)
        pair = (value.market_id, value.target_date)
        entry = manifest_index.get(pair)
        if entry is None:
            raise RobustnessConfigurationError(
                f"candidate scoring row is absent from pinned holdout manifest: {pair!r}"
            )
        if entry.unit != value.unit:
            raise RobustnessConfigurationError(
                f"candidate scoring row unit disagrees with manifest: {pair!r}"
            )
        key = _row_key(raw)
        prior = seen.get(key)
        if prior is not None:
            duplicates += 1
            if prior.scoring_projection != value.scoring_projection:
                conflicts += 1
                if len(conflict_examples) < 10:
                    conflict_examples.append(repr(key))
            continue
        if len(seen) >= MAX_SCORING_KEYS:
            raise RobustnessConfigurationError(
                f"candidate scoring-key cap exceeded: {MAX_SCORING_KEYS}"
            )
        seen[key] = value
        baseline = baseline_rows.get(key)
        if baseline is None:
            extra += 1
            if len(extra_examples) < 10:
                extra_examples.append(repr(key))
            continue
        matched += 1
        if baseline.alignment_projection != value.alignment_projection:
            label_mismatches += 1
            if len(label_examples) < 10:
                label_examples.append(repr(key))
            continue
        if value.unit not in selected_units:
            continue
        accumulator = accumulators.get(pair)
        if accumulator is None:
            accumulator = MarketDateScores(
                market_id=value.market_id,
                target_date=value.target_date,
                unit=value.unit,
                settlement_source=entry.settlement_source,
            )
            accumulators[pair] = accumulator
        accumulator.add(baseline, value)

    missing_keys = set(baseline_rows) - set(seen)
    blockers: list[str] = []
    if conflicts:
        blockers.append(
            f"candidate has {conflicts} conflicting duplicate H1 scoring keys"
        )
    if missing_keys:
        blockers.append(f"candidate is missing {len(missing_keys)} baseline scoring rows")
    if extra:
        blockers.append(f"candidate has {extra} extra scoring rows")
    if label_mismatches:
        blockers.append(
            f"candidate changed {label_mismatches} outcome/market/unit labels"
        )
    evidence = {
        "status": "PASS" if not blockers else "BLOCK",
        "raw_rows": stats.items_yielded,
        "unique_scoring_rows": len(seen),
        "matched_scoring_rows": matched,
        "duplicate_extras": duplicates,
        "conflicting_duplicates": conflicts,
        "missing": len(missing_keys),
        "extra": extra,
        "label_mismatches": label_mismatches,
        "conflict_examples": conflict_examples,
        "missing_examples": [repr(key) for key in list(missing_keys)[:10]],
        "extra_examples": extra_examples,
        "label_mismatch_examples": label_examples,
        "blockers": blockers,
    }
    return evidence, stats, blockers


def _combine_daily(
    market_dates: Iterable[MarketDateScores],
    *,
    unit: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[MarketDateScores]] = defaultdict(list)
    for row in market_dates:
        if row.unit == unit:
            grouped[row.target_date].append(row)
    output: list[dict[str, Any]] = []
    for target_date, rows in sorted(grouped.items()):
        n = sum(row.rows for row in rows)
        if not n:
            continue
        baseline_brier = sum(row.baseline_brier_sum for row in rows) / n
        candidate_brier = sum(row.candidate_brier_sum for row in rows) / n
        baseline_logloss = sum(row.baseline_logloss_sum for row in rows) / n
        candidate_logloss = sum(row.candidate_logloss_sum for row in rows) / n
        market_brier = sum(row.market_brier_sum for row in rows) / n
        market_logloss = sum(row.market_logloss_sum for row in rows) / n
        output.append(
            {
                "target_date": target_date,
                "rows": n,
                "markets": len({row.market_id for row in rows}),
                "baseline_brier": baseline_brier,
                "candidate_brier": candidate_brier,
                "brier_delta": candidate_brier - baseline_brier,
                "baseline_logloss": baseline_logloss,
                "candidate_logloss": candidate_logloss,
                "logloss_delta": candidate_logloss - baseline_logloss,
                "market_brier": market_brier,
                "market_logloss": market_logloss,
                "candidate_brier_delta_vs_market": candidate_brier - market_brier,
                "candidate_logloss_delta_vs_market": candidate_logloss - market_logloss,
            }
        )
    return output


def _diagnostic_disposition(summary: Mapping[str, Any]) -> str:
    if not summary.get("fleet_dates"):
        return "NO_ROWS"
    brier_ci = summary.get("brier_cluster_bootstrap_95ci") or {}
    logloss_ci = summary.get("logloss_cluster_bootstrap_95ci") or {}
    if (brier_ci.get("high") is not None and brier_ci["high"] < 0.0) and (
        logloss_ci.get("high") is not None and logloss_ci["high"] < 0.0
    ):
        return "SUPPORTED"
    if summary.get("mean_brier_delta", 0.0) < 0.0 and summary.get(
        "mean_logloss_delta", 0.0
    ) < 0.0:
        return "DIRECTIONAL_ONLY"
    return "NOT_SUPPORTED"


def build_sensitivity_summaries(
    accumulators: Mapping[tuple[str, str], MarketDateScores],
    *,
    selected_weights: Mapping[str, float],
    expected_markets: Iterable[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build primary parity plus three fixed, post-hoc holdout sensitivities."""

    expected = set(expected_markets)
    by_date: dict[str, set[str]] = defaultdict(set)
    for (market_id, target_date), scores in accumulators.items():
        if scores.rows:
            by_date[target_date].add(market_id)
    complete_dates = sorted(
        target_date for target_date, markets in by_date.items() if markets == expected
    )
    daily_complete_dates = sorted(
        target_date
        for target_date in complete_dates
        if all(
            accumulators[(market_id, target_date)].settlement_source == "daily_summary"
            for market_id in expected
        )
    )

    filters = {
        "all_pinned_recomputed": lambda row: True,
        "daily_summary_only": lambda row: row.settlement_source == "daily_summary",
        "complete_12_market_dates": lambda row: row.target_date in set(complete_dates),
        "daily_summary_complete_12_market_dates": lambda row: row.target_date
        in set(daily_complete_dates),
    }
    summaries: dict[str, Any] = {}
    values = list(accumulators.values())
    for name, predicate in filters.items():
        subset = [row for row in values if predicate(row)]
        units: dict[str, Any] = {}
        for unit in UNITS:
            weight = float(selected_weights.get(unit, 0.0))
            if weight <= 0.0:
                units[unit] = {
                    "status": "NO_TUNE_CANDIDATE",
                    "summary": None,
                }
                continue
            daily = _combine_daily(subset, unit=unit)
            split = "holdout" if name == "all_pinned_recomputed" else f"holdout_posthoc_{name}"
            summary = paired_summary(daily, split=split, unit=unit, weight=weight)
            units[unit] = {
                "status": _diagnostic_disposition(summary),
                "summary": summary,
            }
        summaries[name] = {
            "post_hoc": name != "all_pinned_recomputed",
            "selection_effect": "NONE",
            "units": units,
        }
    panel_evidence = {
        "observed_markets_by_date": {
            target_date: sorted(markets) for target_date, markets in sorted(by_date.items())
        },
        "observed_complete_12_market_dates": complete_dates,
        "observed_daily_summary_complete_12_market_dates": daily_complete_dates,
    }
    return summaries, panel_evidence


def _mean(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values]
    return sum(values) / len(values) if values else None


def build_additional_diagnostics(
    accumulators: Mapping[tuple[str, str], MarketDateScores],
    *,
    selected_weights: Mapping[str, float],
) -> dict[str, Any]:
    """Describe market heterogeneity, source complement, and date influence.

    These diagnostics are intentionally downstream of the fixed H1 selection.
    They are not additional selection gates and do not amend the primary result.
    """

    values = list(accumulators.values())
    per_market: dict[str, Any] = {}
    for market_id in sorted({row.market_id for row in values}):
        market_rows = [row for row in values if row.market_id == market_id]
        unit = market_rows[0].unit
        weight = float(selected_weights.get(unit, 0.0))
        daily = _combine_daily(market_rows, unit=unit)
        summary = paired_summary(
            daily,
            split=f"holdout_posthoc_market_{market_id}",
            unit=unit,
            weight=weight,
        )
        per_market[market_id] = {
            "post_hoc": True,
            "selection_effect": "NONE",
            "unit": unit,
            "status": _diagnostic_disposition(summary),
            "summary": summary,
        }

    snapshot_rows = [
        row for row in values if row.settlement_source == "snapshot_high"
    ]
    snapshot_units: dict[str, Any] = {}
    for unit in UNITS:
        weight = float(selected_weights.get(unit, 0.0))
        daily = _combine_daily(snapshot_rows, unit=unit)
        summary = paired_summary(
            daily,
            split="holdout_posthoc_snapshot_high_only",
            unit=unit,
            weight=weight,
        )
        snapshot_units[unit] = {
            "status": _diagnostic_disposition(summary),
            "summary": summary,
        }

    leave_one_date_out: dict[str, Any] = {}
    for unit in UNITS:
        weight = float(selected_weights.get(unit, 0.0))
        daily = _combine_daily(values, unit=unit)
        exclusions = []
        for omitted in daily:
            retained = [
                row
                for row in daily
                if row["target_date"] != omitted["target_date"]
            ]
            exclusions.append(
                {
                    "omitted_date": omitted["target_date"],
                    "fleet_dates": len(retained),
                    "mean_brier_delta": _mean(
                        row["brier_delta"] for row in retained
                    ),
                    "mean_logloss_delta": _mean(
                        row["logloss_delta"] for row in retained
                    ),
                    "mean_candidate_brier_delta_vs_market": _mean(
                        row["candidate_brier_delta_vs_market"] for row in retained
                    ),
                    "mean_candidate_logloss_delta_vs_market": _mean(
                        row["candidate_logloss_delta_vs_market"] for row in retained
                    ),
                }
            )
        brier_values = [
            row["mean_brier_delta"]
            for row in exclusions
            if row["mean_brier_delta"] is not None
        ]
        logloss_values = [
            row["mean_logloss_delta"]
            for row in exclusions
            if row["mean_logloss_delta"] is not None
        ]
        negative_both = sum(
            row["mean_brier_delta"] is not None
            and row["mean_brier_delta"] < 0.0
            and row["mean_logloss_delta"] is not None
            and row["mean_logloss_delta"] < 0.0
            for row in exclusions
        )
        leave_one_date_out[unit] = {
            "post_hoc": True,
            "selection_effect": "NONE",
            "weight": weight,
            "exclusions": len(exclusions),
            "negative_both_after_exclusion": negative_both,
            "all_exclusions_negative_both": bool(exclusions)
            and negative_both == len(exclusions),
            "mean_brier_delta_range": {
                "minimum": min(brier_values) if brier_values else None,
                "maximum": max(brier_values) if brier_values else None,
            },
            "mean_logloss_delta_range": {
                "minimum": min(logloss_values) if logloss_values else None,
                "maximum": max(logloss_values) if logloss_values else None,
            },
            "most_adverse_brier_omission": (
                max(
                    exclusions,
                    key=lambda row: row["mean_brier_delta"],
                )["omitted_date"]
                if brier_values
                else None
            ),
            "most_adverse_logloss_omission": (
                max(
                    exclusions,
                    key=lambda row: row["mean_logloss_delta"],
                )["omitted_date"]
                if logloss_values
                else None
            ),
            "rows": exclusions,
        }
    return {
        "post_hoc": True,
        "selection_effect": "NONE",
        "per_market": per_market,
        "snapshot_high_only": {
            "post_hoc": True,
            "selection_effect": "NONE",
            "interpretation": (
                "descriptive complement to daily_summary_only; small date counts "
                "must not be interpreted as confirmatory"
            ),
            "units": snapshot_units,
        },
        "leave_one_fleet_date_out": leave_one_date_out,
    }


def _numeric_difference(left: Any, right: Any) -> float | None:
    if left is None and right is None:
        return 0.0
    if left is None or right is None:
        return None
    try:
        return abs(float(left) - float(right))
    except (TypeError, ValueError):
        return 0.0 if left == right else None


def compare_primary_summary(
    primary: Mapping[str, Any], recomputed: Mapping[str, Any]
) -> dict[str, Any]:
    """Require the streamed all-pinned recomputation to match the H1 result."""

    blockers: list[str] = []
    differences: list[float] = []
    for field in (
        "split",
        "unit",
        "weight",
        "fleet_dates",
        "scoring_rows",
        "mean_brier_delta",
        "mean_logloss_delta",
        "mean_candidate_brier_delta_vs_market",
        "mean_candidate_logloss_delta_vs_market",
    ):
        difference = _numeric_difference(primary.get(field), recomputed.get(field))
        if difference is None or difference > SUMMARY_TOLERANCE:
            blockers.append(
                f"all-pinned primary mismatch in {field}: {primary.get(field)!r} != {recomputed.get(field)!r}"
            )
        elif difference is not None:
            differences.append(difference)
    for metric in ("brier", "logloss"):
        field = f"{metric}_cluster_bootstrap_95ci"
        for bound in ("low", "high", "replicates", "seed"):
            difference = _numeric_difference(
                (primary.get(field) or {}).get(bound),
                (recomputed.get(field) or {}).get(bound),
            )
            if difference is None or difference > SUMMARY_TOLERANCE:
                blockers.append(
                    f"all-pinned primary mismatch in {field}.{bound}"
                )
            elif difference is not None:
                differences.append(difference)
        sign_field = f"{metric}_sign_test"
        for value_field in (
            "improvements",
            "regressions",
            "ties",
            "non_ties",
            "two_sided_p",
        ):
            difference = _numeric_difference(
                (primary.get(sign_field) or {}).get(value_field),
                (recomputed.get(sign_field) or {}).get(value_field),
            )
            if difference is None or difference > SUMMARY_TOLERANCE:
                blockers.append(
                    f"all-pinned primary mismatch in {sign_field}.{value_field}"
                )
            elif difference is not None:
                differences.append(difference)
    primary_daily = {
        str(row.get("target_date")): row for row in primary.get("daily") or []
    }
    recomputed_daily = {
        str(row.get("target_date")): row for row in recomputed.get("daily") or []
    }
    if set(primary_daily) != set(recomputed_daily):
        blockers.append("all-pinned primary and recomputed fleet-date keys differ")
    for target_date in set(primary_daily) & set(recomputed_daily):
        for field in (
            "rows",
            "markets",
            "baseline_brier",
            "candidate_brier",
            "brier_delta",
            "baseline_logloss",
            "candidate_logloss",
            "logloss_delta",
            "market_brier",
            "market_logloss",
            "candidate_brier_delta_vs_market",
            "candidate_logloss_delta_vs_market",
        ):
            difference = _numeric_difference(
                primary_daily[target_date].get(field),
                recomputed_daily[target_date].get(field),
            )
            if difference is None or difference > SUMMARY_TOLERANCE:
                blockers.append(
                    f"all-pinned daily mismatch on {target_date} in {field}"
                )
            elif difference is not None:
                differences.append(difference)
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "tolerance": SUMMARY_TOLERANCE,
        "maximum_absolute_difference": max(differences) if differences else 0.0,
        "blockers": blockers,
    }


def _validate_h1_result(
    h1: Mapping[str, Any],
    *,
    h1_path: Path,
    corpus_path: Path,
    baseline_cache: Path,
    candidate_metadata: Mapping[float, Any],
) -> tuple[dict[str, float], list[str]]:
    blockers: list[str] = []
    if h1.get("schema_version") != H1_SCHEMA_VERSION:
        raise RobustnessConfigurationError(
            f"unexpected H1 result schema: {h1.get('schema_version')!r}"
        )
    if h1.get("status") != "COMPLETE":
        raise RobustnessConfigurationError("H1 result must be COMPLETE before post-hoc analysis")
    if (h1.get("tune") or {}).get("status") != "PASS":
        raise RobustnessConfigurationError("H1 tune gates did not pass")
    if (h1.get("holdout") or {}).get("status") != "PASS":
        raise RobustnessConfigurationError("H1 holdout gates did not pass")
    if (h1.get("experiment") or {}).get("selection_uses_holdout") is not False:
        raise RobustnessConfigurationError("H1 result does not prove tune-only selection")
    if h1.get("promotion_authorized") is not False:
        raise RobustnessConfigurationError("H1 result unexpectedly authorizes promotion")
    lock_raw = str((h1.get("outputs") or {}).get("lock_path") or "")
    if not lock_raw:
        raise RobustnessConfigurationError("H1 result lacks its research lock path")
    lock_path = _resolved(lock_raw)
    if lock_path.exists():
        raise RobustnessConfigurationError(
            f"H1 research lock still exists; result is not immutable: {lock_path}"
        )
    recorded_corpus = str((h1.get("inputs") or {}).get("corpus_path") or "")
    if not recorded_corpus or not _same_path(_resolved(recorded_corpus), corpus_path):
        raise RobustnessConfigurationError("H1 result corpus path differs from requested manifest")
    selected_raw = (h1.get("tune") or {}).get("selected_weights") or {}
    selected = {unit: float(selected_raw.get(unit, 0.0)) for unit in UNITS}
    positive = {weight for weight in selected.values() if weight > 0.0}
    if positive != set(candidate_metadata):
        raise RobustnessConfigurationError(
            "candidate caches must equal the distinct positive tune-selected weights: "
            f"selected={sorted(positive)}, caches={sorted(candidate_metadata)}"
        )
    recorded_caches = {
        os.path.normcase(str(_resolved(path)))
        for path in (h1.get("outputs") or {}).get("cache_files") or []
    }
    required = {
        os.path.normcase(str(baseline_cache)),
        *(os.path.normcase(str(meta.path)) for meta in candidate_metadata.values()),
    }
    if not required <= recorded_caches:
        raise RobustnessConfigurationError(
            "selected holdout cache paths are not all bound into the H1 result"
        )
    if not _same_path(
        h1_path,
        _resolved((h1.get("outputs") or {}).get("json_out") or h1_path),
    ):
        blockers.append("H1 result path differs from its recorded json_out path")
    return selected, blockers


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    paths = validate_paths(
        h1_result=args.h1_result,
        corpus_manifest=args.corpus_manifest,
        baseline_cache=args.baseline_cache,
        candidate_caches=args.candidate_cache,
        json_out=args.json_out,
        report_out=args.report_out,
    )
    h1 = _read_json_bounded(paths["h1_result"], max_bytes=MAX_H1_RESULT_BYTES)
    manifest = _read_json_bounded(
        paths["corpus_manifest"], max_bytes=MAX_MANIFEST_BYTES
    )
    h1_hash = _sha256_small_stable(paths["h1_result"])
    manifest_hash = _sha256_small_stable(paths["corpus_manifest"])
    if (h1.get("inputs") or {}).get("corpus_hash") != manifest.get("corpus_hash"):
        raise RobustnessConfigurationError("H1 and manifest corpus hashes differ")

    baseline_meta = read_cache_metadata(paths["baseline_cache"])
    if baseline_meta.split != "holdout" or baseline_meta.weight != 0.0:
        raise RobustnessConfigurationError(
            "baseline cache must be the frozen holdout weight-zero arm"
        )
    candidate_meta: dict[float, Any] = {}
    for cache_path in paths["candidate_caches"]:
        metadata = read_cache_metadata(cache_path)
        if metadata.split != "holdout" or metadata.weight <= 0.0:
            raise RobustnessConfigurationError(
                f"candidate cache is not a positive-weight holdout arm: {cache_path}"
            )
        if metadata.weight in candidate_meta:
            raise RobustnessConfigurationError(
                f"multiple candidate caches declare weight {metadata.weight}"
            )
        candidate_meta[metadata.weight] = metadata

    selected_weights, blockers = _validate_h1_result(
        h1,
        h1_path=paths["h1_result"],
        corpus_path=paths["corpus_manifest"],
        baseline_cache=paths["baseline_cache"],
        candidate_metadata=candidate_meta,
    )
    market_units = expected_market_units()
    holdout_dates = tuple(str(value) for value in (h1.get("split") or {}).get("holdout_dates") or [])
    manifest_index, manifest_panel = build_manifest_index(
        manifest, holdout_dates, market_units
    )

    baseline_rows, baseline_evidence, baseline_stats, baseline_blockers = stream_baseline_rows(
        paths["baseline_cache"], manifest_index
    )
    blockers.extend(baseline_blockers)
    if set(baseline_evidence["target_dates"]) != set(holdout_dates):
        blockers.append("baseline scoring dates differ from the predeclared holdout dates")

    accumulators: dict[tuple[str, str], MarketDateScores] = {}
    candidate_evidence: dict[str, Any] = {}
    candidate_reader_stats: dict[str, Any] = {}
    for weight, metadata in sorted(candidate_meta.items()):
        units = {unit for unit, selected in selected_weights.items() if selected == weight}
        evidence, stats, arm_blockers = stream_candidate_rows(
            metadata.path,
            baseline_rows=baseline_rows,
            manifest_index=manifest_index,
            selected_units=units,
            accumulators=accumulators,
        )
        candidate_evidence[str(weight)] = evidence
        candidate_reader_stats[str(weight)] = stats.as_dict()
        blockers.extend(f"weight {weight}: {reason}" for reason in arm_blockers)

    expected_selected_pairs = {
        pair
        for pair, entry in manifest_index.items()
        if selected_weights.get(entry.unit, 0.0) > 0.0
    }
    missing_market_dates = sorted(expected_selected_pairs - set(accumulators))
    if missing_market_dates:
        blockers.append(
            f"{len(missing_market_dates)} selected manifest market-dates have no paired scoring rows"
        )
    summaries, observed_panel = build_sensitivity_summaries(
        accumulators,
        selected_weights=selected_weights,
        expected_markets=market_units,
    )
    additional_diagnostics = build_additional_diagnostics(
        accumulators,
        selected_weights=selected_weights,
    )
    if (
        manifest_panel["manifest_complete_12_market_dates"]
        != observed_panel["observed_complete_12_market_dates"]
    ):
        blockers.append("manifest and paired-row 12-market-complete dates differ")
    if (
        manifest_panel["manifest_daily_summary_complete_12_market_dates"]
        != observed_panel["observed_daily_summary_complete_12_market_dates"]
    ):
        blockers.append(
            "manifest and paired-row daily-summary complete-panel dates differ"
        )

    primary_validation: dict[str, Any] = {}
    primary_paired = (h1.get("holdout") or {}).get("paired") or {}
    for unit in UNITS:
        recomputed = (
            (summaries["all_pinned_recomputed"]["units"].get(unit) or {}).get("summary")
            or {}
        )
        primary = primary_paired.get(unit) or {}
        if selected_weights.get(unit, 0.0) <= 0.0:
            primary_validation[unit] = {"status": "NOT_APPLICABLE", "blockers": []}
            continue
        validation = compare_primary_summary(primary, recomputed)
        primary_validation[unit] = validation
        blockers.extend(f"{unit} primary parity: {reason}" for reason in validation["blockers"])

    # Hash after every streaming pass and bind the exact stat observed by the
    # metadata reader.  Any concurrent cache mutation fails closed.
    baseline_hash = sha256_stable_file(
        baseline_meta.path,
        expected_size_bytes=baseline_meta.size_bytes,
        expected_mtime_ns=baseline_meta.mtime_ns,
    )
    candidate_inputs: dict[str, Any] = {}
    for weight, metadata in sorted(candidate_meta.items()):
        candidate_inputs[str(weight)] = {
            **metadata.as_dict(),
            "sha256": sha256_stable_file(
                metadata.path,
                expected_size_bytes=metadata.size_bytes,
                expected_mtime_ns=metadata.mtime_ns,
            ),
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE" if not blockers else "BLOCK",
        "research_only": True,
        "promotion_authorized": False,
        "technical_blockers": blockers,
        "design": {
            "primary_result": "the preregistered all-pinned H1 holdout in h1_result",
            "post_hoc": True,
            "selection_uses_post_hoc_results": False,
            "selection_uses_holdout": False,
            "selected_weights_copied_from_h1_tune": selected_weights,
            "sensitivity_names": list(SENSITIVITY_NAMES),
            "scoring": (
                "H1 band/snapshot rows pooled within native-unit fleet date; "
                "fleet dates equally weighted for point estimates and cluster bootstrap"
            ),
            "settlement_source_join": "pinned manifest by (market_id,target_date)",
            "complete_panel_contract": "exactly the canonical 12 built-in markets",
        },
        "inputs": {
            "opened_read_only": True,
            "h1_result": {
                "path": str(paths["h1_result"]),
                "size_bytes": paths["h1_result"].stat().st_size,
                "sha256": h1_hash,
                "schema_version": h1.get("schema_version"),
                "status": h1.get("status"),
            },
            "corpus_manifest": {
                "path": str(paths["corpus_manifest"]),
                "size_bytes": paths["corpus_manifest"].stat().st_size,
                "sha256": manifest_hash,
                "corpus_hash": manifest.get("corpus_hash"),
            },
            "baseline_cache": {
                **baseline_meta.as_dict(),
                "sha256": baseline_hash,
            },
            "candidate_caches": candidate_inputs,
        },
        "outputs": {
            "json_out": str(paths["json_out"]),
            "report_out": str(paths["report_out"]),
            "outside_input_data_root": True,
        },
        "primary_reference": {
            "h1_status": h1.get("status"),
            "h1_holdout_status": (h1.get("holdout") or {}).get("status"),
            "h1_dispositions": (h1.get("holdout") or {}).get("dispositions") or {},
            "h1_paired": primary_paired,
            "all_pinned_recomputed": summaries["all_pinned_recomputed"],
            "parity": primary_validation,
        },
        "panel_evidence": {
            **manifest_panel,
            **observed_panel,
            "missing_selected_manifest_market_dates": [
                list(pair) for pair in missing_market_dates
            ],
        },
        "sensitivities": {
            name: summaries[name] for name in SENSITIVITY_NAMES
        },
        "additional_diagnostics": additional_diagnostics,
        "alignment": {
            "duplicate_contract": (
                "keep first only when replayed_p/outcome/market_yes/unit are "
                "NaN-safe canonically identical; conflicting duplicate blocks"
            ),
            "baseline": baseline_evidence,
            "candidates": candidate_evidence,
        },
        "bounded_reader": {
            "baseline": baseline_stats.as_dict(),
            "candidates": candidate_reader_stats,
            "maximum_scoring_keys": MAX_SCORING_KEYS,
        },
        "safety": {
            "model_replay_performed": False,
            "weight_selection_performed": False,
            "serving_pointer_changed": False,
            "artifact_promoted": False,
            "live_trading": False,
            "input_data_written": False,
        },
    }
    return payload


def _summary_table_rows(payload: Mapping[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    primary = payload.get("primary_reference") or {}
    sources = [("primary: preregistered all-pinned", primary.get("h1_paired") or {})]
    recomputed_units = (
        (primary.get("all_pinned_recomputed") or {}).get("units") or {}
    )
    sources.append(
        (
            "check: all-pinned recomputed",
            {
                unit: (recomputed_units.get(unit) or {}).get("summary")
                for unit in UNITS
            },
        )
    )
    for name, section in (payload.get("sensitivities") or {}).items():
        sources.append(
            (
                f"post-hoc: {name}",
                {
                    unit: ((section.get("units") or {}).get(unit) or {}).get("summary")
                    for unit in UNITS
                },
            )
        )
    snapshot_units = (
        ((payload.get("additional_diagnostics") or {}).get("snapshot_high_only") or {}).get(
            "units"
        )
        or {}
    )
    sources.append(
        (
            "post-hoc descriptive: snapshot_high_only",
            {
                unit: (snapshot_units.get(unit) or {}).get("summary")
                for unit in UNITS
            },
        )
    )
    for label, unit_summaries in sources:
        for unit in UNITS:
            summary = unit_summaries.get(unit) or {}
            brier_ci = summary.get("brier_cluster_bootstrap_95ci") or {}
            logloss_ci = summary.get("logloss_cluster_bootstrap_95ci") or {}
            rows.append(
                [
                    label,
                    unit,
                    summary.get("fleet_dates"),
                    summary.get("scoring_rows"),
                    fmt_signed(summary.get("mean_brier_delta")),
                    f"[{fmt_num(brier_ci.get('low'))}, {fmt_num(brier_ci.get('high'))}]",
                    fmt_signed(summary.get("mean_logloss_delta")),
                    f"[{fmt_num(logloss_ci.get('low'))}, {fmt_num(logloss_ci.get('high'))}]",
                    fmt_signed(summary.get("mean_candidate_brier_delta_vs_market")),
                ]
            )
    return rows


def render_report(payload: Mapping[str, Any]) -> str:
    panel = payload.get("panel_evidence") or {}
    inputs = payload.get("inputs") or {}
    baseline = inputs.get("baseline_cache") or {}

    def table(headers: list[str], rows: list[list[Any]]) -> str:
        return "\n".join(markdown_table(headers, rows))

    lines = [
        "# H1 Ordinal-Smoothing Holdout Robustness",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "Mode: research-only; no replay, reselection, promotion, serving change, or live trading.",
        "",
        "## Interpretation contract",
        "",
        "The preregistered all-pinned H1 holdout remains primary. The source and panel rows below are post-hoc sensitivity checks only and cannot change the tune-selected weight or primary disposition.",
        "",
        f"Frozen selection copied from H1 tune: `{_canonical_json((payload.get('design') or {}).get('selected_weights_copied_from_h1_tune') or {})}`.",
        "",
        "## Results",
        "",
        table(
            [
                "Analysis",
                "Unit",
                "Dates",
                "Rows",
                "Brier delta",
                "Brier 95% CI",
                "Log-loss delta",
                "Log-loss 95% CI",
                "Candidate-minus-market Brier",
            ],
            _summary_table_rows(payload),
        ),
        "",
        "Negative candidate-minus-incumbent deltas favor the selected smoothing arm. Candidate-minus-market values are a separate calibration benchmark; this diagnostic does not treat incumbent improvement as market edge.",
        "",
        "## Panel and source evidence",
        "",
        f"Expected fleet: `{panel.get('expected_market_count')}` markets: `{', '.join(panel.get('expected_markets') or [])}`.",
        f"Pinned holdout market-dates: `{panel.get('manifest_market_dates')}`; settlement sources: `{_canonical_json(panel.get('manifest_settlement_sources') or {})}`.",
        f"Manifest complete-panel dates: `{', '.join(panel.get('manifest_complete_12_market_dates') or [])}`.",
        f"Manifest daily-summary complete-panel dates: `{', '.join(panel.get('manifest_daily_summary_complete_12_market_dates') or [])}`.",
        f"Observed complete-panel dates: `{', '.join(panel.get('observed_complete_12_market_dates') or [])}`.",
        "",
        "## Additional post-hoc stability diagnostics",
        "",
        "Per-market heterogeneity, the snapshot-high source complement, and leave-one-fleet-date-out influence were computed from the same frozen paired rows. They are descriptive and have no selection effect.",
        "",
        table(
            [
                "Market",
                "Unit",
                "Dates",
                "Brier delta",
                "Log-loss delta",
                "Candidate-minus-market Brier",
                "Diagnostic disposition",
            ],
            [
                [
                    market_id,
                    values.get("unit"),
                    ((values.get("summary") or {}).get("fleet_dates")),
                    fmt_signed((values.get("summary") or {}).get("mean_brier_delta")),
                    fmt_signed((values.get("summary") or {}).get("mean_logloss_delta")),
                    fmt_signed(
                        (values.get("summary") or {}).get(
                            "mean_candidate_brier_delta_vs_market"
                        )
                    ),
                    values.get("status"),
                ]
                for market_id, values in sorted(
                    ((payload.get("additional_diagnostics") or {}).get("per_market") or {}).items()
                )
            ],
        ),
        "",
        table(
            [
                "Unit",
                "Exclusions",
                "Negative on both",
                "Brier-delta range",
                "Log-loss-delta range",
                "Most adverse Brier omission",
                "Most adverse log-loss omission",
            ],
            [
                [
                    unit,
                    values.get("exclusions"),
                    values.get("negative_both_after_exclusion"),
                    "["
                    + fmt_signed(
                        (values.get("mean_brier_delta_range") or {}).get("minimum")
                    )
                    + ", "
                    + fmt_signed(
                        (values.get("mean_brier_delta_range") or {}).get("maximum")
                    )
                    + "]",
                    "["
                    + fmt_signed(
                        (values.get("mean_logloss_delta_range") or {}).get("minimum")
                    )
                    + ", "
                    + fmt_signed(
                        (values.get("mean_logloss_delta_range") or {}).get("maximum")
                    )
                    + "]",
                    values.get("most_adverse_brier_omission"),
                    values.get("most_adverse_logloss_omission"),
                ]
                for unit, values in sorted(
                    (
                        (payload.get("additional_diagnostics") or {}).get(
                            "leave_one_fleet_date_out"
                        )
                        or {}
                    ).items()
                )
            ],
        ),
        "",
        "## Immutable provenance",
        "",
        table(
            ["Input", "Bytes", "SHA-256", "Fingerprint/status"],
            [
                [
                    "H1 result",
                    (inputs.get("h1_result") or {}).get("size_bytes"),
                    (inputs.get("h1_result") or {}).get("sha256"),
                    (inputs.get("h1_result") or {}).get("status"),
                ],
                [
                    "promotion corpus",
                    (inputs.get("corpus_manifest") or {}).get("size_bytes"),
                    (inputs.get("corpus_manifest") or {}).get("sha256"),
                    (inputs.get("corpus_manifest") or {}).get("corpus_hash"),
                ],
                [
                    "holdout weight 0",
                    baseline.get("size_bytes"),
                    baseline.get("sha256"),
                    baseline.get("fingerprint"),
                ],
                *[
                    [
                        f"holdout weight {weight}",
                        values.get("size_bytes"),
                        values.get("sha256"),
                        values.get("fingerprint"),
                    ]
                    for weight, values in sorted(
                        (inputs.get("candidate_caches") or {}).items(),
                        key=lambda item: float(item[0]),
                    )
                ],
            ],
        ),
        "",
        "## Gates",
        "",
        f"All-pinned cache recomputation parity: `{_canonical_json((payload.get('primary_reference') or {}).get('parity') or {})}`.",
        f"Duplicate/alignment evidence: `{_canonical_json(payload.get('alignment') or {})}`.",
        f"Bounded-reader evidence: `{_canonical_json(payload.get('bounded_reader') or {})}`.",
    ]
    blockers = payload.get("technical_blockers") or []
    if blockers:
        lines.extend(["", "## Technical blockers", ""])
        lines.extend(f"- {blocker}" for blocker in blockers)
    lines.extend(
        [
            "",
            "## Safety disposition",
            "",
            "This artifact is diagnostic only. It does not authorize a model artifact, release, serving-pointer update, promotion, or live order path.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        if not content.endswith("\n"):
            handle.write("\n")
    os.replace(temporary, path)


def write_outputs(payload: Mapping[str, Any], json_out: Path, report_out: Path) -> None:
    _atomic_write(json_out, json.dumps(payload, indent=2, sort_keys=True))
    _atomic_write(report_out, render_report(payload))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Derive fixed post-hoc source and complete-panel sensitivities from "
            "immutable selected H1 holdout caches; never replay or reselect."
        )
    )
    parser.add_argument("--h1-result", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--baseline-cache", required=True)
    parser.add_argument(
        "--candidate-cache",
        action="append",
        required=True,
        help="Repeat once for each distinct positive tune-selected holdout weight.",
    )
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--report-out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_analysis(args)
        write_outputs(payload, _resolved(args.json_out), _resolved(args.report_out))
    except (RobustnessConfigurationError, OSError, ValueError) as exc:
        print(f"H1 robustness analysis blocked: {exc}", file=sys.stderr)
        return 2
    print(
        "H1 robustness analysis "
        f"{payload.get('status')}: {args.json_out} and {args.report_out}"
    )
    return 0 if payload.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
