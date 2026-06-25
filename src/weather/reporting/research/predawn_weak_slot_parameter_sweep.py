"""Parameter sweep for the predawn weak-slot repair gate."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from weather.paths import data_path
from weather.reporting.research import predawn_weak_slot_repair as predawn
from weather.reporting.formatting import fmt_signed, markdown_table
from weather.reporting.hourly.ten_minute_model_performance import (
    parse_time,
    read_candidate_checkpoint_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("predawn_weak_slot_parameter_sweep")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_CANDIDATE_ROWS = DEFAULT_BACKTEST_ROOT / "item82_miami_fallback_shadow_variants.csv"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item228_predawn_weak_slot_parameter_sweep.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item228_predawn_weak_slot_parameter_sweep_report.md"
DEFAULT_BLEND_GRID = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.75, 0.90, 1.0)
DEFAULT_EXTRAPOLATION_GRID = (0.50, 0.75, 1.0, 1.25, 1.50, 1.75, 2.0, 2.25, 2.50, 3.0, 3.50, 4.0, 5.0, 6.0)
DEFAULT_POWER_GRID = (0.25, 0.50, 0.75, 1.0, 1.25, 1.50, 2.0, 2.50, 3.0, 3.50, 4.0, 5.0, 6.0, 8.0)
DEFAULT_EARLY_BRIER_TOLERANCE = 0.003
DEFAULT_EARLY_LOGLOSS_TOLERANCE = 0.010
DEFAULT_WEAK_BRIER_IMPROVEMENT = 0.003
DEFAULT_WEAK_MARKET_TOLERANCE = 0.003
DEFAULT_WEAK_LOGLOSS_TOLERANCE = 0.010


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float_grid(value: str | None, default: tuple[float, ...]) -> tuple[float, ...]:
    if not value:
        return default
    output = []
    for token in str(value).split(","):
        token = token.strip()
        if token:
            output.append(float(token))
    return tuple(output) or default


def _hour(row: dict[str, Any]) -> int | None:
    parsed = parse_time(row.get("captured_at_local"))
    if parsed is None:
        return None
    return int(parsed.hour)


def _timestamp(row: dict[str, Any]) -> float:
    value = row.get("_timestamp")
    try:
        return float(value)
    except (TypeError, ValueError):
        parsed = parse_time(row.get("captured_at_local"))
        return parsed.timestamp() if parsed else math.inf


def _hourly_checkpoint_indexes(rows: list[dict[str, Any]]) -> list[int]:
    selected: dict[tuple[Any, ...], tuple[float, int]] = {}
    for index, row in enumerate(rows):
        hour = _hour(row)
        if hour is None:
            continue
        key = (row.get("market_id"), row.get("target_date"), row.get("band_key"), hour)
        timestamp = _timestamp(row)
        if key not in selected or timestamp < selected[key][0]:
            selected[key] = (timestamp, index)
    return [value[1] for key, value in sorted(selected.items(), key=lambda item: tuple(str(part) for part in item[0]))]


def _group_inverse(rows: list[dict[str, Any]]) -> np.ndarray:
    group_ids: dict[tuple[Any, ...], int] = {}
    inverse = []
    for row in rows:
        key = (row.get("market_id"), row.get("target_date"), row.get("snapshot_id"), row.get("time_slot_minute"))
        if key not in group_ids:
            group_ids[key] = len(group_ids)
        inverse.append(group_ids[key])
    return np.asarray(inverse, dtype=int)


def _metric_summary(probability: np.ndarray, current: np.ndarray, market: np.ndarray, outcome: np.ndarray, indexes: np.ndarray) -> dict[str, float | int | None]:
    if indexes.size == 0:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
            "candidate_logloss": None,
            "current_logloss": None,
            "market_logloss": None,
            "logloss_delta_vs_current": None,
            "logloss_delta_vs_market": None,
        }
    p = probability[indexes]
    c = current[indexes]
    m = market[indexes]
    y = outcome[indexes]
    candidate_brier = float(np.mean((p - y) ** 2))
    current_brier = float(np.mean((c - y) ** 2))
    market_brier = float(np.mean((m - y) ** 2))
    clipped_p = np.clip(p, 1e-15, 1.0 - 1e-15)
    clipped_c = np.clip(c, 1e-15, 1.0 - 1e-15)
    clipped_m = np.clip(m, 1e-15, 1.0 - 1e-15)
    candidate_logloss = float(np.mean(-(y * np.log(clipped_p) + (1.0 - y) * np.log(1.0 - clipped_p))))
    current_logloss = float(np.mean(-(y * np.log(clipped_c) + (1.0 - y) * np.log(1.0 - clipped_c))))
    market_logloss = float(np.mean(-(y * np.log(clipped_m) + (1.0 - y) * np.log(1.0 - clipped_m))))
    return {
        "rows": int(indexes.size),
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": candidate_brier - current_brier,
        "delta_vs_market": candidate_brier - market_brier,
        "candidate_logloss": candidate_logloss,
        "current_logloss": current_logloss,
        "market_logloss": market_logloss,
        "logloss_delta_vs_current": candidate_logloss - current_logloss,
        "logloss_delta_vs_market": candidate_logloss - market_logloss,
    }


def _score_status(
    early: dict[str, Any],
    weak: dict[str, Any],
    *,
    early_brier_tolerance: float,
    early_logloss_tolerance: float,
    weak_brier_improvement: float,
    weak_market_tolerance: float,
    weak_logloss_tolerance: float,
) -> tuple[str, str, list[str]]:
    blockers = []
    early_delta = early.get("delta_vs_market")
    early_logloss = early.get("logloss_delta_vs_market")
    weak_current = weak.get("delta_vs_current")
    weak_market = weak.get("delta_vs_market")
    weak_logloss = weak.get("logloss_delta_vs_market")
    hourly_pass = (
        early_delta is not None
        and early_logloss is not None
        and float(early_delta) <= float(early_brier_tolerance)
        and float(early_logloss) <= float(early_logloss_tolerance)
    )
    ten_minute_pass = (
        weak_current is not None
        and weak_market is not None
        and weak_logloss is not None
        and float(weak_current) <= -float(weak_brier_improvement)
        and float(weak_market) <= float(weak_market_tolerance)
        and float(weak_logloss) <= float(weak_logloss_tolerance)
    )
    if not hourly_pass:
        if early_delta is None or float(early_delta) > float(early_brier_tolerance):
            blockers.append("early-hour Brier remains outside market tolerance")
        if early_logloss is None or float(early_logloss) > float(early_logloss_tolerance):
            blockers.append("early-hour log-loss remains outside market tolerance")
    if not ten_minute_pass:
        if weak_current is None or float(weak_current) > -float(weak_brier_improvement):
            blockers.append("weak-slot Brier does not improve enough versus current")
        if weak_market is None or float(weak_market) > float(weak_market_tolerance):
            blockers.append("weak-slot Brier remains outside market tolerance")
        if weak_logloss is None or float(weak_logloss) > float(weak_logloss_tolerance):
            blockers.append("weak-slot log-loss remains outside market tolerance")
    return ("PASS" if hourly_pass else "BLOCK", "PASS" if ten_minute_pass else "BLOCK", blockers)


def build_payload(
    candidate_rows: str | Path = DEFAULT_CANDIDATE_ROWS,
    ten_minute_report: str | Path = DEFAULT_TEN_MINUTE_REPORT,
    *,
    blend_grid: tuple[float, ...] = DEFAULT_BLEND_GRID,
    extrapolation_grid: tuple[float, ...] = DEFAULT_EXTRAPOLATION_GRID,
    power_grid: tuple[float, ...] = DEFAULT_POWER_GRID,
    early_brier_tolerance: float = DEFAULT_EARLY_BRIER_TOLERANCE,
    early_logloss_tolerance: float = DEFAULT_EARLY_LOGLOSS_TOLERANCE,
    weak_brier_improvement: float = DEFAULT_WEAK_BRIER_IMPROVEMENT,
    weak_market_tolerance: float = DEFAULT_WEAK_MARKET_TOLERANCE,
    weak_logloss_tolerance: float = DEFAULT_WEAK_LOGLOSS_TOLERANCE,
    top_limit: int = 20,
) -> dict[str, Any]:
    weak_slots = predawn.weak_slots_from_report(ten_minute_report)
    source_rows = read_candidate_checkpoint_rows(Path(candidate_rows))
    scoped = predawn.scoped_policy_rows(source_rows, weak_slots)
    weak_rows = [row for row in scoped if row.get("time_slot_minute") in weak_slots]
    split = predawn.split_dates(weak_rows)
    train_rows = predawn.rows_for_dates(weak_rows, split["train_dates"])
    model = predawn.fit_predawn_calibrator(train_rows)
    if model is None:
        logistic = np.asarray([float(row.get("variant_probability") or 0.0) for row in weak_rows], dtype=float)
        calibrator_source = "fallback_item147_probability"
    else:
        logistic = model.predict_proba(predawn.calibrator_frame(weak_rows))[:, 1]
        calibrator_source = "time_split_logistic"

    current = np.asarray([float(row.get("current_probability") or 0.0) for row in scoped], dtype=float)
    item147 = np.asarray([float(row.get("variant_probability") or 0.0) for row in scoped], dtype=float)
    market = np.asarray([float(row.get("market_yes") or 0.0) for row in scoped], dtype=float)
    outcome = np.asarray([float(row.get("outcome") or 0.0) for row in scoped], dtype=float)
    weak_mask = np.asarray([row.get("time_slot_minute") in weak_slots for row in scoped], dtype=bool)
    weak_positions = np.where(weak_mask)[0]
    weak_current = current[weak_positions]
    weak_item147 = item147[weak_positions]
    inverse = _group_inverse(weak_rows)
    hourly_indexes = _hourly_checkpoint_indexes(scoped)
    early_indexes = np.asarray(
        [index for index in hourly_indexes if (_hour(scoped[index]) is not None and 0 <= int(_hour(scoped[index])) <= 8)],
        dtype=int,
    )
    hour_indexes = {
        hour: np.asarray([index for index in hourly_indexes if _hour(scoped[index]) == hour], dtype=int)
        for hour in (3, 4, 5)
    }

    rows = []
    for blend in blend_grid:
        blended = ((1.0 - float(blend)) * weak_item147) + (float(blend) * logistic)
        for extrapolation in extrapolation_grid:
            extrapolated = np.maximum(0.0, weak_current + (float(extrapolation) * (blended - weak_current)))
            for power in power_grid:
                weights = extrapolated ** float(power)
                sums = np.bincount(inverse, weights=weights, minlength=(int(inverse.max()) + 1 if inverse.size else 0))
                normalized = np.divide(weights, sums[inverse], out=np.zeros_like(weights), where=sums[inverse] > 0)
                probability = current.copy()
                probability[weak_positions] = normalized
                early = _metric_summary(probability, current, market, outcome, early_indexes)
                weak = _metric_summary(probability, current, market, outcome, weak_positions)
                hourly_status, ten_minute_status, blockers = _score_status(
                    early,
                    weak,
                    early_brier_tolerance=early_brier_tolerance,
                    early_logloss_tolerance=early_logloss_tolerance,
                    weak_brier_improvement=weak_brier_improvement,
                    weak_market_tolerance=weak_market_tolerance,
                    weak_logloss_tolerance=weak_logloss_tolerance,
                )
                hour_metrics = {
                    str(hour): _metric_summary(probability, current, market, outcome, indexes)
                    for hour, indexes in hour_indexes.items()
                }
                rows.append({
                    "blend": float(blend),
                    "extrapolation": float(extrapolation),
                    "power": float(power),
                    "status": "PASS" if hourly_status == "PASS" and ten_minute_status == "PASS" else "BLOCK",
                    "candidate_hourly_status": hourly_status,
                    "candidate_ten_minute_status": ten_minute_status,
                    "blockers": blockers,
                    "early_morning": early,
                    "weak_slot": weak,
                    "hour_metrics": hour_metrics,
                })

    rows.sort(
        key=lambda row: (
            row["status"] != "PASS",
            row["candidate_ten_minute_status"] != "PASS",
            float((row["early_morning"] or {}).get("delta_vs_market") or 999.0),
            float((row["early_morning"] or {}).get("logloss_delta_vs_market") or 999.0),
            float((row["weak_slot"] or {}).get("delta_vs_market") or 999.0),
        )
    )
    pass_rows = [row for row in rows if row["status"] == "PASS"]
    hourly_pass_rows = [row for row in rows if row["candidate_hourly_status"] == "PASS"]
    ten_pass_rows = [row for row in rows if row["candidate_ten_minute_status"] == "PASS"]
    status = "PASS" if pass_rows else "BLOCK"
    reasons = [] if pass_rows else [
        "no swept parameter set clears both candidate-hourly and candidate-10-minute gates",
        "best swept settings still exceed broad early-hour market tolerance",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "reasons": reasons,
        "inputs": {
            "candidate_rows": str(candidate_rows),
            "ten_minute_report": str(ten_minute_report),
            "calibrator_source": calibrator_source,
            "train_dates": split.get("train_dates") or [],
            "eval_dates": split.get("eval_dates") or [],
        },
        "thresholds": {
            "early_brier_tolerance": float(early_brier_tolerance),
            "early_logloss_tolerance": float(early_logloss_tolerance),
            "weak_brier_improvement": float(weak_brier_improvement),
            "weak_market_tolerance": float(weak_market_tolerance),
            "weak_logloss_tolerance": float(weak_logloss_tolerance),
        },
        "grid": {
            "blend": list(blend_grid),
            "extrapolation": list(extrapolation_grid),
            "power": list(power_grid),
            "candidate_count": len(rows),
        },
        "corpus": {
            "source_rows": len(source_rows),
            "scoped_rows": len(scoped),
            "weak_rows": len(weak_rows),
            "weak_slots": sorted(int(slot) for slot in weak_slots),
            "early_hourly_rows": int(early_indexes.size),
            "market_days": len({(row.get("market_id"), row.get("target_date")) for row in scoped}),
        },
        "summary": {
            "pass_both_count": len(pass_rows),
            "candidate_hourly_pass_count": len(hourly_pass_rows),
            "candidate_ten_minute_pass_count": len(ten_pass_rows),
            "best": rows[0] if rows else {},
        },
        "top_candidates": rows[: int(top_limit)],
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    best = summary.get("best") or {}
    best_early = best.get("early_morning") or {}
    best_weak = best.get("weak_slot") or {}
    top_rows = []
    for row in payload.get("top_candidates") or []:
        early = row.get("early_morning") or {}
        weak = row.get("weak_slot") or {}
        hours = row.get("hour_metrics") or {}
        top_rows.append([
            row.get("blend"),
            row.get("extrapolation"),
            row.get("power"),
            row.get("candidate_hourly_status"),
            row.get("candidate_ten_minute_status"),
            fmt_signed(early.get("delta_vs_market")),
            fmt_signed(early.get("logloss_delta_vs_market")),
            fmt_signed(weak.get("delta_vs_current")),
            fmt_signed(weak.get("delta_vs_market")),
            fmt_signed(weak.get("logloss_delta_vs_market")),
            fmt_signed((hours.get("3") or {}).get("delta_vs_market")),
            fmt_signed((hours.get("4") or {}).get("delta_vs_market")),
            fmt_signed((hours.get("5") or {}).get("delta_vs_market")),
        ])
    return "\n".join([
        "# Predawn Weak-Slot Parameter Sweep",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Candidate count", (payload.get("grid") or {}).get("candidate_count")],
                ["Pass both count", summary.get("pass_both_count")],
                ["Candidate-hourly pass count", summary.get("candidate_hourly_pass_count")],
                ["Candidate 10-minute pass count", summary.get("candidate_ten_minute_pass_count")],
                ["Source rows", (payload.get("corpus") or {}).get("source_rows")],
                ["Weak rows", (payload.get("corpus") or {}).get("weak_rows")],
                ["Early hourly rows", (payload.get("corpus") or {}).get("early_hourly_rows")],
                ["Calibrator source", (payload.get("inputs") or {}).get("calibrator_source")],
            ],
        ),
        "",
        "## Best Candidate",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Blend", best.get("blend")],
                ["Extrapolation", best.get("extrapolation")],
                ["Power", best.get("power")],
                ["Candidate-hourly status", best.get("candidate_hourly_status")],
                ["Candidate 10-minute status", best.get("candidate_ten_minute_status")],
                ["Early delta vs market", fmt_signed(best_early.get("delta_vs_market"))],
                ["Early log-loss delta vs market", fmt_signed(best_early.get("logloss_delta_vs_market"))],
                ["Weak delta vs current", fmt_signed(best_weak.get("delta_vs_current"))],
                ["Weak delta vs market", fmt_signed(best_weak.get("delta_vs_market"))],
                ["Weak log-loss delta vs market", fmt_signed(best_weak.get("logloss_delta_vs_market"))],
            ],
        ),
        "",
        "## Top Candidates",
        "",
        *markdown_table(
            [
                "Blend",
                "Extrap",
                "Power",
                "Hourly",
                "10-min",
                "Early DM",
                "Early LLM",
                "Weak DC",
                "Weak DM",
                "Weak LLM",
                "H03 DM",
                "H04 DM",
                "H05 DM",
            ],
            top_rows,
        ),
        "",
        "## Reasons",
        "",
        *(f"- {reason}" for reason in (payload.get("reasons") or ["none"])),
        "",
    ])


def write_outputs(payload: dict[str, Any], json_out: str | Path = DEFAULT_OUT, report_out: str | Path = DEFAULT_REPORT) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sweep predawn weak-slot repair calibrator parameters.")
    parser.add_argument("--candidate-rows", default=str(DEFAULT_CANDIDATE_ROWS))
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--blend-grid", default="")
    parser.add_argument("--extrapolation-grid", default="")
    parser.add_argument("--power-grid", default="")
    parser.add_argument("--top-limit", type=int, default=20)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        args.candidate_rows,
        args.ten_minute_report,
        blend_grid=_float_grid(args.blend_grid, DEFAULT_BLEND_GRID),
        extrapolation_grid=_float_grid(args.extrapolation_grid, DEFAULT_EXTRAPOLATION_GRID),
        power_grid=_float_grid(args.power_grid, DEFAULT_POWER_GRID),
        top_limit=args.top_limit,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Predawn weak-slot parameter sweep: status={payload.get('status')} pass_both={payload.get('summary', {}).get('pass_both_count')}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0 if payload.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
