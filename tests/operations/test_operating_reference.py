"""Tests for the generated operating reference."""

from __future__ import annotations

import pytest

from weather.operations import operating_reference


def test_every_listed_constant_resolves_to_a_live_value():
    """The whole point: a renamed or deleted constant must fail loudly, not print stale."""
    rows = operating_reference.collect_constants()

    assert len(rows) == len(operating_reference.GOVERNING_CONSTANTS)
    for row in rows:
        assert row["value"] is not None
        assert row["source_file"], f"{row['attribute']} has no resolvable source file"
        assert row["line"], f"{row['attribute']} assignment line was not located"


def test_a_missing_constant_raises_with_an_actionable_message():
    spec = operating_reference.ConstantSpec(
        "weather.collection.collection_health",
        "THIS_CONSTANT_DOES_NOT_EXIST",
        "meaning",
        "matters",
    )

    with pytest.raises(AttributeError) as excinfo:
        operating_reference._module_and_line(spec)

    assert "no longer exists" in str(excinfo.value)
    assert "GOVERNING_CONSTANTS" in str(excinfo.value)


def test_the_graded_window_agrees_with_the_settlement_coverage_window():
    """A disagreement here is a real defect, not a documentation nit.

    The streak verdict window and the settlement material-coverage window describe the
    same hours. If they drift apart, one of the two subsystems is grading a different
    day than the other.
    """
    rows = {row["attribute"]: row["value"] for row in operating_reference.collect_constants()}

    start = rows["AFTERNOON_START_HOUR"]
    end = rows["AFTERNOON_END_HOUR"]
    declared = rows["MATERIAL_COVERAGE_WINDOW"]

    assert declared.startswith(f"{start:02d}:00-{end:02d}:00"), (
        f"settlement declares '{declared}' but the graded window is {start:02d}:00-{end:02d}:00"
    )


def test_render_includes_windows_constants_and_the_regeneration_command():
    markdown = operating_reference.render_markdown(operating_reference.collect_constants())

    assert "Generated — do not hand-edit" in markdown
    assert "weather.operations.operating_reference" in markdown
    assert "AFTERNOON_START_HOUR" in markdown
    assert "COMPLETE_DAY_MIN_ROWS" in markdown
    assert "12:00-18:00 local" in markdown
    assert "01:00-04:00 local" in markdown


def test_tracked_reference_points_to_runtime_schedule_without_embedding_it():
    markdown = operating_reference.render_markdown(operating_reference.collect_constants())

    assert "data/alerts/OPERATING_SCHEDULE.md" in markdown
    assert "WeatherAlpha" not in markdown


def test_runtime_schedule_lists_every_scheduled_trigger_given_one():
    schedule = [
        {"name": "WeatherAlpha", "at": "01:20"},
        {"name": "WeatherBeta", "at": "08:10"},
    ]

    markdown = operating_reference.render_schedule_markdown(schedule)

    assert "WeatherAlpha" in markdown
    assert "01:20" in markdown
    assert "WeatherBeta" in markdown
    assert "Generated runtime state" in markdown
    assert "receipt" in markdown
