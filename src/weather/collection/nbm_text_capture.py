"""Capture NBM NBH/NBS station blocks into the shared forecast payload CAS.

Capture only: nothing here is read by features, serving, or training. For each
recent hourly cycle of each product this streams the national text bulletin
once, keeps the configured market stations' blocks verbatim, stores the gzip
of that extract in :class:`SharedForecastPayloadCAS`, and appends one
manifest row per cycle. A cycle with a success or partial row is never downloaded again.

    python -m weather.collection.nbm_text_capture --hours-back 3
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import requests

from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS
from weather.io import acquire_writer_lock, append_jsonl, read_jsonl, release_writer_lock
from weather.market.market_registry import all_specs
from weather.paths import data_path
from weather.sources.nbm_text_bulletins import (
    NBM_TEXT_BASE_URLS,
    NBM_TEXT_EXTRACTOR_VERSION,
    NBM_TEXT_MEDIA_TYPE,
    NBM_TEXT_PAYLOAD_ENCODING,
    NBM_TEXT_PRODUCTS,
    NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION,
    NbmTextBulletinError,
    extract_sha256,
    extract_station_blocks,
    normalize_product,
    recent_cycles,
    text_bulletin_url,
    text_cycle_key,
)

DEFAULT_MANIFEST_ROOT = data_path("forecast_payload_cas", "nbm_text_manifests")
DEFAULT_HOURS_BACK = 3
CHUNK_BYTES = 1024 * 1024
REQUEST_TIMEOUT = (15, 120)
LOCK_STALE_SECONDS = 1800.0
USER_AGENT = "weather-market-research/1.0 (local)"
TERMINAL_STATUSES = frozenset({"success", "partial"})

StreamFn = Callable[[str], Any]


def market_text_stations() -> tuple[str, ...]:
    """Every configured market station, including Toronto (CYYZ has NBM text blocks)."""
    return tuple(sorted({str(spec.icao).upper() for spec in all_specs() if spec.icao}))


def manifest_path(root: Path, cycle_time: datetime) -> Path:
    return Path(root) / f"{cycle_time.astimezone(timezone.utc):%Y%m%d}.jsonl"


def captured_cycle_keys(root: Path, cycle_times: Iterable[datetime]) -> set[str]:
    keys: set[str] = set()
    for path in sorted({manifest_path(root, t) for t in cycle_times}):
        for row in read_jsonl(path):
            # A partial capture is stored too; re-downloading would not add a station.
            if isinstance(row, dict) and row.get("status") in TERMINAL_STATUSES:
                keys.add(str(row.get("cycle_key")))
    return keys


def _default_stream(url: str):
    return requests.get(url, stream=True, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})


def _gzip_bytes(text: str) -> bytes:
    # mtime=0 and no file name: identical extracts give identical blobs.
    return gzip.compress(text.encode("latin-1"), compresslevel=9, mtime=0)


def capture_cycle(
    product: str,
    cycle_time: datetime,
    *,
    cas: SharedForecastPayloadCAS,
    stations: Sequence[str],
    stream_fn: StreamFn = _default_stream,
    base_urls: Sequence[str] = NBM_TEXT_BASE_URLS,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Download one cycle once and return its manifest row (status explains the outcome)."""
    product = normalize_product(product)
    row: dict[str, Any] = {
        "schema_version": NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION,
        "extractor_version": NBM_TEXT_EXTRACTOR_VERSION,
        "source": f"nbm_text_{product}",
        "product": NBM_TEXT_PRODUCTS[product],
        "cycle_key": text_cycle_key(product, cycle_time),
        "issued_at": cycle_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z"),
        "stations_requested": sorted(stations),
        "tried_urls": [],
        "feature_use": "none_capture_only",
    }
    for base_url in base_urls:
        url = text_bulletin_url(product, cycle_time, base_url)
        row["tried_urls"].append(url)
        started = now_fn()
        status, response = 0, None
        try:
            response = stream_fn(url)
            status = int(getattr(response, "status_code", 0))
            if status in (403, 404):
                row.update(status="not_published", http_status=status)
                continue
            if status != 200:
                row.update(status="http_error", http_status=status)
                return row
            digest = hashlib.sha256()
            received = 0

            def counted(chunks):
                nonlocal received
                for chunk in chunks:
                    digest.update(chunk)
                    received += len(chunk)
                    yield chunk

            extraction = extract_station_blocks(
                counted(response.iter_content(chunk_size=CHUNK_BYTES)),
                product=product, cycle_time=cycle_time, stations=stations,
            )
            received_at = now_fn()
        except (NbmTextBulletinError, requests.RequestException) as exc:
            row.update(status="malformed" if isinstance(exc, NbmTextBulletinError) else "transfer_error",
                       http_status=status, error=f"{type(exc).__name__}: {exc}"[:500])
            return row
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        declared = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
        row.update(
            source_url=url,
            http_status=status,
            request_started_at=started.isoformat(),
            response_received_at=received_at.isoformat(),
            national_bytes=received,
            national_sha256=digest.hexdigest(),
            national_content_length=int(declared) if declared else None,
            national_lines=extraction.national_lines,
            national_station_headers=extraction.national_headers,
            product_versions=sorted(extraction.product_versions),
            stations_found=extraction.stations_found,
            stations_missing=extraction.stations_missing,
            stations_incomplete=extraction.incomplete_stations(),
            block_line_counts={s: len(lines) for s, lines in sorted(extraction.blocks.items())},
        )
        if declared and int(declared) != received:
            row["status"] = "truncated"
            return row
        if not extraction.blocks:
            row["status"] = "no_station_blocks"
            return row
        text = extraction.extract_text()
        stored = cas.put(_gzip_bytes(text))
        row.update(
            status="success" if not (row["stations_missing"] or row["stations_incomplete"]) else "partial",
            extract_sha256=extract_sha256(text),
            extract_bytes=len(text.encode("latin-1")),
            extract_media_type=NBM_TEXT_MEDIA_TYPE,
            payload_encoding=NBM_TEXT_PAYLOAD_ENCODING,
            cas_kind=stored["cas_kind"],
            payload_hash_algorithm=stored["payload_hash_algorithm"],
            payload_hash=stored["payload_hash"],
            payload_bytes=stored["payload_bytes"],
            payload_ref=stored["payload_ref"],
            payload_blob_created=stored["created"],
        )
        return row
    return row


