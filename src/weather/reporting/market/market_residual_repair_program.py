"""Market-specific early-hour residual repair program report."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.research.exact_band_distance_zero_calibration import (
    GUARDRAIL_SLICES,
    TARGET_SLICES,
    guardrail_status,
    read_variant_rows,
    rows_for_slice,
    score_summary,
    target_status,
)
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_residual_repair_program")
REJECTED_REGISTRY_SCHEMA_VERSION = "market_residual_repair_rejected_registry_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "market_residual_repair_program.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "market_residual_repair_program_report.md"
DEFAULT_MANIFEST_DIR = DEFAULT_BACKTEST_ROOT / "market_residual_repair_manifests"
DEFAULT_REJECTED_REGISTRY_OUT = DEFAULT_BACKTEST_ROOT / "market_residual_repair_rejected_registry.json"
DEFAULT_CANDIDATE_ROWS = (
    DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_variant_rows.csv",
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv",
)
DEFAULT_RESIDUAL_MARKETS = (
    "seattle",
    "nyc",
    "austin",
    "miami",
    "san-francisco",
    "los-angeles",
)
DEFAULT_MARKET_TOL = 0.003
DEFAULT_LOGLOSS_TOL = 0.010
PROGRAM_SLICES = (
    *TARGET_SLICES,
    "one_above_early",
    "one_below_early",
    "adjacent_early",
    "broad_early",
    "ramp",
    "late",
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


def parse_markets(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_RESIDUAL_MARKETS
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_candidate_exports(paths: list[str | Path]) -> list[dict[str, Any]]:
    exports = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            exports.append({
                "path": str(path),
                "exists": False,
                "rows": [],
                "variant_ids": [],
                "variant_families": [],
            })
            continue
        rows = read_variant_rows(path)
        for row in rows:
            row["_source_path"] = str(path)
        exports.append({
            "path": str(path),
            "exists": True,
            "rows": rows,
            "variant_ids": sorted({str(row.get("variant_id")) for row in rows if row.get("variant_id")}),
            "variant_families": sorted({
                str(row.get("variant_family")) for row in rows if row.get("variant_family")
            }),
        })
    return exports


def _candidate_label(export: dict[str, Any]) -> str:
    variant_ids = export.get("variant_ids") or []
    if variant_ids:
        return ",".join(variant_ids)
    return Path(export.get("path") or "candidate_rows").stem


def _candidate_family(export: dict[str, Any]) -> str:
    families = export.get("variant_families") or []
    if families:
        return ",".join(families)
    return _candidate_label(export)


def _slice_status(slice_name: str, summary: dict[str, Any], *, market_tol: float, logloss_tol: float) -> tuple[str, str]:
    if slice_name in TARGET_SLICES:
        return target_status(summary, market_tol=market_tol, logloss_tol=logloss_tol)
    return guardrail_status(summary, market_tol=market_tol, logloss_tol=logloss_tol)


def evaluate_candidate_for_market(
    export: dict[str, Any],
    market_id: str,
    *,
    market_tol: float,
    logloss_tol: float,
) -> dict[str, Any]:
    market_rows = [
        row for row in export.get("rows") or []
        if str(row.get("market_id") or "").lower() == market_id
    ]
    slice_results = []
    blockers = []
    for slice_name in PROGRAM_SLICES:
        summary = score_summary(rows_for_slice(market_rows, slice_name))
        status, detail = _slice_status(
            slice_name,
            summary,
            market_tol=market_tol,
            logloss_tol=logloss_tol,
        )
        result = {
            "slice": slice_name,
            **summary,
            "status": status,
            "detail": detail,
        }
        slice_results.append(result)
        if status == "BLOCK":
            blockers.append({
                "slice": slice_name,
                "detail": detail,
                "evidence": result,
            })

    broad_early = next((row for row in slice_results if row.get("slice") == "broad_early"), {})
    return {
        "candidate_id": _candidate_label(export),
        "candidate_family": _candidate_family(export),
        "source_path": export.get("path"),
        "source_exists": bool(export.get("exists")),
        "variant_ids": export.get("variant_ids") or [],
        "variant_families": export.get("variant_families") or [],
        "market_id": market_id,
        "rows": len(market_rows),
        "target_dates": sorted({row.get("target_date") for row in market_rows if row.get("target_date")}),
        "status": "PASS" if market_rows and not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "primary_score": {
            "slice": "broad_early",
            "market_days": broad_early.get("market_days"),
            "candidate_brier": broad_early.get("candidate_brier"),
            "current_brier": broad_early.get("current_brier"),
            "market_brier": broad_early.get("market_brier"),
            "delta_vs_current": broad_early.get("delta_vs_current"),
            "delta_vs_market": broad_early.get("delta_vs_market"),
            "logloss_delta_vs_current": broad_early.get("logloss_delta_vs_current"),
            "logloss_delta_vs_market": broad_early.get("logloss_delta_vs_market"),
        },
        "slice_results": slice_results,
    }


def _candidate_sort_key(result: dict[str, Any]) -> tuple[Any, ...]:
    score = result.get("primary_score") or {}
    status_rank = 0 if result.get("status") == "PASS" else 1
    delta_market = _finite(score.get("delta_vs_market"))
    delta_current = _finite(score.get("delta_vs_current"))
    return (
        status_rank,
        math.inf if delta_market is None else delta_market,
        math.inf if delta_current is None else delta_current,
        result.get("blocker_count", 0),
        result.get("candidate_id") or "",
    )


def allowlist_recommendation(market_id: str, best: dict[str, Any] | None) -> dict[str, Any]:
    if best and best.get("status") == "PASS":
        action = "KEEP_SHADOW"
        serving_behavior = "current_or_shadow"
        permission_behavior = "current_or_harvest_only"
        blocker_reason = ""
    else:
        action = "BLOCK_CANDIDATE"
        serving_behavior = "current_or_shadow"
        permission_behavior = "current_or_harvest_only"
        blocker_reason = (
            ((best or {}).get("first_blocker") or {}).get("detail")
            or "no market-scoped candidate cleared target and guardrail gates"
        )
    score = (best or {}).get("primary_score") or {}
    return {
        "market_id": market_id,
        "candidate_id": (best or {}).get("candidate_id"),
        "candidate_family": (best or {}).get("candidate_family"),
        "action": action,
        "serving_behavior": serving_behavior,
        "permission_behavior": permission_behavior,
        "blocker_reason": blocker_reason,
        "candidate_brier": score.get("candidate_brier"),
        "current_brier": score.get("current_brier"),
        "market_brier": score.get("market_brier"),
        "delta_vs_current": score.get("delta_vs_current"),
        "delta_vs_market": score.get("delta_vs_market"),
    }


def manifest_for_market(
    market_id: str,
    candidate_results: list[dict[str, Any]],
    *,
    generated_at_utc: str,
) -> dict[str, Any]:
    sorted_results = sorted(candidate_results, key=_candidate_sort_key)
    best = sorted_results[0] if sorted_results else None
    return {
        "manifest_id": f"item231_{market_id.replace('-', '_')}_early_residual_v0_1",
        "roadmap_item": 231,
        "market_id": market_id,
        "generated_at_utc": generated_at_utc,
        "status": "PASS" if best and best.get("status") == "PASS" else "BLOCK",
        "best_candidate_id": (best or {}).get("candidate_id"),
        "best_candidate_family": (best or {}).get("candidate_family"),
        "target_slices": list(TARGET_SLICES),
        "guardrail_slices": [name for name in PROGRAM_SLICES if name not in TARGET_SLICES],
        "candidate_results": sorted_results,
        "promotion_allowlist_recommendation": allowlist_recommendation(market_id, best),
        "next_repair_scope": {
            "feature_families": [
                "source_disagreement",
                "source_availability_missingness",
                "overnight_forecast_movement",
                "time_to_heating",
                "forecast_relative_winner_geometry",
                "coastal_or_marine_context",
            ],
            "policy": (
                "Do not broad-promote this market until a market-scoped candidate "
                "clears exact/distance targets and adjacent/ramp/late guardrails."
            ),
        },
    }


def _known_no_go_entries(paths: list[str | Path]) -> list[dict[str, Any]]:
    entries = []
    for path in paths:
        payload = _read_json(path)
        if not payload:
            continue
        entries.append({
            "repair_family": "existing_variant_basket_selection",
            "status": payload.get("status") or ("NO_GO" if payload.get("acceptance") == "blocked" else "CLEAR"),
            "source_path": str(path),
            "disposition_id": payload.get("disposition_id"),
            "blocked_market_count": payload.get("blocked_market_count"),
            "blocked_markets": payload.get("blocked_markets") or [],
            "detail": payload.get("next_action") or "existing basket/guard policy did not clear held-out gates",
        })
    return entries


def build_rejected_registry(
    manifests: list[dict[str, Any]],
    *,
    known_no_go_paths: list[str | Path] | None = None,
    generated_at_utc: str,
) -> dict[str, Any]:
    entries = _known_no_go_entries(known_no_go_paths or [])
    seen = {(entry.get("repair_family"), entry.get("source_path"), entry.get("market_id")) for entry in entries}
    for manifest in manifests:
        for result in manifest.get("candidate_results") or []:
            if result.get("status") != "BLOCK":
                continue
            key = (result.get("candidate_family"), result.get("source_path"), manifest.get("market_id"))
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "repair_family": result.get("candidate_family"),
                "candidate_id": result.get("candidate_id"),
                "market_id": manifest.get("market_id"),
                "status": "NO_GO",
                "source_path": result.get("source_path"),
                "first_blocker": (result.get("first_blocker") or {}).get("detail"),
                "blocked_slices": [blocker.get("slice") for blocker in result.get("blockers") or []],
                "primary_score": result.get("primary_score") or {},
                "next_action": "build a new market-specific no-market signal before retesting this family",
            })
    family_counts = Counter(entry.get("repair_family") for entry in entries)
    return {
        "schema_version": REJECTED_REGISTRY_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "entry_count": len(entries),
        "repair_family_counts": dict(sorted(family_counts.items())),
        "entries": entries,
    }


def build_payload(
    rows_paths: list[str | Path],
    *,
    markets: tuple[str, ...] = DEFAULT_RESIDUAL_MARKETS,
    known_no_go_paths: list[str | Path] | None = None,
    market_tol: float = DEFAULT_MARKET_TOL,
    logloss_tol: float = DEFAULT_LOGLOSS_TOL,
) -> dict[str, Any]:
    generated_at_utc = utc_iso()
    markets = tuple(str(market).strip().lower() for market in markets if str(market).strip())
    exports = read_candidate_exports(rows_paths)
    manifests = []
    for market_id in markets:
        candidate_results = [
            evaluate_candidate_for_market(
                export,
                market_id,
                market_tol=market_tol,
                logloss_tol=logloss_tol,
            )
            for export in exports
        ]
        manifests.append(manifest_for_market(
            market_id,
            candidate_results,
            generated_at_utc=generated_at_utc,
        ))
    rejected_registry = build_rejected_registry(
        manifests,
        known_no_go_paths=known_no_go_paths or [],
        generated_at_utc=generated_at_utc,
    )
    recommendations = [
        manifest["promotion_allowlist_recommendation"]
        for manifest in manifests
    ]
    action_counts = Counter(row.get("action") for row in recommendations)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "status": "PASS" if manifests and all(manifest.get("status") == "PASS" for manifest in manifests) else "BLOCK",
        "inputs": {
            "rows_paths": [str(path) for path in rows_paths],
            "known_no_go_paths": [str(path) for path in known_no_go_paths or []],
            "markets": list(markets),
            "market_tolerance": float(market_tol),
            "logloss_tolerance": float(logloss_tol),
        },
        "candidate_exports": [
            {
                "path": export.get("path"),
                "exists": export.get("exists"),
                "row_count": len(export.get("rows") or []),
                "variant_ids": export.get("variant_ids") or [],
                "variant_families": export.get("variant_families") or [],
            }
            for export in exports
        ],
        "summary": {
            "market_count": len(manifests),
            "pass_count": sum(1 for manifest in manifests if manifest.get("status") == "PASS"),
            "blocked_count": sum(1 for manifest in manifests if manifest.get("status") != "PASS"),
            "action_counts": dict(sorted(action_counts.items())),
            "promote_markets": [],
            "shadow_markets": [
                row["market_id"] for row in recommendations if row.get("action") == "KEEP_SHADOW"
            ],
            "blocked_markets": [
                row["market_id"] for row in recommendations if row.get("action") == "BLOCK_CANDIDATE"
            ],
        },
        "promotion_allowlist_recommendations": recommendations,
        "manifests": manifests,
        "rejected_registry": rejected_registry,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Market-Specific Early-Hour Residual Repair Program",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Markets", summary.get("market_count")],
            ["Passing manifests", summary.get("pass_count")],
            ["Blocked manifests", summary.get("blocked_count")],
            ["Promote markets", ", ".join(summary.get("promote_markets") or []) or "-"],
            ["Shadow markets", ", ".join(summary.get("shadow_markets") or []) or "-"],
            ["Blocked markets", ", ".join(summary.get("blocked_markets") or []) or "-"],
            ["Rejected registry entries", (payload.get("rejected_registry") or {}).get("entry_count")],
        ],
    )
    lines += ["", "## Candidate Exports", ""]
    lines += markdown_table(
        ["Path", "Exists", "Rows", "Variant IDs", "Variant Families"],
        [
            [
                row.get("path"),
                row.get("exists"),
                row.get("row_count"),
                ", ".join(row.get("variant_ids") or []) or "-",
                ", ".join(row.get("variant_families") or []) or "-",
            ]
            for row in payload.get("candidate_exports") or []
        ],
    )
    lines += ["", "## Market Manifests", ""]
    lines += markdown_table(
        [
            "Market",
            "Status",
            "Best candidate",
            "Family",
            "Action",
            "Candidate",
            "Current",
            "Market",
            "Delta Current",
            "Delta Market",
            "Blocker",
        ],
        [
            [
                manifest.get("market_id"),
                manifest.get("status"),
                manifest.get("best_candidate_id") or "-",
                manifest.get("best_candidate_family") or "-",
                (manifest.get("promotion_allowlist_recommendation") or {}).get("action"),
                fmt_num((manifest.get("promotion_allowlist_recommendation") or {}).get("candidate_brier")),
                fmt_num((manifest.get("promotion_allowlist_recommendation") or {}).get("current_brier")),
                fmt_num((manifest.get("promotion_allowlist_recommendation") or {}).get("market_brier")),
                fmt_signed((manifest.get("promotion_allowlist_recommendation") or {}).get("delta_vs_current")),
                fmt_signed((manifest.get("promotion_allowlist_recommendation") or {}).get("delta_vs_market")),
                (manifest.get("promotion_allowlist_recommendation") or {}).get("blocker_reason") or "-",
            ]
            for manifest in payload.get("manifests") or []
        ],
    )
    lines += ["", "## Rejected Repair Registry", ""]
    lines += markdown_table(
        ["Family", "Candidate", "Market", "Status", "First Blocker"],
        [
            [
                row.get("repair_family"),
                row.get("candidate_id") or "-",
                row.get("market_id") or "-",
                row.get("status"),
                row.get("first_blocker") or row.get("detail") or "-",
            ]
            for row in (payload.get("rejected_registry") or {}).get("entries") or []
        ],
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
    *,
    manifest_dir: str | Path | None = DEFAULT_MANIFEST_DIR,
    rejected_registry_out: str | Path | None = DEFAULT_REJECTED_REGISTRY_OUT,
) -> dict[str, Any]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")

    manifest_paths = []
    if manifest_dir:
        manifest_root = Path(manifest_dir)
        manifest_root.mkdir(parents=True, exist_ok=True)
        for manifest in payload.get("manifests") or []:
            path = manifest_root / f"{manifest['manifest_id']}.json"
            path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest_paths.append(path)

    rejected_path = None
    if rejected_registry_out:
        rejected_path = Path(rejected_registry_out)
        rejected_path.parent.mkdir(parents=True, exist_ok=True)
        rejected_path.write_text(
            json.dumps(payload.get("rejected_registry") or {}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return {
        "json": json_path,
        "report": report_path,
        "manifests": manifest_paths,
        "rejected_registry": rejected_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build market-specific early-hour residual repair manifests.")
    parser.add_argument("rows", nargs="*", help="Candidate row CSV exports. Defaults to active Item 147 and predawn rows.")
    parser.add_argument("--markets", default=",".join(DEFAULT_RESIDUAL_MARKETS))
    parser.add_argument("--known-no-go", action="append", default=[])
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--logloss-tol", type=float, default=DEFAULT_LOGLOSS_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    parser.add_argument("--rejected-registry-out", default=str(DEFAULT_REJECTED_REGISTRY_OUT))
    args = parser.parse_args(argv)
    rows = [Path(path) for path in args.rows] if args.rows else list(DEFAULT_CANDIDATE_ROWS)
    payload = build_payload(
        rows,
        markets=parse_markets(args.markets),
        known_no_go_paths=args.known_no_go,
        market_tol=args.market_tol,
        logloss_tol=args.logloss_tol,
    )
    outputs = write_outputs(
        payload,
        args.out,
        args.report,
        manifest_dir=args.manifest_dir,
        rejected_registry_out=args.rejected_registry_out,
    )
    print(f"Market residual repair program: {payload['status']}")
    print(f"JSON written to {outputs['json']}")
    print(f"Report written to {outputs['report']}")
    print(f"Manifest files written: {len(outputs['manifests'])}")
    if outputs.get("rejected_registry"):
        print(f"Rejected registry written to {outputs['rejected_registry']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
