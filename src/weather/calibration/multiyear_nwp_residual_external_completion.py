"""Complete the sealed no-refit 2026 residual-model external evaluation."""

from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Mapping, Sequence

from weather.calibration import multiyear_nwp_residual as frozen
from weather.calibration import multiyear_nwp_residual_external as prior
from weather.market.market_registry import BUILTIN_SPECS
from weather.operations import wu_outcome_export_contract as export_contract
from weather.sources.daily_summary import native_bucket


AMENDMENT_SCHEMA = "multiyear_nwp_residual_external_completion_amendment_v1"
ATTEMPT_SCHEMA = "multiyear_nwp_residual_external_completion_attempt_v1"
RESULT_SCHEMA = "multiyear_nwp_residual_external_completion_result_v1"
VERIFICATION_SCHEMA = "multiyear_nwp_residual_external_completion_verification_v1"

MISSION_SHA256 = "5824c7123d837f80cb4ffd9c80fb594e058b8b3bcb807557a09e57b10a77b36b"
RESULT_BRANCH = (
    "codex/workstation-multiyear-nwp-residual-external-completion-2026-09-100h"
)
SOURCE_BRANCH = "codex/workstation-wu-outcome-admissible-gap-spec-2026-09-100g"
SOURCE_TIP = "734f14adba7055ba7459db8a9ab4a16983a1b202"
SOURCE_TREE = "1468c089b62e09a09a13006a1936c32787e4c64b"
SOURCE_IMPLEMENTATION = "e47857bad276e767f15baa98ccf0347cf2048ec0"
SOURCE_IMPLEMENTATION_TREE = "e92bd4e4683d925d8bf961bc4dd751cb00322a5a"
SOURCE_TERMINAL_RECEIPT_SHA256 = (
    "61552b4157cbe899cdaef05f12a3161b4b2898960a095c79445a6692d500e0c2"
)
SOURCE_BUNDLE_SHA256 = (
    "0fa455f058c2663e3d8d8ea9d9b66212fe6422ec3aa08f9bf1d0b9a9b9e9f8ef"
)

FROZEN_DESIGN_FILE_SHA256 = prior.FROZEN_DESIGN_FILE_SHA256
FROZEN_DESIGN_SHA256 = prior.FROZEN_DESIGN_SHA256
FROZEN_MODULE_SHA256 = prior.FROZEN_MODULE_SHA256
FROZEN_MODEL_SHA256 = prior.FROZEN_MODEL_SHA256
FROZEN_FEATURE_ORDER_SHA256 = {
    "baseline": "4e35fe7e2d44d37e22ff02b2b681c2de840a487d1eeddef7cace58b2852bf603",
    "challenger": "5839aa7373cdd78d4d54cccfa27d7d8b42ffb8acc5d80e08135561335fa2c3fb",
    "combined": "3d2b3fa4a9b58f7881b80609234904f54fd2db05b21c1f96aac10b5389859bbd",
}
FROZEN_AMENDMENT_FILE_SHA256 = (
    "866d7537440c6d1921128deff04e04ecc03f9bcc6f0b904b0fa1489e302ac152"
)
FROZEN_AMENDMENT_SHA256 = (
    "34be1c1eb27d4a563baef3da00e6c24b9bb3e009f5fc7e41b5329b37f7bfa0e0"
)
FROZEN_EVALUATOR_SHA256 = (
    "471d8dbd0f0adf97d040ec2351b6ad1b182934dcdc6296ceb8f71a20c69b469f"
)
TRANSFER_MANIFEST_SHA256 = prior.TRANSFER_MANIFEST_SHA256

ORIGINAL_SPEC_FILE_SHA256 = (
    "cf10553a9b041a783bf5caf56b191835e2904474a4bad34dcbc1f6ad934d093f"
)
ORIGINAL_SPEC_SHA256 = (
    "5d370c51da7d95e1d3a62a8ff4f9d66cd3312c5eecfebcbdbaab169be505e0f9"
)
COMPLETION_SPEC_FILE_SHA256 = (
    "d540a5dc43845f87e811aca7670e86f5eada3f5ba8476dd1bdc2aef80bd3518c"
)
COMPLETION_SPEC_SHA256 = (
    "6f02e1dcc077c69037017137725931e94d4fd652da976affda12a2109bb67407"
)
GAP_MANIFEST_FILE_SHA256 = (
    "6ba020575e3ef1eb903ae0010510caea20f31b31bdf3451c0e03f11175c3de94"
)
GAP_MANIFEST_SHA256 = (
    "64176a727907c8f62c496f6fb1893c1f7462cfef15c1db3f06ef7b3e244f0ce8"
)
EXPORT_MANIFEST_FILE_SHA256 = (
    "849d7f1241451acfa0d5558d1978a99281c17ea214953b0008d534586190c8d5"
)
EXPORT_MANIFEST_SHA256 = (
    "a500d1d0159cc112279a7d94bbe01a22306c741161b15ec98eb9b98556267aaf"
)
EXPORT_PAYLOAD_SHA256 = (
    "3cef2fe7553cfd0450e78e7c45deda2d186beb607f34318ead545ce5e3863860"
)
PORTABLE_VALIDATION_FILE_SHA256 = (
    "92cfd27c7ada4b11cd41141cb0544cc29aa0064e7dcff43fd59691f8c2d84492"
)
PORTABLE_ACL_SHA256 = (
    "81fc4c7e398a1d90d2e3903f8e3c38e01ac4263a1d9d21f861a6dc981abfe14e"
)

OLD_EXTERNAL_ATTEMPT_FILE_SHA256 = (
    "e8a3e19da0798fef56c74bca98c6fec798d3d3f99dd253f0c600532c8cc217d3"
)
OLD_EXTERNAL_ATTEMPT_SHA256 = (
    "55d7dfe0dd9fe45ecd0926931dfcca4376765ccec1751c0036053efcafc9d86b"
)
OLD_P0_PRE_FILE_SHA256 = (
    "d997534449f60ffd27b5f21688cfc2f4fec78f0338eeab57ea3362ffeb5f2d95"
)
OLD_P0_POST_FILE_SHA256 = (
    "be25eab1e4ca4199022183b3e1c1709cbf8f3af1cb559303e6c3a9ef389d9ee1"
)
OLD_RESULT_VERIFICATION_FILE_SHA256 = (
    "049488d4ad679f80226471ae424f8dcb6555cab13e219181e656a9a433b3f5d9"
)
OLD_TERMINAL_ATTEMPT_FILE_SHA256 = (
    "c596d921ebeb3c37b44a3d49989813d53289057bba02f8896aadd82fbe92b8cd"
)
OLD_TERMINAL_RESULT_FILE_SHA256 = (
    "1bb76d52daadecc2a4f978af56a0476c9ee43ae9ac097a8162630b51c803a656"
)
OLD_TERMINAL_RECORDS_SHA256 = (
    "6888cdf6655448defd5b46b811ecd9bcf36b397b425b8322f37d083619a9b876"
)
OLD_TRAINING_RECORDS_SHA256 = (
    "09fb7e37ba54b2dd93ef9fc85707fde17be5de05a87bf45966d725ab509d4026"
)

COHORTS = prior.COHORTS
BOUNDARY_ANCHOR = prior.BOUNDARY_ANCHOR
EXPECTED = {
    "requested_cells": 816,
    "admitted_old": 720,
    "admitted_export": 94,
    "admitted_union": 814,
    "exclusions": 2,
    "pre_expected": 696,
    "pre_admitted": 694,
    "pre_exclusions": 2,
    "pre_dates": 58,
    "post_expected": 120,
    "post_admitted": 120,
    "post_exclusions": 0,
    "post_dates": 10,
}
EXPECTED_EXCLUSIONS = {
    ("atlanta", "2026-06-06"),
    ("miami", "2026-06-06"),
}
OLD_SOURCE_CLASS = "frozen_workstation_wu_mirror"
EXPORT_SOURCE_CLASS = "protected_production_export"
RECORD_COLUMNS = (
    "cohort",
    "market",
    "target_date",
    "month",
    "native_unit",
    "outcome_source_class",
    "outcome_source_identity",
    "wu_daily_row_count",
    "outcome_native",
    *prior.PREDICTION_KEYS,
)


IntegrityError = frozen.IntegrityError


def _load_json(path: Path) -> dict[str, Any]:
    return frozen._load_json(path)


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return frozen.self_hash(value, field)


def _exclusive_json(path: Path, value: object) -> None:
    if path.exists():
        raise IntegrityError(f"create-only JSON already exists: {path}")
    encoded = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _git(*arguments: str, binary: bool = False):
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=not binary,
    )
    if completed.returncode != 0:
        stderr = completed.stderr
        if binary:
            stderr = stderr.decode(errors="replace")
        raise IntegrityError(f"git {' '.join(arguments)} failed: {str(stderr).strip()}")
    return completed.stdout


def _repo_root() -> Path:
    return Path(str(_git("rev-parse", "--show-toplevel")).strip()).resolve(strict=True)


def _git_identity() -> dict[str, object]:
    return {
        "branch": str(_git("branch", "--show-current")).strip(),
        "commit": str(_git("rev-parse", "HEAD")).strip(),
        "tree": str(_git("rev-parse", "HEAD^{tree}")).strip(),
    }


