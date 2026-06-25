"""Diagnostics and microstructure helpers for pooled candidate replay."""

from __future__ import annotations

import json
import math
import pickle
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

from weather.backtesting.replay_backtest import FIDELITY_FAITHFUL_L1
from weather.calibration.pooled_feature_model import (
    FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION,
    FEATURE_SUBSET_FORECAST_PROFILE,
    FEATURE_SUBSET_MARINE_WATER_CONTRAST,
)
from weather.calibration.pooled_candidate_scoring import (
    DEFAULT_MICROSTRUCTURE_VARIANT_OUT,
    MICROSTRUCTURE_SCHEMA_VERSION,
    MICROSTRUCTURE_TARGET_TAXONOMIES,
    _clamp_probability,
    _valid_probability,
    apply_microstructure_gate,
    artifact_hash_for_path,
    blocked_candidate_validation_gate,
    build_microstructure_gate,
    candidate_comparison,
    grouped_microstructure_comparison,
    microstructure_comparison,
    microstructure_shadow_variant_rows,
    payload_hash,
    write_microstructure_shadow_variants,
)
from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS, snapshot_band_key
from weather.market.market_registry import REGISTRY
from weather.paths import data_path
from weather.reporting.candidate_lifecycle.variant_registry import variant_contract_for_artifact
from weather.scoring.metrics import group_sort_key


DEFAULT_CASEBOOK = data_path() / "backtest" / "disagreement_casebook.json"
MICROSTRUCTURE_NUMERIC_FEATURES = [
    "candidate_p",
    "replayed_p",
    "recorded_p",
    "market_yes",
    "candidate_logit",
    "replayed_logit",
    "market_logit",
    "candidate_minus_market",
    "candidate_minus_replayed",
    "replayed_minus_market",
    "abs_candidate_minus_market",
    "candidate_cutoff_hour",
    *CLOB_MODEL_FEATURE_COLUMNS,
]
MICROSTRUCTURE_CATEGORICAL_FEATURES = [
    "market_id",
    "bin_type",
    "candidate_cutoff_hour_bucket",
]
POOLED_REPLAY_PREDICTION_FUNCTION = "weather.calibration.pooled_candidate_replay:run_pooled_candidate_replay"


def probability_logit(value, epsilon=1e-6):
    value = max(float(epsilon), min(1.0 - float(epsilon), float(value)))
    return math.log(value / (1.0 - value))


def cutoff_hour_bucket(value):
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return "na"
    if hour <= 8:
        return "07-08"
    if hour <= 13:
        return "09-13"
    if hour <= 16:
        return "14-16"
    return "17-20"


def _micro_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def microstructure_feature_record(row):
    """Build a no-outcome row for the CLOB shadow overlay."""
    candidate = _micro_float(row.get("candidate_p"))
    current = _micro_float(row.get("replayed_p"))
    recorded = _micro_float(row.get("recorded_p"))
    market = _micro_float(row.get("market_yes"))
    output = {
        "market_id": row.get("market_id") or "unknown",
        "bin_type": row.get("bin_type") or row.get("bin_kind") or "eq",
        "candidate_cutoff_hour": _micro_float(row.get("candidate_cutoff_hour")),
        "candidate_cutoff_hour_bucket": cutoff_hour_bucket(row.get("candidate_cutoff_hour")),
        "candidate_p": candidate,
        "replayed_p": current,
        "recorded_p": recorded,
        "market_yes": market,
        "candidate_logit": probability_logit(candidate) if candidate is not None else None,
        "replayed_logit": probability_logit(current) if current is not None else None,
        "market_logit": probability_logit(market) if market is not None else None,
        "candidate_minus_market": candidate - market if candidate is not None and market is not None else None,
        "candidate_minus_replayed": candidate - current if candidate is not None and current is not None else None,
        "replayed_minus_market": current - market if current is not None and market is not None else None,
        "abs_candidate_minus_market": abs(candidate - market) if candidate is not None and market is not None else None,
    }
    for column in CLOB_MODEL_FEATURE_COLUMNS:
        output[column] = _micro_float(row.get(column))
    return output


