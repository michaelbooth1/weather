"""Capture-only retention of Toronto (CYYZ/CYTZ) NBM NBP station blocks.

The national NBM NBP bulletin is market-invariant and already downloaded for
the US markets. Toronto has never extracted its own station blocks because the
``nbm_probabilistic_tmax`` source is US-only. When the operator policy in
``config/toronto_nbm_blocks.json`` is enabled, Toronto stores its CYYZ/CYTZ
blocks under a separate source name, ``nbm_toronto_station_blocks``.

That source name is deliberately unknown to the feature builder, so retaining
the blocks is storage only: Toronto serving features, the distribution and
train/serve parity are unchanged. Feeding these blocks to a model is a separate
model decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from weather.forecast_payload_contracts import nbm_nbp_request_key
from weather.paths import config_path
from weather.schema_registry import schema_version
from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax


TORONTO_NBM_BLOCKS_SOURCE = "nbm_toronto_station_blocks"
TORONTO_NBM_BLOCKS_MARKET_ID = "toronto"
POLICY_SCHEMA_VERSION = schema_version("toronto_nbm_blocks_policy")
PAYLOAD_SCHEMA_VERSION = schema_version("nbm_toronto_station_blocks")
DEFAULT_POLICY_PATH = config_path("toronto_nbm_blocks.json")
DEFAULT_RETAIN_TORONTO_NBM_BLOCKS = False
DEFAULT_STATIONS = ("CYYZ", "CYTZ")
# Reuse a same-target-date retained payload this long before fetching again,
# so an unshared Toronto pass cannot re-download the ~35 MB national bulletin
# on every iteration.
TORONTO_NBM_BLOCKS_REUSE_MINUTES = 60
# Fields of the parsed per-station payload that carry the full national
# bulletin; the bulletin itself is retained by the US markets' shared CAS.
_NATIONAL_BODY_FIELDS = ("raw_payload", "tried_urls")


@dataclass(frozen=True)
class TorontoNbmBlocksPolicy:
    retain_toronto_nbm_blocks: bool = DEFAULT_RETAIN_TORONTO_NBM_BLOCKS
    stations: tuple[str, ...] = field(default=DEFAULT_STATIONS)
    status: str = "default_preserve_current_behavior"
    path: str | None = None
    detail: str | None = None

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["stations"] = list(self.stations)
        return data


def _fail_safe(path: Path, detail: str) -> TorontoNbmBlocksPolicy:
    """Missing or ambiguous policy keeps today's behaviour: no retention."""

    return TorontoNbmBlocksPolicy(
        status="invalid_fail_safe_preserve_current_behavior",
        path=str(path),
        detail=detail,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def load_toronto_nbm_blocks_policy(
    path: str | Path = DEFAULT_POLICY_PATH,
) -> TorontoNbmBlocksPolicy:
    path = Path(path)
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except FileNotFoundError:
        return _fail_safe(path, "policy file is missing")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _fail_safe(path, f"{type(exc).__name__}: {exc}")
    if not isinstance(raw, dict):
        return _fail_safe(path, "policy root must be an object")
    if raw.get("schema_version") != POLICY_SCHEMA_VERSION:
        return _fail_safe(path, f"expected schema_version={POLICY_SCHEMA_VERSION}")
    capture = raw.get("capture")
    if not isinstance(capture, dict):
        return _fail_safe(path, "capture policy must be an object")
    enabled = capture.get("retain_toronto_nbm_blocks")
    if not isinstance(enabled, bool):
        return _fail_safe(path, "capture.retain_toronto_nbm_blocks must be a boolean")
    stations = capture.get("stations", list(DEFAULT_STATIONS))
    if (
        not isinstance(stations, list)
        or not stations
        or not all(isinstance(item, str) and item.strip() for item in stations)
    ):
        return _fail_safe(path, "capture.stations must be a non-empty list of station ids")
    return TorontoNbmBlocksPolicy(
        retain_toronto_nbm_blocks=enabled,
        stations=tuple(dict.fromkeys(item.strip().upper() for item in stations)),
        status="configured",
        path=str(path),
    )


def toronto_nbm_blocks_enabled(spec, policy: TorontoNbmBlocksPolicy | None = None) -> bool:
    """True only for the Toronto market with the policy explicitly enabled."""

    if str(getattr(spec, "id", "") or "") != TORONTO_NBM_BLOCKS_MARKET_ID:
        return False
    policy = policy or load_toronto_nbm_blocks_policy()
    return bool(policy.retain_toronto_nbm_blocks)


def toronto_station_blocks_payload(
    text: str,
    stations,
    target_date: date | str,
    *,
    source_url: str,
    fetched_at: str | None,
    cycle_key: str,
    policy: TorontoNbmBlocksPolicy | None = None,
) -> dict[str, Any]:
    """Extract and retain the named station blocks from one national bulletin.

    The returned ``raw_payload`` holds only the station blocks plus the
    national bulletin's identity (request key, cycle key, SHA-1 body hash used
    by the NBP raw payload), so it is a small local forecast payload rather
    than a second copy of the national bulletin.
    """

    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    station_payloads: dict[str, Any] = {}
    raw_blocks: dict[str, str] = {}
    for station_id in stations:
        parsed = parse_nbp_station_tmax(
            text,
            station_id,
            target_date,
            source_url=source_url,
            fetched_at=fetched_at,
        )
        block = parsed.get("raw_station_block") or ""
        raw_blocks[station_id] = block
        station_payloads[station_id] = {
            key: value
            for key, value in parsed.items()
            if key not in _NATIONAL_BODY_FIELDS
        }
    national = {
        "source_url": source_url,
        "request_key": nbm_nbp_request_key(source_url),
        "cycle_key": cycle_key,
        "payload_hash": hashlib.sha1(
            str(text or "").encode("utf-8", errors="replace")
        ).hexdigest(),
        "payload_bytes": len(str(text or "").encode("utf-8")),
    }
    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "source": TORONTO_NBM_BLOCKS_SOURCE,
        "available": any(bool(block) for block in raw_blocks.values()),
        "capture_only": True,
        "feeds_features": False,
        "target_date": target_date.isoformat(),
        "fetched_at": fetched_at,
        "stations_requested": list(stations),
        "stations_found": [station for station, block in raw_blocks.items() if block],
        "stations": station_payloads,
        "national_bulletin": national,
        "policy": (policy.payload() if policy is not None else None),
        "raw_payload": {
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "source": TORONTO_NBM_BLOCKS_SOURCE,
            "source_kind": "nbp_station_blocks",
            "target_date": target_date.isoformat(),
            "fetched_at": fetched_at,
            "national_bulletin": national,
            "station_blocks": raw_blocks,
        },
    }
