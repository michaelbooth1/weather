"""Tests for the maker countability post-mortem."""

from __future__ import annotations

import json

from weather.reporting.market import mm_countability_postmortem as postmortem


def _write_run(day_dir, run_id, *, counted, incidents=None, raw=None):
    run_dir = day_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / postmortem.REMEDIATION_NAME
    if raw is not None:
        target.write_text(raw, encoding="utf-8")
        return run_dir
    payload = {
        "counts_toward_live_forward_gate": counted,
        "incidents": incidents or [],
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    return run_dir


def _incident(gate, root_cause, market, *, can_still_count=False):
    return {
        "gate": gate,
        "root_cause": root_cause,
        "market_id": market,
        "can_still_count_live_forward_day": can_still_count,
    }


def test_day_counts_when_any_run_counts(tmp_path):
    day = tmp_path / "2026-08-01"
    _write_run(day, "run_a", counted=False, incidents=[_incident("model_freshness", "stale_model_row", "toronto")])
    _write_run(day, "run_b", counted=True)

    report = postmortem.build_postmortem(tmp_path)

    assert report["total_days"] == 1
    assert report["counted_days"] == 1
    assert report["days"][0]["counted"] is True
    assert report["days"][0]["counted_runs"] == 1
    assert report["days"][0]["runs"] == 2


def test_uncounted_day_is_reported_with_its_blocker(tmp_path):
    day = tmp_path / "2026-08-02"
    _write_run(day, "run_a", counted=False, incidents=[_incident("model_freshness", "stale_model_row", "denver")])

    report = postmortem.build_postmortem(tmp_path)

    assert report["counted_days"] == 0
    assert report["uncounted_days"] == 1
    assert report["countable_day_yield"] == 0.0
    assert report["blockers"][0]["gate"] == "model_freshness"
    assert report["blockers"][0]["root_cause"] == "stale_model_row"
    assert report["markets"][0]["market_id"] == "denver"


def test_incident_that_still_counts_is_not_a_blocker(tmp_path):
    day = tmp_path / "2026-08-03"
    _write_run(
        day,
        "run_a",
        counted=True,
        incidents=[_incident("clob_freshness", "minor_gap", "miami", can_still_count=True)],
    )

    report = postmortem.build_postmortem(tmp_path)

    assert report["counted_days"] == 1
    assert report["blockers"] == []
    assert report["markets"] == []


def test_first_and_last_seen_bracket_a_regression(tmp_path):
    for day_name in ("2026-06-25", "2026-06-26", "2026-06-27"):
        day = tmp_path / day_name
        _write_run(day, "run_a", counted=True)
    for day_name in ("2026-06-28", "2026-06-29"):
        day = tmp_path / day_name
        _write_run(
            day,
            "run_a",
            counted=False,
            incidents=[_incident("fill_evidence", "no_quote_legs", "toronto")],
        )

    report = postmortem.build_postmortem(tmp_path)

    assert report["total_days"] == 5
    assert report["counted_days"] == 3
    blocker = report["blockers"][0]
    assert blocker["root_cause"] == "no_quote_legs"
    assert blocker["first_seen"] == "2026-06-28"
    assert blocker["last_seen"] == "2026-06-29"
    assert blocker["days_affected"] == 2


def test_missing_and_unparseable_files_are_never_silently_dropped(tmp_path):
    day = tmp_path / "2026-08-04"
    (day / "run_missing").mkdir(parents=True)
    _write_run(day, "run_bad", counted=False, raw="{not json")

    report = postmortem.build_postmortem(tmp_path)

    assert report["days"][0]["runs"] == 2
    assert report["counted_days"] == 0
    causes = {row["root_cause"] for row in report["blockers"]}
    assert postmortem.NO_REMEDIATION in causes
    assert postmortem.UNPARSEABLE in causes


def test_day_level_quarantine_scaffolding_is_not_counted_as_a_run(tmp_path):
    day = tmp_path / "2026-08-04"
    _write_run(
        day,
        "run_a",
        counted=False,
        incidents=[_incident("model_freshness", "stale_model_row", "toronto")],
    )
    (day / postmortem.QUARANTINE_DIR_NAME / "retired_run").mkdir(parents=True)
    (day / ".launch_state").mkdir()

    report = postmortem.build_postmortem(tmp_path)

    assert report["days"][0]["runs"] == 1
    causes = {row["root_cause"] for row in report["blockers"]}
    assert postmortem.NO_REMEDIATION not in causes


def test_gate_repair_counterfactual_keeps_other_and_missing_blockers(tmp_path):
    repaired = tmp_path / "2026-08-01"
    _write_run(
        repaired,
        "run_a",
        counted=False,
        incidents=[_incident("model_freshness", "stale_model_row", "toronto")],
    )
    mixed = tmp_path / "2026-08-02"
    _write_run(
        mixed,
        "run_a",
        counted=False,
        incidents=[
            _incident("model_freshness", "stale_model_row", "toronto"),
            _incident("release_binding", "wrong_release", "toronto"),
        ],
    )
    missing = tmp_path / "2026-08-03"
    (missing / "run_missing").mkdir(parents=True)

    report = postmortem.build_gate_repair_counterfactual(
        tmp_path,
        repaired_gates=["model_freshness"],
    )

    assert report["counted_days"] == 1
    assert report["total_days"] == 3
    assert report["days"][0]["counted"] is True
    assert report["days"][1]["counted"] is False
    assert report["days"][2]["counted"] is False


def test_non_day_directories_are_ignored(tmp_path):
    (tmp_path / "_quarantine").mkdir()
    (tmp_path / "daily_roll_status.json").write_text("{}", encoding="utf-8")
    day = tmp_path / "2026-08-05"
    _write_run(day, "run_a", counted=True)

    report = postmortem.build_postmortem(tmp_path)

    assert report["total_days"] == 1
    assert report["first_day"] == "2026-08-05"


def test_empty_root_does_not_divide_by_zero(tmp_path):
    report = postmortem.build_postmortem(tmp_path)

    assert report["total_days"] == 0
    assert report["countable_day_yield"] is None
    assert "n/a" in postmortem.render_markdown(report)


def test_markdown_renders_every_day_and_blocker(tmp_path):
    day = tmp_path / "2026-08-06"
    _write_run(day, "run_a", counted=False, incidents=[_incident("model_freshness", "stale_model_row", "toronto")])

    markdown = postmortem.render_markdown(postmortem.build_postmortem(tmp_path))

    assert "Maker countability post-mortem" in markdown
    assert "2026-08-06" in markdown
    assert "stale_model_row" in markdown
    assert "0 of 1 maker days counted" in markdown
