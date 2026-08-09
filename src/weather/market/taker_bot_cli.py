"""Implementation slice extracted from src/weather/market/taker_bot.py."""

import json
import os
import time
import uuid
from collections import defaultdict

from weather.market.taker_bot_finalization import *  # noqa: F403
from weather.market import exchange_economics
from weather.market.taker_evidence_starvation import (
    build_taker_upstream_dependency_status,
    classify_taker_evidence_starvation,
)
from weather.operations import event_metadata_validation
from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
)
from weather.market.worker_release_binding import (
    WorkerReleaseBindingError,
    load_worker_release_binding,
    stamp_worker_release_lineage,
    verify_worker_snapshot_binding,
    worker_release_summary_fields,
    worker_tape_columns,
    worker_tape_summary_fields,
    verify_worker_csv_tape_for_append,
    verify_worker_tape_lineage,
)
from weather.runtime_identity import get_runtime_identity
from weather.market.market_latest_inputs import load_latest_market_inputs
from weather.market.taker_bot_incremental import (
    BENCHMARK_REFRESH_GROUP_LIMIT,
    DEFAULT_RESOURCE_BUDGETS,
    IncrementalTakerStore,
    process_resource_sample,
    resource_diagnostics,
)

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.


def _uses_default_snapshot_root(path):
    try:
        return Path(path).resolve() == Path(DEFAULT_SNAPSHOTS_ROOT).resolve()
    except OSError:
        return Path(path) == Path(DEFAULT_SNAPSHOTS_ROOT)


def _event_metadata_state(path, target_date, snapshots_root):
    explicit_path = path is not None
    path = Path(path or event_metadata_validation.DEFAULT_JSON_OUT)
    required = _uses_default_snapshot_root(snapshots_root) or explicit_path
    payload = event_metadata_validation.load_validation_payload(path) if required else None
    return {
        "required": required,
        "exists": payload is not None,
        "path": str(path),
        "target_date": ensure_date(target_date).isoformat(),
        "status": (payload or {}).get("status") if payload else ("missing" if required else "not_required"),
        "validation_hash": (payload or {}).get("validation_hash"),
        "payload": payload,
    }


def _event_metadata_gate(state, market_id):
    if not (state or {}).get("required"):
        return {"required": False, "ok": True, "reason": "not required for non-default snapshot root"}
    payload = (state or {}).get("payload")
    gate = event_metadata_validation.gate_for_market(payload, market_id)
    if payload and payload.get("target_date") != state.get("target_date"):
        gate = {
            **gate,
            "ok": False,
            "status": "BLOCK",
            "reason": (
                "event metadata validation target_date does not match taker run target_date: "
                f"{payload.get('target_date')} != {state.get('target_date')}"
            ),
            "remediation_command": event_metadata_validation.VALIDATION_COMMAND.replace(
                "<YYYY-MM-DD>",
                state.get("target_date") or "<YYYY-MM-DD>",
            ),
        }
    return gate


def _exchange_economics_gate_for_run(snapshot_path, target_date, platform, now, required=True):
    gate = exchange_economics.load_exchange_economics_gate(
        snapshot_path or exchange_economics.DEFAULT_SNAPSHOT,
        target_date,
        platform=platform,
        now=now,
        required=required,
    )
    return gate, exchange_economics.exchange_economics_artifact_fields(gate)


def _apply_exchange_economics_fields(rows, fields):
    for row in rows or []:
        row.update({
            "exchange_economics_snapshot_id": fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": fields.get("exchange_economics_evidence_basis"),
        })
    return rows


def _annotate_taker_pnl_with_exchange_economics(pnl_payload, gate, fields):
    pnl_payload = pnl_payload or {}
    pnl_payload["exchange_economics_gate"] = gate
    pnl_payload.update(fields)
    pnl_payload.setdefault("summary", {}).update({
        "exchange_economics_gate_status": gate.get("status"),
        "exchange_economics_gate_reason": gate.get("reason"),
        "promotion_evidence_basis": (
            "settlement_scored" if gate.get("ok") else exchange_economics.STALE_EVIDENCE_BASIS
        ),
        **fields,
    })
    for row in pnl_payload.get("by_strategy") or []:
        row.update({
            "exchange_economics_gate_status": gate.get("status"),
            **fields,
        })
    comparison = pnl_payload.get("strategy_comparison") or {}
    if comparison:
        comparison.update({
            "exchange_economics_gate_status": gate.get("status"),
            **fields,
        })
    return pnl_payload


def discover_inputs(
    target_date,
    markets=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    config=None,
    now=None,
    observation_status=None,
    event_metadata_state=None,
    release_binding=None,
):
    now = utc_now(now)
    config = {**DEFAULT_CONFIG, **(config or {})}
    rows = []
    market_summaries = []
    for spec in selected_specs(markets):
        market_config = config_for_date(target_date, spec.id)
        folder = Path(snapshots_root) / market_config.event_slug
        latest_inputs = load_latest_market_inputs(
            folder,
            market_id=spec.id,
            max_age_seconds=float(config["max_book_age_seconds"]),
        )
        snapshot_rows = latest_inputs["snapshot_rows"]
        if release_binding is not None:
            # Authenticate the immutable snapshot projection before CLOB/book
            # enrichment overwrites fields such as captured_at_utc with the
            # supporting evidence timestamp.
            verify_worker_snapshot_binding(
                folder,
                snapshot_rows,
                release_binding,
                market_id=spec.id,
                target_date=target_date,
            )
        current_high_assessment = current_high_probability_summary(
            snapshot_rows,
            normalized_high_for_market(observation_status, spec.id),
        )
        source_rows = latest_inputs["source_rows"]
        book_rows = latest_inputs["book_rows"]
        clob_feature_rows = latest_inputs["clob_feature_rows"]
        metadata_gate = _event_metadata_gate(event_metadata_state, spec.id)
        market_summaries.append(
            preflight_summary_for_market(
                spec,
                target_date,
                folder,
                snapshot_rows,
                source_rows,
                book_rows,
                clob_feature_rows,
                event_metadata_gate=metadata_gate,
                current_high_assessment=current_high_assessment,
                token_rows=latest_inputs["token_rows"],
                input_read_diagnostics=latest_inputs["diagnostics"],
            )
        )
        market_summaries[-1]["current_high_assessment"] = current_high_assessment
        bounded_projection_ok = bool(latest_inputs["diagnostics"]["projection"].get("ok"))
        if snapshot_rows and metadata_gate.get("ok", True) and bounded_projection_ok:
            rows.extend(
                assemble_taker_inputs_for_market(
                    spec.id,
                    folder,
                    snapshot_rows,
                    source_rows,
                    clob_feature_rows,
                    book_rows,
                    current_high_assessment=current_high_assessment,
                )
            )
    return rows, market_summaries


def build_run_config_payload(
    run_id,
    target_date,
    budget_usdc,
    markets,
    run_folder,
    snapshots_root,
    config,
    now,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
    experiment_id=DEFAULT_EXPERIMENT_ID,
    strategy_specs=None,
    registry=None,
    runtime_identity=None,
    event_metadata_state=None,
    exchange_economics_gate=None,
):
    strategy_specs = strategy_specs or selected_strategy_specs(None, base_config=config, registry=registry)
    lifecycle = active_strategy_lifecycle_payload(strategy_specs, config=config, target_date=target_date)
    runtime_identity = runtime_identity or get_runtime_identity()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat(),
        "runtime_identity": runtime_identity,
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "budget_usdc": float(budget_usdc),
        "budget_scope": "per_strategy",
        "markets": [spec.id for spec in selected_specs(markets)],
        "run_folder": str(run_folder),
        "snapshots_root": str(snapshots_root),
        "observation_status_path": str(observation_status_path),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "policy_config": config,
        "fee_config": taker_fee_config(config),
        "exchange_economics_gate": exchange_economics_gate or {},
        **exchange_economics.exchange_economics_artifact_fields(exchange_economics_gate or {}),
        "executable_depth_config": {
            "executable_depth_model": config.get("executable_depth_model"),
            "executable_depth_slippage_bps": config.get("executable_depth_slippage_bps"),
            "executable_depth_haircut": config.get("executable_depth_haircut"),
        },
        "taker_edge_permission": {
            "enabled": bool_value(config.get("taker_edge_permission_enabled"), True),
            "map_path": config.get("taker_edge_permission_map_path"),
            "missing_map_blocks": bool_value(config.get("taker_edge_permission_missing_map_blocks"), True),
            "calibrated_entry_enabled": bool_value(config.get("calibrated_entry_enabled"), True),
            "calibrated_sizing_enabled": bool_value(config.get("calibrated_sizing_enabled"), True),
            "min_after_cost_ev_per_share": config.get("min_after_cost_ev_per_share"),
            "market_no_trade_precondition_enabled": bool_value(
                config.get("market_no_trade_precondition_enabled"),
                True,
            ),
            "adverse_selection_edge_cap_enabled": bool_value(
                config.get("adverse_selection_edge_cap_enabled"),
                True,
            ),
            "adverse_selection_edge_cap": config.get("adverse_selection_edge_cap"),
            "adverse_selection_cap_min_skill_weight": config.get("adverse_selection_cap_min_skill_weight"),
        },
        "active_strategy_id": lifecycle.get("active_strategy_id"),
        "active_strategy_lifecycle": lifecycle.get("active_strategy_lifecycle"),
        "active_strategy_canary": lifecycle.get("active_strategy_canary"),
        "experiment_id": experiment_id,
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_ids": [item.get("strategy_id") for item in strategy_specs],
        "performance_gate_state": {
            "weak_slot_gate_status": config.get("_weak_slot_gate_status"),
            "weak_slot_gate_source": config.get("_weak_slot_gate_source"),
            "weak_slot_minutes": config.get("_weak_slot_minutes") or [],
            "hourly_gate_status": config.get("_hourly_gate_status"),
            "hourly_gate_source": config.get("_hourly_gate_source"),
        },
        "event_metadata_validation": {
            key: value
            for key, value in (event_metadata_state or {}).items()
            if key != "payload"
        },
        "strategy_registry": strategy_registry_payload(registry=registry),
        "strategies": [
            {
                key: value
                for key, value in item.items()
                if key not in {"config"}
            }
            for item in strategy_specs
        ],
        "shadow_safety": {
            "loads_private_keys": False,
            "posts_orders": False,
            "pretend_taker_orders_only": True,
            "counterfactual_orders_only": True,
        },
        "counterfactual_tape": {
            "enabled": bool_value(config.get("counterfactual_tape_enabled"), True),
            "strategies": counterfactual_strategy_arg(config),
            "retention_days": int(config.get("counterfactual_retention_days") or 14),
        },
        "model_variant_basket": {
            "variant_ids": taker_model_variant_ids(config),
            "include_missing": bool_value(config.get("taker_model_variant_include_missing"), False),
            "default_basket": DEFAULT_TAKER_MODEL_VARIANT_BASKET,
        },
    }


