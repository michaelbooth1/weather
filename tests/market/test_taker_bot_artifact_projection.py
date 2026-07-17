import csv
import gc
import json
import os
import tracemalloc
from pathlib import Path

import weather.market.taker_profitability_artifact_verification as verification_module
from weather.market.taker_bot_artifact_projection import (
    BAKEOFF_LEDGER_PROJECTION_SCHEMA_VERSION,
    SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION,
    bakeoff_ledger_projection_path,
    build_bakeoff_ledger_projection,
    load_bakeoff_ledger_projection,
    load_settled_finalization_projection,
    read_pretty_json_top_level_schema_version,
    settled_finalization_projection_path,
    write_bakeoff_ledger_projection,
    write_settled_finalization_projection,
)
from weather.market.taker_bot_finalization import next_run_policy_gate


BAKEOFF_SCHEMA_VERSION = "taker_strategy_bakeoff_test_v1"
EXCHANGE_GATE = {"required": False, "ok": True, "status": "PASS"}
FINALIZATION_STRATEGY_FIELDS = {
    "strategy_id",
    "strategy_family",
    "filled_order_count",
    "after_fee_pnl_scored",
    "after_slippage_pnl_scored",
    "live_profitability_evidence_basis",
    "market_benchmark_status",
    "market_smarter_slice_count",
    "market_benchmark_no_trade_net_pnl_usdc",
    "market_benchmark_avoided_loss_usdc",
    "market_benchmark_missed_gain_usdc",
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
}


class _SpilledRecommendations:
    is_spilled_rows = True

    def __len__(self) -> int:
        return 1_000_000

    def __iter__(self):
        raise AssertionError("projection must not iterate spilled recommendations")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _strategy_row() -> dict:
    return {
        "strategy_id": "raw_edge_control",
        "strategy_family": "control",
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
        "exchange_economics_snapshot_id": "snapshot-1",
        "exchange_economics_hash": "a" * 64,
        "exchange_economics_evidence_basis": "exchange_snapshot",
    }


def _bakeoff_payload(*, recommendations=None) -> dict:
    strategy = {
        "strategy_id": "raw_edge_control",
        "strategy_family": "control",
        "filled_order_count": 3,
        "settled_order_count": 2,
        "settled_market_count": 2,
        "unsettled_order_count": 1,
        "unscored_order_count": 0,
        "spent_usdc": 12.5,
        "settlement_pnl_usdc": 1.25,
        "net_pnl_usdc": 1.5,
        "low_price_tail_fill_count": 0,
        "market_benchmark_recommendations": (
            recommendations if recommendations is not None else []
        ),
        "unbounded_diagnostic": "z" * 100_000,
    }
    return {
        "schema_version": BAKEOFF_SCHEMA_VERSION,
        "run_id": "run-a",
        "source_run_id": "source-a",
        "target_date": "2026-07-14",
        "label_summary": {"label_rows": 2, "complete_rows": 2},
        "blockers": [],
        "promotion_gates": [
            {"strategy_id": "raw_edge_control", "status": "PASS"}
        ],
        "pnl": {"by_strategy": [strategy]},
        "profitability_artifact_verification": {"status": "PASS"},
    }


def _settled_payload() -> dict:
    strategy = {
        **_strategy_row(),
        "market_benchmark_recommendations": ["x" * 100_000],
        "unbounded_diagnostic": "y" * 100_000,
    }
    return {
        "schema_version": "taker_settlement_finalization_test_v1",
        "run_id": "run-a",
        "target_date": "2026-07-14",
        "exchange_economics_gate": EXCHANGE_GATE,
        "exchange_economics_status": "PASS",
        "exchange_economics_evidence_basis": "exchange_snapshot",
        "exchange_economics_snapshot_id": "snapshot-1",
        "exchange_economics_hash": "a" * 64,
        "exchange_economics_source_hash": "b" * 64,
        "exchange_economics_verified_at_utc": "2026-07-15T00:00:00+00:00",
        "exchange_economics_effective_date": "2026-07-14",
        "exchange_economics_platform": "polymarket",
        "pnl": {
            "summary": {
                "filled_order_count": 1,
                "after_fee_pnl_scored": True,
                "after_slippage_pnl_scored": True,
                "live_profitability_evidence_basis": (
                    "executable_after_fee_after_slippage"
                ),
                "net_pnl_usdc": 0.9,
            },
            "large_rows": ["q" * 100_000],
        },
        "strategy_summary": {"strategies": [strategy]},
        "counterfactual": {"large_rows": ["r" * 100_000]},
    }


