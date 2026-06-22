"""NBM probabilistic Tmax gate for roadmap item 190."""

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
from weather.sources.nbm_probabilistic_tmax import NBM_PROB_TMAX_FEATURE_COLUMNS


SCHEMA_VERSION = "nbm_probabilistic_tmax_gate_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SOURCE_INVENTORY_JSON = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_all_hours_replay.json"
DEFAULT_HGB_PERMUTATION = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_hgb_permutation.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item190_nbm_probabilistic_tmax_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item190_nbm_probabilistic_tmax_gate_report.md"
DEFAULT_CURRENT_TOL = 0.003
DEFAULT_MIN_US_MARKET_ROWS = 1

NBM_SOURCE = "nbm_probabilistic_tmax"
NBM_FEATURES = tuple(NBM_PROB_TMAX_FEATURE_COLUMNS)
ISOLATED_NBM_SUBSETS = {
    "nbm_probabilistic_tmax",
    "official_us_guidance_nbm_prob",
    "forecast_nbm_probabilistic_tmax",
}
NBM_PERMUTATION_FAMILIES = {"official_us_guidance", "open_meteo_forecast_profile", "forecast_source_state"}
HISTORICAL_NBM_STATUSES = {
    "nbm_probabilistic_tmax_archive_available",
    "qmd_archive_available",
    "nbp_station_archive_available",
    "historical_nbm_prob_archive_available",
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
    row = _find_inventory_row(source_inventory, "nws_grid")
    feature_columns = set(row.get("feature_columns") or [])
    active_columns = set(row.get("active_model_feature_columns") or [])
    source_status = row.get("source_status") or {}
    forecast_payloads = row.get("forecast_payloads") or {}
    source_status_seen = set(source_status.get("sources_seen") or [])
    forecast_payloads_seen = set(forecast_payloads.get("sources_seen") or [])
    catalog_nbm = [feature for feature in NBM_FEATURES if feature in feature_columns]
    active_nbm = [feature for feature in NBM_FEATURES if feature in active_columns]

    return {
        "family_id": row.get("family_id"),
        "source_keys": row.get("source_keys") or [],
        "historical_archive_status": row.get("historical_archive_status"),
        "live_only": row.get("live_only"),
        "live_only_policy": row.get("live_only_policy"),
        "train_serve_parity_status": row.get("train_serve_parity_status"),
        "lineage_status": row.get("lineage_status"),
        "active_model_usage_status": row.get("active_model_usage_status"),
        "catalog_nbm_features": catalog_nbm,
        "missing_catalog_nbm_features": [feature for feature in NBM_FEATURES if feature not in feature_columns],
        "active_nbm_features": active_nbm,
        "missing_active_nbm_features": [feature for feature in NBM_FEATURES if feature not in active_columns],
        "source_status_sources_seen": sorted(source_status_seen),
        "forecast_payload_sources_seen": sorted(forecast_payloads_seen),
        "nbm_source_status_seen": NBM_SOURCE in source_status_seen,
        "nbm_forecast_payload_seen": NBM_SOURCE in forecast_payloads_seen,
        "forecast_payload_rows": forecast_payloads.get("rows", 0),
        "forecast_payload_folder_count": forecast_payloads.get("folder_count", 0),
        "missing_forecast_payload_folder_count": forecast_payloads.get("missing_folder_count", 0),
        "missing_forecast_payload_folder_samples": forecast_payloads.get("missing_folder_samples") or [],
        "feature_missingness": row.get("feature_missingness") or {},
    }


def isolated_nbm_artifact(candidate: dict[str, Any]) -> dict[str, Any]:
    artifact = candidate.get("artifact") or {}
    subset = artifact.get("feature_subset")
    contract = artifact.get("feature_subset_contract") or {}
    contract_name = contract.get("name")
    allowed_families = set(contract.get("allowed_feature_families") or [])
    reasons = []
    if subset in ISOLATED_NBM_SUBSETS:
        reasons.append(f"feature_subset={subset}")
    if contract_name in ISOLATED_NBM_SUBSETS:
        reasons.append(f"feature_subset_contract.name={contract_name}")
    if allowed_families and allowed_families <= {"nbm_probabilistic_tmax", "market_climate_context"}:
        if "nbm_probabilistic_tmax" in allowed_families:
            reasons.append("feature_subset_contract.allowed_feature_families includes only NBM-prob plus context")

    return {
        "isolated": bool(reasons),
        "basis": reasons,
        "feature_subset": subset,
        "contract_name": contract_name,
        "allowed_feature_families": sorted(allowed_families),
    }


def permutation_evidence(hgb_permutation_path: str | Path = DEFAULT_HGB_PERMUTATION) -> dict[str, Any]:
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
        if family not in NBM_PERMUTATION_FAMILIES or feature not in NBM_FEATURES:
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
        "expected_features": list(NBM_FEATURES),
        "observed_expected_feature_count": len(observed),
        "missing_expected_features": [feature for feature in NBM_FEATURES if feature not in observed],
        "best_feature": (best or {}).get("feature"),
        "best_delta_mae": (best or {}).get("best_delta_mae"),
        "rows": rows,
    }


