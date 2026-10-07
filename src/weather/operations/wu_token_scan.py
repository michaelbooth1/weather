"""Read-only scan for persisted Weather Underground page access tokens.

Owner decision OD15 (2026-10-06) allows the free WU history access that uses the
token scraped from the public history page, but the token must never be
persisted in logs, tapes, error rows, commits or anything pushed. This CLI walks
the given roots and reports *where* a token-shaped value appears, never *what*
it is: the output carries only file paths, per-pattern match counts and the
byte offset of the first match.

Exit codes: 0 clean (every eligible file scanned), 1 at least one finding,
2 error or incomplete scan (a cap was hit, a root is missing or empty, a file
could not be read, a symlink or junction was skipped, a non-link reparse point
such as a OneDrive placeholder was left unread, an entry was neither a file nor a
directory, content could not be decoded, or ``--token-from-env`` names an
unusable variable), 3 the scan found nothing but ``--json-out`` could not be
written (the report is still printed; a FOUND scan exits 1 even then, so a
finding is never masked). A capped scan is never reported clean. Invariant (N3): CLEAN means every regular file under the
request was read, except files reachable only through a link that ``--links
ignore`` explicitly waived; ``unread_reasons`` in the report names every reason
a scan is not CLEAN.

Links (``--links``): by default (``incomplete``) a symlink, junction or reparse
point met inside a root is not followed, its path is listed in
``skipped_link_paths`` and the scan is INCOMPLETE, because the tree behind it
was not read. ``follow-within-root`` follows a link only when its resolved
target lies inside the resolved requested root (cycle-safe; a link out of the
root stays skipped and incomplete). ``ignore`` still lists skipped links but
lets the scan be CLEAN without them. No mode ever follows a link out of the
requested root.

A link here is a name-surrogate reparse point (symlink or junction). Any other
reparse point -- a OneDrive cloud placeholder, a deduplicated file, an app
execution alias, or one whose tag cannot be read -- holds content in place, so
outside ``follow-within-root`` (which reads it in place when it resolves inside
the root) it is listed in ``skipped_reparse_paths`` and makes the scan
INCOMPLETE under every policy, ``ignore`` included.

An explicit ``files=`` list (used by the repository ratchet) is handled exactly
like ``roots``: a directory or junction named in it is walked as named, never
silently dropped.

Encoded content (Defender MF1): every file is scanned as raw bytes -- and every
chunk holding a NUL byte also with its NULs removed, so ASCII text in UTF-16
anywhere in a file is matched (label ``nul-stripped``; a PowerShell 5.1 ``>>``
append to a UTF-8 log is UTF-16LE without a BOM) -- then its
first bytes are sniffed and any recognised layer is decoded as a stream and
scanned too, recursively up to ``MAX_DECODE_DEPTH`` layers: gzip, bzip2, xz/lzma,
zip members, UTF-16/UTF-32 (BOM, or UTF-16 without a BOM by its NUL pattern) and
whole-file base64. Content that is recognised but cannot be decoded -- zstd, 7z,
rar, lz4, Parquet (its pages may be compressed), an encrypted or unsupported zip
member, a corrupt or truncated stream, base64 that stops being base64, or a layer
past ``--max-decoded-bytes`` -- is listed in ``undecoded`` and makes the scan
INCOMPLETE. Matches made before a layer broke are kept, and any decoder failure
is recorded against its file only: it never aborts the scan or hides a FOUND. Findings name the layer (``gzip>utf-16-le``, ``zip[2]``), never a zip
member name. Not covered (follow-ups): base64 or compressed runs embedded inside
an otherwise plain file, raw zlib streams, and a zip with data before its header.

Directories skipped by name (``--exclude-dir``) are listed in
``skipped_excluded``; skipping them does not make the scan incomplete.

The walk is bounded by ``--max-files``, ``--max-file-bytes``,
``--max-total-bytes`` and, per file across its decoded layers,
``--max-decoded-bytes``. Files and decoded layers are streamed in chunks, so
memory stays flat however large a tape is.
"""

from __future__ import annotations

import argparse
import base64
import bz2
import codecs
import gzip
import json
import lzma
import os
import re
import stat
import sys
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "wu_token_scan_v1"

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_ERROR = 2
# The scan ran (its status is printed) but the --json-out report could not be written.
EXIT_OUTPUT_ERROR = 3

