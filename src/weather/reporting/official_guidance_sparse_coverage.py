"""Official-guidance sparse coverage report for roadmap item 137."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "official_guidance_sparse_coverage_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_COVERAGE = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_coverage.csv"
DEFAULT_VARIABLE_SUMMARY = DEFAULT_BACKTEST_ROOT / "input_variable_significance_2026_06_18_variable_summary.csv"
DEFAULT_SOURCE_FAMILY_INVENTORY = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item137_official_guidance_sparse_coverage.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item137_official_guidance_sparse_coverage_report.md"

FAMILY_TARGETS = {
    "nws_grid": {
        "min_days": 60,
        "min_markets": 11,
        "min_unique_raw": 10,
        "min_row_coverage": 0.35,
        "min_replay_days": 20,
        "required_replay_delta": -0.0001,
        "owner": "US official guidance",
    },
    "multi_model_guidance": {
        "min_days": 60,
        "min_markets": 11,
        "min_unique_raw": 10,
        "min_row_coverage": 0.35,
        "min_replay_days": 20,
        "required_replay_delta": -0.0001,
        "owner": "forecast archive",
    },
    "eccc_gridded": {
        "min_days": 30,
        "min_markets": 1,
        "min_unique_raw": 5,
        "min_row_coverage": 0.25,
        "min_replay_days": 15,
        "required_replay_delta": -0.0001,
        "owner": "Canadian official guidance",
        "market_scope": "toronto_only",
    },
    "mrms_precip": {
        "min_days": 40,
        "min_markets": 8,
        "min_unique_raw": 5,
        "min_row_coverage": 0.25,
        "min_replay_days": 15,
        "required_replay_delta": -0.0001,
        "owner": "precip source adapter",
    },
}
PRIORITY_FEATURES = {
    "nws_grid_high",
    "nws_grid_qpf_after_cutoff_sum",
    "nws_grid_pop_after_cutoff_max",
    "nws_grid_sky_cover_after_cutoff_mean",
    "open_meteo_gfs_high_delta",
    "open_meteo_hrrr_high_delta",
    "open_meteo_nbm_high_delta",
    "open_meteo_nam_high_delta",
    "open_meteo_nbm_hrrr_disagreement",
    "open_meteo_multimodel_high_spread",
    "eccc_gem_high",
    "eccc_gem_seamless_high",
    "eccc_gem_vs_forecast_high",
    "eccc_gem_precip_after_cutoff_sum",
    "mrms_precip_since_cutoff_mm",
    "mrms_max_rate_since_cutoff_mm_per_hr",
    "mrms_convective_interruption",
}


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    value = _safe_float(value)
    return int(value) if value is not None else 0


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def guidance_family_for_feature(feature: str) -> str | None:
    if feature.startswith("nws_grid"):
        return "nws_grid"
    if feature.startswith("open_meteo_"):
        return "multi_model_guidance"
    if feature.startswith("eccc_gem"):
        return "eccc_gridded"
    if feature.startswith("mrms_"):
        return "mrms_precip"
    return None


def _summary_by_feature(variable_summary_path: str | Path) -> dict[str, dict[str, str]]:
    return {row.get("feature") or "": row for row in _read_csv(variable_summary_path)}


def field_status(row: dict[str, Any], target: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = []
    if row["n_days_non_missing"] < target["min_days"]:
        reasons.append(f"market-days {row['n_days_non_missing']} < {target['min_days']}")
    if row["n_markets_non_missing"] < target["min_markets"]:
        reasons.append(f"markets {row['n_markets_non_missing']} < {target['min_markets']}")
    if row["n_unique_raw"] < target["min_unique_raw"]:
        reasons.append(f"unique values {row['n_unique_raw']} < {target['min_unique_raw']}")
    if row["row_coverage"] < target["min_row_coverage"]:
        reasons.append(f"row coverage {row['row_coverage']:.3f} < {target['min_row_coverage']:.3f}")
    if not row["analyzable"]:
        reasons.append("insufficient within-market variation")
    return ("pass" if not reasons else "blocked", reasons)


def build_field_rows(
    coverage_path: str | Path = DEFAULT_COVERAGE,
    variable_summary_path: str | Path = DEFAULT_VARIABLE_SUMMARY,
) -> list[dict[str, Any]]:
    summary = _summary_by_feature(variable_summary_path)
    rows = []
    for row in _read_csv(coverage_path):
        feature = row.get("feature") or ""
        family_id = guidance_family_for_feature(feature)
        if not family_id:
            continue
        target = FAMILY_TARGETS[family_id]
        merged = summary.get(feature) or {}
        item = {
            "feature": feature,
            "family_id": family_id,
            "priority": feature in PRIORITY_FEATURES,
            "n_rows_non_missing": _safe_int(row.get("n_rows_non_missing")),
            "row_coverage": _safe_float(row.get("row_coverage")) or 0.0,
            "n_days_non_missing": _safe_int(row.get("n_days_non_missing")),
            "n_markets_non_missing": _safe_int(row.get("n_markets_non_missing")),
            "n_unique_raw": _safe_int(row.get("n_unique_raw")),
            "n_rows_within_market_variation": _safe_int(row.get("n_rows_within_market_variation")),
            "analyzable": str(row.get("analyzable")).lower() == "true",
            "daily_latest_pearson_r": _safe_float(merged.get("daily_latest_pearson_r")),
            "hgb_delta_mae_mean": _safe_float(merged.get("hgb_delta_mae_mean")),
            "targets": target,
        }
        status, reasons = field_status(item, target)
        item["status"] = status
        item["blockers"] = reasons
        item["decision"] = "promotion_candidate" if status == "pass" else "diagnostic_only"
        rows.append(item)
    return sorted(rows, key=lambda item: (item["family_id"], not item["priority"], item["feature"]))


def _inventory_by_family(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path)
    return {
        row.get("family_id"): row
        for row in payload.get("inventory") or []
        if row.get("family_id")
    }


def family_gate_status(
    family_id: str,
    field_rows: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target = FAMILY_TARGETS[family_id]
    fields = [row for row in field_rows if row["family_id"] == family_id]
    pass_fields = [row for row in fields if row["status"] == "pass"]
    priority_fields = [row for row in fields if row["priority"]]
    priority_pass_fields = [row for row in priority_fields if row["status"] == "pass"]
    inv = inventory.get(family_id) or {}
    ablation = inv.get("ablation") or {}
    promotion = inv.get("promotion_decision") or {}
    lineage_status = inv.get("lineage_status") or "UNKNOWN"
    replay_days = _safe_int(ablation.get("days"))
    replay_delta = _safe_float(ablation.get("delta"))
    replay_present = bool(ablation.get("settlement_scored")) and replay_days > 0

    blockers = []
    if not fields:
        blockers.append("no configured fields found in coverage artifact")
    if not pass_fields:
        blockers.append("no field clears coverage targets")
    if priority_fields and not priority_pass_fields:
        blockers.append("no priority field clears coverage targets")
    if "PARTIAL" in lineage_status or str(promotion.get("status") or "").startswith("BLOCK_LINEAGE"):
        blockers.append(f"lineage not promotion-ready: {lineage_status}")
    if not replay_present:
        blockers.append("family replay evidence missing")
    elif replay_days < target["min_replay_days"]:
        blockers.append(f"replay days {replay_days} < {target['min_replay_days']}")
    if replay_delta is None or replay_delta >= target["required_replay_delta"]:
        blockers.append(
            "family replay does not show positive lift "
            f"({fmt_signed(replay_delta, 4)} >= {target['required_replay_delta']:+.4f})"
        )

    status = "PASS" if not blockers else "BLOCK"
    if status == "PASS":
        decision = "promotion_candidate"
    elif not pass_fields:
        decision = "diagnostic_only_sparse_coverage"
    elif replay_present:
        decision = "diagnostic_only_pending_replay_lift"
    else:
        decision = "diagnostic_only_pending_replay"
    return {
        "family_id": family_id,
        "owner": target["owner"],
        "status": status,
        "decision": decision,
        "blockers": blockers,
        "field_count": len(fields),
        "passing_field_count": len(pass_fields),
        "priority_field_count": len(priority_fields),
        "passing_priority_field_count": len(priority_pass_fields),
        "best_days_non_missing": max((row["n_days_non_missing"] for row in fields), default=0),
        "best_markets_non_missing": max((row["n_markets_non_missing"] for row in fields), default=0),
        "best_row_coverage": max((row["row_coverage"] for row in fields), default=0.0),
        "lineage_status": lineage_status,
        "inventory_promotion_status": promotion.get("status") or "-",
        "replay": {
            "status": ablation.get("status") or "-",
            "settlement_scored": bool(ablation.get("settlement_scored")),
            "days": replay_days,
            "rows": _safe_int(ablation.get("rows")),
            "delta": replay_delta,
            "variant": ablation.get("variant") or "-",
        },
        "targets": target,
    }


def build_report_payload(
    coverage_path: str | Path = DEFAULT_COVERAGE,
    variable_summary_path: str | Path = DEFAULT_VARIABLE_SUMMARY,
    source_family_inventory: str | Path = DEFAULT_SOURCE_FAMILY_INVENTORY,
) -> dict[str, Any]:
    fields = build_field_rows(coverage_path, variable_summary_path)
    inventory = _inventory_by_family(source_family_inventory)
    families = [
        family_gate_status(family_id, fields, inventory)
        for family_id in FAMILY_TARGETS
    ]
    blocked = [row for row in families if row["status"] != "PASS"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "coverage": str(coverage_path),
            "variable_summary": str(variable_summary_path),
            "source_family_inventory": str(source_family_inventory),
        },
        "coverage_targets": FAMILY_TARGETS,
        "field_rows": fields,
        "family_gates": families,
        "promotion_gate": {
            "status": "PASS" if not blocked else "BLOCK",
            "blocked_families": [row["family_id"] for row in blocked],
            "decision": (
                "official_guidance_model_influence_allowed"
                if not blocked else
                "official_guidance_model_influence_blocked"
            ),
            "policy": (
                "Fields remain diagnostic-only until coverage targets, lineage, "
                "and positive family-level replay all pass."
            ),
        },
    }


def _family_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row["family_id"],
            row["status"],
            row["decision"],
            row["passing_field_count"],
            row["field_count"],
            row["passing_priority_field_count"],
            row["priority_field_count"],
            row["best_days_non_missing"],
            row["best_markets_non_missing"],
            fmt_num(row["best_row_coverage"]),
            row["lineage_status"],
            (row.get("replay") or {}).get("days", 0),
            fmt_signed((row.get("replay") or {}).get("delta"), 4),
            "; ".join(row.get("blockers") or []) or "-",
        ]
        for row in rows
    ]


def _field_rows(rows: list[dict[str, Any]], *, priority_only: bool = False) -> list[list[Any]]:
    selected = [row for row in rows if (row["priority"] or not priority_only)]
    return [
        [
            row["family_id"],
            row["feature"],
            "yes" if row["priority"] else "no",
            row["status"],
            row["n_days_non_missing"],
            row["n_markets_non_missing"],
            row["n_unique_raw"],
            fmt_num(row["row_coverage"]),
            "yes" if row["analyzable"] else "no",
            fmt_num(row.get("daily_latest_pearson_r")),
            "; ".join(row.get("blockers") or []) or "-",
        ]
        for row in selected
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    gate = payload.get("promotion_gate") or {}
    lines = [
        "# Official Guidance Sparse-Coverage Evidence Growth",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Promotion gate: `{gate.get('status')}`",
        f"Decision: `{gate.get('decision')}`",
        "",
        "## Family Gates",
        "",
    ]
    lines += markdown_table(
        [
            "Family",
            "Status",
            "Decision",
            "Passing Fields",
            "Fields",
            "Priority Passing",
            "Priority Fields",
            "Best Days",
            "Best Markets",
            "Best Coverage",
            "Lineage",
            "Replay Days",
            "Replay Delta",
            "Blockers",
        ],
        _family_rows(payload.get("family_gates") or []),
    )
    lines += ["", "## Priority Field Coverage", ""]
    lines += markdown_table(
        [
            "Family",
            "Feature",
            "Priority",
            "Status",
            "Days",
            "Markets",
            "Unique",
            "Coverage",
            "Analyzable",
            "Daily r",
            "Blockers",
        ],
        _field_rows(payload.get("field_rows") or [], priority_only=True),
    )
    lines += ["", "## All Official-Guidance Field Coverage", ""]
    lines += markdown_table(
        [
            "Family",
            "Feature",
            "Priority",
            "Status",
            "Days",
            "Markets",
            "Unique",
            "Coverage",
            "Analyzable",
            "Daily r",
            "Blockers",
        ],
        _field_rows(payload.get("field_rows") or []),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.coverage,
        args.variable_summary,
        args.source_family_inventory,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 137 official-guidance sparse coverage report.")
    parser.add_argument("--coverage", default=str(DEFAULT_COVERAGE))
    parser.add_argument("--variable-summary", default=str(DEFAULT_VARIABLE_SUMMARY))
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY_INVENTORY))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Official guidance sparse coverage: {payload['promotion_gate']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
