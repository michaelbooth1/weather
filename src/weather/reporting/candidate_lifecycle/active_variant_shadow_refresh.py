"""Canonical active-variant shadow refresh.

This module builds the scheduled active-variant shadow artifact consumed by
daily evidence-growth reporting. It deliberately fails closed when active
registry variants are absent instead of falling back to stale item-specific
bakeoff exports.
"""

from __future__ import annotations

import argparse
import csv
import json
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import config_path, data_path
from weather.reporting.formatting import markdown_table
from weather.reporting.candidate_lifecycle.multi_variant_shadow import (
    LONG_TABLE_COLUMNS,
    OBSERVATION_KEY_FIELDS,
    build_payload as build_multi_variant_payload,
    read_prediction_rows,
    write_attribution_sidecar,
    write_json as write_multi_variant_json,
    write_long_csv,
)
from weather.reporting.candidate_lifecycle.variant_registry import (
    active_export_paths,
    headline_registry_variants,
    audit_registry,
    load_registry,
    resolve_registry_path,
    variant_export_contract,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("active_variant_shadow_refresh")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_REGISTRY_PATH = config_path("model_variant_registry.json")
DEFAULT_LONG_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_long.csv"
DEFAULT_ATTRIBUTION_SIDECAR_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_attribution.jsonl"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_report.md"
DEFAULT_EXECUTION_OUT_DIR = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_runs"
DEFAULT_WINDOW_CORPUS_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_window_corpus.json"
# Variant lifecycle decisions are about RECENT skill; replaying every registry
# contract over the full promotion corpus scaled with corpus growth until the
# step alone took 11.2h of a 16.6h chain (2026-07-05/06), starving the nightly
# retrain lock, spanning midnight (breaking date-consistency invariants), and
# squeezing collection. The shadow evidence window caps that permanently; the
# promotion corpus itself stays full-history for promotion gates.
DEFAULT_EVIDENCE_WINDOW_DATES = 14
ROW_ROUTE_COMPOSITE_RUNTIME = "candidate_row_route_composite"
ACTIVE_TIMESPLIT_LOGISTIC_RUNTIME = "active_timesplit_logistic_repair"
REPAIR_INTEGRATION_RUNTIME = "repair_integration_active_contract"
DERIVED_RUNTIMES = {"conservative_bridge_policy", "microstructure_shadow_report"}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_rows(paths: list[str | Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing = []
    missing = []
    for value in paths:
        path = Path(value)
        if path.exists():
            stat = path.stat()
            existing.append({
                "path": str(path),
                "exists": True,
                "bytes": stat.st_size,
                "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        else:
            missing.append({"path": str(path), "exists": False})
    rows = read_prediction_rows([row["path"] for row in existing]) if existing else []
    return rows, existing + missing


def _filter_active_or_control_rows(
    rows: list[dict[str, Any]],
    active_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        variant_id = str(row.get("variant_id") or "")
        is_control = str(row.get("is_control") or "").strip().lower() in {"1", "true", "yes", "y"}
        if variant_id in active_ids or is_control:
            selected.append(row)
    return selected


def _resolve_registry_output_path(value: str | Path | None) -> Path | None:
    if value in (None, ""):
        return None
    return resolve_registry_path(value) or Path(value)


def _variant_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value)).strip("_") or "variant"


def _execution_row(
    variant: dict[str, Any],
    contract: dict[str, Any],
    *,
    status: str,
    output_path: str | Path | None = None,
    source_variant_id: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    row = {
        "variant_id": variant.get("variant_id"),
        "live_runtime": contract.get("live_runtime"),
        "prediction_function": contract.get("prediction_function"),
        "status": status,
    }
    if output_path is not None:
        row["output_path"] = str(output_path)
    if source_variant_id:
        row["source_variant_id"] = source_variant_id
    if detail:
        row["detail"] = detail
    return row


def _registry_active_entry(registry: dict[str, Any], variant_id: str) -> dict[str, Any] | None:
    entry = (registry.get("by_id") or {}).get(str(variant_id))
    if entry:
        return entry
    for row in registry.get("variants") or []:
        if str(row.get("variant_id") or "") == str(variant_id):
            return row
    return None


def _read_route_recipe(path: str | Path | None) -> dict[str, Any]:
    if path in (None, ""):
        raise ValueError("candidate row-route composite requires route_recipe_path")
    recipe_path = _resolve_registry_output_path(path)
    if recipe_path is None or not recipe_path.exists():
        raise FileNotFoundError(f"candidate row-route recipe not found: {path}")
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("candidate row-route recipe must contain a JSON object")
    sources = payload.get("sources") or []
    source_ids = payload.get("source_variant_ids") or []
    for source in sources:
        if isinstance(source, dict) and source.get("variant_id"):
            source_ids.append(source.get("variant_id"))
    source_ids = [str(source_id) for source_id in dict.fromkeys(source_ids) if source_id]
    rules = payload.get("routes") or payload.get("rules") or []
    if not source_ids:
        raise ValueError("candidate row-route recipe requires source_variant_ids")
    if not rules:
        raise ValueError("candidate row-route recipe requires routes")
    return {**payload, "source_variant_ids": source_ids, "routes": rules}


def _observation_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in OBSERVATION_KEY_FIELDS)


def _rule_matches(row: dict[str, Any], rule: dict[str, Any]) -> bool:
    match = rule.get("match") or {}
    if not isinstance(match, dict):
        raise ValueError("candidate row-route recipe route.match must be an object")
    for field, expected in match.items():
        actual = str(row.get(field) or "")
        if isinstance(expected, list):
            allowed = {str(value) for value in expected}
        else:
            allowed = {str(expected)}
        if actual not in allowed:
            return False
    return True


def _route_source_variant_id(row: dict[str, Any], rules: list[dict[str, Any]]) -> str:
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("candidate row-route recipe routes must be objects")
        if _rule_matches(row, rule):
            source_id = str(rule.get("source_variant_id") or "")
            if not source_id:
                raise ValueError("candidate row-route recipe route requires source_variant_id")
            return source_id
    raise ValueError(
        "candidate row-route recipe did not match observation "
        + "/".join(str(row.get(field) or "") for field in OBSERVATION_KEY_FIELDS)
    )


def _write_candidate_row_route_export(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_fields = sorted({
        key
        for row in rows
        for key in row
        if key not in LONG_TABLE_COLUMNS
    })
    fieldnames = [*LONG_TABLE_COLUMNS, *extra_fields]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _source_variant_rows(
    registry: dict[str, Any],
    source_variant_id: str,
) -> tuple[dict[str, Any], dict[tuple[str, ...], dict[str, Any]]]:
    entry = _registry_active_entry(registry, source_variant_id)
    if not entry:
        raise ValueError(f"candidate row-route source variant is not registered: {source_variant_id}")
    lifecycle = str(entry.get("lifecycle") or "").lower()
    if lifecycle != "active" or entry.get("active_for_headline") is False:
        raise ValueError(f"candidate row-route source variant is not active/headline-countable: {source_variant_id}")
    contract = variant_export_contract(entry)
    export_path = _resolve_registry_output_path(contract.get("default_export_path"))
    if export_path is None or not export_path.exists():
        raise FileNotFoundError(
            f"candidate row-route source export not found for {source_variant_id}: "
            f"{contract.get('default_export_path')}"
        )
    rows = [
        row for row in read_prediction_rows([export_path])
        if str(row.get("variant_id") or "") == source_variant_id
    ]
    if not rows:
        raise ValueError(f"candidate row-route source export has no rows for {source_variant_id}")
    by_key = {_observation_key(row): row for row in rows}
    if len(by_key) != len(rows):
        raise ValueError(f"candidate row-route source export has duplicate observation rows: {source_variant_id}")
    return {**contract, "variant_id": source_variant_id, "variant_family": entry.get("variant_family")}, by_key


def _execute_candidate_row_route_composite_contract(
    variant: dict[str, Any],
    contract: dict[str, Any],
    *,
    registry: dict[str, Any],
) -> dict[str, Any]:
    output_path = _resolve_registry_output_path(contract.get("default_export_path"))
    if output_path is None:
        raise ValueError("candidate row-route composite requires default_export_path")
    recipe = _read_route_recipe(contract.get("route_recipe_path") or variant.get("route_recipe_path"))
    variant_id = str(variant.get("variant_id") or contract.get("variant_id") or "")
    if not variant_id:
        raise ValueError("candidate row-route composite requires variant_id")

    source_maps: dict[str, dict[tuple[str, ...], dict[str, Any]]] = {}
    source_contracts: dict[str, dict[str, Any]] = {}
    for source_id in recipe["source_variant_ids"]:
        source_contract, rows_by_key = _source_variant_rows(registry, source_id)
        source_contracts[source_id] = source_contract
        source_maps[source_id] = rows_by_key

    all_keys = sorted({key for rows_by_key in source_maps.values() for key in rows_by_key})
    output_rows: list[dict[str, Any]] = []
    missing_routes: list[str] = []
    source_order = list(recipe["source_variant_ids"])
    for key in all_keys:
        reference = next((source_maps[source_id][key] for source_id in source_order if key in source_maps[source_id]), None)
        if reference is None:
            continue
        source_id = _route_source_variant_id(reference, recipe["routes"])
        source_row = source_maps.get(source_id, {}).get(key)
        if source_row is None:
            missing_routes.append(f"{'/'.join(key)} -> {source_id}")
            continue
        source_contract = source_contracts[source_id]
        output_row = dict(source_row)
        output_row.update({
            "variant_id": variant_id,
            "variant_family": contract.get("export_family") or variant.get("variant_family") or variant_id,
            "uses_market_features": str(contract.get("track") or variant.get("track") or "") == "market_informed",
            "is_control": False,
            "claim_lane": output_row.get("claim_lane") or "weather_only_core_model",
            "route_source_path": source_contract.get("default_export_path"),
            "route_source_variant_family": source_contract.get("variant_family"),
            "route_source_variant_id": source_id,
        })
        output_rows.append(output_row)
    if missing_routes:
        raise ValueError(
            "candidate row-route recipe selected source rows that are missing: "
            + "; ".join(missing_routes[:5])
        )
    if not output_rows:
        raise ValueError("candidate row-route composite emitted no rows")

    _write_candidate_row_route_export(output_path, output_rows)
    return _execution_row(
        variant,
        contract,
        status="OK",
        output_path=output_path,
        detail=f"rows={len(output_rows)}; sources={','.join(source_order)}",
    )


def _derived_output_paths(active_variants: list[dict[str, Any]]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for variant in active_variants:
        contract = variant_export_contract(variant)
        runtime = str(contract.get("live_runtime") or "")
        if runtime not in DERIVED_RUNTIMES:
            continue
        output_path = _resolve_registry_output_path(contract.get("default_export_path"))
        if output_path is not None:
            paths[runtime] = output_path
    return paths


def _execute_pooled_candidate_replay_contract(
    variant: dict[str, Any],
    contract: dict[str, Any],
    *,
    registry_path: str | Path,
    corpus_path: str | Path,
    snapshots_root: str | Path,
    out_dir: str | Path = DEFAULT_EXECUTION_OUT_DIR,
    derived_output_paths: dict[str, Path] | None = None,
    min_artifact_free_bytes: int = 0,
    current_tol: float = 0.003,
    market_tol: float = 0.003,
    min_days: int = 2,
    min_trust: int = 25,
    require_exact_identity: bool = False,
    require_all_markets: bool = False,
    replay_cache: str = "read_write",
    replay_cache_root: str | Path | None = None,
    disable_replay_cache_sentinel: bool = False,
) -> dict[str, Any]:
    """Execute one pooled replay registry contract and write its configured export.

    The pooled replay function also owns bridge/CLOB derived variant exports, so
    the first successful pooled execution can be asked to emit those paths.
    """
    from weather.backtesting.replay_backtest import FIDELITY_FAITHFUL_L1
    from weather.calibration import pooled_candidate_replay

    output_path = _resolve_registry_output_path(contract.get("default_export_path"))
    artifact_path = _resolve_registry_output_path(contract.get("artifact_path"))
    out_dir = Path(out_dir)
    backtest_root = Path(corpus_path).parent
    variant_id = str(variant.get("variant_id") or contract.get("variant_id") or "variant")
    slug = _variant_slug(variant_id)
    args = SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=str(snapshots_root),
        artifact=str(artifact_path or contract.get("artifact_path") or ""),
        variant_registry=str(registry_path),
        out=str(out_dir / f"{slug}_pooled_candidate_replay_report.md"),
        json_out=str(out_dir / f"{slug}_pooled_candidate_replay.json"),
        replay_report=str(out_dir / f"{slug}_current_replay_report.md"),
        current_tol=current_tol,
        market_tol=market_tol,
        min_days=min_days,
        min_trust=min_trust,
        max_fidelity_l1=FIDELITY_FAITHFUL_L1,
        clob_max_age_seconds=180.0,
        replay_cache=replay_cache,
        replay_cache_root=str(replay_cache_root) if replay_cache_root else None,
        disable_replay_cache_sentinel=disable_replay_cache_sentinel,
        casebook=str(backtest_root / "disagreement_casebook.json"),
        candidate_variant_out=str(output_path) if output_path else None,
        candidate_variant_id=variant_id,
        candidate_variant_family=contract.get("export_family") or contract.get("variant_family"),
        candidate_variant_uses_market_features=str(contract.get("track") or "") == "market_informed",
        candidate_variant_control=False,
        disable_candidate_variant_export=False,
        microstructure_artifact=None,
        microstructure_variant_out=None,
        microstructure_min_train_rows=500,
        skip_microstructure_overlay=True,
        source_state_ablation_variant_out=None,
        bridge_variant_out=None,
        min_artifact_free_bytes=min_artifact_free_bytes,
        require_exact_identity=require_exact_identity,
        require_all_markets=require_all_markets,
        long_job_guard_info={},
        fail_on_block=False,
    )
    derived_output_paths = derived_output_paths or {}
    if "microstructure_shadow_report" in derived_output_paths:
        args.skip_microstructure_overlay = False
        args.microstructure_variant_out = str(derived_output_paths["microstructure_shadow_report"])
        args.microstructure_artifact = None
    if "conservative_bridge_policy" in derived_output_paths:
        args.bridge_variant_out = str(derived_output_paths["conservative_bridge_policy"])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    report = pooled_candidate_replay.run_pooled_candidate_replay(args)
    row = _execution_row(
        variant,
        contract,
        status="OK",
        output_path=output_path,
        detail=f"verdict={report.get('verdict')}; cutover={report.get('cutover_decision')}",
    )
    return row


def _execute_active_timesplit_logistic_repair_contract(
    variant: dict[str, Any],
    contract: dict[str, Any],
    *,
    registry_path: str | Path,
    out_dir: str | Path = DEFAULT_EXECUTION_OUT_DIR,
) -> dict[str, Any]:
    """Execute the active time-split logistic export contract."""
    from weather.reporting.research import item224_active_timesplit_logistic_repair

    output_path = _resolve_registry_output_path(contract.get("default_export_path"))
    if output_path is None:
        raise ValueError("active time-split logistic repair requires default_export_path")
    out_dir = Path(out_dir)
    slug = _variant_slug(str(variant.get("variant_id") or contract.get("variant_id") or "variant"))
    input_rows = _resolve_registry_output_path(
        contract.get("input_rows_path")
        or variant.get("input_rows_path")
        or item224_active_timesplit_logistic_repair.DEFAULT_INPUT_ROWS
    )
    payload = item224_active_timesplit_logistic_repair.build_payload(
        input_rows=input_rows,
        rows_out=output_path,
        registry_out=out_dir / f"{slug}_registry.json",
        contract_out=out_dir / f"{slug}_contract.json",
        base_registry=registry_path,
    )
    aggregate = payload.get("aggregate") or {}
    return _execution_row(
        variant,
        contract,
        status="OK",
        output_path=output_path,
        detail=(
            f"rows={payload.get('eval_rows')}; "
            f"delta_vs_market={aggregate.get('delta_vs_market')}"
        ),
    )


def _execute_repair_integration_contract(
    variant: dict[str, Any],
    contract: dict[str, Any],
    *,
    registry_path: str | Path,
    out_dir: str | Path = DEFAULT_EXECUTION_OUT_DIR,
) -> dict[str, Any]:
    """Execute a repair-integration active export contract."""
    from weather.reporting.candidate_lifecycle import repair_integration

    output_path = _resolve_registry_output_path(contract.get("default_export_path"))
    if output_path is None:
        raise ValueError("repair integration requires default_export_path")
    specs_path = _resolve_registry_output_path(
        contract.get("repair_specs_path") or variant.get("repair_specs_path")
    )
    if specs_path is None:
        raise ValueError("repair integration requires repair_specs_path")
    out_dir = Path(out_dir)
    slug = _variant_slug(str(variant.get("variant_id") or contract.get("variant_id") or "variant"))
    source_candidate_json = (
        _resolve_registry_output_path(contract.get("source_candidate_json") or variant.get("source_candidate_json"))
        or repair_integration.DEFAULT_SOURCE_CANDIDATE_JSON
    )
    payload = repair_integration.build_payload(
        repair_specs_path=specs_path,
        rows_out=output_path,
        registry_out=out_dir / f"{slug}_registry.json",
        contract_out=out_dir / f"{slug}_contract.json",
        base_registry=registry_path,
        source_candidate_json=source_candidate_json,
        variant_id=str(variant.get("variant_id") or contract.get("variant_id")),
        variant_family=contract.get("export_family") or variant.get("variant_family") or repair_integration.DEFAULT_VARIANT_FAMILY,
    )
    summary = payload.get("summary") or {}
    return _execution_row(
        variant,
        contract,
        status="OK" if payload.get("status") == "PASS" else "BLOCK",
        output_path=output_path,
        detail=(
            f"repairs={summary.get('integrated_repair_count')}; "
            f"rows={summary.get('integrated_rows')}; "
            f"delta_vs_market={summary.get('aggregate_delta_vs_market')}"
        ),
    )


def windowed_corpus_manifest(
    corpus_path: str | Path,
    out_path: str | Path = DEFAULT_WINDOW_CORPUS_OUT,
    *,
    window_dates: int = DEFAULT_EVIDENCE_WINDOW_DATES,
) -> dict[str, Any]:
    """Pin a recent-evidence sub-corpus for shadow variant replays.

    Keeps the newest `window_dates` distinct target dates from the promotion
    corpus manifest and writes a valid pinned manifest (recomputed corpus_hash)
    so replays against it keep their append/rewrite protection. Returns the
    path to use plus window metadata; `window_dates <= 0` or a corpus already
    inside the window returns the original path unchanged.
    """
    from weather.reporting.promotion.promotion_corpus import (
        corpus_hash,
        load_manifest,
        summarize_entries,
        write_manifest,
    )

    corpus_path = Path(corpus_path)
    passthrough = {
        "path": str(corpus_path),
        "windowed": False,
        "window_dates": int(window_dates or 0),
    }
    if not window_dates or int(window_dates) <= 0 or not corpus_path.exists():
        return passthrough
    try:
        manifest = load_manifest(corpus_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        # A corpus that fails pinned-manifest validation replays as-is (the
        # pre-window behavior); the replay layer owns rejecting bad corpora.
        return {**passthrough, "window_skip_reason": f"{type(exc).__name__}: {exc}"}
    entries = manifest.get("entries") or []
    dates = sorted({str(e.get("target_date")) for e in entries if e.get("target_date")})
    keep = set(dates[-int(window_dates):])
    subset = [e for e in entries if str(e.get("target_date")) in keep]
    if len(subset) == len(entries):
        return {
            **passthrough,
            "market_day_count": len(entries),
            "window_date_count": len(dates),
        }
    windowed = {key: value for key, value in manifest.items() if key != "_path"}
    windowed["entries"] = subset
    windowed["summary"] = summarize_entries(subset)
    windowed["corpus_hash"] = corpus_hash(subset)
    windowed["evidence_window"] = {
        "window_dates": int(window_dates),
        "window_date_min": min(keep) if keep else None,
        "window_date_max": max(keep) if keep else None,
        "source_corpus_path": str(corpus_path),
        "source_corpus_hash": manifest.get("corpus_hash"),
        "source_market_day_count": len(entries),
        "source_date_count": len(dates),
    }
    out_path = Path(out_path)
    write_manifest(windowed, out_path)
    return {
        "path": str(out_path),
        "windowed": True,
        "window_dates": int(window_dates),
        "window_date_count": len(keep),
        "market_day_count": len(subset),
        "source_market_day_count": len(entries),
        "window_date_min": min(keep) if keep else None,
        "window_date_max": max(keep) if keep else None,
    }


def execute_registry_prediction_exports(
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    corpus_path: str | Path = DEFAULT_BACKTEST_ROOT / "promotion_corpus.json",
    snapshots_root: str | Path | None = None,
    out_dir: str | Path = DEFAULT_EXECUTION_OUT_DIR,
    min_artifact_free_bytes: int = 0,
    current_tol: float = 0.003,
    market_tol: float = 0.003,
    min_days: int = 2,
    min_trust: int = 25,
    require_exact_identity: bool = False,
    require_all_markets: bool = False,
    replay_cache: str = "read_write",
    replay_cache_root: str | Path | None = None,
    disable_replay_cache_sentinel: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Run active registry prediction contracts and return generated sources."""
    from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT

    generated_at_utc = generated_at_utc or utc_iso()
    snapshots_root = snapshots_root or DEFAULT_SNAPSHOTS_ROOT
    corpus_path = Path(corpus_path)
    registry = load_registry(registry_path)
    active_variants = headline_registry_variants(registry)
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    generated_paths: list[str] = []

    if not corpus_path.exists():
        blockers.append(f"promotion corpus not found: {corpus_path}")
        return {
            "status": "BLOCK",
            "generated_at_utc": generated_at_utc,
            "source_paths": [],
            "executions": rows,
            "blockers": blockers,
        }

    pooled_variants = [
        variant
        for variant in active_variants
        if str(variant_export_contract(variant).get("live_runtime") or "") == "pooled_candidate_replay"
    ]
    derived_variants = [
        variant
        for variant in active_variants
        if str(variant_export_contract(variant).get("live_runtime") or "") in DERIVED_RUNTIMES
    ]
    row_route_composite_variants = [
        variant
        for variant in active_variants
        if str(variant_export_contract(variant).get("live_runtime") or "") == ROW_ROUTE_COMPOSITE_RUNTIME
    ]
    active_timesplit_variants = [
        variant
        for variant in active_variants
        if str(variant_export_contract(variant).get("live_runtime") or "") == ACTIVE_TIMESPLIT_LOGISTIC_RUNTIME
    ]
    repair_integration_variants = [
        variant
        for variant in active_variants
        if str(variant_export_contract(variant).get("live_runtime") or "") == REPAIR_INTEGRATION_RUNTIME
    ]
    unsupported = [
        variant
        for variant in active_variants
        if str(variant_export_contract(variant).get("live_runtime") or "")
        not in {
            "pooled_candidate_replay",
            ROW_ROUTE_COMPOSITE_RUNTIME,
            ACTIVE_TIMESPLIT_LOGISTIC_RUNTIME,
            REPAIR_INTEGRATION_RUNTIME,
            *DERIVED_RUNTIMES,
        }
    ]

    derived_paths = _derived_output_paths(derived_variants)
    derived_pending = dict(derived_paths)
    for variant in unsupported:
        contract = variant_export_contract(variant)
        rows.append(_execution_row(
            variant,
            contract,
            status="UNSUPPORTED",
            detail=f"unsupported live_runtime {contract.get('live_runtime')!r}",
        ))
        blockers.append(f"unsupported live_runtime for {variant.get('variant_id')}: {contract.get('live_runtime')}")

    if derived_variants and not pooled_variants:
        blockers.append("derived active variant runtimes require at least one pooled_candidate_replay source")

    for variant in pooled_variants:
        contract = variant_export_contract(variant)
        output_path = _resolve_registry_output_path(contract.get("default_export_path"))
        artifact_path = _resolve_registry_output_path(contract.get("artifact_path"))
        if contract.get("artifact_required", True) and artifact_path is not None and not artifact_path.exists():
            rows.append(_execution_row(
                variant,
                contract,
                status="BLOCK",
                output_path=output_path,
                detail=f"artifact not found: {artifact_path}",
            ))
            blockers.append(f"artifact not found for {variant.get('variant_id')}: {artifact_path}")
            continue
        try:
            row = _execute_pooled_candidate_replay_contract(
                variant,
                contract,
                registry_path=registry_path,
                corpus_path=corpus_path,
                snapshots_root=snapshots_root,
                out_dir=out_dir,
                derived_output_paths=derived_pending,
                min_artifact_free_bytes=min_artifact_free_bytes,
                current_tol=current_tol,
                market_tol=market_tol,
                min_days=min_days,
                min_trust=min_trust,
                require_exact_identity=require_exact_identity,
                require_all_markets=require_all_markets,
                replay_cache=replay_cache,
                replay_cache_root=replay_cache_root,
                disable_replay_cache_sentinel=disable_replay_cache_sentinel,
            )
        except Exception as exc:  # pragma: no cover - exercised through failure payloads in production.
            rows.append(_execution_row(
                variant,
                contract,
                status="ERROR",
                output_path=output_path,
                detail=str(exc),
            ))
            blockers.append(f"execution failed for {variant.get('variant_id')}: {exc}")
            continue
        rows.append(row)
        if output_path is not None:
            generated_paths.append(str(output_path))
        for derived_variant in derived_variants:
            derived_contract = variant_export_contract(derived_variant)
            runtime = str(derived_contract.get("live_runtime") or "")
            path = derived_pending.get(runtime)
            if path is None:
                continue
            rows.append(_execution_row(
                derived_variant,
                derived_contract,
                status="DERIVED",
                output_path=path,
                source_variant_id=variant.get("variant_id"),
            ))
            generated_paths.append(str(path))
        derived_pending = {}

    for variant in derived_variants:
        contract = variant_export_contract(variant)
        output_path = _resolve_registry_output_path(contract.get("default_export_path"))
        if output_path is not None and str(output_path) in generated_paths:
            continue
        rows.append(_execution_row(
            variant,
            contract,
            status="BLOCK",
            output_path=output_path,
            detail="derived runtime was not emitted by a pooled_candidate_replay source",
        ))
        blockers.append(f"derived runtime not emitted for {variant.get('variant_id')}")

    for variant in row_route_composite_variants:
        contract = variant_export_contract(variant)
        output_path = _resolve_registry_output_path(contract.get("default_export_path"))
        try:
            row = _execute_candidate_row_route_composite_contract(
                variant,
                contract,
                registry=registry,
            )
        except Exception as exc:  # pragma: no cover - exercised through failure payloads in production.
            rows.append(_execution_row(
                variant,
                contract,
                status="ERROR",
                output_path=output_path,
                detail=str(exc),
            ))
            blockers.append(f"execution failed for {variant.get('variant_id')}: {exc}")
            continue
        rows.append(row)
        if output_path is not None:
            generated_paths.append(str(output_path))

    for variant in active_timesplit_variants:
        contract = variant_export_contract(variant)
        output_path = _resolve_registry_output_path(contract.get("default_export_path"))
        try:
            row = _execute_active_timesplit_logistic_repair_contract(
                variant,
                contract,
                registry_path=registry_path,
                out_dir=out_dir,
            )
        except Exception as exc:  # pragma: no cover - exercised through failure payloads in production.
            rows.append(_execution_row(
                variant,
                contract,
                status="ERROR",
                output_path=output_path,
                detail=str(exc),
            ))
            blockers.append(f"execution failed for {variant.get('variant_id')}: {exc}")
            continue
        rows.append(row)
        if output_path is not None:
            generated_paths.append(str(output_path))

    for variant in repair_integration_variants:
        contract = variant_export_contract(variant)
        output_path = _resolve_registry_output_path(contract.get("default_export_path"))
        try:
            row = _execute_repair_integration_contract(
                variant,
                contract,
                registry_path=registry_path,
                out_dir=out_dir,
            )
        except Exception as exc:  # pragma: no cover - exercised through failure payloads in production.
            rows.append(_execution_row(
                variant,
                contract,
                status="ERROR",
                output_path=output_path,
                detail=str(exc),
            ))
            blockers.append(f"execution failed for {variant.get('variant_id')}: {exc}")
            continue
        rows.append(row)
        if row.get("status") != "OK":
            blockers.append(f"execution blocked for {variant.get('variant_id')}: {row.get('detail')}")
        if output_path is not None:
            generated_paths.append(str(output_path))

    generated_paths = sorted(dict.fromkeys(generated_paths))
    status = "OK" if not blockers else ("ERROR" if any(row.get("status") == "ERROR" for row in rows) else "BLOCK")
    return {
        "status": status,
        "generated_at_utc": generated_at_utc,
        "source_paths": generated_paths,
        "executions": rows,
        "blockers": blockers,
    }


def build_payload(
    prediction_paths: list[str | Path] | tuple[str | Path, ...] | None,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    execution: dict[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    if not prediction_paths and execution is None:
        prediction_paths = active_export_paths(registry)
    contract_audit = audit_registry(registry, evidence_paths=[str(path) for path in (prediction_paths or [])])
    active_variants = headline_registry_variants(registry)
    active_ids = {str(row.get("variant_id")) for row in active_variants if row.get("variant_id")}
    raw_rows, source_paths = _path_rows([str(path) for path in (prediction_paths or [])])
    selected_rows = _filter_active_or_control_rows(raw_rows, active_ids)
    multi_variant = build_multi_variant_payload(
        selected_rows,
        variant_registry=registry,
        dedupe_shared_controls=True,
        duplicate_observation_policy="warn",
    )
    reported_ids = {
        str(row.get("variant_id"))
        for row in multi_variant.get("rows") or []
        if row.get("variant_id") and not row.get("is_control")
    }
    missing_active_ids = sorted(active_ids - reported_ids)
    status = "OK"
    blockers = []
    if not prediction_paths:
        status = "BLOCK"
        blockers.append("no active-variant export paths configured in registry")
    if contract_audit.get("status") == "ERROR":
        status = "BLOCK"
        blockers.append("active registry export contract audit failed")
    if not selected_rows:
        status = "BLOCK"
        blockers.append("no active registry variant rows were found in source paths")
    if missing_active_ids:
        status = "BLOCK"
        blockers.append("active registry variants missing from canonical shadow output")
    if multi_variant.get("status") == "ERROR":
        status = "ERROR"
        blockers.append("multi-variant shadow scorer reported errors")
    elif status == "OK" and multi_variant.get("status") == "WARN":
        status = "WARN"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "blockers": blockers,
        "source_paths": source_paths,
        "registry": {
            "path": registry.get("path"),
            "exists": registry.get("exists"),
            "contract_status": contract_audit.get("status"),
            "active_variant_count": len(active_variants),
            "active_variant_ids": sorted(active_ids),
            "reported_active_variant_ids": sorted(reported_ids),
            "missing_active_variant_ids": missing_active_ids,
        },
        "contract_audit": contract_audit,
        "execution": execution or {},
        "summary": {
            "source_path_count": len(source_paths),
            "raw_rows": len(raw_rows),
            "selected_rows": len(selected_rows),
            "canonical_rows": len(multi_variant.get("rows") or []),
            "missing_active_variant_count": len(missing_active_ids),
            "multi_variant_status": multi_variant.get("status"),
            "unique_observation_count": (multi_variant.get("summary") or {}).get("unique_observation_count", 0),
            "market_day_count": (multi_variant.get("summary") or {}).get("market_day_count", 0),
            "deduplicated_rows": (multi_variant.get("summary") or {}).get("deduplicated_rows", 0),
            "execution_status": (execution or {}).get("status"),
            "execution_count": len((execution or {}).get("executions") or []),
        },
        "multi_variant_shadow": multi_variant,
    }


def write_json(path: str | Path, payload: dict[str, Any], *, include_rows: bool = False) -> Path:
    copy = dict(payload)
    multi = dict(copy.get("multi_variant_shadow") or {})
    if not include_rows:
        multi.pop("rows", None)
    copy["multi_variant_shadow"] = multi
    return write_multi_variant_json(path, copy, include_rows=True)


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    registry = payload.get("registry") or {}
    summary = payload.get("summary") or {}
    claim_lanes = (payload.get("multi_variant_shadow") or {}).get("claim_lanes") or {}
    claim_lane_rows = [
        [
            lane,
            item.get("rows", 0),
            item.get("variant_count", 0),
            ", ".join(item.get("variant_ids") or []) or "-",
            item.get("counts_toward_weather_model_promotion_rows", 0),
            item.get("quote_risk_eligible_rows", 0),
            item.get("uses_market_features_rows", 0),
        ]
        for lane, item in sorted(claim_lanes.items())
    ] or [["-", 0, 0, "-", 0, 0, 0]]
    lines = [
        "# Active Variant Shadow Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Source paths", summary.get("source_path_count")],
                ["Raw rows", summary.get("raw_rows")],
                ["Selected rows", summary.get("selected_rows")],
                ["Canonical rows", summary.get("canonical_rows")],
                ["Unique observations", summary.get("unique_observation_count")],
                ["Market-days", summary.get("market_day_count")],
                ["Deduplicated rows", summary.get("deduplicated_rows")],
                ["Missing active variants", summary.get("missing_active_variant_count")],
            ],
        ),
        "",
        "## Claim Lane Separation",
        "",
        *markdown_table(
            [
                "Claim Lane",
                "Rows",
                "Variants",
                "Variant IDs",
                "Weather Promotion Rows",
                "Quote-Risk Eligible Rows",
                "Market-Feature Rows",
            ],
            claim_lane_rows,
        ),
        "",
        "## Active Registry Coverage",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Registry", registry.get("path")],
                ["Contract audit", registry.get("contract_status")],
                ["Active variants", ", ".join(registry.get("active_variant_ids") or []) or "-"],
                ["Reported active variants", ", ".join(registry.get("reported_active_variant_ids") or []) or "-"],
                ["Missing active variants", ", ".join(registry.get("missing_active_variant_ids") or []) or "-"],
            ],
        ),
        "",
        "## Registry Execution",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Execution status", (payload.get("execution") or {}).get("status") or "-"],
                ["Generated source paths", len((payload.get("execution") or {}).get("source_paths") or [])],
                ["Execution rows", len((payload.get("execution") or {}).get("executions") or [])],
            ],
        ),
        "",
        *markdown_table(
            ["Variant", "Runtime", "Status", "Output", "Source"],
            [
                [
                    row.get("variant_id"),
                    row.get("live_runtime"),
                    row.get("status"),
                    row.get("output_path") or "-",
                    row.get("source_variant_id") or "-",
                ]
                for row in (payload.get("execution") or {}).get("executions") or []
            ],
        ),
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend([f"- {blocker}" for blocker in blockers] or ["- none"])
    lines.extend(["", "## Source Paths", ""])
    lines.extend(markdown_table(
        ["Path", "Exists", "Bytes", "Modified UTC"],
        [
            [
                row.get("path"),
                row.get("exists"),
                row.get("bytes"),
                row.get("modified_at_utc"),
            ]
            for row in payload.get("source_paths") or []
        ],
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_outputs(
    payload: dict[str, Any],
    *,
    long_out: str | Path = DEFAULT_LONG_OUT,
    attribution_sidecar_out: str | Path = DEFAULT_ATTRIBUTION_SIDECAR_OUT,
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path, Path, Path]:
    rows = (payload.get("multi_variant_shadow") or {}).get("rows") or []
    long_path = write_long_csv(long_out, rows)
    sidecar_path = write_attribution_sidecar(attribution_sidecar_out, rows)
    json_path = write_json(json_out, payload, include_rows=False)
    report_path = write_report(report_out, payload)
    return long_path, sidecar_path, json_path, report_path


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Build canonical active-variant shadow refresh artifacts.")
    parser.add_argument("predictions", nargs="*", help="Current active variant shadow row CSV/JSON/JSONL paths.")
    parser.add_argument("--variant-registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument(
        "--execute-registry-contracts",
        action="store_true",
        help="Run active registry export contracts before building the canonical shadow artifact.",
    )
    parser.add_argument("--corpus-path", default=str(DEFAULT_BACKTEST_ROOT / "promotion_corpus.json"))
    parser.add_argument("--snapshots-root", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_EXECUTION_OUT_DIR))
    parser.add_argument("--window-corpus-out", default=str(DEFAULT_WINDOW_CORPUS_OUT))
    parser.add_argument(
        "--active-variant-shadow-window-dates",
        type=int,
        default=DEFAULT_EVIDENCE_WINDOW_DATES,
    )
    parser.add_argument("--min-artifact-free-bytes", type=int, default=0)
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--replay-cache", default="read_write", choices=["read_write", "write_only", "off"])
    parser.add_argument("--replay-cache-root", default="")
    parser.add_argument("--disable-replay-cache-sentinel", action="store_true")
    parser.add_argument("--long-out", default=str(DEFAULT_LONG_OUT))
    parser.add_argument("--attribution-sidecar-out", default=str(DEFAULT_ATTRIBUTION_SIDECAR_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)

    predictions = list(args.predictions)
    execution = None
    evidence_window = None
    if args.execute_registry_contracts and not predictions:
        evidence_window = windowed_corpus_manifest(
            args.corpus_path,
            args.window_corpus_out,
            window_dates=args.active_variant_shadow_window_dates,
        )
        execution = execute_registry_prediction_exports(
            registry_path=args.variant_registry,
            corpus_path=evidence_window["path"],
            snapshots_root=args.snapshots_root or None,
            out_dir=args.out_dir,
            min_artifact_free_bytes=args.min_artifact_free_bytes,
            current_tol=args.current_tol,
            market_tol=args.market_tol,
            min_days=args.min_days,
            min_trust=args.min_trust,
            require_exact_identity=args.require_exact_identity,
            require_all_markets=args.require_all_markets,
            replay_cache=args.replay_cache,
            replay_cache_root=args.replay_cache_root or None,
            disable_replay_cache_sentinel=args.disable_replay_cache_sentinel,
        )
        predictions = execution.get("source_paths") or []

    payload = build_payload(predictions, registry_path=args.variant_registry, execution=execution)
    if evidence_window is not None:
        payload["evidence_window"] = evidence_window
    long_path, sidecar_path, json_path, report_path = write_outputs(
        payload,
        long_out=args.long_out,
        attribution_sidecar_out=args.attribution_sidecar_out,
        json_out=args.json_out,
        report_out=args.report_out,
    )
    print(f"Active variant shadow refresh: {payload['status']}")
    print(f"Long table written to {long_path}")
    print(f"Attribution sidecar written to {sidecar_path}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
