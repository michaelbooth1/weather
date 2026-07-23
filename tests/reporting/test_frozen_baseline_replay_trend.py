"""Tests for the frozen-baseline replay trend (item 217)."""

from __future__ import annotations

import csv
import json
import tracemalloc

from weather.reporting.candidate_lifecycle.multi_variant_shadow import (
    read_prediction_rows as read_all_prediction_rows,
)
from weather.reporting.scorecards import frozen_baseline_replay_trend as fbt


def _row(market, date, snap, band, prob, outcome, *, market_yes=0.10, regime="ramp", variant="cur"):
    return {
        "variant_id": variant,
        "variant_family": variant,
        "market_id": market,
        "target_date": date,
        "snapshot_id": snap,
        "band_key": band,
        "probability": prob,
        "current_probability": prob,
        "market_yes": market_yes,
        "outcome": outcome,
        "cutoff_regime": regime,
    }


def test_current_better_than_baseline_on_shared_weather():
    # Same observations (frozen weather); current is sharper on the truth.
    current = [
        _row("nyc", "2026-06-20", "s1", "83 F", 0.80, 1),
        _row("nyc", "2026-06-20", "s2", "84 F", 0.10, 0),
    ]
    baseline = [
        _row("nyc", "2026-06-20", "s1", "83 F", 0.50, 1, variant="base"),
        _row("nyc", "2026-06-20", "s2", "84 F", 0.40, 0, variant="base"),
    ]
    payload = fbt.build_payload(current, baseline, generated_at="t")
    assert payload["independent_baseline_status"] == "PRESENT"
    assert payload["coverage"]["shared_observations"] == 2
    overall = payload["overall"]
    # current Brier = (0.2^2 + 0.1^2)/2 = 0.025 ; baseline = (0.5^2 + 0.4^2)/2 = 0.205
    assert abs(overall["brier_current"] - 0.025) < 1e-9
    assert abs(overall["brier_baseline"] - 0.205) < 1e-9
    assert overall["brier_delta_current_minus_baseline"] < 0  # current better on fixed weather


def test_only_shared_observations_are_scored():
    current = [
        _row("nyc", "2026-06-20", "s1", "83 F", 0.7, 1),
        _row("nyc", "2026-06-20", "s2", "84 F", 0.2, 0),  # current-only
    ]
    baseline = [
        _row("nyc", "2026-06-20", "s1", "83 F", 0.6, 1, variant="base"),
        _row("nyc", "2026-06-19", "s9", "70 F", 0.6, 1, variant="base"),  # baseline-only
    ]
    cov = fbt.build_payload(current, baseline, generated_at="t")["coverage"]
    assert cov["shared_observations"] == 1
    assert cov["current_only_observations"] == 1
    assert cov["baseline_only_observations"] == 1


def test_missing_when_no_shared_observations():
    current = [_row("nyc", "2026-06-20", "s1", "83 F", 0.7, 1)]
    baseline = [_row("nyc", "2026-06-20", "sX", "83 F", 0.6, 1, variant="base")]
    payload = fbt.build_payload(current, baseline, generated_at="t")
    assert payload["independent_baseline_status"] == "MISSING"
    assert "no_shared_frozen_observations" in payload["status_reasons"]


def test_outcome_mismatch_is_skipped():
    current = [_row("nyc", "2026-06-20", "s1", "83 F", 0.7, 1)]
    baseline = [_row("nyc", "2026-06-20", "s1", "83 F", 0.6, 0, variant="base")]  # label drift
    payload = fbt.build_payload(current, baseline, generated_at="t")
    assert payload["overall"] is None
    assert payload["independent_baseline_status"] == "MISSING"


def test_per_regime_and_per_market_breakdown():
    current = [
        _row("nyc", "2026-06-20", "s1", "83 F", 0.9, 1, regime="early"),
        _row("toronto", "2026-06-20", "s2", "23 C", 0.9, 1, regime="peak"),
    ]
    baseline = [
        _row("nyc", "2026-06-20", "s1", "83 F", 0.5, 1, regime="early", variant="b"),
        _row("toronto", "2026-06-20", "s2", "23 C", 0.5, 1, regime="peak", variant="b"),
    ]
    payload = fbt.build_payload(current, baseline, generated_at="t")
    assert set(payload["by_regime"]) == {"early", "peak"}
    assert set(payload["by_market"]) == {"nyc", "toronto"}


def test_pin_and_load_manifest_roundtrip(tmp_path):
    preds = tmp_path / "baseline_long.csv"
    preds.write_text("variant_id,market_id\nbase,nyc\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest = fbt.pin_baseline(
        [preds],
        baseline_id="accepted_2026_06_13",
        code_identity="abc123",
        corpus_id="promotion_corpus",
        manifest_path=manifest_path,
        store_dir=tmp_path / "store",
    )
    assert manifest["baseline_id"] == "accepted_2026_06_13"
    loaded = fbt.load_manifest(manifest_path)
    assert loaded["code_identity"] == "abc123"
    # the export was copied into the durable store
    assert (tmp_path / "store" / "accepted_2026_06_13" / "baseline_long.csv").exists()


