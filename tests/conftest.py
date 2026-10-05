"""Keep pytest's base temp short on Windows, wherever the caller points it.

Tests build nested layouts under ``tmp_path`` that need about 200 characters of
their own. A deep ``--basetemp`` (an agent scratchpad, a nested worktree) or a
deep ``TEMP`` pushed those paths past Windows' 260-character limit and failed
tests with ``FileNotFoundError``. On Windows any base temp longer than
``MAX_BASETEMP_CHARS`` is replaced by a fresh ``<SystemDrive>\\pt\\t-*`` directory,
which this session removes when it ends, so callers that delete their own
``--basetemp`` still leave nothing behind. Short base temps (the bounded suite's
``C:\\pt\\bs-*`` chunks, CI runners) are left exactly as given.
"""

from __future__ import annotations

import getpass
import os
import shutil
import tempfile
from pathlib import Path

import pytest

MAX_BASETEMP_CHARS = 64
_DEFAULT_SUFFIX_CHARS = len("\\pytest-of-\\pytest-999")
_relocated: dict[str, Path] = {}


def planned_basetemp_chars(requested: str | None, *, tempdir: str, user: str) -> int:
    """Length of the base temp pytest would use without relocation."""

    if requested:
        return len(os.path.abspath(requested))
    return len(tempdir) + len(user) + _DEFAULT_SUFFIX_CHARS


def needs_short_basetemp(requested: str | None, *, tempdir: str, user: str, is_windows: bool) -> bool:
    return is_windows and planned_basetemp_chars(requested, tempdir=tempdir, user=user) > MAX_BASETEMP_CHARS


def _user() -> str:
    try:
        return getpass.getuser()
    except (ImportError, OSError, KeyError):
        return "unknown"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    # Runs before pytest's tmpdir plugin reads ``config.option.basetemp``.
    requested = config.option.basetemp
    if not needs_short_basetemp(
        requested, tempdir=tempfile.gettempdir(), user=_user(), is_windows=os.name == "nt"
    ):
        return
    root = Path(os.environ.get("SystemDrive", "C:") + "\\") / "pt"
    root.mkdir(exist_ok=True)
    short = Path(tempfile.mkdtemp(prefix="t-", dir=root))
    _relocated["requested"] = Path(requested) if requested else Path(tempfile.gettempdir())
    _relocated["short"] = short
    config.option.basetemp = str(short)


def pytest_report_header(config: pytest.Config) -> str | None:
    if "short" not in _relocated:
        return None
    return (
        f"basetemp relocated for Windows path length: {_relocated['requested']} -> "
        f"{_relocated['short']} (removed at exit)"
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    short = _relocated.pop("short", None)
    _relocated.clear()
    if short is not None:
        shutil.rmtree(short, ignore_errors=True)
