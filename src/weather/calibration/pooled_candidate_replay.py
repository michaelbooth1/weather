"""Shadow replay for the pooled F-family feature-model candidate.

This is the cutover guard for Roadmap item 33. It replays the pinned promotion
corpus with the current serving model, then scores the separate pooled-F
artifact against the same settled rows as a shadow candidate. Live serving is
not changed by this module.
"""
import argparse
import csv
import hashlib
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

from weather.calibration.probability_calibration import apply_continuous_density_calibration
from weather.backtesting.backtest import (
    expected_calibration_error,
    fmt_num,
    fmt_pct,
    fmt_signed,
    group_sort_key,
    markdown_table,
    score_rows,
    winner_band_catchup,
)
from weather.model.feature_store import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, row_temp_native
from weather.reporting.location_trust import score_all_markets
from weather.market.market_microstructure_features import (
    CLOB_MODEL_FEATURE_COLUMNS,
    feature_index_for_folder,
    snapshot_band_key,
)
from weather.market.market_registry import REGISTRY
from weather.model.continuous_density import (
    band_probability_from_distribution as density_band_probability_from_distribution,
)
from weather.calibration.pooled_feature_model import (
    DEFAULT_BAND_ARTIFACT,
    add_dynamic_source_state_features,
    add_city_features,
    band_prediction_record,
    market_climate_stats,
    market_source_reliability,
    predict_band_rows_for_bundle,
    predict_density_rows_for_bundle,
    predict_rows,
)
from weather.reporting.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    entry_for_folder,
    folders_from_manifest,
    load_manifest,
)
from weather.backtesting.replay import (
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
    source_freshness_group,
)
from weather.backtesting.replay_backtest import FIDELITY_FAITHFUL_L1, run_replay_backtest
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT, folder_market_id
from weather.model.toronto_model import TorontoHighTempModel
from weather.artifacts import sha256_file, writable_artifact_path
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)

DEFAULT_OUT = Path("data") / "backtest" / "pooled_candidate_replay_report.md"
DEFAULT_JSON_OUT = Path("data") / "backtest" / "pooled_candidate_replay.json"
DEFAULT_REPLAY_REPORT = Path("data") / "backtest" / "pooled_candidate_current_replay_report.md"
DEFAULT_CASEBOOK = Path("data") / "backtest" / "disagreement_casebook.json"
DEFAULT_MICROSTRUCTURE_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl")
DEFAULT_CANDIDATE_VARIANT_OUT = Path("data") / "backtest" / "pooled_candidate_shadow_variants.csv"
DEFAULT_MICROSTRUCTURE_VARIANT_OUT = Path("data") / "backtest" / "clob_overlay_shadow_variants.csv"
DEFAULT_BRIDGE_VARIANT_OUT = Path("data") / "backtest" / "conservative_bridge_shadow_variants.csv"
MICROSTRUCTURE_SCHEMA_VERSION = "clob_microstructure_overlay_v0.2"
MICROSTRUCTURE_GATE_SCHEMA_VERSION = "clob_microstructure_taxonomy_gate_v0.1"
CONSERVATIVE_BRIDGE_SCHEMA_VERSION = "conservative_bridge_policy_v0.1"
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
    "captured_at_local",
    "range_label",
    "bin_type",
    "bin_value",
    "cutoff_hour",
]
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
        "captured_at_local": row.get("captured_at_local"),
        "range_label": row.get("range_label"),
        "bin_type": row.get("bin_type") or row.get("bin_kind"),
        "bin_value": row.get("bin_value_c") or row.get("bin_value"),
        "cutoff_hour": row.get("candidate_cutoff_hour"),
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS)
        writer.writeheader()
        writer.writerows(variant_rows)
    return str(path), len(variant_rows)


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


