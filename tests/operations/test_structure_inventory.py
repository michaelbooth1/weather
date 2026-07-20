from pathlib import Path

from weather.operations.structure_inventory import (
    build_structure_inventory,
    compatibility_shims,
    render_report,
)


def _write(path: Path, lines: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"x_{idx} = {idx}" for idx in range(lines)) + "\n", encoding="utf-8")


def test_structure_inventory_counts_repo_areas_without_live_data_dependency(tmp_path):
    repo = tmp_path
    _write(repo / "src" / "weather" / "reporting" / "large.py", lines=6)
    _write(repo / "src" / "weather" / "reporting" / "small.py", lines=2)
    _write(repo / "src" / "weather" / "market" / "market.py", lines=3)
    _write(repo / "src" / "weather" / "release.py", lines=2)
    _write(repo / "tests" / "reporting" / "test_large.py", lines=4)
    _write(repo / "tests" / "test_release.py", lines=3)
    _write(repo / "app" / "views" / "overview.py", lines=5)
    _write(repo / "src" / "legacy_wrapper.py", lines=1)
    _write(repo / "app.py", lines=1)
    _write(repo / "backfill_all.py", lines=1)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "start_weather_dashboard.cmd").write_text("@echo off\n", encoding="utf-8")
    artifact = repo / "artifacts" / "models" / "demo.pkl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"1234")
    data_file = repo / "data" / "snapshots" / "demo.json"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("{}", encoding="utf-8")

    payload = build_structure_inventory(
        repo,
        tracked_files=[
            "src/weather/reporting/large.py",
            "src/weather/reporting/small.py",
            "src/weather/market/market.py",
            "src/weather/release.py",
            "tests/reporting/test_large.py",
            "tests/test_release.py",
            "app/views/overview.py",
            "README.md",
        ],
        source_root=repo / "src" / "weather",
        tests_root=repo / "tests",
        app_root=repo / "app",
        artifacts_root=repo / "artifacts",
        data_root=repo / "data",
        line_threshold=5,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )

    assert payload["schema_version"] == "structure_inventory_v0.2"
    assert payload["tracked_file_count"] == 8
    top = {row["area"]: row["tracked_files"] for row in payload["top_level_counts"]}
    assert top["src"] == 4
    assert top["tests"] == 2
    packages = {row["package"]: row for row in payload["source_packages"]}
    assert packages["reporting"]["python_files"] == 2
    assert packages["reporting"]["lines"] == 8
    assert packages["<root>"]["python_files"] == 1
    assert packages["<root>"]["lines"] == 2
    test_areas = {row["area"]: row for row in payload["test_areas"]}
    assert test_areas["<root>"]["python_files"] == 1
    assert test_areas["<root>"]["lines"] == 3
    assert payload["source_python_files"] == 4
    assert payload["source_lines"] == 13
    assert payload["test_python_files"] == 2
    assert payload["test_lines"] == 7
    assert payload["large_modules"][0]["path"] == "src/weather/reporting/large.py"
    assert payload["compatibility_shims"]["flat_src_wrappers"] == 1
    assert payload["compatibility_shims"]["root_streamlit_shims"] == 1
    assert payload["compatibility_shims"]["root_helper_shims"] == 1
    assert payload["compatibility_shims"]["root_script_shims"] == 1
    assert payload["compatibility_shims"]["paths"] == [
        "src/legacy_wrapper.py",
        "app.py",
        "backfill_all.py",
        "scripts/start_weather_dashboard.cmd",
    ]
    assert payload["artifacts"][0]["area"] == "models"
    assert payload["data"][0]["area"] == "snapshots"
    assert payload["data_budget_checks"]["checked"] is True
    assert payload["data_budget_checks"]["warning_count"] == 0
    assert payload["architecture_ratchet"]["status"] == "SKIPPED"


