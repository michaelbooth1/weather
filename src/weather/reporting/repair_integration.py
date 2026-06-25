"""First-class active-contract integration for validated repair row exports."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import config_path, data_path
from weather.reporting.candidate_hourly_performance import read_variant_rows
from weather.reporting.candidate_variant_replay_summary import (
    DEFAULT_SOURCE_CANDIDATE_JSON,
    build_variant_replay_summary,
    write_outputs as write_replay_summary_outputs,
)
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.multi_variant_shadow import LONG_TABLE_COLUMNS, OBSERVATION_KEY_FIELDS
from weather.reporting.variant_registry import SCHEMA_VERSION as VARIANT_REGISTRY_SCHEMA_VERSION
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("repair_integration")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_BASE_REGISTRY = config_path("model_variant_registry.json")
DEFAULT_REPAIR_SPECS = DEFAULT_BACKTEST_ROOT / "repair_integration_specs.json"
DEFAULT_OUT_ROWS = DEFAULT_BACKTEST_ROOT / "repair_integrated_active_rows.csv"
DEFAULT_OUT_JSON = DEFAULT_BACKTEST_ROOT / "repair_integration.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "repair_integration_report.md"
DEFAULT_ACTIVE_REPLAY_JSON = DEFAULT_BACKTEST_ROOT / "repair_integrated_active_replay_summary.json"
DEFAULT_ACTIVE_REPLAY_REPORT = DEFAULT_BACKTEST_ROOT / "repair_integrated_active_replay_summary_report.md"
DEFAULT_REGISTRY_OUT = DEFAULT_BACKTEST_ROOT / "repair_integration_registry.json"
DEFAULT_CONTRACT_OUT = DEFAULT_BACKTEST_ROOT / "repair_integration_contract.json"
DEFAULT_VARIANT_ID = "repair_integrated_active_candidate_v0_1"
DEFAULT_VARIANT_FAMILY = "repair_integrated_active_candidate"
LIVE_RUNTIME = "repair_integration_active_contract"
REPLAY_PREDICTION_FUNCTION = "weather.reporting.repair_integration:build_payload"
HARD_NON_COUNTABLE_MARKERS = ("same_corpus", "diagnostic_row_export")
SURROGATE_MARKER = "row_export_surrogate"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_path(value: str | Path | None) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if path in (None, ""):
        return {}
    value = Path(path)
    if not value.exists():
        return {}
    payload = json.loads(value.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_repair_specs(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        specs = payload
    elif isinstance(payload, dict):
        specs = payload.get("repairs") or payload.get("repair_specs") or []
    else:
        specs = []
    if not isinstance(specs, list):
        raise ValueError("repair specs JSON must contain a list or a repairs list")
    return [dict(spec) for spec in specs if isinstance(spec, dict)]


def _repair_id(spec: dict[str, Any], index: int) -> str:
    return str(spec.get("repair_id") or spec.get("id") or f"repair_{index + 1}")


def _source_summary(spec: dict[str, Any]) -> dict[str, Any]:
    inline = spec.get("summary")
    if isinstance(inline, dict):
        return dict(inline)
    return _read_json(spec.get("summary_path") or spec.get("validation_summary_path"))


def _validation_status(spec: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    blocked = summary.get("blocked_validation") or {}
    evidence = (
        summary.get("validation_evidence")
        or blocked.get("validation_evidence")
        or spec.get("validation_evidence")
        or "missing"
    )
    metric_passed = bool(
        summary.get("row_export_metric_passed")
        or blocked.get("metric_passed")
        or spec.get("metric_passed")
    )
    active_passed = evidence == "active_replay_contract" and bool(
        blocked.get("passed") or summary.get("verdict") == "PASS" or spec.get("validated")
    )
    surrogate_validated = evidence == "row_export_surrogate" and bool(
        metric_passed or spec.get("validated")
    )
    explicit_validated = bool(spec.get("validated")) and evidence not in {"missing", ""}
    validated = active_passed or surrogate_validated or explicit_validated
    return {
        "source_validation_evidence": evidence,
        "source_metric_passed": metric_passed,
        "source_blocked_validation_passed": blocked.get("passed"),
        "source_verdict": summary.get("verdict"),
        "validated": bool(validated),
        "source_summary_path": _as_path(spec.get("summary_path") or spec.get("validation_summary_path")),
    }


def _observation_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in OBSERVATION_KEY_FIELDS)


def _marker_blockers(row: dict[str, Any]) -> list[str]:
    blockers = []
    for key, value in row.items():
        text = str(value or "").strip().lower()
        if not text:
            continue
        for marker in HARD_NON_COUNTABLE_MARKERS:
            if marker in text:
                blockers.append(f"{key}={value}")
                break
    return blockers


def _clean_integrated_row(
    row: dict[str, Any],
    *,
    variant_id: str,
    variant_family: str,
    repair_id: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    blockers = _marker_blockers(row)
    if blockers:
        raise ValueError(
            f"repair row {repair_id} contains non-integratable marker(s): "
            + "; ".join(blockers[:5])
        )
    output = {}
    for key, value in row.items():
        if key.startswith("_") or key in {"capture_hour", "variant_probability"}:
            continue
        if SURROGATE_MARKER in str(value or "").strip().lower():
            continue
        output[key] = value
    output.update({
        "variant_id": variant_id,
        "variant_family": variant_family,
        "uses_market_features": "false",
        "is_control": "false",
        "claim_lane": "weather_only_core_model",
        "counts_toward_weather_model_promotion": "true",
        "quote_risk_eligible": "false",
        "quote_risk_gate_reason": "weather_only_core_model",
        "postprocess_config_hash": variant_id,
        "repair_integration_status": "active_replay_contract",
        "repair_integration_source_repair_id": repair_id,
        "repair_integration_generated_at_utc": generated_at_utc,
    })
    if not output.get("recorded_probability"):
        output["recorded_probability"] = output.get("probability")
    return output


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    fields = list(LONG_TABLE_COLUMNS)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields


def write_rows(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _fieldnames(rows)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output


def active_contract(
    rows_out: str | Path,
    *,
    variant_id: str = DEFAULT_VARIANT_ID,
    variant_family: str = DEFAULT_VARIANT_FAMILY,
    repair_specs_path: str | Path | None = None,
    source_candidate_json: str | Path | None = None,
    repair_ids: list[str] | None = None,
) -> dict[str, Any]:
    contract = {
        "variant_id": variant_id,
        "variant_family": variant_family,
        "lifecycle": "active",
        "track": "no_market",
        "roles": ["candidate", "no-market", "active-bakeoff", "repair-integrated"],
        "active_for_headline": True,
        "artifact_required": False,
        "prediction_function": REPLAY_PREDICTION_FUNCTION,
        "prediction_mode": "band_binary",
        "export_family": variant_family,
        "default_export_path": str(rows_out).replace("\\", "/"),
        "postprocess_config_hash": variant_id,
        "live_runtime": LIVE_RUNTIME,
        "roadmap_items": [315],
        "repair_integration": {
            "repair_ids": sorted(repair_ids or []),
            "status": "configured",
        },
    }
    if repair_specs_path not in (None, ""):
        contract["repair_specs_path"] = str(repair_specs_path).replace("\\", "/")
    if source_candidate_json not in (None, ""):
        contract["source_candidate_json"] = str(source_candidate_json).replace("\\", "/")
    return contract


def write_contract(path: str | Path, contract: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def write_registry(
    path: str | Path,
    *,
    base_registry: str | Path | None,
    contract: dict[str, Any],
    generated_at_utc: str,
) -> tuple[Path, dict[str, Any]]:
    if base_registry not in (None, "") and Path(base_registry).exists():
        registry = json.loads(Path(base_registry).read_text(encoding="utf-8"))
    else:
        registry = {
            "schema_version": VARIANT_REGISTRY_SCHEMA_VERSION,
            "description": "Generated repair-integration active registry sidecar.",
            "variants": [],
        }
    variants = [
        dict(row)
        for row in registry.get("variants") or []
        if row.get("variant_id") != contract.get("variant_id")
    ]
    variants.append(contract)
    registry["schema_version"] = registry.get("schema_version") or VARIANT_REGISTRY_SCHEMA_VERSION
    registry["variants"] = variants
    registry["updated_at_utc"] = generated_at_utc
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    registry["path"] = str(output)
    registry["exists"] = True
    registry["by_id"] = {
        str(row.get("variant_id")): dict(row)
        for row in variants
        if row.get("variant_id")
    }
    return output, registry


def _load_integratable_repairs(
    repair_specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    statuses = []
    integratable = []
    blockers = []
    for index, spec in enumerate(repair_specs):
        repair_id = _repair_id(spec, index)
        rows_path = spec.get("rows_path") or spec.get("variant_rows") or spec.get("path")
        summary = _source_summary(spec)
        validation = _validation_status(spec, summary)
        preview_only = bool(spec.get("preview_only") or spec.get("not_yet_integrated"))
        status = {
            "repair_id": repair_id,
            "rows_path": _as_path(rows_path),
            "priority": int(spec.get("priority") or 0),
            "serving_change": bool(spec.get("serving_change", True)),
            "preview_only": preview_only,
            **validation,
        }
        if not rows_path:
            status["integration_status"] = "blocked"
            status["reason"] = "repair rows_path is missing"
            blockers.append(f"{repair_id}: rows_path is missing")
            statuses.append(status)
            continue
        if preview_only:
            status["integration_status"] = "not_yet_integrated"
            status["reason"] = "surrogate evidence is preview-only until active-contract integration"
            statuses.append(status)
            continue
        if not validation["validated"]:
            status["integration_status"] = "not_yet_integrated"
            status["reason"] = "repair has not passed source validation metrics"
            statuses.append(status)
            continue
        rows = read_variant_rows(rows_path)
        if not rows:
            status["integration_status"] = "blocked"
            status["reason"] = "repair rows have no scoreable observations"
            blockers.append(f"{repair_id}: no scoreable rows")
            statuses.append(status)
            continue
        duplicate_count = len(rows) - len({_observation_key(row) for row in rows})
        if duplicate_count:
            status["integration_status"] = "blocked"
            status["reason"] = f"repair rows contain {duplicate_count} duplicate observation key(s)"
            blockers.append(f"{repair_id}: duplicate observation rows")
            statuses.append(status)
            continue
        status["source_rows"] = len(rows)
        status["integration_status"] = "ready_to_integrate"
        statuses.append(status)
        integratable.append({"spec": spec, "status": status, "rows": rows})
    return statuses, integratable, blockers


def _mark_integrated_statuses(
    statuses: list[dict[str, Any]],
    consolidation: dict[str, Any],
) -> list[dict[str, Any]]:
    rows_by_repair = consolidation.get("integrated_rows_by_repair") or {}
    updated = []
    for status in statuses:
        row = dict(status)
        repair_id = row.get("repair_id")
        if row.get("integration_status") == "ready_to_integrate":
            integrated_rows = int(rows_by_repair.get(repair_id, 0) or 0)
            if integrated_rows:
                row["integration_status"] = "integrated"
                row["integrated_rows"] = integrated_rows
                row["reason"] = "folded into active replay/export contract"
            else:
                row["integration_status"] = "not_yet_integrated"
                row["reason"] = "all rows were superseded during consolidation"
        updated.append(row)
    return updated


def _consolidate_rows(
    repairs: list[dict[str, Any]],
    *,
    variant_id: str,
    variant_family: str,
    generated_at_utc: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: dict[tuple[str, ...], dict[str, Any]] = {}
    selected_source: dict[tuple[str, ...], str] = {}
    skipped = Counter()
    for repair in sorted(
        repairs,
        key=lambda item: (-int((item["status"] or {}).get("priority") or 0), item["status"].get("repair_id") or ""),
    ):
        repair_id = repair["status"]["repair_id"]
        for row in repair["rows"]:
            key = _observation_key(row)
            if key in selected:
                skipped[repair_id] += 1
                continue
            selected[key] = _clean_integrated_row(
                row,
                variant_id=variant_id,
                variant_family=variant_family,
                repair_id=repair_id,
                generated_at_utc=generated_at_utc,
            )
            selected_source[key] = repair_id
    rows = [selected[key] for key in sorted(selected)]
    source_counts = Counter(selected_source.values())
    return rows, {
        "integrated_rows": len(rows),
        "integrated_repair_ids": sorted(source_counts),
        "integrated_rows_by_repair": dict(sorted(source_counts.items())),
        "skipped_duplicate_rows_by_repair": dict(sorted(skipped.items())),
    }


def build_payload(
    repair_specs: list[dict[str, Any]] | None = None,
    *,
    repair_specs_path: str | Path | None = None,
    rows_out: str | Path = DEFAULT_OUT_ROWS,
    registry_out: str | Path = DEFAULT_REGISTRY_OUT,
    contract_out: str | Path = DEFAULT_CONTRACT_OUT,
    source_candidate_json: str | Path = DEFAULT_SOURCE_CANDIDATE_JSON,
    base_registry: str | Path | None = DEFAULT_BASE_REGISTRY,
    variant_id: str = DEFAULT_VARIANT_ID,
    variant_family: str = DEFAULT_VARIANT_FAMILY,
    current_tol: float = 0.003,
    market_tol: float = 0.003,
    min_market_days: int = 2,
) -> dict[str, Any]:
    generated_at = utc_iso()
    if repair_specs is None:
        if repair_specs_path in (None, ""):
            raise ValueError("repair_specs or repair_specs_path is required")
        repair_specs = read_repair_specs(repair_specs_path)
    statuses, integratable, blockers = _load_integratable_repairs(repair_specs)
    rows, consolidation = _consolidate_rows(
        integratable,
        variant_id=variant_id,
        variant_family=variant_family,
        generated_at_utc=generated_at,
    )
    statuses = _mark_integrated_statuses(statuses, consolidation)
    if not rows:
        blockers.append("no validated repair rows were integrated")
    rows_path = write_rows(rows_out, rows)
    contract = active_contract(
        rows_path,
        variant_id=variant_id,
        variant_family=variant_family,
        repair_specs_path=repair_specs_path,
        source_candidate_json=source_candidate_json,
        repair_ids=consolidation["integrated_repair_ids"],
    )
    contract_path = write_contract(contract_out, contract)
    registry_path, registry = write_registry(
        registry_out,
        base_registry=base_registry,
        contract=contract,
        generated_at_utc=generated_at,
    )
    active_replay_summary = None
    if rows:
        try:
            active_replay_summary = build_variant_replay_summary(
                rows_path,
                source_candidate_json,
                validation_evidence="active_replay_contract",
                current_tol=current_tol,
                market_tol=market_tol,
                min_market_days=min_market_days,
                active_registry_contract=contract,
                variant_registry=registry,
            )
        except Exception as exc:
            blockers.append(f"active replay contract validation failed: {exc}")
    active_blocked = (active_replay_summary or {}).get("blocked_validation") or {}
    active_passed = bool(active_blocked.get("passed"))
    status = "PASS" if rows and active_passed and not blockers else "BLOCK"
    validation_counts = Counter(row.get("source_validation_evidence") for row in statuses)
    integration_counts = Counter(row.get("integration_status") for row in statuses)
    aggregate = (active_replay_summary or {}).get("aggregate") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "status": status,
        "variant_id": variant_id,
        "variant_family": variant_family,
        "output_rows": str(rows_path),
        "registry_out": str(registry_path),
        "contract_out": str(contract_path),
        "source_candidate_json": str(source_candidate_json),
        "repair_specs_path": _as_path(repair_specs_path),
        "active_contract": contract,
        "summary": {
            "repair_count": len(statuses),
            "integrated_repair_count": len(consolidation["integrated_repair_ids"]),
            "integrated_rows": consolidation["integrated_rows"],
            "source_validation_evidence_counts": dict(sorted(validation_counts.items())),
            "integration_status_counts": dict(sorted(integration_counts.items())),
            "aggregate_delta_vs_market": aggregate.get("delta_vs_market"),
            "active_replay_contract_passed": active_passed,
            "active_replay_verdict": (active_replay_summary or {}).get("verdict"),
        },
        "repairs": statuses,
        "consolidation": consolidation,
        "blockers": blockers,
        "active_replay_summary": active_replay_summary or {},
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    active = payload.get("active_replay_summary") or {}
    aggregate = active.get("aggregate") or {}
    lines = [
        "# Repair Integration",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Active Contract",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Variant", payload.get("variant_id")],
                ["Rows", payload.get("output_rows")],
                ["Registry", payload.get("registry_out")],
                ["Contract", payload.get("contract_out")],
                ["Active replay verdict", summary.get("active_replay_verdict")],
                ["Active replay passed", summary.get("active_replay_contract_passed")],
                ["Aggregate delta vs market", fmt_signed(summary.get("aggregate_delta_vs_market"))],
            ],
        ),
        "",
        "## Consolidated Replay",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Rows", aggregate.get("n", 0)],
                ["Candidate Brier", fmt_num(aggregate.get("candidate_brier"))],
                ["Current Brier", fmt_num(aggregate.get("current_brier"))],
                ["Market Brier", fmt_num(aggregate.get("market_brier"))],
                ["Delta vs current", fmt_signed(aggregate.get("delta_vs_current"))],
                ["Delta vs market", fmt_signed(aggregate.get("delta_vs_market"))],
            ],
        ),
        "",
        "## Repairs",
        "",
        *markdown_table(
            ["Repair", "Evidence", "Status", "Rows", "Reason"],
            [
                [
                    row.get("repair_id"),
                    row.get("source_validation_evidence"),
                    row.get("integration_status"),
                    row.get("source_rows", 0),
                    row.get("reason") or "-",
                ]
                for row in payload.get("repairs") or []
            ],
        ),
        "",
        "## Blockers",
        "",
    ]
    lines.extend([f"- {blocker}" for blocker in payload.get("blockers") or []] or ["- none"])
    return "\n".join(lines) + "\n"


def write_json_report(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT_JSON,
    report_out: str | Path = DEFAULT_REPORT,
    *,
    active_replay_json_out: str | Path | None = None,
    active_replay_report_out: str | Path | None = None,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    active_replay = payload.get("active_replay_summary") or {}
    if active_replay and active_replay_json_out and active_replay_report_out:
        replay_json, replay_report = write_replay_summary_outputs(
            active_replay,
            active_replay_json_out,
            active_replay_report_out,
        )
        payload["promotion_candidate_json"] = str(replay_json)
        payload["promotion_candidate_report"] = str(replay_report)
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Integrate validated repair row exports into a first-class active replay contract."
    )
    parser.add_argument("--repair-specs", default=str(DEFAULT_REPAIR_SPECS))
    parser.add_argument("--rows-out", default=str(DEFAULT_OUT_ROWS))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--active-replay-json-out", default=str(DEFAULT_ACTIVE_REPLAY_JSON))
    parser.add_argument("--active-replay-report-out", default=str(DEFAULT_ACTIVE_REPLAY_REPORT))
    parser.add_argument("--registry-out", default=str(DEFAULT_REGISTRY_OUT))
    parser.add_argument("--contract-out", default=str(DEFAULT_CONTRACT_OUT))
    parser.add_argument("--base-registry", default=str(DEFAULT_BASE_REGISTRY))
    parser.add_argument("--source-candidate-json", default=str(DEFAULT_SOURCE_CANDIDATE_JSON))
    parser.add_argument("--variant-id", default=DEFAULT_VARIANT_ID)
    parser.add_argument("--variant-family", default=DEFAULT_VARIANT_FAMILY)
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-market-days", type=int, default=2)
    args = parser.parse_args(argv)
    payload = build_payload(
        repair_specs_path=args.repair_specs,
        rows_out=args.rows_out,
        registry_out=args.registry_out,
        contract_out=args.contract_out,
        base_registry=args.base_registry,
        source_candidate_json=args.source_candidate_json,
        variant_id=args.variant_id,
        variant_family=args.variant_family,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_market_days=args.min_market_days,
    )
    json_path, report_path = write_json_report(
        payload,
        args.out_json,
        args.report,
        active_replay_json_out=args.active_replay_json_out,
        active_replay_report_out=args.active_replay_report_out,
    )
    print(f"Repair integration: {payload['status']}")
    print(f"Rows written to {payload['output_rows']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