def write_microstructure_shadow_variants(path, rows):
    if not path:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_conservative_bridge_shadow_variants(path, rows):
    if not path:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MICROSTRUCTURE_SHADOW_VARIANT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def conservative_bridge_report(rows, variant_out_path=DEFAULT_BRIDGE_VARIANT_OUT):
    policy = apply_conservative_bridge(rows)
    policy_hash = payload_hash(policy)
    variant_rows = conservative_bridge_shadow_variant_rows(
        rows,
        candidate_artifact_hash=rows[0].get("candidate_artifact_hash") if rows else "",
        policy_hash=policy_hash,
    )
    variant_path = write_conservative_bridge_shadow_variants(variant_out_path, variant_rows)
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


def _model_for_market(models, market_id):
    if market_id not in models:
        models[market_id] = TorontoHighTempModel(market_id=market_id)
    return models[market_id]


def _climate_for_market(climates, model, market_id):
    if market_id not in climates:
        climates[market_id] = market_climate_stats(model.historical_target_cache())
    return climates[market_id]


def _source_reliability_for_market(source_reliability, spec):
    if spec.id not in source_reliability:
        source_reliability[spec.id] = market_source_reliability(spec)
    return source_reliability[spec.id]


def _record_feature_row(model, spec, climate, record, source_reliability=None):
    now = parse_built_at(record)
    if now is None:
        raise ValueError("replay record is missing a parseable built_at/captured_at_local timestamp")
    target_date = record_target_date(record)
    if target_date is not None:
        model.set_target_date(target_date)
    sources = record.get("sources") or {}
    history = model.source_data(sources, "wu_history")
    cutoff_hour = model.effective_intraday_cutoff_hour(now, history.get("rows") or [])
    features = model.extract_live_features(sources, cutoff_hour, now=now)
    current = model.source_data(sources, "wu_current")
    metar = model.source_data(sources, "metar")
    support_values = [
        features.get("high_so_far"),
        row_temp_native(current),
        row_temp_native(metar),
    ]
    observed_support = model.max_value(*support_values)
    row = {column: features.get(column) for column in FEATURE_COLUMNS}
    row["cutoff_hour"] = int(cutoff_hour)
    row["target_date"] = target_date.isoformat() if target_date else record.get("target_date")
    row["observed_support_bucket"] = model.round_half_up(observed_support)
    add_city_features(row, spec, climate, source_reliability=source_reliability)
    add_dynamic_source_state_features(row, sources=sources, captured_at=now)
    return row


def build_candidate_features(manifest, snapshots_root, family_unit):
    """Return (market_id, snapshot_id) -> feature row for candidate scoring."""
    models = {}
    climates = {}
    source_reliability = {}
    diagnostics = {
        "family_unit": family_unit,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "candidate_snapshots": 0,
        "predicted_snapshots": 0,
        "excluded_non_family_snapshots": 0,
        "missing_replay_records": 0,
        "reconstructed_excluded": 0,
        "missing_hour_models": 0,
        "feature_errors": [],
        "hour_counts": {},
    }
    include_reconstructed = bool(manifest.get("include_reconstructed"))
    features = {}

    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        entry = entry_for_folder(manifest, folder)
        pinned_ids = [str(item) for item in (entry or {}).get("snapshot_ids") or []]
        if not family_unit_matches(spec, family_unit):
            diagnostics["excluded_non_family_snapshots"] += len(pinned_ids)
            continue

        model = _model_for_market(models, market_id)
        climate = _climate_for_market(climates, model, market_id)
        reliability = _source_reliability_for_market(source_reliability, spec)
        records = index_records_by_snapshot(load_replay_records(folder))
        for snapshot_id in pinned_ids:
            record = records.get(snapshot_id)
            if not record:
                diagnostics["missing_replay_records"] += 1
                continue
            if is_reconstructed(record) and not include_reconstructed:
                diagnostics["reconstructed_excluded"] += 1
                continue
            diagnostics["candidate_snapshots"] += 1
            try:
                feature_row = _record_feature_row(model, spec, climate, record, source_reliability=reliability)
            except Exception as exc:  # noqa: BLE001 - diagnostics should survive bad rows
                if len(diagnostics["feature_errors"]) < 20:
                    diagnostics["feature_errors"].append({
                        "market_id": market_id,
                        "snapshot_id": snapshot_id,
                        "error": str(exc),
                })
                continue
            diagnostics["predicted_snapshots"] += 1
            diagnostics["hour_counts"][str(feature_row["cutoff_hour"])] = (
                diagnostics["hour_counts"].get(str(feature_row["cutoff_hour"]), 0) + 1
            )
            features[(market_id, snapshot_id)] = feature_row
    return features, diagnostics


