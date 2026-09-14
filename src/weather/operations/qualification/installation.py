"""Reproduce a reviewed dependency set from retained wheels, with no index.

Preparation/install runs off-host before candidate execution. Existing targets
are never repaired, reused or upgraded; failed installations remain spent.
"""

from __future__ import annotations

from pathlib import Path

from . import environment
from .contracts import record, sequence, text
from .records import checked_root, digest, fields, integer, publish, relative_path, require


def lock(value):
    value = record(value, "qualification_dependency_lock_v2", {"platform", "python_version", "python_sha256", "wheels"})
    require(value["platform"] in {"windows", "linux"}, "unsupported installation platform")
    text(value["python_version"])
    require(len(value["python_version"].split(".")) == 3, "exact interpreter patch required")
    digest(value["python_sha256"])
    names, filenames = set(), set()
    for wheel in sequence(value["wheels"], minimum=1, maximum=512):
        fields(wheel, {"name", "version", "filename", "sha256", "size"})
        name = environment.distribution_name(wheel["name"])
        require(name == wheel["name"] and name not in names, "duplicate/noncanonical dependency name")
        names.add(name)
        version = text(wheel["version"])
        require(all(c.isalnum() or c in ".+-_!" for c in version), "invalid fixed dependency version")
        filename = relative_path(wheel["filename"])
        require("/" not in filename and filename.endswith(".whl") and filename.casefold() not in filenames,
                "invalid/duplicate retained wheel filename")
        filenames.add(filename.casefold())
        digest(wheel["sha256"])
        integer(wheel["size"], minimum=1, maximum=512 * 1024**2)
    return value


def prepare(value, *, wheel_root, destination, python_path):
    """Verify wheel bytes and emit only fixed offline pip arguments.

    The adopted off-host wrapper executes the returned argv with its pinned
    interpreter/pip closure and native containment. Returning argv is not an
    installation PASS; the producer verifies the resulting complete environment.
    """
    value = lock(value)
    wheel_root = checked_root(wheel_root)
    python_path = Path(python_path)
    require(python_path.is_absolute(), "absolute reviewed installer interpreter required")
    identity = environment.file_identity(python_path.parent, python_path.name, native_installation=True)
    require(identity["sha256"] == value["python_sha256"], "installer interpreter differs")
    for wheel in value["wheels"]:
        actual = environment.file_identity(wheel_root, wheel["filename"])
        require(actual["sha256"] == wheel["sha256"] and actual["size"] == wheel["size"], "retained wheel differs")
    observed = environment.enumerate_files(wheel_root)
    require(observed == sorted(item["filename"] for item in value["wheels"]), "wheel directory contains unreviewed files")
    destination = Path(destination)
    require(destination.is_absolute(), "absolute installation destination required")
    checked_root(destination.parent)
    require(not destination.exists() and not destination.is_relative_to(wheel_root), "installation namespace spent or overlaps wheels")
    destination.mkdir()
    # An explicit prefix preserves installation-owned RECORD paths. No build
    # backend, editable project, extra dependency resolution or index is used.
    lines = [item["name"] + "==" + item["version"] + " --hash=sha256:" + item["sha256"] for item in value["wheels"]]
    requirements = destination / "reviewed-requirements.txt"
    with requirements.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        import os
        os.fsync(handle.fileno())
    publish(destination, "installation-claim.json", value)
    return [str(python_path), "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
            "--no-input", "--no-index", "--no-deps", "--only-binary=:all:", "--no-compile", "--ignore-installed",
            "--require-hashes", "--find-links", str(wheel_root), "--prefix", str(destination / "prefix"),
            "--report", str(destination / "installation-report.json"), "-r", str(requirements)]
