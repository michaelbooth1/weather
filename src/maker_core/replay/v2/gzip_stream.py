"""Deterministic single-member gzip for bundle v0.3 streams (owner decision 8; B-def D2/D3).

Writer side (``compress_file``): stdlib ``gzip`` with ``mtime=0``, an empty header file name and a fixed
level, so the header is fixed (no FNAME, MTIME 0, OS byte 255, XFL set by the level). The deflate body is a
property of the zlib build: it is stable within one build but NOT portable across zlib builds (CPython's
Windows builds move to zlib-ng in 3.14). The stored-byte SHA-256 is therefore transport integrity only; the
per-stream decoded SHA-256 is the identity for any cross-host or cross-version comparison, and the zlib
runtime version is recorded beside it.

Reader side (``decode``): ``zlib`` in gzip-wrapper mode, which checks the header, CRC-32 and ISIZE. The
caller hashes the stored bytes it feeds in (so the hash is under the decompressor, not of the decoded
lines). Decoded output is produced in bounded slices and refused as soon as it would exceed the
manifest's declared size (decompression bomb). Every zlib failure, a truncated member, a non-canonical
header, and a second member or trailing bytes after the first member are refused as ``BundleError``.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
import gzip
import hashlib
from pathlib import Path
import sys
import zlib

from maker_core.replay.bundle import BundleError

CODEC = "gzip"
LEVEL = 6
MTIME = 0
CHUNK_BYTES = 1024**2
HEADER_BYTES = 10
_MAGIC = b"\x1f\x8b\x08"


def compression_record(level: int = LEVEL) -> dict:
    """The ``bundle.json`` ``compression`` object (manifest-bound, checked by the reader)."""
    return dict(codec=CODEC, level=level, mtime=MTIME, zlib_runtime_version=zlib.ZLIB_RUNTIME_VERSION)


def receipt_record(level: int = LEVEL) -> dict:
    """What the export receipt records about how the stored bytes were produced (B-def D3)."""
    return dict(compression_record(level), zlib_version=zlib.ZLIB_VERSION, python=sys.version)


class _HashingSink:
    """A write-only file object that hashes and counts every stored byte the compressor emits."""

    def __init__(self, handle):
        self.handle, self.sha, self.bytes = handle, hashlib.sha256(), 0

    def write(self, raw) -> int:
        raw = bytes(raw)
        self.handle.write(raw)
        self.sha.update(raw)
        self.bytes += len(raw)
        return len(raw)

    def flush(self):
        self.handle.flush()


def compress_file(source: Path, target: Path, *, level: int = LEVEL,
                  check: Callable[[], None] = lambda: None) -> dict:
    """Gzip ``source`` into the new file ``target``; return the stored ``sha256`` and ``bytes``."""
    if type(level) is not int or not 1 <= level <= 9:
        raise BundleError("invalid_compression_level")
    with source.open("rb") as inp, target.open("xb") as out:
        sink = _HashingSink(out)
        with gzip.GzipFile(filename="", mode="wb", compresslevel=level, fileobj=sink, mtime=MTIME) as packed:
            while block := inp.read(CHUNK_BYTES):
                check()
                packed.write(block)
        out.flush()
    return dict(sha256=sink.sha.hexdigest(), bytes=sink.bytes)


def _header(head: bytes):
    """A canonical header: gzip magic, deflate, no flags (no name/comment/extra), MTIME 0."""
    if head[:3] != _MAGIC:
        raise BundleError("stream_decompression_failed")
    if head[3] != 0 or head[4:8] != b"\x00\x00\x00\x00":
        raise BundleError("stream_gzip_header_not_canonical")


def decode(chunks: Iterable[bytes], limit: int, *, check: Callable[[], None] = lambda: None) -> Iterator[bytes]:
    """Decoded blocks of exactly one gzip member fed as stored ``chunks``; at most ``limit`` decoded bytes.

    Raises ``BundleError``: ``stream_decompression_failed`` (bad header, corrupt deflate data, CRC or ISIZE
    mismatch, truncated member), ``stream_gzip_header_not_canonical``, ``stream_multi_member_or_trailing_data``,
    ``stream_decoded_size_mismatch`` (more than ``limit`` decoded bytes: refused before the excess is kept).
    """
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    state = dict(total=0, head=b"")

    def drain(data):
        while True:
            out = inflater.decompress(data, min(CHUNK_BYTES, limit - state["total"] + 1))
            if out:
                state["total"] += len(out)
                if state["total"] > limit:
                    raise BundleError("stream_decoded_size_mismatch")
                yield out
            if inflater.eof:
                if inflater.unused_data:
                    raise BundleError("stream_multi_member_or_trailing_data")
                return
            tail = inflater.unconsumed_tail
            if not out and len(tail) >= len(data):
                if tail:
                    raise BundleError("stream_decompression_failed")
                return  # needs more input
            data = tail
            check()

    try:
        for chunk in chunks:
            if not chunk:
                continue
            if inflater.eof:
                raise BundleError("stream_multi_member_or_trailing_data")
            if len(state["head"]) < HEADER_BYTES:
                state["head"] += chunk[:HEADER_BYTES - len(state["head"])]
                if len(state["head"]) == HEADER_BYTES:
                    _header(state["head"])
            yield from drain(chunk)
        if not inflater.eof:
            yield from drain(b"")
        if not inflater.eof:
            raise BundleError("stream_decompression_failed")
    except zlib.error as exc:
        raise BundleError("stream_decompression_failed") from exc


def lines(blocks: Iterable[bytes], max_line_bytes: int) -> Iterator[bytes]:
    """Newline-terminated lines from decoded blocks; a line over ``max_line_bytes`` or an unterminated
    tail is refused without being buffered past the cap."""
    rest = b""
    for block in blocks:
        data = rest + block if rest else block
        start = 0
        while (end := data.find(b"\n", start)) >= 0:
            if end + 1 - start > max_line_bytes:
                raise BundleError("record_too_large_or_unterminated")
            yield data[start:end + 1]
            start = end + 1
        rest = data[start:]
        if len(rest) > max_line_bytes:
            raise BundleError("record_too_large_or_unterminated")
    if rest:
        raise BundleError("record_too_large_or_unterminated")
