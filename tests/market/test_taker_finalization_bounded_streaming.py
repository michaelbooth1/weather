import gc
import json
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

from tests.market.test_taker_bot import order_row, write_labels, write_taker_run
from weather.market.taker_bot import (
    DEFAULT_BAKEOFF_STRATEGIES,
    finalization_watchdog,
    finalize_taker_run,
    run_taker_strategy_bakeoff,
)
from weather.market.taker_bot_aggregation import TakerRunAggregation
from weather.market.taker_bot_scoring import market_benchmark_scoreboard


TARGET_DATE = "2026-06-19"
FINALIZED_AT = "2026-06-20T12:00:00+00:00"
EVENTS = {
    "atlanta": "highest-temperature-in-atlanta-on-june-19-2026",
    "miami": "highest-temperature-in-miami-on-june-19-2026",
}
INPUT_ARTIFACTS = {
    "daily_pnl.json",
    "orders_long.csv",
    "run_summary.json",
}


def _fixed_disk_usage(_path):
    return SimpleNamespace(free=10_000_000_000)


def _source_rows(*, run_id="fixture"):
    rows = []
    for index, (market_id, event_slug) in enumerate(EVENTS.items()):
        band = 88 + index
        row = order_row(
            market_id,
            event_slug,
            f"{band}-{band + 1} F",
            band,
            band + 1,
            fill_size=2 + index,
            fill_notional=1 + index,
        )
        row.update({
            "run_id": run_id,
            "snapshot_id": f"snapshot-{index}",
            "captured_at_utc": f"2026-06-20T03:4{index}:00+00:00",
            "generated_at_utc": f"2026-06-20T03:4{index}:12+00:00",
            # Legacy tapes can have this column present but blank. The spill
            # metadata must group it exactly like strategy_id_for_row does.
            "strategy_id": "",
        })
        rows.append(row)
    return rows


def _write_fixture(root, *, run_count):
    for index in range(run_count):
        run_id = f"run-{index:03d}"
        write_taker_run(
            root,
            run_id,
            _source_rows(run_id=run_id),
            reported_net=0,
            reported_mtm=0,
            reported_unsettled=len(EVENTS),
        )
    labels = root / "market_day_labels.csv"
    write_labels(labels, [
        {
            "event_slug": EVENTS["atlanta"],
            "market_id": "atlanta",
            "target_date": TARGET_DATE,
            "settlement_bucket": 88,
            "winning_band": "88-89 F",
            "quality_grade": "complete",
        },
        {
            "event_slug": EVENTS["miami"],
            "market_id": "miami",
            "target_date": TARGET_DATE,
            # Exercise both winning and losing settlement rows.
            "settlement_bucket": 90,
            "winning_band": "90-91 F",
            "quality_grade": "complete",
        },
    ])
    return labels


def _normalize(value, root, *, parent_key=None):
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if parent_key == "source_artifact_binding" and key in {"mtime_ns", "sha256"}:
                normalized[key] = f"<{key}>"
            else:
                normalized[key] = _normalize(item, root, parent_key=key)
        return normalized
    if isinstance(value, list):
        return [_normalize(item, root, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item, root, parent_key=parent_key) for item in value)
    if isinstance(value, str):
        return value.replace(str(root), "<ROOT>")
    return value


def _produced_artifacts(run_folder, root):
    artifacts = {}
    for path in sorted(item for item in run_folder.iterdir() if item.is_file()):
        if path.name in INPUT_ARTIFACTS:
            continue
        if path.suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            artifacts[path.name] = _normalize(value, root)
        elif path.suffix == ".csv":
            artifacts[path.name] = path.read_bytes()
        else:
            artifacts[path.name] = path.read_text(encoding="utf-8").replace(
                str(root),
                "<ROOT>",
            )
    return artifacts


