"""Time-split validation for current-blend alpha schedules.

This report is intentionally stricter than replay-row alpha sweeps: alphas are
selected on earlier market-days and evaluated on later market-days. The same
pinned replay corpus still provides both sides, so the output is model-repair
evidence rather than promotion evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "current_blend_time_split_validation_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_ROWS = DEFAULT_BACKTEST_ROOT / "item35_direct_band_all_market_full_variant_rows.csv"
DEFAULT_BASE_REPLAY = DEFAULT_BACKTEST_ROOT / "item35_direct_band_all_market_full_replay.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item35_current_blend_time_split_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item35_current_blend_time_split_validation_report.md"
DEFAULT_ALPHA_GRID = tuple(round(index / 20.0, 2) for index in range(21))
DEFAULT_MARKET_TOL = 0.003


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clamp_probability(value: float) -> float:
    return max(1e-15, min(1.0 - 1e-15, float(value)))


def brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def load_base_alpha_schedule(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    artifact = data.get("artifact") or {}
    return {
        "default_alpha": float(artifact.get("current_blend_default_alpha", 1.0)),
        "market_alpha": {
            str(market): float(alpha)
            for market, alpha in (artifact.get("current_blend_market_alpha") or {}).items()
        },
        "artifact_hash": artifact.get("artifact_hash"),
        "postprocess_config_hash": artifact.get("postprocess_config_hash"),
    }


def base_alpha_for_market(market_id: str, schedule: dict[str, Any]) -> float:
    market_alpha = schedule.get("market_alpha") or {}
    if market_id in market_alpha:
        return max(0.0, min(1.0, float(market_alpha[market_id])))
    return max(0.0, min(1.0, float(schedule.get("default_alpha", 1.0))))


def reconstruct_raw_probability(probability: float, current_probability: float, alpha: float) -> float | None:
    alpha = float(alpha)
    if alpha <= 1e-12:
        return None
    return _clamp_probability((float(probability) - (1.0 - alpha) * float(current_probability)) / alpha)


def read_variant_rows(path: str | Path, base_schedule: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            market_id = source.get("market_id") or ""
            target_date = source.get("target_date") or ""
            probability = _safe_float(source.get("probability"))
            current_probability = _safe_float(source.get("current_probability"))
            market_probability = _safe_float(source.get("market_yes"))
            outcome = _safe_int(source.get("outcome"))
            if (
                not market_id
                or not target_date
                or probability is None
                or current_probability is None
                or market_probability is None
                or outcome is None
            ):
                continue
            base_alpha = base_alpha_for_market(market_id, base_schedule)
            rows.append({
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": source.get("snapshot_id") or "",
                "band_key": source.get("band_key") or "",
                "probability": _clamp_probability(probability),
                "current_probability": _clamp_probability(current_probability),
                "market_probability": _clamp_probability(market_probability),
                "outcome": int(outcome),
                "base_alpha": base_alpha,
                "raw_probability": reconstruct_raw_probability(
                    probability,
                    current_probability,
                    base_alpha,
                ),
            })
    return rows


def candidate_probability(row: dict[str, Any], alpha: float) -> float:
    raw_probability = row.get("raw_probability")
    current = float(row["current_probability"])
    if raw_probability is None:
        return current
    alpha = max(0.0, min(1.0, float(alpha)))
    return _clamp_probability(alpha * float(raw_probability) + (1.0 - alpha) * current)


def split_market_dates(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    dates_by_market: dict[str, list[str]] = {}
    for row in rows:
        dates_by_market.setdefault(row["market_id"], [])
    for market_id in dates_by_market:
        dates_by_market[market_id] = sorted({
            row["target_date"]
            for row in rows
            if row["market_id"] == market_id
        })

    split: dict[str, dict[str, Any]] = {}
    for market_id, dates in sorted(dates_by_market.items()):
        if len(dates) <= 1:
            train_dates = set(dates)
            eval_dates: set[str] = set()
        else:
            cut = max(1, len(dates) // 2)
            train_dates = set(dates[:cut])
            eval_dates = set(dates[cut:])
        split[market_id] = {
            "train_dates": sorted(train_dates),
            "eval_dates": sorted(eval_dates),
        }
    return split


def rows_for_split(rows: list[dict[str, Any]], split: dict[str, dict[str, Any]], side: str) -> list[dict[str, Any]]:
    selected = []
    date_key = "train_dates" if side == "train" else "eval_dates"
    for row in rows:
        market_split = split.get(row["market_id"]) or {}
        if row["target_date"] in set(market_split.get(date_key) or []):
            selected.append(row)
    return selected


def score_rows(rows: list[dict[str, Any]], alpha_by_market: dict[str, float]) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    candidate_losses = []
    current_losses = []
    market_losses = []
    for row in rows:
        alpha = alpha_by_market.get(row["market_id"], 1.0)
        outcome = int(row["outcome"])
        candidate_losses.append(brier(candidate_probability(row, alpha), outcome))
        current_losses.append(brier(float(row["current_probability"]), outcome))
        market_losses.append(brier(float(row["market_probability"]), outcome))
    candidate_brier = sum(candidate_losses) / len(candidate_losses)
    current_brier = sum(current_losses) / len(current_losses)
    market_brier = sum(market_losses) / len(market_losses)
    return {
        "rows": len(rows),
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": candidate_brier - current_brier,
        "delta_vs_market": candidate_brier - market_brier,
    }


def score_daily_first(rows: list[dict[str, Any]], alpha_by_market: dict[str, float]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    group_scores = [
        score_rows(group_rows, alpha_by_market)
        for group_rows in grouped.values()
    ]
    if not group_scores:
        return score_rows([], alpha_by_market)
    keys = ("candidate_brier", "current_brier", "market_brier", "delta_vs_current", "delta_vs_market")
    return {
        "market_days": len(group_scores),
        **{
            key: sum(score[key] for score in group_scores if score[key] is not None) / len(group_scores)
            for key in keys
        },
    }


def alpha_grid_values(alpha_grid: str | None = None) -> list[float]:
    if not alpha_grid:
        return list(DEFAULT_ALPHA_GRID)
    values = []
    for item in str(alpha_grid).split(","):
        item = item.strip()
        if not item:
            continue
        values.append(max(0.0, min(1.0, float(item))))
    return sorted(set(values))


def select_market_alpha(
    rows: list[dict[str, Any]],
    market_id: str,
    train_dates: list[str],
    grid: list[float],
) -> dict[str, Any]:
    train_rows = [
        row for row in rows
        if row["market_id"] == market_id and row["target_date"] in set(train_dates)
    ]
    if not train_rows:
        return {"market_id": market_id, "selected_alpha": 1.0, "reason": "no_training_rows"}
    if all(row.get("raw_probability") is None for row in train_rows):
        return {
            "market_id": market_id,
            "selected_alpha": 0.0,
            "reason": "baseline_artifact_full_current_fallback_no_raw_candidate",
        }
    candidates = []
    for alpha in grid:
        score = score_rows(train_rows, {market_id: alpha})
        candidates.append({
            "alpha": float(alpha),
            "candidate_brier": score["candidate_brier"],
            "delta_vs_current": score["delta_vs_current"],
            "delta_vs_market": score["delta_vs_market"],
        })
    candidates.sort(key=lambda item: (item["candidate_brier"], item["alpha"]))
    selected = candidates[0]
    return {
        "market_id": market_id,
        "selected_alpha": float(selected["alpha"]),
        "reason": "min_train_brier_on_earlier_market_days",
        "train_rows": len(train_rows),
        "train_dates": list(train_dates),
        "selection_score": selected,
        "candidates": candidates,
    }


def build_payload(
    rows_path: str | Path = DEFAULT_ROWS,
    base_replay_path: str | Path = DEFAULT_BASE_REPLAY,
    alpha_grid: str | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    base_schedule = load_base_alpha_schedule(base_replay_path)
    rows = read_variant_rows(rows_path, base_schedule)
    split = split_market_dates(rows)
    grid = alpha_grid_values(alpha_grid)
    selections = [
        select_market_alpha(rows, market_id, market_split.get("train_dates") or [], grid)
        for market_id, market_split in sorted(split.items())
    ]
    selected_alpha = {
        selection["market_id"]: float(selection["selected_alpha"])
        for selection in selections
    }
    baseline_alpha = {
        market_id: base_alpha_for_market(market_id, base_schedule)
        for market_id in split
    }
    train_rows = rows_for_split(rows, split, "train")
    eval_rows = rows_for_split(rows, split, "eval")
    selected_eval = score_rows(eval_rows, selected_alpha)
    selected_daily = score_daily_first(eval_rows, selected_alpha)
    baseline_eval = score_rows(eval_rows, baseline_alpha)
    selections_by_market = {
        selection["market_id"]: selection
        for selection in selections
    }
    market_results = []
    for market_id, market_split in sorted(split.items()):
        market_eval_rows = [
            row for row in eval_rows
            if row["market_id"] == market_id
        ]
        market_train_rows = [
            row for row in train_rows
            if row["market_id"] == market_id
        ]
        selected_score = score_rows(market_eval_rows, selected_alpha)
        baseline_score = score_rows(market_eval_rows, baseline_alpha)
        selection = selections_by_market.get(market_id) or {}
        market_results.append({
            "market_id": market_id,
            "selected_alpha": selected_alpha.get(market_id),
            "baseline_alpha": baseline_alpha.get(market_id),
            "selection_reason": selection.get("reason"),
            "raw_candidate_train_rows": sum(1 for row in market_train_rows if row.get("raw_probability") is not None),
            "raw_candidate_eval_rows": sum(1 for row in market_eval_rows if row.get("raw_probability") is not None),
            "train_dates": market_split.get("train_dates") or [],
            "eval_dates": market_split.get("eval_dates") or [],
            "eval": selected_score,
            "baseline_eval": baseline_score,
            "holdout_status": (
                "PASS"
                if (
                    selected_score.get("delta_vs_current") is not None
                    and selected_score["delta_vs_current"] <= 0.0
                    and selected_score.get("delta_vs_market") is not None
                    and selected_score["delta_vs_market"] <= float(market_tol)
                )
                else "BLOCK"
            ),
        })
    readiness_status = (
        "PASS"
        if (
            selected_eval.get("delta_vs_current") is not None
            and selected_eval["delta_vs_current"] <= 0.0
            and selected_eval.get("delta_vs_market") is not None
            and selected_eval["delta_vs_market"] <= float(market_tol)
            and selected_daily.get("delta_vs_market") is not None
            and selected_daily["delta_vs_market"] <= float(market_tol)
            and all(row["holdout_status"] == "PASS" for row in market_results)
        )
        else "BLOCK"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_path": str(rows_path),
        "base_replay_path": str(base_replay_path),
        "base_schedule": base_schedule,
        "alpha_grid": grid,
        "market_tol": float(market_tol),
        "evidence_classification": "development_time_split_not_promotion_evidence",
        "no_leakage_audit": {
            "primary_evidence_unit": "market_day",
            "status": "PASS" if eval_rows else "WARN",
            "detail": (
                "Alpha selection uses earlier target dates and evaluation uses later target dates "
                "within each market. This does not make the result promotion evidence because both "
                "sides come from the pinned replay corpus."
            ),
        },
        "row_counts": {
            "total": len(rows),
            "train": len(train_rows),
            "eval": len(eval_rows),
        },
        "selected_alpha": selected_alpha,
        "selections": selections,
        "baseline": {
            "eval": baseline_eval,
            "eval_daily_first": score_daily_first(eval_rows, baseline_alpha),
        },
        "selected": {
            "train": score_rows(train_rows, selected_alpha),
            "eval": selected_eval,
            "eval_daily_first": selected_daily,
        },
        "market_results": market_results,
        "readiness_status": readiness_status,
        "blockers": [
            row for row in market_results
            if row["holdout_status"] != "PASS"
        ],
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = payload.get("selected") or {}
    baseline = payload.get("baseline") or {}
    lines = [
        "# Current-Blend Time-Split Validation",
        "",
        f"Generated: {payload.get('generated_at')}",
        "",
        "This is development evidence, not promotion evidence. Alphas are selected on earlier "
        "market-days and evaluated on later market-days, but both sides still come from the pinned replay corpus.",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Readiness status", payload.get("readiness_status")],
            ["Evidence classification", payload.get("evidence_classification")],
            ["Rows", (payload.get("row_counts") or {}).get("total")],
            ["Train rows", (payload.get("row_counts") or {}).get("train")],
            ["Eval rows", (payload.get("row_counts") or {}).get("eval")],
            ["Selected alpha", json.dumps(payload.get("selected_alpha") or {}, sort_keys=True)],
        ],
    )
    lines += [
        "",
        "## Holdout Scores",
        "",
    ]
    selected_eval = selected.get("eval") or {}
    selected_daily = selected.get("eval_daily_first") or {}
    baseline_eval = baseline.get("eval") or {}
    baseline_daily = baseline.get("eval_daily_first") or {}
    lines += markdown_table(
        ["Scope", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
        [
            [
                "selected eval rows",
                fmt_num(selected_eval.get("candidate_brier")),
                fmt_num(selected_eval.get("current_brier")),
                fmt_num(selected_eval.get("market_brier")),
                fmt_signed(selected_eval.get("delta_vs_current")),
                fmt_signed(selected_eval.get("delta_vs_market")),
            ],
            [
                "baseline eval rows",
                fmt_num(baseline_eval.get("candidate_brier")),
                fmt_num(baseline_eval.get("current_brier")),
                fmt_num(baseline_eval.get("market_brier")),
                fmt_signed(baseline_eval.get("delta_vs_current")),
                fmt_signed(baseline_eval.get("delta_vs_market")),
            ],
            [
                "selected daily-first",
                fmt_num(selected_daily.get("candidate_brier")),
                fmt_num(selected_daily.get("current_brier")),
                fmt_num(selected_daily.get("market_brier")),
                fmt_signed(selected_daily.get("delta_vs_current")),
                fmt_signed(selected_daily.get("delta_vs_market")),
            ],
            [
                "baseline daily-first",
                fmt_num(baseline_daily.get("candidate_brier")),
                fmt_num(baseline_daily.get("current_brier")),
                fmt_num(baseline_daily.get("market_brier")),
                fmt_signed(baseline_daily.get("delta_vs_current")),
                fmt_signed(baseline_daily.get("delta_vs_market")),
            ],
        ],
    )
    lines += [
        "",
        "## Market Holdout",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Alpha",
            "Selection reason",
            "Raw Eval Rows",
            "Train Dates",
            "Eval Dates",
            "Candidate",
            "Current",
            "Market",
            "Delta Current",
            "Delta Market",
            "Status",
        ],
        [
            [
                row.get("market_id"),
                fmt_num(row.get("selected_alpha")),
                row.get("selection_reason") or "-",
                row.get("raw_candidate_eval_rows", 0),
                ", ".join(row.get("train_dates") or []),
                ", ".join(row.get("eval_dates") or []),
                fmt_num((row.get("eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("current_brier")),
                fmt_num((row.get("eval") or {}).get("market_brier")),
                fmt_signed((row.get("eval") or {}).get("delta_vs_current")),
                fmt_signed((row.get("eval") or {}).get("delta_vs_market")),
                row.get("holdout_status"),
            ]
            for row in payload.get("market_results") or []
        ],
    )
    lines += [
        "",
        "## No-Leakage Audit",
        "",
    ]
    audit = payload.get("no_leakage_audit") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", audit.get("status")],
            ["Primary evidence unit", audit.get("primary_evidence_unit")],
            ["Detail", audit.get("detail")],
        ],
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate current-blend alphas on a chronological replay split.")
    parser.add_argument("--rows", default=str(DEFAULT_ROWS))
    parser.add_argument("--base-replay", default=str(DEFAULT_BASE_REPLAY))
    parser.add_argument("--alpha-grid", default=None)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = build_payload(
        rows_path=args.rows,
        base_replay_path=args.base_replay,
        alpha_grid=args.alpha_grid,
        market_tol=args.market_tol,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"Current-blend time-split status: {payload['readiness_status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
