"""Decision-grade tune-only physical ordinal-smoothing replay, generation 2.

This runner accepts no prior H1 result, holdout, fresh-panel manifest, cache,
or resume input.  It cold-replays a fresh W0 baseline, an independent W0
canary, and the five preregistered physical-C anchors under one exact
RESEARCH_UNBOUND execution closure.  ``COMPLETE.json`` is the sole commit
marker for the unique output generation.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityError,
    ExecutionIdentityManifest,
    InvocationSpec,
    assert_serialized_completion_matches,
    capture_execution_identity,
    recapture_and_assert_unchanged,
)
from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import corpus_hash, load_manifest
from weather.reporting.research.current_replay_time_frontier import sha256_stable_file
from weather.reporting.research.ordinal_smoothing_execution_closure import (
    DEFAULT_IMPORT_NAMES,
    RESEARCH_GRAPH_KIND,
    build_replay_closure_spec,
    execution_lineage,
    run_partition_arm,
)
from weather.reporting.research.ordinal_smoothing_physical_refinement import (
    FIXED_BLEND_WEIGHT,
    PHYSICAL_C_SIGMA_ANCHORS,
    native_sigma,
    select_family_sigmas,
)
from weather.reporting.research.ordinal_smoothing_physical_replay import (
    analyze_candidate,
    configure_staged_data_root,
    read_dates,
    validate_staged_daily_inputs,
)
from weather.reporting.research.ordinal_smoothing_sweep import (
    alignment_gate,
    analyze_weight_zero_control,
    folders_for_entries,
    mass_gate,
)
from weather.reporting.research.research_generation import (
    ResearchGeneration,
    ResearchGenerationError,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_physical_replay_gen2")
GENERATION_SCHEMA_VERSION = schema_version(
    "ordinal_smoothing_physical_replay_gen2_generation_commit"
)
CANARY_DATE = "2026-06-21"
EXPECTED_TUNE_DATES = (
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-07",
    "2026-06-08",
    "2026-06-09",
    "2026-06-10",
    "2026-06-11",
    "2026-06-12",
    "2026-06-13",
    "2026-06-14",
    "2026-06-15",
    "2026-06-16",
    "2026-06-17",
    "2026-06-19",
    "2026-06-20",
    "2026-06-21",
)
EXPECTED_TUNE_DATES_FILE_SHA256 = (
    "e546cb4dfe7def0225c8c4ce8165f5dfffdd235903d896aaafdcb2e77eab2041"
)
EXPECTED_TUNE_CORPUS_FILE_SHA256 = (
    "d1492ea5e4ae33eca68c59b9d55cc0aa2aef881acc62cce05f8d9c6d65e14acb"
)
EXPECTED_TUNE_CORPUS_HASH = (
    "ef4cfa84f6c18b433063cd8766f0e0af7d6f2eda0d3febdccb7756f2a016cff6"
)
EXPECTED_TUNE_ENTRY_COUNT = 143
EXPECTED_SOURCE_CORPUS_FILE_SHA256 = (
    "4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5"
)
EXPECTED_SOURCE_CORPUS_HASH = (
    "d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f"
)
PROFILE = "ordinal_smoothing_physical_replay_gen2_strict_v0.1"
RESULT_NAME = "ordinal_smoothing_physical_replay_gen2.json"
REPORT_NAME = "ordinal_smoothing_physical_replay_gen2.md"
MAX_CACHE_BYTES = 4 * 1024**3
MAX_RESULT_BYTES = 256 * 1024**2
MAX_PROJECTED_MINUTES = 240.0
MAX_PROJECTED_BYTES = 25 * 1024**3
MEASURED_FULL_ARM_MINUTES = 25.0
MEASURED_FULL_ARM_BYTES = 2_300_000_000
MEASURED_CANARY_MINUTES = 5.0
MEASURED_CANARY_BYTES = 400_000_000
UNITS = ("C", "F")


class Gen2ReplayError(RuntimeError):
    """The cold tune replay cannot continue under its strict contract."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    )


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _input_receipt(path: Path) -> dict[str, Any]:
    value = path.stat()
    digest = sha256_stable_file(
        path,
        expected_size_bytes=value.st_size,
        expected_mtime_ns=value.st_mtime_ns,
    )
    return {
        "path": str(path),
        "size_bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "sha256": digest,
    }


