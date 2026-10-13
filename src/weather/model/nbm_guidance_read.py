"""MG-1 shadow stage ``nbm_v2_guidance_read_v1`` (pure; no I/O and no clock).

The stage implements the signed MG-1 rule
(``docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md`` §1)
as a post-model distribution stage. It reads the captured parser-v2 NBM
probabilistic Tmax source item and the served path's captured floor inputs,
and returns a band vector or the captured served vector unchanged. It is
computed in shadow and never served (§2.2). It reads no observation source
itself, so effective WU print-cutoff semantics are inherited from the served
feature path that computed the floor inputs.

The constants below are frozen by the pre-registration; changing any of them
is a new stage version, never an edit of this one.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.model.source_adapters import FETCH_META_KEY
from weather.sources.nbm_probabilistic_tmax import nbp_parser_version_number

STAGE_ID = "nbm_v2_guidance_read_v1"
SIGMA_FLOOR_F = 1.0
LOOKBACK_HOURS = 24
REQUIRED_PARSER = 2
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
RENORMALISE_TOLERANCE = 1e-12
NATIVE_UNIT = "F"
STATUS_MG1 = "mg1"
STATUS_FALLBACK = "fallback"

STAGE_CONSTANTS = {
    "stage_id": STAGE_ID,
    "sigma_floor_native": SIGMA_FLOOR_F,
    "lookback_hours": LOOKBACK_HOURS,
    "required_parser_version": REQUIRED_PARSER,
    "floor_fields": list(FLOOR_FIELDS),
    "discretisation": "integer, mass on [k-0.5, k+0.5)",
    "final_high": "H = max(B, X), B = floor(F + 0.5)",
    "renormalise_tolerance": RENORMALISE_TOLERANCE,
    "native_unit": NATIVE_UNIT,
    "fallback": "captured served vector, unmasked",
}


def stage_config_sha256() -> str:
    """SHA-256 of the frozen constants (canonical JSON)."""

    text = json.dumps(STAGE_CONSTANTS, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stage_code_sha256() -> str:
    """SHA-256 of this module's bytes, CRLF normalised to LF."""

    data = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- reading


@dataclass(frozen=True)
class NbmV2Read:
    eligible: bool
    reason: str | None
    v2_mean: float | None = None
    v2_stddev: float | None = None
    issued_at: str | None = None
    valid_time_utc: str | None = None
    available_at: str | None = None
    available_basis: str | None = None
    period_kind: str | None = None
    parser_version: int | None = None
    cache_status: str | None = None
    stale: bool | None = None
    pit_violation: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def read_v2(source_item: Mapping[str, Any] | None, captured_at_utc: Any, target_date: date | str) -> NbmV2Read:
    """Eligibility of the captured parser-v2 read for (station, D) at capture time t (MG-1 §1).

    ``source_item`` is ``model["sources"]["nbm_probabilistic_tmax"]`` as captured
    (``{"ok", "stale", "cache_status", "data": payload, ...}``).
    """

    captured = _utc(captured_at_utc)
    if captured is None:
        return NbmV2Read(False, "captured_at_invalid")
    target = target_date.isoformat() if isinstance(target_date, date) else str(target_date or "")
    item = source_item if isinstance(source_item, Mapping) else {}
    payload = item.get("data") if isinstance(item.get("data"), Mapping) else None
    if not item.get("ok") or payload is None:
        return NbmV2Read(False, "source_not_ok")
    meta = payload.get(FETCH_META_KEY) if isinstance(payload.get(FETCH_META_KEY), Mapping) else {}
    common = {
        "cache_status": item.get("cache_status") or meta.get("cache_status"),
        "stale": bool(item.get("stale")) or bool(meta.get("stale")),
        "period_kind": payload.get("period_kind"),
        "issued_at": payload.get("issued_at"),
        "valid_time_utc": payload.get("valid_time_utc"),
    }
    try:
        parser = nbp_parser_version_number(payload.get("parser_version"))
    except ValueError:
        return NbmV2Read(False, "parser_version_unknown", **common)
    common["parser_version"] = parser
    if parser != REQUIRED_PARSER:
        return NbmV2Read(False, "parser_version_not_2", **common)
    if payload.get("available") is not True:
        return NbmV2Read(False, "read_not_available", **common)
    if payload.get("period_kind") != "maximum":
        return NbmV2Read(False, "period_kind_not_maximum", **common)
    if str(payload.get("target_date") or "") != target:
        return NbmV2Read(False, "target_date_mismatch", **common)
    issued = _utc(payload.get("issued_at"))
    if issued is None:
        return NbmV2Read(False, "issued_at_invalid", **common)
    if issued > captured:
        return NbmV2Read(False, "issued_after_capture", pit_violation=True, **common)
    if captured - issued > timedelta(hours=LOOKBACK_HOURS):
        return NbmV2Read(False, "outside_lookback", **common)
    available, basis = None, None
    for key, value in (
        ("response_received_at", meta.get("response_received_at")),
        ("fetched_at", meta.get("fetched_at") or payload.get("fetched_at")),
        ("first_seen_at", payload.get("first_seen_at") or item.get("first_seen_at")),
    ):
        available = _utc(value)
        if available is not None:
            basis = key
            break
    common.update(available_at=_iso(available), available_basis=basis)
    if available is None:
        return NbmV2Read(False, "availability_missing", **common)
    if available > captured:
        return NbmV2Read(False, "available_after_capture", pit_violation=True, **common)
    mean, stddev = _finite(payload.get("mean_native")), _finite(payload.get("stddev_native"))
    if mean is None or stddev is None:
        return NbmV2Read(False, "mean_or_stddev_not_finite", **common)
    return NbmV2Read(True, None, v2_mean=mean, v2_stddev=stddev, **common)


