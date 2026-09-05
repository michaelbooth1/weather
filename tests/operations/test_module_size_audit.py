import re
from pathlib import Path

from weather.operations import module_size_audit
from weather.operations.module_size_audit import (
    DEFAULT_SOURCE_ROOT,
    build_module_size_audit,
    render_report,
)
from weather.paths import REPO_ROOT


def test_module_size_audit_warns_for_modules_above_threshold(tmp_path):
    root = tmp_path / "src" / "weather"
    package = root / "reporting"
    package.mkdir(parents=True)
    (package / "small.py").write_text("x = 1\n", encoding="utf-8")
    (package / "large.py").write_text("\n".join(f"x_{idx} = {idx}" for idx in range(5)), encoding="utf-8")

    payload = build_module_size_audit(root, warning_lines=5, generated_at_utc="2026-06-20T00:00:00+00:00")

    rows = {Path(row["path"]).name: row for row in payload["largest_modules"]}
    assert payload["schema_version"] == "module_size_audit_v0.1"
    assert rows["large.py"]["status"] == "WARN"
    assert rows["small.py"]["status"] == "OK"
    assert payload["warning_count"] == 1
    assert payload["governance_status"] == "WARN"
    assert any(
        row["kind"] == "warning_metadata_missing" and Path(row["path"]).name == "large.py"
        for row in payload["governance_errors"]
    )


def test_module_size_report_includes_ownership_map(tmp_path):
    root = tmp_path / "src" / "weather"
    root.mkdir(parents=True)
    (root / "demo.py").write_text("x = 1\n", encoding="utf-8")

    payload = build_module_size_audit(root, generated_at_utc="2026-06-20T00:00:00+00:00")
    report = render_report(payload)

    assert "# Module Size Audit" in report
    assert "src/weather/calibration/pooled_feature_model.py" in report


def test_current_warning_modules_have_complete_ownership_metadata_and_no_orphans():
    payload = build_module_size_audit(
        DEFAULT_SOURCE_ROOT,
        generated_at_utc="2026-07-12T00:00:00+00:00",
    )

    warnings = [row for row in payload["largest_modules"] if row["status"] == "WARN"]
    # The named allowance below rejects new warnings while permitting reductions.
    # Ensure the report's bounded largest-module view covers every warning.
    assert len(warnings) == payload["warning_count"]
    assert all(row["owner"] and row["boundary"] and row["next_split"] for row in warnings)
    assert payload["governance_status"] == "PASS"
    assert payload["governance_errors"] == []


def test_current_warnings_stay_within_reviewed_ownership_allowance():
    payload = build_module_size_audit(DEFAULT_SOURCE_ROOT)
    document = (REPO_ROOT / "docs/operations/module-ownership-map.md").read_text(encoding="utf-8")

    summary = re.search(
        r"^- Allowed warning modules: (?P<modules>.+?)\n- A module",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert summary is not None
    documented = set(re.findall(r"`([^`]+)`", summary.group("modules")))
    expected = {
        row["path"].removeprefix("src/").removesuffix(".py").replace("/", ".")
        for row in payload["largest_modules"]
        if row["status"] == "WARN"
    }
    assert expected <= documented, f"New warnings require reviewed ownership: {sorted(expected - documented)}"


def test_reducing_owned_module_debt_passes_but_replacement_unowned_warning_fails(tmp_path, monkeypatch):
    root = tmp_path / "src" / "weather"
    root.mkdir(parents=True)
    owned = root / "owned.py"
    owned.write_text("x = 1\n" * 5, encoding="utf-8")
    monkeypatch.setattr(module_size_audit, "OWNERSHIP_NOTES", {
        module_size_audit.relative_to_repo(owned): {
            "owner": "operations",
            "boundary": "Bounded fixture orchestration.",
            "next_split": "Remove obsolete orchestration.",
        },
    })

    initial = build_module_size_audit(root, warning_lines=5)
    assert initial["warning_count"] == 1
    assert initial["governance_status"] == "PASS"

    owned.write_text("x = 1\n", encoding="utf-8")
    reduced = build_module_size_audit(root, warning_lines=5)
    assert reduced["warning_count"] == 0
    assert reduced["governance_status"] == "PASS"

    (root / "unowned.py").write_text("x = 1\n" * 5, encoding="utf-8")
    replacement = build_module_size_audit(root, warning_lines=5)
    assert replacement["warning_count"] == initial["warning_count"]
    assert replacement["governance_status"] == "WARN"
    assert any(
        row["kind"] == "warning_metadata_missing" and Path(row["path"]).name == "unowned.py"
        for row in replacement["governance_errors"]
    )
