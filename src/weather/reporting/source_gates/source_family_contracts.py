"""Fail-closed contracts for source-family evidence used by promotion gates."""

from __future__ import annotations

import math
from datetime import date

from weather.backtesting.source_ablation_contract import (
    ALL_VARIANTS,
    SourceAblationContractError,
    members_for_variant,
)
from weather.backtesting.source_ablation_evidence import (
    applicable_market_ids_for_variant,
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
    slice_partition_blockers,
    summary_day_effect_blockers,
    target_date_from_day,
)
from weather.market.market_registry import REGISTRY
from weather.schema_registry import schema_version
from weather.reporting.source_gates.source_artifact_binding import (
    receipt_shape_contract,
)


OPERATIONAL_ABLATION_SCHEMA_VERSION = schema_version("source_family_ablation")
RESEARCH_ABLATION_SCHEMA_VERSION = schema_version("source_family_ablation_research")
SOURCE_FAMILY_INVENTORY_SCHEMA_VERSION = schema_version("source_family_inventory")
EXPECTED_SOURCE_FAMILY_IDS = (
    "settlement_observation",
    "forecast_baseline",
    "open_meteo_expanded",
    "nws_grid",
    "multi_model_guidance",
    "mrms_precip",
    "marine_context",
    "eccc_gridded",
    "reanalysis_synoptic",
    "nearby_station_redundancy",
    "clob_microstructure",
)
EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS = {
    "settlement_observation": ("wu_history", "wu_current", "metar", "eccc_swob"),
    "forecast_baseline": (
        "forecast_baseline",
        "all_forecasts",
        "weather_forecast",
        "open_meteo",
        "eccc_citypage",
    ),
    "open_meteo_expanded": (
        "open_meteo_expanded",
        "open_meteo",
        "open_meteo_air_quality",
    ),
    "nws_grid": (
        "official_us_guidance",
        "nws_grid",
        "nws_hourly",
        "nbm_probabilistic_tmax",
    ),
    "multi_model_guidance": (
        "multi_model_guidance",
        "open_meteo_multimodel",
        "open_meteo_global_models",
        "global_ensemble",
    ),
    "mrms_precip": ("precip_context", "mrms_precip"),
    "marine_context": ("coastal_context", "marine_context"),
    "eccc_gridded": ("eccc_gem", "toronto_official", "open_meteo_family"),
    "reanalysis_synoptic": ("reanalysis_synoptic",),
    "nearby_station_redundancy": ("nearby_station_redundancy", "source_state"),
    "clob_microstructure": ("clob_microstructure", "clob_microstructure_overlay"),
}
PROMOTION_DECISION_STATUSES = {
    "HOLD_HISTORICAL_ONLY",
    "BLOCK_LINEAGE",
    "BLOCK_PARITY",
    "BLOCK_UNSAFE_ABLATION",
    "BLOCK_MISSING_ABLATION",
    "HOLD_NO_LIFT",
    "PROMOTION_CANDIDATE",
}

