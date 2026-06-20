"""Chronological validation for contextual exact-winner repair factors.

This is development evidence only. It tests whether inference-available row
contexts can explain exact-winner underpricing without selecting factors on the
same market-days being evaluated.
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
from weather.reporting.winner_boost_validation import (
    brier,
    clamp_probability,
    parse_csv_list,
    read_rows,
    split_market_dates,
)


SCHEMA_VERSION = "contextual_winner_time_split_validation_v0.2"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "contextual_winner_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "contextual_winner_validation_report.md"
DEFAULT_MARKET_TOL = 0.003
INFERENCE_CONTEXT_FIELDS = (
    "band_key",
    "cutoff_regime",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
)
DEFAULT_TEMPLATES = (
    "market",
    "cutoff_regime",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
    "band_key",
    "band_key+forecast_bucket_pressure",
    "band_key+forecast_disagreement_bucket",
    "band_key+forecast_bucket_pressure+forecast_disagreement_bucket",
    "cutoff_regime+forecast_disagreement_bucket",
    "cutoff_regime+forecast_bucket_pressure",
    "forecast_bucket_pressure+forecast_disagreement_bucket",
    "cutoff_regime+forecast_bucket_pressure+forecast_disagreement_bucket",
)


def parse_template(value: str) -> tuple[str, ...]:
    value = str(value or "market").strip().lower()
    if value in {"", "market"}:
        return ()
    fields = tuple(part.strip() for part in value.split("+") if part.strip())
    unknown = [field for field in fields if field not in INFERENCE_CONTEXT_FIELDS]
    if unknown:
        raise ValueError(f"Unknown contextual-winner field(s): {', '.join(unknown)}")
    return fields


def template_label(template: tuple[str, ...]) -> str:
    return "+".join(template) if template else "market"


def parse_templates(value: str | None) -> list[tuple[str, ...]]:
    labels = parse_csv_list(value, DEFAULT_TEMPLATES)
    templates: list[tuple[str, ...]] = []
    for label in labels:
        template = parse_template(label)
        if template not in templates:
            templates.append(template)
    return templates or [()]


def rows_for_dates(rows: list[dict[str, Any]], market_id: str, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [
        row for row in rows
        if row["market_id"] == market_id and row["target_date"] in date_set
    ]


def context_key(row: dict[str, Any], template: tuple[str, ...]) -> tuple[str, ...]:
    return tuple([str(row.get("market_id") or "unknown")] + [str(row.get(field) or "na") for field in template])


def fit_context_factors(
    rows: list[dict[str, Any]],
    template: tuple[str, ...],
    min_rows: int = 20,
    prior_rows: float = 80.0,
    factor_min: float = 0.50,
    factor_max: float = 8.0,
    min_factor_delta: float = 0.05,
) -> dict[tuple[str, ...], dict[str, Any]]:
    stats: dict[tuple[str, ...], dict[str, float]] = defaultdict(lambda: {"n": 0.0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row in rows:
        if row.get("bin_type") != "eq":
            continue
        key = context_key(row, template)
        stats[key]["n"] += 1.0
        stats[key]["outcome_sum"] += float(row["outcome"])
        stats[key]["prob_sum"] += float(row["probability"])

    factors: dict[tuple[str, ...], dict[str, Any]] = {}
    for key, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        probability_sum = float(stat["prob_sum"])
        if probability_sum <= 0:
            continue
        mean_probability = probability_sum / n
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if mean_probability <= 0:
            continue
        factor = smoothed_observed / mean_probability
        factor = max(float(factor_min), min(float(factor_max), factor))
        if abs(factor - 1.0) < float(min_factor_delta):
            continue
        factors[key] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }
    return factors


def contextual_probabilities(
    rows: list[dict[str, Any]],
    template: tuple[str, ...],
    factors: dict[tuple[str, ...], dict[str, Any]],
) -> list[float]:
    output = [row["probability"] for row in rows]
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["market_id"], row["snapshot_id"])].append(index)
    for indexes in grouped.values():
        weights = []
        for index in indexes:
            row = rows[index]
            factor = 1.0
            if row.get("bin_type") == "eq":
                entry = factors.get(context_key(row, template))
                if entry is not None:
                    factor = float(entry.get("factor", 1.0))
            weights.append(float(row["probability"]) * factor)
        total = sum(weights)
        if total <= 0:
            continue
        for index, weight in zip(indexes, weights):
            output[index] = clamp_probability(weight / total)
    return output


def score_probabilities(rows: list[dict[str, Any]], probabilities: list[float] | None = None) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    probabilities = probabilities or [row["probability"] for row in rows]
    candidate_brier = sum(brier(probability, int(row["outcome"])) for row, probability in zip(rows, probabilities)) / len(rows)
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


def select_template(
    rows: list[dict[str, Any]],
    templates: list[tuple[str, ...]],
    min_rows: int,
    prior_rows: float,
    factor_min: float,
    factor_max: float,
) -> dict[str, Any]:
    candidates = []
    for template in templates:
        factors = fit_context_factors(
            rows,
            template,
            min_rows=min_rows,
            prior_rows=prior_rows,
            factor_min=factor_min,
            factor_max=factor_max,
        )
        probabilities = contextual_probabilities(rows, template, factors)
        score = score_probabilities(rows, probabilities)
        candidates.append({
            "template": template_label(template),
            "template_fields": list(template),
            "factor_count": len(factors),
            "candidate_brier": score["candidate_brier"],
            "delta_vs_current": score["delta_vs_current"],
            "delta_vs_market": score["delta_vs_market"],
            "factors": factors,
        })
    candidates.sort(key=lambda item: (
        math.inf if item["candidate_brier"] is None else item["candidate_brier"],
        item["factor_count"],
        item["template"],
    ))
    return candidates[0] if candidates else {
        "template": "market",
        "template_fields": [],
        "factor_count": 0,
        "candidate_brier": None,
        "delta_vs_current": None,
        "delta_vs_market": None,
        "factors": {},
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


def serialize_factors(factors: dict[tuple[str, ...], dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    rows = []
    for key, entry in factors.items():
        rows.append({
            "context": "|".join(key),
            "factor": float(entry.get("factor", 1.0)),
            "n": int(entry.get("n", 0)),
            "observed_rate": entry.get("observed_rate"),
            "mean_probability": entry.get("mean_probability"),
        })
    rows.sort(key=lambda row: (abs(row["factor"] - 1.0), row["n"]), reverse=True)
    return rows[:limit]


def score_daily_first(rows: list[dict[str, Any]], selections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"])].append(row)
    if not grouped:
        return {"market_days": 0}
    scores = []
    for (market_id, _target_date), group_rows in grouped.items():
        selection = selections.get(market_id) or {}
        template = tuple(selection.get("template_fields") or [])
        factors = selection.get("factors") or {}
        probabilities = contextual_probabilities(group_rows, template, factors)
        scores.append(score_probabilities(group_rows, probabilities))
    keys = ("candidate_brier", "current_brier", "market_brier", "delta_vs_current", "delta_vs_market")
    return {
        "market_days": len(scores),
        **{
            key: sum(score[key] for score in scores if score.get(key) is not None) / len(scores)
            for key in keys
        },
    }


def build_payload(
    rows_paths: list[str | Path],
    templates_csv: str | None = None,
    min_rows: int = 20,
    prior_rows: float = 80.0,
    factor_min: float = 0.50,
    factor_max: float = 8.0,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    rows = read_rows(rows_paths)
    templates = parse_templates(templates_csv)
    split = split_market_dates(rows)
    train_rows_all = []
    eval_rows_all = []
    selections: dict[str, dict[str, Any]] = {}
    oracle_selections: dict[str, dict[str, Any]] = {}
    market_results = []

    for market_id, market_split in sorted(split.items()):
        train_rows = rows_for_dates(rows, market_id, market_split["train_dates"])
        eval_rows = rows_for_dates(rows, market_id, market_split["eval_dates"])
        train_rows_all.extend(train_rows)
        eval_rows_all.extend(eval_rows)
        selection = select_template(
            train_rows,
            templates,
            min_rows=min_rows,
            prior_rows=prior_rows,
            factor_min=factor_min,
            factor_max=factor_max,
        )
        eval_oracle = select_template(
            eval_rows,
            templates,
            min_rows=min_rows,
            prior_rows=prior_rows,
            factor_min=factor_min,
            factor_max=factor_max,
        )
        selections[market_id] = selection
        oracle_selections[market_id] = eval_oracle
        template = tuple(selection.get("template_fields") or [])
        factors = selection.get("factors") or {}
        eval_probabilities = contextual_probabilities(eval_rows, template, factors)
        selected_eval = score_probabilities(eval_rows, eval_probabilities)
        baseline_eval = score_probabilities(eval_rows)
        oracle_template = tuple(eval_oracle.get("template_fields") or [])
        oracle_factors = eval_oracle.get("factors") or {}
        oracle_probabilities = contextual_probabilities(eval_rows, oracle_template, oracle_factors)
        oracle_eval = score_probabilities(eval_rows, oracle_probabilities)
        serialized_factors = serialize_factors(factors)
        market_results.append({
            "market_id": market_id,
            "train_dates": market_split["train_dates"],
            "eval_dates": market_split["eval_dates"],
            "selected_template": selection["template"],
            "selected_factor_count": selection["factor_count"],
            "selection_score": {
                "candidate_brier": selection["candidate_brier"],
                "delta_vs_current": selection["delta_vs_current"],
                "delta_vs_market": selection["delta_vs_market"],
            },
            "top_factors": serialized_factors,
            "baseline_eval": baseline_eval,
            "eval": selected_eval,
            "eval_oracle": {
                "classification": "diagnostic_only_later_date_selected",
                "selected_template": eval_oracle["template"],
                "selected_factor_count": eval_oracle["factor_count"],
                "score": oracle_eval,
                "top_factors": serialize_factors(oracle_factors),
            },
            "holdout_status": _pass_status(selected_eval, market_tol),
        })

    serializable_selections = {
        market_id: {
            "template": selection["template"],
            "template_fields": selection["template_fields"],
            "factor_count": selection["factor_count"],
            "top_factors": serialize_factors(selection.get("factors") or {}),
        }
        for market_id, selection in selections.items()
    }
    readiness_status = "PASS" if market_results and all(row["holdout_status"] == "PASS" for row in market_results) else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "evidence_classification": "development_time_split_not_promotion_evidence",
        "templates": [template_label(template) for template in templates],
        "fit_config": {
            "min_rows": int(min_rows),
            "prior_rows": float(prior_rows),
            "factor_min": float(factor_min),
            "factor_max": float(factor_max),
            "market_tol": float(market_tol),
            "inference_context_fields": list(INFERENCE_CONTEXT_FIELDS),
        },
        "no_leakage_audit": {
            "status": "PASS" if eval_rows_all else "WARN",
            "primary_evidence_unit": "market_day",
            "detail": (
                "Context templates are selected on earlier target dates and evaluated on later "
                "target dates. Factor keys use only market id, candidate band key, cutoff, "
                "forecast pressure, forecast disagreement, forecast source-count, and "
                "source-freshness columns."
            ),
        },
        "row_counts": {
            "total": len(rows),
            "train": len(train_rows_all),
            "eval": len(eval_rows_all),
        },
        "selected_template_by_market": {
            market_id: selection["template"]
            for market_id, selection in selections.items()
        },
        "selected_contexts_by_market": serializable_selections,
        "baseline": {
            "eval_daily_first": score_daily_first(eval_rows_all, {
                market_id: {"template_fields": [], "factors": {}}
                for market_id in selections
            }),
        },
        "selected": {
            "eval_daily_first": score_daily_first(eval_rows_all, selections),
        },
        "eval_oracle": {
            "classification": "diagnostic_only_later_date_selected",
            "eval_daily_first": score_daily_first(eval_rows_all, oracle_selections),
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
    oracle_daily = (payload.get("eval_oracle") or {}).get("eval_daily_first") or {}
    lines = [
        "# Contextual Winner Time-Split Validation",
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
            ["Templates", ", ".join(payload.get("templates") or [])],
            ["Min rows", (payload.get("fit_config") or {}).get("min_rows")],
            ["Prior rows", fmt_num((payload.get("fit_config") or {}).get("prior_rows"))],
            ["Factor bounds", f"{fmt_num((payload.get('fit_config') or {}).get('factor_min'))} to {fmt_num((payload.get('fit_config') or {}).get('factor_max'))}"],
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
            [
                "eval oracle (diagnostic)",
                fmt_num(oracle_daily.get("candidate_brier")),
                fmt_num(oracle_daily.get("current_brier")),
                fmt_num(oracle_daily.get("market_brier")),
                fmt_signed(oracle_daily.get("delta_vs_current")),
                fmt_signed(oracle_daily.get("delta_vs_market")),
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
            "Template",
            "Factors",
            "Train Dates",
            "Eval Dates",
            "Baseline",
            "Candidate",
            "Current",
            "Market",
            "Delta Market",
            "Oracle Template",
            "Oracle Gap",
            "Status",
        ],
        [
            [
                row.get("market_id"),
                row.get("selected_template"),
                row.get("selected_factor_count"),
                ", ".join(row.get("train_dates") or []),
                ", ".join(row.get("eval_dates") or []),
                fmt_num((row.get("baseline_eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("candidate_brier")),
                fmt_num((row.get("eval") or {}).get("current_brier")),
                fmt_num((row.get("eval") or {}).get("market_brier")),
                fmt_signed((row.get("eval") or {}).get("delta_vs_market")),
                (row.get("eval_oracle") or {}).get("selected_template"),
                fmt_signed(((row.get("eval_oracle") or {}).get("score") or {}).get("delta_vs_market")),
                row.get("holdout_status"),
            ]
            for row in payload.get("market_results") or []
        ],
    )
    lines += [
        "",
        "## Top Selected Factors",
        "",
    ]
    for row in payload.get("market_results") or []:
        lines += [
            f"### {row.get('market_id')}",
            "",
        ]
        factors = row.get("top_factors") or []
        if factors:
            lines += markdown_table(
                ["Context", "Factor", "Rows", "Observed", "Mean P"],
                [
                    [
                        item.get("context"),
                        fmt_num(item.get("factor")),
                        item.get("n"),
                        fmt_num(item.get("observed_rate")),
                        fmt_num(item.get("mean_probability")),
                    ]
                    for item in factors
                ],
            )
        else:
            lines.append("No non-neutral selected factors.")
        lines.append("")
    lines += [
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
    parser = argparse.ArgumentParser(description="Validate contextual exact-winner repair factors on chronological splits.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports to evaluate.")
    parser.add_argument("--templates", default=None)
    parser.add_argument("--min-rows", type=int, default=20)
    parser.add_argument("--prior-rows", type=float, default=80.0)
    parser.add_argument("--factor-min", type=float, default=0.50)
    parser.add_argument("--factor-max", type=float, default=8.0)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = build_payload(
        rows_paths=args.rows,
        templates_csv=args.templates,
        min_rows=args.min_rows,
        prior_rows=args.prior_rows,
        factor_min=args.factor_min,
        factor_max=args.factor_max,
        market_tol=args.market_tol,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"Contextual winner validation: {payload['readiness_status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
