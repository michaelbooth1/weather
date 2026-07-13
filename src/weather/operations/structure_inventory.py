"""Repository structure inventory for growth and architecture audits."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import ARTIFACTS_ROOT, DATA_ROOT, REPO_ROOT, data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("structure_inventory")
DEFAULT_OUT = data_path("backtest", "structure_inventory.json")
DEFAULT_REPORT = data_path("backtest", "structure_inventory_report.md")
DEFAULT_LINE_THRESHOLD = 1_000
DEFAULT_OTHER_DATA_BUDGET_MIB = 1_000
DEFAULT_DATA_BUDGET_MIB = {
    "backtest": 2_000,
    "metar": 2_000,
    "noaa_ghcnh": 5_000,
    "snapshots": 50_000,
    "wunderground": 2_000,
}

DEFAULT_ROOT_STREAMLIT_SHIMS = (
    "app.py",
)
DEFAULT_ROOT_HELPER_SHIMS = (
    "backfill_all.py",
    "scratch.py",
    "train_all_markets.ps1",
)
ROOT_AREA_NAME = "<root>"
PACKAGE_ROOTS = {
    "backtesting",
    "calibration",
    "collection",
    "market",
    "model",
    "operations",
    "reporting",
    "sources",
}
SHARED_PACKAGE_ROOTS = {
    "artifacts",
    "io",
    "paths",
    "schema_registry",
    "scoring",
    "time",
    "units",
    "variant_registry",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative(path: str | Path, root: str | Path) -> str:
    path = Path(path)
    root = Path(root)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix().replace("\\", "/")


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _line in handle)
    except (OSError, UnicodeDecodeError):
        return 0


def git_tracked_files(repo_root: str | Path = REPO_ROOT) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _group_top_level(tracked_files: list[str]) -> list[dict]:
    counts = Counter(path.split("/", 1)[0] for path in tracked_files if path)
    return [
        {"area": area, "tracked_files": count}
        for area, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _group_extensions(tracked_files: list[str]) -> list[dict]:
    counts = Counter(Path(path).suffix.lower() or "<none>" for path in tracked_files if path)
    return [
        {"extension": extension, "tracked_files": count}
        for extension, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )


def package_line_counts(root: str | Path, *, repo_root: str | Path) -> list[dict]:
    root = Path(root)
    if not root.exists():
        return []
    root_files = sorted(path for path in root.glob("*.py") if path.is_file())
    rows = [{
        "package": ROOT_AREA_NAME,
        "path": _relative(root, repo_root),
        "python_files": len(root_files),
        "lines": sum(_count_lines(path) for path in root_files),
    }]
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        files = _python_files(child)
        rows.append({
            "package": child.name,
            "path": _relative(child, repo_root),
            "python_files": len(files),
            "lines": sum(_count_lines(path) for path in files),
        })
    rows.sort(key=lambda row: (-row["lines"], row["package"]))
    return rows


def test_area_counts(tests_root: str | Path, *, repo_root: str | Path) -> list[dict]:
    tests_root = Path(tests_root)
    if not tests_root.exists():
        return []
    root_files = sorted(path for path in tests_root.glob("*.py") if path.is_file())
    rows = [{
        "area": ROOT_AREA_NAME,
        "path": _relative(tests_root, repo_root),
        "python_files": len(root_files),
        "lines": sum(_count_lines(path) for path in root_files),
    }]
    for child in sorted(tests_root.iterdir()):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        files = _python_files(child)
        rows.append({
            "area": child.name,
            "path": _relative(child, repo_root),
            "python_files": len(files),
            "lines": sum(_count_lines(path) for path in files),
        })
    rows.sort(key=lambda row: (-row["lines"], row["area"]))
    return rows


def app_file_counts(app_root: str | Path, *, repo_root: str | Path) -> list[dict]:
    rows = [
        {
            "path": _relative(path, repo_root),
            "lines": _count_lines(path),
        }
        for path in _python_files(Path(app_root))
    ]
    rows.sort(key=lambda row: (-row["lines"], row["path"]))
    return rows


def large_modules(
    source_root: str | Path,
    *,
    repo_root: str | Path,
    line_threshold: int = DEFAULT_LINE_THRESHOLD,
) -> list[dict]:
    rows = []
    for path in _python_files(Path(source_root)):
        lines = _count_lines(path)
        if lines >= line_threshold:
            rows.append({
                "path": _relative(path, repo_root),
                "lines": lines,
            })
    rows.sort(key=lambda row: (-row["lines"], row["path"]))
    return rows


def _source_package(path: Path, source_root: Path) -> str | None:
    try:
        relative = path.relative_to(source_root)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    package = relative.parts[0]
    return package if package in PACKAGE_ROOTS else None


def _imported_weather_package(module_name: str) -> str | None:
    if module_name == "weather" or not module_name.startswith("weather."):
        return None
    parts = module_name.split(".")
    if len(parts) < 2:
        return None
    package = parts[1]
    if package in PACKAGE_ROOTS or package in SHARED_PACKAGE_ROOTS:
        return package
    return None


def _weather_import_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def package_edges(source_root: str | Path, *, repo_root: str | Path) -> dict:
    source_root = Path(source_root)
    edges: dict[tuple[str, str], set[str]] = {}
    parse_errors = []
    for path in _python_files(source_root):
        source = _source_package(path, source_root)
        if not source:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append({
                "path": _relative(path, repo_root),
                "error": str(exc),
            })
            continue
        for module_name in _weather_import_modules(tree):
            target = _imported_weather_package(module_name)
            if not target or target == source or target in SHARED_PACKAGE_ROOTS:
                continue
            edges.setdefault((source, target), set()).add(_relative(path, repo_root))
    rows = [
        {
            "source": source,
            "target": target,
            "edge": f"{source}->{target}",
            "file_count": len(files),
            "files": sorted(files),
        }
        for (source, target), files in sorted(edges.items())
    ]
    rows.sort(key=lambda row: (-row["file_count"], row["edge"]))
    return {
        "edges": rows,
        "parse_errors": parse_errors,
    }


def compatibility_shims(repo_root: str | Path = REPO_ROOT) -> dict:
    repo_root = Path(repo_root)
    flat_wrappers = [
        path
        for path in sorted((repo_root / "src").glob("*.py"))
        if path.name != "__init__.py"
    ]
    root_streamlit_shims = [
        repo_root / name
        for name in DEFAULT_ROOT_STREAMLIT_SHIMS
        if (repo_root / name).exists()
    ]
    root_helper_shims = [
        repo_root / name
        for name in DEFAULT_ROOT_HELPER_SHIMS
        if (repo_root / name).exists()
    ]
    script_root_shims = [
        path
        for path in sorted((repo_root / "scripts").glob("*"))
        if path.is_file()
    ]
    return {
        "flat_src_wrappers": len(flat_wrappers),
        "root_streamlit_shims": len(root_streamlit_shims),
        "root_helper_shims": len(root_helper_shims),
        "root_script_shims": len(script_root_shims),
        "total": (
            len(flat_wrappers)
            + len(root_streamlit_shims)
            + len(root_helper_shims)
            + len(script_root_shims)
        ),
        "examples": [
            _relative(path, repo_root)
            for path in [
                *flat_wrappers[:5],
                *root_streamlit_shims[:5],
                *root_helper_shims[:5],
                *script_root_shims[:5],
            ]
        ],
    }


def directory_size_summary(root: str | Path, *, repo_root: str | Path) -> list[dict]:
    root = Path(root)
    if not root.exists():
        return []
    rows = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        file_count = 0
        bytes_total = 0
        for path in child.rglob("*"):
            if not path.is_file():
                continue
            try:
                bytes_total += path.stat().st_size
            except OSError:
                continue
            file_count += 1
        rows.append({
            "area": child.name,
            "path": _relative(child, repo_root),
            "files": file_count,
            "bytes": bytes_total,
            "mib": round(bytes_total / (1024 * 1024), 2),
        })
    rows.sort(key=lambda row: (-row["bytes"], row["area"]))
    return rows


def data_budget_checks(
    data_rows: list[dict],
    *,
    budget_mib: dict[str, int | float] | None = None,
) -> dict:
    budgets = dict(DEFAULT_DATA_BUDGET_MIB if budget_mib is None else budget_mib)
    warnings = []
    for row in data_rows:
        area = row["area"]
        threshold_mib = float(budgets.get(area, DEFAULT_OTHER_DATA_BUDGET_MIB))
        threshold_bytes = threshold_mib * 1024 * 1024
        if row["bytes"] <= threshold_bytes:
            continue
        recommendation = "Review retention and move bulky generated state outside the repo if it is operational data."
        if area == "snapshots":
            recommendation = "Move large snapshot roots outside the repo or apply retention before daily refresh loops fail."
        warnings.append({
            "area": area,
            "path": row["path"],
            "mib": row["mib"],
            "threshold_mib": threshold_mib,
            "files": row["files"],
            "recommendation": recommendation,
        })
    return {
        "checked": True,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _run_architecture_ratchet(repo_root: str | Path) -> dict:
    command = [".\\venv\\Scripts\\python.exe", "-m", "pytest", "tests\\operations\\test_import_architecture.py", "-q"]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "status": "ERROR",
            "returncode": None,
            "command": " ".join(command),
            "summary": str(exc),
        }
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    summary = output.splitlines()[-1] if output else ""
    return {
        "ran": True,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "returncode": result.returncode,
        "command": " ".join(command),
        "summary": summary,
    }


def build_structure_inventory(
    repo_root: str | Path = REPO_ROOT,
    *,
    tracked_files: list[str] | None = None,
    source_root: str | Path | None = None,
    tests_root: str | Path | None = None,
    app_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
    data_root: str | Path | None = None,
    line_threshold: int = DEFAULT_LINE_THRESHOLD,
    include_data_sizes: bool = True,
    data_budget_mib: dict[str, int | float] | None = None,
    run_architecture_ratchet: bool = False,
    generated_at_utc: str | None = None,
) -> dict:
    repo_root = Path(repo_root)
    source_root = Path(source_root) if source_root is not None else repo_root / "src" / "weather"
    tests_root = Path(tests_root) if tests_root is not None else repo_root / "tests"
    app_root = Path(app_root) if app_root is not None else repo_root / "app"
    artifacts_root = Path(artifacts_root) if artifacts_root is not None else ARTIFACTS_ROOT
    data_root = Path(data_root) if data_root is not None else DATA_ROOT
    tracked_files = tracked_files if tracked_files is not None else git_tracked_files(repo_root)
    source_packages = package_line_counts(source_root, repo_root=repo_root)
    test_areas = test_area_counts(tests_root, repo_root=repo_root)
    app_files = app_file_counts(app_root, repo_root=repo_root)
    artifacts = directory_size_summary(artifacts_root, repo_root=repo_root)
    data = directory_size_summary(data_root, repo_root=repo_root) if include_data_sizes else []
    data_budgets = (
        data_budget_checks(data, budget_mib=data_budget_mib)
        if include_data_sizes
        else {"checked": False, "warning_count": 0, "warnings": []}
    )
    modules = large_modules(source_root, repo_root=repo_root, line_threshold=line_threshold)
    edge_payload = package_edges(source_root, repo_root=repo_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "repo_root": str(repo_root),
        "line_threshold": int(line_threshold),
        "tracked_file_count": len(tracked_files),
        "top_level_counts": _group_top_level(tracked_files),
        "extension_counts": _group_extensions(tracked_files),
        "source_packages": source_packages,
        "source_python_files": sum(row["python_files"] for row in source_packages),
        "source_lines": sum(row["lines"] for row in source_packages),
        "large_modules": modules,
        "large_module_count": len(modules),
        "package_edges": edge_payload["edges"],
        "package_edge_parse_errors": edge_payload["parse_errors"],
        "test_areas": test_areas,
        "test_python_files": sum(row["python_files"] for row in test_areas),
        "test_lines": sum(row["lines"] for row in test_areas),
        "app_files": app_files,
        "compatibility_shims": compatibility_shims(repo_root),
        "artifacts": artifacts,
        "artifact_mib": round(sum(row["bytes"] for row in artifacts) / (1024 * 1024), 2),
        "data": data,
        "data_mib": round(sum(row["bytes"] for row in data) / (1024 * 1024), 2),
        "data_sizes_included": include_data_sizes,
        "data_budget_checks": data_budgets,
        "architecture_ratchet": (
            _run_architecture_ratchet(repo_root)
            if run_architecture_ratchet
            else {"ran": False, "status": "SKIPPED"}
        ),
    }


def write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def render_report(payload: dict) -> str:
    lines = [
        "# Structure Inventory",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Tracked files: `{payload.get('tracked_file_count')}`",
        f"Source Python files: `{payload.get('source_python_files')}`",
        f"Source lines: `{payload.get('source_lines')}`",
        f"Large modules over `{payload.get('line_threshold')}` lines: `{payload.get('large_module_count')}`",
        f"Compatibility shims: `{(payload.get('compatibility_shims') or {}).get('total')}`",
        f"Artifact MiB: `{payload.get('artifact_mib')}`",
        f"Data MiB: `{payload.get('data_mib')}`"
        if payload.get("data_sizes_included")
        else "Data MiB: `skipped`",
        f"Architecture ratchet: `{(payload.get('architecture_ratchet') or {}).get('status')}`",
        "",
        "## Top-Level Tracked Files",
        "",
    ]
    lines += _table(
        ["Area", "Tracked files"],
        [[row["area"], row["tracked_files"]] for row in payload.get("top_level_counts") or []],
    )
    lines += ["", "## Source Packages", ""]
    lines += _table(
        ["Package", "Python files", "Lines"],
        [[row["package"], row["python_files"], row["lines"]] for row in payload.get("source_packages") or []],
    )
    lines += ["", "## Large Modules", ""]
    lines += _table(
        ["Path", "Lines"],
        [[row["path"], row["lines"]] for row in payload.get("large_modules") or []],
    )
    lines += ["", "## Test Areas", ""]
    lines += _table(
        ["Area", "Python files", "Lines"],
        [[row["area"], row["python_files"], row["lines"]] for row in payload.get("test_areas") or []],
    )
    lines += ["", "## Package Edges", ""]
    lines += _table(
        ["Edge", "Files"],
        [[row["edge"], row["file_count"]] for row in payload.get("package_edges") or []],
    )
    if payload.get("package_edge_parse_errors"):
        lines += ["", "Package-edge parse errors:"]
        for row in payload.get("package_edge_parse_errors") or []:
            lines.append(f"- {row.get('path')}: {row.get('error')}")
    lines += ["", "## Artifacts", ""]
    lines += _table(
        ["Area", "Files", "MiB"],
        [[row["area"], row["files"], row["mib"]] for row in payload.get("artifacts") or []],
    )
    lines += ["", "## Ignored Data", ""]
    if payload.get("data_sizes_included"):
        lines += _table(
            ["Area", "Files", "MiB"],
            [[row["area"], row["files"], row["mib"]] for row in payload.get("data") or []],
        )
    else:
        lines.append("_Skipped. Re-run with `--include-data-sizes` to include ignored runtime state._")
    lines += ["", "## Ignored Data Budget", ""]
    data_budget = payload.get("data_budget_checks") or {}
    if not data_budget.get("checked"):
        lines.append("_Not checked. Re-run with `--include-data-sizes` to evaluate ignored runtime state._")
    elif data_budget.get("warnings"):
        lines += _table(
            ["Area", "MiB", "Threshold MiB", "Recommendation"],
            [
                [row["area"], row["mib"], row["threshold_mib"], row["recommendation"]]
                for row in data_budget.get("warnings") or []
            ],
        )
    else:
        lines.append("_No ignored data budget warnings._")
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inventory repository structure and growth-pressure indicators.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--line-threshold", type=int, default=DEFAULT_LINE_THRESHOLD)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--include-data-sizes", action="store_true")
    parser.add_argument("--skip-data-sizes", action="store_true", help="Deprecated; data sizes are skipped by default.")
    parser.add_argument("--run-architecture-ratchet", action="store_true")
    args = parser.parse_args(argv)

    payload = build_structure_inventory(
        args.repo_root,
        line_threshold=args.line_threshold,
        include_data_sizes=args.include_data_sizes and not args.skip_data_sizes,
        run_architecture_ratchet=args.run_architecture_ratchet,
    )
    write_json(args.out, payload)
    write_report(args.report, payload)
    print(
        "Structure inventory: tracked={tracked_file_count} source_py={source_python_files} "
        "large_modules={large_module_count} shims={shims} data_mib={data_mib}".format(
            shims=payload["compatibility_shims"]["total"],
            **payload,
        )
    )
    return payload


if __name__ == "__main__":
    main()
