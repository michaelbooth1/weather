"""Trend analysis for saved model-market disagreement audit rows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.model_market_disagreement_audit import DEFAULT_LOG_PATH, read_audit_log, safe_float
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_market_disagreement_analysis")
DEFAULT_JSON_OUT = data_path("backtest", "model_market_disagreement_analysis.json")
DEFAULT_REPORT_OUT = data_path("backtest", "model_market_disagreement_analysis.md")


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
    """Keep the latest append-only revision per audit_key."""
    latest: dict[str, dict[str, Any]] = {}
    revisions: Counter[str] = Counter()
    for index, row in enumerate(rows):
        key = row.get("audit_key") or f"row-{index}"
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


def recommendation_for_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    direction = pattern.get("direction")
    market_id = pattern.get("market_id")
    label = pattern.get("range_label") or pattern.get("band_key")
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
            "avg_brier_gap_market_minus_model": pattern.get("avg_brier_gap_market_minus_model"),
            "sample_audit_keys": pattern.get("sample_audit_keys"),
        },
        "action": action,
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
) -> dict[str, Any]:
    raw_rows = read_audit_log(log_path)
    latest, revision_counts = latest_records(raw_rows)
    records = [enrich_record(row) for row in latest]
    resolved = [row for row in records if row.get("resolved")]
    pending = [row for row in records if not row.get("resolved")]
    market_closer = [row for row in resolved if row.get("closer_source") == "market"]
    model_closer = [row for row in resolved if row.get("closer_source") == "model"]
    patterns = priority_patterns(records, min_cases=min_pattern_cases)
    recommendations = [recommendation_for_pattern(row) for row in patterns[:20]]
    summary = {
        "audit_log_path": str(log_path),
        "raw_log_rows": len(raw_rows),
        "deduped_audit_snapshots": len(records),
        "superseded_revision_count": max(0, len(raw_rows) - len(records)),
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "model_closer_count": len(model_closer),
        "market_closer_count": len(market_closer),
        "tie_count": sum(1 for row in resolved if row.get("closer_source") == "tie"),
        "avg_gap_points": compact_float(mean(row.get("gap_points") for row in records)),
        "avg_brier_gap_market_minus_model": compact_float(mean(row.get("brier_gap_market_minus_model") for row in resolved)),
        "market_ids": sorted({str(row.get("market_id")) for row in records if row.get("market_id")}),
        "recommendation_count": len(recommendations),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_now_iso(),
        "summary": summary,
        "groups": {
            "by_market": group_rows(records, ("market_id",)),
            "by_market_direction": group_rows(records, ("market_id", "direction")),
            "by_band_direction": group_rows(records, ("market_id", "band_key", "range_label", "direction")),
            "by_local_hour": group_rows(records, ("captured_local_hour",)),
            "by_target_date": trend_rows(records),
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
        output.append([
            row.get("priority"),
            row.get("market_id"),
            row.get("range_label"),
            row.get("direction"),
            evidence.get("case_count"),
            evidence.get("market_closer_count"),
            evidence.get("pending_count"),
            row.get("action"),
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


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    groups = payload.get("groups") or {}
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
            ["Raw log rows", summary.get("raw_log_rows")],
            ["Resolved / pending", f"{summary.get('resolved_count')} / {summary.get('pending_count')}"],
            ["Model closer / market closer", f"{summary.get('model_closer_count')} / {summary.get('market_closer_count')}"],
            ["Average gap points", fmt_num(summary.get("avg_gap_points"), 2)],
            ["Average Brier gap market-model", fmt_signed(summary.get("avg_brier_gap_market_minus_model"), 4)],
            ["Markets", ", ".join(summary.get("market_ids") or [])],
            ["Recommendations", summary.get("recommendation_count")],
        ],
    ))
    lines.extend(["", "## Recommendations", ""])
    lines.extend(markdown_table(
        ["Priority", "Market", "Band", "Direction", "Cases", "Market closer", "Pending", "Action"],
        render_recommendation_rows(payload.get("recommendations") or []),
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


def write_outputs(payload: dict[str, Any], json_out: str | Path = DEFAULT_JSON_OUT, report_out: str | Path = DEFAULT_REPORT_OUT) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze saved model-market disagreement audit rows.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--min-pattern-cases", type=int, default=1)
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    payload = build_payload(
        log_path=args.log_path,
        min_pattern_cases=args.min_pattern_cases,
    )
    if not args.no_write:
        json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
        print(f"Wrote {json_out}")
        print(f"Wrote {report_out}")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
