"""Plain archive proof, catalog publication, and exact staged-file cleanup.

A complete staged member verification plus a byte-identical independent cloud
download proves the same complete archive. No encryption or key custody applies.
Original removal continues through cold_archive_reclaim's existing native pins,
fresh protected-input review, cleanup preflight and allocation ledger.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from weather import cold_archive_locations as locations
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_campaign_review as review
from weather.operations import cold_archive_reclaim as reclaim
from weather.operations import production_cold_archive_stage as archive
from weather.operations import production_cold_archive_transfer_core as transfer
from weather.schema_registry import schema_version

PROOFS = ("production_manifest", "production_receipt", "plain_upload")
EVIDENCE_FIELDS = ("owner_approval", "proposal", "selection", "plan", *PROOFS)
require = locations._require


def validated(proofs, *, source_root, backup_host_id, archive_id, now):
    require(isinstance(proofs, dict) and set(proofs) == set(PROOFS),
            "plain archive requires complete stage and independent upload proofs")
    docs = {name: catalog._unpack(proofs[name]) for name in PROOFS}
    manifest, production, uploaded = (docs[name] for name in PROOFS)
    bridge.validate_production_evidence(manifest, production, manifest.get("plan_sha256"))
    require(Path(manifest["source_root"]) == source_root
            and manifest.get("source_proof") == "native_pinned_bytes_during_staging",
            "plain archive source root differs")
    for row in manifest["files"]:
        parts = locations.relative_path(row["path"]).parts
        require(len(parts) == 3 and parts[0] == "snapshots",
                "plain archive requires immediate snapshot inputs")
    archive._check_seal(uploaded, "receipt_hash")
    require(uploaded.get("schema_version") == schema_version("cold_archive_plain_upload")
            and uploaded.get("status") == "PASS" and uploaded.get("payload_encryption") == "none"
            and uploaded.get("independent_download_verified") is True
            and uploaded.get("originals_deleted") == 0
            and uploaded.get("execution_host_id") == backup_host_id
            and uploaded.get("bundle_sha256") == manifest["archive_sha256"]
            and type(uploaded.get("bytes")) is int and uploaded["bytes"] == manifest["archive_bytes"],
            "plain independent download does not prove this complete archive")
    locations.require_sha(backup_host_id)
    aid = locations.archive_id(archive_id)
    upload_id = locations.archive_id(uploaded.get("attempt_id"))
    require(re.fullmatch(re.escape(aid) + r"u[1-9][0-9]*", upload_id) is not None,
            "plain upload attempt belongs to a different archive")
    source = Path(uploaded.get("source_path", ""))
    require(source.is_absolute() and ".." not in source.parts and len(source.parents) >= 4,
            "plain upload source path is invalid")
    workstation = source.parents[3]
    require(workstation != source_root.parent
            and source == workstation / "scratch" / "ac-in" / aid / "archive.tar.gz"
            and Path(uploaded.get("downloaded_path", "")) ==
                workstation / "scratch" / "ac-backup" / upload_id / "downloaded-archive.tar.gz",
            "plain upload lacks an independent workstation download")
    require(timedelta(0) <= now - reclaim._utc(uploaded.get("completed_at_utc")) <= timedelta(hours=24),
            "plain download verification is future-dated or older than 24 hours")
    drive = uploaded.get("drive")
    require(isinstance(drive, dict) and set(drive) ==
            {"root_folder_id", "object_id", "remote_key", "bytes", "hashes"},
            "plain upload cloud identity is incomplete")
    folder = drive["root_folder_id"]
    require(isinstance(folder, str) and transfer.ID_RE.fullmatch(folder) is not None,
            "plain archive cloud folder identity is invalid")
    require(isinstance(drive.get("remote_key"), str)
            and re.fullmatch(re.escape(aid) + r"u[1-9][0-9]*-archive[.]tar[.]gz", drive["remote_key"]) is not None,
            "plain cloud object belongs to a different archive")
    remote = transfer._remote_record(
        {key: value for key, value in drive.items() if key != "root_folder_id"},
        key=drive["remote_key"], expected_bytes=manifest["archive_bytes"])
    require(folder != remote["object_id"], "plain archive folder and object identities collide")
    bound = {
        "archive_id": aid, "chunk_id": manifest["chunk_id"], "plan_sha256": manifest["plan_sha256"],
        "production_manifest_sha256": proofs["production_manifest"]["sha256"],
        "production_receipt_sha256": proofs["production_receipt"]["sha256"],
        "plain_upload_receipt_sha256": proofs["plain_upload"]["sha256"],
        "payload_encryption": "none", "source_root": str(source_root),
        "files": manifest["files"], "archive_sha256": manifest["archive_sha256"],
        "archive_bytes": manifest["archive_bytes"], "drive_root_folder_id": folder,
        "objects": [{"kind": "archive", **remote, "sha256": manifest["archive_sha256"]}],
    }
    return docs, bound


def read_entry(path, digest, *, backup_host_id, now):
    entry, actual = locations.read_record(path, digest)
    require(entry.get("schema_version") == schema_version("cold_archive_catalog_entry")
            and entry.get("status") == "UPLOADED", "unsupported plain catalog entry")
    docs, bound = validated(entry.get("proofs"), source_root=Path(entry.get("source_root", "")),
                            backup_host_id=backup_host_id, archive_id=entry.get("archive_id"), now=now)
    require(all(entry.get(key) == value for key, value in bound.items())
            and entry.get("cleanup_eligible") is False and entry.get("deletion_authorized") is False,
            "plain catalog entry differs from its exact proofs")
    return entry, actual, docs


def prepare_request(request, *, production_root, backup_host_id, output_root,
                    admission, deadline_monotonic):
    """Publish verified locations and prepare a fresh exact original reclaim."""
    guard = archive._Guard(admission, deadline_monotonic, 16 * archive.MIB)
    root = production_root / "data"
    with ExitStack() as stack:
        proofs = {}
        for name in PROOFS:
            spec = request[name]
            path = locations.safe_path(spec["path"])
            stack.enter_context(bridge._file_pin(path))
            _, proofs[name] = catalog._proof(path, spec["sha256"])
        docs, bound = validated(proofs, source_root=root, backup_host_id=backup_host_id,
                                archive_id=request["archive_id"], now=datetime.now(timezone.utc))
        entry = {"schema_version": schema_version("cold_archive_catalog_entry"), "status": "UPLOADED",
                 **bound, "proofs": proofs, "published_at_utc": datetime.now(timezone.utc).isoformat(),
                 "cleanup_eligible": False, "deletion_authorized": False}
        reclaim._approval(request, stack, entry)
        stage_path = Path(docs["production_receipt"].get("attempt_root", "")) / "archive.tar.gz"
        relative = stage_path.relative_to(production_root)
        require(len(relative.parts) == 5 and relative.parts[:2] == ("scratch", "production_cold_archive")
                and relative.parts[-2:] == ("stage", "archive.tar.gz"),
                "plain stage payload is outside its fixed production layout")
        locations.archive_id(relative.parts[2])
        sources, markers = [], []
        for row in entry["files"]:
            guard.admit()
            path = locations.safe_path(root.joinpath(*locations.relative_path(row["path"]).parts))
            pin = stack.enter_context(archive._source_pin(path))
            require(pin.metadata() == {key: value for key, value in archive._rows([row])[0].items()
                                       if key != "path"}, "plain source identity changed before publication")
            marker = locations.marker_path(path)
            catalog._mkdir(marker.parent)
            stack.enter_context(archive._directory_pin(marker.parent))
            sources.append(path)
            markers.append(marker)
        parent = catalog._mkdir(root / "cold_archive" / "catalog" / "archives" / entry["archive_id"])
        stack.enter_context(archive._directory_pin(parent))
        guard.admit()
        entry_path = parent / "upload.json"
        if entry_path.exists():
            existing, entry_sha, _ = read_entry(entry_path, None, backup_host_id=backup_host_id,
                                                now=datetime.now(timezone.utc))
            require(existing.get("proofs") == proofs and all(existing.get(key) == value for key, value in bound.items()),
                    "existing plain catalog belongs to different verified bytes")
            entry = existing
        else:
            entry, entry_sha = catalog._write_record(entry_path, entry)
        for path, marker, row in zip(sources, markers, entry["files"]):
            guard.admit()
            if not marker.exists():
                catalog._write_record(marker, {
                    "schema_version": schema_version("cold_archive_location"), "source_path": row["path"],
                    "archive_id": entry["archive_id"], "entry_sha256": entry_sha,
                    "sha256": row["sha256"], "size_bytes": row["size_bytes"]})
            require(locations.load_location(path).entry_sha256 == entry_sha, "plain location readback differs")
        guard.admit()
        checked = review.review_sources(production_root=production_root, entry=entry, entry_sha256=entry_sha,
                                         output_root=output_root / "source-review")
        with bridge._file_pin(locations.safe_path(stage_path)) as pin:
            native = pin.metadata()
        inventory_path = output_root / "spool-inventory.json"
        archive._write(inventory_path, archive._seal({
            "schema_version": schema_version("cold_archive_spool_inventory"), "archive_id": entry["archive_id"],
            "entry_sha256": entry_sha, "files": [{"role": "staged_archive", "path": relative.as_posix(),
                "sha256": entry["archive_sha256"], **native}]}, "receipt_hash"))
        return {**request, "catalog_entry": {"path": str(entry_path), "sha256": entry_sha},
                "source_review": checked,
                "spool_inventory": {"path": str(inventory_path), "sha256": archive._load(inventory_path)[1]}}


def prepare_spool(inventory, *, entry, entry_sha256, restore_record, production_root, stack, guard):
    """Select only the exact staging payload already proved by plain recovery."""
    require(entry.get("payload_encryption") == "none" and restore_record is None
            and inventory.get("schema_version") == schema_version("cold_archive_spool_inventory")
            and inventory.get("archive_id") == entry["archive_id"]
            and inventory.get("entry_sha256") == entry_sha256, "plain spool binding differs")
    receipt = catalog._unpack(entry["proofs"]["production_receipt"])
    expected_path = Path(receipt["attempt_root"]) / "archive.tar.gz"
    relative = expected_path.relative_to(production_root)
    require(len(relative.parts) == 5 and relative.parts[:2] == ("scratch", "production_cold_archive")
            and relative.parts[-2:] == ("stage", "archive.tar.gz"), "plain spool layout differs")
    locations.archive_id(relative.parts[2])
    rows = inventory.get("files")
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
            "plain spool inventory must contain one exact staged archive")
    row = rows[0]
    require(row.get("role") == "staged_archive" and row.get("path") == relative.as_posix()
            and row.get("sha256") == entry["archive_sha256"]
            and row.get("size_bytes") == entry["archive_bytes"], "plain spool file differs")
    expected = {key: archive._integer(row.get(key), key) for key in
                ("size_bytes", "mtime_ns", "device", "file_id", "allocated_bytes")}
    pin = stack.enter_context(reclaim.spool._removal_pin(locations.safe_path(expected_path)))
    guard.admit()
    require(pin.metadata() == expected and pin.digest(guard=guard) == entry["archive_sha256"],
            "plain spool native identity or content changed")
    return [pin], [{"role": "staged_archive", "path": relative.as_posix(),
                    "sha256": entry["archive_sha256"], **expected}]
