"""Read-only installation inventories with explicit roots and wheel provenance.

Discovery is preparatory evidence, never an approved environment by itself. The
review pins these raw-byte manifests before tests run. No pip command, package
import, credential value, installation or environment repair occurs here.
"""

from __future__ import annotations

import base64
import csv
import hashlib
from importlib import metadata
import io
import os
from pathlib import Path
import re
import stat

from .records import checked_root, digest, distinct_paths, fields, integer, open_record, relative_path, require


MAX_FILE_BYTES = 512 * 1024**2
MAX_ENVIRONMENT_BYTES = 4 * 1024**3
MAX_ENVIRONMENT_FILES = 30_000
NAME = re.compile(r"[-_.]+")


def distribution_name(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value),
            "invalid distribution name")
    return NAME.sub("-", value).lower()


def file_identity(root, path, *, maximum=MAX_FILE_BYTES):
    """Hash the entire regular file through the shared anti-redirection reader."""
    relative_path(path)
    hasher, size = hashlib.sha256(), 0
    with open_record(root, path) as handle:
        while part := handle.read(min(1024 * 1024, maximum + 1 - size)):
            size += len(part)
            require(size <= maximum, "environment file exceeds bound")
            hasher.update(part)
    return {"path": path, "sha256": hasher.hexdigest(), "size": size, "mode": "100644"}


def rooted_path(root, path):
    # abspath normalizes RECORD's installer-owned ../Scripts references, but
    # deliberately does not resolve symlinks/reparse points before open_record.
    checked_root(root)
    actual = Path(os.path.abspath(path))
    try:
        result = actual.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("installed file escapes approved installation root") from exc
    return relative_path(result)


def files_manifest(root, paths):
    paths = sorted(paths)
    require(0 < len(paths) <= MAX_ENVIRONMENT_FILES, "installation file count exceeds bound")
    distinct_paths(paths)
    files, total = [], 0
    for path in paths:
        item = file_identity(root, path)
        total += item["size"]
        require(total <= MAX_ENVIRONMENT_BYTES, "installation bytes exceed bound")
        files.append(item)
    return {"schema": "qualification_runtime_files_v2", "files": files}


def enumerate_files(root, *, excluded_directories=()):
    """Walk only an explicitly declared installation root; reject redirects."""
    checked_root(root)
    for excluded in excluded_directories:
        relative_path(excluded)
    result = []
    for directory, names, files in os.walk(root, followlinks=False):
        kept = []
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                    "redirected installation directory")
            if relative not in excluded_directories:
                kept.append(name)
        names[:] = kept
        for name in sorted(files):
            result.append((Path(directory) / name).relative_to(root).as_posix())
            require(len(result) <= MAX_ENVIRONMENT_FILES, "installation file count exceeds bound")
    distinct_paths(result)
    return sorted(result)


def _record_rows(raw):
    require(type(raw) is str and len(raw.encode("utf-8")) <= 4 * 1024**2, "invalid installed RECORD")
    rows = list(csv.reader(io.StringIO(raw), strict=True))
    require(0 < len(rows) <= MAX_ENVIRONMENT_FILES, "invalid installed RECORD size")
    require(all(len(row) == 3 and row[0] for row in rows), "malformed installed RECORD row")
    return rows


def installed_distribution(distribution, installation_root):
    """Verify RECORD against actual bytes, retaining unhashed generated entries."""
    raw = distribution.read_text("RECORD")
    require(raw is not None, "installed distribution has no RECORD")
    paths, expected = [], {}
    for path, encoded_hash, size in _record_rows(raw):
        require("\\" not in path and "\x00" not in path, "ambiguous installed RECORD path")
        relative = rooted_path(installation_root, distribution.locate_file(path))
        require(relative not in expected, "duplicate installed RECORD path")
        require(not size or (size.isascii() and size.isdigit()), "invalid installed RECORD size")
        expected[relative] = (encoded_hash, int(size) if size else None)
        paths.append(relative)
    manifest = files_manifest(installation_root, paths)
    for item in manifest["files"]:
        encoded, size = expected[item["path"]]
        if encoded:
            require(encoded.startswith("sha256="), "unsupported installed RECORD hash")
            actual = base64.urlsafe_b64encode(bytes.fromhex(item["sha256"])).decode("ascii").rstrip("=")
            require(encoded == "sha256=" + actual, "installed bytes disagree with RECORD")
        require(size is None or item["size"] == size, "installed size disagrees with RECORD")
    return manifest


def discover_distributions(site_roots):
    """Inspect metadata only; never import entry points or package modules."""
    require(type(site_roots) is list and 0 < len(site_roots) <= 4, "explicit site roots required")
    for root in site_roots:
        checked_root(root)
    found = {}
    for dist in metadata.distributions(path=[str(path) for path in site_roots]):
        name = distribution_name(dist.metadata["Name"])
        require(name not in found, "ambiguous duplicate installed distribution")
        require(type(dist.version) is str and bool(dist.version), "missing distribution version")
        found[name] = dist
    return found


def bind_wheels(distributions, wheel_root, pins):
    """Match every installed dependency to an independently pinned retained wheel.

    Editable project installs are intentionally unsupported in this generic
    dependency lane: their source/path binding needs the dedicated project
    installation contract, rather than an invented wheel hash.
    """
    require(type(pins) is list and len(pins) == len(distributions), "incomplete resolved wheel set")
    result = {}
    for pin in pins:
        fields(pin, {"name", "version", "filename", "sha256", "size"})
        name = distribution_name(pin["name"])
        require(name not in result and name in distributions, "unexpected/duplicate wheel pin")
        require(distributions[name].version == pin["version"], "installed distribution version differs")
        filename = relative_path(pin["filename"])
        require("/" not in filename and filename.endswith(".whl"), "only retained wheel files supported")
        digest(pin["sha256"])
        integer(pin["size"], minimum=1, maximum=MAX_FILE_BYTES)
        actual = file_identity(wheel_root, filename)
        require(actual["sha256"] == pin["sha256"] and actual["size"] == pin["size"], "wheel bytes differ")
        result[name] = {key: pin[key] for key in ("filename", "sha256", "size")}
    require(set(result) == set(distributions), "installed dependencies differ from resolved wheel set")
    return result