def _require_file(path: Path, expected_sha256: str | None = None) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or frozen._is_reparse_point(resolved):
        raise IntegrityError(f"required regular file is absent or redirected: {path}")
    record = {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": frozen.sha256_file(resolved),
    }
    if expected_sha256 is not None and record["sha256"] != expected_sha256:
        raise IntegrityError(f"required file hash differs: {path}")
    return record


def _relative_inventory(root: Path) -> list[dict[str, object]]:
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir() or frozen._is_reparse_point(resolved_root):
        raise IntegrityError(f"inventory root is absent or redirected: {root}")
    records = []
    for path in sorted(resolved_root.rglob("*")):
        if path.is_dir():
            if frozen._is_reparse_point(path):
                raise IntegrityError(f"inventory directory is redirected: {path}")
            continue
        if not path.is_file() or frozen._is_reparse_point(path):
            raise IntegrityError(f"inventory file is absent or redirected: {path}")
        records.append(
            {
                "relative_path": path.relative_to(resolved_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": frozen.sha256_file(path),
            }
        )
    return records


def _validate_json_self_hash(
    path: Path,
    *,
    file_sha256: str,
    field: str,
    self_sha256: str | None = None,
) -> dict[str, Any]:
    _require_file(path, file_sha256)
    value = _load_json(path)
    actual = value.get(field)
    if actual != _self_hash(value, field):
        raise IntegrityError(f"JSON self-hash differs: {path}")
    if self_sha256 is not None and actual != self_sha256:
        raise IntegrityError(f"JSON declared identity differs: {path}")
    return value


def _verify_source_git_and_runner(
    terminal_receipt: Path, source_bundle: Path
) -> dict[str, object]:
    identity = _git_identity()
    if identity != {
        "branch": RESULT_BRANCH,
        "commit": SOURCE_TIP,
        "tree": SOURCE_TREE,
    }:
        raise IntegrityError("completion design must be frozen at the exact source tip")
    source_ref = str(_git("rev-parse", SOURCE_BRANCH)).strip()
    source_tree = str(_git("rev-parse", f"{SOURCE_BRANCH}^{{tree}}")).strip()
    implementation_tree = str(
        _git("rev-parse", f"{SOURCE_IMPLEMENTATION}^{{tree}}")
    ).strip()
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", SOURCE_IMPLEMENTATION, SOURCE_TIP],
        check=False,
        capture_output=True,
        text=True,
    )
    if (
        source_ref != SOURCE_TIP
        or source_tree != SOURCE_TREE
        or implementation_tree != SOURCE_IMPLEMENTATION_TREE
        or ancestor.returncode != 0
    ):
        raise IntegrityError("source branch or implementation ancestry differs")
    receipt = _require_file(terminal_receipt, SOURCE_TERMINAL_RECEIPT_SHA256)
    bundle = _require_file(source_bundle, SOURCE_BUNDLE_SHA256)
    return {
        "source_branch": SOURCE_BRANCH,
        "source_tip": SOURCE_TIP,
        "source_tree": SOURCE_TREE,
        "source_implementation": SOURCE_IMPLEMENTATION,
        "source_implementation_tree": SOURCE_IMPLEMENTATION_TREE,
        "implementation_is_ancestor": True,
        "terminal_receipt": receipt,
        "complete_history_bundle": bundle,
    }


def _verify_old_run(old_run_root: Path) -> dict[str, object]:
    inventory = _relative_inventory(old_run_root)
    expected_paths = {
        "external-2026/external-evaluation-attempt.json",
        "p0-post.json",
        "p0-pre.json",
        "result-verification.json",
        "terminal/evaluation-records.csv",
        "terminal/result.json",
        "terminal/terminal-evaluation-attempt.json",
        "training/eleven-field-residual-challenger.pkl",
        "training/temperature-residual-baseline.pkl",
        "training/training-receipt.json",
        "training/training-records.csv",
    }
    if {str(item["relative_path"]) for item in inventory} != expected_paths:
        raise IntegrityError("old frozen research root file set differs")
    by_path = {str(item["relative_path"]): item for item in inventory}
    expected_hashes = {
        "external-2026/external-evaluation-attempt.json": OLD_EXTERNAL_ATTEMPT_FILE_SHA256,
        "p0-pre.json": OLD_P0_PRE_FILE_SHA256,
        "p0-post.json": OLD_P0_POST_FILE_SHA256,
        "result-verification.json": OLD_RESULT_VERIFICATION_FILE_SHA256,
        "terminal/evaluation-records.csv": OLD_TERMINAL_RECORDS_SHA256,
        "terminal/result.json": OLD_TERMINAL_RESULT_FILE_SHA256,
        "terminal/terminal-evaluation-attempt.json": OLD_TERMINAL_ATTEMPT_FILE_SHA256,
        "training/training-records.csv": OLD_TRAINING_RECORDS_SHA256,
        "training/temperature-residual-baseline.pkl": FROZEN_MODEL_SHA256[
            "temperature_residual_baseline"
        ],
        "training/eleven-field-residual-challenger.pkl": FROZEN_MODEL_SHA256[
            "eleven_field_residual_challenger"
        ],
    }
    for relative, expected in expected_hashes.items():
        if by_path[relative]["sha256"] != expected:
            raise IntegrityError(f"old frozen research artifact differs: {relative}")
    external_attempt = _validate_json_self_hash(
        old_run_root / "external-2026" / "external-evaluation-attempt.json",
        file_sha256=OLD_EXTERNAL_ATTEMPT_FILE_SHA256,
        field="attempt_sha256",
        self_sha256=OLD_EXTERNAL_ATTEMPT_SHA256,
    )
    if (
        external_attempt.get("status") != "SEALED_BEFORE_2026_SOURCE_OUTCOME_ACCESS"
        or external_attempt.get("rerun_authorized") is not False
        or external_attempt.get("model_refits_authorized") != 0
        or external_attempt.get("probability_model_refits_authorized") != 0
    ):
        raise IntegrityError("spent old external attempt contract differs")
    verification = _validate_json_self_hash(
        old_run_root / "result-verification.json",
        file_sha256=OLD_RESULT_VERIFICATION_FILE_SHA256,
        field="verification_sha256",
    )
    if (
        verification.get("status") != "PASS"
        or verification.get("result_file_sha256") != OLD_TERMINAL_RESULT_FILE_SHA256
        or verification.get("evaluation_records_sha256")
        != OLD_TERMINAL_RECORDS_SHA256
        or verification.get("models_refitted") != 0
        or verification.get("source_outcomes_reopened") is not False
    ):
        raise IntegrityError("old terminal verification contract differs")
    terminal_attempt = _validate_json_self_hash(
        old_run_root / "terminal" / "terminal-evaluation-attempt.json",
        file_sha256=OLD_TERMINAL_ATTEMPT_FILE_SHA256,
        field="attempt_sha256",
    )
    if (
        terminal_attempt.get("status") != "SEALED_BEFORE_2025_OUTCOME_ACCESS"
        or terminal_attempt.get("rerun_authorized") is not False
    ):
        raise IntegrityError("old 2025 terminal attempt contract differs")
    for name, phase, expected_file in (
        ("p0-pre.json", "pre", OLD_P0_PRE_FILE_SHA256),
        ("p0-post.json", "post", OLD_P0_POST_FILE_SHA256),
    ):
        value = _validate_json_self_hash(
            old_run_root / name,
            file_sha256=expected_file,
            field="p0_sha256",
        )
        if value.get("status") != "PASS" or value.get("phase") != phase:
            raise IntegrityError(f"old P0 artifact contract differs: {name}")
    return {
        "root": str(old_run_root.resolve(strict=True)),
        "file_count": len(inventory),
        "bytes": sum(int(item["bytes"]) for item in inventory),
        "inventory": inventory,
        "inventory_sha256": frozen.canonical_sha256(inventory),
        "spent_external_attempt_file_sha256": OLD_EXTERNAL_ATTEMPT_FILE_SHA256,
        "spent_external_attempt_sha256": OLD_EXTERNAL_ATTEMPT_SHA256,
        "old_2025_outcome_values_accessed": 0,
    }


