"""Restore a date range of archived market-day families into the restore cache.

Workstation only. ``plan`` is read-only: it locates every marker-registered
member of the requested families and dates in a recovery data root, checks each
catalog member against its event-day manifest SHA-256, and refuses a file that
sits at an archived original path (a hand copy is not a restore). ``run``
composes the existing reviewed steps per archive: catalog proof export,
independent Drive download, crypt restore, catalog restore record and managed
cache publication. Afterwards every member must resolve to a verified cache
copy whose content matches the catalog and therefore the event-day manifest.

Nothing here deletes an original, a cache, a cloud object or a failed attempt.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable

from weather import cold_archive_locations as locations
from weather import execution_host
from weather.market.market_config import date_from_event_slug
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_catalog as catalog
from weather.operations import event_day_manifest as manifests
from weather.operations import production_cold_archive_transfer_core as transfer
from weather.paths import repo_path

TOOL = "weather.operations.workstation_restore_set"
FAMILIES = {family.name: family for family in manifests.EVENT_DAY_ARTIFACT_FAMILIES}
MAX_DEADLINE_SECONDS = 4 * 3600


class RestoreSetRefused(RuntimeError):
    """The restore set cannot be restored as requested; nothing was changed."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _refuse(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise RestoreSetRefused(code, detail)


def _families(names) -> list[str]:
    names = sorted(set(names or ()))
    _refuse(bool(names) and set(names) <= set(FAMILIES), "family_invalid",
            f"choose from {', '.join(sorted(FAMILIES))}")
    return names


def _event_manifest_records(folder: Path) -> dict[str, dict[str, Any]]:
    path = manifests.event_day_manifest_path(folder)
    if not path.is_file():
        _refuse(locations.load_location(path) is None, "event_manifest_archived", str(path))
        _refuse(False, "event_manifest_missing", str(path))
    manifest = manifests.read_event_day_manifest(path)
    _refuse(manifest is not None and manifests.manifest_hash_valid(manifest),
            "event_manifest_invalid", str(path))
    return {record.get("path"): record for record in manifests._manifest_file_records(manifest)}


def plan_restore_set(*, data_root, start_date: date, end_date: date, families) -> dict[str, Any]:
    """Locate the requested members and prove each against its event-day manifest."""
    _refuse(start_date <= end_date, "date_range_invalid", f"{start_date} > {end_date}")
    selected_families = _families(families)
    root = locations.safe_path(Path(data_root).absolute() / "snapshots", directory=True)
    members, archives = [], {}
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        target = date_from_event_slug(folder.name)
        if target is None or not start_date <= target <= end_date:
            continue
        records = None
        for source in locations.registered_sources(folder):
            family = next((name for name in selected_families
                           if manifests._matches_family(Path(source.name), FAMILIES[name])), None)
            if family is None:
                continue
            location = locations.load_location(source)
            _refuse(not source.exists() and not source.is_symlink(), "hand_copied_original",
                    f"{source} is present at an archived original path; only a restore may supply it")
            records = _event_manifest_records(folder) if records is None else records
            record = records.get(source.name) or {}
            _refuse(record.get("sha256") == location.member["sha256"]
                    and record.get("bytes") == location.member["size_bytes"],
                    "event_manifest_mismatch", f"{source} differs from its event-day manifest")
            try:
                cached = locations.cached_path(location)
            except locations.CatalogIntegrityError as exc:
                raise RestoreSetRefused("cache_not_verified", f"{source}: {exc}") from exc
            members.append({"source_path": str(source), "event_slug": folder.name,
                            "target_date": target.isoformat(), "family": family,
                            "archive_id": location.entry["archive_id"],
                            "sha256": location.member["sha256"],
                            "size_bytes": location.member["size_bytes"],
                            "state": "cached" if cached else "archived"})
            if cached is None:
                archives.setdefault(location.entry["archive_id"], {
                    "archive_id": location.entry["archive_id"],
                    "entry_path": str(location.entry_path), "entry_sha256": location.entry_sha256,
                    "drive_root_folder_id": location.entry["drive_root_folder_id"],
                    "bytes": sum(row["size_bytes"] for row in location.entry["files"])})
    return {"tool": TOOL, "status": "PLANNED", "data_root": str(Path(data_root).absolute()),
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "families": selected_families, "members": members,
            "archives": [archives[key] for key in sorted(archives)],
            "restore_bytes": sum(row["bytes"] for row in archives.values()),
            "cleanup_eligible": False}


@dataclass(frozen=True)
class Steps:
    """The two cloud/crypto steps; defaults call the reviewed executors."""

    download: Callable[..., Path]
    restore: Callable[..., tuple[Path, Path]]