def test_repository_compatibility_shim_surfaces_are_retired():
    payload = compatibility_shims()

    assert payload["flat_src_wrappers"] == 0
    assert payload["root_streamlit_shims"] == 0
    assert payload["root_helper_shims"] == 0
    assert payload["root_script_shims"] == 0
    assert payload["total"] == 0
    assert payload["paths"] == []


def test_structure_inventory_can_skip_data_sizes(tmp_path):
    repo = tmp_path
    _write(repo / "src" / "weather" / "reporting" / "demo.py", lines=1)
    (repo / "data" / "snapshots").mkdir(parents=True)
    (repo / "data" / "snapshots" / "large.json").write_text("{}", encoding="utf-8")

    payload = build_structure_inventory(
        repo,
        tracked_files=["src/weather/reporting/demo.py"],
        source_root=repo / "src" / "weather",
        tests_root=repo / "tests",
        app_root=repo / "app",
        artifacts_root=repo / "artifacts",
        data_root=repo / "data",
        include_data_sizes=False,
    )

    assert payload["data_sizes_included"] is False
    assert payload["data"] == []
    assert payload["data_mib"] == 0


def test_structure_inventory_report_includes_key_sections(tmp_path):
    repo = tmp_path
    _write(repo / "src" / "weather" / "reporting" / "demo.py", lines=2)

    payload = build_structure_inventory(
        repo,
        tracked_files=["src/weather/reporting/demo.py"],
        source_root=repo / "src" / "weather",
        tests_root=repo / "tests",
        app_root=repo / "app",
        artifacts_root=repo / "artifacts",
        data_root=repo / "data",
        include_data_sizes=False,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )
    report = render_report(payload)

    assert "# Structure Inventory" in report
    assert "## Source Packages" in report
    assert "## Large Modules" in report
    assert "## Package Edges" in report
    assert "## Ignored Data Budget" in report
    assert "Data MiB: `skipped`" in report
    assert "with `--include-data-sizes`" in report


def test_structure_inventory_reports_package_edges(tmp_path):
    repo = tmp_path
    _write(repo / "src" / "weather" / "reporting" / "report.py", lines=1)
    (repo / "src" / "weather" / "reporting" / "report.py").write_text(
        "from weather.market.market_registry import all_specs\n",
        encoding="utf-8",
    )
    _write(repo / "src" / "weather" / "market" / "market_registry.py", lines=1)

    payload = build_structure_inventory(
        repo,
        tracked_files=[
            "src/weather/reporting/report.py",
            "src/weather/market/market_registry.py",
        ],
        source_root=repo / "src" / "weather",
        tests_root=repo / "tests",
        app_root=repo / "app",
        artifacts_root=repo / "artifacts",
        data_root=repo / "data",
        include_data_sizes=False,
    )

    edges = {row["edge"]: row for row in payload["package_edges"]}
    assert edges["reporting->market"]["file_count"] == 1
    assert edges["reporting->market"]["files"] == ["src/weather/reporting/report.py"]


def test_structure_inventory_reports_ignored_data_budget_warnings(tmp_path):
    repo = tmp_path
    _write(repo / "src" / "weather" / "reporting" / "demo.py", lines=1)
    data_file = repo / "data" / "snapshots" / "demo.json"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("{}", encoding="utf-8")

    payload = build_structure_inventory(
        repo,
        tracked_files=["src/weather/reporting/demo.py"],
        source_root=repo / "src" / "weather",
        tests_root=repo / "tests",
        app_root=repo / "app",
        artifacts_root=repo / "artifacts",
        data_root=repo / "data",
        data_budget_mib={"snapshots": 0},
    )

    warnings = payload["data_budget_checks"]["warnings"]
    assert payload["data_budget_checks"]["warning_count"] == 1
    assert warnings[0]["area"] == "snapshots"
    assert warnings[0]["threshold_mib"] == 0
    assert "outside the repo" in warnings[0]["recommendation"]

    report = render_report(payload)
    assert "## Ignored Data Budget" in report
    assert "snapshots" in report
