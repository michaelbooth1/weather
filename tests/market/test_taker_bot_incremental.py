import csv
import io
import tracemalloc
from pathlib import Path
from unittest.mock import patch

from weather.market.taker_bot_incremental import (
    IncrementalTakerStore,
    resource_diagnostics,
)


COLUMNS = [
    "intent_key",
    "strategy_id",
    "order_status",
    "generated_at_utc",
    "captured_at_utc",
    "reason_code",
    "total_spent_usdc",
]


def _row(index, *, filled=False):
    return {
        "intent_key": f"intent-{index:06d}",
        "strategy_id": "control",
        "order_status": "FILLED" if filled else "SKIPPED",
        "generated_at_utc": f"2026-07-13T12:{index % 60:02d}:00+00:00",
        "captured_at_utc": f"2026-07-13T12:{index % 60:02d}:00+00:00",
        "reason_code": "BUY_FILLED" if filled else "NO_TRADE_EDGE_TOO_SMALL",
        "total_spent_usdc": "1.0" if filled else "",
    }


def _csv_line(row, columns=COLUMNS):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=columns,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writerow(row)
    return output.getvalue().encode("utf-8")


def _resource_payload(
    *,
    tick_number,
    observed_at_epoch,
    private_mib,
    pid,
    process_instance_id=None,
):
    budgets = {
        "warmup_ticks": 1,
        "private_memory_max_mib": 1_000,
        "working_set_max_mib": 1_000,
        "post_warmup_private_slope_mib_per_hour": 1_000,
        "ordinary_tick_tape_read_max_bytes": 1_000,
        "ordinary_tick_tape_write_max_bytes": 1_000,
        "process_read_max_bytes_per_tick": 1_000,
        "process_write_max_bytes_per_tick": 1_000,
        "tick_duration_max_seconds": 1,
    }
    identity = {"pid": pid}
    if process_instance_id is not None:
        identity["process_instance_id"] = process_instance_id
    payload = resource_diagnostics(
        {**identity, "process_read_bytes": 0, "process_write_bytes": 0},
        {
            **identity,
            "private_bytes": private_mib * 1024**2,
            "working_set_bytes": 80 * 1024**2,
            "process_read_bytes": 50,
            "process_write_bytes": 50,
        },
        elapsed_seconds=0.25,
        tick_number=tick_number,
        tape_io={"tape_bytes_read": 0, "tape_bytes_written": 0},
        budgets=budgets,
    )
    payload["observed_at_epoch"] = observed_at_epoch
    return payload


def test_growing_tape_keeps_materialized_state_and_per_tick_io_bounded(tmp_path):
    tape = tmp_path / "orders_long.csv"
    store = IncrementalTakerStore(tmp_path)
    store.prepare_tape("orders", tape, COLUMNS)

    tracemalloc.start()
    first_window_peak = 0
    second_window_peak = 0
    for index in range(600):
        tracemalloc.reset_peak()
        result = store.append_rows(
            "orders",
            tape,
            COLUMNS,
            [_row(index, filled=index in {0, 300})],
        )
        _current, peak = tracemalloc.get_traced_memory()
        if index < 300:
            first_window_peak = max(first_window_peak, peak)
        else:
            second_window_peak = max(second_window_peak, peak)
        assert result["bytes_written"] < 1024
    tracemalloc.stop()

    stats = store.tape_stats("orders")
    diagnostics = store.io_diagnostics()
    assert stats["row_count"] == 600
    assert len(store.filled_rows("orders")) == 2
    assert len(store.representative_rows("orders")) == 1
    assert diagnostics["tape_bytes_read"] == 0
    assert diagnostics["ordinary_full_history_reads"] == 0
    assert diagnostics["ordinary_full_history_rewrites"] == 0
    # Later ticks do not materialize the 600-row tape.  Allow allocator noise,
    # but reject a peak that scales with the first 300 persisted rows.
    assert second_window_peak <= first_window_peak + 512 * 1024
    store.close()


