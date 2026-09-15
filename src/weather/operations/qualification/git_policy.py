"""Frozen Git interpretation for the typed guarded merge.

Local configuration is byte bound; includes, external merge/diff drivers and
unreviewed filters are refused. Hooks and global/system attributes are disabled.
The sole optional LFS clean/smudge tool must occur in the qualified native-file
inventory. No discovery result is accepted as its own review.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import subprocess

from . import environment, merge_tree, source
from .contracts import fields, record
from .records import checked_root, digest, require


def _identity(path):
    path = Path(path)
    try:
        value = environment.file_identity(checked_root(path.parent), path.name, maximum=2 * 1024**2)
    except FileNotFoundError:
        return {"path": str(path), "present": False, "sha256": None, "size": 0}
    return {"path": str(path), "present": True, "sha256": value["sha256"], "size": value["size"]}


def _config(git, repository):
    raw = source.git_output(git, repository, "config", "--local", "--no-includes", "--null", "--list", maximum=2 * 1024**2)
    require(not raw or raw.endswith(b"\0"), "truncated local Git configuration")
    for entry in raw.split(b"\0")[:-1]:
        key = entry.split(b"\n", 1)[0].decode("utf-8").lower()
        require(not key.startswith(("include.", "includeif.")), "Git configuration includes are not qualified")
        require(not (key.startswith("merge.") and key.endswith(".driver")), "external Git merge driver refused")
        require(not (key.startswith("filter.") and not key.startswith("filter.lfs.")), "unreviewed Git filter refused")
        require(key != "diff.external" and not (key.startswith("diff.") and key.endswith((".command", ".textconv"))),
                "external Git diff conversion refused")
        require(not key.startswith("url.") and not key.endswith(".extraheader") and
                key not in {"core.sshcommand", "core.gitproxy", "core.worktree"}, "redirected Git endpoint or worktree refused")
    return hashlib.sha256(raw).hexdigest()


def _git_directory(git, repository, argument):
    raw = source.git_output(git, repository, "rev-parse", argument).decode("utf-8").strip()
    path = Path(raw)
    return checked_root(path if path.is_absolute() else repository / path)


def _local_state(git, repository):
    local = _git_directory(git, repository, "--git-dir")
    common = _git_directory(git, repository, "--git-common-dir")
    paths = sorted({common / "config", local / "config.worktree", common / "info/attributes"}, key=str)
    rows = []
    for path in paths:
        # Git's optional info directory may itself be absent. Its appearance
        # with an attributes file is still detected by the later full recheck.
        if not path.parent.exists():
            rows.append({"path": str(path), "present": False, "sha256": None, "size": 0})
        else:
            rows.append(_identity(path))
    return {"root": str(repository), "local": str(local), "common": str(common),
            "config_sha256": _config(git, repository), "files": rows}


def _attributes(git, candidate, baseline, commit):
    before, after = [merge_tree.tree_entries(git, candidate, value) for value in (baseline, commit)]
    selected = lambda entries: {path: item for path, item in entries.items() if Path(path).name == ".gitattributes"}
    first, last = selected(before), selected(after)
    require(first == last, "initial split adoption cannot change Git attributes")
    rows, lfs = [], False
    for path, item in sorted(last.items()):
        raw = source.git_output(git, candidate, "cat-file", "blob", item["oid"], maximum=1024**2)
        for line in raw.decode("utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            tokens = line.split()
            require(not tokens[0].startswith("[attr]"), "Git attribute macros require separate review")
            for token in tokens[1:]:
                if token.startswith("filter="):
                    require(token == "filter=lfs", "unreviewed Git attribute filter")
                    lfs = True
                if token.startswith("merge="):
                    require(token in {"merge=lfs", "merge=text", "merge=binary", "merge=union"},
                            "unreviewed Git attribute merge driver")
                require(not token.startswith("working-tree-encoding="), "working-tree encoding migration refused")
        rows.append({"path": path, "git_blob": item["oid"], "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
    return rows, lfs


def native_lfs(graph, environment_ref, bindings, *, required):
    if not required:
        return None
    reviewed = graph.get(environment_ref)
    files = graph.get(reviewed["native_files"])["files"]
    candidates = [row for row in files if Path(row["path"]).name.lower() in {"git-lfs", "git-lfs.exe"}]
    require(len(candidates) == 1, "qualified native inventory must pin exactly one Git LFS executable")
    item = candidates[0]
    root = checked_root(Path(bindings["native"]))
    actual = environment.file_identity(root, item["path"], native_installation=True)
    require(actual == item, "qualified Git LFS executable changed")
    return {"root": str(root), **item}


def capture(git, production, candidate, *, baseline, commit, hooks, graph, environment_ref, bindings):
    """Preparatory snapshot; arming and every native mutation revalidate it."""
    production, candidate, hooks = [checked_root(Path(root)) for root in (production, candidate, hooks)]
    require(not any(hooks.iterdir()), "qualification hooks directory must be empty")
    attributes, lfs_required = _attributes(git, candidate, baseline, commit)
    state = [_local_state(git, root) for root in (production, candidate)]
    require(all(not row["present"] or row["size"] == 0 for tree in state for row in tree["files"]
                if Path(row["path"]).name == "attributes"), "repository-local attribute override refused")
    require(all(not row["present"] or row["size"] == 0 for tree in state for row in tree["files"]
                if Path(row["path"]).name == "config.worktree"), "worktree-local Git overrides require separate review")
    return {"schema": "qualification_git_policy_v2", "baseline": digest(baseline, git=True),
        "source": digest(commit, git=True), "git": environment.file_identity(Path(git).parent, Path(git).name, native_installation=True),
        "git_root": str(Path(git).parent), "hooks": str(hooks), "repositories": state, "attributes": attributes,
        "lfs": native_lfs(graph, environment_ref, bindings, required=lfs_required)}


def validate(value, *, git, production, candidate, baseline, commit, graph, environment_ref, bindings):
    record(value, "qualification_git_policy_v2", {"baseline", "source", "git", "git_root", "hooks", "repositories", "attributes", "lfs"})
    observed = capture(git, production, candidate, baseline=baseline, commit=commit, hooks=value["hooks"],
                       graph=graph, environment_ref=environment_ref, bindings=bindings)
    require(value == observed, "effective Git policy changed after review")
    for path in value["attributes"]:
        for root in (production, candidate):
            actual = environment.file_identity(Path(root), path["path"])
            require(actual["sha256"] == path["sha256"] and actual["size"] == path["size"], "working Git attributes changed")
    return options(value)


def options(value):
    """Fixed arguments used by the native parent's Git wrapper, never a hook."""
    settings = {"core.fsmonitor": "false", "core.untrackedCache": "false", "core.hooksPath": value["hooks"],
        "core.attributesFile": os.devnull, "core.autocrlf": "false", "core.eol": "lf",
        "commit.gpgSign": "false", "tag.gpgSign": "false", "credential.helper": "", "core.askPass": "",
        "filter.lfs.process": "", "filter.lfs.required": "true" if value["lfs"] else "false"}
    if value["lfs"]:
        item = value["lfs"]
        executable = (Path(item["root"]) / item["path"]).as_posix()
        require(not any(char in executable for char in "\r\n\0"), "invalid native filter path")
        for mode in ("clean", "smudge"):
            settings["filter.lfs." + mode] = shlex.quote(executable) + " " + mode + " -- %f"
    else:
        settings.update({"filter.lfs.clean": "", "filter.lfs.smudge": ""})
    return ["--no-replace-objects", *(word for key, value in settings.items() for word in ("-c", key + "=" + value))]
