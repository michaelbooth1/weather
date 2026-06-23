"""Maker model-version shadow bakeoff helpers.

The live maker run keeps using the served quote tape. This module expands the
same policy inputs through a small, frozen model-variant basket and writes a
separate counterfactual quote-intent tape for analysis.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.mm_policy import (
    clamp_probability,
    decide_quote,
    maybe_float,
    policy_hash,
    utc_now,
)


SCHEMA_VERSION = "mm_model_variant_bakeoff_v0.1"
DEFAULT_BASKET_ID = "maker_default_v0"

DEFAULT_VARIANT_SPECS = [
    {
        "model_variant_id": "served_current",
        "model_variant_family": "served_current",
        "model_variant_role": "served",
        "probability_source": "served_fair_probability",
        "uses_market_features": False,
        "counts_toward_model_promotion": True,
    },
    {
        "model_variant_id": "current_high_trust_retrain",
        "model_variant_family": "current_high_trust",
        "model_variant_role": "shadow",
        "probability_source": "column",
        "probability_columns": [
            "current_high_trust_fair_probability",
            "current_high_retrain_probability",
        ],
        "uses_market_features": False,
        "counts_toward_model_promotion": True,
    },
    {
        "model_variant_id": "dynamic_source_freshness",
        "model_variant_family": "dynamic_source_freshness",
        "model_variant_role": "shadow",
        "probability_source": "column",
        "probability_columns": [
            "dynamic_source_freshness_probability",
            "dynamic_source_fair_probability",
            "source_state_probability",
        ],
        "uses_market_features": False,
        "counts_toward_model_promotion": True,
    },
    {
        "model_variant_id": "conservative_no_market_baseline",
        "model_variant_family": "conservative_no_market",
        "model_variant_role": "control",
        "probability_source": "market_mid",
        "uses_market_features": False,
        "counts_toward_model_promotion": False,
    },
    {
        "model_variant_id": "clob_overlay_risk_only",
        "model_variant_family": "clob_overlay",
        "model_variant_role": "shadow",
        "probability_source": "derived_clob_overlay",
        "uses_market_features": True,
        "counts_toward_model_promotion": False,
    },
]


def split_tokens(value):
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _fmt_band_value(value):
    number = maybe_float(value)
    if number is None:
        return str(value or "")
    return f"{number:.1f}"


def band_key(row):
    kind, value, value_hi = snapshot_band_key(row)
    if kind == "eq" and value_hi not in (None, ""):
        return f"eq:{_fmt_band_value(value)}-{_fmt_band_value(value_hi)}"
    return f"{kind}:{_fmt_band_value(value)}"


def row_key(row, target_date=None):
    return (
        str(row.get("market_id") or ""),
        str(row.get("target_date") or target_date or ""),
        str(row.get("snapshot_id") or ""),
        str(row.get("band_key") or band_key(row)),
    )


def _runtime_identity_text(runtime_identity):
    identity = (runtime_identity or {}).get("current_identity") or runtime_identity or {}
    return json.dumps(identity, sort_keys=True, default=str)


def _probability_from_spec(row, spec, config):
    source = spec.get("probability_source")
    served = clamp_probability(row.get("fair_probability") or row.get("model_probability") or row.get("candidate_p"))
    market_mid = clamp_probability(row.get("market_mid") or row.get("clob_midpoint") or row.get("market_yes"))
    if source == "served_fair_probability":
        return served, "served_fair_probability"
    if source == "market_mid":
        return market_mid, "market_mid_no_edge_control"
    if source == "derived_clob_overlay":
        if served is None or market_mid is None:
            return None, "missing_served_or_market_mid"
        weight = maybe_float(config.get("early_hour_guardrail_market_weight"))
        if weight is None:
            weight = 0.35
        weight = max(0.0, min(1.0, float(weight)))
        return (1.0 - weight) * served + weight * market_mid, f"derived_clob_overlay_weight={weight}"
    if source == "column":
        for column in spec.get("probability_columns") or []:
            value = clamp_probability(row.get(column))
            if value is not None:
                return value, column
        return None, "missing_probability_column"
    return None, f"unsupported_probability_source:{source}"


def _variant_specs(config):
    selected = set(split_tokens(config.get("maker_model_variant_ids")))
    specs = [dict(row) for row in DEFAULT_VARIANT_SPECS]
    if selected:
        specs = [row for row in specs if row.get("model_variant_id") in selected]
    return specs


def load_external_variant_index(paths, *, target_date, market_ids=None, variant_ids=None, max_rows=250000):
    market_ids = set(market_ids or [])
    variant_ids = set(variant_ids or [])
    index = defaultdict(list)
    diagnostics = []
    loaded_rows = 0
    for raw_path in paths:
        path = Path(raw_path)
        diag = {"path": str(path), "exists": path.exists(), "loaded_rows": 0, "status": "PASS"}
        if not path.exists():
            diag["status"] = "MISSING"
            diagnostics.append(diag)
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if str(row.get("target_date") or "") != str(target_date):
                    continue
                if market_ids and str(row.get("market_id") or "") not in market_ids:
                    continue
                if variant_ids and str(row.get("variant_id") or "") not in variant_ids:
                    continue
                probability = clamp_probability(row.get("probability") or row.get("variant_probability"))
                if probability is None:
                    continue
                index[row_key(row, target_date)].append(row)
                loaded_rows += 1
                diag["loaded_rows"] += 1
                if loaded_rows >= int(max_rows):
                    diag["status"] = "TRUNCATED"
                    diag["reason"] = f"stopped after {max_rows} external model-variant rows"
                    break
        diagnostics.append(diag)
        if loaded_rows >= int(max_rows):
            break
    return index, diagnostics


def _external_variant_row(base_row, variant_row, basket_id, basket_size, runtime_identity, now):
    probability = clamp_probability(variant_row.get("probability") or variant_row.get("variant_probability"))
    if probability is None:
        return None
    variant_id = variant_row.get("variant_id") or "external_variant"
    out = dict(base_row)
    out.update({
        "fair_probability": probability,
        "model_probability": probability,
        "model_version": variant_id,
        "served_model_version": base_row.get("model_version") or "",
        "served_fair_probability": clamp_probability(
            base_row.get("fair_probability") or base_row.get("model_probability") or base_row.get("candidate_p")
        ),
        "model_variant_id": variant_id,
        "model_variant_family": variant_row.get("variant_family") or "external_variant",
        "model_variant_role": "shadow",
        "model_variant_basket_id": basket_id,
        "model_variant_basket_size": basket_size,
        "model_variant_probability_source": variant_row.get("source_path") or "external_variant_row",
        "model_variant_prediction_at_utc": (
            variant_row.get("prediction_at_utc")
            or variant_row.get("captured_at_utc")
            or variant_row.get("captured_at_local")
            or now.isoformat()
        ),
        "model_variant_artifact_path": variant_row.get("artifact_path") or "",
        "model_variant_artifact_hash": variant_row.get("artifact_hash") or "",
        "model_variant_postprocess_config_hash": variant_row.get("postprocess_config_hash") or "",
        "model_variant_feature_schema": variant_row.get("feature_schema_version") or "",
        "model_variant_runtime_identity": _runtime_identity_text(runtime_identity),
        "model_variant_counterfactual": True,
    })
    return out


def materialize_model_variant_inputs(policy_inputs, config, *, target_date, runtime_identity=None, now=None):
    now = utc_now(now)
    config = config or {}
    basket_id = str(config.get("maker_model_variant_basket_id") or DEFAULT_BASKET_ID)
    specs = _variant_specs(config)
    requested_external_ids = set(split_tokens(config.get("maker_model_variant_ids")))
    external_paths = split_tokens(config.get("maker_model_variant_paths"))
    market_ids = {row.get("market_id") for row in policy_inputs if row.get("market_id")}
    external_index, external_diagnostics = load_external_variant_index(
        external_paths,
        target_date=target_date,
        market_ids=market_ids,
        variant_ids=requested_external_ids,
        max_rows=int(float(config.get("maker_model_variant_max_external_rows") or 250000)),
    ) if external_paths else ({}, [])
    external_variant_ids = {
        str(row.get("variant_id"))
        for rows in external_index.values()
        for row in rows
        if row.get("variant_id")
    }
    basket_size = len(specs) + len(external_variant_ids)
    runtime_text = _runtime_identity_text(runtime_identity)
    materialized = []
    skipped = Counter()
    emitted = Counter()
    for base_row in policy_inputs:
        seen_for_base = set()
        for spec in specs:
            variant_id = spec["model_variant_id"]
            probability, source = _probability_from_spec(base_row, spec, config)
            if probability is None:
                skipped[(variant_id, source)] += 1
                continue
            served = clamp_probability(base_row.get("fair_probability") or base_row.get("model_probability") or base_row.get("candidate_p"))
            out = dict(base_row)
            out.update({
                "fair_probability": probability,
                "model_probability": probability,
                "model_version": base_row.get("model_version") if variant_id == "served_current" else variant_id,
                "served_model_version": base_row.get("model_version") or "",
                "served_fair_probability": served,
                "model_variant_id": variant_id,
                "model_variant_family": spec["model_variant_family"],
                "model_variant_role": spec["model_variant_role"],
                "model_variant_basket_id": basket_id,
                "model_variant_basket_size": basket_size,
                "model_variant_probability_source": source,
                "model_variant_prediction_at_utc": base_row.get("captured_at_utc") or now.isoformat(),
                "model_variant_artifact_path": spec.get("artifact_path") or "",
                "model_variant_artifact_hash": spec.get("artifact_hash") or "",
                "model_variant_postprocess_config_hash": spec.get("postprocess_config_hash") or "",
                "model_variant_feature_schema": spec.get("feature_schema_version") or "",
                "model_variant_runtime_identity": runtime_text,
                "model_variant_counterfactual": variant_id != "served_current",
            })
            materialized.append(out)
            emitted[variant_id] += 1
            seen_for_base.add(variant_id)
        for variant_row in external_index.get(row_key(base_row, target_date), []):
            variant_id = variant_row.get("variant_id") or "external_variant"
            if variant_id in seen_for_base:
                continue
            out = _external_variant_row(base_row, variant_row, basket_id, basket_size, runtime_identity, now)
            if out:
                materialized.append(out)
                emitted[variant_id] += 1
                seen_for_base.add(variant_id)
    skipped_rows = [
        {
            "model_variant_id": variant_id,
            "reason": reason,
            "input_row_count": count,
        }
        for (variant_id, reason), count in sorted(skipped.items())
    ]
    basket = {
        "schema_version": SCHEMA_VERSION,
        "basket_id": basket_id,
        "frozen": True,
        "pre_registered_variant_ids": [row["model_variant_id"] for row in specs] + sorted(external_variant_ids),
        "default_variant_specs": specs,
        "external_variant_paths": external_paths,
        "external_variant_diagnostics": external_diagnostics,
        "base_input_rows": len(policy_inputs),
        "materialized_input_rows": len(materialized),
        "emitted_variant_ids": sorted(emitted),
        "emitted_variant_counts": dict(sorted(emitted.items())),
        "skipped_variants": skipped_rows,
        "multiple_testing_family_size": max(1, len([variant for variant in emitted if variant != "served_current"])),
    }
    return materialized, basket


def build_model_variant_quote_rows(policy_inputs, config, *, target_date, runtime_identity=None, now=None):
    if not config.get("maker_model_variant_basket_enabled", True):
        return [], {
            "schema_version": SCHEMA_VERSION,
            "status": "DISABLED",
            "reason": "maker model-variant basket disabled",
        }
    variant_inputs, basket = materialize_model_variant_inputs(
        policy_inputs,
        config,
        target_date=target_date,
        runtime_identity=runtime_identity,
        now=now,
    )
    rows = [decide_quote(row, config=config, now=now) for row in variant_inputs]
    basket.update(score_model_variant_quote_rows(rows, config))
    basket["status"] = "PASS" if rows else "EMPTY"
    return rows, basket


def score_model_variant_quote_rows(rows, config=None):
    config = config or {}
    by_pair = defaultdict(list)
    for row in rows:
        by_pair[(row.get("model_variant_id") or "unknown", row.get("policy_hash") or policy_hash(config))].append(row)
    pair_rows = []
    for (variant_id, policy_id), group in sorted(by_pair.items()):
        quote_count = sum(1 for row in group if str(row.get("quote_permission")).lower() in {"1", "true", "yes"})
        edges = [maybe_float(row.get("edge")) for row in group]
        edges = [value for value in edges if value is not None]
        reasons = Counter(row.get("reason_code") or "unknown" for row in group)
        pair_rows.append({
            "model_variant_id": variant_id,
            "model_variant_family": group[0].get("model_variant_family") if group else "",
            "model_variant_role": group[0].get("model_variant_role") if group else "",
            "policy_id": policy_id,
            "row_count": len(group),
            "quote_permission_rows": quote_count,
            "quote_permission_rate": round(quote_count / len(group), 6) if group else 0.0,
            "mean_edge": round(sum(edges) / len(edges), 6) if edges else None,
            "mean_abs_edge": round(sum(abs(value) for value in edges) / len(edges), 6) if edges else None,
            "market_count": len({row.get("market_id") for row in group if row.get("market_id")}),
            "snapshot_count": len({row.get("snapshot_id") for row in group if row.get("snapshot_id")}),
            "reason_counts": dict(sorted(reasons.items())),
        })
    served_by_policy = {
        row["policy_id"]: row
        for row in pair_rows
        if row.get("model_variant_id") == "served_current"
    }
    for row in pair_rows:
        served = served_by_policy.get(row["policy_id"])
        row["delta_quote_permission_rate_vs_served_current"] = (
            round(row["quote_permission_rate"] - served["quote_permission_rate"], 6)
            if served and row.get("model_variant_id") != "served_current"
            else 0.0
        )
    return {
        "score_schema_version": SCHEMA_VERSION,
        "score_status": "SAMPLE_PENDING" if pair_rows else "NO_ROWS",
        "score_basis": "quote_intent_policy_counterfactual",
        "policy_pair_count": len(pair_rows),
        "model_variant_by_policy": pair_rows,
    }


def render_model_variant_report(payload):
    payload = payload or {}
    lines = [
        "# Maker Model-Variant Bakeoff",
        "",
        f"Schema: `{payload.get('schema_version') or SCHEMA_VERSION}`",
        f"Status: `{payload.get('status') or '-'}`",
        f"Basket: `{payload.get('basket_id') or '-'}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| Base input rows | {payload.get('base_input_rows', 0)} |",
        f"| Materialized variant input rows | {payload.get('materialized_input_rows', 0)} |",
        f"| Emitted variants | {', '.join(payload.get('emitted_variant_ids') or []) or '-'} |",
        f"| Multiple-testing family size | {payload.get('multiple_testing_family_size', 0)} |",
        "",
        "## By Variant And Policy",
        "",
        "| Variant | Family | Policy | Rows | Quote rows | Quote rate | Delta vs served | Mean edge | Mean abs edge |",
        "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("model_variant_by_policy") or []:
        lines.append(
            f"| {row.get('model_variant_id')} | {row.get('model_variant_family')} | "
            f"{row.get('policy_id')} | {row.get('row_count', 0)} | "
            f"{row.get('quote_permission_rows', 0)} | {row.get('quote_permission_rate', 0.0)} | "
            f"{row.get('delta_quote_permission_rate_vs_served_current', 0.0)} | "
            f"{row.get('mean_edge') if row.get('mean_edge') is not None else '-'} | "
            f"{row.get('mean_abs_edge') if row.get('mean_abs_edge') is not None else '-'} |"
        )
    if payload.get("skipped_variants"):
        lines.extend([
            "",
            "## Skipped Variants",
            "",
            "| Variant | Reason | Input rows |",
            "| :--- | :--- | ---: |",
        ])
        for row in payload.get("skipped_variants") or []:
            lines.append(
                f"| {row.get('model_variant_id')} | {row.get('reason')} | {row.get('input_row_count', 0)} |"
            )
    lines.extend([
        "",
        "## Promotion Boundary",
        "",
        "This report is descriptive quote-intent evidence. Promotion claims require clustered settlement/markout evidence from the next promotion gate.",
        "",
    ])
    return "\n".join(lines)
