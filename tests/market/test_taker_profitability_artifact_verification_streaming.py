import csv
import gc
import json
import os
import tracemalloc
from pathlib import Path

import weather.market.taker_profitability_artifact_verification as verification_module
from weather.market.taker_profitability_artifact_verification import (
    FILLED_ORDER_FIELDS,
    ORDER_OPPORTUNITY_FIELDS,
    verify_taker_profitability_artifacts,
)


EXCHANGE_GATE = {"required": False, "ok": True, "status": "PASS"}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _strategy_row() -> dict:
    return {
        "strategy_id": "raw_edge_control",
        "filled_order_count": 1,
        "after_fee_pnl_scored": True,
        "after_slippage_pnl_scored": True,
        "live_profitability_evidence_basis": (
            "executable_after_fee_after_slippage"
        ),
        "market_benchmark_status": "PASS",
        "market_smarter_slice_count": 0,
        "market_benchmark_no_trade_net_pnl_usdc": 0.0,
        "market_benchmark_avoided_loss_usdc": 0.0,
        "market_benchmark_missed_gain_usdc": 0.0,
    }


def _comparison() -> dict:
    return {
        "market_benchmark_summary": {
            "market_smarter_slice_count": 0,
            "no_trade_recommendation_count": 1,
            "avoided_loss_usdc": 0.0,
            "missed_gain_usdc": 0.0,
        }
    }


def _write_equivalent_profitability_payloads(run: Path) -> None:
    strategy_row = _strategy_row()
    comparison = _comparison()
    _write_json(run / "daily_pnl.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "by_strategy": [strategy_row],
        "strategy_comparison": comparison,
    })
    _write_json(run / "strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [strategy_row],
        "comparison": comparison,
    })
    _write_json(run / "settled_pnl.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "pnl": {
            "summary": {
                "filled_order_count": 1,
                "after_fee_pnl_scored": True,
                "after_slippage_pnl_scored": True,
                "live_profitability_evidence_basis": (
                    "executable_after_fee_after_slippage"
                ),
            },
            "by_strategy": [strategy_row],
        },
    })
    _write_json(run / "settled_strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [strategy_row],
        "comparison": comparison,
    })


def test_equivalent_sidecars_do_not_change_streamed_field_checks(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    _write_csv(
        run / "orders_long.csv",
        [
            "order_status",
            "fee_usdc",
            "pnl_fee_basis",
            "executable_depth_model_version",
            "executable_depth_size",
            "expected_profit_after_friction_per_share",
            "fee_pnl_usdc",
            "slippage_usdc",
        ],
        [
            {
                "order_status": "FILLED",
                "fee_usdc": 0.01,
                "pnl_fee_basis": "after_fee",
                "executable_depth_model_version": "top_of_book_only_v1",
                "executable_depth_size": "",
                "expected_profit_after_friction_per_share": 0.02,
                "fee_pnl_usdc": 0.10,
                "slippage_usdc": "",
            },
            {
                "order_status": "FILLED",
                "fee_usdc": 0.02,
                "pnl_fee_basis": "after_fee",
                "executable_depth_model_version": "top_of_book_only_v1",
                "executable_depth_size": "",
                "expected_profit_after_friction_per_share": 0.03,
                "fee_pnl_usdc": 0.20,
                "slippage_usdc": "",
            },
            {
                "order_status": "SKIPPED",
                "fee_usdc": 0.0,
                "pnl_fee_basis": "paper_no_fee",
                "executable_depth_model_version": "top_of_book_only_v1",
                "executable_depth_size": 10,
                "expected_profit_after_friction_per_share": 0.01,
                "fee_pnl_usdc": "",
                "slippage_usdc": 0.1,
            },
        ],
    )
    _write_equivalent_profitability_payloads(run)

    compact_result = verify_taker_profitability_artifacts(run)

    (run / "strategy_summary.json").unlink()
    (run / "settled_strategy_summary.json").unlink()
    fallback_result = verify_taker_profitability_artifacts(run)

    assert compact_result == fallback_result
    assert compact_result["status"] == "BLOCK"
    assert compact_result["failed_check_count"] == 4
    assert [
        check["code"]
        for check in compact_result["checks"]
        if check["status"] == "FAIL"
    ] == [
        "orders_executable_depth_mode_missing",
        "orders_executable_depth_size_null_only",
        "orders_slippage_usdc_null_only",
        "orders_executable_net_pnl_usdc_missing",
    ]


def _write_large_valid_tape(path: Path, row_count: int) -> None:
    fieldnames = [
        "order_status",
        *ORDER_OPPORTUNITY_FIELDS,
        *FILLED_ORDER_FIELDS,
        "ignored_payload",
    ]
    row = {
        "order_status": "FILLED",
        "fee_usdc": 0.01,
        "pnl_fee_basis": "after_fee",
        "executable_depth_model_version": "top_of_book_only_v1",
        "executable_depth_mode": "top_of_book",
        "executable_depth_size": 10,
        "expected_profit_after_friction_per_share": 0.02,
        "fee_pnl_usdc": 0.10,
        "slippage_usdc": 0.01,
        "executable_net_pnl_usdc": 0.09,
        "ignored_payload": "x" * 256,
    }
    _write_csv(path, fieldnames, (row for _index in range(row_count)))


def _semantic_result(result: dict) -> dict:
    return {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "exchange_economics_gate": result["exchange_economics_gate"],
        "check_count": result["check_count"],
        "failed_check_count": result["failed_check_count"],
        "checks": [
            (check["code"], check["status"])
            for check in result["checks"]
        ],
    }


def _measured_peak(tmp_path: Path, row_count: int) -> tuple[int, dict]:
    run = tmp_path / f"run-{row_count}"
    run.mkdir()
    _write_large_valid_tape(run / "orders_long.csv", row_count)
    _write_json(run / "strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [_strategy_row()],
        "comparison": _comparison(),
    })

    gc.collect()
    tracemalloc.start()
    try:
        result = verify_taker_profitability_artifacts(run)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, _semantic_result(result)


