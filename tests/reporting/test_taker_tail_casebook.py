import csv
import gc
import json
import tracemalloc

from weather.market.taker_bot import load_settlement_labels, read_order_rows
from weather.reporting.casebooks.taker_tail_casebook import (
    build_tail_casebook,
    build_tail_casebook_from_paths,
    render_report,
    write_outputs,
)


def test_tail_casebook_flags_settled_losing_low_price_tail_slice():
    row = {
        "run_id": "fixture-run",
        "target_date": "2026-06-21",
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-21-2026",
        "captured_at_utc": "2026-06-21T20:00:00+00:00",
        "order_status": "FILLED",
        "range_label": "84-85 F",
        "bin_kind": "eq",
        "bin_value": "84",
        "bin_value_hi": "85",
        "clob_token_id": "token-atlanta-84",
        "fair_probability": "0.40",
        "best_ask": "0.01",
        "edge": "0.39",
        "fill_size": "10",
        "fill_notional_usdc": "0.1",
        "total_spent_usdc": "0.1",
        "low_price_tail": "True",
        "market_centered_warm_tail": "False",
        "current_high_band_distance": "4",
        "market_modal_band_distance": "4",
        "source_freshness_state": "all_fresh",
    }
    labels = {
        "by_event_slug": {
            row["event_slug"]: {
                "event_slug": row["event_slug"],
                "market_id": "atlanta",
                "target_date": "2026-06-21",
                "settlement_bucket": 80,
                "winning_band": "80-81 F",
                "quality_grade": "complete",
            }
        },
        "by_market_date": {},
    }

    payload = build_tail_casebook([row], labels=labels, source_runs=["fixture"])
    report = render_report(payload)

    assert payload["summary"]["status"] == "BLOCK_BAD_TAIL_SLICES"
    assert payload["summary"]["tail_fill_count"] == 1
    assert payload["summary"]["losing_tail_fill_count"] == 1
    assert payload["by_tail_type"][0]["tail_type"] == "low_price_tail"
    assert payload["by_tail_type"][0]["loss_count"] == 1
    assert payload["no_go_candidates"][0]["candidate_action"] == "block_until_repeated_settlement_positive_oos"
    assert "low_price_tail" in payload["no_go_candidates"][0]["slice_key"]
    assert "Taker Tail Casebook" in report
    assert "block_until_repeated_settlement_positive_oos" in report


def test_tail_casebook_infers_legacy_warm_tail_from_modal_context():
    base = {
        "run_id": "legacy-run",
        "target_date": "2026-06-20",
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-20-2026",
        "snapshot_id": "s1",
        "captured_at_utc": "2026-06-20T18:00:00+00:00",
        "bin_kind": "eq",
        "source_freshness_state": "all_fresh",
    }
    modal = {
        **base,
        "order_status": "SKIPPED",
        "range_label": "78-79 F",
        "bin_value": "78",
        "bin_value_hi": "79",
        "market_mid": "0.60",
        "best_ask": "0.61",
        "fair_probability": "0.55",
    }
    filled_warm_tail = {
        **base,
        "order_status": "FILLED",
        "range_label": "88-89 F",
        "bin_value": "88",
        "bin_value_hi": "89",
        "market_mid": "0.12",
        "best_ask": "0.13",
        "fair_probability": "0.25",
        "fill_size": "10",
        "fill_notional_usdc": "1.3",
        "total_spent_usdc": "1.3",
    }
    labels = {
        "by_event_slug": {
            base["event_slug"]: {
                "event_slug": base["event_slug"],
                "market_id": "atlanta",
                "target_date": "2026-06-20",
                "settlement_bucket": 78,
                "winning_band": "78-79 F",
                "quality_grade": "complete",
            }
        },
        "by_market_date": {},
    }

    payload = build_tail_casebook([modal, filled_warm_tail], labels=labels)

    assert payload["summary"]["warm_tail_fill_count"] == 1
    assert payload["cases"][0]["tail_type"] == "market_centered_warm_tail"
    assert payload["cases"][0]["market_modal_band_key"] == "eq:78-79"
    assert payload["cases"][0]["market_modal_band_distance"] == 9.0
    assert payload["cases"][0]["settlement_result"] == "loss"


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_run(root, name, rows):
    folder = root / name
    _write_csv(folder / "orders_long.csv", rows)
    return folder


