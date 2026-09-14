"""Deterministic S-plus-Q tree and actual working-byte checks for the primitive.

These routines never merge, stage, commit, reset or push. The adopted primitive
calls them at its own mutation boundaries under the same lease. A check made
only after publication cannot replace any of those boundaries.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from . import environment, source
from .contracts import fields, inventory, record, sequence
from .inputs import generation, open_current
from .records import digest, distinct_paths, integer, open_record, reference, require


GENERATED = ("config/location_market_events.json", "config/locations.json")


def tree_entries(git, root, commit):
    digest(commit, git=True)
    raw = source.git_output(git, root, "ls-tree", "-rz", "--full-tree", commit)
    require(raw.endswith(b"\0"), "complete nonempty source tree required")
    entries = {}
    for row in raw[:-1].split(b"\0"):
        metadata, name = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        require(mode in {"100644", "100755"} and kind == "blob", "source tree contains a link or submodule")
        path = name.decode("utf-8")
        require(path not in entries, "duplicate Git tree path")
        entries[path] = {"mode": mode, "oid": digest(oid, git=True)}
    require(len(entries) <= source.MAX_TRACKED_FILES, "source tree file bound")
    distinct_paths(list(entries))
    return entries


def object_id(kind, raw):
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def tree_id(entries):
    """Git's byte ordering includes a trailing slash when sorting a subtree."""
    root = {}
    distinct_paths(list(entries))
    for path, value in entries.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            existing = node.setdefault(part, {})
            require(type(existing) is dict, "tree file/directory collision")
            node = existing
        require(parts[-1] not in node, "tree file/directory collision")
        require(value["mode"] in {"100644", "100755"}, "unsupported tree mode")
        node[parts[-1]] = (value["mode"], digest(value["oid"], git=True))

    def encode(node):
        result = []
        for name in sorted(node, key=lambda key: (key + ("/" if type(node[key]) is dict else "")).encode("utf-8")):
            value = node[name]
            mode, oid = ("40000", object_id("tree", encode(value))) if type(value) is dict else value
            result.append(mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid))
        return b"".join(result)

    return object_id("tree", encode(root))


def configuration(value):
    value = record(value, "qualification_configuration_v2", {"source", "baseline", "generated", "dependencies"})
    digest(value["source"], git=True)
    digest(value["baseline"], git=True)
    reference(value["dependencies"])
    generated = sequence(value["generated"], minimum=2, maximum=2)
    require([fields(item, {"path", "payload", "git_blob", "generation"})["path"] for item in generated] == list(GENERATED),
            "only the canonical generated pair may overlay source")
    for item in generated:
        reference(item["payload"])
        digest(item["git_blob"], git=True)
        observed = fields(item["generation"], {"device", "file_id", "size", "mtime_ns", "ctime_ns"})
        for name in ("device", "file_id"):
            require(type(observed[name]) is str and observed[name].isascii() and observed[name].isdigit(), "invalid config generation")
        for name in ("size", "mtime_ns", "ctime_ns"):
            integer(observed[name])
        require(observed["size"] == item["payload"]["size"], "config generation size differs")
    return value


def preview(git, source_root, *, source_commit, source_tree, baseline, config_graph, configuration_ref):
    q = configuration(config_graph.get(configuration_ref))
    require(q["source"] == source_commit and q["baseline"] == baseline, "configuration belongs to another source/baseline")
    entries = tree_entries(git, source_root, source_commit)
    require(tree_id(entries) == source_tree, "source tree differs from reviewed source")
    baseline_entries = tree_entries(git, source_root, baseline)
    # Initial v2 has no artifact/environment migration lane. Existing LFS
    # payloads remain readable, but a changed artifact needs separate review.
    require({p: v for p, v in entries.items() if p.startswith("artifacts/")} ==
            {p: v for p, v in baseline_entries.items() if p.startswith("artifacts/")},
            "initial split qualification does not support tracked artifact changes")
    for item in q["generated"]:
        require(item["path"] in entries and entries[item["path"]]["mode"] == "100644", "generated source path missing or executable")
        config_graph.blob(item["payload"], maximum=2 * 1024**2)
        with open_record(config_graph.root, item["payload"]["path"]) as handle:
            raw = handle.read(2 * 1024**2 + 1)
        require(object_id("blob", raw) == item["git_blob"], "configuration blob identity differs")
        entries[item["path"]] = {"mode": "100644", "oid": item["git_blob"]}
    config_graph.fresh()
    return {"schema": "qualification_effective_tree_v2", "source": source_commit, "baseline": baseline,
            "configuration_sha256": configuration_ref["sha256"], "tree": tree_id(entries)}


def revalidate_generated(production, config_graph, configuration_ref):
    q = configuration(config_graph.get(configuration_ref))
    for item in q["generated"]:
        with open_current(production, item["path"], maximum=2 * 1024**2) as (handle, current):
            require(current == item["generation"], "generated config generation changed")
            raw = handle.read(2 * 1024**2 + 1)
        require(len(raw) == item["payload"]["size"] and hashlib.sha256(raw).hexdigest() == item["payload"]["sha256"],
                "generated config bytes changed")
    config_graph.fresh()


def working_bytes(git, production, *, source_root, source_commit, source_inventory, config_graph, configuration_ref):
    """Check every represented source byte, including unsmudged LFS payloads.

    An existing LFS payload is admissible only when the source's actual pointer
    binds its entire SHA256 and size. An arbitrary tracked working-file change
    cannot use that exception. Git tree identity remains the pointer identity.
    """
    files = inventory(source_inventory, "qualification_source_inventory_v2")["files"]
    q = configuration(config_graph.get(configuration_ref))
    overlays = {item["path"]: item for item in q["generated"]}
    entries = tree_entries(git, source_root, source_commit)
    require(set(entries) == {item["path"] for item in files}, "working verification source inventory incomplete")
    indexed = source.git_output(git, production, "ls-files", "-z").decode("utf-8").split("\0")[:-1]
    require(set(indexed) == set(entries) and len(indexed) == len(entries), "production tracked file set differs")
    for item in files:
        path = item["path"]
        expected = overlays[path]["payload"] if path in overlays else item
        actual = environment.file_identity(production, path)
        if (actual["sha256"], actual["size"]) == (expected["sha256"], expected["size"]):
            continue
        require(path.startswith("artifacts/") and path not in overlays and item["size"] <= 1024,
                "effective working source/config bytes differ")
        pointer = source.git_output(git, source_root, "cat-file", "blob", entries[path]["oid"], maximum=1024)
        match = re.fullmatch(rb"version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n", pointer)
        require(match is not None and actual["sha256"] == match[1].decode("ascii") and actual["size"] == int(match[2]),
                "working artifact is not the source-bound complete LFS payload")
    revalidate_generated(production, config_graph, configuration_ref)


def staged_tree(git, production, expected_tree):
    require(source.git_output(git, production, "diff", "--name-only", "--diff-filter=U") == b"", "merge has conflicts")
    actual = source.git_output(git, production, "write-tree").decode("ascii").strip()
    require(actual == digest(expected_tree, git=True), "staged merge differs from the reviewed effective tree")


def committed_tree(git, production, *, expected_tree, first_parent, source_commit):
    parts = source.git_output(git, production, "rev-list", "--parents", "-n", "1", "HEAD").decode("ascii").split()
    require(len(parts) == 3 and parts[1:] == [first_parent, source_commit], "integration is not the exact two-parent merge")
    require(source.git_output(git, production, "rev-parse", "HEAD^{tree}").decode("ascii").strip() == expected_tree,
            "committed merge differs from the reviewed effective tree")
    return digest(parts[0], git=True)
