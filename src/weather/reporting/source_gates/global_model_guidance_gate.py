"""Global-model guidance gate for roadmap item 189."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.source_gates.source_family_consumer_contract import (
    source_family_inventory_consumer_contract,
)


SCHEMA_VERSION = "global_model_guidance_gate_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SOURCE_INVENTORY_JSON = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_all_hours_replay.json"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item189_global_model_guidance_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item189_global_model_guidance_gate_report.md"
DEFAULT_CURRENT_TOL = 0.003
DEFAULT_MIN_EARLY_ROWS = 1

GLOBAL_MODEL_SOURCE = "open_meteo_global_models"
GLOBAL_MODEL_FEATURES = (
    "open_meteo_global_models_high_spread",
    "open_meteo_ecmwf_ifs_high_delta",
    "open_meteo_ecmwf_aifs_high_delta",
    "open_meteo_ncep_aigfs_high_delta",
    "open_meteo_gfs_graphcast_high_delta",
    "open_meteo_ecmwf_ifs_aifs_disagreement",
    "open_meteo_global_models_next_3h_spread",
    "open_meteo_global_models_run_to_run_high_change",
)
LEGACY_ENSEMBLE_FEATURES = (
    "forecast_global_ensemble_spread",
    "forecast_next_3h_ensemble_spread",
    "forecast_global_ensemble_high_p10",
    "forecast_global_ensemble_high_p90",
    "forecast_global_ensemble_high_spread_80",
)
ISOLATED_GLOBAL_MODEL_SUBSETS = {
    "global_model_guidance",
    "open_meteo_global_models",
    "forecast_global_model_guidance",
}
MULTI_MODEL_FAMILIES = {"official_multimodel_guidance", "open_meteo_forecast_profile", "forecast_source_state"}
HISTORICAL_MODEL_STATUSES = {
    "model_run_archive_available",
    "global_model_archive_available",
    "historical_global_model_archive_available",
}


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_inventory_row(payload: dict[str, Any], family_id: str) -> dict[str, Any]:
    for row in payload.get("inventory") or []:
        if row.get("family_id") == family_id:
            return row
    return {}


def source_inventory_evidence(source_inventory: dict[str, Any]) -> dict[str, Any]:
    inventory_contract = source_family_inventory_consumer_contract(
        source_inventory
    )
    row = _find_inventory_row(source_inventory, "multi_model_guidance")
    feature_columns = set(row.get("feature_columns") or [])
    active_columns = set(row.get("active_model_feature_columns") or [])
    forecast_payloads = row.get("forecast_payloads") or {}
    source_status = row.get("source_status") or {}
    source_status_seen = set(source_status.get("sources_seen") or [])
    forecast_payloads_seen = set(forecast_payloads.get("sources_seen") or [])
    catalog_global = [feature for feature in GLOBAL_MODEL_FEATURES if feature in feature_columns]
    active_global = [feature for feature in GLOBAL_MODEL_FEATURES if feature in active_columns]

    return {
        "operational_contract": inventory_contract,
        "family_id": row.get("family_id"),
        "source_keys": row.get("source_keys") or [],
        "historical_archive_status": row.get("historical_archive_status"),
        "live_only": row.get("live_only"),
        "live_only_policy": row.get("live_only_policy"),
        "train_serve_parity_status": row.get("train_serve_parity_status"),
        "lineage_status": row.get("lineage_status"),
        "active_model_usage_status": row.get("active_model_usage_status"),
        "catalog_global_model_features": catalog_global,
        "missing_catalog_global_model_features": [feature for feature in GLOBAL_MODEL_FEATURES if feature not in feature_columns],
        "active_global_model_features": active_global,
        "missing_active_global_model_features": [feature for feature in GLOBAL_MODEL_FEATURES if feature not in active_columns],
        "source_status_sources_seen": sorted(source_status_seen),
        "forecast_payload_sources_seen": sorted(forecast_payloads_seen),
        "global_model_source_status_seen": GLOBAL_MODEL_SOURCE in source_status_seen,
        "global_model_forecast_payload_seen": GLOBAL_MODEL_SOURCE in forecast_payloads_seen,
        "forecast_payload_rows": forecast_payloads.get("rows", 0),
        "forecast_payload_folder_count": forecast_payloads.get("folder_count", 0),
        "missing_forecast_payload_folder_count": forecast_payloads.get("missing_folder_count", 0),
        "missing_forecast_payload_folder_samples": forecast_payloads.get("missing_folder_samples") or [],
        "feature_missingness": row.get("feature_missingness") or {},
    }


def isolated_global_model_artifact(candidate: dict[str, Any]) -> dict[str, Any]:
    artifact = candidate.get("artifact") or {}
    subset = artifact.get("feature_subset")
    contract = artifact.get("feature_subset_contract") or {}
    contract_name = contract.get("name")
    allowed_families = set(contract.get("allowed_feature_families") or [])
    reasons = []
    if subset in ISOLATED_GLOBAL_MODEL_SUBSETS:
        reasons.append(f"feature_subset={subset}")
    if contract_name in ISOLATED_GLOBAL_MODEL_SUBSETS:
        reasons.append(f"feature_subset_contract.name={contract_name}")
    if allowed_families and allowed_families <= {"global_model_guidance", "market_climate_context"}:
        if "global_model_guidance" in allowed_families:
            reasons.append("feature_subset_contract.allowed_feature_families includes only global models plus context")

    return {
        "isolated": bool(reasons),
        "basis": reasons,
        "feature_subset": subset,
        "contract_name": contract_name,
        "allowed_feature_families": sorted(allowed_families),
    }


def permutation_evidence(hgb_permutation_path: str | Path = DEFAULT_HGB_PERMUTATION) -> dict[str, Any]:
    expected = set(GLOBAL_MODEL_FEATURES) | set(LEGACY_ENSEMBLE_FEATURES)
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "slices": set(),
            "families": set(),
            "positive_delta_mae_sum": 0.0,
            "delta_mae_sum": 0.0,
            "best_delta_mae": None,
            "min_hgb_importance_q": None,
        }
    )
    for row in _read_csv(hgb_permutation_path):
        feature = row.get("feature") or ""
        family = row.get("family") or ""
        if family not in MULTI_MODEL_FAMILIES or feature not in expected:
            continue
        item = grouped[feature]
        item["slices"].add(row.get("slice") or "all")
        item["families"].add(family)
        delta = _safe_float(row.get("hgb_delta_mae_mean"))
        q_value = _safe_float(row.get("hgb_importance_q"))
        if delta is not None:
            item["delta_mae_sum"] += delta
            if delta > 0:
                item["positive_delta_mae_sum"] += delta
            if item["best_delta_mae"] is None or delta > item["best_delta_mae"]:
                item["best_delta_mae"] = delta
        if q_value is not None and (item["min_hgb_importance_q"] is None or q_value < item["min_hgb_importance_q"]):
            item["min_hgb_importance_q"] = q_value

    rows = []
    for feature in sorted(grouped):
        item = grouped[feature]
        rows.append({
            "feature": feature,
            "feature_kind": "global_model" if feature in GLOBAL_MODEL_FEATURES else "legacy_ensemble",
            "slices": sorted(item["slices"]),
            "families": sorted(item["families"]),
            "positive_delta_mae_sum": item["positive_delta_mae_sum"],
            "delta_mae_sum": item["delta_mae_sum"],
            "best_delta_mae": item["best_delta_mae"],
            "min_hgb_importance_q": item["min_hgb_importance_q"],
        })

    observed = {row["feature"] for row in rows}
    best = max(rows, key=lambda row: row["best_delta_mae"] if row["best_delta_mae"] is not None else float("-inf"), default=None)
    return {
        "path": str(hgb_permutation_path),
        "expected_global_model_features": list(GLOBAL_MODEL_FEATURES),
        "legacy_ensemble_features": list(LEGACY_ENSEMBLE_FEATURES),
        "observed_global_model_feature_count": len(set(GLOBAL_MODEL_FEATURES) & observed),
        "observed_legacy_ensemble_feature_count": len(set(LEGACY_ENSEMBLE_FEATURES) & observed),
        "missing_global_model_features": [feature for feature in GLOBAL_MODEL_FEATURES if feature not in observed],
        "best_feature": (best or {}).get("feature"),
        "best_delta_mae": (best or {}).get("best_delta_mae"),
        "rows": rows,
    }


def _find_early_slice(candidate: dict[str, Any]) -> dict[str, Any]:
    for key in ("by_cutoff_regime", "by_global_model_slice", "by_morning_slice"):
        for row in candidate.get(key) or []:
            group = str(row.get("group") or row.get("slice") or "").lower()
            if group in {"predawn", "morning", "early", "early_day"}:
                return row
    gate = candidate.get("global_model_gate") or {}
    early = gate.get("predawn") or gate.get("morning") or gate.get("early") or {}
    return early if isinstance(early, dict) else {}


def acceptance(
    candidate: dict[str, Any],
    source_evidence: dict[str, Any],
    permutation: dict[str, Any],
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    min_early_rows: int = DEFAULT_MIN_EARLY_ROWS,
) -> dict[str, Any]:
    blockers = []
    artifact_scope = isolated_global_model_artifact(candidate)
    early_slice = _find_early_slice(candidate)
    aggregate = candidate.get("aggregate") or {}
    blocked_validation = candidate.get("blocked_validation") or {}

    if (source_evidence.get("operational_contract") or {}).get("status") != "PASS":
        blockers.append({
            "code": "source_inventory_not_operationally_authorized",
            "detail": "; ".join(
                (source_evidence.get("operational_contract") or {}).get("blockers") or []
            ),
        })

    if not candidate:
        blockers.append({"code": "candidate_replay_missing", "detail": "missing candidate replay JSON"})
    if not artifact_scope["isolated"]:
        blockers.append({
            "code": "isolated_global_model_replay_missing",
            "detail": "candidate replay is not scoped to Open-Meteo global-model guidance",
        })
    if source_evidence.get("missing_catalog_global_model_features"):
        blockers.append({
            "code": "global_model_feature_catalog_incomplete",
            "detail": ", ".join(source_evidence.get("missing_catalog_global_model_features") or []),
        })
    if not source_evidence.get("global_model_source_status_seen") or not source_evidence.get("global_model_forecast_payload_seen"):
        blockers.append({
            "code": "global_model_payload_capture_missing",
            "detail": "open_meteo_global_models is not present in both source-status and forecast-payload inventory",
        })
    if source_evidence.get("missing_forecast_payload_folder_count", 0):
        blockers.append({
            "code": "global_model_payload_lineage_partial",
            "detail": f"{source_evidence.get('missing_forecast_payload_folder_count')} snapshot folders lack global-model payload rows",
        })
    if source_evidence.get("historical_archive_status") not in HISTORICAL_MODEL_STATUSES:
        blockers.append({
            "code": "historical_global_model_backfill_missing",
            "detail": str(source_evidence.get("historical_archive_status") or "missing inventory status"),
        })
    if not source_evidence.get("active_global_model_features"):
        blockers.append({
            "code": "global_model_features_not_selected_by_active_artifact",
            "detail": "global-model columns are cataloged but absent from active artifact feature_names",
        })
    if source_evidence.get("train_serve_parity_status") != "PASS":
        blockers.append({
            "code": "train_serve_parity_not_pass",
            "detail": str(source_evidence.get("train_serve_parity_status") or "-"),
        })
    if permutation.get("observed_global_model_feature_count", 0) == 0:
        blockers.append({
            "code": "global_model_permutation_evidence_missing",
            "detail": "no ECMWF/AIFS/AIGFS/GraphCast rows found in HGB permutation artifact",
        })
    elif permutation.get("missing_global_model_features"):
        blockers.append({
            "code": "global_model_permutation_features_missing",
            "detail": ", ".join(permutation.get("missing_global_model_features") or []),
        })
    if blocked_validation.get("passed") is not True:
        blockers.append({
            "code": "blocked_validation_failed",
            "detail": "; ".join(blocked_validation.get("reasons") or []) or "blocked validation did not pass",
        })

    early_n = int(early_slice.get("n") or 0)
    early_delta = early_slice.get("delta_vs_current")
    if early_n < min_early_rows:
        blockers.append({
            "code": "predawn_morning_slice_missing",
            "detail": f"predawn/morning slice rows {early_n} < {min_early_rows}",
        })
    elif early_delta is None or early_delta >= 0:
        blockers.append({
            "code": "predawn_morning_slice_no_current_lift",
            "detail": f"predawn/morning delta_vs_current={fmt_signed(early_delta, 4)}",
        })

    aggregate_delta = aggregate.get("delta_vs_current")
    if aggregate_delta is not None and aggregate_delta > current_tol:
        blockers.append({
            "code": "aggregate_regression",
            "detail": f"aggregate delta_vs_current={aggregate_delta:+.4f} > {current_tol:.4f}",
        })

    return {
        "status": "PASS" if not blockers else "BLOCK",
        "current_tolerance": current_tol,
        "min_early_rows": min_early_rows,
        "blockers": blockers,
        "artifact_scope": artifact_scope,
        "predawn_morning_slice": early_slice,
    }


def build_report_payload(
    source_inventory_json: str | Path = DEFAULT_SOURCE_INVENTORY_JSON,
    candidate_json: str | Path = DEFAULT_CANDIDATE_JSON,
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    min_early_rows: int = DEFAULT_MIN_EARLY_ROWS,
) -> dict[str, Any]:
    source_inventory = _read_json(source_inventory_json)
    candidate = _read_json(candidate_json)
    source_evidence = source_inventory_evidence(source_inventory)
    permutation = permutation_evidence(hgb_permutation)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "serving_or_release_authorization": False,
        "authorization_note": (
            "Detached report only; runtime current-input revalidation is required "
            "before serving or release authorization."
        ),
        "inputs": {
            "source_inventory_json": str(source_inventory_json),
            "candidate_json": str(candidate_json),
            "hgb_permutation": str(hgb_permutation),
        },
        "source_inventory": source_evidence,
        "candidate": {
            "artifact": candidate.get("artifact") or {},
            "aggregate": candidate.get("aggregate") or {},
            "blocked_validation": candidate.get("blocked_validation") or {},
            "by_cutoff_regime": candidate.get("by_cutoff_regime") or [],
            "global_model_gate": candidate.get("global_model_gate") or {},
            "verdict": candidate.get("verdict"),
            "cutover_decision": candidate.get("cutover_decision"),
        },
        "permutation_evidence": permutation,
        "acceptance": acceptance(
            candidate,
            source_evidence,
            permutation,
            current_tol=current_tol,
            min_early_rows=min_early_rows,
        ),
    }


def _permutation_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("feature"),
            row.get("feature_kind"),
            ", ".join(row.get("slices") or []),
            fmt_num(row.get("positive_delta_mae_sum"), 6),
            fmt_num(row.get("best_delta_mae"), 6),
            fmt_num(row.get("min_hgb_importance_q"), 4),
        ]
        for row in rows
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    acceptance_payload = payload.get("acceptance") or {}
    blockers = acceptance_payload.get("blockers") or []
    source_inventory = payload.get("source_inventory") or {}
    candidate = payload.get("candidate") or {}
    artifact = candidate.get("artifact") or {}
    permutation = payload.get("permutation_evidence") or {}

    lines = [
        "# Global Model Guidance Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Gate status: `{acceptance_payload.get('status')}`",
        "Serving/release authorization: `false`",
        (
            "This detached report cannot authorize serving or release; runtime "
            "current-input revalidation is required."
        ),
        "",
        "## Source Inventory",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Family", source_inventory.get("family_id") or "-"],
            ["Source keys", ", ".join(source_inventory.get("source_keys") or []) or "-"],
            ["Source status sources", ", ".join(source_inventory.get("source_status_sources_seen") or []) or "-"],
            ["Forecast payload sources", ", ".join(source_inventory.get("forecast_payload_sources_seen") or []) or "-"],
            ["Missing payload folders", source_inventory.get("missing_forecast_payload_folder_count", 0)],
            ["Historical archive status", source_inventory.get("historical_archive_status") or "-"],
            ["Train/serve parity", source_inventory.get("train_serve_parity_status") or "-"],
            ["Catalog global-model features", len(source_inventory.get("catalog_global_model_features") or [])],
            ["Active global-model features", len(source_inventory.get("active_global_model_features") or [])],
        ],
    )
    lines += ["", "## Candidate Scope", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Artifact", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature subset", artifact.get("feature_subset") or "-"],
            ["Isolated global-model replay", "yes" if (acceptance_payload.get("artifact_scope") or {}).get("isolated") else "no"],
            ["Verdict", candidate.get("verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Predawn/morning rows", (acceptance_payload.get("predawn_morning_slice") or {}).get("n", 0)],
            ["Predawn/morning delta current", fmt_signed((acceptance_payload.get("predawn_morning_slice") or {}).get("delta_vs_current"), 4)],
        ],
    )
    lines += ["", "## Acceptance Blockers", ""]
    if blockers:
        lines += markdown_table(
            ["Code", "Detail"],
            [[blocker.get("code"), blocker.get("detail")] for blocker in blockers],
        )
    else:
        lines += ["No blockers."]

    lines += ["", "## Permutation Evidence", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Expected global-model features", len(permutation.get("expected_global_model_features") or [])],
            ["Observed global-model features", permutation.get("observed_global_model_feature_count", 0)],
            ["Observed legacy ensemble features", permutation.get("observed_legacy_ensemble_feature_count", 0)],
            ["Missing global-model features", ", ".join(permutation.get("missing_global_model_features") or []) or "-"],
            ["Best feature", permutation.get("best_feature") or "-"],
            ["Best feature delta MAE", fmt_num(permutation.get("best_delta_mae"), 6)],
        ],
    )
    lines += ["", "### Observed Guidance Rows", ""]
    lines += markdown_table(
        ["Feature", "Kind", "Slices", "Positive Delta MAE Sum", "Best Delta MAE", "Min q"],
        _permutation_rows(permutation.get("rows") or []),
    )
    lines += [
        "",
        "## Next Unblock",
        "",
        (
            "Backfill or replay-save Open-Meteo global-model runs, train/replay a global-model-scoped "
            "candidate with ECMWF/AIFS/AIGFS/GraphCast columns selected, and add a predawn/morning "
            "settlement slice."
        ),
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.source_inventory_json,
        args.candidate_json,
        args.hgb_permutation,
        current_tol=args.current_tol,
        min_early_rows=args.min_early_rows,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 189 global model guidance gate.")
    parser.add_argument("--source-inventory-json", default=str(DEFAULT_SOURCE_INVENTORY_JSON))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    parser.add_argument("--min-early-rows", type=int, default=DEFAULT_MIN_EARLY_ROWS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Global model guidance gate: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