def microstructure_feature_frame(records, feature_names=None):
    frame = pd.DataFrame(records)
    for column in MICROSTRUCTURE_NUMERIC_FEATURES:
        if column not in frame:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in MICROSTRUCTURE_CATEGORICAL_FEATURES:
        if column not in frame:
            frame[column] = "unknown"
        frame[column] = frame[column].fillna("unknown").astype(str)
    features = pd.get_dummies(
        frame[MICROSTRUCTURE_NUMERIC_FEATURES + MICROSTRUCTURE_CATEGORICAL_FEATURES],
        columns=MICROSTRUCTURE_CATEGORICAL_FEATURES,
        dtype=float,
    )
    if feature_names is not None:
        features = features.reindex(columns=feature_names, fill_value=0.0)
    return features


def eligible_microstructure_rows(rows):
    output = []
    for idx, row in enumerate(rows):
        if not _valid_probability(row.get("candidate_p")):
            continue
        if not _valid_probability(row.get("replayed_p")):
            continue
        if not _valid_probability(row.get("market_yes")):
            continue
        if row.get("outcome") is None:
            continue
        if _micro_float(row.get("clob_feature_available")) != 1.0:
            continue
        copy = dict(row)
        copy["_micro_index"] = idx
        output.append(copy)
    return output


def train_microstructure_model(rows, feature_names=None):
    records = [microstructure_feature_record(row) for row in rows]
    frame = microstructure_feature_frame(records, feature_names=feature_names)
    feature_names = list(frame.columns)
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    x_train = imputer.fit_transform(frame)
    y_train = [int(row.get("outcome")) for row in rows]
    model = HistGradientBoostingClassifier(
        max_iter=70,
        max_leaf_nodes=15,
        learning_rate=0.05,
        l2_regularization=0.05,
        random_state=38,
    )
    model.fit(x_train, y_train)
    return {
        "model": model,
        "imputer": imputer,
        "feature_names": feature_names,
        "classes": [int(value) for value in model.classes_],
    }


def predict_microstructure_model(bundle, rows):
    if not rows:
        return []
    records = [microstructure_feature_record(row) for row in rows]
    frame = microstructure_feature_frame(records, feature_names=bundle["feature_names"])
    x_eval = bundle["imputer"].transform(frame)
    probabilities = bundle["model"].predict_proba(x_eval)
    classes = [int(value) for value in bundle["classes"]]
    if 1 not in classes:
        return [1.0 if classes and classes[0] == 1 else 0.0 for _ in rows]
    idx = classes.index(1)
    return [_clamp_probability(float(row[idx])) for row in probabilities]


def _micro_group_key(row):
    return row.get("target_date") or f"{row.get('market_id')}:{row.get('snapshot_id')}"


def out_of_fold_microstructure_predictions(rows, min_train_rows=500):
    """Score CLOB rows out of fold, grouped by target date to avoid same-day leakage."""
    for row in rows:
        row["micro_candidate_p"] = None
    eligible = eligible_microstructure_rows(rows)
    diagnostics = {
        "eligible_rows": len(eligible),
        "predicted_rows": 0,
        "fold_count": 0,
        "skipped_folds": [],
        "min_train_rows": int(min_train_rows),
    }
    grouped = defaultdict(list)
    for row in eligible:
        grouped[_micro_group_key(row)].append(row)
    if len(grouped) < 2:
        diagnostics["skipped_folds"].append({
            "group": "all",
            "reason": "fewer than two target-date groups with CLOB rows",
        })
        return diagnostics

    for group, eval_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        train_rows = [
            row
            for key, items in grouped.items()
            if key != group
            for row in items
        ]
        labels = {int(row.get("outcome")) for row in train_rows if row.get("outcome") is not None}
        if len(train_rows) < int(min_train_rows) or labels != {0, 1}:
            diagnostics["skipped_folds"].append({
                "group": group,
                "train_rows": len(train_rows),
                "reason": "insufficient rows or one-class training fold",
            })
            continue
        bundle = train_microstructure_model(train_rows)
        probabilities = predict_microstructure_model(bundle, eval_rows)
        diagnostics["fold_count"] += 1
        diagnostics["predicted_rows"] += len(probabilities)
        for eval_row, probability in zip(eval_rows, probabilities):
            rows[eval_row["_micro_index"]]["micro_candidate_p"] = probability
    return diagnostics


