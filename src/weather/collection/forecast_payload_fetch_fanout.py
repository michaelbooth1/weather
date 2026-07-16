"""Cross-process single-fetch fan-out for immutable NBM national payloads.

The managed snapshot fleet runs one market per isolated child.  A holder
fetches the market-invariant response, publishes its exact bytes through the
shared forecast CAS, and then publishes a small immutable receipt.  Other
children wait for that receipt and hash-verify the CAS bytes before parsing
their own station.  A bounded wait timeout fails open to the caller's ordinary
provider fetch so a wedged holder cannot stall the fleet.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from weather.collection.forecast_payload_cas import (
    ForecastPayloadCASIntegrityError,
    SharedForecastPayloadCAS,
    shared_payload_ref,
)
from weather.forecast_payload_contracts import (
    ForecastPayloadExtractionIdentityError,
    NBM_NBP_SOURCE,
    forecast_fanout_coordination_id,
    forecast_fanout_receipt_ref,
    nbm_nbp_cycle_key_from_bulletin,
)
from weather.sources.forecast_payload_fanout import (
    FanoutFetchResult,
    MarketInvariantFetchFanout,
)


RECEIPT_SCHEMA_VERSION = "forecast_payload_cross_process_fanout_receipt_v0.1"
FANOUT_CAS_ROOT_ENV = "WEATHER_FORECAST_FANOUT_CAS_ROOT"
FANOUT_SCOPE_ENV = "WEATHER_FORECAST_FANOUT_SCOPE"
DEFAULT_WAIT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_SECONDS = 0.05
MAX_RECEIPT_BYTES = 16 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_RECEIPT_CONTENT_SHA256_KEY = "_verified_receipt_content_sha256"


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")


def _receipt_stat_signature(value: os.stat_result) -> tuple[int, ...]:
    """Return the path identity and mutation-sensitive receipt metadata."""

    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _validate_receipt_stat(path: Path, value: os.stat_result) -> None:
    attributes = int(getattr(value, "st_file_attributes", 0) or 0)
    if not stat.S_ISREG(value.st_mode) or (
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ForecastPayloadCASIntegrityError(
            f"cross-process fan-out receipt is not a regular non-reparse file: {path}"
        )
    if value.st_size > MAX_RECEIPT_BYTES:
        raise ForecastPayloadCASIntegrityError(
            f"cross-process fan-out receipt exceeds {MAX_RECEIPT_BYTES} bytes: {path}"
        )


def _receipt_ancestor_paths(cas_root: Path, parent: Path) -> list[Path]:
    """Return the lexical CAS-root-to-parent chain without resolving links."""

    root = Path(os.path.abspath(cas_root))
    parent = Path(os.path.abspath(parent))
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ForecastPayloadCASIntegrityError(
            f"cross-process fan-out receipt path escapes CAS root: {parent}"
        ) from exc
    paths = [root]
    current = root
    for part in relative.parts:
        current = current / part
        paths.append(current)
    return paths


def _validate_receipt_ancestors(
    cas_root: Path,
    parent: Path,
    *,
    allow_missing: bool,
) -> None:
    """Reject symlink/reparse ancestors from the CAS root through the parent."""

    missing_seen = False
    for path in _receipt_ancestor_paths(cas_root, parent):
        try:
            value = os.lstat(path)
        except FileNotFoundError:
            if not allow_missing:
                raise ForecastPayloadCASIntegrityError(
                    f"cross-process fan-out receipt ancestor is missing: {path}"
                )
            missing_seen = True
            continue
        except OSError as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt ancestor is unreadable: {path}: {exc}"
            ) from exc
        if missing_seen:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt ancestor exists below a missing "
                f"directory: {path}"
            )
        attributes = int(getattr(value, "st_file_attributes", 0) or 0)
        if not stat.S_ISDIR(value.st_mode) or (
            attributes & _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt ancestor is not a regular "
                f"non-reparse directory: {path}"
            )


def _ensure_receipt_parent(cas_root: Path, parent: Path) -> None:
    _validate_receipt_ancestors(cas_root, parent, allow_missing=True)
    parent.mkdir(parents=True, exist_ok=True)
    _validate_receipt_ancestors(cas_root, parent, allow_missing=False)


def _write_immutable_json(
    cas_root: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    """Publish one complete receipt without replacing an existing receipt."""

    encoded = _canonical_json_bytes(payload)
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise ForecastPayloadCASIntegrityError(
            f"cross-process fan-out receipt exceeds {MAX_RECEIPT_BYTES} bytes"
        )
    _ensure_receipt_parent(cas_root, path.parent)
    staging = path.with_name(
        f".{path.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        with staging.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(staging, path)
        except FileExistsError:
            pass
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
        _validate_receipt_ancestors(
            cas_root,
            path.parent,
            allow_missing=False,
        )
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _error_receipt(exc: Exception) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    if isinstance(exc, requests.HTTPError):
        kind = "http_error"
    elif isinstance(exc, requests.Timeout):
        kind = "timeout"
    elif isinstance(exc, requests.ConnectionError):
        kind = "connection_error"
    else:
        kind = "remote_error"
    return {
        "kind": kind,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "http_status": _http_status(exc),
        "retry_after": retry_after,
    }


def _raise_receipt_error(error: Mapping[str, Any]) -> None:
    kind = str(error.get("kind") or "remote_error")
    message = str(error.get("message") or error.get("exception_type") or kind)
    if kind == "http_error":
        response = requests.Response()
        response.status_code = int(error.get("http_status") or 500)
        if error.get("retry_after") not in (None, ""):
            response.headers["Retry-After"] = str(error["retry_after"])
        raise requests.HTTPError(message, response=response)
    if kind == "timeout":
        raise requests.Timeout(message)
    if kind == "connection_error":
        raise requests.ConnectionError(message)
    raise RuntimeError(f"cross-process fetch holder failed: {message}")


class CrossProcessMarketInvariantFetchFanout:
    """Coordinate one market-invariant fetch across isolated child processes."""

    def __init__(
        self,
        cas_root: str | Path,
        *,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        monotonic_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.cas = SharedForecastPayloadCAS(cas_root)
        self.wait_timeout_seconds = max(0.0, float(wait_timeout_seconds))
        self.poll_seconds = max(0.001, float(poll_seconds))
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self._local = MarketInvariantFetchFanout(max_entries=2)

    @staticmethod
    def _validated_key(
        source: str,
        request_key: str,
        cycle_key: str,
        scope_key: str,
    ) -> tuple[str, str, str, str]:
        source, request_key, cycle_key = MarketInvariantFetchFanout._key(
            source,
            request_key,
            cycle_key,
        )
        if source != NBM_NBP_SOURCE:
            raise ValueError(
                "cross-process single-fetch fan-out is registered only for NBM NBP"
            )
        scope_key = str(scope_key or "").strip()
        if not scope_key:
            raise ValueError("cross-process single-fetch fan-out requires scope_key")
        return source, request_key, cycle_key, scope_key

    def _paths(
        self,
        source: str,
        request_key: str,
        cycle_key: str,
        scope_key: str,
    ) -> tuple[Path, Path]:
        digest = forecast_fanout_coordination_id(
            source=source,
            request_key=request_key,
            cycle_key=cycle_key,
            scope_key=scope_key,
        )
        receipt_path = self.cas.root / forecast_fanout_receipt_ref(digest)
        return receipt_path, receipt_path.with_name(f"{digest}.claim")

    @staticmethod
    def _try_claim(
        cas_root: Path,
        path: Path,
        key_fields: Mapping[str, str],
    ) -> str | None:
        _ensure_receipt_parent(cas_root, path.parent)
        token = uuid.uuid4().hex
        payload = {
            **dict(key_fields),
            "token": token,
            "pid": os.getpid(),
            "claimed_at_unix": time.time(),
        }
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
        try:
            os.write(handle, _canonical_json_bytes(payload))
            os.fsync(handle)
        finally:
            os.close(handle)
        _validate_receipt_ancestors(
            cas_root,
            path.parent,
            allow_missing=False,
        )
        return token

    @staticmethod
    def _release_claim(cas_root: Path, path: Path, token: str) -> None:
        _validate_receipt_ancestors(
            cas_root,
            path.parent,
            allow_missing=False,
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("token") != token:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        _validate_receipt_ancestors(
            cas_root,
            path.parent,
            allow_missing=False,
        )

    @staticmethod
    def _read_receipt(cas_root: Path, path: Path) -> dict[str, Any] | None:
        _validate_receipt_ancestors(
            cas_root,
            path.parent,
            allow_missing=True,
        )
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            _validate_receipt_ancestors(
                cas_root,
                path.parent,
                allow_missing=True,
            )
            return None
        except OSError as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt is unreadable: {path}: {exc}"
            ) from exc
        _validate_receipt_stat(path, before)
        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            handle = os.open(path, flags)
        except OSError as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt changed before open: {path}: {exc}"
            ) from exc
        try:
            opened = os.fstat(handle)
            _validate_receipt_stat(path, opened)
            if _receipt_stat_signature(opened) != _receipt_stat_signature(before):
                raise ForecastPayloadCASIntegrityError(
                    f"cross-process fan-out receipt changed before read: {path}"
                )
            chunks: list[bytes] = []
            remaining = MAX_RECEIPT_BYTES + 1
            while remaining > 0:
                chunk = os.read(handle, min(4096, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            after_read = os.fstat(handle)
        except OSError as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt is unreadable: {path}: {exc}"
            ) from exc
        finally:
            os.close(handle)
        try:
            after_path = os.lstat(path)
        except OSError as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt changed after read: {path}: {exc}"
            ) from exc
        _validate_receipt_stat(path, after_read)
        _validate_receipt_stat(path, after_path)
        _validate_receipt_ancestors(
            cas_root,
            path.parent,
            allow_missing=False,
        )
        signature = _receipt_stat_signature(before)
        if (
            _receipt_stat_signature(after_read) != signature
            or _receipt_stat_signature(after_path) != signature
            or len(encoded) != before.st_size
        ):
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt mutated during read: {path}"
            )
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt exceeds {MAX_RECEIPT_BYTES} bytes: {path}"
            )
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt is unreadable: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt is not an object: {path}"
            )
        payload[_RECEIPT_CONTENT_SHA256_KEY] = hashlib.sha256(encoded).hexdigest()
        return payload

    @staticmethod
    def _validated_coordinator_evidence(
        receipt: Mapping[str, Any],
        *,
        source: str,
        request_key: str,
        cycle_key: str,
        scope_key: str,
        payload_bytes: int,
    ) -> dict[str, Any]:
        evidence_id = forecast_fanout_coordination_id(
            source=source,
            request_key=request_key,
            cycle_key=cycle_key,
            scope_key=scope_key,
        )
        expected_ref = forecast_fanout_receipt_ref(evidence_id)
        receipt_sha256 = str(
            receipt.get(_RECEIPT_CONTENT_SHA256_KEY) or ""
        ).lower()
        if len(receipt_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in receipt_sha256
        ):
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt content hash is invalid"
            )
        if receipt.get("coordinator_evidence_id") != evidence_id:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out coordinator evidence identity mismatch"
            )
        if receipt.get("coordinator_receipt_ref") != expected_ref:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out coordinator receipt reference mismatch"
            )
        network_fetch_count = receipt.get("coordinator_network_fetch_count")
        physical_bytes = receipt.get("coordinator_physical_bytes_written")
        if type(network_fetch_count) is not int or network_fetch_count != 1:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out coordinator network-fetch count is invalid"
            )
        if type(physical_bytes) is not int or physical_bytes < 0:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out coordinator physical-write count is invalid"
            )
        created = receipt.get("coordinator_payload_blob_created")
        reused = receipt.get("coordinator_payload_blob_reused")
        if type(created) is not bool or type(reused) is not bool or created == reused:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out coordinator blob outcome is invalid"
            )
        expected_physical = payload_bytes if created else 0
        if physical_bytes != expected_physical:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out coordinator physical-write attribution mismatch"
            )
        return {
            "coordinator_evidence_id": evidence_id,
            "coordinator_receipt_ref": expected_ref,
            "coordinator_receipt_sha256": receipt_sha256,
            "coordinator_attribution_status": "available",
            "coordinator_network_fetch_count": network_fetch_count,
            "coordinator_payload_blob_created": created,
            "coordinator_payload_blob_reused": reused,
            "coordinator_physical_bytes_written": physical_bytes,
        }

    def _result_from_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        source: str,
        request_key: str,
        cycle_key: str,
        scope_key: str,
        waited_seconds: float,
    ) -> FanoutFetchResult:
        if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt schema mismatch"
            )
        for field, expected in (
            ("source", source),
            ("request_key", request_key),
            ("cycle_key", cycle_key),
            ("scope_key", scope_key),
        ):
            if str(receipt.get(field) or "") != expected:
                raise ForecastPayloadCASIntegrityError(
                    f"cross-process fan-out receipt {field} mismatch"
                )
        status = str(receipt.get("status") or "")
        if status == "error":
            error = receipt.get("error")
            if not isinstance(error, Mapping):
                raise ForecastPayloadCASIntegrityError(
                    "cross-process fan-out error receipt is malformed"
                )
            _raise_receipt_error(error)
        if status != "success":
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt status is invalid: {status!r}"
            )
        digest = str(receipt.get("payload_hash") or "")
        expected_bytes = receipt.get("payload_bytes")
        try:
            expected_bytes = int(expected_bytes)
        except (TypeError, ValueError) as exc:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt payload_bytes is invalid"
            ) from exc
        if receipt.get("payload_ref") != shared_payload_ref(digest):
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt payload_ref mismatch"
            )
        payload_bytes = self.cas.read(digest, expected_bytes=expected_bytes)
        try:
            text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out CAS payload is not UTF-8"
            ) from exc
        try:
            bulletin_cycle_key = nbm_nbp_cycle_key_from_bulletin(text)
        except ForecastPayloadExtractionIdentityError as exc:
            raise ForecastPayloadCASIntegrityError(str(exc)) from exc
        if bulletin_cycle_key != cycle_key:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out payload does not match the requested NBM cycle"
            )
        new_success_fields = {
            "bulletin_cycle_key",
            "coordinator_evidence_id",
            "coordinator_receipt_ref",
            "coordinator_network_fetch_count",
            "coordinator_payload_blob_created",
            "coordinator_payload_blob_reused",
            "coordinator_physical_bytes_written",
        }
        present_new_fields = new_success_fields.intersection(receipt)
        if present_new_fields and present_new_fields != new_success_fields:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out receipt has partial coordinator evidence"
            )
        if present_new_fields:
            if receipt.get("bulletin_cycle_key") != bulletin_cycle_key:
                raise ForecastPayloadCASIntegrityError(
                    "cross-process fan-out receipt bulletin cycle mismatch"
                )
            coordinator_evidence = self._validated_coordinator_evidence(
                receipt,
                source=source,
                request_key=request_key,
                cycle_key=cycle_key,
                scope_key=scope_key,
                payload_bytes=expected_bytes,
            )
        else:
            coordinator_evidence = {
                "coordinator_receipt_sha256": receipt.get(
                    _RECEIPT_CONTENT_SHA256_KEY
                ),
                "coordinator_attribution_status": (
                    "legacy_receipt_attribution_unavailable"
                ),
            }
        value = {
            "text": text,
            "fetched_at": receipt.get("fetched_at"),
            "request_started_at": receipt.get("request_started_at"),
            "response_received_at": receipt.get("response_received_at"),
        }
        return FanoutFetchResult(
            value,
            source,
            request_key,
            cycle_key,
            fetched=False,
            reused=True,
            coordination_status="cross_process_receipt_reused",
            waited_seconds=max(0.0, waited_seconds),
            prepublished_payload_hash=digest,
            prepublished_payload_bytes=expected_bytes,
            prepublished_payload_ref=receipt.get("payload_ref"),
            prepublished_blob_reused=True,
            **coordinator_evidence,
        )

    def _holder_fetch(
        self,
        *,
        source: str,
        request_key: str,
        cycle_key: str,
        scope_key: str,
        receipt_path: Path,
        claim_path: Path,
        claim_token: str,
        fetch_fn: Callable[[], Any],
        waited_seconds: float,
    ) -> FanoutFetchResult:
        coordinator_evidence_id = forecast_fanout_coordination_id(
            source=source,
            request_key=request_key,
            cycle_key=cycle_key,
            scope_key=scope_key,
        )
        base_receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "source": source,
            "request_key": request_key,
            "cycle_key": cycle_key,
            "scope_key": scope_key,
            "coordinator_evidence_id": coordinator_evidence_id,
            "coordinator_receipt_ref": forecast_fanout_receipt_ref(
                coordinator_evidence_id
            ),
        }
        try:
            value = fetch_fn()
            if not isinstance(value, Mapping) or not isinstance(value.get("text"), str):
                raise ForecastPayloadCASIntegrityError(
                    "cross-process NBM fan-out fetch must return a mapping with text"
                )
            try:
                bulletin_cycle_key = nbm_nbp_cycle_key_from_bulletin(
                    value["text"]
                )
            except ForecastPayloadExtractionIdentityError as exc:
                raise ForecastPayloadCASIntegrityError(str(exc)) from exc
            if bulletin_cycle_key != cycle_key:
                raise ForecastPayloadCASIntegrityError(
                    "cross-process fan-out payload does not match the requested NBM cycle"
                )
            payload_bytes = value["text"].encode("utf-8")
            stored = self.cas.put(payload_bytes)
            receipt = {
                **base_receipt,
                "status": "success",
                "bulletin_cycle_key": bulletin_cycle_key,
                "fetched_at": value.get("fetched_at"),
                "request_started_at": value.get("request_started_at"),
                "response_received_at": value.get("response_received_at"),
                "payload_hash": stored["payload_hash"],
                "payload_bytes": stored["payload_bytes"],
                "payload_ref": stored["payload_ref"],
                "coordinator_network_fetch_count": 1,
                "coordinator_payload_blob_created": stored["created"],
                "coordinator_payload_blob_reused": stored["reused"],
                "coordinator_physical_bytes_written": stored[
                    "physical_bytes_written"
                ],
            }
            _write_immutable_json(self.cas.root, receipt_path, receipt)
            published = self._read_receipt(self.cas.root, receipt_path)
            published_payload = {
                key: value
                for key, value in (published or {}).items()
                if key != _RECEIPT_CONTENT_SHA256_KEY
            }
            if published_payload != receipt:
                return self._result_from_receipt(
                    published or {},
                    source=source,
                    request_key=request_key,
                    cycle_key=cycle_key,
                    scope_key=scope_key,
                    waited_seconds=waited_seconds,
                )
            coordinator_evidence = self._validated_coordinator_evidence(
                published or {},
                source=source,
                request_key=request_key,
                cycle_key=cycle_key,
                scope_key=scope_key,
                payload_bytes=stored["payload_bytes"],
            )
            return FanoutFetchResult(
                dict(value),
                source,
                request_key,
                cycle_key,
                fetched=True,
                reused=False,
                coordination_status="cross_process_holder_published",
                waited_seconds=max(0.0, waited_seconds),
                prepublished_payload_hash=stored["payload_hash"],
                prepublished_payload_bytes=stored["payload_bytes"],
                prepublished_payload_ref=stored["payload_ref"],
                prepublished_blob_created=stored["created"],
                prepublished_blob_reused=stored["reused"],
                **coordinator_evidence,
            )
        except Exception as exc:
            _write_immutable_json(
                self.cas.root,
                receipt_path,
                {**base_receipt, "status": "error", "error": _error_receipt(exc)},
            )
            raise
        finally:
            self._release_claim(self.cas.root, claim_path, claim_token)

    def _cross_process_fetch(
        self,
        *,
        source: str,
        request_key: str,
        cycle_key: str,
        scope_key: str,
        fetch_fn: Callable[[], Any],
    ) -> FanoutFetchResult:
        source, request_key, cycle_key, scope_key = self._validated_key(
            source,
            request_key,
            cycle_key,
            scope_key,
        )
        receipt_path, claim_path = self._paths(
            source,
            request_key,
            cycle_key,
            scope_key,
        )
        started = self.monotonic_fn()
        key_fields = {
            "source": source,
            "request_key": request_key,
            "cycle_key": cycle_key,
            "scope_key": scope_key,
        }
        while True:
            receipt = self._read_receipt(self.cas.root, receipt_path)
            if receipt is not None:
                return self._result_from_receipt(
                    receipt,
                    **key_fields,
                    waited_seconds=self.monotonic_fn() - started,
                )
            claim_token = self._try_claim(self.cas.root, claim_path, key_fields)
            if claim_token is not None:
                # Recheck after claiming in case another holder published just
                # before releasing its claim.
                receipt = self._read_receipt(self.cas.root, receipt_path)
                if receipt is not None:
                    self._release_claim(self.cas.root, claim_path, claim_token)
                    return self._result_from_receipt(
                        receipt,
                        **key_fields,
                        waited_seconds=self.monotonic_fn() - started,
                    )
                return self._holder_fetch(
                    **key_fields,
                    receipt_path=receipt_path,
                    claim_path=claim_path,
                    claim_token=claim_token,
                    fetch_fn=fetch_fn,
                    waited_seconds=self.monotonic_fn() - started,
                )
            waited = self.monotonic_fn() - started
            if waited >= self.wait_timeout_seconds:
                value = fetch_fn()
                return FanoutFetchResult(
                    value,
                    source,
                    request_key,
                    cycle_key,
                    fetched=True,
                    reused=False,
                    coordination_status="cross_process_wait_timeout_fail_open",
                    waited_seconds=max(0.0, waited),
                    wait_timed_out=True,
                )
            self.sleep_fn(min(self.poll_seconds, self.wait_timeout_seconds - waited))

    @staticmethod
    def _validate_result_cycle(result: FanoutFetchResult) -> FanoutFetchResult:
        value = result.value
        if not isinstance(value, Mapping) or not isinstance(value.get("text"), str):
            raise ForecastPayloadCASIntegrityError(
                "cross-process NBM fan-out result must contain text"
            )
        try:
            bulletin_cycle = nbm_nbp_cycle_key_from_bulletin(value["text"])
        except ForecastPayloadExtractionIdentityError as exc:
            raise ForecastPayloadCASIntegrityError(str(exc)) from exc
        if bulletin_cycle != result.cycle_key:
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out payload does not match the requested NBM cycle"
            )
        return result

    def fetch(
        self,
        *,
        source: str,
        request_key: str,
        cycle_key: str,
        fetch_fn: Callable[[], Any],
        scope_key: str | None = None,
    ) -> FanoutFetchResult:
        if not str(scope_key or "").strip():
            return self._validate_result_cycle(
                self._local.fetch(
                    source=source,
                    request_key=request_key,
                    cycle_key=cycle_key,
                    fetch_fn=fetch_fn,
                    scope_key=scope_key,
                )
            )
        outer = self._local.fetch(
            source=source,
            request_key=request_key,
            cycle_key=cycle_key,
            fetch_fn=lambda: self._cross_process_fetch(
                source=source,
                request_key=request_key,
                cycle_key=cycle_key,
                scope_key=str(scope_key),
                fetch_fn=fetch_fn,
            ),
            scope_key=scope_key,
        )
        inner = outer.value
        if not isinstance(inner, FanoutFetchResult):
            raise ForecastPayloadCASIntegrityError(
                "cross-process fan-out returned an invalid local result"
            )
        if not outer.reused:
            return self._validate_result_cycle(inner)
        return self._validate_result_cycle(
            replace(
                inner,
                fetched=False,
                reused=True,
                coordination_status="same_process_scoped_receipt_reused",
                prepublished_blob_created=False,
                prepublished_blob_reused=bool(inner.prepublished_payload_hash),
            )
        )

    def clear(self) -> None:
        self._local.clear()

    def completed_entry_count(self) -> int:
        return self._local.completed_entry_count()


def fanout_from_environment(
    env: Mapping[str, str] | None = None,
) -> tuple[CrossProcessMarketInvariantFetchFanout | None, str | None]:
    """Build the child-only coordinator from a complete parent env contract."""

    env = os.environ if env is None else env
    cas_root = str(env.get(FANOUT_CAS_ROOT_ENV) or "").strip()
    scope_key = str(env.get(FANOUT_SCOPE_ENV) or "").strip()
    if not cas_root and not scope_key:
        return None, None
    if not cas_root or not scope_key:
        raise RuntimeError(
            "cross-process forecast fan-out requires both CAS root and scope"
        )
    return CrossProcessMarketInvariantFetchFanout(cas_root), scope_key
