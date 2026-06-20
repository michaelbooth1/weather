"""Chronological validation for selecting among existing no-market variants.

This is development evidence only. It asks whether already generated variant
branches can be combined per market using only earlier settled market-days,
then evaluates that selected basket on later market-days.
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


SCHEMA_VERSION = "variant_basket_selection_validation_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "variant_basket_selection_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "variant_basket_selection_validation_report.md"
DEFAULT_MARKET_TOL = 0.003
DEFAULT_SLICE_KEYS = (
    "cutoff_regime",
    "cutoff_hour",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "bin_type",
    "settlement_distance_bucket",
    "source_freshness_state",
)
DEFAULT_GUARD_POLICIES = (
    "current",
    "all_variant",
    "all_fresh",
    "not_failed_wu",
    "not_early",
    "midday_late",
    "warm_side",
    "not_near_forecast",
    "all_fresh_midday_late",
)


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
    return max(0.0, min(1.0, float(value)))


def parse_markets(value: str | None) -> set[str] | None:
    if not value:
        return None
    markets = {item.strip() for item in str(value).split(",") if item.strip()}
    return markets or None


def brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def normalize_variant_row(row: dict[str, Any], source_path: str | Path | None = None) -> dict[str, Any] | None:
    market_id = row.get("market_id") or ""
    target_date = row.get("target_date") or ""
    snapshot_id = row.get("snapshot_id") or ""
    band_key = row.get("band_key") or row.get("range_label") or ""
    probability = _safe_float(row.get("probability"))
    current_probability = _safe_float(row.get("current_probability"))
    market_probability = _safe_float(row.get("market_yes") or row.get("market_probability"))
    outcome = _safe_int(row.get("outcome"))
    if (
        not market_id
        or not target_date
        or not snapshot_id
        or not band_key
        or probability is None
        or current_probability is None
        or market_probability is None
        or outcome not in {0, 1}
    ):
        return None
    source_name = Path(source_path).stem if source_path else "variant_rows"
    return {
        "variant_id": row.get("variant_id") or source_name,
        "variant_family": row.get("variant_family") or "",
        "market_id": market_id,
        "target_date": target_date,
        "snapshot_id": snapshot_id,
        "band_key": band_key,
        "observation_key": (market_id, target_date, snapshot_id, band_key),
        "probability": _clamp_probability(probability),
        "current_probability": _clamp_probability(current_probability),
        "market_probability": _clamp_probability(market_probability),
        "outcome": int(outcome),
        "source_path": str(source_path) if source_path else "",
        "cutoff_regime": row.get("cutoff_regime") or row.get("candidate_cutoff_regime") or "",
        "cutoff_hour": row.get("cutoff_hour") or row.get("candidate_cutoff_hour") or "",
        "forecast_disagreement_bucket": row.get("forecast_disagreement_bucket") or "",
        "forecast_bucket_pressure": row.get("forecast_bucket_pressure") or "",
        "bin_type": row.get("bin_type") or "",
        "settlement_distance_bucket": row.get("settlement_distance_bucket") or row.get("settlement_distance") or "",
        "source_freshness_state": row.get("source_freshness_state") or row.get("source_status_group") or "",
    }


def read_variant_rows(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            for source in csv.DictReader(handle):
                row = normalize_variant_row(source, source_path=path)
                if row is not None:
                    rows.append(row)
    return rows


def add_current_control(rows: list[dict[str, Any]], variant_id: str = "current") -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        seen.setdefault(row["observation_key"], row)
    controls = []
    for row in seen.values():
        controls.append({
            **row,
            "variant_id": variant_id,
            "variant_family": "current_serving_control",
            "probability": row["current_probability"],
            "source_path": "derived_current_control",
        })
    return [*rows, *controls]


def split_market_dates(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    dates_by_market: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        dates_by_market[row["market_id"]].add(row["target_date"])
    split = {}
    for market_id, dates_set in sorted(dates_by_market.items()):
        dates = sorted(dates_set)
        if len(dates) <= 1:
            train_dates = dates
            eval_dates: list[str] = []
        else:
            cut = max(1, len(dates) // 2)
            train_dates = dates[:cut]
            eval_dates = dates[cut:]
        split[market_id] = {"train_dates": train_dates, "eval_dates": eval_dates}
    return split


def rows_for(
    rows: list[dict[str, Any]],
    *,
    market_id: str | None = None,
    variant_id: str | None = None,
    dates: set[str] | list[str] | None = None,
) -> list[dict[str, Any]]:
    date_set = set(dates or [])
    return [
        row for row in rows
        if (market_id is None or row["market_id"] == market_id)
        and (variant_id is None or row["variant_id"] == variant_id)
        and (not date_set or row["target_date"] in date_set)
    ]


def score_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    candidate = sum(brier(row["probability"], row["outcome"]) for row in rows) / len(rows)
    current = sum(brier(row["current_probability"], row["outcome"]) for row in rows) / len(rows)
    market = sum(brier(row["market_probability"], row["outcome"]) for row in rows) / len(rows)
    return {
        "rows": len(rows),
        "candidate_brier": candidate,
        "current_brier": current,
        "market_brier": market,
        "delta_vs_current": candidate - current,
        "delta_vs_market": candidate - market,
    }


def score_rows_with_probability(rows: list[dict[str, Any]], probability_fn) -> dict[str, Any]:
    if not rows:
        return score_rows([])
    candidate = sum(brier(probability_fn(row), row["outcome"]) for row in rows) / len(rows)
    current = sum(brier(row["current_probability"], row["outcome"]) for row in rows) / len(rows)
    market = sum(brier(row["market_probability"], row["outcome"]) for row in rows) / len(rows)
    return {
        "rows": len(rows),
        "candidate_brier": candidate,
        "current_brier": current,
        "market_brier": market,
        "delta_vs_current": candidate - current,
        "delta_vs_market": candidate - market,
    }


def score_daily_first(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    scores = [score_rows(group_rows) for group_rows in grouped.values()]
    scores = [score for score in scores if score.get("rows")]
    if not scores:
        return {"market_days": 0, **score_rows([])}

    def avg(key: str) -> float | None:
        values = [score.get(key) for score in scores if score.get(key) is not None]
        return sum(values) / len(values) if values else None

    return {
        "market_days": len(scores),
        "rows": sum(int(score.get("rows") or 0) for score in scores),
        "candidate_brier": avg("candidate_brier"),
        "current_brier": avg("current_brier"),
        "market_brier": avg("market_brier"),
        "delta_vs_current": avg("delta_vs_current"),
        "delta_vs_market": avg("delta_vs_market"),
    }


def score_daily_first_with_probability(rows: list[dict[str, Any]], probability_fn) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    scores = [score_rows_with_probability(group_rows, probability_fn) for group_rows in grouped.values()]
    scores = [score for score in scores if score.get("rows")]
    if not scores:
        return {"market_days": 0, **score_rows([])}

    def avg(key: str) -> float | None:
        values = [score.get(key) for score in scores if score.get(key) is not None]
        return sum(values) / len(values) if values else None

    return {
        "market_days": len(scores),
        "rows": sum(int(score.get("rows") or 0) for score in scores),
        "candidate_brier": avg("candidate_brier"),
        "current_brier": avg("current_brier"),
        "market_brier": avg("market_brier"),
        "delta_vs_current": avg("delta_vs_current"),
        "delta_vs_market": avg("delta_vs_market"),
    }


def _score_sort_key(score: dict[str, Any], variant_id: str) -> tuple[float, str]:
    value = score.get("candidate_brier")
    return (math.inf if value is None else float(value), variant_id)


def select_variant_for_market(
    rows: list[dict[str, Any]],
    market_id: str,
    train_dates: list[str],
) -> dict[str, Any]:
    variant_ids = sorted({row["variant_id"] for row in rows if row["market_id"] == market_id})
    candidates = []
    for variant_id in variant_ids:
        train_rows = rows_for(rows, market_id=market_id, variant_id=variant_id, dates=train_dates)
        score = score_daily_first(train_rows)
        candidates.append({"variant_id": variant_id, "train_daily_first": score})
    candidates.sort(key=lambda row: _score_sort_key(row["train_daily_first"], row["variant_id"]))
    selected = candidates[0] if candidates else {"variant_id": None, "train_daily_first": score_daily_first([])}
    return {
        "selected_variant_id": selected["variant_id"],
        "selection_score": selected["train_daily_first"],
        "candidates": candidates,
    }


def oracle_variant_for_market(
    rows: list[dict[str, Any]],
    market_id: str,
    eval_dates: list[str],
) -> dict[str, Any]:
    variant_ids = sorted({row["variant_id"] for row in rows if row["market_id"] == market_id})
    candidates = []
    for variant_id in variant_ids:
        eval_rows = rows_for(rows, market_id=market_id, variant_id=variant_id, dates=eval_dates)
        score = score_daily_first(eval_rows)
        candidates.append({"variant_id": variant_id, "eval_daily_first": score})
    candidates.sort(key=lambda row: _score_sort_key(row["eval_daily_first"], row["variant_id"]))
    selected = candidates[0] if candidates else {"variant_id": None, "eval_daily_first": score_daily_first([])}
    return {
        "oracle_variant_id": selected["variant_id"],
        "oracle_score": selected["eval_daily_first"],
    }


def evaluate_leave_one_date_selection(
    rows: list[dict[str, Any]],
    market_tol: float,
) -> list[dict[str, Any]]:
    """Select on all but one market-day, then score the held-out day."""
    split_dates: dict[str, list[str]] = {
        market_id: sorted({row["target_date"] for row in rows if row["market_id"] == market_id})
        for market_id in sorted({row["market_id"] for row in rows})
    }
    results = []
    for market_id, dates in split_dates.items():
        selected_rows_all = []
        current_rows_all = []
        oracle_rows_all = []
        date_results = []
        for eval_date in dates:
            train_dates = [date for date in dates if date != eval_date]
            if not train_dates:
                continue
            selection = select_variant_for_market(rows, market_id, train_dates)
            selected_variant_id = selection["selected_variant_id"]
            selected_eval = rows_for(
                rows,
                market_id=market_id,
                variant_id=selected_variant_id,
                dates=[eval_date],
            )
            current_eval = rows_for(
                rows,
                market_id=market_id,
                variant_id="current",
                dates=[eval_date],
            )
            oracle = oracle_variant_for_market(rows, market_id, [eval_date])
            oracle_eval = rows_for(
                rows,
                market_id=market_id,
                variant_id=oracle["oracle_variant_id"],
                dates=[eval_date],
            )
            selected_score = score_daily_first(selected_eval)
            current_score = score_daily_first(current_eval)
            oracle_score = oracle["oracle_score"]
            selected_rows_all.extend(selected_eval)
            current_rows_all.extend(current_eval)
            oracle_rows_all.extend(oracle_eval)
            date_results.append({
                "eval_date": eval_date,
                "train_dates": train_dates,
                "selected_variant_id": selected_variant_id,
                "selected_eval": selected_score,
                "current_eval": current_score,
                "eval_oracle_variant_id": oracle["oracle_variant_id"],
                "eval_oracle": oracle_score,
            })
        selected_score = score_daily_first(selected_rows_all)
        current_score = score_daily_first(current_rows_all)
        oracle_score = score_daily_first(oracle_rows_all)
        selected_counts: dict[str, int] = defaultdict(int)
        oracle_counts: dict[str, int] = defaultdict(int)
        for row in date_results:
            selected_counts[str(row.get("selected_variant_id") or "-")] += 1
            oracle_counts[str(row.get("eval_oracle_variant_id") or "-")] += 1
        reasons = []
        if selected_score.get("delta_vs_market") is not None and selected_score["delta_vs_market"] > market_tol:
            reasons.append(f"leave-one-day selected delta_vs_market {fmt_signed(selected_score['delta_vs_market'])} > {fmt_signed(market_tol)}")
        if selected_score.get("delta_vs_current") is not None and selected_score["delta_vs_current"] > 0:
            reasons.append("leave-one-day selected regresses current")
        results.append({
            "market_id": market_id,
            "status": "blocked" if reasons else "pass",
            "reasons": reasons,
            "dates": dates,
            "date_count": len(date_results),
            "selected_eval": selected_score,
            "current_eval": current_score,
            "eval_oracle": oracle_score,
            "selected_variant_counts": dict(sorted(selected_counts.items())),
            "eval_oracle_variant_counts": dict(sorted(oracle_counts.items())),
            "date_results": date_results,
        })
    return results


def guard_policy_matches(row: dict[str, Any], policy: str) -> bool:
    policy = str(policy or "current")
    if policy == "current":
        return False
    if policy == "all_variant":
        return True
    if policy == "all_fresh":
        return row.get("source_freshness_state") == "all_fresh"
    if policy == "not_failed_wu":
        return row.get("source_freshness_state") != "failed:wu_history"
    if policy == "not_early":
        return row.get("cutoff_regime") != "early"
    if policy == "midday_late":
        return row.get("cutoff_regime") in {"midday", "late"}
    if policy == "warm_side":
        return row.get("forecast_bucket_pressure") == "warm_side"
    if policy == "not_near_forecast":
        return row.get("forecast_bucket_pressure") != "near_forecast"
    if policy == "all_fresh_midday_late":
        return row.get("source_freshness_state") == "all_fresh" and row.get("cutoff_regime") in {
            "midday",
            "late",
        }
    raise ValueError(f"Unknown guard policy: {policy}")


def guarded_probability(row: dict[str, Any], policy: str) -> float:
    return row["probability"] if guard_policy_matches(row, policy) else row["current_probability"]


def select_guard_policy(
    rows: list[dict[str, Any]],
    policies: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    candidates = []
    for policy in policies:
        score = score_daily_first_with_probability(
            rows,
            lambda row, policy=policy: guarded_probability(row, policy),
        )
        candidates.append({"policy": policy, "train_daily_first": score})
    candidates.sort(key=lambda row: (
        math.inf if row["train_daily_first"].get("candidate_brier") is None else row["train_daily_first"]["candidate_brier"],
        row["policy"],
    ))
    selected = candidates[0] if candidates else {"policy": "current", "train_daily_first": score_daily_first([])}
    return {
        "selected_policy": selected["policy"],
        "selection_score": selected["train_daily_first"],
        "candidates": candidates,
    }


def evaluate_guard_policies(
    rows: list[dict[str, Any]],
    market_tol: float,
    policies: tuple[str, ...] | list[str] = DEFAULT_GUARD_POLICIES,
) -> list[dict[str, Any]]:
    results = []
    variant_ids = sorted({row["variant_id"] for row in rows if row["variant_id"] != "current"})
    market_ids = sorted({row["market_id"] for row in rows})
    for market_id in market_ids:
        dates = sorted({row["target_date"] for row in rows if row["market_id"] == market_id})
        for variant_id in variant_ids:
            variant_rows = rows_for(rows, market_id=market_id, variant_id=variant_id)
            if not variant_rows:
                continue
            fixed_candidates = []
            for policy in policies:
                score = score_daily_first_with_probability(
                    variant_rows,
                    lambda row, policy=policy: guarded_probability(row, policy),
                )
                fixed_candidates.append({"policy": policy, "score": score})
            fixed_candidates.sort(key=lambda row: (
                math.inf if row["score"].get("candidate_brier") is None else row["score"]["candidate_brier"],
                row["policy"],
            ))
            best_fixed = fixed_candidates[0] if fixed_candidates else {"policy": "current", "score": score_daily_first([])}

            selected_eval_rows = []
            current_eval_rows = []
            date_results = []
            selected_counts: dict[str, int] = defaultdict(int)
            for eval_date in dates:
                train_dates = [date for date in dates if date != eval_date]
                if not train_dates:
                    continue
                train_rows = rows_for(
                    rows,
                    market_id=market_id,
                    variant_id=variant_id,
                    dates=train_dates,
                )
                eval_rows = rows_for(
                    rows,
                    market_id=market_id,
                    variant_id=variant_id,
                    dates=[eval_date],
                )
                selection = select_guard_policy(train_rows, policies)
                selected_policy = selection["selected_policy"]
                selected_counts[selected_policy] += 1
                selected_score = score_daily_first_with_probability(
                    eval_rows,
                    lambda row, selected_policy=selected_policy: guarded_probability(row, selected_policy),
                )
                selected_eval_rows.extend([
                    {**row, "probability": guarded_probability(row, selected_policy)}
                    for row in eval_rows
                ])
                current_eval_rows.extend([
                    {**row, "probability": row["current_probability"]}
                    for row in eval_rows
                ])
                date_results.append({
                    "eval_date": eval_date,
                    "selected_policy": selected_policy,
                    "selected_eval": selected_score,
                    "selection_score": selection["selection_score"],
                })

            selected_score = score_daily_first(selected_eval_rows)
            current_score = score_daily_first(current_eval_rows)
            reasons = []
            if selected_score.get("delta_vs_market") is not None and selected_score["delta_vs_market"] > market_tol:
                reasons.append(
                    f"train-selected guard delta_vs_market {fmt_signed(selected_score['delta_vs_market'])} > {fmt_signed(market_tol)}"
                )
            if selected_score.get("delta_vs_current") is not None and selected_score["delta_vs_current"] > 0:
                reasons.append("train-selected guard regresses current")
            results.append({
                "market_id": market_id,
                "variant_id": variant_id,
                "status": "blocked" if reasons else "pass",
                "reasons": reasons,
                "date_count": len(date_results),
                "best_fixed_policy": best_fixed["policy"],
                "best_fixed_score": best_fixed["score"],
                "train_selected_score": selected_score,
                "current_score": current_score,
                "selected_policy_counts": dict(sorted(selected_counts.items())),
                "date_results": date_results,
            })
    return results


def observation_variant_map(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, dict[str, Any]]]:
    output: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        output[row["observation_key"]][row["variant_id"]] = row
    return dict(output)


def select_variant_for_market_slice(
    rows: list[dict[str, Any]],
    market_id: str,
    slice_key: str,
    slice_value: str,
    train_dates: list[str],
    min_train_rows: int,
) -> dict[str, Any]:
    variant_ids = sorted({
        row["variant_id"]
        for row in rows
        if row["market_id"] == market_id and str(row.get(slice_key) or "") == slice_value
    })
    candidates = []
    for variant_id in variant_ids:
        train_rows = [
            row for row in rows
            if row["market_id"] == market_id
            and row["variant_id"] == variant_id
            and str(row.get(slice_key) or "") == slice_value
            and row["target_date"] in set(train_dates)
        ]
        score = score_daily_first(train_rows)
        candidates.append({"variant_id": variant_id, "train_daily_first": score})
    candidates.sort(key=lambda row: _score_sort_key(row["train_daily_first"], row["variant_id"]))
    if not candidates or int(candidates[0]["train_daily_first"].get("rows") or 0) < min_train_rows:
        return {
            "selected_variant_id": "current",
            "selection_score": score_daily_first([]),
            "reason": "insufficient_train_rows",
            "candidates": candidates,
        }
    return {
        "selected_variant_id": candidates[0]["variant_id"],
        "selection_score": candidates[0]["train_daily_first"],
        "reason": "selected_on_train",
        "candidates": candidates,
    }


def slice_values_by_market(rows: list[dict[str, Any]], slice_key: str) -> dict[str, list[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        values[row["market_id"]].add(str(row.get(slice_key) or ""))
    return {market: sorted(groups) for market, groups in values.items()}


def evaluate_slice_policy(
    rows: list[dict[str, Any]],
    split: dict[str, dict[str, list[str]]],
    slice_key: str,
    market_tol: float,
    min_train_rows: int,
) -> dict[str, Any]:
    selections = []
    selection_by_market_group: dict[tuple[str, str], str] = {}
    for market_id, values in slice_values_by_market(rows, slice_key).items():
        train_dates = (split.get(market_id) or {}).get("train_dates") or []
        for value in values:
            selection = select_variant_for_market_slice(
                rows,
                market_id,
                slice_key,
                value,
                train_dates,
                min_train_rows,
            )
            selection_by_market_group[(market_id, value)] = selection["selected_variant_id"]
            if selection["selected_variant_id"] != "current":
                selections.append({
                    "market_id": market_id,
                    "slice_key": slice_key,
                    "slice_value": value,
                    "selected_variant_id": selection["selected_variant_id"],
                    "reason": selection["reason"],
                    "train_daily_first": selection["selection_score"],
                })

    obs_map = observation_variant_map(rows)
    selected_eval_rows = []
    current_eval_rows = []
    oracle_eval_rows = []
    oracle_selections = []
    for obs_rows in obs_map.values():
        any_row = next(iter(obs_rows.values()))
        market_id = any_row["market_id"]
        eval_dates = set((split.get(market_id) or {}).get("eval_dates") or [])
        if any_row["target_date"] not in eval_dates:
            continue
        slice_value = str(any_row.get(slice_key) or "")
        selected_variant = selection_by_market_group.get((market_id, slice_value), "current")
        selected_eval_rows.append(obs_rows.get(selected_variant) or obs_rows.get("current") or any_row)
        current_eval_rows.append(obs_rows.get("current") or any_row)

    for market_id, values in slice_values_by_market(rows, slice_key).items():
        eval_dates = (split.get(market_id) or {}).get("eval_dates") or []
        for value in values:
            candidates = []
            for variant_id in sorted({
                row["variant_id"]
                for row in rows
                if row["market_id"] == market_id and str(row.get(slice_key) or "") == value
            }):
                eval_rows = [
                    row for row in rows
                    if row["market_id"] == market_id
                    and row["variant_id"] == variant_id
                    and str(row.get(slice_key) or "") == value
                    and row["target_date"] in set(eval_dates)
                ]
                candidates.append({"variant_id": variant_id, "eval_daily_first": score_daily_first(eval_rows)})
            candidates.sort(key=lambda row: _score_sort_key(row["eval_daily_first"], row["variant_id"]))
            if candidates:
                oracle_selections.append({
                    "market_id": market_id,
                    "slice_key": slice_key,
                    "slice_value": value,
                    "oracle_variant_id": candidates[0]["variant_id"],
                    "eval_daily_first": candidates[0]["eval_daily_first"],
                })

    oracle_by_market_group = {
        (row["market_id"], row["slice_value"]): row["oracle_variant_id"]
        for row in oracle_selections
    }
    for obs_rows in obs_map.values():
        any_row = next(iter(obs_rows.values()))
        market_id = any_row["market_id"]
        eval_dates = set((split.get(market_id) or {}).get("eval_dates") or [])
        if any_row["target_date"] not in eval_dates:
            continue
        slice_value = str(any_row.get(slice_key) or "")
        oracle_variant = oracle_by_market_group.get((market_id, slice_value), "current")
        oracle_eval_rows.append(obs_rows.get(oracle_variant) or obs_rows.get("current") or any_row)

    selected_score = score_daily_first(selected_eval_rows)
    oracle_score = score_daily_first(oracle_eval_rows)
    current_score = score_daily_first(current_eval_rows)
    reasons = []
    if selected_score.get("delta_vs_market") is not None and selected_score["delta_vs_market"] > market_tol:
        reasons.append(f"selected slice policy delta_vs_market {fmt_signed(selected_score['delta_vs_market'])} > {fmt_signed(market_tol)}")
    if selected_score.get("delta_vs_current") is not None and selected_score["delta_vs_current"] > 0:
        reasons.append("selected slice policy regresses current")
    return {
        "slice_key": slice_key,
        "status": "blocked" if reasons else "pass",
        "reasons": reasons,
        "selected_eval": selected_score,
        "current_eval": current_score,
        "eval_oracle": oracle_score,
        "non_current_selection_count": len(selections),
        "non_current_selections": selections,
    }


def build_payload(
    rows_paths: list[str | Path],
    markets: set[str] | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
    include_current_control: bool = True,
    slice_keys: tuple[str, ...] | list[str] = DEFAULT_SLICE_KEYS,
    min_slice_train_rows: int = 20,
) -> dict[str, Any]:
    rows = read_variant_rows(rows_paths)
    if markets:
        rows = [row for row in rows if row["market_id"] in markets]
    if include_current_control:
        rows = add_current_control(rows)

    split = split_market_dates(rows)
    market_results = []
    selected_eval_rows: list[dict[str, Any]] = []
    current_eval_rows: list[dict[str, Any]] = []
    oracle_eval_rows: list[dict[str, Any]] = []

    for market_id, market_split in sorted(split.items()):
        selection = select_variant_for_market(rows, market_id, market_split["train_dates"])
        selected_variant_id = selection["selected_variant_id"]
        selected_eval = rows_for(
            rows,
            market_id=market_id,
            variant_id=selected_variant_id,
            dates=market_split["eval_dates"],
        )
        current_eval = rows_for(
            rows,
            market_id=market_id,
            variant_id="current",
            dates=market_split["eval_dates"],
        )
        oracle = oracle_variant_for_market(rows, market_id, market_split["eval_dates"])
        oracle_eval = rows_for(
            rows,
            market_id=market_id,
            variant_id=oracle["oracle_variant_id"],
            dates=market_split["eval_dates"],
        )
        selected_eval_rows.extend(selected_eval)
        current_eval_rows.extend(current_eval)
        oracle_eval_rows.extend(oracle_eval)
        selected_score = score_daily_first(selected_eval)
        current_score = score_daily_first(current_eval)
        oracle_score = oracle["oracle_score"]
        reasons = []
        if not selected_eval:
            reasons.append("no eval rows for selected variant")
        if selected_score.get("delta_vs_market") is not None and selected_score["delta_vs_market"] > market_tol:
            reasons.append(f"selected eval delta_vs_market {fmt_signed(selected_score['delta_vs_market'])} > {fmt_signed(market_tol)}")
        if selected_score.get("delta_vs_current") is not None and selected_score["delta_vs_current"] > 0:
            reasons.append("selected eval regresses current")
        market_results.append({
            "market_id": market_id,
            "train_dates": market_split["train_dates"],
            "eval_dates": market_split["eval_dates"],
            "selected_variant_id": selected_variant_id,
            "selection_score": selection["selection_score"],
            "selected_eval": selected_score,
            "current_eval": current_score,
            "eval_oracle_variant_id": oracle["oracle_variant_id"],
            "eval_oracle": oracle_score,
            "status": "blocked" if reasons else "pass",
            "reasons": reasons,
            "candidate_train_scores": selection["candidates"],
        })

    aggregate = score_daily_first(selected_eval_rows)
    current = score_daily_first(current_eval_rows)
    oracle = score_daily_first(oracle_eval_rows)
    blockers = [
        row for row in market_results
        if row["status"] == "blocked"
    ]
    acceptance_reasons = []
    if aggregate.get("delta_vs_market") is not None and aggregate["delta_vs_market"] > market_tol:
        acceptance_reasons.append(f"selected basket delta_vs_market {fmt_signed(aggregate['delta_vs_market'])} > {fmt_signed(market_tol)}")
    if aggregate.get("delta_vs_current") is not None and aggregate["delta_vs_current"] > 0:
        acceptance_reasons.append("selected basket regresses current")
    if blockers:
        acceptance_reasons.append(f"{len(blockers)} market(s) block selected eval")
    acceptance = "blocked" if acceptance_reasons else "pass"
    slice_policy_results = [
        evaluate_slice_policy(
            rows,
            split,
            slice_key,
            market_tol=market_tol,
            min_train_rows=min_slice_train_rows,
        )
        for slice_key in slice_keys
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in rows_paths],
        "market_tol": market_tol,
        "include_current_control": include_current_control,
        "markets": sorted(split),
        "variant_ids": sorted({row["variant_id"] for row in rows}),
        "acceptance": acceptance,
        "acceptance_reasons": acceptance_reasons,
        "aggregate_selected_eval": aggregate,
        "aggregate_current_eval": current,
        "aggregate_eval_oracle": oracle,
        "market_results": market_results,
        "slice_policy_results": slice_policy_results,
        "leave_one_date_results": evaluate_leave_one_date_selection(rows, market_tol),
        "guard_policy_results": evaluate_guard_policies(rows, market_tol),
        "min_slice_train_rows": min_slice_train_rows,
    }


def _score_cell(score: dict[str, Any], key: str) -> Any:
    return fmt_num(score.get(key), 4)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    return "\n".join(markdown_table(headers, rows))


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Variant Basket Selection Validation",
        "",
        f"Generated: `{payload['generated_at_utc']}`",
        f"Schema: `{payload['schema_version']}`",
        f"Acceptance: `{payload['acceptance']}`",
        "",
        "This report selects among existing variant-row exports on earlier market-days",
        "and evaluates the selected per-market basket on later market-days.",
        "Eval oracle columns are diagnostic only and are not eligible selection evidence.",
        "",
        "## Inputs",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Rows files", ", ".join(payload.get("inputs") or [])],
                ["Variants", ", ".join(payload.get("variant_ids") or [])],
                ["Markets", ", ".join(payload.get("markets") or [])],
                ["Market tolerance", fmt_signed(payload.get("market_tol"))],
                ["Acceptance blockers", "; ".join(payload.get("acceptance_reasons") or []) or "-"],
            ],
        ),
        "",
        "## Aggregate Later-Date Evaluation",
        "",
        _table(
            ["Policy", "Market-days", "Rows", "Candidate", "Current", "Market", "Delta Current", "Delta Market"],
            [
                [
                    "selected basket",
                    (payload.get("aggregate_selected_eval") or {}).get("market_days", 0),
                    (payload.get("aggregate_selected_eval") or {}).get("rows", 0),
                    _score_cell(payload.get("aggregate_selected_eval") or {}, "candidate_brier"),
                    _score_cell(payload.get("aggregate_selected_eval") or {}, "current_brier"),
                    _score_cell(payload.get("aggregate_selected_eval") or {}, "market_brier"),
                    fmt_signed((payload.get("aggregate_selected_eval") or {}).get("delta_vs_current"), 4),
                    fmt_signed((payload.get("aggregate_selected_eval") or {}).get("delta_vs_market"), 4),
                ],
                [
                    "eval oracle",
                    (payload.get("aggregate_eval_oracle") or {}).get("market_days", 0),
                    (payload.get("aggregate_eval_oracle") or {}).get("rows", 0),
                    _score_cell(payload.get("aggregate_eval_oracle") or {}, "candidate_brier"),
                    _score_cell(payload.get("aggregate_eval_oracle") or {}, "current_brier"),
                    _score_cell(payload.get("aggregate_eval_oracle") or {}, "market_brier"),
                    fmt_signed((payload.get("aggregate_eval_oracle") or {}).get("delta_vs_current"), 4),
                    fmt_signed((payload.get("aggregate_eval_oracle") or {}).get("delta_vs_market"), 4),
                ],
            ],
        ),
        "",
        "## By Market",
        "",
        _table(
            [
                "Market",
                "Selected variant",
                "Status",
                "Train dates",
                "Eval dates",
                "Eval candidate",
                "Eval current",
                "Eval market",
                "Eval delta market",
                "Eval oracle",
                "Oracle delta market",
                "Reasons",
            ],
            [
                [
                    row["market_id"],
                    row.get("selected_variant_id") or "-",
                    row["status"],
                    ", ".join(row.get("train_dates") or []),
                    ", ".join(row.get("eval_dates") or []),
                    _score_cell(row.get("selected_eval") or {}, "candidate_brier"),
                    _score_cell(row.get("selected_eval") or {}, "current_brier"),
                    _score_cell(row.get("selected_eval") or {}, "market_brier"),
                    fmt_signed((row.get("selected_eval") or {}).get("delta_vs_market"), 4),
                    row.get("eval_oracle_variant_id") or "-",
                    fmt_signed((row.get("eval_oracle") or {}).get("delta_vs_market"), 4),
                    "; ".join(row.get("reasons") or []) or "-",
                ]
                for row in payload.get("market_results") or []
            ],
        ),
        "",
        "## Slice-Key Policies",
        "",
        "Each row selects variants independently by market and one inference-time",
        "slice key using earlier market-days, then evaluates the resulting policy",
        "on later market-days.",
        "",
        _table(
            [
                "Slice key",
                "Status",
                "Non-current selections",
                "Selected candidate",
                "Selected current",
                "Selected market",
                "Selected delta market",
                "Eval oracle",
                "Oracle delta market",
                "Reasons",
            ],
            [
                [
                    row["slice_key"],
                    row["status"],
                    row.get("non_current_selection_count", 0),
                    _score_cell(row.get("selected_eval") or {}, "candidate_brier"),
                    _score_cell(row.get("selected_eval") or {}, "current_brier"),
                    _score_cell(row.get("selected_eval") or {}, "market_brier"),
                    fmt_signed((row.get("selected_eval") or {}).get("delta_vs_market"), 4),
                    _score_cell(row.get("eval_oracle") or {}, "candidate_brier"),
                    fmt_signed((row.get("eval_oracle") or {}).get("delta_vs_market"), 4),
                    "; ".join(row.get("reasons") or []) or "-",
                ]
                for row in payload.get("slice_policy_results") or []
            ],
        ),
        "",
        "## Leave-One-Market-Day Stability",
        "",
        "Each row selects a market's branch on all other dates, then evaluates",
        "the held-out market-day. This checks whether a branch survives more",
        "than the single first-half/second-half split above.",
        "",
        _table(
            [
                "Market",
                "Status",
                "Dates",
                "Selected counts",
                "Oracle counts",
                "Selected candidate",
                "Selected current",
                "Selected market",
                "Selected delta market",
                "Eval oracle",
                "Oracle delta market",
                "Reasons",
            ],
            [
                [
                    row["market_id"],
                    row["status"],
                    row.get("date_count", 0),
                    json.dumps(row.get("selected_variant_counts") or {}, sort_keys=True),
                    json.dumps(row.get("eval_oracle_variant_counts") or {}, sort_keys=True),
                    _score_cell(row.get("selected_eval") or {}, "candidate_brier"),
                    _score_cell(row.get("selected_eval") or {}, "current_brier"),
                    _score_cell(row.get("selected_eval") or {}, "market_brier"),
                    fmt_signed((row.get("selected_eval") or {}).get("delta_vs_market"), 4),
                    _score_cell(row.get("eval_oracle") or {}, "candidate_brier"),
                    fmt_signed((row.get("eval_oracle") or {}).get("delta_vs_market"), 4),
                    "; ".join(row.get("reasons") or []) or "-",
                ]
                for row in payload.get("leave_one_date_results") or []
            ],
        ),
        "",
        "## Guarded Branch Policies",
        "",
        "Each row evaluates one variant guarded back to current serving by a",
        "small set of inference-time source/cutoff/forecast-side policies.",
        "The fixed policy column is diagnostic; train-selected guard scores",
        "select the policy on all other market-days and evaluate the held-out",
        "day.",
        "",
        _table(
            [
                "Market",
                "Variant",
                "Status",
                "Best fixed policy",
                "Fixed candidate",
                "Fixed delta market",
                "Selected policy counts",
                "Selected candidate",
                "Selected current",
                "Selected market",
                "Selected delta market",
                "Reasons",
            ],
            [
                [
                    row["market_id"],
                    row["variant_id"],
                    row["status"],
                    row.get("best_fixed_policy"),
                    _score_cell(row.get("best_fixed_score") or {}, "candidate_brier"),
                    fmt_signed((row.get("best_fixed_score") or {}).get("delta_vs_market"), 4),
                    json.dumps(row.get("selected_policy_counts") or {}, sort_keys=True),
                    _score_cell(row.get("train_selected_score") or {}, "candidate_brier"),
                    _score_cell(row.get("train_selected_score") or {}, "current_brier"),
                    _score_cell(row.get("train_selected_score") or {}, "market_brier"),
                    fmt_signed((row.get("train_selected_score") or {}).get("delta_vs_market"), 4),
                    "; ".join(row.get("reasons") or []) or "-",
                ]
                for row in payload.get("guard_policy_results") or []
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], out: str | Path | None, report: str | Path | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if report:
        path = Path(report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_report(payload), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate chronological per-market selection among variant CSVs.")
    parser.add_argument("rows", nargs="+", help="Item-69-style variant row CSVs.")
    parser.add_argument("--markets", default=None, help="Comma-separated market ids to include.")
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-current-control", action="store_true")
    parser.add_argument(
        "--slice-keys",
        default=",".join(DEFAULT_SLICE_KEYS),
        help="Comma-separated slice keys for slice-level branch selection.",
    )
    parser.add_argument("--min-slice-train-rows", type=int, default=20)
    args = parser.parse_args()

    payload = build_payload(
        args.rows,
        markets=parse_markets(args.markets),
        market_tol=args.market_tol,
        include_current_control=not args.no_current_control,
        slice_keys=tuple(item.strip() for item in args.slice_keys.split(",") if item.strip()),
        min_slice_train_rows=args.min_slice_train_rows,
    )
    write_outputs(payload, args.out, args.report)
    print(f"Variant basket selection validation: {payload['acceptance']}")


if __name__ == "__main__":
    main()