def _verify_mirror_inventory(old_amendment: Mapping[str, Any]) -> dict[str, object]:
    input_binding = old_amendment["input_binding"]
    mirror = Path(input_binding["mirror_root"]).resolve(strict=True)
    if not mirror.is_dir() or frozen._is_reparse_point(mirror):
        raise IntegrityError("frozen WU mirror root is absent or redirected")
    expected = input_binding["outcome_source_file_inventory"]
    if frozen.canonical_sha256(expected) != input_binding[
        "outcome_source_file_inventory_sha256"
    ]:
        raise IntegrityError("frozen WU mirror inventory self-hash differs")
    actual = []
    for record in expected:
        path = mirror / record["relative_path"]
        item = _require_file(path, record["sha256"])
        observed = {
            "market": record["market"],
            "station": record["station"],
            "relative_path": record["relative_path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        if observed != record:
            raise IntegrityError(f"frozen WU mirror identity differs: {record['market']}")
        actual.append(observed)
    return {
        "root": str(mirror),
        "file_count": len(actual),
        "files": actual,
        "file_inventory_sha256": frozen.canonical_sha256(actual),
        "semantic_outcome_values_parsed": 0,
    }


def verify_prior_inputs(
    *,
    design_path: Path,
    old_amendment_path: Path,
    artifact_root: Path,
    corpus_root: Path,
    old_run_root: Path,
) -> tuple[dict[str, object], dict[str, dict]]:
    _require_file(design_path, FROZEN_DESIGN_FILE_SHA256)
    old_amendment = _validate_json_self_hash(
        old_amendment_path,
        file_sha256=FROZEN_AMENDMENT_FILE_SHA256,
        field="amendment_sha256",
        self_sha256=FROZEN_AMENDMENT_SHA256,
    )
    old_evaluator = Path(prior.__file__).resolve(strict=True)
    _require_file(old_evaluator, FROZEN_EVALUATOR_SHA256)
    validated_amendment, validated_design, bundles = prior._validate_amendment(
        old_amendment_path, artifact_root
    )
    if (
        validated_design.get("design_sha256") != FROZEN_DESIGN_SHA256
        or validated_amendment.get("amendment_sha256") != FROZEN_AMENDMENT_SHA256
        or validated_amendment["input_binding"]["corpus_root"]
        != str(corpus_root.resolve(strict=True))
    ):
        raise IntegrityError("frozen prior amendment/design binding differs")
    transfer = prior.verify_transfer(corpus_root)
    old_run = _verify_old_run(old_run_root)
    mirror = _verify_mirror_inventory(old_amendment)
    feature_hashes = {
        "baseline": frozen.canonical_sha256(list(frozen.BASELINE_FEATURES)),
        "challenger": frozen.canonical_sha256(list(frozen.CHALLENGER_FEATURES)),
        "combined": frozen.canonical_sha256(
            {
                "baseline": list(frozen.BASELINE_FEATURES),
                "challenger": list(frozen.CHALLENGER_FEATURES),
            }
        ),
    }
    if feature_hashes != FROZEN_FEATURE_ORDER_SHA256:
        raise IntegrityError("frozen feature-order hashes differ")
    audit = {
        "design": {
            "path": str(design_path.resolve(strict=True)),
            "file_sha256": FROZEN_DESIGN_FILE_SHA256,
            "self_sha256": FROZEN_DESIGN_SHA256,
        },
        "old_amendment": {
            "path": str(old_amendment_path.resolve(strict=True)),
            "file_sha256": FROZEN_AMENDMENT_FILE_SHA256,
            "self_sha256": FROZEN_AMENDMENT_SHA256,
        },
        "old_evaluator": {
            "path": str(old_evaluator),
            "file_sha256": FROZEN_EVALUATOR_SHA256,
        },
        "frozen_module_sha256": FROZEN_MODULE_SHA256,
        "models": dict(FROZEN_MODEL_SHA256),
        "feature_order_sha256": feature_hashes,
        "transfer": transfer,
        "mirror": mirror,
        "old_run": old_run,
        "models_refitted": 0,
        "probability_models_refitted": 0,
        "outcome_values_parsed": 0,
    }
    audit["audit_sha256"] = _self_hash(audit, "audit_sha256")
    return audit, bundles


def _request_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("market") or ""), str(row.get("target_date") or "")


def verify_outcome_contract(
    *,
    original_spec_path: Path,
    completion_spec_path: Path,
    gap_manifest_path: Path,
    export_root: Path,
    portable_validation_path: Path,
) -> dict[str, object]:
    original_spec = _validate_json_self_hash(
        original_spec_path,
        file_sha256=ORIGINAL_SPEC_FILE_SHA256,
        field="spec_sha256",
        self_sha256=ORIGINAL_SPEC_SHA256,
    )
    spec = _validate_json_self_hash(
        completion_spec_path,
        file_sha256=COMPLETION_SPEC_FILE_SHA256,
        field="spec_sha256",
        self_sha256=COMPLETION_SPEC_SHA256,
    )
    gap = _validate_json_self_hash(
        gap_manifest_path,
        file_sha256=GAP_MANIFEST_FILE_SHA256,
        field="gap_manifest_sha256",
        self_sha256=GAP_MANIFEST_SHA256,
    )
    if (
        spec.get("original_spec_binding", {}).get("file_sha256")
        != ORIGINAL_SPEC_FILE_SHA256
        or spec.get("original_spec_binding", {}).get("self_hash")
        != ORIGINAL_SPEC_SHA256
        or original_spec.get("spec_sha256") != ORIGINAL_SPEC_SHA256
    ):
        raise IntegrityError("original/new outcome specs are not exactly linked")
    if (
        gap.get("status") != "COMPLETE_OUTCOME_BLIND_INVENTORY"
        or gap.get("outcome_values_read") != 0
        or tuple(gap.get("outcome_fields_accessed") or ())
        or gap.get("minimum_wu_daily_row_count") != frozen.COMPLETE_DAY_MIN_ROWS
    ):
        raise IntegrityError("prior support-only WU audit contract differs")
    entries = gap.get("entries") or []
    if len(entries) != EXPECTED["requested_cells"]:
        raise IntegrityError("support-only WU audit cell count differs")
    by_status = {
        status: {_request_key(row) for row in entries if row.get("status") == status}
        for status in ("present_admissible", "present_below_threshold", "missing")
    }
    if (
        len(by_status["present_admissible"]) != EXPECTED["admitted_old"]
        or len(by_status["present_below_threshold"]) != EXPECTED["exclusions"]
        or len(by_status["missing"]) != EXPECTED["admitted_export"]
        or by_status["present_below_threshold"] != EXPECTED_EXCLUSIONS
    ):
        raise IntegrityError("support-only WU audit status accounting differs")
    requests = spec.get("request", {}).get("keys") or []
    request_keys = [_request_key(row) for row in requests]
    if (
        spec.get("request", {}).get("requested_rows") != EXPECTED["admitted_export"]
        or len(request_keys) != EXPECTED["admitted_export"]
        or len(set(request_keys)) != len(request_keys)
        or set(request_keys) != by_status["missing"]
        or set(request_keys) & by_status["present_admissible"]
    ):
        raise IntegrityError("protected export request does not equal the old missing-key set")
    pre_requests = sum(row.get("provenance_side") == "pre_boundary" for row in requests)
    post_requests = sum(
        row.get("provenance_side") == "post_boundary_directional" for row in requests
    )
    if (pre_requests, post_requests) != (82, 12):
        raise IntegrityError("protected export request provenance split differs")

    resolved_export = export_root.resolve(strict=True)
    if not resolved_export.is_dir() or frozen._is_reparse_point(resolved_export):
        raise IntegrityError("protected export root is absent or redirected")
    children = list(resolved_export.iterdir())
    if (
        len(children) != 2
        or {path.name for path in children} != export_contract.EXPORT_FILENAMES
        or any(not path.is_file() or frozen._is_reparse_point(path) for path in children)
    ):
        raise IntegrityError("protected export does not contain exactly two regular files")
    manifest_path = resolved_export / "manifest.json"
    payload_path = resolved_export / "wu-outcomes.jsonl"
    _require_file(manifest_path, EXPORT_MANIFEST_FILE_SHA256)
    payload_record = _require_file(payload_path, EXPORT_PAYLOAD_SHA256)
    manifest = _validate_json_self_hash(
        manifest_path,
        file_sha256=EXPORT_MANIFEST_FILE_SHA256,
        field="manifest_sha256",
        self_sha256=EXPORT_MANIFEST_SHA256,
    )
    canonical_manifest = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8")
        + b"\n"
    )
    if manifest_path.read_bytes() != canonical_manifest:
        raise IntegrityError("protected export manifest encoding differs")
    payload_binding = manifest.get("payload_file") or {}
    if (
        manifest.get("schema_version") != export_contract.EXPORT_MANIFEST_SCHEMA
        or manifest.get("status") != "COMPLETE_CREATE_ONLY_EXPORT"
        or manifest.get("spec_sha256") != COMPLETION_SPEC_SHA256
        or manifest.get("gap_manifest_sha256") != GAP_MANIFEST_SHA256
        or manifest.get("requested_rows") != EXPECTED["admitted_export"]
        or manifest.get("exported_rows") != EXPECTED["admitted_export"]
        or payload_binding
        != {
            "relative_path": "wu-outcomes.jsonl",
            "bytes": payload_record["bytes"],
            "sha256": EXPORT_PAYLOAD_SHA256,
            "rows": EXPECTED["admitted_export"],
        }
        or len(manifest.get("source_files") or []) != 24
    ):
        raise IntegrityError("protected export manifest binding differs")
    actual_acl = export_contract._actual_export_acl_proof(resolved_export)
    producer_acl = export_contract._validate_acl_proof(
        manifest.get("destination_acl_proof")
    )
    if (
        actual_acl is None
        or actual_acl.get("sddl_sha256") != PORTABLE_ACL_SHA256
    ):
        raise IntegrityError("protected export ACL identity differs")
    deny_acl = frozen._acl_proof(resolved_export)
    if not deny_acl.get("qualifying_rules"):
        raise IntegrityError("protected export explicit write/delete deny is absent")

    portable = _validate_json_self_hash(
        portable_validation_path,
        file_sha256=PORTABLE_VALIDATION_FILE_SHA256,
        field="validation_sha256",
    )
    if (
        portable.get("schema_version") != export_contract.VALIDATION_SCHEMA
        or portable.get("status") != "PASS"
        or portable.get("producer_manifest_file_sha256")
        != EXPORT_MANIFEST_FILE_SHA256
        or portable.get("payload_sha256") != EXPORT_PAYLOAD_SHA256
        or portable.get("manifest_sha256") != EXPORT_MANIFEST_SHA256
        or portable.get("validated_rows") != EXPECTED["admitted_export"]
        or portable.get("outcome_values_reported") != 0
        or portable.get("actual_destination_acl_proof", {}).get("sddl_sha256")
        != PORTABLE_ACL_SHA256
    ):
        raise IntegrityError("independent portable validation identity differs")
    accounting = {
        "requested_cells": len(entries),
        "old_admitted": len(by_status["present_admissible"]),
        "protected_export_requested": len(request_keys),
        "admitted_union": len(by_status["present_admissible"]) + len(request_keys),
        "explicit_exclusions": len(by_status["present_below_threshold"]),
        "final_accounted_cells": len(by_status["present_admissible"])
        + len(request_keys)
        + len(by_status["present_below_threshold"]),
        "request_overlap_with_old_admitted": len(
            set(request_keys) & by_status["present_admissible"]
        ),
        "pre_export_keys": pre_requests,
        "post_export_keys": post_requests,
        "excluded_keys": [list(key) for key in sorted(EXPECTED_EXCLUSIONS)],
    }
    if (
        accounting["admitted_union"] != EXPECTED["admitted_union"]
        or accounting["final_accounted_cells"] != EXPECTED["requested_cells"]
    ):
        raise IntegrityError("completion accounting does not close")
    audit = {
        "original_spec": {
            "path": str(original_spec_path.resolve(strict=True)),
            "file_sha256": ORIGINAL_SPEC_FILE_SHA256,
            "self_sha256": ORIGINAL_SPEC_SHA256,
        },
        "completion_spec": {
            "path": str(completion_spec_path.resolve(strict=True)),
            "file_sha256": COMPLETION_SPEC_FILE_SHA256,
            "self_sha256": COMPLETION_SPEC_SHA256,
        },
        "gap_manifest": {
            "path": str(gap_manifest_path.resolve(strict=True)),
            "file_sha256": GAP_MANIFEST_FILE_SHA256,
            "self_sha256": GAP_MANIFEST_SHA256,
            "outcome_values_read": 0,
        },
        "protected_export": {
            "root": str(resolved_export),
            "manifest_file_sha256": EXPORT_MANIFEST_FILE_SHA256,
            "manifest_sha256": EXPORT_MANIFEST_SHA256,
            "payload_sha256": EXPORT_PAYLOAD_SHA256,
            "payload_bytes": payload_record["bytes"],
            "file_count": len(children),
            "producer_acl": producer_acl,
            "acl": actual_acl,
            "deny_acl": deny_acl,
            "outcome_values_parsed": 0,
        },
        "portable_validation": {
            "path": str(portable_validation_path.resolve(strict=True)),
            "file_sha256": PORTABLE_VALIDATION_FILE_SHA256,
            "validation_sha256": portable["validation_sha256"],
        },
        "accounting": accounting,
    }
    audit["audit_sha256"] = _self_hash(audit, "audit_sha256")
    return audit


