"""Fail-closed synthesis for the sealed workstation source-ablation run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import ntpath
import os
import posixpath
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from weather.backtesting.replay_ablation import (
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
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
from weather.reporting.research.research_generation import ResearchGeneration
from weather.reporting.research.source_ablation_hardened import (
    TERMINAL_CORPUS_HASH,
    TERMINAL_FEASIBILITY_SHA256,
    TERMINAL_MARKET_IDS,
    TERMINAL_PREREGISTRATION_SHA256,
    TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256,
    TERMINAL_SUPPORT_SHA256,
)
from weather.reporting.research.source_ablation_runtime_correction import (
    CORRECTION_SCHEMA_VERSION,
    RETRY_GENERATION_LEAF,
    stable_file_receipt,
    validate_runtime_support_correction,
)
from weather.schema_registry import schema_version


SOURCE_COMMIT_SCHEMA_VERSION = schema_version("source_ablation_generation_commit")
SYNTHESIS_COMMIT_SCHEMA_VERSION = schema_version(
    "source_ablation_synthesis_generation_commit"
)
SOURCE_ARTIFACT_NAME = "source_family_ablation.json"
SOURCE_REPORT_NAME = "source_family_ablation.md"
SOURCE_COMPLETE_NAME = "COMPLETE.json"
SYNTHESIS_ARTIFACT_NAME = "source_ablation_synthesis.json"
SYNTHESIS_REPORT_NAME = "source_ablation_synthesis.md"
SYNTHESIS_PROFILE = schema_version("source_ablation_synthesis_profile")
MAX_INPUT_BYTES = 128 * 1024 * 1024


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _manifest_path_key(base_root: object, displayed_path: object) -> tuple[str, str]:
    """Canonicalize a captured display path without touching the filesystem.

    Execution manifests display files below ``base_root`` as relative paths,
    while terminal receipts record absolute paths.  Use the captured root's
    path grammar so validation is independent of the host reading the artifact.
    """

    base_text = str(base_root or "")
    path_text = str(displayed_path or "")
    if not base_text or not path_text:
        raise ValueError("source execution profile contains an empty bound path")

    windows_base = PureWindowsPath(base_text)
    if windows_base.is_absolute():
        windows_path = PureWindowsPath(path_text)
        is_absolute = windows_path.is_absolute()
        if not is_absolute and ".." in windows_path.parts:
            raise ValueError("source execution profile contains an escaping relative path")
        normalized_base = ntpath.normcase(ntpath.normpath(str(windows_base)))
        normalized_path = ntpath.normcase(
            ntpath.normpath(
                str(windows_path)
                if is_absolute
                else ntpath.join(normalized_base, str(windows_path))
            )
        )
        if not is_absolute:
            try:
                common = ntpath.commonpath((normalized_base, normalized_path))
            except ValueError as exc:
                raise ValueError(
                    "source execution profile relative path has a different drive"
                ) from exc
            if common != normalized_base:
                raise ValueError("source execution profile relative path escapes base root")
        return "windows", normalized_path

    posix_base = PurePosixPath(base_text)
    if posix_base.is_absolute():
        posix_path = PurePosixPath(path_text)
        is_absolute = posix_path.is_absolute()
        if not is_absolute and ".." in posix_path.parts:
            raise ValueError("source execution profile contains an escaping relative path")
        normalized_base = posixpath.normpath(str(posix_base))
        normalized_path = posixpath.normpath(
            str(posix_path)
            if is_absolute
            else posixpath.join(normalized_base, str(posix_path))
        )
        if not is_absolute and posixpath.commonpath(
            (normalized_base, normalized_path)
        ) != normalized_base:
            raise ValueError("source execution profile relative path escapes base root")
        return "posix", normalized_path

    raise ValueError("source execution profile base root is not absolute")


def _stable_file(
    path: str | Path,
    *,
    max_bytes: int = MAX_INPUT_BYTES,
    require_single_link: bool = False,
) -> tuple[Path, bytes, dict[str, Any]]:
    """Read one regular file while pinning its handle and path identity."""

    resolved = Path(path).expanduser().resolve(strict=True)
    before = resolved.stat()
    if not resolved.is_file() or int(before.st_size) > int(max_bytes):
        raise ValueError(f"sealed synthesis input is missing, non-file, or too large: {resolved}")
    with resolved.open("rb") as handle:
        opened_before = os.fstat(handle.fileno())
        raw = handle.read()
        opened_after = os.fstat(handle.fileno())
    after = resolved.stat()

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_nlink),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
        )

    if not identity(before) == identity(opened_before) == identity(opened_after) == identity(after):
        raise ValueError(f"sealed synthesis input changed while reading: {resolved}")
    if require_single_link and int(after.st_nlink) != 1:
        raise ValueError(f"committed generation leaf must have one hard link: {resolved}")
    digest = hashlib.sha256(raw).hexdigest()
    return resolved, raw, {
        "path": str(resolved),
        "sha256": digest,
        "size_bytes": int(after.st_size),
    }


def _load_json(path: str | Path, *, expected_sha256: str, expected_schema: str):
    resolved, raw, receipt = _stable_file(path)
    digest = str(receipt["sha256"])
    if digest != expected_sha256:
        raise ValueError(
            f"sealed synthesis input hash differs: {resolved}; expected {expected_sha256}, observed {digest}"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"sealed synthesis input is invalid JSON: {resolved}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != expected_schema:
        raise ValueError(f"sealed synthesis input schema differs: {resolved}")
    return resolved, payload, digest


def _runtime_correction_predecessors(
    *,
    artifact: Mapping[str, Any],
    support: Mapping[str, Any],
    preregistration_sha256: str,
    support_sha256: str,
    feasibility_sha256: str,
) -> dict[str, Any]:
    """Reconstruct the correction's exact predecessor graph from sealed inputs."""

    sealed = artifact.get("sealed_contracts") or {}
    corpus = artifact.get("corpus") or {}
    provenance = support.get("provenance") or {}
    return {
        "corpus_file_sha256": (sealed.get("corpus") or {}).get("sha256"),
        "corpus_hash": corpus.get("corpus_hash"),
        "preregistration_sha256": preregistration_sha256,
        "support_sha256": support_sha256,
        "feasibility_sha256": feasibility_sha256,
        "tune_dates_sha256": (sealed.get("tune_dates") or {}).get("sha256"),
        "holdout_dates_sha256": (sealed.get("holdout_dates") or {}).get("sha256"),
        "replay_input_manifest_sha256": provenance.get(
            "replay_input_manifest_sha256"
        ),
        "replay_input_file_count": provenance.get("replay_input_file_count"),
        "pinned_record_count": support.get("admitted_replay_rows"),
    }


