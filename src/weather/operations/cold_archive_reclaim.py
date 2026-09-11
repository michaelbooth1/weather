"""Exact-source reclaim after approved selection, recovery and custody proofs.

This API is not an unattended scheduler. Its production CLI supplies host,
lease, deadline, resource and imported-source checks. Failed attempts and
campaign transitions remain immutable and block automatic continuation.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from weather import cold_archive_locations as locations
from weather import runtime_identity
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_spool_cleanup as spool
from weather.operations import production_cold_archive_stage as archive
from weather.operations.cleanup_preflight import build_cleanup_preflight
from weather.operations.cold_archive_native_removal import ExactNtfsRemoval
from weather.operations.storage_classes import classification_payload
from weather.operations.storage_recovery_inventory import event_date
from weather.schema_registry import schema_version

CONSUMER_FILES = (
    "src/weather/cold_archive_locations.py", "src/weather/io.py",
    "src/weather/operations/cold_archive_catalog.py",
    "src/weather/operations/closed_market_day_archive.py",
    "src/weather/operations/event_day_manifest.py",
    "src/weather/operations/density_live_replay_parity.py",
    "src/weather/market/market_microstructure_features.py",
    "src/weather/market/mm_paper_scoring.py",
    "src/weather/market/order_book_tape.py",
    "src/weather/calibration/residual_distribution_corpus.py",
    "src/weather/reporting/data_quality/data_layer_audit_collectors.py",
    "src/weather/reporting/data_quality/clob_coverage_audit.py",
    "src/weather/reporting/scorecards/settled_day_root_cause.py",
)
SELECTION_CHECKS = ("market_day_closed", "settlement_final", "barriers_clear",
                    "queues_clear", "point_in_time_windows_clear",
                    "protected_release_replay_inputs_clear")


def _require(condition, message):
    locations._require(condition, message)


def _utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    _require(result.tzinfo is not None, "reclaim evidence requires timezone-aware timestamps")
    return result.astimezone(timezone.utc)


def _load(spec, stack, *, sealed=True):
    _require(isinstance(spec, dict) and set(spec) == {"path", "sha256"},
             "reclaim evidence must bind one exact path and SHA-256")
    locations.require_sha(spec["sha256"])
    path = locations.safe_path(spec["path"])
    _require(path.stat().st_size <= locations.MAX_METADATA_BYTES, "reclaim metadata exceeds bound")
    stack.enter_context(bridge._file_pin(path))
    if sealed:
        value, digest = locations.read_record(path, spec["sha256"])
    else:
        value, _ = archive._load(path, spec["sha256"])
        digest = spec["sha256"]
    return value, digest


def _approval(request, stack, entry):
    approval, approval_sha = _load(request["owner_approval"], stack, sealed=False)
    proposal, proposal_sha = _load(request["proposal"], stack, sealed=False)
    selection, selection_sha = _load(request["selection"], stack, sealed=False)
    plan, plan_sha = _load(request["plan"], stack, sealed=False)
    _require(approval.get("schema_version") == schema_version("archive_target_owner_approval")
             and isinstance(approval.get("approved_by"), str) and approval["approved_by"].strip()
             and isinstance(approval.get("owner_instruction"), str) and approval["owner_instruction"].strip(),
             "reclaim requires the bound owner selection approval")
    proposal_kind = proposal.get("selection_kind")
    _require(proposal_kind in {"primary", "standby"}, "unsupported approved selection kind")
    kind = "primary" if proposal_kind == "primary" else "conditional_reserve"
    selected = approval.get("primary" if kind == "primary" else "conditional_reserve", {})
    _require(selected.get("sha256") == proposal_sha
             and proposal.get("schema_version") == schema_version("archive_target_owner_review_proposal"),
             "reclaim proposal is not the owner-approved selection")
    _require(selection.get("schema_version") == schema_version("large_archive_candidate_selection")
             and selection.get("source_review_proposal_sha256") == proposal_sha
             and selection.get("owner_approval_sha256") == approval_sha
             and archive._rows(selection.get("files")) == archive._rows(proposal.get("files")),
             "reclaim selection differs from the approved original identities")
    archive._check_seal(plan, "plan_hash")
    _require(plan.get("schema_version") == schema_version("production_cold_archive_plan")
             and plan.get("selection_sha256") == selection_sha and plan_sha == entry["plan_sha256"]
             and plan.get("chunk_grouping") in (archive.SELECTIVE_GROUPING, archive.MARKET_DAY_GROUPING,
                                               archive.PARTITIONED_GROUPING),
             "reclaim requires the exact selective plan")
    matches = [chunk for chunk in plan.get("chunks", []) if chunk.get("chunk_id") == entry["chunk_id"]]
    _require(len(matches) == 1 and archive._rows(matches[0].get("files")) == archive._rows(entry["files"]),
             "reclaim archive differs from its approved plan chunk")
    plan_rows = archive._rows([row for chunk in plan["chunks"] for row in chunk["files"]])
    limit = archive._integer(plan.get("chunk_bytes"), "chunk_bytes", maximum=archive.MAX_CHUNK_BYTES)
    _require(limit > 0 and plan.get("format") == archive.FORMAT
             and archive._chunks(plan_rows, limit, plan["chunk_grouping"], plan.get("isolated_events", ())) == plan["chunks"]
             and plan.get("file_count") == len(plan_rows), "reclaim plan grouping or count changed")
    _require(plan_rows
             == archive._rows(selection["files"])
             and all(Path(document.get("source_root", "")) == Path(entry["source_root"])
                     for document in (proposal, selection, plan)),
             "reclaim plan or source-root inventory changed")
    target = approval.get("conditional_reserve", {}).get("use_only_if_qualified_primary_reclaim_is_below_bytes")
    _require(type(target) is int and 0 < target <= 1024**4, "approved reclaim target is invalid")
    return approval, approval_sha, kind, target


def _market_day_evidence(review, entry, stack):
    events = sorted({locations.relative_path(row["path"]).parts[1] for row in entry["files"]})
    _require(1 <= len(events) <= 16, "reclaim market-day evidence exceeds bound")
    if len(events) == 1 and "market_days" not in review:
        return  # Existing single-day reviews retain their original contract.
    rows = review.get("market_days")
    _require(isinstance(rows, list) and len(rows) == len(events)
             and all(isinstance(row, dict) for row in rows)
             and [row.get("event_slug") for row in rows] == events,
             "reclaim requires exact ordered evidence for every market day")
    for event, row in zip(events, rows):
        _require(set(row) == {"event_slug", "target_date", "settlement"}
                 and row["target_date"] == event_date(event).isoformat(),
                 "market-day settlement identity differs")
        spec = row["settlement"]
        _require(isinstance(spec, dict) and Path(spec.get("path", "")) ==
                 Path(entry["source_root"]) / "snapshots" / event / "settlement.json",
                 "market-day settlement evidence path differs")
        settlement, _ = _load(spec, stack, sealed=False)
        reconciliation = settlement.get("polymarket_reconciliation")
        _require(settlement.get("target_date") == row["target_date"]
                 and isinstance(reconciliation, dict)
                 and reconciliation.get("event_closed") is True
                 and reconciliation.get("status") == "match",
                 "market-day final settlement is not proved")
        winners = reconciliation.get("winning_markets")
        _require(isinstance(winners, list) and 1 <= len(winners) <= 256
                 and all(isinstance(winner, dict) and winner.get("closed") is True
                         and winner.get("resolved") is True for winner in winners),
                 "market-day winning markets are not finally resolved")


def _review(spec, stack, entry, entry_sha, now):
    review, digest = _load(spec, stack)
    _require(review.get("schema_version") == schema_version("cold_archive_source_review")
             and review.get("status") == "PASS" and review.get("entry_sha256") == entry_sha
             and review.get("archive_id") == entry["archive_id"]
             and review.get("files") == [{"path": row["path"], "sha256": row["sha256"]}
                                         for row in entry["files"]],
             "protected-input review does not cover this exact archive")
    checked, expires = _utc(review.get("checked_at_utc")), _utc(review.get("expires_at_utc"))
    _require(checked <= now < expires and expires - checked <= timedelta(minutes=5),
             "protected-input review is expired, future-dated or overlong")
    _market_day_evidence(review, entry, stack)
    checks = review.get("checks")
    _require(isinstance(checks, dict) and set(checks) == set(SELECTION_CHECKS),
             "protected-input review lacks required checks")
    _require(all(isinstance(row, dict) for row in checks.values()), "source protection checks must be objects")
    _require(checks["market_day_closed"].get("closed") is True
             and checks["settlement_final"].get("settled") is True
             and checks["settlement_final"].get("settlement_state") in
                 {"settled_countable", "settled_non_countable"},
             "source market day is not proved closed and finally settled")
    for name, row in checks.items():
        _require(isinstance(row, dict) and row.get("status") == "PASS", "source protection check failed")
        if name.endswith("_clear"):
            _require(row.get("open_references") == [], "protected or pending inputs still reference the source")
        evidence = row.get("evidence")
        _require(isinstance(evidence, list) and 1 <= len(evidence) <= 16,
                 "source protection check requires bounded evidence")
        for item in evidence:
            _load(item, stack, sealed=False)
    return review, digest, expires


def _restore(spec, stack, entry, entry_sha, now):
    record, digest = _load(spec, stack)
    _require(record.get("schema_version") == schema_version("cold_archive_catalog_restore")
             and record.get("status") == "RESTORE_VERIFIED"
             and record.get("entry_sha256") == entry_sha
             and record.get("archive_id") == entry["archive_id"]
             and record.get("verified_file_count") == len(entry["files"]),
             "reclaim requires catalog-bound complete restore proof")
    restored, transport = catalog._unpack(record["restore"]), catalog._unpack(record["transport"])
    archive._check_seal(restored, "receipt_hash")
    archive._check_seal(transport, "receipt_hash")
    _require(restored.get("schema_version") == schema_version("production_cold_archive_restore_receipt")
             and restored.get("status") == "PASS" and restored.get("restore_performed") is True
             and restored.get("checks") == dict.fromkeys(bridge.RESTORE_CHECKS, "PASS")
             and restored.get("verified_file_count") == len(entry["files"])
             and restored.get("transport_receipt_sha256") == record["transport"]["sha256"]
             and restored.get("restored_members") == [
                 {"path": row["path"], "bytes": row["size_bytes"], "sha256": row["sha256"]}
                 for row in entry["files"]],
             "reclaim restore is incomplete")
    _require(transport.get("schema_version") == schema_version("production_cold_archive_transport_receipt")
             and transport.get("status") == "PASS" and transport.get("phase") == "download_and_verify"
             and transport.get("independent_download") is True and transport.get("upload_performed") is False
             and transport.get("upload_receipt_sha256") == entry["proofs"]["upload_receipt"]["sha256"]
             and transport.get("ciphertext") == entry["ciphertext"],
             "reclaim requires independent download of the exact committed upload")
    for evidence in (transport, restored):
        _require(all(evidence.get(key) == entry[key] for key in (
            "archive_id", "chunk_id", "plan_sha256", "production_manifest_sha256",
            "production_receipt_sha256", "crypt_receipt_sha256"))
                 and evidence.get("cleanup_eligible") is False
                 and evidence.get("deletion_authorized") is False,
                 "reclaim recovery proof belongs to a different source")
    docs, _, _ = catalog._validated_upload(entry["proofs"], Path(entry["source_root"]))
    expected_drive = {key: docs["upload_receipt"]["drive"][key]
                      for key in ("root_folder_id", "object_id", "remote_key")}
    _require(transport.get("drive") == expected_drive and restored.get("drive") == expected_drive
             and restored.get("ciphertext") == docs["crypt_receipt"]["ciphertext"]
             and restored.get("source_retained") is True and transport.get("source_retained") is True,
             "reclaim recovery cloud or ciphertext identity differs")
    expected_metadata = docs["upload_receipt"]["metadata_objects"]
    downloaded_metadata = transport.get("metadata_objects")
    _require(isinstance(downloaded_metadata, list) and len(downloaded_metadata) == len(expected_metadata),
             "reclaim downloaded metadata is incomplete")
    for actual, expected in zip(downloaded_metadata, expected_metadata):
        _require(isinstance(actual, dict) and isinstance(actual.get("downloaded_path"), str)
                 and {key: value for key, value in actual.items() if key != "downloaded_path"} == expected,
                 "reclaim downloaded recovery metadata differs")
    completed = _utc(restored.get("completed_at_utc"))
    _require(timedelta(0) <= now - completed <= timedelta(hours=24),
             "original reclaim requires a complete restore within the last 24 hours")
    return record, digest


def _custody(spec, stack, entry_sha, restore_sha, backup_host_id, now):
    custody, digest = _load(spec, stack)
    _require(custody.get("schema_version") == schema_version("cold_archive_custody")
             and custody.get("status") == "PASS"
             and custody.get("entry_sha256") == entry_sha
             and custody.get("restore_record_sha256") == restore_sha
             and custody.get("backup_execution_host_id") == backup_host_id,
             "reclaim lacks exact off-host catalog and restore custody")
    backups = custody.get("verified_backups")
    _require(isinstance(backups, dict) and set(backups) == {"catalog_entry", "restore_record"}
             and backups["catalog_entry"].get("sha256") == entry_sha
             and backups["restore_record"].get("sha256") == restore_sha
             and all(isinstance(value.get("path"), str) and value["path"] for value in backups.values()),
             "off-host metadata backup identities differ")
    owner = custody.get("recovery_key_custody", {})
    _require(owner.get("confirmed") is True and owner.get("outside_both_pcs") is True
             and isinstance(owner.get("approved_by"), str) and owner["approved_by"].strip()
             and isinstance(owner.get("storage_reference"), str) and owner["storage_reference"].strip()
             and _utc(owner.get("confirmed_at_utc")) <= now,
             "off-PC recovery-key custody requires the owner's confirmation")
    return custody, digest


def verify_consumer_adoption(source_root, production_root, stack, loops):
    """Pin reviewed consumer bytes on both hosts and require adopted live scopes."""
    for relative in CONSUMER_FILES:
        source, production = source_root / relative, production_root / relative
        for path in (source, production):
            stack.enter_context(bridge._file_pin(locations.safe_path(path)))
            _require(path.stat().st_size <= locations.MAX_METADATA_BYTES, "consumer source exceeds bound")
        _require(source.read_bytes() == production.read_bytes(),
                 "archive-aware consumer source has not been adopted: " + relative)
    _require(len(loops) == 3, "all three capture identities are required")
    for loop in loops:
        identity = loop.get("runtime_identity") or {}
        scope = identity.get("source_scope_files")
        _require(isinstance(scope, list) and 0 < len(scope) <= 2048
                 and all(isinstance(path, str) and locations.relative_path(path).as_posix() == path
                         for path in scope),
                 "capture loaded-source scope is missing or invalid")
        _require(runtime_identity.identities_match(
            identity, runtime_identity.current_identity_for(identity, repo_root=production_root)),
            "capture has not adopted the current consumer source")


def _retain_recovery(entry_path, record, record_sha, custody, custody_sha, stack, guard):
    """Keep complete off-host handback proof in the production catalog."""
    guard.admit()
    entry_parent = Path(entry_path).parent
    destinations = ((entry_parent / "restores" / (record["restore"]["sha256"] + ".json"), record, record_sha),
                    (entry_parent / "custody" / (custody_sha + ".json"), custody, custody_sha))
    for path, value, digest in destinations:
        parent = catalog._mkdir(path.parent)
        stack.enter_context(archive._directory_pin(parent))
        guard.admit()
        if path.exists():
            locations.read_record(path, digest)
        else:
            _, copied_sha = catalog._write_record(path, value)
            _require(copied_sha == digest, "retained recovery proof bytes differ")
        stack.enter_context(bridge._file_pin(path))
    return {"restore_record": str(destinations[0][0]), "custody_record": str(destinations[1][0])}


def _removal_pin(path):
    return ExactNtfsRemoval(path)


def _progress(parent, approval_sha, target):
    pointer = parent / "progress.json"
    if not pointer.exists():
        return {"schema_version": schema_version("cold_archive_reclaim_progress"),
                "status": "READY", "owner_approval_sha256": approval_sha, "target_bytes": target,
                "reclaimed_allocated_bytes": 0, "deleted_files": 0, "sequence": 0}, None
    value, digest = locations.read_record(pointer)
    _require(value.get("schema_version") == schema_version("cold_archive_reclaim_progress")
             and value.get("status") == "READY" and value.get("owner_approval_sha256") == approval_sha
             and value.get("target_bytes") == target, "reclaim campaign requires explicit reconciliation")
    for key in ("reclaimed_allocated_bytes", "deleted_files", "sequence"):
        _require(type(value.get(key)) is int and value[key] >= 0, "reclaim progress counters are invalid")
    return value, digest


def _advance(parent, state, previous):
    value = {**state, "previous_sha256": previous, "updated_at_utc": datetime.now(timezone.utc).isoformat()}
    revisions = catalog._mkdir(parent / "progress")
    _, digest = catalog._write_record(revisions / (uuid.uuid4().hex + ".json"), value)
    catalog._write_record(parent / "progress.json", value, replace_sha256=previous)
    return value, digest


def reclaim_chunk(*, request, source_root, production_root, backup_host_id,
                  capture_loops, admission, deadline_monotonic):
    """Reclaim one approved primary archive under the caller's verified lease.

    Conditional-reserve execution deliberately remains refused until a separate
    complete primary-disposition proof is implemented and qualified.
    """
    guard = archive._Guard(admission, deadline_monotonic, 16 * archive.MIB)
    now = datetime.now(timezone.utc)
    attempt_id = locations.archive_id(request["attempt_id"])
    with ExitStack() as stack:
        entry_doc, entry_sha = _load(request["catalog_entry"], stack)
        is_plain = request.get("payload_encryption") == "none"
        if is_plain:
            from weather.operations import cold_archive_plain as plain
            entry, _, _ = plain.read_entry(request["catalog_entry"]["path"], entry_sha,
                                           backup_host_id=backup_host_id, now=now)
        else:
            entry, _, _ = catalog._entry(request["catalog_entry"]["path"], entry_sha)
        _require(entry_doc == entry and Path(entry["source_root"]) == production_root / "data",
                 "reclaim original data root differs from production")
        local_root = catalog._local_catalog_root(request["catalog_entry"]["path"], entry)
        _require(local_root == production_root / "data", "reclaim cannot use a relocated recovery catalog")
        approval, approval_sha, kind, target = _approval(request, stack, entry)
        _require(kind == "primary", "conditional reserve needs a qualified complete primary-disposition proof")
        for row in entry["files"]:
            parts = locations.relative_path(row["path"]).parts
            _require(len(parts) == 3 and parts[0] == "snapshots"
                     and event_date(parts[1]) < now.astimezone(ZoneInfo("America/Toronto")).date() - timedelta(days=30),
                     "reclaim target is not an old immediate market-day source")
        review, review_sha, review_expires = _review(request["source_review"], stack, entry, entry_sha, now)
        if is_plain:
            restore_record = restore_sha = custody_sha = None
            retained_recovery = {"plain_upload_receipt_sha256": entry["plain_upload_receipt_sha256"]}
        else:
            restore_record, restore_sha = _restore(request["restore_record"], stack, entry, entry_sha, now)
            custody, custody_sha = _custody(request["custody_record"], stack, entry_sha, restore_sha, backup_host_id, now)
            retained_recovery = _retain_recovery(request["catalog_entry"]["path"], restore_record, restore_sha,
                                                 custody, custody_sha, stack, guard)
        verify_consumer_adoption(source_root, production_root, stack, capture_loops)
        campaign = catalog._mkdir(local_root / "cold_archive" / "catalog" / "reclaims" / approval_sha)
        stack.enter_context(archive._directory_pin(campaign))
        state, state_sha = _progress(campaign, approval_sha, target)
        _require(state["reclaimed_allocated_bytes"] < target, "approved reclaim target is already reached")
        pins, planned, hashes = [], [], {}
        for row in entry["files"]:
            guard.admit()
            path = local_root.joinpath(*locations.relative_path(row["path"]).parts)
            marker = locations.marker_path(path)
            stack.enter_context(bridge._file_pin(locations.safe_path(marker)))
            location = locations.load_location(path)
            _require(location is not None and location.entry_sha256 == entry_sha,
                     "reclaim source location marker is missing or changed")
            pin = stack.enter_context(_removal_pin(locations.safe_path(path)))
            native = pin.metadata()
            _require(native == {key: value for key, value in archive._rows([row])[0].items() if key != "path"},
                     "reclaim source native identity or allocation changed")
            digest = pin.digest(guard=guard)
            _require(digest == row["sha256"], "reclaim source content differs from the restored archive")
            pins.append(pin)
            planned.append({**row, **native})
            hashes[path.resolve()] = digest
        spool_sha, spool_pins, spool_files = None, [], []
        if "spool_inventory" in request:
            inventory, spool_sha = _load(request["spool_inventory"], stack)
            prepare = plain.prepare_spool if is_plain else spool.prepare_spool
            spool_pins, spool_files = prepare(
                inventory, entry=entry, entry_sha256=entry_sha, restore_record=restore_record,
                production_root=production_root, stack=stack, guard=guard)
        candidates = []
        for row in planned:
            classified = classification_payload(row["path"])
            candidates.append({"path": row["path"], "data_path": row["path"],
                               "bytes": row["size_bytes"], "sha256": row["sha256"],
                               "storage_class": classified["storage_class"],
                               "artifact_family": classified["artifact_family"],
                               "rebuild_source": "verified complete archive " + entry["archive_id"],
                               "deletion_reason": "owner-approved verified off-site archive reclaim"})
        cleanup = {"schema_version": schema_version("cleanup_manifest"), "root": str(local_root),
                   "operator_review": {"approved": True, "approved_by": approval["approved_by"],
                                       "note": approval["owner_instruction"],
                                       "owner_approval_sha256": approval_sha},
                   "candidates": candidates}
        preflight = build_cleanup_preflight(cleanup, root=local_root,
                                             sha256_reader=lambda path: hashes[Path(path).resolve()])
        _require(preflight.get("status") == "PASS" and preflight.get("delete_permission") is True,
                 "canonical cleanup preflight refused")
        attempt = campaign / attempt_id
        attempt.mkdir()
        stack.enter_context(archive._directory_pin(attempt))
        base = {"schema_version": schema_version("cold_archive_reclaim_receipt"),
                "attempt_id": attempt_id, "archive_id": entry["archive_id"], "chunk_id": entry["chunk_id"],
                "entry_sha256": entry_sha,
                "owner_approval_sha256": approval_sha, "source_review_sha256": review_sha,
                "restore_record_sha256": restore_sha, "custody_record_sha256": custody_sha,
                "plan_sha256": entry["plan_sha256"], "selection_kind": kind,
                "target_bytes": target, "previous_reclaimed_allocated_bytes": state["reclaimed_allocated_bytes"]}
        if is_plain:
            base.pop("restore_record_sha256")
            base.pop("custody_record_sha256")
            base.update(payload_encryption="none", plain_upload_receipt_sha256=entry["plain_upload_receipt_sha256"])
        catalog._write_record(attempt / "cleanup_manifest.json", cleanup)
        catalog._write_record(attempt / "preflight.json", preflight)
        catalog._write_record(attempt / "intent.json", {**base, "status": "INTENT", "files": planned})
        state, state_sha = _advance(campaign, {**state, "status": "IN_PROGRESS", "attempt_id": attempt_id}, state_sha)
        spool_result = None
        if spool_pins:
            spool_result = spool.remove_prepared(spool_pins, spool_files, attempt=attempt,
                                                binding=base, inventory_sha256=spool_sha, guard=guard)
        removed = []
        for index, (pin, row) in enumerate(zip(pins, planned)):
            guard.admit()
            _require(datetime.now(timezone.utc) < review_expires, "source protection review expired")
            if state["reclaimed_allocated_bytes"] + sum(item["allocated_bytes"] for item in removed) >= target:
                break
            pin.remove()
            catalog._write_record(attempt / f"file-{index:05d}.json",
                                  {**base, "status": "DELETED", "file": row})
            removed.append(row)
        inventory = catalog.write_inventory(source_root=local_root, admission=admission,
                                            deadline_monotonic=deadline_monotonic)
        result, result_sha = catalog._write_record(attempt / "receipt.json", {
            **base, "status": "PASS", "files": removed, "deleted_files": len(removed),
            "reclaimed_allocated_bytes": sum(row["allocated_bytes"] for row in removed),
            "source_retained": len(removed) == 0, "inventory": inventory,
            "spool_cleanup": spool_result, "retained_recovery": retained_recovery,
            "completed_at_utc": datetime.now(timezone.utc).isoformat()})
        _advance(campaign, {**state, "status": "READY", "sequence": state["sequence"] + 1,
                           "deleted_files": state["deleted_files"] + len(removed),
                           "reclaimed_allocated_bytes": state["reclaimed_allocated_bytes"] + result["reclaimed_allocated_bytes"],
                           "last_receipt_path": str(attempt / "receipt.json"), "last_receipt_sha256": result_sha}, state_sha)
        return {**result, "receipt_path": str(attempt / "receipt.json"), "receipt_sha256": result_sha,
                "inventory": inventory}
