"""Chronological validation for no-market context guard policies.

This report is development evidence only. It asks whether an already-generated
candidate row export can be guarded back to current serving by inference-time
context fields, selecting policies on earlier market-days and evaluating them
on later market-days.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("context_guard_validation")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_ROWS = DEFAULT_BACKTEST_ROOT / "item32_reanalysis_austin_guard_chicago_nyc_raw_variant_rows.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "context_guard_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "context_guard_validation_report.md"
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MIN_GUARD_ROWS = 200
DEFAULT_TOP_POLICIES = 5
DEFAULT_GUARD_KEYS = (
    "source_freshness_state",
    "cutoff_regime",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "forecast_source_count_bucket",
    "bin_type",
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
    return max(1e-15, min(1.0 - 1e-15, float(value)))


def brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def parse_csv_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return tuple(default)
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def normalize_row(row: dict[str, Any], guard_keys: tuple[str, ...]) -> dict[str, Any] | None:
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
    output = {
        "market_id": market_id,
        "target_date": target_date,
        "snapshot_id": snapshot_id,
        "band_key": band_key,
        "probability": _clamp_probability(probability),
        "current_probability": _clamp_probability(current_probability),
        "market_probability": _clamp_probability(market_probability),
        "outcome": int(outcome),
    }
    for key in guard_keys:
        output[key] = str(row.get(key) or "")
    return output


def read_variant_rows(path: str | Path, guard_keys: tuple[str, ...] = DEFAULT_GUARD_KEYS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            row = normalize_row(source, guard_keys)
            if row is not None:
                rows.append(row)
    return rows


def score_rows(rows: list[dict[str, Any]], probabilities: list[float] | None = None) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    if probabilities is None:
        probabilities = [row["probability"] for row in rows]
    candidate = sum(brier(probability, row["outcome"]) for row, probability in zip(rows, probabilities)) / len(rows)
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


def score_daily_first(rows: list[dict[str, Any]], probabilities: list[float] | None = None) -> dict[str, Any]:
    if not rows:
        return {"market_days": 0, **score_rows([])}
    if probabilities is None:
        probabilities = [row["probability"] for row in rows]
    grouped: dict[tuple[str, str], list[tuple[dict[str, Any], float]]] = defaultdict(list)
    for row, probability in zip(rows, probabilities):
        grouped[(row["market_id"], row["target_date"])].append((row, probability))
    scores = []
    for items in grouped.values():
        group_rows = [row for row, _probability in items]
        group_probabilities = [probability for _row, probability in items]
        scores.append(score_rows(group_rows, group_probabilities))
    keys = ("candidate_brier", "current_brier", "market_brier", "delta_vs_current", "delta_vs_market")
    return {
        "market_days": len(scores),
        "rows": sum(score["rows"] for score in scores),
        **{key: sum(score[key] for score in scores) / len(scores) for key in keys},
    }


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


def rows_for_dates(rows: list[dict[str, Any]], market_id: str, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [
        row for row in rows
        if row["market_id"] == market_id and row["target_date"] in date_set
    ]


def candidate_diff_rows(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if abs(row["probability"] - row["current_probability"]) > 1e-12)


def condition_matches(row: dict[str, Any], conditions: tuple[tuple[str, str], ...]) -> bool:
    return all(str(row.get(key) or "") == str(value) for key, value in conditions)


def policy_id(mode: str, conditions: tuple[tuple[str, str], ...] = ()) -> str:
    if mode in {"observed_baseline", "all_current", "all_candidate"}:
        return mode
    suffix = "&".join(f"{key}={value}" for key, value in conditions)
    return f"{mode}_{suffix}"


def generate_condition_sets(
    rows: list[dict[str, Any]],
    guard_keys: tuple[str, ...],
    max_combo_size: int,
) -> list[tuple[tuple[str, str], ...]]:
    atoms: list[tuple[str, str]] = []
    for key in guard_keys:
        values = sorted({str(row.get(key) or "") for row in rows if str(row.get(key) or "")})
        atoms.extend((key, value) for value in values)
    condition_sets: list[tuple[tuple[str, str], ...]] = []
    max_combo_size = max(1, int(max_combo_size))
    for size in range(1, max_combo_size + 1):
        for combo in itertools.combinations(atoms, size):
            keys = [key for key, _value in combo]
            if len(set(keys)) != len(keys):
                continue
            condition_sets.append(tuple(combo))
    return condition_sets


def generate_policies(
    rows: list[dict[str, Any]],
    guard_keys: tuple[str, ...],
    max_combo_size: int,
    min_guard_rows: int,
) -> list[dict[str, Any]]:
    policies = [
        {"policy_id": "observed_baseline", "mode": "observed_baseline", "conditions": [], "guard_rows": len(rows)},
        {"policy_id": "all_current", "mode": "all_current", "conditions": [], "guard_rows": len(rows)},
        {"policy_id": "all_candidate", "mode": "all_candidate", "conditions": [], "guard_rows": len(rows)},
    ]
    for conditions in generate_condition_sets(rows, guard_keys, max_combo_size):
        guard_rows = sum(1 for row in rows if condition_matches(row, conditions))
        if guard_rows < int(min_guard_rows):
            continue
        for mode in ("candidate_on", "current_on"):
            policies.append({
                "policy_id": policy_id(mode, conditions),
                "mode": mode,
                "conditions": [{"key": key, "value": value} for key, value in conditions],
                "guard_rows": guard_rows,
            })
    return policies


def policy_probabilities(rows: list[dict[str, Any]], policy: dict[str, Any]) -> list[float]:
    mode = policy.get("mode")
    if mode == "observed_baseline" or mode == "all_candidate":
        return [row["probability"] for row in rows]
    if mode == "all_current":
        return [row["current_probability"] for row in rows]
    conditions = tuple((item["key"], item["value"]) for item in policy.get("conditions") or [])
    output = []
    for row in rows:
        matched = condition_matches(row, conditions)
        if mode == "candidate_on":
            output.append(row["probability"] if matched else row["current_probability"])
        elif mode == "current_on":
            output.append(row["current_probability"] if matched else row["probability"])
        else:
            output.append(row["probability"])
    return output


def status_for_score(score: dict[str, Any], market_tol: float = DEFAULT_MARKET_TOL) -> tuple[str, list[str]]:
    reasons = []
    delta_market = score.get("delta_vs_market")
    delta_current = score.get("delta_vs_current")
    if delta_market is not None and delta_market > float(market_tol):
        reasons.append(f"delta_vs_market {fmt_signed(delta_market)} > {fmt_signed(market_tol)}")
    if delta_current is not None and delta_current > 0:
        reasons.append("regresses current")
    return ("BLOCK" if reasons else "PASS", reasons)


def _score_sort_key(item: dict[str, Any]) -> tuple[float, str]:
    score = item.get("train_daily_first") or item.get("eval_daily_first") or {}
    value = score.get("candidate_brier")
    return (math.inf if value is None else float(value), item.get("policy_id") or "")


def evaluate_market(
    rows: list[dict[str, Any]],
    market_id: str,
    split: dict[str, list[str]],
    guard_keys: tuple[str, ...],
    max_combo_size: int,
    min_guard_rows: int,
    market_tol: float,
    top_policies: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[float], list[dict[str, Any]], list[float]]:
    market_rows = [row for row in rows if row["market_id"] == market_id]
    train_rows = rows_for_dates(rows, market_id, split.get("train_dates") or [])
    eval_rows = rows_for_dates(rows, market_id, split.get("eval_dates") or [])
    policies = generate_policies(train_rows, guard_keys, max_combo_size, min_guard_rows)
    candidates = []
    for policy in policies:
        train_probabilities = policy_probabilities(train_rows, policy)
        eval_probabilities = policy_probabilities(eval_rows, policy)
        candidates.append({
            "policy_id": policy["policy_id"],
            "mode": policy["mode"],
            "conditions": policy.get("conditions") or [],
            "guard_rows": policy.get("guard_rows", 0),
            "train_daily_first": score_daily_first(train_rows, train_probabilities),
            "eval_daily_first": score_daily_first(eval_rows, eval_probabilities),
        })
    candidates.sort(key=_score_sort_key)
    selected = candidates[0] if candidates else {
        "policy_id": "observed_baseline",
        "mode": "observed_baseline",
        "conditions": [],
        "guard_rows": 0,
        "train_daily_first": score_daily_first([]),
        "eval_daily_first": score_daily_first([]),
    }
    selected_policy = {
        "policy_id": selected["policy_id"],
        "mode": selected["mode"],
        "conditions": selected.get("conditions") or [],
    }
    selected_eval_probabilities = policy_probabilities(eval_rows, selected_policy)
    baseline_eval_probabilities = [row["probability"] for row in eval_rows]
    selected_eval_score = score_daily_first(eval_rows, selected_eval_probabilities)
    baseline_eval_score = score_daily_first(eval_rows, baseline_eval_probabilities)
    selected_status, selected_reasons = status_for_score(selected_eval_score, market_tol)
    baseline_status, baseline_reasons = status_for_score(baseline_eval_score, market_tol)
    eval_ranked = sorted(
        candidates,
        key=lambda item: (
            math.inf
            if item["eval_daily_first"].get("candidate_brier") is None
            else item["eval_daily_first"]["candidate_brier"],
            item["policy_id"],
        ),
    )
    eval_oracle = eval_ranked[0] if eval_ranked else selected
    return (
        {
            "market_id": market_id,
            "train_dates": split.get("train_dates") or [],
            "eval_dates": split.get("eval_dates") or [],
            "rows": len(market_rows),
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "candidate_diff_train_rows": candidate_diff_rows(train_rows),
            "candidate_diff_eval_rows": candidate_diff_rows(eval_rows),
            "policy_count": len(candidates),
            "selected_policy": selected_policy,
            "selected_train": selected["train_daily_first"],
            "selected_eval": selected_eval_score,
            "selected_status": selected_status,
            "selected_reasons": selected_reasons,
            "baseline_eval": baseline_eval_score,
            "baseline_status": baseline_status,
            "baseline_reasons": baseline_reasons,
            "eval_oracle_policy": {
                "policy_id": eval_oracle["policy_id"],
                "mode": eval_oracle["mode"],
                "conditions": eval_oracle.get("conditions") or [],
            },
            "eval_oracle": eval_oracle["eval_daily_first"],
            "top_eval_policies": [
                {
                    "policy_id": item["policy_id"],
                    "mode": item["mode"],
                    "conditions": item.get("conditions") or [],
                    "guard_rows": item.get("guard_rows", 0),
                    "eval_daily_first": item["eval_daily_first"],
                }
                for item in eval_ranked[: int(top_policies)]
            ],
        },
        eval_rows,
        selected_eval_probabilities,
        eval_rows,
        baseline_eval_probabilities,
    )


def build_context_guard_validation(
    rows_path: str | Path = DEFAULT_ROWS,
    *,
    guard_keys: tuple[str, ...] = DEFAULT_GUARD_KEYS,
    max_combo_size: int = 2,
    min_guard_rows: int = DEFAULT_MIN_GUARD_ROWS,
    market_tol: float = DEFAULT_MARKET_TOL,
    top_policies: int = DEFAULT_TOP_POLICIES,
) -> dict[str, Any]:
    rows = read_variant_rows(rows_path, guard_keys=guard_keys)
    split = split_market_dates(rows)
    market_results = []
    selected_rows_all: list[dict[str, Any]] = []
    selected_probabilities_all: list[float] = []
    baseline_rows_all: list[dict[str, Any]] = []
    baseline_probabilities_all: list[float] = []
    for market_id in sorted(split):
        result, selected_rows, selected_probabilities, baseline_rows, baseline_probabilities = evaluate_market(
            rows,
            market_id,
            split[market_id],
            guard_keys,
            max_combo_size,
            min_guard_rows,
            market_tol,
            top_policies,
        )
        market_results.append(result)
        selected_rows_all.extend(selected_rows)
        selected_probabilities_all.extend(selected_probabilities)
        baseline_rows_all.extend(baseline_rows)
        baseline_probabilities_all.extend(baseline_probabilities)

    selected_eval = score_rows(selected_rows_all, selected_probabilities_all)
    baseline_eval = score_rows(baseline_rows_all, baseline_probabilities_all)
    selected_daily_first = score_daily_first(selected_rows_all, selected_probabilities_all)
    baseline_daily_first = score_daily_first(baseline_rows_all, baseline_probabilities_all)
    blocked_markets = [
        row["market_id"]
        for row in market_results
        if row.get("selected_status") == "BLOCK"
    ]
    status = "PASS" if not blocked_markets and not status_for_score(selected_daily_first, market_tol)[1] else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_classification": "development diagnostic, not promotion evidence",
        "rows_path": str(rows_path),
        "guard_keys": list(guard_keys),
        "max_combo_size": int(max_combo_size),
        "min_guard_rows": int(min_guard_rows),
        "market_tol": float(market_tol),
        "row_counts": {
            "source_rows": len(rows),
            "markets": len(split),
            "selected_eval_rows": len(selected_rows_all),
            "candidate_diff_rows": candidate_diff_rows(rows),
        },
        "status": status,
        "summary": {
            "blocked_markets": blocked_markets,
            "pass_markets": [
                row["market_id"]
                for row in market_results
                if row.get("selected_status") == "PASS"
            ],
            "selected_daily_first": selected_daily_first,
            "baseline_daily_first": baseline_daily_first,
        },
        "selected_eval": selected_eval,
        "baseline_eval": baseline_eval,
        "selected_daily_first": selected_daily_first,
        "baseline_daily_first": baseline_daily_first,
        "market_results": market_results,
    }


def _score_cells(score: dict[str, Any]) -> list[str]:
    return [
        fmt_num(score.get("candidate_brier")),
        fmt_num(score.get("current_brier")),
        fmt_num(score.get("market_brier")),
        fmt_signed(score.get("delta_vs_current"), 4),
        fmt_signed(score.get("delta_vs_market"), 4),
    ]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Current-Blend Context Guard Validation",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: `{payload.get('status')}`",
        "",
        f"Evidence classification: {payload.get('evidence_classification')}.",
        "",
        "Policies are selected on each market's earlier target dates and evaluated on later target dates. "
        "Guard keys are inference-time fields only: "
        + ", ".join(payload.get("guard_keys") or []),
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Scope", "Candidate", "Current", "Market", "Delta Current", "Delta Market"],
        [
            ["selected eval rows", *_score_cells(payload.get("selected_eval") or {})],
            ["baseline eval rows", *_score_cells(payload.get("baseline_eval") or {})],
            ["selected daily-first", *_score_cells(payload.get("selected_daily_first") or {})],
            ["baseline daily-first", *_score_cells(payload.get("baseline_daily_first") or {})],
        ],
    ))
    lines.extend(["", "## Market Selection", ""])
    rows = []
    for result in payload.get("market_results") or []:
        rows.append([
            result.get("market_id"),
            result.get("candidate_diff_train_rows"),
            result.get("candidate_diff_eval_rows"),
            (result.get("selected_policy") or {}).get("policy_id"),
            fmt_num((result.get("selected_eval") or {}).get("candidate_brier")),
            fmt_signed((result.get("selected_eval") or {}).get("delta_vs_market"), 4),
            result.get("selected_status"),
            fmt_num((result.get("baseline_eval") or {}).get("candidate_brier")),
            fmt_signed((result.get("baseline_eval") or {}).get("delta_vs_market"), 4),
            (result.get("eval_oracle_policy") or {}).get("policy_id"),
            fmt_signed((result.get("eval_oracle") or {}).get("delta_vs_market"), 4),
        ])
    lines.extend(markdown_table(
        [
            "Market",
            "Candidate Train Rows",
            "Candidate Eval Rows",
            "Selected Policy",
            "Selected Candidate",
            "Selected Market Gap",
            "Selected Status",
            "Baseline Candidate",
            "Baseline Market Gap",
            "Eval Oracle Policy",
            "Eval Oracle Gap",
        ],
        rows,
    ))
    lines.append("")
    for result in payload.get("market_results") or []:
        lines.extend([f"## {result.get('market_id')}", ""])
        policy_rows = []
        for rank, item in enumerate(result.get("top_eval_policies") or [], start=1):
            score = item.get("eval_daily_first") or {}
            policy_rows.append([
                rank,
                item.get("policy_id"),
                item.get("guard_rows"),
                fmt_num(score.get("candidate_brier")),
                fmt_num(score.get("current_brier")),
                fmt_num(score.get("market_brier")),
                fmt_signed(score.get("delta_vs_current"), 4),
                fmt_signed(score.get("delta_vs_market"), 4),
            ])
        lines.extend(markdown_table(
            [
                "Rank",
                "Policy",
                "Guard Rows",
                "Eval Candidate",
                "Eval Current",
                "Eval Market",
                "Delta Current",
                "Delta Market",
            ],
            policy_rows,
        ))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: dict[str, Any], out: str | Path | None = None, report: str | Path | None = None) -> None:
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if report:
        report_path = Path(report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(payload), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate no-market context guard policies over variant rows.")
    parser.add_argument("--variant-rows", default=str(DEFAULT_ROWS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--guard-keys", default=",".join(DEFAULT_GUARD_KEYS))
    parser.add_argument("--max-combo-size", type=int, default=2)
    parser.add_argument("--min-guard-rows", type=int, default=DEFAULT_MIN_GUARD_ROWS)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--top-policies", type=int, default=DEFAULT_TOP_POLICIES)
    args = parser.parse_args(argv)
    payload = build_context_guard_validation(
        args.variant_rows,
        guard_keys=parse_csv_list(args.guard_keys, DEFAULT_GUARD_KEYS),
        max_combo_size=args.max_combo_size,
        min_guard_rows=args.min_guard_rows,
        market_tol=args.market_tol,
        top_policies=args.top_policies,
    )
    write_outputs(payload, args.out, args.report)
    print(
        f"Context guard validation: {payload['status']} "
        f"({len(payload.get('summary', {}).get('blocked_markets') or [])} blocked markets)"
    )
    if args.out:
        print(f"JSON written to {args.out}")
    if args.report:
        print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