def _implementation_files(repo_root: Path) -> list[dict[str, object]]:
    relatives = (
        "src/weather/calibration/multiyear_nwp_residual_external_completion.py",
        "tests/calibration/test_multiyear_nwp_residual_external_completion.py",
        "src/weather/schema_registry_recent_data.py",
        "scripts/ops/workload_admission.ps1",
    )
    records = []
    for relative in relatives:
        path = repo_root / PurePosixPath(relative)
        item = _require_file(path)
        records.append(
            {
                "relative_path": relative,
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
        )
    return records


def freeze_amendment(
    *,
    design_path: Path,
    old_amendment_path: Path,
    artifact_root: Path,
    corpus_root: Path,
    old_run_root: Path,
    original_spec_path: Path,
    completion_spec_path: Path,
    gap_manifest_path: Path,
    export_root: Path,
    portable_validation_path: Path,
    source_terminal_receipt: Path,
    source_bundle: Path,
    result_root: Path,
    output: Path,
) -> dict[str, object]:
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        raise IntegrityError("completion amendment freeze requires workstation wrapper")
    source = _verify_source_git_and_runner(source_terminal_receipt, source_bundle)
    prior_audit, _ = verify_prior_inputs(
        design_path=design_path,
        old_amendment_path=old_amendment_path,
        artifact_root=artifact_root,
        corpus_root=corpus_root,
        old_run_root=old_run_root,
    )
    outcome_audit = verify_outcome_contract(
        original_spec_path=original_spec_path,
        completion_spec_path=completion_spec_path,
        gap_manifest_path=gap_manifest_path,
        export_root=export_root,
        portable_validation_path=portable_validation_path,
    )
    if result_root.exists():
        raise IntegrityError("completion result root already exists before design freeze")
    repo_root = _repo_root()
    implementation_files = _implementation_files(repo_root)
    amendment = {
        "schema_version": AMENDMENT_SCHEMA,
        "status": "IMMUTABLE_BEFORE_COMPLETION_OUTCOME_ACCESS",
        "purpose": (
            "Leakage-safe no-refit external-secondary completion of the frozen "
            "2026 residual-model evaluation; directional and non-confirmatory."
        ),
        "mission": {
            "sha256": MISSION_SHA256,
            "result_branch": RESULT_BRANCH,
            "source": source,
        },
        "p0_precreation_proof": {
            "controller_head": SOURCE_TIP,
            "controller_tree": SOURCE_TREE,
            "controller_and_source_clean": True,
            "result_ref_absent": True,
            "result_worktree_absent": True,
            "result_run_root_absent": True,
            "assigned_principal": "DESKTOP-RFCD2GH\\Michael",
            "shared_mutex_free": True,
            "poison_marker_absent": True,
            "reserved_dates": [],
        },
        "implementation": {
            "planned_branch": RESULT_BRANCH,
            "base_commit": SOURCE_TIP,
            "base_tree": SOURCE_TREE,
            "files": implementation_files,
            "files_sha256": frozen.canonical_sha256(implementation_files),
            "exact_commit_bound_by_attempt_seal": True,
        },
        "frozen_identity": {
            "design_file_sha256": FROZEN_DESIGN_FILE_SHA256,
            "design_sha256": FROZEN_DESIGN_SHA256,
            "old_amendment_file_sha256": FROZEN_AMENDMENT_FILE_SHA256,
            "old_amendment_sha256": FROZEN_AMENDMENT_SHA256,
            "old_evaluator_sha256": FROZEN_EVALUATOR_SHA256,
            "frozen_module_sha256": FROZEN_MODULE_SHA256,
            "model_sha256": dict(FROZEN_MODEL_SHA256),
            "feature_order_sha256": dict(FROZEN_FEATURE_ORDER_SHA256),
            "model_count": 2,
            "models_refitted": 0,
            "probability_models_refitted": 0,
        },
        "input_binding": {
            "design_path": str(design_path.resolve(strict=True)),
            "old_amendment_path": str(old_amendment_path.resolve(strict=True)),
            "artifact_root": str(artifact_root.resolve(strict=True)),
            "corpus_root": str(corpus_root.resolve(strict=True)),
            "old_run_root": str(old_run_root.resolve(strict=True)),
            "original_spec_path": str(original_spec_path.resolve(strict=True)),
            "completion_spec_path": str(completion_spec_path.resolve(strict=True)),
            "gap_manifest_path": str(gap_manifest_path.resolve(strict=True)),
            "export_root": str(export_root.resolve(strict=True)),
            "portable_validation_path": str(
                portable_validation_path.resolve(strict=True)
            ),
            "prior_audit": prior_audit,
            "outcome_contract_audit": outcome_audit,
        },
        "outcome_sources": {
            OLD_SOURCE_CLASS: {
                "authority": "configured WU daily-summary native settlement high",
                "expected_admitted_keys": EXPECTED["admitted_old"],
                "frozen_read_only": True,
            },
            EXPORT_SOURCE_CLASS: {
                "authority": "exact protected production WU export",
                "expected_admitted_keys": EXPECTED["admitted_export"],
                "manifest_file_sha256": EXPORT_MANIFEST_FILE_SHA256,
                "payload_sha256": EXPORT_PAYLOAD_SHA256,
                "frozen_read_only": True,
            },
            "overlap_permitted": False,
        },
        "support_accounting": {
            **EXPECTED,
            "excluded_keys": [list(key) for key in sorted(EXPECTED_EXCLUSIONS)],
            "all_68_dates_must_be_represented": True,
            "all_12_markets_must_be_represented": True,
        },
        "cohorts": {
            name: {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "role": "external_secondary",
            }
            for name, (start, end) in COHORTS.items()
        },
        "provenance_boundary": {
            "anchor": BOUNDARY_ANCHOR,
            "first_post_boundary_date": "2026-07-31",
            "cohorts_must_never_be_pooled": True,
        },
        "methods": {
            "native_units": frozen.MARKET_UNITS,
            "primary_leads": list(frozen.LEADS_PRIMARY),
            "sensitivity_leads": list(frozen.LEADS_SENSITIVITY),
            "features": "exact frozen preprocessing and feature order",
            "estimators": "exact two already-fitted frozen estimators",
            "model_refits": 0,
            "probability_model_refits": 0,
            "minimum_wu_daily_rows": frozen.COMPLETE_DAY_MIN_ROWS,
            "errors": "forecast minus outcome in Celsius-equivalent units",
            "improvement": "baseline loss minus challenger loss",
            "bootstrap": {
                "method": "shared-weight crossed target-date x market pigeonhole bootstrap",
                "draws": frozen.BOOTSTRAP_DRAWS,
                "seed": frozen.BOOTSTRAP_SEED,
                "interval": "percentile 95%",
                "power": "two-sided normal plug-in at alpha=0.05",
                "mde_80": "(z_0.975 + z_0.8) * crossed bootstrap standard error",
            },
            "separate_reporting": ["pre_boundary", "post_boundary_directional"],
            "pooled_headline": False,
        },
        "disposition": {
            "EXTERNAL_DIRECTION_CONSISTENT": (
                "primary-MSE and leads-1-7-MSE improvement points are positive "
                "in both separate cohorts"
            ),
            "EXTERNAL_DIRECTION_ADVERSE": "all four MSE improvement points are negative",
            "EXTERNAL_DIRECTION_MIXED": (
                "otherwise, including any zero or sign disagreement"
            ),
            "INTEGRITY_FAILURE": (
                "any identity, support, no-refit, unit, boundary, source, or "
                "create-only failure"
            ),
        },
        "result_contract": {
            "root": str(result_root.absolute()),
            "create_only": True,
            "rerun_authorized": False,
            "attempt": "external-completion-attempt.json",
            "records": {
                "pre_boundary": "pre-boundary-records.csv",
                "post_boundary_directional": "post-boundary-directional-records.csv",
            },
            "result": "result.json",
            "verification": "result-verification.json",
        },
        "evidence_classification": {
            "external_secondary": True,
            "confirmation": False,
            "changes_original_verdict": False,
            "original_verdict": "INCONCLUSIVE_UNDERPOWERED",
            "can_authorize_distribution_challenger": False,
            "can_authorize_release_promotion_alpha_serving_or_live_use": False,
        },
        "prohibited_actions": [
            "provider, network, market-data, production, Scheduler, exchange, or credential access",
            "live trade, order, cancel, promotion, serving, release, candidate freeze, confirmation-window declaration, or alpha allocation",
            "model fit, partial_fit, probability-model fit, or model write",
            "2025 outcome access or use of a reserved date",
            "pooling across b77cfbed / 2026-07-31",
            "lowering the 18-row threshold, imputing exclusions, dropping a market, or changing any feature, estimator, lead, bootstrap, seed, or decision rule",
            "mutation of any frozen corpus, export, mirror, old run, prior amendment, or prior evaluator",
            "branch merge or history rewrite",
        ],
        "outcome_values_parsed_before_freeze": 0,
    }
    amendment["amendment_sha256"] = _self_hash(amendment, "amendment_sha256")
    _exclusive_json(output, amendment)
    return amendment


def _verify_implementation_files(amendment: Mapping[str, Any]) -> None:
    repo_root = _repo_root()
    actual = _implementation_files(repo_root)
    expected = amendment["implementation"]["files"]
    if (
        actual != expected
        or frozen.canonical_sha256(actual)
        != amendment["implementation"]["files_sha256"]
    ):
        raise IntegrityError("completion implementation file identity differs")


def _committed_amendment_proof(path: Path, amendment: Mapping[str, Any]) -> dict:
    root = _repo_root()
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise IntegrityError("completion amendment is outside the repository") from exc
    committed = _git("show", f"HEAD:{relative}", binary=True)
    if committed != resolved.read_bytes():
        raise IntegrityError("completion amendment is not committed byte-for-byte at HEAD")
    status = str(_git("status", "--porcelain", "--untracked-files=all"))
    identity = _git_identity()
    if (
        status.strip()
        or identity["branch"] != RESULT_BRANCH
        or identity["commit"] == SOURCE_TIP
        or str(_git("merge-base", SOURCE_TIP, str(identity["commit"]))).strip()
        != SOURCE_TIP
    ):
        raise IntegrityError("completion evaluation requires a clean descendant commit")
    _verify_implementation_files(amendment)
    return {
        **identity,
        "relative_path": relative,
        "blob": str(_git("rev-parse", f"HEAD:{relative}")).strip(),
        "file_sha256": frozen.sha256_file(resolved),
        "amendment_sha256": amendment["amendment_sha256"],
        "worktree_clean": True,
    }


def _validate_amendment_light(path: Path) -> dict[str, Any]:
    amendment = _load_json(path)
    if (
        amendment.get("schema_version") != AMENDMENT_SCHEMA
        or amendment.get("status") != "IMMUTABLE_BEFORE_COMPLETION_OUTCOME_ACCESS"
        or amendment.get("amendment_sha256")
        != _self_hash(amendment, "amendment_sha256")
        or amendment.get("outcome_values_parsed_before_freeze") != 0
    ):
        raise IntegrityError("completion amendment identity differs")
    _verify_implementation_files(amendment)
    return amendment


def _validate_amendment_full(
    path: Path,
) -> tuple[dict[str, Any], dict[str, dict], dict[str, object], dict[str, object]]:
    amendment = _validate_amendment_light(path)
    binding = amendment["input_binding"]
    prior_audit, bundles = verify_prior_inputs(
        design_path=Path(binding["design_path"]),
        old_amendment_path=Path(binding["old_amendment_path"]),
        artifact_root=Path(binding["artifact_root"]),
        corpus_root=Path(binding["corpus_root"]),
        old_run_root=Path(binding["old_run_root"]),
    )
    outcome_audit = verify_outcome_contract(
        original_spec_path=Path(binding["original_spec_path"]),
        completion_spec_path=Path(binding["completion_spec_path"]),
        gap_manifest_path=Path(binding["gap_manifest_path"]),
        export_root=Path(binding["export_root"]),
        portable_validation_path=Path(binding["portable_validation_path"]),
    )
    if (
        frozen.canonical_sha256(prior_audit)
        != frozen.canonical_sha256(binding["prior_audit"])
        or frozen.canonical_sha256(outcome_audit)
        != frozen.canonical_sha256(binding["outcome_contract_audit"])
    ):
        raise IntegrityError("completion input identity changed after design freeze")
    return amendment, bundles, prior_audit, outcome_audit


def _seal_attempt(
    output_root: Path,
    amendment_path: Path,
    amendment: Mapping[str, Any],
    commit_proof: Mapping[str, Any],
) -> tuple[Path, dict[str, object]]:
    if output_root.exists():
        raise IntegrityError("completion output root already exists")
    output_root.mkdir(parents=True, exist_ok=False)
    path = output_root / amendment["result_contract"]["attempt"]
    attempt = {
        "schema_version": ATTEMPT_SCHEMA,
        "status": "SEALED_BEFORE_COMPLETION_OUTCOME_ACCESS",
        "mission_sha256": MISSION_SHA256,
        "amendment_file_sha256": frozen.sha256_file(amendment_path),
        "amendment_sha256": amendment["amendment_sha256"],
        "implementation_commit": dict(commit_proof),
        "input_identity": {
            "prior_audit_sha256": amendment["input_binding"]["prior_audit"][
                "audit_sha256"
            ],
            "outcome_contract_audit_sha256": amendment["input_binding"][
                "outcome_contract_audit"
            ]["audit_sha256"],
            "model_sha256": dict(FROZEN_MODEL_SHA256),
            "protected_payload_sha256": EXPORT_PAYLOAD_SHA256,
        },
        "cohorts": amendment["cohorts"],
        "outcome_sources_authorized_once": [OLD_SOURCE_CLASS, EXPORT_SOURCE_CLASS],
        "outcome_values_accessed_before_seal": 0,
        "model_refits_authorized": 0,
        "partial_fits_authorized": 0,
        "probability_model_refits_authorized": 0,
        "model_writes_authorized": 0,
        "2025_outcome_access_authorized": 0,
        "rerun_authorized": False,
        "workstation_wrapper_active": os.environ.get(
            "WEATHER_WORKSTATION_WRAPPER_ACTIVE"
        )
        == "1",
        "file_fsync_required": True,
    }
    if not attempt["workstation_wrapper_active"]:
        raise IntegrityError("completion attempt requires workstation wrapper")
    attempt["attempt_sha256"] = _self_hash(attempt, "attempt_sha256")
    _exclusive_json(path, attempt)
    return path, attempt


def _required_dates() -> set[str]:
    return {
        value
        for start, end in COHORTS.values()
        for value in prior._date_range(start, end)
    }


def load_old_outcomes_once(
    old_amendment: Mapping[str, Any], gap: Mapping[str, Any]
) -> tuple[dict[tuple[str, str], dict[str, object]], list[dict[str, object]], dict]:
    mirror = Path(old_amendment["input_binding"]["mirror_root"]).resolve(strict=True)
    required_dates = _required_dates()
    gap_entries = {_request_key(row): row for row in gap["entries"]}
    outcomes: dict[tuple[str, str], dict[str, object]] = {}
    exclusions: list[dict[str, object]] = []
    ignored_non_2026_rows = 0
    opened_files = 0
    inventory = {
        row["market"]: row
        for row in old_amendment["input_binding"]["outcome_source_file_inventory"]
    }
    for market, path in frozen._outcome_paths(mirror).items():
        record = inventory[market]
        if frozen.sha256_file(path) != record["sha256"]:
            raise IntegrityError(f"old WU source changed before semantic read: {market}")
        opened_files += 1
        seen_dates: set[str] = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = tuple(next(reader, ()))
            required = {
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp_bucket_native",
            }
            if not required.issubset(header):
                raise IntegrityError(f"old WU outcome columns are incomplete: {market}")
            positions = {name: header.index(name) for name in required}
            for row in reader:
                try:
                    raw_date = row[positions["local_date"]]
                    local_date = date.fromisoformat(raw_date)
                except (IndexError, ValueError):
                    continue
                if local_date.year != prior.EXTERNAL_YEAR:
                    ignored_non_2026_rows += 1
                    continue
                if raw_date not in required_dates:
                    continue
                key = (market, raw_date)
                if raw_date in seen_dates:
                    raise IntegrityError(f"duplicate old WU date: {market}/{raw_date}")
                seen_dates.add(raw_date)
                gap_row = gap_entries.get(key)
                if gap_row is None or gap_row.get("status") == "missing":
                    raise IntegrityError(f"old WU presence disagrees with gap audit: {market}/{raw_date}")
                try:
                    row_count = int(row[positions["row_count"]])
                except (IndexError, ValueError):
                    row_count = 0
                if row_count != gap_row.get("row_count"):
                    raise IntegrityError(f"old WU support changed: {market}/{raw_date}")
                if gap_row.get("status") == "present_below_threshold":
                    if row_count >= frozen.COMPLETE_DAY_MIN_ROWS:
                        raise IntegrityError("old WU exclusion threshold status differs")
                    exclusions.append(
                        {
                            "market": market,
                            "target_date": raw_date,
                            "reason": "wu_row_count_below_18",
                            "row_count": row_count,
                            "outcome_source_class": OLD_SOURCE_CLASS,
                        }
                    )
                    continue
                if row_count < frozen.COMPLETE_DAY_MIN_ROWS:
                    raise IntegrityError("old WU admitted row fell below threshold")
                unit = row[positions["temperature_unit"]].strip().upper()
                if unit != frozen.MARKET_UNITS[market]:
                    raise IntegrityError(f"old WU native unit differs: {market}/{raw_date}")
                selected = {name: row[index] for name, index in positions.items()}
                outcome = native_bucket(selected)
                if outcome is None:
                    raise IntegrityError(f"old WU native outcome is absent: {market}/{raw_date}")
                outcomes[key] = {
                    "outcome_native": int(outcome),
                    "native_unit": unit,
                    "wu_daily_row_count": row_count,
                    "outcome_source_class": OLD_SOURCE_CLASS,
                    "outcome_source_identity": record["sha256"],
                }
    expected_old = {
        key for key, row in gap_entries.items() if row.get("status") == "present_admissible"
    }
    expected_exclusions = {
        key
        for key, row in gap_entries.items()
        if row.get("status") == "present_below_threshold"
    }
    if set(outcomes) != expected_old or {
        (str(row["market"]), str(row["target_date"])) for row in exclusions
    } != expected_exclusions:
        raise IntegrityError("old WU semantic outcome key accounting differs")
    audit = {
        "source_class": OLD_SOURCE_CLASS,
        "files_opened_once": opened_files,
        "admitted_outcome_values_parsed": len(outcomes),
        "excluded_values_not_parsed": len(exclusions),
        "ignored_non_2026_rows_without_outcome_value_access": ignored_non_2026_rows,
        "outcome_value_access_2025": 0,
        "keys_sha256": frozen.canonical_sha256(
            [f"{market}|{target}" for market, target in sorted(outcomes)]
        ),
    }
    return outcomes, exclusions, audit


def _validate_source_bindings(manifest: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    bindings: dict[tuple[str, str], str] = {}
    for row in manifest.get("source_files") or []:
        if not isinstance(row, dict) or set(row) != {
            "role",
            "relative_path",
            "bytes_before",
            "bytes_after",
            "sha256_before",
            "sha256_after",
        }:
            raise IntegrityError("protected source-file binding fields differ")
        role = str(row.get("role") or "")
        relative = export_contract._portable_relative(
            row.get("relative_path"), "source file"
        ).as_posix()
        before = export_contract._require_sha(row.get("sha256_before"), "source hash")
        if (
            role not in {"settlement_ledger", "wu_daily_summary"}
            or row.get("bytes_before") != row.get("bytes_after")
            or before
            != export_contract._require_sha(row.get("sha256_after"), "source hash")
        ):
            raise IntegrityError("protected source changed during production export")
        key = (role, relative.casefold())
        if key in bindings:
            raise IntegrityError("protected source-file binding is duplicate")
        bindings[key] = before
    return bindings


def load_protected_outcomes_once(
    *,
    payload_path: Path,
    requests: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> tuple[dict[tuple[str, str], dict[str, object]], dict[str, object]]:
    request_map = {_request_key(row): row for row in requests}
    if len(request_map) != len(requests):
        raise IntegrityError("protected request keys are duplicate")
    configured_markets = {item.id: item for item in BUILTIN_SPECS}
    source_bindings = _validate_source_bindings(manifest)
    outcomes: dict[tuple[str, str], dict[str, object]] = {}
    value_accesses = 0
    with payload_path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise IntegrityError("protected payload contains a blank row")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IntegrityError(
                    f"protected payload JSON is invalid at line {line_number}"
                ) from exc
            if not isinstance(row, dict) or set(row) != export_contract.EXPORT_ROW_FIELDS:
                raise IntegrityError("protected payload fields differ")
            if line.encode("utf-8") != export_contract.canonical_json_bytes(row) + b"\n":
                raise IntegrityError("protected payload encoding differs")
            if row.get("schema_version") != export_contract.EXPORT_ROW_SCHEMA:
                raise IntegrityError("protected payload row schema differs")
            key = _request_key(row)
            request = request_map.get(key)
            if request is None or key in outcomes:
                raise IntegrityError("protected payload key is unrequested or duplicate")
            market, target = key
            try:
                target_date = date.fromisoformat(target)
            except ValueError as exc:
                raise IntegrityError("protected target date is invalid") from exc
            expected_side = (
                "post_boundary_directional"
                if target_date >= export_contract.BOUNDARY_DATE
                else "pre_boundary"
            )
            configured = configured_markets.get(market)
            expected_slug = (
                f"{configured.slug_prefix}-{target_date.strftime('%B').lower()}-"
                f"{target_date.day}-{target_date.year}"
                if configured is not None
                else ""
            )
            if (
                row.get("provenance_side") != expected_side
                or request.get("provenance_side") != expected_side
                or row.get("settlement_unit") != request.get("settlement_unit")
                or str(row.get("resolution_station") or "").casefold()
                != str(request.get("station") or "").casefold()
                or row.get("settlement_source") != "daily_summary"
                or row.get("resolution_source_type") != "wunderground_history"
                or configured is None
                or row.get("resolution_wu_history_id") != configured.wu_history_id
                or str(row.get("resolution_station") or "").casefold()
                != configured.icao.casefold()
                or row.get("resolution_timezone") != configured.timezone
                or row.get("settlement_unit") != configured.display_unit
                or row.get("source_event_slug") != expected_slug
            ):
                raise IntegrityError("protected payload provenance or native-unit identity differs")
            row_count = row.get("wu_daily_row_count")
            if (
                isinstance(row_count, bool)
                or not isinstance(row_count, int)
                or row_count < frozen.COMPLETE_DAY_MIN_ROWS
            ):
                raise IntegrityError("protected payload WU support is below threshold")
            bucket = row.get("settlement_bucket_native")
            value_accesses += 1
            if isinstance(bucket, bool) or not isinstance(bucket, int):
                raise IntegrityError("protected payload native outcome is invalid")
            revision = row.get("source_revision_number")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise IntegrityError("protected payload revision number is invalid")
            if not str(row.get("source_revision_id") or ""):
                raise IntegrityError("protected payload revision identity is absent")
            export_contract._require_utc_timestamp(
                row.get("source_recorded_at_utc"), "source revision time"
            )
            label_hash = export_contract._require_sha(
                row.get("source_label_hash"), "source label hash"
            )
            expected_ledger = f"data/settlements/{market}/ledger.jsonl"
            expected_daily = (
                f"data/wunderground/{str(request['station']).casefold()}/daily/"
                "daily_summary.csv"
            )
            if (
                row.get("source_ledger_relative_path") != expected_ledger
                or row.get("source_daily_summary_relative_path") != expected_daily
            ):
                raise IntegrityError("protected payload source path differs")
            for role, path_name, hash_name in (
                ("settlement_ledger", "source_ledger_relative_path", "source_ledger_sha256"),
                ("wu_daily_summary", "source_daily_summary_relative_path", "source_daily_summary_sha256"),
            ):
                source_hash = export_contract._require_sha(row.get(hash_name), hash_name)
                binding_key = (role, str(row[path_name]).casefold())
                if source_bindings.get(binding_key) != source_hash:
                    raise IntegrityError("protected payload source hash is not manifest-bound")
            outcomes[key] = {
                "outcome_native": bucket,
                "native_unit": str(row["settlement_unit"]),
                "wu_daily_row_count": row_count,
                "outcome_source_class": EXPORT_SOURCE_CLASS,
                "outcome_source_identity": label_hash,
            }
    if set(outcomes) != set(request_map):
        raise IntegrityError("protected payload does not cover its exact request set")
    if (
        value_accesses != len(requests)
        or manifest.get("payload_file", {}).get("rows") != len(outcomes)
    ):
        raise IntegrityError("protected payload semantic access count differs")
    audit = {
        "source_class": EXPORT_SOURCE_CLASS,
        "files_opened_once": 1,
        "admitted_outcome_values_parsed": value_accesses,
        "outcome_value_access_2025": 0,
        "keys_sha256": frozen.canonical_sha256(
            [f"{market}|{target}" for market, target in sorted(outcomes)]
        ),
    }
    return outcomes, audit


def combine_outcomes(
    *,
    old: Mapping[tuple[str, str], dict[str, object]],
    exported: Mapping[tuple[str, str], dict[str, object]],
    exclusions: Sequence[Mapping[str, object]],
) -> tuple[dict[tuple[str, str], dict[str, object]], dict[str, object]]:
    overlap = set(old) & set(exported)
    combined = {**old, **exported}
    exclusion_keys = {
        (str(row["market"]), str(row["target_date"])) for row in exclusions
    }
    all_keys = set(combined) | exclusion_keys
    required = {
        (market, target)
        for market in frozen.MARKETS
        for target in _required_dates()
    }
    pre = {
        key for key in combined if COHORTS["pre_boundary"][0].isoformat() <= key[1] <= COHORTS["pre_boundary"][1].isoformat()
    }
    post = {
        key for key in combined if COHORTS["post_boundary_directional"][0].isoformat() <= key[1] <= COHORTS["post_boundary_directional"][1].isoformat()
    }
    if (
        overlap
        or len(old) != EXPECTED["admitted_old"]
        or len(exported) != EXPECTED["admitted_export"]
        or len(combined) != EXPECTED["admitted_union"]
        or exclusion_keys != EXPECTED_EXCLUSIONS
        or all_keys != required
        or len(pre) != EXPECTED["pre_admitted"]
        or len(post) != EXPECTED["post_admitted"]
        or len({key[1] for key in pre}) != EXPECTED["pre_dates"]
        or len({key[1] for key in post}) != EXPECTED["post_dates"]
        or {key[0] for key in pre} != set(frozen.MARKETS)
        or {key[0] for key in post} != set(frozen.MARKETS)
    ):
        raise IntegrityError("combined 814+2 outcome accounting differs")
    audit = {
        "old_admitted": len(old),
        "export_admitted": len(exported),
        "key_overlap": len(overlap),
        "union_admitted": len(combined),
        "exclusions": len(exclusion_keys),
        "accounted_cells": len(all_keys),
        "pre_admitted": len(pre),
        "pre_dates": len({key[1] for key in pre}),
        "post_admitted": len(post),
        "post_dates": len({key[1] for key in post}),
        "markets": sorted({key[0] for key in combined}),
        "union_keys_sha256": frozen.canonical_sha256(
            [f"{market}|{target}" for market, target in sorted(combined)]
        ),
    }
    return combined, audit


def _write_records(path: Path, records: Sequence[Mapping[str, object]]) -> dict:
    if path.exists():
        raise IntegrityError(f"create-only completion records already exist: {path}")
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECORD_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "relative_path": path.name,
        "bytes": path.stat().st_size,
        "sha256": frozen.sha256_file(path),
        "rows": len(records),
    }


def _prediction_records(
    *,
    surfaces: Mapping,
    evidence: Mapping[tuple[str, str], Mapping[str, object]],
    bundles: Mapping[str, dict],
    cohort: str,
) -> tuple[list[dict], dict]:
    outcomes = {key: int(value["outcome_native"]) for key, value in evidence.items()}
    records, refit_audit = prior._predict_records(
        surfaces=dict(surfaces), outcomes=outcomes, bundles=dict(bundles), cohort=cohort
    )
    for row in records:
        source = evidence[(str(row["market"]), str(row["target_date"]))]
        if str(source["native_unit"]) != str(row["native_unit"]):
            raise IntegrityError("prediction/outcome native unit differs")
        row["outcome_source_class"] = source["outcome_source_class"]
        row["outcome_source_identity"] = source["outcome_source_identity"]
        row["wu_daily_row_count"] = source["wu_daily_row_count"]
    return records, refit_audit


def evaluate_completion_cohort(
    records: Sequence[dict], exclusions: Sequence[Mapping[str, object]]
) -> dict:
    evaluation = prior.evaluate_cohort(records, exclusions)
    classes: dict[str, int] = {}
    for row in records:
        value = str(row["outcome_source_class"])
        classes[value] = classes.get(value, 0) + 1
    evaluation["support"]["outcome_source_classes"] = classes
    evaluation["support"]["record_rows_sha256"] = frozen.canonical_sha256(
        [dict(row) for row in records]
    )
    return evaluation


def external_disposition(evaluations: Mapping[str, dict]) -> dict[str, object]:
    signs = {}
    for cohort in COHORTS:
        endpoints = evaluations[cohort]["crossed_bootstrap"]["endpoints"]
        signs[f"{cohort}__primary"] = endpoints[
            "primary__squared_error_improvement"
        ]["point"]
        signs[f"{cohort}__all_leads_sensitivity"] = endpoints[
            "all_leads_sensitivity__squared_error_improvement"
        ]["point"]
    if all(value > 0 for value in signs.values()):
        disposition = "EXTERNAL_DIRECTION_CONSISTENT"
    elif all(value < 0 for value in signs.values()):
        disposition = "EXTERNAL_DIRECTION_ADVERSE"
    else:
        disposition = "EXTERNAL_DIRECTION_MIXED"
    return {
        "disposition": disposition,
        "mse_improvement_points": signs,
        "changes_original_verdict": False,
        "original_verdict": "INCONCLUSIVE_UNDERPOWERED",
        "external_secondary": True,
        "confirmation": False,
        "can_authorize_distribution_challenger": False,
        "can_authorize_release_promotion_alpha_serving_or_live_use": False,
        "authorized_actions": [],
    }


def run_evaluation(*, amendment_path: Path, output_root: Path) -> dict[str, object]:
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        raise IntegrityError("completion evaluation requires workstation wrapper")
    amendment, bundles, prior_pre, outcome_pre = _validate_amendment_full(amendment_path)
    expected_root = Path(amendment["result_contract"]["root"]).absolute()
    if output_root.absolute() != expected_root:
        raise IntegrityError("completion output root differs from the frozen amendment")
    commit_proof = _committed_amendment_proof(amendment_path, amendment)
    attempt_path, attempt = _seal_attempt(
        output_root, amendment_path, amendment, commit_proof
    )

    binding = amendment["input_binding"]
    old_amendment = _load_json(Path(binding["old_amendment_path"]))
    gap = _load_json(Path(binding["gap_manifest_path"]))
    spec = _load_json(Path(binding["completion_spec_path"]))
    manifest = _load_json(Path(binding["export_root"]) / "manifest.json")
    surfaces, feature_audit = prior.load_feature_surfaces(Path(binding["corpus_root"]))
    old_outcomes, exclusions, old_source_audit = load_old_outcomes_once(
        old_amendment, gap
    )
    export_outcomes, export_source_audit = load_protected_outcomes_once(
        payload_path=Path(binding["export_root"]) / "wu-outcomes.jsonl",
        requests=spec["request"]["keys"],
        manifest=manifest,
    )
    evidence, union_audit = combine_outcomes(
        old=old_outcomes, exported=export_outcomes, exclusions=exclusions
    )

    records_by_cohort: dict[str, list[dict]] = {}
    record_artifacts = {}
    refit_audits = {}
    for cohort in COHORTS:
        records, refit_audit = _prediction_records(
            surfaces=surfaces,
            evidence=evidence,
            bundles=bundles,
            cohort=cohort,
        )
        records_by_cohort[cohort] = records
        record_artifacts[cohort] = _write_records(
            output_root / amendment["result_contract"]["records"][cohort], records
        )
        refit_audits[cohort] = refit_audit

    evaluations = {
        cohort: evaluate_completion_cohort(records_by_cohort[cohort], exclusions)
        for cohort in COHORTS
    }
    disposition = external_disposition(evaluations)
    _, _, prior_post, outcome_post = _validate_amendment_full(amendment_path)
    if (
        frozen.canonical_sha256(prior_pre) != frozen.canonical_sha256(prior_post)
        or frozen.canonical_sha256(outcome_pre) != frozen.canonical_sha256(outcome_post)
    ):
        raise IntegrityError("completion inputs changed during evaluation")
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": "EXTERNAL_SECONDARY_2026_COMPLETION_COMPLETE",
        "disposition": disposition,
        "amendment": {
            "relative_path": commit_proof["relative_path"],
            "file_sha256": frozen.sha256_file(amendment_path),
            "amendment_sha256": amendment["amendment_sha256"],
            "commit_proof": commit_proof,
        },
        "terminal_attempt": {
            "relative_path": attempt_path.name,
            "file_sha256": frozen.sha256_file(attempt_path),
            "attempt_sha256": attempt["attempt_sha256"],
            "rerun_authorized": False,
        },
        "frozen_identity": amendment["frozen_identity"],
        "feature_audit": feature_audit,
        "outcome_audit": {
            "old_source": old_source_audit,
            "protected_export_source": export_source_audit,
            "union": union_audit,
            "exclusions": exclusions,
            "semantic_outcome_values_parsed": len(old_outcomes)
            + len(export_outcomes),
            "outcome_value_access_2025": 0,
            "source_files_opened_semantically": old_source_audit["files_opened_once"]
            + export_source_audit["files_opened_once"],
        },
        "record_artifacts": record_artifacts,
        "evaluations": evaluations,
        "no_refit_audit": {
            "cohorts": refit_audits,
            "models_refitted": 0,
            "partial_fits": 0,
            "probability_models_refitted": 0,
            "model_writes": 0,
            "model_hashes_before": dict(FROZEN_MODEL_SHA256),
            "model_hashes_after": dict(FROZEN_MODEL_SHA256),
        },
        "immutability_audit": {
            "prior_input_pre_sha256": prior_pre["audit_sha256"],
            "prior_input_post_sha256": prior_post["audit_sha256"],
            "outcome_contract_pre_sha256": outcome_pre["audit_sha256"],
            "outcome_contract_post_sha256": outcome_post["audit_sha256"],
            "corpus_export_models_old_run_mirror_and_acl_unchanged": True,
            "frozen_input_writes": 0,
        },
        "evidence_classification": amendment["evidence_classification"],
        "prohibited_actions_audit": {
            "provider_network_or_market_data_calls": 0,
            "model_refits": 0,
            "partial_fits": 0,
            "probability_model_refits": 0,
            "model_writes": 0,
            "2025_outcome_value_accesses": 0,
            "pooled_cross_boundary_evaluations": 0,
            "markets_dropped": 0,
            "low_support_rows_imputed": 0,
            "frozen_input_writes": 0,
            "production_scheduler_exchange_credential_accesses": 0,
            "release_distribution_promotion_candidate_alpha_confirmation_serving_actions": 0,
            "branch_merges_or_history_rewrites": 0,
        },
    }
    result["result_sha256"] = _self_hash(result, "result_sha256")
    _exclusive_json(output_root / amendment["result_contract"]["result"], result)
    return result


def _read_records(path: Path, expected_cohort: str) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RECORD_COLUMNS:
            raise IntegrityError("completion evaluation-record column order differs")
        for row in reader:
            if row["cohort"] != expected_cohort:
                raise IntegrityError("completion evaluation-record cohort differs")
            record = {
                "cohort": row["cohort"],
                "market": row["market"],
                "target_date": row["target_date"],
                "month": int(row["month"]),
                "native_unit": row["native_unit"],
                "outcome_source_class": row["outcome_source_class"],
                "outcome_source_identity": row["outcome_source_identity"],
                "wu_daily_row_count": int(row["wu_daily_row_count"]),
                "outcome_native": int(row["outcome_native"]),
            }
            for key in prior.PREDICTION_KEYS:
                value = float(row[key])
                if not math.isfinite(value):
                    raise IntegrityError("completion prediction record is non-finite")
                record[key] = value
            records.append(record)
    return records


def verify_result(
    *, amendment_path: Path, output_root: Path
) -> dict[str, object]:
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        raise IntegrityError("completion verification requires workstation wrapper")
    amendment = _validate_amendment_light(amendment_path)
    _committed_amendment_proof(amendment_path, amendment)
    result_path = output_root / amendment["result_contract"]["result"]
    result = _load_json(result_path)
    if (
        result.get("schema_version") != RESULT_SCHEMA
        or result.get("result_sha256") != _self_hash(result, "result_sha256")
        or result.get("amendment", {}).get("amendment_sha256")
        != amendment["amendment_sha256"]
    ):
        raise IntegrityError("completion result identity differs")
    attempt = _load_json(output_root / result["terminal_attempt"]["relative_path"])
    if (
        attempt.get("schema_version") != ATTEMPT_SCHEMA
        or attempt.get("attempt_sha256") != _self_hash(attempt, "attempt_sha256")
        or attempt.get("rerun_authorized") is not False
    ):
        raise IntegrityError("completion attempt identity differs")
    exclusions = result["outcome_audit"]["exclusions"]
    reproduced = {}
    records_by_cohort = {}
    for cohort in COHORTS:
        record = result["record_artifacts"][cohort]
        path = output_root / record["relative_path"]
        if (
            path.stat().st_size != record["bytes"]
            or frozen.sha256_file(path) != record["sha256"]
        ):
            raise IntegrityError(f"sealed completion records differ: {cohort}")
        rows = _read_records(path, cohort)
        records_by_cohort[cohort] = rows
        reproduced[cohort] = evaluate_completion_cohort(rows, exclusions)
        if frozen.canonical_sha256(reproduced[cohort]) != frozen.canonical_sha256(
            result["evaluations"][cohort]
        ):
            raise IntegrityError(f"completion deterministic reproduction differs: {cohort}")
    old = {
        (str(row["market"]), str(row["target_date"])): row
        for rows in records_by_cohort.values()
        for row in rows
        if row["outcome_source_class"] == OLD_SOURCE_CLASS
    }
    exported = {
        (str(row["market"]), str(row["target_date"])): row
        for rows in records_by_cohort.values()
        for row in rows
        if row["outcome_source_class"] == EXPORT_SOURCE_CLASS
    }
    _, reproduced_union = combine_outcomes(
        old=old, exported=exported, exclusions=exclusions
    )
    if frozen.canonical_sha256(reproduced_union) != frozen.canonical_sha256(
        result["outcome_audit"]["union"]
    ):
        raise IntegrityError("completion source-accounting reproduction differs")
    disposition = external_disposition(reproduced)
    if frozen.canonical_sha256(disposition) != frozen.canonical_sha256(
        result["disposition"]
    ):
        raise IntegrityError("completion disposition reproduction differs")
    verification = {
        "schema_version": VERIFICATION_SCHEMA,
        "status": "PASS",
        "result_file_sha256": frozen.sha256_file(result_path),
        "result_sha256": result["result_sha256"],
        "amendment_sha256": amendment["amendment_sha256"],
        "record_sha256": {
            cohort: result["record_artifacts"][cohort]["sha256"] for cohort in COHORTS
        },
        "reproduced_evaluation_sha256": {
            cohort: frozen.canonical_sha256(value)
            for cohort, value in reproduced.items()
        },
        "reproduced_union_sha256": frozen.canonical_sha256(reproduced_union),
        "reproduced_disposition": disposition["disposition"],
        "bootstrap_reproduced": True,
        "source_outcomes_reopened": False,
        "source_outcome_files_opened": 0,
        "models_loaded": 0,
        "models_refitted": 0,
        "partial_fits": 0,
        "probability_models_refitted": 0,
        "model_writes": 0,
        "outcome_value_access_2025": 0,
        "cohorts_reproduced_separately": True,
        "pooled_headline_computed": False,
    }
    verification["verification_sha256"] = _self_hash(
        verification, "verification_sha256"
    )
    return verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze-amendment")
    freeze.add_argument("--design", type=Path, required=True)
    freeze.add_argument("--old-amendment", type=Path, required=True)
    freeze.add_argument("--artifact-root", type=Path, required=True)
    freeze.add_argument("--corpus-root", type=Path, required=True)
    freeze.add_argument("--old-run-root", type=Path, required=True)
    freeze.add_argument("--original-spec", type=Path, required=True)
    freeze.add_argument("--completion-spec", type=Path, required=True)
    freeze.add_argument("--gap-manifest", type=Path, required=True)
    freeze.add_argument("--export-root", type=Path, required=True)
    freeze.add_argument("--portable-validation", type=Path, required=True)
    freeze.add_argument("--source-terminal-receipt", type=Path, required=True)
    freeze.add_argument("--source-bundle", type=Path, required=True)
    freeze.add_argument("--result-root", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--amendment", type=Path, required=True)
    evaluate.add_argument("--output-root", type=Path, required=True)

    verify = subparsers.add_parser("verify-result")
    verify.add_argument("--amendment", type=Path, required=True)
    verify.add_argument("--output-root", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "freeze-amendment":
        result = freeze_amendment(
            design_path=args.design,
            old_amendment_path=args.old_amendment,
            artifact_root=args.artifact_root,
            corpus_root=args.corpus_root,
            old_run_root=args.old_run_root,
            original_spec_path=args.original_spec,
            completion_spec_path=args.completion_spec,
            gap_manifest_path=args.gap_manifest,
            export_root=args.export_root,
            portable_validation_path=args.portable_validation,
            source_terminal_receipt=args.source_terminal_receipt,
            source_bundle=args.source_bundle,
            result_root=args.result_root,
            output=args.output,
        )
    elif args.command == "evaluate":
        result = run_evaluation(
            amendment_path=args.amendment,
            output_root=args.output_root,
        )
    else:
        result = verify_result(
            amendment_path=args.amendment,
            output_root=args.output_root,
        )
        _exclusive_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
