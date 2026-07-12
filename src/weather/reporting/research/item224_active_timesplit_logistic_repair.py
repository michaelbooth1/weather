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
    "forecast_source_count_bucket",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "route_source_variant_id",
)
GUARDRAIL_FEATURES = (
    "current_probability",
)
SETTLEMENT_OR_OUTCOME_DERIVED_FIELDS = (
    "outcome",
    "settlement_distance_bucket",
    "used_extra_location_labels",
    "target_local_labels_present",
    "extra_location_gate_status",
    "extra_location_gate_reason",
    "extra_location_weight",
    "casebook_taxonomy",
    "casebook_case_id",
    "casebook_result",
    "casebook_slice_type",
    "feature_schema_version",
    "feature_family_hash",
    "feature_missingness_hash",
    "micro_gate_taxonomy",
    "micro_gate_reason",
)
MARKET_DERIVED_FIELDS = (
    "market_yes",
    "clob_feature_available",
    "clob_midpoint",
    "clob_spread",
    "clob_liquidity_score",
)
EVAL_IDENTITY_FIELDS = (
    "target_date",
    "snapshot_id",
    "band_key",
    "captured_at_local",
)
EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS = (
    *SETTLEMENT_OR_OUTCOME_DERIVED_FIELDS,
    *MARKET_DERIVED_FIELDS,
    *EVAL_IDENTITY_FIELDS,
)
PROHIBITED_FEATURE_FIELDS = frozenset(EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS)
APPROVED_MODEL_FEATURES = frozenset((*NUMERIC_FEATURES, *CATEGORICAL_FEATURES))
APPROVED_GUARDRAIL_FEATURES = frozenset(GUARDRAIL_FEATURES)
SNAPSHOT_KEY_FIELDS = ("market_id", "target_date", "snapshot_id")
REPAIR_EXTRA_FIELDS = (
    "item224_active_timesplit_logistic_raw_probability",
    "item224_active_timesplit_guardrail",
    "item224_active_timesplit_raw_partition_method",
    "item224_active_timesplit_final_partition_method",
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
    "claim_lane": "quarantined_label_leak_repair",
    "counts_toward_weather_model_promotion": "false",
    "quote_risk_eligible": "false",
    "quote_risk_gate_reason": "item224_v0_1_label_leak_quarantine",
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


def validate_feature_contract(
    *,
    numeric_features: tuple[str, ...] | list[str] | None = None,
    categorical_features: tuple[str, ...] | list[str] | None = None,
    guardrail_features: tuple[str, ...] | list[str] | None = None,
) -> dict[str, list[str]]:
    """Validate the inference-only model/guardrail allowlist and fail closed."""

    numeric = tuple(NUMERIC_FEATURES if numeric_features is None else numeric_features)
    categorical = tuple(CATEGORICAL_FEATURES if categorical_features is None else categorical_features)
    guardrail = tuple(GUARDRAIL_FEATURES if guardrail_features is None else guardrail_features)
    model = (*numeric, *categorical)
    issues = []

    duplicates = sorted(field for field, count in Counter(model).items() if count > 1)
    if duplicates:
        issues.append(f"duplicate model fields: {', '.join(duplicates)}")

    prohibited_model = sorted({
        field
        for field in model
        if field in PROHIBITED_FEATURE_FIELDS
        or "settlement" in field.strip().lower()
        or "outcome" in field.strip().lower()
    })
    prohibited_guardrail = sorted({
        field
        for field in guardrail
        if field in PROHIBITED_FEATURE_FIELDS
        or "settlement" in field.strip().lower()
        or "outcome" in field.strip().lower()
    })
    if prohibited_model:
        issues.append(f"prohibited model fields: {', '.join(prohibited_model)}")
    if prohibited_guardrail:
        issues.append(f"prohibited guardrail fields: {', '.join(prohibited_guardrail)}")

    unexpected_model = sorted(set(model) - APPROVED_MODEL_FEATURES)
    unexpected_guardrail = sorted(set(guardrail) - APPROVED_GUARDRAIL_FEATURES)
    if unexpected_model:
        issues.append(f"unapproved model fields: {', '.join(unexpected_model)}")
    if unexpected_guardrail:
        issues.append(f"unapproved guardrail fields: {', '.join(unexpected_guardrail)}")

    missing_exclusions = sorted(
        set(SETTLEMENT_OR_OUTCOME_DERIVED_FIELDS)
        - set(EXCLUDED_LABEL_MARKET_OR_IDENTITY_FIELDS)
    )
    if missing_exclusions:
        issues.append(
            "settlement/outcome-derived fields missing from explicit exclusions: "
            + ", ".join(missing_exclusions)
        )
    if issues:
        raise ValueError("Item224 fail-closed feature contract violation: " + "; ".join(issues))
    return {
        "numeric_features": list(numeric),
        "categorical_features": list(categorical),
        "guardrail_features": list(guardrail),
    }


def read_rows(path: str | Path) -> tuple[list[str], list[dict[str, Any]]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_rows(path: str | Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> Path:
    if rows:
        validate_probability_partitions(rows)
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
    contract = validate_feature_contract()
    features = {
        "active_route_probability": finite_float(row.get("probability")),
        "current_probability": finite_float(row.get("current_probability")),
        "bin_value": finite_float(row.get("bin_value")),
        "cutoff_hour": finite_float(row.get("cutoff_hour")),
    }
    for field in CATEGORICAL_FEATURES:
        features[field] = str(row.get(field) or "")
    expected = set(contract["numeric_features"] + contract["categorical_features"])
    if set(features) != expected or set(features) & PROHIBITED_FEATURE_FIELDS:
        raise ValueError("Item224 row feature extraction violated the fail-closed feature contract")
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


def snapshot_key(row: dict[str, Any]) -> tuple[str, ...]:
    key = tuple(str(row.get(field) or "").strip() for field in SNAPSHOT_KEY_FIELDS)
    if not all(key):
        missing = [field for field, value in zip(SNAPSHOT_KEY_FIELDS, key) if not value]
        raise ValueError(
            "Item224 probability partition is missing snapshot key field(s): "
            + ", ".join(missing)
        )
    return key


def _normalized_partition(values: list[Any]) -> list[float] | None:
    weights = []
    for value in values:
        try:
            weight = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(weight) or weight < 0.0:
            return None
        weights.append(weight)
    try:
        total = math.fsum(weights)
    except OverflowError:
        return None
    if not math.isfinite(total) or total <= 0.0:
        return None
    normalized = [weight / total for weight in weights]
    normalized[-1] += 1.0 - math.fsum(normalized)
    return normalized


def normalize_snapshot_probabilities(
    rows: list[dict[str, Any]],
    probabilities: list[Any],
) -> tuple[list[float], list[str], dict[str, Any]]:
    """Normalize mutually exclusive bands, falling back to current then uniform."""

    if len(rows) != len(probabilities):
        raise ValueError("probability rows and values differ")
    grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
    seen_bands: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for index, row in enumerate(rows):
        key = snapshot_key(row)
        band_key = str(row.get("band_key") or "").strip()
        if not band_key:
            raise ValueError("Item224 probability partition is missing band_key")
        if band_key in seen_bands[key]:
            raise ValueError(
                "Item224 probability partition has duplicate band_key "
                f"{band_key!r} for snapshot {key!r}"
            )
        seen_bands[key].add(band_key)
        grouped[key].append(index)

    normalized = [0.0] * len(rows)
    methods = [""] * len(rows)
    method_counts: Counter[str] = Counter()
    for indexes in grouped.values():
        partition = _normalized_partition([probabilities[index] for index in indexes])
        method = "model_partition_normalized"
        if partition is None:
            partition = _normalized_partition([
                rows[index].get("current_probability") for index in indexes
            ])
            method = "current_partition_fallback"
        if partition is None:
            partition = [1.0 / len(indexes)] * len(indexes)
            partition[-1] += 1.0 - math.fsum(partition)
            method = "uniform_partition_fallback"
        method_counts[method] += 1
        for index, probability in zip(indexes, partition):
            normalized[index] = probability
            methods[index] = method

    partition_sums = [math.fsum(normalized[index] for index in indexes) for indexes in grouped.values()]
    return normalized, methods, {
        "snapshot_partitions": len(grouped),
        "normalization_method_counts": dict(sorted(method_counts.items())),
        "max_abs_partition_sum_error": max(
            (abs(total - 1.0) for total in partition_sums),
            default=0.0,
        ),
    }


def validate_probability_partitions(
    rows: list[dict[str, Any]],
    *,
    probability_field: str = "probability",
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[snapshot_key(row)].append(row)
    errors = []
    for key, group_rows in grouped.items():
        values = []
        bands = set()
        for row in group_rows:
            band_key = str(row.get("band_key") or "").strip()
            if not band_key or band_key in bands:
                errors.append(f"snapshot {key!r} has missing or duplicate band_key {band_key!r}")
                continue
            bands.add(band_key)
            try:
                value = float(row.get(probability_field))
            except (TypeError, ValueError):
                value = math.nan
            if not math.isfinite(value) or value < 0.0 or value > 1.0:
                errors.append(
                    f"snapshot {key!r} has invalid {probability_field}={row.get(probability_field)!r}"
                )
            values.append(value)
        try:
            total = math.fsum(values)
        except OverflowError:
            total = math.inf
        if not math.isfinite(total) or abs(total - 1.0) > tolerance:
            errors.append(
                f"snapshot {key!r} {probability_field} partition sums to {total!r}, expected 1"
            )
    if errors:
        raise ValueError("Item224 probability partition validation failed: " + "; ".join(errors))
    return {
        "snapshot_partitions": len(grouped),
        "max_abs_partition_sum_error": max(
            (
                abs(
                    math.fsum(float(row.get(probability_field)) for row in group_rows)
                    - 1.0
                )
                for group_rows in grouped.values()
            ),
            default=0.0,
        ),
    }


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

    validate_feature_contract()
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
        ], remainder="drop")),
        (
            "model",
            LogisticRegression(max_iter=1000, C=MODEL_C, class_weight="balanced"),
        ),
    ])
    model.fit(train_frame, labels)
    return [clamp_probability(probability) for probability in model.predict_proba(eval_frame)[:, 1]]


