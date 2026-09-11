"""Conservative primary-allocation ceiling for the approved conditional reserve.

Unreclaimed primary files are counted at their full owner-approved allocation:
a larger source cannot pass the existing stage/reclaim identity contract.
Only proved past allocation reductions and currently pinned queue protection
reduce that ceiling. No absence, estimated compression or unattempted reclaim
is counted as a saving.
"""
from __future__ import annotations

from pathlib import Path
import re

from weather import cold_archive_locations as locations
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_campaign_review as review
from weather.operations import production_cold_archive_stage as archive
from weather.schema_registry import schema_version

MAX_RECEIPTS = 512
MAX_TOTAL_METADATA_BYTES = 16 * archive.MIB
require = locations._require


def primary_capacity(*, request, approval, approval_sha256, state, campaign,
                     source_root, stack, guard):
    """Prove the full approved primary cannot reach the target under this lease."""
    root = locations.safe_path(source_root, directory=True)
    campaign = Path(campaign)
    require(campaign == root / "cold_archive" / "catalog" / "reclaims" / approval_sha256,
            "conditional reserve requires the exact canonical campaign")
    target = state["target_bytes"]
    require(type(target) is int and 0 < target <= 1024**4
            and target == approval.get("conditional_reserve", {}).get("use_only_if_qualified_primary_reclaim_is_below_bytes")
            and state.get("status") == "READY"
            and state.get("owner_approval_sha256") == approval_sha256,
            "conditional reserve requires a reconciled owner-bound campaign")
    used = 0

    def pin_metadata(path):
        nonlocal used
        guard.admit()
        path = locations.safe_path(path)
        size = path.stat().st_size
        used += size
        require(size <= locations.MAX_METADATA_BYTES and used <= MAX_TOTAL_METADATA_BYTES,
                "primary capacity metadata exceeds its bounded budget")
        stack.enter_context(bridge._file_pin(path))
        return path, size

    def read(path, expected=None, *, sealed=True):
        path, size = pin_metadata(path)
        value, digest = (locations.read_record(path, expected) if sealed
                         else archive._load(path, expected))
        guard.account(size)
        return value, digest

    owner, owner_sha = read(request["owner_approval"]["path"], request["owner_approval"]["sha256"], sealed=False)
    require(owner == approval and owner_sha == approval_sha256
            and owner.get("schema_version") == schema_version("archive_target_owner_approval"),
            "primary capacity owner approval bytes differ")
    primary_spec = approval.get("primary", {})
    name = primary_spec.get("proposal")
    require(isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9._-]+[.]json", name),
            "owner primary proposal must be an immediate JSON filename")
    locations.require_sha(primary_spec.get("sha256"))
    primary_path = Path(request["owner_approval"]["path"]).parent / name
    primary, primary_sha = read(primary_path, primary_spec["sha256"], sealed=False)
    require(primary.get("schema_version") == schema_version("archive_target_owner_review_proposal")
            and primary.get("selection_kind") == "primary"
            and Path(primary.get("source_root", "")) == root,
            "primary capacity proposal differs from the approved production selection")
    primary_rows = archive._rows(primary.get("files"))
    require(primary.get("file_count") == len(primary_rows)
            and primary.get("allocated_bytes") == sum(row["allocated_bytes"] for row in primary_rows)
            and primary.get("logical_bytes") == sum(row["size_bytes"] for row in primary_rows),
            "primary capacity proposal totals do not reconcile")
    reserve, _ = read(request["proposal"]["path"], request["proposal"]["sha256"], sealed=False)
    require(reserve.get("schema_version") == schema_version("archive_target_owner_review_proposal")
            and reserve.get("selection_kind") == "standby"
            and request["proposal"]["sha256"] == approval["conditional_reserve"]["sha256"]
            and Path(reserve.get("source_root", "")) == root,
            "primary capacity requires the owner-bound conditional reserve")
    approved = {"primary": {row["path"]: row for row in primary_rows},
                "conditional_reserve": {row["path"]: row for row in archive._rows(reserve.get("files"))}}
    require(not (approved["primary"].keys() & approved["conditional_reserve"].keys()),
            "primary and reserve selections overlap")
    children = list(campaign.iterdir())
    require(len(children) <= MAX_RECEIPTS + 2, "primary capacity receipt count exceeds bound")
    receipts, all_removed, primary_removed, archives = [], set(), {}, set()
    for child in sorted(children):
        if child.name in {"progress", "progress.json"}:
            continue
        guard.admit()
        locations.archive_id(child.name)
        stack.enter_context(archive._directory_pin(locations.safe_path(child, directory=True)))
        receipt_path = child / "receipt.json"
        receipt, digest = read(receipt_path)
        kind = receipt.get("selection_kind")
        require(receipt.get("schema_version") == schema_version("cold_archive_reclaim_receipt")
                and receipt.get("status") == "PASS" and receipt.get("attempt_id") == child.name
                and receipt.get("owner_approval_sha256") == approval_sha256
                and receipt.get("target_bytes") == target and kind in approved,
                "primary capacity found an unqualified reclaim receipt")
        aid = locations.archive_id(receipt.get("archive_id"))
        require(aid not in archives, "primary capacity archive was counted twice")
        archives.add(aid)
        entry_path = root / "cold_archive" / "catalog" / "archives" / aid / "upload.json"
        locations.require_sha(receipt.get("entry_sha256"))
        locations.require_sha(receipt.get("plan_sha256"))
        entry, _ = read(entry_path, receipt["entry_sha256"])
        require(entry.get("schema_version") == schema_version("cold_archive_catalog_entry")
                and entry.get("status") == "UPLOADED" and entry.get("archive_id") == aid and Path(entry.get("source_root", "")) == root
                and entry.get("plan_sha256") == receipt.get("plan_sha256"),
                "primary capacity receipt belongs to a different archive")
        archive._rows(entry.get("files"))
        members = {row["path"]: row for row in entry["files"]}
        rows = archive._rows(receipt.get("files"))
        require(len(rows) == len(members)
                and type(receipt.get("deleted_files")) is int and receipt["deleted_files"] == len(rows)
                and type(receipt.get("reclaimed_allocated_bytes")) is int
                and receipt["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in rows)
                and type(receipt.get("previous_reclaimed_allocated_bytes")) is int
                and receipt["previous_reclaimed_allocated_bytes"] >= 0,
                "primary capacity receipt counters do not reconcile")
        for original, row in zip(sorted(receipt["files"], key=lambda item: item["path"]), rows):
            require(row["path"] not in all_removed and row["path"] in approved[kind]
                    and archive._matches_source(approved[kind][row["path"]], row)
                    and members.get(row["path"]) == original,
                    "primary capacity source identity, allocation or archive member differs")
            locations.require_sha(original.get("sha256"))
            all_removed.add(row["path"])
            if kind == "primary":
                primary_removed[row["path"]] = row
        receipts.append((receipt, digest, str(receipt_path)))
    require(1 <= len(receipts) <= MAX_RECEIPTS
            and type(state.get("sequence")) is int and state["sequence"] == len(receipts)
            and state.get("deleted_files") == len(all_removed),
            "primary capacity campaign file or receipt count differs")
    total = 0
    for receipt, _, _ in sorted(receipts, key=lambda item: (
            item[0]["previous_reclaimed_allocated_bytes"],
            item[0]["reclaimed_allocated_bytes"] > 0)):
        require(receipt["previous_reclaimed_allocated_bytes"] == total,
                "primary capacity reclaim history is not contiguous")
        total += receipt["reclaimed_allocated_bytes"]
    last = [item for item in receipts if Path(item[2]) == Path(state.get("last_receipt_path", ""))]
    require(total == state.get("reclaimed_allocated_bytes")
            and len(last) == 1 and last[0][1] == state.get("last_receipt_sha256")
            and last[0][0]["attempt_id"] == state.get("attempt_id")
            and last[0][0]["previous_reclaimed_allocated_bytes"]
                + last[0][0]["reclaimed_allocated_bytes"] == total,
            "primary capacity history differs from the current campaign pointer")

    class PinnedObservations(review.Observations):
        def text(self, path, maximum=2 * archive.MIB):
            path, size = pin_metadata(path)
            value = super().text(path, maximum)
            guard.account(size)
            return value

    observations = PinnedObservations()
    protected, queue_path, audit_path = review.protected_queue_events(
        production_root=root.parent, observations=observations)
    remaining = [row for row in primary_rows if row["path"] not in primary_removed]
    excluded = [row for row in remaining if row["path"].split("/")[1] in protected]
    possible = [row for row in remaining if row["path"].split("/")[1] not in protected]
    reclaimed_bytes = sum(row["allocated_bytes"] for row in primary_removed.values())
    possible_bytes = sum(row["allocated_bytes"] for row in possible)
    upper_bound = reclaimed_bytes + possible_bytes
    require(upper_bound < target,
            "qualified primary allocation ceiling can still reach the approved target")
    guard.admit()
    return {
        "primary_proposal_sha256": primary_sha, "primary_file_count": len(primary_rows),
        "primary_reclaimed_file_count": len(primary_removed),
        "primary_reclaimed_allocated_bytes": reclaimed_bytes,
        "unreclaimed_primary_file_count": len(possible),
        "unreclaimed_primary_allocated_bytes_upper_bound": possible_bytes,
        "queue_protected_primary_file_count": len(excluded),
        "queue_protected_primary_approved_allocated_bytes": sum(row["allocated_bytes"] for row in excluded),
        "queue_protected_events": sorted({row["path"].split("/")[1] for row in excluded}),
        "queue_evidence": [observations.spec(queue_path), observations.spec(audit_path)],
        "qualified_primary_allocated_bytes_upper_bound": upper_bound,
        "target_bytes": target, "campaign_sequence": state["sequence"],
        "reclaim_receipts": [{"path": path, "sha256": digest} for _, digest, path in receipts],
        "source_payload_bytes_read": 0, "metadata_bytes_read": used,
    }