def test_restart_uses_checkpoint_without_reading_or_rescoring_history(tmp_path):
    tape = tmp_path / "orders_long.csv"
    with IncrementalTakerStore(tmp_path) as store:
        store.prepare_tape("orders", tape, COLUMNS)
        for index in range(100):
            store.append_rows("orders", tape, COLUMNS, [_row(index, filled=index == 0)])
        original_size = tape.stat().st_size

    with IncrementalTakerStore(tmp_path) as restarted:
        restarted.prepare_tape("orders", tape, COLUMNS)
        diagnostics = restarted.io_diagnostics()
        assert restarted.tape_stats("orders")["row_count"] == 100
        assert restarted.has_intent("orders", "intent-000099")
        assert len(restarted.filled_rows("orders")) == 1
        assert diagnostics["tape_bytes_read"] == 0
        assert diagnostics["recovered_row_count"] == 0
        assert tape.stat().st_size == original_size


def test_restart_recovers_only_uncheckpointed_append_tail(tmp_path):
    tape = tmp_path / "orders_long.csv"
    with IncrementalTakerStore(tmp_path) as store:
        store.prepare_tape("orders", tape, COLUMNS)
        store.append_rows("orders", tape, COLUMNS, [_row(1)])
        checkpointed_size = tape.stat().st_size

    tail = _csv_line(_row(2))
    with tape.open("ab") as handle:
        handle.write(tail)

    with IncrementalTakerStore(tmp_path) as restarted:
        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("tail recovery materialized the complete tape"),
        ):
            restarted.prepare_tape("orders", tape, COLUMNS)
        diagnostics = restarted.io_diagnostics()
        assert restarted.tape_stats("orders")["row_count"] == 2
        assert restarted.has_intent("orders", "intent-000002")
        assert diagnostics["recovery_mode"] is True
        assert diagnostics["recovery_kind"] == "uncheckpointed_tail"
        assert diagnostics["recovered_row_count"] == 1
        assert diagnostics["tape_bytes_read"] == len(tail)
        assert diagnostics["tape_bytes_read"] < checkpointed_size


def test_legacy_bootstrap_streams_tape_without_materializing_complete_bytes(tmp_path):
    tape = tmp_path / "orders_long.csv"
    with tape.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for index in range(200):
            writer.writerow(_row(index, filled=index == 0))
    tape_size = tape.stat().st_size

    with IncrementalTakerStore(tmp_path) as store:
        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("legacy bootstrap materialized the complete tape"),
        ):
            store.prepare_tape("orders", tape, COLUMNS)
        diagnostics = store.io_diagnostics()
        assert store.tape_stats("orders")["row_count"] == 200
        assert len(store.filled_rows("orders")) == 1
        assert diagnostics["recovery_kind"] == "legacy_full_stream"
        assert diagnostics["tape_bytes_read"] == tape_size


def test_existing_checkpoint_streams_one_time_refreshable_benchmark_reindex(tmp_path):
    tape = tmp_path / "orders_long.csv"
    columns = [
        *COLUMNS,
        "target_date",
        "market_id",
        "snapshot_id",
        "event_slug",
        "capture_hour_local",
        "taker_side",
        "no_book_source",
        "no_book_fresh",
        "real_no_book_depth_eligible",
    ]
    row = {
        **_row(1),
        "target_date": "2026-07-13",
        "market_id": "market-a",
        "snapshot_id": "snapshot-001",
        "event_slug": "event-a",
        "capture_hour_local": "09",
        "taker_side": "NO",
        "no_book_source": "no_token_book",
        "no_book_fresh": "True",
        "real_no_book_depth_eligible": "True",
    }
    with IncrementalTakerStore(tmp_path) as store:
        store.prepare_tape("orders", tape, columns)
        store.append_rows("orders", tape, columns, [row])
        store.connection.execute("DELETE FROM benchmark_groups")
        store.connection.execute(
            "DELETE FROM metadata WHERE key = 'derived_index_version'"
        )
        store.connection.execute(
            "DELETE FROM metadata WHERE key = 'derived_reindex_required_kinds'"
        )
        store.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            ("benchmark:orders", '{"summary":{"opportunity_count":999}}'),
        )
        store.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            (
                "no_side:orders",
                '{"overall":{"no_side_row_count":1},"by_strategy":{}}',
            ),
        )
        store.connection.commit()

    tail_row = {
        **row,
        "intent_key": "intent-000002",
        "generated_at_utc": "2026-07-13T12:10:00+00:00",
        "captured_at_utc": "2026-07-13T12:10:00+00:00",
        "market_id": "market-b",
        "snapshot_id": "snapshot-002",
        "event_slug": "event-b",
        "capture_hour_local": "10",
    }
    tail = _csv_line(tail_row, columns)
    with tape.open("ab") as handle:
        handle.write(tail)

    with IncrementalTakerStore(tmp_path) as migrated:
        migrated.prepare_tape("orders", tape, columns)
        pending = migrated.pending_benchmark_groups("orders")
        diagnostics = migrated.io_diagnostics()
        no_side = migrated.no_side_summary("orders")

        assert migrated.benchmark("orders") == {}
        assert migrated.tape_stats("orders")["row_count"] == 2
        assert migrated.benchmark_pending_count("orders") == 2
        assert len(pending) == 2
        assert pending[0]["rows"][0]["intent_key"] == "intent-000001"
        assert no_side["no_side_row_count"] == 2
        assert [item["value"] for item in no_side["by_market"]] == [
            "market-a",
            "market-b",
        ]
        assert [item["value"] for item in no_side["by_hour"]] == ["09", "10"]
        assert diagnostics["recovery_mode"] is True
        assert diagnostics["recovery_kind"] == (
            "uncheckpointed_tail_then_derived_index_migration"
        )
        assert diagnostics["orders_derived_reindexed_row_count"] == 2
        assert diagnostics["recovered_row_count"] == 1
        assert diagnostics["tape_bytes_read"] == tape.stat().st_size + len(tail)


