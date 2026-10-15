"""t3-r3 shadow stage ``remaining_rise_floor_v1`` (pure; no network and no clock).

Implements the remaining-rise stage of the 13-16 pre-registration
(``docs/research/remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md`` §1;
D2 draft §5, serve form d2-r3f). Owner OD-B1 (2026-10-15) authorised the build.

At one snapshot the stage reads only:

1. the captured 81a floor F (max of the finite ``FLOOR_FIELDS``; in practice
   ``guidance_physical_floor``, the METAR maximum since local midnight);
2. B = round_half_up(F);
3. the market's station;
4. the local target month;
5. the local clock hour of the snapshot;
6. the frozen artifact ``remaining_rise_pmf_v1`` (hash bound below).

It returns P(H = B + e) mapped to bands (``eq`` [low, high] inclusive, ``lte``
<= high, ``gte`` >= low), then the 81a floor mask and renormalisation. It falls
back to the captured served vector, unchanged, when F or the cell is missing,
the METAR source is flagged ``stale``, or the floored mass is 0. It runs after
the served final distribution and is computed in shadow only, never served.

It reads no observation source itself, so effective WU print-cutoff semantics
are inherited from the served feature path that computed the floor inputs. It
has no fitted parameter, no hour gate, no pooling with served and no recency
rule. The constants and the artifact hash are frozen by the pre-registration:
changing any of them is a new stage version, never an edit of this one.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from weather.artifacts import resolve_artifact_path
from weather.units import round_half_up

STAGE_ID = "remaining_rise_floor_v1"
ARTIFACT_ID = "remaining_rise_pmf_v1"
ARTIFACT_FILENAME = f"{ARTIFACT_ID}.json"
ARTIFACT_SHA256 = "b727fe1a897f8786afcd89514f0bae4a82d9e03ad951f2d72db9e228dd2afb09"
CANDIDATE_ID = "t3-r3"
REGISTRY_SHA256 = "ae86d0350391219d1f96a91e944335eec2e9216f95b0fdc58e9cda3185456559"
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
RENORMALISE_TOLERANCE = 1e-12
NATIVE_UNIT = "F"
STATUS_STAGE = "remaining_rise"
STATUS_FALLBACK = "fallback"

STAGE_CONSTANTS = {
    "stage_id": STAGE_ID,
    "candidate": CANDIDATE_ID,
    "registry_sha256": REGISTRY_SHA256,
    "artifact_id": ARTIFACT_ID,
    "artifact_sha256": ARTIFACT_SHA256,
    "floor_fields": list(FLOOR_FIELDS),
    "anchor": "B = round_half_up(F), F = max of finite floor_fields",
    "cell_key": "station x local target month x local clock hour of captured_at",
    "band_map": "P(H = B + e): eq [low, high] inclusive, lte <= high, gte >= low",
    "floor_mask": "non-gte band with high < B set to 0, then renormalise",
    "renormalise_tolerance": RENORMALISE_TOLERANCE,
    "native_unit": NATIVE_UNIT,
    "fallback": "captured served vector, unmasked",
    "order": "after the served final distribution; shadow only",
}


def stage_config_sha256() -> str:
    """SHA-256 of the frozen constants (canonical JSON)."""

    text = json.dumps(STAGE_CONSTANTS, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stage_code_sha256() -> str:
    """SHA-256 of this module's bytes, CRLF normalised to LF."""

    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# --------------------------------------------------------------------------- artifact


@dataclass(frozen=True)
class RiseCell:
    station: str
    month: int
    hour: int
    base: int
    pmf: tuple[float, ...]
    n_days: int

    def key(self) -> dict:
        return {"station": self.station, "month": self.month, "hour": self.hour,
                "base": self.base, "n_days": self.n_days}


@dataclass(frozen=True)
class RiseTable:
    sha256: str
    cells: Mapping[tuple[str, int, int], RiseCell]

    def cell(self, station: str | None, month: int | None, hour: int | None) -> RiseCell | None:
        if station is None or month is None or hour is None:
            return None
        return self.cells.get((str(station).upper(), int(month), int(hour)))


def parse_table(data: bytes) -> RiseTable:
    """Parse artifact bytes; the hash is over the exact bytes read."""

    document = json.loads(data.decode("utf-8"))
    if document.get("artifact_id") != ARTIFACT_ID or document.get("unit") != NATIVE_UNIT:
        raise ValueError("not a remaining_rise_pmf_v1 Fahrenheit artifact")
    cells: dict[tuple[str, int, int], RiseCell] = {}
    for station, months in (document.get("cells") or {}).items():
        for month, hours in months.items():
            for hour, cell in hours.items():
                pmf = tuple(float(value) for value in cell["pmf"])
                if not pmf or int(cell["base"]) < 0 or any(not math.isfinite(v) or v < 0 for v in pmf):
                    raise ValueError(f"invalid cell {station}/{month}/{hour}")
                cells[(station, int(month), int(hour))] = RiseCell(
                    station, int(month), int(hour), int(cell["base"]), pmf, int(cell["n_days"])
                )
    return RiseTable(hashlib.sha256(data).hexdigest(), cells)


