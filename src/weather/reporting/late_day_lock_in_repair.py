"""Late-day lock-in saturation validation."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.hourly_model_performance import (
    DEFAULT_LABELS_CSV,
    DEFAULT_QUALITY_GRADES,
    DEFAULT_SNAPSHOTS_ROOT,
    discover_labeled_folders,
    score_folder,
    summarize_rows,
)
from weather.reporting.ten_minute_model_performance import (
    summarize_by_slot,
    ten_minute_checkpoint_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("late_day_lock_in_repair")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "late_day_lock_in_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "late_day_lock_in_repair_report.md"
DEFAULT_FACTOR_GRID = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MIN_CURRENT_IMPROVEMENT = 0.001
DEFAULT_TOP_SLOTS = 12


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def late_blocker_slots(report_path: str | Path, top_slots: int = DEFAULT_TOP_SLOTS) -> set[int]:
    payload = _read_json(report_path)
    by_slot = payload.get("by_slot") or []
    rows = [
        row for row in by_slot
        if int(row.get("time_slot_minute") or 0) >= 15 * 60 and int(row.get("n") or 0) >= 30
    ]
    selected = sorted(rows, key=lambda row: safe_float(row.get("brier_delta")) or 0.0)[: int(top_slots)]
    return {int(row["time_slot_minute"]) for row in selected if row.get("time_slot_minute") is not None}


def bin_covers_value(row: dict[str, Any], value: float | None) -> bool:
    if value is None:
        return False
    kind = row.get("bin_kind") or row.get("bin_type")
    lo = safe_float(row.get("bin_value_c"))
    hi = safe_float(row.get("bin_value_hi"))
    if lo is None:
        return False
    if kind == "lte":
        return value <= lo
    if kind == "gte":
        return value >= lo
    if hi is not None and hi != lo:
        return lo <= value <= hi
    return abs(value - lo) <= 0.51


def lock_in_candidate_rows(rows: list[dict[str, Any]], slots: set[int], factor: float) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("time_slot_minute"),
            )
        ].append(row)
    output = []
    for snapshot_rows in grouped.values():
        slot = snapshot_rows[0].get("time_slot_minute")
        if slot not in slots or float(factor) == 1.0:
            output.extend(dict(row) for row in snapshot_rows)
            continue
        weights = []
        for row in snapshot_rows:
            high_so_far = safe_float(row.get("feature_high_so_far"))
            match = bin_covers_value(row, high_so_far)
            weight = max(0.0, float(row.get("model_probability") or 0.0))
            if match:
                weight *= float(factor)
            weights.append(weight)
        total = sum(weights)
        for row, weight in zip(snapshot_rows, weights):
            item = dict(row)
            if total > 0:
                item["model_probability"] = weight / total
            output.append(item)
    return output


def split_dates(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    dates = sorted({row.get("target_date") for row in rows if row.get("target_date")})
    if len(dates) <= 1:
        return {"train_dates": dates, "eval_dates": dates}
    cut = max(1, len(dates) // 2)
    return {"train_dates": dates[:cut], "eval_dates": dates[cut:]}


def rows_for_dates(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [row for row in rows if row.get("target_date") in date_set]


def compare_summary(current_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    current = summarize_rows(current_rows) or {}
    candidate = summarize_rows(candidate_rows) or {}
    return {
        "n": candidate.get("n", current.get("n", 0)),
        "market_days": candidate.get("market_days", current.get("market_days")),
        "candidate_brier": candidate.get("model_brier"),
        "current_brier": current.get("model_brier"),
        "market_brier": current.get("market_brier"),
        "delta_vs_current": (
            candidate.get("model_brier") - current.get("model_brier")
            if candidate.get("model_brier") is not None and current.get("model_brier") is not None
            else None
        ),
        "delta_vs_market": (
            candidate.get("model_brier") - current.get("market_brier")
            if candidate.get("model_brier") is not None and current.get("market_brier") is not None
            else None
        ),
        "candidate_logloss": candidate.get("model_logloss"),
        "current_logloss": current.get("model_logloss"),
        "market_logloss": current.get("market_logloss"),
        "logloss_delta_vs_current": (
            candidate.get("model_logloss") - current.get("model_logloss")
            if candidate.get("model_logloss") is not None and current.get("model_logloss") is not None
            else None
        ),
        "logloss_delta_vs_market": (
            candidate.get("model_logloss") - current.get("market_logloss")
            if candidate.get("model_logloss") is not None and current.get("market_logloss") is not None
            else None
        ),
        "winner_candidate_probability": candidate.get("winner_model_probability"),
        "winner_current_probability": current.get("winner_model_probability"),
        "winner_market_probability": current.get("winner_market_probability"),
    }


def select_factor(rows: list[dict[str, Any]], slots: set[int], factors: tuple[float, ...]) -> dict[str, Any]:
    candidates = []
    for factor in factors:
        transformed = lock_in_candidate_rows(rows, slots, factor)
        summary = compare_summary(rows, transformed)
        candidates.append({"factor": float(factor), "summary": summary})
    best = min(
        candidates,
        key=lambda item: (
            safe_float(item["summary"].get("candidate_brier")) if item["summary"].get("candidate_brier") is not None else math.inf,
            abs(float(item["factor"]) - 1.0),
        ),
    )
    return {"selected_factor": best["factor"], "candidates": candidates, "selected_summary": best["summary"]}


def overlock_guardrail(rows: list[dict[str, Any]], slots: set[int], factor: float) -> dict[str, Any]:
    risky_groups = []
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("time_slot_minute") not in slots:
            continue
        grouped[(row.get("market_id"), row.get("target_date"), row.get("snapshot_id"))].append(row)
    for key, snapshot_rows in grouped.items():
        high_rows = [
            row for row in snapshot_rows
            if bin_covers_value(row, safe_float(row.get("feature_high_so_far")))
        ]
        if not high_rows:
            continue
        if not any(int(row.get("outcome") or 0) == 1 for row in high_rows):
            risky_groups.append(key)
    current_rows = [
        row for key in risky_groups for row in grouped.get(key, [])
    ]
    candidate_rows = lock_in_candidate_rows(current_rows, slots, factor)
    summary = compare_summary(current_rows, candidate_rows)
    return {
        "risky_snapshot_count": len(risky_groups),
        "summary": summary,
        "status": "PASS" if not risky_groups or (summary.get("delta_vs_current") or 0.0) <= 0.0 else "BLOCK",
    }


def build_scored_rows(
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
) -> list[dict[str, Any]]:
    labels, _skipped = discover_labeled_folders(
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        markets=[],
        start_date=None,
        end_date=None,
    )
    rows = []
    for item in labels:
        scored, _day = score_folder(item["folder"], item["label"])
        rows.extend(scored)
    return ten_minute_checkpoint_rows(rows)


def build_payload(
    *,
    ten_minute_report=DEFAULT_TEN_MINUTE_REPORT,
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    factor_grid=DEFAULT_FACTOR_GRID,
    top_slots=DEFAULT_TOP_SLOTS,
    market_tol=DEFAULT_MARKET_TOL,
    min_current_improvement=DEFAULT_MIN_CURRENT_IMPROVEMENT,
) -> dict[str, Any]:
    checkpoint_rows = build_scored_rows(labels_csv=labels_csv, snapshots_root=snapshots_root)
    slots = late_blocker_slots(ten_minute_report, top_slots=top_slots)
    target_rows = [row for row in checkpoint_rows if row.get("time_slot_minute") in slots]
    split = split_dates(target_rows)
    train_rows = rows_for_dates(target_rows, split["train_dates"])
    eval_rows = rows_for_dates(target_rows, split["eval_dates"])
    selection = select_factor(train_rows, slots, tuple(float(item) for item in factor_grid))
    factor = selection["selected_factor"]
    all_summary = compare_summary(target_rows, lock_in_candidate_rows(target_rows, slots, factor))
    eval_summary = compare_summary(eval_rows, lock_in_candidate_rows(eval_rows, slots, factor))
    guardrail = overlock_guardrail(target_rows, slots, factor)
    blockers = []
    if (safe_float(eval_summary.get("delta_vs_current")) or 0.0) > -float(min_current_improvement):
        blockers.append({
            "gate": "late_day_current_improvement",
            "detail": (
                f"eval Brier delta vs current {fmt_signed(eval_summary.get('delta_vs_current'))} "
                f"does not clear {-float(min_current_improvement):+.4f}"
            ),
        })
    if (safe_float(eval_summary.get("delta_vs_market")) or math.inf) > float(market_tol):
        blockers.append({
            "gate": "late_day_market_tolerance",
            "detail": f"eval Brier delta vs market {fmt_signed(eval_summary.get('delta_vs_market'))} exceeds +{float(market_tol):.4f}",
        })
    if guardrail.get("status") != "PASS":
        blockers.append({
            "gate": "overlock_guardrail",
            "detail": f"{guardrail.get('risky_snapshot_count')} high-so-far mismatch snapshot(s) regress under saturation",
        })
    slot_summaries = [
        row for row in summarize_by_slot(checkpoint_rows)
        if row.get("time_slot_minute") in slots
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "candidate_policy": {
            "variant_id": "late_day_high_stood_lock_in_saturation",
            "uses_market_features": False,
            "selected_factor": factor,
            "factor_grid": list(factor_grid),
            "slot_labels": [row.get("time_slot_label") for row in sorted(slot_summaries, key=lambda item: item["time_slot_minute"])],
            "features": [
                "feature_high_so_far",
                "feature_current_temp",
                "feature_forecast_gap",
                "feature_minutes_since_cutoff",
                "feature_forecast_disagreement",
                "feature_source_freshness_state",
            ],
        },
        "split": split,
        "train_selection": selection,
        "all_summary": all_summary,
        "eval_summary": eval_summary,
        "overlock_guardrail": guardrail,
        "slot_casebook": slot_summaries,
    }


def _summary_rows(payload: dict[str, Any]) -> list[list[Any]]:
    policy = payload.get("candidate_policy") or {}
    return [
        ["Status", payload.get("status")],
        ["Blockers", payload.get("blocker_count")],
        ["First blocker", (payload.get("first_blocker") or {}).get("gate") or "-"],
        ["Selected factor", policy.get("selected_factor")],
        ["Slots", ", ".join(policy.get("slot_labels") or [])],
        ["Train dates", ", ".join((payload.get("split") or {}).get("train_dates") or [])],
        ["Eval dates", ", ".join((payload.get("split") or {}).get("eval_dates") or [])],
    ]


def _metric_rows(rows: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    return [
        [
            label,
            summary.get("n"),
            summary.get("market_days"),
            fmt_num(summary.get("candidate_brier")),
            fmt_num(summary.get("current_brier")),
            fmt_num(summary.get("market_brier")),
            fmt_signed(summary.get("delta_vs_current")),
            fmt_signed(summary.get("delta_vs_market")),
            fmt_num(summary.get("winner_candidate_probability")),
            fmt_num(summary.get("winner_current_probability")),
            fmt_num(summary.get("winner_market_probability")),
        ]
        for label, summary in rows
    ]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Late-Day Lock-In Repair Validation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(["Field", "Value"], _summary_rows(payload))
    lines += ["", "## Candidate Metrics", ""]
    lines += markdown_table(
        [
            "Slice",
            "Rows",
            "Days",
            "Candidate Brier",
            "Current Brier",
            "Market Brier",
            "Delta Current",
            "Delta Market",
            "Winner Candidate P",
            "Winner Current P",
            "Winner Market P",
        ],
        _metric_rows([
            ("all selected slots", payload.get("all_summary") or {}),
            ("eval selected slots", payload.get("eval_summary") or {}),
            ("overlock guardrail", (payload.get("overlock_guardrail") or {}).get("summary") or {}),
        ]),
    )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Gate", "Detail"],
            [[row.get("gate"), row.get("detail")] for row in payload.get("blockers") or []],
        )
    lines += ["", "## Slot Casebook", ""]
    lines += markdown_table(
        ["Slot", "Rows", "Days", "Model Brier", "Market Brier", "Brier Delta", "Winner Model P", "Winner Market P"],
        [
            [
                row.get("time_slot_label"),
                row.get("n"),
                row.get("market_days"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_signed(row.get("brier_delta")),
                fmt_num(row.get("winner_model_probability")),
                fmt_num(row.get("winner_market_probability")),
            ]
            for row in payload.get("slot_casebook") or []
        ],
    )
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], json_out=DEFAULT_OUT, report_out=DEFAULT_REPORT) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate late-day lock-in saturation repair.")
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--factor-grid", default=",".join(str(item) for item in DEFAULT_FACTOR_GRID))
    parser.add_argument("--top-slots", type=int, default=DEFAULT_TOP_SLOTS)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--min-current-improvement", type=float, default=DEFAULT_MIN_CURRENT_IMPROVEMENT)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    return parser


def _parse_factor_grid(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in str(value).split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        ten_minute_report=args.ten_minute_report,
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        factor_grid=_parse_factor_grid(args.factor_grid),
        top_slots=args.top_slots,
        market_tol=args.market_tol,
        min_current_improvement=args.min_current_improvement,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    print(f"Late-day lock-in repair validation: {payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
