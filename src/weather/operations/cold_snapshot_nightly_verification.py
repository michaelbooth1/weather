"""Read-only verification of an unfinished file in a failed nightly batch.

A nightly attempt can stop after a file's before-journal and before its
after-journal (for example, admission loss after NTFS compression). This binds
that exact before-journal, its batch selection and the failed attempt, then
re-reads the retained file once through a writer-excluding handle and proves its
SHA-256, native identity and compression state. It never compresses, rewrites,
deletes or retries anything. The resulting verification attempt is the only
evidence ``cold_snapshot_nightly_resolution`` accepts for an unfinished file.

Run through ``cold_snapshot_compression_run.ps1 -VerifyRetained`` with a
``cold_snapshot_nightly_verification_request``.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
from pathlib import Path
import re

from weather.operations import cold_snapshot_compression as cold
from weather.operations import cold_snapshot_nightly as nightly
from weather.operations import storage_recovery_inventory as inventory
from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
from weather.schema_registry import schema_version

ATTEMPT = re.compile(r"nightly-[0-9]{8}-[0-9A-Za-z-]{1,64}")
BATCH = re.compile(r"batch-[0-9]{4}")
JOURNAL = re.compile(r"([0-9]{3})-(before|after)\.json")
SHA256 = re.compile(r"[0-9a-f]{64}")
OPERATION = "verify_retained_nightly"
REQUEST_FIELDS = {"schema_version", "production_repo_root", "execution_host_id", "operation",
                  "approved_by", "approved_at_utc", "expires_at_utc", "attempt", "batch", "ordinal",
                  "preimage_sha256", "predecessor_wrapper_sha256"}
BEFORE_FIELDS = {"size_bytes", "allocation_bytes", "mtime_ns", "volume_serial", "file_index",
                 "attributes", "creation_filetime", "compression_format"}
COMPRESSED = 0x800
NORMAL = 0x80


def is_request(payload):
    return (isinstance(payload, dict)
            and payload.get("schema_version") == schema_version("cold_snapshot_nightly_verification_request"))


def validate_request(payload, *, production_root, now):
    if not isinstance(payload, dict) or set(payload) != REQUEST_FIELDS:
        raise ValueError("nightly verification request fields do not match the exact contract")
    if not is_request(payload) or payload["operation"] != OPERATION:
        raise ValueError("explicit read-only nightly retained-file verification is required")
    if Path(payload["production_repo_root"]) != production_root:
        raise ValueError("production repository binding mismatch")
    if not isinstance(payload["approved_by"], str) or not 0 < len(payload["approved_by"].strip()) <= 128:
        raise ValueError("named approval required")
    for key in ("execution_host_id", "preimage_sha256", "predecessor_wrapper_sha256"):
        if not isinstance(payload[key], str) or not SHA256.fullmatch(payload[key]):
            raise ValueError("host and evidence identities must be exact SHA-256")
    approved, expires = cold._utc(payload["approved_at_utc"]), cold._utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("request is expired, future-dated or overlong")
    if not isinstance(payload["attempt"], str) or not ATTEMPT.fullmatch(payload["attempt"]):
        raise ValueError("attempt must be one exact nightly-YYYYMMDD-* directory name")
    if not isinstance(payload["batch"], str) or not BATCH.fullmatch(payload["batch"]):
        raise ValueError("batch must be one exact batch-NNNN directory name")
    if type(payload["ordinal"]) is not int or not 0 <= payload["ordinal"] < cold.MAX_FILES:
        raise ValueError("ordinal must name one file inside a nightly batch")
    return payload


def _sha256_receipt(path, maximum=cold.MAX_RECEIPT_BYTES):
    inventory.checked_stat(path, directory=False)
    payload, raw = cold.read_bounded_json(path, maximum)
    return payload, hashlib.sha256(raw).hexdigest()


def check_failed_attempt(wrapper, result, host):
    if (wrapper.get("status") != "FAILED" or wrapper.get("teardown_proved") is not True
            or wrapper.get("hard_stop") is not False or wrapper.get("apply") is not True
            or wrapper.get("deleted_files") != 0 or wrapper.get("cleanup_eligible") is not False
            or wrapper.get("execution_host_id") != host
            or not re.fullmatch(r"[0-9a-f]{40}", str(wrapper.get("source_git_sha", "")))):
        raise ValueError("predecessor must be a torn-down FAILED nightly apply on this host")
    if (result.get("schema_version") != schema_version("cold_snapshot_nightly_receipt")
            or result.get("status") != "FAILED_RETAIN_AND_INSPECT"
            or result.get("source_git_sha") != wrapper.get("source_git_sha")
            or result.get("request_sha256") != wrapper.get("request_sha256")
            or result.get("execution_host_id") != host or result.get("apply") is not True
            or result.get("deleted_files") != 0 or result.get("cleanup_eligible") is not False):
        raise ValueError("child result does not bind the failed nightly attempt")


def unfinished_journal(batch, ordinal):
    """The batch's started prefix must end at exactly this unfinished ordinal."""
    phases = {}
    for entry in batch.iterdir():
        match = JOURNAL.fullmatch(entry.name)
        if match:
            phases.setdefault(int(match.group(1)), set()).add(match.group(2))
        elif entry.name != "selection.json":
            raise ValueError(f"unexpected file in unfinished {batch.name}: {entry.name}")
    if sorted(phases) != list(range(ordinal + 1)):
        raise ValueError("ordinal is not the last started file of a contiguous batch prefix")
    if any(phases[index] != {"before", "after"} for index in range(ordinal)):
        raise ValueError("an earlier file in the batch is also unfinished")
    if phases[ordinal] != {"before"}:
        raise ValueError("file already has an after-journal; resolve it without verification")
    return batch / f"{ordinal:03d}-before.json"


