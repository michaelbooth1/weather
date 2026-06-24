"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_finalization import *  # noqa: F403
from weather.market import exchange_economics
from weather.operations import event_metadata_validation
from weather.runtime_identity import get_runtime_identity

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
):
    now = utc_now(now)
    config = {**DEFAULT_CONFIG, **(config or {})}
    rows = []
    market_summaries = []
    for spec in selected_specs(markets):
        market_config = config_for_date(target_date, spec.id)
        folder = Path(snapshots_root) / market_config.event_slug
        snapshot_rows = load_latest_snapshot_rows(folder)
        current_high_assessment = current_high_probability_summary(
            snapshot_rows,
            normalized_high_for_market(observation_status, spec.id),
        )
        snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
        source_rows = source_status_for_snapshot(folder, snapshot_id)
        book_rows = latest_book_rows(folder, outcomes={"", "yes", "no"})
        clob_feature_rows = latest_clob_feature_rows(
            folder,
            snapshot_id,
            build_if_missing=True,
            max_age_seconds=float(config["max_book_age_seconds"]),
            market_id=spec.id,
        )
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
            )
        )
        market_summaries[-1]["current_high_assessment"] = current_high_assessment
        if snapshot_rows and metadata_gate.get("ok", True):
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
):
    now = utc_now(now)
    target = ensure_date(target_date)
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
    run_folder.mkdir(parents=True, exist_ok=True)
    order_path = run_folder / "orders_long.csv"
    existing_rows = read_order_rows(order_path) if append else []
    if (
        Path(snapshots_root) != Path(DEFAULT_SNAPSHOTS_ROOT)
        and Path(observation_status_path) == Path(DEFAULT_OBSERVATION_STATUS)
    ):
        observation_status = {}
    else:
        observation_status = load_observation_status(observation_status_path, now=now, config=config)
    event_state = _event_metadata_state(event_metadata_validation_path, target, snapshots_root)
    input_rows, market_summaries = discover_inputs(
        target,
        markets=markets,
        snapshots_root=snapshots_root,
        config=config,
        now=now,
        observation_status=observation_status,
        event_metadata_state=event_state,
    )
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
        )
        new_rows.extend(strategy_rows)
        budget_ledger.extend(strategy_ledger)
    all_rows = score_orders([*existing_rows, *new_rows], snapshots_root=snapshots_root, ledger_root=ledger_root, now=now)
    _apply_exchange_economics_fields(new_rows, exchange_fields)
    _apply_exchange_economics_fields(all_rows, exchange_fields)
    write_csv_rows(order_path, ORDER_COLUMNS, all_rows)
    tape_integrity = tape_integrity_summary(order_path, len(all_rows), "orders_long")
    append_jsonl(run_folder / "budget_ledger.jsonl", budget_ledger)
    counterfactual_path = run_folder / COUNTERFACTUAL_TAPE_FILENAME
    counterfactual_ledger_path = run_folder / "counterfactual_budget_ledger.jsonl"
    counterfactual_rows = []
    all_counterfactual_rows = []
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
    if bool_value(config.get("counterfactual_tape_enabled"), True):
        existing_counterfactual_rows = read_order_rows(counterfactual_path) if append else []
        counterfactual_build = build_counterfactual_taker_rows(
            input_rows,
            existing_counterfactual_rows,
            all_rows,
            budget_usdc=budget_usdc,
            run_id=run_id,
            target_date=target,
            now=now,
            config=config,
            strategies=counterfactual_strategy_arg(config),
            experiment_id=experiment_id,
            strategy_registry=strategy_registry,
        )
        counterfactual_rows = counterfactual_build["rows"]
        counterfactual_strategy_ids = [
            item.get("strategy_id")
            for item in counterfactual_build.get("strategy_specs") or []
        ]
        counterfactual_model_variant_manifest = counterfactual_build.get("model_variant_manifest") or counterfactual_model_variant_manifest
        all_counterfactual_rows = score_orders(
            [*existing_counterfactual_rows, *counterfactual_rows],
            snapshots_root=snapshots_root,
            ledger_root=ledger_root,
            now=now,
        )
        _apply_exchange_economics_fields(counterfactual_rows, exchange_fields)
        _apply_exchange_economics_fields(all_counterfactual_rows, exchange_fields)
        all_counterfactual_rows = annotate_counterfactual_rows(
            all_counterfactual_rows,
            real_rows=all_rows,
            strategy_set=",".join(counterfactual_strategy_ids),
        )
        write_csv_rows(counterfactual_path, COUNTERFACTUAL_ORDER_COLUMNS, all_counterfactual_rows)
        counterfactual_tape_integrity = tape_integrity_summary(
            counterfactual_path,
            len(all_counterfactual_rows),
            "counterfactual_orders_long",
        )
        if counterfactual_build.get("ledger"):
            append_jsonl(counterfactual_ledger_path, counterfactual_build["ledger"])
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
    counterfactual_no_side_campaign = no_side_campaign_summary(all_counterfactual_rows)
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
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_date": target.isoformat(),
        "runtime_identity": runtime_identity,
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
        "cumulative_counterfactual_rows": len(all_counterfactual_rows),
        "cumulative_counterfactual_would_buy_count": sum(
            1 for row in all_counterfactual_rows
            if str(row.get("order_status") or "").upper() == "FILLED"
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
        "market_status_counts": dict(sorted(Counter(row.get("status") for row in market_summaries).items())),
        "tape_integrity": tape_integrity,
        "counterfactual_tape_integrity": counterfactual_tape_integrity,
        **zero_trade_diagnosis,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "runtime_identity": runtime_identity,
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
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "remediation_command": "python -m weather.market.market_microstructure ensure",
        },
    }
    write_json(run_folder / "run_summary.json", payload)
    (run_folder / "run_report.md").write_text(render_report(payload), encoding="utf-8")
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
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "runtime_identity": runtime_identity,
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
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "remediation_command": "python -m weather.market.market_microstructure ensure",
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
    results = []
    tick = 0
    with keep_system_awake("weather taker bot loop"):
        while True:
            now = utc_now()
            if until is not None and now > until:
                break
            if max_ticks is not None and tick >= int(max_ticks):
                break
            payload = build_run_once(
                target_date,
                budget_usdc,
                markets=markets,
                now=now,
                append=True,
                **kwargs,
            )
            results.append(payload)
            tick += 1
            if max_ticks is not None and tick >= int(max_ticks):
                break
            time.sleep(float(interval_seconds))
    return results[-1] if results else None


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

    common = {
        "markets": args.markets,
        "runs_root": Path(args.runs_root),
        "snapshots_root": Path(args.snapshots_root),
        "run_id": args.run_id,
        "config": parse_config_overrides(args.config),
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