def repaired_probability(
    row: dict[str, Any],
    raw_probability: float,
) -> tuple[float, list[str]]:
    validate_feature_contract()
    current = clamp_probability(row.get("current_probability"))
    probability = clamp_probability(raw_probability)
    guardrails = []
    if current <= HIGH_CONFIDENCE_LOW or current >= HIGH_CONFIDENCE_HIGH:
        probability = current
        guardrails.append("preserve_high_confidence_current_v0_1")
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
    validate_feature_contract()
    normalized_raw, raw_partition_methods, raw_partition_summary = normalize_snapshot_probabilities(
        eval_rows,
        raw_probabilities,
    )
    repaired_probabilities = []
    row_guardrails = []
    for row, raw_probability in zip(eval_rows, normalized_raw):
        final_probability, guardrails = repaired_probability(row, raw_probability)
        repaired_probabilities.append(final_probability)
        row_guardrails.append(guardrails)
    normalized_final, final_partition_methods, final_partition_summary = normalize_snapshot_probabilities(
        eval_rows,
        repaired_probabilities,
    )

    output = []
    guardrail_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for (
        row,
        raw_probability,
        final_probability,
        guardrails,
        raw_partition_method,
        final_partition_method,
    ) in zip(
        eval_rows,
        normalized_raw,
        normalized_final,
        row_guardrails,
        raw_partition_methods,
        final_partition_methods,
    ):
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
            "item224_active_timesplit_raw_partition_method": raw_partition_method,
            "item224_active_timesplit_final_partition_method": final_partition_method,
            "active_timesplit_training_window": ",".join(training_dates),
            "active_timesplit_eval_window": ",".join(eval_dates),
            "active_timesplit_model": MODEL_LABEL,
            "active_timesplit_source_variant_id": source_id,
        })
        output.append(item)
    validate_probability_partitions(output)
    validate_probability_partitions(
        output,
        probability_field="item224_active_timesplit_logistic_raw_probability",
    )
    return output, {
        "guardrail_counts": dict(sorted(guardrail_counts.items())),
        "active_source_lineage_counts": dict(sorted(source_counts.items())),
        "raw_partition_normalization": raw_partition_summary,
        "final_partition_normalization": final_partition_summary,
    }


