from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.operations import settlement_hole_check
from weather.operations.settlement_hole_check import check_settlement_holes, tail_lines


@pytest.fixture(autouse=True)
def synthetic_market_registry(monkeypatch):
    monkeypatch.setattr(settlement_hole_check, "all_specs",
                        lambda: [SimpleNamespace(id=market) for market in ("alpha", "beta")])


def test_tail_lines_reads_only_requested_suffix(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(f"line-{index}" for index in range(1000)) + "\n", encoding="utf-8")

    assert tail_lines(ledger, 3, chunk_bytes=16) == ["line-997", "line-998", "line-999"]


def _append(ledger: Path, **record) -> None:
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def test_latest_revision_controls_and_interior_holes_are_reported(tmp_path: Path) -> None:
    for market in ("alpha", "beta"):
        ledger = tmp_path / "data" / "settlements" / market / "ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        _append(ledger, target_date="2026-08-10", settlement_source="WU", settlement_high=30)
        _append(ledger, target_date="2026-08-11", settlement_source="none", settlement_high=None)
        _append(ledger, target_date="2026-08-12", settlement_source="WU", settlement_high=31)
    # A later valid revision repairs only alpha's interior hole.
    _append(
        tmp_path / "data" / "settlements" / "alpha" / "ledger.jsonl",
        target_date="2026-08-11",
        settlement_source="WU",
        settlement_high=29,
    )

    result = check_settlement_holes(
        tmp_path,
        now=datetime.fromisoformat("2026-08-13T22:00:00-04:00"),
        window_days=3,
        tail_line_count=400,
    )

    assert result["ok"] is True
    assert result["holes"] == [
        {"date": "2026-08-11", "markets": 1, "missing_markets": ["beta"]}
    ]


def test_yesterday_is_not_expected_before_noon(tmp_path: Path) -> None:
    ledger = tmp_path / "data" / "settlements" / "alpha" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    _append(ledger, target_date="2026-08-12", settlement_source="none", settlement_high=None)

    result = check_settlement_holes(
        tmp_path,
        now=datetime.fromisoformat("2026-08-13T06:00:00-04:00"),
        window_days=1,
    )

    assert result["holes"] == []
    assert result["authoritative_holes"] == []


@pytest.mark.parametrize(("source", "high", "authoritative"), [
    ("snapshot_high", 77, False), ("daily_summary(sparse)", 77, False),
    ("daily_summary", "NaN", False), ("daily_summary", "Infinity", False),
    ("daily_summary", True, False), ("daily_summary", "bad", False),
    ("daily_summary", "1_0", False), ("daily_summary", "+1.0e0", True),
    ("daily_summary", 0, True), (" Daily_Summary ", "-2.0", True),
])
def test_authoritative_alarm_matches_backfill_predicate(tmp_path, source, high, authoritative):
    day = "2026-08-12"
    for market in ("alpha", "unregistered"):
        ledger = tmp_path / "data" / "settlements" / market / "ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        _append(ledger, target_date=day, settlement_source="daily_summary", settlement_high=1)
        _append(ledger, target_date=day, settlement_source=source, settlement_high=high)
    result = check_settlement_holes(tmp_path, now=datetime.fromisoformat("2026-08-13T12:00:00"), window_days=1)
    assert result["market_count"] == 2
    assert result["missing_ledgers"] == ["beta"]
    assert result["holes"] == [{"date": day, "markets": 1, "missing_markets": ["beta"]}]
    missing = ["beta"] if authoritative else ["alpha", "beta"]
    assert result["authoritative_holes"] == [{"date": day, "markets": len(missing), "missing_markets": missing}]


def test_absent_tree_counts_every_registered_market(tmp_path):
    result = check_settlement_holes(tmp_path, now=datetime.fromisoformat("2026-08-13T12:00:00"), window_days=1)
    assert result["market_count"] == 2
    assert result["missing_ledgers"] == ["alpha", "beta"]
    assert result["authoritative_holes"][0]["missing_markets"] == ["alpha", "beta"]
