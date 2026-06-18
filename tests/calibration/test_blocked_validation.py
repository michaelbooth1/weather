from datetime import date, timedelta

from weather.calibration.blocked_validation import (
    blocked_validation_audit,
    split_leakage,
    validation_splits,
)


def _rows():
    start = date(2025, 12, 27)
    rows = []
    for offset in range(10):
        for market_id in ("nyc", "denver"):
            rows.append({
                "market_id": market_id,
                "target_date": (start + timedelta(days=offset)).isoformat(),
                "candidate_p": 0.55,
                "outcome": int(offset % 2 == 0),
            })
    return rows


def test_blocked_validation_splits_do_not_reuse_held_out_partitions():
    rows = _rows()

    splits = validation_splits(rows, rolling_block_days=3)

    assert {split["mode"] for split in splits} >= {
        "leave_one_market_day",
        "holdout_month",
        "holdout_year",
        "rolling_forward_block",
        "current_active_day",
    }
    for split in splits:
        assert split["train_indices"]
        assert split["validation_indices"]
        assert split_leakage(rows, split) == []


def test_blocked_validation_audit_reports_zero_leakage():
    audit = blocked_validation_audit(_rows(), rolling_block_days=3)

    assert audit["schema_version"] == "blocked_validation_v0.1"
    assert audit["ok"] is True
    assert audit["market_day_count"] == 20
    assert audit["target_date_count"] == 10
    assert audit["leak_count"] == 0
    assert audit["split_count"] > 0
