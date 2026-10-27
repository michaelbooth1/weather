"""Daily-chain ``market_day_labels_finalize`` step under ``--label-rule``.

Guards: the venue-rule label wiring of the daily chain (docs/operations/venue-rule-labels.md, cutover
runbook step 4): the default WU path is unchanged, venue mode builds the label CSV from already-fetched
routine METAR and then finalizes against it, and a missing CSV or a missing post-cutover row refuses.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from weather.backtesting.settlement_ledger import FolderFinalizationError
from weather.backtesting.venue_rule_labels import default_label_path
from weather.market.market_registry import MarketSpec, spec_for_id
from weather.operations import daily_refresh_source_steps as steps
from weather.operations.daily_refresh import build_parser

SLUG = "highest-temperature-in-nyc-on-october-24-2026"


def _tape(folder):
    start = datetime(2026, 10, 24, 11, 0)
    pd.DataFrame([
        {
            "snapshot_id": f"s{i}",
            "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
            "range_label": f"{band} F",
            "bin_kind": "eq",
            "bin_value_c": band,
            "model_probability": 0.5,
            "market_yes": 0.4,
            "wu_history_high": 80.0,
        }
        for i in range(43)
        for band in (77, 80)
    ]).to_csv(folder / "snapshots_long.csv", index=False)


def _routine_csv(root, rows):
    path = root / "klga" / "routine" / "asos_routine_2026-10-23_2026-10-25.csv"
    path.parent.mkdir(parents=True)
    lines = ["station,valid,tmpf,tmpc,metar"]
    for valid, ddhhmm, temp, t_group in rows:
        lines.append(f"LGA,{valid},70.00,20.00,KLGA {ddhhmm}Z 22003KT 10SM {temp}/10 A2987 RMK AO2 {t_group}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def layout(tmp_path):
    folder = tmp_path / "snapshots" / SLUG
    folder.mkdir(parents=True)
    _tape(folder)
    wu_root = tmp_path / "wunderground"
    with patch.object(MarketSpec, "data_root", property(lambda self: wu_root / self.icao.lower())):
        yield tmp_path, folder


def _args(tmp_path, folder, *extra):
    args = build_parser().parse_args([
        "run",
        "--labels-csv", str(tmp_path / "labels.csv"),
        "--ledger-root", str(tmp_path / "ledger"),
        "--venue-labels-root", str(tmp_path / "venue"),
        "--venue-metar-root", str(tmp_path / "metar"),
        "--skip-polymarket-reconciliation",
        *extra,
    ])
    args.folders = [str(folder)]
    return args


def test_default_label_rule_is_wu_and_never_builds(layout):
    tmp_path, folder = layout
    args = _args(tmp_path, folder)
    assert args.label_rule == "wu"
    with patch.object(steps, "finalize_folders", return_value=[]) as finalize, \
            patch.object(steps, "run_venue_rule_label_build") as build, \
            patch.object(steps, "finalize_with_venue_labels") as venue:
        result = steps.run_market_day_labels_finalize(args)
    assert result["status"] == "PASS"
    assert "label_rule" not in result
    build.assert_not_called()
    venue.assert_not_called()
    assert finalize.call_args.kwargs["daily_summary_path"] is None
    assert finalize.call_args.kwargs["labels_csv"] == args.labels_csv


def test_venue_mode_builds_then_finalizes_against_the_venue_csv(layout):
    tmp_path, folder = layout
    hourly = [
        (f"2026-10-24 {hour:02d}:51", f"24{hour:02d}51", "20", "T02000100") for hour in range(4, 24)
    ]
    hourly[10] = ("2026-10-24 14:51", "241451", "25", "T02500100")  # 25.0 C = 77 F
    _routine_csv(tmp_path / "metar", hourly + [("2026-10-25 18:51", "251851", "20", "T02000100")])
    result = steps.run_market_day_labels_finalize(_args(tmp_path, folder, "--label-rule", "venue"))

    assert result["status"] == "PASS"
    assert result["label_rule"] == "venue"
    built = result["venue_label_build"]["markets"]["nyc"]
    assert built["label_source_counts"] == {"metar_routine": 1}
    venue_csv = default_label_path(spec_for_id("nyc"), tmp_path / "venue")
    assert built["output"] == str(venue_csv)
    label = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
    assert label["settlement_bucket"] == 77  # not the tape's WU high of 80
    assert label["settlement_source"] == "daily_summary"
    assert label["daily_summary_path"] == str(venue_csv)


def test_venue_mode_refuses_without_a_label_csv(layout):
    tmp_path, folder = layout
    result = steps.run_market_day_labels_finalize(
        _args(tmp_path, folder, "--label-rule", "venue", "--skip-venue-label-build")
    )
    assert result["status"] == "BLOCK"
    assert result["reason"] == "venue_rule_labels_unavailable"
    assert not (tmp_path / "ledger").exists()
    assert not (folder / "settlement.json").exists()


def test_venue_mode_refuses_a_post_cutover_date_without_a_venue_row(layout):
    tmp_path, folder = layout
    # The stream ends on 10-24, so 10-24 is not yet final and has no row.
    _routine_csv(tmp_path / "metar", [("2026-10-24 18:51", "241851", "25", "T02500100")])
    with pytest.raises(FolderFinalizationError, match="no venue-rule label row for 2026-10-24"):
        steps.run_market_day_labels_finalize(_args(tmp_path, folder, "--label-rule", "venue"))
    assert not (folder / "settlement.json").exists()


def test_venue_mode_refuses_a_thin_post_cutover_day(layout):
    tmp_path, folder = layout
    # One routine report would leave the ledger on the tape's WU high, so it is refused.
    _routine_csv(tmp_path / "metar", [
        ("2026-10-24 18:51", "241851", "25", "T02500100"),
        ("2026-10-25 18:51", "251851", "20", "T02000100"),
    ])
    with pytest.raises(FolderFinalizationError, match="has 1 reports, fewer than 18"):
        steps.run_market_day_labels_finalize(_args(tmp_path, folder, "--label-rule", "venue"))
    assert not (folder / "settlement.json").exists()


def test_venue_mode_rejects_a_daily_summary_override(layout):
    tmp_path, folder = layout
    result = steps.run_market_day_labels_finalize(
        _args(tmp_path, folder, "--label-rule", "venue", "--daily-summary", str(tmp_path / "d.csv"))
    )
    assert result == {"status": "BLOCK", "reason": "daily_summary_override_with_venue_label_rule"}
