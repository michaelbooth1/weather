from weather.operations.agent_docs_audit import (
    audit_repo,
    broken_local_links,
    legacy_command_matches,
)


def test_agent_docs_audit_passes_repository_contracts():
    assert audit_repo() == []


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
