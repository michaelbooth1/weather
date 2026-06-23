"""Physical feature-family isolated replay ratchet.

This report consumes the source-family inventory and settlement-scored source
ablation artifact, then translates them into the stricter item-263 vocabulary.
It does not train or replay models; missing evidence remains an explicit block.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path
from weather.reporting.formatting import fmt_signed, markdown_table
from weather.reporting.source_family_inventory import FAMILY_SPECS
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("physical_feature_family_ratchet")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SOURCE_FAMILY_INVENTORY = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_SOURCE_FAMILY_ABLATION = DEFAULT_BACKTEST_ROOT / "source_family_ablation.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "physical_feature_family_ratchet.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "physical_feature_family_ratchet.md"

EXCLUDED_OVERLAY_FAMILIES = {"clob_microstructure"}
POSITIVE_LIFT_EPSILON = 0.0001
HARM_EPSILON = -0.0001
REQUIRED_SLICE_KINDS = {"market", "cutoff_regime", "market_cutoff_regime", "settlement_distance"}

CONTRACT_FIELDS = [
    "provider/source keys",
    "raw-payload lineage artifacts",
    "historical availability",
    "live availability policy",
    "feature transforms and active artifact columns",
    "missingness and fallback behavior",
    "train rows and served rows",
    "isolated settlement-scored replay or ablation evidence",
    "market/cutoff/source-health/settlement-distance slices",
]


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


SPEC_BY_FAMILY = {spec.family_id: spec for spec in FAMILY_SPECS}


def _family_variants(row):
    family_id = row.get("family_id") or ""
    spec = SPEC_BY_FAMILY.get(family_id)
    variants = []
    ablation = row.get("ablation") or {}
    if ablation.get("variant"):
        variants.append(ablation["variant"])
    if spec:
        variants.extend(spec.ablation_variants)
    variants.extend(row.get("source_keys") or [])
    seen = set()
    ordered = []
    for variant in variants:
        if variant and variant not in seen:
            ordered.append(variant)
            seen.add(variant)
    return ordered


def _slice_rows_for_family(ablation_payload, variants):
    variants = set(variants)
    rows = [
        row for row in (ablation_payload.get("slice_effects") or [])
        if row.get("variant") in variants
    ]
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("variant") or ""),
            str(row.get("slice") or ""),
            str(row.get("market_id") or ""),
            str(row.get("cutoff_regime") or ""),
            str(row.get("settlement_distance") or ""),
        ),
    )


def _day_rows_for_family(ablation_payload, variants):
    day_effects = ablation_payload.get("day_effects") or {}
    rows = []
    for variant in variants:
        for row in day_effects.get(variant) or []:
            rows.append({"variant": variant, **row})
    return rows


def _slice_summary(slice_rows):
    kinds = sorted({row.get("slice") or "unknown" for row in slice_rows})
    harmful = [
        row for row in slice_rows
        if _float(row.get("delta"), 0.0) < HARM_EPSILON
    ]
    positive = [
        row for row in slice_rows
        if _float(row.get("delta"), 0.0) > POSITIVE_LIFT_EPSILON
    ]
    return {
        "slice_count": len(slice_rows),
        "slice_kinds": kinds,
        "required_slice_kinds_present": sorted(set(kinds) & REQUIRED_SLICE_KINDS),
        "missing_required_slice_kinds": sorted(REQUIRED_SLICE_KINDS - set(kinds)),
        "positive_slice_count": len(positive),
        "harmful_slice_count": len(harmful),
        "worst_harm": min((_float(row.get("delta"), 0.0) for row in harmful), default=None),
    }


def _status_for_family(row, slice_rows):
    lineage = row.get("lineage_status") or "UNKNOWN"
    parity = row.get("train_serve_parity_status") or "UNKNOWN"
    ablation = row.get("ablation") or {}
    ablation_status = ablation.get("status") or "MISSING"
    delta = _float(ablation.get("delta"))
    active_count = _int(row.get("active_model_feature_count"))
    active_status = row.get("active_model_usage_status") or ""
    model_influence = bool(row.get("model_influence", row.get("configured_model_influence", True)))
    live_only = bool(row.get("live_only")) or "live_only" in str(row.get("live_only_policy") or "")
    slice_summary = _slice_summary(slice_rows)

    blockers = []
    if lineage != "PASS":
        blockers.append(f"lineage_status={lineage}")
        return "LINEAGE_BLOCKED", blockers, slice_summary
    if parity != "PASS":
        blockers.append(f"train_serve_parity_status={parity}")
        return "LINEAGE_BLOCKED", blockers, slice_summary
    if live_only and active_count == 0:
        blockers.append(f"live_only_policy={row.get('live_only_policy')}")
        return "LIVE_ONLY", blockers, slice_summary
    if model_influence and active_count == 0 and active_status != "ACTIVE_OVERLAY":
        blockers.append(f"active_model_usage_status={active_status or 'UNKNOWN'}")
        return "MISSING_ACTIVE_ARTIFACT", blockers, slice_summary
    if ablation_status != "PRESENT":
        blockers.append(f"ablation_status={ablation_status}")
        return "MISSING_SETTLED_REPLAY", blockers, slice_summary
    if not slice_rows:
        blockers.append("missing settlement-sliced ablation rows")
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    missing_kinds = slice_summary["missing_required_slice_kinds"]
    if missing_kinds:
        blockers.append("missing required slice kinds: " + ", ".join(missing_kinds))
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    if delta is None or delta <= POSITIVE_LIFT_EPSILON:
        blockers.append(f"pooled_delta={delta}")
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    if slice_summary["harmful_slice_count"]:
        blockers.append(f"harmful_slice_count={slice_summary['harmful_slice_count']}")
        return "ISOLATED_REPLAY_BLOCK", blockers, slice_summary
    if active_count > 0:
        return "PROMOTION_ELIGIBLE", blockers, slice_summary
    return "SHADOW_PASS", blockers, slice_summary


def _rollup_bucket(status):
    if status == "PROMOTION_ELIGIBLE":
        return "ready_for_retraining"
    if status in {"SHADOW_PASS", "LIVE_ONLY"}:
        return "diagnostic_only"
    return "evidence_blocked"


def build_ratchet(
    *,
    source_family_inventory=DEFAULT_SOURCE_FAMILY_INVENTORY,
    source_family_ablation=DEFAULT_SOURCE_FAMILY_ABLATION,
    generated_at_utc=None,
):
    inventory_payload = _read_json(source_family_inventory)
    ablation_payload = _read_json(source_family_ablation)
    source_rows = inventory_payload.get("inventory") or []
    families = []
    excluded = []
    slice_rows = []
    for row in source_rows:
        family_id = row.get("family_id") or ""
        if family_id in EXCLUDED_OVERLAY_FAMILIES:
            excluded.append({
                "family_id": family_id,
                "reason": "market-informed/CLOB-derived overlay excluded from physical-weather ratchet",
                "lineage_status": row.get("lineage_status"),
                "train_serve_parity_status": row.get("train_serve_parity_status"),
            })
            continue
        variants = _family_variants(row)
        family_slices = _slice_rows_for_family(ablation_payload, variants)
        family_day_rows = _day_rows_for_family(ablation_payload, variants)
        status, blockers, summary = _status_for_family(row, family_slices)
        bucket = _rollup_bucket(status)
        ablation = row.get("ablation") or {}
        family = {
            "family_id": family_id,
            "label": row.get("label"),
            "owner": row.get("owner"),
            "status": status,
            "rollup_bucket": bucket,
            "blockers": blockers,
            "source_keys": row.get("source_keys") or [],
            "lineage_artifacts": row.get("lineage_artifacts") or [],
            "lineage_status": row.get("lineage_status"),
            "train_serve_parity_status": row.get("train_serve_parity_status"),
            "historical_archive_status": row.get("historical_archive_status"),
            "live_only_policy": row.get("live_only_policy"),
            "active_model_usage_status": row.get("active_model_usage_status"),
            "active_model_feature_count": row.get("active_model_feature_count"),
            "active_model_feature_columns": row.get("active_model_feature_columns") or [],
            "missing_required_parity_feature_columns": row.get("missing_required_parity_feature_columns") or [],
            "feature_missingness": row.get("feature_missingness") or {},
            "ablation": {
                "status": ablation.get("status"),
                "variant": ablation.get("variant"),
                "rows": ablation.get("n") or ablation.get("rows"),
                "days": ablation.get("days"),
                "delta": ablation.get("delta"),
                "days_source_helped": ablation.get("days_source_helped"),
                "days_source_hurt": ablation.get("days_source_hurt"),
            },
            "ablation_variants": variants,
            "settlement_slice_summary": summary,
            "day_effect_count": len(family_day_rows),
        }
        families.append(family)
        for slice_row in family_slices:
            slice_rows.append({"family_id": family_id, **slice_row})

    status_counts = Counter(row["status"] for row in families)
    bucket_counts = Counter(row["rollup_bucket"] for row in families)
    blocked_count = sum(1 for row in families if row["rollup_bucket"] == "evidence_blocked")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": "BLOCK" if blocked_count else "PASS",
        "inputs": {
            "source_family_inventory": str(source_family_inventory),
            "source_family_ablation": str(source_family_ablation),
            "inventory_status": inventory_payload.get("status"),
            "ablation_status": ablation_payload.get("status"),
            "ablation_schema_version": ablation_payload.get("schema_version"),
        },
        "contract": {
            "fields": CONTRACT_FIELDS,
            "status_vocabulary": [
                "LIVE_ONLY",
                "LINEAGE_BLOCKED",
                "MISSING_ACTIVE_ARTIFACT",
                "MISSING_SETTLED_REPLAY",
                "ISOLATED_REPLAY_BLOCK",
                "SHADOW_PASS",
                "PROMOTION_ELIGIBLE",
            ],
            "excluded_overlay_families": sorted(EXCLUDED_OVERLAY_FAMILIES),
        },
        "summary": {
            "family_count": len(families),
            "excluded_overlay_family_count": len(excluded),
            "blocking_family_count": blocked_count,
            "status_counts": dict(sorted(status_counts.items())),
            "rollup_bucket_counts": dict(sorted(bucket_counts.items())),
            "settlement_slice_row_count": len(slice_rows),
        },
        "rollup": {
            "ready_for_retraining": [row["family_id"] for row in families if row["rollup_bucket"] == "ready_for_retraining"],
            "diagnostic_only": [row["family_id"] for row in families if row["rollup_bucket"] == "diagnostic_only"],
            "evidence_blocked": [row["family_id"] for row in families if row["rollup_bucket"] == "evidence_blocked"],
        },
        "families": families,
        "settlement_sliced_lift": slice_rows,
        "excluded_market_overlay_families": excluded,
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Physical Feature-Family Isolated Replay Ratchet",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Physical families", summary.get("family_count")],
            ["Blocking families", summary.get("blocking_family_count")],
            ["Excluded overlay families", summary.get("excluded_overlay_family_count")],
            ["Settlement slice rows", summary.get("settlement_slice_row_count")],
            ["Status counts", json.dumps(summary.get("status_counts") or {}, sort_keys=True)],
            ["Rollup buckets", json.dumps(summary.get("rollup_bucket_counts") or {}, sort_keys=True)],
        ],
    )
    lines += ["", "## Contract", ""]
    for field in (payload.get("contract") or {}).get("fields") or []:
        lines.append(f"- {field}")
    lines += ["", "## Family Ratchet", ""]
    lines += markdown_table(
        ["Family", "Status", "Rollup", "Lineage", "Parity", "Ablation Delta", "Slices", "Blockers"],
        [
            [
                row.get("family_id"),
                row.get("status"),
                row.get("rollup_bucket"),
                row.get("lineage_status"),
                row.get("train_serve_parity_status"),
                fmt_signed((row.get("ablation") or {}).get("delta"), 4),
                (row.get("settlement_slice_summary") or {}).get("slice_count"),
                "; ".join(row.get("blockers") or []) or "-",
            ]
            for row in payload.get("families") or []
        ],
    )
    rollup = payload.get("rollup") or {}
    lines += ["", "## Rollup", ""]
    lines += markdown_table(
        ["Bucket", "Families"],
        [
            ["Ready for retraining", ", ".join(rollup.get("ready_for_retraining") or []) or "-"],
            ["Diagnostic only", ", ".join(rollup.get("diagnostic_only") or []) or "-"],
            ["Evidence blocked", ", ".join(rollup.get("evidence_blocked") or []) or "-"],
        ],
    )
    slices = payload.get("settlement_sliced_lift") or []
    if slices:
        lines += ["", "## Settlement-Sliced Lift And Harm", ""]
        lines += markdown_table(
            ["Family", "Variant", "Slice", "Market", "Regime", "Distance", "Rows", "Delta"],
            [
                [
                    row.get("family_id"),
                    row.get("variant"),
                    row.get("slice"),
                    row.get("market_id") or "-",
                    row.get("cutoff_regime") or "-",
                    row.get("settlement_distance") or "-",
                    row.get("n"),
                    fmt_signed(row.get("delta"), 4),
                ]
                for row in slices[:80]
            ],
        )
    excluded = payload.get("excluded_market_overlay_families") or []
    if excluded:
        lines += ["", "## Excluded Market Overlay Families", ""]
        lines += markdown_table(
            ["Family", "Reason", "Lineage", "Parity"],
            [
                [
                    row.get("family_id"),
                    row.get("reason"),
                    row.get("lineage_status"),
                    row.get("train_serve_parity_status"),
                ]
                for row in excluded
            ],
        )
    return "\n".join(lines) + "\n"


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the physical feature-family isolated replay ratchet.")
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY_INVENTORY))
    parser.add_argument("--source-family-ablation", default=str(DEFAULT_SOURCE_FAMILY_ABLATION))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)
    payload = build_ratchet(
        source_family_inventory=args.source_family_inventory,
        source_family_ablation=args.source_family_ablation,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Physical feature-family ratchet: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return payload


if __name__ == "__main__":
    main()
