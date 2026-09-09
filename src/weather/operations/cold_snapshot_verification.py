"""Read-only verification of one retained cold-snapshot compression preimage."""
from __future__ import annotations

from pathlib import Path
import re

from weather.operations import cold_snapshot_compression as compression
from weather.operations.ntfs_file_compression import LockedNtfsFile, PinnedNtfsDirectory
from weather.schema_registry import schema_version


def validate_request(payload, *, production_root, now):
    if not isinstance(payload, dict):
        raise ValueError("verification request must be an object")
    extra = {"preimage_receipt", "preimage_sha256", "predecessor_wrapper_sha256"}
    if not extra <= payload.keys():
        raise ValueError("verification requires an exact preimage and predecessor wrapper")
    if (payload.get("schema_version") != schema_version("cold_snapshot_verification_request")
            or payload.get("operation") != "verify_retained"):
        raise ValueError("explicit read-only retained-file verification is required")
    for key in ("preimage_sha256", "predecessor_wrapper_sha256"):
        if not isinstance(payload[key], str) or not re.fullmatch(r"[0-9a-f]{64}", payload[key]):
            raise ValueError("verification evidence hashes must be exact SHA-256")
    if "predecessor_request" in payload:
        predecessor_request_path(payload, production_root)
        extra.add("predecessor_request")
    rows = payload.get("files")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("verification is restricted to one exact file")
    attrs = rows[0].get("attributes")
    if (type(attrs) is not int or attrs & ~(0x20 | 0x80 | 0x800)
            or (attrs & 0x80 and attrs != 0x80)):
        raise ValueError("verification rejects unsupported file attributes")
    # Reuse every ordinary cold-path, age, size, identity and approval bound.
    ordinary = {key: value for key, value in payload.items() if key not in extra}
    ordinary.update(schema_version=schema_version("cold_snapshot_compression_request"),
                    operation="compress_and_retain",
                    files=[{**rows[0], "attributes": attrs & ~0x800}])
    compression.validate_request(ordinary, production_root=production_root, now=now)
    return rows


def predecessor_request_path(request, production_root):
    value = request["predecessor_request"]
    if not isinstance(value, str) or not value:
        raise ValueError("predecessor request must be an exact retained original")
    path = Path(value)
    if (not path.is_absolute() or str(path) != value
            or path.parent != production_root / "scratch/handoffs"
            or path.suffix != ".json" or path.name.startswith(".")):
        raise ValueError("predecessor request must name a direct scratch/handoffs JSON file")
    return path


def read_predecessor_request(request, wrapper, attempt, production_root):
    """Bind legacy reformatted copies to the still-retained, hash-exact approval."""
    retained = attempt / "request.json"
    expected_hash = wrapper.get("request_sha256")
    if "predecessor_request" not in request:
        return compression._read_receipt(retained, expected_hash, compression.MAX_REQUEST_BYTES)
    original = predecessor_request_path(request, production_root)
    with PinnedNtfsDirectory(original.parent):
        payload = compression._read_receipt(original, expected_hash, compression.MAX_REQUEST_BYTES)
    compression.inventory.validate_root(retained.parent)
    compression.inventory.checked_stat(retained, directory=False)
    _, retained_raw = compression.read_bounded_json(retained, compression.MAX_REQUEST_BYTES)
    canonical = (compression.json.dumps(payload, sort_keys=True, indent=2,
                                         allow_nan=False) + "\n").encode()
    if (compression.hashlib.sha256(retained_raw).hexdigest() != expected_hash
            and retained_raw != canonical):
        raise ValueError("retained request differs from hash-bound original approval")
    return payload


