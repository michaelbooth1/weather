"""No tracked file carries a WU page-token value.

Guards: OD15 (owner decision 2026-10-06) -- the scraped WU page token is never committed or pushed;
the repository-wide scan uses the same patterns as the production leak scanner.
"""

from __future__ import annotations

import subprocess

import pytest

from weather.operations.wu_token_scan import EXIT_CLEAN, exit_code_for, scan, unread_reasons
from weather.paths import REPO_ROOT

pytestmark = [pytest.mark.ratchet, pytest.mark.spawns]

MAX_TRACKED_FILE_BYTES = 1024 * 1024 * 1024


def _tracked_files():
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    names = [name for name in completed.stdout.decode("utf-8").split("\0") if name]
    return [REPO_ROOT / name for name in names]


def test_no_tracked_file_contains_a_wu_api_key_value():
    files = [path for path in _tracked_files() if path.exists() or path.is_symlink()]
    assert files, "git ls-files returned nothing"

    result = scan([], files=files, max_files=len(files) + 1, max_file_bytes=MAX_TRACKED_FILE_BYTES,
                  max_total_bytes=64 * MAX_TRACKED_FILE_BYTES)

    assert result.errors == []
    assert result.skipped_oversize == []
    assert result.truncated_reason is None
    # N3: nothing named in the list may go unread (a directory, link or reparse point).
    assert unread_reasons(result) == []
    assert exit_code_for(result) == EXIT_CLEAN
    # Paths and counts only: a failure message must not quote the token itself.
    assert [(row["path"], row["matches"]) for row in result.findings] == []
