"""Bounded, replay-only workstation taker strategy bakeoff.

This harness freezes an explicit set of paper-taker run folders, audits every
input without modifying it, replays the registered strategy basket with the
settlement-learning permission fence disabled, and aggregates results at the
market-day and fleet-date levels.  It is deliberately research-only: exchange
economics freshness remains visible and no result can promote or enable live
trading.

The canonical order tapes and settlement labels are treated as immutable
inputs. Every output path must resolve outside the explicit read-only root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from weather.io import (
    iter_csv_rows,
    read_json,
    sha256_file,
    write_csv_rows_atomic,
    write_json_atomic,
    write_text_atomic,
)
from weather.market.market_registry import all_specs
from weather.market.mm_policy import bool_value, maybe_float
from weather.market.taker_bot_bakeoff import (
    SETTLEMENT_PNL_SOURCES,
    _read_bakeoff_source_summary,
    run_taker_strategy_bakeoff,
    taker_settlement_label_complete,
)
from weather.market.taker_bot_strategy_registry import (
    DEFAULT_CONFIG,
    DEFAULT_CONTROL_STRATEGY_ID,
)
from weather.reporting.research.research_path_contract import resolve_output_outside_read_only_roots
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("workstation_taker_bakeoff")
CONTROL_STRATEGY_ID = DEFAULT_CONTROL_STRATEGY_ID
ALL_STRATEGIES = (
    "raw_edge_control",
    "calibrated_edge",
    "low_price_tail_capped",
    "fade_overpriced",
    "winner_centered_or_adjacent",
    "current_high_lockin",
    "late_day_liquidity_filtered",
    "strict_edge_probe",
    "small_order_probe",
)
SIDE_VALUES = ("ALL", "YES", "NO")
BOOTSTRAP_SEED = 20_260_722
BOOTSTRAP_REPLICATES = 10_000
MIN_HIGH_COVERAGE_SPAN_MINUTES = 12 * 60
MIN_MODERATE_COVERAGE_SPAN_MINUTES = 4 * 60
MAX_FILLED_CASE_ROWS_PER_DAY = 5_000
EXPERIMENT_ID_PREFIX = "workstation-unfenced-taker-bakeoff"
ECONOMICS_CONFIG_KEYS = (
    "taker_fee_rate",
    "taker_fee_model",
    "taker_fee_market_category",
    "taker_fee_effective_date",
    "taker_fee_provenance_url",
    "executable_depth_model",
    "executable_depth_slippage_bps",
    "executable_depth_haircut",
)
RESEARCH_CONFIG = {
    "taker_edge_permission_enabled": False,
    **{key: DEFAULT_CONFIG[key] for key in ECONOMICS_CONFIG_KEYS},
}
COUNT_FIELDS = (
    "evaluated_rows",
    "priced_rows",
    "positive_raw_edge_rows",
    "positive_after_cost_ev_rows",
    "buy_action_rows",
    "filled_rows",
    "settled_filled_rows",
    "winning_fills",
    "losing_fills",
    "unmatched_filled_rows",
    "after_fee_scored_fills",
    "after_slippage_scored_fills",
    "real_no_book_rows",
    "real_no_book_depth_eligible_rows",
)
SUM_FIELDS = (
    "spent_usdc",
    "gross_pnl_usdc",
    "fee_usdc",
    "slippage_usdc",
    "modeled_cost_usdc",
    "net_after_modeled_costs_usdc",
)
MARKET_DAY_CSV_COLUMNS = (
    "target_date",
    "market_id",
    "strategy_id",
    "side",
    "input_market_observed",
    "label_available",
    *COUNT_FIELDS,
    *SUM_FIELDS,
    "reason_counts_json",
)
DAILY_CSV_COLUMNS = (
    "target_date",
    "strategy_id",
    "side",
    "primary_eligible",
    *COUNT_FIELDS,
    *SUM_FIELDS,
)
FILLED_CASE_CSV_COLUMNS = (
    "target_date",
    "market_id",
    "strategy_id",
    "strategy_family",
    "side",
    "event_slug",
    "snapshot_id",
    "captured_at_utc",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "model_variant_id",
    "fair_probability",
    "calibrated_model_probability",
    "market_implied_probability",
    "calibrated_fair_probability",
    "best_ask",
    "no_best_ask",
    "edge",
    "calibrated_edge",
    "calibrated_after_fee_edge",
    "after_cost_ev_per_share",
    "expected_profit_after_friction_per_share",
    "taker_skill_weight",
    "reliability_confidence",
    "reliability_adjusted_fair_probability",
    "risk_adjusted_edge",
    "risk_adjusted_expected_profit_per_share",
    "low_price_tail",
    "tail_risk_bucket",
    "current_high_band_distance",
    "market_modal_band_key",
    "market_modal_probability",
    "fill_price",
    "fill_size",
    "fill_notional_usdc",
    "fee_usdc",
    "slippage_usdc",
    "total_spent_usdc",
    "settlement_outcome",
    "gross_pnl_usdc",
    "net_pnl_usdc",
    "pnl_source",
    "no_book_source",
    "real_no_book_depth_eligible",
    "reason_code",
    "strategy_config_hash",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _round(value: float | int | None, digits: int = 6) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value), digits)


def _canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_seed(*parts: Any, seed: int = BOOTSTRAP_SEED) -> int:
    digest = _canonical_hash([seed, *parts])
    return int(digest[:16], 16)


def _require_safe_output(path: str | Path, *, read_only_data_root: str | Path) -> Path:
    return resolve_output_outside_read_only_roots(
        path, read_only_roots=[read_only_data_root]
    )


def _file_fingerprint(path: Path, *, include_hash: bool = True) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path) if include_hash else None,
    }


def _same_stat(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_size = left.get("size_bytes")
    right_size = right.get("size_bytes")
    left_mtime = left.get("mtime_ns")
    right_mtime = right.get("mtime_ns")
    return (
        left_size is not None
        and right_size is not None
        and left_mtime is not None
        and right_mtime is not None
        and int(left_size) == int(right_size)
        and int(left_mtime) == int(right_mtime)
    )


def expected_market_ids() -> tuple[str, ...]:
    return tuple(spec.id for spec in all_specs())


def _strategy_list(value: str | Sequence[str] | None) -> list[str]:
    if value in (None, ""):
        return list(ALL_STRATEGIES)
    if isinstance(value, str):
        result = [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    else:
        result = [str(item).strip() for item in value if str(item).strip()]
    if len(result) != len(set(result)):
        raise ValueError("strategy ids must be unique")
    if CONTROL_STRATEGY_ID not in result:
        raise ValueError(f"strategy basket must contain control {CONTROL_STRATEGY_ID!r}")
    return result


def create_frozen_manifest(
    run_folders: Sequence[str | Path],
    *,
    labels_csv: str | Path,
    exchange_economics_snapshot_path: str | Path,
    latest_label_date: str,
    strategies: str | Sequence[str] | None = None,
    provenance: str = "read-only workstation mirror",
) -> dict[str, Any]:
    """Create a replay manifest from explicit, absolute, non-quarantine paths."""

    rows = []
    seen_dates: set[str] = set()
    latest = str(latest_label_date)
    for raw_folder in run_folders:
        folder = Path(raw_folder)
        if not folder.is_absolute():
            raise ValueError(f"run folder must be absolute: {folder}")
        folder = folder.resolve()
        if any(part.lower() == "_quarantine" for part in folder.parts):
            raise ValueError(f"quarantined run folders are forbidden: {folder}")
        target_date = folder.parent.name
        if target_date in seen_dates:
            raise ValueError(f"one run folder per target date is required: {target_date}")
        if target_date > latest:
            raise ValueError(f"run {target_date} is later than frozen label cutoff {latest}")
        seen_dates.add(target_date)
        rows.append({"target_date": target_date, "run_folder": str(folder)})
    rows.sort(key=lambda row: row["target_date"])
    if not rows:
        raise ValueError("at least one explicit run folder is required")
    if rows[-1]["target_date"] != latest:
        raise ValueError("frozen run list must reach the latest fully countable label date")
    labels_path = Path(labels_csv).resolve()
    economics_path = Path(exchange_economics_snapshot_path).resolve()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "frozen_input_manifest",
        "created_at_utc": utc_now().isoformat(),
        "research_only": True,
        "writes_to_input_tree": False,
        "data_provenance": provenance,
        "run_selection_policy": (
            "explicit one-per-date run folders frozen before replay; candidates were selected "
            "by largest non-empty direct orders_long.csv and quarantine paths were excluded"
        ),
        "latest_fully_settled_countable_label_date": latest,
        "labels_csv": str(labels_path),
        "exchange_economics_snapshot_path": str(economics_path),
        "strategies": _strategy_list(strategies),
        "expected_market_ids": list(expected_market_ids()),
        "config_overrides": dict(RESEARCH_CONFIG),
        "bootstrap": {
            "unit": "fleet_date",
            "seed": BOOTSTRAP_SEED,
            "replicates": BOOTSTRAP_REPLICATES,
            "interval": "percentile_95",
        },
        "run_folders": rows,
    }
    payload["manifest_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key not in {"created_at_utc", "manifest_hash"}}
    )
    return payload


def validate_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest schema: {payload.get('schema_version')!r}")
    if payload.get("artifact_type") != "frozen_input_manifest":
        raise ValueError("expected a frozen_input_manifest")
    normalized = create_frozen_manifest(
        [row.get("run_folder") for row in payload.get("run_folders") or []],
        labels_csv=payload.get("labels_csv") or "",
        exchange_economics_snapshot_path=payload.get("exchange_economics_snapshot_path") or "",
        latest_label_date=payload.get("latest_fully_settled_countable_label_date") or "",
        strategies=payload.get("strategies") or (),
        provenance=payload.get("data_provenance") or "",
    )
    supplied_hash = payload.get("manifest_hash")
    actual_hash = _canonical_hash(
        {key: value for key, value in payload.items() if key not in {"created_at_utc", "manifest_hash"}}
    )
    if not supplied_hash or supplied_hash != actual_hash:
        raise ValueError("frozen manifest hash does not match its replay-defining fields")
    if supplied_hash != normalized["manifest_hash"]:
        raise ValueError("frozen manifest no longer matches the registered strategy/economics contract")
    return dict(payload)


def load_manifest(path: str | Path) -> dict[str, Any]:
    payload = read_json(path, {}) or {}
    return validate_manifest(payload)


def _label_support_rows(
    labels_csv: str | Path,
    *,
    expected_markets: Sequence[str],
) -> dict[str, dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_csv_rows(labels_csv, attach_diagnostics=True):
        target_date = str(row.get("target_date") or "")
        if target_date:
            by_date[target_date].append(row)
    expected = set(expected_markets)
    result: dict[str, dict[str, Any]] = {}
    for target_date, rows in sorted(by_date.items()):
        market_counts = Counter(str(row.get("market_id") or "") for row in rows)
        observed = {market for market in market_counts if market}
        complete = sum(int(taker_settlement_label_complete(row)) for row in rows)
        countable = sum(int(bool_value(row.get("promotion_countable"), False)) for row in rows)
        blocking_reconciliation = sum(
            str(row.get("reconciliation_status") or "").strip().lower()
            in {"mismatch", "not_closed", "unavailable", "fetch_error"}
            for row in rows
        )
        duplicate_markets = sorted(market for market, count in market_counts.items() if market and count > 1)
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        fully_supported = bool(
            rows
            and not missing
            and not extra
            and not duplicate_markets
            and complete == len(rows)
            and countable == len(rows)
            and not blocking_reconciliation
        )
        result[target_date] = {
            "target_date": target_date,
            "label_row_count": len(rows),
            "observed_market_count": len(observed),
            "observed_market_ids": sorted(observed),
            "expected_market_count": len(expected),
            "missing_market_ids": missing,
            "unexpected_market_ids": extra,
            "duplicate_market_ids": duplicate_markets,
            "taker_complete_label_count": complete,
            "promotion_countable_label_count": countable,
            "blocking_reconciliation_count": blocking_reconciliation,
            "fully_settled_countable_fleet": fully_supported,
        }
    return result


def _capture_span_minutes(first: str | None, last: str | None) -> float | None:
    if not first or not last:
        return None
    try:
        start = datetime.fromisoformat(first.replace("Z", "+00:00"))
        end = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (end - start).total_seconds() / 60.0)


def audit_run_folder(
    run_row: Mapping[str, Any],
    *,
    expected_markets: Sequence[str],
) -> dict[str, Any]:
    """Stream and fingerprint one source tape; never write beside the input."""

    target_date = str(run_row.get("target_date") or "")
    folder = Path(run_row.get("run_folder") or "").resolve()
    orders_path = folder / "orders_long.csv"
    blockers: list[str] = []
    warnings: list[str] = []
    if any(part.lower() == "_quarantine" for part in folder.parts):
        blockers.append("quarantine_path_forbidden")
    if not orders_path.is_file():
        return {
            "target_date": target_date,
            "run_folder": str(folder),
            "orders_path": str(orders_path),
            "status": "BLOCK",
            "replay_eligible": False,
            "primary_input_eligible": False,
            "blockers": [*blockers, "missing_orders_tape"],
            "warnings": warnings,
        }

    stat_before = _file_fingerprint(orders_path, include_hash=False)
    row_count = 0
    market_ids: set[str] = set()
    event_slugs: set[str] = set()
    target_counts: Counter[str] = Counter()
    min_capture: str | None = None
    max_capture: str | None = None
    missing_snapshot_id = 0
    missing_capture_time = 0
    for row in iter_csv_rows(orders_path, attach_diagnostics=True):
        row_count += 1
        market = str(row.get("market_id") or "")
        if market:
            market_ids.add(market)
        slug = str(row.get("event_slug") or "")
        if slug:
            event_slugs.add(slug)
        row_target = str(row.get("target_date") or "")
        target_counts[row_target or "<missing>"] += 1
        capture = str(row.get("captured_at_utc") or "")
        if capture:
            min_capture = capture if min_capture is None or capture < min_capture else min_capture
            max_capture = capture if max_capture is None or capture > max_capture else max_capture
        else:
            missing_capture_time += 1
        missing_snapshot_id += int(not row.get("snapshot_id"))
    stat_after = _file_fingerprint(orders_path, include_hash=False)
    if not _same_stat(stat_before, stat_after):
        blockers.append("orders_tape_changed_during_audit")
    if row_count == 0:
        blockers.append("empty_orders_tape")
    bad_targets = sorted(value for value in target_counts if value != target_date)
    if bad_targets:
        blockers.append("orders_target_date_mismatch")
    expected = set(expected_markets)
    missing_markets = sorted(expected - market_ids)
    unexpected_markets = sorted(market_ids - expected)
    if missing_markets:
        warnings.append("partial_input_market_fleet")
    if unexpected_markets:
        warnings.append("unexpected_input_markets")
    span = _capture_span_minutes(min_capture, max_capture)
    if span is None or span < MIN_HIGH_COVERAGE_SPAN_MINUTES:
        warnings.append("short_capture_span")
    if missing_capture_time:
        warnings.append("rows_missing_capture_time")
    if missing_snapshot_id:
        warnings.append("rows_missing_snapshot_id")

    run_config = read_json(folder / "run_config.json", {}) or {}
    source_summary = _read_bakeoff_source_summary(folder / "run_summary.json")
    fingerprint = _file_fingerprint(orders_path, include_hash=True)
    stat_final = _file_fingerprint(orders_path, include_hash=False)
    if not _same_stat(stat_after, stat_final):
        blockers.append("orders_tape_changed_during_hash")
    replay_eligible = bool(row_count and not blockers)
    primary_input = bool(
        replay_eligible
        and not missing_markets
        and not unexpected_markets
        and market_ids == expected
    )
    return {
        "target_date": target_date,
        "run_folder": str(folder),
        "orders_path": str(orders_path),
        "status": "BLOCK" if blockers else ("WARN" if warnings else "PASS"),
        "replay_eligible": replay_eligible,
        "primary_input_eligible": primary_input,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "orders_fingerprint": fingerprint,
        "source_row_count": row_count,
        "target_date_counts": dict(sorted(target_counts.items())),
        "observed_market_count": len(market_ids),
        "observed_market_ids": sorted(market_ids),
        "missing_market_ids": missing_markets,
        "unexpected_market_ids": unexpected_markets,
        "event_slug_count": len(event_slugs),
        "min_captured_at_utc": min_capture,
        "max_captured_at_utc": max_capture,
        "capture_span_minutes": _round(span),
        "missing_capture_time_row_count": missing_capture_time,
        "missing_snapshot_id_row_count": missing_snapshot_id,
        "run_config_target_date": run_config.get("target_date"),
        "run_config_run_id": run_config.get("run_id"),
        "run_config_markets": list(run_config.get("markets") or []),
        "source_summary_target_date": source_summary.get("target_date"),
        "source_summary_run_id": source_summary.get("run_id"),
        "source_summary_fields": source_summary.get("summary") or {},
    }


def audit_manifest(
    manifest: Mapping[str, Any],
    *,
    out_root: str | Path,
    read_only_data_root: str | Path,
) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    out_root = _require_safe_output(out_root, read_only_data_root=read_only_data_root)
    out_root.mkdir(parents=True, exist_ok=True)
    markets = list(manifest.get("expected_market_ids") or expected_market_ids())
    labels_path = Path(manifest["labels_csv"])
    economics_path = Path(manifest["exchange_economics_snapshot_path"])
    label_support = _label_support_rows(labels_path, expected_markets=markets)
    fully_supported_dates = sorted(
        target for target, row in label_support.items()
        if row["fully_settled_countable_fleet"]
    )
    computed_latest = fully_supported_dates[-1] if fully_supported_dates else None
    frozen_latest = manifest.get("latest_fully_settled_countable_label_date")
    global_blockers = []
    if computed_latest != frozen_latest:
        global_blockers.append("frozen_latest_label_date_mismatch")
    run_audits = []
    for index, row in enumerate(manifest.get("run_folders") or [], start=1):
        print(f"audit {index}/{len(manifest['run_folders'])}: {row['target_date']}", flush=True)
        run_audits.append(audit_run_folder(row, expected_markets=markets))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "input_audit",
        "generated_at_utc": utc_now().isoformat(),
        "manifest_hash": manifest.get("manifest_hash"),
        "research_only": True,
        "input_tree_mutated": False,
        "status": "BLOCK" if global_blockers else "PASS",
        "global_blockers": global_blockers,
        "labels_fingerprint": _file_fingerprint(labels_path),
        "exchange_economics_snapshot_fingerprint": _file_fingerprint(economics_path),
        "computed_latest_fully_settled_countable_label_date": computed_latest,
        "fully_settled_countable_label_dates": fully_supported_dates,
        "label_support": [label_support.get(row["target_date"], {
            "target_date": row["target_date"],
            "fully_settled_countable_fleet": False,
            "missing_reason": "no_label_rows",
        }) for row in manifest.get("run_folders") or []],
        "run_audits": run_audits,
        "summary": {
            "run_count": len(run_audits),
            "replay_eligible_run_count": sum(int(row.get("replay_eligible", False)) for row in run_audits),
            "primary_input_eligible_run_count": sum(
                int(row.get("primary_input_eligible", False)) for row in run_audits
            ),
            "blocked_run_count": sum(int(row.get("status") == "BLOCK") for row in run_audits),
            "warning_run_count": sum(int(row.get("status") == "WARN") for row in run_audits),
        },
    }
    write_json_atomic(out_root / "input_audit.json", payload, trailing_newline=True)
    return payload


def _new_metrics() -> dict[str, Any]:
    return {
        **{field: 0 for field in COUNT_FIELDS},
        **{field: 0.0 for field in SUM_FIELDS},
        "reason_counts": Counter(),
    }


def _side_for_row(row: Mapping[str, Any]) -> str:
    return "NO" if str(row.get("side") or "").upper().startswith("NO") else "YES"


def _add_metrics(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for field in COUNT_FIELDS:
        target[field] += int(source.get(field) or 0)
    for field in SUM_FIELDS:
        target[field] += float(source.get(field) or 0.0)
    target["reason_counts"].update(source.get("reason_counts") or {})


def _finalize_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{field: int(metrics.get(field) or 0) for field in COUNT_FIELDS},
        **{field: _round(float(metrics.get(field) or 0.0)) for field in SUM_FIELDS},
        "reason_counts": dict(sorted((metrics.get("reason_counts") or {}).items())),
    }


def _update_metrics(metrics: dict[str, Any], row: Mapping[str, Any], side: str) -> None:
    metrics["evaluated_rows"] += 1
    price = maybe_float(row.get("no_best_ask") if side == "NO" else row.get("best_ask"))
    metrics["priced_rows"] += int(price is not None)
    raw_edge = maybe_float(row.get("edge"))
    metrics["positive_raw_edge_rows"] += int(raw_edge is not None and raw_edge > 0)
    after_cost_ev = maybe_float(row.get("after_cost_ev_per_share"))
    metrics["positive_after_cost_ev_rows"] += int(after_cost_ev is not None and after_cost_ev > 0)
    action = str(row.get("action") or "").upper()
    filled = str(row.get("order_status") or "").upper() == "FILLED"
    metrics["buy_action_rows"] += int(action == "BUY")
    metrics["filled_rows"] += int(filled)
    reason = str(row.get("reason_code") or "unknown")
    metrics["reason_counts"][reason] += 1
    if side == "NO":
        real_book = row.get("no_book_source") == "no_token_book"
        metrics["real_no_book_rows"] += int(real_book)
        metrics["real_no_book_depth_eligible_rows"] += int(
            real_book and bool_value(row.get("real_no_book_depth_eligible"), False)
        )
    if not filled:
        return
    fee = maybe_float(row.get("fee_usdc")) or 0.0
    slippage = maybe_float(row.get("slippage_usdc")) or 0.0
    metrics["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
    metrics["fee_usdc"] += fee
    metrics["slippage_usdc"] += slippage
    metrics["modeled_cost_usdc"] += fee + slippage
    metrics["after_fee_scored_fills"] += int(
        bool_value(row.get("after_fee_pnl_scored"), False)
        or row.get("pnl_fee_basis") in {"after_fee", "fees_included", "net_after_fee"}
    )
    metrics["after_slippage_scored_fills"] += int(
        bool_value(row.get("after_slippage_pnl_scored"), False)
        or bool(row.get("executable_depth_model_version"))
    )
    settled = row.get("pnl_source") in SETTLEMENT_PNL_SOURCES
    metrics["settled_filled_rows"] += int(settled)
    if not settled:
        metrics["unmatched_filled_rows"] += 1
        return
    outcome = maybe_float(row.get("settlement_outcome"))
    metrics["winning_fills"] += int(outcome == 1.0)
    metrics["losing_fills"] += int(outcome == 0.0)
    metrics["gross_pnl_usdc"] += maybe_float(row.get("gross_pnl_usdc")) or 0.0
    metrics["net_after_modeled_costs_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0


def summarize_scored_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    target_date: str,
    strategies: Sequence[str],
    expected_markets: Sequence[str],
    label_markets: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Collapse spilled scored rows into exact, bounded market-day cells."""

    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    observed_markets: set[str] = set()
    unknown_strategies: Counter[str] = Counter()
    source_rows = 0
    filled_case_rows = []
    filled_case_overflow_count = 0
    strategy_set = set(strategies)
    for row in rows:
        source_rows += 1
        strategy_id = str(row.get("strategy_id") or CONTROL_STRATEGY_ID)
        if strategy_id not in strategy_set:
            unknown_strategies[strategy_id] += 1
            continue
        market_id = str(row.get("market_id") or "unknown")
        observed_markets.add(market_id)
        side = _side_for_row(row)
        key = (strategy_id, market_id, side)
        metrics = by_key.setdefault(key, _new_metrics())
        _update_metrics(metrics, row, side)
        if str(row.get("order_status") or "").upper() == "FILLED":
            if len(filled_case_rows) < MAX_FILLED_CASE_ROWS_PER_DAY:
                filled_case_rows.append({key: row.get(key) for key in FILLED_CASE_CSV_COLUMNS})
            else:
                filled_case_overflow_count += 1

    market_ids = sorted(set(expected_markets) | observed_markets)
    available_labels = set(label_markets if label_markets is not None else expected_markets)
    market_rows = []
    for strategy_id in strategies:
        for market_id in market_ids:
            side_metrics = {}
            for side in ("YES", "NO"):
                side_metrics[side] = by_key.get((strategy_id, market_id, side), _new_metrics())
            all_metrics = _new_metrics()
            _add_metrics(all_metrics, side_metrics["YES"])
            _add_metrics(all_metrics, side_metrics["NO"])
            side_metrics["ALL"] = all_metrics
            for side in SIDE_VALUES:
                market_rows.append({
                    "target_date": target_date,
                    "market_id": market_id,
                    "strategy_id": strategy_id,
                    "side": side,
                    "input_market_observed": market_id in observed_markets,
                    "label_available": market_id in available_labels,
                    **_finalize_metrics(side_metrics[side]),
                })

    daily_rows = []
    for strategy_id in strategies:
        for side in SIDE_VALUES:
            metrics = _new_metrics()
            for row in market_rows:
                if row["strategy_id"] == strategy_id and row["side"] == side:
                    _add_metrics(metrics, row)
            daily_rows.append({
                "target_date": target_date,
                "strategy_id": strategy_id,
                "side": side,
                **_finalize_metrics(metrics),
            })
    return {
        "source_scored_row_count": source_rows,
        "unknown_strategy_counts": dict(sorted(unknown_strategies.items())),
        "observed_market_ids": sorted(observed_markets),
        "filled_order_rows": filled_case_rows,
        "filled_order_row_overflow_count": filled_case_overflow_count,
        "market_day_rows": market_rows,
        "daily_strategy_rows": daily_rows,
    }