def read_preimage(request, candidate, *, production_root):
    path = Path(request["preimage_receipt"])
    if (not path.is_absolute()
            or path.parent.parent != production_root / "scratch/cold_snapshot_compression"
            or not re.fullmatch(r"[0-9]{3}-before\.json", path.name)):
        raise ValueError("preimage must name an exact retained compression journal")
    with PinnedNtfsDirectory(path.parent):
        preimage = compression._read_receipt(path, request["preimage_sha256"])
        wrapper = compression._read_receipt(path.parent / "wrapper-result.json",
                                             request["predecessor_wrapper_sha256"])
        old_request = read_predecessor_request(request, wrapper, path.parent, production_root)
    old_source = wrapper.get("source_git_sha", "")
    if (wrapper.get("status") != "FAILED" or wrapper.get("teardown_proved") is not True
            or wrapper.get("apply") is not True or wrapper.get("deleted_files") != 0
            or wrapper.get("cleanup_eligible") is not False
            or wrapper.get("execution_host_id") != request["execution_host_id"]
            or old_request.get("execution_host_id") != request["execution_host_id"]
            or not re.fullmatch(r"[0-9a-f]{40}", old_source)):
        raise ValueError("predecessor must be a terminal failed compression on this host")
    if (preimage.get("schema_version") != schema_version("cold_snapshot_compression_receipt")
            or preimage.get("source_git_sha") != old_source
            or preimage.get("request_sha256") != wrapper.get("request_sha256")
            or preimage.get("execution_host_id") != request["execution_host_id"]
            or preimage.get("inventory_wrapper_sha256") != old_request.get("inventory_wrapper_sha256")
            or preimage.get("path") != candidate["path"] or preimage.get("apply") is not True
            or preimage.get("action") != "COMPRESS_AND_RETAIN"
            or preimage.get("deleted_files") != 0 or preimage.get("cleanup_eligible") is not False
            or preimage.get("reclaimed_bytes") != 0
            or not re.fullmatch(r"[0-9a-f]{64}", preimage.get("sha256", ""))):
        raise ValueError("preimage does not bind the failed request and exact retained file")
    # The old approval is historical evidence, not current execution authority.
    old_rows = compression.validate_request(
        old_request, production_root=production_root,
        now=compression._utc(old_request["approved_at_utc"]))
    ordinal = int(path.name[:3])
    if ordinal >= len(old_rows):
        raise ValueError("preimage ordinal is outside the failed request")
    before = preimage.get("before", {})
    fields = {"size_bytes", "allocation_bytes", "mtime_ns", "volume_serial", "file_index",
              "attributes", "creation_filetime", "compression_format"}
    if (set(before) != fields or any(type(before[key]) is not int for key in fields)
            or before["creation_filetime"] <= 0 or before["compression_format"] != 0):
        raise ValueError("preimage lacks exact original native metadata")
    original = {"path": preimage["path"], "size_bytes": before["size_bytes"],
                "allocated_bytes": before["allocation_bytes"], "mtime_ns": str(before["mtime_ns"]),
                "device": str(before["volume_serial"]), "file_id": str(before["file_index"]),
                "attributes": before["attributes"]}
    if old_rows[ordinal] != original:
        raise ValueError("preimage native metadata differs from its original request")
    for key in ("size_bytes", "mtime_ns", "device", "file_id"):
        if candidate[key] != original[key]:
            raise ValueError("fresh inventory identity differs from the original preimage")
    return preimage


def verify_candidate(path, expected, preimage, *, guard, opener=LockedNtfsFile,
                     bytes_per_second=compression.MAX_IO_BYTES_PER_SECOND):
    """Read once through a writer-excluding handle; never request write access."""
    guard()
    with opener(path, writable=False) as opened:
        observed = opened.metadata()
        expected_native = {
            "size_bytes": expected["size_bytes"], "mtime_ns": int(expected["mtime_ns"]),
            "volume_serial": int(expected["device"]), "file_index": int(expected["file_id"]),
            "allocation_bytes": expected["allocated_bytes"], "attributes": expected["attributes"],
        }
        original = preimage["before"]
        if (any(observed[key] != value for key, value in expected_native.items())
                or any(observed[key] != original[key] for key in compression.IDENTITY_FIELDS)):
            raise ValueError("retained file native identity changed before verification")
        if observed["compression_format"] not in {0, 2}:
            raise ValueError("retained file has unsupported compression")
        if bool(observed["attributes"] & 0x800) != (observed["compression_format"] == 2):
            raise ValueError("retained file attributes differ from its compression state")
        if (observed["compression_format"] == 0
                and (observed["allocation_bytes"] != original["allocation_bytes"]
                     or observed["attributes"] != original["attributes"])):
            raise ValueError("uncompressed file allocation changed")
        digest = opened.digest(guard=guard, bytes_per_second=bytes_per_second)
        guard()
        if opened.metadata() != observed or digest != preimage["sha256"]:
            raise ValueError("retained file content or metadata does not match its preimage")
    return {"path": expected["path"], "status": "VERIFIED_RETAINED",
            "action": "VERIFY_RETAINED", "before": original, "after": observed,
            "sha256": digest, "preimage_source_git_sha": preimage["source_git_sha"],
            "reclaimed_bytes": 0, "source_files_changed": 0,
            "verified_reclaimed_bytes": original["allocation_bytes"] - observed["allocation_bytes"]}