def check_preimage(preimage, row, *, now):
    before = preimage.get("before")
    if (set(preimage) != {"path", "before", "sha256", "action"} or preimage["path"] != row.get("path")
            or preimage["action"] != "COMPRESS_AND_RETAIN"
            or not isinstance(preimage["sha256"], str) or not SHA256.fullmatch(preimage["sha256"])):
        raise ValueError("before-journal does not bind its selected file and an exact SHA-256")
    if (not isinstance(before, dict) or set(before) != BEFORE_FIELDS
            or any(type(before[key]) is not int for key in BEFORE_FIELDS)
            or before["creation_filetime"] <= 0 or before["compression_format"] != 0):
        raise ValueError("before-journal lacks exact original native metadata")
    selected = {"size_bytes": before["size_bytes"], "allocated_bytes": before["allocation_bytes"],
                "mtime_ns": str(before["mtime_ns"]), "device": str(before["volume_serial"]),
                "file_id": str(before["file_index"]), "attributes": before["attributes"]}
    if any(row.get(key) != value for key, value in selected.items()):
        raise ValueError("before-journal native metadata differs from its batch selection")
    if not nightly.eligible(row, now=now):
        raise ValueError("selected file is outside the nightly cold-file contract")


def read_preimage(request, *, production_root, now):
    """Return (selection row, preimage) for one exact unfinished nightly file."""
    attempt = inventory.validate_root(production_root / "scratch" / cold.WORKLOAD / request["attempt"])
    batch = inventory.validate_root(attempt / request["batch"])
    batches = sorted(p.name for p in attempt.iterdir() if p.is_dir() and BATCH.fullmatch(p.name))
    if not batches or batches[-1] != request["batch"]:
        raise ValueError("only the last batch of a failed nightly attempt can hold an unfinished file")
    with PinnedNtfsDirectory(attempt):
        wrapper = cold._read_receipt(attempt / "wrapper-result.json", request["predecessor_wrapper_sha256"])
        result, _ = _sha256_receipt(attempt / "result.json")
        check_failed_attempt(wrapper, result, request["execution_host_id"])
        policy = cold._read_receipt(attempt / "request.json", wrapper["request_sha256"], cold.MAX_REQUEST_BYTES)
        if policy.get("execution_host_id") != request["execution_host_id"]:
            raise ValueError("failed nightly policy does not bind this host")
        with PinnedNtfsDirectory(batch):
            path = unfinished_journal(batch, request["ordinal"])
            preimage = cold._read_receipt(path, request["preimage_sha256"])
            selection, _ = _sha256_receipt(batch / "selection.json")
        files = selection.get("files")
        if (not re.fullmatch(r"inventory-[0-9]{4}\.json", str(selection.get("inventory")))
                or not isinstance(files, list) or request["ordinal"] >= len(files)):
            raise ValueError("batch selection does not bind its inventory and ordinal")
        manifest = cold._read_receipt(attempt / selection["inventory"],
                                      selection.get("inventory_sha256"), inventory.MAX_OUTPUT_BYTES)
    row = files[request["ordinal"]]
    if manifest.get("status") != "PASS" or row not in manifest.get("files", []):
        raise ValueError("selected file is absent from its PASS nightly inventory")
    check_preimage(preimage, row, now=now)
    return row, preimage


def retained_state(before, observed):
    """Refuse any native identity or compression state the interrupted file cannot have."""
    if any(observed.get(key) != before[key] for key in cold.IDENTITY_FIELDS):
        raise ValueError("retained file native identity changed before verification")
    form = observed.get("compression_format")
    if form not in {0, 2} or bool(observed["attributes"] & COMPRESSED) != (form == 2):
        raise ValueError("retained file compression state is not uncompressed or LZNT1")
    if form == 0 and (observed["allocation_bytes"] != before["allocation_bytes"]
                      or observed["attributes"] != before["attributes"]):
        raise ValueError("uncompressed retained file allocation or attributes changed")
    if form == 2 and observed["attributes"] != (before["attributes"] & ~NORMAL) | COMPRESSED:
        raise ValueError("compressed retained file attributes differ from its preimage")