def final_microstructure_artifact(rows, metadata=None, min_train_rows=500):
    eligible = eligible_microstructure_rows(rows)
    labels = {int(row.get("outcome")) for row in eligible if row.get("outcome") is not None}
    if len(eligible) < int(min_train_rows) or labels != {0, 1}:
        return None
    bundle = train_microstructure_model(eligible)
    return {
        "schema_version": MICROSTRUCTURE_SCHEMA_VERSION,
        "trained_at": datetime.now().isoformat(),
        "family_unit": "F",
        "prediction_mode": "band_binary_microstructure_overlay",
        "objective": "out_of_fold_clob_overlay_brier",
        "gate": (metadata or {}).get("gate"),
        "feature_names": bundle["feature_names"],
        "numeric_features": MICROSTRUCTURE_NUMERIC_FEATURES,
        "categorical_features": MICROSTRUCTURE_CATEGORICAL_FEATURES,
        "classes": bundle["classes"],
        "train_rows": len(eligible),
        "model": bundle["model"],
        "imputer": bundle["imputer"],
        "metadata": metadata or {},
    }


def write_microstructure_artifact(path, artifact):
    if artifact is None or not path:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)
    return str(path)


def row_band_key_text(row):
    kind, value, value_hi = snapshot_band_key(row)
    if value is None:
        return f"{kind}:?"
    if value_hi is not None and value_hi != value:
        return f"{kind}:{value:g}-{value_hi:g}"
    return f"{kind}:{value:g}"


