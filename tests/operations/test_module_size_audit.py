from pathlib import Path

from weather.operations.module_size_audit import (
    build_module_size_audit,
    render_report,
)


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


def test_module_size_report_includes_ownership_map(tmp_path):
    root = tmp_path / "src" / "weather"
    root.mkdir(parents=True)
    (root / "demo.py").write_text("x = 1\n", encoding="utf-8")

    payload = build_module_size_audit(root, generated_at_utc="2026-06-20T00:00:00+00:00")
    report = render_report(payload)

    assert "# Module Size Audit" in report
    assert "src/weather/calibration/pooled_feature_model.py" in report
