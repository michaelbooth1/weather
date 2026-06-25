"""Trend analysis for saved model-market disagreement audit rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.backtesting.settlement_ledger import DEFAULT_LABELS_CSV
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.model_market_disagreement_audit import (
    DEFAULT_LOG_PATH,
    append_audit_log,
    audit_key_for_row,
    clean_label,
    closer_source,
    read_audit_log,
    safe_float,
    settlement_outcome_for_row,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_market_disagreement_analysis")
REVIEW_QUEUE_SCHEMA_VERSION = schema_version("model_market_disagreement_review_queue")
DEFAULT_JSON_OUT = data_path("backtest", "model_market_disagreement_analysis.json")
DEFAULT_REPORT_OUT = data_path("backtest", "model_market_disagreement_analysis.md")
DEFAULT_REVIEW_QUEUE_OUT = data_path("backtest", "model_market_disagreement_review_queue.json")
DEFAULT_COMPLETE_LABEL_QUALITY_GRADES = ("complete", "manual_override")
REHYDRATION_EXCLUDED_STATUSES = {"excluded_missing_label", "excluded_partial_label"}


REPAIR_LANES = {
    "exact_band_winner_centering": {
        "repair_lane": "exact-band/winner-centering",
        "owner": "exact-band winner-centering repair",
        "roadmap_owner": "Items 70, 147, 230",
        "next_experiment": "audit_exact_band_winner_centering_replay",
        "experiment_artifact": "data/backtest/experiments/audit_exact_band_winner_centering_replay.json",
        "counts_toward_repair_evidence": True,
    },
    "warm_tail_dampening": {
        "repair_lane": "warm-tail dampening",
        "owner": "warm-tail spread repair",
        "roadmap_owner": "Items 195, 232, 236",
        "next_experiment": "audit_warm_tail_dampening_replay",
        "experiment_artifact": "data/backtest/experiments/audit_warm_tail_dampening_replay.json",
        "counts_toward_repair_evidence": True,
    },
    "source_state_reliability": {
        "repair_lane": "source-state reliability",
        "owner": "source-state reliability repair",
        "roadmap_owner": "Items 105, 136",
        "next_experiment": "audit_source_state_reliability_replay",
        "experiment_artifact": "data/backtest/experiments/audit_source_state_reliability_replay.json",
        "counts_toward_repair_evidence": True,
    },
    "market_specific_residual_repair": {
        "repair_lane": "market-specific residual repair",
        "owner": "market residual repair",
        "roadmap_owner": "Items 231, 264",
        "next_experiment": "audit_market_residual_repair_replay",
        "experiment_artifact": "data/backtest/experiments/audit_market_residual_repair_replay.json",
        "counts_toward_repair_evidence": True,
    },
    "settlement_watchlist": {
        "repair_lane": "settlement watchlist",
        "owner": "audit analysis operator",
        "roadmap_owner": "Item 271",
        "next_experiment": None,
        "experiment_artifact": None,
        "counts_toward_repair_evidence": False,
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def compact_float(value: Any, digits: int = 6) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return round(number, digits)


def mean(values) -> float | None:
    numbers = [float(value) for value in values if safe_float(value) is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def latest_records(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep the latest append-only revision per audited observation."""
    latest: dict[str, dict[str, Any]] = {}
    revisions: Counter[str] = Counter()
    for index, row in enumerate(rows):
        key = audit_key_for_row(row) or row.get("audit_key") or f"row-{index}"
        item = dict(row)
        item["_source_order"] = index
        revisions[key] += 1
        previous = latest.get(key)
        if previous is None:
            latest[key] = item
            continue
        prev_revision = int(previous.get("audit_revision") or 1)
        next_revision = int(item.get("audit_revision") or 1)
        if (next_revision, index) >= (prev_revision, int(previous.get("_source_order") or 0)):
            latest[key] = item
    for key, item in latest.items():
        item["revision_count"] = revisions[key]
        item.pop("_source_order", None)
    return list(latest.values()), dict(revisions)


def read_label_rows(labels_csv: str | Path = DEFAULT_LABELS_CSV) -> list[dict[str, Any]]:
    path = Path(labels_csv)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _label_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("target_date") or ""),
        str(row.get("finalized_at_utc") or row.get("generated_at_utc") or ""),
    )


def labels_by_event_slug(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=_label_sort_key):
        event_slug = str(row.get("event_slug") or "").strip()
        if event_slug:
            labels[event_slug] = dict(row)
    return labels


def _quality_grade(label: dict[str, Any] | None) -> str:
    return str((label or {}).get("quality_grade") or "").strip().casefold()


