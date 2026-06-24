"""Item 224 no-market Seattle warm-support repair candidate."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.bottom_location_winner_centering import parse_time_slot
from weather.reporting.formatting import fmt_num, markdown_table
from weather.reporting.predawn_weak_slot_repair import weak_slots_from_report


SCHEMA_VERSION = "item224_no_market_seattle_warm_support_repair_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_INPUT_ROWS = DEFAULT_BACKTEST_ROOT / "item224_no_market_model_frontier_rf_depth8_w1_rows.csv"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "current_max_trust_ten_minute_performance.json"
DEFAULT_OUT_ROWS = DEFAULT_BACKTEST_ROOT / "item224_no_market_seattle_warm_support_repair_rows.csv"
DEFAULT_OUT_JSON = DEFAULT_BACKTEST_ROOT / "item224_no_market_seattle_warm_support_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item224_no_market_seattle_warm_support_repair_report.md"

VARIANT_ID = "item224_no_market_seattle_warm_support_repair_v0_1"
VARIANT_FAMILY = "bottom_no_market_seattle_warm_support_repair"
EXCLUDED_LABEL_OR_MARKET_FEATURES = ("outcome", "market_yes", "settlement_distance_bucket")
METADATA_DEFAULTS = {
    "variant_id": VARIANT_ID,
    "variant_family": VARIANT_FAMILY,
    "uses_market_features": "false",
    "is_control": "false",
    "claim_lane": "item224_no_market_location_repair_candidate",
    "counts_toward_weather_model_promotion": "false",
    "quote_risk_eligible": "false",
    "quote_risk_gate_reason": "same_corpus_location_gate_candidate_not_quote_evidence",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("market_id") or "").strip().lower(),
        str(row.get("target_date") or "").strip(),
        str(row.get("snapshot_id") or "").strip(),
    )


def bin_value(row: dict[str, Any]) -> float | None:
    return finite_float(row.get("bin_value") or row.get("bin_value_c"))


def is_eq_row(row: dict[str, Any]) -> bool:
    return str(row.get("bin_type") or "").strip().lower() == "eq"


def cutoff_regime(rows: list[dict[str, Any]]) -> str:
    values = [str(row.get("cutoff_regime") or "").strip().lower() for row in rows]
    values = [value for value in values if value]
    return Counter(values).most_common(1)[0][0] if values else "unknown"


def support_center(eq_rows: list[dict[str, Any]]) -> float | None:
    values = [value for value in (bin_value(row) for row in eq_rows) if value is not None]
    return sum(values) / len(values) if values else None


def group_time_slot(rows: list[dict[str, Any]]) -> int | None:
    for row in rows:
        slot = parse_time_slot(row.get("captured_at_local"))
        if slot is not None:
            return slot
    return None


def repair_rule_for_group(
    group_rows: list[dict[str, Any]],
    weak_slots: set[int],
) -> dict[str, Any] | None:
    market_id, _target_date, _snapshot_id = row_key(group_rows[0])
    if market_id != "seattle":
        return None
    eq_rows = sorted(
        [row for row in group_rows if is_eq_row(row) and bin_value(row) is not None],
        key=lambda row: float(bin_value(row) or 0.0),
    )
    if not eq_rows:
        return None
    center = support_center(eq_rows)
    regime = cutoff_regime(eq_rows)
    slot = group_time_slot(eq_rows)
    is_weak_slot = slot in weak_slots if slot is not None else False
    if regime not in {"early", "midday"} or center is None:
        return None

    if 69.5 <= center <= 70.5:
        if regime == "early" and is_weak_slot:
            return {
                "rule_id": "seattle_center70_weak_plus2_full",
                "support_center": center,
                "step": 2,
                "alpha": 1.0,
                "reason": "Seattle weak-slot center-70 support underweights warmer EQ bands",
            }
        if regime == "early":
            return {
                "rule_id": "seattle_center70_early_plus1_half",
                "support_center": center,
                "step": 1,
                "alpha": 0.5,
                "reason": "Seattle early center-70 support needs moderate warm redistribution",
            }
        return {
            "rule_id": "seattle_center70_midday_plus1_strong",
            "support_center": center,
            "step": 1,
            "alpha": 0.9,
            "reason": "Seattle midday center-70 support needs strong warm redistribution",
        }

    if 75.5 <= center <= 76.5 and regime == "early" and is_weak_slot:
        return {
            "rule_id": "seattle_center76_weak_plus1_light",
            "support_center": center,
            "step": 1,
            "alpha": 0.2,
            "reason": "Seattle weak-slot center-76 support needs light warm redistribution",
        }
    return None


def shifted_probabilities(probabilities: list[float], *, step: int, alpha: float) -> list[float]:
    if not probabilities:
        return []
    step = max(0, int(step))
    alpha = max(0.0, min(1.0, float(alpha)))
    shifted = [0.0] * len(probabilities)
    for index, probability in enumerate(probabilities):
        shifted[min(len(probabilities) - 1, index + step)] += max(0.0, float(probability))
    blended = [
        (1.0 - alpha) * max(0.0, float(probability)) + alpha * shifted_probability
        for probability, shifted_probability in zip(probabilities, shifted)
    ]
    old_total = sum(max(0.0, float(probability)) for probability in probabilities)
    new_total = sum(blended)
    if old_total > 0.0 and new_total > 0.0:
        blended = [value * old_total / new_total for value in blended]
    return [max(1e-8, min(1.0 - 1e-8, value)) for value in blended]


def apply_repair(
    rows: list[dict[str, Any]],
    weak_slots: set[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repaired = [dict(row) for row in rows]
    for row in repaired:
        row.update(METADATA_DEFAULTS)

    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(repaired):
        key = row_key(row)
        if all(key):
            groups[key].append(index)

    rule_counts: Counter[str] = Counter()
    changed_eq_rows = 0
    changed_groups = 0
    examples = []
    for indexes in groups.values():
        group_rows = [repaired[index] for index in indexes]
        rule = repair_rule_for_group(group_rows, weak_slots)
        if not rule:
            continue
        eq_indexes = [
            index
            for index in indexes
            if is_eq_row(repaired[index]) and bin_value(repaired[index]) is not None
        ]
        eq_indexes.sort(key=lambda index: float(bin_value(repaired[index]) or 0.0))
        probabilities = [
            finite_float(repaired[index].get("probability"), 0.0) or 0.0
            for index in eq_indexes
        ]
        repaired_probabilities = shifted_probabilities(
            probabilities,
            step=int(rule["step"]),
            alpha=float(rule["alpha"]),
        )
        for index, probability in zip(eq_indexes, repaired_probabilities):
            repaired[index]["probability"] = f"{probability:.12g}"
            repaired[index]["recorded_probability"] = f"{probability:.12g}"
        changed_groups += 1
        changed_eq_rows += len(eq_indexes)
        rule_counts[str(rule["rule_id"])] += 1
        if len(examples) < 8:
            market_id, target_date, snapshot_id = row_key(group_rows[0])
            examples.append({
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "rule_id": rule["rule_id"],
                "support_center": rule["support_center"],
                "step": rule["step"],
                "alpha": rule["alpha"],
            })

    return repaired, {
        "group_count": len(groups),
        "changed_group_count": changed_groups,
        "changed_eq_row_count": changed_eq_rows,
        "rule_group_counts": dict(sorted(rule_counts.items())),
        "examples": examples,
    }


def output_fieldnames(fieldnames: list[str] | None) -> list[str]:
    output = list(fieldnames or [])
    for field in reversed(tuple(METADATA_DEFAULTS) + ("recorded_probability",)):
        if field not in output:
            output.insert(0, field)
    seen = set()
    unique = []
    for field in output:
        if field not in seen:
            seen.add(field)
            unique.append(field)
    return unique


def read_rows(path: str | Path) -> tuple[list[str], list[dict[str, Any]]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_rows(path: str | Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output


def build_payload(
    input_rows: str | Path = DEFAULT_INPUT_ROWS,
    ten_minute_report: str | Path = DEFAULT_TEN_MINUTE_REPORT,
    *,
    rows_out: str | Path = DEFAULT_OUT_ROWS,
) -> dict[str, Any]:
    fieldnames, rows = read_rows(input_rows)
    weak_slots = weak_slots_from_report(ten_minute_report)
    repaired, repair_summary = apply_repair(rows, weak_slots)
    rows_path = write_rows(rows_out, output_fieldnames(fieldnames), repaired)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "evidence_classification": "same_corpus_no_market_location_gate_candidate_not_broad_promotion_evidence",
        "variant_id": VARIANT_ID,
        "variant_family": VARIANT_FAMILY,
        "input_rows": str(input_rows),
        "ten_minute_report": str(ten_minute_report),
        "output_rows": str(rows_path),
        "row_count": len(repaired),
        "excluded_label_derived_or_market_features": list(EXCLUDED_LABEL_OR_MARKET_FEATURES),
        "no_market_feature_basis": [
            "market_id",
            "captured_at_local weak-slot membership",
            "cutoff_regime",
            "bin_type",
            "bin_value support center",
            "source candidate probability distribution",
        ],
        "metadata_defaults": dict(METADATA_DEFAULTS),
        "repair_summary": repair_summary,
    }


def render_report(payload: dict[str, Any]) -> str:
    repair_summary = payload.get("repair_summary") or {}
    lines = [
        "# Item 224 No-Market Seattle Warm-Support Repair",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Evidence: `{payload.get('evidence_classification')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Rows", payload.get("row_count")],
            ["Changed groups", repair_summary.get("changed_group_count")],
            ["Changed EQ rows", repair_summary.get("changed_eq_row_count")],
            ["Output rows", payload.get("output_rows")],
            ["Excluded fields", ", ".join(payload.get("excluded_label_derived_or_market_features") or [])],
        ],
    )
    lines += ["", "## Repair Rules", ""]
    lines += markdown_table(
        ["Rule", "Groups"],
        [
            [rule, count]
            for rule, count in sorted((repair_summary.get("rule_group_counts") or {}).items())
        ],
    )
    lines += ["", "## Examples", ""]
    lines += markdown_table(
        ["Market", "Date", "Snapshot", "Rule", "Center", "Step", "Alpha"],
        [
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("rule_id"),
                fmt_num(row.get("support_center")),
                row.get("step"),
                row.get("alpha"),
            ]
            for row in repair_summary.get("examples") or []
        ],
    )
    return "\n".join(lines) + "\n"


def write_json_report(payload: dict[str, Any], json_out: str | Path, report_out: str | Path) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Item 224 no-market Seattle warm-support repair rows.")
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--out-rows", default=str(DEFAULT_OUT_ROWS))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        args.input_rows,
        args.ten_minute_report,
        rows_out=args.out_rows,
    )
    json_path, report_path = write_json_report(payload, args.out_json, args.report)
    repair_summary = payload.get("repair_summary") or {}
    print(
        "Item 224 Seattle warm-support repair: "
        f"{repair_summary.get('changed_group_count', 0)} groups, "
        f"{repair_summary.get('changed_eq_row_count', 0)} EQ rows changed"
    )
    print(f"Rows written to {payload.get('output_rows')}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
