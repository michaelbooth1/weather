import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.reporting.research.workstation_morning_frontier import (
    CALIBRATION_MARGIN,
    MorningFrontierError,
    _holm_adjust,
    build_payload,
    main,
    render_report,
    validate_paths,
)


def _tracker(records, *, headline="MODEL CALIBRATED"):
    return {
        "verdict_cutoff": 9,
        "per_cutoff": {"9": {"records": records}},
        "verdict": {
            "headline": headline,
            "n": len(records),
            "reach_rate": 0.5,
            "model_reach": 0.4,
            "market_reach": 0.45,
            "gap": 0.1,
        },
    }


def _record(
    target_date,
    *,
    model_p,
    market_p,
    reached,
    settlement,
    model_median,
    market_median,
    settlement_source="daily_summary",
):
    return {
        "date": target_date,
        "model_reach": model_p,
        "market_reach": market_p,
        "reached": reached,
        "settlement": settlement,
        "model_median": model_median,
        "market_median": market_median,
        "settlement_source": settlement_source,
    }


def _write(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_payload_uses_equal_fleet_dates_and_normalizes_fahrenheit(tmp_path):
    _write(
        tmp_path / "toronto.json",
        _tracker(
            [
                _record("2026-06-21", model_p=0.2, market_p=0.4, reached=True,
                        settlement=25, model_median=23, market_median=24),
                _record("2026-06-22", model_p=0.7, market_p=0.6, reached=False,
                        settlement=24, model_median=25, market_median=24),
            ],
            headline="SKEPTICISM IS COSTING",
        ),
    )
    _write(
        tmp_path / "denver.json",
        _tracker(
            [
                _record("2026-06-21", model_p=0.4, market_p=0.5, reached=True,
                        settlement=90, model_median=86, market_median=88),
            ]
        ),
    )

    payload = build_payload(
        tmp_path,
        market_units={"toronto": "C", "denver": "F"},
        tune_end=date(2026, 6, 21),
        holdout_start=date(2026, 6, 22),
        cutoffs=(9,),
        bootstrap_replicates=100,
        bootstrap_seed=7,
    )

    tune = payload["by_cutoff"]["9"]["tune"]
    holdout = payload["by_cutoff"]["9"]["holdout"]
    assert tune["n_observations"] == 2
    assert tune["n_fleet_dates"] == 1
    # Toronto point delta is +1 C; Denver is (+2 F)*(5/9). Equal-market mean.
    expected = (1.0 + 2.0 * 5.0 / 9.0) / 2.0
    assert tune["equal_fleet_date"]["model_minus_market_point_abs_error_c"]["mean"] == pytest.approx(expected)
    assert holdout["n_observations"] == 1
    assert tune["sensitivities"]["complete_market_panel"]["n_observations"] == 2
    assert holdout["sensitivities"]["complete_market_panel"]["status"] == "BLOCK_NO_ROWS"
    assert payload["schema_version"] == "workstation_morning_frontier_v0.2"
    assert payload["design"]["selection_uses_holdout"] is False
    assert payload["input_integrity"]["status"] == "PASS"
    assert "Tune ends `2026-06-21`" in render_report(payload)


def test_city_selection_uses_tune_records_when_full_verdict_and_holdout_conflict(
    tmp_path,
):
    records = [
        _record(
            "2026-06-20",
            model_p=0.7,
            market_p=0.8,
            reached=True,
            settlement=30,
            model_median=29,
            market_median=30,
        ),
        _record(
            "2026-06-22",
            model_p=0.4,
            market_p=0.3,
            reached=False,
            settlement=27,
            model_median=29,
            market_median=28,
        ),
        _record(
            "2026-06-23",
            model_p=0.4,
            market_p=0.3,
            reached=False,
            settlement=27,
            model_median=29,
            market_median=28,
        ),
    ]
    # The source verdict intentionally represents the full corpus and conflicts
    # with the tune-only gap (+0.30). The holdout gap also reverses to -0.40.
    _write(tmp_path / "conflict-city.json", _tracker(records, headline="MODEL CALIBRATED"))

    payload = build_payload(
        tmp_path,
        market_units={"conflict-city": "C"},
        tune_end=date(2026, 6, 21),
        holdout_start=date(2026, 6, 22),
        cutoffs=(9,),
        bootstrap_replicates=100,
        bootstrap_seed=17,
    )

    city_analysis = payload["city_analysis"]
    city = city_analysis["cities"][0]
    assert city_analysis["status"] == "RETROSPECTIVE_SPLIT_RESPECTING_NOT_CONFIRMATORY"
    assert city_analysis["selected_markets"] == ["conflict-city"]
    assert city["tune_classification"] == "SKEPTICISM IS COSTING"
    assert city["reported_full_corpus_verdict_unused"]["headline"] == "MODEL CALIBRATED"
    assert city["reported_verdict_conflicts_with_tune_classification"] is True
    assert (
        city["tune"]["equal_fleet_date"]["outcome_minus_model_reach"]["mean"]
        > CALIBRATION_MARGIN
    )
    assert city["holdout"]["equal_fleet_date"]["outcome_minus_model_reach"]["mean"] == pytest.approx(-0.4)
    assert city_analysis["holdout_groups"]["tune_selected"]["n_observations"] == 2
    assert city_analysis["city_multiplicity"]["n_tests"] == 2
    report = render_report(payload)
    assert "retrospective, split-respecting diagnostic" in report
    assert "not a preregistered or untouched confirmation" in report


def test_holm_families_preserve_ties_and_expected_adjusted_values():
    fleet_tests = [
        {"cutoff": cutoff, "metric": metric, "raw_p": raw_p}
        for cutoff, metric, raw_p in (
            (7, "brier", 0.001),
            (7, "logloss", 0.001),
            (9, "brier", 0.001),
            (9, "logloss", 0.001),
            (11, "brier", 0.001),
            (11, "logloss", 0.001),
            (13, "brier", 0.03515625),
            (13, "logloss", 0.03515625),
        )
    ]
    fleet_adjusted = _holm_adjust(fleet_tests)
    cutoff_13 = [row for row in fleet_adjusted if row["cutoff"] == 13]
    assert [row["holm_adjusted_p"] for row in cutoff_13] == [
        pytest.approx(0.0703125),
        pytest.approx(0.0703125),
    ]

    city_tests = [
        {
            "market": "miami" if index < 2 else f"market-{index:02d}",
            "metric": "brier" if index % 2 == 0 else "logloss",
            "raw_p": 0.0018310546875 if index < 2 else 1.0,
        }
        for index in range(24)
    ]
    city_adjusted = _holm_adjust(city_tests)
    miami = [row for row in city_adjusted if row["market"] == "miami"]
    assert [row["holm_adjusted_p"] for row in miami] == [
        pytest.approx(0.0439453125),
        pytest.approx(0.0439453125),
    ]


def test_sensitivities_exclude_fallback_rows_and_incomplete_fleet_dates(tmp_path):
    fallback = _record(
        "2026-06-22",
        model_p=0.2,
        market_p=0.4,
        reached=True,
        settlement=25,
        model_median=23,
        market_median=24,
        settlement_source="snapshot_high",
    )
    daily = _record(
        "2026-06-22",
        model_p=0.3,
        market_p=0.5,
        reached=True,
        settlement=90,
        model_median=86,
        market_median=88,
    )
    _write(tmp_path / "toronto.json", _tracker([fallback]))
    _write(tmp_path / "denver.json", _tracker([daily]))

    payload = build_payload(
        tmp_path,
        market_units={"toronto": "C", "denver": "F"},
        tune_end=date(2026, 6, 21),
        holdout_start=date(2026, 6, 22),
        cutoffs=(9,),
        bootstrap_replicates=20,
        bootstrap_seed=11,
    )

    holdout = payload["by_cutoff"]["9"]["holdout"]
    assert holdout["n_observations"] == 2
    assert holdout["sensitivities"]["daily_summary_only"]["n_observations"] == 1
    assert holdout["sensitivities"]["complete_market_panel"]["n_observations"] == 2
    assert (
        holdout["sensitivities"]["daily_summary_complete_market_panel"]["status"]
        == "BLOCK_NO_ROWS"
    )


def test_missing_market_and_duplicate_records_fail_closed(tmp_path):
    _write(tmp_path / "toronto.json", _tracker([]))
    with pytest.raises(MorningFrontierError, match="missing forecast-tracker input"):
        build_payload(
            tmp_path,
            market_units={"toronto": "C", "denver": "F"},
            tune_end=date(2026, 6, 21),
            holdout_start=date(2026, 6, 22),
            cutoffs=(9,),
            bootstrap_replicates=10,
        )

    duplicate = _record(
        "2026-06-21", model_p=0.2, market_p=0.3, reached=True,
        settlement=25, model_median=24, market_median=25,
    )
    _write(tmp_path / "toronto.json", _tracker([duplicate, duplicate]))
    with pytest.raises(MorningFrontierError, match="duplicate market/cutoff/date"):
        build_payload(
            tmp_path,
            market_units={"toronto": "C"},
            tune_end=date(2026, 6, 21),
            holdout_start=date(2026, 6, 22),
            cutoffs=(9,),
            bootstrap_replicates=10,
        )


def test_invalid_probability_and_overlapping_split_fail_closed(tmp_path):
    _write(
        tmp_path / "toronto.json",
        _tracker(
            [_record("2026-06-21", model_p=1.2, market_p=0.3, reached=True,
                     settlement=25, model_median=24, market_median=25)]
        ),
    )
    with pytest.raises(MorningFrontierError, match=r"outside \[0, 1\]"):
        build_payload(
            tmp_path,
            market_units={"toronto": "C"},
            tune_end=date(2026, 6, 21),
            holdout_start=date(2026, 6, 22),
            cutoffs=(9,),
            bootstrap_replicates=10,
        )
    with pytest.raises(MorningFrontierError, match="must precede"):
        build_payload(
            tmp_path,
            market_units={"toronto": "C"},
            tune_end=date(2026, 6, 22),
            holdout_start=date(2026, 6, 22),
            cutoffs=(9,),
            bootstrap_replicates=10,
        )
    with pytest.raises(MorningFrontierError, match="fixed city-selection hour 9"):
        build_payload(
            tmp_path,
            market_units={"toronto": "C"},
            tune_end=date(2026, 6, 21),
            holdout_start=date(2026, 6, 22),
            cutoffs=(7,),
            bootstrap_replicates=10,
        )


def test_outputs_below_read_only_data_root_are_rejected_before_write(tmp_path):
    data_root = tmp_path / "data"
    input_dir = tmp_path / "inputs"
    data_root.mkdir()
    input_dir.mkdir()
    source = input_dir / "toronto.json"
    source.write_text("{}", encoding="utf-8")
    forbidden = data_root / "analysis" / "result.json"

    with pytest.raises(MorningFrontierError, match="outside the read-only data root"):
        validate_paths(
            read_only_data_root=data_root,
            input_dir=input_dir,
            source_files=[source],
            output_json=forbidden,
            output_report=tmp_path / "report.md",
        )

    assert not forbidden.parent.exists()

    with pytest.raises(MorningFrontierError, match="source report"):
        validate_paths(
            read_only_data_root=data_root,
            input_dir=input_dir,
            source_files=[source],
            output_json=source,
            output_report=tmp_path / "report.md",
        )

    hardlink = tmp_path / "source-hardlink.json"
    try:
        hardlink.hardlink_to(source)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")
    with pytest.raises(MorningFrontierError, match="source report"):
        validate_paths(
            read_only_data_root=data_root,
            input_dir=input_dir,
            source_files=[source],
            output_json=hardlink,
            output_report=tmp_path / "report.md",
        )


def test_main_validates_explicit_market_sources_before_writing(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    input_dir = tmp_path / "inputs"
    data_root.mkdir()
    input_dir.mkdir()
    (input_dir / "toronto.json").write_text("{}", encoding="utf-8")
    output_json = tmp_path / "result.json"
    output_report = tmp_path / "result.md"
    monkeypatch.setattr(
        "weather.reporting.research.workstation_morning_frontier.all_specs",
        lambda: [SimpleNamespace(id="toronto", display_unit="C")],
    )
    monkeypatch.setattr(
        "weather.reporting.research.workstation_morning_frontier.build_payload",
        lambda *args, **kwargs: {
            "status": "PASS",
            "input_integrity": {"market_count": 1},
        },
    )
    written = []
    monkeypatch.setattr(
        "weather.reporting.research.workstation_morning_frontier.write_outputs",
        lambda payload, json_path, report_path: written.append(
            (payload, json_path, report_path)
        ),
    )

    main(
        [
            "--read-only-data-root",
            str(data_root),
            "--input-dir",
            str(input_dir),
            "--output-json",
            str(output_json),
            "--output-report",
            str(output_report),
            "--tune-end",
            "2026-06-21",
            "--holdout-start",
            "2026-06-22",
        ]
    )
    assert written == [
        (
            {"status": "PASS", "input_integrity": {"market_count": 1}},
            output_json,
            output_report,
        )
    ]