def _materialized_source_rows(run_paths):
    rows = []
    for run in run_paths:
        order_path = run / "orders_long.csv"
        for row in read_order_rows(order_path):
            out = dict(row)
            out["_source_orders_path"] = str(order_path)
            out["_source_run"] = str(run)
            rows.append(out)
    return rows


def test_streamed_multi_run_casebook_matches_materialized_artifacts(tmp_path):
    event_slug = "highest-temperature-in-atlanta-on-june-20-2026"
    base = {
        "target_date": "2026-06-20",
        "market_id": "atlanta",
        "event_slug": event_slug,
        "captured_at_utc": "2026-06-20T18:00:00+00:00",
        "bin_kind": "eq",
        "source_freshness_state": "all_fresh",
    }
    legacy_fill = {
        **base,
        "run_id": "run-one",
        "order_id": "legacy-warm",
        "snapshot_id": "shared-modal",
        "order_status": "FILLED",
        "range_label": "88-89 F",
        "bin_value": "88",
        "bin_value_hi": "89",
        "market_mid": "0.12",
        "best_ask": "0.13",
        "fair_probability": "0.25",
        "fill_size": "10",
        "fill_notional_usdc": "1.3",
        "total_spent_usdc": "1.3",
    }
    duplicate_loss = {
        **base,
        "run_id": "run-one",
        "order_id": "duplicate-loss",
        "snapshot_id": "loss-snapshot",
        "order_status": "FILLED",
        "range_label": "88-89 F",
        "bin_value": "88",
        "bin_value_hi": "89",
        "market_mid": "0.12",
        "best_ask": "0.01",
        "fair_probability": "0.40",
        "fill_size": "10",
        "fill_notional_usdc": "0.1",
        "total_spent_usdc": "0.1",
        "low_price_tail": "True",
        "market_centered_warm_tail": "False",
        "current_high_band_distance": "4",
    }
    unmatched_fill = {
        **duplicate_loss,
        "run_id": "run-one",
        "order_id": "unmatched",
        "snapshot_id": "unmatched",
        "market_id": "unmatched-market",
        "event_slug": "missing-label-event",
    }
    first_modal = {
        **base,
        "run_id": "run-one",
        "order_id": "first-modal",
        "snapshot_id": "shared-modal",
        "order_status": "SKIPPED",
        "range_label": "78-79 F",
        "bin_value": "78",
        "bin_value_hi": "79",
        "market_mid": "0.5000000",
        "best_ask": "0.51",
        "fair_probability": "0.50",
    }
    later_rounded_modal = {
        **base,
        "run_id": "run-two",
        "order_id": "later-rounded-modal",
        "snapshot_id": "shared-modal",
        "order_status": "SKIPPED",
        "range_label": "80-81 F",
        "bin_value": "80",
        "bin_value_hi": "81",
        "market_mid": "0.5000004",
        "best_ask": "0.51",
        "fair_probability": "0.50",
    }
    repeated_loss = {**duplicate_loss}
    winning_tail = {
        **base,
        "run_id": "run-two",
        "order_id": "winning-tail",
        "snapshot_id": "winning-tail",
        "order_status": "FILLED",
        "range_label": "80-81 F",
        "bin_value": "80",
        "bin_value_hi": "81",
        "market_mid": "0.40",
        "best_ask": "0.01",
        "fair_probability": "0.50",
        "fill_size": "10",
        "fill_notional_usdc": "0.1",
        "total_spent_usdc": "0.1",
        "low_price_tail": "True",
        "market_centered_warm_tail": "False",
        "current_high_band_distance": "0",
    }
    run_paths = [
        _write_run(
            tmp_path / "runs",
            "run-one",
            [legacy_fill, duplicate_loss, unmatched_fill, first_modal],
        ),
        _write_run(
            tmp_path / "runs",
            "run-two",
            [later_rounded_modal, repeated_loss, winning_tail],
        ),
    ]
    labels_csv = tmp_path / "labels.csv"
    _write_csv(
        labels_csv,
        [{
            "event_slug": event_slug,
            "market_id": "atlanta",
            "target_date": "2026-06-20",
            "settlement_bucket": "80",
            "winning_band": "80-81 F",
            "quality_grade": "complete",
        }],
    )
    generated_at = "2026-07-17T00:00:00+00:00"
    expected = build_tail_casebook(
        _materialized_source_rows(run_paths),
        labels=load_settlement_labels(labels_csv),
        source_runs=run_paths,
        generated_at_utc=generated_at,
    )

    payload = build_tail_casebook_from_paths(
        run_paths,
        labels_csv=labels_csv,
        generated_at_utc=generated_at,
    )
    try:
        first_json = tmp_path / "casebook.json"
        first_report = tmp_path / "casebook.md"
        second_json = tmp_path / "casebook-detail.json"
        second_report = tmp_path / "casebook-detail.md"
        write_outputs(payload, json_out=first_json, report_out=first_report)
        write_outputs(payload, json_out=second_json, report_out=second_report)

        assert getattr(payload["cases"], "is_spilled_rows", False)
        assert len(payload["cases"]) == 5
        assert json.loads(first_json.read_text(encoding="utf-8")) == expected
        assert json.loads(second_json.read_text(encoding="utf-8")) == expected
        assert first_report.read_text(encoding="utf-8") == render_report(expected)
        assert second_report.read_text(encoding="utf-8") == render_report(expected)
    finally:
        payload.close()