def label_is_complete(
    label: dict[str, Any] | None,
    *,
    complete_quality_grades: tuple[str, ...] = DEFAULT_COMPLETE_LABEL_QUALITY_GRADES,
) -> bool:
    if not label:
        return False
    allowed = {str(item).casefold() for item in complete_quality_grades}
    return _quality_grade(label) in allowed and safe_float(label.get("settlement_bucket")) is not None


def _target_label_summary(
    labels: list[dict[str, Any]],
    target_date: str | None,
    *,
    complete_quality_grades: tuple[str, ...],
) -> dict[str, Any]:
    target_labels = [
        row for row in labels
        if not target_date or str(row.get("target_date") or "")[:10] == str(target_date)[:10]
    ]
    quality_counts = Counter(_quality_grade(row) or "missing" for row in target_labels)
    complete_count = sum(
        1 for row in target_labels
        if label_is_complete(row, complete_quality_grades=complete_quality_grades)
    )
    partial_count = sum(1 for row in target_labels if row and not label_is_complete(
        row,
        complete_quality_grades=complete_quality_grades,
    ))
    return {
        "target_date": target_date,
        "label_count": len(target_labels),
        "complete_label_count": complete_count,
        "partial_label_count": partial_count,
        "quality_counts": dict(sorted(quality_counts.items())),
    }


def settlement_rehydration_excluded(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "") in REHYDRATION_EXCLUDED_STATUSES


def unresolved_for_rehydration(row: dict[str, Any]) -> bool:
    return row.get("fair_value_probability") is None


def _copy_with_label_fields(
    row: dict[str, Any],
    *,
    label: dict[str, Any] | None,
    status: str,
    generated_at_utc: str,
    reason: str,
) -> dict[str, Any]:
    output = dict(row)
    output["audited_at_utc"] = generated_at_utc
    output["run_id"] = f"settlement_rehydration_{generated_at_utc}"
    output["status"] = status
    output["settlement_rehydration_source"] = "market_day_labels_csv"
    output["settlement_rehydrated_at_utc"] = generated_at_utc
    output["settlement_rehydration_reason"] = reason
    output["settlement_rehydration_excluded"] = status in REHYDRATION_EXCLUDED_STATUSES
    output["settlement_label_available"] = bool(label)
    if label:
        output["settlement_bucket"] = compact_float(label.get("settlement_bucket"))
        output["settlement_unit"] = label.get("settlement_unit")
        output["settlement_source"] = label.get("settlement_source")
        output["settlement_quality_grade"] = label.get("quality_grade")
        output["winning_band"] = clean_label(label.get("winning_band"))
    return output


def _rehydrated_record_for_label(
    row: dict[str, Any],
    *,
    label: dict[str, Any] | None,
    generated_at_utc: str,
    complete_quality_grades: tuple[str, ...],
) -> dict[str, Any]:
    if not label:
        return _copy_with_label_fields(
            row,
            label=None,
            status="excluded_missing_label",
            generated_at_utc=generated_at_utc,
            reason="target-date audit row has no canonical market_day_labels.csv row",
        )
    if not label_is_complete(label, complete_quality_grades=complete_quality_grades):
        return _copy_with_label_fields(
            row,
            label=label,
            status="excluded_partial_label",
            generated_at_utc=generated_at_utc,
            reason=f"canonical label quality_grade={label.get('quality_grade') or 'missing'}",
        )

    outcome = settlement_outcome_for_row(row, label.get("settlement_bucket"))
    output = _copy_with_label_fields(
        row,
        label=label,
        status="resolved" if outcome is not None else "unresolved_after_label_rehydration",
        generated_at_utc=generated_at_utc,
        reason="joined to complete canonical market_day_labels.csv settlement",
    )
    fair = float(outcome) if outcome is not None else None
    model_probability = safe_float(output.get("model_probability"))
    market_yes = safe_float(output.get("market_yes"))
    closer, model_distance, market_distance = closer_source(
        model_probability=model_probability,
        market_yes=market_yes,
        fair_value_probability=fair,
    )
    output["fair_value_probability"] = compact_float(fair)
    output["fair_value_percent"] = compact_float(fair * 100.0 if fair is not None else None)
    output["closer_source"] = closer
    output["model_distance_points"] = model_distance
    output["market_distance_points"] = market_distance
    output["outcome"] = outcome
    return output


def _rehydration_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_key": before.get("audit_key"),
        "event_slug": before.get("event_slug"),
        "market_id": before.get("market_id"),
        "target_date": before.get("target_date"),
        "range_label": before.get("range_label"),
        "snapshot_id": before.get("snapshot_id"),
        "before_status": before.get("status"),
        "after_status": after.get("status"),
        "before_closer_source": before.get("closer_source"),
        "after_closer_source": after.get("closer_source"),
        "outcome": after.get("outcome"),
        "settlement_bucket": after.get("settlement_bucket"),
        "settlement_quality_grade": after.get("settlement_quality_grade"),
        "settlement_rehydration_reason": after.get("settlement_rehydration_reason"),
    }