def test_resource_budgets_are_explicit_advisory_and_slope_is_restart_safe(tmp_path):
    budgets = {
        "warmup_ticks": 1,
        "private_memory_max_mib": 100,
        "working_set_max_mib": 100,
        "post_warmup_private_slope_mib_per_hour": 10,
        "ordinary_tick_tape_read_max_bytes": 100,
        "ordinary_tick_tape_write_max_bytes": 100,
        "process_read_max_bytes_per_tick": 100,
        "process_write_max_bytes_per_tick": 100,
        "tick_duration_max_seconds": 1,
    }
    first = resource_diagnostics(
        {"process_read_bytes": 0, "process_write_bytes": 0},
        {
            "private_bytes": 90 * 1024**2,
            "working_set_bytes": 80 * 1024**2,
            "process_read_bytes": 50,
            "process_write_bytes": 50,
        },
        elapsed_seconds=0.5,
        tick_number=2,
        tape_io={"tape_bytes_read": 50, "tape_bytes_written": 50},
        budgets=budgets,
    )
    first["observed_at_epoch"] = 1_000.0
    with IncrementalTakerStore(tmp_path) as store:
        first = store.record_resource_diagnostics(first)

    second = resource_diagnostics(
        {"process_read_bytes": 0, "process_write_bytes": 0},
        {
            "private_bytes": 110 * 1024**2,
            "working_set_bytes": 80 * 1024**2,
            "process_read_bytes": 150,
            "process_write_bytes": 50,
        },
        elapsed_seconds=0.5,
        tick_number=3,
        tape_io={"tape_bytes_read": 50, "tape_bytes_written": 150},
        budgets=budgets,
    )
    second["observed_at_epoch"] = 4_600.0
    with IncrementalTakerStore(tmp_path) as restarted:
        second = restarted.record_resource_diagnostics(second)
        persisted_sample_count = restarted.resource_sample_count()

    assert first["status"] == "PASS"
    assert second["status"] == "WARN"
    assert second["advisory_only"] is True
    assert set(second["failed_budgets"]) == {
        "private_memory",
        "tape_write",
        "process_read",
        "post_warmup_private_slope",
    }
    assert second["post_warmup_private_slope_mib_per_hour"] == 20.0
    assert second["resource_history"]["sample_count"] == 2
    assert persisted_sample_count == 2


