"""Current-max trust retrain readiness and evidence gate."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.model.feature_store import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("current_max_trust_retrain_gate")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_CURRENT_MAX_CSV = DEFAULT_BACKTEST_ROOT / "price_free_model_learning_current_max_carryover.csv"
DEFAULT_FEATURE_QUALITY_JSON = DEFAULT_BACKTEST_ROOT / "feature_quality_quarantine.json"
DEFAULT_ROOT_CAUSE_JSON = DEFAULT_BACKTEST_ROOT / "settled_day_root_cause_2026-06-20.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "current_max_trust_retrain_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "current_max_trust_retrain_gate_report.md"
TRUST_FIELDS = (
    "trusted_current_max",
    "support_only_current_max",
    "quarantined_current_max",
    "current_max_trusted_flag",
    "current_max_support_only_flag",
    "current_max_quarantined_flag",
    "current_max_gap_to_history",
    "current_max_gap_to_current_temp",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_csv_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    value = _safe_float(value)
    return int(value) if value is not None else None


def current_max_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    state_counts = Counter(row.get("current_max_state") or "unknown" for row in rows)
    disposition_counts = Counter(row.get("feature_disposition") or "unknown" for row in rows)
    cutoff_counts = Counter(str(row.get("cutoff_hour") or "") for row in rows)
    pre_reset_count = sum(1 for row in rows if str(row.get("pre_reset")).lower() == "true")
    risky_count = sum(
        1 for row in rows
        if (row.get("current_max_state") or "") in {
            "pre_reset_current_max_null",
            "early_current_max_history_gap",
            "current_max_history_gap",
            "current_max_current_temp_gap",
        }
    )
    gap_to_current = [
        value for value in (_safe_float(row.get("gap_to_current_temp")) for row in rows)
        if value is not None
    ]
    return {
        "row_count": len(rows),
        "market_count": len({row.get("market_id") for row in rows if row.get("market_id")}),
        "target_date_count": len({row.get("target_date") for row in rows if row.get("target_date")}),
        "state_counts": dict(sorted(state_counts.items())),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "cutoff_hour_counts": dict(sorted(cutoff_counts.items())),
        "pre_reset_count": pre_reset_count,
        "risky_or_guarded_count": risky_count,
        "max_gap_to_current_temp": max(gap_to_current) if gap_to_current else None,
    }


def feature_quality_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    summary = (payload or {}).get("summary") or {}
    reason_counts = summary.get("reason_counts") or {}
    return {
        "available": bool(payload),
        "schema_version": (payload or {}).get("schema_version") or summary.get("schema_version"),
        "scanned_feature_row_count": summary.get("scanned_feature_row_count"),
        "quarantine_row_count": summary.get("quarantine_row_count"),
        "training_excluded_row_count": summary.get("training_excluded_row_count"),
        "current_max_exceeds_observed_support": reason_counts.get("current_max_exceeds_observed_support", 0),
        "startup_live_observation_implausible": reason_counts.get("startup_live_observation_implausible", 0),
        "raw_evidence_absent_row_count": summary.get("raw_evidence_absent_row_count"),
    }


def root_cause_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    summary = (payload or {}).get("summary") or {}
    issue_counts = summary.get("issue_counts") or {}
    return {
        "available": bool(payload),
        "target_date": (payload or {}).get("target_date"),
        "status": (payload or {}).get("status"),
        "snapshot_count": summary.get("snapshot_count"),
        "issue_count": summary.get("issue_count"),
        "wu_current_max_anomaly_count": issue_counts.get("WU_CURRENT_MAX_ANOMALY", 0),
        "ramp_window_warm_tail_spread_count": issue_counts.get("RAMP_WINDOW_WARM_TAIL_SPREAD", 0),
        "taker_bought_warm_tail_count": issue_counts.get("TAKER_BOUGHT_WARM_TAIL", 0),
        "late_day_lockin_under_coverage_count": issue_counts.get("LATE_DAY_LOCKIN_UNDER_COVERAGE", 0),
    }


def retrain_evidence_summary(path: str | Path | None) -> dict[str, Any]:
    payload = _read_json(path)
    if not path:
        return {"path": None, "available": False}
    summary = {
        "path": str(path),
        "available": bool(payload),
        "schema_version": (payload or {}).get("schema_version"),
        "feature_schema_version": (
            (payload or {}).get("feature_schema_version")
            or ((payload or {}).get("artifact") or {}).get("feature_schema_version")
            or ((payload or {}).get("training") or {}).get("feature_schema_version")
        ),
        "current_max_trust_ablation": (payload or {}).get("current_max_trust_ablation"),
        "early_hour": (payload or {}).get("early_hour"),
        "late_lock_in": (payload or {}).get("late_lock_in"),
    }
    return summary


def gate_row(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def build_gates(
    *,
    current_max: dict[str, Any],
    feature_quality: dict[str, Any],
    root_cause: dict[str, Any],
    retrain: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = []
    missing_fields = [field for field in TRUST_FIELDS if field not in FEATURE_COLUMNS]
    gates.append(gate_row(
        "feature_schema_trust_fields",
        "PASS" if not missing_fields else "BLOCK",
        (
            f"feature schema {FEATURE_SCHEMA_VERSION} exposes all current-max trust fields"
            if not missing_fields
            else "feature schema is missing trust fields: " + ", ".join(missing_fields)
        ),
        {"missing_fields": missing_fields, "trust_fields": list(TRUST_FIELDS)},
    ))
    gates.append(gate_row(
        "current_max_carryover_corpus",
        "PASS" if current_max.get("row_count", 0) > 0 else "BLOCK",
        f"current-max carryover rows={current_max.get('row_count', 0)}",
        current_max,
    ))
    gates.append(gate_row(
        "feature_quality_quarantine_baseline",
        "PASS" if feature_quality.get("available") and feature_quality.get("quarantine_row_count", 0) > 0 else "BLOCK",
        (
            "feature-quality quarantine baseline is available"
            if feature_quality.get("available")
            else "feature-quality quarantine baseline missing"
        ),
        feature_quality,
    ))
    gates.append(gate_row(
        "june20_root_cause_baseline",
        "PASS" if root_cause.get("available") and root_cause.get("wu_current_max_anomaly_count", 0) > 0 else "BLOCK",
        (
            "June 20 root-cause baseline has WU_CURRENT_MAX_ANOMALY evidence"
            if root_cause.get("available")
            else "June 20 root-cause baseline missing"
        ),
        root_cause,
    ))
    feature_schema = retrain.get("feature_schema_version")
    gates.append(gate_row(
        "retrained_artifact_evidence",
        "PASS" if retrain.get("available") and feature_schema == FEATURE_SCHEMA_VERSION else "BLOCK",
        (
            f"retrain report uses active feature schema {FEATURE_SCHEMA_VERSION}"
            if retrain.get("available") and feature_schema == FEATURE_SCHEMA_VERSION
            else "missing retrain report proving artifact was trained with current-max trust fields"
        ),
        retrain,
    ))
    ablation = retrain.get("current_max_trust_ablation")
    gates.append(gate_row(
        "trust_field_ablation",
        "PASS" if isinstance(ablation, dict) and ablation.get("status") == "PASS" else "BLOCK",
        (
            "trust-field ablation passed"
            if isinstance(ablation, dict) and ablation.get("status") == "PASS"
            else "missing trust-field ablation comparing no/raw/trust-weighted current-max features"
        ),
        ablation if isinstance(ablation, dict) else {},
    ))
    return gates


def build_payload(
    *,
    current_max_csv: str | Path = DEFAULT_CURRENT_MAX_CSV,
    feature_quality_json: str | Path = DEFAULT_FEATURE_QUALITY_JSON,
    root_cause_json: str | Path = DEFAULT_ROOT_CAUSE_JSON,
    retrain_report_json: str | Path | None = None,
) -> dict[str, Any]:
    current_max = current_max_summary(_read_csv_rows(current_max_csv))
    feature_quality = feature_quality_summary(_read_json(feature_quality_json))
    root_cause = root_cause_summary(_read_json(root_cause_json))
    retrain = retrain_evidence_summary(retrain_report_json)
    gates = build_gates(
        current_max=current_max,
        feature_quality=feature_quality,
        root_cause=root_cause,
        retrain=retrain,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "current_max_csv": str(current_max_csv),
            "feature_quality_json": str(feature_quality_json),
            "root_cause_json": str(root_cause_json),
            "retrain_report_json": str(retrain_report_json) if retrain_report_json else None,
        },
        "feature_schema": {
            "version": FEATURE_SCHEMA_VERSION,
            "trust_fields": list(TRUST_FIELDS),
            "trust_fields_present": [field for field in TRUST_FIELDS if field in FEATURE_COLUMNS],
        },
        "current_max_carryover": current_max,
        "feature_quality_quarantine": feature_quality,
        "june20_root_cause": root_cause,
        "retrain_evidence": retrain,
        "gates": gates,
        "blockers": blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Current-Max Trust Retrain Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    first = payload.get("first_blocker") or {}
    current_max = payload.get("current_max_carryover") or {}
    feature_quality = payload.get("feature_quality_quarantine") or {}
    root_cause = payload.get("june20_root_cause") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Feature schema", (payload.get("feature_schema") or {}).get("version")],
            ["Current-max rows", current_max.get("row_count")],
            ["Quarantine rows", feature_quality.get("quarantine_row_count")],
            ["June 20 WU anomalies", root_cause.get("wu_current_max_anomaly_count")],
            ["June 20 warm-tail issues", root_cause.get("ramp_window_warm_tail_spread_count")],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Current-Max Corpus", ""]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Rows", current_max.get("row_count")],
            ["Markets", current_max.get("market_count")],
            ["Target dates", current_max.get("target_date_count")],
            ["Pre-reset rows", current_max.get("pre_reset_count")],
            ["Risky or guarded rows", current_max.get("risky_or_guarded_count")],
            ["Max gap to current temp", fmt_num(current_max.get("max_gap_to_current_temp"))],
        ],
    )
    lines += ["", "## Root-Cause Baseline", ""]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Target date", root_cause.get("target_date")],
            ["Snapshots", root_cause.get("snapshot_count")],
            ["WU_CURRENT_MAX_ANOMALY", root_cause.get("wu_current_max_anomaly_count")],
            ["RAMP_WINDOW_WARM_TAIL_SPREAD", root_cause.get("ramp_window_warm_tail_spread_count")],
            ["TAKER_BOUGHT_WARM_TAIL", root_cause.get("taker_bought_warm_tail_count")],
            ["LATE_DAY_LOCKIN_UNDER_COVERAGE", root_cause.get("late_day_lockin_under_coverage_count")],
        ],
    )
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
    parser = argparse.ArgumentParser(description="Gate current-max trust retrain evidence.")
    parser.add_argument("--current-max-csv", default=str(DEFAULT_CURRENT_MAX_CSV))
    parser.add_argument("--feature-quality-json", default=str(DEFAULT_FEATURE_QUALITY_JSON))
    parser.add_argument("--root-cause-json", default=str(DEFAULT_ROOT_CAUSE_JSON))
    parser.add_argument("--retrain-report-json", default=None)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        current_max_csv=args.current_max_csv,
        feature_quality_json=args.feature_quality_json,
        root_cause_json=args.root_cause_json,
        retrain_report_json=args.retrain_report_json,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Current-max trust retrain gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
