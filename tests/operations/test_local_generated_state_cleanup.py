import json

from weather.operations.local_generated_state_cleanup import (
    build_cleanup_report,
    dependency_pin_sync,
    render_report,
)


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def write_dependency_files(root, *, pyproject_deps, requirements):
    write_text(
        root / "pyproject.toml",
        "[project]\n"
        "name = \"weather-market\"\n"
        "dependencies = [\n"
        + "".join(f"    \"{dependency}\",\n" for dependency in pyproject_deps)
        + "]\n",
    )
    write_text(
        root / "requirements.txt",
        "\n".join(requirements) + "\n",
    )


def test_cleanup_report_classifies_local_state_without_deleting(tmp_path):
    write_bytes(tmp_path / ".pytest_cache" / "v" / "cache" / "nodeids", b"[]")
    write_bytes(tmp_path / ".ruff_cache" / "0.15.17" / "entry", b"cache")
    write_bytes(tmp_path / "src" / "weather_market.egg-info" / "PKG-INFO", b"metadata")
    write_bytes(tmp_path / "pkg" / "__pycache__" / "module.cpython-311.pyc", b"bytecode")
    write_text(tmp_path / "scratch" / "no_market_location_fast_audit.py", "print('legacy')\n")
    write_text(tmp_path / "scratch" / "no_market_location_fast_audit.md", "# Finding\n")
    write_bytes(tmp_path / "docs" / "crlf.md", b"# Title\r\nbody\r\n")
    write_text(tmp_path / ".gitattributes", "* text=auto eol=lf\n")
    write_dependency_files(
        tmp_path,
        pyproject_deps=["numpy==2.4.6", "requests==2.34.2"],
        requirements=["numpy==2.4.6", "requests==2.34.2"],
    )
    write_text(
        tmp_path / "tools" / "research" / "research_harness.py",
        "SCRIPT_INVENTORY = {\n"
        "    'legacy.py': {'status': 'retired', 'smoke': 'help', 'notes': 'kept sentinel'},\n"
        "    'research_harness.py': {'status': 'supported', 'smoke': 'help', 'notes': 'harness'},\n"
        "}\n"
        "def validate_inventory(root=None):\n"
        "    return []\n",
    )
    write_text(tmp_path / "tools" / "research" / "legacy.py", "print('retired')\n")

    payload = build_cleanup_report(
        tmp_path,
        generated_at_utc="2026-06-21T00:00:00+00:00",
    )
    report = render_report(payload)

    assert payload["schema_version"] == "local_generated_state_cleanup_v0.1"
    assert payload["dry_run_only"] is True
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["safe_cache_summary"]["root_count"] == 4
    assert payload["scratch_review"]["file_count"] == 2
    assert payload["research_review"]["status_counts"]["retired"] == 1
    assert payload["dependency_pin_sync"]["in_sync"] is True
    assert payload["line_endings"]["crlf_file_count"] == 1
    assert "no_market_location_fast_audit.py" in json.dumps(payload["scratch_review"])
    assert "Local Generated State Cleanup Dry Run" in report
    assert "delete_after_active_work_finishes" in report


def test_dependency_pin_sync_reports_missing_and_mismatched_dependencies(tmp_path):
    write_dependency_files(
        tmp_path,
        pyproject_deps=["numpy==2.4.6", "requests==2.34.2"],
        requirements=["numpy==2.4.6", "requests==2.35.0", "pandas==3.0.3"],
    )

    payload = dependency_pin_sync(tmp_path)

    assert payload["status"] == "WARN"
    assert payload["in_sync"] is False
    assert payload["missing_from_pyproject"] == ["pandas"]
    assert payload["mismatched_versions"] == ["requests"]
