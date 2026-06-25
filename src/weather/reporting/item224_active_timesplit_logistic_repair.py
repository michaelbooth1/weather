"""Item 224 active-source time-split logistic repair export."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import config_path, data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "item224_active_timesplit_logistic_repair_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_INPUT_ROWS = DEFAULT_BACKTEST_ROOT / "item224_active_source_route_composite_rows.csv"
DEFAULT_BASE_REGISTRY = config_path("model_variant_registry.json")
DEFAULT_OUT_ROWS = DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_rows.csv"
DEFAULT_OUT_JSON = DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_report.md"
DEFAULT_REGISTRY_OUT = DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_registry.json"
DEFAULT_CONTRACT_OUT = DEFAULT_BACKTEST_ROOT / "item224_active_timesplit_logistic_repair_contract.json"

VARIANT_ID = "item224_active_timesplit_logistic_repair_v0_1"
VARIANT_FAMILY = "item224_active_timesplit_logistic_repair"
DEFAULT_TRAINING_DATES = ("2026-06-07", "2026-06-08")
DEFAULT_EVAL_DATES = ("2026-06-12", "2026-06-13")
MODEL_LABEL = "logistic_regression_c0p003_balanced"
MODEL_C = 0.003
HIGH_CONFIDENCE_LOW = 0.001
HIGH_CONFIDENCE_HIGH = 0.999
EARLY_ADJACENT_CURRENT_CAP_MAX_CURRENT = 0.05
EARLY_ADJACENT_CURRENT_CAP_MIN_GAP = 0.08

NUMERIC_FEATURES = (
    "active_route_probability",
    "current_probability",
    "bin_value",
    "cutoff_hour",
)
CATEGORICAL_FEATURES = (
    "market_id",
    "bin_type",
    "cutoff_regime",
    "source_freshness_state",
    "settlement_distance_bucket",
    "forecast_source_count_bucket",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "feature_missingness_hash",
    "route_source_variant_id",
)
EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS = (
    "outcome",
    "market_yes",
    "target_date",
    "snapshot_id",
    "captured_at_local",
)
REPAIR_EXTRA_FIELDS = (
    "item224_active_timesplit_logistic_raw_probability",
    "item224_active_timesplit_guardrail",
    "active_timesplit_training_window",
    "active_timesplit_eval_window",
    "active_timesplit_model",
    "active_timesplit_source_variant_id",
)
COUNTABLE_ROW_DEFAULTS = {
    "variant_id": VARIANT_ID,
    "variant_family": VARIANT_FAMILY,
    "uses_market_features": "false",
    "is_control": "false",
    "claim_lane": "weather_only_core_model",
    "counts_toward_weather_model_promotion": "true",
    "quote_risk_eligible": "false",
    "quote_risk_gate_reason": "weather_only_core_model",
    "postprocess_config_hash": VARIANT_ID,
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp_probability(value: Any) -> float:
    return max(1e-15, min(1.0 - 1e-15, finite_float(value)))


def read_rows(path: str | Path) -> tuple[list[str], list[dict[str, Any]]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_rows(path: str | Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output


def output_fieldnames(fieldnames: list[str]) -> list[str]:
    output = list(fieldnames)
    for field in REPAIR_EXTRA_FIELDS:
        if field not in output:
            output.append(field)
    return output


def row_features(row: dict[str, Any]) -> dict[str, Any]:
    features = {
        "active_route_probability": finite_float(row.get("probability")),
        "current_probability": finite_float(row.get("current_probability")),
        "bin_value": finite_float(row.get("bin_value")),
        "cutoff_hour": finite_float(row.get("cutoff_hour")),
    }
    for field in CATEGORICAL_FEATURES:
        features[field] = str(row.get(field) or "")
    return features


def split_rows(
    rows: list[dict[str, Any]],
    *,
    training_dates: tuple[str, ...],
    eval_dates: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    training_set = set(training_dates)
    eval_set = set(eval_dates)
    return (
        [row for row in rows if str(row.get("target_date") or "") in training_set],
        [row for row in rows if str(row.get("target_date") or "") in eval_set],
    )


def fit_predict_probabilities(train_rows: list[dict[str, Any]], eval_rows: list[dict[str, Any]]) -> list[float]:
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    if not train_rows:
        raise ValueError("training split has no rows")
    if not eval_rows:
        raise ValueError("evaluation split has no rows")

    columns = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
    train_frame = pd.DataFrame([row_features(row) for row in train_rows], columns=columns)
    eval_frame = pd.DataFrame([row_features(row) for row in eval_rows], columns=columns)
    labels = [int(finite_float(row.get("outcome"))) for row in train_rows]
    try:
        encoder = OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse_output=True)
    except TypeError:
        encoder = OneHotEncoder(handle_unknown="ignore", min_frequency=10, sparse=True)
    model = Pipeline([
        ("features", ColumnTransformer([
            ("num", StandardScaler(), list(NUMERIC_FEATURES)),
            ("cat", encoder, list(CATEGORICAL_FEATURES)),
        ])),
        (
            "model",
            LogisticRegression(max_iter=1000, C=MODEL_C, class_weight="balanced"),
        ),
    ])
    model.fit(train_frame, labels)
    return [clamp_probability(probability) for probability in model.predict_proba(eval_frame)[:, 1]]


def early_adjacent_current_cap_applies(row: dict[str, Any], raw_probability: float, current: float) -> bool:
    return (
        str(row.get("cutoff_regime") or "").strip().lower() == "early"
        and str(row.get("bin_type") or "").strip().lower() == "eq"
        and str(row.get("settlement_distance_bucket") or "").strip() in {"1", "2"}
        and current < EARLY_ADJACENT_CURRENT_CAP_MAX_CURRENT
        and raw_probability - current > EARLY_ADJACENT_CURRENT_CAP_MIN_GAP
    )


def repaired_probability(
    row: dict[str, Any],
    raw_probability: float,
) -> tuple[float, list[str]]:
    current = clamp_probability(row.get("current_probability"))
    probability = clamp_probability(raw_probability)
    guardrails = []
    if current <= HIGH_CONFIDENCE_LOW or current >= HIGH_CONFIDENCE_HIGH:
        probability = current
        guardrails.append("preserve_high_confidence_current_v0_1")
    if early_adjacent_current_cap_applies(row, raw_probability, current):
        probability = current
        guardrails.append("early_adjacent_low_current_gap_cap_v0_1")
    return probability, guardrails


def decorate_eval_rows(
    eval_rows: list[dict[str, Any]],
    raw_probabilities: list[float],
    *,
    training_dates: tuple[str, ...],
    eval_dates: tuple[str, ...],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(eval_rows) != len(raw_probabilities):
        raise ValueError("evaluation rows and raw probability count differ")
    output = []
    guardrail_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for row, raw_probability in zip(eval_rows, raw_probabilities):
        final_probability, guardrails = repaired_probability(row, raw_probability)
        guardrail_counts.update(guardrails)
        source_id = str(row.get("route_source_variant_id") or "")
        if source_id:
            source_counts[source_id] += 1
        item = dict(row)
        item.update(COUNTABLE_ROW_DEFAULTS)
        item.update({
            "probability": repr(float(final_probability)),
            "recorded_probability": repr(float(final_probability)),
            "item224_active_timesplit_logistic_raw_probability": repr(float(raw_probability)),
            "item224_active_timesplit_guardrail": ";".join(guardrails),
            "active_timesplit_training_window": ",".join(training_dates),
            "active_timesplit_eval_window": ",".join(eval_dates),
            "active_timesplit_model": MODEL_LABEL,
            "active_timesplit_source_variant_id": source_id,
        })
        output.append(item)
    return output, {
        "guardrail_counts": dict(sorted(guardrail_counts.items())),
        "active_source_lineage_counts": dict(sorted(source_counts.items())),
    }


def brier(probability: Any, outcome: Any) -> float:
    return (clamp_probability(probability) - int(finite_float(outcome))) ** 2


def score_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0}
    candidate = sum(brier(row.get("probability"), row.get("outcome")) for row in rows) / len(rows)
    current = sum(brier(row.get("current_probability"), row.get("outcome")) for row in rows) / len(rows)
    market = sum(brier(row.get("market_yes"), row.get("outcome")) for row in rows) / len(rows)
    return {
        "rows": len(rows),
        "candidate_brier": candidate,
        "current_brier": current,
        "market_brier": market,
        "delta_vs_current": candidate - current,
        "delta_vs_market": candidate - market,
    }


def market_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("market_id") or "")].append(row)
    return {
        market_id: score_summary(market_rows)
        for market_id, market_rows in sorted(grouped.items())
        if market_id
    }


def active_contract(rows_out: str | Path) -> dict[str, Any]:
    return {
        "variant_id": VARIANT_ID,
        "variant_family": VARIANT_FAMILY,
        "lifecycle": "active",
        "track": "no_market",
        "roles": ["candidate", "no-market", "item224-active-timesplit-probe"],
        "active_for_headline": True,
        "artifact_required": False,
        "prediction_function": "weather.reporting.item224_active_timesplit_logistic_repair:build_payload",
        "prediction_mode": "band_binary",
        "export_family": VARIANT_FAMILY,
        "default_export_path": str(rows_out).replace("\\", "/"),
        "postprocess_config_hash": VARIANT_ID,
        "live_runtime": "active_timesplit_logistic_repair",
        "roadmap_items": [224],
    }


def write_contract(path: str | Path, contract: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return output


def write_registry(
    path: str | Path,
    *,
    base_registry: str | Path,
    contract: dict[str, Any],
    generated_at_utc: str,
) -> Path:
    registry = json.loads(Path(base_registry).read_text(encoding="utf-8"))
    variants = [
        row
        for row in registry.get("variants") or []
        if row.get("variant_id") != contract.get("variant_id")
    ]
    variants.append(contract)
    registry["variants"] = variants
    registry["updated_at_utc"] = generated_at_utc
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return output


def build_payload(
    input_rows: str | Path = DEFAULT_INPUT_ROWS,
    *,
    rows_out: str | Path = DEFAULT_OUT_ROWS,
    registry_out: str | Path = DEFAULT_REGISTRY_OUT,
    contract_out: str | Path = DEFAULT_CONTRACT_OUT,
    base_registry: str | Path = DEFAULT_BASE_REGISTRY,
    training_dates: tuple[str, ...] = DEFAULT_TRAINING_DATES,
    eval_dates: tuple[str, ...] = DEFAULT_EVAL_DATES,
) -> dict[str, Any]:
    fieldnames, source_rows = read_rows(input_rows)
    train_rows, eval_rows = split_rows(
        source_rows,
        training_dates=tuple(training_dates),
        eval_dates=tuple(eval_dates),
    )
    raw_probabilities = fit_predict_probabilities(train_rows, eval_rows)
    repaired_rows, repair_summary = decorate_eval_rows(
        eval_rows,
        raw_probabilities,
        training_dates=tuple(training_dates),
        eval_dates=tuple(eval_dates),
    )
    rows_path = write_rows(rows_out, output_fieldnames(fieldnames), repaired_rows)
    generated_at = utc_iso()
    contract = active_contract(rows_path)
    contract_path = write_contract(contract_out, contract)
    registry_path = write_registry(
        registry_out,
        base_registry=base_registry,
        contract=contract,
        generated_at_utc=generated_at,
    )
    guardrail_counts = repair_summary["guardrail_counts"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "status": "ACTIVE_CONTRACT_EXPORT_READY",
        "variant_id": VARIANT_ID,
        "variant_family": VARIANT_FAMILY,
        "input_rows": str(input_rows),
        "output_rows": str(rows_path),
        "registry_out": str(registry_path),
        "contract_out": str(contract_path),
        "training_dates": list(training_dates),
        "eval_dates": list(eval_dates),
        "train_rows": len(train_rows),
        "eval_rows": len(repaired_rows),
        "model": {
            "type": "sklearn.linear_model.LogisticRegression",
            "C": MODEL_C,
            "class_weight": "balanced",
            "max_iter": 1000,
        },
        "feature_policy": {
            "numeric_features": list(NUMERIC_FEATURES),
            "categorical_features": list(CATEGORICAL_FEATURES),
            "excluded_label_market_or_identity_fields": list(EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS),
            "uses_market_features": False,
            "uses_eval_outcomes_for_training": False,
        },
        "guardrails": {
            "preserve_high_confidence_current_v0_1": {
                "current_probability_low": HIGH_CONFIDENCE_LOW,
                "current_probability_high": HIGH_CONFIDENCE_HIGH,
                "rows": int(guardrail_counts.get("preserve_high_confidence_current_v0_1", 0)),
            },
            "early_adjacent_low_current_gap_cap_v0_1": {
                "cutoff_regime": "early",
                "bin_type": "eq",
                "settlement_distance_bucket": ["1", "2"],
                "current_probability_max": EARLY_ADJACENT_CURRENT_CAP_MAX_CURRENT,
                "raw_probability_minus_current_min": EARLY_ADJACENT_CURRENT_CAP_MIN_GAP,
                "rows": int(guardrail_counts.get("early_adjacent_low_current_gap_cap_v0_1", 0)),
            },
        },
        "active_source_lineage_counts": repair_summary["active_source_lineage_counts"],
        "aggregate": score_summary(repaired_rows),
        "market_rows": market_summaries(repaired_rows),
    }


def render_report(payload: dict[str, Any]) -> str:
    aggregate = payload.get("aggregate") or {}
    guardrails = payload.get("guardrails") or {}
    lines = [
        "# Item 224 Active Time-Split Logistic Repair",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Scope",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variant", payload.get("variant_id")],
            ["Input rows", payload.get("input_rows")],
            ["Output rows", payload.get("output_rows")],
            ["Training dates", ", ".join(payload.get("training_dates") or [])],
            ["Evaluation dates", ", ".join(payload.get("eval_dates") or [])],
            ["Train rows", payload.get("train_rows")],
            ["Eval rows", payload.get("eval_rows")],
        ],
    )
    lines += ["", "## Aggregate", ""]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Candidate Brier", fmt_num(aggregate.get("candidate_brier"))],
            ["Current Brier", fmt_num(aggregate.get("current_brier"))],
            ["Market Brier", fmt_num(aggregate.get("market_brier"))],
            ["Delta vs current", fmt_signed(aggregate.get("delta_vs_current"))],
            ["Delta vs market", fmt_signed(aggregate.get("delta_vs_market"))],
        ],
    )
    lines += ["", "## Guardrails", ""]
    lines += markdown_table(
        ["Guardrail", "Rows"],
        [
            [name, (row or {}).get("rows")]
            for name, row in guardrails.items()
        ],
    )
    lines += ["", "## Market Rows", ""]
    lines += markdown_table(
        ["Market", "Rows", "Delta Current", "Delta Market"],
        [
            [
                market_id,
                row.get("rows"),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
            ]
            for market_id, row in (payload.get("market_rows") or {}).items()
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


def parse_date_list(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Item 224 active-source time-split repair export.")
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--out-rows", default=str(DEFAULT_OUT_ROWS))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--registry-out", default=str(DEFAULT_REGISTRY_OUT))
    parser.add_argument("--contract-out", default=str(DEFAULT_CONTRACT_OUT))
    parser.add_argument("--base-registry", default=str(DEFAULT_BASE_REGISTRY))
    parser.add_argument("--training-dates", default=",".join(DEFAULT_TRAINING_DATES))
    parser.add_argument("--eval-dates", default=",".join(DEFAULT_EVAL_DATES))
    args = parser.parse_args(argv)

    payload = build_payload(
        args.input_rows,
        rows_out=args.out_rows,
        registry_out=args.registry_out,
        contract_out=args.contract_out,
        base_registry=args.base_registry,
        training_dates=parse_date_list(args.training_dates),
        eval_dates=parse_date_list(args.eval_dates),
    )
    json_path, report_path = write_json_report(payload, args.out_json, args.report)
    print(f"Item224 active time-split repair rows written to {payload['output_rows']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    print(f"Registry written to {payload['registry_out']}")
    print(f"Contract written to {payload['contract_out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