def reviewed_steps(*, rclone_executable, rclone_config, dpapi_secret, drive_remote_name,
                   crypt_remote_name) -> Steps:
    def download(*, entry, proofs, output_root, data_root, admission, deadline_monotonic,
                 free_space_reserve_bytes):
        transfer.transfer_chunk(
            crypt_receipt_path=proofs["crypt_receipt"]["path"],
            crypt_receipt_sha256=proofs["crypt_receipt"]["sha256"],
            production_manifest_path=proofs["production_manifest"]["path"],
            production_manifest_sha256=proofs["production_manifest"]["sha256"],
            production_receipt_path=proofs["production_receipt"]["path"],
            production_receipt_sha256=proofs["production_receipt"]["sha256"],
            upload_receipt_path=proofs["upload_receipt"]["path"],
            upload_receipt_sha256=proofs["upload_receipt"]["sha256"],
            plan_sha256=entry["plan_sha256"], archive_id=entry["archive_id"],
            rclone_executable=rclone_executable, rclone_config=rclone_config,
            dpapi_secret=dpapi_secret, drive_remote_name=drive_remote_name,
            drive_root_folder_id=entry["drive_root_folder_id"], output_root=output_root,
            protected_root=data_root, admission=admission, deadline_monotonic=deadline_monotonic,
            free_space_reserve_bytes=free_space_reserve_bytes, phase="download_and_verify")
        return Path(output_root) / "receipt.json"

    def restore(*, entry, proofs, transport_receipt, attempt, restore_id):
        transport, transport_sha = _read(transport_receipt)
        ciphertext_root, output_root = attempt / "ciphertext", attempt / "restore"
        ciphertext_root.mkdir()
        output_root.mkdir()
        bridge.run("restore", production_manifest=proofs["production_manifest"]["path"],
                   production_manifest_sha256=proofs["production_manifest"]["sha256"],
                   production_receipt=proofs["production_receipt"]["path"],
                   production_receipt_sha256=proofs["production_receipt"]["sha256"],
                   plan_sha256=entry["plan_sha256"], archive_id=entry["archive_id"],
                   rclone_executable=rclone_executable, rclone_config=rclone_config,
                   dpapi_secret=dpapi_secret, crypt_remote_name=crypt_remote_name,
                   ciphertext_root=ciphertext_root, output_root=output_root, restore_id=restore_id,
                   crypt_receipt=proofs["crypt_receipt"]["path"],
                   crypt_receipt_sha256=proofs["crypt_receipt"]["sha256"],
                   transport_receipt=transport_receipt, transport_receipt_sha256=transport_sha,
                   downloaded_file=transport["downloaded_file"]["path"])
        return output_root / restore_id / "receipt.json", output_root / restore_id / "members"

    return Steps(download=download, restore=restore)