def _load_validate_runtime_support_correction(
    *,
    correction_path: str | Path,
    repo_root: str | Path,
    source_generation_dir: str | Path,
    artifact: Mapping[str, Any],
    support: Mapping[str, Any],
    preregistration_sha256: str,
    support_sha256: str,
    feasibility_sha256: str,
) -> dict[str, Any]:
    """Load and validate the correction, its live helper, and source receipts."""

    resolved, correction, correction_sha256 = _load_json(
        correction_path,
        expected_sha256=TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256,
        expected_schema=CORRECTION_SCHEMA_VERSION,
    )
    correction_receipt = stable_file_receipt(resolved)
    if correction_receipt["sha256"] != correction_sha256:
        raise ValueError("runtime-support correction changed across stable reads")
    predecessors = _runtime_correction_predecessors(
        artifact=artifact,
        support=support,
        preregistration_sha256=preregistration_sha256,
        support_sha256=support_sha256,
        feasibility_sha256=feasibility_sha256,
    )
    validation = validate_runtime_support_correction(
        correction,
        repo_root=repo_root,
        support=support,
        predecessor_hashes=predecessors,
        generation_dir=source_generation_dir,
    )
    source_seals = artifact.get("sealed_contracts") or {}
    observed = {
        "runtime_support_correction": correction_receipt,
        "runtime_support_helper": validation["helper_receipt"],
    }
    for label, live_receipt in observed.items():
        source_receipt = source_seals.get(label)
        if not isinstance(source_receipt, Mapping) or dict(source_receipt) != dict(
            live_receipt
        ):
            raise ValueError(
                f"source artifact {label} receipt differs from live correction evidence"
            )
    return {
        "path": resolved,
        "payload": correction,
        "receipt": correction_receipt,
        "predecessors": predecessors,
        "validation": validation,
        "helper_path": validation["helper_path"],
        "helper_receipt": validation["helper_receipt"],
    }


def _validate_source_generation_commit(
    artifact_path: Path,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the artifact's adjacent source generation to be fully committed."""

    artifact_path = artifact_path.resolve(strict=True)
    if artifact_path.name != SOURCE_ARTIFACT_NAME:
        raise ValueError(
            f"source artifact must be the canonical generation leaf {SOURCE_ARTIFACT_NAME!r}"
        )
    generation = artifact_path.parent.resolve(strict=True)
    children = {child.name: child for child in generation.iterdir()}
    expected_names = {
        SOURCE_ARTIFACT_NAME,
        SOURCE_REPORT_NAME,
        SOURCE_COMPLETE_NAME,
    }
    if (
        set(children) != expected_names
        or any(not child.is_file() for child in children.values())
        or any(
            child.is_symlink()
            or child.resolve(strict=True) != child.absolute()
            or child.resolve(strict=True).parent != generation
            for child in children.values()
        )
    ):
        raise ValueError(
            "source generation does not contain exactly the two outputs and COMPLETE.json"
        )
    complete_path, complete_raw, complete_receipt = _stable_file(
        children[SOURCE_COMPLETE_NAME],
        max_bytes=4 * 1024 * 1024,
        require_single_link=True,
    )
    try:
        commit = json.loads(complete_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"source generation COMPLETE.json is invalid: {complete_path}") from exc
    expected_commit_fields = {
        "schema_version",
        "status",
        "generated_at_utc",
        "research_only",
        "serving_or_release_authorization",
        "multi_leaf_atomic_transaction_claimed",
        "commit_marker_semantics",
        "execution_identity",
        "terminal_seals",
        "outputs",
        "metadata",
    }
    if not isinstance(commit, dict) or set(commit) != expected_commit_fields:
        raise ValueError("source generation COMPLETE.json fields differ from the exact commit contract")
    if (
        commit.get("schema_version") != SOURCE_COMMIT_SCHEMA_VERSION
        or commit.get("status") != "COMPLETE"
        or commit.get("research_only") is not True
        or commit.get("serving_or_release_authorization") is not False
        or commit.get("multi_leaf_atomic_transaction_claimed") is not False
        or commit.get("commit_marker_semantics")
        != "COMPLETE.json is the sole final commit marker"
    ):
        raise ValueError("source generation COMPLETE.json status or safety contract differs")
    generated_at = str(commit.get("generated_at_utc") or "")
    try:
        parsed_generated_at = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ValueError("source generation commit timestamp is invalid") from exc
    if parsed_generated_at.tzinfo is None:
        raise ValueError("source generation commit timestamp is not timezone-aware")

    outputs = commit.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 2:
        raise ValueError("source generation commit must contain exactly two output receipts")
    by_name: dict[str, Mapping[str, Any]] = {}
    for row in outputs:
        if not isinstance(row, Mapping) or set(row) != {"name", "sha256", "size_bytes"}:
            raise ValueError("source generation output receipt is malformed")
        name = str(row.get("name") or "")
        if name in by_name:
            raise ValueError(f"source generation has duplicate output receipt: {name}")
        if not _is_sha256(row.get("sha256")) or type(row.get("size_bytes")) is not int:
            raise ValueError(f"source generation output receipt is invalid: {name}")
        by_name[name] = row
    if set(by_name) != {SOURCE_ARTIFACT_NAME, SOURCE_REPORT_NAME}:
        raise ValueError("source generation output names differ from the exact contract")
    observed_outputs: dict[str, dict[str, Any]] = {}
    for name in (SOURCE_ARTIFACT_NAME, SOURCE_REPORT_NAME):
        _, _, receipt = _stable_file(children[name], require_single_link=True)
        observed = {key: receipt[key] for key in ("sha256", "size_bytes")}
        expected = {key: by_name[name].get(key) for key in ("sha256", "size_bytes")}
        if observed != expected:
            raise ValueError(f"source generation output differs from COMPLETE.json: {name}")
        observed_outputs[name] = receipt

    execution = artifact.get("execution_identity")
    if not isinstance(execution, Mapping):
        raise ValueError("source artifact execution identity is missing")
    start_raw = execution.get("start")
    completion_raw = execution.get("completion")
    if not isinstance(start_raw, Mapping) or not isinstance(completion_raw, Mapping):
        raise ValueError("source artifact execution manifests are missing")
    start, completion = assert_serialized_completion_matches(start_raw, completion_raw)
    commit_execution = commit.get("execution_identity")
    expected_execution = {
        "start_digest": start.identity_digest,
        "completion_digest": completion.identity_digest,
        "identical_full_manifest": True,
    }
    if commit_execution != expected_execution:
        raise ValueError("source generation execution digest differs from the artifact")
    artifact_seals = artifact.get("sealed_contracts")
    if not isinstance(artifact_seals, Mapping) or commit.get("terminal_seals") != artifact_seals:
        raise ValueError("source generation terminal-seal receipts differ from the artifact")
    required_seals = {
        "corpus",
        "preregistration",
        "support",
        "feasibility",
        "runtime_support_correction",
        "runtime_support_helper",
        "tune_dates",
        "holdout_dates",
    }
    if set(artifact_seals) != required_seals:
        raise ValueError("source artifact terminal-seal receipt family differs")
    expected_terminal_hashes = {
        "preregistration": TERMINAL_PREREGISTRATION_SHA256,
        "support": TERMINAL_SUPPORT_SHA256,
        "feasibility": TERMINAL_FEASIBILITY_SHA256,
        "runtime_support_correction": TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256,
    }
    for name, expected_digest in expected_terminal_hashes.items():
        receipt = artifact_seals.get(name)
        if not isinstance(receipt, Mapping) or receipt.get("sha256") != expected_digest:
            raise ValueError(f"source generation {name} seal receipt differs")
    for name, receipt in artifact_seals.items():
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != {"path", "sha256", "size_bytes", "mtime_ns"}
            or not str(receipt.get("path") or "")
            or not _is_sha256(receipt.get("sha256"))
            or type(receipt.get("size_bytes")) is not int
            or int(receipt["size_bytes"]) <= 0
            or type(receipt.get("mtime_ns")) is not int
            or int(receipt["mtime_ns"]) <= 0
        ):
            raise ValueError(f"source generation terminal-seal receipt is malformed: {name}")
    metadata = commit.get("metadata")
    expected_metadata = {
        "profile": "workstation_source_ablation_hardened_v0.1",
        "artifact_schema_version": "source_family_ablation_v0.2",
        "variant_count": 22,
        "market_days_scored": 309,
    }
    if metadata != expected_metadata:
        raise ValueError("source generation commit metadata differs from the exact run contract")
    final_children = {child.name: child for child in generation.iterdir()}
    if (
        set(final_children) != expected_names
        or any(not child.is_file() for child in final_children.values())
        or any(
            child.is_symlink()
            or child.resolve(strict=True) != child.absolute()
            or child.resolve(strict=True).parent != generation
            for child in final_children.values()
        )
    ):
        raise ValueError("source generation changed while verifying its commit")
    for name, expected in (
        (SOURCE_ARTIFACT_NAME, observed_outputs[SOURCE_ARTIFACT_NAME]),
        (SOURCE_REPORT_NAME, observed_outputs[SOURCE_REPORT_NAME]),
        (SOURCE_COMPLETE_NAME, complete_receipt),
    ):
        _, _, final_receipt = _stable_file(
            final_children[name], require_single_link=True
        )
        if {
            key: final_receipt[key] for key in ("sha256", "size_bytes")
        } != {key: expected[key] for key in ("sha256", "size_bytes")}:
            raise ValueError(f"source generation changed during verification: {name}")
    return {
        "generation_dir": str(generation),
        "complete": complete_receipt,
        "outputs": observed_outputs,
        "execution_identity_digest": start.identity_digest,
        "terminal_seals": copy.deepcopy(dict(artifact_seals)),
        "metadata": copy.deepcopy(dict(metadata)),
    }


