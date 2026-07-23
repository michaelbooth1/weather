"""Hardened, sealed runner for the 2026-07 workstation source ablation.

This runner deliberately has no partial-family, market, folder, reconstructed,
serving-release, or overwrite mode.  It consumes the terminal pre-run seals,
recomputes exact runtime support, binds the full execution closure, and exposes
one generation only after a final exclusive COMPLETE marker records every
output hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import weather.paths as weather_paths
from weather.backtesting.replay_ablation import (
    build_payload,
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
    render_report,
    run_ablation,
    summarize,
    summarize_slice_effects,
)
from weather.backtesting.source_ablation_contract import ALL_VARIANTS, VARIANT_MEMBERS
from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    InvocationSpec,
    PathBinding,
    TreeBinding,
    assert_serialized_completion_matches,
    capture_execution_identity,
    recapture_and_assert_unchanged,
)
from weather.market.market_registry import REGISTRY
from weather.model.toronto_model import TorontoHighTempModel
from weather.release_serving import STATUS_RESEARCH_UNBOUND, VerifiedServingBundle
from weather.reporting.promotion.promotion_corpus import folders_from_manifest
from weather.reporting.research.research_generation import ResearchGeneration
from weather.reporting.research.source_ablation_runtime_correction import (
    RETRY_GENERATION_LEAF,
    validate_runtime_support_correction,
)
from weather.schema_registry import schema_version


TERMINAL_PREREGISTRATION_SHA256 = (
    "a98a1be7383b7bac200e0baea6f680ad5505a5bfc1054b2bc14fc192973e176f"
)
TERMINAL_SUPPORT_SHA256 = (
    "55af741c35a6b4fcaa1df89cfcdcb479bb84603f91dfefae4b42a53e49470cf7"
)
TERMINAL_FEASIBILITY_SHA256 = (
    "09b8d7c20930d9a37dd0310c41071c4344d274bae11bf7d688a486f38af4d148"
)
TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256 = (
    "105429a593c149dc9d59518e1623368c6c34ba7a125042f5f4f61ee770956fad"
)
TERMINAL_CORPUS_FILE_SHA256 = (
    "4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5"
)
TERMINAL_CORPUS_HASH = (
    "d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f"
)
TERMINAL_MARKET_IDS = tuple(sorted(REGISTRY))
GENERATION_SCHEMA_VERSION = schema_version("source_ablation_generation_commit")
MAX_SEAL_BYTES = 64 * 1024 * 1024


class HardenedSourceAblationError(RuntimeError):
    """The sealed source run cannot continue without weakening its contract."""


def _stable_bytes(path: str | Path, *, max_bytes: int = MAX_SEAL_BYTES) -> tuple[Path, bytes, str]:
    resolved = Path(path).expanduser().resolve(strict=True)
    before = resolved.stat()
    if not resolved.is_file() or before.st_size > int(max_bytes):
        raise HardenedSourceAblationError(
            f"sealed input is missing, non-file, or too large: {resolved}"
        )
    with resolved.open("rb") as handle:
        handle_before = os.fstat(handle.fileno())
        raw = handle.read()
        handle_after = os.fstat(handle.fileno())
    after = resolved.stat()
    identity = lambda value: (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_nlink),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )
    if not (
        identity(before)
        == identity(handle_before)
        == identity(handle_after)
        == identity(after)
    ):
        raise HardenedSourceAblationError(f"sealed input changed while reading: {resolved}")
    return resolved, raw, hashlib.sha256(raw).hexdigest()


def _stable_json(path: str | Path) -> tuple[Path, dict[str, Any], str]:
    resolved, raw, digest = _stable_bytes(path)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HardenedSourceAblationError(
            f"sealed JSON is invalid: {resolved}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise HardenedSourceAblationError(f"sealed JSON root is not an object: {resolved}")
    return resolved, payload, digest


def _receipt(path: Path, digest: str) -> dict[str, Any]:
    stat_result = path.stat()
    return {
        "path": str(path),
        "sha256": digest,
        "size_bytes": int(stat_result.st_size),
        "mtime_ns": int(stat_result.st_mtime_ns),
    }


def _read_dates(path: str | Path) -> tuple[Path, tuple[str, ...], str]:
    resolved, raw, digest = _stable_bytes(path, max_bytes=1024 * 1024)
    values = tuple(
        value
        for value in (
            line.split("#", 1)[0].strip()
            for line in raw.decode("utf-8").splitlines()
        )
        if value
    )
    if not values or values != tuple(sorted(set(values))):
        raise HardenedSourceAblationError(
            f"date seal must be nonempty, sorted, and unique: {resolved}"
        )
    return resolved, values, digest


def load_terminal_contracts(args) -> dict[str, Any]:
    corpus_path, corpus_raw, corpus_file_sha256 = _stable_bytes(args.corpus)
    prereg_path, preregistration, preregistration_sha256 = _stable_json(
        args.preregistration
    )
    support_path, support, support_sha256 = _stable_json(args.support_seal)
    feasibility_path, feasibility, feasibility_sha256 = _stable_json(
        args.feasibility_seal
    )
    correction_path, correction, correction_sha256 = _stable_json(
        args.runtime_support_correction_seal
    )
    tune_path, tune_dates, tune_sha256 = _read_dates(args.tune_dates_file)
    holdout_path, holdout_dates, holdout_sha256 = _read_dates(args.holdout_dates_file)
    observed_terminal = {
        "corpus": corpus_file_sha256,
        "preregistration": preregistration_sha256,
        "support": support_sha256,
        "feasibility": feasibility_sha256,
        "runtime_support_correction": correction_sha256,
    }
    expected_terminal = {
        "corpus": TERMINAL_CORPUS_FILE_SHA256,
        "preregistration": TERMINAL_PREREGISTRATION_SHA256,
        "support": TERMINAL_SUPPORT_SHA256,
        "feasibility": TERMINAL_FEASIBILITY_SHA256,
        "runtime_support_correction": TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256,
    }
    if observed_terminal != expected_terminal:
        raise HardenedSourceAblationError(
            f"terminal sealed hashes differ: expected={expected_terminal}, observed={observed_terminal}"
        )
    corpus = json.loads(corpus_raw.decode("utf-8"))
    if not isinstance(corpus, dict) or corpus.get("corpus_hash") != TERMINAL_CORPUS_HASH:
        raise HardenedSourceAblationError("corpus semantic hash is not the terminal pin")
    if preregistration.get("schema_version") != "workstation_source_ablation_preregistration_v0.3":
        raise HardenedSourceAblationError("preregistration is not terminal v0.3")
    if support.get("schema_version") != "captured_source_variant_support_audit_v0.4":
        raise HardenedSourceAblationError("support seal is not terminal v0.4")
    if feasibility.get("schema_version") != "source_ablation_inference_feasibility_v0.2":
        raise HardenedSourceAblationError("feasibility seal is not terminal v0.2")
    prereg_inference = preregistration.get("inference") or {}
    prereg_variants = tuple(preregistration.get("single_source_variants") or ()) + tuple(
        (preregistration.get("group_variants") or {}).keys()
    )
    if prereg_variants != ALL_VARIANTS:
        raise HardenedSourceAblationError("preregistration family is not the exact 22 variants")
    if tuple(sorted(prereg_inference.get("primary_market_ids") or ())) != TERMINAL_MARKET_IDS:
        raise HardenedSourceAblationError("preregistration market set is not the exact fleet")
    support_provenance = support.get("provenance") or {}
    feasibility_provenance = feasibility.get("provenance") or {}
    bound_hashes = {
        "support_preregistration": (support_provenance.get("preregistration") or {}).get("sha256"),
        "support_corpus": (support_provenance.get("corpus") or {}).get("sha256"),
        "feasibility_support": (feasibility_provenance.get("support") or {}).get("sha256"),
        "feasibility_preregistration": (feasibility_provenance.get("preregistration") or {}).get("sha256"),
        "feasibility_corpus": (feasibility_provenance.get("corpus") or {}).get("sha256"),
    }
    if bound_hashes != {
        "support_preregistration": preregistration_sha256,
        "support_corpus": corpus_file_sha256,
        "feasibility_support": support_sha256,
        "feasibility_preregistration": preregistration_sha256,
        "feasibility_corpus": corpus_file_sha256,
    }:
        raise HardenedSourceAblationError("terminal seals do not bind one another exactly")
    date_provenance = {
        "tune": (support_provenance.get("tune_dates") or {}).get("sha256"),
        "holdout": (support_provenance.get("holdout_dates") or {}).get("sha256"),
    }
    if date_provenance != {"tune": tune_sha256, "holdout": holdout_sha256}:
        raise HardenedSourceAblationError("support seal date files differ from supplied seals")
    correction_predecessors = {
        "corpus_file_sha256": corpus_file_sha256,
        "corpus_hash": corpus.get("corpus_hash"),
        "preregistration_sha256": preregistration_sha256,
        "support_sha256": support_sha256,
        "feasibility_sha256": feasibility_sha256,
        "tune_dates_sha256": tune_sha256,
        "holdout_dates_sha256": holdout_sha256,
        "replay_input_manifest_sha256": support_provenance.get(
            "replay_input_manifest_sha256"
        ),
        "replay_input_file_count": support_provenance.get(
            "replay_input_file_count"
        ),
        "pinned_record_count": support.get("admitted_replay_rows"),
    }
    try:
        correction_validation = validate_runtime_support_correction(
            correction,
            repo_root=args.repo_root,
            support=support,
            predecessor_hashes=correction_predecessors,
            generation_dir=args.generation_dir,
        )
    except ValueError as exc:
        raise HardenedSourceAblationError(
            f"runtime-support correction seal is invalid: {exc}"
        ) from exc
    support_rows = support.get("variants") or []
    if [str(row.get("variant") or "") for row in support_rows] != list(
        ALL_VARIANTS
    ):
        raise HardenedSourceAblationError(
            "support seal does not contain the exact ordered 22-variant family"
        )
    for row in support_rows:
        variant = str(row["variant"])
        if tuple(row.get("members") or ()) != VARIANT_MEMBERS[variant]:
            raise HardenedSourceAblationError(
                f"support membership differs from the canonical treatment: {variant}"
            )
        splits = row.get("splits") or {}
        if tuple((splits.get("tune") or {}).get("allocated_dates") or ()) != tune_dates:
            raise HardenedSourceAblationError("support tune allocation differs across seals")
        if tuple((splits.get("holdout") or {}).get("allocated_dates") or ()) != holdout_dates:
            raise HardenedSourceAblationError("support holdout allocation differs across seals")
    strict_rows = feasibility.get("strict_variants") or []
    if [str(row.get("variant") or "") for row in strict_rows] != list(ALL_VARIANTS):
        raise HardenedSourceAblationError(
            "feasibility seal does not contain the exact ordered strict family"
        )
    market_keys = [
        (str(row.get("variant") or ""), str(row.get("market_id") or ""))
        for row in feasibility.get("variant_markets") or []
    ]
    if (
        not market_keys
        or len(market_keys) != len(set(market_keys))
        or any(variant not in VARIANT_MEMBERS for variant, _ in market_keys)
        or any(market_id not in TERMINAL_MARKET_IDS for _, market_id in market_keys)
    ):
        raise HardenedSourceAblationError(
            "feasibility variant-market family is empty, duplicated, or non-canonical"
        )
    corpus_market_ids = {
        str(row.get("market_id") or "") for row in corpus.get("entries") or []
    }
    if tuple(sorted(corpus_market_ids)) != TERMINAL_MARKET_IDS:
        raise HardenedSourceAblationError("corpus market IDs differ from terminal fleet")
    return {
        "corpus_path": corpus_path,
        "corpus": corpus,
        "corpus_file_sha256": corpus_file_sha256,
        "preregistration_path": prereg_path,
        "preregistration": preregistration,
        "preregistration_sha256": preregistration_sha256,
        "support_path": support_path,
        "support": support,
        "support_sha256": support_sha256,
        "feasibility_path": feasibility_path,
        "feasibility": feasibility,
        "feasibility_sha256": feasibility_sha256,
        "correction_path": correction_path,
        "correction": correction,
        "correction_sha256": correction_sha256,
        "correction_predecessors": correction_predecessors,
        "correction_validation": correction_validation,
        "helper_path": correction_validation["helper_path"],
        "helper_sha256": correction_validation["helper_receipt"]["sha256"],
        "helper_size_bytes": correction_validation["helper_receipt"]["size_bytes"],
        "tune_path": tune_path,
        "tune_dates": tune_dates,
        "tune_sha256": tune_sha256,
        "holdout_path": holdout_path,
        "holdout_dates": holdout_dates,
        "holdout_sha256": holdout_sha256,
    }


def build_source_closure(
    *,
    repo_root: Path,
    data_root: Path,
    snapshots_root: Path,
    contracts: Mapping[str, Any],
    generation_dir: Path,
) -> ClosureSpec:
    entries = contracts["corpus"].get("entries") or []
    paths = [
        PathBinding("python_executable", Path(sys.executable), "required_file"),
        PathBinding("sitecustomize_shim", repo_root / "sitecustomize.py", "required_file"),
        PathBinding("weather_package_shim", repo_root / "weather" / "__init__.py", "required_file"),
        PathBinding("corpus", contracts["corpus_path"], "required_file"),
        PathBinding("preregistration", contracts["preregistration_path"], "required_file"),
        PathBinding("support_seal", contracts["support_path"], "required_file"),
        PathBinding("feasibility_seal", contracts["feasibility_path"], "required_file"),
        PathBinding(
            "runtime_support_correction",
            contracts["correction_path"],
            "required_file",
        ),
        PathBinding(
            "runtime_support_helper",
            contracts["helper_path"],
            "required_file",
        ),
        PathBinding(
            "failed_generation_001",
            contracts["correction_validation"]["failed_generation_path"],
            "absent",
        ),
        PathBinding("tune_dates", contracts["tune_path"], "required_file"),
        PathBinding("holdout_dates", contracts["holdout_path"], "required_file"),
        PathBinding(
            "active_release_pointer",
            repo_root / "artifacts" / "releases" / "current_release.json",
            "absent",
        ),
    ]
    for index, entry in enumerate(entries):
        relative = str(entry.get("folder_relative_to_snapshots_root") or "")
        if not relative or Path(relative).name != relative:
            raise HardenedSourceAblationError(f"invalid corpus folder identity: {relative!r}")
        folder = (snapshots_root / relative).resolve(strict=True)
        try:
            folder.relative_to(snapshots_root)
        except ValueError as exc:
            raise HardenedSourceAblationError(f"corpus folder escapes snapshot root: {folder}") from exc
        prefix = f"corpus_{index:03d}"
        paths.extend(
            (
                PathBinding(f"{prefix}_tape", folder / "snapshots_long.csv", "required_file"),
                PathBinding(f"{prefix}_replay", folder / "replay_inputs.jsonl", "required_file"),
                PathBinding(
                    f"{prefix}_reconstructed",
                    folder / "replay_inputs_reconstructed.jsonl",
                    "file_or_absent",
                ),
            )
        )
    trees = [
        TreeBinding(
            "weather_source_tree",
            repo_root / "src" / "weather",
            excludes=("**/__pycache__/**", "**/*.pyc"),
        ),
        TreeBinding("artifact_tree", repo_root / "artifacts"),
        TreeBinding("config_tree", repo_root / "config"),
    ]
    for market_id in TERMINAL_MARKET_IDS:
        station = REGISTRY[market_id].icao.lower()
        wu_root = data_root / "wunderground" / station
        paths.append(
            PathBinding(
                f"wu_{market_id}_daily",
                wu_root / "daily" / "daily_summary.csv",
                "required_file",
            )
        )
        trees.append(
            TreeBinding(
                f"wu_{market_id}_hourly",
                wu_root / "hourly",
                includes=("year=*/month=*/observations.jsonl",),
            )
        )
    run_parameters = {
        "profile": "workstation_source_ablation_hardened_v0.1",
        "research_only": True,
        "model_binding": STATUS_RESEARCH_UNBOUND,
        "repo_root": str(repo_root),
        "data_root": str(data_root),
        "snapshots_root": str(snapshots_root),
        "generation_dir": str(generation_dir),
        "corpus_sha256": contracts["corpus_file_sha256"],
        "corpus_hash": contracts["corpus"].get("corpus_hash"),
        "preregistration_sha256": contracts["preregistration_sha256"],
        "support_sha256": contracts["support_sha256"],
        "feasibility_sha256": contracts["feasibility_sha256"],
        "runtime_support_correction_sha256": contracts["correction_sha256"],
        "runtime_support_helper_sha256": contracts["helper_sha256"],
        "runtime_support_pairs_sha256": contracts["correction_validation"][
            "pairs_sha256"
        ],
        "retry_generation_leaf": RETRY_GENERATION_LEAF,
        "variants": list(ALL_VARIANTS),
        "market_ids": list(TERMINAL_MARKET_IDS),
        "tune_dates": list(contracts["tune_dates"]),
        "holdout_dates": list(contracts["holdout_dates"]),
        "bootstrap_replicates": 10000,
        "bootstrap_base_seed": 20260722,
        "include_reconstructed": False,
    }
    return ClosureSpec(
        name="workstation-source-ablation-hardened-v0.1",
        base_root=repo_root,
        invocation=InvocationSpec.current(run_parameters=run_parameters),
        path_bindings=tuple(paths),
        tree_bindings=tuple(trees),
        environment=EnvironmentSpec(
            import_names=(
                "joblib",
                "numpy",
                "pandas",
                "scipy",
                "sklearn",
                "weather",
                "weather.backtesting.replay_ablation",
                "weather.model.feature_store",
                "weather.model.toronto_model",
                "weather.reporting.research.source_ablation_hardened",
                "weather.reporting.research.source_ablation_runtime_correction",
            )
        ),
    )


def _generation_parent(generation_dir: Path, data_root: Path) -> Path:
    if generation_dir.name in {"", ".", ".."}:
        raise HardenedSourceAblationError("generation directory needs a concrete leaf name")
    lexical_parent = generation_dir.parent
    parent = lexical_parent.resolve(strict=True)
    if parent != lexical_parent or not lexical_parent.is_dir():
        raise HardenedSourceAblationError(
            f"generation parent contains an alias or is not a directory: {lexical_parent}"
        )
    resolved_data = data_root.resolve(strict=True)
    try:
        parent.relative_to(resolved_data)
    except ValueError:
        pass
    else:
        raise HardenedSourceAblationError("generation output resolves inside read-only data")
    if os.path.lexists(generation_dir):
        raise HardenedSourceAblationError(f"generation directory already exists: {generation_dir}")
    return parent


def publish_complete_generation(
    generation_dir: Path,
    *,
    data_root: Path,
    payload: Mapping[str, Any],
    report: str,
    closure: ClosureSpec,
) -> dict[str, Any]:
    """Publish a unique generation and make COMPLETE.json its sole commit point."""

    _generation_parent(generation_dir, data_root)
    execution = payload.get("execution_identity") or {}
    start_raw = execution.get("start")
    completion_raw = execution.get("completion")
    if not isinstance(start_raw, Mapping) or not isinstance(completion_raw, Mapping):
        raise HardenedSourceAblationError(
            "generation payload lacks complete execution manifests"
        )
    start, embedded_completion = assert_serialized_completion_matches(
        start_raw, completion_raw
    )
    seals = payload.get("sealed_contracts")
    if not isinstance(seals, Mapping) or not seals:
        raise HardenedSourceAblationError("generation payload lacks terminal seals")
    with ResearchGeneration(
        generation_dir,
        read_only_roots=(data_root,),
        commit_schema_version=GENERATION_SCHEMA_VERSION,
    ) as generation:
        generation.publish_json("source_family_ablation.json", dict(payload))
        generation.publish_text("source_family_ablation.md", report)
        return generation.commit(
            start=start,
            expected_completion=embedded_completion,
            terminal_recapture=lambda: recapture_and_assert_unchanged(
                start,
                closure,
                phase=(
                    "source ablation after final output inventory "
                    "immediately before COMPLETE.json"
                ),
            ),
            terminal_seals=seals,
            extra={
                "profile": "workstation_source_ablation_hardened_v0.1",
                "artifact_schema_version": payload.get("schema_version"),
                "variant_count": (payload.get("summary") or {}).get("variant_count"),
                "market_days_scored": (payload.get("summary") or {}).get(
                    "market_days_scored"
                ),
            },
        )


def _canonicalize_variant_outputs(summaries, day_effects):
    summaries_by_variant = {
        str(row.get("variant") or ""): row for row in summaries
    }
    if (
        set(summaries_by_variant) != set(ALL_VARIANTS)
        or set(day_effects) != set(ALL_VARIANTS)
        or len(summaries_by_variant) != len(summaries)
    ):
        raise HardenedSourceAblationError(
            "sealed source replay did not produce exactly one result per variant"
        )
    return (
        [summaries_by_variant[variant] for variant in ALL_VARIANTS],
        {variant: day_effects[variant] for variant in ALL_VARIANTS},
    )


def run_hardened(args) -> tuple[dict[str, Any], dict[str, Any]]:
    repo_root = Path(args.repo_root).expanduser().resolve(strict=True)
    data_root = Path(args.data_root).expanduser().resolve(strict=True)
    snapshots_root = Path(args.snapshots_root).expanduser().resolve(strict=True)
    generation_dir = Path(
        os.path.abspath(os.fspath(Path(args.generation_dir).expanduser()))
    )
    if Path.cwd().resolve() != repo_root:
        raise HardenedSourceAblationError(
            f"run from the bound repository root: expected {repo_root}, observed {Path.cwd().resolve()}"
        )
    _generation_parent(generation_dir, data_root)
    contracts = load_terminal_contracts(args)
    corpus_manifest = {
        **contracts["corpus"],
        "_path": str(contracts["corpus_path"]),
    }
    if corpus_manifest.get("corpus_hash") != TERMINAL_CORPUS_HASH:
        raise HardenedSourceAblationError("loaded corpus differs from terminal semantic pin")
    weather_paths.DATA_ROOT = data_root
    TorontoHighTempModel._historical_target_cache.clear()
    folders = [
        str(path)
        for path in folders_from_manifest(corpus_manifest, snapshots_root)
    ]
    if len(folders) != len(corpus_manifest.get("entries") or ()):
        raise HardenedSourceAblationError("corpus folder expansion is not one-to-one")
    closure = build_source_closure(
        repo_root=repo_root,
        data_root=data_root,
        snapshots_root=snapshots_root,
        contracts=contracts,
        generation_dir=generation_dir,
    )
    start = capture_execution_identity(closure)
    post_capture_contracts = load_terminal_contracts(args)
    for key in (
        "corpus_file_sha256",
        "preregistration_sha256",
        "support_sha256",
        "feasibility_sha256",
        "correction_sha256",
        "helper_sha256",
        "helper_size_bytes",
        "tune_sha256",
        "holdout_sha256",
    ):
        if post_capture_contracts[key] != contracts[key]:
            raise HardenedSourceAblationError(
                f"terminal contract changed across start capture: {key}"
            )
    contracts = post_capture_contracts
    research_bundle = VerifiedServingBundle(
        status=STATUS_RESEARCH_UNBOUND,
        reason="sealed workstation source-ablation research; no active release binding",
        pointer_present=False,
    )
    support_audit: dict[str, Any] = {}
    model_binding: dict[str, Any] = {}
    data, market_days = run_ablation(
        folders,
        ALL_VARIANTS,
        include_reconstructed=False,
        corpus_manifest=corpus_manifest,
        support_manifest=contracts["support"],
        support_audit=support_audit,
        support_sha256=contracts["support_sha256"],
        preregistration=contracts["preregistration"],
        preregistration_sha256=contracts["preregistration_sha256"],
        feasibility=contracts["feasibility"],
        model_binding_audit=model_binding,
        model_factory=lambda market_id: TorontoHighTempModel(
            market_id=market_id,
            serving_bundle=research_bundle,
        ),
    )
    if data.empty:
        raise HardenedSourceAblationError("sealed source replay produced no paired rows")
    summaries, day_effects = summarize(data)
    summaries, day_effects = _canonicalize_variant_outputs(
        summaries, day_effects
    )
    split_dates = {
        "tune": list(contracts["tune_dates"]),
        "holdout": list(contracts["holdout_dates"]),
    }
    paired = paired_day_inference(day_effects, split_dates)
    robustness = paired_inference_sensitivities(
        day_effects,
        market_days,
        split_dates=split_dates,
        required_market_ids=TERMINAL_MARKET_IDS,
    )
    market_inference = paired_market_inference(
        day_effects,
        split_dates,
        day_meta=market_days,
    )
    completion = recapture_and_assert_unchanged(
        start, closure, phase="source replay before generation commit"
    )
    assert_serialized_completion_matches(start.to_dict(), completion.to_dict())
    sealed_contracts = {
        "corpus": _receipt(contracts["corpus_path"], contracts["corpus_file_sha256"]),
        "preregistration": _receipt(
            contracts["preregistration_path"], contracts["preregistration_sha256"]
        ),
        "support": _receipt(contracts["support_path"], contracts["support_sha256"]),
        "feasibility": _receipt(
            contracts["feasibility_path"], contracts["feasibility_sha256"]
        ),
        "runtime_support_correction": _receipt(
            contracts["correction_path"], contracts["correction_sha256"]
        ),
        "runtime_support_helper": _receipt(
            contracts["helper_path"], contracts["helper_sha256"]
        ),
        "tune_dates": _receipt(contracts["tune_path"], contracts["tune_sha256"]),
        "holdout_dates": _receipt(
            contracts["holdout_path"], contracts["holdout_sha256"]
        ),
    }
    payload = build_payload(
        summaries,
        day_effects,
        market_days,
        ALL_VARIANTS,
        False,
        summarize_slice_effects(data),
        corpus_manifest,
        paired,
        robustness,
        market_inference,
        split_dates,
        runtime_support_audit=support_audit,
        sealed_contracts=sealed_contracts,
        model_binding=model_binding,
        execution_identity={
            "start": start.to_dict(),
            "completion": completion.to_dict(),
            "full_manifest_equality": True,
        },
    )
    report = render_report(
        summaries,
        day_effects,
        market_days,
        False,
        robustness,
        market_inference,
    )
    commit = publish_complete_generation(
        generation_dir,
        data_root=data_root,
        payload=payload,
        report=report,
        closure=closure,
    )
    return payload, commit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the exact sealed, research-unbound workstation source ablation."
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--preregistration", required=True)
    parser.add_argument("--support-seal", required=True)
    parser.add_argument("--feasibility-seal", required=True)
    parser.add_argument("--runtime-support-correction-seal", required=True)
    parser.add_argument("--tune-dates-file", required=True)
    parser.add_argument("--holdout-dates-file", required=True)
    parser.add_argument("--generation-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload, commit = run_hardened(args)
    print(
        "Hardened source ablation committed: "
        f"{payload['summary']['variant_count']} variants, "
        f"{payload['summary']['market_days_scored']} market-days, "
        f"execution {commit['execution_identity']['start_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
