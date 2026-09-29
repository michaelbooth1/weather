"""Bounded, reviewed WU temp plan/preflight/apply; native exact-file deletion."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from weather.operations.cleanup_preflight import build_cleanup_preflight
from weather.operations.production_cold_archive_stage import _load, _safe_path, _write
from weather.operations.wu_orphan_proofs import (
    Budget, OrphanRefused, candidate_path, compare_record, current_proof, observe,
)
from weather.paths import data_path
from weather.schema_registry import schema_version

MAX_ENTRIES = 10000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def plan_hash(manifest):
    return hashlib.sha256(canonical({k: v for k, v in manifest.items()
                                    if k not in {"plan_sha256", "operator_review"}})).hexdigest()


def plan(root, *, max_entries=MAX_ENTRIES, max_bytes=1024**3, max_seconds=300, **observations):
    root = Path(root).absolute()
    _safe_path(root, directory=True)
    if type(max_entries) is not int or not 0 < max_entries <= MAX_ENTRIES:
        raise OrphanRefused("invalid_entry_cap")
    budget = Budget(max_bytes, max_seconds)
    wu = root / "wunderground"
    _safe_path(wu, directory=True)
    selected, refused, stack, visited = [], [], [wu], 0
    stop = None
    while stack and stop is None:
        directory = stack.pop()
        _safe_path(directory, directory=True)
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    budget.admit()
                except OrphanRefused:
                    stop = "time_cap"
                    break
                if visited >= max_entries:
                    stop = "entry_cap"
                    break
                visited += 1
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                try:
                    _safe_path(path, directory=entry.is_dir(follow_symlinks=False))
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                    elif path.name.endswith(".tmp"):
                        with observe(root, relative, budget=budget, **observations) as (_, _, row, _):
                            selected.append(row)
                except (OSError, ValueError) as exc:
                    reason = str(exc) if isinstance(exc, OrphanRefused) else "exclusive_handle_or_file_unavailable"
                    refused.append(dict(path=relative, reason=reason))
                    if reason in {"time_cap", "byte_cap"}:
                        stop = reason
                        break
    manifest = dict(schema_version=schema_version("cleanup_manifest"), kind="wu-atomic-orphans",
        generated_at_utc=time.time(), root=str(root), candidates=sorted(selected, key=lambda r: r["path"]),
        refused=refused, visited_entries=visited, bytes_read=budget.bytes_read, stop_reason=stop,
        limits=dict(max_entries=max_entries, max_bytes=max_bytes, max_seconds=max_seconds),
        operator_review=dict(approved=False, approved_by="", note="", plan_sha256=""))
    manifest["plan_sha256"] = plan_hash(manifest)
    return manifest


def validate_manifest(manifest, root):
    if (manifest.get("schema_version") != schema_version("cleanup_manifest")
            or manifest.get("kind") != "wu-atomic-orphans"
            or manifest.get("plan_sha256") != plan_hash(manifest)
            or Path(manifest.get("root", "")).absolute() != root):
        raise OrphanRefused("manifest_binding_invalid")
    review = manifest.get("operator_review", {})
    if (review.get("approved") is not True or not review.get("approved_by") or not review.get("note")
            or review.get("plan_sha256") != manifest["plan_sha256"]):
        raise OrphanRefused("exact_plan_review_required")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not 0 < len(candidates) <= MAX_ENTRIES:
        raise OrphanRefused("candidate_count_invalid")
    seen = set()
    for row in candidates:
        candidate_path(root, row["path"])
        if row["path"].casefold() in seen:
            raise OrphanRefused("duplicate_candidate")
        seen.add(row["path"].casefold())


def execute(manifest, root, output, *, apply=False, max_bytes=1024**3, max_seconds=300, **observations):
    """Every candidate gets fresh preflight, durable intent, recheck and receipt."""
    root, output = Path(root).absolute(), Path(output).absolute()
    validate_manifest(manifest, root)
    budget = Budget(max_bytes, max_seconds)
    results = []
    for index, candidate in enumerate(manifest["candidates"]):
        result = dict(path=candidate["path"], status="BLOCK", deleted=False)
        try:
            with observe(root, candidate["path"], budget=budget, **observations) as (pin, final, row, proof):
                compare_record(candidate, row)
                preflight = build_cleanup_preflight(dict(manifest, candidates=[candidate]), root=root,
                    sha256_reader=lambda _: row["sha256"],
                    wu_orphan_verifier=lambda *_: proof)
                if preflight["status"] != "PASS":
                    raise OrphanRefused("cleanup_preflight_blocked")
                result.update(preflight=preflight, current_proof=asdict(proof), sha256=row["sha256"])
                if apply:
                    _write(output / f"{index:05d}-intent.json", dict(result, status="INTENT",
                        plan_sha256=manifest["plan_sha256"], candidate=candidate))
                    budget.admit()
                    if pin.metadata() != row["metadata"] or final.metadata() != row["final_metadata"]:
                        raise OrphanRefused("file_identity_changed")
                    fresh = current_proof(row["path"], pin.metadata(), proof.writer_pid,
                        **{k: v for k, v in observations.items() if k in {"process_reader", "now"}})
                    # Both file handles and every ancestor remain pinned.
                    # No pathname unlink or recursive removal fallback.
                    result.update(removal_started=True, deleted=None)
                    pin.remove()
                    result.update(deleted=True, status="DELETED", current_proof=asdict(fresh))
                else:
                    result["status"] = "PASS"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["reason"] = str(exc) if isinstance(exc, OrphanRefused) else "proof_or_io_unavailable"
        _write(output / f"{index:05d}-receipt.json", dict(result, plan_sha256=manifest["plan_sha256"]))
        results.append(result)
        if result["status"] == "BLOCK":
            break
    return dict(schema_version=schema_version("wu_orphan_cleanup_receipt"),
        plan_sha256=manifest["plan_sha256"], apply=apply, results=results, bytes_read=budget.bytes_read,
        status="PASS" if len(results) == len(manifest["candidates"]) and all(r["status"] != "BLOCK" for r in results) else "BLOCK")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "preflight", "apply"])
    parser.add_argument("--root", type=Path, default=data_path())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--max-entries", type=int, default=MAX_ENTRIES)
    parser.add_argument("--max-bytes", type=int, default=1024**3)
    parser.add_argument("--max-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        root, output = args.root.absolute(), args.output.absolute()
        _safe_path(root, directory=True)
        _safe_path(output.parent, directory=True)
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise OrphanRefused("output_must_be_separate_from_source")
        output.mkdir()  # create-only attempt: never overwrite previous evidence.
        if args.command == "plan":
            value = plan(root, max_entries=args.max_entries, max_bytes=args.max_bytes, max_seconds=args.max_seconds)
            _write(output / "manifest.json", value)
        else:
            if not args.manifest or not args.manifest_sha256 or len(args.manifest_sha256) != 64:
                raise OrphanRefused("manifest_sha256_required")
            value, _ = _load(args.manifest.absolute(), args.manifest_sha256)
            value = execute(value, root, output, apply=args.command == "apply",
                            max_bytes=args.max_bytes, max_seconds=args.max_seconds)
            _write(output / "result.json", value)
        print(json.dumps(dict(status=value.get("status", "PLANNED"), output=str(output))))
        return 2 if value.get("status") == "BLOCK" else 0
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps(dict(status="BLOCK", reason="wu_orphan_cleanup_refused")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