def taker_edge_permission_coverage(rows, config=None):
    config = config or {}
    rows = list(rows or [])
    permission_counts = Counter(row.get("taker_edge_permission") or "missing" for row in rows)
    evidence_counts = Counter(row.get("taker_edge_permission_evidence_status") or "missing" for row in rows)
    adverse_counts = Counter(row.get("adverse_selection_status") or "missing" for row in rows)
    reason_counts = Counter(row.get("reason_code") or "unknown" for row in rows)
    market_no_trade_rows = sum(
        1 for row in rows
        if row.get("market_benchmark_precondition") == "no_trade"
        or row.get("reason_code") == "NO_TRADE_MARKET_BENCHMARK_NO_TRADE"
    )
    return {
        "enabled": bool_value(config.get("taker_edge_permission_enabled"), True),
        "calibrated_entry_enabled": bool_value(config.get("calibrated_entry_enabled"), True),
        "calibrated_sizing_enabled": bool_value(config.get("calibrated_sizing_enabled"), True),
        "map_path": config.get("taker_edge_permission_map_path"),
        "row_count": len(rows),
        "edge_allowed_rows": permission_counts.get("edge_allowed", 0),
        "not_edge_allowed_rows": sum(
            count for permission, count in permission_counts.items()
            if permission != "edge_allowed"
        ),
        "missing_evidence_rows": evidence_counts.get("map_missing", 0) + evidence_counts.get("missing_cell", 0),
        "market_no_trade_rows": market_no_trade_rows,
        "after_cost_ev_skipped_rows": reason_counts.get("NO_TRADE_AFTER_COST_EV_TOO_SMALL", 0),
        "adverse_selection_blocked_rows": reason_counts.get("NO_TRADE_ADVERSE_SELECTION_EDGE_CAP", 0),
        "permission_counts": dict(sorted(permission_counts.items())),
        "evidence_status_counts": dict(sorted(evidence_counts.items())),
        "adverse_selection_counts": dict(sorted(adverse_counts.items())),
    }