def build_clob_feature_index(manifest, snapshots_root, family_unit, max_age_seconds=180):
    """Return band-level CLOB features keyed by replay row identity."""
    output = {}
    diagnostics = {
        "clob_feature_folders": 0,
        "clob_feature_rows": 0,
        "clob_feature_available_rows": 0,
        "clob_feature_missing_folders": 0,
    }
    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            continue
        if not (Path(folder) / "order_books_summary.csv").exists():
            diagnostics["clob_feature_missing_folders"] += 1
            continue
        folder_index = feature_index_for_folder(
            folder,
            max_age_seconds=max_age_seconds,
            market_id=market_id,
        )
        diagnostics["clob_feature_folders"] += 1
        diagnostics["clob_feature_rows"] += len(folder_index)
        diagnostics["clob_feature_available_rows"] += sum(
            1 for row in folder_index.values()
            if row.get("clob_feature_available")
        )
        output.update(folder_index)
    return output, diagnostics


def build_source_freshness_index(manifest, snapshots_root, family_unit):
    """Return (market_id, snapshot_id) -> compact source freshness group."""
    output = {}
    counts = Counter()
    diagnostics = {
        "source_freshness_snapshots": 0,
        "source_freshness_missing_records": 0,
        "source_freshness_states": {},
    }
    include_reconstructed = bool(manifest.get("include_reconstructed"))
    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            continue
        entry = entry_for_folder(manifest, folder)
        records = index_records_by_snapshot(load_replay_records(folder))
        pinned_ids = [str(item) for item in (entry or {}).get("snapshot_ids") or records.keys()]
        for snapshot_id in pinned_ids:
            record = records.get(str(snapshot_id))
            if not record:
                diagnostics["source_freshness_missing_records"] += 1
                continue
            if is_reconstructed(record) and not include_reconstructed:
                continue
            group = source_freshness_group(record)
            output[(market_id, str(snapshot_id))] = group
            counts[group] += 1
    diagnostics["source_freshness_snapshots"] = len(output)
    diagnostics["source_freshness_states"] = dict(sorted(counts.items()))
    return output, diagnostics


def build_candidate_distributions(manifest, snapshots_root, artifact):
    """Return (market_id, snapshot_id) -> pooled candidate distribution."""
    family_unit = artifact.get("family_unit") or "F"
    models_by_hour = artifact.get("models") or {}
    support = artifact.get("support")
    feature_rows, diagnostics = build_candidate_features(manifest, snapshots_root, family_unit)
    by_hour = defaultdict(list)
    for (market_id, snapshot_id), feature_row in feature_rows.items():
        hour = str(feature_row["cutoff_hour"])
        if hour not in models_by_hour:
            diagnostics["missing_hour_models"] += 1
            continue
        by_hour[hour].append((market_id, snapshot_id, feature_row))

    predictions = {}
    for hour, items in sorted(by_hour.items(), key=lambda item: int(item[0])):
        bundle = models_by_hour[hour]
        rows = [item[2] for item in items]
        distributions = predict_rows(
            bundle["model"],
            bundle["imputer"],
            bundle["feature_names"],
            rows,
            support=support,
        )
        for (market_id, snapshot_id, feature_row), distribution in zip(items, distributions):
            predictions[(market_id, snapshot_id)] = {
                "distribution": distribution,
                "cutoff_hour": feature_row["cutoff_hour"],
            }
    diagnostics["predicted_snapshots"] = len(predictions)
    return predictions, diagnostics