def rehydrate_audit_log(
    *,
    log_path: str | Path = DEFAULT_LOG_PATH,
    labels_csv: str | Path = DEFAULT_LABELS_CSV,
    target_date: str | None = None,
    generated_at_utc: str | None = None,
    complete_quality_grades: tuple[str, ...] = DEFAULT_COMPLETE_LABEL_QUALITY_GRADES,
    write: bool = True,
) -> dict[str, Any]:
    """Append post-settlement revisions for unresolved target-date audit rows."""
    generated_at = generated_at_utc or utc_now_iso()
    raw_rows = read_audit_log(log_path)
    latest, _revision_counts = latest_records(raw_rows)
    labels = read_label_rows(labels_csv)
    by_slug = labels_by_event_slug(labels)
    target_text = str(target_date)[:10] if target_date else None
    target_latest = [
        row for row in latest
        if not target_text or str(row.get("target_date") or "")[:10] == target_text
    ]
    candidates = [row for row in target_latest if unresolved_for_rehydration(row)]

    planned_records = []
    planned_by_key = {}
    deltas = []
    missing_label_count = 0
    partial_label_count = 0
    unresolved_after_rehydrate_count = 0
    for row in candidates:
        label = by_slug.get(str(row.get("event_slug") or ""))
        if not label:
            missing_label_count += 1
        elif not label_is_complete(label, complete_quality_grades=complete_quality_grades):
            partial_label_count += 1
        updated = _rehydrated_record_for_label(
            row,
            label=label,
            generated_at_utc=generated_at,
            complete_quality_grades=complete_quality_grades,
        )
        if updated.get("status") == "unresolved_after_label_rehydration":
            unresolved_after_rehydrate_count += 1
        planned_records.append(updated)
        planned_by_key[updated.get("audit_key")] = updated
        deltas.append(_rehydration_delta(row, updated))

    if write:
        written, skipped = append_audit_log(planned_records, log_path)
    else:
        written, skipped = list(planned_records), []

    after_by_key = {}
    for row in target_latest:
        key = str(row.get("audit_key") or audit_key_for_row(row))
        after_by_key[key] = dict(row)
    for row in written:
        after_by_key[str(row.get("audit_key"))] = dict(row)
    for row in planned_records:
        if not write:
            after_by_key[str(row.get("audit_key"))] = dict(row)
    after_records = list(after_by_key.values())
    resolved_after = [row for row in after_records if row.get("fair_value_probability") is not None]
    excluded_after = [row for row in after_records if settlement_rehydration_excluded(row)]
    pending_after = [
        row for row in after_records
        if row.get("fair_value_probability") is None and not settlement_rehydration_excluded(row)
    ]
    remaining_complete_label_pending = []
    for row in pending_after:
        label = by_slug.get(str(row.get("event_slug") or ""))
        if label_is_complete(label, complete_quality_grades=complete_quality_grades):
            remaining_complete_label_pending.append(row)

    model_rehydrated = [
        row for row in planned_records
        if row.get("fair_value_probability") is not None and row.get("closer_source") == "model"
    ]
    market_rehydrated = [
        row for row in planned_records
        if row.get("fair_value_probability") is not None and row.get("closer_source") == "market"
    ]
    tie_rehydrated = [
        row for row in planned_records
        if row.get("fair_value_probability") is not None and row.get("closer_source") == "tie"
    ]
    blockers = []
    if remaining_complete_label_pending:
        blockers.append({
            "gate": "target_date_complete_label_rows_still_pending",
            "detail": (
                f"{len(remaining_complete_label_pending)} target-date disagreement row(s) "
                "remain unresolved despite complete canonical labels"
            ),
            "sample_audit_keys": [
                row.get("audit_key") for row in remaining_complete_label_pending[:10]
            ],
        })
    status = "BLOCK" if blockers else ("WARN" if (missing_label_count or partial_label_count) else "PASS")
    label_summary = _target_label_summary(
        labels,
        target_text,
        complete_quality_grades=complete_quality_grades,
    )
    return {
        "generated_at_utc": generated_at,
        "status": status,
        "target_date": target_text,
        "log_path": str(log_path),
        "labels_csv": str(labels_csv),
        "write_enabled": bool(write),
        "target_row_count": len(target_latest),
        "pending_before_count": len(candidates),
        "planned_revision_count": len(planned_records),
        "written_revision_count": len(written),
        "skipped_revision_count": len(skipped),
        "rehydrated_count": len([row for row in planned_records if row.get("fair_value_probability") is not None]),
        "model_closer_rehydrated_count": len(model_rehydrated),
        "market_closer_rehydrated_count": len(market_rehydrated),
        "tie_rehydrated_count": len(tie_rehydrated),
        "excluded_partial_label_count": partial_label_count,
        "excluded_missing_label_count": missing_label_count,
        "excluded_after_count": len(excluded_after),
        "resolved_after_count": len(resolved_after),
        "pending_after_count": len(pending_after),
        "unresolved_after_rehydrate_count": len(remaining_complete_label_pending),
        "label_summary": label_summary,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "gate": {
            "status": status,
            "blocker_count": len(blockers),
            "first_blocker": blockers[0] if blockers else {},
        },
        "interpretation_deltas": deltas,
        "written_audit_keys": [row.get("audit_key") for row in written],
        "skipped_audit_keys": [row.get("audit_key") for row in skipped],
        "planned_audit_keys": [row.get("audit_key") for row in planned_by_key.values()],
    }