def last_nonzero_scored_tick_summary(rows):
    rows = list(rows or [])
    if not rows:
        return {}
    grouped = {}
    for index, row in enumerate(rows):
        key = (
            row.get("generated_at_utc")
            or row.get("captured_at_utc")
            or f"row-{index:06d}"
        )
        grouped.setdefault(str(key), []).append(row)
    if not grouped:
        return {}
    latest_key = max(grouped)
    tick_rows = grouped[latest_key]
    filled = [row for row in tick_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    reason_counts = Counter(row.get("reason_code") or "unknown" for row in tick_rows)
    generated_times = sorted({row.get("generated_at_utc") for row in tick_rows if row.get("generated_at_utc")})
    captured_times = sorted({row.get("captured_at_utc") for row in tick_rows if row.get("captured_at_utc")})
    return {
        "generated_at_utc": generated_times[-1] if generated_times else None,
        "captured_at_utc": captured_times[-1] if captured_times else None,
        "row_count": len(tick_rows),
        "filled_order_count": len(filled),
        "spent_usdc": round(sum_field(filled, "total_spent_usdc"), 6),
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def _benchmark_group_payloads(rows, policy_config):
    groups = defaultdict(list)
    for row in rows or []:
        groups[(
            strategy_id_for_row(row),
            str(row.get("target_date") or ""),
            str(row.get("market_id") or ""),
            str(row.get("snapshot_id") or ""),
        )].append(dict(row))
    return [
        {
            "rows": group_rows,
            "payload": market_benchmark_scoreboard(group_rows, policy_config=policy_config),
        }
        for _key, group_rows in sorted(groups.items())
    ]


def _append_jsonl_batch_idempotent(path, rows):
    """Complete one bounded pending JSONL batch without duplicating a durable tail."""

    rows = list(rows or [])
    if not rows:
        return {"row_count": 0, "bytes_written": 0, "already_complete": True}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_rows = [
        (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")
        for row in rows
    ]
    data = b"".join(encoded_rows)
    overlap = 0
    try:
        actual = path.stat().st_size
    except OSError:
        actual = 0
    if actual:
        with path.open("rb") as handle:
            handle.seek(max(0, actual - len(data)))
            tail = handle.read()
        if tail.endswith(data):
            return {"row_count": len(rows), "bytes_written": 0, "already_complete": True}
        first_line = encoded_rows[0]
        start = tail.rfind(first_line)
        if start >= 0 and data.startswith(tail[start:]):
            overlap = len(tail) - start
        elif not tail.endswith(b"\n"):
            partial = tail.rsplit(b"\n", 1)[-1]
            if partial and data.startswith(partial):
                overlap = len(partial)
            else:
                raise RuntimeError(
                    f"pending JSONL batch found an unrelated incomplete tail in {path}"
                )
    remaining = data[overlap:]
    if remaining:
        with path.open("ab") as handle:
            handle.write(remaining)
            handle.flush()
            os.fsync(handle.fileno())
    return {
        "row_count": len(rows),
        "bytes_written": len(remaining),
        "already_complete": not remaining,
    }


def _benchmark_settlement_state(row, *, snapshots_root, ledger_root):
    event_slug = str(row.get("event_slug") or "")
    settlement = settlement_for_folder(
        Path(snapshots_root) / event_slug,
        event_slug,
        ledger_root=ledger_root,
    )
    if not settlement:
        return {"present": False}
    return {
        "present": True,
        "settlement_bucket": settlement.get("settlement_bucket"),
        "winning_band": settlement.get("winning_band"),
        "quality_grade": settlement.get("quality_grade"),
        "market_id": settlement.get("market_id"),
        "target_date": settlement.get("target_date"),
    }


def _refresh_incremental_benchmark(
    store,
    *,
    policy_config,
    snapshots_root,
    ledger_root,
    now,
    limit=BENCHMARK_REFRESH_GROUP_LIMIT,
):
    probe_rows = store.benchmark_probe_rows("orders")
    changed_events = []
    unavailable_after_finalized = []
    if probe_rows:
        scored_probes = score_orders(
            probe_rows,
            snapshots_root=snapshots_root,
            ledger_root=ledger_root,
            now=now,
        )
        settlement_by_event = {}
        for row in scored_probes:
            event_slug = str(row.get("event_slug") or "")
            if event_slug not in settlement_by_event:
                settlement_by_event[event_slug] = _benchmark_settlement_state(
                    row,
                    snapshots_root=snapshots_root,
                    ledger_root=ledger_root,
                )
            row["_benchmark_settlement_signature"] = settlement_by_event[event_slug]
        signature_state = store.mark_benchmark_event_signatures("orders", scored_probes)
        changed_events = signature_state.get("changed_events") or []
        unavailable_after_finalized = (
            signature_state.get("unavailable_after_finalized_events") or []
        )
    pending_groups = store.pending_benchmark_groups(
        "orders",
        limit=limit,
        exclude_event_keys=unavailable_after_finalized,
    )
    refreshed = 0
    deferred_generation_mismatch = 0
    if pending_groups:
        pending_rows = [
            row
            for group in pending_groups
            for row in group.get("rows") or []
        ]
        # Bind benchmark scoring to the exact settlement generation captured
        # above.  Re-reading the mutable label inside score_orders would reopen
        # a disappear/correction race between signature and contribution.
        scored_rows = []
        for row in pending_rows:
            item = dict(row)
            event_slug = str(item.get("event_slug") or "")
            captured = settlement_by_event.get(event_slug) or {"present": False}
            outcome = (
                settlement_outcome_for_order(item, captured)
                if captured.get("present")
                else None
            )
            item["settlement_outcome"] = compact_float(outcome)
            if str(item.get("order_status") or "").upper() == "FILLED":
                if outcome is not None:
                    fill_size = maybe_float(item.get("fill_size")) or 0.0
                    components = executable_pnl_components(item, float(outcome) * fill_size)
                    item.update(components)
            scored_rows.append(item)
        safe_groups = []
        for group in _benchmark_group_payloads(scored_rows, policy_config):
            rows = list(group.get("rows") or [])
            if not rows:
                continue
            event_slug = str(rows[0].get("event_slug") or "")
            captured_settlement = settlement_by_event.get(event_slug)
            current_settlement = _benchmark_settlement_state(
                rows[0],
                snapshots_root=snapshots_root,
                ledger_root=ledger_root,
            )
            generation_matches = current_settlement == captured_settlement
            outcomes_match = True
            if generation_matches and (captured_settlement or {}).get("present"):
                for row in rows:
                    expected = settlement_outcome_for_order(row, captured_settlement)
                    actual = maybe_float(row.get("settlement_outcome"))
                    if (
                        expected is None
                        or actual is None
                        or abs(float(expected) - float(actual)) > 1e-9
                    ):
                        outcomes_match = False
                        break
            elif generation_matches:
                outcomes_match = all(
                    maybe_float(row.get("settlement_outcome")) is None
                    for row in rows
                )
            if not generation_matches or not outcomes_match:
                deferred_generation_mismatch += 1
                continue
            safe_groups.append(group)
        refreshed = store.apply_benchmark_groups("orders", safe_groups)
    remaining = store.benchmark_pending_count("orders")
    return {
        "status": "REFRESH_PENDING" if remaining else "CURRENT",
        "changed_event_count": len(changed_events),
        "settlement_unavailable_after_finalized_event_count": len(
            unavailable_after_finalized
        ),
        "refreshed_group_count": int(refreshed),
        "deferred_generation_mismatch_group_count": int(
            deferred_generation_mismatch
        ),
        "remaining_group_count": int(remaining),
        "group_limit_per_tick": int(limit),
    }


def _complete_pending_incremental_tick(
    store,
    pending,
    *,
    order_path,
    counterfactual_path,
    budget_ledger_path,
    counterfactual_ledger_path,
    order_columns,
    counterfactual_columns,
):
    order_rows = list(pending.get("order_rows") or [])
    benchmark_groups = list(pending.get("order_benchmark_groups") or [])
    missing_orders = [
        row
        for row in order_rows
        if not store.has_intent("orders", str(row.get("intent_key") or ""))
    ]
    if missing_orders:
        store.append_rows(
            "orders",
            order_path,
            order_columns,
            missing_orders,
            benchmark_groups=benchmark_groups,
        )
    if benchmark_groups:
        store.apply_benchmark_groups("orders", benchmark_groups)

    counterfactual_rows = list(pending.get("counterfactual_rows") or [])
    missing_counterfactual = [
        row
        for row in counterfactual_rows
        if not store.has_intent("counterfactual", str(row.get("intent_key") or ""))
    ]
    if missing_counterfactual:
        store.append_rows(
            "counterfactual",
            counterfactual_path,
            counterfactual_columns,
            missing_counterfactual,
        )
    if any(
        not store.has_intent("orders", str(row.get("intent_key") or ""))
        for row in order_rows
    ) or any(
        not store.has_intent("counterfactual", str(row.get("intent_key") or ""))
        for row in counterfactual_rows
    ):
        raise RuntimeError("pending taker tick did not reach a durable terminal phase")
    _append_jsonl_batch_idempotent(
        budget_ledger_path,
        pending.get("budget_ledger") or [],
    )
    _append_jsonl_batch_idempotent(
        counterfactual_ledger_path,
        pending.get("counterfactual_ledger") or [],
    )
    store.clear_pending_tick()
    return {
        "recovered": True,
        "order_row_count": len(order_rows),
        "counterfactual_row_count": len(counterfactual_rows),
    }


def _archive_run_folder_for_fresh(run_folder, now):
    run_folder = Path(run_folder)
    if not run_folder.exists() or not any(run_folder.iterdir()):
        return None
    stamp = utc_now(now).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # Daily-roll and finalization enumerate the immediate children below the
    # active runs root.  Keep preserved generations in a sibling root so an
    # archived run cannot be mistaken for an active one.
    runs_root = run_folder.parent.parent
    archive_parent = (
        runs_root.with_name(f"{runs_root.name}_fresh_archives")
        / run_folder.parent.name
    )
    archive_parent.mkdir(parents=True, exist_ok=True)
    for index in range(1000):
        collision = "" if index == 0 else f".{index}"
        archived = archive_parent / f"{run_folder.name}.fresh-archive-{stamp}{collision}"
        if archived.exists():
            continue
        run_folder.rename(archived)
        return archived
    raise RuntimeError(f"could not archive existing fresh-run folder {run_folder}")


def _incremental_pnl_payload(
    store,
    *,
    budget_usdc,
    run_id,
    target_date,
    now,
    policy_config,
    snapshots_root,
    ledger_root,
    benchmark_refresh=None,
):
    """Build cumulative P&L from bounded fill state plus checkpoint counters."""

    filled = score_orders(
        store.filled_rows("orders"),
        snapshots_root=snapshots_root,
        ledger_root=ledger_root,
        now=now,
    )
    filled_keys = {row.get("intent_key") for row in filled if row.get("intent_key")}
    representatives = [
        row
        for row in store.representative_rows("orders")
        if row.get("intent_key") not in filled_keys
    ]
    payload = build_pnl_payload(
        [*filled, *representatives],
        budget_usdc,
        run_id,
        target_date,
        now=now,
        policy_config=policy_config,
    )
    stats = store.tape_stats("orders")
    strategy_stats = store.strategy_stats("orders")
    payload["summary"]["order_rows"] = stats["row_count"]
    payload["summary"]["filled_order_count"] = stats["filled_count"]
    payload["summary"]["reason_counts"] = stats["reason_counts"]

    benchmark = store.benchmark("orders") or payload.get("market_benchmark_scoreboard") or {}
    benchmark.setdefault("summary", {})["traded_pnl_usdc"] = sum_field(
        filled,
        "net_pnl_usdc",
    )
    current_traded_pnl = Counter()
    for row in filled:
        current_traded_pnl[strategy_id_for_row(row)] += maybe_float(row.get("net_pnl_usdc")) or 0.0
    for row in benchmark.get("by_strategy") or []:
        row["traded_pnl_usdc"] = round(current_traded_pnl[row.get("strategy_id")], 6)
    benchmark_by_strategy = {
        row.get("strategy_id"): row
        for row in benchmark.get("by_strategy") or []
    }
    rows_by_strategy = {
        row.get("strategy_id"): row
        for row in payload.get("by_strategy") or []
    }
    thresholds = promotion_thresholds(policy_config)
    refresh_pending = int((benchmark_refresh or {}).get("remaining_group_count") or 0) > 0
    for strategy_id, cumulative in strategy_stats.items():
        row = rows_by_strategy.get(strategy_id)
        if row is None:
            continue
        row.update({
            "order_rows": cumulative["row_count"],
            "reason_counts": cumulative["reason_counts"],
            "stale_book_rows": cumulative["stale_book_rows"],
            "source_stale_rows": cumulative["source_stale_rows"],
        })
        scored_benchmark = benchmark_by_strategy.get(strategy_id) or {}
        row.update({
            "market_benchmark_status": (
                "BLOCK_REFRESH_PENDING"
                if refresh_pending
                else scored_benchmark.get("status") or "PASS"
            ),
            "market_benchmark_opportunity_count": scored_benchmark.get("opportunity_count") or 0,
            "market_smarter_slice_count": scored_benchmark.get("market_smarter_slice_count") or 0,
            "market_benchmark_traded_pnl_usdc": scored_benchmark.get("traded_pnl_usdc") or 0.0,
            "market_benchmark_model_top_net_pnl_usdc": scored_benchmark.get("model_top_net_pnl_usdc") or 0.0,
            "market_benchmark_market_top_net_pnl_usdc": scored_benchmark.get("market_top_net_pnl_usdc") or 0.0,
            "market_benchmark_no_trade_net_pnl_usdc": scored_benchmark.get("no_trade_net_pnl_usdc") or 0.0,
            "market_benchmark_avoided_loss_usdc": scored_benchmark.get("avoided_loss_usdc") or 0.0,
            "market_benchmark_missed_gain_usdc": scored_benchmark.get("missed_gain_usdc") or 0.0,
            "market_benchmark_recommendations": scored_benchmark.get("recommendations") or [],
        })
        gate = settlement_promotion_gate(row, thresholds)
        if refresh_pending:
            gate = dict(gate)
            gate["status"] = "BLOCK"
            gate["gates"] = [
                *(gate.get("gates") or []),
                {
                    "name": "benchmark_refresh_complete",
                    "ok": False,
                    "value": (benchmark_refresh or {}).get("remaining_group_count"),
                    "threshold": 0,
                },
            ]
            gate["failed_gates"] = [
                *(gate.get("failed_gates") or []),
                "benchmark_refresh_complete",
            ]
        row["settlement_promotion_gate"] = gate
        row["settlement_promotion_gate_status"] = gate["status"]
        row["settlement_promotion_failed_gates"] = gate["failed_gates"]
        row["quality_candidate_countable"] = gate["status"] == "PASS"
        row["quality_candidate_evidence_basis"] = gate["basis"]

    strategy_rows = payload.get("by_strategy") or []
    best_by_net = max(strategy_rows, key=lambda row: maybe_float(row.get("net_pnl_usdc")) or 0.0, default={})
    countable = [row for row in strategy_rows if row.get("quality_candidate_countable")]
    best_countable = max(countable, key=lambda row: maybe_float(row.get("net_pnl_usdc")) or 0.0, default={})
    comparison = payload.setdefault("strategy_comparison", {})
    comparison.update({
        "best_strategy_id": best_by_net.get("strategy_id"),
        "best_strategy_net_pnl_usdc": best_by_net.get("net_pnl_usdc"),
        "best_settlement_scored_strategy_id": best_countable.get("strategy_id"),
        "best_settlement_scored_net_pnl_usdc": best_countable.get("net_pnl_usdc"),
        "countable_strategy_quality_candidate": best_countable,
        "countable_strategy_quality_candidate_status": (
            "COUNTABLE_SETTLED" if best_countable else "MISSING_SETTLED_SAMPLE"
        ),
        "market_benchmark_summary": benchmark.get("summary") or {},
        "market_benchmark_status": (
            "BLOCK_REFRESH_PENDING"
            if refresh_pending
            else
            "BLOCK_MARKET_SMARTER"
            if (benchmark.get("summary") or {}).get("market_smarter_slice_count")
            else "PASS"
        ),
    })
    payload["market_benchmark_scoreboard"] = benchmark
    payload["incremental_persistence"] = {
        "schema_version": "taker_incremental_pnl_v0.1",
        "bounded_materialized_filled_rows": len(filled),
        "bounded_representative_rows": len(representatives),
        "cumulative_order_rows": stats["row_count"],
        "scoring_basis": "bounded_fills_plus_incremental_counters",
        "benchmark_refresh": benchmark_refresh or {},
    }
    return payload, filled


def build_run_once(
    target_date,
    budget_usdc,
    markets=None,
    runs_root=DEFAULT_RUNS_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    run_id=None,
    config=None,
    now=None,
    append=True,
    ledger_root=None,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
    strategies=None,
    experiment_id=None,
    strategy_registry=None,
    event_metadata_validation_path=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    active_release_pointer_path=None,
    releases_root=DEFAULT_RELEASES_ROOT,
    release_repo_root=REPO_ROOT,
    release_check_runtime=True,
):
    tick_started = time.perf_counter()
    resource_start = process_resource_sample()
    now = utc_now(now)
    target = ensure_date(target_date)
    release_binding = load_worker_release_binding(
        pointer_path=active_release_pointer_path or DEFAULT_ACTIVE_RELEASE_POINTER,
        releases_root=releases_root,
        repo_root=release_repo_root,
        check_runtime=release_check_runtime,
        enabled=(
            active_release_pointer_path is not None
            or _uses_default_snapshot_root(snapshots_root)
        ),
    )
    release_summary_fields = worker_release_summary_fields(release_binding)
    order_columns = worker_tape_columns(ORDER_COLUMNS, release_binding)
    counterfactual_columns = worker_tape_columns(
        COUNTERFACTUAL_ORDER_COLUMNS,
        release_binding,
    )
    config = enrich_config_with_performance_gates({**DEFAULT_CONFIG, **(config or {})}, target)
    exchange_gate, exchange_fields = _exchange_economics_gate_for_run(
        exchange_economics_snapshot_path,
        target,
        exchange_economics_platform,
        now,
        required=(
            bool(exchange_economics_required)
            if exchange_economics_required is not None
            else (_uses_default_snapshot_root(snapshots_root) or exchange_economics_snapshot_path is not None)
        ),
    )
    strategy_specs = selected_strategy_specs(strategies, base_config=config, registry=strategy_registry)
    strategy_ids = [item["strategy_id"] for item in strategy_specs]
    experiment_id = experiment_id or default_experiment_id(target, strategy_ids)
    if run_id is None:
        if strategy_ids == [DEFAULT_CONTROL_STRATEGY_ID] and experiment_id == DEFAULT_EXPERIMENT_ID:
            run_id = default_run_id(target, config=config)
        else:
            run_id = default_run_id(target, config={
                **config,
                "experiment_id": experiment_id,
                "strategy_ids": strategy_ids,
            })
    run_folder = run_folder_for(runs_root, target, run_id)
    fresh_archive_path = _archive_run_folder_for_fresh(run_folder, now) if not append else None
    run_folder.mkdir(parents=True, exist_ok=True)
    order_path = run_folder / "orders_long.csv"
    counterfactual_path = run_folder / COUNTERFACTUAL_TAPE_FILENAME
    budget_ledger_path = run_folder / "budget_ledger.jsonl"
    counterfactual_ledger_path = run_folder / "counterfactual_budget_ledger.jsonl"
    counterfactual_enabled = bool_value(config.get("counterfactual_tape_enabled"), True)
    verify_worker_csv_tape_for_append(
        order_path,
        order_columns,
        release_binding,
        label="taker order tape",
    )
    verify_worker_csv_tape_for_append(
        counterfactual_path,
        counterfactual_columns,
        release_binding,
        label="taker counterfactual tape",
    )
    incremental_store = IncrementalTakerStore(run_folder) if append else None
    counterfactual_prepared = False
    pending_recovery = {}
    if incremental_store is not None:
        incremental_store.prepare_tape("orders", order_path, order_columns)
        pending = incremental_store.pending_tick()
        if (
            counterfactual_enabled
            or (pending.get("counterfactual_rows") or [])
            or counterfactual_path.exists()
        ):
            incremental_store.prepare_tape(
                "counterfactual",
                counterfactual_path,
                counterfactual_columns,
            )
            counterfactual_prepared = True
        if pending:
            verify_worker_tape_lineage(
                pending.get("order_rows") or [],
                release_binding,
                label="pending taker order tape rows",
            )
            verify_worker_tape_lineage(
                pending.get("counterfactual_rows") or [],
                release_binding,
                label="pending taker counterfactual tape rows",
            )
            pending_recovery = _complete_pending_incremental_tick(
                incremental_store,
                pending,
                order_path=order_path,
                counterfactual_path=counterfactual_path,
                budget_ledger_path=budget_ledger_path,
                counterfactual_ledger_path=counterfactual_ledger_path,
                order_columns=order_columns,
                counterfactual_columns=counterfactual_columns,
            )
        existing_rows = incremental_store.filled_rows("orders")
        verify_worker_tape_lineage(
            existing_rows,
            release_binding,
            label="existing taker order tape",
        )
        if counterfactual_prepared:
            verify_worker_tape_lineage(
                incremental_store.filled_rows("counterfactual"),
                release_binding,
                label="existing taker counterfactual tape",
            )
    else:
        existing_rows = []
    if (
        Path(snapshots_root) != Path(DEFAULT_SNAPSHOTS_ROOT)
        and Path(observation_status_path) == Path(DEFAULT_OBSERVATION_STATUS)
    ):
        observation_status = {}
    else:
        observation_status = load_observation_status(observation_status_path, now=now, config=config)
    event_state = _event_metadata_state(event_metadata_validation_path, target, snapshots_root)
    try:
        input_rows, market_summaries = discover_inputs(
            target,
            markets=markets,
            snapshots_root=snapshots_root,
            config=config,
            now=now,
            observation_status=observation_status,
            event_metadata_state=event_state,
            release_binding=release_binding,
        )
    except WorkerReleaseBindingError:
        if incremental_store is not None:
            incremental_store.close()
        raise
    new_rows = []
    budget_ledger = []
    for strategy in strategy_specs:
        strategy_existing_rows = [
            row for row in existing_rows
            if strategy_id_for_row(row) == strategy["strategy_id"]
        ]
        strategy_rows, strategy_ledger = apply_taker_budget(
            input_rows,
            strategy_existing_rows,
            strategy.get("budget_usdc") or budget_usdc,
            run_id,
            target,
            now,
            strategy["config"],
            strategy=strategy,
            experiment_id=experiment_id,
            intent_exists=(
                (lambda key: incremental_store.has_intent("orders", key))
                if incremental_store is not None
                else None
            ),
        )
        new_rows.extend(strategy_rows)
        budget_ledger.extend(strategy_ledger)
    new_rows = score_orders(
        new_rows,
        snapshots_root=snapshots_root,
        ledger_root=ledger_root,
        now=now,
    )
    _apply_exchange_economics_fields(new_rows, exchange_fields)
    stamp_worker_release_lineage(new_rows, release_binding)
    order_benchmark_groups = _benchmark_group_payloads(new_rows, config)
    counterfactual_rows = []
    all_counterfactual_rows = []
    counterfactual_ledger = []
    counterfactual_strategy_ids = []
    counterfactual_model_variant_manifest = {
        "requested_variant_ids": [],
        "materialized_variant_ids": [],
        "missing_variant_ids": [],
        "materialized_row_count": 0,
    }
    counterfactual_tape_integrity = {
        "status": "DISABLED",
        "path": str(counterfactual_path),
        "row_kind": "counterfactual_orders_long",
        "expected_rows": 0,
        "actual_rows": 0,
        "detail": "counterfactual tape disabled by config",
    }
    if counterfactual_enabled:
        if incremental_store is not None:
            existing_counterfactual_rows = incremental_store.filled_rows("counterfactual")
            real_attribution_rows = [
                *incremental_store.latest_rows("orders"),
                *new_rows,
            ]
        else:
            existing_counterfactual_rows = []
            real_attribution_rows = new_rows
        counterfactual_build = build_counterfactual_taker_rows(
            input_rows,
            existing_counterfactual_rows,
            real_attribution_rows,
            budget_usdc=budget_usdc,
            run_id=run_id,
            target_date=target,
            now=now,
            config=config,
            strategies=counterfactual_strategy_arg(config),
            experiment_id=experiment_id,
            strategy_registry=strategy_registry,
            intent_exists=(
                (lambda key: incremental_store.has_intent("counterfactual", key))
                if incremental_store is not None
                else None
            ),
        )
        counterfactual_rows = counterfactual_build["rows"]
        counterfactual_strategy_ids = [
            item.get("strategy_id")
            for item in counterfactual_build.get("strategy_specs") or []
        ]
        counterfactual_model_variant_manifest = counterfactual_build.get("model_variant_manifest") or counterfactual_model_variant_manifest
        counterfactual_ledger = list(counterfactual_build.get("ledger") or [])
        counterfactual_rows = score_orders(
            counterfactual_rows,
            snapshots_root=snapshots_root,
            ledger_root=ledger_root,
            now=now,
        )
        _apply_exchange_economics_fields(counterfactual_rows, exchange_fields)
        counterfactual_rows = annotate_counterfactual_rows(
            counterfactual_rows,
            real_rows=real_attribution_rows,
            strategy_set=",".join(counterfactual_strategy_ids),
        )
        stamp_worker_release_lineage(counterfactual_rows, release_binding)

    if incremental_store is not None:
        incremental_tick_id = uuid.uuid4().hex
        budget_ledger = [
            {**row, "incremental_tick_id": incremental_tick_id}
            for row in budget_ledger
        ]
        counterfactual_ledger = [
            {**row, "incremental_tick_id": incremental_tick_id}
            for row in counterfactual_ledger
        ]
        pending_tick = {
            "schema_version": "taker_pending_tick_v0.1",
            "incremental_tick_id": incremental_tick_id,
            "run_id": run_id,
            "target_date": target.isoformat(),
            "order_rows": new_rows,
            "order_benchmark_groups": order_benchmark_groups,
            "counterfactual_rows": counterfactual_rows,
            "budget_ledger": budget_ledger,
            "counterfactual_ledger": counterfactual_ledger,
        }
        pending_work = bool(
            new_rows or counterfactual_rows or budget_ledger or counterfactual_ledger
        )
        if pending_work:
            incremental_store.save_pending_tick(pending_tick)
        try:
            incremental_store.append_rows(
                "orders",
                order_path,
                order_columns,
                new_rows,
                benchmark_groups=order_benchmark_groups,
            )
            if counterfactual_enabled:
                incremental_store.append_rows(
                    "counterfactual",
                    counterfactual_path,
                    counterfactual_columns,
                    counterfactual_rows,
                )
            _append_jsonl_batch_idempotent(budget_ledger_path, budget_ledger)
            _append_jsonl_batch_idempotent(
                counterfactual_ledger_path,
                counterfactual_ledger,
            )
            if pending_work:
                incremental_store.clear_pending_tick()
        except Exception:
            # The durable pending envelope deliberately remains for restart.
            incremental_store.close()
            raise
        all_rows = score_orders(
            incremental_store.filled_rows("orders"),
            snapshots_root=snapshots_root,
            ledger_root=ledger_root,
            now=now,
        )
        _apply_exchange_economics_fields(all_rows, exchange_fields)
        tape_integrity = incremental_store.tape_integrity("orders", "orders_long")
        if counterfactual_enabled:
            all_counterfactual_rows = score_orders(
                incremental_store.filled_rows("counterfactual"),
                snapshots_root=snapshots_root,
                ledger_root=ledger_root,
                now=now,
            )
            _apply_exchange_economics_fields(all_counterfactual_rows, exchange_fields)
            counterfactual_tape_integrity = incremental_store.tape_integrity(
                "counterfactual",
                "counterfactual_orders_long",
            )
        elif counterfactual_prepared:
            all_counterfactual_rows = score_orders(
                incremental_store.filled_rows("counterfactual"),
                snapshots_root=snapshots_root,
                ledger_root=ledger_root,
                now=now,
            )
            _apply_exchange_economics_fields(all_counterfactual_rows, exchange_fields)
    else:
        all_rows = new_rows
        write_csv_rows(order_path, order_columns, all_rows)
        tape_integrity = tape_integrity_summary(order_path, len(all_rows), "orders_long")
        if counterfactual_enabled:
            all_counterfactual_rows = counterfactual_rows
            write_csv_rows(counterfactual_path, counterfactual_columns, all_counterfactual_rows)
            counterfactual_tape_integrity = tape_integrity_summary(
                counterfactual_path,
                len(all_counterfactual_rows),
                "counterfactual_orders_long",
            )

    if incremental_store is None:
        append_jsonl(budget_ledger_path, budget_ledger)
        if counterfactual_ledger:
            append_jsonl(counterfactual_ledger_path, counterfactual_ledger)
    total_budget_usdc = sum(float(item.get("budget_usdc") or budget_usdc) for item in strategy_specs)
    runtime_identity = get_runtime_identity()
    run_config = build_run_config_payload(
        run_id,
        target,
        budget_usdc,
        markets,
        run_folder,
        snapshots_root,
        config,
        now,
        observation_status_path=observation_status_path,
        experiment_id=experiment_id,
        strategy_specs=strategy_specs,
        registry=strategy_registry,
        runtime_identity=runtime_identity,
        event_metadata_state=event_state,
        exchange_economics_gate=exchange_gate,
    )
    run_config.update(release_summary_fields)
    if incremental_store is not None:
        benchmark_refresh = _refresh_incremental_benchmark(
            incremental_store,
            policy_config=run_config.get("policy_config") or config,
            snapshots_root=snapshots_root,
            ledger_root=ledger_root,
            now=now,
        )
        pnl_payload, all_rows = _incremental_pnl_payload(
            incremental_store,
            budget_usdc=total_budget_usdc,
            run_id=run_id,
            target_date=target,
            now=now,
            policy_config=run_config.get("policy_config") or config,
            snapshots_root=snapshots_root,
            ledger_root=ledger_root,
            benchmark_refresh=benchmark_refresh,
        )
    else:
        benchmark_refresh = {}
        pnl_payload = build_pnl_payload(
            all_rows,
            total_budget_usdc,
            run_id,
            target,
            now=now,
            policy_config=run_config.get("policy_config") or config,
        )
    pnl_payload = _annotate_taker_pnl_with_exchange_economics(pnl_payload, exchange_gate, exchange_fields)
    no_side_campaign = (
        incremental_store.no_side_summary(
            "orders",
            scored_filled_rows=all_rows,
            pnl_payload=pnl_payload,
        )
        if incremental_store is not None
        else no_side_campaign_summary(all_rows, pnl_payload=pnl_payload)
    )
    counterfactual_no_side_campaign = (
        incremental_store.no_side_summary(
            "counterfactual",
            scored_filled_rows=all_counterfactual_rows,
        )
        if incremental_store is not None
        else no_side_campaign_summary(all_counterfactual_rows)
    )
    edge_permission_coverage = taker_edge_permission_coverage(new_rows, config)
    run_config["taker_edge_permission_coverage"] = edge_permission_coverage
    write_json(run_folder / "daily_pnl.json", pnl_payload)
    write_json(run_folder / "run_config.json", run_config)
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=run_config,
        run_id=run_id,
        target_date=target,
        now=now,
    )
    write_json(run_folder / "strategy_summary.json", strategy_summary)
    strategy_report_path = run_folder / "strategy_report.md"
    strategy_report_path.write_text(render_strategy_report(strategy_summary), encoding="utf-8")

    reason_counts = Counter(row.get("reason_code") or "unknown" for row in new_rows)
    latest_filled = [row for row in new_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    order_state = incremental_store.tape_stats("orders") if incremental_store is not None else None
    counterfactual_state = (
        incremental_store.tape_stats("counterfactual")
        if incremental_store is not None and counterfactual_prepared
        else None
    )
    last_nonzero_tick = (
        order_state.get("last_nonzero_scored_tick")
        if order_state is not None
        else last_nonzero_scored_tick_summary(all_rows)
    )
    weak_slot_rows = [row for row in new_rows if row.get("weak_slot_gate_status") == "blocked"]
    warm_tail_rows = [row for row in new_rows if bool_value(row.get("market_centered_warm_tail"), False)]
    warm_tail_blocked = [
        row for row in new_rows
        if row.get("reason_code") in {"NO_TRADE_MARKET_CENTERED_WARM_TAIL", "NO_TRADE_MARKET_CENTERED_WARM_TAIL_CAP"}
    ]
    zero_trade_diagnosis = classify_zero_trade_root_cause(
        market_summaries,
        permission_rows=len(latest_filled),
        output_rows=len(new_rows),
    )
    if incremental_store is not None:
        tick_number = incremental_store.tick_number()
        budget_overrides = {
            key: config.get(f"taker_{key}", default)
            for key, default in DEFAULT_RESOURCE_BUDGETS.items()
        }
        resource_status = resource_diagnostics(
            resource_start,
            process_resource_sample(),
            elapsed_seconds=time.perf_counter() - tick_started,
            tick_number=tick_number,
            tape_io=incremental_store.io_diagnostics(),
            budgets=budget_overrides,
        )
        resource_status = incremental_store.record_resource_diagnostics(resource_status)
        tape_io_status = resource_status.get("tape_io") or {}
        incremental_persistence = {
            "schema_version": "taker_incremental_persistence_v0.1",
            "status": "RECOVERED" if tape_io_status.get("recovery_mode") else "PASS",
            "mode": "append_checkpoint",
            "checkpoint_path": str(incremental_store.path),
            "restart_recovery": "streaming_legacy_bootstrap_or_uncheckpointed_tail_only",
            "recovery_mode": bool(tape_io_status.get("recovery_mode")),
            "recovery_kind": tape_io_status.get("recovery_kind"),
            "recovered_row_count": int(tape_io_status.get("recovered_row_count") or 0),
            "recovery_bytes_read": (
                int(tape_io_status.get("tape_bytes_read") or 0)
                if tape_io_status.get("recovery_mode")
                else 0
            ),
            "ordinary_full_history_reads": 0,
            "ordinary_full_history_rewrites": 0,
            "bounded_materialized_order_fills": len(all_rows),
            "bounded_materialized_counterfactual_fills": len(all_counterfactual_rows),
            "pending_tick_recovery": pending_recovery,
            "benchmark_refresh": benchmark_refresh,
        }
    else:
        tick_number = 1
        resource_status = {}
        incremental_persistence = {
            "schema_version": "taker_incremental_persistence_v0.1",
            "status": "MAINTENANCE_REBUILD",
            "mode": "explicit_non_append",
            "fresh_archive_path": str(fresh_archive_path) if fresh_archive_path else None,
        }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_date": target.isoformat(),
        "runtime_identity": runtime_identity,
        **release_summary_fields,
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "active_strategy_id": run_config.get("active_strategy_id"),
        "active_strategy_lifecycle": run_config.get("active_strategy_lifecycle"),
        "active_strategy_canary": run_config.get("active_strategy_canary"),
        "strategy_count": len(strategy_specs),
        "strategy_ids": strategy_ids,
        "budget_usdc": round(total_budget_usdc, 6),
        "budget_per_strategy_usdc": round(float(budget_usdc), 6),
        "budget_scope": "per_strategy",
        "budget_spent_usdc": pnl_payload["summary"]["budget_spent_usdc"],
        "budget_remaining_usdc": pnl_payload["summary"]["budget_remaining_usdc"],
        "exchange_economics_gate_status": exchange_gate.get("status"),
        "exchange_economics_gate_reason": exchange_gate.get("reason"),
        **exchange_fields,
        "latest_tick_rows": len(new_rows),
        "latest_tick_filled_orders": len(latest_filled),
        "latest_tick_spent_usdc": sum_field(latest_filled, "total_spent_usdc"),
        "latest_tick_counterfactual_rows": len(counterfactual_rows),
        "latest_tick_counterfactual_would_buy_count": sum(
            1 for row in counterfactual_rows
            if str(row.get("order_status") or "").upper() == "FILLED"
        ),
        "last_nonzero_scored_tick": last_nonzero_tick,
        "cumulative_counterfactual_rows": (
            counterfactual_state.get("row_count") if counterfactual_state is not None else len(all_counterfactual_rows)
        ),
        "cumulative_counterfactual_would_buy_count": (
            counterfactual_state.get("filled_count")
            if counterfactual_state is not None
            else sum(
                1 for row in all_counterfactual_rows
                if str(row.get("order_status") or "").upper() == "FILLED"
            )
        ),
        "counterfactual_strategy_ids": counterfactual_strategy_ids,
        "counterfactual_model_variant_manifest": counterfactual_model_variant_manifest,
        "no_side_campaign": no_side_campaign,
        "counterfactual_no_side_campaign": counterfactual_no_side_campaign,
        "no_side_campaign_status": no_side_campaign.get("status"),
        "counterfactual_no_side_campaign_status": counterfactual_no_side_campaign.get("status"),
        "counterfactual_no_side_rows": counterfactual_no_side_campaign.get("no_side_row_count"),
        "counterfactual_no_side_would_buy_count": counterfactual_no_side_campaign.get("no_side_would_buy_count"),
        "counterfactual_countable_no_side_would_buy_count": counterfactual_no_side_campaign.get("countable_no_side_would_buy_count"),
        "taker_edge_permission_coverage": edge_permission_coverage,
        "cumulative_order_rows": order_state.get("row_count") if order_state is not None else len(all_rows),
        "cumulative_filled_orders": pnl_payload["summary"]["filled_order_count"],
        "cumulative_net_pnl_usdc": pnl_payload["summary"]["net_pnl_usdc"],
        "reason_counts": dict(sorted(reason_counts.items())),
        "weak_slot_gate_status": config.get("_weak_slot_gate_status"),
        "weak_slot_gate_source": config.get("_weak_slot_gate_source"),
        "weak_slot_blocked_rows": len(weak_slot_rows),
        "market_centered_warm_tail_rows": len(warm_tail_rows),
        "market_centered_warm_tail_blocked_rows": len(warm_tail_blocked),
        "next_run_policy_status": "UNKNOWN",
        "market_status_counts": dict(sorted(Counter(row.get("status") for row in market_summaries).items())),
        "tape_integrity": tape_integrity,
        "counterfactual_tape_integrity": counterfactual_tape_integrity,
        "incremental_persistence": incremental_persistence,
        "resource_diagnostics": resource_status,
        **zero_trade_diagnosis,
    }
    upstream_dependency_status = build_taker_upstream_dependency_status(market_summaries)
    summary["upstream_dependency_status"] = upstream_dependency_status
    evidence_starvation = classify_taker_evidence_starvation(summary, markets=market_summaries)
    summary.update({
        "taker_evidence_starvation": evidence_starvation,
        "latest_tick_scoring_liveness": {
            "status": evidence_starvation.get("status"),
            "classification": evidence_starvation.get("classification"),
            "restart_recommended": evidence_starvation.get("restart_recommended"),
            "countability_status": evidence_starvation.get("countability_status"),
            "latest_tick_rows": evidence_starvation.get("latest_tick_rows"),
            "last_nonzero_scored_tick": evidence_starvation.get("last_nonzero_scored_tick"),
            "first_failing_dependency": evidence_starvation.get("first_failing_dependency"),
            "remediation_command": evidence_starvation.get("remediation_command"),
        },
        "taker_day_classification": evidence_starvation.get("taker_day_classification"),
        "zero_would_buy_classification": evidence_starvation.get("zero_would_buy_classification"),
        "taker_evidence_countability_status": evidence_starvation.get("countability_status"),
        "taker_evidence_countability_blockers": evidence_starvation.get("countability_blockers") or [],
    })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "runtime_identity": runtime_identity,
        **release_summary_fields,
        "run_folder": str(run_folder),
        "run_config_path": str(run_folder / "run_config.json"),
        "orders_path": str(order_path),
        "counterfactual_orders_path": str(counterfactual_path),
        "budget_ledger_path": str(run_folder / "budget_ledger.jsonl"),
        "counterfactual_budget_ledger_path": str(counterfactual_ledger_path),
        "daily_pnl_path": str(run_folder / "daily_pnl.json"),
        "run_report_path": str(run_folder / "run_report.md"),
        "strategy_summary_path": str(run_folder / "strategy_summary.json"),
        "strategy_report_path": str(strategy_report_path),
        "summary": summary,
        "config": config,
        "strategy_registry": strategy_registry_payload(strategy_registry),
        "strategies": run_config.get("strategies"),
        "strategy_summary": strategy_summary,
        "observation_status": observation_status,
        "markets": market_summaries,
        "pnl": pnl_payload,
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "latest_orders": new_rows,
        "latest_counterfactual_orders": counterfactual_rows,
        "tape_integrity": tape_integrity,
        "counterfactual_tape_integrity": counterfactual_tape_integrity,
        "counterfactual_model_variant_manifest": counterfactual_model_variant_manifest,
        "incremental_persistence": incremental_persistence,
        "resource_diagnostics": resource_status,
        "upstream_dependency_status": upstream_dependency_status,
        "taker_evidence_starvation": evidence_starvation,
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "snapshot_status_command": "python -m weather.collection.snapshot_tracker --status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "first_failing_dependency": evidence_starvation.get("first_failing_dependency"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "taker_day_classification": evidence_starvation.get("taker_day_classification"),
            "evidence_countability_status": evidence_starvation.get("countability_status"),
            "remediation_command": evidence_starvation.get("remediation_command"),
        },
    }
    write_json(run_folder / "run_summary.json", payload)
    (run_folder / "run_report.md").write_text(render_report(payload), encoding="utf-8")
    if incremental_store is not None:
        incremental_store.close()
    return payload


