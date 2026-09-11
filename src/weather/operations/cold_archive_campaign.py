"""Resumable, serial orchestration of the approved verified archive campaign."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from weather import execution_host
from weather import cold_archive_locations as locations
from weather.operations import production_cold_archive_stage as archive
from weather.operations import workstation_cold_archive_stage as identity
from weather.operations import cold_archive_campaign_io as io
from weather.operations import cold_archive_campaign_state as state
from weather.operations import cold_archive_campaign_steps as steps
from weather.paths import repo_path
from weather.schema_registry import schema_version


utc = state.utc
active_window = state.active_window


def validate(config, source):
    required = {
        "schema_version", "campaign_id", "archive_prefix", "production_root",
        "production_source_tip", "workstation_root", "workstation_source_tip",
        "execution_host_id", "backup_execution_host_id", "approved_by", "approved_at_utc",
        "expires_at_utc", "windows", "plan", "owner_approval", "proposal", "selection",
        "completed_reclaims", "progress_path", "target_bytes", "remote_host", "remote_user",
        "private_key", "known_hosts", "known_hosts_sha256", "ssh_executable", "scp_executable",
        "workstation_python", "rclone_executable", "crypt_config", "crypt_secret",
        "crypt_remote_name", "ciphertext_root", "drive_config", "drive_secret",
        "drive_remote_name", "drive_root_folder_id", "key_custody"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("campaign configuration fields differ")
    if config["schema_version"] != schema_version("cold_archive_campaign_config"):
        raise ValueError("campaign configuration version differs")
    for name in ("campaign_id", "archive_prefix"):
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", config[name]) is None:
            raise ValueError("invalid campaign identity")
    for name in ("production_source_tip", "workstation_source_tip"):
        if re.fullmatch(r"[0-9a-f]{40}", config[name]) is None:
            raise ValueError("full source tip required")
    if os.name != "nt" or os.environ.get("WEATHER_ARCHIVE_CAMPAIGN_WRAPPER") != "1":
        raise ValueError("native campaign launcher required")
    if execution_host.current_execution_host_id() != config["execution_host_id"]:
        raise ValueError("campaign production host differs")
    current = identity._capture_tool_identity(source)
    if current["git_commit"] != config["production_source_tip"] or current["git_dirty"] is not False:
        raise ValueError("campaign source must be exact and clean")
    root = archive._safe_path(Path(config["production_root"]), directory=True)
    if Path(config["progress_path"]).parent != root / "data/cold_archive/catalog/reclaims" / config["owner_approval"]["sha256"]:
        raise ValueError("campaign progress pointer differs from owner approval")
    if type(config["target_bytes"]) is not int or not 0 < config["target_bytes"] <= 1024**4:
        raise ValueError("campaign target bound")
    if not isinstance(config["windows"], list) or not 1 <= len(config["windows"]) <= 8:
        raise ValueError("campaign execution-window bound")
    previous = utc(config["approved_at_utc"])
    for window in config["windows"]:
        if set(window) != {"start", "end", "owner_exception"}:
            raise ValueError("campaign window fields differ")
        start, end = utc(window["start"]), utc(window["end"])
        if start < previous or not start < end <= utc(config["expires_at_utc"]):
            raise ValueError("campaign windows overlap or exceed authority")
        previous = end
    if (utc(config["expires_at_utc"]) - utc(config["approved_at_utc"])).total_seconds() > 72 * 3600:
        raise ValueError("campaign approval is overlong")
    from weather.operations import production_cold_archive_copy as outbound
    import ipaddress
    address = ipaddress.IPv4Address(config["remote_host"])
    if not address.is_private or address.is_loopback or address.is_multicast or address.is_unspecified:
        raise ValueError("campaign target must be the reviewed private workstation")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", config["remote_user"]) is None:
        raise ValueError("literal workstation principal required")
    for name in ("workstation_root", "workstation_python", "rclone_executable", "crypt_config",
                 "crypt_secret", "ciphertext_root", "drive_config", "drive_secret"):
        outbound.remote_path(config[name])
    outbound.remote_path(config["key_custody"]["path"])
    if not isinstance(config["completed_reclaims"], list) or len(config["completed_reclaims"]) > 512:
        raise ValueError("baseline recovery evidence bound")
    documents = {name: io.load_spec(config[name]) for name in ("plan", "owner_approval", "proposal", "selection")}
    plan, selection = documents["plan"], documents["selection"]
    archive._check_seal(plan, "plan_hash")
    if (plan["selection_sha256"] != config["selection"]["sha256"]
            or archive._rows([row for chunk in plan["chunks"] for row in chunk["files"]])
            != archive._rows(selection["files"])):
        raise ValueError("campaign must retain the exact approved plan and full selection")
    if documents["owner_approval"]["conditional_reserve"]["use_only_if_qualified_primary_reclaim_is_below_bytes"] != config["target_bytes"]:
        raise ValueError("campaign target differs from owner instruction")
    done = []
    for item in config["completed_reclaims"]:
        proof = io.load_spec(item)
        archive._check_seal(proof, "receipt_hash")
        if proof["status"] != "PASS" or proof["owner_approval_sha256"] != config["owner_approval"]["sha256"]:
            raise ValueError("baseline original reclaim is not qualified")
        done.extend(row["path"] for row in proof["files"])
    if len(done) != len(set(done)):
        raise ValueError("baseline reclaimed sources overlap")
    ready, isolated = state.remaining_chunks(plan, done)
    return root, ready, isolated


def progress(config):
    value, _ = locations.read_record(config["progress_path"])
    if value["status"] != "READY" or value["owner_approval_sha256"] != config["owner_approval"]["sha256"]:
        raise state.CampaignPaused("authoritative reclaim progress requires reconciliation")
    return value


def run(config_path, config_sha256, *, max_batches=None):
    config = archive._load(config_path, config_sha256)[0]
    source = repo_path()
    root, ready, isolated = validate(config, source)
    control_parent = root / "scratch" / "ac-control"
    control_parent.mkdir(exist_ok=True)
    control = control_parent / config["campaign_id"]
    control.mkdir(exist_ok=True)
    transport = io.Transport(config, source)
    active_window(config, datetime.now(timezone.utc))
    transport.rpc("setup", {"campaign_id": config["campaign_id"]})
    summaries = []
    for chunk in ready:
        aid = config["archive_prefix"] + chunk["chunk_id"].removeprefix("chunk-")
        adapter = steps.Steps(config, aid, chunk, transport)
        journal = state.BatchJournal(control / (aid + "-journal"), {
            "config_sha256": config_sha256, "archive_id": aid, "chunk_id": chunk["chunk_id"],
            "plan_sha256": config["plan"]["sha256"]})
        # Always finish recovery backup for a started batch, even when its reclaim
        # reached the target. New batches stop at the authoritative original counter.
        started = any(journal.root.glob("*.claim.json"))
        current = progress(config)
        if current["reclaimed_allocated_bytes"] >= config["target_bytes"] and not started:
            break
        phases = journal.run(adapter, stop_requested=lambda: (control / "STOP").exists())
        reclaim = io.load_spec(phases["reclaim"]["evidence"]["documents"]["reclaim"])
        summary = {"archive_id": aid, "logical_bytes": chunk["logical_bytes"], "phases": phases,
                   "reclaimed_allocated_bytes": reclaim["reclaimed_allocated_bytes"]}
        summaries.append(summary)
        if len(summaries) >= state.QUALIFICATION_BATCHES:
            state.qualification(summaries)
        current = progress(config)
        print(json.dumps({
            "status": "BATCH_VERIFIED", "archive_id": aid,
            "original_reclaimed_bytes": current["reclaimed_allocated_bytes"],
            "target_bytes": config["target_bytes"],
            "qualification_batches": min(len(summaries), state.QUALIFICATION_BATCHES),
            "batch_seconds": sum(value["elapsed_seconds"] for value in phases.values()),
            "remaining_estimate": state.remaining_estimate(
                summaries, max(0, config["target_bytes"] - current["reclaimed_allocated_bytes"]))}), flush=True)
        if max_batches is not None and len(summaries) >= max_batches:
            break
    current = progress(config)
    result = {"status": "TARGET_REACHED" if current["reclaimed_allocated_bytes"] >= config["target_bytes"]
              else "PAUSED", "original_reclaimed_bytes": current["reclaimed_allocated_bytes"],
              "target_bytes": config["target_bytes"], "completed_batches": len(summaries),
              "isolated_chunks": isolated, "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    print(json.dumps(result), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--log-file")
    args = parser.parse_args(argv)
    if args.max_batches is not None and not 1 <= args.max_batches <= 10000:
        parser.error("max batches must be positive and bounded")
    if args.log_file:
        config = archive._load(args.config, args.config_sha256)[0]
        path = Path(args.log_file)
        expected = Path(config["production_root"]) / "scratch/ac-control" / config["campaign_id"]
        if path.parent != expected or not path.name.endswith(".log"):
            raise ValueError("campaign log path differs")
        expected.mkdir(parents=True, exist_ok=True)
        archive._safe_path(expected, directory=True)
        with path.open("x", encoding="utf-8", buffering=1) as output:
            nested = ["--config", args.config, "--config-sha256", args.config_sha256]
            if args.max_batches is not None:
                nested.extend(["--max-batches", str(args.max_batches)])
            with redirect_stdout(output), redirect_stderr(output):
                return main(nested)
    try:
        run(args.config, args.config_sha256, max_batches=args.max_batches)
    except state.CampaignPaused as exc:
        print(json.dumps({"status": "PAUSED_RETAIN_AND_INSPECT", "reason": str(exc)}), flush=True)
        return 2
    except Exception as exc:
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__,
                          "reason": str(exc)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
