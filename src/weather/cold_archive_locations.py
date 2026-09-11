"""Read-only locations for explicitly archived snapshot inputs.

Original paths remain logical identities. Missing archived inputs raise a typed
RuntimeError instead of looking like an empty tape. Archive publication and
cache lifecycle belong to weather.operations.cold_archive_catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

from weather.schema_registry import schema_version

MARKER_DIRECTORY = ".cold_archive"
MAX_METADATA_BYTES = 2 * 1024**2
MAX_MEMBERS = 256
ARCHIVE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


class CatalogIntegrityError(RuntimeError):
    """An archive location or cached input cannot be trusted."""


class ArchivedInputRequired(RuntimeError):
    """A known archived input must be restored before the job can run."""

    def __init__(self, location):
        self.location = location
        self.source_path = location.source_path
        self.archive_id = location.entry["archive_id"]
        super().__init__(
            f"Archived input requires restore: {self.source_path}; archive {self.archive_id}. "
            "Use python -m weather.operations.cold_archive_catalog locate --source-path "
            f'"{self.source_path}" for the exact cloud objects and restore instructions.'
        )


def _require(condition, message):
    if not condition:
        raise CatalogIntegrityError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sealed(value):
    result = dict(value)
    result.pop("receipt_hash", None)
    result["receipt_hash"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def require_sha(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             "invalid archive SHA-256")


def relative_path(value):
    _require(isinstance(value, str) and bool(value) and "\\" not in value and ":" not in value,
             "invalid archive relative path")
    parts = value.split("/")
    _require(PurePosixPath(value).as_posix() == value and not value.startswith("/")
             and all(part and part not in {".", ".."} and not part.endswith((".", " "))
                     and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in part)
                     for part in parts), "unsafe archive relative path")
    return PurePosixPath(value)


def archive_id(value):
    _require(isinstance(value, str) and ARCHIVE_ID_RE.fullmatch(value) is not None
             and not value.endswith("."), "invalid archive ID")
    return value


def safe_path(path, *, directory=False):
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "absolute archive path required")
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        _require(not stat.S_ISLNK(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "archive links and reparse points are forbidden")
    _require(path.is_dir() if directory else path.is_file(), "invalid archive path type")
    if not directory:
        _require(path.stat().st_nlink == 1, "archive metadata and cache must not be hardlinked")
    return path


def file_identity(path):
    info = Path(path).stat()
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate archive JSON key")
        result[key] = value
    return result


def read_record(path, expected_sha256=None):
    try:
        path = safe_path(path)
        before = file_identity(path)
        _require(before["bytes"] <= MAX_METADATA_BYTES, "archive metadata byte bound exceeded")
        with path.open("rb") as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
        _require(len(raw) <= MAX_METADATA_BYTES and file_identity(path) == before,
                 "archive metadata changed during read")
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None:
            require_sha(expected_sha256)
            _require(digest == expected_sha256, "archive metadata hash mismatch")
        value = json.loads(raw, object_pairs_hook=_pairs)
        _require(isinstance(value, dict) and value == sealed(value), "archive metadata seal mismatch")
        return value, digest
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise CatalogIntegrityError("archive metadata is unreadable or invalid") from exc


@dataclass(frozen=True)
class Location:
    source_path: Path
    source_root: Path
    catalog_root: Path
    entry_path: Path
    entry_sha256: str
    entry: dict
    member: dict

    @property
    def local(self):
        return self.source_path.is_file()


def marker_path(path):
    path = Path(path)
    return path.parent / MARKER_DIRECTORY / (path.name + ".json")


def load_location(path):
    """Return durable identity/location metadata, whether or not raw data is local."""
    source = Path(path).absolute()
    marker = marker_path(source)
    if not marker.exists() and not marker.is_symlink():
        return None
    record, _ = read_record(marker)
    _require(set(record) == {"schema_version", "source_path", "archive_id", "entry_sha256",
                             "sha256", "size_bytes", "receipt_hash"},
             "archive marker fields differ")
    _require(record["schema_version"] == schema_version("cold_archive_location"),
             "unsupported archive location schema")
    relative = relative_path(record["source_path"])
    _require(len(relative.parts) == 3 and relative.parts[0] == "snapshots",
             "archive location must identify an immediate snapshot input")
    _require(len(source.parents) >= 3 and tuple(source.parts[-3:]) == relative.parts,
             "archive marker belongs to a different source")
    root = source.parents[2]
    catalog = root / "cold_archive" / "catalog"
    entry_path = catalog / "archives" / archive_id(record["archive_id"]) / "upload.json"
    entry, digest = read_record(entry_path, record["entry_sha256"])
    _require(entry.get("schema_version") == schema_version("cold_archive_catalog_entry")
             and entry.get("status") == "UPLOADED"
             and entry.get("archive_id") == record["archive_id"],
             "archive location entry mismatch")
    require_sha(record["sha256"])
    _require(type(record["size_bytes"]) is int and record["size_bytes"] >= 0,
             "archive source size invalid")
    files = entry.get("files")
    _require(isinstance(files, list) and 0 < len(files) <= MAX_MEMBERS
             and all(isinstance(row, dict) and isinstance(row.get("path"), str) for row in files),
             "archive member inventory invalid")
    names = [row["path"].casefold() for row in files]
    _require(len(names) == len(set(names)), "archive member inventory contains collisions")
    matches = [row for row in files if row["path"] == record["source_path"]]
    _require(len(matches) == 1 and matches[0].get("sha256") == record["sha256"]
             and matches[0].get("size_bytes") == record["size_bytes"],
             "archive source binding mismatch")
    return Location(source, root, catalog, entry_path, digest, entry, matches[0])


def cached_path(location):
    """Return a locally verified cache member, or None if no local copy remains."""
    pointer = location.entry_path.parent / "cache.json"
    if not pointer.exists():
        return None
    cache, _ = read_record(pointer)
    _require(cache.get("schema_version") == schema_version("cold_archive_cache")
             and cache.get("status") == "PASS"
             and cache.get("entry_sha256") == location.entry_sha256,
             "archive cache binding mismatch")
    members = cache.get("files")
    _require(isinstance(members, list) and len(members) == len(location.entry["files"]),
             "archive cache inventory mismatch")
    matches = [row for row in members if isinstance(row, dict)
               and row.get("source_path") == location.member["path"]]
    _require(len(matches) == 1, "archive cache member missing or duplicated")
    member = matches[0]
    relative = relative_path(member.get("cache_path"))
    expected_prefix = ("cold_archive", "restore_cache", archive_id(cache.get("cache_id")), "members")
    _require(relative.parts[:4] == expected_prefix
             and relative.parts[4:] == relative_path(location.member["path"]).parts,
             "archive cache path escaped its managed directory")
    path = location.source_root.joinpath(*relative.parts)
    if not path.exists():
        return None
    try:
        safe_path(path)
        identity = file_identity(path)
        _require(identity == member.get("identity")
                 and identity["bytes"] == location.member["size_bytes"]
                 and member.get("sha256") == location.member["sha256"],
                 "archive cache identity mismatch")
        # Windows st_ctime is creation time; same-size rewrites can retain
        # both creation and restored mtime. Metadata alone cannot cache a hash.
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024**2):
                digest.update(block)
        _require(file_identity(path) == identity and digest.hexdigest() == member["sha256"],
                 "archive cache content mismatch")
        return path
    except OSError as exc:
        raise CatalogIntegrityError("archive cache became unavailable during verification") from exc


def resolve_local_path(path):
    """Resolve an original or verified cache file; never hide a known archive."""
    path = Path(path)
    if path.is_file():
        return path
    location = load_location(path)
    if location is None:
        return path
    cached = cached_path(location)
    if cached is None:
        raise ArchivedInputRequired(location)
    return cached


def registered_sources(folder, pattern="*"):
    """Discover logical filenames retained in markers, including off-site inputs."""
    folder = Path(folder)
    markers = folder / MARKER_DIRECTORY
    if not markers.exists():
        return []
    safe_path(markers.absolute(), directory=True)
    result = []
    for index, marker in enumerate(sorted(markers.iterdir())):
        _require(index < MAX_MEMBERS, "market-day archive marker bound exceeded")
        _require(marker.name.endswith(".json"), "unexpected archive marker")
        source = folder / marker.name[:-5]
        if fnmatch.fnmatchcase(source.name, pattern):
            _require(load_location(source) is not None, "archive marker disappeared")
            result.append(source)
    return result


def archived_inputs(folder):
    """List off-site logical inputs without reading payloads or warming caches."""
    result = []
    for source in registered_sources(folder):
        if source.is_file():
            continue
        location = load_location(source)
        _require(location is not None, "archive location disappeared")
        result.append({"path": source.name, "source_path": location.member["path"],
                       "archive_id": location.entry["archive_id"],
                       "entry_sha256": location.entry_sha256})
    return result


def require_local_inputs(paths):
    """Resolve the complete explicit job input list before doing any analysis."""
    return [resolve_local_path(path) for path in paths]
