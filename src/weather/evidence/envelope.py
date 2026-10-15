"""PL-1 row envelope: availability bases, canonical bytes and UTC text.

Every journal row is attributable (plan §2.4): ``first_seen_utc``, ``provider_time`` or
``run_init``, ``availability_basis``, ``parser_version``, ``raw_ref``, ``config_sha256`` and
``code_manifest_sha``. The basis decides how a point-in-time reader may use the row.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

LIVE_RECEIPT = "live_receipt"
PROVIDER_STAMP = "provider_stamp"
S3_LASTMODIFIED = "s3_lastmodified"
ARCHIVE_PROXY = "archive_proxy"
STITCHED_NO_ISSUE = "stitched_no_issue"
BASES = (LIVE_RECEIPT, PROVIDER_STAMP, S3_LASTMODIFIED, ARCHIVE_PROXY, STITCHED_NO_ISSUE)
# Usable for PIT only as stamp + a declared per-source margin.
STAMPED_BASES = (PROVIDER_STAMP, S3_LASTMODIFIED)
# Never usable for PIT training (labels and referees only).
PIT_REFUSED_BASES = (ARCHIVE_PROXY, STITCHED_NO_ISSUE)
PIT_UNPROVEN_TAG = "HISTORICAL_FIRST_AVAILABILITY_UNPROVEN"

ENVELOPE_FIELDS = ("provider_time", "run_init", "availability_basis", "parser_version", "raw_ref", "event_date")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(text) -> datetime:
    if isinstance(text, datetime):
        value = text
    else:
        value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timestamp without zone")
    return value.astimezone(timezone.utc)


def epoch_utc_text(seconds) -> str | None:
    if seconds is None or isinstance(seconds, bool):
        return None
    try:
        return utc_text(datetime.fromtimestamp(float(seconds), tz=timezone.utc))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def envelope(*, basis: str, parser_version: str, provider_time=None, run_init=None, raw_ref=None,
             event_date=None) -> dict:
    """The family-supplied part of a row envelope; the journal adds the rest."""
    if basis not in BASES:
        raise ValueError(f"unknown availability basis {basis!r}")
    if not parser_version:
        raise ValueError("parser_version is required")
    return {"availability_basis": basis, "parser_version": parser_version, "provider_time": provider_time,
            "run_init": run_init, "raw_ref": raw_ref, "event_date": event_date}