def load_casebook_index(path):
    path = Path(path)
    if not path.exists():
        return {}, {"path": str(path), "exists": False, "cases": 0, "refs": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    index = {}
    for case in payload.get("cases") or []:
        market_id = case.get("market_id")
        band_key = case.get("band_key_text") or case.get("band_key")
        if not market_id or not band_key:
            continue
        snapshot_ids = case.get("snapshot_ids") or [case.get("peak_snapshot_id")]
        for snapshot_id in snapshot_ids:
            if not snapshot_id:
                continue
            key = (market_id, str(snapshot_id), band_key)
            existing = index.get(key)
            if existing and (existing.get("peak_abs_edge") or 0.0) >= (case.get("peak_abs_edge") or 0.0):
                continue
            index[key] = {
                "case_id": case.get("case_id"),
                "taxonomy": case.get("taxonomy"),
                "model_result": case.get("model_result"),
                "slice_type": (
                    "known_edge_candidate"
                    if case.get("model_result") == "model_win"
                    else "model_losing_family"
                    if case.get("model_result") == "model_loss"
                    else "open_or_mixed"
                ),
                "peak_abs_edge": case.get("peak_abs_edge"),
            }
    return index, {"path": str(path), "exists": True, "cases": len(payload.get("cases") or []), "refs": len(index)}


def annotate_casebook_rows(rows, casebook_index):
    matched = 0
    for row in rows:
        key = (row.get("market_id"), str(row.get("snapshot_id")), row_band_key_text(row))
        case = casebook_index.get(key)
        if not case:
            row["casebook_taxonomy"] = None
            row["casebook_case_id"] = None
            row["casebook_result"] = None
            row["casebook_slice_type"] = None
            continue
        matched += 1
        row["casebook_taxonomy"] = case.get("taxonomy")
        row["casebook_case_id"] = case.get("case_id")
        row["casebook_result"] = case.get("model_result")
        row["casebook_slice_type"] = case.get("slice_type")
    return matched


def microstructure_shadow_report(
    rows,
    casebook_path=None,
    artifact_path=None,
    min_train_rows=500,
    variant_out_path=DEFAULT_MICROSTRUCTURE_VARIANT_OUT,
    candidate_artifact_hash="",
    min_free_bytes=0,
):
    casebook_index, casebook_diagnostics = load_casebook_index(casebook_path or DEFAULT_CASEBOOK)
    matched = annotate_casebook_rows(rows, casebook_index)
    diagnostics = out_of_fold_microstructure_predictions(rows, min_train_rows=min_train_rows)
    aggregate = microstructure_comparison(rows)
    by_market = grouped_microstructure_comparison(rows, "market_id")
    by_hour = grouped_microstructure_comparison(rows, "candidate_cutoff_hour")
    by_taxonomy = grouped_microstructure_comparison(rows, "casebook_taxonomy")
    target_slices = [
        row for row in by_taxonomy
        if row.get("group") in MICROSTRUCTURE_TARGET_TAXONOMIES
    ]
    gate = build_microstructure_gate(target_slices)
    gate_counts = apply_microstructure_gate(rows, gate)
    gated = {
        "gate": gate,
        "counts": gate_counts,
        "aggregate": microstructure_comparison(rows, probability_field="micro_gated_candidate_p"),
        "by_market": grouped_microstructure_comparison(rows, "market_id", probability_field="micro_gated_candidate_p"),
        "by_hour": grouped_microstructure_comparison(rows, "candidate_cutoff_hour", probability_field="micro_gated_candidate_p"),
        "by_taxonomy": grouped_microstructure_comparison(rows, "casebook_taxonomy", probability_field="micro_gated_candidate_p"),
    }
    gated["target_slices"] = [
        row for row in gated["by_taxonomy"]
        if row.get("group") in MICROSTRUCTURE_TARGET_TAXONOMIES
    ]
    artifact = final_microstructure_artifact(
        rows,
        metadata={
            "casebook": casebook_diagnostics,
            "aggregate": aggregate,
            "target_slices": target_slices,
            "gate": gate,
            "gated": {
                "aggregate": gated["aggregate"],
                "target_slices": gated["target_slices"],
                "counts": gate_counts,
            },
            "oof": diagnostics,
        },
        min_train_rows=min_train_rows,
    )
    written_artifact = write_microstructure_artifact(artifact_path, artifact)
    microstructure_artifact_hash = (
        artifact_hash_for_path(written_artifact)
        if written_artifact
        else payload_hash({
            "schema_version": MICROSTRUCTURE_SCHEMA_VERSION,
            "oof": diagnostics,
            "gate": gate,
        })
    )
    variant_rows = microstructure_shadow_variant_rows(
        rows,
        candidate_artifact_hash=candidate_artifact_hash,
        microstructure_artifact_hash=microstructure_artifact_hash,
    )
    variant_path = write_microstructure_shadow_variants(
        variant_out_path,
        variant_rows,
        min_free_bytes=min_free_bytes,
    )
    diagnostics["casebook_matched_rows"] = matched
    diagnostics["casebook"] = casebook_diagnostics
    diagnostics["artifact_path"] = written_artifact
    diagnostics["artifact_hash"] = microstructure_artifact_hash
    diagnostics["artifact_train_rows"] = (artifact or {}).get("train_rows")
    diagnostics["gated_overlay_rows"] = gate_counts["overlay_rows"]
    diagnostics["gated_base_rows"] = gate_counts["base_rows"]
    diagnostics["shadow_variant_rows"] = len(variant_rows)
    diagnostics["shadow_variant_path"] = variant_path
    diagnostics["claim_lanes"] = {
        "weather_only_core_model": {
            "rows": sum(
                1 for row in variant_rows
                if row.get("claim_lane") == "weather_only_core_model"
            ),
            "counts_toward_weather_model_promotion": True,
        },
        "market_informed_quote_risk": {
            "rows": sum(
                1 for row in variant_rows
                if row.get("claim_lane") == "market_informed_quote_risk"
            ),
            "quote_risk_eligible_rows": sum(
                1 for row in variant_rows
                if row.get("quote_risk_eligible")
            ),
            "counts_toward_weather_model_promotion": False,
        },
    }
    return {
        "schema_version": MICROSTRUCTURE_SCHEMA_VERSION,
        "enabled": True,
        "target_taxonomies": list(MICROSTRUCTURE_TARGET_TAXONOMIES),
        "gate": gate,
        "diagnostics": diagnostics,
        "aggregate": aggregate,
        "gated": gated,
        "by_market": by_market,
        "by_hour": by_hour,
        "by_taxonomy": by_taxonomy,
        "target_slices": target_slices,
        "shadow_variants": {
            "path": variant_path,
            "rows": len(variant_rows),
            "variant_ids": sorted({row["variant_id"] for row in variant_rows}),
            "claim_lanes": sorted({row.get("claim_lane") for row in variant_rows if row.get("claim_lane")}),
        },
    }


def market_verdict(comp, day_count, trust, current_tol, market_tol, min_days, min_trust, blocked_validation=None):
    if not comp:
        return "BLOCK", ["no candidate rows scored"]
    reasons = []
    delta_current = comp.get("delta_vs_current")
    if delta_current is None or delta_current > current_tol:
        reasons.append(
            f"candidate regresses current by {delta_current:+.4f} > {current_tol:.4f}"
            if delta_current is not None else
            "missing candidate-vs-current delta"
        )
    if blocked_validation and not blocked_validation.get("passed"):
        detail = "; ".join(blocked_validation.get("reasons") or []) or "blocked validation failed"
        reasons.append(f"blocked validation failed: {detail}")
    if reasons:
        return "BLOCK", reasons

    shadow = []
    if delta_current is not None and delta_current >= 0:
        shadow.append("not proven better than current replay")
    if day_count < min_days:
        shadow.append(f"{day_count} settled day(s) < {min_days}")
    candidate_brier = comp.get("candidate_brier")
    market_brier = comp.get("market_brier")
    if candidate_brier is None or market_brier is None or candidate_brier > market_brier + market_tol:
        shadow.append("not proven better than market on pinned rows")
    trust_score = (trust or {}).get("trust_score")
    if trust_score is None or trust_score < min_trust:
        shadow.append(f"trust {trust_score if trust_score is not None else '-'} < {min_trust}")
    if shadow:
        return "SHADOW", shadow
    return "PASS", ["beats current replay and clears market/trust gates"]


def _per_market(rows, trust_by_market, args):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("market_id")].append(row)
    output = []
    for market_id in sorted(grouped):
        market_rows = grouped[market_id]
        comp = candidate_comparison(market_rows)
        day_count = len({
            row.get("target_date")
            for row in market_rows
            if row.get("target_date") and _valid_probability(row.get("candidate_p"))
        })
        snapshot_count = len({
            row.get("snapshot_id")
            for row in market_rows
            if row.get("snapshot_id") and _valid_probability(row.get("candidate_p"))
        })
        trust = trust_by_market.get(market_id) or {}
        blocked_validation = blocked_candidate_validation_gate(
            market_rows,
            current_tol=args.current_tol,
            market_tol=args.market_tol,
            min_days=args.min_days,
        )
        verdict, reasons = market_verdict(
            comp,
            day_count,
            trust,
            args.current_tol,
            args.market_tol,
            args.min_days,
            args.min_trust,
            blocked_validation=blocked_validation,
        )
        spec = REGISTRY.get(market_id)
        output.append({
            "market_id": market_id,
            "city": spec.city_label if spec else market_id,
            "days": day_count,
            "snapshots": snapshot_count,
            "rows": (comp or {}).get("n", 0),
            "comparison": comp,
            "trust": trust,
            "verdict": verdict,
            "reason": "; ".join(reasons),
            "blocked_validation": blocked_validation,
        })
    return output