def attach_candidate_probabilities(replay_results, predictions, family_unit, source_freshness=None):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        snapshot_id = str(row.get("snapshot_id"))
        copy["source_freshness_state"] = (source_freshness or {}).get(
            (market_id, snapshot_id),
            "missing_source_status",
        )
        candidate = predictions.get((market_id, snapshot_id))
        if candidate:
            kind, value, value_hi = snapshot_band_key(row)
            copy["candidate_cutoff_hour"] = candidate.get("cutoff_hour")
            copy["candidate_p"] = band_probability_from_distribution(
                candidate.get("distribution"),
                kind,
                value,
                value_hi,
            )
        else:
            copy["candidate_cutoff_hour"] = None
            copy["candidate_p"] = None
        if _valid_probability(copy.get("candidate_p")):
            coverage["candidate_rows"] += 1
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)
    return rows, coverage


def attach_band_candidate_probabilities(
    replay_results,
    feature_rows,
    artifact,
    family_unit,
    clob_features=None,
    source_freshness=None,
):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    models_by_hour = artifact.get("models") or {}
    by_hour = defaultdict(list)
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        copy["candidate_p"] = None
        copy["candidate_cutoff_hour"] = None
        snapshot_id = str(row.get("snapshot_id"))
        copy["source_freshness_state"] = (source_freshness or {}).get(
            (market_id, snapshot_id),
            "missing_source_status",
        )
        feature_row = feature_rows.get((market_id, snapshot_id))
        if feature_row:
            kind, value, value_hi = snapshot_band_key(row)
            band_row = band_prediction_record(
                feature_row,
                kind,
                value,
                value_hi=value_hi,
            )
            clob_key = (market_id, snapshot_id, kind, value, value_hi)
            clob_row = (clob_features or {}).get(clob_key)
            if clob_row:
                for column in CLOB_MODEL_FEATURE_COLUMNS:
                    band_row[column] = clob_row.get(column)
                    copy[column] = clob_row.get(column)
            hour = str(band_row.get("cutoff_hour"))
            copy["candidate_cutoff_hour"] = band_row.get("cutoff_hour")
            if hour in models_by_hour:
                by_hour[hour].append((len(rows), band_row))
            else:
                coverage["missing_candidate_rows"] += 1
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)

    for hour, items in sorted(by_hour.items(), key=lambda item: int(item[0])):
        bundle = models_by_hour[hour]
        band_rows = [item[1] for item in items]
        probabilities = predict_band_rows_for_bundle(bundle, band_rows, postprocess=True)
        for (row_index, _), probability in zip(items, probabilities):
            rows[row_index]["candidate_p"] = probability

    postprocess = artifact.get("postprocess") or {}
    if postprocess.get("partition_normalization_enabled", True):
        normalize_partition_probabilities(
            rows,
            gamma=float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    if postprocess.get("current_blend_enabled", False):
        apply_current_blend_guardrail(rows, postprocess)

    candidate_rows = sum(1 for row in rows if _valid_probability(row.get("candidate_p")))
    coverage["candidate_rows"] = candidate_rows
    coverage["missing_candidate_rows"] = coverage["family_rows"] - candidate_rows
    return rows, coverage


def attach_density_candidate_probabilities(
    replay_results,
    feature_rows,
    artifact,
    family_unit,
    source_freshness=None,
):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    snapshot_rows = []
    payload_indexes = {}
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not family_unit_matches(spec, family_unit):
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        copy["candidate_p"] = None
        copy["candidate_cutoff_hour"] = None
        snapshot_id = str(row.get("snapshot_id"))
        copy["source_freshness_state"] = (source_freshness or {}).get(
            (market_id, snapshot_id),
            "missing_source_status",
        )
        feature_row = feature_rows.get((market_id, snapshot_id))
        if feature_row:
            copy["candidate_cutoff_hour"] = feature_row.get("cutoff_hour")
            key = (market_id, snapshot_id)
            if key not in payload_indexes:
                payload_indexes[key] = len(snapshot_rows)
                snapshot_rows.append(feature_row)
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)

    payloads = predict_density_rows_for_bundle(artifact, snapshot_rows)
    payload_by_snapshot = {
        key: payloads[index] if index < len(payloads) else None
        for key, index in payload_indexes.items()
    }
    for row in rows:
        if _valid_probability(row.get("candidate_p")):
            continue
        market_id = row.get("market_id")
        snapshot_id = str(row.get("snapshot_id"))
        payload = payload_by_snapshot.get((market_id, snapshot_id))
        spec = REGISTRY.get(market_id)
        if not payload or not spec:
            continue
        feature_row = feature_rows.get((market_id, snapshot_id)) or {}
        payload = apply_continuous_density_calibration(
            payload,
            artifact,
            floor_bucket=feature_row.get("observed_floor_bucket"),
            unit=spec.display_unit,
            cutoff_hour=feature_row.get("cutoff_hour"),
        )
        kind, value, value_hi = snapshot_band_key(row)
        probability = density_band_probability_from_distribution(
            payload,
            spec,
            {
                "kind": kind,
                "value": value,
                "value_hi": value_hi,
                "unit": spec.display_unit,
            },
        )
        if _valid_probability(probability):
            row["candidate_p"] = _clamp_probability(probability)
            row["candidate_density_mean_f"] = payload.get("mean_f")
            row["candidate_density_sigma_f"] = payload.get("sigma_f")

    candidate_rows = sum(1 for row in rows if _valid_probability(row.get("candidate_p")))
    coverage["candidate_rows"] = candidate_rows
    coverage["missing_candidate_rows"] = coverage["family_rows"] - candidate_rows
    return rows, coverage


