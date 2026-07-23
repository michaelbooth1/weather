"""One-shot strict fresh-panel confirmation for a sealed gen2 H1 candidate."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import stat as stat_module
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityError,
    InvocationSpec,
    atomic_write_json_exclusive,
    assert_serialized_completion_matches,
    capture_execution_identity,
    recapture_and_assert_unchanged,
)
from weather.market.market_registry import REGISTRY
from weather.reporting.research.ordinal_smoothing_execution_closure import (
    DEFAULT_IMPORT_NAMES,
    RESEARCH_GRAPH_KIND,
    build_replay_closure_spec,
    execution_lineage,
    run_partition_arm,
)
from weather.reporting.research.ordinal_smoothing_fresh_confirmation_audit import (
    audit_manifest_entries,
    build_date_panel,
)
from weather.reporting.research.ordinal_smoothing_physical_refinement import (
    FIXED_BLEND_WEIGHT,
    PHYSICAL_C_SIGMA_ANCHORS,
    native_sigma,
    select_family_sigmas,
)
from weather.reporting.research.ordinal_smoothing_physical_replay import (
    configure_staged_data_root,
    validate_staged_daily_inputs,
)
from weather.reporting.research.ordinal_smoothing_physical_replay_gen2 import (
    EXPECTED_TUNE_CORPUS_FILE_SHA256,
    EXPECTED_TUNE_CORPUS_HASH,
    EXPECTED_TUNE_DATES,
    EXPECTED_TUNE_DATES_FILE_SHA256,
    EXPECTED_TUNE_ENTRY_COUNT,
    PROFILE as TUNE_PROFILE,
    REPORT_NAME as TUNE_REPORT_NAME,
    RESULT_NAME as TUNE_RESULT_NAME,
)
from weather.reporting.research.ordinal_smoothing_sweep import (
    BOOTSTRAP_REPLICATES,
    alignment_gate,
    folders_for_entries,
    mass_gate,
    paired_fleet_date_rows,
    paired_summary,
    scope_effect_audit,
)
from weather.reporting.research.research_generation import (
    COMPLETE_NAME,
    ResearchGeneration,
    ResearchGenerationError,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("ordinal_smoothing_physical_confirmation")
GENERATION_SCHEMA_VERSION = schema_version(
    "ordinal_smoothing_physical_confirmation_generation_commit"
)
TUNE_SCHEMA_VERSION = schema_version("ordinal_smoothing_physical_replay_gen2")
TUNE_GENERATION_SCHEMA_VERSION = schema_version(
    "ordinal_smoothing_physical_replay_gen2_generation_commit"
)
PROFILE = "ordinal_smoothing_physical_confirmation_strict_v0.1"
STRICT_DATES = (
    "2026-07-15",
    "2026-07-16",
    "2026-07-17",
    "2026-07-18",
    "2026-07-19",
)
EXPECTED_FRESH_MANIFEST_SHA256 = (
    "b9ea179b2fe6305f33771c2ee6a0dc6336e30ea995a89454fbf257775b5cfeba"
)
EXPECTED_FRESH_CORPUS_HASH = (
    "c8cf729d1b185101286624777a831ed15e496f82b9e94071710ab97e40a1a336"
)
EXPECTED_FRESH_SOURCE_MANIFEST_SHA256 = (
    "4ff50585a1b2cbdb7bd1a5f4be633b7b3cecf5bba6a42f4109080d4c98c6d180"
)
EXPECTED_FRESH_SOURCE_CORPUS_HASH = (
    "1117ad38a60ef128f4881dbf6d89db36034a15d93b12fec586af75cfd2f3c288"
)
RESULT_NAME = "ordinal_smoothing_physical_confirmation.json"
REPORT_NAME = "ordinal_smoothing_physical_confirmation.md"
MAX_INPUT_JSON_BYTES = 256 * 1024**2
MAX_CACHE_BYTES = 2 * 1024**3
UNITS = ("C", "F")


class ConfirmationError(RuntimeError):
    """The one-shot confirmation cannot proceed under its sealed contract."""


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


def _stable_file(
    path: Path, *, max_bytes: int | None = None, capture: bool = True
) -> tuple[bytes | None, dict[str, Any]]:
    before_link = path.lstat()
    before = path.stat()
    is_reparse = bool(int(getattr(before_link, "st_file_attributes", 0)) & 0x400)
    if (
        path.is_symlink()
        or is_reparse
        or not stat_module.S_ISREG(before.st_mode)
        or int(before.st_nlink) != 1
        or (max_bytes is not None and before.st_size > max_bytes)
    ):
        raise ConfirmationError(f"input is missing, non-file, or too large: {path}")
    digest = hashlib.sha256()
    chunks = [] if capture else None
    with path.open("rb") as handle:
        opened_before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        opened_after = os.fstat(handle.fileno())
    after = path.stat()
    after_link = path.lstat()

    def identity(value):
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_nlink),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
        )

    if (
        not identity(before)
        == identity(before_link)
        == identity(opened_before)
        == identity(opened_after)
        == identity(after)
        == identity(after_link)
    ):
        raise ConfirmationError(f"input changed while reading: {path}")
    return (b"".join(chunks) if chunks is not None else None), {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "size_bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
        "nlink": int(after.st_nlink),
    }


def _stable_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, receipt = _stable_file(path, max_bytes=MAX_INPUT_JSON_BYTES)
    if raw is None:  # pragma: no cover - defensive contract guard
        raise ConfirmationError(f"JSON input was not captured: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfirmationError(f"invalid JSON input: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfirmationError(f"JSON input root must be an object: {path}")
    return value, receipt


def _bound_absolute(value: Any, base_root: Path) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = base_root / path
    return path.resolve(strict=False)


def _validate_tune_identity_semantics(
    manifest, *, generation: Path, result: Mapping[str, Any]
) -> dict[str, Any]:
    identity = manifest.identity
    experiment = result.get("experiment") or {}
    invocation = identity.get("invocation") or {}
    parameters = invocation.get("run_parameters") or {}
    expected_parameter_keys = {
        "profile",
        "schema_version",
        "model_graph",
        "research_only",
        "active_or_current_production_claimed",
        "repo_root",
        "mirror_data_root",
        "staged_data_root",
        "snapshots_root",
        "tune_corpus",
        "tune_dates_file",
        "generation_dir",
        "tune_dates",
        "tune_dates_file_sha256",
        "tune_corpus_file_sha256",
        "tune_corpus_hash",
        "tune_corpus_entry_count",
        "canary_date",
        "physical_c_sigma_anchors",
        "native_mapping",
        "blend_weight",
        "selection_rule",
        "fresh_manifest_accepted",
        "holdout_accepted",
        "prior_h1_result_accepted",
        "prior_cache_or_resume_accepted",
        "full_arms",
        "independent_canary_arms",
    }
    if set(parameters) != expected_parameter_keys:
        raise ConfirmationError("tune identity invocation parameter surface is not exact")
    experiment_extras = set(experiment) - set(parameters)
    if experiment_extras != {"design_digest", "runtime_seconds", "tune_market_days"}:
        raise ConfirmationError("tune result experiment fields differ from bound invocation")
    if _canonical_json({key: experiment.get(key) for key in parameters}) != _canonical_json(
        parameters
    ):
        raise ConfirmationError("tune result parameters differ from bound invocation")
    if _digest(parameters) != experiment.get("design_digest"):
        raise ConfirmationError("tune design digest does not recompute from bound invocation")
    if not isinstance(experiment.get("runtime_seconds"), (int, float)) or float(
        experiment["runtime_seconds"]
    ) < 0.0:
        raise ConfirmationError("tune runtime is invalid")
    if int(experiment.get("tune_market_days") or -1) != EXPECTED_TUNE_ENTRY_COUNT:
        raise ConfirmationError("tune market-day count differs from literal corpus")

    repo_root = Path(str(parameters["repo_root"])).resolve(strict=True)
    if (
        identity.get("closure_name") != TUNE_PROFILE
        or Path(str(identity.get("base_root") or "")).resolve(strict=False) != repo_root
        or Path(str(invocation.get("cwd") or "")).resolve(strict=False) != repo_root
        or Path(str(parameters["generation_dir"])).resolve(strict=False)
        != generation.resolve(strict=True)
    ):
        raise ConfirmationError("tune identity base, cwd, profile, or generation path differs")
    cli_fields = (
        ("--repo-root", "repo_root"),
        ("--mirror-data-root", "mirror_data_root"),
        ("--staged-data-root", "staged_data_root"),
        ("--snapshots-root", "snapshots_root"),
        ("--tune-corpus", "tune_corpus"),
        ("--tune-dates-file", "tune_dates_file"),
        ("--generation-dir", "generation_dir"),
    )
    expected_argv_tail = []
    for flag, key in cli_fields:
        expected_argv_tail.extend(
            [flag, str(Path(str(parameters[key])).resolve(strict=False))]
        )
    argv = invocation.get("argv") or []
    if not isinstance(argv, list) or argv[1:] != expected_argv_tail:
        raise ConfirmationError("tune identity argv is not the exact cold-run CLI")

    rows = identity.get("bindings") or []
    bindings = {str(row.get("label") or ""): row for row in rows}
    if len(bindings) != len(rows):
        raise ConfirmationError("tune identity binding labels are duplicated")
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
    if not required_paths <= set(bindings) or not required_trees <= set(bindings):
        raise ConfirmationError("tune identity lacks required source/contract bindings")
    corpus_binding = bindings["partition_corpus"]
    dates_binding = bindings["contract:tune_dates"]
    terminal = result.get("terminal_seals") or {}
    if (
        corpus_binding.get("state") != "file"
        or corpus_binding.get("sha256") != EXPECTED_TUNE_CORPUS_FILE_SHA256
        or _bound_absolute(corpus_binding.get("path"), repo_root)
        != Path(str(parameters["tune_corpus"])).resolve(strict=True)
        or dates_binding.get("state") != "file"
        or dates_binding.get("sha256") != EXPECTED_TUNE_DATES_FILE_SHA256
        or _bound_absolute(dates_binding.get("path"), repo_root)
        != Path(str(parameters["tune_dates_file"])).resolve(strict=True)
    ):
        raise ConfirmationError("tune identity corpus/date bindings differ from terminal pins")
    shim_contracts = {
        "contract:sitecustomize": (repo_root / "sitecustomize.py", "sitecustomize"),
        "contract:weather_import_shim": (
            repo_root / "weather" / "__init__.py",
            "weather_import_shim",
        ),
    }
    for label, (path, seal_name) in shim_contracts.items():
        row = bindings[label]
        if (
            row.get("state") != "file"
            or _bound_absolute(row.get("path"), repo_root) != path.resolve(strict=True)
            or row.get("sha256") != (terminal.get(seal_name) or {}).get("sha256")
        ):
            raise ConfirmationError(f"tune identity shim binding is invalid: {label}")
    for label in ("release_pointer_absent:1", "release_pointer_absent:2"):
        row = bindings[label]
        if row.get("expectation") != "absent" or row.get("state") != "absent":
            raise ConfirmationError("tune identity does not prove absent release pointers")
    tree_roots = {
        "canonical_source": repo_root / "src" / "weather",
        "artifact_graph": repo_root / "artifacts",
        "configuration_graph": repo_root / "config",
    }
    for label, root in tree_roots.items():
        row = bindings[label]
        if (
            row.get("state") != "directory"
            or int(row.get("file_count") or 0) <= 0
            or _bound_absolute(row.get("root"), repo_root) != root.resolve(strict=True)
        ):
            raise ConfirmationError(f"tune identity tree binding is invalid: {label}")
    for prefix, expected in (
        ("snapshot_tree:", EXPECTED_TUNE_ENTRY_COUNT),
        ("captured_replay:", EXPECTED_TUNE_ENTRY_COUNT),
        ("reconstructed_replay:", EXPECTED_TUNE_ENTRY_COUNT),
        ("snapshot_tape_jsonl:", EXPECTED_TUNE_ENTRY_COUNT),
        ("snapshot_tape_long:", EXPECTED_TUNE_ENTRY_COUNT),
        ("wu_daily:", len(REGISTRY)),
        ("wu_hourly:", len(REGISTRY)),
    ):
        observed = [row for label, row in bindings.items() if label.startswith(prefix)]
        if len(observed) != expected:
            raise ConfirmationError(f"tune identity closure count differs: {prefix}")
        if prefix == "reconstructed_replay:":
            valid_states = {"file", "absent"}
        elif prefix in {"snapshot_tree:", "wu_hourly:"}:
            valid_states = {"directory"}
        else:
            valid_states = {"file"}
        if any(row.get("state") not in valid_states for row in observed):
            raise ConfirmationError(f"tune identity binding state differs: {prefix}")

    environment = identity.get("environment") or {}
    selection = environment.get("selection") or {}
    expected_imports = set(DEFAULT_IMPORT_NAMES) | {
        "weather.reporting.research.ordinal_smoothing_physical_replay_gen2",
        "weather.reporting.research.research_generation",
        "weather.release_serving",
    }
    selected_imports = set(selection.get("import_names") or [])
    observed_imports = {
        str(row.get("name") or "") for row in environment.get("imports") or []
    }
    if (
        selection.get("include_packages") is not True
        or not environment.get("packages")
        or "WEATHER_" not in set(selection.get("env_prefixes") or [])
        or expected_imports != selected_imports
        or selected_imports != observed_imports
    ):
        raise ConfirmationError("tune identity package/import/environment closure is invalid")
    source_root = (repo_root / "src" / "weather").resolve(strict=True)
    shim_root = (repo_root / "weather").resolve(strict=True)
    for row in environment.get("imports") or []:
        name = str(row.get("name") or "")
        if not name.startswith("weather"):
            continue
        resolved = _bound_absolute(row.get("resolved_file"), repo_root)
        allowed = False
        for root in (source_root, shim_root):
            try:
                resolved.relative_to(root)
                allowed = True
            except ValueError:
                pass
        if not allowed:
            raise ConfirmationError(f"tune weather import escapes bound source: {name}")
    runtime = environment.get("runtime") or {}
    python_binding = bindings["contract:python_executable"]
    sys_path = {
        Path(str(row.get("resolved") or "")).resolve(strict=False)
        for row in runtime.get("sys_path") or []
    }
    if (
        python_binding.get("state") != "file"
        or _bound_absolute(python_binding.get("path"), repo_root)
        != Path(str(runtime.get("executable") or "")).resolve(strict=True)
        or repo_root not in sys_path
        or (repo_root / "src").resolve(strict=True) not in sys_path
    ):
        raise ConfirmationError("tune identity runtime/python/sys.path closure is invalid")
    return {
        "status": "PASS",
        "binding_count": len(bindings),
        "package_count": len(environment.get("packages") or []),
        "import_count": len(observed_imports),
        "design_digest": experiment.get("design_digest"),
        "generation_dir": str(generation.resolve(strict=True)),
    }


def _validate_tune_generation(
    generation: Path, *, verify_all_outputs: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    complete_path = generation / COMPLETE_NAME
    result_path = generation / TUNE_RESULT_NAME
    commit, commit_receipt = _stable_json(complete_path)
    result, result_receipt = _stable_json(result_path)
    if (
        commit.get("schema_version") != TUNE_GENERATION_SCHEMA_VERSION
        or commit.get("status") != "COMPLETE"
        or commit.get("research_only") is not True
        or commit.get("serving_or_release_authorization") is not False
        or commit.get("multi_leaf_atomic_transaction_claimed") is not False
        or commit.get("commit_marker_semantics")
        != "COMPLETE.json is the sole final commit marker"
        or result.get("schema_version") != TUNE_SCHEMA_VERSION
        or result.get("status") != "COMPLETE"
    ):
        raise ConfirmationError("tune generation/result schema or status is invalid")
    execution = commit.get("execution_identity") or {}
    if (
        execution.get("start_digest") != execution.get("completion_digest")
        or execution.get("identical_full_manifest") is not True
    ):
        raise ConfirmationError("tune generation execution closure is not complete")
    result_execution = result.get("execution_identity") or {}
    validated_start, validated_completion = assert_serialized_completion_matches(
        result_execution.get("start") or {}, result_execution.get("completion") or {}
    )
    if validated_start.identity_digest != execution.get("start_digest"):
        raise ConfirmationError("tune result and generation commit identities differ")
    outputs = commit.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ConfirmationError("tune generation has no committed output inventory")
    output_names = [str(row.get("name") or "") for row in outputs if isinstance(row, dict)]
    if len(output_names) != len(outputs) or len(output_names) != len(set(output_names)):
        raise ConfirmationError("tune generation output inventory is malformed or duplicated")
    expected_cache_names = {
        "cache/tune-fresh-w0.json",
        "cache/tune-fresh-w0-canary.json",
        *{
            "cache/tune-physical-c-" + f"{anchor:.2f}".replace(".", "p") + ".json"
            for anchor in PHYSICAL_C_SIGMA_ANCHORS
        },
    }
    expected_output_names = expected_cache_names | {TUNE_RESULT_NAME, TUNE_REPORT_NAME}
    if set(output_names) != expected_output_names:
        raise ConfirmationError("tune generation does not contain the exact fixed leaves")
    output_index = {str(row["name"]): row for row in outputs}
    for name, row in output_index.items():
        if (
            set(row) != {"name", "sha256", "size_bytes"}
            or len(str(row.get("sha256") or "")) != 64
            or any(
                character not in "0123456789abcdef"
                for character in str(row.get("sha256") or "")
            )
            or isinstance(row.get("size_bytes"), bool)
            or not isinstance(row.get("size_bytes"), int)
            or int(row["size_bytes"]) <= 0
            or Path(name).is_absolute()
            or ".." in Path(name).parts
        ):
            raise ConfirmationError(f"tune generation output receipt is invalid: {name}")
    expected_result = output_index.get(TUNE_RESULT_NAME) or {}
    if (
        expected_result.get("sha256") != result_receipt["sha256"]
        or int(expected_result.get("size_bytes") or -1) != result_receipt["size_bytes"]
    ):
        raise ConfirmationError("tune result hash does not match COMPLETE.json")
    if verify_all_outputs:
        actual_names = set()
        for path in generation.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(generation).as_posix()
            if relative != COMPLETE_NAME:
                actual_names.add(relative)
        if actual_names != set(output_index):
            raise ConfirmationError("tune generation fixed leaves differ from COMPLETE.json")
        for name, expected in output_index.items():
            path = (generation / Path(name)).resolve(strict=True)
            if not _is_within(path, generation):
                raise ConfirmationError(f"tune generation output escapes root: {name}")
            _, observed = _stable_file(path, capture=False)
            if (
                observed["sha256"] != expected.get("sha256")
                or observed["size_bytes"] != int(expected.get("size_bytes") or -1)
            ):
                raise ConfirmationError(f"tune generation output hash mismatch: {name}")

    def pass_gate(value: Any) -> bool:
        return (
            isinstance(value, Mapping)
            and value.get("status") == "PASS"
            and value.get("blockers") == []
        )

    if (
        result.get("disposition") != "FROZEN_FOR_ONE_SHOT_STRICT_CONFIRMATION"
        or result.get("research_only") is not True
        or result.get("promotion_authorized") is not False
        or result.get("serving_changed") is not False
        or result.get("holdout_opened") is not False
        or result.get("fresh_panel_opened") is not False
        or result.get("prior_h1_result_or_cache_used") is not False
        or result.get("model_graph") != RESEARCH_GRAPH_KIND
        or result.get("active_or_current_production_claimed") is not False
        or result.get("technical_blockers") != []
        or result_execution.get("identical_full_manifest") is not True
        or not pass_gate(result.get("profile_gate"))
        or not pass_gate(result.get("baseline_gate"))
        or not pass_gate(result.get("canary_gate"))
    ):
        raise ConfirmationError("tune result safety flags or primary gates are invalid")
    lineage = result.get("lineage") or {}
    generation_contract = result.get("generation_contract") or {}
    pointer_states = lineage.get("current_release_pointers") or []
    if (
        lineage.get("model_graph") != RESEARCH_GRAPH_KIND
        or lineage.get("execution_identity_digest") != validated_start.identity_digest
        or lineage.get("active_or_current_production_claimed") is not False
        or len(pointer_states) != 2
        or any(row.get("state") != "absent" for row in pointer_states)
        or generation_contract.get("complete_marker") != COMPLETE_NAME
        or generation_contract.get("multi_leaf_atomic_transaction_claimed") is not False
        or generation_contract.get("prior_generation_reuse") is not False
    ):
        raise ConfirmationError("tune lineage or generation contract is invalid")
    arm_gates = result.get("arm_gates") or {}
    expected_arm_keys = {str(anchor) for anchor in PHYSICAL_C_SIGMA_ANCHORS}
    if set(arm_gates) != expected_arm_keys or any(
        not pass_gate(arm_gates[key]) for key in expected_arm_keys
    ):
        raise ConfirmationError("tune result does not contain five passing arm gates")

    experiment = result.get("experiment") or {}
    if (
        experiment.get("profile") != TUNE_PROFILE
        or experiment.get("schema_version") != TUNE_SCHEMA_VERSION
        or experiment.get("model_graph") != RESEARCH_GRAPH_KIND
        or experiment.get("research_only") is not True
        or experiment.get("active_or_current_production_claimed") is not False
        or tuple(experiment.get("tune_dates") or ()) != EXPECTED_TUNE_DATES
        or experiment.get("tune_dates_file_sha256")
        != EXPECTED_TUNE_DATES_FILE_SHA256
        or experiment.get("tune_corpus_file_sha256")
        != EXPECTED_TUNE_CORPUS_FILE_SHA256
        or experiment.get("tune_corpus_hash") != EXPECTED_TUNE_CORPUS_HASH
        or int(experiment.get("tune_corpus_entry_count") or -1)
        != EXPECTED_TUNE_ENTRY_COUNT
        or tuple(experiment.get("physical_c_sigma_anchors") or ())
        != tuple(PHYSICAL_C_SIGMA_ANCHORS)
        or experiment.get("fresh_manifest_accepted") is not False
        or experiment.get("holdout_accepted") is not False
        or experiment.get("prior_h1_result_accepted") is not False
        or experiment.get("prior_cache_or_resume_accepted") is not False
        or int(experiment.get("full_arms") or -1) != 6
        or int(experiment.get("independent_canary_arms") or -1) != 1
    ):
        raise ConfirmationError("tune invocation parameters differ from the sealed design")
    identity_semantics = _validate_tune_identity_semantics(
        validated_start, generation=generation, result=result
    )

    summaries = result.get("summaries") or {}
    if set(summaries) != set(UNITS):
        raise ConfirmationError("tune summaries do not contain exactly C and F")
    for unit in UNITS:
        rows = summaries.get(unit)
        if not isinstance(rows, list) or len(rows) != len(PHYSICAL_C_SIGMA_ANCHORS):
            raise ConfirmationError(f"tune summaries have an invalid {unit} grid")
        anchors = {float(row.get("physical_c_sigma")) for row in rows}
        if anchors != set(PHYSICAL_C_SIGMA_ANCHORS) or any(
            str(row.get("unit") or "").upper() != unit
            or float(row.get("native_sigma"))
            != native_sigma(float(row.get("physical_c_sigma")), unit)
            or float(row.get("blend_weight")) != FIXED_BLEND_WEIGHT
            for row in rows
        ):
            raise ConfirmationError(f"tune summaries have an invalid {unit} mapping")
    try:
        recomputed_selected, recomputed_selection = select_family_sigmas(summaries)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfirmationError(f"tune selection cannot be recomputed: {exc}") from exc
    selected = result.get("selected_physical_c_sigmas") or {}
    if (
        _canonical_json(selected) != _canonical_json(recomputed_selected)
        or _canonical_json(result.get("selection") or {})
        != _canonical_json(recomputed_selection)
    ):
        raise ConfirmationError("tune selected pair does not reproduce from summaries")
    frozen = result.get("frozen_candidate") or {}
    expected_native = {
        unit: native_sigma(float(selected[unit]), unit) for unit in UNITS if unit in selected
    }
    if (
        set(selected) != set(UNITS)
        or any(float(selected[unit]) not in PHYSICAL_C_SIGMA_ANCHORS for unit in UNITS)
        or frozen.get("status") != "FROZEN"
        or _canonical_json(frozen.get("physical_c_sigma_by_family") or {})
        != _canonical_json(selected)
        or _canonical_json(frozen.get("native_sigma_by_family") or {})
        != _canonical_json(expected_native)
        or float(frozen.get("blend_weight") or -1.0) != FIXED_BLEND_WEIGHT
        or frozen.get("selection_uses_tune_only") is not True
        or frozen.get("confirmation_runs_completed") != 0
        or frozen.get("one_shot_confirmation_authorized") is not True
        or frozen.get("promotion_authorized") is not False
    ):
        raise ConfirmationError("tune result does not expose one eligible frozen family pair")

    terminal_seals = result.get("terminal_seals") or {}
    design_seal = terminal_seals.get("design") or {}
    if (
        _canonical_json(commit.get("terminal_seals") or {})
        != _canonical_json(terminal_seals)
        or set(terminal_seals)
        != {"tune_corpus", "tune_dates", "sitecustomize", "weather_import_shim", "design"}
        or (terminal_seals.get("tune_corpus") or {}).get("sha256")
        != EXPECTED_TUNE_CORPUS_FILE_SHA256
        or (terminal_seals.get("tune_dates") or {}).get("sha256")
        != EXPECTED_TUNE_DATES_FILE_SHA256
        or design_seal.get("profile") != TUNE_PROFILE
        or design_seal.get("sha256") != experiment.get("design_digest")
    ):
        raise ConfirmationError("tune result and commit terminal seals differ")
    metadata = commit.get("metadata") or {}
    if (
        set(metadata)
        != {
            "profile",
            "model_graph",
            "result",
            "report",
            "selected_physical_c_sigmas",
            "one_shot_confirmation_authorized",
        }
        or metadata.get("profile") != TUNE_PROFILE
        or metadata.get("model_graph") != RESEARCH_GRAPH_KIND
        or metadata.get("result") != TUNE_RESULT_NAME
        or metadata.get("report") != TUNE_REPORT_NAME
        or _canonical_json(metadata.get("selected_physical_c_sigmas") or {})
        != _canonical_json(selected)
        or metadata.get("one_shot_confirmation_authorized") is not True
    ):
        raise ConfirmationError("tune COMPLETE metadata differs from frozen result")

    cache_records = result.get("cache_records")
    if not isinstance(cache_records, list) or len(cache_records) != len(expected_cache_names):
        raise ConfirmationError("tune result cache receipt inventory is incomplete")
    cache_index = {str(row.get("name") or ""): row for row in cache_records}
    if len(cache_index) != len(cache_records) or set(cache_index) != expected_cache_names:
        raise ConfirmationError("tune result cache receipt inventory differs from outputs")
    start_digest = validated_start.identity_digest
    for name, record in cache_index.items():
        output = output_index[name]
        identity_gates = record.get("identity_gates") or {}
        if (
            record.get("sha256") != output.get("sha256")
            or record.get("size_bytes") != output.get("size_bytes")
            or identity_gates.get("identical_full_manifest") is not True
            or identity_gates.get("pre_arm_digest") != start_digest
            or identity_gates.get("post_arm_digest") != start_digest
        ):
            raise ConfirmationError(f"tune cache receipt is not closure-bound: {name}")
        assert_serialized_completion_matches(
            identity_gates.get("pre_cache") or {}, identity_gates.get("post_cache") or {}
        )
    baseline_sha = cache_index["cache/tune-fresh-w0.json"]["sha256"]
    if (result.get("canary_gate") or {}).get("cache_sha256") != cache_index[
        "cache/tune-fresh-w0-canary.json"
    ]["sha256"]:
        raise ConfirmationError("tune canary gate is not bound to its committed cache")
    for anchor in PHYSICAL_C_SIGMA_ANCHORS:
        name = "cache/tune-physical-c-" + f"{anchor:.2f}".replace(".", "p") + ".json"
        if (arm_gates[str(anchor)] or {}).get("cache_sha256") != cache_index[name]["sha256"]:
            raise ConfirmationError("tune arm gate is not bound to its committed cache")
        if not cache_index[name].get("fingerprint"):
            raise ConfirmationError("tune candidate cache fingerprint is absent")
    if not baseline_sha:
        raise ConfirmationError("tune fresh W0 cache seal is absent")
    return result, {
        "complete": commit_receipt,
        "result": result_receipt,
        "selected_physical_c_sigmas": {unit: float(selected[unit]) for unit in UNITS},
        "identity_semantics": identity_semantics,
    }


def _strict_manifest(
    manifest_path: Path, snapshots_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest, receipt = _stable_json(manifest_path)
    materialization = manifest.get("materialization") or {}
    if (
        receipt["sha256"] != EXPECTED_FRESH_MANIFEST_SHA256
        or manifest.get("schema_version") != "promotion_corpus_v0.1"
        or manifest.get("corpus_hash") != EXPECTED_FRESH_CORPUS_HASH
        or materialization.get("schema_version")
        != "ordinal_smoothing_literal_panel_v0.1"
        or materialization.get("kind") != "fresh"
        or tuple(materialization.get("dates") or ()) != STRICT_DATES
        or int(materialization.get("entry_count") or -1) != len(STRICT_DATES) * len(REGISTRY)
        or materialization.get("source_manifest_sha256")
        != EXPECTED_FRESH_SOURCE_MANIFEST_SHA256
        or materialization.get("source_corpus_hash")
        != EXPECTED_FRESH_SOURCE_CORPUS_HASH
        or int(materialization.get("excluded_entry_count") or -1) <= 0
        or manifest.get("skipped") != []
    ):
        raise ConfirmationError("fresh manifest is not the preregistered terminal pin")
    entries = [dict(entry) for entry in manifest.get("entries") or []]
    keys = [(entry.get("target_date"), entry.get("market_id")) for entry in entries]
    expected_keys = {(date, market_id) for date in STRICT_DATES for market_id in REGISTRY}
    if len(entries) != len(expected_keys) or set(keys) != expected_keys or len(keys) != len(set(keys)):
        raise ConfirmationError("fresh manifest is not the exact 5x12 strict panel")
    for entry in entries:
        if str(entry.get("folder_relative_to_snapshots_root") or "") != str(
            entry.get("event_slug") or ""
        ):
            raise ConfirmationError("fresh corpus folder identity differs from event slug")
    audit_rows, verification = audit_manifest_entries(
        manifest, snapshots_root=snapshots_root
    )
    panel, strict_eligible, _ = build_date_panel(STRICT_DATES, audit_rows)
    if (
        tuple(strict_eligible) != STRICT_DATES
        or verification.get("verification_warning_count") != 0
        or any(not row.get("strict_confirmation_eligible") for row in panel)
    ):
        raise ConfirmationError("fresh panel no longer has exact pins/current identity")
    return manifest, entries, {
        "manifest": receipt,
        "panel": panel,
        "verification": verification,
    }


def _expected_generation_dir(
    tune_generation: Path, tune_complete_sha: str, fresh_manifest_sha: str
) -> Path:
    name = (
        "physical-confirmation-"
        f"{tune_complete_sha[:12]}-{fresh_manifest_sha[:12]}"
    )
    return tune_generation.parent / name


def validate_paths(args: argparse.Namespace) -> dict[str, Path]:
    paths = {
        name: Path(value).expanduser().resolve(strict=True)
        for name, value in {
            "repo_root": args.repo_root,
            "mirror_data_root": args.mirror_data_root,
            "staged_data_root": args.staged_data_root,
            "snapshots_root": args.snapshots_root,
            "tune_generation": args.tune_generation_dir,
            "fresh_corpus": args.fresh_corpus,
        }.items()
    }
    for name in ("repo_root", "mirror_data_root", "staged_data_root", "snapshots_root", "tune_generation"):
        if not paths[name].is_dir():
            raise ConfirmationError(f"required directory is missing: {name}")
    if not paths["fresh_corpus"].is_file():
        raise ConfirmationError("fresh manifest is missing")
    if Path.cwd().resolve() != paths["repo_root"]:
        raise ConfirmationError("confirmation must run from the bound repository root")
    if not _is_within(paths["snapshots_root"], paths["mirror_data_root"]):
        raise ConfirmationError("snapshots_root escapes mirror_data_root")
    if not _is_within(paths["snapshots_root"], paths["staged_data_root"]):
        raise ConfirmationError("snapshots_root escapes staged_data_root")
    _, complete_receipt = _stable_file(
        paths["tune_generation"] / COMPLETE_NAME, capture=False
    )
    _, manifest_receipt = _stable_file(paths["fresh_corpus"], capture=False)
    expected = _expected_generation_dir(
        paths["tune_generation"],
        complete_receipt["sha256"],
        manifest_receipt["sha256"],
    )
    expected = Path(os.path.abspath(os.fspath(expected)))
    supplied = Path(
        os.path.abspath(os.fspath(Path(args.generation_dir).expanduser()))
    )
    if supplied != expected:
        raise ConfirmationError(
            f"one-shot generation path is deterministic; expected {expected}"
        )
    attempt_marker = supplied.with_name(supplied.name + ".ATTEMPT.json")
    if os.path.lexists(attempt_marker):
        raise ConfirmationError("one-shot confirmation authorization is already consumed")
    if os.path.lexists(supplied):
        raise ConfirmationError("one-shot confirmation generation already exists")
    for root in (paths["mirror_data_root"], paths["staged_data_root"]):
        if _is_within(supplied, root):
            raise ConfirmationError("confirmation output resolves inside read-only data")
    paths["generation_dir"] = supplied
    paths["attempt_marker"] = attempt_marker
    return paths


def _consume_one_shot_authorization(
    paths: Mapping[str, Path], tune_receipts: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "one_shot_confirmation_attempt",
        "status": "AUTHORIZATION_CONSUMED",
        "research_only": True,
        "promotion_authorized": False,
        "serving_changed": False,
        "generation_dir": str(paths["generation_dir"]),
        "tune_generation": str(paths["tune_generation"]),
        "tune_complete_sha256": (tune_receipts.get("complete") or {}).get("sha256"),
        "tune_result_sha256": (tune_receipts.get("result") or {}).get("sha256"),
        "fresh_corpus": str(paths["fresh_corpus"]),
        "fresh_corpus_sha256": EXPECTED_FRESH_MANIFEST_SHA256,
        "strict_dates": list(STRICT_DATES),
        "semantics": (
            "persistent create-if-absent marker; never removed, including failed attempts"
        ),
    }
    atomic_write_json_exclusive(paths["attempt_marker"], payload)
    _, receipt = _stable_file(paths["attempt_marker"], capture=False)
    return {**receipt, "payload": payload}


def _assert_exact_cli(paths: Mapping[str, Path]) -> None:
    fields = (
        ("--repo-root", "repo_root"),
        ("--mirror-data-root", "mirror_data_root"),
        ("--staged-data-root", "staged_data_root"),
        ("--snapshots-root", "snapshots_root"),
        ("--tune-generation-dir", "tune_generation"),
        ("--fresh-corpus", "fresh_corpus"),
        ("--generation-dir", "generation_dir"),
    )
    expected = []
    for flag, key in fields:
        expected.extend((flag, str(paths[key])))
    if sys.argv[1:] != expected:
        raise ConfirmationError("confirmation requires the exact ordered canonical CLI")


def _run_parameters(
    paths: Mapping[str, Path],
    selected: Mapping[str, float],
    tune_receipts: Mapping[str, Any],
    attempt_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "schema_version": SCHEMA_VERSION,
        "model_graph": RESEARCH_GRAPH_KIND,
        "research_only": True,
        "repo_root": str(paths["repo_root"]),
        "mirror_data_root": str(paths["mirror_data_root"]),
        "staged_data_root": str(paths["staged_data_root"]),
        "snapshots_root": str(paths["snapshots_root"]),
        "tune_generation": str(paths["tune_generation"]),
        "fresh_corpus": str(paths["fresh_corpus"]),
        "generation_dir": str(paths["generation_dir"]),
        "attempt_marker": str(paths["attempt_marker"]),
        "attempt_marker_sha256": attempt_receipt.get("sha256"),
        "strict_dates": list(STRICT_DATES),
        "required_market_ids": sorted(REGISTRY),
        "selected_physical_c_sigma_by_family": dict(selected),
        "selected_native_sigma_by_family": {
            unit: native_sigma(selected[unit], unit) for unit in UNITS
        },
        "blend_weight": FIXED_BLEND_WEIGHT,
        "arms": ["fresh_w0", "single_mixed_family_candidate"],
        "alternative_candidates_or_reselection": False,
        "fleet_date_weighting": "equal",
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_unit": "paired_fleet_date",
        "tune_complete_sha256": (tune_receipts.get("complete") or {}).get("sha256"),
        "tune_result_sha256": (tune_receipts.get("result") or {}).get("sha256"),
        "fresh_manifest_sha256": EXPECTED_FRESH_MANIFEST_SHA256,
        "fresh_corpus_hash": EXPECTED_FRESH_CORPUS_HASH,
        "fresh_source_manifest_sha256": EXPECTED_FRESH_SOURCE_MANIFEST_SHA256,
        "fresh_source_corpus_hash": EXPECTED_FRESH_SOURCE_CORPUS_HASH,
    }


def _assert_confirmation_profile(
    spec: ClosureSpec, entries: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    path_labels = {binding.label for binding in spec.path_bindings}
    tree_labels = {binding.label for binding in spec.tree_bindings}
    required_paths = {
        "partition_corpus",
        "contract:python_executable",
        "contract:sitecustomize",
        "contract:weather_import_shim",
        "contract:one_shot_attempt",
        "contract:tune_complete",
        "contract:tune_result",
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
    if len(entries) != len(STRICT_DATES) * len(REGISTRY):
        blockers.append("confirmation corpus is not the exact 5x12 panel")
    invocation = spec.invocation.run_parameters
    if (
        tuple(invocation.get("strict_dates") or ()) != STRICT_DATES
        or invocation.get("fresh_manifest_sha256") != EXPECTED_FRESH_MANIFEST_SHA256
        or invocation.get("fresh_corpus_hash") != EXPECTED_FRESH_CORPUS_HASH
        or invocation.get("fresh_source_manifest_sha256")
        != EXPECTED_FRESH_SOURCE_MANIFEST_SHA256
        or invocation.get("fresh_source_corpus_hash")
        != EXPECTED_FRESH_SOURCE_CORPUS_HASH
        or not invocation.get("attempt_marker_sha256")
    ):
        blockers.append("fresh literal-panel seals differ from preregistration")
    if blockers:
        raise ConfirmationError("strict closure profile failed: " + "; ".join(blockers))
    return {
        "status": "PASS",
        "path_bindings": len(path_labels),
        "tree_bindings": len(tree_labels),
        "corpus_entries": len(entries),
        "market_count": market_count,
        "blockers": [],
    }


def _strict_replay_gate(arm: Mapping[str, Any]) -> dict[str, Any]:
    mass = mass_gate(arm.get("distribution_rows") or [])
    alignment = alignment_gate(arm.get("rows") or [], arm.get("rows") or [])
    blockers = (
        list((arm.get("replay") or {}).get("blockers") or [])
        + list(mass.get("blockers") or [])
        + list(alignment.get("blockers") or [])
    )
    date_markets: dict[str, set[str]] = {}
    for row in arm.get("distribution_rows") or []:
        date_markets.setdefault(str(row.get("target_date") or ""), set()).add(
            str(row.get("market_id") or "")
        )
    if tuple(sorted(date_markets)) != STRICT_DATES:
        blockers.append("replay distributions do not exactly cover strict dates")
    for date in STRICT_DATES:
        if date_markets.get(date) != set(REGISTRY):
            blockers.append(f"replay date is not exact 12-market panel: {date}")
    if blockers:
        raise ConfirmationError("strict W0 replay gate failed: " + "; ".join(blockers))
    return {
        "status": "PASS",
        "mass": mass,
        "alignment": alignment,
        "date_market_counts": {date: len(date_markets[date]) for date in STRICT_DATES},
        "replay": arm.get("replay") or {},
        "blockers": [],
    }


def _candidate_analysis(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any], selected: Mapping[str, float]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if BOOTSTRAP_REPLICATES != 10_000:
        raise ConfirmationError("confirmation bootstrap must remain fixed at 10,000 replicates")
    mass = mass_gate(candidate.get("distribution_rows") or [])
    alignment = alignment_gate(baseline.get("rows") or [], candidate.get("rows") or [])
    effect = scope_effect_audit(
        baseline.get("distribution_rows") or [], candidate.get("distribution_rows") or []
    )
    blockers = (
        list((candidate.get("replay") or {}).get("blockers") or [])
        + list(mass.get("blockers") or [])
        + list(alignment.get("blockers") or [])
        + list(effect.get("blockers") or [])
    )
    summaries = {}
    dispositions = {}
    for unit in UNITS:
        daily = paired_fleet_date_rows(
            baseline.get("rows") or [], candidate.get("rows") or [], unit
        )
        raw = paired_summary(
            daily,
            split="strict-fresh-confirmation",
            unit=unit,
            weight=float(selected[unit]),
        )
        summary = dict(raw)
        summary["physical_c_sigma"] = float(selected[unit])
        summary["native_sigma"] = native_sigma(float(selected[unit]), unit)
        summary["blend_weight"] = FIXED_BLEND_WEIGHT
        summary["mean_brier_delta_vs_w0"] = summary.pop("mean_brier_delta")
        summary["mean_logloss_delta_vs_w0"] = summary.pop("mean_logloss_delta")
        if summary["fleet_dates"] != len(STRICT_DATES):
            blockers.append(f"{unit} summary does not contain all five fleet dates")
        means_negative = (
            summary["mean_brier_delta_vs_w0"] is not None
            and summary["mean_logloss_delta_vs_w0"] is not None
            and summary["mean_brier_delta_vs_w0"] < 0.0
            and summary["mean_logloss_delta_vs_w0"] < 0.0
        )
        brier_ci = summary["brier_cluster_bootstrap_95ci"]
        log_ci = summary["logloss_cluster_bootstrap_95ci"]
        if means_negative and brier_ci["high"] < 0.0 and log_ci["high"] < 0.0:
            disposition = "SUPPORTED"
        elif means_negative:
            disposition = "DIRECTIONAL_ONLY"
        else:
            disposition = "NOT_SUPPORTED"
        summary["disposition"] = disposition
        summary["low_power_five_date_panel"] = True
        summaries[unit] = summary
        dispositions[unit] = disposition
    if blockers:
        raise ConfirmationError("candidate gate failed: " + "; ".join(blockers))
    return {
        "status": "PASS",
        "mass": mass,
        "alignment": alignment,
        "scope_effect": effect,
        "replay": candidate.get("replay") or {},
        "blockers": [],
    }, summaries, dispositions


def _publish_cache(
    *,
    generation: ResearchGeneration,
    name: str,
    arm: Mapping[str, Any],
    arm_contract: Mapping[str, Any],
    gate: Mapping[str, Any],
    start,
    completion,
    design_digest: str,
    fresh_w0_sha256: str | None,
) -> dict[str, Any]:
    fingerprint = _digest(
        {
            "schema_version": SCHEMA_VERSION,
            "profile": PROFILE,
            "arm_contract": dict(arm_contract),
            "execution_identity_digest": start.identity_digest,
            "design_digest": design_digest,
            "fresh_w0_cache_sha256": fresh_w0_sha256,
            "model_graph": RESEARCH_GRAPH_KIND,
        }
    )
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "one_shot_confirmation_arm_cache",
        "fingerprint": fingerprint,
        "arm_contract": dict(arm_contract),
        "gate": dict(gate),
        "execution_identity": {
            "start": start.to_dict(),
            "completion": completion.to_dict(),
            "identical_full_manifest": True,
        },
        "arm": dict(arm),
    }
    assert_serialized_completion_matches(
        envelope["execution_identity"]["start"],
        envelope["execution_identity"]["completion"],
    )
    receipt = generation.publish_json(name, envelope, compact=True)
    if receipt["size_bytes"] > MAX_CACHE_BYTES:
        raise ConfirmationError(f"confirmation cache exceeds fixed cap: {name}")
    return {
        **receipt,
        "fingerprint": fingerprint,
        "arm_contract": dict(arm_contract),
        "fresh_w0_cache_sha256": fresh_w0_sha256,
    }


def _render_report(payload: Mapping[str, Any]) -> str:
    rows = []
    for unit in UNITS:
        summary = (payload.get("summaries") or {}).get(unit) or {}
        brier_ci = summary.get("brier_cluster_bootstrap_95ci") or {}
        log_ci = summary.get("logloss_cluster_bootstrap_95ci") or {}
        rows.append(
            "| {unit} | {physical:.2f} | {native:.2f} | {brier:+.8f} "
            "[{blow:+.8f}, {bhigh:+.8f}] | {log:+.8f} [{llow:+.8f}, {lhigh:+.8f}] "
            "| {market:+.8f} | {disp} |".format(
                unit=unit,
                physical=float(summary["physical_c_sigma"]),
                native=float(summary["native_sigma"]),
                brier=float(summary["mean_brier_delta_vs_w0"]),
                blow=float(brier_ci["low"]),
                bhigh=float(brier_ci["high"]),
                log=float(summary["mean_logloss_delta_vs_w0"]),
                llow=float(log_ci["low"]),
                lhigh=float(log_ci["high"]),
                market=float(summary["mean_candidate_brier_delta_vs_market"]),
                disp=summary["disposition"],
            )
        )
    return "\n".join(
        [
            "# H1 One-Shot Strict Fresh Confirmation",
            "",
            "The frozen tune-selected mixed-family candidate was replayed exactly once against "
            "a fresh W0 on the preregistered July 15–19 exact 5x12 panel.",
            "",
            "| Unit | Physical C sigma | Native sigma | Brier vs W0 (95% CI) "
            "| Log-loss vs W0 (95% CI) | Brier vs market | Disposition |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            *rows,
            "",
            "Fleet dates are weighted equally. Intervals use the fixed deterministic 10,000-"
            "replicate paired fleet-date bootstrap; paired date signs are in the JSON. "
            "Five dates—especially one C market—are low power.",
            "",
            "SUPPORTED requires both negative means and both 95% CI upper bounds below zero. "
            "Negative means with either interval crossing zero are DIRECTIONAL_ONLY; all other "
            "outcomes are NOT_SUPPORTED. This result does not authorize serving, promotion, or trading.",
            "",
            "`COMPLETE.json` is the sole final commit marker.",
            "",
        ]
    )


def run_confirmation(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = validate_paths(args)
    _assert_exact_cli(paths)
    configure_staged_data_root(paths["staged_data_root"])
    tune_result, tune_receipts = _validate_tune_generation(
        paths["tune_generation"], verify_all_outputs=True
    )
    selected = dict(tune_receipts["selected_physical_c_sigmas"])
    manifest, entries, panel_evidence = _strict_manifest(
        paths["fresh_corpus"], paths["snapshots_root"]
    )
    folders = folders_for_entries(entries, paths["snapshots_root"])
    validate_staged_daily_inputs(entries, paths["staged_data_root"])
    attempt_receipt = _consume_one_shot_authorization(paths, tune_receipts)
    parameters = _run_parameters(paths, selected, tune_receipts, attempt_receipt)
    design_digest = _digest(parameters)
    imports = tuple(
        sorted(
            set(DEFAULT_IMPORT_NAMES)
            | {
                "weather.reporting.research.ordinal_smoothing_fresh_confirmation_audit",
                "weather.reporting.research.ordinal_smoothing_physical_confirmation",
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
        corpus_path=paths["fresh_corpus"],
        entries=entries,
        invocation=InvocationSpec.current(run_parameters=parameters),
        required_contract_files=(
            ("python_executable", Path(sys.executable)),
            ("sitecustomize", paths["repo_root"] / "sitecustomize.py"),
            ("weather_import_shim", paths["repo_root"] / "weather" / "__init__.py"),
            ("one_shot_attempt", paths["attempt_marker"]),
            ("tune_complete", paths["tune_generation"] / COMPLETE_NAME),
            ("tune_result", paths["tune_generation"] / TUNE_RESULT_NAME),
        ),
        environment=EnvironmentSpec(import_names=imports, include_packages=True),
    )
    profile_gate = _assert_confirmation_profile(closure, entries)
    _, sitecustomize_receipt = _stable_file(
        paths["repo_root"] / "sitecustomize.py", capture=False
    )
    _, weather_shim_receipt = _stable_file(
        paths["repo_root"] / "weather" / "__init__.py", capture=False
    )
    terminal_seals = {
        "tune_complete": tune_receipts["complete"],
        "tune_result": tune_receipts["result"],
        "fresh_manifest": panel_evidence["manifest"],
        "one_shot_attempt": attempt_receipt,
        "sitecustomize": sitecustomize_receipt,
        "weather_import_shim": weather_shim_receipt,
        "design": {"profile": PROFILE, "sha256": design_digest},
    }
    started = time.perf_counter()
    builder = ResearchGeneration(
        generation_dir=paths["generation_dir"],
        read_only_roots=(paths["mirror_data_root"], paths["staged_data_root"]),
        commit_schema_version=GENERATION_SCHEMA_VERSION,
    )
    with builder as generation:
        start = capture_execution_identity(closure)
        reloaded_tune, reloaded_receipts = _validate_tune_generation(
            paths["tune_generation"], verify_all_outputs=False
        )
        reloaded_manifest, reloaded_entries, reloaded_panel = _strict_manifest(
            paths["fresh_corpus"], paths["snapshots_root"]
        )
        if (
            _canonical_json(reloaded_tune.get("selected_physical_c_sigmas") or {})
            != _canonical_json(tune_result.get("selected_physical_c_sigmas") or {})
            or reloaded_receipts["complete"]["sha256"]
            != tune_receipts["complete"]["sha256"]
            or _canonical_json(reloaded_manifest) != _canonical_json(manifest)
            or _canonical_json(reloaded_panel["panel"]) != _canonical_json(panel_evidence["panel"])
            or _canonical_json(reloaded_entries) != _canonical_json(entries)
        ):
            raise ConfirmationError("terminal tune/panel inputs changed across start capture")
        recapture_and_assert_unchanged(start, closure, phase="after confirmation input reload")

        pre_w0 = recapture_and_assert_unchanged(start, closure, phase="before fresh W0")
        w0 = run_partition_arm(
            partition="strict-fresh-confirmation",
            arm_name="fresh-w0",
            folders=folders,
            corpus_manifest=manifest,
            staged_data_root=paths["staged_data_root"],
            scratch_output_root=generation.generation_dir,
            physical_c_sigma_by_family=None,
        )
        post_w0 = recapture_and_assert_unchanged(start, closure, phase="after fresh W0")
        w0_gate = _strict_replay_gate(w0)
        pre_w0_cache = recapture_and_assert_unchanged(start, closure, phase="before W0 cache")
        w0_record = _publish_cache(
            generation=generation,
            name="cache/strict-fresh-w0.json",
            arm=w0,
            arm_contract={"kind": "fresh_w0", "dates": list(STRICT_DATES), "blend_weight": 0.0},
            gate=w0_gate,
            start=start,
            completion=post_w0,
            design_digest=design_digest,
            fresh_w0_sha256=None,
        )
        post_w0_cache = recapture_and_assert_unchanged(start, closure, phase="after W0 cache")
        w0_record["identity_gates"] = {
            "pre_arm_digest": pre_w0.identity_digest,
            "post_arm_digest": post_w0.identity_digest,
            "pre_cache": pre_w0_cache.to_dict(),
            "post_cache": post_w0_cache.to_dict(),
            "identical_full_manifest": True,
        }
        assert_serialized_completion_matches(
            w0_record["identity_gates"]["pre_cache"],
            w0_record["identity_gates"]["post_cache"],
        )

        pre_candidate = recapture_and_assert_unchanged(start, closure, phase="before candidate")
        candidate = run_partition_arm(
            partition="strict-fresh-confirmation",
            arm_name="single-mixed-family-candidate",
            folders=folders,
            corpus_manifest=manifest,
            staged_data_root=paths["staged_data_root"],
            scratch_output_root=generation.generation_dir,
            physical_c_sigma_by_family=selected,
        )
        post_candidate = recapture_and_assert_unchanged(start, closure, phase="after candidate")
        candidate_gate, summaries, dispositions = _candidate_analysis(w0, candidate, selected)
        pre_candidate_cache = recapture_and_assert_unchanged(
            start, closure, phase="before candidate cache"
        )
        candidate_record = _publish_cache(
            generation=generation,
            name="cache/strict-fresh-mixed-candidate.json",
            arm=candidate,
            arm_contract={
                "kind": "single_mixed_family_candidate",
                "dates": list(STRICT_DATES),
                "physical_c_sigma_by_family": selected,
                "native_sigma_by_family": {
                    unit: native_sigma(selected[unit], unit) for unit in UNITS
                },
                "blend_weight": FIXED_BLEND_WEIGHT,
                "alternative_or_reselection": False,
            },
            gate=candidate_gate,
            start=start,
            completion=post_candidate,
            design_digest=design_digest,
            fresh_w0_sha256=str(w0_record["sha256"]),
        )
        post_candidate_cache = recapture_and_assert_unchanged(
            start, closure, phase="after candidate cache"
        )
        candidate_record["identity_gates"] = {
            "pre_arm_digest": pre_candidate.identity_digest,
            "post_arm_digest": post_candidate.identity_digest,
            "pre_cache": pre_candidate_cache.to_dict(),
            "post_cache": post_candidate_cache.to_dict(),
            "identical_full_manifest": True,
        }
        assert_serialized_completion_matches(
            candidate_record["identity_gates"]["pre_cache"],
            candidate_record["identity_gates"]["post_cache"],
        )
        candidate = None
        gc.collect()

        completion = recapture_and_assert_unchanged(
            start, closure, phase="after both one-shot confirmation arms"
        )
        assert_serialized_completion_matches(start.to_dict(), completion.to_dict())
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETE",
            "disposition": "ONE_SHOT_STRICT_CONFIRMATION_COMPLETE",
            "research_only": True,
            "promotion_authorized": False,
            "serving_changed": False,
            "model_graph": RESEARCH_GRAPH_KIND,
            "active_or_current_production_claimed": False,
            "experiment": {
                **parameters,
                "design_digest": design_digest,
                "runtime_seconds": time.perf_counter() - started,
                "fresh_market_days": len(entries),
                "low_power_warning": (
                    "Only five fleet dates; C has one market. Do not interpret non-support as equivalence."
                ),
            },
            "terminal_seals": terminal_seals,
            "closure_profile_gate": profile_gate,
            "tune_candidate": {
                "physical_c_sigma_by_family": selected,
                "native_sigma_by_family": {
                    unit: native_sigma(selected[unit], unit) for unit in UNITS
                },
                "reselected_after_fresh_scores": False,
            },
            "strict_panel": panel_evidence,
            "lineage": execution_lineage(start),
            "execution_identity": {
                "start": start.to_dict(),
                "completion": completion.to_dict(),
                "identical_full_manifest": True,
            },
            "w0_gate": w0_gate,
            "candidate_gate": candidate_gate,
            "summaries": summaries,
            "dispositions": dispositions,
            "decision_rule": {
                "SUPPORTED": "both means < 0 and both 95% CI upper bounds < 0",
                "DIRECTIONAL_ONLY": "both means < 0 but at least one 95% CI crosses zero",
                "NOT_SUPPORTED": "otherwise",
            },
            "cache_records": [w0_record, candidate_record],
            "one_shot": {
                "fresh_w0_arms": 1,
                "candidate_arms": 1,
                "alternative_candidates_scored": 0,
                "reselection_performed": False,
                "attempt_marker": attempt_receipt,
            },
            "technical_blockers": [],
        }
        generation.publish_json(RESULT_NAME, payload)
        generation.publish_text(REPORT_NAME, _render_report(payload))
        commit = generation.commit(
            start=start,
            expected_completion=completion,
            terminal_recapture=lambda: recapture_and_assert_unchanged(
                start,
                closure,
                phase=(
                    "confirmation after final output inventory "
                    "immediately before COMPLETE.json"
                ),
            ),
            terminal_seals=terminal_seals,
            extra={
                "profile": PROFILE,
                "model_graph": RESEARCH_GRAPH_KIND,
                "result": RESULT_NAME,
                "report": REPORT_NAME,
                "strict_dates": list(STRICT_DATES),
                "dispositions": dispositions,
                "promotion_authorized": False,
            },
        )
    return payload, commit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--mirror-data-root", required=True)
    parser.add_argument("--staged-data-root", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--tune-generation-dir", required=True)
    parser.add_argument("--fresh-corpus", required=True)
    parser.add_argument("--generation-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        payload, commit = run_confirmation(build_parser().parse_args(argv))
    except (ConfirmationError, ExecutionIdentityError, ResearchGenerationError, ValueError) as exc:
        print(f"strict physical confirmation blocked: {exc}", file=sys.stderr)
        return 2
    print(
        "strict physical confirmation committed: "
        f"dispositions={payload.get('dispositions')} "
        f"identity={(commit.get('execution_identity') or {}).get('start_digest')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
