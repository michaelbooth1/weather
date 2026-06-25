"""Chronological validation for forecast-side rank repairs.

This is development evidence only. It tests whether the candidate's top-ranked
band within each forecast-pressure side can repair blocked-market winner gaps
without selecting the policy on the same market-days being evaluated.
"""

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
from weather.reporting.validation.winner_boost_validation import (
    brier,
    clamp_probability,
    parse_csv_list,
    parse_factor_grid,
    read_rows,
    rows_for_dates,
    split_market_dates,
)


SCHEMA_VERSION = "forecast_side_rank_validation_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "forecast_side_rank_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "forecast_side_rank_validation_report.md"
DEFAULT_MARKET_TOL = 0.003
DEFAULT_FACTOR_GRID = (0.50, 0.70, 0.85, 1.0, 1.15, 1.30, 1.50, 1.75, 2.0, 2.5, 3.0, 4.0, 6.0, 8.0)
DEFAULT_POLICIES = (
    "none",
    "pressure_top1",
    "pressure_top2",
    "off_forecast_pressure_top1",
    "off_forecast_pressure_top2",
    "eq_pressure_top1",
    "eq_pressure_top2",
    "early_eq_pressure_top1",
    "early_eq_pressure_top2",
    "warm_side_top1",
    "warm_side_top2",
    "cool_side_top1",
    "cool_side_top2",
    "near_forecast_top1",
    "near_forecast_top2",
)


def parse_markets(value: str | None) -> set[str] | None:
    if not value:
        return None
    markets = {item.strip() for item in str(value).split(",") if item.strip()}
    return markets or None


def _rank_limit(policy: str) -> int:
    marker = "_top"
    if marker not in policy:
        raise ValueError(f"Invalid forecast-side rank policy: {policy}")
    try:
        return int(policy.rsplit(marker, 1)[1])
    except ValueError as exc:
        raise ValueError(f"Invalid forecast-side rank policy: {policy}") from exc


def _pressure_bucket_allowed(row: dict[str, Any], policy: str) -> bool:
    pressure = str(row.get("forecast_bucket_pressure") or "").lower()
    if policy.startswith("warm_side_"):
        return pressure == "warm_side"
    if policy.startswith("cool_side_"):
        return pressure == "cool_side"
    if policy.startswith("near_forecast_"):
        return pressure == "near_forecast"
    if policy.startswith("off_forecast_pressure_"):
        return pressure in {"warm_side", "cool_side"}
    return pressure in {"warm_side", "cool_side", "near_forecast"}


def policy_matches(row: dict[str, Any], pressure_rank: int | None, policy: str) -> bool:
    policy = str(policy or "none")
    if policy == "none":
        return False
    if pressure_rank is None or pressure_rank > _rank_limit(policy):
        return False
    if policy.startswith("eq_") and row.get("bin_type") != "eq":
        return False
    if policy.startswith("early_eq_") and (
        row.get("bin_type") != "eq" or row.get("cutoff_regime") != "early"
    ):
        return False
    return _pressure_bucket_allowed(row, policy)


def _snapshot_groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[int]]:
    grouped: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["market_id"], row["target_date"], row["snapshot_id"])].append(index)
    return grouped


def _pressure_ranks(rows: list[dict[str, Any]], indexes: list[int]) -> dict[int, int]:
    by_pressure: dict[str, list[int]] = defaultdict(list)
    for index in indexes:
        pressure = str(rows[index].get("forecast_bucket_pressure") or "").lower()
        by_pressure[pressure].append(index)

    ranks: dict[int, int] = {}
    for pressure_indexes in by_pressure.values():
        ranked = sorted(pressure_indexes, key=lambda index: float(rows[index]["probability"]), reverse=True)
        for rank, index in enumerate(ranked, start=1):
            ranks[index] = rank
    return ranks


