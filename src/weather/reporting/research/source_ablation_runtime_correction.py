"""Immutable correction contract for the workstation source-ablation retry."""

from __future__ import annotations

import hashlib
import json
import os
import stat as stat_module
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from weather.backtesting.source_ablation_contract import ALL_VARIANTS
from weather.schema_registry import schema_version


CORRECTION_SCHEMA_VERSION = schema_version(
    "source_ablation_runtime_support_correction"
)
PARITY_SCHEMA_VERSION = schema_version("source_ablation_runtime_support_parity")
CORRECTION_STATUS = "SEALED_FOR_GENERATION_002"
HELPER_RELATIVE_PATH = Path("src/weather/backtesting/source_ablation_contract.py")
PRE_FIX_HELPER_SHA256 = (
    "3b205d7c3cdd648035c771f50217fedfbdfbb39c6e3e55cbc420ceeffc2278af"
)
FAILED_GENERATION_LEAF = "sealed-source-ablation-v0.1-generation-001"
RETRY_GENERATION_LEAF = "sealed-source-ablation-v0.1-generation-002"
PRODUCER_PROFILE = "workstation_source_ablation_hardened_v0.1"
PAIR_SPLITS = ("tune", "holdout")

EXPECTED_OUTCOME_USE = {
    "scope": "pinned replay source payloads only",
    "outcome_effects_read": False,
    "settlements_read": False,
    "scores_computed": False,
}
EXPECTED_AFFECTED_UNIT = {
    "folder_relative_to_snapshots_root": (
        "highest-temperature-in-toronto-on-june-15-2026"
    ),
    "target_date": "2026-06-15",
    "market_id": "toronto",
    "snapshot_id": "20260615T104352-0400",
    "canonical_replay_record_sha256": (
        "6f4b3c2523f4af5636f92b7b11a892194637459abac4869ad8f00243aede36fe"
    ),
}
EXPECTED_MISMATCHES = [
    {
        "variant": "wu_history",
        "split": "tune",
        "sealed_supported_snapshot_count": 19653,
        "pre_fix_runtime_supported_snapshot_count": 19654,
        "sealed_supported_snapshot_units_sha256": (
            "022405a03bf734b1bc3330858c482b4433007cc047b7742903d8b684f8d0519a"
        ),
        "pre_fix_runtime_supported_snapshot_units_sha256": (
            "23254fea4f6c2df7f1b6507555a49808ee8656c05f24f8f62e49a84bc9a99dcf"
        ),
    },
    {
        "variant": "eccc_swob",
        "split": "tune",
        "sealed_supported_snapshot_count": 2262,
        "pre_fix_runtime_supported_snapshot_count": 2263,
        "sealed_supported_snapshot_units_sha256": (
            "1002c65c64b0f85ab17849936eede3ef190f62ea63b37d127b3e1c73aecba68f"
        ),
        "pre_fix_runtime_supported_snapshot_units_sha256": (
            "ab6e72658268aa21e324883b2bc023efb5bba4c2b42fe55b3e6e06873f1fda22"
        ),
    },
]
EXPECTED_CORRECTION = {
    "rule_id": "post_model_target_date_match_false_is_not_usable",
    "semantics": (
        "A nonempty model-filtered source wrapper with target_date_match=false "
        "is unusable source support."
    ),
    "support_units_changed": False,
    "treatments_changed": False,
    "inference_changed": False,
    "affected_unit": EXPECTED_AFFECTED_UNIT,
    "pre_fix_mismatches": EXPECTED_MISMATCHES,
    "group_variant_mismatch_count": 0,
    "model_target_date_mismatch_count": 0,
}
EXPECTED_PARITY_COUNTERS = {
    "support_builder_mismatch_count": 0,
    "corrected_runtime_mismatch_count": 0,
    "replay_receipt_mismatch_count": 0,
    "pinned_selection_mismatch_count": 0,
}
EXPECTED_FAILED_ATTEMPT = {
    "generation_leaf": FAILED_GENERATION_LEAF,
    "complete_present": False,
    "generation_dir_present": False,
    "temporary_leaf_count": 0,
    "terminal_error": (
        "runtime support differs from seal for "
        "wu_history/tune/supported_snapshot_count"
    ),
}
EXPECTED_RETRY = {
    "generation_leaf": RETRY_GENERATION_LEAF,
    "producer_profile": PRODUCER_PROFILE,
}


