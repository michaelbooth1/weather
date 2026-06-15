import csv
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from model_history import build_history_payload, recent_completed_dates  # noqa: E402


SLUG = "highest-temperature-in-toronto-on-july-1-2026"


def write_tape(root):
    folder = Path(root) / SLUG
    folder.mkdir(parents=True)
    columns = [
        "snapshot_id",
        "captured_at_utc",
        "captured_at_local",
        "event_slug",
        "model_version",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "model_probability",
        "market_yes",
        "market_no",
    ]
    rows = [
        {
            "snapshot_id": "s1",
            "captured_at_utc": "2026-07-01T14:00:00+00:00",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test",
            "range_label": "24 C",
            "bin_kind": "eq",
            "bin_value_c": "24",
            "model_probability": "0.30",
            "market_yes": "0.20",
            "market_no": "0.80",
        },
        {
            "snapshot_id": "s1",
            "captured_at_utc": "2026-07-01T14:00:00+00:00",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test",
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": "25",
            "model_probability": "0.49",
            "market_yes": "0.40",
            "market_no": "0.60",
        },
        {
            "snapshot_id": "s1",
            "captured_at_utc": "2026-07-01T14:00:00+00:00",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test",
            "range_label": "26 C",
            "bin_kind": "eq",
            "bin_value_c": "26",
            "model_probability": "0.21",
            "market_yes": "0.40",
            "market_no": "0.60",
        },
        {
            "snapshot_id": "s2",
            "captured_at_utc": "2026-07-01T15:00:00+00:00",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test",
            "range_label": "24 C",
            "bin_kind": "eq",
            "bin_value_c": "24",
            "model_probability": "0.20",
            "market_yes": "0.15",
            "market_no": "0.85",
        },
        {
            "snapshot_id": "s2",
            "captured_at_utc": "2026-07-01T15:00:00+00:00",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test",
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": "25",
            "model_probability": "0.60",
            "market_yes": "0.45",
            "market_no": "0.55",
        },
        {
            "snapshot_id": "s2",
            "captured_at_utc": "2026-07-01T15:00:00+00:00",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test",
            "range_label": "26 C",
            "bin_kind": "eq",
            "bin_value_c": "26",
            "model_probability": "0.20",
            "market_yes": "0.40",
            "market_no": "0.60",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (folder / "settlement.json").write_text(
        json.dumps(
            {
                "event_slug": SLUG,
                "market_id": "toronto",
                "target_date": "2026-07-01",
                "settlement_bucket": 25,
                "settlement_unit": "C",
                "winning_band": "25 C",
                "quality_grade": "complete",
                "coverage_clean": True,
                "capture_ratio": 1.0,
                "max_gap_minutes": 60,
                "settlement_source": "test",
            }
        ),
        encoding="utf-8",
    )


def test_recent_completed_dates_excludes_current_day():
    assert recent_completed_dates(as_of=datetime(2026, 6, 15), days=3) == [
        date(2026, 6, 12),
        date(2026, 6, 13),
        date(2026, 6, 14),
    ]


def test_history_payload_scores_day_and_finds_winner_first_over_50(tmp_path):
    write_tape(tmp_path)

    payload = build_history_payload(
        snapshots_root=tmp_path,
        dates=[date(2026, 7, 1)],
        market_ids=["toronto"],
    )

    day = payload["days"][0]
    assert payload["overall"]["market_days"] == 1
    assert day["status"] == "scored"
    assert day["winning_band"] == "25 C"
    assert day["winning_first_over_50_time"] == "11:00 EDT"
    assert day["winning_first_top_time"] == "10:00 EDT"
    assert day["winner_crossed_50"] is True
    assert day["final_top_was_winner"] is True
    assert day["scored_rows"] == 6
