"""NBM NBH/NBS national text bulletins: URLs and station-block extraction.

Capture only. The National Blend of Models publishes hourly (NBH, 1-25 h) and
short-range (NBS, 3-hourly to 72 h) station text guidance every hour as one
~30 MB national file per product. We keep only the blocks of the configured
market stations, byte-for-byte as published, and never feed them to features.

The extractor streams lines, so the national file is never held in memory.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION = "nbm_text_station_blocks_v0.1"
NBM_TEXT_EXTRACTOR_VERSION = 1  # bump when block selection or canonical form changes
NBM_TEXT_PRIMARY_BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"
# Public AWS Open Data mirror of the same files (no credentials).
NBM_TEXT_MIRROR_BASE_URL = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
NBM_TEXT_BASE_URLS = (NBM_TEXT_PRIMARY_BASE_URL, NBM_TEXT_MIRROR_BASE_URL)
# Product code -> file stem token and header token.
NBM_TEXT_PRODUCTS = {"nbh": "NBH", "nbs": "NBS"}
NBM_TEXT_MEDIA_TYPE = "text/plain; charset=us-ascii"
NBM_TEXT_PAYLOAD_ENCODING = "gzip"

_HEADER_RE = re.compile(
    r"^\s*(?P<station>[A-Z0-9]{3,8})\s+NBM\s+V(?P<version>\S+)\s+"
    r"(?P<product>NB[A-Z])\s+GUIDANCE\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+(?P<hour>\d{4})\s+UTC"
)
# Rows every complete block must carry, by product.
_REQUIRED_ROWS = {"NBH": ("UTC", "TMP", "DPT"), "NBS": ("FHR", "TMP", "DPT")}


class NbmTextBulletinError(ValueError):
    """The bulletin is not the requested product/cycle or is malformed."""


def normalize_product(product: str) -> str:
    key = str(product or "").strip().lower()
    if key not in NBM_TEXT_PRODUCTS:
        raise NbmTextBulletinError(f"unsupported NBM text product: {product!r}")
    return key


def text_bulletin_url(product: str, run_time: datetime, base_url: str = NBM_TEXT_PRIMARY_BASE_URL) -> str:
    product = normalize_product(product)
    run_time = run_time.astimezone(timezone.utc)
    day, hour = run_time.strftime("%Y%m%d"), run_time.strftime("%H")
    return f"{base_url.rstrip('/')}/blend.{day}/{hour}/text/blend_{product}tx.t{hour}z"


def text_cycle_key(product: str, run_time: datetime) -> str:
    product = normalize_product(product)
    return f"nbm-{product}:{run_time.astimezone(timezone.utc).strftime('%Y%m%dT%HZ')}"


def recent_cycles(now_utc: datetime, hours_back: int) -> list[datetime]:
    """Newest first: the current hour and ``hours_back`` earlier hourly cycles."""
    cursor = now_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [cursor - timedelta(hours=offset) for offset in range(max(0, int(hours_back)) + 1)]


def parse_header(line: str) -> dict | None:
    match = _HEADER_RE.match(line)
    if not match:
        return None
    issued = datetime.strptime(f"{match['date']} {match['hour']}", "%m/%d/%Y %H%M")
    return {
        "station": match["station"],
        "product_version": match["version"],
        "product": match["product"],
        "issued_at": issued.replace(tzinfo=timezone.utc),
    }


@dataclass
class StationBlockExtraction:
    product: str
    cycle_time: datetime
    stations: tuple[str, ...]
    blocks: dict[str, list[str]] = field(default_factory=dict)
    product_versions: set[str] = field(default_factory=set)
    national_lines: int = 0
    national_headers: int = 0

    @property
    def stations_found(self) -> list[str]:
        return sorted(self.blocks)

    @property
    def stations_missing(self) -> list[str]:
        return sorted(set(self.stations) - set(self.blocks))

    def incomplete_stations(self) -> list[str]:
        required = _REQUIRED_ROWS[NBM_TEXT_PRODUCTS[self.product]]
        bad = []
        for station, lines in self.blocks.items():
            codes = {line[:5].strip() for line in lines[1:]}
            if not all(code in codes for code in required):
                bad.append(station)
        return sorted(bad)

    def extract_text(self) -> str:
        """Canonical extract: kept blocks in station order, each line LF-terminated."""
        return "".join(
            "".join(f"{line}\n" for line in self.blocks[station])
            for station in sorted(self.blocks)
        )


def _iter_text_lines(chunks: Iterable[bytes]) -> Iterator[str]:
    pending = b""
    for chunk in chunks:
        if not chunk:
            continue
        pending += chunk
        *complete, pending = pending.split(b"\n")
        for raw in complete:
            yield raw.rstrip(b"\r").decode("latin-1")
    if pending:
        yield pending.rstrip(b"\r").decode("latin-1")


def extract_station_blocks(
    chunks: Iterable[bytes],
    *,
    product: str,
    cycle_time: datetime,
    stations: Iterable[str],
) -> StationBlockExtraction:
    """Stream a national bulletin and keep only the requested station blocks.

    A block runs from its header to the next blank line or header. Every kept
    header must name the requested product and cycle; a duplicate kept station
    is malformed. Blocks are kept verbatim (trailing whitespace preserved).
    """
    product = normalize_product(product)
    token = NBM_TEXT_PRODUCTS[product]
    cycle_time = cycle_time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    wanted = tuple(sorted({str(s).strip().upper() for s in stations if str(s).strip()}))
    result = StationBlockExtraction(product=product, cycle_time=cycle_time, stations=wanted)
    current: list[str] | None = None
    for line in _iter_text_lines(chunks):
        result.national_lines += 1
        header = parse_header(line) if "GUIDANCE" in line else None
        if header is not None:
            result.national_headers += 1
            current = None
            if header["station"] not in wanted:
                continue
            if header["product"] != token:
                raise NbmTextBulletinError(f"expected {token} bulletin, found {header['product']}")
            if header["issued_at"] != cycle_time:
                raise NbmTextBulletinError(
                    f"{header['station']} block issued {header['issued_at']:%Y-%m-%dT%HZ}, "
                    f"requested {cycle_time:%Y-%m-%dT%HZ}"
                )
            if header["station"] in result.blocks:
                raise NbmTextBulletinError(f"duplicate {header['station']} block")
            result.product_versions.add(header["product_version"])
            current = result.blocks.setdefault(header["station"], [])
            current.append(line)
            continue
        if current is None:
            continue
        if not line.strip():
            current = None
            continue
        current.append(line)
    return result


def extract_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("latin-1")).hexdigest()
