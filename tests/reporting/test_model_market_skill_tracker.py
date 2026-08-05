import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from weather.market.market_config import event_slug_for_date
from weather.reporting.scorecards.model_market_skill_tracker import (
    FLOOR_REGIME_ANCHOR,
    NOT_DISTINGUISHABLE,
    reservation_guard,
    run_tracker,
    weekly_payloads,
)


def _write_reservation(path: Path, *, inactive: bool = True) -> None:
    text = (
        "# Reserved confirmation window\n\n"
        "NONE ARE CURRENTLY RESERVED.\n\nNo date is held out today.\n"
        if inactive
        else "# Reserved confirmation window\n\nReserved dates: 2026-09-20 through 2026-10-01.\n"
    )
    path.write_text(text, encoding="utf-8")


def _write_fixture(root: Path) -> tuple[Path, Path, str]:
    snapshots = root / "snapshots"
    settlements = root / "settlements"
    target = date(2026, 7, 1)
    slug = event_slug_for_date(target, "toronto")
    folder = snapshots / slug
    folder.mkdir(parents=True)
    columns = [
        "snapshot_id", "captured_at_utc", "event_slug", "model_version",
        "runtime_git_commit", "runtime_git_dirty", "runtime_code_state",
        "runtime_source_fingerprint", "range_label", "bin_kind", "bin_value_c",
        "model_probability", "market_yes", "market_no",
    ]
    rows = []
    for snapshot_id, hour, model, market in (
        ("s1", 14, (0.2, 0.6, 0.2), (0.3, 0.5, 0.2)),
        ("s2", 15, (0.1, 0.7, 0.2), (0.2, 0.6, 0.2)),
    ):
        for bucket, model_probability, market_yes in zip((24, 25, 26), model, market):
            rows.append({
                "snapshot_id": snapshot_id,
                "captured_at_utc": f"2026-07-01T{hour:02d}:00:00+00:00",
                "event_slug": slug,
                "model_version": "fixture",
                "runtime_git_commit": FLOOR_REGIME_ANCHOR,
                "runtime_git_dirty": "False",
                "runtime_code_state": "clean",
                "runtime_source_fingerprint": "fixture",
                "range_label": f"{bucket} C",
                "bin_kind": "eq",
                "bin_value_c": bucket,
                "model_probability": model_probability,
                "market_yes": market_yes,
                "market_no": 1 - market_yes,
            })
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    ledger = settlements / "toronto" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    label = {
        "schema_version": "fixture",
        "event_slug": slug,
        "market_id": "toronto",
        "city": "Toronto",
        "target_date": target.isoformat(),
        "settlement_bucket": 25,
        "settlement_unit": "C",
        "winning_band": "25 C",
        "quality_grade": "complete",
        "coverage_clean": True,
        "capture_ratio": 1.0,
        "max_gap_minutes": 10,
        "material_coverage_grade": "strict_complete",
        "promotion_countable": True,
        "promotion_countable_reason": "fixture countable",
        "settlement_source": "fixture_wu_history",
    }
    ledger.write_text(json.dumps(label, sort_keys=True) + "\n", encoding="utf-8")
    return snapshots, settlements, slug


def _args(tmp_path: Path, command: str = "backfill") -> argparse.Namespace:
    snapshots, settlements, _slug = _write_fixture(tmp_path)
    reservation = tmp_path / "reserved.md"
    _write_reservation(reservation)
    output = tmp_path / "output"
    return argparse.Namespace(
        command=command,
        repo_root=str(Path(__file__).resolve().parents[2]),
        snapshots_root=str(snapshots),
        settlement_root=str(settlements),
        history_path=str(output / "history.jsonl"),
        summary_path=str(output / "summary.json"),
        report_path=str(output / "report.md"),
        reservation_path=str(reservation),
        floor_control_rows=None,
        cool_bias_control_rows=None,
        allow_missing_positive_controls=True,
        replicates=40,
        seed=123,
    )


