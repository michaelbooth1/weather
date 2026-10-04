"""The retained maker paper-score freshness reader keeps its verdicts."""

import json
from pathlib import Path

from weather.reporting.market.retired_trading_evidence import (
    ACTIVE_DAY_EVIDENCE_MODE,
    discover_run_folders,
    maker_paper_score_freshness,
    maker_paper_score_freshness_from_report,
)


def _write_run(runs_root: Path, target_date: str, run_id: str, *, active: bool = True) -> Path:
    folder = runs_root / target_date / run_id
    folder.mkdir(parents=True)
    (folder / "quote_intents_long.csv").write_text("run_id\n" + run_id + "\n", encoding="utf-8")
    (folder / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "target_date": target_date,
                "evidence_mode": ACTIVE_DAY_EVIDENCE_MODE if active else "diagnostic",
                "generated_at_utc": f"{target_date}T20:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return folder


def _write_report(path: Path, covered: list[Path]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-06-20T00:00:00+00:00",
                "summary": {
                    "paper_score_freshness": {
                        "covered_run_folders": [str(folder) for folder in covered],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_report_covering_latest_active_day_passes(tmp_path: Path) -> None:
    runs_root = tmp_path / "mm_runs"
    old_run = _write_run(runs_root, "2026-06-18", "old-active")
    new_run = _write_run(runs_root, "2026-06-19", "new-active")
    report = _write_report(tmp_path / "backtest" / "mm_paper_report.json", [old_run, new_run])

    freshness = maker_paper_score_freshness_from_report(runs_root, report)

    assert freshness["status"] == "PASS"
    assert freshness["blocks_maker_evidence_countability"] is False
    assert freshness["latest_completed_active_day"] == "2026-06-19"
    assert freshness["latest_covered_active_day"] == "2026-06-19"
    assert freshness["live_forward_day_count"] == 2
    assert freshness["report_exists"] is True


def test_report_missing_latest_active_day_is_stale(tmp_path: Path) -> None:
    runs_root = tmp_path / "mm_runs"
    old_run = _write_run(runs_root, "2026-06-18", "old-active")
    _write_run(runs_root, "2026-06-19", "new-active")
    report = _write_report(tmp_path / "backtest" / "mm_paper_report.json", [old_run])

    freshness = maker_paper_score_freshness_from_report(runs_root, report)

    assert freshness["status"] == "STALE"
    assert freshness["blocks_maker_evidence_countability"] is True
    assert freshness["latest_completed_active_day"] == "2026-06-19"
    assert freshness["latest_covered_active_day"] == "2026-06-18"


def test_missing_report_is_stale_and_blocks(tmp_path: Path) -> None:
    runs_root = tmp_path / "mm_runs"
    run = _write_run(runs_root, "2026-06-19", "only-active")
    missing = tmp_path / "backtest" / "mm_paper_report.json"

    freshness = maker_paper_score_freshness_from_report(runs_root, missing)

    assert discover_run_folders(runs_root) == [run]
    assert freshness["report_exists"] is False
    # No covered folders means the latest completed active day is not covered.
    assert freshness["status"] == "STALE"
    assert freshness["blocks_maker_evidence_countability"] is True


def test_no_active_day_runs_reports_no_active_day(tmp_path: Path) -> None:
    runs_root = tmp_path / "mm_runs"
    _write_run(runs_root, "2026-06-19", "diagnostic-run", active=False)
    report = _write_report(tmp_path / "backtest" / "mm_paper_report.json", [])

    freshness = maker_paper_score_freshness_from_report(runs_root, report)

    assert freshness["status"] == "NO_ACTIVE_DAY"
    # Owner decision 2026-10-04 (freshness#3): a missing active day fails closed.
    assert freshness["blocks_maker_evidence_countability"] is True
    assert freshness["completed_active_run_count"] == 0


def test_countability_block_fails_closed_per_status(tmp_path: Path) -> None:
    """Owner decision 2026-10-04 (freshness#3): only PASS leaves countability unblocked."""
    runs_root = tmp_path / "mm_runs"
    diagnostic = _write_run(runs_root, "2026-06-17", "diagnostic-run", active=False)
    old_run = _write_run(runs_root, "2026-06-18", "old-active")
    new_run = _write_run(runs_root, "2026-06-19", "new-active")

    no_active_day = maker_paper_score_freshness([diagnostic], [])
    stale = maker_paper_score_freshness([old_run, new_run], [old_run])
    passing = maker_paper_score_freshness([old_run, new_run], [old_run, new_run])

    assert no_active_day["status"] == "NO_ACTIVE_DAY"
    assert no_active_day["blocks_maker_evidence_countability"] is True
    assert stale["status"] == "STALE"
    assert stale["blocks_maker_evidence_countability"] is True
    assert passing["status"] == "PASS"
    assert passing["blocks_maker_evidence_countability"] is False
