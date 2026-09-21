"""Immutable pilot-envelope definitions and fail-closed profile selection.

These definitions do not grant exchange capability. Stage 1 retains its
original numeric envelope and canonical profile bytes.
Stage 2 selection additionally needs matching, dated grants in the two owning
documents; host, source, attendance and action-time gates remain independent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from weather.paths import REPO_ROOT


@dataclass(frozen=True)
class LiveEnvelope:
    profile_id: str
    per_order_pusd: int
    per_band_pusd: int
    per_event_pusd: int
    daily_loss_pusd: int
    wallet_pusd: int
    max_submits: int
    post_only: bool = True
    no_naked_sell: bool = True
    stop_on_fill: bool = True

    def canonical_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("ascii")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class HoldEnvelope(LiveEnvelope):
    session_seconds: int = 120 * 60
    max_sessions_per_utc_day: int = 4
    max_reward_days: int = 3
    heartbeat_seconds: int = 5
    geoblock_refresh_seconds: int = 45
    public_refresh_seconds: int = 60
    cleanup_seconds: int = 20


STAGE1_V1 = LiveEnvelope("stage1_v1", 10, 10, 25, 25, 100, 1)
STAGE2_HOLD_V1 = HoldEnvelope("stage2_hold_v1", 16, 20, 25, 25, 100, 2)
GRANT_KEY = "stage2_hold_owner_authorization"
GRANT_PREFIX = "Stage 2 owner authorization: "


class EnvelopeNotAuthorized(ValueError):
    """No exact current owner grant exists for the requested envelope."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EnvelopeNotAuthorized("duplicate authorization field")
        result[key] = value
    return result


def _json_object(raw: str) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as exc:
        raise EnvelopeNotAuthorized("invalid authorization JSON") from exc
    if not isinstance(value, dict):
        raise EnvelopeNotAuthorized("authorization must be an object")
    return value


def select_envelope(
    profile_id: str = "stage1_v1",
    *,
    state_of_play_path: Path = REPO_ROOT / "docs/operations/STATE_OF_PLAY.md",
    assignment_path: Path = REPO_ROOT / "config/international_live_execution_host.json",
    now: datetime | None = None,
) -> LiveEnvelope:
    """Select numeric limits, never bypass any live gate or mutate either file.

Stage 2's draft grant format has four exact keys: profile_id, profile_sha256,
authorized_on (ISO date), expires_at_utc. The assignment's GRANT_KEY object
must equal the single GRANT_PREFIX JSON line in the Current authority section.
The two sources must be changed only under a dated owner decision. Selecting
this envelope supplies neither an exchange client nor a submit capability.
"""
    if profile_id == STAGE1_V1.profile_id:
        return STAGE1_V1
    if profile_id != STAGE2_HOLD_V1.profile_id:
        raise EnvelopeNotAuthorized("unknown envelope profile")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise EnvelopeNotAuthorized("current time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    try:
        state = Path(state_of_play_path).read_text(encoding="utf-8")
        assignment = _json_object(Path(assignment_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise EnvelopeNotAuthorized("owner authorization sources unreadable") from exc
    sections = re.findall(r"^## Current authority\s*\n(.*?)(?=^## |\Z)", state, re.MULTILINE | re.DOTALL)
    if len(sections) != 1:
        raise EnvelopeNotAuthorized("one Current authority section is required")
    lines = [line[len(GRANT_PREFIX):] for line in sections[0].splitlines() if line.startswith(GRANT_PREFIX)]
    if len(lines) != 1:
        raise EnvelopeNotAuthorized("Stage 2 has no single dated owner authorization")
    grant = _json_object(lines[0])
    if set(grant) != {"profile_id", "profile_sha256", "authorized_on", "expires_at_utc"}:
        raise EnvelopeNotAuthorized("owner grant fields are not exact")
    if assignment.get(GRANT_KEY) != grant:
        raise EnvelopeNotAuthorized("owner grant differs between state and assignment")
    if grant["profile_id"] != profile_id or grant["profile_sha256"] != STAGE2_HOLD_V1.sha256:
        raise EnvelopeNotAuthorized("owner grant profile/hash mismatch")
    try:
        authorized_on = date.fromisoformat(grant["authorized_on"])
        expires = datetime.fromisoformat(grant["expires_at_utc"].replace("Z", "+00:00"))
        valid = (
            authorized_on.isoformat() == grant["authorized_on"]
            and authorized_on == current.date()
            and expires.tzinfo is not None
            and expires.utcoffset() is not None
            and expires.astimezone(timezone.utc).date() == authorized_on
            and current < expires.astimezone(timezone.utc)
        )
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise EnvelopeNotAuthorized("owner grant date/expiry is not current")
    return STAGE2_HOLD_V1