DEFAULT_MAX_FILES = 500_000
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
# Decoded bytes read from one file across all its layers (decompression-bomb bound).
DEFAULT_MAX_DECODED_BYTES = 2 * 1024 * 1024 * 1024
MAX_DECODE_DEPTH = 4
# Bytes of a file or layer inspected to recognise an encoding or container.
SNIFF_BYTES = 4096
# Read size for decoded layers: small enough that a stream which breaks part-way
# (truncated gzip) has already surfaced, and been scanned, most of what it decoded.
DECODED_READ_BYTES = 256 * 1024
# Report label for matches found only after removing NUL bytes (UTF-16 text).
NUL_STRIPPED_LAYER = "nul-stripped"
DEFAULT_EXCLUDED_DIR_NAMES = (".git", "__pycache__", "venv", ".venv", "node_modules")
LINKS_INCOMPLETE = "incomplete"
LINKS_IGNORE = "ignore"
LINKS_FOLLOW_WITHIN_ROOT = "follow-within-root"
LINK_POLICIES = (LINKS_INCOMPLETE, LINKS_IGNORE, LINKS_FOLLOW_WITHIN_ROOT)
# The report lists at most this many skipped link paths; the count is always exact.
MAX_REPORTED_LINK_PATHS = 10_000
CHUNK_BYTES = 1024 * 1024
# Longest match any pattern can produce; a match straddling two chunks is always
# whole inside the overlap.
OVERLAP_BYTES = 4096
MIN_ENV_TOKEN_CHARS = 8
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
# Reparse tags with this bit (IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT for
# junctions) redirect to another path; every other tag (cloud placeholders, dedup,
# app execution aliases) holds data in place.
_IO_REPARSE_TAG_NAME_SURROGATE = 0x20000000
_KIND_LINK = "link"
_KIND_REPARSE = "reparse"

# A token value: WU page keys are 32 hex characters; anything alphanumeric of 16+
# characters is treated as token-shaped so ``api_key=None`` or ``<redacted>`` never match.
_VALUE = rb"[A-Za-z0-9]{16,128}"
# A quote, raw or escaped: backslash-escaped, HTML/Angular entities, URL-encoded once
# (``%22``) or twice (``%2522``), or JSON-escaped (``"``).
_QUOTE = rb"(?:\\?[\"']|&quot;|&q;|&#34;|&#x22;|%(?:25)?2[27]|\\u002[27])"
# Key/value separators in the same encodings.
_EQUALS = rb"(?:=|%(?:25)?3[Dd]|&#61;|&#x3[Dd];|\\u003[Dd])"
_COLON = rb"(?::|%(?:25)?3[Aa]|&#58;|&#x3[Aa];|\\u003[Aa])"
# The key name: apiKey, api_key, API_KEY and header spellings such as X-Api-Key.
_KEY = rb"api[_-]?key"
# Start of a key name: a word boundary, or straight after an escape (``%22``,
# ``%2522``, ``"``) whose last character would otherwise defeat ``\b``.
_KEY_START = rb"(?:\b|(?<=%[0-9A-Fa-f]{2})|(?<=%25[0-9A-Fa-f]{2})|(?<=\\u00[0-9A-Fa-f]{2}))"
# A token may follow an escape (``%22<token>``, ``%253A<token>``, ``"<token>``)
# whose last character is a hex digit, so "not preceded by hex" alone would miss it.
_HEX_START = rb"(?:(?<![0-9a-f])|(?<=%[0-9a-f]{2})|(?<=%25[0-9a-f]{2})|(?<=\\u00[0-9a-f]{2}))"

PATTERNS = {
    # apiKey=<value> in a URL, a log line or an error row (also URL-encoded ``=``).
    "apikey_query_param": re.compile(rb"(?i)" + _KEY_START + _KEY + _EQUALS + _VALUE),
    # apiKey:<value> in key style: JSON "apiKey":"<value>" (also a JSON string nested
    # in JSON), a Python dict repr 'apiKey': '<value>', or a JS/log apiKey: <value>.
    "apikey_colon_field": re.compile(
        rb"(?i)" + _KEY_START + _KEY + _QUOTE + rb"?\s*" + _COLON + rb"\s*" + _QUOTE + rb"?" + _VALUE
    ),
    # The WU page runtime global: "API_KEY":"<value>" (raw, HTML-escaped or Angular
    # &q; transfer state) or a JS ``API_KEY = '<value>'`` assignment.
    "wu_page_api_key_block": re.compile(
        rb"\bAPI_KEY" + _QUOTE + rb"?\s*[:=]\s*" + _QUOTE + rb"?" + _VALUE
    ),
    # A bare 32-hex string within 64 bytes after an apiKey/API_KEY name.
    "hex32_near_apikey": re.compile(
        rb"(?is)" + _KEY + rb".{0,64}?" + _HEX_START + rb"[0-9a-f]{32}(?![0-9a-f])"
    ),
}
EXACT_TOKEN_PATTERN = "exact_env_token"