class RuntimeSupportCorrectionError(ValueError):
    """The runtime-support correction is incomplete or has drifted."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _exact_keys(value: object, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        observed = sorted(value) if isinstance(value, Mapping) else type(value).__name__
        raise RuntimeSupportCorrectionError(
            f"{label} keys differ: expected={sorted(expected)}, observed={observed}"
        )
    return value


def stable_file_receipt(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve(strict=True)
    before_link = resolved.lstat()
    before = resolved.stat()
    is_reparse = bool(int(getattr(before_link, "st_file_attributes", 0)) & 0x400)
    if (
        resolved.is_symlink()
        or is_reparse
        or not stat_module.S_ISREG(before.st_mode)
        or int(before.st_nlink) != 1
    ):
        raise RuntimeSupportCorrectionError(
            f"correction input is not one regular file: {resolved}"
        )
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        opened_before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        opened_after = os.fstat(handle.fileno())
    after = resolved.stat()

    def identity(value):
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_nlink),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
        )

    if not (
        identity(before)
        == identity(opened_before)
        == identity(opened_after)
        == identity(after)
    ):
        raise RuntimeSupportCorrectionError(
            f"correction input changed while hashing: {resolved}"
        )
    return {
        "path": str(resolved),
        "sha256": digest.hexdigest(),
        "size_bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
    }


def expected_support_pairs(support: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = support.get("variants") or []
    if [str(row.get("variant") or "") for row in rows] != list(ALL_VARIANTS):
        raise RuntimeSupportCorrectionError(
            "support seal does not contain the exact ordered variant family"
        )
    output = []
    for row in rows:
        variant = str(row["variant"])
        splits = row.get("splits") or {}
        for split in PAIR_SPLITS:
            details = splits.get(split) or {}
            output.append(
                {
                    "variant": variant,
                    "split": split,
                    "supported_snapshot_count": int(
                        details["supported_snapshot_count"]
                    ),
                    "supported_snapshot_units_sha256": str(
                        details["supported_snapshot_units_sha256"]
                    ),
                }
            )
    return output


def support_pairs_sha256(pairs: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_bytes(pairs)).hexdigest()


def validate_runtime_support_correction(
    payload: Mapping[str, Any],
    *,
    repo_root: str | Path,
    support: Mapping[str, Any],
    predecessor_hashes: Mapping[str, Any],
    generation_dir: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    generation = Path(generation_dir).expanduser().absolute()
    top = _exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "research_only",
            "serving_or_release_authorization",
            "outcome_use",
            "predecessors",
            "helper",
            "correction",
            "all_44_parity",
            "failed_attempt",
            "retry",
        },
        "correction seal",
    )
    if (
        top["schema_version"] != CORRECTION_SCHEMA_VERSION
        or top["status"] != CORRECTION_STATUS
        or top["research_only"] is not True
        or top["serving_or_release_authorization"] is not False
    ):
        raise RuntimeSupportCorrectionError(
            "correction schema, status, or research-only authorization differs"
        )
    outcome = _exact_keys(
        top["outcome_use"], set(EXPECTED_OUTCOME_USE), "outcome_use"
    )
    if dict(outcome) != EXPECTED_OUTCOME_USE:
        raise RuntimeSupportCorrectionError("correction is not outcome-firewalled")

    predecessors = _exact_keys(
        top["predecessors"], set(predecessor_hashes), "predecessors"
    )
    if dict(predecessors) != dict(predecessor_hashes):
        raise RuntimeSupportCorrectionError("correction predecessor binding differs")

    helper = _exact_keys(
        top["helper"],
        {"relative_path", "pre_fix_sha256", "sha256", "size_bytes"},
        "helper",
    )
    if (
        helper["relative_path"] != HELPER_RELATIVE_PATH.as_posix()
        or helper["pre_fix_sha256"] != PRE_FIX_HELPER_SHA256
    ):
        raise RuntimeSupportCorrectionError("correction helper identity differs")
    helper_path = (root / HELPER_RELATIVE_PATH).resolve(strict=True)
    try:
        helper_path.relative_to(root)
    except ValueError as exc:
        raise RuntimeSupportCorrectionError("correction helper escapes repository") from exc
    helper_receipt = stable_file_receipt(helper_path)
    if (
        helper_receipt["sha256"] != helper["sha256"]
        or helper_receipt["size_bytes"] != helper["size_bytes"]
    ):
        raise RuntimeSupportCorrectionError("live correction helper differs from seal")

    correction = _exact_keys(
        top["correction"], set(EXPECTED_CORRECTION), "correction"
    )
    if dict(correction) != EXPECTED_CORRECTION:
        raise RuntimeSupportCorrectionError("correction diagnosis differs")

    expected_pairs = expected_support_pairs(support)
    parity = _exact_keys(
        top["all_44_parity"],
        {"schema_version", "order", "pair_count", "pairs_sha256", "pairs", "counters"},
        "all_44_parity",
    )
    if (
        parity["schema_version"] != PARITY_SCHEMA_VERSION
        or parity["order"]
        != "ALL_VARIANTS order, then tune and holdout for each variant"
        or parity["pair_count"] != len(expected_pairs)
        or parity["pair_count"] != 44
        or parity["pairs"] != expected_pairs
        or parity["pairs_sha256"] != support_pairs_sha256(expected_pairs)
    ):
        raise RuntimeSupportCorrectionError("all-44 parity proof differs from support v5")
    counters = _exact_keys(
        parity["counters"], set(EXPECTED_PARITY_COUNTERS), "parity counters"
    )
    if dict(counters) != EXPECTED_PARITY_COUNTERS:
        raise RuntimeSupportCorrectionError("all-44 parity counters are not exact zero")

    failed = _exact_keys(
        top["failed_attempt"], set(EXPECTED_FAILED_ATTEMPT), "failed_attempt"
    )
    if dict(failed) != EXPECTED_FAILED_ATTEMPT:
        raise RuntimeSupportCorrectionError("failed-attempt record differs")
    retry = _exact_keys(top["retry"], set(EXPECTED_RETRY), "retry")
    if dict(retry) != EXPECTED_RETRY or generation.name != RETRY_GENERATION_LEAF:
        raise RuntimeSupportCorrectionError("retry generation identity differs")
    failed_path = generation.with_name(FAILED_GENERATION_LEAF)
    if failed_path.exists():
        raise RuntimeSupportCorrectionError("failed generation-001 leaf now exists")
    temporary = list(
        generation.parent.glob(f".{FAILED_GENERATION_LEAF}.tmp-*")
    ) if generation.parent.exists() else []
    if temporary:
        raise RuntimeSupportCorrectionError("failed generation-001 temporary leaves exist")
    return {
        "helper_path": helper_path,
        "helper_receipt": helper_receipt,
        "pairs": expected_pairs,
        "pairs_sha256": support_pairs_sha256(expected_pairs),
        "failed_generation_path": failed_path,
    }
