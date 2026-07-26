"""Input loading, gating, and scorecard helpers for daily learning."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from weather.experiment_contract import (
    TERMINAL_DISPOSITIONS,
    ExperimentContractError,
    finalize_self_hash,
    verify_automatic_experiment_queue,
    verify_experiment_manifest,
    verify_experiment_result,
    verify_materialized_experiment_manifest,
)
from weather.io import (
    pretty_json_root_is_closed,
    read_json,
    read_jsonl,
    read_pretty_json_object_values,
    read_pretty_json_top_level_values,
)
from weather.paths import data_path
from weather.reporting.daily import daily_rollup_freshness
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("daily_learning")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "daily_learning.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_learning_report.md"

ARTIFACT_FILES = {
    "daily_refresh_status": "daily_refresh_status.json",
    "ingest_quality_gate": "ingest_quality_gate.json",
    "promotion_refresh": "f_family_promotion_refresh.json",
    "hourly_model_performance": "hourly_model_performance.json",
    "ten_minute_model_performance": "ten_minute_model_performance.json",
    "price_free_model_learning": "price_free_model_learning.json",
    "candidate_replay": "pooled_candidate_replay_latest.json",
    "shadow_ab_monitor": "shadow_ab_monitor.json",
    "model_variant_evidence_growth": "model_variant_evidence_growth.json",
    "progress_audit": "progress_audit.json",
    "disagreement_casebook": "disagreement_casebook.json",
    "model_market_disagreement_analysis": "model_market_disagreement_analysis.json",
    "event_metadata_validation": "event_metadata_validation.json",
    "fleet_observability": "fleet_observability.json",
    "data_layer_audit": "data_layer_audit.json",
    "snapshot_evaluation": "snapshot_evaluation.json",
    "settled_day_root_cause": "settled_day_root_cause.json",
    "settled_day_freshness": "settled_day_freshness.json",
    "settled_day_analysis_barrier": "settled_day_analysis_barrier.json",
    "source_family_inventory": "source_family_inventory.json",
    "proper_scoring_reliability_scorecard": "proper_scoring_reliability_scorecard.json",
    "winner_rank_parity": "winner_rank_parity.json",
    "taker_finalization_watchdog": "taker_finalization_watchdog.json",
    "taker_tail_casebook": "taker_tail_casebook.json",
    "trading_evidence": "trading_evidence.json",
    "june23_location_bias_repair": "june23_location_bias_repair_packet.json",
    "experiment_queue_results": "experiment_queue_results.json",
}
ARTIFACT_FALLBACK_GLOBS = {
    "settled_day_root_cause": ("settled_day_root_cause_*.json",),
}
PRICE_FREE_SUMMARY_FIELDS = (
    "schema_version",
    "generated_at_utc",
    "status",
    "evidence_classification",
    "overall",
    "daily_summary",
    "last_scored_target_date",
    "latest_settled_label_date",
    "scoring_liveness",
)
PRICE_FREE_CORPUS_FIELDS = (
    "selected_label_count",
    "scored_market_days",
    "markets",
    "date_min",
    "date_max",
    "all_snapshot_rows",
    "hourly_checkpoint_rows",
    "price_free_reason_counts",
    "skipped_labels",
)
PRICE_FREE_CURRENT_MAX_FIELDS = (
    "summary",
    "by_market_hour",
    "examples",
    "focused_row_count",
    "focus_definition",
)
PRICE_FREE_LEGACY_FALLBACK_MAX_BYTES = 16 * 1024 * 1024
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
IMPACT_SORT_KEYS = (
    "estimated_impact",
    "impact",
    "impact_score",
    "excess_brier_rows",
    "delta_vs_market",
    "delta_vs_current",
    "code_effect",
    "net_pnl_usdc",
    "pnl_at_risk_usdc",
    "market_gap",
    "blocked_market_count",
    "affected_market_count",
    "row_count",
    "rows",
    "count",
)
PROMOTION_MIN_INDEPENDENT_MARKET_DAYS = 30
PROMOTION_BOOTSTRAP_RESAMPLES = 1000
PROMOTION_CI_LEVEL = 0.95
CALIBRATION_ECE_DRIFT_THRESHOLD = 0.02
CALIBRATION_BIAS_DRIFT_THRESHOLD = 0.5
INPUT_FRESHNESS_MAX_SKEW_HOURS = 18.0
INPUT_CONSISTENCY_BRIER_TOLERANCE = 1e-6
EXPERIMENT_QUEUE_MAX_ITEMS = 20
EXPERIMENT_QUEUE_RETRAIN_INPUT_LIMIT = 12
RETRAIN_CORPUS_GROWTH_MARKET_DAYS = 1
CRITICAL_INPUTS = (
    "daily_refresh_status",
    "promotion_refresh",
    "snapshot_evaluation",
    "event_metadata_validation",
    "fleet_observability",
    "data_layer_audit",
    "trading_evidence",
    "settled_day_analysis_barrier",
    "model_market_disagreement_analysis",
)
COUNTABLE_LABEL_CORPUS_SKIP_REASONS = {
    "feature_quality_quarantine_excluded",
    "too_few_replay_inputs",
}


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_int(value):
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _priority_rank(value):
    return PRIORITY_ORDER.get(str(value or "P2").upper(), PRIORITY_ORDER["P2"])


def _impact_score(row):
    values = []
    for key in IMPACT_SORT_KEYS:
        value = maybe_float((row or {}).get(key))
        if value is not None:
            values.append(abs(value))
    return max(values) if values else 0.0


def _estimated_impact(evidence):
    if isinstance(evidence, dict):
        return round(_impact_score(evidence), 6)
    return 0.0


def _rank_learnings(learnings):
    indexed = list(enumerate(learnings or []))
    indexed.sort(
        key=lambda item: (
            _priority_rank(item[1].get("priority")),
            -maybe_float(item[1].get("estimated_impact") or 0.0),
            item[0],
        )
    )
    return [row for _index, row in indexed]


def _stable_id(*parts):
    text = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _status_from_queue_result(result):
    if not result:
        return None
    disposition = result.get("disposition")
    if disposition in TERMINAL_DISPOSITIONS:
        return disposition
    status = result.get("resolution_status") or result.get("experiment_status") or result.get("status")
    if status in TERMINAL_DISPOSITIONS:
        return status
    if status in {"failed", "blocked", "executed", "recorded", "still_open"}:
        return "regressed" if status == "failed" else "inconclusive"
    return "inconclusive"


def _queue_results_by_id(results_payload):
    results = {}
    for index, row in enumerate((results_payload or {}).get("results") or []):
        if not isinstance(row, dict):
            raise ExperimentContractError(
                f"experiment_queue_results.results[{index}] must be an object"
            )
        queue_id = row.get("queue_id")
        if queue_id:
            queue_id = str(queue_id)
            if queue_id in results:
                raise ExperimentContractError(
                    f"duplicate experiment result queue_id: {queue_id}"
                )
            results[queue_id] = row
    return results


def _apply_queue_result(item, results_by_id):
    result = results_by_id.get(str(item.get("queue_id") or ""))
    if not result:
        return item
    manifest = item.get("experiment_manifest")
    try:
        verified = verify_experiment_result(result, manifest=manifest)
    except (ExperimentContractError, TypeError, ValueError) as exc:
        return {
            **item,
            "status": "ineligible_invalid_result",
            "eligible": False,
            "materialized_executable": False,
            "command": [],
            "argv": [],
            "last_result": {
                "contract_status": "LEGACY_OR_INVALID",
                "contract_error": str(exc),
                "claimed_status": result.get("status"),
                "claimed_resolution_status": result.get("resolution_status"),
                "claimed_disposition": result.get("disposition"),
                "returncode": result.get("returncode"),
                "executed_at_utc": result.get("executed_at_utc"),
                "result_artifact": result.get("result_artifact"),
                "detail": result.get("detail"),
            },
        }
    return {
        **item,
        "status": verified["disposition"],
        "eligible": False,
        "command": [],
        "argv": [],
        "last_result": {
            "contract_status": "PASS",
            "schema_version": verified["schema_version"],
            "result_sha256": verified["result_sha256"],
            "disposition": verified["disposition"],
            "disposition_reason": verified["disposition_reason"],
            "returncode": verified.get("returncode"),
            "finished_at_utc": verified["finished_at_utc"],
        },
    }


def _with_experiment_contract(
    base,
    raw_manifest,
    *,
    legacy_command,
    repo_root=None,
):
    legacy = {
        "hypothesis": base.get("hypothesis"),
        "artifact_path": base.get("artifact_path"),
        "clearance_rule": base.get("clearance_rule"),
        "command": legacy_command,
        "status": base.get("status"),
    }
    try:
        manifest = verify_experiment_manifest(raw_manifest)
        if manifest["queue_id"] != base["queue_id"]:
            raise ExperimentContractError(
                "experiment manifest queue_id disagrees with the source queue_id"
            )
    except (ExperimentContractError, TypeError, ValueError) as exc:
        return {
            **base,
            "status": "ineligible_incomplete_contract",
            "eligible": False,
            "contract_eligible": False,
            "contract_status": "BLOCK",
            "materialized_executable": False,
            "materialization_status": "NOT_EVALUATED",
            "materialization_blockers": ["structural experiment contract is invalid"],
            "command": [],
            "argv": [],
            "experiment_manifest": raw_manifest if isinstance(raw_manifest, dict) else None,
            "manifest_sha256": (
                raw_manifest.get("manifest_sha256") if isinstance(raw_manifest, dict) else None
            ),
            "owner": None,
            "candidate_output_root": None,
            "eligibility": {
                "status": "INELIGIBLE",
                "reason": "missing_or_invalid_executable_experiment_manifest",
                "blockers": [str(exc)],
            },
            "legacy": legacy,
        }
    materialization_blockers = []
    if repo_root is None:
        materialization_blockers.append(
            "explicit repo_root is required for materialized executable verification"
        )
    else:
        try:
            verify_materialized_experiment_manifest(
                manifest,
                repo_root=repo_root,
            )
        except (ExperimentContractError, OSError, TypeError, ValueError) as exc:
            materialization_blockers.append(str(exc))
    if materialization_blockers:
        return {
            **base,
            "hypothesis": manifest["hypothesis"],
            "status": "ineligible_unmaterialized_contract",
            "eligible": False,
            "contract_eligible": True,
            "contract_status": "PASS",
            "materialized_executable": False,
            "materialization_status": "BLOCK",
            "materialization_blockers": materialization_blockers,
            "command": [],
            "argv": [],
            "manifest_argv": list(manifest["argv"]),
            "experiment_manifest": manifest,
            "manifest_sha256": manifest["manifest_sha256"],
            "owner": manifest["owner"],
            "candidate_output_root": manifest["candidate_output_root"],
            "eligibility": {
                "status": "INELIGIBLE",
                "reason": "materialized_experiment_contract_not_verified",
                "blockers": materialization_blockers,
            },
            "legacy": legacy,
        }
    return {
        **base,
        "hypothesis": manifest["hypothesis"],
        "status": "queued",
        "eligible": True,
        "contract_eligible": True,
        "contract_status": "PASS",
        "materialized_executable": True,
        "materialization_status": "PASS",
        "materialization_blockers": [],
        "command": list(manifest["argv"]),
        "argv": list(manifest["argv"]),
        "experiment_manifest": manifest,
        "manifest_sha256": manifest["manifest_sha256"],
        "owner": manifest["owner"],
        "candidate_output_root": manifest["candidate_output_root"],
        "eligibility": {
            "status": "ELIGIBLE",
            "reason": "verified_executable_experiment_manifest",
            "blockers": [],
        },
        "legacy": legacy,
    }


def _queue_item_from_learning(
    row,
    index,
    *,
    generated_at_utc,
    repo_root=None,
):
    evidence = row.get("evidence") or {}
    slice_name = first_present(
        evidence.get("slice"),
        evidence.get("gate"),
        row.get("category"),
        "daily_learning",
    )
    group = evidence.get("group")
    if group not in (None, "") and str(group) not in str(slice_name):
        slice_name = f"{slice_name}={group}"
    hypothesis = first_present(
        evidence.get("next_experiment"),
        row.get("action"),
        row.get("signal"),
        "Inspect and replay this retrain input.",
    )
    artifact_path = first_present(
        evidence.get("experiment_artifact"),
        evidence.get("artifact_path"),
        evidence.get("path"),
        "",
    )
    clearance_rule = first_present(
        evidence.get("clearance_rule"),
        "Must improve the queued slice without regressing protected promotion gates.",
    )
    raw_manifest = evidence.get("experiment_manifest")
    manifest_queue_id = (
        raw_manifest.get("queue_id") if isinstance(raw_manifest, dict) else None
    )
    queue_id = (
        evidence.get("queue_id")
        or manifest_queue_id
        or f"daily:{_stable_id(row.get('source'), row.get('category'), slice_name, hypothesis)}"
    )
    explicit_command = evidence.get("experiment_command") or evidence.get("command")
    base = {
        "queue_id": queue_id,
        "source": row.get("source"),
        "category": row.get("category"),
        "slice": str(slice_name),
        "hypothesis": str(hypothesis),
        "artifact_path": str(artifact_path),
        "clearance_rule": str(clearance_rule),
        "status": "queued",
        "priority": row.get("priority") or "P2",
        "estimated_impact": row.get("estimated_impact"),
        "created_at_utc": generated_at_utc,
        "source_learning_index": index,
    }
    return _with_experiment_contract(
        base,
        raw_manifest,
        legacy_command=explicit_command,
        repo_root=repo_root,
    )


def _queue_item_from_manifest(row, *, generated_at_utc, repo_root=None):
    manifest_status = row.get("status") or "queued"
    if manifest_status == "eligible":
        status = "queued"
    elif manifest_status == "blocked_missing_case":
        status = "blocked_missing_evidence"
    else:
        status = manifest_status
    raw_manifest = row.get("experiment_manifest")
    manifest_queue_id = (
        raw_manifest.get("queue_id") if isinstance(raw_manifest, dict) else None
    )
    base = {
        "queue_id": (
            row.get("queue_id")
            or manifest_queue_id
            or f"item301:{_stable_id(row.get('market_id'), row.get('slice'))}"
        ),
        "source": row.get("source") or "june23_location_bias_repair_packet",
        "category": "june23_location_bias_repair",
        "slice": row.get("slice") or row.get("market_id") or "june23_location_bias_repair",
        "hypothesis": row.get("hypothesis") or "Replay June 23 location-bias repair candidate.",
        "artifact_path": row.get("artifact_path") or "",
        "clearance_rule": row.get("clearance_rule") or "Must pass protected-location preservation and normal promotion gates.",
        "status": status,
        "priority": row.get("priority") or "P1",
        "estimated_impact": row.get("estimated_impact"),
        "created_at_utc": generated_at_utc,
        "market_id": row.get("market_id"),
        "target_date": row.get("target_date"),
        "repair_family": row.get("repair_family"),
    }
    return _with_experiment_contract(
        base,
        raw_manifest,
        legacy_command=row.get("command"),
        repo_root=repo_root,
    )


def _build_experiment_queue(
    learnings,
    payloads,
    artifacts,
    *,
    generated_at_utc,
    run_date=None,
    repo_root=None,
):
    results_by_id = _queue_results_by_id(payloads.get("experiment_queue_results") or {})
    items = []
    june23 = payloads.get("june23_location_bias_repair") or {}
    for manifest in june23.get("experiment_queue_items") or june23.get("repair_manifests") or []:
        items.append(
            _queue_item_from_manifest(
                manifest,
                generated_at_utc=generated_at_utc,
                repo_root=repo_root,
            )
        )
    retrain_rows = [
        (index, row)
        for index, row in enumerate(learnings or [])
        if row.get("retrain_input") and not row.get("blocker")
    ]
    retrain_rows.sort(
        key=lambda item: (
            _priority_rank(item[1].get("priority")),
            -maybe_float(item[1].get("estimated_impact") or 0.0),
            item[0],
        )
    )
    for index, row in retrain_rows[:EXPERIMENT_QUEUE_RETRAIN_INPUT_LIMIT]:
        items.append(
            _queue_item_from_learning(
                row,
                index,
                generated_at_utc=generated_at_utc,
                repo_root=repo_root,
            )
        )

    deduped = {}
    for item in items:
        queue_id = str(item.get("queue_id") or _stable_id(item.get("source"), item.get("slice"), item.get("hypothesis")))
        item["queue_id"] = queue_id
        if queue_id in deduped:
            raise ExperimentContractError(
                f"duplicate experiment queue_id: {queue_id}"
            )
        deduped[queue_id] = item
    ranked = sorted(
        (_apply_queue_result(item, results_by_id) for item in deduped.values()),
        key=lambda item: (
            _priority_rank(item.get("priority")),
            item.get("eligible") is not True,
            -maybe_float(item.get("estimated_impact") or 0.0),
            str(item.get("queue_id")),
        ),
    )[:EXPERIMENT_QUEUE_MAX_ITEMS]
    eligible = [
        item for item in ranked
        if item.get("eligible") is True and item.get("status") == "queued"
    ]
    results_record = artifacts.get("experiment_queue_results") or {}
    verified_terminal = [
        item
        for item in ranked
        if ((item.get("last_result") or {}).get("contract_status") == "PASS")
        and item.get("status") in TERMINAL_DISPOSITIONS
    ]
    blocked = [
        item
        for item in ranked
        if item.get("eligible") is not True and item not in verified_terminal
    ]
    queue = {
        "schema_version": schema_version("automatic_experiment_queue"),
        "generated_at_utc": generated_at_utc,
        "run_date": str(run_date or "")[:10],
        "status": "READY" if eligible else "EMPTY",
        "eligibility_contract": {
            "policy": "verified_materialized_experiment_manifest_only",
            "structural_contract_is_not_executable": True,
            "operational_execution_claimed": False,
            "legacy_entries_visible": True,
            "legacy_entries_eligible": False,
            "commands_or_hashes_inferred": False,
            "terminal_dispositions": sorted(TERMINAL_DISPOSITIONS),
        },
        "items": ranked,
        "summary": {
            "queue_count": len(ranked),
            "eligible_count": len(eligible),
            "contract_eligible_count": sum(
                1 for item in ranked if item.get("contract_eligible") is True
            ),
            "materialized_executable_count": len(eligible),
            "ineligible_count": len(blocked),
            "blocked_count": len(blocked),
            "verified_terminal_count": len(verified_terminal),
            "legacy_or_invalid_result_count": sum(
                1
                for item in ranked
                if (item.get("last_result") or {}).get("contract_status")
                == "LEGACY_OR_INVALID"
            ),
            **{
                f"{disposition}_count": sum(
                    1 for item in verified_terminal if item.get("status") == disposition
                )
                for disposition in sorted(TERMINAL_DISPOSITIONS)
            },
            "still_open_count": len(eligible),
            "item301_count": sum(1 for item in ranked if item.get("category") == "june23_location_bias_repair"),
        },
        "results_artifact": {
            "path": results_record.get("path"),
            "exists": bool(results_record.get("exists")),
            "generated_at_utc": results_record.get("generated_at_utc"),
        },
    }
    finalized = finalize_self_hash(queue, hash_field="queue_sha256")
    return verify_automatic_experiment_queue(finalized, repo_root=repo_root)


def _capped_sorted_rows(rows, limit, source, truncated_sources=None, priority_func=None):
    indexed = list(enumerate(rows or []))
    indexed.sort(
        key=lambda item: (
            _priority_rank(priority_func(item[1]) if priority_func else item[1].get("priority")),
            -_impact_score(item[1]),
            item[0],
        )
    )
    total = len(indexed)
    if truncated_sources is not None and total > limit:
        truncated_sources.append({
            "source": source,
            "limit": limit,
            "total_count": total,
            "dropped_count": total - limit,
        })
    return [row for _index, row in indexed[:limit]]


def _count_summary(counts):
    counts = counts or {}
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "-"


def _artifact_record(name, path, payload):
    status = None
    if isinstance(payload, dict):
        raw_status = payload.get("status")
        if isinstance(raw_status, dict):
            status = raw_status.get("status")
        else:
            status = raw_status
    target_date = None
    if isinstance(payload, dict):
        corpus = payload.get("corpus") or {}
        liveness = payload.get("scoring_liveness") or {}
        rehydration = payload.get("rehydration") or {}
        candidates = (
            payload.get("target_date"),
            payload.get("run_date"),
            corpus.get("date_max"),
            liveness.get("last_scored_target_date"),
            rehydration.get("target_date"),
        )
        target_date = next((str(value)[:10] for value in candidates if value not in (None, "")), None)
    return {
        "name": name,
        "path": str(path),
        "exists": payload is not None,
        "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
        "generated_at_utc": payload.get("generated_at_utc") if isinstance(payload, dict) else None,
        "status": status,
        "target_date": target_date,
    }


def _latest_matching_artifact(root, pattern):
    candidates = [path for path in Path(root).glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def _load_artifact(root, name, filename):
    path = Path(root) / filename
    if name == "price_free_model_learning":
        payload = _load_price_free_model_learning(path)
    else:
        payload = read_json(path, default=None)
    if payload is not None:
        return path, payload
    for pattern in ARTIFACT_FALLBACK_GLOBS.get(name, ()):
        fallback_path = _latest_matching_artifact(root, pattern)
        if fallback_path is None:
            continue
        payload = read_json(fallback_path, default=None)
        if payload is not None:
            return fallback_path, payload
    return path, None


def _load_price_free_model_learning(path):
    """Read only bounded scorecard fields from the growing v0.1 artifact."""

    path = Path(path)
    if not path.exists():
        return None
    payload = read_pretty_json_top_level_values(path, PRICE_FREE_SUMMARY_FIELDS)
    required = {"schema_version", "status", "daily_summary"}
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if (
        pretty_json_root_is_closed(path)
        and required <= payload.keys()
        and payload.get("schema_version") == "price_free_model_learning_v0.1"
    ):
        corpus = read_pretty_json_object_values(
            path,
            "corpus",
            PRICE_FREE_CORPUS_FIELDS,
        )
        current_max = read_pretty_json_object_values(
            path,
            "current_max_carryover",
            PRICE_FREE_CURRENT_MAX_FIELDS,
        )
        if (
            {"scored_market_days", "hourly_checkpoint_rows"} <= corpus.keys()
            and current_max
        ):
            payload["corpus"] = corpus
            payload["current_max_carryover"] = current_max
            return payload
    # Small historical/unit-test artifacts may be compact JSON rather than the
    # canonical pretty format. Preserve that compatibility without permitting
    # an unbounded whole-file fallback for a growing production artifact.
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= PRICE_FREE_LEGACY_FALLBACK_MAX_BYTES:
        return read_json(path, default=None)
    return None


def _market_day_labels_summary(path):
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "exists": False}
    quality_counts = Counter()
    reconciliation_counts = Counter()
    settlement_source_counts = Counter()
    material_coverage_counts = Counter()
    countable_by_quality_grade = Counter()
    total = 0
    material_available = False
    promotion_countable_count = 0
    promotion_blocked_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("event_slug"):
                continue
            total += 1
            quality_counts[str(row.get("quality_grade") or "missing")] += 1
            reconciliation_counts[str(row.get("reconciliation_status") or "missing")] += 1
            settlement_source_counts[str(row.get("settlement_source") or "missing")] += 1
            material_grade = row.get("material_coverage_grade")
            if material_grade:
                material_available = True
                material_coverage_counts[str(material_grade)] += 1
            if "promotion_countable" in row and row.get("promotion_countable") != "":
                if str(row.get("promotion_countable")).strip().lower() in {"1", "true", "yes", "y"}:
                    promotion_countable_count += 1
                    countable_by_quality_grade[str(row.get("quality_grade") or "missing")] += 1
                else:
                    promotion_blocked_count += 1
    return {
        "path": str(path),
        "exists": True,
        "total_all": total,
        "quality_counts": dict(sorted(quality_counts.items())),
        "countable_by_quality_grade": dict(sorted(countable_by_quality_grade.items())),
        "reconciliation_counts": dict(sorted(reconciliation_counts.items())),
        "settlement_source_counts": dict(sorted(settlement_source_counts.items())),
        "material_coverage_counts": dict(sorted(material_coverage_counts.items())),
        "promotion_countability_available": material_available,
        "promotion_countable_label_count": promotion_countable_count,
        "promotion_blocked_label_count": promotion_blocked_count,
    }


def load_inputs(backtest_root=DEFAULT_BACKTEST_ROOT):
    root = Path(backtest_root)
    payloads = {}
    artifacts = {}
    for name, filename in ARTIFACT_FILES.items():
        path, payload = _load_artifact(root, name, filename)
        payloads[name] = payload or {}
        artifacts[name] = _artifact_record(name, path, payload)
    ledger_path = root / "daily_progress_ledger.jsonl"
    ledger_rows = read_jsonl(ledger_path)
    payloads["daily_progress_ledger"] = ledger_rows
    artifacts["daily_progress_ledger"] = {
        "name": "daily_progress_ledger",
        "path": str(ledger_path),
        "exists": bool(ledger_rows),
        "schema_version": ledger_rows[-1].get("schema_version") if ledger_rows else None,
        "generated_at_utc": ledger_rows[-1].get("generated_at_utc") if ledger_rows else None,
        "status": "OK" if ledger_rows else None,
        "row_count": len(ledger_rows),
    }
    payloads["market_day_labels"] = _market_day_labels_summary(root / "market_day_labels.csv")
    return payloads, artifacts


def _parse_timestamp(value):
    return daily_rollup_freshness.parse_timestamp(value)


def _parse_run_date(value):
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _coerce_in_memory_daily_refresh_input(payloads, artifacts, daily_refresh_summary, generated_at_utc):
    if not daily_refresh_summary:
        return
    payloads["daily_refresh_status"] = {
        **(payloads.get("daily_refresh_status") or {}),
        "generated_at_utc": generated_at_utc,
        "status": "in_progress",
        "summary": daily_refresh_summary,
    }
    record = artifacts.get("daily_refresh_status") or {}
    artifacts["daily_refresh_status"] = {
        **record,
        "name": "daily_refresh_status",
        "exists": True,
        "generated_at_utc": generated_at_utc,
        "status": "in_progress",
        "source": "daily_refresh_summary",
    }


def _input_gate_status(*statuses):
    flat = []
    for status in statuses:
        if isinstance(status, (list, tuple, set)):
            flat.extend(status)
        else:
            flat.append(status)
    if any(status == "FAIL" for status in flat):
        return "FAIL"
    if any(status == "WARN" for status in flat):
        return "WARN"
    return "PASS"


def _freshness_rows(artifacts, *, run_date, max_skew_hours, critical_inputs):
    run_day = _parse_run_date(run_date)
    valid_rows = []
    for name, record in sorted((artifacts or {}).items()):
        timestamp = _parse_timestamp((record or {}).get("generated_at_utc"))
        if timestamp is not None and (record or {}).get("exists"):
            valid_rows.append((name, timestamp))
    newest_name = None
    newest_dt = None
    if valid_rows:
        newest_name, newest_dt = max(valid_rows, key=lambda item: item[1])

    rows = []
    stale_inputs = []
    critical_stale_inputs = []
    invalid_timestamp_inputs = []
    missing_timestamp_inputs = []
    for name, record in sorted((artifacts or {}).items()):
        record = record or {}
        exists = bool(record.get("exists"))
        generated_raw = record.get("generated_at_utc")
        generated_dt = _parse_timestamp(generated_raw)
        artifact_target_day = _parse_run_date(record.get("target_date"))
        target_date_aligned = bool(run_day is not None and artifact_target_day == run_day)
        reasons = []
        skew_hours = None
        run_date_delta_days = None
        status = "PASS"
        if not exists:
            status = "MISSING"
            reasons.append("artifact_missing")
        elif generated_raw in (None, ""):
            status = "TIMESTAMP_MISSING"
            reasons.append("generated_at_utc_missing")
            missing_timestamp_inputs.append(name)
        elif generated_dt is None:
            status = "TIMESTAMP_INVALID"
            reasons.append("generated_at_utc_invalid")
            invalid_timestamp_inputs.append(name)
        else:
            if run_day is not None:
                run_date_delta_days = (run_day - generated_dt.date()).days
                if generated_dt.date() < run_day:
                    reasons.append("generated_before_run_date")
            if newest_dt is not None:
                skew_hours = round((newest_dt - generated_dt).total_seconds() / 3600.0, 3)
                if skew_hours > max_skew_hours and not target_date_aligned:
                    reasons.append("older_than_newest_input_threshold")
            if reasons:
                status = "STALE"
                stale_inputs.append(name)
        severity = "PASS"
        if status != "PASS":
            severity = "FAIL" if name in critical_inputs and status != "MISSING" else "WARN"
            if severity == "FAIL":
                critical_stale_inputs.append(name)
        rows.append({
            "name": name,
            "critical": name in critical_inputs,
            "exists": exists,
            "generated_at_utc": generated_raw,
            "generated_date": generated_dt.date().isoformat() if generated_dt is not None else None,
            "target_date": artifact_target_day.isoformat() if artifact_target_day is not None else None,
            "target_date_aligned": target_date_aligned,
            "freshness_status": status,
            "severity": severity,
            "reasons": reasons,
            "run_date_delta_days": run_date_delta_days,
            "age_vs_newest_hours": skew_hours,
            "path": record.get("path"),
        })
    freshness_statuses = [
        row["severity"]
        for row in rows
        if row["freshness_status"] != "MISSING"
    ]
    return {
        "status": _input_gate_status(freshness_statuses),
        "max_skew_hours": max_skew_hours,
        "newest_input": newest_name,
        "newest_generated_at_utc": newest_dt.isoformat() if newest_dt is not None else None,
        "stale_inputs": stale_inputs,
        "critical_stale_inputs": critical_stale_inputs,
        "missing_timestamp_inputs": missing_timestamp_inputs,
        "invalid_timestamp_inputs": invalid_timestamp_inputs,
        "rows": rows,
    }


def _coverage_gate(artifacts, *, critical_inputs):
    rows = []
    for name, record in sorted((artifacts or {}).items()):
        exists = bool((record or {}).get("exists"))
        rows.append({
            "name": name,
            "critical": name in critical_inputs,
            "exists": exists,
        })
    missing = [row["name"] for row in rows if not row["exists"]]
    critical_missing = [row["name"] for row in rows if row["critical"] and not row["exists"]]
    total = len(rows)
    present = total - len(missing)
    return {
        "status": "FAIL" if critical_missing else "WARN" if missing else "PASS",
        "present_count": present,
        "total_count": total,
        "coverage_ratio": round(present / total, 4) if total else 1.0,
        "missing_count": len(missing),
        "missing_inputs": missing,
        "critical_inputs": list(critical_inputs),
        "critical_missing_inputs": critical_missing,
        "rows": rows,
    }


def _consistency_check(name, status, detail, evidence=None):
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def _trading_evidence_run_date(payload):
    trading = payload or {}
    candidates = [
        trading.get("run_date"),
        trading.get("target_date"),
        (trading.get("market_making") or {}).get("run_date"),
        (trading.get("market_making") or {}).get("target_date"),
        (trading.get("taker") or {}).get("run_date"),
        (trading.get("taker") or {}).get("target_date"),
    ]
    return first_present(*candidates)


def _date_text(value):
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    return text or None


def _target_date_check(name, expected_date, observed_date, *, mode="equals", source=None):
    observed = _date_text(observed_date)
    expected = _date_text(expected_date)
    evidence = {
        "expected_target_date": expected,
        "observed_target_date": observed,
        "mode": mode,
        "source": source or name,
    }
    if not expected or not observed:
        return _consistency_check(
            name,
            "SKIP",
            f"{source or name} has no comparable target date.",
            evidence,
        )
    if mode == "date_max":
        status = "PASS" if observed == expected else "FAIL"
        detail = f"{source or name} date_max={observed}; expected_target={expected}"
    else:
        status = "PASS" if observed == expected else "FAIL"
        detail = f"{source or name} target_date={observed}; expected_target={expected}"
    return _consistency_check(name, status, detail, evidence)


def _settled_analysis_anchor(payloads, run_date):
    """The settled day the run's artifacts must agree on.

    Since the 2026-07-02 finalize-window redesign, a daily chain running on
    date D analyzes settled day D-1, so target-dated artifacts can never equal
    run_date. Anchoring them to run_date made these invariants fail for every
    clean chain (they only passed when stale carried artifacts happened to
    share an old date) and starved the experiment queue. Artifacts must agree
    with the settled-analysis target; a separate recency check bounds how far
    that target may trail run_date.
    """
    return _date_text(
        (payloads.get("settled_day_freshness") or {}).get("target_date")
        or (payloads.get("settled_day_analysis_barrier") or {}).get("target_date")
        or run_date
    )


def _scoring_liveness(payload):
    return (payload or {}).get("scoring_liveness") or {}


def _last_scored_target_date(payload):
    liveness = _scoring_liveness(payload)
    corpus = (payload or {}).get("corpus") or {}
    return (
        (payload or {}).get("last_scored_target_date")
        or liveness.get("last_scored_target_date")
        or (payload or {}).get("target_date")
        or corpus.get("date_max")
    )


def _target_date_consistency_checks(payloads, *, run_date):
    expected = _settled_analysis_anchor(payloads, run_date)
    checks = [_settled_target_recency_check(expected, run_date)]
    specs = [
        (
            "settled_day_freshness_target_date",
            (payloads.get("settled_day_freshness") or {}).get("target_date"),
            "equals",
            "settled_day_freshness",
        ),
        (
            "settled_day_analysis_barrier_target_date",
            (payloads.get("settled_day_analysis_barrier") or {}).get("target_date"),
            "equals",
            "settled_day_analysis_barrier",
        ),
        (
            "settled_day_root_cause_target_date",
            (payloads.get("settled_day_root_cause") or {}).get("target_date"),
            "equals",
            "settled_day_root_cause",
        ),
        (
            "promotion_refresh_corpus_date_max",
            ((payloads.get("promotion_refresh") or {}).get("corpus") or {}).get("date_max"),
            "date_max",
            "promotion_refresh.corpus",
        ),
        (
            "hourly_model_performance_date_max",
            ((payloads.get("hourly_model_performance") or {}).get("corpus") or {}).get("date_max"),
            "date_max",
            "hourly_model_performance.corpus",
        ),
        (
            "hourly_model_performance_last_scored_target_date",
            _last_scored_target_date(payloads.get("hourly_model_performance") or {}),
            "equals",
            "hourly_model_performance",
        ),
        (
            "ten_minute_model_performance_date_max",
            ((payloads.get("ten_minute_model_performance") or {}).get("corpus") or {}).get("date_max"),
            "date_max",
            "ten_minute_model_performance.corpus",
        ),
        (
            "ten_minute_model_performance_last_scored_target_date",
            _last_scored_target_date(payloads.get("ten_minute_model_performance") or {}),
            "equals",
            "ten_minute_model_performance",
        ),
        (
            "price_free_model_learning_date_max",
            ((payloads.get("price_free_model_learning") or {}).get("corpus") or {}).get("date_max"),
            "date_max",
            "price_free_model_learning.corpus",
        ),
        (
            "price_free_model_learning_last_scored_target_date",
            _last_scored_target_date(payloads.get("price_free_model_learning") or {}),
            "equals",
            "price_free_model_learning",
        ),
    ]
    checks.extend(
        _target_date_check(name, expected, observed, mode=mode, source=source)
        for name, observed, mode, source in specs
    )
    return checks


def _settled_target_recency_check(anchor_date, run_date):
    """Fail closed when the agreed settled target trails run_date by > 1 day.

    Mutual target agreement alone would also pass a uniformly STALE artifact
    set (everything from three days ago agreeing with itself); the analyzed
    day must be run_date or the day before it.
    """
    anchor = _date_text(anchor_date)
    run = _date_text(run_date)
    evidence = {"settled_target_date": anchor, "run_date": run}
    if not anchor or not run:
        return _consistency_check(
            "settled_target_recency",
            "SKIP",
            "no comparable settled target or run date",
            evidence,
        )
    try:
        lag_days = (date.fromisoformat(run) - date.fromisoformat(anchor)).days
    except ValueError:
        return _consistency_check(
            "settled_target_recency",
            "FAIL",
            f"unparseable dates: settled_target={anchor}; run_date={run}",
            evidence,
        )
    evidence["lag_days"] = lag_days
    status = "PASS" if 0 <= lag_days <= 1 else "FAIL"
    return _consistency_check(
        "settled_target_recency",
        status,
        f"settled_target={anchor}; run_date={run}; lag_days={lag_days}",
        evidence,
    )


def _consistency_gate(payloads, scorecard, *, run_date, brier_delta_tolerance):
    checks = []
    labels_total = safe_int(((scorecard.get("labels") or {}).get("total")))
    corpus_days = safe_int(((scorecard.get("corpus") or {}).get("market_day_count")))
    skipped_by_reason = (scorecard.get("corpus") or {}).get("skipped_by_reason") or {}
    countable_label_skip_count = sum(
        safe_int(count)
        for reason, count in skipped_by_reason.items()
        if str(reason) in COUNTABLE_LABEL_CORPUS_SKIP_REASONS
    )
    expected_label_total = corpus_days + countable_label_skip_count
    if labels_total or corpus_days:
        labels_match = labels_total == corpus_days or labels_total == expected_label_total
        checks.append(_consistency_check(
            "promotion_corpus_vs_settled_labels",
            "PASS" if labels_match else "FAIL",
            (
                f"promotion corpus market_day_count={corpus_days}; "
                f"settled label total={labels_total}; "
                f"countable corpus skips={countable_label_skip_count}"
            ),
            {
                "market_day_count": corpus_days,
                "settled_label_total": labels_total,
                "countable_corpus_skip_count": countable_label_skip_count,
                "expected_settled_label_total": expected_label_total,
                "skipped_by_reason": skipped_by_reason,
            },
        ))
    else:
        checks.append(_consistency_check(
            "promotion_corpus_vs_settled_labels",
            "SKIP",
            "No corpus market-days or settled labels were present.",
            {"market_day_count": corpus_days, "settled_label_total": labels_total},
        ))

    # Trading evidence summarizes the settled analysis day, so it aligns with
    # the settled-target anchor, not the calendar run date (see
    # _settled_analysis_anchor for why those differ on every clean chain).
    expected_trading_date = _settled_analysis_anchor(payloads, run_date)
    trading_run_date = _trading_evidence_run_date(payloads.get("trading_evidence") or {})
    observed_trading_date = str(trading_run_date or "")[:10]
    if expected_trading_date and observed_trading_date:
        checks.append(_consistency_check(
            "trading_evidence_run_date",
            "PASS" if observed_trading_date == expected_trading_date else "FAIL",
            f"trading_evidence date={observed_trading_date}; expected_target={expected_trading_date}",
            {"trading_evidence_date": observed_trading_date, "expected_target_date": expected_trading_date},
        ))
    else:
        checks.append(_consistency_check(
            "trading_evidence_run_date",
            "FAIL",
            "Trading evidence is missing a run_date or target_date for alignment.",
            {"trading_evidence_date": observed_trading_date or None, "expected_target_date": expected_trading_date or None},
        ))

    checks.extend(_target_date_consistency_checks(payloads, run_date=run_date))

    candidate = scorecard.get("candidate") or {}
    candidate_brier = maybe_float(candidate.get("candidate_brier"))
    for name, baseline_key, delta_key in (
        ("candidate_delta_vs_current", "current_brier", "delta_vs_current"),
        ("candidate_delta_vs_market", "market_brier", "delta_vs_market"),
    ):
        baseline = maybe_float(candidate.get(baseline_key))
        observed_delta = maybe_float(candidate.get(delta_key))
        if candidate_brier is None or baseline is None or observed_delta is None:
            checks.append(_consistency_check(
                name,
                "SKIP",
                f"{delta_key} could not be checked because one or more Brier values are missing.",
                {
                    "candidate_brier": candidate_brier,
                    baseline_key: baseline,
                    delta_key: observed_delta,
                },
            ))
            continue
        expected_delta = candidate_brier - baseline
        difference = observed_delta - expected_delta
        checks.append(_consistency_check(
            name,
            "PASS" if abs(difference) <= brier_delta_tolerance else "FAIL",
            (
                f"{delta_key}={observed_delta:.6f}; expected "
                f"candidate_brier - {baseline_key}={expected_delta:.6f}"
            ),
            {
                "candidate_brier": candidate_brier,
                baseline_key: baseline,
                delta_key: observed_delta,
                "expected_delta": expected_delta,
                "difference": difference,
                "tolerance": brier_delta_tolerance,
            },
        ))
    failed = [row for row in checks if row.get("status") == "FAIL"]
    return {
        "status": "FAIL" if failed else "PASS",
        "brier_delta_tolerance": brier_delta_tolerance,
        "failed_invariant_count": len(failed),
        "failed_invariants": [row["name"] for row in failed],
        "checks": checks,
    }


def _build_input_gate(
    payloads,
    artifacts,
    scorecard,
    *,
    run_date,
    max_skew_hours=INPUT_FRESHNESS_MAX_SKEW_HOURS,
    brier_delta_tolerance=INPUT_CONSISTENCY_BRIER_TOLERANCE,
    critical_inputs=CRITICAL_INPUTS,
):
    critical_inputs = tuple(critical_inputs or ())
    coverage = _coverage_gate(artifacts, critical_inputs=critical_inputs)
    freshness = _freshness_rows(
        artifacts,
        run_date=run_date,
        max_skew_hours=float(max_skew_hours),
        critical_inputs=critical_inputs,
    )
    consistency = _consistency_gate(
        payloads,
        scorecard,
        run_date=run_date,
        brier_delta_tolerance=float(brier_delta_tolerance),
    )
    return {
        "status": _input_gate_status(
            coverage.get("status"),
            freshness.get("status"),
            consistency.get("status"),
        ),
        "run_date": str(run_date or "")[:10],
        "critical_inputs": list(critical_inputs),
        "coverage": coverage,
        "freshness": freshness,
        "consistency": consistency,
    }


def _candidate_from_payloads(payloads):
    promotion = payloads.get("promotion_refresh") or {}
    candidate = promotion.get("candidate") or {}
    replay = payloads.get("candidate_replay") or {}
    if candidate:
        return candidate
    if replay:
        return {
            "aggregate": replay.get("aggregate") or {},
            "coverage": replay.get("coverage") or {},
            "verdict": replay.get("verdict"),
            "candidate_market_verdict": replay.get("candidate_market_verdict"),
            "cutover_decision": replay.get("cutover_decision"),
            "blocked_validation": replay.get("blocked_validation") or {},
            "slices": {
                "by_market": replay.get("market_rows") or [],
                "by_cutoff_hour": replay.get("by_hour") or [],
                "by_band_type": replay.get("by_bin_type") or [],
                "by_settlement_distance": replay.get("by_settlement_distance") or [],
                "by_source_freshness": replay.get("by_source_freshness") or [],
            },
        }
    return {}


def _label_total_for_quality_grades(label_summary, quality_grades):
    if not label_summary or not label_summary.get("exists"):
        return None
    quality_counts = label_summary.get("quality_counts") or {}
    if not quality_grades or "all" in {str(item).lower() for item in quality_grades}:
        return safe_int(label_summary.get("total_all"))
    return sum(safe_int(quality_counts.get(str(grade))) for grade in quality_grades)


def _label_total_for_admission(label_summary, quality_grades, admit_promotion_countable):
    """Count settled labels the corpus admission rules make eligible.

    Grade-eligible labels plus, when the corpus admits item-319 material
    countability, promotion-countable labels outside the listed grades. This is
    the total the corpus-vs-labels invariant must reconcile against; the
    all-grades label total includes non-countable capture-gap history the
    corpus is required to exclude.
    """
    grade_total = _label_total_for_quality_grades(label_summary, quality_grades)
    if grade_total is None:
        return None
    if not admit_promotion_countable:
        return grade_total
    if not quality_grades or "all" in {str(item).lower() for item in quality_grades}:
        return grade_total
    countable_by_grade = label_summary.get("countable_by_quality_grade") or {}
    grades = {str(grade) for grade in quality_grades}
    return grade_total + sum(
        safe_int(count)
        for grade, count in countable_by_grade.items()
        if str(grade) not in grades
    )


def _scorecard_label_summary(daily_labels, market_day_labels, corpus):
    daily_labels = daily_labels or {}
    market_day_labels = market_day_labels or {}
    quality_grades = corpus.get("quality_grades") or ["complete", "manual_override"]
    admit_promotion_countable = bool(corpus.get("admit_promotion_countable"))
    # The corpus-vs-labels invariant needs the label total scoped to the same
    # admission rules the corpus applied; the raw all-grades total counts
    # non-countable capture-gap history the corpus must exclude.
    scoped_total = _label_total_for_admission(
        market_day_labels, quality_grades, admit_promotion_countable
    )
    csv_total = _label_total_for_quality_grades(market_day_labels, quality_grades)
    daily_total = safe_int(daily_labels.get("total"))
    if scoped_total is not None:
        total = scoped_total
        source = "market_day_labels_csv_admission_scoped"
    elif daily_total > 0:
        total = daily_total
        source = "daily_refresh_status"
    elif csv_total is not None:
        total = csv_total
        source = "market_day_labels_csv"
    else:
        total = daily_total
        source = "daily_refresh_status"
    return {
        "total": total,
        "total_admission_scoped": scoped_total,
        "admit_promotion_countable": admit_promotion_countable,
        "quality_counts": (
            daily_labels.get("quality_counts")
            or market_day_labels.get("quality_counts")
            or {}
        ),
        "reconciliation_counts": (
            daily_labels.get("reconciliation_counts")
            or market_day_labels.get("reconciliation_counts")
            or {}
        ),
        "material_coverage_counts": market_day_labels.get("material_coverage_counts") or {},
        "promotion_countability_available": bool(market_day_labels.get("promotion_countability_available")),
        "promotion_countable_label_count": safe_int(market_day_labels.get("promotion_countable_label_count")),
        "promotion_blocked_label_count": safe_int(market_day_labels.get("promotion_blocked_label_count")),
        "source": source,
        "path": market_day_labels.get("path"),
        "total_all": market_day_labels.get("total_all"),
        "quality_grades": list(quality_grades),
    }


def _label_countability_policy(label_summary, barrier):
    barrier_policy = (barrier or {}).get("label_countability") or {}
    if barrier_policy:
        return {
            **barrier_policy,
            "source": "settled_day_analysis_barrier",
        }
    quality_counts = (label_summary or {}).get("quality_counts") or {}
    if (label_summary or {}).get("promotion_countability_available"):
        blocked_count = safe_int((label_summary or {}).get("promotion_blocked_label_count"))
        partial_count = safe_int(quality_counts.get("partial"))
        promotion_countable = blocked_count == 0
        return {
            "status": "promotion_countable" if promotion_countable else "diagnostic_only",
            "promotion_countable": promotion_countable,
            "diagnostic_only": not promotion_countable,
            "partial_label_count": partial_count,
            "strict_partial_label_count": partial_count,
            "quality_counts": quality_counts,
            "material_coverage_counts": (label_summary or {}).get("material_coverage_counts") or {},
            "material_promotion_countable_label_count": safe_int(
                (label_summary or {}).get("promotion_countable_label_count")
            ),
            "material_promotion_blocked_label_count": blocked_count,
            "reason": (
                "all selected settled labels are promotion-countable"
                if promotion_countable
                else f"{blocked_count} settled label(s) are not material-coverage promotion-countable"
            ),
            "source": "label_material_coverage_counts",
        }
    partial_count = safe_int(quality_counts.get("partial"))
    if partial_count:
        return {
            "status": "diagnostic_only",
            "promotion_countable": False,
            "diagnostic_only": True,
            "partial_label_count": partial_count,
            "quality_counts": quality_counts,
            "reason": f"{partial_count} settled label(s) have quality_grade=partial",
            "source": "label_quality_counts",
        }
    return {
        "status": "promotion_countable",
        "promotion_countable": True,
        "diagnostic_only": False,
        "partial_label_count": 0,
        "quality_counts": quality_counts,
        "reason": "all selected settled labels are promotion-countable",
        "source": "label_quality_counts",
    }


def _served_calibration_lane(scorecard):
    lanes = (scorecard or {}).get("lanes") or []
    for name in ("weather_only", "current", "candidate", "no_market"):
        for row in lanes:
            if row.get("lane") == name:
                return row
    section = (((scorecard or {}).get("lane_sections") or {}).get("weather_only") or [])
    return section[0] if section else {}


def _calibration_monitoring_summary(scorecard):
    if not scorecard:
        return {
            "calibration_status": "MISSING",
            "calibration_ece": None,
            "calibration_row_count": None,
            "directional_bias_status": "MISSING",
            "directional_bias_mean_error": None,
            "directional_bias_abs_mean_error": None,
            "directional_bias_source": None,
        }
    lane = _served_calibration_lane(scorecard)
    explicit_bias = scorecard.get("directional_bias") or {}
    afternoon = scorecard.get("afternoon_post_ramp_slice") or {}
    ece = maybe_float(first_present(
        lane.get("ece"),
        lane.get("expected_calibration_error"),
        (scorecard.get("summary") or {}).get("model_ece"),
    ))
    signed_bias = maybe_float(first_present(
        explicit_bias.get("signed_bias"),
        explicit_bias.get("signed_bias_c"),
        explicit_bias.get("mean_realized_minus_predicted"),
        explicit_bias.get("mean_signed_error"),
    ))
    source = explicit_bias.get("source")
    if signed_bias is None and afternoon.get("mean_expected_high_bias") is not None:
        expected_minus_realized = maybe_float(afternoon.get("mean_expected_high_bias"))
        signed_bias = -expected_minus_realized if expected_minus_realized is not None else None
        source = "proper_scoring_reliability_scorecard.afternoon_post_ramp_slice"
    return {
        "calibration_status": "PRESENT" if ece is not None else "MISSING",
        "calibration_ece": ece,
        "calibration_row_count": safe_int(lane.get("row_count")),
        "directional_bias_status": "PRESENT" if signed_bias is not None else "MISSING",
        "directional_bias_mean_error": signed_bias,
        "directional_bias_abs_mean_error": abs(signed_bias) if signed_bias is not None else None,
        "directional_bias_source": source,
    }


def _scorecard(payloads, daily_refresh_summary=None):
    daily = payloads.get("daily_refresh_status") or {}
    daily_summary = daily_refresh_summary or daily.get("summary") or {}
    rollup_freshness = (
        daily_summary.get("rollup_freshness")
        or ((daily.get("summary") or {}).get("rollup_freshness"))
        or payloads.get("rollup_freshness")
        or {}
    )
    ingest = first_present(
        daily_summary.get("ingest_quality_gate"),
        payloads.get("ingest_quality_gate"),
    ) or {}
    promotion = payloads.get("promotion_refresh") or {}
    early_hour_promotion_blocker = promotion.get("early_hour_promotion_blocker") or {}
    hourly = payloads.get("hourly_model_performance") or {}
    ten_minute = payloads.get("ten_minute_model_performance") or {}
    price_free = payloads.get("price_free_model_learning") or {}
    price_free_current_max = price_free.get("current_max_carryover") or {}
    candidate = _candidate_from_payloads(payloads)
    aggregate = candidate.get("aggregate") or {}
    corpus = promotion.get("corpus") or {}
    label_summary = _scorecard_label_summary(
        daily_summary.get("labels") or {},
        payloads.get("market_day_labels") or {},
        corpus,
    )
    decisions = promotion.get("decisions") or {}
    shadow = payloads.get("shadow_ab_monitor") or {}
    variant = payloads.get("model_variant_evidence_growth") or {}
    progress = payloads.get("progress_audit") or {}
    casebook = (payloads.get("disagreement_casebook") or {}).get("summary") or {}
    disagreement_analysis = payloads.get("model_market_disagreement_analysis") or {}
    disagreement_rehydration = disagreement_analysis.get("rehydration") or {}
    fleet = payloads.get("fleet_observability") or {}
    event_metadata = payloads.get("event_metadata_validation") or {}
    trading = payloads.get("trading_evidence") or {}
    data_layer = payloads.get("data_layer_audit") or {}
    snapshot_eval = payloads.get("snapshot_evaluation") or {}
    root_cause = payloads.get("settled_day_root_cause") or {}
    settled_day = payloads.get("settled_day_freshness") or {}
    settled_barrier = payloads.get("settled_day_analysis_barrier") or {}
    source_family_inventory = payloads.get("source_family_inventory") or {}
    taker_finalization = payloads.get("taker_finalization_watchdog") or {}
    taker_tail = payloads.get("taker_tail_casebook") or {}
    proper_scoring = payloads.get("proper_scoring_reliability_scorecard") or {}
    winner_rank = payloads.get("winner_rank_parity") or {}
    snapshot_status = snapshot_eval.get("status") or {}
    snapshot_inventory = snapshot_eval.get("snapshot_inventory") or {}
    backlog = snapshot_eval.get("improvement_backlog") or {}

    return {
        "labels": label_summary,
        "label_countability": _label_countability_policy(label_summary, settled_barrier),
        "ingest_quality_gate": {
            "status": ingest.get("status"),
            "fail_reasons": ingest.get("fail_reasons") or [],
            "warn_reasons": ingest.get("warn_reasons") or [],
        },
        "promotion": {
            "candidate_verdict": candidate.get("verdict") or promotion.get("candidate_verdict"),
            "cutover_decision": candidate.get("cutover_decision") or promotion.get("cutover_decision"),
            "promote_markets": decisions.get("promote_markets") or [],
            "shadow_markets": decisions.get("shadow_markets") or [],
            "blocked_markets": decisions.get("blocked_markets") or [],
            "action_counts": decisions.get("action_counts") or {},
            "readiness_status": (promotion.get("readiness") or {}).get("status"),
            "readiness_blockers": (promotion.get("readiness") or {}).get("blockers") or [],
            "early_hour_promotion_blocker": early_hour_promotion_blocker,
            "early_hour_promotion_allowed": early_hour_promotion_blocker.get("promotion_allowed"),
            "early_hour_blocker_count": early_hour_promotion_blocker.get("blocker_count"),
        },
        "hourly_model_performance": {
            "status": (hourly.get("hourly_performance_gate") or {}).get("status"),
            "daily_summary": hourly.get("daily_summary") or {},
            "hourly_performance_gate": hourly.get("hourly_performance_gate") or {},
            "remediation_registry_summary": (hourly.get("remediation_registry") or {}).get("summary") or {},
            "early_hour_market_deltas": (hourly.get("remediation_registry") or {}).get("early_hour_market_deltas") or [],
            "last_scored_target_date": _last_scored_target_date(hourly),
            "latest_settled_label_date": (_scoring_liveness(hourly)).get("latest_settled_label_date"),
            "scoring_liveness": _scoring_liveness(hourly),
        },
        "ten_minute_model_performance": {
            "status": (ten_minute.get("ten_minute_performance_gate") or {}).get("status"),
            "daily_summary": ten_minute.get("daily_summary") or {},
            "ten_minute_performance_gate": ten_minute.get("ten_minute_performance_gate") or {},
            "candidate_ten_minute_gate": ten_minute.get("candidate_ten_minute_gate") or {},
            "weak_slots": ten_minute.get("weak_slots") or {},
            "rankings": ten_minute.get("rankings") or {},
            "last_scored_target_date": _last_scored_target_date(ten_minute),
            "latest_settled_label_date": (_scoring_liveness(ten_minute)).get("latest_settled_label_date"),
            "scoring_liveness": _scoring_liveness(ten_minute),
        },
        "price_free_model_learning": {
            "status": price_free.get("status"),
            "daily_summary": price_free.get("daily_summary") or {},
            "corpus": price_free.get("corpus") or {},
            "overall": price_free.get("overall") or {},
            "current_max_carryover": {
                "summary": price_free_current_max.get("summary") or {},
                "by_market_hour": price_free_current_max.get("by_market_hour") or [],
                "examples": (price_free_current_max.get("examples") or [])[:30],
                "focused_row_count": price_free_current_max.get("focused_row_count"),
                "focus_definition": price_free_current_max.get("focus_definition"),
            },
            "evidence_classification": price_free.get("evidence_classification") or {},
            "last_scored_target_date": _last_scored_target_date(price_free),
            "latest_settled_label_date": (_scoring_liveness(price_free)).get("latest_settled_label_date"),
            "scoring_liveness": _scoring_liveness(price_free),
        },
        "corpus": {
            "market_day_count": safe_int(corpus.get("market_day_count")),
            "snapshot_count": safe_int(corpus.get("snapshot_count")),
            "band_row_count": safe_int(corpus.get("band_row_count")),
            "path": corpus.get("path"),
            "corpus_hash": corpus.get("corpus_hash"),
            "quality_grades": corpus.get("quality_grades") or [],
            "admit_promotion_countable": bool(corpus.get("admit_promotion_countable")),
            "admitted_by": corpus.get("admitted_by") or {},
            "skipped_by_reason": corpus.get("skipped_by_reason") or {},
            "skipped_count": safe_int(corpus.get("skipped_count")),
        },
        "candidate": {
            "rows": safe_int(first_present(aggregate.get("rows"), aggregate.get("n"))),
            "candidate_brier": maybe_float(aggregate.get("candidate_brier")),
            "current_brier": maybe_float(aggregate.get("current_brier")),
            "market_brier": maybe_float(aggregate.get("market_brier")),
            "delta_vs_current": maybe_float(aggregate.get("delta_vs_current")),
            "delta_vs_market": maybe_float(aggregate.get("delta_vs_market")),
            "missing_candidate_rows": safe_int((candidate.get("coverage") or {}).get("missing_candidate_rows")),
            "blocked_validation": candidate.get("blocked_validation") or {},
            "paired_delta_samples": (
                candidate.get("paired_delta_samples")
                or candidate.get("market_day_deltas")
                or aggregate.get("paired_delta_samples")
                or aggregate.get("market_day_deltas")
                or []
            ),
        },
        "shadow_ab_monitor": {
            "status": shadow.get("status"),
            "summary": shadow.get("summary") or {},
        },
        "model_variant_evidence_growth": {
            "status": variant.get("status"),
            "summary": variant.get("summary") or {},
            "delta_vs_baseline": variant.get("delta_vs_baseline"),
            "evidence_sla": variant.get("evidence_sla") or {},
            "no_growth_reasons": variant.get("no_growth_reasons") or [],
            "trend": variant.get("trend") or [],
        },
        "variant_learning_gate": daily_summary.get("variant_learning_gate") or {},
        "core_model_trend_claim": progress.get("core_model_trend_claim") or {},
        "calibration_monitoring": _calibration_monitoring_summary(proper_scoring),
        "casebook": {
            "case_count": safe_int(casebook.get("case_count")),
            "settled_case_count": safe_int(casebook.get("settled_case_count")),
            "open_case_count": safe_int(casebook.get("open_case_count")),
            "model_win_count": safe_int(casebook.get("model_win_count")),
            "model_loss_count": safe_int(casebook.get("model_loss_count")),
            "taxonomy_counts": casebook.get("taxonomy_counts") or {},
        },
        "winner_rank_parity": {
            "status": winner_rank.get("status"),
            "dates": winner_rank.get("dates") or [],
            "summary": winner_rank.get("summary") or {},
            "parity_gate": winner_rank.get("parity_gate") or {},
            "top_owner_route_count": len(winner_rank.get("top_owner_routes") or []),
            "top_owner_routes": (winner_rank.get("top_owner_routes") or [])[:20],
        },
        "model_market_disagreement_rehydration": {
            "status": (
                disagreement_rehydration.get("status")
                or ((disagreement_rehydration.get("gate") or {}).get("status"))
                or ((disagreement_analysis.get("summary") or {}).get("rehydration_status"))
            ),
            "target_date": disagreement_rehydration.get("target_date"),
            "pending_before_count": safe_int(disagreement_rehydration.get("pending_before_count")),
            "rehydrated_count": safe_int(disagreement_rehydration.get("rehydrated_count")),
            "model_closer_rehydrated_count": safe_int(
                disagreement_rehydration.get("model_closer_rehydrated_count")
            ),
            "market_closer_rehydrated_count": safe_int(
                disagreement_rehydration.get("market_closer_rehydrated_count")
            ),
            "excluded_partial_label_count": safe_int(disagreement_rehydration.get("excluded_partial_label_count")),
            "excluded_missing_label_count": safe_int(disagreement_rehydration.get("excluded_missing_label_count")),
            "pending_after_count": safe_int(disagreement_rehydration.get("pending_after_count")),
            "unresolved_after_rehydrate_count": safe_int(
                disagreement_rehydration.get("unresolved_after_rehydrate_count")
            ),
            "blocker_count": safe_int(disagreement_rehydration.get("blocker_count")),
            "blockers": disagreement_rehydration.get("blockers") or [],
            "report_out": (disagreement_analysis.get("summary") or {}).get("report_out"),
        },
        "fleet": {
            "status": fleet.get("status"),
            "summary": fleet.get("summary") or {},
            "live_forward_slo": fleet.get("live_forward_slo") or {},
            "current_code_soak": fleet.get("current_code_soak") or {},
            "clean_active_day_countability": fleet.get("clean_active_day_countability") or {},
            "source_status_proof": ((fleet.get("collection") or {}).get("source_status_proof") or {}),
            "mm_paper_evidence": fleet.get("mm_paper_evidence") or {},
        },
        "event_metadata_validation": {
            "status": event_metadata.get("status"),
            "target_date": event_metadata.get("target_date"),
            "validation_hash": event_metadata.get("validation_hash"),
            "summary": event_metadata.get("summary") or {},
            "first_blocker": ((event_metadata.get("summary") or {}).get("first_blocker") or {}),
            "refresh_command": event_metadata.get("refresh_command"),
            "validation_command": event_metadata.get("validation_command"),
        },
        "trading_evidence": trading,
        "taker_finalization_watchdog": {
            "status": taker_finalization.get("status"),
            "summary": taker_finalization.get("summary") or {},
            "alerts": taker_finalization.get("alerts") or [],
            "finalized_runs": taker_finalization.get("finalized_runs") or [],
            "champion_challenger_ledger": taker_finalization.get("champion_challenger_ledger") or {},
        },
        "taker_tail_casebook": {
            "status": (taker_tail.get("summary") or {}).get("status") or taker_tail.get("status"),
            "summary": taker_tail.get("summary") or {},
            "by_tail_type": taker_tail.get("by_tail_type") or [],
            "no_go_candidates": taker_tail.get("no_go_candidates") or [],
        },
        "data_layer_audit": {
            "gate_status": (data_layer.get("gate_summary") or {}).get("status"),
            "gate_summary": data_layer.get("gate_summary") or {},
            "sidecar_eligibility": ((data_layer.get("snapshots") or {}).get("sidecar_eligibility") or {}),
            "recommendation_count": len(data_layer.get("recommendations") or []),
            "p0_remediation_count": len(
                [
                    row for row in data_layer.get("remediation_manifest") or []
                    if row.get("priority") == "P0"
                ]
            ),
        },
        "snapshot_evaluation": {
            "status": snapshot_status.get("status"),
            "gate_counts": snapshot_status,
            "snapshot_folders": safe_int(snapshot_inventory.get("folder_count")),
            "snapshots": safe_int(snapshot_inventory.get("snapshot_count")),
            "top_gap_count": len(backlog.get("top_slices") or []),
        },
        "settled_day_root_cause": {
            "status": root_cause.get("status"),
            "target_date": root_cause.get("target_date"),
            "summary": root_cause.get("summary") or {},
            "last_scored_target_date": _last_scored_target_date(root_cause),
            "latest_settled_label_date": (_scoring_liveness(root_cause)).get("latest_settled_label_date"),
            "scoring_liveness": _scoring_liveness(root_cause),
        },
        "settled_day_freshness": {
            "status": settled_day.get("status"),
            "target_date": settled_day.get("target_date"),
            "summary": settled_day.get("summary") or {},
            "repair_command": settled_day.get("repair_command"),
            "replay_status_repair_command": settled_day.get("replay_status_repair_command"),
        },
        "settled_day_analysis_barrier": {
            "status": settled_barrier.get("status"),
            "target_date": settled_barrier.get("target_date"),
            "blocker_count": settled_barrier.get("blocker_count"),
            "blockers": settled_barrier.get("blockers") or [],
            "label_countability": settled_barrier.get("label_countability") or {},
            "resume_command": settled_barrier.get("resume_command"),
        },
        "source_family_inventory": {
            "status": source_family_inventory.get("status"),
            "summary": source_family_inventory.get("summary") or {},
            "promotion_preflight": source_family_inventory.get("promotion_preflight") or {},
        },
        "rollup_freshness": rollup_freshness,
    }


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_BACKTEST_ROOT",
    "DEFAULT_SNAPSHOTS_ROOT",
    "DEFAULT_JSON_OUT",
    "DEFAULT_REPORT_OUT",
    "ARTIFACT_FILES",
    "ARTIFACT_FALLBACK_GLOBS",
    "PRIORITY_ORDER",
    "IMPACT_SORT_KEYS",
    "PROMOTION_MIN_INDEPENDENT_MARKET_DAYS",
    "PROMOTION_BOOTSTRAP_RESAMPLES",
    "PROMOTION_CI_LEVEL",
    "CALIBRATION_ECE_DRIFT_THRESHOLD",
    "CALIBRATION_BIAS_DRIFT_THRESHOLD",
    "INPUT_FRESHNESS_MAX_SKEW_HOURS",
    "INPUT_CONSISTENCY_BRIER_TOLERANCE",
    "EXPERIMENT_QUEUE_MAX_ITEMS",
    "EXPERIMENT_QUEUE_RETRAIN_INPUT_LIMIT",
    "RETRAIN_CORPUS_GROWTH_MARKET_DAYS",
    "CRITICAL_INPUTS",
    "COUNTABLE_LABEL_CORPUS_SKIP_REASONS",
    "utc_iso",
    "safe_int",
    "maybe_float",
    "first_present",
    "_priority_rank",
    "_impact_score",
    "_estimated_impact",
    "_rank_learnings",
    "_stable_id",
    "_status_from_queue_result",
    "_queue_results_by_id",
    "_apply_queue_result",
    "_queue_item_from_learning",
    "_queue_item_from_manifest",
    "_build_experiment_queue",
    "_capped_sorted_rows",
    "_count_summary",
    "_artifact_record",
    "_latest_matching_artifact",
    "_load_artifact",
    "_market_day_labels_summary",
    "load_inputs",
    "_parse_timestamp",
    "_parse_run_date",
    "_coerce_in_memory_daily_refresh_input",
    "_input_gate_status",
    "_freshness_rows",
    "_coverage_gate",
    "_consistency_check",
    "_trading_evidence_run_date",
    "_date_text",
    "_target_date_check",
    "_scoring_liveness",
    "_last_scored_target_date",
    "_target_date_consistency_checks",
    "_consistency_gate",
    "_build_input_gate",
    "_candidate_from_payloads",
    "_label_total_for_quality_grades",
    "_label_total_for_admission",
    "_scorecard_label_summary",
    "_label_countability_policy",
    "_served_calibration_lane",
    "_calibration_monitoring_summary",
    "_scorecard",
]
