"""Chronological validation for simple exact-winner boost policies.

This is development evidence, not promotion evidence. It selects boost factors
on earlier market-days and evaluates later market-days using only row-export
columns that are available before settlement.
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


SCHEMA_VERSION = "winner_boost_time_split_validation_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "winner_boost_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "winner_boost_validation_report.md"
DEFAULT_FACTOR_GRID = (1.0, 1.2, 1.4, 1.6, 1.8, 2.25, 3.0, 4.0)
DEFAULT_POLICIES = (
    "none",
    "all_eq",
    "early_eq",
    "midday_eq",
    "off_forecast_eq",
    "near_forecast_eq",
    "warm_side_eq",
    "cool_side_eq",
    "early_near_forecast_eq",
    "early_warm_side_eq",
    "early_cool_side_eq",
    "midday_near_forecast_eq",
    "midday_warm_side_eq",
    "midday_cool_side_eq",
)
DEFAULT_MARKET_TOL = 0.003


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


def read_rows(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            for source in csv.DictReader(handle):
                market_id = source.get("market_id") or ""
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
                    "bin_type": (source.get("bin_type") or "").lower(),
                    "cutoff_hour": source.get("cutoff_hour") or "",
                    "cutoff_regime": (source.get("cutoff_regime") or "").lower(),
                    "forecast_bucket_pressure": (source.get("forecast_bucket_pressure") or "").lower(),
                    "forecast_disagreement_bucket": (source.get("forecast_disagreement_bucket") or "").lower(),
                    "forecast_source_count_bucket": (source.get("forecast_source_count_bucket") or "").lower(),
                    "source_freshness_state": source.get("source_freshness_state") or "",
                })
    return rows


def policy_matches(row: dict[str, Any], policy: str) -> bool:
    policy = str(policy or "none")
    if policy == "none":
        return False
    if row.get("bin_type") != "eq":
        return False
    cutoff_regime = row.get("cutoff_regime")
    forecast_pressure = row.get("forecast_bucket_pressure")
    if policy == "all_eq":
        return True
    if policy == "early_eq":
        return cutoff_regime == "early"
    if policy == "midday_eq":
        return cutoff_regime == "midday"
    if policy == "off_forecast_eq":
        return forecast_pressure in {"cool_side", "warm_side"}
    if policy == "near_forecast_eq":
        return forecast_pressure == "near_forecast"
    if policy == "warm_side_eq":
        return forecast_pressure == "warm_side"
    if policy == "cool_side_eq":
        return forecast_pressure == "cool_side"
    if policy == "early_near_forecast_eq":
        return cutoff_regime == "early" and forecast_pressure == "near_forecast"
    if policy == "early_warm_side_eq":
        return cutoff_regime == "early" and forecast_pressure == "warm_side"
    if policy == "early_cool_side_eq":
        return cutoff_regime == "early" and forecast_pressure == "cool_side"
    if policy == "midday_near_forecast_eq":
        return cutoff_regime == "midday" and forecast_pressure == "near_forecast"
    if policy == "midday_warm_side_eq":
        return cutoff_regime == "midday" and forecast_pressure == "warm_side"
    if policy == "midday_cool_side_eq":
        return cutoff_regime == "midday" and forecast_pressure == "cool_side"
    raise ValueError(f"Unknown winner boost policy: {policy}")


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


def boosted_probabilities(rows: list[dict[str, Any]], policy: str, factor: float) -> list[float]:
    factor = max(0.0, float(factor))
    output = [row["probability"] for row in rows]
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["market_id"], row["snapshot_id"])].append(index)
    for indexes in grouped.values():
        weights = [
            rows[index]["probability"] * (factor if policy_matches(rows[index], policy) else 1.0)
            for index in indexes
        ]
        total = sum(weights)
        if total <= 0:
            continue
        for index, weight in zip(indexes, weights):
            output[index] = clamp_probability(weight / total)
    return output


def score_rows(rows: list[dict[str, Any]], policy: str, factor: float) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    candidate_probabilities = boosted_probabilities(rows, policy, factor)
    candidate_losses = []
    current_losses = []
    market_losses = []
    for row, candidate in zip(rows, candidate_probabilities):
        outcome = int(row["outcome"])
        candidate_losses.append(brier(candidate, outcome))
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


def score_daily_first(rows: list[dict[str, Any]], policy_by_market: dict[str, str], factor_by_market: dict[str, float]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    if not grouped:
        return {"market_days": 0}
    scores = [
        score_rows(group_rows, policy_by_market.get(market_id, "none"), factor_by_market.get(market_id, 1.0))
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


def select_policy(rows: list[dict[str, Any]], policies: list[str], factors: list[float]) -> dict[str, Any]:
    candidates = []
    for policy in policies:
        for factor in factors:
            if policy == "none" and abs(factor - 1.0) > 1e-12:
                continue
            score = score_rows(rows, policy, factor)
            candidates.append({
                "policy": policy,
                "factor": float(factor),
                "candidate_brier": score["candidate_brier"],
                "delta_vs_current": score["delta_vs_current"],
                "delta_vs_market": score["delta_vs_market"],
            })
    candidates.sort(key=lambda item: (item["candidate_brier"], item["policy"], item["factor"]))
    selected = candidates[0] if candidates else {"policy": "none", "factor": 1.0}
    return {
        "selected_policy": selected["policy"],
        "selected_factor": float(selected["factor"]),
        "selection_score": selected,
        "candidates": candidates,
    }


def build_payload(
    rows_paths: list[str | Path],
    factor_grid: str | None = None,
    policies_csv: str | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    rows = read_rows(rows_paths)
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
        selected_eval = score_rows(
            eval_rows,
            selection["selected_policy"],
            selection["selected_factor"],
        )
        baseline_eval = score_rows(eval_rows, "none", 1.0)
        market_results.append({
            "market_id": market_id,
            "train_dates": market_split["train_dates"],
            "eval_dates": market_split["eval_dates"],
            **selection,
            "baseline_eval": baseline_eval,
            "eval": selected_eval,
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
    readiness_status = "PASS" if market_results and all(row["holdout_status"] == "PASS" for row in market_results) else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "factor_grid": factors,
        "policies": policies,
        "market_tol": float(market_tol),
        "evidence_classification": "development_time_split_not_promotion_evidence",
        "no_leakage_audit": {
            "status": "PASS" if eval_rows_all else "WARN",
            "primary_evidence_unit": "market_day",
            "detail": (
                "Policy/factor selection uses earlier target dates and evaluation uses later "
                "target dates within each market. Policies use only bin type, cutoff regime, "
                "and forecast-pressure row columns."
            ),
        },
        "row_counts": {
            "total": len(rows),
            "train": len(train_rows_all),
            "eval": len(eval_rows_all),
        },
        "selected_policy_by_market": policy_by_market,
        "selected_factor_by_market": factor_by_market,
        "baseline": {
            "eval_daily_first": score_daily_first(eval_rows_all, {row["market_id"]: "none" for row in rows}, {row["market_id"]: 1.0 for row in rows}),
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
        "# Winner-Boost Time-Split Validation",
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
    parser = argparse.ArgumentParser(description="Validate exact-winner boost policies on chronological splits.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports to evaluate.")
    parser.add_argument("--factor-grid", default=None)
    parser.add_argument("--policies", default=None)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = build_payload(
        rows_paths=args.rows,
        factor_grid=args.factor_grid,
        policies_csv=args.policies,
        market_tol=args.market_tol,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"Winner-boost validation: {payload['readiness_status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