def verify_candidate(path, request, row, preimage, *, guard, opener=nightly.LARGE_OPENER,
                     bytes_per_second=cold.MAX_IO_BYTES_PER_SECOND):
    """Read once through a writer-excluding handle; never request write access."""
    guard()
    before = preimage["before"]
    with opener(path, writable=False) as opened:
        observed = opened.metadata()
        retained_state(before, observed)
        digest = opened.digest(guard=guard, bytes_per_second=bytes_per_second)
        guard()
        if opened.metadata() != observed or digest != preimage["sha256"]:
            raise ValueError("retained file content or metadata does not match its preimage")
    return {"path": row["path"], "status": "VERIFIED_RETAINED", "action": "VERIFY_RETAINED",
            "attempt": request["attempt"], "batch": request["batch"], "ordinal": request["ordinal"],
            "preimage_sha256": request["preimage_sha256"], "before": before, "after": observed,
            "sha256": digest, "reclaimed_bytes": 0, "source_files_changed": 0,
            "verified_reclaimed_bytes": before["allocation_bytes"] - observed["allocation_bytes"]}


def accept(root, attempt_name, wrapper_sha256, batch, ordinal, preimage_path, row, preimage,
           verification_wrapper, verification_sha256):
    """Bind a PASS verification attempt to one unfinished resolution row, or refuse."""
    path = Path(verification_wrapper)
    parent = root / "scratch" / cold.WORKLOAD
    if (not path.is_absolute() or path.parent.parent != parent or path.name != "wrapper-result.json"
            or ATTEMPT.fullmatch(path.parent.name) or path.parent.name == "resolved-nightly"):
        raise ValueError("verification must name one exact verification attempt wrapper receipt")
    if not isinstance(verification_sha256, str) or not SHA256.fullmatch(verification_sha256):
        raise ValueError("verification wrapper SHA-256 required")
    folder = inventory.validate_root(path.parent)
    wrapper = cold._read_receipt(path, verification_sha256)
    if (wrapper.get("status") != "PASS" or wrapper.get("verify_retained") is not True
            or wrapper.get("teardown_proved") is not True or wrapper.get("hard_stop") is not False
            or wrapper.get("apply") is not False or wrapper.get("deleted_files") != 0
            or wrapper.get("cleanup_eligible") is not False or wrapper.get("source_files_changed") != 0
            or wrapper.get("reclaimed_bytes") != 0):
        raise ValueError("verification wrapper is not a torn-down read-only PASS")
    result = cold._read_receipt(folder / "result.json", wrapper.get("child_result_sha256"))
    request = cold._read_receipt(folder / "request.json", wrapper.get("request_sha256"), cold.MAX_REQUEST_BYTES)
    _, journal_sha256 = _sha256_receipt(preimage_path)
    rows = result.get("results")
    if (result.get("schema_version") != schema_version("cold_snapshot_verification_receipt")
            or result.get("status") != "PASS" or result.get("verify_retained") is not True
            or result.get("apply") is not False or result.get("source_files_changed") != 0
            or result.get("reclaimed_bytes") != 0 or result.get("deleted_files") != 0
            or result.get("cleanup_eligible") is not False
            or result.get("request_sha256") != wrapper.get("request_sha256")
            or result.get("source_git_sha") != wrapper.get("source_git_sha")
            or result.get("execution_host_id") != wrapper.get("execution_host_id")
            or not is_request(request) or request.get("operation") != OPERATION
            or request.get("execution_host_id") != wrapper.get("execution_host_id")
            or (request.get("attempt"), request.get("batch"), request.get("ordinal"))
            != (attempt_name, batch, ordinal)
            or request.get("predecessor_wrapper_sha256") != wrapper_sha256
            or request.get("preimage_sha256") != journal_sha256
            or not isinstance(rows, list) or len(rows) != 1):
        raise ValueError("verification attempt does not bind this unfinished nightly file")
    proof = rows[0]
    if (preimage.get("path") != row["path"] or preimage.get("action") != "COMPRESS_AND_RETAIN"
            or proof.get("status") != "VERIFIED_RETAINED" or proof.get("path") != row["path"]
            or proof.get("sha256") != preimage["sha256"] or proof.get("before") != preimage["before"]
            or proof.get("preimage_sha256") != journal_sha256
            or (proof.get("attempt"), proof.get("batch"), proof.get("ordinal")) != (attempt_name, batch, ordinal)
            or proof.get("reclaimed_bytes") != 0 or proof.get("source_files_changed") != 0
            or proof.get("verified_reclaimed_bytes")
            != preimage["before"]["allocation_bytes"] - proof.get("after", {}).get("allocation_bytes", 0)):
        raise ValueError("verification result is not an equal-hash VERIFIED_RETAINED proof")
    retained_state(preimage["before"], proof["after"])
    return {"verification_wrapper_sha256": verification_sha256,
            "reclaimed_bytes": proof["verified_reclaimed_bytes"]}
