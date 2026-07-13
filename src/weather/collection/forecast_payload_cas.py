"""Shared immutable storage for market-invariant forecast response bytes.

The shared store owns only raw response bytes.  Per-market capture time,
request/cycle identity, parsing identity, and model lineage remain in the
append-only snapshot manifest written by :mod:`weather.collection.snapshot_store`.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

from weather.forecast_payload_contracts import (
    ForecastPayloadExtractionIdentityError,
    NBM_NBP_ENCODING,
    NBM_NBP_MEDIA_TYPE,
    NBM_NBP_SOURCE,
    validate_nbm_shared_payload_identity,
    validate_forecast_extraction_identity,
)
from weather.paths import data_path


SHARED_FORECAST_PAYLOAD_CAS_ROOT = data_path("forecast_payload_cas")
SHARED_FORECAST_PAYLOAD_CAS_KIND = "shared-forecast-payload-cas-v1"
SHARED_FORECAST_PAYLOAD_SCOPE = "shared_market_invariant"
LOCAL_FORECAST_PAYLOAD_CAS_KIND = "market-local-forecast-payload-cas-v1"
LOCAL_FORECAST_PAYLOAD_SCOPE = "market_local"
RAW_BYTES_HASH_ALGORITHM = "sha256-raw-bytes"
CANONICAL_JSON_HASH_ALGORITHM = "sha256-canonical-json"
PAYLOAD_ATTESTATION_KEY = "forecast_payload_attestation"
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


def parse_market_invariant_attestation(source: str, payload: Any) -> dict[str, Any] | None:
    """Return verified storage inputs for an explicitly attested response.

    Attestation is opt-in and deliberately strict.  Unknown or incomplete
    metadata is an integrity error, not an invitation to infer that a provider
    response is market invariant.
    """

    if not isinstance(payload, Mapping):
        return None
    attestation = payload.get(PAYLOAD_ATTESTATION_KEY)
    if attestation is None:
        return None
    if not isinstance(attestation, Mapping):
        raise ForecastPayloadCASIntegrityError("forecast payload attestation must be an object")
    if attestation.get("market_invariant") is not True:
        raise ForecastPayloadCASIntegrityError(
            "forecast payload attestation must explicitly set market_invariant=true"
        )
    if str(attestation.get("source") or "") != str(source):
        raise ForecastPayloadCASIntegrityError("forecast payload attestation source mismatch")
    request_key = str(attestation.get("request_key") or "").strip()
    cycle_key = str(attestation.get("cycle_key") or "").strip()
    body_field = str(attestation.get("body_field") or "").strip()
    encoding = str(attestation.get("encoding") or "utf-8").lower()
    media_type = str(attestation.get("media_type") or "").strip()
    if not request_key or not cycle_key or not body_field or not media_type:
        raise ForecastPayloadCASIntegrityError(
            "market-invariant attestation requires request_key, cycle_key, body_field, and media_type"
        )
    if encoding != NBM_NBP_ENCODING:
        raise ForecastPayloadCASIntegrityError(
            f"unsupported market-invariant payload encoding: {encoding}"
        )
    if media_type != NBM_NBP_MEDIA_TYPE:
        raise ForecastPayloadCASIntegrityError(
            "NBM shared payload media type does not match its replay contract"
        )
    body = payload.get(body_field)
    if not isinstance(body, str):
        raise ForecastPayloadCASIntegrityError(
            f"attested market-invariant body field is not text: {body_field}"
        )
    extraction_schema = str(attestation.get("extraction_schema") or "").strip()
    extraction_identity = attestation.get("extraction_identity")
    try:
        extraction_identity = validate_nbm_shared_payload_identity(
            source=source,
            source_url=str(payload.get("source_url") or payload.get("url") or ""),
            request_key=request_key,
            cycle_key=cycle_key,
            extraction_schema=extraction_schema,
            extraction_identity=extraction_identity,
            target_date=str(payload.get("target_date") or ""),
            payload=payload,
        )
    except ForecastPayloadExtractionIdentityError as exc:
        raise ForecastPayloadCASIntegrityError(str(exc)) from exc
    single_fetch = attestation.get("single_fetch")
    if single_fetch is None:
        single_fetch = {}
    elif not isinstance(single_fetch, Mapping):
        raise ForecastPayloadCASIntegrityError(
            "forecast single-fetch provenance must be an object"
        )
    for key, expected in (
        ("request_key", request_key),
        ("cycle_key", cycle_key),
    ):
        declared = str(single_fetch.get(key) or "").strip()
        if declared and declared != expected:
            raise ForecastPayloadCASIntegrityError(
                f"forecast single-fetch {key} does not match its attestation"
            )
    return {
        "payload_bytes": body.encode(encoding),
        "request_key": request_key,
        "cycle_key": cycle_key,
        "media_type": media_type,
        "encoding": encoding,
        "extraction_schema": extraction_schema,
        "extraction_identity": extraction_identity,
        "single_fetch": dict(single_fetch),
        "single_fetch_reused": bool(single_fetch.get("reused")),
    }


def manifest_extraction_identity(row: Mapping[str, Any]) -> dict[str, str]:
    """Parse and validate the source-specific replay identity in a v2 row."""

    raw_identity = row.get("extraction_identity")
    if isinstance(raw_identity, str):
        try:
            raw_identity = json.loads(raw_identity)
        except json.JSONDecodeError as exc:
            raise ForecastPayloadCASIntegrityError(
                "forecast extraction identity is not valid JSON"
            ) from exc
    try:
        return validate_forecast_extraction_identity(
            str(row.get("source") or ""),
            str(row.get("extraction_schema") or ""),
            raw_identity,
        )
    except ForecastPayloadExtractionIdentityError as exc:
        raise ForecastPayloadCASIntegrityError(str(exc)) from exc


def _market_station_id(market_id: Any) -> str | None:
    market_id = str(market_id or "").strip().lower()
    if not market_id:
        return None
    # Keep the shared contract independent of the market package at import
    # time. The registry lookup is used only when a manifest declares a known
    # market; unknown research markets remain verifiable by their explicit
    # extraction identity.
    from weather.market.market_registry import REGISTRY

    spec = REGISTRY.get(market_id)
    station_id = getattr(spec, "icao", None) if spec is not None else None
    return str(station_id).upper().strip() if station_id else None


def validate_nbm_shared_manifest_identity(
    row: Mapping[str, Any],
    *,
    expected_station_id: str | None = None,
) -> dict[str, str]:
    """Validate one v2 NBM manifest's request, cycle, target, and station."""

    if row.get("schema_version") != "forecast_payload_manifest_v2":
        raise ForecastPayloadCASIntegrityError(
            "shared NBM reference requires forecast_payload_manifest_v2"
        )
    if str(row.get("source") or "").strip() != NBM_NBP_SOURCE:
        raise ForecastPayloadCASIntegrityError(
            "shared NBM identity validator received an unsupported source"
        )
    target_date = str(row.get("target_date") or "").strip()
    if not target_date:
        raise ForecastPayloadCASIntegrityError(
            "shared NBM manifest target_date is missing"
        )
    expected_station_id = (
        str(expected_station_id or "").upper().strip()
        or _market_station_id(row.get("market_id"))
    )
    raw_identity = row.get("extraction_identity")
    if isinstance(raw_identity, str):
        try:
            raw_identity = json.loads(raw_identity)
        except json.JSONDecodeError as exc:
            raise ForecastPayloadCASIntegrityError(
                "forecast extraction identity is not valid JSON"
            ) from exc
    try:
        return validate_nbm_shared_payload_identity(
            source=str(row.get("source") or ""),
            source_url=str(row.get("source_url") or ""),
            request_key=str(row.get("request_key") or ""),
            cycle_key=str(row.get("cycle_key") or ""),
            extraction_schema=str(row.get("extraction_schema") or ""),
            extraction_identity=raw_identity,
            target_date=target_date,
            expected_station_id=expected_station_id,
        )
    except ForecastPayloadExtractionIdentityError as exc:
        raise ForecastPayloadCASIntegrityError(str(exc)) from exc


