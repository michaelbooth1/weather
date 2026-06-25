"""Build a settled-day root-cause report across model, taker, and MM logs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import read_json
from weather.paths import data_path, docs_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.casebooks.disagreement_casebook import (
    load_market_event_context,
    market_event_summary,
    parse_time as parse_event_time,
)
from weather.reporting.roadmap.roadmap_backlog import item_files, parse_item
from weather.reporting.serving_gates.model_scoring_liveness import (
    attach_scoring_liveness,
    build_root_cause_rerun_command,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("settled_day_root_cause")
DEFAULT_DATA_ROOT = data_path()
DEFAULT_SNAPSHOTS_ROOT = DEFAULT_DATA_ROOT / "snapshots"
DEFAULT_BACKTEST_ROOT = DEFAULT_DATA_ROOT / "backtest"
DEFAULT_LABELS_CSV = DEFAULT_BACKTEST_ROOT / "market_day_labels.csv"
DEFAULT_TAKER_ROOT = DEFAULT_DATA_ROOT / "taker_runs"
DEFAULT_MM_ROOT = DEFAULT_DATA_ROOT / "mm_runs"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_root_cause.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_root_cause_report.md"
DEFAULT_ISSUES_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_root_cause_issues.csv"
DEFAULT_ROADMAP_ROOT = docs_path("roadmap")
SNAPSHOTS_FILENAME = "snapshots_long.csv"
FEATURES_FILENAME = "features_long.csv"
EXPLANATIONS_FILENAME = "snapshot_explanations_long.csv"
SETTLEMENT_FILENAME = "settlement.json"
EPSILON = 1e-9

ROADMAP_BY_ISSUE = {
    "TAKER_BOUGHT_WARM_TAIL": ["192", "194", "195"],
    "MODEL_TOP_WARM_SIDE_MISS": ["194", "195"],
    "HIGH_DISAGREEMENT_WARM_OUTLIER": ["194"],
    "RAMP_WINDOW_WARM_TAIL_SPREAD": ["195"],
    "WU_CURRENT_MAX_ANOMALY": ["193"],
    "STARTUP_LIVE_OBSERVATION_IMPLAUSIBLE": ["197"],
    "LATE_DAY_LOCKIN_UNDER_COVERAGE": ["196"],
    "MODEL_WEAK_HOUR_SLOT": ["160", "177", "168"],
    "MM_PREFLIGHT_STALE_BOOKS": ["210", "161", "157"],
}
SUGGESTED_ROADMAP_TITLES = {
    "TAKER_BOUGHT_WARM_TAIL": "Post-Closure Taker Warm-Tail Loss Recurrence",
    "MODEL_TOP_WARM_SIDE_MISS": "Post-Closure Model Warm-Side Miss Recurrence",
    "HIGH_DISAGREEMENT_WARM_OUTLIER": "Post-Closure High-Disagreement Warm-Outlier Recurrence",
    "RAMP_WINDOW_WARM_TAIL_SPREAD": "Post-Closure Ramp-Window Warm-Tail Recurrence",
    "WU_CURRENT_MAX_ANOMALY": "Post-Closure WU Current-Max Anomaly Recurrence",
    "STARTUP_LIVE_OBSERVATION_IMPLAUSIBLE": "Post-Closure Startup Observation Implausibility Recurrence",
    "LATE_DAY_LOCKIN_UNDER_COVERAGE": "Post-Closure Late-Day Lock-In Coverage Recurrence",
    "MODEL_WEAK_HOUR_SLOT": "Model Weak-Slot Recurrence Active Remediation",
    "MM_PREFLIGHT_STALE_BOOKS": "Market-Maker Stale-Input Blackout Recurrence",
}
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def maybe_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) else number
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def maybe_int(value: Any) -> int | None:
    number = maybe_float(value)
    if number is None:
        return None
    return int(round(number))


def mean(values) -> float | None:
    cleaned = [value for value in values if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def compact(value: Any, decimals: int = 4) -> Any:
    number = maybe_float(value)
    if number is None:
        return value
    return round(number, decimals)


def date_slug(target_date: str) -> str:
    parsed = datetime.strptime(str(target_date), "%Y-%m-%d")
    return f"{parsed.strftime('%B').lower()}-{parsed.day}-{parsed.year}"


def folder_market_id(folder: str | Path) -> str:
    name = Path(folder).name
    match = re.match(r"highest-temperature-in-(?P<market>.+)-on-", name)
    return (match.group("market") if match else name).replace("_", "-")


def snapshot_folders_for_date(snapshots_root: str | Path, target_date: str) -> list[Path]:
    root = Path(snapshots_root)
    suffix = f"on-{date_slug(target_date)}"
    if not root.exists():
        return []
    return sorted(
        folder for folder in root.iterdir()
        if folder.is_dir()
        and folder.name.endswith(suffix)
        and (folder / SNAPSHOTS_FILENAME).exists()
    )


def label_numbers(value: Any) -> list[int]:
    if not value:
        return []
    return [int(match.group(0)) for match in re.finditer(r"(?<!\d)-?\d+", str(value))]


def settlement_bucket(settlement: dict[str, Any]) -> int | None:
    direct = maybe_int(settlement.get("settlement_bucket"))
    if direct is not None:
        return direct
    evidence = settlement.get("evidence") or {}
    reconciliation = evidence.get("polymarket_reconciliation") or {}
    local_band = reconciliation.get("local_winning_band") or {}
    direct = maybe_int(local_band.get("value"))
    if direct is not None:
        return direct
    winners = reconciliation.get("winning_markets") or reconciliation.get("matching_winning_markets") or []
    for winner in winners:
        direct = maybe_int(winner.get("value"))
        if direct is not None:
            return direct
        nums = label_numbers(winner.get("label") or winner.get("question"))
        if nums:
            return nums[0]
    return None


def settlement_unit(settlement: dict[str, Any]) -> str | None:
    direct = settlement.get("settlement_unit")
    if direct:
        return str(direct)
    spec = ((settlement.get("evidence") or {}).get("resolution_spec") or {})
    return spec.get("market_unit")


def band_key(row: dict[str, Any]) -> tuple[str, int | None, int | None]:
    kind = (row.get("bin_kind") or row.get("kind") or "").lower()
    value = maybe_int(row.get("bin_value_c") or row.get("bin_value") or row.get("value"))
    value_hi = maybe_int(row.get("bin_value_hi_c") or row.get("bin_value_hi") or row.get("value_hi"))
    nums = label_numbers(row.get("range_label"))
    if value is None and nums:
        value = nums[0]
    if value_hi is None:
        if kind == "eq" and len(nums) >= 2:
            value_hi = nums[-1]
        else:
            value_hi = value
    return kind, value, value_hi


def band_outcome(row: dict[str, Any], final_bucket: int | None) -> int | None:
    if final_bucket is None:
        return None
    kind, value, value_hi = band_key(row)
    if value is None:
        return None
    if kind == "lte":
        return int(final_bucket <= value)
    if kind == "gte":
        return int(final_bucket >= value)
    if value_hi is None:
        value_hi = value
    return int(value <= final_bucket <= value_hi)


def band_identity(row: dict[str, Any]) -> tuple[str, int | None, int | None]:
    return band_key(row)


def band_midpoint(row: dict[str, Any]) -> float | None:
    _kind, value, value_hi = band_key(row)
    if value is None:
        return None
    value_hi = value if value_hi is None else value_hi
    return (float(value) + float(value_hi)) / 2.0


def model_expected_bucket(rows: list[dict[str, Any]]) -> float | None:
    pairs = []
    for row in rows:
        probability = maybe_float(row.get("model_probability"))
        midpoint = band_midpoint(row)
        if probability is None or midpoint is None or probability < 0:
            continue
        pairs.append((midpoint, probability))
    total = sum(probability for _, probability in pairs)
    if total <= 0:
        return None
    return sum(midpoint * probability for midpoint, probability in pairs) / total


def model_effective_spread(rows: list[dict[str, Any]], expected: float | None) -> float | None:
    if expected is None:
        return None
    pairs = []
    for row in rows:
        probability = maybe_float(row.get("model_probability"))
        midpoint = band_midpoint(row)
        if probability is None or midpoint is None or probability < 0:
            continue
        pairs.append((midpoint, probability))
    total = sum(probability for _, probability in pairs)
    if total <= 0:
        return None
    variance = sum(((midpoint - expected) ** 2) * probability for midpoint, probability in pairs) / total
    return math.sqrt(max(0.0, variance))


def capture_hour(row: dict[str, Any]) -> int | None:
    text = row.get("captured_at_local") or row.get("captured_at_utc") or ""
    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).hour
        except ValueError:
            pass
    return maybe_int(row.get("capture_hour_local") or row.get("cutoff_hour"))


def afternoon_slice_summary(snapshot_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        row for row in snapshot_rows
        if row.get("hour") is not None and 15 <= int(row.get("hour")) <= 18
    ]
    biases = [
        row.get("model_expected_minus_settlement")
        for row in rows
        if row.get("model_expected_minus_settlement") is not None
    ]
    return {
        "hour_window": "15-18",
        "snapshot_count": len(rows),
        "mean_expected_high_bias": mean(biases),
        "hot_share": mean(1.0 if bias > 0 else 0.0 for bias in biases),
        "mean_winner_probability": mean(row.get("final_model_probability") for row in rows),
        "mean_effective_spread": mean(row.get("model_effective_spread") for row in rows),
        "mean_forecast_disagreement": mean(row.get("forecast_disagreement") for row in rows),
    }


def load_features_by_snapshot(folder: Path) -> dict[str, dict[str, Any]]:
    path = folder / FEATURES_FILENAME
    if not path.exists():
        return {}
    output: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            snapshot_id = row.get("snapshot_id")
            if snapshot_id and snapshot_id not in output:
                output[snapshot_id] = dict(row)
    return output


def load_explanations_by_snapshot(folder: Path) -> dict[str, list[dict[str, Any]]]:
    path = folder / EXPLANATIONS_FILENAME
    if not path.exists():
        return {}
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            snapshot_id = row.get("snapshot_id")
            if snapshot_id:
                output[snapshot_id].append(dict(row))
    return output


def explanation_evidence_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sections = sorted({row.get("section") for row in rows if row.get("section")})
    hashes = sorted({row.get("payload_hash") for row in rows if row.get("payload_hash")})
    return {
        "available": bool(rows),
        "row_count": len(rows),
        "sections": sections,
        "payload_hashes": hashes[:12],
        "source_hash": next((row.get("source_hash") for row in rows if row.get("source_hash")), None),
        "model_identity_hash": next((row.get("model_identity_hash") for row in rows if row.get("model_identity_hash")), None),
    }


def _rank(rows: list[dict[str, Any]], key: str, wanted_identity: tuple[str, int | None, int | None]) -> int | None:
    ranked = sorted(rows, key=lambda item: maybe_float(item.get(key)) or 0.0, reverse=True)
    for index, row in enumerate(ranked, start=1):
        if band_identity(row) == wanted_identity:
            return index
    return None


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    issue_code: str,
    source: str,
    market_id: str,
    event_slug: str = "",
    snapshot_id: str = "",
    severity: str = "medium",
    detail: str = "",
    metric: float | None = None,
    roadmap_items: list[str] | None = None,
) -> None:
    issues.append({
        "issue_code": issue_code,
        "source": source,
        "market_id": market_id,
        "event_slug": event_slug,
        "snapshot_id": snapshot_id,
        "severity": severity,
        "detail": detail,
        "metric": metric,
        "roadmap_items": ",".join(roadmap_items or ROADMAP_BY_ISSUE.get(issue_code, [])),
    })


def _snapshot_issue_checks(
    *,
    row: dict[str, Any],
    feature_row: dict[str, Any],
    final_bucket: int,
    final_row: dict[str, Any],
    model_top: dict[str, Any],
    final_model_rank: int | None,
    market_id: str,
    unit: str | None,
    issues: list[dict[str, Any]],
) -> None:
    event_slug = row.get("event_slug") or ""
    snapshot_id = row.get("snapshot_id") or ""
    hour = capture_hour(row)
    _kind, top_value, _top_hi = band_key(model_top)
    final_probability = maybe_float(final_row.get("model_probability"))
    market_probability = maybe_float(final_row.get("market_yes"))
    top_probability = maybe_float(model_top.get("model_probability"))
    warm_miss = (
        top_value is not None
        and top_value > final_bucket + 1
        and (final_model_rank or 99) > 1
    )
    if warm_miss:
        _add_issue(
            issues,
            issue_code="MODEL_TOP_WARM_SIDE_MISS",
            source="snapshots_long",
            market_id=market_id,
            event_slug=event_slug,
            snapshot_id=snapshot_id,
            severity="high" if (top_probability or 0.0) >= 0.35 else "medium",
            detail=(
                f"model top {model_top.get('range_label')} while settled bucket was "
                f"{final_bucket}; final rank={final_model_rank}"
            ),
            metric=(top_probability or 0.0) - (final_probability or 0.0),
        )
    disagreement = maybe_float(row.get("forecast_disagreement") or feature_row.get("forecast_disagreement"))
    if warm_miss and disagreement is not None and disagreement >= 3.0:
        _add_issue(
            issues,
            issue_code="HIGH_DISAGREEMENT_WARM_OUTLIER",
            source="snapshots_long",
            market_id=market_id,
            event_slug=event_slug,
            snapshot_id=snapshot_id,
            severity="medium",
            detail=f"forecast disagreement {disagreement:.2f} with warm-side model top",
            metric=disagreement,
        )
    if warm_miss and hour is not None and 8 <= hour <= 14:
        _add_issue(
            issues,
            issue_code="RAMP_WINDOW_WARM_TAIL_SPREAD",
            source="snapshots_long",
            market_id=market_id,
            event_slug=event_slug,
            snapshot_id=snapshot_id,
            severity="high",
            detail=f"ramp hour {hour} model top was above settled bucket",
            metric=(top_probability or 0.0) - (final_probability or 0.0),
        )
    if warm_miss and hour is not None and 15 <= hour <= 19:
        live_minus_high = maybe_float(feature_row.get("live_reading_minus_high"))
        if live_minus_high is None or live_minus_high < 0:
            _add_issue(
                issues,
                issue_code="LATE_DAY_LOCKIN_UNDER_COVERAGE",
                source="snapshots_long",
                market_id=market_id,
                event_slug=event_slug,
                snapshot_id=snapshot_id,
                severity="medium",
                detail=f"late-day hour {hour} kept warm-side top after current rolled",
                metric=live_minus_high,
            )

    history_high = maybe_float(row.get("wu_history_high_c") or feature_row.get("high_so_far"))
    current_temp = maybe_float(row.get("wu_current_c") or feature_row.get("current_temp"))
    current_max = maybe_float(row.get("wu_max_since_7am_c") or feature_row.get("trusted_current_max"))
    if current_max is not None and history_high is not None and current_temp is not None:
        max_gap = current_max - max(history_high, current_temp)
        if max_gap >= 3.0:
            _add_issue(
                issues,
                issue_code="WU_CURRENT_MAX_ANOMALY",
                source="features",
                market_id=market_id,
                event_slug=event_slug,
                snapshot_id=snapshot_id,
                severity="medium",
                detail=f"current max exceeded printed/current observations by {max_gap:.2f}",
                metric=max_gap,
            )

    if hour is not None and hour < 7:
        high_so_far = maybe_float(feature_row.get("high_so_far"))
        current = maybe_float(feature_row.get("current_temp"))
        if str(unit or "").upper() == "F":
            implausible = any(value is not None and value < 45.0 for value in (high_so_far, current))
        else:
            implausible = any(value is not None and (value < -20.0 or value > 55.0) for value in (high_so_far, current))
        if implausible:
            _add_issue(
                issues,
                issue_code="STARTUP_LIVE_OBSERVATION_IMPLAUSIBLE",
                source="features",
                market_id=market_id,
                event_slug=event_slug,
                snapshot_id=snapshot_id,
                severity="medium",
                detail=f"startup feature values high_so_far={high_so_far}, current_temp={current}, unit={unit}",
            )

    if (
        final_probability is not None
        and market_probability is not None
        and market_probability - final_probability >= 0.15
    ):
        _add_issue(
            issues,
            issue_code="MODEL_WEAK_HOUR_SLOT",
            source="snapshots_long",
            market_id=market_id,
            event_slug=event_slug,
            snapshot_id=snapshot_id,
            severity="low",
            detail=f"market gave settled band {market_probability:.3f} vs model {final_probability:.3f}",
            metric=market_probability - final_probability,
        )


def analyze_snapshot_folder(folder: str | Path) -> dict[str, Any]:
    folder = Path(folder)
    settlement = read_json(folder / SETTLEMENT_FILENAME, default={}) or {}
    final_bucket = settlement_bucket(settlement)
    market_id = settlement.get("market_id") or folder_market_id(folder)
    unit = settlement_unit(settlement)
    features_by_snapshot = load_features_by_snapshot(folder)
    explanations_by_snapshot = load_explanations_by_snapshot(folder)
    market_events = load_market_event_context(folder)
    by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with (folder / SNAPSHOTS_FILENAME).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            snapshot_id = row.get("snapshot_id")
            if snapshot_id:
                by_snapshot[snapshot_id].append(dict(row))

    snapshot_rows = []
    issues: list[dict[str, Any]] = []
    for snapshot_id, rows in by_snapshot.items():
        if final_bucket is None:
            continue
        final_rows = [row for row in rows if band_outcome(row, final_bucket) == 1]
        if not final_rows:
            continue
        final_row = max(final_rows, key=lambda item: maybe_float(item.get("model_probability")) or 0.0)
        model_top = max(rows, key=lambda item: maybe_float(item.get("model_probability")) or 0.0)
        market_top = max(rows, key=lambda item: maybe_float(item.get("market_yes")) or 0.0)
        final_identity = band_identity(final_row)
        model_rank = _rank(rows, "model_probability", final_identity)
        market_rank = _rank(rows, "market_yes", final_identity)
        expected = model_expected_bucket(rows)
        spread = model_effective_spread(rows, expected)
        feature_row = features_by_snapshot.get(snapshot_id, {})
        disagreement = maybe_float(final_row.get("forecast_disagreement") or feature_row.get("forecast_disagreement"))
        explanation_evidence = explanation_evidence_summary(explanations_by_snapshot.get(snapshot_id, []))
        market_event_evidence = market_event_summary(
            market_events,
            key=final_identity,
            direction="model_yes",
            snapshot_time=parse_event_time(final_row.get("captured_at_local") or final_row.get("captured_at_utc")),
        )
        row = {
            "event_slug": final_row.get("event_slug") or folder.name,
            "market_id": market_id,
            "snapshot_id": snapshot_id,
            "captured_at_local": final_row.get("captured_at_local") or "",
            "hour": capture_hour(final_row),
            "settlement_bucket": final_bucket,
            "settlement_unit": unit,
            "final_range_label": final_row.get("range_label"),
            "model_top_label": model_top.get("range_label"),
            "market_top_label": market_top.get("range_label"),
            "final_model_probability": maybe_float(final_row.get("model_probability")),
            "final_market_probability": maybe_float(final_row.get("market_yes")),
            "model_top_probability": maybe_float(model_top.get("model_probability")),
            "market_top_probability": maybe_float(market_top.get("market_yes")),
            "model_final_rank": model_rank,
            "market_final_rank": market_rank,
            "model_expected_bucket": expected,
            "model_expected_minus_settlement": (
                expected - final_bucket
                if expected is not None and final_bucket is not None
                else None
            ),
            "model_effective_spread": spread,
            "forecast_disagreement": disagreement,
            "model_top_is_winner": band_identity(model_top) == final_identity,
            "market_top_is_winner": band_identity(market_top) == final_identity,
            "explanation_available": explanation_evidence.get("available"),
            "explanation_row_count": explanation_evidence.get("row_count"),
            "explanation_sections": explanation_evidence.get("sections"),
            "explanation_source_hash": explanation_evidence.get("source_hash"),
            "explanation_model_identity_hash": explanation_evidence.get("model_identity_hash"),
            "market_event_available": market_event_evidence.get("available"),
            "market_event_token_id": market_event_evidence.get("token_id"),
            "price_history_points_300s": market_event_evidence.get("price_history_points_300s"),
            "latest_market_event_price": market_event_evidence.get("latest_price"),
            "price_change_300s": market_event_evidence.get("price_change_300s"),
            "ws_event_count_300s": market_event_evidence.get("ws_event_count_300s"),
            "ws_event_types": market_event_evidence.get("ws_event_types"),
        }
        snapshot_rows.append(row)
        _snapshot_issue_checks(
            row=final_row,
            feature_row=feature_row,
            final_bucket=final_bucket,
            final_row=final_row,
            model_top=model_top,
            final_model_rank=model_rank,
            market_id=market_id,
            unit=unit,
            issues=issues,
        )

    return {
        "folder": str(folder),
        "event_slug": folder.name,
        "market_id": market_id,
        "settlement_bucket": final_bucket,
        "settlement_unit": unit,
        "snapshot_count": len(snapshot_rows),
        "model_top_winner_rate": mean(1.0 if row["model_top_is_winner"] else 0.0 for row in snapshot_rows),
        "market_top_winner_rate": mean(1.0 if row["market_top_is_winner"] else 0.0 for row in snapshot_rows),
        "mean_final_model_probability": mean(row.get("final_model_probability") for row in snapshot_rows),
        "mean_final_market_probability": mean(row.get("final_market_probability") for row in snapshot_rows),
        "mean_model_final_rank": mean(row.get("model_final_rank") for row in snapshot_rows),
        "mean_market_final_rank": mean(row.get("market_final_rank") for row in snapshot_rows),
        "afternoon_post_ramp_slice": afternoon_slice_summary(snapshot_rows),
        "explanation_snapshot_count": sum(1 for row in snapshot_rows if row.get("explanation_available")),
        "explanation_row_count": sum(int(row.get("explanation_row_count") or 0) for row in snapshot_rows),
        "explanation_sections": sorted({
            section
            for row in snapshot_rows
            for section in (row.get("explanation_sections") or [])
        }),
        "market_event_snapshot_count": sum(1 for row in snapshot_rows if row.get("market_event_available")),
        "price_history_snapshot_count": sum(
            1 for row in snapshot_rows if int(row.get("price_history_points_300s") or 0) > 0
        ),
        "ws_event_snapshot_count": sum(
            1 for row in snapshot_rows if int(row.get("ws_event_count_300s") or 0) > 0
        ),
        "worst_model_misses": sorted(
            snapshot_rows,
            key=lambda row: (
                row.get("model_final_rank") or 0,
                (row.get("model_top_probability") or 0.0) - (row.get("final_model_probability") or 0.0),
            ),
            reverse=True,
        )[:10],
        "issue_counts": dict(Counter(issue["issue_code"] for issue in issues)),
        "issues": issues,
    }


def discover_taker_run(target_date: str, taker_root: str | Path = DEFAULT_TAKER_ROOT) -> Path | None:
    date_root = Path(taker_root) / target_date
    if not date_root.exists():
        return None
    candidates = [path for path in date_root.iterdir() if path.is_dir() and path.name.startswith("taker-")]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def analyze_taker_run(run_folder: str | Path | None, target_date: str) -> dict[str, Any]:
    if run_folder is None:
        run_folder = discover_taker_run(target_date)
    if run_folder is None:
        return {"available": False, "run_folder": None, "issues": [], "summary": {}}
    run_folder = Path(run_folder)
    pnl = read_json(run_folder / "daily_pnl.json", default={}) or {}
    issues: list[dict[str, Any]] = []
    filled_count = 0
    losing_fill_count = 0
    warm_tail_loss_count = 0
    net_pnl = maybe_float(pnl.get("net_pnl_usdc") or (pnl.get("summary") or {}).get("net_pnl_usdc"))
    if net_pnl is None:
        net_pnl = sum(maybe_float(row.get("net_pnl_usdc")) or 0.0 for row in pnl.get("by_market") or [])
    worst_fills: list[dict[str, Any]] = []
    by_market = {row.get("market_id"): dict(row) for row in pnl.get("by_market") or []}
    orders_path = run_folder / "orders_long.csv"
    if orders_path.exists():
        with orders_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                fill_notional = maybe_float(row.get("fill_notional_usdc")) or 0.0
                if fill_notional <= 0:
                    continue
                filled_count += 1
                pnl_value = maybe_float(row.get("net_pnl_usdc") or row.get("settlement_pnl_usdc"))
                if pnl_value is not None and pnl_value < 0:
                    losing_fill_count += 1
                bucket = maybe_float(row.get("bin_value"))
                settled_high = maybe_float(row.get("settlement_current_high") or row.get("raw_current_high"))
                if (
                    pnl_value is not None
                    and pnl_value < 0
                    and bucket is not None
                    and settled_high is not None
                    and bucket > settled_high + 1
                ):
                    warm_tail_loss_count += 1
                    _add_issue(
                        issues,
                        issue_code="TAKER_BOUGHT_WARM_TAIL",
                        source="orders_long",
                        market_id=row.get("market_id") or "",
                        event_slug=row.get("event_slug") or "",
                        snapshot_id=row.get("snapshot_id") or "",
                        severity="high" if fill_notional >= 5 else "medium",
                        detail=(
                            f"filled {row.get('range_label')} at {row.get('fill_price')} "
                            f"for {fill_notional:.2f} USDC; reference high {settled_high}"
                        ),
                        metric=pnl_value,
                    )
                if pnl_value is not None:
                    worst_fills.append({
                        "market_id": row.get("market_id"),
                        "event_slug": row.get("event_slug"),
                        "snapshot_id": row.get("snapshot_id"),
                        "hour": row.get("capture_hour_local"),
                        "range_label": row.get("range_label"),
                        "fill_price": maybe_float(row.get("fill_price")),
                        "fill_notional_usdc": fill_notional,
                        "net_pnl_usdc": pnl_value,
                        "fair_probability": maybe_float(row.get("fair_probability")),
                        "current_max_disposition": row.get("current_max_disposition"),
                    })
    worst_fills = sorted(worst_fills, key=lambda row: row.get("net_pnl_usdc") or 0.0)[:10]
    return {
        "available": True,
        "run_folder": str(run_folder),
        "summary": {
            "net_pnl_usdc": net_pnl,
            "filled_order_count": filled_count or sum(int(row.get("filled_order_count") or 0) for row in by_market.values()),
            "losing_fill_count": losing_fill_count,
            "warm_tail_loss_count": warm_tail_loss_count,
            "by_market": list(by_market.values()),
        },
        "worst_fills": worst_fills,
        "issue_counts": dict(Counter(issue["issue_code"] for issue in issues)),
        "issues": issues,
    }


def discover_mm_runs(target_date: str, mm_root: str | Path = DEFAULT_MM_ROOT) -> list[Path]:
    date_root = Path(mm_root) / target_date
    if not date_root.exists():
        return []
    return sorted(path for path in date_root.iterdir() if path.is_dir())


def analyze_mm_runs(target_date: str, mm_root: str | Path = DEFAULT_MM_ROOT) -> dict[str, Any]:
    runs = []
    issues: list[dict[str, Any]] = []
    for run_folder in discover_mm_runs(target_date, mm_root):
        summary = read_json(run_folder / "run_summary.json", default={}) or {}
        preflight = read_json(run_folder / "preflight.json", default={}) or {}
        cumulative = summary.get("cumulative") or {}
        blocked = int(cumulative.get("blocked_by_preflight_count") or 0)
        fills_path = run_folder / "fills_long.csv"
        fill_count = 0
        if fills_path.exists():
            with fills_path.open("r", encoding="utf-8", newline="") as handle:
                fill_count = max(0, sum(1 for _ in csv.DictReader(handle)))
        stale_markets = []
        for market in preflight.get("markets") or []:
            reasons = list(market.get("blocking_reasons") or [])
            book_reason = ((market.get("book_audit") or {}).get("reason") or "")
            if book_reason:
                reasons.append(book_reason)
            if any("old" in str(reason).lower() or "stale" in str(reason).lower() for reason in reasons):
                stale_markets.append(market.get("market_id") or market.get("city") or "")
        if blocked or stale_markets:
            _add_issue(
                issues,
                issue_code="MM_PREFLIGHT_STALE_BOOKS",
                source="mm_run",
                market_id=",".join(sorted(set(stale_markets))) or "fleet",
                event_slug="",
                snapshot_id="",
                severity="medium",
                detail=f"{blocked} ticks blocked by preflight; stale markets={','.join(sorted(set(stale_markets))) or '-'}",
                metric=float(blocked),
            )
        runs.append({
            "run_folder": str(run_folder),
            "run_id": run_folder.name,
            "blocked_by_preflight_count": blocked,
            "fill_count": fill_count,
            "counts_toward_live_forward_gate": summary.get("counts_toward_live_forward_gate"),
            "stale_market_count": len(set(stale_markets)),
            "stale_markets": sorted(set(stale_markets)),
        })
    return {
        "available": bool(runs),
        "run_count": len(runs),
        "runs": runs,
        "issue_counts": dict(Counter(issue["issue_code"] for issue in issues)),
        "issues": issues,
    }


def _weak_performance_rows(payload: dict[str, Any], source_name: str, limit: int = 12) -> list[dict[str, Any]]:
    candidates = []
    for value in payload.values():
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            brier_delta = maybe_float(row.get("brier_delta"))
            logloss_delta = maybe_float(row.get("logloss_delta"))
            if brier_delta is None and logloss_delta is None:
                continue
            if (brier_delta is not None and brier_delta < 0) or (logloss_delta is not None and logloss_delta < 0):
                candidates.append({
                    "source": source_name,
                    "slot": row.get("hour_label") or row.get("slot_label") or row.get("regime") or row.get("hour") or row.get("slot"),
                    "brier_delta": brier_delta,
                    "logloss_delta": logloss_delta,
                    "winner_probability_gap": maybe_float(row.get("winner_catchup_gap") or row.get("partition_winner_probability_gap")),
                    "model_winner_probability": maybe_float(row.get("winner_model_probability") or row.get("partition_model_winner_probability")),
                    "market_winner_probability": maybe_float(row.get("winner_market_probability") or row.get("partition_market_winner_probability")),
                    "snapshots": maybe_int(row.get("snapshots") or row.get("partition_snapshots")),
                })
    return sorted(
        candidates,
        key=lambda row: (row.get("brier_delta") if row.get("brier_delta") is not None else 0.0),
    )[:limit]


def analyze_performance_artifacts(target_date: str, backtest_root: str | Path = DEFAULT_BACKTEST_ROOT) -> dict[str, Any]:
    root = Path(backtest_root)
    hourly = read_json(root / f"hourly_model_performance_{target_date}.json", default={}) or {}
    ten_minute = read_json(root / f"ten_minute_model_performance_{target_date}.json", default={}) or {}
    weak_rows = _weak_performance_rows(hourly, "hourly") + _weak_performance_rows(ten_minute, "ten_minute")
    issues: list[dict[str, Any]] = []
    for row in weak_rows[:20]:
        _add_issue(
            issues,
            issue_code="MODEL_WEAK_HOUR_SLOT",
            source=row["source"],
            market_id="fleet",
            severity="low",
            detail=f"slot {row.get('slot')} brier_delta={row.get('brier_delta')}",
            metric=row.get("brier_delta"),
        )
    return {
        "available": bool(hourly or ten_minute),
        "weak_rows": weak_rows[:12],
        "issue_counts": dict(Counter(issue["issue_code"] for issue in issues)),
        "issues": issues,
    }


def _parse_roadmap_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def roadmap_inventory(roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in item_files(roadmap_root):
        item = parse_item(path, root=roadmap_root)
        number = item.get("number")
        if number is None:
            continue
        rows[str(number)] = {
            "item": str(number),
            "title": item.get("title"),
            "status": item.get("status"),
            "date": item.get("date"),
            "disposition": item.get("disposition"),
            "path": item.get("path"),
            "active": bool(item.get("active")),
        }
    return rows


def _suggested_roadmap_title(issue_code: str) -> str:
    if issue_code in SUGGESTED_ROADMAP_TITLES:
        return SUGGESTED_ROADMAP_TITLES[issue_code]
    return "Post-Closure " + issue_code.lower().replace("_", " ").title() + " Recurrence"


def classify_roadmap_mapping(
    issue_code: str,
    roadmap_items: list[str],
    inventory: dict[str, dict[str, Any]],
    *,
    issue_date: str | date | None,
) -> dict[str, Any]:
    item_rows = [inventory.get(str(item)) or {"item": str(item), "status": "MISSING"} for item in roadmap_items]
    active_items = [row["item"] for row in item_rows if row.get("active")]
    parsed_issue_date = _parse_roadmap_date(issue_date)
    completed_dates = [
        parsed
        for parsed in (_parse_roadmap_date(row.get("date")) for row in item_rows if row.get("status") == "COMPLETE")
        if parsed is not None
    ]
    missing_items = [row["item"] for row in item_rows if row.get("status") == "MISSING"]
    suggested_title = ""

    if active_items:
        classification = "active_owner"
        detail = "issue has active OPEN/PARTIAL roadmap owner(s)"
    elif not roadmap_items:
        classification = "unmapped_no_owner"
        detail = "issue has no roadmap mapping"
        suggested_title = _suggested_roadmap_title(issue_code)
    elif missing_items:
        classification = "missing_mapped_item"
        detail = "mapped roadmap item file is missing"
        suggested_title = _suggested_roadmap_title(issue_code)
    elif parsed_issue_date and completed_dates and all(parsed_issue_date > completed for completed in completed_dates):
        classification = "post_closure_recurrence"
        detail = "issue date is after every completed mapped item and no active owner exists"
        suggested_title = _suggested_roadmap_title(issue_code)
    elif parsed_issue_date and completed_dates and parsed_issue_date <= max(completed_dates):
        classification = "historical_closure_evidence"
        detail = "issue date predates or belongs to the closure audit for completed mapped items"
    else:
        classification = "complete_owner_unverified_date"
        detail = "issue maps only to completed items but completion dates are unavailable"
        suggested_title = _suggested_roadmap_title(issue_code)

    return {
        "classification": classification,
        "classification_detail": detail,
        "roadmap_item_statuses": item_rows,
        "active_owner_items": active_items,
        "completed_item_dates": sorted(str(value) for value in completed_dates),
        "suggested_new_item_title": suggested_title,
    }


def roadmap_mappings(
    issue_counts: Counter,
    *,
    issue_date: str | date | None = None,
    roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT,
) -> list[dict[str, Any]]:
    inventory = roadmap_inventory(roadmap_root)
    rows = []
    for issue_code, count in sorted(issue_counts.items()):
        roadmap_items = ROADMAP_BY_ISSUE.get(issue_code, [])
        classification = classify_roadmap_mapping(
            issue_code,
            roadmap_items,
            inventory,
            issue_date=issue_date,
        )
        rows.append({
            "issue_code": issue_code,
            "count": count,
            "roadmap_items": roadmap_items,
            **classification,
        })
    return rows


def aggregate_afternoon_slice(market_reports: list[dict[str, Any]]) -> dict[str, Any]:
    slices = [
        report.get("afternoon_post_ramp_slice") or {}
        for report in market_reports
        if report.get("afternoon_post_ramp_slice")
    ]
    total_snapshots = sum(int(row.get("snapshot_count") or 0) for row in slices)
    weighted = []
    for row in slices:
        count = int(row.get("snapshot_count") or 0)
        if count <= 0:
            continue
        weighted.extend([row] * count)
    return {
        "hour_window": "15-18",
        "market_count": len([row for row in slices if int(row.get("snapshot_count") or 0) > 0]),
        "snapshot_count": total_snapshots,
        "mean_expected_high_bias": mean(row.get("mean_expected_high_bias") for row in weighted),
        "hot_share": mean(row.get("hot_share") for row in weighted),
        "mean_winner_probability": mean(row.get("mean_winner_probability") for row in weighted),
        "mean_effective_spread": mean(row.get("mean_effective_spread") for row in weighted),
        "mean_forecast_disagreement": mean(row.get("mean_forecast_disagreement") for row in weighted),
    }


def build_payload(
    target_date: str,
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    taker_run_folder: str | Path | None = None,
    taker_root: str | Path = DEFAULT_TAKER_ROOT,
    mm_root: str | Path = DEFAULT_MM_ROOT,
    backtest_root: str | Path = DEFAULT_BACKTEST_ROOT,
    labels_csv: str | Path | None = None,
    roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT,
    now: str | None = None,
) -> dict[str, Any]:
    folders = snapshot_folders_for_date(snapshots_root, target_date)
    market_reports = [analyze_snapshot_folder(folder) for folder in folders]
    afternoon_slice = aggregate_afternoon_slice(market_reports)
    taker = analyze_taker_run(taker_run_folder or discover_taker_run(target_date, taker_root), target_date)
    market_maker = analyze_mm_runs(target_date, mm_root)
    performance = analyze_performance_artifacts(target_date, backtest_root)

    all_issues: list[dict[str, Any]] = []
    for report in market_reports:
        all_issues.extend(report.get("issues") or [])
    all_issues.extend(taker.get("issues") or [])
    all_issues.extend(market_maker.get("issues") or [])
    all_issues.extend(performance.get("issues") or [])
    all_issues = sorted(
        all_issues,
        key=lambda row: (
            SEVERITY_RANK.get(row.get("severity"), 0),
            abs(maybe_float(row.get("metric")) or 0.0),
            row.get("issue_code") or "",
        ),
        reverse=True,
    )
    issue_counts = Counter(issue["issue_code"] for issue in all_issues)
    mappings = roadmap_mappings(issue_counts, issue_date=target_date, roadmap_root=roadmap_root)
    mapping_classification_counts = Counter(row.get("classification") or "unknown" for row in mappings)
    new_item_candidates = [
        {
            "issue_code": row.get("issue_code"),
            "count": row.get("count"),
            "suggested_title": row.get("suggested_new_item_title"),
            "classification": row.get("classification"),
            "detail": row.get("classification_detail"),
        }
        for row in mappings
        if row.get("suggested_new_item_title")
    ]
    snapshot_count = sum(report.get("snapshot_count") or 0 for report in market_reports)
    explanation_snapshot_count = sum(report.get("explanation_snapshot_count") or 0 for report in market_reports)
    price_history_snapshot_count = sum(report.get("price_history_snapshot_count") or 0 for report in market_reports)
    ws_event_snapshot_count = sum(report.get("ws_event_snapshot_count") or 0 for report in market_reports)
    status = "NO_DATA" if not market_reports and not taker.get("available") else ("ACTIONABLE" if issue_counts else "OK")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now or utc_now(),
        "target_date": target_date,
        "status": status,
        "snapshots_root": str(Path(snapshots_root)),
        "summary": {
            "status": status,
            "market_count": len(market_reports),
            "snapshot_count": snapshot_count,
            "issue_count": len(all_issues),
            "issue_counts": dict(issue_counts),
            "roadmap_mapping_classification_counts": dict(sorted(mapping_classification_counts.items())),
            "new_roadmap_item_candidate_count": len(new_item_candidates),
            "model_top_winner_rate": mean(report.get("model_top_winner_rate") for report in market_reports),
            "market_top_winner_rate": mean(report.get("market_top_winner_rate") for report in market_reports),
            "mean_final_model_probability": mean(report.get("mean_final_model_probability") for report in market_reports),
            "mean_final_market_probability": mean(report.get("mean_final_market_probability") for report in market_reports),
            "afternoon_post_ramp_slice": afternoon_slice,
            "explanation_snapshot_count": explanation_snapshot_count,
            "explanation_coverage_rate": (
                explanation_snapshot_count / snapshot_count
                if snapshot_count else None
            ),
            "explanation_sections": sorted({
                section
                for report in market_reports
                for section in (report.get("explanation_sections") or [])
            }),
            "price_history_snapshot_count": price_history_snapshot_count,
            "ws_event_snapshot_count": ws_event_snapshot_count,
            "market_event_snapshot_count": sum(report.get("market_event_snapshot_count") or 0 for report in market_reports),
            "price_history_coverage_rate": (
                price_history_snapshot_count / snapshot_count
                if snapshot_count else None
            ),
            "ws_event_coverage_rate": (
                ws_event_snapshot_count / snapshot_count
                if snapshot_count else None
            ),
            "taker_net_pnl_usdc": (taker.get("summary") or {}).get("net_pnl_usdc"),
            "mm_run_count": market_maker.get("run_count"),
        },
        "roadmap_mappings": mappings,
        "new_roadmap_item_candidates": new_item_candidates,
        "markets": [
            {key: value for key, value in report.items() if key not in {"issues", "worst_model_misses"}}
            for report in market_reports
        ],
        "worst_model_misses": [
            row
            for report in market_reports
            for row in report.get("worst_model_misses") or []
        ][:30],
        "issues": all_issues,
        "taker": taker,
        "market_maker": market_maker,
        "performance": performance,
    }
    liveness_labels_csv = Path(labels_csv) if labels_csv else Path(backtest_root) / DEFAULT_LABELS_CSV.name
    rerun_command = build_root_cause_rerun_command(
        target_date=target_date,
        snapshots_root=snapshots_root,
        taker_root=taker_root,
        mm_root=mm_root,
        backtest_root=backtest_root,
        labels_csv=liveness_labels_csv,
    )
    attach_scoring_liveness(
        payload,
        artifact_name="settled_day_root_cause",
        labels_csv=liveness_labels_csv,
        last_scored_target_date=target_date,
        rerun_command=rerun_command,
    )
    payload["summary"]["scoring_liveness_status"] = (payload.get("scoring_liveness") or {}).get("status")
    if (payload.get("scoring_liveness") or {}).get("status") == "BLOCK":
        payload["status"] = "BLOCK"
        payload["summary"]["status"] = "BLOCK"
    return payload


def _summary_rows(summary: dict[str, Any]) -> list[list[Any]]:
    return [
        ["Status", summary.get("status")],
        ["Markets", summary.get("market_count")],
        ["Snapshots", summary.get("snapshot_count")],
        ["Issues", summary.get("issue_count")],
        ["Model top winner rate", fmt_num(summary.get("model_top_winner_rate"), 3)],
        ["Market top winner rate", fmt_num(summary.get("market_top_winner_rate"), 3)],
        ["Final model probability", fmt_num(summary.get("mean_final_model_probability"), 3)],
        ["Final market probability", fmt_num(summary.get("mean_final_market_probability"), 3)],
        ["Explanation snapshots", summary.get("explanation_snapshot_count")],
        ["Explanation coverage", fmt_num(summary.get("explanation_coverage_rate"), 3)],
        ["Explanation sections", ", ".join(summary.get("explanation_sections") or []) or "-"],
        ["Price-history snapshots", summary.get("price_history_snapshot_count")],
        ["Price-history coverage", fmt_num(summary.get("price_history_coverage_rate"), 3)],
        ["WebSocket event snapshots", summary.get("ws_event_snapshot_count")],
        ["WebSocket event coverage", fmt_num(summary.get("ws_event_coverage_rate"), 3)],
        ["Taker net PnL USDC", fmt_signed(summary.get("taker_net_pnl_usdc"), 2)],
        ["MM run count", summary.get("mm_run_count")],
    ]


def render_report(payload: dict[str, Any], *, top_n: int = 12) -> str:
    liveness = payload.get("scoring_liveness") or {}
    lines = [
        f"# Settled-Day Root-Cause Report: {payload.get('target_date')}",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
        *markdown_table(["Metric", "Value"], _summary_rows(payload.get("summary") or {})),
        "",
    ]
    if liveness:
        lines += [
            "## Scoring Liveness",
            "",
            *markdown_table(
                ["Metric", "Value"],
                [
                    ["Status", liveness.get("status")],
                    ["Last scored target date", liveness.get("last_scored_target_date") or "-"],
                    ["Latest settled label date", liveness.get("latest_settled_label_date") or "-"],
                    ["Remediation", liveness.get("remediation_command") or "-"],
                ],
            ),
            "",
        ]
    issue_counts = (payload.get("summary") or {}).get("issue_counts") or {}
    lines += ["## Issue Counts", ""]
    afternoon = (payload.get("summary") or {}).get("afternoon_post_ramp_slice") or {}
    lines += ["## Afternoon Post-Ramp Slice", ""]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Hour window", afternoon.get("hour_window")],
            ["Markets", afternoon.get("market_count")],
            ["Snapshots", afternoon.get("snapshot_count")],
            ["Mean expected-high bias", fmt_signed(afternoon.get("mean_expected_high_bias"), 3)],
            ["Hot share", fmt_num(afternoon.get("hot_share"), 3)],
            ["Winner probability", fmt_num(afternoon.get("mean_winner_probability"), 3)],
            ["Effective spread", fmt_num(afternoon.get("mean_effective_spread"), 3)],
            ["Forecast disagreement", fmt_num(afternoon.get("mean_forecast_disagreement"), 3)],
        ],
    )
    lines.append("")

    if issue_counts:
        lines += markdown_table(
            ["Issue", "Count"],
            [[key, value] for key, value in sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)],
        )
    else:
        lines.append("No issue codes were detected.")
    lines.append("")

    mappings = payload.get("roadmap_mappings") or []
    lines += ["## Roadmap Mapping", ""]
    if mappings:
        lines += markdown_table(
            ["Issue", "Count", "Roadmap Items", "Active Owners", "Classification", "Suggested Item"],
            [
                [
                    row["issue_code"],
                    row["count"],
                    ",".join(row.get("roadmap_items") or []),
                    ",".join(row.get("active_owner_items") or []) or "-",
                    row.get("classification") or "-",
                    row.get("suggested_new_item_title") or "-",
                ]
                for row in mappings
            ],
        )
    else:
        lines.append("No roadmap mappings were triggered.")
    lines.append("")
    candidates = payload.get("new_roadmap_item_candidates") or []
    if candidates:
        lines += [
            "### Suggested New Roadmap Items",
            "",
            *markdown_table(
                ["Issue", "Count", "Classification", "Suggested Title"],
                [
                    [
                        row.get("issue_code"),
                        row.get("count"),
                        row.get("classification"),
                        row.get("suggested_title"),
                    ]
                    for row in candidates
                ],
            ),
            "",
        ]

    market_rows = []
    for row in payload.get("markets") or []:
        market_rows.append([
            row.get("market_id"),
            row.get("settlement_bucket"),
            row.get("settlement_unit"),
            row.get("snapshot_count"),
            fmt_num(row.get("model_top_winner_rate"), 3),
            fmt_num(row.get("market_top_winner_rate"), 3),
            fmt_num(row.get("mean_final_model_probability"), 3),
            fmt_num(row.get("mean_final_market_probability"), 3),
            row.get("explanation_snapshot_count"),
            ", ".join(row.get("explanation_sections") or []) or "-",
            row.get("price_history_snapshot_count"),
            row.get("ws_event_snapshot_count"),
            row.get("issue_counts"),
        ])
    lines += ["## Markets", ""]
    lines += markdown_table(
        [
            "Market",
            "Settle",
            "Unit",
            "Snapshots",
            "Model Top Hit",
            "Market Top Hit",
            "Model Winner P",
            "Market Winner P",
            "Explanation Snapshots",
            "Explanation Sections",
            "Price Hist Snapshots",
            "WS Event Snapshots",
            "Issues",
        ],
        market_rows[:top_n],
    )
    lines.append("")

    top_issues = payload.get("issues") or []
    lines += ["## Top Issue Evidence", ""]
    lines += markdown_table(
        ["Issue", "Source", "Market", "Snapshot", "Severity", "Metric", "Detail", "Roadmap"],
        [
            [
                row.get("issue_code"),
                row.get("source"),
                row.get("market_id"),
                row.get("snapshot_id"),
                row.get("severity"),
                compact(row.get("metric")),
                row.get("detail"),
                row.get("roadmap_items"),
            ]
            for row in top_issues[:top_n]
        ],
    )
    lines.append("")

    taker = payload.get("taker") or {}
    lines += ["## Taker Bot", ""]
    if taker.get("available"):
        summary = taker.get("summary") or {}
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Run folder", taker.get("run_folder")],
                ["Net PnL", fmt_signed(summary.get("net_pnl_usdc"), 2)],
                ["Filled orders", summary.get("filled_order_count")],
                ["Losing fills", summary.get("losing_fill_count")],
                ["Warm-tail losing fills", summary.get("warm_tail_loss_count")],
            ],
        )
        lines += ["", "### Worst Fills", ""]
        lines += markdown_table(
            ["Market", "Hour", "Range", "Fill", "Notional", "PnL", "Fair P", "Current Max"],
            [
                [
                    row.get("market_id"),
                    row.get("hour"),
                    row.get("range_label"),
                    fmt_num(row.get("fill_price"), 4),
                    fmt_num(row.get("fill_notional_usdc"), 2),
                    fmt_signed(row.get("net_pnl_usdc"), 2),
                    fmt_num(row.get("fair_probability"), 3),
                    row.get("current_max_disposition"),
                ]
                for row in taker.get("worst_fills") or []
            ],
        )
    else:
        lines.append("No taker run folder was found.")
    lines.append("")

    mm = payload.get("market_maker") or {}
    lines += ["## Market Maker", ""]
    if mm.get("available"):
        lines += markdown_table(
            ["Run", "Preflight Blocks", "Fills", "Counts Forward", "Stale Markets"],
            [
                [
                    row.get("run_id"),
                    row.get("blocked_by_preflight_count"),
                    row.get("fill_count"),
                    row.get("counts_toward_live_forward_gate"),
                    ",".join(row.get("stale_markets") or []),
                ]
                for row in mm.get("runs") or []
            ],
        )
    else:
        lines.append("No MM run folder was found.")
    lines.append("")

    performance = payload.get("performance") or {}
    lines += ["## Weak Performance Slots", ""]
    weak_rows = performance.get("weak_rows") or []
    if weak_rows:
        lines += markdown_table(
            ["Source", "Slot", "Brier Delta", "Logloss Delta", "Winner Gap", "Snapshots"],
            [
                [
                    row.get("source"),
                    row.get("slot"),
                    fmt_signed(row.get("brier_delta"), 4),
                    fmt_signed(row.get("logloss_delta"), 4),
                    fmt_signed(row.get("winner_probability_gap"), 4),
                    row.get("snapshots"),
                ]
                for row in weak_rows[:top_n]
            ],
        )
    else:
        lines.append("No weak slots were detected from available performance artifacts.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
    issues_out: str | Path = DEFAULT_ISSUES_OUT,
) -> tuple[Path, Path, Path]:
    json_out = Path(json_out)
    report_out = Path(report_out)
    issues_out = Path(issues_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    issues_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    fieldnames = [
        "issue_code",
        "source",
        "market_id",
        "event_slug",
        "snapshot_id",
        "severity",
        "metric",
        "detail",
        "roadmap_items",
        "roadmap_classification",
        "active_owner_items",
        "suggested_new_item_title",
    ]
    mapping_by_issue = {
        row.get("issue_code"): row
        for row in payload.get("roadmap_mappings") or []
    }
    with issues_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in payload.get("issues") or []:
            mapping = mapping_by_issue.get(row.get("issue_code")) or {}
            output = {key: row.get(key) for key in fieldnames}
            output["roadmap_classification"] = mapping.get("classification")
            output["active_owner_items"] = ",".join(mapping.get("active_owner_items") or [])
            output["suggested_new_item_title"] = mapping.get("suggested_new_item_title")
            writer.writerow(output)
    return json_out, report_out, issues_out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a settled-day root-cause report across model, taker, and MM logs.")
    parser.add_argument("--date", required=True, dest="target_date")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--taker-run-folder")
    parser.add_argument("--taker-root", default=str(DEFAULT_TAKER_ROOT))
    parser.add_argument("--mm-root", default=str(DEFAULT_MM_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--roadmap-root", default=str(DEFAULT_ROADMAP_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--issues-out", default=str(DEFAULT_ISSUES_OUT))
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        args.target_date,
        snapshots_root=args.snapshots_root,
        taker_run_folder=args.taker_run_folder,
        taker_root=args.taker_root,
        mm_root=args.mm_root,
        backtest_root=args.backtest_root,
        labels_csv=args.labels_csv,
        roadmap_root=args.roadmap_root,
    )
    json_out, report_out, issues_out = write_outputs(
        payload,
        args.json_out,
        args.report_out,
        args.issues_out,
    )
    print(f"Settled-day root-cause report: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    print(f"Issues written to {issues_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
