"""No repository code bypasses git hooks (`core.hooksPath` override or `--no-verify`).

Guards: the repository rule of never bypassing git hooks (incident 2026-10-22: the
correspondence-index closeout committed with `git -c core.hooksPath=`).

Scans every tracked file under scripts/ops/, src/, tools/, app/ and .github/
(enumerated with `git ls-files`), case-insensitively, so `-c core.hookspath=` and
`--NO-VERIFY` are caught too. LEGACY lists the occurrences that predate this ratchet,
one exact line per entry with its reason; it may only shrink, and a listed line that
no longer exists fails as stale so the list is pruned when the code is fixed.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from weather.paths import REPO_ROOT

pytestmark = [pytest.mark.ratchet, pytest.mark.spawns]

SCOPES = ("scripts/ops/", "src/", "tools/", "app/", ".github/")
PATTERN = re.compile(r"core\.hookspath|--no-verify", re.IGNORECASE)

# (path, stripped line) -> reason. Read-only or scratch-store git plumbing that
# predates the ratchet; none of them commits to a real repository.
_READ_ONLY = "pre-existing; read-only git plumbing (status/rev-parse/ls-files), never commits"
LEGACY: dict[tuple[str, str], str] = {
    ("scripts/ops/bounded_worktree_test_suite.ps1", '"-c", "core.hooksPath=NUL"'): _READ_ONLY,
    ("scripts/ops/workstation_pregate.ps1",
     "$rows = @(& $GitExe -c core.fsmonitor=false -c core.hooksPath=NUL @Arguments 2>&1 |"): _READ_ONLY,
    ("scripts/ops/international_live_templates/stage0.py.tmpl", 'f"core.hooksPath={os.devnull}",'):
        "pre-existing; sealed live-wrapper template (release-bound bytes), read-only git",
    ("scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl", 'f"core.hooksPath={os.devnull}",'):
        "pre-existing; sealed live-wrapper template (release-bound bytes), read-only git",
    ("src/weather/operations/international_live_wrapper_sealer.py", 'f"core.hooksPath={os.devnull}",'):
        "pre-existing; live-wrapper sealer read-only git and ls-remote",
    ("src/weather/operations/landing_preflight.py",
     'GIT_SAFETY_CONFIG = ("-c", "maintenance.auto=false", "-c", "gc.auto=0", "-c", f"core.hooksPath={os.devnull}")'):
        "pre-existing; preflight merge-tree in a private scratch object store",
    ("src/weather/operations/landing_preflight.py", 'ctx.git("config", "core.hooksPath", str(hooks))'):
        "pre-existing; configures the private scratch bare store, not a real repository",
}


def find_bypasses(files: dict[str, str]) -> list[tuple[str, int, str]]:
    """Return (path, line number, stripped line) for every match (pure; unit-tested below)."""
    hits = []
    for path, text in sorted(files.items()):
        for number, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                hits.append((path, number, line.strip()))
    return hits


def _tracked_texts() -> dict[str, str]:
    completed = subprocess.run(["git", "ls-files", "-z", "--", *SCOPES], cwd=REPO_ROOT,
                               capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    names = [name for name in completed.stdout.decode("utf-8").split("\0") if name]
    assert names, "git ls-files returned nothing"
    texts = {}
    for name in names:
        path = REPO_ROOT / name
        if path.is_file():
            texts[name] = path.read_bytes().decode("utf-8", errors="replace")
    return texts


def test_no_tracked_code_bypasses_git_hooks() -> None:
    hits = find_bypasses(_tracked_texts())
    new = [f"{path}:{number}: {line}" for path, number, line in hits if (path, line) not in LEGACY]
    assert new == [], "git hook bypass in tracked code (remove it; do not allowlist):\n" + "\n".join(new)
    stale = sorted(set(LEGACY) - {(path, line) for path, _, line in hits})
    assert stale == [], f"LEGACY entries no longer present; delete them: {stale}"


@pytest.mark.parametrize("line", [
    'Invoke-Git $w @("-c", "core.hooksPath=", "commit")',
    "git -c core.hookspath= commit -m x",
    "git commit --no-verify -m x",
    "git push --NO-VERIFY",
    "git config core.HooksPath /dev/null",
])
def test_pattern_flags_every_spelling(line: str) -> None:
    assert find_bypasses({"scripts/ops/x.ps1": line}) == [("scripts/ops/x.ps1", 1, line)]


@pytest.mark.parametrize("line", [
    'Invoke-Git $w @("commit", "--quiet", "-m", "msg")',
    "git config core.hooks /x",
    "git commit --verify",
])
def test_pattern_ignores_ordinary_git(line: str) -> None:
    assert find_bypasses({"scripts/ops/x.ps1": line}) == []
