"""Ledger finalize with ``--label-rule venue`` reads each market's venue-rule label CSV.

Guards: the venue-rule label wiring into the settlement ledger (docs/operations/venue-rule-labels.md):
opt-in, fail-closed when a market's label CSV is missing, WU default unchanged.
"""

import csv
import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from weather.backtesting.venue_rule_labels import default_label_path
from weather.market import market_day_labels
from weather.market.market_registry import spec_for_id

SLUG = "highest-temperature-in-toronto-on-may-27-2026"


def _tape(folder):
    start = datetime(2026, 5, 27, 11, 0)
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


def _run(tmp_path, *extra):
    folder = tmp_path / "snapshots" / SLUG
    folder.mkdir(parents=True)
    _tape(folder)
    args = market_day_labels.build_parser().parse_args([
        "finalize", str(folder),
        "--labels-csv", str(tmp_path / "labels.csv"),
        "--ledger-root", str(tmp_path / "ledger"),
        "--skip-polymarket-reconciliation",
        *extra,
    ])
    args.func(args)
    return folder


def test_venue_rule_finalize_reads_the_market_venue_label_csv(tmp_path):
    root = tmp_path / "venue"
    path = default_label_path(spec_for_id("toronto"), root)
    path.parent.mkdir(parents=True)
    path.write_text(
        "local_date,row_count,max_temp,max_temp_bucket,max_temp_times,label_source\n"
        "2026-05-27,24,26.0,26,15:00,wu_history\n",
        encoding="utf-8",
    )
    folder = _run(tmp_path, "--label-rule", "venue", "--venue-labels-root", str(root))
    label = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
    assert label["settlement_bucket"] == 26
    assert label["settlement_source"] == "daily_summary"
    assert label["daily_summary_path"] == str(path)
    with (tmp_path / "labels.csv").open(encoding="utf-8", newline="") as handle:
        assert [row["event_slug"] for row in csv.DictReader(handle)] == [SLUG]
    assert not list((tmp_path / "ledger" / "_venue_rule_finalize").glob("*.csv"))


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
