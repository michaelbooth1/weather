"""Disposition gate for Item 138 weak input-family pruning."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item138_weak_input_family_gate")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_WEAK_INPUT = DEFAULT_BACKTEST_ROOT / "item138_weak_input_family_disposition.json"
DEFAULT_ITEM136 = DEFAULT_BACKTEST_ROOT / "item136_source_state_disposition.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item138_weak_input_family_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item138_weak_input_family_gate_report.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "ALLOW", "ALLOWED"}


def _first_blocker(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict) and first.get("detail"):
        return str(first.get("detail"))
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(blockers[0].get("detail") or blockers[0].get("gate") or blockers[0].get("category") or "")
    return ""


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def simple_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "disposition": payload.get("disposition"),
        "blocker_count": payload.get("blocker_count", len(payload.get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
    }


def weak_input_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    families = payload.get("families") or []
    preflight = payload.get("training_preflight") or {}
    regime_backfill = [row for row in families if row.get("disposition") == "regime_backfill"]
    diagnostic = [row for row in families if row.get("disposition") == "diagnostic_only"]
    warnings = preflight.get("warnings") or []
    warning_families = sorted({row.get("family") for row in warnings if row.get("family")})
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "summary": payload.get("summary") or {},
        "training_preflight": preflight,
        "families": families,
        "family_count": len(families),
        "diagnostic_families": sorted(row.get("family") for row in diagnostic if row.get("family")),
        "regime_backfill_families": sorted(row.get("family") for row in regime_backfill if row.get("family")),
        "warning_families": warning_families,
    }


def build_gates(*, weak_input: dict[str, Any], item136: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    families = weak_input.get("families") or []
    missing_dispositions = [row.get("family") or "unknown" for row in families if not row.get("disposition")]
    gates.append(_gate(
        "family_disposition_inventory",
        "PASS" if families and not missing_dispositions else "BLOCK",
        (
            f"{len(families)} input families have explicit dispositions"
            if families and not missing_dispositions
            else "one or more input families lack explicit disposition"
        ),
        {"family_count": len(families), "missing_dispositions": missing_dispositions},
    ))

    backfill_missing = [
        row.get("family") or "unknown"
        for row in families
        if row.get("disposition") == "regime_backfill" and not row.get("backfill_plan")
    ]
    gates.append(_gate(
        "regime_backfill_plan_inventory",
        "PASS" if not backfill_missing else "BLOCK",
        (
            "all regime-backfill families have targeted plans"
            if not backfill_missing
            else "regime-backfill families missing plans: " + ", ".join(backfill_missing)
        ),
        {
            "regime_backfill_families": weak_input.get("regime_backfill_families") or [],
            "missing_plans": backfill_missing,
        },
    ))

    preflight = weak_input.get("training_preflight") or {}
    surface_pass = preflight.get("schema_version") == "weak_input_family_disposition_v0.1" and isinstance(
        preflight.get("diagnostic_only_families"), list
    )
    gates.append(_gate(
        "model_explanation_diagnostic_surface",
        "PASS" if surface_pass else "BLOCK",
        (
            "diagnostic-only family surface is present for model explanations"
            if surface_pass
            else "diagnostic-only family surface is missing from preflight payload"
        ),
        preflight,
    ))

    warnings = preflight.get("warnings") or []
    warning_families = weak_input.get("warning_families") or []
    gates.append(_gate(
        "active_artifact_pruning_preflight",
        "PASS" if preflight.get("status") == "PASS" and not warnings else "BLOCK",
        (
            "active artifact has no weak-family pruning warnings"
            if preflight.get("status") == "PASS" and not warnings
            else "active artifact still warns on weak families: " + ", ".join(warning_families or ["unknown"])
        ),
        preflight,
    ))

    gates.append(_gate(
        "upstream_source_state_disposition",
        "PASS" if _passes(item136.get("status")) else "BLOCK",
        (
            "upstream source-state reliability disposition is promotion-ready"
            if _passes(item136.get("status"))
            else item136.get("first_blocker") or "upstream source-state reliability remains shadow-only"
        ),
        item136,
    ))
    return gates


def build_payload(
    *,
    weak_input: str | Path = DEFAULT_WEAK_INPUT,
    item136: str | Path = DEFAULT_ITEM136,
) -> dict[str, Any]:
    weak_payload = weak_input_summary(weak_input)
    item136_payload = simple_gate_summary(item136)
    gates = build_gates(weak_input=weak_payload, item136=item136_payload)
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "disposition": "KEEP_POLICY_SHADOW_PRUNE_ON_RETRAIN" if blockers else "PRUNING_READY",
        "promotion_allowed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "weak_input": str(weak_input),
            "item136": str(item136),
        },
        "weak_input": weak_payload,
        "item136": item136_payload,
        "gates": gates,
        "blockers": blockers,
        "next_action": (
            "Keep weak families diagnostic/regime-backfill only. Do not treat the active artifact as pruned "
            "until training preflight is PASS and upstream source-state reliability gates clear."
        ),
    }


def render_report(payload: dict[str, Any]) -> str:
    weak = payload.get("weak_input") or {}
    preflight = weak.get("training_preflight") or {}
    first = payload.get("first_blocker") or {}
    lines = [
        "# Item 138 Weak Input-Family Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Disposition", payload.get("disposition")],
            ["Promotion allowed", payload.get("promotion_allowed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Families", weak.get("family_count")],
            ["Diagnostic families", ", ".join(weak.get("diagnostic_families") or []) or "-"],
            ["Regime backfill families", ", ".join(weak.get("regime_backfill_families") or []) or "-"],
            ["Training preflight", preflight.get("status")],
            ["Warning families", ", ".join(weak.get("warning_families") or []) or "-"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Preflight Warnings", ""]
    lines += markdown_table(
        ["Family", "Disposition", "Features", "Reasons"],
        [
            [
                row.get("family"),
                row.get("disposition"),
                row.get("feature_count"),
                "; ".join(row.get("reasons") or []) or "-",
            ]
            for row in preflight.get("warnings") or []
        ],
    )
    lines += ["", "## Next Action", "", payload.get("next_action") or "-"]
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Item 138 weak input-family pruning gate.")
    parser.add_argument("--weak-input", default=str(DEFAULT_WEAK_INPUT))
    parser.add_argument("--item136", default=str(DEFAULT_ITEM136))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(weak_input=args.weak_input, item136=args.item136)
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 138 weak input-family gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