def overall_verdict(market_rows, require_all_markets=False):
    blockers = [row for row in market_rows if row["verdict"] == "BLOCK"]
    passes = [row for row in market_rows if row["verdict"] == "PASS"]
    shadows = [row for row in market_rows if row["verdict"] == "SHADOW"]
    if require_all_markets and (blockers or shadows):
        return "BLOCK"
    if blockers and passes:
        return "PARTIAL_PASS"
    if blockers:
        return "BLOCK"
    if shadows and passes:
        return "PASS_WITH_SHADOWS"
    if shadows:
        return "SHADOW_ONLY"
    if passes:
        return "PASS"
    return "BLOCK"


def cutover_decision(verdict):
    if verdict == "PASS":
        return "CUTOVER_READY"
    if verdict in {"PARTIAL_PASS", "PASS_WITH_SHADOWS"}:
        return "PER_MARKET_ONLY"
    return "DO_NOT_CUT_OVER"


def replay_gate_status(replay_results, max_fidelity_l1=FIDELITY_FAITHFUL_L1, require_exact_identity=False):
    """Global replay safety gate for a candidate promotion run."""
    warnings = replay_results.get("corpus_warnings") or []
    fidelity = replay_results.get("fidelity") or {}
    same_n = fidelity.get("same_identity_n") or 0
    max_l1 = fidelity.get("same_identity_max_l1")

    corpus_ok = not warnings
    if corpus_ok:
        corpus_message = "PASS: all pinned tape/replay hashes matched"
    else:
        corpus_message = f"FAIL: {len(warnings)} corpus pin warning(s)"

    if same_n:
        fidelity_ok = max_l1 is not None and max_l1 <= max_fidelity_l1
        verdict = "PASS" if fidelity_ok else "FAIL"
        fidelity_message = (
            f"{verdict}: {same_n} exact-identity snapshot(s), "
            f"max L1 {max_l1:.5f} vs limit {max_fidelity_l1:.5f}"
        )
    elif require_exact_identity:
        fidelity_ok = False
        fidelity_message = "FAIL: no exact-identity snapshots in corpus"
    else:
        fidelity_ok = True
        fidelity_message = "WARN: no exact-identity snapshots yet; strict canary not required"

    return {
        "global_ok": bool(corpus_ok and fidelity_ok),
        "corpus_ok": bool(corpus_ok),
        "corpus_message": corpus_message,
        "corpus_warning_count": len(warnings),
        "fidelity_ok": bool(fidelity_ok),
        "fidelity_message": fidelity_message,
        "same_identity_n": same_n,
        "same_identity_max_l1": max_l1,
        "max_fidelity_l1": max_fidelity_l1,
        "require_exact_identity": bool(require_exact_identity),
    }