def _memory_fixture(root, run_count, rows_per_run=256):
    event_slug = "highest-temperature-in-atlanta-on-june-20-2026"
    labels_csv = root / "labels.csv"
    _write_csv(
        labels_csv,
        [{
            "event_slug": event_slug,
            "market_id": "atlanta",
            "target_date": "2026-06-20",
            "settlement_bucket": "70",
            "winning_band": "70-71 F",
            "quality_grade": "complete",
        }],
    )
    run_paths = []
    for run_index in range(run_count):
        rows = []
        for row_index in range(rows_per_run):
            rows.append({
                "run_id": f"run-{run_index:02d}",
                "order_id": f"run-{run_index:02d}-row-{row_index:04d}",
                "target_date": "2026-06-20",
                "market_id": "atlanta",
                "event_slug": event_slug,
                "snapshot_id": f"run-{run_index:02d}-snapshot-{row_index:04d}",
                "captured_at_utc": "2026-06-20T18:00:00+00:00",
                "order_status": "FILLED",
                "range_label": "90-91 F",
                "bin_kind": "eq",
                "bin_value": "90",
                "bin_value_hi": "91",
                "market_mid": "0.10",
                "best_ask": "0.01",
                "fair_probability": "0.20",
                "fill_size": "1",
                "fill_notional_usdc": "0.01",
                "total_spent_usdc": "0.01",
                "low_price_tail": "True",
                "market_centered_warm_tail": "False",
                "current_high_band_distance": "4",
                "source_freshness_state": "all_fresh",
                "unused_payload": (
                    f"{run_index:02d}:{row_index:04d}:" + ("x" * 512)
                ),
            })
        run_paths.append(
            _write_run(root / "runs", f"run-{run_index:02d}", rows)
        )
    return run_paths, labels_csv


def _streamed_peak(root, run_count):
    run_paths, labels_csv = _memory_fixture(root, run_count)
    gc.collect()
    tracemalloc.start()
    try:
        payload = build_tail_casebook_from_paths(
            run_paths,
            labels_csv=labels_csv,
            generated_at_utc="2026-07-17T00:00:00+00:00",
        )
        try:
            first_json = root / "casebook.json"
            first_report = root / "casebook.md"
            second_json = root / "casebook-detail.json"
            second_report = root / "casebook-detail.md"
            write_outputs(payload, json_out=first_json, report_out=first_report)
            write_outputs(payload, json_out=second_json, report_out=second_report)
            counts = dict(payload["summary"])
        finally:
            payload.close()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, counts


def test_streamed_casebook_peak_memory_stays_flat_as_runs_grow(tmp_path):
    few_peak, few_counts = _streamed_peak(tmp_path / "few", 5)
    many_peak, many_counts = _streamed_peak(tmp_path / "many", 50)

    assert few_counts["order_row_count"] == 5 * 256
    assert few_counts["scored_order_row_count"] == 5 * 256
    assert few_counts["tail_fill_count"] == 5 * 256
    assert few_counts["losing_tail_fill_count"] == 5 * 256
    assert many_counts["order_row_count"] == 50 * 256
    assert many_counts["scored_order_row_count"] == 50 * 256
    assert many_counts["tail_fill_count"] == 50 * 256
    assert many_counts["losing_tail_fill_count"] == 50 * 256
    assert many_peak <= few_peak + 2 * 1024 * 1024
