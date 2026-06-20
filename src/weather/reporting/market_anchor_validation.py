"""Chronological validation for market-informed anchor repairs.

This is development evidence, not promotion evidence. It asks whether sparse
CLOB midpoint or full snapshot market-price anchors can repair blocked replay
markets when the anchor policy is selected on earlier market-days and evaluated
on later market-days.
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


SCHEMA_VERSION = "market_anchor_time_split_validation_v0.2"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "market_anchor_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "market_anchor_validation_report.md"
DEFAULT_ALPHA_GRID = (0.0, 0.10, 0.25, 0.50, 0.75, 1.0)
DEFAULT_SOURCES = ("candidate", "clob_midpoint")
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MIN_TRAIN_CLOB_ANCHOR_COVERAGE = 0.05
MARKET_INFORMED_SOURCES = {"clob_midpoint", "market_yes"}


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


def parse_alpha_grid(value: str | None) -> list[float]:
    values = []
    for item in parse_csv_list(value, DEFAULT_ALPHA_GRID):
        alpha = max(0.0, min(1.0, float(item)))
        if alpha not in values:
            values.append(alpha)
    return sorted(values) or [0.0]


def parse_sources(value: str | None) -> list[str]:
    sources = []
    for source in parse_csv_list(value, DEFAULT_SOURCES):
        source = source.strip().lower()
        if source not in {"candidate", "clob_midpoint", "market_yes"}:
            raise ValueError(f"Unknown market-anchor source: {source}")
        if source not in sources:
            sources.append(source)
    return sources or ["candidate"]


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
                clob_midpoint = safe_float(source.get("clob_midpoint"))
                rows.append({
                    "market_id": market_id,
                    "target_date": target_date,
                    "snapshot_id": snapshot_id,
                    "band_key": source.get("band_key") or "",
                    "probability": clamp_probability(probability),
                    "current_probability": clamp_probability(current_probability),
                    "market_probability": clamp_probability(market_probability),
                    "outcome": int(outcome),
                    "clob_midpoint": clamp_probability(clob_midpoint) if clob_midpoint is not None else None,
                    "clob_spread": safe_float(source.get("clob_spread")),
                    "clob_liquidity_score": safe_float(source.get("clob_liquidity_score")),
                    "clob_feature_available": safe_float(source.get("clob_feature_available")),
                })
    return rows


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    q = max(0.0, min(1.0, float(q)))
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * q))
    return ordered[index]


def split_market_dates(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    dates_by_market: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        dates_by_market[row["market_id"]].add(row["target_date"])
    output = {}
    for market_id, date_set in sorted(dates_by_market.items()):
        dates = sorted(date_set)
        if len(dates) <= 1:
            train_dates = dates
            eval_dates: list[str] = []
        else:
            cut = max(1, len(dates) // 2)
            train_dates = dates[:cut]
            eval_dates = dates[cut:]
        output[market_id] = {
            "train_dates": train_dates,
            "eval_dates": eval_dates,
        }
    return output


def rows_for_dates(rows: list[dict[str, Any]], market_id: str, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [
        row for row in rows
        if row["market_id"] == market_id and row["target_date"] in date_set
    ]


def anchor_value(
    row: dict[str, Any],
    source: str,
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
) -> float | None:
    if source == "candidate":
        return None
    if source == "market_yes":
        return float(row["market_probability"])
    if source == "clob_midpoint":
        midpoint = row.get("clob_midpoint")
        if midpoint is None:
            return None
        spread = row.get("clob_spread")
        liquidity = row.get("clob_liquidity_score")
        if max_clob_spread is not None and (spread is None or spread > max_clob_spread):
            return None
        if min_clob_liquidity is not None and (liquidity is None or liquidity < min_clob_liquidity):
            return None
        return float(midpoint)
    raise ValueError(f"Unknown market-anchor source: {source}")


def anchored_probability(
    row: dict[str, Any],
    source: str,
    alpha: float,
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
) -> tuple[float, bool]:
    base = float(row["probability"])
    anchor = anchor_value(
        row,
        source,
        max_clob_spread=max_clob_spread,
        min_clob_liquidity=min_clob_liquidity,
    )
    if source == "candidate" or anchor is None or alpha <= 0:
        return clamp_probability(base), False
    alpha = max(0.0, min(1.0, float(alpha)))
    return clamp_probability((1.0 - alpha) * base + alpha * anchor), True


def score_rows(
    rows: list[dict[str, Any]],
    source: str,
    alpha: float,
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "anchor_coverage": None,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    candidate_losses = []
    current_losses = []
    market_losses = []
    anchored_count = 0
    for row in rows:
        probability, used_anchor = anchored_probability(
            row,
            source,
            alpha,
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        anchored_count += int(used_anchor)
        outcome = int(row["outcome"])
        candidate_losses.append(brier(probability, outcome))
        current_losses.append(brier(float(row["current_probability"]), outcome))
        market_losses.append(brier(float(row["market_probability"]), outcome))
    candidate_brier = sum(candidate_losses) / len(candidate_losses)
    current_brier = sum(current_losses) / len(current_losses)
    market_brier = sum(market_losses) / len(market_losses)
    return {
        "rows": len(rows),
        "anchor_coverage": anchored_count / len(rows),
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": candidate_brier - current_brier,
        "delta_vs_market": candidate_brier - market_brier,
    }


def clob_stability_summary(
    rows: list[dict[str, Any]],
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
) -> dict[str, Any]:
    anchor_rows = [
        row for row in rows
        if anchor_value(
            row,
            "clob_midpoint",
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        ) is not None
    ]
    if not rows:
        return {
            "rows": 0,
            "anchor_rows": 0,
            "anchor_coverage": None,
            "candidate_brier": None,
            "clob_brier": None,
            "market_brier": None,
            "delta_clob_vs_candidate": None,
            "delta_clob_vs_market": None,
            "spread_mean": None,
            "spread_p90": None,
            "liquidity_mean": None,
            "liquidity_p10": None,
        }
    if not anchor_rows:
        return {
            "rows": len(rows),
            "anchor_rows": 0,
            "anchor_coverage": 0.0,
            "candidate_brier": None,
            "clob_brier": None,
            "market_brier": None,
            "delta_clob_vs_candidate": None,
            "delta_clob_vs_market": None,
            "spread_mean": None,
            "spread_p90": None,
            "liquidity_mean": None,
            "liquidity_p10": None,
        }
    candidate_losses = []
    clob_losses = []
    market_losses = []
    spreads = []
    liquidities = []
    for row in anchor_rows:
        outcome = int(row["outcome"])
        midpoint = anchor_value(
            row,
            "clob_midpoint",
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        candidate_losses.append(brier(float(row["probability"]), outcome))
        clob_losses.append(brier(float(midpoint), outcome))
        market_losses.append(brier(float(row["market_probability"]), outcome))
        if row.get("clob_spread") is not None:
            spreads.append(float(row["clob_spread"]))
        if row.get("clob_liquidity_score") is not None:
            liquidities.append(float(row["clob_liquidity_score"]))
    candidate_brier = mean(candidate_losses)
    clob_brier = mean(clob_losses)
    market_brier = mean(market_losses)
    return {
        "rows": len(rows),
        "anchor_rows": len(anchor_rows),
        "anchor_coverage": len(anchor_rows) / len(rows),
        "candidate_brier": candidate_brier,
        "clob_brier": clob_brier,
        "market_brier": market_brier,
        "delta_clob_vs_candidate": (
            clob_brier - candidate_brier
            if clob_brier is not None and candidate_brier is not None
            else None
        ),
        "delta_clob_vs_market": (
            clob_brier - market_brier
            if clob_brier is not None and market_brier is not None
            else None
        ),
        "spread_mean": mean(spreads),
        "spread_p90": quantile(spreads, 0.90),
        "liquidity_mean": mean(liquidities),
        "liquidity_p10": quantile(liquidities, 0.10),
    }


def clob_anchor_train_coverage_gate(
    train_summary: dict[str, Any],
    sources: list[str],
    min_train_coverage: float = DEFAULT_MIN_TRAIN_CLOB_ANCHOR_COVERAGE,
) -> dict[str, Any]:
    """Fail closed when a CLOB midpoint selector has no train-side evidence."""
    applies = "clob_midpoint" in set(sources or [])
    coverage = train_summary.get("anchor_coverage")
    anchor_rows = int(train_summary.get("anchor_rows") or 0)
    if not applies:
        return {
            "status": "NOT_APPLICABLE",
            "applies": False,
            "min_train_anchor_coverage": float(min_train_coverage),
            "train_anchor_coverage": coverage,
            "train_anchor_rows": anchor_rows,
            "reason": "clob_midpoint source not evaluated",
        }
    ok = (
        coverage is not None
        and float(coverage) >= float(min_train_coverage)
        and anchor_rows > 0
    )
    return {
        "status": "PASS" if ok else "BLOCK",
        "applies": True,
        "min_train_anchor_coverage": float(min_train_coverage),
        "train_anchor_coverage": coverage,
        "train_anchor_rows": anchor_rows,
        "reason": (
            "train-side CLOB midpoint coverage clears selector threshold"
            if ok else
            (
                "train-side CLOB midpoint coverage below selector threshold "
                f"({float(coverage or 0.0):.4f} < {float(min_train_coverage):.4f})"
            )
        ),
    }


def score_daily_first(
    rows: list[dict[str, Any]],
    policy_by_market: dict[str, dict[str, Any]],
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    if not grouped:
        return {"market_days": 0}
    scores = []
    for (market_id, _target_date), group_rows in grouped.items():
        policy = policy_by_market.get(market_id) or {"source": "candidate", "alpha": 0.0}
        scores.append(score_rows(
            group_rows,
            str(policy.get("source", "candidate")),
            float(policy.get("alpha", 0.0)),
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        ))
    keys = ("candidate_brier", "current_brier", "market_brier", "delta_vs_current", "delta_vs_market")
    return {
        "market_days": len(scores),
        **{
            key: sum(score[key] for score in scores if score.get(key) is not None) / len(scores)
            for key in keys
        },
        "anchor_coverage": sum(score.get("anchor_coverage") or 0.0 for score in scores) / len(scores),
    }


def candidate_policies(sources: list[str], alpha_grid: list[float]) -> list[dict[str, Any]]:
    policies = [{"source": "candidate", "alpha": 0.0}]
    for source in sources:
        if source == "candidate":
            continue
        for alpha in alpha_grid:
            if alpha <= 0:
                continue
            policies.append({"source": source, "alpha": float(alpha)})
    return policies


def select_policy(
    rows: list[dict[str, Any]],
    sources: list[str],
    alpha_grid: list[float],
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
) -> dict[str, Any]:
    candidates = []
    for policy in candidate_policies(sources, alpha_grid):
        score = score_rows(
            rows,
            policy["source"],
            policy["alpha"],
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        candidates.append({
            **policy,
            "candidate_brier": score["candidate_brier"],
            "delta_vs_current": score["delta_vs_current"],
            "delta_vs_market": score["delta_vs_market"],
            "anchor_coverage": score["anchor_coverage"],
        })
    candidates.sort(key=lambda item: (
        math.inf if item.get("candidate_brier") is None else item["candidate_brier"],
        item["source"],
        item["alpha"],
    ))
    return candidates[0] if candidates else {"source": "candidate", "alpha": 0.0}


def build_payload(
    rows_paths: list[str | Path],
    sources_csv: str | None = None,
    alpha_grid: str | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
    max_clob_spread: float | None = None,
    min_clob_liquidity: float | None = None,
    min_train_clob_anchor_coverage: float = DEFAULT_MIN_TRAIN_CLOB_ANCHOR_COVERAGE,
) -> dict[str, Any]:
    rows = read_rows(rows_paths)
    sources = parse_sources(sources_csv)
    alphas = parse_alpha_grid(alpha_grid)
    split = split_market_dates(rows)
    train_rows_all = []
    eval_rows_all = []
    selected_policy_by_market = {}
    oracle_policy_by_market = {}
    market_results = []
    for market_id, market_split in sorted(split.items()):
        train_rows = rows_for_dates(rows, market_id, market_split["train_dates"])
        eval_rows = rows_for_dates(rows, market_id, market_split["eval_dates"])
        train_rows_all.extend(train_rows)
        eval_rows_all.extend(eval_rows)
        selected = select_policy(
            train_rows,
            sources,
            alphas,
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        oracle = select_policy(
            eval_rows,
            sources,
            alphas,
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        selected_policy_by_market[market_id] = selected
        oracle_policy_by_market[market_id] = oracle
        selected_eval = score_rows(
            eval_rows,
            selected["source"],
            selected["alpha"],
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        baseline_eval = score_rows(eval_rows, "candidate", 0.0)
        oracle_eval = score_rows(
            eval_rows,
            oracle["source"],
            oracle["alpha"],
            max_clob_spread=max_clob_spread,
            min_clob_liquidity=min_clob_liquidity,
        )
        market_results.append({
            "market_id": market_id,
            "train_dates": market_split["train_dates"],
            "eval_dates": market_split["eval_dates"],
            "selected_source": selected["source"],
            "selected_alpha": selected["alpha"],
            "selected_train_score": {
                "candidate_brier": selected.get("candidate_brier"),
                "delta_vs_current": selected.get("delta_vs_current"),
                "delta_vs_market": selected.get("delta_vs_market"),
                "anchor_coverage": selected.get("anchor_coverage"),
            },
            "oracle_eval_source": oracle["source"],
            "oracle_eval_alpha": oracle["alpha"],
            "baseline_eval": baseline_eval,
            "eval": selected_eval,
            "oracle_eval": oracle_eval,
            "clob_stability": {
                "train": clob_stability_summary(
                    train_rows,
                    max_clob_spread=max_clob_spread,
                    min_clob_liquidity=min_clob_liquidity,
                ),
                "eval": clob_stability_summary(
                    eval_rows,
                    max_clob_spread=max_clob_spread,
                    min_clob_liquidity=min_clob_liquidity,
                ),
            },
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
    selected_daily = score_daily_first(
        eval_rows_all,
        selected_policy_by_market,
        max_clob_spread=max_clob_spread,
        min_clob_liquidity=min_clob_liquidity,
    )
    baseline_daily = score_daily_first(
        eval_rows_all,
        {market_id: {"source": "candidate", "alpha": 0.0} for market_id in selected_policy_by_market},
        max_clob_spread=max_clob_spread,
        min_clob_liquidity=min_clob_liquidity,
    )
    oracle_daily = score_daily_first(
        eval_rows_all,
        oracle_policy_by_market,
        max_clob_spread=max_clob_spread,
        min_clob_liquidity=min_clob_liquidity,
    )
    train_clob_summary = clob_stability_summary(
        train_rows_all,
        max_clob_spread=max_clob_spread,
        min_clob_liquidity=min_clob_liquidity,
    )
    eval_clob_summary = clob_stability_summary(
        eval_rows_all,
        max_clob_spread=max_clob_spread,
        min_clob_liquidity=min_clob_liquidity,
    )
    clob_gate = clob_anchor_train_coverage_gate(
        train_clob_summary,
        sources,
        min_train_coverage=min_train_clob_anchor_coverage,
    )
    market_holdouts_pass = bool(market_results) and all(
        row["holdout_status"] == "PASS"
        for row in market_results
    )
    readiness_status = (
        "PASS"
        if market_holdouts_pass and clob_gate.get("status") in ("PASS", "NOT_APPLICABLE")
        else "BLOCK"
    )
    blockers = [
        row for row in market_results
        if row["holdout_status"] != "PASS"
    ]
    if clob_gate.get("status") == "BLOCK":
        blockers.append({
            "market_id": "all",
            "holdout_status": "BLOCK",
            "selected_source": "clob_midpoint",
            "selected_alpha": None,
            "blocker": "clob_anchor_train_coverage",
            "reason": clob_gate.get("reason"),
            "clob_stability": {
                "train": train_clob_summary,
                "eval": eval_clob_summary,
            },
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "sources": sources,
        "alpha_grid": alphas,
        "market_tol": float(market_tol),
        "max_clob_spread": max_clob_spread,
        "min_clob_liquidity": min_clob_liquidity,
        "min_train_clob_anchor_coverage": float(min_train_clob_anchor_coverage),
        "evidence_classification": "development_time_split_not_promotion_evidence",
        "market_informed_disclaimer": (
            "CLOB midpoint and market_yes anchors use live market information. They can measure "
            "serving-safety or microstructure value, but market_yes anchoring is not model edge."
        ),
        "no_leakage_audit": {
            "status": "PASS" if eval_rows_all else "WARN",
            "primary_evidence_unit": "market_day",
            "detail": "Anchor source and alpha are selected on earlier target dates and evaluated on later target dates.",
        },
        "row_counts": {
            "total": len(rows),
            "train": len(train_rows_all),
            "eval": len(eval_rows_all),
        },
        "selected_policy_by_market": selected_policy_by_market,
        "oracle_eval_policy_by_market": oracle_policy_by_market,
        "clob_anchor_train_coverage_gate": clob_gate,
        "clob_stability": {
            "train": train_clob_summary,
            "eval": eval_clob_summary,
        },
        "baseline": {
            "eval_daily_first": baseline_daily,
        },
        "selected": {
            "eval_daily_first": selected_daily,
        },
        "oracle_eval": {
            "eval_daily_first": oracle_daily,
        },
        "market_results": market_results,
        "readiness_status": readiness_status,
        "blockers": blockers,
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
    oracle_daily = payload.get("oracle_eval", {}).get("eval_daily_first") or {}
    lines = [
        "# Market-Anchor Time-Split Validation",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "Evidence classification: development diagnostic, not promotion evidence.",
        "",
        payload.get("market_informed_disclaimer") or "",
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
            ["Sources", ", ".join(payload.get("sources") or [])],
            ["Alpha grid", ", ".join(str(value) for value in payload.get("alpha_grid") or [])],
            ["Max CLOB spread", fmt_num(payload.get("max_clob_spread"))],
            ["Min CLOB liquidity", fmt_num(payload.get("min_clob_liquidity"))],
            ["Min train CLOB anchor coverage", fmt_num(payload.get("min_train_clob_anchor_coverage"))],
        ],
    )
    lines += [
        "",
        "## Daily-First Holdout",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Candidate", "Current", "Market", "Delta Current", "Delta Market", "Anchor Coverage"],
        [
            [
                "selected",
                fmt_num(selected_daily.get("candidate_brier")),
                fmt_num(selected_daily.get("current_brier")),
                fmt_num(selected_daily.get("market_brier")),
                fmt_signed(selected_daily.get("delta_vs_current")),
                fmt_signed(selected_daily.get("delta_vs_market")),
                fmt_num(selected_daily.get("anchor_coverage")),
            ],
            [
                "baseline",
                fmt_num(baseline_daily.get("candidate_brier")),
                fmt_num(baseline_daily.get("current_brier")),
                fmt_num(baseline_daily.get("market_brier")),
                fmt_signed(baseline_daily.get("delta_vs_current")),
                fmt_signed(baseline_daily.get("delta_vs_market")),
                fmt_num(baseline_daily.get("anchor_coverage")),
            ],
            [
                "oracle eval best",
                fmt_num(oracle_daily.get("candidate_brier")),
                fmt_num(oracle_daily.get("current_brier")),
                fmt_num(oracle_daily.get("market_brier")),
                fmt_signed(oracle_daily.get("delta_vs_current")),
                fmt_signed(oracle_daily.get("delta_vs_market")),
                fmt_num(oracle_daily.get("anchor_coverage")),
            ],
        ],
    )
    lines += [
        "",
        "## CLOB Stability",
        "",
    ]
    clob = payload.get("clob_stability") or {}
    train_clob = clob.get("train") or {}
    eval_clob = clob.get("eval") or {}
    clob_gate = payload.get("clob_anchor_train_coverage_gate") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Train coverage gate", clob_gate.get("status")],
            ["Gate reason", clob_gate.get("reason")],
            ["Min train anchor coverage", fmt_num(clob_gate.get("min_train_anchor_coverage"))],
            ["Train anchor coverage", fmt_num(clob_gate.get("train_anchor_coverage"))],
            ["Train anchor rows", clob_gate.get("train_anchor_rows")],
        ],
    )
    lines += [
        "",
    ]
    lines += markdown_table(
        ["Scope", "Coverage", "Candidate", "CLOB", "Market", "CLOB vs Candidate", "CLOB vs Market"],
        [
            [
                "train",
                fmt_num(train_clob.get("anchor_coverage")),
                fmt_num(train_clob.get("candidate_brier")),
                fmt_num(train_clob.get("clob_brier")),
                fmt_num(train_clob.get("market_brier")),
                fmt_signed(train_clob.get("delta_clob_vs_candidate")),
                fmt_signed(train_clob.get("delta_clob_vs_market")),
            ],
            [
                "eval",
                fmt_num(eval_clob.get("anchor_coverage")),
                fmt_num(eval_clob.get("candidate_brier")),
                fmt_num(eval_clob.get("clob_brier")),
                fmt_num(eval_clob.get("market_brier")),
                fmt_signed(eval_clob.get("delta_clob_vs_candidate")),
                fmt_signed(eval_clob.get("delta_clob_vs_market")),
            ],
        ],
    )
    lines += [
        "",
        "## CLOB Stability By Market",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Train Cov",
            "Train CLOB-Cand",
            "Eval Cov",
            "Eval CLOB-Cand",
            "Eval CLOB-Market",
            "Eval Spread P90",
            "Eval Liquidity P10",
        ],
        [
            [
                row.get("market_id"),
                fmt_num(((row.get("clob_stability") or {}).get("train") or {}).get("anchor_coverage")),
                fmt_signed(((row.get("clob_stability") or {}).get("train") or {}).get("delta_clob_vs_candidate")),
                fmt_num(((row.get("clob_stability") or {}).get("eval") or {}).get("anchor_coverage")),
                fmt_signed(((row.get("clob_stability") or {}).get("eval") or {}).get("delta_clob_vs_candidate")),
                fmt_signed(((row.get("clob_stability") or {}).get("eval") or {}).get("delta_clob_vs_market")),
                fmt_num(((row.get("clob_stability") or {}).get("eval") or {}).get("spread_p90")),
                fmt_num(((row.get("clob_stability") or {}).get("eval") or {}).get("liquidity_p10")),
            ]
            for row in payload.get("market_results") or []
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
            "Selected",
            "Train Dates",
            "Eval Dates",
            "Baseline",
            "Candidate",
            "Market",
            "Delta Market",
            "Coverage",
            "Oracle Eval",
            "Status",
        ],
        [
            [
                row.get("market_id"),
                f"{row.get('selected_source')}:{fmt_num(row.get('selected_alpha'))}",
                ", ".join(row.get("train_dates") or []),
                ", ".join(row.get("eval_dates") or []),
                fmt_num((row.get("baseline_eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("market_brier")),
                fmt_signed((row.get("eval") or {}).get("delta_vs_market")),
                fmt_num((row.get("eval") or {}).get("anchor_coverage")),
                (
                    f"{row.get('oracle_eval_source')}:{fmt_num(row.get('oracle_eval_alpha'))} "
                    f"{fmt_signed((row.get('oracle_eval') or {}).get('delta_vs_market'))}"
                ),
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
    parser = argparse.ArgumentParser(description="Validate market-informed anchor repairs on chronological splits.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports to evaluate.")
    parser.add_argument("--sources", default=None, help="Comma-separated candidate,clob_midpoint,market_yes.")
    parser.add_argument("--alpha-grid", default=None)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--max-clob-spread", type=float, default=None)
    parser.add_argument("--min-clob-liquidity", type=float, default=None)
    parser.add_argument(
        "--min-train-clob-anchor-coverage",
        type=float,
        default=DEFAULT_MIN_TRAIN_CLOB_ANCHOR_COVERAGE,
        help="Minimum train-side CLOB midpoint anchor coverage required when clob_midpoint is evaluated.",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = build_payload(
        rows_paths=args.rows,
        sources_csv=args.sources,
        alpha_grid=args.alpha_grid,
        market_tol=args.market_tol,
        max_clob_spread=args.max_clob_spread,
        min_clob_liquidity=args.min_clob_liquidity,
        min_train_clob_anchor_coverage=args.min_train_clob_anchor_coverage,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"Market-anchor validation: {payload['readiness_status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
