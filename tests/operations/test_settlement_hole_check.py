from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from weather.operations.settlement_hole_check import check_settlement_holes, tail_lines


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