def _audit_indexes(audit: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    run_index = {row["target_date"]: row for row in audit.get("run_audits") or []}
    label_index = {row["target_date"]: row for row in audit.get("label_support") or []}
    return run_index, label_index


def _verify_audited_tape_unchanged(run_audit: Mapping[str, Any]) -> None:
    fingerprint = run_audit.get("orders_fingerprint") or {}
    path = Path(fingerprint.get("path") or run_audit.get("orders_path") or "")
    current = _file_fingerprint(path, include_hash=False)
    if not _same_stat(fingerprint, current):
        raise RuntimeError(f"audited orders tape changed before replay: {path}")
    if not fingerprint.get("sha256") or sha256_file(path) != fingerprint.get("sha256"):
        raise RuntimeError(f"audited orders tape hash changed before replay: {path}")


def _verify_shared_inputs_unchanged(
    manifest: Mapping[str, Any], audit: Mapping[str, Any]
) -> None:
    for manifest_key, audit_key in (
        ("labels_csv", "labels_fingerprint"),
        ("exchange_economics_snapshot_path", "exchange_economics_snapshot_fingerprint"),
    ):
        path = Path(manifest[manifest_key])
        expected = audit.get(audit_key) or {}
        current = _file_fingerprint(path, include_hash=False)
        if not _same_stat(expected, current):
            raise RuntimeError(f"audited shared input changed before replay: {path}")
        if not expected.get("sha256") or sha256_file(path) != expected.get("sha256"):
            raise RuntimeError(f"audited shared input hash changed before replay: {path}")


def run_one_day(
    manifest: Mapping[str, Any],
    audit: Mapping[str, Any],
    run_row: Mapping[str, Any],
    *,
    out_root: str | Path,
    read_only_data_root: str | Path,
) -> dict[str, Any]:
    out_root = _require_safe_output(out_root, read_only_data_root=read_only_data_root)
    target_date = str(run_row["target_date"])
    run_index, label_index = _audit_indexes(audit)
    run_audit = run_index[target_date]
    if not run_audit.get("replay_eligible"):
        raise RuntimeError(f"run {target_date} failed the read-only replay audit")
    _verify_shared_inputs_unchanged(manifest, audit)
    _verify_audited_tape_unchanged(run_audit)
    day_dir = out_root / "days" / target_date
    day_dir.mkdir(parents=True, exist_ok=True)
    canonical_json = day_dir / "strategy_bakeoff.json"
    canonical_report = day_dir / "strategy_bakeoff.md"
    strategies = list(manifest["strategies"])
    payload = run_taker_strategy_bakeoff(
        run_row["run_folder"],
        labels_csv=manifest["labels_csv"],
        strategies=",".join(strategies),
        out_json=canonical_json,
        out_report=canonical_report,
        experiment_id=f"{EXPERIMENT_ID_PREFIX}-{target_date}",
        config=dict(manifest["config_overrides"]),
        exchange_economics_snapshot_path=manifest["exchange_economics_snapshot_path"],
        exchange_economics_required=True,
        stream_tapes=True,
        materialize_output_rows=False,
    )
    try:
        compact = summarize_scored_rows(
            payload.iter_scored_rows(),
            target_date=target_date,
            strategies=strategies,
            expected_markets=manifest["expected_market_ids"],
            label_markets=(label_index.get(target_date) or {}).get("observed_market_ids") or (),
        )
        pnl = payload.get("pnl") or {}
        day_summary = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "day_replay_summary",
            "generated_at_utc": utc_now().isoformat(),
            "manifest_hash": manifest.get("manifest_hash"),
            "research_only": True,
            "permission_fence_disabled": True,
            "target_date": target_date,
            "run_folder": str(Path(run_row["run_folder"]).resolve()),
            "orders_fingerprint": run_audit.get("orders_fingerprint"),
            "input_audit_status": run_audit.get("status"),
            "primary_input_eligible": bool(run_audit.get("primary_input_eligible")),
            "label_support": label_index.get(target_date) or {},
            "canonical_bakeoff_json": str(canonical_json),
            "canonical_bakeoff_sha256": sha256_file(canonical_json),
            "canonical_bakeoff_report": str(canonical_report),
            "projection_json": str(day_dir / "strategy_bakeoff_ledger_projection.json"),
            "strategies": strategies,
            "config_overrides": dict(manifest["config_overrides"]),
            "exchange_economics_gate": payload.get("exchange_economics_gate") or {},
            "bakeoff_summary": payload.get("summary") or {},
            "score_summary": payload.get("score_summary") or {},
            "label_summary": payload.get("label_summary") or {},
            "blockers": payload.get("blockers") or [],
            "pnl_by_strategy": pnl.get("by_strategy") or [],
            **compact,
        }
        write_json_atomic(day_dir / "day_summary.json", day_summary, trailing_newline=True)
        return day_summary
    finally:
        payload.close()