def resolve_forecast_payload_bytes(
    row: Mapping[str, Any],
    *,
    shared_cas_root: str | Path | None = None,
    event_folder: str | Path | None = None,
) -> bytes:
    """Resolve and hash-verify one legacy-local or v2 shared manifest row."""

    digest = validate_sha256(str(row.get("payload_hash") or ""))
    expected_bytes = row.get("payload_bytes")
    expected_bytes = int(expected_bytes) if expected_bytes not in (None, "") else None
    if row.get("payload_storage_scope") == SHARED_FORECAST_PAYLOAD_SCOPE:
        if row.get("payload_cas_kind") != SHARED_FORECAST_PAYLOAD_CAS_KIND:
            raise ForecastPayloadCASIntegrityError("shared payload CAS kind mismatch")
        if row.get("payload_hash_algorithm") != RAW_BYTES_HASH_ALGORITHM:
            raise ForecastPayloadCASIntegrityError(
                "shared payload hash algorithm mismatch"
            )
        if (
            str(row.get("payload_encoding") or "").lower()
            != NBM_NBP_ENCODING
        ):
            raise ForecastPayloadCASIntegrityError("shared payload encoding mismatch")
        if row.get("payload_media_type") != NBM_NBP_MEDIA_TYPE:
            raise ForecastPayloadCASIntegrityError(
                "shared payload media type mismatch"
            )
        if row.get("raw_payload_retained") is not True:
            raise ForecastPayloadCASIntegrityError(
                "shared payload row must retain its raw CAS reference"
            )
        validate_nbm_shared_manifest_identity(row)
        ref = str(row.get("payload_ref") or "")
        expected_ref = shared_payload_ref(digest)
        if ref != expected_ref:
            raise ForecastPayloadCASIntegrityError(
                f"shared payload ref mismatch: expected={expected_ref} actual={ref!r}"
            )
        cas = SharedForecastPayloadCAS(shared_cas_root)
        declared_path = str(row.get("raw_payload_path") or "").strip()
        if (
            shared_cas_root is None
            and declared_path
            and Path(declared_path).resolve() != cas.path_for(digest).resolve()
        ):
            raise ForecastPayloadCASIntegrityError("shared payload path does not match CAS root/ref")
        return cas.read(digest, expected_bytes=expected_bytes)

    raw_path_text = str(row.get("raw_payload_path") or "").strip()
    if not raw_path_text:
        raise ForecastPayloadCASIntegrityError("market-local payload path missing")
    raw_path = Path(raw_path_text)
    if not raw_path.is_absolute() and event_folder is not None:
        raw_path = Path(event_folder) / raw_path
    if raw_path.is_symlink() or not raw_path.is_file():
        raise ForecastPayloadCASIntegrityError(f"market-local payload missing or symlinked: {raw_path}")
    with raw_path.open("rb") as handle:
        stored = handle.read()
    canonical_bytes = stored[:-1] if stored.endswith(b"\n") else stored
    if raw_payload_digest(canonical_bytes) != digest:
        raise ForecastPayloadCASIntegrityError(f"market-local payload hash mismatch: {raw_path}")
    if expected_bytes is not None and len(canonical_bytes) != expected_bytes:
        raise ForecastPayloadCASIntegrityError(f"market-local payload byte-count mismatch: {raw_path}")
    return canonical_bytes


def forecast_payload_byte_summary(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    physical_write_budget_bytes: int | None = None,
) -> dict[str, Any]:
    created = sum(1 for row in rows if row.get("payload_blob_created"))
    reused = sum(1 for row in rows if row.get("payload_blob_reused"))
    logical = sum(int(row.get("logical_referenced_bytes") or row.get("payload_bytes") or 0) for row in rows)
    physical = sum(int(row.get("physical_bytes_written") or 0) for row in rows)
    avoided = sum(int(row.get("avoided_bytes") or 0) for row in rows)
    budget = int(physical_write_budget_bytes) if physical_write_budget_bytes is not None else None
    return {
        "schema_version": "forecast_payload_storage_observability_v0.1",
        "manifest_row_count": len(rows),
        "created_blob_count": created,
        "reused_blob_count": reused,
        "logical_referenced_bytes": logical,
        "physical_bytes_written": physical,
        "avoided_bytes": avoided,
        "physical_write_budget_bytes": budget,
        "physical_write_budget_status": (
            "NOT_CONFIGURED"
            if budget is None
            else ("PASS" if physical <= budget else "BLOCK")
        ),
    }