def shaped_probabilities(rows: list[dict[str, Any]], policy: str, factor: float) -> list[float]:
    factor = max(0.0, float(factor))
    output = [float(row["probability"]) for row in rows]
    for indexes in _snapshot_groups(rows).values():
        ranks = _pressure_ranks(rows, indexes)
        weights = []
        for index in indexes:
            row = rows[index]
            multiplier = factor if policy_matches(row, ranks.get(index), policy) else 1.0
            weights.append(float(row["probability"]) * multiplier)
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
    probabilities = shaped_probabilities(rows, policy, factor)
    candidate_brier = sum(
        brier(probability, int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ) / len(rows)
    current_brier = sum(brier(row["current_probability"], int(row["outcome"])) for row in rows) / len(rows)
    market_brier = sum(brier(row["market_probability"], int(row["outcome"])) for row in rows) / len(rows)
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


def select_policy(rows: list[dict[str, Any]], policies: list[str], factors: list[float]) -> dict[str, Any]:
    candidates = []
    for policy in policies:
        for factor in factors:
            if policy == "none" and abs(float(factor) - 1.0) > 1e-12:
                continue
            if policy != "none" and abs(float(factor) - 1.0) <= 1e-12:
                continue
            score = score_rows(rows, policy, factor)
            candidates.append({
                "policy": policy,
                "factor": float(factor),
                **score,
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


def _pass_status(score: dict[str, Any], market_tol: float) -> str:
    if (
        score.get("delta_vs_current") is not None
        and score["delta_vs_current"] <= 0.0
        and score.get("delta_vs_market") is not None
        and score["delta_vs_market"] <= float(market_tol)
    ):
        return "PASS"
    return "BLOCK"


def build_payload(
    rows_paths: list[str | Path],
    markets: set[str] | None = None,
    factor_grid: str | None = None,
    policies_csv: str | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    rows = read_rows(rows_paths)
    if markets:
        rows = [row for row in rows if row["market_id"] in markets]
    split = split_market_dates(rows)
    factors = parse_factor_grid(factor_grid) if factor_grid else list(DEFAULT_FACTOR_GRID)
    policies = parse_csv_list(policies_csv, DEFAULT_POLICIES)

    selections: dict[str, dict[str, Any]] = {}
    oracle_selections: dict[str, dict[str, Any]] = {}
    market_results = []
    train_rows_all = []
    eval_rows_all = []
    for market_id, market_split in sorted(split.items()):
        train_rows = rows_for_dates(rows, market_id, market_split["train_dates"])
        eval_rows = rows_for_dates(rows, market_id, market_split["eval_dates"])
        train_rows_all.extend(train_rows)
        eval_rows_all.extend(eval_rows)

        selection = select_policy(train_rows, policies, factors)
        eval_oracle = select_policy(eval_rows, policies, factors)
        selections[market_id] = selection
        oracle_selections[market_id] = eval_oracle

        selected_eval = score_rows(
            eval_rows,
            selection["selected_policy"],
            selection["selected_factor"],
        )
        baseline_eval = score_rows(eval_rows, "none", 1.0)
        oracle_eval = score_rows(
            eval_rows,
            eval_oracle["selected_policy"],
            eval_oracle["selected_factor"],
        )
        market_results.append({
            "market_id": market_id,
            "train_dates": market_split["train_dates"],
            "eval_dates": market_split["eval_dates"],
            **selection,
            "baseline_eval": baseline_eval,
            "eval": selected_eval,
            "eval_oracle": {
                "selected_policy": eval_oracle["selected_policy"],
                "selected_factor": eval_oracle["selected_factor"],
                "score": oracle_eval,
            },
            "holdout_status": _pass_status(selected_eval, market_tol),
        })

    policy_by_market = {
        market_id: selection["selected_policy"]
        for market_id, selection in selections.items()
    }
    factor_by_market = {
        market_id: float(selection["selected_factor"])
        for market_id, selection in selections.items()
    }
    oracle_policy_by_market = {
        market_id: selection["selected_policy"]
        for market_id, selection in oracle_selections.items()
    }
    oracle_factor_by_market = {
        market_id: float(selection["selected_factor"])
        for market_id, selection in oracle_selections.items()
    }
    baseline_policy = {market_id: "none" for market_id in policy_by_market}
    baseline_factor = {market_id: 1.0 for market_id in policy_by_market}
    readiness_status = (
        "PASS"
        if market_results and all(row["holdout_status"] == "PASS" for row in market_results)
        else "BLOCK"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "markets": sorted(markets) if markets else "all",
        "factor_grid": factors,
        "policies": policies,
        "market_tol": float(market_tol),
        "evidence_classification": "development_time_split_not_promotion_evidence",
        "no_leakage_audit": {
            "status": "PASS" if eval_rows_all else "WARN",
            "primary_evidence_unit": "market_day",
            "detail": (
                "Policy/factor selection uses earlier target dates and evaluation uses later "
                "target dates within each market. Policy inputs are candidate probabilities, "
                "candidate ranks within each forecast-pressure side, bin type, cutoff regime, "
                "and forecast-pressure labels. Market prices are used only for scoring."
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
            "eval_daily_first": score_daily_first(eval_rows_all, baseline_policy, baseline_factor),
        },
        "selected": {
            "eval_daily_first": score_daily_first(eval_rows_all, policy_by_market, factor_by_market),
        },
        "eval_oracle": {
            "classification": "diagnostic_only_later_date_selected",
            "eval_daily_first": score_daily_first(eval_rows_all, oracle_policy_by_market, oracle_factor_by_market),
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


def _daily_row(label: str, payload: dict[str, Any]) -> list[Any]:
    return [
        label,
        payload.get("market_days"),
        fmt_num(payload.get("candidate_brier")),
        fmt_num(payload.get("current_brier")),
        fmt_num(payload.get("market_brier")),
        fmt_signed(payload.get("delta_vs_current")),
        fmt_signed(payload.get("delta_vs_market")),
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    selected_daily = (payload.get("selected") or {}).get("eval_daily_first") or {}
    baseline_daily = (payload.get("baseline") or {}).get("eval_daily_first") or {}
    oracle_daily = ((payload.get("eval_oracle") or {}).get("eval_daily_first")) or {}
    lines = [
        "# Forecast-Side Rank Validation",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "This is development evidence, not promotion evidence. Policies are selected on earlier "
        "market-days and evaluated on later market-days. The eval oracle is diagnostic only.",
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
            ["Selected policies", json.dumps(payload.get("selected_policy_by_market") or {}, sort_keys=True)],
            ["Selected factors", json.dumps(payload.get("selected_factor_by_market") or {}, sort_keys=True)],
        ],
    )
    lines += [
        "",
        "## Daily-First Holdout",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Market Days", "Candidate", "Current", "Market", "Delta Current", "Delta Market"],
        [
            _daily_row("baseline", baseline_daily),
            _daily_row("selected", selected_daily),
            _daily_row("eval oracle (diagnostic)", oracle_daily),
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
            "Selected",
            "Current",
            "Market",
            "Delta Current",
            "Delta Market",
            "Oracle Policy",
            "Oracle Gap",
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
                fmt_signed((row.get("eval") or {}).get("delta_vs_current")),
                fmt_signed((row.get("eval") or {}).get("delta_vs_market")),
                (row.get("eval_oracle") or {}).get("selected_policy"),
                fmt_signed(((row.get("eval_oracle") or {}).get("score") or {}).get("delta_vs_market")),
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
    parser = argparse.ArgumentParser(description="Validate forecast-side rank repair policies on chronological splits.")
    parser.add_argument("rows", nargs="+", help="One or more Item-69-style candidate row CSV exports.")
    parser.add_argument("--markets", default=None, help="Optional comma-separated market ids to include.")
    parser.add_argument("--factor-grid", default=None)
    parser.add_argument("--policies", default=None)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = build_payload(
        rows_paths=args.rows,
        markets=parse_markets(args.markets),
        factor_grid=args.factor_grid,
        policies_csv=args.policies,
        market_tol=args.market_tol,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"Forecast-side rank validation: {payload['readiness_status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
