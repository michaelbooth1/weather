"""Bounded offline verification of sealed v2 hours and per-family storage rates."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import zlib

from weather.market.maker_evidence_store import SCHEMA, MAX_LINE_BYTES, decode_body, digest, encoded

MAX_INSPECTION_BYTES = 1024**3


def family(name):
    for prefix, group in (("book-", "token_books"), ("updates-", "updates"),
                          ("reward-", "rewards"), ("universe-", "universe"),
                          ("subscription-", "subscriptions")):
        if name.startswith(prefix):
            return group
    return name.split(".")[0]


def inspect_capture(root, day):
    root = Path(root)
    datetime.strptime(day, "%Y-%m-%d")
    status = json.loads((root / "status.json").read_bytes())
    if not status.get("finished_at_utc") or status["schema_version"] != SCHEMA:
        raise ValueError("inspection requires a terminal v2 capture")
    files, manifests, family_bytes, family_gzip = {}, {}, Counter(), Counter()
    for folder in sorted((root / day).iterdir()):
        if not folder.is_dir():
            continue
        manifest = folder / "manifest.json"
        path, opener = (manifest, open) if manifest.exists() else (manifest.with_suffix(".json.gz"), gzip.open)
        with opener(path, "rb") as handle:
            raw = handle.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise ValueError("oversized file manifest")
        info = json.loads(raw)
        if info["schema_version"] != SCHEMA:
            raise ValueError("unsupported journal schema")
        key = folder.relative_to(root).as_posix()
        manifests[key] = {"sha256": digest(raw), "file_count": len(info["files"])}
        family_bytes["manifests"] += len(raw)
        family_gzip["manifests"] += len(gzip.compress(raw, compresslevel=6, mtime=0))
        listed = set(info["files"])
        actual = {p.name.removesuffix(".gz") for p in folder.glob("*.jsonl*") if not p.name.endswith(".tmp")}
        if listed != actual:
            raise ValueError("sealed manifest file coverage mismatch")
        for name, expected in info["files"].items():
            if Path(name).name != name or not name.endswith(".jsonl"):
                raise ValueError("invalid file manifest path")
            plain = folder / name
            files[key + "/" + name] = {"path": plain if plain.exists() else plain.with_suffix(".jsonl.gz"),
                                      "expected": expected, "family": family(name)}
    if not manifests or len(files) > 20000 or sum(v["expected"]["bytes"] for v in files.values()) > MAX_INSPECTION_BYTES:
        raise ValueError("inspection exceeds file/byte bounds or contains no sealed hours")
    readers, counts, stored, response_bytes, minute_bytes = {}, Counter(), Counter(), Counter(), Counter()
    canonical_only = projected = verified = 0

    def read_payload(key, offset):
        if key not in files or not isinstance(offset, int) or offset < 0:
            raise ValueError("payload reference escaped declared files")
        if key not in readers:
            if len(readers) >= 16:
                readers.pop(next(iter(readers))).close()
            path = files[key]["path"]
            readers[key] = (gzip.open if path.suffix == ".gz" else open)(path, "rb")
        handle = readers[key]
        handle.seek(offset)
        line = handle.readline(MAX_LINE_BYTES + 1)
        if len(line) > MAX_LINE_BYTES:
            raise ValueError("oversized referenced record")
        row = json.loads(line)
        if row["offset"] != offset:
            raise ValueError("payload offset mismatch")
        return row

    def body_bytes(row, segment, depth=0):
        if depth > 2:
            raise ValueError("cyclic or oversized payload reference chain")
        if "payload_ref" in row:
            ref = row["payload_ref"]
            return body_bytes(read_payload(segment + "/" + ref["file"], ref["offset"]), segment, depth + 1)
        if "parts" not in row:
            return decode_body(row)
        chunks = []
        for part in row["parts"]:
            chunks.append(part["literal_utf8"].encode() if "literal_utf8" in part else
                          body_bytes(read_payload(segment + "/" + part["file"], part["offset"]), segment, depth + 1))
        return b"".join(chunks)

    try:
        for key, entry in files.items():
            path, expected = entry["path"], entry["expected"]
            opener = gzip.open if path.suffix == ".gz" else open
            sha, compressor, compressed = hashlib.sha256(), zlib.compressobj(6, wbits=31), 0
            offset = records = last_offset = 0
            with opener(path, "rb") as handle:
                while line := handle.readline(MAX_LINE_BYTES + 1):
                    if len(line) > MAX_LINE_BYTES or offset + len(line) > expected["bytes"]:
                        raise ValueError("journal exceeds declared byte bound")
                    row = json.loads(line)
                    if row["offset"] != offset or not line.endswith(b"\n"):
                        raise ValueError("record offset or newline mismatch")
                    last_offset = offset
                    offset += len(line)
                    records += 1
                    sha.update(line)
                    compressed += len(compressor.compress(line))
                    if "kind" not in row:  # Book constituent, verified by full-response reassembly and file hash.
                        continue
                    body = body_bytes(row, key.rsplit("/", 1)[0])
                    expected_body = row.get("stored_sha256", row["response_sha256"])
                    if digest(body) != expected_body:
                        if row["body_stored"] or digest(encoded(json.loads(body))) != row.get("content_sha256"):
                            raise ValueError("response/content hash mismatch")
                        canonical_only += 1
                    if row.get("content_sha256") and digest(encoded(json.loads(body))) != row["content_sha256"]:
                        raise ValueError("canonical content hash mismatch")
                    if row["kind"] in ("stream_lifecycle", "stream_gap"):
                        reference = json.loads(body).get("subscription")
                        if reference:
                            subscription = body_bytes(read_payload(reference["segment"] + "/" + reference["file"],
                                                                   reference["offset"]), reference["segment"])
                            if digest(subscription) != reference["sha256"]:
                                raise ValueError("subscription reference hash mismatch")
                    projected += row.get("representation") == "selection_projection"
                    kind = row["kind"]
                    counts[kind] += 1
                    stored[kind] += row["body_stored"]
                    response_bytes[kind] += row["response_bytes"]
                    minute_bytes[row["captured_at_utc"][:16]] += row["response_bytes"]
                    verified += 1
            if (sha.hexdigest(), offset, records, last_offset) != (expected["sha256"], expected["bytes"], expected["records"], expected["last_offset"]):
                raise ValueError("sealed file integrity mismatch")
            compressed += len(compressor.flush())
            entry["gzip_level_6_bytes"] = compressed
            family_bytes[entry["family"]] += offset
            family_gzip[entry["family"]] += compressed
    finally:
        for reader in readers.values():
            reader.close()
    elapsed = (datetime.fromisoformat(status["finished_at_utc"]) - datetime.fromisoformat(status["started_at_utc"])).total_seconds()
    raw_total, gzip_total = sum(family_bytes.values()), sum(family_gzip.values())
    window_seconds = status.get("update_window_active_seconds", 0.)
    update_gzip = family_gzip["updates"] + family_gzip["stream"]
    return {"day": day, "schema_version": SCHEMA, "elapsed_seconds": elapsed,
            "cycles": status["cycles"], "failed_cycles": status["failed_cycles"],
            "http": status["http"], "stream": status["stream"], "trades": status["trades"],
            "manifest_files_verified": len(manifests), "journal_files_verified": len(files),
            "response_records_verified": verified, "canonical_only_references": canonical_only,
            "discovery_projection_responses": projected, "counts_by_kind": dict(counts),
            "bodies_stored_by_kind": dict(stored), "response_bytes_by_kind": dict(response_bytes),
            "response_bytes_by_utc_minute": dict(minute_bytes), "journal_bytes": raw_total,
            "gzip_level_6_bytes": gzip_total, "journal_bytes_per_minute": raw_total * 60 / elapsed,
            "peak_raw_working_bytes": status["peak_raw_working_bytes"],
            "final_raw_working_bytes": status["raw_working_bytes"],
            "gzip_bytes_per_day_extrapolated": gzip_total * 86400 / elapsed,
            "stream_off_gzip_bytes_per_day_extrapolated": (gzip_total - update_gzip) * 86400 / elapsed,
            "update_window_active_seconds": window_seconds,
            "in_window_updates_gzip_bytes_per_minute": update_gzip * 60 / window_seconds if window_seconds else None,
            "in_window_updates_gzip_bytes_per_30_minutes": update_gzip * 1800 / window_seconds if window_seconds else None,
            "extrapolation_is_not_a_full_day_measurement": True,
            "projection_basis": "Observed sealed-hour gzip-6 bytes, including actual file-manifest overhead; no stream extrapolation into off periods",
            "families": {name: {"journal_bytes": size, "gzip_level_6_bytes": family_gzip[name],
                                  "gzip_bytes_per_day_extrapolated": family_gzip[name] * 86400 / elapsed}
                         for name, size in family_bytes.items()},
            "manifests": manifests}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(inspect_capture(args.root, args.day), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