def test_resource_slope_resets_for_new_process_identity_or_pid(tmp_path):
    identity_cases = [
        (
            tmp_path / "instance-id",
            {"pid": 101, "process_instance_id": "process-a"},
            {"pid": 101, "process_instance_id": "process-b"},
        ),
        (
            tmp_path / "pid-fallback",
            {"pid": 201},
            {"pid": 202},
        ),
        (
            tmp_path / "fork-inherited-instance-id",
            {"pid": 301, "process_instance_id": "inherited-process-id"},
            {"pid": 302, "process_instance_id": "inherited-process-id"},
        ),
    ]

    for run_folder, original_identity, restarted_identity in identity_cases:
        with IncrementalTakerStore(run_folder) as store:
            first = store.record_resource_diagnostics(
                _resource_payload(
                    tick_number=1,
                    observed_at_epoch=1_000.0,
                    private_mib=80,
                    **original_identity,
                )
            )
            baseline = store.record_resource_diagnostics(
                _resource_payload(
                    tick_number=2,
                    observed_at_epoch=1_100.0,
                    private_mib=90,
                    **original_identity,
                )
            )
            sloped = store.record_resource_diagnostics(
                _resource_payload(
                    tick_number=3,
                    observed_at_epoch=4_700.0,
                    private_mib=110,
                    **original_identity,
                )
            )
            restarted = store.record_resource_diagnostics(
                _resource_payload(
                    tick_number=4,
                    observed_at_epoch=8_300.0,
                    private_mib=300,
                    **restarted_identity,
                )
            )

            assert first["warmup"] is True
            assert baseline["resource_history"]["baseline_epoch"] == 1_100.0
            assert sloped["post_warmup_private_slope_mib_per_hour"] == 20.0
            assert restarted["warmup"] is True
            assert "post_warmup_private_slope_mib_per_hour" not in restarted
            assert restarted["resource_history"]["baseline_epoch"] is None
            assert restarted["resource_history"]["last_epoch"] is None
            assert restarted["resource_history"]["sample_count"] == 4
            assert restarted["resource_history"]["process_sample_count"] == 1
            assert restarted["resource_history"]["process_restart_count"] == 1
            assert store.resource_sample_count() == 4


def test_no_side_summary_preserves_canonical_dimensions_and_pnl_gate_fields(tmp_path):
    tape = tmp_path / "orders.csv"
    filled = {
        **_row(1, filled=True),
        "strategy_id": "control",
        "strategy_family": "raw_edge",
        "market_id": "market-a",
        "capture_hour_local": 9,
        "taker_side": "NO",
        "no_book_source": "no_token_book",
        "no_book_fresh": True,
        "real_no_book_depth_eligible": True,
    }
    skipped = {
        **_row(2),
        "strategy_id": "challenger",
        "strategy_family": "fade",
        "market_id": "market-b",
        "capture_hour_local": 10,
        "taker_side": "NO",
        "no_book_source": "synthetic_yes_complement",
        "no_book_fresh": True,
        "real_no_book_depth_eligible": False,
    }
    scored_filled = {
        **filled,
        "pnl_source": "settlement",
        "settlement_outcome": 1.0,
        "net_pnl_usdc": 2.0,
    }
    pnl_payload = {
        "by_strategy": [
            {
                "strategy_id": "control",
                "net_pnl_usdc": 2.0,
                "market_benchmark_market_top_net_pnl_usdc": 1.25,
                "settlement_promotion_gate_status": "PASS",
                "settlement_promotion_failed_gates": [],
            },
            {
                "strategy_id": "challenger",
                "net_pnl_usdc": 0.0,
                "market_benchmark_market_top_net_pnl_usdc": 0.0,
                "settlement_promotion_gate_status": "BLOCK_NO_SETTLED_TRADES",
                "settlement_promotion_failed_gates": ["settled_trades"],
            },
        ]
    }

    with IncrementalTakerStore(tmp_path) as store:
        store.prepare_tape("orders", tape, COLUMNS)
        store.append_rows("orders", tape, COLUMNS, [filled, skipped])
        summary = store.no_side_summary(
            "orders",
            scored_filled_rows=[scored_filled],
            pnl_payload=pnl_payload,
        )

    assert [row["strategy_id"] for row in summary["by_strategy"]] == [
        "challenger",
        "control",
    ]
    assert [row["value"] for row in summary["by_market"]] == ["market-a", "market-b"]
    assert [row["value"] for row in summary["by_hour"]] == ["09", "10"]
    assert summary["slices"] == {
        "by_market": summary["by_market"],
        "by_hour": summary["by_hour"],
    }

    control = next(row for row in summary["by_strategy"] if row["strategy_id"] == "control")
    assert control["strategy_family"] == "raw_edge"
    assert control["strategy_market_top_net_pnl_usdc"] == 1.25
    assert control["strategy_delta_vs_market_top_net_pnl_usdc"] == 0.75
    assert control["settlement_promotion_gate_status"] == "PASS"
    assert control["settlement_promotion_failed_gates"] == []
    assert control["settled_countable_no_side_would_buy_count"] == 1
    assert control["net_pnl_usdc"] == 2.0

    challenger = next(
        row for row in summary["by_strategy"] if row["strategy_id"] == "challenger"
    )
    assert challenger["settlement_promotion_gate_status"] == "BLOCK_NO_SETTLED_TRADES"
    assert challenger["settlement_promotion_failed_gates"] == ["settled_trades"]


