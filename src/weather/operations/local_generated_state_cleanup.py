"""Dry-run audit for ignored local generated state and cleanup readiness."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import REPO_ROOT, data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("local_generated_state_cleanup")
DEFAULT_OUT = data_path("backtest", "local_generated_state_cleanup.json")
DEFAULT_REPORT = data_path("backtest", "local_generated_state_cleanup_report.md")

SAFE_CACHE_ROOTS = (
    ".pytest_cache",
    ".ruff_cache",
    "src/weather_market.egg-info",
)
SKIP_TRAVERSAL_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "data",
    "env",
    "node_modules",
    "venv",
}
LINE_ENDING_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "artifacts",
    "data",
    "env",
    "node_modules",
    "venv",
}
TEXT_LINE_ENDING_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_LINE_ENDING_NAMES = {
    ".gitattributes",
    ".gitignore",
    "requirements.txt",
}
PIN_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([^;\s]+)")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def relative_to_root(path: str | Path, root: str | Path) -> str:
    path = Path(path)
    root = Path(root)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def bytes_to_display(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{int(size)} B"


def directory_size(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        return path.stat().st_size, 1
    total = 0
    count = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            total += child.stat().st_size
            count += 1
        except OSError:
            continue
    return total, count


def iter_dirs_named(root: Path, name: str):
    for current, dirs, _files in os.walk(root):
        dirs[:] = [dirname for dirname in dirs if dirname not in SKIP_TRAVERSAL_DIRS or dirname == name]
        current_path = Path(current)
        for dirname in list(dirs):
            if dirname == name:
                yield current_path / dirname
                dirs.remove(dirname)


def safe_cache_entries(repo_root: str | Path = REPO_ROOT) -> list[dict[str, Any]]:
    repo_root = Path(repo_root)
    paths = {repo_root / root for root in SAFE_CACHE_ROOTS if (repo_root / root).exists()}
    paths.update(iter_dirs_named(repo_root, "__pycache__"))
    rows = []
    for path in sorted(paths, key=lambda item: relative_to_root(item, repo_root)):
        size, files = directory_size(path)
        rows.append({
            "path": relative_to_root(path, repo_root),
            "kind": "safe_cache",
            "bytes": size,
            "file_count": files,
            "cleanup_policy": "delete_after_active_work_finishes",
            "dry_run_action": "would_delete",
        })
    return rows


def scratch_recommendation(path: Path) -> tuple[str, str]:
    if path.suffix == ".py":
        if "no_market_location" in path.name:
            return (
                "superseded_by_package_harness",
                "Confirm no unique logic remains, then prefer weather.reporting.location_analysis.no_market_location_transfer.",
            )
        return ("review_for_tool_or_test_promotion", "Promote to tools/research or tests before deletion.")
    if path.suffix == ".md":
        return ("promote_or_reference_durable_report", "Promote durable conclusions to docs/research before deletion.")
    if path.suffix in {".json", ".csv"}:
        return ("generated_evidence_pair", "Keep with the paired report until durable findings are documented.")
    return ("review_before_delete", "Classify manually before deleting scratch output.")


def scratch_review_entries(repo_root: str | Path = REPO_ROOT) -> list[dict[str, Any]]:
    repo_root = Path(repo_root)
    scratch_root = repo_root / "scratch"
    if not scratch_root.exists():
        return []
    rows = []
    for path in sorted(scratch_root.iterdir(), key=lambda item: item.name):
        if path.name == "__pycache__":
            continue
        size, files = directory_size(path)
        recommendation, rationale = scratch_recommendation(path)
        rows.append({
            "path": relative_to_root(path, repo_root),
            "kind": "durable_scratch_review",
            "suffix": path.suffix or "<dir>",
            "bytes": size,
            "file_count": files,
            "recommendation": recommendation,
            "rationale": rationale,
        })
    return rows


def _load_research_harness(research_root: Path):
    harness = research_root / "research_harness.py"
    if not harness.exists():
        return None, [f"{relative_to_root(harness, research_root.parent.parent)} missing"]
    spec = importlib.util.spec_from_file_location("_weather_research_harness_cleanup", harness)
    if spec is None or spec.loader is None:
        return None, [f"{harness} cannot be imported"]
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - defensive import guard
        return None, [f"{harness} import failed: {exc}"]
    return module, []


def research_status_recommendation(status: str) -> str:
    if status == "retired":
        return "keep_documented_failure_sentinel_unless_harness_row_is_removed"
    if status == "fixture-only":
        return "keep_fixture_only_script_under_harness_inventory"
    if status == "supported":
        return "keep_supported_entrypoint"
    return "add_inventory_row_or_remove_unowned_script"


def research_review(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = Path(repo_root)
    research_root = repo_root / "tools" / "research"
    module, errors = _load_research_harness(research_root)
    inventory = dict(getattr(module, "SCRIPT_INVENTORY", {}) or {}) if module else {}
    if module and hasattr(module, "validate_inventory"):
        try:
            errors.extend(module.validate_inventory(research_root))
        except Exception as exc:  # pragma: no cover - defensive validation guard
            errors.append(f"research inventory validation failed: {exc}")
    scripts = {path.name for path in research_root.glob("*.py")} if research_root.exists() else set()
    rows = []
    status_counts: dict[str, int] = {}
    for name in sorted(scripts | set(inventory)):
        meta = inventory.get(name) or {}
        status = meta.get("status") or "missing_inventory"
        status_counts[status] = status_counts.get(status, 0) + 1
        path = research_root / name
        size, _files = directory_size(path)
        rows.append({
            "path": relative_to_root(path, repo_root),
            "status": status,
            "smoke": meta.get("smoke"),
            "bytes": size,
            "notes": meta.get("notes") or "",
            "recommendation": research_status_recommendation(status),
        })
    return {
        "root": relative_to_root(research_root, repo_root),
        "script_count": len(rows),
        "status_counts": status_counts,
        "validation_errors": errors,
        "scripts": rows,
    }


def normalize_pin(value: str) -> tuple[str, str | None]:
    match = PIN_RE.match(value)
    if not match:
        return value.strip().lower().replace("_", "-"), None
    name, version = match.groups()
    return name.lower().replace("_", "-"), version.strip()


def load_pyproject_dependencies(path: Path) -> list[str]:
    if not path.exists():
        return []
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return [str(item).strip() for item in payload.get("project", {}).get("dependencies", [])]


def load_requirements(path: Path) -> list[str]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if clean:
            rows.append(clean)
    return rows


def dependency_pin_sync(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = Path(repo_root)
    pyproject = load_pyproject_dependencies(repo_root / "pyproject.toml")
    requirements = load_requirements(repo_root / "requirements.txt")
    pyproject_by_name = {normalize_pin(row)[0]: normalize_pin(row)[1] for row in pyproject}
    requirements_by_name = {normalize_pin(row)[0]: normalize_pin(row)[1] for row in requirements}
    missing_from_requirements = sorted(set(pyproject_by_name) - set(requirements_by_name))
    missing_from_pyproject = sorted(set(requirements_by_name) - set(pyproject_by_name))
    mismatched_versions = sorted(
        {
            name
            for name in set(pyproject_by_name) & set(requirements_by_name)
            if pyproject_by_name[name] != requirements_by_name[name]
        }
    )
    unpinned = sorted({
        name
        for name, version in {**pyproject_by_name, **requirements_by_name}.items()
        if version is None
    })
    in_sync = not (missing_from_requirements or missing_from_pyproject or mismatched_versions or unpinned)
    return {
        "status": "PASS" if in_sync else "WARN",
        "in_sync": in_sync,
        "pyproject_dependency_count": len(pyproject),
        "requirements_dependency_count": len(requirements),
        "missing_from_requirements": missing_from_requirements,
        "missing_from_pyproject": missing_from_pyproject,
        "mismatched_versions": mismatched_versions,
        "unpinned_dependencies": unpinned,
    }


def git_tracked_files(repo_root: Path) -> list[Path] | None:
    if not (repo_root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [repo_root / line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_line_ending_candidate(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    if any(part in LINE_ENDING_SKIP_DIRS for part in relative.parts):
        return False
    return path.suffix in TEXT_LINE_ENDING_SUFFIXES or path.name in TEXT_LINE_ENDING_NAMES


def iter_line_ending_candidates(repo_root: Path):
    tracked = git_tracked_files(repo_root)
    candidates = tracked if tracked is not None else [path for path in repo_root.rglob("*") if path.is_file()]
    for path in candidates:
        if path.exists() and path.is_file() and is_line_ending_candidate(path, repo_root):
            yield path


def line_ending_report(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = Path(repo_root)
    rows = []
    scanned = 0
    for path in iter_line_ending_candidates(repo_root):
        scanned += 1
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if b"\0" in payload:
            continue
        crlf = payload.count(b"\r\n")
        if crlf:
            rows.append({
                "path": relative_to_root(path, repo_root),
                "crlf_line_count": crlf,
                "bytes": len(payload),
                "recommendation": "normalize_to_lf_in_controlled_docs_code_pass",
            })
    return {
        "policy": "* text=auto eol=lf",
        "scanned_file_count": scanned,
        "crlf_file_count": len(rows),
        "crlf_files": sorted(rows, key=lambda row: row["path"]),
    }


def build_cleanup_report(
    repo_root: str | Path = REPO_ROOT,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    caches = safe_cache_entries(repo_root)
    scratch = scratch_review_entries(repo_root)
    research = research_review(repo_root)
    dependencies = dependency_pin_sync(repo_root)
    endings = line_ending_report(repo_root)
    action_required = bool(
        caches
        or scratch
        or research.get("validation_errors")
        or dependencies["status"] != "PASS"
        or endings["crlf_file_count"]
    )
    cache_bytes = sum(row["bytes"] for row in caches)
    scratch_bytes = sum(row["bytes"] for row in scratch)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_now().isoformat(),
        "repo_root": repo_root.as_posix(),
        "dry_run_only": True,
        "status": "ACTION_REQUIRED" if action_required else "PASS",
        "safe_cache_summary": {
            "root_count": len(caches),
            "file_count": sum(row["file_count"] for row in caches),
            "bytes": cache_bytes,
            "display_bytes": bytes_to_display(cache_bytes),
            "entries": caches,
        },
        "scratch_review": {
            "file_count": len(scratch),
            "bytes": scratch_bytes,
            "display_bytes": bytes_to_display(scratch_bytes),
            "entries": scratch,
        },
        "research_review": research,
        "dependency_pin_sync": dependencies,
        "line_endings": endings,
        "recommended_sequence": [
            "Rerun this dry-run after active agent work and tests finish.",
            "Delete only the safe_cache entries after confirming no long-running process is using them.",
            "Promote or document durable scratch conclusions before deleting scratch files.",
            "Keep retired tools/research scripts while they remain documented harness sentinels.",
            "Normalize CRLF files in a dedicated docs/code hygiene change consistent with .gitattributes.",
        ],
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_report(payload: dict[str, Any]) -> str:
    cache = payload.get("safe_cache_summary") or {}
    scratch = payload.get("scratch_review") or {}
    research = payload.get("research_review") or {}
    dependencies = payload.get("dependency_pin_sync") or {}
    endings = payload.get("line_endings") or {}
    lines = [
        "# Local Generated State Cleanup Dry Run",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Dry run only: `{payload.get('dry_run_only')}`",
        "",
        "## Safe Cache Deletion Candidates",
        "",
        f"Roots: `{cache.get('root_count', 0)}`  Files: `{cache.get('file_count', 0)}`  Size: `{cache.get('display_bytes', '0 B')}`",
        "",
        "| Path | Files | Size | Policy |",
        "| :--- | ---: | ---: | :--- |",
    ]
    for row in cache.get("entries") or []:
        lines.append(
            "| {path} | {files} | {size} | {policy} |".format(
                path=row["path"],
                files=row["file_count"],
                size=bytes_to_display(row["bytes"]),
                policy=row["cleanup_policy"],
            )
        )
    if not cache.get("entries"):
        lines.append("| - | 0 | 0 B | - |")
    lines.extend([
        "",
        "## Scratch Review",
        "",
        f"Files: `{scratch.get('file_count', 0)}`  Size: `{scratch.get('display_bytes', '0 B')}`",
        "",
        "| Path | Size | Recommendation | Rationale |",
        "| :--- | ---: | :--- | :--- |",
    ])
    for row in scratch.get("entries") or []:
        lines.append(
            "| {path} | {size} | {recommendation} | {rationale} |".format(
                path=row["path"],
                size=bytes_to_display(row["bytes"]),
                recommendation=row["recommendation"],
                rationale=row["rationale"],
            )
        )
    if not scratch.get("entries"):
        lines.append("| - | 0 B | - | - |")
    lines.extend([
        "",
        "## Research Harness",
        "",
        f"Scripts: `{research.get('script_count', 0)}`",
        f"Validation errors: `{len(research.get('validation_errors') or [])}`",
        "",
        "| Status | Count |",
        "| :--- | ---: |",
    ])
    for status, count in sorted((research.get("status_counts") or {}).items()):
        lines.append(f"| {status} | {count} |")
    if not research.get("status_counts"):
        lines.append("| - | 0 |")
    lines.extend([
        "",
        "## Dependency Pin Sync",
        "",
        f"Status: `{dependencies.get('status')}`",
        f"In sync: `{dependencies.get('in_sync')}`",
        f"Missing from requirements: `{', '.join(dependencies.get('missing_from_requirements') or []) or '-'}`",
        f"Missing from pyproject: `{', '.join(dependencies.get('missing_from_pyproject') or []) or '-'}`",
        f"Mismatched versions: `{', '.join(dependencies.get('mismatched_versions') or []) or '-'}`",
        "",
        "## Line Endings",
        "",
        f"Policy: `{endings.get('policy')}`",
        f"Scanned files: `{endings.get('scanned_file_count', 0)}`",
        f"CRLF files: `{endings.get('crlf_file_count', 0)}`",
        "",
        "| Path | CRLF lines | Recommendation |",
        "| :--- | ---: | :--- |",
    ])
    for row in endings.get("crlf_files") or []:
        lines.append(f"| {row['path']} | {row['crlf_line_count']} | {row['recommendation']} |")
    if not endings.get("crlf_files"):
        lines.append("| - | 0 | - |")
    lines.extend([
        "",
        "## Recommended Sequence",
        "",
    ])
    for step in payload.get("recommended_sequence") or []:
        lines.append(f"- {step}")
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dry-run local generated-state cleanup and tooling sweep.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--fail-on-issues", action="store_true")
    args = parser.parse_args(argv)

    payload = build_cleanup_report(args.repo_root)
    write_json(args.out, payload)
    write_report(args.report, payload)
    cache = payload["safe_cache_summary"]
    scratch = payload["scratch_review"]
    print(
        "Local generated state cleanup dry-run: status={status} safe_cache_roots={roots} "
        "scratch_files={scratch_files} crlf_files={crlf_files}".format(
            status=payload["status"],
            roots=cache["root_count"],
            scratch_files=scratch["file_count"],
            crlf_files=payload["line_endings"]["crlf_file_count"],
        )
    )
    if args.fail_on_issues and payload["status"] != "PASS":
        raise SystemExit(1)
    return payload


if __name__ == "__main__":
    main()
