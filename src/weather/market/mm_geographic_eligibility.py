"""Fail-closed geographic eligibility evidence for International live mutation.

The official public response includes the caller's source address.  This module
uses that value only to validate the response shape and deliberately omits it
from every durable receipt.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from weather.schema_registry import schema_version


GEOBLOCK_ENDPOINT = "https://polymarket.com/api/geoblock"
RECEIPT_SCHEMA_VERSION = schema_version("mm_geographic_eligibility_receipt")
PHYSICAL_LOCATION_CONFIRMATION = (
    "INTERNATIONAL_POLYMARKET_PHYSICALLY_PRESENT_IN_ELIGIBLE_JURISDICTION_"
    "NO_VPN_PROXY_REMOTE_HOST_OR_CIRCUMVENTION"
)
MAX_RECEIPT_AGE_SECONDS = 60
MAX_RESPONSE_BYTES = 16 * 1024
REQUEST_TIMEOUT_SECONDS = 10.0
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
REGION_RE = re.compile(r"^[A-Z0-9-]{0,32}$")


class GeographicEligibilityError(RuntimeError):
    """Raised when exact fresh public and attended eligibility do not pass."""

    def __init__(self, blocker_code: str):
        super().__init__(f"geographic eligibility blocked: {blocker_code}")
        self.blocker_code = blocker_code


class _PublicCheckFailure(RuntimeError):
    def __init__(
        self,
        blocker_code: str,
        *,
        response_binding: Mapping[str, Any] | None = None,
    ):
        super().__init__(blocker_code)
        self.blocker_code = blocker_code
        self.response_binding = (
            dict(response_binding) if response_binding is not None else None
        )


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return _canonical_digest(
        {key: value for key, value in payload.items() if key != "receipt_payload_sha256"}
    )


def _utc_now(clock: Callable[[], datetime] | None) -> datetime:
    current = clock() if clock is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise GeographicEligibilityError("CLOCK_NOT_UTC_AWARE")
    return current.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise GeographicEligibilityError(f"{label}_INVALID") from exc
    if parsed.tzinfo is None:
        raise GeographicEligibilityError(f"{label}_INVALID")
    return parsed.astimezone(timezone.utc)


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise GeographicEligibilityError("RECEIPT_NAMESPACE_NOT_NEW") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # A partial receipt spends the attempt namespace and must be reviewed.
        raise


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None:
        getter = getattr(response, "getcode", None)
        status = getter() if callable(getter) else None
    return status if type(status) is int else None


def _response_content_type(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    value = getter("Content-Type") if callable(getter) else None
    if not isinstance(value, str):
        return None
    return value.split(";", 1)[0].strip().lower()


def _response_final_url(response: Any) -> str | None:
    getter = getattr(response, "geturl", None)
    value = getter() if callable(getter) else None
    return value if isinstance(value, str) else None


def _fetch_official(
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(timeout_seconds, bool) or not 0 < float(timeout_seconds) <= 30:
        raise GeographicEligibilityError("REQUEST_TIMEOUT_INVALID")
    request = Request(
        GEOBLOCK_ENDPOINT,
        method="GET",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": "weather-international-live-geography-gate/1",
        },
    )
    open_request = opener or urlopen
    response = None
    try:
        response = open_request(request, timeout=float(timeout_seconds))
        status = _response_status(response)
        content_type = _response_content_type(response)
        final_url = _response_final_url(response)
        if status != 200 or final_url != GEOBLOCK_ENDPOINT:
            raise _PublicCheckFailure("PUBLIC_CHECK_UNAVAILABLE")
        try:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except Exception as exc:
            raise _PublicCheckFailure("PUBLIC_CHECK_UNAVAILABLE") from exc
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RESPONSE_BYTES:
            raise _PublicCheckFailure("MALFORMED_OFFICIAL_RESPONSE")
        binding = {
            "body_bytes": len(raw),
            "content_type": content_type,
            "final_url": final_url,
            "http_status": status,
        }
        if content_type != "application/json":
            raise _PublicCheckFailure(
                "MALFORMED_OFFICIAL_RESPONSE", response_binding=binding
            )
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _PublicCheckFailure(
                "MALFORMED_OFFICIAL_RESPONSE", response_binding=binding
            ) from exc
        if not isinstance(decoded, dict) or set(decoded) != {
            "blocked",
            "country",
            "ip",
            "region",
        }:
            raise _PublicCheckFailure(
                "MALFORMED_OFFICIAL_RESPONSE", response_binding=binding
            )
        blocked = decoded["blocked"]
        country = decoded["country"]
        region = decoded["region"]
        source_address = decoded["ip"]
        if not (
            type(blocked) is bool
            and isinstance(country, str)
            and COUNTRY_RE.fullmatch(country) is not None
            and isinstance(region, str)
            and REGION_RE.fullmatch(region) is not None
            and isinstance(source_address, str)
        ):
            raise _PublicCheckFailure(
                "MALFORMED_OFFICIAL_RESPONSE", response_binding=binding
            )
        try:
            ipaddress.ip_address(source_address)
        except ValueError as exc:
            raise _PublicCheckFailure(
                "MALFORMED_OFFICIAL_RESPONSE", response_binding=binding
            ) from exc
        official = {
            "blocked": blocked,
            "country": country,
            "region": region,
        }
        # Bind the decision without retaining a reversible commitment to the
        # source IP contained in the raw official response.
        binding["redacted_body_sha256"] = _canonical_digest(official)
        official["decision_sha256"] = _canonical_digest(official)
        return official, binding
    except _PublicCheckFailure:
        raise
    except Exception as exc:
        raise _PublicCheckFailure("PUBLIC_CHECK_UNAVAILABLE") from exc
    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            closer()


def validate_geographic_eligibility_receipt(
    receipt: Mapping[str, Any],
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    """Validate a successful receipt without contacting the public endpoint."""

    expected_keys = {
        "agreement",
        "blocker_code",
        "checked_at_utc",
        "eligible",
        "endpoint",
        "fresh_until_utc",
        "freshness_max_age_seconds",
        "official",
        "operator_attestation",
        "privacy",
        "receipt_payload_sha256",
        "response_binding",
        "schema_version",
        "status",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != expected_keys:
        raise GeographicEligibilityError("RECEIPT_SHAPE_INVALID")
    if not (
        receipt.get("schema_version") == RECEIPT_SCHEMA_VERSION
        and receipt.get("status") == "PASS"
        and receipt.get("endpoint") == GEOBLOCK_ENDPOINT
        and receipt.get("eligible") is True
        and receipt.get("agreement") is True
        and receipt.get("blocker_code") is None
        and type(receipt.get("freshness_max_age_seconds")) is int
        and receipt["freshness_max_age_seconds"] == MAX_RECEIPT_AGE_SECONDS
        and SHA256_RE.fullmatch(str(receipt.get("receipt_payload_sha256") or ""))
        is not None
        and receipt["receipt_payload_sha256"] == _payload_digest(receipt)
    ):
        raise GeographicEligibilityError("RECEIPT_CONTENT_INVALID")
    official = receipt.get("official")
    if not isinstance(official, Mapping) or set(official) != {
        "blocked",
        "country",
        "decision_sha256",
        "region",
    }:
        raise GeographicEligibilityError("OFFICIAL_DECISION_INVALID")
    decision = {
        "blocked": official.get("blocked"),
        "country": official.get("country"),
        "region": official.get("region"),
    }
    if not (
        decision["blocked"] is False
        and isinstance(decision["country"], str)
        and COUNTRY_RE.fullmatch(decision["country"]) is not None
        and isinstance(decision["region"], str)
        and REGION_RE.fullmatch(decision["region"]) is not None
        and official.get("decision_sha256") == _canonical_digest(decision)
    ):
        raise GeographicEligibilityError("OFFICIAL_DECISION_INVALID")
    binding = receipt.get("response_binding")
    if not isinstance(binding, Mapping) or set(binding) != {
        "body_bytes",
        "content_type",
        "final_url",
        "http_status",
        "redacted_body_sha256",
    }:
        raise GeographicEligibilityError("RESPONSE_BINDING_INVALID")
    if not (
        type(binding.get("body_bytes")) is int
        and 0 < binding["body_bytes"] <= MAX_RESPONSE_BYTES
        and SHA256_RE.fullmatch(
            str(binding.get("redacted_body_sha256") or "")
        )
        is not None
        and binding.get("redacted_body_sha256")
        == _canonical_digest(decision)
        and binding.get("content_type") == "application/json"
        and binding.get("final_url") == GEOBLOCK_ENDPOINT
        and binding.get("http_status") == 200
    ):
        raise GeographicEligibilityError("RESPONSE_BINDING_INVALID")
    attestation = receipt.get("operator_attestation")
    if not isinstance(attestation, Mapping) or set(attestation) != {
        "confirmation",
        "no_circumvention",
        "physical_location_eligible",
    }:
        raise GeographicEligibilityError("OPERATOR_ATTESTATION_INVALID")
    if not (
        attestation.get("confirmation") == PHYSICAL_LOCATION_CONFIRMATION
        and attestation.get("physical_location_eligible") is True
        and attestation.get("no_circumvention") is True
        and receipt.get("privacy") == {
            "source_address_retained": False,
            "secret_values_retained": False,
        }
    ):
        raise GeographicEligibilityError("OPERATOR_ATTESTATION_INVALID")
    checked = _parse_utc(receipt.get("checked_at_utc"), label="CHECKED_AT_UTC")
    fresh_until = _parse_utc(
        receipt.get("fresh_until_utc"), label="FRESH_UNTIL_UTC"
    )
    if fresh_until != checked + timedelta(seconds=MAX_RECEIPT_AGE_SECONDS):
        raise GeographicEligibilityError("RECEIPT_FRESHNESS_INVALID")
    if require_fresh:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if current < checked or current > fresh_until:
            raise GeographicEligibilityError("RECEIPT_STALE")
    return dict(receipt)


def check_geographic_eligibility(
    receipt_out: str | Path,
    *,
    confirmation: str,
    physical_location_eligible: bool,
    no_circumvention: bool,
    opener: Callable[..., Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the exact official public check, write one receipt, and fail closed."""

    output = Path(receipt_out).resolve()
    if output.exists():
        raise GeographicEligibilityError("RECEIPT_NAMESPACE_NOT_NEW")
    checked = _utc_now(clock)
    attestation = {
        "confirmation": confirmation,
        "no_circumvention": no_circumvention,
        "physical_location_eligible": physical_location_eligible,
    }
    official: dict[str, Any] | None = None
    response_binding: dict[str, Any] | None = None
    blocker_code: str | None = None
    if not (
        confirmation == PHYSICAL_LOCATION_CONFIRMATION
        and type(physical_location_eligible) is bool
        and type(no_circumvention) is bool
    ):
        blocker_code = "OPERATOR_ATTESTATION_INVALID"
    else:
        try:
            official, response_binding = _fetch_official(
                opener=opener,
                timeout_seconds=timeout_seconds,
            )
        except _PublicCheckFailure as exc:
            blocker_code = exc.blocker_code
            response_binding = exc.response_binding
    agreement = bool(
        official is not None
        and type(physical_location_eligible) is bool
        and (not official["blocked"]) is physical_location_eligible
    )
    if blocker_code is None:
        if official is None or response_binding is None:
            blocker_code = "PUBLIC_CHECK_UNAVAILABLE"
        elif official["blocked"] is True:
            blocker_code = "OFFICIAL_LOCATION_BLOCKED"
        elif physical_location_eligible is not True:
            blocker_code = "PUBLIC_PHYSICAL_LOCATION_DISAGREEMENT"
        elif no_circumvention is not True:
            blocker_code = "CIRCUMVENTION_NOT_REFUSED"
    eligible = blocker_code is None and agreement is True
    payload: dict[str, Any] = {
        "agreement": agreement,
        "blocker_code": blocker_code,
        "checked_at_utc": _iso_utc(checked),
        "eligible": eligible,
        "endpoint": GEOBLOCK_ENDPOINT,
        "fresh_until_utc": _iso_utc(
            checked + timedelta(seconds=MAX_RECEIPT_AGE_SECONDS)
        ),
        "freshness_max_age_seconds": MAX_RECEIPT_AGE_SECONDS,
        "official": official,
        "operator_attestation": attestation,
        "privacy": {
            "source_address_retained": False,
            "secret_values_retained": False,
        },
        "receipt_payload_sha256": None,
        "response_binding": response_binding,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "PASS" if eligible else "FAIL",
    }
    payload["receipt_payload_sha256"] = _payload_digest(payload)
    _write_new_json(output, payload)
    if not eligible:
        raise GeographicEligibilityError(str(blocker_code))
    return validate_geographic_eligibility_receipt(
        payload,
        now=checked,
        require_fresh=True,
    )
