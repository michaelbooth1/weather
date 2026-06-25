"""Settlement scoring for NBM probabilistic Tmax guidance.

This is the roadmap item 190 calibration-anchor scorer. It does not train or
promote a model. It evaluates the captured NBM percentile curve against settled
Polymarket temperature bands on the same rows used by the model/market tapes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT, discover_settled_folders
from weather.backtesting.settlement_ledger import band_value_hi, resolve_outcome
from weather.calibration.pooled_candidate_scoring import (
    blocked_candidate_validation_gate,
    calibration_diagnostics,
    candidate_comparison,
    daily_first_candidate_comparison,
    grouped_candidate_comparison,
)
from weather.market.market_registry import spec_for_slug
from weather.model.continuous_density import bucket_interval_native
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version
from weather.sources.nbm_probabilistic_tmax import NBM_PROB_TMAX_FEATURE_COLUMNS


SCHEMA_VERSION = schema_version("nbm_probabilistic_tmax_settlement_scoring")
DEFAULT_OUT = data_path() / "backtest" / "item190_nbm_probabilistic_tmax_settlement_scoring.json"
DEFAULT_REPORT = data_path() / "backtest" / "item190_nbm_probabilistic_tmax_settlement_scoring_report.md"
NBM_PERCENTILE_COLUMNS = {
    "10": "nbm_prob_tmax_p10",
    "25": "nbm_prob_tmax_p25",
    "50": "nbm_prob_tmax_p50",
    "75": "nbm_prob_tmax_p75",
    "90": "nbm_prob_tmax_p90",
}
DEFAULT_QUALITY_GRADES = ("complete", "manual_override", "partial")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_int(value: Any) -> int | None:
    number = _safe_float(value)
    return int(number) if number is not None else None


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _falsey(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    return str(value or "").strip().lower() in {"0", "false", "no", "n"}


def is_nbm_us_market(spec: Any) -> bool:
    """Return whether the market is eligible for the current NBM CONUS path."""

    if spec is None:
        return False
    sources = set(getattr(spec, "sources", ()) or ())
    wu_history_id = str(getattr(spec, "wu_history_id", "") or "").upper()
    icao = str(getattr(spec, "icao", "") or "").upper()
    return "nws_grid" in sources and wu_history_id.endswith(":US") and icao.startswith("K")


def _feature_index(folder: str | Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    rows = _read_csv(Path(folder) / "features_long.csv")
    index = {}
    schema_versions = Counter()
    nbm_rows = 0
    impossible_rows = 0
    for row in rows:
        snapshot_id = row.get("snapshot_id")
        if not snapshot_id:
            continue
        index[snapshot_id] = row
        if row.get("feature_schema_version"):
            schema_versions[row["feature_schema_version"]] += 1
        if any(_safe_float(row.get(column)) is not None for column in NBM_PERCENTILE_COLUMNS.values()):
            nbm_rows += 1
        if _truthy(row.get("nbm_prob_tmax_impossible_flag")):
            impossible_rows += 1
    return index, {
        "feature_rows": len(rows),
        "feature_snapshot_count": len(index),
        "nbm_feature_rows": nbm_rows,
        "nbm_impossible_feature_rows": impossible_rows,
        "feature_schema_versions": dict(sorted(schema_versions.items())),
    }


def _payload_summary(folder: str | Path) -> dict[str, Any]:
    rows = _read_csv(Path(folder) / "forecast_payloads_long.csv")
    nbm_rows = [row for row in rows if row.get("source") == "nbm_probabilistic_tmax"]
    return {
        "forecast_payload_rows": len(rows),
        "nbm_forecast_payload_rows": len(nbm_rows),
        "nbm_payload_hashes": sorted({row.get("payload_hash") for row in nbm_rows if row.get("payload_hash")})[:5],
        "nbm_source_urls": sorted({row.get("source_url") for row in nbm_rows if row.get("source_url")})[:5],
    }


def percentiles_from_feature_row(row: dict[str, Any]) -> dict[str, float]:
    percentiles = {}
    for percentile, column in NBM_PERCENTILE_COLUMNS.items():
        value = _safe_float((row or {}).get(column))
        if value is not None:
            percentiles[percentile] = value
    return percentiles


def _sorted_percentile_points(percentiles: dict[str, Any]) -> list[tuple[float, float]] | None:
    points = []
    for key, value in (percentiles or {}).items():
        q = _safe_float(key)
        x = _safe_float(value)
        if q is None or x is None:
            continue
        points.append((q / 100.0, x))
    points.sort(key=lambda item: item[0])
    if len(points) < 2:
        return None
    for (_, previous), (_, current) in zip(points, points[1:]):
        if current < previous:
            return None
    return points


def cdf_from_percentile_curve(percentiles: dict[str, Any], threshold: float | None) -> float | None:
    """Piecewise-linear CDF through NBM percentile points with linear tails."""

    if threshold is None:
        return None
    points = _sorted_percentile_points(percentiles)
    if not points:
        return None
    x = float(threshold)
    first_q, first_x = points[0]
    last_q, last_x = points[-1]

    if x <= first_x:
        next_q, next_x = points[1]
        slope = (next_q - first_q) / (next_x - first_x) if next_x > first_x else first_q
        return _clamp_probability(first_q - max(0.0, (first_x - x) * slope))
    if x >= last_x:
        prev_q, prev_x = points[-2]
        slope = (last_q - prev_q) / (last_x - prev_x) if last_x > prev_x else (1.0 - last_q)
        return _clamp_probability(last_q + max(0.0, (x - last_x) * slope))

    for (lower_q, lower_x), (upper_q, upper_x) in zip(points, points[1:]):
        if lower_x <= x <= upper_x:
            if upper_x == lower_x:
                return _clamp_probability((lower_q + upper_q) / 2.0)
            weight = (x - lower_x) / (upper_x - lower_x)
            return _clamp_probability(lower_q + weight * (upper_q - lower_q))
    return None


def nbm_band_probability_from_percentiles(
    percentiles: dict[str, Any],
    kind: str,
    value: Any,
    value_hi: Any = None,
) -> float | None:
    low, high = bucket_interval_native(kind, value, value_hi)
    cdf_low = None if low is None else cdf_from_percentile_curve(percentiles, low)
    cdf_high = None if high is None else cdf_from_percentile_curve(percentiles, high)
    kind = str(kind or "eq").lower()
    if kind == "lte":
        return None if cdf_high is None else _clamp_probability(cdf_high)
    if kind == "gte":
        return None if cdf_low is None else _clamp_probability(1.0 - cdf_low)
    if cdf_low is None or cdf_high is None:
        return None
    return _clamp_probability(cdf_high - cdf_low)


def _band_fields(row: dict[str, Any]) -> tuple[str | None, int | None, int | None]:
    kind = str(row.get("bin_kind") or row.get("bin_type") or "").lower() or None
    value = _safe_int(row.get("bin_value_c") or row.get("bin_value"))
    if value is None:
        return kind, None, None
    explicit_hi = _safe_int(row.get("bin_value_hi") or row.get("bin_value_hi_c"))
    value_hi = band_value_hi(row.get("range_label"), value) if explicit_hi is None else explicit_hi
    return kind, value, value_hi


def _settlement_distance_bucket(kind: str | None, value: int | None, value_hi: int | None, settlement: int | None) -> str:
    if kind is None or value is None or settlement is None:
        return "unknown"
    value_hi = value if value_hi is None else value_hi
    if kind == "lte":
        distance = max(0, int(settlement) - int(value))
    elif kind == "gte":
        distance = max(0, int(value) - int(settlement))
    elif int(value) <= int(settlement) <= int(value_hi):
        distance = 0
    else:
        distance = min(abs(int(settlement) - int(value)), abs(int(settlement) - int(value_hi)))
    return str(int(distance))


def _normalize_snapshot_probabilities(rows: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("snapshot_id") or "")].append(row)
    for snapshot_rows in grouped.values():
        total = sum(float(row["nbm_raw_candidate_p"]) for row in snapshot_rows)
        for row in snapshot_rows:
            row["nbm_partition_probability_sum"] = total
            row["candidate_p"] = _clamp_probability(
                float(row["nbm_raw_candidate_p"]) / total if total > 0 else float(row["nbm_raw_candidate_p"])
            )


def score_folder(
    folder: str | Path,
    *,
    quality_grades: tuple[str, ...] = DEFAULT_QUALITY_GRADES,
    exclude_impossible: bool = True,
    normalize_partitions: bool = True,
) -> dict[str, Any]:
    folder = Path(folder)
    spec = spec_for_slug(folder.name)
    if not is_nbm_us_market(spec):
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": getattr(spec, "id", None),
            "status": "SKIP",
            "reason": "not_us_nbm_market",
            "rows": [],
        }

    settlement = _read_json(folder / "settlement.json")
    if not settlement:
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": getattr(spec, "id", None),
            "status": "SKIP",
            "reason": "missing_settlement_json",
            "rows": [],
        }
    if quality_grades and str(settlement.get("quality_grade") or "") not in set(quality_grades):
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": getattr(spec, "id", None),
            "status": "SKIP",
            "reason": "settlement_quality_excluded",
            "quality_grade": settlement.get("quality_grade"),
            "rows": [],
        }

    features, feature_summary = _feature_index(folder)
    payload_summary = _payload_summary(folder)
    snapshots = _read_csv(folder / "snapshots_long.csv")
    settlement_bucket = _safe_int(settlement.get("settlement_bucket"))
    skip_reasons: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []

    for source in snapshots:
        snapshot_id = source.get("snapshot_id")
        feature = features.get(snapshot_id or "")
        if not feature:
            skip_reasons["missing_feature_row"] += 1
            continue
        if exclude_impossible and _truthy(feature.get("nbm_prob_tmax_impossible_flag")):
            skip_reasons["nbm_physical_impossible"] += 1
            continue
        if exclude_impossible and _falsey(feature.get("nbm_prob_tmax_physical_valid_flag")):
            skip_reasons["nbm_physical_invalid"] += 1
            continue
        percentiles = percentiles_from_feature_row(feature)
        if len(percentiles) < 5:
            skip_reasons["missing_nbm_percentiles"] += 1
            continue
        kind, value, value_hi = _band_fields(source)
        outcome = resolve_outcome(kind, value, settlement_bucket, value_hi)
        if outcome is None:
            skip_reasons["missing_outcome"] += 1
            continue
        candidate = nbm_band_probability_from_percentiles(percentiles, kind or "eq", value, value_hi)
        if candidate is None:
            skip_reasons["nbm_probability_unavailable"] += 1
            continue
        current = _safe_float(source.get("model_probability"))
        market_yes = _safe_float(source.get("market_yes"))
        if current is None or market_yes is None:
            skip_reasons["missing_baseline_probability"] += 1
            continue

        rows.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "target_date": settlement.get("target_date") or source.get("target_date"),
            "event_slug": folder.name,
            "snapshot_id": snapshot_id,
            "captured_at_utc": source.get("captured_at_utc"),
            "captured_at_local": source.get("captured_at_local"),
            "candidate_cutoff_hour": _safe_int(feature.get("cutoff_hour")),
            "cutoff_hour": _safe_int(feature.get("cutoff_hour")),
            "range_label": source.get("range_label"),
            "bin_type": kind,
            "bin_value_c": value,
            "bin_value_hi": value_hi,
            "settlement_bucket": settlement_bucket,
            "settlement_distance_bucket": _settlement_distance_bucket(kind, value, value_hi, settlement_bucket),
            "outcome": int(bool(outcome)),
            "candidate_p": candidate,
            "nbm_raw_candidate_p": candidate,
            "replayed_p": current,
            "recorded_p": current,
            "market_yes": _clamp_probability(market_yes),
            "feature_schema_version": feature.get("feature_schema_version"),
            "nbm_prob_tmax_p10": percentiles.get("10"),
            "nbm_prob_tmax_p25": percentiles.get("25"),
            "nbm_prob_tmax_p50": percentiles.get("50"),
            "nbm_prob_tmax_p75": percentiles.get("75"),
            "nbm_prob_tmax_p90": percentiles.get("90"),
            "nbm_prob_tmax_stddev": _safe_float(feature.get("nbm_prob_tmax_stddev")),
            "nbm_prob_tmax_iqr": _safe_float(feature.get("nbm_prob_tmax_iqr")),
            "nbm_prob_tmax_physical_valid_flag": _safe_float(feature.get("nbm_prob_tmax_physical_valid_flag")),
            "nbm_prob_tmax_impossible_flag": _safe_float(feature.get("nbm_prob_tmax_impossible_flag")),
        })

    if normalize_partitions:
        _normalize_snapshot_probabilities(rows)
    return {
        "folder": str(folder),
        "event_slug": folder.name,
        "market_id": spec.id,
        "target_date": settlement.get("target_date"),
        "quality_grade": settlement.get("quality_grade"),
        "settlement_bucket": settlement_bucket,
        "status": "SCORED" if rows else "NO_ROWS",
        "reason": None if rows else "no_scorable_nbm_rows",
        "snapshot_rows": len(snapshots),
        "scored_rows": len(rows),
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "feature_summary": feature_summary,
        "payload_summary": payload_summary,
        "rows": rows,
    }


def _folder_inputs(
    snapshots_root: str | Path,
    *,
    as_of: str | None = None,
    folders: list[str | Path] | None = None,
) -> list[Path]:
    if folders:
        return [Path(folder) for folder in folders]
    return list(discover_settled_folders(root=snapshots_root, as_of=as_of, required_file="snapshots_long.csv"))


def _artifact_payload(row_count: int, feature_schema_versions: dict[str, int]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(DEFAULT_OUT),
        "prediction_mode": "nbm_percentile_curve_anchor",
        "objective": "settlement_scored_nbm_probabilistic_tmax_band_brier",
        "feature_subset": "nbm_probabilistic_tmax",
        "feature_subset_contract": {
            "schema_version": "pooled_feature_subset_v0.1",
            "name": "nbm_probabilistic_tmax",
            "allowed_feature_families": ["nbm_probabilistic_tmax", "market_climate_context"],
            "blocked_feature_families": ["clob_microstructure", "settlement_observation"],
            "description": "Direct NBM probabilistic Tmax percentile-curve calibration-anchor replay.",
        },
        "feature_names": list(NBM_PROB_TMAX_FEATURE_COLUMNS),
        "feature_schema_versions": feature_schema_versions,
        "row_count": row_count,
    }


def _verdict(
    rows: list[dict[str, Any]],
    blocked_validation: dict[str, Any],
    by_market: list[dict[str, Any]],
    *,
    current_tol: float,
) -> tuple[str, str]:
    if not rows:
        return "BLOCK", "NO_CUTOVER"
    if blocked_validation.get("passed") is not True:
        return "BLOCK", "DO_NOT_CUT_OVER"
    regressions = [
        row for row in by_market
        if row.get("delta_vs_current") is None or row.get("delta_vs_current") > current_tol
    ]
    if regressions:
        return "BLOCK", "DO_NOT_CUT_OVER"
    return "PASS", "SHADOW_READY"


def build_payload(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    as_of: str | None = None,
    folders: list[str | Path] | None = None,
    quality_grades: tuple[str, ...] = DEFAULT_QUALITY_GRADES,
    exclude_impossible: bool = True,
    normalize_partitions: bool = True,
    current_tol: float = 0.003,
    market_tol: float = 0.003,
    min_days: int = 2,
) -> dict[str, Any]:
    folder_paths = _folder_inputs(snapshots_root, as_of=as_of, folders=folders)
    folder_results = [
        score_folder(
            folder,
            quality_grades=quality_grades,
            exclude_impossible=exclude_impossible,
            normalize_partitions=normalize_partitions,
        )
        for folder in folder_paths
    ]
    rows = [row for result in folder_results for row in result.get("rows") or []]
    feature_schema_versions: Counter[str] = Counter()
    for result in folder_results:
        for schema, count in ((result.get("feature_summary") or {}).get("feature_schema_versions") or {}).items():
            feature_schema_versions[schema] += count

    aggregate = candidate_comparison(rows)
    daily_first = daily_first_candidate_comparison(rows)
    blocked_validation = blocked_candidate_validation_gate(
        rows,
        current_tol=current_tol,
        market_tol=market_tol,
        min_days=min_days,
    )
    by_market = grouped_candidate_comparison(rows, "market_id")
    by_hour = grouped_candidate_comparison(rows, "candidate_cutoff_hour")
    by_settlement_distance = grouped_candidate_comparison(rows, "settlement_distance_bucket")
    verdict, cutover_decision = _verdict(
        rows,
        blocked_validation,
        by_market,
        current_tol=current_tol,
    )
    scored_folders = [result for result in folder_results if result.get("status") == "SCORED"]
    quality_grade_counts = Counter(
        str(result.get("quality_grade") or "unknown")
        for result in scored_folders
    )
    nbm_payload_folder_count = sum(
        1
        for result in folder_results
        if ((result.get("payload_summary") or {}).get("nbm_forecast_payload_rows") or 0) > 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "snapshots_root": str(snapshots_root),
            "as_of": as_of,
            "folder_count": len(folder_paths),
            "quality_grades": list(quality_grades),
            "exclude_impossible": exclude_impossible,
            "normalize_partitions": normalize_partitions,
            "current_tol": current_tol,
            "market_tol": market_tol,
            "min_days": min_days,
        },
        "artifact": _artifact_payload(len(rows), dict(sorted(feature_schema_versions.items()))),
        "coverage": {
            "discovered_folder_count": len(folder_paths),
            "scored_folder_count": len(scored_folders),
            "skipped_folder_count": len(folder_results) - len(scored_folders),
            "nbm_payload_folder_count": nbm_payload_folder_count,
            "row_count": len(rows),
            "market_count": len({row.get("market_id") for row in rows}),
            "target_date_count": len({row.get("target_date") for row in rows}),
            "markets": sorted({row.get("market_id") for row in rows if row.get("market_id")}),
            "target_dates": sorted({row.get("target_date") for row in rows if row.get("target_date")}),
            "quality_grade_counts": dict(sorted(quality_grade_counts.items())),
        },
        "folder_results": [
            {key: value for key, value in result.items() if key != "rows"}
            for result in folder_results
        ],
        "aggregate": aggregate,
        "daily_first": daily_first,
        "blocked_validation": blocked_validation,
        "by_nbm_us_market": by_market,
        "by_market": by_market,
        "by_hour": by_hour,
        "by_settlement_distance": by_settlement_distance,
        "calibration": {
            "candidate": calibration_diagnostics(rows, "candidate_p"),
            "current": calibration_diagnostics(rows, "replayed_p"),
            "market": calibration_diagnostics(rows, "market_yes"),
        },
        "nbm_probabilistic_tmax_gate": {
            "by_us_market": by_market,
        },
        "scored_row_samples": rows[:20],
        "verdict": verdict,
        "cutover_decision": cutover_decision,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    coverage = payload.get("coverage") or {}
    aggregate = payload.get("aggregate") or {}
    blocked = payload.get("blocked_validation") or {}
    lines = [
        "# NBM Probabilistic Tmax Settlement Scoring",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Verdict: `{payload.get('verdict')}`",
        f"Cutover decision: `{payload.get('cutover_decision')}`",
        "",
        "## Coverage",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Discovered folders", coverage.get("discovered_folder_count")],
                ["Scored folders", coverage.get("scored_folder_count")],
                ["NBM payload folders", coverage.get("nbm_payload_folder_count")],
                ["Rows", coverage.get("row_count")],
                ["Markets", ", ".join(coverage.get("markets") or []) or "-"],
                ["Target dates", ", ".join(coverage.get("target_dates") or []) or "-"],
                [
                    "Scored quality grades",
                    ", ".join(
                        f"{grade}={count}"
                        for grade, count in (coverage.get("quality_grade_counts") or {}).items()
                    ) or "-",
                ],
            ],
        ),
        "",
        "## Aggregate",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Rows", aggregate.get("n")],
                ["NBM Brier", fmt_num(aggregate.get("candidate_brier"), 6)],
                ["Current Brier", fmt_num(aggregate.get("current_brier"), 6)],
                ["Market Brier", fmt_num(aggregate.get("market_brier"), 6)],
                ["Delta vs current", fmt_signed(aggregate.get("delta_vs_current"), 6)],
                ["Delta vs market", fmt_signed(aggregate.get("delta_vs_market"), 6)],
                ["NBM ECE", fmt_num(aggregate.get("candidate_ece"), 6)],
            ],
        ),
        "",
        "## Blocked Validation",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Verdict", blocked.get("verdict") or "-"],
                ["Passed", blocked.get("passed")],
                ["Reasons", "; ".join(blocked.get("reasons") or []) or "-"],
            ],
        ),
        "",
        "## US Market Rows",
        "",
        *markdown_table(
            ["Market", "Rows", "NBM Brier", "Current Brier", "Delta"],
            [
                [
                    row.get("group"),
                    row.get("n"),
                    fmt_num(row.get("candidate_brier"), 6),
                    fmt_num(row.get("current_brier"), 6),
                    fmt_signed(row.get("delta_vs_current"), 6),
                ]
                for row in payload.get("by_nbm_us_market") or []
            ],
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    quality_grades = tuple(
        item.strip()
        for item in str(args.quality_grades or "").split(",")
        if item.strip()
    )
    payload = build_payload(
        args.snapshots_root,
        as_of=args.as_of,
        folders=args.folders,
        quality_grades=quality_grades,
        exclude_impossible=not args.include_impossible,
        normalize_partitions=not args.disable_partition_normalization,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
    )
    payload["artifact"]["path"] = str(args.out)
    write_json(args.out, payload)
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Settlement-score NBM probabilistic Tmax guidance.")
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders. Defaults to discovered settled folders.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES))
    parser.add_argument("--include-impossible", action="store_true")
    parser.add_argument("--disable-partition-normalization", action="store_true")
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"NBM probabilistic Tmax settlement scoring: {payload['verdict']} ({payload['cutover_decision']})")
    print(f"Rows scored: {(payload.get('coverage') or {}).get('row_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
