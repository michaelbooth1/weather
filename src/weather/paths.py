"""Repository path helpers used by source, app, scripts, and tests."""

from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = SRC_ROOT.parent
DATA_ROOT = REPO_ROOT / "data"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
DOCS_ROOT = REPO_ROOT / "docs"
TOOLS_ROOT = REPO_ROOT / "tools"
CONFIG_ROOT = REPO_ROOT / "config"


def repo_path(*parts: str | Path) -> Path:
    return REPO_ROOT.joinpath(*parts)


def data_path(*parts: str | Path) -> Path:
    return DATA_ROOT.joinpath(*parts)


def artifacts_path(*parts: str | Path) -> Path:
    return ARTIFACTS_ROOT.joinpath(*parts)


def relative_to_repo(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()

