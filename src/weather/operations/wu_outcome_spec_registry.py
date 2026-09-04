"""Exact immutable specifications admitted by the WU outcome exporter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


ORIGINAL_SPEC_RELATIVE = PurePosixPath(
    "docs/roadmap/wu-outcome-gap-production-export-spec-2026-09-100a.json"
)
ORIGINAL_SPEC_FILE_SHA256 = (
    "cf10553a9b041a783bf5caf56b191835e2904474a4bad34dcbc1f6ad934d093f"
)
ORIGINAL_SPEC_SELF_SHA256 = (
    "5d370c51da7d95e1d3a62a8ff4f9d66cd3312c5eecfebcbdbaab169be505e0f9"
)
ADMISSIBLE_SPEC_RELATIVE = PurePosixPath(
    "docs/roadmap/wu-outcome-admissible-gap-production-export-spec-2026-09-100g.json"
)
ADMISSIBLE_SPEC_FILE_SHA256 = (
    "d540a5dc43845f87e811aca7670e86f5eada3f5ba8476dd1bdc2aef80bd3518c"
)
ADMISSIBLE_SPEC_SELF_SHA256 = (
    "6f02e1dcc077c69037017137725931e94d4fd652da976affda12a2109bb67407"
)
ADMISSIBLE_SPEC_MISSION_ID = (
    "workstation-wu-outcome-admissible-gap-spec-2026-09-100g"
)

TRACKED_GAP_FILE_SHA256 = (
    "6ba020575e3ef1eb903ae0010510caea20f31b31bdf3451c0e03f11175c3de94"
)
TRACKED_GAP_SELF_SHA256 = (
    "64176a727907c8f62c496f6fb1893c1f7462cfef15c1db3f06ef7b3e244f0ce8"
)

REQUEST_KEY_FIELDS = frozenset(
    {
        "local_status",
        "market",
        "provenance_side",
        "settlement_unit",
        "station",
        "target_date",
    }
)
LOW_SUPPORT_KEYS = (
    (
        "atlanta",
        "2026-06-06",
        "katl",
        "F",
        "pre_boundary",
        "present_below_threshold",
    ),
    (
        "miami",
        "2026-06-06",
        "kmia",
        "F",
        "pre_boundary",
        "present_below_threshold",
    ),
)


@dataclass(frozen=True)
class FrozenSpecRegistration:
    relative_path: PurePosixPath
    file_sha256: str
    self_sha256: str
    requested_rows: int
    status_counts: tuple[tuple[str, int], ...]
    low_support_in_request: bool


FROZEN_SPEC_REGISTRY = {
    ORIGINAL_SPEC_RELATIVE: FrozenSpecRegistration(
        relative_path=ORIGINAL_SPEC_RELATIVE,
        file_sha256=ORIGINAL_SPEC_FILE_SHA256,
        self_sha256=ORIGINAL_SPEC_SELF_SHA256,
        requested_rows=96,
        status_counts=(("missing", 94), ("present_below_threshold", 2)),
        low_support_in_request=True,
    ),
    ADMISSIBLE_SPEC_RELATIVE: FrozenSpecRegistration(
        relative_path=ADMISSIBLE_SPEC_RELATIVE,
        file_sha256=ADMISSIBLE_SPEC_FILE_SHA256,
        self_sha256=ADMISSIBLE_SPEC_SELF_SHA256,
        requested_rows=94,
        status_counts=(("missing", 94),),
        low_support_in_request=False,
    ),
}


def request_key_identity(row: object) -> tuple[str, str, str, str, str, str] | None:
    """Return the exact non-value identity of a request or exclusion row."""

    if not isinstance(row, dict) or set(row) != REQUEST_KEY_FIELDS:
        return None
    values = (
        row.get("market"),
        row.get("target_date"),
        row.get("station"),
        row.get("settlement_unit"),
        row.get("provenance_side"),
        row.get("local_status"),
    )
    return values if all(isinstance(value, str) for value in values) else None


def registration_for_self_hash(value: object) -> FrozenSpecRegistration | None:
    """Resolve an admitted contract by its exact canonical self-hash."""

    return next(
        (
            registration
            for registration in FROZEN_SPEC_REGISTRY.values()
            if registration.self_sha256 and registration.self_sha256 == value
        ),
        None,
    )
