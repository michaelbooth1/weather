"""No credential file is ever tracked, and the credential locations stay git-ignored.

Guards: owner rule 2026-10-09 (relayed with the wallet-reader any-LAN decision) -- credentials are
NEVER uploaded to GitHub; docs/operations/wallet-reader.md (.env and config/local/ hold the reader
and venue secrets) and AGENTS.md (no credentials in the repository).
"""

from __future__ import annotations

from pathlib import PurePosixPath
import subprocess

import pytest

from weather.paths import REPO_ROOT

pytestmark = [pytest.mark.ratchet, pytest.mark.spawns]

# Names-only templates and placeholders that may be tracked.
ALLOWED_ENV = frozenset({".env.example"})
ALLOWED_CONFIG_LOCAL = frozenset({"README.md", ".gitkeep"})


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, check=False)


def forbidden_tracked(paths: list[str]) -> list[str]:
    """Return every tracked path that is a credential location (pure; unit-tested below)."""
    bad = []
    for name in paths:
        path = PurePosixPath(name)
        if path.name.startswith(".env") and path.name not in ALLOWED_ENV:
            bad.append(name)
        elif path.parts[:2] == ("config", "local") and not (
                len(path.parts) == 3 and (path.name in ALLOWED_CONFIG_LOCAL or ".example" in path.name)):
            bad.append(name)
    return bad


def test_no_credential_file_is_tracked() -> None:
    completed = _git("ls-files", "-z")
    assert completed.returncode == 0
    tracked = [name for name in completed.stdout.decode("utf-8").split("\0") if name]
    assert tracked, "git ls-files returned nothing"
    assert forbidden_tracked(tracked) == []


@pytest.mark.parametrize("path", [
    ".env", ".env.local", ".env.prod", "src/.env", "config/local/wallet_reader_client.json",
    "config/local/anything.json", "config/local/sub/README.md",
])
def test_credential_locations_are_git_ignored(path: str) -> None:
    completed = _git("check-ignore", "-q", "--no-index", path)
    assert completed.returncode == 0, f"{path} is not git-ignored"


def test_env_example_stays_trackable() -> None:
    assert _git("check-ignore", "-q", "--no-index", ".env.example").returncode == 1


@pytest.mark.parametrize("paths,expected", [
    ([".env.example", "config/local/README.md", "config/local/.gitkeep", "config/local/client.example.json",
      "config/registry.json", "docs/env.md"], []),
    ([".env"], [".env"]),
    (["app/.env.production"], ["app/.env.production"]),
    (["config/local/wallet_reader_client.json"], ["config/local/wallet_reader_client.json"]),
    (["config/local/nested/README.md"], ["config/local/nested/README.md"]),
])
def test_forbidden_tracked_classifier(paths: list[str], expected: list[str]) -> None:
    assert forbidden_tracked(paths) == expected