@dataclass
class ScanResult:
    findings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped_oversize: list = field(default_factory=list)
    skipped_links: int = 0
    skipped_link_paths: list = field(default_factory=list)
    followed_links: int = 0
    skipped_reparse_points: int = 0
    skipped_reparse_paths: list = field(default_factory=list)
    link_policy: str = LINKS_INCOMPLETE
    files_scanned: int = 0
    bytes_scanned: int = 0
    decoded_bytes_scanned: int = 0
    undecoded: list = field(default_factory=list)
    skipped_excluded: list = field(default_factory=list)
    skipped_excluded_count: int = 0
    truncated_reason: str | None = None


def _reparse_info(info, path):
    """Return ``(file_attributes, reparse_tag)`` for a non-followed stat of ``path``."""
    attributes = getattr(info, "st_file_attributes", 0) or 0
    tag = getattr(info, "st_reparse_tag", 0) or 0
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT and not tag:
        tag = getattr(os.lstat(path), "st_reparse_tag", 0) or 0
    return attributes, tag


def _entry_kind(entry: os.DirEntry):
    """``"link"`` for a symlink or junction, ``"reparse"`` for any other reparse point, else None.

    An entry whose attributes cannot be read is ``"reparse"``: it was not read, and
    unlike a link no policy may waive it.
    """
    try:
        if entry.is_symlink():
            return _KIND_LINK
        is_junction = getattr(entry, "is_junction", None)
        if is_junction is not None and is_junction():
            return _KIND_LINK
        attributes, tag = _reparse_info(entry.stat(follow_symlinks=False), entry.path)
    except OSError:
        return _KIND_REPARSE
    if not attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        return None
    return _KIND_LINK if tag & _IO_REPARSE_TAG_NAME_SURROGATE else _KIND_REPARSE


def _record_skipped_link(result, path):
    if result is None:
        return
    result.skipped_links += 1
    if len(result.skipped_link_paths) < MAX_REPORTED_LINK_PATHS:
        result.skipped_link_paths.append(str(path))


def _record_skipped_reparse(result, path):
    if result is None:
        return
    result.skipped_reparse_points += 1
    if len(result.skipped_reparse_paths) < MAX_REPORTED_LINK_PATHS:
        result.skipped_reparse_paths.append(str(path))


def _record_unread(result, path, reason):
    if result is not None:
        result.errors.append({"path": str(path), "error": reason})


def _record_excluded(result, path):
    if result is None:
        return
    result.skipped_excluded_count += 1
    if len(result.skipped_excluded) < MAX_REPORTED_LINK_PATHS:
        result.skipped_excluded.append(str(path))