def floor_value(features: Mapping[str, Any] | None) -> float | None:
    """F = max of the finite captured floor fields (81a), or None."""

    values = [_finite((features or {}).get(name)) for name in FLOOR_FIELDS]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


# --------------------------------------------------------------------------- bands


@dataclass(frozen=True)
class Band:
    kind: str
    low: int
    high: int


def band_from_row(row: Mapping[str, Any]) -> Band:
    """Map a served long row (``bin_kind``, ``bin_value_c``, ``bin_value_hi_c``; native units) to a band.

    Same mapping as ``guidance_extract.band_vector``; the ``_c`` names are legacy and hold native values.
    """

    kind = row.get("bin_kind")
    if kind not in {"lte", "eq", "gte"}:
        raise ValueError("invalid_band_kind")
    low, high = _finite(row.get("bin_value_c")), _finite(row.get("bin_value_hi_c"))
    if low is None or low != int(low) or (high is not None and high != int(high)):
        raise ValueError("noninteger_band_limits")
    return Band(kind, int(low), int(high) if high is not None else int(low))


def _ndtr(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def band_probs(bands: Sequence[Band], floor_bucket: int, mu: float, sigma: float) -> list[float]:
    """P(H in band), H = max(B, X), X ~ N(mu, sigma) integer-discretised (``t5_nbh_latest.band_probs``)."""

    def cdf(x: float) -> float:
        if x == math.inf:
            return 1.0
        if x == -math.inf:
            return 0.0
        return _ndtr((x - mu) / sigma)

    out = []
    for band in bands:
        upper = math.inf if band.kind == "gte" else band.high + 0.5
        lower = -math.inf if band.kind == "lte" or band.low <= floor_bucket else band.low - 0.5
        possible = band.kind == "gte" or band.high >= floor_bucket
        out.append(max(cdf(upper) - cdf(lower), 0.0) if possible else 0.0)
    return out


def floor_impossible(bands: Sequence[Band], floor_bucket: int) -> list[bool]:
    """81a mask: a non-``gte`` band whose high is below the floor bucket is impossible."""

    return [band.kind != "gte" and band.high < floor_bucket for band in bands]


# --------------------------------------------------------------------------- stage


@dataclass(frozen=True)
class StageResult:
    vector: tuple[float, ...]
    status: str
    reason: str | None
    floor: float | None
    floor_bucket: int | None
    sigma: float | None

    def to_dict(self) -> dict:
        return {**asdict(self), "vector": list(self.vector)}


def apply(
    bands: Sequence[Band],
    served: Sequence[float],
    read: NbmV2Read,
    floor: float | None,
    *,
    unit: str = NATIVE_UNIT,
) -> StageResult:
    """The MG-1 vector, or the captured served vector unchanged (§1 fallback)."""

    served_vector = tuple(float(value) for value in served)
    if len(served_vector) != len(bands) or not bands:
        raise ValueError("served vector and bands differ in length")

    def fallback(reason: str, bucket: int | None = None, sigma: float | None = None) -> StageResult:
        return StageResult(served_vector, STATUS_FALLBACK, reason, floor, bucket, sigma)

    if unit != NATIVE_UNIT:
        return fallback("unit_not_fahrenheit")
    if not read.eligible:
        return fallback(read.reason or "read_ineligible")
    if floor is None or not math.isfinite(floor):
        return fallback("missing_floor")
    bucket = math.floor(float(floor) + 0.5)
    sigma = max(float(read.v2_stddev), SIGMA_FLOOR_F)
    p = band_probs(bands, bucket, float(read.v2_mean), sigma)
    total = sum(p)
    if not total > 0:
        return fallback("zero_mass", bucket, sigma)
    p = [value / total for value in p]
    p = [0.0 if impossible else value for value, impossible in zip(p, floor_impossible(bands, bucket))]
    total = sum(p)
    if not total > 0:
        return fallback("zero_mass_after_floor", bucket, sigma)
    if abs(total - 1.0) > RENORMALISE_TOLERANCE:
        p = [value / total for value in p]
    return StageResult(tuple(p), STATUS_MG1, None, floor, bucket, sigma)
