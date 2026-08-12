"""Rebuild and replay captured runtimes from per-file model identities.

This is the outcome-blind -09-76a continuation of -09-75a.  It resolves the
captured SHA-256 fingerprints against Git blobs reachable from every ref,
materializes one disposable synthetic runtime per selected identity, and
replays only the already-frozen incumbent distributions.

No settlement, realized band, market probability, provider, recovery
candidate, alpha decision, or C endpoint is read by this harness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_SEED = SCRIPT_PATH.with_name("measure_identity_binding_09_76a_seed.json")
DEFAULT_RUN_ROOT = DEFAULT_REPO_ROOT / "scratch" / "runs" / "identity-binding-09-76a"
sys.path.insert(0, str(SCRIPT_PATH.parent))
import measure_replay_trust_09_75a as prior  # noqa: E402
import measure_high_so_far_population_09_70a as population  # noqa: E402


IDENTITY_GROUPS = ("code_files", "artifact_files")
ROW_KEY_FIELDS = prior.ROW_KEY_FIELDS
MODEL_PREFIXES = ("weather.model", "weather.calibration")
TORONTO_TZ = ZoneInfo("America/Toronto")
LFS_VERSION = b"version https://git-lfs.github.com/spec/v1\n"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256_bytes(encoded)


def git(repo_root: Path, *args: str, text: bool = True) -> str | bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo_root), *args], text=text
    )


def load_seed(path: Path, repo_root: Path, *, verify_inputs: bool = True) -> dict[str, Any]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    require(seed.get("schema_version") == "identity_binding_seed_v1", "seed schema drifted")
    if verify_inputs:
        for key, value in seed["tracked_inputs"].items():
            if not key.endswith("_relative_path"):
                continue
            prefix = key[: -len("_relative_path")]
            actual = sha256_file(repo_root / value)
            expected = seed["tracked_inputs"][f"{prefix}_sha256"]
            require(actual == expected, f"{prefix} hash mismatch: {actual}")
    return seed


def verify_scratch_input(seed: dict[str, Any], path: Path, key: str) -> None:
    actual = sha256_file(path)
    expected = seed["scratch_inputs"][key]
    require(actual == expected, f"{key} mismatch: {actual}")


def identity_file_items(identity: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for group in IDENTITY_GROUPS:
        for item in identity.get(group) or []:
            yield group, item


def combined_identity_hash(items: list[dict[str, Any]]) -> str:
    reduced = [
        {
            "path": item.get("path"),
            "exists": item.get("exists"),
            "sha256": item.get("sha256"),
        }
        for item in items
    ]
    return canonical_sha256(reduced)


def validate_identity(identity: dict[str, Any]) -> str:
    identity_hash = str(identity.get("identity_hash") or "")
    require(len(identity_hash) == 64, "captured identity hash is missing")
    seen_paths: set[str] = set()
    for group, item in identity_file_items(identity):
        path = str(item.get("path") or "")
        normalized = Path(path)
        require(path and not normalized.is_absolute() and ".." not in normalized.parts, f"unsafe identity path: {path}")
        require(path not in seen_paths, f"duplicate identity path: {path}")
        seen_paths.add(path)
        exists = item.get("exists") is True
        if exists:
            require(len(str(item.get("sha256") or "")) == 64, f"missing SHA-256: {path}")
            require(int(item.get("size")) >= 0, f"missing size: {path}")
        else:
            require(item.get("sha256") is None, f"absent file has SHA-256: {path}")
        require(group in IDENTITY_GROUPS, f"unexpected identity group: {group}")
    require(
        combined_identity_hash(identity.get("code_files") or []) == identity.get("code_hash"),
        f"captured code hash does not recompute: {identity_hash}",
    )
    require(
        combined_identity_hash(identity.get("artifact_files") or [])
        == identity.get("artifact_hash"),
        f"captured artifact hash does not recompute: {identity_hash}",
    )
    payload = {
        "schema_version": identity.get("schema_version"),
        "model_version": identity.get("model_version"),
        "market_id": identity.get("market_id"),
        "active_model_kind": identity.get("active_model_kind"),
        "code_hash": identity.get("code_hash"),
        "artifact_hash": identity.get("artifact_hash"),
    }
    require(
        canonical_sha256(payload) == identity_hash,
        f"captured identity hash does not recompute: {identity_hash}",
    )
    return identity_hash


def selected_identity_context(records_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    context: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "decision_rows": 0,
            "diagnostic_rows": 0,
            "runtime_commits": set(),
            "built_at": [],
            "markets": set(),
        }
    )
    population_counts: Counter[tuple[str, str]] = Counter()
    rows = 0
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            rows += 1
            identity = item["record"].get("model_identity") or {}
            identity_hash = str(identity.get("identity_hash") or "")
            population_name = item["selection"]["analysis_population"]
            population_counts[(population_name, "identity" if identity_hash else "neither")] += 1
            require(identity_hash == str(item["binding"].get("model_identity_hash") or ""), "identity binding drifted")
            if not identity_hash:
                continue
            validate_identity(identity)
            existing = identities.setdefault(identity_hash, identity)
            require(canonical_sha256(existing) == canonical_sha256(identity), f"identity payload changed: {identity_hash}")
            target = context[identity_hash]
            if population_name == "decision_stratum":
                target["decision_rows"] += 1
            else:
                target["diagnostic_rows"] += 1
            commit = str(item["binding"].get("runtime_commit") or "")
            if commit:
                target["runtime_commits"].add(commit)
            built_at = str(item["record"].get("built_at") or item["selection"].get("captured_at_utc") or "")
            if built_at:
                target["built_at"].append(built_at)
            target["markets"].add(item["selection"]["market_id"])
    require(rows == 372, f"selected replay population drifted: {rows}")
    serializable_context = {
        key: {
            **value,
            "runtime_commits": sorted(value["runtime_commits"]),
            "built_at": sorted(value["built_at"]),
            "markets": sorted(value["markets"]),
        }
        for key, value in context.items()
    }
    summary = {
        "rows": rows,
        "identities": len(identities),
        "population_counts": {
            f"{population_name}:{binding}": count
            for (population_name, binding), count in sorted(population_counts.items())
        },
        "context": serializable_context,
    }
    return identities, summary


def extract_identity_catalog(
    seed: dict[str, Any],
    repo_root: Path,
    snapshots_root: Path,
    records_path: Path,
    census_path: Path,
    output: Path,
) -> dict[str, Any]:
    verify_scratch_input(seed, records_path, "replay_records_sha256")
    verify_scratch_input(seed, census_path, "census_records_sha256")
    selected_identities, selected = selected_identity_context(records_path)

    expected_by_day: dict[tuple[str, str], dict[tuple[str, str], str]] = defaultdict(dict)
    B_rows_by_identity: Counter[str] = Counter()
    census_rows = 0
    with census_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            census_rows += 1
            identity_hash = str(row.get("model_identity_hash") or "")
            if identity_hash:
                B_rows_by_identity[identity_hash] += 1
            short_key = (str(row["snapshot_id"]), str(row["captured_at_utc"]))
            day = (str(row["market_id"]), str(row["target_date"]))
            previous = expected_by_day[day].setdefault(short_key, identity_hash)
            require(previous == identity_hash, f"census identity changed within key: {day + short_key}")
    require(census_rows == seed["population"]["B_feature_snapshots_with_replay"], f"B census drifted: {census_rows}")
    require(sum(B_rows_by_identity.values()) == seed["population"]["B_identity_bearing_rows"], "B identity-bearing count drifted")

    prior_seed = prior.load_seed(
        repo_root / seed["tracked_inputs"]["prior_seed_relative_path"], repo_root
    )
    roster = prior.projected_b_roster(prior_seed, repo_root)
    identities = dict(selected_identities)
    found_keys: set[tuple[str, str, str, str]] = set()
    receipts = []
    for roster_row in sorted(roster, key=lambda row: (row["market_id"], row["target_date"])):
        market_id = roster_row["market_id"]
        target_date = roster_row["target_date"]
        day = (market_id, target_date)
        expected = expected_by_day[day]
        replay_file = prior.replay_path(snapshots_root, market_id, target_date)
        require(replay_file.is_file(), f"replay input missing: {replay_file}")
        digest = hashlib.sha256()
        matched: set[tuple[str, str]] = set()
        with replay_file.open("rb") as handle:
            for raw in handle:
                digest.update(raw)
                snapshot_id = population.json_value_by_key(raw, "snapshot_id")
                captured_at = population.json_value_by_key(raw, "captured_at_utc")
                if not isinstance(snapshot_id, str) or not isinstance(captured_at, str):
                    continue
                short_key = (snapshot_id, captured_at)
                if short_key not in expected or short_key in matched:
                    continue
                matched.add(short_key)
                found_keys.add((market_id, target_date, snapshot_id, captured_at))
                expected_hash = expected[short_key]
                identity = population.json_value_by_key(raw, "model_identity") or {}
                actual_hash = str(identity.get("identity_hash") or "")
                require(actual_hash == expected_hash, f"raw identity disagrees with census: {day + short_key}")
                if not actual_hash:
                    continue
                validate_identity(identity)
                existing = identities.setdefault(actual_hash, identity)
                require(canonical_sha256(existing) == canonical_sha256(identity), f"identity payload changed: {actual_hash}")
        require(matched == set(expected), f"census keys missing from replay input: {day}")
        receipts.append(
            {
                "path": replay_file.relative_to(snapshots_root.parent.parent).as_posix()
                if replay_file.is_relative_to(snapshots_root.parent.parent)
                else str(replay_file),
                "bytes": replay_file.stat().st_size,
                "sha256": digest.hexdigest(),
                "census_keys": len(expected),
            }
        )

    expected_key_count = sum(len(items) for items in expected_by_day.values())
    require(len(found_keys) == expected_key_count, f"identity catalog key coverage drifted: {len(found_keys)}")
    require(set(B_rows_by_identity) <= set(identities), "some B identity payloads were not recovered")
    payload = {
        "schema_version": "identity_catalog_v1",
        "mission": seed["mission"],
        "identities": {
            key: {
                "identity": identities[key],
                "B_rows": B_rows_by_identity.get(key, 0),
                **selected["context"].get(
                    key,
                    {
                        "decision_rows": 0,
                        "diagnostic_rows": 0,
                        "runtime_commits": [],
                        "built_at": [],
                        "markets": [],
                    },
                ),
            }
            for key in sorted(identities)
        },
        "support": {
            "B_rows": census_rows,
            "B_identity_bearing_rows": sum(B_rows_by_identity.values()),
            "B_identity_count": len(B_rows_by_identity),
            "selected_identity_count": selected["identities"],
            "selected_population_counts": selected["population_counts"],
            "raw_replay_files": len(receipts),
            "raw_replay_bytes": sum(item["bytes"] for item in receipts),
            "raw_replay_receipts_sha256": canonical_sha256(receipts),
            "records_sha256": sha256_file(records_path),
            "census_sha256": sha256_file(census_path),
        },
        "campaign": seed["campaign"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return payload


def parse_lfs_pointer(data: bytes) -> dict[str, Any] | None:
    if not data.startswith(LFS_VERSION) or len(data) > 1024:
        return None
    lines = data.decode("ascii", errors="strict").splitlines()
    if len(lines) < 3 or not lines[1].startswith("oid sha256:") or not lines[2].startswith("size "):
        return None
    oid = lines[1].split(":", 1)[1]
    size = int(lines[2].split(" ", 1)[1])
    require(len(oid) == 64, f"invalid LFS OID: {oid}")
    return {"oid_sha256": oid, "size": size}


def batch_object_types(repo_root: Path, object_ids: list[str]) -> dict[str, tuple[str, int]]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        input="".join(f"{oid}\n" for oid in object_ids),
        text=True,
        capture_output=True,
        check=True,
    )
    result: dict[str, tuple[str, int]] = {}
    for line in completed.stdout.splitlines():
        oid, kind, size = line.split()
        result[oid] = (kind, int(size))
    require(len(result) == len(object_ids), "Git object type census was incomplete")
    return result


def batch_blob_contents(repo_root: Path, object_ids: list[str]) -> Iterable[tuple[str, bytes]]:
    process = subprocess.Popen(
        ["git", "-C", str(repo_root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(process.stdin is not None and process.stdout is not None, "cannot open git cat-file pipes")
    try:
        for requested in object_ids:
            process.stdin.write(requested.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii").strip()
            resolved, kind, size_text = header.split()
            require(kind == "blob", f"non-blob in blob stream: {header}")
            size = int(size_text)
            data = process.stdout.read(size)
            require(len(data) == size, f"short Git blob read: {requested}")
            require(process.stdout.read(1) == b"\n", f"missing Git blob terminator: {requested}")
            yield resolved, data
    finally:
        process.stdin.close()
        return_code = process.wait()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        require(return_code == 0, f"git cat-file failed: {stderr}")


def common_git_dir(repo_root: Path) -> Path:
    value = str(git(repo_root, "rev-parse", "--git-common-dir")).strip()
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def lfs_object_path(git_dir: Path, oid: str) -> Path:
    return git_dir / "lfs" / "objects" / oid[:2] / oid[2:4] / oid


def ref_snapshot(repo_root: Path) -> tuple[list[dict[str, str]], int]:
    raw = str(
        git(
            repo_root,
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        )
    )
    refs = []
    unmerged_remote = 0
    for line in raw.splitlines():
        name, oid = line.split()
        refs.append({"ref": name, "object": oid})
        if not name.startswith("refs/remotes/origin/") or name in {
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/master",
        }:
            continue
        result = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", oid, "origin/master"]
        )
        if result.returncode != 0:
            unmerged_remote += 1
    return refs, unmerged_remote


def enumerate_reachable_objects(repo_root: Path) -> tuple[list[str], dict[str, list[str]]]:
    raw = str(git(repo_root, "rev-list", "--objects", "--all"))
    object_ids = []
    paths: dict[str, list[str]] = defaultdict(list)
    seen = set()
    for line in raw.splitlines():
        oid, *remainder = line.split(" ", 1)
        if oid not in seen:
            object_ids.append(oid)
            seen.add(oid)
        if remainder and remainder[0] not in paths[oid]:
            paths[oid].append(remainder[0])
    return object_ids, paths


def resolve_fingerprints(
    seed: dict[str, Any], repo_root: Path, catalog_path: Path, output: Path
) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    require(catalog.get("schema_version") == "identity_catalog_v1", "identity catalog schema drifted")
    targets: dict[str, set[tuple[str, int]]] = defaultdict(set)
    target_paths: set[str] = set()
    for entry in catalog["identities"].values():
        identity = entry["identity"]
        validate_identity(identity)
        for _, item in identity_file_items(identity):
            target_paths.add(str(item["path"]))
            if item.get("exists"):
                targets[str(item["sha256"])].add((str(item["path"]), int(item["size"])))

    refs, unmerged_remote = ref_snapshot(repo_root)
    object_ids, object_paths = enumerate_reachable_objects(repo_root)
    object_types = batch_object_types(repo_root, object_ids)
    blobs = [oid for oid in object_ids if object_types[oid][0] == "blob"]
    targeted = [
        oid
        for oid in blobs
        if any(path in target_paths for path in object_paths.get(oid, []))
    ]
    remaining = [oid for oid in blobs if oid not in set(targeted)]
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def scan(oids: list[str], phase: str, unresolved_only: bool) -> None:
        wanted = set(targets) - set(matches) if unresolved_only else set(targets)
        if not wanted:
            return
        for oid, data in batch_blob_contents(repo_root, oids):
            raw_sha = sha256_bytes(data)
            if raw_sha in wanted:
                matches[raw_sha].append(
                    {
                        "kind": "git_blob",
                        "blob_oid": oid,
                        "blob_size": len(data),
                        "observed_paths": object_paths.get(oid, []),
                        "scan_phase": phase,
                    }
                )
            pointer = parse_lfs_pointer(data)
            if pointer and pointer["oid_sha256"] in wanted:
                matches[pointer["oid_sha256"]].append(
                    {
                        "kind": "lfs_pointer_blob",
                        "blob_oid": oid,
                        "blob_size": len(data),
                        "lfs_oid_sha256": pointer["oid_sha256"],
                        "lfs_size": pointer["size"],
                        "observed_paths": object_paths.get(oid, []),
                        "scan_phase": phase,
                    }
                )

    scan(targeted, "captured_paths", unresolved_only=False)
    unresolved_after_paths = sorted(set(targets) - set(matches))
    scan(remaining, "all_reachable_blob_fallback", unresolved_only=True)

    git_dir = common_git_dir(repo_root)
    lfs_verification: dict[str, dict[str, Any]] = {}
    for candidates in matches.values():
        for candidate in candidates:
            if candidate["kind"] != "lfs_pointer_blob":
                continue
            oid = candidate["lfs_oid_sha256"]
            if oid in lfs_verification:
                continue
            path = lfs_object_path(git_dir, oid)
            exists = path.is_file()
            actual_size = path.stat().st_size if exists else None
            verified = bool(exists and actual_size == candidate["lfs_size"] and sha256_file(path) == oid)
            lfs_verification[oid] = {
                "path": str(path),
                "exists": exists,
                "size": actual_size,
                "verified": verified,
            }

    def candidate_rank(candidate: dict[str, Any], path: str) -> tuple[int, int, str]:
        return (
            0 if path in candidate.get("observed_paths", []) else 1,
            0 if candidate["kind"] == "git_blob" else 1,
            candidate["blob_oid"],
        )

    resolutions = {}
    unresolved_files: Counter[str] = Counter()
    for identity_hash, entry in catalog["identities"].items():
        files = []
        for group, item in identity_file_items(entry["identity"]):
            path = str(item["path"])
            base = {
                "group": group,
                "path": path,
                "captured_exists": item.get("exists") is True,
                "captured_size": item.get("size"),
                "captured_sha256": item.get("sha256"),
            }
            if not item.get("exists"):
                files.append(
                    {
                        **base,
                        "status": "resolved_captured_absence",
                        "fingerprint_resolved": True,
                        "materializable": True,
                        "source": None,
                    }
                )
                continue
            candidates = sorted(matches.get(str(item["sha256"]), []), key=lambda value: candidate_rank(value, path))
            valid = [
                value
                for value in candidates
                if (
                    value["kind"] == "git_blob" and value["blob_size"] == int(item["size"])
                )
                or (
                    value["kind"] == "lfs_pointer_blob" and value["lfs_size"] == int(item["size"])
                )
            ]
            if not valid:
                unresolved_files[path] += 1
                files.append(
                    {
                        **base,
                        "status": "unresolved_no_reachable_blob",
                        "fingerprint_resolved": False,
                        "materializable": False,
                        "source": None,
                    }
                )
                continue
            chosen = valid[0]
            materializable = True
            status = "resolved_git_blob"
            if chosen["kind"] == "lfs_pointer_blob":
                materializable = lfs_verification[chosen["lfs_oid_sha256"]]["verified"]
                status = (
                    "resolved_lfs_pointer_and_object"
                    if materializable
                    else "resolved_lfs_pointer_object_unavailable"
                )
            files.append(
                {
                    **base,
                    "status": status,
                    "fingerprint_resolved": True,
                    "materializable": materializable,
                    "source": {**chosen, "candidate_count": len(valid)},
                }
            )
        present = [item for item in files if item["captured_exists"]]
        resolutions[identity_hash] = {
            "market_id": entry["identity"].get("market_id"),
            "model_version": entry["identity"].get("model_version"),
            "active_model_kind": entry["identity"].get("active_model_kind"),
            "B_rows": entry["B_rows"],
            "decision_rows": entry["decision_rows"],
            "diagnostic_rows": entry["diagnostic_rows"],
            "runtime_commits": entry["runtime_commits"],
            "built_at": entry["built_at"],
            "files_total": len(files),
            "captured_present_files": len(present),
            "captured_absent_files": len(files) - len(present),
            "resolved_present_files": sum(item["fingerprint_resolved"] for item in present),
            "materializable_present_files": sum(item["materializable"] for item in present),
            "fully_resolved": all(item["fingerprint_resolved"] for item in present),
            "fully_materializable": all(item["materializable"] for item in present),
            "unresolved_files": [item["path"] for item in present if not item["fingerprint_resolved"]],
            "files": files,
        }

    proof_regular = None
    proof_lfs = None
    for identity_hash, resolution in resolutions.items():
        for item in resolution["files"]:
            source = item.get("source") or {}
            if proof_regular is None and source.get("kind") == "git_blob":
                data = bytes(git(repo_root, "cat-file", "blob", source["blob_oid"], text=False))
                proof_regular = {
                    "identity_hash": identity_hash,
                    "path": item["path"],
                    "captured_sha256": item["captured_sha256"],
                    "git_blob_oid": source["blob_oid"],
                    "git_blob_content_sha256": sha256_bytes(data),
                    "content_bytes": len(data),
                    "mapping": "captured SHA-256 equals SHA-256 of decoded Git blob bytes; it is not the Git object ID",
                }
            if proof_lfs is None and source.get("kind") == "lfs_pointer_blob":
                verification = lfs_verification[source["lfs_oid_sha256"]]
                proof_lfs = {
                    "identity_hash": identity_hash,
                    "path": item["path"],
                    "captured_sha256": item["captured_sha256"],
                    "git_pointer_blob_oid": source["blob_oid"],
                    "pointer_oid_sha256": source["lfs_oid_sha256"],
                    "pointer_declared_size": source["lfs_size"],
                    "local_lfs_object_verified": verification["verified"],
                    "mapping": "captured SHA-256 equals the tracked LFS pointer oid and the verified local LFS object bytes",
                }
            if proof_regular and proof_lfs:
                break
        if proof_regular and proof_lfs:
            break

    B_full = sum(item["B_rows"] for item in resolutions.values() if item["fully_resolved"])
    decision_full = sum(
        item["decision_rows"] for item in resolutions.values() if item["fully_resolved"]
    )
    payload = {
        "schema_version": "identity_resolution_v1",
        "mission": seed["mission"],
        "catalog_sha256": sha256_file(catalog_path),
        "ref_scope": {
            "refs": refs,
            "ref_count": len(refs),
            "refs_sha256": canonical_sha256(refs),
            "unmerged_origin_branch_count": unmerged_remote,
            "reachable_object_count": len(object_ids),
            "reachable_blob_count": len(blobs),
            "captured_path_blob_count": len(targeted),
            "global_fallback_blob_count": len(remaining),
            "unresolved_hashes_after_path_scan": unresolved_after_paths,
            "all_reachable_objects_scanned_for_final_unresolved": bool(unresolved_after_paths),
        },
        "hash_mapping_proof": {
            "regular_blob": proof_regular,
            "lfs_artifact": proof_lfs,
        },
        "support": {
            "target_fingerprints": len(targets),
            "resolved_target_fingerprints": len(set(targets) & set(matches)),
            "unresolved_target_fingerprints": sorted(set(targets) - set(matches)),
            "identity_count": len(resolutions),
            "fully_resolved_identities": sum(item["fully_resolved"] for item in resolutions.values()),
            "partially_resolved_identities": sum(not item["fully_resolved"] for item in resolutions.values()),
            "selected_identity_count": sum(bool(item["decision_rows"] or item["diagnostic_rows"]) for item in resolutions.values()),
            "B_fully_resolved_rows": B_full,
            "B_total_rows": seed["population"]["B_feature_snapshots_with_replay"],
            "B_identity_bearing_rows": seed["population"]["B_identity_bearing_rows"],
            "decision_fully_resolved_rows": decision_full,
            "decision_identity_bearing_rows": seed["population"]["decision_runtime_commit_bound_rows"] + seed["population"]["decision_identity_only_rows"],
            "unresolved_file_identity_counts": dict(sorted(unresolved_files.items())),
        },
        "lfs_verification": lfs_verification,
        "identities": resolutions,
        "runtime_trees": {},
        "campaign": seed["campaign"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return payload


def reachable_commits(repo_root: Path) -> list[tuple[int, str]]:
    result = []
    seen = set()
    for line in str(git(repo_root, "rev-list", "--all", "--timestamp")).splitlines():
        timestamp_text, commit = line.split()
        if commit not in seen:
            result.append((int(timestamp_text), commit))
            seen.add(commit)
    return result


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def tree_entries(repo_root: Path, commit: str, paths: list[str]) -> dict[str, str]:
    raw = bytes(
        git(
            repo_root,
            "ls-tree",
            "-r",
            "-z",
            commit,
            "--",
            *paths,
            text=False,
        )
    )
    entries = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        _mode, kind, oid = metadata.decode("ascii").split()
        if kind == "blob":
            entries[path.decode("utf-8")] = oid
    return entries


def donor_score(resolution: dict[str, Any], entries: dict[str, str]) -> int:
    score = 0
    for item in resolution["files"]:
        actual_oid = entries.get(item["path"])
        if not item["captured_exists"]:
            score += actual_oid is None
            continue
        source = item.get("source") or {}
        score += actual_oid == source.get("blob_oid")
    return score


def select_donor_commit(
    repo_root: Path,
    resolution: dict[str, Any],
    commit_times: list[tuple[int, str]],
) -> dict[str, Any]:
    built = [parse_timestamp(value).timestamp() for value in resolution.get("built_at") or []]
    anchor = statistics.median(built) if built else max(timestamp for timestamp, _ in commit_times)
    nearest = sorted(commit_times, key=lambda item: (abs(item[0] - anchor), item[1]))[:12]
    candidates = {commit for _, commit in nearest}
    for abbreviation in resolution.get("runtime_commits") or []:
        candidates.add(str(git(repo_root, "rev-parse", abbreviation)).strip())
    paths = [item["path"] for item in resolution["files"]]
    scored = []
    timestamp_by_commit = {commit: timestamp for timestamp, commit in commit_times}
    for commit in sorted(candidates):
        entries = tree_entries(repo_root, commit, paths)
        scored.append(
            {
                "commit": commit,
                "matching_identity_paths": donor_score(resolution, entries),
                "identity_paths": len(paths),
                "distance_to_capture_seconds": abs(timestamp_by_commit[commit] - anchor),
            }
        )
    scored.sort(
        key=lambda item: (
            -item["matching_identity_paths"],
            item["distance_to_capture_seconds"],
            item["commit"],
        )
    )
    require(scored, "no donor commit candidates")
    return {**scored[0], "candidates_scored": len(scored)}


def safe_extract_tar(tar_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(tar_path, "r") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            require(
                target == destination_resolved or destination_resolved in target.parents,
                f"unsafe git archive member: {member.name}",
            )
        archive.extractall(destination, filter="data")


def preserve_existing(target: Path, preserve_root: Path, relative_path: str) -> None:
    if not target.exists():
        return
    preserved = preserve_root / relative_path
    preserved.parent.mkdir(parents=True, exist_ok=True)
    require(not preserved.exists(), f"preserved donor path already exists: {preserved}")
    target.replace(preserved)


def ensure_normal_blob(
    repo_root: Path, blob_store: Path, captured_sha256: str, blob_oid: str, expected_size: int
) -> Path:
    destination = blob_store / captured_sha256
    if destination.is_file():
        require(destination.stat().st_size == expected_size, f"blob store size drifted: {destination}")
        require(sha256_file(destination) == captured_sha256, f"blob store hash drifted: {destination}")
        return destination
    data = bytes(git(repo_root, "cat-file", "blob", blob_oid, text=False))
    require(len(data) == expected_size, f"resolved Git blob size mismatch: {blob_oid}")
    require(sha256_bytes(data) == captured_sha256, f"resolved Git blob SHA mismatch: {blob_oid}")
    blob_store.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.exists(), f"synthetic target already exists: {destination}")
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def hydrate_donor_lfs(
    target: Path, preserved_root: Path, relative_path: str, git_dir: Path
) -> dict[str, Any] | None:
    if not target.is_file() or target.stat().st_size > 1024:
        return None
    pointer = parse_lfs_pointer(target.read_bytes())
    if pointer is None:
        return None
    source = lfs_object_path(git_dir, pointer["oid_sha256"])
    if not source.is_file() or source.stat().st_size != pointer["size"]:
        return {
            "status": "donor_lfs_object_unavailable",
            "oid_sha256": pointer["oid_sha256"],
            "size": pointer["size"],
        }
    preserve_existing(target, preserved_root, relative_path)
    link_or_copy(source, target)
    return {
        "status": "donor_lfs_object_materialized",
        "oid_sha256": pointer["oid_sha256"],
        "size": pointer["size"],
    }


def assemble_runtime_trees(
    seed: dict[str, Any],
    repo_root: Path,
    catalog_path: Path,
    resolution_path: Path,
    run_root: Path,
) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload = json.loads(resolution_path.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == "identity_resolution_v1", "resolution schema drifted")
    require(not payload.get("runtime_trees"), "runtime trees already recorded; refusing to overwrite")
    selected_hashes = [
        identity_hash
        for identity_hash, item in payload["identities"].items()
        if item["decision_rows"] or item["diagnostic_rows"]
    ]
    require(len(selected_hashes) == 63, f"selected identity count drifted: {len(selected_hashes)}")
    commit_times = reachable_commits(repo_root)
    git_dir = common_git_dir(repo_root)
    base_root = run_root / "b4"
    tree_root = run_root / "r4"
    blob_store = run_root / "resolved-blobs"
    base_root.mkdir(parents=True, exist_ok=True)
    tree_root.mkdir(parents=True, exist_ok=True)
    donors: dict[str, dict[str, Any]] = {}
    for identity_hash in selected_hashes:
        donors[identity_hash] = select_donor_commit(
            repo_root, payload["identities"][identity_hash], commit_times
        )
    short_names = {identity_hash: identity_hash[:16] for identity_hash in selected_hashes}
    require(len(set(short_names.values())) == len(short_names), "identity path prefixes collide")

    for index, identity_hash in enumerate(sorted(selected_hashes), start=1):
        resolution = payload["identities"][identity_hash]
        donor = donors[identity_hash]
        commit = donor["commit"]
        base = base_root / commit
        if not base.is_dir():
            archive_path = base_root / f"{commit}.tar"
            require(not archive_path.exists(), f"base archive already exists without base tree: {archive_path}")
            top_level = set(
                str(git(repo_root, "ls-tree", "-d", "--name-only", commit)).splitlines()
            )
            archive_roots = [name for name in ("src", "artifacts", "config") if name in top_level]
            require("src" in archive_roots, f"donor commit has no src tree: {commit}")
            subprocess.run(
                [
                    "git",
                    "-c",
                    "filter.lfs.process=",
                    "-c",
                    "filter.lfs.smudge=",
                    "-c",
                    "filter.lfs.required=false",
                    "-C",
                    str(repo_root),
                    "archive",
                    "--format=tar",
                    f"--output={archive_path}",
                    commit,
                    *archive_roots,
                ],
                check=True,
                env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
            )
            base.mkdir(parents=True)
            safe_extract_tar(archive_path, base)
        runtime = tree_root / short_names[identity_hash]
        require(not runtime.exists(), f"synthetic runtime already exists: {runtime}")
        shutil.copytree(base, runtime, copy_function=os.link)
        preserved = runtime / "_identity_binding_preserved_donor"
        absent = runtime / "_identity_binding_captured_absent"
        donor_lfs = []
        for item in resolution["files"]:
            target = runtime / item["path"]
            if not item["captured_exists"]:
                preserve_existing(target, absent, item["path"])
                continue
            if not item["fingerprint_resolved"] or not item["materializable"]:
                hydration = hydrate_donor_lfs(
                    target, preserved / "unresolved_lfs_pointer", item["path"], git_dir
                )
                if hydration:
                    donor_lfs.append({"path": item["path"], **hydration})
                continue
            source = item["source"]
            preserve_existing(target, preserved / "overlaid", item["path"])
            if source["kind"] == "git_blob":
                materialized = ensure_normal_blob(
                    repo_root,
                    blob_store,
                    item["captured_sha256"],
                    source["blob_oid"],
                    int(item["captured_size"]),
                )
            else:
                materialized = lfs_object_path(git_dir, source["lfs_oid_sha256"])
                require(materialized.is_file(), f"resolved LFS object missing: {materialized}")
                require(materialized.stat().st_size == int(item["captured_size"]), f"resolved LFS size mismatch: {materialized}")
            link_or_copy(materialized, target)
        file_audit = []
        for item in resolution["files"]:
            target = runtime / item["path"]
            actual_exists = target.is_file()
            actual_sha = sha256_file(target) if actual_exists else None
            file_audit.append(
                {
                    "path": item["path"],
                    "captured_exists": item["captured_exists"],
                    "actual_exists": actual_exists,
                    "captured_sha256": item["captured_sha256"],
                    "actual_sha256": actual_sha,
                    "matches_captured": actual_exists == item["captured_exists"]
                    and (not actual_exists or actual_sha == item["captured_sha256"]),
                }
            )
        matched_files = sum(item["matches_captured"] for item in file_audit)
        payload["runtime_trees"][identity_hash] = {
            "runtime_root": str(runtime.resolve()),
            "donor": donor,
            "captured_files_matching_tree": matched_files,
            "captured_files_total": len(file_audit),
            "tree_matches_full_identity": matched_files == len(file_audit),
            "donor_lfs_hydration": donor_lfs,
            "file_audit_sha256": canonical_sha256(file_audit),
        }
        print(
            f"ASSEMBLED {index}/{len(selected_hashes)} {identity_hash[:12]} "
            f"files={matched_files}/{len(file_audit)} donor={commit[:12]}",
            flush=True,
        )
    payload["assembly"] = {
        "selected_identities": len(selected_hashes),
        "runtime_root": str(tree_root.resolve()),
        "base_commits": sorted({item["commit"] for item in donors.values()}),
        "no_source_branch_modified": True,
        "donor_bytes_preserved": True,
    }
    resolution_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return payload


def audit_identity_tree(identity: dict[str, Any], runtime_root: Path) -> dict[str, Any]:
    rows = []
    for group, item in identity_file_items(identity):
        target = runtime_root / str(item["path"])
        actual_exists = target.is_file()
        actual_sha = sha256_file(target) if actual_exists else None
        matches = actual_exists == (item.get("exists") is True) and (
            not actual_exists or actual_sha == item.get("sha256")
        )
        rows.append(
            {
                "group": group,
                "path": item["path"],
                "captured_exists": item.get("exists") is True,
                "actual_exists": actual_exists,
                "captured_sha256": item.get("sha256"),
                "actual_sha256": actual_sha,
                "matches": matches,
            }
        )
    return {
        "files": len(rows),
        "matching_files": sum(item["matches"] for item in rows),
        "matches_full_identity": all(item["matches"] for item in rows),
        "unmatched_files": [item["path"] for item in rows if not item["matches"]],
        "files_sha256": canonical_sha256(rows),
    }


def resolved_module_files(runtime_root: Path) -> dict[str, str]:
    modules: dict[str, str] = {}
    intended = (runtime_root / "src").resolve()
    escaped_weather: dict[str, str] = {}
    for name, module in sorted(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        resolved = Path(module_file).resolve()
        if intended == resolved or intended in resolved.parents:
            modules[name] = str(resolved)
        elif name == "weather" or name.startswith("weather."):
            escaped_weather[name] = str(resolved)
    require(
        not escaped_weather,
        f"weather module escaped synthetic identity tree: {escaped_weather}",
    )
    return modules


def import_runtime_model(runtime_root: Path) -> tuple[Any, str]:
    """Import through the layout actually present in the synthetic donor tree."""

    packaged_entrypoint = runtime_root / "src" / "weather" / "model" / "toronto_model.py"
    packaged_init = runtime_root / "src" / "weather" / "__init__.py"
    flat_entrypoint = runtime_root / "src" / "toronto_model.py"
    if packaged_init.is_file() and packaged_entrypoint.is_file():
        module_name = "weather.model.toronto_model"
    elif flat_entrypoint.is_file():
        module_name = "toronto_model"
    else:
        require(
            packaged_entrypoint.is_file(),
            "synthetic donor has neither a packaged nor flat Toronto model entrypoint",
        )
        package_root = runtime_root / "src" / "weather"
        historical_flat_paths = [package_root]
        historical_flat_paths.extend(
            candidate for candidate in sorted(package_root.iterdir()) if candidate.is_dir()
        )
        sys.path[:0] = [str(candidate) for candidate in historical_flat_paths]
        module_name = "toronto_model"
    module = importlib.import_module(module_name)
    module_file = Path(str(getattr(module, "__file__", ""))).resolve()
    intended = (runtime_root / "src").resolve()
    require(
        intended == module_file or intended in module_file.parents,
        f"model entrypoint escaped synthetic identity tree: {module_name} -> {module_file}",
    )
    return module, module_name


def compatible_feature_source_binding(
    model: Any,
    sources: dict[str, Any],
    cutoff_hour: int,
    high_so_far: Any,
    current_temp: Any,
) -> dict[str, Any]:
    try:
        return prior.feature_source_binding(
            model, sources, cutoff_hour, high_so_far, current_temp
        )
    except AttributeError as error:
        return {
            "status": "unavailable_in_historical_model_api",
            "error": f"{type(error).__name__}: {error}",
        }


def replay_identity(
    seed: dict[str, Any],
    records_path: Path,
    catalog_path: Path,
    resolution_path: Path,
    identity_hash: str,
    runtime_root: Path,
    scientific_site: Path,
    output: Path,
) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    require(identity_hash in catalog["identities"], f"identity absent from catalog: {identity_hash}")
    require(identity_hash in resolution["runtime_trees"], f"identity runtime absent: {identity_hash}")
    expected_runtime = Path(resolution["runtime_trees"][identity_hash]["runtime_root"]).resolve()
    require(expected_runtime == runtime_root.resolve(), f"runtime root disagrees with resolution: {runtime_root}")
    identity = catalog["identities"][identity_hash]["identity"]
    audit = audit_identity_tree(identity, runtime_root)
    resolution_item = resolution["identities"][identity_hash]
    require(
        audit["matches_full_identity"] == resolution_item["fully_materializable"],
        f"tree fidelity disagrees with resolution class: {identity_hash}",
    )
    preloaded = [name for name in sys.modules if name == "weather" or name.startswith("weather.")]
    require(not preloaded, f"weather modules loaded before synthetic path binding: {preloaded}")
    sys.path.insert(0, str(scientific_site))
    sys.path.insert(0, str(runtime_root / "src"))
    os.chdir(runtime_root)
    toronto, entrypoint_module = import_runtime_model(runtime_root)

    selected = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if str(item["binding"].get("model_identity_hash") or "") == identity_hash:
                selected.append(item)
    require(selected, f"no selected rows for identity: {identity_hash}")
    tolerance = float(seed["replay"]["l1_tolerance"])
    feature_tolerance = float(seed["replay"]["feature_tolerance"])
    results = []
    for item in selected:
        selection = item["selection"]
        record = item["record"]
        captured_identity = record.get("model_identity") or {}
        require(captured_identity.get("identity_hash") == identity_hash, "selected identity drifted")
        model = toronto.TorontoHighTempModel(
            target_date=date.fromisoformat(selection["target_date"]),
            market_id=selection["market_id"],
        )
        now = datetime.fromisoformat(record["built_at"])
        replayed = model.estimate_distribution(record["sources"], now=now)
        l1, max_abs = prior.distribution_error(record.get("recorded_distribution") or {}, replayed)
        band_differences = prior.distribution_differences(
            record.get("recorded_distribution") or {}, replayed, tolerance
        )
        history_rows = model.source_data(record["sources"], "wu_history").get("rows") or []
        cutoff = model.effective_intraday_cutoff_hour(now, history_rows)
        replayed_features = model.live_feature_record(
            record["sources"],
            cutoff,
            captured_at=now,
            model_version=record.get("model_version"),
        )
        differences = prior.compare_features(
            item["recorded_features"], replayed_features, feature_tolerance
        )
        recorded_source = compatible_feature_source_binding(
            model,
            record["sources"],
            int(float(item["recorded_features"]["cutoff_hour"])),
            item["recorded_features"].get("high_so_far"),
            item["recorded_features"].get("current_temp"),
        )
        replayed_source = compatible_feature_source_binding(
            model,
            record["sources"],
            int(replayed_features["cutoff_hour"]),
            replayed_features.get("high_so_far"),
            replayed_features.get("current_temp"),
        )
        runtime_identity = record.get("runtime_identity") or {}
        results.append(
            {
                **selection,
                **item["binding"],
                "identity_hash": identity_hash,
                "identity_resolution_class": (
                    "fully_resolved" if resolution_item["fully_resolved"] else "partially_resolved"
                ),
                "tree_matches_full_identity": audit["matches_full_identity"],
                "l1": l1,
                "max_abs": max_abs,
                "matches": l1 <= tolerance,
                "recorded_active_model_kind": captured_identity.get("active_model_kind"),
                "replayed_active_model_kind": getattr(model, "active_model_kind", None),
                "feature_difference_count": len(differences),
                "first_feature_difference": differences[0] if differences else None,
                "feature_differences_sha256": canonical_sha256(differences),
                "feature_difference_examples": differences[:20] if l1 > tolerance else [],
                "first_distribution_difference": band_differences[0] if band_differences else None,
                "distribution_difference_examples": band_differences[:20],
                "recorded_feature_source": recorded_source,
                "replayed_feature_source": replayed_source,
                "runtime_source_fingerprint": runtime_identity.get("source_fingerprint"),
                "runtime_identity_captured_at_utc": runtime_identity.get("captured_at_utc"),
                "runtime_python_version": runtime_identity.get("python_version"),
            }
        )
    modules = resolved_module_files(runtime_root)
    receipt = {
        "schema_version": "identity_binding_runtime_receipt_v1",
        "identity_hash": identity_hash,
        "runtime_root": str(runtime_root.resolve()),
        "resolution_class": (
            "fully_resolved" if resolution_item["fully_resolved"] else "partially_resolved"
        ),
        "tree_matches_full_identity": audit["matches_full_identity"],
        "identity_tree_audit": audit,
        "module_files": modules,
        "entrypoint_module": entrypoint_module,
        "tolerance": tolerance,
        "rows": len(results),
        "decision_rows": sum(row["analysis_population"] == "decision_stratum" for row in results),
        "diagnostic_rows": sum(row["analysis_population"] == "source_switch_diagnostic" for row in results),
        "matched_rows": sum(row["matches"] for row in results),
        "failed_rows": sum(not row["matches"] for row in results),
        "max_l1": max((row["l1"] for row in results), default=None),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return receipt


def run_all_identities(
    script_path: Path,
    seed_path: Path,
    records_path: Path,
    catalog_path: Path,
    resolution_path: Path,
    python311: Path,
    scientific_site: Path,
    receipts_root: Path,
    run_manifest_path: Path,
) -> dict[str, Any]:
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    identities = sorted(resolution["runtime_trees"])
    require(len(identities) == 63, f"runtime identity count drifted: {len(identities)}")
    receipts_root.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for index, identity_hash in enumerate(identities, start=1):
        output = receipts_root / f"receipt-{identity_hash}.json"
        if output.is_file():
            existing = json.loads(output.read_text(encoding="utf-8"))
            require(existing.get("identity_hash") == identity_hash, f"receipt identity drifted: {output}")
            outcomes.append(
                {
                    "identity_hash": identity_hash,
                    "returncode": 0,
                    "receipt": str(output.resolve()),
                    "stdout": "",
                    "stderr": "",
                    "reused": True,
                }
            )
            print(f"REUSE {index}/{len(identities)} {identity_hash[:12]}", flush=True)
            continue
        runtime_root = Path(resolution["runtime_trees"][identity_hash]["runtime_root"])
        command = [
            str(python311),
            str(script_path),
            "--seed",
            str(seed_path),
            "replay",
            "--records",
            str(records_path),
            "--catalog",
            str(catalog_path),
            "--resolution",
            str(resolution_path),
            "--identity-hash",
            identity_hash,
            "--runtime-root",
            str(runtime_root),
            "--scientific-site",
            str(scientific_site),
            "--output",
            str(output),
        ]
        completed = subprocess.run(command, text=True, capture_output=True)
        outcomes.append(
            {
                "identity_hash": identity_hash,
                "returncode": completed.returncode,
                "receipt": str(output.resolve()) if output.is_file() else None,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "reused": False,
            }
        )
        print(
            f"REPLAY {index}/{len(identities)} {identity_hash[:12]} exit={completed.returncode}",
            flush=True,
        )
    payload = {
        "schema_version": "identity_binding_run_manifest_v1",
        "python311": str(python311.resolve()),
        "python311_version": subprocess.check_output(
            [str(python311), "--version"], text=True, stderr=subprocess.STDOUT
        ).strip(),
        "scientific_site": str(scientific_site.resolve()),
        "identities": len(identities),
        "successful": sum(item["returncode"] == 0 for item in outcomes),
        "failed": sum(item["returncode"] != 0 for item in outcomes),
        "outcomes": outcomes,
    }
    run_manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return payload


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def replay_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = [row for row in rows if row.get("identity_replay_attempted")]
    matched = sum(row.get("identity_matches") is True for row in attempted)
    failures = [float(row["identity_l1"]) for row in attempted if row.get("identity_matches") is False]
    return {
        "rows": len(rows),
        "replayed_rows": len(attempted),
        "matched_rows": matched,
        "failed_rows": len(attempted) - matched,
        "match_rate": matched / len(attempted) if attempted else None,
        "failure_l1": {
            "count": len(failures),
            "median": percentile(failures, 0.5),
            "p90": percentile(failures, 0.9),
            "p99": percentile(failures, 0.99),
            "max": max(failures, default=None),
        },
    }


def grouped_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "missing")].append(row)
    return {key: replay_summary(items) for key, items in sorted(grouped.items())}


def load_previous_rows(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {prior.row_key(row): row for row in csv.DictReader(handle)}


def commit_metadata(repo_root: Path, commits: set[str]) -> dict[str, dict[str, Any]]:
    result = {}
    for abbreviation in sorted(commits):
        raw = str(git(repo_root, "show", "-s", "--format=%H|%ct|%cI|%s", abbreviation)).strip()
        commit, timestamp, iso_time, subject = raw.split("|", 3)
        landed_utc = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        landed_local = landed_utc.astimezone(TORONTO_TZ)
        result[abbreviation] = {
            "commit": commit,
            "committer_timestamp": int(timestamp),
            "committer_iso": iso_time,
            "subject": subject,
            "toronto_local_time": landed_local.isoformat(),
            "toronto_local_hour": landed_local.hour,
            "inside_12_to_18_local": 12 <= landed_local.hour < 18,
        }
    return result


def identity_transition_times(census_path: Path) -> dict[str, list[float]]:
    by_market: dict[str, list[tuple[float, str]]] = defaultdict(list)
    with census_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            timestamp = parse_timestamp(str(row["captured_at_utc"])).timestamp()
            by_market[str(row["market_id"])].append(
                (timestamp, str(row.get("model_identity_hash") or ""))
            )
    transitions: dict[str, list[float]] = {}
    for market, values in by_market.items():
        ordered = sorted(set(values))
        points = []
        previous = None
        for timestamp, identity_hash in ordered:
            if previous is not None and identity_hash != previous:
                points.append(timestamp)
            previous = identity_hash
        transitions[market] = points
    return transitions


def nearest_distance(value: float, candidates: list[float]) -> float | None:
    return min((abs(value - candidate) for candidate in candidates), default=None)


def timing_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    absolute = abs(seconds)
    if absolute <= 3600:
        return "within_1h"
    if absolute <= 6 * 3600:
        return "1_to_6h"
    if absolute <= 24 * 3600:
        return "6_to_24h"
    return "over_24h"


def bool_text(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def aggregate_results(
    seed: dict[str, Any],
    repo_root: Path,
    records_path: Path,
    census_path: Path,
    catalog_path: Path,
    resolution_path: Path,
    run_manifest_path: Path,
    receipts_root: Path,
    csv_path: Path,
    manifest_path: Path,
    checksums_path: Path,
) -> dict[str, Any]:
    verify_scratch_input(seed, records_path, "replay_records_sha256")
    verify_scratch_input(seed, census_path, "census_records_sha256")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    require(run_manifest["failed"] == 0 and run_manifest["successful"] == 63, "not every identity replay succeeded")
    previous_path = repo_root / seed["tracked_inputs"]["prior_csv_relative_path"]
    previous = load_previous_rows(previous_path)

    base_rows = []
    records_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            key = prior.row_key(item)
            records_by_key[key] = item
            prior_row = previous[key]
            identity_hash = str(item["binding"].get("model_identity_hash") or "")
            resolution_item = resolution["identities"].get(identity_hash)
            base_rows.append(
                {
                    **item["selection"],
                    **item["binding"],
                    "identity_hash": identity_hash,
                    "identity_resolution_class": (
                        "fully_resolved"
                        if resolution_item and resolution_item["fully_resolved"]
                        else "partially_resolved"
                        if resolution_item
                        else "no_identity"
                    ),
                    "identity_files_resolved": resolution_item["resolved_present_files"] if resolution_item else None,
                    "identity_files_present": resolution_item["captured_present_files"] if resolution_item else None,
                    "identity_unresolved_files": resolution_item["unresolved_files"] if resolution_item else [],
                    "identity_replay_attempted": False,
                    "identity_matches": None,
                    "identity_l1": None,
                    "identity_max_abs": None,
                    "tree_matches_full_identity": None,
                    "feature_difference_count": None,
                    "first_feature_difference": None,
                    "recorded_active_model_kind": None,
                    "replayed_active_model_kind": None,
                    "runtime_source_fingerprint": None,
                    "runtime_python_version": None,
                    "commit_replay_attempted": prior_row["replay_attempted"] == "true",
                    "commit_matches": prior_row["matches"] == "true" if prior_row["matches"] else None,
                    "commit_l1": float(prior_row["l1"]) if prior_row["l1"] else None,
                }
            )
    indexed = {prior.row_key(row): row for row in base_rows}
    require(len(indexed) == 372, f"selected aggregate population drifted: {len(indexed)}")

    receipt_files = []
    for outcome in run_manifest["outcomes"]:
        path = Path(outcome["receipt"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        receipt_files.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "identity_hash": payload["identity_hash"],
                "resolution_class": payload["resolution_class"],
                "tree_matches_full_identity": payload["tree_matches_full_identity"],
                "rows": payload["rows"],
                "matched_rows": payload["matched_rows"],
                "failed_rows": payload["failed_rows"],
                "max_l1": payload["max_l1"],
                "entrypoint_module": payload["entrypoint_module"],
                "module_files": payload["module_files"],
                "identity_tree_audit": payload["identity_tree_audit"],
            }
        )
        for result in payload["results"]:
            key = prior.row_key(result)
            require(key in indexed, f"identity receipt row outside population: {key}")
            target = indexed[key]
            require(not target["identity_replay_attempted"], f"row replayed twice: {key}")
            for source, destination in (
                ("matches", "identity_matches"),
                ("l1", "identity_l1"),
                ("max_abs", "identity_max_abs"),
                ("tree_matches_full_identity", "tree_matches_full_identity"),
                ("feature_difference_count", "feature_difference_count"),
                ("first_feature_difference", "first_feature_difference"),
                ("recorded_active_model_kind", "recorded_active_model_kind"),
                ("replayed_active_model_kind", "replayed_active_model_kind"),
                ("runtime_source_fingerprint", "runtime_source_fingerprint"),
                ("runtime_python_version", "runtime_python_version"),
            ):
                target[destination] = result.get(source)
            target["identity_replay_attempted"] = True

    decision = [row for row in indexed.values() if row["analysis_population"] == "decision_stratum"]
    diagnostics = [row for row in indexed.values() if row["analysis_population"] == "source_switch_diagnostic"]
    identity_bearing = [row for row in decision if row["identity_hash"]]
    require(len(identity_bearing) == 366, f"decision identity population drifted: {len(identity_bearing)}")
    require(all(row["identity_replay_attempted"] for row in identity_bearing), "not every identity-bearing decision row replayed")
    require(sum(not row["identity_hash"] for row in decision) == 2, "neither-bound decision rows drifted")

    commits = {row["runtime_commit"] for row in decision if row["runtime_commit"]}
    commit_info = commit_metadata(repo_root, commits)
    transitions = identity_transition_times(census_path)
    for row in decision:
        captured = parse_timestamp(row["captured_at_utc"]).timestamp()
        commit = row["runtime_commit"]
        if commit:
            landing = commit_info[commit]
            row["commit_age_seconds"] = captured - landing["committer_timestamp"]
            row["commit_toronto_local_hour"] = landing["toronto_local_hour"]
            row["commit_inside_12_to_18_local"] = landing["inside_12_to_18_local"]
        else:
            row["commit_age_seconds"] = None
            row["commit_toronto_local_hour"] = None
            row["commit_inside_12_to_18_local"] = None
        distance = nearest_distance(captured, transitions.get(row["market_id"], []))
        row["nearest_identity_transition_seconds"] = distance
        row["commit_age_bucket"] = timing_bucket(row["commit_age_seconds"])
        row["identity_transition_bucket"] = timing_bucket(distance)

    bound = [row for row in decision if row["binding_class"] == "runtime_commit_bound"]
    fully = [row for row in identity_bearing if row["identity_resolution_class"] == "fully_resolved"]
    partial = [row for row in identity_bearing if row["identity_resolution_class"] == "partially_resolved"]
    full_failures = [row for row in fully if row["identity_matches"] is False]
    partial_failures = [row for row in partial if row["identity_matches"] is False]
    fully_resolved_testable = bool(fully)
    residual_exists = bool(full_failures) if fully_resolved_testable else None
    if not fully_resolved_testable:
        verdict = "NO_SELECTED_IDENTITY_FULLY_RESOLVES_FROM_REACHABLE_GIT"
    elif residual_exists:
        verdict = "IDENTITY_BINDING_DOES_NOT_REPRODUCE_CAPTURED_OUTPUT"
    else:
        verdict = "IDENTITY_BINDING_RESTORES_REPRODUCTION_ON_FULLY_RESOLVED_IDENTITIES"
    baseline = seed["baseline_09_75a"]
    same_bound = replay_summary(bound)
    full_summary = replay_summary(fully)
    partial_summary = replay_summary(partial)
    all_identity_summary = replay_summary(identity_bearing)
    rescued_unbound = [
        row
        for row in decision
        if row["binding_class"] == "model_identity_only" and row["identity_replay_attempted"]
    ]

    newly_matched = sum(
        row["commit_matches"] is False and row["identity_matches"] is True for row in bound
    )
    regressed_matches = sum(
        row["commit_matches"] is True and row["identity_matches"] is False for row in bound
    )
    exact_unchanged = sum(
        row["commit_matches"] is True and row["identity_matches"] is True for row in bound
    )
    zero_feature_failures = sum(
        row["feature_difference_count"] == 0 for row in full_failures
    )

    B_resolution = {
        identity_hash: {
            "B_rows": item["B_rows"],
            "files_resolved": item["resolved_present_files"],
            "files_present": item["captured_present_files"],
            "fully_resolved": item["fully_resolved"],
            "unresolved_files": item["unresolved_files"],
        }
        for identity_hash, item in resolution["identities"].items()
        if item["B_rows"]
    }
    selected_resolution = {
        identity_hash: {
            "market_id": item["market_id"],
            "model_version": item["model_version"],
            "active_model_kind": item["active_model_kind"],
            "decision_rows": item["decision_rows"],
            "diagnostic_rows": item["diagnostic_rows"],
            "files_resolved": item["resolved_present_files"],
            "files_present": item["captured_present_files"],
            "fully_resolved": item["fully_resolved"],
            "unresolved_files": item["unresolved_files"],
            "file_resolution": [
                {
                    "path": file_item["path"],
                    "status": file_item["status"],
                    "captured_sha256": file_item["captured_sha256"],
                    "source_blob_oid": (file_item.get("source") or {}).get("blob_oid"),
                }
                for file_item in item["files"]
            ],
        }
        for identity_hash, item in resolution["identities"].items()
        if item["decision_rows"] or item["diagnostic_rows"]
    }

    output_fields = (
        *prior.DECISION_FIELDS,
        "analysis_population",
        "binding_class",
        "runtime_commit",
        "model_version",
        "identity_hash",
        "identity_resolution_class",
        "identity_files_resolved",
        "identity_files_present",
        "identity_unresolved_files",
        "commit_replay_attempted",
        "commit_matches",
        "commit_l1",
        "identity_replay_attempted",
        "identity_matches",
        "identity_l1",
        "identity_max_abs",
        "tree_matches_full_identity",
        "feature_difference_count",
        "first_feature_difference",
        "recorded_active_model_kind",
        "replayed_active_model_kind",
        "runtime_source_fingerprint",
        "runtime_python_version",
        "commit_age_seconds",
        "commit_toronto_local_hour",
        "commit_inside_12_to_18_local",
        "nearest_identity_transition_seconds",
        "commit_age_bucket",
        "identity_transition_bucket",
    )
    ordered = sorted(indexed.values(), key=prior.row_key)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            rendered = dict(row)
            for field in (
                "commit_replay_attempted",
                "commit_matches",
                "identity_replay_attempted",
                "identity_matches",
                "tree_matches_full_identity",
                "commit_inside_12_to_18_local",
            ):
                rendered[field] = bool_text(rendered.get(field))
            for field in ("identity_unresolved_files", "first_feature_difference"):
                value = rendered.get(field)
                rendered[field] = json.dumps(value, sort_keys=True, separators=(",", ":")) if value not in (None, "") else ""
            writer.writerow({field: rendered.get(field, "") for field in output_fields})

    manifest = {
        "schema_version": "identity_binding_manifest_v1",
        "mission": seed["mission"],
        "verdict": verdict,
        "decision_replay": {
            "tolerance": seed["replay"]["l1_tolerance"],
            "rows": len(decision),
            "identity_bearing_rows": len(identity_bearing),
            "same_358_commit_bound_rows": same_bound,
            "fully_resolved_identities": full_summary,
            "partially_resolved_identities": partial_summary,
            "all_identity_bearing_rows": all_identity_summary,
            "baseline_commit_binding": baseline,
            "match_rate_change_on_same_358": same_bound["match_rate"] - baseline["match_rate"],
            "newly_matched_vs_commit_binding": newly_matched,
            "commit_matches_lost_under_identity_binding": regressed_matches,
            "matches_under_both_bindings": exact_unchanged,
            "unbound_rows": {
                "identity_only_rows": len(rescued_unbound),
                "identity_only_matched": sum(row["identity_matches"] is True for row in rescued_unbound),
                "identity_only_failed": sum(row["identity_matches"] is False for row in rescued_unbound),
                "neither_rows": sum(not row["identity_hash"] for row in decision),
            },
            "by_market": grouped_summary(decision, "market_id"),
            "by_window": grouped_summary(decision, "window"),
            "by_resolution_class": grouped_summary(decision, "identity_resolution_class"),
        },
        "whole_B_resolution": {
            "rows": seed["population"]["B_feature_snapshots_with_replay"],
            "identity_bearing_rows": seed["population"]["B_identity_bearing_rows"],
            "commit_bound_baseline_rows": seed["population"]["B_runtime_commit_bound_rows"],
            "fully_resolved_identity_rows": resolution["support"]["B_fully_resolved_rows"],
            "partially_resolved_identity_rows": seed["population"]["B_identity_bearing_rows"] - resolution["support"]["B_fully_resolved_rows"],
            "neither_rows": seed["population"]["B_feature_snapshots_with_replay"] - seed["population"]["B_identity_bearing_rows"],
            "fully_resolved_share": resolution["support"]["B_fully_resolved_rows"] / seed["population"]["B_feature_snapshots_with_replay"],
            "per_identity": B_resolution,
        },
        "resolution": {
            "support": resolution["support"],
            "ref_scope": resolution["ref_scope"],
            "hash_mapping_proof": resolution["hash_mapping_proof"],
            "selected_per_identity": selected_resolution,
        },
        "three_way_drift_test": {
            "residual_failure_class_survives": residual_exists,
            "fully_resolved_decision_testable": fully_resolved_testable,
            "diagnosis_verdict": (
                "UNIDENTIFIABLE_NO_FULLY_RESOLVED_DECISION_IDENTITY"
                if not fully_resolved_testable
                else "RESIDUAL_SURVIVES_FULL_IDENTITY_BINDING"
                if residual_exists
                else "NO_RESIDUAL_AFTER_FULL_IDENTITY_BINDING"
            ),
            "fully_resolved_failed_rows": len(full_failures),
            "fully_resolved_failures_with_zero_feature_differences": zero_feature_failures,
            "fully_resolved_failures_with_nonzero_feature_differences": len(full_failures) - zero_feature_failures,
            "fully_resolved_failures_same_active_kind": sum(
                row["recorded_active_model_kind"] == row["replayed_active_model_kind"]
                for row in full_failures
            ),
            "partially_resolved_failed_rows": len(partial_failures),
            "partially_resolved_failures_with_zero_feature_differences": sum(
                row["feature_difference_count"] == 0 for row in partial_failures
            ),
            "timing_proxy_population": (
                "fully_resolved" if fully_resolved_testable else "partially_resolved_confounded"
            ),
            "by_commit_age": grouped_summary(fully if fully_resolved_testable else partial, "commit_age_bucket"),
            "by_identity_transition_distance": grouped_summary(fully if fully_resolved_testable else partial, "identity_transition_bucket"),
            "by_commit_midday_landing": grouped_summary(fully if fully_resolved_testable else partial, "commit_inside_12_to_18_local"),
            "commit_metadata": commit_info,
            "true_roll_proximity_identifiable": False,
            "true_roll_proximity_limitation": "capture records disk fingerprints and HEAD but no process start, restart event, or loaded-module content hash; identity transitions and commit time are only declared proxies",
            "captured_runtime_python_versions": dict(
                sorted(Counter(str(row["runtime_python_version"] or "missing") for row in identity_bearing).items())
            ),
        },
        "source_switch_diagnostics": replay_summary(diagnostics),
        "runtime_receipts": receipt_files,
        "input_receipts": {
            "records_sha256": sha256_file(records_path),
            "census_sha256": sha256_file(census_path),
            "catalog_sha256": sha256_file(catalog_path),
            "resolution_sha256": sha256_file(resolution_path),
            "run_manifest_sha256": sha256_file(run_manifest_path),
            "prior_csv_sha256": sha256_file(previous_path),
        },
        "artifact": {
            "csv_relative_path": csv_path.relative_to(repo_root).as_posix(),
            "csv_rows": len(ordered),
            "csv_sha256": sha256_file(csv_path),
        },
        "campaign": seed["campaign"],
        "explicitly_not_done": [
            "no alpha allocation, recovery candidate probability, displacement, ceiling, realized outcome, settlement score, market comparison, or C endpoint",
            "no provider or exchange call and no write under data",
            "no model_identity, model, feature, calibration, floor, collection, producer, replay, scoring, serving, release, schedule, branch, or trading change",
            "no merge, rebase, branch deletion, production registration, restart, or state write",
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    checksums_path.write_text(
        f"{sha256_file(csv_path)}  {csv_path.name}\n"
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog")
    catalog.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    catalog.add_argument("--snapshots-root", type=Path, required=True)
    catalog.add_argument("--records", type=Path, required=True)
    catalog.add_argument("--census", type=Path, required=True)
    catalog.add_argument("--output", type=Path, required=True)

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    resolve.add_argument("--catalog", type=Path, required=True)
    resolve.add_argument("--output", type=Path, required=True)

    assemble = sub.add_parser("assemble")
    assemble.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    assemble.add_argument("--catalog", type=Path, required=True)
    assemble.add_argument("--resolution", type=Path, required=True)
    assemble.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)

    replay_parser = sub.add_parser("replay")
    replay_parser.add_argument("--records", type=Path, required=True)
    replay_parser.add_argument("--catalog", type=Path, required=True)
    replay_parser.add_argument("--resolution", type=Path, required=True)
    replay_parser.add_argument("--identity-hash", required=True)
    replay_parser.add_argument("--runtime-root", type=Path, required=True)
    replay_parser.add_argument("--scientific-site", type=Path, required=True)
    replay_parser.add_argument("--output", type=Path, required=True)

    run_all = sub.add_parser("run-all")
    run_all.add_argument("--records", type=Path, required=True)
    run_all.add_argument("--catalog", type=Path, required=True)
    run_all.add_argument("--resolution", type=Path, required=True)
    run_all.add_argument("--python311", type=Path, required=True)
    run_all.add_argument("--scientific-site", type=Path, required=True)
    run_all.add_argument("--receipts-root", type=Path, required=True)
    run_all.add_argument("--run-manifest", type=Path, required=True)

    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    aggregate.add_argument("--records", type=Path, required=True)
    aggregate.add_argument("--census", type=Path, required=True)
    aggregate.add_argument("--catalog", type=Path, required=True)
    aggregate.add_argument("--resolution", type=Path, required=True)
    aggregate.add_argument("--run-manifest", type=Path, required=True)
    aggregate.add_argument("--receipts-root", type=Path, required=True)
    aggregate.add_argument("--csv-output", type=Path)
    aggregate.add_argument("--manifest-output", type=Path)
    aggregate.add_argument("--checksums-output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = getattr(args, "repo_root", DEFAULT_REPO_ROOT).resolve()
    verify_inputs = args.command not in {"replay", "run-all"}
    seed_path = args.seed.resolve()
    seed = load_seed(seed_path, repo_root, verify_inputs=verify_inputs)
    if args.command == "catalog":
        payload = extract_identity_catalog(
            seed,
            repo_root,
            args.snapshots_root.resolve(),
            args.records.resolve(),
            args.census.resolve(),
            args.output.resolve(),
        )
        print(json.dumps(payload["support"], indent=2, sort_keys=True))
        return 0
    if args.command == "resolve":
        payload = resolve_fingerprints(
            seed, repo_root, args.catalog.resolve(), args.output.resolve()
        )
        print(json.dumps(payload["support"], indent=2, sort_keys=True))
        return 0
    if args.command == "assemble":
        payload = assemble_runtime_trees(
            seed,
            repo_root,
            args.catalog.resolve(),
            args.resolution.resolve(),
            args.run_root.resolve(),
        )
        print(json.dumps(payload["assembly"], indent=2, sort_keys=True))
        return 0
    if args.command == "replay":
        payload = replay_identity(
            seed,
            args.records.resolve(),
            args.catalog.resolve(),
            args.resolution.resolve(),
            args.identity_hash,
            args.runtime_root.resolve(),
            args.scientific_site.resolve(),
            args.output.resolve(),
        )
        print(
            json.dumps(
                {
                    "identity_hash": payload["identity_hash"],
                    "resolution_class": payload["resolution_class"],
                    "tree_matches_full_identity": payload["tree_matches_full_identity"],
                    "rows": payload["rows"],
                    "matched_rows": payload["matched_rows"],
                    "failed_rows": payload["failed_rows"],
                    "max_l1": payload["max_l1"],
                    "module_files": payload["module_files"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run-all":
        payload = run_all_identities(
            SCRIPT_PATH,
            seed_path,
            args.records.resolve(),
            args.catalog.resolve(),
            args.resolution.resolve(),
            args.python311.resolve(),
            args.scientific_site.resolve(),
            args.receipts_root.resolve(),
            args.run_manifest.resolve(),
        )
        print(json.dumps({key: payload[key] for key in ("python311_version", "identities", "successful", "failed")}, indent=2, sort_keys=True))
        return 0
    artifacts = seed["artifacts"]
    csv_path = (args.csv_output or repo_root / artifacts["csv_relative_path"]).resolve()
    manifest_path = (
        args.manifest_output or repo_root / artifacts["manifest_relative_path"]
    ).resolve()
    checksums_path = (
        args.checksums_output or repo_root / artifacts["checksums_relative_path"]
    ).resolve()
    payload = aggregate_results(
        seed,
        repo_root,
        args.records.resolve(),
        args.census.resolve(),
        args.catalog.resolve(),
        args.resolution.resolve(),
        args.run_manifest.resolve(),
        args.receipts_root.resolve(),
        csv_path,
        manifest_path,
        checksums_path,
    )
    print(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "decision_replay": payload["decision_replay"],
                "whole_B_resolution": {
                    key: value
                    for key, value in payload["whole_B_resolution"].items()
                    if key != "per_identity"
                },
                "three_way_drift_test": {
                    key: value
                    for key, value in payload["three_way_drift_test"].items()
                    if key not in {"commit_metadata"}
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
