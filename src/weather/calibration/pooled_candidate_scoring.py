"""Row-level scoring and shadow-policy helpers for pooled candidate replay."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import pickle
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from weather.paths import data_path

from weather.artifacts import sha256_file
from weather.calibration.blocked_validation import blocked_validation_audit
from weather.reporting.artifact_disk_budget import (
    DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES,
    DEFAULT_ROW_EXPORT_BYTES_PER_ROW,
    ensure_row_export_disk_headroom,
)
from weather.scoring.metrics import (
    expected_calibration_error,
    group_sort_key,
    score_rows,
    winner_band_catchup,
)
from weather.schema_registry import schema_version

DEFAULT_CANDIDATE_VARIANT_OUT = data_path() / "backtest" / "pooled_candidate_shadow_variants.csv"
DEFAULT_MICROSTRUCTURE_VARIANT_OUT = data_path() / "backtest" / "clob_overlay_shadow_variants.csv"
DEFAULT_BRIDGE_VARIANT_OUT = data_path() / "backtest" / "conservative_bridge_shadow_variants.csv"
DEFAULT_SOURCE_STATE_ABLATION_VARIANT_OUT = data_path() / "backtest" / "source_state_ablation_shadow_variants.csv"
DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES = DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES
DEFAULT_VARIANT_EXPORT_BYTES_PER_ROW = DEFAULT_ROW_EXPORT_BYTES_PER_ROW
MICROSTRUCTURE_SCHEMA_VERSION = "clob_microstructure_overlay_v0.2"
MICROSTRUCTURE_GATE_SCHEMA_VERSION = "clob_microstructure_taxonomy_gate_v0.1"
CONSERVATIVE_BRIDGE_SCHEMA_VERSION = "conservative_bridge_policy_v0.1"
SOURCE_STATE_ABLATION_SCHEMA_VERSION = "source_state_ablation_v0.1"
SOURCE_STATE_ABLATION_FAMILY = "source_state_ablation"
SOURCE_STATE_ABLATION_ALL_FRESH_MAX_REGRESSION = 0.0
SOURCE_STATE_ABLATION_DEGRADED_MAX_REGRESSION = 0.0
ATTRIBUTION_SCHEMA_VERSION = schema_version("multi_variant_shadow_attribution")
ATTRIBUTION_FEATURE_FIELDS = [
    "candidate_cutoff_hour",
    "candidate_cutoff_regime",
    "source_freshness_state",
    "settlement_distance_bucket",
    "forecast_source_count",
    "forecast_disagreement",
    "forecast_gap",
    "forecast_source_count_bucket",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "clob_feature_available",
    "clob_midpoint",
    "clob_spread",
    "clob_liquidity_score",
    "casebook_taxonomy",
]
MICROSTRUCTURE_TARGET_TAXONOMIES = (
    "market_lead",
    "book_liquidity_artifact",
)
CONSERVATIVE_BRIDGE_ALPHA_BY_MARKET = {
    "atlanta": 0.90,
    "denver": 0.90,
    "houston": 0.90,
    "miami": 0.00,
    "dallas": 0.00,
    "san-francisco": 0.00,
    "austin": 0.50,
    "chicago": 0.50,
    "los-angeles": 0.50,
    "nyc": 0.35,
    "seattle": 0.35,
}
MICROSTRUCTURE_GATE_MIN_ROWS = 25
MICROSTRUCTURE_GATE_MAX_DELTA_VS_CANDIDATE = 0.0
MICROSTRUCTURE_GATE_MAX_DELTA_VS_MARKET = 0.0
MICROSTRUCTURE_GATE_MAX_LOGLOSS_DELTA_VS_CANDIDATE = 0.0
MICROSTRUCTURE_GATE_MAX_ECE = 0.12
MICROSTRUCTURE_GATE_MAX_OVERCONFIDENT_ERROR_RATE = 0.25
MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS = [
    "variant_id",
    "variant_family",
    "uses_market_features",
    "is_control",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "artifact_hash",
    "postprocess_config_hash",
    "experiment_start_date",
    "attribution_schema_version",
    "captured_at_local",
    "range_label",
    "bin_type",
    "bin_value",
    "cutoff_hour",
    "cutoff_regime",
    "source_freshness_state",
    "settlement_distance_bucket",
    "forecast_source_count_bucket",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "casebook_taxonomy",
    "casebook_case_id",
    "casebook_result",
    "casebook_slice_type",
    "feature_schema_version",
    "feature_family_hash",
    "feature_missingness_hash",
    "clob_feature_available",
    "clob_midpoint",
    "clob_spread",
    "clob_liquidity_score",
    "micro_gate_taxonomy",
    "micro_gate_reason",
]

def load_artifact(path):
    path = Path(path)
    with path.open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, dict) or not artifact.get("models"):
        raise ValueError(f"{path} is not a pooled feature artifact")
    return artifact


def artifact_hash_for_path(path):
    try:
        return sha256_file(path)
    except OSError:
        return ""


def payload_hash(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _valid_probability(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value)


def _clamp_probability(value):
    return max(0.0, min(1.0, float(value)))


def family_unit_matches(spec, family_unit):
    return bool(spec) and (
        str(family_unit or "").lower() == "all" or spec.display_unit == family_unit
    )


def band_probability_from_distribution(distribution, kind, value, value_hi=None):
    """Map a native-unit bucket distribution to one Polymarket band."""
    if not distribution:
        return None
    try:
        lo = float(value)
        hi = float(value_hi) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None

    kind = str(kind or "eq").lower()
    total = 0.0
    for bucket, probability in distribution.items():
        try:
            bucket_value = float(bucket)
            probability = float(probability)
        except (TypeError, ValueError):
            continue
        if kind == "lte" and bucket_value <= lo:
            total += probability
        elif kind == "gte" and bucket_value >= lo:
            total += probability
        elif kind not in ("lte", "gte") and lo <= bucket_value <= hi:
            total += probability
    return _clamp_probability(total)


def probability_view(rows, probability_field):
    output = []
    for row in rows:
        probability = row.get(probability_field)
        if not _valid_probability(probability):
            continue
        copy = dict(row)
        copy["model_probability"] = _clamp_probability(probability)
        output.append(copy)
    return output


def candidate_comparison(rows):
    """Candidate vs current serving replay vs recorded tape vs market."""
    candidate_rows = probability_view(rows, "candidate_p")
    if not candidate_rows:
        return None
    current_rows = probability_view(candidate_rows, "replayed_p")
    recorded_rows = probability_view(candidate_rows, "recorded_p")
    candidate = score_rows(candidate_rows)
    current = score_rows(current_rows)
    recorded = score_rows(recorded_rows)
    if not candidate or not current or not recorded:
        return None
    ece = expected_calibration_error(candidate_rows, "model_probability")
    return {
        "n": candidate["n"],
        "candidate_brier": candidate["model_brier"],
        "current_brier": current["model_brier"],
        "recorded_brier": recorded["model_brier"],
        "market_brier": candidate["market_brier"],
        "candidate_logloss": candidate["model_logloss"],
        "current_logloss": current["model_logloss"],
        "recorded_logloss": recorded["model_logloss"],
        "market_logloss": candidate["market_logloss"],
        "candidate_skill": candidate["brier_skill_score"],
        "current_skill": current["brier_skill_score"],
        "recorded_skill": recorded["brier_skill_score"],
        "candidate_ece": ece,
        "delta_vs_current": candidate["model_brier"] - current["model_brier"],
        "delta_vs_recorded": candidate["model_brier"] - recorded["model_brier"],
        "delta_vs_market": candidate["model_brier"] - candidate["market_brier"],
        "base_rate": candidate["base_rate"],
    }


def _score_probability_field(rows, probability_field):
    view = probability_view(rows, probability_field)
    if not view:
        return None
    return score_rows(view)


def calibration_diagnostics(rows, probability_field):
    scored = []
    high_confidence = []
    high_confidence_wrong = []
    for row in rows:
        probability = row.get(probability_field)
        if not _valid_probability(probability) or row.get("outcome") is None:
            continue
        probability = _clamp_probability(probability)
        outcome = int(row.get("outcome"))
        scored.append({
            "model_probability": probability,
            "outcome": outcome,
        })
        if probability >= 0.90 or probability <= 0.10:
            high_confidence.append((probability, outcome))
            if (probability >= 0.90 and outcome == 0) or (probability <= 0.10 and outcome == 1):
                high_confidence_wrong.append((probability, outcome))
    if not scored:
        return {
            "ece": None,
            "extreme_prediction_rate": None,
            "overconfident_error_rate": None,
        }
    return {
        "ece": expected_calibration_error(scored, "model_probability"),
        "extreme_prediction_rate": len(high_confidence) / len(scored),
        "overconfident_error_rate": (
            len(high_confidence_wrong) / len(high_confidence)
            if high_confidence else 0.0
        ),
    }


def microstructure_comparison(rows, probability_field="micro_candidate_p"):
    """Microstructure overlay vs pooled candidate/current/market on same rows."""
    micro_rows = probability_view(rows, probability_field)
    if not micro_rows:
        return None
    micro = score_rows(micro_rows)
    base = _score_probability_field(micro_rows, "candidate_p")
    current = _score_probability_field(micro_rows, "replayed_p")
    recorded = _score_probability_field(micro_rows, "recorded_p")
    if not micro or not base or not current or not recorded:
        return None
    micro_calibration = calibration_diagnostics(micro_rows, probability_field)
    base_calibration = calibration_diagnostics(micro_rows, "candidate_p")
    return {
        "n": micro["n"],
        "micro_brier": micro["model_brier"],
        "candidate_brier": base["model_brier"],
        "current_brier": current["model_brier"],
        "recorded_brier": recorded["model_brier"],
        "market_brier": micro["market_brier"],
        "micro_logloss": micro["model_logloss"],
        "candidate_logloss": base["model_logloss"],
        "current_logloss": current["model_logloss"],
        "recorded_logloss": recorded["model_logloss"],
        "market_logloss": micro["market_logloss"],
        "micro_ece": micro_calibration["ece"],
        "candidate_ece": base_calibration["ece"],
        "micro_extreme_prediction_rate": micro_calibration["extreme_prediction_rate"],
        "micro_overconfident_error_rate": micro_calibration["overconfident_error_rate"],
        "micro_skill": micro["brier_skill_score"],
        "candidate_skill": base["brier_skill_score"],
        "current_skill": current["brier_skill_score"],
        "delta_vs_candidate": micro["model_brier"] - base["model_brier"],
        "delta_vs_current": micro["model_brier"] - current["model_brier"],
        "delta_vs_recorded": micro["model_brier"] - recorded["model_brier"],
        "delta_vs_market": micro["model_brier"] - micro["market_brier"],
        "base_rate": micro["base_rate"],
    }


def grouped_microstructure_comparison(rows, group_key, probability_field="micro_candidate_p"):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = microstructure_comparison(group_rows, probability_field=probability_field)
        if comp:
            output.append({"group": group, **comp})
    return output


def _micro_gate_reason(
    comp,
    min_rows,
    max_delta_vs_candidate,
    max_delta_vs_market,
    max_logloss_delta_vs_candidate,
    max_ece,
    max_overconfident_error_rate,
):
    if not comp:
        return "missing taxonomy score"
    rows = int(comp.get("n") or 0)
    if rows < int(min_rows):
        return f"rows {rows} < {int(min_rows)}"
    delta_candidate = comp.get("delta_vs_candidate")
    if delta_candidate is None or delta_candidate > float(max_delta_vs_candidate):
        return (
            f"delta_vs_candidate {delta_candidate:+.4f} > {float(max_delta_vs_candidate):+.4f}"
            if delta_candidate is not None
            else "missing delta_vs_candidate"
        )
    delta_market = comp.get("delta_vs_market")
    if delta_market is None or delta_market > float(max_delta_vs_market):
        return (
            f"delta_vs_market {delta_market:+.4f} > {float(max_delta_vs_market):+.4f}"
            if delta_market is not None
            else "missing delta_vs_market"
        )
    micro_logloss = comp.get("micro_logloss")
    candidate_logloss = comp.get("candidate_logloss")
    if micro_logloss is None or candidate_logloss is None:
        return "missing log-loss score"
    logloss_delta = micro_logloss - candidate_logloss
    if logloss_delta > float(max_logloss_delta_vs_candidate):
        return (
            f"logloss_delta_vs_candidate {logloss_delta:+.4f} > "
            f"{float(max_logloss_delta_vs_candidate):+.4f}"
        )
    micro_ece = comp.get("micro_ece")
    if micro_ece is None or micro_ece > float(max_ece):
        return (
            f"micro_ece {micro_ece:.4f} > {float(max_ece):.4f}"
            if micro_ece is not None else
            "missing micro_ece"
        )
    overconfident_error = comp.get("micro_overconfident_error_rate")
    if (
        overconfident_error is None
        or overconfident_error > float(max_overconfident_error_rate)
    ):
        return (
            f"micro_overconfident_error_rate {overconfident_error:.4f} > "
            f"{float(max_overconfident_error_rate):.4f}"
            if overconfident_error is not None else
            "missing micro_overconfident_error_rate"
        )
    return None


def build_microstructure_gate(
    taxonomy_scores,
    target_taxonomies=MICROSTRUCTURE_TARGET_TAXONOMIES,
    min_rows=MICROSTRUCTURE_GATE_MIN_ROWS,
    max_delta_vs_candidate=MICROSTRUCTURE_GATE_MAX_DELTA_VS_CANDIDATE,
    max_delta_vs_market=MICROSTRUCTURE_GATE_MAX_DELTA_VS_MARKET,
    max_logloss_delta_vs_candidate=MICROSTRUCTURE_GATE_MAX_LOGLOSS_DELTA_VS_CANDIDATE,
    max_ece=MICROSTRUCTURE_GATE_MAX_ECE,
    max_overconfident_error_rate=MICROSTRUCTURE_GATE_MAX_OVERCONFIDENT_ERROR_RATE,
):
    """Return the taxonomy allowlist for applying the CLOB overlay.

    The raw overlay is allowed to change probabilities only on pre-declared
    target taxonomies where out-of-fold replay beats both the base candidate and
    the market on that same slice. Everything else falls back to the base
    candidate probability.
    """
    by_taxonomy = {
        item.get("group"): item
        for item in taxonomy_scores or []
        if item.get("group") not in (None, "")
    }
    decisions = []
    allowed = []
    blocked = []
    for taxonomy in target_taxonomies:
        comp = by_taxonomy.get(taxonomy)
        reason = _micro_gate_reason(
            comp,
            min_rows=min_rows,
            max_delta_vs_candidate=max_delta_vs_candidate,
            max_delta_vs_market=max_delta_vs_market,
            max_logloss_delta_vs_candidate=max_logloss_delta_vs_candidate,
            max_ece=max_ece,
            max_overconfident_error_rate=max_overconfident_error_rate,
        )
        decision = {
            "taxonomy": taxonomy,
            "allowed": reason is None,
            "reason": "replay-proven improvement" if reason is None else reason,
            "rows": (comp or {}).get("n", 0),
            "micro_brier": (comp or {}).get("micro_brier"),
            "candidate_brier": (comp or {}).get("candidate_brier"),
            "market_brier": (comp or {}).get("market_brier"),
            "micro_logloss": (comp or {}).get("micro_logloss"),
            "candidate_logloss": (comp or {}).get("candidate_logloss"),
            "micro_ece": (comp or {}).get("micro_ece"),
            "micro_overconfident_error_rate": (comp or {}).get("micro_overconfident_error_rate"),
            "delta_vs_candidate": (comp or {}).get("delta_vs_candidate"),
            "delta_vs_market": (comp or {}).get("delta_vs_market"),
        }
        decisions.append(decision)
        if decision["allowed"]:
            allowed.append(taxonomy)
        else:
            blocked.append(decision)
    return {
        "schema_version": MICROSTRUCTURE_GATE_SCHEMA_VERSION,
        "policy": "target_taxonomy_replay_allowlist",
        "target_taxonomies": list(target_taxonomies),
        "allowed_taxonomies": allowed,
        "blocked_taxonomies": blocked,
        "decisions": decisions,
        "min_rows": int(min_rows),
        "max_delta_vs_candidate": float(max_delta_vs_candidate),
        "max_delta_vs_market": float(max_delta_vs_market),
        "max_logloss_delta_vs_candidate": float(max_logloss_delta_vs_candidate),
        "max_ece": float(max_ece),
        "max_overconfident_error_rate": float(max_overconfident_error_rate),
    }


def apply_microstructure_gate(rows, gate, overlay_field="micro_candidate_p", output_field="micro_gated_candidate_p"):
    allowed = set((gate or {}).get("allowed_taxonomies") or [])
    counts = {
        "overlay_rows": 0,
        "base_rows": 0,
        "missing_base_rows": 0,
        "missing_overlay_rows": 0,
        "allowed_taxonomies": sorted(allowed),
    }
    for row in rows:
        row[output_field] = None
        row["micro_gate_action"] = "none"
        row["micro_gate_reason"] = "missing base candidate probability"
        row["micro_gate_taxonomy"] = row.get("casebook_taxonomy")
        base = row.get("candidate_p")
        if not _valid_probability(base):
            counts["missing_base_rows"] += 1
            continue
        taxonomy = row.get("casebook_taxonomy")
        overlay = row.get(overlay_field)
        if taxonomy in allowed and _valid_probability(overlay):
            row[output_field] = _clamp_probability(overlay)
            row["micro_gate_action"] = "overlay"
            row["micro_gate_reason"] = f"allowed taxonomy: {taxonomy}"
            counts["overlay_rows"] += 1
            continue
        row[output_field] = _clamp_probability(base)
        row["micro_gate_action"] = "base"
        if taxonomy in allowed:
            row["micro_gate_reason"] = "allowed taxonomy but missing overlay probability"
            counts["missing_overlay_rows"] += 1
        elif taxonomy:
            row["micro_gate_reason"] = f"blocked taxonomy: {taxonomy}"
        else:
            row["micro_gate_reason"] = "no casebook taxonomy"
        counts["base_rows"] += 1
    return counts


def _shadow_band_key(row):
    label = row.get("range_label")
    if label not in (None, ""):
        return str(label)
    kind = row.get("bin_type") or row.get("bin_kind") or "eq"
    value = row.get("bin_value_c") or row.get("bin_value")
    value_hi = row.get("bin_value_hi_c") or row.get("bin_value_hi")
    if value_hi not in (None, "", value):
        return f"{kind}:{value}-{value_hi}"
    return f"{kind}:{value}"


def _shadow_variant_row(row, variant, experiment_start_date):
    probability = row.get(variant["probability_field"])
    if not _valid_probability(probability):
        return None
    feature_payload = {
        field: row.get(field)
        for field in ATTRIBUTION_FEATURE_FIELDS
        if row.get(field) not in (None, "")
    }
    missingness_payload = {
        field: row.get(field) in (None, "")
        for field in ATTRIBUTION_FEATURE_FIELDS
    }
    return {
        "variant_id": variant["variant_id"],
        "variant_family": variant["variant_family"],
        "uses_market_features": variant["uses_market_features"],
        "is_control": variant["is_control"],
        "market_id": row.get("market_id"),
        "target_date": row.get("target_date"),
        "snapshot_id": row.get("snapshot_id"),
        "band_key": _shadow_band_key(row),
        "probability": _clamp_probability(probability),
        "current_probability": row.get("replayed_p"),
        "recorded_probability": row.get("recorded_p"),
        "market_yes": row.get("market_yes"),
        "outcome": int(row.get("outcome")),
        "artifact_hash": variant.get("artifact_hash") or row.get("artifact_hash") or "",
        "postprocess_config_hash": variant.get("postprocess_config_hash") or "",
        "experiment_start_date": experiment_start_date,
        "attribution_schema_version": ATTRIBUTION_SCHEMA_VERSION,
        "captured_at_local": row.get("captured_at_local"),
        "range_label": row.get("range_label"),
        "bin_type": row.get("bin_type") or row.get("bin_kind"),
        "bin_value": row.get("bin_value_c") or row.get("bin_value"),
        "cutoff_hour": row.get("candidate_cutoff_hour"),
        "cutoff_regime": row.get("candidate_cutoff_regime"),
        "source_freshness_state": row.get("source_freshness_state"),
        "settlement_distance_bucket": row.get("settlement_distance_bucket"),
        "forecast_source_count_bucket": row.get("forecast_source_count_bucket"),
        "forecast_disagreement_bucket": row.get("forecast_disagreement_bucket"),
        "forecast_bucket_pressure": row.get("forecast_bucket_pressure"),
        "casebook_taxonomy": row.get("casebook_taxonomy"),
        "casebook_case_id": row.get("casebook_case_id"),
        "casebook_result": row.get("casebook_result"),
        "casebook_slice_type": row.get("casebook_slice_type"),
        "feature_schema_version": row.get("feature_schema_version"),
        "feature_family_hash": row.get("feature_family_hash") or (payload_hash(feature_payload) if feature_payload else ""),
        "feature_missingness_hash": row.get("feature_missingness_hash") or payload_hash(missingness_payload),
        "clob_feature_available": row.get("clob_feature_available"),
        "clob_midpoint": row.get("clob_midpoint"),
        "clob_spread": row.get("clob_spread"),
        "clob_liquidity_score": row.get("clob_liquidity_score"),
        "micro_gate_taxonomy": row.get("micro_gate_taxonomy"),
        "micro_gate_reason": row.get("micro_gate_reason"),
    }


def _settled_shadow_source_rows(rows):
    for row in rows:
        if (
            not _valid_probability(row.get("market_yes"))
            or not _valid_probability(row.get("replayed_p"))
            or row.get("outcome") is None
        ):
            continue
        yield row


def ensure_variant_export_disk_headroom(
    path,
    row_count,
    min_free_bytes=0,
    bytes_per_row=DEFAULT_VARIANT_EXPORT_BYTES_PER_ROW,
):
    """Fail before writing large generated variant exports when disk is low."""
    return ensure_row_export_disk_headroom(
        path,
        row_count,
        min_free_bytes=min_free_bytes,
        bytes_per_row=bytes_per_row,
        context="variant export",
    )


def candidate_shadow_variant_rows(
    rows,
    variant_id,
    variant_family,
    uses_market_features=False,
    is_control=False,
    artifact_hash="",
    postprocess_config_hash="",
    experiment_start_date=None,
):
    """Return item-69-compatible rows for a single replayed candidate artifact."""
    experiment_start_date = experiment_start_date or datetime.now().date().isoformat()
    variant = {
        "variant_id": variant_id,
        "variant_family": variant_family,
        "uses_market_features": bool(uses_market_features),
        "is_control": bool(is_control),
        "probability_field": "candidate_p",
        "artifact_hash": artifact_hash,
        "postprocess_config_hash": postprocess_config_hash,
    }
    output = []
    for row in _settled_shadow_source_rows(rows):
        variant_row = _shadow_variant_row(row, variant, experiment_start_date)
        if variant_row is not None:
            output.append(variant_row)
    return output


def write_candidate_shadow_variants(
    path,
    rows,
    variant_id,
    variant_family,
    uses_market_features=False,
    is_control=False,
    artifact_hash="",
    postprocess_config_hash="",
    min_free_bytes=0,
):
    if not path:
        return None, 0
    variant_rows = candidate_shadow_variant_rows(
        rows,
        variant_id=variant_id,
        variant_family=variant_family,
        uses_market_features=uses_market_features,
        is_control=is_control,
        artifact_hash=artifact_hash,
        postprocess_config_hash=postprocess_config_hash,
    )
    path = Path(path)
    ensure_variant_export_disk_headroom(path, len(variant_rows), min_free_bytes=min_free_bytes)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS)
        writer.writeheader()
        writer.writerows(variant_rows)
    return str(path), len(variant_rows)


def source_state_ablation_feature_groups(artifact):
    """Return dynamic source-state feature families present in a replayed artifact."""
    artifact = artifact or {}
    declared = set(artifact.get("dynamic_source_state_columns") or [])
    feature_names = set()
    for bundle in (artifact.get("models") or {}).values():
        feature_names.update(str(name) for name in bundle.get("feature_names") or [])
    columns = declared | {
        name
        for name in feature_names
        if name.startswith("source_")
    }
    groups = {
        "freshest_forecast_age": [
            column for column in columns
            if column in {"source_forecast_payload_age_minutes"}
        ],
        "max_forecast_age": [
            column for column in columns
            if column in {"source_forecast_max_age_minutes"}
        ],
        "forecast_family_degradation": sorted(
            column for column in columns
            if column in {"source_forecast_failed_count", "source_forecast_stale_count"}
        ),
        "wu_history_state": sorted(
            column for column in columns
            if column.startswith("source_wu_history_")
        ),
        "metar_state": sorted(
            column for column in columns
            if column.startswith("source_metar_")
        ),
        "source_state_counts": sorted(
            column for column in columns
            if column in {
                "source_state_all_fresh",
                "source_state_missing_sources",
                "source_failed_count",
                "source_stale_count",
                "source_unknown_count",
            }
        ),
        "status_group_interactions": sorted(
            column for column in columns
            if column == "source_status_group" or column.startswith("source_status_group_")
        ),
        "cross_source_disagreement": [
            column for column in columns
            if column in {"source_cross_source_max_disagreement"}
        ],
    }
    return {
        key: value
        for key, value in groups.items()
        if value
    }


def source_state_degradation_bucket(row):
    state = str(row.get("source_freshness_state") or row.get("source_status_group") or "").strip()
    if not state:
        return "unknown_source_state"
    if state == "all_fresh":
        return "all_fresh"
    if state == "missing_source_status" or state == "missing_sources":
        return "missing_source_status"
    if "failed:" in state or "stale:" in state or "rate_limited" in state:
        return "degraded_source"
    return "other_source_state"


def source_state_ablation_shadow_variant_rows(
    rows,
    experiment_start_date=None,
    candidate_artifact_hash="",
):
    """Return item-69-compatible control and dynamic source-state variant rows."""
    experiment_start_date = experiment_start_date or datetime.now().date().isoformat()
    variants = [
        {
            "variant_id": "source_state_no_source_state_current",
            "variant_family": SOURCE_STATE_ABLATION_FAMILY,
            "probability_field": "replayed_p",
            "uses_market_features": False,
            "is_control": True,
            "artifact_hash": "",
            "postprocess_config_hash": "current_serving_no_source_state",
        },
        {
            "variant_id": "source_state_dynamic_candidate",
            "variant_family": SOURCE_STATE_ABLATION_FAMILY,
            "probability_field": "candidate_p",
            "uses_market_features": False,
            "is_control": False,
            "artifact_hash": candidate_artifact_hash,
            "postprocess_config_hash": SOURCE_STATE_ABLATION_SCHEMA_VERSION,
        },
    ]
    output = []
    for row in _settled_shadow_source_rows(rows):
        for variant in variants:
            variant_row = _shadow_variant_row(row, variant, experiment_start_date)
            if variant_row is not None:
                output.append(variant_row)
    return output


def write_source_state_ablation_shadow_variants(path, rows, min_free_bytes=0):
    if not path:
        return None
    path = Path(path)
    ensure_variant_export_disk_headroom(path, len(rows), min_free_bytes=min_free_bytes)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def source_state_ablation_gate(rows):
    aggregate = candidate_comparison(rows)
    daily_first = daily_first_candidate_comparison(rows)
    all_fresh_rows = [
        row for row in rows
        if source_state_degradation_bucket(row) == "all_fresh"
    ]
    degraded_rows = [
        row for row in rows
        if source_state_degradation_bucket(row) == "degraded_source"
    ]
    all_fresh = candidate_comparison(all_fresh_rows)
    degraded = candidate_comparison(degraded_rows)
    reasons = []
    if not aggregate:
        reasons.append("no paired source-state replay rows")
    if daily_first and daily_first.get("delta_vs_current") is not None and daily_first["delta_vs_current"] > 0:
        reasons.append("daily-first candidate regresses current serving")
    if (
        all_fresh
        and all_fresh.get("delta_vs_current") is not None
        and all_fresh["delta_vs_current"] > SOURCE_STATE_ABLATION_ALL_FRESH_MAX_REGRESSION
    ):
        reasons.append("all-fresh rows regress current serving")
    if (
        degraded
        and degraded.get("delta_vs_current") is not None
        and degraded["delta_vs_current"] > SOURCE_STATE_ABLATION_DEGRADED_MAX_REGRESSION
    ):
        reasons.append("degraded-source rows regress current serving")
    verdict = "READY" if not reasons else "SHADOW"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "aggregate": aggregate,
        "daily_first": daily_first,
        "all_fresh": all_fresh,
        "degraded_source": degraded,
    }


def grouped_source_state_ablation(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = candidate_comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def source_state_degradation_rows(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[source_state_degradation_bucket(row)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = candidate_comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def source_state_ablation_report(
    rows,
    artifact,
    candidate_artifact_hash="",
    variant_out_path=DEFAULT_SOURCE_STATE_ABLATION_VARIANT_OUT,
    min_free_bytes=0,
):
    feature_groups = source_state_ablation_feature_groups(artifact)
    enabled = bool((artifact or {}).get("dynamic_source_state_enabled") or feature_groups)
    if not enabled:
        return {
            "schema_version": SOURCE_STATE_ABLATION_SCHEMA_VERSION,
            "enabled": False,
            "reason": "candidate artifact does not declare dynamic source-state features",
            "feature_groups": feature_groups,
        }
    variant_rows = source_state_ablation_shadow_variant_rows(
        rows,
        candidate_artifact_hash=candidate_artifact_hash,
    )
    variant_path = write_source_state_ablation_shadow_variants(
        variant_out_path,
        variant_rows,
        min_free_bytes=min_free_bytes,
    )
    return {
        "schema_version": SOURCE_STATE_ABLATION_SCHEMA_VERSION,
        "enabled": True,
        "feature_groups": feature_groups,
        "gate": source_state_ablation_gate(rows),
        "by_degradation": source_state_degradation_rows(rows),
        "by_source_freshness": grouped_source_state_ablation(rows, "source_freshness_state"),
        "by_market": grouped_source_state_ablation(rows, "market_id"),
        "shadow_variants": {
            "path": variant_path,
            "rows": len(variant_rows),
            "variant_ids": sorted({row["variant_id"] for row in variant_rows}),
        },
    }


def microstructure_shadow_variant_rows(
    rows,
    experiment_start_date=None,
    candidate_artifact_hash="",
    microstructure_artifact_hash="",
):
    """Return item-69-compatible rows for base, raw CLOB, and gated CLOB lanes."""
    variants = [
        {
            "variant_id": "pooled_f_candidate_control",
            "variant_family": "clob_overlay",
            "probability_field": "candidate_p",
            "uses_market_features": False,
            "is_control": True,
            "artifact_hash": candidate_artifact_hash,
            "postprocess_config_hash": "base_candidate",
        },
        {
            "variant_id": "clob_overlay_raw_oof",
            "variant_family": "clob_overlay",
            "probability_field": "micro_candidate_p",
            "uses_market_features": True,
            "is_control": False,
            "artifact_hash": microstructure_artifact_hash,
            "postprocess_config_hash": "raw_oof",
        },
        {
            "variant_id": "clob_overlay_gated_taxonomy",
            "variant_family": "clob_overlay",
            "probability_field": "micro_gated_candidate_p",
            "uses_market_features": True,
            "is_control": False,
            "artifact_hash": microstructure_artifact_hash,
            "postprocess_config_hash": "taxonomy_gate",
        },
    ]
    experiment_start_date = experiment_start_date or datetime.now().date().isoformat()
    output = []
    for row in _settled_shadow_source_rows(rows):
        for variant in variants:
            variant_row = _shadow_variant_row(row, variant, experiment_start_date)
            if variant_row is not None:
                output.append(variant_row)
    return output


def write_microstructure_shadow_variants(path, rows, min_free_bytes=0):
    if not path:
        return None
    path = Path(path)
    ensure_variant_export_disk_headroom(path, len(rows), min_free_bytes=min_free_bytes)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def bridge_policy_payload(alpha_by_market=None):
    alpha_by_market = dict(alpha_by_market or CONSERVATIVE_BRIDGE_ALPHA_BY_MARKET)
    return {
        "schema_version": CONSERVATIVE_BRIDGE_SCHEMA_VERSION,
        "policy_id": "item73_conservative_bridge_2026_06_15",
        "alpha_by_market": dict(sorted(alpha_by_market.items())),
        "probability_formula": "alpha * candidate_p + (1 - alpha) * current_serving_p",
        "uses_market_features": False,
        "notes": (
            "Predeclared per-market operational bridge. It does not use market "
            "prices, CLOB features, outcomes, or same-day promotion decisions."
        ),
    }


def bridge_alpha_for_market(market_id, alpha_by_market=None):
    alpha_by_market = alpha_by_market or CONSERVATIVE_BRIDGE_ALPHA_BY_MARKET
    try:
        return max(0.0, min(1.0, float(alpha_by_market[str(market_id)])))
    except (KeyError, TypeError, ValueError):
        return 0.0


def apply_conservative_bridge(rows, alpha_by_market=None, output_field="bridge_candidate_p"):
    policy = bridge_policy_payload(alpha_by_market)
    for row in rows:
        row[output_field] = None
        row["bridge_alpha"] = bridge_alpha_for_market(row.get("market_id"), policy["alpha_by_market"])
        row["bridge_policy_id"] = policy["policy_id"]
        if not _valid_probability(row.get("candidate_p")) or not _valid_probability(row.get("replayed_p")):
            row["bridge_reason"] = "missing candidate or current probability"
            continue
        candidate = _clamp_probability(row["candidate_p"])
        current = _clamp_probability(row["replayed_p"])
        alpha = row["bridge_alpha"]
        row[output_field] = _clamp_probability(alpha * candidate + (1.0 - alpha) * current)
        row["bridge_reason"] = f"alpha={alpha:.2f}"
    return policy


def bridge_comparison(rows, probability_field="bridge_candidate_p"):
    bridge_rows = probability_view(rows, probability_field)
    if not bridge_rows:
        return None
    bridge = score_rows(bridge_rows)
    candidate = _score_probability_field(bridge_rows, "candidate_p")
    current = _score_probability_field(bridge_rows, "replayed_p")
    recorded = _score_probability_field(bridge_rows, "recorded_p")
    if not bridge or not candidate or not current:
        return None
    bridge_calibration = calibration_diagnostics(bridge_rows, probability_field)
    candidate_calibration = calibration_diagnostics(bridge_rows, "candidate_p")
    return {
        "n": bridge["n"],
        "bridge_brier": bridge["model_brier"],
        "candidate_brier": candidate["model_brier"],
        "current_brier": current["model_brier"],
        "recorded_brier": recorded["model_brier"] if recorded else None,
        "market_brier": bridge["market_brier"],
        "bridge_logloss": bridge["model_logloss"],
        "candidate_logloss": candidate["model_logloss"],
        "current_logloss": current["model_logloss"],
        "recorded_logloss": recorded["model_logloss"] if recorded else None,
        "market_logloss": bridge["market_logloss"],
        "bridge_ece": bridge_calibration["ece"],
        "candidate_ece": candidate_calibration["ece"],
        "bridge_skill": bridge["brier_skill_score"],
        "candidate_skill": candidate["brier_skill_score"],
        "current_skill": current["brier_skill_score"],
        "delta_vs_candidate": bridge["model_brier"] - candidate["model_brier"],
        "delta_vs_current": bridge["model_brier"] - current["model_brier"],
        "delta_vs_recorded": (
            bridge["model_brier"] - recorded["model_brier"]
            if recorded else None
        ),
        "delta_vs_market": bridge["model_brier"] - bridge["market_brier"],
        "base_rate": bridge["base_rate"],
    }


def grouped_bridge_comparison(rows, group_key, probability_field="bridge_candidate_p"):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = bridge_comparison(group_rows, probability_field=probability_field)
        if comp:
            output.append({"group": group, **comp})
    return output


def conservative_bridge_shadow_variant_rows(
    rows,
    experiment_start_date=None,
    candidate_artifact_hash="",
    policy_hash="",
):
    experiment_start_date = experiment_start_date or datetime.now().date().isoformat()
    policy_hash = policy_hash or payload_hash(bridge_policy_payload())
    output = []
    variants = [
        {
            "variant_id": "pooled_f_candidate_control",
            "variant_family": "conservative_bridge",
            "probability_field": "candidate_p",
            "uses_market_features": False,
            "is_control": True,
            "artifact_hash": candidate_artifact_hash,
            "postprocess_config_hash": "base_candidate",
        },
        {
            "variant_id": "conservative_bridge_policy_v0_1",
            "variant_family": "conservative_bridge",
            "probability_field": "bridge_candidate_p",
            "uses_market_features": False,
            "is_control": False,
            "artifact_hash": policy_hash,
            "postprocess_config_hash": CONSERVATIVE_BRIDGE_SCHEMA_VERSION,
        },
    ]
    for row in _settled_shadow_source_rows(rows):
        for variant in variants:
            variant_row = _shadow_variant_row(row, variant, experiment_start_date)
            if variant_row is not None:
                output.append(variant_row)
    return output


def write_conservative_bridge_shadow_variants(path, rows, min_free_bytes=0):
    if not path:
        return None
    path = Path(path)
    ensure_variant_export_disk_headroom(path, len(rows), min_free_bytes=min_free_bytes)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def conservative_bridge_report(
    rows,
    variant_out_path=DEFAULT_BRIDGE_VARIANT_OUT,
    min_free_bytes=0,
):
    policy = apply_conservative_bridge(rows)
    policy_hash = payload_hash(policy)
    variant_rows = conservative_bridge_shadow_variant_rows(
        rows,
        candidate_artifact_hash=rows[0].get("candidate_artifact_hash") if rows else "",
        policy_hash=policy_hash,
    )
    variant_path = write_conservative_bridge_shadow_variants(
        variant_out_path,
        variant_rows,
        min_free_bytes=min_free_bytes,
    )
    return {
        "schema_version": CONSERVATIVE_BRIDGE_SCHEMA_VERSION,
        "enabled": True,
        "policy": policy,
        "policy_hash": policy_hash,
        "diagnostics": {
            "shadow_variant_rows": len(variant_rows),
            "shadow_variant_path": variant_path,
        },
        "aggregate": bridge_comparison(rows),
        "by_market": grouped_bridge_comparison(rows, "market_id"),
        "by_hour": grouped_bridge_comparison(rows, "candidate_cutoff_hour"),
        "by_settlement_distance": grouped_bridge_comparison(rows, "settlement_distance_bucket"),
        "by_source_freshness": grouped_bridge_comparison(rows, "source_freshness_state"),
    }


def grouped_candidate_comparison(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = candidate_comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def daily_first_candidate_comparison(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.get("market_id"), row.get("target_date"))].append(row)
    comps = [candidate_comparison(group_rows) for group_rows in grouped.values()]
    comps = [comp for comp in comps if comp]
    if not comps:
        return None

    def avg(key):
        return sum(comp[key] for comp in comps) / len(comps)

    return {
        "n_days": len(comps),
        "n": sum(comp["n"] for comp in comps),
        "candidate_brier": avg("candidate_brier"),
        "current_brier": avg("current_brier"),
        "recorded_brier": avg("recorded_brier"),
        "market_brier": avg("market_brier"),
        "candidate_skill": avg("candidate_skill"),
        "current_skill": avg("current_skill"),
        "delta_vs_current": avg("candidate_brier") - avg("current_brier"),
        "delta_vs_market": avg("candidate_brier") - avg("market_brier"),
        "base_rate": avg("base_rate"),
    }


def blocked_candidate_validation_gate(rows, current_tol=0.003, market_tol=0.003, min_days=2):
    """Gate promotion on daily-first blocked validation, not row-level lift alone."""
    rows = list(rows)
    daily_first = daily_first_candidate_comparison(rows)
    split_audit = blocked_validation_audit(rows)
    reasons = []
    if not split_audit.get("ok"):
        reasons.append(f"{split_audit.get('leak_count', 0)} blocked split leakage issue(s)")
    if not daily_first:
        reasons.append("no daily-first candidate comparison rows")
    else:
        n_days = int(daily_first.get("n_days") or 0)
        if n_days < min_days:
            reasons.append(f"{n_days} daily-first held-out day(s) < {min_days}")
        delta_current = daily_first.get("delta_vs_current")
        if delta_current is None or delta_current > current_tol:
            reasons.append(
                f"daily-first candidate regresses current by {delta_current:+.4f} > {current_tol:.4f}"
                if delta_current is not None else
                "missing daily-first candidate-vs-current delta"
            )
        candidate_brier = daily_first.get("candidate_brier")
        market_brier = daily_first.get("market_brier")
        if candidate_brier is None or market_brier is None or candidate_brier > market_brier + market_tol:
            reasons.append(
                "daily-first candidate is not within market tolerance"
                if candidate_brier is not None and market_brier is not None else
                "missing daily-first candidate-vs-market metrics"
            )
    return {
        "schema_version": "blocked_candidate_validation_gate_v0.1",
        "split_mode": "daily_first_market_day",
        "passed": not reasons,
        "verdict": "PASS" if not reasons else "BLOCK",
        "current_tol": current_tol,
        "market_tol": market_tol,
        "min_days": min_days,
        "reasons": reasons,
        "daily_first": daily_first,
        "split_audit": split_audit,
    }


EXACT_WINNER_TARGET_MARKETS = ("seattle", "nyc", "miami", "chicago")


def _distance_bucket(row):
    value = row.get("settlement_distance_bucket")
    if value in (None, ""):
        value = row.get("settlement_distance")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _cutoff_hour(row):
    value = row.get("candidate_cutoff_hour")
    if value in (None, ""):
        value = row.get("cutoff_hour")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bin_type(row):
    return str(row.get("bin_type") or row.get("bin_kind") or "").lower()


def exact_winner_probability_summary(rows):
    winners = [
        row for row in rows
        if int(row.get("outcome") or 0) == 1
        and _bin_type(row) == "eq"
        and _distance_bucket(row) == 0
        and _valid_probability(row.get("candidate_p"))
        and _valid_probability(row.get("replayed_p"))
        and _valid_probability(row.get("market_yes"))
    ]
    if not winners:
        return {
            "winner_rows": 0,
            "candidate_mean_probability": None,
            "current_mean_probability": None,
            "market_mean_probability": None,
            "candidate_minus_current": None,
            "candidate_minus_market": None,
            "candidate_over_50_rate": None,
            "current_over_50_rate": None,
            "market_over_50_rate": None,
        }
    n = len(winners)
    candidate_mean = sum(float(row["candidate_p"]) for row in winners) / n
    current_mean = sum(float(row["replayed_p"]) for row in winners) / n
    market_mean = sum(float(row["market_yes"]) for row in winners) / n
    return {
        "winner_rows": n,
        "candidate_mean_probability": candidate_mean,
        "current_mean_probability": current_mean,
        "market_mean_probability": market_mean,
        "candidate_minus_current": candidate_mean - current_mean,
        "candidate_minus_market": candidate_mean - market_mean,
        "candidate_over_50_rate": sum(1 for row in winners if float(row["candidate_p"]) > 0.5) / n,
        "current_over_50_rate": sum(1 for row in winners if float(row["replayed_p"]) > 0.5) / n,
        "market_over_50_rate": sum(1 for row in winners if float(row["market_yes"]) > 0.5) / n,
    }


def exact_winner_scope_comparison(label, rows):
    rows = list(rows)
    comp = candidate_comparison(rows)
    if not comp:
        return {"slice": label, "n": 0}
    current_calibration = calibration_diagnostics(rows, "replayed_p")
    market_calibration = calibration_diagnostics(rows, "market_yes")
    candidate_winner = winner_band_catchup(probability_view(rows, "candidate_p"))
    current_winner = winner_band_catchup(probability_view(rows, "replayed_p"))
    exact_winner = exact_winner_probability_summary(rows)
    return {
        "slice": label,
        **comp,
        "current_ece": current_calibration["ece"],
        "market_ece": market_calibration["ece"],
        "winner_candidate_probability": candidate_winner.get("winner_model_probability"),
        "winner_current_probability": current_winner.get("winner_model_probability"),
        "winner_market_probability": candidate_winner.get("winner_market_probability"),
        "winner_candidate_catchup_rate": candidate_winner.get("winner_catchup_rate"),
        "winner_current_catchup_rate": current_winner.get("winner_catchup_rate"),
        "exact_winner": exact_winner,
    }


def exact_winner_candidate_diagnostics(rows):
    target_markets = set(EXACT_WINNER_TARGET_MARKETS)
    scopes = [
        ("settlement_distance_0", lambda row: _distance_bucket(row) == 0),
        ("one_above_guardrail", lambda row: _distance_bucket(row) == 1),
        ("exact_band_eq", lambda row: _bin_type(row) == "eq"),
        ("cutoff_hours_07_15", lambda row: (_cutoff_hour(row) is not None and 7 <= _cutoff_hour(row) <= 15)),
        ("target_gap_markets", lambda row: row.get("market_id") in target_markets),
        (
            "combined_target_failure_slice",
            lambda row: (
                _distance_bucket(row) == 0
                and _bin_type(row) == "eq"
                and (_cutoff_hour(row) is not None and 7 <= _cutoff_hour(row) <= 15)
                and row.get("market_id") in target_markets
            ),
        ),
    ]
    scope_rows = [
        exact_winner_scope_comparison(label, [row for row in rows if predicate(row)])
        for label, predicate in scopes
    ]
    for market_id in EXACT_WINNER_TARGET_MARKETS:
        scope_rows.append(
            exact_winner_scope_comparison(
                f"target_market_{market_id}",
                [row for row in rows if row.get("market_id") == market_id],
            )
        )

    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.get("market_id"), row.get("target_date"))].append(row)
    per_day = []
    for (market_id, target_date), group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = candidate_comparison(group_rows)
        if comp:
            per_day.append({
                "group": f"{market_id}:{target_date}",
                "market_id": market_id,
                "target_date": target_date,
                **comp,
            })
    worst_days = sorted(
        per_day,
        key=lambda row: (
            row.get("delta_vs_current") if row.get("delta_vs_current") is not None else -999.0
        ),
        reverse=True,
    )[:12]
    return {
        "target_markets": list(EXACT_WINNER_TARGET_MARKETS),
        "scopes": scope_rows,
        "daily_first": daily_first_candidate_comparison(rows),
        "worst_daily_current_regressions": worst_days,
    }
