from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _requirements_dependencies(path: Path) -> list[str]:
    deps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        deps.append(line)
    return deps


def test_requirements_and_pyproject_dependency_pins_match():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_deps = sorted(pyproject["project"]["dependencies"])
    requirements_deps = sorted(_requirements_dependencies(REPO_ROOT / "requirements.txt"))

    assert requirements_deps == pyproject_deps