def _infer_order_tape_budget(rows, default=0.0):
    for row in rows or []:
        value = maybe_float(row.get("budget_usdc"))
        if value is not None:
            return value
    return float(default)


def _infer_order_tape_strategies(rows):
    strategy_ids = []
    seen = set()
    for row in rows or []:
        strategy_id = strategy_id_for_row(row)
        if strategy_id and strategy_id not in seen:
            seen.add(strategy_id)
            strategy_ids.append(strategy_id)
    return ",".join(strategy_ids) or None


def recover_run_artifacts_from_orders(
    run_folder,
    *,
    budget_usdc=None,
    markets=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
    config=None,
    strategies=None,
    experiment_id=None,
    strategy_registry=None,
    now=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    """Rebuild summary artifacts for a run folder with a complete order tape."""
    now = utc_now(now)
    run_folder = Path(run_folder)
    order_path = run_folder / "orders_long.csv"
    if not order_path.exists():
        raise FileNotFoundError(f"missing taker orders tape: {order_path}")
    all_rows = read_order_rows(order_path)
    if not all_rows:
        raise ValueError(f"taker orders tape has no rows: {order_path}")

    first = all_rows[0]
    target = ensure_date(first.get("target_date") or run_folder.parent.name)
    run_id = first.get("run_id") or run_folder.name
    budget = float(budget_usdc if budget_usdc is not None else _infer_order_tape_budget(all_rows))
    strategy_arg = strategies or _infer_order_tape_strategies(all_rows)
    config = enrich_config_with_performance_gates({**DEFAULT_CONFIG, **(config or {})}, target)
    exchange_gate, exchange_fields = _exchange_economics_gate_for_run(
        exchange_economics_snapshot_path,
        target,
        exchange_economics_platform,
        now,
        required=(
            bool(exchange_economics_required)
            if exchange_economics_required is not None
            else (_uses_default_snapshot_root(snapshots_root) or exchange_economics_snapshot_path is not None)
        ),
    )
    strategy_specs = selected_strategy_specs(strategy_arg, base_config=config, registry=strategy_registry)
    strategy_ids = [item["strategy_id"] for item in strategy_specs]
    experiment_id = experiment_id or first.get("experiment_id") or default_experiment_id(target, strategy_ids)
    if markets in (None, "", "all"):
        market_arg = ",".join(sorted({row.get("market_id") for row in all_rows if row.get("market_id")})) or markets
    else:
        market_arg = markets

    generated_times = [row.get("generated_at_utc") for row in all_rows if row.get("generated_at_utc")]
    latest_generated = max(generated_times) if generated_times else None
    latest_rows = [
        row for row in all_rows
        if latest_generated is None or row.get("generated_at_utc") == latest_generated
    ]
    _apply_exchange_economics_fields(latest_rows, exchange_fields)
    tape_integrity = tape_integrity_summary(order_path, len(all_rows), "orders_long")
    total_budget_usdc = sum(float(item.get("budget_usdc") or budget) for item in strategy_specs)
    runtime_identity = get_runtime_identity()
    run_config = build_run_config_payload(
        run_id,
        target,
        budget,
        market_arg,
        run_folder,
        snapshots_root,
        config,
        now,
        observation_status_path=observation_status_path,
        experiment_id=experiment_id,
        strategy_specs=strategy_specs,
        registry=strategy_registry,
        runtime_identity=runtime_identity,
        exchange_economics_gate=exchange_gate,
    )
    pnl_payload = build_pnl_payload(
        all_rows,
        total_budget_usdc,
        run_id,
        target,
        now=now,
        policy_config=run_config.get("policy_config") or config,
    )
    pnl_payload = _annotate_taker_pnl_with_exchange_economics(pnl_payload, exchange_gate, exchange_fields)
    no_side_campaign = no_side_campaign_summary(all_rows, pnl_payload=pnl_payload)
    counterfactual_path = run_folder / COUNTERFACTUAL_TAPE_FILENAME
    counterfactual_ledger_path = run_folder / "counterfactual_budget_ledger.jsonl"
    counterfactual_tape_integrity = {
        "status": "MISSING",
        "path": str(counterfactual_path),
        "row_kind": "counterfactual_orders_long",
        "expected_rows": 0,
        "actual_rows": 0,
        "detail": "counterfactual tape was not present when recovering run artifacts",
    }
    if counterfactual_path.exists():
        counterfactual_rows = read_order_rows(counterfactual_path)
        counterfactual_tape_integrity = tape_integrity_summary(
            counterfactual_path,
            len(counterfactual_rows),
            "counterfactual_orders_long",
        )
    else:
        counterfactual_rows = []
    recovered_release_fields = worker_tape_summary_fields(
        [*all_rows, *counterfactual_rows]
    )
    run_config.update(recovered_release_fields)
    counterfactual_no_side_campaign = no_side_campaign_summary(counterfactual_rows)
    edge_permission_coverage = taker_edge_permission_coverage(latest_rows, config)
    run_config["taker_edge_permission_coverage"] = edge_permission_coverage

    write_json(run_folder / "daily_pnl.json", pnl_payload)
    write_json(run_folder / "run_config.json", run_config)
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=run_config,
        run_id=run_id,
        target_date=target,
        now=now,
    )
    write_json(run_folder / "strategy_summary.json", strategy_summary)
    strategy_report_path = run_folder / "strategy_report.md"
    strategy_report_path.write_text(render_strategy_report(strategy_summary), encoding="utf-8")

    reason_counts = Counter(row.get("reason_code") or "unknown" for row in latest_rows)
    latest_filled = [row for row in latest_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    last_nonzero_tick = last_nonzero_scored_tick_summary(all_rows)
    weak_slot_rows = [row for row in latest_rows if row.get("weak_slot_gate_status") == "blocked"]
    warm_tail_rows = [row for row in latest_rows if bool_value(row.get("market_centered_warm_tail"), False)]
    warm_tail_blocked = [
        row for row in latest_rows
        if row.get("reason_code") in {"NO_TRADE_MARKET_CENTERED_WARM_TAIL", "NO_TRADE_MARKET_CENTERED_WARM_TAIL_CAP"}
    ]
    zero_trade_diagnosis = classify_zero_trade_root_cause(
        [],
        permission_rows=len(latest_filled),
        output_rows=len(latest_rows),
    )
    if len(latest_filled) <= 0 and latest_rows:
        zero_trade_diagnosis = {
            **zero_trade_diagnosis,
            "root_cause_class": "policy_no_edge",
            "first_failing_gate": "policy",
            "zero_trades_expected": True,
        }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_date": target.isoformat(),
        "runtime_identity": runtime_identity,
        **recovered_release_fields,
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "active_strategy_id": run_config.get("active_strategy_id"),
        "active_strategy_lifecycle": run_config.get("active_strategy_lifecycle"),
        "active_strategy_canary": run_config.get("active_strategy_canary"),
        "strategy_count": len(strategy_specs),
        "strategy_ids": strategy_ids,
        "budget_usdc": round(total_budget_usdc, 6),
        "budget_per_strategy_usdc": round(float(budget), 6),
        "budget_scope": "per_strategy",
        "budget_spent_usdc": pnl_payload["summary"]["budget_spent_usdc"],
        "budget_remaining_usdc": pnl_payload["summary"]["budget_remaining_usdc"],
        "exchange_economics_gate_status": exchange_gate.get("status"),
        "exchange_economics_gate_reason": exchange_gate.get("reason"),
        **exchange_fields,
        "latest_tick_rows": len(latest_rows),
        "latest_tick_filled_orders": len(latest_filled),
        "latest_tick_spent_usdc": sum_field(latest_filled, "total_spent_usdc"),
        "latest_tick_counterfactual_rows": 0,
        "latest_tick_counterfactual_would_buy_count": 0,
        "last_nonzero_scored_tick": last_nonzero_tick,
        "cumulative_counterfactual_rows": len(counterfactual_rows),
        "cumulative_counterfactual_would_buy_count": sum(
            1 for row in counterfactual_rows
            if str(row.get("order_status") or "").upper() == "FILLED"
        ),
        "counterfactual_strategy_ids": [],
        "counterfactual_model_variant_manifest": {
            "requested_variant_ids": [],
            "materialized_variant_ids": [],
            "missing_variant_ids": [],
            "materialized_row_count": 0,
        },
        "no_side_campaign": no_side_campaign,
        "counterfactual_no_side_campaign": counterfactual_no_side_campaign,
        "no_side_campaign_status": no_side_campaign.get("status"),
        "counterfactual_no_side_campaign_status": counterfactual_no_side_campaign.get("status"),
        "counterfactual_no_side_rows": counterfactual_no_side_campaign.get("no_side_row_count"),
        "counterfactual_no_side_would_buy_count": counterfactual_no_side_campaign.get("no_side_would_buy_count"),
        "counterfactual_countable_no_side_would_buy_count": counterfactual_no_side_campaign.get("countable_no_side_would_buy_count"),
        "taker_edge_permission_coverage": edge_permission_coverage,
        "cumulative_order_rows": len(all_rows),
        "cumulative_filled_orders": pnl_payload["summary"]["filled_order_count"],
        "cumulative_net_pnl_usdc": pnl_payload["summary"]["net_pnl_usdc"],
        "reason_counts": dict(sorted(reason_counts.items())),
        "weak_slot_gate_status": config.get("_weak_slot_gate_status"),
        "weak_slot_gate_source": config.get("_weak_slot_gate_source"),
        "weak_slot_blocked_rows": len(weak_slot_rows),
        "market_centered_warm_tail_rows": len(warm_tail_rows),
        "market_centered_warm_tail_blocked_rows": len(warm_tail_blocked),
        "next_run_policy_status": "UNKNOWN",
        "market_status_counts": {},
        "tape_integrity": tape_integrity,
        "counterfactual_tape_integrity": counterfactual_tape_integrity,
        "artifact_recovery": {
            "status": "RECOVERED_FROM_ORDERS_TAPE",
            "source_orders_path": str(order_path),
            "latest_generated_at_utc": latest_generated,
        },
        **zero_trade_diagnosis,
    }
    upstream_dependency_status = build_taker_upstream_dependency_status([])
    summary["upstream_dependency_status"] = upstream_dependency_status
    evidence_starvation = classify_taker_evidence_starvation(summary, markets=[])
    summary.update({
        "taker_evidence_starvation": evidence_starvation,
        "latest_tick_scoring_liveness": {
            "status": evidence_starvation.get("status"),
            "classification": evidence_starvation.get("classification"),
            "restart_recommended": evidence_starvation.get("restart_recommended"),
            "countability_status": evidence_starvation.get("countability_status"),
            "latest_tick_rows": evidence_starvation.get("latest_tick_rows"),
            "last_nonzero_scored_tick": evidence_starvation.get("last_nonzero_scored_tick"),
            "first_failing_dependency": evidence_starvation.get("first_failing_dependency"),
            "remediation_command": evidence_starvation.get("remediation_command"),
        },
        "taker_day_classification": evidence_starvation.get("taker_day_classification"),
        "zero_would_buy_classification": evidence_starvation.get("zero_would_buy_classification"),
        "taker_evidence_countability_status": evidence_starvation.get("countability_status"),
        "taker_evidence_countability_blockers": evidence_starvation.get("countability_blockers") or [],
    })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "runtime_identity": runtime_identity,
        **recovered_release_fields,
        "run_folder": str(run_folder),
        "run_config_path": str(run_folder / "run_config.json"),
        "orders_path": str(order_path),
        "counterfactual_orders_path": str(counterfactual_path),
        "budget_ledger_path": str(run_folder / "budget_ledger.jsonl"),
        "counterfactual_budget_ledger_path": str(counterfactual_ledger_path),
        "daily_pnl_path": str(run_folder / "daily_pnl.json"),
        "run_report_path": str(run_folder / "run_report.md"),
        "strategy_summary_path": str(run_folder / "strategy_summary.json"),
        "strategy_report_path": str(strategy_report_path),
        "summary": summary,
        "config": config,
        "strategy_registry": strategy_registry_payload(strategy_registry),
        "strategies": run_config.get("strategies"),
        "strategy_summary": strategy_summary,
        "observation_status": {},
        "markets": [],
        "pnl": pnl_payload,
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "latest_orders": latest_rows,
        "latest_counterfactual_orders": [],
        "tape_integrity": tape_integrity,
        "counterfactual_tape_integrity": counterfactual_tape_integrity,
        "counterfactual_model_variant_manifest": summary["counterfactual_model_variant_manifest"],
        "upstream_dependency_status": upstream_dependency_status,
        "taker_evidence_starvation": evidence_starvation,
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "snapshot_status_command": "python -m weather.collection.snapshot_tracker --status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "first_failing_dependency": evidence_starvation.get("first_failing_dependency"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "taker_day_classification": evidence_starvation.get("taker_day_classification"),
            "evidence_countability_status": evidence_starvation.get("countability_status"),
            "remediation_command": evidence_starvation.get("remediation_command"),
        },
    }
    write_json(run_folder / "run_summary.json", payload)
    (run_folder / "run_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def recover_main(argv=None):
    parser = argparse.ArgumentParser(description="Recover taker run summary artifacts from an existing orders_long.csv.")
    parser.add_argument("--run-folder", required=True, help="Taker run folder containing orders_long.csv.")
    parser.add_argument("--budget-usdc", type=float, default=None)
    parser.add_argument("--markets", default=None)
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--observation-status", default=str(DEFAULT_OBSERVATION_STATUS))
    parser.add_argument("--strategies", default=None)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT))
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    parser.add_argument("--config", action="append", default=[], help="Taker bot config override, key=value.")
    args = parser.parse_args(argv)
    payload = recover_run_artifacts_from_orders(
        Path(args.run_folder),
        budget_usdc=args.budget_usdc,
        markets=args.markets,
        snapshots_root=Path(args.snapshots_root),
        observation_status_path=Path(args.observation_status),
        config=parse_config_overrides(args.config),
        strategies=args.strategies,
        experiment_id=args.experiment_id,
        now=args.now,
        exchange_economics_snapshot_path=Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None,
        exchange_economics_platform=args.exchange_economics_platform,
    )
    summary = payload.get("summary") or {}
    print(
        "Taker bot recovery: "
        f"{summary.get('cumulative_order_rows')} order rows, "
        f"{summary.get('cumulative_filled_orders')} cumulative buys -> {payload.get('run_folder')}"
    )
    return payload


