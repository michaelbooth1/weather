import csv
import json

import pytest

from weather.reporting.casebooks.severe_tail_ex_ante import (
    analyze_compact_rows,
    compact_replay_rows,
    load_current_settlement_index,
    render_report,
)


def _snapshot(market, target_date, snapshot, captured, model, market_p, outcome, **features):
    rows = []
    for index, (model_value, market_value, result) in enumerate(zip(model, market_p, outcome)):
        rows.append(
            {
                "band": f"band-{index}",
                "captured_at_local": captured,
                "cutoff_hour": captured[11:13],
                "feature_forecast_disagreement": features.get("disagreement", 2.0),
                "feature_forecast_high": features.get("forecast_high", 90.0),
                "feature_forecast_source_count": features.get("source_count", 4),
                "feature_high_so_far": features.get("high_so_far", 80.0),
                "market_id": market,
                "market_yes": market_value,
                "outcome": result,
                "reconstructed": features.get("reconstructed", False),
                "replayed_p": model_value,
                "snapshot_id": snapshot,
                "target_date": target_date,
            }
        )
    return rows


def _index(*keys):
    return {
        key: {
            "market_id": key[0],
            "target_date": key[1],
            "event_slug": f"{key[0]}-{key[1]}",
            "promotion_countable": True,
        }
        for key in keys
    }


def test_compaction_enforces_cutoff_and_reproduces_severe_definition():
    rows = _snapshot(
        "atlanta",
        "2026-07-22",
        "s1",
        "2026-07-22T09:05:00-04:00",
        [0.10, 0.20, 0.70],
        [0.05, 0.90, 0.05],
        [0.0, 1.0, 0.0],
    )
    compact, excluded = compact_replay_rows(
        rows,
        settlement_index=_index(("atlanta", "2026-07-22")),
        stratum="before_2026_07_31",
    )
    assert excluded == {}
    assert len(compact) == 3
    assert [row["severe"] for row in compact] == [False, True, True]
    assert compact[1]["selected_abs_gap_points"] == pytest.approx(70.0)
    assert compact[0]["market_mode_is_winner"] is True
    assert compact[0]["forecast_high_distance"] == 10.0


def test_effective_cutoff_may_lag_wall_clock():
    rows = _snapshot(
        "atlanta",
        "2026-07-22",
        "s1",
        "2026-07-22T10:05:00-04:00",
        [0.5, 0.5],
        [0.5, 0.5],
        [1.0, 0.0],
    )
    for row in rows:
        row["cutoff_hour"] = 9
    compact, excluded = compact_replay_rows(
        rows,
        settlement_index=_index(("atlanta", "2026-07-22")),
        stratum="before_2026_07_31",
    )
    assert len(compact) == 2
    assert compact[0]["cutoff_hour"] == 9
    assert excluded == {}


def test_compaction_excludes_undated_reconstructed_and_wrong_stratum():
    rows = []
    rows += _snapshot(
        "atlanta", "2026-07-22", "bad-time", "not-a-time",
        [0.5, 0.5], [0.5, 0.5], [1, 0]
    )
    rows += _snapshot(
        "atlanta", "2026-07-23", "reconstructed", "2026-07-23T09:00:00-04:00",
        [0.5, 0.5], [0.5, 0.5], [1, 0], reconstructed=True
    )
    rows += _snapshot(
        "atlanta", "2026-08-01", "post", "2026-08-01T09:00:00-04:00",
        [0.5, 0.5], [0.5, 0.5], [1, 0]
    )
    compact, excluded = compact_replay_rows(
        rows,
        settlement_index=_index(
            ("atlanta", "2026-07-22"),
            ("atlanta", "2026-07-23"),
            ("atlanta", "2026-08-01"),
        ),
        stratum="before_2026_07_31",
    )
    assert compact == []
    assert excluded == {
        "outside_provenance_stratum": 1,
        "reconstructed_snapshot": 1,
        "undated_snapshot": 1,
    }


def test_current_settlement_index_does_not_count_revisions_as_days(tmp_path):
    path = tmp_path / "atlanta" / "ledger.jsonl"
    path.parent.mkdir()
    rows = [
        {
            "event_slug": "event-1",
            "market_id": "atlanta",
            "target_date": "2026-07-22",
            "revision_number": 0,
            "promotion_countable": False,
        },
        {
            "event_slug": "event-1",
            "market_id": "atlanta",
            "target_date": "2026-07-22",
            "revision_number": 1,
            "promotion_countable": True,
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    index, inventory = load_current_settlement_index(tmp_path)
    assert index[("atlanta", "2026-07-22")]["promotion_countable"] is True
    assert inventory["raw_ledger_record_count"] == 2
    assert inventory["current_event_label_count"] == 1
    assert inventory["raw_ledger_reported_snapshot_sum"] == 0


def test_analysis_returns_curve_without_selecting_an_operating_point():
    raw = []
    raw += _snapshot(
        "atlanta", "2026-07-22", "s1", "2026-07-22T09:00:00-04:00",
        [0.1, 0.2, 0.7], [0.05, 0.9, 0.05], [0, 1, 0]
    )
    raw += _snapshot(
        "atlanta", "2026-07-23", "s2", "2026-07-23T09:00:00-04:00",
        [0.2, 0.6, 0.2], [0.2, 0.6, 0.2], [0, 1, 0]
    )
    compact, excluded = compact_replay_rows(
        raw,
        settlement_index=_index(
            ("atlanta", "2026-07-22"), ("atlanta", "2026-07-23")
        ),
        stratum="before_2026_07_31",
    )
    payload = analyze_compact_rows(
        compact,
        settlement_inventory={"raw_ledger_record_count": 2, "current_event_label_count": 2},
        source={"kind": "test"},
        excluded_snapshots=excluded,
        stratum="before_2026_07_31",
        bootstrap_replicates=30,
        bootstrap_seed=1,
    )
    assert payload["verdict"] == "STRUCTURE_FOUND_CHARACTERIZE_RULES"
    gap_30 = next(
        row for row in payload["tradeoff_curve"]
        if row["rule_family"] == "selected_band_gap" and row["threshold"] == 30.0
    )
    assert gap_30["severe_loss_recall"] == 1.0
    assert "operating_point" not in payload
    report = render_report(payload)
    assert "No operating point is selected" in report
    assert "Settlement and the realized outcome define" in report


def test_non_countable_settlement_is_excluded():
    rows = _snapshot(
        "atlanta", "2026-07-22", "s1", "2026-07-22T09:00:00-04:00",
        [0.5, 0.5], [0.5, 0.5], [1, 0]
    )
    index = _index(("atlanta", "2026-07-22"))
    index[("atlanta", "2026-07-22")]["promotion_countable"] = False
    compact, excluded = compact_replay_rows(
        rows, settlement_index=index, stratum="before_2026_07_31"
    )
    assert compact == []
    assert excluded == {"settlement_not_promotion_countable": 1}