def run_capture(
    *,
    products: Sequence[str] = tuple(NBM_TEXT_PRODUCTS),
    hours_back: int = DEFAULT_HOURS_BACK,
    now_utc: datetime | None = None,
    cas_root: str | Path | None = None,
    manifest_root: str | Path = DEFAULT_MANIFEST_ROOT,
    stations: Sequence[str] | None = None,
    stream_fn: StreamFn = _default_stream,
    base_urls: Sequence[str] = NBM_TEXT_BASE_URLS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture every not-yet-captured recent cycle; one writer at a time."""
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manifest_root = Path(manifest_root)
    stations = tuple(stations or market_text_stations())
    cycles = recent_cycles(now_utc, hours_back)
    summary: dict[str, Any] = {"schema_version": NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION,
                               "now_utc": now_utc.isoformat(), "dry_run": dry_run, "cycles": []}
    lock = None
    if not dry_run:
        lock = acquire_writer_lock(manifest_root / "capture", stale_after_seconds=LOCK_STALE_SECONDS)
        if lock is None:
            summary["status"] = "locked"
            return summary
    try:
        done = captured_cycle_keys(manifest_root, cycles)
        cas = SharedForecastPayloadCAS(cas_root)
        for product in products:
            for cycle_time in cycles:
                key = text_cycle_key(product, cycle_time)
                if key in done:
                    summary["cycles"].append({"cycle_key": key, "status": "already_captured"})
                    continue
                if dry_run:
                    summary["cycles"].append({"cycle_key": key, "status": "would_fetch"})
                    continue
                row = capture_cycle(product, cycle_time, cas=cas, stations=stations,
                                    stream_fn=stream_fn, base_urls=base_urls)
                row["captured_at"] = datetime.now(timezone.utc).isoformat()
                # Not-yet-published cycles leave no row; they are retried next run.
                if row.get("status") != "not_published":
                    append_jsonl(manifest_path(manifest_root, cycle_time), row)
                summary["cycles"].append({k: row.get(k) for k in (
                    "cycle_key", "status", "payload_bytes", "stations_missing")})
        summary["status"] = "ok"
    finally:
        release_writer_lock(lock)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--products", nargs="+", default=list(NBM_TEXT_PRODUCTS),
                        choices=sorted(NBM_TEXT_PRODUCTS))
    parser.add_argument("--hours-back", type=int, default=DEFAULT_HOURS_BACK)
    parser.add_argument("--cas-root", default=None)
    parser.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    parser.add_argument("--dry-run", action="store_true", help="List cycles that would be fetched.")
    args = parser.parse_args(argv)
    summary = run_capture(products=args.products, hours_back=args.hours_back, cas_root=args.cas_root,
                          manifest_root=args.manifest_root, dry_run=args.dry_run)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
