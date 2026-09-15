"""Bounded data-only artifact extraction into a fresh, spent-on-failure root."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import zipfile

from .records import checked_root, distinct_paths, open_record, relative_path, require


MAX_ARCHIVE_BYTES = 512 * 1024**2
MAX_EXPANDED_BYTES = 2 * 1024**3
MAX_MEMBER_BYTES = 128 * 1024**2
MAX_MEMBERS = 16_384
DATA_SUFFIXES = {".json", ".jsonl", ".xml", ".log", ".txt", ".sigstore"}


def inspect_archive(handle):
    archive = zipfile.ZipFile(handle, "r")
    try:
        members = archive.infolist()
        require(0 < len(members) <= MAX_MEMBERS, "artifact archive member count exceeds bound")
        total, names = 0, []
        for member in members:
            require(not member.is_dir(), "artifact archive must contain files only")
            name = relative_path(member.filename)
            require(Path(name).suffix in DATA_SUFFIXES, "artifact member is not an approved data type")
            require(member.orig_filename == name, "truncated or ambiguous archive name")
            names.append(name)
            require(member.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} and
                    not member.flag_bits & 1, "unsupported/encrypted archive member")
            mode = member.external_attr >> 16
            require(stat.S_IFMT(mode) in {0, stat.S_IFREG} and not mode & 0o111,
                    "archive links or executable members are forbidden")
            require(0 < member.file_size <= MAX_MEMBER_BYTES and member.compress_size > 0,
                    "artifact member size exceeds bound")
            require(member.file_size <= max(1024 * 1024, member.compress_size * 200),
                    "artifact expansion ratio exceeds bound")
            total += member.file_size
            require(total <= MAX_EXPANDED_BYTES, "expanded artifact exceeds bound")
        distinct_paths(names)
        # No file may also name an ancestor directory, including by case alias.
        folded = {name.casefold() for name in names}
        for name in names:
            parts = name.split("/")
            require(not any("/".join(parts[:index]).casefold() in folded for index in range(1, len(parts))),
                    "artifact file/directory conflict")
        return archive, members
    except BaseException:
        archive.close()
        raise


def extract(root, archive_ref, destination):
    """Input SHA is independently authenticated by the importer before use.

    This function still hashes the actual input itself; the returned manifest
    is diagnostic data only. A separate sealed import receipt grants usability.
    Failure leaves the new destination in place and cannot be retried over it.
    """
    from .records import digest, fields, integer

    fields(archive_ref, {"path", "sha256", "size"})
    digest(archive_ref["sha256"])
    integer(archive_ref["size"], minimum=1, maximum=MAX_ARCHIVE_BYTES)
    destination = Path(destination)
    require(destination.is_absolute(), "absolute artifact destination required")
    checked_root(destination.parent)
    require(not destination.exists(), "artifact destination was already spent")
    with open_record(root, archive_ref["path"]) as handle:
        hasher, count = hashlib.sha256(), 0
        while block := handle.read(min(1024 * 1024, archive_ref["size"] + 1 - count)):
            count += len(block)
            require(count <= archive_ref["size"], "artifact archive grew")
            hasher.update(block)
        require(count == archive_ref["size"] and hasher.hexdigest() == archive_ref["sha256"],
                "artifact archive digest differs")
        handle.seek(0)
        archive, members = inspect_archive(handle)
        try:
            destination.mkdir(mode=0o700)
            identities = []
            for member in members:
                target = destination.joinpath(*member.filename.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                checked_root(target.parent)
                hasher, count = hashlib.sha256(), 0
                # The namespace is owned by this operation; files are create-only.
                with archive.open(member, "r") as source, target.open("xb") as output:
                    while block := source.read(min(1024 * 1024, member.file_size + 1 - count)):
                        count += len(block)
                        require(count <= member.file_size, "expanded member grew")
                        output.write(block)
                        hasher.update(block)
                    require(count == member.file_size, "truncated archive member")
                    output.flush()
                    os.fsync(output.fileno())
                identity = {"path": member.filename, "sha256": hasher.hexdigest(), "size": count}
                # Shared reader rejects links, replacement and unstable bytes.
                reread = hashlib.sha256()
                with open_record(destination, member.filename) as sealed:
                    while block := sealed.read(1024 * 1024):
                        reread.update(block)
                require(reread.hexdigest() == identity["sha256"], "extracted artifact changed")
                identities.append(identity)
            return identities
        finally:
            archive.close()