def _us_market_rows(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("by_nbm_us_market", "by_us_market", "nbm_prob_market_gate"):
        rows = candidate.get(key) or []
        if isinstance(rows, list) and rows:
            return rows
    gate = candidate.get("nbm_probabilistic_tmax_gate") or {}
    rows = gate.get("by_us_market") or []
    return rows if isinstance(rows, list) else []


def acceptance(
    candidate: dict[str, Any],
    source_evidence: dict[str, Any],
    permutation: dict[str, Any],
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    min_us_market_rows: int = DEFAULT_MIN_US_MARKET_ROWS,
) -> dict[str, Any]:
    blockers = []
    artifact_scope = isolated_nbm_artifact(candidate)
    market_rows = _us_market_rows(candidate)
    aggregate = candidate.get("aggregate") or {}
    blocked_validation = candidate.get("blocked_validation") or {}

    if not candidate:
        blockers.append({"code": "candidate_replay_missing", "detail": "missing candidate replay JSON"})
    if not artifact_scope["isolated"]:
        blockers.append({
            "code": "isolated_nbm_replay_missing",
            "detail": "candidate replay is not scoped to NBM probabilistic Tmax guidance",
        })
    if source_evidence.get("missing_catalog_nbm_features"):
        blockers.append({
            "code": "nbm_feature_catalog_incomplete",
            "detail": ", ".join(source_evidence.get("missing_catalog_nbm_features") or []),
        })
    if not source_evidence.get("nbm_source_status_seen"):
        blockers.append({
            "code": "nbm_source_status_missing",
            "detail": "nbm_probabilistic_tmax is absent from source-status inventory",
        })
    if not source_evidence.get("nbm_forecast_payload_seen"):
        blockers.append({
            "code": "nbm_forecast_payload_missing",
            "detail": "nbm_probabilistic_tmax is absent from forecast-payload inventory",
        })
    if source_evidence.get("missing_forecast_payload_folder_count", 0):
        blockers.append({
            "code": "nbm_payload_lineage_partial",
            "detail": f"{source_evidence.get('missing_forecast_payload_folder_count')} snapshot folders lack NBM payload rows",
        })
    if source_evidence.get("historical_archive_status") not in HISTORICAL_NBM_STATUSES:
        blockers.append({
            "code": "historical_nbm_backfill_missing",
            "detail": str(source_evidence.get("historical_archive_status") or "missing inventory status"),
        })
    if not source_evidence.get("active_nbm_features"):
        blockers.append({
            "code": "nbm_features_not_selected_by_active_artifact",
            "detail": "NBM probabilistic columns are cataloged but absent from active artifact feature_names",
        })
    if source_evidence.get("train_serve_parity_status") != "PASS":
        blockers.append({
            "code": "train_serve_parity_not_pass",
            "detail": str(source_evidence.get("train_serve_parity_status") or "-"),
        })
    if permutation.get("observed_expected_feature_count", 0) == 0:
        blockers.append({
            "code": "nbm_permutation_evidence_missing",
            "detail": "no NBM probabilistic Tmax rows found in HGB permutation artifact",
        })
    elif permutation.get("missing_expected_features"):
        blockers.append({
            "code": "nbm_permutation_features_missing",
            "detail": ", ".join(permutation.get("missing_expected_features") or []),
        })
    if blocked_validation.get("passed") is not True:
        blockers.append({
            "code": "blocked_validation_failed",
            "detail": "; ".join(blocked_validation.get("reasons") or []) or "blocked validation did not pass",
        })

    if len(market_rows) < min_us_market_rows:
        blockers.append({
            "code": "us_market_settlement_slices_missing",
            "detail": f"US market settlement rows {len(market_rows)} < {min_us_market_rows}",
        })
    else:
        regressions = [
            row
            for row in market_rows
            if row.get("delta_vs_current") is None or row.get("delta_vs_current") > current_tol
        ]
        if regressions:
            samples = ", ".join(str(row.get("group") or row.get("market_id") or "-") for row in regressions[:6])
            blockers.append({
                "code": "us_market_regression",
                "detail": f"{len(regressions)} US market rows regress current beyond tolerance: {samples}",
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
        "min_us_market_rows": min_us_market_rows,
        "blockers": blockers,
        "artifact_scope": artifact_scope,
        "us_market_rows": market_rows,
    }


def build_report_payload(
    source_inventory_json: str | Path = DEFAULT_SOURCE_INVENTORY_JSON,
    candidate_json: str | Path = DEFAULT_CANDIDATE_JSON,
    hgb_permutation: str | Path = DEFAULT_HGB_PERMUTATION,
    *,
    current_tol: float = DEFAULT_CURRENT_TOL,
    min_us_market_rows: int = DEFAULT_MIN_US_MARKET_ROWS,
) -> dict[str, Any]:
    source_inventory = _read_json(source_inventory_json)
    candidate = _read_json(candidate_json)
    source_evidence = source_inventory_evidence(source_inventory)
    permutation = permutation_evidence(hgb_permutation)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
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
            "by_nbm_us_market": _us_market_rows(candidate),
            "verdict": candidate.get("verdict"),
            "cutover_decision": candidate.get("cutover_decision"),
        },
        "permutation_evidence": permutation,
        "acceptance": acceptance(
            candidate,
            source_evidence,
            permutation,
            current_tol=current_tol,
            min_us_market_rows=min_us_market_rows,
        ),
    }


