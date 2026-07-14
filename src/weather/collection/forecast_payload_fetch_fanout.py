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
from weather.sources.forecast_payload_fanout import (
    FanoutFetchResult,
    MarketInvariantFetchFanout,
)


RECEIPT_SCHEMA_VERSION = "forecast_payload_cross_process_fanout_receipt_v0.1"
FANOUT_CAS_ROOT_ENV = "WEATHER_FORECAST_FANOUT_CAS_ROOT"
FANOUT_SCOPE_ENV = "WEATHER_FORECAST_FANOUT_SCOPE"
DEFAULT_WAIT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_SECONDS = 0.05


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Publish one complete receipt without replacing an existing receipt."""

    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(
        f".{path.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        with staging.open("xb") as handle:
            handle.write(_canonical_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(staging, path)
        except FileExistsError:
            pass
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
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
        identity = _canonical_json_bytes({
            "scope_key": scope_key,
            "source": source,
            "request_key": request_key,
            "cycle_key": cycle_key,
        })
        digest = hashlib.sha256(identity).hexdigest()
        folder = self.cas.root / "fetch_fanout" / "sha256" / digest[:2]
        return folder / f"{digest}.receipt.json", folder / f"{digest}.claim"

    @staticmethod
    def _try_claim(path: Path, key_fields: Mapping[str, str]) -> str | None:
        path.parent.mkdir(parents=True, exist_ok=True)
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
        return token

    @staticmethod
    def _release_claim(path: Path, token: str) -> None:
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

    @staticmethod
    def _read_receipt(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt is unreadable: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ForecastPayloadCASIntegrityError(
                f"cross-process fan-out receipt is not an object: {path}"
            )
        return payload

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
        base_receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "source": source,
            "request_key": request_key,
            "cycle_key": cycle_key,
            "scope_key": scope_key,
        }
        try:
            value = fetch_fn()
            if not isinstance(value, Mapping) or not isinstance(value.get("text"), str):
                raise ForecastPayloadCASIntegrityError(
                    "cross-process NBM fan-out fetch must return a mapping with text"
                )
            payload_bytes = value["text"].encode("utf-8")
            stored = self.cas.put(payload_bytes)
            receipt = {
                **base_receipt,
                "status": "success",
                "fetched_at": value.get("fetched_at"),
                "request_started_at": value.get("request_started_at"),
                "response_received_at": value.get("response_received_at"),
                "payload_hash": stored["payload_hash"],
                "payload_bytes": stored["payload_bytes"],
                "payload_ref": stored["payload_ref"],
            }
            _write_immutable_json(receipt_path, receipt)
            published = self._read_receipt(receipt_path)
            if published != receipt:
                return self._result_from_receipt(
                    published or {},
                    source=source,
                    request_key=request_key,
                    cycle_key=cycle_key,
                    scope_key=scope_key,
                    waited_seconds=waited_seconds,
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
            )
        except Exception as exc:
            _write_immutable_json(
                receipt_path,
                {**base_receipt, "status": "error", "error": _error_receipt(exc)},
            )
            raise
        finally:
            self._release_claim(claim_path, claim_token)

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
            receipt = self._read_receipt(receipt_path)
            if receipt is not None:
                return self._result_from_receipt(
                    receipt,
                    **key_fields,
                    waited_seconds=self.monotonic_fn() - started,
                )
            claim_token = self._try_claim(claim_path, key_fields)
            if claim_token is not None:
                # Recheck after claiming in case another holder published just
                # before releasing its claim.
                receipt = self._read_receipt(receipt_path)
                if receipt is not None:
                    self._release_claim(claim_path, claim_token)
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
            return self._local.fetch(
                source=source,
                request_key=request_key,
                cycle_key=cycle_key,
                fetch_fn=fetch_fn,
                scope_key=scope_key,
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
            return inner
        return replace(
            inner,
            fetched=False,
            reused=True,
            coordination_status="same_process_scoped_receipt_reused",
            prepublished_blob_created=False,
            prepublished_blob_reused=bool(inner.prepublished_payload_hash),
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