def normalize_partition_probabilities(rows, gamma=1.25):
    """Normalize direct band probabilities across each snapshot's band partition."""
    gamma = max(0.1, float(gamma or 1.0))
    grouped = defaultdict(list)
    for idx, row in enumerate(rows):
        if _valid_probability(row.get("candidate_p")):
            grouped[(row.get("market_id"), row.get("snapshot_id"))].append(idx)
    for indexes in grouped.values():
        weights = [
            max(1e-12, float(rows[idx]["candidate_p"])) ** gamma
            for idx in indexes
        ]
        total = sum(weights)
        if total <= 0:
            continue
        for idx, weight in zip(indexes, weights):
            rows[idx]["candidate_p"] = weight / total
    return rows


def current_blend_alpha(row, config):
    market_alpha = config.get("current_blend_market_alpha") or {}
    market_id = row.get("market_id")
    if market_id in market_alpha:
        alpha = market_alpha[market_id]
    else:
        alpha = config.get("current_blend_default_alpha", 1.0)
    source_alpha = config.get("current_blend_source_freshness_alpha") or {}
    if source_alpha:
        source_state = row.get("source_freshness_state") or row.get("source_status_group") or "unknown"
        source_default = config.get("current_blend_source_freshness_default_alpha", 0.0)
        source_state_alpha = source_alpha.get(source_state, source_default)
        try:
            alpha = min(float(alpha), float(source_state_alpha))
        except (TypeError, ValueError):
            alpha = source_state_alpha
    try:
        return max(0.0, min(1.0, float(alpha)))
    except (TypeError, ValueError):
        return 1.0


def apply_current_blend_guardrail(rows, config):
    """Blend pooled candidate probabilities with incumbent replay probabilities."""
    for row in rows:
        if not _valid_probability(row.get("candidate_p")):
            continue
        if not _valid_probability(row.get("replayed_p")):
            continue
        alpha = current_blend_alpha(row, config)
        if alpha >= 1.0:
            continue
        candidate = _clamp_probability(row["candidate_p"])
        incumbent = _clamp_probability(row["replayed_p"])
        row["candidate_p"] = (alpha * candidate) + ((1.0 - alpha) * incumbent)
    return rows


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
    variant_path = write_microstructure_shadow_variants(variant_out_path, variant_rows)
    diagnostics["casebook_matched_rows"] = matched
    diagnostics["casebook"] = casebook_diagnostics
    diagnostics["artifact_path"] = written_artifact
    diagnostics["artifact_hash"] = microstructure_artifact_hash
    diagnostics["artifact_train_rows"] = (artifact or {}).get("train_rows")
    diagnostics["gated_overlay_rows"] = gate_counts["overlay_rows"]
    diagnostics["gated_base_rows"] = gate_counts["base_rows"]
    diagnostics["shadow_variant_rows"] = len(variant_rows)
    diagnostics["shadow_variant_path"] = variant_path
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
        },
    }


