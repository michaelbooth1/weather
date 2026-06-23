"""Fail-closed gate for Item 186 soil and antecedent-water features."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_pct, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item186_soil_antecedent_gate")
EXPECTED_SIDECAR_SCHEMA = schema_version("reanalysis_synoptic_features")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_REANALYSIS_ROOT = data_path() / "reanalysis"
DEFAULT_SOURCE_FAMILY = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_SETTLEMENT_GATE = DEFAULT_BACKTEST_ROOT / "item186_soil_antecedent_settlement_gate.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item186_soil_antecedent_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item186_soil_antecedent_gate_report.md"
DEFAULT_MIN_MARKETS = 12

SOIL_COLUMNS = (
    "reanalysis_soil_dryness_available",
    "reanalysis_prev_day_soil_moisture_0_to_7cm_percentile",
    "reanalysis_prev_day_soil_moisture_0_to_7cm_anomaly",
    "reanalysis_prev_day_soil_dryness_percentile",
    "reanalysis_prev_day_dry_vpd_stress_proxy",
)
WATER_COLUMNS = (
    "reanalysis_prev_day_precipitation_sum",
    "reanalysis_prev_7d_precipitation_sum",
    "reanalysis_prev_14d_precipitation_sum",
    "reanalysis_prev_30d_precipitation_sum",
    "reanalysis_prev_7d_precipitation_minus_et0",
    "reanalysis_prev_14d_precipitation_minus_et0",
    "reanalysis_prev_30d_precipitation_minus_et0",
)
REQUIRED_COLUMNS = (*SOIL_COLUMNS, *WATER_COLUMNS)
BLANK_VALUES = {"", "na", "nan", "none", "null", "n/a"}
PASS_STATUSES = {"PASS", "READY", "ALLOW", "ALLOWED"}


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
    return str(value or "").upper() in PASS_STATUSES


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in BLANK_VALUES:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if text.lower() in BLANK_VALUES:
        return False
    return True


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def sidecar_paths(reanalysis_root: str | Path) -> list[Path]:
    return sorted(Path(reanalysis_root).glob("*/features/reanalysis_synoptic_features.csv"))


def market_from_path(path: Path, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        market_id = str(row.get("market_id") or "").strip()
        if market_id:
            return market_id
    return path.parent.parent.name


def _date_bounds(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    dates = sorted(
        str(row.get("local_date") or "")[:10]
        for row in rows
        if str(row.get("local_date") or "").strip()
    )
    if not dates:
        return None, None
    return dates[0], dates[-1]


def _column_present_counts(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> dict[str, int]:
    return {
        column: sum(1 for row in rows if _is_present(row.get(column)))
        for column in columns
    }


def _complete_row_count(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> int:
    return sum(1 for row in rows if all(_is_present(row.get(column)) for column in columns))


def sidecar_summary(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    rows = read_csv_rows(path)
    row_count = len(rows)
    first_date, last_date = _date_bounds(rows)
    schemas = sorted({str(row.get("schema_version") or "").strip() for row in rows if row.get("schema_version")})
    soil_counts = _column_present_counts(rows, SOIL_COLUMNS)
    water_counts = _column_present_counts(rows, WATER_COLUMNS)
    soil_complete = _complete_row_count(rows, SOIL_COLUMNS)
    water_complete = _complete_row_count(rows, WATER_COLUMNS)
    return {
        "market_id": market_from_path(path, rows),
        "path": str(path),
        "rows": row_count,
        "first_date": first_date,
        "last_date": last_date,
        "schema_versions": schemas,
        "schema_ok": schemas == [EXPECTED_SIDECAR_SCHEMA],
        "soil_complete_rows": soil_complete,
        "soil_coverage": soil_complete / row_count if row_count else 0.0,
        "water_complete_rows": water_complete,
        "water_coverage": water_complete / row_count if row_count else 0.0,
        "soil_present_by_column": soil_counts,
        "water_present_by_column": water_counts,
        "soil_missing_columns": [column for column, count in soil_counts.items() if row_count and count == 0],
        "water_missing_columns": [column for column, count in water_counts.items() if row_count and count == 0],
    }


def coverage_summary(reanalysis_root: str | Path) -> dict[str, Any]:
    sidecars = [sidecar_summary(path) for path in sidecar_paths(reanalysis_root)]
    total_rows = sum(row.get("rows", 0) for row in sidecars)
    soil_complete = sum(row.get("soil_complete_rows", 0) for row in sidecars)
    water_complete = sum(row.get("water_complete_rows", 0) for row in sidecars)
    return {
        "reanalysis_root": str(Path(reanalysis_root)),
        "sidecar_count": len(sidecars),
        "total_rows": total_rows,
        "soil_complete_rows": soil_complete,
        "soil_coverage": soil_complete / total_rows if total_rows else 0.0,
        "water_complete_rows": water_complete,
        "water_coverage": water_complete / total_rows if total_rows else 0.0,
        "markets_with_soil": sorted(row["market_id"] for row in sidecars if row.get("soil_complete_rows", 0) > 0),
        "markets_with_water": sorted(row["market_id"] for row in sidecars if row.get("water_complete_rows", 0) > 0),
        "schema_versions": sorted({
            version
            for row in sidecars
            for version in (row.get("schema_versions") or [])
            if version
        }),
        "sidecars": sidecars,
    }


def source_family_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    rows = payload.get("inventory") or payload.get("rows") or []
    family = next(
        (row for row in rows if isinstance(row, dict) and row.get("family_id") == "reanalysis_synoptic"),
        None,
    )
    family = family or {}
    feature_columns = family.get("feature_columns") or []
    missing_required = [column for column in REQUIRED_COLUMNS if column not in feature_columns]
    promotion = family.get("promotion_decision") or {}
    lane = family.get("promotion_lane") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "family_present": bool(family),
        "train_serve_parity_status": family.get("train_serve_parity_status"),
        "promotion_decision_status": promotion.get("status"),
        "promotion_decision_reason": promotion.get("reason"),
        "promotion_lane_status": lane.get("status"),
        "promotion_lane_policy": lane.get("policy"),
        "allowed_markets": lane.get("allowed_markets") or [],
        "quarantined_markets": lane.get("quarantined_markets") or [],
        "feature_column_count": len(feature_columns),
        "missing_required_columns": missing_required,
    }


def _market_rows_from_settlement(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("markets") or payload.get("market_results") or []
    return [row for row in rows if isinstance(row, dict)]


def settlement_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    lane = payload.get("promotion_lane") or payload.get("lane") or {}
    rows = _market_rows_from_settlement(payload)
    allowed = lane.get("allowed_markets") or [
        row.get("market_id")
        for row in rows
        if str(row.get("decision") or row.get("status") or "").lower() in {"promote", "allow", "pass"}
    ]
    quarantined = lane.get("quarantined_markets") or [
        row.get("market_id")
        for row in rows
        if str(row.get("decision") or row.get("status") or "").lower() in {"block", "quarantine"}
    ]
    blocked_rows = [
        row.get("market_id")
        for row in rows
        if str(row.get("decision") or row.get("status") or "").lower() in {"block", "quarantine"}
    ]
    unquarantined_blocked = sorted(
        str(market)
        for market in blocked_rows
        if market and market not in set(quarantined)
    )
    settlement_scored = bool(
        payload.get("settlement_scored")
        or (payload.get("summary") or {}).get("settlement_scored")
        or rows
    )
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "settlement_scored": settlement_scored,
        "market_count": len(rows),
        "allowed_markets": sorted(str(market) for market in allowed if market),
        "quarantined_markets": sorted(str(market) for market in quarantined if market),
        "unquarantined_blocked_markets": unquarantined_blocked,
        "promotion_lane_status": lane.get("status"),
        "promotion_lane_policy": lane.get("policy"),
        "first_blocker": payload.get("first_blocker"),
        "blocker_count": payload.get("blocker_count", len(payload.get("blockers") or [])),
    }


def build_gates(
    *,
    coverage: dict[str, Any],
    source_family: dict[str, Any],
    settlement_gate: dict[str, Any],
    min_markets: int,
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    sidecars = coverage.get("sidecars") or []
    schema_ok = all(row.get("schema_ok") for row in sidecars)
    rowless = [row.get("market_id") for row in sidecars if row.get("rows", 0) == 0]
    enough_markets = coverage.get("sidecar_count", 0) >= min_markets
    gates.append(_gate(
        "sidecar_file_inventory",
        "PASS" if enough_markets and schema_ok and not rowless else "BLOCK",
        (
            f"{coverage.get('sidecar_count')} sidecars use {EXPECTED_SIDECAR_SCHEMA} with non-empty rows"
            if enough_markets and schema_ok and not rowless
            else "reanalysis sidecar inventory is incomplete, empty, or on an unexpected schema"
        ),
        {
            "min_markets": min_markets,
            "sidecar_count": coverage.get("sidecar_count"),
            "schema_versions": coverage.get("schema_versions"),
            "rowless_markets": rowless,
        },
    ))

    markets_without_soil = [
        row.get("market_id")
        for row in sidecars
        if row.get("soil_complete_rows", 0) <= 0
    ]
    gates.append(_gate(
        "soil_anomaly_feature_coverage",
        "PASS" if sidecars and not markets_without_soil else "BLOCK",
        (
            f"soil anomaly/dry-VPD fields have {coverage.get('soil_complete_rows')} complete rows "
            f"across {len(coverage.get('markets_with_soil') or [])} markets"
            if sidecars and not markets_without_soil
            else "one or more markets have no complete soil anomaly/dry-VPD rows"
        ),
        {
            "soil_columns": list(SOIL_COLUMNS),
            "soil_complete_rows": coverage.get("soil_complete_rows"),
            "soil_coverage": coverage.get("soil_coverage"),
            "markets_without_soil": markets_without_soil,
        },
    ))

    markets_without_water = [
        row.get("market_id")
        for row in sidecars
        if row.get("water_complete_rows", 0) <= 0
    ]
    gates.append(_gate(
        "antecedent_water_balance_backfill",
        "PASS" if sidecars and not markets_without_water else "BLOCK",
        (
            f"precipitation and water-balance fields have {coverage.get('water_complete_rows')} complete rows "
            f"across {len(coverage.get('markets_with_water') or [])} markets"
            if sidecars and not markets_without_water
            else "precipitation-backed water-balance fields have no complete coverage in one or more markets"
        ),
        {
            "water_columns": list(WATER_COLUMNS),
            "water_complete_rows": coverage.get("water_complete_rows"),
            "water_coverage": coverage.get("water_coverage"),
            "markets_without_water": markets_without_water,
        },
    ))

    source_ready = (
        source_family.get("family_present")
        and source_family.get("train_serve_parity_status") == "PASS"
        and source_family.get("promotion_decision_status") == "PROMOTION_CANDIDATE"
        and not source_family.get("missing_required_columns")
    )
    gates.append(_gate(
        "source_family_inventory",
        "PASS" if source_ready else "BLOCK",
        (
            "reanalysis_synoptic inventory has parity, candidate status, and required Item 186 columns"
            if source_ready
            else "reanalysis_synoptic inventory is missing parity, candidate status, or required Item 186 columns"
        ),
        source_family,
    ))

    settlement_ready = (
        settlement_gate.get("exists")
        and _passes(settlement_gate.get("status"))
        and settlement_gate.get("settlement_scored")
        and settlement_gate.get("market_count", 0) > 0
    )
    gates.append(_gate(
        "settlement_scored_family_gate",
        "PASS" if settlement_ready else "BLOCK",
        (
            "isolated soil/antecedent-water family gate is settlement-scored"
            if settlement_ready
            else "isolated soil/antecedent-water settlement gate is missing or not pass-ready"
        ),
        settlement_gate,
    ))

    promotion_policy_ready = (
        settlement_ready
        and bool(settlement_gate.get("allowed_markets"))
        and not settlement_gate.get("unquarantined_blocked_markets")
    )
    gates.append(_gate(
        "positive_market_promotion_policy",
        "PASS" if promotion_policy_ready else "BLOCK",
        (
            "promotion lane is limited to positive markets with blocked markets quarantined"
            if promotion_policy_ready
            else "no positive-market promotion lane exists for the soil/antecedent-water subfamily"
        ),
        {
            "allowed_markets": settlement_gate.get("allowed_markets") or [],
            "quarantined_markets": settlement_gate.get("quarantined_markets") or [],
            "unquarantined_blocked_markets": settlement_gate.get("unquarantined_blocked_markets") or [],
            "promotion_lane_status": settlement_gate.get("promotion_lane_status"),
            "promotion_lane_policy": settlement_gate.get("promotion_lane_policy"),
        },
    ))
    return gates


def build_payload(
    *,
    reanalysis_root: str | Path = DEFAULT_REANALYSIS_ROOT,
    source_family_inventory: str | Path = DEFAULT_SOURCE_FAMILY,
    settlement_gate: str | Path = DEFAULT_SETTLEMENT_GATE,
    min_markets: int = DEFAULT_MIN_MARKETS,
) -> dict[str, Any]:
    coverage = coverage_summary(reanalysis_root)
    source_family = source_family_summary(source_family_inventory)
    settlement = settlement_gate_summary(settlement_gate)
    gates = build_gates(
        coverage=coverage,
        source_family=source_family,
        settlement_gate=settlement,
        min_markets=min_markets,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    next_action = (
        "Allow only the settlement-positive soil/antecedent-water markets into the scoped lane; "
        "keep blocked markets quarantined until their market gates turn positive."
        if not blockers
        else (
            "Backfill Open-Meteo/ERA5 precipitation into the reanalysis history cache, rebuild all "
            "reanalysis sidecars, then run an isolated soil/antecedent-water settlement gate before "
            "allowing any market into promotion."
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "disposition": "PROMOTION_READY" if not blockers else "KEEP_SHADOW_DIAGNOSTIC",
        "promotion_allowed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "reanalysis_root": str(reanalysis_root),
            "source_family_inventory": str(source_family_inventory),
            "settlement_gate": str(settlement_gate),
            "min_markets": min_markets,
        },
        "coverage": coverage,
        "source_family": source_family,
        "settlement_gate": settlement,
        "gates": gates,
        "blockers": blockers,
        "next_action": next_action,
    }


def render_report(payload: dict[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    source = payload.get("source_family") or {}
    settlement = payload.get("settlement_gate") or {}
    first = payload.get("first_blocker") or {}
    lines = [
        "# Item 186 Soil Antecedent-Water Gate",
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
            ["Sidecars", coverage.get("sidecar_count")],
            ["Total rows", coverage.get("total_rows")],
            ["Soil complete rows", coverage.get("soil_complete_rows")],
            ["Soil coverage", fmt_pct(coverage.get("soil_coverage"))],
            ["Water complete rows", coverage.get("water_complete_rows")],
            ["Water coverage", fmt_pct(coverage.get("water_coverage"))],
            ["Source family parity", source.get("train_serve_parity_status")],
            ["Source family decision", source.get("promotion_decision_status")],
            ["Broad reanalysis lane", source.get("promotion_lane_status") or "-"],
            ["Settlement gate status", settlement.get("status") or "-"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Market Coverage", ""]
    lines += markdown_table(
        ["Market", "Rows", "Schema", "Soil rows", "Soil pct", "Water rows", "Water pct", "Missing water columns"],
        [
            [
                row.get("market_id"),
                row.get("rows"),
                ", ".join(row.get("schema_versions") or []) or "-",
                row.get("soil_complete_rows"),
                fmt_pct(row.get("soil_coverage")),
                row.get("water_complete_rows"),
                fmt_pct(row.get("water_coverage")),
                ", ".join(row.get("water_missing_columns") or []) or "-",
            ]
            for row in sorted(coverage.get("sidecars") or [], key=lambda item: str(item.get("market_id") or ""))
        ],
    )
    lines += ["", "## Promotion Lane Context", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Inventory allowed markets", ", ".join(source.get("allowed_markets") or []) or "-"],
            ["Inventory quarantined markets", ", ".join(source.get("quarantined_markets") or []) or "-"],
            ["Settlement allowed markets", ", ".join(settlement.get("allowed_markets") or []) or "-"],
            ["Settlement quarantined markets", ", ".join(settlement.get("quarantined_markets") or []) or "-"],
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Item 186 soil/antecedent-water promotion gate.")
    parser.add_argument("--reanalysis-root", default=str(DEFAULT_REANALYSIS_ROOT))
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY))
    parser.add_argument("--settlement-gate", default=str(DEFAULT_SETTLEMENT_GATE))
    parser.add_argument("--min-markets", type=int, default=DEFAULT_MIN_MARKETS)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        reanalysis_root=args.reanalysis_root,
        source_family_inventory=args.source_family_inventory,
        settlement_gate=args.settlement_gate,
        min_markets=args.min_markets,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 186 soil/antecedent-water gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
