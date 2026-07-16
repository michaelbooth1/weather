"""Replay identity contracts for shared market-invariant forecast payloads."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Mapping


NBM_NBP_SOURCE = "nbm_probabilistic_tmax"
NBM_NBP_EXTRACTION_SCHEMA = "nbm_nbp_station_target_v1"
NBM_NBP_MEDIA_TYPE = "text/plain; charset=utf-8"
NBM_NBP_ENCODING = "utf-8"
MAX_FANOUT_COORDINATOR_ATTRIBUTIONS = 32
_NBM_STATION_RE = re.compile(r"^[A-Z0-9]{3,5}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NBM_NBP_HEADER_RE = re.compile(
    r"^\s*[A-Z0-9]{3,5}\s+NBM\s+V\S+\s+NBP\s+GUIDANCE\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<hour>\d{4})\s+UTC\b",
    re.IGNORECASE | re.MULTILINE,
)


class ForecastPayloadExtractionIdentityError(ValueError):
    """A shared payload cannot be replayed for its declared extraction."""


def nbm_nbp_request_key(source_url: str) -> str:
    """Return the exact request identity for one national NBM bulletin."""

    source_url = str(source_url or "").strip()
    if not source_url:
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload requires a source_url"
        )
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return f"{NBM_NBP_SOURCE}:GET:sha256:{digest}"


def nbm_nbp_cycle_key_from_url(source_url: str) -> str:
    """Derive the provider-cycle identity from the exact request URL."""

    source_url = str(source_url or "").strip()
    if not source_url:
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload requires a source_url"
        )
    match = re.search(
        r"/blend\.(?P<day>\d{8})/(?P<hour>\d{2})/",
        source_url,
    )
    if match:
        return f"nbm-nbp:{match.group('day')}T{match.group('hour')}Z"
    # Retained archives and controlled mirrors may use a stable URL without the
    # NOMADS date folder. Keep that identity request-specific so it cannot
    # collide with a dated operational cycle.
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return f"nbm-nbp:url-sha256:{digest}"


def nbm_nbp_cycle_key_from_bulletin(text: str) -> str:
    """Derive one unambiguous provider cycle from NBM bulletin headers."""

    cycles: set[str] = set()
    for match in _NBM_NBP_HEADER_RE.finditer(str(text or "")):
        try:
            issue_time = datetime.strptime(
                f"{match.group('date')} {match.group('hour')}",
                "%m/%d/%Y %H%M",
            ).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ForecastPayloadExtractionIdentityError(
                "NBM bulletin contains an invalid issue time"
            ) from exc
        if issue_time.minute != 0:
            raise ForecastPayloadExtractionIdentityError(
                "NBM bulletin issue time is not an hourly provider cycle"
            )
        cycles.add(f"nbm-nbp:{issue_time.strftime('%Y%m%dT%HZ')}")
    if not cycles:
        raise ForecastPayloadExtractionIdentityError(
            "NBM bulletin does not contain a semantic provider cycle"
        )
    if len(cycles) != 1:
        raise ForecastPayloadExtractionIdentityError(
            "NBM bulletin contains inconsistent semantic provider cycles"
        )
    return next(iter(cycles))


def forecast_fanout_coordination_id(
    *,
    source: str,
    request_key: str,
    cycle_key: str,
    scope_key: str,
) -> str:
    """Return the stable identity for one cross-process fetch decision."""

    fields = {
        "scope_key": str(scope_key or "").strip(),
        "source": str(source or "").strip(),
        "request_key": str(request_key or "").strip(),
        "cycle_key": str(cycle_key or "").strip(),
    }
    if not all(fields.values()):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordination identity is incomplete"
        )
    encoded = (
        json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def forecast_fanout_receipt_ref(coordination_id: str) -> str:
    """Return the canonical shared-CAS receipt reference for an identity."""

    coordination_id = str(coordination_id or "").lower().strip()
    if not _SHA256_RE.fullmatch(coordination_id):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordination identity is not a SHA-256 digest"
        )
    return (
        f"fetch_fanout/sha256/{coordination_id[:2]}/"
        f"{coordination_id}.receipt.json"
    )


_FANOUT_COORDINATOR_IMMUTABLE_FIELDS = (
    "coordinator_receipt_ref",
    "coordinator_receipt_sha256",
    "source",
    "request_key",
    "cycle_key",
    "scope_key",
    "network_fetch_count",
    "payload_blob_created",
    "payload_blob_reused",
    "physical_bytes_written",
    "payload_hash",
    "payload_bytes",
)


def validate_fanout_coordinator_attribution(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one bounded, receipt-owned accounting attribution record."""

    if not isinstance(value, Mapping):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator attribution must be an object"
        )
    source = str(value.get("source") or "").strip()
    request_key = str(value.get("request_key") or "").strip()
    cycle_key = str(value.get("cycle_key") or "").strip()
    scope_key = str(value.get("scope_key") or "").strip()
    if source != NBM_NBP_SOURCE:
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator attribution source is invalid"
        )
    expected_id = forecast_fanout_coordination_id(
        source=source,
        request_key=request_key,
        cycle_key=cycle_key,
        scope_key=scope_key,
    )
    evidence_id = str(value.get("coordinator_evidence_id") or "").strip()
    receipt_ref = str(value.get("coordinator_receipt_ref") or "").strip()
    receipt_sha256 = str(
        value.get("coordinator_receipt_sha256") or ""
    ).lower().strip()
    if evidence_id != expected_id or receipt_ref != forecast_fanout_receipt_ref(
        expected_id
    ):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator attribution identity mismatch"
        )
    if not _SHA256_RE.fullmatch(receipt_sha256):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator receipt hash is invalid"
        )
    network_fetch_count = value.get("network_fetch_count")
    physical_bytes = value.get("physical_bytes_written")
    payload_bytes = value.get("payload_bytes")
    logical_bytes = value.get("logical_referenced_bytes")
    created = value.get("payload_blob_created")
    reused = value.get("payload_blob_reused")
    if type(network_fetch_count) is not int or network_fetch_count != 1:
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator network-fetch count is invalid"
        )
    if (
        type(physical_bytes) is not int
        or physical_bytes < 0
        or type(payload_bytes) is not int
        or payload_bytes < 0
        or type(logical_bytes) is not int
        or logical_bytes < 0
    ):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator byte attribution is invalid"
        )
    if type(created) is not bool or type(reused) is not bool or created == reused:
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator blob attribution is invalid"
        )
    if physical_bytes != (payload_bytes if created else 0):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator physical-write attribution mismatch"
        )
    payload_hash = str(value.get("payload_hash") or "").lower().strip()
    if not _SHA256_RE.fullmatch(payload_hash):
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator payload hash is invalid"
        )
    return {
        "coordinator_evidence_id": expected_id,
        "coordinator_receipt_ref": receipt_ref,
        "coordinator_receipt_sha256": receipt_sha256,
        "source": source,
        "request_key": request_key,
        "cycle_key": cycle_key,
        "scope_key": scope_key,
        "network_fetch_count": network_fetch_count,
        "payload_blob_created": created,
        "payload_blob_reused": reused,
        "physical_bytes_written": physical_bytes,
        "payload_hash": payload_hash,
        "payload_bytes": payload_bytes,
        "logical_referenced_bytes": logical_bytes,
    }