def _permutation_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("feature"),
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
        "# NBM Probabilistic Tmax Gate",
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
            ["Forecast payload sources", ", ".join(source_inventory.get("forecast_payload_sources_seen") or []) or "-"],
            ["Missing payload folders", source_inventory.get("missing_forecast_payload_folder_count", 0)],
            ["Historical archive status", source_inventory.get("historical_archive_status") or "-"],
            ["Train/serve parity", source_inventory.get("train_serve_parity_status") or "-"],
            ["Catalog NBM features", len(source_inventory.get("catalog_nbm_features") or [])],
            ["Active NBM features", len(source_inventory.get("active_nbm_features") or [])],
        ],
    )
    lines += ["", "## Candidate Scope", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Artifact", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature subset", artifact.get("feature_subset") or "-"],
            ["Isolated NBM replay", "yes" if (acceptance_payload.get("artifact_scope") or {}).get("isolated") else "no"],
            ["Verdict", candidate.get("verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["US market rows", len(acceptance_payload.get("us_market_rows") or [])],
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
            ["Expected NBM features", len(permutation.get("expected_features") or [])],
            ["Observed NBM features", permutation.get("observed_expected_feature_count", 0)],
            ["Missing expected features", ", ".join(permutation.get("missing_expected_features") or []) or "-"],
            ["Best feature", permutation.get("best_feature") or "-"],
            ["Best feature delta MAE", fmt_num(permutation.get("best_delta_mae"), 6)],
        ],
    )
    lines += ["", "### Observed NBM Rows", ""]
    lines += markdown_table(
        ["Feature", "Slices", "Positive Delta MAE Sum", "Best Delta MAE", "Min q"],
        _permutation_rows(permutation.get("rows") or []),
    )
    lines += [
        "",
        "## Next Unblock",
        "",
        (
            "Persist NBM probabilistic payloads, add QMD/bucket-edge or replay-safe station archives, "
            "train/replay an NBM-prob-scoped candidate, and add US-market settlement slices."
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
        min_us_market_rows=args.min_us_market_rows,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 190 NBM probabilistic Tmax gate.")
    parser.add_argument("--source-inventory-json", default=str(DEFAULT_SOURCE_INVENTORY_JSON))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--hgb-permutation", default=str(DEFAULT_HGB_PERMUTATION))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    parser.add_argument("--min-us-market-rows", type=int, default=DEFAULT_MIN_US_MARKET_ROWS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"NBM probabilistic Tmax gate: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
