from __future__ import annotations

import json
from pathlib import Path

import pytest

from weather.paths import DATA_ROOT
from weather.reporting.scorecards.detectable_win_power import (
    DetectableWinPowerError,
    INPUT_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    build_power_design,
    main,
    minimum_detectable_effect,
    one_sided_clustered_t_power,
    render_markdown,
    required_cluster_count,
    validate_design_input,
    write_power_design,
)
from weather.schema_registry import REGISTERED_SCHEMAS


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "detectable_win_power_design_v0.1.json"
)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    return build_power_design(
        load_fixture(),
        generated_at_utc="2026-08-03T00:00:00+00:00",
        simulation_repetitions=10_000,
    )


def test_clustered_t_power_inverts_to_mde_and_required_n() -> None:
    standard_deviation = 0.005991632921640033
    detectable = minimum_detectable_effect(14, standard_deviation)
    assert detectable == pytest.approx(0.004206460533435848)
    assert one_sided_clustered_t_power(14, detectable, standard_deviation) == pytest.approx(
        0.8
    )
    assert required_cluster_count(0.0011507019411383013, standard_deviation) == 169
    assert required_cluster_count(0.0, standard_deviation) is None
    assert (
        required_cluster_count(
            0.0011507019411383013,
            0.009722955233244698,
            degrees_of_freedom_cap=11,
        )
        == 504
    )


def test_fourteen_days_are_not_powered_for_primary_served_effect(report: dict) -> None:
    primary = next(
        item for item in report["endpoint_power"] if item["id"] == "primary_09_14_brier"
    )
    fleet = primary["populations"]["fleet"]
    assert fleet["current_window"]["minimum_detectable_effect"] == pytest.approx(
        0.006898949715109472
    )
    assert fleet["current_window"]["minimum_detectable_fraction_of_baseline"] == pytest.approx(
        0.3229722098
    )
    assert fleet["planning_effect"]["required_date_clusters_at_upper"] == 504
    assert fleet["planning_effect"]["required_date_clusters_at_midpoint"] == 2337
    assert fleet["planning_effect"]["required_date_clusters_at_zero"] is None


def test_endpoint_table_distinguishes_fleet_and_toronto(report: dict) -> None:
    by_id = {item["id"]: item for item in report["endpoint_power"]}
    assert by_id["pooled_brier"]["populations"]["fleet"]["planning_effect"][
        "required_date_clusters_at_upper"
    ] == 53
    assert by_id["primary_09_14_brier"]["populations"]["toronto"][
        "planning_effect"
    ]["required_date_clusters_at_upper"] == 3350
    assert by_id["severe_tail_sse"]["populations"]["fleet"]["planning_effect"][
        "required_date_clusters_at_upper"
    ] == 4
    assert by_id["severe_tail_sse"]["populations"]["toronto"]["planning_effect"][
        "required_date_clusters_at_upper"
    ] == 69


def test_reservation_recommendation_is_exact_and_primary_bound(report: dict) -> None:
    reservation = report["reservation"]
    assert reservation["recommendation"] == "EXTEND_NOW"
    assert reservation["additional_start"] == "2026-08-20"
    assert reservation["additional_end"] == "2027-12-22"
    assert reservation["additional_days"] == 490
    assert reservation["total_reserved_days"] == 504
    assert reservation["point_estimate_required_days_for_upper_effect"] == 504
    assert reservation["point_estimate_buffer_days"] == 0


def test_raw_slice_bar_is_a_lottery_and_max_t_controls_familywise_error(
    report: dict,
) -> None:
    sensitivity = report["slice_gate"]["false_rejection_sensitivity"]
    for simulation in sensitivity.values():
        assert simulation["observed_slice_count"] == 54
        assert simulation["raw_point_bar_false_rejection_rate_54_slices"] > 0.99
        assert simulation["raw_point_bar_false_rejection_rate_53_slices_min"] > 0.99
        assert simulation["max_t_boundary_familywise_error"] == pytest.approx(0.05)
        assert simulation["max_t_uniformly_better_false_rejection_rate"] <= 0.05
    assert report["slice_gate"]["verdict"] == "UNACCEPTABLE_LOTTERY"


def test_markdown_leads_with_action_and_matches_primary(report: dict) -> None:
    markdown = render_markdown(report)
    assert markdown.index("## Reservation recommendation") < markdown.index(
        "## Expected served effect"
    )
    assert "Extend now by 490 days" in markdown
    assert "Fleet 09:00-14:00 paired daily-first Brier difference" in markdown
    assert "99." in markdown


def test_writer_keeps_json_and_markdown_under_declared_root(
    report: dict, tmp_path: Path
) -> None:
    json_path, markdown_path = write_power_design(report, run_root=tmp_path / "run")
    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert markdown_path.read_text(encoding="utf-8") == render_markdown(report)


def test_writer_rejects_data_root_before_writing(report: dict) -> None:
    blocked = DATA_ROOT / "forbidden-power-output"
    with pytest.raises(DetectableWinPowerError, match="outside data"):
        write_power_design(report, run_root=blocked)
    assert not blocked.exists()


def test_validation_rejects_snapshot_style_or_incomplete_inputs() -> None:
    payload = load_fixture()
    payload["endpoints"][1]["populations"]["fleet"]["cluster_deltas"] = [0.1, 0.2]
    with pytest.raises(DetectableWinPowerError, match="date clusters"):
        validate_design_input(payload)

    payload = load_fixture()
    payload["slice_gate"]["dimension_slice_counts"]["market"][0] -= 1
    with pytest.raises(DetectableWinPowerError, match="do not partition"):
        validate_design_input(payload)


def test_cli_writes_standalone_design(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_root = tmp_path / "standalone"
    assert (
        main(
            [
                "--input",
                str(FIXTURE),
                "--run-root",
                str(run_root),
                "--simulation-repetitions",
                "2000",
            ]
        )
        == 0
    )
    payload = json.loads((run_root / "detectable-win-power.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["input_file_sha256"]
    assert payload["report_sha256"]
    assert "EXTEND_NOW" in capsys.readouterr().out


def test_schemas_are_registered_and_fixture_is_aggregate_only() -> None:
    versions = {spec.version for spec in REGISTERED_SCHEMAS}
    assert INPUT_SCHEMA_VERSION in versions
    assert REPORT_SCHEMA_VERSION in versions
    fixture_text = FIXTURE.read_text(encoding="utf-8")
    assert "C:\\Users" not in fixture_text
    assert "snapshot_id" not in fixture_text
