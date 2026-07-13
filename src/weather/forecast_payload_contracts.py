"""Replay identity contracts for shared market-invariant forecast payloads."""

from __future__ import annotations

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
