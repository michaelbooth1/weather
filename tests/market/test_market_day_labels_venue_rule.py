"""Ledger finalize with ``--label-rule venue`` reads each market's venue-rule label CSV.

Guards: the venue-rule label wiring into the settlement ledger (docs/operations/venue-rule-labels.md):
opt-in, fail-closed when a market's label CSV is missing, WU default unchanged, and a folder dated
before the cutover labelled from the WU daily summary exactly as under the WU rule.
"""

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from weather.backtesting.venue_rule_labels import default_label_path
from weather.market import market_day_labels
from weather.market.market_registry import MarketSpec, spec_for_id

SLUG = "highest-temperature-in-toronto-on-may-27-2026"
POST_SLUG = "highest-temperature-in-toronto-on-october-24-2026"


def _tape(folder, day=date(2026, 5, 27)):
    start = datetime(day.year, day.month, day.day, 11, 0)
    pd.DataFrame([
        {
            "snapshot_id": f"s{i}",
            "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
            "range_label": f"{band} C",
            "bin_kind": "eq",
            "bin_value_c": band,
            "model_probability": 0.5,
            "market_yes": 0.4,
            "wu_history_high_c": 25.0,
        }
        for i in range(43)
        for band in (25, 26)
    ]).to_csv(folder / "snapshots_long.csv", index=False)


def _run(tmp_path, *extra, slug=SLUG, day=date(2026, 5, 27)):
    folder = tmp_path / "snapshots" / slug
    folder.mkdir(parents=True)
    _tape(folder, day)
    args = market_day_labels.build_parser().parse_args([
        "finalize", str(folder),
        "--labels-csv", str(tmp_path / "labels.csv"),
        "--ledger-root", str(tmp_path / "ledger"),
        "--skip-polymarket-reconciliation",
        *extra,
    ])
    args.func(args)
    return folder


def _venue_csv(root, rows):
    path = default_label_path(spec_for_id("toronto"), root)
    path.parent.mkdir(parents=True)
    path.write_text(
        "local_date,row_count,max_temp,max_temp_bucket,max_temp_times,label_source\n" + rows,
        encoding="utf-8",
    )
    return path


def test_venue_rule_finalize_reads_the_market_venue_label_csv(tmp_path):
    path = _venue_csv(tmp_path / "venue", "2026-10-24,24,26.0,26,15:00,metar_routine\n")
    folder = _run(
        tmp_path, "--label-rule", "venue", "--venue-labels-root", str(tmp_path / "venue"),
        slug=POST_SLUG, day=date(2026, 10, 24),
    )
    label = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
    assert label["settlement_bucket"] == 26
    assert label["settlement_source"] == "daily_summary"
    assert label["daily_summary_path"] == str(path)
    with (tmp_path / "labels.csv").open(encoding="utf-8", newline="") as handle:
        assert [row["event_slug"] for row in csv.DictReader(handle)] == [POST_SLUG]
    assert not list((tmp_path / "ledger" / "_venue_rule_finalize").glob("*.csv"))


def test_pre_cutover_folder_finalizes_from_the_wu_summary_under_the_venue_rule(tmp_path):
    # The venue CSV disagrees with WU on purpose: before the cutover only WU counts.
    _venue_csv(tmp_path / "venue", "2026-05-27,24,27.0,27,15:00,wu_history\n")
    wu_root = tmp_path / "wunderground"
    wu_summary = wu_root / "cyyz" / "daily" / "daily_summary.csv"
    wu_summary.parent.mkdir(parents=True)
    wu_summary.write_text("local_date,row_count,max_temp_bucket_c\n2026-05-27,24,26\n", encoding="utf-8")
    with patch.object(MarketSpec, "data_root", property(lambda self: wu_root / self.icao.lower())):
        folder = _run(tmp_path, "--label-rule", "venue", "--venue-labels-root", str(tmp_path / "venue"))
    label = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
    assert label["settlement_bucket"] == 26
    assert Path(label["daily_summary_path"]) == wu_summary


def test_venue_rule_finalize_fails_closed_without_a_label_csv(tmp_path):
    with pytest.raises(SystemExit, match="build the venue-rule labels first"):
        _run(tmp_path, "--label-rule", "venue", "--venue-labels-root", str(tmp_path / "none"))
    assert not (tmp_path / "ledger").exists()
    assert not (tmp_path / "labels.csv").exists()


def test_venue_rule_and_daily_summary_override_are_exclusive(tmp_path):
    with pytest.raises(SystemExit, match="mutually exclusive"):
        _run(tmp_path, "--label-rule", "venue", "--daily-summary", str(tmp_path / "d.csv"))


def test_default_label_rule_is_wu():
    args = market_day_labels.build_parser().parse_args(["finalize"])
    assert args.label_rule == "wu"
