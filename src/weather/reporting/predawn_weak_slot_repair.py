"""Predawn weak-slot winner-centering repair validation."""

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
from weather.reporting.ten_minute_model_performance import (
    DEFAULT_ITEM147_ROWS,
    read_candidate_checkpoint_rows,
    slot_label,
    summarize_candidate_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("predawn_weak_slot_repair")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "predawn_weak_slot_repair_report.md"
DEFAULT_MIN_BRIER_IMPROVEMENT = 0.003
DEFAULT_MARKET_TOL = 0.003
PREDAWN_FEATURE_CONTRACT = [
    "time_slot_minute",
    "forecast_gap_size",
    "band_mid_minus_forecast",
    "forecast_source_count",
    "forecast_disagreement",
    "source_freshness_state",
    "prior_cycle_forecast_movement",
    "minutes_until_local_heating_window",
]


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


def weak_slots_from_report(path: str | Path) -> set[int]:
    payload = _read_json(path)
    slots = (payload.get("weak_slots") or {}).get("slot_minutes") or []
    return {int(slot) for slot in slots}


def split_dates(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    dates = sorted({row.get("target_date") for row in rows if row.get("target_date")})
    if len(dates) <= 1:
        return {"train_dates": dates, "eval_dates": dates}
    cut = max(1, len(dates) // 2)
    return {"train_dates": dates[:cut], "eval_dates": dates[cut:]}


def scoped_policy_rows(rows: list[dict[str, Any]], weak_slots: set[int]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        item = dict(row)
        if item.get("time_slot_minute") not in weak_slots:
            item["variant_probability"] = item.get("current_probability")
        output.append(item)
    return output


def _bin_value(row: dict[str, Any]) -> float | None:
    for key in ("bin_value", "bin_value_c"):
        value = safe_float(row.get(key))
        if value is not None:
            return value
    band = str(row.get("band_key") or "")
    if ":" in band:
        return safe_float(band.split(":", 1)[1])
    return None


def _normalized(rows: list[dict[str, Any]], key: str) -> list[float]:
    values = [max(0.0, float(row.get(key) or 0.0)) for row in rows]
    total = sum(values)
    if total <= 0:
        return []
    return [value / total for value in values]


def effective_band_count(rows: list[dict[str, Any]], key: str) -> float | None:
    probabilities = _normalized(rows, key)
    if not probabilities:
        return None
    concentration = sum(value * value for value in probabilities)
    return 1.0 / concentration if concentration > 0 else None


def adjacent_winner_mass(rows: list[dict[str, Any]], key: str, max_distance: float = 1.0) -> float | None:
    probabilities = _normalized(rows, key)
    if not probabilities:
        return None
    winner_values = [
        _bin_value(row)
        for row in rows
        if int(row.get("outcome") or 0) == 1 and _bin_value(row) is not None
    ]
    if not winner_values:
        return None
    total = 0.0
    for row, probability in zip(rows, probabilities):
        value = _bin_value(row)
        if value is not None and any(abs(value - winner) <= max_distance for winner in winner_values):
            total += probability
    return total


def _mean(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def distribution_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
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
    variant_effective = []
    current_effective = []
    market_effective = []
    variant_adjacent = []
    current_adjacent = []
    market_adjacent = []
    for snapshot_rows in grouped.values():
        variant_effective.append(effective_band_count(snapshot_rows, "variant_probability"))
        current_effective.append(effective_band_count(snapshot_rows, "current_probability"))
        market_effective.append(effective_band_count(snapshot_rows, "market_yes"))
        variant_adjacent.append(adjacent_winner_mass(snapshot_rows, "variant_probability"))
        current_adjacent.append(adjacent_winner_mass(snapshot_rows, "current_probability"))
        market_adjacent.append(adjacent_winner_mass(snapshot_rows, "market_yes"))
    variant_eff = _mean(variant_effective)
    current_eff = _mean(current_effective)
    market_eff = _mean(market_effective)
    variant_adj = _mean(variant_adjacent)
    current_adj = _mean(current_adjacent)
    market_adj = _mean(market_adjacent)
    return {
        "snapshot_groups": len(grouped),
        "variant_effective_bands": variant_eff,
        "current_effective_bands": current_eff,
        "market_effective_bands": market_eff,
        "effective_band_delta_vs_current": (
            variant_eff - current_eff if variant_eff is not None and current_eff is not None else None
        ),
        "effective_band_delta_vs_market": (
            variant_eff - market_eff if variant_eff is not None and market_eff is not None else None
        ),
        "variant_adjacent_winner_mass": variant_adj,
        "current_adjacent_winner_mass": current_adj,
        "market_adjacent_winner_mass": market_adj,
        "adjacent_winner_mass_delta_vs_current": (
            variant_adj - current_adj if variant_adj is not None and current_adj is not None else None
        ),
        "adjacent_winner_mass_delta_vs_market": (
            variant_adj - market_adj if variant_adj is not None and market_adj is not None else None
        ),
    }


def scored_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_candidate_rows(rows) or {}
    summary.update(distribution_summary(rows))
    return summary


def rows_for_dates(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [row for row in rows if row.get("target_date") in date_set]


def status_for_summary(
    summary: dict[str, Any],
    *,
    min_brier_improvement: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> tuple[str, list[str]]:
    reasons = []
    delta_current = safe_float(summary.get("delta_vs_current"))
    delta_market = safe_float(summary.get("delta_vs_market"))
    winner_delta = safe_float(summary.get("winner_variant_probability"))
    winner_current = safe_float(summary.get("winner_current_probability"))
    effective_delta = safe_float(summary.get("effective_band_delta_vs_current"))
    adjacent_delta = safe_float(summary.get("adjacent_winner_mass_delta_vs_current"))
    if delta_current is None or delta_current > -float(min_brier_improvement):
        reasons.append(
            f"Brier delta vs current {fmt_signed(delta_current)} does not clear {-float(min_brier_improvement):+.4f}"
        )
    if delta_market is None or delta_market > float(market_tol):
        reasons.append(f"Brier delta vs market {fmt_signed(delta_market)} exceeds +{float(market_tol):.4f}")
    if winner_delta is None or winner_current is None or winner_delta <= winner_current:
        reasons.append("winner probability did not increase versus current")
    if effective_delta is None or effective_delta >= 0:
        reasons.append("effective-band spread did not shrink versus current")
    if adjacent_delta is not None and adjacent_delta < 0:
        reasons.append("adjacent-winner mass regressed versus current")
    return ("PASS" if not reasons else "BLOCK", reasons)


def top_cases(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    cases = []
    for row in rows:
        if int(row.get("outcome") or 0) != 1:
            continue
        variant = safe_float(row.get("variant_probability"))
        current = safe_float(row.get("current_probability"))
        market = safe_float(row.get("market_yes"))
        if variant is None or current is None or market is None:
            continue
        cases.append({
            "market_id": row.get("market_id"),
            "target_date": row.get("target_date"),
            "time_slot_label": row.get("time_slot_label") or slot_label(row.get("time_slot_minute")),
            "snapshot_id": row.get("snapshot_id"),
            "band_key": row.get("band_key"),
            "variant_probability": variant,
            "current_probability": current,
            "market_probability": market,
            "variant_lift_vs_current": variant - current,
            "gap_vs_market": market - variant,
        })
    return sorted(
        cases,
        key=lambda row: (row.get("gap_vs_market") or 0.0, row.get("variant_lift_vs_current") or 0.0),
        reverse=True,
    )[:limit]


def regime_guardrails(rows: list[dict[str, Any]], weak_slots: set[int]) -> list[dict[str, Any]]:
    output = []
    scoped = scoped_policy_rows(rows, weak_slots)
    for regime in ("early_morning", "ramp_midday", "late_day", "lock_in"):
        regime_rows = [
            row for row in scoped
            if row.get("time_slot_regime") == regime and row.get("time_slot_minute") not in weak_slots
        ]
        if not regime_rows:
            continue
        summary = scored_summary(regime_rows)
        output.append({
            "regime": regime,
            "rows": summary.get("n", 0),
            "market_days": summary.get("market_days"),
            "delta_vs_current": summary.get("delta_vs_current"),
            "delta_vs_market": summary.get("delta_vs_market"),
            "status": "PASS" if (summary.get("delta_vs_current") or 0.0) <= DEFAULT_MARKET_TOL else "BLOCK",
            "reason": "scoped policy leaves non-weak-slot probabilities unchanged",
        })
    return output


def build_payload(
    candidate_rows: str | Path = DEFAULT_ITEM147_ROWS,
    ten_minute_report: str | Path = DEFAULT_TEN_MINUTE_REPORT,
    *,
    min_brier_improvement: float = DEFAULT_MIN_BRIER_IMPROVEMENT,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    weak_slots = weak_slots_from_report(ten_minute_report)
    rows = read_candidate_checkpoint_rows(Path(candidate_rows))
    weak_rows = [row for row in rows if row.get("time_slot_minute") in weak_slots]
    split = split_dates(weak_rows)
    train_rows = rows_for_dates(weak_rows, split["train_dates"])
    eval_rows = rows_for_dates(weak_rows, split["eval_dates"])
    all_summary = scored_summary(weak_rows)
    train_summary = scored_summary(train_rows)
    eval_summary = scored_summary(eval_rows)
    all_status, all_reasons = status_for_summary(
        all_summary,
        min_brier_improvement=min_brier_improvement,
        market_tol=market_tol,
    )
    eval_status, eval_reasons = status_for_summary(
        eval_summary,
        min_brier_improvement=min_brier_improvement,
        market_tol=market_tol,
    )
    guardrails = regime_guardrails(rows, weak_slots)
    guardrail_blockers = [row for row in guardrails if row.get("status") != "PASS"]
    blockers = []
    if all_status != "PASS":
        blockers.append({
            "gate": "aggregate_predawn_weak_slot_repair",
            "detail": "; ".join(all_reasons),
        })
    if eval_status != "PASS":
        blockers.append({
            "gate": "time_split_predawn_weak_slot_repair",
            "detail": "; ".join(eval_reasons),
        })
    if guardrail_blockers:
        blockers.append({
            "gate": "non_predawn_guardrail_regression",
            "detail": f"{len(guardrail_blockers)} non-predawn guardrail row(s) blocked",
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "candidate_policy": {
            "variant_id": "item147_time_split_alpha_predawn_weak_slot_scoped",
            "source_variant_ids": sorted({row.get("variant_id") for row in rows if row.get("variant_id")}),
            "uses_market_features": False,
            "scope": "apply item147_time_split_alpha only to current 10-minute weak slots; use current probabilities elsewhere",
            "weak_slot_labels": [slot_label(slot) for slot in sorted(weak_slots)],
            "feature_contract": PREDAWN_FEATURE_CONTRACT,
        },
        "inputs": {
            "candidate_rows": str(candidate_rows),
            "ten_minute_report": str(ten_minute_report),
            "min_brier_improvement": float(min_brier_improvement),
            "market_tolerance": float(market_tol),
        },
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "split": split,
        "weak_slot_summary": all_summary,
        "train_summary": train_summary,
        "eval_summary": eval_summary,
        "guardrails": guardrails,
        "casebook": {
            "case_count": len(top_cases(weak_rows, limit=10**9)),
            "top_cases": top_cases(weak_rows),
        },
    }


def _summary_rows(payload: dict[str, Any]) -> list[list[Any]]:
    return [
        ["Status", payload.get("status")],
        ["Blockers", payload.get("blocker_count")],
        ["First blocker", (payload.get("first_blocker") or {}).get("gate") or "-"],
        ["Weak slots", ", ".join((payload.get("candidate_policy") or {}).get("weak_slot_labels") or [])],
        ["Train dates", ", ".join((payload.get("split") or {}).get("train_dates") or [])],
        ["Eval dates", ", ".join((payload.get("split") or {}).get("eval_dates") or [])],
    ]


def _metric_rows(sections: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    rows = []
    for label, summary in sections:
        rows.append([
            label,
            summary.get("n"),
            summary.get("market_days"),
            fmt_num(summary.get("variant_brier")),
            fmt_num(summary.get("current_brier")),
            fmt_num(summary.get("market_brier")),
            fmt_signed(summary.get("delta_vs_current")),
            fmt_signed(summary.get("delta_vs_market")),
            fmt_num(summary.get("winner_variant_probability")),
            fmt_num(summary.get("winner_current_probability")),
            fmt_num(summary.get("winner_market_probability")),
            fmt_num(summary.get("effective_band_delta_vs_current")),
            fmt_num(summary.get("adjacent_winner_mass_delta_vs_current")),
        ])
    return rows


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Predawn Weak-Slot Repair Validation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(["Field", "Value"], _summary_rows(payload))
    lines += ["", "## Candidate Policy", ""]
    policy = payload.get("candidate_policy") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variant", policy.get("variant_id")],
            ["Source variants", ", ".join(policy.get("source_variant_ids") or [])],
            ["Uses market features", policy.get("uses_market_features")],
            ["Scope", policy.get("scope")],
            ["Feature contract", ", ".join(policy.get("feature_contract") or [])],
        ],
    )
    lines += ["", "## Weak-Slot Validation", ""]
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
            "Eff Band Delta",
            "Adjacent Mass Delta",
        ],
        _metric_rows([
            ("all weak slots", payload.get("weak_slot_summary") or {}),
            ("train weak slots", payload.get("train_summary") or {}),
            ("eval weak slots", payload.get("eval_summary") or {}),
        ]),
    )
    blockers = payload.get("blockers") or []
    if blockers:
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Gate", "Detail"],
            [[row.get("gate"), row.get("detail")] for row in blockers],
        )
    lines += ["", "## Non-Predawn Guardrails", ""]
    lines += markdown_table(
        ["Regime", "Rows", "Days", "Delta Current", "Delta Market", "Status", "Reason"],
        [
            [
                row.get("regime"),
                row.get("rows"),
                row.get("market_days"),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
                row.get("status"),
                row.get("reason"),
            ]
            for row in payload.get("guardrails") or []
        ],
    )
    lines += ["", "## Weak-Slot Casebook", ""]
    lines += markdown_table(
        ["Market", "Date", "Slot", "Band", "Candidate P", "Current P", "Market P", "Lift", "Gap To Market"],
        [
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("time_slot_label"),
                row.get("band_key"),
                fmt_num(row.get("variant_probability")),
                fmt_num(row.get("current_probability")),
                fmt_num(row.get("market_probability")),
                fmt_signed(row.get("variant_lift_vs_current")),
                fmt_signed(row.get("gap_vs_market")),
            ]
            for row in ((payload.get("casebook") or {}).get("top_cases") or [])
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
    parser = argparse.ArgumentParser(description="Validate predawn weak-slot winner-centering repairs.")
    parser.add_argument("--candidate-rows", default=str(DEFAULT_ITEM147_ROWS))
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--min-brier-improvement", type=float, default=DEFAULT_MIN_BRIER_IMPROVEMENT)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        args.candidate_rows,
        args.ten_minute_report,
        min_brier_improvement=args.min_brier_improvement,
        market_tol=args.market_tol,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    print(f"Predawn weak-slot repair validation: {payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
