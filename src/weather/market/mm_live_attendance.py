"""One exact typed attestation for a sealed attended session; no I/O at import."""

from __future__ import annotations

import hashlib
import re

from weather.market.mm_geographic_eligibility import PHYSICAL_LOCATION_CONFIRMATION


def session_confirmation_literal(stage_confirmation: str, scope_sha256: str) -> str:
    if not re.fullmatch(r"INTERNATIONAL_POLYMARKET_[A-Z0-9_]+", stage_confirmation):
        raise ValueError("invalid session confirmation stage")
    if not re.fullmatch(r"[a-f0-9]{64}", scope_sha256):
        raise ValueError("invalid displayed session scope hash")
    return f"{stage_confirmation} {scope_sha256} {PHYSICAL_LOCATION_CONFIRMATION}"


def confirm_attended_session(stage_confirmation, scope_sha256, *, read_input=None):
    """Read once, before credentials; wrong or missing input fails closed."""
    expected = session_confirmation_literal(stage_confirmation, scope_sha256)
    supplied = (read_input or input)(
        "Review the displayed sealed session. Confirm the stage, scope and physical "
        "eligibility without circumvention by typing exactly:\n" + expected + "\n> "
    )
    if supplied != expected:
        raise RuntimeError("sealed session confirmation did not match")
    return {
        "authorization_method": "typed_session_confirmation",
        "scope_sha256": scope_sha256,
        "literal_sha256": hashlib.sha256(expected.encode("ascii")).hexdigest(),
        "physical_location_eligible": True,
        "no_circumvention": True,
    }
