"""Replay identity contracts for shared market-invariant forecast payloads."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Mapping


NBM_NBP_SOURCE = "nbm_probabilistic_tmax"
NBM_NBP_EXTRACTION_SCHEMA = "nbm_nbp_station_target_v1"
NBM_NBP_MEDIA_TYPE = "text/plain; charset=utf-8"
NBM_NBP_ENCODING = "utf-8"
_NBM_STATION_RE = re.compile(r"^[A-Z0-9]{3,5}$")


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