def _run_pipeline(root, labels, *, stream_tapes):
    results = {}
    for run_folder in sorted((root / "taker_runs" / TARGET_DATE).iterdir()):
        bakeoff = run_taker_strategy_bakeoff(
            run_folder,
            labels_csv=labels,
            now=FINALIZED_AT,
            min_free_bytes=0,
            disk_usage_fn=_fixed_disk_usage,
            stream_tapes=stream_tapes,
            materialize_output_rows=True,
        )
        finalized = finalize_taker_run(
            run_folder,
            labels_csv=labels,
            now=FINALIZED_AT,
            min_free_bytes=0,
            disk_usage_fn=_fixed_disk_usage,
            stream_tapes=stream_tapes,
            materialize_output_rows=True,
        )
        results[run_folder.name] = {
            "bakeoff": _normalize(bakeoff, root),
            "finalized": _normalize(finalized, root),
            "artifacts": _produced_artifacts(run_folder, root),
        }
    return results


def test_streaming_matches_materialized_for_multi_run_finalization_and_bakeoff(tmp_path):
    # Equal-length directory names keep binding sizes comparable while the
    # normalizer replaces only paths and the projection's mtime/hash receipt.
    materialized_root = tmp_path / "materialized"
    streaming_root = tmp_path / "streaming___"
    materialized_labels = _write_fixture(materialized_root, run_count=2)
    streaming_labels = _write_fixture(streaming_root, run_count=2)

    materialized = _run_pipeline(
        materialized_root,
        materialized_labels,
        stream_tapes=False,
    )
    streaming = _run_pipeline(
        streaming_root,
        streaming_labels,
        stream_tapes=True,
    )

    assert materialized.keys() == streaming.keys()
    for run_id in materialized:
        assert materialized[run_id]["bakeoff"]["summary"]["strategy_count"] == 7
        assert materialized[run_id]["bakeoff"]["strategy_ids"] == (
            DEFAULT_BAKEOFF_STRATEGIES.split(",")
        )
        assert materialized[run_id]["bakeoff"] == streaming[run_id]["bakeoff"]
        assert materialized[run_id]["finalized"] == streaming[run_id]["finalized"]
        assert materialized[run_id]["artifacts"] == streaming[run_id]["artifacts"]
        assert {
            "settled_orders_long.csv",
            "settled_pnl.json",
            "settled_report.md",
            "strategy_bakeoff.json",
            "strategy_bakeoff.md",
            "strategy_bakeoff_ledger_projection.json",
        }.issubset(materialized[run_id]["artifacts"])


def test_spilled_benchmark_groups_blank_legacy_strategy_like_materialized_rows():
    rows = _source_rows()
    for index, row in enumerate(rows):
        row.update({
            "settlement_outcome": str(1 - index),
            "pnl_source": "settlement_finalized",
            "net_pnl_usdc": "1" if index == 0 else "-1",
        })
    materialized = market_benchmark_scoreboard(rows)

    with TakerRunAggregation() as aggregation:
        aggregation.scored_rows.extend(rows)
        aggregation.commit()
        spilled = aggregation.materialize(
            market_benchmark_scoreboard(aggregation.scored_rows)
        )
        repeated = aggregation.materialize(
            market_benchmark_scoreboard(aggregation.scored_rows)
        )

    assert spilled == materialized
    assert repeated == materialized


def _watchdog_peak(root, *, run_count):
    labels = _write_fixture(root, run_count=run_count)
    gc.collect()
    tracemalloc.start()
    try:
        payload = finalization_watchdog(
            target_date=TARGET_DATE,
            runs_root=root / "taker_runs",
            labels_csv=labels,
            now=FINALIZED_AT,
            min_free_bytes=0,
            disk_usage_fn=_fixed_disk_usage,
            bakeoff_strategies=DEFAULT_BAKEOFF_STRATEGIES,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert payload["summary"]["run_count"] == run_count
    assert payload["summary"]["finalized_run_count"] == run_count
    assert payload["summary"]["bakeoff_created_count"] == run_count
    return peak


def test_watchdog_traced_memory_stays_flat_from_five_to_fifty_runs(tmp_path):
    few_peak = _watchdog_peak(tmp_path / "few", run_count=5)
    many_peak = _watchdog_peak(tmp_path / "many", run_count=50)

    # The watchdog intentionally retains a compact receipt per run, so allow
    # modest linear metadata plus allocator noise, but not retained tape rows.
    assert many_peak <= (few_peak * 2) + (2 * 1024 * 1024), {
        "few_peak_bytes": few_peak,
        "many_peak_bytes": many_peak,
    }
