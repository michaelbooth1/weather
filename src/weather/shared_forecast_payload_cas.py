"""Shared immutable byte store for market-invariant forecast responses.

The store itself is owner-neutral: ``weather.collection`` publishes into it
(snapshot writer, cross-process fetch fan-out) and ``weather.model`` reads it to
dereference last-good cache entries. It imports only the standard library and
``weather.paths``. ``weather.collection.forecast_payload_cas`` re-exports every public
name here, so existing callers see the same objects.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any

from weather.paths import data_path


# One fleet root: the snapshot writer, the isolated capture fan-out and the
# last-good model cache all resolve blobs below it.
SHARED_FORECAST_PAYLOAD_CAS_ROOT = data_path("forecast_payload_cas")
SHARED_FORECAST_PAYLOAD_CAS_KIND = "shared-forecast-payload-cas-v1"
SHARED_FORECAST_PAYLOAD_SCOPE = "shared_market_invariant"
RAW_BYTES_HASH_ALGORITHM = "sha256-raw-bytes"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ForecastPayloadCASIntegrityError(RuntimeError):
    """A shared payload reference is missing, malformed, or corrupt."""


def validate_sha256(digest: str) -> str:
    digest = str(digest or "").lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ForecastPayloadCASIntegrityError(f"invalid SHA-256 digest: {digest!r}")
    return digest


def raw_payload_digest(payload_bytes: bytes) -> str:
    return hashlib.sha256(bytes(payload_bytes)).hexdigest()


def shared_payload_ref(digest: str) -> str:
    digest = validate_sha256(digest)
    return f"sha256/{digest[:2]}/{digest}.blob"


def _stream_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class SharedForecastPayloadCAS:
    """Atomic, cross-process convergent CAS for exact raw response bytes.

    A complete uniquely named staging file is flushed and verified before an
    atomic hard-link publishes the digest path.  Therefore a killed writer can
    leave only an unreferenced staging file; readers never observe a partial
    final blob.  Competing publishers either create the same final inode or
    verify the already-published bytes before reporting reuse.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else SHARED_FORECAST_PAYLOAD_CAS_ROOT

    def relative_ref(self, digest: str) -> str:
        return shared_payload_ref(digest)

    def path_for(self, digest: str) -> Path:
        return self.root.joinpath(*self.relative_ref(digest).split("/"))

    def verify_path(self, path: str | Path, digest: str, *, expected_bytes: int | None = None) -> int:
        path = Path(path)
        digest = validate_sha256(digest)
        if path.is_symlink():
            raise ForecastPayloadCASIntegrityError(f"shared payload symlink forbidden: {path}")
        if not path.is_file():
            raise ForecastPayloadCASIntegrityError(f"shared payload missing: {path}")
        actual_digest, actual_bytes = _stream_digest(path)
        if actual_digest != digest:
            raise ForecastPayloadCASIntegrityError(
                f"shared payload hash mismatch: path={path} expected={digest} actual={actual_digest}"
            )
        if expected_bytes is not None and actual_bytes != int(expected_bytes):
            raise ForecastPayloadCASIntegrityError(
                f"shared payload byte-count mismatch: path={path} expected={expected_bytes} actual={actual_bytes}"
            )
        return actual_bytes

    def verify(self, digest: str, *, expected_bytes: int | None = None) -> int:
        return self.verify_path(self.path_for(digest), digest, expected_bytes=expected_bytes)

    def contains(self, digest: str, *, expected_bytes: int) -> bool:
        """Return whether a published blob exists with the expected byte count.

        This is a cheap presence check for callers that keep only a reference;
        it does not re-hash.  Anything that serves the bytes must use ``read``,
        which verifies the digest and size.
        """

        path = self.path_for(digest)
        if path.is_symlink() or not path.is_file():
            return False
        return path.stat().st_size == int(expected_bytes)

    def put(self, payload_bytes: bytes, *, expected_digest: str | None = None) -> dict[str, Any]:
        payload_bytes = bytes(payload_bytes)
        digest = raw_payload_digest(payload_bytes)
        if expected_digest is not None and validate_sha256(expected_digest) != digest:
            raise ForecastPayloadCASIntegrityError(
                "precomputed shared forecast payload digest does not match supplied bytes"
            )
        path = self.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            self.verify_path(path, digest, expected_bytes=len(payload_bytes))
            return self._put_result(path, digest, len(payload_bytes), created=False)

        staging = path.with_name(
            f".{path.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
        )
        created = False
        try:
            with staging.open("xb") as handle:
                handle.write(payload_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            self.verify_path(staging, digest, expected_bytes=len(payload_bytes))
            try:
                # A hard link publishes an already-complete file without ever
                # replacing an immutable digest path.  It is atomic on NTFS and
                # on the POSIX filesystems used by CI.
                os.link(staging, path)
                created = True
            except FileExistsError:
                created = False
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    created = False
                else:
                    raise
            self.verify_path(path, digest, expected_bytes=len(payload_bytes))
        finally:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
        return self._put_result(path, digest, len(payload_bytes), created=created)

    def read(self, digest: str, *, expected_bytes: int | None = None) -> bytes:
        path = self.path_for(digest)
        digest = validate_sha256(digest)
        if path.is_symlink():
            raise ForecastPayloadCASIntegrityError(f"shared payload symlink forbidden: {path}")
        if not path.is_file():
            raise ForecastPayloadCASIntegrityError(f"shared payload missing: {path}")
        actual_digest = hashlib.sha256()
        payload = bytearray()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                actual_digest.update(chunk)
                payload.extend(chunk)
        if actual_digest.hexdigest() != digest:
            raise ForecastPayloadCASIntegrityError(f"shared payload hash mismatch: {path}")
        if expected_bytes is not None and len(payload) != int(expected_bytes):
            raise ForecastPayloadCASIntegrityError(f"shared payload byte-count mismatch: {path}")
        return bytes(payload)

    def _put_result(self, path: Path, digest: str, payload_bytes: int, *, created: bool) -> dict[str, Any]:
        return {
            "cas_kind": SHARED_FORECAST_PAYLOAD_CAS_KIND,
            "storage_scope": SHARED_FORECAST_PAYLOAD_SCOPE,
            "payload_hash_algorithm": RAW_BYTES_HASH_ALGORITHM,
            "payload_hash": digest,
            "payload_bytes": payload_bytes,
            "payload_ref": self.relative_ref(digest),
            "path": str(path),
            "created": bool(created),
            "reused": not bool(created),
            "physical_bytes_written": payload_bytes if created else 0,
            "logical_referenced_bytes": payload_bytes,
            "avoided_bytes": 0 if created else payload_bytes,
        }
