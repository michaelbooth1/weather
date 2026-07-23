from __future__ import annotations

import copy

import pytest

from weather.reporting.research.workstation_taker_bakeoff import (
    COUNT_FIELDS,
    SUM_FIELDS,
    _require_safe_output,
    bootstrap_mean_ci,
    build_aggregate,
    create_frozen_manifest,
    summarize_scored_rows,
    validate_manifest,
)


def _daily_row(target_date, strategy_id, side, net, *, fills=1):
    return {
        "target_date": target_date,
        "strategy_id": strategy_id,
        "side": side,
        **{field: (fills if field in {"filled_rows", "settled_filled_rows"} else 0) for field in COUNT_FIELDS},
        **{field: (float(net) if field == "net_after_modeled_costs_usdc" else 0.0) for field in SUM_FIELDS},
        "reason_counts": {},
    }


def test_output_guard_uses_the_explicit_immutable_root(tmp_path):
    data_root = tmp_path / "mirror-without-data-in-name"
    data_root.mkdir()
    with pytest.raises(ValueError, match="read-only root"):
        _require_safe_output(
            data_root / "result.json", read_only_data_root=data_root
        )
    target = _require_safe_output(
        tmp_path / "scratch" / "result.json", read_only_data_root=data_root
    )
    assert target == (tmp_path / "scratch" / "result.json").resolve()


def test_frozen_manifest_rejects_quarantine_duplicates_and_tampering(tmp_path):
    labels = tmp_path / "inputs" / "labels.csv"
    economics = tmp_path / "inputs" / "economics.json"
    run_1 = tmp_path / "inputs" / "2026-07-18" / "taker-a"
    run_2 = tmp_path / "inputs" / "2026-07-19" / "taker-b"
    payload = create_frozen_manifest(
        [run_1, run_2],
        labels_csv=labels,
        exchange_economics_snapshot_path=economics,
        latest_label_date="2026-07-19",
        strategies=["raw_edge_control", "fade_overpriced"],
    )
    assert validate_manifest(payload)["manifest_hash"] == payload["manifest_hash"]

    tampered = copy.deepcopy(payload)
    tampered["config_overrides"]["taker_fee_rate"] = 0.0
    with pytest.raises(ValueError, match="hash"):
        validate_manifest(tampered)

    with pytest.raises(ValueError, match="one run folder per"):
        create_frozen_manifest(
            [run_1, run_1.parent / "taker-other"],
            labels_csv=labels,
            exchange_economics_snapshot_path=economics,
            latest_label_date="2026-07-18",
        )
    with pytest.raises(ValueError, match="Quarantined|quarantined"):
        create_frozen_manifest(
            [tmp_path / "inputs" / "2026-07-19" / "_quarantine" / "taker-b"],
            labels_csv=labels,
            exchange_economics_snapshot_path=economics,
            latest_label_date="2026-07-19",
        )


def test_scored_rows_collapse_to_yes_no_market_day_funnel():
    rows = [
        {
            "strategy_id": "raw_edge_control",
            "market_id": "toronto",
            "side": "YES_BUY",
            "best_ask": 0.2,
            "edge": 0.1,
            "after_cost_ev_per_share": 0.05,
            "action": "NO_TRADE",
            "order_status": "SKIPPED",
            "reason_code": "NO_TRADE_STALE_BOOK",
        },
        {
            "strategy_id": "raw_edge_control",
            "market_id": "toronto",
            "side": "YES_BUY",
            "best_ask": 0.3,
            "edge": 0.2,
            "after_cost_ev_per_share": 0.12,
            "action": "BUY",
            "order_status": "FILLED",
            "reason_code": "BUY_EDGE",
            "pnl_source": "settlement_finalized",
            "settlement_outcome": 1,
            "total_spent_usdc": 2.0,
            "gross_pnl_usdc": 5.0,
            "fee_usdc": 0.1,
            "slippage_usdc": 0.2,
            "net_pnl_usdc": 4.7,
            "pnl_fee_basis": "after_fee",
            "executable_depth_model_version": "top_of_book_plus_1pct_depth_v1",
        },
        {
            "strategy_id": "fade_overpriced",
            "market_id": "toronto",
            "side": "NO_BUY",
            "no_best_ask": 0.4,
            "edge": 0.15,
            "after_cost_ev_per_share": 0.08,
            "action": "BUY",
            "order_status": "FILLED",
            "reason_code": "BUY_EDGE",
            "pnl_source": "settlement",
            "settlement_outcome": 0,
            "total_spent_usdc": 1.1,
            "gross_pnl_usdc": -1.0,
            "fee_usdc": 0.05,
            "slippage_usdc": 0.05,
            "net_pnl_usdc": -1.1,
            "pnl_fee_basis": "after_fee",
            "executable_depth_model_version": "top_of_book_plus_1pct_depth_v1",
            "no_book_source": "no_token_book",
            "real_no_book_depth_eligible": True,
        },
    ]
    payload = summarize_scored_rows(
        rows,
        target_date="2026-07-19",
        strategies=["raw_edge_control", "fade_overpriced"],
        expected_markets=["toronto", "nyc"],
        label_markets=["toronto"],
    )
    index = {
        (row["strategy_id"], row["market_id"], row["side"]): row
        for row in payload["market_day_rows"]
    }
    control_yes = index[("raw_edge_control", "toronto", "YES")]
    assert control_yes["evaluated_rows"] == 2
    assert control_yes["positive_after_cost_ev_rows"] == 2
    assert control_yes["settled_filled_rows"] == 1
    assert control_yes["winning_fills"] == 1
    assert control_yes["net_after_modeled_costs_usdc"] == 4.7
    assert control_yes["modeled_cost_usdc"] == pytest.approx(0.3)
    assert control_yes["reason_counts"] == {"BUY_EDGE": 1, "NO_TRADE_STALE_BOOK": 1}
    assert len(payload["filled_order_rows"]) == 2
    assert {row["side"] for row in payload["filled_order_rows"]} == {"YES_BUY", "NO_BUY"}
    assert payload["filled_order_row_overflow_count"] == 0

    fade_no = index[("fade_overpriced", "toronto", "NO")]
    assert fade_no["real_no_book_rows"] == 1
    assert fade_no["real_no_book_depth_eligible_rows"] == 1
    assert fade_no["losing_fills"] == 1
    assert fade_no["net_after_modeled_costs_usdc"] == -1.1
    assert index[("fade_overpriced", "toronto", "ALL")]["evaluated_rows"] == 1
    assert index[("fade_overpriced", "nyc", "NO")]["evaluated_rows"] == 0
    assert index[("fade_overpriced", "nyc", "NO")]["label_available"] is False