def test_upsert_trend_dedups_by_run_date(tmp_path):
    path = tmp_path / "trend.jsonl"
    fbt.upsert_trend({"run_date": "2026-06-20", "brier_delta_current_minus_baseline": -0.01}, path)
    fbt.upsert_trend({"run_date": "2026-06-19", "brier_delta_current_minus_baseline": -0.02}, path)
    fbt.upsert_trend({"run_date": "2026-06-20", "brier_delta_current_minus_baseline": -0.03}, path)
    rows = fbt.load_trend(path)
    assert [r["run_date"] for r in rows] == ["2026-06-19", "2026-06-20"]  # sorted, deduped
    latest = [r for r in rows if r["run_date"] == "2026-06-20"][0]
    assert latest["brier_delta_current_minus_baseline"] == -0.03  # replaced, not appended


def test_trend_row_and_report_render():
    current = [_row("nyc", "2026-06-20", "s1", "83 F", 0.8, 1)]
    baseline = [_row("nyc", "2026-06-20", "s1", "83 F", 0.5, 1, variant="base")]
    payload = fbt.build_payload(
        current, baseline, manifest={"baseline_id": "b1"}, code_identity="cur1", generated_at="t"
    )
    row = fbt.trend_row(payload)
    assert row["run_date"] == "2026-06-20"
    assert row["baseline_id"] == "b1"
    assert row["independent_baseline_status"] == "PRESENT"
    report = fbt.render_report(payload, [row])
    assert "Frozen-Baseline Replay Trend" in report
    assert "weather held constant" in report


def _write_rows(path, rows):
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_variant_streaming_matches_read_all_then_filter_with_invalid_selected_rows(tmp_path):
    current_path = tmp_path / "current.csv"
    baseline_path = tmp_path / "baseline.csv"
    current_raw = [
        {
            "variant_id": "irrelevant",
            "source_freshness_state": "invalid row must be filtered before validation",
        },
        {
            "variant_id": "current",
            "family": "family",
            "market_id": "nyc",
            "market_date": "2026-06-20",
            "snapshot_id": "s1",
            "range_label": "83 F",
            "candidate_p": "0.8",
            "current_p": "0.5",
            "market_probability": "0.4",
            "outcome": "1",
            "candidate_cutoff_regime": "ramp",
            "source_freshness_state": "fresh",
        },
        {
            "variant_id": "current",
            "family": "family",
            "market_id": "nyc",
            "market_date": "2026-06-20",
            "snapshot_id": "s2",
            "range_label": "84 F",
            "candidate_p": "not-numeric",
            "current_p": "0.5",
            "market_probability": "0.4",
            "outcome": "0",
            "candidate_cutoff_regime": "ramp",
            "source_freshness_state": "fresh",
        },
    ]
    baseline_raw = [
        {
            "variant_id": "baseline",
            "family": "family",
            "market_id": "nyc",
            "market_date": "2026-06-20",
            "snapshot_id": "s1",
            "range_label": "83 F",
            "candidate_p": "0.5",
            "current_p": "0.5",
            "market_probability": "0.4",
            "outcome": "1",
            "candidate_cutoff_regime": "ramp",
            "source_freshness_state": "stale",
        }
    ]
    _write_rows(current_path, current_raw)
    _write_rows(baseline_path, baseline_raw)

    legacy_current = fbt._filter_variant(
        read_all_prediction_rows([current_path]),
        "current",
    )
    legacy_baseline = fbt._filter_variant(
        read_all_prediction_rows([baseline_path]),
        "baseline",
    )
    expected = fbt.build_payload(
        legacy_current,
        legacy_baseline,
        generated_at="fixed",
    )

    actual = fbt.build_payload(
        fbt.read_prediction_rows([current_path], variant_id="current"),
        fbt.read_prediction_rows([baseline_path], variant_id="baseline"),
        generated_at="fixed",
    )

    assert actual == expected
    assert actual["validation_errors"] == [
        {
            "row_number": 2,
            "variant_id": "current",
            "errors": ["missing required field: probability"],
        }
    ]


def test_variant_streaming_does_not_retain_large_irrelevant_csv_population(tmp_path):
    path = tmp_path / "wide.csv"
    fieldnames = [
        "variant_id",
        "variant_family",
        "market_id",
        "target_date",
        "snapshot_id",
        "band_key",
        "probability",
        "current_probability",
        "market_yes",
        "outcome",
        "cutoff_regime",
        "unused_wide_payload",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(20_000):
            writer.writerow({
                "variant_id": "irrelevant",
                "unused_wide_payload": f"{index:05d}-" + ("x" * 512),
            })
        writer.writerow({
            "variant_id": "selected",
            "variant_family": "selected",
            "market_id": "nyc",
            "target_date": "2026-06-20",
            "snapshot_id": "s1",
            "band_key": "83 F",
            "probability": "0.8",
            "current_probability": "0.8",
            "market_yes": "0.5",
            "outcome": "1",
            "cutoff_regime": "ramp",
            "unused_wide_payload": "must not be retained",
        })

    tracemalloc.start()
    try:
        rows = fbt.read_prediction_rows([path], variant_id="selected")
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(rows) == 1
    assert rows[0]["variant_id"] == "selected"
    assert "unused_wide_payload" not in rows[0]
    assert peak_bytes < path.stat().st_size // 2
