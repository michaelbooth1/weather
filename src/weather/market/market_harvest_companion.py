"""Forward-only paper companion for International market-harvest evidence.

The companion consumes objects already loaded by the ordinary market-making
tick.  It owns a distinct artifact family and never grants live permission or
contributes evidence to the model/promotion lane.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

from weather.io import (
    append_csv_rows,
    append_jsonl,
    write_csv_rows_atomic,
    write_json_atomic,
)
from weather.market.market_making_run_constants import SCHEMA_VERSION as RUN_SCHEMA_VERSION
from weather.market.market_making_run_support import (
    apply_run_budget,
    lifecycle_fill_transition,
)
from weather.market.mm_scoring_projection import SCORING_COLUMNS
from weather.market.mm_paper_constants import FILL_COLUMNS
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_harvest_paper_companion")
ARTIFACT_DIRECTORY = "market_harvest_companion"
PLATFORM_ID = "polymarket_global"
EVIDENCE_MODE = "market_harvest_forward_only_paper"
DEFAULT_REPORT_NAME = "market_harvest_companion_report.json"
DEFAULT_REPORT_MD_NAME = "market_harvest_companion_report.md"
DEFAULT_FILLS_NAME = "market_harvest_companion_simulated_fills.csv"
DEFAULT_QUEUE_NAME = "market_harvest_companion_queue.csv"

COMPANION_COLUMNS = tuple(SCORING_COLUMNS) + (
    "companion_schema_version",
    "evidence_class",
    "evidence_surface",
    "platform_id",
    "parent_run_id",
    "policy_opportunity",
    "condition_id",
    "snapshot_id",
    "book_capture_ids",
    "book_captured_at_utc",
    "book_rows_sha256",
    "token_rows_sha256",
    "source_status_rows_sha256",
    "source_hashes_sha256",
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
    "quote_ttl_seconds",
    "authenticated_fill",
    "realized_pnl_eligible",
)


def _canonical_hash(value):
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _source_hashes(rows):
    values = []
    for row in rows or []:
        for key, value in row.items():
            if "hash" in str(key).lower() and value not in (None, ""):
                values.append({"field": str(key), "value": str(value)})
    return sorted(values, key=lambda item: (item["field"], item["value"]))


def input_binding(book_rows, token_rows, source_rows, exchange_economics_fields):
    """Bind a companion decision to the exact already-loaded public inputs."""

    capture_ids = sorted({
        str(row.get("capture_id") or row.get("snapshot_id") or "")
        for row in book_rows or []
        if row.get("capture_id") or row.get("snapshot_id")
    })
    captured_times = sorted({
        str(row.get("captured_at_utc") or row.get("book_time_utc") or "")
        for row in book_rows or []
        if row.get("captured_at_utc") or row.get("book_time_utc")
    })
    source_hashes = _source_hashes(source_rows)
    economics = {
        key: exchange_economics_fields.get(key)
        for key in (
            "exchange_economics_snapshot_id",
            "exchange_economics_hash",
            "exchange_economics_evidence_basis",
        )
    }
    return {
        "book_capture_ids": capture_ids,
        "book_captured_at_utc": captured_times,
        "book_rows_sha256": _canonical_hash(book_rows or []),
        "token_rows_sha256": _canonical_hash(token_rows or []),
        "source_status_rows_sha256": _canonical_hash(source_rows or []),
        "source_hashes": source_hashes,
        "source_hashes_sha256": _canonical_hash(source_hashes),
        **economics,
    }


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _state_after_events(previous_open_orders, events):
    open_orders = dict(previous_open_orders or {})
    for event in events:
        key = event.get("lifecycle_key")
        transition = event.get("transition")
        if not key:
            continue
        if transition == "paper_posted":
            open_orders[key] = dict(event)
        elif transition == "filled" and key in open_orders:
            updated = lifecycle_fill_transition(open_orders[key], event)
            if updated is None:
                open_orders.pop(key, None)
            else:
                open_orders[key] = updated
        elif transition in {"canceled", "expired", "replaced", "released", "blocked_by_preflight"}:
            open_orders.pop(key, None)
    return open_orders


def _tick_id(parent_run_id, now, rows, bindings):
    return _canonical_hash({
        "parent_run_id": parent_run_id,
        "generated_at_utc": now.isoformat(),
        "policy_hashes": sorted({str(row.get("policy_hash") or "") for row in rows}),
        "markets": bindings,
    })


def _binding_columns(binding):
    return {
        "book_capture_ids": ";".join(binding.get("book_capture_ids") or []),
        "book_captured_at_utc": ";".join(binding.get("book_captured_at_utc") or []),
        "book_rows_sha256": binding.get("book_rows_sha256"),
        "token_rows_sha256": binding.get("token_rows_sha256"),
        "source_status_rows_sha256": binding.get("source_status_rows_sha256"),
        "source_hashes_sha256": binding.get("source_hashes_sha256"),
        "exchange_economics_snapshot_id": binding.get("exchange_economics_snapshot_id"),
        "exchange_economics_hash": binding.get("exchange_economics_hash"),
        "exchange_economics_evidence_basis": binding.get("exchange_economics_evidence_basis"),
    }


def _ensure_economics_capture(parent_run_folder, folder, capture):
    capture = dict(capture or {})
    if capture.get("captured") is not True:
        return capture
    source = Path(parent_run_folder) / "exchange_economics_snapshot.json"
    destination = Path(folder) / "exchange_economics_snapshot.json"
    if not source.is_file():
        raise FileNotFoundError(source)
    if not destination.exists():
        try:
            os.link(source, destination)
        except OSError:
            temporary = destination.with_name(
                f"{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
            )
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(destination)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
    observed = hashlib.sha256(destination.read_bytes()).hexdigest()
    if observed != capture.get("file_sha256"):
        raise RuntimeError("companion exchange-economics capture hash mismatch")
    return {**capture, "path": str(destination)}


def write_tick(
    parent_run_folder,
    parent_run_id,
    target_date,
    mode,
    budget_usdc,
    now,
    raw_rows,
    preflight_rows,
    input_bindings,
    policy_config,
    *,
    exchange_economics_capture=None,
    append=False,
):
    """Publish one idempotent companion tick beneath the parent run folder."""

    if mode not in {"shadow", "paper-live-forward"}:
        raise ValueError("market-harvest companion is paper-only")
    folder = Path(parent_run_folder) / ARTIFACT_DIRECTORY
    folder.mkdir(parents=True, exist_ok=True)
    companion_economics_capture = _ensure_economics_capture(
        parent_run_folder,
        folder,
        exchange_economics_capture,
    )
    state_path = folder / "companion_state.json"
    state = _read_json(state_path, {}) if append else {}
    processed = list(state.get("processed_tick_ids") or [])
    tick_id = _tick_id(parent_run_id, now, raw_rows, input_bindings)
    if tick_id in processed:
        summary = _read_json(folder / "run_summary.json", {})
        return {**summary, "status": "DUPLICATE_SKIPPED", "tick_id": tick_id}

    companion_run_id = f"{parent_run_id}--market-harvest"
    ttl = float(policy_config.get("quote_ttl_seconds") or 120.0)
    companion_budget = min(
        float(budget_usdc),
        float(policy_config.get("max_daily_loss") or budget_usdc),
    )
    preflight_by_market = {row["market_id"]: row for row in preflight_rows}
    annotated_raw_rows = [
        {**row, "policy_opportunity": bool(row.get("quote_permission"))}
        for row in raw_rows
    ]
    quote_rows, ledger, _risks, lifecycle_events, lifecycle = apply_run_budget(
        annotated_raw_rows,
        companion_budget,
        companion_run_id,
        target_date,
        mode,
        now,
        preflight_by_market,
        previous_open_orders=state.get("open_orders") or {},
        quote_ttl_seconds=ttl,
    )
    for row in quote_rows:
        binding = input_bindings.get(row.get("market_id") or "", {})
        row.update({
            "companion_schema_version": SCHEMA_VERSION,
            "evidence_class": "quote_opportunity",
            "evidence_surface": "public_market_data_counterfactual",
            "platform_id": PLATFORM_ID,
            "parent_run_id": parent_run_id,
            "authenticated_fill": False,
            "realized_pnl_eligible": False,
            **_binding_columns(binding),
        })
        row["live_trade_permission"] = False
    if any(row.get("live_trade_permission") for row in quote_rows):
        raise RuntimeError("market-harvest companion attempted to grant live permission")
    persisted_quote_rows = [row for row in quote_rows if row.get("quote_permission")]

    lifecycle_rows = []
    for event in lifecycle_events:
        if event.get("transition") == "blocked_by_budget":
            continue
        lifecycle_rows.append({
            **event,
            "companion_schema_version": SCHEMA_VERSION,
            "evidence_class": "simulated_lifecycle",
            "evidence_surface": "paper_counterfactual",
            "platform_id": PLATFORM_ID,
            "parent_run_id": parent_run_id,
            "authenticated_fill": False,
            "realized_pnl_eligible": False,
        })

    quote_path = folder / "quote_intents_long.csv"
    model_variant_path = folder / "model_variant_quote_intents_long.csv"
    if append and quote_path.exists():
        append_csv_rows(quote_path, COMPANION_COLUMNS, persisted_quote_rows)
    else:
        write_csv_rows_atomic(quote_path, COMPANION_COLUMNS, persisted_quote_rows)
        write_csv_rows_atomic(model_variant_path, COMPANION_COLUMNS, [])
    append_jsonl(folder / "order_lifecycle.jsonl", lifecycle_rows)
    retained_ledger = [
        row for row in ledger if row.get("event") != "budget_exhausted"
    ]
    append_jsonl(folder / "budget_ledger.jsonl", retained_ledger)

    cumulative = Counter(state.get("cumulative_counts") or {})
    cumulative.update({
        "ticks": 1,
        "opportunities": sum(bool(row.get("policy_opportunity")) for row in quote_rows),
        "simulated_posted_quotes": sum(bool(row.get("quote_permission")) for row in quote_rows),
        "coverage_gaps": sum(not bool(row.get("quote_permission")) for row in quote_rows),
        "simulated_posted_legs": sum(
            event.get("transition") == "paper_posted" for event in lifecycle_rows
        ),
    })
    open_orders = _state_after_events(state.get("open_orders") or {}, lifecycle_events)
    processed.append(tick_id)
    processed = processed[-2048:]
    next_state = {
        "schema_version": SCHEMA_VERSION,
        "parent_run_id": parent_run_id,
        "processed_tick_ids": processed,
        "open_orders": open_orders,
        "cumulative_counts": dict(cumulative),
    }
    write_json_atomic(state_path, next_state)

    run_config = {
        "schema_version": RUN_SCHEMA_VERSION,
        "companion_schema_version": SCHEMA_VERSION,
        "run_id": companion_run_id,
        "parent_run_id": parent_run_id,
        "target_date": str(target_date),
        "mode": mode,
        "permission_profile": "market_harvest",
        "platform_id": PLATFORM_ID,
        "evidence_mode": EVIDENCE_MODE,
        "policy_config": policy_config,
        "quote_ttl_seconds": ttl,
        "run_budget_usdc": companion_budget,
        "input_bindings_by_market": input_bindings,
        "exchange_economics_capture": companion_economics_capture,
        "live_trade_permission_allowed": False,
        "authenticated_execution_evidence": False,
        "realized_pnl_eligible": False,
    }
    write_json_atomic(folder / "run_config.json", run_config)
    live_gate = {
        "schema_version": SCHEMA_VERSION,
        "status": "PAPER_ONLY",
        "counts_toward_live_forward_gate": False,
        "live_trade_permission": False,
        "reason": "market-harvest companion is isolated counterfactual paper evidence",
    }
    write_json_atomic(folder / "live_forward_gate.json", live_gate)
    summary = {
        "schema_version": RUN_SCHEMA_VERSION,
        "companion_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "run_id": companion_run_id,
        "parent_run_id": parent_run_id,
        "target_date": str(target_date),
        "mode": mode,
        "generated_at_utc": now.isoformat(),
        "evidence_mode": EVIDENCE_MODE,
        "artifact_family": ARTIFACT_DIRECTORY,
        "run_folder": str(folder),
        "tick_id": tick_id,
        "latest_tick": {
            "opportunities": sum(bool(row.get("policy_opportunity")) for row in quote_rows),
            "simulated_posted_quotes": sum(bool(row.get("quote_permission")) for row in quote_rows),
            "coverage_gaps": sum(not bool(row.get("quote_permission")) for row in quote_rows),
            "simulated_posted_legs": sum(
                event.get("transition") == "paper_posted" for event in lifecycle_rows
            ),
            "reason_counts": dict(sorted(Counter(
                str(row.get("reason_code") or "unknown") for row in quote_rows
            ).items())),
            "preflight_status_counts": dict(sorted(Counter(
                str(row.get("status") or "UNKNOWN") for row in preflight_rows
            ).items())),
        },
        "cumulative": dict(cumulative),
        "open_order_count": lifecycle.get("current_open_order_count", 0),
        "budget_reserved_usdc": lifecycle.get("current_reserved_usdc", 0.0),
        "quote_intents_path": str(quote_path),
        "order_lifecycle_path": str(folder / "order_lifecycle.jsonl"),
        "run_config_path": str(folder / "run_config.json"),
        "live_forward_gate": live_gate,
        "counts_toward_live_forward_gate": False,
        "live_trade_permission_rows": 0,
        "authenticated_fill_count": 0,
        "realized_pnl_count": 0,
    }
    write_json_atomic(folder / "run_summary.json", summary)
    return {**summary, "run_folder": str(folder)}


COMPANION_FILL_COLUMNS = tuple(FILL_COLUMNS) + (
    "companion_schema_version",
    "evidence_class",
    "public_execution_evidence_class",
    "evidence_surface",
    "platform_id",
    "configured_fee_equivalent_estimate_usdc",
    "configured_maker_rebate_estimate_usdc",
    "configured_liquidity_reward_estimate_usdc",
    "authoritative_fee_usdc",
    "authoritative_rebate_usdc",
    "authoritative_incentive_usdc",
    "simulated_settlement_pnl_usdc",
    "simulated_net_pnl_after_fees_incentives_usdc",
    "authenticated_fill",
    "realized_pnl_eligible",
    "realized_pnl_usdc",
)

COMPANION_QUEUE_COLUMNS = (
    "companion_schema_version",
    "evidence_class",
    "evidence_surface",
    "platform_id",
    "leg_id",
    "status",
    "estimated_fill_size",
    "initial_queue_ahead",
    "depleted_ahead",
    "reason",
    "authenticated_fill",
    "realized_pnl_eligible",
)


def discover_run_folders(runs_root):
    root = Path(runs_root)
    if not root.exists():
        return []
    return sorted(
        path.parent
        for path in root.glob(f"*/*/{ARTIFACT_DIRECTORY}/quote_intents_long.csv")
        if path.is_file()
    )


def _companion_fill(row):
    out = dict(row)
    out.update({
        "companion_schema_version": SCHEMA_VERSION,
        "evidence_class": "simulated_fill",
        "public_execution_evidence_class": "public_trade",
        "evidence_surface": "strict_public_trade_through_counterfactual",
        "platform_id": PLATFORM_ID,
        "configured_fee_equivalent_estimate_usdc": row.get("maker_fee_equivalent_usdc") or 0.0,
        "configured_maker_rebate_estimate_usdc": row.get("maker_rebate_estimate_usdc") or 0.0,
        "configured_liquidity_reward_estimate_usdc": row.get("liquidity_reward_estimate_usdc") or 0.0,
        "authoritative_fee_usdc": 0.0,
        "authoritative_rebate_usdc": 0.0,
        "authoritative_incentive_usdc": 0.0,
        "simulated_settlement_pnl_usdc": row.get("settlement_pnl_usdc"),
        "simulated_net_pnl_after_fees_incentives_usdc": row.get(
            "net_pnl_after_fees_incentives_usdc"
        ),
        "maker_rebate_accepted_usdc": 0.0,
        "liquidity_reward_accepted_usdc": 0.0,
        "authenticated_fill": False,
        "realized_pnl_eligible": False,
        "realized_pnl_usdc": 0.0,
    })
    return out


def _companion_queue(row):
    return {
        **row,
        "companion_schema_version": SCHEMA_VERSION,
        "evidence_class": "simulated_queue",
        "evidence_surface": "public_book_queue_counterfactual",
        "platform_id": PLATFORM_ID,
        "authenticated_fill": False,
        "realized_pnl_eligible": False,
    }


def _render_score_report(payload):
    summary = payload["summary"]
    return "\n".join([
        "# International Market-Harvest Paper Companion",
        "",
        "This report is counterfactual paper evidence. It contains no authenticated fills, realized P&L, or live permission.",
        "",
        f"- Opportunities: `{summary['opportunities']}`",
        f"- Simulated posted quotes: `{summary['simulated_posted_quotes']}`",
        f"- Simulated posted legs: `{summary['simulated_posted_legs']}`",
        f"- Strict conservative fills: `{summary['conservative_fills']}`",
        f"- Unresolved legs: `{summary['unresolved_legs']}`",
        f"- Coverage gaps: `{summary['coverage_gaps']}`",
        f"- Countable market-days: `{summary['countable_market_days']}`",
        f"- Authenticated fills: `{summary['authenticated_fill_count']}`",
        f"- Realized-P&L rows: `{summary['realized_pnl_count']}`",
        "",
    ])


def score_runs(
    runs_root,
    snapshots_root,
    backtest_root,
    *,
    selected_run_folders=None,
    latest_n=14,
    now=None,
    casebook_path=None,
    ledger_root=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_target_date=None,
    exchange_economics_platform=PLATFORM_ID,
    exchange_economics_required=True,
    clob_recon_path=None,
):
    """Score only companion folders through the canonical strict paper scorer."""

    from weather.market import mm_paper

    folders = [Path(path) for path in (selected_run_folders or discover_run_folders(runs_root))]
    if latest_n is not None:
        folders = folders[-max(0, int(latest_n)):]
    if not folders:
        return {
            "status": "SKIPPED",
            "reason": "no_market_harvest_companion_runs",
            "selected_run_count": 0,
        }
    payload = mm_paper.build_paper_payload(
        runs_root=runs_root,
        snapshots_root=snapshots_root,
        backtest_root=backtest_root,
        selected_run_folders=folders,
        casebook_path=casebook_path or Path(backtest_root) / "disagreement_casebook.json",
        promotion_refresh=Path(backtest_root) / "f_family_promotion_refresh.json",
        now=now,
        ledger_root=ledger_root,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_target_date=exchange_economics_target_date,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
        clob_recon_path=clob_recon_path or Path(backtest_root) / "clob_book_recon.json",
        include_model_variants=False,
        stream_run_inputs=True,
        materialize_output_rows=True,
    )
    fills = [_companion_fill(row) for row in payload.get("fills") or []]
    queue = [_companion_queue(row) for row in payload.get("queue_companion") or []]
    strict_summary = payload.get("summary") or {}
    completeness = payload.get("fill_evidence_completeness") or {}
    companion_quote_rows = [
        row
        for folder in folders
        for row in _read_companion_rows(folder / "quote_intents_long.csv")
    ]
    quote_market_days = {
        (str(row.get("target_date") or ""), str(row.get("market_id") or ""))
        for row in companion_quote_rows
        if str(row.get("quote_permission") or "").lower() in {"true", "1", "yes"}
        and row.get("target_date")
        and row.get("market_id")
    }
    blockers = list(completeness.get("blockers") or [])
    unresolved = int(completeness.get("unresolved_resting_quote_count") or 0)
    coverage_gaps = (
        len(blockers)
        + int(completeness.get("missing_size_trade_rows") or 0)
        + int(completeness.get("rejected_execution_evidence_rows") or 0)
        + int(completeness.get("conflicting_execution_evidence_rows") or 0)
        + int(completeness.get("missing_book_queue_legs") or 0)
        + int(completeness.get("missing_trade_size_queue_legs") or 0)
    )
    fallback_opportunities = sum(
        str(
            row.get("policy_opportunity")
            if row.get("policy_opportunity") not in (None, "")
            else row.get("quote_permission")
        ).lower() in {"true", "1", "yes"}
        for row in companion_quote_rows
    )
    recorded_opportunities = sum(
        int(
            ((_read_json(folder / "run_summary.json", {}).get("cumulative") or {}).get(
                "opportunities"
            ) or 0)
        )
        for folder in folders
    )
    summary = {
        "opportunities": recorded_opportunities or fallback_opportunities,
        "simulated_posted_quotes": int(strict_summary.get("quote_permission_rows") or 0),
        "simulated_posted_legs": int(strict_summary.get("quote_legs") or 0),
        "conservative_fills": len(fills),
        "unresolved_legs": unresolved,
        "coverage_gaps": coverage_gaps,
        "countable_market_days": len(quote_market_days) if completeness.get("status") == "PASS" else 0,
        "queue_companion_legs": len(queue),
        "queue_estimated_fill_legs": int(strict_summary.get("queue_estimated_fill_legs") or 0),
        "fill_evidence_completeness_status": completeness.get("status"),
        "fill_evidence_blockers": blockers,
        "authenticated_fill_count": 0,
        "realized_pnl_count": 0,
        "live_trade_permission_rows": 0,
        "counts_toward_model_promotion": False,
        "counts_toward_live_forward_gate": False,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if completeness.get("status") == "PASS" else "BLOCK",
        "generated_at_utc": payload.get("generated_at_utc"),
        "platform_id": PLATFORM_ID,
        "evidence_mode": EVIDENCE_MODE,
        "selected_run_folders": [str(folder) for folder in folders],
        "summary": summary,
        "strict_scorer_schema_version": payload.get("schema_version"),
        "strict_fill_rule": "strict_trade_through_price_and_recorded_size",
        "fill_evidence_completeness": completeness,
        "event_diagnostics": payload.get("event_diagnostics") or {},
        "exchange_economics_gate": payload.get("exchange_economics_gate") or {},
        "authoritative_economics": {
            "fees_usdc": 0.0,
            "rebates_usdc": 0.0,
            "incentives_usdc": 0.0,
            "reason": "no authenticated account-level payout or fee evidence",
        },
    }
    out_root = Path(backtest_root)
    write_json_atomic(out_root / DEFAULT_REPORT_NAME, report)
    (out_root / DEFAULT_REPORT_MD_NAME).write_text(
        _render_score_report(report),
        encoding="utf-8",
    )
    write_csv_rows_atomic(out_root / DEFAULT_FILLS_NAME, COMPANION_FILL_COLUMNS, fills)
    write_csv_rows_atomic(out_root / DEFAULT_QUEUE_NAME, COMPANION_QUEUE_COLUMNS, queue)
    return {
        "status": report["status"],
        "selected_run_count": len(folders),
        "report_path": str(out_root / DEFAULT_REPORT_NAME),
        "report_markdown_path": str(out_root / DEFAULT_REPORT_MD_NAME),
        "fills_path": str(out_root / DEFAULT_FILLS_NAME),
        "queue_path": str(out_root / DEFAULT_QUEUE_NAME),
        "summary": summary,
    }


def _read_companion_rows(path):
    from weather.io import read_csv_rows

    return read_csv_rows(path)


__all__ = [
    "ARTIFACT_DIRECTORY",
    "COMPANION_COLUMNS",
    "EVIDENCE_MODE",
    "SCHEMA_VERSION",
    "input_binding",
    "discover_run_folders",
    "score_runs",
    "write_tick",
]
