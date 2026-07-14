"""Neutral role map for an immutable weather-model serving contract."""

from __future__ import annotations

from typing import Any, Mapping

from weather.schema_registry import schema_version


SEMANTIC_CONTRACT_SCHEMA_VERSION = schema_version("release_semantic_contract")
CANDIDATE_LEAKAGE_AUDIT_SCHEMA_VERSION = schema_version("candidate_input_leakage_audit")
BASE_MODEL_SERVING_GRAPH_SCHEMA_VERSION = schema_version("base_model_serving_graph")

BASE_MODEL_MARKET_COMPONENT_KINDS = {
    "feature_hgb": "model",
    "feature_lr_coefficients": "model",
    "late_day_lr_coefficients": "model",
    "calibrated_weights": "calibration",
    "probability_calibration": "calibration",
    "forecast_error_model": "calibration",
    "settlement_lag_model": "calibration",
}
BASE_MODEL_SHARED_COMPONENT_ROLES = {
    "afternoon_residual_centering": "base_model.shared.afternoon_residual_centering",
    "family_secondary_artifacts": "family_secondary_calibration",
}

PRODUCTION_CANDIDATE_MODE = "production"
RESEARCH_ONLY_CANDIDATE_MODE = "research_only"
CANDIDATE_MODES = frozenset({PRODUCTION_CANDIDATE_MODE, RESEARCH_ONLY_CANDIDATE_MODE})

PRODUCTION_RELEASE_KIND = "production"
SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND = "serving_identity_bootstrap"
ACTIVE_RELEASE_KINDS = frozenset(
    {PRODUCTION_RELEASE_KIND, SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND}
)


def active_release_kind(pointer: Mapping[str, Any]) -> str:
    """Return the explicit kind, treating pre-kind pointers as production.

    Older pointers could only be created for production-capable releases, so
    the absent-field interpretation is backward-compatible and cannot turn an
    older research candidate into a serving release.
    """

    if "release_kind" not in pointer:
        return PRODUCTION_RELEASE_KIND
    return str(pointer.get("release_kind") or "")


def has_serving_identity_bootstrap_provenance(pointer: Mapping[str, Any]) -> bool:
    """Recognize bootstrap origin provenance carried across pointer changes."""

    provenance = pointer.get("release_kind_provenance")
    if not isinstance(provenance, Mapping):
        return False
    origin_release_id = str(provenance.get("origin_release_id") or "").strip()
    origin_manifest_sha = str(provenance.get("origin_manifest_sha256") or "")
    decision_sha = str(provenance.get("promotion_decision_sha256") or "")
    boundary_sha = str(provenance.get("market_day_boundary_sha256") or "")
    reviewed_by = str(provenance.get("reviewed_by") or "").strip()
    return bool(
        active_release_kind(pointer) == SERVING_IDENTITY_BOOTSTRAP_RELEASE_KIND
        and provenance.get("origin_action") == "PROMOTE"
        and provenance.get("origin_sequence") == 1
        and origin_release_id
        and len(origin_manifest_sha) == 64
        and all(character in "0123456789abcdef" for character in origin_manifest_sha)
        and len(decision_sha) == 64
        and all(character in "0123456789abcdef" for character in decision_sha)
        and len(boundary_sha) == 64
        and all(character in "0123456789abcdef" for character in boundary_sha)
        and reviewed_by
        and (
            "active_release_id" not in pointer
            or pointer.get("active_release_id") == origin_release_id
        )
        and (
            "active_manifest_sha256" not in pointer
            or pointer.get("active_manifest_sha256") == origin_manifest_sha
        )
    )

# These roles are qualification evidence, not runtime inputs. They are
# mandatory only for a production-capable candidate/release and are retained
# verbatim in the immutable release inventory for later audit and rollback.
PRODUCTION_POINT_IN_TIME_ROLE_KINDS = {
    "point_in_time_corpus": "corpus",
    "point_in_time_materialization_manifest": "contract",
    "point_in_time_validation_plan": "contract",
    "point_in_time_streaming_evaluation": "audit",
}

# Role names are stable loader-facing identifiers.  Paths may change between
# releases, but a runtime must bind every serving role to the exact verified
# file declared by the immutable manifest.
SEMANTIC_SERVING_ROLE_KINDS = {
    "pooled_band_model": "model",
    "family_secondary_calibration": "calibration",
    "artifact_registry": "registry",
    "model_variant_registry": "registry",
    "locations_config": "config",
    "location_market_events_config": "config",
    "markets_config": "config",
    "market_route_table": "route",
    "base_model_serving_graph": "route",
    "pooled_feature_schema": "feature_schema",
    "pooled_imputer_metadata": "imputer",
    "pooled_calibrator_metadata": "calibration",
    "pooled_postprocessor_metadata": "postprocessor",
    "settlement_rules": "settlement_rules",
    "training_evaluation_corpus": "corpus",
    "candidate_input_leakage_audit": "audit",
    "semantic_serving_contract": "contract",
}

SERVING_ARTIFACT_KINDS = frozenset(
    {
        "model",
        "calibration",
        "config",
        "imputer",
        "feature_schema",
        "postprocessor",
        "route",
        "registry",
        "settlement_rules",
    }
)

REQUIRED_SEMANTIC_ARTIFACT_KINDS = frozenset(SEMANTIC_SERVING_ROLE_KINDS.values())
