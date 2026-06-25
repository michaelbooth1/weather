"""Marine water-temperature contrast gate for roadmap item 191."""

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
from weather.sources.marine_context import MARINE_CONTEXT_FEATURE_COLUMNS


SCHEMA_VERSION = "marine_contrast_gate_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SOURCE_INVENTORY_JSON = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_ABLATION_JSON = DEFAULT_BACKTEST_ROOT / "source_family_ablation_marine_context.json"
DEFAULT_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "item191_marine_contrast_replay.json"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item191_marine_contrast_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item191_marine_contrast_gate_report.md"
DEFAULT_CURRENT_TOL = 0.003
DEFAULT_MIN_ONSHORE_ROWS = 1

MARINE_SOURCE = "marine_context"
WATER_CONTRAST_FEATURES = (
    "marine_water_temp_native",
    "marine_water_minus_forecast_high",
    "marine_onshore_water_minus_forecast_high",
    "marine_onshore_cooling_potential",
    "marine_breeze_risk",
    "marine_layer_suppression",
)
SUPPORTING_MARINE_FEATURES = tuple(
    feature
    for feature in MARINE_CONTEXT_FEATURE_COLUMNS
    if feature not in WATER_CONTRAST_FEATURES
)
ISOLATED_MARINE_SUBSETS = {
    "marine_context",
    "marine_water_contrast",
    "coastal_context_marine_contrast",
}
MARINE_PERMUTATION_FAMILIES = {"marine_microclimate", "coastal_context"}
HISTORICAL_MARINE_STATUSES = {
    "marine_station_archive_available",
    "gridded_sst_archive_available",
    "glsea_oisst_archive_available",
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
    row = _find_inventory_row(source_inventory, "marine_context")
    feature_columns = set(row.get("feature_columns") or [])
    active_columns = set(row.get("active_model_feature_columns") or [])
    source_status = row.get("source_status") or {}
    source_status_seen = set(source_status.get("sources_seen") or [])
    catalog_contrast = [feature for feature in WATER_CONTRAST_FEATURES if feature in feature_columns]
    active_contrast = [feature for feature in WATER_CONTRAST_FEATURES if feature in active_columns]

    return {
        "family_id": row.get("family_id"),
        "source_keys": row.get("source_keys") or [],
        "historical_archive_status": row.get("historical_archive_status"),
        "live_only": row.get("live_only"),
        "live_only_policy": row.get("live_only_policy"),
        "train_serve_parity_status": row.get("train_serve_parity_status"),
        "lineage_status": row.get("lineage_status"),
        "active_model_usage_status": row.get("active_model_usage_status"),
        "catalog_contrast_features": catalog_contrast,
        "missing_catalog_contrast_features": [feature for feature in WATER_CONTRAST_FEATURES if feature not in feature_columns],
        "active_contrast_features": active_contrast,
        "missing_active_contrast_features": [feature for feature in WATER_CONTRAST_FEATURES if feature not in active_columns],
        "source_status_sources_seen": sorted(source_status_seen),
        "marine_source_status_seen": MARINE_SOURCE in source_status_seen,
        "source_status_rows": source_status.get("rows", 0),
        "source_status_folder_count": source_status.get("folder_count", 0),
        "missing_source_status_folder_count": source_status.get("missing_folder_count", 0),
        "missing_source_status_folder_samples": source_status.get("missing_folder_samples") or [],
        "feature_missingness": row.get("feature_missingness") or {},
    }


def ablation_evidence(ablation_payload: dict[str, Any]) -> dict[str, Any]:
    variants = ablation_payload.get("variants") or []
    variant = next((row for row in variants if row.get("variant") == "marine_context"), {})
    return {
        "schema_version": ablation_payload.get("schema_version"),
        "summary": ablation_payload.get("summary") or {},
        "variant": variant,
        "delta": variant.get("delta"),
        "days": variant.get("days"),
        "n": variant.get("n"),
        "days_source_helped": variant.get("days_source_helped"),
        "days_source_hurt": variant.get("days_source_hurt"),
    }


def isolated_marine_artifact(candidate: dict[str, Any]) -> dict[str, Any]:
    artifact = candidate.get("artifact") or {}
    subset = artifact.get("feature_subset")
    contract = artifact.get("feature_subset_contract") or {}
    contract_name = contract.get("name")
    allowed_families = set(contract.get("allowed_feature_families") or [])
    reasons = []
    if subset in ISOLATED_MARINE_SUBSETS:
        reasons.append(f"feature_subset={subset}")
    if contract_name in ISOLATED_MARINE_SUBSETS:
        reasons.append(f"feature_subset_contract.name={contract_name}")
    marine_allowed = {"marine_context", "market_climate_context", "market_band_geometry"}
    if allowed_families and allowed_families <= marine_allowed:
        if "marine_context" in allowed_families:
            reasons.append("feature_subset_contract.allowed_feature_families isolates marine context plus band context")

    return {
        "isolated": bool(reasons),
        "basis": reasons,
        "feature_subset": subset,
        "contract_name": contract_name,
        "allowed_feature_families": sorted(allowed_families),
    }


def candidate_contrast_features(candidate: dict[str, Any]) -> list[str]:
    artifact = (candidate or {}).get("artifact") or {}
    names = set(artifact.get("feature_names") or [])
    return [feature for feature in WATER_CONTRAST_FEATURES if feature in names]


def candidate_sidecar_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    diagnostics = (candidate or {}).get("diagnostics") or {}
    filled_columns = diagnostics.get("marine_water_contrast_sidecar_filled_columns") or {}
    return {
        "loaded_markets": diagnostics.get("marine_water_contrast_sidecar_loaded_markets") or [],
        "rows_applied": int(diagnostics.get("marine_water_contrast_sidecar_rows_applied") or 0),
        "rows_missing": int(diagnostics.get("marine_water_contrast_sidecar_rows_missing") or 0),
        "rows_without_observed_features": int(
            diagnostics.get("marine_water_contrast_sidecar_rows_without_observed_features") or 0
        ),
        "filled_contrast_features": [
            feature for feature in WATER_CONTRAST_FEATURES if int(filled_columns.get(feature) or 0) > 0
        ],
        "filled_columns": filled_columns,
    }


def permutation_evidence(hgb_permutation_path: str | Path = DEFAULT_HGB_PERMUTATION) -> dict[str, Any]:
    expected = set(WATER_CONTRAST_FEATURES) | set(SUPPORTING_MARINE_FEATURES)
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
        if family not in MARINE_PERMUTATION_FAMILIES or feature not in expected:
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
            "feature_kind": "water_contrast" if feature in WATER_CONTRAST_FEATURES else "supporting_marine",
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
        "expected_water_contrast_features": list(WATER_CONTRAST_FEATURES),
        "supporting_marine_features": list(SUPPORTING_MARINE_FEATURES),
        "observed_water_contrast_feature_count": len(set(WATER_CONTRAST_FEATURES) & observed),
        "observed_supporting_marine_feature_count": len(set(SUPPORTING_MARINE_FEATURES) & observed),
        "missing_water_contrast_features": [feature for feature in WATER_CONTRAST_FEATURES if feature not in observed],
        "best_feature": (best or {}).get("feature"),
        "best_delta_mae": (best or {}).get("best_delta_mae"),
        "rows": rows,
    }


