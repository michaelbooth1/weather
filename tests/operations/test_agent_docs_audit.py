import datetime as dt
import subprocess
from pathlib import Path

from weather.operations.agent_docs_audit import (
    LINE_BUDGETS,
    NESTED_AGENT_FILE_LINE_BUDGET,
    _agent_files,
    _markdown_files,
    audit_repo,
    broken_local_links,
    legacy_command_matches,
    line_budget_errors,
    retired_claim_errors,
    state_of_play_age_errors,
    unindexed_operations_docs,
)


def test_agent_docs_audit_passes_repository_contracts():
    assert audit_repo() == []


def test_repository_markdown_scope_excludes_ignored_sibling_worktrees():
    root = Path.cwd()
    markdown = _markdown_files(root)
    agents = _agent_files(root)
    listed = subprocess.run(
        [
            "git", "ls-files", "-z", "--cached", "--others",
            "--exclude-standard", "--", "*.md",
        ],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    expected = {root / path.decode() for path in listed if path}

    assert set(markdown) == expected
    assert len(agents) == sum(path.name == "AGENTS.md" for path in expected)
    assert all(".claude/worktrees" not in path.as_posix() for path in markdown)


def test_broken_local_links_reports_missing_target(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("[missing](other.md)\n", encoding="utf-8")

    assert broken_local_links(tmp_path, [doc]) == [
        "guide.md: missing link target: other.md"
    ]


def test_broken_local_links_ignores_link_shaped_powershell_in_fences(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text(
        "```powershell\n"
        '$paused = ([string](Get-ScheduledTask -TaskName "WeatherDataMirror").State)\n'
        "```\n"
        "[missing](outside.md)\n",
        encoding="utf-8",
    )

    assert broken_local_links(tmp_path, [doc]) == [
        "guide.md: missing link target: outside.md"
    ]


def test_broken_local_links_preserves_exact_historical_exclusion(tmp_path):
    doc = (
        tmp_path
        / "docs"
        / "roadmap"
        / "agent-report-2026-08-02-workstation-spec-contract-repair.md"
    )
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "[historical](../../src/weather/reporting/validation/"
        "floor_retrain_gate_harness.py#L1079)\n",
        encoding="utf-8",
    )

    assert broken_local_links(tmp_path, [doc]) == []


def test_legacy_command_scan_rejects_root_script_shims_but_allows_canonical_paths():
    legacy_register = ".\\" + "scripts\\" + "register_daily_refresh.ps1"
    legacy_launcher = ".\\" + "scripts\\" + "start_weather_dashboard.cmd"
    assert legacy_command_matches(legacy_register)
    assert legacy_command_matches(legacy_launcher)
    assert legacy_command_matches(r".\scripts\ops\register_daily_refresh.ps1") == []
    assert legacy_command_matches(r".\scripts\launch\start_weather_dashboard.cmd") == []


def test_line_budget_flags_an_always_loaded_file_that_grew(tmp_path):
    root = tmp_path.resolve()
    (root / "AGENTS.md").write_text("rule\n" * (LINE_BUDGETS["AGENTS.md"] + 1), encoding="utf-8")
    nested = root / "pkg" / "AGENTS.md"
    nested.parent.mkdir()
    nested.write_text("rule\n" * NESTED_AGENT_FILE_LINE_BUDGET, encoding="utf-8")

    errors = line_budget_errors(root)

    assert len(errors) == 1
    assert errors[0].startswith("AGENTS.md: ")
    assert "exceeds the always-loaded budget" in errors[0]


def test_operations_docs_must_be_linked_from_an_index(tmp_path):
    root = tmp_path.resolve()
    operations = root / "docs" / "operations"
    operations.mkdir(parents=True)
    (operations / "README.md").write_text("[linked](LINKED.md)\n", encoding="utf-8")
    (root / "docs" / "README.md").write_text(
        "[other](operations/FROM_DOCS_INDEX.md)\n", encoding="utf-8"
    )
    for name in ("LINKED.md", "FROM_DOCS_INDEX.md", "ORPHAN.md"):
        (operations / name).write_text("# doc\n", encoding="utf-8")

    assert unindexed_operations_docs(root) == [
        "docs/operations/ORPHAN.md: not linked from docs/operations/README.md or docs/README.md"
    ]


def test_retired_claim_is_rejected_outside_the_retraction_record(tmp_path):
    root = tmp_path.resolve()
    current = root / "AGENTS.md"
    current.write_text("fine\nthe streak is the #1 operational objective\n", encoding="utf-8")
    record = root / "docs" / "operations" / "RETRACTED_AND_FALSE_LEADS.md"
    record.parent.mkdir(parents=True)
    record.write_text("we used to say: the #1 operational objective\n", encoding="utf-8")

    errors = retired_claim_errors(root, [current, record])

    assert len(errors) == 1
    assert errors[0].startswith("AGENTS.md:2: retired claim")


def test_state_of_play_age_is_measured_from_its_declared_date(tmp_path):
    root = tmp_path.resolve()
    state = root / "docs" / "operations" / "STATE_OF_PLAY.md"
    state.parent.mkdir(parents=True)
    state.write_text("# State of play\n\n**Last updated: 2026-09-13 America/Toronto.**\n", encoding="utf-8")

    fresh = state_of_play_age_errors(root, today=dt.date(2026, 9, 16), max_age_days=3)
    stale = state_of_play_age_errors(root, today=dt.date(2026, 9, 19), max_age_days=3)

    assert fresh == []
    assert len(stale) == 1 and "6 days old" in stale[0]

    state.write_text("# State of play\n\nno date here\n", encoding="utf-8")
    assert "no parseable" in state_of_play_age_errors(
        root, today=dt.date(2026, 9, 19), max_age_days=3
    )[0]