def test_bakeoff_projection_excludes_spilled_recommendations() -> None:
    projection = build_bakeoff_ledger_projection(
        _bakeoff_payload(recommendations=_SpilledRecommendations()),
        source_binding={
            "filename": "strategy_bakeoff.json",
            "size_bytes": 123,
            "mtime_ns": 456,
            "sha256": "0" * 64,
        },
    )

    assert projection["projection_schema_version"] == (
        BAKEOFF_LEDGER_PROJECTION_SCHEMA_VERSION
    )
    strategy = projection["pnl"]["by_strategy"][0]
    assert set(strategy) == {
        "strategy_id",
        "strategy_family",
        "filled_order_count",
        "settled_order_count",
        "settled_market_count",
        "unsettled_order_count",
        "unscored_order_count",
        "spent_usdc",
        "settlement_pnl_usdc",
        "net_pnl_usdc",
        "low_price_tail_fill_count",
    }
    assert "market_benchmark_recommendations" not in strategy
    assert "unbounded_diagnostic" not in strategy
    assert len(json.dumps(projection)) < 4_096


def test_bakeoff_projection_preserves_exchange_gate_policy_semantics() -> None:
    strategy_summary = {
        "strategies": [{
            "strategy_id": "raw_edge_control",
            "net_pnl_usdc": 1.0,
        }],
        "comparison": {},
    }
    run_config = {
        "active_strategy_id": "raw_edge_control",
        "strategy_ids": ["raw_edge_control"],
        "strategies": [{"strategy_id": "raw_edge_control"}],
    }
    for gate in (
        {"status": "PASS", "ok": True, "required": True},
        {"status": "BLOCK", "ok": False, "required": True, "reason": "stale"},
    ):
        payload = {
            **_bakeoff_payload(),
            "exchange_economics_gate": gate,
        }
        projection = build_bakeoff_ledger_projection(
            payload,
            source_binding={
                "filename": "strategy_bakeoff.json",
                "size_bytes": 123,
                "mtime_ns": 456,
                "sha256": "0" * 64,
            },
        )
        assert next_run_policy_gate(
            strategy_summary,
            run_config=run_config,
            bakeoff=projection,
        ) == next_run_policy_gate(
            strategy_summary,
            run_config=run_config,
            bakeoff=payload,
        )


def test_bakeoff_projection_rejects_content_tampering_and_stale_stats(
    tmp_path: Path,
) -> None:
    source = tmp_path / "strategy_bakeoff.json"
    payload = _bakeoff_payload()
    _write_json(source, payload)
    projection_path = write_bakeoff_ledger_projection(source, payload)

    loaded = load_bakeoff_ledger_projection(
        source,
        expected_bakeoff_schema_version=BAKEOFF_SCHEMA_VERSION,
    )
    assert loaded is not None
    assert projection_path == bakeoff_ledger_projection_path(source)

    source_stat = source.stat()
    original = source.read_bytes()
    tampered = original.replace(b'"run-a"', b'"run-b"', 1)
    assert tampered != original
    assert len(tampered) == len(original)
    source.write_bytes(tampered)
    os.utime(
        source,
        ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
    )
    rebound_stat = source.stat()
    assert rebound_stat.st_size == source_stat.st_size
    assert rebound_stat.st_mtime_ns == source_stat.st_mtime_ns
    assert load_bakeoff_ledger_projection(
        source,
        expected_bakeoff_schema_version=BAKEOFF_SCHEMA_VERSION,
    ) is None

    source.write_bytes(original)
    os.utime(
        source,
        ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns + 1_000_000_000),
    )
    assert load_bakeoff_ledger_projection(
        source,
        expected_bakeoff_schema_version=BAKEOFF_SCHEMA_VERSION,
    ) is None