def _day_summary_matches(
    payload: Mapping[str, Any], manifest: Mapping[str, Any], run_row: Mapping[str, Any]
) -> bool:
    metadata_matches = bool(
        payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("artifact_type") == "day_replay_summary"
        and payload.get("manifest_hash") == manifest.get("manifest_hash")
        and payload.get("target_date") == run_row.get("target_date")
        and payload.get("run_folder") == str(Path(run_row.get("run_folder") or "").resolve())
        and payload.get("strategies") == manifest.get("strategies")
    )
    if not metadata_matches:
        return False
    fingerprint = payload.get("orders_fingerprint") or {}
    source_path = Path(fingerprint.get("path") or "")
    if not source_path.is_file() or not _same_stat(fingerprint, _file_fingerprint(source_path, include_hash=False)):
        return False
    if not fingerprint.get("sha256") or sha256_file(source_path) != fingerprint.get("sha256"):
        return False
    canonical_path = Path(payload.get("canonical_bakeoff_json") or "")
    expected_sha = payload.get("canonical_bakeoff_sha256")
    return bool(
        canonical_path.is_file()
        and expected_sha
        and sha256_file(canonical_path) == expected_sha
    )


def run_replays(
    manifest: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    out_root: str | Path,
    read_only_data_root: str | Path,
    resume: bool = True,
    max_days: int = 0,
) -> list[dict[str, Any]]:
    out_root = _require_safe_output(out_root, read_only_data_root=read_only_data_root)
    if audit.get("status") == "BLOCK":
        raise RuntimeError(f"input audit is blocked: {audit.get('global_blockers')}")
    _verify_shared_inputs_unchanged(manifest, audit)
    run_index, _label_index = _audit_indexes(audit)
    run_rows = list(manifest.get("run_folders") or [])
    if max_days > 0:
        run_rows = run_rows[:max_days]
    progress_path = out_root / "replay_progress.json"
    results = []
    for index, run_row in enumerate(run_rows, start=1):
        target_date = run_row["target_date"]
        day_path = out_root / "days" / target_date / "day_summary.json"
        existing = read_json(day_path, {}) or {}
        if resume and _day_summary_matches(existing, manifest, run_row):
            result = existing
            action = "resume"
        elif not run_index.get(target_date, {}).get("replay_eligible"):
            result = {
                "schema_version": SCHEMA_VERSION,
                "artifact_type": "day_replay_summary",
                "manifest_hash": manifest.get("manifest_hash"),
                "target_date": target_date,
                "run_folder": run_row["run_folder"],
                "status": "skipped_input_audit_block",
                "error": ",".join(run_index.get(target_date, {}).get("blockers") or []),
            }
            action = "skip"
        else:
            try:
                result = run_one_day(
                    manifest,
                    audit,
                    run_row,
                    out_root=out_root,
                    read_only_data_root=read_only_data_root,
                )
                result["status"] = "ok"
                action = "run"
            except Exception as exc:  # noqa: BLE001 - preserve progress across independent dates
                result = {
                    "schema_version": SCHEMA_VERSION,
                    "artifact_type": "day_replay_summary",
                    "manifest_hash": manifest.get("manifest_hash"),
                    "target_date": target_date,
                    "run_folder": run_row["run_folder"],
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                action = "error"
        results.append(result)
        progress = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "replay_progress",
            "generated_at_utc": utc_now().isoformat(),
            "manifest_hash": manifest.get("manifest_hash"),
            "completed_count": len(results),
            "planned_count": len(run_rows),
            "ok_count": sum(int(row.get("status", "ok") == "ok") for row in results),
            "error_count": sum(int(row.get("status") == "error") for row in results),
            "days": [{
                "target_date": row.get("target_date"),
                "status": row.get("status", "ok"),
                "error": row.get("error"),
            } for row in results],
        }
        write_json_atomic(progress_path, progress, trailing_newline=True)
        generated = (result.get("bakeoff_summary") or {}).get("generated_order_rows")
        print(
            f"replay {index}/{len(run_rows)} {target_date}: {action}; generated_rows={generated}",
            flush=True,
        )
    return results