def deduplicate_fanout_coordinator_attributions(
    values: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    """Return exact-id-deduplicated records or fail on conflicting evidence."""

    grouped: dict[str, dict[str, Any]] = {}
    immutable: dict[str, tuple[Any, ...]] = {}
    for raw in values:
        row = validate_fanout_coordinator_attribution(raw)
        evidence_id = row["coordinator_evidence_id"]
        signature = tuple(row[field] for field in _FANOUT_COORDINATOR_IMMUTABLE_FIELDS)
        previous = immutable.setdefault(evidence_id, signature)
        if previous != signature:
            raise ForecastPayloadExtractionIdentityError(
                "forecast fan-out coordinator attribution conflicts across records"
            )
        if evidence_id not in grouped:
            grouped[evidence_id] = dict(row)
        else:
            grouped[evidence_id]["logical_referenced_bytes"] += row[
                "logical_referenced_bytes"
            ]
    if len(grouped) > MAX_FANOUT_COORDINATOR_ATTRIBUTIONS:
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out coordinator attribution bound exceeded"
        )
    return [grouped[key] for key in sorted(grouped)]


def fanout_coordinator_attribution_totals(
    values: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> dict[str, int]:
    """Return exact-once coordinator totals for a validated record set."""

    rows = deduplicate_fanout_coordinator_attributions(values)
    physical = sum(row["physical_bytes_written"] for row in rows)
    logical = sum(row["logical_referenced_bytes"] for row in rows)
    if physical > logical:
        raise ForecastPayloadExtractionIdentityError(
            "forecast fan-out physical bytes exceed referenced bytes"
        )
    return {
        "coordinator_evidence_count": len(rows),
        "network_fetch_count": sum(row["network_fetch_count"] for row in rows),
        "physical_bytes_written": physical,
        "logical_referenced_bytes": logical,
        "avoided_bytes": logical - physical,
    }


def validate_forecast_extraction_identity(
    source: str,
    extraction_schema: str,
    identity: Mapping[str, Any] | None,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return a normalized, source-specific replay identity or fail closed."""

    source = str(source or "").strip()
    extraction_schema = str(extraction_schema or "").strip()
    if source != NBM_NBP_SOURCE:
        raise ForecastPayloadExtractionIdentityError(
            f"no shared forecast extraction contract is registered for source: {source!r}"
        )
    if extraction_schema != NBM_NBP_EXTRACTION_SCHEMA:
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload requires the registered station/target extraction schema"
        )
    if not isinstance(identity, Mapping):
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload extraction identity must be an object"
        )

    station_id = str(identity.get("station_id") or "").upper().strip()
    target_date = str(identity.get("target_date") or "").strip()
    if not _NBM_STATION_RE.fullmatch(station_id):
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload extraction identity requires a valid station_id"
        )
    try:
        normalized_target_date = date.fromisoformat(target_date).isoformat()
    except ValueError as exc:
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload extraction identity requires an ISO target_date"
        ) from exc

    if isinstance(payload, Mapping):
        payload_station = str(payload.get("station_id") or "").upper().strip()
        payload_target = str(payload.get("target_date") or "").strip()
        if payload_station and payload_station != station_id:
            raise ForecastPayloadExtractionIdentityError(
                "NBM payload station_id does not match its extraction identity"
            )
        if payload_target and payload_target != normalized_target_date:
            raise ForecastPayloadExtractionIdentityError(
                "NBM payload target_date does not match its extraction identity"
            )

    return {
        "station_id": station_id,
        "target_date": normalized_target_date,
    }


def validate_nbm_shared_payload_identity(
    *,
    source: str,
    source_url: str,
    request_key: str,
    cycle_key: str,
    extraction_schema: str,
    extraction_identity: Mapping[str, Any] | None,
    target_date: str | None = None,
    expected_station_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Validate the complete NBM request/cycle and market extraction identity."""

    source = str(source or "").strip()
    if source != NBM_NBP_SOURCE:
        raise ForecastPayloadExtractionIdentityError(
            f"no shared NBM identity contract is registered for source: {source!r}"
        )
    source_url = str(source_url or "").strip()
    expected_request_key = nbm_nbp_request_key(source_url)
    expected_cycle_key = nbm_nbp_cycle_key_from_url(source_url)
    if str(request_key or "").strip() != expected_request_key:
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload request_key does not match source_url"
        )
    if str(cycle_key or "").strip() != expected_cycle_key:
        raise ForecastPayloadExtractionIdentityError(
            "NBM shared payload cycle_key does not match source_url"
        )

    identity = validate_forecast_extraction_identity(
        source,
        extraction_schema,
        extraction_identity,
        payload=payload,
    )
    declared_target_date = str(target_date or "").strip()
    if declared_target_date and declared_target_date != identity["target_date"]:
        raise ForecastPayloadExtractionIdentityError(
            "NBM manifest target_date does not match its extraction identity"
        )
    expected_station_id = str(expected_station_id or "").upper().strip()
    if expected_station_id and identity["station_id"] != expected_station_id:
        raise ForecastPayloadExtractionIdentityError(
            "NBM extraction station_id does not match its market registry station"
        )
    return identity