def test_reservation_guard_fails_before_evidence_work(tmp_path):
    path = tmp_path / "reserved.md"
    _write_reservation(path, inactive=False)
    with pytest.raises(RuntimeError, match="refusing to read"):
        reservation_guard(path)


def test_production_backfill_requires_positive_controls(tmp_path):
    args = _args(tmp_path)
    args.allow_missing_positive_controls = False
    with pytest.raises(RuntimeError, match="requires both passing positive-control inputs"):
        run_tracker(args)


def test_backfill_is_append_only_and_restart_idempotent(tmp_path):
    args = _args(tmp_path)
    first = run_tracker(args)
    history = Path(args.history_path)
    first_lines = history.read_text(encoding="utf-8").splitlines()

    assert first["status"] == "PASS"
    assert first["appended_market_day_revisions"] == 2
    assert first["appended_weekly_revisions"] == 2
    assert len(first["current_market_days"]) == 2
    assert {row["artifact_regime"] for row in first["current_market_days"].values()} == {
        "hard_rescued_floor_v1"
    }
    all_hours = next(
        row for row in first["current_market_days"].values()
        if row["capture_slice"] == "all_market_local_capture_hours"
    )
    assert all_hours["settlement"]["promotion_countable"] is True
    assert all_hours["model_decomposition"]["identity_residual"] == pytest.approx(0.0)
    assert all_hours["market_decomposition"]["identity_residual"] == pytest.approx(0.0)

    second = run_tracker(args)
    assert second["appended_market_day_revisions"] == 0
    assert second["appended_weekly_revisions"] == 0
    assert history.read_text(encoding="utf-8").splitlines() == first_lines


def test_refresh_appends_corrections_without_rewriting_history(tmp_path):
    args = _args(tmp_path)
    first = run_tracker(args)
    history = Path(args.history_path)
    before = history.read_text(encoding="utf-8")
    label = next(iter(first["settlement_labels"].values()))
    corrected = {
        **label,
        "settlement_bucket": 26,
        "winning_band": "26 C",
        "promotion_countable_reason": "fixture corrected countable",
    }
    ledger = Path(args.settlement_root) / "toronto" / "ledger.jsonl"
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(corrected, sort_keys=True) + "\n")

    args.command = "refresh"
    refreshed = run_tracker(args)
    after = history.read_text(encoding="utf-8")

    assert after.startswith(before)
    assert refreshed["appended_market_day_revisions"] == 2
    assert refreshed["appended_weekly_revisions"] == 2
    assert all(
        row["settlement"]["settlement_bucket"] == 26
        for row in refreshed["current_market_days"].values()
    )


def _weekly_day(target: date, market_id: str) -> dict:
    week_start = target - timedelta(days=target.weekday())
    decomposition = {
        "brier": 0.2,
        "reliability": 0.05,
        "resolution": 0.06,
        "uncertainty": 0.21,
        "identity_residual": 0.0,
    }
    return {
        "status": "promotion_countable",
        "market_id": market_id,
        "target_date": target.isoformat(),
        "week_start": week_start.isoformat(),
        "artifact_regime": "hard_rescued_floor_v1",
        "capture_slice": "all_market_local_capture_hours",
        "model_brier": 0.2,
        "market_brier": 0.2,
        "model_minus_market_brier_gap": 0.0,
        "model_over_market_brier_ratio": 1.0,
        "model_decomposition": decomposition,
        "market_decomposition": decomposition,
        "revision_id": f"{target}:{market_id}",
    }


def test_week_delta_uses_required_indistinguishable_language():
    rows = []
    for target in (date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 13), date(2026, 7, 14)):
        rows.extend(_weekly_day(target, market_id) for market_id in ("toronto", "nyc"))
    weekly = weekly_payloads(rows, replicates=40, base_seed=123)
    current = next(row for row in weekly if row["week_start"] == "2026-07-13")
    assert current["week_over_week"]["statement"] == NOT_DISTINGUISHABLE
    assert current["week_over_week"]["status"] == "NOT_STATISTICALLY_DISTINGUISHABLE"
