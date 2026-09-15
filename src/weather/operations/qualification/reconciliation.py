"""Inspect an ambiguous split commit without turning it into adoption proof.

No reset, commit, push or retry exists here. Historical source/configuration
bytes prove the committed tree; ordinary later generated refreshes are allowed
only for current read-only health inspection, never for a new merge boundary.
"""

from __future__ import annotations

from pathlib import Path

from . import merge_tree, source
from .records import digest, require


def inspect_tree(checked, git, *, prepared_baseline):
    m, reviewed, local = checked["manifest"], checked["review"], checked["local"]
    production = Path(m["repo_root"])
    baseline, commit = m["baseline"]["master"], m["expected_tip"]
    prepared_baseline = digest(prepared_baseline, git=True)
    qref = checked["host_plan"]["configuration"]
    q = merge_tree.configuration(local.get(qref))
    expected = merge_tree.preview(git, production, source_commit=commit, source_tree=reviewed["source"]["tree"],
                                 baseline=baseline, config_graph=local, configuration_ref=qref)
    prepared = merge_tree.tree_entries(git, production, baseline)
    for item in q["generated"]:
        prepared[item["path"]] = {"mode": "100644", "oid": item["git_blob"]}
    require(source.git_output(git, production, "rev-parse", prepared_baseline + "^{tree}").decode().strip() ==
            merge_tree.tree_id(prepared), "prepared baseline is not the complete original B plus Q")
    if prepared_baseline != baseline:
        require(source.git_output(git, production, "rev-list", "--parents", "-n", "1", prepared_baseline).decode().split() ==
                [prepared_baseline, baseline], "prepared baseline has unreviewed parents")
    head = source.git_output(git, production, "rev-parse", "HEAD").decode().strip()
    master = source.git_output(git, production, "rev-parse", "master").decode().strip()
    origin = source.git_output(git, production, "rev-parse", "origin/master").decode().strip()
    branch = source.git_output(git, production, "symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
    require(branch == "master" and head == master, "reconciliation requires exact checked-out master")
    merge_head = Path(source.git_output(git, production, "rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD").decode().strip())
    if head == prepared_baseline:
        require(origin == baseline, "uncommitted attempt has unexpected published state")
        if merge_head.exists():
            require(merge_head.read_bytes() == (commit + "\n").encode(), "pending merge belongs to another source")
        disposition = "UNCOMMITTED_REQUIRES_REVIEW"
    else:
        require(not merge_head.exists(), "committed integration still has MERGE_HEAD")
        merge_tree.committed_tree(git, production, expected_tree=expected["tree"],
                                 first_parent=prepared_baseline, source_commit=commit)
        require(origin in {baseline, head}, "published ref is neither original B nor exact M")
        merge_tree.working_bytes(git, production, source_root=production, source_commit=commit,
            source_inventory=checked["graph"].get(reviewed["source_inventory"]), config_graph=local,
            configuration_ref=qref, allow_generated_refresh=True)
        changed = source.git_output(git, production, "diff", "--cached", "--name-only", "--no-ext-diff", "--no-textconv", "HEAD", "--").decode().splitlines()
        require(set(changed) <= set(merge_tree.GENERATED), "unreviewed staged production changes remain")
        disposition = "PUBLISHED_CURRENT" if origin == head else "MERGED_UNPUBLISHED_REQUIRES_REVIEW"
    return {"disposition": disposition, "production_head": head, "origin_master": origin,
        "prepared_baseline": prepared_baseline, "effective_tree": expected["tree"],
        "pending_merge_head": merge_head.exists(), "historical_proof_upgraded": False, "downstream_authorized": False}


def execution_health(production):
    """The same current auxiliary status/lock/identity conditions as v1 recovery."""
    from .inputs import _input_object, open_current
    from weather.operations.execution_tape_supervisor import read_status, execution_tape_health
    status = read_status()
    health = execution_tape_health(status, stale_after_seconds=180)
    with open_current(production, "data/snapshots/.execution_tape_status.json.writer.lock", maximum=2 * 1024**2) as (handle, _):
        raw = handle.read(2 * 1024**2 + 1)
    require(len(raw) <= 2 * 1024**2, "auxiliary writer lock exceeds metadata bound")
    lock = _input_object(raw)
    managed = status.get("managed_process", {})
    require(health.get("state") in {"RUNNING", "DEGRADED"} and health.get("pid_alive") is True and
        health.get("runtime_identity_matches_current") is True and health.get("evidence_integrity") == "PASS" and
        status.get("state") == "CONNECTED" and status.get("market") == "all" and status.get("runner") == "managed_execution_tape" and
        managed.get("verified_at_capture") is True and type(status.get("pid")) is int and status["pid"] > 0 and
        status["pid"] == managed.get("pid") == lock.get("pid") == lock.get("managed_process", {}).get("pid") and
        managed.get("creation_time_token") == lock.get("managed_process", {}).get("creation_time_token"),
        "current canonical auxiliary producer status/lock/source proof is unhealthy")
    return {"status": status, "health": health, "writer_lock": lock}


def retain_health(output, payload):
    """Retain complete finite domain telemetry separately from strict metadata.

    Domain ages may be floats. Control records stay integer-only and bind all
    original telemetry bytes through this data reference rather than rounding it.
    """
    import hashlib
    import json
    import os
    from .records import checked_root
    output = checked_root(output)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    require(0 < len(raw) <= 2 * 1024**2, "terminal health telemetry exceeds metadata bound")
    with (output / "health.json").open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": "health.json", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}