def paper_until_utc(target_date, markets=None):
    target = ensure_date(target_date)
    specs = selected_specs(markets)
    ends = [
        datetime.combine(target, dt_time(23, 59, 59), tzinfo=spec.tz).astimezone(timezone.utc)
        for spec in specs
    ]
    return max(ends) if ends else None


def run_loop(
    target_date,
    budget_usdc,
    markets=None,
    interval_seconds=60.0,
    until_utc=None,
    max_ticks=None,
    **kwargs,
):
    until = parse_time(until_utc) if until_utc else paper_until_utc(target_date, markets=markets)
    last_payload = None
    tick = 0
    with keep_system_awake("weather taker bot loop"):
        while True:
            now = utc_now()
            if until is not None and now > until:
                break
            if max_ticks is not None and tick >= int(max_ticks):
                break
            last_payload = build_run_once(
                target_date,
                budget_usdc,
                markets=markets,
                now=now,
                append=True,
                **kwargs,
            )
            tick += 1
            if max_ticks is not None and tick >= int(max_ticks):
                break
            time.sleep(float(interval_seconds))
    return last_payload


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value.")
        key, value = item.split("=", 1)
        if key not in DEFAULT_CONFIG:
            raise SystemExit(f"Unknown taker bot config key {key!r}.")
        default = DEFAULT_CONFIG[key]
        if isinstance(default, bool):
            config[key] = bool_value(value)
        elif isinstance(default, int):
            config[key] = int(float(value))
        elif isinstance(default, float):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def finalize_main(argv=None):
    parser = argparse.ArgumentParser(description="Finalize taker-bot paper P&L against settled labels.")
    parser.add_argument("--date", default=None, help="Target market date to finalize, YYYY-MM-DD.")
    parser.add_argument("--run-folder", default=None, help="Finalize one taker run folder.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    parser.add_argument("--watchdog", action="store_true", help="Scan labelable runs and finalize missing settled P&L.")
    parser.add_argument("--no-finalize", action="store_true", help="Report watchdog state without writing settled artifacts.")
    parser.add_argument("--sla-hours", type=float, default=DEFAULT_FINALIZATION_SLA_HOURS)
    parser.add_argument("--status-out", default=None, help="Optional JSON status output for watchdog mode.")
    parser.add_argument("--report-out", default=None, help="Optional Markdown report output for watchdog mode.")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--retention-days", type=int, default=DEFAULT_FINALIZATION_RETENTION_DAYS)
    parser.add_argument("--retention-min-candidate-bytes", type=int, default=DEFAULT_RETENTION_CANDIDATE_MIN_BYTES)
    parser.add_argument("--no-bakeoff", action="store_true", help="Do not create or refresh strategy_bakeoff artifacts.")
    parser.add_argument("--bakeoff-strategies", default=DEFAULT_BAKEOFF_STRATEGIES)
    parser.add_argument("--champion-strategy-id", default=ACTIVE_DEFAULT_STRATEGY_ID)
    parser.add_argument("--champion-min-complete-label-days", type=int, default=DEFAULT_CHAMPION_MIN_COMPLETE_LABEL_DAYS)
    parser.add_argument("--champion-min-settled-orders", type=int, default=DEFAULT_CHAMPION_MIN_SETTLED_ORDERS)
    parser.add_argument("--champion-ledger-out", default=None)
    parser.add_argument("--champion-ledger-report-out", default=None)
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT))
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    args = parser.parse_args(argv)
    if args.watchdog:
        payload = finalization_watchdog(
            target_date=args.date,
            runs_root=Path(args.runs_root),
            labels_csv=Path(args.labels_csv),
            run_folder=Path(args.run_folder) if args.run_folder else None,
            now=args.now,
            sla_hours=args.sla_hours,
            finalize_missing=not args.no_finalize,
            min_free_bytes=args.min_free_bytes,
            retention_days=args.retention_days,
            retention_min_candidate_bytes=args.retention_min_candidate_bytes,
            ensure_bakeoff=not args.no_bakeoff,
            bakeoff_strategies=args.bakeoff_strategies,
            champion_strategy_id=args.champion_strategy_id,
            champion_min_complete_label_days=args.champion_min_complete_label_days,
            champion_min_settled_orders=args.champion_min_settled_orders,
            champion_ledger_out=Path(args.champion_ledger_out) if args.champion_ledger_out else None,
            champion_ledger_report_out=(
                Path(args.champion_ledger_report_out) if args.champion_ledger_report_out else None
            ),
            exchange_economics_snapshot_path=(
                Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None
            ),
            exchange_economics_platform=args.exchange_economics_platform,
            exchange_economics_required=True,
        )
        if args.status_out:
            write_json(Path(args.status_out), payload)
        if args.report_out:
            Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_out).write_text(render_finalization_watchdog_report(payload), encoding="utf-8")
        summary = payload["summary"]
        print(
            "Taker finalization watchdog: "
            f"{summary['finalized_run_count']} finalized, "
            f"{summary['sla_breach_count']} SLA breach(es), "
            f"{summary['pending_finalization_count']} pending"
        )
        return payload
    payload = finalize_taker_runs(
        target_date=args.date,
        runs_root=Path(args.runs_root),
        labels_csv=Path(args.labels_csv),
        run_folder=Path(args.run_folder) if args.run_folder else None,
        now=args.now,
        min_free_bytes=args.min_free_bytes,
        exchange_economics_snapshot_path=(
            Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None
        ),
        exchange_economics_platform=args.exchange_economics_platform,
        exchange_economics_required=True,
    )
    print(f"Taker finalization: {payload['run_count']} run(s) finalized")
    for row in payload["runs"]:
        print(
            f"- {row['run_id']} {row['target_date']}: "
            f"net={row['net_pnl_usdc']} USDC, "
            f"settled/unsettled={row['settled_order_count']}/{row['unsettled_order_count']}, "
            f"reconciliation={row['reconciliation_status']} -> {row['settled_pnl_path']}"
        )
    return payload


