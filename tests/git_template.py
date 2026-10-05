"""Session-cached single-commit git fixture repositories.

Many fixtures write a small source tree and then run ``git init``, ``git add .``
and ``git commit`` so a script under test sees a clean checkout at a known tip.
Spawning git is the expensive part on Windows. ``commit_fixture_tree`` keeps the
result identical while spawning fewer processes:

* The first call for a given shape (the exact set of relative file paths, the
  commit message and the ``-c`` configuration) runs the original three commands
  in ``source`` and keeps a copy of the resulting ``.git`` directory.
* Later calls with the same shape copy that ``.git`` into ``source`` and run one
  ``git commit --all --amend``. The tracked path set is identical by
  construction, so ``--all`` stages exactly what ``git add .`` would have
  staged (every per-test byte, such as a unique mutex name, is re-hashed), and
  ``--amend`` of the root commit yields again a single parentless commit with
  the same message, identity and tree as a fresh build.

What a script can observe in the checkout is the same: ``HEAD`` is one root
commit whose tree is the current files, the index matches, and
``git status --porcelain`` is clean. The only differences are an unreachable
template commit object and one extra reflog line, which no fixture user reads.
The ``.git`` directory of a plain ``git init`` holds no absolute paths, so a
copy is relocatable. Use this only for single-commit trees without worktrees,
submodules or remotes; anything else keeps its own git commands.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


def _git(*arguments: str, timeout: float) -> str:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _shape_key(source: Path, config: Sequence[str], message: str) -> str:
    paths = sorted(path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file())
    payload = json.dumps({"paths": paths, "config": list(config), "message": message})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def commit_fixture_tree(
    source: Path,
    *,
    cache_root: Path,
    config: Sequence[str],
    message: str,
    quiet: bool = False,
    timeout: float = 40,
) -> str:
    """Make ``source`` a one-commit repository of its current files; return HEAD.

    Equivalent to ``git init <source>``, ``git -C <source> add .`` and
    ``git -C <source> -c <config>... commit [-q] -m <message>``.
    """
    source = Path(source)
    assert not (source / ".git").exists(), source
    config_args = [item for pair in (("-c", value) for value in config) for item in pair]
    quiet_args = ["-q"] if quiet else []
    template = Path(cache_root) / _shape_key(source, config, message)
    if (template / "HEAD").is_file():
        shutil.copytree(template, source / ".git")
        _git("-C", str(source), *config_args, "commit", *quiet_args, "--all", "--amend", "--no-edit",
             timeout=timeout)
    else:
        _git("init", *quiet_args, str(source), timeout=timeout)
        _git("-C", str(source), "add", ".", timeout=timeout)
        _git("-C", str(source), *config_args, "commit", *quiet_args, "-m", message, timeout=timeout)
        template.parent.mkdir(parents=True, exist_ok=True)
        staging = template.with_name(template.name + ".partial")
        shutil.copytree(source / ".git", staging)
        staging.rename(template)
    return _git("-C", str(source), "rev-parse", "HEAD", timeout=timeout)