def validate_paths(args: argparse.Namespace) -> dict[str, Path]:
    paths = {
        name: Path(value).expanduser().resolve(strict=True)
        for name, value in {
            "repo_root": args.repo_root,
            "mirror_data_root": args.mirror_data_root,
            "staged_data_root": args.staged_data_root,
            "snapshots_root": args.snapshots_root,
            "tune_corpus": args.tune_corpus,
            "tune_dates": args.tune_dates_file,
        }.items()
    }
    for name in ("repo_root", "mirror_data_root", "staged_data_root", "snapshots_root"):
        if not paths[name].is_dir():
            raise Gen2ReplayError(f"required directory is missing: {name}: {paths[name]}")
    for name in ("tune_corpus", "tune_dates"):
        if not paths[name].is_file():
            raise Gen2ReplayError(f"required file is missing: {name}: {paths[name]}")
    if Path.cwd().resolve() != paths["repo_root"]:
        raise Gen2ReplayError(
            f"run from bound repo root: {paths['repo_root']}; observed {Path.cwd().resolve()}"
        )
    if not _is_within(paths["snapshots_root"], paths["mirror_data_root"]):
        raise Gen2ReplayError("snapshots_root must remain below mirror_data_root")
    if not _is_within(paths["snapshots_root"], paths["staged_data_root"]):
        raise Gen2ReplayError("snapshots_root must remain below staged_data_root")
    generation = Path(
        os.path.abspath(os.fspath(Path(args.generation_dir).expanduser()))
    )
    resolved_parent = generation.parent.resolve(strict=True)
    if resolved_parent != generation.parent or not generation.parent.is_dir():
        raise Gen2ReplayError("generation parent must already exist")
    if os.path.lexists(generation):
        raise Gen2ReplayError(f"generation already exists; no resume/reuse is allowed: {generation}")
    for root in (paths["mirror_data_root"], paths["staged_data_root"]):
        if _is_within(generation, root):
            raise Gen2ReplayError(f"generation resolves inside read-only data: {generation}")
    paths["generation_dir"] = generation
    projected_minutes = 6 * MEASURED_FULL_ARM_MINUTES + MEASURED_CANARY_MINUTES
    projected_bytes = 6 * MEASURED_FULL_ARM_BYTES + MEASURED_CANARY_BYTES
    if projected_minutes > MAX_PROJECTED_MINUTES or projected_bytes > MAX_PROJECTED_BYTES:
        raise Gen2ReplayError("cold replay exceeds the fixed workstation budget")
    return paths


def _assert_exact_cli(paths: Mapping[str, Path]) -> None:
    fields = (
        ("--repo-root", "repo_root"),
        ("--mirror-data-root", "mirror_data_root"),
        ("--staged-data-root", "staged_data_root"),
        ("--snapshots-root", "snapshots_root"),
        ("--tune-corpus", "tune_corpus"),
        ("--tune-dates-file", "tune_dates"),
        ("--generation-dir", "generation_dir"),
    )
    expected = []
    for flag, key in fields:
        expected.extend((flag, str(paths[key])))
    if sys.argv[1:] != expected:
        raise Gen2ReplayError("cold replay requires the exact ordered canonical CLI")