def market_verdict(comp, day_count, trust, current_tol, market_tol, min_days, min_trust):
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
        verdict, reasons = market_verdict(
            comp,
            day_count,
            trust,
            args.current_tol,
            args.market_tol,
            args.min_days,
            args.min_trust,
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
        "quality_grades": manifest.get("quality_grades"),
    }


def candidate_variant_defaults(artifact):
    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
    if prediction_mode == "continuous_density_f":
        return "pooled_continuous_density_hgb_v0_1", "pooled_continuous_density"
    return "pooled_f_candidate", "pooled_f_candidate"


def run_pooled_candidate_replay(args):
    manifest = load_manifest(args.corpus)
    artifact = load_artifact(args.artifact)
    artifact_hash = artifact.get("artifact_hash") or artifact_hash_for_path(args.artifact)
    family_unit = artifact.get("family_unit") or "F"
    prediction_mode = artifact.get("prediction_mode") or "bucket_distribution"
    default_variant_id, default_variant_family = candidate_variant_defaults(artifact)
    candidate_variant_id = getattr(args, "candidate_variant_id", None) or default_variant_id
    candidate_variant_family = getattr(args, "candidate_variant_family", None) or default_variant_family
    folders = [str(folder) for folder in folders_from_manifest(manifest, args.snapshots_root)]
    replay_results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=args.replay_report,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=bool(args.replay_report),
        corpus_manifest=manifest,
        long_job_guard_info=getattr(args, "long_job_guard_info", None),
    )
    replay_gate = replay_gate_status(
        replay_results,
        max_fidelity_l1=getattr(args, "max_fidelity_l1", FIDELITY_FAITHFUL_L1),
        require_exact_identity=getattr(args, "require_exact_identity", False),
    )
    if prediction_mode == "band_binary":
        feature_rows, diagnostics = build_candidate_features(manifest, args.snapshots_root, family_unit)
        clob_features, clob_diagnostics = build_clob_feature_index(
            manifest,
            args.snapshots_root,
            family_unit,
            max_age_seconds=args.clob_max_age_seconds,
        )
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(clob_diagnostics)
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_band_candidate_probabilities(
            replay_results,
            feature_rows,
            artifact,
            family_unit,
            clob_features=clob_features,
            source_freshness=source_freshness,
        )
    elif prediction_mode == "continuous_density_f":
        feature_rows, diagnostics = build_candidate_features(manifest, args.snapshots_root, family_unit)
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_density_candidate_probabilities(
            replay_results,
            feature_rows,
            artifact,
            family_unit,
            source_freshness=source_freshness,
        )
    else:
        predictions, diagnostics = build_candidate_distributions(manifest, args.snapshots_root, artifact)
        source_freshness, source_freshness_diagnostics = build_source_freshness_index(
            manifest,
            args.snapshots_root,
            family_unit,
        )
        diagnostics.update(source_freshness_diagnostics)
        candidate_rows, coverage = attach_candidate_probabilities(
            replay_results,
            predictions,
            family_unit,
            source_freshness=source_freshness,
        )
    for row in candidate_rows:
        row["candidate_artifact_hash"] = artifact_hash

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_by_market = {row["market"]: row for row in trust_rows}
    market_rows = _per_market(candidate_rows, trust_by_market, args)
    aggregate = candidate_comparison(candidate_rows)
    daily_first = daily_first_candidate_comparison(candidate_rows)
    by_market = grouped_candidate_comparison(candidate_rows, "market_id")
    by_hour = grouped_candidate_comparison(candidate_rows, "candidate_cutoff_hour")
    by_bin_type = grouped_candidate_comparison(candidate_rows, "bin_type")
    by_settlement_distance = grouped_candidate_comparison(candidate_rows, "settlement_distance_bucket")
    by_source_freshness = grouped_candidate_comparison(candidate_rows, "source_freshness_state")
    candidate_variant_path, candidate_variant_rows_count = write_candidate_shadow_variants(
        getattr(args, "candidate_variant_out", None),
        candidate_rows,
        variant_id=candidate_variant_id,
        variant_family=candidate_variant_family,
        uses_market_features=getattr(args, "candidate_variant_uses_market_features", False),
        is_control=getattr(args, "candidate_variant_control", False),
        artifact_hash=artifact_hash,
        postprocess_config_hash=artifact.get("schema_version") or "",
    )
    candidate_shadow_variants = None
    if candidate_variant_path:
        candidate_shadow_variants = {
            "path": candidate_variant_path,
            "rows": candidate_variant_rows_count,
            "variant_id": candidate_variant_id,
            "variant_family": candidate_variant_family,
            "uses_market_features": bool(getattr(args, "candidate_variant_uses_market_features", False)),
            "is_control": bool(getattr(args, "candidate_variant_control", False)),
        }
    postprocess = artifact.get("postprocess") or {}
    exact_winner_diagnostics = None
    if (
        postprocess.get("exact_winner_catchup_enabled")
        or "exact_winner" in str(candidate_variant_family)
    ):
        exact_winner_diagnostics = exact_winner_candidate_diagnostics(candidate_rows)
    microstructure = None
    if not getattr(args, "skip_microstructure_overlay", False):
        microstructure = microstructure_shadow_report(
            candidate_rows,
            casebook_path=getattr(args, "casebook", DEFAULT_CASEBOOK),
            artifact_path=getattr(args, "microstructure_artifact", DEFAULT_MICROSTRUCTURE_ARTIFACT),
            min_train_rows=getattr(args, "microstructure_min_train_rows", 500),
            variant_out_path=getattr(args, "microstructure_variant_out", DEFAULT_MICROSTRUCTURE_VARIANT_OUT),
            candidate_artifact_hash=artifact_hash,
        )
    conservative_bridge = conservative_bridge_report(
        candidate_rows,
        variant_out_path=getattr(args, "bridge_variant_out", DEFAULT_BRIDGE_VARIANT_OUT),
    )
    market_verdict = overall_verdict(market_rows, require_all_markets=args.require_all_markets)
    verdict = market_verdict if replay_gate["global_ok"] else "BLOCK"
    adjacent_calibration = postprocess.get("adjacent_calibration") or {}

    report = {
        "generated_at": datetime.now().isoformat(),
        "verdict": verdict,
        "candidate_market_verdict": market_verdict,
        "cutover_decision": cutover_decision(verdict),
        "artifact": {
            "path": str(args.artifact),
            "artifact_hash": artifact_hash,
            "schema_version": artifact.get("schema_version"),
            "feature_schema_version": artifact.get("feature_schema_version"),
            "family_unit": family_unit,
            "prediction_mode": prediction_mode,
            "objective": artifact.get("objective"),
            "trained_at": artifact.get("trained_at"),
            "support_min": min(artifact.get("support") or []) if artifact.get("support") else None,
            "support_max": max(artifact.get("support") or []) if artifact.get("support") else None,
            "hour_models": sorted(int(hour) for hour in (artifact.get("models") or {})),
            "adjacent_calibration_contexts": adjacent_calibration.get("context_count"),
            "current_blend_default_alpha": postprocess.get("current_blend_default_alpha"),
            "current_blend_market_alpha": postprocess.get("current_blend_market_alpha") or {},
        },
        "corpus": _manifest_summary(manifest),
        "coverage": coverage,
        "diagnostics": diagnostics,
        "replay_gate": replay_gate,
        "aggregate": aggregate,
        "daily_first": daily_first,
        "market_rows": market_rows,
        "by_market": by_market,
        "by_hour": by_hour,
        "by_bin_type": by_bin_type,
        "by_settlement_distance": by_settlement_distance,
        "by_source_freshness": by_source_freshness,
        "candidate_shadow_variants": candidate_shadow_variants,
        "exact_winner_diagnostics": exact_winner_diagnostics,
        "microstructure": microstructure,
        "conservative_bridge": conservative_bridge,
        "replay_summary": {
            "snaps_scored": replay_results.get("snaps_scored"),
            "total_rows": replay_results.get("total_rows"),
            "fidelity": replay_results.get("fidelity") or {},
            "corpus_warnings": replay_results.get("corpus_warnings") or [],
        },
        "long_job_guard": getattr(args, "long_job_guard_info", None) or {},
    }
    write_report(report, args.out)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report



