"""Chronological validation for forecast-pressure probability tilts.

This is development evidence only. It tests whether an inference-available
forecast-relative row category can repair blocked-market winner underpricing
without selecting the tilt on the same market-days being evaluated.
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


SCHEMA_VERSION = "forecast_pressure_tilt_validation_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "forecast_pressure_tilt_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "forecast_pressure_tilt_validation_report.md"
DEFAULT_MARKET_TOL = 0.003
DEFAULT_FACTOR_GRID = (0.50, 0.70, 0.85, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0)
DEFAULT_POLICIES = (
    "none",
    "near_forecast",
    "warm_side",
    "cool_side",
    "off_forecast",
    "early_warm_side",
    "early_cool_side",
)


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def clamp_probability(value: float) -> float:
    return max(1e-15, min(1.0 - 1e-15, float(value)))


def brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def parse_csv_list(value: str | None, default: tuple[Any, ...]) -> list[str]:
    if not value:
        return [str(item) for item in default]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def parse_factor_grid(value: str | None) -> list[float]:
    factors = []
    for item in parse_csv_list(value, DEFAULT_FACTOR_GRID):
        factor = max(0.0, float(item))
        if factor not in factors:
            factors.append(factor)
    return sorted(factors) or [1.0]


def read_rows(paths: list[str | Path], markets: set[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            for source in csv.DictReader(handle):
                market_id = source.get("market_id") or ""
                if markets and market_id not in markets:
                    continue
                target_date = source.get("target_date") or ""
                snapshot_id = source.get("snapshot_id") or ""
                probability = safe_float(source.get("probability"))
                current_probability = safe_float(source.get("current_probability"))
                market_probability = safe_float(source.get("market_yes"))
                outcome = safe_int(source.get("outcome"))
                if (
                    not market_id
                    or not target_date
                    or not snapshot_id
                    or probability is None
                    or current_probability is None
                    or market_probability is None
                    or outcome is None
                ):
                    continue
                rows.append({
                    "market_id": market_id,
                    "target_date": target_date,
                    "snapshot_id": snapshot_id,
                    "band_key": source.get("band_key") or "",
                    "probability": clamp_probability(probability),
                    "current_probability": clamp_probability(current_probability),
                    "market_probability": clamp_probability(market_probability),
                    "outcome": int(outcome),
                    "forecast_bucket_pressure": (source.get("forecast_bucket_pressure") or "unknown").lower(),
                    "cutoff_regime": (source.get("cutoff_regime") or "").lower(),
                    "forecast_disagreement_bucket": (source.get("forecast_disagreement_bucket") or "").lower(),
                    "source_freshness_state": source.get("source_freshness_state") or "",
                })
    return rows


def policy_matches(row: dict[str, Any], policy: str) -> bool:
    pressure = str(row.get("forecast_bucket_pressure") or "").lower()
    regime = str(row.get("cutoff_regime") or "").lower()
    if policy == "none":
        return False
    if policy == "near_forecast":
        return pressure == "near_forecast"
    if policy == "warm_side":
        return pressure == "warm_side"
    if policy == "cool_side":
        return pressure == "cool_side"
    if policy == "off_forecast":
        return pressure in {"warm_side", "cool_side"}
    if policy == "early_warm_side":
        return regime == "early" and pressure == "warm_side"
    if policy == "early_cool_side":
        return regime == "early" and pressure == "cool_side"
    raise ValueError(f"Unknown forecast-pressure tilt policy: {policy}")


def split_market_dates(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    dates_by_market: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        dates_by_market[row["market_id"]].add(row["target_date"])
    split = {}
    for market_id, date_set in sorted(dates_by_market.items()):
        dates = sorted(date_set)
        if len(dates) <= 1:
            train_dates = dates
            eval_dates: list[str] = []
        else:
            cut = max(1, len(dates) // 2)
            train_dates = dates[:cut]
            eval_dates = dates[cut:]
        split[market_id] = {"train_dates": train_dates, "eval_dates": eval_dates}
    return split


def rows_for_dates(rows: list[dict[str, Any]], market_id: str, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [
        row for row in rows
        if row["market_id"] == market_id and row["target_date"] in date_set
    ]


def tilted_probabilities(rows: list[dict[str, Any]], policy: str, factor: float) -> list[float]:
    output = [row["probability"] for row in rows]
    factor = max(0.0, float(factor))
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["market_id"], row["snapshot_id"])].append(index)
    for indexes in grouped.values():
        weights = []
        for index in indexes:
            row = rows[index]
            weight = row["probability"] * (factor if policy_matches(row, policy) else 1.0)
            weights.append(weight)
        total = sum(weights)
        if total <= 0:
            continue
        for index, weight in zip(indexes, weights):
            output[index] = clamp_probability(weight / total)
    return output


def score_rows(rows: list[dict[str, Any]], policy: str = "none", factor: float = 1.0) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    probabilities = tilted_probabilities(rows, policy, factor)
    candidate_losses = []
    current_losses = []
    market_losses = []
    for row, probability in zip(rows, probabilities):
        outcome = int(row["outcome"])
        candidate_losses.append(brier(probability, outcome))
        current_losses.append(brier(row["current_probability"], outcome))
        market_losses.append(brier(row["market_probability"], outcome))
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


def score_daily_first(
    rows: list[dict[str, Any]],
    policy_by_market: dict[str, str],
    factor_by_market: dict[str, float],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    if not grouped:
        return {"market_days": 0}
    scores = [
        score_rows(
            group_rows,
            policy_by_market.get(market_id, "none"),
            factor_by_market.get(market_id, 1.0),
        )
        for (market_id, _target_date), group_rows in grouped.items()
    ]
    keys = ("candidate_brier", "current_brier", "market_brier", "delta_vs_current", "delta_vs_market")
    return {
        "market_days": len(scores),
        **{
            key: sum(score[key] for score in scores if score.get(key) is not None) / len(scores)
            for key in keys
        },
    }


def winner_summary(rows: list[dict[str, Any]], policy: str = "none", factor: float = 1.0) -> dict[str, Any]:
    if not rows:
        return {"winner_rows": 0}
    probabilities = tilted_probabilities(rows, policy, factor)
    winner_probabilities = []
    winner_market = []
    for row, probability in zip(rows, probabilities):
        if int(row["outcome"]) == 1:
            winner_probabilities.append(probability)
            winner_market.append(row["market_probability"])
    if not winner_probabilities:
        return {"winner_rows": 0}
    candidate_mean = sum(winner_probabilities) / len(winner_probabilities)
    market_mean = sum(winner_market) / len(winner_market)
    return {
        "winner_rows": len(winner_probabilities),
        "winner_candidate_probability": candidate_mean,
        "winner_market_probability": market_mean,
        "winner_gap_vs_market": candidate_mean - market_mean,
    }


def select_policy(rows: list[dict[str, Any]], policies: list[str], factors: list[float]) -> dict[str, Any]:
    candidates = []
    for policy in policies:
        for factor in factors:
            if policy == "none" and abs(factor - 1.0) > 1e-12:
                continue
            score = score_rows(rows, policy, factor)
            winner = winner_summary(rows, policy, factor)
            candidates.append({
                "policy": policy,
                "factor": float(factor),
                "candidate_brier": score["candidate_brier"],
                "delta_vs_current": score["delta_vs_current"],
                "delta_vs_market": score["delta_vs_market"],
                "winner_gap_vs_market": winner.get("winner_gap_vs_market"),
            })
    candidates.sort(key=lambda item: (
        math.inf if item["candidate_brier"] is None else item["candidate_brier"],
        item["policy"],
        item["factor"],
    ))
    selected = candidates[0] if candidates else {"policy": "none", "factor": 1.0}
    return {
        "selected_policy": selected["policy"],
        "selected_factor": float(selected["factor"]),
        "selection_score": selected,
        "candidates": candidates,
    }


def build_payload(
    rows_paths: list[str | Path],
    markets: list[str] | None = None,
    factor_grid: str | None = None,
    policies_csv: str | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    market_set = set(markets or [])
    rows = read_rows(rows_paths, markets=market_set or None)
    split = split_market_dates(rows)
    factors = parse_factor_grid(factor_grid)
    policies = parse_csv_list(policies_csv, DEFAULT_POLICIES)
    selections = {}
    market_results = []
    train_rows_all = []
    eval_rows_all = []
    for market_id, market_split in sorted(split.items()):
        train_rows = rows_for_dates(rows, market_id, market_split["train_dates"])
        eval_rows = rows_for_dates(rows, market_id, market_split["eval_dates"])
        train_rows_all.extend(train_rows)
        eval_rows_all.extend(eval_rows)
        selection = select_policy(train_rows, policies, factors)
        selections[market_id] = selection
        selected_eval = score_rows(eval_rows, selection["selected_policy"], selection["selected_factor"])
        baseline_eval = score_rows(eval_rows)
        selected_winner = winner_summary(eval_rows, selection["selected_policy"], selection["selected_factor"])
        baseline_winner = winner_summary(eval_rows)
        market_results.append({
            "market_id": market_id,
            "train_dates": market_split["train_dates"],
            "eval_dates": market_split["eval_dates"],
            **selection,
            "baseline_eval": baseline_eval,
            "eval": selected_eval,
            "baseline_winner": baseline_winner,
            "selected_winner": selected_winner,
            "holdout_status": (
                "PASS"
                if (
                    selected_eval.get("delta_vs_current") is not None
                    and selected_eval["delta_vs_current"] <= 0.0
                    and selected_eval.get("delta_vs_market") is not None
                    and selected_eval["delta_vs_market"] <= float(market_tol)
                )
                else "BLOCK"
            ),
        })

    policy_by_market = {
        market_id: selection["selected_policy"]
        for market_id, selection in selections.items()
    }
    factor_by_market = {
        market_id: float(selection["selected_factor"])
        for market_id, selection in selections.items()
    }
    baseline_policy = {market_id: "none" for market_id in selections}
    baseline_factor = {market_id: 1.0 for market_id in selections}
    readiness_status = (
        "PASS"
        if market_results and all(row["holdout_status"] == "PASS" for row in market_results)
        else "BLOCK"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "row_counts": {
            "total": len(rows),
            "train": len(train_rows_all),
            "eval": len(eval_rows_all),
        },
        "filters": {
            "markets": sorted(market_set) if market_set else [],
            "market_tol": float(market_tol),
        },
        "factor_grid": factors,
        "policies": policies,
        "evidence_classification": "development_time_split_not_promotion_evidence",
        "no_leakage_audit": {
            "status": "PASS" if eval_rows_all else "WARN",
            "primary_evidence_unit": "market_day",
            "detail": (
                "Forecast-pressure tilt policy and factor are selected on earlier target "
                "dates and evaluated on later target dates within each market. Policies use "
                "forecast_bucket_pressure and cutoff_regime, which are available before settlement."
            ),
        },
        "selected_policy_by_market": policy_by_market,
        "selected_factor_by_market": factor_by_market,
        "baseline": {
            "eval_daily_first": score_daily_first(eval_rows_all, baseline_policy, baseline_factor),
        },
        "selected": {
            "eval_daily_first": score_daily_first(eval_rows_all, policy_by_market, factor_by_market),
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
    selected_daily = payload.get("selected", {}).get("eval_daily_first") or {}
    baseline_daily = payload.get("baseline", {}).get("eval_daily_first") or {}
    lines = [
        "# Forecast-Pressure Tilt Time-Split Validation",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "Evidence classification: development diagnostic, not promotion evidence.",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Readiness status", payload.get("readiness_status")],
            ["Rows", (payload.get("row_counts") or {}).get("total")],
            ["Train rows", (payload.get("row_counts") or {}).get("train")],
            ["Eval rows", (payload.get("row_counts") or {}).get("eval")],
            ["Policies", ", ".join(payload.get("policies") or [])],
            ["Factor grid", ", ".join(str(value) for value in payload.get("factor_grid") or [])],
        ],
    )
    lines += [
        "",
        "## Daily-First Holdout",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Candidate", "Current", "Market", "Delta Current", "Delta Market"],
        [
            [
                "selected",
                fmt_num(selected_daily.get("candidate_brier")),
                fmt_num(selected_daily.get("current_brier")),
                fmt_num(selected_daily.get("market_brier")),
                fmt_signed(selected_daily.get("delta_vs_current")),
                fmt_signed(selected_daily.get("delta_vs_market")),
            ],
            [
                "baseline",
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
            "Policy",
            "Factor",
            "Train Dates",
            "Eval Dates",
            "Baseline",
            "Candidate",
            "Current",
            "Market",
            "Delta Market",
            "Winner Gap",
            "Status",
        ],
        [
            [
                row.get("market_id"),
                row.get("selected_policy"),
                fmt_num(row.get("selected_factor")),
                ", ".join(row.get("train_dates") or []),
                ", ".join(row.get("eval_dates") or []),
                fmt_num((row.get("baseline_eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("current_brier")),
                fmt_num((row.get("eval") or {}).get("market_brier")),
                fmt_signed((row.get("eval") or {}).get("delta_vs_market")),
                fmt_signed((row.get("selected_winner") or {}).get("winner_gap_vs_market")),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate forecast-pressure probability tilts on chronological splits.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports to evaluate.")
    parser.add_argument("--markets", default="")
    parser.add_argument("--factor-grid", default=None)
    parser.add_argument("--policies", default=None)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        rows_paths=args.rows,
        markets=parse_csv_list(args.markets, ()),
        factor_grid=args.factor_grid,
        policies_csv=args.policies,
        market_tol=args.market_tol,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"Forecast-pressure tilt validation: {payload['readiness_status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