def _manifest_for_entries(
    manifest: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    output = {key: value for key, value in manifest.items() if key not in {"entries", "skipped"}}
    output["entries"] = [dict(entry) for entry in entries]
    output["skipped"] = []
    output["source_corpus_hash"] = manifest.get("corpus_hash")
    output["corpus_hash"] = corpus_hash(
        output["entries"],
        schema_version=manifest.get("schema_version") or "promotion_corpus_v0.1",
    )
    return output


def load_tune_dates_contract(path: Path) -> tuple[str, ...]:
    receipt = _input_receipt(path)
    if receipt["sha256"] != EXPECTED_TUNE_DATES_FILE_SHA256:
        raise Gen2ReplayError("tune dates file hash differs from preregistration")
    dates = tuple(read_dates(path))
    if dates != EXPECTED_TUNE_DATES:
        raise Gen2ReplayError("tune date tuple differs from preregistration")
    if _input_receipt(path)["sha256"] != receipt["sha256"]:
        raise Gen2ReplayError("tune dates file changed while validating")
    return dates


def load_tune_only_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipt = _input_receipt(path)
    if receipt["sha256"] != EXPECTED_TUNE_CORPUS_FILE_SHA256:
        raise Gen2ReplayError("tune-only corpus file hash differs from preregistration")
    manifest = load_manifest(
        path,
        max_bytes=MAX_RESULT_BYTES,
        allow_research_materialization=True,
    )
    manifest.pop("_path", None)
    materialization = manifest.get("materialization") or {}
    if (
        manifest.get("corpus_hash") != EXPECTED_TUNE_CORPUS_HASH
        or materialization.get("schema_version")
        != "ordinal_smoothing_literal_panel_v0.1"
        or materialization.get("kind") != "tune"
        or tuple(materialization.get("dates") or ()) != EXPECTED_TUNE_DATES
        or int(materialization.get("entry_count") or -1) != EXPECTED_TUNE_ENTRY_COUNT
        or materialization.get("source_manifest_sha256")
        != EXPECTED_SOURCE_CORPUS_FILE_SHA256
        or materialization.get("source_corpus_hash") != EXPECTED_SOURCE_CORPUS_HASH
        or int(materialization.get("excluded_entry_count") or -1) <= 0
        or manifest.get("skipped") != []
    ):
        raise Gen2ReplayError("tune-only corpus materialization contract is invalid")
    entries = [dict(entry) for entry in manifest.get("entries") or []]
    keys = []
    for entry in entries:
        market_id = str(entry.get("market_id") or "")
        target_date = str(entry.get("target_date") or "")
        event_slug = str(entry.get("event_slug") or "")
        relative = str(entry.get("folder_relative_to_snapshots_root") or "")
        if market_id not in REGISTRY or not target_date or not event_slug:
            raise Gen2ReplayError("tune-only corpus has incomplete entry identity")
        if relative != event_slug:
            raise Gen2ReplayError("tune-only corpus folder identity differs from event slug")
        keys.append((market_id, target_date, event_slug))
    if (
        len(entries) != EXPECTED_TUNE_ENTRY_COUNT
        or len(keys) != len(set(keys))
        or tuple(sorted({key[1] for key in keys})) != EXPECTED_TUNE_DATES
        or {key[0] for key in keys} != set(REGISTRY)
    ):
        raise Gen2ReplayError("tune-only corpus is not the exact preregistered panel")
    if _input_receipt(path)["sha256"] != receipt["sha256"]:
        raise Gen2ReplayError("tune-only corpus changed while validating")
    return manifest, entries


def _run_parameters(paths: Mapping[str, Path], tune_dates: Sequence[str]) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "schema_version": SCHEMA_VERSION,
        "model_graph": RESEARCH_GRAPH_KIND,
        "research_only": True,
        "active_or_current_production_claimed": False,
        "repo_root": str(paths["repo_root"]),
        "mirror_data_root": str(paths["mirror_data_root"]),
        "staged_data_root": str(paths["staged_data_root"]),
        "snapshots_root": str(paths["snapshots_root"]),
        "tune_corpus": str(paths["tune_corpus"]),
        "tune_dates_file": str(paths["tune_dates"]),
        "generation_dir": str(paths["generation_dir"]),
        "tune_dates": list(tune_dates),
        "tune_dates_file_sha256": EXPECTED_TUNE_DATES_FILE_SHA256,
        "tune_corpus_file_sha256": EXPECTED_TUNE_CORPUS_FILE_SHA256,
        "tune_corpus_hash": EXPECTED_TUNE_CORPUS_HASH,
        "tune_corpus_entry_count": EXPECTED_TUNE_ENTRY_COUNT,
        "canary_date": CANARY_DATE,
        "physical_c_sigma_anchors": list(PHYSICAL_C_SIGMA_ANCHORS),
        "native_mapping": {"C": "x", "F": "1.8*x"},
        "blend_weight": FIXED_BLEND_WEIGHT,
        "selection_rule": (
            "negative tune mean paired Brier and log-loss deltas vs fresh W0; "
            "rank by Brier, log-loss, then smaller physical-C sigma"
        ),
        "fresh_manifest_accepted": False,
        "holdout_accepted": False,
        "prior_h1_result_accepted": False,
        "prior_cache_or_resume_accepted": False,
        "full_arms": 6,
        "independent_canary_arms": 1,
    }