def test_streamed_order_verification_peak_memory_stays_flat_as_tape_grows(
    tmp_path: Path,
) -> None:
    few_peak, few_result = _measured_peak(tmp_path, 5_000)
    many_peak, many_result = _measured_peak(tmp_path, 50_000)

    assert few_result == many_result
    assert many_result["status"] == "PASS"
    assert many_result["failed_check_count"] == 0
    assert many_peak <= few_peak + 2 * 1024 * 1024


def test_oversized_daily_rejects_older_unbound_strategy_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = tmp_path / "stale-summary"
    run.mkdir()
    _write_large_valid_tape(run / "orders_long.csv", 1)
    summary_path = run / "strategy_summary.json"
    daily_path = run / "daily_pnl.json"
    _write_json(summary_path, {
        "schema_version": "taker_strategy_report_v0.1",
        "run_id": "run-1",
        "target_date": "2026-07-14",
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [_strategy_row()],
        "comparison": _comparison(),
    })
    daily_path.write_text(json.dumps({
        "run_id": "run-1",
        "target_date": "2026-07-14",
        "exchange_economics_gate": EXCHANGE_GATE,
        "by_strategy": [{"strategy_id": "raw_edge_control"}],
        "strategy_comparison": {},
        "padding": "x" * 2_000,
    }, indent=2, sort_keys=True), encoding="utf-8")
    os.utime(summary_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(daily_path, ns=(2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(
        verification_module,
        "DEFAULT_PROJECTION_MAX_BYTES",
        512,
    )

    result = verify_taker_profitability_artifacts(run)

    assert result["status"] == "BLOCK"
    assert any(
        row["code"] == "strategy_rows_missing" and row["status"] == "FAIL"
        for row in result["checks"]
    )


def test_orphan_settled_summary_is_not_finalization_evidence(
    tmp_path: Path,
) -> None:
    run = tmp_path / "orphan-finalization-summary"
    run.mkdir()
    _write_large_valid_tape(run / "orders_long.csv", 1)
    _write_json(run / "strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [_strategy_row()],
        "comparison": _comparison(),
    })
    _write_json(run / "settled_strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [_strategy_row()],
    })

    result = verify_taker_profitability_artifacts(run)

    assert result["status"] == "PASS"
    assert any(
        row["code"] == "finalization_payload_absent"
        and row["status"] == "SKIP"
        for row in result["checks"]
    )