def _manifest_summary(manifest):
    summary = manifest.get("summary") or {}
    return {
        "path": manifest.get("_path"),
        "schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "as_of": manifest.get("as_of"),
        "market_day_count": summary.get("market_day_count"),
        "snapshot_count": summary.get("snapshot_count"),
        "band_row_count": summary.get("band_row_count"),
        "feature_quality_excluded_snapshot_count": summary.get("feature_quality_excluded_snapshot_count", 0),
        "feature_quality_excluded_band_row_count": summary.get("feature_quality_excluded_band_row_count", 0),
        "quality_grades": manifest.get("quality_grades"),
    }


def candidate_variant_defaults(artifact, *, variant_registry=None, artifact_path=None):
    contract = variant_contract_for_artifact(
        variant_registry,
        artifact_path,
        prediction_function=POOLED_REPLAY_PREDICTION_FUNCTION,
    ) if variant_registry and artifact_path else None
    if contract:
        return contract.get("variant_id"), contract.get("export_family") or contract.get("variant_family")
    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
    if artifact.get("feature_subset") == FEATURE_SUBSET_FORECAST_PROFILE:
        return "item134_forecast_profile_v0_1", "forecast_profile_calibration"
    if artifact.get("feature_subset") == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        return "item187_forecast_radiation_v0_1", "forecast_radiation_calibration"
    if artifact.get("feature_subset") == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        return "item191_marine_water_contrast_v0_1", "marine_water_contrast_calibration"
    if prediction_mode == "continuous_density_f":
        schema = artifact.get("schema_version") or "pooled_continuous_density_hgb_v0.1"
        return str(schema).replace(".", "_"), "pooled_continuous_density"
    return "pooled_f_candidate", "pooled_f_candidate"


