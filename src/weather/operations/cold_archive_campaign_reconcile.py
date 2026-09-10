"""Reconcile committed reclaim metadata after an outer-wrapper failure.

This never deletes sources or advances the authoritative ledger. An incomplete
ledger transition remains blocked for the existing explicit recovery procedure.
"""
from datetime import datetime, timezone
from pathlib import Path

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_campaign_io as io
from weather.operations import cold_archive_campaign_state as state


def require(value, message):
    if not value:
        raise state.CampaignPaused(message)


def committed_reclaim(*, wrapper, receipt, progress, entry_sha256, archive_id,
                      approval_sha256, production_root):
    outer = io.load_spec(wrapper)
    core, core_sha = locations.read_record(receipt["path"], receipt["sha256"])
    counter, counter_sha = locations.read_record(progress)
    require(outer.get("teardown_proved") is True, "reclaim child-tree teardown remains unknown")
    require(core.get("status") == "PASS" and core.get("archive_id") == archive_id
            and core.get("entry_sha256") == entry_sha256
            and core.get("owner_approval_sha256") == approval_sha256,
            "completed reclaim receipt binding differs")
    files = core.get("files")
    require(isinstance(files, list) and 1 <= len(files) <= 256
            and core.get("deleted_files") == len(files), "completed reclaim file count differs")
    allocated = sum(row["allocated_bytes"] for row in files)
    require(allocated == core.get("reclaimed_allocated_bytes"), "completed reclaim byte count differs")
    require(counter.get("status") == "READY"
            and counter.get("owner_approval_sha256") == approval_sha256
            and counter.get("last_receipt_sha256") == core_sha
            and Path(counter.get("last_receipt_path", "")) == Path(receipt["path"])
            and counter.get("reclaimed_allocated_bytes") == (
                core["previous_reclaimed_allocated_bytes"] + allocated),
            "authoritative reclaim ledger still requires reconciliation")
    attempt = Path(receipt["path"]).parent
    root = locations.safe_path(Path(production_root) / "data", directory=True)
    for index, row in enumerate(files):
        completed, _ = locations.read_record(attempt / f"file-{index:05d}.json")
        require(completed.get("status") == "DELETED" and completed.get("file") == row
                and completed.get("entry_sha256") == entry_sha256
                and completed.get("archive_id") == archive_id, "individual deletion proof differs")
        path = root.joinpath(*locations.relative_path(row["path"]).parts)
        require(not path.exists(), "reclaimed source path is present and needs inspection")
    spool = core.get("spool_cleanup")
    require(spool is None or spool.get("status") == "PASS", "temporary-payload cleanup is unproved")
    return {
        "status": "COMMITTED_RECONCILED", "archive_id": archive_id,
        "wrapper_sha256": wrapper["sha256"], "reclaim_receipt_sha256": core_sha,
        "progress_sha256": counter_sha, "deleted_files": len(files),
        "reclaimed_allocated_bytes": allocated, "new_deletions": 0}


def retain(path, result):
    path = Path(path)
    if path.exists():
        existing, _ = locations.read_record(path)
        require(all(existing.get(key) == value for key, value in result.items()),
                "reconciliation proof changed")
    else:
        catalog._write_record(path, {**result, "reconciled_at_utc": datetime.now(timezone.utc).isoformat()})
    return io.spec(path)