def brier(probability: Any, outcome: Any) -> float:
    return (clamp_probability(probability) - int(finite_float(outcome))) ** 2


def score_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0}
    validate_probability_partitions(rows)
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


def quarantined_contract(rows_out: str | Path) -> dict[str, Any]:
    return {
        "variant_id": VARIANT_ID,
        "variant_family": VARIANT_FAMILY,
        "lifecycle": "shadow",
        "track": "no_market",
        "roles": [
            "candidate",
            "no-market",
            "shadow-only",
            "label-leak-quarantined",
            "item224-active-timesplit-probe",
        ],
        "active_for_headline": False,
        "counts_toward_weather_model_promotion": False,
        "promotion_status": "blocked",
        "promotion_block_reason": "item224_v0_1_used_settlement/outcome-derived features",
        "artifact_required": False,
        "prediction_function": "weather.reporting.research.item224_active_timesplit_logistic_repair:build_payload",
        "prediction_mode": "band_binary",
        "export_family": VARIANT_FAMILY,
        "default_export_path": str(rows_out).replace("\\", "/"),
        "postprocess_config_hash": VARIANT_ID,
        "live_runtime": "active_timesplit_logistic_repair",
        "roadmap_items": [224],
        "notes": (
            "Quarantined 2026-07-11: historical v0.1 evidence used settlement_distance_bucket "
            "directly and through feature_missingness_hash, and its guardrail read settlement "
            "distance. A new variant and clean rerun are required before promotion."
        ),
    }


def active_contract(rows_out: str | Path) -> dict[str, Any]:
    """Compatibility alias; Item224 v0.1 now emits a quarantined shadow contract."""

    return quarantined_contract(rows_out)


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
    feature_contract = validate_feature_contract()
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
    contract = quarantined_contract(rows_path)
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
        "status": "QUARANTINED_RETRAIN_AND_REVALIDATION_REQUIRED",
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
            **feature_contract,
            "contract_validation": "fail_closed_allowlist",
            "settlement_or_outcome_derived_fields": list(
                SETTLEMENT_OR_OUTCOME_DERIVED_FIELDS
            ),
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
        },
        "probability_partition_normalization": {
            "group_fields": list(SNAPSHOT_KEY_FIELDS),
            "raw": repair_summary["raw_partition_normalization"],
            "final": repair_summary["final_partition_normalization"],
            "fallback_order": ["current_probability_partition", "uniform_partition"],
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
