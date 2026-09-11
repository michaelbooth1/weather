"""Plain uploads reuse exact original removal after real full-archive parity proofs."""
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_plain as plain
from weather.operations import cold_archive_reclaim as reclaim
from weather.operations import production_cold_archive_reclaim_cli as cli
from weather.schema_registry import schema_version
from tests.operations import test_cold_archive_catalog as fixtures
from tests.operations.test_cold_archive_catalog import corpus
from tests.operations.test_cold_archive_reclaim import native_source_metadata, record

BACKUP = "c" * 64
APPROVAL = "b" * 64


@pytest.fixture
def plain_case(corpus, monkeypatch, request):
    c = corpus
    aid = "plain-fixture"
    source = c.tmp / "workstation/scratch/ac-in" / aid / "archive.tar.gz"
    downloaded = c.tmp / "workstation/scratch/ac-backup" / (aid + "u2") / "downloaded-archive.tar.gz"
    for path in (source, downloaded):
        path.parent.mkdir(parents=True)
        shutil.copyfile(c.args["production_manifest"].parent / "archive.tar.gz", path)
    uploaded = {
        "schema_version": schema_version("cold_archive_plain_upload"), "status": "PASS",
        "attempt_id": aid + "u2", "execution_host_id": BACKUP, "payload_encryption": "none",
        "bundle_sha256": c.manifest["archive_sha256"], "bytes": c.manifest["archive_bytes"],
        "source_path": str(source), "downloaded_path": str(downloaded),
        "independent_download_verified": True, "originals_deleted": 0,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "drive": {"root_folder_id": "folder_123456789", "object_id": "object_123456789",
                  "remote_key": aid + "u1-archive.tar.gz", "bytes": c.manifest["archive_bytes"],
                  "hashes": {"sha256": c.manifest["archive_sha256"]}}}
    upload_spec = record(c.tmp / "plain-upload.json", uploaded)
    now = datetime.now(timezone.utc)
    req = {
        "schema_version": schema_version("production_cold_archive_plain_reclaim_request"),
        "production_repo_root": str(c.tmp), "execution_host_id": "e" * 64, "operation": "reclaim",
        "approved_by": "fixture owner", "approved_at_utc": (now - timedelta(seconds=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(), "source_git_sha": "f" * 40,
        "attempt_id": aid + "r1", "archive_id": aid, "payload_encryption": "none",
        "production_manifest": {"path": str(c.args["production_manifest"]),
                                "sha256": c.args["production_manifest_sha256"]},
        "production_receipt": {"path": str(c.args["production_receipt"]),
                               "sha256": c.args["production_receipt_sha256"]},
        "plain_upload": upload_spec,
        **{name: {"path": str(c.tmp / (name + ".json")), "sha256": "a" * 64}
           for name in ("owner_approval", "proposal", "selection", "plan")}}
    monkeypatch.setattr(reclaim, "_approval", lambda *args: (
        {"approved_by": "fixture owner", "owner_instruction": "archive the selected fixture files"},
        APPROVAL, "primary", 100_000_000_000))
    monkeypatch.setattr(reclaim, "verify_consumer_adoption", lambda *args: None)
    if not request.node.name.startswith("test_native"):
        monkeypatch.setattr(reclaim, "_removal_pin", fixtures.FixtureRemoval)
        monkeypatch.setattr(reclaim.spool, "_removal_pin", fixtures.FixtureRemoval)
    def review_sources(*, entry, entry_sha256, output_root, **kwargs):
        output_root.mkdir()
        evidence = record(output_root / "evidence.json", {"fixture_only": True}, sealed=False)
        checks = {name: {"status": "PASS", "evidence": [evidence]} for name in reclaim.SELECTION_CHECKS}
        checks["market_day_closed"]["closed"] = True
        checks["settlement_final"].update(settled=True, settlement_state="settled_countable")
        for name in checks:
            if name.endswith("_clear"):
                checks[name]["open_references"] = []
        return record(output_root / "review.json", {
            "schema_version": schema_version("cold_archive_source_review"), "status": "PASS",
            "entry_sha256": entry_sha256, "archive_id": entry["archive_id"],
            "files": [{"path": row["path"], "sha256": row["sha256"]} for row in entry["files"]],
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "expires_at_utc": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
            "checks": checks})
    monkeypatch.setattr(plain.review, "review_sources", review_sources)
    output = c.tmp / "plain-attempt"
    output.mkdir()
    return SimpleNamespace(c=c, request=req, uploaded=uploaded, output=output)


def prepare(case):
    return plain.prepare_request(case.request, production_root=case.c.tmp, backup_host_id=BACKUP,
                                 output_root=case.output, admission=lambda: True,
                                 deadline_monotonic=time.monotonic() + 30)


def remove(case, request):
    return reclaim.reclaim_chunk(request=request, source_root=case.c.tmp, production_root=case.c.tmp,
                                 backup_host_id=BACKUP, capture_loops=[], admission=lambda: True,
                                 deadline_monotonic=time.monotonic() + 30)


@pytest.mark.parametrize("fault", ["hash", "size", "host", "download", "media_identity", "stage_incomplete"])
def test_plain_invalid_proof_retains_all_originals(plain_case, fault):
    case = plain_case
    if fault == "stage_incomplete":
        spec = case.request["production_receipt"]
        value = json.loads(Path(spec["path"]).read_bytes())
        value["verification"]["file_count"] -= 1
    else:
        spec = case.request["plain_upload"]
        value = copy.deepcopy(case.uploaded)
        if fault == "hash": value["bundle_sha256"] = "a" * 64
        elif fault == "size": value["bytes"] += 1
        elif fault == "host": value["execution_host_id"] = "d" * 64
        elif fault == "download": value["independent_download_verified"] = False
        elif fault == "media_identity": value["drive"]["remote_key"] = "differentu1-archive.tar.gz"
    spec.update(record(Path(spec["path"]), value))
    with pytest.raises((RuntimeError, ValueError)):
        prepare(case)
    assert all((case.c.day / name).read_bytes() == content for name, content in case.c.contents.items())
    assert not (case.c.root / "cold_archive/catalog/archives" / case.request["archive_id"] / "upload.json").exists()


def test_plain_changed_original_refuses_before_any_deletion(plain_case):
    case = plain_case
    req = prepare(case)
    path = case.c.day / sorted(case.c.contents)[-1]
    path.write_bytes(b"changed")
    with pytest.raises((RuntimeError, ValueError), match="identity|content"):
        remove(case, req)
    assert all((case.c.day / name).is_file() for name in case.c.contents)


def test_native_plain_reclaim_keeps_locations_and_removes_only_verified_files(plain_case):
    case = plain_case
    req = prepare(case)
    result = remove(case, req)
    assert result["status"] == "PASS" and result["deleted_files"] == len(case.c.contents)
    assert result["payload_encryption"] == "none" and "custody_record_sha256" not in result
    assert result["reclaimed_allocated_bytes"] == sum(row["allocated_bytes"] for row in case.c.manifest["files"])
    assert result["spool_cleanup"]["deleted_files"] == 1
    assert not (case.c.args["production_manifest"].parent / "archive.tar.gz").exists()
    for name in case.c.contents:
        source = case.c.day / name
        assert not source.exists()
        assert locations.load_location(source).entry["payload_encryption"] == "none"
    assert Path(case.uploaded["source_path"]).is_file()
    assert Path(case.uploaded["downloaded_path"]).is_file()


def test_plain_cli_requires_explicit_mode_and_complete_evidence(plain_case):
    case = plain_case
    kwargs = dict(production_root=case.c.tmp, now=datetime.now(timezone.utc), source_git_sha="f" * 40)
    assert cli.validate_request(case.request, **kwargs) == case.request
    for change in ({"payload_encryption": "crypt"}, {"schema_version": schema_version("production_cold_archive_reclaim_request")}):
        with pytest.raises(ValueError):
            cli.validate_request({**case.request, **change}, **kwargs)
    bad = dict(case.request)
    bad.pop("plain_upload")
    with pytest.raises(ValueError):
        cli.validate_request(bad, **kwargs)


def test_plain_publication_can_resume_with_identical_proof(plain_case):
    case = plain_case
    first = prepare(case)
    case.output = case.c.tmp / "plain-retry"
    case.output.mkdir()
    second = prepare(case)
    assert first["catalog_entry"] == second["catalog_entry"]
    assert first["source_review"] != second["source_review"]
    assert all((case.c.day / name).is_file() for name in case.c.contents)
