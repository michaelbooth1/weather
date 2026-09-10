"""Completed deletion is reconciled from native-owner receipts, never repeated."""
import pytest
from weather.operations import cold_archive_campaign_reconcile as reconcile
from weather.operations import cold_archive_campaign_io as io
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_campaign_state as state


def test_committed_delete_with_failed_outer_wrapper_needs_no_new_delete(tmp_path):
    (tmp_path / "data").mkdir()
    attempt = tmp_path / "attempt"; attempt.mkdir()
    row = {"path": "snapshots/event/file.jsonl", "allocated_bytes": 4096}
    wrapper, _ = catalog._write_record(tmp_path / "wrapper.json", {
        "status": "FAILED", "teardown_proved": True})
    fields = {"archive_id": "a1", "entry_sha256": "e" * 64, "owner_approval_sha256": "a" * 64}
    catalog._write_record(attempt / "file-00000.json", {**fields, "status": "DELETED", "file": row})
    core, core_sha = catalog._write_record(attempt / "receipt.json", {
        **fields, "status": "PASS", "files": [row], "deleted_files": 1,
        "reclaimed_allocated_bytes": 4096, "previous_reclaimed_allocated_bytes": 8192})
    progress = tmp_path / "progress.json"
    catalog._write_record(progress, {
        "status": "READY", "owner_approval_sha256": "a" * 64,
        "last_receipt_path": str(attempt / "receipt.json"), "last_receipt_sha256": core_sha,
        "reclaimed_allocated_bytes": 12288})
    args = dict(wrapper=io.spec(tmp_path / "wrapper.json"), receipt=io.spec(attempt / "receipt.json"),
                progress=progress, entry_sha256="e" * 64, archive_id="a1", approval_sha256="a" * 64,
                production_root=tmp_path)
    before = progress.read_bytes()
    result = reconcile.committed_reclaim(**args)
    assert result["status"] == "COMMITTED_RECONCILED"
    assert result["new_deletions"] == 0 and result["reclaimed_allocated_bytes"] == 4096
    retained = reconcile.retain(tmp_path / "reconciliation.json", result)
    assert reconcile.retain(tmp_path / "reconciliation.json", result) == retained
    assert progress.read_bytes() == before
    catalog._write_record(tmp_path / "uncertain.json", {"status": "IN_PROGRESS"})
    with pytest.raises(state.CampaignPaused, match="ledger"):
        reconcile.committed_reclaim(**{**args, "progress": tmp_path / "uncertain.json"})
