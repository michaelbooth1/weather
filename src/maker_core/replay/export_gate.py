"""The panel export gate for maker replay v2 (owner decision 3, Swarm M 2026-10-06).

The ``maker-replay-v2-v1`` registration draft says that no panel or settlement-only date's 88a data may be
exported or read before it is signed. This module makes that rule code: every export entry point calls
``export_permitted`` as its **first statement**, before it opens any input, creates any output or touches a
ledger or lock.

- **Gated days** are the registration's panel window: quote dates 2026-09-30..2026-10-13 plus the settlement-only
  dates 2026-10-14 and 2026-10-15, i.e. every UTC day from 2026-09-30 through 2026-10-15 inclusive.
- **UTC-day boundaries.** A day is a UTC calendar date. Day ``d`` is gated when its UTC interval
  ``[d 00:00:00Z, d+1 00:00:00Z)`` lies inside ``[GATE_FIRST_UTC, GATE_END_UTC)``. A ``datetime`` is refused rather
  than silently truncated, because a local-time instant could name the wrong UTC day.
- **Authorization.** A gated day passes only when the signed ``maker-replay-v2-v1`` authorization verifies. While
  ``SIGNED_REGISTRATION_SHA256`` is ``None`` (unsigned), nothing can verify, so every gated day is refused.
  Signing is a reviewed code change that sets this constant and lands the v2 authorization verifier (unit U4).
- **No override.** There is no parameter, environment variable or flag that skips the gate.

Days outside the window (for example the calibration dates and 2026-10-16 onward) pass this gate and meet the
exporter's own checks next.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from maker_core.replay.bundle import BundleError

AUTHORIZATION_ID = "maker-replay-v2-v1"
GATE_FIRST_UTC = datetime(2026, 9, 30, tzinfo=timezone.utc)
GATE_END_UTC = datetime(2026, 10, 16, tzinfo=timezone.utc)  # exclusive: 2026-10-15 is the last gated UTC day
GATED_DAYS = frozenset(date(2026, 9, 30) + timedelta(days=n) for n in range((GATE_END_UTC - GATE_FIRST_UTC).days))
# The SHA-256 of the signed registration text. None until the owner signs; then every gated day still needs a
# verified owner decision through the v2 authorization verifier.
SIGNED_REGISTRATION_SHA256: str | None = None

REFUSAL_CODES = (
    "export_gate_day_required",
    "export_gate_noncanonical_day",
    "panel_export_requires_signed_registration",
    "panel_export_requires_owner_decision",
    "panel_export_authorization_unavailable",
    "panel_export_authorization_refused",
)


def utc_day(day) -> date:
    """The UTC calendar date named by ``day`` (a ``date`` or a canonical ``YYYY-MM-DD`` string)."""
    if isinstance(day, datetime):
        raise BundleError("export_gate_day_required")
    if isinstance(day, date):
        return day
    if not isinstance(day, str):
        raise BundleError("export_gate_day_required")
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise BundleError("export_gate_noncanonical_day") from None
    if parsed.isoformat() != day:
        # date.fromisoformat also accepts e.g. "20260930"; a gate must not depend on the spelling.
        raise BundleError("export_gate_noncanonical_day")
    return parsed


def gated(day) -> bool:
    """True when the whole UTC day lies inside the registration's panel window."""
    start = datetime.combine(utc_day(day), datetime.min.time(), tzinfo=timezone.utc)
    return GATE_FIRST_UTC <= start and start + timedelta(days=1) <= GATE_END_UTC


def export_permitted(day, owner_decision=None, *, now=None) -> date:
    """Return the UTC day if it may be exported; otherwise raise ``BundleError`` before anything is opened."""
    parsed = utc_day(day)
    if not gated(parsed):
        return parsed
    if SIGNED_REGISTRATION_SHA256 is None:
        raise BundleError("panel_export_requires_signed_registration")
    if owner_decision is None:
        raise BundleError("panel_export_requires_owner_decision")
    try:
        from maker_core.replay.v2 import authorization
        verify = authorization.verify_export_decision
    except (ImportError, AttributeError):
        raise BundleError("panel_export_authorization_unavailable") from None
    now = now or datetime.now(timezone.utc)
    if verify(owner_decision, authorization_id=AUTHORIZATION_ID, registration_sha256=SIGNED_REGISTRATION_SHA256,
              day=parsed, now=now) is not True:
        raise BundleError("panel_export_authorization_refused")
    return parsed