def forecast_profile_guardrails(rows, min_rows=50, tolerance=0.003):
    by_market = defaultdict(list)
    for row in rows:
        if row.get("forecast_disagreement_bucket") != "high_disagreement":
            continue
        by_market[row.get("market_id") or "unknown"].append(row)
    output = []
    for market_id, market_rows in sorted(by_market.items()):
        comp = candidate_comparison(market_rows)
        if not comp:
            continue
        reasons = []
        if int(comp.get("n") or 0) < int(min_rows):
            reasons.append(f"high-disagreement rows {comp.get('n', 0)} < {int(min_rows)}")
        delta_current = comp.get("delta_vs_current")
        delta_market = comp.get("delta_vs_market")
        if delta_current is None or delta_current > float(tolerance):
            reasons.append("candidate not proven safe versus current on high-disagreement rows")
        if delta_market is None or delta_market > float(tolerance):
            reasons.append("candidate not proven safe versus market on high-disagreement rows")
        output.append({
            "market_id": market_id,
            "comparison": comp,
            "status": "pass" if not reasons else "blocked",
            "reasons": reasons,
        })
    return {
        "schema_version": "forecast_profile_guardrails_v0.1",
        "high_disagreement_min_rows": int(min_rows),
        "tolerance": float(tolerance),
        "rows": output,
        "blocked_markets": [row["market_id"] for row in output if row["status"] != "pass"],
    }


def sidecar_eligibility_summary_from_audit(
    audit_path,
    *,
    candidate_variant_id=None,
    candidate_variant_family=None,
):
    path = Path(audit_path) if audit_path else None
    base = {
        "schema_version": "candidate_replay_sidecar_eligibility_v0.1",
        "source_path": str(path) if path else None,
        "loaded": False,
        "candidate_variant_id": candidate_variant_id,
        "candidate_variant_family": candidate_variant_family,
        "primary_label_counts": {},
        "readiness_label_counts": {},
        "missing_artifact_counts": {},
        "non_reconstructable_gap_counts": {},
        "backfill_command_counts": {},
        "backfill_candidate_folder_count": 0,
        "active_day_sidecar_regression_count": 0,
        "feature_quality_quarantine": {},
        "promotion_exclusion_sample": [],
        "by_market": [],
    }
    if not path or not path.exists():
        base["status"] = "missing"
        return base
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base["status"] = "unreadable"
        base["error"] = f"{type(exc).__name__}: {exc}"
        return base

    snapshots = payload.get("snapshots") or {}
    sidecar = snapshots.get("sidecar_eligibility") or {}
    feature_quality = snapshots.get("feature_quality_quarantine") or sidecar.get("feature_quality_quarantine") or {}
    if not sidecar:
        base["status"] = "unavailable"
        return base

    base.update({
        "loaded": True,
        "status": "loaded",
        "snapshot_folder_count": snapshots.get("folder_count", 0),
        "primary_label_counts": sidecar.get("primary_label_counts") or {},
        "readiness_label_counts": sidecar.get("label_counts") or {},
        "missing_artifact_counts": sidecar.get("missing_artifact_counts") or {},
        "non_reconstructable_gap_counts": sidecar.get("non_reconstructable_gap_counts") or {},
        "backfill_command_counts": sidecar.get("backfill_command_counts") or {},
        "backfill_candidate_folder_count": sidecar.get("backfill_candidate_folder_count", 0),
        "active_day_sidecar_regression_count": sidecar.get("active_day_sidecar_regression_count", 0),
        "feature_quality_quarantine": feature_quality,
        "promotion_exclusion_sample": (sidecar.get("promotion_exclusion_sample") or [])[:10],
        "by_market": [
            {
                "market_id": row.get("market_id") or row.get("market") or row.get("city") or "unknown",
                "days": row.get("folders", row.get("days", 0)),
                "training_ready_days": row.get("training_ready_label_days", 0),
                "explanation_ready_days": row.get("explanation_ready_days", 0),
                "market_aware_ready_days": row.get("market_aware_ready_days", 0),
                "variant_ready_days": row.get("variant_ready_days", 0),
                "latest_target_date": row.get("latest_target_date"),
            }
            for row in snapshots.get("by_market") or []
        ],
    })
    return base


from weather.model.variant_prediction_runtime import (  # noqa: E402
    MICROSTRUCTURE_CATEGORICAL_FEATURES,
    MICROSTRUCTURE_NUMERIC_FEATURES,
    _micro_float,
    cutoff_hour_bucket,
    microstructure_feature_frame,
    microstructure_feature_record,
    probability_logit,
)
