"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_finalization import *  # noqa: F403
from weather.runtime_identity import get_runtime_identity

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def discover_inputs(
    target_date,
    markets=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    config=None,
    now=None,
    observation_status=None,
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
        market_summaries.append(
            preflight_summary_for_market(
                spec,
                target_date,
                folder,
                snapshot_rows,
                source_rows,
                book_rows,
                clob_feature_rows,
                current_high_assessment=current_high_assessment,
            )
        )
        market_summaries[-1]["current_high_assessment"] = current_high_assessment
        if snapshot_rows:
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
        "executable_depth_config": {
            "executable_depth_model": config.get("executable_depth_model"),
            "executable_depth_slippage_bps": config.get("executable_depth_slippage_bps"),
            "executable_depth_haircut": config.get("executable_depth_haircut"),
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
        },
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
):
    now = utc_now(now)
    target = ensure_date(target_date)
    config = enrich_config_with_performance_gates({**DEFAULT_CONFIG, **(config or {})}, target)
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
    input_rows, market_summaries = discover_inputs(
        target,
        markets=markets,
        snapshots_root=snapshots_root,
        config=config,
        now=now,
        observation_status=observation_status,
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
    write_csv_rows(order_path, ORDER_COLUMNS, all_rows)
    tape_integrity = tape_integrity_summary(order_path, len(all_rows), "orders_long")
    append_jsonl(run_folder / "budget_ledger.jsonl", budget_ledger)
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
    )
    pnl_payload = build_pnl_payload(
        all_rows,
        total_budget_usdc,
        run_id,
        target,
        now=now,
        policy_config=run_config.get("policy_config") or config,
    )
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
        "latest_tick_rows": len(new_rows),
        "latest_tick_filled_orders": len(latest_filled),
        "latest_tick_spent_usdc": sum_field(latest_filled, "total_spent_usdc"),
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
        "budget_ledger_path": str(run_folder / "budget_ledger.jsonl"),
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
        "latest_orders": new_rows,
        "tape_integrity": tape_integrity,
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