def test_top_level_schema_reader_is_bounded_and_ignores_nested_schema(
    tmp_path: Path,
) -> None:
    source = tmp_path / "large_pretty.json"
    with source.open("wb") as handle:
        handle.write(b"{\n")
        handle.write(b'  "metadata": {\n')
        handle.write(b'    "schema_version": "nested-v1"\n')
        handle.write(b"  },\n")
        handle.write(b'  "oversized": "' + (b"x" * (2 * 1024 * 1024)) + b'",\n')
        handle.write(b'  "schema_version": "root-v1",\n')
        handle.write(b'  "tail": true\n')
        handle.write(b"}\n")

    gc.collect()
    tracemalloc.start()
    try:
        schema_version = read_pretty_json_top_level_schema_version(
            source,
            max_line_bytes=64,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert schema_version == "root-v1"
    assert peak < 512 * 1024


def test_settled_finalization_projection_shape_and_stat_binding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "settled_pnl.json"
    payload = _settled_payload()
    _write_json(source, payload)
    projection_path = write_settled_finalization_projection(source, payload)
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    source_stat = source.stat()

    assert projection_path == settled_finalization_projection_path(source)
    assert projection["projection_schema_version"] == (
        SETTLED_FINALIZATION_PROJECTION_SCHEMA_VERSION
    )
    assert projection["source_artifact_binding"] == {
        "filename": source.name,
        "size_bytes": source_stat.st_size,
        "mtime_ns": source_stat.st_mtime_ns,
    }
    assert projection["summary"] == payload["pnl"]["summary"]
    assert set(projection["strategies"][0]) == FINALIZATION_STRATEGY_FIELDS
    assert "pnl" not in projection
    assert "strategy_summary" not in projection
    assert "counterfactual" not in projection
    assert load_settled_finalization_projection(source) == projection

    invalid_shape = {**projection, "strategies": {}}
    _write_json(projection_path, invalid_shape)
    assert load_settled_finalization_projection(source) is None

    write_settled_finalization_projection(source, payload)
    source.write_text(
        source.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert load_settled_finalization_projection(source) is None


def _write_valid_verifier_inputs(run: Path) -> None:
    order = {
        "order_status": "FILLED",
        "fee_usdc": 0.01,
        "pnl_fee_basis": "after_fee",
        "executable_depth_model_version": "top_of_book_only_v1",
        "executable_depth_mode": "top_of_book",
        "executable_depth_size": 10,
        "expected_profit_after_friction_per_share": 0.02,
        "fee_pnl_usdc": 0.1,
        "slippage_usdc": 0.01,
        "executable_net_pnl_usdc": 0.09,
    }
    with (run / "orders_long.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(order))
        writer.writeheader()
        writer.writerow(order)
    _write_json(run / "strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [_strategy_row()],
        "comparison": {
            "market_benchmark_summary": {
                "market_smarter_slice_count": 0,
                "no_trade_recommendation_count": 1,
                "avoided_loss_usdc": 0.0,
                "missed_gain_usdc": 0.0,
            }
        },
    })


def test_profitability_verifier_prefers_settled_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    _write_valid_verifier_inputs(run)
    settled_path = run / "settled_pnl.json"
    settled_payload = _settled_payload()
    _write_json(settled_path, settled_payload)
    write_settled_finalization_projection(settled_path, settled_payload)
    _write_json(run / "settled_strategy_summary.json", {
        "exchange_economics_gate": EXCHANGE_GATE,
        "strategies": [{
            **_strategy_row(),
            "after_fee_pnl_scored": False,
            "after_slippage_pnl_scored": False,
            "live_profitability_evidence_basis": "paper_no_fee",
        }],
    })

    original_read_small_json = verification_module._read_small_json

    def reject_settled_fallback(path):
        if Path(path).name in {
            "settled_pnl.json",
            "settled_strategy_summary.json",
        }:
            raise AssertionError(f"settled fallback should not be read: {path}")
        return original_read_small_json(path)

    monkeypatch.setattr(
        verification_module,
        "_read_small_json",
        reject_settled_fallback,
    )
    verification = verification_module.verify_taker_profitability_artifacts(run)

    assert verification["status"] == "PASS", verification["checks"]
    assert verification["failed_check_count"] == 0
