"""Development diagnostic for Item 224 bottom-market no-market winner repair."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "item224_no_market_ranked_winner_repair_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_INPUT_DIR = DEFAULT_BACKTEST_ROOT / "item224_basket_inputs"
DEFAULT_INPUTS = (
    DEFAULT_INPUT_DIR / "bottom_current_max_trust_variant_rows.csv",
    DEFAULT_INPUT_DIR / "bottom_item147_time_split_alpha_variant_rows.csv",
    DEFAULT_INPUT_DIR / "bottom_item187_forecast_radiation_shadow_variants.csv",
    DEFAULT_INPUT_DIR / "bottom_item32_reanalysis_rich_no_pressure_full_merged_variant_rows.csv",
    DEFAULT_INPUT_DIR / "bottom_item50_pooled_candidate_shadow_variants.csv",
    DEFAULT_INPUT_DIR / "bottom_item70_exact_winner_shadow_variants_full.csv",
    DEFAULT_INPUT_DIR / "bottom_item71_dynamic_source_shadow_variants_full.csv",
    DEFAULT_INPUT_DIR / "bottom_pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv",
)
DEFAULT_OUT_ROWS = DEFAULT_BACKTEST_ROOT / "item224_bottom_no_market_ranked_winner_repair_rows.csv"
DEFAULT_OUT_JSON = DEFAULT_BACKTEST_ROOT / "item224_bottom_no_market_ranked_winner_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item224_bottom_no_market_ranked_winner_repair_report.md"
DEFAULT_TRAIN_DATES = ("2026-06-07", "2026-06-08")
DEFAULT_EVAL_DATES = ("2026-06-12", "2026-06-13")
KEY_FIELDS = ("market_id", "target_date", "snapshot_id", "band_key")
EXCLUDED_LABEL_OR_MARKET_FEATURES = ("outcome", "market_yes", "settlement_distance_bucket")
EXTRA_FIELDS = (
    "variant_id",
    "variant_family",
    "uses_market_features",
    "claim_lane",
    "counts_toward_weather_model_promotion",
    "quote_risk_eligible",
    "quote_risk_gate_reason",
)


def finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def logit_probability(value: Any) -> float:
    probability = finite_float(value, 0.0) or 0.0
    probability = max(1e-5, min(1.0 - 1e-5, probability))
    return math.log(probability / (1.0 - probability))


def row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("market_id") or "").strip().lower(),
        str(row.get("target_date") or "").strip(),
        str(row.get("snapshot_id") or "").strip(),
        str(row.get("band_key") or "").strip(),
    )


def read_candidate_inputs(paths: list[str | Path]) -> tuple[list[str], dict[tuple[str, ...], dict[str, Any]], dict[tuple[str, ...], dict[str, float]]]:
    variant_names: list[str] = []
    base_rows: dict[tuple[str, ...], dict[str, Any]] = {}
    probabilities: dict[tuple[str, ...], dict[str, float]] = {}
    for path_value in paths:
        path = Path(path_value)
        variant_name = path.stem
        variant_names.append(variant_name)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = row_key(row)
                if not all(key):
                    continue
                if key not in base_rows or "current_max_trust" in variant_name:
                    base_rows[key] = dict(row)
                probability = finite_float(row.get("probability"))
                if probability is not None:
                    probabilities.setdefault(key, {})[variant_name] = probability
    return variant_names, base_rows, probabilities


def modal_features_by_key(
    variant_names: list[str],
    base_rows: dict[tuple[str, ...], dict[str, Any]],
    probabilities: dict[tuple[str, ...], dict[str, float]],
) -> dict[tuple[str, ...], dict[str, float]]:
    by_group: dict[tuple[str, str, str], list[tuple[str, ...]]] = defaultdict(list)
    for key in base_rows:
        if key in probabilities:
            by_group[key[:3]].append(key)

    modal_features: dict[tuple[str, ...], dict[str, float]] = defaultdict(dict)
    for keys in by_group.values():
        for variant_name in variant_names:
            values = []
            for key in keys:
                base = base_rows[key]
                probability = probabilities.get(key, {}).get(variant_name)
                if probability is None:
                    probability = finite_float(base.get("current_probability"), 0.0) or 0.0
                values.append((key, probability, finite_float(base.get("bin_value"), 0.0) or 0.0))
            if not values:
                continue
            sorted_values = sorted(values, key=lambda item: item[1], reverse=True)
            _top_key, top_probability, top_bin = sorted_values[0]
            total = sum(max(0.0, probability) for _key, probability, _bin in values) or 1.0
            entropy = -sum(
                (max(1e-12, probability / total)) * math.log(max(1e-12, probability / total))
                for _key, probability, _bin in values
            )
            ranks = {key: index + 1 for index, (key, _probability, _bin) in enumerate(sorted_values)}
            for key, probability, bin_value in values:
                modal_features[key][f"{variant_name}_rank"] = float(ranks[key])
                modal_features[key][f"{variant_name}_gap_to_top_p"] = top_probability - probability
                modal_features[key][f"{variant_name}_distance_to_top_bin"] = abs(bin_value - top_bin)
                modal_features[key][f"{variant_name}_snapshot_entropy"] = entropy
    return modal_features


def build_feature_records(
    variant_names: list[str],
    base_rows: dict[tuple[str, ...], dict[str, Any]],
    probabilities: dict[tuple[str, ...], dict[str, float]],
    *,
    train_dates: set[str],
    eval_dates: set[str],
) -> list[dict[str, Any]]:
    modal_features = modal_features_by_key(variant_names, base_rows, probabilities)
    records: list[dict[str, Any]] = []
    for key in sorted(set(base_rows) & set(probabilities)):
        base = base_rows[key]
        target_date = str(base.get("target_date") or "")
        if target_date not in train_dates | eval_dates:
            continue
        outcome = finite_float(base.get("outcome"))
        if outcome is None:
            continue
        record: dict[str, Any] = {}
        for variant_name in variant_names:
            probability = probabilities.get(key, {}).get(variant_name)
            if probability is None:
                probability = finite_float(base.get("current_probability"), 0.0) or 0.0
            record[f"logit_{variant_name}"] = logit_probability(probability)
            record[f"p_{variant_name}"] = probability
            for suffix in ("_rank", "_gap_to_top_p", "_distance_to_top_bin", "_snapshot_entropy"):
                record[f"{variant_name}{suffix}"] = modal_features.get(key, {}).get(f"{variant_name}{suffix}")
        record.update({
            "market_id": str(base.get("market_id") or "").strip().lower(),
            "bin_type": str(base.get("bin_type") or "").strip().lower(),
            "cutoff_regime": str(base.get("cutoff_regime") or "").strip().lower(),
            "source_freshness_state": str(base.get("source_freshness_state") or "").strip().lower(),
            "forecast_source_count_bucket": str(base.get("forecast_source_count_bucket") or "").strip().lower(),
            "forecast_disagreement_bucket": str(base.get("forecast_disagreement_bucket") or "").strip().lower(),
            "forecast_bucket_pressure": str(base.get("forecast_bucket_pressure") or "").strip().lower(),
            "cutoff_hour": finite_float(base.get("cutoff_hour"), 0.0) or 0.0,
            "bin_value": finite_float(base.get("bin_value"), 0.0) or 0.0,
            "target_date": target_date,
            "snapshot_group": "|".join(key[:3]),
            "key": key,
            "outcome": int(outcome),
        })
        records.append(record)
    return records


def numeric_columns(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return []
    return [
        key
        for key in records[0]
        if key.startswith(("logit_", "p_"))
        or key.endswith(("_rank", "_gap_to_top_p", "_distance_to_top_bin", "_snapshot_entropy"))
    ] + ["cutoff_hour", "bin_value"]


def categorical_columns() -> list[str]:
    return [
        "market_id",
        "bin_type",
        "cutoff_regime",
        "source_freshness_state",
        "forecast_source_count_bucket",
        "forecast_disagreement_bucket",
        "forecast_bucket_pressure",
    ]


def predict_ranked_repair(
    records: list[dict[str, Any]],
    *,
    train_dates: set[str],
    regularization_c: float,
    group_normalized_weight: float,
) -> np.ndarray:
    if not records:
        return np.array([])
    frame = pd.DataFrame(records)
    train_mask = frame["target_date"].isin(train_dates)
    if frame.loc[train_mask, "outcome"].nunique() < 2:
        raise ValueError("ranked winner repair training data must contain both outcome classes")

    num_cols = numeric_columns(records)
    cat_cols = categorical_columns()
    preprocessor = ColumnTransformer([
        ("num", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), num_cols),
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5), cat_cols),
    ])
    model = Pipeline([
        ("preprocessor", preprocessor),
        ("logistic", LogisticRegression(
            max_iter=1000,
            C=float(regularization_c),
            class_weight="balanced",
        )),
    ])
    model.fit(frame.loc[train_mask, num_cols + cat_cols], frame.loc[train_mask, "outcome"])
    raw = model.predict_proba(frame[num_cols + cat_cols])[:, 1]
    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for index, group_key in enumerate(frame["snapshot_group"]):
        grouped[str(group_key)].append((index, float(raw[index])))

    weight = max(0.0, min(1.0, float(group_normalized_weight)))
    predictions = np.zeros(len(frame))
    for items in grouped.values():
        total = sum(probability for _index, probability in items)
        fallback = 1.0 / len(items) if items else 0.0
        for index, probability in items:
            normalized = probability / total if total > 0 else fallback
            predictions[index] = max(1e-5, min(1.0 - 1e-5, weight * normalized + (1.0 - weight) * probability))
    return predictions


def metric_summary(records: list[dict[str, Any]], predictions: np.ndarray, mask: np.ndarray, base_rows: dict[tuple[str, ...], dict[str, Any]]) -> dict[str, Any]:
    indexes = np.where(mask)[0]
    if len(indexes) == 0:
        return {"rows": 0}
    outcomes = np.array([records[index]["outcome"] for index in indexes], dtype=float)
    candidate = predictions[indexes]
    current = np.array([
        finite_float(base_rows[records[index]["key"]].get("current_probability"), 0.0) or 0.0
        for index in indexes
    ])
    market = np.array([
        finite_float(base_rows[records[index]["key"]].get("market_yes"), 0.0) or 0.0
        for index in indexes
    ])
    candidate_brier = float(np.mean((candidate - outcomes) ** 2))
    current_brier = float(np.mean((current - outcomes) ** 2))
    market_brier = float(np.mean((market - outcomes) ** 2))
    clipped_candidate = np.clip(candidate, 1e-5, 1.0 - 1e-5)
    clipped_current = np.clip(current, 1e-5, 1.0 - 1e-5)
    clipped_market = np.clip(market, 1e-5, 1.0 - 1e-5)
    return {
        "rows": int(len(indexes)),
        "brier_candidate": candidate_brier,
        "brier_current": current_brier,
        "brier_market": market_brier,
        "delta_vs_current": candidate_brier - current_brier,
        "delta_vs_market": candidate_brier - market_brier,
        "logloss_candidate": float(log_loss(outcomes, clipped_candidate, labels=[0, 1])),
        "logloss_current": float(log_loss(outcomes, clipped_current, labels=[0, 1])),
        "logloss_market": float(log_loss(outcomes, clipped_market, labels=[0, 1])),
    }


def output_fieldnames(base_rows: dict[tuple[str, ...], dict[str, Any]]) -> list[str]:
    fieldnames = list(next(iter(base_rows.values())).keys()) if base_rows else []
    for field in reversed(EXTRA_FIELDS):
        if field not in fieldnames:
            fieldnames.insert(0, field)
    output = []
    for field in fieldnames:
        if field not in output:
            output.append(field)
    return output


def write_rows(
    rows_out: str | Path,
    records: list[dict[str, Any]],
    predictions: np.ndarray,
    base_rows: dict[tuple[str, ...], dict[str, Any]],
) -> Path:
    path = Path(rows_out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = output_fieldnames(base_rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for index, record in enumerate(records):
            base = dict(base_rows[record["key"]])
            base.update({
                "variant_id": "item224_bottom_no_market_ranked_winner_repair_v0_1",
                "variant_family": "bottom_no_market_ranked_winner_mass",
                "uses_market_features": "false",
                "claim_lane": "development_diagnostic_no_market_repair",
                "counts_toward_weather_model_promotion": "false",
                "quote_risk_eligible": "false",
                "quote_risk_gate_reason": "development_diagnostic_not_promotion_evidence",
                "probability": float(predictions[index]),
                "recorded_probability": float(predictions[index]),
            })
            writer.writerow(base)
    return path


def build_payload(
    input_paths: list[str | Path],
    *,
    train_dates: tuple[str, ...] = DEFAULT_TRAIN_DATES,
    eval_dates: tuple[str, ...] = DEFAULT_EVAL_DATES,
    regularization_c: float = 0.03,
    group_normalized_weight: float = 0.85,
    rows_out: str | Path = DEFAULT_OUT_ROWS,
) -> dict[str, Any]:
    train_set = set(train_dates)
    eval_set = set(eval_dates)
    variant_names, base_rows, probabilities = read_candidate_inputs(input_paths)
    records = build_feature_records(
        variant_names,
        base_rows,
        probabilities,
        train_dates=train_set,
        eval_dates=eval_set,
    )
    predictions = predict_ranked_repair(
        records,
        train_dates=train_set,
        regularization_c=regularization_c,
        group_normalized_weight=group_normalized_weight,
    )
    rows_path = write_rows(rows_out, records, predictions, base_rows)
    frame = pd.DataFrame(records)
    train_mask = frame["target_date"].isin(train_set).to_numpy()
    eval_mask = frame["target_date"].isin(eval_set).to_numpy()
    by_eval_market = {}
    for market in sorted(frame.loc[eval_mask, "market_id"].unique()):
        by_eval_market[market] = metric_summary(
            records,
            predictions,
            (frame["target_date"].isin(eval_set) & (frame["market_id"] == market)).to_numpy(),
            base_rows,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_classification": "development_time_split_no_market_diagnostic_not_promotion_evidence",
        "excluded_label_derived_features": list(EXCLUDED_LABEL_OR_MARKET_FEATURES),
        "model_selection": {
            "regularization_c": float(regularization_c),
            "group_normalized_weight": float(group_normalized_weight),
        },
        "train_dates": sorted(train_set),
        "eval_dates": sorted(eval_set),
        "input_paths": [str(path) for path in input_paths],
        "variant_feature_names": variant_names,
        "output_rows": str(rows_path),
        "row_count": len(records),
        "train": metric_summary(records, predictions, train_mask, base_rows),
        "eval": metric_summary(records, predictions, eval_mask, base_rows),
        "by_eval_market": by_eval_market,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Item 224 No-Market Ranked Winner Repair",
        "",
        f"Schema: `{payload.get('schema_version')}`",
        f"Evidence: `{payload.get('evidence_classification')}`",
        "",
        "## Summary",
        "",
    ]
    eval_summary = payload.get("eval") or {}
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Rows", payload.get("row_count")],
            ["Train dates", ", ".join(payload.get("train_dates") or [])],
            ["Eval dates", ", ".join(payload.get("eval_dates") or [])],
            ["Eval delta vs current", fmt_signed(eval_summary.get("delta_vs_current"))],
            ["Eval delta vs market", fmt_signed(eval_summary.get("delta_vs_market"))],
            ["Output rows", payload.get("output_rows")],
            ["Excluded fields", ", ".join(payload.get("excluded_label_derived_features") or [])],
        ],
    )
    lines += ["", "## Held-Out Markets", ""]
    lines += markdown_table(
        ["Market", "Rows", "Candidate", "Current", "Market", "Delta Current", "Delta Market"],
        [
            [
                market,
                row.get("rows"),
                fmt_num(row.get("brier_candidate")),
                fmt_num(row.get("brier_current")),
                fmt_num(row.get("brier_market")),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
            ]
            for market, row in sorted((payload.get("by_eval_market") or {}).items())
        ],
    )
    return "\n".join(lines) + "\n"


def write_json_report(payload: dict[str, Any], json_out: str | Path, report_out: str | Path) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def parse_dates(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Item 224 no-market ranked winner repair diagnostic rows.")
    parser.add_argument("rows", nargs="*", help="Candidate row CSV exports. Defaults to Item 224 bottom-market inputs.")
    parser.add_argument("--train-dates", default=",".join(DEFAULT_TRAIN_DATES))
    parser.add_argument("--eval-dates", default=",".join(DEFAULT_EVAL_DATES))
    parser.add_argument("--regularization-c", type=float, default=0.03)
    parser.add_argument("--group-normalized-weight", type=float, default=0.85)
    parser.add_argument("--out-rows", default=str(DEFAULT_OUT_ROWS))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    input_paths = [Path(path) for path in args.rows] if args.rows else list(DEFAULT_INPUTS)
    payload = build_payload(
        input_paths,
        train_dates=parse_dates(args.train_dates),
        eval_dates=parse_dates(args.eval_dates),
        regularization_c=args.regularization_c,
        group_normalized_weight=args.group_normalized_weight,
        rows_out=args.out_rows,
    )
    json_path, report_path = write_json_report(payload, args.out_json, args.report)
    print(
        "Item 224 no-market ranked winner repair: "
        f"eval delta vs current {fmt_signed((payload.get('eval') or {}).get('delta_vs_current'))}, "
        f"delta vs market {fmt_signed((payload.get('eval') or {}).get('delta_vs_market'))}"
    )
    print(f"Rows written to {payload.get('output_rows')}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