@lru_cache(maxsize=4)
def _load_cached(path_text: str, size: int, mtime_ns: int) -> RiseTable:
    return parse_table(Path(path_text).read_bytes())


def load_table(path: str | Path | None = None) -> RiseTable:
    """Load the artifact (cached per path, size and mtime)."""

    resolved = Path(path) if path is not None else resolve_artifact_path(ARTIFACT_FILENAME)
    stat = resolved.stat()
    return _load_cached(str(resolved), stat.st_size, stat.st_mtime_ns)


# --------------------------------------------------------------------------- inputs


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def floor_value(features: Mapping[str, Any] | None) -> float | None:
    """F = max of the finite captured floor fields (81a), or None."""

    values = [_finite((features or {}).get(name)) for name in FLOOR_FIELDS]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


@dataclass(frozen=True)
class CellKey:
    station: str | None
    month: int | None
    hour: int | None
    captured_local_date: str | None
    on_target_date: bool

    def to_dict(self) -> dict:
        return asdict(self)


def cell_key(station: str | None, timezone_name: str | None, captured_at: datetime, target_date: date | str) -> CellKey:
    """Station, local target month and local clock hour of the snapshot."""

    target = target_date.isoformat() if isinstance(target_date, date) else str(target_date or "")[:10]
    month = int(target[5:7]) if len(target) == 10 and target[5:7].isdigit() else None
    if captured_at.tzinfo is None or not timezone_name:
        return CellKey(station, month, None, None, False)
    local = captured_at.astimezone(ZoneInfo(timezone_name))
    local_date = local.date().isoformat()
    return CellKey(station.upper() if station else None, month, local.hour, local_date, local_date == target)


# --------------------------------------------------------------------------- bands


@dataclass(frozen=True)
class Band:
    kind: str
    low: int
    high: int


def band_from_row(row: Mapping[str, Any]) -> Band:
    """Map a served long row (``bin_kind``, ``bin_value_c``, ``bin_value_hi_c``; native units) to a band.

    The ``_c`` names are legacy and hold native values.
    """

    kind = row.get("bin_kind")
    if kind not in {"lte", "eq", "gte"}:
        raise ValueError("invalid_band_kind")
    low, high = _finite(row.get("bin_value_c")), _finite(row.get("bin_value_hi_c"))
    if low is None or low != int(low) or (high is not None and high != int(high)):
        raise ValueError("noninteger_band_limits")
    return Band(kind, int(low), int(high) if high is not None else int(low))


def band_probs(bands: Sequence[Band], base: int, pmf: Sequence[float]) -> list[float]:
    """Mass of the integer pmf ``P(H = base + i) = pmf[i]`` on each band (t3-r3 ``band_probs``)."""

    cumulative = [0.0]
    for value in pmf:
        cumulative.append(cumulative[-1] + value)
    n = len(pmf)

    def mass(lo: int, hi: int) -> float:
        i = min(max(lo - base, 0), n)
        j = min(max(hi - base + 1, 0), n)
        return max(cumulative[j] - cumulative[i], 0.0)

    out = []
    for band in bands:
        if band.kind == "lte":
            out.append(mass(-10**6, band.high))
        elif band.kind == "gte":
            out.append(mass(band.low, 10**6))
        else:
            out.append(mass(band.low, band.high))
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

    def to_dict(self) -> dict:
        return {**asdict(self), "vector": list(self.vector)}


def apply(
    bands: Sequence[Band],
    served: Sequence[float],
    *,
    floor: float | None,
    cell: RiseCell | None,
    metar_stale: bool,
    on_target_date: bool,
    artifact_sha256: str | None,
    unit: str = NATIVE_UNIT,
) -> StageResult:
    """The t3-r3 vector, or the captured served vector unchanged (§1 fallback)."""

    served_vector = tuple(float(value) for value in served)
    if len(served_vector) != len(bands) or not bands:
        raise ValueError("served vector and bands differ in length")

    def fallback(reason: str, bucket: int | None = None) -> StageResult:
        return StageResult(served_vector, STATUS_FALLBACK, reason, floor, bucket)

    if unit != NATIVE_UNIT:
        return fallback("unit_not_fahrenheit")
    if artifact_sha256 != ARTIFACT_SHA256:
        return fallback("artifact_hash_mismatch")
    if not on_target_date:
        return fallback("snapshot_not_on_target_date")
    if floor is None or not math.isfinite(floor):
        return fallback("missing_floor")
    bucket = round_half_up(floor)
    if metar_stale:
        return fallback("metar_stale", bucket)
    if cell is None:
        return fallback("missing_cell", bucket)
    p = band_probs(bands, bucket + cell.base, cell.pmf)
    p = [0.0 if impossible else value for value, impossible in zip(p, floor_impossible(bands, bucket))]
    total = sum(p)
    if not total > 0:
        return fallback("zero_mass_after_floor", bucket)
    if abs(total - 1.0) > RENORMALISE_TOLERANCE:
        p = [value / total for value in p]
    return StageResult(tuple(p), STATUS_STAGE, None, floor, bucket)
