"""Bounded offline integrity and byte-rate summary of a completed scratch capture.

Reads only an explicitly named day's journals and its root status. Never reads
credentials, follows another data root, changes evidence or opens a network.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import zlib

from weather.market.maker_evidence_store import DEFAULT_STREAM_CAP, digest, encoded

MAX_INSPECTION_BYTES = 1024**3
MAX_LINE_BYTES = 8 * 1024**2


def inspect_capture(root, day):
    root = Path(root)
    datetime.strptime(day, "%Y-%m-%d")
    folder = root / day
    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    if not status.get("finished_at_utc"):
        raise ValueError("inspection requires a terminal capture")
    paths = sorted(folder.glob("*.jsonl"))
    if len(paths) > 2048 or sum(p.stat().st_size for p in paths) > MAX_INSPECTION_BYTES:
        raise ValueError("inspection exceeds file/byte bound")
    files = {}
    for path in paths:
        compressor = zlib.compressobj(level=6, wbits=31)
        sha, compressed = hashlib.sha256(), 0
        with path.open("rb") as handle:
            while block := handle.read(65536):
                sha.update(block)
                compressed += len(compressor.compress(block))
        compressed += len(compressor.flush())
        files[path.name] = {"bytes": path.stat().st_size, "sha256": sha.hexdigest(),
                            "gzip_level_6_bytes": compressed}
    payloads, counts, stored, raw, minute_bytes = {}, Counter(), Counter(), Counter(), Counter()
    total, canonical_only, projected = 0, 0, 0
    manifest_compressors, manifest_gzip = {}, Counter()
    def read_payload(filename, offset):
        if filename not in files or filename == "manifest.jsonl":
            raise ValueError("manifest references a non-journal file")
        if filename not in payloads:
            if len(payloads) >= 16:
                payloads.pop(next(iter(payloads))).close()
            payloads[filename] = (folder / filename).open("rb")
        handle = payloads[filename]
        handle.seek(offset)
        line = handle.readline(MAX_LINE_BYTES + 1)
        if len(line) > MAX_LINE_BYTES:
            raise ValueError("oversized payload row")
        return json.loads(line)

    def body_bytes(payload):
        if "body_base64" in payload:
            return base64.b64decode(payload["body_base64"], validate=True)
        pieces = []
        for part in payload["parts"]:
            if "literal_base64" in part:
                pieces.append(base64.b64decode(part["literal_base64"], validate=True))
            else:
                child = read_payload(part["file"], part["offset"])
                pieces.append(base64.b64decode(child["body_base64"], validate=True))
        return b"".join(pieces)
    try:
        with (folder / "manifest.jsonl").open("rb") as manifest:
            for line in manifest:
                if len(line) > MAX_LINE_BYTES:
                    raise ValueError("oversized manifest row")
                row = json.loads(line)
                kind = row["kind"]
                if kind not in manifest_compressors:
                    manifest_compressors[kind] = zlib.compressobj(level=6, wbits=31)
                manifest_gzip[kind] += len(manifest_compressors[kind].compress(line))
                payload = read_payload(row["payload_file"], row["payload_offset"])
                body = body_bytes(payload)
                if row.get("representation") == "selection_projection":
                    projected += 1
                if digest(body) != row.get("stored_sha256", row["response_sha256"]):
                    if row["body_stored"] or digest(encoded(json.loads(body))) != row["content_sha256"]:
                        raise ValueError("response/content hash mismatch")
                    canonical_only += 1
                content = encoded(json.loads(body)) if row.get("change_key") else body
                if digest(content) != row["content_sha256"]:
                    raise ValueError("canonical content hash mismatch")
                counts[row["kind"]] += 1
                stored[row["kind"]] += int(row["body_stored"])
                raw[row["kind"]] += row["response_bytes"]
                minute_bytes[row["captured_at_utc"][:16]] += row["response_bytes"]
                total += 1
    finally:
        for handle in payloads.values():
            handle.close()
    elapsed = (datetime.fromisoformat(status["finished_at_utc"]) -
               datetime.fromisoformat(status["started_at_utc"])).total_seconds()
    raw_total = sum(row["bytes"] for row in files.values())
    gzip_total = sum(row["gzip_level_6_bytes"] for row in files.values())
    for kind, compressor in manifest_compressors.items():
        manifest_gzip[kind] += len(compressor.flush())
    stream_names = {name for name in files if name == "stream.jsonl" or name.startswith("updates-")}
    stream_gzip = sum(files[name]["gzip_level_6_bytes"] for name in stream_names) + manifest_gzip["stream"]
    other_gzip = sum(row["gzip_level_6_bytes"] for name, row in files.items()
                     if name != "manifest.jsonl" and name not in stream_names) + sum(
                         size for kind, size in manifest_gzip.items() if kind != "stream")
    stream_raw_daily = raw["stream"] * 86400 / elapsed
    cap_fraction = min(1., DEFAULT_STREAM_CAP / stream_raw_daily) if stream_raw_daily else 1.
    return {"day": day, "elapsed_seconds": elapsed, "cycles": status["cycles"],
            "failed_cycles": status["failed_cycles"], "http": status["http"],
            "stream": status["stream"], "trades": status["trades"],
            "manifest_rows_verified": total, "canonical_only_references": canonical_only,
            "discovery_projection_responses": projected,
            "counts_by_kind": dict(counts), "bodies_stored_by_kind": dict(stored),
            "response_bytes_by_kind": dict(raw), "response_bytes_by_utc_minute": dict(minute_bytes),
            "journal_bytes": raw_total, "gzip_level_6_bytes": gzip_total,
            "journal_bytes_per_minute": raw_total * 60 / elapsed,
            "uncapped_journal_bytes_per_day_extrapolated": raw_total * 86400 / elapsed,
            "uncapped_gzip_bytes_per_day_extrapolated": gzip_total * 86400 / elapsed,
            "manifest_gzip_bytes_by_kind": dict(manifest_gzip),
            "default_cap_gzip_bytes_per_day_extrapolated": (other_gzip + stream_gzip * cap_fraction) * 86400 / elapsed,
            "cap_projection_basis": "Observed per-family gzip ratio; separate manifest-kind compression; stationary traffic and 300 MB raw cap assumed",
            "extrapolation_is_not_a_full_day_measurement": True, "files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(inspect_capture(args.root, args.day), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