def _find_onshore_slice(candidate: dict[str, Any]) -> dict[str, Any]:
    for key in ("by_marine_breeze_slice", "by_onshore_breeze_slice", "by_marine_context_slice"):
        for row in candidate.get(key) or []:
            group = str(row.get("group") or row.get("slice") or "").lower()
            if group in {"onshore", "breeze_risk", "marine_layer_suppression", "onshore_breeze"}:
                return row
    gate = candidate.get("marine_contrast_gate") or {}
    onshore = gate.get("onshore_breeze") or gate.get("breeze_risk") or {}
    return onshore if isinstance(onshore, dict) else {}


def acceptance(
    candidate: dict[str, Any],
    source_evidence: dict[str, Any],
    ablation: dict[str, Any],
    permutation: dict[str, Any],
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    min_onshore_rows: int = DEFAULT_MIN_ONSHORE_ROWS,
) -> dict[str, Any]:
    blockers = []
    artifact_scope = isolated_marine_artifact(candidate)
    onshore_slice = _find_onshore_slice(candidate)
    aggregate = candidate.get("aggregate") or {}
    blocked_validation = candidate.get("blocked_validation") or {}
    candidate_features = candidate_contrast_features(candidate)
    sidecar_evidence = candidate_sidecar_evidence(candidate)

    if not candidate:
        blockers.append({"code": "candidate_replay_missing", "detail": "missing candidate replay JSON"})
    if not artifact_scope["isolated"]:
        blockers.append({
            "code": "isolated_marine_replay_missing",
            "detail": "candidate replay is not scoped to marine water-contrast features",
        })
    if source_evidence.get("missing_catalog_contrast_features"):
        blockers.append({
            "code": "marine_contrast_feature_catalog_incomplete",
            "detail": ", ".join(source_evidence.get("missing_catalog_contrast_features") or []),
        })
    if not source_evidence.get("marine_source_status_seen"):
        blockers.append({
            "code": "marine_source_status_missing",
            "detail": "marine_context is absent from source-status inventory",
        })
    if source_evidence.get("missing_source_status_folder_count", 0):
        blockers.append({
            "code": "marine_source_lineage_partial",
            "detail": f"{source_evidence.get('missing_source_status_folder_count')} snapshot folders lack marine source rows",
        })
    if source_evidence.get("historical_archive_status") not in HISTORICAL_MARINE_STATUSES:
        blockers.append({
            "code": "historical_marine_backfill_missing",
            "detail": str(source_evidence.get("historical_archive_status") or "missing inventory status"),
        })
    if artifact_scope["isolated"] and not candidate_features:
        blockers.append({
            "code": "marine_contrast_features_not_selected_by_candidate_artifact",
            "detail": "marine contrast columns are absent from the scoped candidate artifact feature_names",
        })
    if source_evidence.get("train_serve_parity_status") != "PASS":
        blockers.append({
            "code": "train_serve_parity_not_pass",
            "detail": str(source_evidence.get("train_serve_parity_status") or "-"),
        })
    if (ablation.get("delta") is None) or float(ablation.get("delta") or 0.0) <= 0.0:
        blockers.append({
            "code": "marine_ablation_no_positive_lift",
            "detail": f"marine_context ablation delta={fmt_signed(ablation.get('delta'), 4)}",
        })
    if permutation.get("observed_water_contrast_feature_count", 0) == 0:
        blockers.append({
            "code": "marine_contrast_permutation_evidence_missing",
            "detail": "no water-contrast rows found in HGB permutation artifact",
        })
    elif permutation.get("missing_water_contrast_features"):
        blockers.append({
            "code": "marine_contrast_permutation_features_missing",
            "detail": ", ".join(permutation.get("missing_water_contrast_features") or []),
        })
    if blocked_validation.get("passed") is not True:
        blockers.append({
            "code": "blocked_validation_failed",
            "detail": "; ".join(blocked_validation.get("reasons") or []) or "blocked validation did not pass",
        })

    onshore_n = int(onshore_slice.get("n") or 0)
    onshore_delta = onshore_slice.get("delta_vs_current")
    if onshore_n < min_onshore_rows:
        blockers.append({
            "code": "onshore_breeze_settlement_slice_missing",
            "detail": f"onshore/breeze slice rows {onshore_n} < {min_onshore_rows}",
        })
    elif onshore_delta is None or onshore_delta >= 0:
        blockers.append({
            "code": "onshore_breeze_slice_no_current_lift",
            "detail": f"onshore/breeze delta_vs_current={fmt_signed(onshore_delta, 4)}",
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
        "min_onshore_rows": min_onshore_rows,
        "blockers": blockers,
        "artifact_scope": artifact_scope,
        "candidate_contrast_features": candidate_features,
        "candidate_sidecar_evidence": sidecar_evidence,
        "onshore_breeze_slice": onshore_slice,
    }


def build_report_payload(
    source_inventory_json: str | Path = DEFAULT_SOURCE_INVENTORY_JSON,
    ablation_json: str | Path = DEFAULT_ABLATION_JSON,
    candidate_json: str | Path = DEFAULT_CANDIDATE_JSON,
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    min_onshore_rows: int = DEFAULT_MIN_ONSHORE_ROWS,
) -> dict[str, Any]:
    source_inventory = _read_json(source_inventory_json)
    ablation_payload = _read_json(ablation_json)
    candidate = _read_json(candidate_json)
    source_evidence = source_inventory_evidence(source_inventory)
    ablation = ablation_evidence(ablation_payload)
    permutation = permutation_evidence(hgb_permutation)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "source_inventory_json": str(source_inventory_json),
            "ablation_json": str(ablation_json),
            "candidate_json": str(candidate_json),
            "hgb_permutation": str(hgb_permutation),
        },
        "source_inventory": source_evidence,
        "ablation_evidence": ablation,
        "candidate": {
            "artifact": candidate.get("artifact") or {},
            "aggregate": candidate.get("aggregate") or {},
            "blocked_validation": candidate.get("blocked_validation") or {},
            "by_marine_breeze_slice": candidate.get("by_marine_breeze_slice") or candidate.get("by_onshore_breeze_slice") or [],
            "diagnostics": candidate.get("diagnostics") or {},
            "verdict": candidate.get("verdict"),
            "cutover_decision": candidate.get("cutover_decision"),
            "candidate_contrast_features": candidate_contrast_features(candidate),
            "candidate_sidecar_evidence": candidate_sidecar_evidence(candidate),
        },
        "permutation_evidence": permutation,
        "acceptance": acceptance(
            candidate,
            source_evidence,
            ablation,
            permutation,
            current_tol=current_tol,
            min_onshore_rows=min_onshore_rows,
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
    ablation = payload.get("ablation_evidence") or {}
    candidate = payload.get("candidate") or {}
    artifact = candidate.get("artifact") or {}
    permutation = payload.get("permutation_evidence") or {}
    sidecar = acceptance_payload.get("candidate_sidecar_evidence") or candidate.get("candidate_sidecar_evidence") or {}
    onshore_slice = acceptance_payload.get("onshore_breeze_slice") or {}
    onshore_delta = onshore_slice.get("delta_vs_current")

    lines = [
        "# Marine Contrast Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Gate status: `{acceptance_payload.get('status')}`",
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
            ["Missing source folders", source_inventory.get("missing_source_status_folder_count", 0)],
            ["Historical archive status", source_inventory.get("historical_archive_status") or "-"],
            ["Train/serve parity", source_inventory.get("train_serve_parity_status") or "-"],
            ["Catalog contrast features", len(source_inventory.get("catalog_contrast_features") or [])],
            ["Active contrast features", len(source_inventory.get("active_contrast_features") or [])],
        ],
    )
    lines += ["", "## Existing Ablation", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variant", (ablation.get("variant") or {}).get("variant") or "-"],
            ["Rows", ablation.get("n") or 0],
            ["Days", ablation.get("days") or 0],
            ["Delta", fmt_signed(ablation.get("delta"), 4)],
            ["Days helped", ablation.get("days_source_helped") or 0],
            ["Days hurt", ablation.get("days_source_hurt") or 0],
        ],
    )
    lines += ["", "## Candidate Scope", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Artifact", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature subset", artifact.get("feature_subset") or "-"],
            ["Isolated marine replay", "yes" if (acceptance_payload.get("artifact_scope") or {}).get("isolated") else "no"],
            ["Verdict", candidate.get("verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Candidate contrast features", len(candidate.get("candidate_contrast_features") or [])],
            ["Onshore/breeze rows", onshore_slice.get("n", 0)],
            ["Onshore/breeze delta current", fmt_signed(onshore_delta, 4)],
            ["Marine sidecar markets", ", ".join(sidecar.get("loaded_markets") or []) or "-"],
            ["Marine sidecar rows applied", sidecar.get("rows_applied", 0)],
            ["Marine sidecar rows missing", sidecar.get("rows_missing", 0)],
            ["Marine sidecar rows without observed features", sidecar.get("rows_without_observed_features", 0)],
            ["Sidecar-filled contrast features", ", ".join(sidecar.get("filled_contrast_features") or []) or "-"],
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
            ["Expected water-contrast features", len(permutation.get("expected_water_contrast_features") or [])],
            ["Observed water-contrast features", permutation.get("observed_water_contrast_feature_count", 0)],
            ["Observed supporting marine features", permutation.get("observed_supporting_marine_feature_count", 0)],
            ["Missing water-contrast features", ", ".join(permutation.get("missing_water_contrast_features") or []) or "-"],
            ["Best feature", permutation.get("best_feature") or "-"],
            ["Best feature delta MAE", fmt_num(permutation.get("best_delta_mae"), 6)],
        ],
    )
    lines += ["", "### Observed Marine Rows", ""]
    lines += markdown_table(
        ["Feature", "Kind", "Slices", "Positive Delta MAE Sum", "Best Delta MAE", "Min q"],
        _permutation_rows(permutation.get("rows") or []),
    )
    next_unblock = (
        "Refresh broad marine ablation/permutation evidence and resolve the daily-first market-tolerance "
        "blocker before any cutover; the sidecar-backed onshore/breeze settlement slice is present."
        if onshore_slice.get("n", 0) and onshore_delta is not None and onshore_delta < 0
        else (
            "Backfill station history or add GLSEA/OISST gridded SST, train/replay a marine-contrast "
            "candidate with water-contrast columns selected, and add an onshore/breeze settlement slice."
        )
    )
    lines += ["", "## Next Unblock", "", next_unblock]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.source_inventory_json,
        args.ablation_json,
        args.candidate_json,
        args.hgb_permutation,
        current_tol=args.current_tol,
        min_onshore_rows=args.min_onshore_rows,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 191 marine contrast gate.")
    parser.add_argument("--source-inventory-json", default=str(DEFAULT_SOURCE_INVENTORY_JSON))
    parser.add_argument("--ablation-json", default=str(DEFAULT_ABLATION_JSON))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    parser.add_argument("--min-onshore-rows", type=int, default=DEFAULT_MIN_ONSHORE_ROWS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Marine contrast gate: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