def bakeoff_main(argv=None):
    parser = argparse.ArgumentParser(description="Run a settlement-scored taker strategy bakeoff.")
    parser.add_argument("--run-folder", required=True, help="Taker run folder containing orders_long.csv.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--strategies", default=DEFAULT_BAKEOFF_STRATEGIES)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--budget-usdc", type=float, default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-report", default=None)
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    parser.add_argument("--min-settled-orders", type=int, default=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS)
    parser.add_argument("--max-drawdown-usdc", type=float, default=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT))
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    parser.add_argument("--config", action="append", default=[], help="Taker bot config override, key=value.")
    args = parser.parse_args(argv)
    payload = run_taker_strategy_bakeoff(
        Path(args.run_folder),
        labels_csv=Path(args.labels_csv),
        strategies=args.strategies,
        budget_usdc=args.budget_usdc,
        out_json=Path(args.out_json) if args.out_json else None,
        out_report=Path(args.out_report) if args.out_report else None,
        now=args.now,
        experiment_id=args.experiment_id,
        config=parse_config_overrides(args.config),
        min_settled_orders=args.min_settled_orders,
        max_drawdown_usdc=args.max_drawdown_usdc,
        min_free_bytes=args.min_free_bytes,
        exchange_economics_snapshot_path=Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None,
        exchange_economics_platform=args.exchange_economics_platform,
    )
    summary = payload["summary"]
    print(
        "Taker strategy bakeoff: "
        f"{summary['strategy_count']} strategy arm(s), "
        f"{summary['promotion_pass_count']} pass, "
        f"{summary['promotion_block_count']} block -> {payload['output_json_path']}"
    )
    return payload


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "finalize":
        return finalize_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "bakeoff":
        return bakeoff_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "recover":
        return recover_main(raw_argv[1:])
    parser = argparse.ArgumentParser(description="Run the daily paper taker-bot simulator.")
    parser.add_argument("--date", required=True, help="Target market date, YYYY-MM-DD.")
    parser.add_argument("--budget-usdc", type=float, required=True, help="Daily simulated spend budget.")
    parser.add_argument("--markets", default="all", help="'all' or comma-separated market ids.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--observation-status", default=str(DEFAULT_OBSERVATION_STATUS))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    parser.add_argument("--config", action="append", default=[], help="Taker bot config override, key=value.")
    parser.add_argument(
        "--disable-counterfactual-tape",
        action="store_true",
        help="Disable counterfactual strategy-replay tape generation for this run.",
    )
    parser.add_argument(
        "--strategies",
        default=ACTIVE_DEFAULT_STRATEGY_ID,
        help="Comma-separated taker strategy IDs to run as isolated paper arms.",
    )
    parser.add_argument("--experiment-id", default=None, help="Stable experiment ID for multi-arm attribution.")
    parser.add_argument("--fresh", action="store_true", help="Start a fresh run folder instead of appending daily state.")
    parser.add_argument("--loop", action="store_true", help="Run repeatedly until end of market day or --until-utc.")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--until-utc", default=None)
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--ledger-root", default=None)
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT))
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    args = parser.parse_args(raw_argv)

    config = parse_config_overrides(args.config)
    if args.disable_counterfactual_tape:
        config["counterfactual_tape_enabled"] = False
    common = {
        "markets": args.markets,
        "runs_root": Path(args.runs_root),
        "snapshots_root": Path(args.snapshots_root),
        "run_id": args.run_id,
        "config": config,
        "ledger_root": Path(args.ledger_root) if args.ledger_root else None,
        "observation_status_path": Path(args.observation_status),
        "strategies": args.strategies,
        "experiment_id": args.experiment_id,
        "exchange_economics_snapshot_path": Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None,
        "exchange_economics_platform": args.exchange_economics_platform,
    }
    if args.loop and args.now is None and not args.fresh:
        payload = run_loop(
            args.date,
            args.budget_usdc,
            interval_seconds=args.interval_seconds,
            until_utc=args.until_utc,
            max_ticks=args.max_ticks,
            **common,
        )
    else:
        payload = build_run_once(
            args.date,
            args.budget_usdc,
            now=args.now,
            append=not args.fresh,
            **common,
        )
    if payload is None:
        print("Taker bot: no ticks executed")
        return None
    summary = payload["summary"]
    print(
        "Taker bot: "
        f"{summary['latest_tick_filled_orders']} new buys, "
        f"{summary['cumulative_filled_orders']} cumulative buys, "
        f"P&L {summary['cumulative_net_pnl_usdc']} USDC -> {payload['run_folder']}"
    )
    return payload


if __name__ == "__main__":
    main()

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