def _real_key(path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(root_key: str, target_key: str) -> bool:
    try:
        return os.path.commonpath([root_key, target_key]) == root_key
    except ValueError:  # different drives
        return False


def iter_files(
    roots,
    excluded_dir_names=DEFAULT_EXCLUDED_DIR_NAMES,
    result=None,
    *,
    link_policy=LINKS_INCOMPLETE,
):
    """Yield ``(path, size)`` for regular files under ``roots``.

    Links met inside a root are skipped and recorded on ``result``; with
    ``link_policy="follow-within-root"`` a link whose resolved target lies inside
    the resolved root is followed instead (each real directory is walked once).
    A link is never followed out of its requested root. Non-link reparse points
    are recorded as unread (``skipped_reparse_paths``) unless followed in place,
    and an entry that is neither a file nor a directory is recorded as an error:
    nothing below a root is ever dropped without a trace on ``result``.
    """
    if link_policy not in LINK_POLICIES:
        raise ValueError(f"unknown link policy: {link_policy!r}")
    follow = link_policy == LINKS_FOLLOW_WITHIN_ROOT
    excluded = {name.casefold() for name in excluded_dir_names}
    for root in roots:
        if isinstance(root, str) and not root.strip():
            # Path("") is ".", so an empty argument would silently scan the cwd.
            _record_unread(result, root, "EmptyPath")
            continue
        root = Path(root)
        try:
            root_info = os.lstat(root)
        except OSError as exc:
            if result is not None:
                result.errors.append({"path": str(root), "error": type(exc).__name__})
            continue
        if stat.S_ISLNK(root_info.st_mode):
            _record_skipped_link(result, root)
            continue
        if stat.S_ISREG(root_info.st_mode):
            yield root, root_info.st_size
            continue
        # A requested root is read as named, even if it is itself a junction; its
        # resolved path is the boundary no followed link may leave.
        root_key = _real_key(root) if follow else ""
        visited = {root_key} if follow else set()
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    children = sorted(entries, key=lambda item: item.name)
            except OSError as exc:
                if result is not None:
                    result.errors.append({"path": str(directory), "error": type(exc).__name__})
                continue
            subdirectories = []
            for entry in children:
                kind = _entry_kind(entry)
                if kind is not None:
                    if not follow:
                        if kind == _KIND_LINK:
                            _record_skipped_link(result, entry.path)
                        else:
                            _record_skipped_reparse(result, entry.path)
                        continue
                    try:
                        target_key = _real_key(entry.path)
                        target_info = os.stat(entry.path)
                    except (OSError, ValueError):
                        _record_skipped_link(result, entry.path)
                        continue
                    if not _inside(root_key, target_key):
                        _record_skipped_link(result, entry.path)
                        continue
                    is_dir = stat.S_ISDIR(target_info.st_mode)
                    if is_dir:
                        if entry.name.casefold() in excluded:
                            _record_excluded(result, entry.path)
                            continue
                        if target_key in visited:
                            continue
                        visited.add(target_key)
                    elif not stat.S_ISREG(target_info.st_mode):
                        _record_skipped_link(result, entry.path)
                        continue
                    if result is not None:
                        result.followed_links += 1
                    if is_dir:
                        subdirectories.append(Path(entry.path))
                    else:
                        yield Path(entry.path), target_info.st_size
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.casefold() in excluded:
                            _record_excluded(result, entry.path)
                        else:
                            if follow:
                                key = _real_key(entry.path)
                                if key in visited:
                                    continue
                                visited.add(key)
                            subdirectories.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        _record_unread(result, entry.path, "NotARegularFile")
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError as exc:
                    if result is not None:
                        result.errors.append({"path": entry.path, "error": type(exc).__name__})
                    continue
                yield Path(entry.path), size
            stack.extend(reversed(subdirectories))


def _match_into(buffer, patterns, hits, base, limit, eof):
    """Count matches in ``buffer`` that start before ``limit`` (all of them at EOF)."""
    lowered = buffer.lower()
    key_named = b"apikey" in lowered or b"api_key" in lowered or b"api-key" in lowered
    for name, pattern in patterns.items():
        # Every built-in pattern is anchored on an apiKey/API_KEY name; a chunk
        # without one cannot match, so skip the (slow, case-insensitive) regex.
        if name in PATTERNS and not key_named:
            continue
        for match in pattern.finditer(buffer):
            if not eof and match.start() >= limit:
                continue  # counted with the next chunk, which carries this overlap
            count, first = hits.get(name, (0, None))
            hits[name] = (count + 1, base + match.start() if first is None else first)


def _scan_stream(reader, patterns, size=None, hits=None, stripped_hits=None):
    """Return ``(hits, head, stripped_hits)`` for a binary stream, scanned in chunks.

    ``hits`` maps pattern -> (count, first_offset). ``head`` is the first
    ``SNIFF_BYTES`` bytes, used to recognise an inner layer. ``size`` (a regular
    file's length) sizes the reads; a decoded stream is read in
    ``DECODED_READ_BYTES`` pieces so a stream that breaks part-way still yields
    what it decoded. ``hits`` and ``stripped_hits`` may be passed in and are
    filled in place, so a caller keeps partial findings when the reader raises.

    MF1-R: any chunk holding a NUL byte is also scanned with its NULs removed
    (``stripped_hits``). ASCII text in UTF-16LE/BE -- with or without a BOM, at any
    offset, e.g. a PowerShell 5.1 ``>>`` append to a UTF-8 log -- then matches.
    The overlap carry is shared, so a match straddling chunks is counted once.
    """
    hits = {} if hits is None else hits
    stripped_hits = {} if stripped_hits is None else stripped_hits
    head = b""
    base = 0
    carry = b""
    remaining = size
    while True:
        if remaining is None:
            chunk = reader.read(DECODED_READ_BYTES)
        else:
            # Size the read to the file: a full-chunk read() allocates CHUNK_BYTES per
            # call, which dominates the cost of scanning many small files on Windows.
            # A file that grows while it is read continues in 64 KiB reads.
            chunk = reader.read(min(CHUNK_BYTES, remaining) if remaining else 64 * 1024)
            remaining = max(0, remaining - len(chunk))
        eof = not chunk
        if len(head) < SNIFF_BYTES and chunk:
            head += chunk[: SNIFF_BYTES - len(head)]
        buffer = carry + chunk
        if not buffer:
            break
        limit = len(buffer) if eof else max(0, len(buffer) - OVERLAP_BYTES)
        _match_into(buffer, patterns, hits, base, limit, eof)
        if b"\x00" in buffer:
            stripped = buffer.replace(b"\x00", b"")
            tail = buffer[limit:]
            stripped_limit = len(stripped) - (len(tail) - tail.count(0))
            _match_into(stripped, patterns, stripped_hits, base, stripped_limit, eof)
        if eof:
            break
        carry = buffer[limit:]
        base += limit
    return hits, head, stripped_hits


def _scan_raw(path, patterns):
    with open(path, "rb") as handle:
        return _scan_stream(handle, patterns, size=os.fstat(handle.fileno()).st_size)


def scan_file(path, patterns):
    """Return ``{pattern: (count, first_offset)}`` for one file's raw bytes, streaming in chunks."""
    return _scan_raw(path, patterns)[0]


# --- decoded layers (Defender MF1) -------------------------------------------------------

_UNDECODABLE_MAGIC = (
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
    (b"\x04\x22\x4d\x18", "lz4"),
    (b"PAR1", "parquet"),
    (b"PARE", "parquet"),  # encrypted footer
)
_BASE64_STD = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n")
_BASE64_URL = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=\r\n")
_MIN_BASE64_CHARS = 64


class _DecodedTooLarge(Exception):
    pass


class _UndecodableLayer(Exception):
    pass


def _utf16_by_nuls(head):
    """``"utf-16-le"``/``"utf-16-be"`` when ``head`` looks like BOM-less UTF-16 text, else None."""
    usable = len(head) // 2 * 2
    if usable < 16:
        return None
    pairs = usable // 2
    even_nul = head[0:usable:2].count(0)
    odd_nul = head[1:usable:2].count(0)
    if odd_nul >= 0.6 * pairs and even_nul <= 0.1 * pairs:
        return "utf-16-le"
    if even_nul >= 0.6 * pairs and odd_nul <= 0.1 * pairs:
        return "utf-16-be"
    return None


def _looks_base64(head):
    body = head.replace(b"\r", b"").replace(b"\n", b"")
    if len(body) < _MIN_BASE64_CHARS:
        return None
    letters = set(body)
    # Mixed case is required: a hex digest list is valid base64 alphabet but is text.
    if not (letters & set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ") and letters & set(b"abcdefghijklmnopqrstuvwxyz")):
        return None
    if set(head) <= _BASE64_STD:
        return "base64"
    if set(head) <= _BASE64_URL:
        return "base64url"
    return None


def _sniff(head):
    """Name the layer ``head`` starts, ``"!<name>"`` for one that cannot be decoded, or None."""
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if head.startswith(b"BZh") and head[4:10] in (b"1AY&SY", b"\x17rE8P\x90"):
        return "bzip2"
    if head.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    for magic, name in _UNDECODABLE_MAGIC:
        if head.startswith(magic):
            return "!" + name
    if head.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return "utf-32"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    return _utf16_by_nuls(head) or _looks_base64(head)


class _Budget:
    def __init__(self, remaining):
        self.remaining = remaining


class _CappedReader:
    """Count decoded bytes against the per-file budget; raise once it is spent."""

    def __init__(self, inner, budget):
        self.inner = inner
        self.budget = budget

    def read(self, size=-1):
        data = self.inner.read(size)
        self.budget.remaining -= len(data)
        if self.budget.remaining < 0:
            raise _DecodedTooLarge()
        return data


class _ChunkReader:
    """A read(size)-honouring stream over ``_next_chunk()`` (gzip and zip need exact reads)."""

    done = False

    def __init__(self):
        self._buffer = b""
        self._offset = 0

    def _next_chunk(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def read(self, size=-1):
        if size is None or size < 0:
            size = CHUNK_BYTES
        # Refill only when the buffer is spent, so small reads (gzip asks for 8 KiB)
        # slice a single chunk instead of re-copying it.
        while self._offset >= len(self._buffer) and not self.done:
            self._buffer, self._offset = self._next_chunk(), 0
        data = self._buffer[self._offset : self._offset + size]
        self._offset += len(data)
        return data


class _TranscodeReader(_ChunkReader):
    """Present a UTF-16/UTF-32 stream as UTF-8 bytes (undecodable units become U+FFFD)."""

    def __init__(self, raw, encoding):
        super().__init__()
        self.raw = raw
        self.decoder = codecs.getincrementaldecoder(encoding)(errors="replace")

    def _next_chunk(self):
        chunk = self.raw.read(CHUNK_BYTES)
        self.done = not chunk
        return self.decoder.decode(chunk, final=self.done).encode("utf-8")


class _Base64Reader(_ChunkReader):
    """Decode a whole-file base64 stream (line breaks allowed) chunk by chunk."""

    def __init__(self, raw, urlsafe):
        super().__init__()
        self.raw = raw
        self.urlsafe = urlsafe
        self.pending = b""

    def _decode(self, data):
        if self.urlsafe:
            data = data.translate(bytes.maketrans(b"-_", b"+/"))
        return base64.b64decode(data, validate=True)

    def _next_chunk(self):
        while not self.done:
            chunk = self.raw.read(CHUNK_BYTES)
            self.done = not chunk
            self.pending += chunk.replace(b"\r", b"").replace(b"\n", b"")
            if self.done:
                tail, self.pending = self.pending, b""
                if len(tail) % 4 == 1:
                    raise _UndecodableLayer("truncated base64")
                return self._decode(tail + b"=" * (-len(tail) % 4)) if tail else b""
            whole = len(self.pending) // 4 * 4
            if whole:
                data, self.pending = self.pending[:whole], self.pending[whole:]
                decoded = self._decode(data)
                if decoded:
                    return decoded
        return b""


@contextmanager
def _open_inner(open_parent, kind):
    with open_parent() as raw:
        if kind == "gzip":
            with gzip.GzipFile(fileobj=raw, mode="rb") as inner:
                yield inner
        elif kind == "bzip2":
            with bz2.BZ2File(raw, mode="rb") as inner:
                yield inner
        elif kind == "xz":
            with lzma.LZMAFile(raw, mode="rb") as inner:
                yield inner
        elif kind in ("base64", "base64url"):
            yield _Base64Reader(raw, urlsafe=kind == "base64url")
        else:
            yield _TranscodeReader(raw, kind)


class _LayerScan:
    """Per-file state while decoded layers are scanned."""

    def __init__(self, path, patterns, budget):
        self.path = path
        self.patterns = patterns
        self.budget = budget
        self.layers = {}
        self.undecoded = []
        self.decoded_bytes = 0

    def unread(self, label, cause):
        self.undecoded.append({"path": str(self.path), "reason": f"{label}:{cause}"})

    def keep(self, label, hits, stripped_hits):
        if hits:
            self.layers[label] = hits
        if stripped_hits:
            self.layers[f"{label}>{NUL_STRIPPED_LAYER}" if label else NUL_STRIPPED_LAYER] = stripped_hits

    def scan_layer(self, open_layer, label, depth):
        """Scan one decoded layer, then any layer inside it.

        S3: matches made before a layer breaks (truncated or corrupt stream, cap
        reached) are kept, and the layer is also listed as undecoded.
        """
        start = self.budget.remaining
        hits, stripped_hits = {}, {}
        head = None
        try:
            with open_layer() as reader:
                _hits, head, _stripped = _scan_stream(
                    _CappedReader(reader, self.budget), self.patterns, hits=hits, stripped_hits=stripped_hits
                )
        except _DecodedTooLarge:
            self.unread(label, "decoded_oversize")
        except Exception as exc:  # noqa: BLE001 - S1: any decoder failure is this file's, never the scan's.
            self.unread(label, type(exc).__name__)
        finally:
            self.decoded_bytes += max(0, start - max(self.budget.remaining, 0))
        self.keep(label, hits, stripped_hits)
        if head is not None:
            self.descend(open_layer, head, label, depth)

    def descend(self, open_layer, head, label, depth):
        kind = _sniff(head)
        if kind is None:
            return
        child = f"{label}>{kind.lstrip('!')}" if label else kind.lstrip("!")
        if kind.startswith("!"):
            self.unread(child, "undecodable_format")
            return
        if depth >= MAX_DECODE_DEPTH:
            self.unread(child, "max_decode_depth")
            return
        if kind == "zip":
            self.scan_zip(open_layer, label, depth)
            return
        self.scan_layer(lambda: _open_inner(open_layer, kind), child, depth + 1)

    def scan_zip(self, open_layer, label, depth):
        prefix = f"{label}>" if label else ""
        try:
            with open_layer() as raw:
                seekable = getattr(raw, "seekable", None)
                if not (callable(seekable) and seekable()):
                    # A zip needs its central directory; base64/UTF-16 layers cannot seek.
                    self.unread(prefix + "zip", "unseekable")
                    return
                self._scan_archive(raw, prefix, depth)
        except Exception as exc:  # noqa: BLE001 - S1: per file, never the whole scan.
            self.unread(prefix + "zip", type(exc).__name__)

    def _scan_archive(self, raw, prefix, depth):
        with zipfile.ZipFile(raw) as archive:
            for index, info in enumerate(archive.infolist()):
                if info.is_dir():
                    continue
                child = f"{prefix}zip[{index}]"
                if info.flag_bits & 0x1:
                    self.unread(child, "encrypted")
                    continue
                self.scan_layer(lambda info=info: archive.open(info), child, depth + 1)


def _scan_decoded(path, head, patterns, max_decoded_bytes):
    """Scan the decoded layers inside ``path`` (whose raw bytes start with ``head``).

    S1: whatever goes wrong while decoding is recorded against this file as
    undecoded; it never aborts the scan, so a FOUND elsewhere always survives.
    """
    layer_scan = _LayerScan(path, patterns, _Budget(max_decoded_bytes))
    try:
        layer_scan.descend(lambda: open(path, "rb"), head, "", 0)
    except Exception as exc:  # noqa: BLE001
        layer_scan.unread("decode", type(exc).__name__)
    return layer_scan


def scan(
    roots,
    *,
    exact_token: bytes | None = None,
    max_files=DEFAULT_MAX_FILES,
    max_file_bytes=DEFAULT_MAX_FILE_BYTES,
    max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
    excluded_dir_names=DEFAULT_EXCLUDED_DIR_NAMES,
    files=None,
    link_policy=LINKS_INCOMPLETE,
    max_decoded_bytes=DEFAULT_MAX_DECODED_BYTES,
):
    """Scan ``roots`` (or an explicit ``files`` list of paths) and return a :class:`ScanResult`.

    ``files`` entries are treated exactly like ``roots``: a regular file is read,
    a directory (or a junction named directly) is walked, a symlink is a skipped
    link, and a missing path is an error. Nothing in the list is dropped silently.
    """
    patterns = dict(PATTERNS)
    if exact_token:
        patterns[EXACT_TOKEN_PATTERN] = re.compile(re.escape(exact_token))
    if link_policy not in LINK_POLICIES:
        raise ValueError(f"unknown link policy: {link_policy!r}")
    result = ScanResult(link_policy=link_policy)
    requested = roots if files is None else files
    candidates = iter_files(requested, excluded_dir_names, result, link_policy=link_policy)
    for path, size in candidates:
        if result.files_scanned >= max_files:
            result.truncated_reason = "max_files"
            break
        if size > max_file_bytes:
            result.skipped_oversize.append({"path": str(path), "size_bytes": size})
            continue
        if result.bytes_scanned + size > max_total_bytes:
            result.truncated_reason = "max_total_bytes"
            break
        try:
            hits, head, stripped_hits = _scan_raw(path, patterns)
        except OSError as exc:
            result.errors.append({"path": str(path), "error": type(exc).__name__})
            continue
        result.files_scanned += 1
        result.bytes_scanned += size
        layers = _scan_decoded(path, head, patterns, max_decoded_bytes)
        layers.keep("", {}, stripped_hits)
        result.decoded_bytes_scanned += layers.decoded_bytes
        result.undecoded.extend(layers.undecoded)
        if hits or layers.layers:
            matches = {name: count for name, (count, _first) in hits.items()}
            for layer_hits in layers.layers.values():
                for name, (count, _first) in layer_hits.items():
                    matches[name] = matches.get(name, 0) + count
            row = {
                "path": str(path),
                "size_bytes": size,
                "matches": dict(sorted(matches.items())),
                # Offsets are into the raw file; a decoded-only match has none here.
                "first_match_offset": {name: first for name, (_count, first) in sorted(hits.items())},
            }
            if layers.layers:
                row["decoded_matches"] = {
                    label: {name: count for name, (count, _first) in sorted(layer_hits.items())}
                    for label, layer_hits in sorted(layers.layers.items())
                }
            result.findings.append(row)
    return result


def links_incomplete(result: ScanResult) -> bool:
    """True when a skipped link leaves part of a tree unread and no flag waived it."""
    return result.skipped_links > 0 and result.link_policy != LINKS_IGNORE


def reparse_incomplete(result: ScanResult) -> bool:
    """True when a non-link reparse point (placeholder, dedup file) was left unread.

    No link policy waives this: ``ignore`` may skip links, never data held in place.
    """
    return result.skipped_reparse_points > 0


def unread_reasons(result: ScanResult) -> list:
    """Every reason the scan did not read all it was asked to; empty only for a complete scan."""
    reasons = []
    if result.errors:
        reasons.append("errors")
    if result.skipped_oversize:
        reasons.append("oversize_files_skipped")
    if result.truncated_reason:
        reasons.append("truncated:" + result.truncated_reason)
    if links_incomplete(result):
        reasons.append("links_skipped")
    if reparse_incomplete(result):
        reasons.append("reparse_points_unread")
    if result.undecoded:
        reasons.append("undecoded_content")
    return reasons


def exit_code_for(result: ScanResult) -> int:
    if result.findings:
        return EXIT_FOUND
    if unread_reasons(result):
        return EXIT_ERROR
    return EXIT_CLEAN


def report(result: ScanResult, roots, *, exact_token_env=None, caps=None) -> dict:
    code = exit_code_for(result)
    status = {EXIT_CLEAN: "CLEAN", EXIT_FOUND: "FOUND", EXIT_ERROR: "INCOMPLETE"}[code]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "exit_code": code,
        "roots": [str(root) for root in roots],
        "patterns": sorted(PATTERNS) + ([EXACT_TOKEN_PATTERN] if exact_token_env else []),
        "exact_token_env": exact_token_env,
        "caps": caps or {},
        "files_scanned": result.files_scanned,
        "bytes_scanned": result.bytes_scanned,
        "decoded_bytes_scanned": result.decoded_bytes_scanned,
        "undecoded": result.undecoded,
        "skipped_excluded": result.skipped_excluded,
        "skipped_excluded_count": result.skipped_excluded_count,
        "finding_file_count": len(result.findings),
        "findings": result.findings,
        "skipped_links": result.skipped_links,
        "skipped_link_paths": result.skipped_link_paths,
        "skipped_link_paths_truncated": result.skipped_links > len(result.skipped_link_paths),
        "links_incomplete": links_incomplete(result),
        "link_policy": result.link_policy,
        "followed_links": result.followed_links,
        "skipped_reparse_points": result.skipped_reparse_points,
        "skipped_reparse_paths": result.skipped_reparse_paths,
        "reparse_incomplete": reparse_incomplete(result),
        "unread_reasons": unread_reasons(result),
        "skipped_oversize": result.skipped_oversize,
        "truncated_reason": result.truncated_reason,
        "errors": result.errors,
        "matched_text_reported": False,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m weather.operations.wu_token_scan",
        description=(
            "Read-only scan for persisted WU page access tokens. Reports paths, per-pattern "
            "counts and first-match byte offsets only; never the matched text."
        ),
    )
    parser.add_argument("roots", nargs="+", help="Files or directories to scan.")
    parser.add_argument(
        "--token-from-env",
        metavar="NAME",
        help="Also scan for the exact token held in environment variable NAME (never echoed).",
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument(
        "--max-decoded-bytes",
        type=int,
        default=DEFAULT_MAX_DECODED_BYTES,
        help="Decoded bytes read from one file across its gzip/zip/UTF-16/base64 layers; beyond it the "
        "file is listed in undecoded and the scan is incomplete.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        metavar="NAME",
        help="Directory name to skip (repeatable). Defaults: " + ", ".join(DEFAULT_EXCLUDED_DIR_NAMES),
    )
    parser.add_argument(
        "--links",
        choices=LINK_POLICIES,
        default=LINKS_INCOMPLETE,
        help=(
            "What to do with a symlink, junction or reparse point inside a root. "
            "incomplete (default): skip it, list it and exit 2 unless something is found; "
            "follow-within-root: follow it only if its target resolves inside the requested root; "
            "ignore: skip and list it without making the scan incomplete. A non-link reparse "
            "point (OneDrive placeholder, dedup file) left unread is incomplete under every policy."
        ),
    )
    parser.add_argument("--json-out", help="Also write the JSON report to this path.")
    return parser


def _error_report(message, roots):
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ERROR",
        "exit_code": EXIT_ERROR,
        "roots": [str(root) for root in roots],
        "error": message,
        "matched_text_reported": False,
    }


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    exact_token = None
    if args.token_from_env:
        value = os.environ.get(args.token_from_env, "")
        if len(value.strip()) < MIN_ENV_TOKEN_CHARS:
            payload = _error_report(
                f"environment variable {args.token_from_env} is unset or shorter than "
                f"{MIN_ENV_TOKEN_CHARS} characters",
                args.roots,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return EXIT_ERROR
        exact_token = value.strip().encode("utf-8")
    caps = {
        "max_files": args.max_files,
        "max_file_bytes": args.max_file_bytes,
        "max_total_bytes": args.max_total_bytes,
        "max_decoded_bytes": args.max_decoded_bytes,
        "excluded_dir_names": list(args.exclude_dir or DEFAULT_EXCLUDED_DIR_NAMES),
        "links": args.links,
    }
    try:
        result = scan(
            args.roots,
            exact_token=exact_token,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
            excluded_dir_names=args.exclude_dir or DEFAULT_EXCLUDED_DIR_NAMES,
            link_policy=args.links,
            max_decoded_bytes=args.max_decoded_bytes,
        )
    except Exception as exc:  # noqa: BLE001 - report the class only; a message could quote file text.
        payload = _error_report(f"scan failed: {type(exc).__name__}", args.roots)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_ERROR
    finally:
        exact_token = None
    payload = report(result, args.roots, exact_token_env=args.token_from_env, caps=caps)
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        try:
            out = Path(args.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"wu_token_scan: --json-out could not be written ({type(exc).__name__})", file=sys.stderr)
            # A finding always wins: a wrapper keyed on exit 1 must never miss a FOUND.
            return EXIT_FOUND if payload["exit_code"] == EXIT_FOUND else EXIT_OUTPUT_ERROR
    return payload["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
