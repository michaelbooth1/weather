"""Validate the repository's agent-facing knowledge contracts.

This audit is deliberately deterministic and offline. It checks discoverability
and mechanically verifiable ownership signals; it does not pretend to prove
that prose is semantically current.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

from weather.paths import REPO_ROOT


REQUIRED_FILES = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "app/AGENTS.md",
    "artifacts/AGENTS.md",
    "config/AGENTS.md",
    "docs/AGENTS.md",
    "docs/README.md",
    "docs/architecture.md",
    "docs/development.md",
    "docs/documentation-maintenance.md",
    "docs/operations/AGENT_CONTEXT.md",
    "docs/operations/README.md",
    "docs/roadmap/AGENTS.md",
    "docs/roadmap/active-backlog.md",
    "scripts/ops/AGENTS.md",
    "src/weather/AGENTS.md",
    "src/weather/backtesting/AGENTS.md",
    "src/weather/calibration/AGENTS.md",
    "src/weather/collection/AGENTS.md",
    "src/weather/market/AGENTS.md",
    "src/weather/model/AGENTS.md",
    "src/weather/operations/AGENTS.md",
    "src/weather/reporting/AGENTS.md",
    "src/weather/sources/AGENTS.md",
    "tests/AGENTS.md",
    "tools/AGENTS.md",
)

CANONICAL_DOCS = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "docs/README.md",
    "docs/architecture.md",
    "docs/development.md",
    "docs/documentation-maintenance.md",
    "docs/operations/AGENT_CONTEXT.md",
    "docs/operations/OPERATIONS_DESIGN.md",
    "docs/operations/README.md",
    "docs/operations/artifact-storage-policy.md",
    "docs/operations/config-inventory.md",
    "docs/operations/package-boundaries.md",
    "docs/operations/path-policy.md",
)

UPDATE_TRIGGER_DOCS = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/architecture.md",
    "docs/development.md",
    "docs/documentation-maintenance.md",
    "docs/operations/AGENT_CONTEXT.md",
    "docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md",
    "docs/operations/OPERATIONS_DESIGN.md",
    "docs/operations/README.md",
    "docs/operations/artifact-storage-policy.md",
    "docs/operations/config-inventory.md",
    "docs/operations/package-boundaries.md",
    "docs/operations/path-policy.md",
)

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HISTORICAL_MISSING_LINK_EXCLUSIONS = frozenset(
    {
        (
            "docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md",
            "../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079",
        ),
    }
)
LEGACY_COMMAND_PATTERNS = (
    re.compile(r"(?:pythonw?\.exe\s+-m\s+src\.|python\s+-m\s+src\.|-m\s+src\.)"),
    re.compile(r"streamlit\s+run\s+app\.py"),
    re.compile(
        r"(?:^|[\s`'\"])(?:\.\\)?scripts\\(?!ops\\|launch\\)"
        r"(?:register_[A-Za-z0-9_]+\.ps1|start_weather_dashboard\."
        r"(?:cmd|ps1|vbs))",
        re.MULTILINE,
    ),
    re.compile(
        r"(?:^|[\s`'\"])(?:\./)?scripts/(?!ops/|launch/)"
        r"(?:register_[A-Za-z0-9_]+\.ps1|start_weather_dashboard\."
        r"(?:cmd|ps1|vbs))",
        re.MULTILINE,
    ),
)


def _markdown_files(repo_root: Path) -> list[Path]:
    ignored_dirs = {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "data",
        "scratch",
        "venv",
    }
    paths: list[Path] = []
    for current, directories, filenames in os.walk(repo_root):
        directories[:] = [name for name in directories if name not in ignored_dirs]
        current_path = Path(current)
        paths.extend(current_path / name for name in filenames if name.endswith(".md"))
    return sorted(paths)


def _agent_files(repo_root: Path) -> list[Path]:
    return [path for path in _markdown_files(repo_root) if path.name == "AGENTS.md"]


def legacy_command_matches(text: str) -> list[str]:
    return [
        match.group(0).strip()
        for pattern in LEGACY_COMMAND_PATTERNS
        for match in pattern.finditer(text)
    ]


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    # Optional Markdown link titles follow whitespace. Repository paths with
    # spaces should be angle-bracketed and are handled above.
    if " " in target:
        target = target.split(" ", 1)[0]
    return unquote(target.split("#", 1)[0].split("?", 1)[0])


def _is_immutable_record(path: Path) -> bool:
    """Dated roadmap correspondence, which `docs/roadmap/AGENTS.md` forbids editing.

    These files are the record of what was known when they were written. Code they cite
    legitimately moves or never lands, and the only way to repair such a link is to edit
    the record -- which that rule prohibits. Enforcing repairable-only-by-editing link
    targets on an immutable file is a rule with no legal way to satisfy it, and on
    2026-08-06 it had left `python -m weather.operations.agent_docs_audit` -- a baseline
    check in the root `AGENTS.md` -- failing on master since at least 2026-08-02, on a
    report citing `floor_retrain_gate_harness.py`, a path no ref has ever contained.
    A baseline gate that is always red teaches agents to ignore it.
    """
    if path.parent.name != "roadmap":
        return False
    return path.name.startswith(("agent-report-", "workstation-handoff-"))


def _markdown_outside_fenced_code(text: str) -> str:
    """Blank fenced code while preserving all prose and line boundaries.

    PowerShell casts such as ``[string](...)`` have Markdown-link syntax but
    are executable examples, not links. Link auditing fenced code therefore
    produces false missing-file findings. Supporting both CommonMark fence
    characters and longer closing fences keeps the scanner deterministic
    without trying to parse the rest of Markdown.
    """
    fence: tuple[str, int] | None = None
    visible: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        indent = len(body) - len(body.lstrip(" "))
        candidate = body[indent:] if indent <= 3 else ""
        marker = candidate[:1]
        run_length = 0
        if marker in {"`", "~"}:
            run_length = len(candidate) - len(candidate.lstrip(marker))

        if fence is None:
            if run_length >= 3:
                fence = (marker, run_length)
                visible.append("\n" if line.endswith(("\n", "\r")) else "")
            else:
                visible.append(line)
            continue

        if (
            marker == fence[0]
            and run_length >= fence[1]
            and not candidate[run_length:].strip()
        ):
            fence = None
        visible.append("\n" if line.endswith(("\n", "\r")) else "")
    return "".join(visible)


def broken_local_links(repo_root: Path, paths: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    for path in paths or _markdown_files(repo_root):
        immutable = _is_immutable_record(path)
        text = _markdown_outside_fenced_code(
            path.read_text(encoding="utf-8-sig")
        )
        for match in MARKDOWN_LINK_RE.finditer(text):
            raw_target = match.group(1)
            relative_path = path.relative_to(repo_root).as_posix()
            if (relative_path, raw_target) in HISTORICAL_MISSING_LINK_EXCLUSIONS:
                # Published correspondence is immutable. This link names code
                # retained only in Git history after its research lane was removed.
                continue
            target = _link_target(raw_target)
            if not target or target.startswith(("#", "/")):
                continue
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(repo_root.resolve())
            except ValueError:
                # Still enforced on immutable records: this one is a structural problem,
                # not drift, and it never becomes unfixable by the passage of time.
                errors.append(f"{path.relative_to(repo_root)}: link escapes repository: {raw_target}")
                continue
            if not resolved.exists() and not immutable:
                errors.append(f"{path.relative_to(repo_root)}: missing link target: {raw_target}")
    return errors


def _dependency_map_from_pyproject(repo_root: Path) -> dict[str, str]:
    payload = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = payload.get("project", {}).get("dependencies", [])
    result: dict[str, str] = {}
    for dependency in dependencies:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^;\s]+)", dependency.strip())
        if not match:
            raise ValueError(f"pyproject dependency is not exactly pinned: {dependency}")
        result[match.group(1).lower()] = match.group(2)
    return result


def _dependency_map_from_requirements(repo_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in (repo_root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^;\s]+)", line)
        if not match:
            raise ValueError(f"requirement is not exactly pinned: {line}")
        result[match.group(1).lower()] = match.group(2)
    return result


def _builtin_market_rows(repo_root: Path) -> list[dict[str, str]]:
    """Read literal built-in MarketSpec fields without loading runtime overrides."""

    source = (repo_root / "src/weather/market/market_registry.py").read_text(
        encoding="utf-8-sig"
    )
    tree = ast.parse(source)
    specs: dict[str, dict[str, str]] = {}
    builtin_names: list[str] = []
    fields = {"id", "city_label", "display_unit", "icao", "timezone"}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "BUILTIN_SPECS" and isinstance(node.value, (ast.Tuple, ast.List)):
            builtin_names = [
                item.id for item in node.value.elts if isinstance(item, ast.Name)
            ]
            continue
        if not isinstance(node.value, ast.Call):
            continue
        function_name = (
            node.value.func.id if isinstance(node.value.func, ast.Name) else None
        )
        if function_name != "MarketSpec":
            continue
        values = {
            keyword.arg: ast.literal_eval(keyword.value)
            for keyword in node.value.keywords
            if keyword.arg in fields
        }
        if fields.issubset(values):
            specs[target.id] = values
    if not builtin_names or any(name not in specs for name in builtin_names):
        raise ValueError("could not parse BUILTIN_SPECS from market_registry.py")
    return [specs[name] for name in builtin_names]


def audit_repo(repo_root: Path = REPO_ROOT) -> list[str]:
    repo_root = repo_root.resolve()
    errors: list[str] = []

    for relative in REQUIRED_FILES:
        if not (repo_root / relative).is_file():
            errors.append(f"missing required knowledge file: {relative}")

    agent_files = _agent_files(repo_root)
    if not agent_files:
        errors.append("no AGENTS.md files discovered")
    for path in agent_files:
        text = path.read_text(encoding="utf-8-sig")
        if "Update this file when" not in text:
            errors.append(f"{path.relative_to(repo_root)}: missing update trigger")

    for relative in UPDATE_TRIGGER_DOCS:
        path = repo_root / relative
        if path.exists() and "Update this file when" not in path.read_text(
            encoding="utf-8-sig"
        ):
            errors.append(f"{relative}: missing update trigger")

    errors.extend(broken_local_links(repo_root))

    config_inventory = (repo_root / "docs/operations/config-inventory.md").read_text(
        encoding="utf-8-sig"
    )
    for config_path in sorted((repo_root / "config").glob("*.json")):
        if f"`{config_path.name}`" not in config_inventory:
            errors.append(
                "docs/operations/config-inventory.md: missing checked-in config "
                f"{config_path.name}"
            )

    readme = (repo_root / "README.md").read_text(encoding="utf-8-sig")
    market_section = readme.split("## Setup", 1)[0]
    try:
        builtin_markets = _builtin_market_rows(repo_root)
    except (OSError, SyntaxError, ValueError) as exc:
        errors.append(str(exc))
        builtin_markets = []
    for spec in builtin_markets:
        expected_row = (
            f"| `{spec['id']}` | {spec['city_label']} | {spec['display_unit']} | "
            f"`{spec['icao']}` | `{spec['timezone']}` |"
        )
        if expected_row not in market_section:
            errors.append(
                f"README.md: missing or stale built-in market row: {spec['id']}"
            )

    try:
        pyproject_dependencies = _dependency_map_from_pyproject(repo_root)
        requirements_dependencies = _dependency_map_from_requirements(repo_root)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if pyproject_dependencies != requirements_dependencies:
            errors.append(
                "dependency drift: pyproject.toml project dependencies and "
                "requirements.txt differ"
            )

    active_paths = [repo_root / relative for relative in CANONICAL_DOCS]
    active_paths.extend(_agent_files(repo_root))
    for path in sorted(set(active_paths)):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig")
        for match in legacy_command_matches(text):
            errors.append(
                f"{path.relative_to(repo_root)}: legacy command surface: {match}"
            )

    return sorted(set(errors))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate agent-facing documentation and knowledge contracts."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = audit_repo(args.repo_root)
    if errors:
        print(f"Agent docs audit: FAIL ({len(errors)} issue(s))")
        for error in errors:
            print(f"- {error}")
        return 1
    markdown_count = len(_markdown_files(args.repo_root.resolve()))
    agent_count = len(_agent_files(args.repo_root.resolve()))
    print(f"Agent docs audit: PASS ({agent_count} agent files, {markdown_count} Markdown files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