def direction_for_record(row: dict[str, Any]) -> str:
    gap = safe_float(row.get("model_minus_market_points"))
    if gap is None:
        return "unknown"
    if gap > 0:
        return "model_higher_than_market"
    if gap < 0:
        return "market_higher_than_model"
    return "flat"


def enrich_record(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    direction = direction_for_record(item)
    item["direction"] = direction
    item["resolved"] = item.get("fair_value_probability") is not None
    item["settlement_rehydration_excluded"] = settlement_rehydration_excluded(item)
    item["pending_settlement"] = (
        not item["resolved"]
        and not item["settlement_rehydration_excluded"]
    )
    captured_local = parse_time(item.get("captured_at_local"))
    audited_at = parse_time(item.get("audited_at_utc"))
    item["captured_local_hour"] = captured_local.hour if captured_local else None
    item["captured_local_date"] = captured_local.date().isoformat() if captured_local else None
    item["audited_date"] = audited_at.date().isoformat() if audited_at else None
    model = safe_float(item.get("model_probability"))
    market = safe_float(item.get("market_yes"))
    fair = safe_float(item.get("fair_value_probability"))
    if model is not None and market is not None and fair is not None:
        model_brier = (model - fair) ** 2
        market_brier = (market - fair) ** 2
        item["model_brier"] = compact_float(model_brier)
        item["market_brier"] = compact_float(market_brier)
        item["brier_gap_market_minus_model"] = compact_float(market_brier - model_brier)
    else:
        item["model_brier"] = None
        item["market_brier"] = None
        item["brier_gap_market_minus_model"] = None
    return item


def summarize_group(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> dict[str, Any]:
    first = rows[0] if rows else {}
    resolved = [row for row in rows if row.get("resolved")]
    pending = [row for row in rows if not row.get("resolved")]
    market_closer = [row for row in resolved if row.get("closer_source") == "market"]
    model_closer = [row for row in resolved if row.get("closer_source") == "model"]
    ties = [row for row in resolved if row.get("closer_source") == "tie"]
    return {
        **{field: first.get(field) for field in key_fields},
        "case_count": len(rows),
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "market_closer_count": len(market_closer),
        "model_closer_count": len(model_closer),
        "tie_count": len(ties),
        "market_closer_rate": compact_float(len(market_closer) / len(resolved) if resolved else None),
        "model_closer_rate": compact_float(len(model_closer) / len(resolved) if resolved else None),
        "avg_gap_points": compact_float(mean(row.get("gap_points") for row in rows)),
        "max_gap_points": compact_float(max((safe_float(row.get("gap_points")) or 0.0) for row in rows) if rows else None),
        "avg_model_minus_market_points": compact_float(mean(row.get("model_minus_market_points") for row in rows)),
        "avg_model_distance_points": compact_float(mean(row.get("model_distance_points") for row in resolved)),
        "avg_market_distance_points": compact_float(mean(row.get("market_distance_points") for row in resolved)),
        "avg_brier_gap_market_minus_model": compact_float(mean(row.get("brier_gap_market_minus_model") for row in resolved)),
        "sample_audit_keys": [row.get("audit_key") for row in rows[:5]],
        "sample_range_labels": sorted({str(row.get("range_label") or "") for row in rows if row.get("range_label")})[:5],
    }


def group_rows(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        groups[key].append(row)
    summaries = [summarize_group(group, key_fields) for group in groups.values()]
    summaries.sort(key=lambda row: (
        row.get("market_closer_count", 0),
        row.get("pending_count", 0),
        row.get("case_count", 0),
        row.get("max_gap_points") or 0.0,
    ), reverse=True)
    return summaries


def priority_patterns(records: list[dict[str, Any]], *, min_cases: int = 1) -> list[dict[str, Any]]:
    patterns = group_rows(records, ("market_id", "band_key", "range_label", "direction"))
    output = []
    for row in patterns:
        if row["case_count"] < int(min_cases):
            continue
        if row["market_closer_count"] <= 0 and row["pending_count"] <= 0:
            continue
        priority = "P1"
        if row["market_closer_count"] >= max(2, int(min_cases)):
            priority = "P0"
        elif row["pending_count"] and (row.get("max_gap_points") or 0.0) >= 65.0:
            priority = "P1"
        elif row["pending_count"]:
            priority = "P2"
        row = dict(row)
        row["priority"] = priority
        output.append(row)
    output.sort(key=lambda row: (
        {"P0": 3, "P1": 2, "P2": 1}.get(row.get("priority"), 0),
        row.get("market_closer_count", 0),
        row.get("pending_count", 0),
        row.get("max_gap_points") or 0.0,
    ), reverse=True)
    return output


def _lane_with_overrides(lane_id: str, **overrides) -> dict[str, Any]:
    route = dict(REPAIR_LANES[lane_id])
    route["route_id"] = lane_id
    route.update({key: value for key, value in overrides.items() if value is not None})
    route["automatic_model_or_trading_change_allowed"] = False
    return route


def route_for_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    """Map an audit pattern to the operator-owned repair lane."""
    if int(pattern.get("market_closer_count") or 0) <= 0:
        return _lane_with_overrides(
            "settlement_watchlist",
            evidence_policy="Pending settlement only; do not count toward repair evidence yet.",
        )
    direction = pattern.get("direction")
    band_key = str(pattern.get("band_key") or "")
    market_id = str(pattern.get("market_id") or "market")
    if direction == "market_higher_than_model" and band_key.startswith("eq:"):
        return _lane_with_overrides(
            "exact_band_winner_centering",
            evidence_policy="Resolved market-closer exact-band evidence; route to winner-centering replay.",
        )
    if direction == "model_higher_than_market":
        return _lane_with_overrides(
            "warm_tail_dampening",
            evidence_policy="Resolved market-closer over-allocation evidence; route to warm-tail/spread replay.",
        )
    if direction == "market_higher_than_model":
        return _lane_with_overrides(
            "source_state_reliability",
            evidence_policy=(
                "Resolved market-closer under-allocation evidence; check source-state/current-high "
                "support before candidate changes."
            ),
        )
    experiment = f"audit_{market_id}_residual_repair_replay"
    return _lane_with_overrides(
        "market_specific_residual_repair",
        owner=f"{market_id} market residual repair",
        next_experiment=experiment,
        experiment_artifact=f"data/backtest/experiments/{experiment}.json",
        evidence_policy=f"Resolved market-closer evidence for {market_id}; route to market-specific residual repair.",
    )


def review_queue_id(recommendation: dict[str, Any]) -> str:
    evidence = recommendation.get("evidence") or {}
    source = "|".join([
        str(recommendation.get("category") or ""),
        str(recommendation.get("market_id") or ""),
        str(recommendation.get("range_label") or ""),
        str(recommendation.get("direction") or ""),
        ",".join(str(key) for key in evidence.get("sample_audit_keys") or []),
    ])
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    market_id = str(recommendation.get("market_id") or "market").replace(" ", "-")
    return f"audit-review-{market_id}-{digest}"


def recommendation_for_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    direction = pattern.get("direction")
    market_id = pattern.get("market_id")
    label = pattern.get("range_label") or pattern.get("band_key")
    route = route_for_pattern(pattern)
    if pattern.get("market_closer_count", 0) > 0:
        if direction == "market_higher_than_model":
            action = (
                "Investigate under-allocation on market-favored bands: replay the saved snapshots, "
                "check source freshness/current-high support, and test a no-leak exact-band/winner-centering repair."
            )
        elif direction == "model_higher_than_market":
            action = (
                "Investigate model over-allocation on market-rejected bands: compare forecast/current-high support, "
                "then test dampening or wider distribution spread on this slice."
            )
        else:
            action = "Review this resolved market-closer disagreement slice before changing calibration."
        category = "model_repair_candidate"
    else:
        action = "Keep on the settlement watchlist; rerun the audit after the market settles before counting it as evidence."
        category = "settlement_watchlist"
    return {
        "priority": pattern.get("priority"),
        "category": category,
        "market_id": market_id,
        "range_label": label,
        "direction": direction,
        "evidence": {
            "case_count": pattern.get("case_count"),
            "resolved_count": pattern.get("resolved_count"),
            "pending_count": pattern.get("pending_count"),
            "market_closer_count": pattern.get("market_closer_count"),
            "model_closer_count": pattern.get("model_closer_count"),
            "avg_brier_gap_market_minus_model": pattern.get("avg_brier_gap_market_minus_model"),
            "sample_audit_keys": pattern.get("sample_audit_keys"),
        },
        "route": route,
        "action": action,
    }


def operator_review_queue(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for recommendation in payload.get("recommendations") or []:
        route = recommendation.get("route") or {}
        evidence = recommendation.get("evidence") or {}
        queue_id = review_queue_id(recommendation)
        ready_for_repair = recommendation.get("category") == "model_repair_candidate"
        rows.append({
            "review_queue_id": queue_id,
            "status": "READY_FOR_OPERATOR_REVIEW" if ready_for_repair else "WATCHLIST_PENDING_SETTLEMENT",
            "priority": recommendation.get("priority"),
            "category": recommendation.get("category"),
            "market_id": recommendation.get("market_id"),
            "range_label": recommendation.get("range_label"),
            "direction": recommendation.get("direction"),
            "repair_lane": route.get("repair_lane"),
            "owner": route.get("owner"),
            "roadmap_owner": route.get("roadmap_owner"),
            "next_experiment": route.get("next_experiment"),
            "experiment_artifact": route.get("experiment_artifact"),
            "counts_toward_repair_evidence": bool(route.get("counts_toward_repair_evidence")),
            "automatic_model_or_trading_change_allowed": False,
            "case_count": evidence.get("case_count"),
            "resolved_count": evidence.get("resolved_count"),
            "pending_count": evidence.get("pending_count"),
            "market_closer_count": evidence.get("market_closer_count"),
            "model_closer_count": evidence.get("model_closer_count"),
            "sample_audit_keys": evidence.get("sample_audit_keys") or [],
            "suggested_backlog_note": (
                f"{recommendation.get('priority')} {recommendation.get('market_id')} "
                f"{recommendation.get('range_label')} {recommendation.get('direction')} -> "
                f"{route.get('repair_lane')} ({route.get('roadmap_owner')}). "
                f"{route.get('evidence_policy')}"
            ),
            "action": recommendation.get("action"),
        })
    return {
        "schema_version": REVIEW_QUEUE_SCHEMA_VERSION,
        "generated_at_utc": payload.get("generated_at_utc"),
        "source_schema_version": payload.get("schema_version"),
        "source_audit_log_path": (payload.get("summary") or {}).get("audit_log_path"),
        "policy": {
            "pending_cases_count_as_repair_evidence": False,
            "automatic_model_or_trading_change_allowed": False,
            "automatic_trade_policy_change_allowed": False,
        },
        "rows": rows,
    }


def trend_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = group_rows(records, ("target_date",))
    rows.sort(key=lambda row: str(row.get("target_date") or ""))
    return rows


def build_payload(
    *,
    log_path: str | Path = DEFAULT_LOG_PATH,
    min_pattern_cases: int = 1,
    generated_at_utc: str | None = None,
    rehydration_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or utc_now_iso()
    raw_rows = read_audit_log(log_path)
    latest, revision_counts = latest_records(raw_rows)
    records = [enrich_record(row) for row in latest]
    excluded = [row for row in records if row.get("settlement_rehydration_excluded")]
    active_records = [row for row in records if not row.get("settlement_rehydration_excluded")]
    resolved = [row for row in active_records if row.get("resolved")]
    pending = [row for row in active_records if row.get("pending_settlement")]
    market_closer = [row for row in resolved if row.get("closer_source") == "market"]
    model_closer = [row for row in resolved if row.get("closer_source") == "model"]
    patterns = priority_patterns(active_records, min_cases=min_pattern_cases)
    recommendations = [recommendation_for_pattern(row) for row in patterns[:20]]
    ready_for_review_count = sum(1 for row in recommendations if row.get("category") == "model_repair_candidate")
    watchlist_recommendation_count = sum(1 for row in recommendations if row.get("category") == "settlement_watchlist")
    summary = {
        "audit_log_path": str(log_path),
        "raw_log_rows": len(raw_rows),
        "deduped_audit_snapshots": len(records),
        "active_audit_snapshots": len(active_records),
        "superseded_revision_count": max(0, len(raw_rows) - len(records)),
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "settlement_rehydration_excluded_count": len(excluded),
        "model_closer_count": len(model_closer),
        "market_closer_count": len(market_closer),
        "tie_count": sum(1 for row in resolved if row.get("closer_source") == "tie"),
        "avg_gap_points": compact_float(mean(row.get("gap_points") for row in active_records)),
        "avg_brier_gap_market_minus_model": compact_float(mean(row.get("brier_gap_market_minus_model") for row in resolved)),
        "market_ids": sorted({str(row.get("market_id")) for row in active_records if row.get("market_id")}),
        "recommendation_count": len(recommendations),
        "ready_for_operator_review_count": ready_for_review_count,
        "settlement_watchlist_recommendation_count": watchlist_recommendation_count,
        "rehydration_status": (rehydration_summary or {}).get("status"),
        "rehydrated_count": (rehydration_summary or {}).get("rehydrated_count"),
        "rehydration_unresolved_after_count": (rehydration_summary or {}).get("unresolved_after_rehydrate_count"),
        "rehydration_excluded_partial_label_count": (rehydration_summary or {}).get("excluded_partial_label_count"),
        "rehydration_excluded_missing_label_count": (rehydration_summary or {}).get("excluded_missing_label_count"),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "summary": summary,
        "rehydration": rehydration_summary or {},
        "groups": {
            "by_market": group_rows(active_records, ("market_id",)),
            "by_market_direction": group_rows(active_records, ("market_id", "direction")),
            "by_band_direction": group_rows(active_records, ("market_id", "band_key", "range_label", "direction")),
            "by_local_hour": group_rows(active_records, ("captured_local_hour",)),
            "by_target_date": trend_rows(active_records),
        },
        "priority_patterns": patterns,
        "recommendations": recommendations,
        "pending_watchlist": sorted(
            pending,
            key=lambda row: (row.get("gap_points") or 0.0, row.get("audited_at_utc") or ""),
            reverse=True,
        )[:50],
        "resolved_market_closer_examples": sorted(
            market_closer,
            key=lambda row: (abs(row.get("brier_gap_market_minus_model") or 0.0), row.get("gap_points") or 0.0),
            reverse=True,
        )[:50],
        "revision_counts": revision_counts,
    }
    payload["operator_review_queue"] = operator_review_queue(payload)
    return payload


def render_group_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    output = []
    for row in rows[:limit]:
        label = row.get("range_label") or row.get("band_key") or row.get("market_id") or row.get("target_date") or row.get("captured_local_hour")
        output.append([
            row.get("market_id") or "-",
            label,
            row.get("direction") or "-",
            row.get("case_count"),
            row.get("resolved_count"),
            row.get("pending_count"),
            row.get("model_closer_count"),
            row.get("market_closer_count"),
            fmt_num(row.get("avg_gap_points"), 2),
            fmt_signed(row.get("avg_brier_gap_market_minus_model"), 4),
        ])
    return output


def render_recommendation_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    output = []
    for row in rows[:limit]:
        evidence = row.get("evidence") or {}
        route = row.get("route") or {}
        output.append([
            row.get("priority"),
            row.get("market_id"),
            row.get("range_label"),
            row.get("direction"),
            evidence.get("case_count"),
            evidence.get("market_closer_count"),
            evidence.get("pending_count"),
            route.get("repair_lane"),
            route.get("roadmap_owner"),
            row.get("action"),
        ])
    return output


def render_review_queue_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    output = []
    for row in rows[:limit]:
        output.append([
            row.get("review_queue_id"),
            row.get("status"),
            row.get("priority"),
            row.get("market_id"),
            row.get("range_label"),
            row.get("repair_lane"),
            row.get("roadmap_owner"),
            row.get("counts_toward_repair_evidence"),
            row.get("automatic_model_or_trading_change_allowed"),
            row.get("next_experiment") or "-",
        ])
    return output


def render_pending_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    output = []
    for row in rows[:limit]:
        output.append([
            row.get("market_id"),
            row.get("target_date"),
            row.get("range_label"),
            row.get("direction"),
            fmt_signed(row.get("model_minus_market_points"), 2),
            fmt_num(row.get("gap_points"), 2),
            row.get("audited_at_utc"),
        ])
    return output


def render_rehydration_delta_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[list[Any]]:
    output = []
    for row in rows[:limit]:
        output.append([
            row.get("market_id"),
            row.get("target_date"),
            row.get("range_label"),
            row.get("before_status"),
            row.get("after_status"),
            row.get("before_closer_source"),
            row.get("after_closer_source"),
            row.get("settlement_quality_grade"),
        ])
    return output


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    groups = payload.get("groups") or {}
    rehydration = payload.get("rehydration") or {}
    rehydration_gate = rehydration.get("gate") or {}
    lines = [
        "# Model-Market Disagreement Audit Analysis",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Audit snapshots", summary.get("deduped_audit_snapshots")],
            ["Active audit snapshots", summary.get("active_audit_snapshots")],
            ["Raw log rows", summary.get("raw_log_rows")],
            ["Resolved / pending", f"{summary.get('resolved_count')} / {summary.get('pending_count')}"],
            ["Rehydration excluded", summary.get("settlement_rehydration_excluded_count")],
            ["Model closer / market closer", f"{summary.get('model_closer_count')} / {summary.get('market_closer_count')}"],
            ["Rehydration gate", summary.get("rehydration_status") or "-"],
            ["Average gap points", fmt_num(summary.get("avg_gap_points"), 2)],
            ["Average Brier gap market-model", fmt_signed(summary.get("avg_brier_gap_market_minus_model"), 4)],
            ["Markets", ", ".join(summary.get("market_ids") or [])],
            ["Recommendations", summary.get("recommendation_count")],
            ["Ready for operator review", summary.get("ready_for_operator_review_count")],
            ["Settlement watchlist recommendations", summary.get("settlement_watchlist_recommendation_count")],
        ],
    ))
    if rehydration:
        lines.extend(["", "## Settlement Rehydration", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Target date", rehydration.get("target_date") or "-"],
                ["Gate", rehydration_gate.get("status") or rehydration.get("status") or "-"],
                ["Target rows", rehydration.get("target_row_count")],
                ["Pending before", rehydration.get("pending_before_count")],
                ["Rehydrated", rehydration.get("rehydrated_count")],
                ["Model / market closer", f"{rehydration.get('model_closer_rehydrated_count')} / {rehydration.get('market_closer_rehydrated_count')}"],
                ["Excluded partial / missing", f"{rehydration.get('excluded_partial_label_count')} / {rehydration.get('excluded_missing_label_count')}"],
                ["Pending after", rehydration.get("pending_after_count")],
                ["Unresolved complete-label rows", rehydration.get("unresolved_after_rehydrate_count")],
                ["Written revisions", rehydration.get("written_revision_count")],
            ],
        ))
        lines.extend(["", "## Rehydration Interpretation Changes", ""])
        lines.extend(markdown_table(
            [
                "Market",
                "Target",
                "Band",
                "Before status",
                "After status",
                "Before closer",
                "After closer",
                "Label quality",
            ],
            render_rehydration_delta_rows(rehydration.get("interpretation_deltas") or []),
        ))
    lines.extend(["", "## Recommendations", ""])
    lines.extend(markdown_table(
        ["Priority", "Market", "Band", "Direction", "Cases", "Market closer", "Pending", "Repair lane", "Roadmap owner", "Action"],
        render_recommendation_rows(payload.get("recommendations") or []),
    ))
    review_queue = payload.get("operator_review_queue") or {}
    lines.extend(["", "## Operator Review Queue", ""])
    lines.extend(markdown_table(
        [
            "Review id",
            "Status",
            "Priority",
            "Market",
            "Band",
            "Repair lane",
            "Roadmap owner",
            "Counts as evidence",
            "Auto-change allowed",
            "Next experiment",
        ],
        render_review_queue_rows(review_queue.get("rows") or []),
    ))
    lines.extend(["", "## Priority Patterns", ""])
    lines.extend(markdown_table(
        ["Market", "Slice", "Direction", "Cases", "Resolved", "Pending", "Model closer", "Market closer", "Avg gap", "Brier gap"],
        render_group_rows(payload.get("priority_patterns") or []),
    ))
    lines.extend(["", "## By Market And Direction", ""])
    lines.extend(markdown_table(
        ["Market", "Slice", "Direction", "Cases", "Resolved", "Pending", "Model closer", "Market closer", "Avg gap", "Brier gap"],
        render_group_rows(groups.get("by_market_direction") or []),
    ))
    lines.extend(["", "## Pending Watchlist", ""])
    lines.extend(markdown_table(
        ["Market", "Target", "Band", "Direction", "Model-market pts", "Gap pts", "Audited"],
        render_pending_rows(payload.get("pending_watchlist") or []),
    ))
    lines.append("")
    return "\n".join(lines)


def write_review_queue(payload: dict[str, Any], queue_out: str | Path = DEFAULT_REVIEW_QUEUE_OUT) -> Path:
    queue_path = Path(queue_out)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue = payload.get("operator_review_queue") or operator_review_queue(payload)
    queue_path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return queue_path


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
    review_queue_out: str | Path | None = None,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    if review_queue_out:
        write_review_queue(payload, review_queue_out)
    return json_path, report_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze saved model-market disagreement audit rows.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--target-date", default="")
    parser.add_argument("--rehydrate", action="store_true")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--review-queue-out", default=str(DEFAULT_REVIEW_QUEUE_OUT))
    parser.add_argument("--min-pattern-cases", type=int, default=1)
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    rehydration = None
    if args.rehydrate:
        if not args.target_date:
            raise SystemExit("--target-date is required with --rehydrate")
        rehydration = rehydrate_audit_log(
            log_path=args.log_path,
            labels_csv=args.labels_csv,
            target_date=args.target_date,
            write=not args.no_write,
        )
    payload = build_payload(
        log_path=args.log_path,
        min_pattern_cases=args.min_pattern_cases,
        rehydration_summary=rehydration,
    )
    if not args.no_write:
        json_out, report_out = write_outputs(payload, args.json_out, args.report_out, review_queue_out=args.review_queue_out)
        print(f"Wrote {json_out}")
        print(f"Wrote {report_out}")
        if args.review_queue_out:
            print(f"Wrote {args.review_queue_out}")
        if rehydration:
            print(f"Rehydration gate: {rehydration.get('status')}")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