def _percentile(sorted_values: Sequence[float], probability: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    seed: int,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Deterministic percentile CI from whole fleet-date resamples."""

    clean = [float(value) for value in values]
    if not clean:
        return {
            "n": 0,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "positive_count": 0,
            "negative_count": 0,
            "tie_count": 0,
            "replicates": int(replicates),
            "seed": int(seed),
        }
    rng = random.Random(seed)
    n = len(clean)
    means = []
    for _index in range(int(replicates)):
        means.append(sum(clean[rng.randrange(n)] for _item in range(n)) / n)
    means.sort()
    return {
        "n": n,
        "mean": _round(sum(clean) / n),
        "ci_low": _round(_percentile(means, 0.025)),
        "ci_high": _round(_percentile(means, 0.975)),
        "positive_count": sum(int(value > 0) for value in clean),
        "negative_count": sum(int(value < 0) for value in clean),
        "tie_count": sum(int(value == 0) for value in clean),
        "replicates": int(replicates),
        "seed": int(seed),
    }


def _sum_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = _new_metrics()
    for row in rows:
        _add_metrics(metrics, row)
    return _finalize_metrics(metrics)


def _own_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    strategy_id: str,
    side: str,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    selected = [row for row in rows if row["strategy_id"] == strategy_id and row["side"] == side]
    values = [float(row.get("net_after_modeled_costs_usdc") or 0.0) for row in selected]
    ci = bootstrap_mean_ci(values, seed=seed, replicates=replicates)
    totals = _sum_rows(selected)
    survives = bool(
        totals["settled_filled_rows"] > 0
        and (ci["mean"] or 0.0) > 0
        and (ci["ci_low"] or 0.0) > 0
    )
    return {
        "strategy_id": strategy_id,
        "side": side,
        "date_count": len(selected),
        **totals,
        "equal_fleet_date_mean_net_usdc": ci["mean"],
        "fleet_date_bootstrap_ci_low_usdc": ci["ci_low"],
        "fleet_date_bootstrap_ci_high_usdc": ci["ci_high"],
        "positive_date_count": ci["positive_count"],
        "negative_date_count": ci["negative_count"],
        "tie_date_count": ci["tie_count"],
        "positive_edge_survives_ci": survives,
    }


def _paired_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    strategy_id: str,
    side: str,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    index = {(row["target_date"], row["strategy_id"], row["side"]): row for row in rows}
    dates = sorted({row["target_date"] for row in rows})
    paired_rows = []
    for target_date in dates:
        variant = index.get((target_date, strategy_id, side))
        control = index.get((target_date, CONTROL_STRATEGY_ID, side))
        if variant is None or control is None:
            continue
        variant_net = float(variant.get("net_after_modeled_costs_usdc") or 0.0)
        control_net = float(control.get("net_after_modeled_costs_usdc") or 0.0)
        paired_rows.append({
            "target_date": target_date,
            "strategy_id": strategy_id,
            "control_strategy_id": CONTROL_STRATEGY_ID,
            "side": side,
            "variant_net_usdc": _round(variant_net),
            "control_net_usdc": _round(control_net),
            "delta_net_usdc": _round(variant_net - control_net),
        })
    values = [float(row["delta_net_usdc"]) for row in paired_rows]
    ci = bootstrap_mean_ci(values, seed=seed, replicates=replicates)
    return {
        "strategy_id": strategy_id,
        "control_strategy_id": CONTROL_STRATEGY_ID,
        "side": side,
        "paired_date_count": len(paired_rows),
        "equal_fleet_date_mean_delta_net_usdc": ci["mean"],
        "fleet_date_bootstrap_ci_low_usdc": ci["ci_low"],
        "fleet_date_bootstrap_ci_high_usdc": ci["ci_high"],
        "positive_delta_date_count": ci["positive_count"],
        "negative_delta_date_count": ci["negative_count"],
        "tie_delta_date_count": ci["tie_count"],
        "beats_control_with_ci": bool(
            values and (ci["mean"] or 0.0) > 0 and (ci["ci_low"] or 0.0) > 0
        ),
        "daily_deltas": paired_rows,
    }


def _side_symmetry_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    strategy_id: str,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    index = {(row["target_date"], row["strategy_id"], row["side"]): row for row in rows}
    dates = sorted({row["target_date"] for row in rows})
    deltas = []
    for target_date in dates:
        yes = index.get((target_date, strategy_id, "YES"))
        no = index.get((target_date, strategy_id, "NO"))
        if yes is None or no is None:
            continue
        deltas.append(
            float(no.get("net_after_modeled_costs_usdc") or 0.0)
            - float(yes.get("net_after_modeled_costs_usdc") or 0.0)
        )
    ci = bootstrap_mean_ci(deltas, seed=seed, replicates=replicates)
    yes_rows = [row for row in rows if row["strategy_id"] == strategy_id and row["side"] == "YES"]
    no_rows = [row for row in rows if row["strategy_id"] == strategy_id and row["side"] == "NO"]
    return {
        "strategy_id": strategy_id,
        "comparison": "NO minus YES net by fleet date",
        "yes": _sum_rows(yes_rows),
        "no": _sum_rows(no_rows),
        "equal_fleet_date_mean_no_minus_yes_net_usdc": ci["mean"],
        "fleet_date_bootstrap_ci_low_usdc": ci["ci_low"],
        "fleet_date_bootstrap_ci_high_usdc": ci["ci_high"],
        "positive_delta_date_count": ci["positive_count"],
        "negative_delta_date_count": ci["negative_count"],
        "tie_delta_date_count": ci["tie_count"],
    }


def _population_summary(
    rows: Sequence[Mapping[str, Any]],
    strategies: Sequence[str],
    *,
    population_id: str,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    own = []
    paired = []
    for strategy_id in strategies:
        for side in SIDE_VALUES:
            own.append(_own_summary(
                rows,
                strategy_id=strategy_id,
                side=side,
                seed=_stable_seed(population_id, "own", strategy_id, side, seed=seed),
                replicates=replicates,
            ))
            if strategy_id != CONTROL_STRATEGY_ID:
                paired.append(_paired_summary(
                    rows,
                    strategy_id=strategy_id,
                    side=side,
                    seed=_stable_seed(population_id, "paired", strategy_id, side, seed=seed),
                    replicates=replicates,
                ))
    symmetry = [
        _side_symmetry_summary(
            rows,
            strategy_id=strategy_id,
            seed=_stable_seed(population_id, "symmetry", strategy_id, seed=seed),
            replicates=replicates,
        )
        for strategy_id in strategies
    ]
    return {
        "population_id": population_id,
        "date_count": len({row["target_date"] for row in rows}),
        "dates": sorted({row["target_date"] for row in rows}),
        "strategy_side_summaries": own,
        "paired_vs_control": paired,
        "yes_no_symmetry": symmetry,
    }


def build_aggregate(
    manifest: Mapping[str, Any],
    audit: Mapping[str, Any],
    day_summaries: Sequence[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Build primary, sensitivity, temporal, and missingness evidence."""

    strategies = list(manifest["strategies"])
    run_index, label_index = _audit_indexes(audit)
    day_index = {row.get("target_date"): row for row in day_summaries}
    support = []
    all_market_rows = []
    all_daily_rows = []
    all_filled_rows = []
    filled_row_overflow_count = 0
    for run_row in manifest.get("run_folders") or []:
        target_date = run_row["target_date"]
        run_audit = run_index.get(target_date) or {}
        labels = label_index.get(target_date) or {}
        day = day_index.get(target_date) or {}
        replay_ok = day.get("status", "ok") == "ok" and bool(day.get("daily_strategy_rows"))
        primary = bool(
            replay_ok
            and run_audit.get("primary_input_eligible")
            and labels.get("fully_settled_countable_fleet")
        )
        reasons = []
        if not replay_ok:
            reasons.append("replay_missing_or_failed")
        if not run_audit.get("primary_input_eligible"):
            reasons.append("input_market_fleet_incomplete")
        if not labels.get("fully_settled_countable_fleet"):
            reasons.append("labels_not_fully_settled_countable")
        support.append({
            "target_date": target_date,
            "run_folder": run_row["run_folder"],
            "run_audit_status": run_audit.get("status") or "MISSING",
            "replay_status": day.get("status") or ("ok" if replay_ok else "missing"),
            "input_market_count": run_audit.get("observed_market_count", 0),
            "expected_market_count": len(manifest["expected_market_ids"]),
            "capture_span_minutes": run_audit.get("capture_span_minutes"),
            "labels_fully_settled_countable": bool(labels.get("fully_settled_countable_fleet")),
            "primary_eligible": primary,
            "exclusion_reasons": reasons,
        })
        if replay_ok:
            all_filled_rows.extend(day.get("filled_order_rows") or [])
            filled_row_overflow_count += int(day.get("filled_order_row_overflow_count") or 0)
            for row in day.get("market_day_rows") or []:
                all_market_rows.append({**row, "primary_eligible": primary})
            for row in day.get("daily_strategy_rows") or []:
                all_daily_rows.append({**row, "primary_eligible": primary})

    primary_dates = {row["target_date"] for row in support if row["primary_eligible"]}
    primary_rows = [row for row in all_daily_rows if row["target_date"] in primary_dates]
    primary = _population_summary(
        primary_rows,
        strategies,
        population_id="primary_complete_fleet_and_labels",
        seed=seed,
        replicates=replicates,
    )
    high_coverage_dates = {
        row["target_date"] for row in support
        if row["primary_eligible"]
        and (maybe_float(row.get("capture_span_minutes")) or 0.0) >= MIN_HIGH_COVERAGE_SPAN_MINUTES
    }
    high_coverage_rows = [row for row in primary_rows if row["target_date"] in high_coverage_dates]
    high_coverage = _population_summary(
        high_coverage_rows,
        strategies,
        population_id=f"sensitivity_capture_span_at_least_{MIN_HIGH_COVERAGE_SPAN_MINUTES}_minutes",
        seed=seed,
        replicates=replicates,
    )
    moderate_coverage_dates = {
        row["target_date"] for row in support
        if row["primary_eligible"]
        and (maybe_float(row.get("capture_span_minutes")) or 0.0)
        >= MIN_MODERATE_COVERAGE_SPAN_MINUTES
    }
    moderate_coverage = _population_summary(
        [row for row in primary_rows if row["target_date"] in moderate_coverage_dates],
        strategies,
        population_id=(
            f"diagnostic_capture_span_at_least_{MIN_MODERATE_COVERAGE_SPAN_MINUTES}_minutes"
        ),
        seed=seed,
        replicates=replicates,
    )

    ordered_primary_dates = sorted(primary_dates)
    split_index = max(1, math.ceil(len(ordered_primary_dates) * 0.6)) if ordered_primary_dates else 0
    development_dates = set(ordered_primary_dates[:split_index])
    confirmation_dates = set(ordered_primary_dates[split_index:])
    temporal = {
        "rule": "chronological 60/40 robustness split; strategies were preregistered and no tuning used either segment",
        "development": _population_summary(
            [row for row in primary_rows if row["target_date"] in development_dates],
            strategies,
            population_id="chronological_first_60_percent",
            seed=seed,
            replicates=replicates,
        ),
        "confirmation": _population_summary(
            [row for row in primary_rows if row["target_date"] in confirmation_dates],
            strategies,
            population_id="chronological_last_40_percent",
            seed=seed,
            replicates=replicates,
        ),
    }
    positive_survivors = [
        row for row in primary["strategy_side_summaries"]
        if row["side"] == "ALL" and row["positive_edge_survives_ci"]
    ]
    paired_winners = [
        row for row in primary["paired_vs_control"]
        if row["side"] == "ALL" and row["beats_control_with_ci"]
    ]
    economics_statuses = sorted({
        str((row.get("exchange_economics_gate") or {}).get("status") or "MISSING")
        for row in day_summaries
        if row.get("daily_strategy_rows")
    })
    decision = (
        "FOLLOW_UP_CANDIDATE_SURVIVED_FIXED_POLICY_REPLAY"
        if positive_survivors
        else "STOP_NO_POSITIVE_AFTER_COST_EDGE_SURVIVED"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "aggregate",
        "generated_at_utc": utc_now().isoformat(),
        "manifest_hash": manifest.get("manifest_hash"),
        "research_only": True,
        "permission_fence_disabled_for_counterfactual_learning": True,
        "exchange_economics_gate_statuses": economics_statuses,
        "exchange_economics_limitation": (
            "Economics evidence is evaluated at actual run time. Any stale or blocked status "
            "keeps every result research-only even though fixed modeled costs are applied."
        ),
        "bootstrap": {
            "unit": "whole fleet date",
            "seed": int(seed),
            "replicates": int(replicates),
            "interval": "deterministic percentile 95%",
        },
        "funnel_definitions": {
            "evaluated_rows": "all generated strategy-band rows scored against labels",
            "priced_rows": "YES best_ask or NO no_best_ask is numeric",
            "positive_raw_edge_rows": "row edge is strictly positive",
            "positive_after_cost_ev_rows": "after_cost_ev_per_share is strictly positive",
            "buy_action_rows": "action equals BUY",
            "filled_rows": "paper order_status equals FILLED",
            "settled_filled_rows": "filled row pnl_source is settlement or settlement_finalized",
            "net_after_modeled_costs_usdc": "sum of settlement-scored net_pnl_usdc after fee and slippage",
        },
        "support": support,
        "summary": {
            "frozen_run_count": len(manifest.get("run_folders") or []),
            "replayed_run_count": len({row["target_date"] for row in all_daily_rows}),
            "primary_date_count": len(primary_dates),
            "primary_dates": sorted(primary_dates),
            "excluded_date_count": len(support) - len(primary_dates),
            "high_coverage_primary_date_count": len(high_coverage_dates),
            "moderate_coverage_primary_date_count": len(moderate_coverage_dates),
            "positive_after_cost_survivor_count": len(positive_survivors),
            "paired_control_winner_count": len(paired_winners),
            "decision": decision,
            "threshold_or_sizing_sweep_authorized": bool(positive_survivors),
        },
        "positive_after_cost_survivors": positive_survivors,
        "paired_control_winners": paired_winners,
        "primary": primary,
        "moderate_capture_coverage_diagnostic": moderate_coverage,
        "high_capture_coverage_sensitivity": high_coverage,
        "temporal_robustness": temporal,
        "filled_order_rows": all_filled_rows,
        "filled_order_row_overflow_count": filled_row_overflow_count,
        "market_day_rows": all_market_rows,
        "daily_strategy_rows": all_daily_rows,
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, bool)):
        return str(value)
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def render_aggregate_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") or {}
    primary = payload.get("primary") or {}
    lines = [
        "# Workstation taker bakeoff",
        "",
        f"**Outcome: {summary.get('decision', 'UNKNOWN')}.**",
        "",
        (
            f"The frozen corpus contains {summary.get('frozen_run_count', 0)} run folders; "
            f"{summary.get('primary_date_count', 0)} fleet dates met complete-input and "
            "fully settled/countable label requirements. The permission fence was disabled "
            "only for offline counterfactual learning."
        ),
        "",
        "## Primary equal-fleet-date results",
        "",
        "| Strategy | Side | Dates | Fills | Net USDC | Mean/day | 95% CI | +/-/= days |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in primary.get("strategy_side_summaries") or []:
        lines.append(
            "| {strategy_id} | {side} | {date_count} | {settled_filled_rows} | {net} | "
            "{mean} | [{low}, {high}] | {positive_date_count}/{negative_date_count}/{tie_date_count} |".format(
                net=_fmt(row.get("net_after_modeled_costs_usdc")),
                mean=_fmt(row.get("equal_fleet_date_mean_net_usdc")),
                low=_fmt(row.get("fleet_date_bootstrap_ci_low_usdc")),
                high=_fmt(row.get("fleet_date_bootstrap_ci_high_usdc")),
                **row,
            )
        )
    lines.extend([
        "",
        "## Paired variants versus control",
        "",
        "| Strategy | Side | Dates | Mean delta/day | 95% CI | +/-/= days |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ])
    for row in primary.get("paired_vs_control") or []:
        lines.append(
            "| {strategy_id} | {side} | {paired_date_count} | {mean} | [{low}, {high}] | "
            "{positive_delta_date_count}/{negative_delta_date_count}/{tie_delta_date_count} |".format(
                mean=_fmt(row.get("equal_fleet_date_mean_delta_net_usdc")),
                low=_fmt(row.get("fleet_date_bootstrap_ci_low_usdc")),
                high=_fmt(row.get("fleet_date_bootstrap_ci_high_usdc")),
                **row,
            )
        )
    lines.extend([
        "",
        "## YES/NO opportunity funnel",
        "",
        "| Strategy | Side | Evaluated | Priced | Raw edge > 0 | After-cost EV > 0 | Fills | Net USDC |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in primary.get("strategy_side_summaries") or []:
        if row.get("side") not in {"YES", "NO"}:
            continue
        lines.append(
            "| {strategy_id} | {side} | {evaluated_rows} | {priced_rows} | "
            "{positive_raw_edge_rows} | {positive_after_cost_ev_rows} | "
            "{settled_filled_rows} | {net} |".format(
                net=_fmt(row.get("net_after_modeled_costs_usdc")),
                **row,
            )
        )
    lines.extend([
        "",
        "## Date support and missingness",
        "",
        "| Date | Audit | Replay | Markets | Span min | Labels complete/countable | Primary | Exclusion |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ])
    for row in payload.get("support") or []:
        lines.append(
            "| {target_date} | {run_audit_status} | {replay_status} | {input_market_count}/{expected_market_count} | "
            "{span} | {labels} | {primary} | {reason} |".format(
                span=_fmt(row.get("capture_span_minutes"), 1),
                labels="yes" if row.get("labels_fully_settled_countable") else "no",
                primary="yes" if row.get("primary_eligible") else "no",
                reason=", ".join(row.get("exclusion_reasons") or []) or "-",
                **row,
            )
        )
    lines.extend([
        "",
        "## Interpretation constraints",
        "",
        f"- Exchange-economics gate statuses: {', '.join(payload.get('exchange_economics_gate_statuses') or []) or 'none'}.",
        f"- Bootstrap unit is the whole fleet date ({(payload.get('bootstrap') or {}).get('replicates')} deterministic replicates).",
        "- The chronological split is a robustness check, not a tuning/confirmation reuse; all arms were preregistered.",
        "- No production policy, release, promotion, credential, or live action is changed by this report.",
        (
            "- A threshold/sizing sweep is authorized only if a fixed-policy strategy has positive "
            "mean after-cost net and a strictly positive 95% fleet-date CI."
        ),
        "",
    ])
    return "\n".join(lines)


def write_aggregate_outputs(
    payload: Mapping[str, Any],
    *,
    out_root: str | Path,
    read_only_data_root: str | Path,
) -> None:
    out_root = _require_safe_output(out_root, read_only_data_root=read_only_data_root)
    write_json_atomic(out_root / "aggregate.json", payload, trailing_newline=True)
    write_text_atomic(out_root / "aggregate.md", render_aggregate_markdown(payload))
    market_rows = []
    for row in payload.get("market_day_rows") or []:
        market_rows.append({
            **row,
            "reason_counts_json": json.dumps(row.get("reason_counts") or {}, sort_keys=True),
        })
    write_csv_rows_atomic(out_root / "market_day_rows.csv", MARKET_DAY_CSV_COLUMNS, market_rows)
    write_csv_rows_atomic(
        out_root / "daily_strategy_rows.csv",
        DAILY_CSV_COLUMNS,
        payload.get("daily_strategy_rows") or [],
    )
    write_csv_rows_atomic(
        out_root / "filled_order_casebook.csv",
        FILLED_CASE_CSV_COLUMNS,
        payload.get("filled_order_rows") or [],
    )
    paired_rows = []
    for row in (payload.get("primary") or {}).get("paired_vs_control") or []:
        paired_rows.extend(row.get("daily_deltas") or [])
    write_csv_rows_atomic(
        out_root / "paired_fleet_date_deltas.csv",
        (
            "target_date",
            "strategy_id",
            "control_strategy_id",
            "side",
            "variant_net_usdc",
            "control_net_usdc",
            "delta_net_usdc",
        ),
        paired_rows,
    )


def aggregate_from_disk(
    manifest: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    out_root: str | Path,
    read_only_data_root: str | Path,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    out_root = _require_safe_output(out_root, read_only_data_root=read_only_data_root)
    _verify_shared_inputs_unchanged(manifest, audit)
    day_summaries = []
    for run_row in manifest.get("run_folders") or []:
        day_path = out_root / "days" / run_row["target_date"] / "day_summary.json"
        payload = read_json(day_path, {}) or {}
        if _day_summary_matches(payload, manifest, run_row):
            payload.setdefault("status", "ok")
            day_summaries.append(payload)
        else:
            day_summaries.append({
                "target_date": run_row["target_date"],
                "run_folder": run_row["run_folder"],
                "status": "missing_or_stale",
            })
    aggregate = build_aggregate(
        manifest,
        audit,
        day_summaries,
        seed=seed,
        replicates=replicates,
    )
    write_aggregate_outputs(
        aggregate,
        out_root=out_root,
        read_only_data_root=read_only_data_root,
    )
    return aggregate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze", help="write an explicit immutable input manifest")
    freeze.add_argument("--read-only-data-root", required=True)
    freeze.add_argument("--manifest", required=True)
    freeze.add_argument("--labels-csv", required=True)
    freeze.add_argument("--exchange-economics-snapshot", required=True)
    freeze.add_argument("--latest-label-date", required=True)
    freeze.add_argument("--run-folder", action="append", required=True)
    freeze.add_argument("--strategies", default=",".join(ALL_STRATEGIES))
    freeze.add_argument("--provenance", default="read-only workstation mirror")

    for command in ("audit", "run", "aggregate"):
        child = subparsers.add_parser(command)
        child.add_argument("--read-only-data-root", required=True)
        child.add_argument("--manifest", required=True)
        child.add_argument("--out-root", required=True)
    run_parser = subparsers.choices["run"]
    run_parser.add_argument("--no-resume", action="store_true")
    run_parser.add_argument("--max-days", type=int, default=0)
    aggregate_parser = subparsers.choices["aggregate"]
    aggregate_parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    aggregate_parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)

    args = parser.parse_args(argv)
    if args.command == "freeze":
        manifest_path = _require_safe_output(
            args.manifest, read_only_data_root=args.read_only_data_root
        )
        manifest = create_frozen_manifest(
            args.run_folder,
            labels_csv=args.labels_csv,
            exchange_economics_snapshot_path=args.exchange_economics_snapshot,
            latest_label_date=args.latest_label_date,
            strategies=args.strategies,
            provenance=args.provenance,
        )
        write_json_atomic(manifest_path, manifest, trailing_newline=True)
        print(f"frozen {len(manifest['run_folders'])} explicit runs: {manifest_path}")
        return 0

    manifest = load_manifest(args.manifest)
    out_root = _require_safe_output(
        args.out_root, read_only_data_root=args.read_only_data_root
    )
    if args.command == "audit":
        audit = audit_manifest(
            manifest,
            out_root=out_root,
            read_only_data_root=args.read_only_data_root,
        )
        print(json.dumps(audit["summary"], sort_keys=True))
        return 0 if audit["status"] == "PASS" else 1
    audit_path = out_root / "input_audit.json"
    audit = read_json(audit_path, {}) or {}
    if audit.get("manifest_hash") != manifest.get("manifest_hash"):
        raise SystemExit(f"missing or stale audit; run the audit command first: {audit_path}")
    if args.command == "run":
        results = run_replays(
            manifest,
            audit,
            out_root=out_root,
            read_only_data_root=args.read_only_data_root,
            resume=not args.no_resume,
            max_days=args.max_days,
        )
        errors = sum(int(row.get("status") == "error") for row in results)
        return 1 if errors else 0
    aggregate = aggregate_from_disk(
        manifest,
        audit,
        out_root=out_root,
        read_only_data_root=args.read_only_data_root,
        seed=args.bootstrap_seed,
        replicates=args.bootstrap_replicates,
    )
    print(json.dumps(aggregate["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