def test_bootstrap_and_fleet_date_aggregation_are_deterministic_and_equal_day_weighted():
    first = bootstrap_mean_ci([1.0, 0.5, 0.0], seed=17, replicates=500)
    second = bootstrap_mean_ci([1.0, 0.5, 0.0], seed=17, replicates=500)
    assert first == second
    assert first["mean"] == 0.5
    assert (first["positive_count"], first["negative_count"], first["tie_count"]) == (2, 0, 1)

    dates = ["2026-07-17", "2026-07-18", "2026-07-19"]
    control_nets = [1.0, -1.0, 0.0]
    variant_nets = [2.0, -0.5, 0.0]
    manifest = {
        "manifest_hash": "fixture",
        "strategies": ["raw_edge_control", "fade_overpriced"],
        "expected_market_ids": ["toronto"],
        "run_folders": [
            {"target_date": target, "run_folder": f"C:/inputs/{target}/run"}
            for target in dates
        ],
    }
    audit = {
        "run_audits": [{
            "target_date": target,
            "status": "PASS",
            "primary_input_eligible": True,
            "observed_market_count": 1,
            "capture_span_minutes": 900,
        } for target in dates],
        "label_support": [{
            "target_date": target,
            "fully_settled_countable_fleet": True,
        } for target in dates],
    }
    day_summaries = []
    for target, control, variant in zip(dates, control_nets, variant_nets):
        rows = []
        for strategy, net in (("raw_edge_control", control), ("fade_overpriced", variant)):
            rows.extend([
                _daily_row(target, strategy, "ALL", net),
                _daily_row(target, strategy, "YES", net),
                _daily_row(target, strategy, "NO", 0.0, fills=0),
            ])
        day_summaries.append({
            "target_date": target,
            "status": "ok",
            "daily_strategy_rows": rows,
            "market_day_rows": [],
            "exchange_economics_gate": {"status": "BLOCK"},
        })
    payload = build_aggregate(
        manifest,
        audit,
        day_summaries,
        seed=23,
        replicates=500,
    )
    own_index = {
        (row["strategy_id"], row["side"]): row
        for row in payload["primary"]["strategy_side_summaries"]
    }
    assert own_index[("fade_overpriced", "ALL")]["equal_fleet_date_mean_net_usdc"] == 0.5
    assert own_index[("fade_overpriced", "ALL")]["net_after_modeled_costs_usdc"] == 1.5
    paired = next(
        row for row in payload["primary"]["paired_vs_control"]
        if row["strategy_id"] == "fade_overpriced" and row["side"] == "ALL"
    )
    assert paired["equal_fleet_date_mean_delta_net_usdc"] == 0.5
    assert (
        paired["positive_delta_date_count"],
        paired["negative_delta_date_count"],
        paired["tie_delta_date_count"],
    ) == (2, 0, 1)
    assert payload["summary"]["primary_date_count"] == 3
    assert payload["summary"]["threshold_or_sizing_sweep_authorized"] is False
    assert payload["summary"]["decision"] == "STOP_NO_POSITIVE_AFTER_COST_EDGE_SURVIVED"