try:
    from .pooled_candidate_replay_report import write_report  # noqa: E402
except ImportError:  # pragma: no cover - direct src compatibility
    from pooled_candidate_replay_report import write_report  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Replay-score the pooled F-family candidate as a shadow model.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--replay-report", default=str(DEFAULT_REPLAY_REPORT),
                        help="Current-serving replay report path. Empty string disables it.")
    parser.add_argument("--current-tol", type=float, default=0.003,
                        help="Hard-block tolerance for candidate Brier regression vs current replay.")
    parser.add_argument("--market-tol", type=float, default=0.003,
                        help="Shadow threshold for candidate Brier gap versus Polymarket.")
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK),
                        help="Disagreement casebook JSON used to score Item 38 target slices.")
    parser.add_argument("--candidate-variant-out", default="",
                        help="Item-69-compatible candidate variant CSV. Empty string disables variant export.")
    parser.add_argument("--candidate-variant-id", default=None)
    parser.add_argument("--candidate-variant-family", default=None)
    parser.add_argument("--candidate-variant-uses-market-features", action="store_true")
    parser.add_argument("--candidate-variant-control", action="store_true")
    parser.add_argument("--microstructure-artifact", default=str(DEFAULT_MICROSTRUCTURE_ARTIFACT),
                        help="Shadow CLOB overlay artifact path. Empty string disables artifact writing.")
    parser.add_argument("--microstructure-variant-out", default=str(DEFAULT_MICROSTRUCTURE_VARIANT_OUT),
                        help="Item-69-compatible CLOB overlay variant CSV. Empty string disables variant export.")
    parser.add_argument("--microstructure-min-train-rows", type=int, default=500,
                        help="Minimum rows required for each out-of-fold CLOB overlay train fold.")
    parser.add_argument("--skip-microstructure-overlay", action="store_true",
                        help="Disable the non-serving Item 38 CLOB overlay score.")
    parser.add_argument("--bridge-variant-out", default=str(DEFAULT_BRIDGE_VARIANT_OUT),
                        help="Item-69-compatible conservative bridge variant CSV. Empty string disables variant export.")
    parser.add_argument("--require-exact-identity", action="store_true",
                        help="Fail the candidate promotion gate if the corpus has no exact replay-identity canary rows.")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true",
                        help="Exit nonzero when the candidate is blocked.")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    args = parser.parse_args()
    if args.replay_report == "":
        args.replay_report = None
    if args.json_out == "":
        args.json_out = None
    if args.candidate_variant_out == "":
        args.candidate_variant_out = None
    if args.microstructure_artifact == "":
        args.microstructure_artifact = None
    if args.microstructure_variant_out == "":
        args.microstructure_variant_out = None
    if args.bridge_variant_out == "":
        args.bridge_variant_out = None

    with long_job_guard(
        "pooled_candidate_replay",
        state_path=args.long_job_state,
        lock_path=args.long_job_lock,
        priority=args.long_job_priority,
        enabled=not args.disable_long_job_guard,
        force_lock=args.force_long_job_lock,
    ) as guard:
        args.long_job_guard_info = guard
        report = run_pooled_candidate_replay(args)
    print(f"Pooled candidate replay: {report['verdict']} ({report['cutover_decision']})")
    print(f"Report written to {args.out}")
    if args.json_out:
        print(f"JSON written to {args.json_out}")
    if args.replay_report:
        print(f"Current replay report written to {args.replay_report}")
    if args.fail_on_block and report["verdict"] == "BLOCK":
        sys.exit(1)


if __name__ == "__main__":
    main()