def test_recovered_tail_keeps_pending_benchmark_group_until_idempotent_apply(tmp_path):
    tape = tmp_path / "orders.csv"
    benchmark_columns = [
        *COLUMNS,
        "target_date",
        "market_id",
        "snapshot_id",
        "event_slug",
    ]
    recovered_row = {
        **_row(1),
        "target_date": "2026-07-13",
        "market_id": "market-a",
        "snapshot_id": "snapshot-001",
        "event_slug": "event-a",
    }
    with IncrementalTakerStore(tmp_path) as store:
        store.prepare_tape("orders", tape, benchmark_columns)

    tail = _csv_line(recovered_row, benchmark_columns)
    with tape.open("ab") as handle:
        handle.write(tail)

    with IncrementalTakerStore(tmp_path) as recovered:
        recovered.prepare_tape("orders", tape, benchmark_columns)
        pending = recovered.pending_benchmark_groups("orders")
        assert recovered.io_diagnostics()["recovered_row_count"] == 1
        assert recovered.benchmark_pending_count("orders") == 1
        assert len(pending) == 1
        assert pending[0]["rows"][0]["snapshot_id"] == "snapshot-001"

    benchmark_payload = {
        "schema_version": "test_benchmark_v0.1",
        "summary": {
            "opportunity_count": 1,
            "market_smarter_slice_count": 0,
            "no_trade_recommendation_count": 0,
            "traded_pnl_usdc": 0.0,
            "avoided_loss_usdc": 0.0,
            "missed_gain_usdc": 0.0,
        },
        "by_strategy": [
            {
                "strategy_id": "control",
                "opportunity_count": 1,
                "settled_opportunity_count": 0,
                "market_smarter_slice_count": 0,
                "model_beats_market_count": 0,
                "model_beats_no_trade_count": 0,
                "traded_pnl_usdc": 0.0,
                "model_top_net_pnl_usdc": 0.0,
                "market_top_net_pnl_usdc": 0.0,
                "no_trade_net_pnl_usdc": 0.0,
                "avoided_loss_usdc": 0.0,
                "missed_gain_usdc": 0.0,
                "recommendations": [],
            }
        ],
        "slices": [
            {
                "strategy_id": "control",
                "target_date": "2026-07-13",
                "market_id": "market-a",
                "snapshot_id": "snapshot-001",
            }
        ],
    }

    with IncrementalTakerStore(tmp_path) as restarted:
        restarted.prepare_tape("orders", tape, benchmark_columns)
        pending = restarted.pending_benchmark_groups("orders")
        assert len(pending) == 1
        scored_group = {**pending[0], "payload": benchmark_payload}
        assert restarted.apply_benchmark_groups("orders", [scored_group]) == 1
        assert restarted.benchmark_pending_count("orders") == 0
        assert restarted.benchmark("orders")["summary"]["opportunity_count"] == 1

    with IncrementalTakerStore(tmp_path) as restarted_again:
        restarted_again.prepare_tape("orders", tape, benchmark_columns)
        assert restarted_again.apply_benchmark_groups("orders", [scored_group]) == 0
        assert restarted_again.benchmark_pending_count("orders") == 0
        assert restarted_again.benchmark("orders")["summary"]["opportunity_count"] == 1
