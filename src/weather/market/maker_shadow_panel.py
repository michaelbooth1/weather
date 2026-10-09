"""Read-only 88a panel for nightly shadow diagnostics, with the evidence embargo.

Consumes sealed ``maker_evidence_v2`` segments of one UTC day exactly as the 88a
writer (``weather.market.maker_evidence_store``) left them: per-token book
journals referenced from ``books``/``ranking_books`` rows, and public
``last_trade_price`` prints in ``trades``. Every file read is checked against its
segment manifest (size and SHA-256 of the decompressed bytes). Unsealed
segments are listed and never opened. Nothing is written into the 88a root.
Contract: docs/operations/maker-shadow-runner.md.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re

from maker_core.shadow.admission import EMBARGOED_UTC_DAYS, embargo_reason  # re-exported; windows live in core
from weather.market.maker_evidence_store import SCHEMA, decode_body

MID_MAX_AGE = timedelta(seconds=120)
MAX_PANEL_BYTES = 2 * 1024**3
SEGMENT = re.compile(r"\d{2}-[0-9a-f]{12}\Z")
ASSET_FILE = re.compile(r"book-([0-9]{1,100})\.jsonl\Z")


def _mid(book):
    bids = [Decimal(str(level["price"])) for level in book.get("bids") or ()]
    asks = [Decimal(str(level["price"])) for level in book.get("asks") or ()]
    return (max(bids) + min(asks)) / 2 if bids and asks else None


class MakerEvidencePanel:
    """Book mids and trade prints for the requested assets on one sealed 88a UTC day."""

    def __init__(self, root, day, assets):
        self.root, self.day = Path(root), day
        self.assets = {str(a) for a in assets}
        self.samples = {a: [] for a in self.assets}
        self.trades = {a: set() for a in self.assets}
        self.bytes_read = 0
        self.summary = {"utc_day": day, "segments_read": 0, "unsealed_segments_skipped": [], "manifest_sha256": [],
                        "assets_requested": len(self.assets)}
        folder = self.root / day
        if not folder.is_dir():
            raise ValueError("maker_evidence_day_missing")
        for segment in sorted(p for p in folder.iterdir() if p.is_dir() and SEGMENT.fullmatch(p.name)):
            self._segment(segment)
        for rows in self.samples.values():
            rows.sort(key=lambda row: row[0])
        self.times = {a: [t for t, _ in rows] for a, rows in self.samples.items()}
        self.prints_by_asset = {a: sorted(rows) for a, rows in self.trades.items()}
        self.summary.update(assets_covered=sum(1 for a in self.assets if self.covers(a)),
                            book_samples=sum(len(r) for r in self.samples.values()),
                            prints=sum(len(r) for r in self.prints_by_asset.values()), bytes_read=self.bytes_read)

    def _read(self, segment, name, expected):
        plain = segment / name
        path = plain if plain.exists() else plain.with_name(name + ".gz")
        self.bytes_read += expected["bytes"]
        if self.bytes_read > MAX_PANEL_BYTES:
            raise ValueError("maker_evidence_panel_exceeds_byte_bound")
        with (gzip.open if path.suffix == ".gz" else open)(path, "rb") as handle:
            raw = handle.read(expected["bytes"] + 1)
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError("maker_evidence_file_differs_from_manifest")
        rows, offset = {}, 0
        for line in raw.splitlines(keepends=True):
            rows[offset] = json.loads(line)
            offset += len(line)
        return rows

    def _segment(self, segment):
        manifest = segment / "manifest.json"
        path = manifest if manifest.exists() else segment / "manifest.json.gz"
        if not path.exists():
            self.summary["unsealed_segments_skipped"].append(segment.name)
            return
        with (gzip.open if path.suffix == ".gz" else open)(path, "rb") as handle:
            raw = handle.read(2 * 1024**2 + 1)
        info = json.loads(raw)
        if info.get("schema_version") != SCHEMA:
            raise ValueError("unsupported_maker_evidence_schema")
        self.summary["segments_read"] += 1
        self.summary["manifest_sha256"].append(hashlib.sha256(raw).hexdigest())
        files, books = info["files"], {}

        def book_line(name, offset):
            if name not in books:
                books[name] = self._read(segment, name, files[name])
            return books[name][offset]

        for journal in ("books.jsonl", "ranking_books.jsonl"):
            if journal not in files:
                continue
            for row in self._read(segment, journal, files[journal]).values():
                captured = datetime.fromisoformat(row["captured_at_utc"])
                for part in row.get("parts") or ():
                    match = ASSET_FILE.fullmatch(str(part.get("file", "")))
                    if match and match.group(1) in self.assets and part["file"] in files:
                        book = json.loads(book_line(part["file"], part["offset"])["body_utf8"])
                        self.samples[match.group(1)].append((captured, _mid(book)))
        if "trades.jsonl" in files:
            for row in self._read(segment, "trades.jsonl", files["trades.jsonl"]).values():
                if "payload_ref" in row:
                    continue
                message = json.loads(decode_body(row))
                for event in message if isinstance(message, list) else [message]:
                    asset = str(event.get("asset_id")) if isinstance(event, dict) else ""
                    if event.get("event_type") == "last_trade_price" and asset in self.assets:
                        at = datetime.fromtimestamp(int(event["timestamp"]) / 1000, timezone.utc)
                        # Overlapping public connections repeat prints; identical rows count once.
                        self.trades[asset].add((at, Decimal(str(event["price"])), Decimal(str(event["size"])),
                                                str(event.get("side", ""))))

    def covers(self, asset_id):
        return bool(self.samples.get(str(asset_id)))

    def mid(self, asset_id, at_utc):
        rows = self.samples.get(str(asset_id)) or []
        index = bisect_right(self.times.get(str(asset_id), []), at_utc) - 1
        if index < 0 or at_utc - rows[index][0] > MID_MAX_AGE:
            return None
        return rows[index][1]

    def prints(self, asset_id, start_utc, end_utc):
        return [(at, price, size) for at, price, size, _ in self.prints_by_asset.get(str(asset_id), ())
                if start_utc < at <= end_utc]


__all__ = ["EMBARGOED_UTC_DAYS", "MakerEvidencePanel", "embargo_reason"]