def _market_day_label(row: Mapping[str, Any]) -> str:
    return str(row.get("market_day") or row.get("day") or "")


def _ordered_split_dates(split_dates: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Restore the producer's semantic split order after sorted-key JSON I/O."""

    if set(split_dates) != {"tune", "holdout"}:
        raise ValueError("source artifact split mapping differs from tune/holdout")
    return {
        split: list(split_dates[split])
        for split in ("tune", "holdout")
    }


def _validate_execution_profile(
    artifact: Mapping[str, Any],
    correction: Mapping[str, Any],
) -> str:
    execution = artifact.get("execution_identity")
    if not isinstance(execution, Mapping) or execution.get("full_manifest_equality") is not True:
        raise ValueError("source artifact lacks full start/completion identity equality")
    start_raw = execution.get("start")
    completion_raw = execution.get("completion")
    if not isinstance(start_raw, Mapping) or not isinstance(completion_raw, Mapping):
        raise ValueError("source artifact execution manifests are missing")
    start, completion = assert_serialized_completion_matches(start_raw, completion_raw)
    del completion
    bindings = {row["label"]: row for row in start.identity["bindings"]}
    required_labels = {
        "python_executable",
        "sitecustomize_shim",
        "weather_package_shim",
        "corpus",
        "preregistration",
        "support_seal",
        "feasibility_seal",
        "runtime_support_correction",
        "runtime_support_helper",
        "failed_generation_001",
        "tune_dates",
        "holdout_dates",
        "active_release_pointer",
        "weather_source_tree",
        "artifact_tree",
        "config_tree",
    }
    required_labels.update(f"wu_{market_id}_daily" for market_id in TERMINAL_MARKET_IDS)
    required_labels.update(f"wu_{market_id}_hourly" for market_id in TERMINAL_MARKET_IDS)
    for index in range(309):
        required_labels.update(
            {
                f"corpus_{index:03d}_tape",
                f"corpus_{index:03d}_replay",
                f"corpus_{index:03d}_reconstructed",
            }
        )
    missing = sorted(required_labels - set(bindings))
    if missing:
        raise ValueError(f"source execution profile is missing bindings: {missing[:5]}")
    required_file_labels = required_labels - {
        "active_release_pointer",
        "failed_generation_001",
        "weather_source_tree",
        "artifact_tree",
        "config_tree",
        *(f"wu_{market_id}_hourly" for market_id in TERMINAL_MARKET_IDS),
    }
    reconstructed_labels = {
        label for label in required_file_labels if label.endswith("_reconstructed")
    }
    required_file_labels -= reconstructed_labels
    for label in sorted(required_file_labels):
        binding = bindings[label]
        if (
            binding.get("kind") != "path"
            or binding.get("state") != "file"
            or binding.get("expectation") not in {"required_file", "file_or_absent"}
            or not _is_sha256(binding.get("sha256"))
            or type(binding.get("size_bytes")) is not int
            or int(binding["size_bytes"]) <= 0
            or not str(binding.get("resolved_path") or "")
        ):
            raise ValueError(f"source execution profile has an invalid file binding: {label}")
    for label in sorted(reconstructed_labels):
        binding = bindings[label]
        if binding.get("kind") != "path" or binding.get("expectation") != "file_or_absent":
            raise ValueError(f"source execution reconstructed-input binding is malformed: {label}")
        if binding.get("state") == "file":
            if not _is_sha256(binding.get("sha256")) or type(binding.get("size_bytes")) is not int:
                raise ValueError(f"source execution reconstructed-input receipt is invalid: {label}")
        elif binding.get("state") != "absent" or not isinstance(binding.get("absence_anchor"), Mapping):
            raise ValueError(f"source execution reconstructed-input absence is unbound: {label}")
    if bindings["active_release_pointer"].get("state") != "absent":
        raise ValueError("source execution profile does not bind an absent active release pointer")
    failed_binding = bindings["failed_generation_001"]
    if (
        failed_binding.get("kind") != "path"
        or failed_binding.get("expectation") != "absent"
        or failed_binding.get("state") != "absent"
        or not isinstance(failed_binding.get("absence_anchor"), Mapping)
    ):
        raise ValueError("source execution profile does not bind the failed generation absent")
    tree_labels = {
        "weather_source_tree",
        "artifact_tree",
        "config_tree",
        *(f"wu_{market_id}_hourly" for market_id in TERMINAL_MARKET_IDS),
    }
    for label in sorted(tree_labels):
        if (
            bindings[label].get("kind") != "tree"
            or bindings[label].get("state") != "directory"
            or not bindings[label].get("files")
        ):
            raise ValueError(f"source execution profile has an empty required tree: {label}")
        for file_row in bindings[label]["files"]:
            if (
                not isinstance(file_row, Mapping)
                or not str(file_row.get("relative_path") or "")
                or not _is_sha256(file_row.get("sha256"))
                or type(file_row.get("size_bytes")) is not int
            ):
                raise ValueError(f"source execution tree inventory is malformed: {label}")
    environment = start.identity.get("environment")
    if not isinstance(environment, Mapping):
        raise ValueError("source execution environment inventory is missing")
    required_imports = {
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
    }
    selection = environment.get("selection") or {}
    selected_imports = set(selection.get("import_names") or ())
    imports = environment.get("imports") or []
    imports_by_name = {
        str(row.get("name") or ""): row
        for row in imports
        if isinstance(row, Mapping)
    }
    if not required_imports.issubset(selected_imports) or set(imports_by_name) != selected_imports:
        raise ValueError("source execution import selection is incomplete")
    for name in sorted(required_imports):
        row = imports_by_name[name]
        if (
            not str(row.get("resolved_file") or "")
            or not _is_sha256(row.get("sha256"))
            or type(row.get("size_bytes")) is not int
            or int(row["size_bytes"]) <= 0
        ):
            raise ValueError(f"source execution imported-module receipt is incomplete: {name}")
    weather_import = imports_by_name["weather"]
    weather_shim = bindings["weather_package_shim"]
    if (
        weather_import.get("resolved_file") != weather_shim.get("resolved_path")
        or weather_import.get("sha256") != weather_shim.get("sha256")
    ):
        raise ValueError("source execution top-level weather import bypasses the bound shim")
    for name in sorted(required_imports):
        if name.startswith("weather.") and not str(
            imports_by_name[name].get("resolved_file") or ""
        ).startswith("src/weather/"):
            raise ValueError(f"source execution import is outside src/weather: {name}")
    packages = environment.get("packages") or []
    package_versions = {
        str(row.get("name") or "").casefold(): str(row.get("version") or "")
        for row in packages
        if isinstance(row, Mapping)
    }
    for name in ("joblib", "numpy", "pandas", "scipy", "scikit-learn"):
        if not package_versions.get(name):
            raise ValueError(f"source execution package inventory is incomplete: {name}")
    runtime = environment.get("runtime") or {}
    resolved_sys_path = {
        str(row.get("resolved") or "")
        for row in runtime.get("sys_path") or []
        if isinstance(row, Mapping)
    }
    if (
        runtime.get("implementation") != "cpython"
        or not str(runtime.get("python_version") or "")
        or not str(runtime.get("executable") or "")
        or not isinstance(runtime.get("sys_path"), list)
        or not runtime["sys_path"]
        or not {".", "src"}.issubset(resolved_sys_path)
        or runtime.get("executable") != bindings["python_executable"].get("resolved_path")
    ):
        raise ValueError("source execution runtime inventory is incomplete or inconsistent")
    invocation = start.identity.get("invocation") or {}
    if invocation.get("cwd") != start.identity.get("base_root"):
        raise ValueError("source execution invocation cwd differs from its bound repository")
    if not isinstance(invocation.get("argv"), list) or not invocation["argv"]:
        raise ValueError("source execution argv is missing")
    parameters = invocation.get("run_parameters") or {}
    if parameters.get("profile") != "workstation_source_ablation_hardened_v0.1":
        raise ValueError("source execution profile ID differs")
    if parameters.get("model_binding") != "RESEARCH_UNBOUND":
        raise ValueError("source execution profile is not research-unbound")
    if tuple(parameters.get("variants") or ()) != ALL_VARIANTS:
        raise ValueError("source execution profile variant family differs")
    if tuple(parameters.get("market_ids") or ()) != TERMINAL_MARKET_IDS:
        raise ValueError("source execution profile market family differs")
    if parameters.get("support_sha256") != TERMINAL_SUPPORT_SHA256:
        raise ValueError("source execution profile support hash differs")
    if parameters.get("preregistration_sha256") != TERMINAL_PREREGISTRATION_SHA256:
        raise ValueError("source execution profile preregistration hash differs")
    if parameters.get("feasibility_sha256") != TERMINAL_FEASIBILITY_SHA256:
        raise ValueError("source execution profile feasibility hash differs")
    if (
        parameters.get("runtime_support_correction_sha256")
        != TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256
    ):
        raise ValueError("source execution profile correction hash differs")
    source_seals = artifact.get("sealed_contracts") or {}
    base_root = start.identity.get("base_root")
    helper_sha256 = (source_seals.get("runtime_support_helper") or {}).get(
        "sha256"
    )
    if parameters.get("runtime_support_helper_sha256") != helper_sha256:
        raise ValueError("source execution profile correction-helper hash differs")
    correction_pairs_sha256 = (
        (correction.get("all_44_parity") or {}).get("pairs_sha256")
    )
    if parameters.get("runtime_support_pairs_sha256") != correction_pairs_sha256:
        raise ValueError("source execution profile correction-parity hash differs")
    if parameters.get("retry_generation_leaf") != RETRY_GENERATION_LEAF:
        raise ValueError("source execution profile retry generation differs")
    for label in ("runtime_support_correction", "runtime_support_helper"):
        binding = bindings[label]
        receipt = source_seals.get(label) or {}
        if (
            _manifest_path_key(base_root, binding.get("resolved_path"))
            != _manifest_path_key(base_root, receipt.get("path"))
            or binding.get("sha256") != receipt.get("sha256")
            or binding.get("size_bytes") != receipt.get("size_bytes")
            or binding.get("mtime_ns") != receipt.get("mtime_ns")
        ):
            raise ValueError(
                f"source execution profile {label} binding differs from terminal receipt"
            )
    if parameters.get("corpus_hash") != TERMINAL_CORPUS_HASH:
        raise ValueError("source execution profile corpus hash differs")
    return start.identity_digest


def _expected_support(support: Mapping[str, Any]):
    rows = support.get("variants") or []
    if [str(row.get("variant") or "") for row in rows] != list(ALL_VARIANTS):
        raise ValueError("support seal does not contain the exact ordered variants")
    return {str(row["variant"]): row for row in rows}


def _validate_runtime_support(
    artifact: Mapping[str, Any],
    support_rows: Mapping[str, Mapping[str, Any]],
) -> None:
    audit = artifact.get("runtime_support_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("source artifact lacks runtime support audit")
    if audit.get("schema_version") != "source_ablation_runtime_support_audit_v0.1":
        raise ValueError("runtime support audit schema differs")
    if audit.get("support_sha256") != TERMINAL_SUPPORT_SHA256:
        raise ValueError("runtime support audit is not bound to terminal support")
    if audit.get("preregistration_sha256") != TERMINAL_PREREGISTRATION_SHA256:
        raise ValueError("runtime support audit is not bound to terminal preregistration")
    rows = audit.get("variants") or []
    if [str(row.get("variant") or "") for row in rows] != list(ALL_VARIANTS):
        raise ValueError("runtime support audit variant family differs")
    for row in rows:
        variant = str(row["variant"])
        for split in ("tune", "holdout"):
            observed = (row.get("splits") or {}).get(split) or {}
            expected = (support_rows[variant].get("splits") or {}).get(split) or {}
            for key in (
                "supported_snapshot_count",
                "supported_snapshot_units_sha256",
                "supported_market_day_count",
            ):
                if observed.get(key) != expected.get(key):
                    raise ValueError(f"runtime support differs: {variant}/{split}/{key}")


def _validate_day_effect_support(
    day_effects: Mapping[str, Any],
    support_rows: Mapping[str, Mapping[str, Any]],
) -> None:
    if len(day_effects) != len(ALL_VARIANTS) or set(day_effects) != set(ALL_VARIANTS):
        raise ValueError("day-effect tables do not contain the exact variant family")
    for variant in ALL_VARIANTS:
        rows = day_effects.get(variant)
        if not isinstance(rows, list):
            raise ValueError(f"day-effect table is not an array: {variant}")
        actual: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError(f"day-effect row is malformed: {variant}")
            market_day = _market_day_label(row)
            if not market_day or market_day in actual:
                raise ValueError(f"day-effect market-day is blank or duplicate: {variant}")
            actual.add(market_day)
            if int(row.get("n") or 0) <= 0:
                raise ValueError(f"day-effect row has no paired bands: {variant}/{market_day}")
            for key in (
                "brier_delta",
                "logloss_delta",
                "base_brier",
                "variant_brier",
                "base_logloss",
                "variant_logloss",
            ):
                try:
                    value = float(row[key])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"day-effect metric is missing: {variant}/{market_day}/{key}") from exc
                if not math.isfinite(value):
                    raise ValueError(f"day-effect metric is nonfinite: {variant}/{market_day}/{key}")
        expected = set()
        for split in ("tune", "holdout"):
            details = (support_rows[variant].get("splits") or {}).get(split) or {}
            expected.update(
                f"{row['market_id']} {row['target_date']}"
                for row in details.get("supported_market_days") or []
            )
        if actual != expected:
            raise ValueError(
                f"day-effect market-days differ from exact support: {variant}; "
                f"missing={len(expected - actual)}, extra={len(actual - expected)}"
            )


def synthesize_hardened(
    artifact_paths: Sequence[str | Path],
    *,
    repo_root: str | Path,
    preregistration_path: str | Path,
    support_path: str | Path,
    feasibility_path: str | Path,
    runtime_support_correction_path: str | Path,
    helpers: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute inference from detailed market-day effects and apply sealed Holm families."""

    if len(artifact_paths) != 1:
        raise ValueError("hardened synthesis requires exactly one complete 22-variant generation")
    prereg_path, preregistration, prereg_sha = _load_json(
        preregistration_path,
        expected_sha256=TERMINAL_PREREGISTRATION_SHA256,
        expected_schema="workstation_source_ablation_preregistration_v0.3",
    )
    support_resolved, support, support_sha = _load_json(
        support_path,
        expected_sha256=TERMINAL_SUPPORT_SHA256,
        expected_schema="captured_source_variant_support_audit_v0.4",
    )
    feasibility_resolved, feasibility, feasibility_sha = _load_json(
        feasibility_path,
        expected_sha256=TERMINAL_FEASIBILITY_SHA256,
        expected_schema="source_ablation_inference_feasibility_v0.2",
    )
    terminal_sizes = {
        "preregistration": prereg_path.stat().st_size,
        "support": support_resolved.stat().st_size,
        "feasibility": feasibility_resolved.stat().st_size,
    }
    artifact_path, artifact = helpers["load_artifact"](artifact_paths[0])
    source_generation = _validate_source_generation_commit(artifact_path, artifact)
    correction_evidence = _load_validate_runtime_support_correction(
        correction_path=runtime_support_correction_path,
        repo_root=repo_root,
        source_generation_dir=artifact_path.parent,
        artifact=artifact,
        support=support,
        preregistration_sha256=prereg_sha,
        support_sha256=support_sha,
        feasibility_sha256=feasibility_sha,
    )
    sealed_receipts = artifact.get("sealed_contracts") or {}
    for label, resolved, digest in (
        ("preregistration", prereg_path, prereg_sha),
        ("support", support_resolved, support_sha),
        ("feasibility", feasibility_resolved, feasibility_sha),
    ):
        receipt = sealed_receipts.get(label)
        if not isinstance(receipt, Mapping):
            raise ValueError(f"source artifact lacks the {label} seal receipt")
        try:
            receipt_path = Path(str(receipt.get("path") or "")).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"source artifact {label} seal path is invalid") from exc
        if (
            receipt_path != resolved
            or receipt.get("sha256") != digest
            or receipt.get("size_bytes") != resolved.stat().st_size
        ):
            raise ValueError(f"supplied {label} seal differs from the source generation receipt")
    if tuple(artifact.get("requested_variants") or ()) != ALL_VARIANTS:
        raise ValueError("source artifact is not the exact ordered 22-variant run")
    definitions = artifact.get("variants") or []
    if [str(row.get("variant") or "") for row in definitions] != list(ALL_VARIANTS):
        raise ValueError("source artifact definitions are not exact and ordered")
    for row in definitions:
        variant = str(row["variant"])
        if tuple(row.get("ablated_sources") or ()) != VARIANT_MEMBERS[variant]:
            raise ValueError(f"source artifact membership differs: {variant}")
    corpus = artifact.get("corpus") or {}
    if (
        corpus.get("corpus_hash") != TERMINAL_CORPUS_HASH
        or int(corpus.get("market_day_count") or 0) != 309
        or int(corpus.get("snapshot_count") or 0) != 44178
        or corpus.get("input_verification") != "PASS"
    ):
        raise ValueError("source artifact corpus identity differs from terminal corpus")
    sealed = artifact.get("sealed_contracts") or {}
    if (sealed.get("preregistration") or {}).get("sha256") != prereg_sha:
        raise ValueError("source artifact preregistration receipt differs")
    if (sealed.get("support") or {}).get("sha256") != support_sha:
        raise ValueError("source artifact support receipt differs")
    if (sealed.get("feasibility") or {}).get("sha256") != feasibility_sha:
        raise ValueError("source artifact feasibility receipt differs")
    if artifact.get("include_reconstructed") is not False:
        raise ValueError("source artifact admitted reconstructed inputs")
    model_binding = artifact.get("model_binding") or {}
    if (
        model_binding.get("status") != "RESEARCH_UNBOUND"
        or model_binding.get("pointer_present") is not False
        or model_binding.get("shared_explicit_bundle") is not True
        or model_binding.get("serving_or_release_authorization") is not False
        or tuple(model_binding.get("market_ids") or ()) != TERMINAL_MARKET_IDS
    ):
        raise ValueError("source artifact is not explicitly research-unbound")
    execution_digest = _validate_execution_profile(
        artifact, correction_evidence["payload"]
    )
    support_rows = _expected_support(support)
    _validate_runtime_support(artifact, support_rows)

    split_dates = artifact.get("split_dates") or {}
    expected_allocations = {
        split: list(((next(iter(support_rows.values())).get("splits") or {}).get(split) or {}).get("allocated_dates") or [])
        for split in ("tune", "holdout")
    }
    if split_dates != expected_allocations:
        raise ValueError("source artifact split allocation differs from support seal")
    # ResearchGeneration serializes JSON with sorted keys, so a reloaded
    # ``split_dates`` mapping is holdout-first even though the producer computed
    # inference in the preregistered tune-then-holdout order.  Restore that
    # semantic order before comparing ordered inference-row families.
    split_dates = _ordered_split_dates(split_dates)
    market_days = artifact.get("market_days")
    if not isinstance(market_days, list) or len(market_days) != 309:
        raise ValueError("source artifact does not contain exactly 309 market-day metadata rows")
    labels = [_market_day_label(row) for row in market_days if isinstance(row, Mapping)]
    if len(labels) != 309 or len(set(labels)) != 309:
        raise ValueError("source artifact market-day metadata is blank or duplicated")
    day_effects = artifact.get("day_effects")
    if not isinstance(day_effects, Mapping):
        raise ValueError("source artifact day effects are missing")
    _validate_day_effect_support(day_effects, support_rows)
    day_effects = {
        variant: day_effects[variant] for variant in ALL_VARIANTS
    }

    recomputed_paired = paired_day_inference(day_effects, split_dates)
    recomputed_robustness = paired_inference_sensitivities(
        day_effects,
        market_days,
        split_dates=split_dates,
        required_market_ids=TERMINAL_MARKET_IDS,
    )
    recomputed_markets = paired_market_inference(
        day_effects,
        split_dates,
        day_meta=market_days,
    )
    for label, observed, recomputed in (
        ("paired", artifact.get("paired_inference"), recomputed_paired),
        ("robustness", artifact.get("robustness_inference"), recomputed_robustness),
        ("market", artifact.get("market_inference"), recomputed_markets),
    ):
        if _canonical(observed) != _canonical(recomputed):
            raise ValueError(f"source artifact {label} inference differs from recomputation")

    primary = [
        copy.deepcopy(row)
        for row in recomputed_robustness
        if row.get("scope") == helpers["primary_scope"]
        and row.get("split") == "holdout"
    ]
    if [str(row.get("variant") or "") for row in primary] != list(ALL_VARIANTS):
        raise ValueError("strict holdout inference is not one-to-one with variants")
    feasibility_strict_rows = feasibility.get("strict_variants") or []
    if [
        str(row.get("variant") or "")
        for row in feasibility_strict_rows
        if isinstance(row, Mapping)
    ] != list(ALL_VARIANTS):
        raise ValueError("strict feasibility family is not exact and ordered")
    feasibility_strict = {
        str(row.get("variant") or ""): int(row.get("strict_holdout_date_count") or 0)
        for row in feasibility_strict_rows
    }
    for row in primary:
        helpers["validate_fleet"](
            row, scope=helpers["primary_scope"], strict_panel=True
        )
        if int(row.get("fleet_dates") or 0) != feasibility_strict[str(row["variant"])]:
            raise ValueError(f"strict date count differs from feasibility seal: {row['variant']}")
    primary = helpers["add_primary_holm"](primary)
    for row in primary:
        row["disposition"] = helpers["overall_disposition"](row, require_holm=True)

    secondary = [
        copy.deepcopy(row)
        for row in recomputed_robustness
        if row.get("scope") == helpers["secondary_scope"]
        and row.get("split") == "holdout"
    ]
    if [str(row.get("variant") or "") for row in secondary] != list(ALL_VARIANTS):
        raise ValueError("daily-summary holdout inference is not one-to-one with variants")
    primary_by_variant = {str(row["variant"]): row for row in primary}
    for row in secondary:
        helpers["validate_fleet"](
            row, scope=helpers["secondary_scope"], strict_panel=False
        )
        row["disposition"] = helpers["overall_disposition"](row, require_holm=False)
        row["strict_12_market_supported"] = bool(
            int(primary_by_variant[str(row["variant"])].get("fleet_dates") or 0)
        )

    holdout_markets = [
        copy.deepcopy(row)
        for row in recomputed_markets
        if row.get("split") == "holdout"
        and row.get("scope") == "configured_daily_summary_only"
    ]
    observed_market_keys = {
        (str(row.get("variant") or ""), str(row.get("market_id") or ""))
        for row in holdout_markets
    }
    feasible_market_keys = {
        (str(row.get("variant") or ""), str(row.get("market_id") or ""))
        for row in feasibility.get("variant_markets") or []
    }
    if len(observed_market_keys) != len(holdout_markets):
        raise ValueError("daily-summary market inference contains duplicate keys")
    if len(feasible_market_keys) != len(feasibility.get("variant_markets") or []):
        raise ValueError("market feasibility seal contains duplicate keys")
    if observed_market_keys != feasible_market_keys:
        raise ValueError("daily-summary variant-market family differs from feasibility seal")
    for row in holdout_markets:
        helpers["validate_market"](row)
    corrected_markets = helpers["add_market_holm"](holdout_markets)
    for row in corrected_markets:
        row["disposition"] = helpers["market_disposition"](row)
    city_actions = [
        row for row in corrected_markets
        if row["disposition"] != "no_city_action_after_holm"
    ]
    strict_actions = [
        row for row in primary
        if row["disposition"] in {
            "source_helps_both_scores_after_holm",
            "source_harms_both_scores_after_holm",
        }
    ]
    market_sets: dict[str, set[str]] = {variant: set() for variant in ALL_VARIANTS}
    for variant, market_id in observed_market_keys:
        market_sets[variant].add(market_id)
    split_attestation = {
        split: {
            "dates": values,
            "count": len(values),
            "sha256": hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest(),
        }
        for split, values in expected_allocations.items()
    }
    final_terminal = (
        _load_json(
            prereg_path,
            expected_sha256=TERMINAL_PREREGISTRATION_SHA256,
            expected_schema="workstation_source_ablation_preregistration_v0.3",
        ),
        _load_json(
            support_resolved,
            expected_sha256=TERMINAL_SUPPORT_SHA256,
            expected_schema="captured_source_variant_support_audit_v0.4",
        ),
        _load_json(
            feasibility_resolved,
            expected_sha256=TERMINAL_FEASIBILITY_SHA256,
            expected_schema="source_ablation_inference_feasibility_v0.2",
        ),
    )
    final_correction = _load_validate_runtime_support_correction(
        correction_path=correction_evidence["path"],
        repo_root=repo_root,
        source_generation_dir=artifact_path.parent,
        artifact=artifact,
        support=support,
        preregistration_sha256=prereg_sha,
        support_sha256=support_sha,
        feasibility_sha256=feasibility_sha,
    )
    if (
        final_terminal[0][0] != prereg_path
        or _canonical(final_terminal[0][1]) != _canonical(preregistration)
        or final_terminal[1][0] != support_resolved
        or _canonical(final_terminal[1][1]) != _canonical(support)
        or final_terminal[2][0] != feasibility_resolved
        or _canonical(final_terminal[2][1]) != _canonical(feasibility)
        or final_correction["path"] != correction_evidence["path"]
        or _canonical(final_correction["payload"])
        != _canonical(correction_evidence["payload"])
        or final_correction["receipt"] != correction_evidence["receipt"]
        or final_correction["helper_receipt"]
        != correction_evidence["helper_receipt"]
        or final_correction["validation"]["pairs_sha256"]
        != correction_evidence["validation"]["pairs_sha256"]
    ):
        raise ValueError(
            "terminal synthesis seals or runtime-support correction changed "
            "during recomputation"
        )
    final_artifact_path, final_artifact = helpers["load_artifact"](artifact_path)
    if final_artifact_path != artifact_path or _canonical(final_artifact) != _canonical(artifact):
        raise ValueError("source artifact changed during synthesis recomputation")
    if _canonical(
        _validate_source_generation_commit(final_artifact_path, final_artifact)
    ) != _canonical(source_generation):
        raise ValueError("source generation commit changed during synthesis recomputation")
    return {
        "schema_version": helpers["schema_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "non_outcome_blind_reanalysis": True,
        "serving_or_release_authorization": False,
        "corpus_hash": TERMINAL_CORPUS_HASH,
        "corpus_identity": {
            "corpus_hash": TERMINAL_CORPUS_HASH,
            "as_of": corpus.get("as_of"),
            "market_day_count": 309,
            "snapshot_count": 44178,
            "input_verification": "PASS",
        },
        "include_reconstructed": False,
        "execution_identity_digest": execution_digest,
        "source_generation": source_generation,
        "split_date_attestation": split_attestation,
        "sealed_contracts": {
            "preregistration": {
                "path": str(prereg_path),
                "sha256": prereg_sha,
                "size_bytes": terminal_sizes["preregistration"],
            },
            "support": {
                "path": str(support_resolved),
                "sha256": support_sha,
                "size_bytes": terminal_sizes["support"],
            },
            "feasibility": {
                "path": str(feasibility_resolved),
                "sha256": feasibility_sha,
                "size_bytes": terminal_sizes["feasibility"],
            },
            "runtime_support_correction": copy.deepcopy(
                correction_evidence["receipt"]
            ),
            "runtime_support_helper": copy.deepcopy(
                correction_evidence["helper_receipt"]
            ),
        },
        "input_artifacts": [
            {
                "path": str(artifact_path),
                "size_bytes": artifact_path.stat().st_size,
                "sha256": helpers["sha256"](artifact_path),
                "variants": list(ALL_VARIANTS),
            }
        ],
        "variant_definitions": [
            {
                "variant": variant,
                "ablated_sources": list(VARIANT_MEMBERS[variant]),
                "effect_interpretation": (
                    "single_source_removal"
                    if len(VARIANT_MEMBERS[variant]) == 1
                    else "joint_group_removal_not_additive"
                ),
            }
            for variant in ALL_VARIANTS
        ],
        "contract": {
            "primary_split": "holdout",
            "primary_scope": helpers["primary_scope"],
            "primary_market_ids": list(TERMINAL_MARKET_IDS),
            "primary_scope_reason": "exact daily-summary 12-market set equality",
            "primary_multiplicity": "Holm separately across all supported strict holdout variants per score",
            "per_market_multiplicity": "Holm separately across all supported holdout daily-summary variant-market tests per score",
            "secondary_scope": helpers["secondary_scope"],
            "secondary_scope_reason": "support-conditional daily-summary fleet-date description",
            "positive_delta_meaning": "removing the source hurt; source helped",
            "shared_panel_warning": "22 treatments share one outcome panel and are not independent confirmations",
        },
        "summary": {
            "artifact_count": 1,
            "variant_count": len(ALL_VARIANTS),
            "supported_primary_test_count": sum(int(row.get("fleet_dates") or 0) > 0 for row in primary),
            "strict_action_count_after_holm": len(strict_actions),
            "market_test_count": len(corrected_markets),
            "market_count_min": min(len(values) for values in market_sets.values()),
            "market_count_max": max(len(values) for values in market_sets.values()),
            "city_action_count_after_holm": len(city_actions),
        },
        "market_coverage_by_variant": [
            {
                "variant": variant,
                "market_count": len(market_sets[variant]),
                "market_ids": sorted(market_sets[variant]),
            }
            for variant in ALL_VARIANTS
        ],
        "primary_holdout": primary,
        "daily_summary_holdout": secondary,
        "per_market_holdout_holm": corrected_markets,
        "city_actions_after_holm": city_actions,
        "interpretation_limits": list(preregistration.get("interpretation_limits") or []),
    }


def build_synthesis_closure(
    *,
    repo_root: Path,
    data_root: Path,
    artifact_path: Path,
    source_generation: Mapping[str, Any],
    preregistration_path: Path,
    support_path: Path,
    feasibility_path: Path,
    runtime_support_correction: Mapping[str, Any],
    generation_dir: Path,
) -> ClosureSpec:
    """Bind every executable or evidentiary input to the synthesis run."""

    complete_receipt = source_generation.get("complete") or {}
    source_complete = Path(str(complete_receipt.get("path") or "")).resolve(strict=True)
    source_generation_dir = artifact_path.parent.resolve(strict=True)
    run_parameters = {
        "profile": SYNTHESIS_PROFILE,
        "research_only": True,
        "serving_or_release_authorization": False,
        "repo_root": str(repo_root),
        "read_only_data_root": str(data_root),
        "source_generation_dir": str(source_generation_dir),
        "source_artifact": str(artifact_path),
        "source_artifact_sha256": str(
            (source_generation.get("outputs") or {})[SOURCE_ARTIFACT_NAME]["sha256"]
        ),
        "source_complete_sha256": str(complete_receipt.get("sha256") or ""),
        "source_execution_identity_digest": str(
            source_generation.get("execution_identity_digest") or ""
        ),
        "preregistration_sha256": TERMINAL_PREREGISTRATION_SHA256,
        "support_sha256": TERMINAL_SUPPORT_SHA256,
        "feasibility_sha256": TERMINAL_FEASIBILITY_SHA256,
        "runtime_support_correction_sha256": (
            runtime_support_correction["receipt"]["sha256"]
        ),
        "runtime_support_helper_sha256": (
            runtime_support_correction["helper_receipt"]["sha256"]
        ),
        "runtime_support_pairs_sha256": (
            runtime_support_correction["validation"]["pairs_sha256"]
        ),
        "retry_generation_leaf": RETRY_GENERATION_LEAF,
        "generation_dir": str(generation_dir),
        "artifact_count": 1,
        "variants": list(ALL_VARIANTS),
        "market_ids": list(TERMINAL_MARKET_IDS),
    }
    return ClosureSpec(
        name="source-ablation-synthesis-hardened-v0.1",
        base_root=repo_root,
        invocation=InvocationSpec.current(run_parameters=run_parameters),
        path_bindings=(
            PathBinding("python_executable", Path(sys.executable), "required_file"),
            PathBinding("sitecustomize_shim", repo_root / "sitecustomize.py", "required_file"),
            PathBinding(
                "weather_package_shim",
                repo_root / "weather" / "__init__.py",
                "required_file",
            ),
            PathBinding("source_artifact", artifact_path, "required_file"),
            PathBinding("source_generation_complete", source_complete, "required_file"),
            PathBinding("preregistration", preregistration_path, "required_file"),
            PathBinding("support_seal", support_path, "required_file"),
            PathBinding("feasibility_seal", feasibility_path, "required_file"),
            PathBinding(
                "runtime_support_correction",
                runtime_support_correction["path"],
                "required_file",
            ),
            PathBinding(
                "runtime_support_helper",
                runtime_support_correction["helper_path"],
                "required_file",
            ),
            PathBinding(
                "failed_generation_001",
                runtime_support_correction["validation"]["failed_generation_path"],
                "absent",
            ),
            PathBinding(
                "active_release_pointer",
                repo_root / "artifacts" / "releases" / "current_release.json",
                "absent",
            ),
        ),
        tree_bindings=(
            TreeBinding("source_generation_tree", source_generation_dir),
            TreeBinding(
                "weather_source_tree",
                repo_root / "src" / "weather",
                excludes=("**/__pycache__/**", "**/*.pyc"),
            ),
            TreeBinding("artifact_tree", repo_root / "artifacts"),
            TreeBinding("config_tree", repo_root / "config"),
        ),
        environment=EnvironmentSpec(
            import_names=(
                "joblib",
                "numpy",
                "pandas",
                "scipy",
                "sklearn",
                "weather",
                "weather.backtesting.replay_ablation",
                "weather.execution_identity",
                "weather.reporting.research.research_generation",
                "weather.reporting.research.source_ablation_synthesis",
                "weather.reporting.research.source_ablation_synthesis_hardened",
                "weather.reporting.research.source_ablation_runtime_correction",
            )
        ),
    )


def publish_synthesis_generation(
    *,
    generation_dir: Path,
    data_root: Path,
    source_generation_dir: Path,
    payload: Mapping[str, Any],
    report: str,
    start,
    closure: ClosureSpec,
    terminal_seals: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish two immutable leaves and commit only after a final recapture."""

    embedded_identity = payload.get("synthesis_execution_identity")
    if not isinstance(embedded_identity, Mapping):
        raise ValueError(
            "synthesis execution identity must contain start and completion manifests"
        )
    embedded_start_raw = embedded_identity.get("start")
    embedded_completion_raw = embedded_identity.get("completion")
    if not isinstance(embedded_start_raw, Mapping) or not isinstance(
        embedded_completion_raw, Mapping
    ):
        raise ValueError(
            "synthesis execution identity must contain start and completion manifests"
        )
    embedded_start, embedded_completion = assert_serialized_completion_matches(
        embedded_start_raw,
        embedded_completion_raw,
    )
    assert_serialized_completion_matches(
        start.to_dict(),
        embedded_start.to_dict(),
    )
    with ResearchGeneration(
        generation_dir=generation_dir,
        read_only_roots=(data_root, source_generation_dir),
        commit_schema_version=SYNTHESIS_COMMIT_SCHEMA_VERSION,
    ) as generation:
        generation.publish_json(SYNTHESIS_ARTIFACT_NAME, payload)
        generation.publish_text(SYNTHESIS_REPORT_NAME, report)
        return generation.commit(
            start=start,
            expected_completion=embedded_completion,
            terminal_recapture=lambda: recapture_and_assert_unchanged(
                start,
                closure,
                phase=(
                    "source-ablation synthesis after final output inventory "
                    "immediately before COMPLETE.json"
                ),
            ),
            terminal_seals=terminal_seals,
            extra={
                "profile": SYNTHESIS_PROFILE,
                "artifact_schema_version": payload.get("schema_version"),
                "source_execution_identity_digest": payload.get(
                    "execution_identity_digest"
                ),
                "variant_count": (payload.get("summary") or {}).get("variant_count"),
            },
        )


def run_hardened_synthesis(args) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify, recompute, bind, and exclusively commit one sealed synthesis."""

    from weather.reporting.research.source_ablation_synthesis import (
        _load_artifact,
        render_report,
        synthesize,
    )

    repo_root = Path(args.repo_root).expanduser().resolve(strict=True)
    data_root = Path(args.data_root).expanduser().resolve(strict=True)
    if not repo_root.is_dir() or not data_root.is_dir():
        raise ValueError("repository and read-only data roots must be directories")
    if Path.cwd().resolve(strict=True) != repo_root:
        raise ValueError(
            f"run synthesis from the bound repository root: expected {repo_root}, "
            f"observed {Path.cwd().resolve(strict=True)}"
        )
    artifact_path, source_artifact = _load_artifact(args.artifact)
    source_generation = _validate_source_generation_commit(
        artifact_path, source_artifact
    )
    preregistration_path, _, preregistration_sha256 = _load_json(
        args.preregistration,
        expected_sha256=TERMINAL_PREREGISTRATION_SHA256,
        expected_schema="workstation_source_ablation_preregistration_v0.3",
    )
    support_path, support, support_sha256 = _load_json(
        args.support_seal,
        expected_sha256=TERMINAL_SUPPORT_SHA256,
        expected_schema="captured_source_variant_support_audit_v0.4",
    )
    feasibility_path, _, feasibility_sha256 = _load_json(
        args.feasibility_seal,
        expected_sha256=TERMINAL_FEASIBILITY_SHA256,
        expected_schema="source_ablation_inference_feasibility_v0.2",
    )
    correction_evidence = _load_validate_runtime_support_correction(
        correction_path=args.runtime_support_correction_seal,
        repo_root=repo_root,
        source_generation_dir=artifact_path.parent,
        artifact=source_artifact,
        support=support,
        preregistration_sha256=preregistration_sha256,
        support_sha256=support_sha256,
        feasibility_sha256=feasibility_sha256,
    )
    generation_dir = Path(
        os.path.abspath(os.fspath(Path(args.generation_dir).expanduser()))
    )
    # Fail before recomputing inference if the destination is pre-existing or
    # aliases either read-only evidence root.  Publication repeats this check
    # to close the admission/commit race.
    ResearchGeneration(
        generation_dir=generation_dir,
        read_only_roots=(data_root, artifact_path.parent),
        commit_schema_version=SYNTHESIS_COMMIT_SCHEMA_VERSION,
    )
    closure = build_synthesis_closure(
        repo_root=repo_root,
        data_root=data_root,
        artifact_path=artifact_path,
        source_generation=source_generation,
        preregistration_path=preregistration_path,
        support_path=support_path,
        feasibility_path=feasibility_path,
        runtime_support_correction=correction_evidence,
        generation_dir=generation_dir,
    )
    start = capture_execution_identity(closure)
    payload = synthesize(
        (artifact_path,),
        repo_root=repo_root,
        preregistration_path=preregistration_path,
        support_path=support_path,
        feasibility_path=feasibility_path,
        runtime_support_correction_path=correction_evidence["path"],
    )
    completion = recapture_and_assert_unchanged(
        start,
        closure,
        phase="source-ablation synthesis computation",
    )
    payload["synthesis_execution_identity"] = {
        "start": start.to_dict(),
        "completion": completion.to_dict(),
        "full_manifest_equality": True,
    }
    report = render_report(payload)
    final_correction_evidence = _load_validate_runtime_support_correction(
        correction_path=correction_evidence["path"],
        repo_root=repo_root,
        source_generation_dir=artifact_path.parent,
        artifact=source_artifact,
        support=support,
        preregistration_sha256=preregistration_sha256,
        support_sha256=support_sha256,
        feasibility_sha256=feasibility_sha256,
    )
    if (
        final_correction_evidence["receipt"] != correction_evidence["receipt"]
        or final_correction_evidence["helper_receipt"]
        != correction_evidence["helper_receipt"]
        or _canonical(final_correction_evidence["payload"])
        != _canonical(correction_evidence["payload"])
    ):
        raise ValueError(
            "runtime-support correction or live helper changed before publication"
        )
    terminal_seals = {
        **copy.deepcopy(dict(payload["sealed_contracts"])),
        "source_generation_complete": copy.deepcopy(
            dict(source_generation["complete"])
        ),
    }
    commit = publish_synthesis_generation(
        generation_dir=generation_dir,
        data_root=data_root,
        source_generation_dir=artifact_path.parent,
        payload=payload,
        report=report,
        start=start,
        closure=closure,
        terminal_seals=terminal_seals,
    )
    return payload, commit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute and exclusively commit the synthesis of one exact sealed "
            "source-ablation generation; this command does not rerun replay."
        )
    )
    parser.add_argument("artifact")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--preregistration", required=True)
    parser.add_argument("--support-seal", required=True)
    parser.add_argument("--feasibility-seal", required=True)
    parser.add_argument("--runtime-support-correction-seal", required=True)
    parser.add_argument("--generation-dir", required=True)
    return parser


__all__ = [
    "SOURCE_ARTIFACT_NAME",
    "SOURCE_COMPLETE_NAME",
    "SOURCE_REPORT_NAME",
    "SYNTHESIS_ARTIFACT_NAME",
    "SYNTHESIS_REPORT_NAME",
    "build_parser",
    "build_synthesis_closure",
    "publish_synthesis_generation",
    "run_hardened_synthesis",
    "synthesize_hardened",
]
