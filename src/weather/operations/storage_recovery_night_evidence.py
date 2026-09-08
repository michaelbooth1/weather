"""Strict receipt reconciliation for the bounded one-night storage controller."""
from __future__ import annotations

from weather.operations import cold_snapshot_compression as compression
from weather.operations import storage_recovery_night_contract as contract

NATIVE_FIELDS = frozenset({"size_bytes", "allocation_bytes", "mtime_ns", "volume_serial",
                          "file_index", "attributes", "creation_filetime", "compression_format"})
CORE = ("path", "before", "after", "sha256", "status", "action", "reclaimed_bytes")


def native(value):
    if (not isinstance(value, dict) or set(value) != NATIVE_FIELDS
            or any(type(v) is not int or v < 0 for v in value.values())
            or value["creation_filetime"] <= 0):
        raise ValueError("exact native receipt fields required")
    return value


def expected_native(candidate, before):
    native(before)
    observed = {"path": candidate["path"], "size_bytes": before["size_bytes"],
                "allocated_bytes": before["allocation_bytes"], "mtime_ns": str(before["mtime_ns"]),
                "device": str(before["volume_serial"]), "file_id": str(before["file_index"]),
                "attributes": before["attributes"]}
    if observed != candidate:
        raise ValueError("journal native metadata differs from its exact request")


def common(value, request_sha, plan):
    if (not isinstance(value, dict) or value.get("source_git_sha") != plan["source_git_sha"]
            or value.get("request_sha256") != request_sha
            or value.get("execution_host_id") != plan["execution_host_id"]
            or value.get("owner_approved_exception", "") != ""
            or value.get("deleted_files") != 0 or value.get("cleanup_eligible") is not False):
        raise ValueError("attempt source, host, request or retention binding mismatch")


def validate_wrapper(wrapper, *, request_sha, plan, kind):
    common(wrapper, request_sha, plan)
    if (wrapper.get("teardown_proved") is not True or wrapper.get("hard_stop") is not False
            or wrapper.get("status") not in {"PASS", "FAILED"}):
        raise ValueError("missing, hard-stopped or unproved wrapper teardown")
    if kind != "inventory":
        if wrapper.get("apply") is not (kind == "apply"):
            raise ValueError("wrapper operation binding mismatch")
        if (wrapper.get("verify_retained") is True) != (kind == "verify"):
            raise ValueError("wrapper verification mode mismatch")
    if wrapper["status"] == "PASS":
        contract.digest(wrapper.get("child_result_sha256"))


def validate_result_header(result, request, request_sha, plan, kind):
    common(result, request_sha, plan)
    schema = ("storage_recovery_inventory_receipt" if kind == "inventory" else
              "cold_snapshot_verification_receipt" if kind == "verify" else "cold_snapshot_compression_receipt")
    if result.get("schema_version") != compression.schema_version(schema):
        raise ValueError("child result schema mismatch")
    if kind != "inventory":
        if (result.get("apply") is not (kind == "apply")
                or result.get("inventory_wrapper_sha256") != request["inventory_wrapper_sha256"]):
            raise ValueError("child operation or inventory binding mismatch")


def ledger_row(row, *, original_attempt, after_hash, before_hash, verification_attempt=None):
    before, after = native(row["before"]), native(row["after"])
    value = {
        "path": row["path"], "sha256": contract.digest(row["sha256"]),
        "allocation_saving_bytes": before["allocation_bytes"] - after["allocation_bytes"],
        "allocation_before_bytes": before["allocation_bytes"],
        "allocation_after_bytes": after["allocation_bytes"],
        "native_identity": {key: after[key] for key in compression.IDENTITY_FIELDS},
        "original_attempt": original_attempt, "before_journal_sha256": before_hash,
        "completion_receipt_sha256": after_hash,
    }
    if verification_attempt:
        value["verification_attempt"] = verification_attempt
        value["verification_command_reclaimed_bytes"] = 0
    return value