if tuple(EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS) != EXPECTED_SOURCE_FAMILY_IDS:
    raise RuntimeError("source-family variant contract IDs are out of order")


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_count(value):
    return _is_count(value) and value > 0


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _is_iso_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def source_ablation_operational_contract(payload):
    """Classify whether a source-ablation artifact may inform promotion gates."""

    if not isinstance(payload, dict) or not payload:
        return {
            "status": "MISSING",
            "schema_version": None,
            "expected_schema_version": OPERATIONAL_ABLATION_SCHEMA_VERSION,
            "blockers": [],
        }
    observed_schema = payload.get("schema_version")
    blockers = []
    if observed_schema != OPERATIONAL_ABLATION_SCHEMA_VERSION:
        blockers.append(
            "schema_version must equal " + OPERATIONAL_ABLATION_SCHEMA_VERSION
        )
    if payload.get("evidence_mode") != "operational":
        blockers.append("evidence_mode must equal operational")
    if payload.get("research_only") is not False:
        blockers.append("research_only must be explicitly false")
    if payload.get("promotion_preflight_evidence_authorization") is not True:
        blockers.append("promotion_preflight_evidence_authorization must be true")
    if payload.get("include_reconstructed") is not False:
        blockers.append("include_reconstructed must be explicitly false")
    if payload.get("serving_or_release_authorization") is not False:
        blockers.append("serving_or_release_authorization must be explicitly false")
    model_binding = payload.get("model_binding")
    if not isinstance(model_binding, dict):
        blockers.append("model_binding must be an object")
        model_binding = {}
    variants = payload.get("variants")
    variant_ids = []
    rows_scored = 0
    if not isinstance(variants, list) or not variants:
        blockers.append("variants must be a non-empty list")
    else:
        for index, row in enumerate(variants):
            if not isinstance(row, dict):
                blockers.append(f"variants[{index}] must be an object")
                continue
            variant_id = row.get("variant")
            if not isinstance(variant_id, str) or not variant_id.strip():
                blockers.append(f"variants[{index}].variant must be non-empty")
            else:
                variant_ids.append(variant_id)
            row_count = row.get("n", row.get("rows"))
            if not _is_positive_count(row_count):
                blockers.append(f"variants[{index}] must have a positive integer row count")
            else:
                rows_scored += row_count
            if not _is_finite_number(row.get("delta")):
                blockers.append(f"variants[{index}].delta must be finite")
            market_days = row.get("market_days", row.get("days"))
            if not _is_positive_count(market_days):
                blockers.append(
                    f"variants[{index}] must have a positive integer market-day count"
                )
            helped = row.get(
                "market_days_source_helped", row.get("days_source_helped")
            )
            hurt = row.get(
                "market_days_source_hurt", row.get("days_source_hurt")
            )
            if not _is_count(helped) or not _is_count(hurt):
                blockers.append(
                    f"variants[{index}] help/harm market-day counts must be non-negative integers"
                )
            elif _is_positive_count(market_days) and helped + hurt > market_days:
                blockers.append(
                    f"variants[{index}] help/harm counts exceed market-day support"
                )
        if len(variant_ids) != len(set(variant_ids)):
            blockers.append("variant identifiers must be unique")
        candidate_reanalysis = (
            payload.get("evidence_source")
            == "candidate_artifact_band_ablation"
            and variant_ids == ["reanalysis_synoptic"]
            and model_binding.get("binding_kind") == "candidate_artifact"
        )
        for index, row in enumerate(variants):
            if not isinstance(row, dict):
                continue
            variant_id = row.get("variant")
            try:
                expected_members = list(members_for_variant(variant_id))
            except SourceAblationContractError:
                expected_members = (
                    ["reanalysis_synoptic"]
                    if candidate_reanalysis
                    and variant_id == "reanalysis_synoptic"
                    else None
                )
            if expected_members is None:
                blockers.append(f"variants[{index}].variant is not canonical")
            elif row.get("ablated_sources") != expected_members:
                blockers.append(
                    f"variants[{index}].ablated_sources differ from canonical membership"
                )
    requested = payload.get("requested_variants")
    if not isinstance(requested, list) or not requested:
        blockers.append("requested_variants must be a non-empty list")
    elif any(not isinstance(value, str) or not value.strip() for value in requested):
        blockers.append("requested_variants entries must be non-empty strings")
    elif len(requested) != len(set(requested)):
        blockers.append("requested_variants entries must be unique")
    elif not set(variant_ids).issubset(set(requested)):
        blockers.append("scored variants must be contained in requested_variants")
    if model_binding.get("binding_kind") == "candidate_artifact":
        if requested != ["reanalysis_synoptic"]:
            blockers.append(
                "candidate-artifact requested_variants must equal reanalysis_synoptic"
            )
        if variant_ids != ["reanalysis_synoptic"]:
            blockers.append(
                "candidate-artifact scored variants must equal reanalysis_synoptic"
            )
    elif model_binding.get("binding_kind") == "verified_active_release":
        if requested != list(ALL_VARIANTS):
            blockers.append(
                "active-release requested_variants must equal the exact ordered canonical family"
            )
        if (
            len(variant_ids) != len(set(variant_ids))
            or set(variant_ids) != set(ALL_VARIANTS)
        ):
            blockers.append(
                "active-release scored variants must exactly equal the canonical requested family"
            )
    day_effects = payload.get("day_effects")
    if not isinstance(day_effects, dict):
        blockers.append("day_effects must be an object")
        day_effects = {}
    elif set(day_effects) != set(variant_ids):
        blockers.append("day_effects keys must exactly match scored variants")
    variant_by_id = {
        row.get("variant"): row
        for row in (variants or [])
        if isinstance(row, dict) and isinstance(row.get("variant"), str)
    }
    for variant_id in variant_ids:
        day_rows = day_effects.get(variant_id)
        if not isinstance(day_rows, list) or not day_rows:
            blockers.append(f"day_effects.{variant_id} must be a non-empty list")
            continue
        expected_days = variant_by_id[variant_id].get(
            "market_days", variant_by_id[variant_id].get("days")
        )
        if _is_positive_count(expected_days) and len(day_rows) != expected_days:
            blockers.append(
                f"day_effects.{variant_id} count must match variant market-day support"
            )
        observed_days = []
        for index, row in enumerate(day_rows):
            if not isinstance(row, dict):
                blockers.append(f"day_effects.{variant_id}[{index}] must be an object")
                continue
            market_day = row.get("market_day", row.get("day"))
            if not isinstance(market_day, str) or not market_day.strip():
                blockers.append(
                    f"day_effects.{variant_id}[{index}].market_day must be non-empty"
                )
            else:
                observed_days.append(market_day)
            if not _is_positive_count(row.get("n", row.get("rows"))):
                blockers.append(
                    f"day_effects.{variant_id}[{index}] must have positive integer support"
                )
            if not _is_finite_number(row.get("delta", row.get("brier_delta"))):
                blockers.append(
                    f"day_effects.{variant_id}[{index}].delta must be finite"
                )
        if len(observed_days) != len(set(observed_days)):
            blockers.append(f"day_effects.{variant_id} market days must be unique")
    blockers.extend(
        summary_day_effect_blockers(
            variants,
            day_effects,
            label="source-ablation",
        )
    )
    slice_effects = payload.get("slice_effects")
    if not isinstance(slice_effects, list):
        blockers.append("slice_effects must be a list")
        slice_effects = []
    else:
        for index, row in enumerate(slice_effects):
            if not isinstance(row, dict):
                blockers.append(f"slice_effects[{index}] must be an object")
                continue
            if row.get("variant") not in set(variant_ids):
                blockers.append(
                    f"slice_effects[{index}].variant must reference a scored variant"
                )
            if not isinstance(row.get("slice"), str) or not row.get("slice"):
                blockers.append(f"slice_effects[{index}].slice must be non-empty")
            if not _is_positive_count(row.get("n", row.get("rows"))):
                blockers.append(
                    f"slice_effects[{index}] must have positive integer support"
                )
            if not _is_positive_count(row.get("market_days", row.get("days"))):
                blockers.append(
                    f"slice_effects[{index}] must have positive market-day support"
                )
            if not _is_finite_number(row.get("delta")):
                blockers.append(f"slice_effects[{index}].delta must be finite")
    blockers.extend(
        slice_partition_blockers(
            variants,
            day_effects,
            slice_effects,
            label="source-ablation",
        )
    )
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        blockers.append("summary must be an object")
    else:
        if summary.get("variant_count") != len(variants or []):
            blockers.append("summary.variant_count does not match variants")
        if summary.get("rows_scored") != rows_scored:
            blockers.append("summary.rows_scored does not match variant row counts")
        if not _is_positive_count(summary.get("market_days_scored")):
            blockers.append("summary.market_days_scored must be a positive integer")
        if summary.get("slice_effect_count") != len(slice_effects):
            blockers.append("summary.slice_effect_count does not match slice_effects")

    corpus = payload.get("corpus")
    corpus_target_dates = []
    corpus_market_ids = []
    if not isinstance(corpus, dict):
        blockers.append("corpus must be an object")
        corpus = {}
    else:
        if corpus.get("schema_version") != "promotion_corpus_v0.2":
            blockers.append("corpus.schema_version must equal promotion_corpus_v0.2")
        if not _is_sha256(corpus.get("manifest_sha256")):
            blockers.append("corpus.manifest_sha256 must be a 64-character hex digest")
        if not _is_sha256(corpus.get("corpus_hash")):
            blockers.append("corpus.corpus_hash must be a 64-character hex digest")
        if not _is_positive_count(corpus.get("market_day_count")):
            blockers.append("corpus.market_day_count must be a positive integer")
        if not _is_positive_count(corpus.get("snapshot_count")):
            blockers.append("corpus.snapshot_count must be a positive integer")
        if corpus.get("input_verification") != "PASS":
            blockers.append("corpus.input_verification must be PASS")
        corpus_target_dates = corpus.get("target_dates")
        if (
            not isinstance(corpus_target_dates, list)
            or len(corpus_target_dates) < 2
            or corpus_target_dates != sorted(set(corpus_target_dates))
            or any(not _is_iso_date(value) for value in corpus_target_dates)
        ):
            blockers.append(
                "corpus.target_dates must be a sorted unique list with at least two dates"
            )
            corpus_target_dates = []
        corpus_market_ids = corpus.get("market_ids")
        if (
            not isinstance(corpus_market_ids, list)
            or corpus_market_ids != sorted(REGISTRY)
        ):
            blockers.append(
                "corpus.market_ids must exactly match the market registry"
            )
            corpus_market_ids = []

    input_receipts = payload.get("input_receipts")
    if not isinstance(input_receipts, dict):
        blockers.append("input_receipts must be an object")
        input_receipts = {}
    for key, label in (
        ("corpus", "promotion corpus"),
        ("tune_dates", "tune dates"),
        ("holdout_dates", "holdout dates"),
    ):
        blockers.extend(
            receipt_shape_contract(input_receipts.get(key), label=label)[
                "blockers"
            ]
        )
    corpus_receipt = input_receipts.get("corpus")
    if isinstance(corpus_receipt, dict) and corpus:
        if corpus_receipt.get("path") != corpus.get("path"):
            blockers.append("promotion corpus receipt path differs from corpus.path")
        if corpus_receipt.get("sha256") != corpus.get("manifest_sha256"):
            blockers.append(
                "promotion corpus receipt sha256 differs from corpus.manifest_sha256"
            )

    split_dates = payload.get("split_dates")
    normalized_splits = {"tune": [], "holdout": []}
    if not isinstance(split_dates, dict) or set(split_dates) != {"tune", "holdout"}:
        blockers.append("split_dates must contain exactly tune and holdout")
    else:
        for split in ("tune", "holdout"):
            values = split_dates.get(split)
            if (
                not isinstance(values, list)
                or not values
                or values != sorted(set(values))
                or any(not _is_iso_date(value) for value in values)
            ):
                blockers.append(
                    f"split_dates.{split} must be a non-empty sorted unique list"
                )
            else:
                normalized_splits[split] = values
        if set(normalized_splits["tune"]) & set(normalized_splits["holdout"]):
            blockers.append("tune and holdout dates must be disjoint")
        if (
            corpus_target_dates
            and set(normalized_splits["tune"]) | set(normalized_splits["holdout"])
            != set(corpus_target_dates)
        ):
            blockers.append("tune and holdout dates must exactly partition corpus dates")

    market_days = payload.get("market_days")
    day_ids = []
    if not isinstance(market_days, list) or not market_days:
        blockers.append("market_days must be a non-empty list")
        market_days = []
    else:
        for index, row in enumerate(market_days):
            if not isinstance(row, dict):
                blockers.append(f"market_days[{index}] must be an object")
                continue
            day_id = row.get("market_day", row.get("day"))
            if not isinstance(day_id, str) or not day_id:
                blockers.append(
                    f"market_days[{index}] must identify a non-empty market-day"
                )
            else:
                day_ids.append(day_id)
            if row.get("settlement_source") != "daily_summary":
                blockers.append(
                    f"market_days[{index}].settlement_source must equal daily_summary"
                )
        if len(day_ids) != len(set(day_ids)):
            blockers.append("market_days identifiers must be unique")
        allocated_dates = set(normalized_splits["tune"]) | set(
            normalized_splits["holdout"]
        )
        if allocated_dates and any(
            target_date_from_day(day_id) not in allocated_dates
            for day_id in day_ids
        ):
            blockers.append("scored market-days must belong to the sealed date split")
        scored_market_ids = sorted(
            {
                str(day_id).split()[0]
                for day_id in day_ids
                if str(day_id).strip()
            }
        )
        if scored_market_ids != sorted(REGISTRY):
            blockers.append("scored market-day markets must exactly match the registry")
        expected_corpus_day_ids = {
            f"{market_id} {target_date}"
            for market_id in corpus_market_ids
            for target_date in corpus_target_dates
        }
        if set(day_ids) != expected_corpus_day_ids or len(day_ids) != len(
            expected_corpus_day_ids
        ):
            blockers.append(
                "scored market-days must exactly cover the sealed corpus market/date panel"
            )
    if isinstance(summary, dict) and summary.get("market_days_scored") != len(
        market_days
    ):
        blockers.append("summary.market_days_scored does not match market_days")
    if isinstance(summary, dict) and summary.get(
        "market_days_scored"
    ) != corpus.get("market_day_count"):
        blockers.append(
            "summary.market_days_scored does not match corpus.market_day_count"
        )
    for variant_id, rows in day_effects.items():
        expected_variant_day_ids = {
            f"{market_id} {target_date}"
            for market_id in applicable_market_ids_for_variant(variant_id)
            for target_date in corpus_target_dates
        }
        observed_day_ids = [
            str(row.get("market_day") or row.get("day") or "")
            for row in rows
            if isinstance(row, dict)
        ]
        if (
            not set(observed_day_ids).issubset(expected_variant_day_ids)
        ):
            blockers.append(
                f"day_effects.{variant_id} exceeds its sealed applicable market/date panel"
            )

    is_reanalysis_artifact_binding = (
        payload.get("evidence_source") == "candidate_artifact_band_ablation"
        and variant_ids == ["reanalysis_synoptic"]
    )
    if is_reanalysis_artifact_binding:
        blockers.append(
            "operational source-family evidence requires a "
            "verified_active_release model binding; candidate-artifact "
            "reanalysis evidence is research-only pending an independently "
            "anchored trust root"
        )
        if model_binding.get("status") != "BOUND_CANDIDATE_ARTIFACT":
            blockers.append(
                "reanalysis model_binding.status must be BOUND_CANDIDATE_ARTIFACT"
            )
        if model_binding.get("binding_kind") != "candidate_artifact":
            blockers.append(
                "reanalysis model_binding.binding_kind must be candidate_artifact"
            )
        if model_binding.get("promotion_evidence_binding") is not True:
            blockers.append(
                "reanalysis model_binding.promotion_evidence_binding must be true"
            )
        if model_binding.get("serving_or_release_authorization") is not False:
            blockers.append(
                "reanalysis model_binding.serving_or_release_authorization must be false"
            )
        if (
            not isinstance(model_binding.get("artifact_path"), str)
            or not model_binding.get("artifact_path")
        ):
            blockers.append("reanalysis model_binding.artifact_path must be non-empty")
        if not _is_sha256(model_binding.get("artifact_sha256")):
            blockers.append(
                "reanalysis model_binding.artifact_sha256 must be a 64-character hex digest"
            )
        if model_binding.get("prediction_mode") != "band_binary":
            blockers.append(
                "reanalysis model_binding.prediction_mode must equal band_binary"
            )
        artifact_receipt = input_receipts.get("artifact")
        blockers.extend(
            receipt_shape_contract(
                artifact_receipt,
                label="candidate artifact",
            )["blockers"]
        )
        if isinstance(artifact_receipt, dict):
            if artifact_receipt.get("path") != model_binding.get("artifact_path"):
                blockers.append(
                    "candidate artifact receipt path differs from model binding"
                )
            if artifact_receipt.get("sha256") != model_binding.get(
                "artifact_sha256"
            ):
                blockers.append(
                    "candidate artifact receipt sha256 differs from model binding"
                )
        artifact = payload.get("artifact")
        if not isinstance(artifact, dict):
            blockers.append("reanalysis artifact must be an object")
        else:
            expected_artifact = {
                "path": model_binding.get("artifact_path"),
                "sha256": model_binding.get("artifact_sha256"),
                "size_bytes": (
                    artifact_receipt.get("size_bytes")
                    if isinstance(artifact_receipt, dict)
                    else None
                ),
                "prediction_mode": model_binding.get("prediction_mode"),
            }
            for field, expected_value in expected_artifact.items():
                if artifact.get(field) != expected_value:
                    blockers.append(
                        f"reanalysis artifact.{field} differs from its receipt/model binding"
                    )
    else:
        if model_binding.get("binding_kind") != "verified_active_release":
            blockers.append(
                "model_binding.binding_kind must equal verified_active_release"
            )
        if model_binding.get("status") != "BOUND":
            blockers.append("model_binding.status must equal BOUND")
        for field in (
            "pointer_present",
            "base_model_bound",
            "shared_explicit_bundle",
            "shared_verified_bundle",
            "serving_or_release_authorization",
        ):
            if model_binding.get(field) is not True:
                blockers.append(f"model_binding.{field} must be true")
        if (
            not isinstance(model_binding.get("release_id"), str)
            or not model_binding.get("release_id")
        ):
            blockers.append("model_binding.release_id must be non-empty")
        for field in ("release_manifest_sha256", "release_pointer_sha256"):
            if not _is_sha256(model_binding.get(field)):
                blockers.append(
                    f"model_binding.{field} must be a 64-character hex digest"
                )
        bound_market_ids = model_binding.get("market_ids")
        if (
            not isinstance(bound_market_ids, list)
            or not bound_market_ids
            or bound_market_ids != sorted(set(bound_market_ids))
        ):
            blockers.append(
                "model_binding.market_ids must be a non-empty sorted unique list"
            )
            bound_market_ids = []
        if (
            not _is_positive_count(model_binding.get("model_count"))
            or model_binding.get("model_count") != len(bound_market_ids)
        ):
            blockers.append("model_binding.model_count must match market_ids")
        scored_market_ids = sorted(
            {str(day_id).split()[0] for day_id in day_ids if str(day_id).strip()}
        )
        if bound_market_ids and bound_market_ids != scored_market_ids:
            blockers.append("model_binding.market_ids must match scored market-days")

    robustness_contract = payload.get("robustness_contract")
    if not isinstance(robustness_contract, dict):
        blockers.append("robustness_contract must be an object")
    else:
        if robustness_contract.get("primary_market_ids") != sorted(REGISTRY):
            blockers.append(
                "robustness_contract.primary_market_ids must match the market registry"
            )
        if robustness_contract.get("outcome_independent_scope_selection") is not True:
            blockers.append(
                "robustness_contract outcome-independent scope selection must be true"
            )

    expected_paired = []
    expected_robustness = []
    expected_market = []
    try:
        expected_paired = paired_day_inference(day_effects, normalized_splits)
        expected_robustness = paired_inference_sensitivities(
            day_effects,
            market_days,
            split_dates=normalized_splits,
            required_market_ids=tuple(sorted(REGISTRY)),
        )
        expected_market = paired_market_inference(
            day_effects,
            normalized_splits,
            day_meta=market_days,
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        blockers.append(f"inference could not be recomputed: {exc}")
    else:
        if payload.get("paired_inference") != expected_paired:
            blockers.append("paired_inference differs from recomputation")
        if payload.get("robustness_inference") != expected_robustness:
            blockers.append("robustness_inference differs from recomputation")
        if payload.get("market_inference") != expected_market:
            blockers.append("market_inference differs from recomputation")
        for variant_id in variant_ids:
            for split in ("tune", "holdout"):
                row = next(
                    (
                        value
                        for value in expected_paired
                        if value.get("variant") == variant_id
                        and value.get("split") == split
                    ),
                    None,
                )
                if (
                    row is None
                    or not _is_positive_count(row.get("fleet_dates"))
                    or not _is_positive_count(row.get("market_days"))
                ):
                    blockers.append(
                        f"{variant_id}/{split} paired inference has no support"
                    )
            if not any(
                row.get("variant") == variant_id
                and row.get("split") == "holdout"
                and _is_positive_count(row.get("market_days"))
                for row in expected_market
            ):
                blockers.append(
                    f"{variant_id}/holdout market inference has no support"
                )
    return {
        "status": "BLOCK" if blockers else "PASS",
        "schema_version": observed_schema,
        "expected_schema_version": OPERATIONAL_ABLATION_SCHEMA_VERSION,
        "research_schema_version": RESEARCH_ABLATION_SCHEMA_VERSION,
        "blockers": blockers,
    }


def source_family_inventory_ablation_projection_contract(
    inventory_payload,
    ablation_payload,
):
    """Bind promotion-candidate inventory rows to exact current ablation rows."""

    blockers = []
    inventory_payload = (
        inventory_payload if isinstance(inventory_payload, dict) else {}
    )
    ablation_payload = ablation_payload if isinstance(ablation_payload, dict) else {}
    observed_contract = inventory_payload.get("ablation_evidence_contract")
    current_contract = source_ablation_operational_contract(ablation_payload)
    if observed_contract != current_contract:
        blockers.append(
            "inventory ablation evidence contract differs from current ablation"
        )
    if current_contract.get("status") != "PASS":
        blockers.append("current source-family ablation contract is not PASS")
    by_variant = {
        row.get("variant"): row
        for row in (ablation_payload.get("variants") or [])
        if isinstance(row, dict)
        and isinstance(row.get("variant"), str)
        and row.get("variant")
    }
    rows = inventory_payload.get("inventory")
    rows = rows if isinstance(rows, list) else []
    compared = 0
    for index, inventory_row in enumerate(rows):
        if not isinstance(inventory_row, dict):
            continue
        decision = inventory_row.get("promotion_decision")
        if not isinstance(decision, dict) or decision.get(
            "status"
        ) != "PROMOTION_CANDIDATE":
            continue
        compared += 1
        family_id = inventory_row.get("family_id")
        ablation = inventory_row.get("ablation")
        if not isinstance(ablation, dict):
            blockers.append(
                f"inventory[{index}] promotion candidate ablation must be an object"
            )
            continue
        if ablation.get("evidence_source") != "source_family_ablation":
            blockers.append(
                f"inventory[{index}] promotion candidate is not source-family-ablation backed"
            )
        if ablation.get("evidence_contract") != observed_contract:
            blockers.append(
                f"inventory[{index}] promotion candidate contract differs from inventory root"
            )
        canonical_variants = EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS.get(
            family_id,
            (),
        )
        variant_id = ablation.get("variant")
        if variant_id not in canonical_variants:
            blockers.append(
                f"inventory[{index}] promotion candidate variant is not canonical for its family"
            )
            continue
        source_row = by_variant.get(variant_id)
        if not isinstance(source_row, dict):
            blockers.append(
                f"inventory[{index}] promotion candidate variant is absent from current ablation"
            )
            continue
        expected = {
            "status": "PRESENT",
            "variant": variant_id,
            "settlement_scored": True,
            "rows": source_row.get("n") or source_row.get("rows"),
            "days": source_row.get("market_days", source_row.get("days")),
            "delta": source_row.get("delta"),
            "base_brier": source_row.get("base_brier"),
            "variant_brier": source_row.get("variant_brier"),
            "days_source_helped": source_row.get(
                "market_days_source_helped",
                source_row.get("days_source_helped"),
            ),
            "days_source_hurt": source_row.get(
                "market_days_source_hurt",
                source_row.get("days_source_hurt"),
            ),
            "evidence_source": "source_family_ablation",
            "evidence_contract": observed_contract,
        }
        for field, expected_value in expected.items():
            if ablation.get(field) != expected_value:
                blockers.append(
                    f"inventory[{index}] promotion candidate {field} differs from current ablation"
                )
    return {
        "status": "BLOCK" if blockers else "PASS",
        "promotion_candidate_rows_compared": compared,
        "current_ablation_contract": current_contract,
        "blockers": blockers,
    }


def source_family_inventory_integrity_contract(payload):
    """Validate current inventory provenance without requiring every gate to pass."""

    if not isinstance(payload, dict) or not payload:
        return {
            "status": "MISSING",
            "schema_version": None,
            "expected_schema_version": SOURCE_FAMILY_INVENTORY_SCHEMA_VERSION,
            "blockers": ["source-family inventory is missing"],
        }
    blockers = []
    if payload.get("serving_or_release_authorization") is not False:
        blockers.append(
            "source-family inventory serving_or_release_authorization must be false"
        )
    if payload.get("schema_version") != SOURCE_FAMILY_INVENTORY_SCHEMA_VERSION:
        blockers.append(
            f"schema_version must equal {SOURCE_FAMILY_INVENTORY_SCHEMA_VERSION}"
        )
    blockers.extend(
        receipt_shape_contract(
            payload.get("ablation_input_receipt"),
            label="source-family ablation input",
        )["blockers"]
    )
    candidate_replay_receipt = payload.get("candidate_replay_input_receipt")
    if not isinstance(candidate_replay_receipt, dict):
        blockers.append("candidate_replay_input_receipt must be an object")
        candidate_replay_receipt = {}
    elif candidate_replay_receipt.get("status") == "PASS":
        blockers.extend(
            receipt_shape_contract(
                candidate_replay_receipt,
                label="candidate replay input",
            )["blockers"]
        )
    elif not isinstance(candidate_replay_receipt.get("blockers"), list):
        blockers.append(
            "non-PASS candidate_replay_input_receipt must contain blockers"
        )
    if payload.get("candidate_replay_json") != candidate_replay_receipt.get(
        "path"
    ):
        blockers.append(
            "candidate_replay_json differs from candidate_replay_input_receipt.path"
        )
    candidate_artifact_receipt = payload.get(
        "candidate_model_artifact_input_receipt"
    )
    if not isinstance(candidate_artifact_receipt, dict):
        blockers.append(
            "candidate_model_artifact_input_receipt must be an object"
        )
        candidate_artifact_receipt = {}
    elif candidate_artifact_receipt.get("status") == "PASS":
        blockers.extend(
            receipt_shape_contract(
                candidate_artifact_receipt,
                label="candidate replay model artifact input",
            )["blockers"]
        )
    scan_closure = payload.get("scan_input_closure")
    if not isinstance(scan_closure, dict):
        blockers.append("scan_input_closure must be an object")
    elif scan_closure.get("serving_or_release_authorization") is not False:
        blockers.append(
            "scan_input_closure serving_or_release_authorization must be false"
        )
    active_model_usage = payload.get("active_model_usage")
    if not isinstance(active_model_usage, dict):
        blockers.append("active_model_usage must be an object")
        active_model_usage = {}
    usage_verification = active_model_usage.get("verification")
    if not isinstance(usage_verification, dict):
        blockers.append("active_model_usage.verification must be an object")
        usage_verification = {}
    usage_status = active_model_usage.get("status")
    feature_names = active_model_usage.get("feature_names")
    if (
        not isinstance(feature_names, list)
        or any(not isinstance(value, str) or not value for value in feature_names)
        or feature_names != sorted(set(feature_names))
    ):
        blockers.append(
            "active_model_usage.feature_names must be a sorted unique string list"
        )
        feature_names = []
    if active_model_usage.get("feature_count") != len(feature_names):
        blockers.append(
            "active_model_usage.feature_count differs from feature_names"
        )
    overlay_families = active_model_usage.get("active_overlay_families")
    if (
        not isinstance(overlay_families, list)
        or any(
            not isinstance(value, str)
            or value not in EXPECTED_SOURCE_FAMILY_IDS
            for value in overlay_families
        )
        or overlay_families != sorted(set(overlay_families))
    ):
        blockers.append(
            "active_model_usage.active_overlay_families must be a sorted "
            "unique source-family list"
        )
    if usage_verification.get("candidate_replay_receipt") != (
        candidate_replay_receipt
    ):
        blockers.append(
            "active_model_usage candidate replay receipt differs from inventory root"
        )
    if usage_verification.get("artifact_receipt") != candidate_artifact_receipt:
        blockers.append(
            "active_model_usage artifact receipt differs from inventory root"
        )
    usage_blockers = usage_verification.get("blockers")
    if not isinstance(usage_blockers, list):
        blockers.append("active_model_usage.verification.blockers must be a list")
        usage_blockers = []
    if usage_status == "PRESENT":
        if usage_verification.get("status") != "PASS" or usage_blockers:
            blockers.append(
                "PRESENT active_model_usage requires blocker-free PASS verification"
            )
        blockers.extend(
            receipt_shape_contract(
                candidate_replay_receipt,
                label="PRESENT candidate replay input",
            )["blockers"]
        )
        blockers.extend(
            receipt_shape_contract(
                candidate_artifact_receipt,
                label="PRESENT candidate model artifact input",
            )["blockers"]
        )
        if (
            active_model_usage.get("artifact_path")
            != candidate_artifact_receipt.get("path")
        ):
            blockers.append(
                "PRESENT active_model_usage artifact_path differs from its receipt"
            )
        if active_model_usage.get("error") is not None:
            blockers.append("PRESENT active_model_usage cannot contain an error")
        if (
            usage_verification.get(
                "candidate_replay_current_verification", {}
            ).get("status")
            != "PASS"
        ):
            blockers.append(
                "PRESENT active_model_usage lacks current candidate replay verification"
            )
        binding_kind = usage_verification.get("binding_kind")
        if binding_kind == "verified_active_release":
            if (
                usage_verification.get("active_release_initial", {}).get(
                    "status"
                )
                != "PASS"
                or usage_verification.get("active_release_closing", {}).get(
                    "status"
                )
                != "PASS"
            ):
                blockers.append(
                    "active-release model usage lacks opening and closing graph verification"
                )
        elif binding_kind == "candidate_artifact":
            blockers.append(
                "PRESENT active_model_usage cannot use candidate-artifact "
                "binding without an independently anchored trust root"
            )
        else:
            blockers.append(
                "PRESENT active_model_usage binding_kind is not supported"
            )
    elif usage_verification.get("status") == "PASS":
        blockers.append(
            "non-PRESENT active_model_usage cannot carry PASS verification"
        )
    rows = payload.get("inventory")
    if not isinstance(rows, list) or not rows:
        blockers.append("inventory must be a non-empty list")
        rows = []
    family_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            blockers.append(f"inventory[{index}] must be an object")
            continue
        family_id = row.get("family_id")
        if not isinstance(family_id, str) or not family_id.strip():
            blockers.append(f"inventory[{index}].family_id must be non-empty")
        else:
            family_ids.append(family_id)
    if len(family_ids) != len(set(family_ids)):
        blockers.append("inventory family identifiers must be unique")
    if set(family_ids) != set(EXPECTED_SOURCE_FAMILY_IDS):
        missing = sorted(set(EXPECTED_SOURCE_FAMILY_IDS) - set(family_ids))
        unexpected = sorted(set(family_ids) - set(EXPECTED_SOURCE_FAMILY_IDS))
        blockers.append(
            "inventory family set is incomplete or unexpected"
            + (f"; missing={','.join(missing)}" if missing else "")
            + (f"; unexpected={','.join(unexpected)}" if unexpected else "")
        )
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        blockers.append("summary must be an object")
        summary = {}
    elif summary.get("family_count") != len(rows):
        blockers.append("summary.family_count does not match inventory")
    for field, expected in {
        "active_model_usage_status": active_model_usage.get("status"),
        "active_model_feature_count": active_model_usage.get("feature_count"),
        "active_overlay_families": active_model_usage.get(
            "active_overlay_families"
        ),
    }.items():
        if summary.get(field) != expected:
            blockers.append(
                f"summary.{field} differs from active_model_usage"
            )
    ablation_contract = payload.get("ablation_evidence_contract")
    if not isinstance(ablation_contract, dict):
        blockers.append("ablation_evidence_contract must be an object")
        ablation_contract = {}
    preflight = payload.get("promotion_preflight")
    if not isinstance(preflight, dict):
        blockers.append("promotion_preflight must be an object")
        preflight = {}
    if ablation_contract.get("status") not in {"PASS", "BLOCK", "MISSING"}:
        blockers.append("source ablation evidence contract is missing or malformed")
    if not isinstance(ablation_contract.get("blockers"), list):
        blockers.append("source ablation evidence contract blockers must be a list")
    elif ablation_contract.get("status") == "PASS" and ablation_contract.get("blockers"):
        blockers.append("PASS source ablation evidence contract cannot contain blockers")
    if ablation_contract.get("expected_schema_version") != OPERATIONAL_ABLATION_SCHEMA_VERSION:
        blockers.append("source ablation evidence contract expected schema is stale or missing")
    if (
        ablation_contract.get("status") == "PASS"
        and ablation_contract.get("schema_version") != OPERATIONAL_ABLATION_SCHEMA_VERSION
    ):
        blockers.append("PASS source ablation evidence contract has the wrong schema")
    if preflight.get("ablation_evidence_contract") != ablation_contract:
        blockers.append("promotion preflight ablation contract differs from inventory root")
    blocked_families = preflight.get("blocked_families")
    blocking_rows = preflight.get("blocking_rows")
    blocking_evidence = preflight.get("blocking_evidence")
    if not isinstance(blocked_families, list):
        blockers.append("promotion_preflight.blocked_families must be a list")
        blocked_families = []
    if not isinstance(blocking_rows, list):
        blockers.append("promotion_preflight.blocking_rows must be a list")
        blocking_rows = []
    if not isinstance(blocking_evidence, list):
        blockers.append("promotion_preflight.blocking_evidence must be a list")
        blocking_evidence = []
    blocked_count = preflight.get("blocked_family_count")
    evidence_count = preflight.get("blocking_evidence_count")
    if not _is_count(blocked_count) or blocked_count != len(blocked_families):
        blockers.append("promotion_preflight.blocked_family_count is inconsistent")
    if len(blocking_rows) != len(blocked_families):
        blockers.append("promotion_preflight.blocking_rows is inconsistent")
    if not _is_count(evidence_count) or evidence_count != len(blocking_evidence):
        blockers.append("promotion_preflight.blocking_evidence_count is inconsistent")
    expected_blocking_evidence = (
        []
        if ablation_contract.get("status") == "PASS"
        else [
            {
                "artifact": "source_family_ablation",
                "status": ablation_contract.get("status") or "MISSING",
                "blockers": ablation_contract.get("blockers") or [],
            }
        ]
    )
    if blocking_evidence != expected_blocking_evidence:
        blockers.append(
            "promotion_preflight.blocking_evidence does not match the ablation contract"
        )
    expected_preflight_status = (
        "BLOCK" if (blocked_families or blocking_evidence) else "PASS"
    )
    if preflight.get("status") != expected_preflight_status:
        blockers.append("promotion_preflight.status is inconsistent with blockers")
    if payload.get("status") != preflight.get("status"):
        blockers.append("inventory status differs from promotion preflight status")
    if summary.get("blocking_family_count") != blocked_count:
        blockers.append("summary.blocking_family_count is inconsistent")
    if summary.get("ablation_evidence_contract_status") != ablation_contract.get("status"):
        blockers.append("summary ablation contract status is inconsistent")
    expected_blocked_families = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision = row.get("promotion_decision")
        if not isinstance(decision, dict):
            blockers.append(
                "promotion decision must be an object: "
                + str(row.get("family_id") or "unknown")
            )
            continue
        decision_status = decision.get("status")
        if decision_status not in PROMOTION_DECISION_STATUSES:
            blockers.append(
                "promotion decision status is missing or invalid: "
                + str(row.get("family_id") or "unknown")
            )
        model_influence = row.get("model_influence")
        if not isinstance(model_influence, bool):
            blockers.append(
                "model_influence must be boolean: "
                + str(row.get("family_id") or "unknown")
            )
            model_influence = False
        if not isinstance(row.get("configured_model_influence"), bool):
            blockers.append(
                "configured_model_influence must be boolean: "
                + str(row.get("family_id") or "unknown")
            )
        active_status = row.get("active_model_usage_status")
        if active_status == "NOT_USED_BY_ACTIVE_ARTIFACT":
            expected_model_influence = False
        elif active_status in {"ACTIVE_FEATURES", "ACTIVE_OVERLAY"} or (
            isinstance(active_status, str) and active_status.startswith("USAGE_")
        ):
            expected_model_influence = True
        else:
            expected_model_influence = None
            blockers.append(
                "active_model_usage_status is missing or invalid: "
                + str(row.get("family_id") or "unknown")
            )
        if (
            expected_model_influence is not None
            and model_influence is not expected_model_influence
        ):
            blockers.append(
                "model_influence disagrees with active_model_usage_status: "
                + str(row.get("family_id") or "unknown")
            )
        active_columns = row.get("active_model_feature_columns")
        active_count = row.get("active_model_feature_count")
        if not isinstance(active_columns, list):
            blockers.append(
                "active_model_feature_columns must be a list: "
                + str(row.get("family_id") or "unknown")
            )
        elif not _is_count(active_count) or active_count != len(active_columns):
            blockers.append(
                "active model feature count is inconsistent: "
                + str(row.get("family_id") or "unknown")
            )
        lane = row.get("artifact_lane_consistency")
        if lane is not None and not isinstance(lane, dict):
            blockers.append(
                "artifact_lane_consistency must be an object: "
                + str(row.get("family_id") or "unknown")
            )
            lane = {}
        if model_influence and (
            decision_status != "PROMOTION_CANDIDATE"
            or (
                row.get("family_id") == "reanalysis_synoptic"
                and str((lane or {}).get("status") or "").startswith("BLOCK")
            )
        ):
            expected_blocked_families.append(row.get("family_id"))
        ablation = row.get("ablation")
        if not isinstance(ablation, dict):
            blockers.append(
                "ablation must be an object: "
                + str(row.get("family_id") or "unknown")
            )
            ablation = {}
        lineage = row.get("lineage_status")
        parity = row.get("train_serve_parity_status")
        if row.get("live_only_policy") == "historical_only_not_live_serving":
            expected_decision = "HOLD_HISTORICAL_ONLY"
        elif lineage != "PASS":
            expected_decision = "BLOCK_LINEAGE"
        elif parity != "PASS":
            expected_decision = "BLOCK_PARITY"
        elif ablation.get("status") == "BLOCKED_UNSAFE_ARTIFACT":
            expected_decision = "BLOCK_UNSAFE_ABLATION"
        elif ablation.get("status") != "PRESENT":
            expected_decision = "BLOCK_MISSING_ABLATION"
        elif not _is_finite_number(ablation.get("delta")) or float(
            ablation.get("delta")
        ) <= 0:
            expected_decision = "HOLD_NO_LIFT"
        else:
            expected_decision = "PROMOTION_CANDIDATE"
        if decision_status != expected_decision:
            blockers.append(
                "promotion decision disagrees with row evidence: "
                + str(row.get("family_id") or "unknown")
            )
        if decision_status != "PROMOTION_CANDIDATE":
            continue
        if (
            ablation.get("status") != "PRESENT"
            or ablation.get("settlement_scored") is not True
            or not ablation.get("evidence_source")
        ):
            blockers.append(
                "promotion candidate lacks present settlement-scored evidence provenance: "
                + str(row.get("family_id") or "unknown")
            )
        if not _is_finite_number(ablation.get("delta")) or float(
            ablation.get("delta")
        ) <= 0:
            blockers.append(
                "promotion candidate lacks positive finite ablation lift: "
                + str(row.get("family_id") or "unknown")
            )
        if not _is_positive_count(ablation.get("rows")) or not _is_positive_count(
            ablation.get("days")
        ):
            blockers.append(
                "promotion candidate lacks positive row/day support: "
                + str(row.get("family_id") or "unknown")
            )
        evidence_contract = ablation.get("evidence_contract")
        if evidence_contract is not None and not isinstance(evidence_contract, dict):
            blockers.append(
                "promotion candidate evidence contract must be an object: "
                + str(row.get("family_id") or "unknown")
            )
            evidence_contract = {}
        if ablation.get("evidence_source") != "source_family_ablation":
            blockers.append(
                "promotion candidate must be backed by source_family_ablation: "
                + str(row.get("family_id") or "unknown")
            )
        if evidence_contract != ablation_contract:
            blockers.append(
                "promotion candidate source-ablation contract differs from inventory root: "
                + str(row.get("family_id") or "unknown")
            )
    if blocked_families != expected_blocked_families:
        blockers.append(
            "promotion_preflight.blocked_families does not match blocked inventory rows"
        )
    blocking_row_families = [
        row.get("family_id") if isinstance(row, dict) else None
        for row in blocking_rows
    ]
    if blocking_row_families != expected_blocked_families:
        blockers.append(
            "promotion_preflight.blocking_rows does not match blocked inventory rows"
        )
    return {
        "status": "BLOCK" if blockers else "PASS",
        "schema_version": payload.get("schema_version"),
        "expected_schema_version": SOURCE_FAMILY_INVENTORY_SCHEMA_VERSION,
        "serving_or_release_authorization": False,
        "blockers": blockers,
    }


def source_family_inventory_operational_contract(payload):
    """Validate a current inventory before any downstream promotion use."""

    integrity = source_family_inventory_integrity_contract(payload)
    blockers = list(integrity.get("blockers") or [])
    if not isinstance(payload, dict) or not payload:
        return {**integrity, "serving_or_release_authorization": False}
    ablation_contract = payload.get("ablation_evidence_contract")
    if not isinstance(ablation_contract, dict):
        ablation_contract = {}
    if ablation_contract.get("status") != "PASS":
        blockers.append(
            "source ablation evidence contract is not PASS: "
            + str(ablation_contract.get("status") or "MISSING")
        )
    preflight = payload.get("promotion_preflight")
    if not isinstance(preflight, dict):
        preflight = {}
    if payload.get("status") != "PASS":
        blockers.append("source-family inventory status is not PASS")
    if preflight.get("status") != "PASS":
        blockers.append("source-family promotion preflight is not PASS")
    current_inputs = payload.get("current_input_verification")
    if (
        not isinstance(current_inputs, dict)
        or current_inputs.get("status") != "PASS"
        or current_inputs.get("blockers") != []
    ):
        blockers.append(
            "source-family current input verification is missing or not PASS"
        )
    return {
        **integrity,
        "status": "BLOCK" if blockers else "PASS",
        "serving_or_release_authorization": False,
        "blockers": blockers,
    }
