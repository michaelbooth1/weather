"""Nested time-split validation for winner-band row signals.

This is development evidence only. It tests whether inference-time row shape
features can select a target-day winner band without choosing the repair on the
same market-days used for evaluation.
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
from weather.reporting.winner_boost_validation import (
    brier,
    clamp_probability,
    safe_float,
    safe_int,
)


SCHEMA_VERSION = "winner_band_signal_validation_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "winner_band_signal_validation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "winner_band_signal_validation_report.md"
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MODEL_C = 1.0

NUMERIC_FEATURES = (
    "logit_probability",
    "logit_current_probability",
    "logit_recorded_probability",
    "log_probability",
    "log_current_probability",
    "log_recorded_probability",
    "candidate_rank",
    "current_rank",
    "recorded_rank",
    "candidate_top_gap",
    "current_top_gap",
    "recorded_top_gap",
    "candidate_share_over_mean",
    "current_share_over_mean",
    "probability_gap_current",
    "probability_gap_recorded",
    "band_value",
    "cutoff_hour_num",
)
CAT_FEATURES = (
    "market_id",
    "bin_type",
    "cutoff_regime",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
    "candidate_rank_bucket",
    "current_rank_bucket",
)
TRANSFORMS = (
    "baseline",
    "current",
    "row_norm",
    "row_mult",
    "row_sqrt",
    "row_raw25",
)


def _logit(value: float) -> float:
    probability = max(1e-6, min(1.0 - 1e-6, float(value)))
    return math.log(probability / (1.0 - probability))


def _rank_bucket(rank: int) -> str:
    if rank <= 1:
        return "top1"
    if rank == 2:
        return "top2"
    if rank == 3:
        return "top3"
    if rank <= 6:
        return "top4_6"
    return "other"


def _band_value(band_key: str) -> float:
    try:
        return float(str(band_key).split(":", 1)[1].split("-", 1)[0])
    except (IndexError, TypeError, ValueError):
        return 0.0


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
                recorded_probability = safe_float(source.get("recorded_probability"))
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
                    "recorded_probability": clamp_probability(
                        recorded_probability if recorded_probability is not None else probability
                    ),
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
    return enrich_rows(rows)


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    grouped: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(output):
        grouped[(row["market_id"], row["target_date"], row["snapshot_id"])].append(index)

    for indexes in grouped.values():
        candidate_ranked = sorted(indexes, key=lambda idx: output[idx]["probability"], reverse=True)
        current_ranked = sorted(indexes, key=lambda idx: output[idx]["current_probability"], reverse=True)
        recorded_ranked = sorted(indexes, key=lambda idx: output[idx]["recorded_probability"], reverse=True)
        for rank, index in enumerate(candidate_ranked, start=1):
            output[index]["candidate_rank"] = rank
        for rank, index in enumerate(current_ranked, start=1):
            output[index]["current_rank"] = rank
        for rank, index in enumerate(recorded_ranked, start=1):
            output[index]["recorded_rank"] = rank

        top_candidate = output[candidate_ranked[0]]["probability"]
        top_current = output[current_ranked[0]]["current_probability"]
        top_recorded = output[recorded_ranked[0]]["recorded_probability"]
        mean_candidate = sum(output[index]["probability"] for index in indexes) / len(indexes)
        mean_current = sum(output[index]["current_probability"] for index in indexes) / len(indexes)

        for index in indexes:
            row = output[index]
            row["candidate_top_gap"] = top_candidate - row["probability"]
            row["current_top_gap"] = top_current - row["current_probability"]
            row["recorded_top_gap"] = top_recorded - row["recorded_probability"]
            row["candidate_share_over_mean"] = row["probability"] / max(1e-9, mean_candidate)
            row["current_share_over_mean"] = row["current_probability"] / max(1e-9, mean_current)
            row["probability_gap_current"] = row["probability"] - row["current_probability"]
            row["probability_gap_recorded"] = row["probability"] - row["recorded_probability"]
            row["candidate_rank_bucket"] = _rank_bucket(int(row["candidate_rank"]))
            row["current_rank_bucket"] = _rank_bucket(int(row["current_rank"]))

    for row in output:
        row["logit_probability"] = _logit(row["probability"])
        row["logit_current_probability"] = _logit(row["current_probability"])
        row["logit_recorded_probability"] = _logit(row["recorded_probability"])
        row["log_probability"] = math.log(max(1e-9, row["probability"]))
        row["log_current_probability"] = math.log(max(1e-9, row["current_probability"]))
        row["log_recorded_probability"] = math.log(max(1e-9, row["recorded_probability"]))
        row["band_value"] = _band_value(row.get("band_key") or "")
        row["cutoff_hour_num"] = safe_float(row.get("cutoff_hour")) or 0.0
    return output


def nested_market_date_split(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    dates_by_market: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        dates_by_market[row["market_id"]].add(row["target_date"])

    split: dict[str, dict[str, list[str]]] = {}
    for market_id, date_set in sorted(dates_by_market.items()):
        dates = sorted(date_set)
        if len(dates) <= 1:
            fit_dates = dates
            selection_dates: list[str] = []
            eval_dates: list[str] = []
        elif len(dates) == 2:
            fit_dates = dates[:1]
            selection_dates = []
            eval_dates = dates[1:]
        else:
            eval_start = max(2, len(dates) // 2)
            pre_eval = dates[:eval_start]
            fit_dates = pre_eval[:-1]
            selection_dates = pre_eval[-1:]
            eval_dates = dates[eval_start:]
        split[market_id] = {
            "fit_dates": fit_dates,
            "selection_dates": selection_dates,
            "eval_dates": eval_dates,
        }
    return split


def rows_for_dates(rows: list[dict[str, Any]], market_id: str, dates: list[str]) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [
        row for row in rows
        if row["market_id"] == market_id and row["target_date"] in date_set
    ]


def score_probabilities(rows: list[dict[str, Any]], probabilities: list[float]) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
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


def score_daily_first(rows: list[dict[str, Any]], probabilities: list[float]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["market_id"], row["target_date"])].append(index)
    if not grouped:
        return {"market_days": 0}
    scores = [
        score_probabilities(
            [rows[index] for index in indexes],
            [probabilities[index] for index in indexes],
        )
        for indexes in grouped.values()
    ]
    keys = ("candidate_brier", "current_brier", "market_brier", "delta_vs_current", "delta_vs_market")
    return {
        "market_days": len(scores),
        **{
            key: sum(score[key] for score in scores if score.get(key) is not None) / len(scores)
            for key in keys
        },
    }


def normalize_snapshot_weights(rows: list[dict[str, Any]], weights: list[float]) -> list[float]:
    output = [0.0] * len(rows)
    grouped: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["market_id"], row["target_date"], row["snapshot_id"])].append(index)
    for indexes in grouped.values():
        values = [max(1e-12, float(weights[index])) for index in indexes]
        total = sum(values)
        if total <= 0:
            continue
        for index, value in zip(indexes, values):
            output[index] = clamp_probability(value / total)
    return output


def fit_predict_row_signal(
    fit_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    model_c: float = DEFAULT_MODEL_C,
) -> list[float]:
    if not target_rows:
        return []
    outcomes = {int(row["outcome"]) for row in fit_rows}
    if not fit_rows or outcomes != {0, 1}:
        return [row["probability"] for row in target_rows]

    try:
        import pandas as pd
        from sklearn.compose import ColumnTransformer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:  # pragma: no cover - dependency is expected in repo env.
        raise RuntimeError("winner-band signal validation requires pandas and scikit-learn") from exc

    feature_columns = list(NUMERIC_FEATURES + CAT_FEATURES)
    pipeline = Pipeline([
        ("preprocess", ColumnTransformer([
            ("num", StandardScaler(), list(NUMERIC_FEATURES)),
            ("cat", OneHotEncoder(handle_unknown="ignore"), list(CAT_FEATURES)),
        ])),
        ("model", LogisticRegression(max_iter=2000, C=float(model_c), solver="lbfgs")),
    ])
    pipeline.fit(
        pd.DataFrame(fit_rows)[feature_columns],
        [int(row["outcome"]) for row in fit_rows],
    )
    return [
        float(value)
        for value in pipeline.predict_proba(pd.DataFrame(target_rows)[feature_columns])[:, 1]
    ]


def transform_probabilities(rows: list[dict[str, Any]], raw_signal: list[float]) -> dict[str, list[float]]:
    raw = raw_signal if len(raw_signal) == len(rows) else [row["probability"] for row in rows]
    return {
        "baseline": [row["probability"] for row in rows],
        "current": [row["current_probability"] for row in rows],
        "row_norm": normalize_snapshot_weights(rows, raw),
        "row_mult": normalize_snapshot_weights(
            rows,
            [max(0.0, raw[index]) * row["probability"] for index, row in enumerate(rows)],
        ),
        "row_sqrt": normalize_snapshot_weights(
            rows,
            [(max(0.0, raw[index]) ** 0.5) * row["probability"] for index, row in enumerate(rows)],
        ),
        "row_raw25": normalize_snapshot_weights(
            rows,
            [(max(0.0, raw[index]) ** 0.25) * row["probability"] for index, row in enumerate(rows)],
        ),
    }


def select_transform(selection_rows: list[dict[str, Any]], probabilities: dict[str, list[float]]) -> str:
    if not selection_rows:
        return "baseline"
    scores = {
        name: score_daily_first(selection_rows, values)
        for name, values in probabilities.items()
        if name in TRANSFORMS
    }
    return min(
        scores,
        key=lambda name: (
            math.inf if scores[name].get("candidate_brier") is None else scores[name]["candidate_brier"],
            list(TRANSFORMS).index(name),
        ),
    )


def _status(score: dict[str, Any], market_tol: float) -> str:
    if (
        score.get("delta_vs_current") is not None
        and score["delta_vs_current"] <= 0.0
        and score.get("delta_vs_market") is not None
        and score["delta_vs_market"] <= float(market_tol)
    ):
        return "PASS"
    return "BLOCK"


def _compact_score(score: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_days": score.get("market_days"),
        "candidate_brier": score.get("candidate_brier"),
        "current_brier": score.get("current_brier"),
        "market_brier": score.get("market_brier"),
        "delta_vs_current": score.get("delta_vs_current"),
        "delta_vs_market": score.get("delta_vs_market"),
    }


def build_payload(
    rows_paths: list[str | Path],
    market_tol: float = DEFAULT_MARKET_TOL,
    model_c: float = DEFAULT_MODEL_C,
) -> dict[str, Any]:
    rows = read_rows(rows_paths)
    split = nested_market_date_split(rows)
    fit_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []
    market_results = []

    for market_id, market_split in split.items():
        fit_rows.extend(rows_for_dates(rows, market_id, market_split["fit_dates"]))
        selection_rows.extend(rows_for_dates(rows, market_id, market_split["selection_dates"]))
        eval_rows.extend(rows_for_dates(rows, market_id, market_split["eval_dates"]))

    selection_signal = fit_predict_row_signal(fit_rows, selection_rows, model_c=model_c)
    selection_probabilities = transform_probabilities(selection_rows, selection_signal)
    selection_scores = {
        name: _compact_score(score_daily_first(selection_rows, values))
        for name, values in selection_probabilities.items()
    }
    selected_transform = select_transform(selection_rows, selection_probabilities)

    final_fit_rows = fit_rows + selection_rows
    eval_signal = fit_predict_row_signal(final_fit_rows, eval_rows, model_c=model_c)
    eval_probabilities = transform_probabilities(eval_rows, eval_signal)
    eval_scores = {
        name: _compact_score(score_daily_first(eval_rows, values))
        for name, values in eval_probabilities.items()
    }
    eval_best_transform = min(
        eval_scores,
        key=lambda name: (
            math.inf if eval_scores[name].get("candidate_brier") is None else eval_scores[name]["candidate_brier"],
            list(TRANSFORMS).index(name),
        ),
    )

    eval_index_by_market: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(eval_rows):
        eval_index_by_market[row["market_id"]].append(index)

    for market_id, indexes in sorted(eval_index_by_market.items()):
        market_rows = [eval_rows[index] for index in indexes]
        selected_probs = [eval_probabilities[selected_transform][index] for index in indexes]
        baseline_probs = [eval_probabilities["baseline"][index] for index in indexes]
        best_probs = [eval_probabilities[eval_best_transform][index] for index in indexes]
        selected_score = _compact_score(score_daily_first(market_rows, selected_probs))
        market_results.append({
            "market_id": market_id,
            "fit_dates": split[market_id]["fit_dates"],
            "selection_dates": split[market_id]["selection_dates"],
            "eval_dates": split[market_id]["eval_dates"],
            "selected_transform": selected_transform,
            "baseline": _compact_score(score_daily_first(market_rows, baseline_probs)),
            "selected": selected_score,
            "eval_best_diagnostic": {
                "classification": "diagnostic_only_eval_selected",
                "transform": eval_best_transform,
                "score": _compact_score(score_daily_first(market_rows, best_probs)),
            },
            "holdout_status": _status(selected_score, market_tol),
        })

    readiness_status = "PASS" if market_results and all(row["holdout_status"] == "PASS" for row in market_results) else "BLOCK"
    no_leakage_status = "PASS" if fit_rows and selection_rows and eval_rows else "WARN"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "evidence_classification": "development_nested_time_split_not_promotion_evidence",
        "readiness_status": readiness_status,
        "selected_transform": selected_transform,
        "eval_best_diagnostic_transform": eval_best_transform,
        "row_counts": {
            "total": len(rows),
            "fit": len(fit_rows),
            "selection": len(selection_rows),
            "eval": len(eval_rows),
        },
        "fit_config": {
            "model": "pooled_logistic_regression",
            "model_c": float(model_c),
            "market_tol": float(market_tol),
            "numeric_features": list(NUMERIC_FEATURES),
            "categorical_features": list(CAT_FEATURES),
            "transforms": list(TRANSFORMS),
        },
        "split_by_market": split,
        "no_leakage_audit": {
            "status": no_leakage_status,
            "primary_evidence_unit": "market_day",
            "detail": (
                "Row-signal transform is selected on pre-evaluation market-days, then the "
                "pooled row model is refit on all pre-evaluation days and scored only on "
                "later target dates. Market prices are used only as the scoring baseline."
            ),
        },
        "selection_holdout": {
            "scores": selection_scores,
            "selected_transform": selected_transform,
        },
        "eval_holdout": {
            "scores": eval_scores,
            "selected_transform": selected_transform,
            "eval_best_diagnostic_transform": eval_best_transform,
        },
        "market_results": market_results,
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


def _score_rows_for_report(scores: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for transform in TRANSFORMS:
        score = scores.get(transform) or {}
        rows.append([
            transform,
            fmt_num(score.get("candidate_brier")),
            fmt_num(score.get("current_brier")),
            fmt_num(score.get("market_brier")),
            fmt_signed(score.get("delta_vs_current")),
            fmt_signed(score.get("delta_vs_market")),
            score.get("market_days"),
        ])
    return rows


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    selection_scores = (payload.get("selection_holdout") or {}).get("scores") or {}
    eval_scores = (payload.get("eval_holdout") or {}).get("scores") or {}
    selected_eval = eval_scores.get(payload.get("selected_transform")) or {}
    eval_best = eval_scores.get(payload.get("eval_best_diagnostic_transform")) or {}
    lines = [
        "# Winner-Band Signal Validation",
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
            ["Selected transform", payload.get("selected_transform")],
            ["Eval-best transform (diagnostic)", payload.get("eval_best_diagnostic_transform")],
            ["Rows", (payload.get("row_counts") or {}).get("total")],
            ["Fit rows", (payload.get("row_counts") or {}).get("fit")],
            ["Selection rows", (payload.get("row_counts") or {}).get("selection")],
            ["Eval rows", (payload.get("row_counts") or {}).get("eval")],
            ["Model", (payload.get("fit_config") or {}).get("model")],
            ["Model C", fmt_num((payload.get("fit_config") or {}).get("model_c"))],
        ],
    )
    lines += [
        "",
        "## Selection Holdout",
        "",
    ]
    lines += markdown_table(
        ["Transform", "Candidate", "Current", "Market", "Delta Current", "Delta Market", "Market Days"],
        _score_rows_for_report(selection_scores),
    )
    lines += [
        "",
        "## Eval Holdout",
        "",
    ]
    lines += markdown_table(
        ["Transform", "Candidate", "Current", "Market", "Delta Current", "Delta Market", "Market Days"],
        _score_rows_for_report(eval_scores),
    )
    lines += [
        "",
        "## Selected Versus Eval-Best",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Transform", "Candidate", "Current", "Market", "Delta Current", "Delta Market"],
        [
            [
                "selected pre-eval",
                payload.get("selected_transform"),
                fmt_num(selected_eval.get("candidate_brier")),
                fmt_num(selected_eval.get("current_brier")),
                fmt_num(selected_eval.get("market_brier")),
                fmt_signed(selected_eval.get("delta_vs_current")),
                fmt_signed(selected_eval.get("delta_vs_market")),
            ],
            [
                "eval best (diagnostic)",
                payload.get("eval_best_diagnostic_transform"),
                fmt_num(eval_best.get("candidate_brier")),
                fmt_num(eval_best.get("current_brier")),
                fmt_num(eval_best.get("market_brier")),
                fmt_signed(eval_best.get("delta_vs_current")),
                fmt_signed(eval_best.get("delta_vs_market")),
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
            "Fit Dates",
            "Selection Dates",
            "Eval Dates",
            "Baseline",
            "Selected",
            "Current",
            "Market",
            "Delta Current",
            "Delta Market",
            "Eval-Best Transform",
            "Eval-Best Gap",
            "Status",
        ],
        [
            [
                row.get("market_id"),
                ", ".join(row.get("fit_dates") or []),
                ", ".join(row.get("selection_dates") or []),
                ", ".join(row.get("eval_dates") or []),
                fmt_num((row.get("baseline") or {}).get("candidate_brier")),
                fmt_num((row.get("selected") or {}).get("candidate_brier")),
                fmt_num((row.get("selected") or {}).get("current_brier")),
                fmt_num((row.get("selected") or {}).get("market_brier")),
                fmt_signed((row.get("selected") or {}).get("delta_vs_current")),
                fmt_signed((row.get("selected") or {}).get("delta_vs_market")),
                (row.get("eval_best_diagnostic") or {}).get("transform"),
                fmt_signed(((row.get("eval_best_diagnostic") or {}).get("score") or {}).get("delta_vs_market")),
                row.get("holdout_status"),
            ]
            for row in payload.get("market_results") or []
        ],
    )
    audit = payload.get("no_leakage_audit") or {}
    lines += [
        "",
        "## No-Leakage Audit",
        "",
        f"Status: `{audit.get('status')}`",
        "",
        str(audit.get("detail") or ""),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate nested winner-band row-signal transforms.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--model-c", type=float, default=DEFAULT_MODEL_C)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    payload = build_payload(
        args.rows,
        market_tol=args.market_tol,
        model_c=args.model_c,
    )
    write_json(args.out, payload)
    write_markdown_report(args.report, payload)
    print(f"Winner-band signal validation: {payload['readiness_status']}")
    print(f"Wrote JSON to {args.out}")
    print(f"Wrote report to {args.report}")
    return payload


if __name__ == "__main__":
    main()