def _read(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def run_restore_set(*, data_root, work_root, set_id, start_date, end_date, families, steps: Steps,
                    admission, deadline_monotonic, free_space_reserve_bytes,
                    cache_limit_bytes=catalog.DEFAULT_CACHE_BYTES) -> dict[str, Any]:
    """Restore every planned archive, then prove each member reads from the verified cache."""
    locations.archive_id(set_id)
    plan = plan_restore_set(data_root=data_root, start_date=start_date, end_date=end_date,
                            families=families)
    data = Path(plan["data_root"])
    managed = data / "cold_archive" / "restore_cache"
    _refuse(catalog.cache_usage(managed) + plan["restore_bytes"] <= cache_limit_bytes,
            "cache_quota", f"{plan['restore_bytes']} bytes do not fit the restore cache limit")
    work = locations.safe_path(Path(work_root), directory=True)
    _refuse(not work.is_relative_to(data) and not data.is_relative_to(work), "work_root_overlap",
            "the work root must be outside the recovery data root")
    attempt_root = work / set_id
    attempt_root.mkdir()  # Existence spends this set ID, including on failure.
    receipts = []
    for index, archive in enumerate(plan["archives"]):
        catalog._guard(admission, deadline_monotonic)
        entry, _ = locations.read_record(archive["entry_path"], archive["entry_sha256"])
        attempt = attempt_root / archive["archive_id"]
        attempt.mkdir()
        proofs = catalog.export_recovery_proofs(
            entry_path=archive["entry_path"], entry_sha256=archive["entry_sha256"],
            output_root=attempt / "proofs", admission=admission,
            deadline_monotonic=deadline_monotonic)["proof_files"]
        transport_receipt = steps.download(
            entry=entry, proofs=proofs, output_root=attempt / "download", data_root=data,
            admission=admission, deadline_monotonic=deadline_monotonic,
            free_space_reserve_bytes=free_space_reserve_bytes)
        restore_receipt, members_root = steps.restore(
            entry=entry, proofs=proofs, transport_receipt=transport_receipt, attempt=attempt,
            restore_id=f"{set_id}-r{index}")
        _, transport_sha = _read(transport_receipt)
        _, restore_sha = _read(restore_receipt)
        record = catalog.publish_restore(
            entry_path=archive["entry_path"], entry_sha256=archive["entry_sha256"],
            transport_receipt=transport_receipt, transport_receipt_sha256=transport_sha,
            restore_receipt=restore_receipt, restore_receipt_sha256=restore_sha,
            admission=admission, deadline_monotonic=deadline_monotonic)
        cache = catalog.publish_cache(
            entry_path=archive["entry_path"], entry_sha256=archive["entry_sha256"],
            restore_record=record["record_path"], restore_record_sha256=record["record_sha256"],
            restored_members_root=members_root, cache_id=f"{set_id}-c{index}",
            admission=admission, deadline_monotonic=deadline_monotonic,
            free_space_reserve_bytes=free_space_reserve_bytes, cache_limit_bytes=cache_limit_bytes)
        receipts.append({"archive_id": archive["archive_id"], "restore_record": record,
                         "cache": cache})
    for member in plan["members"]:
        # The plan proved catalog SHA == event-day manifest SHA; the cache check
        # re-hashes the restored bytes against that same catalog SHA.
        location = locations.load_location(member["source_path"])
        _refuse(locations.cached_path(location) is not None, "cache_missing_after_restore",
                member["source_path"])
    result = {**plan, "status": "RESTORED", "set_id": set_id, "archive_receipts": receipts,
              "verified_member_count": len(plan["members"])}
    with (attempt_root / "restore-set.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
    return result


def _workstation_guard(deadline_monotonic):
    """Admission for the assigned non-capture workstation under its wrapper."""
    _refuse(os.name == "nt" and os.environ.get(bridge.stage.WRAPPER_ENV) == "1",
            "workstation_wrapper_required", "run through scripts\\ops\\workstation_heavy.ps1")
    assignment_path = repo_path() / execution_host.EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH
    assignment, _ = _read(assignment_path)
    host = execution_host.current_execution_host_id()
    _refuse(assignment.get("assignment_status") == "ASSIGNED"
            and assignment.get("active_portable_execution_host_id") == host
            and assignment.get("active_portable_execution_principal_id")
            == execution_host.current_execution_principal_id()
            and assignment.get("dedicated_capture_execution_host_id") != host,
            "workstation_assignment_required", "restore sets run only on the assigned workstation")

    def admission():
        return (os.environ.get(bridge.stage.WRAPPER_ENV) == "1"
                and time.monotonic() < deadline_monotonic)
    return admission


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("--data-root", required=True)
        command.add_argument("--start-date", required=True, type=date.fromisoformat)
        command.add_argument("--end-date", required=True, type=date.fromisoformat)
        command.add_argument("--family", action="append", required=True, choices=sorted(FAMILIES))
    run = sub.choices["run"]
    for flag in ("work-root", "set-id", "rclone-executable", "rclone-config", "dpapi-secret",
                 "drive-remote-name", "crypt-remote-name"):
        run.add_argument("--" + flag, required=True)
    run.add_argument("--free-space-reserve-bytes", type=int, required=True)
    run.add_argument("--cache-limit-bytes", type=int, default=catalog.DEFAULT_CACHE_BYTES)
    run.add_argument("--deadline-seconds", type=int, default=3600)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    common = dict(data_root=args.data_root, start_date=args.start_date, end_date=args.end_date,
                  families=args.family)
    try:
        if args.operation == "plan":
            result = plan_restore_set(**common)
        else:
            _refuse(0 < args.deadline_seconds <= MAX_DEADLINE_SECONDS, "deadline_invalid",
                    str(args.deadline_seconds))
            deadline = time.monotonic() + args.deadline_seconds
            result = run_restore_set(
                **common, work_root=args.work_root, set_id=args.set_id,
                steps=reviewed_steps(rclone_executable=args.rclone_executable,
                                     rclone_config=args.rclone_config, dpapi_secret=args.dpapi_secret,
                                     drive_remote_name=args.drive_remote_name,
                                     crypt_remote_name=args.crypt_remote_name),
                admission=_workstation_guard(deadline), deadline_monotonic=deadline,
                free_space_reserve_bytes=args.free_space_reserve_bytes,
                cache_limit_bytes=args.cache_limit_bytes)
    except RestoreSetRefused as exc:
        print(json.dumps({"status": "REFUSED", "code": exc.code, "detail": str(exc)}))
        return 2
    except Exception as exc:  # noqa: BLE001 - every partial attempt is retained
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__,
                          "detail": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
