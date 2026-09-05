from unittest import mock

from weather.reporting.roadmap.project_overview import collect_project_overview, MAKER_ITEM


@mock.patch("weather.reporting.roadmap.project_overview.subprocess.run")
def test_project_overview_uses_canonical_next_steps_and_ledger(tmp_git, tmp_path):
    tmp_git.return_value = mock.Mock(returncode=0, stdout="a" * 40 + "\t2026-09-05\tPrepare test\n")
    state = tmp_path / "docs/operations/STATE_OF_PLAY.md"
    state.parent.mkdir(parents=True)
    state.write_text("**Last rewritten: 2026-09-05.**\n\n**Objectives:** Observe the project.\n\n"
                     "## Ordered critical path\n\n1. Prepare the next\n   attended stage.\n2. Reconcile fills.\n\n"
                     "## Standing decisions\nDo not count this as a next step.\n")
    maker = tmp_path / MAKER_ITEM
    maker.parent.mkdir(parents=True)
    maker.write_text("### W4 — Accounting\n\n| W4 | PARTIAL: matched receipts. | Reconcile wallet credits. |\n", encoding="utf-8")
    result = collect_project_overview(tmp_path)
    assert result["objective"] == "Observe the project."
    assert result["next_steps"] == ["Prepare the next attended stage.", "Reconcile fills."]
    assert result["workstreams"][0]["title"] == "Accounting"
    assert result["workstreams"][0]["next_action"] == "Reconcile wallet credits."
    assert result["source"]["head"] == "a" * 40


@mock.patch("weather.reporting.roadmap.project_overview.subprocess.run", side_effect=OSError)
def test_missing_project_sources_are_explicit(_git, tmp_path):
    result = collect_project_overview(tmp_path)
    assert result["available"] is False
    assert result["next_steps"] == []
    assert result["source"]["head"] is None