def _assert_strict_profile(spec: ClosureSpec, entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path_labels = {binding.label for binding in spec.path_bindings}
    tree_labels = {binding.label for binding in spec.tree_bindings}
    required_paths = {
        "partition_corpus",
        "contract:python_executable",
        "contract:sitecustomize",
        "contract:weather_import_shim",
        "contract:tune_dates",
        "release_pointer_absent:1",
        "release_pointer_absent:2",
    }
    required_trees = {"canonical_source", "artifact_graph", "configuration_graph"}
    blockers = []
    if not required_paths <= path_labels:
        blockers.append(f"missing strict paths: {sorted(required_paths - path_labels)}")
    if not required_trees <= tree_labels:
        blockers.append(f"missing strict trees: {sorted(required_trees - tree_labels)}")
    for prefix, expected in (
        ("snapshot_tree:", len(entries)),
        ("captured_replay:", len(entries)),
        ("reconstructed_replay:", len(entries)),
        ("snapshot_tape_jsonl:", len(entries)),
        ("snapshot_tape_long:", len(entries)),
    ):
        observed = sum(label.startswith(prefix) for label in path_labels | tree_labels)
        if observed != expected:
            blockers.append(f"{prefix} closure count {observed} != {expected}")
    market_count = len({str(entry.get("market_id") or "") for entry in entries})
    if sum(label.startswith("wu_daily:") for label in path_labels) != market_count:
        blockers.append("daily WU closure is incomplete")
    if sum(label.startswith("wu_hourly:") for label in tree_labels) != market_count:
        blockers.append("hourly WU closure is incomplete")
    environment = spec.environment
    if not environment.include_packages or "WEATHER_" not in environment.env_prefixes:
        blockers.append("package/WEATHER environment closure is incomplete")
    if not set(DEFAULT_IMPORT_NAMES) <= set(environment.import_names):
        blockers.append("required import provenance is incomplete")
    if spec.invocation.run_parameters.get("profile") != PROFILE:
        blockers.append("strict invocation profile is absent")
    if len(entries) != EXPECTED_TUNE_ENTRY_COUNT:
        blockers.append("tune-only corpus entry count differs from preregistration")
    invocation = spec.invocation.run_parameters
    if (
        tuple(invocation.get("tune_dates") or ()) != EXPECTED_TUNE_DATES
        or invocation.get("tune_dates_file_sha256") != EXPECTED_TUNE_DATES_FILE_SHA256
        or invocation.get("tune_corpus_file_sha256") != EXPECTED_TUNE_CORPUS_FILE_SHA256
        or invocation.get("tune_corpus_hash") != EXPECTED_TUNE_CORPUS_HASH
    ):
        blockers.append("tune-only invocation seals differ from preregistration")
    if blockers:
        raise Gen2ReplayError("strict closure profile failed: " + "; ".join(blockers))
    return {
        "status": "PASS",
        "path_bindings": len(path_labels),
        "tree_bindings": len(tree_labels),
        "corpus_entries": len(entries),
        "market_count": market_count,
        "blockers": [],
    }


def _baseline_gate(arm: Mapping[str, Any], tune_dates: Sequence[str]) -> dict[str, Any]:
    mass = mass_gate(arm.get("distribution_rows") or [])
    alignment = alignment_gate(arm.get("rows") or [], arm.get("rows") or [])
    observed_dates = sorted({str(row.get("target_date") or "") for row in arm.get("rows") or []})
    blockers = (
        list((arm.get("replay") or {}).get("blockers") or [])
        + list(mass.get("blockers") or [])
        + list(alignment.get("blockers") or [])
    )
    if tuple(observed_dates) != tuple(tune_dates):
        blockers.append("fresh W0 rows do not exactly cover tune dates")
    if blockers:
        raise Gen2ReplayError("fresh W0 gate failed: " + "; ".join(blockers))
    return {
        "status": "PASS",
        "mass": mass,
        "alignment": alignment,
        "dates": observed_dates,
        "replay": arm.get("replay") or {},
        "blockers": [],
    }


def _cache_fingerprint(
    *,
    arm_contract: Mapping[str, Any],
    start: ExecutionIdentityManifest,
    corpus_hash: Any,
    design_digest: str,
    w0_sha256: str | None,
) -> str:
    return _digest(
        {
            "schema_version": SCHEMA_VERSION,
            "profile": PROFILE,
            "arm_contract": dict(arm_contract),
            "execution_identity_digest": start.identity_digest,
            "source_corpus_hash": corpus_hash,
            "design_digest": design_digest,
            "fresh_w0_cache_sha256": w0_sha256,
            "prior_cache_reuse": False,
            "model_graph": RESEARCH_GRAPH_KIND,
        }
    )


def _publish_arm(
    *,
    generation: ResearchGeneration,
    cache_name: str,
    arm_contract: Mapping[str, Any],
    folders: Sequence[Path],
    manifest: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    staged_data_root: Path,
    start: ExecutionIdentityManifest,
    closure: ClosureSpec,
    design_digest: str,
    w0_sha256: str | None,
    validator: Callable[[Mapping[str, Any]], tuple[dict[str, Any], Any]],
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    pre_arm = recapture_and_assert_unchanged(start, closure, phase=f"before {cache_name} replay")
    arm = run_partition_arm(
        partition="tune",
        arm_name=str(arm_contract["arm_name"]),
        folders=folders,
        corpus_manifest=manifest,
        staged_data_root=staged_data_root,
        scratch_output_root=generation.generation_dir,
        physical_c_sigma_by_family=arm_contract.get("physical_c_sigma_by_family"),
    )
    post_arm = recapture_and_assert_unchanged(start, closure, phase=f"after {cache_name} replay")
    gate, analysis = validator(arm)
    pre_cache = recapture_and_assert_unchanged(start, closure, phase=f"before {cache_name} cache")
    fingerprint = _cache_fingerprint(
        arm_contract=arm_contract,
        start=start,
        corpus_hash=manifest.get("source_corpus_hash") or manifest.get("corpus_hash"),
        design_digest=design_digest,
        w0_sha256=w0_sha256,
    )
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "cold_replay_arm_cache",
        "fingerprint": fingerprint,
        "arm_contract": dict(arm_contract),
        "entries": len(entries),
        "model_graph": RESEARCH_GRAPH_KIND,
        "active_or_current_production_claimed": False,
        "execution_identity": {
            "start": start.to_dict(),
            "completion": post_arm.to_dict(),
            "identical_full_manifest": True,
        },
        "gate": gate,
        "arm": arm,
    }
    assert_serialized_completion_matches(
        envelope["execution_identity"]["start"],
        envelope["execution_identity"]["completion"],
    )
    receipt = generation.publish_json(cache_name, envelope, compact=True)
    if int(receipt["size_bytes"]) > MAX_CACHE_BYTES:
        raise Gen2ReplayError(f"cache exceeds fixed cap: {cache_name}")
    post_cache = recapture_and_assert_unchanged(start, closure, phase=f"after {cache_name} cache")
    record = {
        **receipt,
        "fingerprint": fingerprint,
        "arm_contract": dict(arm_contract),
        "gate": gate,
        "identity_gates": {
            "pre_arm_digest": pre_arm.identity_digest,
            "post_arm_digest": post_arm.identity_digest,
            "pre_cache": pre_cache.to_dict(),
            "post_cache": post_cache.to_dict(),
            "identical_full_manifest": True,
        },
    }
    assert_serialized_completion_matches(
        record["identity_gates"]["pre_cache"],
        record["identity_gates"]["post_cache"],
    )
    return arm, record, analysis


def _render_report(payload: Mapping[str, Any]) -> str:
    rows = []
    selected = payload.get("selected_physical_c_sigmas") or {}
    for unit in UNITS:
        for summary in (payload.get("summaries") or {}).get(unit) or []:
            brier_ci = summary.get("brier_cluster_bootstrap_95ci") or {}
            log_ci = summary.get("logloss_cluster_bootstrap_95ci") or {}
            rows.append(
                "| {unit} | {physical:.2f} | {native:.2f} | {dates} | {brier:+.8f} "
                "[{blow:+.8f}, {bhigh:+.8f}] | {log:+.8f} [{llow:+.8f}, {lhigh:+.8f}] "
                "| {market:+.8f} | {frozen} |".format(
                    unit=unit,
                    physical=float(summary["physical_c_sigma"]),
                    native=float(summary["native_sigma"]),
                    dates=summary["fleet_dates"],
                    brier=float(summary["mean_brier_delta_vs_w0"]),
                    blow=float(brier_ci["low"]),
                    bhigh=float(brier_ci["high"]),
                    log=float(summary["mean_logloss_delta_vs_w0"]),
                    llow=float(log_ci["low"]),
                    lhigh=float(log_ci["high"]),
                    market=float(summary["mean_candidate_brier_delta_vs_market"]),
                    frozen="yes" if selected.get(unit) == summary["physical_c_sigma"] else "",
                )
            )
    lineage = payload.get("lineage") or {}
    return "\n".join(
        [
            "# H1 Physical-Bandwidth Cold Tune Replay — Generation 2",
            "",
            f"Status: **{payload.get('status')}**",
            "",
            "This is tune-only RESEARCH_UNBOUND evidence. It used a fresh W0, an independent "
            "W0 canary, and five cold candidate replays. No old H1 result, old cache, holdout, "
            "fresh panel, active release, serving pointer, or promotion path was an input.",
            "",
            "| Unit | Physical C sigma | Native sigma | Dates | Brier vs fresh W0 (95% CI) "
            "| Log-loss vs fresh W0 (95% CI) | Brier vs market | Frozen |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            *rows,
            "",
            f"Execution identity: `{lineage.get('execution_identity_digest')}`.",
            f"Source/artifact/config digests: `{lineage.get('source_digest')}` / "
            f"`{lineage.get('artifact_digest')}` / `{lineage.get('configuration_digest')}`.",
            "",
            "The frozen family pair may be used only by the separately preregistered one-shot "
            "strict confirmation runner. Tune scores do not authorize serving or promotion.",
            "`COMPLETE.json` is the sole final commit marker for this multi-leaf generation.",
            "",
        ]
    )


def run_experiment(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = validate_paths(args)
    _assert_exact_cli(paths)
    tune_dates = load_tune_dates_contract(paths["tune_dates"])
    tune_manifest, entries = load_tune_only_manifest(paths["tune_corpus"])
    folders = folders_for_entries(entries, paths["snapshots_root"])
    validate_staged_daily_inputs(entries, paths["staged_data_root"])
    configure_staged_data_root(paths["staged_data_root"])
    parameters = _run_parameters(paths, tune_dates)
    design_digest = _digest(parameters)
    imports = tuple(
        sorted(
            set(DEFAULT_IMPORT_NAMES)
            | {
                "weather.reporting.research.ordinal_smoothing_physical_replay_gen2",
                "weather.reporting.research.research_generation",
                "weather.release_serving",
            }
        )
    )
    closure = build_replay_closure_spec(
        name=PROFILE,
        repo_root=paths["repo_root"],
        staged_data_root=paths["staged_data_root"],
        snapshots_root=paths["snapshots_root"],
        corpus_path=paths["tune_corpus"],
        entries=entries,
        invocation=InvocationSpec.current(run_parameters=parameters),
        required_contract_files=(
            ("python_executable", Path(sys.executable)),
            ("sitecustomize", paths["repo_root"] / "sitecustomize.py"),
            ("weather_import_shim", paths["repo_root"] / "weather" / "__init__.py"),
            ("tune_dates", paths["tune_dates"]),
        ),
        environment=EnvironmentSpec(import_names=imports, include_packages=True),
    )
    profile_gate = _assert_strict_profile(closure, entries)
    terminal_seals = {
        "tune_corpus": _input_receipt(paths["tune_corpus"]),
        "tune_dates": _input_receipt(paths["tune_dates"]),
        "sitecustomize": _input_receipt(paths["repo_root"] / "sitecustomize.py"),
        "weather_import_shim": _input_receipt(
            paths["repo_root"] / "weather" / "__init__.py"
        ),
        "design": {"profile": PROFILE, "sha256": design_digest},
    }
    started = time.perf_counter()
    generation_builder = ResearchGeneration(
        generation_dir=paths["generation_dir"],
        read_only_roots=(paths["mirror_data_root"], paths["staged_data_root"]),
        commit_schema_version=GENERATION_SCHEMA_VERSION,
    )
    with generation_builder as generation:
        start = capture_execution_identity(closure)
        reloaded_dates = load_tune_dates_contract(paths["tune_dates"])
        reloaded_manifest, reloaded_entries = load_tune_only_manifest(
            paths["tune_corpus"]
        )
        reloaded_folders = folders_for_entries(reloaded_entries, paths["snapshots_root"])
        if (
            tuple(reloaded_dates) != tuple(tune_dates)
            or _canonical_json(reloaded_manifest) != _canonical_json(tune_manifest)
            or [str(path) for path in reloaded_folders] != [str(path) for path in folders]
        ):
            raise Gen2ReplayError("tune contracts changed across start closure capture")
        recapture_and_assert_unchanged(start, closure, phase="after tune contract reload")

        cache_records = []
        w0_contract = {
            "arm_name": "fresh-w0-full-tune",
            "kind": "fresh_w0",
            "physical_c_sigma_by_family": None,
            "blend_weight": 0.0,
            "partition": "tune",
        }

        def validate_baseline(arm):
            gate = _baseline_gate(arm, tune_dates)
            return gate, gate

        w0, w0_record, baseline_gate = _publish_arm(
            generation=generation,
            cache_name="cache/tune-fresh-w0.json",
            arm_contract=w0_contract,
            folders=folders,
            manifest=tune_manifest,
            entries=entries,
            staged_data_root=paths["staged_data_root"],
            start=start,
            closure=closure,
            design_digest=design_digest,
            w0_sha256=None,
            validator=validate_baseline,
        )
        cache_records.append(w0_record)
        fresh_w0_sha = str(w0_record["sha256"])

        canary_entries = [entry for entry in entries if str(entry.get("target_date")) == CANARY_DATE]
        canary_markets = {str(entry.get("market_id") or "") for entry in canary_entries}
        if len(canary_entries) != len(REGISTRY) or canary_markets != set(REGISTRY):
            raise Gen2ReplayError("independent canary must be one exact 12-market fleet date")
        canary_manifest = _manifest_for_entries(tune_manifest, canary_entries)
        canary_folders = folders_for_entries(canary_entries, paths["snapshots_root"])

        def validate_canary(arm):
            gate = analyze_weight_zero_control(w0, arm)
            if gate.get("blockers"):
                raise Gen2ReplayError("independent W0 canary failed: " + "; ".join(gate["blockers"]))
            return {"status": "PASS", **dict(gate.get("evidence") or {}), "blockers": []}, {}

        canary_contract = {
            "arm_name": "fresh-w0-independent-canary",
            "kind": "independent_w0_canary",
            "date": CANARY_DATE,
            "physical_c_sigma_by_family": None,
            "blend_weight": 0.0,
            "partition": "tune-canary",
        }
        canary, canary_record, _ = _publish_arm(
            generation=generation,
            cache_name="cache/tune-fresh-w0-canary.json",
            arm_contract=canary_contract,
            folders=canary_folders,
            manifest=canary_manifest,
            entries=canary_entries,
            staged_data_root=paths["staged_data_root"],
            start=start,
            closure=closure,
            design_digest=design_digest,
            w0_sha256=fresh_w0_sha,
            validator=validate_canary,
        )
        cache_records.append(canary_record)
        canary = None
        gc.collect()

        summaries = {unit: [] for unit in UNITS}
        arm_gates = {}
        for index, anchor in enumerate(PHYSICAL_C_SIGMA_ANCHORS, start=1):
            print(
                f"gen2 physical replay {index}/{len(PHYSICAL_C_SIGMA_ANCHORS)}: "
                f"physical_C={anchor:.2f}, native_C={anchor:.2f}, native_F={native_sigma(anchor, 'F'):.2f}",
                flush=True,
            )
            contract = {
                "arm_name": f"physical-c-{anchor:.2f}",
                "kind": "physical_candidate",
                "physical_c_sigma_by_family": {"C": anchor, "F": anchor},
                "native_sigma_by_family": {
                    unit: native_sigma(anchor, unit) for unit in UNITS
                },
                "blend_weight": FIXED_BLEND_WEIGHT,
                "partition": "tune",
            }

            def validate_candidate(arm, *, value=anchor):
                gate, family = analyze_candidate(w0, arm, value)
                return gate, family

            arm, record, family_summaries = _publish_arm(
                generation=generation,
                cache_name=(
                    "cache/tune-physical-c-"
                    + f"{anchor:.2f}".replace(".", "p")
                    + ".json"
                ),
                arm_contract=contract,
                folders=folders,
                manifest=tune_manifest,
                entries=entries,
                staged_data_root=paths["staged_data_root"],
                start=start,
                closure=closure,
                design_digest=design_digest,
                w0_sha256=fresh_w0_sha,
                validator=validate_candidate,
            )
            arm_gates[str(anchor)] = dict(record["gate"])
            arm_gates[str(anchor)]["cache_sha256"] = record["sha256"]
            for unit in UNITS:
                summaries[unit].append(family_summaries[unit])
            cache_records.append(record)
            arm = None
            gc.collect()

        selected, selection = select_family_sigmas(summaries)
        all_families_selected = set(selected) == set(UNITS)
        completion = recapture_and_assert_unchanged(
            start, closure, phase="after all cold tune arms"
        )
        assert_serialized_completion_matches(start.to_dict(), completion.to_dict())
        lineage = execution_lineage(start)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETE",
            "disposition": (
                "FROZEN_FOR_ONE_SHOT_STRICT_CONFIRMATION"
                if all_families_selected
                else "NO_ELIGIBLE_FAMILY_PAIR"
            ),
            "research_only": True,
            "promotion_authorized": False,
            "serving_changed": False,
            "holdout_opened": False,
            "fresh_panel_opened": False,
            "prior_h1_result_or_cache_used": False,
            "model_graph": RESEARCH_GRAPH_KIND,
            "active_or_current_production_claimed": False,
            "profile_gate": profile_gate,
            "experiment": {
                **parameters,
                "design_digest": design_digest,
                "runtime_seconds": time.perf_counter() - started,
                "tune_market_days": len(entries),
            },
            "terminal_seals": terminal_seals,
            "lineage": lineage,
            "execution_identity": {
                "start": start.to_dict(),
                "completion": completion.to_dict(),
                "identical_full_manifest": True,
            },
            "baseline_gate": baseline_gate,
            "canary_gate": {
                **dict(canary_record["gate"]),
                "cache_sha256": canary_record["sha256"],
            },
            "arm_gates": arm_gates,
            "summaries": summaries,
            "selection": selection,
            "selected_physical_c_sigmas": selected,
            "frozen_candidate": {
                "status": "FROZEN" if all_families_selected else "NOT_FROZEN",
                "physical_c_sigma_by_family": selected,
                "native_sigma_by_family": {
                    unit: native_sigma(selected[unit], unit)
                    for unit in selected
                },
                "blend_weight": FIXED_BLEND_WEIGHT,
                "selection_uses_tune_only": True,
                "confirmation_runs_completed": 0,
                "one_shot_confirmation_authorized": all_families_selected,
                "promotion_authorized": False,
            },
            "cache_records": cache_records,
            "generation_contract": {
                "complete_marker": "COMPLETE.json",
                "multi_leaf_atomic_transaction_claimed": False,
                "prior_generation_reuse": False,
            },
            "technical_blockers": [],
        }
        result_receipt = generation.publish_json(RESULT_NAME, payload)
        if int(result_receipt["size_bytes"]) > MAX_RESULT_BYTES:
            raise Gen2ReplayError("gen2 result exceeds fixed compact cap")
        generation.publish_text(REPORT_NAME, _render_report(payload))
        commit = generation.commit(
            start=start,
            expected_completion=completion,
            terminal_recapture=lambda: recapture_and_assert_unchanged(
                start,
                closure,
                phase=(
                    "gen2 after final output inventory "
                    "immediately before COMPLETE.json"
                ),
            ),
            terminal_seals=terminal_seals,
            extra={
                "profile": PROFILE,
                "model_graph": RESEARCH_GRAPH_KIND,
                "result": RESULT_NAME,
                "report": REPORT_NAME,
                "selected_physical_c_sigmas": selected,
                "one_shot_confirmation_authorized": all_families_selected,
            },
        )
    return payload, commit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--mirror-data-root", required=True)
    parser.add_argument("--staged-data-root", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--tune-corpus", required=True)
    parser.add_argument("--tune-dates-file", required=True)
    parser.add_argument("--generation-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        payload, commit = run_experiment(build_parser().parse_args(argv))
    except (Gen2ReplayError, ExecutionIdentityError, ResearchGenerationError, ValueError) as exc:
        print(f"gen2 physical tune replay blocked: {exc}", file=sys.stderr)
        return 2
    print(
        "gen2 physical tune replay committed: "
        f"selection={payload.get('selected_physical_c_sigmas')} "
        f"identity={(commit.get('execution_identity') or {}).get('start_digest')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
