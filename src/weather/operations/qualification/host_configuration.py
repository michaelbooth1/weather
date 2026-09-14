"""Complete current configuration/artifact bindings for split host acceptance.

Only the generated pair may differ from S. The closure includes every tracked
configuration/artifact plus the current release pointer, including its absence,
and every file in the pointed-to immutable release. No pickle is deserialized.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from . import environment, merge_tree, settlement_inputs, source
from .inputs import SourceRoots, _input_object, open_current, validate_current_generation, verified_input
from .records import checked_root, require


POINTER = "artifacts/releases/current_release.json"


def _current_object(production, path, budget):
    with open_current(production, path, maximum=2 * 1024**2) as (handle, generation):
        raw = handle.read(2 * 1024**2 + 1)
    budget.charge(len(raw))
    require(len(raw) <= 2 * 1024**2, "configuration metadata exceeds bound")
    return _input_object(raw.decode("utf-8"))


def required_paths(git, candidate, production, *, source_commit, baseline, budget):
    entries = merge_tree.tree_entries(git, candidate, source_commit)
    before = merge_tree.tree_entries(git, candidate, baseline)
    paths = sorted(path for path in entries if path.startswith(("config/", "artifacts/")))
    require(paths, "configuration/artifact inventory is empty")
    historical = {path for path in before if path.startswith(("config/", "artifacts/"))}
    require(historical == set(paths) and all(entries[path] == before[path] for path in paths
                                            if path not in merge_tree.GENERATED),
            "initial split qualification forbids configuration/artifact migration")
    required = set(paths)
    optional = {POINTER} - required
    try:
        pointer = _current_object(production, POINTER, budget)
    except OSError as exc:
        import os
        if isinstance(exc, FileNotFoundError) or os.name == "nt" and exc.errno in {2, 3}:
            return sorted(required), sorted(optional)
        raise
    release = pointer.get("active_release_id")
    require(type(release) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release) is not None,
            "active release pointer has an unsafe or missing release identity")
    prefix = "artifacts/releases/" + release
    root = checked_root(production / prefix)
    files = environment.enumerate_files(root)
    require("release_manifest.json" in files, "active release manifest is absent")
    manifest = _current_object(production, prefix + "/release_manifest.json", budget)
    require(manifest.get("release_id") == release, "release manifest and pointer identity differ")
    inventory = manifest.get("artifacts", {}).get("inventory")
    require(type(inventory) is list and 0 < len(inventory) <= 8192, "active release file inventory is incomplete")
    from .records import distinct_paths
    declared = [row["path"] for row in inventory]
    distinct_paths(declared)
    require(sorted([*declared, "release_manifest.json"]) == files, "active release has missing or unlisted files")
    required.update(prefix + "/" + path for path in files)
    required.add(POINTER)
    return sorted(required), []


def validate(git, production, *, candidate, source_commit, baseline, graph, configuration_ref, budget):
    """Check complete sealed Q against current generations and actual S bytes."""
    q = merge_tree.configuration(graph.get(configuration_ref))
    require(q["source"] == source_commit and q["baseline"] == baseline, "configuration source binding differs")
    required, optional = required_paths(git, candidate, production, source_commit=source_commit,
                                        baseline=baseline, budget=budget)
    entries = settlement_inputs.load_entries(graph, q["dependencies"])
    expected = set(required) | set(optional)
    require({row["path"] for row in entries} == expected and len(entries) == len(expected) and
            all(row["root"] == "production" and row["kind"] == "config" for row in entries),
            "configuration dependency closure is incomplete or contains another root")
    require(all(row["mandatory"] is (row["path"] in required) for row in entries),
            "required configuration/artifact was downgraded to optional")
    require(graph.get(q["dependencies"])["topologies"] == [], "configuration cannot borrow a settlement topology")
    source_entries = merge_tree.tree_entries(git, candidate, source_commit)
    source_files = {row["path"]: row for row in source.inventory(git, candidate, source_commit)["files"]}
    budget.charge(sum(row["size"] for row in source_files.values()))
    overlays = {item["path"]: item for item in q["generated"]}
    by_path = {row["path"]: row for row in entries}
    for row in entries:
        if not row["present"]:
            continue
        hasher = hashlib.sha256()
        with verified_input(graph.root, row["staged"], budget) as handle:
            while block := handle.read(1024 * 1024):
                hasher.update(block)
        if row["path"] in overlays:
            overlay = overlays[row["path"]]
            require(row["generation"] == overlay["generation"] and
                    row["staged"]["sha256"] == overlay["payload"]["sha256"] and
                    row["staged"]["size"] == overlay["payload"]["size"], "generated pair differs from complete Q")
        elif row["path"] in source_entries:
            expected = source_files[row["path"]]
            same_source = (row["staged"]["sha256"], row["staged"]["size"]) == (expected["sha256"], expected["size"])
            if same_source:
                continue
            require(row["path"].startswith("artifacts/") and expected["size"] <= 1024,
                    "current registry/artifact differs from reviewed source")
            raw = source.git_output(git, candidate, "cat-file", "blob", source_entries[row["path"]]["oid"], maximum=1024)
            budget.charge(len(raw))
            match = re.fullmatch(rb"version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n", raw)
            require(match is not None and (hasher.hexdigest(), row["staged"]["size"]) == (match[1].decode(), int(match[2])),
                    "current artifact differs from complete source-bound LFS payload")
    roots = SourceRoots({"production": production}, {"production": ["config", "artifacts"]}, relative_root="production")
    validate_current_generation(roots, entries, [], budget)
    merge_tree.revalidate_generated(production, graph, configuration_ref)
    graph.fresh()
    return {"configuration_sha256": configuration_ref["sha256"], "file_count": len(entries),
            "read_bytes": budget.observed_bytes, "current_pointer_present": by_path[POINTER]["present"]}
