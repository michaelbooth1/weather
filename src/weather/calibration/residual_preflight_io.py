"""Bounded byte and environment bindings for the frozen residual preflight."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import sysconfig

MAX_SMALL_BYTES = 1024 * 1024
MAX_FEATURE_BYTES = 16 * 1024 * 1024
MAX_DEPENDENCY_BYTES = 1024 * 1024 * 1024
PACKAGES = {"numpy": "numpy", "scipy": "scipy", "pandas": "pandas", "scikit_learn": "sklearn"}


class PreflightError(ValueError):
    """Evidence is absent, changed, out of scope, or unsupported."""


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_digest(value) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def json_bytes(body: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PreflightError("json:duplicate_key")
            result[key] = value
        return result

    def invalid(_):
        raise PreflightError("json:nonfinite")

    return json.loads(body.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid)


def regular_path(value) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise PreflightError("path:absolute_required")
    for member in (path, *path.parents):
        metadata = member.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise PreflightError("path:redirected")
    if not path.is_file():
        raise PreflightError("path:regular_file_required")
    return path


def verify_blob(body: bytes, record: dict) -> bytes:
    expected = record.get("sha256")
    size = record.get("bytes")
    if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
            or type(size) is not int or size < 0):
        raise PreflightError("binding:invalid")
    if len(body) != size or digest(body) != expected:
        raise PreflightError("binding:bytes_or_sha256_differ")
    return body


def read_bound(record: dict, *, maximum=MAX_SMALL_BYTES) -> bytes:
    if type(record.get("bytes")) is not int or not 0 <= record["bytes"] <= maximum:
        raise PreflightError("binding:size_bound")
    path = regular_path(record["path"])
    before = path.stat()
    if before.st_size != record["bytes"]:
        raise PreflightError("binding:size_changed")
    with path.open("rb") as handle:
        body = handle.read(maximum + 1)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PreflightError("binding:changed_during_read")
    return verify_blob(body, record)


def mutation_refused(body: bytes, record: dict) -> bool:
    if not body:
        raise PreflightError("control:empty_source")
    changed = bytes([body[0] ^ 1]) + body[1:]
    try:
        verify_blob(changed, record)
    except PreflightError:
        return True
    raise PreflightError("control:substitution_accepted")


def _dependency_file(path, expected, size):
    path = regular_path(path)
    before = path.stat()
    if before.st_size != size or not 0 <= size <= 128 * 1024 * 1024:
        raise PreflightError("dependency:file_bound")
    actual = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            read += len(block)
            if read > size:
                raise PreflightError("dependency:grew")
            actual.update(block)
    after = path.stat()
    if (read != size or actual.digest() != expected
            or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
        raise PreflightError("dependency:content_changed")
    return actual.hexdigest()


def verify_dependencies(records):
    """Verify recorded runtime files before scientific-package imports.

    This binds the current environment, not an unrecorded training environment.
    RECORD-omitted bytecode caches and transitive packages are not certified.
    """
    if not isinstance(records, list) or len(records) != 8:
        raise PreflightError("dependency:metadata_scope")
    root = Path(sysconfig.get_path("purelib")).resolve()
    grouped = {}
    for record in records:
        package = record.get("package")
        path = regular_path(record["path"])
        if package not in PACKAGES or path.name not in {"METADATA", "RECORD"}:
            raise PreflightError("dependency:unexpected_metadata")
        if path.parent.parent.resolve() != root or not path.parent.name.startswith(package + "-"):
            raise PreflightError("dependency:wrong_installation")
        group = grouped.setdefault(package, {})
        if path.name in group:
            raise PreflightError("dependency:duplicate_metadata")
        group[path.name] = (record, read_bound(record))
    if set(grouped) != set(PACKAGES) or any(set(group) != {"METADATA", "RECORD"} for group in grouped.values()):
        raise PreflightError("dependency:incomplete_metadata")
    results, total_bytes, total_files = [], 0, 0
    seen = set()
    for package, group in sorted(grouped.items()):
        installed_metadata = group["METADATA"][1].decode("utf-8")
        versions = re.findall(r"^Version: (.+)$", installed_metadata, re.MULTILINE)
        if len(versions) != 1:
            raise PreflightError("dependency:version_missing")
        bindings = []
        for row in csv.reader(io.StringIO(group["RECORD"][1].decode("utf-8"))):
            if len(row) != 3:
                raise PreflightError("dependency:record_shape")
            relative, declared_hash, raw_size = row
            path = Path(relative)
            if path.suffix.lower() not in {".py", ".pyd", ".dll"}:
                continue
            if path.is_absolute() or ".." in path.parts:
                raise PreflightError("dependency:runtime_path_escape")
            if not path.parts or path.parts[0] not in {PACKAGES[package], package + ".libs", PACKAGES[package] + ".libs"}:
                raise PreflightError("dependency:unexpected_runtime_root")
            if relative in seen or not re.fullmatch(r"[0-9]+", raw_size):
                raise PreflightError("dependency:duplicate_or_missing_size")
            seen.add(relative)
            size = int(raw_size)
            total_bytes += size
            total_files += 1
            if total_bytes > MAX_DEPENDENCY_BYTES or total_files > 12000:
                raise PreflightError("dependency:total_bound")
            if not declared_hash.startswith("sha256="):
                raise PreflightError("dependency:sha256_required")
            encoded = declared_hash.removeprefix("sha256=")
            try:
                expected = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            except ValueError as exc:
                raise PreflightError("dependency:hash_encoding") from exc
            if len(expected) != 32:
                raise PreflightError("dependency:hash_length")
            sha = _dependency_file(root / path, expected, size)
            bindings.append({"path": relative, "bytes": size, "sha256": sha})
        if not bindings:
            raise PreflightError("dependency:no_runtime_files")
        results.append({
            "package": package, "version": versions[0],
            "metadata": group["METADATA"][0], "record": group["RECORD"][0],
            "runtime_files": len(bindings), "runtime_bytes": sum(item["bytes"] for item in bindings),
            "runtime_bindings_sha256": canonical_digest(bindings),
        })
    return {
        "packages": results, "runtime_files": total_files, "runtime_bytes": total_bytes,
        "scope": "Pinned current METADATA/RECORD and recorded .py/.pyd/.dll files, before imports.",
        "limits": "Not original-training environment proof; omitted caches, transitive packages and OS runtime are not certified.",
    }


def write_new_json(path, value):
    body = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(body) > 8 * MAX_SMALL_BYTES:
        raise PreflightError("output:byte_bound")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(body)
    return {"path": str(path), "bytes": len(body), "sha256": digest(body)}
