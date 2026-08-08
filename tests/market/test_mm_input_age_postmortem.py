"""Tests for maker input-age post-mortem reporting."""

from __future__ import annotations

import csv
import json

from weather.reporting.market.mm_input_age_postmortem import build_input_age_postmortem


FIELDS = (
    "target_date",
    "generated_at_utc",
    "market_id",
    "model_age_seconds",
    "book_age_seconds",
    "preflight_status",
    "range_label",
)


def _write_run(run_dir, rows, *, model_threshold=900, book_threshold=120):
    run_dir.mkdir(parents=True)
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "policy_config": {
                    "max_model_age_seconds": model_threshold,
                    "max_book_age_seconds": book_threshold,
                }
            }
        ),
        encoding="utf-8",
    )
    with (run_dir / "quote_intents_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _row(timestamp, market, model_age, book_age, *, preflight="PASS", band="a"):
    return {
        "target_date": "2026-08-01",
        "generated_at_utc": timestamp,
        "market_id": market,
        "model_age_seconds": model_age,
        "book_age_seconds": book_age,
        "preflight_status": preflight,
        "range_label": band,
    }


def test_deduplicates_bands_and_groups_active_ticks_by_market_and_hour(tmp_path):
    day = tmp_path / "2026-08-01"
    _write_run(
        day / "run_a",
        [
            _row("2026-08-01T11:00:00+00:00", "toronto", 100, 20, band="a"),
            _row("2026-08-01T11:00:00+00:00", "toronto", 100, 20, band="b"),
            _row("2026-08-01T12:00:00+00:00", "toronto", 1000, 130, preflight="BLOCK"),
            _row("2026-08-01T10:59:00+00:00", "toronto", 10, 10),
            _row("2026-08-02T00:01:00+00:00", "toronto", 10, 10),
        ],
    )

    report = build_input_age_postmortem(tmp_path)

    assert report["quote_tape_files"] == 1
    assert report["overall"]["samples"] == 2
    assert report["overall"]["model_age_seconds"]["fresh_fraction"] == 0.5
    assert report["overall"]["book_age_seconds"]["fresh_fraction"] == 0.5
    assert report["overall"]["both_fresh_fraction"] == 0.5
    assert report["overall"]["preflight_pass_fraction"] == 0.5
    assert report["by_market"][0]["market_id"] == "toronto"
    assert [row["hour"] for row in report["by_local_hour"]] == [7, 8]


def test_quarantine_tapes_are_opt_in(tmp_path):
    day = tmp_path / "2026-08-01"
    rows = [_row("2026-08-01T11:00:00+00:00", "toronto", 100, 20)]
    _write_run(day / "run_a", rows)
    _write_run(day / "_quarantine" / "retired_run", rows)

    canonical = build_input_age_postmortem(tmp_path)
    all_runtime = build_input_age_postmortem(tmp_path, include_quarantine=True)

    assert canonical["overall"]["samples"] == 1
    assert all_runtime["overall"]["samples"] == 2