def inspect_apply(request, wrapper, result, journals, *, request_sha, plan):
    """Accept only a contiguous journal prefix and at most one unmatched preimage."""
    validate_wrapper(wrapper, request_sha=request_sha, plan=plan, kind="apply")
    candidates = compression.validate_request(request, production_root=contract.canonical_absolute(plan["production_repo_root"]),
                                               now=contract.utc(request["approved_at_utc"]))
    if result is not None:
        validate_result_header(result, request, request_sha, plan, "apply")
    completed, pending, gap = [], None, False
    expected_names = set()
    for index, candidate in enumerate(candidates):
        before_name, after_name = f"{index:03d}-before.json", f"{index:03d}-after.json"
        expected_names.update((before_name, after_name))
        before, after = journals.get(before_name), journals.get(after_name)
        if before is None:
            if after is not None:
                raise ValueError("completion without a durable preimage")
            gap = True
            continue
        if gap or pending is not None:
            raise ValueError("noncontiguous or multiple unmatched preimages")
        common(before, request_sha, plan)
        if (before.get("schema_version") != compression.schema_version("cold_snapshot_compression_receipt")
                or before.get("path") != candidate["path"] or before.get("apply") is not True
                or before.get("action") != "COMPRESS_AND_RETAIN" or before.get("reclaimed_bytes") != 0
                or before.get("inventory_wrapper_sha256") != request["inventory_wrapper_sha256"]):
            raise ValueError("preimage journal binding mismatch")
        expected_native(candidate, before["before"])
        if before["before"]["compression_format"] != 0:
            raise ValueError("preimage was already compressed")
        contract.digest(before.get("sha256"))
        if after is None:
            pending = {"ordinal": index, "path": candidate["path"], "preimage": before}
            continue
        common(after, request_sha, plan)
        if (after.get("schema_version") != compression.schema_version("cold_snapshot_compression_receipt")
                or after.get("apply") is not True or after.get("action") != "COMPRESS_AND_RETAIN"
                or after.get("status") != "VERIFIED" or after.get("path") != candidate["path"]
                or after.get("sha256") != before["sha256"] or after.get("before") != before["before"]
                or after.get("inventory_wrapper_sha256") != request["inventory_wrapper_sha256"]):
            raise ValueError("completion journal differs from its preimage")
        observed = native(after["after"])
        if (observed["compression_format"] != 2 or observed["attributes"] not in {0x800, 0x820}
                or any(observed[k] != before["before"][k] for k in compression.IDENTITY_FIELDS)
                or type(after.get("reclaimed_bytes")) is not int or after["reclaimed_bytes"] <= 0
                or after["reclaimed_bytes"] != before["before"]["allocation_bytes"] - observed["allocation_bytes"]):
            raise ValueError("completion lacks positive unchanged-identity allocation savings")
        completed.append(after)
    if set(journals) - expected_names:
        raise ValueError("unexpected compression journal")
    if result is not None:
        rows = result.get("results")
        if (not isinstance(rows, list) or len(rows) != len(completed)
                or any({k: a.get(k) for k in CORE} != {k: b.get(k) for k in CORE}
                       for a, b in zip(rows, completed))
                or result.get("reclaimed_bytes") != sum(row["reclaimed_bytes"] for row in completed)):
            raise ValueError("terminal result differs from the completed journals")
    if wrapper["status"] == "PASS":
        if (result is None or result.get("status") != "PASS" or pending is not None
                or len(completed) != len(candidates)
                or wrapper.get("reclaimed_bytes") != result["reclaimed_bytes"]):
            raise ValueError("PASS does not cover every approved file")
    else:
        if result is not None and not contract.memory_refusal(result.get("error")):
            raise ValueError("failed compression is not an approved memory-only interruption")
    return completed, pending


def reconcile_inventory(rows, manifest):
    indexed = {row["path"]: row for row in manifest["files"]}
    if len(indexed) != len(manifest["files"]):
        raise ValueError("duplicate fresh inventory path")
    complete = {row["path"] for row in manifest["folders"] if row["status"] == "COMPLETE"}
    for saved in rows:
        expected = saved["native_identity"]
        current = indexed.get(saved["path"])
        if (current is None or "/".join(saved["path"].split("/")[:2]) not in complete
                or current["size_bytes"] != contract.native_integer(expected["size_bytes"])
                or contract.native_integer(current["mtime_ns"]) != contract.native_integer(expected["mtime_ns"])
                or contract.native_integer(current["device"]) != contract.native_integer(expected["volume_serial"])
                or contract.native_integer(current["file_id"]) != contract.native_integer(expected["file_index"])
                or current["allocated_bytes"] != saved["allocation_after_bytes"]
                or current["attributes"] not in {0x800, 0x820}):
            raise ValueError("completed file differs from fresh inventory: " + saved["path"])


def inspect_verification(request, wrapper, result, preimage, *, request_sha, plan):
    validate_wrapper(wrapper, request_sha=request_sha, plan=plan, kind="verify")
    validate_result_header(result, request, request_sha, plan, "verify")
    if (wrapper["status"] != "PASS" or result.get("status") != "PASS"
            or result.get("verify_retained") is not True
            or result.get("source_files_changed") != 0 or result.get("reclaimed_bytes") != 0
            or wrapper.get("source_files_changed") != 0 or wrapper.get("reclaimed_bytes") != 0
            or result.get("preimage_sha256") != request["preimage_sha256"]
            or result.get("predecessor_wrapper_sha256") != request["predecessor_wrapper_sha256"]
            or len(result.get("results", [])) != 1):
        raise ValueError("read-only verification is incomplete or changed source files")
    row = result["results"][0]
    before, after = native(row["before"]), native(row["after"])
    if (row.get("path") != request["files"][0]["path"] or before != preimage["before"]
            or row.get("sha256") != preimage["sha256"] or row.get("action") != "VERIFY_RETAINED"
            or row.get("status") != "VERIFIED_RETAINED" or row.get("reclaimed_bytes") != 0
            or row.get("source_files_changed") != 0
            or any(after[k] != before[k] for k in compression.IDENTITY_FIELDS)
            or after["compression_format"] not in {0, 2}):
        raise ValueError("verification does not match its original preimage")
    delta = before["allocation_bytes"] - after["allocation_bytes"]
    if (row.get("verified_reclaimed_bytes") != delta or result.get("verified_reclaimed_bytes") != delta
            or wrapper.get("verified_reclaimed_bytes") != delta):
        raise ValueError("prior allocation savings do not reconcile")
    if after["compression_format"] == 0:
        if after != before or delta != 0:
            raise ValueError("uncompressed retained file changed")
    elif delta <= 0:
        raise ValueError("retained compression supplied no positive savings")
    return row
